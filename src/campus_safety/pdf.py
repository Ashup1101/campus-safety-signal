"""Text from untrusted PDFs, with a page cap; any failure becomes a ParseError."""

import io

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from campus_safety.iu_crime_log.parse import ParseError


def extract_text(body: bytes, max_pages: int) -> str:
    if b"%PDF" not in body[:1024]:
        raise ParseError("not a PDF; the archive may have stored an error page")
    try:
        reader = PdfReader(io.BytesIO(body), strict=False)
        if len(reader.pages) > max_pages:
            raise ParseError(f"PDF has more than {max_pages} pages")
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except PyPdfError as e:
        raise ParseError(f"unreadable PDF ({type(e).__name__})") from None
