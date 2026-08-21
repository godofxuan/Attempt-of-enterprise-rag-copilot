# AgentDojo Adaptation Decision

Decision: **REJECTED for this runtime round**. Date: 2026-08-21.

AgentDojo is a useful MIT-licensed environment for measuring utility and prompt
injection attacks in tool-using agents. It is not directly integrated here for
the following evidence-based reasons:

1. Its published workspace tools and user tasks do not match this project's
   `search/find/open` evidence semantics or the one draft-only side effect.
2. A superficial adapter would need to invent email, calendar, banking, or
   workspace behavior. That would test the invented system rather than this
   enterprise knowledge boundary.
3. A meaningful run requires selecting and fixing an LLM, attack suite, utility
   tasks, defense, versions, and costs. This task prohibits a new large model
   experiment and requires A-D reliability work first.
4. Existing retrieved-content paired tests remain the closer security evidence;
   they are narrow and must not be called general AgentDojo coverage.

No AgentDojo source, cases, package, or benchmark result was copied into the
repository. A later proposal may revisit a small subset only if a semantic map
can preserve task utility, attack success, the original denominator, and this
project's identity/ACL/tool boundaries without invented business tools.
