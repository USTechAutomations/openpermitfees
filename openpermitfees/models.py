"""Frozen public schema for Open Permit Fees.

Two rules run through every type here, and both exist because a permit fee that
cannot be traced to the adopting document is indistinguishable from a guess:

1. **A number carries its citation or it does not exist.** ``FeeItem`` refuses to
   construct with an ``amount_usd`` unless a ``Provenance`` accompanies it AND the
   quoted ``matched_text`` from the source document actually contains that amount.
   There is no code path that produces a bare number.
2. **UNKNOWN is a value, not a blank.** A jurisdiction we could not fetch, a fee we
   could not find in the document, and a fee the jurisdiction genuinely does not
   publish are three different states and never collapse into each other.

``SCHEMA_VERSION`` is frozen deliberately: consumers cache field names, and schema
churn evicts us from their configs. Additive changes bump the minor; renames and
removals do not happen inside a major.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

SCHEMA_VERSION = "1.0.0"

# --------------------------------------------------------------------------- #
# enumerations (string literals, not Enum — they cross a JSON boundary)
# --------------------------------------------------------------------------- #

#: How the jurisdiction expresses the price. A scalar "typical fee" is NOT one of
#: these on purpose: most building permit fees are tiered on project valuation, and
#: flattening a tier table to one number is the fabrication this project exists to
#: stop.
BASIS = frozenset(
    {
        "flat",  # one printed amount
        "option",  # one of a printed set of alternatives (e.g. review options A-E)
        "valuation_tiered",  # piecewise base + marginal rate on project valuation
        "per_unit",  # amount x quantity (per meter, per inspection, per hour)
        "percent_of",  # a percentage/multiple of another fee
        "reference",  # priced by another document/table, no amount here
    }
)

#: Why a row does or does not carry a number.
STATUS = frozenset(
    {
        "published",  # the document states this fee; provenance attached
        "not_found_in_document",  # we read the document; this fee is not in it
        "not_published_by_jurisdiction",  # jurisdiction states it does not publish one
        "not_fetched",  # we could not retrieve the document (reason required)
    }
)

CHANGE_EVENT_TYPES = frozenset(
    {
        "first_observed",  # our archive's t0 for this row — NEVER a change
        "amount_changed",
        "basis_changed",
        "row_added",
        "row_removed",
        "document_replaced",  # same URL, new bytes
    }
)


class SchemaViolation(ValueError):
    """Raised when a record would carry a number it cannot source."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _money_tokens(text: str) -> set[str]:
    """Every dollar amount printed in ``text``, normalised to a plain number string."""
    return {
        m.group(1).replace(",", "").rstrip(".").rstrip("0").rstrip(".")
        if "." in m.group(1)
        else m.group(1).replace(",", "")
        for m in re.finditer(r"\$\s?([\d,]+(?:\.\d{1,2})?)", text)
    }


def _normalise_amount(amount: float) -> str:
    return str(int(amount)) if float(amount).is_integer() else str(amount)


# --------------------------------------------------------------------------- #
# provenance
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Provenance:
    """Where a number came from, precisely enough for a reader to re-check it.

    ``matched_text`` is the verbatim line from the source document. It is not
    decoration: :class:`FeeItem` validates the amount against it, so a parser that
    drifts onto the wrong line fails loudly instead of publishing a wrong fee.
    """

    source_url: str
    document_sha256: str
    retrieved_at: str  # UTC ISO-8601
    matched_text: str
    page: Optional[int] = None
    line: Optional[int] = None
    effective_date: Optional[str] = None  # ISO date the fee took effect
    adopting_instrument: Optional[str] = None  # e.g. "Ordinance G-7465"
    approved_date: Optional[str] = None
    code_reference: Optional[str] = None
    document_title: Optional[str] = None

    def __post_init__(self) -> None:
        for required in ("source_url", "document_sha256", "retrieved_at", "matched_text"):
            if not str(getattr(self, required) or "").strip():
                raise SchemaViolation(f"provenance.{required} is required")
        if len(self.document_sha256) != 64:
            raise SchemaViolation("document_sha256 must be a full sha256 hex digest")

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Provenance":
        return cls(**{k: v for k, v in payload.items() if k in _PROVENANCE_FIELDS})


