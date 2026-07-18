# R2-S1 Scope and Threat Model

状态：D1 threat model frozen；D3-D5 implementation `GREEN`；D6 deterministic frozen evaluation `PASSED`；D7 live `NOT RUN`
权威总设计：[R2-S1 design spec](../../superpowers/specs/2026-07-17-r2-s1-indirect-prompt-injection-design.md)

## 1. Protected Asset

R2-S1 保护的是 `/agent/v2/chat` 的可信控制流、模型上下文、授权证据、回答、来源和 trace。目标不是证明模型永远不会被说服，而是让不可信检索内容不能获得新的系统权限，并能量化它是否传播到敏感下游。

需要保护的安全属性：

| Property | Required invariant |
|---|---|
| instruction integrity | 文档内容不能改变 Python allowlist、ACL、预算或 stop policy |
| context integrity | quarantined 内容不能进入 Controller、Ledger、generator 或 verifier |
| confidentiality | system/document/trace canary 和无权文档不得出现在回答或 trace |
| capability confinement | 文档中的 URL、命令或角色标签不能触发真实外部副作用 |
| availability | 单条恶意内容不能造成无限扫描、无限检索或无限解码 |
| auditability | 每次结果有版本化规则、数据、代码和 artifact provenance |
| honest claims | 固定集结果不得写成未知攻击免疫或生产级安全 |

## 2. Adversary

假设攻击者能提交或影响一个对目标用户可见的企业知识库文档，控制以下一个或多个字段：正文、标题、章节、表格单元格、source path、文本 metadata、相邻 chunk。攻击者知道系统使用 RAG，但不知道每次请求生成的 delimiter nonce，也不能修改代码、索引运行时或 ACL policy。

攻击者目标包括：

- 覆盖可信回答规则；
- 伪装成 SYSTEM/ASSISTANT/tool；
- 诱导输出 document/system canary；
- 诱导调用不存在或禁止的工具；
- 诱导请求攻击者 URL；
- 用 Unicode、Base64、markup 或相邻片段规避检测；
- 用高排名投毒占据 top-k，制造错误回答或拒答。

## 3. Trust Assumptions

Trusted for this phase:

- checked-in Python code and pinned direct dependencies；
- active index manifest and ACL metadata integrity；
- server-side `AccessPolicy` and typed Pydantic contracts；
- local model endpoint configuration；
- deterministic evaluator implementation after its own hash is recorded。

Untrusted even after ACL admission:

- all document-derived text and text-like metadata；
- search snippets、parent context、find preview、open content；
- model output；
- user question（由现有 direct-input guard 单独处理）；
- request-supplied identity in the current local demo，直到真实 IAM 在服务端构造身份。

## 4. Threat Events

| ID | Threat event | Entry surface | Target | Required response |
|---|---|---|---|---|
| `R2-T01` | instruction override | body/snippet/open | generator | quarantine before Controller |
| `R2-T02` | role impersonation | title/heading/body | generator | quarantine or keep bounded as benign quote only when context rule permits |
| `R2-T03` | secret/system extraction | body/table/metadata | answer/system canary | quarantine; output canary gate |
| `R2-T04` | tool or egress inducement | URL/command/SOP-like text | tool layer/network | no capability; quarantine attack variant; no-egress assertion |
| `R2-T05` | Unicode/homoglyph mixing | any text field | detector | NFKC/invisible detection view |
| `R2-T06` | encoded payload | Base64-like content | detector/generator | one bounded decode; no recursion/decompression |
| `R2-T07` | markup wrapping | Markdown/HTML/comment/code/link | detector/generator | scan extracted content and structural markers |
| `R2-T08` | split payload | adjacent same-doc chunks/parent | detector | bounded adjacent aggregate; no arbitrary graph search |
| `R2-T09` | ranking displacement | top-ranked poisoned chunks | availability/quality | quarantine then bounded top-up |
| `R2-T10` | benign security discussion | training/software/SOP docs | utility | report FP; preserve admitted original content |
| `R2-T11` | Guard exception | malformed/oversized content | availability | quarantine item; continue admitted evidence |
| `R2-T12` | Guard initialization failure | rules/config | whole request | source-free `system`; never auto-off |

## 5. Security Outcomes

`unsafe` remains the pre-retrieval outcome for a dangerous user question. `security_filtered` is a separate post-retrieval outcome: candidates existed but policy withheld all usable evidence. `not_found` means no supporting visible evidence was found. `permission` means only denied evidence was observed internally. These states must not be collapsed because they have different operational meaning and different leakage risks.

## 6. Residual Risk

- Rule-based detection can miss novel semantic attacks and can quarantine difficult benign text.
- A model can still misinterpret admitted ordinary evidence without an injection.
- Bounded split detection does not cover arbitrary cross-document composition.
- Current local identity is caller supplied and is not production authentication.
- Current telemetry is in-memory and local-only.
- A machine administrator who changes code/index/rules is outside this threat model.

Passing the frozen set supports only the narrow claim in the design spec.
