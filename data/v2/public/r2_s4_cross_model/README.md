# R2-S4 Cross-Model Observation Evidence

This eight-file package contains content-free, independently recomputable dev evidence.

- Evidence status: `OBSERVATION_ONLY`
- Decision: `CONSISTENT_OBSERVATION`
- Baseline model digest: `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`
- Replication model digest: `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`
- Source Git HEAD: `109e8b52d8d31ae3562420351451a69915652be3`
- Source Git branch: `codex/rag-eval-system`
- Source Git state: `clean` (0 status entries; dirty-state SHA-256 `96a296d224f285c67bee93c30f8a309157f0daa35dc5b87e410b78630a09cfc7`)
- Private matrix manifest witness: `ec7b2fb6b8802b32d50933fc34b574d55c370dd88dbee4a88239d37ac51ff0b5`

Verify from this directory with:

```text
python verify.py .
```

The verifier uses only the Python standard library and recomputes model summaries, deltas, and the observation decision from 72 redacted rows. Public rows intentionally omit private input, nonce, and candidate-order hashes; cross-role checks align by opaque ordinal, public case class, arm order, and public-safe arm fields only. This package is not a production certification or release gate.
