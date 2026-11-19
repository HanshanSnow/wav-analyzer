"""导出分析 TXT 的选项对话框。

三件事容易在这里出错，所以都显式做在界面上：
  1. 数据版本：源文件 vs 修改后。两者统计/坐标完全不同，导出前必须让人看见选的是哪个。
  2. 内容分段：7 个段落可勾选，缺数据的段落置灰并注明原因，避免导出后发现整段是「未计算」。
  3. 坐标体量：全量导出可达数千万行、数 GB，实时显示预估行数，超阈值时二次确认。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout,
)

from core.txt_export import (
    HUGE_COORD_ROWS, SECTION_ORDER, STAT_SCOPES, TxtExportOptions, suggest_txt_path,
)

COORD_MODE_HINTS = {
    "per_second": "按采样率换算步长，适合画曲线与对照",
    "step": "按固定采样点间隔抽稀，适合对齐特定分析口径",
    "all": "不抽稀，长文件会非常大（数千万行、数 GB）",
}


class TxtExportDialog(QDialog):
    """选择导出哪个数据版本、哪些章节、坐标取法。"""

    def __init__(
        self,
        parent=None,
        *,
        duration: float,
        sample_rate: int,
        total_samples: int,
        source_path: Path | None = None,
        edited: bool = False,
        region: tuple[float, float] | None = None,
        available: dict[str, bool] | None = None,
        channel_index: int = 0,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("导出分析 TXT")
        self.setMinimumWidth(600)
        self._duration = max(0.0, float(duration))
        self._sample_rate = max(1, int(sample_rate))
        self._total = max(0, int(total_samples))
        self._source_path = source_path
        self._channel_index = channel_index
        self._region = region if region and region[1] > region[0] else None
        self._available = {key: True for key, _ in SECTION_ORDER}
        if available:
            self._available.update({k: bool(v) for k, v in available.items() if k in self._available})
        stored = QSettings("PhysicsExperiment", "SoundWavAnalyzer")

        hint = QLabel(
            "TXT 用定宽空格对齐、除末列外只含 ASCII，任何等宽字体下逐列对齐；"
            "可直接拖进 Excel（数据-分列-固定宽度）或 Origin（空格分隔）。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#455a64;")

        # ------------------------------------------------------------ 数据版本
        self.data_version = QComboBox()
        self.data_version.addItem("源文件分析（未做任何编辑）", False)
        self.data_version.addItem("修改后文件分析（含去噪 / 裁剪结果）", True)
        if not edited:
            item = self.data_version.model().item(1)
            if item is not None:
                item.setEnabled(False)
            self.data_version.setItemText(
                1, "修改后文件分析（当前未编辑，与源文件相同）")
        self.data_version.setCurrentIndex(1 if edited else 0)

        # ------------------------------------------------------------ 章节
        sections_group = QGroupBox("导出内容")
        grid = QGridLayout(sections_group)
        self.section_boxes: dict[str, QCheckBox] = {}
        for position, (key, label) in enumerate(SECTION_ORDER):
            box = QCheckBox(label)
            usable = self._available.get(key, True)
            box.setChecked(usable)
            box.setEnabled(usable)
            if not usable:
                box.setText(f"{label}（当前无数据）")
            self.section_boxes[key] = box
            grid.addWidget(box, position // 2, position % 2)
        note = QLabel("原坐标行数最多，排在文末；段落编号随勾选自动重排。")
        note.setStyleSheet("color:#607d8b;")
        note.setWordWrap(True)

        # ------------------------------------------------------------ 区间统计范围
        stats_group = QGroupBox("区间统计范围（可多选）")
        stats_layout = QVBoxLayout(stats_group)
        self.scope_boxes: dict[str, QCheckBox] = {}
        scope_row = QHBoxLayout()
        for key, label in STAT_SCOPES:
            box = QCheckBox(label)
            box.setChecked(key == "full")
            self.scope_boxes[key] = box
            scope_row.addWidget(box)
        scope_row.addStretch()
        custom_row = QHBoxLayout()
        self.custom_start = QDoubleSpinBox()
        self.custom_end = QDoubleSpinBox()
        for spin in (self.custom_start, self.custom_end):
            spin.setDecimals(3)
            spin.setRange(0.0, max(self._duration, 1.0))
            spin.setSuffix(" s")
            spin.setSingleStep(0.1)
        self.custom_start.setValue(0.0)
        self.custom_end.setValue(min(self._duration, 10.0))
        custom_row.addWidget(QLabel("自定义区间"))
        custom_row.addWidget(self.custom_start)
        custom_row.addWidget(QLabel("–"))
        custom_row.addWidget(self.custom_end)
        custom_row.addStretch()
        self.scope_boxes["region"].setEnabled(self._region is not None)
        if self._region is None:
            self.scope_boxes["region"].setText("蓝框选区（当前无选区）")
        stats_layout.addLayout(scope_row)
        stats_layout.addLayout(custom_row)

        # ------------------------------------------------------------ 坐标取法
        coord_group = QGroupBox("原坐标取法")
        coord_form = QFormLayout(coord_group)
        self.coord_mode = QComboBox()
        self.coord_mode.addItem("每秒固定点数（推荐）", "per_second")
        self.coord_mode.addItem("按步长抽稀", "step")
        self.coord_mode.addItem("全部采样点", "all")
        self.coord_value = QDoubleSpinBox()
        self.coord_value.setRange(1.0, 1_000_000.0)
        self.coord_value.setDecimals(0)
        self.coord_value.setValue(float(stored.value("txt/per_second", 1000)))
        self.coord_rows_label = QLabel()
        self.coord_rows_label.setStyleSheet("color:#37474f;")
        coord_form.addRow("取法", self.coord_mode)
        coord_form.addRow("数值", self.coord_value)
        coord_form.addRow("预估", self.coord_rows_label)

        # ------------------------------------------------------------ 输出文件
        default_path = suggest_txt_path(source_path, edited, channel_index)
        self.path_edit = QLineEdit(default_path)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("导出")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        version_form = QFormLayout()
        version_form.addRow("数据版本", self.data_version)
        layout.addLayout(version_form)
        layout.addWidget(sections_group)
        layout.addWidget(note)
        layout.addWidget(stats_group)
        layout.addWidget(coord_group)
        out_form = QFormLayout()
        out_form.addRow("保存到", path_row)
        layout.addLayout(out_form)
        layout.addWidget(buttons)

        self.data_version.currentIndexChanged.connect(self._on_version_changed)
        self.coord_mode.currentIndexChanged.connect(self._on_coord_mode_changed)
        self.coord_value.valueChanged.connect(self._refresh_estimate)
        self._on_coord_mode_changed()

    # ---------------------------------------------------------------- 交互
    def _on_version_changed(self) -> None:
        default_path = suggest_txt_path(self._source_path, self.edited(), self._channel_index)
        # 用户改过路径就不覆盖；只有仍是旧默认值时才跟着数据版本换名。
        current = self.path_edit.text().strip()
        if not current or Path(current).name.startswith(
                (self._source_path.stem if self._source_path else "分析")):
            self.path_edit.setText(default_path)

    def _on_coord_mode_changed(self) -> None:
        mode = str(self.coord_mode.currentData())
        if mode == "per_second":
            self.coord_value.setRange(1.0, 1_000_000.0)
            self.coord_value.setSuffix(" 点/秒")
        elif mode == "step":
            self.coord_value.setRange(1.0, 1e9)
            self.coord_value.setSuffix(" 点")
        else:
            self.coord_value.setEnabled(False)
            self.coord_value.setSuffix("")
        self.coord_value.setEnabled(mode != "all")
        if mode == "all":
            self.coord_rows_label.setText(COORD_MODE_HINTS[mode])
            self._refresh_estimate()
            return
        self._refresh_estimate()

    def _stride(self) -> int:
        mode = str(self.coord_mode.currentData())
        if mode == "all":
            return 1
        value = float(self.coord_value.value())
        if mode == "step":
            return max(1, int(value))
        return max(1, int(round(self._sample_rate / max(1e-6, value))))

    def _refresh_estimate(self) -> None:
        stride = self._stride()
        rows = (self._total + stride - 1) // stride
        megabytes = rows * 26 / 1024 / 1024
        text = f"{rows:,} 行，约 {megabytes:.1f} MB"
        if rows > HUGE_COORD_ROWS:
            text += "（很大，写入需要一段时间）"
        self.coord_rows_label.setText(text)

    def _browse(self) -> None:
        current = self.path_edit.text().strip()
        path, _ = QFileDialog.getSaveFileName(
            self, "保存分析 TXT", current or "analysis.txt", "文本文件 (*.txt)")
        if path:
            if not path.lower().endswith(".txt"):
                path += ".txt"
            self.path_edit.setText(path)

    # ---------------------------------------------------------------- 结果
    def edited(self) -> bool:
        return bool(self.data_version.currentData())

    def output_path(self) -> str:
        text = self.path_edit.text().strip()
        if text and not text.lower().endswith(".txt"):
            text += ".txt"
        return text

    def options(self) -> TxtExportOptions:
        sections = tuple(key for key, _ in SECTION_ORDER
                         if self.section_boxes[key].isChecked() and self.section_boxes[key].isEnabled())
        scopes = tuple(key for key, _ in STAT_SCOPES
                       if self.scope_boxes[key].isChecked() and self.scope_boxes[key].isEnabled())
        custom = (float(self.custom_start.value()), float(self.custom_end.value()))
        return TxtExportOptions(
            sections=sections,
            coord_mode=str(self.coord_mode.currentData()),
            coord_step=int(self.coord_value.value()),
            coord_per_second=float(self.coord_value.value())
            if self.coord_mode.currentData() == "per_second" else 1000.0,
            stat_scopes=scopes or ("full",),
            region=self._region,
            custom=custom,
        )

    def sizeHint(self):  # noqa: D102 - 段落复选框两列排布，宽一点更整齐
        hint = super().sizeHint()
        hint.setWidth(max(hint.width(), 660))
        return hint

    # ---------------------------------------------------------------- 提交
    def accept(self) -> None:
        path = self.output_path()
        if not path:
            QMessageBox.warning(self, "缺少保存路径", "请先选择 TXT 保存位置。")
            self._browse()
            return
        sections = self.options().sections
        if not sections:
            QMessageBox.warning(self, "未选择内容", "至少勾选一个导出章节。")
            return
        if "coords" in sections and self._stride() == 1 and self._total > HUGE_COORD_ROWS:
            answer = QMessageBox.question(
                self, "确认导出全部采样点",
                f"原坐标不抽稀将写入约 {self._total:,} 行（数 GB），耗时较长。\n确定继续吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        stored = QSettings("PhysicsExperiment", "SoundWavAnalyzer")
        stored.setValue("txt/per_second", float(self.coord_value.value())
                        if self.coord_mode.currentData() == "per_second" else 1000.0)
        super().accept()
