"""重拍手册第 3–7 章的界面配图（01–05）。

01–05 是 1.2 时期手工截的，左侧栏后来加了「声学校准」与「界面语言」两个分组，
旧图与当前界面不符。这里用同步接口还原每一章要讲的状态，一次拍齐。

必须在原生 Windows 桌面跑（offscreen 下查不到中文字体，截出来是方框）。
用法（项目根目录）：
    python docs/make_manual_shots.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_SCALE_FACTOR", "2")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication, QDockWidget, QSplitter  # noqa: E402

OUT = ROOT / "docs" / "figures"
DEMO = ROOT / "demo" / "demo_impulse.wav"
DECAY = ROOT / "demo" / "demo_decay.wav"


def ensure_decay_demo(path: Path) -> None:
    """包络章要一张拟合得漂亮的图：稳态正弦的 R² 恒为 0，衰减信号才用得上指数模型。"""
    if path.exists():
        return
    import numpy as np
    import soundfile as sf

    sr = 48000
    t = np.arange(int(0.6 * sr)) / sr
    tone = 0.8 * np.exp(-5.5 * t) * np.sin(2 * np.pi * 500 * t)
    sf.write(path, tone.astype("float32"), sr, subtype="PCM_24")
    print(f"{path.name}: 已生成 0.6 s / 500 Hz 指数衰减信号")


def light_palette() -> QPalette:
    palette = QPalette()
    window, base, text = QColor(0xF0, 0xF0, 0xF0), QColor(0xFF, 0xFF, 0xFF), QColor(0x1A, 0x1A, 0x1A)
    palette.setColor(QPalette.Window, window)
    palette.setColor(QPalette.WindowText, text)
    palette.setColor(QPalette.Base, base)
    palette.setColor(QPalette.AlternateBase, QColor(0xF7, 0xF7, 0xF7))
    palette.setColor(QPalette.Text, text)
    palette.setColor(QPalette.Button, window)
    palette.setColor(QPalette.ButtonText, text)
    palette.setColor(QPalette.Highlight, QColor(0x2F, 0x6F, 0xED))
    palette.setColor(QPalette.HighlightedText, QColor(0xFF, 0xFF, 0xFF))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(0x8A, 0x8A, 0x8A))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(0x8A, 0x8A, 0x8A))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(0x8A, 0x8A, 0x8A))
    return palette


def shoot(widget, path: Path, target_width: int = 1600) -> None:
    QApplication.processEvents()
    pixmap = widget.grab()
    if pixmap.width() > target_width:
        pixmap = pixmap.scaledToWidth(target_width, Qt.SmoothTransformation)
    pixmap.save(str(path), "PNG")
    print(f"{path.name}: {pixmap.width()}x{pixmap.height()}")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(light_palette())

    from app.main_window import MainWindow

    window = MainWindow()
    window.move(-20000, -20000)
    window.show()
    window.resize(1840, 1500)
    QApplication.processEvents()

    for dock in window.findChildren(QDockWidget):
        dock.hide()
    QApplication.processEvents()

    window.load_audio(DEMO)
    QApplication.processEvents()

    central = window.centralWidget()
    if isinstance(central, QSplitter):
        central.setSizes([470, 1370])
        QApplication.processEvents()

    status = "已载入 demo_impulse.wav｜0.2 s / 44100 Hz"
    window.statusBar().showMessage(status)

    # 01：波形与去噪预览。选区取末段 180–190 ms，蓝色区与橙色预览都能看清
    window.tabs.setCurrentIndex(0)
    window.region.setRegion([0.180, 0.190])
    QApplication.processEvents()
    window.preview_denoise()
    QApplication.processEvents()
    window.statusBar().showMessage(status + "｜预览完成：2 段冲击（橙色曲线为预览，未写入数据）")
    shoot(window, OUT / "01_waveform_denoise.png")

    # 02：傅立叶分析
    window.region.setRegion([0.0, 0.2])
    window.tabs.setCurrentIndex(1)
    QApplication.processEvents()
    shoot(window, OUT / "02_fourier.png")

    # 03：时频图
    window.tabs.setCurrentIndex(2)
    QApplication.processEvents()
    shoot(window, OUT / "03_spectrogram.png")

    # 04：区间统计表
    window.tabs.setCurrentIndex(3)
    QApplication.processEvents()
    window.calculate_statistics()
    QApplication.processEvents()
    shoot(window, OUT / "04_statistics.png")

    # 05：包络与拟合。换指数衰减信号，模型选 exponential，R² 才有说服力
    ensure_decay_demo(DECAY)
    window.load_audio(DECAY)
    QApplication.processEvents()
    window.region.setRegion([0.0, 0.6])
    window.fundamental.setValue(500.0)
    window.envelope_model.setCurrentText("exponential")
    window.tabs.setCurrentIndex(0)
    QApplication.processEvents()
    window.fit_current_envelope()
    QApplication.processEvents()
    window.statusBar().showMessage("已载入 demo_decay.wav｜0.6 s / 48000 Hz｜指数包络拟合")
    shoot(window, OUT / "05_envelope.png")

    window.hide()


if __name__ == "__main__":
    main()
