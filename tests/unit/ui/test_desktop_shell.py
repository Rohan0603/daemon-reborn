"""Tests for the minimal desktop shell lifecycle."""

from __future__ import annotations

import os
from collections.abc import Iterator
from importlib.util import find_spec

import pytest
from PySide6.QtCore import Qt
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
