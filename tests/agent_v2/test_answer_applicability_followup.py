import pytest

from tests.agent_v2.test_query_coverage_v1 import runner_fixture
from tests.v2_test_support import user_context


ELM = (
    "Elm office travel policy\n"
    "Staff grade | Elm lodging limit (CNY/night)\n"
    "G01 | 253.50\nG24 | 276.50"
)


@pytest.mark.parametrize("office,grade", [("Quarry", "G01"), ("Summit", "G24")])
def test_wrong_office_replay_is_not_an_answer(
    office, grade, snapshot_factory, document_factory, chunk_factory
):
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[ELM], claim=ELM
    )
    response = runner.run(
        f"For {office} office staff grade {grade}, what is the lodging limit in CNY/night?",
        user_context(),
    )
    assert response.mode == "not_found"
    assert not response.claims
    assert not response.citations
    assert "253.50" not in response.answer and "276.50" not in response.answer
    assert response.stop_reason == response.trace["stop_reason"] == "not_found"


def test_correct_office_and_grade_keep_answer(
    snapshot_factory, document_factory, chunk_factory
):
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[ELM], claim=ELM
    )
    response = runner.run(
        "For Elm office staff grade G24, what is the lodging limit in CNY/night?",
        user_context(),
    )
    assert response.mode == "answered"
    assert "276.50" in response.answer
    assert response.citations and all(c.supported for c in response.citations)


def test_final_host_check_does_not_trust_upstream_coverage(
    monkeypatch, snapshot_factory, document_factory, chunk_factory
):
    monkeypatch.setattr("app.agent.controller_v2.has_query_anchor_support", lambda *args: True)
    runner, seen = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[ELM], claim=ELM
    )
    response = runner.run(
        "For Quarry office staff grade G01, what is the lodging limit?", user_context()
    )
    assert seen, "This counterexample must exercise generation and final publication."
    assert response.mode == "not_found"
    assert not response.claims and not response.sources
    assert response.warnings
    assert response.trace["query_applicability"]["dropped_claims"] == 1


def test_final_host_check_covers_extractive_builder(
    monkeypatch, snapshot_factory, document_factory, chunk_factory
):
    from app.agent.runner_v2 import ExtractiveResponseBuilder

    monkeypatch.setattr("app.agent.controller_v2.has_query_anchor_support", lambda *args: True)
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[ELM], claim=ELM
    )
    runner.response_builder = ExtractiveResponseBuilder()
    response = runner.run("What is the Quarry office lodging limit?", user_context())
    assert response.mode == "not_found"
    assert not response.claims


def test_grade_substring_does_not_count_as_requested_grade(
    snapshot_factory, document_factory, chunk_factory
):
    text = "Elm office\nStaff grade | Limit (CNY/night)\nG010 | 500.00"
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[text], claim=text
    )
    response = runner.run("For Elm office staff grade G01, what is the limit?", user_context())
    assert response.mode == "not_found"


def test_office_mentioned_in_note_does_not_license_another_office_table(
    snapshot_factory, document_factory, chunk_factory
):
    text = "Quarry office contact directory.\n" + ELM
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[text], claim=text
    )
    response = runner.run("What is the Quarry office lodging limit?", user_context())
    assert response.mode != "answered"


def test_unspecified_office_does_not_drop_explicit_grade_answer(
    snapshot_factory, document_factory, chunk_factory
):
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[ELM], claim=ELM
    )
    response = runner.run("What is the lodging limit for staff grade G24?", user_context())
    assert response.mode == "answered"
    assert "276.50" in response.answer


def test_csv_section_scope_preserves_verified_table_response():
    from app.domain.evidence import AnswerResponse
    from app.agent.answer_applicability import enforce_answer_applicability
    from app.domain.evidence import Claim, ClaimCitation, AnswerSource

    # Table body need not repeat the word 'office'; its admitted section supplies it.
    text = "Staff grade | Apollo lodging limit (CNY/night)\nG24 | 224.50"
    response = AnswerResponse(mode="partial", stop_reason="partial_evidence", answer=text,
        claims=[Claim(claim_id="c1", text=text, cited_chunk_ids=["chunk-a"])],
        citations=[ClaimCitation(claim_id="c1", cited_chunk_ids=["chunk-a"], citation_present=True,
            references_visible_evidence=True, lexical_support=1, supported=True)],
        sources=[AnswerSource(doc_id="doc-a", source_path="doc.csv", section_path=["Apollo office travel policy", "table-1"],
            chunk_id="chunk-a", preview=text, index_run_id="run-one", version_id="policy-a@2026")])
    result = enforce_answer_applicability("For Apollo office staff grade G24, what is the limit?", response)
    assert result.mode == "partial"
    assert result.claims == response.claims
    wrong = enforce_answer_applicability("For Quarry office staff grade G24, what is the limit?", response)
    assert wrong.mode == "not_found"


def test_other_grade_only_generation_falls_back_to_supported_full_table(
    snapshot_factory, document_factory, chunk_factory
):
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory,
        texts=[ELM], claim="G01 | 253.50"
    )
    response = runner.run("For Elm office staff grade G24, what is the limit?", user_context())
    # Existing grounding rejects the short unrelated row. Its extractive fallback
    # legitimately preserves the full visible table, including the requested row.
    assert response.mode == "partial"
    assert response.claims and all("G24 | 276.50" in c.text for c in response.claims)
    assert response.citations and all(c.supported for c in response.citations)
