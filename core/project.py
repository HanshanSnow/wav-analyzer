"""工程文件（``.wavproj``）：只存配方，不存结果。

设计取舍见 ``PlanForVersion2.0.md`` §3.11：

* 不序列化处理后的采样数据（48 kHz × 5 分钟约 115 MB，且与源 WAV 重复），
  只存「源文件 + 可重放的操作序列」；载入后重算频谱、包络与统计。
* 操作序列里的 ``kind`` 与批量 ``STEP_SPECS`` 对齐：``denoise`` /
  ``denoise_tools`` / ``trim``，不另造词汇。
* JSON 的键与 ``kind`` 名字保持英文（文件可被脚本读取），界面提示走
  :func:`tr` / :func:`tf`。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .i18n import tf, tr

PROJECT_FORMAT = "wav-analyzer-project"
PROJECT_VERSION = 1
PROJECT_SUFFIX = ".wavproj"

_HASH_CHUNK = 1 << 20


def file_sha256(path: str | Path) -> str:
    """分块计算 SHA-256，避免把长录音整个读进内存。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _clean_edits(items: Any) -> list[dict[str, Any]]:
    """只保留形如 ``{"kind": str, "params": dict}`` 的条目，其余静默丢弃。"""
    clean: list[dict[str, Any]] = []
    if not isinstance(items, (list, tuple)):
        return clean
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if not isinstance(kind, str) or not kind:
            continue
        params = item.get("params")
        clean.append({"kind": kind, "params": dict(params) if isinstance(params, dict) else {}})
    return clean


def build_project(
    source_path: str | Path,
    *,
    sample_rate: int,
    channels: int,
    frames: int,
    channel: int = 0,
    edits: list[dict[str, Any]] | None = None,
    selection: tuple[float, float] | None = None,
    calibration: dict[str, Any] | None = None,
    analysis: dict[str, Any] | None = None,
    export: dict[str, Any] | None = None,
    reference: dict[str, Any] | None = None,
    created: str | None = None,
) -> dict[str, Any]:
    """组装工程字典。``edits`` 里每项是 ``{"kind": str, "params": dict}``。"""
    source = Path(source_path)
    absolute = str(source.resolve()) if source.exists() else str(source)
    try:
        digest = file_sha256(source) if source.exists() else ""
    except OSError:
        digest = ""
    project: dict[str, Any] = {
        "format": PROJECT_FORMAT,
        "version": PROJECT_VERSION,
        "created": created or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": {
            "path": absolute,
            "relative_path": source.name,
            "sha256": digest,
            "sample_rate": int(sample_rate),
            "channels": int(channels),
            "frames": int(frames),
        },
        "channel": int(channel),
        "edits": _clean_edits(edits),
        "selection": list(selection) if selection else None,
        "calibration": dict(calibration or {}),
        "analysis": dict(analysis or {}),
        "export": dict(export or {}),
    }
    # 外部参考通道：路径 + 声道号 + 哈希。只在真的有参考时写入，
    # 这样没有参考的工程文件结构保持不变（旧文件不需要迁移）。
    if reference:
        project["reference"] = dict(reference)
    return project


def dump_project(project: dict[str, Any]) -> str:
    return json.dumps(project, ensure_ascii=False, indent=2) + "\n"


def save_project(path: str | Path, project: dict[str, Any]) -> Path:
    target = Path(path)
    if target.suffix.lower() != PROJECT_SUFFIX:
        target = target.with_suffix(PROJECT_SUFFIX)
    target.write_text(dump_project(project), encoding="utf-8", newline="\n")
    return target


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_project(path: str | Path) -> dict[str, Any]:
    """读入并做最小校验；未知字段忽略，缺失字段补默认值。

    坏文件抛 :class:`ValueError`，文案已经是给界面直接显示的中文。
    """
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(tf("读不了工程文件：{_v0}", _v0=(exc,))) from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(tf("工程文件不是有效的 JSON：{_v0}", _v0=(exc.msg,))) from exc
    _require(isinstance(raw, dict), tr("工程文件内容不是对象"))
    _require(raw.get("format") == PROJECT_FORMAT,
             tf("这不是本程序的工程文件（format={_v0}）", _v0=(raw.get("format"),)))
    version = raw.get("version")
    _require(isinstance(version, int) and version >= 1,
             tf("工程文件版本号不对：{_v0}", _v0=(version,)))
    _require(version <= PROJECT_VERSION,
             tf("工程文件由更新版本保存（v{_v0}），请先升级程序",
                _v0=(version,)))

    source_block = raw.get("source")
    _require(isinstance(source_block, dict) and bool(source_block.get("path")),
             tr("工程文件里没有记录源文件"))

    clean = _clean_edits(raw.get("edits"))

    return {
        "format": PROJECT_FORMAT,
        "version": int(version),
        "created": str(raw.get("created") or ""),
        "source": {
            "path": str(source_block.get("path") or ""),
            "relative_path": str(source_block.get("relative_path") or ""),
            "sha256": str(source_block.get("sha256") or ""),
            "sample_rate": int(source_block.get("sample_rate") or 0),
            "channels": int(source_block.get("channels") or 0),
            "frames": int(source_block.get("frames") or 0),
        },
        "channel": int(raw.get("channel") or 0),
        "edits": clean,
        "selection": raw.get("selection") if isinstance(raw.get("selection"), list) else None,
        "calibration": dict(raw.get("calibration") or {}),
        "analysis": dict(raw.get("analysis") or {}),
        "export": dict(raw.get("export") or {}),
    }


def source_path_of(project: dict[str, Any], project_dir: str | Path) -> Path | None:
    """先按绝对路径找，再按工程文件旁边的相对路径找；都没有返回 ``None``。"""
    block = project.get("source") or {}
    absolute = block.get("path") or ""
    if absolute:
        candidate = Path(str(absolute))
        if candidate.is_file():
            return candidate
    relative = block.get("relative_path") or ""
    if relative:
        candidate = Path(project_dir) / relative
        if candidate.is_file():
            return candidate
    return None


def verify_source(project: dict[str, Any], path: str | Path) -> str | None:
    """校验源文件哈希；一致返回 ``None``，否则返回给界面显示的原因。"""
    expected = str((project.get("source") or {}).get("sha256") or "")
    if not expected:
        return None
    try:
        actual = file_sha256(path)
    except OSError as exc:
        return tf("读不了源文件：{_v0}", _v0=(exc,))
    if actual != expected:
        return tr("源文件已经变了（哈希不符）：工程里记录的处理过程不再对应这份音频。"
                  "请确认是否仍要载入。")
    return None
