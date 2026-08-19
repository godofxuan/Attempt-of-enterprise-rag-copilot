from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from app.agent_runtime.evalops_artifact import build_agent_run_artifact
from app.agent_runtime.trajectory import SQLiteTrajectoryStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a verified EvalOps Agent run.")
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--git-sha")
    parser.add_argument("--schema-output", type=Path)
    args = parser.parse_args()
    git_sha = args.git_sha or subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    artifact = build_agent_run_artifact(
        SQLiteTrajectoryStore(args.store),
        args.session_id,
        case_id=args.case_id,
        git_sha=git_sha,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if args.schema_output is not None:
        args.schema_output.parent.mkdir(parents=True, exist_ok=True)
        import json

        args.schema_output.write_text(
            json.dumps(artifact.model_json_schema(), indent=2) + "\n",
            encoding="utf-8",
        )
    print(artifact.artifact_sha256)


if __name__ == "__main__":
    main()

