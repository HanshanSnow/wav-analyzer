"""界面语言：以中文原文为键的轻量翻译层。

设计取舍
--------
不引入 Qt Linguist 的 .ts/.qm 流程。原因有三个：一是本项目的中文文案本身就是
最好的键（写代码时直接 ``tr("打开 WAV")``，不用维护什么 ID）；二是 .ts 需要
lupdate/lrelease 两套工具链，对本项目是净负担；三是查不到的条目退回中文，
永远不会出现空白按钮或 ``MainWindow.openButton`` 这类泄露到界面的原文。

用法约定
--------
- 所有面向用户的字符串都过 ``tr()``，包括按钮、标签、提示、表格表头、状态栏。
- 日志、异常内部信息、注释、文档字符串不翻译。
- 导出文件的内容（TXT/CSV/HTML/图注）不走本层，它们属于数据产物而非界面。
- 语言在进程启动时确定；切换语言后由界面重启进程生效（见 ``app/main_window.py``
  的 ``_restart_for_language``），因此不需要实现 retranslate 重刷逻辑。
"""

from __future__ import annotations

import os

LANG_ZH = "zh"
LANG_EN = "en"

DEFAULT_LANGUAGE = LANG_ZH

# QSettings 里的键名。改默认语言不必换键，但换键会让老用户的语言选择回到默认。
LANGUAGE_SETTINGS_KEY = "ui/language"

# 环境变量：截图脚本、冒烟测试用它强制界面语言，不必改动用户已保存的选择。
ENV_LANGUAGE_KEY = "WAV_ANALYZER_UI_LANG"


def language_from_environment() -> str | None:
    """读环境变量里指定的语言；没设、或设成未知值时返回 None（交回默认逻辑）。"""
    value = os.environ.get(ENV_LANGUAGE_KEY, "").strip().lower()
    return value if value in (LANG_ZH, LANG_EN) else None

_OPTIONS: tuple[tuple[str, str], ...] = (
    (LANG_ZH, "中文"),
    (LANG_EN, "English"),
)

_current: str = DEFAULT_LANGUAGE
_table: dict[str, str] = {}


def language_options() -> list[tuple[str, str]]:
    """返回 [(代码, 显示名), ...]，供下拉框直接使用。"""
    return list(_OPTIONS)


def current_language() -> str:
    return _current


def is_english() -> bool:
    return _current == LANG_EN


def set_language(code: str) -> None:
    """设置当前语言。非法值回退到默认语言，不抛异常。"""
    global _current, _table
    _current = code if code in (LANG_ZH, LANG_EN) else DEFAULT_LANGUAGE
    if _current == LANG_EN:
        if not _table:
            from core.i18n_en import EN

            _table = EN
    else:
        _table = {}


def tr(text: str) -> str:
    """翻译一条界面文案。英文模式下查不到就原样返回中文，保证界面不残缺。"""
    if _current == LANG_ZH or not text:
        return text
    return _table.get(text, text)


def tf(template: str, **kw) -> str:
    """翻译带占位符的模板再格式化，等价于 ``tr(template).format(**kw)``。

    为什么需要它：f-string 会先把变量拼进去，翻译层就只剩一个已经拼好的句子，
    查不到词条。所以带变量的界面文案一律写成 ``tf("正在处理 {name}", name=...)``，
    占位符原样留在词条里，英文译文可以自由调整语序。
    """
    return tr(template).format(**kw)
