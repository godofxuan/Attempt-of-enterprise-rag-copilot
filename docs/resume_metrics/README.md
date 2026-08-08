# Resume Metrics Evidence Index

Start with [RAG Improvement Report](RAG_IMPROVEMENT_REPORT.md), then verify
[Baseline vs Final](RAG_BASELINE_VS_FINAL.csv),
[Ablations](RAG_ABLATION.csv), and the machine-readable [experiment
registry](metrics.csv).

## Required closeout files

- [Baseline](BASELINE.md)
- [Experiment registry](EXPERIMENT_REGISTRY.md)
- [Failure analysis](RAG_FAILURE_ANALYSIS.md)
- [Negative results](RAG_NEGATIVE_RESULTS.md)
- [Resume-safe metrics](RAG_RESUME_METRICS.md)
- [Interview guide](RAG_INTERVIEW_GUIDE.md)
- [Claim allowlist](resume_safe_claims.md)

The `evidence/` directory contains aggregate, content-free JSON. Raw model
outputs, external dataset rows, and private run artifacts are not published.

The newest external page-retrieval result is documented in
`../external_datasets/uda_finance_protocol.md`, with public aggregate evidence
at `../external_datasets/evidence/uda_finance_test_v1.json`. The implementation,
download incidents, decisions, and interview explanation are recorded in
`../external_datasets/uda_finance_engineering_journal.md`.
