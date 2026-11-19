"""生成演示用录音（合成信号，非真实实验数据）。

README 与手册配图需要一个“看得懂”的信号：稳态正弦 + 一处冲击。
真实实验录音不进仓库（体积大、含现场信息），示例一律由本脚本现场生成。

用法：
    python demo/make_demo_tone.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SAMPLE_RATE = 48000
DURATION_S = 1.000
FREQUENCY_HZ = 1000.0
AMPLITUDE = 0.40          # 0.4 FS，留出 8 dB 余量，不会削顶
NOISE_RMS = 1e-4          # 约 -80 dBFS 本底，模拟录音底噪
IMPULSE_AT_S = 0.62
IMPULSE_LEN_MS = 3.0
IMPULSE_GAIN = 6.0        # 相对基波幅度的倍数，足以触发冲击检测


def build() -> np.ndarray:
    n = int(SAMPLE_RATE * DURATION_S)
    t = np.arange(n) / SAMPLE_RATE
    signal = AMPLITUDE * np.sin(2 * np.pi * FREQUENCY_HZ * t)

    # 起振淡入 10 ms，避免开头的阶跃在谱上摊出宽带
    fade = int(0.010 * SAMPLE_RATE)
    signal[:fade] *= np.linspace(0.0, 1.0, fade, endpoint=False)

    rng = np.random.default_rng(20261119)
    signal += rng.normal(0.0, NOISE_RMS, n)

    start = int(IMPULSE_AT_S * SAMPLE_RATE)
    width = max(2, int(IMPULSE_LEN_MS / 1000.0 * SAMPLE_RATE))
    signal[start:start + width] += AMPLITUDE * IMPULSE_GAIN * rng.choice([-1.0, 1.0], width)

    return np.clip(signal, -0.999, 0.999)


def main() -> int:
    target = ROOT / "demo" / "demo_tone.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(target), build().astype(np.float32), SAMPLE_RATE, subtype="PCM_24")
    print(f"{target.name}: {DURATION_S:.3f} s / {SAMPLE_RATE} Hz / {FREQUENCY_HZ:.0f} Hz 正弦 + "
          f"{IMPULSE_AT_S:.2f} s 处 {IMPULSE_LEN_MS:.1f} ms 冲击")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
