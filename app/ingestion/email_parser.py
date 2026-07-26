from __future__ import annotations

import base64
import hashlib
import quopri
import re
from dataclasses import dataclass
from datetime import timezone
from email import policy as email_policy
from email.errors import (
    CloseBoundaryNotFoundDefect,
    FirstHeaderLineIsContinuationDefect,
    InvalidDateDefect,
    InvalidMultipartContentTransferEncodingDefect,
    MissingHeaderBodySeparatorDefect,
    MultipartInvariantViolationDefect,
    NoBoundaryInMultipartDefect,
    NonPrintableDefect,
    ObsoleteHeaderDefect,
    StartBoundaryNotFoundDefect,
)
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.domain.documents import (
    DocumentParseError,
    ParseResult,
    ParseWarning,
    ParsedSection,
    SourceLocator,
)
from app.ingestion.file_validation import (
    AssetAdmissionError,
    AssetAdmissionPolicy,
    DEFAULT_ASSET_ADMISSION_POLICY,
    admit_child_asset_bytes,
    validate_asset_admission_context,
)
from app.ingestion.parsers import ParserRegistry, build_default_registry
from app.ingestion.quarantine import (
    AssetStorageError,
    IngestedAsset,
    SecureAssetStore,
)
from app.ingestion.source_events import SourceEvent
from app.security.identity import Principal


EMAIL_PARSER_NAME = "stdlib-email"
EMAIL_PARSER_VERSION = "1.0"
_NESTED_SERIALIZATION_POLICY = email_policy.default.clone(
    linesep="\r\n",
    refold_source="none",
)
_SAFE_WARNING_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RECOVERABLE_DEFECTS = (
    InvalidDateDefect,
    NonPrintableDefect,
    ObsoleteHeaderDefect,
)
_BLOCK_ELEMENTS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
    }
)
_SUPPRESSED_ELEMENTS = frozenset(
    {
        "applet",
        "audio",
        "canvas",
        "iframe",
        "noscript",
        "object",
        "picture",
        "script",
        "style",
        "svg",
        "template",
        "video",
    }
)
_IGNORED_VOID_ELEMENTS = frozenset({"embed", "link", "meta", "source"})


class EmailParseError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class EmailParserPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["email_parser_policy_v1"] = "email_parser_policy_v1"
    max_message_bytes: int = Field(default=16 * 1024 * 1024, ge=1)
    max_mime_parts: int = Field(default=256, ge=1, le=10000)
    max_mime_tree_depth: int = Field(default=32, ge=1, le=256)
    max_nested_message_depth: int = Field(default=4, ge=0, le=64)
    max_attachments: int = Field(default=16, ge=0, le=1024)
    max_attachment_bytes: int = Field(default=8 * 1024 * 1024, ge=1)
    max_total_decoded_bytes: int = Field(default=16 * 1024 * 1024, ge=1)
    max_html_source_chars: int = Field(default=1024 * 1024, ge=1)
    max_html_text_chars: int = Field(default=512 * 1024, ge=1)
    max_output_chars: int = Field(default=2 * 1024 * 1024, ge=1)
    max_subject_chars: int = Field(default=4096, ge=1, le=65536)
    max_headers: int = Field(default=200, ge=1, le=10000)
    max_header_chars: int = Field(default=16 * 1024, ge=1, le=1024 * 1024)
    max_address_count: int = Field(default=256, ge=1, le=10000)
    max_warning_count: int = Field(default=32, ge=0, le=1024)


DEFAULT_EMAIL_PARSER_POLICY = EmailParserPolicy()


class EmailAttachmentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset: IngestedAsset
    media_type: str = Field(min_length=1, max_length=128)
    parsed: ParseResult | None = None

    @model_validator(mode="after")
    def validate_attachment(self) -> EmailAttachmentResult:
        if self.asset.status != "STAGED" or self.parsed is None:
            raise ValueError("parsed email attachment fields are inconsistent")
        return self


class ParsedEmailMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: str = Field(pattern=r"^asset_[0-9a-f]{32}$")
    subject: str
    from_redacted: tuple[str, ...] = ()
    to_redacted: tuple[str, ...] = ()
    cc_redacted: tuple[str, ...] = ()
    date: str | None = None
    body_kind: Literal["plain", "html", "none"]
    body: ParseResult
    mime_part_count: int = Field(ge=1)
    attachments: tuple[EmailAttachmentResult, ...] = ()
    nested_messages: tuple[ParsedEmailMessage, ...] = ()
    warning_codes: tuple[str, ...] = ()

    @field_validator("warning_codes")
    @classmethod
    def validate_warning_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)) or any(
            _SAFE_WARNING_CODE.fullmatch(value) is None for value in values
        ):
            raise ValueError("warning_codes must be unique safe reason codes")
        return values


class EmailPublicTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["email_public_trace_v1"] = "email_public_trace_v1"
    root_asset_id: str = Field(pattern=r"^asset_[0-9a-f]{32}$")
    status: Literal["PARSED", "QUARANTINED"]
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    parser_name: Literal["stdlib-email"] = EMAIL_PARSER_NAME
    parser_version: str = EMAIL_PARSER_VERSION
    mime_part_count: int = Field(ge=0)
    child_asset_count: int = Field(ge=0)
    decoded_child_bytes: int = Field(ge=0)
    warning_codes: tuple[str, ...] = ()

    @field_validator("warning_codes")
    @classmethod
    def validate_warning_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)) or any(
            _SAFE_WARNING_CODE.fullmatch(value) is None for value in values
        ):
            raise ValueError("warning_codes must be unique safe reason codes")
        return values


class EmailParseOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["PARSED", "QUARANTINED"]
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    root_asset: IngestedAsset
    message: ParsedEmailMessage | None = None
    child_assets: tuple[IngestedAsset, ...] = ()
    mime_part_count: int = Field(ge=0)
    decoded_child_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_outcome(self) -> EmailParseOutcome:
        if self.status == "PARSED":
            if (
                self.reason_code != "parsed"
                or self.root_asset.status != "STAGED"
                or self.message is None
            ):
                raise ValueError("parsed email outcome fields are inconsistent")
        elif (
            self.reason_code == "parsed"
            or self.root_asset.status != "QUARANTINED"
            or self.root_asset.reason_code != self.reason_code
            or self.message is not None
        ):
            raise ValueError("quarantined email outcome fields are inconsistent")
        if any(
            child.parent_event_id != self.root_asset.parent_event_id
            for child in self.child_assets
        ):
            raise ValueError("email child event lineage is inconsistent")
        child_ids = [child.asset_id for child in self.child_assets]
        if len(child_ids) != len(set(child_ids)):
            raise ValueError("email child identities must be unique")
        by_id = {child.asset_id: child for child in self.child_assets}
        for child in self.child_assets:
            parent_id = child.parent_asset_id
            seen = {child.asset_id}
            while parent_id != self.root_asset.asset_id:
                if parent_id is None or parent_id in seen or parent_id not in by_id:
                    raise ValueError("email child parent chain is incomplete")
                seen.add(parent_id)
                parent_id = by_id[parent_id].parent_asset_id
        if self.status == "PARSED" and any(
            child.status != "STAGED" for child in self.child_assets
        ):
            raise ValueError("parsed email children must remain staged")
        if self.status == "QUARANTINED" and any(
            child.status != "QUARANTINED" for child in self.child_assets
        ):
            raise ValueError("failed email children must be quarantined")
        if self.message is not None and self.message.asset_id != self.root_asset.asset_id:
            raise ValueError("parsed email root identity is inconsistent")
        if self.message is not None:
            reachable: set[str] = set()

            def add_reachable(asset_id: str) -> None:
                if asset_id in reachable:
                    raise ValueError(
                        "email parsed tree contains a duplicate child reference"
                    )
                reachable.add(asset_id)

            def visit(message: ParsedEmailMessage) -> None:
                for attachment in message.attachments:
                    stored = by_id.get(attachment.asset.asset_id)
                    if (
                        stored != attachment.asset
                        or stored.parent_asset_id != message.asset_id
                    ):
                        raise ValueError("email attachment lineage is inconsistent")
                    add_reachable(stored.asset_id)
                for nested in message.nested_messages:
                    stored = by_id.get(nested.asset_id)
                    if stored is None or stored.parent_asset_id != message.asset_id:
                        raise ValueError("nested email lineage is inconsistent")
                    add_reachable(stored.asset_id)
                    visit(nested)

            visit(self.message)
            if reachable != set(child_ids):
                raise ValueError("email parsed tree does not cover every child")
        published_child_bytes = sum(child.byte_count for child in self.child_assets)
        if (
            self.status == "PARSED"
            and self.decoded_child_bytes != published_child_bytes
        ) or (
            self.status == "QUARANTINED"
            and self.decoded_child_bytes < published_child_bytes
        ):
            raise ValueError("email decoded child byte accounting is inconsistent")
        if (
            self.status == "PARSED"
            and self.message is not None
            and self.mime_part_count != self.message.mime_part_count
        ):
            raise ValueError("parsed email MIME part accounting is inconsistent")
        return self

    def to_public_trace(self) -> EmailPublicTrace:
        warning_codes = (
            self.message.warning_codes if self.message is not None else ()
        )
        return EmailPublicTrace(
            root_asset_id=self.root_asset.asset_id,
            status=self.status,
            reason_code=self.reason_code,
            mime_part_count=self.mime_part_count,
            child_asset_count=len(self.child_assets),
            decoded_child_bytes=self.decoded_child_bytes,
            warning_codes=warning_codes,
        )


