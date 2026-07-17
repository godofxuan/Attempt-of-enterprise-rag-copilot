# E6 Demo and Public Repository Closure Design

最后更新：2026-07-17

状态：approved by exact stage command `批准E5，执行E6演示与公开仓库收口`

审计 run root：`20260716T192459Z_7aec4b9_e6`

## 1. 目标

让招聘者从 README 和三页 Streamlit 工作台看懂：业务问题、身份/权限、Agent 动作、证据覆盖、claim citation、评估结果、负载代价和已知边界。UI 必须消费真实 API 或由不可覆盖 E4/E5 artifacts 导出的公开快照，不允许硬编码一个虚构成功答案。

## 2. 已批准范围与 Git 边界

本设计细化总体计划 `enterprise_agentic_rag_v2_plan.md#7-e6演示文档和招聘材料`，精确阶段命令视为对该范围的批准。允许修改 UI、公开文档、公开小型快照、测试和 ignored 私人面试材料。

以下操作仍未授权：commit、push、merge、tag、默认分支切换、仓库重命名、force-push。E6 的“公开仓库收口”表示当前工作树达到可审查状态，不表示已经发布到 GitHub 默认分支。

## 3. 方案比较

### A. UI 直接读取 `eval_runs/` 和 `load_runs/`，拒绝

优点是代码少。缺点是两个目录被忽略，公开 clone 的 Evaluation 页为空；页面无法证明 README 数字来自哪份 artifact。

### B. Live API + canonical public snapshot，采用

Ask/Trace 使用真实 `/agent/v2/chat`、`/observability/traces/{id}` 和 metrics。Evaluation 使用一个由 E4/E5 artifact 生成的、严格 schema、带 run ID/source hash 的小型 JSON snapshot。生成器默认拒绝覆盖；UI 只读 snapshot。

优点：本机可交互、公开 clone 可展示、数字可追溯、无大 artifact。缺点：snapshot 是阶段性摘要，源 artifacts 仍需本机复核。

### C. 全静态报告 UI，拒绝

截图稳定，但无法演示 request ID、真实 Agent 轨迹和权限上下文，不满足 E6。

## 4. 页面架构

`streamlit_app/ui.py` 使用 `st.navigation` 作为唯一入口：

```text
Ask         streamlit_app/pages/1_Ask.py
Trace       streamlit_app/pages/2_Trace.py
Evaluation  streamlit_app/pages/3_Evaluation.py
```

共享模块：

- `streamlit_app/api_client.py`：typed API client、safe errors、request ID；
- `streamlit_app/demo_cases.py`：从 canonical eval JSON 按 case ID 加载 demo，不复制问题/身份真值；
- `streamlit_app/view_models.py`：把 AnswerResponse/trace/snapshot 转成表格行；
- `streamlit_app/shell.py`：page config、CSS、session state、sidebar readiness；
- `app/evaluation/public_snapshot.py`：公开评测快照 schema 和 exporter；
- `scripts/export_public_demo_snapshot.py`：安全 CLI，读取 E4/E5 artifacts、校验 hash、不可覆盖发布；
- `data/v2/public/demo_snapshot.json`：UI 可提交的小型证据快照。

### 4.1 Ask

- demo case selector + custom question；
- 展示 user ID、tenant、region、groups、top-k；
- 发送真实 `/agent/v2/chat`；
- 展示 answer mode、stop reason、request ID、answer；
- claim/citation 表显示 claim、critical、cited IDs、visible/support verdict；
- sources 显示授权 doc/section/preview；
- feedback 调真实 `/feedback`。

内置 live API cases：单文档、比较、版本冲突、多条件完整性、无答案、权限不足、直接 prompt injection。它们从 `data/v2/eval/*.json` 或 E4 `SECURITY_PROBES` 加载，不保存预设成功结果。

### 4.2 Trace

- 当前 session Agent trace；
- request overview：intent、analysis source、mode、stop reason、request ID；
- evidence summary：required/supported/missing/conflicting counts 和 coverage；
- actions：sequence、tool、status、latency、visible count、context chars、error；
- budget：search/find/open/steps/context；
- HTTP/model spans：从 observability trace endpoint 获取；
- 无 session Agent trace 时只显示指定 request ID 的服务 trace，不伪造 Agent actions。

### 4.3 Evaluation

四个 tab：Quality、Ablation、Runtime、Security。

- Quality：deterministic frozen test 28/28；live dev 23/24；retrieval/answer/agent/security layer metrics；
- Ablation：BM25、dense、hybrid、metadata/temporal、fixed RAG、bounded Agent；
- Runtime：E5 concurrency 1/5/10 p50/p95、RSS、model calls；
- Security：direct injection 0/4、ACL leakage 0；间接 document injection 标记 `NOT RUN`。

每个数字显示 mode/split/sample size/run ID；不把 deterministic perfect result 写成模型准确率。

## 5. Evidence summary API extension

当前 `AnswerResponse.trace` 没有 ledger coverage。E6 新增安全 summary：

