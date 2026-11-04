"""Deterministic, monotonic-time sprite playback state."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from time import monotonic


class PlaybackMode(StrEnum):
    LOOP = "loop"
    ONCE = "once"
    HOLD = "hold"


@dataclass(frozen=True, slots=True)
class SpriteFrame:
    """A frame identifier and its display duration in seconds."""

    key: str
    duration: float

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("frame key must not be empty")
        if not isfinite(self.duration) or self.duration <= 0.0:
            raise ValueError("frame duration must be finite and positive")


@dataclass(frozen=True, slots=True)
class SpriteClip:
    """Immutable clip definition consumed by :class:`SpritePlayer`."""

    name: str
    frames: tuple[SpriteFrame, ...]
    mode: PlaybackMode = PlaybackMode.LOOP

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("clip name must not be empty")
        if not self.frames:
            raise ValueError("clip must contain at least one frame")

    @classmethod
    def from_frames(
        cls,
        name: str,
        frames: Sequence[SpriteFrame],
        mode: PlaybackMode = PlaybackMode.LOOP,
    ) -> SpriteClip:
        return cls(name, tuple(frames), mode)


class SpritePlayer:
    """Advance a clip from monotonic timestamps, independent of timer cadence."""

    def __init__(
        self,
        clips: Sequence[SpriteClip],
        *,
        fallback: str,
        clock: Callable[[], float] = monotonic,
        speed: float = 1.0,
    ) -> None:
        self._clips = {clip.name: clip for clip in clips}
        if fallback not in self._clips:
            raise ValueError("fallback clip must be present")
        self._fallback = fallback
        self._clock = clock
        self._speed = self._validate_speed(speed)
        self._clip = self._clips[fallback]
        self._started_at = self._clock()
        self._paused_at: float | None = None
        self._paused_elapsed = 0.0
        self._generation = 0
        self._stopped = False

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def clip(self) -> SpriteClip:
        return self._clip

    @property
    def paused(self) -> bool:
        return self._paused_at is not None

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def frame(self) -> SpriteFrame:
        return self._frame_at(self._elapsed(self._clock()))

    def set_speed(self, speed: float) -> None:
        speed = self._validate_speed(speed)
        now = self._clock()
        elapsed = self._elapsed(now)
        self._started_at = now - elapsed / speed
        self._speed = speed

    def play(self, clip_name: str, *, now: float | None = None) -> int:
        """Interrupt the current clip and start a fresh generation."""
        self._clip = self._clips.get(clip_name, self._clips[self._fallback])
        self._generation += 1
        self._stopped = False
        self._paused_at = None
        self._paused_elapsed = 0.0
        self._started_at = self._clock() if now is None else self._validate_timestamp(now)
        return self._generation

    def interrupt(self, generation: int, *, fallback: bool = True) -> int:
        """Ignore stale callers and optionally return to the fallback clip."""
        if generation != self._generation:
            return self._generation
        if fallback:
            self.play(self._fallback)
        return self._generation

    def pause(self, *, now: float | None = None) -> None:
        if self._paused_at is None:
            paused_at = self._clock() if now is None else self._validate_timestamp(now)
            self._paused_elapsed = max(0.0, (paused_at - self._started_at) * self._speed)
            self._paused_at = paused_at

    def resume(self, *, now: float | None = None) -> None:
        if self._paused_at is not None:
            resumed = self._clock() if now is None else self._validate_timestamp(now)
            self._started_at = resumed - self._paused_elapsed / self._speed
            self._paused_at = None

    def reset(self, *, now: float | None = None) -> None:
        self._generation += 1
        self._started_at = self._clock() if now is None else self._validate_timestamp(now)
        self._paused_at = None
        self._paused_elapsed = 0.0
        self._stopped = False

    def tick(self, *, now: float | None = None) -> SpriteFrame:
        """Return the frame at ``now``; delayed ticks skip stale frames safely."""
        timestamp = self._clock() if now is None else now
        return self._frame_at(self._elapsed(timestamp))

    def _elapsed(self, now: float) -> float:
        now = self._validate_timestamp(now)
        if self._paused_at is not None:
            return self._paused_elapsed
        return max(0.0, (now - self._started_at) * self._speed)

    def _frame_at(self, elapsed: float) -> SpriteFrame:
        frames = self._clip.frames
        total = sum(frame.duration for frame in frames)
        if self._clip.mode is PlaybackMode.LOOP:
            phase = elapsed % total
        else:
            phase = min(elapsed, total)
            if phase == total:
                self._stopped = self._clip.mode is PlaybackMode.ONCE
                return frames[-1]
        cursor = 0.0
        for frame in frames:
            cursor += frame.duration
            if phase < cursor:
                return frame
        return frames[-1]

    @staticmethod
    def _validate_timestamp(timestamp: float) -> float:
        if not isfinite(timestamp):
            raise ValueError("timestamp must be finite")
        return timestamp

    @staticmethod
    def _validate_speed(speed: float) -> float:
        if not isfinite(speed) or speed <= 0.0:
            raise ValueError("speed must be finite and positive")
        return speed
