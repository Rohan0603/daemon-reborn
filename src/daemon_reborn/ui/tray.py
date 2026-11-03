"""System tray controls for the desktop shell."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon, QWidget

from daemon_reborn.ui.pet import PetWindow


class TrayController:
    """Own the tray icon and its show, settings, and exit actions."""

    def __init__(
        self,
        pet_window: PetWindow,
        *,
        on_settings: Callable[[], None],
        on_exit: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        self.icon = QSystemTrayIcon(
            QIcon(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)),
            parent,
        )
        self.menu = QMenu(parent)
        self.show_action = self.menu.addAction("Show pet")
        self.hide_action = self.menu.addAction("Hide pet")
        self.settings_action = self.menu.addAction("Settings…")
        self.menu.addSeparator()
        self.exit_action = self.menu.addAction("Exit")
        self.show_action.triggered.connect(pet_window.show)
        self.hide_action.triggered.connect(pet_window.hide)
        self.settings_action.triggered.connect(on_settings)
        self.exit_action.triggered.connect(on_exit)
        self.icon.setToolTip("Daemon Reborn")
        self.icon.setContextMenu(self.menu)

    def show(self) -> None:
        """Make the tray icon available."""
        self.icon.show()

    def hide(self) -> None:
        """Remove the tray icon during application shutdown."""
        self.icon.hide()
