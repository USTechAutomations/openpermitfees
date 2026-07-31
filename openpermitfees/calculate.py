"""Evaluate a valuation-tiered fee table.

Publishing tiers instead of a "typical fee" only helps if a consumer can turn
them back into a number, so the tier semantics are executable here rather than
described in prose.

The implementation is checked against the jurisdiction's OWN worked example
(Phoenix prints one for a $250,500 project: $2,053 base plus 51 x $9 = $2,512).
That example is the closest thing to a ground-truth oracle a fee table has, and
any tier table we add should bring one with it.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional

from .models import ValuationTier


class NoApplicableTier(ValueError):
    """The valuation falls outside every published tier."""


def select_tier(
    tiers: Iterable[ValuationTier], valuation_usd: float
) -> Optional[ValuationTier]:
    """The last tier whose range contains ``valuation_usd``.

    "Last" matters: a table may print two rows for the same range (Phoenix prints
    a $98 water-heater/fence minimum and a $195 base fee, both for $1-$1,000).
    The narrower special case is printed first, so the general row wins by
    default and the special case is applied by a caller who knows the work type.
    """
    match: Optional[ValuationTier] = None
    for tier in tiers:
        upper = tier.max_valuation_usd
        if valuation_usd >= tier.min_valuation_usd and (upper is None or valuation_usd <= upper):
            match = tier
    return match


def fee_for_valuation(tiers: Iterable[ValuationTier], valuation_usd: float) -> float:
    """Permit fee for ``valuation_usd`` under a tiered table."""
    tiers = list(tiers)
    tier = select_tier(tiers, valuation_usd)
    if tier is None:
        raise NoApplicableTier(f"no tier covers a valuation of ${valuation_usd:,.2f}")

    fee = tier.base_usd
    if tier.plus_per_increment_usd and tier.increment_usd:
        floor = tier.applies_above_usd if tier.applies_above_usd is not None else tier.min_valuation_usd
        excess = max(0.0, valuation_usd - floor)
        # "or fraction thereof" — jurisdictions round the increment count UP.
        increments = math.ceil(excess / tier.increment_usd)
        fee += increments * tier.plus_per_increment_usd
    return round(fee, 2)


__all__ = ["NoApplicableTier", "fee_for_valuation", "select_tier"]
