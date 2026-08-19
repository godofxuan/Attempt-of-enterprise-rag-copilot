from __future__ import annotations

from pathlib import Path

from scripts.eval_enterprise_v2 import verify_frozen_test_hash


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

EXPECTED_REQUIREMENTS = {
    "fastapi==0.136.0",
    "uvicorn[standard]==0.44.0",
    "streamlit==1.56.0",
    "requests==2.33.1",
    "pydantic==2.13.2",
    "pydantic-settings==2.14.0",
    "python-dotenv==1.2.2",
    "openai==2.32.0",
    "faiss-cpu==1.13.2",
    "rank-bm25==0.2.2",
    "numpy==2.4.4",
    "jieba==0.42.1",
    "pytest==9.0.3",
    "pypdf==6.14.2",
    "python-docx==1.2.0",
    "PyJWT==2.13.0",
    "cryptography==49.0.0",
    "mcp==2.0.0",
    "langgraph==1.2.11",
}


def test_direct_requirements_match_the_proven_local_versions() -> None:
    lines = {
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert lines == EXPECTED_REQUIREMENTS


def test_pytest_uses_system_temp_instead_of_shared_repository_basetemp() -> None:
    config = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert "--basetemp" not in config
    assert "data/eval_outputs/pytest_tmp" not in config.replace("\\", "/")
    assert "--import-mode=importlib" in config


def test_git_attributes_preserve_hash_sensitive_text_bytes_across_platforms() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()

    assert "* text=auto eol=lf" in attributes
    for pattern in ["*.docx", "*.faiss", "*.pdf", "*.pkl", "*.png"]:
        assert f"{pattern} binary" in attributes


def test_ci_is_read_only_deterministic_and_does_not_call_live_services() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    normalized = workflow.lower()

    for required in [
        "permissions:",
        "contents: read",
        "os: [ubuntu-latest, windows-latest]",
        "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803",
        "fetch-depth: 0",
        "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1",
        "python-version: \"3.11.9\"",
        "cache: pip",
        "python -m pip install pip==26.0.1",
        "python -m pip install -r requirements.txt",
        "python -m pip check",
        "python -m compileall -q app scripts streamlit_app tests",
        "verify_frozen_test_hash",
        'PYTHONFAULTHANDLER: "1"',
        "python -u -X faulthandler -m pytest -vv",
        "Publish deterministic test failure context",
        '--expected-branch "${{ github.ref_name }}"',
        '--expected-sha "${{ github.sha }}"',
        "python -m scripts.audit_public_repo",
    ]:
        assert required in workflow

    assert workflow.count("fetch-depth: 0") == 2

    for forbidden in [
        "ollama",
        "uvicorn",
        "load_profile",
        "--mode live",
        "secrets.",
    ]:
        assert forbidden not in normalized


def test_frozen_test_hash_still_matches_manifest() -> None:
    expected, actual = verify_frozen_test_hash(ROOT / "data" / "v2" / "eval")
    assert expected == actual
    assert actual == "556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338"
