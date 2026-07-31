"""The pipeline's contract: a jurisdiction is never silently absent.

A missing jurisdiction reads to a user as "no fees here". A jurisdiction we could
not fetch must therefore still produce a row, carrying the reason, so that the
difference between "we broke" and "nothing to charge" survives into the dataset.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openpermitfees.collect import Collector, collect_all
from openpermitfees.fetch import FetchResult
from openpermitfees.registry import Jurisdiction

URL = "https://example.gov/fees.txt"


@pytest.fixture()
def registry_dir(tmp_path: Path, phoenix_text: str) -> Path:
    """A registry whose one jurisdiction is served from a local text file."""
    directory = tmp_path / "jurisdictions"
    directory.mkdir()
    document = tmp_path / "phoenix.txt"
    document.write_text(phoenix_text, encoding="utf-8")
    (directory / "phoenix-az.json").write_text(
        json.dumps(
            {
                "id": "phoenix-az",
                "name": "Phoenix, AZ",
                "state": "AZ",
                "extractor": "phoenix-az",
                "documents": [{"url": URL, "media_type": "text/plain"}],
            }
        ),
        encoding="utf-8",
    )
    return directory


@pytest.fixture()
def serve_text(monkeypatch, phoenix_text: str):
    """Serve the fixture bytes in place of the network."""

    def _serve(payload: str = phoenix_text):
        def fake_fetch(url, **kwargs):
            return FetchResult(
                url=url,
                ok=True,
                payload=payload.encode("utf-8"),
                media_type="text/plain",
                http_status=200,
                retrieved_at="2026-07-31T00:00:00+00:00",
            )

        monkeypatch.setattr("openpermitfees.collect.fetch", fake_fetch)

    return _serve


def test_a_successful_run_writes_the_extraction_and_archives_the_bytes(
    tmp_path, registry_dir, serve_text
):
    serve_text()
    results = collect_all(tmp_path / "data", registry_dir=registry_dir)
    assert len(results) == 1
    result = results[0]
    assert result.ok
    assert result.changed_bytes is None, "the first observation is not a change"
    assert sum(1 for i in result.items if i.status == "published") == 8

    extraction = (
        tmp_path / "data" / "extracted" / "phoenix-az" / f"{result.document.sha256}.json"
    )
    payload = json.loads(extraction.read_text(encoding="utf-8"))
    assert payload["document"]["adopting_instrument"] == "Ordinance G-7465"
    assert len(payload["items"]) == 10


def test_a_second_identical_run_reports_unchanged(tmp_path, registry_dir, serve_text):
    serve_text()
    collect_all(tmp_path / "data", registry_dir=registry_dir)
    again = collect_all(tmp_path / "data", registry_dir=registry_dir)
    assert again[0].changed_bytes is False


def test_a_changed_document_is_reported_as_changed(tmp_path, registry_dir, serve_text, phoenix_text):
    serve_text()
    collect_all(tmp_path / "data", registry_dir=registry_dir)
    serve_text(phoenix_text + "\n(amended)\n")
    result = collect_all(tmp_path / "data", registry_dir=registry_dir)[0]
    assert result.changed_bytes is True


def test_a_fetch_failure_still_produces_a_row_with_the_reason(tmp_path, registry_dir, monkeypatch):
    monkeypatch.setattr(
        "openpermitfees.collect.fetch",
        lambda url, **kwargs: FetchResult(url=url, ok=False, reason="HTTP 404"),
    )
    result = collect_all(tmp_path / "data", registry_dir=registry_dir)[0]
    assert result.ok is False
    assert len(result.items) == 1
    row = result.items[0]
    assert row.status == "not_fetched"
    assert row.amount_usd is None
    assert "HTTP 404" in row.unavailable_reason and URL in row.unavailable_reason


def test_a_jurisdiction_with_no_extractor_is_marked_not_fetched_not_dropped(tmp_path, serve_text):
    serve_text()
    collector = Collector(tmp_path / "data")
    jurisdiction = Jurisdiction(
        id="nowhere-az",
        name="Nowhere, AZ",
        state="AZ",
        documents=({"url": URL, "media_type": "text/plain"},),
        extractor="nowhere-az",
    )
    items = collector.collect_jurisdiction(jurisdiction)[0].items
    assert [i.status for i in items] == ["not_fetched"]
    assert "no extractor registered" in items[0].unavailable_reason


def test_the_shipped_registry_is_loadable_and_every_entry_has_an_extractor():
    """Also pins that the registry travels inside the package.

    Resolving it relative to the repository root works in a checkout and fails
    silently in an installed wheel — as an empty registry, i.e. a collector that
    reports success and fetches nothing.
    """
    from openpermitfees.extract import registered
    from openpermitfees.registry import DEFAULT_REGISTRY_DIR, load_registry

    import openpermitfees

    assert DEFAULT_REGISTRY_DIR.parent == Path(openpermitfees.__file__).resolve().parent

    registry = load_registry()
    assert registry, "the shipped registry is empty"
    for jurisdiction in registry.values():
        assert jurisdiction.documents, f"{jurisdiction.id} watches no document"
        assert (jurisdiction.extractor or jurisdiction.id) in registered(), (
            f"{jurisdiction.id} has no extractor and would publish nothing"
        )
