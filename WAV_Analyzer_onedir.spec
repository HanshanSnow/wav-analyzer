# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 配置（文件夹版 / onedir）：程序与依赖平铺在一个目录里。

UPX 同单文件版：未安装，`upx=True` 只是空操作，显式关闭以免误判产物形态。

与单文件版的区别只有最后一节：单文件版把 a.binaries / a.datas 塞进 EXE，
启动时整包解压到 %TEMP%\\_MEIxxxx；文件夹版把它们留在旁边，
**启动完全不碰临时目录**——临时目录坏掉的机器上也能直接跑。

用法（项目根目录，产物在 dist\\WAV Analyzer\\）：
    pyinstaller --noconfirm --clean WAV_Analyzer_onedir.spec

两个版本共用同一份 Analysis 配置（hiddenimports、datas 规则完全一致），
改依赖时请同时改 WAV_Analyzer.spec 和本文件。
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

# pyqtgraph 用字符串拼模块名再 importlib 导入，静态分析看不见，必须手写。
hiddenimports += [
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtSvg",
    "pyqtgraph.Qt.OpenGLHelpers",
]

# 应用内手册：两版 PDF 随包带走（软件用 QtPdf 直接打开）。
for _manual in ("manual_zh.pdf", "manual_en.pdf"):
    _manual_path = os.path.join(ROOT, "docs", _manual)
    if os.path.isfile(_manual_path):
        datas += [(_manual_path, "docs")]

# 窗口与任务栏图标（exe 自身图标另由 EXE(icon=...) 指定）
for _icon in ("wav_analyzer.ico", "wav_analyzer_icon.png"):
    _icon_file = os.path.join(ROOT, _icon)
    if os.path.isfile(_icon_file):
        datas += [(_icon_file, ".")]

hiddenimports += [
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
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
    [],
    exclude_binaries=True,
    name="WAV Analyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "wav_analyzer.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="WAV Analyzer",
)
