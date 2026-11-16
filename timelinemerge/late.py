"""Merge engine: watermark-driven lateness decisions and output ordering."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Mapping, Sequence

from .events import Event, format_timestamp
from .ordering import canonical_processing_order, order_output
from .watermark import WatermarkManager

ON_TIME = "on_time"
LATE_ACCEPTED = "late_accepted"
LATE_DROPPED = "late_dropped"


@dataclass(frozen=True)
class MergedEvent:
    """An event accepted into the merged output."""

    event: Event
    late: bool
    watermark_at_decision: datetime
    decision: str

    def to_dict(self) -> Dict[str, object]:
        payload = self.event.to_dict()
        payload["late"] = self.late
        payload["decision"] = self.decision
        payload["watermark_at_decision"] = (
            format_timestamp(self.watermark_at_decision)
            if self.watermark_at_decision is not None
            else None
        )
        return payload


@dataclass(frozen=True)
class Decision:
    """The accept/drop decision recorded for one input event."""

    event: Event
    accepted: bool
    late: bool
    decision: str
    watermark_at_decision: datetime
    threshold: datetime

    def to_dict(self) -> Dict[str, object]:
        return {
            "event": self.event.to_dict(),
            "accepted": self.accepted,
            "late": self.late,
            "decision": self.decision,
            "watermark_at_decision": (
                format_timestamp(self.watermark_at_decision)
                if self.watermark_at_decision is not None
                else None
            ),
            "drop_threshold": format_timestamp(self.threshold),
        }


@dataclass
class MergeResult:
    """Outcome of merging one bounded batch of events."""

    output: List[MergedEvent]
    decisions: List[Decision]
    watermark_history: List[datetime] = field(default_factory=list)
    final_watermark: datetime = None  # type: ignore[assignment]
    emitted: int = 0
    dropped_late: int = 0
    late_accepted: int = 0


def merge_events(
    events: Sequence[Event],
    source_delays: Mapping[str, timedelta],
    allowed_lateness: timedelta,
) -> MergeResult:
    """Merge out-of-order events from multiple sources.

    Events are observed in deterministic processing-time order. After each
    observation the global watermark advances (never backwards). An event is
    late when its event time is strictly earlier than the current watermark;
    it is kept while it remains within the allowed-lateness window and
    discarded once it falls outside the window. Accepted events are emitted
    ordered by ``(event_time, source, id)``.
    """
    manager = WatermarkManager(source_delays)
    decisions: List[Decision] = []
    accepted: List[MergedEvent] = []
    watermark_history: List[datetime] = []
    dropped_late = 0
    late_accepted = 0

    for event in canonical_processing_order(events):
        watermark = manager.observe(event.source, event.event_time)
        if watermark is not None:
            watermark_history.append(watermark)

        if watermark is None or event.event_time >= watermark:
            decision_kind = ON_TIME
            is_late = False
            accepted_flag = True
            decision_watermark = watermark
            threshold = (
                watermark - allowed_lateness
                if watermark is not None
                else event.event_time
            )
        else:
            is_late = True
            threshold = watermark - allowed_lateness
            decision_watermark = watermark
            if event.event_time < threshold:
                decision_kind = LATE_DROPPED
                accepted_flag = False
                dropped_late += 1
            else:
                decision_kind = LATE_ACCEPTED
                accepted_flag = True
                late_accepted += 1

        decision = Decision(
            event=event,
            accepted=accepted_flag,
            late=is_late,
            decision=decision_kind,
            watermark_at_decision=decision_watermark,
            threshold=threshold,
        )
        decisions.append(decision)
        if accepted_flag:
            accepted.append(
                MergedEvent(
                    event=event,
                    late=is_late,
                    watermark_at_decision=decision_watermark,
                    decision=decision_kind,
                )
            )

    # Reorder the accepted events (with their decision metadata attached).
    metadata = {item.event: item for item in accepted}
    output = [
        metadata[event]
        for event in order_output([item.event for item in accepted])
    ]

    return MergeResult(
        output=output,
        decisions=decisions,
        watermark_history=watermark_history,
        final_watermark=manager.global_watermark,
        emitted=len(output),
        dropped_late=dropped_late,
        late_accepted=late_accepted,
    )
