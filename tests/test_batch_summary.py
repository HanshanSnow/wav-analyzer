"""批量结果汇总：分组解析、空单元格、失败行、统计与对比图。"""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.batch import BatchResult, FileOutcome
from core.batch_summary import (
    UNGROUPED, build_summary, comparison_series, export_group_csv, export_summary_csv,
    format_cell, group_statistics, numeric_columns, parse_group_from_name,
    parse_repeat_from_name,
)


def _result() -> BatchResult:
    return BatchResult(files=[
        FileOutcome(path=Path("sample_1000Hz_r1.wav"), ok=True,
                    rows={"file": "sample_1000Hz_r1.wav", "main_frequency": 1000.0,
                          "thd": 0.25, "rms_dbfs": -20.0}),
        FileOutcome(path=Path("sample_1000Hz_r2.wav"), ok=True,
                    rows={"file": "sample_1000Hz_r2.wav", "main_frequency": 1004.0,
                          "thd": 0.31}),
        FileOutcome(path=Path("noise_take.wav"), ok=False, error="读不出文件"),
    ], seconds=3.5)


def test_group_and_repeat_come_from_the_file_name():
    assert parse_group_from_name("sample_1000Hz_r2.wav") == "1000 Hz"
    assert parse_group_from_name("a_1.5kHz_r3.wav") == "1500 Hz"
    assert parse_group_from_name("noise_take.wav") == UNGROUPED
    assert parse_repeat_from_name("sample_1000Hz_r2.wav") == 2
    assert parse_repeat_from_name("probe_run7.wav") == 7
    assert parse_repeat_from_name("noise_take.wav") is None


def test_missing_cells_stay_empty_instead_of_zero():
    summary = build_summary(_result())
    second = summary.rows[1]
    assert second["rms_dbfs"] == ""
    assert second["thd"] == pytest.approx(0.31)
    assert format_cell(second["rms_dbfs"]) == ""


def test_failed_files_keep_a_row_with_reason():
    summary = build_summary(_result())
    failed = summary.rows[2]
    assert failed["ok"] == "失败"
    assert failed["error"] == "读不出文件"
    assert failed["main_frequency"] == ""
    assert len(summary.rows) == 3


def test_columns_are_the_union_of_rows_with_ids_first():
    summary = build_summary(_result())
    assert summary.columns[:5] == ["file", "group", "repeat", "ok", "error"]
    assert "rms_dbfs" in summary.columns
    assert summary.groups == ["1000 Hz", UNGROUPED]


def test_group_statistics_use_only_valid_samples():
    summary = build_summary(_result())
    stats = {(row["group"], row["metric"]): row for row in group_statistics(summary)}
    thd = stats[("1000 Hz", "thd")]
    assert thd["n"] == 2
    assert thd["mean"] == pytest.approx(0.28)
    assert thd["std"] == pytest.approx(0.0424264, rel=1e-5)
    assert ("1000 Hz", "rms_dbfs") in stats        # 只有一个值也算极值，但 n=1
    assert stats[("1000 Hz", "rms_dbfs")]["n"] == 1
    assert stats[("1000 Hz", "rms_dbfs")]["std"] == ""
    assert not [row for row in group_statistics(summary) if row["group"] == UNGROUPED]


def test_numeric_columns_need_two_values():
    summary = build_summary(_result())
    columns = numeric_columns(summary)
    assert "thd" in columns and "main_frequency" in columns
    assert "rms_dbfs" not in columns


def test_comparison_series_indexes_from_one():
    summary = build_summary(_result())
    series = comparison_series(summary, "thd")
    assert list(series) == ["1000 Hz"]
    assert [point[0] for point in series["1000 Hz"]] == [1, 2]
    assert series["1000 Hz"][1][1] == pytest.approx(0.31)


def test_export_summary_csv_keeps_blank_cells(tmp_path):
    summary = build_summary(_result())
    target = export_summary_csv(tmp_path / "summary.csv", summary)
    text = io.open(target, encoding="utf-8-sig").read()
    rows = list(csv.DictReader([line for line in text.splitlines() if not line.startswith("#")]))
    assert len(rows) == 3
    assert rows[1]["rms_dbfs"] == ""
    assert rows[2]["ok"] == "失败"
    assert rows[0]["group"] == "1000 Hz"


def test_export_group_csv_writes_headers(tmp_path):
    summary = build_summary(_result())
    target = export_group_csv(tmp_path / "groups.csv", summary)
    rows = list(csv.DictReader(io.open(target, encoding="utf-8-sig")))
    assert set(rows[0]) == {"group", "metric", "n", "mean", "std", "min", "max"}


def test_export_group_csv_without_samples_raises(tmp_path):
    summary = build_summary(BatchResult(files=[FileOutcome(path=Path("x.wav"), ok=False)]))
    with pytest.raises(ValueError):
        export_group_csv(tmp_path / "empty.csv", summary)


# ---------------------------------------------------------------- 对比图
def test_comparison_png_is_rendered(tmp_path):
    from core.figure_export import FigureOptions, render_comparison_png

    summary = build_summary(_result())
    series = comparison_series(summary, "main_frequency")
    target = tmp_path / "compare.png"
    info = render_comparison_png(target, series, FigureOptions(layout="screen"),
                                 metric="main_frequency")
    assert target.is_file() and target.stat().st_size > 5_000
    assert info["kind"] == "comparison"
    assert info["points"] == 2
    assert target.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_comparison_png_rejects_empty_series(tmp_path):
    from core.figure_export import render_comparison_png

    with pytest.raises(ValueError, match="没有可对比的数据"):
        render_comparison_png(tmp_path / "x.png", {})


# ---------------------------------------------------------------- 对话框
def test_summary_dialog_shows_tables(tmp_path):
    from core.figure_export import FigureOptions
    from PySide6.QtWidgets import QApplication

    from app.batch_summary_dialog import BatchSummaryDialog

    app = QApplication.instance() or QApplication([])
    summary = build_summary(_result())
    dialog = BatchSummaryDialog(None, summary)
    assert dialog.table.rowCount() == 3
    assert dialog.table.columnCount() == len(summary.columns)
    assert dialog.tabs.count() == 2
    assert dialog.metric_combo.count() == len(numeric_columns(summary))
    assert dialog.figure_button.isEnabled() is True
    assert dialog.table.item(1, summary.columns.index("rms_dbfs")).text() == ""
    dialog.close()
    assert FigureOptions is not None and app is not None
