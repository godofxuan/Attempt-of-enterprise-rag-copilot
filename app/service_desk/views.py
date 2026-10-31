"""Current task projection; no permissions or transitions are implemented here."""

from app.domain.product_views import TaskView, FieldView, NextActionView
from app.service_desk.catalog import SERVICES
from app.service_desk.lifecycle import NOTICES

TASK_LABELS = {
    "CANCELLED": "已结束",
    "COMPLETED": "本回合已交付",
    "RUNNING": "正在处理",
    "WAITING_USER": "待补充",
    "BLOCKED": "待继续",
    "READY": "可继续",
    "DRAFT": "待补充",
}


def next_task_action(service, task, delivery=None):
    """Pure projection of existing facts/results. It never changes permissions."""

    def action(kind, label, detail, fields=()):
        return NextActionView(kind=kind, label=label, detail=detail, fields=list(fields))

    if task.get("active_run_id"):
        return action("running", "正在处理", "本次运行尚未结束，可等待或停止本次执行。")
    if task.get("pending_user_update"):
        return action(
            "resolve", "核对原消息与当前参数", "原消息尚未处理完，先核对已保存参数与操作范围。"
        )
    active = service.is_active(task)
    if active and not task.get("receipt"):
        missing = [key for key in service.required_fields(task) if not task["facts"].get(key)]
        if missing or task["status"] == "WAITING_USER" and task.get("question"):
            catalog = SERVICES.get(task["guided_request"]["kind"])
            names = {f["name"]: f["label"] for f in catalog.field_specs()} if catalog else {}
            return action(
                "input",
                "补充必要信息",
                task.get("question") or "请补充：" + "、".join(names.get(k, k) for k in missing),
                missing,
            )
    pending = (delivery or {}).get("pending", [])
    if active and not task.get("receipt") and not task.get("preview") and "preview" in pending:
        kind = task["guided_request"]["kind"]
        selected = (
            task.get("preferred_asset_id") if kind == "loan" else task["facts"].get("asset_id")
        )
        if kind == "loan" and not selected:
            return action("choice", "选择设备", "参数已保存，请选择设备后生成预览。")
    if "knowledge" in pending:
        return action(
            "retry_knowledge", "重试解释", "已保存的参数和预览保留，只补未交付的知识内容。"
        )
    if task.get("current_ticket"):
        return action("receipt", "查看当前工单", task["current_ticket"]["next_step"])
    if not active:
        return action(
            "closed", "查看已保存结果", "事项已结束，历史结果保留；可在助理中开始新的事项。"
        )
    if task.get("preview"):
        submit = task["user_execution_ceiling"] == "SUBMIT_AFTER_CONFIRMATION"
        return action(
            "preview",
            "核对并确认当前预览" if submit else "查看仅预览结果",
            "提交需要单独确认当前完整内容。" if submit else "当前仅预览，绝不提交。",
        )
    if task["user_execution_ceiling"] != "READ_ONLY":
        if task["guided_request"]["kind"] == "loan" and not task.get("preferred_asset_id"):
            return action("choice", "选择设备", "参数已保存，请选择设备后生成预览。")
        return action("prepare", "生成当前预览", "当前参数已保存，可生成预览；尚未提交。")
    return action("continue", "继续查询", task.get("next_step") or "继续读取真实工具结果。")


def task_view(service, task_id):
    task = service.view(task_id)
    kind = task["guided_request"]["kind"]
    catalog = SERVICES.get(kind)
    ticket = task.get("current_ticket")
    cancelled = task["status"] == "CANCELLED"
    active = service.is_active(task)
    busy = bool(task.get("active_run_id") or task.get("pending_user_update"))
    editable = (
        active
        and not task.get("receipt")
        and not busy
        and task["user_execution_ceiling"] != "READ_ONLY"
    )
    delivery = service.workspace.conversations.coordinator.for_task(task)
    action = next_task_action(service, task, delivery)
    return TaskView(
        id=task_id,
        conversation_id=task.get("conversation_id"),
        kind=kind,
        title=catalog.title if catalog else "知识查询",
        status=ticket["status"] if ticket else task["status"],
        status_label=NOTICES.get(ticket["status"], ticket["status"])
        if ticket
        else "待补充"
        if action.kind == "input"
        else "待选择设备"
        if action.kind == "choice"
        else TASK_LABELS.get(task["status"], "待处理"),
        next_step=action.detail,
        ceiling=task["user_execution_ceiling"],
        revision=task["facts_revision"],
        fields=[
            FieldView(
                **{k: v for k, v in field.items() if k in FieldView.model_fields},
                value=task["facts"].get(field["name"]),
            )
            for field in catalog.field_specs()
        ]
        if catalog
        else [],
        preview=task.get("preview"),
        receipt=task.get("receipt"),
        current_ticket=ticket,
        knowledge=task.get("knowledge_result"),
        outcome=task.get("outcome"),
        pending_update=task.get("pending_update"),
        last_error=task.get("last_error"),
        closed=not active,
        can_edit=editable,
        can_run=active and not busy and action.kind not in {"input", "choice"},
        can_cancel=not cancelled and not task.get("receipt"),
        can_submit=editable
        and bool(task.get("preview"))
        and task["user_execution_ceiling"] == "SUBMIT_AFTER_CONFIRMATION",
        turn_delivery=delivery,
        next_action=action,
    )
