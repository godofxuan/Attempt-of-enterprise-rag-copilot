# Known Limitations

最后更新：2026-07-17

本文使用三个状态：`FAILED` 表示已运行且未通过；`NOT RUN` 表示没有满足协议的 fixture/依赖或实验；“未实现”表示代码能力不存在。`NOT RUN` 不能写成通过。

## 1. 当前限制表

| Area | Current state | Consequence | Admission condition |
|---|---|---|---|
| Identity | `UserContext` 由浏览器/调用方声明，只做 schema 和 policy 验证 | 本地演示可以验证 ACL 逻辑，但不能证明真实用户身份 | 由可信 OIDC/IAM gateway 签发身份，并加入 token/tenant/group integration tests |
| Data realism | 72/600 文档和 52 个 eval cases 全部 synthetic | 指标证明工程 contract，不代表真实企业分布或生产泛化 | 法务批准的去标识 pilot corpus、数据治理记录和独立 held-out evaluation |
| Live quality | 当前 canonical live dev 为 23/24 | 一个 system-runtime failure 被保留；不能报告 100% | 先定位/复现失败，再在新冻结 split 上验证，而不是改写旧 artifact |
| Indirect document injection | `NOT RUN` | 直接 prompt probes 通过不代表恶意检索文档安全 | 新 corpus version 加入不可信文档指令、canary 和 expected safe behavior；重建索引并运行 E4 security suite |
| Reranker | `NOT RUN` (`no_admitted_reranker`) | 不能声称 cross-encoder/reranker 改善过排序 | 固定候选模型、license/资源预算与 latency gate；在 frozen test 上做隔离消融 |
| Human review | `NOT RUN`；50 行、8 个人工判断列保持空白 | 自动 claim/citation/required-fact checks 不能替代语义和可用性评分 | 本人按冻结 rubric 完成 review；若用于正式质量结论，再增加第二 reviewer、分歧仲裁和 agreement 记录 |
| Authentication/authorization | 只有本地 ACL policy，没有 SSO、token verification、policy admin 或 audit identity | 不能公网暴露为企业服务 | IAM、server-derived claims、deny-by-default policy store、admin/change audit |
| Index updates | immutable rebuild + activate；没有 incremental upsert/delete | 文档变化需要新 run，不能承诺低延迟同步 | 定义 document tombstone/version contract、idempotency、rollback 和 consistency tests |
| Observability | bounded in-memory traces/metrics | 重启丢失，不能跨进程关联或长期查询 | OpenTelemetry SDK/collector、durable backend、retention/redaction/access policy |
| Deployment | 本地 Windows + Ollama，未提供 production container/orchestrator | 没有证明 Linux image、network policy、resource limits 或 rolling deploy | Reproducible image/SBOM、health probes、secret injection、staging load and rollback |
| Remote CI | workflow contract 在代码中；没有可核验 run URL 时为 `NOT RUN` | 本地通过不等于远端 runner 通过 | 功能分支推送后，核对真实 GitHub Actions run URL、commit SHA 和 artifact retention evidence |
| Scale | demo index 64 chunks；benchmark 不是生产 load | FAISS/in-memory BM25 结论不能外推到 5,000+ 活跃文档与并发租户 | 规模/并发/更新率达到预设阈值后重新 profile，再决定 vector DB/caching |
| Model robustness | direct unsafe rule-first probe 只有 4 条 | 编码、多语言、间接和新型绕过仍可能通过 | 扩展 adversarial taxonomy、人工红队、版本化 model/prompt regression |
| Feedback | 仅保存 question/response SHA-256、helpful、request ID 和时间 | 无法直接读取正文调试；也没有用户级去重或分析平台 | 在隐私评审后建立受控 failure sampling，而不是默认保存全文 |
| Availability | 单进程、单 active index、单本地 Ollama | 没有 HA、队列、backpressure 或多副本一致性 | 明确 SLO/RTO/RPO 后再设计 replicas、queue 和 failover |
| Agent scope | 单 controller、固定工具 allowlist、无长期记忆/checkpoint | 不能称通用 autonomous/multi-Agent platform | 只有出现跨会话恢复或独立角色协作的真实需求与 eval 时才准入 |

## 2. 指标解释限制

- `28/28` deterministic 表示当前合成 test 上的系统 contract 全部通过；它不调用真实 chat/embedding 模型。
- `23/24` live 是一个开发 split 和一次指定本机环境运行；不能当作 production accuracy。
- retrieval 的 `precision@5` 分母固定为 5。单一 gold 文档题即使首位正确，后续位置会自然降低 precision；需要同时看 recall、MRR、NDCG、authority 和 invalid extras。
- workflow ablation 的 outcome accuracy 不逐句评价生成文本；response layer 另测 required facts、citation 和 unsupported claims。
- load p95 来自 31 次本地请求，样本小且硬件/模型常驻状态敏感；它是演示 profile，不是 SLO。
- public snapshot 是原始 artifacts 的脱敏摘要。它带 hash provenance，但不替代 ignored source run 的逐题复核。

## 3. 安全声明限制

已经验证的是：固定 direct unsafe prompts 在 query analysis 后、retrieval 前 source-free 拒绝；ACL 测试不暴露 forbidden docs；错误/trace 不回显已知敏感字段。

尚未证明的是：任意 prompt injection 都会失败、retrieved content 无法影响模型、system prompt 永不泄露、浏览器声明身份可信、或该服务适合公网/多租户生产。

完整威胁与控制映射见 [Security Threat Model](security_threat_model.md)。

## 4. 公开展示边界

- README 与 UI 必须显示 live `23/24`，不能四舍五入为 100%。
- indirect document injection 与 optional reranker 必须显示 `NOT RUN`。
- `526 passed` 是 E5 入口、`569 passed` 是 E6 收口、`574 passed` 是 E7 自动化本地门禁；它们是不同 commit 候选的历史计数，不能相加。
- 没有远端 run URL 时不能声称 GitHub Actions 已实际通过。
- E7 已逐条处理 claims matrix；只能使用 `approved` 原句或 `narrowed` 后的措辞，不能删掉 synthetic、deterministic/local、样本数和 `NOT RUN` 边界。

下一阶段准入项与优先级见 [Industrialization Backlog](industrialization_backlog.md)。
