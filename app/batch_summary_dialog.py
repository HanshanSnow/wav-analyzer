"""批量结果汇总窗口：一张对比表、一张分组统计表，外加导出按钮。

只展示 `core.batch_summary` 算好的表，不在这里重算任何数字。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from core.batch_summary import (
    Summary, comparison_series, export_group_csv, export_summary_csv, format_cell,
    group_statistics, numeric_columns,
)
from core.figure_export import FigureOptions, render_comparison_png
from core.i18n import tf, tr


class BatchSummaryDialog(QDialog):
    """完成后点「查看汇总」打开；表格只读，导出走按钮。"""

    def __init__(self, parent: QWidget | None = None, summary: Summary | None = None):
        super().__init__(parent)
        self.summary = summary or Summary()
        self.setWindowTitle(tr("批量结果汇总"))
        self.resize(1000, 620)
        self._build()

    # ------------------------------------------------------------ 界面
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        if self.summary.reference:
            from pathlib import Path

            ref = self.summary.reference
            banner = QLabel(tf('本批使用外部参考：{_v0}（第 {_v1} 声道）',
                               _v0=(Path(str(ref.get("path") or "")).name),
                               _v1=(int(ref.get("channel") or 0) + 1)))
            banner.setStyleSheet(
                "color: #1f5b38; background: #e8f5e9; border: 1px solid #c8e6c9;"
                " border-radius: 6px; padding: 6px 10px;")
            banner.setWordWrap(True)
            outer.addWidget(banner)

        self.tabs = QTabWidget()
        self.table = self._make_table(self.summary.columns, self.summary.rows)
        self.tabs.addTab(self.table, tf('对比表（{_v0} 个文件）', _v0=(len(self.summary.rows))))
        self.stats = group_statistics(self.summary)
        self.stats_table = self._make_table(
            ["group", "metric", "n", "mean", "std", "min", "max"], self.stats)
        self.tabs.addTab(self.stats_table, tr("分组统计"))
        outer.addWidget(self.tabs, 1)

        figure_row = QHBoxLayout()
        figure_row.addWidget(QLabel(tr("对比图指标")))
        self.metric_combo = QComboBox()
        for column in numeric_columns(self.summary):
            self.metric_combo.addItem(column, column)
        self.metric_combo.setEnabled(self.metric_combo.count() > 0)
        figure_row.addWidget(self.metric_combo, 1)
        outer.addLayout(figure_row)

        footer = QHBoxLayout()
        self.table_button = QPushButton(tr("导出对比表 CSV"))
        self.table_button.clicked.connect(self.export_table)
        self.stats_button = QPushButton(tr("导出分组统计 CSV"))
        self.stats_button.clicked.connect(self.export_stats)
        self.stats_button.setEnabled(bool(self.stats))
        self.figure_button = QPushButton(tr("导出对比图 PNG"))
        self.figure_button.clicked.connect(self.export_figure)
        self.figure_button.setEnabled(self.metric_combo.count() > 0)
        for button in (self.table_button, self.stats_button, self.figure_button):
            footer.addWidget(button)
        footer.addStretch(1)
        close = QPushButton(tr("关闭"))
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        outer.addLayout(footer)

    def _make_table(self, columns: list[str], rows: list[dict]) -> QTableWidget:
        table = QTableWidget(len(rows), len(columns))
        table.setHorizontalHeaderLabels(list(columns))
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        for row_index, row in enumerate(rows):
            for column_index, column in enumerate(columns):
                item = QTableWidgetItem(format_cell(row.get(column)))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                table.setItem(row_index, column_index, item)
        table.resizeColumnsToContents()
        return table

    # ------------------------------------------------------------ 导出
    def export_table(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("导出对比表"), "batch_summary.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            export_summary_csv(path, self.summary)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("导出失败"), str(exc))
            return
        self._notify(path)

    def export_stats(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("导出分组统计"), "batch_groups.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            export_group_csv(path, self.summary)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("导出失败"), str(exc))

    def export_figure(self) -> None:
        column = self.metric_combo.currentData()
        if not column:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("导出对比图"), f"batch_compare_{column}.png", "PNG (*.png)")
        if not path:
            return
        series = comparison_series(self.summary, str(column))
        options = FigureOptions(layout="screen", title=tf('批量对比：{_v0}', _v0=(column)))
        try:
            render_comparison_png(path, series, options, metric=str(column),
                                  x_label=tr("文件序号"), value_label=str(column))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("导出失败"), str(exc))
            return
        self._notify(path)

    def _notify(self, path: str) -> None:
        parent = self.parent()
        if hasattr(parent, "statusBar"):
            parent.statusBar().showMessage(tf('已导出 {path}', path=(path)), 6000)
