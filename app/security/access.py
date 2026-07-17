from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.agent import ToolError
from app.domain.queries import UserContext


AccessCode = Literal[
    "allowed",
    "tenant_mismatch",
    "region_mismatch",
    "group_mismatch",
    "malformed_identity",
    "malformed_metadata",
]


class AccessDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    code: AccessCode

    @model_validator(mode="after")
    def validate_code(self) -> AccessDecision:
        if self.allowed != (self.code == "allowed"):
            raise ValueError("allowed flag must match access code")
        return self


def _value(source: Any, name: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def _identity_scope(source: Any) -> tuple[str, str, frozenset[str]] | None:
    tenant_id = _value(source, "tenant_id")
    region = _value(source, "region")
    groups = _value(source, "groups")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        return None
    if not isinstance(region, str) or not region.strip():
        return None
    if (
        not isinstance(groups, list)
        or not groups
        or any(not isinstance(group, str) or not group.strip() for group in groups)
    ):
        return None
    normalized_groups = frozenset(group.strip() for group in groups)
    if len(normalized_groups) != len(groups):
        return None
    return tenant_id.strip(), region.strip(), normalized_groups


def _resource_scope(source: Any) -> tuple[str, str, frozenset[str]] | None:
    tenant_id = _value(source, "tenant_id")
    region = _value(source, "region")
    groups = _value(source, "acl_groups")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        return None
    if not isinstance(region, str) or not region.strip():
        return None
    if (
        not isinstance(groups, list)
        or not groups
        or any(not isinstance(group, str) or not group.strip() for group in groups)
    ):
        return None
    normalized_groups = frozenset(group.strip() for group in groups)
    if len(normalized_groups) != len(groups):
        return None
    return tenant_id.strip(), region.strip(), normalized_groups


T = TypeVar("T")


class AccessPolicy:
    def evaluate(self, user: UserContext | Mapping[str, Any], resource: Any) -> AccessDecision:
        identity = _identity_scope(user)
        if identity is None:
            return AccessDecision(allowed=False, code="malformed_identity")
        target = _resource_scope(resource)
        if target is None:
            return AccessDecision(allowed=False, code="malformed_metadata")

        tenant_id, region, groups = identity
        target_tenant, target_region, target_groups = target
        if tenant_id != target_tenant:
            return AccessDecision(allowed=False, code="tenant_mismatch")
        if region != target_region:
            return AccessDecision(allowed=False, code="region_mismatch")
        if not groups.intersection(target_groups):
            return AccessDecision(allowed=False, code="group_mismatch")
        return AccessDecision(allowed=True, code="allowed")

    def visible_chunks(
        self,
        user: UserContext | Mapping[str, Any],
        chunks: Sequence[T],
    ) -> tuple[list[T], int]:
        visible: list[T] = []
        denied_count = 0
        for chunk in chunks:
            if self.evaluate(user, chunk).allowed:
                visible.append(chunk)
            else:
                denied_count += 1
        return visible, denied_count

    def visible_indices(
        self,
        user: UserContext | Mapping[str, Any],
        chunks: Sequence[Any],
    ) -> tuple[list[int], int]:
        visible: list[int] = []
        denied_count = 0
        for index, chunk in enumerate(chunks):
            if self.evaluate(user, chunk).allowed:
                visible.append(index)
            else:
                denied_count += 1
        return visible, denied_count


def safe_access_error(decision: AccessDecision) -> ToolError:
    if decision.allowed:
        raise ValueError("allowed decision does not require an access error")
    return ToolError(
        code="permission",
        retryable=False,
        safe_message="The requested resource is unavailable for this identity.",
    )


SENSITIVE_TRACE_KEYS = {
    "acl_groups",
    "chunk_id",
    "chunks",
    "content",
    "context_text",
    "doc_id",
    "documents",
    "hits",
    "matched_text",
    "parent_chunk_id",
    "preview",
    "source_path",
    "text",
    "title",
}
SECRET_PATTERN = re.compile(
    r"(?i)\b(password|token|api[_-]?key)\s*([:=])\s*([^\s,;]+)"
)


def redact_trace_text(value: str, denied_values: Iterable[str] = ()) -> str:
    redacted = SECRET_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        value,
    )
    for denied in denied_values:
        if denied:
            redacted = redacted.replace(str(denied), "[REDACTED]")
    return redacted


def redact_trace_payload(
    value: Any,
    *,
    denied_values: Iterable[str] = (),
) -> Any:
    denied = tuple(str(item) for item in denied_values if str(item))
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {
            str(key): redact_trace_payload(item, denied_values=denied)
            for key, item in value.items()
            if str(key) not in SENSITIVE_TRACE_KEYS
            and not str(key).startswith("internal_")
            and not str(key).startswith("denied_")
        }
    if isinstance(value, list):
        return [redact_trace_payload(item, denied_values=denied) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_trace_payload(item, denied_values=denied) for item in value)
    if isinstance(value, str):
        return redact_trace_text(value, denied)
    return value


__all__ = [
    "AccessCode",
    "AccessDecision",
    "AccessPolicy",
    "redact_trace_payload",
    "redact_trace_text",
    "safe_access_error",
]
