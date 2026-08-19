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

