from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from app.domain.retrieved_security import (
    DETECTOR_VERSION,
    MAX_NORMALIZED_CHARS,
    MAX_SCAN_CHARS,
    RULE_SPECS,
    GuardDecision,
    RiskCategory,
)


SCAN_PREFIX_CHARS = 14_000
SCAN_SUFFIX_CHARS = 6_000
MIN_BASE64_ENCODED_CHARS = 16
MAX_BASE64_ENCODED_CHARS = 4096
MAX_BASE64_DECODED_BYTES = 3072
MAX_BASE64_CANDIDATES = 8
MIN_BASE64_PRINTABLE_RATIO = 0.70
PAIR_MAX_GAP_CHARS = 240
ROLE_ACTION_CHARS = 240
EGRESS_CONTEXT_CHARS = 180
DESCRIPTIVE_CONTEXT_CHARS = 240
MAX_PATTERN_MATCHES = 256

_REMOVED_UNICODE_CATEGORIES = frozenset({"Cf"})
_BIDI_CONTROL_CLASSES = frozenset(
    {"LRE", "RLE", "LRO", "RLO", "PDF", "LRI", "RLI", "FSI", "PDI"}
)
_CONFUSABLE_MAP = {
    "а": "a",
    "е": "e",
    "і": "i",
    "о": "o",
    "р": "p",
    "с": "c",
    "х": "x",
    "у": "y",
}
_CONFUSABLE_TRANSLATION = str.maketrans(_CONFUSABLE_MAP)
_INSTRUCTION_ACTION = re.compile(
    r"\b(?:ignore|disregard|override|replace|forget|bypass)\b"
    r"|\bdo\s+not\s+(?:follow|obey)\b"
    r"|忽略|无视|覆盖|替换|绕过|不要(?:遵守|遵循)"
)
_INSTRUCTION_TARGET = re.compile(
    r"\b(?:(?:all|the)\s+)?(?:previous|prior|system|developer|trusted)\s+"
    r"(?:instructions?|rules?|messages?)\b"
    r"|之前(?:的|所有)?(?:系统)?指令|系统指令|以上(?:要求|规则)|原有(?:指令|规则)"
)
_ROLE_BOUNDARY = re.compile(
    r"(?im)(?:^|\n)\s*(?:\[\s*)?"
    r"(?:system|assistant|developer|tool|系统|助手|开发者|工具)"
    r"(?:\s*\])?\s*[:>]"
)
_ROLE_ACTION = re.compile(
    r"\b(?:ignore|reveal|return|send|upload|call|execute|obey|follow|output|print)\b"
    r"|忽略|显示|返回|发送|上传|调用|执行|遵循|服从"
)
_SECRET_ACTION = re.compile(
    r"\b(?:reveal|print|return|expose|show|leak|disclose|output|send)\b"
    r"|输出|返回|显示|泄露|暴露|发送"
)
_SECRET_TARGET = re.compile(
    r"\b(?:system\s+prompt|developer\s+message|document\s+canary|"
    r"system\s+canary|[a-z0-9_]*canary[a-z0-9_]*|secret|password|"
    r"api[_ -]?key|token)\b"
    r"|系统提示词|开发者消息|诱饵|秘密|密钥|密码|令牌"
)
_EGRESS_ACTION = re.compile(
    r"\b(?:send|upload|post|transmit|exfiltrate|forward|call|request)\b"
    r"|发送|上传|外传|转发|调用|请求"
)
_EGRESS_DESTINATION = re.compile(
    r"https?://|\b(?:webhook|external\s+server|remote\s+endpoint)\b"
    r"|外部服务器|外部地址|网址|链接"
)
_EGRESS_SENSITIVE_CONTEXT = re.compile(
    r"\b(?:assistant|model|system\s+prompt|[a-z0-9_]*canary[a-z0-9_]*|"
    r"secret|password|api[_ -]?key|token|conversation|retrieved\s+content|"
    r"document\s+content)\b"
    r"|助手|模型|系统提示词|诱饵|秘密|密钥|密码|令牌|对话|检索内容|文档内容|请你"
)
_DESCRIPTIVE_MARKER = re.compile(
    r"security\s+training|training\s+example|attack\s+example|"
    r"injection\s+phrase|incident\s+report|quoted|blocked\s+payload|"
    r"安全培训|培训示例|攻击示例|攻击文本|事件报告|引用|拦截"
)
_BASE64_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9+/])"
    r"([A-Za-z0-9+/]{16,4096}={0,2})"
    r"(?![A-Za-z0-9+/=])"
)
_HIDDEN_HTML_ATTRIBUTE = re.compile(
    r"\bhidden(?:\s*=|\s|>)|\baria-hidden\s*=\s*[\"']?true|"
    r"\bstyle\s*=\s*[\"'][^\"']*(?:display\s*:\s*none|visibility\s*:\s*hidden)"
)

