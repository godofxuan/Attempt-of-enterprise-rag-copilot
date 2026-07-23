from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from app.config import get_settings
from app.security.demo_identity import (
    EMERGENCY_RETIRE_CONFIRMATION,
    activate_demo_identity,
    demo_identity_status,
    initialize_demo_identity,
    retire_demo_identity_key,
    rotate_demo_identity,
)
from app.security.identity import IdentityConfigurationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage the ignored local JWT/JWKS demo identity source."
    )
    parser.add_argument(
        "--directory",
        type=Path,
        default=None,
        help="Identity directory; defaults to the configured JWKS parent.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create a new local identity source.")
    init.add_argument("--force", action="store_true")
    init.add_argument("--token-lifetime-seconds", type=int, default=900)

    rotate = subparsers.add_parser(
        "rotate",
        help="Stage a new verification key without replacing client tokens.",
    )

    activate = subparsers.add_parser(
        "activate",
        help="Activate a staged key after the restarted API accepts its probe.",
    )
    activate.add_argument("--kid", required=True)
    activate.add_argument("--token-lifetime-seconds", type=int, default=900)
    activate.add_argument(
        "--api-base-url",
        default="http://127.0.0.1:8000",
    )
    activate.add_argument("--timeout-seconds", type=float, default=5.0)

    retire = subparsers.add_parser(
        "retire",
        help="Retire one non-active key after the overlap window.",
    )
    retire.add_argument("--kid", required=True)
    retire.add_argument(
        "--emergency-revoke",
        action="store_true",
        help=(
            "Break the overlap window and remove the key from the next API "
            "snapshot; restart the API to reject still-live tokens."
        ),
    )
    retire.add_argument(
        "--confirm-emergency-revoke",
        default=None,
        help=(
            "Required exact phrase for --emergency-revoke: "
            f"{EMERGENCY_RETIRE_CONFIRMATION}"
        ),
    )

    subparsers.add_parser("status", help="Print non-secret keyring status.")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    requested_directory = args.directory or settings.identity_jwks_path.parent
    directory = Path(os.path.abspath(requested_directory))
    try:
        if args.command == "init":
            status = initialize_demo_identity(
                directory,
                issuer=settings.identity_issuer,
                audience=settings.identity_audience,
                token_lifetime_seconds=args.token_lifetime_seconds,
                force=args.force,
            )
        elif args.command == "rotate":
            status = rotate_demo_identity(directory)
        elif args.command == "activate":
            status = activate_demo_identity(
                directory,
                kid=args.kid,
                token_lifetime_seconds=args.token_lifetime_seconds,
                snapshot_verifier=lambda token, expected_kid: (
                    _api_snapshot_accepts_pending_key(
                        base_url=args.api_base_url,
                        token=token,
                        expected_kid=expected_kid,
                        timeout_seconds=args.timeout_seconds,
                    )
                ),
            )
        elif args.command == "retire":
            if (
                args.emergency_revoke
                and args.confirm_emergency_revoke
                != EMERGENCY_RETIRE_CONFIRMATION
            ):
                raise ValueError(
                    "emergency revocation requires the exact confirmation phrase"
                )
            if (
                not args.emergency_revoke
                and args.confirm_emergency_revoke is not None
            ):
                raise ValueError(
                    "emergency confirmation requires --emergency-revoke"
                )
            status = retire_demo_identity_key(
                directory,
                kid=args.kid,
                emergency_revoke=args.emergency_revoke,
                emergency_confirmation=args.confirm_emergency_revoke,
            )
        else:
            status = demo_identity_status(directory)
    except (ValueError, FileExistsError, IdentityConfigurationError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "active_kid": status.active_kid,
                "key_ids": list(status.key_ids),
                "persona_count": status.persona_count,
                "pending_kid": status.pending_kid,
                "restart_required": status.restart_required,
                "retirement_not_before": {
                    kid: deadline
                    for kid, deadline in status.retirement_not_before
                },
                "emergency_revocation_count": (
                    status.emergency_revocation_count
                ),
                "emergency_revocations": [
                    {"kid": kid, "revoked_at": revoked_at}
                    for kid, revoked_at in status.emergency_revocations
                ],
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )


def _api_snapshot_accepts_pending_key(
    *,
    base_url: str,
    token: str,
    expected_kid: str,
    timeout_seconds: float,
) -> bool:
    connection: http.client.HTTPConnection | None = None
    try:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or not 0 < timeout_seconds <= 30
        ):
            return False
        port = parsed.port or 80
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            port,
            timeout=timeout_seconds,
        )
        connection.request(
            "GET",
            "/identity/me",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        response = connection.getresponse()
        payload = response.read(16_385)
        if response.status != 200 or len(payload) > 16_384:
            return False
        decoded = json.loads(payload.decode("utf-8"))
        return (
            isinstance(decoded, dict)
            and decoded.get("key_id") == expected_kid
        )
    except (
        http.client.HTTPException,
        json.JSONDecodeError,
        OSError,
        UnicodeDecodeError,
        ValueError,
    ):
        return False
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()


__all__ = ["build_parser", "main"]
