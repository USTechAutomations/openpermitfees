"""Layout-preserving PDF text with page and line coordinates.

Fee schedules are tables rendered as PDFs. Reading order alone destroys them —
"$780" and "Option A - Over the Counter Review" end up in different places — so
extraction runs through ``pdftotext -layout`` (poppler), which preserves the
column geometry the tables depend on.

Every returned line carries its page and 1-based line number within that page so a
:class:`~openpermitfees.models.Provenance` can point a human at the exact place to
re-read. Without those coordinates a citation is just a URL, and a URL is not a
citation when the document is 48 pages long.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


class ExtractionUnavailable(RuntimeError):
    """The document could not be turned into text at all."""


@dataclass(frozen=True)
class TextLine:
    page: int  # 1-based
    line: int  # 1-based within the page
    text: str

    @property
    def stripped(self) -> str:
        return self.text.strip()


def pdftotext_available() -> bool:
    return shutil.which("pdftotext") is not None


def pdf_to_lines(payload: bytes, *, layout: bool = True) -> list[TextLine]:
    """Render a PDF to page/line-addressed text.

    Raises :class:`ExtractionUnavailable` rather than returning empty text: an
    empty extraction and a scanned-image PDF are different problems, and silently
    returning ``[]`` would make an OCR-needed document look like a document with
    no fees in it.
    """
    if not pdftotext_available():
        raise ExtractionUnavailable(
            "pdftotext (poppler-utils) is not installed; install it or pass pre-extracted text"
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        source = Path(tmpdir) / "document.pdf"
        source.write_bytes(payload)
        command = ["pdftotext"]
        if layout:
            command.append("-layout")
        command += [str(source), "-"]
        try:
            completed = subprocess.run(
                command, capture_output=True, timeout=180, check=False
            )
        except subprocess.TimeoutExpired as exc:  # pragma: no cover - defensive
            raise ExtractionUnavailable("pdftotext timed out") from exc

    if completed.returncode != 0:
        raise ExtractionUnavailable(
            f"pdftotext exited {completed.returncode}: "
            f"{completed.stderr.decode('utf-8', 'replace')[:200]}"
        )

    text = completed.stdout.decode("utf-8", errors="replace")
    if not text.strip():
        raise ExtractionUnavailable(
            "document produced no text (likely a scanned image; OCR is out of scope)"
        )
    return lines_from_text(text)


def lines_from_text(text: str) -> list[TextLine]:
    """Split ``pdftotext`` output into page/line-addressed lines (\\f = page break)."""
    out: list[TextLine] = []
    for page_index, page in enumerate(text.split("\f"), start=1):
        for line_index, raw in enumerate(page.split("\n"), start=1):
            out.append(TextLine(page=page_index, line=line_index, text=raw))
    return out


# A table-of-contents line: dot leaders followed by a bare page number, and no
# money anywhere on the line. Section headings repeat verbatim in the contents of
# every fee schedule we have seen, so a naive "first match" lands 40 pages early
# and slices an empty section — silently, which is the dangerous part.
_TOC_LINE = re.compile(r"[.…]{4,}[\s.…]*\d{1,3}\s*$")


def is_toc_line(text: str) -> bool:
    return "$" not in text and bool(_TOC_LINE.search(text))


def find_first(
    lines: Iterable[TextLine], needle: str, *, skip_toc: bool = True
) -> Optional[TextLine]:
    lowered = needle.lower()
    for item in lines:
        if skip_toc and is_toc_line(item.text):
            continue
        if lowered in item.text.lower():
            return item
    return None


def slice_between(
    lines: list[TextLine],
    start_needle: str,
    end_needle: Optional[str] = None,
    *,
    skip_toc: bool = True,
) -> list[TextLine]:
    """Lines from the first real match of ``start_needle`` to just before ``end_needle``."""

    def matches(text: str, needle: str) -> bool:
        if skip_toc and is_toc_line(text):
            return False
        return needle.lower() in text.lower()

    start_index: Optional[int] = None
    for index, item in enumerate(lines):
        if matches(item.text, start_needle):
            start_index = index
            break
    if start_index is None:
        return []
    if end_needle is None:
        return lines[start_index:]
    for index in range(start_index + 1, len(lines)):
        if matches(lines[index].text, end_needle):
            return lines[start_index:index]
    return lines[start_index:]


__all__ = [
    "ExtractionUnavailable",
    "TextLine",
    "find_first",
    "lines_from_text",
    "pdf_to_lines",
    "pdftotext_available",
    "slice_between",
]
