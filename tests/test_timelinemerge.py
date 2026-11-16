"""Unittest suite covering the seven acceptance criteria and core mechanics."""

from __future__ import annotations

import json
import random
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from timelinemerge import (  # noqa: E402
    Event,
    WatermarkManager,
    canonical_processing_order,
    load_events,
    merge_events,
    order_output,
    parse_duration,
)
from timelinemerge.events import format_timestamp  # noqa: E402

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
ALLOWED_LATENESS = timedelta(seconds=5)
SOURCE_DELAYS = {
    "alpha": timedelta(seconds=2),
    "beta": timedelta(seconds=4),
    "gamma": timedelta(seconds=6),
}


def at(offset_seconds):
    return BASE + timedelta(seconds=offset_seconds)


# (processing offset, event offset, source, id)
FIXTURE_ROWS = [
    (100, 0, "alpha", "evt-001"),
    (101, 10, "beta", "evt-002"),
    (102, 16, "gamma", "evt-003"),
    (103, 20, "alpha", "evt-004"),
    (104, 24, "beta", "evt-005"),
    (105, 26, "gamma", "evt-006"),
    (106, 17, "beta", "evt-007"),    # late, inside window, accepted
    (107, 12, "gamma", "evt-008"),   # late, outside window, dropped (wm 18)
    (108, 13, "alpha", "evt-009"),   # boundary late (threshold 13), accepted
    (109, 30, "alpha", "evt-010"),
    (110, 30, "beta", "evt-011"),
    (111, 34, "gamma", "evt-012"),
    (112, 30, "beta", "evt-013"),
    (113, 22, "alpha", "evt-014"),   # late, inside window, accepted
    (114, 20, "gamma", "evt-015"),   # late, outside window, dropped (wm 26)
]

LATE_ACCEPTED_IDS = {"evt-007", "evt-009", "evt-014"}
DROPPED_IDS = {"evt-008", "evt-015"}


def build_fixture_events(shuffle=False, seed=20260101):
    events = [
        Event(
            event_time=at(event_offset),
            processing_time=at(processing_offset),
            source=source,
            id=event_id,
        )
        for processing_offset, event_offset, source, event_id in FIXTURE_ROWS
    ]
    if shuffle:
        random.Random(seed).shuffle(events)
    return events


def expected_output_sequence():
    rows = [row for row in FIXTURE_ROWS if row[3] not in DROPPED_IDS]
    rows.sort(key=lambda row: (row[1], row[2], row[3]))
    return rows


