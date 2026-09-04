# WixQA BGE Reranker v2-m3 Experiment Record

## Read this first: what produced 75.00%

The reported `75.00%` article Recall@5 is from this exact pipeline:

```text
question
  -> BGE-M3 + cosine/IP search over all chunks
  -> retain the first 50 raw chunks (duplicates by article are still present)
  -> score all 50 (question, chunk text) pairs with bge-reranker-v2-m3
  -> sort chunks by descending reranker logit
  -> keep the highest-ranked chunk for each article_id
  -> return the first five unique articles
  -> macro-average per-question article Recall@5 over 200 ExpertWritten questions
```

Two easy-to-miss settings change the experiment:

1. Pass `--candidate-unit chunk`. The script default is `article`. Reranking 50
   article representatives produced `71.00%`, not `75.00%`.
2. Use `data_manifests/WIXQA_OFFICIAL_RAW_MANIFEST.json`, whose SHA-256 is
   `d325412340c110d3f76b832080c702978643d517e296c97bba1abc088ec65b1f`.
   The default historical manifest binds CRLF QA files. The experiment used the
   canonically equivalent official LF transport documented by the V2 clean
   reproduction protocol.

The complete result summary is also available as machine-readable evidence in
`docs/reproduction/evidence/wixqa_bge_reranker_v2_m3_public_v1.json` (SHA-256
`577c957e62ce02fbe30e48e889ca7470b673e914a788a9af8fafe71c769ca415`).

## Scope and code identity

- Repository base used to build the dense index:
  `bd71cb3ca8de4e1899a4ea0e09d3c1c677c77a7e`
- Experiment implementation preserved by:
  `79ba431523562e53e1ace8d74a55bc604d72705c`
- Branch: `feat/wixqa-bge-reranker-v2-m3`
- Evaluation date: 2026-09-02
- This is retrospective offline evaluation on already-consumed public labels.
  It is not a blind holdout, production integration, or answer-quality test.

The dense candidate artifact records the base Git HEAD (`bd71cb3`) because it
was generated while the experiment scripts were uncommitted. The exact script
state used for the run is the state committed as `79ba431`.

## Dataset identity

| Field | Value |
|---|---|
| Dataset | WixQA |
| Source | `Wix/WixQA` on Hugging Face |
| Pinned source revision | `d662dc42479c14e202eccd832f8c4b66a035c4cc` |
| Manifest | `data_manifests/WIXQA_OFFICIAL_RAW_MANIFEST.json` |
| Manifest SHA-256 | `d325412340c110d3f76b832080c702978643d517e296c97bba1abc088ec65b1f` |
| Corpus articles | 6,221 |
| Evaluation cohort | ExpertWritten, all 200 rows |
| Question ID set SHA-256 | `ec11e3e4733bd6701441b127952fa98b0973f9961a0aacabfae570da45976110` |
| Label state | `FIXED_CONSUMED_REGRESSION_REPLAY` |

The 200 questions contain 258 question-to-gold-article labels: 148 questions
have one gold article, 46 have two, and 6 have three. No answer text is used in
retrieval or reranking.

Official LF source file identities are frozen in
`data_manifests/WIXQA_OFFICIAL_RAW_MANIFEST.json`. The V2 protocol and transport
equivalence evidence explain why their byte hashes differ from the historical
CRLF manifest while canonical JSON rows and derived question IDs remain equal:

- `docs/reproduction/evidence/WIXQA_CLEAN_RETRIEVAL_PROTOCOL_V2.json`
- `docs/reproduction/evidence/WIXQA_SOURCE_TRANSPORT_EQUIVALENCE_V1.json`

## Dense retriever and index

| Field | Value |
|---|---|
| Model | Ollama `bge-m3` |
| Ollama model digest | `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab` |
| Embedding dimension | 1,024 |
| Chunking | fixed 1,800 body characters, 150-character overlap |
| Chunk text | article title + newline + body chunk |
| Corpus chunk count | 11,975 |
| Vector index | L2-normalized float32 vectors in FAISS `IndexFlatIP` |
| Retrieval depth | 200 raw chunks per question |
| Index run ID | `wixqa-bge-m3-reproduction-20260902` |
| Index manifest SHA-256 | `e74631aae61f6f15c50f0ce48ee5fba19e5c08bab894b6615dc4903160689796` |

