from __future__ import annotations

import hashlib
import base64
import io
import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import filesystem as filesystem_module
from app.ingestion.email_parser import (
    EmailParseError,
    EmailParseOutcome,
    EmailParserPolicy,
    parse_staged_email,
)
from app.ingestion import email_parser as email_parser_module
from app.ingestion.file_validation import (
    AssetAdmissionError,
    AssetAdmissionPolicy,
    admit_source_event_asset,
)
from app.ingestion.source_events import SourceEvent
from app.ingestion.quarantine import AssetStorageError, SecureAssetStore
from app.ingestion import quarantine as quarantine_module
from app.ingestion.parsers import build_default_registry
from app.security.identity import Principal


FIXTURES = Path(__file__).parents[1] / "fixtures" / "ingestion" / "eml"


def _operator(
    *,
    tenant_id: str = "tenant-a",
    region: str = "cn-east",
    roles: list[str] | None = None,
) -> Principal:
    now = datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc)
    return Principal(
        subject="operator-g4",
        tenant_id=tenant_id,
        region=region,
        groups=["knowledge-admin"],
        roles=["rag.operator"] if roles is None else roles,
        issuer="https://identity.example.invalid",
        audience="rag-copilot",
        key_id="demo-key-g4",
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )


def _event(*, name: str, content: bytes, event_id: str = "evt-g4-001") -> SourceEvent:
    return SourceEvent(
        event_id=event_id,
        operation="UPSERT",
        tenant_id="tenant-a",
        region="cn-east",
        source_system="fictional-mailbox",
        source_key=f"mail/{event_id}",
        occurred_at=datetime(2026, 7, 26, 8, 5, tzinfo=timezone.utc),
        content_relpath=name,
        declared_media_type="message/rfc822",
        content_sha256=hashlib.sha256(content).hexdigest(),
        actor_pseudonym="actor-g4",
        acl_groups=("knowledge-readers",),
    )


def _stage_fixture(tmp_path: Path, fixture_name: str):
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    content = (FIXTURES / fixture_name).read_bytes()
    source = source_root / fixture_name
    source.write_bytes(content)
    event = _event(name=fixture_name, content=content)
    receipt = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )
    assert receipt.status == "STAGED"
    return event, receipt, storage_root


def _stage_content(tmp_path: Path, content: bytes, *, name: str = "generated.eml"):
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    source = source_root / name
    source.write_bytes(content)
    event = _event(name=name, content=content)
    receipt = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )
    assert receipt.status == "STAGED"
    return event, receipt, storage_root


def test_only_authorized_matching_staged_receipt_can_enter_mime_parser(
    tmp_path: Path,
) -> None:
    event, receipt, storage_root = _stage_fixture(tmp_path, "plain.eml")

    with pytest.raises(AssetAdmissionError) as denied:
        parse_staged_email(
            event=event,
            principal=_operator(roles=[]),
            receipt=receipt,
            storage_root=tmp_path / "must-not-be-opened",
        )

    assert denied.value.code == "operator_role_required"
    assert not (tmp_path / "must-not-be-opened").exists()

    other_event = event.model_copy(update={"event_id": "evt-g4-other"})
    with pytest.raises(EmailParseError) as mismatch:
        parse_staged_email(
            event=other_event,
            principal=_operator(),
            receipt=receipt,
            storage_root=storage_root,
        )
    assert mismatch.value.code == "receipt_event_mismatch"


def test_tampered_staged_eml_fails_before_mime_result(tmp_path: Path) -> None:
    event, receipt, storage_root = _stage_fixture(tmp_path, "plain.eml")
    assert receipt.stored_relpath is not None
    payload = storage_root / receipt.stored_relpath
    payload.write_bytes(payload.read_bytes() + b"\nTampered.")

    with pytest.raises(EmailParseError) as error:
        parse_staged_email(
            event=event,
            principal=_operator(),
            receipt=receipt,
            storage_root=storage_root,
        )

    assert error.value.code == "staged_asset_integrity_mismatch"


def test_plain_body_and_headers_are_parsed_with_address_redaction(
    tmp_path: Path,
) -> None:
    event, receipt, storage_root = _stage_fixture(tmp_path, "plain.eml")

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.status == "PARSED"
    assert outcome.reason_code == "parsed"
    assert outcome.message is not None
    assert outcome.message.subject == "Fictional plain policy update"
    assert outcome.message.date == "2026-07-25T02:30:00+00:00"
    assert outcome.message.from_redacted == ("[redacted]",)
    assert outcome.message.to_redacted == ("[redacted]",)
    assert outcome.message.cc_redacted == ("[redacted]",)
    assert outcome.message.body_kind == "plain"
    assert "fictional travel approval limit" in outcome.message.body.text.casefold()
    assert outcome.message.attachments == ()
    assert outcome.message.nested_messages == ()


