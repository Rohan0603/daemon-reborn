"""Small transparent placeholder character window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget


class PetWindow(QWidget):
    """A passive, compact topmost window with a minimal original placeholder face."""

    def __init__(self) -> None:
        super().__init__()
        self._shutdown = False
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(160, 160)

    @property
    def is_shutdown(self) -> bool:
        """Whether the application has permanently closed this window."""
        return self._shutdown

    def shutdown(self) -> None:
        """Allow the close event through during application shutdown."""
        self._shutdown = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._shutdown:
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#77b9a5"))
        painter.drawEllipse(12, 12, 136, 136)
        painter.setBrush(QColor("#19352d"))
        painter.drawEllipse(48, 58, 12, 14)
        painter.drawEllipse(100, 58, 12, 14)
        painter.drawRoundedRect(68, 96, 24, 6, 3, 3)
        painter.end()
