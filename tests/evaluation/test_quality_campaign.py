from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation.quality_campaign import (
    _require_matching_owner,
    initialize_quality_review_campaign,
    verify_quality_review_campaign_readiness,
)
from scripts import (
    init_quality_review_campaign,
    verify_quality_review_campaign,
)


ROOT = Path(__file__).resolve().parents[2]
PACKET = (
    ROOT / "data" / "v2" / "quality_review" / "r2-s8-calibration-v4"
)


def test_campaign_initialization_is_blank_private_and_self_verifying(
    tmp_path: Path,
) -> None:
    campaign = initialize_quality_review_campaign(
        packet_dir=PACKET,
        out_root=tmp_path / "campaigns",
        campaign_id="r2-s8-human-pilot-test",
    )

    manifest = verify_quality_review_campaign_readiness(campaign)

    assert manifest.status == "NOT_RUN"
    assert manifest.claim_status == "NOT_RUN"
    assert manifest.human_judgements_completed == 0
    assert manifest.reviewer_slots == ("reviewer-a", "reviewer-b")
    assert (
        campaign / "coordinator" / "identity-pepper.bin"
    ).read_bytes() not in b"".join(
        path.read_bytes()
        for path in (campaign / "reviewer-kits").rglob("*")
        if path.is_file()
    )
    assert list((campaign / "inbox").iterdir()) == []
    assert list((campaign / "submissions").iterdir()) == []
    assert list((campaign / "evidence").iterdir()) == []
    for slot in manifest.reviewer_slots:
        kit = campaign / "reviewer-kits" / slot
        assert (kit / "completed_template.csv").read_bytes() == (
            kit / manifest.packet_id / "submission_template.csv"
        ).read_bytes()
    assert (
        campaign / "coordinator" / "reviewer-a.identity.txt"
    ).read_bytes() == b""
    commands = (
        campaign / "coordinator" / "COMMANDS.md"
    ).read_text(encoding="utf-8")
    assert "submissions\\reviewer-a" in commands
    assert "submissions\\reviewer-b" in commands
    (
        campaign / "coordinator" / "reviewer-a.identity.txt"
    ).write_text("stable-reviewer-a-id\n", encoding="utf-8")
    with pytest.raises(ValueError, match="identity placeholder is not blank"):
        verify_quality_review_campaign_readiness(campaign)


def test_campaign_is_no_overwrite_and_detects_tampering(
    tmp_path: Path,
) -> None:
    out_root = tmp_path / "campaigns"
    campaign = initialize_quality_review_campaign(
        packet_dir=PACKET,
        out_root=out_root,
        campaign_id="r2-s8-human-pilot-test",
    )

    with pytest.raises(FileExistsError, match="already exists"):
        initialize_quality_review_campaign(
            packet_dir=PACKET,
            out_root=out_root,
            campaign_id="r2-s8-human-pilot-test",
        )

    task = (
        campaign
        / "reviewer-kits"
        / "reviewer-a"
        / "REVIEWER_TASK.md"
    )
    task.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="kit hash mismatch"):
        verify_quality_review_campaign_readiness(campaign)


def test_campaign_rejects_pepper_and_undeclared_file_changes(
    tmp_path: Path,
) -> None:
    campaigns = tmp_path / "campaigns"
    first = initialize_quality_review_campaign(
        packet_dir=PACKET,
        out_root=campaigns,
        campaign_id="pepper-tamper",
    )
    pepper = first / "coordinator" / "identity-pepper.bin"
    pepper.write_bytes(b"x" * 32)
    with pytest.raises(ValueError, match="identity (pepper|domain)"):
        verify_quality_review_campaign_readiness(first)

    second = initialize_quality_review_campaign(
        packet_dir=PACKET,
        out_root=campaigns,
        campaign_id="extra-file",
    )
    (second / "reviewer-kits" / "reviewer-a" / "secret.txt").write_text(
        "unexpected\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing or undeclared"):
        verify_quality_review_campaign_readiness(second)


def test_campaign_cli_initializes_and_verifies_not_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_checks: list[bool] = []
    monkeypatch.setattr(
        init_quality_review_campaign,
        "validate_quality_review_campaign_owner_context",
        lambda: owner_checks.append(True),
    )
    out_root = tmp_path / "campaigns"
    assert (
        init_quality_review_campaign.main(
            [
                "--campaign-id",
                "cli-human-pilot",
                "--packet-dir",
                str(PACKET),
                "--out-root",
                str(out_root),
            ]
        )
        == 0
    )
    initialized = json.loads(capsys.readouterr().out)
    assert owner_checks == [True]
    assert initialized["status"] == "NOT_RUN"
    assert initialized["human_judgements_completed"] == 0

    campaign = out_root / "cli-human-pilot"
    assert (
        verify_quality_review_campaign.main(
            ["--campaign-dir", str(campaign)]
        )
        == 0
    )
    verified = json.loads(capsys.readouterr().out)
    assert verified["claim_status"] == "NOT_RUN"
    assert verified["reviewer_slots"] == ["reviewer-a", "reviewer-b"]


def test_campaign_owner_context_rejects_delegated_windows_identity() -> None:
    with pytest.raises(RuntimeError, match="owner mismatch"):
        _require_matching_owner("delegated-worker", "operator")

    _require_matching_owner("OPERATOR", "operator")
