"""谱峰数量进工程文件（审计 P2）。

谱峰数量只影响展示：工程里存它只为"重开工程还是同一张谱峰表"。
这里验证：保存写入、恢复读取、旧工程默认 8、越界钳制、且不改变 FFT 结果。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from core.audio_io import write_wav

FS = 48000


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wav(tmp_path, name="p.wav", seconds=1.0):
    path = tmp_path / name
    t = np.arange(int(FS * seconds)) / FS
    x = 0.3 * np.sin(2 * np.pi * 1000 * t) + 0.1 * np.sin(2 * np.pi * 3000 * t)
    write_wav(path, x[:, None], FS, subtype="PCM_16")
    return path


def test_project_saves_peak_count(app, tmp_path):
    window = MainWindow()
    window.load_audio(_wav(tmp_path))
    window.peak_count_spin.setValue(1)
    project = window._project_payload()
    assert project["analysis"]["peak_count"] == 1
    window.close()
    app.processEvents()


@pytest.mark.parametrize("saved", [1, 50])
def test_project_restores_peak_count(app, tmp_path, saved):
    window = MainWindow()
    window.load_audio(_wav(tmp_path, f"r{saved}.wav"))
    window.peak_count_spin.setValue(8)
    project = window._project_payload()
    project["analysis"]["peak_count"] = saved

    window.peak_count_spin.setValue(3)     # 故意改成别的值
    window._apply_project(project)

    assert window.peak_count_spin.value() == saved
    assert window.peak_table.rowCount() <= saved
    window.close()
    app.processEvents()


def test_old_project_without_peak_count_defaults_to_eight(app, tmp_path):
    window = MainWindow()
    window.load_audio(_wav(tmp_path, "old.wav"))
    project = window._project_payload()
    project["analysis"].pop("peak_count", None)   # 模拟旧工程

    window.peak_count_spin.setValue(50)
    window._apply_project(project)
    assert window.peak_count_spin.value() == 8
    window.close()
    app.processEvents()


def test_out_of_range_peak_count_is_clamped(app, tmp_path):
    window = MainWindow()
    window.load_audio(_wav(tmp_path, "clamp.wav"))
    project = window._project_payload()
    project["analysis"]["peak_count"] = 500
    window._apply_project(project)
    assert window.peak_count_spin.value() == 100
    window.close()
    app.processEvents()


def test_restoring_peak_count_does_not_change_fft(app, tmp_path):
    window = MainWindow()
    window.load_audio(_wav(tmp_path, "fft.wav"))
    before = window.fourier.main_frequency
    project = window._project_payload()
    project["analysis"]["peak_count"] = 37
    window._apply_project(project)
    assert window.fourier.main_frequency == pytest.approx(before, rel=0, abs=1e-9)
    window.close()
    app.processEvents()
