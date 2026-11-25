"""批量处理测试：步骤规格、引擎行为、去噪回归、脚本编辑窗口与主窗口串联。"""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from app.batch_dialog import BatchDialog
from app.batch_progress import BatchProgressOverlay
from app.main_window import MainWindow
from core.audio_io import read_wav, write_wav
from core.batch import (
    STEP_SPECS, describe_step, new_step, normalize_steps,
    parse_fundamental_from_name, resolve_fundamental, resolve_region, run_batch,
)
from core.denoise import detect_and_repair_impulses

FS = 8000


def _app():
    return QApplication.instance() or QApplication([])


def _settings(tmp_path) -> QSettings:
    store = QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    store.clear()
    return store


@pytest.fixture(autouse=True)
def _close_batch_dialogs():
    """收掉测试里创建的 BatchDialog。

    不关闭时，pytest 打印完 "N passed" 进程仍会以 0xC0000409 退出（BUG-022）：
    摘要说成功、进程却失败，这种假绿灯会掩盖真实回归。
    只处理 BatchDialog，不去动其它窗口——全局清理会误伤后面还要用的对象。
    """
    yield
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        if isinstance(widget, BatchDialog):
            widget.close()
            widget.deleteLater()
    app.processEvents()


def _tone(path, f0, amp=0.3, seconds=2.0, fs=FS, noise=1e-4):
    t = np.arange(int(fs * seconds)) / fs
    rng = np.random.default_rng(0)
    x = amp * np.sin(2 * np.pi * f0 * t) + rng.normal(0.0, noise, t.size)
    write_wav(path, x, fs, subtype="PCM_16")
    return path


def _wait_worker(window: MainWindow, timeout_ms: int = 90000) -> None:
    loop = QEventLoop()
    probe = QTimer()
    probe.setInterval(30)
    probe.timeout.connect(lambda: loop.quit() if window.batch_worker is None else None)
    probe.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    probe.stop()


# ---------------------------------------------------------------- 步骤规格


def test_step_specs_cover_all_single_file_functions():
    kinds = {spec.kind for spec in STEP_SPECS}
    assert kinds == {
        "denoise", "denoise_tools", "trim", "envelope", "stats", "dual",
        "export_wav", "export_txt", "export_png", "export_csv", "export_html",
    }, "单文件能做的处理与导出都应在批量步骤里可选"


def test_new_step_returns_independent_params():
    first = new_step("export_txt")
    second = new_step("export_txt")
    first["params"]["sections"].remove("coords")
    assert "coords" in second["params"]["sections"], "两份默认参数不能共享同一个 list"


def test_normalize_steps_fills_defaults_and_drops_unknown():
    steps = normalize_steps([
        {"kind": "stats", "params": {"region": "trim"}},
        {"kind": "not-a-step", "params": {}},
        {"kind": "export_csv"},
    ])
    assert [item["kind"] for item in steps] == ["stats", "export_csv"]
    assert steps[0]["params"]["region"] == "trim"
    assert steps[0]["params"]["head"] == 0.2, "缺失参数应补成默认值"
    assert steps[1]["params"]["aggregate"] == "single"


def test_describe_step_hides_irrelevant_params():
    step = new_step("stats")
    step["params"]["region"] = "all"
    text = describe_step(step)
    assert "去掉" not in text and "起点" not in text, "全文件模式下不该显示首尾/区间参数"
    step["params"]["region"] = "trim"
    assert "去掉首尾" in describe_step(step)
    step["params"]["head"] = 0.5
    assert "0.5s" in describe_step(step), "非默认值要显示出来"


def test_describe_step_reports_single_choice():
    step = new_step("export_txt")
    step["params"]["aggregate"] = "single"
    assert "合并为一个 TXT" in describe_step(step)


# ---------------------------------------------------------------- 参数解析