def test_html_fallback_does_not_expose_active_or_remote_elements(
    tmp_path: Path,
) -> None:
    event, receipt, storage_root = _stage_fixture(tmp_path, "html_only.eml")

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.message is not None
    assert outcome.message.body_kind == "html"
    assert "Fictional HTML notice" in outcome.message.body.text
    assert "approved internal request form" in outcome.message.body.text
    assert "fetch(" not in outcome.message.body.text
    assert "remote.example.invalid" not in outcome.message.body.text
    assert "tracker" not in outcome.message.body.text


def test_plain_part_wins_over_html_in_multipart_alternative(
    tmp_path: Path,
) -> None:
    event, receipt, storage_root = _stage_fixture(tmp_path, "alternative.eml")

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.message is not None
    assert outcome.message.body_kind == "plain"
    assert "plain representation is authoritative" in outcome.message.body.text
    assert "HTML representation" not in outcome.message.body.text


def test_html_output_limit_quarantines_root_without_parsed_message(
    tmp_path: Path,
) -> None:
    event, receipt, storage_root = _stage_fixture(tmp_path, "html_only.eml")

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
        policy=EmailParserPolicy(max_html_text_chars=8),
    )

    assert outcome.status == "QUARANTINED"
    assert outcome.reason_code == "html_text_limit"
    assert outcome.message is None
    assert outcome.root_asset.status == "QUARANTINED"
    assert outcome.root_asset.stored_relpath is not None
    assert outcome.root_asset.stored_relpath.endswith("/payload.blob")


def test_attachment_reenters_g3_and_parser_registry_as_child_asset(
    tmp_path: Path,
) -> None:
    event, receipt, storage_root = _stage_fixture(
        tmp_path, "mixed_attachment.eml"
    )

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.status == "PARSED"
    assert outcome.message is not None
    assert len(outcome.message.attachments) == 1
    attachment = outcome.message.attachments[0]
    assert attachment.asset.status == "STAGED"
    assert attachment.asset.parent_asset_id == receipt.asset_id
    assert attachment.asset.original_name_redacted == "[redacted].txt"
    assert attachment.parsed is not None
    assert "privileged tool" in attachment.parsed.text
    assert outcome.reason_code == "parsed"
    assert len(outcome.child_assets) == 1


def test_attachment_parser_consumes_receipt_bound_bytes_not_mutable_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event, receipt, storage_root = _stage_fixture(
        tmp_path, "mixed_attachment.eml"
    )
    registry = build_default_registry()
    original_parse_bytes = registry.parse_bytes

    def race_staged_path(content: bytes, *, suffix: str):
        child_path = next(
            path
            for path in (storage_root / "staged").glob("*/payload.txt")
        )
        original = child_path.read_bytes()
        child_path.write_bytes(b"attacker-controlled replacement")
        try:
            return original_parse_bytes(content, suffix=suffix)
        finally:
            child_path.write_bytes(original)

    monkeypatch.setattr(registry, "parse_bytes", race_staged_path)
    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
        parser_registry=registry,
    )

    assert outcome.status == "PARSED"
    assert outcome.message is not None
    parsed = outcome.message.attachments[0].parsed
    assert parsed is not None
    assert "privileged tool" in parsed.text
    assert "attacker-controlled" not in parsed.text


def test_nested_message_is_child_asset_and_recurses_with_same_session(
    tmp_path: Path,
) -> None:
    event, receipt, storage_root = _stage_fixture(tmp_path, "nested.eml")

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.status == "PARSED"
    assert outcome.message is not None
    assert len(outcome.message.nested_messages) == 1
    nested = outcome.message.nested_messages[0]
    assert nested.subject == "Fictional nested message"
    assert "Nested fictional body" in nested.body.text
    assert len(outcome.child_assets) == 1
    assert outcome.child_assets[0].parent_asset_id == receipt.asset_id
    assert outcome.child_assets[0].verified_media_type == "message/rfc822"


