"""Desktop application lifecycle and owned UI objects."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from daemon_reborn.ui.pet import PetWindow
from daemon_reborn.ui.tray import TrayController

logger = logging.getLogger(__name__)


class DesktopApplication:
    """Coordinate the pet window, tray, and clean application exit."""

    def __init__(self, qt_application: QApplication) -> None:
        self.qt_application = qt_application
        self.qt_application.setQuitOnLastWindowClosed(False)
        self.pet_window = PetWindow()
        self._settings_dialog: QMessageBox | None = None
        self.tray = TrayController(
            self.pet_window,
            on_settings=self.show_settings,
            on_exit=self.shutdown,
        )

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
        self.tray.hide()
        self.pet_window.shutdown()
        if self._settings_dialog is not None:
            self._settings_dialog.close()
        self.qt_application.quit()
