"""Persistent library and one knowledge service, using the existing ingestion/RAG core."""
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

from app.ingestion.parsers import build_default_registry
from app.ingestion.chunking import ChunkerConfig
from app.indexing.store import build_index_version, load_active_pointer
from app.retrieval.snapshot import V2IndexSnapshot
from app.retrieval.navigation import DocumentNavigator
from app.retrieval.pipeline import HybridRetrievalPipeline
from app.agent.tools_v2 import V2ToolRegistry
from app.agent.runner_v2 import V2AgentRunner
from app.agent.generation_v2 import GenerationV2ResponseBuilder
from app.domain.agent import AgentBudget
from app.domain.queries import UserContext


def identifier(prefix): return prefix+'_'+uuid.uuid4().hex[:16]


class Library:
    def __init__(self, workspace):
        self.workspace = workspace
        self.running = set()
        self.closing = False
        self.lock = asyncio.Lock()
        self.snapshots = {}
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS knowledge_bases(id TEXT PRIMARY KEY,name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS library_documents(id TEXT PRIMARY KEY,kb_id TEXT,name TEXT,
                    version INTEGER,sha256 TEXT,path TEXT,parsed TEXT,status TEXT,error TEXT,active INTEGER DEFAULT 1);
                CREATE TABLE IF NOT EXISTS library_jobs(id TEXT PRIMARY KEY,kb_id TEXT,status TEXT,error TEXT,
                    generation TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,kb_id TEXT);
                CREATE TABLE IF NOT EXISTS knowledge_answers(id TEXT PRIMARY KEY,conversation_id TEXT,kb_id TEXT,
                    question TEXT,result_json TEXT,generation TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS directory_sources(id TEXT PRIMARY KEY,kb_id TEXT,path TEXT,last_scan TEXT);
                CREATE TABLE IF NOT EXISTS directory_entries(source_id TEXT,relative_path TEXT,sha256 TEXT,doc_id TEXT,status TEXT,
                    PRIMARY KEY(source_id,relative_path));
                CREATE TABLE IF NOT EXISTS product_feedback(id TEXT PRIMARY KEY,target_kind TEXT,target_id TEXT,
                    category TEXT,message TEXT,snapshot TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            """)
            if 'metrics' not in {r[1] for r in db.execute('PRAGMA table_info(library_jobs)')}:
                db.execute('ALTER TABLE library_jobs ADD COLUMN metrics TEXT')
            if 'source_key' not in {r[1] for r in db.execute('PRAGMA table_info(library_documents)')}:
                db.execute('ALTER TABLE library_documents ADD COLUMN source_key TEXT')

    def db(self):
        db = sqlite3.connect(self.workspace.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    async def start(self):
        with self.db() as db:
            db.execute("UPDATE library_jobs SET status='INTERRUPTED',error='Process stopped before completion; retry required' WHERE status='RUNNING'")
            pending = db.execute("SELECT id,kb_id FROM library_jobs WHERE status='QUEUED'").fetchall()
        for job in pending: self.schedule(job['id'], job['kb_id'])

    async def close(self):
        self.closing = True
        for task in self.running: task.cancel()
        await asyncio.gather(*self.running, return_exceptions=True)

    def list(self):
        with self.db() as db:
            return {'bases':[dict(r) for r in db.execute('SELECT * FROM knowledge_bases')],
                    'documents':[dict(r) for r in db.execute('SELECT id,kb_id,name,version,status,error,active FROM library_documents')],
                    'jobs':[dict(r) for r in db.execute('SELECT * FROM library_jobs ORDER BY created_at DESC LIMIT 30')],
                    'directory_sources':[dict(r) for r in db.execute('SELECT * FROM directory_sources')]}

    def create(self, name):
        kb_id = identifier('kb')
        with self.db() as db: db.execute('INSERT INTO knowledge_bases VALUES(?,?)', (kb_id,name))
        return {'id':kb_id,'name':name}

    def require(self, kb_id):
        with self.db() as db:
            if not db.execute('SELECT 1 FROM knowledge_bases WHERE id=?',(kb_id,)).fetchone():
                raise ValueError('KNOWLEDGE_BASE_NOT_FOUND')

    async def upload(self, kb_id, name, content, *, source_key=None):
        self.require(kb_id)
        name = Path(name).name
        suffix = Path(name).suffix.lower()
        if suffix not in {'.txt','.md','.pdf','.docx'}: raise ValueError('UNSUPPORTED_DOCUMENT_TYPE')
        if not content or len(content)>20*1024*1024: raise ValueError('DOCUMENT_SIZE_LIMIT')
        digest = hashlib.sha256(content).hexdigest()
        with self.db() as db:
            old = db.execute('SELECT * FROM library_documents WHERE kb_id=? AND COALESCE(source_key,name)=? AND active=1',(kb_id,source_key or name)).fetchone()
            if old and old['sha256']==digest and old['status']!='FAILED':
                if old['status']=='SOURCE_MISSING':
                    db.execute("UPDATE library_documents SET status='PARSED',error=NULL WHERE id=?",(old['id'],))
                    return {**dict(old),'status':'PARSED','error':None}
                return dict(old)
        doc_id = identifier('doc')
        folder = self.workspace.root/'documents'/kb_id
        folder.mkdir(parents=True,exist_ok=True)
        path = folder/(doc_id+suffix)
        path.write_bytes(content)
        error = None; parsed = None
        try:
            parsed = await asyncio.to_thread(build_default_registry().parse,path)
            if not parsed.text.strip(): raise ValueError('No readable text; OCR is not available')
        except Exception as exc: error = type(exc).__name__+': '+str(exc)
        with self.db() as db:
            # Failed replacement does not retire the working document.
            if old and not error: db.execute('UPDATE library_documents SET active=0 WHERE id=?',(old['id'],))
            db.execute('INSERT INTO library_documents(id,kb_id,name,version,sha256,path,parsed,status,error,active,source_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (doc_id,kb_id,name,old['version']+1 if old else 1,digest,str(path),
                        parsed.model_dump_json() if parsed else None,'FAILED' if error else 'PARSED',error,0 if error else 1,source_key))
        return {'id':doc_id,'name':name,'status':'FAILED' if error else 'PARSED','error':error,
                'preview':parsed.text[:1200] if parsed else ''}

    def register_directory(self,kb_id,path):
        from app.ingestion.path_security import absolute_path_has_redirect
        self.require(kb_id);folder=Path(path).expanduser().absolute()
        if folder.drive.startswith('\\\\') or not folder.is_dir() or folder==Path(folder.anchor) or absolute_path_has_redirect(folder):
            raise ValueError('SELECT_A_REAL_DOCUMENT_DIRECTORY_NOT_A_DRIVE_OR_REDIRECT')
        with self.db() as db:
            row=db.execute('SELECT * FROM directory_sources WHERE kb_id=? AND path=?',(kb_id,str(folder))).fetchone()
            if row:return dict(row)
            source_id=identifier('directory')
            db.execute('INSERT INTO directory_sources VALUES(?,?,?,NULL)',(source_id,kb_id,str(folder)))
        return {'id':source_id,'kb_id':kb_id,'path':str(folder),'last_scan':None}

    async def sync_directory(self,source_id):
        from app.ingestion.path_security import stat_is_redirect, absolute_path_has_redirect
        with self.db() as db:
            source=db.execute('SELECT * FROM directory_sources WHERE id=?',(source_id,)).fetchone()
            previous={r['relative_path']:dict(r) for r in db.execute('SELECT * FROM directory_entries WHERE source_id=?',(source_id,))}
        if not source:raise ValueError('SOURCE_NOT_FOUND')
        folder=Path(source['path'])
        if not folder.is_dir() or absolute_path_has_redirect(folder):raise ValueError('SOURCE_DIRECTORY_UNAVAILABLE')
        def files():
            selected=[];total=0
            for parent,dirs,names in os.walk(folder,followlinks=False):
                dirs[:]=[d for d in dirs if not d.startswith('.') and not stat_is_redirect((Path(parent)/d).lstat())]
                for name in sorted(names):
                    p=Path(parent)/name
                    if p.suffix.lower() not in {'.txt','.md','.pdf','.docx'} or stat_is_redirect(p.lstat()):continue
                    if p.stat().st_size>20*1024*1024:raise ValueError('DOCUMENT_SIZE_LIMIT: '+name)
                    total+=p.stat().st_size
                    if total>64*1024*1024:raise ValueError('DIRECTORY_TOTAL_LIMIT_64_MB')
                    selected.append((p.relative_to(folder).as_posix(),p.read_bytes()))
                    if len(selected)>500:raise ValueError('DIRECTORY_FILE_LIMIT_500')
            return selected
        selected=await asyncio.to_thread(files)
        report={'source_id':source_id,'added':[],'replaced':[],'unchanged':[],'missing':[],'failed':[]}
        present=set()
        for relative,content in selected:
            present.add(relative);sha=hashlib.sha256(content).hexdigest();old=previous.get(relative)
            if old and old['sha256']==sha and old['status']=='PRESENT':
                report['unchanged'].append(relative);continue
            doc=await self.upload(source['kb_id'],Path(relative).name,content,source_key=source_id+'/'+relative)
            if doc['status']=='FAILED':report['failed'].append({'path':relative,'error':doc['error']});continue
            with self.db() as db:
                db.execute('INSERT OR REPLACE INTO directory_entries VALUES(?,?,?,?,?)',(source_id,relative,sha,doc['id'],'PRESENT'))
            report['replaced' if old else 'added'].append(relative)
        for relative,old in previous.items():
            if relative in present:continue
            report['missing'].append(relative)
            with self.db() as db:
                db.execute("UPDATE directory_entries SET status='MISSING' WHERE source_id=? AND relative_path=?",(source_id,relative))
                db.execute("UPDATE library_documents SET status='SOURCE_MISSING',error='Source file missing; last imported immutable version retained' WHERE id=?",(old['doc_id'],))
        with self.db() as db:db.execute('UPDATE directory_sources SET last_scan=CURRENT_TIMESTAMP WHERE id=?',(source_id,))
        return report

    def feedback(self,target_kind,target_id,category,message):
        with self.db() as db:
            if target_kind=='answer':row=db.execute('SELECT * FROM knowledge_answers WHERE id=?',(target_id,)).fetchone()
            elif target_kind=='task':row=db.execute('SELECT * FROM agent_tasks WHERE task_id=?',(target_id,)).fetchone()
            else:raise ValueError('INVALID_FEEDBACK_TARGET')
            if not row:raise ValueError('FEEDBACK_TARGET_NOT_FOUND')
            feedback_id=identifier('feedback')
            db.execute('INSERT INTO product_feedback(id,target_kind,target_id,category,message,snapshot) VALUES(?,?,?,?,?,?)',
                (feedback_id,target_kind,target_id,category,message,json.dumps(dict(row),ensure_ascii=False)))
        return {'id':feedback_id,'status':'RECORDED','message':'已保存复现上下文；不会自动运行模型或声称问题已修复'}

    def enqueue(self, kb_id):
        self.require(kb_id)
        with self.db() as db:
            old = db.execute("SELECT id FROM library_jobs WHERE kb_id=? AND status IN ('QUEUED','RUNNING')",(kb_id,)).fetchone()
            if old: return {'id':old['id'],'status':'QUEUED_OR_RUNNING'}
            job_id = identifier('job')
            db.execute("INSERT INTO library_jobs(id,kb_id,status) VALUES(?,?,'QUEUED')",(job_id,kb_id))
        self.schedule(job_id,kb_id)
        return {'id':job_id,'status':'QUEUED'}

    def schedule(self, job_id, kb_id):
        task = asyncio.create_task(self.build(job_id,kb_id))
        self.running.add(task); task.add_done_callback(self.running.discard)

    async def build(self, job_id, kb_id):
        async with self.lock:
            with self.db() as db: db.execute("UPDATE library_jobs SET status='RUNNING' WHERE id=?",(job_id,))
            try:
                loop = asyncio.get_running_loop()
                with self.db() as db:
                    if not db.execute("SELECT 1 FROM library_documents WHERE kb_id=? AND active=1 AND status!='FAILED'",(kb_id,)).fetchone():
                        raise ValueError('NO_PARSED_DOCUMENTS')
                model_digest=await self.workspace.models.embedding_identity()
                result,document_ids,metrics = await asyncio.to_thread(self._build,job_id,kb_id,
                    self.workspace.models.sync_embed(loop,purpose='index_embedding'),model_digest)
                if self.closing: raise asyncio.CancelledError()
                with self.db() as db:
                    current={r[0] for r in db.execute("SELECT id FROM library_documents WHERE kb_id=? AND active=1 AND status!='FAILED'",(kb_id,))}
                if current!=set(document_ids):raise ValueError('LIBRARY_CHANGED_RETRY')
                from app.indexing.store import activate_version
                await asyncio.to_thread(activate_version,self.workspace.root/'indexes'/kb_id,result.run_id)
                with self.db() as db:
                    db.execute("UPDATE library_jobs SET status='SUCCEEDED',generation=?,metrics=? WHERE id=?",(result.run_id,json.dumps(metrics),job_id))
                self.snapshots.pop(kb_id,None)
            except BaseException as exc:
                with self.db() as db:
                    db.execute("UPDATE library_jobs SET status=?,error=? WHERE id=?",('INTERRUPTED' if isinstance(exc,asyncio.CancelledError) else 'FAILED',type(exc).__name__+': '+str(exc),job_id))
                if isinstance(exc,asyncio.CancelledError): raise

    def _build(self, job_id, kb_id, embed,model_digest):
        with self.db() as db:
            documents = db.execute("SELECT * FROM library_documents WHERE kb_id=? AND active=1 AND status!='FAILED'",(kb_id,)).fetchall()
        if not documents: raise ValueError('NO_PARSED_DOCUMENTS')
        source = self.workspace.root/'documents'/kb_id/'builds'/job_id
        source.mkdir(parents=True,exist_ok=False)
        manifest_docs = []
        for doc in documents:
            # Use parsed text for all supported formats; original stays immutable for opening.
            text = json.loads(doc['parsed'])['text']; content = ('# '+doc['name']+'\n\n'+text).encode('utf8')
            relative = doc['id']+'.md'; (source/relative).write_bytes(content)
            metadata = {'policy_id':hashlib.sha256((doc['source_key'] or doc['name']).encode()).hexdigest()[:20],
                        'version_id':doc['id'],'version':str(doc['version']),'status':'active',
                        'effective_from':'2000-01-01','authority':100,'actual_department':'local',
                        'filed_department':'local','tenant':'local','region':'local','acl_groups':['local-owner'],
                        'variant':'authoritative'}
            manifest_docs.append({'doc_id':doc['id'],'path':relative,'sha256':hashlib.sha256(content).hexdigest(),
                'byte_count':len(content),'format':'md','source_type':'policy','variant':'authoritative',
                'metadata':metadata,'fact_ids':[]})
        manifest = {'schema_version':'enterprise_corpus_manifest_v1','producer':'enterprise_agentic_rag_v2',
            'generator_version':'workbench-1','profile_id':kb_id,'seed':0,'facts_sha256':'0'*64,'profile_sha256':'0'*64,
            'document_count':len(documents),'counts_by_format':{'md':len(documents)},
            'counts_by_source_type':{'policy':len(documents)},'counts_by_variant':{'authoritative':len(documents)},
            'documents':manifest_docs}
        (source/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf8')
        from app.indexing.workbench_cache import CachedChunkEmbeddings
        chunker=ChunkerConfig(mode='heading',chunk_size=1000,overlap=100)
        embeddings=CachedChunkEmbeddings(self.workspace,model_digest,embed,chunker)
        result=build_index_version(root=self.workspace.root/'indexes'/kb_id,input_dir=source,run_id=job_id,
            chunker_config=chunker,embedding_model=self.workspace.config.embedding_model,
            embed_chunks=embeddings,activate=False)
        return result,[d['id'] for d in documents],{'embedding_hits':embeddings.hits,'embedding_misses':embeddings.misses,
            'canonical_documents':len(documents),'chunks':result.indexed_chunk_count}

    def snapshot(self,kb_id):
        self.require(kb_id)
        root = self.workspace.root/'indexes'/kb_id
        pointer = load_active_pointer(root)
        cached = self.snapshots.get(kb_id)
        if not cached or cached.version.manifest.run_id!=pointer.run_id:
            cached = V2IndexSnapshot.load(root,pointer.run_id);self.snapshots[kb_id]=cached
        return cached

    async def answer(self, kb_id, question, *, conversation_id=None, detailed=False):
        loop = asyncio.get_running_loop()
        snapshot = await asyncio.to_thread(self.snapshot,kb_id)
        def generate():
            pipeline = HybridRetrievalPipeline(snapshot,embed_text=self.workspace.models.sync_embed(loop))
            runner = V2AgentRunner(registry=V2ToolRegistry(DocumentNavigator(snapshot,pipeline=pipeline)),
                response_builder=GenerationV2ResponseBuilder(model=self.workspace.config.chat_model,
                    chat_fn=self.workspace.models.sync_chat(loop),max_attempts=1),
                budget=AgentBudget(deadline_ms=240000,max_search_calls=3 if detailed else 2,max_open_calls=4 if detailed else 2))
            user = UserContext(user_id='local-owner',tenant_id='local',region='local',groups=['local-owner'])
            return runner.run(question,user,top_k=6)
        result = await asyncio.to_thread(generate)
        answer_id = identifier('answer'); conversation_id = conversation_id or identifier('conversation')
        with self.db() as db:
            if db.execute('SELECT 1 FROM conversations WHERE id=? AND kb_id!=?',(conversation_id,kb_id)).fetchone():
                raise ValueError('CONVERSATION_KNOWLEDGE_BASE_MISMATCH')
            db.execute('INSERT OR IGNORE INTO conversations VALUES(?,?)',(conversation_id,kb_id))
            db.execute('INSERT INTO knowledge_answers(id,conversation_id,kb_id,question,result_json,generation) VALUES(?,?,?,?,?,?)',
                       (answer_id,conversation_id,kb_id,question,result.model_dump_json(),snapshot.version.manifest.run_id))
        return {'id':answer_id,'conversation_id':conversation_id,'result':result.model_dump(mode='json')}

    def answers(self):
        with self.db() as db:
            return [{**{k:r[k] for k in r.keys() if k!='result_json'},'result':json.loads(r['result_json'])} for r in db.execute(
                'SELECT * FROM knowledge_answers ORDER BY created_at DESC LIMIT 50')]
