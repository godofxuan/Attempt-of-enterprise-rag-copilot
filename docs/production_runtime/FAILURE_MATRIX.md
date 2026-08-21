# Production Runtime Failure Matrix

| Failure | Expected behavior | Automated evidence |
|---|---|---|
| Unknown/admin tool | `DENY`, no backend call | `test_tool_policy.py` |
| ACL denied on an ASK tool | `DENY` wins; no approval | durable and policy tests |
| Model attempts identity override | gateway/policy deny | tool contract and policy tests |
| Expired auth/deadline or exhausted budget | fail closed | policy and existing gateway tests |
| Pre/post hook raises | deny or discard output | policy tests |
| Malicious retrieved text | existing Guarded registry quarantines before publication | existing injection/runtime suites |
| Process exits after interrupt | new process loads checkpoint and approval binding | durable restart test |
| Wrong tenant, wrong reviewer, missing role | resume rejected; no draft | durable authorization test |
| Tool arguments changed | resume rejected by SHA-256 binding | durable authorization test |
| Approval expired | resume rejected | durable authorization test |
| Crash before command commit | rollback; retry commits once | side-effect and durable tests |
| Crash after commit before response | retry returns committed result | side-effect and durable tests |
| Duplicate resume | same persisted result; one draft | durable restart test |
| OTel exporter unavailable | business result succeeds; failure counter increments | telemetry test |
| Trace carries content/credential | forbidden attributes removed | telemetry privacy test |
| PostgreSQL checkpointer unavailable locally | explicit skip, not PASS | integration marker and CI service job |

No row proves multi-host concurrency, database failover, IAM integration, SLOs,
or general prompt-injection resistance.
