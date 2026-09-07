import json

from app.agent.evidence_ledger import build_ledger
from app.agent.generation_v2 import GenerationV2ResponseBuilder
from tests.agent_v2.test_generation_v2 import _replace_state, state_with_evidence, valid_payload
from tests.v2_test_support import admitted_search_hit


def test_related_quote_without_requested_duration_is_not_complete():
    state = state_with_evidence()
    text = "Policy A allows remote work."
    evidence = {
        state.analysis.required_aspects[0]: [
            admitted_search_hit(chunk_id="chunk-a", matched_text=text, context_text=text)
        ]
    }
    state = _replace_state(
        state, evidence_by_aspect=evidence, ledger=build_ledger(state.analysis, evidence)
    )
    builder = GenerationV2ResponseBuilder(
        model="fixture",
        max_attempts=1,
        chat_fn=lambda *a, **k: json.dumps(
            valid_payload(claim_text="Policy A allows remote work.")
        ),
    )
    response = builder.build(
        question="How many days does Policy A allow remote work?",
        state=state,
        mode="answered",
        stop_reason="completed",
        trace={},
    )
    assert response.mode != "answered"
    assert response.trace["answer_sufficiency"] == "missing_requested_value"
