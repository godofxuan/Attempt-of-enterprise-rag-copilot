# Candidate Execution Report

## Final Local Checks

- Complete deterministic suite: **3973 passed, 3 failed, 36 skipped** across
  4012 collected cases. Runtime imports came from this candidate checkout.
- The frozen tests and prior evidence were not edited. This is not an all-green
  release and does not justify promotion to production or main business code.
- Local real HTTP + Ollama smoke: readiness succeeded; unauthenticated chat was
  rejected with 401; employee identity succeeded; the UI health endpoint succeeded.
  Two cited replies returned one answered and one partial. The materials query
  still lacked the requested material details. This is connectivity/contract
  verification, not two fully correct answers or an accuracy benchmark.
- Existing environment `pip check`: no broken requirements.
- Public audit: 38 findings, all in byte-identical pre-existing baseline files;
  zero findings in new/modified files at that scan. The global audit is not PASS.

## Three Preserved Failures

1. `test_e16_public_evidence_binds_protocol_sources_and_implementation`: old
   evidence fingerprints differ for config and readiness implementation.
2. `test_public_trusted_identity_result_recomputes_exactly`: the immutable old
   identity result differs from the current source-bound evaluation. The current
   identity matrix behavior test passes; the old equality assertion remains FAILED.
3. `test_direct_requirements_match_the_proven_local_versions`: the old exact
   dependency set does not contain the new `markdown-it-py==4.2.0` parser dependency.
   Dependency installation consistency and historical exact-set equality differ.

These are real release-contract failures, not hidden PASSED cases. Proper
versioned evidence/dependency-contract migration remains a main-release blocker.
Environment-specific skips are listed in the JUnit evidence, not counted as passes.

## Packaging And Harness Corrections

The first isolated run could not collect an existing Docling adapter test
because its experiment worker had been omitted. The identical original worker
was copied into the delivery; no test or production logic was changed.

The next run recorded 3957 passes, 19 failures and 36 skips. Sixteen failures
were caused by this round's new test launcher executing its top-level setup
again in Windows spawned children. The launcher was wrapped in a main guard;
the final full rerun above passed those process tests. Initial XML/logs and the
initial helper remain available. The three remaining failures are not attributed
to that harness error.

## What Is Delivered

The candidate includes the actual runtime repairs, their unchanged tests, one
required optional-worker source, local launcher and this evidence package.
Application/test/script/UI Python hashes match the original dirty candidate.
The release copy does not include private credentials, databases, model weights,
benchmark source corpora or the unreviewed full local experimental ZIP.

Original raw JUnit and logs remain local. Published JUnit is a **derived,
path-redacted** artifact with captured stdout/stderr removed and credential-like
test syntax redacted; `REDACTION_MAP.json` binds each real raw hash to its
derived hash. It is not labelled as unmodified raw or full-output XML. Earlier evidence files
are unchanged. `SOURCE_IDENTITY.json` fixes the source bytes independently of
the later Git commit containing this report.

## Decision

`LOCAL_REVIEW_CANDIDATE_WITH_LIMITS`.

Publish a separate review branch as requested. Do not replace main business
code, claim production certification, or enable LLM rewriting/XGBoost. No new
retrieval benchmark or human evaluation was run during this packaging round.
The local launcher is opt-in, loopback-only and uses an existing read-only
active-index binding; it does not activate a replacement index.
