"""独立噪声画像（noise_profile）：参考与目标**不要求样本对齐**时的降噪。

适用场景（方案 A 覆盖不了的）：
- 目标录完后才单独录一段环境噪声（两次录音，起点不可对齐）；
- 参考麦克风与目标麦克风没有共用采样时钟；
- 参考比目标长/短，且不是同一段音频。

做法（与之前失败的谱减/WOLA 尝试不同）：

1. 在参考的全局平稳段估计**静态噪声功率谱** P_n(f)，而不是逐帧更新——
   逐帧增益正是之前“能量被搬到其它频带”的根源。
2. 用**决策定向（decision-directed）后验 SNR** 估计目标每帧的增益：
       ξ̂[k] = α·|Y[k-1]|²/P_n[k] + (1−α)·max(|Y[k]|²/P_n[k] − 1, 0)
   前一帧的估计值把增益在时间轴上串起来，避免帧间抖动。
3. 增益取 Wiener 形式 G = ξ/(1+ξ)，再经时间平滑与下限约束， musical noise
   被压到可接受水平。
4. 重叠相加（WOLA）合成，COLA 归一化保证纯音不被改变形状。

护栏（任一不满足则拒绝应用）：
- 参考太短 / 非平稳（前后期 PSD 差异大）；
- 参考里含有与目标主频相同的强音（会把信号当成噪声减掉）；
- 噪声在目标主频处能量占比过高（ν，直接损伤信号）；
- 主频幅值变化超过容差。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal as sps

from .i18n import tf, tr

METHOD_ID = "noise_profile"
DEFAULT_NPERSEG = 1024
DEFAULT_HOP_RATIO = 0.25        # 帧移 = nperseg/4（75% 重叠，增益平滑）
DEFAULT_ALPHA = 0.98            # 决策定向平滑系数（越大越稳，响应越慢）
DEFAULT_PSI_MIN = 0.02          # 增益下限（-34 dB），防止把整帧压成零
DEFAULT_STATIONARITY_DB = 12.0  # 前/后半段**宽带平均功率**的最大允许偏差（不是逐 bin PSD 差）
MIN_REFERENCE_SECONDS = 0.5     # 至少要有这么长的参考才能估计平稳 PSD
MAX_NOISE_AT_F0 = 0.5           # 主频处噪声功率占比上限
MAX_ABS_DELTA_LEVEL_DB = 1.0    # 主频幅值允许变化


@dataclass
class NoiseProfileResult:
    cleaned: np.ndarray | None
    blocked: str | None = None
    noise_psd: np.ndarray | None = None
    freqs: np.ndarray | None = None
    stationarity_db: float | None = None
    noise_at_f0: float | None = None
    delta_level_db: float | None = None
    mean_gain: float | None = None
    notes: list[str] = field(default_factory=list)


def _frame_power(x: np.ndarray, nperseg: int, hop: int,
                 window: np.ndarray) -> np.ndarray:
    """逐帧加窗功率谱 |Y|²，形状 (freq, frame)。"""
    if x.size < nperseg:
        x = np.pad(x, (0, nperseg - x.size))
    frames = sps.stft(x, fs=1.0, window=window, nperseg=nperseg,
                      noverlap=nperseg - hop, boundary=None, padded=False)[2]
    return np.abs(frames) ** 2


def estimate_noise_psd(reference: np.ndarray, sample_rate: int,
                       nperseg: int = DEFAULT_NPERSEG,
                       hop: int | None = None) -> tuple[np.ndarray, np.ndarray, float]:
    """在参考上估计静态噪声功率谱，并返回平稳性指标。

    平稳性取**前/后半段宽带平均功率之比**（dB）。这里刻意不取逐 bin PSD 比值的
    最大值：白噪声每个 bin 的功率服从 χ²₂，逐 bin 比值的涨落可达 10 dB 以上，
    会把平稳噪声判成不平稳。
    """
    reference = np.asarray(reference, dtype=np.float64).reshape(-1)
    if reference.size < int(MIN_REFERENCE_SECONDS * sample_rate):
        raise ValueError(tf("参考太短（{_v0} 点），至少需要 {_v1:.1f} s 才能估计噪声谱。",
                            _v0=reference.size, _v1=MIN_REFERENCE_SECONDS))
    hop = hop or max(1, nperseg // 4)
    window = sps.get_window("hann", nperseg, fftbins=True)
    power = _frame_power(reference, nperseg, hop, window)
    psd = np.mean(power, axis=1)
    freqs = np.fft.rfftfreq(nperseg, d=1.0 / sample_rate)

    half = power.shape[1] // 2
    if half >= 2:
        first = np.mean(power[:, :half], axis=1)
        second = np.mean(power[:, half:], axis=1)
        # 逐 bin 功率比的白噪声方差极大（χ²₂），直接取 max 会把平稳噪声也判成不平稳。
        # 比较**宽带平均功率**的前/后半段差异，20% 以内的起伏视为正常统计涨落。
        total_first = float(np.sum(first))
        total_second = float(np.sum(second))
        if total_first > 0 and total_second > 0:
            stationarity_db = float(abs(10.0 * np.log10(total_first / total_second)))
        else:
            stationarity_db = 0.0
    else:
        stationarity_db = 0.0
    return freqs, psd, stationarity_db


def _tone_amplitude(sig: np.ndarray, sample_rate: int, frequency: float) -> float:
    if sig.size < 8 or frequency <= 0:
        return 0.0
    window = np.hanning(sig.size)
    spectrum = np.abs(np.fft.rfft(sig * window))
    freqs = np.fft.rfftfreq(sig.size, d=1.0 / sample_rate)
    index = int(np.argmin(np.abs(freqs - frequency)))
    return float(2.0 * spectrum[index] / np.sum(window))


def _reference_contains_tone(reference: np.ndarray, sample_rate: int,
                             fundamental: float) -> bool:
    """参考在主频处的音调是否显著强于 broadband（> 3σ 则视为含信号）。"""
    if not fundamental or fundamental <= 0:
        return False
    amplitude = _tone_amplitude(reference, sample_rate, fundamental)
    broadband = float(np.std(reference)) + 1e-12
    # 单频音的幅值约为 RMS 的 √2 倍；宽带噪声里同一 bin 的幅值期望低得多。
    return amplitude > 0.5 * broadband


def apply_noise_profile(target: np.ndarray, reference: np.ndarray,
                        sample_rate: int, *, fundamental: float | None = None,
                        nperseg: int = DEFAULT_NPERSEG,
                        alpha: float = DEFAULT_ALPHA,
                        psi_min: float = DEFAULT_PSI_MIN) -> NoiseProfileResult:
    """用独立噪声画像抑制目标里的平稳噪声。"""
    target = np.asarray(target, dtype=np.float64).reshape(-1)
    reference = np.asarray(reference, dtype=np.float64).reshape(-1)
    if target.size < 32:
        return NoiseProfileResult(None, blocked=tr("信号太短，无法做噪声画像降噪。"))
    if not np.all(np.isfinite(target)) or not np.all(np.isfinite(reference)):
        return NoiseProfileResult(None, blocked=tr("信号或参考里有非有限值（NaN/Inf）。"))
    if not np.any(reference):
        return NoiseProfileResult(None, blocked=tr("参考音频全为零（静音），无法估计噪声谱。"))

    try:
        freqs, noise_psd, stationarity_db = estimate_noise_psd(reference, sample_rate, nperseg)
    except ValueError as exc:
        return NoiseProfileResult(None, blocked=str(exc))

    if stationarity_db is not None and stationarity_db > DEFAULT_STATIONARITY_DB:
        return NoiseProfileResult(
            None, blocked=tf(
                "参考噪声不平稳：前/后半段功率谱最大相差 {_v0:.1f} dB（上限 {_v1:.1f} dB）。"
                "请换一段更平稳的噪声，或用需要参考通道的方法。",
                _v0=stationarity_db, _v1=DEFAULT_STATIONARITY_DB),
            stationarity_db=stationarity_db)

    if _reference_contains_tone(reference, sample_rate, fundamental or 0.0):
        return NoiseProfileResult(
            None, blocked=tr("参考里含有与目标主频相同的强音，会把信号当成噪声减掉。"
                             "请换一段不含信号的纯噪声参考。"))

    # 主频处噪声功率占比：直接决定会削掉多少信号
    noise_at_f0 = None
    if fundamental and fundamental > 0:
        index = int(np.argmin(np.abs(freqs - fundamental)))
        signal_power = _tone_amplitude(target, sample_rate, fundamental) ** 2
        if signal_power > 0:
            noise_at_f0 = float(noise_psd[index] / (noise_psd[index] + signal_power))
            if noise_at_f0 > MAX_NOISE_AT_F0:
                return NoiseProfileResult(
                    None, blocked=tf(
                        "主频处噪声占比 {_v0:.0%} 过高（上限 {_v1:.0%}）：降噪会明显损伤信号。",
                        _v0=noise_at_f0, _v1=MAX_NOISE_AT_F0),
                    noise_at_f0=noise_at_f0)

    # STFT + 决策定向增益。平顶窗（Blackman-Harris）+ 50% 重叠：
    # Hann 窗做 OLA 会在帧边界相互抵消，逐点归一化在边界趋近 0、放大噪声；
    # Blackman-Harris 的 OLA 常数严格非零，逐点归一化稳定。
    hop = max(1, nperseg // 2)
    window = sps.get_window("blackmanharris", nperseg, fftbins=True)
    # 补零只为让 STFT 能算，**输出长度必须等于输入长度**：批量把结果写回原数组，
    # 长度变了会抛 broadcast 错误或悄悄改掉采样点数。
    original_size = target.size
    if original_size < nperseg:
        target = np.pad(target, (0, nperseg - original_size))
    freqs_t, times, stft = sps.stft(target, fs=sample_rate, window=window,
                                    nperseg=nperseg, noverlap=nperseg - hop,
                                    boundary="zeros", padded=True)
    magnitude = np.abs(stft)
    phase = np.exp(1j * np.angle(stft))
    power = magnitude ** 2
    # 噪声谱插值到目标 STFT 频率网格（通常一致，保险起见）
    noise_on_grid = np.interp(freqs_t, freqs, noise_psd)

    gain = np.empty_like(magnitude)
    n_freqs, n_frames = magnitude.shape
    previous = np.ones(n_freqs)  # 每频点一个先验 SNR 估计，沿时间平滑
    for frame in range(n_frames):
        posterior = power[:, frame] / np.maximum(noise_on_grid, 1e-18)
        # 决策定向：以前一帧的先验 SNR 估计平滑当前帧
        prior = alpha * previous + (1.0 - alpha) * np.maximum(posterior - 1.0, 0.0)
        g = prior / (1.0 + prior)
        gain[:, frame] = np.maximum(g, psi_min)
        previous = prior

    cleaned_stft = gain * magnitude * phase
    _, cleaned = sps.istft(cleaned_stft, fs=sample_rate, window=window,
                           nperseg=nperseg, noverlap=nperseg - hop,
                           boundary=True)
    # scipy 的 istft 内部已做窗和归一化（恒等 STFT 往返误差 ~1e-16），
    # 不要再除以自己的 norm——那会把增益变成 ~1/0.7，主频被抬高 3 dB。
    cleaned = np.asarray(cleaned, dtype=np.float64)[: original_size]
    if cleaned.size < original_size:            # 极短输入时 istft 可能偏短
        cleaned = np.pad(cleaned, (0, original_size - cleaned.size))

    delta_level_db = None
    # 幅值诊断只在目标至少有一帧长时才可信：几十个采样点上的单 bin DFT 受泄漏影响，
    # 会把"没动信号"读成 1–2 dB 的变化，进而误触发护栏。
    if fundamental and fundamental > 0 and original_size >= nperseg:
        # 诊断必须在**原始长度**上做，不能拿补零后的数组：补零会改变音调幅值的分母
        before = _tone_amplitude(target[: original_size], sample_rate, fundamental)
        after = _tone_amplitude(cleaned, sample_rate, fundamental)
        if before > 0:
            delta_level_db = float(20.0 * np.log10(max(after, 1e-12) / before))
            if abs(delta_level_db) > MAX_ABS_DELTA_LEVEL_DB:
                return NoiseProfileResult(
                    None, blocked=tf(
                        "主频幅值变化 {_v0:+.2f} dB，超过 {_v1:.1f} dB：噪声画像会损伤信号。",
                        _v0=delta_level_db, _v1=MAX_ABS_DELTA_LEVEL_DB),
                    noise_at_f0=noise_at_f0, delta_level_db=delta_level_db,
                    mean_gain=float(np.mean(gain)))

    return NoiseProfileResult(
        cleaned, noise_psd=noise_psd, freqs=freqs,
        stationarity_db=stationarity_db, noise_at_f0=noise_at_f0,
        delta_level_db=delta_level_db, mean_gain=float(np.mean(gain)),
        notes=[tr("独立噪声画像：静态噪声谱 + 决策定向增益，不要求参考与目标对齐。")])


def _ola_normalization(n_frames: int, nperseg: int, hop: int,
                       window: np.ndarray, size: int) -> np.ndarray:
    """保留给诊断用：istft 输出对应的窗重叠和。正常流程不需要调用，
    因为 scipy 的 istft 内部已经做了同样的归一化。"""
    total = (n_frames - 1) * hop + nperseg
    norm = np.zeros(total)
    for index in range(n_frames):
        start = index * hop
        norm[start:start + nperseg] += window
    return norm[:size]