@pytest.mark.parametrize(
    ("policy", "admission_policy", "expected_reason"),
    [
        (
            EmailParserPolicy(max_attachments=0),
            AssetAdmissionPolicy(),
            "attachment_count_limit",
        ),
        (
            EmailParserPolicy(max_attachment_bytes=8),
            AssetAdmissionPolicy(),
            "attachment_size_limit",
        ),
        (
            EmailParserPolicy(max_total_decoded_bytes=8),
            AssetAdmissionPolicy(),
            "attachment_total_bytes_limit",
        ),
        (
            EmailParserPolicy(),
            AssetAdmissionPolicy(max_event_files=1),
            "event_file_count_limit",
        ),
    ],
)
def test_attachment_budgets_fail_closed_before_child_parse(
    tmp_path: Path,
    policy: EmailParserPolicy,
    admission_policy: AssetAdmissionPolicy,
    expected_reason: str,
) -> None:
    event, receipt, storage_root = _stage_fixture(
        tmp_path, "mixed_attachment.eml"
    )

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
        policy=policy,
        admission_policy=admission_policy,
    )

    assert outcome.status == "QUARANTINED"
    assert outcome.reason_code == expected_reason
    assert outcome.message is None
    assert outcome.child_assets == ()


def test_nested_depth_limit_quarantines_before_child_publication(
    tmp_path: Path,
) -> None:
    event, receipt, storage_root = _stage_fixture(tmp_path, "nested.eml")

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
        policy=EmailParserPolicy(max_nested_message_depth=0),
    )

    assert outcome.status == "QUARANTINED"
    assert outcome.reason_code == "nested_message_depth_limit"
    assert outcome.child_assets == ()


def test_structural_mime_defect_quarantines(tmp_path: Path) -> None:
    event, receipt, storage_root = _stage_fixture(
        tmp_path, "malformed_boundary.eml"
    )

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.status == "QUARANTINED"
    assert outcome.reason_code == "malformed_mime_structure"


def test_invalid_base64_quarantines_without_child_asset(tmp_path: Path) -> None:
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Invalid base64\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=\"bad64\"\r\n\r\n"
        b"--bad64\r\nContent-Type: text/plain\r\n\r\nBody\r\n"
        b"--bad64\r\nContent-Type: text/plain; name=\"note.txt\"\r\n"
        b"Content-Disposition: attachment; filename=\"note.txt\"\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\n"
        b"not-valid-@@@\r\n--bad64--\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.status == "QUARANTINED"
    assert outcome.reason_code == "invalid_transfer_encoding"
    assert outcome.child_assets == ()


def test_msg_attachment_is_explicitly_unsupported(tmp_path: Path) -> None:
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: MSG attachment\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=\"msg-boundary\"\r\n\r\n"
        b"--msg-boundary\r\nContent-Type: text/plain\r\n\r\nBody\r\n"
        b"--msg-boundary\r\nContent-Type: application/vnd.ms-outlook\r\n"
        b"Content-Disposition: attachment; filename=\"mail.msg\"\r\n\r\n"
        b"opaque-msg-data\r\n--msg-boundary--\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.status == "QUARANTINED"
    assert outcome.reason_code == "msg_not_supported"


def test_public_trace_is_allowlisted_and_excludes_private_mail_data(
    tmp_path: Path,
) -> None:
    event, receipt, storage_root = _stage_fixture(
        tmp_path, "mixed_attachment.eml"
    )

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )
    serialized = outcome.to_public_trace().model_dump_json()

    assert set(outcome.to_public_trace().model_dump()) == {
        "schema_version",
        "root_asset_id",
        "status",
        "reason_code",
        "parser_name",
        "parser_version",
        "mime_part_count",
        "child_asset_count",
        "decoded_child_bytes",
        "warning_codes",
    }
    for forbidden in (
        "Attachment Sender",
        "attachment-sender@example.invalid",
        "Fictional attachment",
        "private-instructions.txt",
        "privileged tool",
        str(storage_root),
        receipt.content_sha256,
    ):
        assert forbidden not in serialized


