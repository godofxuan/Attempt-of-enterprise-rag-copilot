"""Optional, offline-only serving scorer with bounded concurrency.

Inference is synchronous: an elapsed deadline discards its result, but does not
pretend to cancel a GPU kernel. No model downloads occur in the request path.
"""

import math
from functools import lru_cache
from pathlib import Path
from threading import Lock

from app.retrieval.reranker_identity import verify_reranker_identity


class LocalCrossEncoder:
    def __init__(self, model_path: Path, *, device: str = "cpu"):
        self.model_path = model_path
        self.device = device
        self._lock = Lock()
        self._model = None
        self._tokenizer = None

    def warmup(self) -> None:
        scores = self("startup readiness", ("A local model readiness check.",))
        if len(scores) != 1 or not math.isfinite(scores[0]):
            raise RuntimeError("reranker warmup returned invalid scores")

    def __call__(self, query, texts):
        if not texts:
            return []
        if len(texts) > 50:
            raise ValueError("serving scorer accepts at most 50 candidates")
        if not self._lock.acquire(timeout=0.25):
            raise TimeoutError("reranker capacity exhausted")
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            if self._model is None:
                if not self.model_path.is_dir():
                    raise ValueError("local reranker directory is unavailable")
                verify_reranker_identity(self.model_path)
                tokenizer = AutoTokenizer.from_pretrained(
                    str(self.model_path),
                    local_files_only=True,
                    trust_remote_code=False,
                )
                model = (
                    AutoModelForSequenceClassification.from_pretrained(
                        str(self.model_path),
                        local_files_only=True,
                        trust_remote_code=False,
                        use_safetensors=True,
                    )
                    .to(self.device)
                    .eval()
                )
                if self.device == "cuda":
                    model.half()
                self._tokenizer, self._model = tokenizer, model
            scores = []
            with torch.inference_mode():
                for start in range(0, len(texts), 16):
                    inputs = self._tokenizer(
                        [(query, text) for text in texts[start : start + 16]],
                        padding=True,
                        truncation=True,
                        max_length=512,
                        return_tensors="pt",
                    ).to(self.device)
                    scores.extend(self._model(**inputs).logits.reshape(-1).float().cpu().tolist())
            return scores
        finally:
            self._lock.release()


@lru_cache(maxsize=1)
def get_local_cross_encoder(model_path: str, device: str) -> LocalCrossEncoder:
    return LocalCrossEncoder(Path(model_path), device=device)
