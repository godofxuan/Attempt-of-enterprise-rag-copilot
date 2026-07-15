import time
from collections.abc import Callable

from app.agent.controller import AdaptiveController, AgentController
from app.agent.router import route_query
from app.agent.schemas import AgentChatResponse, AgentTrace, PlanStep, RouteDecision
from app.agent.tools import ToolExecutionResult, ToolRegistry, build_default_registry
from app.agent.trace import build_step_trace


class AgentRunner:
    def __init__(
        self,
        *,
        registry: ToolRegistry | None = None,
        router: Callable[[str], RouteDecision] = route_query,
        controller: AgentController | None = None,
        max_steps: int = 10,
    ) -> None:
        self.registry = registry or build_default_registry()
        self.router = router
        self.controller = controller or AdaptiveController()
        self.max_steps = max_steps

    def run(self, question: str, top_k: int | None = None) -> AgentChatResponse:
        decision = self.router(question)
        context = self.controller.initialize(
            decision,
            question=question,
            top_k=top_k,
        )
        actual_plan: list[PlanStep] = []
        step_traces = []

        while True:
            step = self.controller.next_step(decision, context)
            if step is None:
                break
            if len(actual_plan) >= self.max_steps:
                raise RuntimeError("Agent exceeded maximum step count")

            actual_plan.append(step)
            started_at = time.perf_counter()
            try:
                result = self.registry.run(step.tool, context)
                context.update(result.updates)
                status = "ok"
                output_summary = result.output_summary
            except Exception as exc:
                status = "error"
                output_summary = f"{type(exc).__name__}: {exc}"
                step_traces.append(
                    build_step_trace(
                        tool=step.tool,
                        status=status,
                        latency_ms=(time.perf_counter() - started_at) * 1000,
                        output_summary=output_summary,
                    )
                )
                raise

            step_traces.append(
                build_step_trace(
                    tool=step.tool,
                    status=status,
                    latency_ms=(time.perf_counter() - started_at) * 1000,
                    output_summary=output_summary,
                )
            )


        return AgentChatResponse(
            answer=context.get("answer", ""),
            sources=context.get("sources", []),
            trace=AgentTrace(
                route=decision.route,
                route_reason=decision.reason,
                plan=actual_plan,
                steps=step_traces,
                retrieval_attempts=context.get("retrieval_attempts", 0),
                evidence_history=context.get("evidence_history", []),
                final_outcome=context.get("final_outcome"),
            ),
        )


def run_agent_chat(question: str, top_k: int | None = None) -> AgentChatResponse:
    return AgentRunner().run(question=question, top_k=top_k)


__all__ = [
    "AgentRunner",
    "ToolExecutionResult",
    "ToolRegistry",
    "run_agent_chat",
]