def test_parse_fundamental_from_name():
    assert parse_fundamental_from_name("ref_1000Hz_D10_r1.wav") == 1000.0
    assert parse_fundamental_from_name("size_P3_2kHz.wav") == 2000.0
    assert parse_fundamental_from_name("bg_20261110.wav") is None


def test_resolve_fundamental_modes():
    assert resolve_fundamental({"fundamental": "auto"}, "a_1000Hz.wav") is None
    assert resolve_fundamental({"fundamental": "fixed", "fundamental_hz": 500}, "x.wav") == 500
    assert resolve_fundamental({"fundamental": "name"}, "a_2000Hz.wav") == 2000
    assert resolve_fundamental({"fundamental": "fixed", "fundamental_hz": 0}, "x.wav") is None


def test_resolve_region_modes():
    assert resolve_region({"region": "all"}, 5.0) == (0.0, 5.0)
    assert resolve_region({"region": "trim", "head": 0.5, "tail": 1.0}, 5.0) == (0.5, 4.0)
    assert resolve_region({"region": "fixed", "start": 1.0, "end": 3.0}, 5.0) == (1.0, 3.0)
    # 终点 0 表示到文件末尾；越界要夹紧
    assert resolve_region({"region": "fixed", "start": 1.0, "end": 0.0}, 5.0) == (1.0, 5.0)
    assert resolve_region({"region": "fixed", "start": 1.0, "end": 99.0}, 5.0) == (1.0, 5.0)


def test_resolve_region_rejects_empty():
    with pytest.raises(ValueError):
        resolve_region({"region": "trim", "head": 1.0, "tail": 1.0}, 2.0)


# ---------------------------------------------------------------- 引擎


