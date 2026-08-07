from __future__ import annotations

import ast
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


GARAK_REVISION = "afae291b684ae64055d53a0ea4228f7e760392ba"
GARAK_PROBE_SHA256 = "b3adec0de41b34cc0f4bcc783d035fd2cd85d9afc9e5a9d9bb1164bd33cabfad"
GARAK_PAYLOAD_SHA256 = "921a2034153eee00969c2e3add201709d4e6083968921f230b56390d92ec5c7b"
GARAK_LICENSE_SHA256 = "b2c6b7794a4b137b5e5e4fe9efb9771f35b6f466d0ea6704bedc649a0cd0f7f0"
_REQUIRED_FIELDS = (
    "top_instructions",
    "contexts",
    "injection_sep_pairs",
    "injection_instructions",
    "payloads",
)


class GarakFixtureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GarakLatentReportSource(GarakFixtureModel):
    repository: Literal["https://github.com/NVIDIA/garak"] = (
        "https://github.com/NVIDIA/garak"
    )
    revision: Literal["afae291b684ae64055d53a0ea4228f7e760392ba"] = (
        GARAK_REVISION
    )
    probe_class: Literal["latentinjection.LatentInjectionReport"] = (
        "latentinjection.LatentInjectionReport"
    )
    probe_sha256: Literal[
        "b3adec0de41b34cc0f4bcc783d035fd2cd85d9afc9e5a9d9bb1164bd33cabfad"
    ] = GARAK_PROBE_SHA256
    payload_sha256: Literal[
        "921a2034153eee00969c2e3add201709d4e6083968921f230b56390d92ec5c7b"
    ] = GARAK_PAYLOAD_SHA256
    license: Literal["Apache-2.0"] = "Apache-2.0"
    license_sha256: Literal[
        "b2c6b7794a4b137b5e5e4fe9efb9771f35b6f466d0ea6704bedc649a0cd0f7f0"
    ] = GARAK_LICENSE_SHA256


class GarakLatentReportCase(GarakFixtureModel):
    case_id: str = Field(pattern=r"^garak-report-(?:attack|benign)-[0-9]{3}$")
    label: Literal["attack", "benign"]
    context_index: int = Field(ge=0)
    injection_instruction_index: int | None = Field(default=None, ge=0)
    payload_index: int | None = Field(default=None, ge=0)
    trigger_index: int | None = Field(default=None, ge=0)
    question: str = Field(min_length=1, max_length=500)
    retrieved_content: str = Field(min_length=1, max_length=100_000)
    expected_utility_terms: list[str] = Field(min_length=1, max_length=5)
    trigger: str | None = None

    @model_validator(mode="after")
    def validate_case(self) -> "GarakLatentReportCase":
        attack_fields = (
            self.injection_instruction_index,
            self.payload_index,
            self.trigger_index,
            self.trigger,
        )
        if self.label == "attack":
            if any(item is None for item in attack_fields):
                raise ValueError("garak attack case requires source indices and trigger")
            assert self.trigger is not None
            if self.trigger.lower() not in self.retrieved_content.lower():
                raise ValueError("garak attack content must contain its trigger")
        elif any(item is not None for item in attack_fields):
            raise ValueError("garak benign case cannot carry attack fields")
        return self


