"""The feed must not manufacture changes out of its own schedule.

``diff`` recomputes the whole archive on every run, and the collector runs on a
timer. Without identity on the event itself, each run re-appends the same
``first_observed`` rows and the feed reports ten changes a day that never
happened — a change feed whose content is its own cron entry. These tests pin
that the second run adds nothing.
"""

from __future__ import annotations

import json

import pytest

from openpermitfees.cli import _recorded_event_keys, main
from openpermitfees.models import ChangeEvent, event_key_of

SHA_ONE = "1" * 64
SHA_TWO = "2" * 64


def event(**overrides) -> ChangeEvent:
    payload = dict(
        jurisdiction_id="phoenix-az",
        event_type="first_observed",
        item_id="phoenix-az/solar/option_a",
        observed_at="2026-07-31T00:00:00+00:00",
        to_document_sha256=SHA_ONE,
    )
    payload.update(overrides)
    return ChangeEvent(**payload)


def test_event_key_ignores_when_we_looked():
    """Two runs over the same archive describe the same difference."""
    monday = event(observed_at="2026-08-03T09:20:00+00:00")
    tuesday = event(observed_at="2026-08-04T09:20:00+00:00")
    assert monday.event_key == tuesday.event_key


def test_event_key_separates_different_documents():
    assert event().event_key != event(to_document_sha256=SHA_TWO).event_key


def test_event_key_separates_fields_of_the_same_row():
    a = event(
        event_type="amount_changed",
        field_name="amount_usd",
        from_document_sha256=SHA_ONE,
        to_document_sha256=SHA_TWO,
    )
    b = event(
        event_type="amount_changed",
        field_name="minimum_usd",
        from_document_sha256=SHA_ONE,
        to_document_sha256=SHA_TWO,
    )
    assert a.event_key != b.event_key


def test_serialised_and_live_events_agree_on_identity():
    """A feed read back off disk must key the same as the object that wrote it."""
    live = event()
    assert event_key_of(json.loads(json.dumps(live.to_dict()))) == live.event_key


def test_reading_a_feed_recovers_every_key(tmp_path):
    feed = tmp_path / "changes.jsonl"
    events = [event(), event(item_id="phoenix-az/pool/minimum")]
    feed.write_text(
        "".join(json.dumps(e.to_dict(), sort_keys=True) + "\n" for e in events),
        encoding="utf-8",
    )
    assert _recorded_event_keys(feed) == {e.event_key for e in events}


def test_a_missing_feed_is_empty_not_an_error(tmp_path):
    assert _recorded_event_keys(tmp_path / "nothing.jsonl") == set()


def test_blank_lines_are_tolerated(tmp_path):
    feed = tmp_path / "changes.jsonl"
    feed.write_text(json.dumps(event().to_dict()) + "\n\n\n", encoding="utf-8")
    assert len(_recorded_event_keys(feed)) == 1


def test_an_unreadable_feed_refuses_rather_than_re_appending_everything(tmp_path):
    """Treating a damaged feed as empty would duplicate the entire history."""
    feed = tmp_path / "changes.jsonl"
    feed.write_text('{"jurisdiction_id": "phoenix-az"\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        _recorded_event_keys(feed)


def _run_diff(tmp_path, data_dir) -> list[dict]:
    out = tmp_path / "changes.jsonl"
    main(["diff", "--data-dir", str(data_dir), "--out", str(out)])
    return [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]


def test_a_second_run_over_an_unchanged_archive_appends_nothing(tmp_path, live_data_dir):
    """THE regression: a daily timer must not grow the feed by 10 events a day."""
    first = _run_diff(tmp_path, live_data_dir)
    assert first, "fixture archive produced no events — this test would be vacuous"
    second = _run_diff(tmp_path, live_data_dir)
    assert second == first


def test_a_third_run_still_appends_nothing(tmp_path, live_data_dir):
    baseline = _run_diff(tmp_path, live_data_dir)
    _run_diff(tmp_path, live_data_dir)
    assert _run_diff(tmp_path, live_data_dir) == baseline


def test_the_first_run_preserves_when_we_first_saw_it(tmp_path, live_data_dir):
    """Re-running must not restamp observed_at to the latest run's clock."""
    first = _run_diff(tmp_path, live_data_dir)
    stamps = {e["item_id"]: e["observed_at"] for e in first}
    second = _run_diff(tmp_path, live_data_dir)
    assert {e["item_id"]: e["observed_at"] for e in second} == stamps
