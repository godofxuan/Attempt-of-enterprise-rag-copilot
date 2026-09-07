"""Export finite service contract evidence without prompts, sources or identities."""

import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()


def percentile(values, q):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def public_row(row, run_id):
    response = row["response"]
    trace = response.get("trace", {})
    server = row["server_trace"] or {}
    score = row["score"]
    result = {key: row[key] for key in ("case_id", "category", "kind", "profile", "repeat")}
    result.update(
        run_id=run_id,
        http_status=row["http_status"],
        client_ms=row["client_ms"],
        mode=response.get("mode", "http_error"),
        stop_reason=response.get("stop_reason"),
        generation_error_category=trace.get("generation_error_category"),
        generation_attempts=trace.get("generation_attempts", 0),
        model_calls=server.get("model_calls", 0),
        model_retries=server.get("model_retries", 0),
        model_errors=server.get("model_errors", 0),
        index_binding_status=trace.get("index_binding_status"),
        source_count=len(response.get("sources", [])),
        packet_hash=trace.get("packet_hash"),
        concurrency=row.get("concurrency"),
        budget={
            key: trace.get("budget", {}).get(key, 0)
            for key in ("search_calls", "find_calls", "open_calls", "steps")
        },
        checks={
            key: score[key]
            for key in (
                "contract_complete",
                "mode_ok",
                "fact_count",
                "matched_facts",
                "source_complete",
                "citation_references",
                "invalid_references",
                "forbidden_publication_count",
                "unsafe_tool_calls",
                "unauthorized_sources",
                "known_security_failure",
            )
        },
    )
    return result


def load_run(root):
    completion = json.loads((root / "completion.json").read_bytes())
    manifest = json.loads((root / "manifest.json").read_bytes())
    if completion.get("status") != "COMPLETE" or completion.get("source_unchanged") is not True:
        raise ValueError("run not certified complete")
    for name in ("rows", "summary"):
        suffix = "jsonl" if name == "rows" else "json"
        if digest(root / f"{name}.{suffix}") != completion[f"{name}_sha256"]:
            raise ValueError("run artifact hash mismatch")
    for key in ("app_sources_sha256", "harness_sha256"):
        if manifest["source"][key] != completion["source"][key]:
            raise ValueError("run execution source changed")
    rows = [json.loads(line) for line in (root / "rows.jsonl").read_bytes().splitlines()]
    summary = json.loads((root / "summary.json").read_bytes())
    main = [row for row in rows if row["kind"] == "main"]
    if len(main) != summary["main_count"]:
        raise ValueError("main request count mismatch")
    keys = {(row["case_id"], row["profile"], row["repeat"]) for row in main}
    if len(keys) != len(main):
        raise ValueError("duplicate main request")
    for expected in summary["summary"]:
        selected = [row for row in main if row["profile"] == expected["profile"]]
        if (
            len(selected) != expected["n"]
            or sum(row["score"]["contract_complete"] for row in selected)
            != expected["all_pass_complete"]
        ):
            raise ValueError("aggregate does not match individual rows")
    identity = {
        "run_id": root.name,
        "initial_source": manifest["source"],
        "final_source": completion["source"],
        "hardware": manifest["hardware"],
        "model_identities": manifest["model_identities"],
        "reranker": manifest["reranker"],
        "settings": manifest["settings"],
        "protocol_sha256": manifest["protocol_sha256"],
        "private_rows_sha256": completion["rows_sha256"],
        "private_summary_sha256": completion["summary_sha256"],
        "private_manifest_sha256": digest(root / "manifest.json"),
        "private_completion_sha256": digest(root / "completion.json"),
        "main_count": len(main),
        "warmup_count": summary["warmup_count"],
        "resource_count": summary["resource_count"],
        "startup": summary["startup"],
        "resource_peak": {
            key: max((s.get(key, 0) for s in summary["resource_samples"]), default=0) or None
            for key in ("process_rss_bytes", "gpu_total_used_mib")
        },
    }
    return [public_row(row, root.name) for row in rows], identity


