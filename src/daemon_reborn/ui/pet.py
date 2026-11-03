"""Small transparent placeholder character window."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCloseEvent, QColor, QMouseEvent, QPainter, QPaintEvent, QRegion
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
        self.setMask(QRegion(12, 12, 136, 136, QRegion.RegionType.Ellipse))
        self._drag_origin: QPoint | None = None
        self._drag_pointer: QPoint | None = None
        self._position_changed: Callable[[], None] | None = None

    def set_position_changed_callback(self, callback: Callable[[], None]) -> None:
        """Set the callback used to remember the screen anchor after dragging."""
        self._position_changed = callback

    @property
    def is_shutdown(self) -> bool:
        """Whether the application has permanently closed this window."""
        return self._shutdown

    @property
    def is_dragging(self) -> bool:
        """Whether a pointer drag is currently in progress."""
        return self._drag_origin is not None and self._drag_pointer is not None

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

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = self.pos()
            self._drag_pointer = event.globalPosition().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None and self._drag_pointer is not None:
            delta = event.globalPosition().toPoint() - self._drag_pointer
            self.move(self._drag_origin + delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_origin is not None:
            self._drag_origin = None
            self._drag_pointer = None
            if self._position_changed is not None:
                self._position_changed()
            event.accept()
            return
        super().mouseReleaseEvent(event)

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
