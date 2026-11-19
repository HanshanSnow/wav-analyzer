"""批量处理的“脚本编辑”窗口：搭步骤 → 选文件 → 开始。

这里只负责“搭好一份脚本并交出去”，实际执行在主窗口里用工作线程跑，
这样进度遮罩能盖住整个主窗口，而且中途可以取消。
"""

from __future__ import annotations

from core.i18n import tf, tr
import json
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QSplitter, QVBoxLayout, QWidget,
)

from core.batch import (
    STEP_SPECS, STEP_SPEC_BY_KIND, describe_step, irrelevant_keys, new_step,
    normalize_steps,
)

EXPORT_KINDS = ("export_wav", "export_txt", "export_png", "export_csv", "export_html")


class BatchDialog(QDialog):
    """返回 (steps, files, output_dir)；由主窗口负责执行。"""

    def __init__(self, parent: QWidget | None = None, default_dir: str = "",
                 settings: QSettings | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("批量处理 — 脚本编辑"))
        self.resize(1010, 730)
        self.steps: list[dict] = []
        self.files: list[str] = []
        self._index = -1
        self._widgets: dict[str, object] = {}
        # 允许注入独立配置对象，测试里用临时 INI 文件，不污染真实偏好。
        self._settings = settings or QSettings("WAVAnalyzer", "WAVAnalyzer")
        self._build_ui()
        self._restore(default_dir)

    # ------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._step_panel())
        splitter.addWidget(self._param_panel())
        splitter.setSizes([320, 640])
        outer.addWidget(splitter, 1)
        outer.addWidget(self._file_panel())

        footer = QHBoxLayout()
        hint = QLabel(tr("步骤自上而下执行；只有“导出”类步骤会写文件，源文件始终只读。"))
        hint.setStyleSheet("color: #607d8b;")
        cancel = QPushButton(tr("取消"))
        cancel.clicked.connect(self.reject)
        self.start_button = QPushButton(tr("开始处理"))
        self.start_button.setDefault(True)
        self.start_button.setMinimumWidth(120)
        self.start_button.clicked.connect(self._on_start)
        footer.addWidget(hint, 1)
        footer.addWidget(cancel)
        footer.addWidget(self.start_button)
        outer.addLayout(footer)

    def _step_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 6, 0)
        title = QLabel(tr("任务步骤"))
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)

        self.step_list = QListWidget()
        # 摘要会把多个非默认参数串成一句话，很容易超出列表宽度：
        # 折行显示且关掉横向滚动条，比让用户左右拖动去找被截断的半个参数好。
        self.step_list.setWordWrap(True)
        self.step_list.setTextElideMode(Qt.ElideNone)
        self.step_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.step_list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self.step_list, 1)

        add_button = QPushButton(tr("＋ 新增步骤"))
        add_button.setToolTip(tr("选择要加入流水线的处理功能"))
        add_button.clicked.connect(self._show_add_menu)
        remove_button = QPushButton(tr("－ 删除"))
        remove_button.clicked.connect(self._remove_step)
        row1 = QHBoxLayout()
        row1.addWidget(add_button, 2)
        row1.addWidget(remove_button, 1)
        layout.addLayout(row1)

        up_button = QPushButton(tr("上移"))
        up_button.clicked.connect(lambda: self._move_step(-1))
        down_button = QPushButton(tr("下移"))
        down_button.clicked.connect(lambda: self._move_step(1))
        row2 = QHBoxLayout()
        row2.addWidget(up_button)
        row2.addWidget(down_button)
        layout.addLayout(row2)

        load_button = QPushButton(tr("载入脚本…"))
        load_button.clicked.connect(self._load_script)
        save_button = QPushButton(tr("保存脚本…"))
        save_button.clicked.connect(self._save_script)
        row3 = QHBoxLayout()
        row3.addWidget(load_button)
        row3.addWidget(save_button)
        layout.addLayout(row3)
        return panel

    def _param_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 0, 0, 0)
        self.step_title = QLabel(tr("尚未添加步骤"))
        self.step_title.setStyleSheet("font-weight: 600; font-size: 11pt;")
        self.step_desc = QLabel(tr("点左侧“＋ 新增步骤”挑一个功能，再在这里设置参数。"))
        self.step_desc.setWordWrap(True)
        self.step_desc.setStyleSheet("color: #546e7a;")
        layout.addWidget(self.step_title)
        layout.addWidget(self.step_desc)

        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(self.form_scroll, 1)
        self._reset_form()
        return panel

    def _file_panel(self) -> QWidget:
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        row1 = QHBoxLayout()
        self.file_label = QLabel(tr("待处理文件：尚未选择"))
        self.file_label.setWordWrap(True)
        pick = QPushButton(tr("选择待处理的文件…"))
        pick.clicked.connect(self._pick_files)
        clear = QPushButton(tr("清空"))
        clear.clicked.connect(self._clear_files)
        row1.addWidget(self.file_label, 1)
        row1.addWidget(pick)
        row1.addWidget(clear)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel(tr("输出目录")))
        self.output_dir = QLineEdit()
        self.output_dir.setPlaceholderText(tr("留空 = 与源文件同目录"))
        self.output_dir.textChanged.connect(self._refresh_hint)
        browse = QPushButton(tr("浏览…"))
        browse.clicked.connect(self._pick_output_dir)
        row2.addWidget(self.output_dir, 1)
        row2.addWidget(browse)
        layout.addLayout(row2)

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color: #607d8b;")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        return panel

    # ------------------------------------------------------------ 步骤编辑
    def _show_add_menu(self) -> None:
        menu = QMenu(self)
        for spec in STEP_SPECS:
            action = menu.addAction(spec.label)
            action.setToolTip(spec.description)
            action.triggered.connect(lambda _checked=False, kind=spec.kind: self._add_step(kind))
        menu.exec(self.cursor().pos())

    def _add_step(self, kind: str) -> None:
        self.steps.append(new_step(kind))
        self._refresh_list()
        self.step_list.setCurrentRow(len(self.steps) - 1)

    def _remove_step(self) -> None:
        if self._index < 0:
            return
        del self.steps[self._index]
        self._index = -1
        self._refresh_list()
        if self.steps:
            self.step_list.setCurrentRow(min(len(self.steps) - 1, self._index if self._index >= 0 else 0))

    def _move_step(self, delta: int) -> None:
        if self._index < 0:
            return
        target = self._index + delta
        if not 0 <= target < len(self.steps):
            return
        self.steps[self._index], self.steps[target] = self.steps[target], self.steps[self._index]
        self._index = target
        self._refresh_list()
        self.step_list.setCurrentRow(target)

    def _refresh_list(self) -> None:
        current = self._index
        self.step_list.blockSignals(True)
        self.step_list.clear()
        for order, step in enumerate(self.steps, 1):
            item = QListWidgetItem(f"{order}. {describe_step(step)}")
            item.setToolTip(STEP_SPEC_BY_KIND[step["kind"]].description)
            self.step_list.addItem(item)
        self.step_list.blockSignals(False)
        if self.steps:
            self.step_list.setCurrentRow(max(0, min(current, len(self.steps) - 1)))

    def _on_row_changed(self, row: int) -> None:
        self._index = row if 0 <= row < len(self.steps) else -1
        self._rebuild_form()

    # ------------------------------------------------------------ 参数表单
    def _reset_form(self) -> None:
        """整块换掉表单容器。

        不能用 QFormLayout.takeAt 清空：它只移走控件、把**空行**留在布局里，
        切几次步骤后 rowCount 会一路累积（实测 3 个参数的表单报出 10 行）。
        换掉 holder 是唯一干净的清空方式。
        """
        old = self.form_scroll.takeWidget()
        if old is not None:
            old.setParent(None)
            old.deleteLater()
        holder = QWidget()
        self.form = QFormLayout(holder)
        self.form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.form_scroll.setWidget(holder)
        self._widgets = {}

    def _rebuild_form(self) -> None:
        self._reset_form()
        if self._index < 0:
            self.step_title.setText(tr("尚未添加步骤"))
            self.step_desc.setText(tr("点左侧“＋ 新增步骤”挑一个功能，再在这里设置参数。"))
            return
        step = self.steps[self._index]
        spec = STEP_SPEC_BY_KIND[step["kind"]]
        self.step_title.setText(spec.label)
        self.step_desc.setText(spec.description)
        params = step["params"]
        for param in spec.params:
            value = params.get(param.key, param.default)
            widget = self._make_widget(param, value)
            self._widgets[param.key] = widget
            if param.kind == "bool":
                self.form.addRow("", widget)
            else:
                self.form.addRow(param.label, widget)
            if param.tooltip:
                widget.setToolTip(param.tooltip)
        self._sync_enabled()

    def _make_widget(self, param, value) -> QWidget:
        if param.kind == "float":
            widget = QDoubleSpinBox()
            widget.setDecimals(param.decimals)
            widget.setRange(param.minimum, param.maximum)
            widget.setSingleStep(param.step)
            widget.setSuffix(param.suffix)
            widget.setKeyboardTracking(False)
            widget.setValue(float(value))
            widget.valueChanged.connect(self._on_param_changed)
            return widget
        if param.kind == "int":
            widget = QSpinBox()
            widget.setRange(int(param.minimum), int(param.maximum))
            widget.setValue(int(value))
            widget.valueChanged.connect(self._on_param_changed)
            return widget
        if param.kind == "choice":
            widget = QComboBox()
            for key, label in param.choices:
                widget.addItem(label, key)
            index = widget.findData(value)
            widget.setCurrentIndex(max(0, index))
            widget.currentIndexChanged.connect(self._on_param_changed)
            return widget
        if param.kind == "bool":
            widget = QCheckBox(param.label)
            widget.setChecked(bool(value))
            widget.toggled.connect(self._on_param_changed)
            return widget
        if param.kind == "checklist":
            holder = QWidget()
            # 章节多的时候两列排，否则一屏放不下，用户得来回滚。
            columns = 2 if len(param.choices) > 4 else 1
            layout = QGridLayout(holder) if columns == 2 else None
            if layout is None:
                layout = QVBoxLayout(holder)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(2)
            else:
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setHorizontalSpacing(18)
                layout.setVerticalSpacing(2)
            picked = list(value or ())
            boxes: dict[str, QCheckBox] = {}
            per_column = (len(param.choices) + columns - 1) // columns
            for order, (key, label) in enumerate(param.choices):
                box = QCheckBox(label)
                box.setChecked(key in picked)
                box.toggled.connect(self._on_param_changed)
                if isinstance(layout, QGridLayout):
                    layout.addWidget(box, order % per_column, order // per_column)
                else:
                    layout.addWidget(box)
                boxes[key] = box
            holder._boxes = boxes          # type: ignore[attr-defined]
            return holder
        widget = QLineEdit(str(value))
        widget.textChanged.connect(self._on_param_changed)
        return widget

    def _collect(self) -> dict:
        step = self.steps[self._index]
        params = {}
        for param in STEP_SPEC_BY_KIND[step["kind"]].params:
            widget = self._widgets.get(param.key)
            if widget is None:
                continue
            if param.kind == "checklist":
                boxes = getattr(widget, "_boxes", {})
                params[param.key] = [key for key, box in boxes.items() if box.isChecked()]
            elif param.kind == "bool":
                params[param.key] = bool(widget.isChecked())
            elif param.kind == "choice":
                params[param.key] = widget.currentData()
            elif param.kind == "text":
                params[param.key] = widget.text()
            elif param.kind == "int":
                params[param.key] = int(widget.value())
            else:
                params[param.key] = float(widget.value())
        return params

    def _on_param_changed(self, *_args) -> None:
        if self._index < 0:
            return
        self.steps[self._index]["params"] = self._collect()
        self._sync_enabled()
        # 列表标题同步更新，避免参数改了摘要还是旧的
        item = self.step_list.item(self._index)
        if item is not None:
            item.setText(f"{self._index + 1}. {describe_step(self.steps[self._index])}")
        self._refresh_hint()

    def _sync_enabled(self) -> None:
        """把当前组合下无意义的参数置灰，避免“填了却不生效”。"""
        if self._index < 0:
            return
        step = self.steps[self._index]
        skip = irrelevant_keys(step["kind"], step["params"])
        for key, widget in self._widgets.items():
            widget.setEnabled(key not in skip)

    # ------------------------------------------------------------ 文件与输出
    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("选择待处理的 WAV（可多选）"), "", tr("WAV 音频 (*.wav)"))
        if paths:
            self.files = list(dict.fromkeys(paths))     # 去重且保序
            self._refresh_hint()

    def _clear_files(self) -> None:
        self.files = []
        self._refresh_hint()

    def _pick_output_dir(self) -> None:
        current = self.output_dir.text().strip()
        start = current if current and Path(current).is_dir() else ""
        folder = QFileDialog.getExistingDirectory(self, tr("选择输出目录"), start)
        if folder:
            self.output_dir.setText(folder)

    def _refresh_hint(self) -> None:
        if not self.files:
            self.file_label.setText(tr("待处理文件：尚未选择"))
        else:
            names = [Path(item).name for item in self.files[:3]]
            more = "" if len(self.files) <= 3 else tf(' …（共 {_v0} 个）', _v0=(len(self.files)))
            self.file_label.setText(
                tf('待处理文件：{_v0} 个 → ', _v0=(len(self.files))) + "、".join(names) + more)
            self.file_label.setToolTip("\n".join(self.files))

        parts: list[str] = []
        total = len(self.steps)
        if total:
            exports = sum(1 for step in self.steps if step["kind"] in EXPORT_KINDS)
            parts.append(tf('共 {total} 个步骤（其中 {exports} 个导出步骤）', total=(total), exports=(exports)))
            target = self.output_dir.text().strip()
            parts.append(tf('输出到 {target}', target=(target)) if target else tr("输出到各源文件所在目录"))
        self.summary_label.setText("；".join(parts))

    # ------------------------------------------------------------ 脚本存取
    def _save_script(self) -> None:
        if not self.steps:
            QMessageBox.information(self, tr("没有可保存的步骤"), tr("请先添加至少一个任务步骤。"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("保存脚本"), "batch_script.json", "JSON (*.json)")
        if not path:
            return
        payload = {"version": 1, "steps": self.steps}
        try:
            Path(path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.summary_label.setText(tf('脚本已保存到 {path}', path=(path)))
        except OSError as exc:
            QMessageBox.warning(self, tr("保存失败"), str(exc))

    def _load_script(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("载入脚本"), "", "JSON (*.json)")
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("载入失败"), str(exc))
            return
        steps = normalize_steps(payload.get("steps") or [])
        if not steps:
            QMessageBox.warning(self, tr("载入失败"), tr("文件里没有可识别的任务步骤。"))
            return
        self.steps = steps
        self._index = -1
        self._refresh_list()
        self.step_list.setCurrentRow(0)
        self.summary_label.setText(tf('已载入 {_v0} 个步骤', _v0=(len(steps))))

    # ------------------------------------------------------------ 校验与返回
    def _on_start(self) -> None:
        if not self.steps:
            QMessageBox.information(self, tr("还没有步骤"), tr("请先用“＋ 新增步骤”搭一条流水线。"))
            return
        if not self.files:
            QMessageBox.information(self, tr("还没有文件"), tr("请先点“选择待处理的文件”。"))
            return
        for step in self.steps:
            if step["kind"] == "export_txt":
                params = step["params"]
                if params.get("aggregate") == "single" and not str(params.get("merged_name") or "").strip():
                    QMessageBox.warning(self, tr("合并文件名不能为空"),
                                        tr("“导出分析 TXT”选了合并方式，请填写合并文件名。"))
                    return
                if not params.get("sections"):
                    QMessageBox.warning(self, tr("没有选章节"),
                                        tr("“导出分析 TXT”至少要勾一个章节。"))
                    return
            if step["kind"] == "export_csv" and step["params"].get("aggregate") == "single":
                if not str(step["params"].get("merged_name") or "").strip():
                    QMessageBox.warning(self, tr("合并文件名不能为空"),
                                        tr("“导出统计 CSV”选了合并方式，请填写合并文件名。"))
                    return
            if step["kind"] == "export_png" and not step["params"].get("kinds"):
                QMessageBox.warning(self, tr("没有选图像类型"),
                                    tr("“导出图像 PNG”至少要勾一种图像。"))
                return
        if not any(step["kind"] in EXPORT_KINDS for step in self.steps):
            answer = QMessageBox.question(
                self, tr("没有导出步骤"),
                tr("当前脚本只做分析、不写任何文件。确定继续吗？"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        self._persist()
        self.accept()

    def _persist(self) -> None:
        """记住上次的脚本与输出目录，实验往往要重复跑同一套流程。"""
        try:
            self._settings.setValue("batch/script", json.dumps(self.steps, ensure_ascii=False))
            self._settings.setValue("batch/output_dir", self.output_dir.text().strip())
        except Exception:
            pass

    def _restore(self, default_dir: str) -> None:
        raw = self._settings.value("batch/script", "")
        restored = False
        if isinstance(raw, str) and raw.strip():
            try:
                steps = normalize_steps(json.loads(raw) or [])
            except ValueError:
                steps = []
            if steps:
                self.steps = steps
                restored = True
        if not self.steps:
            # 首次使用给一条能直接跑的默认流水线
            self.steps = [new_step("stats"), new_step("export_txt"), new_step("export_csv")]
            restored = False
        self._refresh_list()
        if self.steps:
            self.step_list.setCurrentRow(0)
        saved_dir = self._settings.value("batch/output_dir", "")
        self.output_dir.setText(str(saved_dir or default_dir or ""))
        if restored:
            self.summary_label.setText(tf('已恢复上次的 {_v0} 个步骤', _v0=(len(self.steps))))
        self._refresh_hint()

    # ------------------------------------------------------------ 对外
    def job(self) -> tuple[list[dict], list[str], str]:
        return self.steps, self.files, self.output_dir.text().strip()

    def script_steps(self) -> list[dict]:
        return self.steps
