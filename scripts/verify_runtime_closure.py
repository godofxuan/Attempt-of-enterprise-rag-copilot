"""Offline runtime-delivery audit. Exit: 0 verified scope, 2 incomplete, 3 invalid, 4 internal.

Read only the supplied evidence directory. Optional retrieval_gold.json contains
public question/article identifiers, never inferred labels. Output must be new.
This verifies saved artifacts, not model execution or human answer correctness.
"""

import argparse
import csv
import hashlib
import io
import json
import math
from collections import Counter
from pathlib import Path

from scripts.export_runtime_delivery import aggregate, json_bytes, paired, percentile

METRICS = (
    "macro_article_recall_at_5",
    "hit_at_1",
    "hit_at_5",
    "mrr_at_5",
    "ndcg_at_5",
    "all_gold_at_5",
)
ARTIFACTS = {"metrics.csv", "service_cases.json", "service_comparison.json"}


def _read(root, name):
    path = root / name
    if path.resolve().parent != root.resolve() or path.is_symlink():
        raise ValueError("artifact path escapes evidence root")
    return path.read_bytes()


def _json(root, name):
    def invalid_constant(_value):
        raise ValueError("nonfinite JSON number")

    return json.loads(_read(root, name), parse_constant=invalid_constant)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("invalid numeric field")
    return value


def _ids(values, name):
    if not isinstance(values, list) or any(not isinstance(x, str) or not x for x in values):
        raise ValueError("invalid " + name)
    return values


def gold_metrics(gold, ranked):
    _ids(gold, "gold")
    _ids(ranked, "ranking")
    if not gold or len(set(gold)) != len(gold):
        raise ValueError("empty or duplicate gold")
    # Frozen eval_runtime_wixqa.metrics uses first five DISTINCT articles.
    top = list(dict.fromkeys(ranked))[:5]
    positions = [i for i, article in enumerate(top, 1) if article in gold]
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(gold), 5) + 1))
    return {
        "macro_article_recall_at_5": len(set(gold) & set(top)) / len(gold),
        "hit_at_1": int(bool(top and top[0] in gold)),
        "hit_at_5": int(bool(positions)),
        "mrr_at_5": 1 / positions[0] if positions else 0,
        "ndcg_at_5": sum(1 / math.log2(i + 1) for i in positions) / ideal,
        "all_gold_at_5": int(set(gold).issubset(top)),
    }


def _same(actual, expected, label):
    if isinstance(actual, (float, int)) and not isinstance(actual, bool):
        if not math.isclose(_number(actual), _number(expected), rel_tol=0, abs_tol=1e-10):
            raise ValueError("numeric mismatch: " + label)
    elif actual != expected:
        raise ValueError("value mismatch: " + label)


