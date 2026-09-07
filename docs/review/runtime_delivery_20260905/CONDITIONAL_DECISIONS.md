# Runtime Conditional Decisions

Date: 2026-09-07. Bounded sidecar delivery for plan sections 15-17.
This is not RC6 API acceptance or completion of the whole delivery plan.
The main executor owns the real API 40-scenario harness and Q2.

## Decisions

| Item | Decision | Evidence and boundary |
|---|---|---|
| Q1 capacity diagnosis | Completed; selector candidate `REJECTED` as a drop-in | Sparse visible-set microbenchmarks reduce work, but Top-20 boundary ties change returned IDs. No retrieval changes or promotion. |
| Q3 parse coverage | Completed; parser/chunker change `NOT_JUSTIFIED` | Recorded empty-page warnings and missing table structure are measured. No authorized raw-fact/parsed-fact paired failure establishes a repair target or recovered question. |
| Q4 retry | Historical default assessor `REJECTED`; new retry `NOT_JUSTIFIED` | Existing 76/105 false retries; no new online trigger or independent development protocol. No rerun. |
| Q5 independent confirmation | `BLOCKED_INPUT` | No verified unused, label-compatible, permitted cohort in reviewed exposure records; real human review also not supplied. Frozen labels untouched. |

`REJECTED` means an evaluated candidate has negative evidence, not that every
future implementation is impossible. `NOT_JUSTIFIED` means the implementation
trigger has not been demonstrated. `BLOCKED_INPUT` means required inputs or
authorization/review are absent or unverified, not that quality passed.

## Reproduction

Only these source files were created by this sidecar:

- `scripts/diagnose_runtime_assets.py`
- `tests/evaluation/test_runtime_asset_diagnostics.py`
- this document

No edits to `app/`, existing scripts, configuration, retrieved admission,
indexes, datasets, or frozen labels. No downloads, installation, LLM calls,
embedding calls, GPU inference, commit, or push. All generated files are on D
under `.private/runtime_delivery/diagnostics`. The script refuses output
outside that directory and refuses overwriting an existing result.

Executed from the repository on D with its existing `.venv`:

```powershell
New-Item -ItemType Directory -Force .private/runtime_delivery/diagnostics
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:TEMP=(Resolve-Path .private/runtime_delivery/diagnostics).Path
$env:TMP=$env:TEMP
& .\.venv\Scripts\python.exe -X utf8 -B -m scripts.diagnose_runtime_assets --assets --output .private/runtime_delivery/diagnostics/assets_final.json
foreach ($n in @(10000,50000,100000)) {
  & .\.venv\Scripts\python.exe -X utf8 -B -m scripts.diagnose_runtime_assets --scale $n --output ".private/runtime_delivery/diagnostics/capacity_${n}_final.json"
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& .\.venv\Scripts\python.exe -X utf8 -B -m pytest tests/evaluation/test_runtime_asset_diagnostics.py -q -p no:cacheprovider --basetemp .private/runtime_delivery/diagnostics/pytest_final --junitxml .private/runtime_delivery/diagnostics/tests_final.xml
& .\.venv\Scripts\python.exe -X utf8 -B -m scripts.diagnose_runtime_assets --production-coverage --output .private/runtime_delivery/diagnostics/production_coverage_final.json
& .\.venv\Scripts\python.exe -X utf8 -B -m pytest tests/evaluation/test_runtime_asset_diagnostics.py -q -p no:cacheprovider --basetemp .private/runtime_delivery/diagnostics/pytest_production_final --junitxml .private/runtime_delivery/diagnostics/tests_production_final.xml
& .\.venv\Scripts\python.exe -X utf8 -B -m scripts.diagnose_runtime_assets --help
& .\.venv\Scripts\python.exe -X utf8 -B -m ruff check scripts/diagnose_runtime_assets.py tests/evaluation/test_runtime_asset_diagnostics.py --no-cache
```

All final commands exited 0. Latest tests: **23 passed**, three existing FAISS
SWIG deprecation warnings, no skips (22 before the production-coverage addition).
Choose new output names and a new pytest
basetemp on reproduction; final artifacts are intentionally not overwritten.
Each scale executes in a separate, sequential process, freeing its index before
the next allocation. The four external-assets/capacity measurements use one
identical producer hash. A subsequent coverage-only CLI addition has a new
producer hash; no timing was repeated after the main executor's service-eval
resource notice.

## Q1 Measurements

Environment: Python 3.11.9, NumPy 2.4.4, FAISS 1.13.2, Windows build 26200;
12 logical CPUs, FAISS threads explicitly 1. OMP/OpenBLAS/MKL environment
threads were each 1. Other host activity was not isolated.

