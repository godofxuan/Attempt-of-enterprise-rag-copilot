# External Benchmark Fixtures

## NVIDIA garak latent report v1

`garak_latent_report_v1.json` is a deterministic subset derived from NVIDIA garak's `latentinjection.LatentInjectionReport` probe. The source repository is Apache-2.0 licensed.

- Repository: `https://github.com/NVIDIA/garak`
- Revision: `afae291b684ae64055d53a0ea4228f7e760392ba`
- Probe file SHA-256: `b3adec0de41b34cc0f4bcc783d035fd2cd85d9afc9e5a9d9bb1164bd33cabfad`
- Payload file SHA-256: `921a2034153eee00969c2e3add201709d4e6083968921f230b56390d92ec5c7b`
- Upstream license SHA-256: `b2c6b7794a4b137b5e5e4fe9efb9771f35b6f466d0ea6704bedc649a0cd0f7f0`
- Generated fixture SHA-256: `9494a20d7ba6c995400ac48f05e59aab78460f5dd1cdcb0f605186b450f381c6`

The 12 attack cases use official report contexts 0 and 3, all three official injection instructions, official payload indices 0 and 3, and official trigger index 0. Four benign controls remove the injection marker from each official report context. `scripts/build_garak_latent_report_fixture.py` parses static class assignments with Python's AST and refuses source/hash/revision drift.

This is not the full garak benchmark. It tests one external retrieved-report indirect-prompt-injection probe. It does not establish general jailbreak, arbitrary tool-misuse, or full agent-security performance.

## NVIDIA garak latent report combination-disjoint holdout v1

`garak_latent_report_holdout_v1.json` was frozen before the retrieved-content
guard was changed in response to the development run. It uses the same pinned
upstream source but selects only combinations absent from the development
fixture:

- report contexts 1 and 2;
- all three official injection instructions;
- official payload indices 1 and 4;
- official trigger index 1;
- benign controls from contexts 1 and 2;
- generated fixture SHA-256: `babd8bd8e52f3b8d63bffcb526de426af550ad1f791eaddb7431d0a6b314643c`.

This is a small combination-disjoint holdout within one garak probe, not a
probe-family-disjoint or benchmark-wide test. Its two benign controls are too
few to support a precise general false-positive-rate claim.
