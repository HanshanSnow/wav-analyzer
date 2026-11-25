"""声学校准：把数字满幅（FS/dBFS）换算成声压级（dB SPL）。

核心只有一条式子。设

    V_adc,rms  声卡输入的 RMS 电压（V）
    V_fs       0 dBFS 对应的输入电压（Vrms），即 ADC 满幅参考
    G          前置增益（线性倍数，G = 10^(G_dB/20)）
    S          麦克风灵敏度（V/Pa）
    p_ref      参考声压 20 µPa

则

    V_adc,rms = V_fs · 10^(L_dBFS/20)
    p_rms     = V_adc,rms / (G · S)
    L_SPL     = 20·lg(p_rms / p_ref)
              = L_dBFS + 20·lg( V_fs / (G · S · p_ref) )

括号里那一项就是个常数偏移 K，单位 dB。于是全部换算退化成一次加法：

    L_SPL = L_dBFS + K

K 有两种来路，二者等效，本模块都支持：

1. **参数推算**（知道硬件参数时）：给 S（mV/Pa）、G（dB）、V_fs（Vrms）。
   注意 S 用 mV/Pa 输入，内部换算成 V/Pa，所以 K 的表达式里多一个 1000：

       K = 20·lg( V_fs · 1000 / (G_lin · S_mV · 20e-6) )

   例：S = 10 mV/Pa、G = 0 dB、V_fs = 1 Vrms → K = 133.98 dB。
   验算：94 dB SPL（1 Pa）时麦克风出 10 mV，相对 1 Vrms 即 −40 dBFS，
   −40 + 133.98 = 93.98 ≈ 94 dB SPL。

2. **两点标定**（有已知声压级的声源时，更可靠）：把声源开到某个已知值 L_ref，
   读出对应的 dBFS，则 K = L_ref − L_dBFS。这条路不需要知道 V_fs——
   而 V_fs 恰恰是民用声卡最不可靠的参数（消费级 USB 声卡常见 1 Vrms，
   专业设备可能是 0.775 Vrms 或 +4 dBu = 1.228 Vrms，驱动里还不一定告诉）。

**不适用的情况**（必须让用户知道，否则算出来的数是错的）：

- 麦克风或模块带 AGC/ALC（如 MAX9814、多数 USB 会议麦）：增益随声压自动变化，
  同一个 K 不成立，单点标定也没有意义。
- 录音已经削顶：削顶后 dBFS 被压平，反推的声压级系统性偏低。
- 数字增益（软件增益、系统录音音量）不是 0 dB：等效于给 G 多加了一项，
  必须把这一项算进去或固定在 0。
"""

from __future__ import annotations

from core.i18n import tf, tr
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any

# 参考声压 20 µPa。空气中的 dB SPL 定义基准。
P_REF_PA = 20e-6

# 换算成 K 之后，dBFS 的可用下限：低于它反推的声压级没有意义（只是数值噪声）。
MIN_DBFS = -140.0

MODE_PARAMS = "params"
MODE_REFERENCE = "reference"
MODE_LABELS = {
    MODE_PARAMS: tr("按硬件参数推算"),
    MODE_REFERENCE: tr("按已知声压级标定"),
}


