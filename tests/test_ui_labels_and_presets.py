"""界面文案与设置预设测试：统计量中文释义、关闭去噪预览、厂商预设。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QComboBox

from app.settings_dialog import CUSTOM_VENDOR, VENDOR_PRESETS, AISettingsDialog
from core.audio_io import write_wav
from core.statistics import STATISTIC_FIELDS, interval_statistics, statistics_rows

FS = 8000


def _app():
    return QApplication.instance() or QApplication([])


def test_every_statistic_key_has_chinese_label_and_note():
    t = np.arange(FS) / FS
    stats = interval_statistics(0.4 * np.sin(2 * np.pi * 300 * t), FS)
    rows = statistics_rows(stats)
    assert [row[0] for row in rows] == list(stats.keys()), "行顺序需与统计结果一致"
    for key, label, _value, note in rows:
        assert label != key, f"{key} 缺少中文名"
        assert note, f"{key} 缺少释义"
        assert any("\u4e00" <= ch <= "\u9fff" for ch in label)


def test_statistic_field_table_is_unique_and_complete():
    keys = [key for key, _, _ in STATISTIC_FIELDS]
    assert len(keys) == len(set(keys))
    t = np.arange(FS) / FS
    produced = set(interval_statistics(0.4 * np.sin(2 * np.pi * 300 * t), FS).keys())
    assert produced.issubset(set(keys)), f"未登记的统计量：{produced - set(keys)}"


def test_statistics_table_shows_three_columns_with_chinese_names(tmp_path):
    _app()
    from app.main_window import MainWindow

    path = tmp_path / "tone.wav"
    t = np.arange(FS) / FS
    write_wav(path, 0.4 * np.sin(2 * np.pi * 300 * t), FS, subtype="PCM_16")
    window = MainWindow()
    window.load_audio(path)

    table = window.stats_table
    assert table.columnCount() == 3
    labels = [table.item(row, 0).text() for row in range(table.rowCount())]
    assert "有效值 RMS (FS)" in labels
    notes = [table.item(row, 2).text() for row in range(table.rowCount())]
    assert any("dB SPL" in note for note in notes), "需说明 dBFS 不是声压级"
    # 口径说明整句放在释义列，避免挤在窄的数值列
    scope_row = [r for r in range(table.rowCount())
                 if table.item(r, 0).text().startswith("计算口径")][0]
    assert table.item(scope_row, 1).text() == "—"
    assert "RMS" in table.item(scope_row, 2).text()
    window.deleteLater()
    _app().processEvents()


def test_close_preview_clears_pending_result(tmp_path):
    _app()
    from app.main_window import MainWindow

    path = tmp_path / "spike.wav"
    t = np.arange(FS) / FS
    x = 0.4 * np.sin(2 * np.pi * 300 * t)
    x[1000] += 0.9
    write_wav(path, x, FS, subtype="PCM_16")
    window = MainWindow()
    window.load_audio(path)

    window.preview_denoise()
    assert window.pending_denoise is not None
    assert window.apply_button.isEnabled()
    assert window.close_preview_button.isEnabled()

    before = window.processed.copy()
    window.close_denoise_preview()
    assert window.pending_denoise is None
    assert not window.apply_button.isEnabled()
    assert not window.close_preview_button.isEnabled()
    assert not window._preview_active(), "关闭预览后橙色曲线应被清除"
    assert np.array_equal(window.processed, before), "关闭预览不得改动数据"
    assert window.edit_depth == 0
    window.deleteLater()
    _app().processEvents()


def test_settings_dialog_presets_and_custom():
    _app()
    dialog = AISettingsDialog()

    deepseek = "DeepSeek（深度求索）"
    # 先切到“自定义”再切回来：本机 QSettings 里可能存着用户自填的模型名，
    # 直接 setCurrentText 同名项不会触发切换信号，断言就会被本机状态污染。
    dialog.vendor.setCurrentText(CUSTOM_VENDOR)
    dialog.vendor.setCurrentText(deepseek)
    preset = VENDOR_PRESETS[deepseek]
    assert dialog.base_url.text() == preset["base_url"]
    assert dialog.base_url.isReadOnly(), "预设厂商的 Base URL 不应让用户手改"
    assert isinstance(dialog.model, QComboBox) and dialog.model.isEditable()
    assert dialog.model.currentText() == preset["models"][0]
    assert preset["key_hint"] in dialog.key_hint.text()

    moonshot = "Moonshot（月之暗面 Kimi）"
    dialog.vendor.setCurrentText(moonshot)
    assert dialog.base_url.text() == VENDOR_PRESETS[moonshot]["base_url"]
    assert dialog.model.currentText() == VENDOR_PRESETS[moonshot]["models"][0]

    dialog.vendor.setCurrentText(CUSTOM_VENDOR)
    assert not dialog.base_url.isReadOnly(), "自定义模式必须允许自填 Base URL"
    dialog.base_url.setText("http://127.0.0.1:8000/v1")
    dialog.model.setCurrentText("my-local-model")
    dialog.api_key.setText("sk-test")
    settings = dialog.settings()
    assert settings.base_url == "http://127.0.0.1:8000/v1"
    assert settings.model == "my-local-model"
    dialog.deleteLater()
    _app().processEvents()


def test_settings_dialog_accept_requires_base_url_and_model():
    _app()
    from PySide6.QtWidgets import QMessageBox

    dialog = AISettingsDialog()
    original = QMessageBox.warning
    seen = []
    QMessageBox.warning = lambda *args, **kwargs: seen.append(args[2] if len(args) > 2 else "")
    try:
        dialog.vendor.setCurrentText(CUSTOM_VENDOR)
        dialog.base_url.setText("")
        dialog.accept()
        assert seen, "Base URL 为空时应拦截保存"
    finally:
        QMessageBox.warning = original
        dialog.deleteLater()
        _app().processEvents()
