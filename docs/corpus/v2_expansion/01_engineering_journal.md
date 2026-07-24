# R2-S6 Versioned Corpus Expansion Engineering Journal

Status: local implementation and acceptance complete; remote exact-SHA CI
pending at the time this entry was written

Date: 2026-07-24

This journal records the actual implementation order, RED/GREEN evidence,
mistakes, corrections, and artifact provenance. Later corrections should be
appended or explicitly supersede an earlier statement.

## 1. Baseline audit

The existing source of truth was
`data/v2/facts/company_facts_v1.json`. It contained 8 policies, 16 versions,
32 atomic facts, 7 departments, 10 users, and 10 ACL groups.

The profile audit found:

```text
demo       72 documents; 24 dev / 28 test
benchmark 600 documents; 24 dev / 28 test
```

The active local index before this change was:

```text
run_id       20260716T135632Z_7aec4b9_live_bge_m3_fixed
profile      demo
source docs  72
canonical    64
embedding    bge-m3 / 1024 dimensions
chunker      fixed
```

The key finding was that `benchmark` added volume, not knowledge breadth. This
led to the versioned-facts design rather than another document-count increase.

## 2. Fact model implementation

Created:

- `data/v2/facts/company_facts_v2.json`
- `data/v2/config/expanded.json`
- `data/v2/config/expanded_benchmark.json`

The v2 file begins with all validated v1 content and adds 12 policy families,
24 versions, and 72 facts. The resulting inventory is:

```text
schema       enterprise_facts_v2
policies     20
versions     40
facts        104
active facts 52
departments  12
users        15
ACL groups   15
```

### Mistake: policy objects inserted into `users`

During the first large JSON patch, an ambiguous array boundary caused four
policy objects to be inserted into the `users` array. This was not accepted or
committed. Parsing and count inspection exposed the invalid structure before
generation.

Correction:

1. locate the explicit `user_auditor` / `hr_remote` boundary;
2. restore the `users` closing delimiter;
3. move the policy objects under `policies`;
4. re-run Pydantic parsing and exact inventory counts.

Lesson: large fixture patches need semantic anchors and immediate typed
validation. JSON syntax alone is insufficient because an object can be valid
JSON while belonging to the wrong array.

## 3. Public profile catalog

Created `app/corpus/catalog.py`.

Before this change, profile choices were repeated in multiple CLIs. The
catalog binds each public profile ID to one facts file and one profile file:

```text
demo               -> facts v1 + demo.json
benchmark          -> facts v1 + benchmark.json
expanded           -> facts v2 + expanded.json
expanded_benchmark -> facts v2 + expanded_benchmark.json
```

`scripts/generate_enterprise_corpus.py`,
`scripts/eval_corpus_quality.py`, and
`scripts/build_indexes_v2.py` now use the shared catalog/ID set. This prevents
the generator and index builder from accepting different profile lists.

## 4. TDD slice: profile breadth

RED:

```text
test_expanded_profile_reports_real_knowledge_breadth
CLI return code 2: expanded was not an accepted profile
```

Implementation:

- allow `enterprise_facts_v1` and `enterprise_facts_v2` in
  `app/corpus/schemas.py`;
- add `summarize_fact_inventory` in `app/corpus/artifacts.py`;
- report policy/version/fact/active-fact/department/user/group counts from the
  generation CLI;
- preserve generator version `1.0.0` for v1 and use `2.0.0` for v2.

GREEN: focused test passed.

Compatibility proof: all checked-in v1 generated outputs remained exact.

## 5. TDD slice: active-fact support coverage

RED:

```text
test_expanded_profile_makes_every_active_fact_retrievable_from_supporting_content
```

The old random support-document loop did not guarantee that every active fact
appeared outside the authoritative policy. Increasing the random sample size
would only make failure less likely, not impossible.

Implementation in `app/corpus/generator.py`:

1. for v2 profiles, create a deterministic coverage assignment per policy;
2. generate at least `max(3, active_fact_count)` supporting assignments;
3. cycle source types and formats;
4. cover every active fact before filling remaining slots randomly;
5. fail when a profile cannot satisfy the contract;
6. leave the v1 path unchanged.

