"""启动器：解释器选择（无控制台的 pythonw.exe）与 bat 回退顺序。"""

from pathlib import Path

from core.launcher import ERROR_LOG_NAME, no_window_flags, pythonw_sibling

ROOT = Path(__file__).resolve().parents[1]


def test_pythonw_sibling_prefers_windowed_interpreter(tmp_path):
    console = tmp_path / "python.exe"
    console.write_bytes(b"")

    # 没有 windowed 版时原样返回，不能拼出不存在的路径
    assert pythonw_sibling(console) == str(console)
    assert pythonw_sibling("py") == "py"

    windowed = tmp_path / "pythonw.exe"
    windowed.write_bytes(b"")
    assert pythonw_sibling(console) == str(windowed)
    # 已经是 pythonw.exe 时保持不变
    assert pythonw_sibling(windowed) == str(windowed)


def test_no_window_flags_is_pyside_free():
    flags = no_window_flags()
    assert isinstance(flags, dict)
    assert set(flags).issubset({"creationflags"})


def test_bat_prefers_windowed_interpreter_before_console_one():
    text = (ROOT / "run_app.bat").read_text(encoding="utf-8")

    assert "%VENV_PYW%" in text
    windowed = text.index('"%VENV_PYW%" "%APP%"')
    fallback = text.index('"%VENV_PY%" "%APP%"')
    assert windowed < fallback, "bat 必须先试 pythonw.exe，再退 python.exe"


def test_error_log_name_is_stable():
    # 用户照着手册找日志文件，名字不能随手改
    assert ERROR_LOG_NAME == "startup_error.log"


def test_window_icon_resolves():
    import run_app

    path = run_app._icon_path()
    assert path is not None and path.is_file(), "找不到窗口/任务栏图标文件"
    assert path.name in run_app.ICON_NAMES


def test_app_user_model_id_is_stable():
    import run_app

    # 任务栏按这个 ID 分组；改了会让"已固定到任务栏"的快捷方式变成第二个图标
    assert run_app.APP_USER_MODEL_ID == "HanshanSnow.WAVAnalyzer.2"
