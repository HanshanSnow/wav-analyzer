"""降噪工具组的测试：T1–T15（见 `PlanForVersion2.0.md` §3.3.9）。

原则：每条用例都用解析式或已知构造复算，而不是只断言「跑通」。
合成信号都不含任何实验指向元素，数值可重复（固定随机种子）。
"""

from __future__ import annotations

import numpy as np
import pytest

from core import anc
from core.batch import new_step, run_batch
from core.anc import (
    METHOD_IDS,
    combined_u,
    delta_phase_rad,
    delta_sys_db,
    detect_noise_segment,
    estimate_lag,
    erle_db,
    notch_gain_db,
    run_method,
    shift_signal,
    tone_amplitude,
    tsa_loss_db,
)

FS = 8000
ORDER = 128


def tone(frequency: float = 1000.0, seconds: float = 2.0, amplitude: float = 0.4,
         sample_rate: int = FS, start: float = 0.0) -> np.ndarray:
    t = np.arange(int(seconds * sample_rate)) / sample_rate + start
    return amplitude * np.sin(2.0 * np.pi * frequency * t)


def noise(seconds: float = 2.0, amplitude: float = 0.05, sample_rate: int = FS,
          seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return amplitude * rng.standard_normal(int(seconds * sample_rate))


def delayed(signal: np.ndarray, samples: int) -> np.ndarray:
    return np.concatenate([np.zeros(samples), signal[: signal.size - samples]])


def db_ratio(a: np.ndarray, b: np.ndarray) -> float:
    return float(20.0 * np.log10(np.sqrt(np.mean(a ** 2)) / np.sqrt(np.mean(b ** 2))))


# ---------------------------------------------------------------- T1
def test_t1_frozen_ls_removes_correlated_noise_and_keeps_amplitude():
    seconds = 2.4
    level = 0.05
    room = noise(seconds, level, seed=1)
    reference = delayed(room, 2)                       # 参考路：同一噪声、晚 0.25 ms
    signal = np.zeros_like(room)
    start = int(1.2 * FS)                              # 前 1.2 s 只有噪声
    signal[start:] = tone(1000.0, seconds - start / FS, 0.4)
    target = signal + room

    outcome = run_method("ls_frozen", target, reference, FS,
                         fundamental=1000.0, params={"order": ORDER})

    assert outcome.applied
    diag = outcome.diagnostics
    assert diag.erle_holdout_db >= anc.MIN_ERLE_HOLDOUT_DB
    assert abs(diag.delta_level_db) <= 0.2
    # 噪声段在开头，自动检测应落在信号出现之前。
    assert diag.noise_span is not None
    assert diag.noise_span[1] <= 1.2 + 1e-9
    # 纯噪声前缀上的实际抑制量至少 6 dB。
    prefix = slice(0, start)
    assert db_ratio(outcome.cleaned[prefix], target[prefix]) <= -6.0


# ---------------------------------------------------------------- T2
def test_t2_reference_carrying_the_signal_is_rejected():
    seconds = 2.0
    room = noise(seconds, 0.05, seed=2)
    signal = tone(1000.0, seconds, 0.4)
    target = signal + room
    reference = delayed(signal + room, 2)              # 两支通道都听得到激励

    outcome = run_method("ls_frozen", target, reference, FS,
                         fundamental=1000.0, params={"order": ORDER})

    assert not outcome.applied
    assert outcome.cleaned is None
    assert outcome.diagnostics.blocked
    assert ("相干" in outcome.diagnostics.blocked
            or "泄漏" in outcome.diagnostics.blocked)
    # 拒绝时仍要给出诊断值，供报告记录。
    assert outcome.diagnostics.erle_db is not None
    assert outcome.diagnostics.coherence_xd is not None


# ---------------------------------------------------------------- T3
def test_t3_uncorrelated_reference_is_rejected_as_useless():
    seconds = 2.0
    room = noise(seconds, 0.05, seed=3)
    signal = tone(1000.0, seconds, 0.4, start=0.6)
    target = signal + room
    reference = noise(seconds, 0.05, seed=99)          # 与 room 无关

    outcome = run_method("ls_frozen", target, reference, FS,
                         fundamental=1000.0, params={"order": ORDER})

    assert not outcome.applied
    assert outcome.diagnostics.blocked
    assert "ERLE" in outcome.diagnostics.blocked


# ---------------------------------------------------------------- T4
def test_t4_without_stationary_noise_segment_it_asks_for_a_selection():
    rng = np.random.default_rng(4)
    # ? 0.1 s ??????? 1 s ???????
    level = 0.002 + 0.4 * (rng.random(int(2.0 * FS)) > 0.99).astype(float)
    target = tone(1000.0, 2.0, 0.4) * level / 0.4
    reference = delayed(target, 2)

    outcome = run_method("ls_frozen", target, reference, FS,
                         fundamental=1000.0, params={"order": ORDER})

    assert not outcome.applied
    assert outcome.diagnostics.blocked
    assert "噪声段" in outcome.diagnostics.blocked


# ---------------------------------------------------------------- T5
def test_t5_requires_enough_samples_per_tap():
    seconds = 2.5
    room = noise(seconds, 0.05, seed=5)
    target = room.copy()
    reference = delayed(room, 2)

    outcome = run_method("ls_frozen", target, reference, FS,
                         params={"order": 2048})    # 9600 < 8 × 2048

    assert not outcome.applied
    assert "采样点" in outcome.diagnostics.blocked


# ---------------------------------------------------------------- T6
def test_t6_block_ls_tracks_slow_level_drift():
    seconds = 6.0
    rng = np.random.default_rng(6)
    room = 0.05 * rng.standard_normal(int(seconds * FS))
    # 每 2 s 噪声电平变化 ±3 dB（幅度乘 1.41 / 0.71）。
    gains = np.ones(room.size)
    for index, gain in enumerate((1.0, 1.41, 0.71)):
        begin = int(index * 2.0 * FS)
        gains[begin:begin + int(2.0 * FS)] = gain
    room = room * gains
    reference = delayed(room, 2)

    outcome = run_method("ls_block", room, reference, FS,
                         params={"order": ORDER, "block_seconds": 1.0})

    assert outcome.applied
    assert outcome.diagnostics.block_erle
    assert all(np.isfinite(value) for value in outcome.diagnostics.block_erle)
    assert outcome.diagnostics.erle_db >= 4.0


# ---------------------------------------------------------------- T7
def test_t7_long_and_short_blocks_agree_on_diagnostics():
    seconds = 4.0
    room = noise(seconds, 0.05, seed=7)
    reference = delayed(room, 2)
    # tone() 的 start 是相位偏移，不是时间偏移：这里显式把单音放到 1 s 之后。
    signal = np.concatenate([np.zeros(int(1.0 * FS)),
                             tone(1000.0, seconds - 1.0, 0.4)])
    target = signal + room

    short = run_method("ls_block", target, reference, FS, fundamental=1000.0,
                       params={"order": ORDER, "block_seconds": 0.5})
    long = run_method("ls_block", target, reference, FS, fundamental=1000.0,
                      params={"order": ORDER, "block_seconds": 60.0})

    assert short.applied and long.applied
    assert abs(short.diagnostics.delta_level_db
               - long.diagnostics.delta_level_db) <= 0.1


# ---------------------------------------------------------------- T8
def test_t8_sync_average_loss_matches_the_formula():
    sample_rate = 48000
    frequency = 1000.0
    period = 1.0 / frequency
    rng = np.random.default_rng(8)
    epochs = 12
    jitter = rng.normal(0.0, 100e-6, epochs)           # 触发抖动 100 µs
    template = (0.4 * np.sin(2.0 * np.pi * frequency * np.arange(48) / sample_rate)
                * np.exp(-np.arange(48) / sample_rate / 0.0003))
    signal = np.zeros(int((epochs + 2) * period * sample_rate) + 480)
    for index, offset in enumerate(jitter):
        begin = max(0, int(round((index * period + offset) * sample_rate)))
        signal[begin:begin + template.size] += template

    outcome = run_method("sync_avg", signal, None, sample_rate,
                         fundamental=frequency)

    diag = outcome.diagnostics
    assert diag.averages >= anc.MIN_AVERAGES
    expected = tsa_loss_db(frequency, 100e-6)
    assert expected == pytest.approx(-1.715, abs=0.01)
    # 触发抖动 → 子样本对齐会把它补回来，实测幅值损失必须远小于未对齐的解析式。
    assert abs(diag.delta_level_db) <= 0.5
    assert diag.delta_level_db > expected
    assert outcome.applied
    assert "实测幅值损失" in diag.notes[0]
    # 护栏本身：损失超过 0.5 dB 时必须给出带「抖动」的拒绝理由。
    guard = anc._guard(
        anc.Diagnostics(method="sync_avg", averages=8, delta_level_db=-1.715),
        "sync_avg",
    )
    assert guard is not None and "抖动" in guard


# ---------------------------------------------------------------- T9
def test_t9_notch_matches_the_analytic_gain():
    # 手册里的数值例子：50 Hz、Q=30 的陷波器在 55.45 Hz 处约 −0.1 dB。
    assert notch_gain_db(55.45, 50.0, 30.0) == pytest.approx(-0.1004, abs=5e-4)
    assert notch_gain_db(50.0, 50.0, 30.0) == -np.inf

    # 实测：偏离中心 5.45 Hz 的 1 kHz 单音，双向滤波（filtfilt）增益 = 2×解析式。
    analytic = notch_gain_db(1005.45, 1000.0, 30.0)
    signal = tone(1005.45, 1.0, 0.4, sample_rate=48000)
    outcome = run_method("notch", signal, None, 48000, fundamental=1005.45,
                         params={"frequency": 1000.0, "q": 30.0, "harmonics": 1})

    assert outcome.diagnostics.delta_level_db == pytest.approx(2.0 * analytic, abs=0.2)
    # 主频被削掉近 19 dB，远超 0.5 dB 护栏 → 必须拒绝而不是悄悄给出结果。
    assert not outcome.applied
    assert "陷波" in outcome.diagnostics.blocked


def test_t9b_notch_leaves_far_tones_almost_untouched():
    signal = tone(2000.0, 1.0, 0.4, sample_rate=48000)
    outcome = run_method("notch", signal, None, 48000, fundamental=2000.0,
                         params={"frequency": 1000.0, "q": 30.0, "harmonics": 1})
    assert outcome.applied
    assert abs(outcome.diagnostics.delta_level_db) <= 0.01


# ---------------------------------------------------------------- T10
def test_t10_wiener_clean_refuses_a_reference_that_hears_the_signal():
    seconds = 2.0
    room = noise(seconds, 0.05, seed=10)
    signal = tone(1000.0, seconds, 0.4)
    target = signal + room
    reference = delayed(signal + room, 2)

    outcome = run_method("wiener_clean", target, reference, FS, fundamental=1000.0,
                         params={"order": ORDER})

    assert not outcome.applied
    assert "参考路" in outcome.diagnostics.blocked


def test_t10b_wiener_clean_accepts_a_genuinely_clean_reference():
    seconds = 2.0
    room = noise(seconds, 0.05, seed=11)
    reference = delayed(room, 2)
    signal = np.zeros_like(room)
    signal[int(0.6 * FS):] = tone(1000.0, seconds - 0.6, 0.4)
    target = signal + room

    outcome = run_method("wiener_clean", target, reference, FS, fundamental=1000.0,
                         params={"order": ORDER})

    assert outcome.applied
    assert abs(outcome.diagnostics.delta_level_db) <= 0.5


# ---------------------------------------------------------------- T11
def test_t11_wiener_spectral_keeps_the_time_origin():
    seconds = 2.0
    room = noise(seconds, 0.05, seed=12)
    reference = delayed(room, 2)
    pulse = np.zeros_like(room)
    pulse[int(0.7 * FS)] = 0.5
    target = pulse + room

    outcome = run_method("wiener_spectral", target, reference, FS, params={"nperseg": 512})

    assert outcome.applied
    original_lag = estimate_lag(target, pulse, FS)
    cleaned_lag = estimate_lag(outcome.cleaned, pulse, FS)
    assert abs(cleaned_lag - original_lag) < 1e-3


# ---------------------------------------------------------------- T14
def test_t14_formulas_match_the_handbook():
    leak = 0.05
    assert delta_sys_db(leak) == pytest.approx(10.0 * np.log10(1.0 - leak), rel=1e-12)
    assert delta_phase_rad(leak) == pytest.approx(np.arcsin(np.sqrt(leak)), rel=1e-12)
    u_random = 20.0 * np.log10(1.0 + 1.0 / np.sqrt(16.0))
    assert combined_u(delta_sys_db(leak), 16) == pytest.approx(
        np.sqrt(delta_sys_db(leak) ** 2 + u_random ** 2), rel=1e-12)
    assert combined_u(None, 0) is None
    # 0.5 dB 偏差 ⇔ γ² ≤ 0.109（手册第 5 条的推导）。
    assert delta_sys_db(0.109) == pytest.approx(-0.5013, abs=1e-3)


# ---------------------------------------------------------------- T15
@pytest.mark.parametrize("method", METHOD_IDS)
def test_t15_degenerate_inputs_are_reported_not_crashing(method):
    empty = np.zeros(0)
    outcome = run_method(method, empty, empty if method != "sync_avg" else None, FS)
    assert not outcome.applied
    assert outcome.diagnostics.blocked

    zeros = np.zeros(FS)
    outcome = run_method(method, zeros, zeros if method != "sync_avg" else None, FS,
                         params={"order": 32})
    assert not outcome.applied
    assert outcome.diagnostics.blocked


def test_t15b_unknown_method_and_missing_reference():
    outcome = run_method("nope", np.zeros(100), None, FS)
    assert "未知" in outcome.diagnostics.blocked

    outcome = run_method("ls_frozen", np.full(200, 0.1), None, FS)
    assert "参考通道" in outcome.diagnostics.blocked


def test_t15c_clipped_input_stays_finite():
    seconds = 1.0
    room = noise(seconds, 0.05, seed=15)
    signal = np.clip(tone(1000.0, seconds, 1.4), -1.0, 1.0)
    target = signal + room
    reference = delayed(room, 2)

    outcome = run_method("ls_frozen", target, reference, FS, fundamental=1000.0,
                         params={"order": 64})

    assert outcome.cleaned is not None or outcome.diagnostics.blocked
    if outcome.cleaned is not None:
        assert np.all(np.isfinite(outcome.cleaned))


# ---------------------------------------------------------------- 工具函数
def test_detect_noise_segment_finds_the_quiet_prefix():
    room = noise(2.0, 0.05, seed=16)
    signal = np.zeros_like(room)
    signal[int(1.0 * FS):] = tone(1000.0, 1.0, 0.4)
    span = detect_noise_segment(signal + room, FS)
    assert span is not None
    assert span[1] - span[0] == FS
    assert span[1] <= 2.0 * FS


def test_detect_noise_segment_rejects_bursty_input():
    rng = np.random.default_rng(17)
    ramp = noise(2.0, 0.05, seed=17) * np.linspace(0.0, 1.0, int(2.0 * FS))
    assert detect_noise_segment(ramp, FS) is None


def test_tone_amplitude_recovers_the_constructed_value():
    signal = tone(997.3, 1.0, 0.4)
    assert tone_amplitude(signal, FS, 997.3) == pytest.approx(0.4, rel=1e-3)


def test_estimate_lag_and_shift_signal_agree():
    room = noise(0.5, 1.0, seed=18)
    lag_samples = 3
    # ??????????????? m ?????
    measured = estimate_lag(delayed(room, lag_samples), room, FS)
    assert measured * FS == pytest.approx(lag_samples, abs=1.0)
    shifted = shift_signal(room, lag_samples)
    assert np.allclose(shifted[lag_samples:], room[:-lag_samples])
    assert np.all(shifted[:lag_samples] == 0)


def test_erle_is_zero_for_identical_signals():
    signal = tone(500.0, 0.5, 0.3)
    assert erle_db(signal, signal) == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------- 批量步骤
def _stereo_fixture(path, seconds: float = 2.0, seed: int = 21):
    """目标声道 = 噪声 + 1 s 后开始的单音；参考声道 = 同一噪声晚 2 个采样点。"""
    rng = np.random.default_rng(seed)
    room = 0.05 * rng.standard_normal(int(seconds * FS))
    reference = np.concatenate([np.zeros(2), room[:-2]])
    target = room.copy()
    begin = int(1.0 * FS)
    target[begin:] += 0.4 * np.sin(2.0 * np.pi * 1000.0 * np.arange(target.size - begin) / FS)
    from core.audio_io import write_wav
    write_wav(path, np.stack([target, reference], axis=1), FS, subtype="PCM_24")
    return path


def _anc_steps(**params):
    step = new_step("denoise_tools")
    step["params"].update({"method": "ls_frozen", "order": 128,
                           "segment_start": 0.0, "segment_end": 0.5})
    step["params"].update(params)
    return [step, new_step("export_wav"), new_step("export_csv")]


def test_t12_batch_applies_frozen_ls_and_writes_marker_columns(tmp_path):
    source = _stereo_fixture(tmp_path / "stereo.wav")
    out = tmp_path / "out"
    result = run_batch([source], _anc_steps(), output_dir=out)

    assert result.ok_count == 1, result.summary()
    notes = "\n".join(result.files[0].notes)
    assert "ERLE" in notes and "不确定度" in notes

    rows = result.files[0].rows
    assert rows["denoise_method"].startswith("冻结两段式")
    assert rows["denoise_applied"] is True
    # 全段含单音，全段 ERLE 会被单音稀释；判断抵消量看留出段那个数。
    assert rows["denoise_holdout_erle_db"] > 6.0
    assert rows["denoise_blocked"] == ""

    header = (out / "批量统计.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert "denoise_method" in header and "denoise_erle_db" in header


def test_t13_batch_skips_reference_method_on_single_channel(tmp_path):
    mono = tmp_path / "mono.wav"
    from core.audio_io import write_wav
    write_wav(mono, 0.4 * np.sin(2.0 * np.pi * 1000.0 * np.arange(2 * FS) / FS), FS,
              subtype="PCM_24")
    out = tmp_path / "out"
    result = run_batch([mono], _anc_steps(), output_dir=out)

    assert result.ok_count == 1, "单声道缺参考通道只该跳过这一步，不该判整份失败"
    notes = "\n".join(result.files[0].notes)
    assert "需要第二个声道" in notes
    assert result.files[0].rows["denoise_applied"] is False
    assert "需要第二个声道" in result.files[0].rows["denoise_blocked"]
    assert (out / "mono_处理后.wav").exists(), "跳过降噪后仍要继续导出"


def test_t13b_batch_records_a_blocked_reason_instead_of_failing(tmp_path):
    # 参考声道与噪声无关 → 留出段 ERLE 达不到 6 dB，护栏拒绝。
    rng = np.random.default_rng(22)
    room = 0.05 * rng.standard_normal(2 * FS)
    target = room.copy()
    target[int(1.0 * FS):] += tone(1000.0, 1.0, 0.4)
    dependent = 0.05 * rng.standard_normal(2 * FS)
    source = tmp_path / "unrelated.wav"
    from core.audio_io import write_wav
    write_wav(source, np.stack([target, dependent], axis=1), FS, subtype="PCM_24")
    out = tmp_path / "out"
    result = run_batch([source], _anc_steps(), output_dir=out)

    assert result.ok_count == 1
    row = result.files[0].rows
    assert row["denoise_applied"] is False
    assert "ERLE" in row["denoise_blocked"]
    assert (out / "unrelated_处理后.wav").exists()


# ---------------------------------------------------------------- 界面
def _qt():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_dialog_shows_only_the_parameters_that_matter(tmp_path):
    _qt()
    from PySide6.QtCore import QSettings

    from app.anc_dialog import AncToolsDialog

    dialog = AncToolsDialog(None, channels=2, selection=(0.1, 0.4, 2.0),
                            settings=QSettings(str(tmp_path / "prefs.ini"),
                                               QSettings.IniFormat))
    assert dialog.current_method() == "ls_frozen"
    assert dialog.order_spin.isEnabled()
    assert not dialog.notch_spin.isEnabled()

    dialog.method_combo.setCurrentIndex(dialog.method_combo.findData("notch"))
    assert dialog.notch_spin.isEnabled() and dialog.q_spin.isEnabled()
    assert not dialog.order_spin.isEnabled(), "陷波不需要滤波器阶数"
    assert not dialog.auto_check.isEnabled(), "陷波不需要噪声段"

    dialog.method_combo.setCurrentIndex(dialog.method_combo.findData("ls_block"))
    assert dialog.block_spin.isEnabled() and dialog.order_spin.isEnabled()
    assert dialog.auto_check.isChecked()
    assert not dialog.start_spin.isEnabled(), "自动检测时不该让人手填区间"
    dialog.auto_check.setChecked(False)
    dialog.start_spin.setValue(0.25)
    dialog.end_spin.setValue(0.75)
    spec = dialog.params()
    assert spec["method"] == "ls_block"
    assert spec["segment"] == (0.25, 0.75)
    assert spec["options"]["order"] == anc.DEFAULT_ORDER
    dialog.close()


def test_dialog_warns_when_the_file_has_no_reference_channel(tmp_path):
    _qt()
    from PySide6.QtCore import QSettings

    from app.anc_dialog import AncToolsDialog

    dialog = AncToolsDialog(None, channels=1,
                            settings=QSettings(str(tmp_path / "prefs.ini"),
                                               QSettings.IniFormat))
    assert "只有 1 个声道" in dialog.premise_label.text()
    dialog.method_combo.setCurrentIndex(dialog.method_combo.findData("sync_avg"))
    assert "不需要参考通道" in dialog.premise_label.text()
    dialog.close()


def test_main_window_applies_and_undoes_the_tool_group(tmp_path):
    _qt()
    from app.main_window import MainWindow

    source = _stereo_fixture(tmp_path / "stereo.wav")
    window = MainWindow()
    window.load_audio(source)
    before = window.processed.copy()

    window.apply_anc_tools({"method": "ls_frozen", "segment": None,
                            "options": {"order": 128}})

    assert window.edit_log[-1] == "denoise_tools"
    assert not np.array_equal(window.processed[:, 0], before[:, 0])
    assert np.array_equal(window.processed[:, 1], before[:, 1]), "参考声道不该被改写"
    assert "留出段 ERLE" in window.denoise_label.text()

    window.undo()
    assert np.allclose(window.processed, before)
    window.close()


def test_main_window_refuses_when_the_guard_blocks(tmp_path, monkeypatch):
    _qt()
    from PySide6.QtWidgets import QMessageBox

    from app.main_window import MainWindow

    rng = np.random.default_rng(31)
    room = 0.05 * rng.standard_normal(2 * FS)
    target = room.copy()
    target[int(1.0 * FS):] += tone(1000.0, 1.0, 0.4)
    unrelated = 0.05 * rng.standard_normal(2 * FS)
    from core.audio_io import write_wav
    source = tmp_path / "unrelated.wav"
    write_wav(source, np.stack([target, unrelated], axis=1), FS, subtype="PCM_24")

    seen: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda _parent, _title, text, *a, **k: seen.append(text))

    window = MainWindow()
    window.load_audio(source)
    before = window.processed.copy()
    window.apply_anc_tools({"method": "ls_frozen", "segment": None,
                            "options": {"order": 128}})

    assert seen and "ERLE" in seen[0]
    assert window.edit_log == [], "被护栏拒绝时不准留下撤销记录"
    assert np.array_equal(window.processed, before)
    assert "未应用" in window.denoise_label.text()
    window.close()



