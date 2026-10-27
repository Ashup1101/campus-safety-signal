"""Text from untrusted PDFs, with a page cap; any failure becomes a ParseError."""

import io
from typing import Literal

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from campus_safety.iu_crime_log.parse import ParseError


def extract_text(body: bytes, max_pages: int, layout: bool = False) -> str:
    """Plain text, or with layout=True text that keeps each row's horizontal arrangement."""
    if b"%PDF" not in body[:1024]:
        raise ParseError("not a PDF; the archive may have stored an error page")
    try:
        reader = PdfReader(io.BytesIO(body), strict=False)
        if len(reader.pages) > max_pages:
            raise ParseError(f"PDF has more than {max_pages} pages")
        mode: Literal["plain", "layout"] = "layout" if layout else "plain"
        return "\n".join(page.extract_text(extraction_mode=mode) or "" for page in reader.pages)
    except PyPdfError as e:
        raise ParseError(f"unreadable PDF ({type(e).__name__})") from None
