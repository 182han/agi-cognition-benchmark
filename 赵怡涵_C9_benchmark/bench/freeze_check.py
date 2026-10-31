#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冻结检查器：证明「评测跑在冻结数据上」，而不是事后改数据追分。

背景：本基准曾出现一次被作废的运行（`results/void_runs.json` 里的
`deepseek-v4-flash` holdout 0.798）——评测结束后数据被重新生成，导致
分数与题目不再对应。那次是靠人工比对时间戳才发现的，不构成机制保证。

本脚本把这条保证做成可执行的：

    python3 -m bench.freeze_check --create     # 评测前：写 data/FREEZE.json
    python3 -m bench.freeze_check --check      # 评测后：重算并比对，漂移即非零退出

冻结范围
--------
* **inputs**：`data/` 与 `keys/` 下的全部文件。这一组是「题目与答案」，
  任何变化（内容改动、新增、删除）都判定为 FAIL——因为一旦数据变了，
  之前跑的分数就不再属于同一套题。
* **code**：`bench/` 与 `scripts/` 下的全部 .py/.sh。这一组是「生成与评分
  逻辑」，内容改动判定为 FAIL，新增文件只告警（不影响已跑的分数）。

用法示例
--------
    # 创建冻结清单（写入 data/FREEZE.json）
    python3 -m bench.freeze_check --create --note "post-freeze eval baseline"

    # 校验（成功打印 OK，漂移打印明细并非零退出）
    python3 -m bench.freeze_check --check

退出码：0 通过 / 1 漂移 / 2 用法或环境错误
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FREEZE_PATH = os.path.join(ROOT, "data", "FREEZE.json")

INPUT_DIRS = ("data", "keys")
CODE_DIRS = ("bench", "scripts")
CODE_EXT = (".py", ".sh")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def walk(rel_dir: str, exts=None):
    """按字典序返回 rel_dir 下的 (相对路径, 绝对路径)。跳过 __pycache__。

    显式排除 data/FREEZE.json 自身，否则每次 --create 都会把自己写进清单。
    """
    out = []
    base = os.path.join(ROOT, rel_dir)
    if not os.path.isdir(base):
        return out
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in sorted(filenames):
            if exts and not name.endswith(exts):
                continue
            ap = os.path.join(dirpath, name)
            rp = os.path.relpath(ap, ROOT).replace(os.sep, "/")
            if rp == "data/FREEZE.json":
                continue
            if name.startswith("."):
                continue
            out.append((rp, ap))
    return sorted(out)


def collect() -> dict:
    files = {}
    for rel_dir in INPUT_DIRS + CODE_DIRS:
        exts = CODE_EXT if rel_dir in CODE_DIRS else None
        group = "inputs" if rel_dir in INPUT_DIRS else "code"
        for rp, ap in walk(rel_dir, exts):
            files[rp] = {
                "group": group,
                "sha256": sha256_file(ap),
                "bytes": os.path.getsize(ap),
            }
    return files


def cmd_create(note: str, quiet: bool) -> int:
    files = collect()
    doc = {
        "bench": "ΔR-Bench",
        "author": "赵怡涵",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": note,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "n_files": len(files),
        "n_inputs": sum(1 for v in files.values() if v["group"] == "inputs"),
        "n_code": sum(1 for v in files.values() if v["group"] == "code"),
        "files": files,
    }
    os.makedirs(os.path.dirname(FREEZE_PATH), exist_ok=True)
    with open(FREEZE_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    if not quiet:
        print("冻结清单已写入 %s" % os.path.relpath(FREEZE_PATH, ROOT))
        print("  时间    : %s" % doc["created_at"])
        print("  文件数  : %d（inputs %d / code %d）"
              % (doc["n_files"], doc["n_inputs"], doc["n_code"]))
        print("  Python  : %s" % doc["python"])
        print("  备注    : %s" % (note or "-"))
    return 0


def cmd_check(quiet: bool) -> int:
    if not os.path.exists(FREEZE_PATH):
        print("ERROR: 未找到 data/FREEZE.json，请先运行 --create", file=sys.stderr)
        return 2
    with open(FREEZE_PATH, encoding="utf-8") as f:
        doc = json.load(f)
    frozen = doc["files"]
    current = collect()

    changed, missing, added_input, added_code = [], [], [], []
    for rp, meta in sorted(frozen.items()):
        cur = current.get(rp)
        if cur is None:
            missing.append(rp)
        elif cur["sha256"] != meta["sha256"]:
            changed.append((rp, meta["group"], meta["sha256"], cur["sha256"]))
    for rp, meta in sorted(current.items()):
        if rp in frozen:
            continue
        (added_input if meta["group"] == "inputs" else added_code).append(rp)

    hard_fail = bool(changed or missing or added_input)
    if not quiet:
        print("=" * 70)
        print(" ΔR-Bench 冻结校验")
        print(" 冻结时间 : %s" % doc["created_at"])
        print(" 冻结文件 : %d" % doc["n_files"])
        print("=" * 70)
    if not hard_fail and not added_code:
        if not quiet:
            print("OK  全部 %d 个文件与冻结清单一致（未发现任何漂移）"
                  % doc["n_files"])
        return 0
    if changed:
        print("FAIL 内容被修改 %d 个：" % len(changed))
        for rp, grp, a, b in changed:
            print("  - %s [%s]\n      冻结 %s\n      当前 %s" % (rp, grp, a[:16], b[:16]))
    if missing:
        print("FAIL 文件缺失 %d 个：" % len(missing))
        for rp in missing:
            print("  - %s" % rp)
    if added_input:
        print("FAIL 冻结后新增输入文件 %d 个（题目/答案集发生变化）：" % len(added_input))
        for rp in added_input:
            print("  + %s" % rp)
    if added_code:
        print("WARN 新增代码文件 %d 个（不影响已跑分数的题面一致性）：" % len(added_code))
        for rp in added_code:
            print("  + %s" % rp)
    if hard_fail:
        print("\n结论：数据/答案与冻结清单不一致 → 期间产生的分数不可采信。")
        return 1
    print("\n结论：题面与答案未变，仅新增代码文件。")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ΔR-Bench 冻结检查器")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--create", action="store_true", help="写入 data/FREEZE.json")
    g.add_argument("--check", action="store_true", help="校验（默认动作）")
    ap.add_argument("--note", default="", help="--create 时写入备注")
    ap.add_argument("--quiet", action="store_true", help="只在失败时输出")
    args = ap.parse_args(argv)
    if args.create:
        return cmd_create(args.note, args.quiet)
    return cmd_check(args.quiet)


if __name__ == "__main__":
    sys.exit(main())
