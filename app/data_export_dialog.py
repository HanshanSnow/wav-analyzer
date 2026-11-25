"""导出原始数据：在一个窗口里勾选要写的文件、选目录，然后一次写出。

对话框只负责「选什么、写哪里」，真正取数与落盘在主窗口里做——
分析结果都在主窗口的 `fourier` / `envelope_*` / `spectrogram` 上。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from core.i18n import tf, tr

# (kind, 界面名称, 说明, 文件名后缀)
ENTRIES = (
    ("spectrum", tr("频谱 CSV"), tr("每个 FFT 频点一行：频率、幅值、dBFS、相位"), tr("频谱")),
    ("peaks", tr("峰值与谐波 CSV"), tr("主要峰值与基频整数倍谐波，harmonic 列标注阶次"), tr("峰值与谐波")),
    ("envelope", tr("包络 CSV"), tr("时间、包络值、拟合曲线（未拟合时留空）"), tr("包络")),
    ("spectrogram", tr("时频矩阵 NPZ"), tr("频率×时间的 dBFS 矩阵，含跳帧数 skipped"), tr("时频")),
)


class DataExportDialog(QDialog):
    """返回勾选的 kind 列表与输出目录。"""

    def __init__(self, parent: QWidget | None = None, *, stem: str = "",
                 available: dict[str, bool] | None = None, default_dir: str = "",
                 settings: QSettings | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("导出原始数据"))
        self.resize(560, 380)
        self._stem = stem or "data"
        self._available = dict(available or {})
        self._settings = settings or QSettings()
        self._boxes: dict[str, QCheckBox] = {}
        self._build()
        self._restore(default_dir)

    # ------------------------------------------------------------ 界面
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)

        hint = QLabel(tr("以下文件是分析结果的原始数据，列名为英文，文件头 # 注释记录了窗函数与 FFT 规模。"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #546e7a;")
        outer.addWidget(hint)

        for kind, label, detail, _suffix in ENTRIES:
            box = QCheckBox(label)
            usable = bool(self._available.get(kind))
            box.setChecked(usable)
            box.setEnabled(usable)
            if not usable:
                box.setToolTip(tr("当前还没有这项结果，先做对应分析"))
            row = QVBoxLayout()
            row.setSpacing(0)
            row.addWidget(box)
            note = QLabel(detail)
            note.setWordWrap(True)
            note.setStyleSheet("color: #78909c; margin-left: 22px;")
            row.addWidget(note)
            outer.addLayout(row)
            self._boxes[kind] = box

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel(tr("输出目录")))
        self.folder_edit = QLineEdit()
        folder_row.addWidget(self.folder_edit, 1)
        browse = QPushButton(tr("浏览…"))
        browse.clicked.connect(self._browse)
        folder_row.addWidget(browse)
        outer.addLayout(folder_row)

        outer.addStretch(1)

        footer = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setStyleSheet("color: #607d8b;")
        footer.addWidget(self.summary, 1)
        cancel = QPushButton(tr("取消"))
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self.export_button = QPushButton(tr("导出"))
        self.export_button.setDefault(True)
        self.export_button.clicked.connect(self._on_export)
        footer.addWidget(self.export_button)
        outer.addLayout(footer)

    def _restore(self, default_dir: str) -> None:
        remembered = str(self._settings.value("export/data_dir", "", type=str) or "")
        start = default_dir or remembered
        self.folder_edit.setText(start)
        self._refresh_summary()

    def _browse(self) -> None:
        current = self.folder_edit.text().strip()
        start = current if current and Path(current).is_dir() else ""
        folder = QFileDialog.getExistingDirectory(self, tr("选择输出目录"), start)
        if folder:
            self.folder_edit.setText(folder)
            self._refresh_summary()

    # ------------------------------------------------------------ 结果
    def checked_kinds(self) -> list[str]:
        return [kind for kind, box in self._boxes.items() if box.isChecked()]

    def output_dir(self) -> str:
        return self.folder_edit.text().strip()

    def file_name(self, kind: str) -> str:
        suffix = next(item[3] for item in ENTRIES if item[0] == kind)
        return f"{self._stem}_{suffix}"

    def _refresh_summary(self) -> None:
        kinds = self.checked_kinds()
        if not kinds:
            self.summary.setText(tr("未勾选任何文件"))
        else:
            self.summary.setText(tf('将写出 {_v0} 个文件', _v0=(len(kinds))))

    def _on_export(self) -> None:
        if not self.checked_kinds():
            self.summary.setText(tr("未勾选任何文件"))
            return
        folder = self.output_dir()
        if not folder:
            self.summary.setText(tr("请先选择输出目录"))
            return
        if not Path(folder).is_dir():
            self.summary.setText(tr("输出目录不存在"))
            return
        try:
            self._settings.setValue("export/data_dir", folder)
        except Exception:      # noqa: BLE001 - 权限受限时记忆失败不该挡导出
            pass
        self.accept()
