"""界面语言层测试：默认中文、切换行为、翻译覆盖度、英文界面不残留中文。"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from core.i18n import (
    DEFAULT_LANGUAGE, LANG_EN, LANG_ZH, current_language, language_options,
    set_language, tf, tr,
)

ROOT = Path(__file__).resolve().parent.parent
CJK = re.compile(r"[\u4e00-\u9fa5]")

# 导出产物（TXT / HTML / 图片图注）是数据报告，不参与界面切换
EXPORT_ONLY = {"txt_export.py", "exporter.py", "figure_export.py", "i18n.py", "i18n_en.py"}


@pytest.fixture(autouse=True)
def _reset_language():
    """每条测试前后都回到默认语言，避免把英文状态漏给别的测试。"""
    set_language(DEFAULT_LANGUAGE)
    yield
    set_language(DEFAULT_LANGUAGE)


def _ui_strings() -> list[str]:
    """扫描 app/ 与 core/ 里所有 tr()/tf() 包裹的中文原文。"""
    found: list[str] = []
    for sub in ("app", "core"):
        for path in sorted((ROOT / sub).glob("*.py")):
            if path.name in EXPORT_ONLY:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id in ("tr", "tf") and node.args):
                    continue
                arg = node.args[0]
                if (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                        and CJK.search(arg.value)):
                    found.append(arg.value)
    return sorted(set(found))


def test_default_language_is_chinese():
    assert DEFAULT_LANGUAGE == LANG_ZH
    assert current_language() == LANG_ZH


def test_chinese_mode_returns_source_text():
    assert tr("打开 WAV") == "打开 WAV"
    set_language(LANG_EN)
    assert tr("打开 WAV") == "Open WAV"


def test_unknown_text_falls_back_to_chinese():
    """英文缺词条时返回中文，而不是空串或 key——界面不能出现空白按钮。"""
    set_language(LANG_EN)
    assert tr("这条文案故意没有翻译") == "这条文案故意没有翻译"


def test_invalid_language_code_falls_back():
    set_language("kl")
    assert current_language() == DEFAULT_LANGUAGE


def test_language_options_cover_both():
    codes = [code for code, _ in language_options()]
    assert codes == [LANG_ZH, LANG_EN]


def test_tf_formats_after_translation():
    set_language(LANG_EN)
    assert tf("声道 {_v0}", _v0=2) == "Channel 2"
    set_language(LANG_ZH)
    assert tf("声道 {_v0}", _v0=2) == "声道 2"


def test_every_ui_string_has_english():
    """覆盖度守门：新增界面文案必须同时补英文，否则英文界面会露出中文。"""
    from core.i18n_en import EN

    missing = [s for s in _ui_strings() if s not in EN]
    assert not missing, "以下文案缺英文：\n" + "\n".join(missing)


def test_placeholders_match_between_languages():
    """占位符必须一一对应，否则英文模式格式化会抛 KeyError。"""
    from core.i18n_en import EN

    for zh, en in EN.items():
        zh_names = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)[^}]*\}", zh))
        en_names = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)[^}]*\}", en))
        assert zh_names == en_names, "占位符不一致：%r → %r" % (zh, en)


def test_english_ui_has_no_chinese_leftovers():
    """英文模式下构建主窗口，按钮、分组、页签都不能残留中文。"""
    from app.main_window import MainWindow
    from PySide6.QtWidgets import QApplication, QGroupBox, QPushButton

    QApplication.instance() or QApplication([])
    set_language(LANG_EN)
    window = MainWindow()

    texts = [b.text() for b in window.findChildren(QPushButton)]
    texts += [g.title() for g in window.findChildren(QGroupBox)]
    texts.append(window.windowTitle())

    leftovers = [t for t in texts if CJK.search(t)]
    assert not leftovers, "英文界面仍有中文：%s" % leftovers
