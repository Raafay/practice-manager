"""Loading WeasyPrint, with a plain stand-in PDF for development computers without Pango."""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# One A4 page saying "PDF preview not available". Used only with DEBUG on, so a
# Mac without Homebrew's Pango can still load the demo and click around.
PLACEHOLDER_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]"
    b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
    b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"5 0 obj<</Length 56>>stream\nBT /F1 18 Tf 72 760 Td (PDF preview not available) Tj ET\n"
    b"endstream endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
)


def weasyprint_html():
    """Return WeasyPrint's HTML class, or None in development when its system libraries are missing.

    Outside development a missing library is an error, so a live site never sends a stand-in PDF.
    """
    try:
        from weasyprint import HTML
    except OSError:
        if not settings.DEBUG:
            raise
        logger.warning("WeasyPrint cannot load (Pango missing); using a stand-in PDF")
        return None
    return HTML
