"""降噪工具组对话框：选方法、给参数、看前提与护栏，再回到主窗口预览/应用。

原则：这里不碰波形数据，只产出参数字典；真正的计算在主窗口的工作线程里做。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout,
    QWidget,
)

from core.anc import (
    DEFAULT_HARMONICS, DEFAULT_LAMBDA_RATIO, DEFAULT_NOTCH_FREQUENCY, DEFAULT_NOTCH_Q,
    DEFAULT_ORDER, MAX_ABS_DELTA_LEVEL_DB, MAX_COHERENCE_XD, MAX_LEAK_COHERENCE,
    METHOD_SPECS, MIN_AVERAGES, MIN_ERLE_HOLDOUT_DB, SAMPLES_PER_TAP,
)
from core.i18n import tf, tr

SETTINGS_ORG = "PhysicsExperiment"
SETTINGS_APP = "SoundWavAnalyzer"

REFERENCE_METHODS = ("ls_frozen", "wiener_clean", "ls_block", "wiener_spectral",
                     "noise_profile")
# 这些方法只要有一段噪声参考即可，不要求与目标对齐（独立录音也能用）
UNALIGNED_REFERENCE_METHODS = ("noise_profile",)


class _ReferenceProbe(QThread):
    """后台校验参考文件：解码 + 声道/采样率检查 + 哈希，全部在工作线程里做。"""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str, channel: int, sample_rate: int, parent=None):
        super().__init__(parent)
        self._path = path
        self._channel = int(channel)
        self._sample_rate = int(sample_rate)

    def run(self) -> None:  # noqa: D401 - QThread 入口
        try:
            from core.reference import load_reference_cached

            ref = load_reference_cached(self._path, sample_rate=self._sample_rate,
                                        channel=self._channel)
            self.done.emit(ref)
        except Exception as exc:  # noqa: BLE001 - 失败只更新提示，不抛到界面
            self.failed.emit(str(exc))


class AncToolsDialog(QDialog):
    """参数收集：方法、阶数、陷波、分块、噪声段。"""

    def __init__(self, parent: QWidget | None = None, *,
                 channels: int = 1, selection: tuple[float, float, float] | None = None,
                 settings: QSettings | None = None,
                 sample_rate: int = 0, external_reference: str | None = None,
                 reference_channel: int = 0) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("降噪工具组"))
        self.setMinimumWidth(560)
        self._channels = max(1, int(channels))
        self._selection = selection
        self._sample_rate = int(sample_rate)
        self._reference_path = external_reference or None
        self._reference_channel_index = int(reference_channel)
        self._settings = settings or QSettings(SETTINGS_ORG, SETTINGS_APP)
        # 参考校验的令牌与线程：换文件/声道时让旧结果作废，避免迟到结果覆盖新状态
        self._probe_token = 0
        self._probes: list[_ReferenceProbe] = []

        layout = QVBoxLayout(self)

        self.method_combo = QComboBox(self)
        for spec in METHOD_SPECS:
            self.method_combo.addItem(spec.label, spec.method_id)
        layout.addWidget(self.method_combo)

        self.premise_label = QLabel(self)
        self.premise_label.setWordWrap(True)
        layout.addWidget(self.premise_label)

        params = QGroupBox(tr("参数"), self)
        form = QFormLayout(params)
        self.order_spin = QSpinBox(params)
        self.order_spin.setRange(64, 16384)
        self.order_spin.setSingleStep(64)
        self.order_spin.setValue(DEFAULT_ORDER)
        self.order_spin.setToolTip(tr("越大越能拟合长混响；噪声段至少要有 8× 阶数个采样点"))
        form.addRow(tr("滤波器阶数"), self.order_spin)

        self.block_spin = QDoubleSpinBox(params)
        self.block_spin.setRange(0.5, 120.0)
        self.block_spin.setDecimals(1)
        self.block_spin.setSingleStep(0.5)
        self.block_spin.setValue(10.0)
        self.block_spin.setSuffix(" s")
        form.addRow(tr("分块长度"), self.block_spin)

        self.notch_spin = QDoubleSpinBox(params)
        self.notch_spin.setRange(1.0, 20000.0)
        self.notch_spin.setDecimals(2)
        self.notch_spin.setValue(DEFAULT_NOTCH_FREQUENCY)
        self.notch_spin.setSuffix(" Hz")
        form.addRow(tr("陷波中心"), self.notch_spin)

        self.q_spin = QDoubleSpinBox(params)
        self.q_spin.setRange(1.0, 200.0)
        self.q_spin.setDecimals(1)
        self.q_spin.setValue(DEFAULT_NOTCH_Q)
        form.addRow(tr("陷波 Q 值"), self.q_spin)

        self.harmonics_spin = QSpinBox(params)
        self.harmonics_spin.setRange(1, 20)
        self.harmonics_spin.setValue(DEFAULT_HARMONICS)
        form.addRow(tr("谐波次数"), self.harmonics_spin)
        layout.addWidget(params)

        segment = QGroupBox(tr("噪声段"), self)
        segment_form = QFormLayout(segment)
        self.auto_check = QCheckBox(tr("自动检测（找开头最平稳的一段）"), segment)
        self.auto_check.setChecked(True)
        segment_form.addRow(self.auto_check)
        self.start_spin = QDoubleSpinBox(segment)
        self.start_spin.setRange(0.0, 1.0e7)
        self.start_spin.setDecimals(3)
        self.start_spin.setSuffix(" s")
        self.end_spin = QDoubleSpinBox(segment)
        self.end_spin.setRange(0.0, 1.0e7)
        self.end_spin.setDecimals(3)
        self.end_spin.setSuffix(" s")
        if selection is not None:
            self.start_spin.setValue(selection[0])
            self.end_spin.setValue(selection[1])
        segment_form.addRow(tr("起点"), self.start_spin)
        segment_form.addRow(tr("终点"), self.end_spin)
        layout.addWidget(segment)

        reference = QGroupBox(tr("参考来源"), self)
        reference_form = QFormLayout(reference)
        self.ref_source = QComboBox(reference)
        self.ref_source.addItem(tr("内置声道（双声道文件的另一路）"), "builtin")
        self.ref_source.addItem(tr("外部文件…"), "external")
        self.ref_source.addItem(tr("不使用参考"), "none")
        reference_form.addRow(tr("来源"), self.ref_source)

        row = QHBoxLayout()
        self.ref_path_label = QLabel("-", reference)
        self.ref_path_label.setWordWrap(True)
        self.ref_browse = QPushButton(tr("选择…"), reference)
        self.ref_browse.clicked.connect(self._browse_reference)
        row.addWidget(self.ref_path_label, 1)
        row.addWidget(self.ref_browse)
        reference_form.addRow(tr("文件"), row)

        self.ref_channel_spin = QSpinBox(reference)
        self.ref_channel_spin.setRange(1, 16)
        self.ref_channel_spin.setValue(self._reference_channel_index + 1)
        self.ref_channel_spin.setToolTip(
            tr("多声道参考文件里用哪一路；声道号会随工程与批量记录一起保存"))
        reference_form.addRow(tr("声道"), self.ref_channel_spin)

        self.ref_status = QLabel("", reference)
        self.ref_status.setWordWrap(True)
        self.ref_status.setStyleSheet("color:#607d8b;")
        reference_form.addRow(self.ref_status)
        layout.addWidget(reference)

        self.guard_label = QLabel(
            tf("护栏：留出段 ERLE ≥ {_v0:g} dB；泄漏相干 ≤ {_v1:g}；参考与目标相干 ≤ {_v2:g}；"
               "噪声段 ≥ {_v3}× 阶数；同步平均至少 {_v4} 次；陷波对主频影响 ≤ {_v5:g} dB。",
               _v0=MIN_ERLE_HOLDOUT_DB, _v1=MAX_LEAK_COHERENCE, _v2=MAX_COHERENCE_XD,
               _v3=SAMPLES_PER_TAP, _v4=MIN_AVERAGES, _v5=MAX_ABS_DELTA_LEVEL_DB),
            self)
        self.guard_label.setWordWrap(True)
        layout.addWidget(self.guard_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.button(QDialogButtonBox.Ok).setText(tr("分析并应用"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("取消"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.method_combo.currentIndexChanged.connect(self._sync_method)
        self.auto_check.toggled.connect(self._sync_segment)
        self.ref_source.currentIndexChanged.connect(self._on_source_changed)
        self.ref_channel_spin.valueChanged.connect(self._sync_reference)
        self._restore()
        self._sync_method()
        self._sync_reference()

    # ------------------------------------------------------------ 状态同步
    def current_method(self) -> str:
        return str(self.method_combo.currentData())

    def _spec(self):
        method = self.current_method()
        return next((item for item in METHOD_SPECS if item.method_id == method), METHOD_SPECS[0])

    def _sync_method(self) -> None:
        spec = self._spec()
        method = spec.method_id
        needs_reference = method in REFERENCE_METHODS
        source = str(self.ref_source.currentData() or "builtin")
        if not needs_reference:
            note = tr("不需要参考通道，只处理当前选中的声道。")
        elif method in UNALIGNED_REFERENCE_METHODS and source == "external":
            note = tr("用外部参考的整段噪声谱，不要求与目标对齐（可以是另一次录音）。")
        elif needs_reference and source == "none":
            note = tr("这个方法需要参考：请在下方选择内置声道或外部文件。")
        elif needs_reference and source == "builtin" and self._channels < 2:
            note = tr("这个方法需要参考通道：当前文件只有 1 个声道，应用会被拒绝。")
        elif needs_reference:
            note = tr("参考通道取另一个声道；目标通道是当前选中的声道。")
        else:
            note = tr("不需要参考通道，只处理当前选中的声道。")
        self.premise_label.setText(
            tf("{_v0}。适用：{_v1}。{_v2}", _v0=spec.premise, _v1=spec.suitable, _v2=note))

        needs_noise = spec.needs_noise
        for widget in (self.start_spin, self.end_spin):
            widget.setEnabled(needs_noise and not self.auto_check.isChecked())
        self.auto_check.setEnabled(needs_noise)
        self.block_spin.setEnabled(method == "ls_block")
        for widget in (self.notch_spin, self.q_spin, self.harmonics_spin):
            widget.setEnabled(method == "notch")
        # 滤波器阶数只对时域自适应方法有意义；noise_profile 在频域工作
        self.order_spin.setEnabled(needs_reference and method != "noise_profile")
        self.guard_label.setVisible(True)

    def _sync_segment(self) -> None:
        manual = not self.auto_check.isChecked()
        needs_noise = self._spec().needs_noise
        for widget in (self.start_spin, self.end_spin):
            widget.setEnabled(needs_noise and manual)

    # ------------------------------------------------------------ 参考来源
    def reference_path(self) -> str | None:
        return self._reference_path if str(self.ref_source.currentData()) == "external" else None

    def reference_channel(self) -> int:
        return max(0, int(self.ref_channel_spin.value()) - 1)

    def _browse_reference(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("选择参考 WAV"), "", tr("WAV 音频 (*.wav)"))
        if not path:
            return
        self._reference_path = path
        index = self.ref_source.findData("external")
        if index >= 0:
            self.ref_source.setCurrentIndex(index)
        self._sync_reference()

    def _on_source_changed(self) -> None:
        self._sync_reference()
        self._sync_method()  # 参考来源变化会改变方法的前提说明

    def _sync_reference(self) -> None:
        source = str(self.ref_source.currentData() or "builtin")
        external = source == "external"
        self.ref_browse.setEnabled(external)
        self.ref_channel_spin.setEnabled(external)
        self.ref_status.setStyleSheet("color:#607d8b;")
        if source == "none":
            self.ref_path_label.setText("-")
            self.ref_status.setText(tr("不使用参考：需要参考通道的方法会被拒绝。"))
            return
        if source == "builtin":
            self.ref_path_label.setText(tr("内置声道"))
            self.ref_status.setText(
                tr("取双声道文件的另一路；无需外部文件。") if self._channels > 1
                else tr("当前文件只有 1 个声道，不能作为内置参考。"))
            return
        if not self._reference_path:
            self.ref_path_label.setText(tr("未选择"))
            self.ref_status.setText(tr("请选择与目标同时录制、同采样率的参考文件。"))
            return
        self.ref_path_label.setText(Path(self._reference_path).name)
        if self._sample_rate <= 0:
            self.ref_status.setText(tr("载入音频后才能校验参考文件。"))
            return
        self._probe_reference_async()

    def _probe_reference_async(self) -> None:
        """在后台线程里解码+校验参考，避免卡住对话框（大文件可达数百毫秒）。"""
        self._probe_token += 1
        token = self._probe_token
        path = self._reference_path
        channel = self.reference_channel()
        rate = self._sample_rate
        self.ref_status.setStyleSheet("color:#607d8b;")
        self.ref_status.setText(tr("正在校验参考文件…"))

        dialog = self
        probe = _ReferenceProbe(path, channel, rate, dialog)
        self._probes.append(probe)

        def _retire() -> None:
            if probe in dialog._probes:
                dialog._probes.remove(probe)
            probe.deleteLater()

        def on_done(ref) -> None:
            if token == dialog._probe_token:
                dialog.ref_status.setStyleSheet("color:#1f5b38;")
                dialog.ref_status.setText(
                    tf("可用：{_v0} 个声道、{_v1} Hz、{_v2:,} 点；"
                       "与目标不等长时只处理重叠段。",
                       _v0=(ref.channels), _v1=(ref.sample_rate), _v2=(ref.frames)))
            _retire()

        def on_failed(message: str) -> None:
            if token == dialog._probe_token:
                dialog.ref_status.setStyleSheet("color:#b3261e;")
                dialog.ref_status.setText(tf("不可用：{_v0}", _v0=(message)))
            _retire()

        probe.done.connect(on_done)
        probe.failed.connect(on_failed)
        probe.start()

    def done(self, result: int) -> None:  # noqa: N802 - Qt 命名
        """关窗时等校验线程退出：QThread 在运行中被回收会让进程直接崩掉。"""
        for probe in list(getattr(self, "_probes", [])):
            if probe.isRunning():
                probe.wait(3000)
        super().done(result)

    # ------------------------------------------------------------ 记忆与产出
    def _restore(self) -> None:
        method = str(self._settings.value("denoise_tools/method", "ls_frozen"))
        index = self.method_combo.findData(method)
        if index >= 0:
            self.method_combo.setCurrentIndex(index)
        try:
            order = int(self._settings.value("denoise_tools/order", DEFAULT_ORDER))
        except (TypeError, ValueError):
            order = DEFAULT_ORDER
        self.order_spin.setValue(max(self.order_spin.minimum(),
                                     min(order, self.order_spin.maximum())))
        self.auto_check.setChecked(
            str(self._settings.value("denoise_tools/auto_segment", "true")).lower() != "false")

    def _remember(self) -> None:
        self._settings.setValue("denoise_tools/method", self.current_method())
        self._settings.setValue("denoise_tools/order", int(self.order_spin.value()))
        self._settings.setValue("denoise_tools/auto_segment",
                                "true" if self.auto_check.isChecked() else "false")
        self._settings.sync()

    def accept(self) -> None:  # noqa: D401 - Qt 回调
        self._remember()
        super().accept()

    def params(self) -> dict[str, object]:
        """三块参数分开给：method 决定用哪些，其余原样交给 core.anc。"""
        manual = not self.auto_check.isChecked() and self._spec().needs_noise
        segment = None
        if manual:
            segment = (float(self.start_spin.value()), float(self.end_spin.value()))
        return {
            "method": self.current_method(),
            "segment": segment,
            "options": {
                "order": int(self.order_spin.value()),
                "block_seconds": float(self.block_spin.value()),
                "frequency": float(self.notch_spin.value()),
                "q": float(self.q_spin.value()),
                "harmonics": int(self.harmonics_spin.value()),
            },
        }
