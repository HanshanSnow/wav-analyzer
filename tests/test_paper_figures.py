"""论文版式 PNG 的回归测试：物理尺寸、600 dpi、双图拆分、包络平滑、图例外置。"""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.envelope import compute_envelope, fit_envelope
from core.figure_export import (
    PAPER_DPI, PAPER_SIZES, FigureOptions, _smooth_envelope,
    render_spectrogram_png, render_spectrum_png, render_waveform_png,
)
from core.spectral import fourier_analysis, stft_spectrogram


def _signal(seconds: float = 1.0, fs: int = 48000):
    t = np.arange(int(fs * seconds)) / fs
    x = 0.4 * np.sin(2 * np.pi * 1000 * t) + 0.05 * np.sin(2 * np.pi * 3000 * t)
    return x, fs


def _size(path):
    from PIL import Image
    with Image.open(path) as image:
        return image.size


def test_paper_single_column_physical_size(tmp_path):
    x, fs = _signal(0.3)
    info = render_waveform_png(tmp_path / "single.png", samples=x, sample_rate=fs,
                               options=FigureOptions(layout="paper", column="single"))
    width, height = PAPER_SIZES["single"]
    assert (info["width"], info["height"]) == (round(width * PAPER_DPI), round(height * PAPER_DPI))
    assert _size(tmp_path / "single.png") == (info["width"], info["height"])


def test_paper_double_column_physical_size(tmp_path):
    x, fs = _signal(0.3)
    info = render_waveform_png(tmp_path / "double.png", samples=x, sample_rate=fs,
                               options=FigureOptions(layout="paper", column="double"))
    width, height = PAPER_SIZES["double"]
    assert (info["width"], info["height"]) == (round(width * PAPER_DPI), round(height * PAPER_DPI))


def test_paper_wave_with_envelope_splits_into_two_panels(tmp_path):
    x, fs = _signal(0.5)
    times, envelope = compute_envelope(x, fs)
    fit = fit_envelope(times, envelope, "auto")
    info = render_waveform_png(
        tmp_path / "split.png", samples=x, sample_rate=fs,
        options=FigureOptions(layout="paper", column="single"),
        envelope=envelope, envelope_times=times,
        fit_times=times, fit_values=fit.fitted,
    )
    width, height = PAPER_SIZES["single"]
    assert info["height"] > round(height * PAPER_DPI), "有包络时应拆成上下双图，画布更高"
    assert info["series"][:3] == ["当前波形", "包络", "拟合曲线"]

    # 屏幕版式保持单坐标区，避免影响原有出图
    flat = render_waveform_png(
        tmp_path / "flat.png", samples=x, sample_rate=fs,
        options=FigureOptions(layout="screen", width_px=800, height_px=600),
        envelope=envelope, envelope_times=times,
    )
    assert (flat["width"], flat["height"]) == (800, 600)


def test_envelope_smoothing_reduces_ripple():
    x, fs = _signal(0.5)
    _, envelope = compute_envelope(x, fs)
    smooth = _smooth_envelope(envelope, fs, True)
    raw = _smooth_envelope(envelope, fs, False)
    assert raw is envelope
    assert np.std(np.diff(smooth)) < np.std(np.diff(envelope)), "5 ms 平滑应显著降低逐点抖动"
    # 卷积在两端用最近值延拓，均值会有千分级偏差，属于纯绘图影响
    assert np.isclose(np.mean(smooth), np.mean(envelope), rtol=5e-3), "平滑不改变整体幅值水平"


def test_paper_spectrum_marks_harmonics_without_clipping(tmp_path):
    x, fs = _signal(1.0)
    fourier = fourier_analysis(x, fs)
    info = render_spectrum_png(
        tmp_path / "spec.png", fourier,
        FigureOptions(layout="paper", column="single", max_frequency=5000.0, mark_harmonics=True))
    assert "谐波标记" in info["series"]
    assert info["width"] == round(PAPER_SIZES["single"][0] * PAPER_DPI)


def test_paper_spectrogram_uses_double_column(tmp_path):
    x, fs = _signal(0.5)
    spectrogram = stft_spectrogram(x, fs)
    info = render_spectrogram_png(tmp_path / "stft.png", spectrogram,
                                  FigureOptions(layout="paper", column="double"))
    assert info["width"] == round(PAPER_SIZES["double"][0] * PAPER_DPI)


def test_legend_can_be_disabled(tmp_path):
    x, fs = _signal(0.2)
    times, envelope = compute_envelope(x, fs)
    info = render_waveform_png(
        tmp_path / "nolegend.png", samples=x, sample_rate=fs,
        options=FigureOptions(layout="paper", legend=False),
        envelope=envelope, envelope_times=times)
    assert "包络" in info["series"]
    # 没图例时画布不需要额外的底部留白
    assert info["height"] == round(PAPER_SIZES["single"][1] * PAPER_TALL * PAPER_DPI)


PAPER_TALL = 1.32


def test_paper_mode_ignores_dark_background(tmp_path):
    """论文版式固定白底：深色/透明只属于屏幕版式。"""
    x, fs = _signal(0.2)
    info = render_waveform_png(tmp_path / "white.png", samples=x, sample_rate=fs,
                               options=FigureOptions(layout="paper", background="dark"))
    from PIL import Image
    with Image.open(info["path"]).convert("RGB") as image:
        corner = image.getpixel((2, 2))
    assert corner == (255, 255, 255), f"论文版式应始终白底，实际角落像素为 {corner}"