_SEVERITY_ORDER = {"observe": 1, "quarantine": 2}


@dataclass(frozen=True)
class _DetectionView:
    source_segments: tuple[str, ...]
    base64_candidate_segments: tuple[str, ...]
    normalized_segments: tuple[str, ...]
    comparable_segments: tuple[str, ...]
    original_length: int
    normalized_length: int
    scanned_length: int
    nfkc_changed: bool
    format_control_present: bool
    bidi_present: bool
    confusable_changed: bool


@dataclass(frozen=True)
class _RuleMatch:
    category: RiskCategory
    rule_id: str
    severity: Literal["observe", "quarantine"]
    segment_index: int
    start: int
    end: int


def _bounded_segments(content: str) -> tuple[str, ...]:
    if len(content) <= MAX_SCAN_CHARS:
        return (content,)
    return (
        content[:SCAN_PREFIX_CHARS],
        content[-SCAN_SUFFIX_CHARS:],
    )


def _bounded_detection_segments(segments: tuple[str, ...]) -> tuple[str, ...]:
    if sum(len(segment) for segment in segments) <= MAX_NORMALIZED_CHARS:
        return segments
    if len(segments) == 1:
        return (
            segments[0][:SCAN_PREFIX_CHARS],
            segments[0][-SCAN_SUFFIX_CHARS:],
        )
    return (
        segments[0][:SCAN_PREFIX_CHARS],
        segments[-1][-SCAN_SUFFIX_CHARS:],
    )


def _is_removed_format_control(character: str) -> bool:
    return unicodedata.category(character) in _REMOVED_UNICODE_CATEGORIES


def _without_format_controls(text: str) -> str:
    return "".join(
        character for character in text if not _is_removed_format_control(character)
    )


def normalized_content_length(content: str) -> int:
    """Return the detector's pre-bound NFKC/casefold character count."""
    if not isinstance(content, str):
        raise TypeError("retrieved content must be text")
    return len(unicodedata.normalize("NFKC", content).casefold())


def _build_detection_view(content: str) -> _DetectionView:
    source_segments = _bounded_segments(content)
    nfkc_segments = tuple(
        unicodedata.normalize("NFKC", source) for source in source_segments
    )
    base64_candidate_segments = tuple(
        _without_format_controls(segment)
        for segment in _bounded_detection_segments(nfkc_segments)
    )
    normalized_segments = _bounded_detection_segments(
        tuple(segment.casefold() for segment in nfkc_segments)
    )
    comparable_segments: list[str] = []
    nfkc_changed = any(
        nfkc != source for source, nfkc in zip(source_segments, nfkc_segments)
    )
    format_control_present = any(
        _is_removed_format_control(character)
        for segment in source_segments
        for character in segment
    )
    bidi_present = any(
        unicodedata.bidirectional(character) in _BIDI_CONTROL_CLASSES
        for segment in source_segments
        for character in segment
    )
    confusable_changed = False

    for normalized in normalized_segments:
        without_controls = _without_format_controls(normalized)
        comparable = without_controls.translate(_CONFUSABLE_TRANSLATION)
        confusable_changed = confusable_changed or comparable != without_controls
        comparable_segments.append(comparable)

    normalized_length = sum(len(segment) for segment in normalized_segments)
    return _DetectionView(
        source_segments=source_segments,
        base64_candidate_segments=base64_candidate_segments,
        normalized_segments=normalized_segments,
        comparable_segments=tuple(comparable_segments),
        original_length=len(content),
        normalized_length=normalized_length,
        scanned_length=sum(len(segment) for segment in source_segments),
        nfkc_changed=nfkc_changed,
        format_control_present=format_control_present,
        bidi_present=bidi_present,
        confusable_changed=confusable_changed,
    )


