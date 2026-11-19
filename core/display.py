"""显示用序列抽稀。

千万级采样点直接交给绘图库会拖慢重绘，也会让 PNG 导出耗时到十几秒。
这里统一用「按列 min/max」抽稀：每列保留最小值和最大值两个点，峰谷不会被抹平，
时间坐标仍是真实采样时间，因此抽稀只影响绘制，不影响任何数值计算。
"""

from __future__ import annotations

import numpy as np


def min_max_indices(values: np.ndarray, columns: int) -> np.ndarray:
    """返回按列 min/max 抽稀后的采样点索引（长度约为 2×columns）。"""
    data = np.asarray(values).reshape(-1)
    total = len(data)
    columns = max(2, int(columns))
    if total <= columns * 2:
        return np.arange(total)

    per = total // columns
    usable = per * columns
    block = data[:usable].reshape(columns, per)
    rows = np.arange(columns)
    idx = np.empty(columns * 2, dtype=np.int64)
    idx[0::2] = rows * per + block.argmin(axis=1)
    idx[1::2] = rows * per + block.argmax(axis=1)
    if usable < total:
        # 尾部不足一列，把极值并入最后两点，避免末尾被截断。
        tail = data[usable:]
        idx[-2] = usable + int(np.argmin(tail))
        idx[-1] = usable + int(np.argmax(tail))
    idx[0] = 0
    return idx


def min_max_downsample(
    values: np.ndarray,
    sample_rate: int,
    columns: int,
    start_time: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """按列做 min/max 抽稀，返回用于绘制的 (时间, 幅值)。"""
    data = np.asarray(values, dtype=np.float64).reshape(-1)
    total = len(data)
    if total == 0:
        return np.empty(0), np.empty(0)
    columns = max(2, int(columns))
    if total <= columns * 2:
        return start_time + np.arange(total) / sample_rate, data

    idx = min_max_indices(data, columns)
    times = start_time + idx / sample_rate
    # 首末点对齐真实时间范围，曲线始终覆盖完整区间。
    times[0] = start_time
    times[-1] = start_time + (total - 1) / sample_rate
    return times, data[idx]


def thin_xy(
    values: np.ndarray,
    times: np.ndarray,
    max_points: int,
) -> tuple[np.ndarray, np.ndarray]:
    """对任意 x 轴的序列做 min/max 抽稀，用于导出时限制绘制点数。"""
    v = np.asarray(values, dtype=np.float64).reshape(-1)
    t = np.asarray(times, dtype=np.float64).reshape(-1)
    if len(v) != len(t):
        raise ValueError("横纵轴长度不一致")
    if len(v) <= max(4, int(max_points)):
        return t, v
    idx = min_max_indices(v, max(2, int(max_points) // 2))
    return t[idx], v[idx]
