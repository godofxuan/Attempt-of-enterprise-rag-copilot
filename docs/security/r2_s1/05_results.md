# R2-S1 Results

Last updated: 2026-07-17

## 1. Current Evidence Status

```text
phase                                  D3 STANDALONE GUARD CORE GREEN
D3 entry HEAD                          c1c47dfe88c42c309afc32faa9bc6584e90e89ac
RetrievedContentGuard                  IMPLEMENTED, NOT RUNTIME-INTEGRATED
full 72-case security evaluation       NOT RUN
local Qwen/BGE-M3 security evaluation  NOT RUN
```

D2 is intentionally not a release pass. It records the vulnerable data flow before
the Guard exists, so later D3-D5 changes must turn the relevant red tests green
without weakening the already-green trace and no-egress boundaries.

Because no Guard class existed at the D2 baseline, the test names use `guard_off` to
mean the current unguarded path that the later evaluator's explicit OFF dependency
injection must reproduce. No production setting was switched off.

## 2. What Was Added

| File | Purpose |
|---|---|
| `tests/security/test_indirect_injection_red_baseline.py` | prompt propagation, fake-generator canary, raw Search/Open boundary, trace and no-egress probes |
| `tests/retrieval/test_indirect_injection_red_baseline.py` | real `HybridRetrievalPipeline` top-1 poison displacement probe |
| `.private/r2_s1/d2_red_baseline.txt` | ignored raw pytest output; not published because it contains local paths and complete synthetic payloads |
| `.private/r2_s1/d2_control_regression.txt` | ignored output for the existing control suite |

No production code, model setting, API route, R1 dataset, real side-effect tool or
external target was added. All attack strings and canaries are synthetic.

Ignored evidence identity:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `d2_red_baseline.txt` | 41,996 | `050a61b114ce555830f33184de42e2f270125602f35cb65bd546e623d73d649b` |
| `d2_control_regression.txt` | 1,428 | `02f60b0041614fdf0d1a5c31a32cea4f2e66cbc2df3f79225065b7c5d4bf97eb` |

## 3. Test Command and Actual Result

```powershell
.\.venv\Scripts\python.exe -m pytest -vv `
  tests\security\test_indirect_injection_red_baseline.py `
  tests\retrieval\test_indirect_injection_red_baseline.py
```

Actual result:

```text
collected 8
failed    5
passed    3
duration  1.03 s
```

The five failures are expected RED assertions. They are not flaky infrastructure
errors: each assertion reached the intended production data path and exposed the
specific missing security boundary.

## 4. Failure-by-Failure Explanation

### 4.1 Retrieved text reached the generation context

Test:

```text
test_guard_off_attack_unit_does_not_reach_generation_context
```

The test inserted a synthetic policy fact, an instruction-override string, a
document canary, an inert `.invalid` URL and a trace marker into `SearchHit`, plus
an attack string in `OpenResult`. It then used the real
`GenerationV2ResponseBuilder` with only the network/model call replaced by an
in-memory capturing fake.

Expected future behavior: neither attack text nor canary reaches model messages.

Observed behavior: the captured user message contained the canary in all three
current evidence fields:

```text
SearchHit.matched_text
SearchHit.context_text
OpenResult.content -> authorized_document_context
```

Code path proved by the failure:

```text
ControllerState.evidence_by_aspect/open_results
-> generation_v2._build_prompt_sources
-> generation_v2._generation_messages
-> chat_fn(messages)
```

The current system prompt says evidence is untrusted, but that is a model-level
instruction, not a deterministic isolation boundary.

### 4.2 The deterministic fake generator exposed the document canary

Test:

```text
test_guard_off_fake_generator_cannot_expose_document_canary
```

The fake generator is deliberately programmed to return the document canary only
when it sees both the attack trigger and canary in its input messages. The real
generation parser, source-ID mapping, citation verifier and `AnswerResponse`
construction then processed that output.

Observed response fields containing the canary included:

```text
answer
claims[0].text
sources[0].preview
```

The citation verifier reported lexical support `1.0`, because the malicious canary
was present in the cited retrieved evidence. This demonstrates why citation
presence alone cannot classify retrieved content as trustworthy.

