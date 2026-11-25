"""降噪工具组：六种离线方法、统一诊断量、统一护栏。

设计取舍见 `PlanForVersion2.0.md` §3.3。三条必须守住的原则：

1. **默认不改变数据**——本模块只算，不写任何全局状态；调用方（界面/批量）拿到
   `Outcome` 后必须由人确认才把 `cleaned` 写回处理版本。
2. **方法即假设**——每种方法都有前提（参考路是否可含信号、是否需要噪声段）。
   前提不满足时返回 `blocked` 而不是给出更差的数。
3. **诊断同源**——所有方法都输出同一组量（ERLE、相干、泄漏估计、ΔA、ΔL_sys、u_c），
   报告与手册引用同一套公式，`tests/test_anc.py` 用解析式复算，防止实现与手册漂移。

符号（与手册一致）：`d(n)` 目标通道，`x(n)` 参考通道，`h` 传递滤波器，
`N` 阶数，`M` 训练样本数，`λ` 正则系数，`γ²` 幅值平方相干。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
from scipy import linalg as sla
from scipy import signal as sps

from core.i18n import tf, tr

# ---------------------------------------------------------------- 常量
# 阶数与正则：与手册 §3.3.4(c) 的数值必须一致。
DEFAULT_ORDER = 2048
DEFAULT_LAMBDA_RATIO = 1e-5
# 噪声段自动检测窗口与平稳性判据。
NOISE_WINDOW_SECONDS = 1.0
NOISE_BLOCK_SECONDS = 0.05
NOISE_FLATNESS_LIMIT = 0.15
# 分块自适应：块长与遗忘因子。
BLOCK_SECONDS = 10.0
FORGETTING = 0.995
# 陷波默认值。
DEFAULT_NOTCH_FREQUENCY = 50.0
DEFAULT_NOTCH_Q = 30.0
DEFAULT_HARMONICS = 3
# 护栏阈值（手册 §3.3.5 引用同一组常量）。
MIN_ERLE_HOLDOUT_DB = 6.0
MAX_ABS_DELTA_LEVEL_DB = 0.5
MAX_COHERENCE_XD = 0.9
MAX_LEAK_COHERENCE = 0.11
SAMPLES_PER_TAP = 8
MIN_AVERAGES = 4
MAX_ABS_TSA_LOSS_DB = 0.5
# TSA 抖动衰减系数：ΔL = −171.5·f0²·σ_t²（dB，σ_t 单位 s）。
TSA_LOSS_FACTOR = 171.5


@dataclass(frozen=True)
class MethodSpec:
    method_id: str
    label: str
    premise: str
    needs_noise: bool
    reference_may_carry_signal: bool
    tracks_slow_drift: bool
    suitable: str


# 顺序即界面顺序：先安全（不改幅值/窄带），再需要假设的抵消类。
METHOD_SPECS: tuple[MethodSpec, ...] = (
    MethodSpec(
        "sync_avg", tr("同步平均（触发对齐）"),
        tr("需重复激励与稳定触发，无需参考通道"),
        False, False, False, tr("共振/拍频/衰减率等重复测量"),
    ),
    MethodSpec(
        "notch", tr("窄带陷波（零相位）"),
        tr("干扰必须是窄带：工频及其谐波"),
        False, False, False, tr("50/100 Hz 哼声、单频干扰"),
    ),
    MethodSpec(
        "ls_frozen", tr("冻结两段式正则化最小二乘"),
        tr("需有噪声段；参考可含少量信号"),
        True, True, False, tr("默认：双声道、开头有静音"),
    ),
    MethodSpec(
        "wiener_clean", tr("干净参考路 Wiener 抵消"),
        tr("参考路不含信号"),
        False, False, False, tr("参考麦独立拾取环境噪声"),
    ),
    MethodSpec(
        "ls_block", tr("噪声段训练的分块自适应抵消"),
        tr("需噪声段；噪声缓变"),
        True, True, True, tr("长录音、风机转速变化"),
    ),
    MethodSpec(
        "wiener_spectral", tr("平稳噪声频域 Wiener 抵消"),
        tr("噪声平稳，且参考路不含信号"),
        False, False, False, tr("长混响、平稳底噪"),
    ),
    MethodSpec(
        "noise_profile", tr("独立噪声画像（谱减）"),
        tr("参考是单独录的一段平稳噪声，不要求与目标对齐"),
        False, False, False, tr("两次录音、不同采样时钟、参考比目标长/短"),
    ),
)

METHOD_IDS = tuple(spec.method_id for spec in METHOD_SPECS)

# 方法 id → 显示名（报告、批量 CSV 用）。
METHOD_LABELS = {spec.method_id: spec.label for spec in METHOD_SPECS}


@dataclass
class Diagnostics:
    """一次降噪的全部可解释量；`blocked` 非空表示拒绝应用。"""

    method: str
    f0: float | None = None
    erle_db: float | None = None
    erle_holdout_db: float | None = None
    coherence_xd: float | None = None
    leak_coherence: float | None = None
    delta_level_db: float | None = None
    delta_sys_db: float | None = None
    delta_phase_rad: float | None = None
    u_c_db: float | None = None
    noise_span: tuple[float, float] | None = None
    order: int = 0
    samples_trained: int = 0
    averages: int = 0
    block_erle: list[float] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    blocked: str | None = None
    # 独立噪声画像（noise_profile）专用：平稳性、主频处噪声占比、平均增益
    stationarity_db: float | None = None
    noise_at_f0: float | None = None
    mean_gain: float | None = None

    def as_row(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "erle_db": self.erle_db,
            "erle_holdout_db": self.erle_holdout_db,
            "coherence_xd": self.coherence_xd,
            "leak_coherence": self.leak_coherence,
            "delta_level_db": self.delta_level_db,
            "delta_sys_db": self.delta_sys_db,
            "u_c_db": self.u_c_db,
        }


@dataclass
class Outcome:
    cleaned: np.ndarray | None
    diagnostics: Diagnostics

    @property
    def applied(self) -> bool:
        return self.cleaned is not None and self.diagnostics.blocked is None


# ---------------------------------------------------------------- 基础量
def erle_db(target: np.ndarray, cleaned: np.ndarray) -> float:
    """回声/噪声抑制量：10log10(P_d/P_e)。"""
    power_d = float(np.mean(np.square(target, dtype=np.float64)))
    power_e = float(np.mean(np.square(cleaned, dtype=np.float64)))
    if power_e <= 0:
        return float("inf")
    return 10.0 * np.log10(max(power_d, 1e-300) / power_e)


def delta_sys_db(leak: float) -> float:
    """信号系统偏差：ΔL_sys = 10log10(1−γ̂_s²)，等价于幅值乘 √(1−γ̂_s²)。"""
    return 10.0 * np.log10(max(1.0 - float(leak), 1e-12))


def delta_phase_rad(leak: float) -> float:
    """相位影响上界 |Δφ| ≤ arcsin γ_s。"""
    return float(np.arcsin(np.sqrt(min(max(float(leak), 0.0), 1.0))))


def combined_u(delta_sys: float | None, averages: int) -> float | None:
    """合成标准不确定度 u_c = √(ΔL_sys² + u_rand²)，u_rand ≈ 20log10(1+1/√M_eff)。"""
    parts: list[float] = []
    if delta_sys is not None:
        parts.append(float(delta_sys) ** 2)
    if averages > 0:
        u_rand = 20.0 * np.log10(1.0 + 1.0 / np.sqrt(averages))
        parts.append(float(u_rand) ** 2)
    if not parts:
        return None
    return float(np.sqrt(sum(parts)))


def tsa_loss_db(f0: float | None, sigma_t: float | None) -> float:
    """同步平均的抖动衰减：ΔL_TSA = −171.5·f0²·σ_t²（dB）。"""
    if not f0 or not sigma_t:
        return 0.0
    return -TSA_LOSS_FACTOR * float(f0) ** 2 * float(sigma_t) ** 2


def notch_gain_db(frequency: float, notch_frequency: float, q: float) -> float:
    """陷波器在 frequency 处的增益（dB），解析式 |H|² = 1/(1+(fn/(2Q|f−fn|))²)。"""
    offset = abs(float(frequency) - float(notch_frequency))
    if offset <= 0:
        return -np.inf
    ratio = float(notch_frequency) / (2.0 * float(q) * offset)
    return float(-10.0 * np.log10(1.0 + ratio ** 2))


def tone_amplitude(sig: np.ndarray, sample_rate: int, frequency: float) -> float:
    """单频幅值估计：Hann 窗 + 相干增益补偿的单 bin DFT（不要求整周期）。"""
    size = int(len(sig))
    if size < 8 or not frequency:
        return 0.0
    index = np.arange(size, dtype=np.float64)
    window = sps.get_window("hann", size, fftbins=True)
    basis = window * np.exp(-2j * np.pi * float(frequency) * index / sample_rate)
    return float(2.0 * np.abs(np.dot(np.asarray(sig, dtype=np.float64), basis))
                 / float(np.sum(window)))


def coherence_profile(ref: np.ndarray, target: np.ndarray, sample_rate: int,
                      nperseg: int = 4096) -> tuple[np.ndarray, np.ndarray]:
    """Welch 互谱估幅值平方相干 γ²(f)。"""
    limit = min(int(nperseg), len(ref), len(target))
    if limit < 64:
        return np.zeros(1), np.zeros(1)
    nperseg = int(limit)
    noverlap = nperseg // 2
    _, sxx = sps.welch(ref, fs=sample_rate, nperseg=nperseg, noverlap=noverlap,
                       detrend=False)
    _, sdd = sps.welch(target, fs=sample_rate, nperseg=nperseg, noverlap=noverlap,
                       detrend=False)
    freqs, sxd = sps.csd(ref, target, fs=sample_rate, nperseg=nperseg,
                         noverlap=noverlap, detrend=False)
    gamma = np.abs(sxd) ** 2 / (np.abs(sxx) * np.abs(sdd) + 1e-30)
    return freqs, np.clip(gamma, 0.0, 1.0)


def coherence_at(freqs: np.ndarray, gamma: np.ndarray, frequency: float) -> float | None:
    if not frequency or freqs.size < 2:
        return None
    return float(np.interp(float(frequency), freqs, gamma))


def estimate_lag(ref: np.ndarray, target: np.ndarray, sample_rate: int,
                 max_lag_seconds: float = 0.05) -> float:
    """GCC-PHAT 估计 ref 领先 target 的时延（秒，正数表示 ref 更早）。"""
    if len(ref) < 64 or len(target) < 64:
        return 0.0
    size = 1 << int(np.ceil(np.log2(len(ref) + len(target))))
    spectrum_r = np.fft.rfft(ref, size)
    spectrum_t = np.fft.rfft(target, size)
    cross = spectrum_r * np.conj(spectrum_t)
    cross /= np.abs(cross) + 1e-12
    correlation = np.fft.irfft(cross, size)
    limit = int(min(max_lag_seconds * sample_rate, size // 2 - 1))
    if limit < 1:
        return 0.0
    window = np.concatenate([correlation[-limit:], correlation[:limit + 1]])
    index = int(np.argmax(window))
    # 抛物线插值到亚采样
    if 0 < index < window.size - 1:
        left, center, right = window[index - 1], window[index], window[index + 1]
        denominator = left - 2.0 * center + right
        offset = 0.5 * (left - right) / denominator if abs(denominator) > 1e-20 else 0.0
    else:
        offset = 0.0
    lag = index - limit + offset
    return float(lag) / float(sample_rate)


def shift_signal(sig: np.ndarray, samples: float) -> np.ndarray:
    """按采样点数平移（正数后移），小数部分线性插值。"""
    size = len(sig)
    whole = int(np.floor(samples))
    fraction = samples - whole
    if whole >= 0:
        head = np.concatenate([np.zeros(whole), sig[: max(size - whole, 0)]])
    else:
        head = np.concatenate([sig[-whole:], np.zeros(-whole)])
    head = head[:size]
    if fraction > 1e-9:
        shifted = np.concatenate([[0.0], head[:-1]])
        head = head * (1.0 - fraction) + shifted * fraction
    return head


def detect_noise_segment(samples: np.ndarray, sample_rate: int,
                         seconds: float = NOISE_WINDOW_SECONDS,
                         search_limit: float = 10.0) -> tuple[int, int] | None:
    """在前 `search_limit` 秒里找 RMS 最平稳的一整段（脉动最小）。

    返回样本区间；找不到平稳段时返回 None（调用方要求用户框选）。
    """
    size = len(samples)
    span = int(seconds * sample_rate)
    if span < sample_rate // 10 or size < span * 2:
        return None
    block = max(8, int(NOISE_BLOCK_SECONDS * sample_rate))
    candidates: list[tuple[float, float, int, int]] = []
    start = 0
    last = min(size - span, int(search_limit * sample_rate))
    step = max(block, int(0.05 * sample_rate))
    while start <= last:
        chunk = samples[start:start + span]
        count = chunk.size // block
        if count < 4:
            break
        levels = np.sqrt(np.mean(chunk[: count * block].reshape(count, block) ** 2, axis=1))
        mean = float(np.mean(levels))
        if mean > 1e-9:
            candidates.append((float(np.std(levels) / mean), mean, start, start + span))
        start += step
    if not candidates:
        return None
    # ???**???????**????????? RMS ?????????????
    # ???????????????????????? T1/T2 ?????
    levels = np.asarray([item[1] for item in candidates], dtype=np.float64)
    level_limit = 1.5 * float(np.percentile(levels, 10))
    quiet = [item for item in candidates
             if item[1] <= level_limit and item[0] <= NOISE_FLATNESS_LIMIT]
    if not quiet:
        return None
    best = min(quiet, key=lambda item: item[0])
    return best[2], best[3]


# ---------------------------------------------------------------- 线性求解
def _autocorrelation(sig: np.ndarray, order: int) -> np.ndarray:
    spectrum = np.fft.rfft(sig, 2 * len(sig))
    power = np.fft.irfft(np.abs(spectrum) ** 2, 2 * len(sig))
    return power[:order] / max(len(sig), 1)


def _cross_correlation(ref: np.ndarray, target: np.ndarray, order: int) -> np.ndarray:
    """r[k] = Σ x[n−k]·d[n]（因果 FIR 定义下的互相关，k = 0…order−1）。"""
    size = len(ref)
    spectrum_x = np.fft.rfft(ref, 2 * size)
    spectrum_d = np.fft.rfft(target, 2 * size)
    correlation = np.fft.irfft(spectrum_d * np.conj(spectrum_x), 2 * size)
    return correlation[:order] / max(size, 1)


def normal_equations(ref: np.ndarray, target: np.ndarray, order: int,
                     lambda_ratio: float = DEFAULT_LAMBDA_RATIO) -> tuple[np.ndarray, np.ndarray]:
    """返回 (R + λI, Xᵀd)，供最小二乘与递归更新共用。"""
    order = max(1, min(int(order), len(ref) // 4 if len(ref) >= 8 else 1))
    autocorr = _autocorrelation(ref, order)
    matrix = sla.toeplitz(autocorr)
    lam = float(lambda_ratio) * float(np.trace(matrix)) / max(order, 1)
    matrix = matrix + np.eye(order) * max(lam, 1e-18)
    return matrix, _cross_correlation(ref, target, order)


def solve_filter(ref: np.ndarray, target: np.ndarray, order: int = DEFAULT_ORDER,
                 lambda_ratio: float = DEFAULT_LAMBDA_RATIO) -> np.ndarray:
    matrix, rhs = normal_equations(ref, target, order, lambda_ratio)
    try:
        return sla.solve(matrix, rhs, assume_a="pos")
    except (np.linalg.LinAlgError, ValueError):
        return sla.lstsq(matrix, rhs)[0]


def apply_filter(ref: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """因果 FIR 卷积，长度与输入一致。

    非因果效果由 `_align()` 先把参考路后移 `N/2` 得到：解出的 h 自然把主抽头
    放在 `N/2` 附近，等效于居中滤波器，不需要在卷积里做特殊处理。
    """
    weights = np.asarray(weights, dtype=np.float64).reshape(-1)
    if weights.size == 0:
        return np.zeros_like(ref)
    filtered = sps.fftconvolve(np.asarray(ref, dtype=np.float64), weights, mode="full")
    return filtered[: len(ref)]


def _quiet_span(target: np.ndarray, sample_rate: int, seconds: float = 0.25,
                search_limit: float = 10.0) -> tuple[int, int]:
    """找一段能量最低的窗口，用于估计通道时延（避免被主频信号带偏）。"""
    span = max(8, int(seconds * sample_rate))
    if target.size <= span:
        return 0, int(target.size)
    last = min(target.size - span, int(search_limit * sample_rate))
    step = max(1, span // 4)
    best: tuple[float, int] | None = None
    for start in range(0, last + 1, step):
        chunk = target[start:start + span]
        level = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float64))))
        if best is None or level < best[0]:
            best = (level, start)
    assert best is not None
    return best[1], best[1] + span


def _align(ref: np.ndarray, target: np.ndarray, sample_rate: int,
           order: int, span: tuple[int, int] | None = None) -> np.ndarray:
    """把参考路对齐到目标路，并再**提前** N/2。

    时延只在低能量窗口（或调用方指定的噪声段）上估计，避免主频信号把
    GCC-PHAT 的峰拉到错误位置；提前 N/2 让解出的 h 主抽头落在 N/2 附近，
    等效于居中（非因果）滤波器。
    """
    start, stop = span or _quiet_span(target, sample_rate)
    start, stop = int(start), int(stop)
    lag = estimate_lag(ref[start:stop], target[start:stop], sample_rate)
    return shift_signal(ref, -(lag * sample_rate + order / 2.0))


def _quiet_erle(target: np.ndarray, cleaned: np.ndarray, sample_rate: int) -> float:
    """在最低能量的 0.5 s 窗口上算 ERLE：那里只有噪声，才反映真实抵消量。"""
    start, stop = _quiet_span(target, sample_rate, seconds=0.5)
    return erle_db(target[start:stop], cleaned[start:stop])


def _prepare(ref: np.ndarray, target: np.ndarray, sample_rate: int,
             order: int,
             span: tuple[int, int] | None = None) -> tuple[np.ndarray, np.ndarray]:
    ref = np.asarray(ref, dtype=np.float64).reshape(-1)
    target = np.asarray(target, dtype=np.float64).reshape(-1)
    size = min(ref.size, target.size)
    ref, target = ref[:size], target[:size]
    return _align(ref, target, sample_rate, order, span), target


# ---------------------------------------------------------------- 方法实现
def _train_pair(ref: np.ndarray, target: np.ndarray, order: int,
                lambda_ratio: float) -> np.ndarray:
    return solve_filter(ref, target, order, lambda_ratio)


def _evaluate(target: np.ndarray, cleaned: np.ndarray, ref: np.ndarray,
              sample_rate: int, f0: float | None, method: str,
              order: int, trained: int, averages: int,
              noise_span: tuple[float, float] | None,
              predicted_ref: np.ndarray | None = None) -> tuple[Diagnostics, str | None]:
    """统一诊断与护栏；返回 (诊断, 拒绝原因)。"""
    diag = Diagnostics(method=method, f0=f0, order=order,
                       samples_trained=trained, averages=averages,
                       noise_span=noise_span)
    diag.erle_db = erle_db(target, cleaned)
    if f0:
        diag.delta_level_db = 20.0 * np.log10(
            max(tone_amplitude(cleaned, sample_rate, f0), 1e-12)
            / max(tone_amplitude(target, sample_rate, f0), 1e-12)
        )
        freqs, gamma = coherence_profile(ref, target, sample_rate)
        diag.coherence_xd = coherence_at(freqs, gamma, f0)
        if predicted_ref is not None:
            power_pred = tone_amplitude(predicted_ref, sample_rate, f0) ** 2
            power_target = tone_amplitude(target, sample_rate, f0) ** 2
            if power_target > 0:
                diag.leak_coherence = float(min(power_pred / power_target, 1.0))
        if diag.leak_coherence is not None:
            diag.delta_sys_db = delta_sys_db(diag.leak_coherence)
            diag.delta_phase_rad = delta_phase_rad(diag.leak_coherence)
    diag.u_c_db = combined_u(diag.delta_sys_db, averages)
    return diag, _guard(diag, method)


def _guard(diag: Diagnostics, method: str) -> str | None:
    """五条护栏（§3.3.5）；返回第一条不满足的原因。"""
    if method in ("ls_frozen", "ls_block", "wiener_clean", "wiener_spectral"):
        if diag.erle_holdout_db is not None and diag.erle_holdout_db < MIN_ERLE_HOLDOUT_DB:
            return tf("留出段 ERLE 只有 {_v0:.1f} dB（要求 ≥ {_v1:.0f} dB）：参考路对噪声几乎没有预测力。",
                      _v0=diag.erle_holdout_db, _v1=MIN_ERLE_HOLDOUT_DB)
        if diag.leak_coherence is not None and diag.leak_coherence > MAX_LEAK_COHERENCE:
            return tf("估计信号泄漏 γ̂²_s = {_v0:.3f}（上限 {_v1:.3f}）：降噪会损伤主频幅值。",
                      _v0=diag.leak_coherence, _v1=MAX_LEAK_COHERENCE)
        if diag.coherence_xd is not None and diag.coherence_xd > MAX_COHERENCE_XD:
            return tf("参考与目标在主频处相干 γ² = {_v0:.3f}（上限 {_v1:.2f}）：两支通道听到同一个信号，"
                      "抵消会把信号一起减掉。",
                      _v0=diag.coherence_xd, _v1=MAX_COHERENCE_XD)
        if diag.samples_trained and diag.order and \
                diag.samples_trained < diag.order * SAMPLES_PER_TAP:
            return tf("噪声段只有 {_v0} 个采样点，少于 {_v1} 阶 × {_v2} 的下限 {_v3}。",
                      _v0=diag.samples_trained, _v1=diag.order,
                      _v2=SAMPLES_PER_TAP, _v3=diag.order * SAMPLES_PER_TAP)
    if method == "sync_avg":
        if diag.averages < MIN_AVERAGES:
            return tf("只检测到 {_v0} 次重复（至少需要 {_v1} 次）。",
                      _v0=diag.averages, _v1=MIN_AVERAGES)
        if diag.delta_level_db is not None and \
                abs(diag.delta_level_db) > MAX_ABS_TSA_LOSS_DB:
            return tf("触发抖动导致幅值损失 {_v0:.2f} dB，超过 {_v1:.1f} dB。",
                      _v0=diag.delta_level_db, _v1=MAX_ABS_TSA_LOSS_DB)
    if method == "noise_profile":
        # 独立噪声画像的护栏在 core/noise_profile 内部（平稳性、含信号检测、主频占比），
        # 这里只兜住主频幅值变化这一类。
        if diag.delta_level_db is not None and \
                abs(diag.delta_level_db) > MAX_ABS_DELTA_LEVEL_DB:
            return tf("噪声画像对主频的影响 {_v0:.2f} dB，超过 {_v1:.1f} dB。",
                      _v0=diag.delta_level_db, _v1=MAX_ABS_DELTA_LEVEL_DB)
    if method in ("notch",) and diag.delta_level_db is not None and \
            abs(diag.delta_level_db) > MAX_ABS_DELTA_LEVEL_DB:
        return tf("陷波对主频的影响 {_v0:.2f} dB，超过 {_v1:.1f} dB：换更小的 Q 值或改中心频率。",
                  _v0=diag.delta_level_db, _v1=MAX_ABS_DELTA_LEVEL_DB)
    return None


def _blocked(method: str, reason: str, order: int = 0,
             noise_span: tuple[float, float] | None = None) -> Outcome:
    diag = Diagnostics(method=method, order=order, blocked=reason)
    diag.noise_span = noise_span
    return Outcome(None, diag)


def _require(reason: str) -> Outcome:
    return Outcome(None, Diagnostics(method="", blocked=reason))


# ---- (a) 同步平均 -------------------------------------------------
def _triggers(envelope: np.ndarray, sample_rate: int, period: float) -> list[int]:
    threshold = 0.5 * float(np.max(envelope)) if envelope.size else 0.0
    if threshold <= 0:
        return []
    minimum = max(1, int(period * sample_rate * 0.5))
    indices: list[int] = []
    last = -minimum
    for index in range(1, envelope.size):
        if envelope[index] >= threshold > envelope[index - 1] and index - last >= minimum:
            indices.append(index)
            last = index
    return indices


def _epoch_phasors(segments: list[np.ndarray], sample_rate: int,
                   frequency: float) -> np.ndarray:
    """每个周期在基频处的复相量（Hann 窗单 bin DFT）：实测幅值损失与相位抖动都从这里来。"""
    if not segments or not frequency:
        return np.empty(0, dtype=np.complex128)
    size = int(segments[0].size)
    window = sps.get_window("hann", size, fftbins=True)
    time = np.arange(size) / float(sample_rate)
    basis = window * np.exp(-2.0j * np.pi * float(frequency) * time)
    return np.asarray([np.sum(np.asarray(seg, dtype=np.float64) * basis) for seg in segments],
                      dtype=np.complex128)


def sync_average(target: np.ndarray, sample_rate: int,
                 fundamental: float | None = None,
                 min_epochs: int = MIN_AVERAGES) -> Outcome:
    """把重复响应按触发对齐后平均；输出为平均后的一个周期。"""
    target = np.asarray(target, dtype=np.float64).reshape(-1)
    envelope = np.abs(sps.hilbert(target))
    period = 1.0 / fundamental if fundamental else 0.05
    triggers = _triggers(envelope, sample_rate, period)
    if fundamental is None and len(triggers) >= 2:
        period = float(np.median(np.diff(triggers))) / sample_rate
    epoch = int(round(period * sample_rate))
    if epoch < 4 or len(triggers) < min_epochs:
        return _blocked("sync_avg",
                        tf("检测到的重复次数不足（{_v0} 次），无法做同步平均。", _v0=len(triggers)))
    usable = [start for start in triggers if start + epoch <= target.size]
    if len(usable) < min_epochs:
        return _blocked("sync_avg",
                        tf("可用完整周期只有 {_v0} 个（至少 {_v1} 个）。",
                           _v0=len(usable), _v1=min_epochs))
    reference = target[usable[0]:usable[0] + epoch]
    segments: list[np.ndarray] = []
    lags: list[float] = []
    for start in usable:
        chunk = target[start:start + epoch]
        lag = estimate_lag(reference, chunk, sample_rate,
                           max_lag_seconds=period * 0.5)
        lags.append(lag)
        segments.append(shift_signal(chunk, -lag * sample_rate))
    stack = np.vstack(segments)
    cleaned = np.mean(stack, axis=0)
    noise_erle = erle_db(target, np.resize(cleaned, target.size)) if target.size else 0.0
    phasors = _epoch_phasors(segments, sample_rate, fundamental) if fundamental else None
    sigma_lag = float(np.std(lags)) if len(lags) > 1 else 0.0
    if phasors is not None and phasors.size > 1:
        # 实测幅值损失：平均波形的相量长度 / 各周期相量长度均值。
        measured = float(20.0 * np.log10(
            max(float(np.abs(phasors.mean())), 1e-18)
            / max(float(np.mean(np.abs(phasors))), 1e-18)))
        sigma_phase = float(np.std(np.angle(phasors))) / (2.0 * np.pi * fundamental)
        sigma_t = max(sigma_phase, sigma_lag)
    else:
        measured = float(tsa_loss_db(fundamental, sigma_lag) or 0.0)
        sigma_t = sigma_lag
    predicted = tsa_loss_db(fundamental, sigma_t)
    diag = Diagnostics(
        method="sync_avg", f0=fundamental, averages=len(usable),
        samples_trained=len(usable) * epoch,
        delta_level_db=measured, u_c_db=combined_u(None, len(usable)),
    )
    diag.erle_db = float(noise_erle)
    diag.notes.append(tf("触发抖动 σ_t = {_v0:.1f} µs，按公式 ΔL_TSA = {_v1:.2f} dB；实测幅值损失 {_v2:.2f} dB。",
                         _v0=sigma_t * 1e6, _v1=(predicted or 0.0), _v2=measured))
    reason = _guard(diag, "sync_avg")
    diag.blocked = reason
    return Outcome(None if reason else cleaned, diag)


# ---- (b) 窄带陷波 -------------------------------------------------
def notch_filter(target: np.ndarray, sample_rate: int,
                 frequency: float = DEFAULT_NOTCH_FREQUENCY,
                 q: float = DEFAULT_NOTCH_Q, harmonics: int = DEFAULT_HARMONICS,
                 fundamental: float | None = None) -> Outcome:
    target = np.asarray(target, dtype=np.float64).reshape(-1)
    if target.size < 32:
        return _blocked("notch", tr("信号太短，无法做零相位滤波。"))
    cleaned = target.copy()
    for order in range(1, max(1, int(harmonics)) + 1):
        center = float(frequency) * order
        if center >= sample_rate / 2.0:
            break
        b, a = sps.iirnotch(center, float(q), sample_rate)
        cleaned = sps.filtfilt(b, a, cleaned)
    diag = Diagnostics(method="notch", f0=fundamental)
    if fundamental:
        diag.delta_level_db = 20.0 * np.log10(
            max(tone_amplitude(cleaned, sample_rate, fundamental), 1e-12)
            / max(tone_amplitude(target, sample_rate, fundamental), 1e-12)
        )
        diag.delta_sys_db = notch_gain_db(fundamental, float(frequency), float(q))
        diag.notes.append(tf("按解析式，{_v0:g} Hz 处陷波增益 {_v1:.4f} dB。",
                             _v0=fundamental, _v1=notch_gain_db(fundamental, frequency, q)))
    diag.erle_db = erle_db(target, cleaned)
    reason = _guard(diag, "notch")
    diag.blocked = reason
    return Outcome(None if reason else cleaned, diag)


# ---- (c) 冻结两段式 ----------------------------------------------
def frozen_ls(target: np.ndarray, ref: np.ndarray, sample_rate: int,
              order: int = DEFAULT_ORDER,
              lambda_ratio: float = DEFAULT_LAMBDA_RATIO,
              segment: tuple[int, int] | None = None,
              fundamental: float | None = None) -> Outcome:
    """噪声段上训练 h，冻结后作用于全段。"""
    noise = segment or detect_noise_segment(
        np.asarray(target, dtype=np.float64).reshape(-1), sample_rate)
    if noise is None:
        return _blocked("ls_frozen", tr("没有找到平稳噪声段：请先在波形上框选一段只有噪声的区间。"))
    x, d = _prepare(ref, target, sample_rate, order, noise)
    start, stop = int(noise[0]), int(noise[1])
    if stop - start < order * SAMPLES_PER_TAP:
        return _blocked("ls_frozen",
                        tf("噪声段只有 {_v0} 个采样点，少于 {_v1} 阶 × {_v2} 的下限 {_v3}。",
                           _v0=stop - start, _v1=order, _v2=SAMPLES_PER_TAP,
                           _v3=order * SAMPLES_PER_TAP),
                        order=order, noise_span=(start / sample_rate, stop / sample_rate))
    if stop - start < order * 2:
        return _blocked("ls_frozen",
                        tf("噪声段只有 {_v0} 个采样点，至少要 {_v1} 个（2×阶数）才能分训练/留出两半。",
                           _v0=stop - start, _v1=order * 2),
                        order=order, noise_span=(start / sample_rate, stop / sample_rate))
    middle = start + (stop - start) // 2
    weights = _train_pair(x[start:middle], d[start:middle], order, lambda_ratio)
    holdout = apply_filter(x[middle:stop], weights)
    hold_erle = erle_db(d[middle:stop], d[middle:stop] - holdout)
    weights = _train_pair(x[start:stop], d[start:stop], order, lambda_ratio)
    prediction = apply_filter(x, weights)
    cleaned = d - prediction
    diag, reason = _evaluate(
        d, cleaned, x, sample_rate, fundamental, "ls_frozen", order,
        stop - start, 1, (start / sample_rate, stop / sample_rate), prediction,
    )
    diag.erle_holdout_db = float(hold_erle)
    if reason is None:
        reason = _guard(diag, "ls_frozen")
    diag.blocked = reason
    return Outcome(None if reason else cleaned, diag)


# ---- (d) 干净参考路 ----------------------------------------------
def wiener_clean(target: np.ndarray, ref: np.ndarray, sample_rate: int,
                 order: int = DEFAULT_ORDER,
                 lambda_ratio: float = DEFAULT_LAMBDA_RATIO,
                 fundamental: float | None = None) -> Outcome:
    x, d = _prepare(ref, target, sample_rate, order)
    if fundamental:
        freqs, gamma = coherence_profile(x, d, sample_rate)
        coherence = coherence_at(freqs, gamma, fundamental)
        if coherence is not None and coherence > 0.5:
            return _blocked("wiener_clean",
                            tf("参考路在主频处相干 γ² = {_v0:.2f}（> 0.5）：参考路显然含信号，"
                               "请改用「冻结两段式」。", _v0=coherence))
    weights = _train_pair(x, d, order, lambda_ratio)
    prediction = apply_filter(x, weights)
    cleaned = d - prediction
    diag, reason = _evaluate(
        d, cleaned, x, sample_rate, fundamental, "wiener_clean", order,
        d.size, 1, None, prediction,
    )
    diag.erle_holdout_db = _quiet_erle(d, cleaned, sample_rate)
    if reason is None:
        reason = _guard(diag, "wiener_clean")
    diag.blocked = reason
    return Outcome(None if reason else cleaned, diag)


# ---- (e) 分块自适应 ----------------------------------------------
def block_ls(target: np.ndarray, ref: np.ndarray, sample_rate: int,
             order: int = DEFAULT_ORDER,
             lambda_ratio: float = DEFAULT_LAMBDA_RATIO,
             segment: tuple[int, int] | None = None,
             fundamental: float | None = None,
             block_seconds: float = BLOCK_SECONDS) -> Outcome:
    noise = segment or detect_noise_segment(
        np.asarray(target, dtype=np.float64).reshape(-1), sample_rate)
    if noise is None:
        return _blocked("ls_block", tr("没有找到平稳噪声段：请先在波形上框选一段只有噪声的区间。"))
    x, d = _prepare(ref, target, sample_rate, order, noise)
    start, stop = int(noise[0]), int(noise[1])
    if stop - start < order * SAMPLES_PER_TAP:
        return _blocked("ls_block",
                        tf("噪声段只有 {_v0} 个采样点，少于 {_v1} 阶 × {_v2} 的下限 {_v3}。",
                           _v0=stop - start, _v1=order, _v2=SAMPLES_PER_TAP,
                           _v3=order * SAMPLES_PER_TAP),
                        order=order, noise_span=(start / sample_rate, stop / sample_rate))
    if stop - start < order * 2:
        return _blocked("ls_block",
                        tf("噪声段只有 {_v0} 个采样点，至少要 {_v1} 个（2×阶数）才能分训练/留出两半。",
                           _v0=stop - start, _v1=order * 2),
                        order=order, noise_span=(start / sample_rate, stop / sample_rate))
    middle = start + (stop - start) // 2
    base = _train_pair(x[start:middle], d[start:middle], order, lambda_ratio)
    holdout = apply_filter(x[middle:stop], base)
    hold_erle = erle_db(d[middle:stop], d[middle:stop] - holdout)
    matrix, rhs = normal_equations(x[start:stop], d[start:stop], order, lambda_ratio)
    weights = base.copy()
    block = max(int(block_seconds * sample_rate), order)
    curve: list[float] = []
    for begin in range(0, d.size, block):
        end = min(begin + block, d.size)
        if end - begin < order * 2:
            continue
        local_matrix, local_rhs = normal_equations(x[begin:end], d[begin:end], order,
                                                   lambda_ratio)
        matrix = FORGETTING * matrix + (1.0 - FORGETTING) * local_matrix
        rhs = FORGETTING * rhs + (1.0 - FORGETTING) * local_rhs
        try:
            weights = sla.solve(matrix, rhs, assume_a="pos")
        except (np.linalg.LinAlgError, ValueError):
            weights = sla.lstsq(matrix, rhs)[0]
        block_prediction = apply_filter(x[begin:end], weights)
        curve.append(erle_db(d[begin:end], d[begin:end] - block_prediction))
    prediction = apply_filter(x, weights)
    cleaned = d - prediction
    diag, reason = _evaluate(
        d, cleaned, x, sample_rate, fundamental, "ls_block", order,
        stop - start, 1, (start / sample_rate, stop / sample_rate), prediction,
    )
    diag.erle_holdout_db = float(hold_erle)
    diag.block_erle = [float(value) for value in curve]
    if reason is None:
        reason = _guard(diag, "ls_block")
    diag.blocked = reason
    return Outcome(None if reason else cleaned, diag)


# ---- (f) 频域 Wiener ---------------------------------------------
def wiener_spectral(target: np.ndarray, ref: np.ndarray, sample_rate: int,
                    nperseg: int = 4096,
                    fundamental: float | None = None) -> Outcome:
    """零相位频域 Wiener：H(f) = S_xd/S_xx，限幅 |H| ≤ 1 后在频域直接相乘。

    不在时域摆放冲激响应，因此不引入任何时延（T11 用互相关峰位置验证）。
    """
    d = np.asarray(target, dtype=np.float64).reshape(-1)
    r = np.asarray(ref, dtype=np.float64).reshape(-1)
    start, stop = _quiet_span(d, sample_rate)
    lag = estimate_lag(r[start:stop], d[start:stop], sample_rate)
    x = shift_signal(r, -lag * sample_rate)          # 去掉通道时延，不留 N/2
    limit = min(int(nperseg), d.size // 2)
    if limit < 128:
        return _blocked("wiener_spectral", tr("信号太短，无法估计互谱。"))
    nperseg = int(limit)
    freqs, sxx = sps.welch(x, fs=sample_rate, nperseg=nperseg,
                           noverlap=nperseg // 2, detrend=False)
    _, sxd = sps.csd(x, d, fs=sample_rate, nperseg=nperseg,
                     noverlap=nperseg // 2, detrend=False)
    transfer = sxd / (sxx + 1e-18)
    magnitude = np.abs(transfer)
    # 限幅：|H| ≤ 1，避免反相放大把噪声抬高。
    transfer = np.where(magnitude > 1.0, transfer / np.maximum(magnitude, 1e-12), transfer)
    size = int(x.size)
    grid = np.fft.rfftfreq(size, 1.0 / sample_rate)
    real = np.interp(grid, freqs, transfer.real)
    imag = np.interp(grid, freqs, transfer.imag)
    prediction = np.fft.irfft(np.fft.rfft(x, size) * (real + 1j * imag), size)
    cleaned = d - prediction
    diag, reason = _evaluate(
        d, cleaned, x, sample_rate, fundamental, "wiener_spectral", 0,
        d.size, transfer.size, None, prediction,
    )
    diag.erle_holdout_db = _quiet_erle(d, cleaned, sample_rate)
    diag.notes.append(tr("频域 Wiener 是零相位实现，不引入时延，但会改变瞬态包络形状。"))
    if reason is None:
        reason = _guard(diag, "wiener_spectral")
    diag.blocked = reason
    return Outcome(None if reason else cleaned, diag)


# ---------------------------------------------------------------- 统一入口
def run_method(method: str, target: np.ndarray, ref: np.ndarray | None,
               sample_rate: int, *, fundamental: float | None = None,
               segment: tuple[int, int] | None = None,
               params: dict[str, Any] | None = None) -> Outcome:
    """按方法 id 分派；缺参考通道或方法未知时返回 blocked 而不抛异常。"""
    params = dict(params or {})
    if method not in METHOD_IDS:
        return _require(tf("未知的降噪方法：{_v0}", _v0=method))
    signal = np.asarray(target, dtype=np.float64).reshape(-1)
    if signal.size < 32:
        return _blocked(method, tf("信号太短（{_v0} 个采样点），无法做降噪。", _v0=signal.size))
    if not np.any(signal):
        return _blocked(method, tr("信号全为零，没有可处理的内容。"))
    if not np.all(np.isfinite(signal)):
        return _blocked(method, tr("信号里有非有限值（NaN/Inf），请先检查输入文件。"))
    # 需要与目标对齐的参考通道方法：长度必须一致
    if method in ("ls_frozen", "wiener_clean", "ls_block", "wiener_spectral"):
        if ref is None:
            return _blocked(method, tr("这个方法需要参考通道：请加载双声道文件，或选择第二个文件作为参考。"))
        reference = np.asarray(ref, dtype=np.float64).reshape(-1)
        if reference.size != signal.size:
            return _blocked(method, tf("参考通道有 {_v0} 个采样点，目标通道有 {_v1} 个：长度必须一致。",
                                       _v0=reference.size, _v1=signal.size))
        if not np.any(reference):
            return _blocked(method, tr("参考通道全为零，无法估计噪声路径。"))
    # 独立噪声画像：参考不要求对齐，只要求能估计出平稳噪声谱
    if method == "noise_profile":
        if ref is None:
            return _blocked(method,
                            tr("这个方法需要一段噪声参考：请加载外部参考文件，或使用双声道文件的另一路。"))
        reference = np.asarray(ref, dtype=np.float64).reshape(-1)
        if not np.any(reference):
            return _blocked(method, tr("参考音频全为零（静音），无法估计噪声谱。"))
    if method == "sync_avg":
        return sync_average(target, sample_rate,
                            fundamental=params.get("fundamental", fundamental))
    if method == "notch":
        return notch_filter(target, sample_rate,
                            frequency=float(params.get("frequency",
                                                       DEFAULT_NOTCH_FREQUENCY)),
                            q=float(params.get("q", DEFAULT_NOTCH_Q)),
                            harmonics=int(params.get("harmonics", DEFAULT_HARMONICS)),
                            fundamental=fundamental)
    order = int(params.get("order", DEFAULT_ORDER))
    lambda_ratio = float(params.get("lambda_ratio", DEFAULT_LAMBDA_RATIO))
    if method == "ls_frozen":
        return frozen_ls(target, ref, sample_rate, order, lambda_ratio, segment, fundamental)
    if method == "wiener_clean":
        return wiener_clean(target, ref, sample_rate, order, lambda_ratio, fundamental)
    if method == "ls_block":
        return block_ls(target, ref, sample_rate, order, lambda_ratio, segment,
                        fundamental, float(params.get("block_seconds", BLOCK_SECONDS)))
    if method == "noise_profile":
        return noise_profile_method(target, ref, sample_rate, fundamental=fundamental,
                                    params=params)
    return wiener_spectral(target, ref, sample_rate,
                           int(params.get("nperseg", 4096)), fundamental)


def noise_profile_method(target: np.ndarray, ref: np.ndarray | None,
                         sample_rate: int, *, fundamental: float | None = None,
                         params: dict[str, Any] | None = None) -> Outcome:
    """独立噪声画像：参考不要求与目标对齐，可以是另一次录音。"""
    from .noise_profile import apply_noise_profile

    if ref is None:
        return _blocked("noise_profile",
                        tr("这个方法需要一段噪声参考：请加载外部参考文件，或使用双声道文件的另一路。"))
    params = dict(params or {})
    result = apply_noise_profile(
        target, ref, sample_rate, fundamental=fundamental,
        nperseg=int(params.get("nperseg", 1024)),
        alpha=float(params.get("alpha", 0.98)),
        psi_min=float(params.get("psi_min", 0.02)))
    diag = Diagnostics(method="noise_profile", f0=fundamental)
    diag.stationarity_db = result.stationarity_db
    diag.noise_at_f0 = result.noise_at_f0
    diag.delta_level_db = result.delta_level_db
    diag.mean_gain = result.mean_gain
    diag.notes.extend(result.notes)
    if result.blocked is not None:
        diag.blocked = result.blocked
        return Outcome(None, diag)
    # 报告指标：全段 ERLE 与留出段 ERLE（最低能量窗口）
    diag.erle_db = erle_db(np.asarray(target, dtype=np.float64),
                           np.asarray(result.cleaned, dtype=np.float64))
    diag.erle_holdout_db = _quiet_erle(np.asarray(target, dtype=np.float64),
                                       np.asarray(result.cleaned, dtype=np.float64),
                                       sample_rate)
    return Outcome(result.cleaned, diag)
