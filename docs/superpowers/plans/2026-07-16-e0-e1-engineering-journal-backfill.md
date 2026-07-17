# E0/E1 Engineering Journal Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把已经完成的 E0/E1 重写为初学者可读、证据可追溯的三层工程记录，并建立 E2 开始后实时更新的统一模板。

**Architecture:** 仓库内阶段文档负责完整技术因果链，跨阶段总账只做稳定 ID 索引，私人目录保存本机审计和学习任务。历史内容按照 `[OBSERVED]`、`[REPRODUCED]`、`[INFERRED]`、`[RETROACTIVE]`、`[NOT_CAPTURED]` 区分，不伪造已经丢失的原始 RED 输出。

**Tech Stack:** Markdown、PowerShell、Git、pytest、Python 3.11、现有 Pydantic v2 corpus 模块。

## Global Constraints

- 不修改 E1 已冻结的 `data/v2/eval/test.json` 或其 SHA256。
- 不修改 parser、chunker、retriever、index 或 Agent 运行时代码；这些属于后续 E2/E3。
- 公开文档不得包含私人绝对路径、用户名、Token、模型目录或求职材料内容。
- 私有学习卡保持“未验收，不得标记为已掌握”。
- 无法从现存证据恢复的历史输出使用 `[NOT_CAPTURED]`，不得补造日志。
- 未经本人确认不执行 `git add`、commit、push、merge、tag 或 remote 修改。
- 本计划完成后，按本人已经给出的 `批准E1，执行E2解析与索引生命周期` 进入 E2。

---

### Task 1: Freeze the Backfill Evidence Inventory

**Files:**
- Read: `docs/roadmap/enterprise_agentic_rag_v2_design.md`
- Read: `docs/roadmap/enterprise_agentic_rag_v2_plan.md`
- Read: `docs/roadmap/current_to_v2_gap_matrix.md`
- Read: `docs/roadmap/e1_enterprise_corpus_implementation.md`
- Read: `app/corpus/*.py`
- Read: `tests/corpus/*.py`
- Read: `data/v2/**/*`
- Read: private E1 audit and learning card

**Interfaces:**
- Consumes: 当前 branch、HEAD、status、E0/E1 文件、测试和 hash。
- Produces: 可用于回填的证据清单，以及明确缺失的历史证据清单。

- [ ] **Step 1: Capture repository state**

Run:

```powershell
git status --short --branch
git log -8 --oneline --decorate
git diff --check
```

Expected: branch 为 `codex/rag-eval-system`，HEAD 为 `7aec4b9...`，只出现已知 E0/E1 未提交修改。

- [ ] **Step 2: Reproduce E1 focused and full tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\corpus -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Expected: `39 passed`；全仓库 `148 passed, 5 warnings`。

- [ ] **Step 3: Reproduce deterministic profile summaries and frozen hash**

Run:

```powershell
.\.venv\Scripts\python.exe -m scripts.generate_enterprise_corpus --profile demo --dry-run
.\.venv\Scripts\python.exe -m scripts.generate_enterprise_corpus --profile benchmark --dry-run
Get-FileHash data\v2\eval\test.json -Algorithm SHA256
```

Expected: demo 72、benchmark 600、test hash 为 `556FFED...43338`。

- [ ] **Step 4: Classify historical evidence gaps**

Record these facts without reconstruction:

```text
Exact first RED console output for early missing modules: [NOT_CAPTURED]
Current tests and checked-in artifacts: [OBSERVED]
Commands rerun during backfill: [REPRODUCED]
Historical rationale reconstructed from code and existing records: [RETROACTIVE]
Windows transient-lock root cause: [INFERRED], bounded by repeated experiments
```

### Task 2: Create the Cross-Stage Decision and Failure Ledger

**Files:**
- Create: `docs/roadmap/engineering_decision_failure_ledger.md`

**Interfaces:**
- Consumes: stable IDs and evidence levels from the approved journal design.
- Produces: one searchable index linking E0/E1 decisions, incidents, experiments and limitations to detailed phase records.

- [ ] **Step 1: Add ledger reading guide and schema**

The beginning must explain in plain language:

```markdown
这不是另一篇实施文档。它像目录：先按 ID 找到问题，再跳转到阶段文档看完整代码和证据。
```

