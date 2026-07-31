"""Extractor for the City of Phoenix Planning & Development Department fee schedule.

Source: ``https://www.phoenix.gov/content/dam/phoenix/pddsite/documents/impact-fees/fee-schedule.pdf``
(Appendix A.2 of the Phoenix City Code, Chapter 9).

What reading the actual document changes about the naive model of "a permit fee":

* Phoenix publishes **no flat residential mechanical or electrical permit fee**.
  Installation, repair and replacement work is priced from *Table A* on project
  valuation. Any single number offered for "the Phoenix residential mechanical
  permit fee" is invented — so this extractor emits an explicit
  ``not_found_in_document`` row naming Table A instead of a figure.
* Residential solar PV is priced as a **set of five fixed-fee options**
  ($780/$585/$488/$390/$293) that differ in plan-review and inspection count, or
  by valuation when non-standard. Reducing that to one "typical" number loses the
  only thing a contractor is choosing between.
"""

from __future__ import annotations

import re
from typing import Optional

from ..models import FeeItem, Provenance, ValuationTier
from .base import DocumentContext, register
from .pdftext import TextLine, slice_between

JURISDICTION_ID = "phoenix-az"
STATE = "AZ"

_MONEY = r"\$\s?([\d,]+(?:\.\d{2})?)"
_TIER_START = re.compile(rf"^\s*{_MONEY}\s*[-–—]\s*{_MONEY}\s+{_MONEY}\s*(.*)$")
_TIER_OPEN = re.compile(rf"^\s*Over\s+{_MONEY}\s+{_MONEY}\s*(.*)$", re.IGNORECASE)
_PLUS = re.compile(rf"plus\s+{_MONEY}\s+for\s+each\s+additional\s+{_MONEY}", re.IGNORECASE)
_ON_FIRST = re.compile(rf"on\s+first\s+{_MONEY}", re.IGNORECASE)
_OPTION = re.compile(
    rf"Option\s+([A-Z])\s*[-–—]\s*(.+?)\s*[…\.]{{2,}}\s*{_MONEY}\s*(.*)$"
)


def _money(raw: str) -> float:
    return float(raw.replace(",", ""))


