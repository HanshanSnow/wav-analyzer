"""原始数据导出：频谱 / 峰值与谐波 / 包络 CSV，时频矩阵 NPZ。

设计要点（与统计 CSV 保持一致）：

* **列名一律英文**，方便脚本与跨语言处理；文件里的说明文字用 `#` 注释行，
  不参与 `csv.DictReader` 的列解析。
* 频谱的元信息必须落盘：长录音默认只取居中的一段做 FFT，
  丢了 `analysis_offset` / `analyzed_samples` / `total_samples` / `window`，
  导出后的数字就没法和原始录音对上。
* 时频矩阵用 `np.savez_compressed`，并且把 `skipped` 一起写进去——
  长音频会均匀跳帧（`max_frames` 上限），不说明的话用户会以为拿到的是全部帧。
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from .i18n import tf, tr
from .spectral import FourierResult

SPECTRUM_COLUMNS = ("frequency_hz", "amplitude", "amplitude_dbfs", "phase_rad")
PEAK_COLUMNS = ("frequency_hz", "amplitude", "amplitude_dbfs", "phase_rad", "harmonic")
ENVELOPE_COLUMNS = ("time_s", "envelope", "fitted")


def _write_csv(target: Path, columns: tuple[str, ...], rows, metadata: list[str]) -> Path:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(tr("没有可导出的数据"))
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        for line in metadata:
            handle.write(f"# {line}\n")
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return target


def fourier_metadata(fourier: FourierResult) -> list[str]:
    """写进频谱类 CSV 的文件头，键名英文，避免以后报告语言切换时再改一遍。"""
    return [
        f"sample_rate_hz={fourier.sample_rate}",
        f"window={fourier.window}",
        f"n_fft={fourier.n_fft}",
        f"analyzed_samples={fourier.analyzed_samples}",
        f"total_samples={fourier.total_samples}",
        f"analysis_offset_s={fourier.analysis_offset:.9f}",
        f"main_frequency_hz={fourier.main_frequency:.9f}",
        f"thd={fourier.thd:.9g}",
    ]


def export_spectrum_csv(path: str | Path, fourier: FourierResult) -> Path:
    """整条幅值谱：每个 FFT 频点一行。"""
    rows = (
        {
            "frequency_hz": f"{freq:.9f}",
            "amplitude": f"{amp:.12g}",
            "amplitude_dbfs": f"{dbfs:.9f}",
            "phase_rad": f"{phase:.9f}",
        }
        for freq, amp, dbfs, phase in zip(
            fourier.frequencies, fourier.amplitude,
            fourier.amplitude_dbfs, fourier.phase,
        )
    )
    return _write_csv(Path(path), SPECTRUM_COLUMNS, rows, fourier_metadata(fourier))


def export_peaks_csv(
    path: str | Path,
    fourier: FourierResult,
    *,
    include_harmonics: bool = True,
    peak_count: int = 8,
) -> Path:
    """主要峰值；`include_harmonics` 时把基频整数倍谐波也列出来并标注 order。"""
    rows: list[dict[str, object]] = []
    for peak in fourier.peaks(count=peak_count):
        rows.append({**peak, "harmonic": ""})
    if include_harmonics:
        for harmonic in fourier.harmonics():
            rows.append({
                "frequency_hz": harmonic["frequency_hz"],
                "amplitude": harmonic["amplitude"],
                "amplitude_dbfs": harmonic["amplitude_dbfs"],
                "phase_rad": harmonic["phase_rad"],
                "harmonic": harmonic["order"],
            })
    metadata = fourier_metadata(fourier)
    metadata.append(f"fundamental_frequency_hz={fourier.fundamental_frequency:.9f}")
    formatted = [
        {
            "frequency_hz": f"{float(row['frequency_hz']):.9f}",
            "amplitude": f"{float(row['amplitude']):.12g}",
            "amplitude_dbfs": f"{float(row['amplitude_dbfs']):.9f}",
            "phase_rad": f"{float(row['phase_rad']):.9f}",
            "harmonic": row["harmonic"],
        }
        for row in rows
    ]
    return _write_csv(Path(path), PEAK_COLUMNS, formatted, metadata)


def export_envelope_csv(
    path: str | Path,
    times: np.ndarray,
    envelope: np.ndarray,
    fitted: np.ndarray | None = None,
) -> Path:
    """包络曲线与拟合曲线；没有拟合时 `fitted` 列留空，而不是补 0。"""
    times = np.asarray(times, dtype=np.float64)
    envelope = np.asarray(envelope, dtype=np.float64)
    if times.size != envelope.size:
        raise ValueError(tf("包络与时间轴长度不一致：{_v0} vs {_v1}",
                            _v0=(times.size), _v1=(envelope.size)))
    if fitted is not None:
        fitted = np.asarray(fitted, dtype=np.float64)
        if fitted.size != times.size:
            raise ValueError(tf("拟合曲线长度不一致：{_v0} vs {_v1}",
                                _v0=(fitted.size), _v1=(times.size)))
    rows = []
    for index in range(times.size):
        rows.append({
            "time_s": f"{times[index]:.9f}",
            "envelope": f"{envelope[index]:.12g}",
            "fitted": "" if fitted is None else f"{fitted[index]:.12g}",
        })
    metadata = [f"samples={times.size}"]
    return _write_csv(Path(path), ENVELOPE_COLUMNS, rows, metadata)


def total_spectrogram_frames(total_samples: int, nperseg: int, noverlap: int) -> int:
    """不跳帧时 STFT 会得到多少帧；用来算 `skipped`。"""
    step = max(1, nperseg - noverlap)
    if total_samples < nperseg:
        return 0
    return 1 + (total_samples - nperseg) // step


def skipped_frames(total_samples: int, nperseg: int, noverlap: int, kept: int) -> int:
    return max(0, total_spectrogram_frames(total_samples, nperseg, noverlap) - int(kept))


def export_spectrogram_npz(
    path: str | Path,
    times: np.ndarray,
    frequencies: np.ndarray,
    magnitude_db: np.ndarray,
    *,
    nperseg: int,
    noverlap: int,
    sample_rate: int,
    max_frames: int,
    skipped: int,
    window: str = "hann",
) -> Path:
    """时频矩阵。`magnitude_db` 已是 dBFS；布局沿用 `(频率, 时间)`。"""
    target = Path(path)
    # numpy 会自动补 .npz，但只会补在它自己内部；这里先补好再保存，
    # 保证返回给调用方的路径就是真实落盘的文件（BUG-013）。
    if target.suffix.lower() != ".npz":
        target = target.with_suffix(".npz")
    target.parent.mkdir(parents=True, exist_ok=True)
    times = np.asarray(times, dtype=np.float64)
    frequencies = np.asarray(frequencies, dtype=np.float64)
    magnitude_db = np.asarray(magnitude_db, dtype=np.float64)
    if magnitude_db.shape != (frequencies.size, times.size):
        raise ValueError(tf("时频矩阵形状应为 ({_v0}, {_v1})，实际为 {_v2}",
                            _v0=(frequencies.size), _v1=(times.size),
                            _v2=(magnitude_db.shape)))
    np.savez_compressed(
        target,
        times=times,
        frequencies=frequencies,
        magnitude_db=magnitude_db,
        nperseg=np.int32(nperseg),
        noverlap=np.int32(noverlap),
        sample_rate=np.int32(sample_rate),
        max_frames=np.int32(max_frames),
        skipped=np.int32(skipped),
        window=np.array(window),
        unit=np.array("dBFS"),
        layout=np.array("(frequency, time)"),
    )
    return target
