"""报告语言（导出报告用），与界面语言解耦。

为什么单独一份词典，而不是塞进 `core/i18n_en.py`：

* `core/i18n.py` 的键是界面文案，切换界面语言会连带换掉报告用词；
  报告是给人存档、放进实验记录本的，语言应当由用户单独决定；
* 报告里有一批只在文件里出现的说明文字（列定义、导出约定、图注），
  它们进了界面词典反而永远「不被引用」，i18n 工具会报过期条目。

翻译查表顺序：`REPORT_EN` → `core/i18n_en.EN` → 原文。第二级是为了复用
统计量释义那 60 多条已经翻好的文案，避免同一句话维护两份译文。

模板占位符一律用 `{_v0}` / `{_v1}`（与 `core/i18n.py` 的 `tf` 一致），
英文条目必须使用同名占位符，`tests/test_report_i18n.py` 会逐个核对。
"""

from __future__ import annotations

import io
from pathlib import Path

from core.i18n import LANG_ZH, current_language

REPORT_AUTO = "auto"
REPORT_ZH = "zh"
REPORT_EN = "en"

REPORT_LANGUAGES: tuple[tuple[str, str], ...] = (
    (REPORT_AUTO, "跟随界面"),
    (REPORT_ZH, "中文"),
    (REPORT_EN, "English"),
)
DEFAULT_REPORT_LANGUAGE = REPORT_AUTO

_report_language = DEFAULT_REPORT_LANGUAGE
_english: dict[str, str] | None = None
_MERGED: dict[str, str] = {}


