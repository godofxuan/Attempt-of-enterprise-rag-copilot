from pathlib import Path
from pprint import pprint

from app.chunker import chunk_text
from app.utils import read_text_file

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DOCS_DIR = BASE_DIR / "data" / "raw_docs"

file_path = RAW_DOCS_DIR / "refund_policy.md"
text = read_text_file(file_path)

chunks = chunk_text(text=text, source=file_path.name)

print(f"共切出 {len(chunks)} 个 chunks\n")

for i, chunk in enumerate(chunks, start=1):
    print(f"===== Chunk {i} =====")
    pprint(chunk)
    print()