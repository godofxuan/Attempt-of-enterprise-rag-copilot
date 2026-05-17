try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from pprint import pprint

from app.rag_service import answer_question

question = "退款期限是多少？"
result = answer_question(question, top_k=3)

print(f"问题：{question}\n")
print("===== Answer =====")
print(result["answer"])
print("\n===== Sources =====")
pprint(result["sources"])