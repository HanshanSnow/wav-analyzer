"""声学校准：换算公式、统计接入、批量导出与对话框。"""

from __future__ import annotations

import math

import numpy as np
import pytest

from core.calibration import (
    MODE_PARAMS, MODE_REFERENCE, Calibration, dumps_profiles, find_profile, loads_profiles,
)
from core.statistics import attach_calibration, interval_statistics, statistics_rows

FS = 48000


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _tone(amplitude: float, frequency: float = 1000.0, seconds: float = 1.0) -> np.ndarray:
    t = np.arange(int(FS * seconds)) / FS
    return amplitude * np.sin(2 * np.pi * frequency * t)


@pytest.fixture
def ten_mv() -> Calibration:
    """10 mV/Pa、无前置增益、满幅 1 Vrms —— 教科书式的驻极体话筒参数。"""
    return Calibration(name="10mV 麦", sensitivity_mv_pa=10.0, preamp_gain_db=0.0,
                       adc_full_scale_vrms=1.0)


# ---------------------------------------------------------------- 公式
def test_offset_from_parameters(ten_mv: Calibration) -> None:
    # K = 20lg(1 · 1000 / (1 · 10 · 20e-6)) = 20lg(5e6) = 133.9794
    assert ten_mv.offset_db() == pytest.approx(133.9794, abs=1e-3)


def test_94_db_spl_maps_to_expected_dbfs(ten_mv: Calibration) -> None:
    """94 dB SPL = 1 Pa，麦克风出 10 mV，相对 1 Vrms 即 −40 dBFS。"""
    assert ten_mv.dbfs(94.0) == pytest.approx(-40.0, abs=0.03)
    assert ten_mv.spl(-40.0) == pytest.approx(94.0, abs=0.03)


def test_preamp_gain_shifts_offset_by_itself(ten_mv: Calibration) -> None:
    boosted = Calibration(name="+20dB", sensitivity_mv_pa=10.0, preamp_gain_db=20.0,
                          adc_full_scale_vrms=1.0)
    # 前置放大 20 dB，同一个声压录到的 dBFS 高 20，因此 K 小 20
    assert boosted.offset_db() == pytest.approx(ten_mv.offset_db() - 20.0, abs=1e-9)


def test_reference_mode_matches_parameter_mode(ten_mv: Calibration) -> None:
    ref = Calibration(name="校准器", mode=MODE_REFERENCE, ref_spl_db=94.0,
                      ref_dbfs=ten_mv.dbfs(94.0))
    assert ref.offset_db() == pytest.approx(ten_mv.offset_db(), abs=1e-9)


def test_spl_and_dbfs_are_inverse(ten_mv: Calibration) -> None:
    for spl in (-10.0, 40.0, 74.0, 120.0):
        assert ten_mv.spl(ten_mv.dbfs(spl)) == pytest.approx(spl, abs=1e-9)


def test_incomplete_parameters_give_none() -> None:
    assert Calibration(name="空").offset_db() is None
    assert Calibration(name="空").ready is False
    assert Calibration(name="标定缺一半", mode=MODE_REFERENCE, ref_spl_db=94.0).ready is False
    with pytest.raises(ValueError):
        Calibration(name="空").spl(-40.0)


def test_validate_rejects_wrong_values() -> None:
    with pytest.raises(ValueError):
        Calibration(name="").validate()
    with pytest.raises(ValueError):
        Calibration(name="x", sensitivity_mv_pa=0.0).validate()
    with pytest.raises(ValueError):
        Calibration(name="x", sensitivity_mv_pa=10.0, adc_full_scale_vrms=0.0).validate()
    with pytest.raises(ValueError):
        Calibration(name="x", mode=MODE_REFERENCE, ref_spl_db=94.0, ref_dbfs=5.0).validate()


def test_caveats_mention_agc() -> None:
    notes = Calibration(name="x", sensitivity_mv_pa=10.0).caveats()
    assert any("AGC" in item for item in notes)