Index artifact identities from the observed run:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `bm25_tokens.pkl` | 21,554,382 | `5a11505c9f6dbd9186cf045e6ae7dd0de861b08f40b2217c16f890f34b829466` |
| `chunks.jsonl` | 19,517,060 | `0ca1e6191710846fe1ef583f9f7f433dbe06d016bc39ceefdc18a83931fd526e` |
| `faiss.index` | 49,049,645 | `9c1010980eed29849a079101719246fd294121315eb48dea2ecce4d4c888c903` |

The A100 Ollama backend returned HTTP 500 after producing a non-finite result
for one of 11,975 corpus chunks and 9 of 200 queries. Those individual inputs
were recomputed on a second local Ollama instance using the same model name,
digest, and dimension. `scripts/build_wixqa_index.py` recursively splits only a
failed batch and permits the one-text fallback only after model identity
matching. `scripts/export_wixqa_dense_candidates.py` records the query fallback
count (`9`). A reproducer whose Ollama backend does not emit these errors should
not enable the fallback merely to imitate the count; model and resulting
candidate identities matter, not which local device computed them.

The observed dense candidate artifact was:

- file name: `wixqa-dense-top200-chunks-20260902.json`
- bytes: `82,176,293`
- SHA-256:
  `7e7a7c9705155e68cf42834f190110ebab9dd66ccfe75ff8776d95692b994e5e`

It is ignored rather than committed because it is about 82 MB and repeats raw
benchmark questions, chunk text, and labels. A fresh reproduction is expected
to generate it locally. If this SHA differs, compare dense metrics and index
identities before diagnosing the reranker.

## Reranker identity and inference settings

| Field | Value |
|---|---|
| Model | `BAAI/bge-reranker-v2-m3` |
| Hugging Face revision | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |
| `model.safetensors` SHA-256 | `d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286` |
| Loader | `AutoModelForSequenceClassification` |
| Precision/device | float16, one NVIDIA A100-SXM4-40GB |
| Pair format | tokenizer text pair `(question, title + "\n" + body chunk)` |
| Tokenization | dynamic padding, truncation enabled, `max_length=512` |
| Batch size | 16 pairs |
| Score | raw scalar classification logit; sigmoid is omitted because it is monotonic |
| Sort | descending logit; exact ties retain original dense chunk order |
| Random seed | PyTorch CPU and CUDA seeds both set to 0 |

Each candidate depth is inferred independently by the script. The top-50 arm
therefore scores exactly 50 pairs per question; it is not obtained by scoring
200 pairs once and slicing a larger ranked list.

## Observed environment

| Field | Value |
|---|---|
| OS | Ubuntu 20.04.6 LTS, Linux 5.4.0-169-generic, x86_64 |
| GPU | NVIDIA A100-SXM4-40GB, 40,960 MiB |
| NVIDIA driver | 545.23.08 |
| Ollama | 0.17.5 |
| Dense/index Python | 3.13.13 |
| NumPy / FAISS / Pydantic | 2.4.4 / 1.13.2 / 2.13.2 |
| Reranker Python | 3.12.13 |
| PyTorch / CUDA runtime | 2.10.0+cu128 / 12.8 |
| Transformers / Tokenizers | 5.8.0 / 0.22.2 |
| Safetensors / Accelerate | 0.7.0 / 1.11.0 |

Latency values below are machine-specific and cover reranker inference only;
they exclude dense query embedding, FAISS retrieval, model loading, disk I/O,
and application/network overhead.

## Reproduction commands

All commands run from the repository root. Choose repository-local ignored
paths for generated artifacts. The environment must expose a local Ollama
endpoint containing the pinned `bge-m3` digest. The examples use POSIX shell.

### 1. Acquire and verify WixQA

```bash
python -m scripts.download_wixqa \
  --manifest data_manifests/WIXQA_OFFICIAL_RAW_MANIFEST.json \
  --source-root .private/external/wixqa/source

python -m scripts.download_wixqa \
  --offline-verify \
  --manifest data_manifests/WIXQA_OFFICIAL_RAW_MANIFEST.json \
  --source-root .private/external/wixqa/source
```

### 2. Build the BGE-M3 index

For a backend that embeds every input successfully, omit the two fallback
flags. If an identity-matched fallback is required, set its URL explicitly as
shown. The primary endpoint comes from `LLM_BASE_URL`; `EMBEDDING_MODEL` must be
`bge-m3`.

