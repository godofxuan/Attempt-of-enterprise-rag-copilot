# R19 简历实际交付核验

2026-09-10，简历维护任务已完成正式 R19，并更新 `LOCAL_PATH_REDACTED`。
本任务随后读取实际 Markdown、PDF、指针和 QA 文件，独立检查四份 PDF 摘要、单页、照片、三个 GitHub 链接、项目日期、联系方式与最小字号，并目视检查 AI 版 180 dpi 渲染。

正式目录：`LOCAL_PATH_REDACTED`

主要更新文件：`01-陆暄-AI应用-RAG-Agent.pdf`，同名 Markdown 可编辑源。
PDF SHA-256：`8b871609e5390b8625e99061cd18b08315566bdeb104d9bb2bf7724ebe2c3721`。

实际变更：

- 保留 WixQA Recall@5 65.92%→74.25%、nDCG@5 52.08%→59.93% 及 Top50/Top20 的区别。
- 默认问答编排明确为 Python 控制器，LangGraph 用于真实可恢复审批实现。
- 将原查询理解条目替换为回答可靠性，写入固定 40 题、双配置三轮本地鉴权 FastAPI 与真实 LLM 自动回归的有限用例通过率 70.8%→80.4%。
- 不写成线上准确率、240 个独立问题或所有场景提升。
- EvalOps 内容不变；02、03、04 三版 Markdown 与 R18 相同。

核验状态：`ACTUAL_R19_RELEASE_VERIFIED`。
原 R18 AI PDF 摘要保持不变，历史已投附件未覆盖。
复核记录：`LOCAL_PATH_REDACTED`。

项目业务代码、GitHub main、部署与索引在本轮没有更改。“简历正式版”不等于“软件生产发布”。
上线判断、分场景退化及原始证据说明见同目录 `REPORT.md`。
