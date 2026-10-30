"""Readable projection of existing run events; no new runtime or decisions."""

from typing import Any, Literal
from pydantic import BaseModel


class RunEventView(BaseModel):
    seq: int
    actor: Literal["model", "tool", "program"]
    action: str
    status: str
    observation: str
    details: dict[str, Any] | None = None


def project_run_events(events):
    output = []
    for event in events:
        kind = event["kind"]
        data = event["data"] if isinstance(event["data"], dict) else {}
        seq = event["seq"]
        if kind == "model_decision":
            calls = data.get("tool_calls", [])
            output.append(
                RunEventView(
                    seq=seq,
                    actor="model",
                    action="模型提出工具调用" if calls else "模型返回文本",
                    status="proposed" if calls else "no_action",
                    observation="、".join(c["function"]["name"] for c in calls)
                    or "未执行工具；以实际工具结果为准",
                    details={"tool_calls": calls},
                )
            )
        elif kind == "tool_result":
            result = data.get("result", {})
            value = result.get("data")
            name = data.get("tool", "unknown")
            observation = "已返回实际工具结果"
            if result.get("status") == "error":
                observation = result.get("code", "工具执行失败")
            elif isinstance(value, dict):
                if "result" in value and "id" in value:
                    answer = value["result"]
                    observation = (
                        "知识回答："
                        + answer["mode"]
                        + "；来源 "
                        + str(len(answer["sources"]))
                        + " 项"
                    )
                    value = {
                        k: value[k] for k in ("id", "question", "source_notices") if k in value
                    } | {
                        "result": {
                            k: answer.get(k) for k in ("mode", "answer", "sources", "warnings")
                        }
                    }
                elif "assets" in value:
                    observation = (
                        "返回 "
                        + str(len(value["assets"]))
                        + " 项资产记录；以详情中的资格、日期和可用状态为准"
                    )
                elif "tickets" in value:
                    observation = "返回 " + str(len(value["tickets"])) + " 项本人工单记录"
                elif "selected_asset_id" in value:
                    observation = "当前所选设备：" + str(value["selected_asset_id"])
                elif "facts" in value:
                    observation = "当前参数已更新；未自动提交"
                elif "proposal_id" in value:
                    observation = "当前完整预览已保存；未自动提交"
                if "task_id" in value and "observations" in value:
                    value = {
                        k: value.get(k)
                        for k in (
                            "task_id",
                            "status",
                            "facts",
                            "facts_revision",
                            "preview",
                            "current_ticket",
                        )
                    }
            output.append(
                RunEventView(
                    seq=seq,
                    actor="tool",
                    action=name,
                    status=result.get("status", "unknown"),
                    observation=observation,
                    details={"data": value, "code": result.get("code")},
                )
            )
        elif kind in {
            "queued",
            "running",
            "failed",
            "cancelled",
            "interrupted",
            "preview_ready",
            "needs_input",
            "field_changes",
            "finished",
        }:
            labels = {
                "queued": "进入队列",
                "running": "开始执行",
                "failed": "本轮执行失败",
                "cancelled": "本轮执行已停止",
                "interrupted": "运行中断，结果已保留",
                "preview_ready": "当前预览就绪",
                "needs_input": "需要补充信息",
                "field_changes": "参数已更新",
                "finished": "本轮执行结束",
            }
            output.append(
                RunEventView(
                    seq=seq,
                    actor="program",
                    action=labels[kind],
                    status=kind,
                    observation=str(
                        data.get("error")
                        or data.get("question")
                        or "办理结果、答案完整性与审批状态分别查看"
                    ),
                )
            )
            if kind == "finished":
                answer = data.get("result", {})
                for step in answer.get("trace", {}).get("steps", []):
                    output.append(
                        RunEventView(
                            seq=seq,
                            actor="program",
                            action=step.get("tool", "知识处理"),
                            status=step.get("status", ""),
                            observation="知识执行器："
                            + str(step.get("visible_count", 0))
                            + " 项可见结果；属于程序检索计划",
                        )
                    )
    return output