# ---------------------------------------------------------------- 词典
#
# 只放「报告里出现、界面上不出现」的文案。界面词典里已有的（统计量释义、
# 窗名等）不要再抄一遍——查表时会自动回落到 core/i18n_en.EN。
REPORT_EN_TEXT: dict[str, str] = {
    # 头部与章节名
    "声音实验 WAV 数据处理程序 — 分析数据导出": "Acoustic WAV Data Processor — Analysis Data Export",
    "包络方程及参数": "Envelope equation and parameters",
    "傅里叶分析": "Fourier analysis",
    "区间统计": "Interval statistics",
    "双通道分析": "Dual-channel analysis",
    "AI 说明": "AI note",
    "去噪记录": "Denoise log",
    "原坐标（波形采样数据，长表）": "Raw coordinates (waveform samples, long table)",
    "导出说明": "Export notes",
    "全文件": "Full file",
    "蓝框选区": "Blue selection",
    "自定义区间": "Custom interval",
    # 注释行键名
    "导出时间": "Export time",
    "数据版本": "Data version",
    "源文件": "Source file",
    "完整路径": "Full path",
    "采样率": "Sample rate",
    "声道数": "Channels",
    "采样格式": "Sample format",
    "总采样点": "Total samples",
    "时长": "Duration",
    "文件大小": "File size",
    "编辑次数": "Edits",
    "文件指纹": "File fingerprint",
    "声学校准": "Acoustic calibration",
    "限定": "Limits",
    "坐标取法": "Coordinate sampling",
    "编码": "Encoding",
    "列对齐": "Column alignment",
    "导入": "Import",
    "注释": "Comments",
    "单位": "Units",
    "空值": "Empty values",
    "状态": "Status",
    "说明": "Note",
    "原因": "Reason",
    "选区": "Selection",
    "提取方法": "Extraction method",
    "拟合模型": "Fit model",
    "拟合方程": "Fit equation",
    "自变域": "Domain",
    "参数表列定义": "Parameter columns",
    "分析数据段": "Analysis segment",
    "实际参与点数": "Samples used",
    "频率分辨率": "Frequency resolution",
    "统计范围": "Statistics scope",
    "双声道可用内容": "Available for stereo files",
    "激励频率": "Excitation frequency",
    "互相关时延": "Cross-correlation delay",
    "峰值质量": "Peak quality",
    "搜索窗口": "Search window",
    "参考声道电平": "Reference channel level",
    "接收声道电平": "Received channel level",
    "电平差": "Level difference",
    "警告": "Warning",
    "检测参数": "Detection parameters",
    "检测事件": "Detected events",
    "修复后总点数": "Samples after repair",
    "列定义": "Columns",
    # 注释行键值分隔符：中文用全角冒号，英文用冒号加空格
    "{_v0}：{_v1}": "{_v0}: {_v1}",
    # 状态类取值
    "未计算": "not computed",
    "未执行": "not run",
    "无记录": "no record",
    "未生成": "not generated",
    "跳过": "skipped",
    "不可用": "unavailable",
    "无": "none",
    "未知": "unknown",
    "单声道": "mono",
    "双声道": "stereo",
    "插值修复": "interpolated",
    "标记排除": "flagged",
    # 说明性长句
    "先在“包络分析”页对选区做一次拟合，再导出本段":
        "Fit the envelope for the selection on the “Envelope” tab, then export this section.",
    "不适用（常数模型没有相对方差基准）":
        "n/a (a constant model has no relative-variance baseline)",
    "Hilbert 解析信号模值（单边包络）":
        "magnitude of the Hilbert analytic signal (one-sided envelope)",
    "idx 序号  sym 符号  value 数值  unit 单位":
        "idx index  sym symbol  value value  unit unit",
    "包络抽样（约 24 行，便于作图核对）":
        "envelope samples (about 24 rows, for plotting checks)",
    "列定义：t/s 绝对时间  env/FS 包络  fit/FS 拟合值  resid/FS 残差":
        "columns: t/s absolute time  env/FS envelope  fit/FS fitted  resid/FS residual",
    "主要谱峰（按幅值降序）": "Main spectral peaks (amplitude, descending)",
    "列定义：idx 序号  f/Hz 频率  A/FS 幅值  L/dBFS 电平  phi/rad 相位  rel/dB 相对基波电平":
        "columns: idx index  f/Hz frequency  A/FS amplitude  L/dBFS level  "
        "phi/rad phase  rel/dB level relative to fundamental",
    "谐波成分（基频整数倍）": "Harmonic components (integer multiples of the fundamental)",
    "列定义：n 次数  ft/Hz 理论频率  fm/Hz 实测频率  A/FS 幅值  L/dBFS 电平  rel/dB 相对基波":
        "columns: n order  ft/Hz theoretical  fm/Hz measured  A/FS amplitude  "
        "L/dBFS level  rel/dB relative to fundamental",
    "完整谱表（0 – 奈奎斯特，频率升序），每 {_v0} 个频点取 1 行，完整导出含 {_v1} 行":
        "Full spectrum (0 – Nyquist, ascending), 1 row every {_v0} bins, "
        "{_v1} rows in a full export",
    "列定义：f/Hz 频率  A/FS 幅值  L/dBFS 电平  phi/rad 相位":
        "columns: f/Hz frequency  A/FS amplitude  L/dBFS level  phi/rad phase",
    "列定义：idx 序号  key 键名  value 数值  name 中文统计量名":
        "columns: idx index  key key  value value  name statistic name",
    "统计量释义": "Statistic definitions",
    "实际导出按勾选范围输出，未勾选的范围不写入本文件":
        "only the checked scopes are written; unchecked scopes are omitted",
    "当前没有有效的蓝色选区": "there is no valid blue selection",
    "未指定有效的自定义区间": "no valid custom interval was given",
    "区间超出音频范围": "the interval is outside the audio range",
    "[{_v0}.{_v1}] {_v2}统计": "[{_v0}.{_v1}] {_v2} statistics",
    "当前 WAV 为单声道，双通道分析需要左（参考）/右（接收）两路信号":
        "the file is mono; dual-channel analysis needs left (reference) and right (received)",
    "互相关时延、峰值质量、搜索窗口、两路电平与电平差、AGC 风险提示":
        "cross-correlation delay, peak quality, search window, both levels and their "
        "difference, AGC warning",
    "点了“双通道时延与电平分析”之后再导出，本段才有数值":
        "Run “Dual-channel delay and level” before exporting; this section then has values.",
    "尚未应用冲击去噪；本段只在修改后数据上出现":
        "No impulse denoising was applied; this section appears only for edited data.",
    "本次导出未包含 AI 说明；在 AI 助手里让它分析后再导出即可写入本段":
        "This export has no AI note; ask the assistant to analyse the data and export again.",
    "未配置；本报告只含 dBFS，不含 dB SPL":
        "not configured; this report contains dBFS only, no dB SPL",
    # 动态取值模板
    "{_v0} Hz": "{_v0} Hz",
    "{_v0:.6f} – {_v1:.6f} s，长 {_v2:.6f} s": "{_v0:.6f} – {_v1:.6f} s, length {_v2:.6f} s",
    "{_v0:.6f} – {_v1:.6f} s（相对选区起点）":
        "{_v0:.6f} – {_v1:.6f} s (relative to the selection start)",
    "{_v0:,}（总点数 {_v1:,}）": "{_v0:,} (of {_v1:,} total)",
    "{_v0}（{_v1}）": "{_v0} ({_v1})",
    "{_v0} 次（去噪 {_v1} 次，裁剪 {_v2} 次）":
        "{_v0} edits (denoise {_v1}, trim {_v2})",
    "MD5 {_v0}（源 WAV 前 256 MB 的 MD5 前 16 位，用于核对本份导出与原始录音是否对应）":
        "MD5 {_v0} (first 16 hex digits of the MD5 of the first 256 MB of the source WAV, "
        "to check this export against the original recording)",
    "{_v0}；K = {_v1:+.2f} dB（dB SPL = dBFS + K）":
        "{_v0}; K = {_v1:+.2f} dB (dB SPL = dBFS + K)",
    "  限定：{_v0}": "#   limits: {_v0}",
    "UTF-8（含 BOM，Excel 双击不乱码）": "UTF-8 with BOM (opens cleanly in Excel)",
    "定宽空格对齐；除末列外只含 ASCII，任何等宽字体下逐列对齐，中文只在末列或 # 注释行":
        "fixed-width space alignment; all but the last column are ASCII, so columns line up "
        "in any monospace font; Chinese appears only in the last column or # comments",
    'pandas.read_csv(sep=r"\\s+", comment="#")；Excel 用「数据-分列-固定宽度」；Origin 选空格分隔':
        'pandas.read_csv(sep=r"\\s+", comment="#"); in Excel use Data > Text to Columns > '
        "Fixed width; in Origin choose space-delimited",
    "以 # 开头的行为说明，不含数据，可按需忽略":
        "lines starting with # are notes, not data, and can be ignored",
    "FS = 数字满幅归一化幅值；dBFS = 20lg(|x|/FS)；dBFS 不等于声压级 dB SPL":
        "FS = full-scale normalised amplitude; dBFS = 20lg(|x|/FS); dBFS is not dB SPL",
    "-inf 表示该点幅值为 0，对数无定义；nan 表示该量在本数据上不可计算":
        "-inf means the amplitude is 0 and the logarithm is undefined; "
        "nan means the quantity cannot be computed for this data",
    "本文件坐标表步长 {_v0} 点（约 {_v1:.1f} 行/秒）":
        "coordinate table stride {_v0} samples (about {_v1:.1f} rows/s)",
    "列定义：t/s 时间（秒）  x/FS 幅值（满幅归一化）  L/dBFS 电平 20lg|x|":
        "columns: t/s time (s)  x/FS full-scale amplitude  L/dBFS level 20lg|x|",
    "采样点总数 {_v0:,}，抽样步长 {_v1}（约每 {_v1} 点取 1 点），共 {_v2:,} 行":
        "{_v0:,} samples in total, stride {_v1} (1 of every {_v1} samples), {_v2:,} rows",
    "稳健阈值 {_v0:g} × 尺度；估算尺度用 {_v1:,} 点":
        "robust threshold {_v0:g} × scale; scale estimated from {_v1:,} samples",
    "{_v0} 段": "{_v0} segments",
    "idx 序号  t1/s 起点  t2/s 终点  len/ms 长度  dev/FS 峰值偏差  action 处理方式":
        "idx index  t1/s start  t2/s end  len/ms length  dev/FS peak deviation  action",
    "正在写 {_v0}": "writing {_v0}",
    "正在写导出说明": "writing export notes",
    "源文件（未修改）": "Source (unmodified)",
    "采样点不足，无法导出分析数据": "not enough samples to export analysis data",
    "至少选择一个导出章节": "select at least one section to export",
    "分析{_v0}": "analysis {_v0}",
    "修改分析": "edited analysis",
    "源文件分析": "source analysis",
    "声道{_v0}": "channel {_v0}",
}