def aggregate(rows):
    result = []
    for run_id, profile, kind in sorted({(r["run_id"], r["profile"], r["kind"]) for r in rows}):
        selected = [
            r for r in rows if (r["run_id"], r["profile"], r["kind"]) == (run_id, profile, kind)
        ]
        for subset in ("all", "contract_complete", "contract_failed"):
            group = [
                r
                for r in selected
                if subset == "all"
                or r["checks"]["contract_complete"] == (subset == "contract_complete")
            ]
            timing = [r["client_ms"] for r in group]
            result.append(
                dict(
                    run_id=run_id,
                    profile=profile,
                    kind=kind,
                    subset=subset,
                    n=len(group),
                    complete=sum(r["checks"]["contract_complete"] for r in group),
                    mean_ms=sum(timing) / len(timing) if timing else None,
                    p50_ms=percentile(timing, 0.5),
                    p95_ms=percentile(timing, 0.95),
                    known_security_failures=sum(
                        r["checks"]["known_security_failure"] for r in group
                    ),
                    model_calls=sum(r["model_calls"] for r in group),
                    model_retries=sum(r["model_retries"] for r in group),
                    model_errors=sum(r["model_errors"] for r in group),
                )
            )
    return result


def paired(rows):
    main = [r for r in rows if r["kind"] == "main"]
    runs = sorted({r["run_id"] for r in main})
    output = []
    if len(runs) != 2:
        raise ValueError("exactly two runs required for repair comparison")
    # The CLI fixes baseline/final order explicitly; names are not a time source.
    baseline = [r for r in main if r["run_id"] == rows[0]["run_id"]]
    final = [r for r in main if r["run_id"] != rows[0]["run_id"]]
    for profile in sorted({r["profile"] for r in final}):
        before = {(r["case_id"], r["repeat"]): r for r in baseline if r["profile"] == profile}
        after = {(r["case_id"], r["repeat"]): r for r in final if r["profile"] == profile}
        if before.keys() != after.keys():
            raise ValueError("pair cohort mismatch")
        counts = Counter()
        for key, row in after.items():
            a, b = before[key]["checks"]["contract_complete"], row["checks"]["contract_complete"]
            counts[
                "retained" if a and b else "gained" if b else "regressed" if a else "missed"
            ] += 1
        output.append(dict(profile=profile, pairs=len(after), **dict(counts)))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--final", type=Path, required=True)
    parser.add_argument("--confirmation", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rows, identities = [], []
    for root in (args.baseline, args.final):
        new_rows, identity = load_run(root)
        rows.extend(new_rows)
        identities.append(identity)
    comparison = paired(rows)
    if args.confirmation:
        new_rows, identity = load_run(args.confirmation)
        rows.extend(new_rows)
        identities.append(identity)
    metrics = aggregate(rows)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(metrics[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(metrics)
    payloads = {
        "service_cases.json": json_bytes({"schema": "runtime-service-contracts/1", "rows": rows}),
        "metrics.csv": stream.getvalue().encode(),
        "service_comparison.json": json_bytes(comparison),
    }
    manifest = dict(
        schema="runtime-delivery-evidence/1",
        claim="SYNTHETIC_CONTRACT_NOT_HUMAN_ACCURACY",
        identities=identities,
        artifacts={name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()},
        exporter_sha256=digest(__file__),
    )
    payloads["manifest.json"] = json_bytes(manifest)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, data in payloads.items():
        path = args.output / name
        if args.check:
            if not path.exists() or path.read_bytes() != data:
                raise ValueError(f"public evidence mismatch: {name}")
        else:
            if path.exists():
                raise FileExistsError(path)
            path.write_bytes(data)
    print(json.dumps({"status": "VERIFIED" if args.check else "EXPORTED", "rows": len(rows)}))


if __name__ == "__main__":
    main()
