"""Page/line addressing and the table-of-contents trap.

Every fee schedule repeats its section headings verbatim in the contents. A
"first match wins" section slice therefore lands on page 3 instead of page 42 and
returns a one-line section — producing an extraction that is empty but not
failed. That is the exact shape of a confident default: the pipeline reports
success and publishes two rows where ten belong.
"""

from __future__ import annotations

from openpermitfees.extract.pdftext import (
    is_toc_line,
    lines_from_text,
    slice_between,
    find_first,
)


def test_pages_and_lines_are_one_based_and_reset_per_page():
    lines = lines_from_text("a\nb\fc\nd")
    assert [(l.page, l.line, l.text) for l in lines] == [
        (1, 1, "a"),
        (1, 2, "b"),
        (2, 1, "c"),
        (2, 2, "d"),
    ]


def test_toc_lines_are_recognised_by_dot_leaders_and_a_bare_page_number():
    assert is_toc_line("Residential Solar Photovoltaic System Permits ……………………   42")
    assert is_toc_line("Site Plan Base Review Services ....................................  6")


def test_a_line_carrying_money_is_never_treated_as_a_toc_line():
    """Fee lines use dot leaders too — dropping them would delete real rows."""
    assert not is_toc_line("Option A - Over the Counter Review …………………………… $780")
    assert not is_toc_line("b.  Each Additional Meter per Utility ……………………………  $98 each")


def test_section_slice_skips_the_contents_and_finds_the_real_section(phoenix_text):
    lines = lines_from_text(phoenix_text)
    block = slice_between(
        lines, "Residential Solar Photovoltaic System Permits", "Solar Water Heaters"
    )
    assert block, "section not found"
    assert block[0].page == 42, "matched the table of contents instead of the section"
    assert len(block) > 10
    assert any("$780" in line.text for line in block)


def test_without_the_toc_guard_the_same_slice_collapses(phoenix_text):
    """The regression itself, pinned: skip_toc=False reproduces the empty section."""
    lines = lines_from_text(phoenix_text)
    block = slice_between(
        lines,
        "Residential Solar Photovoltaic System Permits",
        "Solar Water Heaters",
        skip_toc=False,
    )
    assert block[0].page < 10
    assert not any("$780" in line.text for line in block)


def test_find_first_skips_the_contents_too(phoenix_text):
    lines = lines_from_text(phoenix_text)
    assert find_first(lines, "TABLE A: BUILDING SAFETY VALUATION-BASED PERMIT FEE").page == 35


def test_a_missing_section_returns_empty_rather_than_the_rest_of_the_document(phoenix_text):
    lines = lines_from_text(phoenix_text)
    assert slice_between(lines, "Fees For A Section That Does Not Exist") == []
