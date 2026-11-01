"""Small ranking illustration; not a retrieval quality benchmark."""
from collections import defaultdict

def fuse(lexical: list[str], dense: list[str], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = defaultdict(float)
    for ranking in (lexical, dense):
        # Each input is a ranked set of distinct candidate IDs.
        for rank, identifier in enumerate(ranking, 1):
            scores[identifier] += 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))

if __name__ == "__main__":
    for identifier, score in fuse(["a", "b", "c"], ["b", "c", "d"]):
        print(identifier, f"{score:.10f}")
