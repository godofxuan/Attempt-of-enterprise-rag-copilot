"""Bind concise model expression to the same retained source claims.

Exact quotes remain verified independently. These finite consistency checks are
not semantic entailment; live content evaluation is recorded separately.
"""

import re
from app.agent.citation_verifier import _content_tokens, _date_mismatch, _negation_mismatch
from app.domain.evidence import AnswerBlock
from app.security.retrieved_content import RetrievedContentGuard


def scalar_literals(text):
    # Markdown ordinals and ASCII identifiers are syntax, not quantities.
    text = re.sub(r"(?m)^\s{0,3}\d+[.)]\s+(?=\S)", "", text)
    return set(re.findall(r"(?<![A-Za-z0-9_])\d+(?:\.\d+)?(?![A-Za-z0-9_])", text))


def retained_blocks(blocks, claims, question, provenance_by_claim=None, *, diagnostics_only=False, audit=None):
    by_id = {claim.claim_id: claim for claim in claims}
    retained, rejected = [], []
    for block in blocks:
        reason = None
        if len(set(block.claim_ids)) != len(block.claim_ids) or not set(block.claim_ids) <= set(
            by_id
        ):
            reason = "unbound_or_discarded_evidence"
        else:
            evidence = "\n".join(by_id[cid].text for cid in block.claim_ids)
            assumptions = "\n".join(block.assumptions)
            tokens = _content_tokens(block.text)
            shared = tokens & _content_tokens(evidence + "\n" + question)
            identifier_context = "\n".join(
                (provenance_by_claim or {}).get(cid, "") for cid in block.claim_ids
            )
            identity_pattern = r"\b[A-Za-z][A-Za-z0-9_-]*\d[A-Za-z0-9_-]*\b"
            identifiers = set(re.findall(identity_pattern, block.text))
            known_identifiers = set(
                re.findall(
                    identity_pattern, evidence + "\n" + identifier_context + "\n" + assumptions
                )
            )
            factual_basis = evidence + ("\n" + assumptions if block.assumptions else "")
            scalar_text = re.sub(identity_pattern, "", block.text)
            if not identifiers <= known_identifiers:
                reason = "unbound_source_identifier"
            elif not set(re.findall(r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9_]+(?![A-Za-z0-9_])", evidence)) <= set(
                re.findall(r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9_]+(?![A-Za-z0-9_])", block.text)
            ):
                reason = "missing_bound_symbol"
            elif not scalar_literals(scalar_text) <= scalar_literals(
                factual_basis
            ) or _date_mismatch(scalar_text, factual_basis):
                reason = "scalar_or_date_mismatch"
            elif tokens and len(shared) / len(tokens) < 0.4:
                reason = "unrelated_expression"
            elif block.kind == "conditional" and (
                not block.assumptions or any(not a or a not in question for a in block.assumptions)
            ):
                reason = "unbound_user_premise"
            elif block.kind != "conditional" and block.assumptions:
                reason = "premises_require_conditional_expression"
            elif _negation_mismatch(
                block.text, evidence + ("\n" + assumptions if block.kind == "conditional" else "")
            ):
                reason = "polarity_mismatch"
            elif RetrievedContentGuard().scan(block.text).disposition != "ADMIT":
                reason = "content_guard"
        if diagnostics_only and reason not in {None, "unbound_or_discarded_evidence", "unbound_user_premise", "premises_require_conditional_expression", "content_guard"}:
            if audit is not None:
                audit.append({"text":block.text,"reason":reason,"authority":"DIAGNOSTIC_NOT_SEMANTIC_PROOF"})
            reason = None
        if reason is None and block.assumptions and any(a not in question for a in block.assumptions):
            reason = "unbound_user_premise"
        if reason is None and RetrievedContentGuard().scan(block.text).disposition != "ADMIT":
            reason = "content_guard"
        if reason:
            rejected.append({"text": block.text, "reason": reason})
        else:
            retained.append(block)
    return retained, rejected


def bind_generated_blocks(rows, generated_claims):
    ids = {claim.source_unit_id: claim.claim_id for claim in generated_claims}
    result = []
    for row in rows:
        if not {"text", "source_unit_ids"} <= set(row) or set(row) - {
            "kind",
            "text",
            "source_unit_ids",
            "need_refs",
            "assumptions",
        }:
            raise ValueError("invalid answer block fields")
        units = row["source_unit_ids"]
        if (
            not isinstance(units, list)
            or not units
            or len(set(units)) != len(units)
            or not set(units) <= set(ids)
        ):
            raise ValueError("answer block must bind its selected complete source units")
        # Host IDs are provenance syntax, not quantities in the explanation.
        mentioned = re.findall(
            r"(?<![A-Za-z0-9])S[1-9]\d*(?:U[1-9]\d*)?(?![A-Za-z0-9])", row["text"]
        )
        known_labels = set(units) | {uid.split("U")[0] for uid in units}
        if not set(mentioned) <= known_labels:
            raise ValueError("unbound source label in answer text")
        text = row["text"]
        for uid in sorted(set(mentioned), key=len, reverse=True):
            text = (
                text.replace("[" + uid + "]", "")
                .replace("（" + uid + "）", "")
                .replace("(" + uid + ")", "")
                .replace(uid, "")
            )
        result.append(
            AnswerBlock(
                kind="conditional" if row.get("assumptions") else "explanation",
                text=text,
                claim_ids=[ids[uid] for uid in units],
                assumptions=row.get("assumptions", []),
            )
        )
    return result
