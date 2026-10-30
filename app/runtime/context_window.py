"""Keep whole recent user turns inside the existing model input allowance."""

from app.runtime.serving_chat import SERVING_CONTEXT_TOKENS, SERVING_OUTPUT_TOKENS


def recent_questions(rows, current_question, *, reserved_evidence_bytes=3600, schema_bytes=1200):
    remaining = max(
        0,
        SERVING_CONTEXT_TOKENS
        - SERVING_OUTPUT_TOKENS
        - reserved_evidence_bytes
        - schema_bytes
        - len(current_question.encode("utf8")),
    )
    selected = []
    for row in rows:  # newest first, never truncate a question or its conditions
        if row["question"] == current_question or any(
            r["question"] == row["question"] for r in selected
        ):
            continue
        size = len(row["question"].encode("utf8"))
        if size > remaining:
            continue
        selected.append(dict(row))
        remaining -= size
    return list(reversed(selected))


def retrieval_windows(text, *, width=1000, overlap=100):
    """Lexical transport windows, never semantic task/obligation splitting."""
    if len(text) <= width:
        return [text]
    return [text[start : start + width] for start in range(0, len(text), width - overlap)][:4]


def recent_tool_groups(messages):
    """Retain complete call/result groups; older facts are rebuilt from state.

    This is a history byte allowance, not a claim to have the model tokenizer.
    Current user input, facts, scope and current verified knowledge stay outside it.
    """
    import json

    groups = []
    for message in messages:
        if message["role"] == "assistant" or not groups:
            groups.append([])
        groups[-1].append(message)
    budget = SERVING_CONTEXT_TOKENS - SERVING_OUTPUT_TOKENS
    while len(groups) > 1 and len(json.dumps(groups, ensure_ascii=False).encode("utf8")) > budget:
        groups.pop(0)
    return [message for group in groups for message in group]
