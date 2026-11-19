from __future__ import annotations

from core.i18n import tf, tr
from typing import Any

from .audio_io import AudioData


def analyze_dual_channel(audio: AudioData, fundamental_frequency: float) -> dict[str, Any]:
    if audio.channels != 2:
        raise ValueError(tr("双通道分析需要左右两个声道"))
    if fundamental_frequency <= 0:
        raise ValueError(tr("双通道分析需要已知激励频率"))
    from analyze import estimate_delay, level_db

    reference = audio.channel(0)
    received = audio.channel(1)
    delay, quality, warning, window, ref_filtered, recv_filtered = estimate_delay(
        reference, received, audio.sample_rate, fundamental_frequency
    )
    ref_db = level_db(ref_filtered)
    recv_db = level_db(recv_filtered)
    return {
        "fundamental_frequency_hz": fundamental_frequency,
        "delay_us": delay * 1e6,
        "peak_quality": quality,
        "search_window_us": window * 1e6,
        "reference_dbfs": ref_db,
        "received_dbfs": recv_db,
        "level_difference_db": ref_db - recv_db,
        "warning": warning,
        "note": tr("未扣除零时延标定；MAX9814 AGC 工作时幅值比不可直接视为隔声量。"),
    }
