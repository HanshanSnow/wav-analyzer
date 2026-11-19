# -*- coding: utf-8 -*-
"""
隔音课题：双通道录音批量分析

数据约定
    data/f1000_D10mm_01.wav   左声道 = 盒内参考麦克风，右声道 = 盒外接收麦克风
    文件名格式：f<频率Hz>_<板子标签>_<重复序号>.wav，例如 f2000_solid_01.wav

用法
    python analyze.py --calib     # 零时延标定（读 calib/ 下两个文件，生成 calib.json）
    python analyze.py             # 批量分析 data/ 下全部 wav，输出 results.csv
    python analyze.py --plot      # 读 results.csv 画图
"""

import argparse
import json
import re
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfiltfilt

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CALIB = ROOT / "calib"
CALIB_JSON = ROOT / "calib.json"


def read_stereo(path):
    fs, x = wavfile.read(str(path))
    x = np.asarray(x)
    if x.ndim == 1:
        raise ValueError(f"{path.name} 是单声道，需要立体声录音（左=参考，右=接收）")
    if x.dtype.kind in "iu":
        x = x.astype(np.float64) / np.iinfo(x.dtype).max
    else:
        x = x.astype(np.float64)
    return fs, x[:, 0], x[:, 1]


def bandpass(sig, fs, f0):
    lo, hi = max(f0 * 0.7, 20.0), min(f0 * 1.4, fs * 0.45)
    sos = butter(4, [lo, hi], btype="band", fs=fs, output="sos")
    return sosfiltfilt(sos, sig)


