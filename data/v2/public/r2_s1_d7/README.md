# R2-S1 D7 Redacted Public Evidence

This package contains content-free, per-case observations projected from the
frozen local live paired run `r2-s1-d7-test-20260718-01`.

Source manifest SHA-256: `5bf058cfa56c2b5034e6f204dc3619833b55b3c30277c5222e7415f97865e14e`

Run `python verify.py` in this directory. The verifier uses only the Python
standard library, validates all checksums and schemas, rebuilds every summary
metric from the redacted rows, and rejects unexpected files or fields.

The package contains hashes, counts, booleans, bounded labels, and timing
observations. It intentionally excludes questions, prompts, retrieved text,
model output, canary and nonce values, content-unit identifiers, machine-local
paths, endpoint details, environment variables, and credentials.

`raw_canary_or_forbidden_action_follow` is a narrow canary/tool signal. It is
not a semantic LLM judge and must not be presented as complete instruction-
following coverage. The source protocol also used a fixed per-case OFF-then-ON
order, and its reached-unit field reproduces the D7 evaluator v1 semantics.
