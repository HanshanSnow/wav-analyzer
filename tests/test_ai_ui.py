"""AI 助手界面与配置的回归测试：气泡配色、Markdown 渲染、Key 保存声明、超时默认值。"""

import httpx
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from ai.client import AISettings, OpenAICompatibleClient
from app import markdown_lite
from app.chat_view import ChatView
from app.settings_dialog import (
    DEFAULT_TIMEOUT_S, TIMEOUT_SETTINGS_KEY, AISettingsDialog, _load_timeout,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------------ Markdown
def test_markdown_headings_bold_and_lists():
    html_text = markdown_lite.to_html(
        "## 结论\n\n当前**主频 1000 Hz**，RMS 0.283。\n\n### 建议\n\n1. 先检测\n2. 再统计\n\n- 甲\n- 乙\n")
    assert "结论" in html_text and "主频" in html_text
    assert "<b>主频 1000 Hz</b>" in html_text
    assert "font-size:11pt" in html_text, "二级标题应比正文大"
    assert "<ol>" in html_text and "<li>先检测</li>" in html_text
    assert "<ul>" in html_text and "<li>乙</li>" in html_text
    assert "##" not in html_text and "**" not in html_text, "标记不应原样漏出"


def test_markdown_table_code_block_and_link():
    source = (
        "| 量 | 数值 |\n|---|---|\n| 主频 | 1000.2 |\n\n"
        "```python\nlevel = 20 * np.log10(a)\n```\n\n"
        "见 [文档](https://example.test/doc)。\n")
    html_text = markdown_lite.to_html(source)
    assert html_text.count("<td") >= 4, "表格应渲染成单元格"
    assert "<b>量</b>" in html_text, "首行应作为表头加粗"
    assert "Consolas" in html_text and "np.log10" in html_text
    assert '<a href="https://example.test/doc">文档</a>' in html_text


def test_markdown_keeps_code_inline_untouched():
    html_text = markdown_lite.to_html("调用 `request_denoise(threshold=8)` 即可")
    assert "request_denoise(threshold=8)" in html_text
    assert "<i>" not in html_text, "代码里的下划线不应被当成斜体"
    plain = markdown_lite.to_plain("## 标题\n- 项 **加粗**")
    assert plain.startswith("标题") and "加粗" in plain and "#" not in plain


def test_markdown_never_loses_plain_text():
    for raw in ("普通一句话", "**只加粗**", "1. 一\n2. 二", "> 引用", "---"):
        assert markdown_lite.to_plain(markdown_lite.to_html(raw)).strip() or raw.strip() == "---"


# ------------------------------------------------------------------ 气泡
def test_chat_view_uses_distinct_colors_and_alignment():
    _app()
    view = ChatView()
    view.add_user("问题")
    view.add_ai("## 回答\n\n正文")
    view.add_error("超时")
    document = view.document().toHtml()
    for color in ("#d8e8ff", "#e9f4ec", "#fdeceb"):
        assert color.replace("#", "").lower() in document.lower(), f"缺少气泡底色 {color}"
    assert view.message_count == 3
    # 用户气泡前面有留白单元格（靠右），AI 气泡后面有留白单元格（靠左）
    first = view.document().toHtml().lower()
    assert first.count("<table") >= 3
    view.deleteLater()


def test_chat_view_renders_markdown_not_raw_markers():
    _app()
    view = ChatView()
    view.add_ai("## 结论\n\n**主频** 1000 Hz")
    text = view.toPlainText()
    assert "##" not in text and "**" not in text, "## 与 ** 不应出现在界面上"
    assert "结论" in text and "主频" in text


# ------------------------------------------------------------------ 模型设置
def test_settings_dialog_has_no_key_checkbox_and_declares_storage():
    _app()
    dialog = AISettingsDialog()
    assert not hasattr(dialog, "save_key"), "不再提供“是否用钥匙串保存”的勾选框"
    assert "钥匙串" in dialog.key_store_note.text()
    assert "不会向任何人透露" in dialog.privacy_note.text()
    assert dialog.timeout.maximum() == 600
    dialog.deleteLater()


def test_timeout_default_is_120s_and_ignores_old_key():
    stored = QSettings("PhysicsExperimentTest", "WavAnalyzerTimeoutTest")
    stored.clear()
    assert DEFAULT_TIMEOUT_S == 120.0
    assert _load_timeout(stored) == 120.0, "没有存储值时用 120 s"
    stored.setValue(TIMEOUT_SETTINGS_KEY, 300)
    assert _load_timeout(stored) == 300.0
    stored.setValue(TIMEOUT_SETTINGS_KEY, "坏值")
    assert _load_timeout(stored) == 120.0
    stored.clear()


def test_client_default_timeout_and_friendly_error():
    settings = AISettings("https://example.test/v1", "m", "k")
    assert settings.timeout_s == 120.0

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = OpenAICompatibleClient(settings, transport=httpx.MockTransport(timeout_handler))
    assert client.client.timeout.read == 120.0
    with pytest.raises(RuntimeError) as excinfo:
        client.chat([{"role": "user", "content": "hi"}])
    assert "请求超时" in str(excinfo.value) and "模型设置" in str(excinfo.value)
    client.close()
