# 工作留痕 / Detailed Changelog

> **两个文档的分工（别混）**
>
> | 文档 | 给谁看 | 写什么 |
> |---|---|---|
> | `CHANGELOG.md` | 用户 / 发布页 | 更新日志：这一版**能用上**的新功能与修复，简洁、双语、不写内部实现 |
> | `DetailedChangelog/Detailed_CHANGELOG.md`（本文件） | 我们自己 / 将来接手的人 | 工作留痕：为什么这么改、当时看到的证据、跑过的命令与结果、踩过的坑与被回滚的尝试 |
>
> **约定**：每次改动在本文件追加一条（最新在上），并在 `CHANGELOG.md` 里补一条用户视角的条目。
> 本文件追求"下次遇到同样问题时能看懂当时发生了什么"，允许写失败与试错。

---

## 2026-11-27 (upload) — Published 2.0.0 to GitHub

- **Repository**: https://github.com/HanshanSnow/wav-analyzer (existing repo, previously v1.6.1).
  The 2.0.0 work was placed **on top of** the existing history
  (`5642d7d` → `95e9051`), not as a new root commit: `git reset --soft origin/main` followed by
  one commit. Diff against v1.6.1 was verified first: **0 files removed**, 60 added.
- **Release**: https://github.com/HanshanSnow/wav-analyzer/releases/tag/v2.0.0 — 4 assets:
  - `WAV_Analyzer_v2.0.0_win64_onedir.zip` (120.8 MB, recommended)
  - `WAV_Analyzer_v2.0.0_win64_onefile.zip` (119.6 MB)
  - `WAV_Analyzer_Manual_EN_v2.0.0.pdf` (2.4 MB)
  - `WAV_Analyzer_Manual_v2.0.0.pdf` (3.3 MB)
- **Release notes corrected before publishing**: the stored notes still carried the *previous*
  build's sizes (136.0 / 124.9 MB) and five stale SHA-256 values. Both the Downloads table and
  the Checksums block were replaced with the measured values of this build
  (onedir `972d8fbb…`, onefile `ee330e1f…`, exe `819b1606…`). Publishing them unchanged would
  have shipped wrong checksums.
- **Environment problems met and worked around**:
  - `git` with the default schannel backend fails here with
    `SEC_E_NO_CREDENTIALS (0x8009030e)`, even for public repos → `git config http.sslBackend openssl`.
  - The first push died with `Recv failure: Connection was reset`; HTTP/1.1 plus a larger
    `http.postBuffer` made it go through. Later pushes hit the same reset again, so the final
    one-file notes fix went in through the GitHub **Contents API** (`c14130a`) instead.
  - `git` refuses the working tree because `D:\WAV_Analyzer` is owned by the pre-reset SID;
    resolved with `git config --global --add safe.directory` (a git setting — no ACL was changed).
- **Local state**: branch `main` is level with `origin/main` at `c14130a`.

---

## 2026-11-27 (final) — Packaging, archival copy, workspace cleanup

- **Release archives** (in `release/`, not uploaded):
  - `WAV_Analyzer_v2.0.0_win64_onefile.zip` — 119.6 MB, single entry `WAV Analyzer.exe`.
  - `WAV_Analyzer_v2.0.0_win64_onedir.zip` — 120.8 MB, 1327 entries under
    `WAV Analyzer/`, verified to contain `WAV Analyzer.exe`, `_internal/docs/manual_zh.pdf`
    and `_internal/wav_analyzer.ico`.
