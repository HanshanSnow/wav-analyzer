import os
import sys
from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication


def _apply_saved_language() -> None:
    """在导入界面模块之前确定界面语言。

    时机很重要：``app/`` 与 ``core/`` 里有模块级的 ``tr()`` 字符串常量，它们在
    import 时求值。如果先 import 再切语言，那些常量会永远停在中文。
    """
    from PySide6.QtCore import QSettings

    from core.i18n import DEFAULT_LANGUAGE, LANGUAGE_SETTINGS_KEY, set_language

    set_language(str(QSettings().value(LANGUAGE_SETTINGS_KEY, DEFAULT_LANGUAGE)))


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

        # 界面双语：确认英文词表进了包，查表能命中，且切回中文后回落正常
        from core.i18n import LANG_EN, LANG_ZH, set_language, tr
        from core.i18n_en import EN

        set_language(LANG_EN)
        steps["i18n_en_entries"] = len(EN)
        steps["i18n_probe_en"] = tr("打开 WAV")
        steps["i18n_ok"] = tr("打开 WAV") == "Open WAV"
        set_language(LANG_ZH)
        steps["i18n_ok"] = steps["i18n_ok"] and tr("打开 WAV") == "打开 WAV"

        # 界面模块连同 pyqtgraph 的 Qt 子模块一起 import 一遍。
        # 这些子模块是 importlib 拼字符串导入的，静态分析看不见，最容易漏打；
        # 以前自检只跑算法链路，漏了 QtOpenGL 也照样报 ok，结果 exe 一启动就崩。
        import pyqtgraph  # noqa: F401

        from pyqtgraph.Qt import OpenGLHelpers  # noqa: F401
        from PySide6 import QtOpenGL, QtOpenGLWidgets  # noqa: F401

        steps["pyqtgraph_version"] = pyqtgraph.__version__
        steps["qt_opengl"] = f"{QtOpenGL.__name__} / {QtOpenGLWidgets.__name__}"
        import app.main_window  # noqa: F401

        steps["gui_import"] = "ok"

        # 再往前一步：真正把主窗口建出来。import 通过不代表能画——Qt 平台插件
        # （qwindows.dll）、图标资源、样式表缺失都要到这一步才暴露。
        QApplication.instance() or QApplication(sys.argv[:1])
        window = app.main_window.MainWindow()
        steps["gui_window"] = f"{window.windowTitle()} / {window.tabs.count()} 个页签"
        window.deleteLater()
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

    # 语言必须在导入主窗口之前定下来（QSettings 也已就绪，路径依赖上面两个名称）
    _apply_saved_language()
    from app.main_window import MainWindow

    window = MainWindow()
    window.show()
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():
        # 异步载入：窗口先出现并显示“处理中”，避免长文件启动时假死。
        window.load_audio_async(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
