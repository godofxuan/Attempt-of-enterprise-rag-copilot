"""Use the existing persistent computation cache for unchanged library chunks."""
import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np

from app.indexing.computation_cache import (PersistentComputationCache,ComponentFingerprint,
    EmbeddingFingerprint,EmbeddingArtifactKey,EmbeddingVectorArtifact)


class CachedChunkEmbeddings:
    def __init__(self,workspace,model_digest,embed,chunker):
        self.workspace=workspace;self.embed=embed;self.digest=model_digest
        self.cache=PersistentComputationCache((workspace.root/'cache'/'embeddings').resolve())
        self.dimension_key='embedding_dimension:'+model_digest
        with sqlite3.connect(workspace.db_path) as db:
            row=db.execute('SELECT value FROM workspace_meta WHERE key=?',(self.dimension_key,)).fetchone()
        self.dimension=int(row[0]) if row else None
        self.pipeline=hashlib.sha256(chunker.model_dump_json().encode()).hexdigest()
        self.component=ComponentFingerprint(name='workbench-ollama-embeddings',semantic_version='1',
            implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.hits=0;self.misses=0

    def fingerprint(self):
        return EmbeddingFingerprint(component=self.component,backend='ollama-local',
            model_identifier=self.workspace.config.embedding_model,model_sha256=self.digest,
            dimension=self.dimension,normalization='none')

    def __call__(self,chunks):
        chunks=list(chunks);result=[None]*len(chunks);missing=[]
        def make_key(chunk):return EmbeddingArtifactKey(tenant_id=chunk.tenant_id,source_system='workbench-library',
                source_key=chunk.policy_id,document_id=chunk.policy_id,
                chunk_text_sha256=hashlib.sha256(chunk.text.encode()).hexdigest(),
                content_pipeline_sha256=self.pipeline,embedding=self.fingerprint())
        for index,chunk in enumerate(chunks):
            cached=self.cache.load_embedding(make_key(chunk)) if self.dimension else None
            if cached:
                self.hits+=1;result[index]=cached.vector
            else:missing.append((index,chunk))
        for offset in range(0,len(missing),16):
            group=missing[offset:offset+16]
            vectors=self.embed.batch([chunk.text for _,chunk in group]) if hasattr(self.embed,'batch') else [self.embed(chunk.text) for _,chunk in group]
            if len(vectors)!=len(group):raise ValueError('EMBEDDING_BATCH_SIZE_MISMATCH')
            for (index,chunk),vector in zip(group,vectors,strict=True):
                if self.dimension is None:
                    self.dimension=len(vector)
                    with sqlite3.connect(self.workspace.db_path) as db:
                        db.execute('INSERT OR IGNORE INTO workspace_meta VALUES(?,?)',(self.dimension_key,str(self.dimension)))
                if len(vector)!=self.dimension:raise ValueError('EMBEDDING_DIMENSION_CHANGED')
                payload=EmbeddingVectorArtifact(vector=tuple(vector))
                self.cache.store_embedding(make_key(chunk),payload)
                self.misses+=1;result[index]=payload.vector
        return np.ascontiguousarray(result,dtype='float32')
