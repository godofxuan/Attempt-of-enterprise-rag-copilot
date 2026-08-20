# Resume Bullet Evidence Map

## Version A

| Bullet | Evidence claim | Metric | Main risk | Forbidden stronger wording |
|---|---|---|---|---|
| A1 replaceable host-controlled runtime | P5 / P7 | mechanism tests only | Architecture breadth can be mistaken for quality | Agent/LangGraph improved accuracy; semantic entailment guaranteed |
| A2 WixQA Dense | P1 / M1 | 42.75% -> 66.42%; 32.15% -> 52.16% | Retrieval can be mislabeled answer quality | RAG accuracy; blind test; SOTA |
| A3 rejected candidate | N1 / M6 | fixes 0; precision -5.83pp; p95 1.859x | Failure can be falsely packaged as quality gain | Agent improved/deployed |
| A4 Guard | P4 / M3 | ASR 4/12 -> 0/12; exposure 12/12 -> 0/12 | Tiny attack/benign denominators | 100% safe; full garak; FPR 0% generally |
| A5 clean replay | P2 / M4 | 63/63; 11,975 embeddings | Same owner and consumed labels | third-party reproduction; new holdout |

## Version B

| Bullet | Evidence claim | Metric | Main risk | Forbidden stronger wording |
|---|---|---|---|---|
| B1 evaluation evidence chain and Agent artifact | P1-P8/N1 | schema/hash/test bindings | Mechanism count is not model quality | comprehensive external validation or external EvalOps adoption |
| B2 retrieval ablation | P1 | all three arm metrics | Equal RRF is negative | hybrid improved quality |
| B3 first-loss attribution | N1 plus attribution aggregate | Top20 7 / Top5 10 / selection 3 | Consumed diagnostic cohort | blind root-cause proof |
| B4 clean verifier | P2 | exact 63/63 | local replay | independent reproduction |
| B5 security evaluation | P4 | attack/exposure/utility/latency | one subset and model | universal defense |

## Version C

| Bullet | Evidence claim | Metric | Main risk | Forbidden stronger wording |
|---|---|---|---|---|
| C1 FTS capacity | P3 / M2 | 511,962; 1.37 GiB; 231.35 s; 1.83 GiB | one-host benchmark | production cluster or QPS |
| C2 crash recovery | P6 / M5 | 30/30 and 12/12 | process exit only | power-loss safe; HA |
| C3 ToolGateway/MCP boundaries | P5 / P7 / P8 | deterministic portfolio gate | local simulated identity and in-process MCP | enterprise SSO; network MCP/OAuth; production SLO |
| C4 reused-ID audit | P3 supporting | 4 groups/8 rows/1 affected/-0.1064pp | sensitivity, not new official score | benchmark corrected to 60.2677% |
| C5 clean replay | P2 | 63/63 | local consumed-label replay | third-party validation |

Full artifact paths, commands, and execution SHAs are in
`../PROJECT_EVIDENCE_MAP.md`.
