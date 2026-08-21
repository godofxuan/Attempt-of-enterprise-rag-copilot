# Known Limitations

1. SQLite checkpointer, approvals, effects, and trajectory are separate files;
   they do not share a distributed transaction.
2. The implemented side effect is a local access-request draft only. No ticket,
   email, IAM, or ACL integration exists.
3. PostgreSQL covers LangGraph checkpoints in CI; approval and effect stores are
   not yet PostgreSQL-backed.
4. There is no approval inbox, notification delivery, revocation UI, retention
   worker, or operational runbook.
5. Approval tokens are bearer secrets returned to the caller. Only their hashes
   are persisted, but transport/session protection remains deployment work.
6. SHA-256 identity fields are pseudonyms and may remain personal data under a
   real organization's policy.
7. OTel has no configured production collector, sampling policy, tail sampling,
   metrics backend, alert, or retention policy.
8. Local real-model harness mode depends on the existing local index and Ollama
   configuration; it is deliberately absent from deterministic CI.
9. The standard `LangGraphOrchestratorAdapter` still has same-process HITL. Only
   the new draft approval workflow uses durable checkpoints.
10. No multi-host load, lock contention, database failover, network partition,
    or chaos test was run.
11. No AgentDojo benchmark was integrated because doing so would require a
    mismatched tool/business environment and external model experiment.
12. This work changes runtime reliability/security mechanisms, not frozen RAG
    retrieval or answer-quality metrics.
