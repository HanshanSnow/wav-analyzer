"""生成批量处理相关界面图（脚本编辑对话框 + 进度遮罩），供目视验收与手册配图。

抓图必须在原生 windows 平台下做：offscreen 平台查不到系统字体，中文会全变成方框。
窗口移到屏幕外再抓，避免打扰。

用法（项目根目录）：
    python docs/make_batch_shots.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 2 倍缩放，抓出来的图放进 PDF 不糊。
os.environ.setdefault("QT_SCALE_FACTOR", "2")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication, QSplitter  # noqa: E402

OUT = ROOT / "docs" / "figures"


def light_palette() -> QPalette:
    """系统深色模式下 Fusion 会跟着变暗，界面图必须固定浅色。"""
    palette = QPalette()
    window, base, text = QColor(0xF0, 0xF0, 0xF0), QColor(0xFF, 0xFF, 0xFF), QColor(0x1A, 0x1A, 0x1A)
    palette.setColor(QPalette.Window, window)
    palette.setColor(QPalette.WindowText, text)
    palette.setColor(QPalette.Base, base)
    palette.setColor(QPalette.AlternateBase, QColor(0xF7, 0xF7, 0xF7))
    palette.setColor(QPalette.Text, text)
    palette.setColor(QPalette.Button, window)
    palette.setColor(QPalette.ButtonText, text)
    palette.setColor(QPalette.ToolTipBase, base)
    palette.setColor(QPalette.ToolTipText, text)
    palette.setColor(QPalette.Highlight, QColor(0x2F, 0x6F, 0xED))
    palette.setColor(QPalette.HighlightedText, QColor(0xFF, 0xFF, 0xFF))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(0x8A, 0x8A, 0x8A))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(0x8A, 0x8A, 0x8A))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(0x8A, 0x8A, 0x8A))
    return palette


def shoot(widget, path: Path) -> None:
    QApplication.processEvents()
    pixmap = widget.grab()
    pixmap.save(str(path), "PNG")
    print(f"{path.name}: {pixmap.width()}x{pixmap.height()}")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(light_palette())

    from app.batch_dialog import BatchDialog
    from app.main_window import MainWindow
    from core.batch import new_step

    window = MainWindow()
    window.resize(1440, 880)
    window.move(-20000, -20000)
    window.show()
    QApplication.processEvents()

    dialog = BatchDialog(window, default_dir=str(ROOT / "demo"))
    dialog.resize(1010, 730)
    # 截图要确定性：清掉 QSettings 里上次恢复的脚本，画一条本实验真会用的流水线
    dialog.steps = [new_step("denoise"), new_step("stats"),
                    new_step("export_csv"), new_step("export_txt")]
    dialog.steps[1]["params"].update(
        {"region": "trim", "head": 0.2, "tail": 0.2, "fundamental": "name"})
    # 合并文件名保持默认：摘要里少一段文字，列表才不会横向滚动
    dialog.steps[2]["params"].update({"aggregate": "single"})
    dialog.steps[3]["params"].update({"aggregate": "single"})
    dialog.files = [str(ROOT / "demo" / f"sample_1000Hz_r{n}.wav") for n in (1, 2, 3)]
    dialog.files += [str(ROOT / "demo" / f"sample_2000Hz_r{n}.wav") for n in (1, 2)]
    # 配图用中性路径：不暴露作者本机的目录结构与实验命名
    dialog.output_dir.setText(r"D:\data\batch_out")
    dialog._refresh_list()
    dialog.step_list.setCurrentRow(3)
    # 列表默认 320 宽，放不下本实验的步骤摘要；配图里把分割条拉开
    splitter = dialog.findChildren(QSplitter)[0]
    splitter.setSizes([520, 660])
    dialog._refresh_hint()
    dialog.move(-20000, -20000)
    dialog.show()
    QApplication.processEvents()
    shoot(dialog, OUT / "09_batch_dialog.png")
    dialog.hide()

    demo = ROOT / "demo" / "demo_impulse.wav"
    if demo.exists():
        window.load_audio(demo)
        QApplication.processEvents()

    overlay = window.batch_overlay
    overlay.start(130)
    overlay.set_stage("import", 7, 130, "size_P3_1000Hz_D10_r2.wav", 0.0)
    overlay.set_stage("process", 7, 130, "size_P3_1000Hz_D10_r2.wav", 0.62)
    QApplication.processEvents()
    shoot(overlay, OUT / "10_batch_progress.png")
    overlay.finish()


if __name__ == "__main__":
    main()
