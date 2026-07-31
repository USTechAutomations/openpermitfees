"""The published artefacts, including the negative controls.

Two properties matter more than any field layout:

1. **Every published number in the export carries its citation.** Not "most" —
   the assertion is over all rows, so a single uncited number fails the build.
2. **The export cannot manufacture coverage.** If extraction produces nothing,
   the dataset must be visibly empty rather than quietly stale. That is the
   inverse-mutation check: force the extractor to refuse, and the export must
   contain zero published rows.
"""

from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path

import pytest

from openpermitfees.export import (
    CSV_COLUMNS,
    DATASET_NAME,
    coverage,
    dataset_card,
    flatten,
    latest_rows,
    schema_org_dataset,
    to_csv,
    to_jsonl,
    write_exports,
)
from openpermitfees.fetch import FetchResult
from openpermitfees.models import FeeItem

GENERATED_AT = "2026-07-31T00:00:00+00:00"
URL = "https://example.gov/fees.txt"


@pytest.fixture()
def collected(tmp_path, phoenix_text, monkeypatch) -> Path:
    """A data dir holding one real collection run, served from the fixture."""
    from openpermitfees.collect import collect_all

    directory = tmp_path / "jurisdictions"
    directory.mkdir()
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
    monkeypatch.setattr(
        "openpermitfees.collect.fetch",
        lambda url, **kwargs: FetchResult(
            url=url,
            ok=True,
            payload=phoenix_text.encode("utf-8"),
            media_type="text/plain",
            http_status=200,
            retrieved_at=GENERATED_AT,
        ),
    )
    collect_all(tmp_path / "data", registry_dir=directory)
    return tmp_path / "data"


# --------------------------------------------------------------------------- #
# every number is cited
# --------------------------------------------------------------------------- #


def test_every_published_row_in_the_export_carries_a_full_citation(collected):
    rows = latest_rows(collected)
    published = [r for r in rows if r["status"] == "published"]
    assert published
    for row in published:
        provenance = row["provenance"]
        assert provenance["source_url"] == URL
        assert len(provenance["document_sha256"]) == 64
        assert provenance["retrieved_at"] == GENERATED_AT
        assert provenance["effective_date"] == "2026-01-20"
        assert provenance["adopting_instrument"] == "Ordinance G-7465"
        assert provenance["page"] and provenance["line"]
        assert provenance["matched_text"].strip()


def test_every_exported_row_survives_being_read_back(collected):
    """The consumer's validation is the producer's validation."""
    for row in latest_rows(collected):
        assert FeeItem.from_dict(row).item_id == row["item_id"]


def test_unpublished_rows_carry_a_reason_and_no_number(collected):
    rows = [r for r in latest_rows(collected) if r["status"] != "published"]
    assert rows
    for row in rows:
        assert "amount_usd" not in row
        assert row["unavailable_reason"].strip()


# --------------------------------------------------------------------------- #
# the export publishes its own holes
# --------------------------------------------------------------------------- #


def test_coverage_counts_the_gaps_not_only_the_wins(collected):
    cover = coverage(latest_rows(collected), generated_from="test")
    assert cover.rows == 10
    assert cover.by_status == {"not_found_in_document": 2, "published": 8}
    assert cover.jurisdictions == 1
    assert cover.with_effective_date == 8


def test_the_dataset_card_states_the_gaps(collected):
    cover = coverage(latest_rows(collected), generated_from="test")
    card = dataset_card(cover, generated_at=GENERATED_AT, jurisdictions=["Phoenix, AZ"])
    assert DATASET_NAME in card
    assert "not_found_in_document" in card
    assert "no \"typical fee\" column" in card
    assert "first_observed" in card


def test_csv_columns_are_stable_and_provenance_is_inline(collected):
    rows = latest_rows(collected)
    parsed = list(csv.DictReader(StringIO(to_csv(rows))))
    assert list(parsed[0]) == CSV_COLUMNS
    assert len(parsed) == len(rows)
    for row in parsed:
        if row["status"] == "published":
            assert row["source_url"] and row["document_sha256"] and row["matched_text"]
        else:
            assert row["amount_usd"] == ""
            assert row["unavailable_reason"]


def test_csv_matched_text_is_single_line(collected):
    """Table A quotes eight wrapped rows; a raw newline would break the CSV shape."""
    table = next(r for r in latest_rows(collected) if r["item_id"].endswith("valuation_table_a"))
    assert "\n" in table["provenance"]["matched_text"]
    assert "\n" not in flatten(table)["matched_text"]


def test_jsonl_is_one_object_per_line(collected):
    rows = latest_rows(collected)
    lines = to_jsonl(rows).strip().split("\n")
    assert len(lines) == len(rows)
    assert all(json.loads(line)["schema_version"] == "1.0.0" for line in lines)


def test_schema_org_markup_names_the_license_and_the_states(collected):
    markup = schema_org_dataset(latest_rows(collected), generated_at=GENERATED_AT)
    assert markup["@type"] == "Dataset"
    assert markup["license"].startswith("https://creativecommons.org/licenses/by/4.0")
    assert {"@type": "Place", "name": "AZ"} in markup["spatialCoverage"]
    assert markup["dateModified"] == GENERATED_AT


def test_write_exports_produces_every_artefact(collected, tmp_path):
    written = write_exports(
        collected,
        tmp_path / "dist",
        generated_at=GENERATED_AT,
        jurisdiction_names=["Phoenix, AZ"],
    )
    assert set(written) == {"jsonl", "csv", "coverage", "card", "schema_org"}
    for path in written.values():
        assert path.exists() and path.stat().st_size > 0


# --------------------------------------------------------------------------- #
# negative controls
# --------------------------------------------------------------------------- #


def test_an_extractor_that_refuses_produces_an_empty_dataset_not_a_stale_one(
    tmp_path, phoenix_text, monkeypatch
):
    """Inverse mutation: if the extractor always refuses, nothing may be published.

    A green export here would mean the pipeline is publishing from somewhere other
    than the document it claims to read.
    """
    from openpermitfees.collect import collect_all
    from openpermitfees.extract import phoenix as module

    directory = tmp_path / "jurisdictions"
    directory.mkdir()
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
    monkeypatch.setattr(
        "openpermitfees.collect.fetch",
        lambda url, **kwargs: FetchResult(
            url=url,
            ok=True,
            payload=phoenix_text.encode("utf-8"),
            media_type="text/plain",
            http_status=200,
            retrieved_at=GENERATED_AT,
        ),
    )
    monkeypatch.setattr(module.PhoenixExtractor, "extract", lambda self, context: [])

    collect_all(tmp_path / "data", registry_dir=directory)
    rows = latest_rows(tmp_path / "data")
    assert rows == []
    cover = coverage(rows, generated_from="test")
    assert cover.rows == 0 and cover.by_status == {}


def test_an_export_from_an_empty_archive_is_empty(tmp_path):
    assert latest_rows(tmp_path / "never-collected") == []
    written = write_exports(
        tmp_path / "never-collected",
        tmp_path / "dist",
        generated_at=GENERATED_AT,
        jurisdiction_names=[],
    )
    assert written["jsonl"].read_text(encoding="utf-8") == ""
    assert json.loads(written["coverage"].read_text(encoding="utf-8"))["rows"] == 0
