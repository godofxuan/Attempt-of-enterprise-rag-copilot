"""Publish arithmetic-auditable WixQA metrics without question/document text."""

import argparse
import json
import math
from pathlib import Path

from scripts.export_runtime_delivery import digest, json_bytes, percentile


def export(root):
    completion = json.loads((root / "completion.json").read_bytes())
    if (
        completion["status"] != "COMPLETE"
        or digest(root / "rows.jsonl") != completion["rows_sha256"]
    ):
        raise ValueError("incomplete or changed retrieval run")
    original = [json.loads(line) for line in (root / "rows.jsonl").read_bytes().splitlines()]
    rows = [
        {
            key: row[key]
            for key in (
                "question_id",
                "profile",
                "metrics",
                "status",
                "article_ids",
                "latency_ms_excluding_shared_embedding",
                "shared_embedding_ms",
            )
        }
        for row in original
    ]
    if len(rows) != 800 or len({(r["question_id"], r["profile"]) for r in rows}) != 800:
        raise ValueError("retrieval cohort mismatch")
    summary = json.loads((root / "summary.json").read_bytes())
    for profile, expected in summary.items():
        group = [r for r in rows if r["profile"] == profile]
        if len(group) != 200 or any(r["status"] != "ok" for r in group):
            raise ValueError("unexpected incomplete retrieval profile")
        for metric in group[0]["metrics"]:
            actual = sum(r["metrics"][metric] for r in group) / len(group)
            if not math.isclose(actual, expected[metric], rel_tol=0, abs_tol=1e-12):
                raise ValueError("retrieval metric mismatch")
        timings = [r["latency_ms_excluding_shared_embedding"] for r in group]
        for q in (0.5, 0.95):
            if not math.isclose(
                percentile(timings, q),
                expected[f"retrieval_latency_p{int(q * 100)}_ms"],
                abs_tol=1e-8,
            ):
                raise ValueError("retrieval timing mismatch")
    return dict(
        schema="retrieval-replay-measurements/1",
        dataset="WixQA ExpertWritten fixed 200, consumed development cohort",
        scope="retrieval only; not answer accuracy; excludes shared query embedding",
        source=completion["source_identity"],
        protocol=completion["protocol"],
        private_rows_sha256=completion["rows_sha256"],
        private_completion_sha256=digest(root / "completion.json"),
        exporter_sha256=digest(__file__),
        summary=summary,
        rows=rows,
        execution_deviation="800 complete + 267 aborted v1 + 7 abandoned v2 = 1074 attempts; "
        "the 7 extra interrupted-run rows exceeded the amended 1067 cap and are retained privately",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = json_bytes(export(args.run))
    if args.check:
        if args.output.read_bytes() != data:
            raise ValueError("public retrieval evidence mismatch")
    else:
        if args.output.exists():
            raise FileExistsError(args.output)
        args.output.write_bytes(data)
    print(json.dumps({"status": "VERIFIED" if args.check else "EXPORTED", "rows": 800}))


if __name__ == "__main__":
    main()
