"""Batch the current ESA product checks inside one explicitly approved local task.

Only named operations, repository tests and the registered synthetic workspace.
No arbitrary command execution interface, dependency installation or cloud calls.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".private/esa-vnext"
EVIDENCE = DATA / "upgrade-050-060"


def command(*parts):
    result = subprocess.run(
        [str(p) for p in parts], cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"}
    )
    if result.returncode:
        raise SystemExit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=["related", "restart-and-journey", "ui-and-resume", "journey-only", "build"],
    )
    parser.add_argument("--expected-instance")
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    if args.operation == "related":
        command(
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "pytest",
            "tests/vnext",
            "tests/product/test_turn_recovery.py",
            "tests/product/test_context_and_clarification.py",
            "tests/product/test_launcher.py",
            "tests/agent_v2/test_a1_draft_delivery.py",
            "-q",
            "--junitxml=" + str(EVIDENCE / "PRODUCT_RELATED_CURRENT.xml"),
        )
    elif args.operation == "build":
        command(sys.executable, "-B", "-X", "utf8", "scripts/build_windows_portable.py")
    elif args.operation in {"ui-and-resume", "journey-only"}:
        assert args.resume and args.resume.resolve().is_relative_to(EVIDENCE)
        os.environ["NODE_PATH"] = str(
            Path.home()
            / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
        )
        if args.operation == "ui-and-resume":
            command(Path(r"D:\Node\node.exe"), "tests/product/browser_navigation.cjs")
        command(Path(r"D:\Node\node.exe"), "tests/product/live_050_journey.cjs", args.resume)
    else:
        import httpx

        assert (
            args.expected_instance
            and args.resume
            and args.resume.resolve().is_relative_to(EVIDENCE)
        )
        assert json.loads((DATA / "workspace.json").read_text("utf8"))["sample_data"] is True
        with httpx.Client(trust_env=False, timeout=4) as client:
            old = client.get("http://127.0.0.1:8740/api/instance").json()
            assert (
                old["instance_id"] == args.expected_instance
                and Path(old["data_dir"]).resolve() == DATA
            )
            client.post(
                "http://127.0.0.1:8740/api/product/shutdown", headers={"X-ESA-Request": "1"}
            ).raise_for_status()
            for _ in range(100):
                try:
                    client.get("http://127.0.0.1:8740/api/status")
                except httpx.HTTPError:
                    break
                time.sleep(0.15)
        command(
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "app.launcher",
            "open",
            "--data-dir",
            DATA,
            "--registry",
            EVIDENCE / "active-workspaces.json",
            "--no-browser",
        )
        os.environ["NODE_PATH"] = str(
            Path.home()
            / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
        )
        command(Path(r"D:\Node\node.exe"), "tests/product/live_050_journey.cjs", args.resume)


if __name__ == "__main__":
    main()
