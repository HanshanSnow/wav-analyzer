"""英文文案表。键是代码里 tr() 包裹的原始中文，值是英文译文。

维护方式
--------
1. 新增界面文案时先写中文并过 tr()，然后在本表补一条。漏补不会崩——英文模式下
   该条会显示中文，测试 ``test_i18n.py`` 会统计未翻译条目数并给出清单。
2. 键必须与代码中的中文**逐字一致**（含全角标点、空格）。改中文原文就要改键。
3. 值里保留 ``%d`` / ``{}`` / ``%s`` 等占位符，顺序与数量必须与原串一致，
   否则格式化会抛异常。
"""

from __future__ import annotations

EN: dict[str, str] = {}

# ---------------------------------------------------------------- 主窗口：左侧栏与分组
EN.update({
    "声音实验 WAV 数据处理程序": "Acoustic Measurement WAV Data Processor",
    "处理中": "Working",
    "文件与声道": "File & channel",
    "尚未载入文件": "No file loaded",
    "请打开 WAV 文件；原始文件始终只读": "Open a WAV file; the original is always read-only",
    "打开 WAV": "Open WAV",
    "自动估计": "Auto estimate",
    "当前声道": "Current channel",
    "已知激励频率": "Known excitation frequency",
    "声学校准": "Acoustic calibration",
    "未校准（只显示 dBFS）": "Not calibrated (dBFS only)",
    "选中的校准用于把 dBFS 换算成 dB SPL；未校准时只显示 dBFS":
        "The selected profile converts dBFS to dB SPL; without one only dBFS is shown",
    "校准设置…": "Calibration…",
    "未校准：统计只显示 dBFS。配好灵敏度或做一次标定后，统计表才会多出声压级两行。":
        "Not calibrated: statistics show dBFS only. Set sensitivity or run a calibration "
        "and two SPL rows appear in the table.",
    "批量处理": "Batch processing",
    "一次处理多个 WAV：先搭步骤脚本，再选文件，后台逐个执行。":
        "Process many WAV files: build a step script, pick the files, run in the background.",
    "批量处理…": "Batch processing…",
    "编辑处理步骤 → 选择待处理文件 → 开始处理": "Edit steps → select files → start",
    "播放与编辑": "Playback & editing",
    "▶ 播放": "▶ Play",
    "■ 停止": "■ Stop",
    "⏸ 暂停": "⏸ Pause",
    "播放选区": "Play selection",
    "播放全文件": "Play whole file",
    "裁剪到选区": "Crop to selection",
    "应用更改到源文件…": "Apply changes to source…",
    "未做编辑": "No edits",
    "坐标与分析": "Coordinates & analysis",
    "频率轴使用对数刻度": "Logarithmic frequency axis",
    "频谱幅值刻度": "Spectrum amplitude scale",
    "指定时间读数": "Read at time",
    "计算选区统计": "Compute selection statistics",
    "双通道时延与电平分析": "Two-channel delay & level analysis",
    "冲击检测与去噪": "Transient detection & repair",
    "稳健阈值": "Robust threshold",
    "最长修复": "Max repair length",
    "检测并预览": "Detect & preview",
    "应用预览": "Apply preview",
    "关闭预览": "Discard preview",
    "清除橙色预览曲线与待应用结果，处理数据不受影响":
        "Clear the orange preview and any pending result; processed data is untouched",
    "撤销上次处理": "Undo last edit",
    "尚未检测": "Not detected yet",
    "包络分析": "Envelope analysis",
    "显示包络并拟合选区": "Show envelope & fit selection",
    "未拟合": "No fit",
    "导出": "Export",
})

# ---------------------------------------------------------------- 主窗口：绘图与表格
EN.update({
    "波形与选区": "Waveform & selection",
    "傅立叶分析": "Fourier analysis",
    "时频图": "Spectrogram",
    "区间统计": "Interval statistics",
    "AI 数据助手": "AI assistant",
    "时间": "Time",
    "幅值": "Amplitude",
    "频率": "Frequency",
    "相位": "Phase",
    "频率 / Hz": "Frequency / Hz",
    "峰值振幅": "Peak amplitude",
    "相位 / rad": "Phase / rad",
    "次数": "Order",
    "统计量": "Statistic",
    "数值": "Value",
    "含义与取值说明": "Definition",
    "主要谱峰": "Dominant peaks",
    "谐波": "Harmonics",
    "振幅谱": "Amplitude spectrum",
    "＋相位谱": "＋ Phase spectrum",
    "傅立叶分析：未载入数据": "Fourier analysis: no data loaded",
    "移动紫色游标读取指定时间的数据；蓝色区域用于统计、裁剪和包络拟合。":
        "Move the purple cursor to read a given time; the blue band drives statistics, "
        "cropping and envelope fitting.",
    "单位 FS 指数字满幅（±1.0 为满量程）；dBFS 是相对满幅的分贝值，不是声压级 dB SPL。"
    "RMS/峰值/标准差基于选区全部有效采样点，主频与 THD 基于居中 FFT 窗口（见“计算口径说明”一行）。":
        "FS means full scale (±1.0 is full scale); dBFS is decibels relative to full scale, "
        "not sound pressure level. RMS/peak/std use every valid sample in the selection; "
        "fundamental and THD use a centred FFT window (see the “Analysis conventions” line).",
    "原始": "Original",
    "当前": "Current",
    "去噪预览": "Repair preview",
    "包络": "Envelope",
    "拟合": "Fit",
    "拟合区间 {_v0:.4f}–{_v1:.4f} s": "Fit range {_v0:.4f}–{_v1:.4f} s",
})

# ---------------------------------------------------------------- 主窗口补漏
EN.update({
    "已裁剪到 {_v0:.3f}–{_v1:.3f} s，保留 {_v2:,} 点；可用“撤销上次处理”还原。":
        "Cropped to {_v0:.3f}–{_v1:.3f} s, kept {_v2:,} samples; "
        "use “Undo last edit” to restore.",
    "处理失败": "Processing failed",
    "处理结果失败": "Result processing failed",
    "WAV 音频 (*.wav)": "WAV audio (*.wav)",
    "当前声道 {_v0:,} 点，长音频会先抽稀再绘制":
        "Current channel has {_v0:,} samples; long recordings are decimated before drawing",
    "批量处理已开始：{_v0} 个文件，{_v1} 个步骤":
        "Batch started: {_v0} file(s), {_v1} step(s)",
    "批量处理失败": "Batch processing failed",
    "确认 AI 去噪预览": "Confirm AI repair preview",
    "AI 请求应用去噪预览：{_v0} 段，修复 {_v1} 个采样，排除 {_v2} 个。":
        "The AI wants to apply a repair preview: {_v0} segment(s), {_v1} sample(s) "
        "interpolated, {_v2} excluded.",
    "应用后只改处理版本，原始 WAV 不变，且可以撤销。":
        "Only the working copy changes; the original WAV stays intact and this can be undone.",
    "应用": "Apply",
    "不应用": "Don't apply",
    "{_v0}；长文件可能需要数秒": "{_v0}; long files may take a few seconds",
    "声道 {_v0}": "Channel {_v0}",
    "{_v0}\n{_v1:.3f} s | {_v2} Hz | {_v3} 声道 | {_v4}\n峰值 {_v5:.4f}，RMS {_v6:.4f}":
        "{_v0}\n{_v1:.3f} s | {_v2} Hz | {_v3} channel(s) | {_v4}\n"
        "Peak {_v5:.4f}, RMS {_v6:.4f}",
    "傅立叶谱、时频图与统计量": "Spectrum, spectrogram and statistics",
    "重新计算频谱与统计量": "Recompute spectrum and statistics",
    "选区 {start:.3f}–{end:.3f} s；长选区需要数秒":
        "Selection {start:.3f}–{end:.3f} s; a long selection takes a few seconds",
    "批量任务正在进行，请等待结束或点遮罩上的“取消”":
        "A batch job is running; wait for it or click “Cancel” on the overlay",
    "当前已有任务在后台运行，请稍后再试":
        "Another task is already running in the background; try again later",
    "批量处理结束": "Batch finished",
    "批量处理已取消": "Batch cancelled",
    "批量处理完成": "Batch complete",
    "AI 请求的去噪预览没有检测到需要修复的区段（0 段），已自动跳过确认，数据未改动。":
        "The repair preview requested by the AI found nothing to fix (0 segments), "
        "so the confirmation was skipped and no data changed.",
    "批量处理进行中": "Batch in progress",
    "批量任务尚未结束。取消并等待当前文件处理完后退出吗？":
        "The batch has not finished. Cancel it, wait for the current file, and quit?",
    "仍有处理在进行": "Work still in progress",
    "当前有后台任务未完成，立即退出可能丢失未保存的处理结果。是否仍要退出？":
        "A background task has not finished; quitting now may lose unsaved results. "
        "Quit anyway?",
    "\n警告：可能存在削顶": "\nWarning: possible clipping",
})