def test_encoded_subject_and_non_utf8_body_are_admitted_and_parsed(
    tmp_path: Path,
) -> None:
    content = (
        b"From: =?utf-8?b?5Y+R5Lu25Lq6?= <sender@example.invalid>\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: =?utf-8?b?5rWL6K+V6YKu5Lu2?=\r\n"
        b"Date: Sat, 25 Jul 2026 14:00:00 +0800\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain; charset=iso-8859-1\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n\r\n"
        b"caf\xe9 policy\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.status == "PARSED"
    assert outcome.message is not None
    assert outcome.message.subject == "测试邮件"
    assert "café policy" in outcome.message.body.text
    assert outcome.message.from_redacted == ("[redacted]",)


def test_filename_without_attachment_disposition_is_still_child_asset(
    tmp_path: Path,
) -> None:
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Filename child\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=\"filename-child\"\r\n\r\n"
        b"--filename-child\r\nContent-Type: text/plain\r\n\r\nBody\r\n"
        b"--filename-child\r\nContent-Type: text/plain; name=\"note.txt\"\r\n\r\n"
        b"Child without disposition.\r\n"
        b"--filename-child--\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.message is not None
    assert len(outcome.message.attachments) == 1
    assert outcome.message.attachments[0].parsed is not None
    assert "Child without disposition" in outcome.message.attachments[0].parsed.text


@pytest.mark.parametrize(
    "encoded",
    [
        b"invalid=ZZvalue",
        b"invalid=0Gvalue",
        b"invalid-tail=",
    ],
)
def test_invalid_quoted_printable_is_quarantined(
    tmp_path: Path,
    encoded: bytes,
) -> None:
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Invalid QP\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=\"badqp\"\r\n\r\n"
        b"--badqp\r\nContent-Type: text/plain\r\n\r\nBody\r\n"
        b"--badqp\r\nContent-Type: text/plain; name=\"note.txt\"\r\n"
        b"Content-Disposition: attachment; filename=\"note.txt\"\r\n"
        b"Content-Transfer-Encoding: quoted-printable\r\n\r\n"
        + encoded
        + b"\r\n--badqp--\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.status == "QUARANTINED"
    assert outcome.reason_code == "invalid_transfer_encoding"
    assert outcome.child_assets == ()


def test_base64_padding_exact_size_is_not_overestimated(tmp_path: Path) -> None:
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Padded base64\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=\"padding\"\r\n\r\n"
        b"--padding\r\nContent-Type: text/plain\r\n\r\nBody\r\n"
        b"--padding\r\nContent-Type: text/plain; name=\"one.txt\"\r\n"
        b"Content-Disposition: attachment; filename=\"one.txt\"\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\nTQ==\r\n"
        b"--padding--\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
        policy=EmailParserPolicy(max_attachment_bytes=1),
    )

    assert outcome.status == "PARSED"
    assert outcome.message is not None
    assert outcome.message.attachments[0].parsed is not None
    assert outcome.message.attachments[0].parsed.text == "M"


def test_invalid_date_is_bounded_warning_not_raw_public_text(tmp_path: Path) -> None:
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Invalid date\r\n"
        b"Date: synthetic-private-invalid-date-canary\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nBody\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.status == "PARSED"
    assert outcome.message is not None
    assert outcome.message.date is None
    assert "invalid_date" in outcome.message.warning_codes
    trace_json = outcome.to_public_trace().model_dump_json()
    assert "synthetic-private-invalid-date-canary" not in trace_json


def test_malformed_content_type_defect_is_not_silently_downgraded(
    tmp_path: Path,
) -> None:
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Broken content type\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain; charset\r\n\r\nBody\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.status == "QUARANTINED"
    assert outcome.reason_code == "malformed_mime_structure"


def test_late_child_failure_quarantines_every_previously_staged_child(
    tmp_path: Path,
) -> None:
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Partial publication defense\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=\"partial\"\r\n\r\n"
        b"--partial\r\nContent-Type: text/plain\r\n\r\nBody\r\n"
        b"--partial\r\nContent-Type: text/plain; name=\"first.txt\"\r\n"
        b"Content-Disposition: attachment; filename=\"first.txt\"\r\n\r\n"
        b"First valid child.\r\n"
        b"--partial\r\nContent-Type: application/vnd.ms-outlook\r\n"
        b"Content-Disposition: attachment; filename=\"second.msg\"\r\n\r\n"
        b"Opaque MSG child.\r\n"
        b"--partial--\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.status == "QUARANTINED"
    assert outcome.reason_code == "msg_not_supported"
    assert len(outcome.child_assets) == 2
    assert all(child.status == "QUARANTINED" for child in outcome.child_assets)
    assert list((storage_root / "staged").iterdir()) == []


def test_child_parser_exception_quarantines_root_and_child(tmp_path: Path) -> None:
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Broken PDF child\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=\"broken-pdf\"\r\n\r\n"
        b"--broken-pdf\r\nContent-Type: text/plain\r\n\r\nBody\r\n"
        b"--broken-pdf\r\nContent-Type: application/pdf; name=\"broken.pdf\"\r\n"
        b"Content-Disposition: attachment; filename=\"broken.pdf\"\r\n\r\n"
        b"%PDF-not-a-real-document\r\n"
        b"--broken-pdf--\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.status == "QUARANTINED"
    assert outcome.reason_code == "attachment_parser_failure"
    assert len(outcome.child_assets) == 1
    assert outcome.child_assets[0].status == "QUARANTINED"
    assert list((storage_root / "staged").iterdir()) == []


