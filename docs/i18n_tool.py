"""i18n 维护工具：把界面中文串自动包成 tr("...") / tf("...")，并统计覆盖情况。

为什么用 AST 而不是正则
----------------------
正则分不清字符串、注释、f-string 和字典键，改错一处就是界面崩。AST 能拿到
每个字符串常量的精确起止位置，且天然跳过注释。

三类东西**故意不包**：
- 文档字符串（不是界面文案，翻译了只会让人看不懂代码）
- 字典的键、集合元素、函数默认值（键被翻译后，用原中文查表的代码会全部失效）
- 导出产物文件（TXT / HTML / 图片图注）——那些是数据报告，不是界面

f-string 转成 ``tf("模板 {a}", a=a)``：模板里的占位符原样保留，``tf`` 先翻译
模板再 format，因此英文译文可以调整语序而不破坏格式化。

用法：
    python docs/i18n_tool.py --dry-run      # 只看会改多少处
    python docs/i18n_tool.py                # 真的改
    python docs/i18n_tool.py --report       # 列出未翻译条目
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMPORT_LINE = "from core.i18n import tf, tr"

# 导出产物，保持中文：它们写进文件，不参与界面切换
EXCLUDED = {"txt_export.py", "exporter.py", "figure_export.py", "i18n.py", "i18n_en.py"}

CJK_RE = re.compile(r"[\u4e00-\u9fa5]")


def _targets() -> list[Path]:
    files: list[Path] = []
    for sub in ("app", "core"):
        for p in sorted((ROOT / sub).glob("*.py")):
            if p.name in EXCLUDED:
                continue
            files.append(p)
    return files


def _docstring_nodes(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            out.add(id(first.value))
    return out


def _skip_nodes(tree: ast.AST) -> set[int]:
    skip = _docstring_nodes(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if k is not None:
                    skip.add(id(k))
        elif isinstance(node, ast.Set):
            for elt in node.elts:
                skip.add(id(elt))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for d in list(args.defaults) + [d for d in args.kw_defaults if d]:
                skip.add(id(d))
    return skip


def _offsets(text: str) -> list[int]:
    offs = [0]
    for line in text.splitlines(keepends=True):
        offs.append(offs[-1] + len(line))
    return offs


def _strip_f_prefix(literal: str) -> str:
    """f"..." / rf"..." / fr"..." → "..." """
    return re.sub(r"^(?:[rR][fF]|[fF][rR]|[fF])", "", literal, count=1)


def _build_tf(src: str, node: ast.JoinedStr, start: int, end: int,
              offs: list[int]) -> str:
    template = _strip_f_prefix(src[start:end])
    names: list[str] = []
    seen: set[str] = set()
    for v in node.values:
        if not isinstance(v, ast.FormattedValue):
            continue
        expr = src[offs[v.value.lineno - 1] + v.value.col_offset:
                   offs[v.value.end_lineno - 1] + v.value.end_col_offset]
        if expr.isidentifier() and expr not in seen and expr not in {
                "tf", "tr", "self", "cls", "None", "True", "False"}:
            name = expr
        else:
            name = "_v%d" % len(names)
        seen.add(name)
        names.append("%s=(%s)" % (name, expr))
    if names:
        return "tf(%s, %s)" % (template, ", ".join(names))
    return "tf(%s)" % template


def wrap(path: Path, dry: bool) -> tuple[int, int]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    skip = _skip_nodes(tree)
    offs = _offsets(src)

    fstring_nodes: set[int] = set()
    edits: list[tuple[int, int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            if not any(isinstance(v, ast.Constant) and isinstance(v.value, str)
                       and CJK_RE.search(v.value) for v in node.values):
                continue
            start = offs[node.lineno - 1] + node.col_offset
            end = offs[node.end_lineno - 1] + node.end_col_offset
            if src[:start].rstrip().endswith(("tf(", "tr(")):
                continue
            edits.append((start, end, _build_tf(src, node, start, end, offs)))
            fstring_nodes.add(id(node))
            continue

        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in skip or not CJK_RE.search(node.value):
            continue
        start = offs[node.lineno - 1] + node.col_offset
        end = offs[node.end_lineno - 1] + node.end_col_offset
        if src[:start].rstrip().endswith(("tr(", "tf(")):
            continue
        edits.append((start, end, "tr(" + src[start:end] + ")"))

    if not edits:
        return 0, 0

    new = src
    for start, end, rep in sorted(edits, key=lambda e: e[0], reverse=True):
        new = new[:start] + rep + new[end:]

    if IMPORT_LINE not in new and "from core.i18n import" not in new:
        lines = new.split("\n")
        insert_at = 0
        for i, line in enumerate(lines[:60]):
            if line.startswith(("import ", "from ")):
                insert_at = i
                break
        lines.insert(insert_at, IMPORT_LINE)
        new = "\n".join(lines)

    if not dry:
        path.write_text(new, encoding="utf-8", newline="")
    return len(edits), len(fstring_nodes)


def collect_used() -> list[str]:
    """扫描代码里所有 tr(...) / tf(...) 的中文原文。"""
    used: list[str] = []
    for p in _targets():
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("tr", "tf") and node.args):
                a = node.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                        and CJK_RE.search(a.value):
                    used.append(a.value)
    return sorted(set(used))


def report() -> int:
    from core.i18n_en import EN
    used = collect_used()
    missing = [s for s in used if s not in EN]
    print("代码内中文串 %d 条，已翻译 %d 条，未翻译 %d 条"
          % (len(used), len(used) - len(missing), len(missing)))
    for s in missing:
        print("  [ ] %s" % s)
    stale = [k for k in EN if k not in set(used)]
    if stale:
        print("\n字典里不再被引用的旧条目 %d 条" % len(stale))
        for s in sorted(stale)[:10]:
            print("  [?] %s" % s)
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)

    if args.report:
        return report()

    total = fstr = 0
    for p in _targets():
        n, f = wrap(p, args.dry_run)
        total += n
        fstr += f
        print("%-30s %3d 处（其中 f-string %d）" % (p.relative_to(ROOT), n, f))
    print("\n合计 %d 处%s" % (total, "（dry-run，未写盘）" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