# ---------------------------------------------------------------- 区间统计：名称与定义
EN.update({
    "RMS/峰值/标准差基于选区全部有效采样点":
        "RMS, peak and standard deviation use every valid sample in the selection",
    "有效起点 (s)": "Valid start (s)",
    "参与统计的第一个采样点时间；若起点被排除段覆盖，会自动向右收缩":
        "Time of the first sample included; if an excluded segment covers the start, "
        "it moves right automatically",
    "有效终点 (s)": "Valid end (s)",
    "参与统计的最后一个采样点时间（右端按开区间理解）":
        "Time of the last sample included (the right edge is open)",
    "请求起点 (s)": "Requested start (s)",
    "蓝框选区原始起点，用于核对掩码把边界修正了多少":
        "Original start of the blue selection, so you can see how far the mask moved it",
    "请求终点 (s)": "Requested end (s)",
    "蓝框选区原始终点": "Original end of the blue selection",
    "有效采样点数": "Valid samples",
    "真正参与计算的采样点数（已扣除被排除的长冲击段）":
        "Samples that actually entered the calculation (long excluded transients removed)",
    "排除点数": "Excluded samples",
    "被判为长冲击、未做插值修复的点数；这些点不计入任何幅值/能量统计":
        "Samples classed as long transients and left unrepaired; they enter no amplitude "
        "or energy statistic",
    "有效时长 (s)": "Valid duration (s)",
    "有效采样点数 ÷ 采样率，通常略小于蓝框宽度":
        "Valid samples ÷ sample rate, usually slightly less than the selection width",
    "均值 / 直流分量 (FS)": "Mean / DC offset (FS)",
    "整段有效数据的算术平均；明显不为 0 说明存在直流偏置，报告需注明":
        "Arithmetic mean over the valid data; a clear non-zero value means a DC offset, "
        "which the report should mention",
    "标准差 (FS)": "Standard deviation (FS)",
    "去均值后的起伏幅度，只反映交流成分，与直流偏置无关":
        "Spread after removing the mean; it reflects the AC part only and ignores DC offset",
    "最小瞬时值 (FS)": "Minimum sample (FS)",
    "单个采样点的最小值（有符号，负半周最深处）":
        "Smallest single sample (signed, deepest point of the negative half-cycle)",
    "最大瞬时值 (FS)": "Maximum sample (FS)",
    "单个采样点的最大值（有符号，正半周最高处）":
        "Largest single sample (signed, highest point of the positive half-cycle)",
    "峰值振幅 max|x| (FS)": "Peak amplitude max|x| (FS)",
    "正负两侧绝对值的较大者，恒为正值；不是峰峰值":
        "Larger of the two absolute extremes, always positive — not peak-to-peak",
    "峰峰值 max−min (FS)": "Peak-to-peak max−min (FS)",
    "max 减 min，等于波形总摆幅，约为峰值振幅的 2 倍（对称波形）":
        "max minus min, the full swing of the waveform — about twice the peak amplitude "
        "for a symmetric signal",
    "有效值 RMS (FS)": "RMS (FS)",
    "√(mean(x²))，包含直流分量；整周期正弦时 RMS = 峰值 ÷ √2 ≈ 0.707×峰值":
        "√(mean(x²)), including DC; for a whole number of sine cycles RMS = peak ÷ √2 "
        "≈ 0.707 × peak",
    "RMS 电平 (dBFS)": "RMS level (dBFS)",
    "20·lg(RMS/FS)，满幅正弦约 −3.01 dBFS；dBFS 是数字满幅相对值，不等于 dB SPL":
        "20·lg(RMS/FS); a full-scale sine is about −3.01 dBFS. dBFS is relative to digital "
        "full scale, not dB SPL",
    "等效声压级 (dB SPL)": "Equivalent SPL (dB SPL)",
    "RMS 电平 + 校准偏移 K；等效于该区间的能量平均声压级，仅在配置声学校准后出现":
        "RMS level + calibration offset K, i.e. the energy-averaged SPL of the interval; "
        "shown only with a calibration profile",
    "峰值声压级 (dB SPL)": "Peak SPL (dB SPL)",
    "20·lg(峰值振幅) + K，未计频率计权，仅在配置声学校准后出现":
        "20·lg(peak amplitude) + K, with no frequency weighting; shown only with a "
        "calibration profile",
    "校准偏移 K (dB)": "Calibration offset K (dB)",
    "dB SPL = dBFS + K；由灵敏度、前置增益与满幅电压推算，或由已知声压级标定得到":
        "dB SPL = dBFS + K, derived from sensitivity, preamp gain and full-scale voltage, "
        "or from a known reference level",
    "校准配置": "Calibration profile",
    "本次换算使用的校准名称；空表示未校准，此时不输出任何 dB SPL":
        "Name of the profile used; empty means uncalibrated, and no dB SPL is emitted",
    "波峰因数 (峰值/RMS)": "Crest factor (peak/RMS)",
    "峰值振幅 ÷ RMS；正弦约 1.414，脉冲/冲击性越强该值越大":
        "Peak amplitude ÷ RMS; about 1.414 for a sine, larger for impulsive signals",
    "主频 (Hz)": "Fundamental (Hz)",
    "幅值最大谱峰对应的频率；长文件按居中窗口估计，实际窗口见“计算口径”":
        "Frequency of the largest spectral peak; long files use a centred window — "
        "see “Analysis conventions”",
    "主频振幅 (FS)": "Fundamental amplitude (FS)",
    "单边幅值谱在主频处的幅值；整周期正弦时约等于峰值振幅":
        "Single-sided amplitude at the fundamental; roughly the peak amplitude for a "
        "whole number of sine cycles",
    "主频电平 (dBFS)": "Fundamental level (dBFS)",
    "20·lg(主频振幅)，用于和本底噪声比较，不是声压级":
        "20·lg(fundamental amplitude), for comparing against the noise floor — not SPL",
    "总谐波失真 THD": "Total harmonic distortion (THD)",
    "2～10 次谐波（到奈奎斯特频率为止）幅值的均方根 ÷ 基波幅值；纯正弦接近 0":
        "RMS of harmonics 2–10 (up to Nyquist) ÷ fundamental amplitude; near 0 for a "
        "pure sine",
    "计算口径说明": "Analysis conventions",
    "声明哪些量基于选区全部采样点、哪些量基于受限 FFT 窗口":
        "States which quantities use every sample in the selection and which use the "
        "limited FFT window",
    "主频/THD 基于居中窗口 {_v0:,}/{_v1:,} 点（{_v2:.3f}–{_v3:.3f} s）":
        "Fundamental/THD use a centred window of {_v0:,}/{_v1:,} points "
        "({_v2:.3f}–{_v3:.3f} s)",
    "主频/THD 基于选区全部有效采样点":
        "Fundamental/THD use every valid sample in the selection",
    "采样率必须为正数": "Sample rate must be positive",
    "统计区间无效：需要 0 ≤ start < end，且区间内必须有采样点":
        "Invalid interval: need 0 ≤ start < end and at least one sample inside",
    "没有可统计的音频数据": "No audio data to analyse",
    "区间内有效采样点不足": "Not enough valid samples in the interval",
    "统计区间包含 NaN 或无穷值": "The interval contains NaN or infinite values",
    "读数时间超出音频范围": "Readout time is outside the audio range",
    "有效区间掩码长度与音频不一致": "Valid-interval mask length does not match the audio",
})

