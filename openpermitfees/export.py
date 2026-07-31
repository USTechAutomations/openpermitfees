"""Dataset export: JSONL, CSV, coverage report, dataset card, schema.org markup.

The export deliberately publishes its own holes. ``coverage`` counts rows by
status, so a reader sees "3 published, 2 not found, 1 not fetched" rather than a
tidy table that hides the two-thirds we could not source. A dataset that only
shows its wins cannot be trusted on the wins.

Every exported row carries its provenance inline (source URL, document digest,
retrieval timestamp, adopting instrument, effective date, page/line). That is the
property this dataset is actually differentiated on — anyone can copy a number,
nobody can copy a citation they never collected.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import SCHEMA_VERSION

DATASET_NAME = "Open Permit Fees"
DATASET_SLUG = "open-permit-fees"
# The dataset's home is the repository, because that is the URL that resolves
# today and holds every version. Citing a page we have not built yet would put
# a 404 in the one place a reader goes to check us.
DATASET_URL = "https://github.com/USTechAutomations/openpermitfees"
DOWNLOAD_URL = (
    "https://raw.githubusercontent.com/USTechAutomations/openpermitfees"
    f"/main/dataset/{DATASET_SLUG}.jsonl"
)
PUBLISHER_NAME = "US Tech Automations"
PUBLISHER_URL = "https://ustechautomations.com/permits"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
LICENSE_NAME = "CC BY 4.0"

CSV_COLUMNS = [
    "item_id",
    "jurisdiction_id",
    "state",
    "permit_type",
    "label",
    "basis",
    "status",
    "amount_usd",
    "minimum_usd",
    "unit",
    "conditions",
    "unavailable_reason",
    "source_url",
    "document_sha256",
    "retrieved_at",
    "effective_date",
    "adopting_instrument",
    "page",
    "line",
    "matched_text",
]


@dataclass
class Coverage:
    jurisdictions: int
    rows: int
    by_status: dict[str, int]
    by_basis: dict[str, int]
    with_effective_date: int
    generated_from: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "jurisdictions": self.jurisdictions,
            "rows": self.rows,
            "by_status": self.by_status,
            "by_basis": self.by_basis,
            "rows_with_effective_date": self.with_effective_date,
            "generated_from": self.generated_from,
        }


def latest_rows(data_dir: Path) -> list[dict[str, Any]]:
    """Newest extraction per (jurisdiction, source_url), flattened to rows."""
    from .archive import Archive

    archive = Archive(Path(data_dir) / "archive")
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for observation in archive.observations():
        seen[(observation["jurisdiction_id"], observation["source_url"])] = observation

    rows: list[dict[str, Any]] = []
    for (jurisdiction_id, _), observation in sorted(seen.items()):
        path = (
            Path(data_dir)
            / "extracted"
            / jurisdiction_id
            / f"{observation['sha256']}.json"
        )
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.extend(payload.get("items", []))
    return rows


def flatten(row: dict[str, Any]) -> dict[str, Any]:
    provenance = row.get("provenance") or {}
    flat = {column: None for column in CSV_COLUMNS}
    for key in (
        "item_id",
        "jurisdiction_id",
        "state",
        "permit_type",
        "label",
        "basis",
        "status",
        "amount_usd",
        "minimum_usd",
        "unit",
        "conditions",
        "unavailable_reason",
    ):
        flat[key] = row.get(key)
    for key in (
        "source_url",
        "document_sha256",
        "retrieved_at",
        "effective_date",
        "adopting_instrument",
        "page",
        "line",
        "matched_text",
    ):
        flat[key] = provenance.get(key)
    if flat["matched_text"]:
        flat["matched_text"] = " ".join(str(flat["matched_text"]).split())
    return flat


def to_jsonl(rows: Iterable[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def to_csv(rows: Iterable[dict[str, Any]]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(flatten(row))
    return buffer.getvalue()


def coverage(rows: list[dict[str, Any]], *, generated_from: str) -> Coverage:
    return Coverage(
        jurisdictions=len({row["jurisdiction_id"] for row in rows}),
        rows=len(rows),
        by_status=dict(sorted(Counter(row["status"] for row in rows).items())),
        by_basis=dict(sorted(Counter(row["basis"] for row in rows).items())),
        with_effective_date=sum(
            1 for row in rows if (row.get("provenance") or {}).get("effective_date")
        ),
        generated_from=generated_from,
    )


def schema_org_dataset(
    rows: list[dict[str, Any]], *, generated_at: str, download_url: Optional[str] = DOWNLOAD_URL
) -> dict[str, Any]:
    """schema.org/Dataset markup — what Google Dataset Search reads."""
    states = sorted({row["state"] for row in rows if row.get("state")})
    payload: dict[str, Any] = {
        "@context": "https://schema.org/",
        "@type": "Dataset",
        "name": DATASET_NAME,
        "description": (
            "Machine-readable US building-permit fee schedules. Every fee carries the "
            "source document URL, its sha256 digest, the retrieval timestamp, the adopting "
            "ordinance and the effective date, plus the page and line it was read from. "
            "Fees that a jurisdiction does not publish are recorded as such rather than "
            "estimated."
        ),
        "url": DATASET_URL,
        "license": LICENSE_URL,
        "version": SCHEMA_VERSION,
        "dateModified": generated_at,
        "isAccessibleForFree": True,
        "creator": {
            "@type": "Organization",
            "name": PUBLISHER_NAME,
            "url": PUBLISHER_URL,
        },
        "creativeWorkStatus": "Incremental",
        "keywords": [
            "building permit fees",
            "permit fee schedule",
            "municipal fees",
            "construction permitting",
            "solar permit fees",
        ],
        "spatialCoverage": [
            {"@type": "Place", "name": state} for state in states
        ],
        "variableMeasured": [
            {"@type": "PropertyValue", "name": name}
            for name in ("amount_usd", "basis", "status", "effective_date", "tiers")
        ],
    }
    if download_url:
        payload["distribution"] = [
            {
                "@type": "DataDownload",
                "encodingFormat": "application/x-ndjson",
                "contentUrl": download_url,
            }
        ]
    return payload


def dataset_card(cover: Coverage, *, generated_at: str, jurisdictions: list[str]) -> str:
    status_lines = "\n".join(
        f"| `{status}` | {count} |" for status, count in cover.by_status.items()
    )
    return f"""# {DATASET_NAME}

