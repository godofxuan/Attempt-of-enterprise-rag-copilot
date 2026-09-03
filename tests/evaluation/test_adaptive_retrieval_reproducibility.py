from scripts.verify_adaptive_retrieval_reproducibility import compare_runs


def _row(question_id: str, *, raw_output_sha256: str = "a" * 64) -> dict:
    return {
        "question_id": question_id,
        "public_row": {
            "baseline_failed": True,
            "assessor_input_messages_sha256": "b" * 64,
            "assessor_request_sha256": "c" * 64,
            "assessor_seed": 42,
            "raw_output_sha256": raw_output_sha256,
            "proposal_sha256": "d" * 64,
            "model_transport_attempts": 1,
            "model_transport_retries": 0,
            "retry_improved": False,
            "retry_fully_recovered": False,
            "retry_no_change": True,
            "retry_worse": False,
            "rewrite_status": "accepted",
            "rejection_reason": None,
        },
    }


def _summary() -> dict:
    return {
        "git_sha": "e" * 40,
        "git_dirty": False,
        "branch": "main",
        "dataset_manifest_sha256": "f" * 64,
        "question_ids_sha256": "1" * 64,
        "index_manifest_sha256": "2" * 64,
        "embedding_model_sha256": "3" * 64,
        "assessor_model": {"full_model_digest": "4" * 64},
        "ollama_runtime": {"ollama_version": "0"},
        "assessor_generation_options": {"temperature": 0.0},
        "critical_file_sha256": {"script": "5" * 64},
    }


def test_reproducibility_closure_requires_every_hash_and_outcome_to_match() -> None:
    result = compare_runs(
        first_summary={**_summary(), "run_id": "first"},
        second_summary={**_summary(), "run_id": "second"},
        first_rows=[_row("question-a")],
        second_rows=[_row("question-a")],
    )

    assert result["same_environment_repeatability"] == "PASS"
    assert result["decision"] == "REPRODUCIBILITY_CLOSED"


def test_reproducibility_closure_fails_when_raw_output_changes() -> None:
    result = compare_runs(
        first_summary=_summary(),
        second_summary=_summary(),
        first_rows=[_row("question-a")],
        second_rows=[_row("question-a", raw_output_sha256="z" * 64)],
    )

    assert result["same_environment_repeatability"] == "FAIL"
    assert result["same_raw_output_sha256_count"] == 0


def test_reproducibility_closure_fails_when_any_outcome_field_changes() -> None:
    first = _row("question-a")
    second = _row("question-a")
    second["public_row"]["retry_no_change"] = False

    result = compare_runs(
        first_summary=_summary(),
        second_summary=_summary(),
        first_rows=[first],
        second_rows=[second],
    )

    assert result["same_environment_repeatability"] == "FAIL"
    assert result["same_outcome_tuple_count"] == 0
