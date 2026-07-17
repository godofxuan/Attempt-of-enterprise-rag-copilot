# Enterprise Agentic RAG E7 Final Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对 E0-E6 累计实现执行可复现的最终工程验收，逐项给出 PASS/FAIL/NOT RUN，只批准有可定位证据和明确边界的公开/简历主张，固定 release-candidate commit，推送当前功能分支并从 GitHub 干净克隆复验。

**Architecture:** E7 不增加新的业务能力，而是把验收拆成静态仓库门禁、数据与索引契约、deterministic/CI 等价验证、live 服务与真实浏览器、人工专属事项、claims 审批和 Git 冻结七层。每层的命令、退出码、artifact/hash、结论和边界写入 `docs/roadmap/e7_final_acceptance_implementation.md`；私有长报告和简历措辞保存在 Git-ignored `.private/e7/`，并复制到既定校外审计目录。

**Tech Stack:** PowerShell 7/Windows PowerShell, Python 3.11, pytest, FastAPI/Uvicorn, Streamlit, Ollama, BM25/FAISS/BGE-M3, Git, SHA-256, Markdown.

## Global Constraints

- 所有结果只能来自 E7 本轮新鲜命令或经过 hash 复核的 immutable artifact；E6 数字只能作为 before evidence。
- 每个验收项必须是 `PASS`、`FAIL` 或 `NOT RUN`；失败和未运行不得改写成通过。
- `human_review.csv` 的八个人工列只能由本人填写；Codex 不代填，也不把空白算通过。
- direct injection 的 4 条 probe 不得外推为 indirect retrieved-content injection；后者没有 fixture 时保持 `NOT RUN`。
- 本地 load profile 不得表述为生产 SLO、容量上限、高并发或跨硬件 benchmark。
- synthetic corpus 不得表述为真实企业内部数据；自报 `UserContext` 不得表述为真实 IAM。
- 没有 remote run URL 时，不得声称 GitHub Actions 已远端通过。
- E7 起始授权不包含 push；本人随后明确要求“直接传到 GitHub”，因此允许提交并推送当前 `codex/rag-eval-system`。仍不 merge、tag、改默认分支、仓库名或公开状态。
- `.private/`、`eval_runs/`、`load_runs/`、本机索引和浏览器临时证据必须继续被 Git 忽略。
- 项目服务结束后必须确认 8000/8501 无监听者；不停止用户已有的 Ollama。

---

### Task 1: Freeze Acceptance Inventory

**Files:**
- Create: `docs/roadmap/e7_final_acceptance_implementation.md`
- Modify: `docs/roadmap/CURRENT_EXECUTION_HANDOFF.md`

**Interfaces:**
- Consumes: E7 九类验收顺序、E6 snapshot、E6 implementation journal、ignored raw artifacts。
- Produces: E7 gate IDs、证据字段和本轮唯一执行入口。

- [x] **Step 1: Record the starting Git boundary**

Run:

```powershell
git branch --show-current
git rev-parse HEAD
git status --short --branch
git diff --cached --name-only
```

Expected: branch 为 `codex/rag-eval-system`，staging area 为空，E0-E6 累计改动仍未被误提交。

- [x] **Step 2: Create the E7 journal skeleton**

为九类验收建立 `gate_id / command / exit_code / artifact / sha256 / verdict / boundary` 字段，并记录任何 incident 的现象、根因、修复、回归证据。

- [x] **Step 3: Mark the handoff as E7 in progress**

只更新唯一当前点，不删除 E0-E6 历史证据。

### Task 2: Static Repository, Data, and Index Gates

**Files:**
- Modify: `docs/roadmap/e7_final_acceptance_implementation.md`

**Interfaces:**
- Consumes: public candidate audit、frozen eval、corpus/index manifests、parser/index tests。
- Produces: E7-G01 到 E7-G03 的 PASS/FAIL/NOT RUN 证据。

- [x] **Step 1: Run Git/privacy/public audit**

Run:

```powershell
.\.venv\Scripts\python.exe -m scripts.audit_public_repo
git check-ignore -v .private\e6\claims_evidence_matrix.md eval_runs load_runs data\indexes_v2
git diff --check
```

Expected: audit 0 findings；私有/raw/runtime path 均有 ignore rule；diff check exit 0。

- [x] **Step 2: Verify frozen facts and immutable artifacts**

Run frozen hash、corpus/fact consistency tests、raw eval/load manifest artifact hash checks和 public snapshot schema/source hash checks。任何 hash mismatch 都是 FAIL，不得重写原 artifact 规避失败。

- [x] **Step 3: Verify parser/index lifecycle and side-effect-free help**

在运行 `python -m scripts.build_indexes_v2 --help` 前后记录 `data/indexes_v2` 文件列表、长度、mtime 和 SHA-256；两份 inventory 必须相同。随后运行 `tests/ingestion`、`tests/indexing`、`tests/corpus`。

