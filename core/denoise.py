"""冲击检测与去噪。

大文件（千万级采样点）下的实现约束：
1. 分块处理，任意时刻只保留一个块的浮点临时数组，避免全长度副本叠加导致内存爆掉；
2. 稳健尺度用等间隔抽样估计（抽样上限 200 万点），既保持稳健性统计意义，
   又避免对 4000 万点连续做 partition 而长时间占用 GIL、卡住界面动画；
3. 所有中间结果只保留 bool 掩码与 float32 残差，峰值内存约为采样点数的 5 字节/点。
"""
from __future__ import annotations

from core.i18n import tf, tr
from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy import ndimage
from scipy.interpolate import CubicSpline

MEDIAN_KERNEL = 5
BLOCK_SAMPLES = 1 << 21  # 每块约 210 万点
SCALE_SAMPLE_LIMIT = 1 << 21  # 稳健尺度抽样上限

ProgressHook = Callable[[float, str], None]


@dataclass
class ImpulseEvent:
    start_sample: int
    end_sample: int
    repaired: bool
    peak_deviation: float

    @property
    def length(self) -> int:
        return self.end_sample - self.start_sample

    def as_dict(self, sample_rate: int) -> dict[str, float | int | bool]:
        return {
            "start_sample": self.start_sample,
            "end_sample": self.end_sample,
            "start_s": self.start_sample / sample_rate,
            "end_s": self.end_sample / sample_rate,
            "duration_ms": self.length / sample_rate * 1000,
            "repaired": self.repaired,
            "peak_deviation": self.peak_deviation,
        }


@dataclass
class DenoiseResult:
    cleaned: np.ndarray
    events: list[ImpulseEvent]
    valid_mask: np.ndarray
    threshold: float
    scale_samples: int = 0

    @property
    def repaired_count(self) -> int:
        return sum(event.repaired for event in self.events)

    @property
    def excluded_count(self) -> int:
        return len(self.events) - self.repaired_count


def _robust_scale(values: np.ndarray) -> float:
    data = np.asarray(values, dtype=np.float64).reshape(-1)
    if data.size == 0:
        return 1e-12
    median = float(np.median(data))
    deviations = np.abs(data - median)
    mad_scale = 1.4826 * float(np.median(deviations))
    # 中值滤波对高频正弦在峰谷处存在系统性残差，MAD 可能为零；
    # 加入高分位数尺度，避免把每个正常峰谷误判为冲击。
    quantile_scale = float(np.quantile(deviations, 0.95))
    scale = max(mad_scale, quantile_scale)
    # 相对判据：分位数尺度若比数据自身幅度小六个数量级以上，说明它是浮点舍入
    # 噪声而不是真实离散度（稳态纯音上 5 点中值滤波几乎逐点复现波形，
    # 残差只剩极少数非零点 + 一堆 1e-14 量级的舍入值）。此时尺度失效，
    # 任何正常残差都会被判成数亿倍离群，整段数据被误标为无效。
    reference = float(np.max(deviations)) if deviations.size else 0.0
    if reference > 0.0 and scale <= 1e-6 * reference:
        significant = deviations[deviations > 1e-6 * reference]
        if significant.size >= 16:
            scale = max(scale, float(np.quantile(significant, 0.95)))
    return max(scale, 1e-12)


def _subsample(values: np.ndarray, limit: int = SCALE_SAMPLE_LIMIT) -> np.ndarray:
    """等间隔抽样：n 不超过 limit 时原样返回，否则按 stride 取点。"""
    total = values.size
    if total <= limit or limit <= 0:
        return values
    stride = int(np.ceil(total / limit))
    return values[::stride]


def _regions(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """把布尔掩码转成 (起始索引, 结束索引) 数组，半开区间。"""
    padded = np.zeros(mask.size + 2, dtype=np.int8)
    padded[1:-1] = mask
    changes = np.diff(padded)
    return np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)


def _merge_regions(starts: np.ndarray, ends: np.ndarray, max_gap: int) -> tuple[np.ndarray, np.ndarray]:
    """合并间距不超过 max_gap 的相邻区段（向量化，不逐个 Python 循环）。"""
    if starts.size <= 1:
        return starts, ends
    breaks = np.flatnonzero(starts[1:] - ends[:-1] > max_gap)
    if breaks.size == 0:
        return starts[:1], ends[-1:]
    merged_starts = np.concatenate((starts[:1], starts[breaks + 1]))
    merged_ends = np.concatenate((ends[breaks], ends[-1:]))
    return merged_starts, merged_ends


