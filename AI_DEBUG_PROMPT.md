# 交给另一个 AI 的纠错任务说明（可直接整份粘贴）

> 用法：把这份文件整份发给对方 AI，在最后的「本次任务」一节里写明你要它查哪一条。
> 它不需要任何额外背景，所有必需事实都写在下面。

---

## 0. 你的角色

你是接手一个**已经能跑的 Windows 桌面程序**的维护者。目标不是重写，而是在**最小改动**的前提下定位并修掉具体缺陷。这个项目已经交付到 v2.0.0，任何大范围重构都会被拒绝。

## 1. 项目速览

- 名称：**WAV Analyzer / 声音实验 WAV 数据处理程序**，版本 2.0.0，MIT 许可
- 位置：`D:\WAV_Analyzer`（所有命令都在这个目录下执行）
- 技术栈：Python 3.13 + PySide6（Qt 6.12）+ pyqtgraph + numpy/scipy/matplotlib + soundfile/sounddevice + httpx + keyring
- 形态：桌面 GUI；可打包成单文件 exe（PyInstaller）
- 入口：`run_app.py`；界面主体 `app/main_window.py`（2500+ 行，改动前务必先定位到具体方法）
- 目录职责：
  - `core/` 算法与导出：`audio_io` `spectral` `denoise` `envelope` `statistics` `calibration` `exporter` `txt_export` `data_export` `figure_export` `project` `batch` `batch_summary` `report_i18n` `i18n`
  - `app/` 界面：`main_window` `manual_viewer` `batch_dialog` `settings_dialog` `image_export_dialog` `txt_export_dialog` `data_export_dialog` `calibration_dialog` `anc_dialog` `chat_view` 等
  - `ai/` 可选的大模型助手（OpenAI 兼容接口）
  - `tests/` pytest，**285 项**；`demo/` 合成示例 WAV；`docs/` 手册 LaTeX 与配图

## 2. 这台机器的特殊事实（极其重要，会误导你）

以下不是推测，是实测结论。不按这些来做，你会在环境问题上浪费几个小时并得出错误结论。

1. **界面语言有两套**，切换语言会重启进程。`core/i18n.py` 以中文原文为键查 `core/i18n_en.py` 的字典；报告语言是另一套，在 `core/report_i18n.py`。
2. **设置文件是 INI**，固定在**程序所在目录**下的 `PhysicsExperiment\<应用名>.ini`。`run_app._configure_settings()` 必须在创建 `QApplication` **之前**调用，且 `QSettings` 只能用**无参**构造（`QSettings("组织","应用")` 这种两参数写法会忽略默认格式、强制走注册表）。
3. **这台机器的普通（非提权）进程写不了用户临时目录**，单文件 exe 会因此报 `Could not create temporary directory!`。所以：
   - 需要跑 GUI/打包产物时，把 `TEMP`/`TMP` 指向工作区内可写目录；
   - 文件夹版（onedir）不依赖临时目录，是验证功能时的首选。
4. **Smart App Control 处于开启状态**，对未签名程序的限制很可能就是上面那条的根因。不要通过"关掉它"来绕过——那不是代码修复。
5. **本机可能没有交互桌面**。跑 Qt 必须设 `QT_QPA_PLATFORM=offscreen`；但 offscreen **默认没有字体**，截图会全是方块，必须同时设 `QT_QPA_FONTDIR=C:\Windows\Fonts`。
6. **测试命令**（必须在可写临时目录的权限下跑，否则 pytest 的 tmp_path 夹具会全报 `PermissionError`，那不是代码 bug）：

   ```powershell
   $env:QT_QPA_PLATFORM='offscreen'
   .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --ignore=.venv --ignore=build --ignore=dist --ignore=_export_audit
   ```