```bash
LLM_BASE_URL=http://127.0.0.1:11435/v1 \
EMBEDDING_MODEL=bge-m3 \
python -m scripts.build_wixqa_index \
  --manifest data_manifests/WIXQA_OFFICIAL_RAW_MANIFEST.json \
  --source-root .private/external/wixqa/source \
  --output-root .private/external/wixqa/indexes \
  --embedding-cache .private/external/wixqa/embedding_cache \
  --run-id wixqa-bge-m3-reproduction-20260902 \
  --chunk-size 1800 \
  --overlap 150 \
  --batch-size 32 \
  --max-batch-chars 48000 \
  --split-on-embedding-http-500 \
  --embedding-http-500-single-fallback-url http://127.0.0.1:11434/v1
```

Verify that `active.json` points at this run and compare the generated manifest
and artifact hashes with the identities above.

### 3. Export raw chunk candidates

This step must retain raw chunks. `--article-depth 50` also stores the
article-deduplicated dense view used for the baseline comparison.

```bash
LLM_BASE_URL=http://127.0.0.1:11435/v1 \
EMBEDDING_MODEL=bge-m3 \
python -m scripts.export_wixqa_dense_candidates \
  --manifest data_manifests/WIXQA_OFFICIAL_RAW_MANIFEST.json \
  --source-root .private/external/wixqa/source \
  --index-root .private/external/wixqa/indexes \
  --output .private/external/wixqa/eval_runs/wixqa-dense-top200-chunks.json \
  --candidate-k 200 \
  --article-depth 50 \
  --chunk-depth 200 \
  --embedding-http-500-fallback-url http://127.0.0.1:11434/v1
```

Before reranking, the expected dense article Recall@5 is `0.6658333333333333`
and raw-top-50-chunk candidate-pool article recall is
`0.9241666666666667`. If either differs materially, the reranker is not being
tested on the same candidate pool.

### 4. Acquire and validate the reranker snapshot

Any Hugging Face download method may be used, but pin the revision and verify
the weight hash before inference. For example:

```bash
RERANKER_MODEL_PATH=.private/models/bge-reranker-v2-m3/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e

hf download BAAI/bge-reranker-v2-m3 \
  --revision 953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e \
  --local-dir "$RERANKER_MODEL_PATH"

sha256sum "$RERANKER_MODEL_PATH/model.safetensors"
```

The required output hash is
`d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286`.

### 5. Run the exact chunk-first experiment

```bash
RERANKER_MODEL_PATH=.private/models/bge-reranker-v2-m3/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e

python -m scripts.eval_wixqa_bge_reranker \
  --candidates .private/external/wixqa/eval_runs/wixqa-dense-top200-chunks.json \
  --model-path "$RERANKER_MODEL_PATH" \
  --output .private/external/wixqa/eval_runs/wixqa-bge-reranker-v2-m3-chunks.json \
  --device cuda:0 \
  --batch-size 16 \
  --max-length 512 \
  --depths 10,20,50,100,200 \
  --candidate-unit chunk
```

The physical GPU ordinal is not part of ranking semantics. The observed run
used `cuda:1`; `cuda:0` above is suitable on a one-GPU reproduction host.

## Exact ranking and metric semantics

For each question `i`, let `C_i^d` be the first `d` raw BGE-M3 chunks. The
reranker computes one logit per `(question, chunk text)` pair, sorts all chunks,
then scans that order and retains only the first chunk for each `article_id`.
There is no score aggregation across chunks from the same article and no dense
score interpolation. The first five unique article IDs form `R_i^5`. No
unreranked candidate is used to backfill a short result list.

Let `G_i` be the set of gold article IDs. Per-question Recall@5 is:

```text
recall_i@5 = |G_i intersection R_i^5| / |G_i|
```

The reported result is a macro average, so every question has equal weight:

```text
article_recall@5 = (1 / 200) * sum_i(recall_i@5)
```

It is not micro recall over all 258 labels. For reference, the dense top-5
found 165 of 258 labels (`63.95%` micro recall) while its macro Recall@5 is
`66.58%`.

Other metrics use binary article relevance:

- Hit@1 is `1` when the first returned article is gold, else `0`, macro-averaged.
- MRR@5 is the reciprocal rank of the first gold article in the first five,
  or `0` when none is present, macro-averaged.
- DCG@5 sums `1/log2(rank + 1)` at relevant ranks. IDCG uses relevant items at
  ranks `1..min(5, |G_i|)`. nDCG@5 is per-question `DCG/IDCG`, macro-averaged.
