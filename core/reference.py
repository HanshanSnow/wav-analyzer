"""外部参考通道：读取、校验、并与目标做起点对齐。

规则（与界面/工程文件一致，改之前先读这段）：

* **单声道与多声道都接受**，但必须**显式指定声道**（0 基）。多声道文件里不同声道
  可能是不同位置/不同增益，静默取第 0 路会让重放不可复现，所以声道号必须一路写进
  `.wavproj` 与批量 JSON。
* **采样率必须一致**：不做重采样——重采样会改变相位与相干性，四个方法的前提就没了。
* **长度允许不同**：只处理"参考与目标的重叠段"，余下部分保持原样、并在报告里写明。
  但重叠段不得少于目标的 50%（且至少 256 点），否则参考不足以下结论。
* **起点必须对齐**：用互相关估计重叠段的延迟，超过 1 ms 视为"不是同一段录音"，
  报错并提示改用独立噪声画像（另一种方法，不要求样本对齐）。
* 不做补零、不做平铺、不做裁剪写入：任何"补出来"的参考都是伪造的对齐。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .audio_io import read_wav
from .i18n import tf, tr

# 起点容差：超过 1 ms 就认为两段录音没有对齐
MAX_LAG_SECONDS = 0.001
# 重叠段至少占目标的比例
MIN_OVERLAP_RATIO = 0.5
MIN_OVERLAP_SECONDS = 0.05


class ReferenceError(ValueError):
    """参考文件不满足使用条件；消息可直接展示给用户。"""


@dataclass(frozen=True)
class ExternalReference:
    path: Path
    samples: np.ndarray          # 单声道 float64
    sample_rate: int
    frames: int
    sha256: str
    channel: int = 0             # 0 基；必须随工程/批量一起保存
    channels: int = 1            # 文件里实际有多少个声道
    size: int = 0                # 文件字节数：与 mtime_ns 一起构成"身份"
    mtime_ns: int = 0

    @property
    def identity(self) -> tuple[int, int]:
        """文件身份：字节数 + 修改时间。变了就说明文件被替换过。"""
        return (int(self.size), int(self.mtime_ns))

    def as_row(self) -> dict:
        return {
            "kind": "external",
            "path": str(self.path),
            "sha256": self.sha256,
            "sample_rate": self.sample_rate,
            "frames": self.frames,
            "channel": self.channel,
            "channels": self.channels,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
        }


def file_sha256(path: str | Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def file_identity(path: str | Path) -> tuple[int, int]:
    """(字节数, 修改时间 ns)：轻量、不读内容，用来判断"还是不是同一个文件"。"""
    try:
        stat = Path(path).stat()
    except OSError:
        return (0, 0)
    return (int(stat.st_size), int(stat.st_mtime_ns))


class ReferenceCache:
    """参考校验结果的小缓存：按路径+声道+采样率+文件身份命中。

    用途是避免"对话框校验一次、保存工程再哈希一次、批量每个文件再读一次"。
    身份（大小+mtime）一变就自动失效，不会让替换过的文件沿用旧结论。
    """

    def __init__(self, max_items: int = 4) -> None:
        self._items: dict[tuple, ExternalReference] = {}
        self._order: list[tuple] = []
        self._max = max(1, int(max_items))

    def _key(self, path, channel, sample_rate, identity) -> tuple:
        return (str(path), int(channel), int(sample_rate), identity)

    def get(self, path, *, channel: int = 0, sample_rate: int = 0):
        key = self._key(path, channel, sample_rate, file_identity(path))
        return self._items.get(key)

    def put(self, reference: ExternalReference) -> None:
        key = self._key(reference.path, reference.channel,
                        reference.sample_rate, reference.identity)
        if key not in self._items:
            self._order.append(key)
        self._items[key] = reference
        while len(self._order) > self._max:
            self._items.pop(self._order.pop(0), None)

    def clear(self) -> None:
        self._items.clear()
        self._order.clear()


# 进程级共享缓存：界面线程与批量/工作线程都读它，只做 dict 操作，开销可忽略。
REFERENCE_CACHE = ReferenceCache()


def load_reference(path: str | Path, *, sample_rate: int, channel: int = 0,
                   frames: int | None = None) -> ExternalReference:
    """读取并校验参考文件；只做与"能否使用"直接相关的检查。

    `frames` 只用于给出更具体的提示，不再强制等长（长度差异交给 align_reference）。
    """
    target = Path(path)
    if not target.is_file():
        raise ReferenceError(tf("参考文件不存在：{_v0}", _v0=(str(target))))
    try:
        audio = read_wav(str(target))
    except Exception as exc:  # noqa: BLE001 - 把底层错误换成可读提示
        raise ReferenceError(tf("参考文件读不出来：{_v0}", _v0=(str(exc)))) from exc

    channels = int(audio.channels)
    if not 0 <= int(channel) < channels:
        raise ReferenceError(tf("参考文件有 {_v0} 个声道，选不了第 {_v1} 路（从 1 数）。",
                                _v0=(channels), _v1=(int(channel) + 1)))
    if int(audio.sample_rate) != int(sample_rate):
        raise ReferenceError(tf("参考文件采样率是 {_v0} Hz，目标是 {_v1} Hz；"
                                "v1 不做自动重采样，请提供同采样率的文件。",
                                _v0=(int(audio.sample_rate)), _v1=(int(sample_rate))))

    data = np.asarray(audio.samples, dtype=np.float64)
    data = data if data.ndim == 1 else data[:, int(channel)]
    data = data.reshape(-1)
    if data.size < 256:
        raise ReferenceError(tf("参考文件太短（{_v0} 点），至少需要 256 点。", _v0=(data.size)))
    if not np.all(np.isfinite(data)):
        raise ReferenceError(tr("参考文件里有非有限值（NaN/Inf）。"))
    if not np.any(data):
        raise ReferenceError(tr("参考音频全为零（静音），无法作为参考。"))

    size, mtime_ns = file_identity(target)
    return ExternalReference(target, data, int(audio.sample_rate), int(data.size),
                             file_sha256(target), int(channel), channels,
                             size=size, mtime_ns=mtime_ns)


def load_reference_cached(path: str | Path, *, sample_rate: int, channel: int = 0,
                          cache: "ReferenceCache | None" = None) -> ExternalReference:
    """带缓存的 `load_reference`：文件身份不变时不再重复解码与哈希。"""
    store = cache if cache is not None else REFERENCE_CACHE
    hit = store.get(path, channel=channel, sample_rate=sample_rate)
    if hit is not None:
        return hit
    reference = load_reference(path, sample_rate=sample_rate, channel=channel)
    store.put(reference)
    return reference


def _best_lag(reference: np.ndarray, target: np.ndarray, sample_rate: int,
              probe_seconds: float = 2.0) -> int:
    """估计 reference 相对 target 的延迟（采样点，正数表示参考滞后）。"""
    from scipy import signal as sps

    probe = int(min(reference.size, target.size, max(256, probe_seconds * sample_rate)))
    a = reference[:probe] - float(np.mean(reference[:probe]))
    b = target[:probe] - float(np.mean(target[:probe]))
    if not np.any(a) or not np.any(b):
        return 0
    correlation = sps.correlate(b, a, mode="full", method="fft")
    lags = sps.correlation_lags(b.size, a.size, mode="full")
    return int(lags[int(np.argmax(np.abs(correlation)))])


def align_reference(reference: np.ndarray, target: np.ndarray,
                    sample_rate: int) -> tuple[np.ndarray, dict]:
    """把参考对齐到目标：返回可用于分帧的参考切片与对齐信息。

    只取重叠段；起点延迟超过 1 ms 直接拒绝（那是"另一次录音"，属于独立噪声画像）。
    """
    ref = np.asarray(reference, dtype=np.float64).reshape(-1)
    tgt = np.asarray(target, dtype=np.float64).reshape(-1)
    overlap = int(min(ref.size, tgt.size))
    minimum = int(max(256, MIN_OVERLAP_SECONDS * sample_rate,
                      MIN_OVERLAP_RATIO * tgt.size))
    if overlap < minimum:
        raise ReferenceError(tf("参考与目标只重叠 {_v0} 点，少于要求的 {_v1} 点"
                                "（至少占目标的 {_v2:.0%}）。",
                                _v0=(overlap), _v1=(minimum), _v2=(MIN_OVERLAP_RATIO)))

    lag = _best_lag(ref, tgt, sample_rate)
    tolerance = max(1, int(round(MAX_LAG_SECONDS * sample_rate)))
    if abs(lag) > tolerance:
        raise ReferenceError(tf("参考与目标的起点相差约 {_v0} 个采样点（超过 {_v1} ms）："
                                "这两段可能不是同一次录音。请换用独立噪声画像，它不要求样本对齐。",
                                _v0=(lag), _v1=(MAX_LAG_SECONDS * 1000)))

    info = {
        "overlap_frames": overlap,
        "target_frames": int(tgt.size),
        "reference_frames": int(ref.size),
        "lag_samples": lag,
        # 余下多少点没有参考可用（保持原样，报告里要写）
        "unprocessed_frames": int(max(0, tgt.size - overlap)),
        "channel": None,
    }
    return ref[:overlap], info
