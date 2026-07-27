# Quality-review packets

| Packet | Status | Use |
|---|---|---|
| `r2-s8-calibration-v3` | REJECTED | Historical preflight artifact. Its CSV hash does not survive Git LF normalization. Do not review or aggregate it. |
| `r2-s8-calibration-v4` | VERIFIED / NOT_RUN | Current 12-case public-synthetic calibration packet. Human review has not run. |

Run `python -m scripts.verify_quality_review_packet` before distributing the
current packet. A future packet must use a new packet ID; existing manifests
must not be edited in place.
