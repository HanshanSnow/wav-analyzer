from __future__ import annotations

import base64
import csv
import html
import io
from pathlib import Path
from typing import Any

import numpy as np

from .denoise import DenoiseResult
from .envelope import EnvelopeFit
from .report_i18n import analysis_scope_text, font_family, report_is_english, rt, rtf
from .spectral import FourierResult
from .statistics import statistics_rows


def _cell(key: str, value: Any, statistics: dict[str, Any]) -> str:
    """统计量单元格文本：口径行按报告语言重写，数值保留 8 位有效数字。"""
    if key == "analysis_scope":
        return analysis_scope_text(statistics)
    return f"{value:.8g}" if isinstance(value, float) else str(value)


def export_rows_csv(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(rt("没有可导出的数据"))
    keys = list(rows[0].keys())
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    return target


def _figure_png(samples: np.ndarray, sample_rate: int, fourier: FourierResult, envelope: np.ndarray | None) -> str:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    if report_is_english():
        plt.rcParams["font.sans-serif"] = ["Times New Roman", "DejaVu Sans"]
        plt.rcParams["font.serif"] = ["Times New Roman", "DejaVu Serif"]
        plt.rcParams["font.family"] = "serif"
    else:
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
        plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(2, 1, figsize=(10, 6))
    # 波形按列 min/max 抽稀后再画：直接 plot 全量采样点会为百万级点建路径，
    # 既慢又吃内存（长录音的 HTML 报告曾因此卡住）。抽稀只影响绘图，
    # 统计与数值导出仍用完整数据。
    from .display import min_max_downsample

    times, plot_values = min_max_downsample(samples, sample_rate, columns=4000)
    axes[0].plot(times, plot_values, linewidth=0.6, label=rt("波形"))
    if envelope is not None and len(envelope) == len(samples):
        env_times, env_values = min_max_downsample(envelope, sample_rate, columns=4000)
        axes[0].plot(env_times, env_values, linewidth=1.2, label=rt("包络"))
        axes[0].legend()
    axes[0].set(xlabel=rt("时间 / s"), ylabel=rt("幅值 / FS"), title=rt("波形"))
    axes[0].grid(alpha=0.25)
    axes[1].plot(fourier.frequencies, fourier.amplitude_dbfs, linewidth=0.8)
    axes[1].set(xlabel=rt("频率 / Hz"), ylabel=rt("幅值 / dBFS"),
                title=rt("傅立叶幅值谱"), xlim=(0, sample_rate / 2))
    axes[1].grid(alpha=0.25)
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=160)
    plt.close(fig)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def build_report_html(
    file_path: str,
    sample_rate: int,
    channel: int,
    statistics: dict[str, Any],
    fourier: FourierResult,
    samples: np.ndarray,
    envelope: np.ndarray | None = None,
    envelope_fit: EnvelopeFit | None = None,
    denoise: DenoiseResult | None = None,
    ai_narrative: str = "",
) -> str:
    figure = _figure_png(samples, sample_rate, fourier, envelope)
    # 报告中统计量用名称 + 键名双标注，避免只给英文变量名造成歧义。
    rows = "".join(
        f"<tr><th>{html.escape(label)}<br><small>{html.escape(key)}</small></th>"
        f"<td>{html.escape(_cell(key, value, statistics))}</td></tr>"
        for key, label, value, _note in statistics_rows(statistics, translate=rt)
    )
    if "calibration_offset_db" in statistics:
        name = str(statistics.get("calibration_name", ""))
        unit_note = rtf(
            "幅值为数字满幅归一化单位；dB SPL 按声学校准「{_v0}」换算（K = {_v1:+.2f} dB），"
            "可靠性取决于该标定，未计频率计权，AGC 麦克风与削顶录音不适用。",
            _v0=(name), _v1=(statistics['calibration_offset_db']),
        )
    else:
        unit_note = rt("幅值为数字满幅归一化单位，dBFS 不等于 dB SPL（未配置声学校准）。")
    fit_html = rt("未执行包络拟合")
    if envelope_fit:
        parameters = ("，".join(f"{key} = {value:.8g}"
                                for key, value in envelope_fit.parameters.items())
                      if not report_is_english()
                      else ", ".join(f"{key} = {value:.8g}"
                                     for key, value in envelope_fit.parameters.items()))
        fit_html = (
            f"<p><strong>{html.escape(envelope_fit.equation)}</strong></p>"
            f"<p>{html.escape(parameters)}</p>"
            + f"<p>{html.escape(rtf('R² = {_v0:.6f}，RMSE = {_v1:.6g}', _v0=(envelope_fit.r_squared), _v1=(envelope_fit.rmse)))}</p>"
        )
    events_html = f"<p>{html.escape(rt('未执行冲击检测。'))}</p>"
    if denoise:
        repair = rt("插值修复")
        excluded = rt("排除出统计")
        events = "".join(
            f"<tr><td>{event.start_sample / sample_rate:.6f}</td><td>{event.end_sample / sample_rate:.6f}</td>"
            f"<td>{repair if event.repaired else excluded}</td></tr>"
            for event in denoise.events
        )
        events_html = (
            f"<p>{html.escape(rtf('检测阈值 {_v0:g}；修复 {_v1} 段，排除 {_v2} 段。', _v0=(denoise.threshold), _v1=(denoise.repaired_count), _v2=(denoise.excluded_count)))}</p>"
            f"<table><thead><tr><th>{rt('开始 / s')}</th><th>{rt('结束 / s')}</th>"
            f"<th>{rt('处理')}</th></tr></thead><tbody>{events}</tbody></table>"
        )
    narrative = html.escape(ai_narrative).replace("\n", "<br>") if ai_narrative \
        else rt("本次报告由本地确定性算法生成，未使用 AI 叙述。")
    lang = "en" if report_is_english() else "zh-CN"
    body_font = (f"{font_family()},serif" if report_is_english()
                 else "'Microsoft YaHei',sans-serif")
    info = rtf("采样率：{_v0} Hz；声道：{_v1}", _v0=(sample_rate), _v1=(channel + 1))
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><title>{rt("WAV 数据处理报告")}</title>
<style>body{{font-family:{body_font};max-width:1000px;margin:32px auto;color:#222;line-height:1.6}}
table{{border-collapse:collapse;width:100%;margin:12px 0}}th,td{{border:1px solid #ccd;padding:6px 10px;text-align:left}}th{{background:#f2f5f8}}img{{max-width:100%}}.note{{background:#f5f7fa;padding:12px}}</style></head>
<body><h1>{rt("WAV 声音实验数据处理报告")}</h1>
<p>{rtf("文件：{_v0}", _v0=(html.escape(file_path)))}<br>{info}</p>
<h2>{rt("波形与傅立叶幅值谱")}</h2><img src="data:image/png;base64,{figure}" alt="{rt("波形与频谱图")}">
<p>{rtf("主频：{_v0:.6f} Hz；主频峰值振幅：{_v1:.8g}；THD：{_v2:.6g}", _v0=(fourier.main_frequency), _v1=(fourier.main_amplitude), _v2=(fourier.thd))}</p>
<p>{rtf("分析窗函数：{_v0}；FFT 点数：{_v1}", _v0=(html.escape(fourier.window)), _v1=(fourier.n_fft))}</p>
<h2>{rt("区间统计")}</h2><table>{rows}</table>
<h2>{rt("包络分析")}</h2>{fit_html}
<h2>{rt("冲击检测与去噪记录")}</h2>{events_html}
<h2>{rt("AI 分析说明")}</h2><div class="note">{narrative}</div>
<p><small>{rtf("本报告由声音实验 WAV 处理程序独立生成，未套用工作区中的任何既有实验报告。{_v0}", _v0=(unit_note))}</small></p>
</body></html>"""


def save_report(path: str | Path, content: str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target
