"""``openpermitfees`` command line.

Exit codes are the interface a timer reads:

* ``0`` — every registered document was fetched and extracted
* ``2`` — at least one document failed (rows still written, marked ``not_fetched``)
* ``3`` — the collector itself could not run (bad registry, missing poppler)

A partial run exiting 0 would let a broken parser sit in public unnoticed, which
is the documented failure mode for published datasets: rot is worse than absence.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from . import extract  # noqa: F401  (registers built-in extractors)
from .archive import Archive
from .collect import Collector
from .diff import diff_extractions
from .export import write_exports
from .models import event_key_of
from .registry import load_registry

DEFAULT_DATA_DIR = Path("data")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--registry-dir", type=Path, default=None)
    parser.add_argument("--jurisdiction", action="append", dest="jurisdictions")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openpermitfees", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="fetch, archive and extract fee schedules")
    _add_common(collect)
    collect.add_argument(
        "--ignore-robots",
        action="store_true",
        help="skip robots.txt (only for a jurisdiction that has told you to)",
    )
    collect.add_argument("--json", action="store_true")

    diff_cmd = sub.add_parser("diff", help="emit change events against the previous observation")
    _add_common(diff_cmd)
    diff_cmd.add_argument("--out", type=Path, default=None)

    export = sub.add_parser("export", help="write dataset files")
    _add_common(export)
    # not "dist/": that is where wheels go, and the published dataset is not a
    # build artefact — it is committed, so a reader can download it without
    # running the collector.
    export.add_argument("--out", type=Path, default=Path("dataset"))

    status = sub.add_parser("status", help="what the archive currently holds")
    _add_common(status)

    return parser


def cmd_collect(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry_dir)
    if not registry:
        print("no jurisdictions registered", file=sys.stderr)
        return 3
    collector = Collector(args.data_dir, respect_robots=not args.ignore_robots)

    failures = 0
    payload = []
    for jurisdiction in registry.values():
        if args.jurisdictions and jurisdiction.id not in args.jurisdictions:
            continue
        for result in collector.collect_jurisdiction(jurisdiction):
            payload.append(result.to_dict())
            if not result.ok:
                failures += 1
                print(f"FAIL {jurisdiction.id} {result.source_url}: {result.reason}", file=sys.stderr)
            else:
                published = sum(1 for item in result.items if item.status == "published")
                changed = {None: "first observation", True: "CHANGED", False: "unchanged"}[
                    result.changed_bytes
                ]
                print(
                    f"ok   {jurisdiction.id} {published}/{len(result.items)} published "
                    f"({changed}, sha {result.document.sha256[:12]})"
                )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 2 if failures else 0


def cmd_diff(args: argparse.Namespace) -> int:
    collector = Collector(args.data_dir)
    archive = Archive(Path(args.data_dir) / "archive")
    observed_at = _now()
    events = []
    for jurisdiction in load_registry(args.registry_dir).values():
        if args.jurisdictions and jurisdiction.id not in args.jurisdictions:
            continue
        for document in jurisdiction.documents:
            url = document["url"]
            latest = archive.latest(jurisdiction.id, url)
            if latest is None:
                continue
            current = collector.read_extraction(jurisdiction.id, latest["sha256"])
            if current is None:
                continue
            previous_observation = archive.previous_distinct(jurisdiction.id, url)
            previous = (
                collector.read_extraction(jurisdiction.id, previous_observation["sha256"])
                if previous_observation
                else None
            )
            events.extend(diff_extractions(previous, current, observed_at=observed_at))

    if not args.out:
        # stdout is a query: show the full diff of the archive as it stands.
        sys.stdout.write(
            "".join(json.dumps(event.to_dict(), sort_keys=True) + "\n" for event in events)
        )
        return 0

    # --out is an append-only FEED, and a feed is read as "these things happened".
    # The diff is recomputed from the whole archive on every run, so without this
    # a daily timer would re-append the same `first_observed` rows every day and
    # the feed would report ten changes a day that never happened. An event is
    # identified by the document pair it describes, not by the run that found it.
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    already = _recorded_event_keys(out)
    fresh = [event for event in events if event.event_key not in already]

    if fresh:
        with out.open("a", encoding="utf-8") as handle:
            handle.write(
                "".join(json.dumps(event.to_dict(), sort_keys=True) + "\n" for event in fresh)
            )
    print(
        f"{len(fresh)} new change events -> {args.out} "
        f"({len(events) - len(fresh)} already recorded)"
    )
    return 0


def _recorded_event_keys(path: Path) -> set[str]:
    """Keys already in the feed. A corrupt line is skipped, never treated as absent.

    Reading a damaged feed as empty would re-append the entire history, so an
    unparseable line raises rather than silently licensing a duplicate flood.
    """
    if not path.exists():
        return set()
    keys: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                keys.add(event_key_of(json.loads(line)))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{number}: change feed is not readable ({exc}). "
                                 "Refusing to append — fix or move the file first.")
    return keys


def cmd_export(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry_dir)
    written = write_exports(
        args.data_dir,
        args.out,
        generated_at=_now(),
        jurisdiction_names=[j.name for j in registry.values()],
    )
    for kind, path in written.items():
        print(f"{kind:10} {path}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    archive = Archive(Path(args.data_dir) / "archive")
    rows = list(archive.observations())
    registry = load_registry(args.registry_dir)
    print(f"registered jurisdictions : {len(registry)}")
    print(f"archived observations    : {len(rows)}")
    print(f"distinct documents       : {len({row['sha256'] for row in rows})}")
    for jurisdiction in registry.values():
        for document in jurisdiction.documents:
            latest = archive.latest(jurisdiction.id, document["url"])
            seen = sum(
                1
                for row in rows
                if row["jurisdiction_id"] == jurisdiction.id
                and row["source_url"] == document["url"]
            )
            state = (
                f"{latest['sha256'][:12]} retrieved {latest['retrieved_at']} ({seen} observations)"
                if latest
                else "never fetched"
            )
            print(f"  {jurisdiction.id:16} {state}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "collect": cmd_collect,
        "diff": cmd_diff,
        "export": cmd_export,
        "status": cmd_status,
    }
    return handlers[args.command](args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
