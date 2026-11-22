"""Observe labelled evidence with the frozen security evaluator.

Only observation decoding changes. Raw requests, model responses, Guard admission
and task scoring retain their original paths. The historical replay modules keep
their exact bytes so their dependency checks continue to detect tampering.
"""

import json
import re
from unittest.mock import patch

from app.evaluation import indirect_injection_live_runner as live
from app.evaluation import indirect_injection_runner as deterministic


def decode_records(records):
    result = []
    for record in records:
        row = dict(record)
        for unit_id in row.get("source_units", []):
            if not isinstance(unit_id, str) or not re.fullmatch(r"S[1-9]\d*U[1-9]\d*", unit_id):
                continue
            opening, closing = "[" + unit_id + "]", "[/" + unit_id + "]"
            for field in ("matched_text", "context_text"):
                text = row.get(field)
                if isinstance(text, str) and text.count(opening) == text.count(closing) == 1:
                    row[field] = text.replace(opening, "").replace(closing, "")
        result.append(row)
    return result


_original_records = deterministic._evidence_records_from_prompt
_original_contains = live._contains_text


def _records(prompt, nonce):
    return decode_records(_original_records(prompt, nonce))


def _contains(value, targets):
    if _original_contains(value, targets):
        return True
    # Inspect the actual JSON evidence envelope inside each recorded message.
    messages = value if isinstance(value, list) else []
    for message in messages:
        if not isinstance(message, dict):
            continue
        for line in str(message.get("content", "")).splitlines():
            if not line.startswith("[{"):
                continue
            try:
                records = json.loads(line)
            except ValueError:
                continue
            if isinstance(records, list) and all(isinstance(r, dict) for r in records):
                if _original_contains(decode_records(records), targets):
                    return True
    return False


def evaluate_paired(*args, **kwargs):
    with patch.object(deterministic, "_evidence_records_from_prompt", _records):
        return deterministic.evaluate_paired(*args, **kwargs)


def evaluate_live_paired(*args, **kwargs):
    with patch.object(live, "_contains_text", _contains):
        return live.evaluate_live_paired(*args, **kwargs)
