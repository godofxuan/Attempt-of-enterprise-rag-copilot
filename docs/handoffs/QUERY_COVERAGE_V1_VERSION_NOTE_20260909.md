# Query Coverage V1 version note

Date: 2026-09-09

## Version position

This record describes a limited development candidate. It does not replace the
canonical public version.

```text
canonical public checkout          D:\文档\agent\RAG_try
canonical public HEAD              c9984e92a10a6f417e2c1d8082af7e8f1e11aee1
candidate working tree             D:\文档\agent\RAG_try\.private\runtime_closure_20260907T160738
candidate branch                   fix/runtime-closure-20260907T160738
candidate base HEAD                b07c03d0256c393db5dfbb969e5d20abd70155b0
candidate patch                    UNCOMMITTED
main / GitHub / active index       UNCHANGED
merge / release / deployment       NOT PERFORMED
```

The candidate inherits pre-existing uncommitted correctness work in its
working tree. Its behavior cannot be attributed to `b07c03d` alone.

## What the candidate changes

- Registers a limited set of expense-query needs covering materials,
  approval, amount limits, and personal applicability. It does not rewrite the
  original question or search string.
- After a first admitted search hit, permits at most one `find` and two chunk
  `open` operations within the same admitted document, version, identity,
  filters, and authorization boundary.
- Carries missing needs into the response body, warnings, mode, and trace. A
  single relevant hit or a valid citation is not treated as proof that every
  requested item was answered.
- Preserves the existing Guard, ACL, citation checks, tool budgets, deadlines,
  and host-controlled execution. It adds no LLM planner or evidence grader.

## Verification recorded for this candidate

- Adjacent regression: 389 passed, 0 failed, 0 skipped. This is 367 existing
  adjacent tests plus 22 new targeted tests, not 389 real user questions.
- Eight fixed first-retrieval-hit development probes were run in paired form.
- In the real local `qwen2.5:3b` arm, target facts delivered into the generation
  packet changed from 7/14 to 12/14; target facts retained in final cited claims
  changed from 6/14 to 10/14.
- Cases that omitted or lacked a requested condition while still publishing
  `answered` changed from 4/8 to 0/8, partly through conservative `partial`
  outcomes. This is not a 100% correctness claim.
- Two cases showed actual content gains: a later travel-receipt clause and a
  colloquial expense-material query reached the verified final answer.
- Each real-model arm made seven answer-generation calls; the candidate added
  no planner or grader calls.

The fixed probes are consumed development cases. They do not replace an
independent user set or the frozen retrieval benchmarks. Observed latency is
confounded by model loading, run order, caching, and one truncated baseline
output, so no speedup claim is supported.

## Known residual gap

The three-need probe still does not publish every supported item. The model's
raw structured output and generation packet contain material and amount-limit
claims, but the existing approval answer-publication contract filters them and
retains only the approval claim. This is a publication-contract composition
gap, not evidence that the model failed to generate those facts. A numbered
query without a matching document also remains `not_found`.

## Claim boundary

Safe summary:

> 针对长文档漏读和多诉求遗漏，增加受限 find/open 补读与缺项提示，并以配对运行核对证据交付和最终回答。

Do not claim that this candidate is merged, deployed, or the default runtime;
that it generally solves multi-intent understanding; that it uses LLM-driven
planning or rewriting; that it achieved 100% correctness or human-validated
accuracy; or that it improved latency. The established WixQA Recall/nDCG
figures and the distinction between raw-50 experiments and raw-20 serving
implementation remain unchanged because this work did not rerun those
benchmarks.

## Source evidence

- Candidate handoff: `.private/runtime_closure_20260907T160738/docs/query_coverage_v1/HANDOFF.md`
- Candidate report: `.private/runtime_closure_20260907T160738/docs/query_coverage_v1/REPORT.md`
- Candidate protocol and result files reside beside that report.
- Raw evidence root: `.private/query_coverage_upgrade_20260909`