- Multi-article completeness@5 is the fraction of the 52 questions with two or
  three gold articles for which all gold articles occur in the first five.

## Results

### Chunk-first reranking (the 75.00% experiment)

| Arm | Hit@1 | Recall@5 | Delta vs dense | nDCG@5 | MRR@5 | Pool recall | Reranker p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Dense | 35.00% | 66.58% | - | 52.14% | 49.57% | - | - |
| raw chunk top-10 | 44.50% | 71.92% | +5.33 pp | 58.87% | 57.84% | 75.33% | 43.28 ms |
| raw chunk top-20 | 45.00% | 72.75% | +6.17 pp | 59.58% | 58.20% | 83.42% | 93.18 ms |
| raw chunk top-50 | 45.00% | **75.00%** | **+8.42 pp** | 60.60% | 58.94% | 92.42% | 190.61 ms |
| raw chunk top-100 | 45.00% | 74.75% | +8.17 pp | 60.48% | 59.02% | 95.92% | 366.11 ms |
| raw chunk top-200 | 45.00% | 75.50% | +8.92 pp | 60.81% | 59.45% | 97.83% | 709.32 ms |

At depth 50, 31 questions gained recall relative to dense top-5 and 12
regressed. The 50 raw chunks represented a mean 37.185 unique articles
(`min=23`, `p50=38`, `p95=46`, `max=50`). Every depth-50 question returned five
unique articles after deduplication.

The observed result artifact was:

- file name: `wixqa-bge-reranker-v2-m3-chunks-20260902.json`
- bytes: `1,194,923`
- SHA-256:
  `3549654cbf7f969a5fddd38897cb704860eed9dc56275bc3760aaaf9b57bdc47`

### Deduplicate-before-reranking control

Running the default/article candidate mode selects only the highest-ranked
dense chunk from each article before cross-encoder inference. It is a different
experiment and produced:

| Article representatives reranked | Recall@5 | nDCG@5 | Reranker p95 |
|---:|---:|---:|---:|
| 10 | 69.92% | 56.45% | 44.35 ms |
| 20 | **71.50%** | **57.02%** | 92.36 ms |
| 50 | 71.00% | 56.54% | 191.09 ms |

This control is useful for diagnosing a result near 71%: it usually means
article deduplication happened before reranking or `--candidate-unit chunk` was
omitted.

## Reproduction checklist and divergence diagnosis

Check identities in this order rather than comparing only the final number:

1. Official LF manifest SHA is `d325...` and question ID set SHA is `ec11...`.
2. There are 6,221 articles and 11,975 chunks with 1,800/150 character
   chunking; title is prepended to every chunk.
3. Ollama BGE-M3 digest is `790764...2146bab`, dimension is 1,024, corpus and
   query vectors are normalized, and search is exact `IndexFlatIP`.
4. The exported artifact contains `chunk_depth: 200`, and
   `chunk_candidates` are still raw chunk-ranked rows with repeated article IDs.
5. Dense macro article Recall@5 is `66.5833%`; raw top-50 chunk pool recall is
   `92.4167%`; mean unique articles in those 50 chunks is `37.185`.
6. Reranker weight SHA is `d9e3...5286`, inference is FP16, max length is 512,
   batch size is 16, and candidate mode is explicitly `chunk`.
7. Deduplication occurs after descending reranker sort, and evaluation takes
   five unique article IDs using macro per-question recall.

The historical clean-reproduction dense result in the repository is `66.4167%`,
whereas this A100/Ollama candidate run yielded `66.5833%`. Consequently, the
`75.00%` observation is strictly bound to the candidate and index identities
recorded above. If a reproducer gets a different dense pool, report both the
dense and reranked results rather than treating the final number alone as a
reranker discrepancy.

## Validation performed before publication

```bash
ruff check \
  scripts/build_wixqa_index.py \
  scripts/eval_wixqa_retrieval.py \
  scripts/export_wixqa_dense_candidates.py \
  scripts/eval_wixqa_bge_reranker.py

PYTHONPATH=. pytest -q \
  tests/external_datasets/test_wixqa.py \
  tests/external_datasets/test_wixqa_retrieval.py \
  tests/external_datasets/test_wixqa_public_evidence.py
```

Observed result: `17 passed`; Ruff passed. These tests validate the maintained
WixQA contracts but do not independently rerun the GPU experiment.
