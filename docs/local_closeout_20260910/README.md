# Local Candidate Closure (2026-09-10)

This branch delivers the previously uncommitted runtime repairs from the
`b07c03d0256c393db5dfbb969e5d20abd70155b0` working tree. It is a review candidate,
not a production release. Existing main, historical tags, evidence and resume
links are preserved. No model or retrieval strategy is promoted by this delivery.

## What Changed

- Bounded expense-query normalization and explicit requested-detail checks;
  same-authorized-source find/open follow-up for late clauses.
- Supported material/amount retention, missing-detail publication, continuous
  citation-prefix binding, and exact duplicate evidence suppression.
- Structure-aware Markdown/DOCX/CSV table chunking and document-quality checks
  tied to indexing and lifecycle publication. Unsupported layout remains a limit.
- Literal office/grade applicability checks before generation and at publication;
  evidence uses its own section heading, never another source's metadata.
- Earlier readiness refresh without extending the readiness validity window.

LLM query advice and Denser-style learned fusion remain offline experiments.
The optional Docling worker is included because its existing tests import it;
it is not wired into production and successful real OCR is not established.

## Evidence And Results

The last bounded model/fusion trial used local BGE-M3, BGE reranker v2-m3 and
Ollama. A new qwen3.5:4b download is a tested generation candidate only.
Default chat remains qwen2.5:3b, evidence qwen3:8b, retrieval bounded Hybrid RRF.

| Fixed evaluation | Observation | Meaning |
|---|---|---|
| Consumed WixQA ExpertWritten200, same mixed candidate pool | BGE Recall@5 75.50%, nDCG@5 60.70% | BM25 top50 + Dense top50 union; offline reference, not serving default |
| Same pool, XGBoost F0/F1 | Recall@5 75.25%, nDCG@5 60.60% | No gain; no shadow or default deployment |
| Original + LLM rewrite candidate union, BGE | Recall@5 74.75%, nDCG@5 60.26% | No gain over original mixed pool |
| Same 18 synthetic generation scenarios | Complete target facts 33/39 to 37/39; runner p95 1.97s to 2.76s | Small deterministic string-coverage proxy, not human accuracy |
| Earlier application-admission WixQA replay | Dense to raw50+BGE Recall@5 65.92% to 74.25%, nDCG@5 52.08% to 59.93% | Historical retrieval improvement, unchanged by this packaging |
| Earlier fixed authenticated API regression | 170/240 to 193/240 finite contracts; false answered 5 to 0 | 40 synthetic questions x 2 configurations x 3 repeats; not 240 independent questions |

Both human WixQA cohorts have already been consumed. No fresh final test exists
in these trials. XGBoost Recall delta versus same-pool BGE is -0.25 percentage
points, paired 95% interval [-1.25, +0.50]. Candidate-pool gains must not be
credited to learned ranking. Denser's complete official framework was not run.

The original local model-trial audit ZIP SHA256 is
`9180c04026425ab89b3fdbfcf541e9b83631c739a640e1615b2a4cd5484925db`.
It contains raw local evidence and is not uploaded as an unreviewed public ZIP.
New public execution evidence and exact-source hashes are recorded separately.
See the [execution report](EXECUTION_REPORT.md), [test results](TEST_RESULTS.json)
and [source identity](SOURCE_IDENTITY.json). Final local regression is
3973 passed, 3 failed, 36 skipped; this candidate is not a green release.

## Local Operation

Use an existing Python environment and a valid BGE-M3 index. No downloads,
index rebuild, activation or database migration are performed by the launcher.
All new local runtime state stays under this checkout's ignored `.private`.

```powershell
.\scripts\local_candidate.ps1 -Action Start -PythonPath '<existing-python.exe>' -IndexRoot '<existing-index-directory>'
.\scripts\local_candidate.ps1 -Action Status
.\scripts\local_candidate.ps1 -Action Stop
```

The API binds only `127.0.0.1:8000`, the existing Streamlit UI only
`127.0.0.1:8501`. Occupied ports cause an error; optional ApiPort/UiPort arguments
select different ports. The launcher does not claim readiness from process
creation; check `/health/ready` before use. Token files and logs are not public.
Demo tokens expire after 15 minutes. Stop this candidate, then use Start with
`-RefreshDemoIdentity` to explicitly replace only this checkout's local demo
identity and invalidate its old tokens. The flag cannot be used while a recorded
candidate process is running. Other worktrees and identities are untouched.
Follow the existing
[identity guide](../security/r2_s5/02_implementation_and_interview_guide.md) for identity management; never
disable expiry or authentication to keep a demo alive.

## Release Boundary

Publishing this branch is source delivery, not main promotion or internet
deployment. Historical source-hash binding failures are preserved; the current
execution report distinguishes them from product failures and missing packages.
No frozen test is weakened, no benchmark is rerun to manufacture a new score,
and no online accuracy, production SLO or general typo/OCR coverage is claimed.
