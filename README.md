# Open Permit Fees

Machine-readable US building-permit fee schedules, cited to the document that
adopted them.

Every number in the output carries the jurisdiction's own source URL, the sha256
of the exact bytes it was read from, the retrieval timestamp, the adopting
ordinance, the effective date, and the page and line it appears on. Fees a
jurisdiction does not publish are recorded as unpublished, not estimated.

```json
{
  "item_id": "phoenix-az/residential_solar_pv/fixed_option_c",
  "jurisdiction_id": "phoenix-az",
  "permit_type": "residential_solar_pv",
  "label": "Residential solar PV fixed fee — Option C (No Plan Review)",
  "basis": "option",
  "status": "published",
  "amount_usd": 488.0,
  "currency": "USD",
  "provenance": {
    "source_url": "https://www.phoenix.gov/content/dam/phoenix/pddsite/documents/impact-fees/fee-schedule.pdf",
    "document_sha256": "4193e742000369ae3b6814e56c7eb2563cf18075240aeb894f335d684ff9436d",
    "retrieved_at": "2026-07-31T16:50:48+00:00",
    "document_title": "City of Phoenix PDD Fee Schedule",
    "adopting_instrument": "Ordinance G-7465",
    "code_reference": "Phoenix City Code, Chapter 9, Appendix A.2",
    "approved_date": "2025-12-17",
    "effective_date": "2026-01-20",
    "page": 42,
    "line": 23,
    "matched_text": "3)   Option C – No Plan Review …………………                 $488 Administrative Fee and 2-\n                                                                    inspections"
  }
}
```

## Why this exists

Permit-fee numbers on the open web are mostly uncited. They get copied between
directories, blog posts and AI answers until a plausible round number — "$150 for
a residential mechanical permit" — has no adopting authority anywhere behind it.

Two things follow from actually reading the documents:

**Most permit fees are not a number.** Phoenix prices building work from a
valuation table: a piecewise base fee plus a marginal rate per $1,000 of project
valuation, "or fraction thereof". There is no flat residential mechanical or
electrical permit fee to quote. This dataset publishes the structure the
jurisdiction adopted — `flat`, `option`, `valuation_tiered`, `per_unit`,
`percent_of`, `reference` — and there is deliberately **no "typical fee" column**.

**The absence is the answer.** A row saying "Phoenix publishes no flat fee for
this permit type; it is priced from Table A" is more useful, and more honest,
than a fabricated figure. Those rows ship with the dataset.

## Download the dataset