Add columns: ID, type, plain-language problem, choice/fix, evidence, result, detailed record.

- [ ] **Step 2: Backfill E0 decisions and limitations**

At minimum add:

```text
E0-D01 staged R1/R2 scope
E0-D02 facts-first corpus before parser/index changes
E0-D03 preserve baseline and require ablation
E0-L01 historical test split is regression-only
E0-L02 current small corpus cannot support production-scale claims
```

- [ ] **Step 3: Backfill E1 decisions, incidents and limitations**

Add E1-D01 through E1-D06, E1-I01 through E1-I07, and E1-L01 through E1-L05. Every row must use an evidence label and link to `e1_enterprise_corpus_implementation.md`.

- [ ] **Step 4: Verify ledger has no orphan IDs**

Run:

```powershell
rg -o "E[01]-[DILX][0-9]{2}" docs\roadmap\engineering_decision_failure_ledger.md | Sort-Object -Unique
```

Expected: all listed IDs are defined in the detailed phase records or explicitly marked as stage-level records.

### Task 3: Backfill the E0 Beginner-Friendly Implementation Record

**Files:**
- Create: `docs/roadmap/e0_readonly_audit_implementation.md`
- Read: the three existing E0 design/plan/gap documents

**Interfaces:**
- Consumes: E0 read-only audit outputs and baseline evidence.
- Produces: an accessible explanation of what E0 inspected, what it learned, why no business code was changed, and how E1-E7 were derived.

- [ ] **Step 1: Explain E0 in plain language**

Start with:

```text
E0 不是“什么都没做”。它先确认旧项目真实具备哪些能力，防止把计划中的能力写成已经完成。
```

Add a glossary for baseline, provenance, gap analysis, phase gate, ablation and regression set.

- [ ] **Step 2: Document the audit path**

Explain, in reading order, the old parser/index/retriever/Agent/evaluator/API/UI entry points and what was observed. Separate verified code behavior from historical claims.

- [ ] **Step 3: Explain each major E0 decision**

For E0-D01 through E0-D03, record alternatives, chosen approach, why it reduced risk, and what evidence would later prove it useful.

- [ ] **Step 4: Add beginner exercises and interview answers**

Include one architecture tracing exercise, five questions with answers, one two-minute oral task and a “cannot claim yet” section.

### Task 4: Rewrite E1 Changes C01-C04

**Files:**
- Modify: `docs/roadmap/e1_enterprise_corpus_implementation.md`
- Read: `app/corpus/schemas.py`
- Read: `app/corpus/generator.py`
- Read: `app/corpus/renderers.py`
- Test evidence: `tests/corpus/test_schemas.py`, `test_repository_inputs.py`, `test_generator.py`, `test_renderers.py`

**Interfaces:**
- Consumes: existing E1 summary and verified source/tests.
- Produces: beginner-first records for schemas, facts/profiles, generator and renderers.

- [ ] **Step 1: Add document reading guide and glossary**

Explain schema, invariant, seed, renderer, authoritative, supporting and four noise variants before using them deeply.

- [ ] **Step 2: Write E1-C01 schema and invariants**

Trace:

```text
JSON bytes -> json.loads -> Pydantic model_validate -> nested validators -> trusted CompanyFacts
```

Explain `PolicyVersion.validate_version`, `PolicyFamily.validate_versions`, `CompanyFacts.validate_references`, `CorpusProfile.validate_profile` and `DocumentSpec.validate_fact_ids` branch by branch.

- [ ] **Step 3: Write E1-C02 facts/profile source of truth**

Explain why facts and presentation documents are separate, how 8 policies/16 versions/32 facts are organized, and why seed cannot alter authoritative truth.

- [ ] **Step 4: Write E1-C03 deterministic generation**

Explain `generate_document_specs` input, base-count arithmetic, authoritative/supporting generation, noise injection and exact count assertion using demo values.

- [ ] **Step 5: Write E1-C04 five renderers**

Explain why rendering occurs after logical document creation, how every renderer preserves fact IDs through the manifest, and what E2 still needs to verify about parser fidelity.

### Task 5: Rewrite E1 Changes C05-C08 and Incidents

