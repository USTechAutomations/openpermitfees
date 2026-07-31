"""The schema's refusals.

Every test here asserts that something is IMPOSSIBLE to construct. That is the
only kind of guarantee worth publishing: a dataset whose invariants are checked
by convention holds until the first tired afternoon.
"""

from __future__ import annotations

import pytest

from openpermitfees.models import (
    BASIS,
    CHANGE_EVENT_TYPES,
    ChangeEvent,
    FeeItem,
    Provenance,
    SCHEMA_VERSION,
    STATUS,
    SchemaViolation,
    ValuationTier,
)

SHA = "a" * 64


def provenance(matched_text: str = "Option A - Over the Counter Review ....... $780", **kw):
    return Provenance(
        source_url="https://example.gov/fees.pdf",
        document_sha256=SHA,
        retrieved_at="2026-07-31T00:00:00+00:00",
        matched_text=matched_text,
        **kw,
    )


def fee(**overrides):
    payload = dict(
        jurisdiction_id="example-az",
        state="AZ",
        permit_type="residential_solar_pv",
        item_id="example-az/residential_solar_pv/fixed_option_a",
        label="Option A",
        basis="option",
        status="published",
        amount_usd=780.0,
        provenance=provenance(),
    )
    payload.update(overrides)
    return FeeItem(**payload)


# --------------------------------------------------------------------------- #
# a number cannot exist without a citation that quotes it
# --------------------------------------------------------------------------- #


def test_published_row_requires_provenance():
    with pytest.raises(SchemaViolation, match="require"):
        fee(provenance=None)


def test_amount_must_appear_in_the_quoted_source_line():
    """The load-bearing check: a parser that drifts one line fails loudly."""
    with pytest.raises(SchemaViolation, match="does not appear in the quoted source line"):
        fee(amount_usd=781.0)


def test_amount_matches_despite_thousands_separator_and_cents():
    row = fee(amount_usd=2053.0, provenance=provenance(matched_text="$100,001 - $500,000  $2,053"))
    assert row.amount_usd == 2053.0
    assert fee(amount_usd=98.0, provenance=provenance(matched_text="minimum fee of $98.00")).amount_usd == 98.0


def test_every_tier_base_must_also_be_quoted():
    quote = "$1 - $1,000   $195\n$1,001 - $25,000   $243"
    good = fee(
        basis="valuation_tiered",
        amount_usd=None,
        tiers=(
            ValuationTier(min_valuation_usd=1, max_valuation_usd=1000, base_usd=195),
            ValuationTier(min_valuation_usd=1001, max_valuation_usd=25000, base_usd=243),
        ),
        provenance=provenance(matched_text=quote),
    )
    assert len(good.tiers) == 2

    with pytest.raises(SchemaViolation, match=r"tier\[1001\].base_usd"):
        fee(
            basis="valuation_tiered",
            amount_usd=None,
            tiers=(
                ValuationTier(min_valuation_usd=1, max_valuation_usd=1000, base_usd=195),
                ValuationTier(min_valuation_usd=1001, max_valuation_usd=25000, base_usd=244),
            ),
            provenance=provenance(matched_text=quote),
        )


def test_minimum_must_be_quoted_too():
    with pytest.raises(SchemaViolation, match="minimum_usd"):
        fee(
            basis="flat",
            amount_usd=None,
            minimum_usd=234.0,
            provenance=provenance(matched_text="minimum permit fee of $230"),
        )


def test_provenance_requires_a_full_digest_and_a_quote():
    with pytest.raises(SchemaViolation, match="document_sha256 must be a full sha256"):
        Provenance(
            source_url="https://example.gov/fees.pdf",
            document_sha256="abc123",
            retrieved_at="2026-07-31T00:00:00+00:00",
            matched_text="$780",
        )
    with pytest.raises(SchemaViolation, match="matched_text is required"):
        Provenance(
            source_url="https://example.gov/fees.pdf",
            document_sha256=SHA,
            retrieved_at="2026-07-31T00:00:00+00:00",
            matched_text="   ",
        )


