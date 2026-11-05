import sys
from ctypes import wintypes

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


class PetWindow(QWidget):
    clicked = Signal()
    drag_started = Signal()
    drag_to = Signal(QPoint)
    drag_finished = Signal()
    menu_requested = Signal(QPoint)

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setWindowTitle("chuh0o")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._frame = QPixmap()
        self._press: QPoint | None = None
        self._offset = QPoint()
        self._dragging = False

    def set_frame(self, pixmap: QPixmap) -> None:
        self._frame = pixmap
        self.setFixedSize(pixmap.size())
        # A native region allows clicks on transparent surroundings to reach other apps.
        self.setMask(pixmap.mask())
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawPixmap(0, 0, self._frame)

    @property
    def pointer_pressed(self) -> bool:
        return self._press is not None

    @property
    def drag_offset(self) -> QPoint:
        return QPoint(self._offset)

    def rebase_pointer(self, previous_origin: QPoint) -> None:
        if self.pointer_pressed:
            self._offset += previous_origin - self.pos()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._offset = self._press - self.pos()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press is None:
            return
        point = event.globalPosition().toPoint()
        if (
            not self._dragging
            and (point - self._press).manhattanLength() >= QApplication.startDragDistance()
        ):
            self._dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.drag_started.emit()
        if self._dragging:
            self.drag_to.emit(point - self._offset)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._press is not None:
            dragging = self._dragging
            if dragging:
                self.drag_to.emit(event.globalPosition().toPoint() - self._offset)
            self.cancel_pointer()
            if dragging:
                self.drag_finished.emit()
            else:
                self.clicked.emit()

    def cancel_pointer(self) -> None:
        self._press = None
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0021:  # WM_MOUSEACTIVATE: deliver click without activation.
                return True, 3  # MA_NOACTIVATE
        return super().nativeEvent(event_type, message)

    def closeEvent(self, event) -> None:
        event.ignore()  # The tray owns application lifetime.
