import json
from pathlib import Path

import pytest

from scripts.verify_runtime_closure import gold_metrics, verify

ROOT = Path(__file__).resolve().parents[2]


def test_gold_metrics_deduplicate_before_cutoff_and_binary_gain():
    result = gold_metrics(["a", "b"], ["x", "x", "a", "y", "z", "b"])
    assert result["macro_article_recall_at_5"] == 1
    assert result["mrr_at_5"] == 0.5
    assert result["ndcg_at_5"] <= 1
    assert gold_metrics(["a"], [])["ndcg_at_5"] == 0


def test_missing_gold_never_claims_gold_verification():
    report = verify(ROOT / "docs/review/runtime_delivery_20260905")
    assert report["overall_status"] == "INCOMPLETE"
    assert report["verification_scope"]["gold_metrics"] == "MISSING_INPUT"
    assert report["verification_scope"]["aggregate_replay"] == "AGGREGATE_REPLAY_VERIFIED"
    assert report["service"]["counts"] == {"main": 680, "warmup": 35, "resource": 60}


@pytest.mark.parametrize("gold", [[], ["a", "a"], [None]])
def test_invalid_gold_is_not_silently_repaired(gold):
    with pytest.raises(ValueError):
        gold_metrics(gold, ["a"])


def test_missing_files_have_explicit_status(tmp_path):
    report = verify(tmp_path)
    assert report["overall_status"] == "INCOMPLETE"
    assert report["diagnostics"]


@pytest.mark.parametrize(
    "mutation",
    ["duplicate", "tamper", "missing_field", "nan", "fractional_count", "identity_float_count"],
)
def test_bad_public_evidence_is_rejected(tmp_path, mutation):
    import shutil

    source = ROOT / "docs/review/runtime_delivery_20260905"
    for name in (
        "manifest.json",
        "service_cases.json",
        "metrics.csv",
        "service_comparison.json",
        "retrieval_evidence.json",
    ):
        shutil.copyfile(source / name, tmp_path / name)
    path = tmp_path / "retrieval_evidence.json"
    packet = json.loads(path.read_bytes())
    if mutation == "duplicate":
        packet["rows"][1] = packet["rows"][0]
    elif mutation == "tamper":
        packet["rows"][0]["metrics"]["mrr_at_5"] = 0.123
    elif mutation == "missing_field":
        del packet["rows"][0]["article_ids"]
    elif mutation == "fractional_count":
        profile = packet["protocol"]["profiles"][0]
        packet["summary"][profile]["case_count"] += 1e-11
    elif mutation == "identity_float_count":
        manifest_path = tmp_path / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["identities"][0]["main_count"] = float(manifest["identities"][0]["main_count"])
        manifest_path.write_text(json.dumps(manifest), encoding="utf8")
    else:
        packet["rows"][0]["latency_ms_excluding_shared_embedding"] = float("nan")
    path.write_text(json.dumps(packet), encoding="utf-8")
    report = verify(tmp_path)
    assert report["overall_status"] == "INVALID"


def test_manifest_path_escape_is_rejected(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"artifacts": {"../outside": "0" * 64}}))
    assert verify(tmp_path)["overall_status"] == "INVALID"


def test_valid_gold_is_recomputed_and_cli_exit_is_scoped(tmp_path, monkeypatch):
    import hashlib
    import shutil

    from scripts.verify_runtime_closure import main

    source = ROOT / "docs/review/runtime_delivery_20260905"
    evidence = tmp_path / "input"
    evidence.mkdir()
    for name in ("manifest.json", "service_cases.json", "metrics.csv", "service_comparison.json"):
        shutil.copyfile(source / name, evidence / name)
    scores = gold_metrics(["a"], ["x", "a"])
    packet = dict(
        schema="retrieval-replay-measurements/1",
        protocol=dict(profiles=["fixture"], case_count=1, candidate_artifact_sha256="a" * 64),
        rows=[
            dict(
                question_id="q",
                profile="fixture",
                article_ids=["x", "a"],
                status="ok",
                metrics=scores,
                latency_ms_excluding_shared_embedding=10,
                shared_embedding_ms=5,
            )
        ],
        summary={
            "fixture": dict(
                **scores,
                case_count=1,
                failures=0,
                retrieval_latency_p50_ms=10,
                retrieval_latency_p95_ms=10,
            )
        },
    )
    raw = json.dumps(packet).encode()
    (evidence / "retrieval_evidence.json").write_bytes(raw)
    (evidence / "retrieval_gold.json").write_text(
        json.dumps(
            dict(
                schema="runtime-retrieval-gold/1",
                ranking_evidence_sha256=hashlib.sha256(raw).hexdigest(),
                candidate_artifact_sha256="a" * 64,
                questions=[dict(question_id="q", gold_article_ids=["a"])],
            )
        )
    )
    assert verify(evidence)["verification_scope"]["gold_metrics"] == "GOLD_METRICS_VERIFIED"
    monkeypatch.setattr(
        "sys.argv", ["verify", "--evidence", str(evidence), "--output", str(tmp_path / "result")]
    )
    assert main() == 0
    report = json.loads((tmp_path / "result/VERIFICATION_REPORT.json").read_bytes())
    assert report["human_semantics"] == "NEEDS_HUMAN"
    assert report["model_rerun"] == "NOT_RUN"


@pytest.mark.parametrize("mode,exit_code", [("missing", 2), ("invalid", 3), ("internal", 4)])
def test_non_success_exit_contract(tmp_path, monkeypatch, mode, exit_code):
    from scripts import verify_runtime_closure as module

    source = tmp_path / "input"
    source.mkdir()
    if mode == "invalid":
        (source / "manifest.json").write_text("{")
    if mode == "internal":

        def fail(*args):
            raise RuntimeError("must not leak internal details")

        monkeypatch.setattr(module, "verify", fail)
    monkeypatch.setattr(
        "sys.argv", ["verify", "--evidence", str(source), "--output", str(tmp_path / "output")]
    )
    assert module.main() == exit_code
    assert "must not leak" not in (tmp_path / "output/VERIFICATION_REPORT.json").read_text()
    assert json.loads((tmp_path / "output/VERIFICATION_REPORT.json").read_bytes())[
        "verification_scope"
    ]
