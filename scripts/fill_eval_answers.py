try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import json
from pathlib import Path
from pprint import pprint

from app.rag_service import answer_question

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_PATH = BASE_DIR / "data" / "eval_answer_template.json"
OUTPUT_PATH = BASE_DIR / "data" / "eval_answer_results.json"

TOP_K = 3


def main() -> None:
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        items = json.load(f)

    results = []

    for item in items:
        question = item["question"]
        rag_result = answer_question(question, top_k=TOP_K)

        filled = dict(item)
        filled["model_answer"] = rag_result["answer"]
        filled["retrieved_sources"] = rag_result["sources"]

        results.append(filled)

        print("===== Generated =====")
        pprint(
            {
                "id": filled["id"],
                "question": filled["question"],
                "model_answer": filled["model_answer"],
            }
        )
        print()

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"已保存到: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()