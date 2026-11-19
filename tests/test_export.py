import numpy as np

from core.exporter import build_report_html, save_report
from core.spectral import fourier_analysis
from core.statistics import interval_statistics


def test_independent_html_report(tmp_path):
    fs = 44100
    t = np.arange(fs // 10) / fs
    x = 0.3 * np.sin(2 * np.pi * 500 * t)
    fourier = fourier_analysis(x, fs)
    stats = interval_statistics(x, fs)
    content = build_report_html("synthetic.wav", fs, 0, stats, fourier, x, ai_narrative="测试说明")
    target = save_report(tmp_path / "report.html", content)
    text = target.read_text(encoding="utf-8")
    assert "傅立叶幅值谱" in text
    assert "测试说明" in text
    assert "data:image/png;base64" in text
    assert "dBFS 不等于 dB SPL" in text


def test_report_uses_chinese_statistics_labels(tmp_path):
    fs = 44100
    t = np.arange(fs // 10) / fs
    x = 0.3 * np.sin(2 * np.pi * 500 * t)
    stats = interval_statistics(x, fs)
    content = build_report_html("synthetic.wav", fs, 0, stats, fourier_analysis(x, fs), x)
    assert "有效值 RMS (FS)" in content, "报告应给出中文统计量名"
    assert "rms" in content, "报告同时保留键名，便于对照 CSV"
    assert "dBFS" in content