This test proves deterministic propagation and output acceptance only. It does not
measure Qwen, any other live model, or a real-world attack-success rate.

### 4.3 Raw SearchResult reached Controller.observe

Test:

```text
test_controller_rejects_raw_search_execution_before_ledger
```

The desired D1 contract requires a runtime `TypeError` when raw execution is passed
to `Controller.observe`. The current call raised nothing, so pytest reported:

```text
Failed: DID NOT RAISE <class 'TypeError'>
```

The path is therefore still:

```text
V2ToolRegistry.run
-> V2ToolExecution(result=raw SearchResult)
-> V2AgentController.observe
-> evidence_by_aspect
-> EvidenceLedger
```

Python type hints do not stop this path because `observe` currently declares and
accepts `V2ToolExecution` itself.

### 4.4 Raw OpenResult reached Controller state

Test:

```text
test_controller_rejects_raw_open_execution_before_state
```

The same runtime rejection was expected for an `open` execution. Nothing was
raised, proving that raw `OpenResult.content` can be appended to
`ControllerState.open_results`. Generation later reads that content through
`_open_context_for_doc`.

### 4.5 A top-ranked poison displaced clean evidence

Test:

```text
test_top_ranked_poison_is_quarantined_and_clean_candidate_is_recovered
```

This test uses the real dense-ranking path with a fixed two-item vector snapshot:

```text
candidate_k = 2
top_k       = 1
rank 1      = top-ranked-poison
rank 2      = clean-recovery-candidate
```

The pipeline reported two dense candidates but returned only:

```text
['top-ranked-poison']
```

The assertion expected the clean candidate and failed. This proves the current
pipeline applies `top_k` before any security quarantine, so later code cannot
recover rank 2 from the returned `SearchResult`. D4 must place quarantine and
bounded fill between the ranked candidate pool and admitted top-k selection.

## 5. Existing Boundaries That Passed

### 5.1 Public trace remained aggregate-only

`test_public_trace_excludes_retrieved_raw_text` passed. The response trace did not
contain the document canary, trace canary or attack trigger. This matches the
current aggregate step schema.

This does not make the overall response safe: the extractive answer can still copy
retrieved text while the separate `trace` field remains clean.

### 5.2 The egress harness blocked before transport

`test_egress_blocker_intercepts_before_transport` passed. The fixture patches both
the `requests` session boundary and direct socket connection boundaries. Its
calibration request used the reserved `.invalid` domain and was intercepted in
process before DNS, socket creation or packet transmission.

### 5.3 Inert attack text caused no network call

`test_inert_egress_instruction_causes_no_network_with_fake_chat` passed. Merely
placing an inert URL and send instruction in retrieved text did not create a tool
or network capability when the chat function was a pure in-memory fake.

This result is consistent with the current read-only tool allowlist. It is not a
claim that an arbitrary future tool registry would be safe.

## 6. Control Regression

The pre-existing implementation tests were run separately so the intentional D2
failures did not hide an accidental regression:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests\agent_v2\test_generation_v2.py `
  tests\agent_v2\test_controller_v2.py `
  tests\agent_v2\test_runner_v2.py `
  tests\retrieval\test_pipeline_ranking.py
```

Actual result:

```text
36 passed, 3 known FAISS warnings, 0 failed, 0.82 s
```

Repository-scope closeout checks:

| Check | Result |
|---|---|
| public repository audit | `348 candidates, 0 findings` |
| repository/audit regression tests | `14 passed, 3 known FAISS warnings` |
| `git diff --check` | exit `0` |
| unfinished/sensitive marker scan | `0 findings` |
| tracked changes under `app/`, `data/`, `scripts/` | none |
| R1 dev/test/manifest SHA-256 | exact D1 frozen values |

R1 hashes rechecked after the D2 run:

```text
data/v2/eval/dev.json
  92b4753df4e69bb570e9ea202420b46124207f15a07cdbb421fb00e6990082bd
data/v2/eval/test.json
  556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338
data/v2/eval/test_manifest.sha256
  fc9151daee0d6a0ac1ecfd1b6a3e361bc985d3f8512a8bc76927528ecd32f253
```