# 报告语言显示名（英文界面里也保持原样，方便用户按语言找）
#
# HTML 报告与图注的文案：这些串只在文件里出现，界面词典里没有。
REPORT_EN_TEXT.update({
    "包络抽样（约 24 行，便于作图核对）": "Envelope samples (about 24 rows, for plotting checks)",
    "列定义：t/s 绝对时间  env/FS 包络  fit/FS 拟合值  resid/FS 残差": "Columns: t/s absolute time  env/FS envelope  fit/FS fitted  resid/FS residual",
    "窗函数": "Window function",
    "FFT 点数": "FFT length",
    "主频": "Main frequency",
    "主频幅值": "Main amplitude",
    "主频电平": "Main level",
    "基频": "Fundamental",
    "总谐波失真": "Total harmonic distortion",
    "列定义：idx 序号  f/Hz 频率  A/FS 幅值  L/dBFS 电平  phi/rad 相位  rel/dB 相对基波电平": "Columns: idx index  f/Hz frequency  A/FS amplitude  L/dBFS level  phi/rad phase  rel/dB level relative to the fundamental",
    "列定义：n 次数  ft/Hz 理论频率  fm/Hz 实测频率  A/FS 幅值  L/dBFS 电平  rel/dB 相对基波": "Columns: n order  ft/Hz theoretical frequency  fm/Hz measured frequency  A/FS amplitude  L/dBFS level  rel/dB relative to the fundamental",
    "列定义：f/Hz 频率  A/FS 幅值  L/dBFS 电平  phi/rad 相位": "Columns: f/Hz frequency  A/FS amplitude  L/dBFS level  phi/rad phase",
    "列定义：idx 序号  key 键名  value 数值  name 统计量名": "Columns: idx index  key  value  name",
    "列定义：t/s 时间（秒）  x/FS 幅值（满幅归一化）  L/dBFS 电平 20lg|x|": "Columns: t/s time (s)  x/FS amplitude (full-scale normalised)  L/dBFS level 20lg|x|",
    "实际导出按勾选范围输出，未勾选的范围不写入本文件": "Only the checked scopes are exported; unchecked scopes are left out of this file",
    "包络与时间轴长度不一致：{_v0} vs {_v1}": "Envelope and time axis lengths differ: {_v0} vs {_v1}",
    "没有可导出的数据": "nothing to export",
    "波形": "Waveform",
    "包络": "Envelope",
    "当前波形": "Current waveform",
    "原始波形": "Original waveform",
    "去噪预览": "Denoise preview",
    "拟合曲线": "Fitted curve",
    "选区": "Selection",
    "游标": "Cursor",
    "振幅谱": "Amplitude spectrum",
    "谱峰标注": "Spectral peaks",
    "谐波标记": "Harmonics",
    "相位谱": "Phase spectrum",
    "时频图": "Spectrogram",
    "时间 / s": "Time / s",
    "幅值 / FS": "Amplitude / FS",
    "频率 / Hz": "Frequency / Hz",
    "幅值 / dBFS": "Amplitude / dBFS",
    "傅立叶幅值谱": "Fourier amplitude spectrum",
    "未执行包络拟合": "No envelope fit was performed.",
    "未执行冲击检测。": "No impulse detection was performed.",
    "排除出统计": "excluded from statistics",
    "检测阈值 {_v0:g}；修复 {_v1} 段，排除 {_v2} 段。":
        "Detection threshold {_v0:g}; repaired {_v1} segments, excluded {_v2}.",
    "开始 / s": "Start / s",
    "结束 / s": "End / s",
    "处理": "Action",
    "本次报告由本地确定性算法生成，未使用 AI 叙述。":
        "This report was produced by local deterministic algorithms; no AI narrative was used.",
    "WAV 数据处理报告": "WAV data processing report",
    "WAV 声音实验数据处理报告": "Acoustic WAV data processing report",
    "文件：{_v0}": "File: {_v0}",
    "采样率：{_v0} Hz；声道：{_v1}": "Sample rate: {_v0} Hz; channel: {_v1}",
    "波形与傅立叶幅值谱": "Waveform and Fourier amplitude spectrum",
    "波形与频谱图": "waveform and spectrum",
    "主频：{_v0:.6f} Hz；主频峰值振幅：{_v1:.8g}；THD：{_v2:.6g}":
        "Main frequency: {_v0:.6f} Hz; peak amplitude at main frequency: {_v1:.8g}; "
        "THD: {_v2:.6g}",
    "分析窗函数：{_v0}；FFT 点数：{_v1}": "Analysis window: {_v0}; FFT length: {_v1}",
    "包络分析": "Envelope analysis",
    "冲击检测与去噪记录": "Impulse detection and denoise log",
    "AI 分析说明": "AI analysis note",
    "幅值为数字满幅归一化单位；dB SPL 按声学校准「{_v0}」换算（K = {_v1:+.2f} dB），"
    "可靠性取决于该标定，未计频率计权，AGC 麦克风与削顶录音不适用。":
        "Amplitudes are full-scale normalised; dB SPL is converted with the acoustic "
        "calibration “{_v0}” (K = {_v1:+.2f} dB). Its reliability depends on that "
        "calibration; no frequency weighting is applied, and it does not hold for AGC "
        "microphones or clipped recordings.",
    "幅值为数字满幅归一化单位，dBFS 不等于 dB SPL（未配置声学校准）。":
        "Amplitudes are full-scale normalised; dBFS is not dB SPL (no acoustic calibration "
        "was configured).",
    "本报告由声音实验 WAV 处理程序独立生成，未套用工作区中的任何既有实验报告。{_v0}":
        "This report was generated independently by the acoustic WAV data processor; no "
        "existing experiment report template was used. {_v0}",
    "R² = {_v0:.6f}，RMSE = {_v1:.6g}": "R² = {_v0:.6f}, RMSE = {_v1:.6g}",
})
_FONT_EN = "Times New Roman"
_FONT_ZH = "SimSun"


