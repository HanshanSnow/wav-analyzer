from __future__ import annotations

from core.i18n import tf, tr
from typing import TYPE_CHECKING, Any, Callable

import numpy as np

from .envelope import compute_envelope
from .spectral import fourier_analysis

if TYPE_CHECKING:
    from .calibration import Calibration

# 统计量按块累加：千万点级文件上若整段做 abs()/平方 会瞬时占用数百 MB，
# 分块后峰值只与块大小有关，数值仍是同一套公式（求和、平方和、极值）。
CHUNK_SAMPLES = 1 << 22


def _chunked_segments(total: int, chunk: int = CHUNK_SAMPLES):
    for start in range(0, total, chunk):
        yield start, min(total, start + chunk)


def _abs_max(x: np.ndarray) -> float:
    peak = 0.0
    for start, stop in _chunked_segments(x.size):
        peak = max(peak, float(np.max(np.abs(x[start:stop]))))
    return peak


def _sum_squares(x: np.ndarray) -> float:
    total = 0.0
    for start, stop in _chunked_segments(x.size):
        block = x[start:stop]
        total += float(np.dot(block, block))
    return total


def _variance(x: np.ndarray, mean: float) -> float:
    total = 0.0
    for start, stop in _chunked_segments(x.size):
        deviation = x[start:stop] - mean
        total += float(np.dot(deviation, deviation))
    return total / x.size


def _all_finite(x: np.ndarray) -> bool:
    for start, stop in _chunked_segments(x.size):
        if not np.isfinite(x[start:stop]).all():
            return False
    return True


# 「计算口径」这段是拼出来的：界面用 tr/tf 渲染，报告要用 rt/rtf 重新渲染。
# 因此同时保留中文原文（模板 + 参数），不把已渲染的字符串当成唯一来源。
_SCOPE_ENERGY = "RMS/峰值/标准差基于选区全部有效采样点"
_SCOPE_WINDOW = "主频/THD 基于居中窗口 {_v0:,}/{_v1:,} 点（{_v2:.3f}–{_v3:.3f} s）"
_SCOPE_ALL = "主频/THD 基于选区全部有效采样点"

