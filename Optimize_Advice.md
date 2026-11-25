# Prompt: Optimize WAV Analyzer Startup and UX — Re-audit 2026-11-25

Work in `D:\WAV_Analyzer`. Use small, benchmarked changes. First fix the correctness/blocking defects in `DEBUG202611242315.md`; do not reimplement completed items below. Preserve scientific behavior, translations, and worker cleanup. Never weaken ACLs, Smart App Control, or antivirus settings.

## Current measurement

Windows/Python 3.13 source launch; offscreen Qt; warm OS and Matplotlib caches; three separate processes. Cumulative seconds from the first in-process statement; excludes interpreter creation, OS scanning, and PyInstaller boot time. Not cold-start or EXE data.

| Milestone | Median | Range |
|---|---:|---:|
| `run_app` imported | 0.095 | 0.090–0.098 |
| Splash shown/processed | 1.243 | 1.240–1.267 |
| `app.main_window` imported | 2.607 | 2.601–2.631 |
| Main window constructed | 2.769 | 2.764–2.797 |
| First frame processed | **2.852** | 2.847–2.881 |
| Matplotlib export-ready | **3.357** | 3.353–3.386 |

The automatic persistent cache selected `D:\WAV_Analyzer\matplotlib-cache`. A detailed run spent ~1.09 s in `QSplashScreen.show()` and ~0.50 s in post-frame export preparation; pixmap load/scale was <4 ms. Real-desktop costs remain unverified.

## Already implemented — retain, test, do not duplicate

- Writable persistent `MPLCONFIGDIR` before Matplotlib import; existing user setting is respected.
- PEP 562 lazy `core` exports; static splash before heavy UI import; no fake animated progress during blocking imports.
- Matplotlib import/warm-up after the first frame through `ensure_ready()` on the GUI thread; no duplicate warm-up.
- Two-stage audio load with generation IDs and nonblocking stage-2 overlay behavior. Its latest-request race is **not fixed**; see Debug P0.
- External reference WAV for aligned ANC and independent `noise_profile`: explicit multichannel selection, matching-rate validation, unequal-length overlap handling, project path/channel/SHA, and batch path/channel support.
- User-selected top-N spectral peaks: default 8, range 1–100, GUI persistence, no FFT recomputation, and GUI/TXT/peak-CSV/figure propagation. This means displayed peaks, not FFT length/bin count.

## P1 — Make onedir the primary Windows distribution

Onefile extraction happens before Python and cannot be covered by a Qt splash.

- Build, sign, benchmark, and selftest onedir and onefile equivalently; distribute onedir first once parity is proven.
- A/B UPX on/off and signed/unsigned artifacts. Keep compression only when measured startup and size both justify it.
- Record cold/warm process-start -> first frame -> export-ready -> first export. Do not infer EXE/cold gains from the warm source table.

Windows temp note: no `sudo` privilege is normally required. A onefile EXE must create/write/execute its PyInstaller extraction directory before Python starts. Failure usually means `%TEMP%` is invalid or denied by ACL/policy/security software; elevation may merely bypass that restriction. Capture the actual `WinError` and path, use a writable per-user location or onedir, and never recommend disabling security or broadening ACLs as the product fix.

## P1 — Profile the remaining startup path

1. **Splash:** `QSplashScreen.show()` dominates the splash milestone offscreen. Profile real Windows desktop/native-window/font initialization before changing assets. Keep the splash static and honest; animation freezes during blocking imports. Do not claim the first splash equals a usable main window.
2. **Post-frame stall:** export preparation blocks the GUI for ~0.5 s immediately after first frame. Show a real “preparing image export” state and gate only affected export actions. Never move first Matplotlib import/warm-up to a worker: comments document Python 3.13/PySide6 access violations.
3. **Imports:** `app.main_window` eagerly imports `ai.client`/httpx, `settings_dialog`/keyring, batch modules, and several dialogs. Defer optional AI/keyring/httpx and infrequently used dialogs to first use where type annotations and tests permit. Measure import timing before/after; avoid broad lazy-import rewrites.
4. Keep the current GUI-thread export fallback and worker `deleteLater()` behavior. First-export correctness outranks a small startup win.

## P2 — Finish external-reference UX and provenance

- Remove synchronous full reads/hashes from dialogs, target loading, project restore, and project save as specified in Debug P1. Validate in workers and ignore stale callbacks.
- Cache a batch reference instead of decoding/hashing it once per input. Key by path/channel/rate/file identity; keep per-target rate, lag, overlap, coherence, and guardrail checks.
- `.wavproj` stores path/channel/SHA, but batch scripts/results currently store only path/channel. Add SHA and explicit missing/changed-reference replay errors while retaining backward-compatible reads.
- Define absolute versus project/script-relative path resolution and test relocation. Do not silently resample, pad, tile, or switch references.
- Preserve the distinction: aligned external reference for synchronous ANC; unaligned, stationary, noise-only reference for `noise_profile`. Keep noise-only, stationarity, tone-preservation, and held-out-noise tests.

## P2 — Complete peak-count reproducibility

The feature works and is globally persisted, but `app/main_window.py:2086-2090` omits it from `.wavproj` analysis metadata and project restore ignores it.

- Save/restore optional `analysis["peak_count"]`, defaulting to 8 for old projects; validate/clamp to 1–100 without changing FFT results.
- Add project round-trip coverage for N=1 and N>8. Keep table/TXT/CSV/figure counts consistent and full-spectrum exports unchanged.
- Continue treating N as presentation only; do not rerun FFT or change main frequency, THD, resolution, waveform, or harmonic count.

## P2 — Reduce large-file memory and export work

- `AnalysisTools` copies the full sample vector and mask for each AI request (`ai/tools.py:17-21`). Use read-only shared snapshots only with proven lifetime/mutation safety; otherwise retain copies and document the memory cost.
- Undo permits four levels/1.2 GB. Expose estimates and consider adaptive limits for huge files; never silently remove the only undo level.
- Reuse min/max display downsampling for HTML and avoid full-channel/plot copies where possible; preserve numerical CSV/NPZ and statistics.
- Profile before changing FFT/STFT algorithms; existing frame caps and Hilbert padding are safeguards, not automatic waste.

## Verification and delivery

For each phase, run focused regressions, then the full suite (current baseline: **324 passed, 5 skipped**, exit 0). Prove new tests fail on old code. Benchmark at least five matched runs; report median/range and separate cold/warm, source/onedir/onefile.

Require both rebuilt frozen selftests green, successful PNG/PDF/SVG/HTML/batch export, rapid-load/channel correctness, cancel/close cleanup, language restart, and real-desktop Chinese/English splash checks. Keep Qt OpenGL/PDF modules, audio DLLs, manuals, and keyring backends packaged. Report unverified hardware, AV, signing, and cold-start behavior explicitly.
