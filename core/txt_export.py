"""分析数据 TXT 导出。

排版规则（踩过坑，别再改回去）：
  * 制表符靠不住——Tab 只能跳到 8 的整数倍，长字段一跨过制表位，后面整列全歪；
  * 「中文 = 2 个等宽字符」也靠不住——Consolas + 中文回退实测 1.875 格，
    SimSun 1.818 格。按 2 格补空格，每多一个汉字就少补 0.125 格，中文列之后整列左漂。

所以这里用**定宽空格对齐，且非末列只允许 ASCII**：ASCII 在等宽字体里恒定占 1 格，
列起点与字体、字号、编辑器无关；中文只出现在最后一列（右侧无列）或 # 注释行里。
`_table` 遇到非末列的中文直接抛错，避免以后改坏。

报告语言独立于界面语言（`core/report_i18n.py`）：所有中文文案都过 `rt()` / `rtf()`，
英文报告里不留中文，连列名注释一起换，免得导出给合作者时半中半英。

大文件保护：坐标长表按块生成、逐块写盘，不在内存里拼整份字符串
（4000 万点全量导出约 3.5 GB）。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np

from .envelope import EnvelopeFit
from .report_i18n import (
    analysis_scope_text,
    report_is_english,
    rt,
    rtf,
    suggest_report_suffix,
)
from .spectral import FourierResult
from .statistics import interval_statistics, statistics_rows

COL_GAP = 3
RULE_WIDTH = 92
# 坐标表每批生成多少行再写盘，兼顾内存与写盘次数。
COORD_BATCH = 8192
# 全量坐标导出的行数阈值：超过时调用方应提示用户（不是硬限制）。
HUGE_COORD_ROWS = 5_000_000

Section = str
ProgressHook = Callable[[float, str], None]

SECTION_ORDER: tuple[tuple[str, str], ...] = (
    ("envelope", "包络方程及参数"),
    ("fourier", "傅里叶分析"),
    ("stats", "区间统计"),
    ("dual", "双通道分析"),
    ("ai", "AI 说明"),
    ("denoise", "去噪记录"),
    ("coords", "原坐标（波形采样数据，长表）"),
)
SECTION_LABELS: dict[str, str] = dict(SECTION_ORDER)

COORD_MODES = (
    ("per_second", "每秒固定点数"),
    ("step", "按步长抽稀"),
    ("all", "全部采样点"),
)
STAT_SCOPES = (("full", "全文件"), ("region", "蓝框选区"), ("custom", "自定义区间"))


@dataclass
class TxtExportOptions:
    """导出内容选项。默认全选，与「一键导出完整分析」的直觉一致。"""

    sections: tuple[str, ...] = tuple(key for key, _ in SECTION_ORDER)
    coord_mode: str = "per_second"
    coord_step: int = 1
    coord_per_second: float = 1000.0
    peak_count: int = 8
    stat_scopes: tuple[str, ...] = ("full",)
    region: tuple[float, float] | None = None
    custom: tuple[float, float] | None = None
    ai_text: str = ""

    def coord_stride(self, sample_rate: int) -> int:
        """把取法换算成抽稀步长（采样点数）。"""
        if self.coord_mode == "all":
            return 1
        if self.coord_mode == "step":
            return max(1, int(self.coord_step))
        rate = max(1e-6, float(self.coord_per_second))
        return max(1, int(round(sample_rate / rate)))

    def coord_rows(self, total: int, sample_rate: int) -> int:
        stride = self.coord_stride(sample_rate)
        return int((total + stride - 1) // stride)


# ---------------------------------------------------------------- 排版工具


def has_wide(text: str) -> bool:
    """含全角或东亚歧义宽字符即为 True（任何等宽字体都不保证占 2 格）。"""
    return any(unicodedata.east_asian_width(ch) in ("W", "F", "A") for ch in text)


def _pad(text: str, width: int, align: str) -> str:
    gap = width - len(text)
    if gap <= 0:
        return text
    return (" " * gap + text) if align == ">" else (text + " " * gap)


def _table(
    rows: Sequence[Sequence[Any]],
    aligns: str | None = None,
    widths: Sequence[int] | None = None,
) -> list[str]:
    """定宽 ASCII 列排版；非末列出现宽字符直接报错。

    widths 用于分批生成的表：各批必须用同一份列宽，否则批与批之间会错开。
    """
    cells = [[str(c) for c in row] for row in rows]
    if not cells:
        return []
    ncols = max(len(r) for r in cells)
    for r in cells:
        r.extend([""] * (ncols - len(r)))
    if aligns is None:
        aligns = "<" * ncols
    aligns = (aligns + "<" * ncols)[:ncols]
    for i in range(ncols - 1):
        for r in cells:
            if has_wide(r[i]):
                raise ValueError(rtf(
                    "第 {_v0} 列（非末列）含中文，无法跨字体对齐：{_v1}",
                    _v0=(i + 1), _v1=(repr(r[i])),
                ))
    if widths is None:
        widths = [max(len(r[i]) for r in cells) for i in range(ncols)]
    else:
        widths = list(widths) + [0] * max(0, ncols - len(widths))
    lines = []
    for r in cells:
        parts = []
        for i in range(ncols - 1):
            parts.append(_pad(r[i], widths[i], aligns[i]) + " " * COL_GAP)
        parts.append(r[-1])
        lines.append("".join(parts).rstrip())
    return lines


def _note(pairs: Iterable[tuple[str, str]]) -> list[str]:
    """注释行键值：整行以 # 开头，不参与列对齐，天然免疫字体宽度。"""
    out: list[str] = []
    for key, value in pairs:
        name = rt(key)
        if value:
            out.append(rtf("# {_v0}：{_v1}", _v0=(name), _v1=(value)))
        else:
            out.append(f"# {name}")
    return out