# ---------------------------------------------------------------- 序列化
def test_profiles_roundtrip(ten_mv: Calibration) -> None:
    payload = dumps_profiles([ten_mv], active=ten_mv.name)
    profiles, active = loads_profiles(payload)
    assert active == ten_mv.name
    assert len(profiles) == 1
    assert profiles[0].sensitivity_mv_pa == 10.0
    assert profiles[0].offset_db() == pytest.approx(ten_mv.offset_db())
    assert find_profile(profiles, ten_mv.name) is not None
    assert find_profile(profiles, "不存在") is None


def test_broken_json_is_tolerated() -> None:
    assert loads_profiles("") == ([], "")
    assert loads_profiles("{ not json") == ([], "")
    assert loads_profiles('{"profiles": "nope"}') == ([], "")


# ---------------------------------------------------------------- 统计接入
def test_statistics_gain_spl_fields_only_when_calibrated(ten_mv: Calibration) -> None:
    x = _tone(10 ** (-40 / 20))          # 峰值 −40 dBFS
    plain = interval_statistics(x, FS, 0.0, 1.0, None, 1000.0)
    assert "rms_spl" not in plain and "peak_spl" not in plain

    stats = interval_statistics(x, FS, 0.0, 1.0, None, 1000.0, calibration=ten_mv)
    assert stats["peak_spl"] == pytest.approx(94.0, abs=0.05)
    assert stats["rms_spl"] == pytest.approx(94.0 - 3.01, abs=0.05)
    assert stats["calibration_offset_db"] == pytest.approx(ten_mv.offset_db())
    assert stats["calibration_name"] == "10mV 麦"


def test_spl_rows_sit_next_to_their_dbfs_rows(ten_mv: Calibration) -> None:
    keys = list(interval_statistics(_tone(0.3), FS, 0.0, 1.0, None, 1000.0, calibration=ten_mv))
    assert keys.index("peak_spl") == keys.index("peak_amplitude") + 1
    assert keys.index("rms_spl") == keys.index("rms_dbfs") + 1
    assert keys[-2:] == ["calibration_offset_db", "calibration_name"]


def test_attach_calibration_is_idempotent_and_reversible(ten_mv: Calibration) -> None:
    base = interval_statistics(_tone(0.3), FS, 0.0, 1.0, None, 1000.0)
    once = attach_calibration(base, ten_mv)
    twice = attach_calibration(once, ten_mv)
    assert list(twice) == list(once)
    assert twice["rms_spl"] == once["rms_spl"]

    cleared = attach_calibration(once, None)
    assert list(cleared) == list(base)
    assert "rms_spl" not in cleared


def test_switching_calibration_updates_values_without_recompute(ten_mv: Calibration) -> None:
    base = interval_statistics(_tone(0.3), FS, 0.0, 1.0, None, 1000.0)
    loud = attach_calibration(base, ten_mv)
    quiet = attach_calibration(loud, Calibration(name="低灵敏", sensitivity_mv_pa=20.0))
    assert quiet["rms_dbfs"] == pytest.approx(loud["rms_dbfs"])
    # 灵敏度翻倍意味着同一电压对应一半声压，K 小 6.02 dB，声压级整体低 6.02
    assert loud["rms_spl"] - quiet["rms_spl"] == pytest.approx(20 * math.log10(2.0), abs=1e-6)


def test_statistics_rows_expose_spl_labels(ten_mv: Calibration) -> None:
    stats = interval_statistics(_tone(0.3), FS, 0.0, 1.0, None, 1000.0, calibration=ten_mv)
    labels = {key: label for key, label, _value, _note in statistics_rows(stats)}
    assert "dB SPL" in labels["rms_spl"]
    assert labels["calibration_offset_db"].startswith("校准偏移")


