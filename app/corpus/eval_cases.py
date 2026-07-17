from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict, deque

from app.corpus.schemas import (
    CompanyFacts,
    CorpusProfile,
    DocumentSpec,
    EvalCase,
    EvalUserContext,
    TaskType,
    UserFixture,
)


TASK_ORDER: tuple[TaskType, ...] = (
    "fact_lookup",
    "version_conflict",
    "completeness",
    "comparison",
    "permission",
    "no_answer",
)


def _context(user: UserFixture) -> EvalUserContext:
    return EvalUserContext.model_validate(user.model_dump(mode="json"))


def _can_access(user: UserFixture, document: DocumentSpec) -> bool:
    return (
        user.tenant == document.metadata.tenant
        and user.region == document.metadata.region
        and bool(set(user.groups) & set(document.metadata.acl_groups))
    )


def _authorized_user(facts: CompanyFacts, document: DocumentSpec) -> UserFixture:
    users = [
        user
        for user in facts.users
        if user.user_id != "user_auditor" and _can_access(user, document)
    ]
    if not users:
        users = [user for user in facts.users if _can_access(user, document)]
    if not users:
        raise ValueError(f"no fixture user can access {document.doc_id!r}")
    return users[0]


def _filters(user: UserFixture) -> dict[str, str | list[str]]:
    return {
        "tenant": user.tenant,
        "region": user.region,
        "acl_groups": user.groups,
    }


def _authoritative_by_version(documents: list[DocumentSpec]) -> dict[str, DocumentSpec]:
    result = {
        document.metadata.version_id: document
        for document in documents
        if document.metadata.variant == "authoritative"
    }
    if len(result) != sum(
        1 for document in documents if document.metadata.variant == "authoritative"
    ):
        raise ValueError("authoritative version documents are not unique")
    return result


def _fact_lookup_cases(
    facts: CompanyFacts,
    authoritative: dict[str, DocumentSpec],
) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for policy in facts.policies:
        version = policy.active_version
        document = authoritative[version.version_id]
        user = _authorized_user(facts, document)
        for fact in version.facts:
            cases.append(
                EvalCase(
                    case_id=f"fact_{fact.fact_id}",
                    question=fact.question,
                    task_type="fact_lookup",
                    answer_mode="answered",
                    user_context=_context(user),
                    required_fact_ids=[fact.fact_id],
                    gold_doc_ids=[document.doc_id],
                    expected_answer=fact.answer,
                    expected_filters=_filters(user),
                    expected_authority_doc_ids=[document.doc_id],
                    tags=["current", policy.department, "atomic_fact"],
                )
            )
    return cases


def _version_conflict_cases(
    facts: CompanyFacts,
    authoritative: dict[str, DocumentSpec],
) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for policy in facts.policies:
        active = policy.active_version
        retired = next(version for version in policy.versions if version.status == "retired")
        active_document = authoritative[active.version_id]
        retired_document = authoritative[retired.version_id]
        user = _authorized_user(facts, active_document)
        fact = active.facts[0]
        cases.append(
            EvalCase(
                case_id=f"conflict_{policy.policy_id}",
                question=f"以当前生效且权威的制度为准，{fact.question}",
                task_type="version_conflict",
                answer_mode="answered",
                user_context=_context(user),
                required_fact_ids=[fact.fact_id],
                gold_doc_ids=[active_document.doc_id],
                distractor_doc_ids=[retired_document.doc_id],
                expected_answer=fact.answer,
                expected_filters=_filters(user),
                expected_authority_doc_ids=[active_document.doc_id],
                tags=["version", "conflict", policy.department],
            )
        )
    return cases


def _completeness_cases(
    facts: CompanyFacts,
    authoritative: dict[str, DocumentSpec],
) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for policy in facts.policies:
        active = policy.active_version
        document = authoritative[active.version_id]
        user = _authorized_user(facts, document)
        cases.append(
            EvalCase(
                case_id=f"complete_{policy.policy_id}",
                question=f"请完整列出《{policy.title}》当前版本的两项关键要求。",
                task_type="completeness",
                answer_mode="answered",
                user_context=_context(user),
                required_fact_ids=[fact.fact_id for fact in active.facts],
                gold_doc_ids=[document.doc_id],
                expected_answer="；".join(fact.answer for fact in active.facts),
                expected_filters=_filters(user),
                expected_authority_doc_ids=[document.doc_id],
                tags=["completeness", policy.department, "multi_fact"],
            )
        )
    return cases


def _comparison_cases(
    facts: CompanyFacts,
    authoritative: dict[str, DocumentSpec],
) -> list[EvalCase]:
    auditor = next(user for user in facts.users if user.user_id == "user_auditor")
    cases: list[EvalCase] = []
    for index, first_policy in enumerate(facts.policies):
        second_policy = facts.policies[(index + 1) % len(facts.policies)]
        first_version = first_policy.active_version
        second_version = second_policy.active_version
        first_document = authoritative[first_version.version_id]
        second_document = authoritative[second_version.version_id]
        if not (_can_access(auditor, first_document) and _can_access(auditor, second_document)):
            raise ValueError("auditor fixture must access comparison gold documents")
        first_fact = first_version.facts[0]
        second_fact = second_version.facts[0]
        cases.append(
            EvalCase(
                case_id=f"compare_{first_policy.policy_id}_{second_policy.policy_id}",
                question=(
                    f"对比《{first_policy.title}》和《{second_policy.title}》当前版本的"
                    "第一项数值要求。"
                ),
                task_type="comparison",
                answer_mode="answered",
                user_context=_context(auditor),
                required_fact_ids=[first_fact.fact_id, second_fact.fact_id],
                gold_doc_ids=[first_document.doc_id, second_document.doc_id],
                expected_answer=f"{first_fact.answer}；{second_fact.answer}",
                expected_filters=_filters(auditor),
                expected_authority_doc_ids=[
                    first_document.doc_id,
                    second_document.doc_id,
                ],
                tags=["comparison", "cross_policy", "multi_document"],
            )
        )
    return cases


