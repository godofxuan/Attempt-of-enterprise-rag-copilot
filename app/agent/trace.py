from app.agent.schemas import ToolTraceStep


def build_step_trace(
    *,
    tool: str,
    status: str,
    latency_ms: float,
    output_summary: str,
) -> ToolTraceStep:
    return ToolTraceStep(
        tool=tool,
        status=status,
        latency_ms=max(0.0, latency_ms),
        output_summary=output_summary,
    )
