"""最新请求必须被执行的回归测试（BUG：异步载入/刷新请求丢失）。

问题：`load_audio_async()` / `refresh_all_async()` 先换代再调 `run_task()`，
而 `run_task()` 在已有 worker 时直接返回 False。于是"在 A 分析期间请求 B"会：
A 的结果被当过期丢弃、B 又没排上队——界面上就是一次永远不结束的加载。

这里用门闩卡住第一次分析，复现"正在跑 A 时请求 B"，再放行，验证 B 终被载入并
完整分析、页签清空、没有遗留 worker。
"""

from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

import app.main_window as main_window_module
from app.main_window import MainWindow
from core.audio_io import write_wav

FS = 48000
ELLIPSIS = "\u2026"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _tone(path, amplitude=0.3, seconds=1.5, fs=FS, channels=1, frequency=1000.0):
    t = np.arange(int(fs * seconds)) / fs
    wave = amplitude * np.sin(2 * np.pi * frequency * t)
    data = np.stack([wave] * channels, axis=1) if channels > 1 else wave[:, None]
    write_wav(path, data, fs, subtype="PCM_16")
    return path


def _wait_until(app, predicate, timeout_ms: int = 20000) -> bool:
    """泵事件直到 predicate 为真；返回是否在超时前满足。"""
    if predicate():
        return True
    loop = QEventLoop()
    state = {"ok": False}
    timer = QTimer()
    timer.setInterval(20)

    def probe() -> None:
        if predicate():
            state["ok"] = True
            loop.quit()

    timer.timeout.connect(probe)
    timer.start()
    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(loop.quit)
    guard.start(timeout_ms)
    loop.exec()
    timer.stop()
    state["ok"] = predicate()
    return state["ok"]


def _tabs(app, window: MainWindow) -> list[str]:
    return [window.tabs.tabText(i) for i in range(window.tabs.count())]


def test_latest_load_request_is_not_lost(app, tmp_path, monkeypatch):
    gate = threading.Event()
    calls = {"n": 0}
    real = main_window_module._analyze_channel

    def gated(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            gate.wait(10)  # 卡住第一次分析，模拟"正在算 A"
        return real(*args, **kwargs)

    monkeypatch.setattr(main_window_module, "_analyze_channel", gated)

    first = _tone(tmp_path / "a.wav", amplitude=0.3)
    second = _tone(tmp_path / "b.wav", amplitude=0.05)

    window = MainWindow()
    window.show()
    window.load_audio_async(first)
    assert _wait_until(app, lambda: calls["n"] >= 1), "第一次分析没有开始"

    # A 的分析还在跑：现在请求 B
    window.load_audio_async(second)
    gate.set()

    ok = _wait_until(app, lambda: (window.audio is not None
                                   and window.audio.source_path.name == "b.wav"
                                   and window.fourier is not None
                                   and not window.busy_running()))
    assert ok, (f"B 没有被载入并分析：当前={getattr(window.audio, 'source_path', None)}, "
                f"fourier={window.fourier is not None}")
    # 两个文件同为 1000 Hz（界面有已知激励频率约束），用幅值区分：B 是 0.05
    assert window.fourier.main_amplitude == pytest.approx(0.05, abs=0.005), \
        f"应用的不是 B 的结果（主频幅值 {window.fourier.main_amplitude:.3f}）"
    tabs = _tabs(app, window)
    assert not any(text.endswith(ELLIPSIS) for text in tabs), f"页签仍在加载态：{tabs}"
    assert window.task is None, "分析结束后不应残留 worker"
    window.close()
    app.processEvents()


def test_latest_channel_request_is_not_lost(app, tmp_path, monkeypatch):
    gate = threading.Event()
    calls = {"n": 0}
    real = main_window_module._analyze_channel

    def gated(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            gate.wait(10)
        return real(*args, **kwargs)

    monkeypatch.setattr(main_window_module, "_analyze_channel", gated)

    # 两声道幅度不同：切声道后主频幅值应随之改变，能证明分析用的是新声道
    t = np.arange(int(FS * 1.5)) / FS
    stereo_path = tmp_path / "stereo.wav"
    write_wav(stereo_path,
              np.stack([0.3 * np.sin(2 * np.pi * 1000 * t),
                        0.15 * np.sin(2 * np.pi * 1000 * t)], axis=1),
              FS, subtype="PCM_16")
    window = MainWindow()
    window.show()
    window.load_audio_async(stereo_path)
    assert _wait_until(app, lambda: calls["n"] >= 1)

    # 第一次分析还卡着：切到第 2 声道（触发 refresh_all_async）
    window.channel_combo.setCurrentIndex(1)
    gate.set()

    ok = _wait_until(app, lambda: window.fourier is not None and not window.busy_running())
    assert ok
    assert window.channel_combo.currentIndex() == 1
    # 第 2 声道减半：主频幅值应反映新声道（0.15 而不是 0.3）
    assert window.fourier.main_amplitude == pytest.approx(0.15, abs=0.02)
    tabs = _tabs(app, window)
    assert not any(text.endswith(ELLIPSIS) for text in tabs), f"页签仍在加载态：{tabs}"
    assert window.task is None
    window.close()
    app.processEvents()
