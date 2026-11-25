"""生成 AI 助手相关界面图（模型设置对话框 + 会话气泡），供目视验收与手册配图。

抓图必须在原生 windows 平台下做：offscreen 平台查不到系统字体，中文会全变成方框。
窗口移到屏幕外再抓，避免打扰。

用法（项目根目录）：
    python docs/make_ai_shots.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_SCALE_FACTOR", "2")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QFrame  # noqa: E402

from docs.make_batch_shots import OUT, light_palette, msg, shoot  # noqa: E402

# 手册配图里不能出现真 Key，也不能出现本机路径
ANSWER_ZH = """## 结论

`demo_impulse.wav` 采样率 48000 Hz，时长 2.00 s，峰值 0.82 FS。
在 0.512 s 处有单点冲击，幅度约为局部 RMS 的 12 倍。

### 建议的处理顺序

1. 先做冲击修复：`request_denoise(threshold=8.0, max_repair_ms=3.0)`
2. 再对 0.2–1.8 s 区间取统计量，避开起振与收尾
3. 把主频与 RMS 记进结果表，与基准文件相减得到 ΔL

| 量 | 数值 | 单位 |
|---|---|---|
| 主频 | 1000.2 | Hz |
| RMS | -10.9 | dBFS |
| 冲击 | 1 | 段 |
"""

ANSWER_EN = """## Conclusion

`demo_impulse.wav` is 48000 Hz, 2.00 s long, peak 0.82 FS.
There is a single transient at 0.512 s, roughly 12x the local RMS.

### Suggested order

1. Repair the transient first: `request_denoise(threshold=8.0, max_repair_ms=3.0)`
2. Then take statistics over 0.2-1.8 s, avoiding the attack and the tail
3. Record main frequency and RMS, subtract the reference file to get dL

| Quantity | Value | Unit |
|---|---|---|
| Main frequency | 1000.2 | Hz |
| RMS | -10.9 | dBFS |
| Transients | 1 | segment |
"""

ANSWER = msg(ANSWER_ZH, ANSWER_EN)


def trim_bottom(pixmap, margin: int = 8):
    """从底部向上找第一行非纯白像素，只保留到它下面 margin 像素。"""
    image = pixmap.toImage()
    width, height = image.width(), image.height()
    bottom = height - 1
    while bottom > 0:
        if any(image.pixelColor(x, bottom).lightness() < 248
               for x in range(0, width, 5)):
            break
        bottom -= 1
    return pixmap.copy(0, 0, width, min(height, bottom + 1 + margin))


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(light_palette())

    from core.i18n import set_language

    # 必须在 import app.* 之前：界面文案常量在 import 时求值
    set_language((os.environ.get("SHOT_LANG") or "zh").strip().lower())

    from app.main_window import MainWindow
    from app.settings_dialog import AISettingsDialog

    window = MainWindow()
    window.resize(1440, 900)
    window.move(-20000, -20000)
    window.show()
    QApplication.processEvents()

    dialog = AISettingsDialog(window)
    dialog.model.setCurrentText("deepseek-chat")
    dialog.api_key.setText("sk-00000000000000000000000000000000")
    dialog.resize(620, dialog.sizeHint().height())
    dialog.move(-20000, -20000)
    dialog.show()
    QApplication.processEvents()
    shoot(dialog, OUT / "11_ai_settings.png")
    dialog.hide()

    # 会话图单独造一个顶层 ChatView：它没有父布局，固定尺寸才不会被 QDockWidget 撑开。
    from app.chat_view import ChatView

    view = ChatView()
    view.setFixedSize(432, 470)  # 先给一个高度，让文档按 432 宽排版
    view.add_user(msg("分析当前录音，检测冲击并给出处理建议",
                      "Analyse the current recording: detect transients and suggest a repair"))
    view.add_ai(ANSWER)
    # 再按实际内容高度收紧：图里不留大片白边，插进手册才不会显小
    QApplication.processEvents()
    bar = view.verticalScrollBar()
    view.setFixedSize(432, view.viewport().height() + bar.maximum() + 26)
    # 手动滚到顶部：ChatView 默认停在最新一条，抓图会把提问那条切掉
    view.verticalScrollBar().setValue(0)
    # 去掉控件自带边框，再把底部空白裁掉：插进手册时图不会被一圈灰线和一片白边撑大
    view.setFrameShape(QFrame.NoFrame)
    view.move(-20000, -20000)
    view.show()
    QApplication.processEvents()
    # 底部白边按设备像素比换算后裁掉：3 倍缩放下 8 逻辑像素等于 24 物理像素
    pixmap = trim_bottom(view.grab(), margin=int(8 * view.devicePixelRatioF()))
    target = OUT / "12_ai_chat.png"
    pixmap.save(str(target), "PNG")
    print(f"{target.name}: {pixmap.width()}x{pixmap.height()}")
    view.hide()


if __name__ == "__main__":
    main()
