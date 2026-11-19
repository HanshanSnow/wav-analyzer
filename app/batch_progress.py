"""批量处理进度遮罩：虚化主窗口 + 居中进度卡片。

为什么不用 ``QDialog.exec()``：模态对话框会跑自己的事件循环，看起来“不卡”，
但一是不好做真正的背景虚化（对话框只盖住自己那块），二是取消逻辑容易和
工作线程的生命周期缠在一起。这里用普通 QWidget 覆盖主窗口，配合
QThread + 信号回主线程，界面始终可响应。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame, QGraphicsBlurEffect, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from core.batch import BatchResult, run_batch


class BatchWorker(QThread):
    """在工作线程跑整条流水线；只在主线程改界面。"""

    staged = Signal(str, int, int, str, float)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, files, steps, output_dir, parent=None, calibration=None):
        super().__init__(parent)
        self._files = list(files)
        self._steps = list(steps)
        self._output_dir = str(output_dir or "")
        # 声学校准：由主窗口在启动前取好，不在这里读界面
        self._calibration = calibration
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:  # noqa: D401 - QThread 入口
        try:
            result: BatchResult = run_batch(
                self._files, self._steps,
                output_dir=self._output_dir or None,
                calibration=self._calibration,
                progress=lambda stage, index, total, name, fraction:
                    self.staged.emit(stage, index, total, name, fraction),
                should_cancel=lambda: self._cancel,
            )
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class BatchProgressOverlay(QWidget):
    """覆盖主窗口的进度层：背景是主窗口的模糊快照，中间是进度卡片。"""

    cancelled = Signal()

    CARD_WIDTH = 520

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.BusyCursor)
        self._backdrop = QLabel(self)
        self._backdrop.setScaledContents(True)
        self._backdrop.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        blur = QGraphicsBlurEffect(self._backdrop)
        blur.setBlurRadius(18)
        blur.setBlurHints(QGraphicsBlurEffect.QualityHint)
        self._backdrop.setGraphicsEffect(blur)

        self._card = QFrame(self)
        self._card.setObjectName("batchCard")
        self._card.setStyleSheet(
            "#batchCard { background: #ffffff; border: 1px solid #d5dde5;"
            " border-radius: 12px; }")
        shadow = QGraphicsDropShadowEffect(self._card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(15, 23, 42, 70))
        self._card.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(10)

        self._title = QLabel("正在批量处理")
        self._title.setStyleSheet("font-size: 13pt; font-weight: 600; color: #16232f;")
        layout.addWidget(self._title)

        self._line_import = QLabel("正在导入文件：—")
        self._line_process = QLabel("正在处理文件：—")
        for label in (self._line_import, self._line_process):
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.NoTextInteraction)
            layout.addWidget(label)

        self._bar = QProgressBar()
        self._bar.setRange(0, 1000)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(10)
        self._bar.setStyleSheet(
            "QProgressBar { background: #e8eef4; border: none; border-radius: 5px; }"
            "QProgressBar::chunk { background: #1565c0; border-radius: 5px; }")
        layout.addWidget(self._bar)

        footer = QHBoxLayout()
        self._percent = QLabel("0%")
        self._percent.setStyleSheet("color: #546e7a;")
        self._cancel = QPushButton("取消")
        self._cancel.setFixedWidth(84)
        self._cancel.clicked.connect(self._request_cancel)
        footer.addWidget(self._percent)
        footer.addStretch(1)
        footer.addWidget(self._cancel)
        layout.addLayout(footer)

        self._total = 0
        self._import_name = ""
        self._process_name = ""
        self._stage = ""
        self.hide()

    # ------------------------------------------------------------ 生命周期
    def start(self, total: int) -> None:
        self._total = max(1, int(total))
        self._import_name = ""
        self._process_name = ""
        self._stage = ""
        self._cancel.setEnabled(True)
        self._cancel.setText("取消")
        self._bar.setValue(0)
        self._percent.setText("0%")
        self._line_import.setText("正在导入文件：—")
        self._line_process.setText("正在处理文件：—")
        self._reset_styles()
        self._capture_backdrop()
        self.setGeometry(self.parentWidget().rect())
        self._place_card()
        self.raise_()
        self.show()

    def finish(self) -> None:
        self.hide()
        self._backdrop.clear()

    def cancel_requested(self) -> bool:
        return not self._cancel.isEnabled()

    def _request_cancel(self) -> None:
        self._cancel.setEnabled(False)
        self._cancel.setText("取消中…")
        self._percent.setText("正在停止，当前文件处理完后结束")
        self.cancelled.emit()

    # ------------------------------------------------------------ 进度
    def set_stage(self, stage: str, index: int, total: int, name: str,
                  fraction: float) -> None:
        self._total = max(1, int(total or self._total))
        total = self._total
        index = max(1, min(int(index or 1), total))
        if name:
            if stage == "import":
                self._import_name = name
            else:
                self._process_name = name

        if stage == "import":
            self._stage = "import"
            self._line_import.setText(f"正在导入文件（{index}/{total}）：{self._import_name}")
        elif stage in ("process", "merge", "done"):
            self._stage = "process"
            if self._import_name:
                self._line_import.setText(f"已导入（{index}/{total}）：{self._import_name}")
            label = "正在汇总" if stage == "merge" else "正在处理文件"
            if stage == "done":
                label = "已完成"
            self._line_process.setText(f"{label}（{index}/{total}）：{self._process_name or '—'}")
        self._reset_styles()

        if stage == "done":
            self._bar.setValue(1000)
            self._percent.setText("100%")
            return
        overall = ((index - 1) + max(0.0, min(1.0, float(fraction)))) / total
        self._bar.setValue(int(overall * 1000))
        self._percent.setText(f"总进度 {overall * 100:.0f}%")

    def _reset_styles(self) -> None:
        active = "font-size: 10.5pt; color: #16232f; font-weight: 600;"
        idle = "font-size: 10.5pt; color: #78909c;"
        self._line_import.setStyleSheet(active if self._stage == "import" else idle)
        self._line_process.setStyleSheet(active if self._stage == "process" else idle)

    # ------------------------------------------------------------ 绘制
    def _capture_backdrop(self) -> None:
        """先抓主窗口快照再显示自己，否则会把遮罩也抓进去。"""
        parent = self.parentWidget()
        if parent is None:
            return
        self.hide()
        pixmap = parent.grab()
        self._backdrop.setPixmap(pixmap)

    def _place_card(self) -> None:
        width = min(self.CARD_WIDTH, max(320, self.width() - 80))
        self._card.setFixedWidth(width)
        self._card.adjustSize()
        height = self._card.sizeHint().height()
        self._card.setGeometry(
            (self.width() - width) // 2, max(24, (self.height() - height) // 2),
            width, height)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        self._backdrop.setGeometry(self.rect())
        self._place_card()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        # 模糊快照上再压一层浅色蒙版：既压暗细节，又保证卡片对比度。
        painter.fillRect(self.rect(), QColor(244, 247, 250, 168))
