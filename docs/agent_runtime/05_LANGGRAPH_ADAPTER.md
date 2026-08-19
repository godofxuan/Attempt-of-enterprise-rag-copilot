# LangGraph Adapter

## Graph

```text
START -> analyze -> decide -> execute -> decide ... -> publish -> END
```

`analyze` uses the existing strict rule-first analyzer. `decide` invokes the
existing bounded controller for one action. `execute` enters the Tool Contract
and feeds the guarded observation back to the controller. `publish` uses the
existing response builder and citation verifier.

This is a real LangGraph `StateGraph`, not a renamed call around the old runner.
The graph owns node scheduling and state movement. It does not own identity,
ACL, retrieved-content admission, tool budgets, evidence authority, citation
verification, or final publication policy.

## Deterministic and model-assisted work

Identity, validation, budgets, ACL, Guard, evidence admission, citation checks,
and terminal publication are deterministic host nodes or dependencies. Query
analysis and claim wording may use configured model fallbacks, but their output
must pass the same strict schemas and publishing gates.

## Runaway protection

The controller has a hard step budget. The adapter also maintains a loop guard
and invokes LangGraph with a recursion limit derived from that budget. A graph
cycle therefore cannot create unrestricted tool calls. System failures produce
a source-free safe terminal.

## Current result

Fixture tests establish contract parity, one guarded search for a simple policy
question, no tools for unsafe input, and bounded termination. They do not prove
an answer-quality improvement. Stage I will determine whether the alternative
adapter offers measurable value beyond maintainability and future HITL support.

