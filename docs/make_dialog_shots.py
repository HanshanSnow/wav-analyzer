"""生成手册用的对话框截图。

手册里的界面图必须跟着对话框一起更新，否则文字描述和图对不上。
抓图必须在原生 windows 平台下做：offscreen 平台查不到任何系统字体，
中文会全部渲染成方框（QFontDatabase.families() 返回 0 项）。
窗口移到屏幕外再抓，避免打扰。

用法（在项目根目录）：
    python docs/make_dialog_shots.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 2 倍缩放，抓出来的图放进 PDF 不糊。
os.environ.setdefault("QT_SCALE_FACTOR", "2")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor, QFont, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

SHOT_LANG = (os.environ.get("SHOT_LANG") or "zh").strip().lower()
_IS_EN = SHOT_LANG == "en"
# 英文手册用 figures_en/，中文手册用 figures/
OUT = ROOT / "docs" / ("figures_en" if _IS_EN else "figures")


def msg(zh: str, en: str) -> str:
    return en if _IS_EN else zh


def light_palette() -> QPalette:
    """手动指定浅色调色板。系统处于深色模式时，Fusion 会跟着变暗，
    手册里的界面图必须是浅色，否则打印出来一片黑。"""
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
    widget.adjustSize()
    widget.move(-20000, -20000)
    widget.show()
    QApplication.processEvents()
    pixmap = widget.grab()
    pixmap.save(str(path), "PNG")
    print(f"{path.name}: {pixmap.width()}x{pixmap.height()}")
    widget.hide()


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(light_palette())
    app.setFont(QFont("Microsoft YaHei", 9))

    from core.i18n import set_language

    # 必须在 import app.* 之前：界面文案常量在 import 时求值
    set_language(SHOT_LANG)

    from app.image_export_dialog import ImageExportDialog
    from app.txt_export_dialog import TxtExportDialog

    image_dialog = ImageExportDialog(
        default_kind="wave",
        default_path=str(ROOT / "demo" / "demo_impulse_wave.png"),
        available={"original": True, "preview": True, "envelope": True, "fit": True},
    )
    shoot(image_dialog, OUT / "07_export_dialog.png")

    txt_dialog = TxtExportDialog(
        duration=12.5,
        sample_rate=48000,
        total_samples=600000,
        source_path=ROOT / "demo" / "demo_impulse_wave.wav",
        edited=True,
        region=(3.2, 8.6),
        available={"envelope": True, "fourier": True, "stats": True,
                   "dual": False, "ai": True, "denoise": True, "coords": True},
    )
    shoot(txt_dialog, OUT / "08_txt_export_dialog.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
