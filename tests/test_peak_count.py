"""谱峰数量（P2-④）：默认 8，范围 1–100，只影响展示与导出，不重算 FFT。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from core.data_export import export_peaks_csv
from core.spectral import fourier_analysis


def _app():
    return QApplication.instance() or QApplication([])


def _tone_with_harmonics(seconds=0.5, sample_rate=8000):
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    return (0.4 * np.sin(2 * np.pi * 1000 * t)
            + 0.2 * np.sin(2 * np.pi * 2000 * t)
            + 0.1 * np.sin(2 * np.pi * 3000 * t))


def _peak_rows(path):
    """只数谱峰行：表头与 # 注释不算，谐波行由 harmonic 列是否为 0 区分。"""
    import csv as _csv

    lines = [line for line in path.read_text(encoding="utf-8-sig").splitlines()
             if line and not line.startswith("#")]
    rows = list(_csv.DictReader(lines))
    return [row for row in rows if not str(row.get("harmonic") or "").strip()
            or str(row.get("harmonic")).strip() == "0"]


def test_peak_csv_default_is_eight(tmp_path):
    fourier = fourier_analysis(_tone_with_harmonics(), 8000, fundamental_frequency=1000.0)
    path = export_peaks_csv(tmp_path / "peaks.csv", fourier, include_harmonics=False)
    assert len(_peak_rows(path)) == 8, "默认应导出 8 个谱峰"


def test_peak_csv_follows_requested_count(tmp_path):
    fourier = fourier_analysis(_tone_with_harmonics(), 8000, fundamental_frequency=1000.0)
    one = export_peaks_csv(tmp_path / "one.csv", fourier, include_harmonics=False, peak_count=1)
    assert len(_peak_rows(one)) == 1

    many = export_peaks_csv(tmp_path / "many.csv", fourier, include_harmonics=False, peak_count=40)
    # 请求数超过真实峰数时按实际数量返回，不补空行
    assert 1 <= len(_peak_rows(many)) <= 40


def test_txt_and_image_dialogs_carry_peak_count(tmp_path):
    from app.image_export_dialog import ImageExportDialog
    from app.txt_export_dialog import TxtExportDialog

    _app()
    image = ImageExportDialog(peak_count=3)
    assert image.options().peak_count == 3
    image.deleteLater()

    txt = TxtExportDialog(duration=1.0, sample_rate=8000, total_samples=8000, peak_count=5)
    assert txt.options().peak_count == 5
    txt.deleteLater()


def test_changing_peak_count_does_not_recompute_fft(monkeypatch):
    _app()
    from app import main_window as mw

    window = mw.MainWindow()
    fourier = fourier_analysis(_tone_with_harmonics(), 8000, fundamental_frequency=1000.0)
    window.fourier = fourier

    def boom(*_args, **_kwargs):
        raise AssertionError("改峰数不应该重算 FFT")

    monkeypatch.setattr(mw, "fourier_analysis", boom)
    window._peak_count_changed(2)
    assert window.peak_table.rowCount() == 2
    window._peak_count_changed(1000)  # 超出真实峰数也不应抛错
    window.deleteLater()
