"""导出图像对话框。

波形图导出最容易踩坑的是「导出的图和我屏幕上看到的不是一回事」，
所以这里把每条曲线单独做成可勾选项，并在勾选项旁标明当前是否有数据，
避免出现「勾了包络但其实是空的」这类误判。
"""

from __future__ import annotations

from core.i18n import tf, tr
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from core.figure_export import KIND_LABELS, PAPER_DPI, PAPER_SIZES, FigureOptions

KIND_WAVE = "wave"
KIND_SPECTRUM = "spectrum"
KIND_SPECTROGRAM = "spectrogram"
KIND_ORDER = (KIND_WAVE, KIND_SPECTRUM, KIND_SPECTROGRAM)

# 论文版式按物理尺寸出图（600 dpi），屏幕版式仍按像素。两者共用同一个下拉。
SIZE_PRESETS = (
    (tr("论文单栏 3.5 × 2.45 in（600 dpi，推荐）"), "paper", "single", 0, 0),
    (tr("论文双栏 7.0 × 2.6 in（600 dpi）"), "paper", "double", 0, 0),
    (tr("屏幕 1600 × 900（报告/PPT）"), "screen", "", 1600, 900),
    (tr("屏幕 1920 × 1080（全高清）"), "screen", "", 1920, 1080),
    (tr("自定义像素"), "screen", "", 0, 0),
)
LEGEND_PLACES = (
    (tr("坐标区外（图底一行，论文推荐）"), "outside"),
    (tr("坐标区内右上角"), "inside"),
    (tr("不显示图例"), "none"),
)
BACKGROUNDS = ((tr("白色（论文/报告）"), "white"), (tr("深色（投影/屏幕）"), "dark"), (tr("透明（叠放到其它版面）"), "transparent"))

# 每类图的扩展名与默认文件名后缀。
KIND_SUFFIX = {KIND_WAVE: tr("波形"), KIND_SPECTRUM: tr("频谱"), KIND_SPECTROGRAM: tr("时频图")}

# 导出格式：值是与 matplotlib 后端一致的扩展名。PNG 位图，PDF/SVG 矢量。
IMAGE_FORMATS = (
    ("png", tr("PNG 位图 (*.png)")),
    ("pdf", tr("PDF 矢量 (*.pdf)")),
    ("svg", tr("SVG 矢量 (*.svg)")),
)
VECTOR_FORMATS = ("pdf", "svg")


