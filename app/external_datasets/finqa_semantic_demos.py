from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import requests
from pydantic import BaseModel, ConfigDict, Field

from app.external_datasets.finqa import (
    DEFAULT_SOURCE_ROOT,
    FINQA_REVISION,
)
from app.external_datasets.finqa_diagnostics import (
    parse_finqa_gold_program,
)
from app.external_datasets.finqa_semantic_program import (
    MAX_SEMANTIC_PROGRAM_STEPS,
    MAX_SEMANTIC_ROLES,
    SemanticProgramSkeleton,
    SemanticProgramStep,
    SemanticRoleRef,
    SemanticRoleSpec,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
from app.external_datasets.finqa_typed_program import StepRef


DEMO_RETRIEVER_VERSION = "deterministic_idf_token_overlap_v1"
FINQA_TRAIN_SHA256 = (
    "49f237eb9779b569473b26b08048867d04635a7cc39ad6a7a5664c55bb428db6"
)
_TRAIN_URL = (
    "https://raw.githubusercontent.com/czyssrs/FinQA/"
    f"{FINQA_REVISION}/dataset/train.json"
)
_GOLD_STEP = re.compile(r"([a-z_]+)\(([^()]*)\)(?:,\s*|$)")
_STEP_REFERENCE = re.compile(r"#([0-9]+)")
_NUMBER = re.compile(
    r"(?<!\w)(?:const_m?\d+|-?(?:\d[\d,]*(?:\.\d+)?|\.\d+)%?)(?!\w)",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"[a-z][a-z_]+", re.IGNORECASE)
_SUPPORTED_OPERATION = {
    "add": "ADD",
    "subtract": "SUB",
    "multiply": "MUL",
    "divide": "DIV",
}
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "did",
    "do",
    "for",
    "from",
    "how",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "were",
    "what",
}


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class FinQAStructuralDemo(_StrictFrozenModel):
    question_template: str = Field(min_length=1, max_length=2_000)
    skeleton: SemanticProgramSkeleton


def demonstration_payload_sha256(
    demonstrations: Sequence[FinQAStructuralDemo],
) -> str | None:
    if not demonstrations:
        return None
    payload = [
        item.model_dump(mode="json") for item in demonstrations
    ]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


class FinQADemoSource(_StrictFrozenModel):
    case_id: str = Field(min_length=1, max_length=512)
    question: str = Field(min_length=1, max_length=2_000)
    program: str = Field(min_length=1, max_length=2_000)


@dataclass(frozen=True)
class _IndexedDemo:
    case_id: str
    identity_sha256: str
    tokens: frozenset[str]
    payload: FinQAStructuralDemo


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        token
        for token in _TOKEN.findall(text.casefold())
        if token not in _STOPWORDS
    )


def _question_template(question: str) -> str:
    return " ".join(_NUMBER.sub("<NUM>", question).split())


def _role_name(
    *,
    operation: str,
    position: int,
    percent_change: bool,
) -> tuple[str, str]:
    if operation == "add":
        return "component", "none"
    if operation == "multiply":
        return "factor", "none"
    if operation == "subtract":
        if percent_change:
            return (
                ("new_value", "end")
                if position == 0
                else ("old_value", "start")
            )
        return (
            ("comparison_left", "none")
            if position == 0
            else ("comparison_right", "none")
        )
    return (
        ("part", "none")
        if position == 0
        else ("total", "none")
    )


def _build_value_free_skeleton(
    case: FinQADemoSource,
) -> SemanticProgramSkeleton | None:
    gold = parse_finqa_gold_program(case.program)
    if (
        not gold.operations
        or len(gold.operations) > MAX_SEMANTIC_PROGRAM_STEPS
        or any(item not in _SUPPORTED_OPERATION for item in gold.operations)
    ):
        return None
    matches = tuple(_GOLD_STEP.finditer(case.program.strip()))
    if len(matches) != len(gold.operations):
        return None
    percent_change = (
        extract_financial_question_intent_v2(
            case.question
        ).operation_family
        == "percent_change"
    )
    role_by_operand: dict[str, str] = {}
    role_specs: list[SemanticRoleSpec] = []
    steps: list[SemanticProgramStep] = []
    for step_index, match in enumerate(matches):
        operation = match.group(1)
        arguments = tuple(
            item.strip() for item in match.group(2).split(",")
        )
        if len(arguments) != 2:
            return None
        references = []
        for argument_index, argument in enumerate(arguments):
            step_match = _STEP_REFERENCE.fullmatch(argument)
            if step_match is not None:
                referenced_index = int(step_match.group(1))
                if referenced_index >= step_index:
                    return None
                references.append(
                    StepRef(step_id=f"step-{referenced_index + 1:02d}")
                )
                continue
            role_id = role_by_operand.get(argument)
            if role_id is None:
                if len(role_specs) >= MAX_SEMANTIC_ROLES:
                    return None
                role_id = f"role-{len(role_specs) + 1:02d}"
                role_by_operand[argument] = role_id
                semantic_role, period_role = _role_name(
                    operation=operation,
                    position=argument_index,
                    percent_change=percent_change,
                )
                role_specs.append(
                    SemanticRoleSpec(
                        role_id=role_id,
                        semantic_role=semantic_role,
                        period_role=period_role,
                    )
                )
            references.append(SemanticRoleRef(role_id=role_id))
        try:
            steps.append(
                SemanticProgramStep(
                    step_id=f"step-{step_index + 1:02d}",
                    operation=_SUPPORTED_OPERATION[operation],
                    arguments=tuple(references),
                )
            )
        except ValueError:
            return None
    try:
        return SemanticProgramSkeleton(
            roles=tuple(role_specs),
            steps=tuple(steps),
            output_step_id=steps[-1].step_id,
        )
    except ValueError:
        return None


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_finqa_demo_sources(
    path: Path,
    *,
    expected_sha256: str = FINQA_TRAIN_SHA256,
) -> tuple[tuple[FinQADemoSource, ...], str]:
    content = path.resolve().read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if (
        not content
        or len(content) > 128 * 1024 * 1024
        or digest != expected_sha256
    ):
        raise ValueError("FinQA demo source does not match pinned train bytes")
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("FinQA demo source is not strict UTF-8 JSON") from exc
    if not isinstance(payload, list) or not payload:
        raise ValueError("FinQA demo source must be a non-empty array")
    sources: list[FinQADemoSource] = []
    for item in payload:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("qa"), dict)
        ):
            raise ValueError("FinQA demo source row is malformed")
        sources.append(
            FinQADemoSource(
                case_id=item.get("id"),
                question=item["qa"].get("question"),
                program=item["qa"].get("program"),
            )
        )
    case_ids = [source.case_id for source in sources]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("FinQA demo source IDs must be unique")
    return tuple(sources), digest


