try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from app.retriever import build_indexes


def main() -> None:
    doc_count, chunk_count = build_indexes()
    print(f"Built indexes: {doc_count} documents, {chunk_count} chunks")


if __name__ == "__main__":
    main()
