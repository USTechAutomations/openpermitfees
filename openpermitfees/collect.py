"""fetch → archive → extract, one jurisdiction document at a time.

The pipeline's contract: **every registered jurisdiction produces rows on every
run, including the ones that failed.** A fetch failure becomes a ``not_fetched``
row carrying the reason; an extractor that finds nothing produces
``not_found_in_document``. A jurisdiction is never silently absent, because a
missing jurisdiction reads to a user as "no fees here" rather than "we broke".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .archive import Archive
from .extract import base as extractors
from .extract.pdftext import ExtractionUnavailable, lines_from_text, pdf_to_lines
from .fetch import RobotsCache, fetch
from .models import FeeDocument, FeeItem, SCHEMA_VERSION
from .registry import Jurisdiction, load_registry

EXTRACTED_DIRNAME = "extracted"


@dataclass
class CollectionResult:
    jurisdiction_id: str
    source_url: str
    ok: bool
    document: Optional[FeeDocument] = None
    items: list[FeeItem] = field(default_factory=list)
    reason: Optional[str] = None
    changed_bytes: Optional[bool] = None  # None = no prior observation

    def to_dict(self) -> dict[str, Any]:
        return {
            "jurisdiction_id": self.jurisdiction_id,
            "source_url": self.source_url,
            "ok": self.ok,
            "reason": self.reason,
            "changed_bytes": self.changed_bytes,
            "document_sha256": self.document.sha256 if self.document else None,
            "item_count": len(self.items),
        }


class Collector:
    def __init__(
        self,
        data_dir: Path,
        *,
        respect_robots: bool = True,
        robots: Optional[RobotsCache] = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.archive = Archive(self.data_dir / "archive")
        self.respect_robots = respect_robots
        self.robots = robots or RobotsCache()

    # ------------------------------------------------------------------ #

    def collect_jurisdiction(self, jurisdiction: Jurisdiction) -> list[CollectionResult]:
        return [
            self.collect_document(jurisdiction, document)
            for document in jurisdiction.documents
        ]

    def collect_document(
        self, jurisdiction: Jurisdiction, document_spec: dict[str, Any]
    ) -> CollectionResult:
        url = document_spec["url"]
        previous = self.archive.latest(jurisdiction.id, url)

        result = fetch(url, robots=self.robots, respect_robots=self.respect_robots)
        if not result.ok:
            return CollectionResult(
                jurisdiction_id=jurisdiction.id,
                source_url=url,
                ok=False,
                reason=result.reason,
                items=[self._not_fetched_row(jurisdiction, url, result.reason or "unknown")],
            )

        stored = self.archive.store(
            jurisdiction_id=jurisdiction.id,
            url=url,
            payload=result.payload or b"",
            media_type=result.media_type or document_spec.get("media_type", ""),
            retrieved_at=result.retrieved_at,
            http_status=result.http_status or 0,
        )
        changed = None if previous is None else previous["sha256"] != stored.sha256

        try:
            items = self.extract(jurisdiction, stored, result.payload or b"")
        except ExtractionUnavailable as exc:
            return CollectionResult(
                jurisdiction_id=jurisdiction.id,
                source_url=url,
                ok=False,
                document=stored,
                reason=f"extraction unavailable: {exc}",
                changed_bytes=changed,
                items=[self._not_fetched_row(jurisdiction, url, f"extraction unavailable: {exc}")],
            )

        self.write_extraction(stored, items)
        return CollectionResult(
            jurisdiction_id=jurisdiction.id,
            source_url=url,
            ok=True,
            document=stored,
            items=items,
            changed_bytes=changed,
        )

    # ------------------------------------------------------------------ #

    def extract(
        self, jurisdiction: Jurisdiction, document: FeeDocument, payload: bytes
    ) -> list[FeeItem]:
        extractor = extractors.get(jurisdiction.extractor or jurisdiction.id)
        if extractor is None:
            return [
                self._not_fetched_row(
                    jurisdiction,
                    document.source_url,
                    "no extractor registered for this jurisdiction",
                )
            ]

        if document.media_type == "application/pdf" or document.archive_path.endswith(".pdf"):
            lines = pdf_to_lines(payload)
        else:
            lines = lines_from_text(payload.decode("utf-8", errors="replace"))

        context = extractors.DocumentContext(document=document, lines=lines)
        facts = extractor.document_facts(context)
        for key, value in facts.items():
            if hasattr(document, key) and getattr(document, key) is None:
                setattr(document, key, value)
        return list(extractor.extract(context))

    # ------------------------------------------------------------------ #

    def _not_fetched_row(
        self, jurisdiction: Jurisdiction, url: str, reason: str
    ) -> FeeItem:
        return FeeItem(
            jurisdiction_id=jurisdiction.id,
            state=jurisdiction.state,
            permit_type="unknown",
            item_id=f"{jurisdiction.id}/unavailable",
            label=f"{jurisdiction.name} fee schedule",
            basis="reference",
            status="not_fetched",
            unavailable_reason=f"{reason} ({url})",
        )

    def extraction_path(self, document: FeeDocument) -> Path:
        return (
            self.data_dir
            / EXTRACTED_DIRNAME
            / document.jurisdiction_id
            / f"{document.sha256}.json"
        )

    def write_extraction(self, document: FeeDocument, items: list[FeeItem]) -> Path:
        path = self.extraction_path(document)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "document": document.to_dict(),
                    "items": [item.to_dict() for item in items],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return path

    def read_extraction(self, jurisdiction_id: str, sha256: str) -> Optional[dict]:
        path = self.data_dir / EXTRACTED_DIRNAME / jurisdiction_id / f"{sha256}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


def collect_all(
    data_dir: Path,
    *,
    registry_dir: Optional[Path] = None,
    only: Optional[list[str]] = None,
    respect_robots: bool = True,
) -> list[CollectionResult]:
    collector = Collector(data_dir, respect_robots=respect_robots)
    results: list[CollectionResult] = []
    for jurisdiction in load_registry(registry_dir).values():
        if only and jurisdiction.id not in only:
            continue
        results.extend(collector.collect_jurisdiction(jurisdiction))
    return results


__all__ = ["CollectionResult", "Collector", "collect_all"]
