from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import OpenAICompatibleClient
from .tools import AnalysisTools


SYSTEM_PROMPT = """你是声音实验数据分析助手。你只能使用提供的本地工具计算数据，不能编造数值。
去噪时先说明理由并调用 request_denoise 生成预览；该工具不会直接修改文件，必须由用户确认。
一次回答里最多调用一次 request_denoise，用户只会看到一次确认。
报告需说明处理步骤、参数、理由、结果和限制。区分峰值振幅、RMS、dBFS 与 dB SPL。
回答用 Markdown 组织：## 小标题、短列表、必要时的表格与行内代码，界面会按格式渲染。
如果数据不足或算法不适用，应明确指出，不要强行给结论。"""


@dataclass
class AIOutcome:
    content: str
    pending_actions: list[dict[str, Any]]
    execution_log: list[dict[str, Any]]


class AIAssistant:
    def __init__(self, client: OpenAICompatibleClient):
        self.client = client
        self.history: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    def ask(self, message: str, tools: AnalysisTools, max_rounds: int = 6) -> AIOutcome:
        if not message.strip():
            raise ValueError("消息不能为空")
        self.history.append({"role": "user", "content": message})
        for _ in range(max_rounds):
            response = self.client.chat(self.history, tools.schemas())
            self.history.append(response)
            calls = response.get("tool_calls") or []
            if not calls:
                return AIOutcome(response.get("content") or "", tools.pending_actions.copy(), tools.execution_log.copy())
            for call in calls:
                function = call.get("function", {})
                result = tools.execute(function.get("name", ""), function.get("arguments", "{}"))
                self.history.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result})
        raise RuntimeError("AI 工具调用轮次过多，已停止；请缩小任务或检查模型响应")
