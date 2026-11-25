from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import soundfile as sf

from core.project import (
    PROJECT_FORMAT, PROJECT_VERSION, build_project, dump_project, file_sha256,
    load_project, save_project, source_path_of, verify_source,
)


def _write_wav(path: Path, seconds: float = 1.0, sample_rate: int = 8000,
               channels: int = 1, frequency: float = 500.0) -> Path:
    times = np.arange(int(seconds * sample_rate)) / sample_rate
    tone = 0.3 * np.sin(2 * np.pi * frequency * times)
    data = tone if channels == 1 else np.column_stack([tone] * channels)
    sf.write(str(path), data, sample_rate, subtype="PCM_24", format="WAV")
    return path


def _project(path: Path, **kwargs) -> dict:
    options = dict(
        sample_rate=48000, channels=2, frames=96000, channel=1,
        edits=[{"kind": "trim", "params": {"start": 0.1, "end": 0.9}}],
        selection=(0.2, 0.8),
        calibration={"active": "标准麦", "payload": "{}"},
        analysis={"fundamental_hz": 1000.0, "envelope_model": "linear", "window": "hamming"},
        export={"report_language": "en"},
    )
    options.update(kwargs)
    return build_project(path, **options)


def test_sha256_of_a_file_matches_hashlib(tmp_path: Path) -> None:
    import hashlib

    source = _write_wav(tmp_path / "a.wav")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    assert file_sha256(source) == expected


def test_round_trip_keeps_every_field(tmp_path: Path) -> None:
    source = _write_wav(tmp_path / "a.wav")
    project = _project(source)
    target = save_project(tmp_path / "a.wavproj", project)
    assert target.suffix == ".wavproj"
    loaded = load_project(target)

    assert loaded["format"] == PROJECT_FORMAT
    assert loaded["version"] == PROJECT_VERSION
    assert loaded["channel"] == 1
    assert loaded["source"]["sha256"] == project["source"]["sha256"]
    assert loaded["source"]["sample_rate"] == 48000
    assert loaded["edits"] == project["edits"]
    assert loaded["selection"] == [0.2, 0.8]
    assert loaded["calibration"]["active"] == "标准麦"
    assert loaded["analysis"]["window"] == "hamming"
    assert loaded["export"]["report_language"] == "en"
    assert dump_project(loaded) == dump_project(project)


def test_suffix_is_added_when_missing(tmp_path: Path) -> None:
    source = _write_wav(tmp_path / "b.wav")
    target = save_project(tmp_path / "noSuffix", _project(source))
    assert target.name == "noSuffix.wavproj"
    assert target.is_file()


def test_source_is_found_by_absolute_path(tmp_path: Path) -> None:
    source = _write_wav(tmp_path / "c.wav")
    project = _project(source)
    assert source_path_of(project, tmp_path) == source.resolve()


def test_source_falls_back_to_relative_path(tmp_path: Path) -> None:
    source = _write_wav(tmp_path / "d.wav")
    project = _project(source)
    moved = tmp_path / "elsewhere"
    moved.mkdir()
    project["source"]["path"] = str(tmp_path / "gone" / "d.wav")
    project["source"]["relative_path"] = "d.wav"
    assert source_path_of(project, tmp_path) == tmp_path / "d.wav"
    assert source_path_of(project, moved) is None


def test_missing_source_returns_none(tmp_path: Path) -> None:
    project = _project(tmp_path / "missing.wav")
    assert source_path_of(project, tmp_path) is None


def test_hash_mismatch_is_reported(tmp_path: Path) -> None:
    source = _write_wav(tmp_path / "e.wav")
    project = _project(source)
    assert verify_source(project, source) is None

    _write_wav(tmp_path / "e.wav", seconds=1.0, frequency=900.0)
    problem = verify_source(project, source)
    assert problem is not None and "哈希" in problem


