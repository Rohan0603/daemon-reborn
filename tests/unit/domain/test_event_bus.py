"""Tests for bounded delivery, overflow policy, and cancellation suppression."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID

from daemon_reborn.domain.contracts import DomainEvent, Priority
from daemon_reborn.domain.event_bus import BoundedEventBus, PublishResult


def event(name: str, priority: Priority, correlation_id: UUID | None = None) -> DomainEvent:
    return DomainEvent(
        event_type=name,
        source="test",
        payload={"name": name},
        priority=priority,
        correlation_id=correlation_id,
        occurred_at=datetime(2026, 11, 3, tzinfo=UTC),
    )


def test_event_bus_preserves_fifo_order_within_capacity() -> None:
    bus = BoundedEventBus(maxsize=2)

    assert bus.publish(event("first", Priority.NORMAL)) is PublishResult.ACCEPTED
    assert bus.publish(event("second", Priority.NORMAL)) is PublishResult.ACCEPTED
    assert [item.event_type for item in bus.drain()] == ["first", "second"]


def test_event_bus_drops_new_event_when_full_and_priority_is_not_higher() -> None:
    bus = BoundedEventBus(maxsize=2)
    bus.publish(event("first", Priority.NORMAL))
    bus.publish(event("second", Priority.HIGH))

    result = bus.publish(event("third", Priority.NORMAL))

    assert result is PublishResult.DROPPED_CAPACITY
    assert [item.event_type for item in bus.drain()] == ["first", "second"]


def test_event_bus_evicts_oldest_lowest_priority_for_more_important_event() -> None:
    bus = BoundedEventBus(maxsize=2)
    bus.publish(event("low-first", Priority.LOW))
    bus.publish(event("low-second", Priority.LOW))

    result = bus.publish(event("urgent", Priority.URGENT))

    assert result is PublishResult.ACCEPTED_AFTER_EVICTION
    assert [item.event_type for item in bus.drain()] == ["low-second", "urgent"]


def test_cancelled_request_removes_queued_events_and_suppresses_late_events() -> None:
    bus = BoundedEventBus(maxsize=2)
    request_id = bus.begin_request()
    assert bus.publish(event("response", Priority.NORMAL, request_id)) is PublishResult.ACCEPTED

    bus.cancel_request(request_id)

    assert bus.publish(event("late-response", Priority.URGENT, request_id)) is PublishResult.DROPPED_STALE
    assert bus.drain() == []


def test_request_capacity_is_bounded_and_completed_ids_are_stale() -> None:
    bus = BoundedEventBus(maxsize=1)
    first_id = bus.begin_request()

    try:
        bus.begin_request()
    except OverflowError:
        pass
    else:
        raise AssertionError("request capacity must be bounded")

    bus.complete_request(first_id)

    assert bus.publish(event("completed-response", Priority.NORMAL, first_id)) is PublishResult.DROPPED_STALE


def test_concurrent_publishers_cannot_exceed_queue_capacity() -> None:
    bus = BoundedEventBus(maxsize=64)

    def publish_batch(worker: int) -> None:
        for index in range(100):
            bus.publish(event(f"{worker}-{index}", Priority.NORMAL))

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(publish_batch, range(8)))

    delivered = bus.drain()
    assert len(delivered) == 64
    assert len({item.event_id for item in delivered}) == 64
