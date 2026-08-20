# Role Positioning

## Version A: AI Application / RAG / Agent

Lead with the replaceable, host-controlled Agent Runtime and retrieval quality.
Then show retrieved-content security or evidence/replay. The core message is:
"I can build a RAG application and prove where it works or fails."

Priority evidence: P7, P1, P5, P8, P4, N1.

Do not lead with FTS implementation details unless the JD emphasizes corpus
scale or indexing.

## Version B: AI Evaluation / GenAI Evaluation

Lead with frozen protocols, metric semantics, clean replay, failure attribution,
negative experiments, and claim boundaries. The core message is: "I build
evaluation evidence that can block a weak release."

Priority evidence: P8, P1, P2, N1, P4, P6.

Do not imply LLM-as-judge or human agreement was completed; semantic answer
correctness remains unestablished.

## Version C: Python Backend / AI Platform

Lead with the one-host 511,962-row indexing lifecycle, verified staging and
activation, process-crash evidence, API identity/ACL, and deterministic tests.
The core message is: "I turn an AI workflow into bounded Python services and
recoverable data paths."

Priority evidence: P3, P7, P8, P6, P5, P2.

Do not claim distributed indexing, production SLO, real IdP integration, or HA.
