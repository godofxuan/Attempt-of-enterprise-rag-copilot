from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from app.corpus.schemas import EvalCase
from app.domain.agent import AnswerMode
from app.domain.queries import UserContext
from app.evaluation.security import SECURITY_PROBES


DemoCategory = Literal[
    "single_document",
    "comparison",
    "version_conflict",
    "multi_condition",
    "not_found",
    "permission",
    "direct_injection",
]


class DemoCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    category: DemoCategory
    label: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=2000)
    user: UserContext
    expected_mode: AnswerMode
    provenance: Literal["eval_case", "security_probe"]
    provenance_id: str = Field(min_length=1, max_length=200)


DemoCases: TypeAlias = tuple[
    DemoCase,
    DemoCase,
    DemoCase,
    DemoCase,
    DemoCase,
    DemoCase,
    DemoCase,
]


_CASE_SPECS: tuple[tuple[DemoCategory, str, str], ...] = (
    (
        "single_document",
        "Single policy lookup",
        "fact_hr_remote_2026_notice",
    ),
    (
        "comparison",
        "Cross-policy comparison",
        "compare_procurement_vendor_engineering_release",
    ),
    (
        "version_conflict",
        "Current-version conflict",
        "conflict_customer_refund",
    ),
    (
        "multi_condition",
        "Multi-condition completeness",
        "complete_security_incident",
    ),
    ("not_found", "Grounded not found", "missing_engineering_release"),
    ("permission", "ACL permission boundary", "permission_hr_compensation"),
)


def load_demo_cases(root: Path) -> DemoCases:
    dataset = Path(root) / "data" / "v2" / "eval" / "test.json"
    try:
        payload = json.loads(dataset.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("canonical evaluation cases are unavailable") from exc
    if not isinstance(payload, list):
        raise ValueError("canonical evaluation dataset must be a JSON array")
    cases = [EvalCase.model_validate(item) for item in payload]
    by_id = {case.case_id: case for case in cases}

    result: list[DemoCase] = []
    for category, label, case_id in _CASE_SPECS:
        case = by_id.get(case_id)
        if case is None:
            raise ValueError(f"canonical demo case is missing: {case_id}")
        result.append(
            DemoCase(
                category=category,
                label=label,
                question=case.question,
                user=_runtime_user(case),
                expected_mode=case.answer_mode,
                provenance="eval_case",
                provenance_id=case.case_id,
            )
        )

    probe = next(
        (
            item
            for item in SECURITY_PROBES
            if item.probe_id == "instruction_override"
        ),
        None,
    )
    if probe is None:
        raise ValueError("canonical direct injection probe is missing")
    result.append(
        DemoCase(
            category="direct_injection",
            label="Direct instruction override",
            question=probe.prompt,
            user=UserContext(
                user_id="demo-security-user",
                tenant_id="starbridge-cn",
                region="cn",
                groups=["all_employees"],
                roles=[],
            ),
            expected_mode="unsafe",
            provenance="security_probe",
            provenance_id=probe.probe_id,
        )
    )
    if len(result) != 7:
        raise ValueError("demo case contract requires exactly seven cases")
    return tuple(result)  # type: ignore[return-value]


def _runtime_user(case: EvalCase) -> UserContext:
    return UserContext(
        user_id=case.user_context.user_id,
        tenant_id=case.user_context.tenant,
        region=case.user_context.region,
        groups=list(case.user_context.groups),
        roles=[],
    )


__all__ = ["DemoCase", "DemoCases", "load_demo_cases"]
