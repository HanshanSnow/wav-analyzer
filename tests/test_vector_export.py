"""矢量图导出：PDF / SVG 走后缀分派、文字转路径、以及对话框的后缀与校验。"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.figure_export import FigureOptions, render_spectrum_png, render_waveform_png  # noqa: E402
from core.spectral import fourier_analysis  # noqa: E402

FS = 8000


def _tone(seconds: float = 0.5) -> np.ndarray:
    t = np.arange(int(FS * seconds)) / FS
    return 0.4 * np.sin(2 * np.pi * 300 * t)


def _paper(**kwargs) -> FigureOptions:
    return FigureOptions(layout="paper", column="single", **kwargs)


def test_pdf_export_is_a_real_pdf_without_pixel_size(tmp_path) -> None:
    target = tmp_path / "wave.pdf"
    info = render_waveform_png(str(target), samples=_tone(), sample_rate=FS, options=_paper())
    assert target.exists() and target.stat().st_size > 5_000
    assert target.read_bytes().startswith(b"%PDF")
    assert info["width"] is None and info["height"] is None
    assert info["vector"] is True
    assert info["inches"] == pytest.approx((3.5, 2.45))


def test_svg_text_becomes_paths_by_default(tmp_path) -> None:
    target = tmp_path / "wave.svg"
    info = render_waveform_png(str(target), samples=_tone(), sample_rate=FS, options=_paper())
    content = target.read_text(encoding="utf-8")
    assert "<svg" in content
    assert "<text" not in content, "默认把文字转成路径，不依赖本机字体"
    assert info["width"] is None


def test_svg_can_keep_editable_text(tmp_path) -> None:
    target = tmp_path / "wave_text.svg"
    render_waveform_png(
        str(target), samples=_tone(), sample_rate=FS,
        options=_paper(vector_text_as_path=False))
    assert "<text" in target.read_text(encoding="utf-8")


def test_spectrum_pdf_export(tmp_path) -> None:
    fourier = fourier_analysis(_tone(), FS)
    target = tmp_path / "spectrum.pdf"
    info = render_spectrum_png(str(target), fourier, _paper())
    assert target.read_bytes().startswith(b"%PDF")
    assert info["width"] is None
    assert target.stat().st_size > 5_000


def test_dialog_switches_suffix_with_format(tmp_path) -> None:
    from app.image_export_dialog import ImageExportDialog, VECTOR_FORMATS
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    dialog = ImageExportDialog(None, default_path=str(tmp_path / "wave.png"))
    assert dialog.output_path().endswith(".png")

    for index in range(dialog.format_combo.count()):
        suffix = str(dialog.format_combo.itemData(index))
        dialog.format_combo.setCurrentIndex(index)
        assert dialog.output_path().endswith(f".{suffix}")
        assert dialog.vector_path_check.isEnabled() is (suffix in VECTOR_FORMATS)
    dialog.close()


def test_dialog_rejects_unknown_suffix(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app.image_export_dialog import ImageExportDialog

    QApplication.instance() or QApplication([])
    dialog = ImageExportDialog(None, default_path=str(tmp_path / "wave.txt"))
    dialog.path_edit.setText(str(tmp_path / "wave.txt"))
    warned: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(str(a)))
    dialog.accept()
    assert warned, "未知后缀必须弹提示而不是照写"
    assert not Path(tmp_path / "wave.txt").exists()
