"""Collect one local source/evidence review, excluding models, indexes and private DB.

Snapshots are read-only copies of declared synthetic domain tables, not a runtime
database or another accounting ledger. Original calls and evidence are untouched.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".private/esa-vnext"
EVIDENCE = DATA / "upgrade-050-060"
PARENT = "5ff9aac2087d8fcfdfd547035cef356d820a52ce"


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", required=True)
    args = parser.parse_args()
    commit = subprocess.check_output(
        ["git", "rev-parse", args.ref + "^{commit}"], text=True
    ).strip()
    output = (
        DATA
        / "deliveries"
        / ("ESA_060_REVIEW_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    )
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"
    source.mkdir()
    paths = [
        "app",
        "frontend",
        "tests",
        "scripts",
        "packaging",
        "docs/esa-vnext",
        "docs/history/RELEASE_040.md",
        "docs/history/README_PRE_030.md",
        "README.md",
        "AGENTS.md",
        "pyproject.toml",
        "uv.lock",
    ]
    raw = subprocess.check_output(["git", "archive", "--format=tar", commit, *paths])
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        assert all(
            (source / e.name).resolve().is_relative_to(source) and not e.issym() and not e.islnk()
            for e in archive.getmembers()
        )
        archive.extractall(source, filter="data")
    (output / "CHANGE.patch").write_bytes(
        subprocess.check_output(["git", "diff", "--binary", PARENT, commit, "--", *paths])
    )
    save(
        output / "IDENTITY.json",
        {
            "application_commit": commit,
            "parent_commit": PARENT,
            "branch": subprocess.check_output(
                ["git", "branch", "--show-current"], text=True
            ).strip(),
            "excluded_dirty_worktree": subprocess.check_output(
                ["git", "status", "--short"], text=True
            ),
            "current_instance": json.loads((DATA / "instance.json").read_text("utf8")),
        },
    )
    originals = output / "evidence"
    originals.mkdir()
    for p in EVIDENCE.iterdir():
        if p.is_file() and p.suffix.lower() in {".json", ".xml", ".png", ".log", ".txt"}:
            shutil.copy2(p, originals / p.name)
    db = sqlite3.connect(DATA / "app.sqlite3")
    db.row_factory = sqlite3.Row
    baseline = sqlite3.connect(EVIDENCE / "before-050.sqlite3")
    baseline.row_factory = sqlite3.Row
    assert json.loads((DATA / "workspace.json").read_text("utf8"))["sample_data"] is True
    assert not db.execute(
        "SELECT 1 FROM workbench_runs WHERE status IN ('queued','running')"
    ).fetchone(), "Do not freeze while a real run is active"
    old = {r["id"]: dict(r) for r in baseline.execute("SELECT * FROM model_calls")}
    new = []
    changed = []
    for row in db.execute("SELECT * FROM model_calls ORDER BY rowid"):
        r = dict(row)
        if r["id"] not in old:
            new.append(r)
        elif any(r.get(k) != v for k, v in old[r["id"]].items() if k != "purpose"):
            changed.append(r["id"])
    assert not changed, "Historical raw accounting changed: " + str(changed)
    with (originals / "NEW_MODEL_CALLS.jsonl").open("w", encoding="utf8") as stream:
        for r in new:
            stream.write(json.dumps(r, ensure_ascii=False) + "\n")
    old_runs = {r[0] for r in baseline.execute("SELECT id FROM workbench_runs")}
    runs = [
        dict(r)
        for r in db.execute("SELECT * FROM workbench_runs ORDER BY rowid")
        if r["id"] not in old_runs
    ]
    save(originals / "NEW_RUNS.json", runs)
    ids = {r["id"] for r in runs}
    save(
        originals / "NEW_RUN_EVENTS.json",
        [
            dict(r)
            for r in db.execute("SELECT * FROM run_events ORDER BY seq")
            if r["run_id"] in ids
        ],
    )
    total = Counter()
    status = Counter()
    purpose = Counter()
    texts = Counter()
    tokens = Counter()
    for r in new:
        total[r["kind"]] += 1
        status[r["kind"] + ":" + r["status"]] += 1
        purpose[r["purpose"]] += 1
        if r["kind"] == "embed":
            texts[r["purpose"]] += len(json.loads(r["input_json"])["input"])
        out = json.loads(r["output_json"] or "{}")
        for k in ("prompt_eval_count", "eval_count"):
            if k in out:
                tokens[k] += out[k]
    save(
        output / "COST.json",
        {
            "baseline": dict(Counter(r["kind"] for r in old.values())),
            "new_actual_attempts": dict(total),
            "new_statuses": dict(status),
            "new_purposes": dict(purpose),
            "embedding_texts_by_purpose": dict(texts),
            "returned_token_counts": dict(tokens),
            "missing_token_or_response_is_unknown": True,
            "current_total": dict(
                Counter(r[0] for r in db.execute("SELECT kind FROM model_calls"))
            ),
            "historical_raw_rows_unchanged": True,
            "unrelated_historical_project_total": "UNKNOWN_NOT_RESET",
            "orphaned_sending_explanation": "One new SENDING record from interrupted process has no recovered response; it remains counted, not fabricated or erased.",
        },
    )
    domain = [
        "tickets",
        "it_repair_tickets",
        "assets",
        "it_assets",
        "repairs",
        "loan_rules",
        "it_repair_rules",
        "asset_details",
        "rule_sources",
        "action_proposals",
        "confirmations",
        "command_ledger",
        "ticket_events",
        "asset_reservations",
    ]
    for label, connection in [("BEFORE", baseline), ("AFTER", db)]:
        snapshot = sqlite3.connect(output / ("TEST_DOMAIN_" + label + ".sqlite3"))
        counts = {}
        for table in domain:
            sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not sql:
                continue
            rows = list(connection.execute("SELECT * FROM " + table))
            snapshot.execute(sql[0])
            if rows:
                snapshot.executemany(
                    "INSERT INTO " + table + " VALUES(" + ",".join("?" for _ in rows[0]) + ")",
                    [tuple(r) for r in rows],
                )
            counts[table] = len(rows)
        snapshot.commit()
        snapshot.close()
        save(
            output / ("TEST_DOMAIN_" + label + ".json"),
            {
                "kind": "DERIVED_ACTUAL_SQL_ROWS_SYNTHETIC_DOMAIN_ONLY",
                "counts": counts,
                "primary_database_included": False,
            },
        )
    db.close()
    baseline.close()
    save(
        output / "MANIFEST.json",
        {
            p.relative_to(output).as_posix(): {
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in output.rglob("*")
            if p.is_file()
        },
    )
    target = Path(str(output) + ".zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for p in sorted(output.rglob("*")):
            if p.is_file():
                archive.write(p, p.relative_to(output))
    save(
        DATA / "deliveries/LATEST_REVIEW.json",
        {
            "path": str(target),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "bytes": target.stat().st_size,
            "application_commit": commit,
        },
    )
    print(str(target))


if __name__ == "__main__":
    main()
