"""Tier arithmetic, checked against the jurisdiction's own worked example.

A fee schedule is one of the rare documents that ships its own oracle: Phoenix
prints a calculation for a $250,500 project and states the answer. If our model
of Table A cannot reproduce the city's own number, the model is wrong.

Both sides of that check are read out of the document — the tiers come from the
extractor, and the expected total is parsed from the example the city printed.
Neither is typed in by hand here, because a hand-typed expectation only proves
the test author and the code agree.
"""

from __future__ import annotations

import re

import pytest

from openpermitfees.calculate import NoApplicableTier, fee_for_valuation, select_tier
from openpermitfees.models import ValuationTier

from .conftest import item

#: "…assuming a total project valuation** of $250,500:
#:   $2,053 base fee plus $459 (51 X $9) on the project valuation = Total permit
#:   fee cost of $2,512"
_WORKED_EXAMPLE = re.compile(
    r"assuming a total project valuation\*{0,2} of \$([\d,]+):\s*\n\s*"
    r"\$([\d,]+) base fee plus \$([\d,]+) \((\d+) X \$(\d+)\)"
    r".*?Total permit fee cost of \$([\d,]+)",
)


def _money(raw: str) -> float:
    return float(raw.replace(",", ""))


@pytest.fixture()
def table_a(phoenix_items):
    return item(phoenix_items, "phoenix-az/building_permit/valuation_table_a").tiers


def test_reproduces_the_documents_own_worked_example(phoenix_text, table_a):
    """The city's printed answer, recomputed from the tiers we extracted."""
    match = _WORKED_EXAMPLE.search(phoenix_text)
    assert match, "the fixture no longer contains the city's worked example"
    valuation, base, marginal, increments, rate, total = match.groups()

    assert fee_for_valuation(table_a, _money(valuation)) == _money(total)

    # and for the same reasons the document gives
    tier = select_tier(table_a, _money(valuation))
    assert tier.base_usd == _money(base)
    assert tier.plus_per_increment_usd == _money(rate)
    assert _money(total) == _money(base) + int(increments) * _money(rate)
    assert _money(marginal) == int(increments) * _money(rate)


def test_or_fraction_thereof_rounds_the_increment_count_up(table_a):
    """$250,500 is 50.5 increments over $200,000 and the city charges 51."""
    tier = select_tier(table_a, 250_500)
    base, rate = tier.base_usd, tier.plus_per_increment_usd
    assert fee_for_valuation(table_a, 250_000) == base + 50 * rate
    assert fee_for_valuation(table_a, 250_001) == base + 51 * rate  # one dollar buys a whole step
    assert fee_for_valuation(table_a, 250_500) == base + 51 * rate


def test_a_valuation_at_a_tier_floor_pays_the_base_only(table_a):
    tier = select_tier(table_a, 250_500)
    assert fee_for_valuation(table_a, tier.applies_above_usd) == tier.base_usd


def test_last_matching_tier_wins_when_a_table_prints_two_rows_for_one_range(table_a):
    """Phoenix prints two rows covering $1-$1,000: a narrow minimum and the base fee.

    The general row is the default; the narrow one is applied by a caller who
    knows the work type. Silently taking the cheaper row would under-quote every
    small permit.
    """
    overlapping = [t for t in table_a if t.min_valuation_usd == 1]
    assert len(overlapping) == 2, "the fixture no longer prints two rows for $1-$1,000"
    assert select_tier(table_a, 500) is overlapping[-1]
    assert fee_for_valuation(table_a, 500) == overlapping[-1].base_usd


def test_the_open_ended_top_tier_has_no_ceiling(table_a):
    top = table_a[-1]
    assert top.max_valuation_usd is None
    huge = top.applies_above_usd * 5
    expected = top.base_usd + (
        (huge - top.applies_above_usd) / top.increment_usd
    ) * top.plus_per_increment_usd
    assert fee_for_valuation(table_a, huge) == pytest.approx(expected)


def test_a_valuation_outside_every_tier_raises_rather_than_guessing():
    bounded = (ValuationTier(min_valuation_usd=1000, max_valuation_usd=2000, base_usd=100),)
    with pytest.raises(NoApplicableTier):
        fee_for_valuation(bounded, 999)
    with pytest.raises(NoApplicableTier):
        fee_for_valuation(bounded, 2001)
    with pytest.raises(NoApplicableTier):
        fee_for_valuation((), 5000)
