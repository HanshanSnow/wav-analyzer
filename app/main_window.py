from __future__ import annotations

import os
import sys

from core.i18n import (
    LANGUAGE_SETTINGS_KEY, current_language, language_options, tf, tr,
)
from pathlib import Path
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QProcess, QRectF, QSettings, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDockWidget, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ai.assistant import AIAssistant, AIOutcome
from ai.client import OpenAICompatibleClient
from ai.tools import AnalysisTools
from core.anc import METHOD_LABELS, Diagnostics as AncDiagnostics
from core.anc import run_method as run_anc_method
from core.audio_io import AudioData, read_wav, write_wav
from core.calibration import (
    MODE_PARAMS, Calibration, dumps_profiles, find_profile, loads_profiles,
)
from core.denoise import DenoiseResult, detect_and_repair_impulses
from core.dual_channel import analyze_dual_channel
from core.batch_summary import build_summary
from core.data_export import (
    export_envelope_csv, export_peaks_csv, export_spectrogram_npz, export_spectrum_csv,
    skipped_frames,
)
from core.editor import apply_to_source, trim_range
from core.envelope import compute_envelope, evaluate_fit, fit_envelope
from core.display import min_max_downsample as _downsample_series
from core.exporter import build_report_html, export_rows_csv, save_report
from core.figure_export import (
    KIND_LABELS, FigureOptions, render_spectrogram_png, render_spectrum_png, render_waveform_png,
)
from core.launcher import pythonw_sibling
from core.project import (
    build_project, load_project, save_project, source_path_of, verify_source,
)
from core.report_i18n import (
    REPORT_AUTO,
    REPORT_EN,
    REPORT_ZH,
    get_report_language,
    set_report_language,
)
from core.spectral import MAX_SPECTROGRAM_FRAMES, fourier_analysis, stft_spectrogram
from core.statistics import (
    attach_calibration, interval_statistics, probe_time, statistics_rows,
)
from core.txt_export import file_md5, write_analysis_txt
from .audio_player import AudioPlayer
from .batch_dialog import BatchDialog
from .batch_progress import BatchProgressOverlay, BatchWorker
from .batch_summary_dialog import BatchSummaryDialog
from .busy_overlay import BusyOverlay
from .calibration_dialog import CalibrationDialog
from .chat_view import ChatView
from .data_export_dialog import DataExportDialog
from .image_export_dialog import (
    KIND_SPECTROGRAM, KIND_SPECTRUM, KIND_WAVE, ImageExportDialog, suggest_path,
)
from .settings_dialog import AISettingsDialog, load_ai_settings
from .txt_export_dialog import TxtExportDialog
from .task_worker import TaskWorker
from .workers import AIWorker

# 全览阈值：可见采样点超过该值时使用预抽稀数据，否则直接显示真实采样点。
DETAIL_LIMIT = 400_000
# 全览曲线的列数上限，兼顾形态保真与重绘速度。
OVERVIEW_COLUMNS = 6000
# 频谱与时频图共用的窗函数：值是 scipy 窗名，界面显示用中文名。
# 两者必须同步——历史上时频图写死 hann，界面换窗后频谱变了、时频图没变，很容易误读。
# 显示文案在 _window_items() 里逐个写成字面量 tr("…")，i18n 工具靠 AST 认字面量，拼出来会漏检。
SPECTRUM_WINDOWS = ("hann", "hamming", "blackman", "boxcar")


def _window_items() -> list[str]:
    return [
        tr("汉宁窗 Hann"),
        tr("海明窗 Hamming"),
        tr("布莱克曼窗 Blackman"),
        tr("矩形窗 Rectangular"),
    ]


def _report_language_items() -> list[str]:
    """报告语言下拉：顺序必须与 REPORT_LANGUAGE_CODES 一致。"""
    return [tr("跟随界面"), tr("中文"), tr("English")]


REPORT_LANGUAGE_CODES = (REPORT_AUTO, REPORT_ZH, REPORT_EN)

# 撤销栈上限：长音频每级撤销都要复制整段处理数据，必须设硬上限。
MAX_UNDO_LEVELS = 4
MAX_UNDO_BYTES = 1_200_000_000


# 显示抽稀统一由 core.display 提供：界面绘制与 PNG 导出共用同一份 min/max 规则。


def _analyze_channel(
    samples: np.ndarray,
    sample_rate: int,
    fundamental: float | None,
    valid_mask: np.ndarray,
    start_s: float,
    end_s: float,
    calibration: "Calibration | None" = None,
    window: str = "hann",
) -> dict:
    """纯计算：在线程中运行，不触碰任何 Qt 对象。

    calibration 必须由调用方在进入线程前取好（它来自界面上的下拉框），
    线程里再去读 Qt 控件是非法的。window 同理，也必须由调用方取好传进来。
    """
    fourier = fourier_analysis(samples, sample_rate, window=window,
                               fundamental_frequency=fundamental)
    spectrogram = stft_spectrogram(samples, sample_rate, window=window)
    stats = interval_statistics(samples, sample_rate, start_s, end_s, valid_mask,
                                fundamental, calibration=calibration)
    overview = _downsample_series(samples, sample_rate, OVERVIEW_COLUMNS)
    return {"fourier": fourier, "spectrogram": spectrogram, "statistics": stats, "overview": overview}