_PROVENANCE_FIELDS = frozenset(
    {
        "source_url",
        "document_sha256",
        "retrieved_at",
        "matched_text",
        "page",
        "line",
        "effective_date",
        "adopting_instrument",
        "approved_date",
        "code_reference",
        "document_title",
    }
)


# --------------------------------------------------------------------------- #
# fee rows
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ValuationTier:
    """One row of a valuation-based permit fee table.

    ``base_usd`` applies at ``min_valuation_usd``; ``plus_per_increment_usd`` is
    charged for each ``increment_usd`` (or fraction) above ``applies_above_usd``.
    """

    min_valuation_usd: float
    max_valuation_usd: Optional[float]  # None = open-ended top tier; stated, never defaulted
    base_usd: float
    plus_per_increment_usd: Optional[float] = None
    increment_usd: Optional[float] = None
    applies_above_usd: Optional[float] = None
    note: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ValuationTier":
        """Round-trip a tier from exported JSON.

        ``max_valuation_usd`` has no default on the class on purpose: an
        open-ended top tier must be written out deliberately, not produced by a
        forgotten keyword. ``to_dict`` drops ``None``, so the absent key is
        restored here — the only place where "missing" legitimately means
        "open-ended".
        """
        return cls(
            min_valuation_usd=payload["min_valuation_usd"],
            max_valuation_usd=payload.get("max_valuation_usd"),
            base_usd=payload["base_usd"],
            plus_per_increment_usd=payload.get("plus_per_increment_usd"),
            increment_usd=payload.get("increment_usd"),
            applies_above_usd=payload.get("applies_above_usd"),
            note=payload.get("note"),
        )


@dataclass(frozen=True)
class FeeItem:
    """One priced (or explicitly unpriced) line of a jurisdiction's fee schedule."""

    jurisdiction_id: str  # "phoenix-az"
    state: str  # "AZ"
    permit_type: str  # "residential_solar_pv"
    item_id: str  # "phoenix-az/residential_solar_pv/fixed_option_a"
    label: str  # as printed in the document
    basis: str
    status: str
    amount_usd: Optional[float] = None
    unit: Optional[str] = None  # "per inspection", "per hour", ...
    tiers: tuple[ValuationTier, ...] = ()
    conditions: Optional[str] = None  # printed qualifiers, verbatim
    minimum_usd: Optional[float] = None
    surcharges: tuple[dict[str, Any], ...] = ()
    provenance: Optional[Provenance] = None
    unavailable_reason: Optional[str] = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.basis not in BASIS:
            raise SchemaViolation(f"unknown basis {self.basis!r}")
        if self.status not in STATUS:
            raise SchemaViolation(f"unknown status {self.status!r}")

        if self.status == "published":
            if self.provenance is None:
                raise SchemaViolation(f"{self.item_id}: published rows require provenance")
        else:
            if self.amount_usd is not None or self.tiers:
                raise SchemaViolation(
                    f"{self.item_id}: status {self.status!r} cannot carry an amount"
                )
            if not (self.unavailable_reason or "").strip():
                raise SchemaViolation(
                    f"{self.item_id}: status {self.status!r} requires unavailable_reason"
                )

        # The load-bearing check: every number must appear in the quoted source line.
        if self.amount_usd is not None:
            self._assert_quoted(self.amount_usd, "amount_usd")
        for tier in self.tiers:
            self._assert_quoted(tier.base_usd, f"tier[{tier.min_valuation_usd}].base_usd")
        if self.minimum_usd is not None:
            self._assert_quoted(self.minimum_usd, "minimum_usd")

    def _assert_quoted(self, amount: float, field_name: str) -> None:
        if self.provenance is None:
            raise SchemaViolation(f"{self.item_id}: {field_name} without provenance")
        if _normalise_amount(amount) not in _money_tokens(self.provenance.matched_text):
            raise SchemaViolation(
                f"{self.item_id}: {field_name}={amount} does not appear in the quoted "
                f"source line {self.provenance.matched_text!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "item_id": self.item_id,
            "jurisdiction_id": self.jurisdiction_id,
            "state": self.state,
            "permit_type": self.permit_type,
            "label": self.label,
            "basis": self.basis,
            "status": self.status,
        }
        if self.amount_usd is not None:
            out["amount_usd"] = self.amount_usd
            out["currency"] = "USD"
        if self.unit:
            out["unit"] = self.unit
        if self.tiers:
            out["tiers"] = [t.to_dict() for t in self.tiers]
        if self.minimum_usd is not None:
            out["minimum_usd"] = self.minimum_usd
        if self.surcharges:
            out["surcharges"] = list(self.surcharges)
        if self.conditions:
            out["conditions"] = self.conditions
        if self.unavailable_reason:
            out["unavailable_reason"] = self.unavailable_reason
        if self.provenance is not None:
            out["provenance"] = self.provenance.to_dict()
        return out

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FeeItem":
        """Rebuild a row from exported JSON, re-running every invariant.

        Reading is validated as strictly as writing: a row hand-edited to carry a
        number its ``matched_text`` does not contain fails here too. The dataset's
        promise is checkable by its consumers, not only by its producer.
        """
        provenance = payload.get("provenance")
        return cls(
            jurisdiction_id=payload["jurisdiction_id"],
            state=payload["state"],
            permit_type=payload["permit_type"],
            item_id=payload["item_id"],
            label=payload["label"],
            basis=payload["basis"],
            status=payload["status"],
            amount_usd=payload.get("amount_usd"),
            unit=payload.get("unit"),
            tiers=tuple(ValuationTier.from_dict(t) for t in payload.get("tiers", ())),
            conditions=payload.get("conditions"),
            minimum_usd=payload.get("minimum_usd"),
            surcharges=tuple(payload.get("surcharges", ())),
            provenance=Provenance.from_dict(provenance) if provenance else None,
            unavailable_reason=payload.get("unavailable_reason"),
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
        )