# --------------------------------------------------------------------------- #
# UNKNOWN is a value, not a blank
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "status", ["not_found_in_document", "not_published_by_jurisdiction", "not_fetched"]
)
def test_unpublished_rows_cannot_carry_a_number(status):
    with pytest.raises(SchemaViolation, match="cannot carry an amount"):
        fee(status=status, unavailable_reason="priced on valuation")


@pytest.mark.parametrize(
    "status", ["not_found_in_document", "not_published_by_jurisdiction", "not_fetched"]
)
def test_unpublished_rows_must_say_why(status):
    with pytest.raises(SchemaViolation, match="requires unavailable_reason"):
        fee(status=status, amount_usd=None, provenance=None)


def test_unknown_basis_and_status_are_rejected():
    with pytest.raises(SchemaViolation, match="unknown basis"):
        fee(basis="typical")
    with pytest.raises(SchemaViolation, match="unknown status"):
        fee(status="probably")


def test_there_is_no_typical_fee_basis():
    """A scalar 'typical fee' is the fabrication this project exists to stop."""
    assert "typical" not in BASIS and "estimate" not in BASIS
    assert "estimated" not in STATUS


# --------------------------------------------------------------------------- #
# frozen schema
# --------------------------------------------------------------------------- #


def test_schema_version_is_pinned():
    """Consumers cache field names; a rename inside 1.x evicts us from their configs."""
    assert SCHEMA_VERSION == "1.0.0"


def test_public_field_set_is_frozen():
    assert set(FeeItem.__dataclass_fields__) == {
        "jurisdiction_id",
        "state",
        "permit_type",
        "item_id",
        "label",
        "basis",
        "status",
        "amount_usd",
        "unit",
        "tiers",
        "conditions",
        "minimum_usd",
        "surcharges",
        "provenance",
        "unavailable_reason",
        "schema_version",
    }
    assert set(Provenance.__dataclass_fields__) == {
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
    assert BASIS == {"flat", "option", "valuation_tiered", "per_unit", "percent_of", "reference"}
    assert STATUS == {
        "published",
        "not_found_in_document",
        "not_published_by_jurisdiction",
        "not_fetched",
    }


# --------------------------------------------------------------------------- #
# round trip
# --------------------------------------------------------------------------- #


def test_round_trip_preserves_a_tiered_row_including_the_open_ended_tier():
    original = fee(
        basis="valuation_tiered",
        amount_usd=None,
        tiers=(
            ValuationTier(min_valuation_usd=1, max_valuation_usd=1000, base_usd=195),
            ValuationTier(
                min_valuation_usd=1000001,
                max_valuation_usd=None,
                base_usd=7803,
                plus_per_increment_usd=5,
                increment_usd=1000,
                applies_above_usd=1000000,
            ),
        ),
        provenance=provenance(matched_text="$1 - $1,000 $195\nOver $1,000,000 $7,803"),
    )
    restored = FeeItem.from_dict(original.to_dict())
    assert restored == original
    assert restored.tiers[1].max_valuation_usd is None


def test_reading_validates_as_strictly_as_writing():
    """A hand-edited export cannot smuggle in an unsourced number."""
    payload = fee().to_dict()
    payload["amount_usd"] = 999.0
    with pytest.raises(SchemaViolation, match="does not appear in the quoted source line"):
        FeeItem.from_dict(payload)


# --------------------------------------------------------------------------- #
# change events
# --------------------------------------------------------------------------- #


def test_first_observed_cannot_claim_a_predecessor():
    with pytest.raises(SchemaViolation, match="first_observed cannot have a predecessor"):
        ChangeEvent(
            jurisdiction_id="example-az",
            event_type="first_observed",
            item_id="example-az/x",
            observed_at="2026-07-31T00:00:00+00:00",
            to_document_sha256=SHA,
            from_document_sha256="c" * 64,
        )


def test_a_real_change_must_name_both_documents():
    with pytest.raises(SchemaViolation, match="requires from_document_sha256"):
        ChangeEvent(
            jurisdiction_id="example-az",
            event_type="amount_changed",
            item_id="example-az/x",
            observed_at="2026-07-31T00:00:00+00:00",
            to_document_sha256=SHA,
        )


def test_first_observed_is_an_event_type_but_never_a_change_type():
    assert "first_observed" in CHANGE_EVENT_TYPES
    assert "fee_changed" not in CHANGE_EVENT_TYPES
