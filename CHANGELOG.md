# 更新日志 / Changelog

WAV Analyzer 的版本记录。每条先英文、后中文。
Release notes for WAV Analyzer. English first, Chinese below.

程序不写注册表与系统目录，解压到任意目录即可运行。
The program writes nothing to the registry or system directories; unpack it anywhere.

---

## 2.0.0 — 2026-11-22

### English

**Input and export**
- FLAC and AIFF input, plus channel selection for recordings with more than two channels.
- Vector figure export: PDF and SVG alongside PNG.
- Raw-data export: spectrum, spectral-peak and envelope CSVs, and the spectrogram matrix as NPZ.
- Batch trim can take its start and end times straight from a waveform selection.
- After a batch run: a comparison table, grouped statistics and comparison figures.

**Analysis and DSP**
- Selectable window function for the spectrum and the spectrogram.
- Long recordings now show the file info and waveform first; the spectrum, spectrogram and statistics appear as they finish in the background, and the window stays usable meanwhile.
- Adjustable spectral-peak count (1–100, default 8) for the peak table, the TXT/CSV peak lists and the figure annotations; the FFT, main frequency and THD are unchanged.
- Denoising toolbox: synchronous averaging, zero-phase notch, four adaptive cancellation methods, and an independent noise profile — each with guard rails and an uncertainty estimate.
- **External reference channel**: the cancellation methods can take their reference from a separate WAV file instead of the second track. A channel index is chosen explicitly and saved with the project and the batch script; unequal lengths are processed on the overlapping span only, and a misaligned onset (beyond 1 ms) is refused rather than silently used.
- **Independent noise profile**: for noise recorded separately from the target (different clocks, two sessions, reference longer or shorter). It estimates one static noise spectrum from the reference and applies a decision-directed, time-smoothed Wiener gain; it refuses non-stationary references, references containing the excitation tone, and settings that would move the fundamental by more than 1 dB.

**Workflow**
- `.wavproj` project files keep the source files, the recipe and the settings, never the processed samples.
- The manual opens and searches inside the program (QtPdf).
- Report language is independent of the interface language.
- The single-file build no longer flashes a black console window at startup.

### 中文

**输入与导出**
- 新增 FLAC 与 AIFF 输入，多声道录音可选择声道
- 图像可导出矢量 PDF / SVG
- 新增原始数据导出：频谱 / 谱峰 / 包络 CSV，时频矩阵 NPZ
- 批量裁切可直接从波形选区取起止时刻
- 批量处理后可查看对比表、分组统计与对比图

**分析与算法**
- 频谱与时频图可选窗函数
- 长录音打开时先显示文件信息与波形，频谱、时频图与统计量随后在后台算完再填入（期间界面可用）
- 频谱图的谱峰数量可调（1–100，默认 8）：影响谱峰表、TXT/CSV 的谱峰列表与图注，不改 FFT、主频与 THD
- 新增降噪工具组：同步平均、零相位陷波与四种自适应抵消，均带护栏与不确定度
- **外部参考通道**：抵消类方法可以从单独的 WAV 文件读参考，而不必用第二路声道。声道号需显式选择，并随工程文件与批量脚本一起保存；长度不同时只处理重叠段；起点相差超过 1 ms 会直接拒绝，而不是悄悄用错数据
- **独立噪声画像**：适合与目标分开录制的噪声（不同采样时钟、两次录音、参考更长或更短）。它从参考估计一份静态噪声谱，再用决策定向、时间平滑的 Wiener 增益处理目标；参考不平稳、参考里含激励音、或会改变主频超过 1 dB 时都会拒绝应用

**流程**
- 新增 `.wavproj` 工程文件：只存源文件路径、操作配方与设置，不存处理后的采样数据
- 程序内可直接打开并搜索手册
- 报告语言可独立于界面语言切换
- 启动不再弹出黑色控制台窗口

### 修复 / Fixed

- 英文界面下打开「模型设置」会抛 `KeyError` 直接崩溃：厂商预设拿翻译后的名字当字典键，英文模式下 `tr("DeepSeek（深度求索）")` 返回 `"DeepSeek"`，查不到键。现在预设键是稳定标识，显示名单独翻译；顺带补上 Moonshot 缺失的英文条目。
- 英文手册与英文 README 的界面配图此前用的是中文截图。现在有独立的英文配图（`docs/figures_en/`），配图脚本支持 `SHOT_LANG=en`，`manual_en.tex` 的 `\graphicspath` 优先取该目录。
- Opening *Model settings* in English crashed with a `KeyError`: vendor presets were looked up by their translated name. Preset keys are now stable identifiers, the display name is translated separately, and the missing Moonshot translation was added.
- The English manual and English README used Chinese screenshots. They now have their own figure set (`docs/figures_en/`); the figure scripts take `SHOT_LANG=en`.

