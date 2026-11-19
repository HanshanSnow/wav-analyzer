# -*- coding: utf-8 -*-
"""
隔音课题：立体声录音（替代 Audacity 的最小方案）

用法
    python record.py --list                     # 列出所有音频设备，找到 USB 声卡的编号
    python record.py out.wav -d 4 -t 10         # 用 4 号设备录 10 秒
    python record.py data/f1000_D10mm_01.wav -d 4

录完会打印两路峰值：接近 1.0 说明削顶，要调小信号源幅度。
"""

import argparse
import sys
from pathlib import Path

import numpy as np


def main():
    ap = argparse.ArgumentParser(description="立体声录音（左=盒内参考，右=盒外接收）")
    ap.add_argument("output", nargs="?", help="输出 wav 路径")
    ap.add_argument("-d", "--device", type=int, help="输入设备编号")
    ap.add_argument("-t", "--seconds", type=float, default=10.0, help="录音时长（秒），默认 10")
    ap.add_argument("-r", "--rate", type=int, default=44100, help="采样率，默认 44100")
    ap.add_argument("--list", action="store_true", help="列出音频设备")
    args = ap.parse_args()

    try:
        import sounddevice as sd
    except ImportError:
        sys.exit("缺少 sounddevice：pip install sounddevice")

    if args.list or args.device is None:
        print(sd.query_devices())
        if args.list:
            return
        ap.error("请用 -d 指定输入设备编号（先 --list 查看）")

    if not args.output:
        ap.error("请给出输出文件路径")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    info = sd.query_devices(args.device, "input")
    if info["max_input_channels"] < 2:
        print(f"警告：{info['name']} 只有 {info['max_input_channels']} 个输入通道，无法录双声道")
        print("      请改用立体声输入的声卡，否则两路信号会混成一路")

    print(f"设备：{info['name']}　{args.seconds:.0f} s @ {args.rate} Hz")
    rec = sd.rec(int(args.seconds * args.rate), samplerate=args.rate,
                 channels=2, dtype="float32", device=args.device)
    sd.wait()

    from scipy.io import wavfile
    wavfile.write(str(out), args.rate, rec)

    peak = np.abs(rec).max(axis=0)
    rms = np.sqrt((rec ** 2).mean(axis=0))
    print(f"已保存 {out}")
    print(f"  左声道  峰值 {peak[0]:.3f}　RMS {20*np.log10(rms[0]+1e-12):6.1f} dBFS")
    print(f"  右声道  峰值 {peak[1]:.3f}　RMS {20*np.log10(rms[1]+1e-12):6.1f} dBFS")
    if peak.max() > 0.98:
        print("  ! 出现削顶，请调小 XR2206 的 Amplitude 或功放音量")
    if peak.min() < 0.01:
        print("  ! 有一路信号过弱，检查该路麦克风供电/增益/接线")


if __name__ == "__main__":
    main()