- **Archival copy** to `D:\xsh\学业资料\SJTU\物理实验导论\11-Sound Isolation\WAV Analyzer\`:
  `CHANGELOG.md`, `Detailed_CHANGELOG.md`, `WAV Analyzer.exe` (onefile) and
  `WAV Analyzer (目录版)\` (complete onedir tree). Copy only — nothing at that path was deleted.
- **Cleanup** (all paths asserted to be inside `D:\WAV_Analyzer` before deletion):
  - `build/` (PyInstaller work dir, 201 MB), `_pytest_mpl_cache/`, build logs;
  - 30 stray directories left by probe scripts and pytest, because earlier runs redirected
    `TEMP` into the workspace: `tmp*` (probe WAVs), `wav_selftest_*`, `pytest-of-*`,
    `matplotlib-a_*`, plus a root `selftest_result.json` — 30.3 MB total;
  - `__pycache__` under `core/app/tests/docs/ai/_archive`.
  - Kept: `.venv`, `dist/`, `release/`, `docs/`, `demo/`, `data/`, `calib/`,
    `matplotlib-cache/`, `_archive-20261123/` (pre-change backups), `_acl-recovery/` (ACL repair
    evidence) and `_export_audit/run_audit.py`.
- **Could not remove** `.pytest_cache/`: deletion is denied by the directory ACL and the policy
  is to never edit ACLs, so it stays and is harmless.
- Workspace (excluding `.venv`) is now ≈1.05 GB, of which `_archive` 392 MB and `dist` 396 MB.

---

## 2026-11-27 (late night) — Rebuilt both executables and ran the frozen selftests

- **Builds (PyInstaller 6.22.3, `--noconfirm --clean`)**
  - onedir: `dist/WAV Analyzer/WAV Analyzer.exe` — 17.8 MB, built 18:34:50
  - onefile: `dist/WAV Analyzer.exe` — 120.3 MB, built 18:36:36
  - Both specs unchanged (`upx=False`, icon in `EXE(icon=...)` and in `datas`).
- **Frozen selftest** (`WAV_ANALYZER_SELFTEST=<wav>`, TEMP/TMP pointed at a workspace dir):
  - onedir: `ok=true`, `manual_pdf_present=true`, `icon_present=true`, `gui_import=ok`,
    `i18n_ok=true` (923 entries), `qt_opengl`/`qt_pdf` both present, `output_devices=12`,
    `keyring_backend=WinVaultKeyring`.
  - onefile: same flags all true; the manual is read from the extracted `_MEI…\docs`
    directory, which is exactly the path the earlier TEMP failure would have broken.
- **Measured wall time, 3 runs each** (process start → selftest written, warm OS cache):
  - onedir 4.22 / 4.17 / 4.18 s, median **4.18 s**
  - onefile 6.32 / 6.55 / 6.57 s, median **6.55 s**
  - This is the full selftest (imports + load + PNG/PDF/HTML/TXT exports), **not** the GUI
    first-frame time; it does show the onefile extraction costs ≈2.4 s on this machine.
- **Icon check**: `ExtractAssociatedIcon` from both new executables still yields the navy
  waveform design (32×32) — the rebuild did not regress the icon.
- **Not uploaded** per instruction; no zips created, `release/` still empty. Artifacts remain
  in `dist/` only.
- **Still unverified**: real-desktop GUI interaction, audio playback on real hardware, the
  SignPath signing flow, and cold-start (reboot) numbers.

---

## 2026-11-27 (night) — Audit round: P0 lost requests, P1 short-target length, P1 blocking reference I/O

### P0 — The latest async load/refresh request was silently dropped

- **Root cause**: `load_audio_async()` / `refresh_all_async()` advanced the generation
  (invalidating in-flight results) and then called `run_task()`, which returns `False` when a
  worker is already running. The user's newest request was neither queued nor honoured.
- **Proof on the old behaviour** (by forcing `_request_async` to call the starter directly):
  requesting B while A was analysing left `audio=b.wav` but `fourier=None` and the tabs stuck
  on "…" — the symptom the user reported.
- **Fix**:
  - a single **latest-wins pending slot** (`_request_async` / `_drain_pending`); the newest
    request replaces older ones and starts in `_task_finished`, i.e. only after the previous
    worker has really released `self.task`;
  - `_task_succeeded` now receives **its own worker and handler**; a result from a worker that
    is no longer current is discarded. The previous shared `_task_handler` slot could hand a
    late result to a newer callback;
  - analysis snapshots (samples/mask/selection) are taken when the worker actually starts, not
    when the request is queued, so an undo/crop in between cannot produce a mixed state;
  - failures clear the tab ellipses, and `closeEvent` drops any pending starter.
- **Tests**: `tests/test_async_request_queue.py` (gated worker: A→B load, and a channel switch
  during analysis), both assert the final state is loaded **and analysed**, tabs are clear and
  no worker remains.

### P1 — `noise_profile` changed the sample count of short targets

- Padding for the STFT leaked into the output: input 100 → output 1024. Fixed by remembering
  `original_size` and slicing back (plus a defensive pad if `istft` comes out short).
- The tone-amplitude guardrail now only runs when the target is at least one frame long; on
  dozens of samples the single-bin estimate is dominated by leakage and produced false
  1–2 dB "damage" verdicts.
- Tests at 31/32/100/1023/1024/1025 samples assert exact output length, finite values and the
  `<32` rejection; one test goes through `run_method` to prove the engine keeps the shape.

### P1 — Reference validation and hashing blocked the GUI thread

- `AncToolsDialog` now validates in a `_ReferenceProbe` QThread with a token: file/channel
  changes immediately mark "validating…" and a late result for an older file is ignored.
  Measured: with a mocked 400 ms `load_reference`, `_sync_reference` returns in <200 ms.
- `_revalidate_reference_after_load()` no longer decodes; it compares **size + mtime**
  (`file_identity`) and clears the reference when the file was replaced.
- Project restore compares the stored `size`/`mtime_ns` first; only legacy projects without
  identity fields fall back to one-off hashing.
- New `ReferenceCache` (identity-keyed, 4 entries) is used by the dialog, the ANC worker,
  project save and batch, so a reference is decoded/hashed once per file identity.
- **Tests**: `tests/test_reference_async.py` — non-blocking dialog validation, stale-result
  cancellation, cache hit/invalidation, batch decoding a shared reference once, and script
  provenance (missing file / changed file / unchanged file).

### P2 — Provenance, wording and stale fields

- Batch scripts now store `sha256`, `size`, `mtime_ns`; loading a script whose reference is
  missing or changed clears it with an explicit dialog and still loads the steps.
- Removed the unused `_State.external_reference_error` field and corrected the `run_batch`
  docstring: invalid references **skip the step with a note**, they do not fall back to the
  built-in channel.
- `noise_profile` documentation now says the stationarity metric is the **broadband power
  ratio** between halves, not a per-bin PSD difference.
- Spectral peak count is now saved/restored in `.wavproj` (`analysis["peak_count"]`, default 8,
  clamped to 1–100) without touching FFT results; covered by
  `tests/test_project_peak_count.py`.

### Settings added via i18n

New strings: reference identity/changed messages, "validating…" status, script reference
errors. All have English entries (full suite enforces this).

**Evidence**: `344 passed, 5 skipped, exit 0`.

**Not done in this round** (explicitly): startup benchmarks (5 matched runs, cold/warm,
signed/unsigned), rebuilding either executable, the sounddevice/NumPy 2.5 deprecation warnings
(vendored), `ai/tools.py` per-request copies, undo memory limits, HTML min/max downsampling,
and project/script **relative path** resolution on relocation.

---

## 2026-11-27 (later) — BUG: progressive loading never started stage 2

### Symptom

Opening any file left the tabs reading "傅立叶分析 …", "时频图 …", "区间统计 …" forever,
with empty plots and an empty statistics table, while the file info and waveform appeared
normally. Reported as "时频图、傅里叶分析和区间统计不做了".

### Root cause

`load_audio_async` runs stage 1 through `run_task`, and its `done` callback immediately calls
`_start_analysis_stage`, which itself calls `run_task`. But `run_task` begins with:

```python
if self.task is not None:
    return False
