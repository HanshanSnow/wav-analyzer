"""批量处理流水线：把单文件的全套功能串成可复用的步骤脚本，逐个文件执行。

设计约束（都是为了“不卡死”）：
  * 本模块**不导入 Qt**，引擎只做纯计算，可以在工作线程里安全运行；
  * 步骤用普通 dict 描述（``{"kind": ..., "params": {...}}``），可直接存成 JSON，
    也便于测试里手写；
  * 每个文件独立状态，绝不共用数组引用——否则一次裁剪会污染下一个文件；
  * 大文件不复制多余副本：只有该步真的改数据时才 copy 一次。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Sequence

import numpy as np

from .audio_io import AudioData, read_wav, write_wav
from .denoise import DenoiseResult, detect_and_repair_impulses
from .editor import trim_range
from .envelope import EnvelopeFit, compute_envelope, fit_envelope
from .exporter import build_report_html, export_rows_csv, save_report
from .figure_export import (
    FigureOptions, render_spectrogram_png, render_spectrum_png, render_waveform_png,
)
from .spectral import fourier_analysis, stft_spectrogram
from .statistics import interval_statistics, statistics_rows

if TYPE_CHECKING:
    from .calibration import Calibration

from .txt_export import (
    SECTION_ORDER, TxtExportOptions, file_md5, write_analysis_txt,
)

# 进度回调：stage ∈ {"import", "process", "export", "merge"}；
# index/total 是文件序号（1 起），fraction 是“当前文件内”的完成比例。
ProgressHook = Callable[[str, int, int, str, float], None]
CancelHook = Callable[[], bool]


# ---------------------------------------------------------------- 参数描述


@dataclass(frozen=True)
class Param:
    """一个步骤参数。界面按 kind 自动生成控件，引擎按 key 取值。"""

    key: str
    label: str
    kind: str                      # float / int / choice / bool / checklist / text
    default: Any
    choices: tuple[tuple[str, str], ...] = ()
    minimum: float = 0.0
    maximum: float = 1.0e7
    decimals: int = 2
    step: float = 0.1
    suffix: str = ""
    tooltip: str = ""


@dataclass(frozen=True)
class StepSpec:
    kind: str
    label: str
    description: str
    params: tuple[Param, ...]
    # 该步骤需要前序提供的数据；缺了就自动补算，不强制用户排序。
    needs: tuple[str, ...] = ()
    # 单声道文件上会自动跳过（只在说明里记一条）。
    stereo_only: bool = False


_REGION = (
    Param("region", "统计区间", "choice", "all",
          (("all", "全文件"), ("trim", "去掉首尾"), ("fixed", "固定区间")),
          tooltip="去掉首尾用于跳过起振与收尾的瞬态"),
    Param("head", "去掉开头", "float", 0.2, minimum=0.0, maximum=600.0,
          decimals=3, step=0.1, suffix=" s"),
    Param("tail", "去掉结尾", "float", 0.2, minimum=0.0, maximum=600.0,
          decimals=3, step=0.1, suffix=" s"),
    Param("start", "起点", "float", 0.0, minimum=0.0, maximum=1.0e7,
          decimals=3, step=0.1, suffix=" s"),
    Param("end", "终点", "float", 0.0, minimum=0.0, maximum=1.0e7,
          decimals=3, step=0.1, suffix=" s（0 表示到文件末尾）"),
)

_FUNDAMENTAL = (
    Param("fundamental", "已知激励频率", "choice", "auto",
          (("auto", "自动估计（取最强峰）"),
           ("fixed", "固定值（所有文件相同）"),
           ("name", "文件名里的频率（如 1000Hz）")),
          tooltip="从文件名解析：识别 1000Hz、2kHz 这类片段，适合按频率命名的一批录音"),
    Param("fundamental_hz", "固定频率值", "float", 1000.0, minimum=0.0,
          maximum=1.0e6, decimals=2, step=10.0, suffix=" Hz"),
)

STEP_SPECS: tuple[StepSpec, ...] = (
    StepSpec(
        "denoise", "冲击去噪",
        "检测超出稳健阈值的短脉冲并三次样条修补；无法修补的超长区间标记为无效点。",
        (
            Param("threshold", "稳健阈值", "float", 8.0, minimum=0.5, maximum=100.0,
                  decimals=2, step=0.5, tooltip="按稳健标准差倍数判定冲击，越小越敏感"),
            Param("max_repair_ms", "最长修复", "float", 3.0, minimum=0.1, maximum=100.0,
                  decimals=2, step=0.1, suffix=" ms"),
            Param("scope", "处理范围", "choice", "all",
                  (("all", "全部声道"), ("first", "仅第 1 声道"))),
        ),
    ),
    StepSpec(
        "trim", "裁剪到区间",
        "只保留指定时间区间，其后的步骤都基于裁剪后的数据。",
        (
            Param("start", "起点", "float", 0.0, minimum=0.0, maximum=1.0e7,
                  decimals=3, step=0.1, suffix=" s"),
            Param("end", "终点", "float", 0.0, minimum=0.0, maximum=1.0e7,
                  decimals=3, step=0.1, suffix=" s（0 表示到文件末尾）"),
        ),
    ),
    StepSpec(
        "envelope", "包络拟合",
        "对指定区间求 Hilbert 包络并拟合（auto 会按残差自动选择常数/线性/指数）。",
        (Param("model", "拟合模型", "choice", "auto",
               (("auto", "auto（自动选择）"), ("constant", "常数"),
                ("linear", "线性"), ("exponential", "指数")),),)
        + _REGION,
        needs=("envelope",),
    ),
    StepSpec(
        "stats", "区间统计",
        "计算选区的 RMS、峰值、主频、THD 等；主频与 THD 受已知激励频率约束。",
        _REGION + _FUNDAMENTAL,
        needs=("stats",),
    ),
    StepSpec(
        "dual", "双通道时延与电平",
        "比较两声道的主频幅值与到达时延。单声道文件自动跳过。",
        _FUNDAMENTAL,
        needs=("dual",),
        stereo_only=True,
    ),
    StepSpec(
        "export_wav", "导出处理后 WAV",
        "把当前处理结果另存为新 WAV，源文件不动。",
        (
            Param("suffix", "文件名后缀", "text", "_处理后"),
            Param("subtype", "采样格式", "choice", "PCM_24",
                  (("PCM_16", "PCM_16（16 bit）"), ("PCM_24", "PCM_24（24 bit）"),
                   ("PCM_32", "PCM_32（32 bit）"), ("FLOAT", "FLOAT（32 bit 浮点）"))),
        ),
    ),
    StepSpec(
        "export_txt", "导出分析 TXT",
        "定宽对齐的纯文本分析报告；可每个文件一份，也可合并成一份汇总。",
        (
            Param("aggregate", "输出方式", "choice", "file",
                  (("file", "每个文件一个 TXT"), ("single", "合并为一个 TXT"))),
            Param("merged_name", "合并文件名", "text", "批量分析汇总.txt"),
            Param("suffix", "文件名后缀", "text", "_分析"),
            Param("sections", "导出章节", "checklist",
                  tuple(key for key, _ in SECTION_ORDER),
                  tuple(SECTION_ORDER),
                  tooltip="合并模式下建议关掉原坐标，否则汇总文件会非常大"),
            Param("coord_mode", "坐标取法", "choice", "per_second",
                  (("per_second", "每秒固定点数"), ("step", "按步长抽稀"),
                   ("all", "全部采样点"))),
            Param("coord_per_second", "每秒点数", "float", 1000.0, minimum=1.0,
                  maximum=1.0e6, decimals=1, step=100.0),
            Param("coord_step", "抽稀步长", "int", 1, minimum=1, maximum=1_000_000),
        ),
    ),
    StepSpec(
        "export_png", "导出图像 PNG",
        "按论文或屏幕版式重新渲染图像，不是界面截图。",
        (
            Param("kinds", "图像类型", "checklist", ("wave",),
                  (("wave", "波形图"), ("spectrum", "幅值谱"), ("spectrogram", "时频图"))),
            Param("layout", "版式", "choice", "paper_single",
                  (("paper_single", "论文单栏 3.5×2.45 in（600 dpi）"),
                   ("paper_double", "论文双栏 7.0×2.6 in（600 dpi）"),
                   ("screen", "屏幕 1600×900"))),
            Param("envelope", "波形图叠包络", "bool", True),
            Param("fit", "波形图叠拟合曲线", "bool", False),
            Param("region", "波形图标出选区", "bool", False),
        ),
    ),
    StepSpec(
        "export_csv", "导出统计 CSV",
        "统计量写成 CSV，可直接进 Excel / Origin；默认合并成一张表。",
        (
            Param("aggregate", "输出方式", "choice", "single",
                  (("single", "合并为一个 CSV（每个文件一行）"),
                   ("file", "每个文件一个 CSV"))),
            Param("merged_name", "合并文件名", "text", "批量统计.csv"),
            Param("suffix", "文件名后缀", "text", "_统计"),
        ),
    ),
    StepSpec(
        "export_html", "生成 HTML 报告",
        "每个文件一份独立报告，含波形、频谱与统计表。",
        (Param("suffix", "文件名后缀", "text", "_报告"),),
    ),
)

STEP_SPEC_BY_KIND: dict[str, StepSpec] = {spec.kind: spec for spec in STEP_SPECS}


def default_params(kind: str) -> dict[str, Any]:
    """按规格取一份默认参数字典（copy，避免多处共享同一 list）。"""
    spec = STEP_SPEC_BY_KIND[kind]
    params: dict[str, Any] = {}
    for param in spec.params:
        value = param.default
        params[param.key] = list(value) if isinstance(value, tuple) else value
    return params


def new_step(kind: str) -> dict[str, Any]:
    return {"kind": kind, "params": default_params(kind)}


def normalize_steps(steps: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """补全缺失参数、丢弃未知步骤；界面保存/加载与脚本调用共用。"""
    result: list[dict[str, Any]] = []
    for step in steps or ():
        kind = str(step.get("kind", ""))
        if kind not in STEP_SPEC_BY_KIND:
            continue
        merged = default_params(kind)
        incoming = step.get("params") or {}
        for key, value in incoming.items():
            if key in merged:
                merged[key] = list(value) if isinstance(value, (list, tuple)) else value
        result.append({"kind": kind, "params": merged})
    return result


_REGION_ONLY_TRIM = {"head", "tail"}
_REGION_ONLY_FIXED = {"start", "end"}


def irrelevant_keys(kind: str, params: dict[str, Any]) -> set[str]:
    """当前参数组合下没有意义的键：摘要里不显示，免得一句话里塞十个数字。"""
    skip: set[str] = set()
    if "region" in params:
        if params.get("region") != "trim":
            skip |= _REGION_ONLY_TRIM
        if params.get("region") != "fixed":
            skip |= _REGION_ONLY_FIXED
    if "fundamental" in params and params.get("fundamental") != "fixed":
        skip.add("fundamental_hz")
    if kind == "export_txt":
        if params.get("coord_mode") != "step":
            skip.add("coord_step")
        if params.get("coord_mode") != "per_second":
            skip.add("coord_per_second")
        if params.get("aggregate") != "single":
            skip.add("merged_name")
    if kind == "export_csv" and params.get("aggregate") != "single":
        skip.add("merged_name")
    if kind == "export_png" and "wave" not in (params.get("kinds") or []):
        skip |= {"envelope", "fit", "region"}
    return skip


def describe_step(step: dict[str, Any]) -> str:
    """一行中文摘要，只列与当前参数组合有关的非默认值。"""
    kind = step.get("kind", "")
    spec = STEP_SPEC_BY_KIND.get(kind)
    if spec is None:
        return kind or "（未知步骤）"
    params = step.get("params") or {}
    skip = irrelevant_keys(kind, params)
    parts: list[str] = []
    for param in spec.params:
        if param.key in skip:
            continue
        value = params.get(param.key, param.default)
        default = list(param.default) if isinstance(param.default, tuple) else param.default
        if param.kind == "checklist":
            labels = dict(param.choices)
            picked = [labels.get(item, item) for item in value or ()]
            if value and list(value) != default:
                parts.append("、".join(picked))
            continue
        if param.kind == "choice":
            if value != param.default:
                parts.append(dict(param.choices).get(value, str(value)))
            continue
        if param.kind == "bool":
            if bool(value) != bool(param.default):
                parts.append(("含" if value else "不含") + param.label)
            continue
        if param.kind == "text":
            if str(value) != str(param.default):
                # 合并文件名、文件名后缀都是 text，不能一律写成“后缀 xxx”
                prefix = "后缀" if "后缀" in param.label else param.label
                parts.append(f"{prefix} {value}")
            continue
        if value != param.default:
            parts.append(f"{param.label} {value}{param.suffix.strip()}")
    summary = "；".join(part for part in parts if part)
    return f"{spec.label} — {summary}" if summary else spec.label


# ---------------------------------------------------------------- 参数解析

_NAME_HZ = re.compile(r"(\d+(?:\.\d+)?)\s*(k?)hz", re.IGNORECASE)


def parse_fundamental_from_name(name: str) -> float | None:
    """从文件名里抓 1000Hz / 2kHz 之类的激励频率。"""
    match = _NAME_HZ.search(name or "")
    if not match:
        return None
    value = float(match.group(1))
    if match.group(2):
        value *= 1000.0
    return value if value > 0 else None


def resolve_fundamental(params: dict[str, Any], name: str) -> float | None:
    mode = str(params.get("fundamental", "auto"))
    if mode == "fixed":
        value = float(params.get("fundamental_hz", 0.0) or 0.0)
        return value if value > 0 else None
    if mode == "name":
        return parse_fundamental_from_name(name)
    return None


def resolve_region(params: dict[str, Any], duration: float) -> tuple[float, float]:
    """把区间参数换算成 (start, end) 秒，并夹到有效范围内。"""
    mode = str(params.get("region", "all"))
    if mode == "trim":
        start = float(params.get("head", 0.0))
        end = duration - float(params.get("tail", 0.0))
    elif mode == "fixed":
        start = float(params.get("start", 0.0))
        end = float(params.get("end", 0.0)) or duration
    else:
        start, end = 0.0, duration
    start = max(0.0, min(start, duration))
    end = max(start, min(end, duration))
    if end - start <= 0.0:
        raise ValueError("统计区间为空：请检查起止时间或去掉的首尾长度")
    return start, end


def _txt_options(params: dict[str, Any]) -> TxtExportOptions:
    sections = params.get("sections")
    if not sections:
        sections = [key for key, _ in SECTION_ORDER]
    return TxtExportOptions(
        sections=tuple(sections),
        coord_mode=str(params.get("coord_mode", "per_second")),
        coord_step=int(params.get("coord_step", 1) or 1),
        coord_per_second=float(params.get("coord_per_second", 1000.0) or 1000.0),
        stat_scopes=("full",),
    )


def _figure_options(params: dict[str, Any]) -> FigureOptions:
    layout = str(params.get("layout", "paper_single"))
    if layout == "paper_double":
        options = FigureOptions(layout="paper", column="double")
    elif layout == "screen":
        options = FigureOptions(layout="screen", width_px=1600, height_px=900)
    else:
        options = FigureOptions(layout="paper", column="single")
    options.background = "white"
    options.legend = True
    options.legend_outside = True
    options.grid = False
    return options


# ---------------------------------------------------------------- 结果


@dataclass
class FileOutcome:
    path: Path
    ok: bool = True
    error: str = ""
    notes: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    rows: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchResult:
    files: list[FileOutcome] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    cancelled: bool = False
    seconds: float = 0.0

    @property
    def ok_count(self) -> int:
        return sum(1 for item in self.files if item.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for item in self.files if not item.ok)

    def summary(self) -> str:
        head = f"共 {len(self.files)} 个文件，成功 {self.ok_count}，失败 {self.fail_count}"
        if self.cancelled:
            head += "（已取消）"
        head += f"，用时 {self.seconds:.1f} s"
        if self.outputs:
            head += f"，输出 {len(self.outputs)} 个文件"
        failures = [item for item in self.files if not item.ok]
        if failures:
            head += "\n" + "\n".join(
                f"· {item.path.name}：{item.error}" for item in failures[:8])
            if len(failures) > 8:
                head += f"\n· 其余 {len(failures) - 8} 个失败略"
        return head


# ---------------------------------------------------------------- 单文件状态


class _State:
    """一个文件的处理状态。数组只在该步真的改数据时才产生新副本。"""

    def __init__(self, path: Path, audio: AudioData, calibration: "Calibration | None" = None):
        self.path = path
        self.audio = audio
        # 整批共用同一个校准：同一批录音的麦克风、增益、系统音量本来就该一致
        self.calibration = calibration
        self.samples = np.array(audio.samples, dtype=np.float64, copy=True)
        self.mask = np.ones(self.samples.shape, dtype=bool)
        self.edits: list[str] = []
        self.denoise: DenoiseResult | None = None
        self.envelope: np.ndarray | None = None
        self.envelope_times: np.ndarray | None = None
        self.envelope_span: tuple[float, float] | None = None
        self.fit: EnvelopeFit | None = None
        self.fit_times: np.ndarray | None = None
        self.stats: dict[str, Any] | None = None
        # 统计步骤解析出的激励频率：TXT/PNG/HTML 若自己没设，就沿用这里的结果，
        # 否则报告里的「已知激励频率」会静默回退成自动估峰。
        self.fundamental: float | None = None
        self.fourier = None
        self.dual: dict[str, Any] | None = None
        self.rows: dict[str, Any] = {}
        self.notes: list[str] = []

    @property
    def sample_rate(self) -> int:
        return int(self.audio.sample_rate)

    @property
    def duration(self) -> float:
        return float(self.samples.shape[0] / self.sample_rate)

    @property
    def channels(self) -> int:
        return int(self.samples.shape[1])

    def channel_samples(self, index: int = 0) -> np.ndarray:
        return self.samples[:, index]

    def channel_mask(self, index: int = 0) -> np.ndarray:
        return self.mask[:, index]


def _ensure_fourier(state: _State, fundamental: float | None):
    if state.fourier is None:
        state.fourier = fourier_analysis(
            state.channel_samples(0), state.sample_rate, fundamental_frequency=fundamental)
    return state.fourier


def _ensure_stats(state: _State, params: dict[str, Any]) -> dict[str, Any]:
    if state.stats is None:
        start, end = resolve_region(params or {"region": "all"}, state.duration)
        fundamental = resolve_fundamental(params or {}, state.path.name)
        state.stats = interval_statistics(
            state.channel_samples(0), state.sample_rate, start, end,
            state.channel_mask(0), fundamental, calibration=state.calibration)
    return state.stats


# ---------------------------------------------------------------- 单文件执行


def _apply_step(state: _State, step: dict[str, Any], ctx: dict[str, Any]) -> None:
    kind = step["kind"]
    params = step.get("params") or {}
    sample_rate = state.sample_rate

    if kind == "denoise":
        indexes = range(state.channels) if params.get("scope", "all") == "all" else range(1)
        total_repaired = 0
        total_excluded = 0
        for index in indexes:
            result = detect_and_repair_impulses(
                state.samples[:, index], sample_rate,
                threshold=float(params.get("threshold", 8.0)),
                max_repair_ms=float(params.get("max_repair_ms", 3.0)))
            state.samples[:, index] = result.cleaned
            state.mask[:, index] = result.valid_mask
            total_repaired += result.repaired_count
            total_excluded += result.excluded_count
            if index == 0:
                state.denoise = result
        state.edits.append("denoise")
        invalid_ratio = float(1.0 - state.mask.mean())
        if invalid_ratio > 0.5:
            # 阈值过低或数据本身以冲击为主时，去噪会把大半数据标成无效，
            # 后续统计会静默给出毫无意义的数字。这里宁可整份失败。
            raise ValueError(
                f"去噪把 {invalid_ratio * 100:.0f}% 的采样点标为无效，"
                "请提高稳健阈值或先确认数据是否异常")
        state.notes.append(f"去噪修复 {total_repaired} 处，标记无效 {total_excluded} 处")
        return

    if kind == "trim":
        start = float(params.get("start", 0.0))
        end = float(params.get("end", 0.0)) or state.duration
        trimmed = trim_range(state.samples, state.mask, sample_rate, start, end)
        state.samples = np.array(trimmed.samples, copy=False)
        state.mask = np.array(trimmed.valid_mask, copy=False)
        state.edits.append("trim")
        state.stats = None
        state.fourier = None
        state.dual = None
        state.notes.append(
            f"裁剪至 {trimmed.start_seconds:.3f}–{trimmed.end_seconds:.3f} s")
        return

    if kind == "envelope":
        start, end = resolve_region(params, state.duration)
        x = state.channel_samples(0)
        margin = min(max(1, int(round(0.5 * sample_rate))), max(0, (x.size - 2) // 2))
        i0 = int(np.clip(round(start * sample_rate) - margin, 0, max(0, x.size - 2)))
        i1 = int(np.clip(round(end * sample_rate) + margin, i0 + 2, x.size))
        times, values = compute_envelope(x[i0:i1], sample_rate)
        times = times + i0 / sample_rate
        selected = ((times >= start) & (times <= end)
                    & np.asarray(state.channel_mask(0), dtype=bool)[i0:i1])
        indexes = np.flatnonzero(selected)
        if indexes.size < 2:
            raise ValueError("选区内有效包络点不足")
        if indexes.size > 5000:
            indexes = indexes[np.linspace(0, indexes.size - 1, 5000).astype(int)]
        state.envelope = values
        state.envelope_times = times
        state.envelope_span = (start, end)
        state.fit = fit_envelope(times[indexes], values[indexes],
                                 str(params.get("model", "auto")))
        state.fit_times = times[indexes]
        return

    if kind == "stats":
        state.stats = None
        state.fundamental = resolve_fundamental(params, state.path.name)
        state.stats = _ensure_stats(state, params)
        state.notes.append(
            f"主频 {state.stats['main_frequency_hz']:.3f} Hz，"
            f"电平 {state.stats['main_amplitude_dbfs']:.2f} dBFS")
        return

    if kind == "dual":
        if state.channels < 2:
            state.notes.append("单声道文件，已跳过双通道分析")
            return
        from .dual_channel import analyze_dual_channel

        fundamental = resolve_fundamental(params, state.path.name)
        if fundamental is None:
            fundamental = float(_ensure_fourier(state, None).main_frequency)
        state.dual = analyze_dual_channel(state.audio, fundamental)
        return

    if kind == "export_wav":
        target = _output_path(state, params, "_处理后", ".wav", ctx)
        write_wav(target, state.samples, sample_rate,
                  subtype=str(params.get("subtype", "PCM_24")))
        _record_output(state, target, ctx)
        return

    if kind == "export_txt":
        _export_txt(state, params, ctx)
        return

    if kind == "export_png":
        _export_png(state, params, ctx)
        return

    if kind == "export_csv":
        _export_csv(state, params, ctx)
        return

    if kind == "export_html":
        _export_html(state, params, ctx)
        return

    raise ValueError(f"未知步骤类型：{kind}")


def _output_dir(ctx: dict[str, Any], state: _State) -> Path:
    root = ctx.get("output_dir")
    return Path(root) if root else state.path.parent


def _output_path(state: _State, params: dict[str, Any], default_suffix: str,
                 extension: str, ctx: dict[str, Any]) -> Path:
    suffix = str(params.get("suffix", default_suffix) or default_suffix)
    stem = state.path.stem or "audio"
    if state.channels > 1:
        stem = f"{stem}"
    target = _output_dir(ctx, state) / f"{stem}{suffix}{extension}"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _record_output(state: _State, target: Path, ctx: dict[str, Any]) -> None:
    ctx.setdefault("outputs", []).append(str(target))


def _export_txt(state: _State, params: dict[str, Any], ctx: dict[str, Any]) -> None:
    options = _txt_options(params)
    fundamental = resolve_fundamental(params, state.path.name)
    if fundamental is None:
        fundamental = state.fundamental
    source = state.path
    try:
        size_mb = source.stat().st_size / 1024 / 1024
    except OSError:
        size_mb = 0.0

    if str(params.get("aggregate", "file")) == "single":
        target = ctx["merged_txt"]
        append = target.exists() and target.stat().st_size > 0
        ctx["merged_outputs"].add(str(target))
    else:
        target = _output_path(state, params, "_分析", ".txt", ctx)
        append = False

    result = write_analysis_txt(
        target,
        samples=state.channel_samples(0),
        sample_rate=state.sample_rate,
        source_name=source.name,
        source_path=str(source),
        subtype=state.audio.subtype,
        size_mb=size_mb,
        md5=file_md5(source),
        data_label="批量处理结果（已编辑）" if state.edits else "源文件（未修改）",
        channels=state.channels,
        edit_depth=len(state.edits),
        denoise_edits=state.edits.count("denoise"),
        trim_edits=state.edits.count("trim"),
        fourier=_ensure_fourier(state, fundamental),
        envelope=state.envelope,
        envelope_times=state.envelope_times,
        envelope_span=state.envelope_span,
        fit=state.fit,
        denoise=state.denoise,
        dual=state.dual,
        options=options,
        fundamental=fundamental,
        calibration=state.calibration,
        valid_mask=state.channel_mask(0),
        append=append,
        skip_footer=bool(str(params.get("aggregate", "file")) == "single"),
    )
    state.notes.append(f"TXT {result['rows']:,} 行 → {target.name}")
    if str(params.get("aggregate", "file")) != "single":
        _record_output(state, target, ctx)


def _export_png(state: _State, params: dict[str, Any], ctx: dict[str, Any]) -> None:
    kinds = list(params.get("kinds") or ["wave"])
    options = _figure_options(params)
    fundamental = resolve_fundamental(params, state.path.name)
    if fundamental is None:
        fundamental = state.fundamental
    stem = state.path.stem or "audio"
    root = _output_dir(ctx, state)

    if "wave" in kinds:
        target = root / f"{stem}_波形.png"
        render_waveform_png(
            target,
            samples=state.channel_samples(0),
            sample_rate=state.sample_rate,
            options=options,
            envelope=state.envelope if params.get("envelope", True) else None,
            envelope_times=state.envelope_times if params.get("envelope", True) else None,
            fit_times=state.fit_times if params.get("fit", False) else None,
            fit_values=state.fit.fitted if (params.get("fit", False) and state.fit) else None,
            region=ctx.get("region") if params.get("region", False) else None,
        )
        _record_output(state, target, ctx)

    if "spectrum" in kinds:
        target = root / f"{stem}_幅值谱.png"
        render_spectrum_png(target, _ensure_fourier(state, fundamental), options,
                            annotate_peaks=True, mark_harmonics=True)
        _record_output(state, target, ctx)

    if "spectrogram" in kinds:
        target = root / f"{stem}_时频图.png"
        spectrogram = stft_spectrogram(state.channel_samples(0), state.sample_rate)
        render_spectrogram_png(target, spectrogram, options)
        _record_output(state, target, ctx)


def _stats_row(state: _State, params: dict[str, Any]) -> dict[str, Any]:
    stats = _ensure_stats(state, params)
    row: dict[str, Any] = {"file": state.path.name}
    for key, _label, _value, _note in statistics_rows(stats):
        value = stats.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            row[key] = value
    return row


def _export_csv(state: _State, params: dict[str, Any], ctx: dict[str, Any]) -> None:
    row = _stats_row(state, params)
    state.rows = row
    if str(params.get("aggregate", "single")) == "single":
        ctx["csv_rows"].append(row)
        return
    target = _output_path(state, params, "_统计", ".csv", ctx)
    export_rows_csv(target, [row])
    _record_output(state, target, ctx)


def _export_html(state: _State, params: dict[str, Any], ctx: dict[str, Any]) -> None:
    fundamental = resolve_fundamental(params, state.path.name)
    if fundamental is None:
        fundamental = state.fundamental
    stats = _ensure_stats(state, params)
    fourier = _ensure_fourier(state, fundamental)
    content = build_report_html(
        str(state.path), state.sample_rate, 0, stats, fourier,
        np.array(state.channel_samples(0), copy=True),
        state.envelope, state.fit, state.denoise, "")
    target = _output_path(state, params, "_报告", ".html", ctx)
    save_report(target, content)
    _record_output(state, target, ctx)


# ---------------------------------------------------------------- 主入口


def _merged_banner(total: int, files: Sequence[Path]) -> str:
    lines = ["声音实验 WAV 数据处理程序 — 批量分析汇总", ""]
    lines.append(f"# 文件数：{total}")
    lines.append("# 数据来源：批量处理（每个文件的完整报告按处理顺序依次附在下方）")
    lines.append("# 分段方式：每段以「分析数据导出」标题开始，含源文件名、路径与 MD5 指纹")
    lines.append("")
    for index, path in enumerate(files, 1):
        lines.append(f"# [{index:>4}] {path}")
    lines.append("")
    return "\n".join(lines).replace("\r\n", "\n")


def _merged_name(script: Sequence[dict[str, Any]], kind: str, fallback: str) -> str:
    """合并输出的文件名取自步骤参数，界面里改了就生效。"""
    for step in script:
        if step["kind"] == kind and str(step["params"].get("aggregate")) == "single":
            name = str(step["params"].get("merged_name") or "").strip()
            return name or fallback
    return fallback


def run_batch(
    files: Sequence[str | Path],
    steps: Sequence[dict[str, Any]],
    *,
    output_dir: str | Path | None = None,
    progress: ProgressHook | None = None,
    should_cancel: CancelHook | None = None,
    merged_txt_name: str | None = None,
    merged_csv_name: str | None = None,
    calibration: "Calibration | None" = None,
) -> BatchResult:
    """按步骤脚本逐个处理文件。整个过程只读源文件，导出写到 output_dir。"""
    paths = [Path(item) for item in files]
    script = normalize_steps(steps)
    result = BatchResult()
    started = time.perf_counter()
    total = len(paths)

    def emit(stage: str, index: int, name: str, fraction: float) -> None:
        if progress is not None:
            progress(stage, index, total, name, max(0.0, min(1.0, fraction)))

    if not paths or not script:
        result.seconds = 0.0
        return result

    root = Path(output_dir) if output_dir else None
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)

    ctx: dict[str, Any] = {
        "output_dir": str(root) if root else "",
        "outputs": [],
        "csv_rows": [],
        "merged_outputs": set(),
        "region": None,
        "fundamental_hz": 0.0,
    }

    # 合并模式的目标文件：先落盘横幅，后面按文件顺序追加。
    needs_txt_merge = any(step["kind"] == "export_txt"
                          and str(step["params"].get("aggregate")) == "single"
                          for step in script)
    needs_csv_merge = any(step["kind"] == "export_csv"
                          and str(step["params"].get("aggregate")) == "single"
                          for step in script)
    if needs_txt_merge:
        base = root or paths[0].parent
        base.mkdir(parents=True, exist_ok=True)
        name = merged_txt_name or _merged_name(script, "export_txt", "批量分析汇总.txt")
        target = base / name
        target.write_text(_merged_banner(total, paths), encoding="utf-8-sig")
        ctx["merged_txt"] = target
    if needs_csv_merge:
        base = root or paths[0].parent
        name = merged_csv_name or _merged_name(script, "export_csv", "批量统计.csv")
        ctx["merged_csv"] = base / name

    for position, path in enumerate(paths, 1):
        if should_cancel is not None and should_cancel():
            result.cancelled = True
            break

        emit("import", position, path.name, 0.0)
        try:
            audio = read_wav(path)
        except Exception as exc:                       # 单个文件读失败不影响其余
            result.files.append(FileOutcome(path, ok=False,
                                            error=f"{type(exc).__name__}: {exc}"))
            continue

        state = _State(path, audio, calibration)
        try:
            quality = audio.quality_report()[0]
            if quality["clipping_warning"]:
                state.notes.append("警告：源文件可能存在削顶")
            state.notes.append(
                f"{audio.duration:.3f} s / {audio.sample_rate} Hz / {(audio.subtype or '未知')}")

            emit("process", position, path.name, 0.0)
            step_count = max(1, len(script))
            for order, step in enumerate(script, 1):
                # 取消只在“文件之间”生效：半途中断会留下导出了一半的文件，
                # 用户看到的“当前文件处理完后结束”必须和实现一致。
                if step["kind"] == "stats":
                    params = step["params"]
                    if params.get("region") == "fixed":
                        ctx["region"] = resolve_region(params, state.duration)
                _apply_step(state, step, ctx)
                emit("process", position, path.name, order / step_count)
        except Exception as exc:
            result.files.append(FileOutcome(
                path, ok=False, error=f"{type(exc).__name__}: {exc}",
                notes=state.notes, outputs=[]))
            continue

        outcome = FileOutcome(path, ok=True, notes=state.notes,
                              outputs=[], rows=dict(state.rows))
        result.files.append(outcome)
        emit("process", position, path.name, 1.0)

    # 合并输出落盘
    if needs_csv_merge and ctx["csv_rows"]:
        if not (should_cancel is not None and should_cancel()):
            emit("merge", total, Path(ctx["merged_csv"]).name, 0.0)
            export_rows_csv(ctx["merged_csv"], ctx["csv_rows"])
    if needs_txt_merge:
        target = ctx["merged_txt"]
        if target.exists():
            with target.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write("\n# 批量处理结束：" + time.strftime("%Y-%m-%d %H:%M:%S") + "\n")

    result.outputs = list(ctx["outputs"]) + sorted(str(item) for item in ctx["merged_outputs"])
    if needs_csv_merge and ctx["csv_rows"]:
        result.outputs.append(str(ctx["merged_csv"]))
    result.seconds = time.perf_counter() - started
    emit("done", total, "", 1.0)
    return result
