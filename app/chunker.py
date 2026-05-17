from app.config import get_settings
from app.utils import normalize_text


def split_sections(text: str) -> list[tuple[str, str]]:
    text = normalize_text(text)
    lines = text.split("\n")

    sections = []
    current_title = "General"
    current_body = []

    for line in lines:
        if line.startswith("#"):
            if current_body:
                sections.append((current_title, "\n".join(current_body).strip()))
                current_body = []
            current_title = line.lstrip("#").strip() or "General"
        else:
            current_body.append(line)

    if current_body:
        sections.append((current_title, "\n".join(current_body).strip()))

    return sections


def chunk_text(text: str, source: str) -> list[dict]:
    settings = get_settings()
    sections = split_sections(text)

    chunk_size = settings.chunk_size
    overlap = settings.chunk_overlap

    chunks = []
    chunk_counter = 0

    for section_title, section_text in sections:
        if not section_text:
            continue

        start = 0
        while start < len(section_text):
            end = min(start + chunk_size, len(section_text))
            chunk_text_value = section_text[start:end].strip()

            if chunk_text_value:
                chunks.append(
                    {
                        "chunk_id": f"{source}-{chunk_counter}",
                        "source": source,
                        "section": section_title,
                        "text": chunk_text_value,
                    }
                )
                chunk_counter += 1

            if end == len(section_text):
                break

            start = end - overlap

    return chunks