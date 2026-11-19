"""分析 TXT 导出的回归测试：段落顺序、全文无制表符、列严格对齐、取法与范围选项。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from core.envelope import compute_envelope, fit_envelope
from core.spectral import fourier_analysis
from core.txt_export import (
    SECTION_ORDER, TxtExportOptions, _table, suggest_txt_path, write_analysis_txt,
)


def _signal(seconds: float = 2.0, fs: int = 48000) -> tuple[np.ndarray, int]:
    t = np.arange(int(fs * seconds)) / fs
    x = 0.4 * np.sin(2 * np.pi * 1000 * t) + 0.05 * np.sin(2 * np.pi * 3000 * t)
    x += 0.003 * np.random.default_rng(1).standard_normal(t.size)
    return x, fs


def _export(tmp_path: Path, **overrides) -> tuple[Path, dict]:
    x, fs = _signal()
    seg = x[fs // 2: fs // 2 + fs]
    times, envelope = compute_envelope(seg, fs)
    fit = fit_envelope(times, envelope, "auto")
    payload = dict(
        samples=x, sample_rate=fs, source_name="demo.wav", source_path="C:/demo.wav",
        subtype="PCM_16", size_mb=1.0, md5="ABCD1234", channels=1,
        fourier=fourier_analysis(seg, fs),
        envelope=envelope, envelope_times=times + 0.5, envelope_span=(0.5, 1.5),
        fit=fit, options=TxtExportOptions(), fundamental=1000.0,
    )
    payload.update(overrides)
    target = tmp_path / "out.txt"
    info = write_analysis_txt(target, **payload)
    return target, info


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8-sig").splitlines()


# ---------------------------------------------------------------- 排版


def test_table_rejects_chinese_in_non_final_column():
    with pytest.raises(ValueError):
        _table([["idx", "统计量", "unit"], ["1", "有效值", "FS"]], aligns="<<<")


def test_table_keeps_last_column_at_same_offset():
    rows = [
        ["idx", "key", "value", "name"],
        ["1", "start_s", "0", "有效起点 (s)"],
        ["10", "excluded_samples", "-12.5", "排除点数"],
    ]
    lines = _table(rows, aligns="<<><")
    starts = {len(line) - len(cell) for line, cell in zip(lines, [row[-1] for row in rows])}
    assert len(starts) == 1, "末列起始位置必须逐行一致"

    # 数值列右对齐：各行数值字段的右端必须落在同一列边界。
    ends = {line.index(cell) + len(cell)
            for line, cell in zip(lines[1:], [row[2] for row in rows[1:]])}
    assert len(ends) == 1


def test_export_has_no_tabs(tmp_path):
    path, _ = _export(tmp_path)
    text = path.read_text(encoding="utf-8-sig")
    assert "\t" not in text, "全文不允许出现制表符：Tab 只能跳 8 的整数倍，长字段会把后续列顶歪"


def test_non_comment_rows_keep_ascii_before_last_column(tmp_path):
    """除末列外不得出现非 ASCII 字符——中文宽度随字体变化，会破坏对齐。"""
    path, _ = _export(tmp_path)
    for line in _lines(path):
        if not line or line.startswith("#") or line.startswith("=") or line.startswith("["):
            continue
        if not (line[0].isascii() and line[0].isalnum()):
            # 纯标题行（章节名、统计量释义）不含表格列，跳过
            continue
        if "  " not in line:
            continue
        head = line.split("   ")[0].rstrip()
        assert all(ord(ch) < 128 for ch in head), f"非末列出现中文：{line!r}"


# ---------------------------------------------------------------- 结构与顺序


def test_section_order_puts_long_tables_last(tmp_path):
    path, info = _export(tmp_path)
    labels = [label for _, label in SECTION_ORDER]
    positions = []
    text = path.read_text(encoding="utf-8-sig")
    for index, label in enumerate(labels, 1):
        positions.append(text.find(f"[{index}] {label}"))
    assert all(position > 0 for position in positions), "七个章节标题都应按序号出现"
    assert positions == sorted(positions), "章节顺序必须与 SECTION_ORDER 一致"
    assert labels[-2] == "去噪记录" and labels[-1].startswith("原坐标"), "最长的两段必须在文末"


def test_renumber_sections_when_some_are_unchecked(tmp_path):
    options = TxtExportOptions(sections=("fourier", "coords"))
    path, info = _export(tmp_path, options=options)
    text = path.read_text(encoding="utf-8-sig")
    assert "[1] 傅里叶分析" in text
    assert "[2] 原坐标" in text
    assert "[3]" not in text
    assert info["sections"] == ["傅里叶分析", "原坐标（波形采样数据，长表）"]


def test_missing_data_sections_are_explained(tmp_path):
    options = TxtExportOptions(sections=("envelope", "denoise"))
    path, _ = _export(tmp_path, options=options, envelope=None, envelope_times=None, fit=None)
    text = path.read_text(encoding="utf-8-sig")
    assert "未计算" in text, "没有包络数据时要明确说明，而不是导出空段"
    assert "无记录" in text


# ---------------------------------------------------------------- 选项


def test_coord_modes_convert_to_stride():
    assert TxtExportOptions(coord_mode="per_second", coord_per_second=1000).coord_stride(48000) == 48
    assert TxtExportOptions(coord_mode="step", coord_step=250).coord_stride(48000) == 250
    assert TxtExportOptions(coord_mode="all").coord_stride(48000) == 1


def test_coord_row_count_follows_stride(tmp_path):
    options = TxtExportOptions(sections=("coords",), coord_mode="per_second", coord_per_second=500)
    path, info = _export(tmp_path, options=options)
    x, fs = _signal()
    stride = options.coord_stride(fs)
    expected = (x.size + stride - 1) // stride
    data_rows = 0
    started = False
    for line in _lines(path):
        if line.startswith("t/s"):
            started = True
            continue
        if started and line and not line.startswith("#"):
            data_rows += 1
        elif started and not line:
            break
    assert data_rows == expected
    assert info["stride"] == stride


def test_stat_scopes_can_be_multiple(tmp_path):
    options = TxtExportOptions(sections=("stats",), stat_scopes=("full", "region"),
                               region=(0.5, 1.0))
    path, _ = _export(tmp_path, options=options)
    text = path.read_text(encoding="utf-8-sig")
    assert "[1.1] 全文件统计" in text
    assert "[1.2] 蓝框选区统计" in text
    assert "自定义" not in text


def test_stat_scopes_skipped_when_no_region(tmp_path):
    options = TxtExportOptions(sections=("stats",), stat_scopes=("full", "region"), region=None)
    path, _ = _export(tmp_path, options=options)
    text = path.read_text(encoding="utf-8-sig")
    assert "跳过" in text


def test_ai_section_writes_narrative(tmp_path):
    options = TxtExportOptions(sections=("ai",), ai_text="主频 1000 Hz，包络平稳。")
    path, _ = _export(tmp_path, options=options)
    assert "主频 1000 Hz，包络平稳。" in path.read_text(encoding="utf-8-sig")


def test_filename_follows_source_and_version():
    source = Path("C:/data/20261110.wav")
    assert suggest_txt_path(source, False).endswith("20261110_源文件分析.txt")
    assert suggest_txt_path(source, True).endswith("20261110_修改分析.txt")
    assert suggest_txt_path(None, False).endswith("分析源文件分析.txt")
