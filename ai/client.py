from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class AISettings:
    base_url: str = "https://api.openai.com/v1"
    model: str = ""
    api_key: str = ""
    temperature: float = 0.2
    timeout_s: float = 120.0


class OpenAICompatibleClient:
    def __init__(self, settings: AISettings, transport: httpx.BaseTransport | None = None):
        if not settings.base_url.strip() or not settings.model.strip():
            raise ValueError("请填写模型 Base URL 和模型名称")
        self.settings = settings
        # 连接阶段单独给短超时：域名解析不了、端口不通时不必傻等两分钟；
        # 读取阶段用用户设置的值，因为推理模型的首字延迟可能很长。
        attempt = float(settings.timeout_s)
        timeout = httpx.Timeout(attempt, connect=min(15.0, attempt))
        self.client = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self.client.close()

    def _url(self, endpoint: str) -> str:
        base = self.settings.base_url.strip().rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[:-len("/chat/completions")]
        return f"{base}/{endpoint.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        return headers

    def _failure_hint(self, exc: Exception) -> str:
        seconds = float(self.settings.timeout_s)
        if isinstance(exc, httpx.TimeoutException):
            return (f"请求超时（{seconds:.0f} s 内没有收到完整响应）。\n\n"
                    "可到“模型设置”里把超时调大（最大 600 s），"
                    "或改用响应更快的模型；推理类模型写长报告时尤其容易超时。")
        if isinstance(exc, httpx.ConnectError):
            return (f"无法连接 {self.settings.base_url}。\n\n"
                    "请检查网络、代理设置，以及 Base URL 是否写全（一般以 /v1 结尾）。")
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            hints = {
                400: "请求格式被拒绝，多半是模型名不支持工具调用，可换一个模型试试。",
                401: "API Key 无效或已过期，请到厂商控制台重新生成。",
                402: "账户余额不足，请充值后重试。",
                403: "该 Key 无权访问这个模型。",
                404: "Base URL 或模型名不存在，请核对拼写。",
                429: "请求过于频繁或额度用尽，稍后再试。",
            }
            hint = hints.get(code, "")
            return f"服务端返回 {code}：{exc.response.reason_phrase}。{hint}".strip()
        return str(exc)

    def test_connection(self) -> str:
        try:
            response = self.client.get(self._url("models"), headers=self._headers())
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(self._failure_hint(exc)) from exc
        return "连接成功，模型服务可访问。"

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            response = self.client.post(self._url("chat/completions"), headers=self._headers(), json=payload)
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(self._failure_hint(exc)) from exc
        data = response.json()
        try:
            return data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("模型响应缺少 choices[0].message") from exc
