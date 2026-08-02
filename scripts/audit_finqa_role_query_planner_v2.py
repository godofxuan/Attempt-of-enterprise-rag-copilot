try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from pathlib import Path

from app.external_datasets.finqa import DEFAULT_PRIVATE_ROOT
from app.external_datasets.finqa_role_query_planner_v2 import (
    PLANNER_VERSION,
    plan_role_queries_from_question_v2,
    verify_question_only_role_query_planner_v2,
)
from scripts import audit_finqa_role_query_planner_v1 as engine


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    engine.DEFAULT_OUTPUT = (
        REPOSITORY_ROOT
        / "docs"
        / "external_datasets"
        / "evidence"
        / "finqa_role_query_planner_v2_calibration_public_v1.json"
    )
    engine.DEFAULT_PRIVATE_OUTPUT = (
        DEFAULT_PRIVATE_ROOT
        / "role_query_planner_v2_audits"
        / "finqa-role-query-planner-v2-calibration-v1"
    )
    engine.IMPLEMENTATION_FILES = (
        "app/external_datasets/finqa_role_query_planner_v2.py",
        "scripts/audit_finqa_role_query_planner_v1.py",
        "scripts/audit_finqa_role_query_planner_v2.py",
    )
    engine.PLANNER_VERSION = PLANNER_VERSION
    engine.plan_role_queries_from_question = (
        plan_role_queries_from_question_v2
    )
    engine.verify_question_only_role_query_planner = (
        verify_question_only_role_query_planner_v2
    )
    return engine.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
