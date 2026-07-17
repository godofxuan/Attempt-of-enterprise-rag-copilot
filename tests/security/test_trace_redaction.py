import json

from app.security.access import redact_trace_payload, redact_trace_text


def test_redaction_removes_nested_chunk_and_acl_fields() -> None:
    payload = {
        "tool": "search",
        "status": "ok",
        "visible_candidate_count": 2,
        "chunk_id": "secret-chunk",
        "doc_id": "secret-doc",
        "text": "secret salary policy",
        "acl_groups": ["hr_confidential"],
        "nested": {
            "title": "Board compensation",
            "matched_text": "secret salary policy",
            "latency_ms": 2.0,
        },
        "items": [
            {"source_path": "documents/secret.docx", "preview": "secret preview"}
        ],
    }

    redacted = redact_trace_payload(payload)
    serialized = json.dumps(redacted, ensure_ascii=False)

    assert redacted["tool"] == "search"
    assert redacted["status"] == "ok"
    assert redacted["visible_candidate_count"] == 2
    assert redacted["nested"]["latency_ms"] == 2.0
    for secret in [
        "secret-chunk",
        "secret-doc",
        "secret salary",
        "hr_confidential",
        "Board compensation",
        "documents/secret.docx",
        "secret preview",
    ]:
        assert secret not in serialized


def test_redaction_replaces_explicit_denied_values_inside_safe_strings() -> None:
    payload = {
        "output_summary": "candidate secret-doc was denied",
        "reason": "no visible evidence",
    }

    redacted = redact_trace_payload(payload, denied_values=["secret-doc"])

    assert redacted["output_summary"] == "candidate [REDACTED] was denied"
    assert redacted["reason"] == "no visible evidence"


def test_trace_text_masks_common_password_token_and_api_key_forms() -> None:
    value = "password=hunter2 token: abc123 api_key=sk-secret normal=value"

    redacted = redact_trace_text(value)

    assert "hunter2" not in redacted
    assert "abc123" not in redacted
    assert "sk-secret" not in redacted
    assert "normal=value" in redacted


def test_redaction_does_not_mutate_original_payload() -> None:
    payload = {"tool": "open", "nested": {"text": "private"}}

    redacted = redact_trace_payload(payload)

    assert payload == {"tool": "open", "nested": {"text": "private"}}
    assert "text" not in redacted["nested"]