# ---------------------------------------------------------------- 批量：步骤说明
EN.update({
    "统计区间": "Interval statistics",
    "去掉开头": "Trim start",
    "去掉结尾": "Trim end",
    "起点": "Start",
    "终点": "End",
    "固定频率值": "Fixed frequency",
    "冲击去噪": "Transient repair",
    "检测超出稳健阈值的短脉冲并三次样条修补；无法修补的超长区间标记为无效点。":
        "Find short spikes above a robust threshold and repair them with cubic splines; "
        "segments too long to repair are marked invalid.",
    "裁剪到区间": "Crop to interval",
    "只保留指定时间区间，其后的步骤都基于裁剪后的数据。":
        "Keep only the given interval; every later step works on the cropped data.",
    "包络拟合": "Envelope fit",
    "对指定区间求 Hilbert 包络并拟合（auto 会按残差自动选择常数/线性/指数）。":
        "Compute the Hilbert envelope over the interval and fit it (auto picks "
        "constant/linear/exponential by residual).",
    "计算选区的 RMS、峰值、主频、THD 等；主频与 THD 受已知激励频率约束。":
        "Compute RMS, peak, fundamental and THD for the selection; the fundamental can be "
        "constrained by a known excitation frequency.",
    "双通道时延与电平": "Two-channel delay & level",
    "比较两声道的主频幅值与到达时延。单声道文件自动跳过。":
        "Compare fundamental amplitude and arrival delay between channels; mono files are "
        "skipped automatically.",
    "把当前处理结果另存为新 WAV，源文件不动。":
        "Save the processed result as a new WAV; the source is never touched.",
    "导出分析 TXT": "Export analysis TXT",
    "定宽对齐的纯文本分析报告；可每个文件一份，也可合并成一份汇总。":
        "Fixed-width plain-text report; one per file or merged into a single summary.",
    "导出图像 PNG": "Export image PNG",
    "按论文或屏幕版式重新渲染图像，不是界面截图。":
        "Re-render the figure in paper or screen layout — not a screenshot of the UI.",
    "导出统计 CSV": "Export statistics CSV",
    "统计量写成 CSV，可直接进 Excel / Origin；默认合并成一张表。":
        "Statistics as CSV, ready for Excel / Origin; merged into one table by default.",
    "生成 HTML 报告": "Generate HTML report",
    "每个文件一份独立报告，含波形、频谱与统计表。":
        "One standalone report per file, with waveform, spectrum and statistics table.",
})

# ---------------------------------------------------------------- 批量：运行与结果
EN.update({
    "共 {_v0} 个文件，成功 {_v1}，失败 {_v2}":
        "{_v0} file(s) total, {_v1} succeeded, {_v2} failed",
    "，用时 {_v0:.1f} s": ", took {_v0:.1f} s",
    "未知步骤类型：{kind}": "Unknown step type: {kind}",
    "TXT {_v0:,} 行 → {_v1}": "TXT {_v0:,} rows → {_v1}",
    "_统计": "_stats",
    "_报告": "_report",
    "_处理后": "_processed",
    "_分析": "_analysis",
    "声音实验 WAV 数据处理程序 — 批量分析汇总":
        "Acoustic Measurement WAV Data Processor — batch analysis summary",
    "# 文件数：{total}": "# Files: {total}",
    "# 数据来源：批量处理（每个文件的完整报告按处理顺序依次附在下方）":
        "# Source: batch processing (each file's full report follows in processing order)",
    "# 分段方式：每段以「分析数据导出」标题开始，含源文件名、路径与 MD5 指纹":
        "# Layout: each section starts with an “analysis export” heading and carries the "
        "source name, path and MD5",
    "去噪修复 {total_repaired} 处，标记无效 {total_excluded} 处":
        "Repaired {total_repaired} point(s), marked {total_excluded} invalid",
    "裁剪至 {_v0:.3f}–{_v1:.3f} s": "Cropped to {_v0:.3f}–{_v1:.3f} s",
    "主频 {_v0:.3f} Hz，电平 {_v1:.2f} dBFS":
        "Fundamental {_v0:.3f} Hz, level {_v1:.2f} dBFS",
    "（已取消）": "(cancelled)",
    "，输出 {_v0} 个文件": ", wrote {_v0} file(s)",
    "（未知步骤）": "(unknown step)",
    "统计区间为空：请检查起止时间或去掉的首尾长度":
        "The interval is empty; check the start/end times or the trimmed head and tail",
    "去噪把 {_v0:.0f}% 的采样点标为无效，请提高稳健阈值或先确认数据是否异常":
        "Repair marked {_v0:.0f}% of samples invalid; raise the robust threshold or check "
        "whether the data is sane",
    "单声道文件，已跳过双通道分析":
        "Mono file — two-channel analysis skipped",
    "批量处理结果（已编辑）": "Batch result (edited)",
    "\n· 其余 {_v0} 个失败略": "\n· {_v0} more failure(s) omitted",
    "\n# 批量处理结束：": "\n# Batch finished: ",
    "警告：源文件可能存在削顶": "Warning: the source may be clipped",
})

