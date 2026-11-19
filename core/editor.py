"""非破坏性编辑的纯逻辑：裁剪、写回源文件。所有函数不依赖 Qt，便于测试。"""
from __future__ import annotations

from core.i18n import tf, tr
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from .audio_io import write_wav


@dataclass
class TrimResult:
    samples: np.ndarray
    valid_mask: np.ndarray
    start_sample: int
    end_sample: int
    start_seconds: float
    end_seconds: float

    @property
    def kept_samples(self) -> int:
        return int(self.samples.shape[0])


def trim_range(
    samples: np.ndarray,
    valid_mask: np.ndarray,
    sample_rate: int,
    start_seconds: float,
    end_seconds: float,
) -> TrimResult:
    """按时间区间裁剪工作数据，返回新数组（不修改输入）。"""
    if sample_rate <= 0:
        raise ValueError(tr("采样率无效"))
    data = np.asarray(samples, dtype=np.float64)
    if data.ndim != 2:
        raise ValueError(tr("音频数据必须是 [采样点, 声道] 二维数组"))
    mask = np.asarray(valid_mask, dtype=bool)
    if mask.shape != data.shape:
        raise ValueError(tr("有效区间掩码形状与音频不一致"))

    total = data.shape[0]
    start = int(round(max(0.0, float(start_seconds)) * sample_rate))
    end = int(round(min(total / sample_rate, float(end_seconds)) * sample_rate))
    start = max(0, min(start, total))
    end = max(0, min(end, total))
    if end - start < 2:
        raise ValueError(tr("裁剪区间太短，至少需要 2 个采样点"))

    return TrimResult(
        samples=data[start:end].copy(),
        valid_mask=mask[start:end].copy(),
        start_sample=start,
        end_sample=end,
        start_seconds=start / sample_rate,
        end_seconds=end / sample_rate,
    )


def backup_path_for(source: Path) -> Path:
    """写回前生成不冲突的备份文件名，例如 sample.bak-20261117-195312.wav。"""
    source = Path(source)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = source.with_name(f"{source.stem}.bak-{stamp}{source.suffix}")
    index = 1
    while candidate.exists():
        candidate = source.with_name(f"{source.stem}.bak-{stamp}-{index}{source.suffix}")
        index += 1
    return candidate


def apply_to_source(source: Path, samples: np.ndarray, sample_rate: int, subtype: str = "") -> Path:
    """把工作数据写回源 WAV，先做同目录备份。返回备份文件路径。"""
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(tf('源文件不存在：{source}', source=(source)))
    data = np.asarray(samples, dtype=np.float64)
    if data.size == 0:
        raise ValueError(tr("没有可写回的数据"))
    if not np.isfinite(data).all():
        raise ValueError(tr("数据含 NaN 或无穷值，已取消写回"))

    backup = backup_path_for(source)
    backup.write_bytes(source.read_bytes())

    # 保持原文件的量化格式；浮点格式统一写成 PCM_24，避免削顶失真累积。
    target_subtype = subtype if subtype.startswith("PCM") else "PCM_24"
    write_wav(source, data, sample_rate, subtype=target_subtype)
    return backup


def file_format_info(path: Path) -> str:
    info = sf.info(str(path))
    return tf('{_v0} / {_v1} Hz / {_v2} 声道', _v0=(info.subtype), _v1=(info.samplerate), _v2=(info.channels))
