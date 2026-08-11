# JD Keyword Map

Snapshot date: 2026-08-11. Sources are official employer career pages surfaced
by web search. This is a dated 12-role directional sample, not a statistical
study of the entire labor market. A role is assigned one primary group even
when its responsibilities overlap. Keyword counts are manual multi-label counts
of explicit responsibilities/requirements visible in the captured postings.

## AI Application / RAG / Agent

| Employer | Role | Signal relevant to this project | Official source |
|---|---|---|---|
| Baidu | 大模型应用开发工程师（J97670，日常实习） | application delivery, RAG, Agent architecture, business iteration | [Baidu Careers](https://talent.baidu.com/jobs/detail/INTERN/d1ed3134-5bd8-4743-a937-acca2773b1e7) |
| Baidu | 深圳-大模型算法工程师（J100681，校招） | RAG, knowledge QA, evaluation system, Python | [Baidu Careers](https://talent.baidu.com/jobs/detail/GRADUATE/fd615cd0-aebd-47c3-bb3d-6e4335e6be90) |
| Baidu | 高级算法工程师（智能体平台方向，J98193） | enterprise AI application platform, Agent task quality and stability | [Baidu Careers](https://talent.baidu.com/jobs/detail/SOCIAL/44e2693e-7f8b-47bc-82d7-de0870f59d2b) |
| NVIDIA | Applied AI Engineer, New College Grad 2026 (JR2015814) | RAG, tool-calling, agentic systems, data/MLOps pipelines, evaluation, CI/CD | [NVIDIA Careers](https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Applied-AI-Engineer--Silicon-Co-Design-Group--New-College-Grad-2026_JR2015814) |

## AI Evaluation / GenAI Evaluation

| Employer | Role | Signal relevant to this project | Official source |
|---|---|---|---|
| Baidu | 大模型评估实习生（J100544） | test execution, result analysis, quality tracking, evaluation automation, Python | [Baidu Careers](https://talent.baidu.com/jobs/detail/INTERN/ac9bfc68-f403-42e4-803d-13ad690293b8) |
| Baidu | 上海-AI测试开发工程师（J101057，校招） | correctness/safety/robustness/performance evaluation, test assets, root-cause analysis | [Baidu Careers](https://talent.baidu.com/jobs/detail/GRADUATE/fea4ea6b-86a6-4a22-807f-b9dc6fa116a6) |
| Baidu | 大模型评测算法工程师（J100902） | benchmarks, rubric, human/automatic evaluation, A/B tests, error analysis, release acceptance, Agent/RAG evaluation | [Baidu Careers](https://talent.baidu.com/jobs/detail/SOCIAL/24c9e591-75c8-42bd-b531-522b53fc47ac) |
| Apple | Machine Learning Engineer, ML/GenAI Evaluation (200671401-2459) | hallucination, faithfulness, groundedness, LLM judge, human evaluation, prompt regression | [Apple Jobs](https://jobs.apple.com/en-us/details/200671401-2459/machine-learning-engineer-ml-genai-evaluation?team=SFTWR) |
| Apple | ML Engineer, Automated Evaluation and Adversarial Design (200657970-0836) | automated evaluation systems, adversarial tests, multi-step/agent decision chains, release workflows | [Apple Jobs](https://jobs.apple.com/en-ca/details/200657970-0836/ml-engineer-automated-evaluation-and-adversarial-design) |
| Apple | AIML Sr ML Engineer, Evaluation (200668113) | benchmarks, evaluators, simulation, offline/device agent evaluation, failure-to-improvement loop | [Apple Jobs](https://jobs.apple.com/en-in/details/200668113/aiml-sr-machine-learning-engineer-evaluation) |
| NVIDIA | Senior Deep Learning Engineer, Model Evaluation & AI Systems (JR2012697) | evaluation frameworks, correctness, reproducibility, RAG/Agent evaluation | [NVIDIA Careers](https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/Senior-Deep-Learning-Engineer---Model-Evaluation---AI-Systems_JR2012697) |

## Python / AI Backend and Performance

| Employer | Role | Signal relevant to this project | Official source |
|---|---|---|---|
| NVIDIA | Senior System Software Engineer, Dynamo Tools (JR2021520) | reproducible performance evaluation, latency, throughput, experiment analysis, systems engineering | [NVIDIA Careers](https://nvidia.wd5.myworkdayjobs.com/nvidiaexternalcareersite/job/us-ca-santa-clara/senior-system-software-engineer---dynamo-tools_jr2021520) |

## Frequency and project mapping

| Explicit signal | Roles mentioning it | Project evidence | Resume use |
|---|---:|---|---|
| evaluation / benchmark / quality measurement | 11/12 | frozen WixQA/Enterprise/garak evidence, verifier, negative results | Strong for all three positionings |
| RAG / Agent / agentic or multi-step AI | 10/12 | bounded controller, evidence path, retrieval and rejected Agent experiments | Strong for AI Application; keep quality claim bounded |
| evaluation infrastructure / software engineering | 10/12 | typed evaluators, public artifacts, CI verifier, FTS lifecycle | Strong for Evaluation and Backend |
| failure analysis / diagnostics / adversarial analysis | 8/12 | first-loss attribution, candidate failure analysis, Guard OFF/ON | Strong differentiator |
| testing / regression / reproducibility / release workflow | 7/12 | clean replay, exact-SHA CI, fail-closed portfolio gate | Strong supporting evidence |
| Python explicitly requested | 6/12 | Python/FastAPI/pytest implementation | Use naturally; do not make a keyword list |
| business or product delivery collaboration | 6/12 | demo API and business-oriented knowledge workflow | Evidence exists for application design, not production adoption |
| latency / throughput / performance / stability | 5/12 | p95 retrieval/candidate metrics, FTS build, local Guard scan | Use measured scope; no SLO/QPS claim |
| data collection / curation / pipelines | 5/12 | canonical ingestion/lifecycle and external dataset adapters | Supporting, especially Backend |
| groundedness / safety / adversarial behavior | 4/12 | citation gate and narrow garak result | Strong but carefully qualified |
| real enterprise identity/permissions integration | 1/12 | local JWT/JWKS + ACL only | `NO_EVIDENCE` for real IdP/SSO; do not claim |
| human evaluation agreement / calibrated LLM judge | 3/12 | human campaign remains NOT_RUN | `NO_EVIDENCE`; do not add a feature for resume matching |

## Decision for this project

The market snapshot supports emphasizing evaluation discipline, RAG/Agent
failure analysis, Python engineering, reproducibility, and measured latency. It
does not justify adding another Agent framework. The largest evidence gap for
evaluation roles is human/judge agreement; because that requires real reviewers,
it remains `NO_EVIDENCE` rather than being simulated.
