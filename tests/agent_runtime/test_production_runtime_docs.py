from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_required_production_runtime_evidence_is_present_and_nonempty() -> None:
    expected = {
        "ARCHITECTURE.md",
        "TOOL_POLICY.md",
        "DURABLE_LANGGRAPH.md",
        "IDEMPOTENT_SIDE_EFFECTS.md",
        "OTEL_GENAI.md",
        "FAILURE_MATRIX.md",
        "RESULTS.md",
        "RESUME_SAFE_CLAIMS.md",
        "KNOWN_LIMITATIONS.md",
        "APPROVAL_LIFECYCLE_INVARIANTS.md",
    }
    root = ROOT / "docs" / "production_runtime"
    assert {path.name for path in root.glob("*.md")} == expected
    assert all(len((root / name).read_text(encoding="utf-8")) > 300 for name in expected)


def test_external_patterns_and_agentdojo_decision_are_explicit() -> None:
    patterns = (
        ROOT / "docs" / "agent_runtime" / "EXTERNAL_HARNESS_PATTERN_DECISIONS.md"
    ).read_text(encoding="utf-8")
    dojo = (ROOT / "docs" / "security" / "AGENTDOJO_ADAPTATION_DECISION.md").read_text(
        encoding="utf-8"
    )

    for decision in ("ADOPT", "ADAPT", "REJECT"):
        assert decision in patterns
    assert "Claude Code is not a runtime dependency" in patterns
    assert "REJECTED for this runtime round" in dojo
    assert "No AgentDojo source" in dojo


def test_readme_keeps_bounded_default_and_durable_claim_scoped() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "bounded controller remains the default" in readme
    assert "access-request DRAFT (never an ACL grant)" in readme
    assert "exactly-once" not in readme.lower()
    assert "docs/production_runtime/" in readme


def test_approval_lifecycle_invariants_and_release_boundaries_are_explicit() -> None:
    invariants = (
        ROOT / "docs" / "production_runtime" / "APPROVAL_LIFECYCLE_INVARIANTS.md"
    ).read_text(encoding="utf-8")

    for number in range(1, 11):
        assert f"I{number}" in invariants
    for status in (
        "IMPLEMENTATION_COMPLETE",
        "EXACT_SHA_CI_REQUIRED",
        "NOT_MERGED",
        "NOT_RELEASED",
        "PORTFOLIO_READY",
        "PRODUCTION_NOT_VERIFIED",
        "DURABILITY_SCOPE = ACCESS_REQUEST_DRAFT_ONLY",
    ):
        assert status in invariants
    assert "Handle is not authentication" in invariants
    assert "not exactly-once" in invariants


def test_public_review_packet_binds_evidence_without_overclaiming() -> None:
    packet = (ROOT / "docs" / "review" / "FINAL_REVIEW_PACKET.md").read_text(encoding="utf-8")
    prompt = (ROOT / "docs" / "review" / "GPT_GITHUB_REVIEW_PROMPT_CN.md").read_text(
        encoding="utf-8"
    )

    required = (
        "e848d8e6090267b28d351758fe8d3cb557dcd586",
        "32470591376",
        "PROJECT_EVIDENCE_MAP.md",
        "KNOWN_LIMITATIONS.md",
        "3322 passed, 30 skipped",
        "Production readiness",
    )
    assert all(value in packet for value in required)
    assert "branch HEAD to equal the implementation SHA" in packet
    assert "不要只根据我粘贴的描述评价" in prompt
    assert "不要错误要求移动中的分支 HEAD" in prompt
