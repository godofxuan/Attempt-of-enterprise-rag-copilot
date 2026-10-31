"""Bind concise model expression to the same retained source claims.

Exact quotes remain verified independently. These finite consistency checks are
not semantic entailment; live content evaluation is recorded separately.
"""

import re
from app.agent.citation_verifier import _content_tokens, _date_mismatch, _negation_mismatch
from app.domain.evidence import AnswerBlock
from app.security.retrieved_content import RetrievedContentGuard


def retained_blocks(blocks, claims, question):
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
            tokens = _content_tokens(block.text)
            shared = tokens & _content_tokens(evidence + "\n" + question)
            scalars = set(re.findall(r"\d+(?:\.\d+)?", block.text))
            permitted = set(re.findall(r"\d+(?:\.\d+)?", evidence + "\n" + question))
            if not scalars <= permitted or _date_mismatch(block.text, evidence + "\n" + question):
                reason = "scalar_or_date_mismatch"
            elif tokens and len(shared) / len(tokens) < 0.4:
                reason = "unrelated_expression"
            elif _negation_mismatch(block.text, evidence):
                reason = "polarity_mismatch"
            elif RetrievedContentGuard().scan(block.text).disposition != "ADMIT":
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
        if set(row) != {"kind", "text", "source_unit_ids"}:
            raise ValueError("invalid answer block fields")
        units = row["source_unit_ids"]
        if (
            not isinstance(units, list)
            or not units
            or len(set(units)) != len(units)
            or not set(units) <= set(ids)
        ):
            raise ValueError("answer block must bind its selected complete source units")
        result.append(
            AnswerBlock(kind=row["kind"], text=row["text"], claim_ids=[ids[uid] for uid in units])
        )
    return result
