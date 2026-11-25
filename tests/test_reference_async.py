"""参考文件校验的异步化与缓存测试（审计 P1）。

要求：
- 对话框里选文件/换声道不能阻塞事件循环；
- 迟到的旧结果必须作废（换了文件后不能被旧结果覆盖）；
- 校验结果按「路径+声道+采样率+文件身份」缓存，文件被替换后自动失效；
- 批量对同一份参考只解码一次。
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication

from core.audio_io import write_wav
from core.reference import REFERENCE_CACHE, file_identity, load_reference_cached

FS = 8000


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _reference(path, seconds=0.8, amplitude=0.05, fs=FS, seed=1):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * fs)) / fs
    data = amplitude * rng.standard_normal(t.size) + 0.001 * np.sin(2 * np.pi * 120 * t)
    write_wav(path, data[:, None], fs, subtype="PCM_16")
    return path


def _pump(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_reference_cache_hits_for_unchanged_file(app, tmp_path, monkeypatch):
    import core.reference as ref_module

    path = _reference(tmp_path / "ref.wav")
    calls = {"n": 0}
    real = ref_module.read_wav

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(ref_module, "read_wav", counting)
    REFERENCE_CACHE.clear()

    first = load_reference_cached(path, sample_rate=FS)
    second = load_reference_cached(path, sample_rate=FS)
    assert calls["n"] == 1, "同一文件被解码了两次"
    assert first.sha256 == second.sha256
    assert first.identity == file_identity(path)


def test_reference_cache_invalidates_when_file_changes(app, tmp_path, monkeypatch):
    import core.reference as ref_module

    REFERENCE_CACHE.clear()
    path = _reference(tmp_path / "ref.wav", amplitude=0.05)
    calls = {"n": 0}
    real = ref_module.read_wav

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(ref_module, "read_wav", counting)
    load_reference_cached(path, sample_rate=FS)
    # 覆盖成另一个文件（内容与大小都变），身份失效后必须重新解码
    _reference(path, amplitude=0.2, seed=9)
    os.utime(path, None)
    load_reference_cached(path, sample_rate=FS)
    assert calls["n"] == 2, "文件被替换后仍命中了旧缓存"


def test_dialog_validation_does_not_block_the_event_loop(app, tmp_path, monkeypatch):
    import core.reference as ref_module
    from app.anc_dialog import AncToolsDialog

    REFERENCE_CACHE.clear()
    path = _reference(tmp_path / "ref.wav")
    real = ref_module.load_reference

    def slow(*args, **kwargs):
        time.sleep(0.4)                       # 模拟慢盘 / 大文件
        return real(*args, **kwargs)

    monkeypatch.setattr(ref_module, "load_reference", slow)

    settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    dialog = AncToolsDialog(None, channels=1, settings=settings, sample_rate=FS)
    dialog.ref_source.setCurrentIndex(dialog.ref_source.findData("external"))
    dialog._reference_path = str(path)

    start = time.perf_counter()
    dialog._sync_reference()                 # 只发起后台校验
    elapsed = time.perf_counter() - start
    assert elapsed < 0.2, f"对话框同步校验耗时 {elapsed * 1000:.0f} ms"
    assert "校验" in dialog.ref_status.text()

    deadline = time.perf_counter() + 5.0
    while time.perf_counter() < deadline and "可用" not in dialog.ref_status.text():
        _pump(50)
    assert "可用" in dialog.ref_status.text(), dialog.ref_status.text()
    dialog.close()
    app.processEvents()


def test_stale_probe_result_is_ignored(app, tmp_path, monkeypatch):
    import core.reference as ref_module
    from app.anc_dialog import AncToolsDialog

    REFERENCE_CACHE.clear()
    first = _reference(tmp_path / "first.wav", amplitude=0.05)
    second = _reference(tmp_path / "second.wav", amplitude=0.2, seed=3)
    real = ref_module.load_reference

    def slow(*args, **kwargs):
        time.sleep(0.3)
        return real(*args, **kwargs)

    monkeypatch.setattr(ref_module, "load_reference", slow)
    settings = QSettings(str(tmp_path / "prefs2.ini"), QSettings.IniFormat)
    dialog = AncToolsDialog(None, channels=1, settings=settings, sample_rate=FS)
    dialog.ref_source.setCurrentIndex(dialog.ref_source.findData("external"))

    dialog._reference_path = str(first)
    dialog._sync_reference()
    dialog._reference_path = str(second)     # 立刻换成第二个文件
    dialog._sync_reference()

    deadline = time.perf_counter() + 5.0
    while time.perf_counter() < deadline and "可用" not in dialog.ref_status.text():
        _pump(50)
    assert "可用" in dialog.ref_status.text()
    # 结果必须对应第二个文件：帧数与第二个一致
    expected = real(str(second), sample_rate=FS, channel=0)
    assert f"{expected.frames:,}" in dialog.ref_status.text()
    dialog.close()
    app.processEvents()


def test_batch_decodes_shared_reference_once(app, tmp_path, monkeypatch):
    import core.reference as ref_module
    from core.batch import new_step, run_batch

    REFERENCE_CACHE.clear()
    folder = tmp_path / "in"
    folder.mkdir()
    files = []
    for index in range(2):
        path = folder / f"t{index}.wav"
        t = np.arange(FS) / FS
        write_wav(path, (0.3 * np.sin(2 * np.pi * 1000 * t))[:, None], FS, subtype="PCM_16")
        files.append(path)
    reference = _reference(tmp_path / "shared.wav")

    calls = {"n": 0}
    real = ref_module.load_reference

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(ref_module, "load_reference", counting)
    step = new_step("denoise_tools")
    step["params"]["method"] = "noise_profile"
    result = run_batch(files, [step, new_step("export_csv")], output_dir=tmp_path / "out",
                       reference={"path": str(reference), "channel": 0})
    assert result.ok_count == 2
    assert calls["n"] == 1, f"两个输入解码了 {calls['n']} 次参考"


# ---------------------------------------------------------------- 脚本溯源
def _script_payload(dialog) -> dict:
    return {"version": 1, "steps": dialog.steps,
            "reference": dialog._reference_for_script()}


def test_script_reference_records_identity(app, tmp_path):
    from app.batch_dialog import BatchDialog

    REFERENCE_CACHE.clear()
    reference = _reference(tmp_path / "ref.wav")
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    dialog = BatchDialog(None, settings=settings)
    dialog._reference_path = str(reference)
    block = dialog._reference_for_script()
    assert block["sha256"] and block["size"] and block["mtime_ns"]
    assert block["channel"] == 0
    dialog.close()
    app.processEvents()


def test_script_reference_missing_is_reported_and_cleared(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from app.batch_dialog import BatchDialog

    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *args, **kwargs: warnings.append(str(args[2])))
    settings = QSettings(str(tmp_path / "s2.ini"), QSettings.IniFormat)
    dialog = BatchDialog(None, settings=settings)
    dialog._restore_script_reference({"path": str(tmp_path / "gone.wav"), "channel": 0})
    assert dialog._reference_path == ""
    assert warnings and "不在了" in warnings[0]
    dialog.close()
    app.processEvents()


def test_script_reference_changed_is_reported_and_cleared(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from app.batch_dialog import BatchDialog

    reference = _reference(tmp_path / "ref2.wav", amplitude=0.05)
    from core.reference import file_identity

    size, mtime = file_identity(reference)
    _reference(tmp_path / "ref2.wav", amplitude=0.3, seed=11)   # 覆盖内容
    os.utime(reference, None)

    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *args, **kwargs: warnings.append(str(args[2])))
    settings = QSettings(str(tmp_path / "s3.ini"), QSettings.IniFormat)
    dialog = BatchDialog(None, settings=settings)
    dialog._restore_script_reference({"path": str(reference), "channel": 0,
                                      "size": size, "mtime_ns": mtime})
    assert dialog._reference_path == ""
    assert warnings and "不一致" in warnings[0]
    dialog.close()
    app.processEvents()


@pytest.fixture(autouse=True)
def _close_batch_dialogs():
    """收掉本文件创建的 BatchDialog：不关闭时 pytest 收尾可能以 0xC0000409 退出。"""
    yield
    from PySide6.QtWidgets import QApplication as _QApp

    from app.batch_dialog import BatchDialog

    application = _QApp.instance()
    if application is None:
        return
    for widget in application.topLevelWidgets():
        if isinstance(widget, BatchDialog):
            widget.close()
            widget.deleteLater()
    application.processEvents()


def test_script_reference_unchanged_is_restored(app, tmp_path):
    from app.batch_dialog import BatchDialog

    reference = _reference(tmp_path / "ref3.wav")
    from core.reference import file_identity

    size, mtime = file_identity(reference)
    settings = QSettings(str(tmp_path / "s4.ini"), QSettings.IniFormat)
    dialog = BatchDialog(None, settings=settings)
    dialog._restore_script_reference({"path": str(reference), "channel": 1,
                                      "size": size, "mtime_ns": mtime})
    assert dialog._reference_path == str(reference)
    assert dialog.reference_channel.value() == 2      # 控件是 1 基
    dialog.close()
    app.processEvents()