```json
"evidence": {
  "required": 2,
  "supported": 2,
  "missing": 0,
  "conflicting": 0,
  "coverage": 1.0,
  "recommended_action": "answer"
}
```

它只含计数、比例和动作，不含 aspect 文本、doc/chunk ID 或正文。unsafe 初始化失败时使用零值；其他终态使用 `state.ledger` 或按当前 evidence 重建 ledger。现有 trace redaction hard gate 必须继续通过。

## 6. Public snapshot contract

快照只含：

- schema/producer/snapshot ID；
- corpus profile、72 source documents、64 active-index chunks、synthetic 声明；
- frozen/live run ID、mode、split、case count、passed/failed、layer rates；
- selected ablation rows及实际 status/reason；
- E5 load rows、model call/RSS delta；
- security direct probes 和 indirect injection `not_run`；
- source artifact relative label、SHA256 和 artifact content hash。

不得包含绝对本机路径、问题、答案、user/tenant/group、source preview、model body 或 secret。Exporter 先验证 E4 manifest 声明的 summary/ablation hash和 E5 manifest hash，再写 staging，默认拒绝已有 target。

## 7. 公开文档

- `README.md`：业务一句话、Mermaid 架构、真实 screenshot、Agentic necessity、结果表、三条命令、synthetic 声明、限制、链接；
- `PROJECT_STATUS.md`：唯一当前状态入口；
- `docs/architecture.md`：数据流/信任边界/运行时；
- `docs/known_limitations.md`：NOT RUN 与 residual risks；
- `docs/demo_runbook.md`：新终端启动、7 个 case、故障恢复、停止进程；
- `docs/industrialization_backlog.md`：R2 admission gates；
- `docs/AGENTIC_RAG_EVOLUTION_LOG.md`：增加历史 banner，不再声明当前状态；
- `docs/assets/README.md` 与实际 UI PNG。

## 8. 私人材料

使用 `.private/e6/`，并在 `.gitignore` 忽略整个 `.private/`：

```text
interview_script_30s.md
interview_script_1min.md
interview_script_3min.md
interview_qa.md
claims_evidence_matrix.md
learning_cards.md
```

claims matrix 每条都包含 wording、source artifact、metric path/hash、边界和 `candidate/approved/rejected`。E6 只生成候选，E7 才最终批准简历主张。

## 9. 视觉设计

定位是安静、紧凑、可扫描的内部知识工作台：白色/浅灰背景，深墨文本，青绿色用于 healthy/evidence，珊瑚色用于 warning/failure。无渐变、无装饰 orb、无营销 hero、无嵌套卡片。

桌面 1440px：主内容约 1180px；关键 metrics 一行；actions/evaluation 用表格和简洁条形图。移动 390px：列自动堆叠，表格允许横向滚动，按钮与文本不得重叠。按钮使用 Streamlit Material icon 参数。

## 10. Public repository audit

新增只读审计：

- candidate files = tracked + untracked nonignored；
- `.env`、`.private/`、indexes、logs、large generated corpora 不得进入 candidate；
- 拒绝 private key、真实形态 API token、非 example.invalid 邮箱、超过 2 MiB 文件；
- README/PROJECT_STATUS/public snapshot 不得包含机器特定用户目录、当前机器路径或 ignored artifact path 作为启动依赖；
- Markdown 本地链接必须存在；
- screenshot 路径和 snapshot schema 必须验证。

测试中的 seeded `password=never-show` 是安全回归 fixture，不按真实 secret 报警；scanner 使用高置信 token pattern而不是泛搜单词 `password`。

## 11. 测试与视觉验收

TDD 顺序：

1. ledger summary trace RED/GREEN；
2. public snapshot exporter RED/GREEN；
3. API client/demo/view model RED/GREEN；
4. repository/docs config RED/GREEN；
5. Streamlit AppTest smoke；
6. full pytest；
7. hidden FastAPI + Streamlit；
8. browser desktop/mobile screenshots，检查 overflow/overlap/console；
9. 运行真实 Ask case并截 Ask/Trace，Evaluation 读取 public snapshot；
10. 停止本阶段所有项目进程。

## 12. 已知验收缺口

当前语料没有间接 document injection fixture。E6 不在展示阶段静默改动 E1 corpus/frozen benchmark。UI Security tab 和 limitations 将其标为 `NOT RUN`；直接 injection 仍显示真实 0/4 probes。若要把该项变 PASS，需要新 corpus version、index rebuild 和 E4 regression，不能只改截图。

## 13. 完成边界

E6 可以声明：三页 UI 消费真实 API/public evidence snapshot；README/status/docs与 E4/E5 证据一致；公开候选文件通过本地隐私/大小/链接审计；私人材料 ignored；桌面/移动视觉验证完成。

E6 不可以声明：已 merge/push/tag/改默认分支、间接 document injection 已通过、人工 review 已完成、GitHub Actions 已在远端实际运行或系统生产就绪。

完成后停止，唯一下一阶段命令：`执行E7最终验收`。