class AcceptanceFixtureTest(unittest.TestCase):
    """The seven acceptance criteria, evaluated against one generated fixture."""

    def setUp(self):
        self.result = merge_events(
            build_fixture_events(), SOURCE_DELAYS, ALLOWED_LATENESS
        )

    def test_criterion_1_fixture_shape_and_counts(self):
        # Three sources, fifteen events, three in-window late, two over-window.
        events = build_fixture_events()
        self.assertEqual(len(events), 15)
        self.assertEqual({event.source for event in events}, set(SOURCE_DELAYS))
        self.assertEqual(self.result.late_accepted, 3)
        self.assertEqual(self.result.dropped_late, 2)
        accepted_late = [item.event.id for item in self.result.output if item.late]
        self.assertEqual(sorted(accepted_late), sorted(LATE_ACCEPTED_IDS))

    def test_criterion_2_non_decreasing_and_emitted_count(self):
        emitted_times = [item.event.event_time for item in self.result.output]
        self.assertEqual(emitted_times, sorted(emitted_times))
        self.assertEqual(self.result.emitted, 15 - 2)
        self.assertEqual(len(self.result.output), 13)

    def test_criterion_3_tie_ordering_source_then_id(self):
        # Three events share event_time 30. Explicit expected order:
        # (alpha, evt-010) -> (beta, evt-011) -> (beta, evt-013).
        tied = [
            (item.event.source, item.event.id)
            for item in self.result.output
            if item.event.event_time == at(30)
        ]
        self.assertEqual(
            tied,
            [
                ("alpha", "evt-010"),
                ("beta", "evt-011"),
                ("beta", "evt-013"),
            ],
        )
        # The complete expected output order is pinned as well.
        self.assertEqual(
            [item.event.id for item in self.result.output],
            [row[3] for row in expected_output_sequence()],
        )

    def test_criterion_4_late_flags_and_dropped_events(self):
        by_id = {item.event.id: item for item in self.result.output}
        for event_id in LATE_ACCEPTED_IDS:
            self.assertIn(event_id, by_id)
            self.assertTrue(by_id[event_id].late)
        output_ids = {item.event.id for item in self.result.output}
        for event_id in DROPPED_IDS:
            self.assertNotIn(event_id, output_ids)
        dropped_decisions = [
            decision for decision in self.result.decisions if not decision.accepted
        ]
        self.assertEqual(
            {decision.event.id for decision in dropped_decisions}, DROPPED_IDS
        )
        self.assertEqual(self.result.dropped_late, 2)
        self.assertEqual(self.result.late_accepted, 3)

    def test_criterion_5_shuffled_input_gives_identical_output(self):
        shuffled_result = merge_events(
            build_fixture_events(shuffle=True), SOURCE_DELAYS, ALLOWED_LATENESS
        )

        def projection(result):
            return [
                (
                    format_timestamp(item.event.event_time),
                    item.event.source,
                    item.event.id,
                    item.late,
                )
                for item in result.output
            ]

        self.assertEqual(projection(self.result), projection(shuffled_result))
        self.assertEqual(self.result.dropped_late, shuffled_result.dropped_late)
        self.assertEqual(self.result.late_accepted, shuffled_result.late_accepted)

    def test_criterion_6_monotonic_watermark_and_drop_watermarks(self):
        history = self.result.watermark_history
        self.assertEqual(history, sorted(history))
        self.assertTrue(
            all(left <= right for left, right in zip(history, history[1:]))
        )

        dropped = {
            decision.event.id: decision
            for decision in self.result.decisions
            if not decision.accepted
        }
        # evt-008 is dropped while the watermark is 18s.
        self.assertEqual(dropped["evt-008"].watermark_at_decision, at(18))
        self.assertGreaterEqual(at(18), dropped["evt-008"].event.event_time)
        # evt-015 is dropped once the watermark has advanced to 26s.
        self.assertEqual(dropped["evt-015"].watermark_at_decision, at(26))
        self.assertGreaterEqual(at(26), dropped["evt-015"].event.event_time)
        self.assertEqual(self.result.final_watermark, at(26))

    def test_criterion_7_report_fields_and_emitted_matches_output(self):
        from timelinemerge.report import build_report

        report = build_report(self.result, input_count=15)
        for field_name in (
            "final_watermark",
            "emitted",
            "dropped_late",
            "late_accepted",
        ):
            self.assertIn(field_name, report)
        self.assertEqual(report["emitted"], len(self.result.output))
        self.assertEqual(report["dropped_late"], 2)
        self.assertEqual(report["late_accepted"], 3)
        self.assertEqual(report["final_watermark"], format_timestamp(at(26)))


class WatermarkMechanicsTest(unittest.TestCase):
    def test_per_source_minus_delay_and_global_minimum(self):
        manager = WatermarkManager(SOURCE_DELAYS)
        self.assertIsNone(manager.observe("alpha", at(10)))
        self.assertIsNone(manager.observe("beta", at(12)))
        self.assertEqual(manager.observe("gamma", at(14)), at(8))
        # alpha 8, beta 8, gamma 8 -> global 8.
        self.assertEqual(manager.global_watermark, at(8))
        self.assertEqual(manager.observe("alpha", at(20)), at(8))
        # alpha 18, minimum remains gamma 8.
        self.assertEqual(manager.observe("gamma", at(30)), at(8))
        # gamma 24, beta advances to 26 -> minimum becomes alpha 18.
        self.assertEqual(manager.observe("beta", at(30)), at(18))

    def test_watermark_never_regresses(self):
        manager = WatermarkManager(SOURCE_DELAYS)
        manager.observe("alpha", at(100))
        manager.observe("beta", at(100))
        manager.observe("gamma", at(100))
        high = manager.global_watermark
        manager.observe("gamma", at(10))
        self.assertEqual(manager.global_watermark, high)

    def test_unknown_source_is_rejected(self):
        manager = WatermarkManager(SOURCE_DELAYS)
        with self.assertRaises(KeyError):
            manager.observe("unknown", at(1))

    def test_window_boundaries_are_inclusive_and_lateness_is_strict(self):
        events = [
            Event(at(10), at(100), "alpha", "a1"),
            Event(at(12), at(101), "beta", "b1"),
            Event(at(14), at(102), "gamma", "g1"),  # global watermark = 8
            Event(at(8), at(103), "alpha", "a2"),   # equal to wm: on time
            Event(at(3), at(104), "alpha", "a3"),   # threshold 3: kept
            Event(at(2), at(105), "alpha", "a4"),   # below threshold: dropped
        ]
        result = merge_events(events, SOURCE_DELAYS, timedelta(seconds=5))
        decisions = {item.event.id: item for item in result.decisions}
        self.assertFalse(decisions["a2"].late)
        self.assertTrue(decisions["a3"].late)
        self.assertTrue(decisions["a3"].accepted)
        self.assertFalse(decisions["a4"].accepted)
        self.assertEqual(result.dropped_late, 1)
        self.assertEqual(result.late_accepted, 1)


