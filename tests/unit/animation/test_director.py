"""ORC-189: pure deterministic animation-director contract."""

import inspect
from datetime import UTC, datetime

import pytest

from daemon_reborn.animation.adapter import apply_intent
from daemon_reborn.animation.director import (
    MOUTH_POSES,
    MouthOverlay,
    is_generation_current,
    resolve,
    resolve_mouth_overlay,
)
from daemon_reborn.animation.player import PlaybackMode, SpriteClip, SpriteFrame, SpritePlayer
from daemon_reborn.domain.behavior import BehaviorPolicy
from daemon_reborn.domain.contracts import (
    BehaviorSnapshot,
    InterruptPolicy,
    Priority,
)


def snapshot(physical: str, activity: str, emotion: str, reaction: str) -> BehaviorSnapshot:
    return BehaviorSnapshot(
        physical_state=physical,
        activity=activity,
        emotion=emotion,
        reaction=reaction,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def policy() -> BehaviorPolicy:
    now = [0.0]
    return BehaviorPolicy(
        monotonic=lambda: now[0],
        wall_clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("physical", "activity", "emotion", "reaction", "expected"),
    [
        ("idle", "idle", "neutral", "none", "idle"),
        ("idle", "thinking", "neutral", "none", "thinking"),
        ("idle", "speaking", "neutral", "none", "speaking"),
        ("idle", "idle", "happy", "none", "happy"),
        ("idle", "idle", "sad", "none", "sad"),
        ("chase", "idle", "neutral", "none", "chase"),
        ("chase", "thinking", "neutral", "none", "chase"),
        ("chase", "speaking", "neutral", "none", "chase"),
        ("chase", "idle", "neutral", "surprised", "chase"),
        ("chase", "idle", "happy", "celebrate", "chase"),
        ("fall", "idle", "neutral", "none", "fall"),
        ("fall", "speaking", "happy", "celebrate", "fall"),
        ("drag", "idle", "neutral", "none", "drag"),
        ("drag", "speaking", "happy", "surprised", "drag"),
        ("idle", "speaking", "happy", "none", "speaking"),
        ("idle", "thinking", "sad", "none", "thinking"),
        ("idle", "idle", "neutral", "surprised", "surprised"),
        ("idle", "idle", "happy", "celebrate", "celebrate"),
        ("idle", "idle", "sad", "disappointed", "disappointed"),
        ("idle", "speaking", "happy", "celebrate", "celebrate"),
        ("idle", "thinking", "sad", "surprised", "surprised"),
        ("idle", "speaking", "sad", "disappointed", "disappointed"),
        ("idle", "idle", "neutral", "unknown", "idle"),
        ("unknown", "speaking", "happy", "none", "idle"),
    ],
)
def test_resolve_uses_deterministic_precedence(
    physical: str, activity: str, emotion: str, reaction: str, expected: str
) -> None:
    result = resolve(
        snapshot(physical, activity, emotion, reaction),
        {"idle", "chase", "fall", "drag", "thinking", "speaking", "happy", "sad",
         "surprised", "celebrate", "disappointed"},
        previous_generation=4,
        policy=policy(),
    )
    assert result.clip_id == expected
    assert result.clip_id in {
        "idle", "chase", "fall", "drag", "thinking", "speaking", "happy", "sad",
        "surprised", "celebrate", "disappointed",
    }


def test_resolve_falls_back_to_packaged_idle_for_empty_or_invalid_catalog() -> None:
    state = snapshot("idle", "speaking", "happy", "celebrate")
    diagnostics: list[str] = []
    assert resolve(state, set(), 0, policy(), diagnostic=diagnostics.append).clip_id == "idle"
    assert resolve(
        state,
        {"C:\\user\\arbitrary.png", "tool_output"},
        0,
        policy(),
        diagnostic=diagnostics.append,
    ).clip_id == "idle"
    assert diagnostics == ["empty_catalog", "invalid_catalog"]


def test_resolve_falls_back_when_selected_clip_is_unavailable() -> None:
    diagnostics: list[str] = []
    assert resolve(
        snapshot("drag", "idle", "neutral", "none"),
        {"idle", "chase"},
        0,
        policy(),
        diagnostic=diagnostics.append,
    ).clip_id == "idle"
    assert diagnostics == ["unavailable_clip"]


def test_resolve_reports_invalid_snapshot_without_exposing_input() -> None:
    diagnostics: list[str] = []
    result = resolve(
        snapshot("user-path-secret", "speaking", "neutral", "none"),
        {"idle", "speaking"},
        0,
        policy(),
        diagnostic=diagnostics.append,
    )
    assert result.clip_id == "idle"
    assert diagnostics == ["invalid_snapshot"]


def test_apply_intent_rejects_stale_generation_before_player_mutation() -> None:
    player = SpritePlayer(
        [
            SpriteClip.from_frames("idle", [SpriteFrame("idle", 1.0)], PlaybackMode.LOOP),
            SpriteClip.from_frames("speaking", [SpriteFrame("speaking", 1.0)], PlaybackMode.LOOP),
        ],
        fallback="idle",
        clock=lambda: 0.0,
    )
    current = player.play("speaking")
    stale = current - 1
    intent = resolve(snapshot("idle", "speaking", "neutral", "none"), {"idle", "speaking"}, stale, policy())

    assert apply_intent(player, intent, stale) is None
    assert player.clip.name == "speaking"
    assert player.generation == current


def test_apply_intent_advances_current_generation() -> None:
    player = SpritePlayer(
        [
            SpriteClip.from_frames("idle", [SpriteFrame("idle", 1.0)], PlaybackMode.LOOP),
            SpriteClip.from_frames("speaking", [SpriteFrame("speaking", 1.0)], PlaybackMode.LOOP),
        ],
        fallback="idle",
        clock=lambda: 0.0,
    )
    intent = resolve(snapshot("idle", "speaking", "neutral", "none"), {"idle", "speaking"}, 0, policy())

    next_generation = apply_intent(player, intent, 0)

    assert next_generation == 1
    assert player.clip.name == "speaking"


def test_resolve_is_idempotent_and_does_not_mutate_policy() -> None:
    source = snapshot("idle", "speaking", "happy", "none")
    behavior_policy = policy()
    first = resolve(source, {"idle", "speaking", "happy"}, 7, behavior_policy)
    second = resolve(source, {"idle", "speaking", "happy"}, 7, behavior_policy)
    assert first == second


@pytest.mark.parametrize("generation, previous, expected", [(0, 0, True), (4, 4, True), (3, 4, False)])
def test_generation_cancellation_rejects_stale_results(
    generation: int, previous: int, expected: bool
) -> None:
    assert is_generation_current(generation, previous) is expected


def test_mouth_overlay_is_separate_validated_allow_list() -> None:
    assert MOUTH_POSES == frozenset({"closed", "open", "round", "smile", "frown"})
    assert resolve_mouth_overlay("open") == MouthOverlay("open")
    assert resolve_mouth_overlay(None) is None
    with pytest.raises(ValueError, match="mouth pose"):
        resolve_mouth_overlay("C:\\user\\mouth.png")


@pytest.mark.parametrize("bad_generation", [-1, True, 1.5])
def test_generation_values_are_rejected(bad_generation: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        is_generation_current(bad_generation, 0)  # type: ignore[arg-type]


def test_resolver_has_no_filesystem_or_llm_execution_paths() -> None:
    source = inspect.getsource(resolve)
    assert "open(" not in source
    assert "subprocess" not in source
    assert "openai" not in source


def test_intent_policy_is_deterministic_and_bounded() -> None:
    result = resolve(snapshot("idle", "speaking", "neutral", "none"), {"idle", "speaking"}, 2, policy())
    assert result.priority is Priority.NORMAL
    assert result.interrupt_policy is InterruptPolicy.ALLOW
    assert result.loop is True
