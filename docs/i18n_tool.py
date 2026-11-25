"""i18n 维护工具：把界面中文串自动包成 tr("...") / tf("...")，并统计覆盖情况。

为什么用 AST 而不是正则
----------------------
正则分不清字符串、注释、f-string 和字典键，改错一处就是界面崩。AST 能拿到
每个字符串常量的精确起止位置，且天然跳过注释。

**偏移量必须按 UTF-8 字节算**：``ast`` 的 ``col_offset`` 是字节偏移，不是字符
偏移。含中文的行里两者相差很大，按字符算会把括号插进字符串中间，直接把文件
改成语法错误。

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
EXCLUDED = {"txt_export.py", "exporter.py", "figure_export.py", "i18n.py",
            "i18n_en.py", "report_i18n.py"}
# 这些模块把中文原文存放成数据（运行时才交给 tr()/rt()），AST 看不到 tr("…") 调用。
# 对它们额外收集所有中文串字面量，避免报告里把它们误报成「不再被引用」。
RAW_STRING_MODULES = {"statistics.py"}

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


def _byte_offsets(text: str) -> list[int]:
    """每行起始处的 UTF-8 字节偏移，与 ast 的 col_offset 同一坐标系。

    必须按 ``\\n`` 切行，不能用 ``str.splitlines()``：后者把 ``\\x0b``、``\\x0c``、
    ``\\u2028`` 也当行界，而 Python 词法分析器只认 ``\\n``，两者行号一旦错开，
    插进去的括号就会落进字符串内部。
    """
    offs = [0]
    for line in text.split("\n"):
        offs.append(offs[-1] + len(line.encode("utf-8")) + 1)
    return offs


def _strip_f_prefix(literal: str) -> str:
    return re.sub(r"^(?:[rR][fF]|[fF][rR]|[fF])", "", literal, count=1)


def _slice(raw: bytes, node: ast.AST, offs: list[int]) -> str:
    start = offs[node.lineno - 1] + node.col_offset
    end = offs[node.end_lineno - 1] + node.end_col_offset
    return raw[start:end].decode("utf-8")


def _build_tf(raw: bytes, node: ast.JoinedStr, offs: list[int]) -> str:
    """把 f-string 重建为 ``tf(模板, 参数=表达式)``。

    模板必须**重新拼**而不是照抄源码：源码里的占位符是 ``{pixels[0]:g}`` 这种
    表达式，而参数名已经改成了 ``_v0``，照抄会让 format 找不到 ``pixels``。
    拼好的模板用 ``repr()`` 输出，转义交给 Python 自己处理。
    """
    parts: list[str] = []
    kws: list[str] = []
    seen: set[str] = set()
    reserved = {"tf", "tr", "self", "cls", "None", "True", "False"}

    for v in node.values:
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            parts.append(v.value.replace("{", "{{").replace("}", "}}"))
            continue
        if not isinstance(v, ast.FormattedValue):
            continue
        expr = _slice(raw, v.value, offs)
        if expr.isidentifier() and expr not in seen and expr not in reserved:
            name = expr
        else:
            name = "_v%d" % len(kws)
        seen.add(name)
        piece = "{" + name
        if v.conversion != -1:
            piece += "!" + chr(v.conversion)
        if v.format_spec is not None:
            spec = _slice(raw, v.format_spec, offs)
            # format_spec 节点的源码跨度已经包含前导冒号，别再加一个
            piece += spec if spec.startswith(":") else ":" + spec
        parts.append(piece + "}")
        kws.append("%s=(%s)" % (name, expr))

    template = "".join(parts)
    head = "tf(%r" % template
    return head + (", " + ", ".join(kws) if kws else "") + ")"


def wrap(path: Path, dry: bool) -> tuple[int, int]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    skip = _skip_nodes(tree)
    offs = _byte_offsets(src)
    raw = src.encode("utf-8")

    edits: list[tuple[int, int, bytes]] = []
    n_fstring = 0

    # f-string 整段替换会覆盖它内部的分段常量，必须先把这些子节点全部排除，
    # 否则同一区间会被改写两次，括号落进字符串中间。
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for sub in ast.walk(node):
                skip.add(id(sub))

    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            if not any(isinstance(v, ast.Constant) and isinstance(v.value, str)
                       and CJK_RE.search(v.value) for v in node.values):
                continue
            start = offs[node.lineno - 1] + node.col_offset
            end = offs[node.end_lineno - 1] + node.end_col_offset
            if src[:start].rstrip().endswith(("tf(", "tr(")):
                continue
            edits.append((start, end, _build_tf(raw, node, offs).encode("utf-8")))
            n_fstring += 1
            continue

        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in skip or not CJK_RE.search(node.value):
            continue
        start = offs[node.lineno - 1] + node.col_offset
        end = offs[node.end_lineno - 1] + node.end_col_offset
        prev = raw[max(0, start - 16):start].decode("utf-8", "ignore").rstrip()
        if prev.endswith(("tr(", "tf(")):
            continue
        literal = raw[start:end]
        edits.append((start, end, b"tr(" + literal + b")"))

    if not edits:
        return 0, 0

    out = raw
    for start, end, rep in sorted(edits, key=lambda e: e[0], reverse=True):
        out = out[:start] + rep + out[end:]

    new = out.decode("utf-8")
    if IMPORT_LINE not in new and "from core.i18n import" not in new:
        lines = new.split("\n")
        # __future__ 必须留在最前面（放在它前面会直接 SyntaxError）
        future_end = 0
        insert_at = None
        for i, line in enumerate(lines[:80]):
            s = line.strip()
            if s.startswith("from __future__"):
                future_end = i + 1
                continue
            if s.startswith(("import ", "from ")) and insert_at is None:
                insert_at = i
                break
        if insert_at is None:
            insert_at = future_end
        lines.insert(insert_at, IMPORT_LINE)
        new = "\n".join(lines)

    if not dry:
        path.write_text(new, encoding="utf-8", newline="")
    return len(edits), n_fstring


def collect_used() -> list[str]:
    used: list[str] = []
    for p in _targets():
        tree = ast.parse(p.read_text(encoding="utf-8"))
        raw = p.name in RAW_STRING_MODULES
        skip = _docstring_nodes(tree) if raw else set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("tr", "tf") and node.args):
                a = node.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                        and CJK_RE.search(a.value):
                    used.append(a.value)
            elif raw and isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in skip and CJK_RE.search(node.value):
                used.append(node.value)
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
    # 脚本在 docs/ 下，sys.path[0] 不是项目根，导入 core.i18n_en 前先补上
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

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
