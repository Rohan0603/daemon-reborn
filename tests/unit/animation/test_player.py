import pytest

from daemon_reborn.animation.player import PlaybackMode, SpriteClip, SpriteFrame, SpritePlayer


def clip(name: str, mode: PlaybackMode = PlaybackMode.LOOP) -> SpriteClip:
    return SpriteClip.from_frames(
        name,
        [SpriteFrame("a", 0.1), SpriteFrame("b", 0.2), SpriteFrame("c", 0.3)],
        mode,
    )


def test_monotonic_trace_is_independent_of_tick_cadence() -> None:
    player = SpritePlayer([clip("idle")], fallback="idle", clock=lambda: 0.0)
    assert [player.tick(now=t).key for t in (0.0, 0.016, 0.049, 0.12, 0.33)] == [
        "a",
        "a",
        "a",
        "b",
        "c",
    ]


def test_loop_delayed_tick_wraps_without_drift() -> None:
    player = SpritePlayer([clip("idle")], fallback="idle", clock=lambda: 0.0)
    assert player.tick(now=0.6).key == "a"
    assert player.tick(now=1.2).key == "a"


def test_once_holds_last_frame_and_hold_never_restarts() -> None:
    once = SpritePlayer([clip("once", PlaybackMode.ONCE)], fallback="once", clock=lambda: 0.0)
    hold = SpritePlayer([clip("hold", PlaybackMode.HOLD)], fallback="hold", clock=lambda: 0.0)
    assert once.tick(now=1.0).key == "c"
    assert once.tick(now=10.0).key == "c"
    assert hold.tick(now=10.0).key == "c"


def test_pause_resume_and_speed_preserve_phase() -> None:
    now = [0.0]
    player = SpritePlayer([clip("idle")], fallback="idle", clock=lambda: now[0])
    now[0] = 0.15
    player.pause()
    now[0] = 5.0
    assert player.frame.key == "b"
    player.resume()
    now[0] = 5.1
    assert player.frame.key == "b"
    player.set_speed(2.0)
    now[0] = 5.2
    assert player.frame.key == "c"


def test_interruptions_increment_generation_and_stale_generation_is_ignored() -> None:
    now = [0.0]
    player = SpritePlayer([clip("idle"), clip("talk")], fallback="idle", clock=lambda: now[0])
    first = player.play("talk")
    second = player.play("idle")
    assert second > first
    assert player.interrupt(first) == second
    assert player.clip.name == "idle"
    assert player.interrupt(second) > second


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_durations_and_speed_are_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        SpriteFrame("bad", value)
    with pytest.raises(ValueError):
        SpritePlayer([clip("idle")], fallback="idle", speed=value)


def test_unknown_clip_falls_back_and_reset_is_deterministic() -> None:
    now = [4.0]
    player = SpritePlayer([clip("idle")], fallback="idle", clock=lambda: now[0])
    player.play("missing")
    assert player.clip.name == "idle"
    now[0] = 9.0
    player.reset()
    assert player.frame.key == "a"
