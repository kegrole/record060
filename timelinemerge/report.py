"""Serialisable merge reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .events import format_timestamp
from .late import MergeResult


def build_report(
    result: MergeResult,
    input_count: int,
    allowed_lateness_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the JSON-serialisable report dictionary."""
    report: Dict[str, Any] = {
        "final_watermark": (
            format_timestamp(result.final_watermark)
            if result.final_watermark is not None
            else None
        ),
        "emitted": result.emitted,
        "dropped_late": result.dropped_late,
        "late_accepted": result.late_accepted,
        "input_events": input_count,
        "output": [item.to_dict() for item in result.output],
        "dropped": [
            decision.to_dict()
            for decision in result.decisions
            if not decision.accepted
        ],
        "watermark_history": [
            format_timestamp(value) for value in result.watermark_history
        ],
    }
    if allowed_lateness_text is not None:
        report["allowed_lateness"] = allowed_lateness_text
    return report


def write_report(report: Dict[str, Any], path: Path) -> None:
    """Write the report to ``path``, creating parent directories as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