GREEN:

```text
active fact support coverage = 1.0
minimum policy source-type count = 3 for expanded
minimum policy source-type count = 6 for expanded_benchmark
```

## 6. TDD slice: deterministic quality gate

RED:

```text
test_expanded_quality_gate_passes_from_the_public_cli
No module named scripts.eval_corpus_quality
```

Implementation:

- `app/corpus/quality.py` computes breadth, coverage, diversity, uniqueness,
  and eval-split metrics;
- `scripts/eval_corpus_quality.py` exposes a stable CLI;
- failed quality checks return exit code 1;
- configuration or filesystem errors return exit code 2;
- passing quality returns exit code 0.

The Windows RED run also showed that a missing Python module reports its error
using the system code page before the script can reconfigure streams. Tests
that intentionally execute missing scripts now use replacement decoding for
stderr; real public CLIs reconfigure stdout/stderr to UTF-8 at startup.

## 7. TDD slice: evaluation question semantics

RED:

```text
test_expanded_completeness_questions_match_the_required_fact_count
IT change policy required 3 fact IDs, but the question said 两项
```

Root cause:

`app/corpus/eval_cases.py::_completeness_cases` hard-coded “两项” because every
v1 active policy had two facts.

Correction:

- add `_item_count_label`;
- derive the label from `len(active.facts)`;
- map 1/2/3 to `一项/两项/三项`;
- retain “两项” for v1, preserving frozen output bytes.

GREEN:

```text
new semantic-count test passed
checked-in v1 output tests passed
```

## 8. TDD slice: index lifecycle admission

RED:

```text
test_index_cli_accepts_expanded_corpus_profiles[expanded]
test_index_cli_accepts_expanded_corpus_profiles[expanded_benchmark]
argparse invalid choice
```

Correction:

- `scripts/build_indexes_v2.py` imports `CORPUS_PROFILE_IDS`;
- `app/config.py` accepts all four profile IDs;
- after live acceptance, the default changed from `demo` to `expanded`.

The default was deliberately changed only after a real expanded index passed
the frozen test set. The historical `demo` profile remains available.

### Default-profile drift found during documentation review

After changing the runtime default, the generation CLI still defaulted to
`demo`. A new user could therefore generate 72 documents and then run an index
builder expecting `expanded`.

RED:

```text
test_generator_defaults_to_the_current_expanded_profile
actual profile: demo
expected profile: expanded
```

Correction: set the generator CLI default to `expanded`. All historical tests
use explicit `--profile demo`, so compatibility behavior remains available and
unambiguous.

## 9. TDD slice: evidence publication

RED:

```text
test_quality_cli_can_publish_a_machine_readable_report
unrecognized arguments: --output
```

Correction:

- `--output` writes the exact stdout JSON bytes as UTF-8 with a final newline;
- existing evidence is refused by default;
- `--force` is required to replace it.

A standalone package under
`data/v2/public/corpus_expansion_v2/` contains quality, index, and live
retrieval summaries. Its verifier checks file set, SHA-256, semantic counts,
model/dimension, split identity, failures, ACL leakage, hit@1, and
document-recall@3.

Tamper regression:

```text
modify quality document_count 240 -> 241
expected result: verifier exit 1, checksum mismatch
actual result: passed
```

## 9.1 Review finding: unused operational ACL group

The first implementation review compared declared ACL groups with all policy
version ACLs. It found:

```text
external_contractors  unused by policy, intentional deny fixture
facilities_ops        unused by policy, unintended
```

The original visitor policy was visible to `all_employees`, so the new
facilities user and group did not exercise a distinct authorization boundary.

RED:

```text
all_operational_acl_groups_are_used = false
unused_operational_acl_group_count = 1
quality CLI exit code = 1
```

Correction:

- exclude only the explicitly denied `external_contractors` fixture from the
  operational-use requirement;
- assign both retired and active visitor-policy versions to
  `facilities_ops`;
- add the new check and metric to the quality report and public verifier.

GREEN:

```text
all_operational_acl_groups_are_used = true
unused_operational_acl_group_count = 0
```

