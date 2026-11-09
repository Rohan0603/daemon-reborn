"""Pure deterministic mapping from behavior snapshots to sprite intents."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from daemon_reborn.domain.behavior import BehaviorPolicy
from daemon_reborn.domain.contracts import (
    AnimationIntent,
    BehaviorSnapshot,
    InterruptPolicy,
    Priority,
)

IDLE_CLIP_ID = "idle"
MOUTH_POSES = frozenset({"closed", "open", "round", "smile", "frown"})
_CLIP_IDS = frozenset(
    {
        "idle",
        "chase",
        "fall",
        "drag",
        "thinking",
        "speaking",
        "neutral",
        "happy",
        "sad",
        "surprised",
        "celebrate",
        "disappointed",
    }
)
_PHYSICAL_CLIPS = frozenset({"chase", "fall", "drag"})
_REACTION_CLIPS = frozenset({"surprised", "celebrate", "disappointed"})
_ACTIVITY_CLIPS = frozenset({"thinking", "speaking"})
_EMOTION_CLIPS = frozenset({"neutral", "happy", "sad"})
_VALID_DIMENSIONS = {
    "physical_state": frozenset({"idle", "chase", "fall", "drag"}),
    "activity": frozenset({"idle", "thinking", "speaking"}),
    "emotion": frozenset({"neutral", "happy", "sad"}),
    "reaction": frozenset({"none", "surprised", "celebrate", "disappointed"}),
}


@dataclass(frozen=True, slots=True)
class MouthOverlay:
    """Validated authored mouth-pose ID; it is not an animation clip path."""

    pose_id: str

    def __post_init__(self) -> None:
        if self.pose_id not in MOUTH_POSES:
            raise ValueError("unknown mouth pose")


def resolve(
    snapshot: BehaviorSnapshot,
    available_clip_ids: Iterable[str],
    previous_generation: int,
    policy: BehaviorPolicy,
    diagnostic: Callable[[str], None] | None = None,
) -> AnimationIntent:
    """Resolve one snapshot without I/O, randomness, or asset-name interpretation.

    Precedence is physical motion, bounded reaction, activity/speech, emotion,
    then idle. Unknown snapshot labels and unavailable selected clips fail closed
    to the packaged idle clip.
    """

    if not isinstance(snapshot, BehaviorSnapshot):
        raise TypeError("snapshot must be BehaviorSnapshot")
    if not isinstance(policy, BehaviorPolicy):
        raise TypeError("policy must be BehaviorPolicy")
    _validate_generation(previous_generation)
    raw_available = tuple(available_clip_ids)
    available = frozenset(
        clip_id for clip_id in raw_available if isinstance(clip_id, str) and clip_id in _CLIP_IDS
    )
    selected = _select_clip(snapshot)
    if selected == IDLE_CLIP_ID and not _snapshot_is_valid(snapshot):
        _emit_diagnostic(diagnostic, "invalid_snapshot")
    if not available:
        _emit_diagnostic(diagnostic, "empty_catalog" if not raw_available else "invalid_catalog")
    elif selected not in available:
        _emit_diagnostic(diagnostic, "unavailable_clip")
    clip_id = selected if selected in available else IDLE_CLIP_ID
    return AnimationIntent(
        clip_id=clip_id,
        priority=Priority.NORMAL,
        interrupt_policy=InterruptPolicy.ALLOW,
        loop=clip_id not in _REACTION_CLIPS,
    )


def resolve_mouth_overlay(pose_id: str | None) -> MouthOverlay | None:
    """Validate an authored mouth pose independently from the base clip."""

    if pose_id is None:
        return None
    return MouthOverlay(pose_id)


def is_generation_current(generation: int, previous_generation: int) -> bool:
    """Return whether a completion/cancellation callback is not stale."""

    _validate_generation(generation)
    _validate_generation(previous_generation)
    return generation == previous_generation


def _select_clip(snapshot: BehaviorSnapshot) -> str:
    values = {
        "physical_state": snapshot.physical_state,
        "activity": snapshot.activity,
        "emotion": snapshot.emotion,
        "reaction": snapshot.reaction,
    }
    if any(values[name] not in allowed for name, allowed in _VALID_DIMENSIONS.items()):
        return IDLE_CLIP_ID
    if snapshot.physical_state in _PHYSICAL_CLIPS:
        return snapshot.physical_state
    if snapshot.reaction in _REACTION_CLIPS:
        return snapshot.reaction
    if snapshot.activity in _ACTIVITY_CLIPS:
        return snapshot.activity
    if snapshot.emotion in _EMOTION_CLIPS and snapshot.emotion != "neutral":
        return snapshot.emotion
    return IDLE_CLIP_ID


def _snapshot_is_valid(snapshot: BehaviorSnapshot) -> bool:
    return all(getattr(snapshot, name) in allowed for name, allowed in _VALID_DIMENSIONS.items())


def _emit_diagnostic(diagnostic: Callable[[str], None] | None, code: str) -> None:
    if diagnostic is not None:
        diagnostic(code)


def _validate_generation(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypeError("generation must be a non-negative integer")


__all__ = [
    "IDLE_CLIP_ID",
    "MOUTH_POSES",
    "MouthOverlay",
    "is_generation_current",
    "resolve",
    "resolve_mouth_overlay",
]
