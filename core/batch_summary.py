"""批量结果的横向对比：一张表、按组统计、以及给对比图用的数据。

三条约定（与批量导出共用）：
- 跳过某一步时该单元格**留空**，不写 0——0 dB 和「没测」是两件事。
- 失败的文件也进表，带 `ok=False` 与原因；不因为它没数据就整行消失。
- 分组只按文件名解析出的基频与重复序号，解析不出就归「未分组」，不猜。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from core.batch import BatchResult, FileOutcome, parse_fundamental_from_name
from core.exporter import export_rows_csv
from core.i18n import tr

ID_COLUMNS = ("file", "group", "repeat", "ok", "error")
UNGROUPED = "未分组"
_REPEAT_PATTERNS = (
    re.compile(r"[_\-#\s][rR](\d{1,3})$"),
    re.compile(r"[_\-#\s](?:run|rep|repeat|trial)(\d{1,3})$", re.IGNORECASE),
)


def parse_repeat_from_name(name: str) -> int | None:
    """`sample_1000Hz_r3.wav` → 3；解析不出返回 None。"""
    stem = Path(name).stem
    for pattern in _REPEAT_PATTERNS:
        match = pattern.search(stem)
        if match:
            return int(match.group(1))
    return None


def parse_group_from_name(name: str) -> str:
    """分组名：优先用文件名里的基频，其次回落「未分组」。"""
    frequency = parse_fundamental_from_name(Path(name).stem)
    return f"{frequency:g} Hz" if frequency is not None else UNGROUPED


@dataclass
class Summary:
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    # 批量级外部参考的溯源信息（路径/声道）；None 表示用的各文件内置声道。
    reference: dict[str, Any] | None = None


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float, np.integer, np.floating)):
        return math.isfinite(float(value))
    if isinstance(value, str):
        try:
            return math.isfinite(float(value))
        except ValueError:
            return False
    return False


def _number(value: Any) -> float:
    return float(value)


def build_summary(result: BatchResult) -> Summary:
    """每个文件一行；列 = 各文件 rows 键的并集（按首次出现排序）。"""
    columns: list[str] = list(ID_COLUMNS)
    seen = set(columns)
    for item in result.files:
        for key in item.rows:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    rows: list[dict[str, Any]] = []
    groups: list[str] = []
    for item in result.files:
        group = parse_group_from_name(item.path.name)
        if group not in groups:
            groups.append(group)
        row: dict[str, Any] = {column: "" for column in columns}
        row["file"] = item.path.name
        row["group"] = group
        repeat = parse_repeat_from_name(item.path.name)
        row["repeat"] = "" if repeat is None else repeat
        row["ok"] = tr("成功") if item.ok else tr("失败")
        row["error"] = "" if item.ok else (item.error or tr("未知错误"))
        if item.ok:
            for key, value in item.rows.items():
                if _is_number(value):
                    row[key] = _number(value)
        rows.append(row)
    return Summary(columns=columns, rows=rows, groups=groups,
                   reference=result.reference)


def metric_columns(summary: Summary, minimum: int = 1) -> list[str]:
    """能算统计的列；`minimum` 是至少要有的有限值个数。"""
    columns = []
    for column in summary.columns:
        if column in ID_COLUMNS:
            continue
        values = [row[column] for row in summary.rows if _is_number(row.get(column))]
        if len(values) >= minimum:
            columns.append(column)
    return columns


def numeric_columns(summary: Summary) -> list[str]:
    """对比图用的列：至少两个点才画得出折线。"""
    return metric_columns(summary, minimum=2)


def group_statistics(summary: Summary) -> list[dict[str, Any]]:
    """按组算 n / 均值 / 样本标准差 / 极值；只用成功且有值的样本。"""
    stats: list[dict[str, Any]] = []
    columns = metric_columns(summary)
    for group in summary.groups:
        for column in columns:
            values = [
                _number(row[column]) for row in summary.rows
                if row["group"] == group and _is_number(row.get(column))
            ]
            if not values:
                continue
            array = np.asarray(values, dtype=np.float64)
            stats.append({
                "group": group,
                "metric": column,
                "n": int(array.size),
                "mean": float(array.mean()),
                "std": float(array.std(ddof=1)) if array.size > 1 else "",
                "min": float(array.min()),
                "max": float(array.max()),
            })
    return stats


def comparison_series(summary: Summary, column: str) -> dict[str, list[tuple[int, float]]]:
    """对比图用：组名 → [(文件序号, 数值)]，序号从 1 起，按表里的顺序。"""
    series: dict[str, list[tuple[int, float]]] = {}
    for index, row in enumerate(summary.rows, start=1):
        if not _is_number(row.get(column)):
            continue
        series.setdefault(row["group"], []).append((index, _number(row[column])))
    return series


def format_cell(value: Any) -> str:
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        number = float(value)
        return "—" if not math.isfinite(number) else f"{number:.6g}"
    return "" if value is None else str(value)


def export_summary_csv(path: str | Path, summary: Summary) -> Path:
    """横向对比表 → CSV；缺的单元格留空。"""
    rows = [{column: format_cell(row.get(column)) for column in summary.columns}
            for row in summary.rows]
    return export_rows_csv(path, rows)


def export_group_csv(path: str | Path, summary: Summary) -> Path:
    rows = [{key: format_cell(value) for key, value in row.items()}
            for row in group_statistics(summary)]
    return export_rows_csv(path, rows)
