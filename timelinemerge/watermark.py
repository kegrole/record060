"""Per-source and global watermark progression."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Mapping, Optional


@dataclass
class WatermarkManager:
    """Track source watermarks and expose a monotonic global watermark.

    Each source watermark is the largest event time observed for that source
    minus its configured out-of-order delay. The global watermark is the
    minimum across all sources. Sources which have not produced an event yet
    do not constrain the global watermark; until every configured source is
    observed, the global watermark stays ``None``. The global value is also
    clamped so it can never move backwards.
    """

    source_delays: Mapping[str, timedelta]
    _max_event_times: Dict[str, datetime]
    _source_watermarks: Dict[str, datetime]
    _global_watermark: Optional[datetime]

    def __init__(self, source_delays: Mapping[str, timedelta]):
        self.source_delays = dict(source_delays)
        self._max_event_times = {}
        self._source_watermarks = {}
        self._global_watermark = None

    @property
    def global_watermark(self) -> Optional[datetime]:
        return self._global_watermark

    @property
    def source_watermarks(self) -> Dict[str, datetime]:
        return dict(self._source_watermarks)

    def observe(self, source: str, event_time: datetime) -> Optional[datetime]:
        """Record one event and return the updated global watermark."""
        if source not in self.source_delays:
            raise KeyError(f"no delay configured for source {source!r}")

        previous_max = self._max_event_times.get(source)
        if previous_max is None or event_time > previous_max:
            self._max_event_times[source] = event_time
            self._source_watermarks[source] = (
                event_time - self.source_delays[source]
            )

        if len(self._source_watermarks) < len(self.source_delays):
            candidate = None
        else:
            candidate = min(self._source_watermarks.values())

        if candidate is not None and (
            self._global_watermark is None or candidate > self._global_watermark
        ):
            self._global_watermark = candidate
        return self._global_watermark