# ---------------------------------------------------------------- 统计量释义# 键名与 interval_statistics 的返回值一一对应。界面、报告与手册共用这一份释义，
# 避免只有英文变量名时产生歧义（例如 peak_amplitude 与 peak_to_peak、rms 与 rms_dbfs）。
# 这里存**中文原文**，翻译在使用处做：界面用 `tr()`，报告用 `rt()`。
# 若在定义时就把 tr() 结果写死，报告语言与界面语言就绑在一起了。
STATISTIC_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("start_s", "有效起点 (s)",
     "参与统计的第一个采样点时间；若起点被排除段覆盖，会自动向右收缩"),
    ("end_s", "有效终点 (s)",
     "参与统计的最后一个采样点时间（右端按开区间理解）"),
    ("requested_start_s", "请求起点 (s)",
     "蓝框选区原始起点，用于核对掩码把边界修正了多少"),
    ("requested_end_s", "请求终点 (s)",
     "蓝框选区原始终点"),
    ("samples", "有效采样点数",
     "真正参与计算的采样点数（已扣除被排除的长冲击段）"),
    ("excluded_samples", "排除点数",
     "被判为长冲击、未做插值修复的点数；这些点不计入任何幅值/能量统计"),
    ("duration_s", "有效时长 (s)",
     "有效采样点数 ÷ 采样率，通常略小于蓝框宽度"),
    ("mean", "均值 / 直流分量 (FS)",
     "整段有效数据的算术平均；明显不为 0 说明存在直流偏置，报告需注明"),
    ("std", "标准差 (FS)",
     "去均值后的起伏幅度，只反映交流成分，与直流偏置无关"),
    ("min", "最小瞬时值 (FS)",
     "单个采样点的最小值（有符号，负半周最深处）"),
    ("max", "最大瞬时值 (FS)",
     "单个采样点的最大值（有符号，正半周最高处）"),
    ("peak_amplitude", "峰值振幅 max|x| (FS)",
     "正负两侧绝对值的较大者，恒为正值；不是峰峰值"),
    ("peak_to_peak", "峰峰值 max−min (FS)",
     "max 减 min，等于波形总摆幅，约为峰值振幅的 2 倍（对称波形）"),
    ("rms", "有效值 RMS (FS)",
     "√(mean(x²))，包含直流分量；整周期正弦时 RMS = 峰值 ÷ √2 ≈ 0.707×峰值"),
    ("rms_dbfs", "RMS 电平 (dBFS)",
     "20·lg(RMS/FS)，满幅正弦约 −3.01 dBFS；dBFS 是数字满幅相对值，不等于 dB SPL"),
    ("rms_spl", "等效声压级 (dB SPL)",
     "RMS 电平 + 校准偏移 K；等效于该区间的能量平均声压级，仅在配置声学校准后出现"),
    ("peak_spl", "峰值声压级 (dB SPL)",
     "20·lg(峰值振幅) + K，未计频率计权，仅在配置声学校准后出现"),
    ("calibration_offset_db", "校准偏移 K (dB)",
     "dB SPL = dBFS + K；由灵敏度、前置增益与满幅电压推算，或由已知声压级标定得到"),
    ("calibration_name", "校准配置",
     "本次换算使用的校准名称；空表示未校准，此时不输出任何 dB SPL"),
    ("crest_factor", "波峰因数 (峰值/RMS)",
     "峰值振幅 ÷ RMS；正弦约 1.414，脉冲/冲击性越强该值越大"),
    ("main_frequency_hz", "主频 (Hz)",
     "幅值最大谱峰对应的频率；长文件按居中窗口估计，实际窗口见“计算口径”"),
    ("main_amplitude", "主频振幅 (FS)",
     "单边幅值谱在主频处的幅值；整周期正弦时约等于峰值振幅"),
    ("main_amplitude_dbfs", "主频电平 (dBFS)",
     "20·lg(主频振幅)，用于和本底噪声比较，不是声压级"),
    ("thd", "总谐波失真 THD",
     "2～10 次谐波（到奈奎斯特频率为止）幅值的均方根 ÷ 基波幅值；纯正弦接近 0"),
    ("analysis_scope", "计算口径说明",
     "声明哪些量基于选区全部采样点、哪些量基于受限 FFT 窗口"),
)

STATISTIC_LABELS_ZH: dict[str, str] = {key: label for key, label, _ in STATISTIC_FIELDS}
STATISTIC_NOTES_ZH: dict[str, str] = {key: note for key, _, note in STATISTIC_FIELDS}
STATISTIC_LABELS: dict[str, str] = {key: tr(label) for key, label, _ in STATISTIC_FIELDS}
STATISTIC_NOTES: dict[str, str] = {key: tr(note) for key, _, note in STATISTIC_FIELDS}


def statistics_rows(
    stats: dict[str, Any],
    translate: "Callable[[str], str] | None" = None,
) -> list[tuple[str, str, Any, str]]:
    """把统计字典转成 (键名, 名称, 数值, 释义) 行；未登记的键回退为原键名。

    translate 默认为界面的 `tr`；导出报告时传 `core.report_i18n.rt`，
    普通字表里那份 61 条释义不必维护第二份译文。
    以 `_` 开头的键是内部标记（例如 `_scope`），不参与表格输出。
    """
    render = translate or tr
    rows: list[tuple[str, str, Any, str]] = []
    for key, value in stats.items():
        if key.startswith("_"):
            continue
        rows.append((
            key,
            render(STATISTIC_LABELS_ZH.get(key, key)),
            value,
            render(STATISTIC_NOTES_ZH.get(key, "")),
        ))
    return rows




def _bounds(length: int, sample_rate: int, start_s: float, end_s: float) -> tuple[int, int]:
    if sample_rate <= 0:
        raise ValueError(tr("采样率必须为正数"))
    start = max(0, int(np.floor(start_s * sample_rate)))
    end = min(length, int(np.ceil(end_s * sample_rate)))
    if start_s < 0 or end_s <= start_s or start >= end:
        raise ValueError(tr("统计区间无效：需要 0 ≤ start < end，且区间内必须有采样点"))
    return start, end


