from __future__ import annotations

from PySide6.QtCore import QRect, QSize

from daemon_reborn.ui.geometry import (
    NormalizedAnchor,
    ScreenArea,
    anchor_for_position,
    clamp_top_left,
    place_on_screen,
)


def test_anchor_places_pet_at_normalized_point_in_available_geometry() -> None:
    screen = ScreenArea("display-1", QRect(0, 40, 1920, 1040))

    result = place_on_screen(screen, NormalizedAnchor(1.0, 0.0), QSize(160, 160))

    assert result == QRect(1760, 40, 160, 160)


def test_clamp_recovers_fully_offscreen_or_partially_outside_position() -> None:
    area = QRect(0, 0, 1920, 1040)

    assert clamp_top_left(QRect(-5000, 1200, 160, 160), area) == (0, 880)
    assert clamp_top_left(QRect(1900, 20, 160, 160), area) == (1760, 20)


def test_anchor_is_clamped_to_valid_fraction() -> None:
    assert NormalizedAnchor(-0.2, 1.4) == NormalizedAnchor(0.0, 1.0)


def test_anchor_round_trips_a_dragged_position() -> None:
    screen = ScreenArea("primary", QRect(-1280, 0, 1280, 720))
    dragged = QRect(-400, 300, 160, 160)

    anchor = anchor_for_position(dragged, screen)

    assert place_on_screen(screen, anchor, QSize(160, 160)) == dragged
