"""批量处理流水线：把单文件的全套功能串成可复用的步骤脚本，逐个文件执行。

设计约束（都是为了“不卡死”）：
  * 本模块**不导入 Qt**，引擎只做纯计算，可以在工作线程里安全运行；
  * 步骤用普通 dict 描述（``{"kind": ..., "params": {...}}``），可直接存成 JSON，
    也便于测试里手写；
  * 每个文件独立状态，绝不共用数组引用——否则一次裁剪会污染下一个文件；
  * 大文件不复制多余副本：只有该步真的改数据时才 copy 一次。
"""

from __future__ import annotations

from core.i18n import tf, tr
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Sequence

import numpy as np

from .anc import Diagnostics as AncDiagnostics
from .anc import METHOD_LABELS, METHOD_SPECS, run_method as run_anc_method
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
    Param("region", tr("统计区间"), "choice", "all",
          (("all", tr("全文件")), ("trim", tr("去掉首尾")), ("fixed", tr("固定区间"))),
          tooltip=tr("去掉首尾用于跳过起振与收尾的瞬态")),
    Param("head", tr("去掉开头"), "float", 0.2, minimum=0.0, maximum=600.0,
          decimals=3, step=0.1, suffix=" s"),
    Param("tail", tr("去掉结尾"), "float", 0.2, minimum=0.0, maximum=600.0,
          decimals=3, step=0.1, suffix=" s"),
    Param("start", tr("起点"), "float", 0.0, minimum=0.0, maximum=1.0e7,
          decimals=3, step=0.1, suffix=" s"),
    Param("end", tr("终点"), "float", 0.0, minimum=0.0, maximum=1.0e7,
          decimals=3, step=0.1, suffix=tr(" s（0 表示到文件末尾）")),
)

_FUNDAMENTAL = (
    Param("fundamental", tr("已知激励频率"), "choice", "auto",
          (("auto", tr("自动估计（取最强峰）")),
           ("fixed", tr("固定值（所有文件相同）")),
           ("name", tr("文件名里的频率（如 1000Hz）"))),
          tooltip=tr("从文件名解析：识别 1000Hz、2kHz 这类片段，适合按频率命名的一批录音")),
    Param("fundamental_hz", tr("固定频率值"), "float", 1000.0, minimum=0.0,
          maximum=1.0e6, decimals=2, step=10.0, suffix=" Hz"),
)