def interval_statistics(
    samples: np.ndarray,
    sample_rate: int,
    start_s: float = 0.0,
    end_s: float | None = None,
    valid_mask: np.ndarray | None = None,
    fundamental_frequency: float | None = None,
    calibration: "Calibration | None" = None,
) -> dict[str, Any]:
    x = np.asarray(samples, dtype=np.float64).reshape(-1)
    if len(x) == 0:
        raise ValueError(tr("没有可统计的音频数据"))
    end_s = len(x) / sample_rate if end_s is None else end_s
    start, end = _bounds(len(x), sample_rate, start_s, end_s)
    segment = x[start:end]
    if valid_mask is not None:
        mask = np.asarray(valid_mask, dtype=bool).reshape(-1)
        if len(mask) != len(x):
            raise ValueError(tr("有效区间掩码长度与音频不一致"))
        local_mask = mask[start:end]
        if local_mask.all():
            # 常见情形：整选区都有效。直接复用视图，省掉一份全量副本。
            selected = segment
            first_valid, last_valid = 0, max(0, len(segment) - 1)
        else:
            selected = segment[local_mask]
            if len(selected) >= 2:
                valid_rel = np.flatnonzero(local_mask)
                first_valid, last_valid = int(valid_rel[0]), int(valid_rel[-1])
            else:
                first_valid, last_valid = 0, 0
    else:
        selected = segment
        first_valid, last_valid = 0, max(0, len(segment) - 1)
    if len(selected) < 2:
        raise ValueError(tr("区间内有效采样点不足"))
    if not _all_finite(selected):
        raise ValueError(tr("统计区间包含 NaN 或无穷值"))
    count = int(selected.size)
    mean = float(np.sum(selected) / count)
    sum_squares = _sum_squares(selected)
    peak = _abs_max(selected)
    rms = float(np.sqrt(sum_squares / count))
    std = float(np.sqrt(max(0.0, _variance(selected, mean))))
    # 主频/THD 用带上限的 FFT，避免长选区触发全量 FFT 卡死界面。
    # RMS 等能量统计量仍基于完整选区，因此数值精度不受影响。
    fourier = fourier_analysis(selected, sample_rate, fundamental_frequency=fundamental_frequency)
    energy_note = tr("RMS/峰值/标准差基于选区全部有效采样点")
    if fourier.analyzed_samples < fourier.total_samples:
        # analysis_offset 的单位是**秒**（相对选区数组起点），不是采样点；
        # 报告里要的是文件内的绝对时间，所以加上选区起点的秒数（BUG-017）。
        window_start_s = (start + first_valid) / sample_rate + float(fourier.analysis_offset)
        window_end_s = window_start_s + fourier.analyzed_samples / sample_rate
        freq_note = (
            tf('主频/THD 基于居中窗口 {_v0:,}/{_v1:,} 点（{_v2:.3f}–{_v3:.3f} s）', _v0=(fourier.analyzed_samples), _v1=(fourier.total_samples), _v2=(window_start_s), _v3=(window_end_s))
        )
        scope_freq: Any = (_SCOPE_WINDOW, {
            "_v0": fourier.analyzed_samples,
            "_v1": fourier.total_samples,
            "_v2": window_start_s,
            "_v3": window_end_s,
        })
    else:
        freq_note = tr("主频/THD 基于选区全部有效采样点")
        scope_freq = _SCOPE_ALL
    # 校准偏移 K：未配置或参数不全时为 None，此时不输出任何 dB SPL 字段。
    # 宁可少给一列，也不要给一个看起来合理、实则没有标定依据的声压级。
    result: dict[str, Any] = {
        "start_s": float((start + first_valid) / sample_rate),
        "end_s": float((start + last_valid + 1) / sample_rate),
        "requested_start_s": float(start_s),
        "requested_end_s": float(end_s),
        "samples": int(len(selected)),
        "excluded_samples": int(end - start - len(selected)),
        "duration_s": float(len(selected) / sample_rate),
        "mean": mean,
        "std": std,
        "min": float(np.min(selected)),
        "max": float(np.max(selected)),
        "peak_amplitude": peak,
        "peak_to_peak": float(np.ptp(selected)),
        "rms": rms,
        "rms_dbfs": float(20 * np.log10(max(rms, 1e-15))),
        "crest_factor": float(peak / max(rms, 1e-15)),
        "main_frequency_hz": fourier.main_frequency,
        "main_amplitude": fourier.main_amplitude,
        "main_amplitude_dbfs": float(20 * np.log10(max(fourier.main_amplitude, 1e-15))),
        "thd": fourier.thd,
        "analysis_scope": f"{energy_note}；{freq_note}",
    }
    # 「计算口径」的原文与参数挂在属性上而不是键上：表格、CSV、报告的行集合
    # 应当只含真正的统计量，多一个键会让列名集合随语言实现细节漂移。
    result = StatisticValues(result)
    result.scope_parts = {"energy": _SCOPE_ENERGY, "freq": scope_freq}
    return attach_calibration(result, calibration)


