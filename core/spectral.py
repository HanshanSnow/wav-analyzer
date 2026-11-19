from __future__ import annotations

from core.i18n import tf, tr
from dataclasses import dataclass

import numpy as np
from scipy import signal


# 长音频保护上限：超过该点数时只取居中连续窗口做 FFT。
# 262144 点 @ 48 kHz ≈ 5.5 s，频率分辨率 ≈ 0.18 Hz，足够声学稳态分析。
MAX_FFT_SAMPLES = 1 << 18
# 时频图最大帧数：超过时均匀抽帧，避免生成上千万点的图像矩阵。
MAX_SPECTROGRAM_FRAMES = 4000


@dataclass
class FourierResult:
    frequencies: np.ndarray
    amplitude: np.ndarray
    phase: np.ndarray
    main_frequency: float
    main_amplitude: float
    fundamental_frequency: float
    thd: float
    sample_rate: int
    window: str
    n_fft: int
    analyzed_samples: int = 0   # 实际参与 FFT 的点数
    total_samples: int = 0      # 输入信号总点数
    analysis_offset: float = 0.0  # 分析窗口起点（秒）

    @property
    def amplitude_dbfs(self) -> np.ndarray:
        return 20 * np.log10(np.maximum(self.amplitude, 1e-15))

    def peaks(self, count: int = 8, min_distance_bins: int = 2) -> list[dict[str, float]]:
        if len(self.amplitude) < 3:
            return []
        indices, _ = signal.find_peaks(self.amplitude, distance=max(1, min_distance_bins))
        indices = indices[self.amplitude[indices] > 0]
        indices = indices[np.argsort(self.amplitude[indices])[::-1]][:count]
        return [
            {"frequency_hz": float(self.frequencies[i]), "amplitude": float(self.amplitude[i]),
             "amplitude_dbfs": float(self.amplitude_dbfs[i]), "phase_rad": float(self.phase[i])}
            for i in indices
        ]

    def harmonics(self, max_harmonic: int = 8) -> list[dict[str, float]]:
        if self.fundamental_frequency <= 0:
            return []
        result = []
        nyquist = self.sample_rate / 2
        for order in range(1, max_harmonic + 1):
            target = self.fundamental_frequency * order
            if target >= nyquist:
                break
            tolerance = max((self.frequencies[1] - self.frequencies[0]) * 2, target * 0.01)
            candidates = np.flatnonzero(np.abs(self.frequencies - target) <= tolerance)
            if not len(candidates):
                continue
            index = int(candidates[np.argmax(self.amplitude[candidates])])
            result.append({
                "order": order,
                "frequency_hz": float(self.frequencies[index]),
                "amplitude": float(self.amplitude[index]),
                "amplitude_dbfs": float(self.amplitude_dbfs[index]),
                "phase_rad": float(self.phase[index]),
            })
        return result


def _refined_peak(frequencies: np.ndarray, amplitude: np.ndarray, index: int) -> tuple[float, float]:
    if index <= 0 or index >= len(amplitude) - 1:
        return float(frequencies[index]), float(amplitude[index])
    left, center, right = amplitude[index - 1:index + 2]
    denominator = left - 2 * center + right
    offset = 0.5 * (left - right) / denominator if abs(denominator) > 1e-20 else 0.0
    offset = float(np.clip(offset, -1.0, 1.0))
    bin_width = frequencies[1] - frequencies[0]
    refined_amplitude = center - 0.25 * (left - right) * offset
    return float(frequencies[index] + offset * bin_width), float(max(refined_amplitude, 0.0))