class _DetectionBudgetExceeded(RuntimeError):
    pass


def _bounded_pattern_matches(
    pattern: re.Pattern[str],
    text: str,
) -> list[re.Match[str]]:
    matches: list[re.Match[str]] = []
    for match in pattern.finditer(text):
        if len(matches) >= MAX_PATTERN_MATCHES:
            raise _DetectionBudgetExceeded("detector pattern match budget exceeded")
        matches.append(match)
    return matches


def _paired_spans(
    text: str,
    first: re.Pattern[str],
    second: re.Pattern[str],
    *,
    max_gap: int = PAIR_MAX_GAP_CHARS,
) -> list[tuple[int, int]]:
    first_matches = _bounded_pattern_matches(first, text)
    second_matches = _bounded_pattern_matches(second, text)
    result: list[tuple[int, int]] = []
    first_index = 0
    second_index = 0
    while first_index < len(first_matches) and second_index < len(second_matches):
        left = first_matches[first_index]
        right = second_matches[second_index]
        if left.end() < right.start():
            gap = right.start() - left.end()
        elif right.end() < left.start():
            gap = left.start() - right.end()
        else:
            gap = 0

        if gap <= max_gap:
            result.append(
                (min(left.start(), right.start()), max(left.end(), right.end()))
            )

        if left.end() <= right.end():
            first_index += 1
        else:
            second_index += 1
    return result


