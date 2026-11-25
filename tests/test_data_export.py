"""导出原始数据：CSV / NPZ 的列、行数、元数据，以及对话框与主窗口的接线。"""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog

from core.data_export import (
    PEAK_COLUMNS, SPECTRUM_COLUMNS, export_envelope_csv, export_peaks_csv,
    export_spectrogram_npz, export_spectrum_csv, skipped_frames, total_spectrogram_frames,
)
from core.envelope import evaluate_fit, fit_envelope
from core.spectral import MAX_SPECTROGRAM_FRAMES, fourier_analysis, stft_spectrogram


def _tone(frequency=1000.0, seconds=0.2, sample_rate=48000, amplitude=0.4):
    t = np.arange(int(sample_rate * seconds)) / sample_rate
    return np.sin(2 * np.pi * frequency * t) * amplitude


def _tone_with_harmonic(seconds=0.2, sample_rate=48000):
    """基频 0.4 + 三次谐波 0.1，供谐波列与 THD 用。"""
    t = np.arange(int(sample_rate * seconds)) / sample_rate
    return 0.4 * np.sin(2 * np.pi * 1000 * t) + 0.1 * np.sin(2 * np.pi * 3000 * t)


def _read_csv(path):
    # 导出写的是 utf-8-sig（Excel 双击不乱码），读回时同样按它解 BOM。
    text = io.open(path, encoding="utf-8-sig").read()
    header = [line for line in text.splitlines() if not line.startswith("#")]
    return list(csv.DictReader(header)), [line for line in text.splitlines() if line.startswith("#")]


def test_spectrum_csv_has_one_row_per_bin(tmp_path):
    fourier = fourier_analysis(_tone(), 48000)
    target = export_spectrum_csv(tmp_path / "s.csv", fourier)
    rows, meta = _read_csv(target)
    assert list(rows[0].keys()) == list(SPECTRUM_COLUMNS)
    assert len(rows) == fourier.frequencies.size
    assert any("hann" in line for line in meta)
    float(rows[0]["amplitude"])            # 数字可解析，不写科学计数法以外的怪格式


def test_peaks_csv_marks_harmonic_order(tmp_path):
    fourier = fourier_analysis(_tone_with_harmonic(), 48000)
    target = export_peaks_csv(tmp_path / "p.csv", fourier)
    rows, _ = _read_csv(target)
    assert list(rows[0].keys()) == list(PEAK_COLUMNS)
    assert len(rows) == len(fourier.peaks()) + len(fourier.harmonics())
    assert any(row["harmonic"] not in ("", "0") for row in rows)


def test_envelope_csv_leaves_fit_blank_without_model(tmp_path):
    times = np.arange(5) / 10
    values = np.array([1.0, 0.9, 0.8, 0.7, 0.6])
    target = export_envelope_csv(tmp_path / "e.csv", times, values)
    rows, _ = _read_csv(target)
    assert [row["fitted"] for row in rows] == [""] * 5
    assert float(rows[0]["time_s"]) == pytest.approx(0.0)


def test_envelope_csv_rejects_mismatched_lengths(tmp_path):
    with pytest.raises(ValueError, match="包络与时间轴长度不一致"):
        export_envelope_csv(tmp_path / "e.csv", np.arange(3), np.arange(4))


def test_evaluate_fit_reproduces_the_curve_at_any_times():
    times = 1.0 + np.arange(40) / 20
    values = 0.5 + 0.3 * (times - times[0])
    fit = fit_envelope(times, values, "linear")
    np.testing.assert_allclose(evaluate_fit(fit, times), fit.fitted, rtol=1e-12, atol=1e-12)
    wider = np.array([times[0], times[0] + 5.0])
    np.testing.assert_allclose(evaluate_fit(fit, wider), [fit.fitted[0], fit.fitted[0] + 1.5], rtol=1e-9)


def test_skipped_frames_counts_frames_dropped_by_the_cap():
    assert total_spectrogram_frames(48000, 1024, 512) == 1 + (48000 - 1024) // 512
    assert skipped_frames(48000, 1024, 512, 10) == total_spectrogram_frames(48000, 1024, 512) - 10
    assert skipped_frames(1024, 1024, 512, 1) == 0


