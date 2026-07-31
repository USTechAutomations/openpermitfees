"""The Phoenix extractor, against the real document text.

The assertions here are deliberately specific — exact amounts, exact page and
line numbers, exact absences. A "we got some rows" test would have passed on the
day the section slice matched the table of contents and published two rows out of
ten, which is the failure this file exists to prevent.
"""

from __future__ import annotations

import pytest

from openpermitfees.extract import get
from openpermitfees.models import SchemaViolation

from .conftest import item

SOLAR_OPTIONS = {
    "a": 780.0,
    "b": 585.0,
    "c": 488.0,
    "d": 390.0,
    "e": 293.0,
}


# --------------------------------------------------------------------------- #
# what the document says about itself
# --------------------------------------------------------------------------- #


def test_document_facts_come_from_the_document(phoenix_context):
    facts = get("phoenix-az").document_facts(phoenix_context)
    assert facts == {
        "title": "City of Phoenix PDD Fee Schedule",
        "adopting_instrument": "Ordinance G-7465",
        "approved_date": "2025-12-17",
        "effective_date": "2026-01-20",
        "code_reference": "Phoenix City Code, Chapter 9, Appendix A.2",
    }


def test_every_published_row_carries_the_ordinance_and_effective_date(phoenix_items):
    published = [i for i in phoenix_items if i.status == "published"]
    assert published
    for row in published:
        assert row.provenance.adopting_instrument == "Ordinance G-7465"
        assert row.provenance.effective_date == "2026-01-20"
        assert row.provenance.page and row.provenance.line


# --------------------------------------------------------------------------- #
# Table A
# --------------------------------------------------------------------------- #


def test_table_a_is_published_as_tiers_not_as_a_number(phoenix_items):
    table = item(phoenix_items, "phoenix-az/building_permit/valuation_table_a")
    assert table.basis == "valuation_tiered"
    assert table.amount_usd is None, "a tiered fee must not be flattened to one number"
    assert len(table.tiers) == 8
    assert table.provenance.page == 35


def test_tier_bounds_are_contiguous_and_ascending(phoenix_items):
    tiers = item(phoenix_items, "phoenix-az/building_permit/valuation_table_a").tiers
    bounded = [t for t in tiers if t.max_valuation_usd is not None]
    for earlier, later in zip(bounded, bounded[1:]):
        assert later.min_valuation_usd >= earlier.min_valuation_usd
        assert later.base_usd >= earlier.base_usd
    assert tiers[-1].max_valuation_usd is None, "the top tier is open-ended"


def test_swimming_pool_minimum_carries_its_surcharge(phoenix_items):
    pool = item(phoenix_items, "phoenix-az/swimming_pool/minimum_permit_fee")
    assert pool.amount_usd == 234.0
    assert pool.minimum_usd == 234.0
    assert len(pool.surcharges) == 1
    surcharge = pool.surcharges[0]
    assert surcharge["amount_usd"] == 30.0
    assert surcharge["authority"] == "Ordinance G-3114"


# --------------------------------------------------------------------------- #
# residential solar PV
# --------------------------------------------------------------------------- #


def test_solar_is_five_fixed_options_not_one_typical_fee(phoenix_items):
    options = [i for i in phoenix_items if i.basis == "option"]
    assert {i.item_id[-1]: i.amount_usd for i in options} == SOLAR_OPTIONS
    for option in options:
        assert option.permit_type == "residential_solar_pv"
        assert option.provenance.page == 42


@pytest.mark.parametrize("letter", sorted(SOLAR_OPTIONS))
def test_each_option_quotes_the_line_its_amount_is_printed_on(phoenix_items, letter):
    option = item(phoenix_items, f"phoenix-az/residential_solar_pv/fixed_option_{letter}")
    printed = f"${SOLAR_OPTIONS[letter]:,.0f}"
    assert printed in option.provenance.matched_text


def test_wrapped_option_conditions_are_rejoined(phoenix_items):
    """Options C and E wrap mid-word: '...2-' / 'inspections'.

    Publishing the truncated first half would state a different fee condition
    than the city printed.
    """
    for letter in ("c", "e"):
        option = item(phoenix_items, f"phoenix-az/residential_solar_pv/fixed_option_{letter}")
        assert not option.conditions.rstrip().endswith("-")
        assert "inspection" in option.conditions.lower()


def test_non_standard_solar_is_a_reference_with_no_amount(phoenix_items):
    row = item(phoenix_items, "phoenix-az/residential_solar_pv/non_standard")
    assert row.basis == "reference"
    assert row.amount_usd is None
    assert "Table A" in row.conditions


# --------------------------------------------------------------------------- #
# what the document does NOT contain
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("permit_type", ["residential_mechanical", "residential_electrical"])
def test_absent_flat_trade_fees_are_answered_not_omitted(phoenix_items, permit_type):
    """Phoenix publishes no flat residential mechanical/electrical permit fee.

    The row exists and says so, pointing at the table that does price the work.
    A missing row would read as "no fee"; a number here would be invented.
    """
    row = item(phoenix_items, f"phoenix-az/{permit_type}/flat_fee")
    assert row.status == "not_found_in_document"
    assert row.amount_usd is None
    assert "Table A" in row.unavailable_reason
    assert "valuation_table_a" in row.unavailable_reason


def test_no_row_claims_a_fee_type_the_document_does_not_cover(phoenix_items):
    permit_types = {i.permit_type for i in phoenix_items}
    assert permit_types == {
        "building_permit",
        "swimming_pool",
        "residential_solar_pv",
        "residential_mechanical",
        "residential_electrical",
    }


# --------------------------------------------------------------------------- #
# the extractor cannot publish an unsourced number even if it tries
# --------------------------------------------------------------------------- #


def test_a_drifting_parser_fails_instead_of_publishing(phoenix_context, monkeypatch):
    """Inverse mutation: make the tier parser return a wrong base fee.

    The schema layer must reject it, because the amount no longer appears in the
    quoted source line. If this test ever passes with a mutated parser, nothing
    in the pipeline is actually checking the numbers.
    """
    from openpermitfees.extract import phoenix as module

    real_parse = module._parse_tier

    def wrong(text: str):
        tier = real_parse(text)
        if tier is None:
            return None
        return module.ValuationTier(
            min_valuation_usd=tier.min_valuation_usd,
            max_valuation_usd=tier.max_valuation_usd,
            base_usd=tier.base_usd + 1,  # one dollar off, the realistic parser bug
            plus_per_increment_usd=tier.plus_per_increment_usd,
            increment_usd=tier.increment_usd,
            applies_above_usd=tier.applies_above_usd,
            note=tier.note,
        )

    monkeypatch.setattr(module, "_parse_tier", wrong)
    with pytest.raises(SchemaViolation, match="does not appear in the quoted source line"):
        get("phoenix-az").extract(phoenix_context)


def test_an_empty_document_produces_no_published_rows(phoenix_document):
    """A blank page must yield absences, never a remembered number."""
    from openpermitfees.extract.base import DocumentContext
    from openpermitfees.extract.pdftext import lines_from_text

    context = DocumentContext(document=phoenix_document, lines=lines_from_text("\n\n\n"))
    items = get("phoenix-az").extract(context)
    assert [i.status for i in items] == ["not_found_in_document"] * len(items)
    assert all(i.amount_usd is None for i in items)
