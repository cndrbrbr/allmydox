from pathlib import Path


def extract(filepath: Path) -> list[tuple[int, str]]:
    """Return list of (page_number, text) tuples. Pages are 1-indexed."""
    ext = filepath.suffix.lower()
    if ext == ".pdf":
        return _extract_pdf(filepath)
    elif ext == ".docx":
        return _extract_docx(filepath)
    elif ext == ".txt":
        return _extract_txt(filepath)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def _extract_pdf(filepath: Path) -> list[tuple[int, str]]:
    import fitz  # pymupdf

    pages = []
    with fitz.open(str(filepath)) as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text()
            if text.strip():
                pages.append((i, text))
    return pages


def _extract_docx(filepath: Path) -> list[tuple[int, str]]:
    from docx import Document

    doc = Document(str(filepath))
    pages: list[tuple[int, str]] = []
    current_page = 1
    current_lines: list[str] = []

    for para in doc.paragraphs:
        if para.contains_page_break:
            if current_lines:
                pages.append((current_page, "\n".join(current_lines)))
                current_lines = []
            current_page += 1
        current_lines.append(para.text)

    if current_lines:
        pages.append((current_page, "\n".join(current_lines)))

    return pages


def _extract_txt(filepath: Path) -> list[tuple[int, str]]:
    text = filepath.read_text(encoding="utf-8", errors="replace")
    return [(1, text)] if text.strip() else []
