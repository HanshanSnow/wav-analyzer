"""独立噪声画像（方案 B）验收测试。

关键场景：上次谱减/WOLA 失败在"per-frame 增益波动把能量搬到其它频带"。
这里专门用带 1 kHz 音的合成噪声验证：
- 主频附近 2–3.8 kHz 频带的能量确实下降；
- 主频幅值只在小容差内变化（不被明显削掉）；
- 纯噪声（无音调）输入时增益接近 1（不引入假信号）；
- 噪声谱确实独立于目标对齐（参考比目标长/短都没关系）。
"""

from __future__ import annotations

import numpy as np
import pytest

from core.noise_profile import apply_noise_profile

FS = 8000


def _tone_plus_noise(seconds=2.0, fs=FS, tone_amp=0.3, noise_amp=0.05, seed=7):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * fs)) / fs
    tone = tone_amp * np.sin(2 * np.pi * 1000.0 * t)
    noise = noise_amp * rng.standard_normal(t.size)
    return tone + noise, rng.normal(0.0, noise_amp, int(0.6 * fs))


def _band_energy(signal, fs=FS, low=2000, high=3800):
    spectrum = np.abs(np.fft.rfft(signal)) ** 2
    freqs = np.fft.rfftfreq(signal.size, d=1.0 / fs)
    band = (freqs > low) & (freqs < high)
    return float(np.mean(spectrum[band]))


def _tone_amplitude(signal, fs=FS, frequency=1000.0):
    window = np.hanning(signal.size)
    spectrum = np.abs(np.fft.rfft(signal * window))
    freqs = np.fft.rfftfreq(signal.size, d=1.0 / fs)
    index = int(np.argmin(np.abs(freqs - frequency)))
    return float(2.0 * spectrum[index] / np.sum(window))


def test_reduces_noise_band_and_keeps_tone():
    target, noise = _tone_plus_noise()
    result = apply_noise_profile(target, noise, FS, fundamental=1000.0)
    assert result.blocked is None, result.blocked
    assert result.cleaned is not None
    before_band = _band_energy(target.astype(np.float64))
    after_band = _band_energy(result.cleaned)
    assert after_band < before_band * 0.5, f"噪声带能量没有明显下降（{before_band:.3f} → {after_band:.3f}）"
    before_tone = _tone_amplitude(target)
    after_tone = _tone_amplitude(result.cleaned)
    change_db = 20 * np.log10(after_tone / before_tone)
    assert abs(change_db) < 1.0, f"主频被明显改变：{change_db:+.2f} dB"


def test_pure_noise_is_suppressed_not_amplified():
    """纯噪声输入时输出应明显变小（增益 < 1），且不产生超出输入的峰值。"""
    rng = np.random.default_rng(3)
    noise = 0.1 * rng.standard_normal(FS)
    result = apply_noise_profile(noise, noise.copy(), FS)
    assert result.blocked is None, result.blocked
    assert np.sqrt(np.mean(result.cleaned ** 2)) < np.sqrt(np.mean(noise ** 2))
    # 不产生比输入更大的样本（musical noise 不应放大峰值）
    assert np.max(np.abs(result.cleaned)) <= np.max(np.abs(noise)) + 1e-9


