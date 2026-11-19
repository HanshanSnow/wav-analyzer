"""生成 README 用的主界面截图。

和 make_batch_shots.py 一样必须在原生 windows 平台跑（offscreen 查不到中文字体，
截出来全是方框），窗口移到屏幕外抓图，不打扰。

用法（项目根目录）：
    python docs/make_readme_shots.py
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
    """抓图后缩到 target_width：README 不需要 4800 宽的图，文件也小一半。"""
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
    # show 之后再 resize：先 resize 会被窗口管理器按屏幕可用区域回缩
    window.resize(1840, 1500)
    QApplication.processEvents()
    print("实际窗口:", window.width(), "x", window.height())

    # 关掉 AI 面板：主界面截图只讲“分析”，侧栏空着还会把左侧挤窄
    for dock in window.findChildren(QDockWidget):
        dock.hide()
    QApplication.processEvents()

    demo = ROOT / "demo" / "demo_tone.wav"
    if demo.exists():
        window.load_audio(demo)
        QApplication.processEvents()

    # 左侧控制栏按设计宽度摆正，否则会被挤成带横向滚动条的窄条
    central = window.centralWidget()
    if isinstance(central, QSplitter):
        central.setSizes([470, 1370])
        QApplication.processEvents()

    # 状态栏会打印源文件全路径，换成本机路径会泄露到公开仓库里
    window.statusBar().showMessage("已载入 demo_tone.wav｜1.0 s / 48000 Hz｜主频 1000.00 Hz")

    window.tabs.setCurrentIndex(1)  # 傅立叶分析
    QApplication.processEvents()
    shoot(window, OUT / "00_overview.png")

    window.tabs.setCurrentIndex(0)  # 波形与选区
    QApplication.processEvents()
    shoot(window, OUT / "00_waveform.png")

    window.hide()


if __name__ == "__main__":
    main()
