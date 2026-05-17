import time
from urllib.parse import urlparse

import requests

from app.config import get_settings
from app.retriever import hybrid_search


def _ollama_api_base_url(llm_base_url: str) -> str:
    parsed = urlparse(llm_base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _chat_with_ollama(model: str, messages: list[dict]) -> str:
    settings = get_settings()
    url = f"{_ollama_api_base_url(settings.llm_base_url)}/api/chat"
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                url,
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": 0},
                },
                timeout=180,
            )
            response.raise_for_status()
            data = response.json()
            return data["message"]["content"]
        except Exception as exc:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)

            if status_code == 503 and attempt < max_attempts:
                time.sleep(attempt * 2)
                continue

            detail = ""
            if response is not None:
                detail = f" Ollama response: {response.text[:500]}"

            raise RuntimeError(
                f"Chat request failed at {url} for model {model!r}: {exc}.{detail}"
            ) from exc


def classify_question_type(question: str) -> str:
    q = question.strip()

    list_keywords = [
        "哪些",
        "什么情况下",
        "哪些情况",
        "什么原因",
        "因为什么",
        "哪些资料",
        "需要哪些",
        "包括哪些",
        "包含哪些",
        "有哪些",
        "列出",
        "列举",
    ]
    comparison_keywords = ["分别", "对比", "区别"]
    process_keywords = ["怎么", "如何", "怎么办", "流程", "处理"]
    yes_no_keywords = ["能不能", "能否", "是否可以", "是否能", "可不可以"]
    yes_no_question_keywords = ["可以", "能", "支持"]

    if any(k in q for k in list_keywords):
        return "list_or_constraint"
    if any(k in q for k in comparison_keywords):
        return "comparison"
    if any(k in q for k in yes_no_keywords) or (
        "吗" in q and any(k in q for k in yes_no_question_keywords)
    ):
        return "yes_no_constraint"
    if any(k in q for k in process_keywords):
        return "process"
    return "fact"


def answer_question(question: str, top_k: int | None = None) -> dict:
    settings = get_settings()

    retrieved = hybrid_search(question=question, top_k=top_k)

    if not retrieved:
        return {
            "answer": "我没有检索到可用的知识库内容，请先导入文档。",
            "sources": [],
        }

    context_blocks = []
    for i, item in enumerate(retrieved, start=1):
        context_blocks.append(
            f"[{i}] 来源: {item['source']} | 小节: {item['section']}\n{item['text']}"
        )

    context_text = "\n\n".join(context_blocks)

    question_type = classify_question_type(question)

    system_prompt = (
        "你是企业知识库助手。\n"
        "你必须严格依据给定的知识库上下文回答，不能补充上下文中没有明确写出的事实。\n"
        "禁止把不同片段里的时间、条件或流程自行拼接成新的结论。\n"
        "先检查上下文是否有直接匹配、同义匹配、否定规则或条件句；只有完全没有相关句子时，才说明“知识库未明确说明”。\n"
        "如果上下文写着“不支持”“不能”“请联系”“请先”等明确规则，必须抽取该规则，不要把它误判为未说明。\n"
        "回答时要尽量简洁、准确、可追溯。"
    )

    if question_type == "list_or_constraint":
        user_prompt = f"""用户问题：
{question}

知识库上下文：
{context_text}

请严格执行下面要求：

1. 这是一道“列举/条件”题。
2. 你必须从知识库上下文中逐条抽取明确出现的条件或项目。
3. 如果上下文里已经写出了条件或列表，禁止回答“知识库未明确说明”。
4. 不要总结成模糊的话，不要省略要点。
5. 只输出下面格式：

简短答案：
- 条目1
- 条目2

依据说明：
引用对应编号，例如 [1]

如果只有在上下文完全没有相关信息时，才允许输出：
未说明部分：知识库未明确说明
"""
    elif question_type == "comparison":
        user_prompt = f"""用户问题：
{question}

知识库上下文：
{context_text}

请严格执行下面要求：

1. 这是一道“比较/分别说明”题。
2. 你必须把每一项分别回答清楚。
3. 不要漏掉任一项。
4. 不要写“知识库未明确说明”，除非上下文里真的没有相关信息。
5. 使用用户问题中的项目名称作为标签，不要只写 A/B 这种无法独立理解的标签。
6. 只输出下面格式：

简短答案：
- 项目名称1：...
- 项目名称2：...

依据说明：
引用对应编号，例如 [1]、[2]
"""
    elif question_type == "yes_no_constraint":
        user_prompt = f"""用户问题：
{question}

知识库上下文：
{context_text}

请严格执行下面要求：

1. 这是一道“是否允许/能否/可以吗”题。
2. 你必须先判断上下文里是否有与问题条件匹配的规则。
3. 如果上下文写着“不支持”“不能”“不可以”等否定规则，必须回答“不可以/不能”，并复述对应规则。
4. 如果问题包含具体限制条件，优先使用匹配该条件的限制性片段，不要被更宽泛的规则干扰。
5. 如果上下文写着“可以”“可”“支持”等肯定规则，必须回答“可以/能”，并复述对应规则。
6. 只有上下文完全没有相关规则时，才允许输出“未说明部分：知识库未明确说明”。
7. 只输出下面格式：

简短答案：
不可以/可以，原因或规则是...

依据说明：
引用对应编号，例如 [1]
"""
    elif question_type == "process":
        user_prompt = f"""用户问题：
{question}

知识库上下文：
{context_text}

请严格执行下面要求：

1. 这是一道“处理/流程/怎么办”题。
2. 你必须从知识库上下文中抽取与问题条件匹配的处理动作。
3. 如果上下文有“如果...请...”“请先...”“需要...”这类句子，直接提取对应动作。
4. 如果问题包含错误码、对象或场景，优先匹配包含这些条件的句子。
5. 不要因为上下文没有完整多步流程就回答“知识库未明确说明”；只要有明确下一步或处理动作，就必须回答。
6. 不要添加“先”“然后”等顺序词，除非匹配到的处理动作本身明确写了这些词。
7. 只输出下面格式：

简短答案：
用一句完整自然的话回答应该怎么处理。

依据说明：
引用对应编号，例如 [1]

如果上下文完全没有相关处理动作，才输出：
未说明部分：知识库未明确说明
"""
    else:
        user_prompt = f"""用户问题：
{question}

知识库上下文：
{context_text}

请严格执行下面要求：

1. 这是一道普通事实题。
2. 你必须从知识库上下文中抽取能直接回答问题的句子。
3. 如果上下文里已经明确写出时间、数量、对象或结论，必须直接回答，禁止输出“知识库未明确说明”。
4. 只输出下面格式：

简短答案：
用一句完整自然的话回答，只说知识库中明确支持的结论。

依据说明：
引用最相关的上下文编号，例如 [1]、[2]。

如果上下文里完全没有相关信息，才输出：
未说明部分：知识库未明确说明

注意：
- 不要把多个时间直接相加。
- 不要写“可能”“推断”“大概”。
- 不要补充上下文里没有明确出现的规则。
- 简短答案必须是完整句子，不要只写短语。
"""

    answer = _chat_with_ollama(
        model=settings.chat_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    sources = [
        {
            "source": item["source"],
            "section": item["section"],
            "chunk_id": item["chunk_id"],
            "preview": item["text"][:120],
        }
        for item in retrieved
    ]

    return {
        "answer": answer,
        "sources": sources,
    }
