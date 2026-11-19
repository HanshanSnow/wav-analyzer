from __future__ import annotations

from core.i18n import tf, tr
from dataclasses import dataclass
import warnings

import numpy as np
from scipy import fft as sfft
from scipy import optimize, signal


@dataclass
class EnvelopeFit:
    model: str
    equation: str
    parameters: dict[str, float]
    fitted: np.ndarray
    r_squared: float
    rmse: float
    start_time: float
    end_time: float


# 低于该长度的信号不启用补零，保证短样本逐点等价于直接调用 hilbert。
SHORT_SIGNAL_LIMIT = 1_000_000
# 允许的最大补零比例，用于把 FFT 边界效应限制在末尾极小区间。
MAX_PAD_RATIO = 1.02


def hilbert_envelope(values: np.ndarray) -> np.ndarray:
    """Hilbert 包络；仅在补零比例极小且信号足够长时启用 FFT 友好长度。

    背景：非 2 的幂长度会让 scipy 走混合基算法，4487 万采样点要 14 秒。
    补零到 next_fast_len 后约 3 秒，代价是末尾极小比例的点受补零边界影响。
    因此这里加了两道限制：
      - 信号长度超过 SHORT_SIGNAL_LIMIT 才考虑补零，短信号保持逐点等价；
      - 补零比例不超过 2%，把边界影响压缩到末尾极小区间。
    """
    n = len(values)
    if n == 0:
        return np.empty(0, dtype=np.float64)
    if n > SHORT_SIGNAL_LIMIT:
        fast = sfft.next_fast_len(n, real=True)
        if fast <= int(n * MAX_PAD_RATIO):
            return np.abs(signal.hilbert(values, N=fast)[:n])
    return np.abs(signal.hilbert(values))


def compute_envelope(samples: np.ndarray, sample_rate: int, method: str = "hilbert", rms_window_ms: float = 20.0) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(samples, dtype=np.float64).reshape(-1)
    if len(x) < 2 or sample_rate <= 0:
        raise ValueError(tr("包络分析数据过短或采样率无效"))
    if not np.isfinite(x).all():
        raise ValueError(tr("包络分析输入包含 NaN 或无穷值"))
    centered = x - np.mean(x)
    if method == "hilbert":
        envelope = hilbert_envelope(centered)
    elif method == "rms":
        window = max(1, round(rms_window_ms * sample_rate / 1000))
        envelope = np.sqrt(np.convolve(centered ** 2, np.ones(window) / window, mode="same"))
    else:
        raise ValueError(tf('未知包络方法：{method}', method=(method)))
    return np.arange(len(x)) / sample_rate, envelope


def fit_envelope(times: np.ndarray, envelope: np.ndarray, model: str = "auto") -> EnvelopeFit:
    t = np.asarray(times, dtype=np.float64).reshape(-1)
    y = np.asarray(envelope, dtype=np.float64).reshape(-1)
    if len(t) != len(y) or len(t) < 2:
        raise ValueError(tr("包络拟合的时间和幅值数组长度必须一致且至少为 2"))
    finite = np.isfinite(t) & np.isfinite(y)
    t, y = t[finite], y[finite]
    if len(t) < 2:
        raise ValueError(tr("包络拟合没有足够的有效数据"))
    relative_t = t - t[0]
    models = ["constant", "linear", "exponential"] if model == "auto" else [model]
    fits = [_fit_one(relative_t, y, name) for name in models]
    best = min(fits, key=lambda item: item.rmse)
    if model == "auto":
        # 简单模型误差与最优模型相差不足 1% 时，优先简单模型，避免稳态过拟合。
        for candidate in fits:
            if candidate.rmse <= best.rmse * 1.01 + 1e-12:
                best = candidate
                break
    best.start_time = float(t[0])
    best.end_time = float(t[-1])
    best.equation = best.equation.replace("T", f"(t - {t[0]:.6g})")
    return best


def _fit_one(t: np.ndarray, y: np.ndarray, model: str) -> EnvelopeFit:
    if model == "constant":
        value = float(np.mean(y))
        fitted = np.full_like(y, value)
        parameters = {"a": value}
        equation = "A(t) = a"
    elif model == "linear":
        slope, intercept = np.polyfit(t, y, 1)
        fitted = intercept + slope * t
        parameters = {"a": float(intercept), "b": float(slope)}
        equation = "A(t) = a + b·T"
    elif model == "exponential":
        def function(time: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
            return a * np.exp(np.clip(b * time, -700, 700)) + c

        initial = [max(float(y[0] - y[-1]), 1e-9), -1.0 / max(t[-1], 1e-6), float(y[-1])]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", optimize.OptimizeWarning)
                popt, _ = optimize.curve_fit(function, t, y, p0=initial, maxfev=20000)
            fitted = function(t, *popt)
            parameters = {"a": float(popt[0]), "b": float(popt[1]), "c": float(popt[2])}
            equation = "A(t) = a·exp(b·T) + c"
        except (RuntimeError, ValueError) as exc:
            raise ValueError(tf('指数包络拟合失败：{exc}', exc=(exc))) from exc
    else:
        raise ValueError(tf('不支持的包络模型：{model}', model=(model)))
    residual = y - fitted
    rmse = float(np.sqrt(np.mean(residual ** 2)))
    total = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1.0 if total < 1e-24 and rmse < 1e-12 else (0.0 if total < 1e-24 else 1 - float(np.sum(residual ** 2)) / total)
    return EnvelopeFit(model, equation, parameters, fitted, float(r_squared), rmse, 0.0, 0.0)
