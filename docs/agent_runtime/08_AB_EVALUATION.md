# Bounded Controller versus LangGraph A/B

## Frozen mechanism protocol

The first vNext A/B is a five-case deterministic mechanism test: grounded
answer, no visible match, permission denial, unsafe request, and indirect prompt
injection in retrieved content. Each arm receives a fresh but identical typed
navigator, identity, ACL, Guard, tool set, budget, and extractive response
builder. HITL is disabled.

Metrics include task success, grounded response, citation correctness, tool-call
validity, tool and step counts, latency, terminal reason, permission violations,
and paired behavioral parity.

Each arm receives one discarded warm-up before timing. Reported latency covers
the complete `run()` call and therefore includes the current per-request graph
compilation cost. With only five measured cases, p95 is diagnostic mechanism
evidence, not an SLO or capacity result.

This protocol verifies that introducing an alternative orchestrator does not
change security and terminal behavior. Five synthetic mechanism cases are too
small and too controlled to support an external answer-quality claim. Existing
WixQA and security evidence remains separate and is not relabeled as LangGraph
evidence.

## Reproduction

```powershell
python -m scripts.eval_agent_runtime_ab
```

The generated artifact records the implementation SHA and dataset hash. Results
are added only after the evaluator code is committed so the SHA identifies the
actual executable implementation.

## Recorded result

- Implementation SHA: `d20382d111cc6ee5a54a1daad92454ecf0c501f3`
- Dataset SHA-256: `48cb124d2f00aa925ae2aaec7f3a1682b9742f76628bb10e637c017ffc658241`
- Artifact SHA-256: `c39d95808fddc882f3f98bf4bdff7c3c0fc59456689415a974d8837a2e9850d9`
- Cases: 5, with 10 total arm rows
- Behavioral parity: 100%
- Task success: 5/5 for each arm
- Permission violations: 0 for each arm
- Mean tool count / step count: 0.8 / 1.8 for each arm
- Bounded p95: 1.283 ms
- LangGraph p95: 6.838 ms

LangGraph produced no quality gain on this protocol. Its p95 was about 5.33x
the bounded adapter because the current implementation compiles a graph per
run. The absolute overhead is small in this in-memory fixture, but the ratio and
five-case p95 must not be generalized to production. The adapter is retained as
an alternative for explicit graph state and HITL, not promoted as the default.
