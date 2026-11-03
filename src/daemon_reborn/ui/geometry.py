"""Logical-coordinate placement helpers for the pet window."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QSize


@dataclass(frozen=True, slots=True)
class ScreenArea:
    """A named screen's taskbar-safe area in Qt device-independent pixels."""

    name: str
    available: QRect


@dataclass(frozen=True, slots=True)
class NormalizedAnchor:
    """Pet top-left anchor as fractions of the screen's available travel range."""

    x: float
    y: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", min(1.0, max(0.0, self.x)))
        object.__setattr__(self, "y", min(1.0, max(0.0, self.y)))


def place_on_screen(screen: ScreenArea, anchor: NormalizedAnchor, size: QSize) -> QRect:
    """Place a window by normalized anchor within a screen's available geometry."""
    max_x = max(screen.available.left(), screen.available.right() - size.width() + 1)
    max_y = max(screen.available.top(), screen.available.bottom() - size.height() + 1)
    travel_x = max_x - screen.available.left()
    travel_y = max_y - screen.available.top()
    x = round(screen.available.left() + anchor.x * travel_x)
    y = round(screen.available.top() + anchor.y * travel_y)
    return QRect(QPoint(x, y), size)


def clamp_top_left(rect: QRect, available: QRect) -> tuple[int, int]:
    """Keep a window fully in the available geometry after a screen change."""
    max_x = max(available.left(), available.right() - rect.width() + 1)
    max_y = max(available.top(), available.bottom() - rect.height() + 1)
    x = min(max(rect.left(), available.left()), max_x)
    y = min(max(rect.top(), available.top()), max_y)
    return x, y


def anchor_for_position(rect: QRect, screen: ScreenArea) -> NormalizedAnchor:
    """Convert a window position to normalized placement within one screen."""
    max_x = max(screen.available.left(), screen.available.right() - rect.width() + 1)
    max_y = max(screen.available.top(), screen.available.bottom() - rect.height() + 1)
    travel_x = max_x - screen.available.left()
    travel_y = max_y - screen.available.top()
    x = 0.0 if travel_x == 0 else (rect.left() - screen.available.left()) / travel_x
    y = 0.0 if travel_y == 0 else (rect.top() - screen.available.top()) / travel_y
    return NormalizedAnchor(x, y)


def select_screen(
    screens: list[ScreenArea], preferred_name: str | None, primary: ScreenArea
) -> ScreenArea:
    """Keep the preferred display when present, otherwise recover to primary."""
    for screen in screens:
        if screen.name == preferred_name:
            return screen
    for screen in screens:
        if screen.name == primary.name:
            return screen
    return screens[0] if screens else primary
