from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.agent_runtime.evalops_artifact import (
    AgentRunArtifactV1,
    verify_agent_run_artifact,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify an Enterprise Agent run artifact and its hash chain."
    )
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()

    artifact = AgentRunArtifactV1.model_validate_json(
        args.artifact.read_text(encoding="utf-8")
    )
    valid = verify_agent_run_artifact(artifact)
    print(
        json.dumps(
            {
                "artifact": str(args.artifact),
                "artifact_sha256": artifact.artifact_sha256,
                "event_count": len(artifact.trajectory),
                "git_sha": artifact.git_sha,
                "valid": valid,
            },
            indent=2,
        )
    )
    if not valid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
