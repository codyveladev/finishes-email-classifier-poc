"""Attachment text extraction. PDF only for the POC."""

from pathlib import Path


def extract_text(path: str | None) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""

    try:
        import pdfplumber
        with pdfplumber.open(p) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages)
        if text.strip():
            return text
    except Exception:
        pass

    try:
        from pypdf import PdfReader
        reader = PdfReader(str(p))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return ""
