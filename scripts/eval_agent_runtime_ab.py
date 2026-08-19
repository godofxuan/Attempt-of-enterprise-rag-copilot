from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from app.agent_runtime.evaluation import run_agent_runtime_ab


def main() -> None:
    parser = argparse.ArgumentParser(description="Run bounded vs LangGraph A/B.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/agent_runtime/evidence/agent_runtime_ab_v1.json"),
    )
    parser.add_argument("--git-sha")
    args = parser.parse_args()
    git_sha = args.git_sha or subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    artifact = run_agent_runtime_ab(git_sha=git_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(artifact.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

