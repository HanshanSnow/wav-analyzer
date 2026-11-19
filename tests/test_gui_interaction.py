"""界面交互测试：处理中遮罩、分层绘制、裁剪撤销、播放。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from app.main_window import DETAIL_LIMIT, MainWindow
from core.audio_io import read_wav, write_wav

FS = 8000


def _app():
    return QApplication.instance() or QApplication([])


def _pump(milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def _wait_task(window: MainWindow, timeout_ms: int = 20000) -> None:
    loop = QEventLoop()
    probe = QTimer()
    probe.setInterval(30)
    probe.timeout.connect(lambda: loop.quit() if window.task is None else None)
    probe.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    probe.stop()
    _pump(40)


@pytest.fixture()
def tone_file(tmp_path):
    t = np.arange(FS * 2) / FS
    x = 0.4 * np.sin(2 * np.pi * 300 * t)
    x[FS] += 0.8
    path = tmp_path / "tone.wav"
    write_wav(path, x, FS, subtype="PCM_16")
    return path


@pytest.fixture()
def long_tone_file(tmp_path):
    """60 s 信号，用于触发全览抽稀（超过逐点显示阈值）。"""
    t = np.arange(FS * 60) / FS
    x = 0.4 * np.sin(2 * np.pi * 300 * t)
    path = tmp_path / "long_tone.wav"
    write_wav(path, x, FS, subtype="PCM_16")
    return path


def _no_block(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)


def test_busy_overlay_follows_background_task(tone_file, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    _app()
    window = MainWindow()
    window.show()
    window.load_audio(tone_file)
    assert window.busy.isVisible() is False

    # 遮罩在启动后台任务时同步显示，不需要等事件循环
    window.preview_denoise_async()
    assert window.busy.isVisible() is True
    _wait_task(window)
    assert window.busy.isVisible() is False
    assert window.pending_denoise is not None
    window.close()


def test_waveform_switches_between_overview_and_detail(long_tone_file):
    _app()
    window = MainWindow()
    window.show()
    window.load_audio(long_tone_file)

    overview = window.wave_curve.getData()[0]
    assert overview is not None
    # 60 s × 8000 Hz = 480000 点，全览必须已经抽稀
    assert overview.shape[0] < 480_000
    assert overview.shape[0] <= 6001 * 2 + 2

    # 放大到 0.1 s，应改为显示真实采样点
    window.wave_plot.setXRange(0.5, 0.6, padding=0)
    _pump(120)
    detail = window.wave_curve.getData()[0]
    assert detail.shape[0] <= DETAIL_LIMIT
    assert 700 <= detail.shape[0] <= 900

    window.wave_plot.setXRange(0, window.work_duration, padding=0)
    _pump(120)
    assert window.wave_curve.getData()[0].shape[0] == overview.shape[0]
    window.close()


def test_trim_and_undo_restores_length(tone_file, monkeypatch):
    _no_block(monkeypatch)
    _app()
    window = MainWindow()
    window.show()
    window.load_audio(tone_file)
    original = window.processed.shape[0]

    window.region.setRegion([0.5, 1.5])
    window.trim_to_selection()
    _pump(60)
    assert window.processed.shape[0] == FS
    assert window.edit_depth == 1
    assert "已应用 1 次编辑" in window.edit_label.text()

    window.undo()
    _pump(60)
    assert window.processed.shape[0] == original
    assert window.edit_depth == 0
    assert window.undo_stack == []
    window.close()


def test_trim_then_writeback_creates_backup(tone_file, monkeypatch, tmp_path):
    _no_block(monkeypatch)
    _app()
    window = MainWindow()
    window.show()
    window.load_audio(tone_file)

    window.region.setRegion([0.2, 0.7])
    window.trim_to_selection()
    _pump(60)
    window.apply_changes_to_source()
    _wait_task(window)

    assert read_wav(tone_file).samples.shape[0] == int(0.5 * FS)
    backups = sorted(tmp_path.glob("*.bak-*"))
    assert len(backups) == 1
    assert read_wav(backups[0]).samples.shape[0] == FS * 2
    assert window.edit_depth == 0
    window.close()


def test_writeback_blocked_without_edits(tone_file, monkeypatch):
    calls = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: calls.append(a) or QMessageBox.Ok)
    _app()
    window = MainWindow()
    window.show()
    window.load_audio(tone_file)
    window.apply_changes_to_source()
    assert calls, "未编辑时应当提示无需写回"
    window.close()


def test_playback_start_pause_stop(tone_file, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    _app()
    window = MainWindow()
    window.show()
    window.load_audio(tone_file)

    from app.audio_player import AudioPlayer

    if not AudioPlayer.available():
        pytest.skip("当前环境没有可用音频输出设备")

    window.region.setRegion([0.0, 1.2])
    window.toggle_play()
    _pump(200)
    assert window.player.is_playing is True
    assert window.play_line.isVisible() is True
    assert window.play_button.text().startswith("⏸")
    position = window.play_line.value()
    assert -0.05 <= position <= 1.3

    window.toggle_play()  # 暂停
    _pump(80)
    assert window.player.is_playing is False
    assert window.play_button.text().startswith("▶")

    window.stop_play()
    _pump(60)
    assert window.play_line.isVisible() is False
    window.close()
