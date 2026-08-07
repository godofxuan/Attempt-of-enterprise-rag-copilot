from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main_v2 import create_app_v2
from app.runtime.finqa_service_protocol_v2 import (
    load_finqa_service_wiring_protocol_v2,
)
from app.runtime.finqa_service_v2 import safe_finqa_service_snapshot_v2
from tests.api_v2.helpers import OPERATOR_HEADERS
from tests.api_v2.test_finqa_service_wiring_v2 import (
    PRIVATE_TEXT,
    QUESTION,
    _Worker,
    _assembly,
    _post,
    _wait_until,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "external_datasets" / "evidence"
DEFAULT_PROTOCOL = EVIDENCE / "finqa_service_wiring_protocol_v2.json"
DEFAULT_OUTPUT = EVIDENCE / "finqa_service_wiring_public_v2.json"
SOURCE_PATHS = (
    "app/main_v2.py",
    "app/runtime/finqa_service_protocol_v2.py",
    "app/runtime/finqa_service_v2.py",
    "tests/api_v2/test_finqa_service_wiring_v2.py",
    "tests/runtime/test_finqa_service_protocol_v2.py",
    "scripts/audit_finqa_service_wiring_v2.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.resolve().read_bytes()).hexdigest()


def _digest(value: bytes | str) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")


def _paired_api(count: int) -> dict[str, object]:
    off, off_worker, _ = _assembly(mode="OFF")
    enabled, enabled_worker, _ = _assembly(mode="LOCAL_TEST_ONLY")
    response_mismatches = 0
    receipt_mismatches = 0
    response_sha256: list[str] = []
    with TestClient(create_app_v2(off)) as off_client:
        with TestClient(create_app_v2(enabled)) as enabled_client:
            for index in range(count):
                request_id = f"e19-public-pair-{index:02d}"
                left = _post(off_client, request_id)
                right = _post(enabled_client, request_id)
                response_mismatches += int(left.content != right.content)
                receipt_mismatches += int(
                    left.headers["X-Feedback-Receipt"]
                    != right.headers["X-Feedback-Receipt"]
                )
                response_sha256.append(_digest(left.content))
            _wait_until(lambda: enabled_worker.observe_calls == count)
            off_metrics = off_client.get(
                "/observability/metrics", headers=OPERATOR_HEADERS
            ).json()["finqa_typed_observation"]
            enabled_metrics = enabled_client.get(
                "/observability/metrics", headers=OPERATOR_HEADERS
            ).json()["finqa_typed_observation"]
    return {
        "paired_requests": count,
        "response_mismatches": response_mismatches,
        "receipt_mismatches": receipt_mismatches,
        "response_sha256": response_sha256,
        "off_worker_start_calls": off_worker.start_calls,
        "off_worker_observe_calls": off_worker.observe_calls,
        "enabled_worker_start_calls": enabled_worker.start_calls,
        "enabled_worker_observe_calls": enabled_worker.observe_calls,
        "enabled_offered_total": enabled_metrics["dark_observation"]["counters"][
            "offered_total"
        ],
        "enabled_completed_total": enabled_metrics["dark_observation"]["counters"][
            "completed_total"
        ],
        "legacy_generic_offer_calls": enabled_metrics["legacy_generic_offer_calls"],
        "secondary_retrieval_calls": enabled_metrics["secondary_retrieval_calls"],
        "model_calls": enabled_metrics["model_calls"],
        "content_retained": enabled_metrics["content_retained"],
        "off_mode": off_metrics["mode"],
        "enabled_mode": enabled_metrics["mode"],
    }


def _failure_matrix() -> dict[str, object]:
    provider, provider_worker, _ = _assembly(
        mode="LOCAL_TEST_ONLY", worker=_Worker(fail_observe=True)
    )
    with TestClient(create_app_v2(provider)) as client:
        response = _post(client, "e19-public-provider-error")
        _wait_until(lambda: provider_worker.observe_calls == 1)
        _wait_until(
            lambda: safe_finqa_service_snapshot_v2(provider.runtime)["dark_observation"][
                "counters"
            ].get("provider_error_total", 0)
            == 1
        )
        provider_metrics = safe_finqa_service_snapshot_v2(provider.runtime)

    startup, startup_worker, _ = _assembly(
        mode="LOCAL_TEST_ONLY", worker=_Worker(fail_start=True)
    )
    startup_failed_closed = False
    try:
        startup.runtime.start()
    except RuntimeError:
        startup_failed_closed = True
    startup_metrics = safe_finqa_service_snapshot_v2(startup.runtime)

    backpressure_worker = _Worker(block=True)
    backpressure, _, _ = _assembly(
        mode="LOCAL_TEST_ONLY", worker=backpressure_worker, queue_capacity=1
    )
    with TestClient(create_app_v2(backpressure)) as client:
        _post(client, "e19-public-active")
        if not backpressure_worker.started_observing.wait(timeout=2):
            raise RuntimeError("E19 backpressure worker did not start")
        _post(client, "e19-public-queued")
        _post(client, "e19-public-rejected")
        during = safe_finqa_service_snapshot_v2(backpressure.runtime)
        backpressure_worker.release.set()
        _wait_until(
            lambda: safe_finqa_service_snapshot_v2(backpressure.runtime)[
                "dark_observation"
            ]["counters"].get("completed_total", 0)
            == 2
        )
    after = safe_finqa_service_snapshot_v2(backpressure.runtime)

    return {
        "provider_error_http_status": response.status_code,
        "provider_error_total": provider_metrics["dark_observation"]["counters"][
            "provider_error_total"
        ],
        "provider_error_isolated": response.status_code == 200,
        "startup_failed_closed": startup_failed_closed,
        "startup_status": startup_metrics["status"],
        "startup_failure_total": startup_metrics["lifecycle"][
            "startup_failure_total"
        ],
        "startup_worker_close_calls": startup_worker.close_calls,
        "backpressure_total": during["dark_observation"]["counters"][
            "backpressure_total"
        ],
        "pending_during_backpressure": during["resolver"]["pending_context_count"],
        "pending_after_shutdown": after["resolver"]["pending_context_count"],
        "shutdown_status": after["status"],
        "shutdown_worker_close_calls": backpressure_worker.close_calls,
    }


def run_audit(*, protocol_path: Path) -> dict[str, object]:
    protocol, protocol_sha256 = load_finqa_service_wiring_protocol_v2(protocol_path)
    paired = _paired_api(protocol.required_paired_api_requests)
    failures = _failure_matrix()
    source_binding = {
        relative: _sha256(ROOT / relative) for relative in SOURCE_PATHS
    }
    predecessor_binding = {
        "e18_protocol_sha256": _sha256(
            EVIDENCE / "finqa_admitted_context_protocol_v1.json"
        ),
        "e18_public_evidence_sha256": _sha256(
            EVIDENCE / "finqa_admitted_context_public_v1.json"
        ),
    }
    main_source = (ROOT / "app" / "main_v2.py").read_text(encoding="utf-8")
    gate_checks = {
        "predecessor_hashes_match": predecessor_binding
        == {
            "e18_protocol_sha256": protocol.source_e18_protocol_sha256,
            "e18_public_evidence_sha256": protocol.source_e18_public_evidence_sha256,
        },
        "paired_request_count_met": paired["paired_requests"]
        == protocol.required_paired_api_requests,
        "primary_response_byte_identical": paired["response_mismatches"]
        == protocol.required_response_mismatches,
        "feedback_receipt_identical": paired["receipt_mismatches"]
        == protocol.required_receipt_mismatches,
        "default_off_zero_worker": paired["off_worker_start_calls"] == 0
        and paired["off_worker_observe_calls"] == 0,
        "enabled_exactly_once": paired["enabled_worker_start_calls"] == 1
        and paired["enabled_worker_observe_calls"] == paired["paired_requests"]
        and paired["enabled_offered_total"] == paired["paired_requests"]
        and paired["enabled_completed_total"] == paired["paired_requests"],
        "legacy_generic_offer_absent": "service.dark_observation.offer(" not in main_source
        and paired["legacy_generic_offer_calls"] == 0,
        "zero_secondary_retrieval_and_model_calls": paired[
            "secondary_retrieval_calls"
        ]
        == 0
        and paired["model_calls"] == 0,
        "aggregate_only_metrics": paired["content_retained"] is False,
        "provider_error_isolated": failures["provider_error_isolated"]
        and failures["provider_error_total"] == 1,
        "startup_failure_closed": failures["startup_failed_closed"]
        and failures["startup_status"] == "FAILED"
        and failures["startup_worker_close_calls"] == 1,
        "backpressure_bounded": failures["backpressure_total"] == 1
        and failures["pending_during_backpressure"] == 1,
        "shutdown_cleans_context": failures["pending_after_shutdown"] == 0
        and failures["shutdown_status"] == "CLOSED"
        and failures["shutdown_worker_close_calls"] == 1,
    }
    if not all(gate_checks.values()):
        raise RuntimeError("E19 versioned service wiring gate failed")
    payload = {
        "schema_version": "finqa_service_wiring_public_v2",
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "decision": "E19_VERSIONED_SERVICE_WIRING_PASSED_DEFAULT_OFF_NOT_PROMOTED",
        "predecessor_binding": predecessor_binding,
        "source_binding": source_binding,
        "paired_api_aggregates": paired,
        "failure_aggregates": failures,
        "gate_checks": gate_checks,
        "public_content_findings": 0,
        "non_claims": list(protocol.non_claims),
    }
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    forbidden = (QUESTION, PRIVATE_TEXT, "tenant-one", "employee-one")
    findings = sum(item in serialized for item in forbidden)
    if findings != protocol.required_public_content_findings:
        raise RuntimeError("E19 public evidence contains controlled private content")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit E19 versioned service wiring.")
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run_audit(protocol_path=args.protocol.resolve())
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_canonical_bytes(payload))
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