class PhoenixExtractor:
    jurisdiction_id = JURISDICTION_ID

    # ------------------------------------------------------------------ #
    # document self-description
    # ------------------------------------------------------------------ #

    def document_facts(self, context: DocumentContext) -> dict:
        header = "\n".join(line.text for line in context.lines[:60])
        facts: dict[str, Optional[str]] = {
            "title": None,
            "adopting_instrument": None,
            "approved_date": None,
            "effective_date": None,
            "code_reference": None,
        }
        if re.search(r"PDD\s+FEE\s+SCHEDULE", header, re.IGNORECASE):
            facts["title"] = "City of Phoenix PDD Fee Schedule"
        ordinance = re.search(r"Per\s+Ordinance\s+([A-Z]-\d+)", header, re.IGNORECASE)
        if ordinance:
            facts["adopting_instrument"] = f"Ordinance {ordinance.group(1)}"
        approved = re.search(r"Approved\s+(\d{1,2}/\d{1,2}/\d{4})", header, re.IGNORECASE)
        if approved:
            facts["approved_date"] = _iso(approved.group(1))
        effective = re.search(r"Effective\s+(\d{1,2}/\d{1,2}/\d{4})", header, re.IGNORECASE)
        if effective:
            facts["effective_date"] = _iso(effective.group(1))
        code = re.search(r"(Phoenix City Code,[^\n]+)", header)
        if code:
            facts["code_reference"] = code.group(1).strip()
        return {k: v for k, v in facts.items() if v}

    # ------------------------------------------------------------------ #
    # fee rows
    # ------------------------------------------------------------------ #

    def extract(self, context: DocumentContext) -> list[FeeItem]:
        facts = self.document_facts(context)
        items: list[FeeItem] = []
        items.extend(self._valuation_table(context, facts))
        items.extend(self._solar_options(context, facts))
        items.extend(self._explicit_absences(context, facts))
        return items

    # -- Table A --------------------------------------------------------- #

    def _valuation_table(self, context: DocumentContext, facts: dict) -> list[FeeItem]:
        block = slice_between(
            context.lines,
            "TABLE A: BUILDING SAFETY VALUATION-BASED PERMIT FEE",
            "EXAMPLE OF A PERMIT FEE CALCULATION",
        )
        if not block:
            return []

        rows = _group_tier_rows(block[1:])
        tiers: list[ValuationTier] = []
        quoted: list[str] = [block[0].text]
        for row_lines in rows:
            tier = _parse_tier(" ".join(line.text.strip() for line in row_lines))
            if tier is not None:
                tiers.append(tier)
                quoted.extend(line.text for line in row_lines)
        if not tiers:
            return []

        provenance = self._provenance(context, facts, block[0], "\n".join(quoted))
        items = [
            FeeItem(
                jurisdiction_id=JURISDICTION_ID,
                state=STATE,
                permit_type="building_permit",
                item_id=f"{JURISDICTION_ID}/building_permit/valuation_table_a",
                label="Table A: Building Safety valuation-based permit fee",
                basis="valuation_tiered",
                status="published",
                tiers=tuple(tiers),
                conditions=(
                    "Permit fees are based on the valuation (building square footage times "
                    "standard rate for occupancy) of each building or building addition."
                ),
                provenance=provenance,
            )
        ]

        pool = _find_line(block, "swimming pools are subject to a minimum permit fee")
        if pool is not None:
            text = " ".join(
                line.text.strip()
                for line in block[block.index(pool) : block.index(pool) + 3]
            )
            minimum = re.search(rf"minimum permit fee of {_MONEY}", text, re.IGNORECASE)
            surcharge = re.search(rf"{_MONEY}\s+aquatics program surcharge", text, re.IGNORECASE)
            if minimum:
                items.append(
                    FeeItem(
                        jurisdiction_id=JURISDICTION_ID,
                        state=STATE,
                        permit_type="swimming_pool",
                        item_id=f"{JURISDICTION_ID}/swimming_pool/minimum_permit_fee",
                        label="Swimming pool minimum permit fee",
                        basis="flat",
                        status="published",
                        amount_usd=_money(minimum.group(1)),
                        minimum_usd=_money(minimum.group(1)),
                        surcharges=(
                            (
                                {
                                    "label": "Aquatics program surcharge",
                                    "amount_usd": _money(surcharge.group(1)),
                                    "authority": "Ordinance G-3114",
                                },
                            )
                            if surcharge
                            else ()
                        ),
                        conditions="Minimum; valuation-based fee applies above it.",
                        provenance=self._provenance(context, facts, pool, text),
                    )
                )
        return items

    # -- residential solar PV -------------------------------------------- #

    def _solar_options(self, context: DocumentContext, facts: dict) -> list[FeeItem]:
        block = slice_between(
            context.lines,
            "Residential Solar Photovoltaic System Permits",
            "Solar Water Heaters",
        )
        block = [line for line in block if line.stripped]
        if not block:
            return []

        items: list[FeeItem] = []
        for index, line in enumerate(block):
            match = _OPTION.search(line.text)
            if not match:
                continue
            letter, review, amount, trailing = match.groups()
            # Option C and E wrap: "$488 Administrative Fee and 2-" / "inspections".
            # Dropping the continuation would publish a fee whose printed condition
            # is truncated mid-word.
            quoted_lines = [line.text]
            for follower in block[index + 1 :]:
                text = follower.stripped
                if not text or "$" in text or _OPTION.search(follower.text):
                    break
                if re.match(r"^[a-z0-9]\s*[.)]\s", text, re.IGNORECASE) or text.startswith("The "):
                    break
                trailing = f"{trailing.rstrip()}{text}" if trailing.rstrip().endswith("-") else f"{trailing} {text}"
                quoted_lines.append(follower.text)
            conditions = " ".join(trailing.split()) or None
            items.append(
                FeeItem(
                    jurisdiction_id=JURISDICTION_ID,
                    state=STATE,
                    permit_type="residential_solar_pv",
                    item_id=f"{JURISDICTION_ID}/residential_solar_pv/fixed_option_{letter.lower()}",
                    label=f"Residential solar PV fixed fee — Option {letter} ({review.strip()})",
                    basis="option",
                    status="published",
                    amount_usd=_money(amount),
                    conditions=conditions,
                    provenance=self._provenance(
                        context, facts, line, "\n".join(quoted_lines).strip()
                    ),
                )
            )

        nonstandard = _find_line(block, "Non-Standard Residential Solar Photovoltaic Permit")
        if nonstandard is not None:
            items.append(
                FeeItem(
                    jurisdiction_id=JURISDICTION_ID,
                    state=STATE,
                    permit_type="residential_solar_pv",
                    item_id=f"{JURISDICTION_ID}/residential_solar_pv/non_standard",
                    label="Non-standard residential solar PV permit",
                    basis="reference",
                    status="published",
                    conditions="Priced from Table A on project valuation.",
                    provenance=self._provenance(
                        context, facts, nonstandard, nonstandard.text.strip()
                    ),
                )
            )
        if items:
            eligibility = _find_line(block, "firms desiring to use these fixed-fee options")
            if eligibility is not None:
                note = " ".join(
                    line.stripped
                    for line in block[block.index(eligibility) : block.index(eligibility) + 3]
                )
                items = [
                    _with_conditions(item, note) if item.basis == "option" else item
                    for item in items
                ]
        return items

    # -- what the document does NOT contain ------------------------------- #

    def _explicit_absences(self, context: DocumentContext, facts: dict) -> list[FeeItem]:
        """Rows for fees people expect Phoenix to publish, and it does not.

        These are answers, not gaps: a contractor searching "Phoenix residential
        mechanical permit fee" is better served by "priced on valuation, here is
        the table" than by a number nobody adopted.
        """
        reason = (
            "Phoenix publishes no flat fee for this permit type; installation, repair and "
            "replacement work is priced from Table A on project valuation "
            f"({JURISDICTION_ID}/building_permit/valuation_table_a)."
        )
        return [
            FeeItem(
                jurisdiction_id=JURISDICTION_ID,
                state=STATE,
                permit_type=permit_type,
                item_id=f"{JURISDICTION_ID}/{permit_type}/flat_fee",
                label=label,
                basis="reference",
                status="not_found_in_document",
                unavailable_reason=reason,
            )
            for permit_type, label in (
                ("residential_mechanical", "Residential mechanical permit — flat fee"),
                ("residential_electrical", "Residential electrical permit — flat fee"),
            )
        ]

    # ------------------------------------------------------------------ #

    def _provenance(
        self, context: DocumentContext, facts: dict, line: TextLine, matched_text: str
    ) -> Provenance:
        document = context.document
        return Provenance(
            source_url=document.source_url,
            document_sha256=document.sha256,
            retrieved_at=document.retrieved_at,
            matched_text=matched_text,
            page=line.page,
            line=line.line,
            effective_date=facts.get("effective_date"),
            adopting_instrument=facts.get("adopting_instrument"),
            approved_date=facts.get("approved_date"),
            code_reference=facts.get("code_reference"),
            document_title=facts.get("title"),
        )


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _iso(us_date: str) -> str:
    month, day, year = us_date.split("/")
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _find_line(lines: list[TextLine], needle: str) -> Optional[TextLine]:
    lowered = needle.lower()
    for line in lines:
        if lowered in line.text.lower():
            return line
    return None


