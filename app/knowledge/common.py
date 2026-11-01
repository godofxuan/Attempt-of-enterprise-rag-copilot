from __future__ import annotations
import uuid, re


def named_source_scope(question, snapshot):
    """Resolve an explicitly quoted document title to existing published policy IDs.

    This is resource binding, not intent classification or a topic dictionary.
    Ambiguous/unmatched names are not guessed. ACL/version filters still apply.
    """
    quoted = re.findall(r"《([^》]{1,200})》", question)
    if not quoted:
        return []
    titles = {}
    for chunk in snapshot.all_chunks_by_id.values():
        if chunk.section_path:
            titles.setdefault(chunk.section_path[0].casefold(), set()).add(chunk.policy_id)
    for doc in snapshot.documents_by_id.values():
        title = getattr(doc, "title", None)
        if title:
            titles.setdefault(title.casefold(), set()).add(doc.policy_id)
    resolved = []
    for name in quoted:
        candidates = titles.get(name.strip().casefold(), set())
        if len(candidates) != 1:
            return []
        resolved.extend(candidates)
    if len(set(resolved)) > 20:
        raise ValueError("NAMED_SOURCE_SCOPE_TOO_LARGE")
    return sorted(set(resolved))


def identifier(prefix):
    return prefix + "_" + uuid.uuid4().hex[:16]
