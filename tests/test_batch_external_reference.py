"""批量里的外部参考通道（Optimize_Advice 方案 A 的批量侧）。

验证：选中外部参考时批量用它（含逐文件校验、长度不一时的部分覆盖）、
结果里记录参考来源（路径 + 声道）、以及同步平均/陷波这类不需要参考的方法
即使外部参考不可用也能继续跑。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from core.audio_io import write_wav
from core.batch import new_step, run_batch

FS = 8000


def _tone(path, f0, amp=0.3, seconds=2.0, fs=FS, noise=1e-4):
    t = np.arange(int(fs * seconds)) / fs
    rng = np.random.default_rng(0)
    x = amp * np.sin(2 * np.pi * f0 * t) + rng.normal(0.0, noise, t.size)
    write_wav(path, x, fs, subtype="PCM_16")
    return path


def _reference(path, seconds=2.0, fs=FS, noise=1e-4):
    t = np.arange(int(fs * seconds)) / fs
    rng = np.random.default_rng(1)
    x = rng.normal(0.0, noise, t.size) + 0.001 * np.sin(2 * np.pi * 120 * t)
    write_wav(path, x, fs, subtype="PCM_16")
    return path


def _anc_step(method="wiener_clean", order=256):
    step = new_step("denoise_tools")
    step["params"]["method"] = method
    step["params"]["order"] = order
    return step


def test_batch_denoise_tools_uses_external_reference(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    target = _tone(folder / "a_1000Hz.wav", 1000)
    ref = _reference(tmp_path / "noise_ref.wav")
    result = run_batch([target], [_anc_step(), new_step("export_csv")],
                       output_dir=tmp_path / "out",
                       reference={"path": str(ref), "channel": 0})
    assert result.ok_count == 1
    outcome = result.files[0]
    assert outcome.rows["denoise_method"]
    assert result.reference is not None
    assert str(ref) == result.reference["path"]
    assert result.reference["channel"] == 0


def test_batch_reference_missing_file_skips_with_note(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    target = _tone(folder / "b_1000Hz.wav", 1000)
    missing = tmp_path / "nope.wav"
    result = run_batch([target], [_anc_step(), new_step("export_csv")],
                       output_dir=tmp_path / "out",
                       reference={"path": str(missing), "channel": 0})
    assert result.ok_count == 1
    notes = result.files[0].notes
    assert any("参考" in note and ("不存在" in note or "不可用" in note) for note in notes)
    # 需要参考的方法被跳过：该行标出 blocked（没有值说明没跑降噪）
    assert not result.files[0].rows.get("denoise_applied")


def test_batch_reference_rate_mismatch_skips_but_batch_continues(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    file1 = _tone(folder / "c1_1000Hz.wav", 1000)
    file2 = _tone(folder / "c2_1000Hz.wav", 1000)
    # 参考是 16 kHz，与 8 kHz 的文件不符：两份文件都应跳过这一步但整批继续
    ref = _reference(tmp_path / "wrong_rate.wav", fs=16000)
    result = run_batch([file1, file2], [_anc_step(), new_step("export_csv")],
                       output_dir=tmp_path / "out",
                       reference={"path": str(ref), "channel": 0})
    assert result.ok_count == 2
    for outcome in result.files:
        assert any("参考" in note and "不可用" in note for note in outcome.notes)


def test_batch_no_reference_method_ignores_bad_reference(tmp_path):
    """不需要参考的方法（同步平均/陷波）即使外部参考不可用也能跑。"""
    folder = tmp_path / "in"
    folder.mkdir()
    target = _tone(folder / "d_1000Hz.wav", 1000)
    missing = tmp_path / "nope.wav"
    steps = [_anc_step(method="notch")]
    result = run_batch([target], steps, output_dir=tmp_path / "out",
                       reference={"path": str(missing), "channel": 0})
    assert result.ok_count == 1
    notes = result.files[0].notes
    assert not any("不可用" in note for note in notes)


def test_batch_reference_channel_recorded_in_summary(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    target = _tone(folder / "e_1000Hz.wav", 1000)
    ref = _reference(tmp_path / "ref.wav")
    result = run_batch([target], [_anc_step()], output_dir=tmp_path / "out",
                       reference={"path": str(ref), "channel": 2})
    assert result.reference is not None
    assert result.reference["channel"] == 2


def test_batch_noise_profile_accepts_unaligned_short_reference(tmp_path):
    """noise_profile：参考比目标短、且不是同一次录音也能用（不对齐）。"""
    folder = tmp_path / "in"
    folder.mkdir()
    target = _tone(folder / "f_1000Hz.wav", 1000)
    ref = _reference(tmp_path / "short_ref.wav", seconds=1.0)
    result = run_batch([target], [_anc_step(method="noise_profile"), new_step("export_csv")],
                       output_dir=tmp_path / "out",
                       reference={"path": str(ref), "channel": 0})
    assert result.ok_count == 1
    notes = result.files[0].notes
    assert not any("只有 1 个声道" in note for note in notes)
    assert any("参考" in note for note in notes)
