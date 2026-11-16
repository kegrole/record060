"""Command-line entry point for the timeline merger."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from .events import load_events, load_source_delays, parse_duration
from .late import merge_events
from .report import build_report, write_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m timelinemerge.cli",
        description=(
            "Merge out-of-order events from multiple sources using per-source "
            "watermarks and an allowed-lateness window."
        ),
    )
    parser.add_argument(
        "--events",
        required=True,
        type=Path,
        help="Path to the JSONL event file (may include a config line).",
    )
    parser.add_argument(
        "--allowed-lateness",
        required=True,
        help="Allowed lateness window, e.g. 5s, 500ms, 2m or 1h.",
    )
    parser.add_argument(
        "--sources",
        type=Path,
        default=None,
        help="Optional JSON file mapping source names to delays.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional path for the full JSON report.",
    )
    return parser


def run(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    configured_delays = None
    if args.sources is not None:
        configured_delays = load_source_delays(args.sources)
    events, source_delays = load_events(args.events, configured_delays)
    if not source_delays:
        parser.error(
            "no source delays configured: add a config line to --events or pass --sources"
        )

    unknown_sources = sorted(
        {event.source for event in events if event.source not in source_delays}
    )
    if unknown_sources:
        parser.error(
            "events from unconfigured source(s): " + ", ".join(unknown_sources)
        )

    allowed_lateness = parse_duration(args.allowed_lateness)
    result = merge_events(events, source_delays, allowed_lateness)
    report = build_report(
        result,
        input_count=len(events),
        allowed_lateness_text=args.allowed_lateness,
    )

    if args.out is not None:
        write_report(report, args.out)

    summary = (
        f"events={len(events)} emitted={result.emitted} "
        f"late_accepted={result.late_accepted} dropped={result.dropped_late}"
    )
    print(summary)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> None:
    sys.exit(run(argv if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
    main()
