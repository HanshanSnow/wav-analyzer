import json

import httpx
import numpy as np

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
