"""应用内手册：路径解析、缺失兜底、真实 PDF 打开与搜索。"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import manual_viewer  # noqa: E402
from app.manual_viewer import ManualViewerDialog, manual_path  # noqa: E402
from core.i18n import LANG_EN, LANG_ZH, set_language  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def restore_language():
    yield
    set_language(LANG_ZH)


def _pump(app, predicate, timeout=15.0):
    """转事件循环等 Qt 后台搜索补结果。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_manual_path_prefers_current_language():
    set_language(LANG_ZH)
    zh = manual_path()
    assert zh is not None and zh.name == "manual_zh.pdf"
    set_language(LANG_EN)
    en = manual_path()
    assert en is not None and en.name == "manual_en.pdf"


def test_manual_path_falls_back_to_other_language(tmp_path, monkeypatch):
    (tmp_path / "manual_en.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(manual_viewer, "docs_directory", lambda: tmp_path)
    set_language(LANG_ZH)
    found = manual_path()
    assert found is not None and found.name == "manual_en.pdf"


def test_manual_path_returns_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(manual_viewer, "docs_directory", lambda: tmp_path)
    assert manual_path() is None


def test_missing_pdf_only_hints(app, tmp_path, monkeypatch):
    monkeypatch.setattr(manual_viewer, "docs_directory", lambda: tmp_path)
    dialog = ManualViewerDialog()
    try:
        assert not dialog.search_edit.isEnabled()
        assert not dialog.zoom_combo.isEnabled()
        assert "没有找到手册 PDF" in dialog.page_label.text()
    finally:
        dialog.deleteLater()


def test_real_manual_opens_and_reports_pages(app):
    path = manual_path()
    assert path is not None
    assert path.stat().st_size > 100_000
    dialog = ManualViewerDialog(path=path)
    try:
        label = dialog.page_label.text()
        assert label.startswith("第 1 / ")
        total = int(label.split("/")[1].strip().split(" ")[0])
        assert total > 10
    finally:
        dialog.deleteLater()


def test_main_window_opens_manual(app, monkeypatch):
    from app.main_window import MainWindow

    opened: list[int] = []

    def fake_exec(self):
        opened.append(1)
        return 0

    monkeypatch.setattr(manual_viewer.ManualViewerDialog, "exec", fake_exec)
    window = MainWindow()
    try:
        window.open_manual()
        assert opened == [1]
    finally:
        window.deleteLater()


def test_search_finds_results_and_jumps(app):
    dialog = ManualViewerDialog()
    try:
        dialog.search_edit.setText("频率")
        dialog.search()
        assert _pump(app, lambda: dialog.next_button.isEnabled()), dialog.search_label.text()
        # 结果逐页补进来，等够三处再测前后跳转
        assert _pump(app, lambda: dialog._search.count() >= 3), dialog.search_label.text()
        assert "处" in dialog.search_label.text()
        assert dialog.page_offset(0) == 0
        dialog.jump_result(1)
        assert "第 2 /" in dialog.search_label.text()
        assert dialog.view.currentSearchResultIndex() == 1
        dialog.jump_result(-1)
        assert "第 1 /" in dialog.search_label.text()
    finally:
        dialog.deleteLater()
