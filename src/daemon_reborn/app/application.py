"""Desktop application lifecycle and owned UI objects."""

from __future__ import annotations

import logging

from PySide6.QtCore import QRect, QSettings, Qt
from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from daemon_reborn.ui.geometry import (
    NormalizedAnchor,
    ScreenArea,
    anchor_for_position,
    clamp_top_left,
    place_on_screen,
)
from daemon_reborn.ui.pet import PetWindow
from daemon_reborn.ui.tray import TrayController

logger = logging.getLogger(__name__)


class DesktopApplication:
    """Coordinate the pet window, tray, and clean application exit."""

    def __init__(
        self, qt_application: QApplication, placement_settings: QSettings | None = None
    ) -> None:
        self.qt_application = qt_application
        self.qt_application.setQuitOnLastWindowClosed(False)
        self.pet_window = PetWindow()
        self._placement_settings = placement_settings or QSettings("Daemon Reborn", "Daemon Reborn")
        self._watched_screens: list[QScreen] = []
        primary = QGuiApplication.primaryScreen()
        # Screen references are intentionally process-local.  QScreen.name() is
        # user-presentable and not guaranteed unique or stable across reconnects.
        self._placement_screen: QScreen | None = primary
        try:
            self._placement_anchor = NormalizedAnchor(
                float(str(self._placement_settings.value("ui/petAnchorX", 0.9))),
                float(str(self._placement_settings.value("ui/petAnchorY", 0.9))),
            )
        except (TypeError, ValueError):
            self._placement_anchor = NormalizedAnchor(0.9, 0.9)
        self._settings_dialog: QMessageBox | None = None
        self.tray = TrayController(
            self.pet_window,
            on_settings=self.show_settings,
            on_exit=self.shutdown,
        )
        self.pet_window.set_position_changed_callback(self._remember_pet_position)
        self.qt_application.screenAdded.connect(self._on_screen_added)
        self.qt_application.screenRemoved.connect(self._on_screen_removed)
        for screen in QGuiApplication.screens():
            self._watch_screen(screen)
        self._restore_pet_position()

    def run(self) -> int:
        """Show the shell and enter Qt's event loop, or report a missing tray."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.error("System tray is unavailable; refusing to start an inaccessible shell")
            return 1
        self.tray.show()
        self.pet_window.show()
        return self.qt_application.exec()

    def show_settings(self) -> None:
        """Show a clear placeholder until the settings UI lands in ORC-181."""
        if self._settings_dialog is not None:
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dialog = QMessageBox(
            QMessageBox.Icon.Information,
            "Daemon Reborn Settings",
            "Settings will be available in a future update.",
            QMessageBox.StandardButton.Ok,
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.finished.connect(lambda _result: setattr(self, "_settings_dialog", None))
        self._settings_dialog = dialog
        dialog.open()

    def shutdown(self) -> None:
        """Hide owned UI and request a clean Qt event-loop exit."""
        try:
            self.qt_application.screenAdded.disconnect(self._on_screen_added)
            self.qt_application.screenRemoved.disconnect(self._on_screen_removed)
        except (RuntimeError, TypeError):
            pass
        for screen in self._watched_screens:
            try:
                screen.geometryChanged.disconnect(self._on_screen_geometry_changed)
                screen.availableGeometryChanged.disconnect(self._on_screen_geometry_changed)
            except (RuntimeError, TypeError):
                pass
        self._watched_screens.clear()
        self.tray.hide()
        self.pet_window.shutdown()
        if self._settings_dialog is not None:
            self._settings_dialog.close()
        self.qt_application.quit()

    @staticmethod
    def _screen_area(screen: QScreen) -> ScreenArea:
        """Return Qt's taskbar-safe screen rectangle in device-independent pixels."""
        return ScreenArea(screen.name() or "primary", screen.availableGeometry())

    def _screen_and_area(self) -> tuple[QScreen, ScreenArea] | None:
        screens = QGuiApplication.screens()
        primary = QGuiApplication.primaryScreen()
        if not screens:
            return None
        primary = primary or screens[0]
        primary_area = self._screen_area(primary)
        if self._placement_screen in screens:
            screen = self._placement_screen
            return screen, self._screen_area(screen)
        return primary, primary_area

    def _watch_screen(self, screen: QScreen) -> None:
        if screen in self._watched_screens:
            return
        screen.geometryChanged.connect(self._on_screen_geometry_changed)
        screen.availableGeometryChanged.connect(self._on_screen_geometry_changed)
        self._watched_screens.append(screen)

    def _on_screen_added(self, screen: QScreen) -> None:
        self._watch_screen(screen)
        self._restore_pet_position()

    def _on_screen_removed(self, screen: QScreen) -> None:
        try:
            screen.geometryChanged.disconnect(self._on_screen_geometry_changed)
            screen.availableGeometryChanged.disconnect(self._on_screen_geometry_changed)
        except (RuntimeError, TypeError):
            pass
        if screen in self._watched_screens:
            self._watched_screens.remove(screen)
        if self._placement_screen is screen:
            self._placement_screen = None
        self._restore_pet_position()

    def _on_screen_geometry_changed(self, _geometry: QRect) -> None:
        if self.pet_window.is_dragging:
            return
        self._restore_pet_position()

    def _restore_pet_position(self, _screen: QScreen | None = None) -> None:
        selection = self._screen_and_area()
        if selection is None:
            return
        _screen, area = selection
        geometry = place_on_screen(area, self._placement_anchor, self.pet_window.size())
        self.pet_window.move(geometry.topLeft())

    def _remember_pet_position(self) -> None:
        point = self.pet_window.frameGeometry().center()
        screen = QGuiApplication.screenAt(point)
        selection = self._screen_and_area()
        if selection is None:
            return
        if screen is None:
            screen, area = selection
        else:
            area = self._screen_area(screen)
        rect = QRect(self.pet_window.pos(), self.pet_window.size())
        x, y = clamp_top_left(rect, area.available)
        self.pet_window.move(x, y)
        self._placement_screen = screen
        self._placement_anchor = anchor_for_position(self.pet_window.geometry(), area)
        self._placement_settings.setValue("ui/petAnchorX", self._placement_anchor.x)
        self._placement_settings.setValue("ui/petAnchorY", self._placement_anchor.y)
        self._placement_settings.sync()
        if self._placement_settings.status() != QSettings.Status.NoError:
            logger.warning("Unable to persist pet placement; retaining the anchor in memory")
