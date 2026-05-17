import json
import pickle
import time
from urllib.parse import urlparse

import faiss
import numpy as np
import requests
from rank_bm25 import BM25Okapi

from app.chunker import chunk_text
from app.config import get_settings
from app.utils import ensure_dir, read_text_file, tokenize_for_bm25


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms

def _write_faiss_index(index: faiss.Index, index_path) -> None:
    serialized = faiss.serialize_index(index)
    index_path.write_bytes(serialized.tobytes())


def _ollama_api_base_url(llm_base_url: str) -> str:
    parsed = urlparse(llm_base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _embed_text(model: str, text: str) -> list[float]:
    settings = get_settings()
    url = f"{_ollama_api_base_url(settings.llm_base_url)}/api/embed"
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                url,
                json={"model": model, "input": text},
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()
            return data["embeddings"][0]
        except Exception as exc:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)

            if status_code == 503 and attempt < max_attempts:
                time.sleep(attempt * 2)
                continue

            detail = ""
            if response is not None:
                detail = f" Ollama response: {response.text[:500]}"

            raise RuntimeError(
                f"Embedding request failed at {url} for model {model!r}: {exc}.{detail}"
            ) from exc


def build_indexes() -> tuple[int, int]:
    settings = get_settings()
    ensure_dir(settings.indexes_dir)

    raw_files = list(settings.raw_docs_dir.glob("*.md")) + list(settings.raw_docs_dir.glob("*.txt"))
    all_chunks = []
    for file_path in raw_files:
        text = read_text_file(file_path)
        chunks = chunk_text(text=text, source=file_path.name)
        all_chunks.extend(chunks)

    if not all_chunks:
        raise ValueError("No raw documents found.")

    embeddings = []
    for chunk in all_chunks:
        embeddings.append(_embed_text(settings.embedding_model, chunk["text"]))

    embeddings_np = np.array(embeddings, dtype="float32")
    embeddings_np = _l2_normalize(embeddings_np)

    dim = embeddings_np.shape[1]
    faiss_index = faiss.IndexFlatIP(dim)
    faiss_index.add(embeddings_np)

    _write_faiss_index(faiss_index, settings.indexes_dir / "faiss.index")

    with open(settings.indexes_dir / "chunks.json", "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)

    tokenized_corpus = [tokenize_for_bm25(chunk["text"]) for chunk in all_chunks]
    with open(settings.indexes_dir / "bm25_tokens.pkl", "wb") as f:
        pickle.dump(tokenized_corpus, f)

    return len(raw_files), len(all_chunks)

def load_indexes():
    settings = get_settings()

    faiss_path = settings.indexes_dir / "faiss.index"
    chunks_path = settings.indexes_dir / "chunks.json"
    bm25_path = settings.indexes_dir / "bm25_tokens.pkl"

    if not faiss_path.exists():
        raise FileNotFoundError(f"FAISS index not found: {faiss_path}")
    if not chunks_path.exists():
        raise FileNotFoundError(f"Chunk metadata not found: {chunks_path}")
    if not bm25_path.exists():
        raise FileNotFoundError(f"BM25 tokens file not found: {bm25_path}")

    raw_bytes = faiss_path.read_bytes()
    faiss_index = faiss.deserialize_index(
        np.frombuffer(raw_bytes, dtype=np.uint8).copy()
    )

    with open(chunks_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    with open(bm25_path, "rb") as f:
        tokenized_corpus = pickle.load(f)

    bm25 = BM25Okapi(tokenized_corpus)

    return faiss_index, bm25, chunks

def hybrid_search(question: str, top_k: int | None = None) -> list[dict]:
    settings = get_settings()
    top_k = top_k or settings.retrieval_top_k
    candidate_k = settings.retrieval_candidate_k

    faiss_index, bm25, chunks = load_indexes()
    query_embedding = _embed_text(settings.embedding_model, question)
    query_vector = np.array([query_embedding], dtype="float32")
    query_vector = _l2_normalize(query_vector)

    dense_scores, dense_indices = faiss_index.search(query_vector, candidate_k)
    dense_indices = dense_indices[0].tolist()

    tokenized_query = tokenize_for_bm25(question)
    sparse_scores = bm25.get_scores(tokenized_query)
    sparse_ranked = np.argsort(sparse_scores)[::-1][:candidate_k].tolist()

    rrf_k = 60
    fused_scores = {}

    for rank, idx in enumerate(dense_indices, start=1):
        if idx == -1:
            continue
        fused_scores[idx] = fused_scores.get(idx, 0.0) + 1.0 / (rrf_k + rank)

    for rank, idx in enumerate(sparse_ranked, start=1):
        fused_scores[idx] = fused_scores.get(idx, 0.0) + 1.0 / (rrf_k + rank)

    ranked = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

    results = []
    for idx, score in ranked:
        item = dict(chunks[idx])
        item["score"] = float(score)
        results.append(item)

    return results
