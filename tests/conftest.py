import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 测试进程也要一个固定的 matplotlib 缓存目录：否则每次跑测试
# matplotlib 都会在当前目录新建一个临时缓存目录（污染仓库）。
import os  # noqa: E402

os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_ROOT / "_pytest_mpl_cache"))
# 目录先建好：交给 matplotlib 自己竞争创建时，偶发会走到"临时缓存目录"分支，
# 让依赖图形字节比较的报告测试出现假失败。
(PROJECT_ROOT / "_pytest_mpl_cache").mkdir(exist_ok=True)
