# Production Runtime Failure Matrix

| Failure | Expected behavior | Automated evidence |
|---|---|---|
| Unknown/admin tool | `DENY`, no backend call | `test_tool_policy.py` |
| ACL denied on an ASK tool | `DENY` wins; no approval | durable and policy tests |
| Model attempts identity override | gateway/policy deny | tool contract and policy tests |
| Expired auth/deadline or exhausted budget | fail closed | policy and existing gateway tests |
| Pre hook raises | fail closed | policy tests |
| Post hook raises | discard output | policy tests |
| `tool_error` hook raises | preserve original business exception; separately record hook type/error type | policy tests |
| `run_stop` hook raises | completed tool state remains complete; close continues | policy tests |
| Malicious retrieved text | existing Guarded registry quarantines before publication | existing injection/runtime suites |
| Process exits after interrupt | new process loads checkpoint and approval binding | durable restart test |
| Wrong tenant, wrong reviewer, missing role | resume rejected; no draft | durable authorization test |
| Tool arguments changed | resume rejected by SHA-256 binding | durable authorization test |
| Approval expired | resume rejected | durable authorization test |
| Two DB connections resume concurrently | one owner; loser gets `ALREADY_RESUMING` | thread race durable test |
| Owner lease expires | new owner gets a higher version; stale owner is fenced | stale-owner durable tests |
| Crash before effect | rollback all workflow facts; lease recovery commits once | atomic failure matrix |
| Crash after effect, before completion | rollback all workflow facts; recovery commits once | atomic failure matrix |
| Crash after completion, before approval | rollback all workflow facts; recovery commits once | atomic failure matrix |
| Crash after approval update, before commit | rollback all workflow facts; recovery commits once | atomic failure matrix |
| Crash after commit, before response | terminal result survives; retry projects completion once | atomic failure matrix |
| Duplicate resume | same persisted result; one draft and one completion | durable restart test |
| OTel exporter unavailable | business result succeeds; failure counter increments | telemetry test |
| Trace carries content/credential | forbidden attributes removed | telemetry privacy test |
| PostgreSQL checkpointer unavailable locally | explicit skip, not PASS | integration marker and CI service job |

No row proves multi-host HA, database failover, network-partition recovery,
external side-effect delivery, IAM integration, SLOs, or general
prompt-injection resistance.
