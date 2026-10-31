"""Original teaching example, NOT a patch to ESA. No model calls or product data."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Request:
    preview: bool = False
    knowledge: bool = False

@dataclass(frozen=True)
class Facts:
    missing_fields: tuple[str, ...] = ()
    busy: bool = False
    preview_ready: bool = False
    knowledge_ready: bool = False

def project(request: Request, facts: Facts) -> dict[str, object]:
    """Task-level missing fields do not block a separate knowledge delivery."""
    task_next = "input" if facts.missing_fields else "prepare"
    if facts.busy:
        return {"task_next": task_next, "turn_actions": ["running"]}
    actions: list[str] = []
    if request.knowledge and not facts.knowledge_ready:
        actions.append("retry_knowledge")
    if request.preview and not facts.preview_ready:
        actions.append("input" if facts.missing_fields else "prepare")
    return {"task_next": task_next, "turn_actions": actions or ["complete"]}

if __name__ == "__main__":
    print(project(Request(knowledge=True), Facts(missing_fields=("loan_start",))))
    print(project(Request(preview=True, knowledge=True), Facts(missing_fields=("loan_start",))))
