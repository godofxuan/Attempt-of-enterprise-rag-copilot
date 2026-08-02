# FinQA Gate E6: Role-to-Candidate Compatibility

## 1. Purpose and boundary

Gate E5 showed that a model can emit a valid multi-step shape while binding the
wrong numbers. E6 asks a narrower question:

> Before another model run, can each semantic operand role see its required
> source number inside a bounded, source-preserving allowlist?

This is an input-layer diagnostic, not answer accuracy. It reuses the disclosed
60-case development calibration. The 40-case internal validation is `NOT_RUN`,
the frozen test is `UNTOUCHED`, and every typed serving route remains disabled.

Runtime inputs are limited to the question, host intent, strictly parsed
semantic skeleton, Guard-admitted operands and admitted evidence text. Gold
program, answer, case ID and gold evidence IDs are offline diagnostics only.

## 2. E6-v1: diagnose the global shortlist

E6-v1 applied role compatibility after a global Top-24 shortlist.

| Metric | E6-v1 |
|---|---:|
| Supported source recall | 91.20% |
| Role recall@4 | 62.77% |
| Role recall@8 | 75.91% |
| Complete case@8 | 63.33% |
| Edge reduction | 65.68% |

The 125 supported roles decomposed into 11 missing before role ranking, zero
removed by the hard filter, 10 present but below rank 8, 28 present but below
rank 4, and 104 retained at 8. The global shortlist was therefore a measured
bottleneck.

## 3. E6-v2 implementation

E6-v2:

1. keeps the complete Guard-admitted operand pool host-side, capped at 128;
2. ranks independently per evidence role;
3. exposes at most 8 candidates per role and 32 unique candidate IDs;
4. supports five program steps and eight evidence roles;
5. represents arithmetic constants as a strict host enum;
6. routes boolean comparison and symbolic table aggregation back to B0;
7. parses bindings through per-role candidate enums.

The controlled compiler is
`app/external_datasets/finqa_controlled_program.py`. It reuses v2.3
source-bound candidate validation and v2 Decimal semantics. A constant has no
candidate ID or evidence ID, so it cannot fabricate a citation.

## 4. Reproducibility incident

The first implementation added constant support to the historical
`finqa_typed_program.py`. Full tests failed because the E3 evidence manifest
hashes that source file. Outputs had not changed, but historical
reproducibility was no longer true.

The repair restored old files byte-for-byte, moved the capability into a new
versioned module, left the old manifest unchanged and reran the complete
external suite. Updating the old manifest was rejected because that would hide
the regression.

## 5. Why `const_N` is not automatically a constant

The first audit stopped on:

```text
CME/2012/page_70.pdf-4
subtract(const_7, const_5), divide(#0, const_5)
```

The evidence says a credit line can move from USD 5 billion to USD 7 billion.
Both numbers are document facts even though FinQA serialized them as constants.
Treating them as host constants could produce 40% while dropping provenance.

The offline rule is occurrence-sensitive:

- if the value can be reconstructed from gold evidence, keep an evidence role;
- otherwise allow it only when it belongs to the frozen constant enum;
- reject unknown non-source constants.

Runtime does not inspect gold. A real planner must represent sourced 5 and 7 as
evidence roles.

## 6. E6-v2 audit history

All write-once outputs are retained. The authoritative selector is
`finqa_role_compatibility_v2_audit_erratum_v1.json`.

| Version | Meaning | Recall@8 | Complete@8 |
|---|---|---:|---:|
| v1 | caller included non-operands | 0.00% | 0.00% |
| v2 | first valid full-pool result | 83.74% | 77.59% |
| v3 | local/diversity ablation, rejected | 77.24% | 68.97% |
| v4 | conservative authoritative result | 83.74% | 77.59% |

V4 also has source recall 100%, constant recall 100%, route accuracy 100%,
edge reduction 73.44%, input-order invariance 60/60, identity preservation
60/60, zero known-period conflicts, zero non-admitted exposure and zero model
calls.

Decision: `INPUT_GATE_FAILED`. Recall@4, recall@8 and complete@8 remain below
their frozen thresholds.

## 7. Why more ranking heuristics were the wrong fix

Twenty of 123 evidence roles remained below rank 8. A five-year payment program
can contain five roles that v2 describes identically as `component / none`.
Every role receives the same ranking query, so the system cannot know which
component means 2016 versus 2019. The schema discarded that information.

The rejected v3 heuristic ablation matters: broad local-window bonuses and
diversity penalties reduced recall. That negative result is preserved instead
of tuning until the development result looks good.

## 8. E6-v3 role-conditioned contract

E6-v3 adds bounded planner fields:

```json
{
  "role_query": "expected principal payment 2019",
  "expected_period": "2019"
}
```

The schema rejects candidate IDs, evidence IDs, step IDs, constant IDs and JSON
fragments in `role_query`. Compatibility still accepts only Guard-admitted
operands and never changes candidate identity, value or provenance.

The offline gold-descriptor upper bound reached:

| Metric | E6-v3 upper bound |
|---|---:|
| Role recall@4 | 98.37% |
| Role recall@8 | 99.19% |
| Complete typed case@8 | 98.28% |
| Edge reduction | 73.63% |
| Route accuracy | 100% |

Decision: `UPPER_BOUND_INPUT_GATE_PASSED`.

This is not planner quality. Role descriptions came from gold evidence
descriptors offline, with answer numbers removed. It proves the interface has
enough capacity; it does not prove a model can populate it.

## 9. Next admissible experiment

Freeze a real planner that generates `role_query` and `expected_period` from
the question only. Measure schema validity, period/entity accuracy, candidate
recall@4/@8, complete binding, strict and grounded answer accuracy against B0,
correct-to-wrong regressions, model calls, latency and identity preservation.
Serving remains disabled until that paired experiment passes.