def set_report_language(code: str) -> None:
    """设置报告语言：auto / zh / en。非法值回落到 auto。"""
    global _report_language
    _report_language = code if code in (REPORT_AUTO, REPORT_ZH, REPORT_EN) else REPORT_AUTO


def get_report_language() -> str:
    return _report_language


def report_language() -> str:
    """解析成真正用哪种语言：auto 跟随界面语言。"""
    if _report_language == REPORT_AUTO:
        return REPORT_EN if current_language() != LANG_ZH else REPORT_ZH
    return _report_language


def report_is_english() -> bool:
    return report_language() == REPORT_EN


def font_family() -> str:
    """英文报告用 Times New Roman，中文仍用宋体。"""
    return _FONT_EN if report_is_english() else _FONT_ZH


def _english_table() -> dict[str, str]:
    global _english
    if _english is None:
        from core.i18n_en import EN

        _english = EN
    return _english


def rt(text: str) -> str:
    """把一段中文报告文案翻成当前报告语言；查不到就原样返回。"""
    if not text or not report_is_english():
        return text
    merged = _MERGED.get(text)
    if merged is not None:
        return merged
    value = REPORT_EN_TEXT.get(text) or _english_table().get(text) or text
    _MERGED[text] = value
    return value


def rtf(template: str, **kwargs) -> str:
    """模板先翻语言、再填占位符。英文条目的占位符名必须与中文一致。"""
    return rt(template).format(**kwargs)