class GarakLatentReportFixture(GarakFixtureModel):
    schema_version: Literal["garak_latent_report_fixture_v1"] = (
        "garak_latent_report_fixture_v1"
    )
    source: GarakLatentReportSource
    selection_protocol: str = Field(min_length=1)
    attack_case_count: int = Field(ge=1)
    benign_case_count: int = Field(ge=1)
    cases: list[GarakLatentReportCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_counts(self) -> "GarakLatentReportFixture":
        attack_count = sum(item.label == "attack" for item in self.cases)
        benign_count = len(self.cases) - attack_count
        if (attack_count, benign_count) != (
            self.attack_case_count,
            self.benign_case_count,
        ):
            raise ValueError("garak fixture case counts do not match cases")
        if len({item.case_id for item in self.cases}) != len(self.cases):
            raise ValueError("garak fixture case IDs must be unique")
        return self


def build_garak_latent_report_fixture(
    *,
    probe_source: bytes,
    payload_source: bytes,
) -> GarakLatentReportFixture:
    if hashlib.sha256(probe_source).hexdigest() != GARAK_PROBE_SHA256:
        raise ValueError("garak latent-injection probe hash mismatch")
    if hashlib.sha256(payload_source).hexdigest() != GARAK_PAYLOAD_SHA256:
        raise ValueError("garak latent-injection payload hash mismatch")
    assignments = extract_class_assignments(
        probe_source.decode("utf-8"),
        class_name="LatentInjectionReportFull",
    )
    payload_document = json.loads(payload_source)
    triggers = payload_document["payloads"]
    if not isinstance(triggers, list) or len(triggers) < 1:
        raise ValueError("garak payload source has no triggers")

    marker = "<|garak_injection|>"
    payload_marker = "<|garak_payload|>"
    trigger_marker = "<|garak_trigger|>"
    contexts = assignments["contexts"]
    instructions = assignments["injection_instructions"]
    payloads = assignments["payloads"]
    separators = assignments["injection_sep_pairs"]
    top_instructions = assignments["top_instructions"]
    if len(contexts) != 4 or len(instructions) != 3 or len(payloads) < 4:
        raise ValueError("garak report source shape changed")
    if separators != [("\n--------\n", "")]:
        raise ValueError("garak report separator contract changed")
    question = str(top_instructions[1]).split("\n", 1)[0].strip()
    expected_terms = {
        0: ["RSU", "grant"],
        1: ["RSU", "stock"],
        2: ["employee", "stock", "purchase"],
        3: ["Hooli", "revenue"],
    }

    cases: list[GarakLatentReportCase] = []
    attack_number = 1
    for context_index in (0, 3):
        context = str(contexts[context_index])
        for instruction_index in range(3):
            for payload_index in (0, 3):
                trigger_index = 0
                trigger = str(triggers[trigger_index])
                payload = str(payloads[payload_index]).replace(
                    trigger_marker,
                    trigger,
                )
                injection = str(instructions[instruction_index]).replace(
                    payload_marker,
                    payload,
                )
                start, end = separators[0]
                retrieved_content = context.replace(
                    marker,
                    f"{start}{injection}{end}",
                )
                cases.append(
                    GarakLatentReportCase(
                        case_id=f"garak-report-attack-{attack_number:03d}",
                        label="attack",
                        context_index=context_index,
                        injection_instruction_index=instruction_index,
                        payload_index=payload_index,
                        trigger_index=trigger_index,
                        question=question,
                        retrieved_content=retrieved_content,
                        expected_utility_terms=expected_terms[context_index],
                        trigger=trigger,
                    )
                )
                attack_number += 1
    for context_index, context in enumerate(contexts, start=1):
        cases.append(
            GarakLatentReportCase(
                case_id=f"garak-report-benign-{context_index:03d}",
                label="benign",
                context_index=context_index - 1,
                question=question,
                retrieved_content=str(context).replace(marker, ""),
                expected_utility_terms=expected_terms[context_index - 1],
            )
        )
    return GarakLatentReportFixture(
        source=GarakLatentReportSource(),
        selection_protocol=(
            "Attacks use report contexts 0 and 3, all three official injection "
            "instructions, official payload indices 0 and 3, and official trigger "
            "index 0. Benign controls remove the injection marker from all four "
            "official report contexts. No prompt text is generated by this project."
        ),
        attack_case_count=12,
        benign_case_count=4,
        cases=cases,
    )


def extract_class_assignments(
    source: str,
    *,
    class_name: str,
) -> dict[str, Any]:
    tree = ast.parse(source)
    environment: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    environment[target.id] = _safe_ast_value(node.value, environment)
                except ValueError:
                    continue
    class_node = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        ),
        None,
    )
    if class_node is None:
        raise ValueError(f"garak source has no {class_name} class")
    values: dict[str, Any] = {}
    scoped = dict(environment)
    for node in class_node.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in _REQUIRED_FIELDS:
            continue
        values[target.id] = _safe_ast_value(node.value, scoped)
        scoped[target.id] = values[target.id]
    if set(values) != set(_REQUIRED_FIELDS):
        raise ValueError("garak report source is missing required assignments")
    return values


def _safe_ast_value(node: ast.AST, environment: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in environment:
        return environment[node.id]
    if isinstance(node, ast.List):
        return [_safe_ast_value(item, environment) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_safe_ast_value(item, environment) for item in node.elts)
    if isinstance(node, ast.JoinedStr):
        return "".join(
            str(_safe_ast_value(item.value, environment))
            if isinstance(item, ast.FormattedValue)
            else str(_safe_ast_value(item, environment))
            for item in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _safe_ast_value(node.left, environment) + _safe_ast_value(
            node.right,
            environment,
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return _safe_ast_value(node.left, environment) * _safe_ast_value(
            node.right,
            environment,
        )
    raise ValueError(f"unsupported garak source expression: {type(node).__name__}")


__all__ = [
    "GARAK_LICENSE_SHA256",
    "GARAK_PAYLOAD_SHA256",
    "GARAK_PROBE_SHA256",
    "GARAK_REVISION",
    "GarakLatentReportCase",
    "GarakLatentReportFixture",
    "build_garak_latent_report_fixture",
    "extract_class_assignments",
]
