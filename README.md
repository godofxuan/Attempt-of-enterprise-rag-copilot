# Enterprise RAG Copilot

A local-first RAG application for question answering over enterprise-style documents.

The project uses a FastAPI backend, a Streamlit UI, local Ollama models, and hybrid retrieval with FAISS and BM25.

## Features

- Ingest Markdown and text documents
- Split documents by section and chunk them for retrieval
- Build local FAISS and BM25 indexes
- Answer questions with retrieved source context
- Return source snippets with each answer
- Collect simple thumbs up / thumbs down feedback
- Run basic retrieval and answer evaluation scripts

## Tech Stack

- Python
- FastAPI
- Streamlit
- Ollama
- FAISS
- BM25
- SQLite

## Project Structure

```text
app/                 # FastAPI backend and RAG pipeline
streamlit_app/        # Streamlit UI
scripts/              # Data preparation, evaluation, and smoke-test scripts
data/raw_docs/        # Sample documents
data/eval_*.json      # Evaluation data
```

Generated files such as indexes, SQLite databases, caches, and local `.env` files are ignored by Git.

## Configuration

Copy the example environment file:

```powershell
copy .env.example .env
```

Default model settings:

```text
CHAT_MODEL=qwen2.5:3b
EMBEDDING_MODEL=bge-m3
```

Other Ollama models can be used by changing the values in `.env`.

If the embedding model is changed, rebuild the index.

## Run

Install dependencies:

```powershell
pip install -r requirements.txt
```

Prepare sample documents:

```powershell
python -m scripts.prepare_sample_docs
```

Start the backend:

```powershell
uvicorn app.main:app --reload
```

Start the UI in another terminal:

```powershell
streamlit run streamlit_app/ui.py
```

Open the Streamlit UI, build the index from the sidebar, then ask a question.

Example questions:

```text
退款期限是多少？
什么情况下不支持退款？
VPN 报错 691 怎么处理？
```

## Evaluation

Run retrieval evaluation:

```powershell
python -m scripts.eval_retrieval
```

Generate answer evaluation results:

```powershell
python -m scripts.fill_eval_answers
```

Current retrieval result on the sample dataset:

- hit@1: 19/20
- hit@3: 20/20

## Notes

- The included documents are fictional sample data.
- `data/indexes/` is generated locally after indexing.
- `data/app.db` is generated locally for feedback storage.
- `.env` should stay local and should not be committed.
