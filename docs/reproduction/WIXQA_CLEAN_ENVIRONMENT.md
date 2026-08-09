# WixQA Clean Reproduction Environment

Captured before the registered replay on 2026-08-09.

| Field | Value |
|---|---|
| OS | Windows 10 build 26200, AMD64 |
| CPU | AMD64 Family 25 Model 97 Stepping 2, 12 logical processors |
| RAM | 33,947,549,696 bytes total |
| GPU | NVIDIA GeForce RTX 5060, 8,151 MiB, driver 610.88 |
| Python | 3.11.9 |
| requirements SHA-256 | `955c718b5a72e4a320b72e6031945f4955c0066f35c9104ca12c357cec1e65fa` |
| NumPy | 2.4.4 |
| BLAS | scipy-openblas 0.3.31.188.0, 64-bit integer, dynamic architecture |
| FAISS | 1.13.2 |
| Torch | 2.13.0+cpu; not used by the Ollama embedding path |
| Embedding service | local Ollama |
| Embedding model | `bge-m3`, F16, 566.70M parameters, dimension 1024 |
| Embedding model SHA-256 | `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab` |
| Git base before protocol commit | `37b07d23fb4d0a25cecc6cd4599f7748c7af0bcd` |

Latency is a new observation on this machine and is not required to equal the
historical machine. Ranking quality, identities, and metric semantics are bound
by the separately committed clean-reproduction protocol.
