"""声音实验信号处理核心。"""

from .audio_io import AudioData, read_wav, write_wav
from .spectral import FourierResult, fourier_analysis, stft_spectrogram
from .denoise import DenoiseResult, ImpulseEvent, detect_and_repair_impulses
from .envelope import EnvelopeFit, compute_envelope, fit_envelope
from .statistics import interval_statistics, probe_time

__all__ = [
    "AudioData", "read_wav", "write_wav", "FourierResult", "fourier_analysis",
    "stft_spectrogram", "DenoiseResult", "ImpulseEvent", "detect_and_repair_impulses",
    "EnvelopeFit", "compute_envelope", "fit_envelope", "interval_statistics", "probe_time",
]