def _with_conditions(item: FeeItem, extra: str) -> FeeItem:
    conditions = " ".join(filter(None, [item.conditions, extra])).strip()
    return FeeItem(
        jurisdiction_id=item.jurisdiction_id,
        state=item.state,
        permit_type=item.permit_type,
        item_id=item.item_id,
        label=item.label,
        basis=item.basis,
        status=item.status,
        amount_usd=item.amount_usd,
        unit=item.unit,
        tiers=item.tiers,
        conditions=conditions or None,
        minimum_usd=item.minimum_usd,
        surcharges=item.surcharges,
        provenance=item.provenance,
        unavailable_reason=item.unavailable_reason,
    )


def _group_tier_rows(lines: list[TextLine]) -> list[list[TextLine]]:
    """Group each tier's opening line with its wrapped continuation lines."""
    groups: list[list[TextLine]] = []
    for line in lines:
        if _TIER_START.match(line.text) or _TIER_OPEN.match(line.text):
            groups.append([line])
        elif groups and line.stripped and not line.stripped.startswith("*"):
            # continuation only while it is still prose about the current tier
            if len(groups[-1]) < 3:
                groups[-1].append(line)
    return groups


def _parse_tier(text: str) -> Optional[ValuationTier]:
    open_ended = _TIER_OPEN.match(text)
    if open_ended:
        floor, base, rest = open_ended.groups()
        return _tier(
            minimum=_money(floor),
            maximum=None,
            base=_money(base),
            rest=rest,
        )
    bounded = _TIER_START.match(text)
    if not bounded:
        return None
    floor, ceiling, base, rest = bounded.groups()
    return _tier(
        minimum=_money(floor),
        maximum=_money(ceiling),
        base=_money(base),
        rest=rest,
    )


def _tier(*, minimum: float, maximum: Optional[float], base: float, rest: str) -> ValuationTier:
    plus = _PLUS.search(rest)
    on_first = _ON_FIRST.search(rest)
    note = rest.strip() or None
    if plus:
        note = None if re.fullmatch(r"[\s,\.]*", _PLUS.sub("", _ON_FIRST.sub("", rest))) else note
    return ValuationTier(
        min_valuation_usd=minimum,
        max_valuation_usd=maximum,
        base_usd=base,
        plus_per_increment_usd=_money(plus.group(1)) if plus else None,
        increment_usd=_money(plus.group(2)) if plus else None,
        applies_above_usd=_money(on_first.group(1)) if on_first else None,
        note=note,
    )


PHOENIX = register(PhoenixExtractor())

__all__ = ["JURISDICTION_ID", "PHOENIX", "PhoenixExtractor"]
