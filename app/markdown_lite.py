"""极简 Markdown → HTML，专供 Qt 富文本（QTextDocument）显示模型回答。

Qt 的富文本引擎只支持 HTML 4 的一个子集，Markdown 库（如 markdown、mistune）
输出的 `<div class=...>`、CSS 类、flex 布局等内容大量不被识别，因此这里手写一个
只覆盖「聊天里真会出现的语法」的转换器：

    标题 # ~ ######        粗体 **x** / __x__
    斜体 *x* / _x_         行内代码 `x`
    删除线 ~~x~~           代码围栏 ```lang
    有序 / 无序列表        引用 >
    表格 | a | b |         分隔线 --- / ***
    链接 [t](url)          裸链接 http(s)://...

转换结果全部使用 Qt 认识的内联标签（b / i / s / a / ul / ol / li / table / hr），
不使用 class、id、CSS 变量，也不依赖任何第三方包。
"""

from __future__ import annotations

import html
import re

__all__ = ["to_html", "to_plain"]

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_UL_ITEM = re.compile(r"^[-*+]\s+(.*)$")
_OL_ITEM = re.compile(r"^\d{1,3}[.)]\s+(.*)$")
_HR = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")

# Qt 富文本里的等宽字体：写两个候选，缺哪个都能退化到系统等宽字体
_MONO = "font-family:'Consolas','Courier New',monospace;"
_CODE_BG = "background-color:#eef1f5;"


def _inline(text: str) -> str:
    """行内语法。先抽出代码段，避免代码里的 * _ ` 被当作强调标记。"""
    stash: list[str] = []

    def hide(match: re.Match[str]) -> str:
        stash.append(match.group(1))
        return f"\x00{len(stash) - 1}\x00"

    text = re.sub(r"`([^`\n]+)`", hide, text)
    text = html.escape(text, quote=False)

    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*\s*([^*\n]+?)\s*\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(?<![\w])__(?!\s)(.+?)(?<!\s)__(?![\w])", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w])", r"<i>\1</i>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # 链接：Markdown 语法优先，其次把裸地址变成可点的链接
    text = re.sub(r"\[([^\]\n]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"(?<![=\"'>])(https?://[^\s<>\u4e00-\u9fff]+)", r'<a href="\1">\1</a>', text)

    def restore(match: re.Match[str]) -> str:
        code = html.escape(stash[int(match.group(1))], quote=False)
        return f'<span style="{_MONO}{_CODE_BG}">{code}</span>'

    return re.sub("\x00(\\d+)\x00", restore, text)


_HEADING_STYLE = {1: ("12pt", "#10243a"), 2: ("11pt", "#17324d"), 3: ("10pt", "#1f2429")}


def _heading(level: int, text: str) -> str:
    """标题不用 hN 标签：Qt 对 h1 的默认字号是正文两倍，撑得很开；
    而 span 上的 font-size 是受支持属性，能精确控制。"""
    size, color = _HEADING_STYLE.get(min(level, 3), _HEADING_STYLE[3])
    return (f'<p><span style="font-size:{size};color:{color};"><b>{_inline(text)}</b></span></p>')


def _code_block(code: str, lang: str = "") -> str:
    body = html.escape(code, quote=False).replace("\n", "<br>")
    hint = f'<span style="color:#78909c;">{html.escape(lang)}</span><br>' if lang else ""
    return (
        f'<table width="100%" cellspacing="0" cellpadding="6"><tr>'
        f'<td bgcolor="#f5f7f9">{hint}<span style="{_MONO}">{body}</span></td>'
        f"</tr></table>"
    )


def _table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    out = ['<table width="100%" cellspacing="0" cellpadding="4">']
    for index, row in enumerate(rows):
        cells = row + [""] * (width - len(row))
        if index == 0:
            out.append("<tr>" + "".join(
                f'<td bgcolor="#e3e8ee"><b>{_inline(cell)}</b></td>' for cell in cells) + "</tr>")
        else:
            out.append("<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in cells) + "</tr>")
    out.append("</table>")
    return "".join(out)


def to_html(text: str) -> str:
    """把一段 Markdown 转成 Qt 富文本片段。未知语法原样保留，不丢内容。"""
    if not text:
        return ""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4).split("\n")
    blocks: list[str] = []
    index = 0
    total = len(lines)

    while index < total:
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            index += 1
            continue

        # 代码围栏
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            index += 1
            body: list[str] = []
            while index < total and not lines[index].strip().startswith("```"):
                body.append(lines[index])
                index += 1
            index += 1
            blocks.append(_code_block("\n".join(body), lang))
            continue

        if _HR.match(stripped):
            blocks.append("<hr>")
            index += 1
            continue

        heading = _HEADING.match(stripped)
        if heading:
            blocks.append(_heading(len(heading.group(1)), heading.group(2).strip()))
            index += 1
            continue

        # 表格：首行 + 分隔行 + 若干数据行
        if _TABLE_ROW.match(line) and index + 1 < total and _TABLE_SEP.match(lines[index + 1]):
            rows: list[list[str]] = []
            while index < total and _TABLE_ROW.match(lines[index]):
                cells = [cell.strip() for cell in _TABLE_ROW.match(lines[index]).group(1).split("|")]
                rows.append(cells)
                index += 1
            rows = [row for row in rows if not all(set(cell) <= set(":- ") for cell in row)]
            blocks.append(_table(rows))
            continue

        # 引用
        if stripped.startswith(">"):
            quoted: list[str] = []
            while index < total and lines[index].strip().startswith(">"):
                quoted.append(lines[index].strip().lstrip(">").strip())
                index += 1
            blocks.append(
                '<table width="100%" cellspacing="0" cellpadding="4"><tr>'
                f'<td bgcolor="#f4f6f8"><span style="color:#546e7a;">{_inline(" ".join(quoted))}</span></td>'
                "</tr></table>")
            continue

        # 列表：连续同类条目成一张表
        for pattern, tag in ((_UL_ITEM, "ul"), (_OL_ITEM, "ol")):
            if pattern.match(line):
                items: list[str] = []
                while index < total and pattern.match(lines[index]):
                    items.append(pattern.match(lines[index]).group(1).strip())
                    index += 1
                blocks.append(f"<{tag}>" + "".join(f"<li>{_inline(item)}</li>" for item in items) + f"</{tag}>")
                break
        else:
            para: list[str] = []
            while index < total and lines[index].strip() and not (
                lines[index].strip().startswith("```")
                or _HEADING.match(lines[index].strip())
                or _UL_ITEM.match(lines[index])
                or _OL_ITEM.match(lines[index])
                or _HR.match(lines[index].strip())
                or lines[index].strip().startswith(">")
                or _TABLE_ROW.match(lines[index])
            ):
                para.append(lines[index].strip())
                index += 1
            blocks.append("<p>" + "<br>".join(_inline(item) for item in para) + "</p>")

    return "".join(blocks)


def to_plain(text: str) -> str:
    """去掉最常见的 Markdown 标记，用于需要纯文本的地方（如写进 TXT 报告）。"""
    if not text:
        return ""
    out = re.sub(r"```[^\n]*\n?", "", text)
    out = re.sub(r"^#{1,6}\s*", "", out, flags=re.MULTILINE)
    out = re.sub(r"^\s*[-*+]\s+", "· ", out, flags=re.MULTILINE)
    out = re.sub(r"[*_~`]{1,3}", "", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"\1（\2）", out)
    return out.strip()
