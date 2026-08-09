# EnterpriseRAG-Bench Reused Source ID Sensitivity

## Question

The benchmark contains 511,962 physical document rows but 511,958 unique
`source_native_id` values. Retrieval evaluation matches gold labels by
`source_native_id`. This audit asks whether retrieving the wrong physical record
with a reused ID can still receive credit.

## Measured scope

The full test Parquet contains four reused-ID groups and eight physical records:

| Reused source ID | Physical rows | Source types |
|---|---:|---|
| `dsid_8a0c5430bac64f8da21c2cee5a7f4df5` | 111, 183922 | confluence, hubspot |
| `dsid_feb1e9063ebb4947bb4f935393c01f0f` | 2762, 190837 | confluence, jira |
| `dsid_f292876dbb47462d85997383af306490` | 3307, 168464 | confluence, google_drive |
| `dsid_6df52fdb96ae4edcb76464738bca3340` | 189418, 191030 | jira, jira |

Each row has a distinct canonical-record SHA-256 in the machine-readable
evidence. The adapter and FTS result preserve that physical identity in
`record_id`, but the official evaluation contract intentionally matches the
benchmark's `source_native_id` gold labels.

## Actual impact

Only `qst_0413` among the 470 retrieval-scored questions references a reused ID.
Its official gold repeats the same Jira ID twice, representing two physical
records. FTS5 returns one of those records in top 5. Therefore:

| Metric | Published ID-aware | Record-aware sensitivity |
|---|---:|---:|
| `qst_0413` Recall@5 | 100.00% | 50.00% |
| Macro Recall@5, 470 questions | 60.3741% | 60.2677% |
| Overall change | - | -0.1064 percentage points |

Yes, the current metric can count a same-ID/wrong-physical-record result as a
hit. The measured maximum observed effect is small: one question and 0.1064
percentage points of Macro Recall@5.

## Decision and boundary

The official 60.3741% result is retained because the benchmark does not provide
record-hash gold labels and the evaluation follows its published ID contract.
The 60.2677% value is a sensitivity analysis, not a replacement benchmark score.
The impact is too small to justify rewriting the adapter, FTS index, or frozen
benchmark. Future datasets with record-level gold should score `record_id`.

Machine-readable evidence:
`docs/final_closeout/evidence/enterprise_reused_source_id_sensitivity_v1.json`.
It binds document/question hashes, private-details hash, index run ID, execution
Git SHA, all reused groups, and the affected question.

## FTS lifecycle conclusion

The current index contract remains `SINGLE_WRITER_OFFLINE_BUILDER` with
`ATOMIC_ACTIVATION`. It verifies SQLite integrity, counts and hashes before
activation; interruption and verification failure preserve the old active
pointer; a second builder fails fast. It does not claim distributed locking,
online concurrent indexing, or production multi-writer operation. See
`docs/rapid_upgrade/02_FTS_ACTIVATION_CONTRACT.md` and its failure-injection tests.