def _unescaped_positions(text: str, token: str) -> list[int]:
    positions: list[int] = []
    for index, character in enumerate(text):
        if character != token:
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and text[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            positions.append(index)
    return positions


def _inside_pair(text: str, start: int, end: int, opening: str, closing: str) -> bool:
    if opening == closing:
        positions = _unescaped_positions(text, opening)
        return any(
            opening_index <= start and end <= closing_index
            for opening_index, closing_index in zip(
                positions[0::2],
                positions[1::2],
            )
        )

    opening_positions = _unescaped_positions(text, opening)
    closing_positions = _unescaped_positions(text, closing)
    opening_index = 0
    closing_index = 0
    while (
        opening_index < len(opening_positions)
        and closing_index < len(closing_positions)
    ):
        if closing_positions[closing_index] < opening_positions[opening_index]:
            closing_index += 1
            continue
        if (
            opening_positions[opening_index] <= start
            and end <= closing_positions[closing_index]
        ):
            return True
        opening_index += 1
        closing_index += 1
    return False


def _is_descriptive_quote(text: str, start: int, end: int) -> bool:
    context_start = max(0, start - DESCRIPTIVE_CONTEXT_CHARS)
    if _DESCRIPTIVE_MARKER.search(text[context_start:start]) is None:
        return False
    quote_pairs = (("\"", "\""), ("'", "'"), ("“", "”"), ("‘", "’"))
    if any(_inside_pair(text, start, end, opening, closing) for opening, closing in quote_pairs):
        return True
    return text.count("```", 0, start) % 2 == 1 and text.find("```", end) >= 0


def _inside_markup(text: str, start: int, end: int) -> bool:
    comment_start = text.rfind("<!--", 0, start + 1)
    if comment_start >= 0 and text.find("-->", end) >= 0:
        return True
    if text.count("```", 0, start) % 2 == 1 and text.find("```", end) >= 0:
        return True
    link_start = text.rfind("[", 0, start + 1)
    link_end = text.find("]", end)
    if (
        link_start >= 0
        and link_end >= end
        and text[link_end + 1 :].lstrip().startswith("(")
    ):
        return True
    tag_start = text.rfind("<", 0, start + 1)
    tag_end = text.find(">", tag_start + 1) if tag_start >= 0 else -1
    if tag_start >= 0 and 0 <= tag_end <= start:
        opening_tag = text[tag_start : tag_end + 1]
        tag_name = re.match(r"<\s*([a-z0-9]+)", opening_tag)
        if (
            tag_name is not None
            and _HIDDEN_HTML_ATTRIBUTE.search(opening_tag) is not None
            and text.find(f"</{tag_name.group(1)}", end) >= 0
        ):
            return True
    return False


def _match(
    category: RiskCategory,
    rule_id: str,
    segment_index: int,
    start: int,
    end: int,
    *,
    severity: Literal["observe", "quarantine"] = "quarantine",
) -> _RuleMatch:
    expected_category, expected_severity = RULE_SPECS[rule_id]
    if category != expected_category or severity != expected_severity:
        raise ValueError("detector rule metadata drifted from the rule allowlist")
    return _RuleMatch(
        category=category,
        rule_id=rule_id,
        severity=severity,
        segment_index=segment_index,
        start=start,
        end=end,
    )


def _scan_non_encoded(view: _DetectionView) -> list[_RuleMatch]:
    matches: list[_RuleMatch] = []
    for segment_index, text in enumerate(view.comparable_segments):
        active: list[_RuleMatch] = []

        for start, end in _paired_spans(
            text,
            _INSTRUCTION_ACTION,
            _INSTRUCTION_TARGET,
        ):
            if not _is_descriptive_quote(text, start, end):
                active.append(
                    _match(
                        "instruction_override",
                        "RCG-INSTRUCTION-OVERRIDE-001",
                        segment_index,
                        start,
                        end,
                    )
                )

        for role in _bounded_pattern_matches(_ROLE_BOUNDARY, text):
            action = _ROLE_ACTION.search(
                text,
                role.end(),
                role.end() + ROLE_ACTION_CHARS,
            )
            if action is None:
                continue
            start, end = role.start(), action.end()
            if not _is_descriptive_quote(text, start, end):
                active.append(
                    _match(
                        "role_impersonation",
                        "RCG-ROLE-BOUNDARY-001",
                        segment_index,
                        start,
                        end,
                    )
                )

        for start, end in _paired_spans(text, _SECRET_ACTION, _SECRET_TARGET):
            if not _is_descriptive_quote(text, start, end):
                active.append(
                    _match(
                        "secret_extraction",
                        "RCG-SECRET-EXTRACTION-001",
                        segment_index,
                        start,
                        end,
                    )
                )

        for start, end in _paired_spans(text, _EGRESS_ACTION, _EGRESS_DESTINATION):
            context = text[
                max(0, start - EGRESS_CONTEXT_CHARS) :
                min(len(text), end + EGRESS_CONTEXT_CHARS)
            ]
            if (
                _EGRESS_SENSITIVE_CONTEXT.search(context) is not None
                and not _is_descriptive_quote(text, start, end)
            ):
                active.append(
                    _match(
                        "tool_egress",
                        "RCG-EGRESS-SENSITIVE-DATA-001",
                        segment_index,
                        start,
                        end,
                    )
                )

        matches.extend(active)
        for risky in active:
            if _inside_markup(text, risky.start, risky.end):
                matches.append(
                    _match(
                        "markup_wrapper",
                        "RCG-MARKUP-WRAPPED-DIRECTIVE-001",
                        segment_index,
                        risky.start,
                        risky.end,
                    )
                )

    if view.bidi_present:
        matches.append(
            _match(
                "invisible_unicode",
                "RCG-INVISIBLE-BIDI-001",
                0,
                0,
                0,
            )
        )
    if view.format_control_present and not view.bidi_present:
        matches.append(
            _match(
                "invisible_unicode",
                "RCG-INVISIBLE-CONTROL-OBSERVE-001",
                0,
                0,
                0,
                severity="observe",
            )
        )

    has_content_quarantine = any(
        match.severity == "quarantine" and match.category != "invisible_unicode"
        for match in matches
    )
    if has_content_quarantine and view.nfkc_changed:
        matches.append(
            _match(
                "invisible_unicode",
                "RCG-INVISIBLE-NFKC-001",
                0,
                0,
                0,
            )
        )
    if has_content_quarantine and (
        view.format_control_present or view.confusable_changed
    ):
        matches.append(
            _match(
                "invisible_unicode",
                "RCG-INVISIBLE-OBFUSCATION-001",
                0,
                0,
                0,
            )
        )
    return matches


def _decision_from_matches(
    view: _DetectionView,
    matches: list[_RuleMatch],
    *,
    decoded_view_count: int = 0,
) -> GuardDecision:
    if not matches:
        disposition = "ADMIT"
        severity = "none"
    else:
        severity = max(matches, key=lambda match: _SEVERITY_ORDER[match.severity]).severity
        disposition = "QUARANTINE" if severity == "quarantine" else "ADMIT"
    return GuardDecision(
        disposition=disposition,
        max_severity=severity,
        risk_categories=tuple(sorted({match.category for match in matches})),
        rule_ids=tuple(sorted({match.rule_id for match in matches})),
        detector_version=DETECTOR_VERSION,
        original_length=view.original_length,
        normalized_length=view.normalized_length,
        scanned_length=view.scanned_length,
        decoded_view_count=decoded_view_count,
        guard_error=False,
    )


def _printable_ratio(decoded: bytes) -> float:
    if not decoded:
        return 0.0
    try:
        text = decoded.decode("utf-8")
    except UnicodeDecodeError:
        printable = sum(
            byte in {9, 10, 13} or 32 <= byte <= 126
            for byte in decoded
        )
        return printable / len(decoded)
    printable_bytes = sum(
        len(character.encode("utf-8"))
        for character in text
        if character.isprintable() or character.isspace()
    )
    return printable_bytes / len(decoded)


def _scan_base64_views(view: _DetectionView) -> tuple[list[_RuleMatch], int]:
    matches: list[_RuleMatch] = []
    inspected_candidates = 0
    decoded_view_count = 0
    for source in view.base64_candidate_segments:
        for candidate in _BASE64_CANDIDATE.finditer(source):
            if inspected_candidates >= MAX_BASE64_CANDIDATES:
                return matches, decoded_view_count
            inspected_candidates += 1
            encoded = candidate.group(1)
            if (
                len(encoded) < MIN_BASE64_ENCODED_CHARS
                or len(encoded) > MAX_BASE64_ENCODED_CHARS
                or len(encoded) % 4 != 0
            ):
                continue
            try:
                decoded = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                continue
            if len(decoded) > MAX_BASE64_DECODED_BYTES:
                continue
            decoded_view_count += 1
            if _printable_ratio(decoded) < MIN_BASE64_PRINTABLE_RATIO:
                continue
            decoded_text = decoded.decode("utf-8", errors="replace")
            decoded_view = _build_detection_view(decoded_text)
            decoded_matches = _scan_non_encoded(decoded_view)
            if not any(match.severity == "quarantine" for match in decoded_matches):
                continue
            matches.extend(decoded_matches)
            matches.append(
                _match(
                    "encoded_payload",
                    "RCG-BASE64-DECODED-001",
                    0,
                    0,
                    0,
                )
            )
    return matches, decoded_view_count


def _scan_bounded_content(content: str) -> GuardDecision:
    view = _build_detection_view(content)
    matches = _scan_non_encoded(view)
    decoded_matches, decoded_view_count = _scan_base64_views(view)
    matches.extend(decoded_matches)
    if (
        view.nfkc_changed
        and any(match.severity == "quarantine" for match in decoded_matches)
        and not any(match.rule_id == "RCG-INVISIBLE-NFKC-001" for match in matches)
    ):
        matches.append(
            _match(
                "invisible_unicode",
                "RCG-INVISIBLE-NFKC-001",
                0,
                0,
                0,
            )
        )
    if (
        view.format_control_present
        and any(match.severity == "quarantine" for match in decoded_matches)
        and not any(
            match.rule_id == "RCG-INVISIBLE-OBFUSCATION-001"
            for match in matches
        )
    ):
        matches.append(
            _match(
                "invisible_unicode",
                "RCG-INVISIBLE-OBFUSCATION-001",
                0,
                0,
                0,
            )
        )
    return _decision_from_matches(
        view,
        matches,
        decoded_view_count=decoded_view_count,
    )


def _guard_error_decision(content: object) -> GuardDecision:
    try:
        original_length = str.__len__(content) if isinstance(content, str) else 0
    except Exception:
        original_length = 0
    return GuardDecision(
        disposition="QUARANTINE",
        max_severity="error",
        risk_categories=("guard_error",),
        rule_ids=("RCG-GUARD-ERROR",),
        detector_version=DETECTOR_VERSION,
        original_length=original_length,
        normalized_length=0,
        scanned_length=0,
        decoded_view_count=0,
        guard_error=True,
    )


_RULE_PROVENANCE = {
    "detector_version": DETECTOR_VERSION,
    "unicode_database_version": unicodedata.unidata_version,
    "scan_prefix_chars": SCAN_PREFIX_CHARS,
    "scan_suffix_chars": SCAN_SUFFIX_CHARS,
    "normalization": {
        "casefold": True,
        "expanded_view_bound": "prefix-14000-suffix-6000",
        "form": "NFKC",
    },
    "removed_unicode_categories": sorted(_REMOVED_UNICODE_CATEGORIES),
    "bidi_control_classes": sorted(_BIDI_CONTROL_CLASSES),
    "proximity_windows": {
        "descriptive_context_chars": DESCRIPTIVE_CONTEXT_CHARS,
        "egress_context_chars": EGRESS_CONTEXT_CHARS,
        "pair_max_gap_chars": PAIR_MAX_GAP_CHARS,
        "role_action_chars": ROLE_ACTION_CHARS,
    },
    "max_pattern_matches": MAX_PATTERN_MATCHES,
    "max_base64_candidates": MAX_BASE64_CANDIDATES,
    "min_base64_encoded_chars": MIN_BASE64_ENCODED_CHARS,
    "max_base64_encoded_chars": MAX_BASE64_ENCODED_CHARS,
    "max_base64_decoded_bytes": MAX_BASE64_DECODED_BYTES,
    "min_base64_printable_ratio": MIN_BASE64_PRINTABLE_RATIO,
    "printable_ratio_unit": "decoded-bytes",
    "base64_candidate_view": "NFKC-case-preserving",
    "confusable_map": sorted(_CONFUSABLE_MAP.items()),
    "rule_specs": {
        rule_id: {"category": category, "severity": severity}
        for rule_id, (category, severity) in sorted(RULE_SPECS.items())
    },
    "patterns": [
        {"flags": pattern.flags, "name": name, "pattern": pattern.pattern}
        for name, pattern in (
            ("instruction_action", _INSTRUCTION_ACTION),
            ("instruction_target", _INSTRUCTION_TARGET),
            ("role_boundary", _ROLE_BOUNDARY),
            ("role_action", _ROLE_ACTION),
            ("secret_action", _SECRET_ACTION),
            ("secret_target", _SECRET_TARGET),
            ("egress_action", _EGRESS_ACTION),
            ("egress_destination", _EGRESS_DESTINATION),
            ("egress_sensitive_context", _EGRESS_SENSITIVE_CONTEXT),
            ("descriptive_marker", _DESCRIPTIVE_MARKER),
            ("base64_candidate", _BASE64_CANDIDATE),
            ("hidden_html_attribute", _HIDDEN_HTML_ATTRIBUTE),
        )
    ],
    "quote_policy": "balanced-unescaped-pairs-with-descriptive-marker",
    "markup_structures": [
        "fenced-code",
        "hidden-html",
        "html-comment",
        "markdown-link",
    ],
}
RULE_SET_SHA256 = hashlib.sha256(
    json.dumps(
        _RULE_PROVENANCE,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()


class RetrievedContentGuard:
    def scan(self, content: object) -> GuardDecision:
        try:
            if not isinstance(content, str):
                raise TypeError("retrieved content must be text")
            return _scan_bounded_content(content)
        except Exception:
            return _guard_error_decision(content)


__all__ = [
    "MAX_BASE64_CANDIDATES",
    "MAX_BASE64_DECODED_BYTES",
    "MAX_BASE64_ENCODED_CHARS",
    "MIN_BASE64_ENCODED_CHARS",
    "MIN_BASE64_PRINTABLE_RATIO",
    "RULE_SET_SHA256",
    "SCAN_PREFIX_CHARS",
    "SCAN_SUFFIX_CHARS",
    "RetrievedContentGuard",
    "normalized_content_length",
]
