# Complete Git Commit Index

> 中文说明：这是从仓库建立到 E18 实现提交的逐提交原始索引。
>
> Cutoff: `ecdc3b7a3391d96c5c1587f57def33ae3f1e113a`
>
> Count: `215` commits. 本次纯文档收口提交自身将在下一次索引刷新时纳入。

阶段解释、代码位置、验证结果和已知限制见 [00_PROJECT_EVOLUTION.md](00_PROJECT_EVOLUTION.md)。

| No. | Date | Commit | Subject |
| ---: | --- | --- | --- |
| 1 | 2026-03-25 | [`d80fc22`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/d80fc223969dbe14111d0ed3044dd9ea6271f98a) | Initial commit |
| 2 | 2026-05-18 | [`d7d2421`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/d7d2421d7543b3b20e44e03ea55ac9a5b5bc1fcc) | Prepare Enterprise RAG Copilot |
| 3 | 2026-05-18 | [`1cf4057`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/1cf4057d8b3678cdfb891f82c220bc0cb49031a3) | Delete README.md |
| 4 | 2026-05-18 | [`c8f5314`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/c8f5314eec2a2a8b8c8f72fe70078aaecb6a0d79) | Resolve README merge conflict |
| 5 | 2026-05-18 | [`cfba324`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/cfba3243d3134ceeb3da43b518756aadaba3f6ab) | Merge remote-tracking branch 'origin/main' |
| 6 | 2026-06-01 | [`1052e5e`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/1052e5e6568d4e38686ceb994ef77885737d3974) | Add enterprise RAG evaluation system |
| 7 | 2026-07-14 | [`a2b43df`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/a2b43dfb258cea918bcb3942b6b0aff0b5e2a9a4) | docs: design agent action evaluation |
| 8 | 2026-07-14 | [`c264152`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/c264152c3150524672ddc1b5584342f95dda6bb6) | docs: plan agent action evaluation |
| 9 | 2026-07-14 | [`943a78b`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/943a78b6431ef7a761c68abcb725a241e37a4c89) | docs: design adaptive evidence loop |
| 10 | 2026-07-14 | [`62c1f99`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/62c1f99ad4e19c098e42a87984c713e0c274d572) | docs: plan adaptive evidence loop |
| 11 | 2026-07-15 | [`7aec4b9`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/7aec4b950e012d3f24b8e1877d6391201e9b8f90) | feat: add evaluated adaptive agentic RAG loop |
| 12 | 2026-07-17 | [`b8b8e8b`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/b8b8e8b8913cec91ddd165c47596ba05b718d2b6) | feat: complete enterprise agentic RAG v2 |
| 13 | 2026-07-17 | [`68731b2`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/68731b25cab49afbc313ce54a2c82d092a80728c) | fix: preserve frozen artifact bytes across clones |
| 14 | 2026-07-17 | [`960fa13`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/960fa134d72cc45a64344016b3b728c07d05930c) | fix: make chunking ablation test clone-safe |
| 15 | 2026-07-17 | [`a628dfe`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/a628dfe02b78dfe8c6a6cbc9b9ca4be4a485858a) | ci: expose native test crashes |
| 16 | 2026-07-17 | [`9607e55`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/9607e55ec0fc12e98d1f61e199bfbf6ac12a0eee) | fix: avoid pyarrow test-only dataframe round trip |
| 17 | 2026-07-17 | [`da2ba8c`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/da2ba8ccd4dcce455926758a8e9fb6fad20aec38) | docs: close E7 GitHub acceptance |
| 18 | 2026-07-17 | [`ce1ec9e`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/ce1ec9e5adb5f9ae253e6a9423747ea618344a22) | docs: specify indirect prompt injection threat model |
| 19 | 2026-07-17 | [`c1c47df`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/c1c47dfe88c42c309afc32faa9bc6584e90e89ac) | test: add retrieved-content injection red-team cases |
| 20 | 2026-07-17 | [`ec85cc7`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/ec85cc718b3df17731fb1d9df7300a3a7c6fe5be) | feat: add deterministic retrieved-content guard core |
| 21 | 2026-07-17 | [`8606432`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/86064322fd532264623abd23e8db7a99634ab342) | feat: enforce guarded retrieved-content boundary |
| 22 | 2026-07-17 | [`0946ad9`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/0946ad90a7d9b54e219006b271c7c7bdc440863c) | feat: complete R2-S1 D5 security boundaries |
| 23 | 2026-07-18 | [`4b7d0b9`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/4b7d0b91078a3246cb9e801631c0a47691bf3985) | feat: complete R2-S1 D6 security evaluation gate |
| 24 | 2026-07-18 | [`1bf9b95`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/1bf9b95917d7ae813ca6214c7ab83492b4c47aa3) | feat: complete R2-S1 D7 live paired evaluation |
| 25 | 2026-07-19 | [`9fcb304`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/9fcb3041ae3561057e1b56d881e91aab8aee0dce) | security: harden indirect-injection evaluation evidence |
| 26 | 2026-07-19 | [`073d735`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/073d7356026954c26c1429fb9faddc5e9a5dcb87) | docs: record R2-S1 closeout delivery |
| 27 | 2026-07-19 | [`04e9b1e`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/04e9b1e79a66d63598537c273cdbf9b026550e50) | docs: define R2-S2 holdout freeze protocol |
| 28 | 2026-07-19 | [`311fcba`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/311fcba4a0537b3dd39a236ccc4407bc9f2451bb) | docs: plan R2-S2 holdout freeze implementation |
| 29 | 2026-07-19 | [`dc1d514`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/dc1d5140a85b0e15f3dfe27bcfedfc6059c2b518) | feat: add holdout package admission contracts |
| 30 | 2026-07-19 | [`999134e`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/999134ec5671e211514a9a30cedc2314c9dd5087) | feat: freeze and verify sealed holdout packages |
| 31 | 2026-07-19 | [`eaa480c`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/eaa480c320b7284df446092e8ced57e3826d40b2) | feat: add holdout freeze operator commands |
| 32 | 2026-07-19 | [`9e202e6`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/9e202e63256580953de141aeb21fdbd46616f55b) | security: prevent raw holdout publication |
| 33 | 2026-07-19 | [`c8f5161`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/c8f5161deaa5974687339fa23fa2518ed3950309) | eval: complete R2-S2 live dev and holdout evidence |
| 34 | 2026-07-19 | [`aabcde5`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/aabcde5fb8711849c38638c7da3c903d08bf36b5) | docs: close R2-S2 implementation plan |
| 35 | 2026-07-21 | [`647005a`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/647005aad3d07a6bab95a4d59ba3262a4a672cca) | docs: define R2-S3 exposure-aware ablation |
| 36 | 2026-07-21 | [`9f6163f`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/9f6163fd1760f8fb285299ac6362dc4bad15cf1f) | docs: plan R2-S3 exposure ablation implementation |
| 37 | 2026-07-21 | [`f026071`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/f0260717af13a1127640bbee0b61aae8c87c6875) | eval: admit exact R2-S3 source evidence |
| 38 | 2026-07-21 | [`7ed0466`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/7ed04660d7ea3a3b244ae8307e422a468108a6a3) | fix: harden Task 1 source evidence admission |
| 39 | 2026-07-21 | [`e546813`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/e546813f6b6d5d9741b6a70ffdc7b770902ce25a) | fix: reject boolean Task 1 arm positions |
| 40 | 2026-07-21 | [`1254a22`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/1254a22c18c23489d174f43fdab96b95e08248ed) | eval: map attack units to runtime candidate ranks |
| 41 | 2026-07-21 | [`d7c1370`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/d7c137060c50aa150f16fc749b6830fc7c236264) | fix: validate exposure unit location state |
| 42 | 2026-07-21 | [`62c57d7`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/62c57d75e8ed6d60b00e350108e219c24b06e0e7) | eval: replay source-bound retrieved admission |
| 43 | 2026-07-21 | [`9232776`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/92327767d347b2d8c5ffe478a90e2e585d08a6b2) | fix: bind admission replay to sanitized evidence |
| 44 | 2026-07-21 | [`36fbad0`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/36fbad0528c53a491403e840e3e7f801006a8678) | eval: compute exposure-aware counterfactual metrics |
| 45 | 2026-07-21 | [`7fc7690`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/7fc769019a5de606353c10c02bc515c71c94998f) | fix: bind Task 4 evidence invariants |
| 46 | 2026-07-21 | [`2b17144`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/2b17144781189e21f1d2bbc225bfb0c07da882d2) | eval: publish immutable exposure analysis runs |
| 47 | 2026-07-21 | [`f2a332f`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/f2a332f39cfcdf7e138464f3b0e3726de3b39da8) | eval: add exposure run operator CLIs |
| 48 | 2026-07-21 | [`a544bd4`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/a544bd4301d0fccc9b03b6c33d3739f3687f666a) | fix: harden immutable exposure publication |
| 49 | 2026-07-21 | [`2ec68b3`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/2ec68b3447500ea60935615130b65fe019ccc50b) | test: cover empty-target publication race |
| 50 | 2026-07-21 | [`0a9a255`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/0a9a255c0257b5668aed8d82c839fdbbd02dbe68) | eval: export verifiable exposure evidence |
| 51 | 2026-07-21 | [`bc342e7`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/bc342e74fa48ed13f9c9fd835c371e72b77dc6ab) | fix: harden public exposure verification |
| 52 | 2026-07-21 | [`127b864`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/127b864d480ad1c87ec3290cb07a1b1c6173351e) | fix: complete public evidence hardening |
| 53 | 2026-07-21 | [`43d53b2`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/43d53b2adc0dfdd147c30183f15eb3a037f399bd) | fix: cover public unit evidence surfaces |
| 54 | 2026-07-21 | [`99453a3`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/99453a33282940799236405fac7c277f7f2757de) | fix: validate public evidence URI authorities |
| 55 | 2026-07-21 | [`7c7da38`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/7c7da385a1caa0c8a7bb92af0f22f714abd5c48f) | fix: validate public evidence host syntax |
| 56 | 2026-07-21 | [`18f48ee`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/18f48ee80047a59dffe62f653c71c6cdd731783b) | fix: allow rooted DNS evidence URLs |
| 57 | 2026-07-21 | [`ea68d5e`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/ea68d5ebeca7918d8c9f0a2bdbbf02f41fe79eac) | security: publish R2-S3 exposure evidence |
| 58 | 2026-07-21 | [`0584924`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/0584924d8dc3fd3adf0e74e515ebea3b1ee5d122) | docs: record R2-S3 exposure ablation |
| 59 | 2026-07-21 | [`d2acd6f`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/d2acd6ff02dfa508484f0b002da3ea8152a03a10) | docs: correct R2-S3 evaluator provenance |
| 60 | 2026-07-21 | [`fa42da5`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/fa42da5f627e356bfb957dc92e6f8bfe33687feb) | eval: bind exposure result recomputation |
| 61 | 2026-07-21 | [`eabe5c7`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/eabe5c7d2a42829c397d1c3c87972f1abb51f066) | eval: validate exposure source semantics |
| 62 | 2026-07-21 | [`2471d3f`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/2471d3f0878a78269650cdd20590bbad26580c34) | eval: bind replay implementation dependencies |
| 63 | 2026-07-21 | [`af5284f`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/af5284ff0ae40e0d3369eba0164e938a43d4a820) | eval: preserve exposure path identities |
| 64 | 2026-07-21 | [`2ca5118`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/2ca511825483fe9f415bd36980d08ce0577ecbaa) | eval: snapshot verified exposure bytes |
| 65 | 2026-07-21 | [`119a43c`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/119a43c012c996fb3e585fe97f8d66a21acf8d30) | audit: cover r2-s3 exposure evidence |
| 66 | 2026-07-21 | [`06b0f62`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/06b0f62fb6bc256c7c8aee882753486d388abab9) | docs: enforce r2-s3 delivery boundary |
| 67 | 2026-07-21 | [`9877ce1`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/9877ce1e9bbf51881819b0abaec1718d9656a724) | security: regenerate R2-S3 exposure evidence |
| 68 | 2026-07-21 | [`f3d6fdc`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/f3d6fdc96938df8c02b763cd9b9fcef09102f378) | docs: record fixed R2-S3 evidence lineage |
| 69 | 2026-07-21 | [`33104e1`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/33104e1f99fbb67d3a63dabf1c5808611b4d1cdb) | eval: bind publication to verified source replay |
| 70 | 2026-07-21 | [`df94d8a`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/df94d8a7367453e865556b71b2ea48a6ec887b87) | security: publish source-bound R2-S3 evidence |
| 71 | 2026-07-21 | [`bb141a0`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/bb141a0b1d5ad29945519545e936e62f9016f956) | fix: harden R2-S3 evidence verification |
| 72 | 2026-07-21 | [`e31a394`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/e31a3942fdb405517b7a11d39cc7e790a0a70c91) | fix: distinguish D7 public case identifiers |
| 73 | 2026-07-21 | [`0caf339`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/0caf3394dab6ed416670f64e08ef5af3519b2fcc) | fix: reject static path redirection in R2-S3 |
| 74 | 2026-07-21 | [`c51dc4c`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/c51dc4c746e2007b5efb6c9ef2c61364f25eb37e) | fix: harden final R2-S3 path entrypoints |
| 75 | 2026-07-21 | [`91cdaba`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/91cdabaf05f2781339559d2728bb811b9cdffec2) | docs: migrate R2-S3 evidence to final -04 |
| 76 | 2026-07-21 | [`e2bd739`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/e2bd7391d0b509dd8e82b7988bca50fa692f59d4) | fix: harden R2-S3 evidence migration bindings |
| 77 | 2026-07-21 | [`11ea23b`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/11ea23be360ce4501beedcd61985d864800d12ae) | fix: align remaining R2-S3 current gates |
| 78 | 2026-07-21 | [`47728eb`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/47728eba5c39edec28b2875581e1cc59d4421aad) | fix: close final R2-S3 review findings |
| 79 | 2026-07-21 | [`a50743f`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/a50743f90b6972a9ed13f1ba7b070d5b8521e6a5) | fix: validate audit security corpus contracts |
| 80 | 2026-07-21 | [`ffcda1b`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/ffcda1b37ceb68712ad004174309aaae9cba401c) | fix: align public audit security corpus pairs |
| 81 | 2026-07-21 | [`1ebf2ca`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/1ebf2ca2164a80a2cead24b666f506f6414eeb09) | test: fix R2-S3 CI cross-platform assumptions |
| 82 | 2026-07-22 | [`b7e8b2d`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/b7e8b2d437c8ed604edd3f4e7a6eb4bad378f857) | docs: design R2-S4 cross-model replication |
| 83 | 2026-07-22 | [`2c4226e`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/2c4226e4793f83162bc238c7f085800706bd4e68) | feat: freeze R2-S4 cross-model plan |
| 84 | 2026-07-22 | [`4c6fb12`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/4c6fb12c606b2ae23082baf02194514816e99771) | feat: add cross-model live manifest v3 |
| 85 | 2026-07-22 | [`1568c29`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/1568c29371e8ca7a8bbf6716ee898d2211ef865e) | fix: bind live v3 to cross-model plan |
| 86 | 2026-07-22 | [`dca7bd4`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/dca7bd426c4638fa69ebaba1363e5b898a483204) | feat: orchestrate restart-safe cross-model runs |
| 87 | 2026-07-22 | [`2ee31ea`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/2ee31ea492764693aff4e29fe973d57c6721d749) | fix: harden cross-model restart admission |
| 88 | 2026-07-22 | [`bcb148c`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/bcb148ca049b8fc518b06663163ca3d2c6a8eb52) | fix: bind cross-model execution environment |
| 89 | 2026-07-22 | [`972f768`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/972f7682d1008ffa37659a8c91d07fc4edea1586) | fix: bind cross-model transport policy |
| 90 | 2026-07-22 | [`a0391c3`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/a0391c3574c7fca0651e5f5010800b457e91ebf8) | feat: publish verified cross-model matrix |
| 91 | 2026-07-22 | [`31d01e1`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/31d01e16790658bc91afd529bf3a141d9bb2c111) | fix: harden cross-model matrix admission |
| 92 | 2026-07-22 | [`ac5996c`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/ac5996c2b749fb760d1b19a0aa3354bee255811f) | fix: treat pair fingerprints as model-specific |
| 93 | 2026-07-22 | [`a4b5098`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/a4b5098fe70d914407f089eefb358c172f7f9145) | feat: add public cross-model evidence verifier |
| 94 | 2026-07-22 | [`734340a`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/734340a9f8497f1bbcebe50df743b3697e9dff69) | fix: separate public evidence trust boundaries |
| 95 | 2026-07-22 | [`d8a6ad7`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/d8a6ad7a0cced372798356d12531e9fe6c58a1be) | docs: freeze R2-S4 operator protocol |
| 96 | 2026-07-22 | [`a9e0cbd`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/a9e0cbd9be3ede1101d82e2099f5e2a957dc20f1) | fix: harden R2-S4 pre-run evidence controls |
| 97 | 2026-07-22 | [`109e8b5`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/109e8b52d8d31ae3562420351451a69915652be3) | fix: preserve historical replay and public privacy |
| 98 | 2026-07-22 | [`12d6885`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/12d6885108279b5c39813634ccd2bb444fcd7f43) | docs: publish R2-S4 cross-model evidence |
| 99 | 2026-07-22 | [`c851f62`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/c851f6264d09adeda1c71f1c09ac471c52792652) | fix: allow public CI provenance in privacy scan |
| 100 | 2026-07-22 | [`a9c32b8`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/a9c32b856d01e26b1d2f0b6380d531a7b8be7ac2) | test: isolate cross-model production index fixture |
| 101 | 2026-07-23 | [`d753df3`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/d753df3915dd78ef930a10ea1e8324e994ed5b91) | feat: harden trusted identity boundary |
| 102 | 2026-07-23 | [`1189253`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/11892531451750609f44138b7348f16b9b1316ff) | fix: bind identity lifecycle to held filesystem objects |
| 103 | 2026-07-23 | [`e657bea`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/e657beaf7d184409b2d7574c974733cbd7233f4e) | docs: record R2-S5 exact-SHA acceptance |
| 104 | 2026-07-24 | [`184913e`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/184913e5e504b150d3959ae541cc808544ac379e) | feat: expand versioned enterprise corpus |
| 105 | 2026-07-24 | [`6c419b1`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/6c419b13ce5751943403a7e2c031de1d3acbc08e) | docs: bind corpus expansion evidence |
| 106 | 2026-07-24 | [`1ce0e82`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/1ce0e82ee5e98a532cc1768b757935e8280c232e) | docs: record corpus expansion CI acceptance |
| 107 | 2026-07-24 | [`9bdc14e`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/9bdc14ea07599b96c3b3e53dccf73df24dded73d) | fix: harden frozen bundle snapshot reads |
| 108 | 2026-07-24 | [`d465eed`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/d465eedb80cae4bc7b2e3be71b782ad565cc188e) | docs: record corpus closeout incident |
| 109 | 2026-07-27 | [`5570d02`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/5570d022cd0be73625748a07a9fcea26eaa97630) | feat: harden enterprise knowledge lifecycle |
| 110 | 2026-07-27 | [`71e26d6`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/71e26d667d49a5573546e703e7a9fbb78803906d) | fix: unify Windows evidence publication |
| 111 | 2026-07-27 | [`f081ccb`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/f081ccbb284feba6af30f38024e87d1c7b273a9d) | docs: close G10 with reproducible evidence |
| 112 | 2026-07-27 | [`d7578e4`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/d7578e4348989de82b6342341e1846b4c276d20c) | feat(evaluation): add independent quality evidence gates |
| 113 | 2026-07-27 | [`4223dba`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/4223dba0ddcf28c6c3494c47bf2d4dd72c00d13f) | fix(evaluation): canonicalize review packet newlines |
| 114 | 2026-07-27 | [`93814f0`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/93814f0dd9e59a797b2dc7dc6ec1b44c01522723) | fix(ci): make clean-checkout evidence reproducible |
| 115 | 2026-07-27 | [`908a79c`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/908a79c259dce7bfc83d0a0d72ccf9062b509f35) | fix(filesystem): enforce Linux no-replace publication |
| 116 | 2026-07-27 | [`c95f9ff`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/c95f9ff834c951f8c2e518e5d0c27d6302b3bd67) | feat(evaluation): add operator-owned review campaigns |
| 117 | 2026-07-27 | [`7edff9b`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/7edff9b0f132d7844f48915dcd052a627f663cdf) | feat(deployment): add auditable Linux rollback contract |
| 118 | 2026-07-27 | [`66dd2b8`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/66dd2b8571ab935fbdb064d2e70c71d427902be7) | fix(ci): redirect container caches to tmpfs |
| 119 | 2026-07-27 | [`00e4669`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/00e4669019da1a66a0ccd6c53ae41d380ebaa3b3) | fix(ci): isolate container index state on tmpfs |
| 120 | 2026-07-27 | [`ba119a2`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/ba119a22a6b02043b1619a8b256fb71ef33de1a4) | fix(ci): secure deployment drill bind mounts |
| 121 | 2026-07-27 | [`0ee3ba2`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/0ee3ba2536dc9a4d0549fde69bd30c6c96b02f04) | fix(ci): apply smoke directory mode as root |
| 122 | 2026-07-27 | [`3123133`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/31231333c8a0cf88973ac90333c407b89d181ee3) | fix(ci): preserve private deployment handoffs |
| 123 | 2026-07-27 | [`9517266`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/951726601213b9b9a75b6ec4016fc87ad0331dfd) | docs(deployment): close out R2-S9 evidence [skip ci] |
| 124 | 2026-07-27 | [`c15da4e`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/c15da4e8c8a3dca95125c5bb26c6952a1c6030ec) | docs: add complete project evolution history [skip ci] |
| 125 | 2026-07-28 | [`25c00e4`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/25c00e41c3a7b662188fb42b09f9a36120058610) | test(agent): reproduce citation fail-open leakage |
| 126 | 2026-07-28 | [`0b8ef0a`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/0b8ef0a3c9254bcaed22b24fcae381bd6d4130b2) | fix(agent): strengthen deterministic citation checks |
| 127 | 2026-07-28 | [`2ca1cd4`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/2ca1cd432fd8467239bf5cea93281cf01ce20165) | fix(agent): rebuild answers from supported claims |
| 128 | 2026-07-28 | [`0998be4`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/0998be4a5769ea115116b54e204eab6c91f14365) | test(evaluation): enforce citation gate in fake attack flow |
| 129 | 2026-07-28 | [`87467ba`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/87467ba3ce53496c7bbf27d324ea94239e7d1f95) | docs(agent): clarify grounding and controller boundaries |
| 130 | 2026-07-28 | [`723543a`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/723543ac727f374464e141f80a4420dbaeb255d6) | feat: add resumable FinanceBench retrieval track |
| 131 | 2026-07-28 | [`5d612ea`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/5d612ea9c6c72039e76846c71d46d16e7f29c733) | fix: route runtime caches to writable container storage |
| 132 | 2026-07-28 | [`c815c39`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/c815c39c747357a39fef86aae97014459f940363) | feat(eval): add frozen FinanceBench page retrieval |
| 133 | 2026-07-28 | [`a2527e6`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/a2527e6834371e1121836cd403d1090ab49e948b) | fix(eval): normalize FinanceBench evidence pages |
| 134 | 2026-07-28 | [`d1b2975`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/d1b2975b7b45cae1abc3696262da1fcf165a4380) | docs(eval): record frozen FinanceBench page results |
| 135 | 2026-07-28 | [`f33e2ab`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/f33e2abcb942ace3931d57530d4bca1d4dd258a5) | feat(eval): add FinanceBench page candidate ranking |
| 136 | 2026-07-28 | [`14adcab`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/14adcabf24ed4b3470a30042ef02b262b2e7bc3c) | feat(retrieval): add guarded local page reranker |
| 137 | 2026-07-28 | [`18e2665`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/18e2665da0a712c4b18b44ab4075fcab2ada94f7) | fix(eval): isolate page reranker timeout budget |
| 138 | 2026-07-28 | [`e4fde24`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/e4fde24328bf9c57e0fcb7e1f06314662a0c8918) | feat(eval): fuse dense and local page rankings |
| 139 | 2026-07-28 | [`89b64af`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/89b64afb7b58f2d23744186089ea8281a1c47199) | fix(retrieval): retry invalid page ranking protocol |
| 140 | 2026-07-28 | [`e032178`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/e032178923b9a35c6eb52060b770ffa2da6172b6) | feat(eval): record page ranking confidence scores |
| 141 | 2026-07-28 | [`ba3dd0e`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/ba3dd0e65240c8bd79a96c176dd7d1df37d019d0) | feat(retrieval): gate page reranking by dense confidence |
| 142 | 2026-07-28 | [`daefac1`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/daefac1f4dcc7dd0c1d30dc45d3108aeb94d34e6) | fix(eval): preserve older reranker run verification |
| 143 | 2026-07-28 | [`f14ef84`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/f14ef840231275bfebed6bc014056d02be26cf3d) | docs(eval): record FinanceBench reranker tradeoffs |
| 144 | 2026-07-28 | [`d32d65e`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/d32d65e55936348d4d8f460694d80ec7726443e1) | feat(eval): add FinQA numerical holdout track |
| 145 | 2026-07-28 | [`64f68a8`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/64f68a8e66d60b841a04148bc1ba57f500bd434f) | fix(eval): classify FinQA model identity transport |
| 146 | 2026-07-28 | [`438906e`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/438906e9de7d2cf2efceffa6c161488c7e1fec8b) | fix(eval): keep FinQA schema Ollama compatible |
| 147 | 2026-07-28 | [`98fe07f`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/98fe07f6cc83b960b959de9f2167f580ab682d92) | feat(eval): separate FinQA strict and presentation accuracy |
| 148 | 2026-07-28 | [`7ce9a60`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/7ce9a60a2b19bd79208eb20aeb69e95a0dfbc569) | fix(eval): isolate FinQA protocol failures per case |
| 149 | 2026-07-28 | [`900e685`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/900e6850583e741f98e2c7ca11a95af69f281e77) | feat(agent): add guarded calculator path for FinQA |
| 150 | 2026-07-29 | [`3458c3b`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/3458c3b869dc8bfc272c887d8437cad58a0f1ea9) | fix(agent): simplify FinQA calculator planning contract |
| 151 | 2026-07-29 | [`40a876c`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/40a876c577a0631059eabac4c0073f970e768116) | fix(eval): clarify financial expression semantics |
| 152 | 2026-07-29 | [`c7042e5`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/c7042e58c938952166db54631e2b5e113d691b70) | fix(eval): preserve increase-rate planning |
| 153 | 2026-07-29 | [`3c2ed21`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/3c2ed21cc1604a99e6e6a445cbea1ef17763b8c9) | feat(eval): enforce frozen FinQA holdout identities |
| 154 | 2026-07-29 | [`ef4d596`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/ef4d596164518802fe3950e110a7978365b11e06) | docs(eval): freeze FinQA external holdout protocol |
| 155 | 2026-07-29 | [`d2abae8`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/d2abae875f0378d5540bdac6ba7019a0a1160585) | fix(eval): accept FinQA single-row tables before execution |
| 156 | 2026-07-29 | [`3513997`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/35139977635cfb31bc1829b1e11422151a9905d6) | docs(eval): refreeze FinQA after schema-only incident |
| 157 | 2026-07-29 | [`f903485`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/f9034858ccd16d3b4ecb7df4dc992d65078afd31) | docs(eval): publish FinQA holdout evidence and limits |
| 158 | 2026-07-29 | [`87d2f0c`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/87d2f0c7bd05fdbaeee20d34e7c8cb2f85c07e32) | feat(eval): add FinQA dev failure diagnostics |
| 159 | 2026-07-29 | [`cba451a`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/cba451a7c221d8b6dfa464487261baae6d6fbed6) | docs(eval): publish FinQA dev failure analysis |
| 160 | 2026-07-29 | [`7b1cbc6`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/7b1cbc60dce1180ead2494d7f0fe70625fd4485e) | docs(learning): explain FinQA results and diagnostics |
| 161 | 2026-07-29 | [`a4a0663`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/a4a06639c9971981c237b1f35bd744f516bfe085) | feat(eval): add bounded FinQA plan review |
| 162 | 2026-07-29 | [`a9c5c04`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/a9c5c04e67fd5e9ecc26a430cda8ec9e34a601c1) | fix(eval): align FinQA reviewer scale contract |
| 163 | 2026-07-29 | [`7876a3a`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/7876a3aaf05bbb802b72fc17d506986a3aa7d048) | feat(eval): add bounded FinQA candidate adjudication |
| 164 | 2026-07-29 | [`d88c3ff`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/d88c3ff06033d2c35ce86ebd50ff2edab973581b) | docs(eval): freeze disjoint FinQA review validation |
| 165 | 2026-07-29 | [`69b7d72`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/69b7d72ed01be64ebb776f2c08ca5c4d9182a501) | fix(eval): record FinQA model runtime backend |
| 166 | 2026-07-29 | [`538a78d`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/538a78de3718c6c77363ab99da49e1278c56a693) | docs(eval): record FinQA review validation |
| 167 | 2026-07-29 | [`e59d9e4`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/e59d9e4fb722e00b99a0b30108a20829bf1cbf7c) | feat(eval): add resumable case checkpoints |
| 168 | 2026-07-29 | [`08a3f62`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/08a3f62ab28ef5284419724cd9a0a20af75c37be) | feat(eval): add runtime uncertainty gating |
| 169 | 2026-07-29 | [`ed1a59c`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/ed1a59ca24c2159fa7c09cf461db1e74939c078b) | docs(eval): publish uncertainty gating evidence |
| 170 | 2026-07-29 | [`65257e9`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/65257e9971a19c58b9b361684f787e86190d6e77) | feat(eval): add end-to-end selective FinQA runner |
| 171 | 2026-07-29 | [`0e0a7f5`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/0e0a7f51a509e82e825dc7caaf808d811c2e565e) | test(eval): freeze selective FinQA cohort |
| 172 | 2026-07-29 | [`454d498`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/454d498b0eff534fbe985d0a7ea96364646f171d) | fix(eval): bind stable CUDA review options |
| 173 | 2026-07-29 | [`6112b54`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/6112b543245232f78887142cfcbb309f1e2ee882) | test(eval): freeze selective FinQA protocol v2 |
| 174 | 2026-07-29 | [`d2a6bf9`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/d2a6bf945b5d3c724ed03aa6288fb609f5bc54cd) | docs(eval): publish selective FinQA evidence |
| 175 | 2026-07-29 | [`904c129`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/904c129937bc85a1de5edd570d8f4e9b096cc5fd) | test(eval): define typed FinQA program contract |
| 176 | 2026-07-29 | [`b63c87e`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/b63c87e6332da425a4dd52ce765627ece2c9843a) | feat(eval): extract typed FinQA numeric candidates |
| 177 | 2026-07-29 | [`a783c18`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/a783c18f15b2f91d2bc6abe11ad8f7ffa8d8e92d) | feat(eval): add typed FinQA program execution |
| 178 | 2026-07-30 | [`9ee80ac`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/9ee80ac7b9e8f030a30ea6005c5e8a118e81c087) | feat(eval): select multiple typed FinQA programs |
| 179 | 2026-07-30 | [`9180b7e`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/9180b7ecd61bbabc1f00edc2929877c471fa769b) | feat(eval): freeze typed FinQA retrospective |
| 180 | 2026-07-30 | [`57d1bee`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/57d1bee8425c01b1097e15709dfd6a3371ad79a5) | eval(finqa): record rejected typed retrospective |
| 181 | 2026-07-30 | [`ac8424d`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/ac8424d23002e2d74e2f36fed32c45d9e8e46a7b) | eval(finqa): freeze typed contract calibration |
| 182 | 2026-07-30 | [`fbcc693`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/fbcc693505529d3c9b1d3c8e900667a857834eac) | feat(finqa): calibrate typed contract v2 |
| 183 | 2026-07-30 | [`39d8edf`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/39d8edf850b69b380677e24d4927210ecfa26b4d) | eval(finqa): add typed contract calibration runner |
| 184 | 2026-07-30 | [`80eac2f`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/80eac2f1e7cd03c12d188b21478a943d43dcf5dd) | fix(finqa): reduce typed planner candidate noise |
| 185 | 2026-07-30 | [`66a464b`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/66a464bf0f4ccbd40f71dca491f395ab4e5acafe) | refactor(finqa): compile typed sketches on host |
| 186 | 2026-07-30 | [`750d7ae`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/750d7aee57e9106cafe5202e824b6c28dddaa7cd) | eval(finqa): close typed contract calibration |
| 187 | 2026-07-30 | [`1467aba`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/1467abaeec6f6cd03bfb50f7b0fff10db67b16c2) | eval(finqa): freeze numeric evidence gate |
| 188 | 2026-07-30 | [`6422f70`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/6422f70cd42ec89b2a35bd45817657625fe4be6b) | docs(finqa): correct numeric input gate semantics |
| 189 | 2026-07-30 | [`6655ee8`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/6655ee80755455ae52f41c468c878c624a01b0e6) | feat(finqa): harden numeric evidence inputs |
| 190 | 2026-07-30 | [`f6d5973`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/f6d597385f9b86460c3bdc504a92f0cadc87b8ee) | docs(finqa): publish numeric evidence gate |
| 191 | 2026-07-30 | [`428af16`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/428af166e73e15d727bb1e15bbdacfddf9e17329) | eval(finqa): freeze v2.3 paired calibration |
| 192 | 2026-07-30 | [`4a1f8e4`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/4a1f8e4de9000adfef3ab115f7e03923b8e84b31) | feat(finqa): add v2.3 paired calibration runtime |
| 193 | 2026-07-30 | [`ce3fac5`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/ce3fac5399b128c97751efc851e54e26ad872971) | eval(finqa): close rejected v2.3 calibration |
| 194 | 2026-07-30 | [`5a5f474`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/5a5f4741d49539c12ffe24c029600fa1420699c0) | eval(finqa): freeze semantic planning calibration |
| 195 | 2026-07-30 | [`df53f7b`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/df53f7ba83fb423f9fa361bff1770fe07dee8004) | feat(finqa): add semantic planning calibration |
| 196 | 2026-07-30 | [`f138efc`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/f138efcf08aaf90a848a10908f1855ba634fc37e) | eval(finqa): close rejected semantic planning calibration |
| 197 | 2026-07-30 | [`e7be330`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/e7be3301edffe97d2c286a37ad118c75a89dafda) | eval(finqa): freeze role compatibility input gate |
| 198 | 2026-07-30 | [`6c2f79b`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/6c2f79bdf82780d56c0f694685d4713dcd642048) | feat(finqa): add role compatibility input audit |
| 199 | 2026-07-30 | [`928e88b`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/928e88b3e0b5deb0744d580ab7d9ae3baa3d52f2) | fix(finqa): correct role compatibility audit accounting |
| 200 | 2026-07-30 | [`2d28f4d`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/2d28f4d8fae8da73d5d99c6b3319d02449f0aa57) | fix(finqa): separate conditional compatibility retention |
| 201 | 2026-07-30 | [`e4bfb00`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/e4bfb007818f9ee88754994ca17834b3c30c3c4a) | eval(finqa): publish rejected role compatibility audit |
| 202 | 2026-07-30 | [`3e90d63`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/3e90d63de935ccbc556e6c19293fc20862370573) | eval(finqa): freeze role compatibility v2 gate |
| 203 | 2026-08-02 | [`43e4181`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/43e4181d26276a944e36ac1a2b30e429b44fbfa3) | feat(finqa): complete descriptor ranking and shadow gates |
| 204 | 2026-08-02 | [`09aabf5`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/09aabf551603c37bf315e6db5ab3f7c3ec247850) | feat(finqa): add isolated shadow replay gate |
| 205 | 2026-08-02 | [`1ff1707`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/1ff17078847db146d770a37003763ff0587e399b) | test(finqa): skip private replay data in clean CI |
| 206 | 2026-08-02 | [`43efb35`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/43efb359622cb2baa4ee935c47769a6da9940fca) | docs(finqa): close E13 remote delivery [skip ci] |
| 207 | 2026-08-02 | [`3e5ebb8`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/3e5ebb813668f01bb88227373062789abe3580eb) | feat(finqa): add bounded shadow worker pool |
| 208 | 2026-08-02 | [`9909d57`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/9909d5746bf5ae1b5bb1c57bce222bf44c6159fe) | docs(finqa): close E14 remote delivery [skip ci] |
| 209 | 2026-08-02 | [`bd35fa1`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/bd35fa1e62ab5c30a87414c6b5e4fd12a0362b23) | feat(finqa): measure local shadow capacity envelope |
| 210 | 2026-08-02 | [`f3dcb30`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/f3dcb301f6d20e24603f9845440416c063b249f9) | docs(finqa): close E15 remote delivery [skip ci] |
| 211 | 2026-08-02 | [`2143ba7`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/2143ba7f9d0c868926192b064b6a72e95839b3ca) | feat(runtime): add default-off service dark observation |
| 212 | 2026-08-02 | [`8625040`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/8625040becaf13d9c5bd36827cfc85f382c6f257) | docs(runtime): close E16 remote delivery [skip ci] |
| 213 | 2026-08-03 | [`2e6a882`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/2e6a882a79e16b740c893eab792035e13d4d67f4) | feat(finqa): add online typed shadow adapter |
| 214 | 2026-08-03 | [`995f70e`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/995f70eb3dfe7978f474fde5381c556080800f21) | docs(finqa): close E17 remote delivery [skip ci] |
| 215 | 2026-08-03 | [`ecdc3b7`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/ecdc3b7a3391d96c5c1587f57def33ae3f1e113a) | feat(finqa): build admitted evidence typed context |

## 范围说明

- 本索引由 `git log HEAD --reverse` 机械生成，不做“只保留重要提交”的人工筛选。
- merge、CI 修复、跨平台修复和文档收口都属于真实工程过程，因此一并保留。
- Cutoff 之后的新提交不会预先写入自己的未知 SHA；最新原始历史以 GitHub Commits 页面为准。
- 私有运行产物、密钥、模型权重、缓存和被 `.gitignore` 排除的本地活动不属于公开提交历史。
