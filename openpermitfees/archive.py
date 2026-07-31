"""Content-addressed archive of retrieved fee-schedule documents.

The archive is the asset. Jurisdictions overwrite their fee schedules in place —
last year's PDF usually stops existing at its URL — so a dated local copy plus the
manifest of when we saw it is the only way an "as of" answer is possible later.

Two properties the rest of the package depends on:

* **Append-only manifest.** Every retrieval writes a row, including retrievals of
  bytes we already hold. A repeated sha256 is the evidence that the document did
  *not* change; dropping it would make "unchanged for 9 reads" unprovable.
* **Bytes are never rewritten.** Files are named by their own digest, so a second
  write of the same content is a no-op and a different document can never
  overwrite an earlier one.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from .models import FeeDocument

MANIFEST_NAME = "manifest.jsonl"

_EXTENSIONS = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "text/plain": ".txt",
    "application/json": ".json",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def extension_for(media_type: str, url: str) -> str:
    base = (media_type or "").split(";", 1)[0].strip().lower()
    if base in _EXTENSIONS:
        return _EXTENSIONS[base]
    suffix = Path(url.split("?", 1)[0]).suffix.lower()
    return suffix if suffix in set(_EXTENSIONS.values()) else ".bin"


@dataclass
class Archive:
    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root).expanduser()

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    def path_for(self, jurisdiction_id: str, digest: str, media_type: str, url: str) -> Path:
        return self.root / jurisdiction_id / f"{digest}{extension_for(media_type, url)}"

    def store(
        self,
        *,
        jurisdiction_id: str,
        url: str,
        payload: bytes,
        media_type: str,
        retrieved_at: str,
        http_status: int,
        title: Optional[str] = None,
    ) -> FeeDocument:
        """Write bytes (if new) and always append a manifest observation."""
        digest = sha256_bytes(payload)
        target = self.path_for(jurisdiction_id, digest, media_type, url)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            tmp = target.with_suffix(target.suffix + ".part")
            tmp.write_bytes(payload)
            os.replace(tmp, target)

        document = FeeDocument(
            jurisdiction_id=jurisdiction_id,
            source_url=url,
            sha256=digest,
            retrieved_at=retrieved_at,
            media_type=media_type,
            byte_length=len(payload),
            archive_path=str(target.relative_to(self.root)),
            http_status=http_status,
            title=title,
        )
        self.append_observation(document)
        return document

    def append_observation(self, document: FeeDocument) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(document.to_dict(), sort_keys=True) + "\n")

    def observations(self, jurisdiction_id: Optional[str] = None) -> Iterator[dict]:
        if not self.manifest_path.exists():
            return
        with self.manifest_path.open(encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                row = json.loads(raw)
                if jurisdiction_id is None or row.get("jurisdiction_id") == jurisdiction_id:
                    yield row

    def latest(self, jurisdiction_id: str, source_url: Optional[str] = None) -> Optional[dict]:
        rows = [
            r
            for r in self.observations(jurisdiction_id)
            if source_url is None or r.get("source_url") == source_url
        ]
        return rows[-1] if rows else None

    def previous_distinct(self, jurisdiction_id: str, source_url: str) -> Optional[dict]:
        """The most recent observation whose bytes differ from the newest one."""
        rows = [r for r in self.observations(jurisdiction_id) if r.get("source_url") == source_url]
        if not rows:
            return None
        newest = rows[-1]["sha256"]
        for row in reversed(rows[:-1]):
            if row["sha256"] != newest:
                return row
        return None

    def read(self, archive_path: str) -> bytes:
        return (self.root / archive_path).read_bytes()


__all__ = ["Archive", "MANIFEST_NAME", "extension_for", "sha256_bytes"]
