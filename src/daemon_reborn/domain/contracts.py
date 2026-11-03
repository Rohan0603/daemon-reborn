"""Immutable, standard-library-only domain messages and value contracts."""

from __future__ import annotations

import math
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from types import MappingProxyType
from uuid import UUID, uuid4

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | tuple[JsonValue, ...] | Mapping[str, JsonValue]
type RequestId = UUID


class Priority(IntEnum):
    """Priority used only to choose which event survives queue overload."""

    LOW = 10
    NORMAL = 20
    HIGH = 30
    URGENT = 40


class InterruptPolicy(StrEnum):
    """How an animation intent can interact with the currently playing clip."""

    ALLOW = "allow"
    QUEUE = "queue"
    NEVER = "never"


def new_request_id() -> RequestId:
    """Return an opaque correlation ID for one asynchronous request."""

    return uuid4()


def _freeze_json(
    value: object,
    path: str = "payload",
    ancestors: set[int] | None = None,
) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, (Mapping, list, tuple)):
        active = set() if ancestors is None else ancestors
        identity = id(value)
        if identity in active:
            raise ValueError(f"{path} contains a cyclic reference")
        active.add(identity)
        try:
            if isinstance(value, Mapping):
                frozen: dict[str, JsonValue] = {}
                for key, nested in value.items():
                    if not isinstance(key, str):
                        raise TypeError(f"{path} keys must be strings")
                    frozen[key] = _freeze_json(nested, f"{path}.{key}", active)
                return MappingProxyType(frozen)
            return tuple(
                _freeze_json(nested, f"{path}[{index}]", active)
                for index, nested in enumerate(value)
            )
        finally:
            active.remove(identity)
    raise TypeError(f"{path} contains unsupported value {type(value).__name__}")


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_aware_datetime(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Sanitized event payload with stable identifiers and optional correlation."""

    event_type: str
    source: str
    payload: Mapping[str, object]
    priority: Priority = Priority.NORMAL
    correlation_id: RequestId | None = None
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        _require_text("event_type", self.event_type)
        _require_text("source", self.source)
        if not isinstance(self.priority, Priority):
            raise TypeError("priority must be a Priority")
        if not isinstance(self.event_id, UUID):
            raise TypeError("event_id must be a UUID")
        if self.correlation_id is not None and not isinstance(self.correlation_id, UUID):
            raise TypeError("correlation_id must be a UUID or None")
        _require_aware_datetime("occurred_at", self.occurred_at)
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")
        frozen = _freeze_json(self.payload)
        if not isinstance(frozen, Mapping):
            raise TypeError("payload must be a mapping")
        object.__setattr__(self, "payload", frozen)


@dataclass(frozen=True, slots=True)
class BehaviorSnapshot:
    """Deterministic, serializable inputs to behavior and animation policy."""

    physical_state: str
    activity: str
    emotion: str
    reaction: str
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        for name in ("physical_state", "activity", "emotion", "reaction"):
            _require_text(name, getattr(self, name))
        _require_aware_datetime("occurred_at", self.occurred_at)


@dataclass(frozen=True, slots=True)
class AnimationIntent:
    """Allow-listed clip intent; it never carries an arbitrary asset path."""

    clip_id: str
    priority: Priority
    interrupt_policy: InterruptPolicy
    loop: bool
    anchor: tuple[float, float] = (0.5, 1.0)

    def __post_init__(self) -> None:
        _require_text("clip_id", self.clip_id)
        if not isinstance(self.priority, Priority):
            raise TypeError("priority must be a Priority")
        if not isinstance(self.interrupt_policy, InterruptPolicy):
            raise TypeError("interrupt_policy must be an InterruptPolicy")
        if not isinstance(self.loop, bool):
            raise TypeError("loop must be a bool")
        if len(self.anchor) != 2 or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or not 0.0 <= value <= 1.0
            for value in self.anchor
        ):
            raise ValueError("anchor values must be finite normalized coordinates between 0 and 1")
        object.__setattr__(self, "anchor", (float(self.anchor[0]), float(self.anchor[1])))


@dataclass(frozen=True, slots=True)
class SpeechRequest:
    """A sanitized speech request correlated across UI, provider and worker."""

    request_id: RequestId
    text: str
    voice_profile: str | None = None
    style_flags: AbstractSet[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, UUID):
            raise TypeError("request_id must be a UUID")
        _require_text("text", self.text)
        if self.voice_profile is not None:
            _require_text("voice_profile", self.voice_profile)
        if not isinstance(self.style_flags, AbstractSet):
            raise TypeError("style_flags must be a set of strings")
        if any(not isinstance(flag, str) or not flag.strip() for flag in self.style_flags):
            raise ValueError("style_flags must contain only non-empty strings")
        object.__setattr__(self, "style_flags", frozenset(self.style_flags))


__all__ = [
    "AnimationIntent",
    "BehaviorSnapshot",
    "DomainEvent",
    "InterruptPolicy",
    "JsonValue",
    "Priority",
    "RequestId",
    "SpeechRequest",
    "new_request_id",
]
