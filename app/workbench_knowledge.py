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
            if 'context_answer_ids' not in {r[1] for r in db.execute('PRAGMA table_info(knowledge_answers)')}:
                db.execute("ALTER TABLE knowledge_answers ADD COLUMN context_answer_ids TEXT NOT NULL DEFAULT '[]'")
            if 'metadata' not in {r[1] for r in db.execute('PRAGMA table_info(library_documents)')}:
                db.execute("ALTER TABLE library_documents ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
            db.execute('UPDATE library_documents SET source_key=name WHERE source_key IS NULL')

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
                    'documents':[{**dict(r),'metadata':json.loads(r['metadata'])} for r in db.execute('SELECT id,kb_id,name,source_key,version,status,error,active,metadata FROM library_documents')],
                    'jobs':[dict(r) for r in db.execute('SELECT * FROM library_jobs ORDER BY created_at DESC LIMIT 30')],
                    'directory_sources':[dict(r) for r in db.execute('SELECT * FROM directory_sources')]}

    def create(self, name):
        kb_id = identifier('kb')
        with self.db() as db: db.execute('INSERT INTO knowledge_bases VALUES(?,?)', (kb_id,name))
        return {'id':kb_id,'name':name}

    async def import_samples(self,kb_id):
        if not self.workspace.config.sample_data:raise ValueError('SYNTHETIC_SAMPLE_MODE_REQUIRED')
        from app.service_desk.rule_documents import sample_documents
        from app.workbench_service import local_actor
        documents=[]
        for sample in sample_documents(self.workspace.service.store,local_actor()):
            doc=await self.upload(kb_id,sample['name'],sample['content'].encode('utf8'))
            if doc['status']!='PARSED':raise ValueError('SAMPLE_PARSE_FAILED')
            metadata={'source_type':'policy' if sample['rule_binding'] else 'wiki',
                'service_tags':sample['service_tags'],'rule_binding':sample['rule_binding'],'effective_from':None}
            with self.db() as db:db.execute('UPDATE library_documents SET metadata=? WHERE id=?',(json.dumps(metadata),doc['id']))
            documents.append(doc)
        return {'documents':documents,'origin':'SYNTHETIC_RULE_BACKED_SAMPLE','index_update_required':True}

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
                        parsed.model_dump_json() if parsed else None,'FAILED' if error else 'PARSED',error,0 if error else 1,source_key or name))
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

    def update_document(self,doc_id,changes):
        if 'active' in changes and changes['active'] is None:raise ValueError('ACTIVE_MUST_BE_BOOLEAN')
        with self.db() as db:
            row=db.execute('SELECT * FROM library_documents WHERE id=?',(doc_id,)).fetchone()
            if not row:raise ValueError('DOCUMENT_NOT_FOUND')
            if changes.get('active') and not row['parsed']:raise ValueError('DOCUMENT_REQUIRES_SUCCESSFUL_PARSE')
            metadata=json.loads(row['metadata'])
            for key in ('source_type','effective_from','service_tags'):
                if key in changes:metadata[key]=changes[key]
            if changes.get('active'):
                db.execute('UPDATE library_documents SET active=0 WHERE kb_id=? AND source_key=?',(row['kb_id'],row['source_key']))
            db.execute('UPDATE library_documents SET name=?,active=?,metadata=? WHERE id=?',
                (changes.get('name') or row['name'],int(changes.get('active',bool(row['active']))),json.dumps(metadata,ensure_ascii=False),doc_id))
        self.snapshots.pop(row['kb_id'],None)
        return {'id':doc_id,'name':changes.get('name') or row['name'],'active':changes.get('active',bool(row['active'])),'metadata':metadata,
            'index_update_required':bool(set(changes)-{'name'})}

    async def retry_document(self,doc_id):
        with self.db() as db:row=db.execute('SELECT * FROM library_documents WHERE id=?',(doc_id,)).fetchone()
        if not row:raise ValueError('DOCUMENT_NOT_FOUND')
        content=Path(row['path']).read_bytes()
        if hashlib.sha256(content).hexdigest()!=row['sha256']:raise ValueError('IMMUTABLE_SOURCE_CHANGED')
        parsed=await asyncio.to_thread(build_default_registry().parse,Path(row['path']))
        if not parsed.text.strip():raise ValueError('NO_READABLE_TEXT_NO_OCR')
        with self.db() as db:
            db.execute('UPDATE library_documents SET active=0 WHERE kb_id=? AND source_key=?',(row['kb_id'],row['source_key']))
            db.execute("UPDATE library_documents SET parsed=?,status='PARSED',error=NULL,active=1 WHERE id=?",(parsed.model_dump_json(),doc_id))
        self.snapshots.pop(row['kb_id'],None)
        return {'id':doc_id,'status':'PARSED','index_update_required':True}

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

    def feedbacks(self):
        with self.db() as db:return [dict(r) for r in db.execute('SELECT id,target_kind,target_id,category,message,created_at FROM product_feedback ORDER BY rowid DESC LIMIT 30')]

    def feedback_case(self,feedback_id):
        with self.db() as db:row=db.execute('SELECT * FROM product_feedback WHERE id=?',(feedback_id,)).fetchone()
        if not row:raise ValueError('FEEDBACK_NOT_FOUND')
        snapshot=json.loads(row['snapshot'])
        if row['target_kind']=='answer':
            input={'question':snapshot['question'],'kb_id':snapshot['kb_id'],'generation':snapshot['generation'],
                   'conversation_id':snapshot['conversation_id']}
            observed=json.loads(snapshot['result_json'])
        else:
            task=json.loads(snapshot['payload']);input={key:task.get(key) for key in ('guided_request','facts','messages','user_execution_ceiling')}
            observed={key:task.get(key) for key in ('observations','outcome','receipt','last_error','status')}
        return {'id':row['id'],'kind':'UNREVIEWED_REGRESSION_CANDIDATE_NOT_AN_EXPECTED_ANSWER',
                'category':row['category'],'report':row['message'],'input':input,'observed':observed,
                'expected':None,'required_review':'根据原始用户要求、当时来源或实际业务库人工制定expected；未审，不自动启动模型或提交。'}

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
                    metadata_now={r['id']:json.loads(r['metadata']) for r in db.execute("SELECT id,metadata FROM library_documents WHERE kb_id=? AND active=1 AND status!='FAILED'",(kb_id,))}
                if current!=set(document_ids) or metadata_now!=metrics['document_metadata']:raise ValueError('LIBRARY_CHANGED_RETRY')
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
        manifest_docs = [];parses={}
        for doc in documents:
            # Feed the original parse to the existing publisher. Re-parsing an
            # artificial Markdown wrapper destroyed PDF/Word source locations.
            content=Path(doc['path']).read_bytes();kind=Path(doc['path']).suffix.lstrip('.')
            relative=doc['id']+'.'+kind;(source/relative).write_bytes(content)
            parses[relative]=json.loads(doc['parsed']);details=json.loads(doc['metadata'])
            metadata = {'policy_id':hashlib.sha256((doc['source_key'] or doc['name']).encode()).hexdigest()[:20],
                        'version_id':doc['id'],'version':str(doc['version']),'status':'active',
                        'effective_from':details.get('effective_from') or date.today().isoformat(),'authority':100,'actual_department':'local',
                        'filed_department':'local','tenant':'local','region':'local','acl_groups':['local-owner'],
                        'variant':'authoritative'}
            manifest_docs.append({'doc_id':doc['id'],'path':relative,'sha256':doc['sha256'],
                'byte_count':len(content),'format':kind,'source_type':details.get('source_type') or 'wiki','variant':'authoritative',
                'metadata':metadata,'fact_ids':[]})
        manifest = {'schema_version':'enterprise_corpus_manifest_v1','producer':'enterprise_agentic_rag_v2',
            'generator_version':'workbench-1','profile_id':kb_id,'seed':0,'facts_sha256':'0'*64,'profile_sha256':'0'*64,
            'document_count':len(documents),'counts_by_format':dict(Counter(d['format'] for d in manifest_docs)),
            'counts_by_source_type':dict(Counter(d['source_type'] for d in manifest_docs)),'counts_by_variant':{'authoritative':len(documents)},
            'documents':manifest_docs}
        (source/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf8')
        from app.indexing.workbench_cache import CachedChunkEmbeddings
        chunker=ChunkerConfig(mode='heading',chunk_size=1000,overlap=100)
        embeddings=CachedChunkEmbeddings(self.workspace,model_digest,embed,chunker)
        from app.ingestion.saved_parses import SavedParseRegistry
        result=build_index_version(root=self.workspace.root/'indexes'/kb_id,input_dir=source,run_id=job_id,
            chunker_config=chunker,embedding_model=self.workspace.config.embedding_model,
            embed_chunks=embeddings,activate=False,registry=SavedParseRegistry(parses))
        return result,[d['id'] for d in documents],{'embedding_hits':embeddings.hits,'embedding_misses':embeddings.misses,
            'canonical_documents':len(documents),'chunks':result.indexed_chunk_count,
            'document_metadata':{d['id']:json.loads(d['metadata']) for d in documents}}

    def snapshot(self,kb_id):
        self.require(kb_id)
        root = self.workspace.root/'indexes'/kb_id
        pointer = load_active_pointer(root)
        cached = self.snapshots.get(kb_id)
        if not cached or cached.version.manifest.run_id!=pointer.run_id:
            cached = V2IndexSnapshot.load(root,pointer.run_id);self.snapshots[kb_id]=cached
        if cached.version.manifest.embedding.model.removesuffix(':latest')!=self.workspace.config.embedding_model.removesuffix(':latest'):
            raise ValueError('INDEX_EMBEDDING_MODEL_CHANGED: 查询模型与索引不匹配，请用当前嵌入模型更新索引')
        with self.db() as db:
            current={r[0] for r in db.execute('SELECT id FROM library_documents WHERE kb_id=? AND active=1 AND parsed IS NOT NULL',(kb_id,))}
            job=db.execute('SELECT status,metrics FROM library_jobs WHERE id=?',(pointer.run_id,)).fetchone()
            metadata_now={r['id']:json.loads(r['metadata']) for r in db.execute('SELECT id,metadata FROM library_documents WHERE kb_id=? AND active=1 AND parsed IS NOT NULL',(kb_id,))}
        if job:
            if job['status']!='SUCCEEDED':raise ValueError('INDEX_NOT_READY: 当前索引发布尚未完成，请稍后重试')
            old_metadata=json.loads(job['metrics'] or '{}').get('document_metadata')
            if old_metadata is not None and old_metadata!=metadata_now:raise ValueError('INDEX_OUTDATED: 资料元数据已变化，请更新索引')
        if current!=set(cached.documents_by_id):raise ValueError('INDEX_OUTDATED: 资料已变化，请更新索引后再提问；历史答案和版本仍保留')
        return cached

    def excerpt(self,doc_id,index_run_id,target_type,target_id):
        with self.db() as db:row=db.execute('SELECT * FROM library_documents WHERE id=?',(doc_id,)).fetchone()
        if not row:raise ValueError('DOCUMENT_NOT_FOUND')
        snapshot=self.snapshots.get(row['kb_id'])
        if not snapshot or snapshot.version.manifest.run_id!=index_run_id:
            snapshot=V2IndexSnapshot.load(self.workspace.root/'indexes'/row['kb_id'],index_run_id)
        if target_type=='document':resource=snapshot.documents_by_id.get(doc_id) if target_id==doc_id else None
        else:
            resource=snapshot.all_chunks_by_id.get(target_id)
            if resource and target_type=='parent' and resource.kind!='parent':resource=None
        if not resource or resource.doc_id!=doc_id:raise ValueError('SOURCE_LOCATION_NOT_BOUND')
        spans=[s.model_dump(mode='json') for s in getattr(resource,'source_spans',[])]
        return {'document_id':doc_id,'name':row['name'],'version':row['version'],'active':bool(row['active']),
            'text':resource.text[:12000],'truncated':len(resource.text)>12000,'source_spans':spans,
            'location_basis':'original_parser' if spans else 'legacy_index_location_only',
            'index_metadata':{'format':snapshot.documents_by_id[doc_id].format,'source_type':snapshot.documents_by_id[doc_id].source_type},
            'current_metadata':json.loads(row['metadata'])}

    def source_notices(self,result):
        notices=[]
        with self.db() as db:
            for source in result.get('sources',[]):
                row=db.execute('SELECT name,version,status,active FROM library_documents WHERE id=?',(source['doc_id'],)).fetchone()
                if row and not row['active']:notices.append(f"{row['name']} v{row['version']}为回答当时的历史版本；当前资料已更新。")
                elif row and row['status']=='SOURCE_MISSING':notices.append(f"{row['name']}源文件缺失，依据最后导入的v{row['version']}；未从缺失文件重新读取。")
        return list(dict.fromkeys(notices))

    def conversation_context(self,kb_id,conversation_id):
        if not conversation_id:return []
        with self.db() as db:
            conversation=db.execute('SELECT kb_id FROM conversations WHERE id=?',(conversation_id,)).fetchone()
            if not conversation:raise ValueError('CONVERSATION_NOT_FOUND')
            if conversation['kb_id']!=kb_id:raise ValueError('CONVERSATION_KNOWLEDGE_BASE_MISMATCH')
            rows=db.execute('SELECT id,question FROM knowledge_answers WHERE conversation_id=? ORDER BY rowid DESC LIMIT 2',(conversation_id,)).fetchall()
        if any(len(row['question'])>500 for row in rows):
            raise ValueError('FOLLOWUP_CONTEXT_TOO_LARGE: 请用完整问题开始新话题；不会截断旧问题中的条件')
        return [dict(row) for row in reversed(rows)]

    async def answer(self, kb_id, question, *, conversation_id=None, detailed=False):
        context=self.conversation_context(kb_id,conversation_id)
        search='\n'.join([row['question'] for row in context]+[question])
        if context and len(search)>1000:raise ValueError('FOLLOWUP_QUERY_TOO_LARGE: 请用完整问题开始新话题')
        loop = asyncio.get_running_loop()
        snapshot = await asyncio.to_thread(self.snapshot,kb_id)
        deep_plan=None
        if detailed:
            from app.agent.deep_knowledge import plan_deep
            from app.agent.query_analysis import RuleFirstQueryAnalyzer
            check=RuleFirstQueryAnalyzer().analyze(question,UserContext(user_id='local-owner',tenant_id='local',region='local',groups=['local-owner']))
            if check.intent!='unsafe':deep_plan=await plan_deep(self.workspace.models,question,context)
        def generate():
            from app.agent.controller_v2 import V2AgentController
            from app.agent.query_analysis import RuleFirstQueryAnalyzer
            class ConversationAnalyzer:
                def analyze(self,original,user):
                    analysis=RuleFirstQueryAnalyzer().analyze(original,user)
                    if deep_plan and analysis.intent!='unsafe':
                        labels=[q.question for q in deep_plan.subquestions]
                        return analysis.model_copy(update={'intent':'comparison' if len(labels)>1 else 'fact',
                            'entities':labels if len(labels)>1 else [],'required_aspects':labels,
                            'search_queries':[q.query for q in deep_plan.subquestions],'source':'model'})
                    if not context or analysis.intent=='unsafe':return analysis
                    # Search may carry prior user referents. Obligations remain
                    # the current original question, never the old answer as fact.
                    return analysis.model_copy(update={'search_queries':[search]})
            pipeline = HybridRetrievalPipeline(snapshot,embed_text=self.workspace.models.sync_embed(loop))
            from app.agent.deep_knowledge import DeepController
            controller=DeepController(deep_plan) if deep_plan else V2AgentController(semantic_question=True)
            runner = V2AgentRunner(registry=V2ToolRegistry(DocumentNavigator(snapshot,pipeline=pipeline)),
                controller=controller,
                analyzer=ConversationAnalyzer(),
                response_builder=GenerationV2ResponseBuilder(model=self.workspace.config.chat_model,
                    chat_fn=self.workspace.models.sync_chat(loop),max_attempts=1),
                budget=AgentBudget(deadline_ms=240000,max_search_calls=6 if deep_plan else 2,
                    max_find_calls=4 if deep_plan else 2,max_open_calls=4 if deep_plan else 2,max_steps=18 if deep_plan else 12))
            user = UserContext(user_id='local-owner',tenant_id='local',region='local',groups=['local-owner'])
            result=runner.run(question,user,top_k=6,clarification_replies=[
                {'asked':'此前同一会话的用户问题，仅用于理解指代，不是知识证据','reply':row['question']} for row in context])
            return result.model_copy(update={'trace':{**result.trace,'knowledge_strategy':controller.report() if deep_plan else {'strategy':'fast_shared_runner'}}})
        result = await asyncio.to_thread(generate)
        with self.db() as db:names={r['id']:r['name'] for r in db.execute('SELECT id,name FROM library_documents WHERE kb_id=?',(kb_id,))}
        result=result.model_copy(update={'sources':[source.model_copy(update={'title':names.get(source.doc_id),
            'format':snapshot.documents_by_id[source.doc_id].format,'source_type':snapshot.documents_by_id[source.doc_id].source_type}) for source in result.sources]})
        answer_id = identifier('answer'); conversation_id = conversation_id or identifier('conversation')
        with self.db() as db:
            if db.execute('SELECT 1 FROM conversations WHERE id=? AND kb_id!=?',(conversation_id,kb_id)).fetchone():
                raise ValueError('CONVERSATION_KNOWLEDGE_BASE_MISMATCH')
            db.execute('INSERT OR IGNORE INTO conversations(id,kb_id) VALUES(?,?)',(conversation_id,kb_id))
            db.execute('INSERT INTO knowledge_answers(id,conversation_id,kb_id,question,result_json,generation,context_answer_ids) VALUES(?,?,?,?,?,?,?)',
                       (answer_id,conversation_id,kb_id,question,result.model_dump_json(),snapshot.version.manifest.run_id,json.dumps([r['id'] for r in context])))
        value=result.model_dump(mode='json')
        return {'id':answer_id,'conversation_id':conversation_id,'kb_id':kb_id,'question':question,
                'source_notices':self.source_notices(value),'result':value,'service_options':self.service_options(value)}

    def service_options(self,result):
        ids={s['doc_id'] for s in result.get('sources',[])}
        if not ids:return []
        with self.db() as db:
            rows=db.execute('SELECT metadata FROM library_documents WHERE id IN ('+','.join('?' for _ in ids)+')',tuple(ids)).fetchall()
        tags={tag for row in rows for tag in (json.loads(row['metadata']).get('service_tags') or [])}
        from app.service_desk.catalog import SERVICES
        return [{'key':key,'title':SERVICES[key].title} for key in sorted(tags) if key in SERVICES]

    def answers(self):
        with self.db() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM knowledge_answers ORDER BY rowid DESC LIMIT 50')]
        return [{**{k:r[k] for k in r if k!='result_json'},'result':json.loads(r['result_json']),
                'source_notices':self.source_notices(json.loads(r['result_json'])),
                'service_options':self.service_options(json.loads(r['result_json']))} for r in rows]

    def valid_answer(self,answer_id,kb_id):
        if not answer_id:return None
        with self.db() as db:row=db.execute('SELECT * FROM knowledge_answers WHERE id=? AND kb_id=?',(answer_id,kb_id)).fetchone()
        if not row:return None
        try:snapshot=self.snapshot(kb_id)
        except (ValueError,FileNotFoundError):return None
        if row['generation']!=snapshot.version.manifest.run_id:return None
        value=json.loads(row['result_json'])
        return {'id':row['id'],'question':row['question'],'conversation_id':row['conversation_id'],'kb_id':kb_id,
            'result':value,'source_notices':self.source_notices(value)}
