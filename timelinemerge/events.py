"""Event model, JSONL loading, and time/duration parsing.

Only the Python standard library is used.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

DurationLike = Union[timedelta, int, float, str]

_DURATION_UNITS = {
    "ms": "milliseconds",
    "s": "seconds",
    "sec": "seconds",
    "secs": "seconds",
    "second": "seconds",
    "seconds": "seconds",
    "m": "minutes",
    "min": "minutes",
    "mins": "minutes",
    "minute": "minutes",
    "minutes": "minutes",
    "h": "hours",
    "hr": "hours",
    "hrs": "hours",
    "hour": "hours",
    "hours": "hours",
}


def parse_duration(value: DurationLike) -> timedelta:
    """Parse a duration into a :class:`timedelta`.

    Bare numbers are interpreted as seconds. Strings take an optional unit
    suffix such as ``5s``, ``250ms``, ``2m`` or ``1h``; a unit-less string is
    also treated as seconds.
    """
    if isinstance(value, timedelta):
        return value
    if isinstance(value, bool):
        raise ValueError(f"invalid duration: {value!r}")
    if isinstance(value, (int, float)):
        return timedelta(seconds=value)
    if not isinstance(value, str):
        raise ValueError(f"unsupported duration type: {type(value).__name__}")

    text_value = value.strip().lower()
    if not text_value:
        raise ValueError("empty duration")
    split_at = len(text_value)
    for index, char in enumerate(text_value):
        if not (char.isdigit() or char == "." or char == "-"):
            split_at = index
            break
    number_text = text_value[:split_at].strip()
    unit = text_value[split_at:].strip()
    if not number_text:
        raise ValueError(f"invalid duration: {value!r}")
    try:
        number = float(number_text)
    except ValueError as exc:
        raise ValueError(f"invalid duration: {value!r}") from exc
    if not unit:
        return timedelta(seconds=number)
    keyword = _DURATION_UNITS.get(unit)
    if keyword is None:
        raise ValueError(f"unknown duration unit {unit!r} in {value!r}")
    return timedelta(**{keyword: number})


def parse_timestamp(value: Union[str, datetime]) -> datetime:
    """Parse an ISO 8601 timestamp into a timezone-aware UTC datetime."""
    if isinstance(value, datetime):
        parsed = value
    else:
        text_value = value.strip()
        if text_value.endswith("Z") or text_value.endswith("z"):
            text_value = text_value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text_value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_timestamp(value: datetime) -> str:
    """Render a UTC datetime as an ISO 8601 string with a trailing ``Z``."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Event:
    """A single event observed from one source."""

    event_time: datetime
    processing_time: datetime
    source: str
    id: str

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "Event":
        missing = [
            key
            for key in ("event_time", "processing_time", "source", "id")
            if key not in data
        ]
        if missing:
            raise ValueError(
                f"event missing required field(s): {', '.join(missing)}"
            )
        return cls(
            event_time=parse_timestamp(data["event_time"]),  # type: ignore[arg-type]
            processing_time=parse_timestamp(data["processing_time"]),  # type: ignore[arg-type]
            source=str(data["source"]),
            id=str(data["id"]),
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "event_time": format_timestamp(self.event_time),
            "processing_time": format_timestamp(self.processing_time),
            "source": self.source,
            "id": self.id,
        }


def load_events(
    path: Union[str, Path], source_delays: Optional[Dict[str, DurationLike]] = None
) -> "tuple[List[Event], Dict[str, timedelta]]":
    """Load events from a JSONL file.

    Plain lines are event objects. A line of the form
    ``{"config": {"source_delays": {"alpha": "2s", ...}}}`` carries the
    per-source delay configuration and may appear anywhere in the file.
    """
    events: List[Event] = []
    delays: Dict[str, timedelta] = {}
    if source_delays:
        delays = {
            source: parse_duration(delay)
            for source, delay in source_delays.items()
        }

    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSON on line {line_number} of {path}: {exc.msg}"
                ) from exc
            if not isinstance(payload, dict):
                raise ValueError(
                    f"line {line_number} of {path} must be a JSON object"
                )
            if "config" in payload:
                config = payload["config"]
                if not isinstance(config, dict) or "source_delays" not in config:
                    raise ValueError(f"invalid config line {line_number} of {path}")
                raw_delays = config["source_delays"]
                if not isinstance(raw_delays, dict):
                    raise ValueError(
                        f"source_delays on line {line_number} must be an object"
                    )
                for source, delay in raw_delays.items():
                    delays[str(source)] = parse_duration(delay)
                continue
            events.append(Event.from_dict(payload))
    return events, delays


def load_source_delays(path: Union[str, Path]) -> Dict[str, timedelta]:
    """Load ``{source: delay}`` mappings from a standalone JSON file."""
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("source delay file must contain a JSON object")
    return {str(source): parse_duration(delay) for source, delay in payload.items()}


def iter_event_dicts(events: Iterable[Event]) -> Iterable[Dict[str, object]]:
    """Yield JSON-serialisable dictionaries for a sequence of events."""
    for event in events:
        yield event.to_dict()
