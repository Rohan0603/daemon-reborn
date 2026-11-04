"""Deterministic logical-coordinate pet physics independent of rendering."""

from __future__ import annotations

from dataclasses import dataclass
from math import copysign


@dataclass(frozen=True, slots=True)
class Vec2:
    x: float
    y: float

    def __add__(self, other: Vec2) -> Vec2:
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vec2) -> Vec2:
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Vec2:
        return Vec2(self.x * scalar, self.y * scalar)


@dataclass(frozen=True, slots=True)
class PhysicsBounds:
    left: float
    top: float
    right: float
    bottom: float

    def normalized(self) -> PhysicsBounds:
        return PhysicsBounds(
            min(self.left, self.right),
            min(self.top, self.bottom),
            max(self.left, self.right),
            max(self.top, self.bottom),
        )


@dataclass(frozen=True, slots=True)
class PhysicsConfig:
    gravity: float = 1800.0
    chase_speed: float = 240.0
    max_delta: float = 0.12
    substep: float = 1.0 / 120.0

    def __post_init__(self) -> None:
        if self.gravity < 0.0 or self.chase_speed < 0.0:
            raise ValueError("gravity and chase_speed must be non-negative")
        if self.max_delta <= 0.0 or self.substep <= 0.0:
            raise ValueError("max_delta and substep must be positive")


class PetPhysics:
    """Fixed-step pet motion with drag, gravity, chase and safe perimeter clamps."""

    def __init__(
        self,
        position: Vec2,
        size: Vec2,
        bounds: PhysicsBounds,
        config: PhysicsConfig | None = None,
    ) -> None:
        self.size = Vec2(max(0.0, size.x), max(0.0, size.y))
        self.config = config or PhysicsConfig()
        self.position = position
        self.velocity = Vec2(0.0, 0.0)
        self.bounds = bounds.normalized()
        self._drag_offset: Vec2 | None = None
        self._clamp_position()

    @property
    def is_dragging(self) -> bool:
        return self._drag_offset is not None

    def set_bounds(self, bounds: PhysicsBounds) -> None:
        self.bounds = bounds.normalized()
        self._clamp_position()

    def set_position(self, position: Vec2) -> None:
        self.position = position
        self._clamp_position()

    def begin_drag(self, pointer: Vec2) -> None:
        self._drag_offset = pointer - self.position
        self.velocity = Vec2(0.0, 0.0)

    def drag_to(self, pointer: Vec2) -> None:
        if self._drag_offset is None:
            return
        self.position = pointer - self._drag_offset
        self.velocity = Vec2(0.0, 0.0)
        self._clamp_position()

    def release(self) -> None:
        self._drag_offset = None

    def step(self, delta_seconds: float, target: Vec2 | None = None) -> None:
        """Advance motion with bounded fixed substeps; invalid time is ignored."""
        if self.is_dragging or delta_seconds <= 0.0:
            return
        remaining = min(delta_seconds, self.config.max_delta)
        while remaining > 0.0:
            dt = min(remaining, self.config.substep)
            self._step_once(dt, target)
            remaining -= dt

    def _step_once(self, dt: float, target: Vec2 | None) -> None:
        if target is not None:
            direction = target.x - (self.position.x + self.size.x / 2.0)
            max_move = self.config.chase_speed * dt
            if abs(direction) <= max_move:
                self.position = Vec2(self.position.x + direction, self.position.y)
                self.velocity = Vec2(0.0, self.velocity.y)
            else:
                self.velocity = Vec2(copysign(self.config.chase_speed, direction), self.velocity.y)
        self.velocity = Vec2(self.velocity.x, self.velocity.y + self.config.gravity * dt)
        self.position = self.position + self.velocity * dt
        self._clamp_position()

    def _clamp_position(self) -> None:
        bounds = self.bounds
        max_x = max(bounds.left, bounds.right - self.size.x)
        max_y = max(bounds.top, bounds.bottom - self.size.y)
        x = min(max(self.position.x, bounds.left), max_x)
        y = min(max(self.position.y, bounds.top), max_y)
        hit_x = x != self.position.x
        hit_floor = y == max_y and self.velocity.y > 0.0
        hit_ceiling = y == bounds.top and self.velocity.y < 0.0
        self.position = Vec2(x, y)
        self.velocity = Vec2(
            0.0 if hit_x else self.velocity.x,
            0.0 if hit_floor or hit_ceiling else self.velocity.y,
        )
