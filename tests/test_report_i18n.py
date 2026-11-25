"""报告语言：导出报告（TXT/HTML/CSV/图注）与界面语言解耦的回归测试。"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from core.envelope import compute_envelope, fit_envelope
from core.exporter import build_report_html
from core.report_i18n import (
    REPORT_AUTO, REPORT_EN, REPORT_ZH, analysis_scope_text, font_family,
    get_report_language, report_is_english, report_language, rt, rtf,
    set_report_language, suggest_report_suffix,
)
from core.spectral import fourier_analysis
from core.statistics import interval_statistics
from core.txt_export import TxtExportOptions, suggest_txt_path, write_analysis_txt

CJK = re.compile(r"[\u4e00-\u9fff]")


@pytest.fixture(autouse=True)
def _reset_language():
    set_report_language(REPORT_AUTO)
    yield
    set_report_language(REPORT_AUTO)


def _signal(seconds: float = 1.0, fs: int = 48000) -> tuple[np.ndarray, int]:
    t = np.arange(int(fs * seconds)) / fs
    x = 0.4 * np.sin(2 * np.pi * 1000 * t) + 0.1 * np.sin(2 * np.pi * 3000 * t)
    return x, fs


# ---------------------------------------------------------------- 状态与查表
def test_default_is_auto_and_follows_interface_language():
    assert get_report_language() == REPORT_AUTO
    assert isinstance(report_language(), str)
    assert report_language() in (REPORT_ZH, REPORT_EN)


def test_set_language_accepts_known_codes_and_rejects_others():
    set_report_language(REPORT_EN)
    assert get_report_language() == REPORT_EN
    assert report_is_english() is True
    set_report_language(REPORT_ZH)
    assert report_is_english() is False
    set_report_language("klingon")
    assert get_report_language() == REPORT_AUTO


def test_rt_falls_back_to_the_original_text():
    set_report_language(REPORT_EN)
    assert rt("傅里叶分析") == "Fourier analysis"
    assert rt("这条串没有译文") == "这条串没有译文"


def test_rtf_fills_placeholders_after_translation():
    set_report_language(REPORT_EN)
    text = rtf("正在写 {_v0}", _v0="坐标表")
    assert text.endswith("坐标表")
    assert "writing" in text.lower()


def test_font_family_follows_report_language():
    set_report_language(REPORT_EN)
    assert "Times" in font_family()
    set_report_language(REPORT_ZH)
    assert "SimSun" in font_family() or "宋" in font_family()


def test_suggest_report_suffix_switches_with_language():
    set_report_language(REPORT_EN)
    assert suggest_report_suffix(True) == "edited_analysis"
    set_report_language(REPORT_ZH)
    assert suggest_report_suffix(True) == "修改分析"


def test_analysis_scope_text_follows_language():
    x, fs = _signal()
    stats = interval_statistics(x, fs, 0.0, 1.0)
    set_report_language(REPORT_ZH)
    zh = analysis_scope_text(stats)
    assert "；" in zh and CJK.search(zh)
    set_report_language(REPORT_EN)
    en = analysis_scope_text(stats)
    assert ";" in en and not CJK.search(en)


# ---------------------------------------------------------------- 导出产物
def _txt(tmp_path: Path) -> str:
    x, fs = _signal()
    times, envelope = compute_envelope(x, fs)
    fit = fit_envelope(times, envelope, "auto")
    fourier = fourier_analysis(x, fs)
    target = tmp_path / "out.txt"
    write_analysis_txt(
        target,
        samples=x, sample_rate=fs, source_name="demo.wav", source_path="C:/demo.wav",
        subtype="PCM_24", size_mb=1.0, md5="ABCD1234", channels=1,
        fourier=fourier, envelope=envelope, envelope_times=times,
        envelope_span=(0.0, 1.0), fit=fit, options=TxtExportOptions(),
        fundamental=1000.0,
    )
    return target.read_text(encoding="utf-8-sig")


def _html() -> str:
    x, fs = _signal()
    times, envelope = compute_envelope(x, fs)
    fit = fit_envelope(times, envelope, "auto")
    return build_report_html(
        file_path="demo.wav", sample_rate=fs, channel=1,
        statistics=interval_statistics(x, fs, 0.0, 1.0),
        fourier=fourier_analysis(x, fs), samples=x,
        envelope=envelope, envelope_fit=fit,
    )


def test_english_txt_report_has_no_chinese(tmp_path):
    set_report_language(REPORT_EN)
    text = _txt(tmp_path)
    assert "Fourier analysis" in text
    assert not CJK.search(text)


def test_chinese_txt_report_stays_chinese(tmp_path):
    set_report_language(REPORT_ZH)
    text = _txt(tmp_path)
    assert "傅里叶分析" in text


def test_english_html_report_has_no_chinese():
    set_report_language(REPORT_EN)
    document = _html()
    assert 'lang="en' in document
    assert not CJK.search(document)


def test_chinese_html_report_stays_chinese():
    set_report_language(REPORT_ZH)
    document = _html()
    assert "区间统计" in document


def test_auto_language_writes_the_same_text_as_the_explicit_choice(tmp_path):
    set_report_language(REPORT_AUTO)
    automatic = _txt(tmp_path)
    set_report_language(report_language())
    explicit = _txt(tmp_path)
    assert automatic == explicit


# ---------------------------------------------------------------- 界面下拉
def test_report_language_combo_matches_the_code_order():
    from PySide6.QtWidgets import QApplication

    from app.main_window import REPORT_LANGUAGE_CODES, MainWindow

    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        combo = window.report_language_combo
        assert combo.count() == len(REPORT_LANGUAGE_CODES)
        for index, code in enumerate(REPORT_LANGUAGE_CODES):
            combo.blockSignals(True)
            combo.setCurrentIndex(index)
            combo.blockSignals(False)
            window._report_language_changed(index)
            assert get_report_language() == code
    finally:
        window.close()
        application.processEvents()
