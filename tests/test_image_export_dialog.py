"""导出图像对话框与主窗口导出链路的测试。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app import main_window as main_window_module
from app.image_export_dialog import SIZE_PRESETS, ImageExportDialog, suggest_path
from app.main_window import MainWindow
from core.audio_io import write_wav

FS = 8000


def _app():
    return QApplication.instance() or QApplication([])


def _wait_task(window: MainWindow, timeout_ms: int = 30000) -> None:
    loop = QEventLoop()
    probe = QTimer()
    probe.setInterval(30)
    probe.timeout.connect(lambda: loop.quit() if window.task is None else None)
    probe.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    probe.stop()


@pytest.fixture()
def tone_file(tmp_path):
    t = np.arange(FS * 2) / FS
    x = 0.4 * np.sin(2 * np.pi * 300 * t)
    path = tmp_path / "tone.wav"
    write_wav(path, x, FS, subtype="PCM_16")
    return path


def test_dialog_marks_unavailable_curves(tmp_path):
    _app()
    dialog = ImageExportDialog(
        None, default_kind="wave", default_path=str(tmp_path / "w.png"),
        available={"original": False, "preview": True, "envelope": False, "fit": False},
    )
    selection = dialog.wave_selection()
    assert selection["original"] is False, "无编辑时原始波形与当前波形重合，不应默认勾选"
    assert selection["preview"] is True, "有去噪预览时应默认带上"
    assert dialog.wave_envelope.isEnabled() is False, "没有包络数据时选项必须禁用"
    assert "当前无数据" in dialog.wave_envelope.text()
    assert dialog.selected_kind() == "wave"


def _index_of(predicate) -> int:
    for index, preset in enumerate(SIZE_PRESETS):
        if predicate(preset):
            return index
    raise AssertionError("找不到指定的尺寸预设")


def test_dialog_defaults_to_paper_single_column(tmp_path):
    _app()
    dialog = ImageExportDialog(None, default_path=str(tmp_path / "w.png"))
    options = dialog.options()
    assert (options.layout, options.column) == ("paper", "single")
    assert options.effective_dpi() == 600
    assert options.legend_outside is True, "论文版式图例应在坐标区外"
    assert dialog.width_spin.isEnabled() is False, "论文版式的像素尺寸由物理尺寸决定，不应可改"


def test_dialog_size_preset_and_custom(tmp_path):
    _app()
    dialog = ImageExportDialog(None, default_path=str(tmp_path / "w.png"))
    screen_index = _index_of(lambda p: p[1] == "screen" and p[3] == 1920)
    dialog.size_preset.setCurrentIndex(screen_index)
    assert (dialog.width_spin.value(), dialog.height_spin.value()) == (1920, 1080)
    dialog.width_spin.setValue(2000)
    assert dialog.size_preset.currentIndex() == len(SIZE_PRESETS) - 1, "手改尺寸后预设应切到自定义"
    options = dialog.options()
    assert (options.layout, options.width_px, options.height_px) == ("screen", 2000, 1080)
    assert options.effective_dpi() == 200


def test_dialog_options_follow_controls(tmp_path):
    _app()
    dialog = ImageExportDialog(None, default_kind="spectrum", default_path=str(tmp_path / "s.png"))
    dialog.spectrum_scale.setCurrentIndex(1)
    dialog.spectrum_limit.setValue(5000.0)
    dialog.spectrum_phase.setChecked(True)
    # 深色/透明背景只属于屏幕版式；论文版式固定白底。
    dialog.size_preset.setCurrentIndex(_index_of(lambda p: p[1] == "screen" and p[3] == 1600))
    dialog.background.setCurrentIndex(1)
    options = dialog.options()
    assert options.spectrum_db is False
    assert options.max_frequency == 5000.0
    assert options.show_phase is True
    assert options.background == "dark"


def test_dialog_appends_png_suffix(tmp_path):
    _app()
    dialog = ImageExportDialog(None, default_path=str(tmp_path / "no_ext"))
    assert dialog.output_path().endswith(".png")


def test_suggest_path_uses_kind_and_channel(tmp_path):
    source = tmp_path / "实验数据.wav"
    assert suggest_path(source, "wave").endswith("实验数据_波形.png")
    assert suggest_path(source, "spectrogram").endswith("实验数据_时频图.png")
    assert suggest_path(source, "spectrum", 1).endswith("实验数据_声道2_频谱.png")


def test_window_exports_waveform_png(tone_file, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    _app()
    window = MainWindow()
    window.load_audio(tone_file)
    assert window.fourier is not None

    target = tmp_path / "exported_wave.png"
    monkeypatch.setattr(main_window_module, "suggest_path", lambda *a, **k: str(target))
    monkeypatch.setattr(ImageExportDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(ImageExportDialog, "output_path", lambda self: str(target))
    window.export_image()
    _wait_task(window)
    assert target.exists() and target.stat().st_size > 5_000
    assert "已导出" in window.statusBar().currentMessage()
    window.close()


def test_window_exports_spectrogram_png(tone_file, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    _app()
    window = MainWindow()
    window.load_audio(tone_file)
    assert window.spectrogram is not None, "分析完成后应缓存时频数据供导出复用"

    target = tmp_path / "exported_stft.png"
    monkeypatch.setattr(main_window_module, "suggest_path", lambda *a, **k: str(target))
    monkeypatch.setattr(ImageExportDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(ImageExportDialog, "selected_kind", lambda self: "spectrogram")
    monkeypatch.setattr(ImageExportDialog, "output_path", lambda self: str(target))
    window.export_image()
    _wait_task(window)
    assert target.exists() and target.stat().st_size > 5_000
    window.close()


def test_cancelled_dialog_writes_nothing(tone_file, tmp_path, monkeypatch):
    _app()
    window = MainWindow()
    window.load_audio(tone_file)
    target = tmp_path / "cancelled.png"
    monkeypatch.setattr(main_window_module, "suggest_path", lambda *a, **k: str(target))
    monkeypatch.setattr(ImageExportDialog, "exec", lambda self: QDialog.Rejected)
    window.export_image()
    assert window.task is None, "取消后不应启动后台任务"
    assert not target.exists()
    window.close()
