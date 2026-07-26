from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from app.lifecycle.operator import (
    LifecycleOperationError,
    LifecycleStatusResult,
)
from scripts.ingest_enterprise_bundle import EXIT_CODES, main
from tests.api_v2.helpers import make_container


class CliOperator:
    def __init__(self, error: LifecycleOperationError | None = None) -> None:
        self.calls = 0
        self.error = error

    def status(self, principal) -> LifecycleStatusResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return LifecycleStatusResult(
            state="EMPTY",
            catalog_sha256="0" * 64,
            catalog_event_count=0,
            live_source_count=0,
            tombstone_count=0,
        )

    def preview(self, request, principal):
        self.calls += 1
        raise AssertionError("preview should not be called")


def test_cli_authentication_fails_before_missing_events_file_is_read(
    capsys,
) -> None:
    operator = CliOperator()
    container = replace(make_container(), lifecycle_operator=operator)

    exit_code = main(
        [
            "preview",
            "--events",
            "definitely-missing.jsonl",
            "--run-id",
            "run-preview",
        ],
        container=container,
        environ={},
    )

    assert exit_code == EXIT_CODES["authorization"]
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "authentication_required"
    assert operator.calls == 0


def test_cli_status_emits_exactly_one_machine_readable_object(capsys) -> None:
    operator = CliOperator()
    container = replace(make_container(), lifecycle_operator=operator)

    exit_code = main(
        ["status"],
        container=container,
        environ={"RAG_OPERATOR_TOKEN": "operator-token"},
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert output.count("\n") == 1
    payload = json.loads(output)
    assert payload["status"] == "COMPLETED"
    assert payload["result"]["state"] == "EMPTY"
    assert operator.calls == 1


def test_cli_maps_domain_categories_to_frozen_exit_codes(capsys) -> None:
    for category, expected in EXIT_CODES.items():
        operator = CliOperator(
            LifecycleOperationError(
                category,
                f"{category}_failure",
                "The operation failed.",
            )
        )
        container = replace(make_container(), lifecycle_operator=operator)

        exit_code = main(
            ["status"],
            container=container,
            environ={"RAG_OPERATOR_TOKEN": "operator-token"},
        )

        assert exit_code == expected
        payload = json.loads(capsys.readouterr().out)
        assert payload["error"]["category"] == category


def test_cli_rejects_duplicate_event_keys_before_operator_call(
    tmp_path: Path,
    capsys,
) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text(
        '{"event_id":"first","event_id":"second"}\n',
        encoding="utf-8",
    )
    operator = CliOperator()
    container = replace(make_container(), lifecycle_operator=operator)

    exit_code = main(
        [
            "preview",
            "--events",
            str(events),
            "--run-id",
            "run-invalid-events",
        ],
        container=container,
        environ={"RAG_OPERATOR_TOKEN": "operator-token"},
    )

    assert exit_code == EXIT_CODES["schema"]
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "events_schema_invalid"
    assert operator.calls == 0


def test_cli_status_maps_unclassified_failure_to_manifest_category(
    capsys,
) -> None:
    class UnexpectedStatusOperator(CliOperator):
        def status(self, principal):
            self.calls += 1
            raise RuntimeError("D:/private/catalog secret-token")

    operator = UnexpectedStatusOperator()
    container = replace(make_container(), lifecycle_operator=operator)

    exit_code = main(
        ["status"],
        container=container,
        environ={"RAG_OPERATOR_TOKEN": "operator-token"},
    )

    assert exit_code == EXIT_CODES["manifest"]
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["error"] == {
        "category": "manifest",
        "code": "lifecycle_status_failed",
    }
    assert "private" not in output.casefold()
    assert "token" not in output.casefold()
