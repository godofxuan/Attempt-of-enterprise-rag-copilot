"""Actual FastAPI/JWT/index path with the existing fixed model fixture."""

from tests.api_v2 import test_runtime_closure_flow

service = test_runtime_closure_flow.service


def test_api_omitted_part_is_in_body_and_trace(service):
    start, _, _ = service
    with start([dict(id="onboarding", text="入职需要身份证。")]) as client:
        result = client.post("/agent/v2/chat", json={"question": "入职需要哪些材料，试用期多久？"})
    body = result.json()
    assert result.status_code == 200
    assert body["mode"] == "partial"
    assert body["trace"]["final_mode"] == "partial"
    assert body["trace"]["question_part_coverage"]["missing"] >= 1
    assert "试用期" in body["answer"]
    assert body["claims"] and all(c["supported"] for c in body["citations"])


def test_api_complete_multi_part_answer_stays_answered(service):
    start, _, _ = service
    with start([dict(id="onboarding", text="入职需要身份证。入职试用期为三个月。")]) as client:
        result = client.post("/agent/v2/chat", json={"question": "入职需要哪些材料，试用期多久？"})
    body = result.json()
    assert result.status_code == 200 and body["mode"] == "answered"
    assert body["trace"]["question_part_coverage"]["missing"] == 0
