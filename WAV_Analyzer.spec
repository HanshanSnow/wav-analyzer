# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 配置：单文件、无控制台，自带音频运行时。

用法（必须在项目根目录执行，spec 里的相对路径依赖当前工作目录）：
    pyinstaller --noconfirm --clean WAV_Analyzer.spec

两个容易漏的运行时依赖：
  _sounddevice_data  -> PortAudio DLL（播放功能，缺了会 "PortAudio library not found"）
  _soundfile_data    -> libsndfile DLL（读写 WAV，缺了会 "cannot load library libsndfile"）
二者都是普通包，用 collect_all 一次性收齐数据与子模块。
keyring 在 Windows 上必须带上 backends.Windows，否则保存 API Key 会报 NoKeyringError。

PySide6 的 Qt 子模块里有一批是 pyqtgraph 用 importlib 动态拼名字导入的
（``importlib.import_module(f"{QT_LIB}.QtOpenGL")``），静态分析看不见，
必须显式写进 hiddenimports，否则打出来的 exe 一启动就
"No module named 'PySide6.QtOpenGL'"。
"""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(os.getcwd())

datas = []
binaries = []
hiddenimports = []

for package in ("_sounddevice_data", "_soundfile_data"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

hiddenimports += [
    "sounddevice",
    "soundfile",
    "keyring.backends.Windows",
] + collect_submodules("keyring.backends")

# pyqtgraph 用字符串拼出模块名再 importlib 导入，静态分析抓不到，必须手写。
# QtOpenGL / QtOpenGLWidgets 是 PlotCurveItem 与 RawImageWidget 的硬依赖：
# 少了它，exe 在 import app.main_window 时就崩，界面根本起不来。
hiddenimports += [
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtSvg",
    "pyqtgraph.Qt.OpenGLHelpers",
]

a = Analysis(
    ["run_app.py"],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "PyQt5",
        "PyQt6",
        "matplotlib.tests",
        "numpy.random.tests",
        "pytest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WAV Analyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "wav_analyzer.ico"),
)