# ---------------------------------------------------------------- 导出
def test_batch_csv_carries_spl_columns(tmp_path, ten_mv: Calibration) -> None:
    import csv
    import shutil

    from core.batch import new_step, run_batch

    source = tmp_path / "测点_1000Hz_D10_r1.wav"
    shutil.copy("demo/demo_tone.wav", source)
    steps = [new_step("stats"), new_step("export_csv")]
    steps[0]["params"].update({"region": "trim", "head": 0.1, "tail": 0.1, "fundamental": "name"})
    steps[1]["params"].update({"aggregate": "single"})
    result = run_batch([source], steps, output_dir=tmp_path / "out", calibration=ten_mv)
    assert result.fail_count == 0

    table = next((tmp_path / "out").glob("*.csv"))
    row = next(csv.DictReader(table.open(encoding="utf-8-sig")))
    offset = float(row["calibration_offset_db"])
    assert offset == pytest.approx(ten_mv.offset_db())
    expected = 20 * math.log10(float(row["peak_amplitude"])) + offset
    assert float(row["peak_spl"]) == pytest.approx(expected, abs=1e-6)
    assert "rms_spl" in row


def test_txt_header_states_calibration(tmp_path, ten_mv: Calibration) -> None:
    from core.batch import new_step, run_batch
    import shutil

    source = tmp_path / "测点_1000Hz_D10_r1.wav"
    shutil.copy("demo/demo_tone.wav", source)
    steps = [new_step("stats"), new_step("export_txt")]
    steps[0]["params"].update({"region": "trim", "head": 0.1, "tail": 0.1, "fundamental": "name"})
    steps[1]["params"].update({"aggregate": "single", "sections": ["stats"]})
    run_batch([source], steps, output_dir=tmp_path / "out", calibration=ten_mv)

    text = next((tmp_path / "out").glob("*.txt")).read_text(encoding="utf-8-sig")
    assert "声学校准：10mV 麦" in text
    assert "K = +133.98 dB" in text
    assert "等效声压级" in text
    assert "AGC" in text


# ---------------------------------------------------------------- 对话框
def test_dialog_switches_mode_and_reports_offset() -> None:
    from app.calibration_dialog import CalibrationDialog

    _app()
    _app()
    dialog = CalibrationDialog(None, profiles=[Calibration(name="默认校准")], active="默认校准",
                               current_dbfs=-35.5)
    dialog.sensitivity.setValue(10.0)
    dialog.full_scale.setValue(1.0)
    assert dialog.selected() is not None
    assert dialog.selected().offset_db() == pytest.approx(133.9794, abs=1e-3)

    dialog.mode.setCurrentIndex(dialog.mode.findData(MODE_REFERENCE))
    assert dialog.sensitivity.isVisibleTo(dialog) is False
    assert dialog.ref_spl.isVisibleTo(dialog) is True

    dialog.ref_spl.setValue(94.0)
    dialog._grab_dbfs()
    assert dialog.ref_dbfs.value() == pytest.approx(-35.5)
    assert dialog.selected().offset_db() == pytest.approx(94.0 + 35.5)

    dialog._accept()
    dialog._accept()
    payload = dialog.result_payload()
    assert payload["active"] == "默认校准"
    assert payload["profiles"][0].mode == MODE_REFERENCE
    dialog.close()


def test_dialog_falls_back_to_default_name_and_bounds() -> None:
    """控件范围与 validate 保持一致，所以正常操作不会撞上校验错误。"""
    from app.calibration_dialog import CalibrationDialog

    _app()
    dialog = CalibrationDialog(None)
    dialog.name.setText("   ")
    assert dialog._collect().name == "未命名校准"

    # 边界值本身合法：0.1 mV/Pa、100 Vrms 之外才会被控件夹住
    dialog.sensitivity.setValue(0.1)
    dialog.full_scale.setValue(20.0)
    assert dialog._collect().ready is True
    assert dialog.selected() is not None
    dialog.close()


def test_window_applies_calibration_to_loaded_audio(ten_mv: Calibration) -> None:
    from app.main_window import MainWindow

    _app()
    _app()
    window = MainWindow()
    window.calibration_profiles = [ten_mv]
    window.calibration_active = ten_mv.name
    window._refresh_calibration_ui()
    assert window._current_calibration().name == ten_mv.name

    window.load_audio("demo/demo_tone.wav")
    assert "rms_spl" in window.statistics
    rows_before = window.stats_table.rowCount()

    window.calibration_combo.setCurrentIndex(0)      # 切回未校准
    assert "rms_spl" not in window.statistics
    assert window.stats_table.rowCount() == rows_before - 4
    window.close()