def test_email_outcome_rejects_cross_field_contradiction(tmp_path: Path) -> None:
    event, receipt, storage_root = _stage_fixture(tmp_path, "plain.eml")
    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )
    payload = outcome.model_dump(mode="python")
    payload["status"] = "QUARANTINED"

    with pytest.raises(ValidationError):
        EmailParseOutcome.model_validate(payload)


def test_quarantine_prepublication_failure_preserves_original_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event, receipt, storage_root = _stage_fixture(tmp_path, "html_only.eml")
    original_write = SecureAssetStore._write_private_file
    calls = 0

    def fail_second_write(path: Path, content: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic transition failure")
        original_write(path, content)

    monkeypatch.setattr(
        SecureAssetStore,
        "_write_private_file",
        staticmethod(fail_second_write),
    )

    with pytest.raises(EmailParseError) as error:
        parse_staged_email(
            event=event,
            principal=_operator(),
            receipt=receipt,
            storage_root=storage_root,
            policy=EmailParserPolicy(max_html_text_chars=8),
        )

    assert error.value.code == "quarantine_transition_failed"
    store = SecureAssetStore(storage_root)
    assert store.read_staged(receipt, byte_limit=receipt.byte_count)
    assert list((storage_root / "quarantine").iterdir()) == []
    assert list((storage_root / ".incoming").iterdir()) == []


@pytest.mark.skipif(
    os.name != "nt",
    reason="Windows sharing-denial retry policy",
)
def test_windows_transient_quarantine_publication_denial_is_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event, receipt, storage_root = _stage_fixture(tmp_path, "html_only.eml")
    original_move = filesystem_module._move_once
    calls = 0

    def transient_denial(
        source_path: Path,
        destination_path: Path,
        *,
        replace: bool,
    ) -> None:
        nonlocal calls
        if Path(source_path).name.startswith("transition_"):
            calls += 1
            if calls <= 2:
                error = PermissionError(13, "synthetic sharing denial")
                error.winerror = 5
                raise error
        original_move(source_path, destination_path, replace=replace)

    monkeypatch.setattr(filesystem_module, "_move_once", transient_denial)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
        policy=EmailParserPolicy(max_html_text_chars=8),
    )

    assert outcome.status == "QUARANTINED"
    assert 3 <= calls <= filesystem_module._WINDOWS_DIRECTORY_MOVE_ATTEMPTS
    assert (storage_root / "quarantine" / receipt.asset_id).is_dir()
    assert list((storage_root / "staged").iterdir()) == []
    assert list((storage_root / ".incoming").iterdir()) == []


def test_published_quarantine_supersedes_stale_staged_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, receipt, storage_root = _stage_fixture(tmp_path, "plain.eml")
    original_rmtree = quarantine_module.shutil.rmtree

    def fail_staged_cleanup(path: Path) -> None:
        if Path(path).name == receipt.asset_id:
            raise OSError("synthetic cleanup failure")
        original_rmtree(path)

    monkeypatch.setattr(quarantine_module.shutil, "rmtree", fail_staged_cleanup)
    store = SecureAssetStore(storage_root)

    with pytest.raises(AssetStorageError) as error:
        store.quarantine_staged(receipt, reason_code="synthetic_failure")

    assert error.value.code == "quarantine_transition_failed"
    assert (storage_root / "quarantine" / receipt.asset_id).is_dir()
    assert (storage_root / "staged" / receipt.asset_id).is_dir()
    with pytest.raises(AssetStorageError) as superseded:
        store.read_staged(receipt, byte_limit=receipt.byte_count)
    assert superseded.value.code == "staged_asset_superseded"

    monkeypatch.undo()
    recovered = store.quarantine_staged(
        receipt,
        reason_code="synthetic_failure",
    )
    assert recovered.status == "QUARANTINED"
    assert recovered.reason_code == "synthetic_failure"
    assert not (storage_root / "staged" / receipt.asset_id).exists()


