"""大文件链路回归测试：分块冲击检测、进度回调、撤销栈上限、统计量一致性。"""
import numpy as np
import pytest
from scipy import ndimage, signal
from scipy.interpolate import CubicSpline

from core import denoise as denoise_module
from core.denoise import detect_and_repair_impulses
from core.statistics import interval_statistics

FS = 8000


def _legacy_detect(samples, sample_rate, threshold=8.0, padding_ms=0.25,
                   merge_gap_ms=20.0, max_repair_ms=3.0):
    """旧整段实现，作为分块版本的等价性参照。"""
    def robust_scale(values):
        median = float(np.median(values))
        deviations = np.abs(values - median)
        return max(1.4826 * float(np.median(deviations)),
                   float(np.quantile(deviations, 0.95)), 1e-12)

    x = np.asarray(samples, dtype=np.float64).reshape(-1)
    residual = x - signal.medfilt(x, kernel_size=5)
    derivative = np.diff(x, prepend=x[0])
    candidates = (np.abs(residual) > threshold * robust_scale(residual)) | (
        np.abs(derivative) > threshold * robust_scale(derivative))
    padding = max(1, round(padding_ms * sample_rate / 1000))
    candidates = ndimage.binary_dilation(candidates, iterations=padding)
    padded = np.concatenate(([False], candidates, [False])).astype(np.int8)
    changes = np.diff(padded)
    starts, ends = np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
    gap = max(0, round(merge_gap_ms * sample_rate / 1000))
    regions = []
    for start, end in zip(starts.tolist(), ends.tolist()):
        if regions and start - regions[-1][1] <= gap:
            regions[-1] = (regions[-1][0], end)
        else:
            regions.append((start, end))
    cleaned = x.copy()
    mask = np.ones(len(x), dtype=bool)
    limit = max(1, round(max_repair_ms * sample_rate / 1000))
    for start, end in regions:
        if end - start <= limit and start > 0 and end < len(x):
            anchors = np.concatenate(
                (np.arange(max(0, start - 8), start), np.arange(end, min(len(x), end + 8))))
            cleaned[start:end] = CubicSpline(anchors, cleaned[anchors])(np.arange(start, end))
        else:
            mask[start:end] = False
    return cleaned, mask, regions


@pytest.fixture(scope="module")
def chunked_signal():
    """长度跨过内部分块边界（BLOCK_SAMPLES）的信号，用于验证分块无缝。"""
    total = denoise_module.BLOCK_SAMPLES + 5000
    t = np.arange(total) / FS
    x = 0.4 * np.sin(2 * np.pi * 500 * t)
    x[denoise_module.BLOCK_SAMPLES - 2] += 0.9
    x[denoise_module.BLOCK_SAMPLES + 7] -= 0.85
    x[1000] += 0.9
    x[total - 10] -= 0.8
    return x


def test_chunked_detection_matches_whole_array(chunked_signal):
    reference_clean, reference_mask, reference_regions = _legacy_detect(chunked_signal, FS)
    result = detect_and_repair_impulses(chunked_signal, FS)

    assert [(e.start_sample, e.end_sample) for e in result.events] == reference_regions
    assert np.array_equal(result.valid_mask, reference_mask)
    assert float(np.max(np.abs(result.cleaned - reference_clean))) < 1e-12


def test_progress_callback_reports_monotonic_fraction():
    t = np.arange(FS * 5) / FS
    x = 0.4 * np.sin(2 * np.pi * 300 * t)
    x[8000] += 0.9
    seen = []
    detect_and_repair_impulses(x, FS, progress=lambda fraction, message: seen.append(fraction))
    assert seen, "应至少回调一次进度"
    assert seen[-1] == pytest.approx(1.0)
    assert all(b >= a for a, b in zip(seen, seen[1:])), f"进度必须单调不减：{seen}"


def test_scale_sampling_is_capped_for_huge_inputs():
    """稳健尺度抽样上限生效，避免全长 partition 长时间占用 GIL。"""
    values = np.arange(200_000, dtype=np.float64)
    sampled = denoise_module._subsample(values, limit=50_000)
    assert sampled.size <= 50_001
    assert denoise_module._subsample(values[:10], limit=50_000).size == 10


def test_interval_statistics_matches_direct_numpy():
    rng = np.random.default_rng(3)
    x = rng.standard_normal(50_000) * 0.2
    mask = np.ones(x.size, dtype=bool)
    mask[1000:1200] = False
    stats = interval_statistics(x, FS, 0.0, x.size / FS, mask)
    selected = x[mask]
    assert stats["samples"] == selected.size
    assert stats["rms"] == pytest.approx(np.sqrt(np.mean(selected ** 2)), rel=1e-12)
    assert stats["std"] == pytest.approx(np.std(selected), rel=1e-12)
    assert stats["mean"] == pytest.approx(np.mean(selected), rel=1e-12)
    assert stats["peak_amplitude"] == pytest.approx(np.max(np.abs(selected)), rel=1e-12)


def test_interval_statistics_handles_fully_valid_mask_without_copy():
    x = np.linspace(-0.5, 0.5, 20_000)
    stats = interval_statistics(x, FS, 0.0, x.size / FS, np.ones(x.size, dtype=bool))
    assert stats["excluded_samples"] == 0
    assert stats["peak_amplitude"] == pytest.approx(0.5, rel=1e-12)
    assert stats["rms"] == pytest.approx(np.sqrt(np.mean(x ** 2)), rel=1e-12)


def test_undo_stack_is_capped_by_levels():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.main_window import MAX_UNDO_LEVELS, MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.processed = np.zeros((100, 1))
    window.valid_mask = np.ones((100, 1), dtype=bool)
    window.reference = np.zeros((100, 1))
    for _ in range(MAX_UNDO_LEVELS + 5):
        window._push_undo()
    assert len(window.undo_stack) == MAX_UNDO_LEVELS
    window.deleteLater()
    app.processEvents()