**Files:**
- Modify: `docs/roadmap/e1_enterprise_corpus_implementation.md`
- Read: `app/corpus/eval_cases.py`
- Read: `app/corpus/artifacts.py`
- Read: `scripts/generate_enterprise_corpus.py`
- Test evidence: remaining `tests/corpus/*.py`

**Interfaces:**
- Consumes: C01-C04 outputs and generated `DocumentSpec` objects.
- Produces: detailed eval, artifact safety, checked-in boundary and documentation records.

- [ ] **Step 1: Write E1-C05 structured eval and frozen split**

Explain all six task types, `gold/distractor/forbidden`, permission vs no-answer, stratified split, interleave and SHA256 freeze. Include one case traced from fact to JSON.

- [ ] **Step 2: Write E1-C06 artifact write and CLI safety**

Trace:

```text
validate target -> build in memory -> write staging -> write manifest last -> activate -> cleanup
```

Explain `--dry-run`, `--force`, ownership validation, root/home rejection and bounded Windows rename retry.

- [ ] **Step 3: Write E1-C07 checked-in boundaries**

Explain why 72/600 generated corpora are ignored while facts, profiles, frozen eval and five smoke fixtures are versioned.

- [ ] **Step 4: Write E1-C08 data card and learning ownership**

Explain synthetic data disclosure, evidence boundaries and why Codex cannot mark learning complete.

- [ ] **Step 5: Add seven incident postmortems**

For each incident record symptom, wrong/initial hypothesis, diagnostic experiment, final fix, regression and remaining uncertainty:

```text
E1-I01 pytest helper collection
E1-I02 Windows CLI encoding
E1-I03 staging rename WinError 5/32
E1-I04 missing cross-version overlap validation
E1-I05 permission split 4/1
E1-I06 patch tool aborted receipt
E1-I07 PowerShell Get-Content JSON encoding false failure
```

### Task 6: Expand Private Audit and Learning Materials

**Files:**
- Create: private `Enterprise_Agentic_RAG_v2_E0_实施记录.md`
- Modify: private `Enterprise_Agentic_RAG_v2_E1_实施记录.md`
- Create: private `E0_只读审计与工业化设计_学习卡.md`
- Modify: private `E1_企业档案与评估集_学习卡.md`

**Interfaces:**
- Consumes: public phase records and current local evidence.
- Produces: local command history, beginner code navigation, interview training and hands-on exercises without polluting the public repo.

- [ ] **Step 1: Add E0 audit and learning card**

Include purpose, code map, five concepts, three commands, one 20-minute experiment, five interview questions, oral task, next-day rewrite and evidence paths.

- [ ] **Step 2: Expand E1 audit with stable IDs**

Map every E1-C/E1-I/E1-L entry to files and tests. Preserve existing hashes and explicitly label retrospective content.

- [ ] **Step 3: Add line-by-line learning walkthroughs to E1 card**

Include one trace each for schema validation, document generation, eval generation and safe artifact activation. Explain function parameters and return values in plain language.

- [ ] **Step 4: Keep learning status unapproved**

Run:

```powershell
rg -n "未验收，不得标记为已掌握" <private E0/E1 learning cards>
```

Expected: both cards retain the exact learning-state warning.

### Task 7: Verify Backfill and Hand Off to E2

**Files:**
- Verify all files from Tasks 1-6.

**Interfaces:**
- Consumes: completed three-layer journal.
- Produces: evidence-backed E1 acceptance and a clean E2 starting point.

- [ ] **Step 1: Check placeholders, private paths and whitespace**

Run repository scans for `TODO`, `TBD`, private absolute paths and trailing whitespace. Intentional mentions in the journal standard must be reviewed manually.

- [ ] **Step 2: Check IDs and required beginner sections**

Verify E0/E1 phase records include “先说人话”, glossary, code reading order, test evidence, limitations, interview questions and hands-on experiment.

- [ ] **Step 3: Re-run E1 regression gates**

Run focused and full pytest, both corpus dry-runs and frozen hash verification. Documentation changes must not alter any generated hash.

- [ ] **Step 4: Check final Git/process boundary**

Run:

```powershell
git status --short --branch
git diff --check
Test-Path .git\index.lock
```

Expected: no unexpected files, no Git lock, no commit or push.

- [ ] **Step 5: Start E2 under the same journal standard**

Create the E2 phase record before changing parser/index code, capture its baseline, then follow TDD change by change.
