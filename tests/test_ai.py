import json

import httpx
import numpy as np
import pytest

from ai.assistant import AIAssistant
from ai.client import AISettings, OpenAICompatibleClient
from ai.tools import AnalysisTools


FS = 44100
T = np.arange(FS // 10) / FS
X = 0.4 * np.sin(2 * np.pi * 1000 * T)


def test_tools_return_real_statistics_and_denoise_is_preview_only():
    damaged = X.copy()
    damaged[1000] += 0.8
    tools = AnalysisTools(damaged, FS, "synthetic.wav")
    info = json.loads(tools.execute("get_audio_info", "{}"))
    assert info["samples"] == len(X)
    stats = json.loads(tools.execute("analyze_interval", '{"start_s": 0, "end_s": 0.1}'))
    assert abs(stats["main_frequency_hz"] - 1000) < 1
    response = json.loads(tools.execute("request_denoise", '{"threshold": 8}'))
    assert response["status"] == "preview_only"
    assert len(tools.pending_actions) == 1
    assert damaged[1000] == X[1000] + 0.8
    error = json.loads(tools.execute("not_registered", "{}"))
    assert "不允许" in error["error"]


def test_streaming_accumulates_content_and_tool_call_fragments():
    """服务端按 SSE 分片返回时，正文与 tool_calls 都要拼回完整消息。"""
    def sse(chunks: list[dict]) -> bytes:
        body = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks)
        return (body + "data: [DONE]\n\n").encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["stream"] is True
        if payload["messages"][-1]["role"] == "user":
            # 工具名整包到达，参数被切成两段
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse([
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call-9", "type": "function",
                                                       "function": {"name": "analyze_interval", "arguments": ""}}]}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"start_s": 0,'}}]}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"end_s": 0.1}'}}]}}]},
            ]))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse([
            {"choices": [{"delta": {"content": "## 结论\n"}}]},
            {"choices": [{"delta": {"content": "主频 1000 Hz"}}]},
        ]))

    client = OpenAICompatibleClient(
        AISettings("https://example.test/v1", "test-model", "test-key"),
        transport=httpx.MockTransport(handler),
    )
    outcome = AIAssistant(client).ask("分析主频", AnalysisTools(X, FS, "synthetic.wav"))
    assert outcome.content == "## 结论\n主频 1000 Hz"
    assert outcome.execution_log[0]["tool"] == "analyze_interval"
    assert outcome.execution_log[0]["arguments"] == {"start_s": 0, "end_s": 0.1}
    client.close()


def test_non_stream_json_response_still_parsed():
    """有的网关不认 stream=true，直接回整包 JSON，必须照样能解析。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, json={
            "choices": [{"message": {"role": "assistant", "content": "整包回答"}}]})

    client = OpenAICompatibleClient(
        AISettings("https://example.test/v1", "test-model", "test-key"),
        transport=httpx.MockTransport(handler),
    )
    assert client.chat([{"role": "user", "content": "hi"}])["content"] == "整包回答"
    client.close()


def test_timeout_message_reports_partial_progress():
    """收到部分内容后超时，提示里要说明已收到多少字，方便判断是网络还是模型太慢。"""
    def handler(request: httpx.Request) -> httpx.Response:
        def gen():
            yield b'data: {"choices":[{"delta":{"content":"half"}}]}\n\n'
            raise httpx.ReadTimeout("stalled", request=request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=gen())

    client = OpenAICompatibleClient(
        AISettings("https://example.test/v1", "test-model", "test-key", timeout_s=120),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RuntimeError) as info:
        client.chat([{"role": "user", "content": "写报告"}])
    assert "超时" in str(info.value)
    assert "4 字" in str(info.value)
    client.close()


def test_stream_side_errors_are_surfaced():
    """流里夹错误、或一个字都没吐，都要明确报错，不能让界面显示空白气泡。"""
    def sse(text: str) -> bytes:
        return text.encode("utf-8")

    def client_for(body: bytes) -> OpenAICompatibleClient:
        return OpenAICompatibleClient(
            AISettings("https://example.test/v1", "test-model", "test-key"),
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)),
        )

    broken = client_for(sse('data: {"error":{"message":"context length exceeded"}}\n\n'))
    with pytest.raises(RuntimeError) as info:
        broken.chat([{"role": "user", "content": "hi"}])
    assert "context length exceeded" in str(info.value)
    broken.close()

    empty = client_for(sse("data: [DONE]\n\n"))
    with pytest.raises(ValueError) as info:
        empty.chat([{"role": "user", "content": "hi"}])
    assert "空内容" in str(info.value)
    empty.close()


def test_openai_compatible_tool_call_loop():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer test-key"
        if payload["messages"][-1]["role"] == "user":
            return httpx.Response(200, json={"choices": [{"message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "call-1", "type": "function", "function": {
                    "name": "analyze_interval", "arguments": '{"start_s":0,"end_s":0.1}'}}],
            }}]})
        tool_message = payload["messages"][-1]
        assert tool_message["role"] == "tool"
        result = json.loads(tool_message["content"])
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": f"实测主频 {result['main_frequency_hz']:.2f} Hz",
        }}]})

    client = OpenAICompatibleClient(
        AISettings("https://example.test/v1", "test-model", "test-key"),
        transport=httpx.MockTransport(handler),
    )
    assistant = AIAssistant(client)
    tools = AnalysisTools(X, FS, "synthetic.wav")
    outcome = assistant.ask("分析主频", tools)
    assert "1000" in outcome.content
    assert outcome.execution_log[0]["tool"] == "analyze_interval"
    client.close()
