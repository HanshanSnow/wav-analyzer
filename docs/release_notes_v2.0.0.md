# Wav Analyzer V2.0.0

A Windows desktop tool for **acoustic measurement WAV data**. Version 2.0 turns the single-file analysis workflow into a reproducible one: FLAC / AIFF and multi-channel input, a denoising toolbox with guard rails, vector figures, raw-data export, `.wavproj` project files, and batch runs that end in a comparison table instead of a folder of loose outputs.

一款处理**声学测量 WAV 数据**的 Windows 桌面程序。2.0 把「单个文件分析」变成「可复现的流程」：FLAC / AIFF 与多声道输入、带护栏的降噪工具组、矢量图、原始数据导出、`.wavproj` 工程文件，以及跑完直接给出对比表的批量处理。

## Downloads

| File | Size | Notes |
| --- | --- | --- |
| `WAV_Analyzer_v2.0.0_win64_onedir.zip` | 120.8 MB | **Recommended.** Folder build — `WAV Analyzer\` with an `_internal\` directory. Startup never touches the temp directory and the first launch is faster |
| `WAV_Analyzer_v2.0.0_win64_onefile.zip` | 119.6 MB | Single-file build — one `WAV Analyzer.exe`. Handy to copy around, but it unpacks into the temp directory on first launch |
| `WAV_Analyzer_Manual_EN_v2.0.0.pdf` | 2.4 MB | English manual |
| `WAV_Analyzer_Manual_v2.0.0.pdf` | 3.3 MB | Chinese manual |

Portable: unpack anywhere, double-click `WAV Analyzer.exe`. No Python, no installer, no admin rights. The first launch is slower because the single-file build unpacks itself.

免安装：解压到任意目录，双击 `WAV Analyzer.exe`。不需要 Python、不需要管理员权限。单文件版首次启动稍慢，属正常。

## Requirements

Windows 10 or 11, x64, 8 GB RAM or more. A GPU with normal graphics acceleration is recommended — the interface plots in real time. Everything except the AI assistant works fully offline.

Windows 10/11 x64、8 GB 以上内存；界面实时绘图，建议有正常图形加速的显卡。除 AI 助手外全部功能离线可用。

## What is new in 2.0

**Input and export**

- FLAC and AIFF input, plus channel selection for recordings with more than two channels.
- Vector figure export: PDF and SVG alongside PNG.
- Raw-data export: spectrum, spectral-peak and envelope CSVs, and the spectrogram matrix as NPZ.
- Batch trim can take its start and end times straight from a waveform selection.
- After a batch run: a comparison table, grouped statistics and comparison figures.

**Analysis and DSP**

- Selectable window function for the spectrum and the spectrogram.
- Denoising toolbox: synchronous averaging, zero-phase notch, and four adaptive cancellation methods — each with guard rails and an uncertainty estimate. A method refuses to change the data when its evidence is insufficient.

**Workflow**

- `.wavproj` project files keep the source files, the recipe and the settings, never the processed samples — a session reopens without a pile of intermediate WAVs.
- The manual opens and searches inside the program (QtPdf).
- Report language is independent of the interface language.
- The single-file build no longer flashes a black console window at startup.

**本版新增**

- 输入：FLAC / AIFF，多声道录音可选择声道
- 导出：矢量 PDF / SVG；频谱、谱峰、包络 CSV；时频矩阵 NPZ
- 批量：裁切可直接取波形选区的起止时刻；跑完给出对比表、分组统计与对比图
- 分析：频谱与时频图可选窗函数
- 降噪工具组：同步平均、零相位陷波、四种自适应抵消，均带护栏与不确定度；证据不足时拒绝改动数据
- 流程：`.wavproj` 工程文件（只存配方与设置，不存采样数据）；程序内打开并搜索手册；报告语言独立于界面语言；启动不再弹出黑色控制台窗口

## Checksums (SHA-256)

```
972d8fbb85939bd5f9f5d3ee72a3565dedcc7bad7a385fa3829362619b85cd05  WAV_Analyzer_v2.0.0_win64_onedir.zip
ee330e1f6fc23abc71d59e217ba70f0daaa314041c1c44e7645c805b2ef8ea28  WAV_Analyzer_v2.0.0_win64_onefile.zip
819b160663d63c5a742f7590220cf3c35b93541b793f764e31de61a0cee76dee  WAV_Analyzer.exe  (inside the onefile zip)
d369f797381c2abb66303aedb26387c590ae0cbc3bceb359efd726cf87627ad7  WAV_Analyzer_Manual_EN_v2.0.0.pdf
5407f0ac17941bfaf1f182093c86ea9db0e0348a1513d586a9b929a16f07644e  WAV_Analyzer_Manual_v2.0.0.pdf
```

Verify with `certutil -hashfile "WAV Analyzer.exe" SHA256` (PowerShell / cmd).

## Known limitations

- The automatic impulse-detection and denoise thresholds are validated on synthetic signals; on real recordings review the preview and adjust by hand.
- Calibration assumes a single scalar `K` for the whole chain — it does not model frequency response, weighting curves, or AGC behaviour. The manual states when the conversion does not hold.
- The AI assistant sends the numbers you attach to the conversation to whichever endpoint you configure. Do not enable it on data you cannot share.
- The program is not code-signed. Windows SmartScreen may warn on first launch; choose "More info" → "Run anyway".
- **Smart App Control** — a freshly installed Windows 11 usually switches it on, and it warns about *every* unsigned program, this one included. The prompt depends on the machine, not on the release: 1.6.1 gets the same warning on such a system, and none where the feature is off. Click "Run" / "More info → Run anyway", or turn Smart App Control off under *Settings → Privacy & security → Windows Security → App & browser control*. That switch is one-way: re-enabling it needs a Windows reinstall.

## 已知限制

- 冲击检测与降噪的自动阈值在合成信号上验证过，真实录音请先看预览再手动调整。
- 校准使用整条链路的单标量 `K`，不含频响、计权与 AGC 行为；手册写明了什么情况下这个换算不成立。
- AI 助手会把对话里附带的数值发给你配置的服务端，敏感数据请勿开启。
- 程序未购买代码签名证书，首次启动可能出现「Windows 已保护你的电脑」提示，选「更多信息」→「仍要运行」。
- **智能应用控制**：全新安装的 Windows 11 通常开着它，会对**任何**未签名程序告警，本程序也不例外。弹不弹取决于机器而不是版本——1.6.1 在同样的系统上一样会弹，在关掉该功能的机器上一样不弹。点「运行」/「更多信息 → 仍要运行」即可；也可以在「设置 → 隐私和安全性 → Windows 安全中心 → 应用和浏览器控制」里关闭。该开关是单向的，想重新打开只能重装系统。

## Upgrading from 1.6.1

Same portable layout — replace the old `WAV Analyzer.exe` with the new one. `.wavproj` files are new in 2.0; older sessions have no project file to migrate.
