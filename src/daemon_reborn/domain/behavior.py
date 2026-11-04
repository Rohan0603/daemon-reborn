"""Deterministic four-axis behavior reducer for ORC-200.

The reducer owns no I/O or GUI state. A later, separately authorized adapter
converts sanitized domain events into BehaviorCommand values.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from daemon_reborn.domain.contracts import BehaviorSnapshot, InterruptPolicy, Priority


_ALLOWED: dict[str, frozenset[str]] = {
    "physical": frozenset({"idle", "chase", "fall", "drag"}),
    "activity": frozenset({"idle", "thinking", "speaking"}),
    "emotion": frozenset({"neutral", "happy", "sad"}),
    "reaction": frozenset({"none", "surprised", "celebrate", "disappointed"}),
}
_REST = {"physical": "idle", "activity": "idle", "emotion": "neutral"}
_MAX_REACTION_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class BehaviorCommand:
    """A validated local behavior intent; never an OS action or authorization."""

    dimension: str
    value: str
    priority: Priority = Priority.NORMAL
    ttl_seconds: float | None = None
    interrupt: InterruptPolicy = InterruptPolicy.ALLOW

    def __post_init__(self) -> None:
        if self.dimension not in _ALLOWED:
            raise ValueError("unknown behavior dimension")
        if not isinstance(self.value, str) or self.value not in _ALLOWED[self.dimension]:
            raise ValueError("unknown behavior value")
        if not isinstance(self.priority, Priority):
            raise TypeError("priority must be Priority")
        if not isinstance(self.interrupt, InterruptPolicy):
            raise TypeError("interrupt must be InterruptPolicy")
        if self.dimension == "reaction" and self.value != "none":
            ttl = self.ttl_seconds
            if (
                isinstance(ttl, bool)
                or not isinstance(ttl, (float, int))
                or not math.isfinite(ttl)
                or not 0.0 < ttl <= _MAX_REACTION_SECONDS
            ):
                raise ValueError("temporary reaction requires bounded positive TTL")
        elif self.ttl_seconds is not None:
            raise ValueError("TTL is permitted only for a nonempty reaction")


@dataclass(frozen=True, slots=True)
class _ActiveReaction:
    value: str
    priority: Priority
    deadline: float


@dataclass(frozen=True, slots=True)
class _PendingReaction:
    value: str
    priority: Priority
    seconds: float


class BehaviorPolicy:
    """Pure, clock-injected deterministic behavior state and bounded reactions.

    Physical pose, activity and emotion are independent axes. Temporary reactions
    are prioritized overlays: a higher-priority reaction suspends the old one,
    explicit QUEUE defers it, and NEVER does not interrupt. Queues are bounded.
    """

    def __init__(
        self,
        *,
        monotonic: Callable[[], float],
        wall_clock: Callable[[], datetime],
        max_pending: int = 8,
    ) -> None:
        if not callable(monotonic) or not callable(wall_clock):
            raise TypeError("injected clocks must be callable")
        if isinstance(max_pending, bool) or not isinstance(max_pending, int) or max_pending < 1:
            raise ValueError("max_pending must be a positive integer")
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._max_pending = max_pending
        self._last_time: float | None = None
        self._axes: dict[str, str] = dict(_REST)
        self._axis_priority: dict[str, Priority] = {
            dimension: Priority.NORMAL for dimension in _REST
        }
        self._active: _ActiveReaction | None = None
        self._suspended: list[_PendingReaction] = []
        self._queued: deque[_PendingReaction] = deque()

    def _now(self) -> float:
        value = self._monotonic()
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("monotonic clock must return a numeric value")
        current = float(value)
        if not math.isfinite(current):
            raise ValueError("monotonic clock must return a finite number")
        if self._last_time is not None and current < self._last_time:
            raise ValueError("monotonic clock moved backward")
        self._last_time = current
        return current

    def _advance(self, now: float) -> None:
        # Start resumed/queued reactions at the *previous deadline*, not now,
        # so a long sleep cannot replay a stale queue on wake.
        while self._active is not None and now >= self._active.deadline:
            boundary = self._active.deadline
            if self._suspended:
                next_item = self._suspended.pop()
            elif self._queued:
                next_item = self._queued.popleft()
            else:
                self._active = None
                return
            self._active = _ActiveReaction(
                next_item.value, next_item.priority, boundary + next_item.seconds
            )

    def _snapshot_at(self) -> BehaviorSnapshot:
        occurred_at = self._wall_clock()
        if not isinstance(occurred_at, datetime):
            raise TypeError("wall clock must return datetime")
        return BehaviorSnapshot(
            physical_state=self._axes["physical"],
            activity=self._axes["activity"],
            emotion=self._axes["emotion"],
            reaction="none" if self._active is None else self._active.value,
            occurred_at=occurred_at,
        )

    def snapshot(self) -> BehaviorSnapshot:
        now = self._now()
        self._advance(now)
        return self._snapshot_at()

    def apply(self, command: BehaviorCommand) -> BehaviorSnapshot:
        if not isinstance(command, BehaviorCommand):
            raise TypeError("command must be BehaviorCommand")
        now = self._now()
        self._advance(now)

        if command.dimension != "reaction":
            if command.priority >= self._axis_priority[command.dimension]:
                self._axes[command.dimension] = command.value
                self._axis_priority[command.dimension] = (
                    Priority.NORMAL if command.value == _REST[command.dimension]
                    else command.priority
                )
            return self._snapshot_at()

        if command.value == "none":
            self._clear_reactions()
            return self._snapshot_at()

        seconds = float(command.ttl_seconds)  # Validated by BehaviorCommand.
        incoming = _PendingReaction(command.value, command.priority, seconds)
        if self._active is None:
            self._active = _ActiveReaction(command.value, command.priority, now + seconds)
        elif command.interrupt == InterruptPolicy.QUEUE:
            if len(self._queued) >= self._max_pending:
                raise OverflowError("reaction queue full")
            self._queued.append(incoming)
        elif command.interrupt == InterruptPolicy.NEVER or command.priority < self._active.priority:
            pass
        else:
            if command.priority > self._active.priority:
                if len(self._suspended) >= self._max_pending:
                    raise OverflowError("reaction suspend stack full")
                remaining = self._active.deadline - now
                if remaining > 0.0:
                    self._suspended.append(
                        _PendingReaction(self._active.value, self._active.priority, remaining)
                    )
            self._active = _ActiveReaction(command.value, command.priority, now + seconds)
        return self._snapshot_at()

    def _clear_reactions(self) -> None:
        self._active = None
        self._suspended.clear()
        self._queued.clear()

    def cancel_reactions(self) -> BehaviorSnapshot:
        now = self._now()
        self._advance(now)
        self._clear_reactions()
        return self._snapshot_at()


__all__ = ["BehaviorCommand", "BehaviorPolicy"]
