"""ORC-200: deterministic, Qt-independent four-axis behavior contracts (TDD)."""

import inspect
from datetime import UTC, datetime, timedelta
from itertools import product

import pytest

from daemon_reborn import domain
from daemon_reborn.domain import behavior
from daemon_reborn.domain.behavior import BehaviorCommand, BehaviorPolicy
from daemon_reborn.domain.contracts import InterruptPolicy, Priority


class FakeClock:
    def __init__(self) -> None:
        self.seconds = 0.0

    def monotonic(self) -> float:
        return self.seconds

    def wall(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=self.seconds)

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


@pytest.mark.parametrize(
    ("pose", "activity", "emotion", "reaction"),
    list(
        product(
            ("idle", "chase", "fall", "drag"),
            ("idle", "thinking", "speaking"),
            ("neutral", "happy", "sad"),
            ("none", "surprised"),
        )
    ),
)
def test_axes_are_orthogonal_and_replayable(
    pose: str, activity: str, emotion: str, reaction: str
) -> None:
    clock = FakeClock()
    policy = BehaviorPolicy(monotonic=clock.monotonic, wall_clock=clock.wall)
    policy.apply(BehaviorCommand("physical", pose))
    policy.apply(BehaviorCommand("activity", activity))
    policy.apply(BehaviorCommand("emotion", emotion))
    if reaction != "none":
        policy.apply(BehaviorCommand("reaction", reaction, ttl_seconds=2.0))
    expected = (pose, activity, emotion, reaction)
    snapshot = policy.snapshot()
    assert (
        snapshot.physical_state,
        snapshot.activity,
        snapshot.emotion,
        snapshot.reaction,
    ) == expected
    assert snapshot.occurred_at == clock.wall()
    assert policy.snapshot() == snapshot


def test_higher_priority_temporary_reaction_interrupts_and_resumes() -> None:
    clock = FakeClock()
    policy = BehaviorPolicy(monotonic=clock.monotonic, wall_clock=clock.wall)
    policy.apply(BehaviorCommand("reaction", "celebrate", priority=Priority.NORMAL, ttl_seconds=5))
    clock.advance(2)
    policy.apply(BehaviorCommand("reaction", "surprised", priority=Priority.URGENT, ttl_seconds=2))
    clock.advance(2.1)
    assert policy.snapshot().reaction == "celebrate"
    clock.advance(3.1)
    assert policy.snapshot().reaction == "none"


def test_reaction_queue_is_fifo_and_bounded() -> None:
    clock = FakeClock()
    policy = BehaviorPolicy(monotonic=clock.monotonic, wall_clock=clock.wall, max_pending=2)
    policy.apply(BehaviorCommand("reaction", "surprised", ttl_seconds=1))
    policy.apply(
        BehaviorCommand("reaction", "celebrate", ttl_seconds=1, interrupt=InterruptPolicy.QUEUE)
    )
    policy.apply(
        BehaviorCommand("reaction", "disappointed", ttl_seconds=1, interrupt=InterruptPolicy.QUEUE)
    )
    with pytest.raises(OverflowError, match="reaction queue"):
        policy.apply(
            BehaviorCommand("reaction", "celebrate", ttl_seconds=1, interrupt=InterruptPolicy.QUEUE)
        )
    clock.advance(1.1)
    assert policy.snapshot().reaction == "celebrate"
    clock.advance(1.1)
    assert policy.snapshot().reaction == "disappointed"
    clock.advance(1.1)
    assert policy.snapshot().reaction == "none"


def test_lower_priority_or_never_interrupt_does_not_preempt() -> None:
    clock = FakeClock()
    policy = BehaviorPolicy(monotonic=clock.monotonic, wall_clock=clock.wall)
    policy.apply(BehaviorCommand("reaction", "surprised", priority=Priority.HIGH, ttl_seconds=2))
    policy.apply(BehaviorCommand("reaction", "celebrate", priority=Priority.LOW, ttl_seconds=2))
    policy.apply(
        BehaviorCommand(
            "reaction",
            "disappointed",
            priority=Priority.URGENT,
            ttl_seconds=2,
            interrupt=InterruptPolicy.NEVER,
        )
    )
    assert policy.snapshot().reaction == "surprised"
    clock.advance(2.1)
    assert policy.snapshot().reaction == "none"


def test_physical_priority_resets_when_returning_to_idle() -> None:
    clock = FakeClock()
    policy = BehaviorPolicy(monotonic=clock.monotonic, wall_clock=clock.wall)
    policy.apply(BehaviorCommand("physical", "drag", priority=Priority.HIGH))
    policy.apply(BehaviorCommand("physical", "fall", priority=Priority.NORMAL))
    assert policy.snapshot().physical_state == "drag"
    policy.apply(BehaviorCommand("physical", "idle", priority=Priority.HIGH))
    policy.apply(BehaviorCommand("physical", "chase", priority=Priority.NORMAL))
    assert policy.snapshot().physical_state == "chase"


def test_cancel_discards_temporary_reactions_without_affecting_other_axes() -> None:
    clock = FakeClock()
    policy = BehaviorPolicy(monotonic=clock.monotonic, wall_clock=clock.wall)
    policy.apply(BehaviorCommand("physical", "drag"))
    policy.apply(BehaviorCommand("reaction", "surprised", ttl_seconds=3))
    policy.apply(
        BehaviorCommand("reaction", "celebrate", ttl_seconds=3, interrupt=InterruptPolicy.QUEUE)
    )
    policy.cancel_reactions()
    clock.advance(15)
    assert policy.snapshot().reaction == "none"
    assert policy.snapshot().physical_state == "drag"


@pytest.mark.parametrize(
    ("dimension", "value"),
    [
        ("physical", "teleport"),
        ("activity", "tool_execute"),
        ("emotion", "override_permissions"),
        ("reaction", "run_shell"),
        ("invalid", "idle"),
    ],
)
def test_unknown_inputs_fail_closed_without_state_mutation(dimension: str, value: str) -> None:
    clock = FakeClock()
    policy = BehaviorPolicy(monotonic=clock.monotonic, wall_clock=clock.wall)
    initial = policy.snapshot()
    with pytest.raises(ValueError):
        policy.apply(BehaviorCommand(dimension, value, ttl_seconds=1))
    assert policy.snapshot() == initial


@pytest.mark.parametrize("ttl", [None, 0, -1, float("inf"), float("nan"), 31])
def test_nonfinite_missing_or_unbounded_reaction_ttl_is_rejected(ttl: float | None) -> None:
    with pytest.raises((ValueError, TypeError)):
        BehaviorCommand("reaction", "surprised", ttl_seconds=ttl)


def test_clock_rollback_fails_before_mutating_state() -> None:
    clock = FakeClock()
    policy = BehaviorPolicy(monotonic=clock.monotonic, wall_clock=clock.wall)
    policy.apply(BehaviorCommand("activity", "thinking"))
    clock.advance(2)
    assert policy.snapshot().activity == "thinking"
    clock.advance(-4)
    with pytest.raises(ValueError, match="monotonic"):
        policy.apply(BehaviorCommand("activity", "speaking"))
    clock.advance(4)
    assert policy.snapshot().activity == "thinking"


def test_domain_package_exports_behavior_public_contracts() -> None:
    assert domain.BehaviorCommand is BehaviorCommand
    assert domain.BehaviorPolicy is BehaviorPolicy


def test_model_and_qt_modules_are_not_domain_dependencies() -> None:
    text = inspect.getsource(behavior)
    assert "PySide6" not in text
    assert "subprocess" not in text
    assert "openai" not in text
