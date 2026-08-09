# Enterprise Dense Capacity Result

## Run identity

- execution SHA: `7e050e45e484e67d5e8f85cba2cd405117ed9b55`;
- corpus: 511,962 EnterpriseRAG-Bench rows, SHA-256
  `6b0747bf160af9427b12101537d53056ac592ada9831c1a98ae01fa50a8d2a9f`;
- model: BGE-M3 digest
  `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`;
- representation: 1,024-dimensional float32, 1,800/150 flat chunks;
- hardware: RTX 5060 8,151 MiB, 12 logical CPUs, approximately 31.6 GiB RAM;
- quality labels used: no;
- persistent vectors written: no.

## Qualification measurements

| Cumulative chunks | Elapsed | Throughput | Returned vector bytes | Peak process RSS |
|---:|---:|---:|---:|---:|
| 1,000 | 27.98 s | 35.739 chunks/s | 4,096,000 | 1,596,862,464 |
| 10,000 | 278.34 s | 35.927 chunks/s | 40,960,000 | 1,612,578,816 |
| 50,000 | 1,360.36 s | 36.755 chunks/s | 204,800,000 | 1,681,207,296 |

Throughput did not collapse: the 50k cumulative rate is above the 10k rate. At
the measured 50k rate, 1,702,370 chunks project to 46,316.57 seconds, or 12.87
hours of embedding. One raw vector matrix is 6,972,907,520 bytes; a second flat
index copy makes 13,945,815,040 bytes before reserve.

## Decision

`FULL_DENSE_NO_GO` for this rapid sprint. Three pre-registered gates fail:

1. projected embedding time exceeds 8 hours;
2. the project does not yet have a resumable deterministic sharded/mmap Dense
   builder for this corpus;
3. no unconsumed development-safe Enterprise quality protocol exists.

Disk and throughput-stability gates pass. The result is valuable capacity
evidence, but it is not Dense retrieval quality, production throughput, or a
resume accuracy claim. Building 12.87 hours of vectors before fixing those two
protocol/engineering gaps would add cost without adding credible evidence.