## 7. What D2 Does and Does Not Establish

Established:

- current selected retrieved text reaches the generation model context;
- a deterministic compliant fake can propagate that content into a valid response;
- raw Search/Open executions are accepted by Controller at runtime;
- current pre-Guard top-k selection can discard a clean recovery candidate;
- the current public trace and tested no-egress boundary are already green.

Not established by D2 alone:

- no detector or Guard existed at that baseline;
- no malicious/benign 72-case dataset has run;
- no Guard OFF/ON metric has been computed;
- no Qwen/BGE-M3 live security trial has run;
- the project cannot yet claim retrieved-content injection defense.

## 8. Expected Green Owner

| Red test | Expected implementation phase |
|---|---|
| prompt/context propagation | D4 integration, reinforced by D5 prompt boundary |
| fake-generator canary response | D4 admitted-only data flow, reinforced by D5 |
| raw Search/Open acceptance | D4 guarded runtime type boundary |
| top-1 poison displacement | D4 bounded candidate fill after quarantine |
| detector rules and false positives | new D3 Guard-core unit tests |

D3 alone is not expected to turn all five D2 failures green because D3 builds the
detector core; D4 is the phase that connects it to retrieval and Controller.

## 9. D3 Standalone Guard Core

### 9.1 Code ownership

| File | D3 responsibility |
|---|---|
| `app/domain/retrieved_security.py` | strict immutable `GuardDecision`, fixed categories, exact rule/category/severity allowlist and resource invariants |
| `app/security/retrieved_content.py` | bounded deterministic scanner, normalization views, rule matching, Base64 handling and fail-closed boundary |
| `app/security/__init__.py` | stable package exports for `RetrievedContentGuard` and `RULE_SET_SHA256` |
| `tests/security/test_retrieved_content_guard.py` | 64 schema, malicious, benign, obfuscation, resource and failure tests |
| `docs/superpowers/plans/2026-07-17-r2-s1-d3-guard-core.md` | test-first D3 execution plan and D4 deferrals |

No retrieval, Controller, generation, API, index, R1 dataset or model code was
changed. The Guard receives one text object and returns content-free diagnostics.

### 9.2 Decision contract

`GuardDecision` uses Pydantic strict mode, `frozen=True`, immutable tuples and an
exact detector-version literal. A caller cannot mutate an admitted decision after
validation, pass numeric strings, invent an `RCG-*` ID, or pair a rule with the
wrong category/severity. The model derives the only valid disposition from the
strongest allowlisted rule:

```text
no rules                         -> ADMIT / none
observe-only rules               -> ADMIT / observe
any quarantine rule             -> QUARANTINE / quarantine
RCG-GUARD-ERROR alone            -> QUARANTINE / error
```

The exact fail-closed object has no raw/normalized/decoded text field.

### 9.3 Detection pipeline

```text
immutable original text
-> source bound: 14,000 prefix + 6,000 suffix when over 20,000
-> NFKC and casefold ephemeral views
-> preserve normalized prefix and suffix if Unicode expansion exceeds 20,000
-> remove all Unicode category Cf controls from comparison/Base64 views
-> limited Cyrillic confusable translation
-> action + target/role/context rule combinations
-> markup annotation only when a risky directive is already present
-> at most 8 strict Base64 candidates, one decode level, max 3,072 bytes
-> immutable ADMIT/QUARANTINE decision
```

Plain `SYSTEM`, `upload`, a URL, markup, Base64, or a quoted training phrase is not
enough by itself. The scanner is deterministic and makes no LLM, embedding, tool
or network call.

### 9.4 Resource and failure behavior

- source and normalized views are each bounded to 20,000 characters;
- Base64 candidates are 16..4,096 encoded characters with printable threshold
  calculated over decoded bytes;
- each regex family is capped at 256 matches and paired with a linear two-pointer
  algorithm instead of a Cartesian product;
- malformed input, internal exceptions and rule-budget exhaustion return the
  exact content-free `RCG-GUARD-ERROR` quarantine decision;
- decoded content is never recursively searched for another Base64 payload and is
  never decompressed.

## 10. TDD and Review Findings

