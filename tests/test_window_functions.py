"""窗函数：可选项、主频一致性、非法窗名、时频图是否真的换窗、导出是否记录窗名。"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.spectral import fourier_analysis, stft_spectrogram  # noqa: E402

FS = 48000
F0 = 1000.0


def _tone(seconds: float = 0.5, amplitude: float = 0.4) -> np.ndarray:
    t = np.arange(int(FS * seconds)) / FS
    return amplitude * np.sin(2 * np.pi * F0 * t)


@pytest.mark.parametrize("window", ["hann", "hamming", "blackman", "boxcar"])
def test_every_window_keeps_the_main_frequency(window: str) -> None:
    result = fourier_analysis(_tone(), FS, window=window)
    assert abs(result.main_frequency - F0) <= 1.0
    assert result.window == window


def test_hann_golden_values_are_unchanged() -> None:
    """v1.6.1 的默认路径（hann）必须逐字段稳定：换窗功能不能顺手改掉旧数值。

    信号取 4800 点（bin 宽正好 10 Hz，1 kHz 与 3 kHz 都落在整数 bin 上），
    这样主频与幅值不受泄漏影响，可以钉死到小数点后。
    """
    n = 4800
    t = np.arange(n) / FS
    x = 0.4 * np.sin(2 * np.pi * F0 * t) + 0.1 * np.sin(2 * np.pi * 3 * F0 * t) + 0.05

    result = fourier_analysis(x, FS, fundamental_frequency=F0)

    assert result.window == "hann"
    assert result.n_fft == n
    assert result.main_frequency == pytest.approx(1000.0, abs=1e-6)
    assert result.main_amplitude == pytest.approx(0.4, rel=1e-3)
    assert result.fundamental_frequency == pytest.approx(1000.0, abs=1e-6)
    assert result.thd == pytest.approx(0.25, rel=1e-2)


def test_spectrogram_honours_the_window() -> None:
    x = _tone()
    _, frequencies, hann_db = stft_spectrogram(x, FS, nperseg=1024, window="hann")
    _, _, boxcar_db = stft_spectrogram(x, FS, nperseg=1024, window="boxcar")
    assert not np.allclose(hann_db, boxcar_db)
    # S_db 的布局是 (频率, 时间)，与 stft 返回的频率轴对齐。
    assert hann_db.shape[0] == frequencies.size
    # 矩形窗旁瓣泄漏大：离开 1 kHz 后残余电平应明显高于汉宁窗。
    far = (frequencies > 1_500) & (frequencies < 2_000)
    assert np.median(boxcar_db[far, :]) > np.median(hann_db[far, :]) + 10.0


@pytest.mark.parametrize("bad", ["hannn", "triangular", ""])
def test_unknown_window_is_rejected(bad: str) -> None:
    with pytest.raises(ValueError, match="不支持的窗函数"):
        fourier_analysis(_tone(), FS, window=bad)
    with pytest.raises(ValueError, match="不支持的窗函数"):
        stft_spectrogram(_tone(), FS, window=bad)


def test_gui_offers_windows_and_exports_the_chosen_one(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    from core.audio_io import write_wav
    from app.main_window import SPECTRUM_WINDOWS, MainWindow

    app = QApplication.instance() or QApplication([])
    source = tmp_path / "tone.wav"
    write_wav(source, _tone(0.2)[:, None], FS)

    window = MainWindow()
    try:
        window.load_audio(source)
        assert window.window_combo.count() == len(SPECTRUM_WINDOWS)
        assert window.spectrum_window == "hann"

        window.window_combo.blockSignals(True)
        window.window_combo.setCurrentIndex(1)
        window.window_combo.blockSignals(False)
        assert window.spectrum_window == "hamming"
        window.refresh_all()
        assert window.fourier is not None and window.fourier.window == "hamming"

        target = tmp_path / "statistics.csv"
        monkeypatch.setattr(
            "app.main_window.QFileDialog.getSaveFileName",
            lambda *args, **kwargs: (str(target), "CSV (*.csv)"),
        )
        window.calculate_statistics()
        window.export_statistics()
        with target.open(newline="", encoding="utf-8-sig") as handle:
            row = next(csv.DictReader(handle))
        assert row["analysis_window"] == "hamming"
    finally:
        window.close()
        app.processEvents()