# ---------------------------------------------------------------- 批量：参数控件
EN.update({
    "去掉首尾用于跳过起振与收尾的瞬态":
        "Trim head and tail to skip the onset and decay transients",
    " s（0 表示到文件末尾）": " s (0 means end of file)",
    "从文件名解析：识别 1000Hz、2kHz 这类片段，适合按频率命名的一批录音":
        "Parse from filename: recognises tokens like 1000Hz or 2kHz — handy when a batch is "
        "named by frequency",
    "全文件": "Whole file",
    "去掉首尾": "Trim head/tail",
    "固定区间": "Fixed interval",
    "自动估计（取最强峰）": "Auto (strongest peak)",
    "固定值（所有文件相同）": "Fixed value (same for all files)",
    "文件名里的频率（如 1000Hz）": "Frequency in filename (e.g. 1000Hz)",
    "处理范围": "Range",
    "文件名后缀": "Filename suffix",
    "采样格式": "Sample format",
    "输出方式": "Output mode",
    "合并文件名": "Merged filename",
    "批量分析汇总.txt": "batch_analysis_summary.txt",
    "导出章节": "Sections",
    "坐标取法": "Coordinate mode",
    "每秒点数": "Points per second",
    "抽稀步长": "Decimation stride",
    "图像类型": "Figure type",
    "版式": "Layout",
    "波形图叠包络": "Overlay envelope",
    "波形图叠拟合曲线": "Overlay fitted curve",
    "波形图标出选区": "Mark selection",
    "批量统计.csv": "batch_statistics.csv",
    "拟合模型": "Fit model",
    "按稳健标准差倍数判定冲击，越小越敏感":
        "Threshold in robust standard deviations — smaller is more sensitive",
    "合并模式下建议关掉原坐标，否则汇总文件会非常大":
        "In merged mode, turn raw coordinates off or the summary file gets huge",
    "后缀": "Suffix",
    "全部声道": "All channels",
    "仅第 1 声道": "Channel 1 only",
    "FLOAT（32 bit 浮点）": "FLOAT (32-bit)",
    "每个文件一个 TXT": "One TXT per file",
    "合并为一个 TXT": "Merge into one TXT",
    "每秒固定点数": "Fixed points per second",
    "按步长抽稀": "Decimate by stride",
    "全部采样点": "All samples",
    "波形图": "Waveform",
    "幅值谱": "Amplitude spectrum",
    "论文单栏 3.5×2.45 in（600 dpi）": "Paper 1-column 3.5×2.45 in (600 dpi)",
    "论文双栏 7.0×2.6 in（600 dpi）": "Paper 2-column 7.0×2.6 in (600 dpi)",
    "屏幕 1600×900": "Screen 1600×900",
    "合并为一个 CSV（每个文件一行）": "Merge into one CSV (one row per file)",
    "每个文件一个 CSV": "One CSV per file",
    "auto（自动选择）": "auto",
    "常数": "Constant",
    "线性": "Linear",
    "指数": "Exponential",
    "含": "Include",
    "不含": "Exclude",
})

# ---------------------------------------------------------------- 批量脚本编辑对话框
EN.update({
    "批量处理 — 脚本编辑": "Batch processing — script editor",
    "步骤自上而下执行；只有“导出”类步骤会写文件，源文件始终只读。":
        "Steps run top to bottom; only “export” steps write files, and the source files "
        "are always read-only.",
    "任务步骤": "Steps",
    "＋ 新增步骤": "＋ Add step",
    "选择要加入流水线的处理功能": "Choose a function to add to the pipeline",
    "－ 删除": "－ Remove",
    "上移": "Move up",
    "下移": "Move down",
    "载入脚本…": "Load script…",
    "保存脚本…": "Save script…",
    "尚未添加步骤": "No steps yet",
    "点左侧“＋ 新增步骤”挑一个功能，再在这里设置参数。":
        "Click “＋ Add step” on the left, then set its parameters here.",
    "待处理文件：尚未选择": "Files: none selected",
    "选择待处理的文件…": "Select files…",
    "清空": "Clear",
    "留空 = 与源文件同目录": "Blank = alongside the source files",
    "浏览…": "Browse…",
    "选择待处理的 WAV（可多选）": "Select WAV files (multiple allowed)",
    "选择输出目录": "Select output directory",
    "保存脚本": "Save script",
    "载入脚本": "Load script",
    "已载入 {_v0} 个步骤": "Loaded {_v0} step(s)",
    "输出目录": "Output directory",
    " …（共 {_v0} 个）": " … ({_v0} total)",
    "共 {total} 个步骤（其中 {exports} 个导出步骤）":
        "{total} step(s), {exports} of them exports",
    "没有可保存的步骤": "Nothing to save",
    "请先添加至少一个任务步骤。": "Add at least one step first.",
    "脚本已保存到 {path}": "Script saved to {path}",
    "载入失败": "Load failed",
    "文件里没有可识别的任务步骤。": "No recognisable steps in this file.",
    "还没有步骤": "No steps yet",
    "请先用“＋ 新增步骤”搭一条流水线。": "Build a pipeline with “＋ Add step” first.",
    "还没有文件": "No files yet",
    "请先点“选择待处理的文件”。": "Click “Select files” first.",
    "没有导出步骤": "No export step",
    "当前脚本只做分析、不写任何文件。确定继续吗？":
        "This script only analyses and writes no files. Continue?",
    "已恢复上次的 {_v0} 个步骤": "Restored {_v0} step(s) from last time",
    "输出到 {target}": "Output to {target}",
    "输出到各源文件所在目录": "Output next to each source file",
    "保存失败": "Save failed",
    "没有选图像类型": "No figure type selected",
    "“导出图像 PNG”至少要勾一种图像。":
        "“Export image PNG” needs at least one figure type.",
    "待处理文件：{_v0} 个 → ": "Files: {_v0} → ",
    "合并文件名不能为空": "Merged filename cannot be empty",
    "“导出分析 TXT”选了合并方式，请填写合并文件名。":
        "“Export analysis TXT” is set to merge — fill in the merged filename.",
    "没有选章节": "No sections selected",
    "“导出分析 TXT”至少要勾一个章节。":
        "“Export analysis TXT” needs at least one section.",
    "“导出统计 CSV”选了合并方式，请填写合并文件名。":
        "“Export statistics CSV” is set to merge — fill in the merged filename.",
})

# ---------------------------------------------------------------- 批量进度遮罩
EN.update({
    "正在批量处理": "Batch processing",
    "正在导入文件：—": "Importing file: —",
    "正在处理文件：—": "Processing file: —",
    "取消": "Cancel",
    "取消中…": "Cancelling…",
    "正在停止，当前文件处理完后结束":
        "Stopping — it ends when the current file finishes",
    "总进度 {_v0:.0f}%": "Overall {_v0:.0f}%",
    "正在导入文件（{index}/{total}）：{_v2}": "Importing file ({index}/{total}): {_v2}",
    "正在汇总": "Summarising",
    "正在处理文件": "Processing file",
    "已完成": "Done",
    "已导入（{index}/{total}）：{_v2}": "Imported ({index}/{total}): {_v2}",
})