All vectors are dimension 1024, float32. Synthetic seed: 20260905. The
diagnostic fills a single preallocated FAISS flat IP storage view in blocks;
it does not construct a second full matrix or save a synthetic index.
Vector storage plus the conservative 4 MiB fill allowance must be below
512 MiB. Preflight requires available memory of twice vector storage plus
64 MiB scratch and a 1 GiB resident margin; otherwise it records
`BLOCKED_RESOURCE` without allocating the index.

At 100k, vector storage was 409,600,000 bytes (390.625 MiB), preflight required
1,960,050,688 available bytes, and measured availability was 17,273,274,368
bytes. Process peak working set after search was 535,580,672 bytes
(510.77 MiB, **whole process**, not vector storage); 16,719,757,312 bytes
remained available. No OOM or disk-backed full-vector workaround. This does
not establish a safe multiworker service capacity or license larger scales.

The reference reproduces `_rank_dense`'s full FAISS ranking then visible-ID
filter loop. The single candidate uses the same exact index with
`IDSelectorBatch` and Top-20. Visibility is synthetic strided membership,
not real users or ACL authorization tests. Both paths include their own
set/selector construction. Result slots are N vs 20; native selector state
and Python allocation costs are not reduced to those slot counts.

One seeded synthetic query, one warm-up per arm and visibility, nine timed
counterbalanced pairs per row; p95 is NumPy's percentile over those nine
repetitions. These are warm CPU microbenchmark timings, **not service p95**,
query-population statistics, retrieval quality, or end-to-end savings.

| Index | Visible | Full/filter p95 ms | Selector p95 ms |
|---|---:|---:|---:|
| Synthetic 10,000 | 100% | 2.796 | 2.715 |
| Synthetic 10,000 | 10% | 2.206 | 0.375 |
| Synthetic 10,000 | 1% | 1.976 | 0.102 |
| Synthetic 50,000 | 100% | 14.099 | 13.262 |
| Synthetic 50,000 | 10% | 11.432 | 2.767 |
| Synthetic 50,000 | 1% | 10.507 | 0.411 |
| Synthetic 100,000 | 100% | 33.697 | 30.976 |
| Synthetic 100,000 | 10% | 25.447 | 5.967 |
| Synthetic 100,000 | 1% | 25.251 | 1.053 |
| Existing WixQA 11,975 | 100% | 2.885 | 2.673 |
| Existing WixQA 11,975 | about 10% (1,198) | 2.445 | 0.451 |
| Existing WixQA 11,975 | about 1% (120) | 2.399 | 0.131 |

The 108 timed pairs above had zero ordered-ID mismatches and zero score
error for this query. This is deliberately not reported as general semantic
equivalence: a separate synthetic 32-vector all-tied case at K=20 returns
IDs 31..12 from full ranking, but 19..0 from selector Top-20. Top-1 also
differs on a four-vector fixture. The candidate therefore fails the plan's
tie requirement despite favorable sparse timings. No Top-200-before-ACL
approximation, ANN, mapping optimization, or second candidate was introduced.

Tests cover empty/sparse sets, ties, K exceeding visible count, and fresh
index-object isolation. The latter is not an activation/rollback lifecycle
test; actual service version switching remains owned by RC3. There is no
same-harness estimate of the dense step's fraction of total request cost.
Document navigation/mapping latency is `NOT_MEASURED` in this bounded sidecar.

## Q3 Coverage

Inputs are existing persisted records, not a new PDF ingestion or reindex.
JSON arrays are streamed with a 16 Mi-character record-buffer limit, and
JSONL is read line-by-line. No record text, warning message, source document
ID, page number, or text-derived boundary hash is emitted.

| Scope | Measured recorded structure |
|---|---|
| Current production documents (`data/indexes_v2`) | 216 canonical records: 99 Markdown, 38 HTML, 35 TXT, 23 CSV, 21 JSONL; 0 recorded warnings; 44 structured tables with nonempty headers |
| Current production structure | 309 sections (233 line and 76 paragraph locators); 216 fixed chunks, all character-located, 0 dedicated table chunks; no PDF records in this sample |
| FinanceBench documents | 84 PDF records, one parser-name hash; 15 documents with 65 `empty_page` warnings; 69 without recorded warnings |
| FinanceBench pages | 12,013 distinct per-document recorded page locators: 11,948 nonempty text pages plus 65 empty-page warning pages; no internal page-number gaps |
| FinanceBench tables | 0 persisted structured tables; 0 table chunks |
| FinanceBench chunks | 29,335 PDF chunks, all page-located, no empty chunk text |
| Repeated boundary candidates | 74 documents; 5,574 occurrences of repeated first/last nonempty lines (at most 160 characters, repeated at least three times per document and position) |
| WixQA chunks | 11,975 nonempty text records; format, page locator, parser/warning schema and structured-table provenance absent from this flat schema |