def test_reference_length_does_not_matter():
    """参考比目标长或短都可以（独立录音场景），只要不短于最小可用长度。"""
    target, noise = _tone_plus_noise()
    longer = np.concatenate([noise, np.zeros(FS // 2)])
    shorter = noise[: int(0.6 * FS)]  # 刚好满足最小参考长度
    for ref in (longer, shorter):
        result = apply_noise_profile(target, ref, FS, fundamental=1000.0)
        assert result.blocked is None, result.blocked
        assert result.cleaned is not None


def test_rejects_too_short_reference():
    target, noise = _tone_plus_noise()
    result = apply_noise_profile(target, noise[:100], FS)
    assert result.blocked is not None
    assert "太短" in result.blocked


def test_rejects_silent_or_nonfinite_reference():
    target, noise = _tone_plus_noise()
    silent = apply_noise_profile(target, np.zeros(noise.size), FS)
    assert silent.blocked is not None
    broken = noise.copy()
    broken[10] = np.nan
    bad = apply_noise_profile(target, broken, FS)
    assert bad.blocked is not None


def test_rejects_nonstationary_reference():
    target, noise = _tone_plus_noise()
    # 后半段能量提高 20 dB：明显不平稳
    ramp = np.ones(noise.size)
    ramp[noise.size // 2:] = 10.0
    nonstationary = noise * ramp
    result = apply_noise_profile(target, nonstationary, FS, fundamental=1000.0)
    assert result.blocked is not None
    assert "不平稳" in result.blocked


def test_output_length_always_equals_input_length():
    """补零只为了让 STFT 能算，输出必须与输入等长（批量会直接写回原数组）。"""
    rng = np.random.default_rng(5)
    reference = rng.normal(0.0, 0.05, int(0.6 * FS))
    for size in (32, 100, 1023, 1024, 1025):
        target = 0.3 * np.sin(2 * np.pi * 1000.0 * np.arange(size) / FS) + \
            0.01 * rng.standard_normal(size)
        result = apply_noise_profile(target, reference, FS, fundamental=1000.0)
        assert result.blocked is None, f"{size} 点被拒绝：{result.blocked}"
        assert result.cleaned.size == size, f"输入 {size} 点，输出 {result.cleaned.size} 点"
        assert np.all(np.isfinite(result.cleaned))


def test_below_minimum_size_is_rejected_without_output():
    rng = np.random.default_rng(6)
    reference = rng.normal(0.0, 0.05, int(0.6 * FS))
    target = 0.3 * np.sin(2 * np.pi * 1000.0 * np.arange(31) / FS)
    result = apply_noise_profile(target, reference, FS, fundamental=1000.0)
    assert result.cleaned is None
    assert result.blocked is not None


def test_short_target_through_engine_keeps_length():
    """引擎入口（run_method）同样不能改变长度，否则批量赋值会广播失败。"""
    from core.anc import run_method

    rng = np.random.default_rng(7)
    reference = rng.normal(0.0, 0.05, int(0.6 * FS))
    target = 0.3 * np.sin(2 * np.pi * 1000.0 * np.arange(100) / FS)
    outcome = run_method("noise_profile", target, reference, FS, fundamental=1000.0)
    assert outcome.applied, outcome.diagnostics.blocked
    assert outcome.cleaned.shape == target.shape


def test_rejects_reference_with_signal_tone():
    """参考里含有与目标相同频率的强音，应拒绝（否则会把信号当噪声减掉）。"""
    target, noise = _tone_plus_noise()
    t = np.arange(noise.size) / FS
    ref_with_tone = noise + 0.2 * np.sin(2 * np.pi * 1000.0 * t)
    result = apply_noise_profile(target, ref_with_tone, FS, fundamental=1000.0)
    assert result.blocked is not None


# ---------------------------------------------------------------- 引擎注册
def test_noise_profile_is_registered_and_needs_no_reference():
    from core.anc import METHOD_IDS, run_method

    assert "noise_profile" in METHOD_IDS
    target, _noise = _tone_plus_noise()
    outcome = run_method("noise_profile", target, None, FS)
    assert not outcome.applied
    assert outcome.diagnostics.blocked


def test_run_method_matches_the_direct_call():
    """引擎入口与直接调用必须给出同一份结果（防止两处参数漂移）。"""
    from core.anc import run_method

    target, noise = _tone_plus_noise()
    direct = apply_noise_profile(target, noise, FS, fundamental=1000.0)
    outcome = run_method("noise_profile", target, noise, FS, fundamental=1000.0)
    assert outcome.applied and direct.blocked is None
    np.testing.assert_allclose(outcome.cleaned, direct.cleaned, rtol=0, atol=0)


def test_noise_profile_accepts_unaligned_reference_in_engine():
    """起点不对齐也允许：这是它与对齐类方法的本质区别。"""
    from core.anc import run_method

    target, noise = _tone_plus_noise()
    shifted = np.roll(noise, 500)
    outcome = run_method("noise_profile", target, shifted, FS, fundamental=1000.0)
    assert outcome.applied, outcome.diagnostics.blocked