# ---------------------------------------------------------------- 模型设置
EN.update({
    "AI 模型设置": "AI model settings",
    "自定义（自填 Base URL 与模型名）": "Custom (enter Base URL and model name)",
    "在 platform.deepseek.com 的 API keys 页面创建，形如 sk-…":
        "Create one on the API keys page of platform.deepseek.com, looks like sk-…",
    "在 platform.moonshot.cn 的 API Key 管理页创建，形如 sk-…":
        "Create one in the API Key page of platform.moonshot.cn, looks like sk-…",
    "在 platform.openai.com 的 API keys 页面创建，形如 sk-…":
        "Create one on the API keys page of platform.openai.com, looks like sk-…",
    "例如：https://api.deepseek.com/v1": "e.g. https://api.deepseek.com/v1",
    "仅保存在本机，不写入源码，也不随文件分发":
        "Stored on this machine only — never in source code, never shipped with files",
    "单次 HTTP 请求的等待上限。推理模型思考时间较长时调大一些；"
    "遇到“请求超时”先试 {_v0} s 以上。":
        "Upper bound for one HTTP request. Raise it for slower reasoning models; on a "
        "timeout, try {_v0} s or more first.",
    "API Key 由 Windows 系统钥匙串（凭据管理器）加密保存，仅存在本机，"
    "不写入配置文件、不写入日志、也不随本程序分发。":
        "The API key is encrypted and stored in the Windows Credential Manager. It stays "
        "on this machine — not in config files, not in logs, not shipped with the app.",
    "WAV Analyzer 不会向任何人透露 API Key。Key 只在与你填写的 Base URL 通信时放入请求头，"
    "其它任何网络请求都不会携带它；导出的 TXT、CSV、图片与报告也不含 Key。":
        "WAV Analyzer never discloses the API key to anyone. It is placed in a request "
        "header only when talking to the Base URL you configured; no other request carries "
        "it, and exported TXT, CSV, images and reports never contain it.",
    "选择预设厂商后，Base URL 与模型名会自动填好，只需填写 API Key；"
    "选择“自定义”则三项都要自己填。模型名可手动改写为厂家的其它模型。":
        "A vendor preset fills Base URL and model name for you — only the API key is "
        "needed. With “Custom” you supply all three. The model name can be edited to any "
        "other model the vendor offers.",
    "厂商预设": "Vendor preset",
    "模型名称": "Model name",
    "温度": "Temperature",
    "超时": "Timeout",
    "测试连接": "Test connection",
    "保存": "Save",
    "自定义服务需兼容 OpenAI 的 /chat/completions 与 /models 接口。":
        "A custom service must be compatible with the OpenAI /chat/completions and /models "
        "endpoints.",
    "连接测试": "Connection test",
    "设置不完整": "Incomplete settings",
    "Base URL 和模型名称不能为空。": "Base URL and model name cannot be empty.",
    "未填写 API Key": "No API key",
    "当前未填写 API Key，AI 助手调用会被服务端拒绝。是否仍然保存？":
        "No API key entered; the server will reject AI requests. Save anyway?",
    "\n\n⚠ Key 未能写入 Windows 钥匙串：{exc}\n下次启动需要重新填写。":
        "\n\n⚠ The key could not be written to the Windows Credential Manager: {exc}\n"
        "You will have to enter it again next launch.",
    "钥匙串不可用": "Credential Manager unavailable",
    "连接失败": "Connection failed",
    "{exc}\n\n请依次检查：API Key 是否正确、Base URL 是否可用、模型名是否存在。":
        "{exc}\n\nCheck in turn: is the API key correct, is the Base URL reachable, does "
        "the model name exist.",
    "其余设置已保存。": "The other settings were saved.",
    "DeepSeek（深度求索）": "DeepSeek",
})

# ---------------------------------------------------------------- AI 会话气泡
EN.update({
    "你": "You",
    "请求失败": "Request failed",
    "提示": "Note",
    "AI 默认只接收当前文件的数值摘要。去噪操作需你确认，不会执行模型生成的代码。":
        "The AI receives a numeric summary of the current file by default. Repairs need "
        "your confirmation and it never executes model-generated code.",
})

# ---------------------------------------------------------------- 导出图像 PNG 对话框
EN.update({
    "波形": "Waveform",
    "频谱": "Spectrum",
    "论文单栏 3.5 × 2.45 in（600 dpi，推荐）": "Paper 1-column 3.5 × 2.45 in (600 dpi, recommended)",
    "论文双栏 7.0 × 2.6 in（600 dpi）": "Paper 2-column 7.0 × 2.6 in (600 dpi)",
    "屏幕 1600 × 900（报告/PPT）": "Screen 1600 × 900 (report/slides)",
    "屏幕 1920 × 1080（全高清）": "Screen 1920 × 1080 (Full HD)",
    "自定义像素": "Custom pixels",
    "坐标区外（图底一行，论文推荐）": "Below the axes (one row, recommended for papers)",
    "坐标区内右上角": "Top-right inside the axes",
    "不显示图例": "No legend",
    "白色（论文/报告）": "White (paper/report)",
    "深色（投影/屏幕）": "Dark (projector/screen)",
    "透明（叠放到其它版面）": "Transparent (for compositing)",
    "图像": "Figure",
    "{stem}_声道{_v1}": "{stem}_ch{_v1}",
    "导出的 PNG 按下方尺寸与背景重新渲染，不是界面截图："
    "长音频会按 min/max 抽稀到 ≤20 万点绘制，峰谷形态与读数不受影响。":
        "The PNG is re-rendered at the size and background below — not a screenshot. Long "
        "audio is drawn with min/max decimation down to ≤200k points; peaks and readouts "
        "are unaffected.",
    "显示网格": "Show grid",
    "论文版式默认不画标题，图题写在 caption 里":
        "Paper layouts omit the title by default — put it in the caption",
    "尺寸 / 版式": "Size / layout",
    "背景": "Background",
    "图层": "Layers",
    "图例": "Legend",
    "标题": "Title",
    "保存到": "Save to",
    "波形内容": "Waveform content",
    "当前波形（已应用处理的波形）": "Current waveform (with edits applied)",
    "原始波形（处理前参考）": "Original waveform (before editing)",
    "去噪预览（尚未应用的橙色曲线）": "Repair preview (orange, not yet applied)",
    "包络线": "Envelope",
    "拟合曲线（含拟合区间）": "Fitted curve (with fit range)",
    "选区底色": "Selection shading",
    "游标位置": "Cursor position",
    "包络与拟合曲线来自“包络拟合”页的计算结果，未计算时不可选；"
    "去噪预览只有点了“检测并预览”后才有内容。":
        "Envelope and fit come from the envelope tab and are unavailable until computed; "
        "the repair preview only exists after “Detect & preview”.",
    "频谱内容": "Spectrum content",
    "dBFS（对数，推荐）": "dBFS (logarithmic, recommended)",
    "线性幅值 / FS": "Linear amplitude / FS",
    "自动（画到奈奎斯特频率）": "Auto (up to Nyquist)",
    "标注主要谱峰频率": "Label dominant peaks",
    "标出基频整数倍位置（谐波）": "Mark harmonic positions",
    "附带相位谱子图": "Add a phase panel",
    "纵轴": "Y axis",
    "频率上限": "Frequency limit",
    "频谱按 FFT 分析窗口计算，长音频只取居中窗口；图上频率分辨率为采样率 ÷ FFT 点数。":
        "The spectrum uses the FFT analysis window; long files use the centred window. "
        "Resolution on the figure is sample rate ÷ FFT size.",
    "时频内容": "Spectrogram content",
    "色标下限": "Colour floor",
    "色标上限自动取 99.5% 分位；调低下限可以看出更弱的成分，但整图会偏亮。":
        "The colour ceiling uses the 99.5th percentile; lowering the floor reveals weaker "
        "components but brightens the whole image.",
    "物理尺寸 {_v0:g} × {_v1:g} in，{PAPER_DPI} dpi → {_v3} × {_v4} px；"
    "刻度朝内、四边齐全、白底":
        "Physical size {_v0:g} × {_v1:g} in at {PAPER_DPI} dpi → {_v3} × {_v4} px; "
        "inward ticks, all four spines, white background",
    "屏幕版式：自定义像素": "Screen layout: custom pixels",
    "保存 PNG": "Save PNG",
    "PNG 图像 (*.png)": "PNG image (*.png)",
    "图像设置": "Image settings",
    "屏幕版式：按像素出图，可选深色或透明背景":
        "Screen layout: pixel-sized output, dark or transparent background available",
    "缺少保存路径": "No save path",
    "请先选择 PNG 文件保存位置。": "Choose where to save the PNG first.",
    "格式不支持": "Unsupported format",
    "本功能只导出 PNG（.png）。": "This only exports PNG (.png).",
    "目录不可用": "Directory unavailable",
    "无法创建目录：{exc}": "Cannot create directory: {exc}",
    "（当前无数据）": " (no data)",
})