Production coverage resolves the existing active pointer to
`20260724T024653Z_expanded_bge_m3_fixed`, verifies its manifest hash and each
record artifact hash, and rechecks the pointer and consumed records after
counting. The manifest reports 240 source documents, 24 duplicates and 216
canonical documents. Zero dedicated table chunks despite 44 document tables
is a structural observation, not proof that fixed chunks lost table facts.
Table-cell/header retention remains unverified. The separate 29-document
`.private/runtime_delivery/service_assets_v4/indexes` acceptance fixture was
not read, modified, or confused with production. This extra coverage command
does no FAISS search or index loading; the two record files total 847,943 bytes.

Repeated boundary candidates are only a heuristic: a legitimate repeated
heading or body line can match. They do not prove harmful headers/footers or
justify stripping content. The 69 records without warnings are not certified
fully usable. Likewise, no internal page-number gaps does not prove that
the source PDF's trailing pages or every original fact were captured.

**Unknown / not measured:** raw PDF page denominator, failed imports absent
from the index, scan prevalence, OCR recovery, table fact recoverability,
cross-chunk header/unit retention, and confirmed header/footer-induced loss.
The inspected PDF parser explicitly disables OCR and emits no structured
tables. CSV/JSONL structured records in production are not evidence of PDF
table extraction or DOCX/XLSX coverage; no all-format production claim is made.

The historical FinanceBench 1/31 parser-risk signal is a different
question-level diagnostic, not interchangeable with today's 15/84 documents
or 65 page warnings. No raw target facts or gold labels were inspected in
this sidecar. Thus no `PARSE_LOSS`/`CHUNK_LOSS` per-question repair cohort has
been proved. Q3 changes remain `NOT_JUSTIFIED`; OCR dependencies, raw-fact
inspection, and a versioned paired repair protocol would be separate work.

## Q4 Existing Negative Evidence

Reviewed `docs/adaptive_retrieval_v3/ASSESSOR_RESULTS.md` and the existing
public run-1 summary; **no model rerun**. Historical three runs each had
TP=85, FP=76, FN=9, TN=29 among 199 parseable assessments, plus one unavailable
output. False retry = 76/(76+29) = 72.38%, not 76/200. The 200-question
ExpertWritten cohort is consumed development evidence, not fresh validation.

`FINAL_DECISION.md` also preserves negative S1/S2 diversity and S5 addendum
results. Corrected Oracle recovery does not provide a permissible online
trigger. No new post-packet `CANDIDATE_MISS` subset with an online-safe
discriminator and independent development protocol was supplied here.
Keep the old assessor rejected and a new rewrite/retry `NOT_JUSTIFIED`.
This does not prejudge the main executor's current per-stage API results.

## Q5 Input Feasibility

This is a human-reviewed public-ledger feasibility snapshot bound to the
hashes in `assets_final.json`, not an automated per-question consumption or
license audit. The script records that decision and hashes those sources;
it does not infer freshness from file existence or open QA datasets.

| Reviewed cohort/source | Feasibility |
|---|---|
| V3 `DATASET_LEDGER.md`: WixQA Synthetic 6,221; Simulated 200; ExpertWritten 200 and multidocument subset | Explicitly consumed development; variants are not new confirmation |
| FinanceBench | Per-question consumption history incomplete in ledger; `UNKNOWN` is not certified unused |
| EnterpriseRAG-Bench | Compatible QA labels/protocol and exposure history unverified; corpus size is not a cohort |
| FinQA E18 protocol | Internal cohort `CONSUMED_NOT_ACCESSED`; frozen test `UNTOUCHED`, but numeric/program task and existing protocol do not authorize repurposing it for this runtime comparison |
| Original UDA page protocol and R5 journal | Original frozen test consumed; R5 used all 41 remaining companies/192 questions after prior rounds consumed 96 eligible companies. Not an unused-company reserve now |
| Quality `CODEX_HANDOFF.json` | Recorded `G5_READY_FOR_TWO_HUMANS_NOT_RUN`; synthetic 12-item calibration is not independent; no new completed double-human review supplied |

No verified unused compatible cohort was established: `BLOCKED_INPUT`.
Missing inputs are a documented unused question/company/document cohort with
compatible target labels, consumption/deduplication audit, permitted access
and a frozen independent protocol; human quality claims additionally require
real reviewers and actual ratings. UDA has a recorded CC-BY-SA-4.0 license,
but its reviewed population is consumed. Other possible populations' license
and access suitability were not newly established. No claim that no fresh
data exists anywhere; no external search or downloads were performed.