def estimate_delay(ref, recv, fs, f0, window_ms=2.0):
    """用 FFT 互相关估计 recv 相对 ref 的时延（秒，正数表示接收端滞后）。

    纯正弦的互相关每隔一个周期就有一个峰，因此搜索窗限制在半个周期以内，
    否则会抓到整周期伪峰。超出窗口的真实时延会发生整周期混叠，用 warn 提示。
    """
    a = bandpass(ref - ref.mean(), fs, f0)
    b = bandpass(recv - recv.mean(), fs, f0)

    n = len(a) + len(b) - 1
    nfft = 1 << (n - 1).bit_length()
    c = np.fft.irfft(np.conj(np.fft.rfft(a, nfft)) * np.fft.rfft(b, nfft), nfft)

    lags = np.arange(nfft)
    lags[lags >= nfft // 2] -= nfft

    win = int(min(window_ms * 1e-3, 0.45 / f0) * fs)   # 不超过半个周期
    idx = np.where(np.abs(lags) <= win)[0]
    k = int(idx[np.argmax(c[idx])])

    y0, y1, y2 = c[k - 1], c[k], c[k + 1]
    denom = y0 - 2 * y1 + y2
    frac = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
    lag = lags[k] + frac

    quality = float(c[k] / (np.std(a) * np.std(b) * len(a) + 1e-12))
    warn = ""
    if abs(lags[k]) >= win - 2:
        warn = f"峰值贴近搜索窗边缘(±{win/fs*1e6:.0f} µs)，时延可能整周期混叠"
    return lag / fs, quality, warn, win / fs, a, b


def level_db(sig):
    return 20 * np.log10(np.sqrt(np.mean(sig ** 2)) + 1e-12)


def parse_name(path):
    m = re.search(r"f(\d+(?:\.\d+)?)", path.stem, re.I)
    freq = float(m.group(1)) if m else None
    parts = path.stem.split("_")
    plate = parts[1] if len(parts) > 1 else "?"
    return freq, plate


def cmd_calib():
    files = sorted(CALIB.glob("*.wav"))
    if len(files) < 2:
        raise SystemExit("calib/ 下需要两个文件：两只麦克风并排正放（如 ab.wav）与互换位置（如 ba.wav）")

    results = []
    for f in files[:2]:
        fs, ref, recv = read_stereo(f)
        f0 = parse_name(f)[0] or 1000.0
        dt, q, warn, win, _, _ = estimate_delay(ref, recv, fs, f0)
        results.append((f.name, dt, q, f0))
        print(f"  {f.name}: Δt = {dt*1e6:+.1f} µs  (峰值质量 {q:.2f}, f0={f0:.0f} Hz, 窗 ±{win*1e6:.0f} µs)")
        if warn:
            print(f"    注意：{warn}")

    tau0 = float(np.mean([r[1] for r in results]))
    CALIB_JSON.write_text(json.dumps({
        "tau0_us": tau0 * 1e6,
        "sources": [r[0] for r in results],
        "f0_hz": results[0][3],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n系统零时延 τ₀ = {tau0*1e6:+.1f} µs，已写入 {CALIB_JSON.name}")


def load_tau0():
    if CALIB_JSON.exists():
        return float(json.loads(CALIB_JSON.read_text(encoding="utf-8"))["tau0_us"]) * 1e-6
    return None


def cmd_analyze():
    files = sorted(DATA.glob("*.wav"))
    if not files:
        raise SystemExit(f"{DATA} 里没有 wav 文件")

    tau0 = load_tau0()
    if tau0 is None:
        print("警告：未找到 calib.json，先跑 --calib 才能得到扣零偏后的时延\n")

    rows = []
    for f in files:
        fs, ref, recv = read_stereo(f)
        freq, plate = parse_name(f)
        f0 = freq or 1000.0
        dt, q, warn, win, a, b = estimate_delay(ref, recv, fs, f0)
        ref_db, recv_db = level_db(a), level_db(b)
        rows.append({
            "file": f.name,
            "freq_hz": freq if freq else "",
            "plate": plate,
            "dt_us": dt * 1e6,
            "dt_corr_us": (dt - tau0) * 1e6 if tau0 is not None else "",
            "dL_dB": ref_db - recv_db,
            "ref_dbfs": ref_db,
            "recv_dbfs": recv_db,
            "peak_quality": q,
            "window_us": win * 1e6,
            "note": warn,
        })
        print(f"{f.name:26s} Δt={dt*1e6:+8.1f} µs  ΔL={ref_db-recv_db:6.1f} dB  Q={q:5.2f}")
        if warn:
            print(f"    ! {warn}")

    out = ROOT / "results.csv"
    keys = list(rows[0].keys())
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        fh.write(",".join(keys) + "\n")
        for r in rows:
            fh.write(",".join(str(r[k]) for k in keys) + "\n")
    print(f"\n共 {len(rows)} 条，已写入 {out.name}")


def cmd_plot():
    import csv
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    src = ROOT / "results.csv"
    if not src.exists():
        raise SystemExit("先跑 python analyze.py 生成 results.csv")

    with src.open(encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    freqs = sorted({float(r["freq_hz"]) for r in rows if r["freq_hz"]})
    plates = []
    for r in rows:
        if r["plate"] not in plates:
            plates.append(r["plate"])

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    w = 0.8 / max(len(freqs), 1)
    for i, fq in enumerate(freqs):
        dls, dts = [], []
        for p in plates:
            v = [r for r in rows if r["plate"] == p and r["freq_hz"] and float(r["freq_hz"]) == fq]
            dls.append(float(np.mean([float(x["dL_dB"]) for x in v])) if v else 0)
            dts.append(float(np.mean([float(x["dt_corr_us"] or x["dt_us"]) for x in v])) if v else 0)
        xs = np.arange(len(plates)) - 0.4 + w * (i + 0.5)
        axes[0].bar(xs, dls, width=w, label=f"{fq:.0f} Hz")
        axes[1].bar(xs, dts, width=w, label=f"{fq:.0f} Hz")

    for ax, ylabel, title in zip(
        axes,
        [r"$\Delta L$ / dB", r"$\Delta t-\tau_0$ / µs"],
        ["隔声量差随开口变化", "群延迟随开口变化"],
    ):
        ax.set_xticks(np.arange(len(plates)))
        ax.set_xticklabels(plates, rotation=45, ha="right")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.3)
        ax.legend(fontsize=8)

    fig.tight_layout()
    out = ROOT / "results.png"
    fig.savefig(out, dpi=200)
    print(f"已生成 {out.name}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="隔音课题双通道录音分析")
    ap.add_argument("--calib", action="store_true", help="零时延标定")
    ap.add_argument("--plot", action="store_true", help="绘制结果图")
    args = ap.parse_args()

    if args.calib:
        cmd_calib()
    elif args.plot:
        cmd_plot()
    else:
        cmd_analyze()
