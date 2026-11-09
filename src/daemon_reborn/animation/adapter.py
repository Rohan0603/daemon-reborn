"""Generation-safe application of domain animation intents to the player."""

from __future__ import annotations

from daemon_reborn.animation.director import _validate_generation
from daemon_reborn.animation.player import PlaybackMode, SpritePlayer
from daemon_reborn.domain.contracts import AnimationIntent


def apply_intent(
    player: SpritePlayer,
    intent: AnimationIntent,
    expected_generation: int,
) -> int | None:
    """Apply an intent only if it was resolved from the player's current generation.

    ``None`` means the intent was stale and the player was left untouched. The
    player performs the same check atomically at its mutation boundary.
    """

    if not isinstance(player, SpritePlayer):
        raise TypeError("player must be SpritePlayer")
    if not isinstance(intent, AnimationIntent):
        raise TypeError("intent must be AnimationIntent")
    _validate_generation(expected_generation)
    return player.play_if_current(
        intent.clip_id,
        expected_generation,
        mode=PlaybackMode.LOOP if intent.loop else PlaybackMode.ONCE,
        interrupt_policy=intent.interrupt_policy,
    )


__all__ = ["apply_intent"]
