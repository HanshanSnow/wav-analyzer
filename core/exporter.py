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
from .spectral import FourierResult
from .statistics import statistics_rows


def export_rows_csv(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("没有可导出的数据")
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

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(2, 1, figsize=(10, 6))
    times = np.arange(len(samples)) / sample_rate
    axes[0].plot(times, samples, linewidth=0.6, label="波形")
    if envelope is not None and len(envelope) == len(samples):
        axes[0].plot(times, envelope, linewidth=1.2, label="包络")
        axes[0].legend()
    axes[0].set(xlabel="时间 / s", ylabel="幅值 / FS", title="波形")
    axes[0].grid(alpha=0.25)
    axes[1].plot(fourier.frequencies, fourier.amplitude_dbfs, linewidth=0.8)
    axes[1].set(xlabel="频率 / Hz", ylabel="幅值 / dBFS", title="傅立叶幅值谱", xlim=(0, sample_rate / 2))
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
    # 报告中统计量用中文名 + 键名双标注，避免只给英文变量名造成歧义。
    rows = "".join(
        f"<tr><th>{html.escape(label)}<br><small>{html.escape(key)}</small></th>"
        f"<td>{html.escape(f'{value:.8g}' if isinstance(value, float) else str(value))}</td></tr>"
        for key, label, value, _note in statistics_rows(statistics)
    )
    if "calibration_offset_db" in statistics:
        name = html.escape(str(statistics.get("calibration_name", "")))
        unit_note = (
            f"幅值为数字满幅归一化单位；dB SPL 按声学校准「{name}」换算"
            f"（K = {statistics['calibration_offset_db']:+.2f} dB），"
            f"可靠性取决于该标定，未计频率计权，AGC 麦克风与削顶录音不适用。"
        )
    else:
        unit_note = "幅值为数字满幅归一化单位，dBFS 不等于 dB SPL（未配置声学校准）。"
    fit_html = "未执行包络拟合"
    if envelope_fit:
        parameters = "，".join(f"{key} = {value:.8g}" for key, value in envelope_fit.parameters.items())
        fit_html = (
            f"<p><strong>{html.escape(envelope_fit.equation)}</strong></p>"
            f"<p>{html.escape(parameters)}</p><p>R² = {envelope_fit.r_squared:.6f}，RMSE = {envelope_fit.rmse:.6g}</p>"
        )
    events_html = "<p>未执行冲击检测。</p>"
    if denoise:
        events = "".join(
            f"<tr><td>{event.start_sample / sample_rate:.6f}</td><td>{event.end_sample / sample_rate:.6f}</td>"
            f"<td>{'插值修复' if event.repaired else '排除出统计'}</td></tr>"
            for event in denoise.events
        )
        events_html = (
            f"<p>检测阈值 {denoise.threshold:g}；修复 {denoise.repaired_count} 段，排除 {denoise.excluded_count} 段。</p>"
            f"<table><thead><tr><th>开始 / s</th><th>结束 / s</th><th>处理</th></tr></thead><tbody>{events}</tbody></table>"
        )
    narrative = html.escape(ai_narrative).replace("\n", "<br>") if ai_narrative else "本次报告由本地确定性算法生成，未使用 AI 叙述。"
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>WAV 数据处理报告</title>
<style>body{{font-family:'Microsoft YaHei',sans-serif;max-width:1000px;margin:32px auto;color:#222;line-height:1.6}}
table{{border-collapse:collapse;width:100%;margin:12px 0}}th,td{{border:1px solid #ccd;padding:6px 10px;text-align:left}}th{{background:#f2f5f8}}img{{max-width:100%}}.note{{background:#f5f7fa;padding:12px}}</style></head>
<body><h1>WAV 声音实验数据处理报告</h1>
<p>文件：{html.escape(file_path)}<br>采样率：{sample_rate} Hz；声道：{channel + 1}</p>
<h2>波形与傅立叶幅值谱</h2><img src="data:image/png;base64,{figure}" alt="波形与频谱图">
<p>主频：{fourier.main_frequency:.6f} Hz；主频峰值振幅：{fourier.main_amplitude:.8g}；THD：{fourier.thd:.6g}</p>
<h2>区间统计</h2><table>{rows}</table>
<h2>包络分析</h2>{fit_html}
<h2>冲击检测与去噪记录</h2>{events_html}
<h2>AI 分析说明</h2><div class="note">{narrative}</div>
<p><small>本报告由声音实验 WAV 处理程序独立生成，未套用工作区中的任何既有实验报告。{unit_note}</small></p>
</body></html>"""


def save_report(path: str | Path, content: str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target
