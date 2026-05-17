from pprint import pprint

from app.retriever import hybrid_search

question = "退款期限是多少？"
results = hybrid_search(question)

print(f"问题：{question}")
print(f"共返回 {len(results)} 条结果\n")

for i, item in enumerate(results, start=1):
    print(f"===== Result {i} =====")
    pprint(item)
    print()