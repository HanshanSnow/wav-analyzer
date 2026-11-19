"""覆盖式“处理中”提示：旋转指示器 + 文案，替代系统“未响应”观感。"""
from __future__ import annotations

from core.i18n import tf, tr
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget


class BusyOverlay(QWidget):
    """半透明遮罩。可见期间拦截鼠标操作，避免用户在重计算时改动数据。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.BusyCursor)
        self._angle = 0
        self._text = tr("处理中…")
        self._hint = ""
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._advance)
        self.hide()

    def start(self, text: str = "处理中…", hint: str = "") -> None:
        self._text = text
        self._hint = hint
        self._angle = 0
        if self.parentWidget() is not None:
            self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def set_text(self, text: str) -> None:
        self._text = text
        self.update()

    def set_hint(self, text: str) -> None:
        self._hint = text
        self.update()

    def _advance(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(250, 250, 250, 210))

        center = self.rect().center()
        radius = 24
        box = QRectF(
            center.x() - radius,
            center.y() - radius - 26,
            radius * 2,
            radius * 2,
        )
        painter.setPen(QPen(QColor("#cfd8dc"), 5))
        painter.drawEllipse(box)

        arc_pen = QPen(QColor("#1565c0"), 5)
        arc_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(arc_pen)
        painter.drawArc(box, int(-self._angle * 16), int(110 * 16))

        font = QFont(painter.font())
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#263238"))
        painter.drawText(
            QRectF(0, center.y() + radius - 12, self.width(), 28),
            Qt.AlignHCenter | Qt.AlignTop,
            self._text,
        )

        if self._hint:
            hint_font = QFont(painter.font())
            hint_font.setPointSize(9)
            hint_font.setBold(False)
            painter.setFont(hint_font)
            painter.setPen(QColor("#607d8b"))
            painter.drawText(
                QRectF(0, center.y() + radius + 16, self.width(), 26),
                Qt.AlignHCenter | Qt.AlignTop,
                self._hint,
            )