- [x] **Step 4: Load the active index contract**

Run:

```powershell
.\.venv\Scripts\python.exe -c "from app.config import get_settings; from app.retrieval.snapshot import V2IndexSnapshot; s=V2IndexSnapshot.load(get_settings().v2_indexes_dir); print(s.version.manifest.run_id, len(s.chunks), s.version.manifest.embedding.model, s.version.manifest.embedding.dimension)"
```

Expected: active run、chunk count、model 和 dimension 与公开可复现文档一致。

### Task 3: Deterministic Evaluation and CI-Equivalent Gates

**Files:**
- Create (ignored): `eval_runs/20260717_e7_test_suite_rc01/`
- Create (ignored): `eval_runs/20260717_e7_test_ablation_rc01/`
- Create (ignored, post-review authority): `eval_runs/20260717_e7_test_suite_rc02/`
- Create (ignored, post-review authority): `eval_runs/20260717_e7_test_ablation_rc02/`
- Modify: `docs/roadmap/e7_final_acceptance_implementation.md`

**Interfaces:**
- Consumes: frozen test、deterministic runtime、retrieval/response/agent/security evaluator。
- Produces: 新鲜 28-case quality run、baseline-vs-v2 ablation、CI 等价 gate 和 full-suite result。

- [x] **Step 1: Publish a fresh deterministic frozen-test run**

Run:

```powershell
.\.venv\Scripts\python.exe -m scripts.eval_enterprise_v2 --suite all --split test --mode deterministic --run-id 20260717_e7_test_suite_rc01
```

Expected: immutable run 发布成功；summary、details、failures 和 metrics 均被 manifest hash 覆盖。

- [x] **Step 2: Publish a fresh deterministic test ablation**

Run:

```powershell
.\.venv\Scripts\python.exe -m scripts.eval_ablation_v2_enterprise --split test --mode deterministic --run-id 20260717_e7_test_ablation_rc01
```

Expected: fixed RAG、retrieval variants、bounded Agentic outcome 与 cost 一起保存，不能只报告胜出的数字。

- [x] **Step 3: Run CI-equivalent commands**

Run:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q app scripts streamlit_app tests
.\.venv\Scripts\python.exe -c "from pathlib import Path; from scripts.eval_enterprise_v2 import verify_frozen_test_hash; expected, actual = verify_frozen_test_hash(Path('data/v2/eval')); assert expected == actual; print(actual)"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.audit_public_repo
```

Expected: all exit 0；pytest 报告 0 failures；仅允许已解释的 FAISS SWIG deprecation warnings。

### Task 4: Live Service, Trace, Load, and Browser Gates

**Files:**
- Create (ignored): `load_runs/20260717_e7_demo_load_rc01/`
- Create (ignored): `load_runs/20260717_e7_demo_load_rc02/`
- Create (ignored): `data/eval_outputs/e7_browser_20260717_rc01/`
- Modify: `docs/roadmap/e7_final_acceptance_implementation.md`

**Interfaces:**
- Consumes: Ollama `bge-m3`/`qwen2.5:3b`、active index、FastAPI、Streamlit、canonical demo cases。
- Produces: health/readiness、request correlation、minimal trace、local load 和 desktop/mobile screenshots。

- [x] **Step 1: Prove preconditions and start fresh processes**

确认模型、active index、8000/8501 空闲；用不带 reload 的 uvicorn 和固定 `127.0.0.1` 启动，再启动 Streamlit。只记录本轮创建的 PID。

- [x] **Step 2: Run health and one real Agent request**

要求 `/health/live=200`、`/health/ready=200`，并验证请求发送 ID、响应 header ID、body trace ID 三者一致。回答必须带 visible source；trace 不得泄漏 question、identity、doc ID 或 source preview。

- [x] **Step 3: Publish a small E7 local load profile**

Run `scripts.load_profile --profile demo --concurrency 1,5,10 --requests-per-level 10 --timeout-seconds 30`，保存 31-request cold/warm 证据和 manifest hashes。该结果只代表本机小样本 demo profile。

- [x] **Step 4: Inspect Ask/Trace/Evaluation in a real browser**

桌面使用 1440x1000，移动端使用 390x844。核对真实 Ask 请求、同 request trace、Evaluation snapshot、内部表格滚动、页面无整体横向溢出、图表非空、无错误控制台消息；保存真实 PNG 和 DOM/网络证据。

- [x] **Step 5: Stop only E7-owned processes**

停止记录的 uvicorn/Streamlit PID，确认端口 8000/8501 无监听者、项目 Python 进程为 0，Ollama 保留。

### Task 5: Human Boundary and Independent Review

**Files:**
- Create: `.private/e7/human_signoff_checklist.md`
- Modify: `docs/roadmap/e7_final_acceptance_implementation.md`

**Interfaces:**
- Consumes: 50-row blank `human_review.csv`、项目代码、公共文档和 candidate claims。
- Produces: 机器可证结论、Codex 只读语义审查意见、本人专属 NOT RUN 清单和独立 reviewer findings。

- [x] **Step 1: Verify the human-review sheet remains blank**

程序化检查 50 行和八个人工列全部为空；结论只能是 `NOT RUN (awaiting owner judgement)`，不能是 PASS。

- [x] **Step 2: Run an independent read-only final review**

 reviewer 检查 E7 spec compliance、代码/测试缺陷、文档数字漂移、privacy/public boundary 和 claims 外推。逐条在当前代码库验证；Critical/Important 必须修复并回归，错误建议要以代码/测试反证。

- [x] **Step 3: Create the owner-only checklist**

列出 30-50 例人工语义评分、三个本人代码实验、30 秒/1 分钟/3 分钟口述和追问压力测试的明确完成标准；Codex 不代签。

### Task 6: Claims Approval and Documentation Closure

**Files:**
- Modify: `.private/e6/claims_evidence_matrix.md`
- Create: `.private/e7/Enterprise_Agentic_RAG_v2_最终验收.md`
- Create: `.private/e7/resume_claims.md`
- Create: `.private/e7/e7_beginner_learning_and_interview.md`
- Modify: `README.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `docs/reproducibility.md`
- Modify: `docs/known_limitations.md`
- Modify: `docs/roadmap/CURRENT_EXECUTION_HANDOFF.md`
- Modify: `docs/roadmap/engineering_decision_failure_ledger.md`