This changed facts, corpus, eval, and index provenance. The first local
expanded build `20260724T023024Z_expanded_bge_m3_fixed` and its first dev/test
runs were therefore marked superseded. The corpus was regenerated, a new
immutable index was built, and both live splits were rerun before publishing
final evidence. The final facts canonical SHA-256 is:

```text
761fd6d2400721bcd669bc3417b4c1d3322d4f179cd584737044805e914c34b1
```

## 9.2 Review finding: incomplete active-fact evaluation coverage

The first quality gate guaranteed document support but did not explicitly
measure whether every active fact appeared in an eval case. A new metric found:

```text
active_fact_eval_coverage = 0.942308
covered active facts      = 49 / 52
missing facts             = finance_invoice approval/payment,
                            hr_leave medical certificate
```

Root cause: the split builder shuffled task buckets, then repeatedly removed
the tail of the current largest bucket until it reached 104 cases. It removed
two policy-level completeness cases. The corresponding atomic fact cases were
also absent, leaving three facts untested.

Correction in `app/corpus/eval_cases.py`:

- define minimum per-task counts;
- for facts v2, preserve all policy-level completeness cases;
- continue balancing the other task buckets;
- retain the original v1 path and exact checked-in bytes;
- fail if a future profile is too small to preserve the coverage contract.

GREEN:

```text
active_fact_eval_coverage = 1.0
every_active_fact_is_evaluated = true
v1 checked-in output tests = passed
new frozen expanded test SHA-256 =
d4c516fcaa9e8dac6474bde69d13f2e95bf9ae4562e91b3fd8d5e90f8ef18c76
```

Only eval bytes changed. The source corpus manifest remained
`5d96338e...fc24e57`, so the final active index stayed valid and was not
rebuilt. New immutable dev/test evaluation runs replaced the previous ACL
runs in the public evidence.

## 10. Actual generation

Expanded profile:

```text
documents by format
  md 114, txt 38, html 42, csv 24, jsonl 22
documents by source
  policy 69, wiki 34, email 39, ticket 50, meeting 24, table 24
documents by variant
  authoritative 40, supporting 133, duplicate 12,
  near_duplicate 19, misfiled 12, stale 24
```

Expanded benchmark:

```text
documents by format
  md 788, txt 405, html 374, csv 199, jsonl 234
documents by source
  policy 270, wiki 439, email 407, ticket 442, meeting 222, table 220
documents by variant
  authoritative 40, supporting 1220, duplicate 160,
  near_duplicate 200, misfiled 140, stale 240
```

## 11. Parser, governance, and chunking

Expanded fixed-chunker dry run:

```text
source documents       240
canonical documents    216
duplicates removed      24
chunks                  216
indexed chunks          216
corpus manifest SHA-256 5d96338e4d637c207c381323fc6919f575983992e553a06f548a7e7e0fc24e57
```

Expanded benchmark dry run:

```text
source documents       2000
canonical documents    1225
duplicates removed      775
chunks                  1225
indexed chunks          1225
corpus manifest SHA-256 833338d8472a1da652134d5b23c100a08cc5e76db785154e8609314b2be1f834
```

The benchmark was not embedded or activated because it has the same 104 facts
as `expanded`. Its purpose is scale and governance testing.

## 12. Real BGE-M3 index

Ollama reported local `bge-m3:latest`, digest
`7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`,
with embedding capability and dimension 1024.

Build result:

```text
run_id          20260724T024653Z_expanded_bge_m3_fixed
profile         expanded
source docs     240
canonical docs  216
chunks          216
embedding       bge-m3 / 1024 / L2
FAISS           IndexFlatIP
duration        40,700 ms
manifest SHA256 69b9fb7d3008467f65fb2920a621e9812cdb59c4919834819333e0e33b866507
activated       true
```

No output for roughly 40 seconds was treated as expected model work, not as a
hang. The process remained alive and completed successfully.

## 13. Live retrieval acceptance

Dev run:

```text
run_id                 corpus_expanded_fullfact_dev_live_20260724
cases                  48 / 48 passed
scored gold cases      32
hit@1                  1.0
MRR                    1.0
document_recall@3      1.0
NDCG@5                 1.0
ACL leakage            0
mean latency           239.86 ms
```

