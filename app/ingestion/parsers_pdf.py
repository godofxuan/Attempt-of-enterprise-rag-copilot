from pathlib import Path

import pypdf
from pypdf import PdfReader

from app.domain.documents import (
    DocumentParseError,
    ParseResult,
    ParseWarning,
    ParsedSection,
    SourceLocator,
)


class PdfDocumentParser:
    name = "pdf"
    version = pypdf.__version__
    suffixes = (".pdf",)

    def parse(self, path: Path) -> ParseResult:
        reader = PdfReader(path)
        sections: list[ParsedSection] = []
        warnings: list[ParseWarning] = []
        text_parts: list[str] = []

        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            locator = SourceLocator(
                kind="page",
                start=page_number,
                end=page_number,
                label=f"page {page_number}",
            )
            if not text:
                warnings.append(
                    ParseWarning(
                        code="empty_page",
                        message=f"Page {page_number} has no extractable text.",
                        severity="warning",
                        locator=locator,
                    )
                )
                continue
            sections.append(
                ParsedSection(
                    heading=f"Page {page_number}",
                    level=0,
                    path=[f"Page {page_number}"],
                    text=text,
                    locator=locator,
                )
            )
            text_parts.append(text)

        full_text = "\n\n".join(text_parts)
        if not full_text.strip():
            raise DocumentParseError(
                code="empty_document",
                path=path,
                parser=self.name,
                message="PDF has no extractable text; OCR is not enabled",
            )
        return ParseResult(
            text=full_text,
            sections=sections,
            headings=[],
            tables=[],
            metadata={"page_count": str(len(reader.pages)), "ocr": "disabled"},
            source_location=path.name,
            parse_warnings=warnings,
            parser_name=self.name,
            parser_version=self.version,
        )