The implementation was built as observable RED/GREEN slices: missing schema,
missing atomic scanner, Base64 handling, resource bounds, fail-closed behavior,
Unicode/markup variants, package exports and decoded-byte threshold semantics all
failed first and then passed.

An independent read-only code review then found six issues before closeout:

| Finding | Why the first implementation was unsafe | D3 correction |
|---|---|---|
| NFKC expansion clipped one side | a suffix directive could leave the normalized view | normalized overflow now preserves separate 14k/6k ends |
| quote test used nearest quote characters | text between two unrelated quoted phrases could be mislabeled descriptive | only balanced unescaped enclosing pairs suppress a marked training example |
| hand-written control set was incomplete | U+2063 and LRM/RLM could split a directive; controls could split Base64 | all Unicode `Cf` controls are annotated and removed only in ephemeral comparison views |
| Cartesian rule pairing | repeated signals could cause quadratic CPU/memory growth | bounded match lists plus linear two-pointer pairing; overflow fails closed |
| mutable/coercive decision model | a validated decision could be mutated or accept invented rule/version values | strict frozen model, tuples, exact version and static rule mapping |
| incomplete rule hash | security semantics could change without provenance changing | hash now covers Unicode DB, control/bidi policy, regex flags, windows, limits and rule mappings |

The reviewer regressions first produced `13 failed / 51 passed`; after correction,
the Guard file produced `64 passed` in `0.14 s` on the local machine.

## 11. D3 Actual Verification

```text
Guard core unit tests                         64 passed, 3 warnings
security regression excluding D2 RED          84 passed, 3 warnings
agent/retrieval regression excluding D2 RED  116 passed, 3 warnings
full regression excluding D2 RED             638 passed, 3 warnings
D2 integration probes unchanged                5 failed / 3 passed
```

All warnings are the existing FAISS SWIG deprecation warnings. The D2 rerun is
stored in ignored `.private/r2_s1/d3_d2_red_unchanged.txt`; it remains red because
D3 deliberately does not alter runtime data flow.

Ignored raw evidence identity:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `d3_guard_core.txt` | 1,428 | `461d7a1936691db0bed7be01f547315af96b04faf27178735d3508f351c7a40b` |
| `d3_full_regression.txt` | 2,728 | `2cdad99d8bf49ba6ab5253ab1968177bfb6dc4a409b5d67983e3c11f11ecdca3` |
| `d3_d2_red_unchanged.txt` | 18,974 | `6514bebc58b79e085b03591b306e317a4b868eb918a6a2954d5766749723ee64` |

Closeout checks:

| Check | Result |
|---|---|
| public repository audit | `352 candidates, 0 findings` |
| repository/config tests | `14 passed, 3 known FAISS warnings` |
| compileall for D3 code/tests | exit `0` |
| R1 dev/test/manifest SHA-256 | exact frozen values from D1/D2 |

Detector identity:

```text
detector_version  rcg-v1.0.0
rule_set_sha256   a544f013e5570b24488220b3ba11c721a2c6e05b2a4895b027dd0601363bbdb0
```

## 12. What D3 Establishes and Defers

Established:

- deterministic per-text classification with immutable, content-free decisions;
- bounded Unicode, role, secret, egress, markup and one-level Base64 checks;
- fail-closed behavior for malformed input, internal errors and rule saturation;
- benign quoted-training and ordinary operational examples in the unit fixture
  remain admitted;
- no regression in the existing suite when the intentional D2 files are excluded.

Deferred to D4 or later:

- no raw `SearchResult`, `FindResult` or `OpenResult` is guarded yet;
- Controller still accepts raw executions and generation still sees selected raw
  evidence;
- quarantine does not yet recover clean candidates after top-k displacement;
- same-document adjacent split aggregation needs authorized document/order context
  and is therefore a D4 concern, not a single-string D3 scanner feature;
- the frozen 72-case OFF/ON evaluator and local Qwen/BGE-M3 run remain `NOT RUN`.

The project still cannot claim end-to-end retrieved-content injection defense.

## 13. Next Approval Gate

```text
批准D3，执行D4数据流接入与能力约束
```
