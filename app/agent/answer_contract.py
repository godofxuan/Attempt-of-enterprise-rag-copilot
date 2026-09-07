"""Bounded answer-shape checks; never a general semantic correctness judge."""

import re

_VALUE = (
    r"(?:\d+(?:\.\d+)?|[一二三四五六七八九十百]+|one|two|three|four|five|six|seven|eight|nine|ten)"
)
_DURATION_QUESTION = re.compile(r"how many days|几天|多少天", re.I)
_DURATION_VALUE = re.compile(_VALUE + r"\s*(?:days?\b|天|日)", re.I)


def answer_sufficiency(question: str, claim_texts: list[str]) -> str:
    if _DURATION_QUESTION.search(question):
        if not any(_DURATION_VALUE.search(text) for text in claim_texts):
            return "missing_requested_value"
        return "bounded_value_present"
    return "semantic_completeness_unverified"
