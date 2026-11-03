from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from daemon_reborn.ui.f04 import (
    SettingsPanel,
    SettingsStore,
    SpeechBubble,
    UiSettings,
    is_quiet_at,
)
from daemon_reborn.ui.pet import PetWindow


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    result = app if isinstance(app, QApplication) else QApplication([])
    yield result
    result.quit()


def test_settings_store_defaults_and_round_trip(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)
    store = SettingsStore(settings)

    assert store.load() == UiSettings()
    value = UiSettings(
        quiet_enabled=True,
        quiet_start="22:00",
        quiet_end="07:00",
        quiet_timezone="UTC",
        speech_enabled=True,
        mute=True,
        reduced_motion=True,
        privacy_mode=True,
    )
    assert store.save(value)
    assert (
        SettingsStore(QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)).load()
        == value
    )


def test_quiet_hours_support_overnight_and_timezone() -> None:
    settings = UiSettings(
        quiet_enabled=True, quiet_start="22:00", quiet_end="07:00", quiet_timezone="UTC"
    )

    assert is_quiet_at(settings, datetime(2026, 1, 1, 23, tzinfo=UTC))
    assert is_quiet_at(settings, datetime(2026, 1, 2, 6, tzinfo=UTC))
    assert not is_quiet_at(settings, datetime(2026, 1, 2, 12, tzinfo=UTC))


def test_invalid_quiet_hours_fall_back_to_safe_defaults(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "bad.ini"), QSettings.Format.IniFormat)
    settings.setValue("ui/v1/quietEnabled", True)
    settings.setValue("ui/v1/quietStart", "not-a-time")
    settings.setValue("ui/v1/quietEnd", "07:00")
    settings.sync()

    assert SettingsStore(settings).load() == UiSettings()


def test_settings_panel_has_accessible_controls_and_reset(
    qapp: QApplication, tmp_path: Path
) -> None:
    store = SettingsStore(QSettings(str(tmp_path / "panel.ini"), QSettings.Format.IniFormat))
    panel = SettingsPanel(store)

    assert panel.accessibleName() == "Daemon Reborn settings"
    assert panel.speech.accessibleName() == "Enable speech"
    assert panel.privacy.accessibleName() == "Privacy mode"
    panel.speech.setChecked(True)
    panel.save_button.click()
    assert store.load().speech_enabled
    panel.reset_button.click()
    assert not store.load().speech_enabled
    assert store.load().privacy_mode
    panel.close()


def test_speech_bubble_is_passive_and_taskbar_safe(qapp: QApplication) -> None:
    pet = PetWindow()
    pet.move(100, 100)
    bubble = SpeechBubble()
    bubble.show_for_pet(pet, "Status")
    available = qapp.primaryScreen().availableGeometry()

    assert bubble.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert bubble.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert available.contains(bubble.frameGeometry().topLeft())
    assert bubble.accessibleName() == "Daemon Reborn speech bubble"

    bubble.close()
    pet.shutdown()
