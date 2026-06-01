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
data/raw_docs/        # Enterprise-style policy documents
data/eval/            # Golden-set evaluation data
data/eval_outputs/    # Generated local evaluation outputs
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

The repository now uses the golden-set documents in `data/raw_docs/`.
Do not run `scripts.prepare_sample_docs` unless you intentionally want to restore the old toy sample documents.

```powershell
python -m scripts.build_indexes
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

### Dataset

The evaluation set is a synthetic enterprise-style golden set, not real private company data.

- 15 Chinese enterprise-style policy documents
- 120 labeled questions
- Question types: `fact`, `constraint`, `list`, `process`, `comparison`, `synonym`, `no_answer`, `adversarial`
- Retrieval splits: `data/eval/retrieval_dev.json`, `data/eval/retrieval_test.json`
- Answer splits: `data/eval/answer_dev.json`, `data/eval/answer_test.json`, `data/eval/adversarial_test.json`

### How To Run

Build indexes:

```powershell
python -m scripts.build_indexes
```

Evaluate Hybrid RRF retrieval:

```powershell
python -m scripts.eval_retrieval_v2 --split test --top-k 5
```

Compare BM25, dense retrieval, and Hybrid RRF:

```powershell
python -m scripts.eval_ablation_v2 --split test --top-k 5
```

Compare fusion strategies:

```powershell
python -m scripts.eval_fusion_ablation --split test --top-k 5
```

Run answer evaluation:

```powershell
python -m scripts.eval_answer_v1 --split test
python -m scripts.eval_answer_v1 --split adversarial
```

On Windows, if `python` points to Anaconda instead of the project virtual environment, use:

```powershell
.\.venv\Scripts\python.exe -m scripts.eval_retrieval_v2 --split test --top-k 5
```

### Metrics Explanation

- `Hit@k`: whether at least one gold source appears in the top-k retrieved chunks.
- `Recall@k`: fraction of gold sources retrieved in top-k.
- `Coverage@k`: whether all gold sources are retrieved in top-k.
- `Precision@k`: relevant retrieved chunks in top-k divided by k.
- `MRR`: reciprocal rank of the first relevant result.
- `nDCG@k`: ranking quality with binary relevance in the first version.
- `must_include_rate`: fraction of required answer points present in the model answer.
- `must_not_include_ok_rate`: fraction of answers without forbidden content.
- `citation_hit_rate`: whether returned sources include any gold source.
- `citation_coverage_rate`: whether returned sources cover all gold sources.
- `refusal_accuracy`: refusal success rate on `no_answer` and `adversarial` questions.

`answerable=false` and ordinary `no_answer` questions are excluded from ordinary retrieval metrics and evaluated through refusal / hallucination checks.

### Current Results

Indexes:

- 15 documents
- 75 chunks

Retrieval test with Hybrid RRF:

- Hit@1: 0.9333
- Hit@3: 1.0
- Hit@5: 1.0
- Recall@5: 0.9917
- Coverage@5: 0.9833
- MRR: 0.9639

Ablation test:

| Method | Hit@1 | Hit@3 | Hit@5 | MRR |
| --- | ---: | ---: | ---: | ---: |
| BM25 only | 0.8500 | 0.9833 | 0.9833 | 0.9056 |
| Dense only | 0.9167 | 0.9833 | 1.0000 | 0.9486 |
| Hybrid RRF | 0.9333 | 1.0000 | 1.0000 | 0.9639 |

Answer eval pilot result, not a final conclusion:

- `--limit 10`
- `must_include_rate_avg`: 0.725
- `citation_hit_rate`: 1.0
- `citation_coverage_rate`: 1.0

### Known Limitations

- The documents are synthetic enterprise-style data.
- Answer evaluation is still being optimized.
- The project has not yet integrated a reranker.
- The project does not yet implement a full Agentic workflow.
- nDCG uses binary relevance in the first version; it can later be upgraded to graded relevance.
- `weighted_score_fusion` uses per-query min-max score normalization and should be treated as an experimental baseline.

## Notes

- The included documents are fictional sample data.
- `data/indexes/` is generated locally after indexing.
- `data/app.db` is generated locally for feedback storage.
- `.env` should stay local and should not be committed.
