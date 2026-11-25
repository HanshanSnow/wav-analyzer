"""应用内手册：用 QtPdf 直接打开 docs 下的中文/英文手册，支持搜索与翻页。

手册文件名保持中性（`manual_zh.pdf` / `manual_en.pdf`）；找不到文件时只提示，
不抛异常——打包漏带 PDF 不该让软件起不来。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtPdf import QPdfDocument, QPdfSearchModel
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from core.i18n import current_language, tf, tr

MANUAL_FILES = {"zh": "manual_zh.pdf", "en": "manual_en.pdf"}
ZOOM_MODES = (("fit", tr("适应宽度")), ("page", tr("适应页面")), ("custom", tr("自定义")))


def docs_directory() -> Path:
    """源码态与 PyInstaller 态都先找程序旁边的 `docs`。"""
    if getattr(sys, "frozen", False):
        candidates = [
            Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "docs",
            Path(sys.executable).resolve().parent / "docs",
        ]
    else:
        candidates = [Path(__file__).resolve().parents[1] / "docs"]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def manual_path(language: str | None = None) -> Path | None:
    """按界面语言选手册；另一版存在也可顶替，都没有返回 None。"""
    folder = docs_directory()
    language = language or current_language()
    order = ["zh", "en"] if language == "zh" else ["en", "zh"]
    for code in order:
        candidate = folder / MANUAL_FILES[code]
        if candidate.is_file():
            return candidate
    return None


class ManualViewerDialog(QDialog):
    """手册窗口：左侧页选择、顶部搜索、底部缩放下拉。"""

    def __init__(self, parent: QWidget | None = None, path: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("使用手册"))
        self.resize(1100, 780)
        self._path = Path(path) if path is not None else manual_path()
        self._document: QPdfDocument | None = None
        self._search: QPdfSearchModel | None = None
        self._result_index = -1
        self._build()
        if self._path is not None:
            self._load()

    # ------------------------------------------------------------ 界面
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(QLabel(tr("搜索")))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("输入关键词，回车跳到第一个匹配"))
        self.search_edit.returnPressed.connect(self.search)
        top.addWidget(self.search_edit, 1)
        self.previous_button = QPushButton(tr("上一处"))
        self.previous_button.clicked.connect(lambda: self.jump_result(-1))
        self.next_button = QPushButton(tr("下一处"))
        self.next_button.clicked.connect(lambda: self.jump_result(1))
        for button in (self.previous_button, self.next_button):
            button.setEnabled(False)
            top.addWidget(button)
        self.search_label = QLabel("")
        top.addWidget(self.search_label)
        top.addWidget(QLabel(tr("缩放")))
        self.zoom_combo = QComboBox()
        for key, label in ZOOM_MODES:
            self.zoom_combo.addItem(label, key)
        self.zoom_combo.currentIndexChanged.connect(self._zoom_changed)
        top.addWidget(self.zoom_combo)
        outer.addLayout(top)

        body = QHBoxLayout()
        self.view = QPdfView()
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        body.addWidget(self.view, 1)
        outer.addLayout(body, 1)

        bottom = QHBoxLayout()
        # QPdfPageSelector 没有暴露页码上限（本绑定里既无 maximumPageNumber 也无
        # setMaximumPageNumber），所以它永远停在第 1–2 页，页码也输不进去。
        # 用户反馈的「页码切换器失灵、上下按钮只能在前两页动」就是它，改用 QSpinBox。
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.setKeyboardTracking(False)
        self.page_spin.valueChanged.connect(self._page_spin_changed)
        bottom.addWidget(QLabel(tr("页码")))
        bottom.addWidget(self.page_spin)
        self.page_label = QLabel("")
        bottom.addWidget(self.page_label)
        bottom.addStretch(1)
        self.open_folder_button = QPushButton(tr("打开手册目录"))
        self.open_folder_button.clicked.connect(self.open_folder)
        bottom.addWidget(self.open_folder_button)
        close = QPushButton(tr("关闭"))
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        outer.addLayout(bottom)

        if self._path is None:
            self._show_missing()

    def _show_missing(self) -> None:
        folder = docs_directory()
        self.search_edit.setEnabled(False)
        self.zoom_combo.setEnabled(False)
        self.page_label.setText(
            tf('没有找到手册 PDF（{_v0}）。', _v0=(str(folder))))
        self.previous_button.setEnabled(False)
        self.next_button.setEnabled(False)

    def _load(self) -> None:
        document = QPdfDocument(self)
        if document.load(str(self._path)) != QPdfDocument.Error.None_:
            self._document = None
            self.page_label.setText(tf('手册打不开：{_v0}', _v0=(str(self._path))))
            return
        self._document = document
        self._search = QPdfSearchModel(self)
        self._search.setDocument(document)
        # 搜索结果由 Qt 在后台逐页补齐，count() 一开始是 0；等它插行再更新计数。
        self._search.rowsInserted.connect(self._on_results_added)
        self.view.setDocument(document)
        self.view.setSearchModel(self._search)
        self.page_spin.setMaximum(max(1, document.pageCount()))
        self.view.pageNavigator().currentPageChanged.connect(self._update_page_label)
        self._update_page_label(self.view.pageNavigator().currentPage())
        self.setWindowTitle(tf('使用手册 — {_v0}', _v0=(self._path.name)))

    # ------------------------------------------------------------ 行为
    def page_offset(self, page: int) -> int:
        """第 page 页顶端在滚动条上的位置（像素）。

        Qt 6.5 起 `QPdfPageNavigator` 不再有 jumpToPage，只剩 `jump(link)`，
        而 link 只能由搜索结果给出；按页跳转只能自己累加页面高度。
        """
        if self._document is None:
            return 0
        zoom = float(self.view.zoomFactor())
        spacing = int(self.view.pageSpacing())
        offset = 0
        for index in range(max(0, min(int(page), self._document.pageCount()))):
            offset += int(round(self._document.pagePointSize(index).height() * zoom)) + spacing
        return offset

    def goto_page(self, page: int) -> None:
        """跳到指定页（0 基）。

        不要自己累加页面高度：`pagePointSize()` 的单位是点，而 QPdfView 画出来的
        是像素，两者差一个缩放比；按点算出来的偏移会把第 30 页送到第 17 页左右。
        Qt 6.4 起 `pageNavigator.jump(page, location, zoom)` 就是干这个的。
        """
        if self._document is None:
            return
        page = max(0, min(int(page), self._document.pageCount() - 1))
        navigator = self.view.pageNavigator()
        zoom = float(navigator.currentZoom() or self.view.zoomFactor() or 1.0)
        try:
            navigator.jump(page, QPointF(0.0, 0.0), zoom)
        except (AttributeError, TypeError):
            # 老版本 Qt 没有 jump(page, location, zoom)，退回按点累加的估算值
            self.view.verticalScrollBar().setValue(self.page_offset(page))

    def _page_spin_changed(self, number: int) -> None:
        self.goto_page(int(number) - 1)

    def _update_page_label(self, page: int) -> None:
        if self._document is None:
            return
        page = max(0, min(int(page), self._document.pageCount() - 1))
        self.page_label.setText(
            tf('第 {_v0} / {_v1} 页', _v0=(page + 1), _v1=(self._document.pageCount())))
        # 回写页码框时屏蔽信号，否则会和 currentPageChanged 形成来回触发的死循环
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(page + 1)
        self.page_spin.blockSignals(False)

    def _zoom_changed(self) -> None:
        key = self.zoom_combo.currentData()
        if key == "fit":
            self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        elif key == "page":
            self.view.setZoomMode(QPdfView.ZoomMode.FitInView)
        else:
            self.view.setZoomMode(QPdfView.ZoomMode.Custom)
            self.view.setZoomFactor(1.5)

    def search(self) -> None:
        if self._search is None:
            return
        text = self.search_edit.text().strip()
        self._result_index = -1
        self.previous_button.setEnabled(False)
        self.next_button.setEnabled(False)
        if not text:
            self._search.setSearchString("")
            self.search_label.setText("")
            return
        self.search_label.setText(tr("正在搜索…"))
        self._search.setSearchString(text)
        self._update_search_label()

    def _on_results_added(self, *_args) -> None:
        self._update_search_label()
        if self._result_index < 0:
            self.jump_result(1)

    def _update_search_label(self) -> None:
        if self._search is None:
            return
        count = int(self._search.count())
        self.previous_button.setEnabled(count > 0)
        self.next_button.setEnabled(count > 0)
        if not self.search_edit.text().strip():
            self.search_label.setText("")
        elif count == 0:
            self.search_label.setText(tr("没有匹配"))
        elif self._result_index < 0:
            self.search_label.setText(tf('共 {_v0} 处', _v0=(count)))

    def jump_result(self, step: int) -> None:
        if self._search is None:
            return
        count = int(self._search.count())
        if count == 0:
            return
        index = (self._result_index + step) % count
        self._result_index = index
        link = self._search.resultAtIndex(index)
        if link is not None:
            self.goto_page(int(link.page()))
        self.view.setCurrentSearchResultIndex(index)
        self.search_label.setText(tf('第 {_v0} / {_v1} 处', _v0=(index + 1), _v1=(count)))

    def open_folder(self) -> None:
        """给出手册所在目录的路径。

        不再调用 explorer.exe：这台机器上它一启动就报 0xC0000142（应用程序无法
        正常启动），用户看到的是系统错误框而不是目录。改为把路径显示出来并可复制。
        """
        folder = docs_directory()
        box = QMessageBox(self)
        box.setWindowTitle(tr("手册所在位置"))
        box.setText(tf('手册 PDF 就存放在这个目录：\n{_v0}', _v0=(str(folder))))
        box.setInformativeText(
            tr("系统的文件管理器打不开（explorer.exe 启动失败），这里直接给出路径，"
               "可以复制后粘到保存对话框或资源管理器地址栏。"))
        copy_button = box.addButton(tr("复制路径"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is copy_button:
            from PySide6.QtGui import QGuiApplication

            QGuiApplication.clipboard().setText(str(folder))
