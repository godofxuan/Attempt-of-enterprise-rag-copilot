"""Model-friendly evidence and rich UI evidence are different projections.
Reference validity DOES NOT establish semantic correctness.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Source:
    id: str
    title: str
    version: str
    text: str
    locator: str

def model_view(sources: list[Source]) -> list[dict[str, str]]:
    return [{"id": s.id, "title": s.title, "content": s.text} for s in sources]

def ui_view(sources: list[Source]) -> dict[str, dict[str, str]]:
    return {s.id: {"title": s.title, "version": s.version, "text": s.text, "locator": s.locator} for s in sources}

def citations_exist(cited: list[str], sources: list[Source]) -> bool:
    allowed = {s.id for s in sources}
    return bool(cited) and set(cited) <= allowed

if __name__ == "__main__":
    data = [Source("loan-1", "合成借用制度", "v1", "借用申请提交后为待审批。", "第1节")]
    print("引用存在：", citations_exist(["loan-1"], data))
    print("但这不能证明：报修提交后为待审批。")
    print(ui_view(data))
