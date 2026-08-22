# Known Limitations

1. The approval, local draft effect command, and completion outbox share one
   SQLite transaction. LangGraph checkpoints and trajectory projection remain
   separate stores and do not share a distributed transaction.
2. The implemented side effect is a local access-request draft only. No ticket,
   email, IAM, or ACL integration exists.
3. PostgreSQL covers LangGraph checkpoints in CI; approval/effect/completion
   ownership is still SQLite-backed and therefore a shared-filesystem,
   single-database deployment assumption.
4. There is no approval inbox, notification delivery, revocation UI, retention
   worker, or operational runbook.
5. Current approvals use a persisted server-side locator Handle so a lost Start
   response can be recovered. The Handle is not authorization. Authenticated
   identity, tenant, reviewer role, ACL/policy, expiry, and argument hash are
   revalidated. Handle revocation policy, transport hardening, and an operational
   approval service remain deployment work.
6. SHA-256 identity fields are pseudonyms and may remain personal data under a
   real organization's policy.
7. OTel has no configured production collector, sampling policy, tail sampling,
   metrics backend, alert, or retention policy.
8. Local real-model harness mode depends on the existing local index and Ollama
   configuration; it is deliberately absent from deterministic CI.
9. The standard `LangGraphOrchestratorAdapter` still has same-process HITL. Only
   `DurableAccessRequestWorkflow` uses durable checkpoints. The deprecated
   `DurableLangGraphOrchestrator` name is an import alias, not a generic Agent
   orchestrator.
10. No multi-host load, lock contention, database failover, network partition,
    or chaos test was run.
11. No AgentDojo benchmark was integrated because doing so would require a
    mismatched tool/business environment and external model experiment.
12. This work changes runtime reliability/security mechanisms, not frozen RAG
    retrieval or answer-quality metrics.
13. Lease correctness assumes a sufficiently consistent database-facing clock;
    no distributed clock-skew qualification has been run.
14. Completion outbox delivery is an idempotent local projection, not an
    externally managed dispatcher with retries, alerts, retention, or dead
    lettering.
15. Start/Resume process concurrency is tested against one SQLite database, but
    multi-host HA, database failover, network partition behavior, and automatic
    failover remain unverified and must not be claimed.