Machine-readable US building-permit fee schedules, cited to the document that
adopted them.

*Generated {generated_at} · schema `{SCHEMA_VERSION}` · license {LICENSE_NAME}*

## What is in it

One row per fee line item. Every row that carries a number also carries:

- `source_url` — the jurisdiction's own fee-schedule document
- `document_sha256` — digest of the exact bytes the number was read from
- `retrieved_at` — when we fetched those bytes
- `effective_date` / `adopting_instrument` — when the fee took effect and under
  which ordinance or resolution
- `page` / `line` / `matched_text` — the verbatim line, so a reader can re-check
  it in seconds

## What is deliberately not in it

There is **no "typical fee" column**. Most building permit fees are tiered on
project valuation, and flattening a tier table into one number invents a fee no
jurisdiction adopted. Rows carry the structure the jurisdiction actually
published: `flat`, `option`, `valuation_tiered`, `per_unit`, `percent_of` or
`reference`.

Fees we could not source are published as rows too, with a reason:

| status | rows |
|---|---|
{status_lines}

`not_found_in_document` means we read the document and the fee is not in it —
which is itself the answer for permit types a city prices on valuation instead.
`not_fetched` means we could not retrieve the document, and no number is offered.

## Coverage

- Jurisdictions: **{cover.jurisdictions}** ({", ".join(jurisdictions)})
- Rows: **{cover.rows}**
- Rows with an effective date: **{cover.with_effective_date}**

Coverage is small and deliberately so: each jurisdiction is parsed by a
purpose-written extractor and checked against the source document, rather than
scraped generically. Breadth without provenance is the thing this dataset exists
to replace.

## Change feed

The archive keeps every observed version of every fee-schedule document, so fee
changes are dated against the day we observed them. The first sighting of a row
is recorded as `first_observed` and is **not** reported as a change — the feed
never dates a fee to the day we started collecting.

## Citation

> {DATASET_NAME} ({generated_at[:4]}). {PUBLISHER_NAME}. {DATASET_URL}

## Reproducing it

```bash
pip install openpermitfees   # requires poppler-utils for pdftotext
openpermitfees collect       # fetch + archive + extract
openpermitfees export        # jsonl, csv, coverage, card, schema.org markup
```
"""


def write_exports(
    data_dir: Path, out_dir: Path, *, generated_at: str, jurisdiction_names: list[str]
) -> dict[str, Path]:
    rows = latest_rows(data_dir)
    cover = coverage(rows, generated_from=str(data_dir))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = {
        "jsonl": out_dir / f"{DATASET_SLUG}.jsonl",
        "csv": out_dir / f"{DATASET_SLUG}.csv",
        "coverage": out_dir / "coverage.json",
        "card": out_dir / "DATASET_CARD.md",
        "schema_org": out_dir / "dataset.jsonld",
    }
    written["jsonl"].write_text(to_jsonl(rows), encoding="utf-8")
    written["csv"].write_text(to_csv(rows), encoding="utf-8")
    written["coverage"].write_text(
        json.dumps(cover.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
    written["card"].write_text(
        dataset_card(cover, generated_at=generated_at, jurisdictions=jurisdiction_names),
        encoding="utf-8",
    )
    written["schema_org"].write_text(
        json.dumps(
            schema_org_dataset(rows, generated_at=generated_at), indent=2, sort_keys=True
        ),
        encoding="utf-8",
    )
    return written


__all__ = [
    "CSV_COLUMNS",
    "Coverage",
    "DATASET_NAME",
    "DATASET_SLUG",
    "DATASET_URL",
    "coverage",
    "dataset_card",
    "flatten",
    "latest_rows",
    "schema_org_dataset",
    "to_csv",
    "to_jsonl",
    "write_exports",
]
