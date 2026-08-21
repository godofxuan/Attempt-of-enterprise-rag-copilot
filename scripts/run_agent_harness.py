from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from app.agent_runtime.harness_contract import AgentHarnessRunner, HarnessRequestV1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run enterprise.agent-harness/1.0")
    parser.add_argument("--input", type=Path, help="JSON request file; stdin when omitted")
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--git-sha", default=None)
    args = parser.parse_args()
    raw = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
    request = HarnessRequestV1.model_validate_json(raw)
    git_sha = args.git_sha or subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        text=True,
    ).strip()
    result = AgentHarnessRunner(
        state_root=args.state_root,
        git_sha=git_sha,
    ).run(request)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
