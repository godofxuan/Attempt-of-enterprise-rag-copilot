# Adaptive Retrieval V3 Engineering Journal

## G0: Repository and Dataset Audit

- **Stage:** G0 Repository + dataset audit
- **Git SHA:** `827306d7aad4d9d3160e9bb3cf8f90d58fd43e9e`
- **Dataset:** WixQA and repository-visible external evaluation records.
- **Dataset status:** WixQA ExpertWritten 200 and the 17-case adaptive subset
  are `CONSUMED_DEVELOPMENT`.
- **Hypothesis:** None. This gate records facts before any V3 model call.
- **Arms:** None.
- **Primary question:** Can V3 separate assessment, rewrite, and routing without
  altering historical conclusions or authority boundaries?
- **Result:** Yes. The existing V2 runtime is bounded and Guard/ACL/Gateway
  owned. The old local assessor combines verdict and rewrite in one call, so it
  cannot answer V3's component questions unchanged. Existing S4 has a separate
  two-query validator/retrieval harness that can be reused offline.
- **Interpretation:** Build a new evaluation-only assessor contract; do not
  change `controller_v2.py`, `runner_v2.py`, `ToolGateway`, or serving policy.
- **Decision:** G0 complete. Proceed to G1 assessor quality only.
- **Next:** Freeze the assessor contract and three-run quality protocol.
