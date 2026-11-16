"""Deterministic ordering helpers."""

from __future__ import annotations

from typing import Iterable, List, Sequence

from .events import Event


def canonical_processing_order(events: Iterable[Event]) -> List[Event]:
    """Return events in the order in which the merge observes them.

    Real arrival order is ``processing_time``; because two events can share a
    processing timestamp, deterministic tie-breakers are applied so shuffling
    the input collection cannot change the result.
    """
    return sorted(
        events,
        key=lambda event: (
            event.processing_time,
            event.source,
            event.id,
            event.event_time,
        ),
    )


def order_output(events: Sequence[Event]) -> List[Event]:
    """Order accepted events by event time, then source, then id.

    ``sorted`` is stable, but both secondary keys are explicit so equal event
    times are always resolved by source first and id second regardless of the
    incoming order.
    """
    return sorted(
        events, key=lambda event: (event.event_time, event.source, event.id)
    )
