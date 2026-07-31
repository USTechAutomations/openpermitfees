"""The change feed: dated, sourced differences between two observations.

This is the part of the dataset nobody else sells. Jurisdictions publish the
*current* fee schedule and overwrite it; "what did Phoenix charge in March, and
when did it change?" is unanswerable from any public source once the PDF is
replaced. Diffing our own archive answers it — but only for the window we have
actually observed.

Hence the one rule this module refuses to break: **the first sighting of a row is
``first_observed``, never a change.** Emitting "fee changed" the first time we
look would date every fee in the country to the day we started collecting, which
is a claim about us, not about the fee.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from .models import ChangeEvent

#: Fields whose movement is worth a dated event. Presentation-only differences
#: (label wording, conditions rewording) are deliberately excluded — they churn
#: with every document re-typeset and would drown the signal.
TRACKED_FIELDS = ("amount_usd", "basis", "status", "minimum_usd", "tiers")


def _index(items: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["item_id"]: item for item in items}


def _effective(item: Optional[dict[str, Any]]) -> Optional[str]:
    if not item:
        return None
    return (item.get("provenance") or {}).get("effective_date")


def diff_extractions(
    previous: Optional[dict[str, Any]],
    current: dict[str, Any],
    *,
    observed_at: str,
) -> list[ChangeEvent]:
    """Compare two extraction snapshots of the same jurisdiction."""
    current_doc = current["document"]
    current_items = _index(current["items"])
    jurisdiction_id = current_doc["jurisdiction_id"]
    to_sha = current_doc["sha256"]
    source_url = current_doc.get("source_url")

    if previous is None:
        return [
            ChangeEvent(
                jurisdiction_id=jurisdiction_id,
                event_type="first_observed",
                item_id=item_id,
                observed_at=observed_at,
                to_document_sha256=to_sha,
                new_value=item.get("amount_usd"),
                effective_date_to=_effective(item),
                source_url=source_url,
            )
            for item_id, item in sorted(current_items.items())
        ]

    previous_doc = previous["document"]
    from_sha = previous_doc["sha256"]
    previous_items = _index(previous["items"])
    events: list[ChangeEvent] = []

    if from_sha != to_sha:
        events.append(
            ChangeEvent(
                jurisdiction_id=jurisdiction_id,
                event_type="document_replaced",
                item_id=f"{jurisdiction_id}/document",
                observed_at=observed_at,
                from_document_sha256=from_sha,
                to_document_sha256=to_sha,
                old_value=previous_doc.get("effective_date"),
                new_value=current_doc.get("effective_date"),
                effective_date_from=previous_doc.get("effective_date"),
                effective_date_to=current_doc.get("effective_date"),
                source_url=source_url,
            )
        )

    for item_id in sorted(set(previous_items) | set(current_items)):
        before = previous_items.get(item_id)
        after = current_items.get(item_id)
        common = dict(
            jurisdiction_id=jurisdiction_id,
            item_id=item_id,
            observed_at=observed_at,
            from_document_sha256=from_sha,
            to_document_sha256=to_sha,
            source_url=source_url,
            effective_date_from=_effective(before),
            effective_date_to=_effective(after),
        )
        if before is None:
            events.append(
                ChangeEvent(event_type="row_added", new_value=after.get("amount_usd"), **common)
            )
            continue
        if after is None:
            events.append(
                ChangeEvent(event_type="row_removed", old_value=before.get("amount_usd"), **common)
            )
            continue
        for field_name in TRACKED_FIELDS:
            old, new = before.get(field_name), after.get(field_name)
            if old == new:
                continue
            events.append(
                ChangeEvent(
                    event_type=(
                        "amount_changed"
                        if field_name in ("amount_usd", "minimum_usd", "tiers")
                        else "basis_changed"
                    ),
                    field_name=field_name,
                    old_value=old,
                    new_value=new,
                    **common,
                )
            )
    return events


__all__ = ["TRACKED_FIELDS", "diff_extractions"]
