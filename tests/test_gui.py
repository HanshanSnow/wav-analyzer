import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from core.audio_io import write_wav


def test_gui_load_analyze_denoise_envelope(tmp_path):
    app = QApplication.instance() or QApplication([])
    fs = 44100
    t = np.arange(fs // 10) / fs
    x = 0.4 * np.sin(2 * np.pi * 1000 * t)
    damaged = x.copy()
    damaged[1500] += 0.8
    source = tmp_path / "gui_input.wav"
    write_wav(source, damaged, fs)

    window = MainWindow()
    window.load_audio(source)
    assert window.audio.channels == 1
    assert abs(window.fourier.main_frequency - 1000) < 0.2
    assert window.stats_table.rowCount() > 10
    window.preview_denoise()
    assert window.pending_denoise is not None
    assert window.pending_denoise.events
    window.apply_denoise()
    assert window.last_denoise is not None
    assert window.apply_button.isEnabled() is False
    window.fit_current_envelope()
    assert window.envelope_fit is not None
    assert window.envelope_fit.rmse < 0.01
    window.undo()
    assert window.undo_stack == []
    window.close()
    app.processEvents()
