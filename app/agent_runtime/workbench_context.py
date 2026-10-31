"""Bound current facts and small relevant history for the existing tool loop."""

from app.service_desk.catalog import SERVICES


class ContextBuilder:
    def __init__(self, service):
        self.service = service

    def build(self, task, turn=None, observed=()):
        from app.service_desk.goals import OUTPUT_MEANINGS

        service = SERVICES.get(task["guided_request"]["kind"])
        current_ticket = None
        if task.get("receipt") and service:
            current_ticket = self.service.ticket(task["task_id"], task["receipt"]["ticket_id"])
        history = []
        conversations = getattr(self.service.workspace, "conversations", None)
        if conversations and task.get("conversation_id"):
            for row in reversed(conversations.turns(task["conversation_id"])[-6:]):
                # Whole recent user turns only; no lossy rewrite of constraints.
                if (
                    row["role"] == "user"
                    and (not turn or row["id"] != turn["id"])
                    and sum(len(r["text"]) for r in history) + len(row["text"]) <= 1500
                ):
                    if not turn or row["text"] != turn["text"]:
                        history.insert(
                            0,
                            {
                                "role": "user",
                                "text": row["text"],
                                "status": row.get("status"),
                                "historical_not_a_new_request": True,
                            },
                        )
        linked = None
        answer_id = (task.get("knowledge_result") or {}).get("id") or task.get("linked_answer_id")
        if answer_id:
            library = getattr(self.service.workspace, "library", None)
            if library and hasattr(library, "valid_answer"):
                linked = library.valid_answer(answer_id, task.get("kb_id"))
        if linked:
            answer = linked["result"]
            linked = {
                "id": linked["id"],
                "question": linked["question"],
                "mode": answer["mode"],
                "answer": answer["answer"],
                "sources": answer["sources"],
                "warnings": answer.get("warnings", []),
            }
        valid = self.service.valid_observations(task)
        workflow = {
            "READ_ONLY": "完成当前只读查询，不准备申请",
            "PREVIEW_ONLY": "现在准备完整预览并交付；绝不提交",
            "SUBMIT_AFTER_CONFIRMATION": "现在准备完整申请预览；随后等待用户对当前预览精确确认，再提交一次并读回",
        }[task["user_execution_ceiling"]]
        return {
            "task_kind": task["guided_request"]["kind"],
            "execution_ceiling": task["user_execution_ceiling"],
            "requested_results": {
                name: workflow
                if name == "open_application"
                else (service.output_meanings or {}).get(name, OUTPUT_MEANINGS[name])
                if service
                else OUTPUT_MEANINGS[name]
                for name in task["task_goal"]["required_outputs"]
            },
            "user_selected_workflow": workflow,
            "forbidden_operations": task["task_goal"]["forbidden_operations"],
            "facts": task["facts"],
            "reference_date": str(self.service.store.today()),
            "preferred_asset_id": task.get("preferred_asset_id"),
            "required_outputs": task["task_goal"]["required_outputs"],
            "current_ticket": current_ticket,
            "valid_observations": {k: v for k, v in valid.items() if k not in observed},
            "missing_domain_observations": (
                [service.rule_need] if service and service.rule_need not in valid else []
            ),
            "missing_fields": (
                [k for k in self.service.required_fields(task) if not task["facts"].get(k)]
                if not turn
                or "update_parameters" in observed
                or turn.get("preserve_latest_parameters")
                else None
            ),
            "current_input_application": (
                "historical_retry: later parameter changes are authoritative; do not reapply old edits. Continue unresolved work using current facts. Ask for a new user message if an unapplied old change is still wanted."
                if turn and turn.get("preserve_latest_parameters")
                else "pending: stored facts do not yet include the current user message"
                if turn and "update_parameters" not in observed
                else "applied_or_no_new_input"
            ),
            "last_presented_options": (
                (task.get("presented_options") or {}).get("items", [])
                if (task.get("presented_options") or {}).get("facts_revision")
                == task["facts_revision"]
                and self.service.store.clock()
                - (task.get("presented_options") or {}).get("observed_at", 0)
                <= 60
                else []
            ),
            "field_schema": service.field_specs() if service else [],
            "knowledge_base_id": task.get("kb_id"),
            "knowledge_mode": "deep" if turn and turn.get("detailed") else "fast",
            "knowledge_rule_boundary": "Uploaded/linked documents explain sources. Current SQLite domain rules alone authorize business execution.",
            "linked_knowledge": linked if "knowledge_answer" not in observed else None,
            "historical_user_turns_for_references_only": history,
            "current_turn_id": turn["id"] if turn else None,
            "preview_available": bool(task.get("pending_proposal_id")),
        }
