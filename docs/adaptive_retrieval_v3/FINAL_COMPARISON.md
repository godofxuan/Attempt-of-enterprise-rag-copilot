# Adaptive Retrieval V3 Final Comparison

## G6-G9 Final Closure

### G6: Deterministic Controls

The existing, hash-bound retrieval strategy bake-off is retained as the V3
control evidence: hybrid RRF Top-5 is the reference; two diversity variants
were rejected; historical always-on S4 two-query fusion is not a V3 finalist.
V3 G2 independently rejected S4 as a corrective action on Oracle-selected
first-pass failures. No new retrieval database, framework, model, or default
parameter is justified by this result.

### G7: Fresh Validation

`NOT_RUN`: the dataset ledger establishes that no verified V3-compatible fresh
question cohort is available. Calling any WixQA split fresh would be false.
No post-result tuning or fabricated holdout was performed.

### G8: End-to-End Answer/Citation

`NOT_RUN`: no retrieval strategy reached `FINALIST`, so running answer and
citation evaluation would not validate an eligible new policy. Existing
grounding, citation, ACL, Guard, and evidence-ledger evaluations remain intact.

### G9: Default

`REJECTED`. No V3 adaptive retrieval profile becomes `FINAL_DEFAULT` or
changes serving behavior. The current default stays the existing bounded hybrid
RRF workflow. This is the evidence-backed final system-selection decision.
