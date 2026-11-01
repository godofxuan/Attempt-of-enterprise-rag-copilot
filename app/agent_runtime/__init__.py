"""Stable legacy exports loaded only when explicitly requested.

Importing the product tool loop must not initialize old graphs, evaluation or MCP.
"""
from importlib import import_module

_EXPORTS = {
    'AgentOrchestrator': 'app.agent_runtime.orchestrator',
    'AccessRequestDraft': 'app.agent_runtime.side_effects',
    'AccessRequestDraftArguments': 'app.agent_runtime.side_effects',
    'AgentArtifactTrace': 'app.agent_runtime.evalops_artifact',
    'AgentHarnessRunner': 'app.agent_runtime.harness_contract',
    'AgentTelemetry': 'app.agent_runtime.telemetry',
    'AgentEvent': 'app.agent_runtime.trajectory',
    'AgentEventDraft': 'app.agent_runtime.trajectory',
    'AgentRunRequest': 'app.agent_runtime.orchestrator',
    'AgentRunResult': 'app.agent_runtime.orchestrator',
    'AgentRuntimeABArtifact': 'app.agent_runtime.evaluation',
    'AgentRuntimeABCase': 'app.agent_runtime.evaluation',
    'AgentRuntimeABRow': 'app.agent_runtime.evaluation',
    'AgentRuntimeScenarioNavigator': 'app.agent_runtime.evaluation',
    'AgentRunArtifactV1': 'app.agent_runtime.evalops_artifact',
    'AgentTrajectoryReplay': 'app.agent_runtime.replay',
    'BoundedControllerAdapter': 'app.agent_runtime.orchestrator',
    'DurableApprovalRequest': 'app.agent_runtime.durable_orchestrator',
    'DurableAccessRequestWorkflow': 'app.agent_runtime.durable_orchestrator',
    'DurableLangGraphOrchestrator': 'app.agent_runtime.durable_orchestrator',
    'DurableToolRunRequest': 'app.agent_runtime.durable_orchestrator',
    'DurableToolRunResult': 'app.agent_runtime.durable_orchestrator',
    'HumanReviewDecision': 'app.agent_runtime.orchestrator',
    'HumanReviewRequest': 'app.agent_runtime.orchestrator',
    'EnterpriseKnowledgeMCP': 'app.agent_runtime.mcp_adapter',
    'LangGraphOrchestratorAdapter': 'app.agent_runtime.orchestrator',
    'MCPContextBroker': 'app.agent_runtime.mcp_adapter',
    'SQLiteTrajectoryStore': 'app.agent_runtime.trajectory',
    'SQLitePolicyAuditStore': 'app.agent_runtime.tool_policy',
    'SQLiteSideEffectStore': 'app.agent_runtime.side_effects',
    'PolicyDecision': 'app.agent_runtime.tool_policy',
    'PolicyHookDispatcher': 'app.agent_runtime.tool_policy',
    'ToolPolicy': 'app.agent_runtime.tool_policy',
    'ToolPolicyInput': 'app.agent_runtime.tool_policy',
    'ToolRisk': 'app.agent_runtime.tool_policy',
    'TraceIdentity': 'app.agent_runtime.telemetry',
    'HarnessOutputV1': 'app.agent_runtime.harness_contract',
    'HarnessRequestV1': 'app.agent_runtime.harness_contract',
    'ToolContext': 'app.agent_runtime.tool_contract',
    'ToolDefinition': 'app.agent_runtime.tool_contract',
    'ToolError': 'app.agent_runtime.tool_contract',
    'ToolGateway': 'app.agent_runtime.tool_gateway',
    'ToolRequest': 'app.agent_runtime.tool_contract',
    'ToolResult': 'app.agent_runtime.tool_contract',
    'TrajectoryRecorder': 'app.agent_runtime.trajectory',
    'build_agent_run_artifact': 'app.agent_runtime.evalops_artifact',
    'replay_trajectory': 'app.agent_runtime.replay',
    'run_agent_runtime_ab': 'app.agent_runtime.evaluation',
    'verify_agent_run_artifact': 'app.agent_runtime.evalops_artifact',
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module(module), name)
    globals()[name] = value
    return value
