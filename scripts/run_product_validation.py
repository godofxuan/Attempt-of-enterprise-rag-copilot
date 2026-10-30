"""Batch the current ESA product checks inside one explicitly approved local task.

Only named operations, repository tests and the registered synthetic workspace.
No arbitrary command execution interface, dependency installation or cloud calls.
"""

import argparse
from datetime import datetime, timezone
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".private/esa-vnext"
EVIDENCE = DATA / "upgrade-050-060"
NODE = Path(os.environ.get("ESA_NODE_EXE") or shutil.which("node") or "node")


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
        choices=[
            "related",
            "restart-and-journey",
            "ui-and-resume",
            "journey-only",
            "build",
            "release-validation",
            "patch-validation",
        ],
    )
    parser.add_argument("--expected-instance")
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--artifact", type=Path)
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
            "--junitxml="
            + str(
                EVIDENCE
                / (
                    "PRODUCT_RELATED_"
                    + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
                    + ".xml"
                )
            ),
        )
    elif args.operation == "build":
        command(sys.executable, "-B", "-X", "utf8", "scripts/build_windows_portable.py")
    elif args.operation in {"release-validation", "patch-validation"}:
        import httpx

        assert args.artifact and args.artifact.resolve().is_relative_to(DATA / "build/releases")
        patch = args.operation == "patch-validation"
        identity = args.artifact.stem.rsplit("-", 1)[-1]
        if patch:
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
                "tests/agent_v2/test_cited_packet_completeness.py",
                "-q",
                "--junitxml=" + str(EVIDENCE / ("FINAL_REGRESSION_" + identity + ".xml")),
            )
        command(
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "tests.product.probe_windows_portable",
            "--artifact",
            args.artifact,
            "--output",
            EVIDENCE / ("Windows 最终包验证 " + identity),
            "--starts",
            "1" if patch else "5",
        )
        package = Path(str(args.artifact.resolve())[:-4])
        with httpx.Client(trust_env=False, timeout=4) as client:
            old = client.get("http://127.0.0.1:8740/api/instance").json()
            assert (
                old["instance_id"] == args.expected_instance
                and Path(old["data_dir"]).resolve() == DATA
            )
            before = client.get("http://127.0.0.1:8740/api/status").json()
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
            package / "ESA.exe",
            "--data-dir",
            DATA,
            "--registry",
            EVIDENCE / "active-workspaces.json",
            "--no-browser",
        )
        with httpx.Client(trust_env=False, timeout=4) as client:
            after = client.get("http://127.0.0.1:8740/api/status").json()
            assert (
                before["generation_calls"] == after["generation_calls"]
                and before["initialized_at"] == after["initialized_at"]
            )
            (EVIDENCE / ("INSTANCE_" + identity + ".json")).write_text(
                json.dumps(
                    {
                        "before": old,
                        "new": client.get("http://127.0.0.1:8740/api/instance").json(),
                        "release": json.loads((package / "release.json").read_text("utf8")),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "utf8",
            )
        command(
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "tests.product.live_quality_060",
            *(["--targeted-long"] if patch else []),
        )
        if patch:
            os.environ["NODE_PATH"] = str(ROOT / "frontend/node_modules")
            command(NODE, "tests/product/browser_final_readback.cjs")
            return
        quality = max(EVIDENCE.glob("QUALITY_060_*.json"), key=lambda p: p.stat().st_mtime)
        results = json.loads(quality.read_text("utf8"))
        direct = next(r for r in results["cases"] if r["name"] == "loan_direct")
        resume = EVIDENCE / "FINAL_UI_CURRENT_ANSWER.json"
        resume.write_text(
            json.dumps(
                {"answer": direct["run"]["result"], "same_version_api_evidence": str(quality)},
                ensure_ascii=False,
            ),
            "utf8",
        )
        os.environ["NODE_PATH"] = str(ROOT / "frontend/node_modules")
        command(NODE, "tests/product/browser_navigation.cjs")
        command(NODE, "tests/product/live_050_journey.cjs", resume)
    elif args.operation in {"ui-and-resume", "journey-only"}:
        assert args.resume and args.resume.resolve().is_relative_to(EVIDENCE)
        os.environ["NODE_PATH"] = str(ROOT / "frontend/node_modules")
        if args.operation == "ui-and-resume":
            command(NODE, "tests/product/browser_navigation.cjs")
        command(NODE, "tests/product/live_050_journey.cjs", args.resume)
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
        os.environ["NODE_PATH"] = str(ROOT / "frontend/node_modules")
        command(NODE, "tests/product/live_050_journey.cjs", args.resume)


if __name__ == "__main__":
    main()
