import pytest

from app.retrieval.reranker_identity import verify_reranker_identity


def test_missing_model_fails_before_loading(tmp_path):
    with pytest.raises(ValueError, match="missing"):
        verify_reranker_identity(tmp_path)


def test_wrong_weights_are_rejected(tmp_path):
    (tmp_path / "model.safetensors").write_bytes(b"not the frozen model")
    with pytest.raises(ValueError, match="identity mismatch"):
        verify_reranker_identity(tmp_path)
