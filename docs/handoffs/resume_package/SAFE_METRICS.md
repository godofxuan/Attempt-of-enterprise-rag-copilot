# Safe Metrics

Use only these primary headlines unless a target JD needs a supporting metric.

| ID | Class | Metric | Required qualifier |
|---|---|---|---|
| M1 | Primary | WixQA Recall@5 `42.75% -> 66.42%` and nDCG@5 `32.15% -> 52.16%` | 200 ExpertWritten public-label retrieval questions; not answer accuracy or blind |
| M2 | Primary | FTS5 `511,962` rows, `1.37 GiB`, `231.35 s`, `~1.83 GiB` peak RSS | 9 source types, one-host lexical index build |
| M3 | Primary with narrow security qualifier | Guard ASR `4/12 -> 0/12`, exposure `12/12 -> 0/12`, mean scan `1.42 ms` | one pinned garak subset, 12 attacks + 2 benign, not universal safety |
| M4 | Supporting | clean replay `63/63`, tolerance `0.0`, 11,975 embeddings | local consumed-label regression, not third-party reproduction |
| M5 | Supporting | FTS hard exits `30/30`; active pointer `12/12` | process crash only, not power loss or HA |
| M6 | Negative | multi-doc fixes `0`, completeness delta `0pp`, precision `-5.83pp`, p95 `1.859x` | 20 consumed development cases; candidate rejected |

The complete meanings, exact source paths, and forbidden phrasings are in
`../RESUME_METRIC_LEDGER.md` and `../PROJECT_EVIDENCE_MAP.md`.
