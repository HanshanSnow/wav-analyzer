"""保真性回归测试：优化长音频性能时不得牺牲数值准确性。"""
import time

import numpy as np

from core.audio_io import AudioData
from core.spectral import fourier_analysis, stft_spectrogram
from core.statistics import interval_statistics, probe_time


FS = 48000


def test_energy_statistics_use_full_selection():
    """RMS/峰值必须基于选区全部采样点，不能使用抽稀后的数据。"""
    rng = np.random.default_rng(42)
    x = rng.normal(0, 0.2, 300000)  # 超过单列显示阈值
    stats = interval_statistics(x, FS)
    assert stats["samples"] == len(x)
    assert abs(stats["rms"] - np.sqrt(np.mean(x ** 2))) < 1e-9
    assert abs(stats["peak_amplitude"] - np.max(np.abs(x))) < 1e-9
    assert "analysis_scope" in stats
    assert "全部有效采样点" in stats["analysis_scope"]


def test_fourier_window_is_disclosed():
    """使用受限窗口时必须如实标注实际点数与时间范围。"""
    t = np.arange(FS * 12) / FS
    x = 0.4 * np.sin(2 * np.pi * 997 * t)
    result = fourier_analysis(x, FS, fundamental_frequency=997)
    assert result.analyzed_samples < result.total_samples
    assert result.analysis_offset > 0
    assert abs(result.main_frequency - 997) < 0.3
    assert abs(result.main_amplitude - 0.4) < 1e-3
    # 用户可要求全量分析
    full = fourier_analysis(x, FS, fundamental_frequency=997, max_samples=0)
    assert full.analyzed_samples == full.total_samples


def test_probe_envelope_has_no_edge_bias():
    """游标包络读数不得因 Hilbert 边缘效应产生系统偏低。"""
    t = np.arange(FS * 2) / FS
    x = 0.4 * np.sin(2 * np.pi * 1000 * t)
    for ts in (0.05, 0.5, 1.0, 1.5, 1.95):
        value = probe_time(x, FS, ts)["envelope"]
        assert abs(value - 0.4) < 0.004, f"t={ts} 包络 {value} 偏离 0.4"


def test_long_audio_stays_fast():
    """长音频各分析步骤必须在秒级完成，避免界面假死。"""
    x = np.zeros(FS * 30)
    x[::480] = 0.5  # 30 秒 100 Hz -like 脉冲
    started = time.perf_counter()
    interval_statistics(x, FS)
    fourier_analysis(x, FS, fundamental_frequency=100)
    stft_spectrogram(x, FS)
    probe_time(x, FS, 15.0)
    assert time.perf_counter() - started < 3.0


def test_stft_frame_cap_keeps_frequency_axis():
    """跳帧只能减少时间帧数，不能改变频率轴（采样率语义不变）。"""
    x = 0.3 * np.sin(2 * np.pi * 5000 * np.arange(FS * 20) / FS)
    times, frequencies, magnitude = stft_spectrogram(x, FS)
    assert len(times) <= 4000
    assert frequencies[-1] == FS / 2
    peak_bin = int(np.argmax(magnitude[:, len(times) // 2]))
    assert abs(frequencies[peak_bin] - 5000) < 50  # 分辨率 46.875 Hz
