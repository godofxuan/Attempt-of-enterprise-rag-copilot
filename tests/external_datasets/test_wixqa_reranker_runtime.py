from __future__ import annotations

import sys
from types import SimpleNamespace

from scripts.eval_wixqa_retrieval import _model_kwargs_for_dtype, build_parser


def test_wixqa_reranker_dtype_defaults_to_auto() -> None:
    args = build_parser().parse_args(["--cohort", "simulated", "--run-id", "fixture"])
    assert args.reranker_dtype == "auto"
    assert _model_kwargs_for_dtype(args.reranker_dtype) == {}


def test_wixqa_reranker_dtype_maps_to_lazy_torch_dtype(monkeypatch) -> None:
    fake_torch = SimpleNamespace(
        float32=object(),
        float16=object(),
        bfloat16=object(),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert _model_kwargs_for_dtype("float32") == {"torch_dtype": fake_torch.float32}
    assert _model_kwargs_for_dtype("float16") == {"torch_dtype": fake_torch.float16}
    assert _model_kwargs_for_dtype("bfloat16") == {"torch_dtype": fake_torch.bfloat16}
