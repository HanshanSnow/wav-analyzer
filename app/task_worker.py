"""通用后台任务：把耗时计算移出 GUI 线程，结果回主线程渲染。"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QThread, Signal


class TaskWorker(QThread):
    """在独立线程执行 callable。func 内部不得触碰任何 Qt 对象。

    func 可接受可选的关键字参数 progress(0~1, 文案)，用于把进度回传界面；
    若 func 不接受该参数，则自动降级为无进度模式。
    """

    succeeded = Signal(object)
    failed = Signal(str)
    progressed = Signal(float, str)

    def __init__(self, func: Callable[..., Any], *args, report_progress: bool = False, **kwargs):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs
        self._report_progress = report_progress

    def _emit_progress(self, fraction: float, message: str) -> None:
        self.progressed.emit(float(fraction), str(message))

    def run(self) -> None:
        try:
            if self._report_progress:
                self._kwargs["progress"] = self._emit_progress
            self.succeeded.emit(self._func(*self._args, **self._kwargs))
        except Exception as exc:  # 后台异常统一回到主线程弹窗
            self.failed.emit(f"{type(exc).__name__}: {exc}")
