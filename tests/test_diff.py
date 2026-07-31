"""The change feed's one unbreakable rule, plus what counts as a change.

If the first sighting of a row were reported as a change, every fee in the
dataset would be dated to the day we started collecting — a claim about us
wearing the costume of a claim about the fee. The feed is only worth publishing
if that never happens.
"""

from __future__ import annotations

from openpermitfees.diff import TRACKED_FIELDS, diff_extractions

OBSERVED = "2026-07-31T00:00:00+00:00"
SHA_ONE = "1" * 64
SHA_TWO = "2" * 64


def snapshot(sha: str, items: list[dict], *, effective_date: str = "2026-01-20") -> dict:
    return {
        "document": {
            "jurisdiction_id": "phoenix-az",
            "sha256": sha,
            "source_url": "https://example.gov/fees.pdf",
            "effective_date": effective_date,
        },
        "items": items,
    }


def row(item_id: str, amount, **extra) -> dict:
    payload = {
        "item_id": item_id,
        "amount_usd": amount,
        "basis": "flat",
        "status": "published",
        "provenance": {"effective_date": "2026-01-20"},
    }
    payload.update(extra)
    return payload


def test_first_sighting_is_first_observed_and_nothing_else():
    events = diff_extractions(
        None, snapshot(SHA_ONE, [row("a", 780.0), row("b", 585.0)]), observed_at=OBSERVED
    )
    assert {e.event_type for e in events} == {"first_observed"}
    assert len(events) == 2
    assert all(e.from_document_sha256 is None for e in events)


def test_an_unchanged_document_produces_no_events():
    items = [row("a", 780.0)]
    events = diff_extractions(
        snapshot(SHA_ONE, items), snapshot(SHA_ONE, items), observed_at=OBSERVED
    )
    assert events == []


def test_a_changed_amount_is_dated_and_names_both_documents():
    events = diff_extractions(
        snapshot(SHA_ONE, [row("a", 780.0)]),
        snapshot(SHA_TWO, [row("a", 820.0)], effective_date="2027-01-01"),
        observed_at=OBSERVED,
    )
    kinds = [e.event_type for e in events]
    assert "document_replaced" in kinds
    changed = next(e for e in events if e.event_type == "amount_changed")
    assert (changed.old_value, changed.new_value) == (780.0, 820.0)
    assert changed.from_document_sha256 == SHA_ONE
    assert changed.to_document_sha256 == SHA_TWO
    assert changed.observed_at == OBSERVED
    assert changed.field_name == "amount_usd"


def test_added_and_removed_rows_are_distinct_from_amount_changes():
    events = diff_extractions(
        snapshot(SHA_ONE, [row("a", 780.0), row("gone", 100.0)]),
        snapshot(SHA_TWO, [row("a", 780.0), row("new", 200.0)]),
        observed_at=OBSERVED,
    )
    by_type = {e.event_type: e for e in events if e.event_type != "document_replaced"}
    assert by_type["row_added"].item_id == "new"
    assert by_type["row_removed"].item_id == "gone"
    assert "amount_changed" not in by_type


def test_a_row_becoming_unsourced_is_reported():
    """A fee disappearing from the document is news, not silence."""
    events = diff_extractions(
        snapshot(SHA_ONE, [row("a", 780.0)]),
        snapshot(
            SHA_TWO,
            [
                {
                    "item_id": "a",
                    "amount_usd": None,
                    "basis": "reference",
                    "status": "not_found_in_document",
                }
            ],
        ),
        observed_at=OBSERVED,
    )
    fields = {e.field_name for e in events if e.field_name}
    assert {"amount_usd", "status", "basis"} <= fields


def test_presentation_only_churn_is_not_tracked():
    """Re-typeset labels and reworded conditions must not flood the feed."""
    assert "label" not in TRACKED_FIELDS
    assert "conditions" not in TRACKED_FIELDS
    events = diff_extractions(
        snapshot(SHA_ONE, [row("a", 780.0, label="Option A", conditions="one inspection")]),
        snapshot(SHA_ONE, [row("a", 780.0, label="OPTION A", conditions="1 inspection")]),
        observed_at=OBSERVED,
    )
    assert events == []


def test_same_bytes_different_run_is_not_a_document_replacement():
    items = [row("a", 780.0)]
    events = diff_extractions(
        snapshot(SHA_ONE, items), snapshot(SHA_ONE, items), observed_at="2026-08-05T00:00:00+00:00"
    )
    assert not any(e.event_type == "document_replaced" for e in events)