def _comment(text: str) -> str:
    """整行注释：# 前缀不参与翻译，只翻正文。"""
    return "# " + rt(text)


def _commentf(template: str, **kwargs: Any) -> str:
    """带占位的整行注释。"""
    return "# " + rtf(template, **kwargs)


def _num(value: Any, digits: int = 6) -> str:
    if isinstance(value, (bool, np.bool_)):
        return "1" if value else "0"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not np.isfinite(number):
            return "-inf" if number < 0 else "nan"
        return f"{number:.{digits}g}"
    return str(value)


def _rule(title: str) -> str:
    return f"\n{'=' * RULE_WIDTH}\n{title}\n{'=' * RULE_WIDTH}"


# ---------------------------------------------------------------- 各数据段


def _section_envelope(
    envelope: np.ndarray | None,
    envelope_times: np.ndarray | None,
    span: tuple[float, float] | None,
    fit: EnvelopeFit | None,
    sample_rate: int,
) -> list[str]:
    if envelope is None or fit is None:
        return _note([("状态", rt("未计算")),
                      ("说明", rt("先在“包络分析”页对选区做一次拟合，再导出本段"))])
    times = np.asarray(envelope_times if envelope_times is not None else
                       np.arange(len(envelope)) / float(sample_rate), dtype=np.float64)
    env = np.asarray(envelope, dtype=np.float64).reshape(-1)
    start = float(span[0]) if span else float(times[0])
    end = float(span[1]) if span else float(times[-1] + 1.0 / sample_rate)
    r2 = rtf("{_v0:.6f}", _v0=(fit.r_squared))
    out = _note([
        ("选区", rtf("{_v0:.6f} – {_v1:.6f} s，长 {_v2:.6f} s",
                   _v0=(start), _v1=(end), _v2=(end - start))),
        ("提取方法", rt("Hilbert 解析信号模值（单边包络）")),
        ("拟合模型", fit.model),
        ("拟合方程", rtf("y = {_v0}", _v0=(fit.equation))),
        ("自变域", rtf("{_v0:.6f} – {_v1:.6f} s（相对选区起点）",
                    _v0=(fit.start_time), _v1=(fit.end_time))),
        ("R^2", r2),
        ("RMSE", rtf("{_v0} FS", _v0=(_num(fit.rmse)))),
        ("参数表列定义", rt("idx 序号  sym 符号  value 数值  unit 单位")),
    ])
    units = {"a": "FS", "b": "FS/s", "c": "FS"}
    if fit.model == "exponential":
        units["b"] = "1/s"
    rows: list[list[Any]] = [["idx", "sym", "value", "unit"]]
    for index, (name, value) in enumerate(fit.parameters.items(), 1):
        rows.append([index, name, _num(value), units.get(name, "FS")])
    out += _table(rows, aligns="<><<")

    out += ["", _comment("包络抽样（约 24 行，便于作图核对）"),
            _comment("列定义：t/s 绝对时间  env/FS 包络  fit/FS 拟合值  resid/FS 残差")]
    rows = [["t/s", "env/FS", "fit/FS", "resid/FS"]]
    fitted = np.asarray(fit.fitted, dtype=np.float64)
    size = min(times.size, env.size, fitted.size)
    stride = max(1, size // 24)
    for i in range(0, size, stride):
        rows.append([
            f"{times[i]:.6f}", f"{env[i]:.6f}", f"{fitted[i]:.6f}",
            f"{env[i] - fitted[i]:+.6f}",
        ])
    out += _table(rows, aligns="<>>>")
    return out


def _section_fourier(fourier: FourierResult | None, peak_count: int = 8) -> list[str]:
    if fourier is None:
        return _note([("状态", rt("未计算")), ("说明", rt("频谱分析结果尚未就绪"))])
    n_fft = int(fourier.n_fft) or 1
    df = fourier.sample_rate / n_fft
    start = float(fourier.analysis_offset)
    end = start + fourier.analyzed_samples / fourier.sample_rate
    out = _note([
        ("分析数据段", rtf("{_v0:.6f} – {_v1:.6f} s，长 {_v2:.6f} s",
                      _v0=(start), _v1=(end), _v2=(end - start))),
        ("实际参与点数", rtf("{_v0:,}（总点数 {_v1:,}）",
                       _v0=(fourier.analyzed_samples), _v1=(fourier.total_samples))),
        ("窗函数", rt(fourier.window)),
        ("FFT 点数", f"{n_fft:,}"),
        ("频率分辨率", rtf("{_v0:.6f} Hz", _v0=(df))),
        ("主频", rtf("{_v0:.4f} Hz", _v0=(fourier.main_frequency))),
        ("主频幅值", rtf("{_v0:.6f} FS", _v0=(fourier.main_amplitude))),
        ("主频电平", rtf("{_v0:.4f} dBFS",
                     _v0=(20 * np.log10(max(fourier.main_amplitude, 1e-12))))),
        ("基频", rtf("{_v0:.4f} Hz", _v0=(fourier.fundamental_frequency))),
        ("总谐波失真", rtf("{_v0:.4f} %", _v0=(fourier.thd * 100))),
    ])

    base = max(float(fourier.main_amplitude), 1e-12)
    out += ["", _comment("主要谱峰（按幅值降序）"),
            _comment("列定义：idx 序号  f/Hz 频率  A/FS 幅值  L/dBFS 电平  phi/rad 相位  rel/dB 相对基波电平")]
    rows: list[list[Any]] = [["idx", "f/Hz", "A/FS", "L/dBFS", "phi/rad", "rel/dB"]]
    for index, peak in enumerate(fourier.peaks(count=max(1, int(peak_count))), 1):
        rel = 20 * np.log10(max(peak["amplitude"], 1e-12) / base)
        rows.append([index, f"{peak['frequency_hz']:.4f}", f"{peak['amplitude']:.6f}",
                     f"{peak['amplitude_dbfs']:.4f}", f"{peak['phase_rad']:+.4f}", f"{rel:+.2f}"])
    out += _table(rows, aligns="<>>>>>")

    out += ["", _comment("谐波成分（基频整数倍）"),
            _comment("列定义：n 次数  ft/Hz 理论频率  fm/Hz 实测频率  A/FS 幅值  L/dBFS 电平  rel/dB 相对基波")]
    rows = [["n", "ft/Hz", "fm/Hz", "A/FS", "L/dBFS", "rel/dB"]]
    for harmonic in fourier.harmonics(max_harmonic=8):
        rel = 20 * np.log10(max(harmonic["amplitude"], 1e-12) / base)
        rows.append([harmonic["order"],
                     f"{fourier.fundamental_frequency * harmonic['order']:.4f}",
                     f"{harmonic['frequency_hz']:.4f}", f"{harmonic['amplitude']:.6f}",
                     f"{harmonic['amplitude_dbfs']:.4f}", f"{rel:+.2f}"])
    out += _table(rows, aligns="<>>>>>")

    stride = max(1, fourier.frequencies.size // 40)
    out += ["", _commentf("完整谱表（0 – 奈奎斯特，频率升序），每 {_v0} 个频点取 1 行，完整导出含 {_v1} 行",
                          _v0=(stride), _v1=(f"{fourier.frequencies.size:,}")),
            _comment("列定义：f/Hz 频率  A/FS 幅值  L/dBFS 电平  phi/rad 相位")]
    rows = [["f/Hz", "A/FS", "L/dBFS", "phi/rad"]]
    for i in range(0, fourier.frequencies.size, stride):
        rows.append([f"{fourier.frequencies[i]:.4f}", f"{fourier.amplitude[i]:.8f}",
                     f"{fourier.amplitude_dbfs[i]:.4f}", f"{fourier.phase[i]:+.4f}"])
    out += _table(rows, aligns="<>>>")
    return out


def _stats_block(stats: dict[str, Any], title: str, scope: str) -> list[str]:
    """窄数值表 + 释义块。value 若非纯 ASCII（如 analysis_scope）改放注释行。"""
    rows: list[list[Any]] = [["idx", "key", "value", "name"]]
    notes: list[str] = []
    extra: list[tuple[str, str]] = []
    for index, (key, label, value, note_text) in enumerate(
        statistics_rows(stats, translate=rt), 1
    ):
        if key == "analysis_scope":
            value = analysis_scope_text(stats)
        text = _num(value)
        if has_wide(text):
            extra.append((key, text))
            text = "-"
        rows.append([index, key, text, label])
        notes.append(rtf("{_v0}：{_v1}", _v0=(key), _v1=(note_text)))
    out = [title, ""]
    out += _note([("统计范围", scope)])
    out += ["", _comment("列定义：idx 序号  key 键名  value 数值  name 统计量名")]
    out += _table(rows, aligns="<<><")
    if extra:
        out.append("")
        out += _note(extra)
    out += ["", rt("统计量释义")]
    out += [f"# {line}" for line in notes]
    return out


def _section_stats(
    samples: np.ndarray,
    sample_rate: int,
    valid_mask: np.ndarray | None,
    options: TxtExportOptions,
    fundamental: float | None,
    position: int = 3,
    calibration: Any | None = None,
) -> list[str]:
    duration = samples.size / sample_rate
    scopes = [s for s in options.stat_scopes if s in ("full", "region", "custom")]
    if not scopes:
        scopes = ["full"]
    blocks: list[list[str]] = []
    for index, scope in enumerate(scopes, 1):
        if scope == "region" and (not options.region or options.region[1] <= options.region[0]):
            blocks.append(_note([("状态", rt("跳过")), ("原因", rt("当前没有有效的蓝色选区"))]))
            continue
        if scope == "custom" and (not options.custom or options.custom[1] <= options.custom[0]):
            blocks.append(_note([("状态", rt("跳过")), ("原因", rt("未指定有效的自定义区间"))]))
            continue
        start, end = 0.0, duration
        if scope == "region" and options.region:
            start, end = float(options.region[0]), float(options.region[1])
        if scope == "custom" and options.custom:
            start, end = float(options.custom[0]), float(options.custom[1])
        end = min(end, duration)
        if end <= start:
            blocks.append(_note([("状态", rt("跳过")), ("原因", rt("区间超出音频范围"))]))
            continue
        stats = interval_statistics(samples, sample_rate, start, end,
                                    valid_mask=valid_mask, fundamental_frequency=fundamental,
                                    calibration=calibration)
        label = rt(dict(STAT_SCOPES)[scope])
        title = rtf("[{_v0}.{_v1}] {_v2}统计", _v0=(position), _v1=(index), _v2=(label))
        blocks.append(_stats_block(stats, title,
                                   rtf("{_v0:.6f} – {_v1:.6f} s", _v0=(start), _v1=(end))))
    out: list[str] = [_comment("实际导出按勾选范围输出，未勾选的范围不写入本文件")]
    for block in blocks:
        out.append("")
        out += block
    return out


def _section_dual(dual: dict[str, Any] | None, channels: int) -> list[str]:
    if channels != 2:
        return _note([
            ("状态", rt("不可用")),
            ("原因", rt("当前 WAV 为单声道，双通道分析需要左（参考）/右（接收）两路信号")),
            ("双声道可用内容", rt("互相关时延、峰值质量、搜索窗口、两路电平与电平差、AGC 风险提示")),
        ])
    if not dual:
        return _note([("状态", rt("未执行")),
                      ("说明", rt("点了“双通道时延与电平分析”之后再导出，本段才有数值"))])
    return _note([
        ("激励频率", rtf("{_v0:.4f} Hz", _v0=(dual.get('fundamental_frequency_hz', 0)))),
        ("互相关时延", rtf("{_v0:.3f} us", _v0=(dual.get('delay_us', 0)))),
        ("峰值质量", f"{dual.get('peak_quality', 0):.4f}"),
        ("搜索窗口", rtf("{_v0:.3f} us", _v0=(dual.get('search_window_us', 0)))),
        ("参考声道电平", rtf("{_v0:.4f} dBFS", _v0=(dual.get('reference_dbfs', 0)))),
        ("接收声道电平", rtf("{_v0:.4f} dBFS", _v0=(dual.get('received_dbfs', 0)))),
        ("电平差", rtf("{_v0:.4f} dB", _v0=(dual.get('level_difference_db', 0)))),
        ("警告", str(dual.get("warning", "") or rt("无"))),
        ("说明", str(dual.get("note", ""))),
    ])


def _section_denoise(denoise: Any | None, sample_rate: int, cleaned_size: int) -> list[str]:
    if denoise is None:
        return _note([("状态", rt("无记录")),
                      ("说明", rt("尚未应用冲击去噪；本段只在修改后数据上出现"))])
    events = list(denoise.events)
    out = _note([
        ("检测参数", rtf("稳健阈值 {_v0:g} × 尺度；估算尺度用 {_v1:,} 点",
                    _v0=(denoise.threshold),
                    _v1=(getattr(denoise, 'scale_samples', 0)))),
        ("检测事件", rtf("{_v0} 段", _v0=(len(events)))),
        ("插值修复", rtf("{_v0} 段", _v0=(denoise.repaired_count))),
        ("标记排除", rtf("{_v0} 段", _v0=(len(events) - denoise.repaired_count))),
        ("修复后总点数", f"{cleaned_size:,}"),
        ("列定义", rt("idx 序号  t1/s 起点  t2/s 终点  len/ms 长度  dev/FS 峰值偏差  action 处理方式")),
    ])
    rows: list[list[Any]] = [["idx", "t1/s", "t2/s", "len/ms", "dev/FS", "action"]]
    repaired = rt("插值修复")
    flagged = rt("标记排除")
    for index, event in enumerate(events, 1):
        start = event.start_sample / sample_rate
        end = event.end_sample / sample_rate
        rows.append([index, f"{start:.6f}", f"{end:.6f}", f"{(end - start) * 1000:.3f}",
                     f"{abs(event.peak_deviation):.6f}",
                     repaired if event.repaired else flagged])
    out += _table(rows, aligns="<>>>>>")
    return out


def _section_ai(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return _note([("状态", rt("未生成")),
                      ("说明", rt("本次导出未包含 AI 说明；在 AI 助手里让它分析后再导出即可写入本段"))])
    return text.splitlines()


# ---------------------------------------------------------------- 头部与尾注


def _header(payload: dict[str, Any], options: TxtExportOptions) -> list[str]:
    out = [rt("声音实验 WAV 数据处理程序 — 分析数据导出"), ""]
    channels = payload["channels"]
    channels_text = rtf("{_v0}（{_v1}）", _v0=(channels),
                        _v1=(rt("单声道") if channels == 1 else rt("双声道")))
    out += _note([
        ("导出时间", payload["exported_at"]),
        ("数据版本", payload["data_label"]),
        ("源文件", payload["source_name"]),
        ("完整路径", payload["source_path"]),
        ("采样率", rtf("{_v0} Hz", _v0=(payload['sample_rate']))),
        ("声道数", channels_text),
        ("采样格式", payload["subtype"] or rt("未知")),
        ("总采样点", f"{payload['samples']:,}"),
        ("时长", rtf("{_v0:.6f} s", _v0=(payload['duration']))),
        ("文件大小", rtf("{_v0:.2f} MB", _v0=(payload['size_mb']))),
        ("编辑次数", rtf("{_v0} 次（去噪 {_v1} 次，裁剪 {_v2} 次）",
                     _v0=(payload['edit_depth']), _v1=(payload['denoise_edits']),
                     _v2=(payload['trim_edits']))),
        ("文件指纹", rtf("MD5 {_v0}（源 WAV 前 256 MB 的 MD5 前 16 位，用于核对本份导出与原始录音是否对应）",
                     _v0=(payload['md5']))),
    ])
    calibration = payload.get("calibration")
    offset = calibration.offset_db() if calibration is not None and getattr(calibration, "ready", False) else None
    if offset is None:
        out += _note([("声学校准", rt("未配置；本报告只含 dBFS，不含 dB SPL"))])
    else:
        out += _note([("声学校准", rtf("{_v0}；K = {_v1:+.2f} dB（dB SPL = dBFS + K）",
                                  _v0=(calibration.name), _v1=(offset)))])
        out += [_commentf("  限定：{_v0}", _v0=(text))
                for text in getattr(calibration, "caveats", lambda: [])()]
    return out


def _footer(sample_rate: int, stride: int) -> list[str]:
    out = [_rule(rt("导出说明"))]
    out += _note([
        ("编码", rt("UTF-8（含 BOM，Excel 双击不乱码）")),
        ("列对齐", rt("定宽空格对齐；除末列外只含 ASCII，任何等宽字体下逐列对齐，中文只在末列或 # 注释行")),
        ("导入", rt('pandas.read_csv(sep=r"\\s+", comment="#")；Excel 用「数据-分列-固定宽度」；Origin 选空格分隔')),
        ("注释", rt("以 # 开头的行为说明，不含数据，可按需忽略")),
        ("单位", rt("FS = 数字满幅归一化幅值；dBFS = 20lg(|x|/FS)；dBFS 不等于声压级 dB SPL")),
        ("空值", rt("-inf 表示该点幅值为 0，对数无定义；nan 表示该量在本数据上不可计算")),
        ("坐标取法", rtf("本文件坐标表步长 {_v0} 点（约 {_v1:.1f} 行/秒）",
                    _v0=(stride), _v1=(sample_rate / stride))),
    ])
    return out


def _coord_widths(samples: np.ndarray, sample_rate: int) -> list[int]:
    """坐标表列宽。必须整份数据算一次：分批生成时各批用同一份列宽，否则批间会错开。"""
    peak = 0.0
    for start in range(0, samples.size, 1 << 22):
        block = samples[start:start + (1 << 22)]
        if block.size:
            peak = max(peak, float(block.max()), -float(block.min()))
    time_width = max(len("t/s"), len(f"{(samples.size - 1) / sample_rate:.6f}"))
    # 极小幅值改用科学计数法输出（见 _coord_lines），列宽要按那种形态预留
    value_width = max(len("x/FS"), len(f"{peak:+.6f}"), len("+9.999e-99"))
    if peak > 0:
        level_width = max(len("L/dBFS"), len(f"{20.0 * np.log10(peak):.4f}"))
    else:
        level_width = len("L/dBFS")
    return [time_width, value_width, max(level_width, len("-inf"), len("-999.9999"))]


def _coord_lines(
    samples: np.ndarray, sample_rate: int, stride: int, widths: Sequence[int]
) -> Iterable[list[str]]:
    """按批生成坐标表文本，避免在内存里拼整表（4000 万点全量约 3.5 GB）。"""
    total = samples.size
    yield ["", _comment("列定义：t/s 时间（秒）  x/FS 幅值（满幅归一化）  L/dBFS 电平 20lg|x|"),
           _commentf("采样点总数 {_v0:,}，抽样步长 {_v1}（约每 {_v1} 点取 1 点），共 {_v2:,} 行",
                     _v0=(total), _v1=(stride), _v2=((total + stride - 1) // stride))]
    rows: list[list[Any]] = [["t/s", "x/FS", "L/dBFS"]]
    for start in range(0, total, stride * COORD_BATCH):
        chunk = samples[start:start + stride * COORD_BATCH:stride]
        times = (np.arange(chunk.size) * stride + start) / sample_rate
        for t, v in zip(times.tolist(), chunk.tolist()):
            if not np.isfinite(v):
                # NaN/Inf 是「不可计算」，不是「幅值为 0」：两者必须写得出差别（BUG-012）
                rows.append([f"{t:.6f}", "nan", "nan"])
                continue
            if v == 0.0:
                rows.append([f"{t:.6f}", f"{v:+.6f}", "-inf"])
                continue
            # 微小非零值不能再被压成 +0.000000：改用科学计数法保留有效数字
            text = f"{v:+.6f}" if abs(v) >= 1e-6 else f"{v:+.3e}"
            level_db = float(20.0 * np.log10(abs(v)))
            rows.append([f"{t:.6f}", text, f"{level_db:.4f}"])
        yield _table(rows, aligns="<>>", widths=widths)
        rows = []


# ---------------------------------------------------------------- 主入口


def write_analysis_txt(
    path: str | Path,
    *,
    samples: np.ndarray,
    sample_rate: int,
    source_name: str,
    source_path: str,
    subtype: str = "",
    size_mb: float = 0.0,
    md5: str = "",
    data_label: str = "源文件（未修改）",
    channels: int = 1,
    edit_depth: int = 0,
    denoise_edits: int = 0,
    trim_edits: int = 0,
    fourier: FourierResult | None = None,
    envelope: np.ndarray | None = None,
    envelope_times: np.ndarray | None = None,
    envelope_span: tuple[float, float] | None = None,
    fit: EnvelopeFit | None = None,
    denoise: Any | None = None,
    dual: dict[str, Any] | None = None,
    options: TxtExportOptions | None = None,
    fundamental: float | None = None,
    valid_mask: np.ndarray | None = None,
    progress: ProgressHook | None = None,
    append: bool = False,
    skip_footer: bool = False,
    calibration: Any | None = None,
) -> dict[str, Any]:
    """把分析结果写成 TXT。返回 {path, rows, bytes, sections, stride}。

    append=True 时把本次报告追加到已有文件（批量合并模式）。此时不能用
    utf-8-sig：BOM 只在文件开头出现一次，追加时再写一遍会在文件中间留下
    一个不可见的 \\ufeff，记事本看起来是每段标题前多一个怪字符。
    """
    options = options or TxtExportOptions()
    data = np.asarray(samples, dtype=np.float64).reshape(-1)
    if data.size < 2:
        raise ValueError(rt("采样点不足，无法导出分析数据"))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    sections = [key for key, _ in SECTION_ORDER if key in options.sections]
    if not sections:
        raise ValueError(rt("至少选择一个导出章节"))

    payload = {
        "exported_at": _now(),
        "data_label": rt(data_label),
        "source_name": source_name,
        "source_path": source_path,
        "sample_rate": int(sample_rate),
        "channels": int(channels),
        "subtype": subtype,
        "samples": int(data.size),
        "duration": float(data.size / sample_rate),
        "size_mb": float(size_mb),
        "edit_depth": int(edit_depth),
        "denoise_edits": int(denoise_edits),
        "trim_edits": int(trim_edits),
        "md5": md5,
        "calibration": calibration,
    }
    stride = options.coord_stride(sample_rate)
    layout: list[tuple[str, str]] = [(key, rt(SECTION_LABELS[key])) for key in sections]
    coord_widths = _coord_widths(data, sample_rate) if "coords" in sections else []

    total_sections = max(1, len(layout))
    rows_written = 0

    def emit(handle, lines: Sequence[str] | str) -> None:
        nonlocal rows_written
        if isinstance(lines, str):
            handle.write(lines + "\n")
            rows_written += 1
        else:
            for line in lines:
                handle.write(line + "\n")
                rows_written += 1

    encoding = "utf-8" if append else "utf-8-sig"
    with target.open("a" if append else "w", encoding=encoding, newline="\n") as handle:
        emit(handle, _header(payload, options))
        for position, (key, label) in enumerate(layout, 1):
            if progress:
                progress((position - 1) / total_sections,
                         rtf("正在写 {_v0}", _v0=(label)))
            emit(handle, _rule(f"[{position}] {label}"))
            if key == "envelope":
                emit(handle, _section_envelope(envelope, envelope_times, envelope_span,
                                               fit, sample_rate))
            elif key == "fourier":
                emit(handle, _section_fourier(fourier, peak_count=options.peak_count))
            elif key == "stats":
                emit(handle, _section_stats(data, sample_rate, valid_mask, options,
                                            fundamental, position, calibration))
            elif key == "dual":
                emit(handle, _section_dual(dual, payload["channels"]))
            elif key == "ai":
                emit(handle, _section_ai(options.ai_text))
            elif key == "denoise":
                emit(handle, _section_denoise(denoise, sample_rate, int(data.size)))
            elif key == "coords":
                for block in _coord_lines(data, sample_rate, stride, coord_widths):
                    emit(handle, block)
        if not skip_footer:
            if progress:
                progress(0.99, rt("正在写导出说明"))
            emit(handle, _footer(sample_rate, stride))

    return {
        "path": str(target),
        "rows": rows_written,
        "bytes": target.stat().st_size,
        "sections": [label for _, label in layout],
        "stride": stride,
    }


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def suggest_txt_path(source_path: Path | None, edited: bool, channel_index: int = 0) -> str:
    """<源文件名>_源文件分析.txt / <源文件名>_修改分析.txt（英文报告用 ASCII 后缀）"""
    suffix = suggest_report_suffix(edited)
    if source_path is None:
        name = f"analysis_{suffix}.txt" if report_is_english() else f"分析{suffix}.txt"
        return str(Path.cwd() / name)
    stem = source_path.stem or "audio"
    if channel_index:
        stem = f"{stem}_{rtf('声道{_v0}', _v0=(channel_index + 1))}"
    return str(source_path.with_name(f"{stem}_{suffix}.txt"))


def file_md5(path: str | Path, limit_mb: float = 256.0) -> str:
    """取源文件前 256 MB 的 MD5 前 16 位；超长文件不必为指纹把整份读一遍。"""
    import hashlib

    digest = hashlib.md5()
    source = Path(path)
    remaining = int(limit_mb * 1024 * 1024)
    try:
        with source.open("rb") as handle:
            while remaining > 0:
                block = handle.read(min(1 << 20, remaining))
                if not block:
                    break
                digest.update(block)
                remaining -= len(block)
    except OSError:
        return ""
    return digest.hexdigest()[:16].upper()
