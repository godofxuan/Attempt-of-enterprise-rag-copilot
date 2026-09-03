# Adaptive Retrieval V3 Rewrite Results

## G2 Decision: `REJECTED`

G2 fixed an Oracle subset of 88 consumed WixQA ExpertWritten questions whose
historical first-pass hybrid Top-5 did not cover all gold articles. It compares
the following fixed-final-five arms across the three existing, hash-bound S4
runs:

| Arm | Recall@5 | nDCG@5 | MRR@5 | Multi-doc complete@5 | Decision |
|---|---:|---:|---:|---:|---|
| R0 original hybrid Top-5 | 15.91% | 12.75% | 17.41% | 0.00% | reference |
| R1 original query, Top-10 candidate depth, final Top-5 | 15.91% | 12.75% | 17.41% | 0.00% | no effect |
| R2 historical validated two-query fusion, run 1/2 | 15.34% | 11.96% | 15.83% | 0.00% | worse |
| R2 historical validated two-query fusion, run 3 | 15.91% | 12.23% | 15.83% | 2.44% | mixed, lower rank quality |

R1 exactly equals R0 because candidate depth alone cannot alter a fixed,
unchanged RRF Top-5. R2 does not give a stable improvement on the difficult
Oracle-selected slice; it lowers nDCG and MRR in all three runs. Therefore the
historical S4 expansion is `REJECTED` as a V3 corrective-retrieval candidate.
No validator tuning is justified on this consumed slice, so G3 has no eligible
positive candidate to modify.

Evidence: [G2 public result](evidence/g2-oracle-historical-v4.json). The
historical S4 raw expansions remain private and are not republished.