## Artifacts And Failures

Final generated artifacts (all private; hashes measured from exact bytes):

| Filename under `.private/runtime_delivery/diagnostics` | SHA-256 |
|---|---|
| `assets_final.json` | `a2a60dfb24f00a2dfc5dffcf7af12ff732ee55fcc28ca8d8bbb74976f1163208` |
| `capacity_10000_final.json` | `aa87f3b10fb5695b1eabd27ac8f0bb974b3615f45cb8ff5635b456073baee769` |
| `capacity_50000_final.json` | `f43cb504d3d678e970eae0968412b174d6dede27e42a2827d534f7891645320d` |
| `capacity_100000_final.json` | `9e24a4b2dda0bc5e97316a3272514cbefeebc3a78ee45271ef6aa0fc05269515` |
| `tests_final.xml` | `c3fdd8ec89971e19e4a4f29b580afe3ffdaac811afc0117c1d768dd8a996130b` |
| `production_coverage_final.json` | `29385b1b82104c9a53fb3a6dbb2de0490301bc36d610ba5b61467a962afe7c43` |
| `tests_production_final.xml` | `c67a10c2e1148f1c1c33a5c828d1084233d23ce34fb09c77937e31decea8fab8` |

External-assets/capacity producer `scripts/diagnose_runtime_assets.py` SHA-256:
`9843960c9445b346aa8b359ea920da28d937b59a1d94f514e397227078deb834`.
Latest script after the production-coverage-only addition:
`88a3d21c979eb75cea6f78ea890ebb45b363674f6fb90ee4cd288d8bb2b410a3`.
Each JSON stores its command arguments, environment versions and producer
hash. `assets_final.json` additionally binds all five consumed index files,
eight public decision/exposure artifacts, dense pipeline source and PDF
parser source. Input byte hashes include:

- FinanceBench documents: `d4fe6497cfea162a12fc7ccabda0e7d2c26b9ca726285e1a04432bc523ac5eca`
- FinanceBench chunks: `abeca919cc0f24903235543fb77b0cfc55c5303d239188123f0d032ac39c74ce`
- WixQA chunks: `0ca1e6191710846fe1ef583f9f7f433dbe06d016bc39ceefdc18a83931fd526e`
- WixQA index: `fe4afe8c1ab31dee3f47e11695139c56eebc06f344b99028b16fb42dd0ce2976`
- V3 exposure ledger: `a350274b876e62ab86107ac93aa28517529ecc8f64a3e214434a959103252064`
- Historical assessor summary: `728ef147eba840bcbaa79660cff01269d0da79ee3bfc7b631f0fcfc1877de45a`
- Production active pointer: `1bc3e9492a4af7a641d464c8de7334e6c1d062110dcf18c7f8bec97dda3ef1df`
- Production documents: `40740bae3bbfe700d6c6211793a25d7ad1164e9109d0c9b9173d115e6e21af05`
- Production chunks: `28d6d7c3707ee3e36d71c7fc148c75a88eff01ff23ad3f7c34669732a404bf46`

Retained development failures and reruns:

1. Initial test run: exit 1, 15 passed, one true Top-1 tie-equivalence failure,
   six setup errors because the diagnostics parent directory did not yet
   exist. `tests_v1.xml` retains the failure. Directory preparation fixed
   setup; the tie difference was preserved as a known-negative assertion,
   not hidden by changing retrieval semantics.
2. First `--assets --output .../assets_v1.json` attempt: exit 1 at FAISS's
   narrow-character absolute-path file reader in the Unicode workspace.
   Python could hash/read the same file; `PyCallbackIOReader` successfully
   loaded it unchanged. A Unicode-path regression test covers the fix.
   No partial assets-v1 result was emitted.
3. `tests_v2.xml` (19 passed), `assets_v2.json` and `capacity_*_v1.json` remain
   development records. The final run follows the added page/boundary counts,
   Top-20 tie probe and Unicode-reader tests, with one final producer hash.
   No thresholds or decisions were tuned against timing reruns.
4. A broad filename inventory crossed historical test ACL-denied directories;
   those access errors were not bypassed. Subsequent inspection used only
   the explicit asset roots above. Ruff initially found formatting/import
   issues in the new files; final check passed.

This closes the four assigned conditional diagnoses/decisions only. It does
not claim full API quality, generalized retrieval equivalence, parser fact
completeness, new independent validation, or main-plan completion.
