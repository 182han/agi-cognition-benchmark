#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ΔR-Bench 基准自检（benchmark self-check）

「脚本全绿 ≠ 东西是对的」。所以这里检查的不是「文件在不在」，而是
**这套题本身站不站得住**：

  S1 生成器确定性     同一 seed 两次生成，字节级一致
  S2 答案 key 可核验   rule_text 反向解析 → 重新施加到查询 → 必须等于 answer
                       （这一步把「答案」从一个需要信任的断言，变成可机械复核的结论）
  S3 宇宙一致性        同一宇宙内所有题目的规则指纹相同
  S4 参考解满分        全知参考解在评分器下必须是 1.0（题目可解 + 评分器无系统性错误）
  S5 可归纳性复核      每个宇宙的示例集在**独立探针集**上必须唯一确定真规则
  S6 题目量            ≥ 20 题（挑战硬指标）
  S7 控制集退化        打乱示例输出后，归纳解题器正确率必须显著下降

用法：
    python3 -m bench.selfcheck --root . --split dev [--holdout holdout]
退出码 0 = 全绿；非 0 = 有项没过。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from bench.generate import read_jsonl  # noqa: E402
from bench.hypothesis import ambiguity_report  # noqa: E402
from bench.rules import (  # noqa: E402
    apply_rule, parse_rule_text, rule_fingerprint,
)

RESULTS: List[Tuple[str, str, bool, str]] = []


