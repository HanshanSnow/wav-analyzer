"""多格式输入：FLAC / AIFF 读取、错误文案、多声道选择。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
import soundfile as sf
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from core.audio_io import read_wav, write_wav


def _tone(fs: int = 48000, seconds: float = 0.2, freq: float = 1000.0) -> np.ndarray:
    t = np.arange(int(fs * seconds)) / fs
    return 0.4 * np.sin(2 * np.pi * freq * t)


@pytest.mark.parametrize(
    ("suffix", "fmt", "subtype"),
    [(".wav", "WAV", "PCM_24"), (".flac", "FLAC", "PCM_24"), (".aiff", "AIFF", "PCM_24")],
)
def test_reads_wav_flac_aiff(tmp_path, suffix, fmt, subtype):
    source = tmp_path / f"probe{suffix}"
    data = _tone()
    sf.write(str(source), data, 48000, format=fmt, subtype=subtype)

    audio = read_wav(source)

    assert audio.sample_rate == 48000
    assert audio.channels == 1
    assert audio.subtype.upper() == subtype
    assert audio.samples.shape == (data.size, 1)
    assert audio.source_path == source


def test_missing_file_says_audio_not_wav(tmp_path):
    with pytest.raises(FileNotFoundError) as excinfo:
        read_wav(tmp_path / "nope.wav")

    assert "音频文件不存在" in str(excinfo.value)


def test_gui_opens_flac(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "tone.flac"
    sf.write(str(source), _tone(), 48000, format="FLAC", subtype="PCM_24")

    window = MainWindow()
    try:
        window.load_audio(source)
        assert window.audio.channels == 1
        assert window.audio.subtype.upper() == "PCM_24"
        assert abs(window.fourier.main_frequency - 1000.0) < 0.5
    finally:
        window.close()
        app.processEvents()


def test_three_channel_file_can_pick_channel(tmp_path):
    app = QApplication.instance() or QApplication([])
    base = _tone(seconds=0.2)
    data = np.column_stack([base, base * 0.5, base * 0.25])
    source = tmp_path / "three.wav"
    write_wav(source, data, 48000)

    window = MainWindow()
    try:
        window.load_audio(source)
        assert window.audio.channels == 3
        assert window.channel_combo.count() == 3

        # 信号会启动后台线程，而 closeEvent 在带任务时会弹模态框等 20 s；
        # 测试里屏蔽信号后手动走同步分析，验证换道确实是换数据。
        window.channel_combo.blockSignals(True)
        window.channel_combo.setCurrentIndex(2)
        window.channel_combo.blockSignals(False)
        window.refresh_all()

        assert abs(float(np.max(np.abs(window.current_samples()))) - 0.1) < 0.01
        assert abs(window.fourier.main_frequency - 1000.0) < 0.5
    finally:
        window.close()
        app.processEvents()