def test_empty_hash_is_not_checked(tmp_path: Path) -> None:
    source = _write_wav(tmp_path / "f.wav")
    project = _project(source)
    project["source"]["sha256"] = ""
    assert verify_source(project, source) is None


def test_bad_json_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "bad.wavproj"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        load_project(bad)


def test_wrong_format_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "other.wavproj"
    bad.write_text(json.dumps({"format": "something-else", "version": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="不是本程序"):
        load_project(bad)


def test_newer_version_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "newer.wavproj"
    bad.write_text(json.dumps({
        "format": PROJECT_FORMAT, "version": PROJECT_VERSION + 1,
        "source": {"path": "a.wav"},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="更新版本"):
        load_project(bad)


def test_missing_source_block_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "nosrc.wavproj"
    bad.write_text(json.dumps({"format": PROJECT_FORMAT, "version": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="源文件"):
        load_project(bad)


def test_unknown_fields_and_bad_edits_are_tolerated(tmp_path: Path) -> None:
    source = _write_wav(tmp_path / "g.wav")
    project = _project(source, edits=[
        {"kind": "trim", "params": {"start": 0.0, "end": 0.5}},
        {"kind": "", "params": {}},
        "not a dict",
        {"params": {"start": 0.1}},
    ])
    project["future_field"] = {"anything": 1}
    target = save_project(tmp_path / "g.wavproj", project)
    loaded = load_project(target)
    assert loaded["edits"] == [{"kind": "trim", "params": {"start": 0.0, "end": 0.5}}]
    assert "future_field" not in loaded


def test_empty_edits_list_is_allowed(tmp_path: Path) -> None:
    source = _write_wav(tmp_path / "h.wav")
    project = _project(source, edits=[])
    loaded = load_project(save_project(tmp_path / "h.wavproj", project))
    assert loaded["edits"] == []


def test_read_error_is_a_value_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="读不了工程文件"):
        load_project(tmp_path / "nope.wavproj")


# ---------------------------------------------------------------- 界面往返


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_main_window_round_trip_replays_trim(tmp_path: Path) -> None:
    _app()
    from app.main_window import MainWindow

    source = _write_wav(tmp_path / "ui.wav", seconds=2.0, sample_rate=8000)

    first = MainWindow()
    first.load_audio(source)
    first.region.setRegion((0.25, 1.25))
    first.trim_to_selection()
    assert first.edit_depth == 1
    payload = first._project_payload()
    trimmed = first.processed.copy()
    target = save_project(tmp_path / "ui.wavproj", payload)
    first.close()

    second = MainWindow()
    second.load_audio(source)
    second._apply_project(load_project(target))
    assert second.edit_depth == 1
    assert second.edit_log == ["trim"]
    assert second.processed.shape == trimmed.shape
    assert np.allclose(second.processed, trimmed, atol=1e-9)
    second.close()


def test_main_window_denoise_recipe_records_parameters(tmp_path: Path) -> None:
    _app()
    from app.main_window import MainWindow
    from core.denoise import DenoiseResult

    source = _write_wav(tmp_path / "dn.wav", seconds=1.0, sample_rate=8000)
    window = MainWindow()
    window.load_audio(source)
    window.threshold.setValue(7.5)
    window.max_repair.setValue(2.5)
    samples = window.processed[:, 0].copy()
    result = DenoiseResult(samples, [], np.ones(samples.shape[0], dtype=bool), 7.5, 0)
    window.pending_denoise_params = {"threshold": 7.5, "max_repair_ms": 2.5}
    window._commit_denoise(result, 0)
    payload = window._project_payload()
    assert payload["edits"] == [{
        "kind": "denoise",
        "params": {"threshold": 7.5, "max_repair_ms": 2.5, "channel": 0},
    }]
    window.close()


def test_project_buttons_exist(tmp_path: Path) -> None:
    _app()
    from app.main_window import MainWindow

    window = MainWindow()
    assert window.save_project_button.text().startswith("保存工程")
    assert window.open_project_button.text().startswith("打开工程")
    window.close()
