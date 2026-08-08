from scripts.r3_evidence_tour import load_evidence_tour, render_markdown


def test_r3_evidence_tour_recomputes_public_decisions() -> None:
    tour = load_evidence_tour()

    assert tour["page_retrieval"]["decision"] == (
        "VALIDATION_REJECTED_FIXED_TEST_UNTOUCHED"
    )
    assert tour["answer"]["typed_candidate_oracle_count"] == 7
    assert tour["security_stress"]["guard_off_attack_success_count"] == 12
    assert tour["security_stress"]["guard_on_attack_success_count"] == 0
    assert all(len(value) == 64 for value in tour["evidence_sha256"].values())
    assert tour["human_review"]["status"] == "NOT_RUN"


def test_r3_evidence_tour_markdown_keeps_claim_boundary() -> None:
    rendered = render_markdown(load_evidence_tour())

    assert "ASR 12/48 -> 0/48" in rendered
    assert "not a blind holdout" in rendered
    assert "two independent reviewers" in rendered
