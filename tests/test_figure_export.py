"""导出 PNG 的回归测试：三张图能落盘、选项生效、抽稀生效、字体不乱码。"""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.envelope import compute_envelope, fit_envelope
from core.figure_export import (
    FigureOptions, MAX_PLOT_POINTS, render_spectrogram_png, render_spectrum_png,
    render_waveform_png,
)
from core.spectral import fourier_analysis, stft_spectrogram


def _signal(seconds: float = 1.0, fs: int = 48000) -> tuple[np.ndarray, int]:
    t = np.arange(int(fs * seconds)) / fs
    x = 0.4 * np.sin(2 * np.pi * 1000 * t) + 0.05 * np.sin(2 * np.pi * 3000 * t)
    x += 0.005 * np.random.default_rng(0).standard_normal(t.size)
    return x, fs


def _png_size(path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(path) as image:
        return image.size


def test_waveform_png_has_requested_size(tmp_path):
    x, fs = _signal(0.5)
    target = tmp_path / "wave.png"
    info = render_waveform_png(
        target, samples=x, sample_rate=fs,
        options=FigureOptions(width_px=1280, height_px=720, title="波形"),
    )
    assert target.exists() and target.stat().st_size > 10_000
    assert (info["width"], info["height"]) == (1280, 720)
    assert _png_size(target) == (1280, 720)
    assert info["series"] == ["当前波形"]


def test_waveform_only_plots_selected_curves(tmp_path):
    x, fs = _signal(0.4)
    times, envelope = compute_envelope(x, fs)
    fit = fit_envelope(times, envelope, "exponential")
    info = render_waveform_png(
        tmp_path / "wave_all.png", samples=x, sample_rate=fs,
        original=x * 0.9, preview=x * 0.5,
        envelope=envelope, envelope_times=times,
        fit_times=times[: len(fit.fitted)], fit_values=fit.fitted,
        region=(0.1, 0.3), cursor=0.2,
    )
    assert info["series"] == ["原始波形", "去噪预览", "当前波形", "包络", "拟合曲线", "选区", "游标"]

    bare = render_waveform_png(
        tmp_path / "wave_bare.png", samples=x, sample_rate=fs,
        options=FigureOptions(legend=False, grid=False),
    )
    assert bare["series"] == ["当前波形"], "未勾选的曲线不应出现在导出图里"


def test_waveform_downsamples_without_changing_coverage(tmp_path):
    # 300 万点：绘制点数必须受限，但时间范围仍覆盖整段数据。
    x, fs = _signal(62.0, 48000)
    assert len(x) > MAX_PLOT_POINTS
    info = render_waveform_png(tmp_path / "long.png", samples=x, sample_rate=fs)
    assert info["points"] <= MAX_PLOT_POINTS
    assert info["total_samples"] == len(x)


def test_spectrum_png_phase_and_peak_labels(tmp_path):
    x, fs = _signal(1.0)
    fourier = fourier_analysis(x, fs)
    target = tmp_path / "spectrum.png"
    info = render_spectrum_png(
        target, fourier, FigureOptions(title="幅值谱"), show_phase=True, mark_harmonics=True)
    assert target.exists() and target.stat().st_size > 5_000
    assert "振幅谱" in info["series"] and "相位谱" in info["series"]
    assert "谐波标记" in info["series"] and "谱峰标注" in info["series"]

    linear = render_spectrum_png(
        tmp_path / "spectrum_linear.png", fourier,
        FigureOptions(spectrum_db=False, max_frequency=5000.0, annotate_peaks=False))
    assert "谱峰标注" not in linear["series"], "关闭标注后不应再画谱峰文字"
    assert linear["points"] < info["points"], "限制频率上限后绘制的谱线点数应减少"


def test_spectrogram_png_respects_frequency_limit(tmp_path):
    x, fs = _signal(1.0)
    spectrogram = stft_spectrogram(x, fs)
    full = render_spectrogram_png(tmp_path / "stft_full.png", spectrogram)
    part = render_spectrogram_png(
        tmp_path / "stft_part.png", spectrogram, FigureOptions(max_frequency=4000.0))
    assert part["points"] < full["points"]
    assert (tmp_path / "stft_part.png").exists()


def test_transparent_and_dark_backgrounds(tmp_path):
    x, fs = _signal(0.3)
    dark = render_waveform_png(
        tmp_path / "dark.png", samples=x, sample_rate=fs,
        options=FigureOptions(background="dark"))
    clear = render_waveform_png(
        tmp_path / "clear.png", samples=x, sample_rate=fs,
        options=FigureOptions(background="transparent"))
    assert dark["path"] != clear["path"]
    from PIL import Image
    with Image.open(tmp_path / "clear.png") as image:
        assert image.mode in ("RGBA", "LA"), "透明背景应带 alpha 通道"


def test_rejects_empty_input(tmp_path):
    with pytest.raises(ValueError):
        render_waveform_png(tmp_path / "empty.png", samples=np.zeros(1), sample_rate=48000)
    with pytest.raises(ValueError):
        render_spectrogram_png(tmp_path / "empty.png", (np.zeros(0), np.zeros(0), np.zeros((0, 0))))


def test_font_has_no_missing_glyphs(tmp_path):
    """中文标题 + 斜体变量 + 正体单位不允许出现缺字形（方块）。"""
    import warnings

    x, fs = _signal(0.3)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        render_waveform_png(
            tmp_path / "font.png", samples=x, sample_rate=fs,
            options=FigureOptions(title="时间响应曲线 1000 Hz"))
    missing = [str(w.message) for w in caught if "glyph" in str(w.message).lower()]
    assert not missing, f"存在缺字形：{missing[:3]}"
