# EvalOps aggregate evidence exports

This directory contains versioned, aggregate-only references that an external
evaluation system can verify without receiving private questions, source text,
case identifiers, or per-case outcomes.

Each reference binds a source commit and successful CI run to one repository
artifact by SHA-256. The verifier checks strict schema validation, repository-
relative path safety, artifact integrity, decision/protocol consistency, and the
absence of private-payload keys. Dataset-specific metric recomputation still
requires an authorized per-case input package and is deliberately reported as
`INPUT_REQUIRED` here.

Verify the WixQA negative-result export from the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_external_aggregate_export `
  docs/evalops_exports/wixqa_reranker_negative_v1.json
```