# ---------------------------------------------------------------- 导出分析 TXT 对话框
EN.update({
    "按采样率换算步长，适合画曲线与对照":
        "Stride derived from the sample rate — good for plotting and comparison",
    "按固定采样点间隔抽稀，适合对齐特定分析口径":
        "Decimate by a fixed sample stride — good for matching a specific convention",
    "不抽稀，长文件会非常大（数千万行、数 GB）":
        "No decimation; long files get huge (tens of millions of rows, several GB)",
    "{rows:,} 行，约 {megabytes:.1f} MB": "{rows:,} rows, about {megabytes:.1f} MB",
    "TXT 用定宽空格对齐、除末列外只含 ASCII，任何等宽字体下逐列对齐；"
    "可直接拖进 Excel（数据-分列-固定宽度）或 Origin（空格分隔）。":
        "The TXT is space-aligned with ASCII in every column but the last, so it lines up "
        "in any monospace font. Import it into Excel (Data → Text to Columns → Fixed width) "
        "or Origin (space-delimited).",
    "源文件分析（未做任何编辑）": "Source file analysis (no edits)",
    "修改后文件分析（含去噪 / 裁剪结果）": "Edited file analysis (repair / crop applied)",
    "导出内容": "Content",
    "原坐标行数最多，排在文末；段落编号随勾选自动重排。":
        "Raw coordinates are the longest section and go last; numbering closes up as you "
        "toggle sections.",
    "区间统计范围（可多选）": "Interval ranges (multi-select)",
    "原坐标取法": "Coordinate mode",
    "每秒固定点数（推荐）": "Fixed points per second (recommended)",
    "取法": "Mode",
    "预估": "Estimate",
    "数据版本": "Data version",
    "（很大，写入需要一段时间）": " (very large, writing takes a while)",
    "保存分析 TXT": "Save analysis TXT",
    "文本文件 (*.txt)": "Text file (*.txt)",
    "修改后文件分析（当前未编辑，与源文件相同）":
        "Edited file analysis (currently unedited, identical to the source)",
    "自定义区间": "Custom interval",
    "蓝框选区（当前无选区）": "Blue selection (none currently)",
    " 点/秒": " points/s",
    "缺少保存路径": "No save path",
    "请先选择 TXT 保存位置。": "Choose where to save the TXT first.",
    "未选择内容": "Nothing selected",
    "至少勾选一个导出章节。": "Select at least one section.",
    "确认导出全部采样点": "Confirm exporting every sample",
    "原坐标不抽稀将写入约 {_v0:,} 行（数 GB），耗时较长。\n确定继续吗？":
        "Without decimation the raw coordinates write about {_v0:,} rows (several GB) and "
        "take a long time.\nContinue?",
    "{label}（当前无数据）": "{label} (no data)",
    "分析": "Analysis",
    " 点": " points",
})

# ---------------------------------------------------------------- 声学校准对话框
EN.update({
    "新建": "New",
    "删除": "Delete",
    "保存并应用": "Save & apply",
    "把录音的数字满幅电平换算成声压级，只需要一个加性偏移："
    "<b>dB SPL = dBFS + K</b>。K 可以由硬件参数推算，也可以用声压级已知的声源标定。"
    "未配置校准时，程序只显示 dBFS，不会给出任何声压级。":
        "Turning a digital full-scale level into sound pressure level needs one additive "
        "offset: <b>dB SPL = dBFS + K</b>. K comes either from hardware parameters or from "
        "a source with a known level. Without a profile the program shows dBFS only and "
        "never reports SPL.",
    "⚠ 两种麦克风不要用这套换算：<b>带 AGC/ALC 的模块</b>（如 MAX9814、多数 USB 会议麦）"
    "增益会随声压自动变化；<b>录音已削顶</b>时 dBFS 被压平，反推的声压级系统性偏低。"
    "另外系统录音音量必须是 100%（数字增益 0 dB），否则要把它折进前置增益里。":
        "⚠ Two cases break this conversion: <b>modules with AGC/ALC</b> (MAX9814, most USB "
        "conference mics), whose gain tracks the sound pressure; and <b>clipped "
        "recordings</b>, where dBFS is flattened so the derived SPL is systematically low. "
        "Also keep the system recording level at 100% (0 dB digital gain) or fold that "
        "attenuation into the preamp gain.",
    "取当前统计": "Use current statistics",
    "把当前选区的 RMS 电平填进来": "Fill in the RMS level of the current selection",
    "名称": "Name",
    "方式": "Method",
    "<b>K = {offset:+.2f} dB</b>　→　声压级 = 读数 + {_v1:+.2f} dB<br>"
    "反过来：{_v2:.1f} dB SPL 满幅，94 dB SPL 约对应 {_v3:+.2f} dBFS。":
        "<b>K = {offset:+.2f} dB</b>　→　SPL = reading + {_v1:+.2f} dB<br>"
        "Conversely: full scale is {_v2:.1f} dB SPL, and 94 dB SPL is about {_v3:+.2f} dBFS.",
    "K 是常数偏移，所以同一批录音只要麦克风、前置增益和系统音量不变，标定一次即可复用。":
        "K is a constant offset, so one calibration covers a whole batch as long as the "
        "microphone, preamp gain and system volume stay the same.",
    "配置": "Profile",
    "麦克风灵敏度": "Microphone sensitivity",
    "前置增益": "Preamp gain",
    "声卡满幅输入": "ADC full-scale input",
    "已知声压级": "Known SPL",
    "对应读数": "Matching reading",
    "（未完成）": " (incomplete)",
    "没有可用读数": "No reading available",
    "请先在主界面点“计算选区统计”，再来取 RMS 电平。":
        "Click “Compute selection statistics” in the main window first, then fetch the RMS "
        "level.",
    "K 尚未确定：请补全当前方式的参数。": "K is not determined yet; complete the parameters.",
    "至少保留一个配置": "Keep at least one profile",
    "可以清空参数当作“未校准”，无需删除。":
        "You can clear the parameters to mean “uncalibrated” instead of deleting it.",
    "删除校准": "Delete calibration",
    "确定删除「{name}」？": "Delete “{name}”?",
    "未命名校准": "Untitled calibration",
    "校准 {_v0}": "Calibration {_v0}",
    "参数不完整": "Incomplete parameters",
    "默认校准": "Default calibration",
})

