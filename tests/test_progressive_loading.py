"""渐进加载的回归测试（BUG：第二阶段从未启动）。

历史：`run_task` 在 `if self.task is not None: return False` 处挡住了第二阶段——
`succeeded` 回调执行时第一个 worker 还没收到 `finished`，`self.task` 非空。
结果是文件信息与波形出来了，但傅立叶分析、时频图、区间统计永远停在「…」。
这些测试盯住"载入后页签必须清掉省略号，且三份分析结果都落地"。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from core.audio_io import write_wav

FS = 48000
ELLIPSIS = "\u2026"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _tone(path, seconds=2.0, fs=FS):
    t = np.arange(int(fs * seconds)) / fs
    x = 0.3 * np.sin(2 * np.pi * 1000 * t) + 0.1 * np.sin(2 * np.pi * 3000 * t)
    write_wav(path, x[:, None], fs, subtype="PCM_16")
    return path


def _load_and_wait(window: MainWindow, path, timeout_ms: int = 20000) -> bool:
    """载入并等到第二阶段结束；返回是否在超时前完成。"""
    window.load_audio_async(path)
    loop = QEventLoop()
    finished = {"done": False}

    def probe() -> None:
        if window.fourier is not None and not window.busy_running():
            finished["done"] = True
            loop.quit()

    timer = QTimer()
    timer.setInterval(30)
    timer.timeout.connect(probe)
    timer.start()
    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(loop.quit)
    guard.start(timeout_ms)
    loop.exec()
    timer.stop()
    return finished["done"]


def test_async_load_finishes_all_three_stages(app, tmp_path):
    window = MainWindow()
    assert _load_and_wait(window, _tone(tmp_path / "a.wav"))
    tabs = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert not any(text.endswith(ELLIPSIS) for text in tabs), f"页签仍停在加载态：{tabs}"
    assert window.fourier is not None
    assert window.overview is not None
    assert window.statistics is not None
    window.close()
    app.processEvents()


@pytest.mark.parametrize("peaks", [1, 8, 50])
def test_async_load_works_for_any_peak_count(app, tmp_path, peaks):
    """谱峰数量只影响谱峰表，不该影响三份分析是否落地。"""
    window = MainWindow()
    window.peak_count_spin.setValue(peaks)
    assert _load_and_wait(window, _tone(tmp_path / f"p{peaks}.wav"))
    assert window.peak_table.rowCount() == peaks
    tabs = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert not any(text.endswith(ELLIPSIS) for text in tabs)
    window.close()
    app.processEvents()
