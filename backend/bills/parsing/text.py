from pathlib import Path

import pdfplumber


def extract_pdf_text(path: Path) -> str:
    """Text layer of a PDF, pages separated by form feeds. Empty for scans."""
    with pdfplumber.open(path) as pdf:
        return "\f".join(page.extract_text() or "" for page in pdf.pages)