- 新增**文件夹版（onedir）**发布包：程序文件平铺在 exe 旁边，**启动不依赖系统临时目录**。单文件版在临时目录不可写的机器上会报 `Could not create temporary directory!`，文件夹版可直接绕过；两份手册与 README 都写明了如何选择。
- 设置改存本地 INI 文件（程序目录下的 `PhysicsExperiment\`，不可写时回退系统存储）。此前用注册表，在部分机器上写入静默失败，表现为「切成英文重启还是中文」「改过的设置重开就没了」「批量脚本记不住」。
- 修复手册窗口：页码框换成可输入的数值框（原来上限只有 1–2 页）、跳页改用 `pageNavigator.jump()`（原来把「点」当「像素」累加，跳 30 页会落到 17 页）、修掉页码框与视图互相触发的死循环。
- 滚轮不再被下拉框/数字框/页签栏截获：滚轮一律转交给左侧面板滚动，数值只能点开或用方向键修改。
- 「保存工程 / 打开工程」改用 Qt 自带对话框，绕开系统外壳（本机 `explorer.exe` 报 `0xC0000142` 时外壳会谎报「没有权限」）。
- 批量处理脚本：关窗口即记住本次步骤与输出目录（原来只有点「开始」才存），并保留「保存脚本… / 载入脚本…」的 JSON 导出。
- 图像导出的图例文字此前硬编码中文（当前波形、原始波形、去噪预览、包络、拟合曲线、选区、游标、振幅谱、谱峰标注、谐波标记、相位谱、时频图），英文模式下导出图仍是中文；现已全部接入报告翻译层。
- Added a **folder (onedir) build** that never touches the temp directory, fixed settings persistence by moving to an INI file, repaired the in-app manual's page navigation and search, stopped combos/spinboxes from swallowing the mouse wheel, switched the project dialogs to Qt's own file dialog, made the batch script remember itself on close, and translated the figure legends that were hard-coded in Chinese.

### 修复：代码审查发现的 22 项缺陷 / Fixed: 22 defects from a code audit

- **数据正确性**：切换声道后，上一声道的去噪预览仍可被应用到新声道；撤销后保存工程仍会重放已撤销的操作；写回源文件后保存工程会对新基线重复执行同一操作；打开工程时选区被重置为全文件。
- **批量处理**：不同目录的同名 WAV 会静默覆盖导出文件（现自动加 `_2` 序号）；去噪/裁剪后统计、频谱、双通道、包络与拟合缓存未完整失效；双通道步骤始终分析原始音频而非当前样本；取消后仍把未写入的合并 CSV 列进结果。
- **算法**：长音频跳帧 STFT 比正常分支高 6.02 dB、时间戳提前半个窗长；RMS 窗长大于输入时包络与时间轴长度不等；3 点 FFT 漏掉正频率 bin 的单边谱倍增；长选区的分析窗口时间缺少选区起点。
- **线程与界面**：降噪工具组的工作线程直接读取 Qt 控件；已完成的 AIWorker 不释放并持续持有音频快照；"测试连接"在界面线程同步等待网络。
- **导出与校准**：TXT 原坐标表把极小非零值压成 `+0.000000`、把 NaN 写成 `-inf`；NPZ 自动补扩展名后返回路径与实际文件不一致；非有限校准参数可让 `.ready` 抛数学域异常。
- **脚本与测试**：`record.py` 检测到单声道设备后仍请求双声道录音；`analyze.py` 手工拼 CSV，文件名含逗号时列错位；批量对话框测试不释放 Qt 对象，导致 pytest 打印通过后仍以 `0xC0000409` 退出（现 `284 passed` 且退出码为 0）。
- 任务栏与窗口图标改为程序自己的图标（此前显示的是宿主进程 pythonw / 打包引导器的图标）。
- Data correctness on channel switching, undo and apply-to-source; batch output collisions, stale caches, dual-channel input and cancelled CSV bookkeeping; STFT branch scaling and timestamps; thread-safety in the ANC worker and AI worker lifecycle; TXT/CSV/NPZ/calibration edge cases; and a test-suite leak that made pytest exit with `0xC0000409` after reporting success.

### 校验 / Verification

- 自动化测试 285 项（`tests/`），覆盖核心算法、界面交互、界面语言、大文件处理流水线、批量流水线、声学校准、图像导出、文本导出与报告导出。
- 285 automated tests (`tests/`) covering core algorithms, GUI interaction, UI language, large-file pipelines, batch pipelines, acoustic calibration, and the image / text / report exporters.
- 自动去噪阈值仅在合成信号上验证，真实录音请先看预览再手动调整。
  The automatic denoise threshold is validated on synthetic signals only; review the preview on real recordings.

---

## 1.6.1 — 2026-11-20

- 修复打包版启动即报错：单文件版缺 `PySide6.QtOpenGL` / `QtOpenGLWidgets`，界面模块无法加载（源码运行不受影响）；自检改为真正 import 界面模块。
- 切换界面语言后重启，退出时不再弹「Failed to remove temporary directory」：子进程不再继承父进程的 `_MEIxxxx` 临时目录指针。
- AI 助手改为流式接收：超时含义变为「连续 120 s 没有新数据」，提示会附带已收到的字数。
- Fixed the packaged build crashing at startup on some machines (missing `PySide6.QtOpenGL` / `QtOpenGLWidgets`), the stray PyInstaller temp directory after a language-switch restart, and long AI answers being reported as timeouts (now streamed).

## 1.6 — 2026-11-18

- 界面新增中英双语：左侧栏底部切换，重启生效；按钮、分组、页签、提示与错误信息全部英文化；导出文本与报告正文仍为中文（定宽排版按中文列宽调校）。
- 文档同步双语化，README 分英文主文档与中文版。
- Bilingual interface (Chinese / English), switchable at the bottom of the left sidebar; documentation made bilingual too.

## 1.5 — 2026-11-16

- 新增声学校准：按灵敏度 / 前置增益 / 满幅电压推算偏移 `K`，或用已知声压级标定；统计、CSV、TXT、HTML 报告与批量处理同步输出 dB SPL；未校准时不出声压级。
- Acoustic calibration: derive `K` from sensitivity / preamp gain / full-scale voltage, or calibrate against a known SPL. No SPL is printed when uncalibrated.

## 1.4 — 2026-11-14

- AI 助手：提问与回答改用不同底色气泡，回答按 Markdown 渲染；Key 固定存 Windows 钥匙串；默认超时 120 s，并对超时、连接、鉴权失败分别提示；AI 去噪确认只问一次。
- AI assistant: distinct chat bubbles, Markdown rendering, key stored in the Windows credential store, 120 s default timeout with distinct error messages.

## 1.3 — 2026-11-12

- 新增批量处理：可保存的步骤脚本、多选文件只记路径、独立线程执行、模糊遮罩与逐文件进度、取消只在文件之间生效；TXT 与 CSV 支持合并为一个文件。
- Batch processing: reusable step scripts, worker-thread execution, per-file progress, cancel between files, and merged TXT/CSV output.

## 1.2 — 2026-11-08

- 新增导出分析 TXT：七段结构、定宽 ASCII 对齐、坐标取法三选项、区间统计多选，附源 WAV 的 MD5 指纹。
- 图像导出新增论文版式（单栏 3.50×2.45 in、双栏 7.00×2.60 in、600 dpi、刻度朝内四边齐全、次刻度），图例统一移到坐标区外图底一行。
- Fixed-width TXT export with MD5 fingerprint of the source WAV; paper-ready figure layouts at 600 dpi.

## 1.1 — 2026-11-05

- 新增裁剪、播放试听与应用更改到源文件；新增导出图像 PNG；区间统计改为中文名、数值、含义三列；冲击检测改为分块计算，长音频不再假死。
- Trim, playback preview and apply-to-source; PNG figure export; block-wise impulse detection for long files.

## 1.0 — 2026-11-03

- 首个可用版本：去噪、傅立叶分析、时频分析、包络拟合、区间统计、双通道分析、AI 助手与报告导出。
- First usable version: denoising, Fourier and time-frequency analysis, envelope fitting, interval statistics, dual-channel analysis, AI assistant and report export.
