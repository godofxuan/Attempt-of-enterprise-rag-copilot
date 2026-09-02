# WixQA Article Reranker Protocol

Status: frozen before full-cohort results

## Objective

Measure whether a pinned Cross-Encoder can improve WixQA article ranking after
BGE-M3 Dense candidate generation. The reranker may reorder candidates but may
not retrieve new articles, inspect labels, or change the final Top-5 cutoff.

## Evidence boundary

- `simulated` (200 cases) is the configuration-selection cohort.
- `expertwritten` (200 cases) is historically consumed public-label evidence.
- The ExpertWritten comparison is retrospective and is not a fresh holdout,
  blind benchmark, answer-accuracy result, or runtime-promotion authority.
- Every run stays under `.private` on drive D. Only aggregate metrics and
  content-free hashes may be published.

## Frozen identities

- Implementation commit: `440f76a55b075fbe6de87b61fe7d1ed27b6fe0c7`
- Dataset revision: `d662dc42479c14e202eccd832f8c4b66a035c4cc`
- Dataset manifest: `e40972d70a8c80685b3730733efd90ac82a01fd52a949a0d27e122809bc290dd`
- Index manifest: `d21b3aa78bc578a86d421c4db724b6441d404e13ed628bd8c22fdaff002daa09`
- Embedding: `bge-m3` digest
  `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`
- Reranker: `cross-encoder/ms-marco-MiniLM-L6-v2` revision
  `c5ee24cb16019beea0893ab7796b1df96625c6b8`
- Reranker weights SHA-256:
  `821d1aa69520101d6e0737f78a042ae25b19e5cb9160701909d10434f4aeb0ae`
- Device and batch size: CPU, 16
- Dense chunk candidate depth: 200
- Final article cutoff: 5

## Selection arms

All arms use the same query embedding and Dense candidates:

1. Cross-Encoder Top-10, Dense head protection 0.
2. Cross-Encoder Top-10, Dense head protection 1.
3. Cross-Encoder Top-20, Dense head protection 1.

The selected arm maximizes validation nDCG@5. Ties are broken by Recall@5,
then MRR@5, then lower p95 latency. No post-result threshold or arm changes are
allowed.

## Admission gate

Against the Dense arm in the same validation run, the selected candidate must:

- not reduce article Recall@5;
- improve nDCG@5 by at least 0.02 absolute;
- keep p95 latency at or below 5.0 times Dense;
- preserve the candidate set, use one reranker call per question, and record
  all Guard quarantines and rule IDs.

Only a passing validation candidate may be executed once on ExpertWritten.
Passing the retrospective ExpertWritten comparison does not enable the
reranker in the application runtime.

## Commands

Each validation command uses:

```text
python -m scripts.eval_wixqa_retrieval --cohort simulated \
  --run-id <frozen-id> --article-reranker cross_encoder \
  --reranker-model cross-encoder/ms-marco-MiniLM-L6-v2 \
  --reranker-revision c5ee24cb16019beea0893ab7796b1df96625c6b8 \
  --reranker-device cpu --reranker-batch-size 16 \
  --candidate-k 200 --reranker-top-n <10|20> \
  --reranker-dense-head-count <0|1>
```

The single ExpertWritten command additionally requires
`--consume-fixed-external` and uses the selected configuration unchanged.

