"""AI 会话视图：把「你 / AI / 提示 / 错误」渲染成不同底色的对话框。

为什么不用 QListWidget 一行一个 QLabel：那样跨消息选文字、复制整段分析结果都会失效。
这里用 QTextBrowser + 表格模拟气泡，选中复制、滚轮、缩放全都保持原生行为，
同时用不同底色的单元格把提问与回答区分开。

Qt 富文本不支持 border-radius（圆角）与 box-shadow，所以气泡是直角的；
除此之外的观感（左/右对齐、留白、角色标签）都是可控的。
"""

from __future__ import annotations

import html

from PySide6.QtGui import QColor, QPalette, QTextCursor
from PySide6.QtWidgets import QTextBrowser, QWidget

from . import markdown_lite

# 角色 → （气泡底色, 名称文字色, 名称）
_ROLE_STYLE: dict[str, tuple[str, str, str]] = {
    "user": ("#d8e8ff", "#12457f", "你"),
    "ai": ("#e9f4ec", "#1f5b38", "AI"),
    "error": ("#fdeceb", "#a02a20", "请求失败"),
    "notice": ("#fff7e0", "#7a5c00", "提示"),
}
_INDENT_PERCENT = 12  # 窄边留白比例：气泡占 88%，一眼能看出左右归属
_TEXT_COLOR = "#1f2429"  # 气泡内正文固定深色：浅底色气泡在深色主题下也能读


def _bubble(body: str, role: str, align_right: bool) -> str:
    background, name_color, name = _ROLE_STYLE[role]
    header = (f'<p><span style="color:{name_color};'
              f'font-size:8pt;">{html.escape(name)}</span></p>')
    cell = (f'<td width="{100 - _INDENT_PERCENT}%" bgcolor="{background}" '
            f'style="padding:7px;">{header}'
            f'<span style="color:{_TEXT_COLOR};">{body}</span></td>')
    spacer = f'<td width="{_INDENT_PERCENT}%"></td>'
    cells = spacer + cell if align_right else cell + spacer
    return (f'<table width="100%" cellspacing="0" cellpadding="0"><tr>{cells}</tr></table>'
            '<p style="font-size:4pt;">&nbsp;</p>')

class ChatView(QTextBrowser):
    """只读会话区。对外只暴露 add_user / add_ai / add_notice / add_error。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setReadOnly(True)
        self.document().setDocumentMargin(4)
        # 会话区固定成“白纸”：气泡是浅底色，若底色跟随系统深色主题，
        # 深色主题下浅气泡 + 浅文字会直接看不清。
        palette = self.palette()
        palette.setColor(QPalette.Base, QColor("#ffffff"))
        palette.setColor(QPalette.Text, QColor(_TEXT_COLOR))
        palette.setColor(QPalette.Link, QColor("#0b57d0"))
        self.setPalette(palette)
        # 默认链接色取自系统主题，深色主题下是浅蓝，落在浅绿气泡上几乎看不见。
        self.document().setDefaultStyleSheet(
            "a { color:#0b57d0; } "
            "table { border-color:#dfe5ea; } "
            "ul, ol { margin-top:2px; margin-bottom:2px; }"
        )
        self._count = 0

    # ------------------------------------------------------------ 对外接口
    @property
    def message_count(self) -> int:
        return self._count

    def add_user(self, text: str) -> None:
        self._append(_bubble(self._plain(text), "user", True))

    def add_ai(self, text: str) -> None:
        self._append(_bubble(markdown_lite.to_html(text), "ai", False))

    def add_notice(self, text: str) -> None:
        self._append(_bubble(self._plain(text), "notice", False))

    def add_error(self, text: str) -> None:
        self._append(_bubble(self._plain(text), "error", False))

    def add_welcome(self) -> None:
        self.add_notice("AI 默认只接收当前文件的数值摘要。去噪操作需你确认，不会执行模型生成的代码。")

    # ------------------------------------------------------------ 内部
    @staticmethod
    def _plain(text: str) -> str:
        return html.escape(text or "", quote=False).replace("\n", "<br>")

    def _append(self, fragment: str) -> None:
        if not fragment:
            return
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(fragment)
        self._count += 1
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())
