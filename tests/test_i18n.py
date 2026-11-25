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
    assert tr("打开音频") == "打开音频"
    set_language(LANG_EN)
    assert tr("打开音频") == "Open audio"


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


def test_restart_command_keeps_script_and_drops_pyinstaller_temp_pointers(
    monkeypatch, tmp_path
):
    """重启命令必须能真正再拉起一个界面，并剥掉 onefile 的临时目录指针。

    两个坑各对应一个断言：源码方式运行时 ``sys.argv[0]`` 才是脚本路径，漏了它
    新进程就是没有脚本的裸解释器，读完空 stdin 立刻退出（切换语言闪退）；
    打包方式运行时子进程若继承 ``_MEIxxxx``，旧进程退出会删不掉临时目录。
    """
    import sys

    from app.main_window import _pyinstaller_free_env, _restart_command

    env = {
        "PATH": "/usr/bin",
        "_PYI_APPLICATION_HOME_DIR": r"C:\Temp\_MEI000035bc2",
        "_PYI_ARCHIVE_FILE": r"C:\Temp\_MEI000035bc2\WAV Analyzer.exe",
        "_MEIPASS2": r"C:\Temp\_MEI000035bc2",
        "_PYI_PARENT_PROCESS_LEVEL": "1",
    }
    cleaned = _pyinstaller_free_env(env)

    assert cleaned == {"PATH": "/usr/bin"}
    # 源码方式运行时本来就没有这些变量，不能凭空造出来
    assert _pyinstaller_free_env({"PATH": "/usr/bin"}) == {"PATH": "/usr/bin"}

    # 源码运行：优先同目录的 pythonw.exe（无控制台）+ 脚本路径 + 用户参数
    launcher_dir = tmp_path / "Scripts"
    launcher_dir.mkdir()
    console_python = launcher_dir / "python.exe"
    windowed_python = launcher_dir / "pythonw.exe"
    console_python.write_bytes(b"")
    windowed_python.write_bytes(b"")
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "argv", ["run_app.py", "某个.wav"])
    monkeypatch.setattr(sys, "executable", str(console_python))
    program, arguments = _restart_command()
    assert program == str(windowed_python)
    assert arguments == [str((ROOT / "run_app.py").resolve()), "某个.wav"]

    # 没有 pythonw.exe 时退回 python.exe，不能拼出一个不存在的解释器路径
    windowed_python.unlink()
    assert _restart_command()[0] == str(console_python)

    # 打包运行：可执行文件自己就是 argv[0]，用户参数原样带上
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "argv", ["WAV Analyzer.exe", "某个.wav"])
    assert _restart_command() == (sys.executable, ["某个.wav"])


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
