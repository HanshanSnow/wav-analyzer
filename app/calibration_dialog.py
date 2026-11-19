"""声学校准设置对话框：把 dBFS 换算成 dB SPL 所需的偏移量 K。

两条路都支持，而且界面上实时显示两条路的等效结果：

- 按硬件参数推算：灵敏度、前置增益、声卡满幅输入电压；
- 按已知声压级标定：拿一个声压级已知的声源（校准器、或已标定过的手机），
  填它标称的声压级和程序读到的 dBFS，K = L_ref − L_dBFS。

第二条更可靠，因为民用声卡的"满幅电压"是最不可靠的一个参数。
"""

from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from core.calibration import MODE_LABELS, MODE_PARAMS, MODE_REFERENCE, Calibration


class CalibrationDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        profiles: list[Calibration] | None = None,
        active: str = "",
        current_dbfs: float | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("声学校准")
        self.resize(640, 520)
        self.profiles: list[Calibration] = copy.deepcopy(profiles or [])
        if not self.profiles:
            self.profiles = [Calibration(name="默认校准")]
        self.current_dbfs = current_dbfs
        self.active = active or self.profiles[0].name

        layout = QVBoxLayout(self)
        layout.addWidget(self._intro())

        picker = QHBoxLayout()
        self.picker = QComboBox()
        self.picker.currentIndexChanged.connect(self._on_pick)
        new_button = QPushButton("新建")
        new_button.clicked.connect(self._create)
        delete_button = QPushButton("删除")
        delete_button.clicked.connect(self._delete)
        picker.addWidget(QLabel("配置"))
        picker.addWidget(self.picker, 1)
        picker.addWidget(new_button)
        picker.addWidget(delete_button)
        layout.addLayout(picker)

        layout.addWidget(self._form())
        layout.addWidget(self._caveats())

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("保存并应用")
        self.buttons.button(QDialogButtonBox.Cancel).setText("取消")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._refresh_picker()

    # ------------------------------------------------------------ 静态文案
    def _intro(self) -> QWidget:
        label = QLabel(
            "把录音的数字满幅电平换算成声压级，只需要一个加性偏移："
            "<b>dB SPL = dBFS + K</b>。K 可以由硬件参数推算，也可以用声压级已知的声源标定。"
            "未配置校准时，程序只显示 dBFS，不会给出任何声压级。"
        )
        label.setWordWrap(True)
        label.setStyleSheet("color:#37474f;")
        return label

    def _caveats(self) -> QWidget:
        label = QLabel(
            "⚠ 两种麦克风不要用这套换算：<b>带 AGC/ALC 的模块</b>（如 MAX9814、多数 USB 会议麦）"
            "增益会随声压自动变化；<b>录音已削顶</b>时 dBFS 被压平，反推的声压级系统性偏低。"
            "另外系统录音音量必须是 100%（数字增益 0 dB），否则要把它折进前置增益里。"
        )
        label.setWordWrap(True)
        label.setStyleSheet(
            "background:#fff8e1; border:1px solid #ffe082; border-radius:4px; padding:8px; color:#5d4037;")
        return label

    # ------------------------------------------------------------ 表单
    def _form(self) -> QWidget:
        box = QWidget()
        form = QFormLayout(box)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.name = QLineEdit()
        self.mode = QComboBox()
        for key in (MODE_PARAMS, MODE_REFERENCE):
            self.mode.addItem(MODE_LABELS[key], key)
        self.mode.currentIndexChanged.connect(self._on_mode)

        self.sensitivity = QDoubleSpinBox()
        self.sensitivity.setRange(0.1, 500.0)
        self.sensitivity.setDecimals(2)
        self.sensitivity.setValue(10.0)
        self.sensitivity.setSuffix(" mV/Pa")

        self.gain = QDoubleSpinBox()
        self.gain.setRange(-20.0, 120.0)
        self.gain.setDecimals(1)
        self.gain.setValue(0.0)
        self.gain.setSuffix(" dB")

        self.full_scale = QDoubleSpinBox()
        self.full_scale.setRange(0.01, 20.0)
        self.full_scale.setDecimals(3)
        self.full_scale.setValue(1.0)
        self.full_scale.setSuffix(" Vrms")

        self.ref_spl = QDoubleSpinBox()
        self.ref_spl.setRange(-20.0, 180.0)
        self.ref_spl.setDecimals(1)
        self.ref_spl.setValue(94.0)
        self.ref_spl.setSuffix(" dB SPL")

        self.ref_dbfs = QDoubleSpinBox()
        self.ref_dbfs.setRange(-140.0, 0.0)
        self.ref_dbfs.setDecimals(2)
        self.ref_dbfs.setValue(-40.0)
        self.ref_dbfs.setSuffix(" dBFS")
        self.grab_button = QPushButton("取当前统计")
        self.grab_button.setToolTip("把当前选区的 RMS 电平填进来")
        self.grab_button.clicked.connect(self._grab_dbfs)
        dbfs_row = QHBoxLayout()
        dbfs_row.addWidget(self.ref_dbfs)
        dbfs_row.addWidget(self.grab_button)
        dbfs_wrap = QWidget()
        dbfs_wrap.setLayout(dbfs_row)
        dbfs_row.setContentsMargins(0, 0, 0, 0)

        form.addRow("名称", self.name)
        form.addRow("方式", self.mode)
        self.param_labels: list[QLabel] = []
        self.param_rows: list[tuple[QLabel, QWidget]] = []
        for text, widget in (
            ("麦克风灵敏度", self.sensitivity),
            ("前置增益", self.gain),
            ("声卡满幅输入", self.full_scale),
        ):
            label = QLabel(text)
            form.addRow(label, widget)
            self.param_labels.append(label)
            self.param_rows.append((label, widget))
        self.ref_labels: list[QLabel] = []
        self.ref_rows: list[tuple[QLabel, QWidget]] = []
        for text, widget in (("已知声压级", self.ref_spl), ("对应读数", dbfs_wrap)):
            label = QLabel(text)
            form.addRow(label, widget)
            self.ref_labels.append(label)
            self.ref_rows.append((label, widget))

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(
            "background:#e8f5e9; border:1px solid #a5d6a7; border-radius:4px; padding:8px; color:#1b5e20;")
        form.addRow(self.summary)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#78909c;")
        form.addRow(self.hint)

        for widget in (self.sensitivity, self.gain, self.full_scale, self.ref_spl, self.ref_dbfs):
            widget.valueChanged.connect(self._recalc)
        self.name.textChanged.connect(self._recalc)
        self.mode.currentIndexChanged.connect(self._recalc)
        return box

    # ------------------------------------------------------------ 数据流
    def _index(self) -> int:
        return max(0, self.picker.currentIndex())

    def _refresh_picker(self) -> None:
        self.picker.blockSignals(True)
        self.picker.clear()
        for item in self.profiles:
            suffix = "" if item.ready else "（未完成）"
            self.picker.addItem(f"{item.name}{suffix}")
        index = next((i for i, item in enumerate(self.profiles) if item.name == self.active), 0)
        self.picker.setCurrentIndex(index)
        self.picker.blockSignals(False)
        self._load(index)

    def _on_pick(self, index: int) -> None:
        if index >= 0:
            self._load(index)

    def _load(self, index: int) -> None:
        item = self.profiles[index]
        for widget in (self.name, self.sensitivity, self.gain, self.full_scale, self.ref_spl, self.ref_dbfs):
            widget.blockSignals(True)
        self.name.setText(item.name)
        mode_index = self.mode.findData(item.mode)
        self.mode.setCurrentIndex(mode_index if mode_index >= 0 else 0)
        self.sensitivity.setValue(item.sensitivity_mv_pa or 10.0)
        self.gain.setValue(item.preamp_gain_db)
        self.full_scale.setValue(item.adc_full_scale_vrms)
        self.ref_spl.setValue(item.ref_spl_db if item.ref_spl_db is not None else 94.0)
        self.ref_dbfs.setValue(item.ref_dbfs if item.ref_dbfs is not None else -40.0)
        for widget in (self.name, self.sensitivity, self.gain, self.full_scale, self.ref_spl, self.ref_dbfs):
            widget.blockSignals(False)
        self._on_mode()
        self._recalc()

    def _collect(self) -> Calibration:
        item = Calibration(
            name=self.name.text().strip() or "未命名校准",
            mode=self.mode.currentData(),
            sensitivity_mv_pa=float(self.sensitivity.value()),
            preamp_gain_db=float(self.gain.value()),
            adc_full_scale_vrms=float(self.full_scale.value()),
            ref_spl_db=float(self.ref_spl.value()),
            ref_dbfs=float(self.ref_dbfs.value()),
        )
        return item

    def _store(self) -> None:
        index = self._index()
        if index < len(self.profiles):
            self.profiles[index] = self._collect()

    def _on_mode(self) -> None:
        reference = self.mode.currentData() == MODE_REFERENCE
        for label, widget in self.param_rows:
            label.setVisible(not reference)
            widget.setVisible(not reference)
        for label, widget in self.ref_rows:
            label.setVisible(reference)
            widget.setVisible(reference)

    def _grab_dbfs(self) -> None:
        if self.current_dbfs is None:
            QMessageBox.information(self, "没有可用读数", "请先在主界面点“计算选区统计”，再来取 RMS 电平。")
            return
        self.ref_dbfs.setValue(float(self.current_dbfs))

    def _recalc(self) -> None:
        item = self._collect()
        offset = item.offset_db()
        if offset is None:
            self.summary.setText("K 尚未确定：请补全当前方式的参数。")
            self.hint.setText("")
            return
        self.summary.setText(
            f"<b>K = {offset:+.2f} dB</b>　→　声压级 = 读数 + {offset:+.2f} dB<br>"
            f"反过来：{item.spl(0.0):.1f} dB SPL 满幅，94 dB SPL 约对应 {item.dbfs(94.0):+.2f} dBFS。"
        )
        self.hint.setText(
            "K 是常数偏移，所以同一批录音只要麦克风、前置增益和系统音量不变，标定一次即可复用。")

    def _create(self) -> None:
        self._store()
        self.profiles.append(Calibration(name=f"校准 {len(self.profiles) + 1}"))
        self.active = self.profiles[-1].name
        self._refresh_picker()
        self.picker.setCurrentIndex(len(self.profiles) - 1)

    def _delete(self) -> None:
        if len(self.profiles) <= 1:
            QMessageBox.information(self, "至少保留一个配置", "可以清空参数当作“未校准”，无需删除。")
            return
        index = self._index()
        name = self.profiles[index].name
        if QMessageBox.question(self, "删除校准", f"确定删除「{name}」？") != QMessageBox.Yes:
            return
        self.profiles.pop(index)
        self.active = self.profiles[max(0, index - 1)].name
        self._refresh_picker()

    def _accept(self) -> None:
        item = self._collect()
        try:
            item.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "参数不完整", str(exc))
            return
        self.profiles[self._index()] = item
        self.active = item.name
        super().accept()

    # ------------------------------------------------------------ 结果
    def selected(self) -> Calibration | None:
        item = self._collect()
        return item if item.ready else None

    def result_payload(self) -> dict[str, Any]:
        return {"profiles": self.profiles, "active": self.active}
