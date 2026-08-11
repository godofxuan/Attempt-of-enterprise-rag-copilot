# Resume Metric Ledger

This table is the numeric safety boundary for resume and recruiter materials.
Values come from checked-in public evidence, not from prompts or memory.

| Class | Metric | Value | Dataset/scope | Meaning | Safe wording | Unsafe wording | Evidence |
|---|---|---:|---|---|---|---|---|
| A | WixQA Recall@5 | `42.75% -> 66.42%` | ExpertWritten, 200 fixed public-label retrieval questions | BM25-to-Dense retrieval gain | "Dense improved Recall@5 from 42.75% to 66.42%" | "RAG/answer accuracy is 66.42%" | `docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json` |
| A | WixQA nDCG@5 | `32.15% -> 52.16%` | Same 200 questions | Better ordering of gold articles in Top-5 | "nDCG@5 improved from 32.15% to 52.16%" | "Answer relevance is 52.16%" | same JSON |
| A | Full FTS build | `511,962` rows; `1.37 GiB`; `231.35 s`; `~1.83 GiB` peak RSS | EnterpriseRAG-Bench, 9 source types, one host | Full lexical corpus became executable with measured capacity | State all four values and single-host scope | "Production-scale cluster" or "high-performance" without comparison | `docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json` |
| A | Retrieved-content Guard | ASR `4/12 -> 0/12`; exposure `12/12 -> 0/12`; mean scan `1.42 ms` | Pinned garak subset, 12 attacks + 2 benign, local Qwen3-8B | Narrow OFF/ON security observation | Include "pinned 12-attack subset" | "100% safe", "full garak", or general FPR `0%` | `docs/resume_metrics/evidence/garak_latent_report_holdout_v1.json` |
| B | Clean replay | `63/63`, tolerance `0.0`; 11,975 embeddings | Three consumed WixQA cohorts, fresh local roots | Exact local regression reproducibility | "Reproduced 63 frozen quality values exactly from clean roots" | "Independent third-party replication" or "new holdout" | `docs/reproduction/evidence/wixqa_clean_reproduction_public_v1.json` |
| B | Enterprise lexical Recall@5 | `60.3741%` on `470` questions | EnterpriseRAG-Bench fixed public labels | Macro document retrieval recall | "Lexical Macro Recall@5 60.37%" | "Answer accuracy 60.37%" | `docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json` |
| B | Reused-ID sensitivity | `60.3741% -> 60.2677%`, `-0.1064pp`; 1/470 affected | Same benchmark under physical-record scoring | Benchmark identity sensitivity | Call it a sensitivity audit | Replace the official score without explanation | `docs/final_closeout/evidence/enterprise_reused_source_id_sensitivity_v1.json` |
| B | FTS process-crash trials | `30/30`; zero corrupt/mixed, manual-intervention, or unrecoverable-lock cases | Deterministic hard-process-exit matrix | Restart recovery under tested kill points | "30 hard-process-exit recovery trials passed" | "Power-loss safe" or "production HA" | `docs/final_evidence_closure/evidence/fts_hard_crash_matrix_v1.json` |
| B | Active-pointer trials | `12/12`; zero mixed/truncated pointers or restart failures | Four stages x three repetitions | Atomic pointer visibility under process exit | "12 active-pointer crash trials produced old-or-new complete state" | "All filesystem failures are atomic" | `docs/final_evidence_closure/evidence/active_pointer_crash_matrix_v1.json` |
| C | Equal RRF negative | Recall@5 `59.25%` vs Dense `66.42%`; p95 `304.64` vs `157.41 ms` | WixQA ExpertWritten 200 | Equal fusion lost quality and added latency | "Rejected equal RRF under a frozen gate" | "Hybrid retrieval improved quality" | WixQA retrieval JSON |
| C | Multi-document candidate negative | completeness `0% -> 0%`; recall `+2.5pp`; precision `-5.83pp`; p95 `1.859x`; fixes `0` | 20 consumed development cases | Candidate failed complete-evidence objective | "Rejected a bounded candidate with zero complete-case fixes" | "Agent improved multi-document quality" or "validation" | `docs/multidoc_candidate/evidence/aggregate_v1.json` |
| D | Synthetic Dense score | Recall@5 `97.88%` | Synthetic development cohort | Same-generator development ease | Do not use as resume headline | Present as external or blind quality | WixQA retrieval JSON |
| D | Gold Retrieval Oracle | Guard admitted all gold `20/20`, final complete `0/20` | Consumed diagnostic cohort with injected gold | Stage-capacity diagnosis | Interview-only diagnostic | Present as real retrieval/Agent quality | `docs/multidoc_attribution/evidence/aggregate_v1.json` |
| D | Test pass count | varies by commit/environment | Local/CI software regression | Code contract health | Mention only with exact SHA and context if asked | Product quality, model accuracy, or reliability SLO | exact verifier/CI run |

Class meaning:

- **A:** resume-safe primary metric.
- **B:** interview-supporting metric; use only when it serves the target role.
- **C:** negative result demonstrating evaluation discipline.
- **D:** forbidden or misleading as a resume quality claim.