def report_language_options() -> tuple[tuple[str, str], ...]:
    """界面下拉用：auto 的显示名跟随界面语言。"""
    from core.i18n import tr

    return tuple((code, tr(label)) for code, label in REPORT_LANGUAGES)


def analysis_scope_text(stats: dict) -> str:
    """把「计算口径」按报告语言重新渲染。

    `core/statistics.py` 在结果里存了中文原文（`_scope`）与已渲染字符串
    （`analysis_scope`）；后者跟随**界面**语言，不能直接写进英文报告。
    """
    scope = getattr(stats, "scope_parts", None) if stats is not None else None
    if not scope:
        return str(stats.get("analysis_scope", "")) if isinstance(stats, dict) else ""
    separator = "; " if report_is_english() else "；"
    parts = [rt(scope.get("energy", ""))]
    freq = scope.get("freq")
    if isinstance(freq, tuple) and freq:
        parts.append(rtf(freq[0], **dict(freq[1])))
    elif isinstance(freq, str) and freq:
        parts.append(rt(freq))
    return separator.join(part for part in parts if part)


def suggest_report_suffix(edited: bool) -> str:
    """文件名后缀：中文态沿用旧名，英文态用 ASCII，免得英文报告带中文文件名。"""
    if report_is_english():
        return "edited_analysis" if edited else "source_analysis"
    return "修改分析" if edited else "源文件分析"


def read_text(path: str | Path) -> str:
    """测试与核对用：按导出编码读回报告。"""
    return io.open(path, encoding="utf-8-sig").read()