STEP_SPECS: tuple[StepSpec, ...] = (
    StepSpec(
        "denoise", tr("冲击去噪"),
        tr("检测超出稳健阈值的短脉冲并三次样条修补；无法修补的超长区间标记为无效点。"),
        (
            Param("threshold", tr("稳健阈值"), "float", 8.0, minimum=0.5, maximum=100.0,
                  decimals=2, step=0.5, tooltip=tr("按稳健标准差倍数判定冲击，越小越敏感")),
            Param("max_repair_ms", tr("最长修复"), "float", 3.0, minimum=0.1, maximum=100.0,
                  decimals=2, step=0.1, suffix=" ms"),
            Param("scope", tr("处理范围"), "choice", "all",
                  (("all", tr("全部声道")), ("first", tr("仅第 1 声道")))),
        ),
    ),
    StepSpec(
        "denoise_tools", tr("降噪工具组"),
        tr("按选定的方法抑制噪声：需要假设的方法会在护栏不满足时拒绝应用并写明原因。"),
        (
            Param("method", tr("方法"), "choice", "ls_frozen",
                  tuple((spec.method_id, spec.label) for spec in METHOD_SPECS)),
            Param("order", tr("滤波器阶数"), "int", 2048, minimum=64, maximum=16384,
                  step=64, tooltip=tr("越大越能拟合长混响，但需要更多噪声采样点（≥ 8× 阶数）")),
            Param("block_seconds", tr("分块长度"), "float", 10.0, minimum=0.5,
                  maximum=120.0, decimals=1, step=0.5, suffix=" s",
                  tooltip=tr("只对「分块自适应」有用：每块的统计量按遗忘因子并入总估计")),
            Param("notch_frequency", tr("陷波中心"), "float", 50.0, minimum=1.0,
                  maximum=20000.0, decimals=2, step=1.0, suffix=" Hz"),
            Param("notch_q", tr("陷波 Q 值"), "float", 30.0, minimum=1.0, maximum=200.0,
                  decimals=1, step=1.0, tooltip=tr("Q 越大陷波越窄；Q=30 时 50 Hz 陷波对 55 Hz 影响约 0.1 dB")),
            Param("harmonics", tr("谐波次数"), "int", 3, minimum=1, maximum=20, step=1),
            Param("segment_start", tr("噪声段起点"), "float", 0.0, minimum=0.0,
                  maximum=1.0e7, decimals=3, step=0.1,
                  suffix=" " + tr("s（起点与终点都留 0 表示自动检测）")),
            Param("segment_end", tr("噪声段终点"), "float", 0.0, minimum=0.0,
                  maximum=1.0e7, decimals=3, step=0.1, suffix=" s"),
        ),
    ),
    StepSpec(
        "trim", tr("裁剪到区间"),
        tr("只保留指定时间区间，其后的步骤都基于裁剪后的数据。"),
        (
            Param("start", tr("起点"), "float", 0.0, minimum=0.0, maximum=1.0e7,
                  decimals=3, step=0.1, suffix=" s"),
            Param("end", tr("终点"), "float", 0.0, minimum=0.0, maximum=1.0e7,
                  decimals=3, step=0.1, suffix=tr(" s（0 表示到文件末尾）")),
        ),
    ),
    StepSpec(
        "envelope", tr("包络拟合"),
        tr("对指定区间求 Hilbert 包络并拟合（auto 会按残差自动选择常数/线性/指数）。"),
        (Param("model", tr("拟合模型"), "choice", "auto",
               (("auto", tr("auto（自动选择）")), ("constant", tr("常数")),
                ("linear", tr("线性")), ("exponential", tr("指数"))),),)
        + _REGION,
        needs=("envelope",),
    ),
    StepSpec(
        "stats", tr("区间统计"),
        tr("计算选区的 RMS、峰值、主频、THD 等；主频与 THD 受已知激励频率约束。"),
        _REGION + _FUNDAMENTAL,
        needs=("stats",),
    ),
    StepSpec(
        "dual", tr("双通道时延与电平"),
        tr("比较两声道的主频幅值与到达时延。单声道文件自动跳过。"),
        _FUNDAMENTAL,
        needs=("dual",),
        stereo_only=True,
    ),
    StepSpec(
        "export_wav", tr("导出处理后 WAV"),
        tr("把当前处理结果另存为新 WAV，源文件不动。"),
        (
            Param("suffix", tr("文件名后缀"), "text", tr("_处理后")),
            Param("subtype", tr("采样格式"), "choice", "PCM_24",
                  (("PCM_16", "PCM_16（16 bit）"), ("PCM_24", "PCM_24（24 bit）"),
                   ("PCM_32", "PCM_32（32 bit）"), ("FLOAT", tr("FLOAT（32 bit 浮点）")))),
        ),
    ),
    StepSpec(
        "export_txt", tr("导出分析 TXT"),
        tr("定宽对齐的纯文本分析报告；可每个文件一份，也可合并成一份汇总。"),
        (
            Param("aggregate", tr("输出方式"), "choice", "file",
                  (("file", tr("每个文件一个 TXT")), ("single", tr("合并为一个 TXT")))),
            Param("merged_name", tr("合并文件名"), "text", tr("批量分析汇总.txt")),
            Param("suffix", tr("文件名后缀"), "text", tr("_分析")),
            Param("sections", tr("导出章节"), "checklist",
                  tuple(key for key, _ in SECTION_ORDER),
                  tuple(SECTION_ORDER),
                  tooltip=tr("合并模式下建议关掉原坐标，否则汇总文件会非常大")),
            Param("coord_mode", tr("坐标取法"), "choice", "per_second",
                  (("per_second", tr("每秒固定点数")), ("step", tr("按步长抽稀")),
                   ("all", tr("全部采样点")))),
            Param("coord_per_second", tr("每秒点数"), "float", 1000.0, minimum=1.0,
                  maximum=1.0e6, decimals=1, step=100.0),
            Param("coord_step", tr("抽稀步长"), "int", 1, minimum=1, maximum=1_000_000),
        ),
    ),
    StepSpec(
        "export_png", tr("导出图像 PNG"),
        tr("按论文或屏幕版式重新渲染图像，不是界面截图。"),
        (
            Param("kinds", tr("图像类型"), "checklist", ("wave",),
                  (("wave", tr("波形图")), ("spectrum", tr("幅值谱")), ("spectrogram", tr("时频图")))),
            Param("layout", tr("版式"), "choice", "paper_single",
                  (("paper_single", tr("论文单栏 3.5×2.45 in（600 dpi）")),
                   ("paper_double", tr("论文双栏 7.0×2.6 in（600 dpi）")),
                   ("screen", tr("屏幕 1600×900")))),
            Param("envelope", tr("波形图叠包络"), "bool", True),
            Param("fit", tr("波形图叠拟合曲线"), "bool", False),
            Param("region", tr("波形图标出选区"), "bool", False),
        ),
    ),
    StepSpec(
        "export_csv", tr("导出统计 CSV"),
        tr("统计量写成 CSV，可直接进 Excel / Origin；默认合并成一张表。"),
        (
            Param("aggregate", tr("输出方式"), "choice", "single",
                  (("single", tr("合并为一个 CSV（每个文件一行）")),
                   ("file", tr("每个文件一个 CSV")))),
            Param("merged_name", tr("合并文件名"), "text", tr("批量统计.csv")),
            Param("suffix", tr("文件名后缀"), "text", tr("_统计")),
        ),
    ),
    StepSpec(
        "export_html", tr("生成 HTML 报告"),
        tr("每个文件一份独立报告，含波形、频谱与统计表。"),
        (Param("suffix", tr("文件名后缀"), "text", tr("_报告")),),
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
        return kind or tr("（未知步骤）")
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
                parts.append((tr("含") if value else tr("不含")) + param.label)
            continue
        if param.kind == "text":
            if str(value) != str(param.default):
                # 合并文件名、文件名后缀都是 text，不能一律写成“后缀 xxx”
                prefix = tr("后缀") if tr("后缀") in param.label else param.label
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
        raise ValueError(tr("统计区间为空：请检查起止时间或去掉的首尾长度"))
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
    # 外部参考的溯源信息（路径/声道/哈希），写进批量结果供汇总与留痕。
    reference: dict[str, Any] | None = None

    @property
    def ok_count(self) -> int:
        return sum(1 for item in self.files if item.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for item in self.files if not item.ok)

    def summary(self) -> str:
        head = tf('共 {_v0} 个文件，成功 {_v1}，失败 {_v2}', _v0=(len(self.files)), _v1=(self.ok_count), _v2=(self.fail_count))
        if self.cancelled:
            head += tr("（已取消）")
        head += tf('，用时 {_v0:.1f} s', _v0=(self.seconds))
        if self.outputs:
            head += tf('，输出 {_v0} 个文件', _v0=(len(self.outputs)))
        failures = [item for item in self.files if not item.ok]
        if failures:
            head += "\n" + "\n".join(
                f"· {item.path.name}：{item.error}" for item in failures[:8])
            if len(failures) > 8:
                head += tf('\n· 其余 {_v0} 个失败略', _v0=(len(failures) - 8))
        return head


# ---------------------------------------------------------------- 单文件状态


_UNSET = object()


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
        # 缓存对应的「有效基频」：None 表示自动估峰。换一个基频就必须重算，
        # 否则 dual(auto) 缓存下来的峰会被后面的 stats(固定频率) 与导出沿用。
        self.fourier_key: object = _UNSET
        self.dual: dict[str, Any] | None = None
        self.rows: dict[str, Any] = {}
        self.notes: list[str] = []
        self.denoise_tools: AncDiagnostics | None = None
        self.anc_row: dict[str, Any] = {}

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
    """按「有效基频」缓存频谱结果。

    只缓存一个对象是不够的：`dual` 用自动估峰（None）先算了一次，
    随后 `stats` 指定了固定频率，导出却仍拿到自动估峰那份（BUG 审查 P0）。
    缓存键必须把基频一起算进去。
    """
    if state.fourier is not None and state.fourier_key == fundamental:
        return state.fourier
    state.fourier = fourier_analysis(
        state.channel_samples(0), state.sample_rate, fundamental_frequency=fundamental)
    state.fourier_key = fundamental
    return state.fourier


def _ensure_stats(state: _State, params: dict[str, Any]) -> dict[str, Any]:
    if state.stats is None:
        start, end = resolve_region(params or {"region": "all"}, state.duration)
        fundamental = resolve_fundamental(params or {}, state.path.name)
        state.stats = interval_statistics(
            state.channel_samples(0), state.sample_rate, start, end,
            state.channel_mask(0), fundamental, calibration=state.calibration)
    return state.stats


def _invalidate_derived(state: _State) -> None:
    """样本或有效掩码一变，所有派生结果立即作废（BUG-009）。

    统计、频谱、双通道、包络、拟合时间轴全都是基于当前样本算出来的；
    只要样本改了还留着旧值，导出里就会出现「去噪后的波形 + 去噪前的统计」
    这种自相矛盾的数据。跳过处理的步骤（例如缺参考声道）不需要调用。
    """
    state.stats = None
    state.fourier = None
    state.fourier_key = _UNSET
    state.dual = None
    state.envelope = None
    state.envelope_times = None
    state.envelope_span = None
    state.fit = None
    state.fit_times = None


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
        _invalidate_derived(state)
        state.edits.append("denoise")
        invalid_ratio = float(1.0 - state.mask.mean())
        if invalid_ratio > 0.5:
            # 阈值过低或数据本身以冲击为主时，去噪会把大半数据标成无效，
            # 后续统计会静默给出毫无意义的数字。这里宁可整份失败。
            raise ValueError(
                tf('去噪把 {_v0:.0f}% 的采样点标为无效，请提高稳健阈值或先确认数据是否异常', _v0=(invalid_ratio * 100)))
        state.notes.append(tf('去噪修复 {total_repaired} 处，标记无效 {total_excluded} 处', total_repaired=(total_repaired), total_excluded=(total_excluded)))
        return

    if kind == "denoise_tools":
        method = str(params.get("method", "ls_frozen"))
        spec = next((item for item in METHOD_SPECS if item.method_id == method), None)
        if spec is None:
            raise ValueError(tf('未知的降噪方法：{_v0}', _v0=(method)))
        target = state.channel_samples(0)
        needs_reference = method in ("ls_frozen", "wiener_clean", "ls_block",
                                     "wiener_spectral", "noise_profile")

        def _skip_step(message: str) -> None:
            # 参考不满足条件不该让整批失败：记备注、跳过这一步，后面的步骤照常跑。
            state.anc_row = {
                "denoise_method": spec.label,
                "denoise_applied": False,
                "denoise_erle_db": None,
                "denoise_holdout_erle_db": None,
                "denoise_delta_level_db": None,
                "denoise_u_c_db": None,
                "denoise_blocked": message,
            }
            state.notes.append(message)

        reference = None
        reference_label = None
        external = ctx.get("reference")
        if external and external.get("path"):
            ref_path = str(external["path"])
            ref_channel = int(external.get("channel") or 0)
            try:
                from .reference import align_reference, load_reference_cached

                # 整批共用同一份参考：按文件身份缓存，避免每个输入都重新解码+哈希
                ref = load_reference_cached(ref_path, sample_rate=sample_rate,
                                            channel=ref_channel)
                if method == "noise_profile":
                    reference = ref.samples.copy()
                    align_info = None
                else:
                    reference, align_info = align_reference(ref.samples, target, sample_rate)
                if align_info and align_info["unprocessed_frames"]:
                    state.notes.append(tf(
                        '外部参考比本文件短：只处理重叠的 {_v0:,} 点，其余保持原样',
                        _v0=(align_info["overlap_frames"])))
                reference_label = tf('外部参考 {_v0} 第 {_v1} 声道',
                                     _v0=(Path(ref_path).name), _v1=(ref_channel + 1))
            except Exception as exc:  # noqa: BLE001 - 校验失败换可读提示，逐文件记备注
                if needs_reference:
                    _skip_step(tf('外部参考不可用（{_v0}），本文件已跳过这一步', _v0=(str(exc))))
                    return
                reference = state.channel_samples(1) if state.channels > 1 else None
        else:
            reference = state.channel_samples(1) if state.channels > 1 else None
        if needs_reference and reference is None:
            _skip_step(tf('降噪工具组“{_v0}”需要第二个声道作参考，本文件只有 1 个声道，已跳过这一步',
                          _v0=(spec.label)))
            return
        start = max(0.0, float(params.get("segment_start", 0.0) or 0.0))
        end = float(params.get("segment_end", 0.0) or 0.0)
        segment = None
        if end > start:
            stop = min(end, state.duration)
            if stop > start:
                segment = (int(round(start * sample_rate)), int(round(stop * sample_rate)))
        fundamental = state.fundamental or resolve_fundamental(params, state.path.name)
        # noise_profile 用整段参考、不切目标；对齐类方法参考短时只处理重叠段
        used = target if (reference is None or method == "noise_profile") \
            else target[: reference.size]
        if segment is not None:
            lo, hi = segment
            hi = min(hi, used.size)
            lo = min(lo, max(0, hi - 1))
            segment = (lo, hi) if hi - lo >= 2 else None
        outcome = run_anc_method(
            method, used, reference, sample_rate, fundamental=fundamental, segment=segment,
            params={
                "order": int(params.get("order", 2048)),
                "block_seconds": float(params.get("block_seconds", 10.0)),
                "frequency": float(params.get("notch_frequency", 50.0)),
                "q": float(params.get("notch_q", 30.0)),
                "harmonics": int(params.get("harmonics", 3)),
            })
        diag = outcome.diagnostics
        state.denoise_tools = diag
        state.anc_row = {
            "denoise_method": METHOD_LABELS.get(method, method),
            "denoise_applied": bool(outcome.applied),
            "denoise_erle_db": diag.erle_db,
            "denoise_holdout_erle_db": diag.erle_holdout_db,
            "denoise_delta_level_db": diag.delta_level_db,
            "denoise_u_c_db": diag.u_c_db,
            "denoise_blocked": diag.blocked or "",
        }
        if reference_label:
            diag.notes.append(tf('参考：{_v0}', _v0=(reference_label)))
            state.notes.append(tf('参考：{_v0}', _v0=(reference_label)))
        state.edits.append(f"denoise_tools:{method}")
        if not outcome.applied:
            state.notes.append(
                tf('降噪工具组“{_v0}”未应用：{_v1}', _v0=(spec.label),
                   _v1=(diag.blocked or tr("未知原因"))))
            return
        cleaned = outcome.cleaned
        if cleaned is not None and cleaned.size < target.size:
            # 外部参考比目标短：只覆盖重叠段，余下采样保持原样。
            state.samples[: cleaned.size, 0] = cleaned
        else:
            state.samples[:, 0] = cleaned
        _invalidate_derived(state)
        state.notes.append(
            tf('降噪工具组“{_v0}”：ERLE {_v1:.1f} dB，合成不确定度 {_v2:.2f} dB',
               _v0=(spec.label), _v1=(diag.erle_db or 0.0), _v2=(diag.u_c_db or 0.0)))
        return

    if kind == "trim":
        duration = state.duration
        requested_start = float(params.get("start", 0.0) or 0.0)
        requested_end = float(params.get("end", 0.0) or 0.0) or duration
        # 批量里各文件长度不同：超出文件长度就钳制并在备注里留痕，
        # 不要因为一个短文件把整批停下来。
        start = max(0.0, min(requested_start, duration))
        end = max(start, min(requested_end, duration))
        if (abs(start - requested_start) > 1e-9 or abs(end - requested_end) > 1e-9):
            state.notes.append(
                tf('裁切区间超出文件长度，已钳制到 {_v0:.3f}–{_v1:.3f} s（文件 {_v2:.3f} s）',
                   _v0=(start), _v1=(end), _v2=(duration)))
        if end - start < 2.0 / sample_rate:
            state.notes.append(
                tf('警告：裁切区间 {_v0:.3f}–{_v1:.3f} s 太短，已跳过这一步', _v0=(start), _v1=(end)))
            return
        trimmed = trim_range(state.samples, state.mask, sample_rate, start, end)
        state.samples = np.array(trimmed.samples, copy=False)
        state.mask = np.array(trimmed.valid_mask, copy=False)
        state.edits.append("trim")
        _invalidate_derived(state)
        state.notes.append(
            tf('裁剪至 {_v0:.3f}–{_v1:.3f} s', _v0=(trimmed.start_seconds), _v1=(trimmed.end_seconds)))
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
            raise ValueError(tr("选区内有效包络点不足"))
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
            tf('主频 {_v0:.3f} Hz，电平 {_v1:.2f} dBFS', _v0=(state.stats['main_frequency_hz']), _v1=(state.stats['main_amplitude_dbfs'])))
        return

    if kind == "dual":
        if state.channels < 2:
            state.notes.append(tr("单声道文件，已跳过双通道分析"))
            return
        from .dual_channel import analyze_dual_channel

        fundamental = resolve_fundamental(params, state.path.name)
        if fundamental is None:
            fundamental = float(_ensure_fourier(state, None).main_frequency)
        # 双通道分析必须用「当前」样本，而不是刚读进来的原始音频：
        # 脚本里排在它前面的裁剪/去噪都要生效（BUG-010）。
        from dataclasses import replace as _dc_replace

        state.dual = analyze_dual_channel(
            _dc_replace(state.audio, samples=state.samples), fundamental)
        return

    if kind == "export_wav":
        target = _output_path(state, params, tr("_处理后"), ".wav", ctx)
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

    raise ValueError(tf('未知步骤类型：{kind}', kind=(kind)))


def _output_dir(ctx: dict[str, Any], state: _State) -> Path:
    root = ctx.get("output_dir")
    return Path(root) if root else state.path.parent


def _unique_target(ctx: dict[str, Any], target: Path) -> Path:
    """同一次批量里保证输出路径唯一。

    不同目录下的同名 WAV 用同一个输出目录时会算出同一个目标路径，
    原来后写的直接覆盖先写的，而结果列表里还挂着两条相同路径，
    用户以为两份都在（BUG-008）。这里给冲突项加 _2、_3 后缀。
    """
    used: set[str] = ctx.setdefault("used_outputs", set())
    key = str(target).lower()
    if key not in used:
        used.add(key)
        return target
    index = 2
    while True:
        candidate = target.with_name(f"{target.stem}_{index}{target.suffix}")
        if str(candidate).lower() not in used:
            used.add(str(candidate).lower())
            return candidate
        index += 1


def _output_path(state: _State, params: dict[str, Any], default_suffix: str,
                 extension: str, ctx: dict[str, Any]) -> Path:
    suffix = str(params.get("suffix", default_suffix) or default_suffix)
    stem = state.path.stem or "audio"
    if state.channels > 1:
        stem = f"{stem}"
    target = _unique_target(ctx, _output_dir(ctx, state) / f"{stem}{suffix}{extension}")
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
        target = _output_path(state, params, tr("_分析"), ".txt", ctx)
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
        data_label=tr("批量处理结果（已编辑）") if state.edits else tr("源文件（未修改）"),
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
    state.notes.append(tf('TXT {_v0:,} 行 → {_v1}', _v0=(result['rows']), _v1=(target.name)))
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
        target = _unique_target(ctx, root / tf('{stem}_波形.png', stem=(stem)))
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
        target = _unique_target(ctx, root / tf('{stem}_幅值谱.png', stem=(stem)))
        render_spectrum_png(target, _ensure_fourier(state, fundamental), options,
                            annotate_peaks=True, mark_harmonics=True)
        _record_output(state, target, ctx)

    if "spectrogram" in kinds:
        target = _unique_target(ctx, root / tf('{stem}_时频图.png', stem=(stem)))
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
    # 降噪标记列：跳过/拒绝时也写进 CSV，而不是留空让人以为是 0。
    row.update(getattr(state, "anc_row", {}) or {})
    return row


def _export_csv(state: _State, params: dict[str, Any], ctx: dict[str, Any]) -> None:
    row = _stats_row(state, params)
    state.rows = row
    if str(params.get("aggregate", "single")) == "single":
        ctx["csv_rows"].append(row)
        return
    target = _output_path(state, params, tr("_统计"), ".csv", ctx)
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
        # 直接传视图：报告只读取样本，复制一份全量 float64 在长录音上要多占几百 MB
        state.channel_samples(0),
        state.envelope, state.fit, state.denoise, "")
    target = _output_path(state, params, tr("_报告"), ".html", ctx)
    save_report(target, content)
    _record_output(state, target, ctx)


