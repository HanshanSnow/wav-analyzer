import os
import subprocess
import sys
from pathlib import Path


def _import_launcher():
    """按文件路径加载 ``core/launcher.py``。

    不能在文件顶部 ``from core.launcher import ...``：``core/__init__.py`` 会连带
    导入 soundfile 等第三方依赖，而这段代码恰恰要在「当前解释器缺依赖」时运行。
    顶部导入会让全局 Python 先抛 ModuleNotFoundError，连换解释器的机会都没有。
    """
    import importlib.util

    path = Path(__file__).resolve().parent / "core" / "launcher.py"
    spec = importlib.util.spec_from_file_location("_wav_launcher", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ensure_project_venv() -> None:
    """当前解释器缺 PySide6 时，改用项目内 ``.venv`` 的解释器重新执行本脚本。

    为什么需要：双击 ``run_app.bat`` 会优先用 .venv，但 ``py -3 run_app.py``、
    ``python run_app.py``、IDE 的运行按钮都会落到全局解释器上。全局 Python 没有
    PySide6，进程报 ModuleNotFoundError 后立刻退出，表现出来就是「打不开软件」
    或「黑窗一闪就没了」。这里在 import PySide6 之前把解释器换过来，
    让所有启动方式都能进界面。
    """
    if getattr(sys, "frozen", False):
        return
    try:
        import PySide6  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    script = Path(__file__).resolve()
    launcher = _import_launcher()
    venv_python = script.parent / ".venv" / "Scripts" / "python.exe"
    if not venv_python.is_file():
        message = (
            "启动失败：当前 Python 没有 PySide6，且项目内没有 .venv。\n"
            "请装好依赖后重试：\n"
            "  py -3 -m venv .venv\n"
            "  .venv\\Scripts\\python.exe -m pip install -r requirements.txt"
        )
        launcher.report_startup_failure(message)
        raise SystemExit(message)
    # 优先 pythonw.exe：用控制台解释器重启会再弹一个黑框，双击 bat 时尤其明显。
    target = launcher.pythonw_sibling(venv_python)
    try:
        same_interpreter = Path(sys.executable).resolve() == Path(target).resolve()
    except OSError:
        same_interpreter = False
    if same_interpreter:
        return
    # 不能用 os.execv：Windows 上它把参数按空格拼接，工作区路径里带空格就会拆错。
    raise SystemExit(
        subprocess.run(
            [target, str(script), *sys.argv[1:]], **launcher.no_window_flags()
        ).returncode
    )


_ensure_project_venv()

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _apply_saved_language() -> None:
    """在导入界面模块之前确定界面语言。

    时机很重要：``app/`` 与 ``core/`` 里有模块级的 ``tr()`` 字符串常量，它们在
    import 时求值。如果先 import 再切语言，那些常量会永远停在中文。
    """
    from PySide6.QtCore import QSettings

    from core.i18n import (
        DEFAULT_LANGUAGE,
        LANGUAGE_SETTINGS_KEY,
        language_from_environment,
        set_language,
    )

    # 环境变量优先：截图脚本与测试用 WAV_ANALYZER_UI_LANG 强制语言，不必改动用户
    # 已经保存的选择（切换语言要重启，脚本里没有重启这回事）。
    set_language(
        language_from_environment()
        or str(QSettings().value(LANGUAGE_SETTINGS_KEY, DEFAULT_LANGUAGE))
    )


def _configure_settings() -> None:
    """把设置写进本地 INI 文件，而不是注册表。

    起因：在部分机器上（HKCU 被策略收紧、或程序跑在受限令牌下）QSettings 写
    注册表会静默失败，表现就是「切换语言后重启还是中文」「改过的设置重开就没了」。
    INI 只依赖本地目录的写权限，稳妥得多。v2.0 起统一走 INI；老用户注册表里的
    旧设置不会自动迁移，第一次启动回到默认值。
    """
    from PySide6.QtCore import QSettings

    # 固定写在程序自己所在目录（便携版就该这样），只有该目录不可写时才退到
    # %LOCALAPPDATA%。顺序不能反过来：以前优先 AppData，结果「管理员运行能建目录
    # → 写进 AppData」和「普通运行建不了 → 写入程序目录」两套位置并存，
    # 换一种方式启动就读不到设置，表现成「明明保存了却说没填」。
    program_dir = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
                   else Path(__file__).resolve().parent)
    candidates = [program_dir]
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "WAV Analyzer")

    for base in candidates:
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        if not os.access(base, os.W_OK):
            continue
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(base))
        return
    # 两处都写不了就沿用默认（注册表），至少还能启动


def _configure_matplotlib_cache() -> None:
    """给 matplotlib 指定一个**持久可写**的缓存目录。

    默认位置是 `%LOCALAPPDATA%\\matplotlib`；在某些机器上普通进程建不了这个目录，
    matplotlib 就退化成"每次启动都建一个临时目录并重建字体缓存"，
    实测让主窗口导入从 1.13 s 变成 1.72 s（审查 P1）。
    必须在**任何** matplotlib 导入之前调用。
    """
    if os.environ.get("MPLCONFIGDIR"):
        return  # 尊重用户/CI 已显式指定的位置
    program_dir = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
                   else Path(__file__).resolve().parent)
    candidates = []
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "WAV Analyzer" / "matplotlib")
    candidates.append(program_dir / "matplotlib-cache")
    for base in candidates:
        try:
            base.mkdir(parents=True, exist_ok=True)
            probe = base / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError:
            continue
        os.environ["MPLCONFIGDIR"] = str(base)
        return