def test_run_batch_produces_all_outputs(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    files = [_tone(folder / "size_P3_500Hz_D10_r1.wav", 500),
             _tone(folder / "size_P3_1000Hz_D10_r1.wav", 1000)]
    out = tmp_path / "out"

    steps = [new_step("envelope")]
    stats = new_step("stats")
    stats["params"].update({"region": "trim", "head": 0.2, "tail": 0.2,
                            "fundamental": "name"})
    steps.append(stats)
    steps.append(new_step("export_wav"))
    txt = new_step("export_txt")
    txt["params"].update({"aggregate": "single", "sections": ["fourier", "stats"]})
    steps.append(txt)
    steps.append(new_step("export_png"))
    steps.append(new_step("export_csv"))
    steps.append(new_step("export_html"))

    result = run_batch(files, steps, output_dir=out)
    assert result.ok_count == 2 and result.fail_count == 0, result.summary()
    assert result.cancelled is False

    names = {path.name for path in out.iterdir()}
    assert "size_P3_500Hz_D10_r1_处理后.wav" in names
    assert "size_P3_500Hz_D10_r1_波形.png" in names
    assert "size_P3_500Hz_D10_r1_报告.html" in names
    assert "批量分析汇总.txt" in names and "批量统计.csv" in names

    csv_text = (out / "批量统计.csv").read_text(encoding="utf-8-sig").splitlines()
    assert len(csv_text) == 3, "两个文件应合并成表头 + 两行"
    assert "main_amplitude_dbfs" in csv_text[0]

    merged = (out / "批量分析汇总.txt").read_text(encoding="utf-8-sig")
    assert merged.count("— 分析数据导出") == 2, "合并模式下每个文件都要有自己的段头"
    assert "size_P3_500Hz_D10_r1.wav" in merged and "size_P3_1000Hz_D10_r1.wav" in merged
    assert merged.count("\ufeff") == 0, "追加时不能再写 BOM，否则文件中间会冒出怪字符"


def test_merged_txt_has_single_bom(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    files = [_tone(folder / f"a_{f}Hz.wav", f) for f in (500, 1000)]
    out = tmp_path / "out"
    txt = new_step("export_txt")
    txt["params"].update({"aggregate": "single", "sections": ["fourier"]})
    run_batch(files, [txt], output_dir=out)
    raw = (out / "批量分析汇总.txt").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "合并文件应以 UTF-8 BOM 开头，Excel 双击才不乱码"
    assert raw.count(b"\xef\xbb\xbf") == 1, "BOM 只能出现一次"


def test_per_file_export_writes_one_output_each(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    files = [_tone(folder / f"b_{f}Hz.wav", f) for f in (500, 1000)]
    out = tmp_path / "out"
    txt = new_step("export_txt")
    txt["params"].update({"aggregate": "file", "sections": ["stats"]})
    result = run_batch(files, [txt], output_dir=out)
    assert result.ok_count == 2
    assert (out / "b_500Hz_分析.txt").exists() and (out / "b_1000Hz_分析.txt").exists()


def test_dual_channel_step_is_skipped_on_mono(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    files = [_tone(folder / "c_500Hz.wav", 500)]
    result = run_batch(files, [new_step("dual")], output_dir=tmp_path / "out")
    assert result.ok_count == 1
    assert any("单声道" in note for note in result.files[0].notes)


def test_batch_continues_after_unreadable_file(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    good = _tone(folder / "d_500Hz.wav", 500)
    bad = folder / "d_broken.wav"
    bad.write_bytes(b"not a wav file")
    result = run_batch([good, bad], [new_step("export_csv")], output_dir=tmp_path / "out")
    assert result.ok_count == 1 and result.fail_count == 1
    assert "d_broken.wav" in result.summary()


def test_batch_progress_reports_import_then_process(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    files = [_tone(folder / f"e_{f}Hz.wav", f) for f in (500, 1000)]
    events: list[tuple] = []
    run_batch(files, [new_step("export_csv")], output_dir=tmp_path / "out",
              progress=lambda *args: events.append(args))
    stages = [event[0] for event in events]
    assert stages[0] == "import" and stages[1] == "process"
    assert stages.count("import") == 2, "每个文件一次导入"
    assert events[0][1] == 1 and events[0][2] == 2, "序号与总数要能对上"
    assert stages[-1] == "done"


def test_batch_can_be_cancelled_between_files(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    files = [_tone(folder / f"f_{f}Hz.wav", f) for f in (500, 1000)]
    calls = {"n": 0}

    def should_cancel() -> bool:
        # 第一次询问（第一个文件开始前）不取消，之后取消
        calls["n"] += 1
        return calls["n"] > 1

    result = run_batch(files, [new_step("export_csv")], output_dir=tmp_path / "out",
                       should_cancel=should_cancel)
    assert result.cancelled is True
    assert len(result.files) == 1, "取消只在文件之间生效，当前文件仍完整处理完"


def test_batch_marks_clipped_source(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    path = folder / "g_500Hz.wav"
    t = np.arange(FS) / FS
    write_wav(path, np.clip(1.4 * np.sin(2 * np.pi * 500 * t), -1.0, 1.0), FS, subtype="PCM_16")
    result = run_batch([path], [new_step("export_csv")], output_dir=tmp_path / "out")
    assert any("削顶" in note for note in result.files[0].notes)


# ---------------------------------------------------------------- 去噪回归


def test_denoise_ignores_steady_tone():
    """稳态纯音不能被判成冲击：中值滤波对缓变正弦几乎逐点精确复现，
    残差的稳健尺度会塌到量化噪声量级，之前会把整段标为无效。"""
    for f0 in (200, 500, 1000, 2000, 4000):
        t = np.arange(int(FS * 2)) / FS
        x = 0.25 * np.sin(2 * np.pi * f0 * t)
        result = detect_and_repair_impulses(x, FS, 8.0, max_repair_ms=3.0)
        assert result.events == [], f"{f0} Hz 纯音不应触发冲击检测"
        assert result.valid_mask.all()


def test_denoise_still_catches_short_impulses():
    t = np.arange(int(FS * 2)) / FS
    x = 0.25 * np.sin(2 * np.pi * 500 * t)
    for position in (3000, 8000, 13000):
        x[position:position + 2] += 0.6
    result = detect_and_repair_impulses(x, FS, 8.0, max_repair_ms=3.0)
    assert len(result.events) == 3, "三个冲击都应检出"
    assert result.repaired_count == 3
    assert [round(event.start_sample / FS, 2) for event in result.events] == [0.37, 1.0, 1.62]


# ---------------------------------------------------------------- 脚本窗口


def test_dialog_default_script(tmp_path):
    _app()
    dialog = BatchDialog(None, settings=_settings(tmp_path))
    assert [step["kind"] for step in dialog.steps] == ["stats", "export_txt", "export_csv"]
    assert dialog.step_list.count() == 3
    assert dialog.step_list.item(0).text().startswith("1. ")


def test_fourier_cache_follows_effective_fundamental(tmp_path):
    """P0 回归：dual(自动估峰) 之后 stats 指定固定基频，导出必须重算频谱。

    只缓存一个 FourierResult 的话，导出会沿用自动估峰那份 200 Hz 的结果，
    而用户明确指定的 100 Hz 只体现在统计表里。
    """
    stereo = tmp_path / "stereo.wav"
    t = np.arange(int(2.0 * FS)) / FS
    channel = np.sin(2 * np.pi * 200.0 * t) + 0.2 * np.sin(2 * np.pi * 100.0 * t)
    write_wav(str(stereo), np.stack([channel, channel], axis=1).astype(np.float32),
              FS, subtype="PCM_24")

    from core.batch import _State, _ensure_fourier

    state = _State(stereo, read_wav(str(stereo)))
    auto = _ensure_fourier(state, None)
    assert abs(auto.main_frequency - 200.0) < 5.0, "自动估峰应落在 200 Hz"
    fixed = _ensure_fourier(state, 100.0)
    assert abs(fixed.main_frequency - 100.0) < 5.0, "指定 100 Hz 必须重算"
    assert _ensure_fourier(state, 100.0) is fixed, "同一基频应复用缓存"
    assert _ensure_fourier(state, None) is not fixed, "换基频必须重算"


def test_dialog_param_edit_syncs_list_and_enables_related_fields(tmp_path):
    _app()
    dialog = BatchDialog(None, settings=_settings(tmp_path))
    dialog.step_list.setCurrentRow(1)
    merged = dialog._widgets["merged_name"]
    assert merged.isEnabled() is False, "每个文件一个 TXT 时，合并文件名无意义"

    combo = dialog._widgets["aggregate"]
    combo.setCurrentIndex(combo.findData("single"))
    assert dialog.steps[1]["params"]["aggregate"] == "single"
    assert merged.isEnabled() is True
    assert "合并为一个 TXT" in dialog.step_list.item(1).text(), "摘要要跟着参数变"

    step_combo = dialog._widgets["coord_mode"]
    step_combo.setCurrentIndex(step_combo.findData("step"))
    assert dialog._widgets["coord_step"].isEnabled() is True
    assert dialog._widgets["coord_per_second"].isEnabled() is False


def test_dialog_checklist_roundtrip(tmp_path):
    _app()
    dialog = BatchDialog(None, settings=_settings(tmp_path))
    dialog.step_list.setCurrentRow(1)
    boxes = dialog._widgets["sections"]._boxes
    boxes["coords"].setChecked(False)
    boxes["ai"].setChecked(False)
    assert "coords" not in dialog.steps[1]["params"]["sections"]
    assert "fourier" in dialog.steps[1]["params"]["sections"]


def test_dialog_add_move_remove(tmp_path):
    _app()
    dialog = BatchDialog(None, settings=_settings(tmp_path))
    dialog._add_step("envelope")
    assert dialog.steps[-1]["kind"] == "envelope"
    dialog.step_list.setCurrentRow(3)
    dialog._move_step(-1)
    assert [step["kind"] for step in dialog.steps][-2:] == ["envelope", "export_csv"]
    dialog._remove_step()
    assert [step["kind"] for step in dialog.steps] == ["stats", "export_txt", "export_csv"]


def test_dialog_start_checks_files_first(tmp_path, monkeypatch):
    _app()
    dialog = BatchDialog(None, settings=_settings(tmp_path))
    seen: list[str] = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *args, **kwargs: seen.append(str(args[2])))
    dialog._on_start()
    assert seen and "文件" in seen[0]
    assert dialog.result() != dialog.DialogCode.Accepted


def test_dialog_script_roundtrip(tmp_path, monkeypatch):
    _app()
    dialog = BatchDialog(None, settings=_settings(tmp_path))
    dialog.step_list.setCurrentRow(1)
    combo = dialog._widgets["aggregate"]
    combo.setCurrentIndex(combo.findData("single"))
    path = tmp_path / "script.json"
    monkeypatch.setattr("app.batch_dialog.QFileDialog.getSaveFileName",
                        lambda *args, **kwargs: (str(path), ""))
    dialog._save_script()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["steps"][1]["params"]["aggregate"] == "single"

    fresh = BatchDialog(None, settings=_settings(tmp_path))
    assert fresh.steps[1]["params"]["aggregate"] == "file"
    monkeypatch.setattr("app.batch_dialog.QFileDialog.getOpenFileName",
                        lambda *args, **kwargs: (str(path), ""))
    fresh._load_script()
    assert fresh.steps[1]["params"]["aggregate"] == "single"


# ---------------------------------------------------------------- 遮罩


def test_overlay_shows_import_and_process_lines():
    _app()
    host = QWidget()
    host.resize(900, 640)
    host.show()
    overlay = BatchProgressOverlay(host)
    overlay.start(10)
    overlay.set_stage("import", 3, 10, "ref_1000Hz_D10_r1.wav", 0.0)
    assert "3/10" in overlay._line_import.text()
    assert "ref_1000Hz_D10_r1.wav" in overlay._line_import.text()
    assert overlay.isVisible()

    overlay.set_stage("process", 3, 10, "ref_1000Hz_D10_r1.wav", 0.5)
    assert overlay._line_process.text().startswith("正在处理文件")
    # 进度条按“已完成 2 个 + 当前 50%”折算，不能只看文件序号
    assert overlay._bar.value() == int((2 + 0.5) / 10 * 1000)

    overlay.set_stage("done", 10, 10, "", 1.0)
    assert overlay._bar.value() == 1000
    overlay.finish()
    assert overlay.isVisible() is False


# ---------------------------------------------------------------- 主窗口串联


def test_main_window_runs_batch_without_blocking(tmp_path, monkeypatch):
    app = _app()
    folder = tmp_path / "in"
    folder.mkdir()
    files = [_tone(folder / f"h_{f}Hz.wav", f) for f in (500, 1000)]
    out = tmp_path / "out"

    window = MainWindow()
    window.show()
    app.processEvents()
    assert window.batch_button.text() == "批量处理…"
    # 结果弹窗在无头环境会阻塞，直接吞掉
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Ok)

    steps = [new_step("export_csv"), new_step("export_wav")]
    assert window.start_batch(steps, [str(path) for path in files], str(out)) is True
    assert window.batch_overlay.isVisible(), "开始后应立刻显示进度遮罩"
    assert window.batch_button.isEnabled() is False, "运行期间不允许重复开始"

    _wait_worker(window)
    app.processEvents()

    assert window.batch_worker is None, "线程结束后必须释放引用"
    assert window.batch_overlay.isVisible() is False
    assert window.batch_button.isEnabled() is True
    assert (out / "批量统计.csv").exists()
    assert len(list(out.glob("*_处理后.wav"))) == 2


def test_main_window_rejects_second_batch(tmp_path):
    _app()
    window = MainWindow()
    assert window.start_batch([], ["x.wav"], "") is False
    assert window.start_batch([new_step("export_csv")], [], "") is False


# ---------------------------------------------------------------- 裁切到区间


def _trim(start: float, end: float) -> dict:
    step = new_step("trim")
    step["params"].update({"start": start, "end": end})
    return step


def test_batch_trim_clamps_beyond_file_length(tmp_path):
    """批量里文件长短不一：超出部分钳制并在备注里留痕，不整批失败。"""
    folder = tmp_path / "in"
    folder.mkdir()
    path = _tone(folder / "a_500Hz.wav", 500, seconds=2.0)
    out = tmp_path / "out"

    result = run_batch([path], [_trim(0.5, 99.0), new_step("export_wav")], output_dir=out)
    assert result.ok_count == 1, result.summary()
    notes = result.files[0].notes
    assert any("钳制" in note for note in notes), notes

    exported = next(out.glob("*_处理后.wav"))
    audio = read_wav(exported)
    assert audio.duration == pytest.approx(1.5, abs=1e-3)


def test_batch_trim_too_short_is_skipped_with_note(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    path = _tone(folder / "a_500Hz.wav", 500, seconds=2.0)
    out = tmp_path / "out"

    result = run_batch([path], [_trim(1.9999, 0.0), new_step("export_wav")], output_dir=out)
    assert result.ok_count == 1, result.summary()
    assert any("太短" in note for note in result.files[0].notes)
    audio = read_wav(next(out.glob("*_处理后.wav")))
    assert audio.duration == pytest.approx(2.0, abs=1e-3), "跳过裁切，保留整个文件"


def test_batch_dialog_fills_trim_from_selection(tmp_path):
    _app()
    dialog = BatchDialog(selection=lambda: (0.25, 0.75, 2.0), settings=_settings(tmp_path))
    dialog.steps = [new_step("trim")]
    dialog._refresh_list()
    dialog.step_list.setCurrentRow(0)

    assert dialog.fill_button.isEnabled() is True
    dialog.fill_button.click()
    assert dialog._widgets["start"].value() == pytest.approx(0.25)
    assert dialog._widgets["end"].value() == pytest.approx(0.75)
    dialog.close()


def test_batch_dialog_fill_button_disabled_without_selection(tmp_path):
    _app()
    dialog = BatchDialog(selection=lambda: None, settings=_settings(tmp_path))
    dialog.steps = [new_step("trim")]
    dialog._refresh_list()
    dialog.step_list.setCurrentRow(0)
    assert dialog.fill_button.isEnabled() is False
    dialog.close()


def test_batch_dialog_rejects_start_not_before_end(tmp_path):
    _app()
    dialog = BatchDialog(selection=lambda: (0.1, 0.2, 2.0), settings=_settings(tmp_path))
    dialog.steps = [_trim(0.5, 0.1)]
    assert dialog._trim_problem() is not None
    assert "起点必须小于终点" in dialog._trim_problem()

    dialog.steps = [_trim(0.5, 0.0)]      # 0 表示到文件末尾，合法
    assert dialog._trim_problem() is None

    dialog.steps = [_trim(-0.1, 0.5)]
    assert "不能为负" in dialog._trim_problem()
    dialog.close()


def test_main_window_selection_seconds(tmp_path):
    _app()
    window = MainWindow()
    assert window.selection_seconds() is None, "没打开音频时不给选区"
    window.load_audio(_tone(tmp_path / "a_500Hz.wav", 500, seconds=2.0))
    start, end, duration = window.selection_seconds()
    assert (start, end) == pytest.approx((0.0, 2.0)), "载入后选区默认覆盖整个文件"
    window.region.setRegion((0.25, 0.75))
    start, end, duration = window.selection_seconds()
    assert (start, end) == pytest.approx((0.25, 0.75))
    assert duration == pytest.approx(2.0, abs=1e-3)
    window.close()

