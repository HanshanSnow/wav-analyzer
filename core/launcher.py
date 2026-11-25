"""启动器共用的小工具：解释器选择、子进程参数、启动失败提示。

四条启动路径（双击 bat、命令行、IDE、切语言重启）都要「优先无控制台解释器」，
这套判断只写一份，避免 bat 与 Python 两处各写一套后漂移。

注意：本模块可能在 Qt 尚未可用时被调用，因此只依赖标准库。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Windows 上 CREATE_NO_WINDOW 让子进程不弹控制台；其它平台没有这个常量。
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

ERROR_LOG_NAME = "startup_error.log"


def pythonw_sibling(executable: str | os.PathLike[str]) -> str:
    """返回与 ``executable`` 同目录的 ``pythonw.exe``；不存在则原样返回。

    ``pythonw.exe`` 是不带控制台的解释器：用它启动，双击 bat 或切语言重启都不会
    闪出黑框。venv 的 ``Scripts`` 目录里一般两个都有。
    """
    path = Path(executable)
    if path.name.lower() == "pythonw.exe":
        return str(path)
    candidate = path.with_name("pythonw.exe")
    if candidate.is_file():
        return str(candidate)
    return str(path)


def no_window_flags() -> dict[str, int]:
    """``subprocess`` 的关键字参数：Windows 上不建控制台窗口。"""
    return {"creationflags": CREATE_NO_WINDOW} if CREATE_NO_WINDOW else {}


def _log_startup_failure(message: str) -> Path | None:
    """把失败信息写到 ``startup_error.log``；任何写入失败都静默放弃。"""
    for base in (Path.cwd(), Path(__file__).resolve().parent.parent):
        try:
            target = base / ERROR_LOG_NAME
            target.write_text(message, encoding="utf-8")
            return target
        except OSError:
            continue
    return None


def report_startup_failure(message: str, title: str = "启动失败") -> None:
    """Qt 还没起来时的失败提示：写日志 + Windows 消息框 + stderr。

    为什么不用 QMessageBox：走到这里通常正是 PySide6 缺失或 Qt 插件加载失败，
    再用 Qt 弹窗只会二次失败，用户什么也看不到（pythonw 下连 stderr 都没有）。
    """
    log_path = _log_startup_failure(message)
    text = message
    if log_path is not None:
        text = f"{message}\n\n详细信息已写入：{log_path}"
    if sys.stderr is not None:
        try:
            print(text, file=sys.stderr)
        except (OSError, ValueError):
            pass
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
        except Exception:  # noqa: BLE001 - 提示失败不能再抛错
            pass
