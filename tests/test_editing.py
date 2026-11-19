"""编辑与长音频优化的回归测试：裁剪、写回、抽稀保真、包络局部化。"""
import numpy as np
import pytest

from core.audio_io import read_wav, write_wav
from core.editor import apply_to_source, backup_path_for, trim_range
from core.envelope import MAX_PAD_RATIO, SHORT_SIGNAL_LIMIT, compute_envelope, hilbert_envelope
from app.main_window import _compute_envelope_fit, _downsample_series

FS = 8000


def sine(duration=1.0, freq=200.0, amp=0.4, fs=FS):
    t = np.arange(int(fs * duration)) / fs
    return t, amp * np.sin(2 * np.pi * freq * t)


def test_trim_range_keeps_requested_window():
    t, x = sine(1.0)
    stereo = np.stack([x, x], axis=1)
    mask = np.ones_like(stereo, dtype=bool)
    result = trim_range(stereo, mask, FS, 0.25, 0.75)
    assert result.kept_samples == int(0.5 * FS)
    assert result.start_sample == int(0.25 * FS)
    assert result.end_sample == int(0.75 * FS)
    assert np.allclose(result.samples, stereo[result.start_sample:result.end_sample])
    # 原始数组不能被修改
    assert stereo.shape[0] == FS


def test_trim_range_rejects_degenerate_window():
    _, x = sine(1.0)
    data = x[:, None]
    mask = np.ones_like(data, dtype=bool)
    with pytest.raises(ValueError):
        trim_range(data, mask, FS, 0.5, 0.50001)


def test_trim_range_clamps_out_of_bounds():
    _, x = sine(1.0)
    data = x[:, None]
    mask = np.ones_like(data, dtype=bool)
    result = trim_range(data, mask, FS, -1.0, 99.0)
    assert result.start_sample == 0
    assert result.end_sample == FS


def test_backup_path_is_unique(tmp_path):
    source = tmp_path / "s.wav"
    write_wav(source, np.zeros((100, 1)), FS)
    first = backup_path_for(source)
    first.write_bytes(b"x")
    second = backup_path_for(source)
    assert first != second
    assert second.name.startswith("s.bak-")


def test_apply_to_source_writes_backup_and_data(tmp_path):
    t, x = sine(1.0)
    source = tmp_path / "s.wav"
    write_wav(source, x, FS, subtype="PCM_16")
    original = read_wav(source)

    trimmed = original.samples[: FS // 2]
    backup = apply_to_source(source, trimmed, FS, original.subtype)

    assert backup.is_file()
    assert read_wav(backup).samples.shape[0] == original.samples.shape[0]
    assert read_wav(source).samples.shape[0] == FS // 2


def test_apply_to_source_rejects_nonfinite(tmp_path):
    _, x = sine(0.2)
    source = tmp_path / "s.wav"
    write_wav(source, x, FS)
    bad = x.copy()
    bad[3] = np.nan
    with pytest.raises(ValueError):
        apply_to_source(source, bad, FS)
    # 失败时不得留下备份残骸覆盖源文件
    assert read_wav(source).samples.shape[0] == len(x)


def test_downsample_preserves_extremes():
    x = np.zeros(100_000)
    x[1_234] = 0.9
    x[98_765] = -0.8
    times, values = _downsample_series(x, FS, 500)
    assert len(values) <= 1000
    assert values.max() == pytest.approx(0.9)
    assert values.min() == pytest.approx(-0.8)
    # 时间轴必须覆盖整个数据范围
    assert times[0] == pytest.approx(0.0)
    assert times[-1] == pytest.approx((len(x) - 1) / FS)


def test_downsample_keeps_short_signal_intact():
    _, x = sine(0.01)
    times, values = _downsample_series(x, FS, 5000)
    assert len(values) == len(x)
    assert np.array_equal(values, x)


def test_hilbert_padding_stays_close_to_direct_transform():
    """长信号走 next_fast_len 补零，必须与直接变换在主体区间一致。"""
    n = SHORT_SIGNAL_LIMIT + 48_577
    t = np.arange(n) / FS
    x = 0.4 * np.sin(2 * np.pi * 300 * t)
    fast = hilbert_envelope(x)
    direct = np.abs(__import__("scipy.signal", fromlist=["hilbert"]).hilbert(x))
    core = slice(n // 10, n * 9 // 10)
    relative = np.abs(fast[core] - direct[core]) / np.maximum(direct[core], 1e-9)
    assert float(np.max(relative)) < 0.01


def test_short_signal_uses_direct_transform():
    _, x = sine(0.5)
    assert np.allclose(hilbert_envelope(x), np.abs(
        __import__("scipy.signal", fromlist=["hilbert"]).hilbert(x)))


def test_envelope_fit_only_covers_selection():
    _, x = sine(4.0, amp=0.5)
    mask = np.ones(len(x), dtype=bool)
    payload = _compute_envelope_fit(x, mask, FS, 1.0, 2.0, "constant")
    fit = payload["fit"]
    assert 0.48 <= fit.parameters["a"] <= 0.52
    assert fit.start_time >= 1.0
    assert fit.end_time <= 2.0
    # 只计算选区附近（含 0.5 s 余量），不应把整段数据都搬进内存
    assert len(payload["envelope"]) < len(x)
    assert MAX_PAD_RATIO >= 1.0


def test_envelope_fit_rejects_empty_selection():
    _, x = sine(0.5)
    mask = np.zeros(len(x), dtype=bool)
    with pytest.raises(ValueError):
        _compute_envelope_fit(x, mask, FS, 0.1, 0.2, "auto")
