"""外部参考通道：声道选择、等长/不等长对齐、与内置声道的等价性。"""

from __future__ import annotations

import numpy as np
import pytest

from core.anc import run_method
from core.audio_io import write_wav
from core.reference import (
    MAX_LAG_SECONDS, ReferenceError, align_reference, file_sha256, load_reference,
)

FS = 8000


def _tone_and_noise(seconds=1.0, seed=11):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * FS)) / FS
    tone = 0.3 * np.sin(2 * np.pi * 1000 * t)
    noise = 0.05 * rng.standard_normal(t.size)
    return (tone + noise).astype(np.float64), noise.astype(np.float64)


def _write_mono(path, data, rate=FS):
    write_wav(str(path), np.asarray(data, dtype=np.float32)[:, None], rate, subtype="PCM_24")
    return path


def test_reference_accepts_mono(tmp_path):
    _, noise = _tone_and_noise()
    path = _write_mono(tmp_path / "ref.wav", noise)
    ref = load_reference(path, sample_rate=FS)
    assert ref.frames == noise.size
    assert ref.channel == 0
    assert ref.sha256 == file_sha256(path)
    assert ref.as_row()["channel"] == 0


def test_reference_accepts_multichannel_with_explicit_choice(tmp_path):
    _, noise = _tone_and_noise()
    other = noise * 2.0
    path = tmp_path / "stereo.wav"
    write_wav(str(path), np.stack([noise, other], axis=1).astype(np.float32), FS,
              subtype="PCM_24")

    left = load_reference(path, sample_rate=FS, channel=0)
    right = load_reference(path, sample_rate=FS, channel=1)
    assert not np.allclose(left.samples, right.samples)
    np.testing.assert_allclose(right.samples, other.astype(np.float32), rtol=1e-6, atol=1e-6)
    assert right.as_row()["channel"] == 1

    with pytest.raises(ReferenceError) as excinfo:
        load_reference(path, sample_rate=FS, channel=2)
    assert "声道" in str(excinfo.value)


def test_reference_rejects_rate_mismatch(tmp_path):
    _, noise = _tone_and_noise()
    path = _write_mono(tmp_path / "ref.wav", noise, rate=16000)
    with pytest.raises(ReferenceError) as excinfo:
        load_reference(path, sample_rate=FS)
    assert "采样率" in str(excinfo.value)


def test_reference_rejects_silent_and_nonfinite(tmp_path):
    silent = _write_mono(tmp_path / "silent.wav", np.zeros(FS))
    with pytest.raises(ReferenceError):
        load_reference(silent, sample_rate=FS)

    import soundfile as sf

    broken = np.zeros(FS)
    broken[5] = np.nan
    bad = tmp_path / "bad.wav"
    sf.write(str(bad), broken.astype(np.float32)[:, None], FS, subtype="FLOAT")
    with pytest.raises(ReferenceError):
        load_reference(bad, sample_rate=FS)


def test_missing_file_is_a_readable_error(tmp_path):
    with pytest.raises(ReferenceError) as excinfo:
        load_reference(tmp_path / "nope.wav", sample_rate=FS)
    assert "不存在" in str(excinfo.value)


def test_align_equal_length_is_unchanged(tmp_path):
    target, noise = _tone_and_noise()
    ref, info = align_reference(noise, target, FS)
    assert info["overlap_frames"] == target.size
    assert info["unprocessed_frames"] == 0
    assert info["lag_samples"] == 0
    assert ref.size == target.size


def test_align_allows_longer_reference_and_reports_unprocessed(tmp_path):
    target, noise = _tone_and_noise(seconds=1.0)
    longer = np.concatenate([noise, np.zeros(FS // 2)])
    ref, info = align_reference(longer, target, FS)
    assert info["overlap_frames"] == target.size
    assert info["unprocessed_frames"] == 0
    assert ref.size == target.size


def test_align_allows_shorter_reference_and_reports_unprocessed():
    target, noise = _tone_and_noise(seconds=1.0)
    shorter = noise[: int(0.8 * FS)]
    ref, info = align_reference(shorter, target, FS)
    assert info["overlap_frames"] == shorter.size
    assert info["unprocessed_frames"] == target.size - shorter.size
    assert ref.size == shorter.size


def test_align_rejects_shifted_reference():
    target, noise = _tone_and_noise()
    shifted = np.roll(noise, 100)
    with pytest.raises(ReferenceError) as excinfo:
        align_reference(shifted, target, FS)
    message = str(excinfo.value)
    assert "起点" in message and "ms" in message


def test_align_rejects_too_little_overlap():
    target, noise = _tone_and_noise()
    with pytest.raises(ReferenceError):
        align_reference(noise[: target.size // 4], target, FS)


def test_external_reference_matches_in_memory_path(tmp_path):
    """关键验收：参考从文件读出来（选声道）与直接给内存数组，结果必须逐点相同。"""
    target, noise = _tone_and_noise()
    path = _write_mono(tmp_path / "ref.wav", noise)
    ref = load_reference(path, sample_rate=FS)
    aligned, _info = align_reference(ref.samples, target, FS)

    from_file = run_method("wiener_spectral", target, aligned, FS, fundamental=1000.0)
    in_memory = run_method("wiener_spectral", target, noise, FS, fundamental=1000.0)
    assert from_file.applied == in_memory.applied
    if in_memory.applied:
        np.testing.assert_allclose(from_file.cleaned, in_memory.cleaned, rtol=0, atol=0)