def _compute_envelope_fit(
    samples: np.ndarray,
    mask: np.ndarray,
    sample_rate: int,
    start: float,
    end: float,
    model: str,
    max_points: int = 5000,
) -> dict:
    """纯计算：只对选区（含少量余量）求包络并拟合，可在工作线程运行。"""
    x = np.asarray(samples, dtype=np.float64).reshape(-1)
    total = len(x)
    margin = min(max(1, int(round(0.5 * sample_rate))), max(0, (total - 2) // 2))
    i0 = int(np.clip(round(start * sample_rate) - margin, 0, max(0, total - 2)))
    i1 = int(np.clip(round(end * sample_rate) + margin, i0 + 2, total))
    times, envelope = compute_envelope(x[i0:i1], sample_rate)
    times = times + i0 / sample_rate

    selected = (times >= start) & (times <= end) & np.asarray(mask, dtype=bool)[i0:i1]
    indices = np.flatnonzero(selected)
    if len(indices) < 2:
        raise ValueError(tr("选区内有效包络点不足"))
    if len(indices) > max_points:
        indices = indices[np.linspace(0, len(indices) - 1, max_points).astype(int)]
    fit = fit_envelope(times[indices], envelope[indices], model)
    return {
        "times": times,
        "envelope": envelope,
        "fit": fit,
        "fit_times": times[indices],
        "span": (start, end),
    }


_PYI_ENV_PREFIX = "_PYI_"
_PYI_ENV_EXACT = ("_MEIPASS2",)


def _restart_command() -> tuple[str, list[str]]:
    """返回重启本程序用的 ``(可执行文件, 参数列表)``。

    坑：源码方式运行时 ``sys.executable`` 是 python.exe，而 ``sys.argv[0]`` 是
    ``run_app.py``。以前直接传 ``sys.argv[1:]``，重启就变成「裸解释器 + 零参数」，
    新进程找不到脚本、读完空 stdin 立即退出——用户看到的就是一切语言窗口一闪就没。
    打包后的单文件版 argv[0] 就是 exe 自身，参数才是真正的用户参数，因此两种形态
    要分开算。
    """
    if getattr(sys, "frozen", False):
        return sys.executable, list(sys.argv[1:])
    script = Path(sys.argv[0]) if sys.argv and sys.argv[0] else Path(__file__)
    if not script.is_file():
        script = Path(__file__)
    # 换用同目录的 pythonw.exe：否则切语言后新进程会带出一个控制台黑框。
    return pythonw_sibling(sys.executable), [str(script.resolve()), *sys.argv[1:]]


def _pyinstaller_free_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    """去掉 PyInstaller onefile 引导器写进环境变量的临时目录指针。

    打包成单文件运行时，引导器把解压目录塞进 ``_PYI_APPLICATION_HOME_DIR``
    等变量，子进程据此复用同一个目录、不再自己解压。重启语言时如果原样继承，
    新进程会继续占用旧进程的 ``_MEIxxxx``，旧进程退出时删不掉，
    于是弹出 "Failed to remove temporary directory"。这里把指针剥掉，
    让新进程自己解压一份，两边互不影响。源码方式运行时这些变量本来就不存在，
    函数是无副作用的空操作。
    """
    source = os.environ if environ is None else environ
    return {key: value for key, value in source.items()
            if key not in _PYI_ENV_EXACT and not key.startswith(_PYI_ENV_PREFIX)}


class _ComboWheelGuard(QObject):
    """滚轮落在下拉框/数字框/页签栏上时，转交给外层滚动区，按钮值不动。

    用户反馈的原话是「滚轮被这些控件卡住」：控件把滚轮吃掉，面板就滚不动；
    而如果放行，滚轮又会直接改掉用户填好的数值。两头都不对。
    正确做法是**不消费**，而是把同一个滚轮事件转给最近的 QAbstractScrollArea，
    让左侧工具栏照常滚动——只有控件已经获得焦点时，滚轮才用来调值。
    """

    def eventFilter(self, obj, event):  # noqa: N802 - Qt 的命名约定
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QAbstractScrollArea, QAbstractSpinBox, QComboBox, QTabBar

        if event.type() != QEvent.Type.Wheel:
            return False
        target = obj if isinstance(obj, QWidget) else None
        while target is not None and not isinstance(
                target, (QComboBox, QAbstractSpinBox, QTabBar)):
            target = target.parentWidget()
        if target is None:
            return False
        # 一律不调值：即使控件拿到了焦点，滚轮也只用来滚面板。
        # 改值请点开下拉框用鼠标选，或点数字框用上下箭头/键盘。
        # 找到外层滚动区并把滚轮转给它；找不到就当作普通滚轮放行
        area = target.parentWidget()
        while area is not None and not isinstance(area, QAbstractScrollArea):
            area = area.parentWidget()
        if area is not None:
            QApplication.sendEvent(area.viewport(), event)
            return True
        return False


_wheel_guard: "_ComboWheelGuard | None" = None


def _install_combo_wheel_guard() -> None:
    global _wheel_guard
    app = QApplication.instance()
    if app is None or _wheel_guard is not None:
        return
    _wheel_guard = _ComboWheelGuard(app)
    app.installEventFilter(_wheel_guard)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("声音实验 WAV 数据处理程序"))
        self.resize(1500, 920)
        self.audio: AudioData | None = None
        self.processed: np.ndarray | None = None
        self.reference: np.ndarray | None = None
        self.valid_mask: np.ndarray | None = None
        self.undo_stack: list[tuple] = []
        self.edit_depth = 0
        self.pending_denoise: DenoiseResult | None = None
        self.last_denoise: DenoiseResult | None = None
        self.last_anc: AncDiagnostics | None = None
        self.fourier = None
        self.envelope_values: np.ndarray | None = None
        self.envelope_times: np.ndarray | None = None
        self.envelope_span: tuple[float, float] | None = None
        self.envelope_fit = None
        self.fit_times: np.ndarray | None = None
        self.spectrogram = None
        self.statistics: dict | None = None
        self.overview: tuple[np.ndarray, np.ndarray] | None = None
        self.ai_assistant: AIAssistant | None = None
        self.ai_worker: AIWorker | None = None
        self.task: TaskWorker | None = None
        self._task_title = tr("处理中")
        self.last_ai_narrative = ""
        self.dual_result: dict | None = None
        self.edit_log: list[str] = []
        self.edit_ops: list[dict] = []
        self.batch_worker: BatchWorker | None = None
        self.last_batch_result = None
        # 关闭抗锯齿是本机千万点级重绘最有效的一档优化，线条宽度为 1 时观感损失很小。
        pg.setConfigOptions(antialias=False, background="w", foreground="#263238")
        self._wave_timer = QTimer(self)
        self._wave_timer.setSingleShot(True)
        self._wave_timer.setInterval(40)
        self._wave_timer.timeout.connect(self._refresh_wave_view)
        self._probe_timer = QTimer(self)
        self._probe_timer.setSingleShot(True)
        self._probe_timer.setInterval(50)
        self._probe_timer.timeout.connect(self.update_probe)
        self.player = AudioPlayer(self)
        self.player.positionChanged.connect(self._on_play_position)
        self.player.stateChanged.connect(self._on_play_state)
        self.player.failed.connect(lambda message: self.statusBar().showMessage(message, 6000))
        self._play_span: tuple[float, float] = (0.0, 0.0)
        self.calibration_profiles: list[Calibration] = []
        self.calibration_active = ""
        self._load_calibrations()
        self._build_ui()
        self._restore_report_language()
        self.busy = BusyOverlay(self)
        self.batch_overlay = BatchProgressOverlay(self)
        self.statusBar().showMessage(tr("请打开音频文件；原始文件始终只读"))

    # ---------------------------------------------------------------- UI 构建
    def _build_ui(self) -> None:
        central = QSplitter(Qt.Horizontal)
        central.addWidget(self._control_panel())
        central.addWidget(self._plot_tabs())
        central.setSizes([330, 1120])
        self.setCentralWidget(central)
        self._build_ai_dock()

    # ---------------------------------------------------------------- 报告语言
    def _restore_report_language(self) -> None:
        """读回上次选择的报告语言；缺省跟随界面语言。"""
        code = get_report_language()
        stored = QSettings()
        value = str(stored.value("export/report_language", REPORT_AUTO) or REPORT_AUTO)
        if value in REPORT_LANGUAGE_CODES:
            code = value
            set_report_language(code)
        index = REPORT_LANGUAGE_CODES.index(code) if code in REPORT_LANGUAGE_CODES else 0
        self.report_language_combo.blockSignals(True)
        self.report_language_combo.setCurrentIndex(index)
        self.report_language_combo.blockSignals(False)

    def _report_language_changed(self, index: int) -> None:
        if not 0 <= index < len(REPORT_LANGUAGE_CODES):
            return
        code = REPORT_LANGUAGE_CODES[index]
        set_report_language(code)
        QSettings().setValue(
            "export/report_language", code
        )

    # ---------------------------------------------------------------- 声学校准
    def _load_calibrations(self) -> None:
        stored = QSettings()
        profiles, active = loads_profiles(str(stored.value("calib/profiles", "") or ""))
        self.calibration_profiles = profiles
        self.calibration_active = active

    def _save_calibrations(self, profiles: list[Calibration], active: str) -> None:
        stored = QSettings()
        stored.setValue("calib/profiles", dumps_profiles(profiles, active))

    def _ready_profiles(self) -> list[Calibration]:
        return [item for item in self.calibration_profiles if item.ready]

    def _current_calibration(self) -> Calibration | None:
        """界面当前选中的校准；未选或参数不全时返回 None（此时不输出 dB SPL）。"""
        combo = getattr(self, "calibration_combo", None)
        if combo is None:
            return None
        name = combo.currentData()
        if not name:
            return None
        item = find_profile(self.calibration_profiles, str(name))
        return item if (item is not None and item.ready) else None

    def _refresh_calibration_ui(self) -> None:
        combo = getattr(self, "calibration_combo", None)
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("未校准（只显示 dBFS）"), "")
        for item in self._ready_profiles():
            combo.addItem(item.name, item.name)
        index = combo.findData(self.calibration_active)
        combo.setCurrentIndex(max(0, index))
        combo.blockSignals(False)
        self._update_calibration_label()

    def _update_calibration_label(self) -> None:
        item = self._current_calibration()
        if item is None:
            self.calibration_label.setText(
                tr("未校准：统计只显示 dBFS。配好灵敏度或做一次标定后，统计表才会多出声压级两行。"))
            return
        offset = item.offset_db()
        self.calibration_label.setText(f"K = {offset:+.2f} dB（dB SPL = dBFS + K）")

    def _on_calibration_changed(self, _index: int = 0) -> None:
        self.calibration_active = str(self.calibration_combo.currentData() or "")
        self._update_calibration_label()
        # 已有统计时就地重算 SPL：统计量本身没变，只是换了个加性偏移，不必重跑 FFT。
        if self.statistics is not None:
            self.statistics = attach_calibration(self.statistics, self._current_calibration())
            self._fill_statistics_table(self.statistics)

    def open_calibration_dialog(self) -> None:
        current_dbfs = None
        if self.statistics is not None:
            value = self.statistics.get("rms_dbfs")
            if isinstance(value, (int, float)):
                current_dbfs = float(value)
        dialog = CalibrationDialog(
            self, profiles=self.calibration_profiles,
            active=self.calibration_active, current_dbfs=current_dbfs)
        if dialog.exec() != QDialog.Accepted:
            return
        payload = dialog.result_payload()
        self.calibration_profiles = payload["profiles"]
        self.calibration_active = payload["active"]
        self._save_calibrations(self.calibration_profiles, self.calibration_active)
        self._refresh_calibration_ui()
        if self.statistics is not None:
            self.statistics = attach_calibration(self.statistics, self._current_calibration())
            self._fill_statistics_table(self.statistics)

    def _control_panel(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        file_group = QGroupBox(tr("文件与声道"))
        file_layout = QVBoxLayout(file_group)
        self.file_label = QLabel(tr("尚未载入文件"))
        self.file_label.setWordWrap(True)
        open_button = QPushButton(tr("打开音频"))
        open_button.clicked.connect(self.open_file)
        self.channel_combo = QComboBox()
        self.channel_combo.currentIndexChanged.connect(self._on_channel_changed)
        self.fundamental = QDoubleSpinBox()
        self.fundamental.setRange(0, 1000000)
        self.fundamental.setValue(1000)
        self.fundamental.setSuffix(" Hz")
        self.fundamental.setSpecialValueText(tr("自动估计"))
        form = QFormLayout()
        form.addRow(tr("当前声道"), self.channel_combo)
        form.addRow(tr("已知激励频率"), self.fundamental)
        project_row = QHBoxLayout()
        self.save_project_button = QPushButton(tr("保存工程…"))
        self.save_project_button.setToolTip(tr("保存源文件与操作过程；载入后可接着做，不保存处理后的音频数据"))
        self.save_project_button.clicked.connect(self.save_project_file)
        self.open_project_button = QPushButton(tr("打开工程…"))
        self.open_project_button.setToolTip(tr("载入 .wavproj 工程文件，重放其中的操作过程"))
        self.open_project_button.clicked.connect(self.open_project_file)
        project_row.addWidget(self.save_project_button)
        project_row.addWidget(self.open_project_button)
        file_layout.addWidget(self.file_label)
        self.reference_label = QLabel("")
        self.reference_label.setWordWrap(True)
        file_layout.addWidget(self.reference_label)
        file_layout.addWidget(open_button)
        file_layout.addLayout(project_row)
        file_layout.addLayout(form)
        layout.addWidget(file_group)

        calibration_group = QGroupBox(tr("声学校准"))
        calibration_layout = QVBoxLayout(calibration_group)
        self.calibration_combo = QComboBox()
        self.calibration_combo.setToolTip(tr("选中的校准用于把 dBFS 换算成 dB SPL；未校准时只显示 dBFS"))
        # 下拉里放的是配置名，别让它按最长名字把按钮挤掉
        self.calibration_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.calibration_combo.setMinimumContentsLength(10)
        self.calibration_combo.currentIndexChanged.connect(self._on_calibration_changed)
        calibration_button = QPushButton(tr("校准设置…"))
        calibration_button.setMinimumWidth(96)
        calibration_button.clicked.connect(self.open_calibration_dialog)
        calibration_row = QHBoxLayout()
        calibration_row.addWidget(self.calibration_combo, 1)
        calibration_row.addWidget(calibration_button)
        self.calibration_label = QLabel()
        self.calibration_label.setWordWrap(True)
        self.calibration_label.setStyleSheet("color: #546e7a;")
        calibration_layout.addLayout(calibration_row)
        calibration_layout.addWidget(self.calibration_label)
        layout.addWidget(calibration_group)

        batch_group = QGroupBox(tr("批量处理"))
        batch_layout = QVBoxLayout(batch_group)
        batch_note = QLabel(tr("一次处理多个音频文件：先搭步骤脚本，再选文件，后台逐个执行。"))
        batch_note.setWordWrap(True)
        batch_note.setStyleSheet("color: #546e7a;")
        self.batch_button = QPushButton(tr("批量处理…"))
        self.batch_button.setToolTip(tr("编辑处理步骤 → 选择待处理文件 → 开始处理"))
        self.batch_button.clicked.connect(self.open_batch_dialog)
        batch_layout.addWidget(batch_note)
        batch_layout.addWidget(self.batch_button)
        layout.addWidget(batch_group)

        play_group = QGroupBox(tr("播放与编辑"))
        play_layout = QVBoxLayout(play_group)
        self.play_target = QComboBox()
        self.play_target.addItems([tr("播放选区"), tr("播放全文件")])
        play_row = QHBoxLayout()
        self.play_button = QPushButton(tr("▶ 播放"))
        self.play_button.clicked.connect(self.toggle_play)
        self.stop_button = QPushButton(tr("■ 停止"))
        self.stop_button.clicked.connect(self.stop_play)
        play_row.addWidget(self.play_button)
        play_row.addWidget(self.stop_button)
        self.trim_button = QPushButton(tr("裁剪到选区"))
        self.trim_button.clicked.connect(self.trim_to_selection_async)
        self.writeback_button = QPushButton(tr("应用更改到源文件…"))
        self.writeback_button.clicked.connect(self.apply_changes_to_source)
        self.edit_label = QLabel(tr("未做编辑"))
        self.edit_label.setWordWrap(True)
        play_layout.addWidget(self.play_target)
        play_layout.addLayout(play_row)
        play_layout.addWidget(self.trim_button)
        play_layout.addWidget(self.writeback_button)
        play_layout.addWidget(self.edit_label)
        layout.addWidget(play_group)

        view_group = QGroupBox(tr("坐标与分析"))
        view_layout = QVBoxLayout(view_group)
        self.amplitude_scale = QComboBox()
        self.amplitude_scale.addItems(["Linear (AMP)", "dBFS"])
        self.amplitude_scale.currentTextChanged.connect(self.update_spectrum)
        self.window_combo = QComboBox()
        self.window_combo.addItems(_window_items())
        self.window_combo.setToolTip(tr("频谱与时频图使用同一个窗函数；换窗后自动重新分析"))
        self.window_combo.currentIndexChanged.connect(self.refresh_all_async)
        self.report_language_combo = QComboBox()
        self.report_language_combo.addItems(_report_language_items())
        self.report_language_combo.setToolTip(
            tr("影响导出的 TXT/HTML 报告与对比图文字；界面语言由上方语言按钮决定")
        )
        self.report_language_combo.currentIndexChanged.connect(self._report_language_changed)
        self.log_frequency = QCheckBox(tr("频率轴使用对数刻度"))
        self.log_frequency.toggled.connect(self.update_spectrum)
        self.probe_time_input = QDoubleSpinBox()
        self.probe_time_input.setDecimals(6)
        self.probe_time_input.setRange(0, 0)
        self.probe_time_input.setSuffix(" s")
        self.probe_time_input.setKeyboardTracking(False)
        self.probe_time_input.valueChanged.connect(lambda value: self.cursor.setValue(value))
        stats_button = QPushButton(tr("计算选区统计"))
        stats_button.clicked.connect(self.calculate_statistics_async)
        dual_button = QPushButton(tr("双通道时延与电平分析"))
        dual_button.clicked.connect(self.run_dual_channel_async)
        view_layout.addWidget(QLabel(tr("频谱幅值刻度")))
        view_layout.addWidget(self.amplitude_scale)
        view_layout.addWidget(QLabel(tr("分析窗函数")))
        view_layout.addWidget(self.window_combo)
        self.peak_count_spin = QSpinBox()
        self.peak_count_spin.setRange(1, 100)
        self.peak_count_spin.setValue(self._stored_peak_count())
        self.peak_count_spin.setToolTip(
            tr("只影响谱峰表、TXT/CSV 与频谱图的峰标注；不改 FFT、主频与 THD"))
        self.peak_count_spin.valueChanged.connect(self._peak_count_changed)
        view_layout.addWidget(QLabel(tr("谱峰数量")))
        view_layout.addWidget(self.peak_count_spin)
        view_layout.addWidget(self.log_frequency)
        view_layout.addWidget(QLabel(tr("指定时间读数")))
        view_layout.addWidget(self.probe_time_input)
        view_layout.addWidget(stats_button)
        view_layout.addWidget(dual_button)
        layout.addWidget(view_group)

        denoise_group = QGroupBox(tr("冲击检测与去噪"))
        denoise_layout = QFormLayout(denoise_group)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.5, 100)
        self.threshold.setValue(8.0)
        self.max_repair = QDoubleSpinBox()
        self.max_repair.setRange(0.1, 100)
        self.max_repair.setValue(3.0)
        self.max_repair.setSuffix(" ms")
        denoise_layout.addRow(tr("稳健阈值"), self.threshold)
        denoise_layout.addRow(tr("最长修复"), self.max_repair)
        preview_button = QPushButton(tr("检测并预览"))
        preview_button.clicked.connect(self.preview_denoise_async)
        self.apply_button = QPushButton(tr("应用预览"))
        self.apply_button.clicked.connect(self.apply_denoise_async)
        self.apply_button.setEnabled(False)
        self.close_preview_button = QPushButton(tr("关闭预览"))
        self.close_preview_button.setToolTip(tr("清除橙色预览曲线与待应用结果，处理数据不受影响"))
        self.close_preview_button.clicked.connect(self.close_denoise_preview)
        self.close_preview_button.setEnabled(False)
        preview_actions = QHBoxLayout()
        preview_actions.addWidget(self.apply_button)
        preview_actions.addWidget(self.close_preview_button)
        undo_button = QPushButton(tr("撤销上次处理"))
        undo_button.clicked.connect(self.undo_async)
        self.denoise_label = QLabel(tr("尚未检测"))
        self.denoise_label.setWordWrap(True)
        denoise_layout.addRow(preview_button)
        denoise_layout.addRow(preview_actions)
        self.anc_button = QPushButton(tr("降噪工具组…"))
        self.anc_button.setToolTip(tr("同步平均、窄带陷波与四种自适应抵消；不满足护栏时只给诊断、不改数据"))
        self.anc_button.clicked.connect(self.open_anc_tools)
        denoise_layout.addRow(self.anc_button)
        denoise_layout.addRow(undo_button)
        denoise_layout.addRow(self.denoise_label)
        layout.addWidget(denoise_group)

        envelope_group = QGroupBox(tr("包络分析"))
        envelope_layout = QVBoxLayout(envelope_group)
        self.envelope_model = QComboBox()
        self.envelope_model.addItems(["auto", "constant", "linear", "exponential"])
        envelope_button = QPushButton(tr("显示包络并拟合选区"))
        envelope_button.clicked.connect(self.fit_current_envelope_async)
        self.envelope_label = QLabel(tr("未拟合"))
        self.envelope_label.setWordWrap(True)
        envelope_layout.addWidget(self.envelope_model)
        envelope_layout.addWidget(envelope_button)
        envelope_layout.addWidget(self.envelope_label)
        layout.addWidget(envelope_group)

        export_group = QGroupBox(tr("导出"))
        export_layout = QVBoxLayout(export_group)
        for text, handler in [
            (tr("导出处理后 WAV"), self.export_processed_async),
            (tr("导出分析 TXT…"), self.export_analysis_txt),
            (tr("导出图像（PNG / PDF / SVG）…"), self.export_image),
            (tr("导出当前统计 CSV"), self.export_statistics),
            (tr("导出原始数据…"), self.export_raw_data),
            (tr("生成独立 HTML 报告"), self.export_report_async),
        ]:
            button = QPushButton(text)
            button.clicked.connect(handler)
            export_layout.addWidget(button)
        # 报告语言决定导出产物的语言，属于导出设置，放在「导出」组里更符合直觉
        export_layout.addWidget(QLabel(tr("报告语言")))
        export_layout.addWidget(self.report_language_combo)
        layout.addWidget(export_group)

        language_group = QGroupBox(tr("界面语言"))
        language_layout = QVBoxLayout(language_group)
        self.language_combo = QComboBox()
        for code, label in language_options():
            self.language_combo.addItem(label, code)
        index = self.language_combo.findData(current_language())
        if index >= 0:
            self.language_combo.setCurrentIndex(index)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        language_layout.addWidget(self.language_combo)
        language_hint = QLabel(tr("切换后程序会自动重启以应用"))
        language_hint.setWordWrap(True)
        language_layout.addWidget(language_hint)
        layout.addWidget(language_group)

        help_group = QGroupBox(tr("帮助"))
        help_layout = QVBoxLayout(help_group)
        manual_button = QPushButton(tr("使用手册…"))
        manual_button.setToolTip(tr("在软件内打开手册，可搜索关键词"))
        manual_button.clicked.connect(self.open_manual)
        help_layout.addWidget(manual_button)
        layout.addWidget(help_group)

        layout.addStretch()
        self._refresh_calibration_ui()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        return scroll

    def open_manual(self) -> None:
        """打开软件内手册窗口（QtPdf）。"""
        from .manual_viewer import ManualViewerDialog

        dialog = ManualViewerDialog(self)
        dialog.exec()

    def set_external_reference(self, path: str | Path | None, channel: int = 0) -> None:
        """指定外部参考 WAV 与声道号（0 基）；None 表示沿用内置声道。

        声道号必须与路径一起保存——否则重放时会悄悄换一路参考。
        这里只做 stat 级身份记录（不读文件内容），真正的解码/校验在工作线程里做。
        """
        self.external_reference_path = str(path) if path else None
        self.external_reference_channel = int(channel or 0)
        if self.external_reference_path:
            from core.reference import file_identity

            self.external_reference_meta = file_identity(self.external_reference_path)
        else:
            self.external_reference_meta = None
        self._update_reference_indicator()

    def _revalidate_reference_after_load(self) -> None:
        """换了文件就重新校验参考：采样率不符等情况下明确失效，而不是等到降噪时才发现。"""
        path = getattr(self, "external_reference_path", None)
        if not path or self.audio is None:
            self._update_reference_indicator()
            return
        from core.reference import file_identity

        recorded = getattr(self, "external_reference_meta", None)
        current = file_identity(path)
        if recorded is not None and current != tuple(recorded):
            # 只比大小+mtime（stat 级，微秒量级），不做全文件解码/哈希
            self.set_external_reference(None)
            self.statusBar().showMessage(
                tf("参考文件已被替换或修改，已清空：{_v0}", _v0=(Path(path).name)), 8000)
            return
        self._update_reference_indicator()

    def _restore_project_reference(self, block: dict) -> None:
        """工程里记录的参考：缺文件或内容变了都要明确报错，不能静默换数据。

        先用工程里存的 size/mtime 做**轻量身份比对**；只有旧工程没存身份时才读文件
        算哈希。真正的内容校验（解码、采样率、声道）留给降噪工作线程。
        """
        self.set_external_reference(None)
        block = block or {}
        path = str(block.get("path") or "")
        if not path:
            return
        candidate = Path(path)
        if not candidate.is_file():
            QMessageBox.warning(self, tr("参考文件找不到"),
                                tf('工程里记录的参考文件不在了：{_v0}', _v0=(path)))
            return

        from core.reference import file_identity, file_sha256

        saved_size = block.get("size")
        saved_mtime = block.get("mtime_ns")
        current = file_identity(candidate)
        changed = False
        if saved_size is not None and saved_mtime is not None:
            changed = current != (int(saved_size), int(saved_mtime))
        else:
            # 旧工程没有身份字段：只能读一次内容比对哈希（一次性成本，之后会写身份）
            expected = str(block.get("sha256") or "")
            changed = bool(expected) and file_sha256(candidate) != expected
        if changed:
            QMessageBox.warning(
                self, tr("参考文件已改变"),
                tf('参考文件与保存工程时不一致：{_v0}\n为避免用错数据，已清空参考。',
                   _v0=(path)))
            return
        self.set_external_reference(candidate, int(block.get("channel") or 0))

    def _update_reference_indicator(self) -> None:
        """左栏只读指示：外部参考有没有、是哪一路。"""
        label = getattr(self, "reference_label", None)
        if label is None:
            return
        path = getattr(self, "external_reference_path", None)
        if not path:
            label.setText(tr("参考：内置声道 / 未设置外部参考"))
            return
        label.setText(tf('参考：{_v0}（第 {_v1} 声道）',
                         _v0=(Path(path).name),
                         _v1=(int(getattr(self, "external_reference_channel", 0)) + 1)))

    def _stored_peak_count(self) -> int:
        """谱峰数量：默认 8，范围 1–100。"""
        value = QSettings().value("analysis/peak_count", 8)
        try:
            return max(1, min(100, int(value)))
        except (TypeError, ValueError):
            return 8

    def _current_peak_count(self) -> int:
        spin = getattr(self, "peak_count_spin", None)
        return spin.value() if spin is not None else self._stored_peak_count()

    def _peak_count_changed(self, value: int) -> None:
        """改峰数只刷新展示与后续导出，不重算 FFT。

        主频、THD、频率分辨率都由 FFT 决定，与"标几个峰"无关；
        重算会白白多花一次 FFT 的时间。
        """
        QSettings().setValue("analysis/peak_count", int(value))
        QSettings().sync()
        if getattr(self, "fourier", None) is not None:
            self._fill_table(self.peak_table, [
                [p["frequency_hz"], p["amplitude"], p["amplitude_dbfs"], p["phase_rad"]]
                for p in self.fourier.peaks(count=int(value))])

    def _on_language_changed(self, _index: int) -> None:
        code = str(self.language_combo.currentData() or "")
        if not code or code == current_language():
            return
        settings = QSettings()
        settings.setValue(LANGUAGE_SETTINGS_KEY, code)
        settings.sync()
        self._restart_for_language()

    def _restart_for_language(self) -> None:
        """切语言后重启进程生效。

        选择重启而不是逐个控件 retranslate：界面有上千条文案和一批模块级常量，
        重刷逻辑漏一个控件就会中英混杂，而重启一次只有百毫秒的代价。
        """
        # 临时把 PyInstaller 的临时目录指针从环境里拿掉，让新进程独立解压，
        # 否则退出时旧目录删不掉会弹警告。startDetached 用当前环境块启动子进程，
        # 所以复制一份、改完立刻还原即可。
        saved = dict(os.environ)
        program, arguments = _restart_command()
        try:
            os.environ.clear()
            os.environ.update(_pyinstaller_free_env(saved))
            started = QProcess.startDetached(program, arguments)
        finally:
            os.environ.clear()
            os.environ.update(saved)
        if started:
            QApplication.quit()
            return
        QMessageBox.information(
            self, tr("需要重启"),
            tr("语言已保存。请手动关闭并重新打开程序以应用新语言。"))

    @staticmethod
    def _curve(color: str, width: int = 1, name: str | None = None) -> pg.PlotDataItem:
        """统一构建抗重绘的曲线：裁剪到视图 + 渲染时降采样。"""
        item = pg.PlotDataItem(pen=pg.mkPen(color, width=width), name=name)
        item.setClipToView(True)
        item.setDownsampling(auto=True, method="peak")
        item.setSkipFiniteCheck(True)
        return item

    def _plot_tabs(self) -> QWidget:
        self.tabs = QTabWidget()
        # 页签栏上的滚轮由应用级 _ComboWheelGuard 统一处理（转交给滚动区）
        # 应用级过滤器：下拉框/数字框没焦点时不响应滚轮（只装一次，由应用持有）
        _install_combo_wheel_guard()
        self.wave_plot = pg.PlotWidget()
        self.wave_plot.showGrid(x=True, y=True, alpha=0.25)
        self.wave_plot.setLabel("bottom", tr("时间"), units="s")
        self.wave_plot.setLabel("left", tr("幅值"), units="FS")
        self.wave_plot.addLegend(offset=(10, 10))
        self.original_curve = self._curve("#90a4ae", name=tr("原始"))
        self.wave_curve = self._curve("#1565c0", name=tr("当前"))
        self.preview_curve = self._curve("#ef6c00", name=tr("去噪预览"))
        self.envelope_curve = self._curve("#2e7d32", width=2, name=tr("包络"))
        self.fit_curve = self._curve("#c2185b", width=2, name=tr("拟合"))
        self.fit_curve.setPen(pg.mkPen("#c2185b", width=2, style=Qt.DashLine))
        for curve in [self.original_curve, self.wave_curve, self.preview_curve,
                      self.envelope_curve, self.fit_curve]:
            self.wave_plot.addItem(curve)
        self.region = pg.LinearRegionItem([0, 0], brush=pg.mkBrush(21, 101, 192, 25))
        self.region.setZValue(10)
        self.wave_plot.addItem(self.region)
        self.cursor = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen("#6a1b9a", width=1))
        self.wave_plot.addItem(self.cursor)
        self.cursor.sigPositionChanged.connect(self._queue_probe)
        self.play_line = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen("#e53935", width=2, style=Qt.DotLine),
        )
        self.play_line.setZValue(11)
        self.play_line.setVisible(False)
        self.wave_plot.addItem(self.play_line)
        self.wave_plot.getViewBox().sigXRangeChanged.connect(self._queue_wave_refresh)
        self.probe_label = QLabel(tr("移动紫色游标读取指定时间的数据；蓝色区域用于统计、裁剪和包络拟合。"))
        self.probe_label.setWordWrap(True)
        wave_page = QWidget()
        wave_layout = QVBoxLayout(wave_page)
        wave_layout.addWidget(self.wave_plot)
        wave_layout.addWidget(self.probe_label)
        self.tabs.addTab(wave_page, tr("波形与选区"))

        fourier_page = QWidget()
        fourier_layout = QVBoxLayout(fourier_page)
        plots = QSplitter(Qt.Vertical)
        self.spectrum_plot = pg.PlotWidget()
        self.spectrum_plot.showGrid(x=True, y=True, alpha=0.25)
        self.spectrum_plot.setLabel("bottom", tr("频率"), units="Hz")
        self.spectrum_curve = self._curve("#00838f")
        self.spectrum_plot.addItem(self.spectrum_curve)
        self.phase_plot = pg.PlotWidget()
        self.phase_plot.showGrid(x=True, y=True, alpha=0.25)
        self.phase_plot.setLabel("bottom", tr("频率"), units="Hz")
        self.phase_plot.setLabel("left", tr("相位"), units="rad")
        self.phase_curve = self._curve("#8e24aa")
        self.phase_plot.addItem(self.phase_curve)
        plots.addWidget(self.spectrum_plot)
        plots.addWidget(self.phase_plot)
        fourier_layout.addWidget(plots, 3)
        self.fourier_summary = QLabel(tr("傅立叶分析：未载入数据"))
        self.fourier_summary.setWordWrap(True)
        fourier_layout.addWidget(self.fourier_summary)
        result_tables = QTabWidget()
        self.peak_table = self._table([tr("频率 / Hz"), tr("峰值振幅"), "dBFS", tr("相位 / rad")])
        self.harmonic_table = self._table([tr("次数"), tr("频率 / Hz"), tr("峰值振幅"), "dBFS", tr("相位 / rad")])
        result_tables.addTab(self.peak_table, tr("主要谱峰"))
        result_tables.addTab(self.harmonic_table, tr("谐波"))
        fourier_layout.addWidget(result_tables, 2)
        self.tabs.addTab(fourier_page, tr("傅立叶分析"))

        self.spectro_plot = pg.PlotWidget()
        self.spectro_plot.setLabel("bottom", tr("时间"), units="s")
        self.spectro_plot.setLabel("left", tr("频率"), units="Hz")
        self.spectro_image = pg.ImageItem()
        self.spectro_plot.addItem(self.spectro_image)
        self.colorbar = pg.ColorBarItem(colorMap=pg.colormap.get("viridis"))
        self.colorbar.setImageItem(self.spectro_image, insert_in=self.spectro_plot.getPlotItem())
        self.colorbar.setLevels((-100, 0))
        self.tabs.addTab(self.spectro_plot, tr("时频图"))

        stats_page = QWidget()
        stats_layout = QVBoxLayout(stats_page)
        stats_hint = QLabel(
            tr("单位 FS 指数字满幅（±1.0 为满量程）；dBFS 是相对满幅的分贝值，不是声压级 dB SPL。"
            "RMS/峰值/标准差基于选区全部有效采样点，主频与 THD 基于居中 FFT 窗口（见“计算口径说明”一行）。")
        )
        stats_hint.setWordWrap(True)
        stats_hint.setStyleSheet("color:#455a64;")
        self.stats_table = self._table([tr("统计量"), tr("数值"), tr("含义与取值说明")])
        self.stats_table.setWordWrap(True)
        self.stats_table.setColumnWidth(0, 190)
        self.stats_table.setColumnWidth(1, 120)
        stats_layout.addWidget(stats_hint)
        stats_layout.addWidget(self.stats_table, 1)
        self.tabs.addTab(stats_page, tr("区间统计"))
        return self.tabs

    def _build_ai_dock(self) -> None:
        dock = QDockWidget(tr("AI 数据助手"), self)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        page = QWidget()
        layout = QVBoxLayout(page)
        settings_button = QPushButton(tr("模型设置"))
        settings_button.clicked.connect(self.configure_ai)
        self.chat_view = ChatView()
        self.chat_view.add_welcome()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText(tr("例如：分析当前数据，检测冲击并给出处理建议"))
        self.chat_input.returnPressed.connect(self.send_ai_message)
        self.send_button = QPushButton(tr("发送"))
        self.send_button.clicked.connect(self.send_ai_message)
        report_button = QPushButton(tr("让 AI 总结当前处理并撰写说明"))
        report_button.clicked.connect(lambda: self.send_ai_message(tr("请调用所需工具分析当前数据，说明处理依据、结果和限制，供数据处理报告使用。")))
        row = QHBoxLayout()
        row.addWidget(self.chat_input)
        row.addWidget(self.send_button)
        layout.addWidget(settings_button)
        layout.addWidget(self.chat_view)
        layout.addLayout(row)
        layout.addWidget(report_button)
        dock.setWidget(page)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    @staticmethod
    def _table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    # ---------------------------------------------------------------- 后台任务
    def busy_running(self) -> bool:
        return self.task is not None

    def _request_async(self, starter) -> None:
        """登记一个后台任务启动器：同一时刻只跑一个，后到的覆盖先到的。

        为什么需要这一层：`run_task()` 在已有 worker 时返回 False，而调用方往往已经
        先换代（让在途结果作废）再启动。旧实现里这次启动就是一去不回——新请求既没
        排队，旧结果又被当过期丢掉，界面表现为「一直加载」。这里用单槽位保存**最新**
        请求，等当前 worker 结束（`_task_finished`）后再启动；重复请求自然合并成一次。
        """
        self._pending_task = starter
        self._drain_pending()

    def _drain_pending(self) -> None:
        """当前没有 worker 时，启动最新排队的请求。"""
        if self.task is not None:
            return
        starter = getattr(self, "_pending_task", None)
        self._pending_task = None
        if starter is None:
            return
        try:
            starter()
        except Exception as exc:                       # 启动器自身出错不能留下死界面
            self._set_tabs_loading(False)
            self.statusBar().clearMessage()
            QMessageBox.warning(self, tr("处理失败"), str(exc))

    def run_task(self, title: str, func, on_done, hint: str = "", progress: bool = False,
                 overlay: bool = True) -> bool:
        """在后台线程执行 func，默认显示“处理中”遮罩。返回是否成功启动。

        progress=True 时 func 会收到 progress(fraction, message) 关键字参数。
        overlay=False 用于「渐进加载」的后半段：此时主界面已经可用，
        不该再被遮罩挡住，只在状态栏与页签上提示进度。
        """
        if self.task is not None:
            return False
        self._task_overlay = bool(overlay)
        if overlay:
            self.busy.start(title, hint)
        self.statusBar().showMessage(title)
        worker = TaskWorker(func, report_progress=progress)
        self.task = worker
        self._task_handler = on_done
        self._task_title = title
        # 回调按 worker 绑定，不再走共享槽位：两个 worker 的 succeeded 若乱序到达，
        # 共享槽位会让后到的旧结果被新回调接收（A 的频谱被当成 B 的结果应用）。
        worker.succeeded.connect(
            lambda payload, w=worker, h=on_done: self._task_succeeded(w, h, payload))
        worker.failed.connect(self._task_failed)
        if progress:
            worker.progressed.connect(self._task_progressed)
        # finished 必须晚于 succeeded：只有线程真正结束后才释放引用，
        # 否则 QThread 可能在运行中被回收，导致进程直接退出（闪退）。
        worker.finished.connect(lambda w=worker: self._task_finished(w))
        worker.start()
        return True

    def _task_progressed(self, fraction: float, message: str) -> None:
        hint = f"{message}（{fraction * 100:.0f}%）"
        self.busy.set_text(f"{self._task_title}…")
        self.busy.set_hint(hint)
        self.statusBar().showMessage(hint)

    def _task_succeeded(self, worker: TaskWorker | None, handler, result) -> None:
        """按 worker 处理成功结果：只接受仍属于当前任务的那一份。"""
        if worker is not None and worker is not self.task:
            # 过期 worker（已被更新请求取代）的结果直接丢弃，绝不能再应用
            return
        self._task_handler = None
        if getattr(self, "_task_overlay", True):
            self.busy.stop()
        if handler is None:
            return
        try:
            handler(result)
        except Exception as exc:
            QMessageBox.warning(self, tr("处理结果失败"), str(exc))

    def _task_failed(self, message: str) -> None:
        self._task_handler = None
        self._pending_analysis = None
        if getattr(self, "_task_overlay", True):
            self.busy.stop()
        # 失败也要撤掉页签上的「…」，否则界面看起来像永远在算
        self._set_tabs_loading(False)
        QMessageBox.warning(self, tr("处理失败"), message)

    def _task_finished(self, worker: TaskWorker | None = None) -> None:
        if self.task is worker:
            self.task = None
        if worker is not None:
            worker.deleteLater()
        # 释放 worker 之后再启动排队中的最新请求：succeeded/failed 回调里 self.task
        # 还没清空，直接调 run_task 会被"已有任务在跑"挡回去。
        self._drain_pending()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        if hasattr(self, "busy"):
            self.busy.setGeometry(self.rect())
        if hasattr(self, "batch_overlay") and self.batch_overlay.isVisible():
            self.batch_overlay.setGeometry(self.rect())

    # ---------------------------------------------------------------- 数据访问
    def _require_audio(self) -> bool:
        if self.audio is None:
            QMessageBox.information(self, tr("请先打开文件"), tr("请先打开一个音频文件。"))
            return False
        return True

    @property
    def work_duration(self) -> float:
        if self.processed is None or self.audio is None:
            return 0.0
        return float(self.processed.shape[0] / self.audio.sample_rate)

    def current_samples(self) -> np.ndarray:
        if self.processed is None:
            raise ValueError(tr("尚未载入音频"))
        return self.processed[:, self.channel_combo.currentIndex()]

    @property
    def spectrum_window(self) -> str:
        """当前窗函数的 scipy 名；下拉越界时回落 hann。"""
        index = self.window_combo.currentIndex()
        if 0 <= index < len(SPECTRUM_WINDOWS):
            return SPECTRUM_WINDOWS[index]
        return SPECTRUM_WINDOWS[0]

    def current_valid_mask(self) -> np.ndarray:
        if self.valid_mask is None:
            raise ValueError(tr("尚未载入音频"))
        return self.valid_mask[:, self.channel_combo.currentIndex()]

    def selection_seconds(self) -> tuple[float, float, float] | None:
        """波形上框选的 (起点, 终点, 当前处理版本时长)。

        提供给批量对话框回填裁切时刻：没有音频或选区为空时返回 None，
        对话框据此把按钮置灰，而不是塞 0–0 进去。
        """
        if self.processed is None or self.audio is None:
            return None
        duration = self.work_duration
        start, end = (float(value) for value in self.region.getRegion())
        start = max(0.0, min(start, duration))
        end = max(0.0, min(end, duration))
        if end - start <= 1e-6:
            return None
        return start, end, duration

    def current_reference(self) -> np.ndarray | None:
        if self.reference is None:
            return None
        return self.reference[:, self.channel_combo.currentIndex()]

    # ---------------------------------------------------------------- 载入
    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("打开音频"), "", tr("音频文件 (*.wav *.flac *.aiff *.aif)"))
        if path:
            self.load_audio_async(path)

    # ---------------------------------------------------------------- 渐进加载
    def _next_generation(self) -> int:
        """开启新一轮分析：任何在途的旧结果都会被丢弃。

        没有它的话，先载入大文件、再立刻切声道，旧文件的慢结果会覆盖新选择。
        """
        self._analysis_generation = getattr(self, "_analysis_generation", 0) + 1
        return self._analysis_generation

    def _generation(self) -> int:
        return getattr(self, "_analysis_generation", 0)

    def _set_tabs_loading(self, loading: bool) -> None:
        """在傅立叶/时频/统计页签标题上加省略号，表示该项还在后台算。"""
        base = getattr(self, "_tab_titles", None)
        if base is None:
            base = [self.tabs.tabText(i) for i in range(self.tabs.count())]
            self._tab_titles = base
        for index in (1, 2, 3):
            if index < len(base):
                self.tabs.setTabText(index, base[index] + (" …" if loading else ""))

    def load_audio_async(self, path: str | Path) -> None:
        """两段式载入：先出元数据与波形，再单独算频谱/时频/统计。

        以前要等读取、质检、FFT、STFT、统计全部算完才有画面；长文件下界面
        长时间空白。现在第一段只读文件，第二段在后台算派生结果，期间界面可用、
        页签上标省略号。
        """
        source = Path(path)
        generation = self._next_generation()
        self._set_tabs_loading(True)

        def start() -> None:
            if generation != self._generation():
                return

            def work():
                audio = read_wav(source)
                return {"audio": audio, "quality": audio.quality_report()}

            def done(payload):
                if generation != self._generation():
                    return  # 已有更新的载入请求，丢弃这批元数据
                self._apply_loaded_meta(payload)
                self._start_analysis_stage(generation)

            self.run_task(
                tr("正在读取音频…"), work, done,
                hint=tf('{_v0}；长文件读取可能需要数秒', _v0=(source.name)),
            )

        self._request_async(start)

    def _start_analysis_stage(self, generation: int) -> bool:
        """第二阶段：在当前样本上算频谱、时频与统计（不挡界面）。

        通过 `_request_async` 排队：可能在第一阶段 worker 尚未结束时被调用，
        此时立刻跑会被 `run_task` 挡回，页签会永远停在「…」。
        """
        if self.audio is None:
            self._set_tabs_loading(False)
            return False

        def start() -> None:
            if generation != self._generation() or self.audio is None:
                return
            channel = self.channel_combo.currentIndex()
            samples = self.processed[:, channel]
            mask = self.valid_mask[:, channel]
            sample_rate = self.audio.sample_rate
            fundamental = self.fundamental.value() or None
            calibration = self._current_calibration()
            window = self.spectrum_window
            start_s, end_s = self.region.getRegion()

            def work():
                return _analyze_channel(samples, sample_rate, fundamental, mask,
                                        start_s, end_s, calibration, window)

            def done(payload):
                if generation != self._generation():
                    return
                self._apply_analysis(payload)
                self._set_tabs_loading(False)

            self.run_task(tr("正在计算频谱与时频…"), work, done,
                          hint=tr("傅立叶谱、时频图与统计量"), overlay=False)

        self._request_async(start)
        return True

    def load_audio(self, path: str | Path) -> None:
        """同步载入，供测试与脚本调用；界面入口使用 load_audio_async。"""
        generation = self._next_generation()
        audio = read_wav(path)
        self._apply_loaded_meta({"audio": audio, "quality": audio.quality_report()})
        channel = self.channel_combo.currentIndex()
        self._apply_analysis(_analyze_channel(
            self.processed[:, channel], audio.sample_rate,
            self.fundamental.value() or None, self.valid_mask[:, channel],
            0.0, audio.duration, self._current_calibration(), self.spectrum_window))
        self._set_tabs_loading(False)
        self._analysis_generation = generation

    def _apply_loaded_meta(self, payload: dict) -> None:
        """只应用元数据与波形：这一步要快到用户立刻看到东西。"""
        audio: AudioData = payload["audio"]
        self.audio = audio
        # 原始数据只保留一份：reference 直接引用 audio.samples（全程不原地修改），
        # processed 保留可编辑副本。千万点级文件可省下数百 MB。
        self.reference = audio.samples
        self.processed = audio.samples.copy()
        self.valid_mask = np.ones(audio.samples.shape, dtype=bool)
        self.undo_stack.clear()
        self.edit_log.clear()
        self.edit_ops.clear()
        self.edit_depth = 0
        self.pending_denoise = None
        self.last_denoise = None
        self.envelope_values = None
        self.envelope_times = None
        self.envelope_span = None
        self.envelope_fit = None
        self.fit_times = None
        # 分析结果留给第二段（渐进加载）填充；同步路径由 _apply_loaded 补齐
        self.statistics = None
        self.fourier = None
        self.overview = None
        self.last_ai_narrative = ""
        self.dual_result: dict | None = None
        self.ai_assistant = None

        self.channel_combo.blockSignals(True)
        self.channel_combo.clear()
        self.channel_combo.addItems([tf('声道 {_v0}', _v0=(i + 1)) for i in range(audio.channels)])
        self.channel_combo.setCurrentIndex(0)
        self.channel_combo.blockSignals(False)

        quality = payload["quality"][0]
        self.file_label.setText(
            tf('{_v0}\n{_v1:.3f} s | {_v2} Hz | {_v3} 声道 | {_v4}\n峰值 {_v5:.4f}，RMS {_v6:.4f}', _v0=(audio.source_path.name), _v1=(audio.duration), _v2=(audio.sample_rate), _v3=(audio.channels), _v4=(audio.subtype), _v5=(quality['peak']), _v6=(quality['rms']))
            + (tr("\n警告：可能存在削顶") if quality["clipping_warning"] else "")
        )
        self.preview_curve.clear()
        self.envelope_curve.clear()
        self.fit_curve.clear()
        self.apply_button.setEnabled(False)
        self.close_preview_button.setEnabled(False)
        self._reset_time_axis(audio.duration)
        # 清空派生视图：第二段算完后由 _apply_analysis 重新填
        self._fill_table(self.peak_table, [])
        self._fill_table(self.harmonic_table, [])
        self.fourier_summary.setText("")
        self.stats_table.setRowCount(0)
        self._render_wave()
        self._update_edit_label()
        self.statusBar().showMessage(
            tf('已载入 {_v0}｜{_v1:.1f} s / {_v2} Hz；正在计算频谱与时频…', _v0=(audio.source_path), _v1=(audio.duration), _v2=(audio.sample_rate)), 8000)

        self._revalidate_reference_after_load()

    def _apply_loaded(self, payload: dict) -> None:
        """兼容入口：一次性应用元数据 + 分析结果（供测试与旧调用方）。"""
        self._apply_loaded_meta(payload)
        self._apply_analysis(payload)

    def _reset_time_axis(self, duration: float) -> None:
        self.region.setRegion([0, duration])
        self.region.setBounds([0, duration])
        self.probe_time_input.setRange(0, max(0.0, duration - 1e-6))
        self.probe_time_input.setValue(0)
        self.cursor.setValue(0)
        self.cursor.setBounds([0, duration])
        self.play_line.setVisible(False)

    # ---------------------------------------------------------------- 刷新
    def refresh_all_async(self) -> bool:
        if self.audio is None or self.processed is None:
            return False
        # 每次重新分析都换代：上一次的在途结果（可能属于旧声道/旧选区）直接作废
        generation = self._next_generation()
        self._set_tabs_loading(True)

        def start() -> None:
            if generation != self._generation() or self.audio is None:
                return
            # 快照放到真正启动时再取：排队期间数据可能已被撤销/编辑改过，
            # 提前取视图会让分析读到新旧混合的状态。
            channel = self.channel_combo.currentIndex()
            samples = self.processed[:, channel]
            mask = self.valid_mask[:, channel]
            sample_rate = self.audio.sample_rate
            fundamental = self.fundamental.value() or None
            calibration = self._current_calibration()
            window = self.spectrum_window
            start_s, end_s = self.region.getRegion()

            def done(payload):
                if generation != self._generation():
                    return
                self._apply_analysis(payload)
                self._set_tabs_loading(False)

            self.run_task(
                tr("正在重新分析当前声道…"),
                lambda: _analyze_channel(samples, sample_rate, fundamental, mask, start_s, end_s,
                                         calibration, window),
                done,
                hint=tr("傅立叶谱、时频图与统计量"),
            )

        self._request_async(start)
        return True

    def refresh_all(self) -> None:
        """同步刷新，供测试与内部调用。"""
        if self.audio is None or self.processed is None:
            return
        self.statistics = None
        self.envelope_values = None
        self.envelope_times = None
        self.envelope_span = None
        self.envelope_fit = None
        self.fit_times = None
        self.envelope_curve.clear()
        self.fit_curve.clear()
        start_s, end_s = self.region.getRegion()
        payload = _analyze_channel(
            self.current_samples(), self.audio.sample_rate,
            self.fundamental.value() or None, self.current_valid_mask(), start_s, end_s,
            self._current_calibration(), self.spectrum_window)
        self._apply_analysis(payload)

    def _apply_analysis(self, payload: dict) -> None:
        self.fourier = payload["fourier"]
        self.statistics = payload["statistics"]
        self.overview = payload["overview"]
        self.update_spectrum()
        self.update_spectrogram(payload["spectrogram"])
        self._fill_statistics_table(self.statistics)
        self._render_wave()

    # ---------------------------------------------------------------- 波形绘制
    def _plot_columns(self) -> int:
        try:
            width = float(self.wave_plot.getViewBox().width())
        except Exception:
            width = 0.0
        if not np.isfinite(width) or width < 50:
            width = 1200.0
        return int(max(2000, min(40000, width * 2)))

    def _queue_wave_refresh(self, *_args) -> None:
        if self.audio is not None:
            self._wave_timer.start()

    def _render_wave(self) -> None:
        """重置视图到全览并绘制。"""
        if self.audio is None or self.processed is None:
            return
        self._wave_timer.stop()
        duration = self.work_duration
        self.wave_plot.setXRange(0, max(duration, 1e-6), padding=0)
        x = self.current_samples()
        low, high = float(np.min(x)), float(np.max(x))
        if high - low < 1e-9:
            low, high = low - 0.1, high + 0.1
        self.wave_plot.setYRange(low, high, padding=0.1)
        self._refresh_wave_view()

    def _refresh_wave_view(self) -> None:
        """按当前视图范围选择绘制策略：全览用预抽稀，放大时显示真实采样点。"""
        if self.audio is None or self.processed is None:
            return
        sample_rate = self.audio.sample_rate
        x = self.current_samples()
        total = len(x)
        try:
            x0, x1 = self.wave_plot.getViewBox().viewRange()[0]
        except Exception:
            x0, x1 = 0.0, self.work_duration
        i0 = int(np.clip(np.floor(x0 * sample_rate), 0, max(0, total - 2)))
        i1 = int(np.clip(np.ceil(x1 * sample_rate), i0 + 2, total))
        visible = i1 - i0

        if visible <= DETAIL_LIMIT:
            times = np.arange(i0, i1) / sample_rate
            self.wave_curve.setData(times, x[i0:i1])
            ref = self.current_reference()
            if self.edit_depth > 0 and ref is not None:
                self.original_curve.setData(times, ref[i0:i1])
                self.original_curve.setVisible(True)
            else:
                self.original_curve.setVisible(False)
        else:
            if self.overview is not None:
                times, values = self.overview
            else:
                times, values = _downsample_series(x, sample_rate, self._plot_columns())
            self.wave_curve.setData(times, values)
            ref = self.current_reference()
            if self.edit_depth > 0 and ref is not None:
                self.original_curve.setData(*_downsample_series(ref, sample_rate, self._plot_columns()))
                self.original_curve.setVisible(True)
            else:
                self.original_curve.setVisible(False)

    def update_waveform(self) -> None:
        """兼容旧调用点。"""
        self._render_wave()

    # ---------------------------------------------------------------- 频谱与时频
    def update_spectrum(self) -> None:
        if self.fourier is None or self.audio is None:
            return
        result = self.fourier
        is_db = self.amplitude_scale.currentText() == "dBFS"
        amplitudes = result.amplitude_dbfs if is_db else result.amplitude
        self.spectrum_curve.setData(result.frequencies, amplitudes)
        self.phase_curve.setData(result.frequencies, result.phase)
        log_x = self.log_frequency.isChecked()
        self.spectrum_plot.setLogMode(x=log_x, y=False)
        self.phase_plot.setLogMode(x=log_x, y=False)
        self.spectrum_plot.setLabel("left", tr("幅值"), units="dBFS" if is_db else "FS")
        if not log_x:
            self.spectrum_plot.setXRange(0, self.audio.sample_rate / 2, padding=0)
        scope = ""
        if getattr(result, "analyzed_samples", 0) and getattr(result, "total_samples", 0):
            if result.analyzed_samples < result.total_samples:
                scope = (
                    tf(' 分析窗口 {_v0:.3f}–{_v1:.3f} s（{_v2:,}/{_v3:,} 点，频率分辨率 {_v4:.4g} Hz）。 主频/THD 仅基于该窗口；RMS 等统计量使用完整选区。', _v0=(result.analysis_offset), _v1=(result.analysis_offset + result.analyzed_samples / self.audio.sample_rate), _v2=(result.analyzed_samples), _v3=(result.total_samples), _v4=(self.audio.sample_rate / result.n_fft))
                )
        self.fourier_summary.setText(
            tf('主频 {_v0:.4f} Hz；主频峰值振幅 {_v1:.6g} FS；THD {_v2:.4%}；窗函数 {_v3}；FFT 点数 {_v4}。{scope} dBFS 不等于 dB SPL。', _v0=(result.main_frequency), _v1=(result.main_amplitude), _v2=(result.thd), _v3=(result.window), _v4=(result.n_fft), scope=(scope))
        )
        self._fill_table(self.peak_table, [[p["frequency_hz"], p["amplitude"], p["amplitude_dbfs"], p["phase_rad"]] for p in result.peaks(count=self._current_peak_count())])
        self._fill_table(self.harmonic_table, [[h["order"], h["frequency_hz"], h["amplitude"], h["amplitude_dbfs"], h["phase_rad"]] for h in result.harmonics()])

    def update_spectrogram(self, data=None) -> None:
        if self.audio is None:
            return
        if data is None:
            data = stft_spectrogram(self.current_samples(), self.audio.sample_rate,
                                    window=self.spectrum_window)
        times, frequencies, magnitude = data
        # 留存一份供导出时频图使用，避免再次做 STFT。
        self.spectrogram = (times, frequencies, magnitude)
        levels = (
            float(np.percentile(magnitude, 5)),
            float(np.percentile(magnitude, 99.5)),
        )
        self.spectro_image.setImage(magnitude.T, autoLevels=False, levels=levels)
        self.spectro_image.setRect(
            QRectF(float(times[0]), 0, float(times[-1] - times[0]), float(frequencies[-1])))
        self.spectro_plot.setXRange(float(times[0]), float(times[-1]), padding=0)
        self.spectro_plot.setYRange(0, float(frequencies[-1]), padding=0)

    def _fill_table(self, table: QTableWidget, rows: list[list]) -> None:
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                text = f"{value:.7g}" if isinstance(value, (float, np.floating)) else str(value)
                table.setItem(row_index, column, QTableWidgetItem(text))

    def _fill_statistics_table(self, stats: dict) -> None:
        """统计量以中文名 + 数值 + 释义三列展示，避免只看英文变量名产生歧义。"""
        table = self.stats_table
        rows = statistics_rows(stats)
        table.setRowCount(len(rows))
        for row_index, (key, label, value, note) in enumerate(rows):
            if key == "analysis_scope":
                # 口径说明是整句话，放在释义列更易读。
                value_text, note_text = "—", str(value)
            else:
                value_text = f"{value:.7g}" if isinstance(value, (float, np.floating)) else str(value)
                note_text = note
            table.setItem(row_index, 0, QTableWidgetItem(label))
            table.setItem(row_index, 1, QTableWidgetItem(value_text))
            table.setItem(row_index, 2, QTableWidgetItem(note_text))
        table.resizeColumnToContents(0)
        table.setColumnWidth(1, 130)
        table.setColumnWidth(2, max(320, table.viewport().width() - 340))

    # ---------------------------------------------------------------- 统计与读数
    def calculate_statistics(self) -> None:
        if not self._require_audio():
            return
        try:
            start, end = self.region.getRegion()
            self.statistics = interval_statistics(
                self.current_samples(), self.audio.sample_rate, start, end,
                self.current_valid_mask(), self.fundamental.value() or None,
                calibration=self._current_calibration(),
            )
            self._fill_statistics_table(self.statistics)
        except Exception as exc:
            QMessageBox.warning(self, tr("统计失败"), str(exc))

    def calculate_statistics_async(self) -> None:
        if not self._require_audio() or self.busy_running():
            return
        samples = self.current_samples()
        mask = self.current_valid_mask()
        sample_rate = self.audio.sample_rate
        fundamental = self.fundamental.value() or None
        calibration = self._current_calibration()
        start, end = self.region.getRegion()

        def work():
            return interval_statistics(samples, sample_rate, start, end, mask, fundamental,
                                       calibration=calibration)

        def done(stats):
            self.statistics = stats
            self._fill_statistics_table(stats)
            self.tabs.setCurrentIndex(3)
            self.statusBar().showMessage(tr("选区统计已更新"), 4000)

        self.run_task(tr("正在计算选区统计…"), work, done, hint=f"{start:.3f}–{end:.3f} s")

    def _queue_probe(self, *_args) -> None:
        self._probe_timer.start()

    def update_probe(self) -> None:
        if self.audio is None:
            return
        try:
            values = probe_time(self.current_samples(), self.audio.sample_rate, float(self.cursor.value()))
            self.probe_label.setText("；".join(f"{key}={value:.6g}" for key, value in values.items()))
        except Exception:
            pass

    # ---------------------------------------------------------------- 去噪
    def _denoise_params(self) -> tuple[np.ndarray, int, float, float]:
        """在主线程取出参数，避免工作线程触碰任何控件。"""
        return (
            self.current_samples(),
            self.audio.sample_rate,
            float(self.threshold.value()),
            float(self.max_repair.value()),
        )

    def preview_denoise(self) -> None:
        """同步检测预览；界面入口见 preview_denoise_async。"""
        if not self._require_audio():
            return
        samples, sample_rate, threshold, max_repair = self._denoise_params()
        result = detect_and_repair_impulses(
            samples, sample_rate, threshold, max_repair_ms=max_repair)
        self._show_denoise_preview(result)

    def preview_denoise_async(self) -> None:
        if not self._require_audio() or self.busy_running():
            return
        samples, sample_rate, threshold, max_repair = self._denoise_params()
        columns = self._plot_columns()

        def work(progress=None):
            result = detect_and_repair_impulses(
                samples, sample_rate, threshold, max_repair_ms=max_repair,
                progress=progress)
            if progress is not None:
                progress(0.98, tr("生成预览曲线"))
            times, values = _downsample_series(result.cleaned, sample_rate, columns)
            return result, times, values

        def done(payload):
            result, times, values = payload
            self._show_denoise_preview(result, times, values)

        self.run_task(
            tr("正在检测冲击信号…"), work, done,
            hint=tr("长音频需要数秒，期间请不要关闭窗口"),
            progress=True,
        )

    def _show_denoise_preview(self, result: DenoiseResult, times=None, values=None) -> None:
        self.pending_denoise = result
        # 记下这份预览是哪个声道算出来的：换声道后绝不能拿它去覆盖另一个声道
        self.pending_denoise_channel = int(self.channel_combo.currentIndex())
        self.pending_denoise_params = {
            "threshold": float(self.threshold.value()),
            "max_repair_ms": float(self.max_repair.value()),
        }
        sample_rate = self.audio.sample_rate
        if times is None or values is None:
            times, values = _downsample_series(result.cleaned, sample_rate, self._plot_columns())
        self.preview_curve.setData(times, values)
        self.denoise_label.setText(
            tf('检测 {_v0} 段：修复 {_v1}，排除 {_v2}。\n', _v0=(len(result.events)), _v1=(result.repaired_count), _v2=(result.excluded_count))
            + "\n".join(
                f"{e.start_sample / sample_rate:.4f}–{e.end_sample / sample_rate:.4f} s"
                for e in result.events[:8])
        )
        self.apply_button.setEnabled(True)
        self.close_preview_button.setEnabled(True)
        self.statusBar().showMessage(
            tf('预览完成：{_v0} 段冲击（橙色曲线为预览，未写入数据）', _v0=(len(result.events))), 6000)

    def _on_channel_changed(self, *_args) -> None:
        """切换声道：丢弃上一声道的去噪预览，再刷新分析。

        预览结果是与具体声道绑定的；留着它会让「应用预览」把声道 A 的处理写进
        声道 B（BUG-001）。这里直接作废，用户要重新检测一次。
        """
        if self.pending_denoise is not None:
            self.pending_denoise = None
            self.preview_curve.clear()
            self.apply_button.setEnabled(False)
            self.close_preview_button.setEnabled(False)
            self.denoise_label.setText(tr("已切换声道，上一声道的预览已丢弃"))
        self.refresh_all_async()

    def _preview_active(self) -> bool:
        data = self.preview_curve.xData
        return data is not None and len(data) > 0

    def close_denoise_preview(self) -> None:
        """丢弃待应用的预览结果，只清界面，不改动任何数据。"""
        if self.busy_running():
            return
        had_preview = self.pending_denoise is not None or self._preview_active()
        self.pending_denoise = None
        self.preview_curve.clear()
        self.apply_button.setEnabled(False)
        self.close_preview_button.setEnabled(False)
        self.denoise_label.setText(tr("预览已关闭，处理数据未改动") if had_preview else tr("尚未检测"))
        self.statusBar().showMessage(tr("已关闭去噪预览（橙色曲线），数据未做任何修改"), 4000)

    def _push_undo(self, kind: str = "edit", params: dict | None = None) -> None:
        # reference 全程只做整体替换、不原地改写，因此按引用保存即可，
        # 无需为每一级撤销各留一份原始波形（千万点级约 350 MB/份）。
        self.undo_stack.append((
            self.processed.copy(), self.valid_mask.copy(), self.reference, self.edit_depth,
        ))
        self.edit_log.append(kind)
        self.edit_ops.append({"kind": kind, "params": dict(params or {})})
        self._trim_undo_stack()

    def _trim_undo_stack(self) -> None:
        """撤销栈按层数与总字节数双重限制，避免长音频连续编辑把内存吃光。"""
        while len(self.undo_stack) > MAX_UNDO_LEVELS:
            self.undo_stack.pop(0)
            if self.edit_log:
                self.edit_log.pop(0)
            if self.edit_ops:
                self.edit_ops.pop(0)
        while len(self.undo_stack) > 1 and self._undo_bytes() > MAX_UNDO_BYTES:
            self.undo_stack.pop(0)
            if self.edit_log:
                self.edit_log.pop(0)
            if self.edit_ops:
                self.edit_ops.pop(0)

    def _undo_bytes(self) -> int:
        return sum(
            entry[0].nbytes + entry[1].nbytes for entry in self.undo_stack
        )

    def _commit_denoise(self, result: DenoiseResult, channel: int) -> None:
        """只提交数组与状态，不产生任何 Qt 调用，可安全地在工作线程执行。"""
        params = dict(getattr(self, "pending_denoise_params", {}) or {})
        params["channel"] = int(channel)
        self._push_undo("denoise", params)
        self.processed[:, channel] = result.cleaned
        self.valid_mask[:, channel] = result.valid_mask
        self.last_denoise = result
        self.pending_denoise = None

    def apply_denoise(self) -> None:
        """同步应用预览；界面入口见 apply_denoise_async。"""
        if self.pending_denoise is None or self.audio is None:
            return
        result = self.pending_denoise
        self._commit_denoise(result, self.channel_combo.currentIndex())
        self.edit_depth += 1
        self.preview_curve.clear()
        self.apply_button.setEnabled(False)
        self.close_preview_button.setEnabled(False)
        self.refresh_all()
        self._update_edit_label()
        self.statusBar().showMessage(tr("已应用到处理版本；原始 WAV 未修改"), 5000)

    def apply_denoise_async(self) -> bool:
        if self.pending_denoise is None or self.audio is None or self.busy_running():
            return False
        result = self.pending_denoise
        channel = self.channel_combo.currentIndex()
        sample_rate = self.audio.sample_rate
        fundamental = self.fundamental.value() or None
        calibration = self._current_calibration()
        window = self.spectrum_window
        start, end = self.region.getRegion()

        def work():
            self._commit_denoise(result, channel)
            return _analyze_channel(
                self.processed[:, channel], sample_rate, fundamental,
                self.valid_mask[:, channel], start, end, calibration, window)

        def done(payload):
            self.edit_depth += 1
            self.preview_curve.clear()
            self.apply_button.setEnabled(False)
            self.close_preview_button.setEnabled(False)
            self._apply_analysis(payload)
            self._update_edit_label()
            self.statusBar().showMessage(tr("已应用到处理版本；原始 WAV 未修改"), 5000)

        self.run_task(tr("正在应用去噪结果…"), work, done, hint=tr("重新计算频谱与统计量"))
        return True

    # ---------------------------------------------------------------- 降噪工具组
    def open_anc_tools(self) -> None:
        if not self._require_audio() or self.busy_running():
            return
        from .anc_dialog import AncToolsDialog

        dialog = AncToolsDialog(
            self, channels=int(self.audio.channels),
            selection=self.selection_seconds(),
            sample_rate=int(self.audio.sample_rate),
            external_reference=getattr(self, "external_reference_path", None),
            reference_channel=getattr(self, "external_reference_channel", 0))
        if dialog.exec() != QDialog.Accepted:
            return
        self.set_external_reference(dialog.reference_path(), dialog.reference_channel())
        params = dialog.params()
        params.setdefault("options", {})["reference_channel"] = dialog.reference_channel()
        self.apply_anc_tools_async(params)

    def _anc_summary(self, outcome) -> str:
        diag = outcome.diagnostics
        label = METHOD_LABELS.get(diag.method, diag.method)
        lines = [tf("方法：{_v0}", _v0=(label))]
        if diag.erle_db is not None:
            lines.append(tf("全段 ERLE：{_v0:.1f} dB", _v0=(diag.erle_db)))
        if diag.erle_holdout_db is not None:
            lines.append(tf("留出段 ERLE：{_v0:.1f} dB", _v0=(diag.erle_holdout_db)))
        if diag.delta_level_db is not None:
            lines.append(tf("主频幅值变化：{_v0:+.2f} dB", _v0=(diag.delta_level_db)))
        if diag.u_c_db is not None:
            lines.append(tf("合成不确定度：{_v0:.2f} dB", _v0=(diag.u_c_db)))
        if diag.noise_span is not None:
            lines.append(tf("噪声段：{_v0:.3f}–{_v1:.3f} s",
                            _v0=(diag.noise_span[0]), _v1=(diag.noise_span[1])))
        if diag.blocked:
            lines.append(tf("未应用：{_v0}", _v0=(diag.blocked)))
        return "\n".join(lines)

    def apply_anc_tools(self, spec: dict) -> None:
        """同步应用；界面入口见 apply_anc_tools_async。"""
        self.last_anc_spec = dict(spec or {})
        outcome = self._anc_compute(
            spec,
            channel=int(self.channel_combo.currentIndex()),
            sample_rate=int(self.audio.sample_rate),
            channels=int(self.audio.channels),
            fundamental=self.fundamental.value() or None,
            processed=self.processed,
            duration=self.work_duration,
            external_reference=getattr(self, "external_reference_path", None),
        )
        self._anc_commit(outcome)

    def _anc_compute(self, spec: dict, *, channel: int, sample_rate: int, channels: int,
                     fundamental: float | None, processed, duration: float,
                     external_reference: str | None = None):
        """纯计算：只接收快照参数，**不读任何 Qt 控件**。

        它会在工作线程里被调用（见 apply_anc_tools_async），而 Qt 控件只能在
        界面线程访问（BUG-004）。所需状态由调用方在启动线程前快照好传进来。
        """
        method = str(spec.get("method", "ls_frozen"))
        options = dict(spec.get("options") or {})
        with_ref = channels > 1
        other = 1 if channel == 0 else 0
        target = processed[:, channel].copy()
        reference = processed[:, other].copy() if with_ref else None
        align_info = None
        external = None
        if external_reference:
            from core.reference import align_reference, load_reference_cached

            external = load_reference_cached(
                external_reference, sample_rate=sample_rate,
                channel=int(options.get("reference_channel", 0)))
            if method == "noise_profile":
                # 独立噪声画像：参考是整段噪声谱，不需要与目标逐点对齐
                reference = external.samples.copy()
            else:
                # 对齐类方法：起点不齐或重叠太少时 align_reference 会抛 ReferenceError
                reference, align_info = align_reference(external.samples, target, sample_rate)
        segment = spec.get("segment")
        span = None
        if segment is not None:
            start = max(0.0, min(float(segment[0]), duration))
            end = min(float(segment[1]), duration)
            if end - start >= 1e-3:
                span = (int(round(start * sample_rate)), int(round(end * sample_rate)))

        # 对齐类方法参考比目标短时只处理重叠段；noise_profile 用整段参考、不切目标
        if method == "noise_profile":
            used = target
        else:
            used = target if reference is None else target[: reference.size]
        if span is not None:
            lo, hi = span
            hi = min(hi, used.size)
            lo = min(lo, max(0, hi - 1))
            span = (lo, hi) if hi - lo >= 2 else None

        outcome = run_anc_method(method, used, reference, sample_rate,
                                 fundamental=fundamental, segment=span, params=options)
        if external is not None and method == "noise_profile":
            outcome.diagnostics.notes.append(
                tf("参考 {_v0}；第 {_v1} 声道；独立噪声画像不做逐点对齐。",
                   _v0=(external.path.name), _v1=(external.channel + 1)))
        if align_info is not None:
            if outcome.applied and used.size < target.size:
                from core.anc import Outcome

                cleaned = target.copy()
                cleaned[: used.size] = outcome.cleaned
                outcome = Outcome(cleaned, outcome.diagnostics)
            note_parts = [tf("参考 {_v0}", _v0=(external.path.name)),
                          tf("第 {_v0} 声道", _v0=(external.channel + 1)),
                          tf("起点差 {_v0} 点", _v0=(align_info["lag_samples"]))]
            if align_info["unprocessed_frames"]:
                note_parts.append(tf("未覆盖的 {_v0:,} 点保持原样",
                                     _v0=(align_info["unprocessed_frames"])))
            outcome.diagnostics.notes.append("；".join(note_parts) + "。")
        return outcome

    def _anc_commit(self, outcome) -> None:
        diag = outcome.diagnostics
        self.last_anc = diag
        summary = self._anc_summary(outcome)
        self.denoise_label.setText(summary)
        if not outcome.applied:
            QMessageBox.warning(self, tr("降噪没有应用"), summary)
            self.statusBar().showMessage(tr("降噪未应用：数据未改动"), 5000)
            return
        channel = self.channel_combo.currentIndex()
        self._push_undo("denoise_tools", dict(getattr(self, "last_anc_spec", {}) or {}))
        self.processed[:, channel] = outcome.cleaned
        self.edit_depth += 1
        self._update_edit_label()
        self.statusBar().showMessage(tr("已应用降噪（可撤销）；原始 WAV 未修改"), 5000)

    def apply_anc_tools_async(self, spec: dict) -> bool:
        if self.audio is None or self.busy_running():
            return False
        channel = self.channel_combo.currentIndex()
        sample_rate = self.audio.sample_rate
        calibration = self._current_calibration()
        window = self.spectrum_window
        start, end = self.region.getRegion()
        # 界面线程里先把工作线程需要的一切快照下来：工作函数里不能再碰控件（BUG-004）
        channels = int(self.audio.channels)
        fundamental = self.fundamental.value() or None
        processed = self.processed
        duration = self.work_duration
        mask = self.valid_mask
        external_reference = getattr(self, "external_reference_path", None)
        self.last_anc_spec = dict(spec or {})

        def work():
            outcome = self._anc_compute(
                spec, channel=int(channel), sample_rate=int(sample_rate),
                channels=channels, fundamental=fundamental,
                processed=processed, duration=duration,
                external_reference=external_reference)
            if not outcome.applied:
                return outcome, None
            cleaned = outcome.cleaned
            return outcome, _analyze_channel(
                cleaned, sample_rate, fundamental,
                mask[:, channel], start, end, calibration, window)

        def done(payload):
            outcome, analysis = payload
            if not outcome.applied:
                self._anc_commit(outcome)
                return
            diag = outcome.diagnostics
            self.last_anc = diag
            self._push_undo("denoise_tools", dict(getattr(self, "last_anc_spec", {}) or {}))
            self.processed[:, channel] = outcome.cleaned
            self.edit_depth += 1
            self.denoise_label.setText(self._anc_summary(outcome))
            self._apply_analysis(analysis)
            self._update_edit_label()
            self.statusBar().showMessage(tr("已应用降噪（可撤销）；原始 WAV 未修改"), 5000)

        return self.run_task(tr("正在做降噪…"), work, done,
                             hint=tr("按所选方法估计并抵消噪声"))

    def _undo_core(self) -> bool:
        if not self.undo_stack:
            self.statusBar().showMessage(tr("没有可撤销的处理"), 3000)
            return False
        self.processed, self.valid_mask, self.reference, self.edit_depth = self.undo_stack.pop()
        if self.edit_log:
            self.edit_log.pop()
        # edit_ops 与 edit_log 必须同步弹出：工程文件用的是 edit_ops，
        # 只弹 edit_log 会让「撤销过的操作」在重开工程时又跑一遍（BUG-002）。
        if self.edit_ops:
            self.edit_ops.pop()
        self.pending_denoise = None
        self.preview_curve.clear()
        self.apply_button.setEnabled(False)
        self.close_preview_button.setEnabled(False)
        self._reset_time_axis(self.work_duration)
        self._update_edit_label()
        return True

    def undo(self) -> None:
        """同步撤销；界面入口见 undo_async。"""
        if not self._undo_core():
            return
        self.refresh_all()
        self.statusBar().showMessage(tr("已撤销上次处理"), 4000)

    def undo_async(self) -> None:
        if not self._undo_core():
            return
        if not self.refresh_all_async():
            self.refresh_all()
        self.statusBar().showMessage(tr("已撤销上次处理"), 4000)

    # ---------------------------------------------------------------- 包络
    def _envelope_args(self) -> tuple:
        return (
            self.current_samples(), self.current_valid_mask(), self.audio.sample_rate,
            *self.region.getRegion(), self.envelope_model.currentText(),
        )

    def fit_current_envelope(self) -> None:
        """同步拟合；界面入口见 fit_current_envelope_async。"""
        if not self._require_audio():
            return
        self._show_envelope(_compute_envelope_fit(*self._envelope_args()))

    def fit_current_envelope_async(self) -> None:
        if not self._require_audio() or self.busy_running():
            return
        arguments = self._envelope_args()
        start, end = arguments[3], arguments[4]
        columns = self._plot_columns()
        sample_rate = self.audio.sample_rate

        def work():
            payload = _compute_envelope_fit(*arguments)
            payload["plot"] = _downsample_series(
                payload["envelope"], sample_rate, columns,
                start_time=float(payload["times"][0]))
            return payload

        self.run_task(
            tr("正在计算包络并拟合…"), work, self._show_envelope,
            hint=tf('选区 {start:.3f}–{end:.3f} s；长选区需要数秒', start=(start), end=(end)),
        )

    def _show_envelope(self, payload: dict) -> None:
        fit = payload["fit"]
        self.envelope_values = payload["envelope"]
        # 导出图像需要绝对时间轴，界面绘图只用抽稀后的相对时间，所以这里单独留存。
        self.envelope_times = payload["times"]
        self.envelope_span = payload["span"]
        self.envelope_fit = fit
        self.fit_times = payload["fit_times"]
        if "plot" in payload:
            plot_times, plot_values = payload["plot"]
        else:
            plot_times, plot_values = _downsample_series(
                payload["envelope"], self.audio.sample_rate, self._plot_columns(),
                start_time=float(payload["times"][0]))
        self.envelope_curve.setData(plot_times, plot_values)
        self.fit_curve.setData(payload["fit_times"], fit.fitted)
        parameters = "，".join(f"{key}={value:.6g}" for key, value in fit.parameters.items())
        span_text = tf('拟合区间 {_v0:.4f}–{_v1:.4f} s', _v0=(fit.start_time), _v1=(fit.end_time))
        self.envelope_label.setText(
            f"{fit.equation}\n{parameters}\nR²={fit.r_squared:.5f}，RMSE={fit.rmse:.5g}\n{span_text}")
        self.statusBar().showMessage(
            tf('包络已按选区（{span_text}）计算，绿色为包络，酒红色为拟合曲线。', span_text=(span_text)), 6000)

    # ---------------------------------------------------------------- 播放
    def toggle_play(self) -> None:
        if self.audio is None or self.processed is None:
            return
        if self.player.is_playing:
            self.player.pause()
            self.play_button.setText(tr("▶ 播放"))
            return
        if not AudioPlayer.available():
            QMessageBox.warning(self, tr("无法播放"), tr("当前系统没有可用的音频输出设备。"))
            return
        x = self.current_samples()
        sample_rate = self.audio.sample_rate
        if self.play_target.currentText() == tr("播放全文件"):
            start, end = 0.0, self.work_duration
        else:
            start, end = self.region.getRegion()
        i0 = int(np.clip(round(start * sample_rate), 0, max(0, len(x) - 2)))
        i1 = int(np.clip(round(end * sample_rate), i0 + 2, len(x)))
        self._play_span = (i0 / sample_rate, i1 / sample_rate)
        try:
            self.player.play(x[i0:i1], sample_rate, self._play_span[0])
        except Exception as exc:
            QMessageBox.warning(self, tr("播放失败"), str(exc))
            return
        self.play_button.setText(tr("⏸ 暂停"))
        self.play_line.setVisible(True)
        self.play_line.setValue(self._play_span[0])
        self.statusBar().showMessage(
            tf('正在播放 {_v0:.3f}–{_v1:.3f} s（仅监听，不改动数据）', _v0=(self._play_span[0]), _v1=(self._play_span[1])), 4000)

    def stop_play(self) -> None:
        self.player.stop()
        self.play_button.setText(tr("▶ 播放"))
        self.play_line.setVisible(False)

    def _on_play_position(self, seconds: float) -> None:
        lower, upper = self._play_span
        self.play_line.setValue(float(np.clip(seconds, lower, upper)))

    def _on_play_state(self, state: str) -> None:
        if state in {"stopped", "paused"}:
            self.play_button.setText(tr("▶ 播放"))
        if state == "stopped":
            self.play_line.setVisible(False)

    # ---------------------------------------------------------------- 裁剪与写回
    def _trim_core(self, start: float, end: float) -> str | None:
        """执行裁剪并更新状态，返回状态栏文案；失败或无需裁剪时返回 None。"""
        if not self._require_audio() or self.busy_running():
            return None
        if end - start >= self.work_duration - 1e-9:
            QMessageBox.information(self, tr("无需裁剪"), tr("当前选区已覆盖整个文件，请先框选需要保留的区间。"))
            return None
        try:
            result = trim_range(
                self.processed, self.valid_mask, self.audio.sample_rate, start, end)
        except Exception as exc:
            QMessageBox.warning(self, tr("裁剪失败"), str(exc))
            return None
        self._push_undo("trim", {"start": float(start), "end": float(end)})
        self.processed = result.samples
        self.valid_mask = result.valid_mask
        self.reference = self.reference[result.start_sample:result.end_sample].copy()
        self.edit_depth += 1
        self.pending_denoise = None
        self.preview_curve.clear()
        self.apply_button.setEnabled(False)
        self.close_preview_button.setEnabled(False)
        self._reset_time_axis(self.work_duration)
        self._update_edit_label()
        return (
            tf('已裁剪到 {_v0:.3f}–{_v1:.3f} s，保留 {_v2:,} 点；可用“撤销上次处理”还原。', _v0=(result.start_seconds), _v1=(result.end_seconds), _v2=(result.kept_samples))
        )

    def trim_to_selection(self) -> None:
        """同步裁剪；界面入口见 trim_to_selection_async。"""
        message = self._trim_core(*self.region.getRegion())
        if message is None:
            return
        self.refresh_all()
        self.statusBar().showMessage(message, 8000)

    def trim_to_selection_async(self) -> None:
        message = self._trim_core(*self.region.getRegion())
        if message is None:
            return
        if not self.refresh_all_async():
            self.refresh_all()
        self.statusBar().showMessage(message, 8000)

    def apply_changes_to_source(self) -> None:
        if not self._require_audio() or self.busy_running():
            return
        source = self.audio.source_path
        if source is None:
            QMessageBox.information(self, tr("无源文件"), tr("当前数据不是从文件载入，无法写回。"))
            return
        if self.edit_depth == 0:
            QMessageBox.information(self, tr("没有改动"), tr("当前处理版本与原始数据一致，无需写回。"))
            return
        answer = QMessageBox.question(
            self, tr("确认写回源文件"),
            tf('将把当前处理版本写回：\n{source}\n\n写入长度 {_v1:.3f} s（原文件 {_v2:.3f} s）。\n写回前会自动在同目录生成 .bak-时间戳 备份文件，原始内容不会立即丢失。\n\n是否继续？', source=(source), _v1=(self.work_duration), _v2=(self.audio.duration)),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        payload = self.processed
        sample_rate = self.audio.sample_rate
        subtype = self.audio.subtype

        def work():
            backup = apply_to_source(source, payload, sample_rate, subtype)
            return backup

        def done(backup: Path):
            # 写回后源文件内容即处理版本，共享引用避免再复制一份全量数据。
            self.reference = self.processed.copy()
            self.audio.samples = self.processed
            self.undo_stack.clear()
            # 源文件已经是处理后的新基线，配方必须一起清空——
            # 否则重开工程会把已经写进源文件的裁剪/去噪再执行一次（BUG-003）。
            self.edit_log.clear()
            self.edit_ops.clear()
            self.edit_depth = 0
            self._update_edit_label()
            QMessageBox.information(
                self, tr("已写回源文件"),
                tf('已写入：\n{source}\n\n备份文件：\n{backup}', source=(source), backup=(backup)))

        self.run_task(tr("正在写回源文件…"), work, done, hint=tr("先备份再覆盖，写入可能需要数秒"))

    # ---------------------------------------------------------------- 工程文件
    def _project_payload(self) -> dict:
        """把当前状态收成「源文件 + 操作配方」，不含处理后的采样数据。"""
        audio = self.audio
        assert audio is not None
        selection = self.selection_seconds()
        reference = None
        reference_path = getattr(self, "external_reference_path", None)
        if reference_path:
            from core.reference import REFERENCE_CACHE, file_identity, file_sha256

            size, mtime_ns = file_identity(reference_path)
            # 身份没变就直接复用已校验过的哈希；否则才读文件（典型参考只有几 MB）
            cached = REFERENCE_CACHE.get(
                reference_path,
                channel=int(getattr(self, "external_reference_channel", 0)),
                sample_rate=int(audio.sample_rate))
            digest = cached.sha256 if cached is not None else ""
            if not digest:
                try:
                    digest = file_sha256(reference_path)
                except OSError:
                    digest = ""
            reference = {
                "kind": "external",
                "path": str(reference_path),
                "channel": int(getattr(self, "external_reference_channel", 0)),
                "sha256": digest,
                "size": size,
                "mtime_ns": mtime_ns,
            }
        return build_project(
            audio.source_path,
            sample_rate=audio.sample_rate,
            channels=audio.channels,
            frames=int(audio.samples.shape[0]),
            channel=int(self.channel_combo.currentIndex()),
            edits=[dict(op) for op in self.edit_ops],
            selection=(selection[0], selection[1]) if selection else None,
            calibration={
                "active": self.calibration_active,
                "payload": dumps_profiles(self.calibration_profiles, self.calibration_active),
            },
            analysis={
                "fundamental_hz": float(self.fundamental.value()) or None,
                "envelope_model": self.envelope_model.currentText(),
                "window": self.spectrum_window,
                # 谱峰数量是展示参数：存进工程只为复现同一张谱峰表，不影响 FFT/主频/THD
                "peak_count": int(self._current_peak_count()),
            },
            export={"report_language": get_report_language()},
            reference=reference,
        )

    def save_project_file(self) -> None:
        if not self._require_audio():
            return
        stem = self.audio.source_path.with_suffix(".wavproj")
        path, _ = QFileDialog.getSaveFileName(
            self, tr("保存工程"), str(stem), tr("工程文件 (*.wavproj)"),
            options=QFileDialog.Option.DontUseNativeDialog)
        if not path:
            return
        try:
            target = save_project(path, self._project_payload())
        except OSError as exc:
            QMessageBox.warning(self, tr("保存工程失败"), str(exc))
            return
        self.statusBar().showMessage(tf('工程已保存到 {_v0}', _v0=(str(target),)), 8000)

    def open_project_file(self) -> None:
        if self.busy_running():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, tr("打开工程"), "", tr("工程文件 (*.wavproj)"),
            options=QFileDialog.Option.DontUseNativeDialog)
        if not path:
            return
        try:
            project = load_project(path)
        except ValueError as exc:
            QMessageBox.warning(self, tr("打开工程失败"), str(exc))
            return
        source = source_path_of(project, Path(path).parent)
        if source is None:
            QMessageBox.warning(
                self, tr("找不到源文件"),
                tr("工程里记录的音频文件不在了：请把它放回原位置，或先打开音频再载入工程。"))
            return
        problem = verify_source(project, source)
        if problem is not None:
            answer = QMessageBox.question(
                self, tr("源文件对不上"),
                problem + "\n\n" + tr("仍然载入这份工程？操作过程会在当前文件上重放。"))
            if answer != QMessageBox.Yes:
                return
        self.load_audio(source)
        if self.audio is None:
            return
        self._apply_project(project)

    def _apply_project(self, project: dict) -> None:
        self._restore_project_reference(project.get("reference") or {})
        channel = int(project.get("channel") or 0)
        if 0 <= channel < self.channel_combo.count():
            self.channel_combo.blockSignals(True)
            self.channel_combo.setCurrentIndex(channel)
            self.channel_combo.blockSignals(False)

        calibration = project.get("calibration") or {}
        payload = str(calibration.get("payload") or "")
        if payload:
            try:
                profiles, active = loads_profiles(payload)
            except Exception:
                profiles, active = [], ""
            if profiles:
                self.calibration_profiles = profiles
                self.calibration_active = str(calibration.get("active") or active)
                self._refresh_calibration_ui()

        analysis = project.get("analysis") or {}
        fundamental = analysis.get("fundamental_hz")
        if fundamental:
            self.fundamental.setValue(float(fundamental))
        model = analysis.get("envelope_model")
        index = self.envelope_model.findText(str(model)) if model else -1
        if index >= 0:
            self.envelope_model.setCurrentIndex(index)
        window = analysis.get("window")
        if window in SPECTRUM_WINDOWS:
            self.window_combo.blockSignals(True)
            self.window_combo.setCurrentIndex(SPECTRUM_WINDOWS.index(window))
            self.window_combo.blockSignals(False)

        language = (project.get("export") or {}).get("report_language")
        if language in REPORT_LANGUAGE_CODES:
            set_report_language(str(language))
            self.report_language_combo.blockSignals(True)
            self.report_language_combo.setCurrentIndex(
                REPORT_LANGUAGE_CODES.index(str(language)))
            self.report_language_combo.blockSignals(False)

        # 谱峰数量：旧工程没有这个字段时沿用默认 8；越界钳到 1–100。
        # 只影响展示（谱峰表/图注），不重算 FFT。
        peaks = analysis.get("peak_count")
        try:
            peaks = int(peaks)
        except (TypeError, ValueError):
            peaks = 8
        peaks = max(1, min(100, peaks))
        self.peak_count_spin.blockSignals(True)
        self.peak_count_spin.setValue(peaks)
        self.peak_count_spin.blockSignals(False)

        self.edit_depth = 0
        self.edit_log.clear()
        self.edit_ops.clear()
        self.undo_stack.clear()
        problems = self._replay_edits(project.get("edits") or [], channel)
        self.edit_depth = len(self.edit_log)

        # 先重置时间轴（它内部会把选区强制设为全文件），再恢复工程里的选区，
        # 否则刚设好的选区立刻被覆盖成全量（BUG-006）。
        self._reset_time_axis(self.work_duration)

        selection = project.get("selection")
        if isinstance(selection, list) and len(selection) == 2:
            try:
                start, end = float(selection[0]), float(selection[1])
            except (TypeError, ValueError):
                start = end = 0.0
            duration = self.work_duration
            if 0.0 <= start < end <= duration + 1e-9:
                self.region.setRegion((start, end))

        self.refresh_all()
        self._update_edit_label()
        if problems:
            QMessageBox.warning(
                self, tr("部分操作没能重放"),
                "\n".join(problems[:8]))
        else:
            self.statusBar().showMessage(
                tf('工程已载入：重放 {_v0} 步操作', _v0=(len(self.edit_log),)), 8000)

    def _replay_edits(self, edits: list[dict], default_channel: int) -> list[str]:
        """按配方重放编辑；返回没能执行的步骤说明，成功的写入编辑记录。"""
        problems: list[str] = []
        sample_rate = self.audio.sample_rate if self.audio is not None else 0
        channels = int(self.processed.shape[1]) if self.processed is not None else 1
        for op in edits:
            kind = str(op.get("kind") or "")
            params = dict(op.get("params") or {})
            try:
                if kind == "denoise":
                    column = min(max(int(params.get("channel", default_channel)), 0), channels - 1)
                    result = detect_and_repair_impulses(
                        self.processed[:, column], sample_rate,
                        float(params.get("threshold", 8.0)),
                        max_repair_ms=float(params.get("max_repair_ms", 3.0)))
                    self.processed[:, column] = result.cleaned
                    self.valid_mask[:, column] = result.valid_mask
                    self.last_denoise = result
                elif kind == "trim":
                    result = trim_range(
                        self.processed, self.valid_mask, sample_rate,
                        float(params.get("start", 0.0)),
                        float(params.get("end", self.work_duration)))
                    self.processed = result.samples
                    self.valid_mask = result.valid_mask
                    self.reference = self.reference[result.start_sample:result.end_sample].copy()
                elif kind == "denoise_tools":
                    column = min(max(int(params.get("channel", default_channel)), 0), channels - 1)
                    other = 0 if column != 0 else min(1, channels - 1)
                    target = self.processed[:, column].copy()
                    reference = self.processed[:, other].copy() if channels > 1 else None
                    segment = params.get("segment")
                    span = None
                    if isinstance(segment, (list, tuple)) and len(segment) == 2:
                        span = (
                            int(round(float(segment[0]) * sample_rate)),
                            int(round(float(segment[1]) * sample_rate)),
                        )
                    outcome = run_anc_method(
                        str(params.get("method") or "ls_frozen"),
                        target, reference, sample_rate,
                        fundamental=float(self.fundamental.value()) or None,
                        segment=span,
                        params=dict(params.get("options") or {}))
                    if outcome.cleaned is not None:
                        self.processed[:, column] = outcome.cleaned
                    self.last_anc = outcome.diagnostics
                else:
                    problems.append(tf('不认识的操作：{_v0}', _v0=(kind,)))
                    continue
            except Exception as exc:  # 单个步骤失败不能把整个工程卡死
                problems.append(f"{kind}: {exc}")
                continue
            self.edit_log.append(kind)
            self.edit_ops.append({"kind": kind, "params": params})
        return problems

    def _update_edit_label(self) -> None:
        if self.edit_depth == 0:
            self.edit_label.setText(tr("未做编辑"))
            return
        self.edit_label.setText(
            tf('已应用 {_v0} 次编辑（去噪/裁剪），当前长度 {_v1:.3f} s；可写回源文件或撤销（可撤销 {_v2} 级）。', _v0=(self.edit_depth), _v1=(self.work_duration), _v2=(len(self.undo_stack))))

    def run_dual_channel(self) -> None:
        if not self._require_audio():
            return
        try:
            current = AudioData(self.processed, self.audio.sample_rate)
            result = analyze_dual_channel(current, self.fundamental.value())
            QMessageBox.information(self, tr("双通道分析"), "\n".join(f"{key}: {value}" for key, value in result.items()))
        except Exception as exc:
            QMessageBox.warning(self, tr("双通道分析失败"), str(exc))

    def run_dual_channel_async(self) -> None:
        if not self._require_audio() or self.busy_running():
            return
        payload = self.processed
        sample_rate = self.audio.sample_rate
        fundamental = self.fundamental.value()

        def work():
            return analyze_dual_channel(AudioData(payload, sample_rate), fundamental)

        def done(result: dict):
            self.dual_result = result
            QMessageBox.information(self, tr("双通道分析"), "\n".join(f"{k}: {v}" for k, v in result.items()))

        self.run_task(tr("正在做双通道时延分析…"), work, done)

    # ---------------------------------------------------------------- 导出
    def export_processed(self) -> None:
        if not self._require_audio():
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("导出处理后 WAV"), "processed.wav", tr("WAV 音频 (*.wav)"))
        if path:
            try:
                write_wav(path, self.processed, self.audio.sample_rate)
                self.statusBar().showMessage(tf('已导出 {path}', path=(path)), 5000)
            except Exception as exc:
                QMessageBox.warning(self, tr("导出失败"), str(exc))

    def export_processed_async(self) -> None:
        if not self._require_audio() or self.busy_running():
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("导出处理后 WAV"), "processed.wav", tr("WAV 音频 (*.wav)"))
        if not path:
            return
        payload = self.processed.copy()
        sample_rate = self.audio.sample_rate

        def work():
            write_wav(path, payload, sample_rate)
            return path

        self.run_task(tr("正在导出 WAV…"), work,
                      lambda result: self.statusBar().showMessage(tf('已导出 {result}', result=(result)), 5000),
                      hint=Path(path).name)

    def export_raw_data(self) -> None:
        """把频谱 / 峰值 / 包络 / 时频矩阵按需写成 CSV 或 NPZ。"""
        if not self._require_audio():
            return
        available = {
            "spectrum": self.fourier is not None,
            "peaks": self.fourier is not None,
            "envelope": self.envelope_values is not None and self.envelope_times is not None,
            "spectrogram": self.spectrogram is not None,
        }
        if not any(available.values()):
            QMessageBox.information(self, tr("没有可导出的数据"),
                                    tr("请先完成频谱分析或包络拟合，再导出原始数据。"))
            return
        source = self.audio.source_path
        stem = Path(source).stem if source else "data"
        default_dir = str(Path(source).parent) if source else str(Path.cwd())
        dialog = DataExportDialog(self, stem=stem, available=available, default_dir=default_dir)
        if dialog.exec() != QDialog.Accepted:
            return
        folder = Path(dialog.output_dir())
        sample_rate = self.audio.sample_rate
        written: list[str] = []
        try:
            for kind in dialog.checked_kinds():
                if kind == "spectrum" and self.fourier is not None:
                    target = folder / f"{dialog.file_name(kind)}.csv"
                    export_spectrum_csv(target, self.fourier)
                    written.append(target.name)
                elif kind == "peaks" and self.fourier is not None:
                    target = folder / f"{dialog.file_name(kind)}.csv"
                    export_peaks_csv(target, self.fourier, peak_count=self._current_peak_count())
                    written.append(target.name)
                elif kind == "envelope" and self.envelope_values is not None:
                    target = folder / f"{dialog.file_name(kind)}.csv"
                    fitted = (evaluate_fit(self.envelope_fit, self.envelope_times)
                              if self.envelope_fit is not None else None)
                    export_envelope_csv(target, self.envelope_times, self.envelope_values, fitted)
                    written.append(target.name)
                elif kind == "spectrogram" and self.spectrogram is not None:
                    times, frequencies, magnitude = self.spectrogram
                    nperseg = 1024
                    noverlap = nperseg // 2
                    total = int(self.processed.shape[0])
                    target = folder / f"{dialog.file_name(kind)}.npz"
                    export_spectrogram_npz(
                        target, times, frequencies, magnitude,
                        nperseg=nperseg, noverlap=noverlap, sample_rate=sample_rate,
                        max_frames=MAX_SPECTROGRAM_FRAMES,
                        skipped=skipped_frames(total, nperseg, noverlap, len(times)),
                        window=self.spectrum_window,
                    )
                    written.append(target.name)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("导出失败"), str(exc))
            return
        if written:
            self.statusBar().showMessage(
                tf('已导出 {_v0} 个文件到 {folder}', _v0=(len(written)), folder=(str(folder))), 8000)

    def export_statistics(self) -> None:
        if not self._require_audio():
            return
        if self.statistics is None:
            self.calculate_statistics()
        if self.statistics is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("导出统计"), "statistics.csv", "CSV (*.csv)")
        if path:
            rows = [
                {key: value for key, value in self.statistics.items()
                 if not key.startswith("_")},
            ]
            rows[0]["analysis_window"] = self.spectrum_window
            export_rows_csv(path, rows)
            self.statusBar().showMessage(tf('已导出 {path}', path=(path)), 5000)

    def export_report(self) -> None:
        if not self._require_audio():
            return
        if self.statistics is None:
            self.calculate_statistics()
        if self.statistics is None or self.fourier is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("生成独立报告"), "wav_analysis_report.html", tr("HTML 报告 (*.html)"))
        if path:
            try:
                content = build_report_html(
                    str(self.audio.source_path), self.audio.sample_rate, self.channel_combo.currentIndex(),
                    self.statistics, self.fourier, self.current_samples(), self.envelope_values,
                    self.envelope_fit, self.last_denoise, self.last_ai_narrative,
                )
                save_report(path, content)
                self.statusBar().showMessage(tf('已生成 {path}', path=(path)), 5000)
            except Exception as exc:
                QMessageBox.warning(self, tr("报告生成失败"), str(exc))

    def export_report_async(self) -> None:
        if not self._require_audio() or self.busy_running():
            return
        if self.statistics is None:
            self.calculate_statistics()
        if self.statistics is None or self.fourier is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("生成独立报告"), "wav_analysis_report.html", tr("HTML 报告 (*.html)"))
        if not path:
            return
        arguments = (
            str(self.audio.source_path), self.audio.sample_rate, self.channel_combo.currentIndex(),
            self.statistics, self.fourier, self.current_samples().copy(), self.envelope_values,
            self.envelope_fit, self.last_denoise, self.last_ai_narrative,
        )

        def work():
            content = build_report_html(*arguments)
            save_report(path, content)
            return path

        self.run_task(tr("正在生成 HTML 报告…"), work,
                      lambda result: self.statusBar().showMessage(tf('已生成 {result}', result=(result)), 5000),
                      hint=tr("包含波形、频谱与统计图表"))

    # ---------------------------------------------------------------- 导出 TXT
    def export_analysis_txt(self) -> None:
        """把分析结果导出成 TXT：先选章节与数据版本，再在工作线程里写盘。"""
        if not self._require_audio() or self.busy_running():
            return
        sample_rate = int(self.audio.sample_rate)
        channel = self.channel_combo.currentIndex()
        region = tuple(self.region.getRegion()) if self.region is not None else None
        edited = self.edit_depth > 0
        available = {
            "envelope": self.envelope_fit is not None and self.envelope_values is not None,
            "fourier": self.fourier is not None,
            "stats": True,
            "dual": self.audio.channels == 2,
            "ai": bool(self.last_ai_narrative.strip()),
            "denoise": self.last_denoise is not None,
            "coords": True,
        }
        dialog = TxtExportDialog(
            self,
            duration=self.work_duration,
            sample_rate=sample_rate,
            total_samples=int(self.current_samples().size),
            source_path=self.audio.source_path,
            edited=edited,
            region=region,
            available=available,
            channel_index=channel,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        options = dialog.options()
        options.ai_text = self.last_ai_narrative or ""
        use_edited = dialog.edited()
        path = dialog.output_path()
        fundamental = float(self.fundamental.value()) or None

        if use_edited:
            samples = np.array(self.current_samples(), dtype=np.float64)
            mask = np.array(self.current_valid_mask(), dtype=bool)
            denoise = self.last_denoise
            envelope = self.envelope_values
            envelope_times = self.envelope_times
            span = self.envelope_span
            fit = self.envelope_fit
        else:
            reference = self.current_reference()
            samples = np.array(reference if reference is not None else self.current_samples(),
                               dtype=np.float64)
            mask = np.ones(samples.shape, dtype=bool)
            denoise = None
            # 包络是在“当前处理数据”上算的，选源文件版本时不能混用。
            if edited:
                envelope = envelope_times = span = fit = None
            else:
                envelope = self.envelope_values
                envelope_times = self.envelope_times
                span = self.envelope_span
                fit = self.envelope_fit

        source = self.audio.source_path
        payload = {
            "source_name": source.name if source else tr("未命名.wav"),
            "source_path": str(source) if source else "",
            "subtype": self.audio.subtype,
            "size_mb": (source.stat().st_size / 1024 / 1024) if source and source.exists() else 0.0,
            "data_label": tr("修改后文件（已编辑）") if use_edited else tr("源文件（未修改）"),
            "channels": self.audio.channels,
            "edit_depth": self.edit_depth if use_edited else 0,
            "denoise_edits": self.edit_log.count("denoise") if use_edited else 0,
            "trim_edits": self.edit_log.count("trim") if use_edited else 0,
            "dual": self.dual_result,
        }
        # 校准在主线程取好再进线程：工作线程读界面控件是非法的
        calibration = self._current_calibration()

        def work(progress=None):
            fourier = fourier_analysis(samples, sample_rate, fundamental_frequency=fundamental)
            return write_analysis_txt(
                path, samples=samples, sample_rate=sample_rate,
                source_name=payload["source_name"], source_path=payload["source_path"],
                subtype=payload["subtype"], size_mb=payload["size_mb"],
                md5=file_md5(source) if source else "",
                data_label=payload["data_label"], channels=payload["channels"],
                edit_depth=payload["edit_depth"], denoise_edits=payload["denoise_edits"],
                trim_edits=payload["trim_edits"], fourier=fourier,
                envelope=envelope, envelope_times=envelope_times, envelope_span=span,
                fit=fit, denoise=denoise, dual=payload["dual"], options=options,
                fundamental=fundamental, valid_mask=mask, progress=progress,
                calibration=calibration,
            )

        def done(result: dict):
            megabytes = result["bytes"] / 1024 / 1024
            self.statusBar().showMessage(
                tf('已导出 {_v0}（{_v1:,} 行，{megabytes:.1f} MB，{_v3} 个章节）', _v0=(result['path']), _v1=(result['rows']), megabytes=(megabytes), _v3=(len(result['sections']))), 10000)

        self.run_task(tr("正在导出分析 TXT…"), work, done,
                      hint=tf('{_v0} 个章节，坐标步长 {_v1} 点', _v0=(len(options.sections)), _v1=(options.coord_stride(sample_rate))),
                      progress=True)

    # ---------------------------------------------------------------- 导出图像
    def _export_kind_for_tab(self) -> str:
        index = self.tabs.currentIndex()
        if index == 1:
            return KIND_SPECTRUM
        if index == 2:
            return KIND_SPECTROGRAM
        return KIND_WAVE

    def export_image(self) -> None:
        """导出 PNG：先弹选项对话框，再在工作线程里重新渲染（不是界面截图）。"""
        if not self._require_audio() or self.busy_running():
            return
        if self.fourier is None:
            self.statusBar().showMessage(tr("分析结果尚未就绪，请稍候再导出"), 4000)
            return
        default_kind = self._export_kind_for_tab()
        channel = self.channel_combo.currentIndex()
        dialog = ImageExportDialog(
            self,
            default_kind=default_kind,
            default_path=suggest_path(self.audio.source_path, default_kind, channel),
            available={
                # 未编辑时 reference 与 processed 完全重合，画两条只是重影。
                "original": self.reference is not None and self.edit_depth > 0,
                "preview": self.pending_denoise is not None,
                "envelope": self.envelope_values is not None,
                "fit": self.envelope_fit is not None,
                "region": True,
                "cursor": True,
            },
        )
        if dialog.exec() != QDialog.Accepted:
            return

        path = dialog.output_path()
        options = dialog.options()
        if not options.title:
            options.title = Path(path).stem
        kind = dialog.selected_kind()
        selected = dialog.wave_selection()
        sample_rate = self.audio.sample_rate

        if kind == KIND_WAVE:
            payload = dict(
                samples=self.current_samples(),
                sample_rate=sample_rate,
                options=options,
                original=self.current_reference() if selected["original"] else None,
                preview=self.pending_denoise.cleaned
                if selected["preview"] and self.pending_denoise is not None else None,
                envelope=self.envelope_values if selected["envelope"] else None,
                envelope_times=self.envelope_times if selected["envelope"] else None,
                fit_times=self.fit_times if selected["fit"] else None,
                fit_values=self.envelope_fit.fitted
                if selected["fit"] and self.envelope_fit is not None else None,
                region=tuple(self.region.getRegion()) if selected["region"] else None,
                cursor=float(self.cursor.value()) if selected["cursor"] else None,
            )

            def work():
                return render_waveform_png(path, **payload)

            title = tr("正在导出波形图…")
            hint = tf('当前声道 {_v0:,} 点，长音频会先抽稀再绘制', _v0=(len(payload['samples'])))
        elif kind == KIND_SPECTRUM:
            fourier = self.fourier

            def work():
                return render_spectrum_png(path, fourier, options)

            title = tr("正在导出频谱图…")
            hint = tr("振幅谱") + (tr("＋相位谱") if options.show_phase else "")
        else:
            if self.spectrogram is None:
                self.update_spectrogram()
            spectrogram = self.spectrogram

            def work():
                return render_spectrogram_png(path, spectrogram, options)

            title = tr("正在导出时频图…")
            hint = tr("重算 dB 色标范围")

        def done(result: dict):
            if result.get("width") is None:
                # 矢量图没有像素尺寸，报物理尺寸，别在状态栏写 None×None。
                inches = result.get("inches") or (0.0, 0.0)
                size = f"{Path(result['path']).suffix.upper().lstrip('.')} {inches[0]}×{inches[1]} in"
            else:
                size = f"{result['width']}×{result['height']}"
            self.statusBar().showMessage(
                tf('已导出 {_v0}（{size}，{_v2}）', _v0=(result['path']), size=(size), _v2=(KIND_LABELS[result['kind']])), 9000)

        self.run_task(title, work, done, hint=hint)

    # ---------------------------------------------------------------- 批量处理
    def open_batch_dialog(self) -> None:
        """搭脚本 → 选文件 → 交给工作线程执行；界面全程可响应。"""
        if self.batch_worker is not None:
            self.statusBar().showMessage(tr("批量任务正在进行，请等待结束或点遮罩上的“取消”"), 5000)
            return
        if self.busy_running():
            self.statusBar().showMessage(tr("当前已有任务在后台运行，请稍后再试"), 5000)
            return
        default_dir = ""
        if self.audio is not None and self.audio.source_path is not None:
            default_dir = str(self.audio.source_path.parent)
        dialog = BatchDialog(self, default_dir=default_dir, selection=self.selection_seconds)
        if dialog.exec() != QDialog.Accepted:
            return
        steps, files, output_dir, reference = dialog.job()
        self.start_batch(steps, files, output_dir, reference=reference)

    def start_batch(self, steps: list[dict], files: list[str], output_dir: str = "",
                    reference: dict | None = None) -> bool:
        """启动批量流水线。返回是否真的启动（供测试直接调用，不弹对话框）。"""
        if self.batch_worker is not None or not steps or not files:
            return False
        worker = BatchWorker(files, steps, output_dir, self,
                             calibration=self._current_calibration(),
                             reference=reference)
        self.batch_worker = worker
        self.batch_overlay.cancelled.connect(worker.cancel)
        worker.staged.connect(self.batch_overlay.set_stage)
        worker.succeeded.connect(self._batch_succeeded)
        worker.failed.connect(self._batch_failed)
        # finished 晚于 succeeded：线程真正结束后才释放引用，否则 QThread 运行中被回收会闪退。
        worker.finished.connect(lambda w=worker: self._batch_finished(w))
        self.batch_button.setEnabled(False)
        self.batch_overlay.start(len(files))
        self.statusBar().showMessage(
            tf('批量处理已开始：{_v0} 个文件，{_v1} 个步骤', _v0=(len(files)), _v1=(len(steps))))
        worker.start()
        return True

    def _batch_succeeded(self, result) -> None:
        self.batch_overlay.finish()
        self.batch_button.setEnabled(True)
        self.last_batch_result = result
        lines = result.summary().splitlines()
        self.statusBar().showMessage(lines[0] if lines else tr("批量处理结束"), 15000)
        box = QMessageBox(self)
        box.setWindowTitle(tr("批量处理已取消") if result.cancelled else tr("批量处理完成"))
        box.setIcon(QMessageBox.Information if result.fail_count == 0 else QMessageBox.Warning)
        box.setText(lines[0] if lines else tr("批量处理结束"))
        if len(lines) > 1:
            box.setInformativeText("\n".join(lines[1:]))
        summary_button = None
        if result.files:
            summary_button = box.addButton(tr("查看汇总"), QMessageBox.ActionRole)
        box.exec()
        if summary_button is not None and box.clickedButton() is summary_button:
            self.show_batch_summary()

    def show_batch_summary(self) -> None:
        """批量完成后查看/导出横向对比表与对比图。"""
        if self.last_batch_result is None:
            self.statusBar().showMessage(tr("还没有批量结果"), 5000)
            return
        summary = build_summary(self.last_batch_result)
        BatchSummaryDialog(self, summary).exec()

    def _batch_failed(self, message: str) -> None:
        self.batch_overlay.finish()
        self.batch_button.setEnabled(True)
        QMessageBox.warning(self, tr("批量处理失败"), message)

    def _batch_finished(self, worker) -> None:
        if self.batch_worker is worker:
            self.batch_worker = None
        worker.deleteLater()

    # ---------------------------------------------------------------- AI
    def configure_ai(self) -> None:
        dialog = AISettingsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.ai_assistant = None

    def send_ai_message(self, preset: str | None = None) -> None:
        if not self._require_audio() or self.ai_worker is not None:
            return
        message = preset if isinstance(preset, str) else self.chat_input.text().strip()
        if not message:
            return
        try:
            if self.ai_assistant is None:
                settings = load_ai_settings()
                if not settings.api_key.strip() or not settings.model.strip():
                    answer = QMessageBox.question(
                        self, tr("AI 尚未配置"),
                        tr("还没有填写 API Key 或模型名称。\n\n"
                        "在“模型设置”里选择一个厂商预设（如 DeepSeek、Moonshot），"
                        "只需填 API Key 即可使用。\n\n现在打开模型设置吗？"),
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
                    )
                    self.send_button.setEnabled(True)
                    if answer == QMessageBox.Yes:
                        self.configure_ai()
                    return
                self.ai_assistant = AIAssistant(OpenAICompatibleClient(settings))
            tools = AnalysisTools(self.current_samples(), self.audio.sample_rate,
                                  self.audio.source_path.name, self.current_valid_mask())
            self.chat_view.add_user(message)
            self.chat_input.clear()
            self.send_button.setEnabled(False)
            self.busy.start(tr("AI 正在分析…"), tr("模型返回后会自动显示结果"))
            self.ai_worker = AIWorker(self.ai_assistant, message, tools, self)
            self.ai_worker.succeeded.connect(self._ai_succeeded)
            self.ai_worker.failed.connect(self._ai_failed)
            # 线程结束后由事件循环释放：否则每问一次就多留一个 worker 和一份
            # 完整音频快照，长音频连问几次内存会线性增长（BUG-005）。
            self.ai_worker.finished.connect(self.ai_worker.deleteLater)
            self.ai_worker.start()
        except Exception as exc:
            self.send_button.setEnabled(True)
            self.ai_worker = None
            self.busy.stop()
            QMessageBox.warning(self, tr("AI 设置或请求失败"), str(exc))

    def _ai_succeeded(self, outcome: AIOutcome) -> None:
        self.busy.stop()
        self.chat_view.add_ai(outcome.content)
        self.last_ai_narrative = outcome.content
        self.send_button.setEnabled(True)
        self.ai_worker = None
        self._confirm_ai_denoise(outcome.pending_actions)

    def _confirm_ai_denoise(self, actions: list[dict[str, Any]]) -> None:
        """只问一次、且 0 区段时不问。

        模型在一轮里可能调用多次 request_denoise，以前每个动作各弹一个
        模态框：点“否”关掉一个，下一个又冒出来，看起来像关不掉；
        区段为 0 时弹框也毫无意义（点了应用也什么都不变）。
        """
        candidates = [item for item in actions
                      if item.get("type") == "denoise" and isinstance(item.get("result"), DenoiseResult)]
        if not candidates:
            return
        result: DenoiseResult = candidates[-1]["result"]
        if not result.events:
            self.chat_view.add_notice(
                tr("AI 请求的去噪预览没有检测到需要修复的区段（0 段），"
                "已自动跳过确认，数据未改动。"))
            return
        box = QMessageBox(self)
        box.setWindowTitle(tr("确认 AI 去噪预览"))
        box.setIcon(QMessageBox.Question)
        box.setText(tf('AI 请求应用去噪预览：{_v0} 段，修复 {_v1} 个采样，排除 {_v2} 个。', _v0=(len(result.events)), _v1=(result.repaired_count), _v2=(result.excluded_count)))
        box.setInformativeText(tr("应用后只改处理版本，原始 WAV 不变，且可以撤销。"))
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.button(QMessageBox.Yes).setText(tr("应用"))
        box.button(QMessageBox.No).setText(tr("不应用"))
        box.setDefaultButton(QMessageBox.No)
        box.setEscapeButton(QMessageBox.No)
        if box.exec() != QMessageBox.Yes:
            return
        self.pending_denoise = result
        self._show_denoise_preview(result)
        if not self.apply_denoise_async():
            self.apply_denoise()

    def _ai_failed(self, message: str) -> None:
        self.busy.stop()
        self.chat_view.add_error(message)
        self.send_button.setEnabled(True)
        self.ai_worker = None

    def closeEvent(self, event) -> None:
        # 关窗时丢掉还没启动的排队请求，避免退出过程中又拉起一个 worker
        self._pending_task = None
        if self.ai_worker is not None:
            QMessageBox.information(self, tr("AI 请求进行中"), tr("请等待当前 AI 请求结束后再关闭程序。"))
            event.ignore()
            return
        if self.batch_worker is not None:
            # 批量线程还在跑：先请求取消，再等它自然结束；中途销毁 QThread 会崩。
            answer = QMessageBox.question(
                self, tr("批量处理进行中"),
                tr("批量任务尚未结束。取消并等待当前文件处理完后退出吗？"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.batch_worker.cancel()
            if not self.batch_worker.wait(60000):
                QMessageBox.information(
                    self, tr("任务仍在收尾"), tr("批量任务尚未结束，请稍等几秒后再关闭窗口。"))
                event.ignore()
                return
            event.accept()
            return
        if self.task is not None:
            answer = QMessageBox.question(
                self, tr("仍有处理在进行"),
                tr("当前有后台任务未完成，立即退出可能丢失未保存的处理结果。是否仍要退出？"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            # 必须在工作线程真正结束后再销毁窗口：QThread 运行中被回收会直接崩溃。
            self.busy.set_text(tr("正在结束后台任务…"))
            if not self.task.wait(20000):
                self.busy.stop()
                QMessageBox.information(
                    self, tr("任务仍在收尾"),
                    tr("后台任务尚未结束，请稍等几秒后再关闭窗口。"))
                event.ignore()
                return
        self.player.stop()
        event.accept()