class _QuarantineRequired(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class _ParseSession:
    policy: EmailParserPolicy
    admission_policy: AssetAdmissionPolicy
    root_bytes: int
    mime_part_count: int = 0
    child_asset_count: int = 0
    decoded_child_bytes: int = 0
    output_chars: int = 0

    def visit_part(self, depth: int) -> None:
        if depth > self.policy.max_mime_tree_depth:
            raise _QuarantineRequired("mime_tree_depth_limit")
        self.mime_part_count += 1
        if self.mime_part_count > self.policy.max_mime_parts:
            raise _QuarantineRequired("mime_part_count_limit")

    def reserve_child(self, byte_count: int) -> None:
        next_count = self.child_asset_count + 1
        if next_count > self.policy.max_attachments:
            raise _QuarantineRequired("attachment_count_limit")
        if 1 + next_count > self.admission_policy.max_event_files:
            raise _QuarantineRequired("event_file_count_limit")
        if byte_count > self.policy.max_attachment_bytes:
            raise _QuarantineRequired("attachment_size_limit")
        next_decoded = self.decoded_child_bytes + byte_count
        if next_decoded > self.policy.max_total_decoded_bytes:
            raise _QuarantineRequired("attachment_total_bytes_limit")
        if self.root_bytes + next_decoded > self.admission_policy.max_event_bytes:
            raise _QuarantineRequired("event_byte_limit")
        self.child_asset_count = next_count
        self.decoded_child_bytes = next_decoded

    def reserve_output(self, char_count: int) -> None:
        next_output = self.output_chars + char_count
        if next_output > self.policy.max_output_chars:
            raise _QuarantineRequired("parser_output_limit")
        self.output_chars = next_output


def _output_text_chars(value) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, BaseModel):
        return _output_text_chars(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return sum(
            _output_text_chars(key) + _output_text_chars(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return sum(_output_text_chars(item) for item in value)
    return 0


@dataclass(frozen=True)
class _PreparedChild:
    content: bytes
    filename_suffix: str
    declared_media_type: str
    nested: _PreparedMessage | None = None


@dataclass(frozen=True)
class _PreparedMessage:
    subject: str
    from_redacted: tuple[str, ...]
    to_redacted: tuple[str, ...]
    cc_redacted: tuple[str, ...]
    date: str | None
    body_kind: Literal["plain", "html", "none"]
    body: ParseResult
    mime_part_count: int
    warning_codes: tuple[str, ...]
    children: tuple[_PreparedChild, ...]


class _SafeHTMLTextExtractor(HTMLParser):
    def __init__(self, *, char_limit: int) -> None:
        super().__init__(convert_charrefs=True)
        self._char_limit = char_limit
        self._suppressed_tags: list[str] = []
        self._parts: list[str] = []
        self._char_count = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        normalized = tag.casefold()
        if normalized in _IGNORED_VOID_ELEMENTS:
            return
        if normalized in _SUPPRESSED_ELEMENTS:
            self._suppressed_tags.append(normalized)
            return
        if not self._suppressed_tags and normalized in _BLOCK_ELEMENTS:
            self._append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        normalized = tag.casefold()
        if normalized in _IGNORED_VOID_ELEMENTS:
            return
        if not self._suppressed_tags and normalized in _BLOCK_ELEMENTS:
            self._append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if (
            normalized in _SUPPRESSED_ELEMENTS
            and self._suppressed_tags
            and normalized == self._suppressed_tags[-1]
        ):
            self._suppressed_tags.pop()
            return
        if not self._suppressed_tags and normalized in _BLOCK_ELEMENTS:
            self._append("\n")

    def handle_data(self, data: str) -> None:
        if not self._suppressed_tags:
            self._append(data)

    def _append(self, value: str) -> None:
        self._char_count += len(value)
        if self._char_count > self._char_limit:
            raise _QuarantineRequired("html_text_limit")
        self._parts.append(value)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self._parts).splitlines())
        return "\n".join(line for line in lines if line).strip()


def _validate_receipt(
    *,
    event: SourceEvent,
    receipt: IngestedAsset,
) -> IngestedAsset:
    try:
        validated = IngestedAsset.model_validate(
            receipt.model_dump(mode="python")
        )
    except (AttributeError, ValidationError) as exc:
        raise EmailParseError(
            "staged_receipt_invalid",
            "The staged email receipt is invalid.",
        ) from exc
    if validated.parent_event_id != event.event_id:
        raise EmailParseError(
            "receipt_event_mismatch",
            "The staged email receipt does not belong to this event.",
        )
    if (
        validated.parent_asset_id is not None
        or validated.status != "STAGED"
        or validated.content_sha256 != event.content_sha256
        or validated.declared_media_type != event.declared_media_type
        or validated.declared_media_type != "message/rfc822"
        or validated.verified_media_type != "message/rfc822"
        or validated.stored_relpath is None
        or not validated.stored_relpath.endswith("/payload.eml")
    ):
        raise EmailParseError(
            "staged_eml_required",
            "A verified staged EML receipt is required.",
        )
    return validated


def _defect_code(defect: object) -> str:
    name = type(defect).__name__
    code = re.sub(r"(?<!^)(?=[A-Z])", "_", name).casefold()
    if code.endswith("_defect"):
        code = code[: -len("_defect")]
    return f"mime_{code}"[:64]


def _inspect_structure(
    message: EmailMessage,
    *,
    session: _ParseSession,
    depth: int = 0,
    warning_codes: list[str],
) -> None:
    session.visit_part(depth)
    raw_headers = [name.casefold() for name, _ in message.raw_items()]
    for singleton in (
        "content-type",
        "content-transfer-encoding",
        "content-disposition",
        "mime-version",
    ):
        if raw_headers.count(singleton) > 1:
            raise _QuarantineRequired("duplicate_structural_header")
    content_type = message.get_content_type().casefold()
    if content_type in {
        "multipart/encrypted",
        "application/pkcs7-mime",
        "application/x-pkcs7-mime",
    }:
        raise _QuarantineRequired("encrypted_content_not_supported")

    defects = list(message.defects)
    for header in message.values():
        defects.extend(getattr(header, "defects", ()))
    for defect in defects:
        if not isinstance(defect, _RECOVERABLE_DEFECTS):
            raise _QuarantineRequired("malformed_mime_structure")
        code = _defect_code(defect)
        if _SAFE_WARNING_CODE.fullmatch(code) and code not in warning_codes:
            warning_codes.append(code)
        if len(warning_codes) > session.policy.max_warning_count:
            raise _QuarantineRequired("mime_warning_count_limit")

    if message.is_multipart() and content_type != "message/rfc822":
        for part in message.iter_parts():
            _inspect_structure(
                part,
                session=session,
                depth=depth + 1,
                warning_codes=warning_codes,
            )


def _raw_payload_bytes(
    part: EmailMessage,
    *,
    byte_limit: int,
    size_reason: str = "decoded_part_size_limit",
) -> bytes:
    transfer_encoding = (part.get("Content-Transfer-Encoding") or "7bit").casefold()
    raw = part.get_payload()
    if isinstance(raw, list):
        raise _QuarantineRequired("malformed_mime_structure")
    if transfer_encoding in {"", "7bit", "8bit", "binary"}:
        decoded = part.get_payload(decode=True)
        if decoded is None:
            if isinstance(raw, bytes):
                decoded = raw
            else:
                try:
                    decoded = raw.encode("ascii", "surrogateescape")
                except UnicodeEncodeError as exc:
                    raise _QuarantineRequired("mime_text_decode_error") from exc
        if len(decoded) > byte_limit:
            raise _QuarantineRequired(size_reason)
        return decoded

    if isinstance(raw, bytes):
        encoded = raw
    else:
        try:
            encoded = raw.encode("ascii", "strict")
        except UnicodeEncodeError as exc:
            raise _QuarantineRequired("invalid_transfer_encoding") from exc

    if transfer_encoding == "base64":
        compact = b"".join(encoded.split())
        if len(compact) % 4 != 0:
            raise _QuarantineRequired("invalid_transfer_encoding")
        padding = len(compact) - len(compact.rstrip(b"="))
        if padding > 2 or b"=" in compact[:-padding or None]:
            raise _QuarantineRequired("invalid_transfer_encoding")
        estimated = (len(compact) // 4) * 3 - padding
        if estimated > byte_limit:
            raise _QuarantineRequired(size_reason)
        try:
            decoded = base64.b64decode(compact, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise _QuarantineRequired("invalid_transfer_encoding") from exc
    elif transfer_encoding == "quoted-printable":
        if len(encoded) > byte_limit:
            raise _QuarantineRequired(size_reason)
        if re.search(rb"=(?![0-9A-Fa-f]{2}|\r?\n)", encoded):
            raise _QuarantineRequired("invalid_transfer_encoding")
        decoded = quopri.decodestring(encoded)
    else:
        raise _QuarantineRequired("unsupported_transfer_encoding")

    if len(decoded) > byte_limit:
        raise _QuarantineRequired(size_reason)
    return decoded


def _decode_text_part(
    part: EmailMessage,
    *,
    byte_limit: int,
    char_limit: int,
) -> str:
    payload = _raw_payload_bytes(part, byte_limit=byte_limit)
    charset = part.get_content_charset() or "us-ascii"
    try:
        text = payload.decode(charset, errors="strict")
    except (LookupError, UnicodeDecodeError) as exc:
        raise _QuarantineRequired("mime_text_decode_error") from exc
    if len(text) > char_limit:
        raise _QuarantineRequired("parser_output_limit")
    return text


def _body_result(
    message: EmailMessage,
    *,
    parser_policy: EmailParserPolicy,
    warning_codes: list[str],
) -> tuple[Literal["plain", "html", "none"], ParseResult]:
    body_part = message.get_body(preferencelist=("plain", "html"))
    if body_part is not None and (
        body_part.get_filename() is not None
        or body_part.get_content_disposition() == "attachment"
    ):
        body_part = None
    if (
        body_part is None
        and message.get_content_type() in {"text/plain", "text/html"}
        and message.get_filename() is None
        and message.get_content_disposition() != "attachment"
    ):
        body_part = message

    if body_part is None:
        warning = ParseWarning(
            code="empty_email_body",
            message="The email contains no extractable body.",
            severity="warning",
        )
        return (
            "none",
            ParseResult(
                text="",
                sections=[],
                headings=[],
                tables=[],
                metadata={"body_kind": "none"},
                source_location="[redacted].eml",
                parse_warnings=[warning],
                parser_name=EMAIL_PARSER_NAME,
                parser_version=EMAIL_PARSER_VERSION,
            ),
        )

    content_type = body_part.get_content_type()
    raw_text = _decode_text_part(
        body_part,
        byte_limit=parser_policy.max_message_bytes,
        char_limit=parser_policy.max_output_chars,
    )
    if content_type == "text/plain":
        body_kind: Literal["plain", "html", "none"] = "plain"
        text = raw_text.strip()
    elif content_type == "text/html":
        body_kind = "html"
        if len(raw_text) > parser_policy.max_html_source_chars:
            raise _QuarantineRequired("html_source_limit")
        extractor = _SafeHTMLTextExtractor(
            char_limit=parser_policy.max_html_text_chars
        )
        try:
            extractor.feed(raw_text)
            extractor.close()
        except _QuarantineRequired:
            raise
        except Exception as exc:
            raise _QuarantineRequired("html_parse_failure") from exc
        text = extractor.text()
    else:
        raise _QuarantineRequired("unsupported_body_media_type")

    warnings = [
        ParseWarning(
            code=code,
            message="A recoverable MIME defect was observed.",
            severity="warning",
        )
        for code in warning_codes
    ]
    if not text:
        warnings.append(
            ParseWarning(
                code="empty_email_body",
                message="The email body produced no text.",
                severity="warning",
            )
        )
    sections = (
        [
            ParsedSection(
                heading="Email body",
                level=0,
                path=["Email body"],
                text=text,
                locator=SourceLocator(
                    kind="line",
                    start=1,
                    end=max(1, len(text.splitlines())),
                    label="email body",
                ),
            )
        ]
        if text
        else []
    )
    return (
        body_kind,
        ParseResult(
            text=text,
            sections=sections,
            headings=[],
            tables=[],
            metadata={"body_kind": body_kind},
            source_location="[redacted].eml",
            parse_warnings=warnings,
            parser_name=EMAIL_PARSER_NAME,
            parser_version=EMAIL_PARSER_VERSION,
        ),
    )


def _redacted_addresses(
    message: EmailMessage,
    header: str,
    *,
    max_count: int,
) -> tuple[str, ...]:
    values = message.get_all(header, [])
    addresses = [address for _, address in getaddresses(values) if address]
    if len(addresses) > max_count:
        raise _QuarantineRequired("address_count_limit")
    return tuple("[redacted]" for _ in addresses)


def _canonical_date(message: EmailMessage, warning_codes: list[str]) -> str | None:
    value = message.get("Date")
    if value is None:
        return None
    try:
        parsed = parsedate_to_datetime(str(value))
    except (TypeError, ValueError, OverflowError):
        if "invalid_date" not in warning_codes:
            warning_codes.append("invalid_date")
        return None
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        if "invalid_date" not in warning_codes:
            warning_codes.append("invalid_date")
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _attachment_suffix(part: EmailMessage) -> str:
    filename = part.get_filename()
    if filename:
        normalized = str(filename).replace("\\", "/")
        return PurePosixPath(normalized).suffix.casefold()
    by_media_type = {
        "text/plain": ".txt",
        "text/html": ".html",
        "text/csv": ".csv",
        "application/x-ndjson": ".jsonl",
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
            ".docx"
        ),
        "message/rfc822": ".eml",
    }
    return by_media_type.get(part.get_content_type().casefold(), "")


def _attachment_parts(message: EmailMessage) -> tuple[EmailMessage, ...]:
    parts: list[EmailMessage] = []

    def add(part: EmailMessage) -> None:
        if all(existing is not part for existing in parts):
            parts.append(part)

    if message.is_multipart():
        for part in message.iter_attachments():
            add(part)

    def find_explicit(part: EmailMessage, *, root: bool = False) -> None:
        content_type = part.get_content_type().casefold()
        if content_type == "message/rfc822" and not root:
            add(part)
            return
        if part.is_multipart():
            for child in part.iter_parts():
                find_explicit(child)
            return
        if (
            part.get_filename() is not None
            or part.get_content_disposition() == "attachment"
            or (
                root
                and content_type not in {"text/plain", "text/html"}
            )
        ):
            add(part)

    find_explicit(message, root=True)
    body_candidate = message.get_body(preferencelist=("plain", "html"))
    if body_candidate is not None and (
        body_candidate.get_filename() is not None
        or body_candidate.get_content_disposition() == "attachment"
    ):
        if all(part is not body_candidate for part in parts):
            parts.insert(0, body_candidate)
    return tuple(parts)


def _nested_message_bytes(
    part: EmailMessage,
    *,
    byte_limit: int,
) -> tuple[bytes, EmailMessage]:
    payload = part.get_payload()
    if (
        not isinstance(payload, list)
        or len(payload) != 1
        or not isinstance(payload[0], EmailMessage)
    ):
        raise _QuarantineRequired("malformed_nested_message")
    nested = payload[0]
    transfer_encoding = (
        part.get("Content-Transfer-Encoding") or "7bit"
    ).casefold()
    if transfer_encoding not in {"", "7bit", "8bit", "binary"}:
        encoded_payload = nested.get_payload()
        if not isinstance(encoded_payload, (str, bytes)):
            raise _QuarantineRequired("malformed_nested_message")
        wrapper = EmailMessage()
        wrapper["Content-Transfer-Encoding"] = transfer_encoding
        wrapper.set_payload(encoded_payload)
        content = _raw_payload_bytes(
            wrapper,
            byte_limit=byte_limit,
            size_reason="attachment_size_limit",
        )
        try:
            decoded = BytesParser(policy=email_policy.default).parsebytes(content)
        except Exception as exc:
            raise _QuarantineRequired("malformed_nested_message") from exc
        if not isinstance(decoded, EmailMessage):
            raise _QuarantineRequired("malformed_nested_message")
        return content, decoded
    try:
        content = nested.as_bytes(policy=_NESTED_SERIALIZATION_POLICY)
    except Exception as exc:
        raise _QuarantineRequired("malformed_nested_message") from exc
    return content, nested


def _prepare_message(
    message: EmailMessage,
    *,
    session: _ParseSession,
    nested_depth: int,
) -> _PreparedMessage:
    subtree_start = session.mime_part_count
    headers = list(message.raw_items())
    if len(headers) > session.policy.max_headers or any(
        len(str(name)) + len(str(value)) > session.policy.max_header_chars
        for name, value in headers
    ):
        raise _QuarantineRequired("header_limit")
    warning_codes: list[str] = []
    _inspect_structure(
        message,
        session=session,
        warning_codes=warning_codes,
    )
    subject = str(message.get("Subject") or "")
    if len(subject) > session.policy.max_subject_chars:
        raise _QuarantineRequired("subject_limit")
    date = _canonical_date(message, warning_codes)
    if len(warning_codes) > session.policy.max_warning_count:
        raise _QuarantineRequired("mime_warning_count_limit")
    body_kind, body = _body_result(
        message,
        parser_policy=session.policy,
        warning_codes=warning_codes,
    )
    from_redacted = _redacted_addresses(
        message,
        "From",
        max_count=session.policy.max_address_count,
    )
    to_redacted = _redacted_addresses(
        message,
        "To",
        max_count=session.policy.max_address_count,
    )
    cc_redacted = _redacted_addresses(
        message,
        "Cc",
        max_count=session.policy.max_address_count,
    )
    session.reserve_output(
        _output_text_chars(
            (
                subject,
                from_redacted,
                to_redacted,
                cc_redacted,
                date,
                body,
                tuple(warning_codes),
            )
        )
    )

    children: list[_PreparedChild] = []
    for part in _attachment_parts(message):
        content_type = part.get_content_type().casefold()
        suffix = _attachment_suffix(part)
        if suffix == ".msg":
            content = _raw_payload_bytes(
                part,
                byte_limit=session.policy.max_attachment_bytes,
                size_reason="attachment_size_limit",
            )
            session.reserve_child(len(content))
            children.append(
                _PreparedChild(
                    content=content,
                    filename_suffix=suffix,
                    declared_media_type=content_type,
                )
            )
            continue
        if content_type in {"message/partial", "message/external-body"}:
            raise _QuarantineRequired("unsupported_message_media_type")
        if content_type == "message/rfc822":
            if nested_depth >= session.policy.max_nested_message_depth:
                raise _QuarantineRequired("nested_message_depth_limit")
            content, nested_message = _nested_message_bytes(
                part,
                byte_limit=session.policy.max_attachment_bytes,
            )
            session.reserve_child(len(content))
            prepared_nested = _prepare_message(
                nested_message,
                session=session,
                nested_depth=nested_depth + 1,
            )
            children.append(
                _PreparedChild(
                    content=content,
                    filename_suffix=".eml",
                    declared_media_type="message/rfc822",
                    nested=prepared_nested,
                )
            )
            continue
        if part.is_multipart():
            raise _QuarantineRequired("unsupported_multipart_attachment")
        content = _raw_payload_bytes(
            part,
            byte_limit=session.policy.max_attachment_bytes,
            size_reason="attachment_size_limit",
        )
        session.reserve_child(len(content))
        children.append(
            _PreparedChild(
                content=content,
                filename_suffix=suffix,
                declared_media_type=content_type,
            )
        )

    return _PreparedMessage(
        subject=subject,
        from_redacted=from_redacted,
        to_redacted=to_redacted,
        cc_redacted=cc_redacted,
        date=date,
        body_kind=body_kind,
        body=body,
        mime_part_count=session.mime_part_count - subtree_start,
        warning_codes=tuple(warning_codes),
        children=tuple(children),
    )


def _publish_prepared_message(
    prepared: _PreparedMessage,
    *,
    event: SourceEvent,
    principal: Principal,
    parent_asset: IngestedAsset,
    storage_root: Path,
    store: SecureAssetStore,
    admission_policy: AssetAdmissionPolicy,
    session: _ParseSession,
    registry: ParserRegistry,
    published_children: list[IngestedAsset],
) -> ParsedEmailMessage:
    attachments: list[EmailAttachmentResult] = []
    nested_messages: list[ParsedEmailMessage] = []
    for child in prepared.children:
        try:
            receipt = admit_child_asset_bytes(
                event=event,
                principal=principal,
                parent_asset=parent_asset,
                content=child.content,
                filename_suffix=child.filename_suffix,
                declared_media_type=child.declared_media_type,
                storage_root=storage_root,
                policy=admission_policy,
            )
        except AssetAdmissionError as exc:
            raise _QuarantineRequired("child_admission_failure") from exc
        published_children.append(receipt)
        if receipt.status != "STAGED":
            raise _QuarantineRequired(receipt.reason_code)
        if child.nested is not None:
            nested_messages.append(
                _publish_prepared_message(
                    child.nested,
                    event=event,
                    principal=principal,
                    parent_asset=receipt,
                    storage_root=storage_root,
                    store=store,
                    admission_policy=admission_policy,
                    session=session,
                    registry=registry,
                    published_children=published_children,
                )
            )
            continue

        try:
            if (
                receipt.content_sha256 is None
                or hashlib.sha256(child.content).hexdigest()
                != receipt.content_sha256
            ):
                raise AssetStorageError(
                    "child_receipt_integrity_mismatch",
                    "The child receipt is not bound to the parsed bytes.",
                )
            parsed = registry.parse_bytes(
                child.content,
                suffix=child.filename_suffix,
            )
            store.read_staged(
                receipt,
                byte_limit=admission_policy.max_file_bytes,
            )
        except (DocumentParseError, AssetStorageError):
            quarantined = store.quarantine_staged(
                receipt,
                reason_code="attachment_parser_failure",
            )
            published_children[-1] = quarantined
            raise _QuarantineRequired("attachment_parser_failure")
        session.reserve_output(_output_text_chars(parsed))
        attachments.append(
            EmailAttachmentResult(
                asset=receipt,
                media_type=child.declared_media_type,
                parsed=parsed,
            )
        )

    return ParsedEmailMessage(
        asset_id=parent_asset.asset_id,
        subject=prepared.subject,
        from_redacted=prepared.from_redacted,
        to_redacted=prepared.to_redacted,
        cc_redacted=prepared.cc_redacted,
        date=prepared.date,
        body_kind=prepared.body_kind,
        body=prepared.body,
        mime_part_count=prepared.mime_part_count,
        attachments=tuple(attachments),
        nested_messages=tuple(nested_messages),
        warning_codes=prepared.warning_codes,
    )


def _quarantine_staged_children(
    store: SecureAssetStore,
    children: list[IngestedAsset],
) -> tuple[IngestedAsset, ...]:
    dispositions = list(children)
    for index in range(len(dispositions) - 1, -1, -1):
        child = dispositions[index]
        if child.status != "STAGED":
            continue
        try:
            dispositions[index] = store.quarantine_staged(
                child,
                reason_code="parent_email_parse_failed",
            )
        except AssetStorageError as exc:
            raise EmailParseError(
                "child_quarantine_failed",
                "A staged email child could not be quarantined safely.",
            ) from exc
    return tuple(dispositions)


def parse_staged_email_body_read_only(
    *,
    receipt: IngestedAsset,
    storage_root: Path,
    policy: EmailParserPolicy = DEFAULT_EMAIL_PARSER_POLICY,
    admission_policy: AssetAdmissionPolicy = DEFAULT_ASSET_ADMISSION_POLICY,
) -> ParseResult:
    """Rebuild the accepted root email body without publishing child assets."""
    try:
        validated_receipt = IngestedAsset.model_validate(
            receipt.model_dump(mode="python")
        )
        parser_policy = EmailParserPolicy.model_validate(
            policy.model_dump(mode="python")
        )
        validated_admission_policy = AssetAdmissionPolicy.model_validate(
            admission_policy.model_dump(mode="python")
        )
    except (AttributeError, ValidationError) as exc:
        raise EmailParseError(
            "email_read_only_contract_invalid",
            "The read-only email materialization contract is invalid.",
        ) from exc
    if (
        validated_receipt.parent_asset_id is not None
        or validated_receipt.status != "STAGED"
        or validated_receipt.declared_media_type != "message/rfc822"
        or validated_receipt.verified_media_type != "message/rfc822"
        or validated_receipt.stored_relpath is None
        or not validated_receipt.stored_relpath.endswith("/payload.eml")
    ):
        raise EmailParseError(
            "staged_eml_required",
            "A verified staged root EML receipt is required.",
        )
    try:
        store = SecureAssetStore(Path(storage_root))
    except AssetStorageError as exc:
        raise EmailParseError(exc.code, str(exc)) from exc

    session = _ParseSession(
        policy=parser_policy,
        admission_policy=validated_admission_policy,
        root_bytes=validated_receipt.byte_count,
    )
    if validated_receipt.byte_count > parser_policy.max_message_bytes:
        raise EmailParseError(
            "message_size_limit",
            "The staged email exceeds the parser message limit.",
        )
    if validated_receipt.byte_count > validated_admission_policy.max_file_bytes:
        raise EmailParseError(
            "file_size_limit",
            "The staged email exceeds the admitted file limit.",
        )
    if validated_receipt.byte_count > validated_admission_policy.max_event_bytes:
        raise EmailParseError(
            "event_byte_limit",
            "The staged email exceeds the admitted event limit.",
        )

    read_limit = min(
        parser_policy.max_message_bytes,
        validated_admission_policy.max_file_bytes,
        validated_admission_policy.max_event_bytes,
    )
    try:
        raw = store.read_staged(
            validated_receipt,
            byte_limit=read_limit,
        )
        message = BytesParser(policy=email_policy.default).parsebytes(raw)
        if not isinstance(message, EmailMessage):
            raise _QuarantineRequired("malformed_mime_structure")
        prepared = _prepare_message(
            message,
            session=session,
            nested_depth=0,
        )
    except AssetStorageError as exc:
        raise EmailParseError(exc.code, str(exc)) from exc
    except _QuarantineRequired as exc:
        raise EmailParseError(
            exc.code,
            "The staged email cannot be materialized read-only.",
        ) from exc
    except Exception as exc:
        raise EmailParseError(
            "email_parser_failure",
            "The staged email parser failed.",
        ) from exc
    return prepared.body


def inspect_email_decoded_surfaces(
    raw: bytes,
    *,
    policy: EmailParserPolicy = DEFAULT_EMAIL_PARSER_POLICY,
    admission_policy: AssetAdmissionPolicy = DEFAULT_ASSET_ADMISSION_POLICY,
) -> tuple[bytes, ...]:
    if not isinstance(raw, bytes):
        raise EmailParseError(
            "email_bytes_invalid",
            "Email inspection requires immutable bytes.",
        )
    try:
        parser_policy = EmailParserPolicy.model_validate(
            policy.model_dump(mode="python")
        )
        validated_admission_policy = AssetAdmissionPolicy.model_validate(
            admission_policy.model_dump(mode="python")
        )
    except (AttributeError, ValidationError) as exc:
        raise EmailParseError(
            "email_policy_invalid",
            "The email inspection policy is invalid.",
        ) from exc
    if (
        len(raw) > parser_policy.max_message_bytes
        or len(raw) > validated_admission_policy.max_file_bytes
        or len(raw) > validated_admission_policy.max_event_bytes
    ):
        raise EmailParseError(
            "message_size_limit",
            "The email exceeds the inspection byte budget.",
        )

    session = _ParseSession(
        policy=parser_policy,
        admission_policy=validated_admission_policy,
        root_bytes=len(raw),
    )
    try:
        message = BytesParser(policy=email_policy.default).parsebytes(raw)
        if not isinstance(message, EmailMessage):
            raise _QuarantineRequired("malformed_mime_structure")
        _prepare_message(
            message,
            session=session,
            nested_depth=0,
        )
        surfaces: list[bytes] = []
        for part in message.walk():
            surfaces.extend(
                str(value).encode("utf-8") for value in part.values()
            )
            if part.is_multipart():
                continue
            surfaces.append(
                _raw_payload_bytes(
                    part,
                    byte_limit=max(
                        parser_policy.max_message_bytes,
                        parser_policy.max_attachment_bytes,
                    ),
                )
            )
        return tuple(surfaces)
    except _QuarantineRequired as exc:
        raise EmailParseError(
            exc.code,
            "The email failed bounded decoded-surface inspection.",
        ) from exc
    except EmailParseError:
        raise
    except Exception as exc:
        raise EmailParseError(
            "email_parser_failure",
            "The email decoded-surface inspection failed.",
        ) from exc


def parse_staged_email(
    *,
    event: SourceEvent,
    principal: Principal,
    receipt: IngestedAsset,
    storage_root: Path,
    policy: EmailParserPolicy = DEFAULT_EMAIL_PARSER_POLICY,
    admission_policy: AssetAdmissionPolicy = DEFAULT_ASSET_ADMISSION_POLICY,
    parser_registry: ParserRegistry | None = None,
) -> EmailParseOutcome:
    event, principal, admission_policy = validate_asset_admission_context(
        event=event,
        principal=principal,
        policy=admission_policy,
    )
    try:
        parser_policy = EmailParserPolicy.model_validate(
            policy.model_dump(mode="python")
        )
    except (AttributeError, ValidationError) as exc:
        raise EmailParseError(
            "email_policy_invalid",
            "The email parser policy is invalid.",
        ) from exc
    receipt = _validate_receipt(event=event, receipt=receipt)
    try:
        store = SecureAssetStore(Path(storage_root))
    except AssetStorageError as exc:
        raise EmailParseError(exc.code, str(exc)) from exc

    session = _ParseSession(
        policy=parser_policy,
        admission_policy=admission_policy,
        root_bytes=receipt.byte_count,
    )
    early_reason: str | None = None
    if receipt.byte_count > parser_policy.max_message_bytes:
        early_reason = "message_size_limit"
    elif receipt.byte_count > admission_policy.max_file_bytes:
        early_reason = "file_size_limit"
    elif receipt.byte_count > admission_policy.max_event_bytes:
        early_reason = "event_byte_limit"
    if early_reason is not None:
        try:
            quarantined = store.quarantine_staged(
                receipt,
                reason_code=early_reason,
            )
        except AssetStorageError as exc:
            raise EmailParseError(exc.code, str(exc)) from exc
        return EmailParseOutcome(
            status="QUARANTINED",
            reason_code=early_reason,
            root_asset=quarantined,
            message=None,
            child_assets=(),
            mime_part_count=0,
            decoded_child_bytes=0,
        )

    read_limit = min(
        parser_policy.max_message_bytes,
        admission_policy.max_file_bytes,
        admission_policy.max_event_bytes,
    )
    try:
        raw = store.read_staged(
            receipt,
            byte_limit=read_limit,
        )
    except AssetStorageError as exc:
        raise EmailParseError(exc.code, str(exc)) from exc

    registry = parser_registry or build_default_registry()
    published_children: list[IngestedAsset] = []
    try:
        message = BytesParser(policy=email_policy.default).parsebytes(raw)
        if not isinstance(message, EmailMessage):
            raise _QuarantineRequired("malformed_mime_structure")
        prepared = _prepare_message(
            message,
            session=session,
            nested_depth=0,
        )
        parsed_message = _publish_prepared_message(
            prepared,
            event=event,
            principal=principal,
            parent_asset=receipt,
            storage_root=Path(storage_root),
            store=store,
            admission_policy=admission_policy,
            session=session,
            registry=registry,
            published_children=published_children,
        )
        return EmailParseOutcome(
            status="PARSED",
            reason_code="parsed",
            root_asset=receipt,
            message=parsed_message,
            child_assets=tuple(published_children),
            mime_part_count=session.mime_part_count,
            decoded_child_bytes=session.decoded_child_bytes,
        )
    except _QuarantineRequired as exc:
        try:
            quarantined = store.quarantine_staged(
                receipt,
                reason_code=exc.code,
            )
        except AssetStorageError as storage_exc:
            raise EmailParseError(storage_exc.code, str(storage_exc)) from storage_exc
        child_dispositions = _quarantine_staged_children(
            store,
            published_children,
        )
        return EmailParseOutcome(
            status="QUARANTINED",
            reason_code=exc.code,
            root_asset=quarantined,
            message=None,
            child_assets=child_dispositions,
            mime_part_count=session.mime_part_count,
            decoded_child_bytes=session.decoded_child_bytes,
        )
    except Exception as exc:
        try:
            store.quarantine_staged(receipt, reason_code="email_parser_failure")
        except AssetStorageError as storage_exc:
            raise EmailParseError(storage_exc.code, str(storage_exc)) from storage_exc
        _quarantine_staged_children(store, published_children)
        raise EmailParseError(
            "email_parser_failure",
            "The staged email parser failed.",
        ) from exc


__all__ = [
    "DEFAULT_EMAIL_PARSER_POLICY",
    "EMAIL_PARSER_NAME",
    "EMAIL_PARSER_VERSION",
    "EmailAttachmentResult",
    "EmailParseError",
    "EmailParseOutcome",
    "EmailParserPolicy",
    "EmailPublicTrace",
    "ParsedEmailMessage",
    "inspect_email_decoded_surfaces",
    "parse_staged_email",
    "parse_staged_email_body_read_only",
]