7. **已知的环境性失败（不要去"修"）**：`tests/test_ai_ui.py::test_timeout_default_is_120s_and_ignores_old_key` 依赖注册表可写，在本机会失败。除此之外应当是 **284 passed**。
8. **i18n 有自动检查**：`tests/test_i18n.py::test_every_ui_string_has_english` 会扫描源码里所有 `tr()` / `tf()` 字符串，缺英文条目就失败。**新增任何界面文案，必须同时在 `core/i18n_en.py` 补英文**。报告/导出的文案走 `core/report_i18n.py` 的 `rt()/rtf()`，两套不要混用。
9. **打包**：两个 spec 都要能过——
   - `WAV_Analyzer.spec`（单文件）→ `dist\WAV Analyzer.exe`
   - `WAV_Analyzer_onedir.spec`（文件夹版）→ `dist\WAV Analyzer\`
   命令：`.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean <spec>`
10. **手册**：`docs/manual_detailed.tex`（中）与 `docs/manual_en.tex`（英），用 `xelatex` 编译两遍（`xelatex` 在 PATH 上）。改中文手册后要 `Copy-Item manual_detailed.pdf manual_zh.pdf`，因为程序内打开的是 `manual_zh.pdf`。
11. **配图脚本**在 `docs/make_*_shots.py`，支持 `SHOT_LANG=en` 输出到 `docs/figures_en/`；手册与 README 依赖这些图。

## 3. 铁律（违反会被立即中止）

这个项目所在机器**曾经因为误删用户目录导致 Windows 崩溃、被迫重装系统**。因此：

- **绝不**删除、移动、改名 `C:\Users\*`、OneDrive、AppData、桌面、文档等任何用户数据；**绝不**操作工作区以外的路径。
- **绝不**使用 `Remove-Item -Recurse` / `rd /s` / `del /s` 这类递归删除，也不要用通配符删除。
- 需要清临时产物时，**只删单个已确认绝对路径的文件/目录**，删前先打印路径核对。
- `.venv` 等目录可能是**符号链接/Junction**：对 Junction 做递归删除会**连目标一起删掉**。正确做法是 `cmd /c rmdir <路径>`（只摘链接）。
- **绝不**修改 ACL、所有者、组策略、注册表安全设置；不运行提权命令。
- **覆盖任何已有文件前先备份**（例如 `xxx.bak-<日期>`）。
- 不改系统设置、不装全局依赖、不往 PATH 里写东西。

## 4. 代码约定

- 所有面向用户的字符串都过 `tr()`（界面）或 `rt()`（导出/报告）；日志、异常、注释不翻译。
- 带变量的文案用 `tf("正在处理 {name}", name=...)`，不要用 f-string 先拼好（否则翻译查不到）。
- 导出物里的文字必须跟随**报告语言**（`rt`），不是界面语言。
- 中文手册与英文手册的结构一一对应，改一份要同步另一份。
- 新增 Qt 控件注意：本项目已全局拦截"下拉框/数字框上的滚轮"，滚轮一律转给外层滚动区；不要破坏这个行为。
- 界面里的 `QSettings` 一律用无参 `QSettings()`。

## 5. 当前状态（v2.0.0，最近一批改动）

已完成并在源码中生效、但**尚未全部打进发布包**：

1. 新增文件夹版（onedir）构建，启动不依赖临时目录。
2. 设置改存 INI，位置固定为程序目录，保存后读回校验。
3. 手册窗口：页码改为可输入的 `QSpinBox`（原来上限 1–2 页）、跳页改用 `pageNavigator.jump()`（原来把"点"当"像素"累加）、修掉页码框与视图互相触发的死循环。
4. 滚轮不再被下拉框/数字框/页签栏吞掉，改为**转发给外层滚动区**。
5. 「保存工程 / 打开工程」改用 Qt 自带对话框（`DontUseNativeDialog`），绕开本机损坏的系统外壳。
6. 批量处理脚本：关闭窗口即记住步骤与输出目录（原来只有点"开始"才存）。
7. 导出的图例文字（当前波形、振幅谱、谱峰标注、谐波标记、相位谱、时频图、选区、游标等）接入报告翻译层。

待验证/待做的已知项：

- **单文件版在普通权限下仍会因临时目录不可写而启动失败**（文件夹版正常）。这是环境限制还是 Smart App Control 所致，尚未定论。
- 「导出当前统计 CSV」的英文覆盖**没有单独实测**（TXT/HTML/CSV×3/NPZ/SVG/PDF 已实测 10/10 通过）。
- PNG 里的文字是像素，无法自动扫描，只能通过 PDF/SVG 的同源标签间接确认。
- 发布包 zip 的校验值与源码可能不同步，重打包后需更新 `docs/release_notes_v2.0.0.md` 里的 SHA-256 与 `CHANGELOG.md`。

## 6. 工作方式要求

1. **先读后改**：定位到具体函数再动手，禁止"整体重写某个模块"。
2. **最小 diff**：只改与缺陷直接相关的行；不要顺手格式化、不要重命名现有变量/函数、不要升级依赖。
3. **可验证**：每个修复都要能用测试或一段可复现脚本证明（贴出命令与输出）。若必须改测试，说明原测试为什么过时。
4. **同步文档**：改动影响用户可见行为时，更新 `CHANGELOG.md` 对应的 2.0.0「修复 / Fixed」小节，并保持中英双语。
5. **报告格式**：给出「现象 → 根因（含证据）→ 改动文件与行号 → 验证方式与结果 → 风险」五段。**没有证据的猜测要标明是猜测。**
6. 不要修改 `.github/workflows/build-sign.yml` 里 SignPath 的占位符配置，除非任务明确要求。

## 7. 本次任务

（在这里写你要它查的具体问题。建议把用户原话、截图说明、复现步骤、以及"我以为是什么原因"一起给它。）

**待查问题：**

- 现象：
- 复现步骤：
- 期望行为：
- 我的初步判断：
- 相关文件（如果知道）：

---

## 附：常用命令速查

```powershell
cd D:\WAV_Analyzer

# 跑测试（务必先设 offscreen，并确保临时目录可写）
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider `
    --ignore=.venv --ignore=build --ignore=dist --ignore=_export_audit

# 从源码启动界面
.\run_app.bat

# 打包（两种形态）
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean WAV_Analyzer.spec
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean WAV_Analyzer_onedir.spec

# 打包后自检（结果写到该 wav 同目录的 selftest_result.json）
$env:WAV_ANALYZER_SELFTEST='D:\WAV_Analyzer\demo\demo_tone.wav'
& 'D:\WAV_Analyzer\dist\WAV Analyzer\WAV Analyzer.exe'

# 英文导出审计（10 项逐字扫中文）
.\.venv\Scripts\python.exe _export_audit\run_audit.py
```