def _retrieval(root, gold_root=None):
    packet = _json(root, "retrieval_evidence.json")
    if packet["schema"] != "retrieval-replay-measurements/1":
        raise ValueError("unsupported retrieval schema")
    rows, protocol = packet["rows"], packet["protocol"]
    profiles = protocol["profiles"]
    count = protocol["case_count"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ValueError("invalid question count")
    _ids(profiles, "profiles")
    if len(set(profiles)) != len(profiles) or not profiles:
        raise ValueError("duplicate or empty profiles")
    if len(rows) != count * len(profiles):
        raise ValueError("retrieval row count mismatch")
    if len({(r["question_id"], r["profile"]) for r in rows}) != len(rows):
        raise ValueError("duplicate retrieval observation")
    if set(packet["summary"]) != set(profiles) or {r["profile"] for r in rows} != set(profiles):
        raise ValueError("retrieval profile mismatch")
    reference_ids = None
    anomalies = Counter()
    summaries = {}
    for profile in profiles:
        group = [r for r in rows if r["profile"] == profile]
        ids = set(_ids([r["question_id"] for r in group], "question IDs"))
        if len(ids) != count or (reference_ids is not None and ids != reference_ids):
            raise ValueError("unequal question cohorts")
        reference_ids = ids
        for r in group:
            ranked = _ids(r["article_ids"], "ranking")
            anomalies["rankings_with_duplicate_articles"] += len(ranked) != len(set(ranked))
            anomalies["short_rankings"] += len(set(ranked)) < 5
            if r["status"] not in {"ok", "error"}:
                raise ValueError("unrecognized retrieval status")
            if r["status"] == "error" and ranked:
                raise ValueError("failed retrieval with nonempty ranking")
            for key in ("latency_ms_excluding_shared_embedding", "shared_embedding_ms"):
                if _number(r[key]) < 0:
                    raise ValueError("negative timing")
            if set(r["metrics"]) != set(METRICS):
                raise ValueError("retrieval metric fields mismatch")
            for value in r["metrics"].values():
                if not 0 <= _number(value) <= 1:
                    raise ValueError("metric outside unit interval")
        actual = {m: sum(r["metrics"][m] for r in group) / count for m in METRICS}
        actual["case_count"] = len(group)
        actual["failures"] = sum(r["status"] != "ok" for r in group)
        timings = [r["latency_ms_excluding_shared_embedding"] for r in group]
        for q in (0.5, 0.95):
            actual[f"retrieval_latency_p{int(q * 100)}_ms"] = percentile(timings, q)
        for key, value in actual.items():
            expected = packet["summary"][profile][key]
            if key in {"case_count", "failures"}:
                if type(expected) is not int or expected != value:
                    raise ValueError("retrieval integer count mismatch: " + key)
            else:
                _same(value, expected, profile + ":" + key)
        summaries[profile] = actual
    gold_status = "MISSING_INPUT"
    gold_root = root if gold_root is None else gold_root
    gold_path = gold_root / "retrieval_gold.json"
    if gold_path.exists():
        gold = _json(gold_root, "retrieval_gold.json")
        if gold["schema"] != "runtime-retrieval-gold/1":
            raise ValueError("unsupported gold schema")
        if (
            gold["ranking_evidence_sha256"]
            != hashlib.sha256(_read(root, "retrieval_evidence.json")).hexdigest()
        ):
            raise ValueError("gold ranking binding mismatch")
        if gold["candidate_artifact_sha256"] != protocol["candidate_artifact_sha256"]:
            raise ValueError("gold candidate binding mismatch")
        entries = gold["questions"]
        if len(entries) != count or {r["question_id"] for r in entries} != reference_ids:
            raise ValueError("gold cohort mismatch")
        labels = {r["question_id"]: r["gold_article_ids"] for r in entries}
        for r in rows:
            for metric, value in gold_metrics(labels[r["question_id"]], r["article_ids"]).items():
                _same(value, r["metrics"][metric], "gold:" + metric)
        gold_status = "GOLD_METRICS_VERIFIED"
    return dict(rows=len(rows), profiles=summaries, anomalies=dict(anomalies)), gold_status


def _service(root):
    packet = _json(root, "service_cases.json")
    if packet["schema"] != "runtime-service-contracts/1":
        raise ValueError("unsupported service schema")
    rows = packet["rows"]
    seen = set()
    counts, groups = Counter(), {}
    for r in rows:
        kind = r["kind"]
        if kind not in {"main", "warmup", "resource1", "resource2", "resource4"}:
            raise ValueError("unknown observation kind")
        key = (r["run_id"], r["profile"], kind, r["case_id"], r["repeat"])
        if kind == "main" and key in seen:
            raise ValueError("duplicate service observation")
        seen.add(key)
        if _number(r["client_ms"]) < 0:
            raise ValueError("negative client timing")
        for field in ("model_calls", "model_errors", "model_retries", "repeat", "http_status"):
            if type(r[field]) is not int or r[field] < 0:
                raise ValueError("invalid service count/status")
        for field in ("contract_complete", "mode_ok", "source_complete", "known_security_failure"):
            if type(r["checks"][field]) is not bool:
                raise ValueError("invalid boolean check")
        group_key = r["run_id"] + "/" + r["profile"] + "/" + kind
        group = groups.setdefault(group_key, dict(n=0, complete=0, modes=Counter(), http=Counter()))
        group["n"] += 1
        group["complete"] += r["checks"]["contract_complete"]
        group["modes"][r["mode"]] += 1
        group["http"][str(r["http_status"])] += 1
        counts["resource" if kind.startswith("resource") else kind] += 1
    identities = _json(root, "manifest.json")["identities"]
    if {r["run_id"] for r in rows} != {i["run_id"] for i in identities}:
        raise ValueError("run identity mismatch")
    for identity in identities:
        for kind, field in (
            ("main", "main_count"),
            ("warmup", "warmup_count"),
            ("resource", "resource_count"),
        ):
            actual = sum(
                r["run_id"] == identity["run_id"]
                and (r["kind"] == kind or (kind == "resource" and r["kind"].startswith("resource")))
                for r in rows
            )
            if type(identity[field]) is not int or actual != identity[field]:
                raise ValueError("service protocol count mismatch")
    expected_metrics = list(csv.DictReader(io.StringIO(_read(root, "metrics.csv").decode("utf8"))))
    computed = aggregate(rows)
    if len(expected_metrics) != len(computed):
        raise ValueError("CSV group count mismatch")
    for a, b in zip(computed, expected_metrics, strict=True):
        if set(a) != set(b):
            raise ValueError("CSV fields mismatch")
        for key, value in a.items():
            if isinstance(value, int):
                if str(value) != b[key]:
                    raise ValueError("CSV integer mismatch: " + key)
            elif isinstance(value, float):
                _same(value, float(b[key]), "CSV:" + key)
            else:
                _same("" if value is None else value, b[key], "CSV:" + key)
    baseline, repair = (identities[i]["run_id"] for i in (0, 1))
    pair_rows = [r for name in (baseline, repair) for r in rows if r["run_id"] == name]
    comparison = paired(pair_rows)
    if comparison != _json(root, "service_comparison.json"):
        raise ValueError("paired counts mismatch")
    return dict(
        rows=len(rows),
        counts=dict(counts),
        groups=groups,
        csv_groups=len(computed),
        pairs=comparison,
        unique_main_cases=len({r["case_id"] for r in rows if r["kind"] == "main"}),
        uniqueness_basis=(
            "main: run/profile/case/repeat; warmup/resource unique request ID absent publicly"
        ),
    )


def verify(root, gold_root=None):
    root = Path(root)
    report = dict(
        overall_status="INCOMPLETE",
        verification_scope=dict(
            artifact_hash="NOT_VERIFIED",
            aggregate_replay="NOT_VERIFIED",
            gold_metrics="MISSING_INPUT",
        ),
        diagnostics=[],
        human_semantics="NEEDS_HUMAN",
        model_rerun="NOT_RUN",
    )
    try:
        manifest = _json(root, "manifest.json")
        if set(manifest["artifacts"]) != ARTIFACTS:
            raise ValueError("unexpected or unsafe artifact names")
        hashes = {}
        for name, expected in manifest["artifacts"].items():
            actual = hashlib.sha256(_read(root, name)).hexdigest()
            if actual != expected:
                raise ValueError("artifact hash mismatch: " + name)
            hashes[name] = actual
        report["hashes"] = hashes
        report["verification_scope"]["artifact_hash"] = "ARTIFACT_HASH_VERIFIED"
        report["service"] = _service(root)
        report["retrieval"], gold_status = _retrieval(root, gold_root)
        report["verification_scope"]["aggregate_replay"] = "AGGREGATE_REPLAY_VERIFIED"
        report["verification_scope"]["gold_metrics"] = gold_status
        if gold_status == "MISSING_INPUT":
            report["diagnostics"].append(
                "retrieval_gold.json missing; saved-score aggregation is not gold recomputation"
            )
        else:
            report["overall_status"] = "VERIFIED_WITHIN_SCOPE"
    except FileNotFoundError as exc:
        report["diagnostics"].append("missing input: " + Path(exc.filename).name)
    except (ValueError, KeyError, TypeError, IndexError, UnicodeError) as exc:
        report["overall_status"] = "INVALID"
        # Never serialize raw input values, private paths or malformed content.
        report["diagnostics"].append(
            str(exc) if type(exc) is ValueError else type(exc).__name__ + ": malformed artifact"
        )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument(
        "--gold-directory",
        type=Path,
        help="Optional explicitly selected directory containing retrieval_gold.json",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; use a new directory")
    try:
        report = verify(args.evidence, args.gold_directory)
    except Exception:
        report = dict(
            overall_status="INTERNAL_ERROR",
            verification_scope=dict(
                artifact_hash="NOT_VERIFIED",
                aggregate_replay="NOT_VERIFIED",
                gold_metrics="NOT_VERIFIED",
            ),
            diagnostics=["internal verifier error"],
            human_semantics="NEEDS_HUMAN",
            model_rerun="NOT_RUN",
        )
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "VERIFICATION_REPORT.json").write_bytes(json_bytes(report))
    print(
        json.dumps(
            {
                "overall_status": report["overall_status"],
                "verification_scope": report["verification_scope"],
            }
        )
    )
    return {"VERIFIED_WITHIN_SCOPE": 0, "INCOMPLETE": 2, "INVALID": 3, "INTERNAL_ERROR": 4}[
        report["overall_status"]
    ]


if __name__ == "__main__":
    raise SystemExit(main())
