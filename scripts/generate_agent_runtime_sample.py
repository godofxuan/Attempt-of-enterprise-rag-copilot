from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from uuid import uuid4

from app.agent.tools_v2 import V2ToolRegistry
from app.agent_runtime.evalops_artifact import (
    AgentRunArtifactV1,
    build_agent_run_artifact,
)
from app.agent_runtime.evaluation import AgentRuntimeScenarioNavigator
from app.agent_runtime.orchestrator import AgentRunRequest, BoundedControllerAdapter
from app.agent_runtime.trajectory import SQLiteTrajectoryStore
from app.domain.queries import UserContext


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the public Agent run sample.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/agent_runtime/evidence/agent_run_artifact_sample_v1.json"),
    )
    parser.add_argument(
        "--schema-output",
        type=Path,
        default=Path("docs/agent_runtime/schemas/agent_run_artifact_v1.schema.json"),
    )
    parser.add_argument("--git-sha")
    args = parser.parse_args()
    git_sha = args.git_sha or subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    store_path = Path(".private/agent_runtime") / f"sample-{uuid4().hex}.sqlite3"
    store = SQLiteTrajectoryStore(store_path)
    adapter = BoundedControllerAdapter(
        V2ToolRegistry(AgentRuntimeScenarioNavigator("answered")),
        trajectory_store=store,
    )
    adapter.run(
        AgentRunRequest(
            question="What is the remote policy?",
            user=UserContext(
                user_id="sample-employee",
                tenant_id="sample-tenant",
                region="cn",
                groups=["employees"],
            ),
            request_id="sample-request",
            trace_id="sample-trace",
            session_id="sample-session",
        )
    )
    artifact = build_agent_run_artifact(
        store,
        "sample-session",
        case_id="public-sample-answer",
        git_sha=git_sha,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
    args.schema_output.parent.mkdir(parents=True, exist_ok=True)
    args.schema_output.write_text(
        json.dumps(AgentRunArtifactV1.model_json_schema(), indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "artifact_sha256": artifact.artifact_sha256,
                "private_store": str(store_path),
                "output": str(args.output),
                "schema_output": str(args.schema_output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