def test_mime_part_count_and_tree_depth_limits_are_independent(
    tmp_path: Path,
) -> None:
    event, receipt, storage_root = _stage_fixture(tmp_path, "alternative.eml")
    part_limited = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
        policy=EmailParserPolicy(max_mime_parts=2),
    )
    assert part_limited.status == "QUARANTINED"
    assert part_limited.reason_code == "mime_part_count_limit"

    nested_content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: MIME tree\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=\"outer-tree\"\r\n\r\n"
        b"--outer-tree\r\n"
        b"Content-Type: multipart/alternative; boundary=\"inner-tree\"\r\n\r\n"
        b"--inner-tree\r\nContent-Type: text/plain\r\n\r\nBody\r\n"
        b"--inner-tree--\r\n--outer-tree--\r\n"
    )
    other_root = tmp_path / "other"
    other_root.mkdir()
    nested_event, nested_receipt, nested_storage = _stage_content(
        other_root, nested_content
    )
    depth_limited = parse_staged_email(
        event=nested_event,
        principal=_operator(),
        receipt=nested_receipt,
        storage_root=nested_storage,
        policy=EmailParserPolicy(max_mime_tree_depth=1),
    )
    assert depth_limited.status == "QUARANTINED"
    assert depth_limited.reason_code == "mime_tree_depth_limit"


def test_aggregate_parser_output_limit_includes_attachment_text(
    tmp_path: Path,
) -> None:
    event, receipt, storage_root = _stage_fixture(
        tmp_path, "mixed_attachment.eml"
    )

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
        policy=EmailParserPolicy(max_output_chars=512),
    )

    assert outcome.status == "QUARANTINED"
    assert outcome.reason_code == "parser_output_limit"
    assert len(outcome.child_assets) == 1
    assert outcome.child_assets[0].status == "QUARANTINED"


def test_encrypted_mime_is_quarantined_without_body_extraction(
    tmp_path: Path,
) -> None:
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Encrypted\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/encrypted; protocol=\"application/pgp-encrypted\"; "
        b"boundary=\"encrypted\"\r\n\r\n"
        b"--encrypted\r\nContent-Type: application/pgp-encrypted\r\n\r\nVersion: 1\r\n"
        b"--encrypted\r\nContent-Type: application/octet-stream\r\n\r\nciphertext\r\n"
        b"--encrypted--\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.status == "QUARANTINED"
    assert outcome.reason_code == "encrypted_content_not_supported"
    assert outcome.child_assets == ()


def test_archive_attachment_is_quarantined_without_extraction(
    tmp_path: Path,
) -> None:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as package:
        package.writestr("nested.txt", "must not be extracted")
    encoded = base64.b64encode(archive.getvalue())
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Archive child\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=\"archive-child\"\r\n\r\n"
        b"--archive-child\r\nContent-Type: text/plain\r\n\r\nBody\r\n"
        b"--archive-child\r\nContent-Type: application/zip; name=\"nested.zip\"\r\n"
        b"Content-Disposition: attachment; filename=\"nested.zip\"\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\n"
        + encoded
        + b"\r\n--archive-child--\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.status == "QUARANTINED"
    assert outcome.reason_code == "archive_not_supported"
    assert len(outcome.child_assets) == 1
    assert outcome.child_assets[0].status == "QUARANTINED"
    assert not any(path.name == "nested.txt" for path in storage_root.rglob("*"))


def test_stricter_runtime_root_and_child_limits_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event, receipt, storage_root = _stage_fixture(tmp_path, "plain.eml")

    def fail_if_full_read_is_attempted(*args, **kwargs):
        raise AssertionError("known-over-limit email must not be read into memory")

    monkeypatch.setattr(
        SecureAssetStore,
        "read_staged",
        fail_if_full_read_is_attempted,
    )
    root_limited = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
        policy=EmailParserPolicy(max_message_bytes=32),
    )
    assert root_limited.status == "QUARANTINED"
    assert root_limited.reason_code == "message_size_limit"
    monkeypatch.undo()

    child_root = tmp_path / "child-limit"
    child_root.mkdir()
    child_event, child_receipt, child_storage = _stage_fixture(
        child_root, "mixed_attachment.eml"
    )

    def fail_child_admission(**kwargs):
        raise AssetAdmissionError(
            "synthetic_child_failure",
            "Synthetic child admission failure.",
        )

    monkeypatch.setattr(
        email_parser_module,
        "admit_child_asset_bytes",
        fail_child_admission,
    )
    child_limited = parse_staged_email(
        event=child_event,
        principal=_operator(),
        receipt=child_receipt,
        storage_root=child_storage,
    )
    assert child_limited.status == "QUARANTINED"
    assert child_limited.reason_code == "child_admission_failure"
    assert child_limited.child_assets == ()