# ---------------------------------------------------------------- 校准核心校验
EN.update({
    "按硬件参数推算": "From hardware parameters",
    "按已知声压级标定": "From a known SPL",
    "{_v0}：K = {offset:+.2f} dB（{_v2:g} mV/Pa，增益 {_v3:+.1f} dB，满幅 {_v4:g} Vrms）":
        "{_v0}: K = {offset:+.2f} dB ({_v2:g} mV/Pa, gain {_v3:+.1f} dB, "
        "full scale {_v4:g} Vrms)",
    "{_v0}：参数不完整": "{_v0}: incomplete parameters",
    "若麦克风或模块带 AGC/ALC，增益随声压自动变化，本校准不成立":
        "With AGC/ALC on the microphone or module the gain tracks sound pressure and this "
        "calibration does not hold",
    "削顶录音反推的声压级偏低，需先排除削顶":
        "Clipped recordings give a low SPL estimate; rule out clipping first",
    "校准参数不完整，无法换算声压级":
        "Calibration parameters are incomplete, cannot convert to SPL",
    "满幅电压取标称值，与声卡实际参考电压可能有偏差；有条件时改用已知声压级标定":
        "Full-scale voltage is nominal and may differ from the converter's actual "
        "reference; prefer a known-SPL calibration when you can",
    "前置增益超过 60 dB，请确认数值口径（是放大倍数还是 dB）":
        "Preamp gain above 60 dB — check whether the number is a linear factor or dB",
    "请填写校准名称（例如「电容麦 无增益」）":
        "Give the profile a name (e.g. “condenser, no gain”)",
    "请填写麦克风灵敏度（mV/Pa，常见电容麦 5–50，驻极体 5–20）":
        "Enter microphone sensitivity (mV/Pa; typical condenser 5–50, electret 5–20)",
    "前置增益应在 −20 ～ 120 dB 之间": "Preamp gain must be between −20 and 120 dB",
    "满幅输入电压应在 0.01 ～ 20 Vrms 之间":
        "Full-scale input voltage must be between 0.01 and 20 Vrms",
    "两点标定需要同时填写已知声压级与对应的 dBFS 读数":
        "Two-point calibration needs both the known SPL and its dBFS reading",
    "已知声压级应在 −20 ～ 180 dB SPL 之间":
        "Known SPL must be between −20 and 180 dB SPL",
    "dBFS 读数应在 {MIN_DBFS:.0f} ～ 0 之间（削顶时等于 0）":
        "dBFS reading must be between {MIN_DBFS:.0f} and 0 (0 when clipped)",
})

# ---------------------------------------------------------------- 计算层提示与校验
EN.update({
    "冲击检测至少需要 9 个采样点和正采样率":
        "Transient detection needs at least 9 samples and a positive sample rate",
    "检测阈值必须为正数": "The detection threshold must be positive",
    "冲击检测输入包含 NaN 或无穷值": "Transient detection input contains NaN or infinity",
    "开始冲击检测": "Detecting transients",
    "扩展冲击区间": "Expanding transient intervals",
    "冲击检测完成": "Transient detection done",
    "计算局部基线 {stop:,}/{total:,} 点": "Computing local baseline {stop:,}/{total:,} points",
    "标记冲击候选 {stop:,}/{total:,} 点": "Marking transient candidates {stop:,}/{total:,} points",
    "修复区段 {index}/{total_regions}": "Repairing segment {index}/{total_regions}",
    "{_v0} / {_v1} Hz / {_v2} 声道": "{_v0} / {_v1} Hz / {_v2} channel(s)",
    "采样率无效": "Invalid sample rate",
    "音频数据必须是 [采样点, 声道] 二维数组":
        "Audio data must be a 2-D [samples, channels] array",
    "有效区间掩码形状与音频不一致": "Valid-interval mask shape does not match the audio",
    "裁剪区间太短，至少需要 2 个采样点": "Crop interval too short — needs at least 2 samples",
    "源文件不存在：{source}": "Source file does not exist: {source}",
    "没有可写回的数据": "No data to write back",
    "数据含 NaN 或无穷值，已取消写回":
        "Data contains NaN or infinity; write-back cancelled",
    "包络分析数据过短或采样率无效": "Envelope input too short or sample rate invalid",
    "包络分析输入包含 NaN 或无穷值": "Envelope input contains NaN or infinity",
    "包络拟合的时间和幅值数组长度必须一致且至少为 2":
        "Envelope fit needs time and amplitude arrays of equal length and at least 2 points",
    "包络拟合没有足够的有效数据": "Not enough valid data for the envelope fit",
    "未知包络方法：{method}": "Unknown envelope method: {method}",
    "不支持的包络模型：{model}": "Unsupported envelope model: {model}",
    "指数包络拟合失败：{exc}": "Exponential envelope fit failed: {exc}",
    "WAV 文件不存在：{source}": "WAV file does not exist: {source}",
    "没有可写入的音频数据": "No audio data to write",
    "音频中含 NaN 或无穷值，无法导出": "Audio contains NaN or infinity, cannot export",
    "音频数据必须是非空的 [采样点, 声道] 数组":
        "Audio data must be a non-empty [samples, channels] array",
    "声道索引越界：{index}": "Channel index out of range: {index}",
    "傅立叶分析至少需要两个采样点和正采样率":
        "Fourier analysis needs at least 2 samples and a positive sample rate",
    "傅立叶分析输入包含 NaN 或无穷值": "Fourier input contains NaN or infinity",
    "窗函数的相干增益无效": "Invalid window coherent gain",
    "时频分析数据过短": "Too little data for the spectrogram",
    "不支持的窗函数：{window}": "Unsupported window: {window}",
    "双通道分析需要左右两个声道": "Two-channel analysis needs a left and a right channel",
    "双通道分析需要已知激励频率":
        "Two-channel analysis needs a known excitation frequency",
    "当前环境缺少 sounddevice，无法播放音频":
        "sounddevice is not available in this environment; cannot play audio",
    "没有可播放的数据": "Nothing to play",
    "处理中…": "Working…",
    "横纵轴长度不一致": "Axis lengths differ",
    "未扣除零时延标定；AGC 工作时幅值比不能直接当作结论。":
        "Zero-delay calibration not removed; with AGC active an amplitude ratio is not a "
        "conclusion on its own.",
    "开始处理": "Start",
    "{stem}_波形.png": "{stem}_waveform.png",
    "{stem}_幅值谱.png": "{stem}_spectrum.png",
    "{stem}_时频图.png": "{stem}_spectrogram.png",
    "界面语言": "Language",
    "切换后程序会自动重启以应用": "The program restarts automatically to apply a change",
    "需要重启": "Restart required",
    "语言已保存。请手动关闭并重新打开程序以应用新语言。":
        "Language saved. Close and reopen the program to apply it.",
})



# ---------------------------------------------------------------- 主窗口：AI 面板与提示
EN.update({
    "模型设置": "Model settings",
    "例如：分析当前数据，检测冲击并给出处理建议":
        "e.g. analyse the current data, detect transients and suggest what to do",
    "发送": "Send",
    "让 AI 总结当前处理并撰写说明": "Ask the AI to summarise this analysis",
    "AI 尚未配置": "AI not configured",
    "还没有填写 API Key 或模型名称。\n\n在“模型设置”里选择一个厂商预设"
    "（如 DeepSeek、Moonshot），只需填 API Key 即可使用。\n\n现在打开模型设置吗？":
        "No API key or model name yet.\n\nPick a vendor preset (DeepSeek, Moonshot, …) "
        "in Model settings — an API key is all you need.\n\nOpen model settings now?",
    "AI 正在分析…": "AI is analysing…",
    "模型返回后会自动显示结果": "The result appears as soon as the model responds",
    "AI 请求进行中": "AI request in progress",
    "请等待当前 AI 请求结束后再关闭程序。":
        "Wait for the current AI request to finish before closing.",
    "AI 设置或请求失败": "AI settings or request failed",
    "请调用所需工具分析当前数据，说明处理依据、结果和限制，供数据处理报告使用。":
        "Call the tools you need to analyse the current data, and explain the basis, "
        "results and limitations for the data report.",
})

