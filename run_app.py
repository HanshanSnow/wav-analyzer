import os
import sys
from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow


def _selftest(wav_path: Path) -> int:
    """打包自检：验证冻结包内的运行时 DLL、核心算法与导出链路是否完整。

    设置环境变量 WAV_ANALYZER_SELFTEST=<某个 wav 路径> 后启动，程序不开界面，
    跑完把结果写到该 wav 同目录的 selftest_result.json，并以退出码报告成败。
    分发前用它确认 libsndfile / PortAudio / keyring 都被正确打进包里。
    """
    import json
    import tempfile
    import traceback

    import numpy as np

    report: dict[str, object] = {"ok": False, "steps": {}}
    steps: dict[str, object] = {}
    report["steps"] = steps
    try:
        from core.audio_io import read_wav
        from core.exporter import build_report_html
        from core.figure_export import FigureOptions, render_waveform_png
        from core.spectral import fourier_analysis
        from core.statistics import interval_statistics
        from core.txt_export import TxtExportOptions, write_analysis_txt

        audio = read_wav(str(wav_path))
        sample_rate = int(audio.sample_rate)
        steps["load"] = f"{tuple(audio.samples.shape)} @ {sample_rate} Hz, subtype={audio.subtype}"

        # 取前两秒足够验证链路，避免自检拖太久。
        mono = np.asarray(audio.samples[:, 0], dtype=np.float64)[: sample_rate * 2]
        stats = interval_statistics(mono, sample_rate)
        steps["rms"] = round(float(stats["rms"]), 8)
        fourier = fourier_analysis(mono, sample_rate)
        steps["main_frequency_hz"] = round(float(fourier.main_frequency), 4)

        workdir = Path(tempfile.mkdtemp(prefix="wav_selftest_"))

        # 屏幕版式（老路径）与论文版式（1.2 新增）各出一张，确认 matplotlib 光栅化与
        # 手工留白在冻结包里都能跑通。
        for tag, options in (
            ("png", FigureOptions(title="自检")),
            ("paper_png", FigureOptions(title="自检", layout="paper", column="single")),
        ):
            target = workdir / f"{tag}.png"
            info = render_waveform_png(
                target, samples=mono, sample_rate=sample_rate, options=options,
            )
            steps[tag] = f"{info['width']}x{info['height']}, {target.stat().st_size} bytes"

        html = build_report_html(wav_path.name, sample_rate, 0.0, stats, fourier, mono)
        steps["html_bytes"] = len(html)

        # 分析 TXT 导出：覆盖定宽排版、坐标表分批写盘与文件指纹。
        txt_path = workdir / "analysis.txt"
        txt_info = write_analysis_txt(
            txt_path,
            samples=mono,
            sample_rate=sample_rate,
            source_name=wav_path.name,
            source_path=str(wav_path),
            subtype=audio.subtype,
            size_mb=wav_path.stat().st_size / (1024 * 1024),
            data_label="源文件分析",
            channels=int(audio.samples.shape[1]),
            fourier=fourier,
            options=TxtExportOptions(
                sections=("fourier", "stats", "coords"),
                coord_mode="per_second",
                coord_per_second=2000.0,
            ),
        )
        steps["txt"] = f"{txt_info['rows']} 行, {txt_info['bytes']} 字节"
        steps["txt_has_tab"] = "\t" in txt_path.read_text(encoding="utf-8")

        import sounddevice

        steps["portaudio_version"] = sounddevice.__version__
        steps["output_devices"] = sum(1 for d in sounddevice.query_devices() if d["max_output_channels"] > 0)

        import keyring

        steps["keyring_backend"] = keyring.get_keyring().__class__.__name__

        # AI 会话渲染：Markdown 转换与气泡拼接都只依赖 Qt，冻结包里应能独立跑通。
        from app.markdown_lite import to_html

        rendered = to_html("## 自检\n\n**粗体** 与 `code`\n\n- 甲\n- 乙")
        steps["markdown_html"] = len(rendered)
        steps["markdown_ok"] = ("<b>" in rendered and "<ul>" in rendered and "##" not in rendered)

        from ai.client import AISettings

        steps["ai_default_timeout_s"] = AISettings().timeout_s

        # 声学校准：只验算一次偏移量，确认换算模块进了包且公式没被改坏
        from core.calibration import Calibration

        steps["calibration_offset_db"] = round(
            Calibration(name="自检", sensitivity_mv_pa=10.0).offset_db(), 3)
        report["ok"] = True
    except Exception:
        report["error"] = traceback.format_exc()

    target = wav_path.with_name("selftest_result.json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1


def main() -> int:
    selftest_target = os.environ.get("WAV_ANALYZER_SELFTEST", "").strip()
    if selftest_target:
        return _selftest(Path(selftest_target))

    app = QApplication(sys.argv)
    app.setApplicationName("声音实验 WAV 数据处理程序")
    app.setOrganizationName("PhysicsExperiment")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei", 9))
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():
        # 异步载入：窗口先出现并显示“处理中”，避免长文件启动时假死。
        window.load_audio_async(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