def test_transfer_encoded_nested_message_is_decoded_before_child_admission(
    tmp_path: Path,
) -> None:
    nested = (
        b"From: nested@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Encoded nested\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Encoded nested body.\r\n"
    )
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Encoded nested outer\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=\"encoded-nested\"\r\n\r\n"
        b"--encoded-nested\r\nContent-Type: text/plain\r\n\r\nOuter body\r\n"
        b"--encoded-nested\r\nContent-Type: message/rfc822\r\n"
        b"Content-Disposition: attachment\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\n"
        + base64.b64encode(nested)
        + b"\r\n--encoded-nested--\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.status == "PARSED"
    assert outcome.message is not None
    assert outcome.message.nested_messages[0].subject == "Encoded nested"
    assert "Encoded nested body" in outcome.message.nested_messages[0].body.text


def test_unencoded_nested_message_preserves_crlf_bytes_for_budget_and_hash(
    tmp_path: Path,
) -> None:
    nested = (
        b"From: nested@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: x\r\n"
        b"Content-Type: text/plain\r\n\r\n"
        b"a\r\na\r\n"
    )
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Nested byte witness\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=\"raw-nested\"\r\n\r\n"
        b"--raw-nested\r\nContent-Type: text/plain\r\n\r\nOuter\r\n"
        b"--raw-nested\r\nContent-Type: message/rfc822\r\n\r\n"
        + nested
        + b"\r\n--raw-nested--\r\n"
    )
    limited_root = tmp_path / "limited"
    limited_root.mkdir()
    event, receipt, storage_root = _stage_content(limited_root, content)
    limited = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
        policy=EmailParserPolicy(max_attachment_bytes=len(nested) - 1),
    )
    assert limited.status == "QUARANTINED"
    assert limited.reason_code == "attachment_size_limit"

    accepted_root = tmp_path / "accepted"
    accepted_root.mkdir()
    event, receipt, storage_root = _stage_content(accepted_root, content)
    accepted = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )
    assert accepted.status == "PARSED"
    assert len(accepted.child_assets) == 1
    assert accepted.child_assets[0].byte_count == len(nested)
    assert accepted.child_assets[0].content_sha256 == hashlib.sha256(nested).hexdigest()


def test_malformed_suppressed_html_cannot_escape_into_extracted_text(
    tmp_path: Path,
) -> None:
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Malformed active HTML\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        b"<html><body><p>Safe prefix.</p>"
        b"<object><script>private-active-canary</object>"
        b"<p>must-stay-suppressed-after-mismatch</p></body></html>\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.status == "PARSED"
    assert outcome.message is not None
    assert "Safe prefix" in outcome.message.body.text
    assert "private-active-canary" not in outcome.message.body.text
    assert "must-stay-suppressed-after-mismatch" not in outcome.message.body.text


def test_header_and_address_budgets_are_fail_closed(tmp_path: Path) -> None:
    content = (
        b"From: a@example.invalid, b@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Header budgets\r\n"
        b"Content-Type: text/plain\r\n\r\nBody\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
        policy=EmailParserPolicy(max_address_count=1),
    )

    assert outcome.status == "QUARANTINED"
    assert outcome.reason_code == "address_count_limit"


def test_explicit_attachment_is_found_inside_alternative_and_single_root(
    tmp_path: Path,
) -> None:
    alternative = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Alternative attachment\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/alternative; boundary=\"alt-attachment\"\r\n\r\n"
        b"--alt-attachment\r\nContent-Type: text/plain\r\n\r\nBody\r\n"
        b"--alt-attachment\r\nContent-Type: text/plain; name=\"note.txt\"\r\n"
        b"Content-Disposition: attachment; filename=\"note.txt\"\r\n\r\n"
        b"Alternative child.\r\n--alt-attachment--\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, alternative)
    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )
    assert outcome.status == "PARSED"
    assert outcome.message is not None
    assert len(outcome.message.attachments) == 1
    assert outcome.message.attachments[0].parsed is not None
    assert "Alternative child" in outcome.message.attachments[0].parsed.text

    single_root = tmp_path / "single-root"
    single_root.mkdir()
    single = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Single attachment\r\n"
        b"Content-Type: text/plain; name=\"only.txt\"\r\n"
        b"Content-Disposition: attachment; filename=\"only.txt\"\r\n\r\n"
        b"Single child.\r\n"
    )
    single_event, single_receipt, single_storage = _stage_content(
        single_root, single
    )
    single_outcome = parse_staged_email(
        event=single_event,
        principal=_operator(),
        receipt=single_receipt,
        storage_root=single_storage,
    )
    assert single_outcome.status == "PARSED"
    assert single_outcome.message is not None
    assert single_outcome.message.body_kind == "none"
    assert len(single_outcome.message.attachments) == 1


