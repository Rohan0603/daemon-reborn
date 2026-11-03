"""Tests for immutable, Qt-independent domain contracts."""

from collections.abc import Mapping, MutableMapping
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from daemon_reborn.domain.contracts import (
    AnimationIntent,
    BehaviorSnapshot,
    DomainEvent,
    InterruptPolicy,
    Priority,
    SpeechRequest,
    new_request_id,
)


def test_domain_event_deep_freezes_valid_json_payload() -> None:
    nested_source = {"label": "ok"}
    source = {"items": [1, nested_source]}
    event = DomainEvent(
        event_type="user.activity",
        source="desktop",
        payload=source,
        occurred_at=datetime(2026, 11, 3, tzinfo=UTC),
    )

    nested_source["label"] = "changed"

    assert event.payload["items"] == (1, {"label": "ok"})
    with pytest.raises(TypeError):
        cast(MutableMapping[str, object], event.payload)["new"] = "value"
    with pytest.raises(TypeError):
        nested = cast(MutableMapping[str, object], event.payload["items"][1])
        nested["label"] = "changed"


@pytest.mark.parametrize(
    "payload",
    [
        {"object": object()},
        {"non_finite": float("nan")},
        {1: "non-string key"},
    ],
)
def test_domain_event_rejects_non_json_payload_values(payload: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        DomainEvent(
            event_type="activity",
            source="test",
            payload=cast(Mapping[str, object], payload),
        )


def test_domain_event_rejects_cyclic_payloads() -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic

    with pytest.raises(ValueError, match="cyclic"):
        DomainEvent(event_type="activity", source="test", payload=cyclic)


def test_domain_event_rejects_naive_timestamp_and_empty_type() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        DomainEvent(
            event_type="activity",
            source="test",
            payload={},
            occurred_at=datetime(2026, 11, 3),
        )
    with pytest.raises(ValueError, match="event_type"):
        DomainEvent(event_type=" ", source="test", payload={})


def test_behavior_snapshot_and_animation_intent_are_frozen_and_validated() -> None:
    snapshot = BehaviorSnapshot(
        physical_state="idle",
        activity="coding",
        emotion="calm",
        reaction="none",
        occurred_at=datetime(2026, 11, 3, tzinfo=UTC),
    )
    intent = AnimationIntent(
        clip_id="idle",
        priority=Priority.NORMAL,
        interrupt_policy=InterruptPolicy.ALLOW,
        loop=True,
        anchor=(0.5, 1.0),
    )

    with pytest.raises(FrozenInstanceError):
        snapshot.emotion = "angry"  # type: ignore[misc]
    assert intent.anchor == (0.5, 1.0)

    with pytest.raises(ValueError, match="anchor"):
        AnimationIntent(
            clip_id="idle",
            priority=Priority.NORMAL,
            interrupt_policy=InterruptPolicy.ALLOW,
            loop=True,
            anchor=(1.5, 0.0),
        )


def test_speech_request_has_correlation_id_and_normalizes_styles() -> None:
    request_id = new_request_id()
    request = SpeechRequest(
        request_id=request_id,
        text="Hello.",
        voice_profile="default",
        style_flags={"warm", "clear"},
    )

    assert isinstance(request.request_id, UUID)
    assert request.style_flags == frozenset({"warm", "clear"})
    with pytest.raises(FrozenInstanceError):
        request.text = "Changed"  # type: ignore[misc]

    with pytest.raises(ValueError, match="text"):
        SpeechRequest(request_id=request_id, text=" ")


def test_speech_request_rejects_string_instead_of_style_set() -> None:
    with pytest.raises(TypeError, match="set"):
        SpeechRequest(
            request_id=new_request_id(),
            text="Hello.",
            style_flags="warm",  # type: ignore[arg-type]
        )
