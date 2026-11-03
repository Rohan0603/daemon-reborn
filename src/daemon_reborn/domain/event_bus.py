"""Thread-safe bounded FIFO event delivery with deterministic overload behavior."""

from __future__ import annotations

from collections import deque
from enum import StrEnum
from threading import Lock
from uuid import UUID

from daemon_reborn.domain.contracts import DomainEvent, RequestId, new_request_id


class PublishResult(StrEnum):
    """Outcome of a non-blocking publish operation."""

    ACCEPTED = "accepted"
    ACCEPTED_AFTER_EVICTION = "accepted_after_eviction"
    DROPPED_CAPACITY = "dropped_capacity"
    DROPPED_STALE = "dropped_stale"


class BoundedEventBus:
    """An in-memory bounded queue; equal-priority overflow always drops newest."""

    def __init__(self, maxsize: int = 256) -> None:
        if isinstance(maxsize, bool) or not isinstance(maxsize, int) or maxsize < 1:
            raise ValueError("maxsize must be a positive integer")
        self._maxsize = maxsize
        self._events: deque[DomainEvent] = deque()
        self._active_requests: set[RequestId] = set()
        self._lock = Lock()

    @property
    def maxsize(self) -> int:
        return self._maxsize

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._events)

    def begin_request(self) -> RequestId:
        """Reserve one bounded request ID so late responses can be suppressed."""

        with self._lock:
            if len(self._active_requests) >= self._maxsize:
                raise OverflowError("active request capacity reached")
            request_id = new_request_id()
            while request_id in self._active_requests:
                request_id = new_request_id()
            self._active_requests.add(request_id)
            return request_id

    def cancel_request(self, request_id: RequestId) -> bool:
        """Invalidate a request and discard its queued messages."""

        return self._finish_request(request_id)

    def complete_request(self, request_id: RequestId) -> bool:
        """Release request capacity after a response has been consumed."""

        return self._finish_request(request_id)

    def is_request_active(self, request_id: RequestId) -> bool:
        with self._lock:
            return request_id in self._active_requests

    def _finish_request(self, request_id: RequestId) -> bool:
        if not isinstance(request_id, UUID):
            raise TypeError("request_id must be a UUID")
        with self._lock:
            was_active = request_id in self._active_requests
            self._active_requests.discard(request_id)
            self._events = deque(
                event for event in self._events if event.correlation_id != request_id
            )
            return was_active

    def publish(self, event: DomainEvent) -> PublishResult:
        """Publish without blocking; preserve FIFO except deterministic overflow eviction."""

        if not isinstance(event, DomainEvent):
            raise TypeError("event must be a DomainEvent")
        with self._lock:
            if event.correlation_id is not None and event.correlation_id not in self._active_requests:
                return PublishResult.DROPPED_STALE
            if len(self._events) < self._maxsize:
                self._events.append(event)
                return PublishResult.ACCEPTED

            lowest_index = min(
                range(len(self._events)),
                key=lambda index: (int(self._events[index].priority), index),
            )
            lowest_priority = self._events[lowest_index].priority
            if event.priority <= lowest_priority:
                return PublishResult.DROPPED_CAPACITY

            del self._events[lowest_index]
            self._events.append(event)
            return PublishResult.ACCEPTED_AFTER_EVICTION

    def drain(self, max_items: int | None = None) -> list[DomainEvent]:
        """Remove and return events in FIFO insertion order."""

        if max_items is not None and (
            isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 0
        ):
            raise ValueError("max_items must be a non-negative integer or None")
        with self._lock:
            count = len(self._events) if max_items is None else min(max_items, len(self._events))
            return [self._events.popleft() for _ in range(count)]


__all__ = ["BoundedEventBus", "PublishResult"]
