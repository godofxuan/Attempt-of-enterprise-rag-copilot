from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import Protocol

from app.domain.queries import (
    QueryAnalysis,
    QueryFilters,
    QueryIntent,
    UserContext,
)


class QueryAnalysisFallback(Protocol):
    def analyze(
        self,
        question: str,
        user: UserContext,
    ) -> QueryAnalysis | Mapping[str, object]: ...


_RISK_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "prompt_injection",
        re.compile(
            r"(?:忽略|无视).{0,12}(?:系统(?:提示|规则)?|知识库|之前的指令)"
            r"|\bignore\s+(?:all\s+)?(?:previous|system|policy|instructions?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "policy_bypass",
        re.compile(
            r"(?:绕过|规避).{0,12}(?:审批|权限|流程|政策|采购)"
            r"|\bbypass\b.{0,24}\b(?:approval|permission|policy|control)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "credential_exfiltration",
        re.compile(
            r"(?:管理员\s*)?(?:密码|凭证|密钥)"
            r"|\bapi[\s_-]*key\b|\badmin(?:istrator)?\s+password\b"
            r"|\baccess\s+token\b|\bsecret\s+key\b",
            re.IGNORECASE,
        ),
    ),
    (
        "data_exfiltration",
        re.compile(
            r"(?:导出|下载|泄露|发送|发给).{0,24}"
            r"(?:客户数据|薪酬表|生产数据库|源代码)"
            r"|\b(?:export|download|leak|send)\b.{0,32}"
            r"\b(?:customer data|payroll|production database|source code)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "fabrication",
        re.compile(
            r"(?:不要|无需|不必).{0,8}(?:引用|来源)"
            r"|(?:直接编|编造|编一个)"
            r"|\b(?:without|ignore)\s+(?:citations?|sources?)\b"
            r"|\b(?:fabricate|make up)\b",
            re.IGNORECASE,
        ),
    ),
)

_COMPARISON_KEYWORDS = (
    "相比",
    "比较",
    "对比",
    "区别",
    "分别",
    "是不是同一个",
    "是否同一个",
    "一样吗",
    "compare",
    "difference",
    "versus",
    " vs ",
)
_COMPLETENESS_KEYWORDS = (
    "全部",
    "所有",
    "完整",
    "列出",
    "列举",
    "哪些",
    "有哪些",
    "包括哪些",
    "包含哪些",
    "complete list",
    "all required",
)
_PROCESS_KEYWORDS = (
    "如何",
    "怎么",
    "流程",
    "步骤",
    "办理",
    "提交",
    "process",
    "how to",
)
_ALL_VERSION_KEYWORDS = (
    "历次版本",
    "所有版本",
    "全部版本",
    "current and historical",
    "all versions",
)
_HISTORICAL_KEYWORDS = (
    "历史版本",
    "旧版",
    "过去版本",
    "曾经",
    "已废止",
    "historical",
    "retired",
    "previous version",
)
_CURRENT_KEYWORDS = (
    "当前",
    "现行",
    "最新",
    "现在",
    "current",
    "latest",
)
_GENERIC_ENTITIES = {
    "这个",
    "那个",
    "相关政策",
    "政策",
    "相关规则",
    "规则",
    "两者",
    "二者",
    "it",
    "them",
}
_AS_OF_PATTERN = re.compile(
    r"(?:截至|截止|as\s+of)\s*"
    r"(?P<year>\d{4})(?:[-/.]|年)"
    r"(?P<month>\d{1,2})(?:[-/.]|月)"
    r"(?P<day>\d{1,2})日?",
    re.IGNORECASE,
)


class RuleFirstQueryAnalyzer:
    def __init__(self, fallback: QueryAnalysisFallback | None = None) -> None:
        self.fallback = fallback

    def analyze(self, question: str, user: UserContext) -> QueryAnalysis:
        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("question must not be empty")

        risk_flags = _risk_flags(normalized_question)
        if risk_flags:
            return QueryAnalysis(
                original_question=normalized_question,
                intent="unsafe",
                risk_flags=risk_flags,
                source="rules",
            )

        filters, temporal_is_explicit = _temporal_filters(normalized_question)
        quoted_entities = _quoted_entities(normalized_question)
        if _contains_any(normalized_question, _COMPARISON_KEYWORDS):
            entities = _comparison_entities(normalized_question, quoted_entities)
            if len(entities) >= 2:
                return _rules_analysis(
                    question=normalized_question,
                    intent="comparison",
                    entities=entities,
                    search_queries=entities,
                    required_aspects=entities,
                    filters=filters,
                )

            deterministic = _rules_analysis(
                question=normalized_question,
                intent="fact",
                entities=entities,
                search_queries=[normalized_question],
                required_aspects=["answer"],
                filters=filters,
            )
            if self.fallback is not None:
                return self._validated_fallback(
                    question=normalized_question,
                    user=user,
                    deterministic=deterministic,
                    rule_entities=entities,
                    temporal_is_explicit=temporal_is_explicit,
                )
            return deterministic

        if _contains_any(normalized_question, _COMPLETENESS_KEYWORDS):
            intent: QueryIntent = "completeness"
            required_aspects = ["complete_policy_coverage"]
        elif _contains_any(normalized_question, _PROCESS_KEYWORDS):
            intent = "process"
            required_aspects = ["process_steps"]
        else:
            intent = "fact"
            required_aspects = ["answer"]
        return _rules_analysis(
            question=normalized_question,
            intent=intent,
            entities=quoted_entities,
            search_queries=[normalized_question],
            required_aspects=required_aspects,
            filters=filters,
        )

    def _validated_fallback(
        self,
        *,
        question: str,
        user: UserContext,
        deterministic: QueryAnalysis,
        rule_entities: list[str],
        temporal_is_explicit: bool,
    ) -> QueryAnalysis:
        try:
            candidate = QueryAnalysis.model_validate(
                self.fallback.analyze(question, user)
            )
            if candidate.original_question != question:
                return deterministic
            if candidate.intent == "unsafe":
                return candidate.model_copy(update={"source": "rules+model"})

            entities = _unique([*rule_entities, *candidate.entities], limit=8)
            if candidate.intent == "comparison":
                if len(entities) < 2:
                    return deterministic
                search_queries = _comparison_queries(
                    entities,
                    candidate.search_queries,
                )
                required_aspects = _unique(
                    [*entities, *candidate.required_aspects],
                    limit=8,
                )
            else:
                search_queries = candidate.search_queries
                required_aspects = candidate.required_aspects

            filters = candidate.filters
            if temporal_is_explicit:
                payload = candidate.filters.model_dump()
                payload.update(
                    temporal_scope=deterministic.filters.temporal_scope,
                    as_of=deterministic.filters.as_of,
                )
                filters = QueryFilters.model_validate(payload)
            return QueryAnalysis(
                original_question=question,
                intent=candidate.intent,
                entities=entities,
                search_queries=search_queries,
                required_aspects=required_aspects,
                filters=filters,
                risk_flags=_unique(
                    [*deterministic.risk_flags, *candidate.risk_flags],
                    limit=20,
                ),
                source="rules+model",
            )
        except Exception:
            return deterministic


def _rules_analysis(
    *,
    question: str,
    intent: QueryIntent,
    entities: list[str],
    search_queries: list[str],
    required_aspects: list[str],
    filters: QueryFilters,
) -> QueryAnalysis:
    return QueryAnalysis(
        original_question=question,
        intent=intent,
        entities=entities,
        search_queries=search_queries,
        required_aspects=required_aspects,
        filters=filters,
        source="rules",
    )


def _risk_flags(question: str) -> list[str]:
    return [name for name, pattern in _RISK_RULES if pattern.search(question)]


def _compact(text: str) -> str:
    return "".join(text.casefold().split())


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    compact = _compact(text)
    return any(_compact(keyword) in compact for keyword in keywords)


def _quoted_entities(question: str) -> list[str]:
    entities: list[str] = []
    for pattern in (r"《([^》]{1,80})》", r"[“\"]([^”\"]{1,80})[”\"]"):
        entities.extend(match.strip() for match in re.findall(pattern, question))
    return _unique(
        [entity for entity in entities if _useful_entity(entity)],
        limit=8,
    )


def _comparison_entities(question: str, quoted: list[str]) -> list[str]:
    if len(quoted) >= 2:
        return quoted

    patterns = (
        re.compile(
            r"(?P<left>[^，。！？?]{1,40}?)[和与及、]"
            r"(?P<right>[^，。！？?]{1,40}?)"
            r"(?:是不是同一个|是否同一个|(?:有何|的)?区别|一样吗|相比|对比)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:比较|对比)\s*(?P<left>[^，。！？?]{1,40}?)"
            r"[和与及、](?P<right>[^，。！？?]{1,40})",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:compare\s+)?(?P<left>[\w -]{2,40}?)\s+"
            r"(?:and|vs\.?|versus)\s+(?P<right>[\w -]{2,40})",
            re.IGNORECASE,
        ),
    )
    extracted = list(quoted)
    for pattern in patterns:
        match = pattern.search(question)
        if match is None:
            continue
        extracted.extend(
            [_clean_entity(match.group("left")), _clean_entity(match.group("right"))]
        )
        break
    return _unique(
        [entity for entity in extracted if _useful_entity(entity)],
        limit=8,
    )


