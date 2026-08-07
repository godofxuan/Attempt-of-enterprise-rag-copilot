try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests

from app.config import get_settings
from app.evaluation.garak_latent_report import GarakLatentReportFixture
from app.evaluation.garak_latent_report_eval import (
    evaluate_garak_latent_report_paired,
    garak_public_limitations,
)
from app.evaluation.indirect_injection_live_runner import (
    LocalOllamaOnlyBoundary,
)
from app.evaluation.indirect_injection_live_writer import (
    resolve_ollama_model_identity,
)
from app.filesystem import atomic_directory_move
from app.ollama_chat import chat_with_ollama


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE = (
    ROOT / "data" / "external_benchmarks" / "garak_latent_report_v1.json"
)
DEFAULT_OUT_ROOT = (
    ROOT / ".private" / "external_security" / "garak_latent_report"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the pinned garak latent-report Guard OFF/ON benchmark."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--execute-live", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute_live:
        raise ValueError("live garak benchmark requires --execute-live")
    if not 1 <= args.timeout_seconds <= 300:
        raise ValueError("timeout must be between 1 and 300 seconds")
    code_revision = _clean_git_revision()
    fixture_path = args.fixture.resolve()
    fixture_bytes = fixture_path.read_bytes()
    fixture = GarakLatentReportFixture.model_validate_json(fixture_bytes)
    fixture_sha256 = hashlib.sha256(fixture_bytes).hexdigest()
    settings = get_settings()

    with LocalOllamaOnlyBoundary(settings.llm_base_url) as boundary:
        session = requests.Session()
        session.trust_env = False
        tags_response = session.get(
            f"{boundary.allowed_origin}/api/tags",
            timeout=30,
        )
        tags_response.raise_for_status()
        model_identity = resolve_ollama_model_identity(
            tags_response.json(),
            args.model,
        )

        def live_chat(model, messages):
            return chat_with_ollama(
                model,
                messages,
                think=False,
                timeout_seconds=args.timeout_seconds,
            )

        result = evaluate_garak_latent_report_paired(
            fixture=fixture,
            fixture_sha256=fixture_sha256,
            model=args.model,
            chat_fn=live_chat,
        )

    result_bytes = _json_bytes(result.model_dump(mode="json"))
    public_summary = {
        "schema_version": "garak_latent_report_public_summary_v1",
        "source": fixture.source.model_dump(mode="json"),
        "fixture_sha256": fixture_sha256,
        "selection_protocol": fixture.selection_protocol,
        "model": model_identity.model_dump(mode="json"),
        "temperature": 0,
        "think": False,
        "retrieval": (
            "Fixed retrieved report content per case; no retrieval ranking changes "
            "between Guard arms."
        ),
        "guard_off": result.guard_off.model_dump(mode="json"),
        "guard_on": result.guard_on.model_dump(mode="json"),
        "limitations": garak_public_limitations(fixture),
    }
    summary_bytes = _json_bytes(public_summary)
    manifest = {
        "schema_version": "garak_latent_report_run_manifest_v1",
        "run_id": args.run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_revision": code_revision,
        "fixture_path": fixture_path.relative_to(ROOT).as_posix(),
        "fixture_sha256": fixture_sha256,
        "model": model_identity.model_dump(mode="json"),
        "command": [sys.executable, *sys.argv[1:]],
        "hardware": {
            "platform": platform.platform(),
            "processor": platform.processor() or "not_reported",
        },
        "egress": {
            "allowed_origin": boundary.allowed_origin,
            "allowed_http_request_count": boundary.allowed_http_request_count,
            "allowed_socket_connect_count": boundary.allowed_socket_connect_count,
            "blocked_attempt_count": boundary.blocked_attempt_count,
        },
        "artifacts": {
            "result.private.json": {
                "sha256": hashlib.sha256(result_bytes).hexdigest(),
                "byte_count": len(result_bytes),
            },
            "summary.json": {
                "sha256": hashlib.sha256(summary_bytes).hexdigest(),
                "byte_count": len(summary_bytes),
            },
        },
    }
    manifest_bytes = _json_bytes(manifest)
    output = _publish(
        root=args.out_root,
        run_id=args.run_id,
        artifacts={
            "manifest.json": manifest_bytes,
            "result.private.json": result_bytes,
            "summary.json": summary_bytes,
        },
    )
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "output_dir": str(output),
                "fixture_sha256": fixture_sha256,
                "model_digest": model_identity.digest,
                "guard_off": result.guard_off.model_dump(mode="json"),
                "guard_on": result.guard_on.model_dump(mode="json"),
                "egress": manifest["egress"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _publish(
    *,
    root: Path,
    run_id: str,
    artifacts: dict[str, bytes],
) -> Path:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / run_id).resolve()
    if target.parent != root or run_id in {".", ".."}:
        raise ValueError("garak run ID is unsafe")
    if target.exists():
        raise FileExistsError(f"garak run already exists: {target}")
    stage = Path(tempfile.mkdtemp(prefix=f".{run_id}.staging-", dir=root))
    try:
        for name, content in artifacts.items():
            (stage / name).write_bytes(content)
        atomic_directory_move(stage, target)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def _clean_git_revision() -> str:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("garak live evaluation requires a clean tracked worktree")
    return revision


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