class OrderingAndParsingTest(unittest.TestCase):
    def test_output_uses_both_secondary_keys(self):
        events = [
            Event(at(5), at(2), "gamma", "z"),
            Event(at(5), at(1), "beta", "b"),
            Event(at(5), at(3), "alpha", "a"),
            Event(at(5), at(4), "beta", "a"),
        ]
        ordered = order_output(events)
        self.assertEqual(
            [(event.source, event.id) for event in ordered],
            [
                ("alpha", "a"),
                ("beta", "a"),
                ("beta", "b"),
                ("gamma", "z"),
            ],
        )

    def test_canonical_processing_order_is_deterministic(self):
        events = [
            Event(at(9), at(1), "gamma", "x"),
            Event(at(8), at(1), "alpha", "x"),
            Event(at(7), at(1), "alpha", "a"),
            Event(at(6), at(0), "beta", "q"),
        ]
        ordered = canonical_processing_order(events)
        self.assertEqual([event.id for event in ordered], ["q", "a", "x", "x"])

    def test_duration_parsing_units(self):
        self.assertEqual(parse_duration("5s"), timedelta(seconds=5))
        self.assertEqual(parse_duration("250ms"), timedelta(milliseconds=250))
        self.assertEqual(parse_duration("2m"), timedelta(minutes=2))
        self.assertEqual(parse_duration("1h"), timedelta(hours=1))
        self.assertEqual(parse_duration(7), timedelta(seconds=7))
        with self.assertRaises(ValueError):
            parse_duration("5xy")


class CliAndDemoTest(unittest.TestCase):
    DEMO = REPO_ROOT / "demo" / "events.jsonl"

    def test_demo_file_matches_generated_acceptance_fixture(self):
        events, delays = load_events(self.DEMO)
        self.assertEqual(len(events), 15)
        self.assertEqual(
            delays,
            {
                "alpha": timedelta(seconds=2),
                "beta": timedelta(seconds=4),
                "gamma": timedelta(seconds=6),
            },
        )
        demo_rows = sorted(
            (event.event_time, event.processing_time, event.source, event.id)
            for event in events
        )
        fixture_rows = sorted(
            (at(event_offset), at(processing_offset), source, event_id)
            for processing_offset, event_offset, source, event_id in FIXTURE_ROWS
        )
        self.assertEqual(demo_rows, fixture_rows)

        result = merge_events(events, delays, ALLOWED_LATENESS)
        self.assertEqual(result.emitted, 13)
        self.assertEqual(result.late_accepted, 3)
        self.assertEqual(result.dropped_late, 2)
        self.assertEqual(result.final_watermark, at(26))

    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "report.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "timelinemerge.cli",
                    "--events",
                    str(self.DEMO),
                    "--allowed-lateness",
                    "5s",
                    "--out",
                    str(out_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = completed.stdout.strip()
            self.assertIn("events=15", summary)
            self.assertIn("emitted=13", summary)
            self.assertIn("late_accepted=3", summary)
            self.assertIn("dropped=2", summary)
            report = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(report["emitted"], 13)
            self.assertEqual(report["dropped_late"], 2)
            self.assertEqual(report["late_accepted"], 3)
            self.assertEqual(report["final_watermark"], format_timestamp(at(26)))


if __name__ == "__main__":
    unittest.main()
