from __future__ import annotations

import argparse
from pathlib import Path

from app.agent_runtime.replay import replay_trajectory
from app.agent_runtime.trajectory import SQLiteTrajectoryStore


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify and replay one persisted Agent trajectory."
    )
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    args = parser.parse_args()
    replay = replay_trajectory(SQLiteTrajectoryStore(args.store), args.session_id)
    print(replay.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

