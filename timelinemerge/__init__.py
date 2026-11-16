"""Multi-source event-time stream merging with watermarks and lateness."""

from .events import Event, load_events, parse_duration, parse_timestamp
from .late import Decision, MergeResult, merge_events
from .ordering import canonical_processing_order, order_output
from .report import build_report, write_report
from .watermark import WatermarkManager

__all__ = [
    "Decision",
    "Event",
    "MergeResult",
    "WatermarkManager",
    "build_report",
    "canonical_processing_order",
    "load_events",
    "merge_events",
    "order_output",
    "parse_duration",
    "parse_timestamp",
    "write_report",
]
