"""把分析结果渲染成可用于论文的 PNG。

两套版式共用同一份数据与同一套抽稀规则，只换排版参数：

* ``layout="paper"``（界面默认）——按印刷物理尺寸出图：单栏 3.5×2.45 in、
  双栏 7.0×2.6 in，600 dpi，刻度朝内且四边齐全，字号 7.5/8.5 pt，
  图例移到坐标区外（论文里图例压曲线是硬伤），默认不画图内标题（图题交给 caption）。
* ``layout="screen"``——原来的像素版式，尺寸/背景/网格照旧，用于 PPT 与网页。

字体规范：西文与数字 Times New Roman，中文按字符级回退宋体；变量在 mathtext 里斜体，
单位走正体文本。因此轴标签写成 ``$t$ / s``、``$x$ / FS`` 的形式——mathtext 里不能混排中文。

所有函数只做纯计算与落盘，不触碰任何 Qt 对象，可直接在工作线程里跑。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from .display import min_max_downsample, thin_xy

# 单条曲线的绘制点数上限。matplotlib 画百万点会明显变慢，
# min/max 抽稀保留峰谷，视觉形态不受影响。
MAX_PLOT_POINTS = 200_000
# 屏幕版式默认 DPI：1600×900 时对应 8×4.5 英寸。
DEFAULT_DPI = 200
# 论文版式：单栏 ≈ 8.9 cm，双栏 ≈ 17.8 cm，与国内期刊/A4 双栏排版对齐。
PAPER_SIZES = {"single": (3.50, 2.45), "double": (7.00, 2.60)}
PAPER_TALL_RATIO = 1.32   # 波形与包络上下双图时的高度倍数
PAPER_DPI = 600
# 制图字体规范：西文与数字用 Times New Roman，中文按字符级回退到宋体（SimSun）。
_SERIF_FONTS = ["Times New Roman", "SimSun", "STIXGeneral", "DejaVu Serif"]
_ENVELOPE_SMOOTH_MS = 5.0

# matplotlib 的 pyplot 状态是进程级的，多线程同时渲染会互相覆盖 rcParams。
_RENDER_LOCK = threading.Lock()


@dataclass
class FigureOptions:
    """导出的通用排版选项。

    screen 版式下像素尺寸 = width_px × height_px；paper 版式下尺寸由 column 决定。
    """

    width_px: int = 1600
    height_px: int = 900
    dpi: int = DEFAULT_DPI
    background: str = "white"      # white / dark / transparent
    grid: bool = False
    legend: bool = True
    title: str = ""
    spectrum_db: bool = True       # 频谱纵轴用 dBFS
    max_frequency: float = 0.0     # 0 表示画到奈奎斯特频率
    annotate_peaks: bool = True    # 标注主频/主要谱峰
    mark_harmonics: bool = False   # 标出基频整数倍位置
    show_phase: bool = False       # 频谱图附带相位子图
    db_floor: float = -100.0       # 时频图动态范围下限（dBFS）
    layout: str = "screen"         # paper / screen（界面默认走 paper，脚本默认保持原像素版式）
    column: str = "single"         # single / double（仅 paper）
    legend_outside: bool = True    # 图例放坐标区外（仅 paper）
    smooth_envelope: bool = True   # 包络绘图做 5 ms 平滑（不影响算法与统计）

    # ------------------------------------------------------------ 尺寸换算
    def is_paper(self) -> bool:
        return self.layout == "paper"

    def effective_dpi(self) -> int:
        return PAPER_DPI if self.is_paper() else max(72, int(self.dpi))

    def figsize(self, tall: bool = False) -> tuple[float, float]:
        if self.is_paper():
            width, height = PAPER_SIZES.get(self.column, PAPER_SIZES["single"])
            return (width, height * PAPER_TALL_RATIO) if tall else (width, height)
        dpi = max(72, int(self.dpi))
        return max(320, int(self.width_px)) / dpi, max(240, int(self.height_px)) / dpi


# matplotlib 必须在本模块导入时（主线程）完成首次导入：
# 若第一次导入发生在 TaskWorker 线程里，Python 3.13 + PySide6 会在 shiboken 的
# 特性探测阶段触发 access violation，现象是导出图片时整个进程闪退。
try:  # pragma: no cover - 环境相关
    import matplotlib as _mpl

    _mpl.use("Agg")
    from matplotlib import pyplot as _PLT
except Exception:  # pragma: no cover - 缺 matplotlib 时应报错而不是崩
    _PLT = None


def _load_pyplot():
    if _PLT is None:
        raise RuntimeError("未安装 matplotlib，无法导出图像")
    return _PLT


def _warm_up() -> None:
    """在主线程把 matplotlib 的惰性路径全部走一遍。

    mathtext 语法树、字体缓存、Agg 光栅化都是首次使用时才构建的。若第一次构建
    发生在 TaskWorker 线程，PySide6 的导入钩子与 CPython 的惰性导入会撞在一起，
    现象就是导出图片时进程直接闪退（access violation / Aborted）。
    这里用一张 1×1 英寸的小图把这条路径提前跑完，代价约 0.15 s。
    """
    import io

    if _PLT is None:  # pragma: no cover - 无 matplotlib
        return
    try:  # pragma: no cover - 环境相关
        with _PLT.rc_context(_paper_rc()):
            figure = _PLT.figure(figsize=(1.2, 1.0))
            axis = figure.add_subplot(111)
            axis.plot([0.0, 1.0], [0.0, 1.0])
            axis.set_xlabel(r"$t$ / s")
            axis.set_ylabel(r"$x$ / FS")
            buffer = io.BytesIO()
            figure.savefig(buffer, format="png", dpi=72)
            _PLT.close(figure)
    except Exception:  # pragma: no cover - 预热失败不应阻断导入
        pass


def _warm_up() -> None:
    """在主线程把 matplotlib 的惰性路径全部走一遍。

    mathtext 语法树、字体缓存、Agg 光栅化都是首次使用时才构建的。若第一次构建
    发生在 TaskWorker 线程，PySide6 的导入钩子与 CPython 的惰性导入会撞在一起，
    现象就是导出图片时进程直接闪退（access violation / Aborted）。
    这里用一张 1×1 英寸的小图把这条路径提前跑完，代价约 0.15 s。
    """
    import io

    if _PLT is None:  # pragma: no cover - 无 matplotlib
        return
    try:  # pragma: no cover - 环境相关
        with _PLT.rc_context(_paper_rc()):
            figure = _PLT.figure(figsize=(1.2, 1.0))
            axis = figure.add_subplot(111)
            axis.plot([0.0, 1.0], [0.0, 1.0])
            axis.set_xlabel(r"$t$ / s")
            axis.set_ylabel(r"$x$ / FS")
            buffer = io.BytesIO()
            figure.savefig(buffer, format="png", dpi=72)
            _PLT.close(figure)
    except Exception:  # pragma: no cover - 预热失败不应阻断导入
        pass


def _paper_rc() -> dict:
    return {
        "font.family": _SERIF_FONTS,
        "font.serif": _SERIF_FONTS,
        "mathtext.fontset": "custom",
        "mathtext.rm": "Times New Roman",
        "mathtext.it": "Times New Roman:italic",
        "mathtext.bf": "Times New Roman:bold",
        "axes.unicode_minus": False,
        "axes.linewidth": 0.6,
        "axes.labelsize": 8.5,
        "axes.titlesize": 8.5,
        "xtick.labelsize": 7.5,
        "ytick.labelsize": 7.5,
        "legend.fontsize": 7.0,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.top": True,
        "ytick.right": True,
        "xtick.major.size": 3.0,
        "ytick.major.size": 3.0,
        "xtick.minor.size": 1.5,
        "ytick.minor.size": 1.5,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.minor.width": 0.45,
        "ytick.minor.width": 0.45,
        "legend.frameon": False,
        "legend.handlelength": 1.6,
        "grid.linewidth": 0.4,
        "grid.linestyle": ":",
        "grid.alpha": 0.55,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    }


def _style(options: FigureOptions):
    if options.is_paper():
        return _paper_rc(), {"foreground": "#1a1a1a", "background": "#ffffff",
                             "transparent": False, "paper": True}
    dark = options.background == "dark"
    transparent = options.background == "transparent"
    scale = max(0.5, options.dpi / float(DEFAULT_DPI))
    foreground = "#e8ecf2" if dark else "#1f2328"
    grid_color = "#39424f" if dark else "#d8dde5"
    background = "#12161c" if dark else "#ffffff"
    if transparent:
        background = "none"
    rc = {
        "font.family": _SERIF_FONTS,
        "font.serif": _SERIF_FONTS,
        "mathtext.fontset": "custom",
        "mathtext.rm": "Times New Roman",
        "mathtext.it": "Times New Roman:italic",
        "mathtext.bf": "Times New Roman:bold",
        "mathtext.default": "it",
        "axes.unicode_minus": False,
        "font.size": 11.0 * scale,
        "axes.titlesize": 12.0 * scale,
        "axes.labelsize": 11.5 * scale,
        "legend.fontsize": 9.5 * scale,
        "xtick.labelsize": 9.5 * scale,
        "ytick.labelsize": 9.5 * scale,
        "text.color": foreground,
        "axes.labelcolor": foreground,
        "axes.edgecolor": foreground,
        "xtick.color": foreground,
        "ytick.color": foreground,
        "axes.facecolor": background,
        "figure.facecolor": background,
        "grid.color": grid_color,
        "legend.framealpha": 0.9,
    }
    return rc, {"foreground": foreground, "background": background,
                "transparent": transparent, "paper": False}


def _decorate(axis, options: FigureOptions, style: dict) -> None:
    """网格与次刻度。论文版式默认给次刻度，读数精度靠它而不是网格。"""
    if options.grid:
        axis.grid(True, which="major", axis="both")
    if style.get("paper"):
        from matplotlib.ticker import AutoMinorLocator
        axis.xaxis.set_minor_locator(AutoMinorLocator(2))
        axis.yaxis.set_minor_locator(AutoMinorLocator(2))


def _place_legend(fig, axes: Sequence[Any], options: FigureOptions) -> int:
    """画图例，返回占用的行数（0 表示画在坐标区内或未画）。

    波形与包络分在上下两个坐标区时，图例要把各坐标区的带标签曲线合起来，
    否则只会列出上面那一条「当前波形」。
    """
    handles: list[Any] = []
    labels: list[str] = []
    for axis in axes:
        found, texts = axis.get_legend_handles_labels()
        for handle, text in zip(found, texts):
            if text not in labels:
                handles.append(handle)
                labels.append(text)
    if not options.legend or not handles:
        return 0
    count = len(handles)
    if options.is_paper() and options.legend_outside:
        columns = count if count <= 4 else 4
        rows = 1 if count <= 4 else 2
        _width, height = fig.get_size_inches()
        fig.legend(handles, labels, loc="lower center", ncol=columns,
                   bbox_to_anchor=(0.5, 0.02 / height), frameon=False,
                   columnspacing=1.8, handletextpad=0.5, borderaxespad=0.0)
        return rows
    axes[0].legend(loc="upper right", ncols=1 if count <= 3 else 2)
    return 0


def _paper_margins(fig, options: FigureOptions, legend_rows: int) -> None:
    """按英寸手工留白。tight_layout 不认识 fig.legend，会算错并把图例压到坐标轴上。"""
    width, height = fig.get_size_inches()
    left = 0.60 if options.column == "double" else 0.52
    right = 0.10
    top = 0.08 + (0.24 if options.title.strip() else 0.0)
    bottom = 0.34 + 0.19 * legend_rows
    fig.subplots_adjust(left=left / width, right=1 - right / width,
                        top=1 - top / height, bottom=bottom / height)


def _finish(plt, fig, axes: Sequence[Any], options: FigureOptions, style: dict, path: Path) -> dict:
    for axis in axes:
        _decorate(axis, options, style)
    rows = _place_legend(fig, axes, options)
    if options.title.strip():
        size = 9.0 if style.get("paper") else 13.0 * max(0.5, options.dpi / float(DEFAULT_DPI))
        fig.suptitle(options.title.strip(), fontsize=size, y=0.985 if style.get("paper") else 0.98)
    # 论文版式的多坐标区一律手工留白：带 gridspec 高度比时 tight_layout 会报
    # "Axes not compatible" 并可能算错留白，把图例或标签压到坐标区上。
    if style.get("paper") and (rows or len(axes) > 1):
        _paper_margins(fig, options, rows)
    else:
        fig.tight_layout(pad=0.2 if style.get("paper") else 1.08)

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    dpi = options.effective_dpi()
    fig.savefig(target, dpi=dpi, transparent=style["transparent"])
    size = fig.get_size_inches()
    width, height = int(round(size[0] * dpi)), int(round(size[1] * dpi))
    plt.close(fig)
    return {"path": str(target), "width": width, "height": height}


def _thin(values, sample_rate: int, max_points: int = MAX_PLOT_POINTS, start_time: float = 0.0):
    columns = max(2, int(max_points) // 2)
    return min_max_downsample(values, sample_rate, columns, start_time=start_time)


def _thin_with_times(values, times, max_points: int = MAX_PLOT_POINTS):
    return thin_xy(values, times, max_points)


def _smooth_envelope(envelope: np.ndarray, sample_rate: int, enabled: bool) -> np.ndarray:
    """包络绘图用 5 ms 滑动平均。

    Hilbert 包络在稳态信号上本身高频抖动，直接画会变成一条粗糙的宽带；
    平滑只影响绘图，拟合与统计仍用原始包络。
    """
    if not enabled or envelope.size < 8 or sample_rate <= 0:
        return envelope
    window = max(1, int(_ENVELOPE_SMOOTH_MS * sample_rate / 1000))
    if window <= 1 or envelope.size < window:
        return envelope
    from scipy.ndimage import uniform_filter1d
    return uniform_filter1d(envelope, window, mode="nearest")


def _colors(options: FigureOptions) -> dict[str, str]:
    if options.is_paper():
        return {
            "current": "#1a1a1a", "original": "0.62", "preview": "#d95f02",
            "envelope": "#c62828", "fit": "#1565c0", "region": "#1565c0",
            "cursor": "#6a1b9a", "spectrum": "#1a1a1a", "mark": "#c62828",
        }
    return {
        "current": "#1565c0", "original": "#9aa4b2", "preview": "#ef6c00",
        "envelope": "#2e7d32", "fit": "#c2185b", "region": "#1565c0",
        "cursor": "#6a1b9a", "spectrum": "#00838f", "mark": "#ef6c00",
    }


def render_waveform_png(
    path: str | Path,
    *,
    samples: np.ndarray,
    sample_rate: int,
    options: FigureOptions | None = None,
    original: np.ndarray | None = None,
    preview: np.ndarray | None = None,
    envelope: np.ndarray | None = None,
    envelope_times: np.ndarray | None = None,
    fit_times: np.ndarray | None = None,
    fit_values: np.ndarray | None = None,
    region: tuple[float, float] | None = None,
    cursor: float | None = None,
    labels: dict[str, str] | None = None,
) -> dict:
    """导出波形图；五种曲线各自可选，选区与游标可选。

    论文版式下若同时画了包络或拟合，自动拆成上下双子图（上波形、下包络）：
    两者量级差异大，叠在一张图里包络会被压成一条贴底的平线。
    """
    data = np.asarray(samples, dtype=np.float64).reshape(-1)
    if data.size < 2:
        raise ValueError("采样点不足，无法导出波形图")
    options = options or FigureOptions()
    names = {
        "current": "当前波形", "original": "原始波形", "preview": "去噪预览",
        "envelope": "包络", "fit": "拟合曲线",
    }
    if labels:
        names.update({k: v for k, v in labels.items() if v})
    colors = _colors(options)
    envelope_array = None if envelope is None else np.asarray(envelope, dtype=np.float64).reshape(-1)
    fitted_array = None if fit_values is None else np.asarray(fit_values, dtype=np.float64).reshape(-1)
    has_envelope = envelope_array is not None and envelope_array.size >= 2
    has_fit = fitted_array is not None and fit_times is not None and fitted_array.size >= 2

    plt = _load_pyplot()
    rc, style = _style(options)
    paper = options.is_paper()
    series: list[str] = []
    points = 0
    drawn = 0
    split = paper and (has_envelope or has_fit)

    with _RENDER_LOCK, plt.rc_context(rc):
        if split:
            fig, (top, bottom) = plt.subplots(
                2, 1, figsize=options.figsize(tall=True), sharex=True,
                gridspec_kw={"height_ratios": [1.0, 1.15], "hspace": 0.12})
            axes = [top, bottom]
            bottom.set_xlabel(r"$t$ / s")
        else:
            fig, top = plt.subplots(figsize=options.figsize())
            bottom = top
            axes = [top]
            top.set_xlabel(r"$t$ / s")

        line_width = 0.55 if paper else 0.8
        if original is not None:
            source = np.asarray(original, dtype=np.float64).reshape(-1)
            if source.size >= 2:
                times, values = _thin(source, sample_rate)
                top.plot(times, values, color=colors["original"],
                         linewidth=line_width * 0.9, label=names["original"], zorder=2)
                series.append(names["original"])
                drawn = max(drawn, len(source))
        if preview is not None:
            source = np.asarray(preview, dtype=np.float64).reshape(-1)
            if source.size >= 2:
                times, values = _thin(source, sample_rate)
                top.plot(times, values, color=colors["preview"],
                         linewidth=line_width, label=names["preview"], zorder=3)
                series.append(names["preview"])
                drawn = max(drawn, len(source))
        times, values = _thin(data, sample_rate)
        top.plot(times, values, color=colors["current"], linewidth=line_width,
                 label=names["current"], zorder=4)
        series.append(names["current"])
        drawn = max(drawn, data.size)
        points += min(data.size, MAX_PLOT_POINTS)
        top.set_ylabel(r"$x$ / FS")

        if has_envelope:
            env = _smooth_envelope(envelope_array, sample_rate, options.smooth_envelope)
            if envelope_times is not None and len(envelope_times) == len(env):
                times_env, values_env = _thin_with_times(
                    env, np.asarray(envelope_times, dtype=np.float64))
            else:
                times_env, values_env = _thin(env, sample_rate)
            bottom.plot(times_env, values_env, color=colors["envelope"],
                        linewidth=0.9 if split else line_width + 0.5,
                        label=names["envelope"], zorder=5)
            series.append(names["envelope"])
        if has_fit:
            fit_at = np.asarray(fit_times, dtype=np.float64).reshape(-1)
            if fit_at.size == fitted_array.size:
                bottom.plot(fit_at, fitted_array, color=colors["fit"],
                            linewidth=1.15 if paper else 1.6, linestyle="--",
                            label=names["fit"], zorder=6)
                series.append(names["fit"])
        if split:
            bottom.set_ylabel(r"$A$ / FS")

        if region is not None:
            start, end = float(region[0]), float(region[1])
            if end > start:
                for axis in axes:
                    axis.axvspan(start, end, color=colors["region"], alpha=0.08, zorder=1)
                series.append("选区")
        if cursor is not None and np.isfinite(cursor):
            for axis in axes:
                axis.axvline(float(cursor), color=colors["cursor"],
                             linewidth=0.8, linestyle=":", zorder=7)
            series.append("游标")

        if sample_rate:
            top.set_xlim(0.0, (data.size - 1) / float(sample_rate))
        info = _finish(plt, fig, axes, options, style, Path(path))
    info.update({"kind": "wave", "series": series, "points": points, "total_samples": int(drawn)})
    return info


def render_spectrum_png(
    path: str | Path,
    fourier,
    options: FigureOptions | None = None,
    *,
    show_phase: bool | None = None,
    mark_harmonics: bool | None = None,
    annotate_peaks: bool | None = None,
) -> dict:
    """导出振幅谱（可选叠加相位子图、谱峰标注、谐波标记）。"""
    options = options or FigureOptions()
    frequencies = np.asarray(fourier.frequencies, dtype=np.float64).reshape(-1)
    if frequencies.size < 2:
        raise ValueError("频谱数据不足，无法导出")
    use_db = options.spectrum_db
    amplitude = fourier.amplitude_dbfs if use_db else np.asarray(fourier.amplitude, dtype=np.float64)
    show_phase = options.show_phase if show_phase is None else show_phase
    mark_harmonics = options.mark_harmonics if mark_harmonics is None else mark_harmonics
    annotate_peaks = options.annotate_peaks if annotate_peaks is None else annotate_peaks
    colors = _colors(options)
    paper = options.is_paper()

    nyquist = (float(fourier.sample_rate) / 2.0
               if getattr(fourier, "sample_rate", 0) else float(frequencies[-1]))
    upper = float(options.max_frequency) if options.max_frequency and options.max_frequency > 0 else nyquist
    upper = min(upper, float(frequencies[-1]))
    keep = frequencies <= upper
    freqs = frequencies[keep]
    amps = np.asarray(amplitude, dtype=np.float64)[keep]
    if freqs.size < 2:
        raise ValueError("截取的频率范围过窄")

    plt = _load_pyplot()
    rc, style = _style(options)
    with _RENDER_LOCK, plt.rc_context(rc):
        if show_phase:
            figsize = options.figsize(tall=paper and show_phase)
            fig, axes = plt.subplots(2, 1, figsize=figsize, sharex=True,
                                     gridspec_kw={"height_ratios": [2.1, 1.0]})
            axis, phase_axis = axes
        else:
            fig, axis = plt.subplots(figsize=options.figsize())
            axes = [axis]
            phase_axis = None
        axis.plot(freqs, amps, color=colors["spectrum"], linewidth=0.6 if paper else 0.8)
        axis.set_ylabel(r"$L$ / dBFS" if use_db else r"$A$ / FS")
        series = ["振幅谱"]

        marks = []
        if mark_harmonics and getattr(fourier, "fundamental_frequency", 0):
            marks = [h for h in fourier.harmonics(max_harmonic=8)
                     if h["frequency_hz"] <= upper and h["amplitude_dbfs"] >= -100]

        if annotate_peaks and freqs.size:
            # 相邻峰靠得太近时标注文字会叠在一起，按频率间隔做一次去重；
            # 已经用 f0、2f0… 标过的谐波位置不再重复标频率，否则两套标注会压在一起。
            placed: list[float] = []
            harmonic_hz = [float(h["frequency_hz"]) for h in marks] if paper else []
            for peak in fourier.peaks(count=8):
                at = float(peak["frequency_hz"])
                if at > upper:
                    continue
                if any(abs(at - other) < max(upper * 0.012, 5.0) for other in harmonic_hz):
                    continue
                if any(abs(at - other) < upper * 0.06 for other in placed):
                    continue
                placed.append(at)
                level = float(peak["amplitude_dbfs"]) if use_db else float(peak["amplitude"])
                if paper:
                    near_right = at > upper * 0.9
                    axis.annotate(
                        f"{at:.1f} Hz", xy=(at, level),
                        xytext=(-6 if near_right else 4, 8 + 9 * (len(placed) % 2)),
                        textcoords="offset points", fontsize=6.0, color=colors["mark"],
                        ha="right" if near_right else "left",
                        bbox=dict(boxstyle="round,pad=0.18", facecolor="white",
                                  edgecolor="none", alpha=0.82))
                else:
                    axis.annotate(
                        f"{at:.1f} Hz", xy=(at, level),
                        xytext=(4, 7 if len(placed) % 2 else -15), textcoords="offset points",
                        fontsize=8.5 * max(0.5, options.dpi / float(DEFAULT_DPI)),
                        color=style["foreground"])
                axis.axvline(at, color=colors["mark"], linewidth=0.5 if paper else 0.6,
                             alpha=0.45 if paper else 0.55)
            series.append("谱峰标注")

        if marks:
            if paper and use_db:
                for index, harmonic in enumerate(sorted(marks, key=lambda h: h["frequency_hz"])):
                    at = float(harmonic["frequency_hz"])
                    level = harmonic["amplitude_dbfs"] if use_db else harmonic["amplitude"]
                    order = int(harmonic["order"])
                    axis.plot(at, level, marker="v", markersize=2.6,
                              color=colors["mark"], zorder=5)
                    tag = "$f_0$" if order == 1 else f"${order}f_0$"
                    near_right = at > upper * 0.88
                    axis.annotate(
                        f"{tag}\n{at:.0f} Hz", xy=(at, level),
                        xytext=(-7 if near_right else 0, 8 + 9 * (index % 2)),
                        textcoords="offset points", ha="right" if near_right else "center",
                        fontsize=6.0, color=colors["mark"], linespacing=1.15,
                        bbox=dict(boxstyle="round,pad=0.18", facecolor="white",
                                  edgecolor="none", alpha=0.82))
            else:
                base = float(fourier.fundamental_frequency)
                order = 1
                while base * order <= upper and order <= 12:
                    axis.axvline(base * order, color=colors["fit"], linewidth=0.6,
                                 linestyle="--", alpha=0.6)
                    order += 1
            series.append("谐波标记")

        axis.set_xlim(0.0, upper)
        if use_db:
            axis.set_ylim(max(float(np.min(amps)) - 6.0, -200.0), 6.0)
        else:
            axis.set_ylim(0.0, float(np.max(amps)) * 1.12 + 1e-12)

        if phase_axis is not None:
            phase = np.asarray(fourier.phase, dtype=np.float64)[keep]
            phase_axis.plot(freqs, phase, color=colors["fit"],
                            linewidth=0.6 if paper else 0.7, alpha=0.85)
            phase_axis.set_xlabel(r"$f$ / Hz")
            phase_axis.set_ylabel(r"$\varphi$ / rad")
            phase_axis.set_ylim(-np.pi, np.pi)
            phase_axis.set_yticks([-np.pi, -np.pi / 2, 0.0, np.pi / 2, np.pi])
            phase_axis.set_yticklabels(
                [r"$-\pi$", r"$-\pi/2$", r"$0$", r"$\pi/2$", r"$\pi$"])
            series.append("相位谱")
        else:
            axis.set_xlabel(r"$f$ / Hz")
        info = _finish(plt, fig, axes, options, style, Path(path))
    info.update({
        "kind": "spectrum", "series": series,
        "points": int(freqs.size), "total_samples": int(frequencies.size),
    })
    return info


def render_spectrogram_png(
    path: str | Path,
    spectrogram: tuple[np.ndarray, np.ndarray, np.ndarray],
    options: FigureOptions | None = None,
    *,
    db_floor: float | None = None,
) -> dict:
    """导出时频图（对数幅度色标）。"""
    options = options or FigureOptions()
    paper = options.is_paper()
    times, frequencies, magnitude = spectrogram
    times = np.asarray(times, dtype=np.float64).reshape(-1)
    frequencies = np.asarray(frequencies, dtype=np.float64).reshape(-1)
    magnitude = np.asarray(magnitude, dtype=np.float64)
    if magnitude.size == 0 or times.size < 2 or frequencies.size < 2:
        raise ValueError("时频数据不足，无法导出")

    nyquist = float(frequencies[-1])
    upper = float(options.max_frequency) if options.max_frequency and options.max_frequency > 0 else nyquist
    upper = min(upper, nyquist)
    rows = frequencies <= upper
    data = magnitude[rows, :]
    freq_axis = frequencies[rows]
    if data.shape[0] < 2:
        raise ValueError("截取的频率范围过窄")

    floor = float(options.db_floor if db_floor is None else db_floor)
    top = float(np.percentile(data, 99.5))
    if not np.isfinite(floor) or floor >= top:
        floor = top - 60.0

    plt = _load_pyplot()
    rc, style = _style(options)
    with _RENDER_LOCK, plt.rc_context(rc):
        fig, axis = plt.subplots(figsize=options.figsize())
        image = axis.imshow(
            data, origin="lower", aspect="auto", cmap="magma" if paper else "viridis",
            extent=[float(times[0]), float(times[-1]), float(freq_axis[0]), float(freq_axis[-1])],
            vmin=floor, vmax=top, interpolation="nearest", rasterized=paper,
        )
        axis.set_xlabel(r"$t$ / s")
        axis.set_ylabel(r"$f$ / Hz")
        bar = fig.colorbar(image, ax=axis, pad=0.02 if paper else 0.015,
                           fraction=0.045 if paper else 0.05)
        bar.set_label(r"$L$ / dBFS")
        if paper:
            bar.ax.tick_params(direction="in", labelsize=7, width=0.6, top=True, right=True)
            bar.outline.set_linewidth(0.5)
        bar.ax.yaxis.label.set_color(style["foreground"])
        info = _finish(plt, fig, [axis], options, style, Path(path))
    info.update({
        "kind": "spectrogram", "series": ["时频图"],
        "points": int(data.size), "total_samples": int(magnitude.size),
    })
    return info


KIND_LABELS = {
    "wave": "波形图",
    "spectrum": "频谱图（傅立叶）",
    "spectrogram": "时频图",
}


# 模块加载即预热：必须在主线程完成 matplotlib 的首次惰性构建。
_warm_up()