APP_USER_MODEL_ID = "HanshanSnow.WAVAnalyzer.2"

ICON_NAMES = ("wav_analyzer.ico", "wav_analyzer_icon.png")


def _program_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _icon_path() -> Path | None:
    """图标文件：源码态在项目根，冻结后在解包目录里（见两个 spec 的 datas）。"""
    bases = [Path(getattr(sys, "_MEIPASS", _program_dir())), _program_dir()]
    for base in bases:
        for name in ICON_NAMES:
            candidate = base / name
            if candidate.is_file():
                return candidate
    return None


def _set_windows_app_id() -> None:
    """给进程一个自己的 AppUserModelID。

    不设的话，Windows 任务栏按宿主进程分组：源码运行显示 pythonw 的图标，
    打包运行显示引导器的图标，而不是程序自己的图标。必须在建窗口之前设。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:  # noqa: BLE001 - 设不上只是图标不好看，不该影响启动
        pass


def _apply_window_icon(app, window=None) -> None:
    """把窗口/任务栏图标设成程序自己的图标。"""
    from PySide6.QtGui import QIcon

    path = _icon_path()
    if path is None:
        return
    icon = QIcon(str(path))
    if icon.isNull():
        return
    app.setWindowIcon(icon)
    if window is not None:
        window.setWindowIcon(icon)


def _make_splash(app):
    """一个轻量启动画面：在导入界面模块之前先给用户看到东西。

    静态图即可——接下来的导入是阻塞的，动画和进度条在这段时间根本不会更新，
    显示假进度比不显示更糟。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPixmap
    from PySide6.QtWidgets import QSplashScreen

    icon_file = _icon_path()
    if icon_file is None:
        return None
    pixmap = QPixmap(str(icon_file))
    if pixmap.isNull():
        return None
    pixmap = pixmap.scaled(220, 220, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    splash = QSplashScreen(pixmap)
    from core.i18n import tr

    splash.showMessage(tr("正在载入界面…"),
                       Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                       QColor(0x45, 0x5A, 0x64))
    splash.show()
    app.processEvents()
    return splash


def _prepare_export_backend() -> None:
    """首帧之后在 GUI 线程导入并预热 matplotlib。

    不能放到工作线程：第一次导入 matplotlib 若发生在 TaskWorker 里，
    Python 3.13 + PySide6 会在 shiboken 特性探测阶段触发 access violation。
    """
    try:
        from core.figure_export import ensure_ready

        ensure_ready()
    except Exception:  # noqa: BLE001 - 预热失败不该影响主界面
        pass


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
        steps["i18n_probe_en"] = tr("打开音频")
        steps["i18n_ok"] = tr("打开音频") == "Open audio"
        set_language(LANG_ZH)
        steps["i18n_ok"] = steps["i18n_ok"] and tr("打开音频") == "打开音频"

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

        # 应用内手册：QtPdf 的两个子模块要到打开手册时才导入，同样抓不到；
        # 顺手确认手册 PDF 真的随包带走了，否则点「使用手册」只会看到缺文件提示。
        from PySide6 import QtPdf, QtPdfWidgets  # noqa: F401

        from app.manual_viewer import manual_path

        steps["qt_pdf"] = f"{QtPdf.__name__} / {QtPdfWidgets.__name__}"
        found_manual = manual_path()
        steps["manual_pdf"] = str(found_manual) if found_manual is not None else ""
        steps["manual_pdf_present"] = found_manual is not None
        # 图标没打进包时，任务栏会退回 Python/引导器的图标——这正是用户反馈过的问题
        steps["icon_present"] = _icon_path() is not None

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

    # 必须在 QApplication 之前：Qt 在创建应用时就会内部建一次 QSettings，
    # 之后再改默认格式对已经成型的那份不起作用（实测仍写注册表）。
    _set_windows_app_id()
    _configure_settings()
    _configure_matplotlib_cache()

    app = QApplication(sys.argv)
    app.setApplicationName("声音实验 WAV 数据处理程序")
    app.setOrganizationName("PhysicsExperiment")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei", 9))
    _apply_window_icon(app)

    # 语言必须在导入主窗口之前定下来（QSettings 也已就绪，路径依赖上面两个名称）
    _apply_saved_language()

    # 闪屏要在导入界面模块之前出现；导入是阻塞的，所以先 processEvents 把它画出来
    splash = _make_splash(app)
    window = None
    try:
        from app.main_window import MainWindow

        window = MainWindow()
        _apply_window_icon(app, window)
        window.show()
    finally:
        if splash is not None:
            splash.finish(window)  # 失败时 window 为 None，也要把闪屏关掉

    # 重活挪到首帧之后：matplotlib 导入 + 预热仍是 GUI 线程，只是不再挡首帧
    from PySide6.QtCore import QTimer

    QTimer.singleShot(0, _prepare_export_backend)
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():
        # 异步载入：窗口先出现并显示“处理中”，避免长文件启动时假死。
        window.load_audio_async(sys.argv[1])
    return app.exec()


def _launch() -> int:
    """包住整个启动过程，让任何异常都能「看得见」地失败。

    pythonw 下没有控制台，异常不处理就只剩「双击没反应」，用户拿不到任何线索。
    这里统一转成消息框 + startup_error.log；SystemExit 照常透传退出码。
    """
    try:
        return main()
    except SystemExit:
        raise
    except BaseException:
        import traceback

        _import_launcher().report_startup_failure("启动失败：\n" + traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(_launch())

