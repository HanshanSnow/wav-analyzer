"""生成声学校准对话框配图。用法（项目根目录）：

    python docs/make_calib_shots.py
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
from PySide6.QtWidgets import QApplication  # noqa: E402

SHOT_LANG = (os.environ.get("SHOT_LANG") or "zh").strip().lower()
_IS_EN = SHOT_LANG == "en"
# 英文手册用 figures_en/，中文手册用 figures/
OUT = ROOT / "docs" / ("figures_en" if _IS_EN else "figures")


def msg(zh: str, en: str) -> str:
    return en if _IS_EN else zh


def light_palette() -> QPalette:
    palette = QPalette()
    window, base, text = QColor(0xF0, 0xF0, 0xF0), QColor(0xFF, 0xFF, 0xFF), QColor(0x1A, 0x1A, 0x1A)
    palette.setColor(QPalette.Window, window)
    palette.setColor(QPalette.WindowText, text)
    palette.setColor(QPalette.Base, base)
    palette.setColor(QPalette.Text, text)
    palette.setColor(QPalette.Button, window)
    palette.setColor(QPalette.ButtonText, text)
    palette.setColor(QPalette.Highlight, QColor(0x2F, 0x6F, 0xED))
    palette.setColor(QPalette.HighlightedText, QColor(0xFF, 0xFF, 0xFF))
    return palette


def shoot(widget, path: Path, target_width: int = 1280) -> None:
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

    from core.i18n import set_language

    # 必须在 import app.* 之前：界面文案常量在 import 时求值
    set_language(SHOT_LANG)

    from app.calibration_dialog import CalibrationDialog
    from core.calibration import Calibration, MODE_REFERENCE

    dialog = CalibrationDialog(
        None,
        profiles=[Calibration(name=msg("电容麦 + 前置 20 dB", "Condenser mic + 20 dB preamp"),
                              sensitivity_mv_pa=12.6,
                              preamp_gain_db=20.0, adc_full_scale_vrms=1.0)],
        active=msg("电容麦 + 前置 20 dB", "Condenser mic + 20 dB preamp"),
        current_dbfs=-32.47,
    )
    dialog.resize(660, 560)
    dialog.move(-20000, -20000)
    dialog.show()
    QApplication.processEvents()
    shoot(dialog, OUT / "13_calibration.png")
    dialog.hide()

    # 第二张：两点标定那一支
    dialog2 = CalibrationDialog(
        None,
        profiles=[Calibration(name=msg("声级校准器 94 dB", "Sound level calibrator 94 dB"),
                              mode=MODE_REFERENCE,
                              ref_spl_db=94.0, ref_dbfs=-39.98)],
        active=msg("声级校准器 94 dB", "Sound level calibrator 94 dB"),
        current_dbfs=-39.98,
    )
    dialog2.resize(660, 560)
    dialog2.move(-20000, -20000)
    dialog2.show()
    QApplication.processEvents()
    shoot(dialog2, OUT / "14_calibration_ref.png")
    dialog2.hide()


if __name__ == "__main__":
    main()
