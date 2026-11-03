"""Privacy-first M1 bubble/settings state and small Qt controls."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time
from enum import StrEnum
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ProviderStatus(StrEnum):
    UNCONFIGURED = "UNCONFIGURED"
    CONNECTING = "CONNECTING"
    READY = "READY"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class UiSettings:
    """Only non-sensitive, user-facing preferences are stored."""

    quiet_enabled: bool = False
    quiet_start: str | None = None
    quiet_end: str | None = None
    quiet_timezone: str = "system"
    speech_enabled: bool = False
    mute: bool = False
    reduced_motion: bool = False
    privacy_mode: bool = True
    bubble_visible: bool = True

    def validated(self) -> UiSettings:
        if self.quiet_enabled:
            _parse_time(self.quiet_start)
            _parse_time(self.quiet_end)
            validate_timezone(self.quiet_timezone)
        return replace(self)


_PREFIX: Final = "ui/v1/"


class SettingsStore:
    """Versioned QSettings adapter with safe defaults and status checking."""

    def __init__(self, settings: QSettings) -> None:
        self.settings = settings

    def load(self) -> UiSettings:
        try:
            value = UiSettings(
                quiet_enabled=_as_bool(self.settings.value(_PREFIX + "quietEnabled", False)),
                quiet_start=_as_optional_string(self.settings.value(_PREFIX + "quietStart")),
                quiet_end=_as_optional_string(self.settings.value(_PREFIX + "quietEnd")),
                quiet_timezone=str(self.settings.value(_PREFIX + "quietTimezone", "system")),
                speech_enabled=_as_bool(self.settings.value(_PREFIX + "speechEnabled", False)),
                mute=_as_bool(self.settings.value(_PREFIX + "mute", False)),
                reduced_motion=_as_bool(self.settings.value(_PREFIX + "reducedMotion", False)),
                privacy_mode=_as_bool(self.settings.value(_PREFIX + "privacyMode", True)),
                bubble_visible=_as_bool(self.settings.value(_PREFIX + "bubbleVisible", True)),
            )
            return value.validated()
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            return UiSettings()

    def save(self, value: UiSettings) -> bool:
        try:
            value = value.validated()
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            return False
        values = {
            "quietEnabled": value.quiet_enabled,
            "quietStart": value.quiet_start or "",
            "quietEnd": value.quiet_end or "",
            "quietTimezone": value.quiet_timezone,
            "speechEnabled": value.speech_enabled,
            "mute": value.mute,
            "reducedMotion": value.reduced_motion,
            "privacyMode": value.privacy_mode,
            "bubbleVisible": value.bubble_visible,
        }
        for key, item in values.items():
            self.settings.setValue(_PREFIX + key, item)
        self.settings.sync()
        return self.settings.status() == QSettings.Status.NoError

    def reset_user_preferences(self) -> bool:
        return self.save(UiSettings())


def validate_timezone(name: str) -> None:
    if name == "system":
        return
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {name}") from exc


def is_quiet_at(settings: UiSettings, instant: datetime) -> bool:
    """Evaluate quiet hours using local civil time, without background polling."""
    if not settings.quiet_enabled:
        return False
    validate_timezone(settings.quiet_timezone)
    local = (
        instant.astimezone()
        if settings.quiet_timezone == "system"
        else instant.astimezone(ZoneInfo(settings.quiet_timezone))
    )
    start = _parse_time(settings.quiet_start)
    end = _parse_time(settings.quiet_end)
    if start == end:
        return True
    if start < end:
        return start <= local.time() < end
    return local.time() >= start or local.time() < end


class SettingsPanel(QDialog):
    """Keyboard-accessible settings surface with no provider or sensor access."""

    def __init__(self, store: SettingsStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._settings = store.load()
        self.setWindowTitle("Daemon Reborn Settings")
        self.setModal(False)
        self.setAccessibleName("Daemon Reborn settings")
        self.setAccessibleDescription("Privacy and notification preferences")
        self.speech = self._check("Enable speech", "speech_enabled", self._settings.speech_enabled)
        self.mute = self._check("Mute output", "mute", self._settings.mute)
        self.reduced_motion = self._check(
            "Reduced motion", "reduced_motion", self._settings.reduced_motion
        )
        self.privacy = self._check("Privacy mode", "privacy_mode", self._settings.privacy_mode)
        self.timezone = QLineEdit(self._settings.quiet_timezone)
        self.timezone.setAccessibleName("Quiet-hours timezone")
        self.timezone.setAccessibleDescription("IANA timezone or system local time")
        self.save_button = QPushButton("Save")
        self.save_button.setAccessibleName("Save settings")
        self.save_button.clicked.connect(self._save)
        self.reset_button = QPushButton("Reset UI preferences")
        self.reset_button.setAccessibleName("Reset UI preferences")
        self.reset_button.clicked.connect(self._reset)
        form = QFormLayout()
        form.addRow(self.speech)
        form.addRow(self.mute)
        form.addRow(self.reduced_motion)
        form.addRow(self.privacy)
        form.addRow("Quiet-hours timezone", self.timezone)
        buttons = QVBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.reset_button)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Provider status: UNCONFIGURED"))
        layout.addLayout(form)
        layout.addLayout(buttons)

    def _check(self, label: str, name: str, checked: bool) -> QCheckBox:
        control = QCheckBox(label)
        control.setObjectName(name)
        control.setChecked(checked)
        control.setAccessibleName(label)
        control.setAccessibleDescription(f"Toggle {label.lower()}")
        control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return control

    def _save(self) -> None:
        self._settings = replace(
            self._settings,
            speech_enabled=self.speech.isChecked(),
            mute=self.mute.isChecked(),
            reduced_motion=self.reduced_motion.isChecked(),
            privacy_mode=self.privacy.isChecked(),
            quiet_timezone=self.timezone.text().strip() or "system",
        )
        self.store.save(self._settings)

    def _reset(self) -> None:
        self._settings = UiSettings()
        self.speech.setChecked(False)
        self.mute.setChecked(False)
        self.reduced_motion.setChecked(False)
        self.privacy.setChecked(True)
        self.timezone.setText("system")
        self.store.reset_user_preferences()


class SpeechBubble(QWidget):
    """Passive, focus-free status bubble anchored to the pet's current screen."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(280, 72)
        self.setAccessibleName("Daemon Reborn speech bubble")
        self.setAccessibleDescription("Passive status text; it does not take keyboard focus")
        label = QLabel(self)
        label.setObjectName("speechBubbleText")
        label.setAccessibleName("Speech bubble text")
        label.setAccessibleDescription("Passive status message")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setGeometry(self.rect().adjusted(12, 8, -12, -8))
        self._label = label

    def show_for_pet(self, pet: QWidget, text: str) -> None:
        """Place the bubble within the taskbar-safe area of the pet's screen."""
        screen = QGuiApplication.screenAt(pet.frameGeometry().center())
        screen = screen or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        pet_rect = pet.frameGeometry()
        preferred = pet_rect.topRight()
        x = preferred.x() + 12
        if x + self.width() > available.right() + 1:
            x = pet_rect.left() - self.width() - 12
        y = pet_rect.top() - self.height() - 12
        if y < available.top():
            y = pet_rect.bottom() + 12
        x = max(available.left(), min(x, available.right() - self.width() + 1))
        y = max(available.top(), min(y, available.bottom() - self.height() + 1))
        self._label.setText(text)
        self._label.setGeometry(self.rect().adjusted(12, 8, -12, -8))
        self.move(x, y)
        self.show()


def _parse_time(value: str | None) -> time:
    if not value:
        raise ValueError("quiet-hours time is required")
    return time.fromisoformat(value)


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_optional_string(value: object) -> str | None:
    text = str(value) if value is not None else ""
    return text or None