# SPL 字段键，attach_calibration 负责成对增删
_SPL_KEYS = ("rms_spl", "peak_spl", "calibration_offset_db", "calibration_name")


class StatisticValues(dict):
    """统计结果字典。

    `scope_parts` 存「计算口径」的中文原文与参数，供报告按另一种语言重渲染；
    它是属性不是键，免得统计表、CSV 表头里多出一列内部字段。
    """

    scope_parts: dict[str, Any] | None = None


def attach_calibration(
    stats: dict[str, Any],
    calibration: "Calibration | None" = None,
) -> dict[str, Any]:
    """在统计结果上重算 dB SPL 字段。

    单独抽出来是因为切换校准配置时不该重跑 FFT——统计量没变，变的只是偏移量。
    返回新字典并保持原有键序：rms_spl 紧跟 rms_dbfs、peak_spl 紧跟 peak_amplitude，
    这样表格、TXT、CSV 的列顺序在任何时候都一致。
    """
    offset = calibration.offset_db() if (calibration is not None and calibration.ready) else None

    def spl_of(fs_value: float) -> float:
        return float(offset + 20 * np.log10(max(float(fs_value), 1e-15)))

    out: dict[str, Any] = StatisticValues()
    for key, value in stats.items():
        if key in _SPL_KEYS:
            continue
        out[key] = value
        if offset is None:
            continue
        if key == "peak_amplitude":
            out["peak_spl"] = spl_of(value)
        elif key == "rms_dbfs":
            out["rms_spl"] = spl_of(stats.get("rms", 0.0))
    if offset is not None:
        # 追在末尾：这两个是换算依据，读者通常先看数、再回头核对怎么来的。
        out["calibration_offset_db"] = float(offset)
        out["calibration_name"] = str(calibration.name)
    if isinstance(out, StatisticValues):
        out.scope_parts = getattr(stats, "scope_parts", None)
    return out


def probe_time(
    samples: np.ndarray,
    sample_rate: int,
    time_s: float,
    local_window_ms: float = 20.0,
) -> dict[str, float]:
    x = np.asarray(samples, dtype=np.float64).reshape(-1)
    if not 0 <= time_s < len(x) / sample_rate:
        raise ValueError(tr("读数时间超出音频范围"))
    center = int(round(time_s * sample_rate))
    instant = float(x[min(center, len(x) - 1)])
    half = max(1, round(local_window_ms * sample_rate / 2000))
    start, end = max(0, center - half), min(len(x), center + half + 1)
    local = x[start:end]
    # Hilbert 变换在窗口边缘有系统误差。用更大的对称窗口求包络，
    # 只取中心点读数，把边缘效应隔离在读数区间之外。
    env_half = max(half * 6, round(120 * sample_rate / 1000))
    env_start, env_end = max(0, center - env_half), min(len(x), center + env_half + 1)
    env_window = x[env_start:env_end]
    _, env_values = compute_envelope(env_window, sample_rate)
    env_center = min(center - env_start, len(env_values) - 1)
    envelope_value = float(env_values[env_center])
    # 仅对局部窗口做 FFT，避免长音频上延迟导入的大数组开销。
    local_freq = float(fourier_analysis(local, sample_rate, n_fft=max(4096, len(local)), max_samples=0).main_frequency)
    return {
        "time_s": float(time_s),
        "instantaneous": instant,
        "local_peak": float(np.max(np.abs(local))),
        "local_rms": float(np.sqrt(np.mean(local ** 2))),
        "envelope": envelope_value,
        "local_main_frequency_hz": local_freq,
    }
