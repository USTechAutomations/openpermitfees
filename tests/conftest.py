"""Shared fixtures.

The Phoenix fixture is the real ``pdftotext -layout`` output of the City of
Phoenix PDD fee schedule, with pages the extractor does not read replaced by a
placeholder. Page numbering is preserved, so provenance page/line assertions in
the tests are the same coordinates a reader would use against the live PDF.

The table-of-contents pages are kept deliberately: the contents repeat every
section heading verbatim, and matching one of them instead of the section is the
bug that silently produced an empty extraction (see ``test_pdftext.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openpermitfees.extract import get  # noqa: F401  (registers built-ins)
from openpermitfees.extract.base import DocumentContext
from openpermitfees.extract.pdftext import lines_from_text
from openpermitfees.models import FeeDocument

FIXTURES = Path(__file__).parent / "fixtures"

PHOENIX_URL = (
    "https://www.phoenix.gov/content/dam/phoenix/pddsite/documents/impact-fees/fee-schedule.pdf"
)
FIXTURE_SHA = "b" * 64


@pytest.fixture(scope="session")
def phoenix_text() -> str:
    return (FIXTURES / "phoenix_fee_schedule.txt").read_text(encoding="utf-8")


@pytest.fixture()
def phoenix_document() -> FeeDocument:
    return FeeDocument(
        jurisdiction_id="phoenix-az",
        source_url=PHOENIX_URL,
        sha256=FIXTURE_SHA,
        retrieved_at="2026-07-31T00:00:00+00:00",
        media_type="application/pdf",
        byte_length=1,
        archive_path="phoenix-az/fixture.pdf",
        http_status=200,
    )


@pytest.fixture()
def phoenix_context(phoenix_text: str, phoenix_document: FeeDocument) -> DocumentContext:
    return DocumentContext(document=phoenix_document, lines=lines_from_text(phoenix_text))


@pytest.fixture()
def phoenix_items(phoenix_context: DocumentContext):
    return get("phoenix-az").extract(phoenix_context)


@pytest.fixture()
def live_data_dir(tmp_path) -> Path:
    """A throwaway copy of the repository's committed archive.

    Copied rather than used in place so a test can never append to the real
    change feed, and so the suite does not depend on whatever the collector
    timer last wrote.
    """
    import shutil

    source = Path(__file__).resolve().parent.parent / "data"
    if not source.exists():  # pragma: no cover - repo always ships one
        pytest.skip("no committed archive to diff")
    destination = tmp_path / "data"
    shutil.copytree(source, destination)
    # The feed itself is an output, not an input; a copied one would make the
    # "second run appends nothing" test pass without proving anything.
    (destination / "changes.jsonl").unlink(missing_ok=True)
    return destination


def item(items, item_id: str):
    """The one row with this id, or a readable failure."""
    matches = [i for i in items if i.item_id == item_id]
    assert len(matches) == 1, f"{item_id}: expected 1 row, got {len(matches)}"
    return matches[0]
