# ESA workbench: recovery fixes and 0.7 release candidate

> 本文是可以公开的草稿模板。发布前把方括号替换为本机核实结果。不得复制完整私有审核包。

## Summary
- Keep one FastAPI application, a bundled React workbench, and a persistent local workspace.
- Preserve original turn options on retry, restore knowledge-base bindings, and page/search conversation history.
- Preserve existing data when a workspace moves; keep published knowledge usable during index updates.
- Consume proposed mixed tool batches; retain existing loan/repair transactions and readback.
- Keep the new grounded-expression experiment **off by default** while its semantic issues are investigated.

## Current status
This is a work-in-progress PR, not a claim of a stable production release. The application targets local single-user use with explicitly synthetic service workflows.

Source branch/commit: [actual branch and SHA].
Default checks: [actual result and environment].
Browser: [actual result; distinguish controlled external-model doubles].
Live model/business: [actual result and build].
Windows artifact: [actual artifact; native first-run/IME status].

## Known work in this PR
- Partial delivery must remain resumable rather than becoming DONE and refusing retry.
- A preview alone must not satisfy a turn that also requested a knowledge answer.
- Explicit preparation should call the domain use case directly.
- Running/build identity and normal upgrade flow need to be unambiguous.
- Experimental answer quality and default product readiness are reported separately.

## Data and compatibility
Existing workspace data is preserved. No private database, raw personal model transcripts, credentials, or model weights are included in this PR. User confirmation, idempotent business writes, and readback remain in place.

## Review focus
Review current product behavior, default API/build/CI, partial result recovery and data continuity. Experimental failures are retained visibly and are not represented as successful default capabilities.
