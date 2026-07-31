"""The jurisdiction registry: which documents we watch, and who parses them.

One JSON file per jurisdiction, shipped inside the package so an installed wheel
finds the same registry a source checkout does. Keeping the list out of code
means a jurisdiction can be added, or a moved fee-schedule URL corrected, without
touching the collector — the failure mode we design against is a broken parser
sitting in public for a week, and a data-only fix is the fastest repair.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

DEFAULT_REGISTRY_DIR = Path(__file__).resolve().parent / "jurisdictions"


@dataclass(frozen=True)
class Jurisdiction:
    id: str
    name: str
    state: str
    documents: tuple[dict[str, Any], ...]
    extractor: Optional[str] = None
    permit_office_url: Optional[str] = None
    notes: Optional[str] = None
    population: Optional[int] = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def document_urls(self) -> tuple[str, ...]:
        return tuple(doc["url"] for doc in self.documents)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Jurisdiction":
        missing = [k for k in ("id", "name", "state", "documents") if k not in payload]
        if missing:
            raise ValueError(f"jurisdiction file missing {missing}")
        return cls(
            id=payload["id"],
            name=payload["name"],
            state=payload["state"],
            documents=tuple(payload["documents"]),
            extractor=payload.get("extractor"),
            permit_office_url=payload.get("permit_office_url"),
            notes=payload.get("notes"),
            population=payload.get("population"),
            tags=tuple(payload.get("tags", ())),
        )


def load_registry(directory: Optional[Path] = None) -> dict[str, Jurisdiction]:
    directory = Path(directory or DEFAULT_REGISTRY_DIR)
    out: dict[str, Jurisdiction] = {}
    for path in sorted(directory.glob("*.json")):
        jurisdiction = Jurisdiction.from_dict(json.loads(path.read_text(encoding="utf-8")))
        out[jurisdiction.id] = jurisdiction
    return out


def iter_registry(directory: Optional[Path] = None) -> Iterator[Jurisdiction]:
    yield from load_registry(directory).values()


__all__ = ["DEFAULT_REGISTRY_DIR", "Jurisdiction", "iter_registry", "load_registry"]
