# V2 Bounded Adaptive Retrieval Decision Record

## Decision

`ADAPTIVE_RETRIEVAL_NOT_YET_JUSTIFIED`

No adaptive-retrieval serving path is present in the V2 Agent Runtime. The existing deterministic Controller, ToolGateway, ACL, retrieved-content Guard, Evidence Ledger, grounding gate, citation path, trajectory/replay behavior, and LangGraph runtime remain unchanged.

## What Was Tested

The development-only diagnostic limits an assessor to a strict JSON proposal with a 120-character addendum. It gives the model only Guard-admitted evidence, appends accepted text to the original query, and measures the union of the baseline and one retry Top-5 against the frozen WixQA multi-document gold mapping.

The predeclared implementation gate is:

```text
retry_fully_recovered >= 3
and retry_fully_recovered / baseline_failures >= 0.10
```

## Why Serving Was Not Added

The first run had 3 fully recovered cases out of 17 baseline failures. A repeat with the same model and corpus had only 2 fully recovered cases out of 17. The absolute threshold therefore did not reproduce. The original diagnostic set temperature zero but did not pin an Ollama generation seed, and used a 12-second per-case timeout. A follow-up diagnostic pins a stable per-case seed, records an input hash for every assessor request, and uses a 30-second timeout. The result remains a no-go unless that protocol produces a stable, predeclared pass and then passes an unconsumed confirmation cohort.

The dominant observed bottlenecks remain initial Top-20/Top-5 retrieval misses and false ledger completeness, rather than a demonstrated, stable query-rewrite recovery path.

## Next Evidence Gate

Do not implement or enable a serving retry until a frozen assessor-output cache or a deterministic alternative-query policy reproduces the gate on a development cohort, followed by a separate unconsumed confirmation set. Any future serving proposal must keep `OFF`, `SHADOW`, and `ON` modes, one retry maximum, host-side addendum validation, and the existing Gateway/Guard/ACL route.