# ---------------------------------------------------------------- 主入口


def _merged_banner(total: int, files: Sequence[Path]) -> str:
    lines = [tr("声音实验 WAV 数据处理程序 — 批量分析汇总"), ""]
    lines.append(tf('# 文件数：{total}', total=(total)))
    lines.append(tr("# 数据来源：批量处理（每个文件的完整报告按处理顺序依次附在下方）"))
    lines.append(tr("# 分段方式：每段以「分析数据导出」标题开始，含源文件名、路径与 MD5 指纹"))
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
    reference: dict[str, Any] | None = None,
) -> BatchResult:
    """按步骤脚本逐个处理文件。整个过程只读源文件，导出写到 output_dir。

    ``reference`` 是批量级的外部参考：``{"path": str, "channel": int(0基)}``。
    所有文件共用同一份参考（按文件身份缓存，不会每个文件都重新解码），逐文件校验；
    某个文件不满足条件时只**跳过这一步并记备注**，不让整批失败。
    """
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
        "reference": dict(reference) if reference else None,
    }
    if reference:
        # 记录批量级参考的溯源信息，结果与汇总里都能查到用了哪份文件、哪一路。
        result.reference = {
            "kind": "external",
            "path": str(reference.get("path") or ""),
            "channel": int(reference.get("channel") or 0),
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
        name = merged_txt_name or _merged_name(script, "export_txt", tr("批量分析汇总.txt"))
        target = base / name
        target.write_text(_merged_banner(total, paths), encoding="utf-8-sig")
        ctx["merged_txt"] = target
    if needs_csv_merge:
        base = root or paths[0].parent
        name = merged_csv_name or _merged_name(script, "export_csv", tr("批量统计.csv"))
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
                state.notes.append(tr("警告：源文件可能存在削顶"))
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
    merged_csv_written = False
    if needs_csv_merge and ctx["csv_rows"]:
        if not (should_cancel is not None and should_cancel()):
            emit("merge", total, Path(ctx["merged_csv"]).name, 0.0)
            export_rows_csv(ctx["merged_csv"], ctx["csv_rows"])
            merged_csv_written = True
    if needs_txt_merge:
        target = ctx["merged_txt"]
        if target.exists():
            with target.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(tr("\n# 批量处理结束：") + time.strftime("%Y-%m-%d %H:%M:%S") + "\n")

    result.outputs = list(ctx["outputs"]) + sorted(str(item) for item in ctx["merged_outputs"])
    # 只有在真的写盘成功后才把合并 CSV 记为输出，否则取消后会把不存在的文件
    # 列进结果里（BUG-011）。
    if merged_csv_written:
        result.outputs.append(str(ctx["merged_csv"]))
    result.seconds = time.perf_counter() - started
    emit("done", total, "", 1.0)
    return result
