"""探针：把 ChatView 渲染成 PNG，检查气泡颜色、对齐与 Markdown 显示。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.chat_view import ChatView

SAMPLE = """## 结论

当前录音**主频 1000.2 Hz**，RMS 0.283 FS（-10.9 dBFS），未发现削顶。

### 处理建议

1. 先做冲击检测：`request_denoise(threshold=8)`
2. 再按区间取统计量，避开 0.0–0.2 s 的起振段
3. 与基准文件相减得 ΔL

| 量 | 数值 | 单位 |
|---|---|---|
| 主频 | 1000.2 | Hz |
| THD | 0.42 | % |

> 注意：dBFS 与 dB SPL 不能混用。

```python
level = 20 * np.log10(max(amp, 1e-15))
```

参考 [DeepSeek 文档](https://api-docs.deepseek.com/)。
"""


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei", 9))
    view = ChatView()
    view.resize(430, 900)
    view.add_welcome()
    view.add_user("分析当前数据，检测冲击并给出处理建议")
    view.add_ai(SAMPLE)
    view.add_error("请求超时（120 s 内没有收到完整响应）。\n\n可到“模型设置”里把超时调大。")
    view.show()
    app.processEvents()
    out = Path(__file__).with_name("_chat_probe.png")
    view.grab().save(str(out))
    print("saved", out, view.message_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