# ---------------------------------------------------------------- 主窗口：操作反馈
EN.update({
    "正在读取并分析 WAV…": "Reading and analysing the WAV…",
    "已载入 {_v0}｜{_v1:.1f} s / {_v2} Hz；主频与 THD 基于受限窗口"
    "（详见傅立叶分析页），统计量使用完整选区。":
        "Loaded {_v0} | {_v1:.1f} s / {_v2} Hz; fundamental and THD use a limited window "
        "(see the Fourier tab), statistics use the full selection.",
    "正在重新分析当前声道…": "Re-analysing the current channel…",
    "主频 {_v0:.4f} Hz；主频峰值振幅 {_v1:.6g} FS；THD {_v2:.4%}；窗函数 {_v3}；"
    "FFT 点数 {_v4}。{scope} dBFS 不等于 dB SPL。":
        "Fundamental {_v0:.4f} Hz; peak amplitude {_v1:.6g} FS; THD {_v2:.4%}; "
        "window {_v3}; FFT size {_v4}. {scope} dBFS is not dB SPL.",
    " 分析窗口 {_v0:.3f}–{_v1:.3f} s（{_v2:,}/{_v3:,} 点，频率分辨率 {_v4:.4g} Hz）。"
    " 主频/THD 仅基于该窗口；RMS 等统计量使用完整选区。":
        " Analysis window {_v0:.3f}–{_v1:.3f} s ({_v2:,}/{_v3:,} points, "
        "resolution {_v4:.4g} Hz). Fundamental and THD use only this window; "
        "RMS and other statistics use the full selection.",
    "正在计算选区统计…": "Computing selection statistics…",
    "选区统计已更新": "Selection statistics updated",
    "长音频需要数秒，期间请不要关闭窗口":
        "Long recordings take a few seconds; please keep the window open",
    "统计失败": "Statistics failed",
    "正在检测冲击信号…": "Detecting transients…",
    "预览完成：{_v0} 段冲击（橙色曲线为预览，未写入数据）":
        "Preview ready: {_v0} transient(s) — the orange trace is a preview, nothing written yet",
    "检测 {_v0} 段：修复 {_v1}，排除 {_v2}。\n":
        "Detected {_v0} segment(s): {_v1} repaired, {_v2} excluded.\n",
    "已关闭去噪预览（橙色曲线），数据未做任何修改":
        "Preview discarded; no data was modified",
    "预览已关闭，处理数据未改动": "Preview discarded; processed data unchanged",
    "生成预览曲线": "Preview trace",
    "已应用到处理版本；原始 WAV 未修改":
        "Applied to the working copy; the original WAV is unchanged",
    "正在应用去噪结果…": "Applying the repair…",
    "已撤销上次处理": "Last edit undone",
    "没有可撤销的处理": "Nothing to undo",
    "正在计算包络并拟合…": "Computing envelope and fitting…",
    "包络已按选区（{span_text}）计算，绿色为包络，酒红色为拟合曲线。":
        "Envelope computed over the selection ({span_text}); green is the envelope, "
        "dark red is the fit.",
    "选区内有效包络点不足": "Not enough valid envelope points in the selection",
    "正在播放 {_v0:.3f}–{_v1:.3f} s（仅监听，不改动数据）":
        "Playing {_v0:.3f}–{_v1:.3f} s (monitoring only, no data changed)",
    "无法播放": "Cannot play",
    "当前系统没有可用的音频输出设备。": "No audio output device is available.",
    "播放失败": "Playback failed",
})

# ---------------------------------------------------------------- 主窗口：写回、导出与关闭
EN.update({
    "确认写回源文件": "Confirm writing back to source",
    "将把当前处理版本写回：\n{source}\n\n写入长度 {_v1:.3f} s（原文件 {_v2:.3f} s）。\n"
    "写回前会自动在同目录生成 .bak-时间戳 备份文件，原始内容不会立即丢失。\n\n是否继续？":
        "This will write the working copy to:\n{source}\n\nLength {_v1:.3f} s "
        "(original {_v2:.3f} s).\nA .bak-<timestamp> backup is created in the same folder "
        "first, so the original is not lost immediately.\n\nContinue?",
    "正在写回源文件…": "Writing back to source…",
    "已应用 {_v0} 次编辑（去噪/裁剪），当前长度 {_v1:.3f} s；"
    "可写回源文件或撤销（可撤销 {_v2} 级）。":
        "{_v0} edit(s) applied (repair/crop), current length {_v1:.3f} s; "
        "you can write back or undo ({_v2} level(s) available).",
    "已写回源文件": "Written back to source",
    "已写入：\n{source}\n\n备份文件：\n{backup}":
        "Written to:\n{source}\n\nBackup:\n{backup}",
    "先备份再覆盖，写入可能需要数秒":
        "Backup first, then overwrite; this may take a few seconds",
    "无需裁剪": "Nothing to crop",
    "当前选区已覆盖整个文件，请先框选需要保留的区间。":
        "The selection already covers the whole file; select the part you want to keep.",
    "裁剪失败": "Crop failed",
    "无源文件": "No source file",
    "当前数据不是从文件载入，无法写回。":
        "This data was not loaded from a file, so it cannot be written back.",
    "没有改动": "No changes",
    "当前处理版本与原始数据一致，无需写回。":
        "The working copy is identical to the original; nothing to write back.",
    "请先打开文件": "Open a file first",
    "请先打开一个 WAV 文件。": "Open a WAV file first.",
    "尚未载入音频": "No audio loaded",
    "正在做双通道时延分析…": "Running two-channel delay analysis…",
    "双通道分析": "Two-channel analysis",
    "双通道分析失败": "Two-channel analysis failed",
    "导出处理后 WAV": "Export processed WAV",
    "导出统计": "Export statistics",
    "生成独立报告": "Generate standalone report",
    "正在导出 WAV…": "Exporting WAV…",
    "正在生成 HTML 报告…": "Generating HTML report…",
    "正在导出分析 TXT…": "Exporting analysis TXT…",
    "正在导出波形图 PNG…": "Exporting waveform PNG…",
    "正在导出频谱图 PNG…": "Exporting spectrum PNG…",
    "正在导出时频图 PNG…": "Exporting spectrogram PNG…",
    "重算 dB 色标范围": "Recompute dB colour range",
    "导出分析 TXT…": "Export analysis TXT…",
    "导出图像 PNG…": "Export image PNG…",
    "导出当前统计 CSV": "Export statistics CSV",
    "生成独立 HTML 报告": "Generate standalone HTML report",
    "HTML 报告 (*.html)": "HTML report (*.html)",
    "包含波形、频谱与统计图表": "Includes waveform, spectrum and statistics charts",
    "分析结果尚未就绪，请稍候再导出":
        "Analysis is not ready yet; try exporting again in a moment",
    "已导出 {path}": "Exported {path}",
    "已导出 {result}": "Exported {result}",
    "已导出 {_v0}（{_v1:,} 行，{megabytes:.1f} MB，{_v3} 个章节）":
        "Exported {_v0} ({_v1:,} rows, {megabytes:.1f} MB, {_v3} sections)",
    "已导出 {_v0}（{size}，{_v2}）": "Exported {_v0} ({size}, {_v2})",
    "{_v0} 个章节，坐标步长 {_v1} 点": "{_v0} sections, coordinate stride {_v1}",
    "已生成 {path}": "Generated {path}",
    "已生成 {result}": "Generated {result}",
    "导出失败": "Export failed",
    "报告生成失败": "Report generation failed",
    "未命名.wav": "untitled.wav",
    "修改后文件（已编辑）": "Modified file (edited)",
    "源文件（未修改）": "Source file (unchanged)",
    "正在结束后台任务…": "Finishing background tasks…",
    "任务仍在收尾": "Task still finishing",
    "批量任务尚未结束，请稍等几秒后再关闭窗口。":
        "The batch has not finished; please wait a few seconds before closing.",
    "后台任务尚未结束，请稍等几秒后再关闭窗口。":
        "Background tasks have not finished; please wait a few seconds before closing.",
})