Frozen test run:

```text
run_id                 corpus_expanded_fullfact_test_live_20260724
cases                  56 / 56 passed
scored gold cases      39
hit@1                  1.0
MRR                    1.0
document_recall@3      1.0
NDCG@5                 0.99794
ACL leakage            0
mean latency           156.82 ms
```

The frozen test hash was verified before execution. This is a local synthetic
regression result, not a production or unseen-domain generalization claim.

## 14. Current verification commands

```powershell
.\.venv\Scripts\python.exe -m scripts.eval_corpus_quality --profile expanded
.\.venv\Scripts\python.exe -m pytest tests\corpus -q
.\.venv\Scripts\python.exe data\v2\public\corpus_expansion_v2\verify.py
```

CI now runs the expanded quality gate on both Ubuntu and Windows before the
full deterministic test suite.

Final pre-commit local gates:

```text
corpus + indexing            92 passed
full pytest                  1939 passed / 22 skipped / 3 warnings
compileall                   passed
pip check                    no broken requirements
public repository audit      534 candidates / 0 findings
public evidence verifier     verified=true
git diff --check             passed; one CRLF-to-LF notice for .env.example
```

The three warnings are the existing FAISS SWIG deprecation warnings. They are
not corpus failures.

Exact-SHA GitHub Actions run #20 accepted evidence commit
`6c419b13ce5751943403a7e2c031de1d3acbc08e`:

```text
run                    30064875678 / success
Ubuntu job             89393769125 / success
Windows job            89393769131 / success
expanded quality gate  success on both platforms
```

Run URL:
https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/30064875678

The unauthenticated GitHub API exposes job conclusions but not job logs or
pytest text, so no platform-specific pass count is inferred here. Local
`1939/22/3` and remote job success are intentionally recorded as different
evidence types.

## 15. Independent review and evidence-chain hardening

A read-only independent reviewer challenged the first release candidate. The
findings and dispositions were:

1. The public package did not bind facts, profile, generated corpus, index,
   frozen datasets, evaluation summaries, and source code into one chain.
   Fixed with `manifest.json`, exact SHA-256 bindings, and implementation
   baseline commit `184913e5e504b150d3959ae541cc808544ac379e`.
2. The first quality command regenerated a corpus in memory but did not prove
   that the materialized corpus used by indexing matched it. Fixed by parsing
   every generated file and requiring exact preset/manifest equality in both
   the quality and index CLIs.
3. The public verifier accepted extra fields and its tamper test only detected
   a stale checksum. Fixed with exact field sets, a frozen release contract,
   cross-artifact hash checks, and tests that alter semantics, update the
   manifest hash, regenerate all checksums, and still expect rejection.
4. The generator assumed every retired version had two facts, while the schema
   did not require a retired version. Fixed by requiring one active plus at
   least one retired version and iterating over the actual retired fact count.
5. Operational ACL use was counted across retired content. Fixed so the gate
   requires every operational group to protect active content.
6. Full v2 byte determinism and undersized-profile failures were insufficiently
   covered. Fixed with whole-artifact same-seed tests, single-fact retired
   coverage, missing-retired rejection, and explicit capacity failure tests.

The live dev/test manifests honestly report that they were captured from dirty
worktree head `e657beaf7d184409b2d7574c974733cbd7233f4e`. The two-commit closeout
therefore uses `184913e` as a reviewed post-run implementation snapshot. It
does not relabel the earlier live run as a clean-checkout run.

During checksum regeneration, Windows PowerShell 5 wrote a UTF-8 BOM because
`Set-Content -Encoding utf8` has platform-specific behavior. The standalone
verifier rejected the first row and two focused tests failed. The checksum
file was rewritten as UTF-8 without BOM through the repository patch path;
the verifier and all five evidence tests then passed. This was an artifact
encoding failure, not a retrieval regression.

## 16. Deferred work

- human review of generated prose and answer usefulness;
- real enterprise document connectors and legal/privacy approval;
- OCR/PDF/DOCX realism expansion;
- measured incremental update/delete workload;
- production deployment and durable telemetry;
- independent-domain evaluation that is not generated from the same facts.