def _permission_cases(
    facts: CompanyFacts,
    authoritative: dict[str, DocumentSpec],
) -> list[EvalCase]:
    contractor = next(user for user in facts.users if user.user_id == "user_contractor")
    cases: list[EvalCase] = []
    for policy in facts.policies:
        active = policy.active_version
        if active.acl_groups == ["all_employees"]:
            continue
        document = authoritative[active.version_id]
        if _can_access(contractor, document):
            raise ValueError("contractor fixture unexpectedly accesses a restricted document")
        cases.append(
            EvalCase(
                case_id=f"permission_{policy.policy_id}",
                question=f"请告诉我《{policy.title}》当前版本的全部内部要求。",
                task_type="permission",
                answer_mode="permission",
                user_context=_context(contractor),
                forbidden_doc_ids=[document.doc_id],
                expected_filters=_filters(contractor),
                tags=["acl", "permission", policy.department],
            )
        )
    return cases


def _no_answer_cases(
    facts: CompanyFacts,
    authoritative: dict[str, DocumentSpec],
) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for policy in facts.policies:
        document = authoritative[policy.active_version.version_id]
        user = _authorized_user(facts, document)
        cases.append(
            EvalCase(
                case_id=f"missing_{policy.policy_id}",
                question=f"《{policy.title}》是否规定 2027 年所有额度自动翻倍？",
                task_type="no_answer",
                answer_mode="not_found",
                user_context=_context(user),
                expected_filters=_filters(user),
                tags=["no_answer", "unsupported", policy.department],
            )
        )
    return cases


def build_eval_splits(
    facts: CompanyFacts,
    documents: list[DocumentSpec],
    profile: CorpusProfile,
    seed: int | None = None,
) -> tuple[list[EvalCase], list[EvalCase]]:
    authoritative = _authoritative_by_version(documents)
    candidates = [
        *_fact_lookup_cases(facts, authoritative),
        *_version_conflict_cases(facts, authoritative),
        *_completeness_cases(facts, authoritative),
        *_comparison_cases(facts, authoritative),
        *_permission_cases(facts, authoritative),
        *_no_answer_cases(facts, authoritative),
    ]
    by_task: dict[TaskType, list[EvalCase]] = defaultdict(list)
    for case in candidates:
        by_task[case.task_type].append(case)

    rng = random.Random(profile.seed if seed is None else seed)
    for task in TASK_ORDER:
        rng.shuffle(by_task[task])

    required_count = profile.eval_dev_count + profile.eval_test_count
    available_count = sum(len(cases) for cases in by_task.values())
    if available_count < required_count:
        raise ValueError(
            f"profile requests {required_count} eval cases but only "
            f"{available_count} exist"
        )

    while sum(len(cases) for cases in by_task.values()) > required_count:
        largest_task = max(TASK_ORDER, key=lambda task: len(by_task[task]))
        by_task[largest_task].pop()

    dev_counts = {task: len(by_task[task]) // 2 for task in TASK_ORDER}
    while sum(dev_counts.values()) > profile.eval_dev_count:
        task = max(
            (
                candidate
                for candidate in TASK_ORDER
                if dev_counts[candidate] > 1
            ),
            key=lambda candidate: len(by_task[candidate]),
        )
        dev_counts[task] -= 1
    while sum(dev_counts.values()) < profile.eval_dev_count:
        task = max(
            (
                candidate
                for candidate in TASK_ORDER
                if dev_counts[candidate] < len(by_task[candidate]) - 1
            ),
            key=lambda candidate: len(by_task[candidate]) - dev_counts[candidate],
        )
        dev_counts[task] += 1

    def interleave(groups: dict[TaskType, list[EvalCase]]) -> list[EvalCase]:
        queues = {task: deque(groups[task]) for task in TASK_ORDER}
        result: list[EvalCase] = []
        while any(queues.values()):
            for task in TASK_ORDER:
                if queues[task]:
                    result.append(queues[task].popleft())
        return result

    dev_groups = {
        task: by_task[task][: dev_counts[task]] for task in TASK_ORDER
    }
    test_groups = {
        task: by_task[task][dev_counts[task] :] for task in TASK_ORDER
    }
    return interleave(dev_groups), interleave(test_groups)


def serialize_eval_cases(cases: list[EvalCase]) -> bytes:
    payload = [case.model_dump(mode="json") for case in cases]
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return text.encode("utf-8")


def build_test_manifest_line(test_bytes: bytes) -> str:
    return f"{hashlib.sha256(test_bytes).hexdigest()}  test.json\n"