The [current dataset release](https://github.com/USTechAutomations/openpermitfees/releases/tag/v0.1.0)
provides direct CSV and JSONL downloads, a machine-readable coverage report,
the dataset card, and schema.org metadata. You do not need Python or a clone of
this repository to inspect the cited fee records.

## Install

Straight from this repository (the package is not yet published to PyPI):

```bash
pip install git+https://github.com/USTechAutomations/openpermitfees.git
```

Extraction shells out to `pdftotext` (poppler), because fee schedules are tables
whose meaning lives in their column geometry:

```bash
sudo apt install poppler-utils     # Debian/Ubuntu
brew install poppler               # macOS
```

The library itself has **no Python dependencies**. A dependency that stops
building is the same outage as a parser that breaks, and this package's promise
is that its output does not silently rot.

## Use

```bash
openpermitfees collect     # fetch → archive → extract
openpermitfees export      # jsonl, csv, coverage.json, dataset card, schema.org
openpermitfees diff        # change events against the previous archived version
openpermitfees status      # what the archive holds
```

Exit codes are the interface a scheduler reads: `0` everything collected, `2` at
least one document failed (its rows are still written, marked `not_fetched`), `3`
the collector could not run at all.

As a library:

```python
from openpermitfees import FeeItem
from openpermitfees.calculate import fee_for_valuation

rows = [FeeItem.from_dict(json.loads(line)) for line in open("dataset/open-permit-fees.jsonl")]
table = next(r for r in rows if r.item_id == "phoenix-az/building_permit/valuation_table_a")

fee_for_valuation(table.tiers, 250_500)   # -> 2512.0
```

`FeeItem.from_dict` re-runs every invariant on read, so a hand-edited export
cannot smuggle in a number its citation does not contain. The dataset's promise
is checkable by its consumers, not only by its producer.

## What the schema guarantees

1. **A number carries its citation or it does not exist.** `FeeItem` refuses to
   construct with an `amount_usd` unless a `Provenance` accompanies it *and* the
   quoted `matched_text` from the source document actually contains that amount.
   A parser that drifts onto the wrong line raises instead of publishing.
2. **UNKNOWN is a value, not a blank.** `not_fetched`, `not_found_in_document`
   and `not_published_by_jurisdiction` are three different states and never
   collapse into each other, or into a missing row.
3. **The first sighting of a fee is never a change.** The change feed emits
   `first_observed` at a row's t0. Dating a fee to the day we started collecting
   would be a claim about us, not about the fee.

`SCHEMA_VERSION` is `1.0.0` and frozen: consumers cache field names, and schema
churn evicts a dataset from the configs it took months to get into. Additive
changes bump the minor; renames and removals do not happen inside a major.

## The archive is the point

Jurisdictions overwrite their fee schedules in place — last year's PDF usually
stops existing at its URL. `data/archive/` keeps every observed version,
content-addressed, with an append-only manifest that records every retrieval
*including* the ones that found nothing new (a repeated digest is the evidence
that the document did not change).

That is what makes "what did this city charge in March, and when did it change?"
answerable at all, and it is only answerable for the window actually observed.
This archive starts 2026-07-31.

## Coverage

Small and deliberately so. Each jurisdiction gets a purpose-written extractor
checked against the source document — including, where the document prints one,
its own worked fee calculation as a ground-truth oracle. Phoenix prints a
$250,500 example totalling $2,512; the test suite recomputes it from the
extracted tiers.

Generic "find the dollar signs" scraping is how a residential mechanical permit
ends up priced at a sign-inspection fee. Ten jurisdictions parsed impeccably beat
a hundred parsed statistically: one wrong published number costs more credibility
than ninety missing ones.

See `dataset/coverage.json` for the current counts by status, and
`dataset/DATASET_CARD.md` for the generated card.

## Adding a jurisdiction

1. Add `openpermitfees/jurisdictions/<id>.json` with the fee-schedule document
   URL and where you found it.
2. Write an extractor in `openpermitfees/extract/<id>.py` that returns `FeeItem`s
   quoting the lines it read, and `not_found_in_document` rows for fees the
   document does not contain.
3. Add a fixture of the document's `pdftotext -layout` output and tests pinning
   the exact amounts, page and line numbers — plus the document's worked example
   if it prints one.

Extractors must never infer, average, or regionally estimate a number. The schema
will refuse it anyway.

## Commission a jurisdiction

If you need a jurisdiction this dataset doesn't cover yet — you run permit
expediting, cost estimation, or a construction-software product and want
citation-grade fee data for a specific city — we build it for you as a
commissioned extraction. US Tech Automations (the company behind this project)
writes the purpose-built extractor, extracts the full fee schedule with every
row cited to page and line of the adopting document, and delivers it as a pull
request to this public repository within ten business days. The work is
priced at $249 per jurisdiction, one-time; this is our service fee, not a
government charge. The result lands under the same CC BY 4.0 dataset license
as everything else here — the paid path funds the free one, and every
commissioned jurisdiction becomes permanently citable by anyone.

To commission one, [open a structured commission request](https://github.com/USTechAutomations/openpermitfees/issues/new?template=commission-request.yml) — US Tech Automations replies in the issue the same working day. Related paid data services live at
[ustechautomations.com/permits/offers](https://ustechautomations.com/permits/offers).

The same Open Permit Fees $249 commissioned-jurisdiction offer is also available
as a [machine-readable offer contract](offer.json).

## Contributing corrections

If a number here disagrees with the document, that is a bug and the citation is
enough to prove it: every row names the page and line to re-read. Open an issue
with the `item_id` and what the document says.

## Licensing

- **Code** — Apache License 2.0 (`LICENSE`).
- **Dataset** — Creative Commons Attribution 4.0 International (CC BY 4.0).
  Cite as: *Open Permit Fees (2026). US Tech Automations.
  https://github.com/USTechAutomations/openpermitfees*
- **Underlying fee schedules** — public records of the jurisdictions named in each
  record's `source_url`. This project archives and cites them; it claims no
  ownership of them.

## Collection etiquette

The collector identifies itself with a contact URL, obeys `robots.txt`, and fails
**closed** on ambiguity: per RFC 9309 a 4xx robots response means "no rules,
crawling allowed", while a 5xx means "unavailable, treat as disallowed". It
retries server errors, never retries a 404, and fetches one document per
jurisdiction per run.

If you run a permitting department and want this collector to stop, or to point
at a better URL, open an issue — a corrected registry entry is a one-line fix.
