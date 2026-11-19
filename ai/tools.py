from __future__ import annotations

import json
from typing import Any, Callable

import numpy as np

from core.denoise import detect_and_repair_impulses
from core.envelope import compute_envelope, fit_envelope
from core.spectral import fourier_analysis
from core.statistics import interval_statistics


class AnalysisTools:
    """只允许调用明确注册的本地算法，不接受模型生成代码。"""

    def __init__(self, samples: np.ndarray, sample_rate: int, file_name: str, valid_mask: np.ndarray | None = None):
        self.samples = np.asarray(samples, dtype=np.float64).reshape(-1).copy()
        self.sample_rate = int(sample_rate)
        self.file_name = file_name
        self.valid_mask = np.ones(len(self.samples), dtype=bool) if valid_mask is None else np.asarray(valid_mask, dtype=bool).copy()
        self.pending_actions: list[dict[str, Any]] = []
        self.execution_log: list[dict[str, Any]] = []
        self._handlers: dict[str, Callable[..., Any]] = {
            "get_audio_info": self.get_audio_info,
            "analyze_interval": self.analyze_interval,
            "fourier_analysis": self.run_fourier,
            "fit_envelope": self.run_envelope_fit,
            "request_denoise": self.request_denoise,
        }

    @staticmethod
    def schemas() -> list[dict[str, Any]]:
        def function(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
            return {"type": "function", "function": {"name": name, "description": description,
                    "parameters": {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}}}

        return [
            function("get_audio_info", "读取当前 WAV 的文件和信号质量信息", {}),
            function("analyze_interval", "计算给定时间区间的 RMS、振幅、主频等统计", {
                "start_s": {"type": "number", "minimum": 0}, "end_s": {"type": "number", "exclusiveMinimum": 0}},
                ["start_s", "end_s"]),
            function("fourier_analysis", "执行傅立叶分析并返回主频、谱峰、谐波和 THD", {
                "start_s": {"type": "number", "minimum": 0}, "end_s": {"type": "number", "exclusiveMinimum": 0}}),
            function("fit_envelope", "计算并拟合包络，返回真实拟合方程和误差", {
                "model": {"type": "string", "enum": ["auto", "constant", "linear", "exponential"]},
                "start_s": {"type": "number", "minimum": 0}, "end_s": {"type": "number", "exclusiveMinimum": 0}}),
            function("request_denoise", "生成冲击检测和去噪预览；不会直接修改数据，需用户在界面确认", {
                "threshold": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
                "max_repair_ms": {"type": "number", "exclusiveMinimum": 0, "maximum": 100}}),
        ]

    def execute(self, name: str, arguments_json: str) -> str:
        if name not in self._handlers:
            return json.dumps({"error": f"不允许的工具：{name}"}, ensure_ascii=False)
        try:
            arguments = json.loads(arguments_json or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("工具参数必须是 JSON 对象")
            result = self._handlers[name](**arguments)
            self.execution_log.append({"tool": name, "arguments": arguments, "status": "ok"})
            return json.dumps(result, ensure_ascii=False, allow_nan=False)
        except Exception as exc:
            self.execution_log.append({"tool": name, "arguments_json": arguments_json, "status": "error", "error": str(exc)})
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    def get_audio_info(self) -> dict[str, Any]:
        x = self.samples
        rms = float(np.sqrt(np.mean(x ** 2)))
        return {"file": self.file_name, "sample_rate": self.sample_rate, "samples": len(x),
                "duration_s": len(x) / self.sample_rate, "peak": float(np.max(np.abs(x))),
                "rms": rms, "rms_dbfs": 20 * np.log10(max(rms, 1e-15)),
                "excluded_samples": int(np.count_nonzero(~self.valid_mask))}

    def _slice(self, start_s: float | None, end_s: float | None) -> tuple[np.ndarray, np.ndarray, int]:
        start_s = 0.0 if start_s is None else float(start_s)
        end_s = len(self.samples) / self.sample_rate if end_s is None else float(end_s)
        start, end = max(0, round(start_s * self.sample_rate)), min(len(self.samples), round(end_s * self.sample_rate))
        if end <= start:
            raise ValueError("分析区间无效")
        return self.samples[start:end], self.valid_mask[start:end], start

    def analyze_interval(self, start_s: float, end_s: float) -> dict[str, Any]:
        return interval_statistics(self.samples, self.sample_rate, start_s, end_s, self.valid_mask)

    def run_fourier(self, start_s: float | None = None, end_s: float | None = None) -> dict[str, Any]:
        selected, valid, _ = self._slice(start_s, end_s)
        selected = selected[valid]
        if len(selected) < 2:
            raise ValueError("有效采样点不足")
        result = fourier_analysis(selected, self.sample_rate, n_fft=max(len(selected), 4096))
        return {"main_frequency_hz": result.main_frequency, "main_amplitude": result.main_amplitude,
                "thd": result.thd, "peaks": result.peaks(), "harmonics": result.harmonics()}

    def run_envelope_fit(self, model: str = "auto", start_s: float | None = None, end_s: float | None = None) -> dict[str, Any]:
        selected, valid, start = self._slice(start_s, end_s)
        times, envelope = compute_envelope(selected, self.sample_rate)
        times += start / self.sample_rate
        fit = fit_envelope(times[valid], envelope[valid], model)
        return {"model": fit.model, "equation": fit.equation, "parameters": fit.parameters,
                "r_squared": fit.r_squared, "rmse": fit.rmse}

    def request_denoise(self, threshold: float = 8.0, max_repair_ms: float = 3.0) -> dict[str, Any]:
        result = detect_and_repair_impulses(self.samples, self.sample_rate, threshold=threshold, max_repair_ms=max_repair_ms)
        action = {"type": "denoise", "result": result}
        self.pending_actions.append(action)
        return {"status": "preview_only", "message": "已生成预览，必须经用户在桌面界面确认后才能应用",
                "events": [event.as_dict(self.sample_rate) for event in result.events],
                "repaired_count": result.repaired_count, "excluded_count": result.excluded_count}