def fourier_analysis(
    samples: np.ndarray,
    sample_rate: int,
    window: str = "hann",
    n_fft: int | None = None,
    remove_dc: bool = True,
    fundamental_frequency: float | None = None,
    max_samples: int | None = MAX_FFT_SAMPLES,
) -> FourierResult:
    x_all = np.asarray(samples, dtype=np.float64).reshape(-1)
    total_samples = len(x_all)
    if total_samples < 2 or sample_rate <= 0:
        raise ValueError(tr("傅立叶分析至少需要两个采样点和正采样率"))
    if not np.isfinite(x_all).all():
        raise ValueError(tr("傅立叶分析输入包含 NaN 或无穷值"))

    # 长音频保护：只取居中的连续窗口参与 FFT。窗口内保留原始采样率，
    # 因此频率轴物理意义不变；界面会标注实际分析的时间范围。
    limit = int(max_samples) if max_samples and int(max_samples) >= 2 else 0
    offset_samples = 0
    if limit and total_samples > limit:
        offset_samples = (total_samples - limit) // 2
        x = x_all[offset_samples:offset_samples + limit]
    else:
        x = x_all
    if remove_dc:
        x = x - np.mean(x)
    n_fft = int(n_fft or len(x))
    if n_fft < len(x):
        # 兼容调用方显式指定较小 n_fft 的情况：自动放宽到窗口长度
        n_fft = len(x)
    try:
        window_values = signal.get_window(window, len(x), fftbins=True)
    except Exception as exc:
        raise ValueError(tf('不支持的窗函数：{window}', window=(window))) from exc
    coherent_gain = float(np.sum(window_values))
    if coherent_gain <= 0:
        raise ValueError(tr("窗函数的相干增益无效"))
    transformed = np.fft.rfft(x * window_values, n=n_fft)
    frequencies = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    amplitude = np.abs(transformed) / coherent_gain
    if len(amplitude) > 2:
        amplitude[1:-1] *= 2.0
        if n_fft % 2:
            amplitude[-1] *= 2.0
    phase = np.angle(transformed)
    search_start = 1
    if fundamental_frequency and fundamental_frequency > 0:
        tolerance = max(frequencies[1] * 3, fundamental_frequency * 0.05)
        candidates = np.flatnonzero(np.abs(frequencies - fundamental_frequency) <= tolerance)
        candidates = candidates[candidates >= search_start]
        peak_index = int(candidates[np.argmax(amplitude[candidates])]) if len(candidates) else search_start
    else:
        peak_index = int(np.argmax(amplitude[search_start:]) + search_start)
    main_frequency, main_amplitude = _refined_peak(frequencies, amplitude, peak_index)
    harmonic_amplitudes = []
    for order in range(2, 11):
        target = main_frequency * order
        if target >= sample_rate / 2:
            break
        tolerance = max(frequencies[1] * 1.5, main_frequency * 0.01)
        candidates = np.flatnonzero(np.abs(frequencies - target) <= tolerance)
        if len(candidates):
            harmonic_amplitudes.append(float(np.max(amplitude[candidates])))
    thd = float(np.sqrt(np.sum(np.square(harmonic_amplitudes))) / max(main_amplitude, 1e-15))
    return FourierResult(
        frequencies, amplitude, phase, main_frequency, main_amplitude,
        main_frequency, thd, int(sample_rate), window, n_fft,
        analyzed_samples=int(len(x)), total_samples=int(total_samples),
        analysis_offset=float(offset_samples / sample_rate),
    )


def stft_spectrogram(
    samples: np.ndarray,
    sample_rate: int,
    nperseg: int = 1024,
    noverlap: int | None = None,
    max_frames: int = MAX_SPECTROGRAM_FRAMES,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.asarray(samples, dtype=np.float64).reshape(-1)
    if len(x) < 2:
        raise ValueError(tr("时频分析数据过短"))
    nperseg = int(np.clip(nperseg, 16, len(x)))
    noverlap = nperseg // 2 if noverlap is None else int(np.clip(noverlap, 0, nperseg - 1))
    hop = max(1, nperseg - noverlap)
    expected_frames = 1 + (len(x) - nperseg) // hop

    if expected_frames <= max_frames:
        frequencies, times, power = signal.spectrogram(
            x - np.mean(x), fs=sample_rate, window="hann", nperseg=nperseg,
            noverlap=noverlap, detrend=False, scaling="spectrum", mode="magnitude",
        )
        return times, frequencies, 20 * np.log10(np.maximum(power, 1e-15))

    # 长音频保护：跳帧 STFT。保持原采样率与窗口长度（频率轴不变），
    # 只在整段信号上均匀取 max_frames 个时间点计算，避免生成上千万帧的矩阵。
    starts = np.linspace(0, len(x) - nperseg, int(max_frames)).astype(np.int64)
    window = signal.get_window("hann", nperseg, fftbins=True)
    coherent_gain = float(np.sum(window))
    n_bins = nperseg // 2 + 1
    magnitude = np.empty((n_bins, len(starts)), dtype=np.float64)
    centered = x - np.mean(x)
    for column, start in enumerate(starts):
        segment = centered[int(start):int(start) + nperseg] * window
        spectrum = np.fft.rfft(segment)
        amp = np.abs(spectrum) / coherent_gain
        if n_bins > 2:
            amp[1:-1] *= 2.0
        magnitude[:, column] = amp
    frequencies = np.fft.rfftfreq(nperseg, d=1.0 / sample_rate)
    times = starts / sample_rate
    return times, frequencies, 20 * np.log10(np.maximum(magnitude, 1e-15))
