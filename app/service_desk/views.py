"""Current task projection; no permissions or transitions are implemented here."""

from app.domain.product_views import TaskView, FieldView
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
    return TaskView(
        id=task_id,
        conversation_id=task.get("conversation_id"),
        kind=kind,
        title=catalog.title if catalog else "知识查询",
        status=ticket["status"] if ticket else task["status"],
        status_label=NOTICES.get(ticket["status"], ticket["status"])
        if ticket
        else TASK_LABELS.get(task["status"], "待处理"),
        next_step=task["next_step"],
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
        can_run=active and not busy,
        can_cancel=not cancelled and not task.get("receipt"),
        can_submit=editable
        and bool(task.get("preview"))
        and task["user_execution_ceiling"] == "SUBMIT_AFTER_CONFIRMATION",
    )
