"""Tests for the minimal desktop shell lifecycle."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from importlib.util import find_spec
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import QPoint, QRect, QSettings, Qt
from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication([])
    yield app
    app.quit()


def test_desktop_shell_application_module_exists() -> None:
    assert find_spec("daemon_reborn.app.application") is not None


def test_pet_window_is_small_translucent_and_does_not_take_focus(qapp: QApplication) -> None:
    from daemon_reborn.ui.pet import PetWindow

    pet = PetWindow()

    assert pet.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert pet.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    flags = pet.windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert pet.width() < qapp.primaryScreen().geometry().width()
    assert pet.height() < qapp.primaryScreen().geometry().height()
    assert pet.mask().contains(pet.rect().center())
    assert not pet.mask().contains(pet.rect().topLeft())

    pet.shutdown()


def test_close_hides_pet_but_shutdown_closes_it(qapp: QApplication) -> None:
    from daemon_reborn.ui.pet import PetWindow

    pet = PetWindow()
    pet.show()
    pet.close()

    assert not pet.isVisible()
    assert not pet.is_shutdown

    pet.show()
    pet.shutdown()

    assert not pet.isVisible()
    assert pet.is_shutdown


def test_pet_drag_moves_window_and_notifies_placement_owner(qapp: QApplication) -> None:
    from daemon_reborn.ui.pet import PetWindow

    pet = PetWindow()
    pet.move(100, 100)
    changed: list[bool] = []
    pet.set_position_changed_callback(lambda: changed.append(True))
    pet.show()
    qapp.processEvents()
    original = pet.pos()

    QTest.mousePress(pet, Qt.MouseButton.LeftButton, pos=QPoint(80, 80))
    QTest.mouseMove(pet, QPoint(105, 95), 10)
    QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=QPoint(105, 95))

    assert pet.pos() != original
    assert changed == [True]
    pet.shutdown()


def test_tray_actions_reopen_pet_open_settings_and_request_exit(qapp: QApplication) -> None:
    from daemon_reborn.ui.pet import PetWindow
    from daemon_reborn.ui.tray import TrayController

    pet = PetWindow()
    callbacks: list[str] = []
    tray = TrayController(
        pet,
        on_settings=lambda: callbacks.append("settings"),
        on_exit=lambda: callbacks.append("exit"),
    )

    pet.hide()
    tray.show_action.trigger()
    assert pet.isVisible()

    tray.settings_action.trigger()
    tray.exit_action.trigger()
    assert callbacks == ["settings", "exit"]
    assert not tray.icon.icon().isNull()

    tray.hide()
    pet.shutdown()


def test_tray_can_hide_and_restore_pet(qapp: QApplication) -> None:
    from daemon_reborn.ui.pet import PetWindow
    from daemon_reborn.ui.tray import TrayController

    pet = PetWindow()
    tray = TrayController(pet, on_settings=lambda: None, on_exit=pet.shutdown)
    pet.show()
    assert pet.isVisible()

    assert hasattr(tray, "hide_action")
    tray.hide_action.trigger()
    assert not pet.isVisible()
    tray.show_action.trigger()
    assert pet.isVisible()

    tray.hide()
    pet.shutdown()


def test_desktop_application_shutdown_hides_owned_ui(qapp: QApplication) -> None:
    from daemon_reborn.app.application import DesktopApplication

    desktop = DesktopApplication(qapp)
    desktop.pet_window.show()
    desktop.tray.show()

    desktop.tray.exit_action.trigger()

    assert not desktop.pet_window.isVisible()
    assert not desktop.tray.icon.isVisible()
    assert desktop.pet_window.is_shutdown


def test_desktop_application_persists_normalized_anchor_without_screen_identity(
    qapp: QApplication, tmp_path: Path
) -> None:
    from daemon_reborn.app.application import DesktopApplication

    settings_path = tmp_path / "placement.ini"
    settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    settings.setValue("ui/petScreen", "legacy-display-name")
    first = DesktopApplication(qapp, settings)
    first.pet_window.move(100, 100)
    first._remember_pet_position()
    saved_x = settings.value("ui/petAnchorX")
    saved_y = settings.value("ui/petAnchorY")
    assert settings.value("ui/petScreen") is None
    first.shutdown()

    second = DesktopApplication(qapp, QSettings(str(settings_path), QSettings.Format.IniFormat))

    assert second._placement_screen is qapp.primaryScreen()
    assert second._placement_anchor.x == float(saved_x)
    assert second._placement_anchor.y == float(saved_y)
    second.shutdown()


def test_screen_change_restores_anchor_after_resize_unplug_and_replug(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from daemon_reborn.app.application import DesktopApplication

    class SignalStub:
        def __init__(self) -> None:
            self._slots: list[Callable[..., None]] = []

        def connect(self, slot: Callable[..., None]) -> None:
            self._slots.append(slot)

        def disconnect(self, slot: Callable[..., None]) -> None:
            self._slots.remove(slot)

        def emit(self, *args: object) -> None:
            for slot in tuple(self._slots):
                slot(*args)

    class ScreenStub:
        def __init__(self, name: str, available: QRect) -> None:
            self._name = name
            self._available = available
            self.geometryChanged = SignalStub()
            self.availableGeometryChanged = SignalStub()

        def name(self) -> str:
            return self._name

        def availableGeometry(self) -> QRect:
            return self._available

    primary = ScreenStub("primary", QRect(0, 0, 1920, 1080))
    external = ScreenStub("external", QRect(-1280, 0, 1280, 720))
    screens = [primary, external]
    monkeypatch.setattr(QGuiApplication, "screens", staticmethod(lambda: screens))
    monkeypatch.setattr(QGuiApplication, "primaryScreen", staticmethod(lambda: primary))
    monkeypatch.setattr(
        QGuiApplication,
        "screenAt",
        staticmethod(
            lambda point: next(
                (screen for screen in screens if screen.availableGeometry().contains(point)), None
            )
        ),
    )
    settings = QSettings(str(tmp_path / "screen-change.ini"), QSettings.Format.IniFormat)
    settings.setValue("ui/petAnchorX", 0.5)
    settings.setValue("ui/petAnchorY", 0.5)

    desktop = DesktopApplication(qapp, settings)
    assert desktop.pet_window.geometry() == QRect(880, 460, 160, 160)

    # A secondary monitor may be selected for the current session, but its
    # object reference is never persisted as a restart identity.
    desktop._placement_screen = cast(QScreen, external)
    desktop._restore_pet_position()
    assert desktop.pet_window.geometry() == QRect(-720, 280, 160, 160)

    external._available = QRect(-1440, 0, 1440, 900)
    external.availableGeometryChanged.emit(external._available)
    assert desktop.pet_window.geometry() == QRect(-800, 370, 160, 160)

    screens[:] = [primary]
    desktop._on_screen_removed(cast(QScreen, external))
    assert desktop.pet_window.geometry() == QRect(880, 460, 160, 160)

    screens[:] = [primary, external]
    desktop._on_screen_added(cast(QScreen, external))
    assert desktop.pet_window.geometry() == QRect(880, 460, 160, 160)
    desktop.shutdown()


def test_screen_change_does_not_reposition_during_active_drag(qapp: QApplication) -> None:
    from daemon_reborn.app.application import DesktopApplication

    desktop = DesktopApplication(qapp)
    desktop.pet_window.move(100, 100)
    before = desktop.pet_window.pos()
    desktop.pet_window._drag_origin = QPoint(100, 100)
    desktop.pet_window._drag_pointer = QPoint(20, 20)

    desktop._on_screen_geometry_changed(QRect(0, 0, 800, 600))
    primary = qapp.primaryScreen()
    assert primary is not None
    desktop._on_screen_added(primary)
    desktop._on_screen_removed(primary)

    assert desktop.pet_window.is_dragging
    assert desktop.pet_window.pos() == before
    desktop.pet_window._drag_origin = None
    desktop.pet_window._drag_pointer = None
    desktop.shutdown()


def test_run_fails_cleanly_when_system_tray_is_unavailable(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from daemon_reborn.app.application import DesktopApplication

    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))
    desktop = DesktopApplication(qapp)

    assert desktop.run() == 1
    assert not desktop.pet_window.isVisible()
    assert not desktop.tray.icon.isVisible()


def test_run_shows_pet_and_tray_when_system_tray_is_available(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from daemon_reborn.app.application import DesktopApplication

    observed: list[tuple[bool, bool]] = []
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    desktop = DesktopApplication(qapp)

    def fake_exec(_application: QApplication) -> int:
        observed.append((desktop.pet_window.isVisible(), desktop.tray.icon.isVisible()))
        return 0

    monkeypatch.setattr(QApplication, "exec", fake_exec)

    assert desktop.run() == 0
    assert desktop.tray.icon.isVisible()
    assert observed == [(True, True)]

    desktop.shutdown()
