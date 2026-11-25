# Privacy Policy / 隐私政策

WAV Analyzer is a local desktop application. This page describes exactly what leaves the
machine, and when.

WAV Analyzer 是一个本地运行的程序。下面说明什么情况下会有数据离开这台机器。

## What is never collected

- **No telemetry, no analytics, no crash reporting.** The program does not contact any server
  on its own.
- **No account, no sign-in.** There is no user identifier.
- **Audio files stay local.** Opening, analysing, denoising, batch processing and every export
  read and write files only on this machine.

## 本程序不会收集

- 没有任何遥测、统计或崩溃上报；程序不会自行连接任何服务器
- 没有账号与登录，也没有用户标识
- 音频文件始终留在本机：打开、分析、降噪、批量处理与所有导出都只读写本地文件

## When data is sent, and where

Only one feature sends anything: the **AI assistant**, and only after you configure it.

- You choose the endpoint (base URL), the model and the API key yourself. The key is stored in
  the Windows Credential Manager, not in a plain file.
- When you send a question, the program transmits: your prompt, and the numbers you attach to
  the conversation (for example a spectrum summary or statistics from the current file).
- The destination is the endpoint **you** configured; the project maintainer operates no
  server and receives nothing.
- If the assistant is not configured, or you never send a message, no network request is made.

## 什么情况下会发送数据

只有**AI 助手**，且必须由你自己配置之后才会联网：

- 端点地址、模型与 API Key 由你填写；Key 保存在 Windows 凭据管理器，不写入明文文件
- 发送提问时，程序会发出：你的问题，以及你挂到对话里的数值（例如当前文件的频谱摘要或统计量）
- 接收方是**你配置的**端点；本项目维护者不运营任何服务器，也收不到任何内容
- 未配置助手，或你从不发送消息，就不会有任何网络请求

## Local files the program writes

- Settings: `<program folder>\PhysicsExperiment\<app>.ini`, falling back to
  `%LOCALAPPDATA%\WAV Analyzer`.
- Project files (`.wavproj`): the source path, the processing recipe and the analysis settings.
  Processed samples are never stored.
- Everything else you create (WAV / TXT / CSV / PNG / PDF / HTML) is written where you choose.

## 程序会写哪些本地文件

- 设置：`<程序目录>\PhysicsExperiment\<程序名>.ini`，不可写时退回 `%LOCALAPPDATA%\WAV Analyzer`
- 工程文件 `.wavproj`：源文件路径、处理配方与分析设置；不保存处理后的采样数据
- 其余文件（WAV / TXT / CSV / PNG / PDF / HTML）只写到你选择的位置

## Changes

Any change to the statements above will be committed to this file in the repository, with the
date recorded in `CHANGELOG.md`.

## 变更

以上内容的任何变化都会提交到仓库中的本文件，并在 `CHANGELOG.md` 中记录日期。