def download_finqa_train_for_demos(
    *,
    source_root: Path = DEFAULT_SOURCE_ROOT,
    session: requests.Session | None = None,
) -> tuple[Path, str, int]:
    target = Path(source_root).resolve() / "dataset" / "train.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        content = target.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest == FINQA_TRAIN_SHA256:
            return target, digest, len(content)
        raise ValueError("existing FinQA train split hash mismatch")
    client = session or requests.Session()
    client.trust_env = False
    response = client.get(
        _TRAIN_URL,
        timeout=(10, 180),
        stream=True,
        allow_redirects=False,
    )
    if response.is_redirect:
        raise ValueError("FinQA train download redirected unexpectedly")
    response.raise_for_status()
    temporary = target.with_suffix(".json.part")
    digest = hashlib.sha256()
    byte_count = 0
    try:
        with temporary.open("xb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                byte_count += len(chunk)
                if byte_count > 128 * 1024 * 1024:
                    raise ValueError("FinQA train split exceeds byte budget")
                digest.update(chunk)
                handle.write(chunk)
        actual = digest.hexdigest()
        if actual != FINQA_TRAIN_SHA256:
            raise ValueError("FinQA train split hash mismatch")
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target, actual, byte_count


class FinQAStructuralDemoIndex:
    def __init__(
        self,
        cases: Sequence[FinQADemoSource],
        *,
        forbidden_case_ids: set[str],
    ) -> None:
        case_ids = [case.case_id for case in cases]
        if (
            not cases
            or len(case_ids) != len(set(case_ids))
            or set(case_ids).intersection(forbidden_case_ids)
        ):
            raise ValueError("dynamic demo source isolation failed")
        indexed: list[_IndexedDemo] = []
        for case in cases:
            skeleton = _build_value_free_skeleton(case)
            tokens = _tokens(case.question)
            if skeleton is None or not tokens:
                continue
            identity = hashlib.sha256(
                (
                    case.case_id
                    + "\n"
                    + case.question
                    + "\n"
                    + case.program
                ).encode("utf-8")
            ).hexdigest()
            indexed.append(
                _IndexedDemo(
                    case_id=case.case_id,
                    identity_sha256=identity,
                    tokens=tokens,
                    payload=FinQAStructuralDemo(
                        question_template=_question_template(
                            case.question
                        ),
                        skeleton=skeleton,
                    ),
                )
            )
        if len(indexed) < 100:
            raise ValueError("dynamic demo index is unexpectedly small")
        document_frequency: Counter[str] = Counter()
        for item in indexed:
            document_frequency.update(item.tokens)
        count = len(indexed)
        self._idf = {
            token: math.log((count + 1) / (frequency + 1)) + 1
            for token, frequency in document_frequency.items()
        }
        self._items = tuple(indexed)
        self.version = DEMO_RETRIEVER_VERSION
        self.identity_sha256 = hashlib.sha256(
            "\n".join(
                item.identity_sha256
                for item in sorted(
                    self._items,
                    key=lambda value: value.identity_sha256,
                )
            ).encode("ascii")
        ).hexdigest()

    @property
    def demo_count(self) -> int:
        return len(self._items)

    def retrieve(
        self,
        question: str,
        *,
        top_k: int = 3,
    ) -> tuple[FinQAStructuralDemo, ...]:
        if not 1 <= top_k <= 3:
            raise ValueError("dynamic demo top_k must be between 1 and 3")
        query_tokens = _tokens(question)
        if not query_tokens:
            raise ValueError("dynamic demo query has no usable tokens")
        scored = []
        for item in self._items:
            overlap = query_tokens.intersection(item.tokens)
            if not overlap:
                continue
            score = sum(self._idf.get(token, 1.0) for token in overlap)
            score /= math.sqrt(len(query_tokens) * len(item.tokens))
            scored.append(
                (score, item.identity_sha256, item.payload)
            )
        scored.sort(key=lambda item: (-item[0], item[1]))
        if len(scored) < top_k:
            raise ValueError("dynamic demo retrieval returned too few rows")
        return tuple(item[2] for item in scored[:top_k])


__all__ = [
    "DEMO_RETRIEVER_VERSION",
    "FINQA_TRAIN_SHA256",
    "FinQADemoSource",
    "FinQAStructuralDemo",
    "FinQAStructuralDemoIndex",
    "demonstration_payload_sha256",
    "download_finqa_train_for_demos",
    "load_finqa_demo_sources",
]
