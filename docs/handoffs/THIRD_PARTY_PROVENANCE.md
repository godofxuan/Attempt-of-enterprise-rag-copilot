# Third-party provenance and license review

- Review date: 2026-08-20
- Reviewed input: `ef9d0a919d3c002b7d868035c90b9f9624202513`
- Branch: `codex/agent-runtime-vnext`

## Scope and method

This is a repository evidence review, not a legal opinion. It inspected recent
Git history, dependency pins, imports, source headers/comments, public design
references, and the current Agent Runtime implementation. Similar code style is
not evidence of copying, and use of an AI coding tool does not reveal model
training sources. `UNKNOWN` and `NOT_VERIFIED` are used where Git cannot establish
line-level origin.

Usage classes:

- `API_USAGE`: installed/imported as a third-party package through its public API.
- `CONCEPT_ONLY`: cited as design or evaluation inspiration; no dependency/import
  or copied implementation was found in the reviewed paths.
- `ADAPTED` / `COPIED`: confirmed source derivation. None was confirmed here.
- `UNKNOWN`: available evidence cannot establish the exact origin or obligation.

## Provenance matrix

| Project component/path | External source | URL | Usage | License observed | Attribution/NOTICE requirement | Currently satisfied | Evidence and action | Unresolved risk |
|---|---|---|---|---|---|---|---|---|
| `app/agent_runtime/orchestrator.py`; `requirements.txt` | LangGraph | https://github.com/langchain-ai/langgraph | API_USAGE | MIT | Preserve MIT notice when redistributing substantial copied source; ordinary package distribution carries its package license | Yes for observed API use; no copied source found | Pinned `langgraph==1.2.11`, imports public `StateGraph`; keep dependency/SBOM and this attribution | Transitive package/model licenses require release-time SBOM review |
| `app/agent_runtime/mcp_adapter.py`; `requirements.txt` | MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk | API_USAGE | MIT | Same MIT preservation rule | Yes for observed API use; no copied SDK source found | Pinned `mcp==2.0.0`, imports `mcp.server.MCPServer`; call it official SDK API adaptation, not an internally authored protocol | Network transports are not used or security-reviewed by this project |
| `docs/AGENTIC_RAG_EVOLUTION_LOG.md` | OpenAI Agents SDK | https://github.com/openai/openai-agents-python | CONCEPT_ONLY | MIT | No code attribution triggered by concept-only reference | Yes | Docs cite tracing/guardrail concepts; package is not pinned or imported | Exact influence on individual design choices is not mechanically measurable |
| Development workflow/docs | OpenAI Codex | https://github.com/openai/codex | CONCEPT_ONLY / tool assistance | Apache-2.0 for the public Codex repository | No copied Codex source found; tool output authorship must still be reviewed by the repository owner | Partial | Git/docs show Codex-assisted review and implementation work, but no Codex package/import or copied file header | Exact line-level human/AI contribution split is NOT_VERIFIED from Git alone |
| Development workflow/docs | Claude Code | https://github.com/anthropics/claude-code | CONCEPT_ONLY / tool reference | All rights reserved; use subject to Anthropic commercial terms | Do not describe Claude Code as open source or copy its code without separate permission | Yes for reviewed repository | Docs explicitly state the core harness was not replicated and use only published behavioral concepts | Exact private-tool output provenance is NOT_VERIFIED; no private prompts are published |
| Retrieval/runtime design references | RAGFlow | https://github.com/infiniflow/ragflow | CONCEPT_ONLY | Apache-2.0 | None for concept-only reference | Yes | No package/import or copied/adapted source identified | Recheck if source snippets are introduced later |
| Retrieval design references | Haystack | https://github.com/deepset-ai/haystack | CONCEPT_ONLY | Apache-2.0 | None for concept-only reference | Yes | No package/import or copied/adapted source identified | Recheck if integration code is introduced later |
| Conditional parser research | Docling | https://github.com/docling-project/docling | CONCEPT_ONLY / NOT_IMPLEMENTED | MIT for code; individual model licenses may differ | None because parser/model was not integrated | Yes | Failure analysis did not meet the parser-ablation trigger; no dependency/import | Model-specific licenses must be checked before any future integration |
| Conditional parser research | MinerU | https://github.com/opendatalab/MinerU | CONCEPT_ONLY / NOT_IMPLEMENTED | MinerU Open Source License based on Apache-2.0 with additional commercial/online-service terms | None because it was not integrated; future use needs a fresh terms review | Yes | Mentioned only as a rejected/conditional parser option | Terms can change and are not equivalent to plain Apache-2.0 |
| Remaining packages in `requirements.txt` | PyPI dependencies | Package metadata and generated SPDX SBOM | API_USAGE | Mixed; not fully re-audited in this closeout | Follow each package and bundled model/data license | Partial | Exact pins exist and `scripts/generate_deployment_sbom.py` generates an SPDX 2.3 inventory | Some generated SBOM license fields may be `NOASSERTION`; release counsel review is not done |
| Repository-authored `app/`, `scripts/`, `tests/` | No confirmed upstream source | N/A | UNKNOWN for line-level authorship | Repository root has no declared license | A public repository without a license does not grant general reuse permission | No | No external copyright/SPDX/adapted/copied headers were found in reviewed runtime source; do not infer ownership solely from that absence | Owner must choose a repository license before inviting reuse; this audit must not choose it unilaterally |

## Findings

1. **Confirmed direct integrations:** LangGraph and the MCP Python SDK are normal
   package/API use under MIT. No copied or adapted upstream source was identified
   in `app/agent_runtime/`.
2. **Confirmed concept references:** OpenAI Agents SDK, RAGFlow, Haystack,
   Docling, and MinerU are referenced as design or rejected research options, not
   imported implementations.
3. **Claude Code is not treated as open source:** its public repository license is
   all-rights-reserved/commercial-terms wording. Existing project docs correctly
   say the core harness was not replicated.
4. **AI assistance is only partially auditable:** repository history and docs
   establish that Codex/Claude-related tools were used in parts of the workflow,
   but Git cannot prove the exact contribution split or source of each generated
   line. No private prompts or local private paths are included in this record.
5. **No project LICENSE:** the repository is publicly visible but currently does
   not declare reuse rights for repository-authored code. This is an unresolved
   publication boundary, not a reason to invent a license or NOTICE in this task.
6. **No new attribution file is legally triggered by observed usage:** this review
   found package API usage and concept references, not confirmed copied source.
   The provenance document itself supplies transparent source links. A future
   source copy, vendoring step, release bundle, or model/data integration must
   reopen the review.

## Owner-approved interview disclosure

The repository facts support this bounded wording, while the precise line-level
contribution split remains `NOT_VERIFIED` from Git alone:

> I defined the architecture boundaries, permission and state invariants,
> evaluation protocols, failure gates, and final acceptance. Claude Code/Codex
> assisted with code search, boilerplate implementation, test generation, and
> refactoring. Every resume claim is traceable to source, tests, evidence
> artifacts, and known limitations, and I can explain and modify those paths.

Do not place AI-assistance wording in the main resume project bullets unless an
application explicitly asks for it. Use it when ownership or development process
is asked in an interview.

## Reopen conditions

Re-run this review before adding vendored code, copied examples, new model/data
weights, a production network MCP transport, a parser such as Docling/MinerU, a
repository LICENSE, or a distributable release artifact.
