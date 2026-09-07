from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.domain.retrieved_security import AdmittedEvidenceChunk, AdmittedOpenResult

SOURCE_UNIT_END = re.compile(
    r"[。！？；]|[!?;][\"'`\u201d\u2019]*|\.(?!\d)[\"'`\u201d\u2019]*(?=\s|$)"
)


def complete_evidence_prefix(text: str, limit: int) -> str:
    """Do not promote a budget-truncated trailing clause to a complete fact."""
    if len(text) <= limit:
        return text
    end = 0
    for boundary in SOURCE_UNIT_END.finditer(text):
        if boundary.end() > limit:
            break
        end = boundary.end()
    return text[:end]


@dataclass(frozen=True)
class DeliveredEvidence:
    """A model-visible prefix view of already admitted, immutable evidence."""

    anchor: AdmittedEvidenceChunk
    matched_text: str
    context_text: str = ""
    opened: AdmittedOpenResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.anchor, AdmittedEvidenceChunk):
            raise TypeError("delivered evidence requires an admitted anchor")
        if not isinstance(self.matched_text, str) or not self.matched_text.strip():
            raise ValueError("delivered evidence requires nonempty text")
        if not isinstance(self.context_text, str):
            raise TypeError("delivered context must be text")
        if self.opened is None:
            if not self.anchor.hit.matched_text.startswith(self.matched_text):
                raise ValueError("delivered matched text must belong to its source")
            if not self.anchor.hit.context_text.startswith(self.context_text):
                raise ValueError("delivered context must belong to its source")
        else:
            if not isinstance(self.opened, AdmittedOpenResult):
                raise TypeError("opened evidence must be admitted")
            original = self.opened.result
            if (original.doc_id, original.source_path) != (
                self.anchor.hit.doc_id,
                self.anchor.hit.source_path,
            ):
                raise ValueError("opened evidence must match its admitted document")
            if self.context_text or not original.content.startswith(self.matched_text):
                raise ValueError("delivered open text must belong to its source")

    @property
    def citation_id(self) -> str:
        if self.opened is None:
            return self.anchor.hit.chunk_id
        result = self.opened.result
        binding = "\n".join(
            (
                self.anchor.hit.index_run_id,
                self.anchor.hit.version_id,
                result.target_type,
                result.target_id,
                result.content,
            )
        )
        digest = hashlib.sha256(binding.encode("utf-8")).hexdigest()[:24]
        return f"open::{digest}"

    @property
    def text(self) -> str:
        if not self.context_text or self.context_text == self.matched_text:
            return self.matched_text
        return f"{self.matched_text}\n{self.context_text}"
