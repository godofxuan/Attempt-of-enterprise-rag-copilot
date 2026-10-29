"""The workbench's shared local model transport, including failed attempts."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid

import httpx
from app.runtime.serving_chat import SERVING_CONTEXT_TOKENS,SERVING_OUTPUT_TOKENS


class ModelService:
    def __init__(self, workspace):
        self.workspace = workspace
        self.semaphore = asyncio.Semaphore(workspace.config.max_parallel_requests)
        self.client = httpx.AsyncClient(trust_env=False, follow_redirects=False)
        with self.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS model_calls(
                id TEXT PRIMARY KEY,kind TEXT,model TEXT,status TEXT,elapsed_ms INTEGER,
                input_json TEXT,output_json TEXT,error TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
            if 'purpose' not in {row[1] for row in db.execute('PRAGMA table_info(model_calls)')}:
                db.execute("ALTER TABLE model_calls ADD COLUMN purpose TEXT NOT NULL DEFAULT 'UNCLASSIFIED_EARLIER_PRODUCT_CALL'")

    def db(self):
        return sqlite3.connect(self.workspace.db_path, timeout=10)

    async def close(self):
        await self.client.aclose()

    async def send(self, kind, payload, *, purpose=None):
        from app.runtime.request_context import remaining_seconds, RequestDeadlineExceeded
        config = self.workspace.config
        call_id = uuid.uuid4().hex
        started = time.monotonic()
        async with self.semaphore:
            remaining=remaining_seconds()
            if remaining is not None and remaining<=0:raise RequestDeadlineExceeded('Run deadline exhausted before send')
            with self.db() as db:
                db.execute("INSERT INTO model_calls(id,kind,model,status,input_json,purpose) VALUES(?,?,?,?,?,?)",
                           (call_id, kind, payload['model'], 'SENDING', json.dumps(payload, ensure_ascii=False),purpose or kind))
            try:
                response = await self.client.post(config.model_endpoint+'/api/'+kind, json=payload,
                    timeout=min(config.request_timeout_seconds,remaining) if remaining is not None else config.request_timeout_seconds)
                response.raise_for_status()
                result = response.json()
                if result.get('error'): raise ValueError(result['error'])
                with self.db() as db:
                    db.execute("UPDATE model_calls SET status='OK',output_json=?,elapsed_ms=? WHERE id=?",
                               (json.dumps(result, ensure_ascii=False), round((time.monotonic()-started)*1000), call_id))
                return result
            except BaseException as exc:
                with self.db() as db:
                    db.execute("UPDATE model_calls SET status='ERROR',error=?,elapsed_ms=? WHERE id=?",
                               (type(exc).__name__+': '+str(exc), round((time.monotonic()-started)*1000), call_id))
                raise

    async def chat(self, messages, *, tools=None, response_format=None, max_tokens=SERVING_OUTPUT_TOKENS):
        payload = {'model':self.workspace.config.chat_model,'messages':messages,'stream':False,
                   'think':False,'options':{'temperature':0,'num_ctx':SERVING_CONTEXT_TOKENS,'num_predict':max_tokens}}
        if tools: payload['tools'] = tools
        if response_format: payload['format'] = response_format
        result=await self.send('chat', payload)
        if result.get('done_reason')=='length':raise ValueError('MODEL_OUTPUT_TRUNCATED')
        message=result['message']
        if not message.get('content') and not message.get('tool_calls'):raise ValueError('MODEL_RESPONSE_EMPTY')
        return message

    async def embed(self, texts, *, purpose='query_embedding'):
        from app.runtime.ollama_embeddings import _decode_embeddings
        result = await self.send('embed', {'model':self.workspace.config.embedding_model,'input':texts,'truncate':False},purpose=purpose)
        return _decode_embeddings(result,expected_count=len(texts),expected_dimension=None)

    async def embedding_identity(self):
        from app.runtime.ollama_embeddings import _model_digest
        response=await self.workspace.client.get(self.workspace.config.model_endpoint+'/api/tags')
        response.raise_for_status()
        return _model_digest(response.json(),self.workspace.config.embedding_model)

    def sync_chat(self, loop):
        def chat(model, messages, *, response_format=None, think=None):
            future = asyncio.run_coroutine_threadsafe(self.chat(messages, response_format=response_format), loop)
            return future.result(timeout=self.workspace.config.request_timeout_seconds+5)['content']
        return chat

    def sync_embed(self, loop, *, purpose='query_embedding'):
        def embed(text):
            future = asyncio.run_coroutine_threadsafe(self.embed([text],purpose=purpose), loop)
            return future.result(timeout=self.workspace.config.request_timeout_seconds+5)[0]
        return embed
