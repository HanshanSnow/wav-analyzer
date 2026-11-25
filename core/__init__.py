"""声音实验信号处理核心。

导出符号采用**惰性加载**（PEP 562）：只 `import core` 时不会连带导入
NumPy/SciPy 的一整串模块。启动路径上语言设置只需要 `core.i18n`，
以前却因为这里的急切导入多花约 1.3 s（Optimize_Advice P1）。
`from core import read_wav` 仍然照常工作。
"""

from __future__ import annotations

import importlib

_EXPORTS = {
    "AudioData": (".audio_io", "AudioData"),
    "read_wav": (".audio_io", "read_wav"),
    "write_wav": (".audio_io", "write_wav"),
    "FourierResult": (".spectral", "FourierResult"),
    "fourier_analysis": (".spectral", "fourier_analysis"),
    "stft_spectrogram": (".spectral", "stft_spectrogram"),
    "DenoiseResult": (".denoise", "DenoiseResult"),
    "ImpulseEvent": (".denoise", "ImpulseEvent"),
    "detect_and_repair_impulses": (".denoise", "detect_and_repair_impulses"),
    "EnvelopeFit": (".envelope", "EnvelopeFit"),
    "compute_envelope": (".envelope", "compute_envelope"),
    "fit_envelope": (".envelope", "fit_envelope"),
    "interval_statistics": (".statistics", "interval_statistics"),
    "probe_time": (".statistics", "probe_time"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(target[0], __name__)
    value = getattr(module, target[1])
    globals()[name] = value  # 缓存，后续访问不再走这里
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