def test_spectrogram_npz_records_shape_and_skipped(tmp_path):
    samples = _tone(seconds=0.2)
    times, frequencies, levels = stft_spectrogram(samples, 48000)
    target = export_spectrogram_npz(
        tmp_path / "t.npz", times, frequencies, levels,
        nperseg=1024, noverlap=512, sample_rate=48000,
        max_frames=MAX_SPECTROGRAM_FRAMES,
        skipped=skipped_frames(samples.size, 1024, 512, times.size), window="hann",
    )
    with np.load(target) as bundle:
        assert bundle["magnitude_db"].shape == (frequencies.size, times.size)
        assert int(bundle["nperseg"]) == 1024
        assert int(bundle["sample_rate"]) == 48000
        assert str(bundle["window"]) == "hann"
        assert int(bundle["skipped"]) >= 0


def test_spectrogram_npz_rejects_wrong_layout(tmp_path):
    times, frequencies, levels = stft_spectrogram(_tone(), 48000)
    with pytest.raises(ValueError, match="时频矩阵形状"):
        export_spectrogram_npz(tmp_path / "bad.npz", times, frequencies, levels.T,
                               nperseg=1024, noverlap=512, sample_rate=48000,
                               max_frames=MAX_SPECTROGRAM_FRAMES, skipped=0)


# ---------------------------------------------------------------- 对话框
@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _dialog(tmp_path, available, app):
    from app.data_export_dialog import DataExportDialog
    return DataExportDialog(
        None, stem="probe", available=available, default_dir=str(tmp_path),
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat),
    )


def test_dialog_disables_unavailable_results(tmp_path, app):
    dialog = _dialog(tmp_path, {"spectrum": True, "peaks": True, "envelope": False,
                                "spectrogram": False}, app)
    assert dialog._boxes["spectrum"].isEnabled()
    assert not dialog._boxes["envelope"].isEnabled()
    assert not dialog._boxes["envelope"].isChecked()
    assert dialog.checked_kinds() == ["spectrum", "peaks"]
    assert dialog.file_name("spectrum") == "probe_频谱"


def test_dialog_refuses_missing_folder(tmp_path, app):
    dialog = _dialog(tmp_path, {"spectrum": True}, app)
    dialog.folder_edit.setText(str(tmp_path / "does-not-exist"))
    dialog._on_export()
    assert dialog.result() != QDialog.Accepted
    assert dialog.summary.text() == "输出目录不存在"


def test_dialog_accepts_with_folder(tmp_path, app):
    dialog = _dialog(tmp_path, {"spectrum": True}, app)
    dialog._on_export()
    assert dialog.result() == QDialog.Accepted
    assert dialog.output_dir() == str(tmp_path)


# ---------------------------------------------------------------- 主窗口接线
def test_main_window_writes_selected_files(tmp_path, app):
    import soundfile as sf
    from app import main_window as module

    source = tmp_path / "probe.wav"
    sf.write(str(source), _tone(seconds=0.2), 48000, subtype="PCM_24")

    class FakeDialog:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def exec(self):
            return QDialog.Accepted

        def checked_kinds(self):
            return ["spectrum", "peaks", "envelope", "spectrogram"]

        def output_dir(self):
            return str(tmp_path)

        def file_name(self, kind):
            return f"probe_{kind}"

    window = module.MainWindow()
    window.load_audio(source)
    window.fit_current_envelope()
    original = module.DataExportDialog
    module.DataExportDialog = FakeDialog
    try:
        window.export_raw_data()
    finally:
        module.DataExportDialog = original
    window.close()

    for name in ("probe_spectrum.csv", "probe_peaks.csv", "probe_envelope.csv",
                 "probe_spectrogram.npz"):
        assert (tmp_path / name).is_file(), name
    rows, _ = _read_csv(tmp_path / "probe_envelope.csv")
    assert any(row["fitted"] for row in rows)
    with np.load(tmp_path / "probe_spectrogram.npz") as bundle:
        assert bundle["magnitude_db"].ndim == 2


def test_main_window_reports_nothing_to_export(tmp_path, app, monkeypatch):
    import soundfile as sf
    from app import main_window as module

    source = tmp_path / "probe.wav"
    sf.write(str(source), _tone(seconds=0.2), 48000, subtype="PCM_24")
    window = module.MainWindow()
    window.load_audio(source)
    window.fourier = None
    window.spectrogram = None
    window.envelope_values = None
    window.envelope_times = None
    shown: list[str] = []
    monkeypatch.setattr(module.QMessageBox, "information",
                        lambda *args, **kwargs: shown.append(args[2]))
    window.export_raw_data()
    window.close()
    assert shown and "请先完成频谱分析" in shown[0]