def test_duplicate_structural_header_is_quarantined(tmp_path: Path) -> None:
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Duplicate structural header\r\n"
        b"Content-Type: text/plain\r\n"
        b"Content-Type: application/octet-stream\r\n\r\nBody\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )

    assert outcome.status == "QUARANTINED"
    assert outcome.reason_code == "duplicate_structural_header"


def test_child_cleanup_failure_still_quarantines_root_and_blocks_child_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Cleanup failure\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=\"cleanup\"\r\n\r\n"
        b"--cleanup\r\nContent-Type: text/plain\r\n\r\nBody\r\n"
        b"--cleanup\r\nContent-Type: text/plain; name=\"first.txt\"\r\n"
        b"Content-Disposition: attachment; filename=\"first.txt\"\r\n\r\n"
        b"First child.\r\n"
        b"--cleanup\r\nContent-Type: application/vnd.ms-outlook\r\n"
        b"Content-Disposition: attachment; filename=\"second.msg\"\r\n\r\n"
        b"Opaque MSG.\r\n--cleanup--\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)
    original = SecureAssetStore.quarantine_staged
    captured_child = None

    def fail_child_cleanup(self, target, *, reason_code):
        nonlocal captured_child
        if target.parent_asset_id is not None and target.status == "STAGED":
            captured_child = target
            raise AssetStorageError(
                "synthetic_child_cleanup_failure",
                "Synthetic child cleanup failure.",
            )
        return original(self, target, reason_code=reason_code)

    monkeypatch.setattr(
        SecureAssetStore,
        "quarantine_staged",
        fail_child_cleanup,
    )

    with pytest.raises(EmailParseError) as error:
        parse_staged_email(
            event=event,
            principal=_operator(),
            receipt=receipt,
            storage_root=storage_root,
        )

    assert error.value.code == "child_quarantine_failed"
    assert captured_child is not None
    assert (storage_root / "quarantine" / receipt.asset_id).is_dir()
    store = SecureAssetStore(storage_root)
    with pytest.raises(AssetStorageError) as blocked:
        store.read_staged(captured_child, byte_limit=captured_child.byte_count)
    assert blocked.value.code == "staged_parent_quarantined"


def test_outcome_rejects_unreachable_orphan_child(tmp_path: Path) -> None:
    event, receipt, storage_root = _stage_fixture(
        tmp_path, "mixed_attachment.eml"
    )
    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
    )
    payload = outcome.model_dump(mode="python")
    first = outcome.child_assets[0]
    orphan_id = "asset_" + "f" * 32
    orphan = first.model_copy(
        update={
            "asset_id": orphan_id,
            "stored_relpath": f"staged/{orphan_id}/payload.txt",
        }
    )
    payload["child_assets"] = (*outcome.child_assets, orphan)

    with pytest.raises(ValidationError):
        EmailParseOutcome.model_validate(payload)

    wrong_count = outcome.model_copy(update={"decoded_child_bytes": 0})
    with pytest.raises(ValidationError):
        EmailParseOutcome.model_validate(wrong_count.model_dump(mode="python"))

    wrong_mime_count = outcome.model_copy(
        update={"mime_part_count": outcome.mime_part_count + 1}
    )
    with pytest.raises(ValidationError):
        EmailParseOutcome.model_validate(
            wrong_mime_count.model_dump(mode="python")
        )

    assert outcome.message is not None
    duplicated_message = outcome.message.model_copy(
        update={
            "attachments": (
                outcome.message.attachments[0],
                outcome.message.attachments[0],
            )
        }
    )
    duplicated = outcome.model_copy(update={"message": duplicated_message})
    with pytest.raises(ValidationError):
        EmailParseOutcome.model_validate(duplicated.model_dump(mode="python"))


def test_aggregate_output_limit_counts_subject_and_structured_fields(
    tmp_path: Path,
) -> None:
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        + b"Subject: "
        + b"x" * 300
        + b"\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nBody\r\n"
    )
    event, receipt, storage_root = _stage_content(tmp_path, content)

    outcome = parse_staged_email(
        event=event,
        principal=_operator(),
        receipt=receipt,
        storage_root=storage_root,
        policy=EmailParserPolicy(
            max_subject_chars=512,
            max_output_chars=200,
        ),
    )

    assert outcome.status == "QUARANTINED"
    assert outcome.reason_code == "parser_output_limit"