```

`self.task` is only cleared in `_task_finished`, which is connected to the worker's `finished`
signal. Qt delivers `succeeded` first and `finished` second, so during the `succeeded` handler
the stage-1 worker is still referenced — stage 2 was refused, silently, every time. Nothing
cleared the tab ellipsis because that only happens in stage 2's completion path.

### Fix

- The `done` callback now only records `self._pending_analysis = generation`.
- `_task_finished` starts it with `QTimer.singleShot(0, ...)` after releasing the worker, so
  `run_task` no longer sees a task in flight.
- Failure path also clears the ellipsis (`_set_tabs_loading(False)`), so a failed stage no
  longer looks like an eternal spinner.

### Verification

- Re-ran the manual-style probe: tabs come back without "…", and `fourier`, `overview` and
  `statistics` are all populated.
- Checked the user's hypothesis that the peak-count feature was responsible: loading at
  1 / 3 / 8 / 50 peaks gives peak-table rows 1 / 3 / 8 / 50 and all three analyses present —
  so the peak count is not involved.
- New regression test `tests/test_progressive_loading.py` (4 cases) asserts no tab keeps the
  ellipsis and all three results land, including three peak-count values.
- `324 passed, exit 0`.

### Icon investigation (same report)

- The current `wav_analyzer.ico` (sha256 `c41a1867…`) is **byte-identical** to
  `_archive-20261123/wav_analyzer.ico.bak`, so the earlier "icon improvement" was reverted to
  the same bytes: nothing changed, exactly as the user observed. It carries all 9 sizes
  (16–256) and is the navy waveform design.
- The icon embedded in both built executables and the icon the app applies from source are
  that same waveform, verified by extracting `ExtractAssociatedIcon` from
  `dist/WAV Analyzer.exe` and `dist/WAV Analyzer/WAV Analyzer.exe`.
- The document-like glyph in the report is therefore not this application's icon; a stale
  pinned shortcut or a different file is the likely source. Awaiting the user's answer on
  where it was seen before changing anything.

---

## 2026-11-27 — Phase B: independent noise profile (shipped)

### `noise_profile`: static noise spectrum + decision-directed gain

- **Why it exists**: the four cancellation methods all require a reference that is
  *sample-aligned* with the target. Noise recorded separately (another session, another
  clock) cannot be used with them. The earlier prototype failed in two ways: per-frame
  spectral subtraction moved energy into neighbouring bands (band energy went 19.6 → 43.3),
  and feeding it into `wiener_spectral` was blocked by the coherence guard (holdout ERLE
  0.2 dB). Both failures are reproduced as regression tests here.
- **What changed in the algorithm** (each against a measured failure):
  1. The noise spectrum is estimated **once** from the reference (Welch average, no per-frame
     update). Per-frame updating was the direct cause of the band-energy increase.
  2. Gain comes from a **decision-directed** prior SNR with temporal smoothing,
     `ξ = α·ξ_prev + (1−α)·max(post−1, 0)`, `G = ξ/(1+ξ)`, floored at −34 dB, α = 0.98.
     This ties adjacent frames together and removes the frame-to-frame gain jitter.
  3. Synthesis uses Blackman-Harris windows with 50 % overlap. Hann with 75 % overlap cancels
     at frame boundaries under OLA and makes point-wise normalization blow up at the edges.
- **Three bugs found while building it**
  - `previous` was initialized per frame instead of per frequency bin → broadcast error.
  - The stationarity metric took the max over per-bin ratios. White-noise bins are χ²₂, so a
    stationary reference was rejected at 7–10 dB. Now it compares broadband power between the
    halves, with a 12 dB limit (short references still fluctuate ~8 dB).
  - Dividing by a hand-built OLA norm double-normalized: scipy's `istft` already normalizes
    (round-trip error 3e-16). The extra division raised the tone by ~3 dB. Removing it fixed
    both the "pure tone unchanged" and the "fundamental amplitude" checks.
- **Guard rails** (each refuses with a user-facing reason): reference shorter than 0.5 s;
  halves differing by more than 12 dB of broadband power; a tone at the target's fundamental
  present in the reference; noise above 50 % of the power at the fundamental; fundamental
  amplitude change beyond 1 dB.
- **Verified numbers**: on a 1 kHz tone in noise, the 2–3.8 kHz band drops to below half its
  energy while the fundamental moves less than 1 dB; a pure tone passes with unity gain; a
  reference shifted by 500 samples is accepted (the whole point versus method A).
- **Integration**: registered in `METHOD_SPECS` (so it appears in the tool group and in the
  batch step choices), routed in `run_method` with a separate branch that skips the
  equal-length requirement, and wired so an external reference is used as the whole noise
  signal without alignment in both `_anc_compute` and `core/batch.py`.
- **Evidence**: `320 passed, exit 0` (10 noise-profile tests + 6 batch-reference tests).

**Files**: `core/noise_profile.py` (new), `core/anc.py`, `app/anc_dialog.py`,
`app/main_window.py`, `core/batch.py`, `core/i18n_en.py`, `docs/manual_detailed.tex`,
`docs/manual_en.tex`, `README.md`, `README.zh-CN.md`, `CHANGELOG.md`,
`tests/test_noise_profile.py` (new).

---

## 2026-11-26 (night) — Phase A, complete

### External reference now works end-to-end, including batch

- **Batch support (the last missing piece of A)**
  - `run_batch(..., reference={"path", "channel"})` carries a batch-level external reference;
    all files share it, and each file is validated independently (rate mismatch / missing file
    / too-little overlap → note + skip that step, never abort the whole batch).
  - `BatchDialog` gained an "External reference" row (path + channel), persisted with the
    script JSON (`{"version":1, "steps":..., "reference":{...}}`) and with the session
    settings, so a closed/reopened dialog keeps the choice.
  - `BatchWorker`/`start_batch` thread the reference through to `run_batch`.
  - When the reference is shorter than a target, only the overlapping span is processed and
    the rest of that file is left untouched (mirroring the single-file `_anc_compute`).
  - `BatchResult.reference` records the provenance; the summary dialog shows a banner
    "This batch used an external reference: <file> (channel N)".
  - Reference-requiring methods that fail validation are recorded as `denoise_blocked` with a
    note, not a crash; non-reference methods (sync_avg/notch) keep running even when the
    external reference is unusable.
  - 5 new tests in `tests/test_batch_external_reference.py`.
- **Phase A is now complete**: engine validation + alignment, dialog picker with channel
  choice + validation status, left-panel indicator + revalidation on load, project-file
  persistence with hash check, and batch support with per-file handling.
- **Evidence**: `308 passed, exit 0`.

**Files**: `core/batch.py`, `app/batch_dialog.py`, `app/batch_progress.py`,
`app/main_window.py`, `core/batch_summary.py`, `app/batch_summary_dialog.py`,
`core/i18n_en.py`, `tests/test_batch_external_reference.py` (new).

---

## 2026-11-26 (evening) — Phase A, part 4

### Indicator, revalidation and project persistence for the external reference

- **Left-panel indicator**: `reference_label` under the file info shows
  "Reference: built-in channel / no external reference" or
  "Reference: <file> (channel N)". Updated from `set_external_reference()`.
- **Revalidation on load**: `_apply_loaded_meta()` → `_revalidate_reference_after_load()`.
  If the stored reference no longer matches the newly loaded audio (sample rate, channel range,
  unreadable), the reference is cleared and the status bar says why — instead of failing later
  inside the denoise tool.
- **Project persistence**: `build_project(..., reference=...)` writes
  `{kind, path, channel, sha256}` **only when a reference exists**, so existing project files
  keep their exact shape (and `test_round_trip_keeps_every_field` stays valid).
  `_project_payload()` hashes the reference file at save time; `_apply_project()` calls
  `_restore_project_reference()`, which:
  - clears the reference when the block is absent or the file is gone (with a dialog naming the
    path), and
  - refuses a file whose SHA-256 differs from the saved one, clearing the reference instead of
    silently analysing with different data.
- **Mistake worth recording**: an edit that removed a blank line joined
  `quality = payload["quality"][0]` with the next statement and broke the whole module
  (`SyntaxError` in 6 test files). Fixed by restoring the line break; the lesson is to always
  run the suite right after a structural edit rather than batching several.
- **Evidence**: `303 passed, exit 0`.

**Remaining for Phase A**: batch support — carry the reference (path + channel, in the batch
JSON) into `core/batch.py`, apply it to every file with per-file validation, and write the
reference provenance into the batch summary. Not started yet.

---

## 2026-11-26 (later) — Phase A, part 3

### Reference-source UI in `AncToolsDialog`

- Added a "Reference source" group: source combo (built-in / external file / none), file name
  label + "Browse…" button, channel spin (1..16, converted to 0-based on read), and a status
  line that validates the chosen file immediately via `load_reference` (channel + sample rate)
  when a sample rate is known.
- Source/channel are disabled appropriately; `reference_path()` returns `None` when the source
  is not "external", so the engine falls back to the built-in channel.
- `MainWindow.open_anc_tools()` now passes the current file's sample rate, the stored reference
  path and channel into the dialog, then writes the dialog's choice back through
  `set_external_reference(path, channel)` and puts the channel into
  `params["options"]["reference_channel"]` (the engine reads it there).
- `set_external_reference()` now stores path **and** channel index together.
- All new strings have English entries.
- **Evidence**: `303 passed, exit 0`.

**Still open for Phase A**
1. Left-panel read-only indicator (decision 3's second half) and revalidation after
   load / trim / apply-to-source / channel switch.
2. `.wavproj` `reference` block + replay error on missing/hash-changed reference;
   batch JSON equivalent with per-file validation.

---

## 2026-11-26 — Phase A, part 2 (decisions applied)

### Reference rules locked: explicit channel, unequal length allowed, two entry points

- **Decisions from the reviewer**
  1. Multichannel references are accepted **only with an explicit channel index**, and that
     index is persisted with the project/batch data (otherwise replay could silently switch
     channels).
  2. Unequal lengths are **allowed**, but only the overlapping span is processed; the rest of
     the target is left untouched and reported.
  3. The reference picker lives in `AncToolsDialog`, with a read-only indicator in the left
     panel (two entry points).
- **Implemented in this pass**
  - `core/reference.py` rewritten: `load_reference(..., channel=0)` accepts mono or
    multichannel, validates the channel index, still rejects rate mismatch / NaN / silent /
    missing, and returns `channel` + `sha256` in `as_row()`.
  - `align_reference(reference, target, sample_rate)` returns the reference slice for the
    overlapping span plus `{overlap_frames, target_frames, reference_frames, lag_samples,
    unprocessed_frames}`. It estimates the onset lag by cross-correlation and refuses when
    |lag| > 1 ms ("probably not the same recording — use the noise-profile method").
  - `_anc_compute()` now: loads the reference with the chosen channel, aligns it, runs the
    method on the overlap only, and stitches the result back so the cleaned array keeps the
    target length; unmatched samples stay unchanged and are noted in the diagnostics.
  - i18n entries for every new message.
  - `tests/test_external_reference.py`: 11 tests (channel pick, invalid channel, rate mismatch,
    silent, non-finite, missing file, equal/longer/shorter alignment, shifted onset rejected,
    too-little overlap, bit-exact equality with the in-memory path).
- **Evidence**: `303 passed, exit 0`.
- **Still open before Phase A is user-usable**
  1. `AncToolsDialog` UI: source selector (built-in / external / none), channel picker,
     "Browse…" button, validation status line; disable reference-requiring methods when none.
  2. Left panel indicator + revalidation after load / trim / apply-to-source / channel switch
     (the reference is bound to target length, so a trim must invalidate it).
  3. `.wavproj` `reference` block `{kind, path, sha256, channel, sample_rate, frames}` and a
     replay error when missing or hash-changed; batch JSON equivalent, per-file validation.
- **Files**: `core/reference.py`, `app/main_window.py`, `core/i18n_en.py`,
  `tests/test_external_reference.py`.

---


## 2026-11-25 (night) — Phase A, part 1

### External reference channel: validation layer + engine wiring (NOT yet user-reachable)

> Status: **paused for review.** The DSP-side plumbing exists, but there is no UI control yet,
> so a user cannot select a reference file. Project/batch persistence is also not done.

- **What was added**
  - `core/reference.py`: `load_reference(path, sample_rate=..., frames=...)` validates a
    user-supplied WAV and returns `ExternalReference(path, samples, sample_rate, frames, sha256)`.
    Rejections (all user-facing messages): missing file, unreadable file, not mono, sample-rate
    mismatch, frame-count mismatch, NaN/Inf, all-zero (silent).
    **No implicit resampling, padding or trimming** — those would fake the alignment the four
    adaptive methods depend on.
  - `app/main_window.py`: `set_external_reference(path)` stores the path;
    `_anc_compute(..., external_reference=...)` loads and validates it *inside the worker*
    (no file I/O on the GUI thread) and uses its samples as the reference channel; both the
    sync and async ANC entry points snapshot the path before starting.
  - `core/i18n_en.py`: English entries for the seven validation messages.
  - `tests/test_external_reference.py`: 7 tests.
- **Key acceptance test**: the same reference data passed as an in-memory array and as a file
  must produce **bit-identical** output from `wiener_spectral`
  (`np.testing.assert_allclose(..., rtol=0, atol=0)`).
- **Evidence**: `299 passed, exit 0`.
- **Deliberately not done yet** (needs review/decision):
  1. `AncToolsDialog` reference-source control (built-in channel / external file / none) and
     disabling methods that require a reference when "none" is chosen.
  2. `.wavproj` `reference` block (kind/path/sha256) + replay-time error when the reference is
     missing or its hash changed; batch JSON equivalent.
  3. Batch: one reference applied to every file, with per-file validation and a note (not a
     whole-batch abort) when a file's length/rate does not match.
  4. Surfacing reference provenance in the ANC summary/notes.
- **Open questions for the reviewer**
  1. Multichannel reference: reject outright (current), or accept with an explicit channel pick?
  2. Length mismatch: keep the hard rejection, or allow it behind an explicit "recorded
     separately, not sample-aligned" acknowledgement that is written into the report?
  3. Placement: reference selection inside `AncToolsDialog`, or a row in the left panel next to
     the file/channel controls?
- **Files**: `core/reference.py` (new), `app/main_window.py`, `core/i18n_en.py`,
  `tests/test_external_reference.py` (new).

---


## 2026-11-25 (late)

### External mono noise reference (Optimize_Advice P2-⑤) — attempted, **not shipped**

- **Goal**: two paths from the roadmap — (1) a synchronous external reference WAV feeding the
  existing four adaptive methods, (2) a separate `noise_profile` method for an independently
  recorded stationary-noise clip.
- **Attempt 1 — hand-written per-frame spectral subtraction + WOLA**
  - The overlap-add machinery itself is correct: constant 0.5 gain halves RMS and cuts the
    2–3.8 kHz band from 19.6 to 5.4; a fixed comb (keep 1 kHz, floor elsewhere) cuts it to 0.84
    with the tone intact.
  - But the per-frame gain derived from `noise_psd / target_psd` fluctuates frame to frame.
    That is effectively an amplitude modulation at the hop rate (~8 Hz) and it **raised**
    broadband energy (19.6 → 43.3). 3-point smoothing along time and frequency did not converge.
- **Attempt 2 — tile the noise WAV to the target length, delegate to the validated `wiener_spectral`**
  - Correctly blocked by its coherence guard: "holdout ERLE only 0.2 dB". Tiled noise matches
    the spectrum but not the specific noise realisation, so the guard is right to refuse.
- **Decision: do not ship.**
  - `noise_profile` removed from `METHOD_SPECS`; the prototype function deleted from
    `core/anc.py` (backup: `_archive-20261123/anc.py.bak`).
  - The attempt's tests moved to `_archive-20261123/noise_profile_attempt_test.py` so CI does
    not carry a permanently-skipped feature.
  - Rationale: a denoiser that silently moves energy into other bands would corrupt experiment
    data; a "method that is always blocked" is worse than no method.
- **What remains (needs a decision, not more code)**
  - (a) Dedicated decision-directed spectral subtraction with a time-smoothed noise PSD,
    validated on synthetic stationary noise before any UI work.
  - (b) Ship only the *synchronous* external reference (mono, equal length, same sample rate)
    feeding the existing four methods — this is UI + validation + provenance (SHA-256) work,
    with no new DSP and much lower risk.
  - (c) Drop the feature for 2.0.
- **Evidence**: `292 passed, exit 0` after the rollback.

---


> Language note: from this entry onward, this file is written in English.

## 2026-11-25 (evening)

### Progressive loading for long recordings (Optimize_Advice P2-③)

- **What changed**
  - `load_audio_async()` is now two stages. Stage 1 (worker) only reads the file and
    computes the quality report; stage 2 (worker) runs FFT, STFT and statistics.
  - `_apply_loaded_meta()` applies metadata + waveform only, clears the derived tables and
    returns immediately; `_apply_analysis()` fills spectrum/spectrogram/statistics when stage 2
    finishes.
  - `run_task(..., overlay=False)` lets stage 2 run without the modal busy overlay, so the
    window stays usable while the derived results are computed.
  - Per-tab indicator: tabs 1–3 get a trailing " …" via `_set_tabs_loading()` and lose it when
    the analysis lands.
  - Generation guard: `_next_generation()` bumps `_analysis_generation` on every load, channel
    switch and re-analysis; every completion handler compares its captured generation and drops
    stale results. This stops a slow result from an older file/channel overwriting a newer one.
  - `_apply_loaded()` is kept as a compatibility shim (meta + analysis) for tests and scripts.
- **Why**: previously the window stayed covered until read + FFT + STFT + statistics were all
  done, so long files showed a long blank/busy period with no visible progress.
- **Evidence**
  - Smoke test: sync `load_audio()` → main frequency 1000.0 Hz, statistics present, 8 peak
    rows, tab text clean; async `load_audio_async()` → task started, generation = 2.
  - Full suite: **292 passed, exit 0**.
- **Known limits (deliberate)**
  - The per-tab indicator is a text suffix, not a spinner, and gives no ETA.
  - Stale results are *discarded*, not cancelled — the worker still finishes. Real cancellation
    needs a cooperative token inside `_analyze_channel`; left for a later pass.
  - Derived-result caching by (data revision, channel, selection, window, fundamental) is still
    not implemented; every refresh recomputes. Measured cost is acceptable for now.
- **Files**: `app/main_window.py`, `core/i18n_en.py`.

---

## 2026-11-25（下午）

### 明确两个文档的分工

- **起因**：上一版把本文件开头写成了"发布材料"的口吻，和 `CHANGELOG.md` 的职责重叠。
- **定稿**：`CHANGELOG.md` = 用户视角的更新日志；本文件 = 工作留痕（决策 + 证据 + 命令 + 踩坑 + 回滚）。
- **落到流程**：今后每次改动两处都要写，本文件写"为什么/怎么验"，`CHANGELOG.md` 写"用户得到什么"。
- **涉及文件**：`DetailedChangelog/Detailed_CHANGELOG.md`（本文件）。

### 谱峰数量可选（P2-④）收尾

- 首轮测试有两条失败，原因是**测试写错了**而不是实现错了：`export_peaks_csv` 默认 `include_harmonics=True`，谐波行也计入 CSV 行数，我按"行数-1 == N"去断言必然偏大。
- 修正方式：测试改用 `include_harmonics=False` 只数谱峰行（并用 `harmonic` 列判空），实现未改动。
- 结果：`tests/test_peak_count.py` 4 passed；全套 **292 passed / exit 0**。

| 项 | 结论 |
|---|---|
| 默认值 | 8（`FigureOptions` / `TxtExportOptions` / 导出对话框一致） |
| 范围 | 1–100，超出实际峰数按真实数量返回，不补空行 |
| 持久化 | `analysis/peak_count` |
| 不重算 FFT | 测试里把 `fourier_analysis` 换成抛异常的桩，改峰数不触发 |

---

## 2026-11-25

### 频谱谱峰数量可选（Optimize_Advice P2-④）

- **改了什么**
  - 左侧「坐标与分析」新增 `QSpinBox`「谱峰数量」，范围 1–100、默认 8，持久化键 `analysis/peak_count`。
  - 改动峰数只刷新谱峰表与后续导出，**不重算 FFT**（主频/THD/分辨率由 FFT 决定，与标几个峰无关）。
  - `FigureOptions.peak_count`、`TxtExportOptions.peak_count`（均默认 8，向后兼容）接入频谱图标注与 TXT 谱峰段；峰值 CSV 走既有 `peak_count` 参数。
  - `ImageExportDialog` / `TxtExportDialog` 新增 `peak_count` 关键字参数并透传。
- **为什么**：用户希望能选"显示前几个主峰"；路线图要求默认保持 8、全谱 CSV/NPZ 不受影响。
- **涉及文件**：`app/main_window.py`、`core/figure_export.py`、`core/txt_export.py`、`app/image_export_dialog.py`、`app/txt_export_dialog.py`、`core/i18n_en.py`、`tests/test_peak_count.py`（新增）。
- **验证**：`tests/test_peak_count.py`（默认 8 / N=1 / N>实际峰数 / 对话框透传 / 改峰数不触发 `fourier_analysis`）。

### HTML 报告绘图降采样、去掉整声道复制（P2-②）

- **改了什么**：`core/exporter.py` 波形与包络改用 `min_max_downsample(columns=4000)` 后再 `plot`；`core/batch.py` 的 HTML 导出不再 `np.array(channel, copy=True)`，直接传视图。
- **为什么**：按全量采样点建 matplotlib 路径，长录音既慢又吃内存；报告生成器只读样本，复制一份全量 float64 纯属浪费（40 分钟录音可达数百 MB）。
- **验证**：2 分钟 / 48 kHz（5,760,000 点）生成 HTML 5.29 s、峰值额外内存 31.9 MB、体积 95.4 KB；统计与数值导出未改动。

### 启动优化（P1：闪屏 + 延迟 matplotlib + core 瘦身）

- **改了什么**
  - `core/__init__.py` 改为 PEP 562 惰性导出，`import core.i18n` 不再连带拉起 NumPy/SciPy。
  - `core/figure_export.py` 不再在导入时加载 matplotlib；新增 `ensure_ready()`，由 `run_app` 在**首帧之后**用 `QTimer.singleShot(0, ...)` 在 GUI 线程预热。
  - 非主线程若抢先调用会抛「图像导出后端尚未就绪」，避免 work 线程里首次导入导致 access violation。
  - `run_app` 新增静态启动闪屏（程序图标），`finally` 中关闭，启动失败也不会留孤儿窗口。
- **为什么**：matplotlib 约 1.2 s，占启动总时长三分之一。
- **测量结论**：`import app.main_window` 后 matplotlib 未加载（已移出）；`ensure_ready()` 单独 1.212 s。**scipy.signal 仍占 1.129 s**，按路线图"先保持急切导入"不动；对话框/httpx/keyring 合计 < 0.1 s，拆分无收益，不做。
- **涉及文件**：`run_app.py`、`core/__init__.py`、`core/figure_export.py`、`tests/conftest.py`、`core/i18n_en.py`。

### 任务栏图标显示为用户自己的程序

- **改了什么**：`_set_windows_app_id()` 在建窗口前调用 `SetCurrentProcessExplicitAppUserModelID`；`_apply_window_icon()` 设置 `app.setWindowIcon` 与主窗口图标；两个 spec 把 `wav_analyzer.ico/.png` 加入 `datas`；自检新增 `icon_present`，CI 断言它。
- **为什么**：全项目没有设过窗口图标，也没有 AppUserModelID，Windows 只能按宿主进程（pythonw / 打包引导器）分组显示。
- **踩坑**：我曾误判 `.ico` 缺大尺寸而重新生成，实际原文件已有 16→256 全档，重新生成反而丢了 96/192，已用备份回滚（哈希一致）。
- **验证**：`QIcon` 可用、`app.windowIcon()` 非空；`tests/test_launcher.py` 新增图标可解析与 AppUserModelID 稳定性两条测试。

### 文件夹版（onedir）设为推荐分发形态 + CI 双形态自检

- **改了什么**：README 中英、两份手册、发布说明都把 onedir 放在首位并标「推荐」；CI 构建两种形态并**分别跑冻结自检**（`ok: true` 且 `manual_pdf_present`、`icon_present`）；两个 spec 的 `upx` 由 `True` 改为显式 `False`。
- **为什么**：本机普通权限写不了用户临时目录，单文件版必须提权才能启动；UPX 未安装，`upx=True` 一直是空操作，改成显式 False 让产物形态可预测（将来引入 UPX 需先 A/B 测量解压与杀软开销）。
- **验证**：文件夹版在未设置 TEMP 的环境下自检通过。

### 批量频谱缓存按有效基频记键

- **改了什么**：`_State.fourier_key` 记录缓存对应的基频（`None` 表示自动估峰），`_ensure_fourier()` 键变化即重算；`_invalidate_derived()` 一并清键。
- **为什么**：`dual(auto)` 先缓存了 200 Hz，随后 `stats(fixed=100)` 只改统计，导出仍拿到 200 Hz 的旧频谱对象。
- **验证**：before/after 探针（旧逻辑 200→200 复用，新逻辑 200→100 重算）+ `tests/test_batch.py::test_fourier_cache_follows_effective_fundamental`。

### 设置测试隔离、matplotlib 缓存持久化、重复 `_warm_up` 清理

- **改了什么**：`test_ai_ui` 的 QSettings 测试改用 `tmp_path` 下的 INI 并 `sync()` 重开；`run_app._configure_matplotlib_cache()` 在任何 matplotlib 导入前选一个持久可写目录；删除 `figure_export.py` 里被静默覆盖的第二份 `_warm_up()`。
- **为什么**：前者让测试不再依赖注册表（本机注册表写入会静默失败）；后者避免每次启动重建字体缓存（实测 1.72→1.13 s）。

---

## 2026-11-24

### 代码审查 22 项缺陷修复（Debug_Report.md）

- **数据正确性**：声道切换后旧预览可覆盖新声道（001）、撤销后工程仍重放已撤销操作（002）、写回源文件后重复执行（003）、工程选区被重置为全量（006）。
- **批量**：同名输入静默覆盖（008，现加 `_2` 序号）、派生缓存不失效（009）、双通道用原始音频（010）、取消后仍列出未写 CSV（011）。
- **算法**：跳帧 STFT 高 6.02 dB（014）、时间戳提前半窗（016）、RMS 窗长大于输入时长度不等（015）、3 点 FFT 漏倍增（019）、长选区分析窗口缺起点（017）。
- **线程/UI**：ANC 线程读控件（004）、AIWorker 不释放（005）、测试连接阻塞界面（007）。
- **导出/校准**：TXT 的 NaN/-inf（012）、NPZ 返回路径（013）、非有限校准参数（018）。
- **脚本/测试**：`record.py` 单声道仍请求双声道（020）、`analyze.py` 手拼 CSV（021）、批量对话框测试不释放对象导致 pytest 以 `0xC0000409` 退出（022）。
- **验证**：全套 `288 passed`，退出码 0（此前"摘要通过但进程崩溃"）。

### 英文手册配图与英文界面崩溃

- 英文手册/README 此前复用中文截图 → 新增 `docs/figures_en/` 与 `SHOT_LANG=en`，`manual_en.tex` 的 `\graphicspath` 优先取该目录。
- 英文界面打开「模型设置」抛 `KeyError: 'DeepSeek'`（用翻译后的名字当字典键）→ 预设键改为稳定标识，显示名单独翻译；补 Moonshot 英文条目。
- 导出图例硬编码中文（当前波形/振幅谱/时频图等 12 项）→ 全部接入 `rt()`，英文导出审计 10/10 通过。

### 批量脚本记忆

- 关窗口即记住步骤与输出目录（原来只有点"开始"才存）；设置改存 INI 后真正生效；修掉「已恢复 N 个步骤」被摘要覆盖的问题。

---

## 2026-11-23

### 设置持久化改走 INI

- `QSettings` 两参数构造会忽略默认格式、强制写注册表；在本机注册表写入静默失败，表现为"切英文重启还是中文""设置存不住"。
- 改为固定写入程序目录下的 `PhysicsExperiment\<应用名>.ini`（不可写时退到 AppData），保存后立即读回校验并提示。

### 交互修复

- 滚轮不再被下拉框/数字框/页签栏吞掉：改为**转交外层滚动区**（早期版本是"吞掉"，等于换个方式卡住用户）。
- 手册窗口：页码改为可输入的 `QSpinBox`；跳页改用 `pageNavigator.jump()`（原来把"点"当"像素"累加）；修掉页码框与视图互相触发的死循环。
- 「保存工程/打开工程」改用 Qt 自带对话框，绕开本机损坏的系统外壳（`explorer.exe` 报 `0xC0000142`）。
- 「打开手册目录」不再启动 explorer，改为显示路径并支持复制。

### v2.0.0 发布材料

- 新增 `CHANGELOG.md`（此前只有手册附录里的版本说明）、`docs/release_notes_v2.0.0.md`、`docs/signing.md` 与 `.github/workflows/build-sign.yml`（SignPath 免费签名通道）。
- 增加文件夹版（onedir）构建配置 `WAV_Analyzer_onedir.spec`。
