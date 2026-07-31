# Open Permit Fees

Machine-readable US building-permit fee schedules, cited to the document that
adopted them.

*Generated 2026-07-31T17:23:53+00:00 · schema `1.0.0` · license CC BY 4.0*

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
| `not_found_in_document` | 2 |
| `published` | 8 |

`not_found_in_document` means we read the document and the fee is not in it —
which is itself the answer for permit types a city prices on valuation instead.
`not_fetched` means we could not retrieve the document, and no number is offered.

## Coverage

- Jurisdictions: **1** (Phoenix, AZ)
- Rows: **10**
- Rows with an effective date: **8**

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

> Open Permit Fees (2026). US Tech Automations. https://github.com/USTechAutomations/openpermitfees

## Reproducing it

```bash
pip install openpermitfees   # requires poppler-utils for pdftotext
openpermitfees collect       # fetch + archive + extract
openpermitfees export        # jsonl, csv, coverage, card, schema.org markup
```
