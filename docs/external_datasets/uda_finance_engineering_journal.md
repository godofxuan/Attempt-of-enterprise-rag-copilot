# UDA FinHybrid Engineering Journal

## 1. Why this stage existed

The previous closeout stopped feature work because FinanceBench's 150 public
questions had already influenced development and test reporting. Continuing to
tune that population would make the numbers less credible. UDA-QA FinHybrid was
selected because it is externally authored, uses real financial-report PDFs,
contains textual and tabular evidence, exposes source-page identity, and is
licensed CC-BY-SA-4.0.

This stage adds evaluation evidence, not a production feature. ACL, Guard,
identity, Agent control, answer generation, and the active application index
were not modified.

## 2. Frozen experimental flow

```text
pinned UDA Git/HF revisions
  -> validate fin_qa.csv SHA and row identities
  -> stable-hash companies/reports/questions
  -> freeze 8-company dev / 12-company test protocol in Git
  -> download and hash-check upstream PDF archive on D drive
  -> extract only 20 selected reports
  -> parse 20 PDFs and build isolated 8,905-chunk BGE-M3 index
  -> compare BM25 / Dense / RRF on 64 dev questions
  -> commit Dense selection by preregistered nDCG@5
  -> atomically claim one-shot test execution
  -> run Dense once on 96 company-disjoint questions
  -> publish content-free aggregate and stop
```

The known report is supplied as a `policy_id` filter for each question. This
matches UDA's document-QA contract and isolates page ranking. It does not test
open-corpus document discovery.

## 3. Code changes

| File | Responsibility |
|---|---|
| `app/external_datasets/uda_finance.py` | strict CSV identity checks, stable company split, safe ZIP extraction, corpus/eval manifests, hash verification |
| `app/external_datasets/uda_finance_page_eval.py` | known-report SearchRequest, page scoring, MRR/nDCG/latency summaries, immutable private runs |
| `scripts/download_uda_finance_archive.py` | bounded Range resume, exact byte count, Xet ETag binding, LFS SHA-256 verification |
| `scripts/prepare_uda_finance.py` | operator CLI for extraction, preparation, and verification |
| `scripts/build_uda_finance_index.py` | isolated parser/chunker/BGE-M3 index with resumable embedding cache |
| `scripts/eval_uda_finance_pages.py` | dev/test runner and one-shot frozen-test marker |
| `tests/external_datasets/test_uda_finance*.py` | deterministic split, path safety, hash tamper, metric recomputation, one-shot contracts |

Raw PDFs, labels, per-question details, embeddings, and indexes remain under
`.private/external/uda_finance` on drive D and are excluded from Git.

## 4. Problems and fixes

### 4.1 Real rows may have one empty answer column

The initial adapter required both `answer_1` and `answer_2`. Loading the real
8,190-row CSV failed because some rows intentionally provide only one answer
form. The contract was corrected to require at least one non-empty answer. Page
retrieval itself never uses either answer for ranking or scoring.

### 4.2 Hugging Face Xet appeared stuck

The first `hf_hub_download` attempt left a zero-byte target while child Python
processes retained the lock after the desktop command was terminated. Process
inspection distinguished these UDA download PIDs from unrelated pytest jobs.
Only the four UDA PIDs were stopped.

Windows `curl` then downloaded 251,652,687 bytes before the server ended the
response and subsequent Schannel resumes failed with `SEC_E_NO_CREDENTIALS`.
A `requests` Range probe proved the server still supported exact `206 Partial
Content`, so a bounded Python downloader was added. It resumed from the exact
byte offset rather than restarting.

### 4.3 Xet ETag is not the file content SHA

After reaching the pinned 2,405,128,290-byte size, validation failed because the
first downloader revision treated CDN Xet ETag `354563...42a3` as the archive
SHA-256. Hugging Face `files_metadata=True` reported the actual LFS SHA-256 as
`e94f2e...dd44`; the local file matched that value exactly. The code now uses
Xet ETag only for Range identity and LFS SHA-256 for final content integrity.
The incomplete file was never promoted before this distinction was fixed.

### 4.4 PDF cross-reference warnings

PyPDF emitted four `wrong pointing object` warnings during parsing but produced
all 20 documents and 8,905 page chunks. Test page-locator coverage was 100%, so
the warnings are disclosed but do not justify replacing the parser from this
consumed test.

## 5. Development decision

| Arm | Hit@5 | MRR@5 | nDCG@5 | p95 ms |
|---|---:|---:|---:|---:|
| BM25 | 67.19% | 48.46% | 53.17% | 123.68 |
| Dense | 84.38% | 60.57% | 66.54% | 235.42 |
| RRF | 79.69% | 61.61% | 66.14% | 297.92 |

RRF had slightly higher MRR than Dense, but the frozen primary metric was
nDCG@5. Dense was therefore committed as the test choice. Changing the primary
metric after observing RRF would be evaluation leakage.

## 6. Fixed-test result

On 96 questions from 12 companies absent from development, Dense achieved:

- Page Hit@1/3/5: `46.88% / 67.71% / 73.96%`;
- MRR@5: `57.07%`;
- nDCG@5: `61.30%`;
- mean/p50/p95 latency: `201.31 / 196.96 / 222.91 ms`;
- page locator coverage: `100%`.

Development Hit@5 was 84.38%, so test performance dropped 10.42 percentage
points. The project records the lower test result rather than promoting the
development number.

## 7. Failure diagnosis and stopping rule

There were 25 misses at rank five. The nearest retrieved page was adjacent in
seven, two to three pages away in one, four to ten pages away in seven, and over
ten pages away in ten. Nearby misses suggest page/table boundaries; distant
misses indicate semantic page-ranking failures.

The test has now been consumed. These categories may motivate a future
hypothesis, but no parser, chunker, reranker, or prompt may be selected on these
96 labels and then reported against the same test. A new dev/test population is
required.

## 8. Interview-safe explanation

> I did not add another RAG framework. I preregistered a company-disjoint UDA
> FinHybrid page-retrieval protocol, selected Dense on 64 development questions,
> and enforced a one-shot 96-question fixed test. BGE-M3 Dense reached 74.0%
> Page Hit@5 and 61.3% nDCG@5 at 222.9 ms p95 within the known report. The test
> was 10.4 points below dev, so I published the generalization drop and stopped
> tuning rather than recycling the test.

## 9. Final repository verification

- UDA focused suite: `11 passed`;
- full repository suite: `3069 passed, 30 skipped` in `232.05 s`;
- warnings: three pre-existing FAISS/SWIG deprecation warnings;
- public repository audit: `1406 candidates / 0 findings`;
- test evidence SHA-256:
  `6b08e213e93ae00c9eb834a388c88460d33356282d112f2f80869e0f04a695d0`.

`0 findings` means that the implemented static rules found no prohibited
content among 1,406 public candidates. It is not a claim that the repository
has no unknown vulnerability.