**Interfaces:**
- Consumes: E7 fresh gates、validated immutable artifacts、independent review、human-only NOT RUN state。
- Produces: approved/narrowed/rejected matrix、最终可说/不可说边界、公开状态与详细教学档案。

- [x] **Step 1: Decide every candidate claim**

每条使用 `approved`、`narrowed` 或 `rejected`；数字 claim 必须保留 dataset/mode/n/local 边界，且引用实际 artifact/hash。`pending_e7` 不得残留。

- [x] **Step 2: Write the private final report and teaching guide**

逐 gate 解释做了什么、代码/文件在哪里、为什么这样验收、遇到的问题、如何定位和修复、结果为何好/不好、面试如何回答。单独列出人工未签项，不能埋在通过项中。

- [x] **Step 3: Update public truth sources**

README、root `PROJECT_STATUS.md`、reproducibility、known limitations、handoff 和总台账使用同一批 E7 数字；历史文档不伪装成当前状态。

- [ ] **Step 4: Copy the private report to the approved external audit path**

将最终报告复制为：

```text
<private-external-audit-path>/Enterprise_Agentic_RAG_v2_最终验收.md
```

复制后比较 SHA-256；该外部文件不进入 Git。

### Task 7: Final Reverification, Push, and Clean-Clone Proof

**Files:**
- Modify: `docs/roadmap/e7_final_acceptance_implementation.md`

**Interfaces:**
- Consumes: 所有 E7 改动和证据。
- Produces: 最终 gate table、固定并推送的 release-candidate commit、GitHub 干净克隆复验证据。

- [x] **Step 1: Re-run the complete final gate after all edits**

再次执行 `pip check`、`compileall`、frozen hash、full pytest、public audit、`git diff --check`、文档链接和 process/port checks。任何失败都重新打开相关 gate。

- [x] **Step 2: Review the exact public candidate set**

确认 `.private/e7`、raw runs、browser scratch 和 active index 均不在 `git status --short` candidate 中；检查将提交的文件列表和大文件。

- [ ] **Step 3: Create the release-candidate commit**

只在所有可自动执行 gate 为 PASS、所有人工专属项明确为 NOT RUN 后，将公开候选提交到当前 `codex/rag-eval-system`。

- [ ] **Step 4: Push the current feature branch**

推送 `codex/rag-eval-system` 到 `origin`，核对 remote branch SHA 与本地 commit 一致。不 merge、tag、切换默认分支或修改仓库可见性。

- [ ] **Step 5: Verify a clean GitHub clone**

从 `origin/codex/rag-eval-system` 克隆到新的临时目录，核对 clone HEAD、private/raw path 不存在、public audit、compile、frozen hash 和 full pytest。该步骤证明公开 clone 可复现，不代表 remote CI 已运行。

- [ ] **Step 6: Verify the committed candidate**

记录 commit SHA、tree 状态、branch/upstream、remote default、最终 public audit、clean-clone 结果和项目进程状态。若文档写入 commit SHA 造成自引用悖论，公开报告使用 Git commit 本身作为 authority，不把 SHA 写回同一个 commit 的被跟踪正文。
