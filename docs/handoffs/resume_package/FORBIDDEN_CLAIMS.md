# Forbidden Claims

Omit or rewrite any draft containing these meanings:

- "RAG accuracy 66.42%" or "answer accuracy 60.37%".
- "Agent improved quality" or "multi-document candidate deployed".
- "Blind WixQA test", "unconsumed validation", or "independent third-party
  reproduction".
- "100% secure", "full garak passed", "universal prompt-injection defense", or
  a general benign FPR of zero.
- "Production-ready", "production SLO/QPS", "high availability", "power-loss
  safe", or "distributed multi-writer indexing".
- "Enterprise SSO/IdP integrated"; the identity source is a local JWT/JWKS
  simulator.
- "Semantic grounding guaranteed", "hallucination eliminated", or "human
  answer quality validated".
- Oracle, synthetic-development, mechanism-only, or consumed-development metrics
  presented as final quality.
- Any `NOT_RUN` capability presented as implemented or passed.
- LangGraph quality uplift, production network MCP/OAuth, durable HITL, or the
  five-case parity diagnostic presented as answer quality or production latency.
- GraphRAG, Redis, Kafka, a reranker, another model/vector database, or any other
  component listed as project capability without corresponding accepted evidence.

Fail closed: if a stronger wording cannot be mapped to
`../PROJECT_EVIDENCE_MAP.md`, mark it `NO_EVIDENCE` and remove it.
