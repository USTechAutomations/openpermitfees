"""The archive: bytes are never rewritten, and every look is recorded.

"Unchanged for nine reads" is only provable if the nine reads were written down.
The manifest is therefore append-only including duplicates, and files are named
by their own digest so one document can never overwrite another.
"""

from __future__ import annotations

from openpermitfees.archive import Archive, extension_for, sha256_bytes

URL = "https://example.gov/fees.pdf"


def store(archive: Archive, payload: bytes, retrieved_at: str) -> None:
    return archive.store(
        jurisdiction_id="phoenix-az",
        url=URL,
        payload=payload,
        media_type="application/pdf",
        retrieved_at=retrieved_at,
        http_status=200,
    )


def test_repeated_identical_retrievals_are_recorded_but_stored_once(tmp_path):
    archive = Archive(tmp_path)
    store(archive, b"%PDF-1", "2026-07-01T00:00:00+00:00")
    store(archive, b"%PDF-1", "2026-07-02T00:00:00+00:00")
    store(archive, b"%PDF-1", "2026-07-03T00:00:00+00:00")

    observations = list(archive.observations("phoenix-az"))
    assert len(observations) == 3, "a repeated digest is the evidence of no change"
    assert len({o["sha256"] for o in observations}) == 1
    stored_files = list((tmp_path / "phoenix-az").iterdir())
    assert len(stored_files) == 1


def test_a_new_version_never_overwrites_the_old_bytes(tmp_path):
    archive = Archive(tmp_path)
    store(archive, b"%PDF-old", "2026-07-01T00:00:00+00:00")
    store(archive, b"%PDF-new", "2026-08-01T00:00:00+00:00")

    assert archive.read(f"phoenix-az/{sha256_bytes(b'%PDF-old')}.pdf") == b"%PDF-old"
    assert archive.read(f"phoenix-az/{sha256_bytes(b'%PDF-new')}.pdf") == b"%PDF-new"
    assert archive.latest("phoenix-az", URL)["sha256"] == sha256_bytes(b"%PDF-new")


def test_previous_distinct_skips_repeat_sightings_of_the_current_bytes(tmp_path):
    archive = Archive(tmp_path)
    store(archive, b"%PDF-old", "2026-07-01T00:00:00+00:00")
    store(archive, b"%PDF-new", "2026-08-01T00:00:00+00:00")
    store(archive, b"%PDF-new", "2026-08-02T00:00:00+00:00")
    store(archive, b"%PDF-new", "2026-08-03T00:00:00+00:00")

    previous = archive.previous_distinct("phoenix-az", URL)
    assert previous["sha256"] == sha256_bytes(b"%PDF-old"), "diffed against itself"


def test_no_predecessor_when_only_one_version_was_ever_seen(tmp_path):
    archive = Archive(tmp_path)
    store(archive, b"%PDF-1", "2026-07-01T00:00:00+00:00")
    store(archive, b"%PDF-1", "2026-07-02T00:00:00+00:00")
    assert archive.previous_distinct("phoenix-az", URL) is None


def test_an_empty_archive_reports_nothing_rather_than_failing(tmp_path):
    archive = Archive(tmp_path / "does-not-exist")
    assert list(archive.observations()) == []
    assert archive.latest("phoenix-az") is None


def test_extension_falls_back_to_the_url_then_to_bin():
    assert extension_for("application/pdf", "https://x/fees") == ".pdf"
    assert extension_for("", "https://x/fees.pdf?v=2") == ".pdf"
    assert extension_for("application/octet-stream", "https://x/fees") == ".bin"