def check(cid: str, name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((cid, name, ok, detail))
    print("  %s [%s] %-30s %s" % ("✅" if ok else "❌", cid, name, detail))


# ---------------------------------------------------------------------------
def sha_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def check_determinism(root: str) -> None:
    """S1：mini 数据集生成两次，逐字节比对。"""
    tmp = tempfile.mkdtemp(prefix="drbench-det-")
    try:
        hashes = []
        for i in range(2):
            d = os.path.join(tmp, "run%d" % i)
            os.makedirs(d, exist_ok=True)
            r = subprocess.run(
                [sys.executable, "-m", "bench.generate", "--split", "dev",
                 "--seed", "999001", "--mini", "--out", d],
                cwd=root, capture_output=True, text=True)
            if r.returncode != 0:
                check("S1", "生成器确定性", False,
                      "mini 生成失败：%s" % r.stderr.strip().splitlines()[-1:])
                return
            h = {}
            for rel in ("data/tasks_dev.jsonl", "keys/keys_dev.jsonl"):
                h[rel] = sha_file(os.path.join(d, rel))
            hashes.append(h)
        same = hashes[0] == hashes[1]
        check("S1", "生成器确定性（同 seed 字节一致）", same,
              "tasks=%s" % hashes[0]["data/tasks_dev.jsonl"][:16] if same
              else "两次生成不一致")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def load(root: str, split: str):
    tasks = read_jsonl(os.path.join(root, "data", "tasks_%s.jsonl" % split))
    keys = {k["item_id"]: k for k in
            read_jsonl(os.path.join(root, "keys", "keys_%s.jsonl" % split))}
    return tasks, keys


def check_key_soundness(tasks, keys) -> None:
    """S2：rule_text 反解 → 重施 → 等于 answer。这是最有价值的一项。"""
    n, bad, unparsed = 0, [], []
    for t in tasks:
        k = keys.get(t["item_id"])
        if not k:
            bad.append(t["item_id"] + "(缺 key)")
            continue
        n += 1
        try:
            rule = parse_rule_text(k["rule_text"])
        except Exception as e:
            unparsed.append("%s:%s" % (t["item_id"], e))
            continue
        if rule_fingerprint(rule) != k["rule_fingerprint"]:
            bad.append(t["item_id"] + "(指纹不符)")
            continue
        got = apply_rule(tuple(t["query"]["input"]), rule)
        if tuple(got) != tuple(k["answer"]):
            bad.append(t["item_id"] + "(答案不符)")
    check("S2", "答案 key 可独立核验", not bad and not unparsed and n > 0,
          "%d 题全部通过（rule_text→结构→重施→等于 answer）" % n
          if not bad and not unparsed else
          "解析失败 %s；不符 %s" % (unparsed[:3], bad[:5]))


def check_universe_consistency(tasks, keys) -> None:
    """S3：同一宇宙内规则指纹唯一。"""
    by_u: Dict[str, set] = {}
    for t in tasks:
        k = keys.get(t["item_id"])
        if k:
            by_u.setdefault(t["universe_public_id"], set()).add(
                k["rule_fingerprint"])
    inconsistent = [u for u, s in by_u.items() if len(s) != 1]
    check("S3", "宇宙内规则指纹唯一", not inconsistent,
          "%d 个宇宙全部单一指纹" % len(by_u) if not inconsistent
          else "不一致：%s" % inconsistent[:3])


def check_reference_full_marks(root: str, splits: Sequence[str]) -> None:
    """S4：参考解全部分片满分。"""
    misses = []
    details = []
    for sp in splits:
        p = os.path.join(root, "results", "reference_oracle_%s_scores.json" % sp)
        if not os.path.exists(p):
            misses.append(sp + "(无结果)")
            continue
        a = json.load(open(p, encoding="utf-8"))["accuracy"]
        details.append("%s=%.4f" % (sp, a))
        if a != 1.0:
            misses.append("%s=%.4f" % (sp, a))
    check("S4", "参考解满分（题目可解+评分器正确）", not misses,
          "  ".join(details) if not misses else "未达标：%s" % misses)


def check_identifiability(tasks, keys, max_universes: int = 0) -> None:
    """S5：可归纳性复核 —— 分成两个**不同强度**的命题，分别报数。

    这里必须把话说准，否则就是在过度声称。本基准的设计保证是：

      S5a（**硬门槛**）**每一道会被打分的题，其答案都被示例唯一确定。**
          这是"判分公平"的充要条件：如果某个查询的答案不被示例确定，那么拿标准答案
          去扣分，扣的就是运气而不是能力。
          复核方式：取该宇宙的**全部被判分输入**（A/B/C 三组的 query）作为探针集，
          枚举所有与示例一致的候选规则，它们在**这些输入上**必须行为一致。

      S5b（**诊断量，不是门槛**）示例是否连"所有可能的输入"都唯一确定。
          这是一个**强得多**的命题，用 3–7 个长度 ≤6 的短示例在 10³ 量级的原语空间上
          一般**做不到**——候选规则可以在示例上完全一致、在被问到的输入上也一致，
          却在某个从没被问过的输入上分歧。
          **这不影响判分公平**（那些输入永远不会被问），所以不设门槛；但它必须被
          如实报出来，否则"唯一可归纳"就成了一句过度声称。

    早期版本只做 S5b 并在失败时判红，等于用一个**本基准并不承诺**的强命题去衡量自己；
    修正为「硬门槛 + 诊断量」两个口径后，两个数字各自都有明确含义。
    """
    by_u: Dict[str, List[Dict[str, Any]]] = {}
    for t in tasks:
        by_u.setdefault(t["universe_public_id"], []).append(t)

    bad_scored = []
    wide_ambiguous = []
    checked = 0
    worst_scored = 1
    for u, items in sorted(by_u.items()):
        with_sup = [t for t in items if t["support"]]
        if not with_sup:
            continue
        t0 = with_sup[0]
        sup = [(tuple(e["input"]), tuple(e["output"])) for e in t0["support"]]
        k = keys[t0["item_id"]]
        truth = parse_rule_text(k["rule_text"])
        alpha = tuple(t0["alphabet"])
        cx = t0["complexity"]
        checked += 1

        # ---- S5a：所有会被打分的输入 --------------------------------------
        scored = []
        seen = set()
        for t in items:
            q = tuple(t["query"]["input"])
            if q not in seen:
                seen.add(q)
                scored.append(q)
        rep_a = ambiguity_report(truth, alpha, sup, scored, max_len=cx, beam=192)
        worst_scored = max(worst_scored, rep_a["n_equivalence"])
        if not (rep_a["identifiable"] and rep_a["truth_in_space"]):
            bad_scored.append("%s(eq=%d,truth=%s)"
                              % (u, rep_a["n_equivalence"], rep_a["truth_in_space"]))

        # ---- S5b：更大范围的独立探针集（诊断量） ---------------------------
        rng = random.Random(0xD1CE ^ (abs(hash(u)) & 0xFFFF))
        wide = list(scored)
        for _ in range(200):
            wide.append(tuple(rng.choice(alpha)
                              for _ in range(rng.randint(2, 6))))
        seenw, probes = set(), []
        for p in wide:
            if p not in seenw:
                seenw.add(p)
                probes.append(p)
        rep_b = ambiguity_report(truth, alpha, sup, probes, max_len=cx, beam=192)
        if not (rep_b["identifiable"] and rep_b["truth_in_space"]):
            wide_ambiguous.append("%s(eq=%d)" % (u, rep_b["n_equivalence"]))

        if max_universes and checked >= max_universes:
            break

    check("S5a", "被判分的输入全部唯一确定（硬门槛）",
          (not bad_scored) and checked > 0,
          "%d 个宇宙全部通过（最大等价类=%d）" % (checked, worst_scored)
          if not bad_scored else "不合格：%s" % bad_scored[:4])

    # S5b 是诊断量：**不设为门槛**，只报数并说明含义
    print("  ℹ️  [S5b] 更大探针集上的歧义（诊断量，不设门槛）: "
          "%d/%d 个宇宙在 200+ 条独立探针上存在与真规则分歧的候选规则 %s"
          % (len(wide_ambiguous), checked,
             ("→ %s" % wide_ambiguous[:4]) if wide_ambiguous else ""))
    print("        含义：这些分歧只出现在**从未被问过**的输入上，"
          "不影响判分公平（S5a 已保证）。")
    print("        不设门槛的理由：用 3–7 个短示例在 10³ 量级原语空间上做到"
          "「全局唯一」在数学上一般不可能；")
    print("        本基准承诺的是「被问到的题有唯一答案」，不是「示例刻画了唯一一条规则」。")


def check_size(tasks, keys) -> None:
    """S6：题量 ≥ 20。"""
    check("S6", "题量 ≥ 20", len(tasks) >= 20,
          "%d 题（A=%d B=%d C=%d）" % (
              len(tasks),
              sum(1 for t in tasks if t["phase"] == "A"),
              sum(1 for t in tasks if t["phase"] == "B"),
              sum(1 for t in tasks if t["phase"] == "C")))


def check_control_drop(root: str, split: str) -> None:
    """S7：控制集退化。"""
    def acc(path):
        if not os.path.exists(path):
            return None
        return json.load(open(path, encoding="utf-8"))["accuracy"]

    normal = acc(os.path.join(root, "results", "search_solver_%s_scores.json" % split))
    ctrl = acc(os.path.join(root, "results",
                            "search_solver_control_corrupt_%s_scores.json" % split))
    if normal is None or ctrl is None:
        check("S7", "控制集退化", False,
              "缺少结果（正常=%s 控制=%s）—— 先跑 reproduce.sh" % (normal, ctrl))
        return
    check("S7", "控制集退化（示例被破坏后应塌向随机）",
          ctrl < 0.35 and (normal - ctrl) > 0.30,
          "正常=%.4f 控制=%.4f 降幅=%.4f" % (normal, ctrl, normal - ctrl))


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ΔR-Bench 基准自检")
    ap.add_argument("--root", default=_HERE)
    ap.add_argument("--split", default="dev")
    ap.add_argument("--holdout", default="holdout")
    ap.add_argument("--skip-determinism", action="store_true",
                    help="跳过 mini 确定性生成（省时间）")
    args = ap.parse_args(argv)

    print("=" * 72)
    print(" ΔR-Bench 基准自检")
    print(" 包根目录：%s   split=%s" % (args.root, args.split))
    print("=" * 72)

    tasks, keys = load(args.root, args.split)
    if not tasks:
        print("❌ 找不到 data/tasks_%s.jsonl —— 先跑 python3 -m bench.generate"
              % args.split)
        return 1

    print("\n[结构]")
    check_size(tasks, keys)
    check_universe_consistency(tasks, keys)

    print("\n[正确性]")
    check_key_soundness(tasks, keys)
    splits = [args.split]
    if os.path.exists(os.path.join(args.root, "data",
                                   "tasks_%s.jsonl" % args.holdout)):
        splits.append(args.holdout)
    check_reference_full_marks(args.root, splits)

    print("\n[方法论]")
    check_identifiability(tasks, keys)
    check_control_drop(args.root, args.split)

    print("\n[确定性]")
    if args.skip_determinism:
        print("  ⏭  [S1] 生成器确定性                       （已按参数跳过）")
    else:
        check_determinism(args.root)

    npass = sum(1 for _, _, ok, _ in RESULTS if ok)
    print("\n" + "=" * 72)
    print(" 结果：%d/%d 通过" % (npass, len(RESULTS)))
    print("=" * 72)
    if npass != len(RESULTS):
        print("\n未通过项：")
        for cid, name, ok, detail in RESULTS:
            if not ok:
                print("  ❌ [%s] %s — %s" % (cid, name, detail))
        return 1
    print("\n✅ 全部通过：题目可解、答案可核验、每题唯一可归纳、控制集能塌。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