def _clean_entity(value: str) -> str:
    cleaned = value.strip(" \t\r\n，。！？?：:；;、的")
    cleaned = re.sub(
        r"^(?:请问|请帮我|帮我|请(?:比较|对比|说明|分析))",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip(" \t\r\n，。！？?：:；;、的")


def _useful_entity(entity: str) -> bool:
    normalized = entity.strip().casefold()
    return len(normalized) >= 2 and normalized not in _GENERIC_ENTITIES


def _temporal_filters(question: str) -> tuple[QueryFilters, bool]:
    match = _AS_OF_PATTERN.search(question)
    if match is not None:
        try:
            as_of = date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
        except ValueError:
            pass
        else:
            return QueryFilters(temporal_scope="as_of", as_of=as_of), True
    if _contains_any(question, _ALL_VERSION_KEYWORDS):
        return QueryFilters(temporal_scope="all"), True
    if _contains_any(question, _HISTORICAL_KEYWORDS):
        return QueryFilters(temporal_scope="historical"), True
    if _contains_any(question, _CURRENT_KEYWORDS):
        return QueryFilters(temporal_scope="current"), True
    return QueryFilters(), False


def _comparison_queries(
    entities: list[str],
    candidate_queries: list[str],
) -> list[str]:
    queries: list[str] = []
    for entity in entities[:4]:
        matching = next(
            (
                query
                for query in candidate_queries
                if entity.casefold() in query.casefold()
            ),
            entity,
        )
        queries.append(matching)
    return _unique(queries, limit=4)


def _unique(values: list[str], *, limit: int) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
        if len(result) == limit:
            break
    return result


__all__ = ["QueryAnalysisFallback", "RuleFirstQueryAnalyzer"]
