from __future__ import annotations

from core.i18n import tf, tr
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf


@dataclass
class AudioData:
    samples: np.ndarray
    sample_rate: int
    source_path: Path | None = None
    subtype: str = ""

    def __post_init__(self) -> None:
        self.samples = np.asarray(self.samples, dtype=np.float64)
        if self.samples.ndim == 1:
            self.samples = self.samples[:, None]
        if self.samples.ndim != 2 or self.samples.shape[0] == 0:
            raise ValueError(tr("音频数据必须是非空的 [采样点, 声道] 数组"))
        if self.sample_rate <= 0:
            raise ValueError(tr("采样率必须为正数"))

    @property
    def channels(self) -> int:
        return int(self.samples.shape[1])

    @property
    def duration(self) -> float:
        return float(self.samples.shape[0] / self.sample_rate)

    def channel(self, index: int) -> np.ndarray:
        if not 0 <= index < self.channels:
            raise IndexError(tf('声道索引越界：{index}', index=(index)))
        return self.samples[:, index].copy()

    def quality_report(self) -> list[dict[str, Any]]:
        reports = []
        for index in range(self.channels):
            x = self.channel(index)
            finite = np.isfinite(x)
            peak = float(np.max(np.abs(x[finite]))) if finite.any() else float("nan")
            rms = float(np.sqrt(np.mean(x[finite] ** 2))) if finite.any() else float("nan")
            reports.append({
                "channel": index,
                "samples": len(x),
                "peak": peak,
                "rms": rms,
                "dbfs": 20 * np.log10(max(rms, 1e-15)),
                "dc_offset": float(np.mean(x[finite])) if finite.any() else float("nan"),
                "clipped_ratio": float(np.mean(np.abs(x) >= 0.999)),
                "nonfinite_count": int(np.count_nonzero(~finite)),
                "nearly_silent": bool(rms < 1e-5),
                "clipping_warning": bool(np.mean(np.abs(x) >= 0.999) > 1e-4),
            })
        return reports


def read_wav(path: str | Path) -> AudioData:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(tf('音频文件不存在：{source}', source=(source)))
    samples, sample_rate = sf.read(str(source), dtype="float64", always_2d=True)
    info = sf.info(str(source))
    return AudioData(samples, int(sample_rate), source, info.subtype or "")


def write_wav(path: str | Path, samples: np.ndarray, sample_rate: int, subtype: str = "PCM_24") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(samples, dtype=np.float64)
    if data.ndim == 1:
        data = data[:, None]
    if data.size == 0 or data.ndim != 2:
        raise ValueError(tr("没有可写入的音频数据"))
    if not np.isfinite(data).all():
        raise ValueError(tr("音频中含 NaN 或无穷值，无法导出"))
    sf.write(str(target), np.clip(data, -1.0, 1.0), sample_rate, subtype=subtype)
    return target