class ImageExportDialog(QDialog):
    """让用户选择导出哪类图、包含哪些曲线，以及尺寸与背景。"""

    def __init__(
        self,
        parent=None,
        *,
        default_kind: str = KIND_WAVE,
        default_path: str = "",
        available: dict[str, bool] | None = None,
        peak_count: int = 8,
    ) -> None:
        super().__init__(parent)
        self._peak_count = max(1, min(100, int(peak_count)))
        self.setWindowTitle(tr("导出图像（PNG / PDF / SVG）"))
        self.setMinimumWidth(560)
        self._available = {
            "original": True, "preview": False, "envelope": False, "fit": False,
            "region": True, "cursor": True,
        }
        if available:
            self._available.update({k: bool(v) for k, v in available.items() if k in self._available})
        stored = QSettings()

        hint = QLabel(
            tr("导出图按下方尺寸与背景重新渲染，不是界面截图："
            "长音频会按 min/max 抽稀到 ≤20 万点绘制，峰谷形态与读数不受影响。"
            "PDF / SVG 是矢量图，缩放不失真，适合直接放进论文。")
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#455a64;")

        self.kind = QComboBox()
        for key in KIND_ORDER:
            self.kind.addItem(KIND_LABELS[key], key)
        index = self.kind.findData(default_kind if default_kind in KIND_ORDER else KIND_WAVE)
        self.kind.setCurrentIndex(max(0, index))

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_wave_page())
        self.pages.addWidget(self._build_spectrum_page())
        self.pages.addWidget(self._build_spectrogram_page())

        # ------------------------------------------------------------ 图像设置
        self.size_preset = QComboBox()
        for label, layout, column, width, height in SIZE_PRESETS:
            self.size_preset.addItem(label, (layout, column, width, height))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(480, 8000)
        self.width_spin.setSingleStep(80)
        self.width_spin.setSuffix(" px")
        self.width_spin.setValue(int(stored.value("export/width", 1600)))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(320, 8000)
        self.height_spin.setSingleStep(60)
        self.height_spin.setSuffix(" px")
        self.height_spin.setValue(int(stored.value("export/height", 900)))
        self.size_note = QLabel()
        self.size_note.setStyleSheet("color:#546e7a;")
        self.background = QComboBox()
        for label, value in BACKGROUNDS:
            self.background.addItem(label, value)
        saved_background = stored.value("export/background", "white")
        background_index = self.background.findData(saved_background)
        self.background.setCurrentIndex(max(0, background_index))
        self.grid_check = QCheckBox(tr("显示网格"))
        self.format_combo = QComboBox()
        for suffix, label in IMAGE_FORMATS:
            self.format_combo.addItem(label, suffix)
        saved_format = str(stored.value("export/format", "png"))
        format_index = self.format_combo.findData(saved_format)
        self.format_combo.setCurrentIndex(max(0, format_index))
        self.format_combo.currentIndexChanged.connect(self._format_changed)
        self.vector_path_check = QCheckBox(tr("矢量图文字转为路径（不依赖本机字体）"))
        self.vector_path_check.setChecked(bool(stored.value("export/vector_text_path", True)))
        self.vector_path_check.setToolTip(
            tr("勾选后 PDF/SVG 里的文字会转成曲线，任何机器打开都不丢字，但不能再编辑文字。"))
        self.legend_place = QComboBox()
        for label, value in LEGEND_PLACES:
            self.legend_place.addItem(label, value)
        saved_legend = stored.value("export/legend_place", "outside")
        legend_index = self.legend_place.findData(saved_legend)
        self.legend_place.setCurrentIndex(max(0, legend_index))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText(tr("论文版式默认不画标题，图题写在 caption 里"))
        # 标题不记忆：不同文件的图用同一个标题最容易出错。

        size_row = QHBoxLayout()
        size_row.addWidget(self.size_preset, 1)
        size_row.addWidget(self.width_spin)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.height_spin)

        image_form = QFormLayout()
        image_form.addRow(tr("格式"), self.format_combo)
        image_form.addRow(tr("尺寸 / 版式"), size_row)
        image_form.addRow("", self.size_note)
        image_form.addRow(tr("背景"), self.background)
        flags = QHBoxLayout()
        flags.addWidget(self.grid_check)
        flags.addStretch()
        image_form.addRow(tr("图层"), flags)
        image_form.addRow(tr("图例"), self.legend_place)
        image_form.addRow(tr("标题"), self.title_edit)
        image_form.addRow("", self.vector_path_check)

        # ------------------------------------------------------------ 输出文件
        self.path_edit = QLineEdit(default_path)
        browse = QPushButton(tr("浏览…"))
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(tr("导出"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("取消"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        form = QFormLayout()
        form.addRow(tr("图像类型"), self.kind)
        layout.addLayout(form)
        layout.addWidget(self.pages)
        layout.addWidget(_group(tr("图像设置"), image_form))
        path_form = QFormLayout()
        path_form.addRow(tr("保存到"), path_row)
        layout.addLayout(path_form)
        layout.addWidget(buttons)

        self.kind.currentIndexChanged.connect(self.pages.setCurrentIndex)
        self.pages.setCurrentIndex(self.kind.currentIndex())
        self.size_preset.currentIndexChanged.connect(self._apply_size_preset)
        self.width_spin.valueChanged.connect(self._sync_preset_from_size)
        self.height_spin.valueChanged.connect(self._sync_preset_from_size)
        saved_preset = int(stored.value("export/preset", 0))
        if 0 <= saved_preset < self.size_preset.count():
            self.size_preset.setCurrentIndex(saved_preset)
        self._apply_size_preset()
        self._format_changed()

    # ---------------------------------------------------------------- 各类型页
    def _build_wave_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox(tr("波形内容"))
        grid = QGridLayout(group)
        self.wave_current = QCheckBox(tr("当前波形（已应用处理的波形）"))
        self.wave_current.setChecked(True)
        self.wave_current.setEnabled(False)
        self.wave_original = QCheckBox(tr("原始波形（处理前参考）"))
        self.wave_preview = QCheckBox(tr("去噪预览（尚未应用的橙色曲线）"))
        self.wave_envelope = QCheckBox(tr("包络线"))
        self.wave_fit = QCheckBox(tr("拟合曲线（含拟合区间）"))
        self.wave_region = QCheckBox(tr("选区底色"))
        self.wave_region.setChecked(True)
        self.wave_cursor = QCheckBox(tr("游标位置"))
        self.wave_cursor.setChecked(True)
        items = [
            (self.wave_current, "current"),
            (self.wave_original, "original"),
            (self.wave_preview, "preview"),
            (self.wave_envelope, "envelope"),
            (self.wave_fit, "fit"),
            (self.wave_region, "region"),
            (self.wave_cursor, "cursor"),
        ]
        for position, (box, key) in enumerate(items):
            available = key == "current" or self._available.get(key, False)
            if key in ("region", "cursor"):
                available = self._available.get(key, True)
            box.setEnabled(available)
            if not available and key not in ("current",):
                box.setText(box.text() + tr("（当前无数据）"))
            grid.addWidget(box, position // 2, position % 2)
        self.wave_original.setChecked(self._available.get("original", False))
        self.wave_preview.setChecked(self._available.get("preview", False))
        self.wave_envelope.setChecked(self._available.get("envelope", False))
        self.wave_fit.setChecked(self._available.get("fit", False))
        self.wave_region.setEnabled(self._available.get("region", True))
        self.wave_cursor.setEnabled(self._available.get("cursor", True))

        note = QLabel(
            tr("包络与拟合曲线来自“包络拟合”页的计算结果，未计算时不可选；"
            "去噪预览只有点了“检测并预览”后才有内容。")
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#607d8b;")
        layout.addWidget(group)
        layout.addWidget(note)
        return page

    def _build_spectrum_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        group = QGroupBox(tr("频谱内容"))
        form = QFormLayout(group)

        self.spectrum_scale = QComboBox()
        self.spectrum_scale.addItem(tr("dBFS（对数，推荐）"), True)
        self.spectrum_scale.addItem(tr("线性幅值 / FS"), False)

        self.spectrum_limit = QDoubleSpinBox()
        self.spectrum_limit.setRange(0.0, 100000.0)
        self.spectrum_limit.setDecimals(1)
        self.spectrum_limit.setSingleStep(500.0)
        self.spectrum_limit.setSuffix(" Hz")
        self.spectrum_limit.setSpecialValueText(tr("自动（画到奈奎斯特频率）"))
        self.spectrum_limit.setValue(0.0)

        self.spectrum_peaks = QCheckBox(tr("标注主要谱峰频率"))
        self.spectrum_peaks.setChecked(True)
        self.spectrum_harmonics = QCheckBox(tr("标出基频整数倍位置（谐波）"))
        self.spectrum_phase = QCheckBox(tr("附带相位谱子图"))

        form.addRow(tr("纵轴"), self.spectrum_scale)
        form.addRow(tr("频率上限"), self.spectrum_limit)
        form.addRow("", self.spectrum_peaks)
        form.addRow("", self.spectrum_harmonics)
        form.addRow("", self.spectrum_phase)

        note = QLabel(tr("频谱按 FFT 分析窗口计算，长音频只取居中窗口；图上频率分辨率为采样率 ÷ FFT 点数。"))
        note.setWordWrap(True)
        note.setStyleSheet("color:#607d8b;")
        layout.addWidget(group)
        layout.addWidget(note)
        return page

    def _build_spectrogram_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        group = QGroupBox(tr("时频内容"))
        form = QFormLayout(group)

        self.spectro_limit = QDoubleSpinBox()
        self.spectro_limit.setRange(0.0, 100000.0)
        self.spectro_limit.setDecimals(1)
        self.spectro_limit.setSingleStep(500.0)
        self.spectro_limit.setSuffix(" Hz")
        self.spectro_limit.setSpecialValueText(tr("自动（画到奈奎斯特频率）"))
        self.spectro_limit.setValue(0.0)

        self.spectro_floor = QDoubleSpinBox()
        self.spectro_floor.setRange(-200.0, -10.0)
        self.spectro_floor.setDecimals(0)
        self.spectro_floor.setSingleStep(5.0)
        self.spectro_floor.setSuffix(" dBFS")
        self.spectro_floor.setValue(-100.0)

        form.addRow(tr("频率上限"), self.spectro_limit)
        form.addRow(tr("色标下限"), self.spectro_floor)

        note = QLabel(tr("色标上限自动取 99.5% 分位；调低下限可以看出更弱的成分，但整图会偏亮。"))
        note.setWordWrap(True)
        note.setStyleSheet("color:#607d8b;")
        layout.addWidget(group)
        layout.addWidget(note)
        return page

    # ---------------------------------------------------------------- 交互
    def _apply_size_preset(self) -> None:
        """论文版式按物理尺寸出图：像素输入框只做展示，改由预设决定。"""
        data = self.size_preset.currentData()
        if not isinstance(data, tuple) or len(data) != 4:
            return
        layout, column, width, height = data
        paper = layout == "paper"
        self.width_spin.setEnabled(not paper)
        self.height_spin.setEnabled(not paper)
        self.background.setEnabled(not paper)
        if paper:
            pixels = PAPER_SIZES.get(column, PAPER_SIZES["single"])
            # 用 :g 而不是 :.1f——2.45 会被舍成 2.5，和 1470 px 对不上，看着像写错了。
            text = (tf('物理尺寸 {_v0:g} × {_v1:g} in，{PAPER_DPI} dpi → {_v3} × {_v4} px；刻度朝内、四边齐全、白底', _v0=(pixels[0]), _v1=(pixels[1]), PAPER_DPI=(PAPER_DPI), _v3=(int(round(pixels[0] * PAPER_DPI))), _v4=(int(round(pixels[1] * PAPER_DPI)))))
            if self.current_format() in VECTOR_FORMATS:
                text += tr("；矢量格式按物理尺寸输出，没有像素尺寸")
            self.size_note.setText(text)
        else:
            text = tr("屏幕版式：按像素出图，可选深色或透明背景")
            if self.current_format() in VECTOR_FORMATS:
                text += tr("；矢量格式的物理尺寸 = 像素 ÷ dpi")
            self.size_note.setText(text)
            if width and height:
                for spin, value in ((self.width_spin, width), (self.height_spin, height)):
                    spin.blockSignals(True)
                    spin.setValue(value)
                    spin.blockSignals(False)

    def _sync_preset_from_size(self) -> None:
        if self._is_paper():
            return
        current = (self.width_spin.value(), self.height_spin.value())
        for index, (_label, layout, _column, width, height) in enumerate(SIZE_PRESETS):
            if layout == "screen" and width and (width, height) == current:
                self.size_preset.blockSignals(True)
                self.size_preset.setCurrentIndex(index)
                self.size_preset.blockSignals(False)
                return
        self.size_preset.blockSignals(True)
        self.size_preset.setCurrentIndex(len(SIZE_PRESETS) - 1)
        self.size_preset.blockSignals(False)
        self.size_note.setText(tr("屏幕版式：自定义像素"))

    def _is_paper(self) -> bool:
        data = self.size_preset.currentData()
        return isinstance(data, tuple) and len(data) == 4 and data[0] == "paper"

    # ---------------------------------------------------------------- 格式
    def current_format(self) -> str:
        return str(self.format_combo.currentData() or "png")

    def _format_changed(self) -> None:
        """切格式：矢量时关掉「转路径」之外的像素概念，并把保存路径的后缀换过来。"""
        suffix = self.current_format()
        vector = suffix in VECTOR_FORMATS
        self.vector_path_check.setEnabled(vector)
        text = self.path_edit.text().strip()
        if text:
            current = Path(text)
            if current.suffix.lower() in (".png", ".pdf", ".svg"):
                self.path_edit.setText(str(current.with_suffix(f".{suffix}")))
        self._apply_size_preset()

    def _browse(self) -> None:
        current = self.path_edit.text().strip()
        suffix = self.current_format()
        directory = str(Path(current).parent) if current else ""
        label = dict(IMAGE_FORMATS)[suffix]
        path, _ = QFileDialog.getSaveFileName(
            self, tr("保存图像"), current or f"waveform.{suffix}", label)
        if path:
            if Path(path).suffix.lower() not in (".png", ".pdf", ".svg"):
                path += f".{suffix}"
            self.path_edit.setText(path)

    # ---------------------------------------------------------------- 结果
    def selected_kind(self) -> str:
        return str(self.kind.currentData())

    def _layout_and_column(self) -> tuple[str, str]:
        data = self.size_preset.currentData()
        if isinstance(data, tuple) and len(data) == 4:
            return str(data[0]), str(data[1])
        return "paper", "single"

    def wave_selection(self) -> dict[str, bool]:
        return {
            "original": self.wave_original.isChecked() and self.wave_original.isEnabled(),
            "preview": self.wave_preview.isChecked() and self.wave_preview.isEnabled(),
            "envelope": self.wave_envelope.isChecked() and self.wave_envelope.isEnabled(),
            "fit": self.wave_fit.isChecked() and self.wave_fit.isEnabled(),
            "region": self.wave_region.isChecked() and self.wave_region.isEnabled(),
            "cursor": self.wave_cursor.isChecked() and self.wave_cursor.isEnabled(),
        }

    def options(self) -> FigureOptions:
        layout, column = self._layout_and_column()
        place = str(self.legend_place.currentData())
        return FigureOptions(
            width_px=self.width_spin.value(),
            height_px=self.height_spin.value(),
            layout=layout,
            column=column,
            legend=place != "none",
            legend_outside=place == "outside",
            background="white" if layout == "paper" else str(self.background.currentData()),
            grid=self.grid_check.isChecked(),
            title=self.title_edit.text().strip(),
            spectrum_db=bool(self.spectrum_scale.currentData()),
            max_frequency=float(self.spectrum_limit.value()) if self.selected_kind() == KIND_SPECTRUM
            else float(self.spectro_limit.value()),
            annotate_peaks=self.spectrum_peaks.isChecked(),
            peak_count=self._peak_count,
            mark_harmonics=self.spectrum_harmonics.isChecked(),
            show_phase=self.spectrum_phase.isChecked(),
            db_floor=float(self.spectro_floor.value()),
            vector_text_as_path=self.vector_path_check.isChecked(),
        )

    def output_path(self) -> str:
        text = self.path_edit.text().strip()
        suffix = self.current_format()
        if not text:
            return ""
        target = Path(text)
        # 只有完全没写扩展名时才补；写了别的后缀就交给 accept() 去拒绝，
        # 免得 "wave.txt" 被静悄悄改成 "wave.txt.png"。
        if not target.suffix:
            text += f".{suffix}"
        return text

    def sizeHint(self):  # noqa: D102 - 让对话框默认宽一点，两列复选框不挤
        hint = super().sizeHint()
        hint.setWidth(max(hint.width(), 640))
        return hint

    # ---------------------------------------------------------------- 提交
    def accept(self) -> None:
        path = self.output_path()
        if not path:
            QMessageBox.warning(self, tr("缺少保存路径"), tr("请先选择图像保存位置。"))
            self._browse()
            return
        target = Path(path)
        if target.suffix.lower() not in (".png", ".pdf", ".svg"):
            QMessageBox.warning(self, tr("格式不支持"), tr("只支持 PNG（.png）、PDF（.pdf）、SVG（.svg）。"))
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.warning(self, tr("目录不可用"), tf('无法创建目录：{exc}', exc=(exc)))
            return
        stored = QSettings()
        stored.setValue("export/width", self.width_spin.value())
        stored.setValue("export/height", self.height_spin.value())
        stored.setValue("export/background", self.background.currentData())
        stored.setValue("export/grid", "true" if self.grid_check.isChecked() else "false")
        stored.setValue("export/legend_place", self.legend_place.currentData())
        stored.setValue("export/preset", self.size_preset.currentIndex())
        stored.setValue("export/format", self.current_format())
        stored.setValue("export/vector_text_path", "true" if self.vector_path_check.isChecked() else "false")
        super().accept()


def _group(title: str, form: QFormLayout) -> QGroupBox:
    box = QGroupBox(title)
    box.setLayout(form)
    return box


def suggest_path(source_path: Path | None, kind: str, channel_index: int = 0) -> str:
    """按源文件与图像类型给出默认输出路径。"""
    suffix = KIND_SUFFIX.get(kind, tr("图像"))
    if source_path is None:
        return str(Path.cwd() / f"{suffix}.png")
    stem = source_path.stem or "audio"
    if channel_index:
        stem = tf('{stem}_声道{_v1}', stem=(stem), _v1=(channel_index + 1))
    return str(source_path.with_name(f"{stem}_{suffix}.png"))