def _detect_mask(
    x: np.ndarray,
    threshold: float,
    block: int,
    progress: ProgressHook | None,
) -> tuple[np.ndarray, np.ndarray, int]:
    """分块计算残差与导数，返回 (候选掩码, float32 残差, 抽样的尺度点数)。"""
    total = x.size
    halo = MEDIAN_KERNEL // 2
    candidates = np.zeros(total, dtype=bool)

    # 第一遍：残差（float32 常驻）与抽样尺度
    residual = np.empty(total, dtype=np.float32)
    scale_values: list[np.ndarray] = []
    take = max(1, SCALE_SAMPLE_LIMIT // max(1, int(np.ceil(total / block))))
    for start in range(0, total, block):
        stop = min(total, start + block)
        low = max(0, start - halo)
        high = min(total, stop + halo)
        baseline = ndimage.median_filter(x[low:high], size=MEDIAN_KERNEL, mode="constant", cval=0.0)
        offset = start - low
        block_residual = x[start:stop] - baseline[offset:offset + (stop - start)]
        residual[start:stop] = block_residual
        scale_values.append(_subsample(block_residual, take))
        if progress is not None:
            progress(0.45 * stop / total, tf('计算局部基线 {stop:,}/{total:,} 点', stop=(stop), total=(total)))
        del baseline, block_residual

    scale_residual = np.concatenate(scale_values) if len(scale_values) > 1 else scale_values[0]
    scale_count = int(scale_residual.size)
    scale_r = _robust_scale(scale_residual)
    # 稳态纯音（本程序的主要数据形态）上，5 点中值滤波对单调段是逐点精确复现：
    # 残差在约 95% 的点上恰好为 0，只在每个周期的峰谷留下曲率量级的凸起
    # （约 A(πf/fs)²/2）。这种“零膨胀”分布会把残差的稳健尺度压到量化噪声
    # 级别，于是正常背景噪声的起伏也会被当成 36 倍离群，整段数据被标为无效。
    # 因此给残差尺度设一个与信号电平挂钩的下限：低于电平 2% 的偏离不判为冲击。
    level = float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0
    scale_r = max(scale_r, 0.02 * level)

    # 第二遍：导数尺度 + 候选判定
    scale_derivative = _derivative_scale(x, block, take)
    for start in range(0, total, block):
        stop = min(total, start + block)
        prepend = x[start] if start == 0 else x[start - 1]
        derivative = np.diff(x[start:stop], prepend=prepend)
        hit = np.abs(derivative) > threshold * scale_derivative
        del derivative
        hit |= np.abs(residual[start:stop]) > np.float32(threshold * scale_r)
        candidates[start:stop] = hit
        if progress is not None:
            progress(0.45 + 0.25 * stop / total, tf('标记冲击候选 {stop:,}/{total:,} 点', stop=(stop), total=(total)))
    del scale_values, scale_residual
    return candidates, residual, scale_count


def _derivative_scale(x: np.ndarray, block: int, take: int) -> float:
    samples: list[np.ndarray] = []
    total = x.size
    for start in range(0, total, block):
        stop = min(total, start + block)
        prepend = x[start] if start == 0 else x[start - 1]
        samples.append(_subsample(np.diff(x[start:stop], prepend=prepend), take))
    combined = np.concatenate(samples) if len(samples) > 1 else samples[0]
    return _robust_scale(combined)


def detect_and_repair_impulses(
    samples: np.ndarray,
    sample_rate: int,
    threshold: float = 8.0,
    padding_ms: float = 0.25,
    merge_gap_ms: float = 20.0,
    max_repair_ms: float = 3.0,
    progress: ProgressHook | None = None,
) -> DenoiseResult:
    x = np.asarray(samples, dtype=np.float64).reshape(-1)
    if len(x) < 9 or sample_rate <= 0:
        raise ValueError(tr("冲击检测至少需要 9 个采样点和正采样率"))
    if threshold <= 0:
        raise ValueError(tr("检测阈值必须为正数"))
    if not np.isfinite(x).all():
        raise ValueError(tr("冲击检测输入包含 NaN 或无穷值"))

    if progress is not None:
        progress(0.02, tr("开始冲击检测"))

    candidates, residual, scale_count = _detect_mask(x, threshold, BLOCK_SAMPLES, progress)

    padding = max(1, round(padding_ms * sample_rate / 1000))
    if progress is not None:
        progress(0.72, tr("扩展冲击区间"))
    dilated = ndimage.maximum_filter1d(
        candidates.view(np.uint8), size=2 * padding + 1, mode="constant", cval=0
    )
    del candidates
    starts, ends = _regions(dilated > 0)
    del dilated
    starts, ends = _merge_regions(
        starts, ends, max(0, round(merge_gap_ms * sample_rate / 1000)))

    cleaned = x.copy()
    valid_mask = np.ones(x.size, dtype=bool)
    events: list[ImpulseEvent] = []
    max_repair_samples = max(1, round(max_repair_ms * sample_rate / 1000))
    total_regions = int(starts.size)
    report_every = max(1, total_regions // 20)

    for index in range(total_regions):
        start = int(starts[index])
        end = int(ends[index])
        length = end - start
        repairable = length <= max_repair_samples and start > 0 and end < x.size
        if repairable:
            left = np.arange(max(0, start - 8), start)
            right = np.arange(end, min(x.size, end + 8))
            anchors = np.concatenate((left, right))
            if len(anchors) >= 4:
                interpolator = CubicSpline(anchors, cleaned[anchors])
                cleaned[start:end] = interpolator(np.arange(start, end))
            else:
                cleaned[start:end] = np.interp(
                    np.arange(start, end), [start - 1, end], [cleaned[start - 1], cleaned[end]]
                )
        else:
            valid_mask[start:end] = False
        events.append(
            ImpulseEvent(
                start, end, repairable,
                float(np.max(np.abs(residual[start:end]))),
            )
        )
        if progress is not None and index % report_every == 0:
            progress(0.78 + 0.2 * index / total_regions, tf('修复区段 {index}/{total_regions}', index=(index), total_regions=(total_regions)))

    if progress is not None:
        progress(1.0, tr("冲击检测完成"))
    return DenoiseResult(cleaned, events, valid_mask, float(threshold), scale_count)