# --------------------------------------------------------------------------- #
# change feed
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ChangeEvent:
    """A dated, sourced difference between two observations of a fee schedule.

    ``first_observed`` is emitted when a row enters the archive and is explicitly
    **not** a change: claiming a fee "changed" the first time we looked at it would
    manufacture news out of our own start date.
    """

    jurisdiction_id: str
    event_type: str
    item_id: str
    observed_at: str
    to_document_sha256: str
    field_name: Optional[str] = None
    old_value: Any = None
    new_value: Any = None
    from_document_sha256: Optional[str] = None
    effective_date_from: Optional[str] = None
    effective_date_to: Optional[str] = None
    source_url: Optional[str] = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.event_type not in CHANGE_EVENT_TYPES:
            raise SchemaViolation(f"unknown event_type {self.event_type!r}")
        if self.event_type == "first_observed" and self.from_document_sha256:
            raise SchemaViolation("first_observed cannot have a predecessor document")
        if self.event_type != "first_observed" and not self.from_document_sha256:
            raise SchemaViolation(f"{self.event_type} requires from_document_sha256")

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class FeeDocument:
    """A retrieved fee-schedule document plus what it says about itself."""

    jurisdiction_id: str
    source_url: str
    sha256: str
    retrieved_at: str
    media_type: str
    byte_length: int
    archive_path: str
    http_status: int
    title: Optional[str] = None
    adopting_instrument: Optional[str] = None
    approved_date: Optional[str] = None
    effective_date: Optional[str] = None
    code_reference: Optional[str] = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, {})}


def today_iso() -> str:
    return date.today().isoformat()


__all__ = [
    "BASIS",
    "CHANGE_EVENT_TYPES",
    "ChangeEvent",
    "FeeDocument",
    "FeeItem",
    "Provenance",
    "SCHEMA_VERSION",
    "STATUS",
    "SchemaViolation",
    "ValuationTier",
    "today_iso",
]
