from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ai.assistant import AIAssistant
from ai.tools import AnalysisTools


class AIWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, assistant: AIAssistant, message: str, tools: AnalysisTools, parent=None):
        super().__init__(parent)
        self.assistant = assistant
        self.message = message
        self.tools = tools

    def run(self) -> None:
        try:
            self.succeeded.emit(self.assistant.ask(self.message, self.tools))
        except Exception as exc:
            self.failed.emit(str(exc))
