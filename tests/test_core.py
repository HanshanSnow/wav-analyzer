import numpy as np

from core.audio_io import AudioData, read_wav, write_wav
from core.denoise import detect_and_repair_impulses
from core.envelope import compute_envelope, fit_envelope
from core.spectral import fourier_analysis, stft_spectrogram
from core.statistics import interval_statistics, probe_time


FS = 44100


def sine(frequency=1000.0, amplitude=0.4, duration=0.1, phase=0.0):
    t = np.arange(round(FS * duration)) / FS
    return t, amplitude * np.sin(2 * np.pi * frequency * t + phase)


def test_fourier_peak_amplitude_frequency_and_thd():
    t, clean = sine()
    distorted = clean + 0.04 * np.sin(2 * np.pi * 2000 * t)
    result = fourier_analysis(distorted, FS)
    assert abs(result.main_frequency - 1000) < 0.2
    assert abs(result.main_amplitude - 0.4) < 1e-3
    assert abs(result.thd - 0.1) < 0.01
    assert result.harmonics(2)[1]["amplitude"] > 0.039
    assert np.isfinite(result.phase).all()


def test_stft_shapes_and_impulse_detection_repair():
    _, clean = sine(duration=0.2)
    damaged = clean.copy()
    damaged[2000] += 0.9
    damaged[6000] -= 0.8
    result = detect_and_repair_impulses(damaged, FS, threshold=8, max_repair_ms=2)
    assert len(result.events) == 2
    assert result.repaired_count == 2
    assert result.valid_mask.all()
    assert np.sqrt(np.mean((result.cleaned - clean) ** 2)) < 0.02
    times, frequencies, magnitude = stft_spectrogram(clean, FS)
    assert magnitude.shape == (len(frequencies), len(times))


def test_long_impulse_is_excluded_not_fabricated():
    _, clean = sine(duration=0.2)
    damaged = clean.copy()
    damaged[3000:3400] = 0.8
    result = detect_and_repair_impulses(damaged, FS, threshold=6, max_repair_ms=1)
    assert result.excluded_count >= 1
    assert not result.valid_mask[3100]
    stats = interval_statistics(result.cleaned, FS, valid_mask=result.valid_mask)
    assert stats["excluded_samples"] > 0


def test_envelope_constant_and_exponential_fit():
    t, steady = sine(duration=0.2)
    _, envelope = compute_envelope(steady, FS)
    steady_fit = fit_envelope(t[100:-100], envelope[100:-100], "constant")
    assert abs(steady_fit.parameters["a"] - 0.4) < 0.01

    decay = 0.8 * np.exp(-2 * t) * np.sin(2 * np.pi * 100 * t)
    _, decay_envelope = compute_envelope(decay, FS)
    fit = fit_envelope(t[100:-100], decay_envelope[100:-100], "exponential")
    assert abs(fit.parameters["b"] + 2) < 0.15
    assert fit.r_squared > 0.99


def test_statistics_and_probe():
    _, clean = sine()
    stats = interval_statistics(clean, FS)
    assert abs(stats["rms"] - 0.4 / np.sqrt(2)) < 1e-6
    assert abs(stats["peak_amplitude"] - 0.4) < 1e-3
    assert abs(stats["main_frequency_hz"] - 1000) < 0.2
    probe = probe_time(clean, FS, 0.05)
    assert abs(probe["local_rms"] - stats["rms"]) < 1e-3
    assert probe["envelope"] > 0.35


def test_wav_roundtrip_and_quality(tmp_path):
    _, clean = sine()
    audio = AudioData(np.column_stack((clean, clean * 0.5)), FS)
    target = tmp_path / "stereo.wav"
    write_wav(target, audio.samples, FS)
    loaded = read_wav(target)
    assert loaded.channels == 2
    assert loaded.sample_rate == FS
    assert loaded.samples.shape == clean.shape + (2,)
    assert np.max(np.abs(loaded.samples[:, 0] - clean)) < 1e-6
    quality = loaded.quality_report()
    assert len(quality) == 2
    assert not quality[0]["clipping_warning"]
