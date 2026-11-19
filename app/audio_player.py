"""音频播放：直接用 sounddevice 播放 numpy 数据，无需临时文件。"""
from __future__ import annotations

from core.i18n import tf, tr
import time

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

try:  # 设备缺失时不影响程序其余功能
    import sounddevice as sd
except Exception:  # pragma: no cover - 仅在无声卡环境触发
    sd = None


class AudioPlayer(QObject):
    positionChanged = Signal(float)  # 相对整段音频的绝对时间（秒）
    stateChanged = Signal(str)       # playing / paused / stopped
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._poll)
        self._offset = 0.0
        self._length = 0.0
        self._rate = 0
        self._playing = False
        self._clock = 0.0

    @staticmethod
    def available() -> bool:
        if sd is None:
            return False
        try:
            sd.check_output_settings(device=None, channels=1)
            return True
        except Exception:
            return False

    @property
    def is_playing(self) -> bool:
        return self._playing

    def play(self, samples: np.ndarray, sample_rate: int, offset_seconds: float = 0.0) -> None:
        """播放给定数据；offset_seconds 用于把播放头映射回整段音频的时间轴。"""
        if sd is None:
            raise RuntimeError(tr("当前环境缺少 sounddevice，无法播放音频"))
        data = np.asarray(samples, dtype=np.float32)
        if data.size == 0:
            raise ValueError(tr("没有可播放的数据"))
        if data.ndim == 1:
            data = data[:, None]
        data = np.clip(data, -1.0, 1.0)

        rate = int(sample_rate)
        channels = int(data.shape[1])
        try:
            sd.check_output_settings(device=None, samplerate=rate, channels=channels)
        except Exception:
            # 设备不支持该采样率：按设备默认采样率重采样，仅影响监听，不改动数据
            target = int(round(float(sd.query_devices(kind="output")["default_samplerate"])))
            from math import gcd

            from scipy.signal import resample_poly

            divisor = gcd(target, rate)
            data = resample_poly(data, target // divisor, rate // divisor, axis=0).astype(np.float32)
            rate = target

        self.stop()
        self._offset = float(offset_seconds)
        self._length = float(data.shape[0] / rate)
        self._rate = rate
        sd.play(data, rate, blocking=False)
        # PortAudio 的 stream.time 是全局时钟，不能直接当作播放进度，这里以本地时钟为基准。
        self._clock = time.perf_counter()
        self._playing = True
        self._timer.start()
        self.stateChanged.emit("playing")

    def pause(self) -> None:
        if not self._playing:
            return
        self._timer.stop()
        self._playing = False
        if sd is not None:
            sd.stop()
        self.stateChanged.emit("paused")

    def stop(self) -> None:
        self._timer.stop()
        was_playing = self._playing
        self._playing = False
        if sd is not None:
            try:
                if sd.get_stream() is not None:
                    sd.stop()
            except Exception:
                pass
        if was_playing:
            self.stateChanged.emit("stopped")

    def _poll(self) -> None:
        if sd is None or not self._playing:
            self._timer.stop()
            return
        elapsed = time.perf_counter() - self._clock
        try:
            stream = sd.get_stream()
            active = bool(stream.active) if stream is not None else False
        except Exception:
            active = False
        self.positionChanged.emit(self._offset + min(elapsed, self._length))
        if not active or elapsed >= self._length:
            self.stop()
            self.stateChanged.emit("stopped")
