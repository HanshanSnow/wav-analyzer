from __future__ import annotations

import json
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
            return (f"请求超时：连续 {seconds:.0f} s 没有收到任何新内容。\n\n"
                    "可到“模型设置”里把超时调大（最大 600 s），"
                    "或改用响应更快的模型；推理类模型在长输出时首字延迟可能很久。")
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

    @staticmethod
    def _message_from_payload(data: bytes | str) -> dict[str, Any]:
        """非流式响应的兜底解析（有些网关不认 stream=true，直接回整包 JSON）。"""
        try:
            body = json.loads(data)
            return body["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ValueError("模型响应缺少 choices[0].message") from exc

    @staticmethod
    def _consume_stream(lines: Any, progress: dict[str, int]) -> dict[str, Any]:
        """把 SSE 增量拼回一条完整的 assistant 消息。

        收流而不是等整包的关键在超时语义：等待整包时 "服务端 120 s 没吐完"
        会直接判超时（写长报告很容易触发）；收流时超时只表示"连续 120 s
        没有新字节"，只要模型还在出字就不会误杀。
        """
        parts: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        for raw in lines:
            line = raw.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                if data == "[DONE]":
                    break
                continue
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content")
            if piece:
                parts.append(piece)
                progress["chars"] = progress.get("chars", 0) + len(piece)
            for call in delta.get("tool_calls") or []:
                index = int(call.get("index", 0))
                slot = calls.setdefault(index, {"id": "", "type": "function",
                                                "function": {"name": "", "arguments": ""}})
                if call.get("id"):
                    slot["id"] = call["id"]
                function = call.get("function") or {}
                # name 一般整包到达，arguments 才是逐段拼接；重复写 name 会拼坏。
                if function.get("name") and not slot["function"]["name"]:
                    slot["function"]["name"] = function["name"]
                if function.get("arguments"):
                    slot["function"]["arguments"] += function["arguments"]
        message: dict[str, Any] = {"role": "assistant", "content": "".join(parts) or None}
        if calls:
            message["tool_calls"] = [calls[i] for i in sorted(calls)]
        return message

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        progress: dict[str, int] = {}
        try:
            with self.client.stream("POST", self._url("chat/completions"),
                                    headers=self._headers(), json=payload) as response:
                response.raise_for_status()
                kind = (response.headers.get("content-type") or "").lower()
                if "event-stream" not in kind:
                    return self._message_from_payload(response.read())
                return self._consume_stream(response.iter_lines(), progress)
        except ValueError:
            raise
        except Exception as exc:
            hint = self._failure_hint(exc)
            received = progress.get("chars", 0)
            if received:
                hint += f"\n\n本次已收到约 {received} 字后才中断，可重试，或把超时调大。"
            raise RuntimeError(hint) from exc