@dataclass
class Calibration:
    """一组「麦克风 + 前置增益」的校准。offset_db 是缓存出来的 K。"""

    name: str = tr("默认校准")
    mode: str = MODE_PARAMS

    # 参数推算用
    sensitivity_mv_pa: float | None = None
    preamp_gain_db: float = 0.0
    adc_full_scale_vrms: float = 1.0

    # 两点标定用
    ref_spl_db: float | None = None
    ref_dbfs: float | None = None

    note: str = ""
    _offset: float | None = field(default=None, repr=False, compare=False)

    # ------------------------------------------------------------ 计算
    def offset_db(self) -> float | None:
        """K：dBFS → dB SPL 的加性偏移。参数不全或非有限值时返回 None。"""
        if self._offset is not None:
            return self._offset
        if self.mode == MODE_REFERENCE:
            if self.ref_spl_db is None or self.ref_dbfs is None:
                return None
            if not (math.isfinite(float(self.ref_spl_db)) and math.isfinite(float(self.ref_dbfs))):
                return None
            return float(self.ref_spl_db) - float(self.ref_dbfs)
        # 手工编辑或损坏的配置文件可能塞进 1e400（解析成 inf）或 nan：
        # 这类值一旦进入 log10 就抛 math domain error，必须先挡掉（BUG-018）。
        if self.sensitivity_mv_pa is None:
            return None
        if not math.isfinite(float(self.sensitivity_mv_pa)) or float(self.sensitivity_mv_pa) <= 0:
            return None
        if not math.isfinite(float(self.preamp_gain_db)):
            return None
        if not math.isfinite(float(self.adc_full_scale_vrms)):
            return None
        gain_linear = 10.0 ** (float(self.preamp_gain_db) / 20.0)
        full_scale = float(self.adc_full_scale_vrms)
        if not math.isfinite(gain_linear) or gain_linear <= 0 or full_scale <= 0:
            return None
        # S 以 mV/Pa 给出，乘 1000 换成 V/Pa 的倒数关系
        offset = 20.0 * math.log10(full_scale * 1000.0 / (gain_linear * self.sensitivity_mv_pa * P_REF_PA))
        return offset if math.isfinite(offset) else None

    @property
    def ready(self) -> bool:
        return self.offset_db() is not None

    def spl(self, dbfs: float) -> float:
        """dBFS → dB SPL。未校准时抛 ValueError，避免静默给出假声压级。"""
        offset = self.offset_db()
        if offset is None:
            raise ValueError(tr("校准参数不完整，无法换算声压级"))
        return float(dbfs) + offset

    def dbfs(self, spl_db: float) -> float:
        """dB SPL → dBFS，用于反推「这个声压级应该录到多少」。"""
        offset = self.offset_db()
        if offset is None:
            raise ValueError(tr("校准参数不完整，无法换算声压级"))
        return float(spl_db) - offset

    def sensitivity_v_pa(self) -> float | None:
        if self.sensitivity_mv_pa is None:
            return None
        return float(self.sensitivity_mv_pa) / 1000.0

    def gain_linear(self) -> float:
        return 10.0 ** (float(self.preamp_gain_db) / 20.0)

    def summary(self) -> str:
        """一行摘要，界面上直接显示。"""
        offset = self.offset_db()
        if offset is None:
            return tf('{_v0}：参数不完整', _v0=(self.name))
        if self.mode == MODE_REFERENCE:
            return (f"{self.name}：K = {offset:+.2f} dB"
                    f"（{self.ref_spl_db:.1f} dB SPL ↔ {self.ref_dbfs:+.2f} dBFS）")
        return (tf('{_v0}：K = {offset:+.2f} dB（{_v2:g} mV/Pa，增益 {_v3:+.1f} dB，满幅 {_v4:g} Vrms）', _v0=(self.name), offset=(offset), _v2=(self.sensitivity_mv_pa), _v3=(self.preamp_gain_db), _v4=(self.adc_full_scale_vrms)))

    def caveats(self) -> list[str]:
        """必须随结果一起显示的限定条件。空列表表示没有额外风险。"""
        notes: list[str] = []
        if self.mode == MODE_PARAMS:
            notes.append(tr("满幅电压取标称值，与声卡实际参考电压可能有偏差；有条件时改用已知声压级标定"))
        notes.append(tr("若麦克风或模块带 AGC/ALC，增益随声压自动变化，本校准不成立"))
        notes.append(tr("削顶录音反推的声压级偏低，需先排除削顶"))
        if abs(float(self.preamp_gain_db)) > 60.0:
            notes.append(tr("前置增益超过 60 dB，请确认数值口径（是放大倍数还是 dB）"))
        return notes

    # ------------------------------------------------------------ 校验
    def validate(self) -> None:
        """保存前检查，错误信息直接面向用户。"""
        if not self.name.strip():
            raise ValueError(tr("请填写校准名称（例如「电容麦 无增益」）"))
        if self.mode == MODE_REFERENCE:
            if self.ref_spl_db is None or self.ref_dbfs is None:
                raise ValueError(tr("两点标定需要同时填写已知声压级与对应的 dBFS 读数"))
            if not -20.0 <= float(self.ref_spl_db) <= 180.0:
                raise ValueError(tr("已知声压级应在 −20 ～ 180 dB SPL 之间"))
            if not MIN_DBFS <= float(self.ref_dbfs) <= 0.0:
                raise ValueError(tf('dBFS 读数应在 {MIN_DBFS:.0f} ～ 0 之间（削顶时等于 0）', MIN_DBFS=(MIN_DBFS)))
            return
        if self.sensitivity_mv_pa is None or self.sensitivity_mv_pa <= 0:
            raise ValueError(tr("请填写麦克风灵敏度（mV/Pa，常见电容麦 5–50，驻极体 5–20）"))
        if not -20.0 <= float(self.preamp_gain_db) <= 120.0:
            raise ValueError(tr("前置增益应在 −20 ～ 120 dB 之间"))
        if not 0.01 <= float(self.adc_full_scale_vrms) <= 20.0:
            raise ValueError(tr("满幅输入电压应在 0.01 ～ 20 Vrms 之间"))

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("_offset", None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Calibration":
        known = {f for f in cls.__dataclass_fields__ if not f.startswith("_")}
        payload = {k: v for k, v in (data or {}).items() if k in known}
        calibration = cls(**payload)
        if calibration.mode not in (MODE_PARAMS, MODE_REFERENCE):
            calibration.mode = MODE_PARAMS
        return calibration


# ---------------------------------------------------------------- 配置集合
def dumps_profiles(profiles: list[Calibration], active: str = "") -> str:
    return json.dumps(
        {"version": 1, "active": active, "profiles": [item.to_dict() for item in profiles]},
        ensure_ascii=False, indent=2)


def loads_profiles(text: str) -> tuple[list[Calibration], str]:
    """容错读取：文件坏了就返回空列表，不让程序启动失败。"""
    if not text or not text.strip():
        return [], ""
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return [], ""
    raw = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return [], ""
    profiles: list[Calibration] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                profiles.append(Calibration.from_dict(item))
            except (TypeError, ValueError):
                continue
    active = payload.get("active") if isinstance(payload, dict) else ""
    return profiles, active if isinstance(active, str) else ""


def find_profile(profiles: list[Calibration], name: str) -> Calibration | None:
    for item in profiles:
        if item.name == name:
            return item
    return None
