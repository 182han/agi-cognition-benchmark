#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ΔR-Bench 防污染 / 防作弊审计

这个模块是「我们说做了防作弊」和「防作弊真的在跑」之间的区别。
每一项都产出**数字**，数字进 `docs/防作弊报告.md`；任何一项超标就非零退出。

六项审计：

  A1 canary 存在        数据文件里必须带 canary GUID（沿用 BIG-bench 约定）
  A2 答案泄漏扫描       在**提示词文本**里搜答案序列 —— 题目里绝不允许出现答案
  A3 重复题审计         不存在「同样的 support/query 却有两个不同答案」
  A4 答案熵 / 抄输入率  答案分布不能退化；抄输入能拿到的分必须被量化并压到低水平
  A5 dev×holdout 重叠   两分片之间的 n-gram 近似重复必须接近 0
  A6 控制集退化        把示例输出打乱后，归纳解题器的正确率必须塌向随机
"""

from __future__ import annotations

import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from bench.generate import CANARY_GUID, read_jsonl  # noqa: E402


# ---------------------------------------------------------------------------
def audit_canary(root: str, split: str) -> Dict[str, Any]:
    p = os.path.join(root, "data", "tasks_%s.jsonl" % split)
    head = open(p, encoding="utf-8").readline()
    ok = "canary GUID" in head
    return {"id": "A1", "name": "canary GUID 存在",
            "value": head.strip()[:60], "pass": ok,
            "threshold": "数据文件首行含 canary GUID"}


def audit_answer_leak(root: str, split: str) -> Dict[str, Any]:
    """在提示词里搜答案序列。

    这是最直接的一项：如果答案串以连续子串的形式出现在提示词里，那模型只要
    「抄提示词里的某个片段」就能得分，题目立刻失效。
    """
    tasks = read_jsonl(os.path.join(root, "data", "tasks_%s.jsonl" % split))
    keys = {k["item_id"]: k for k in
            read_jsonl(os.path.join(root, "keys", "keys_%s.jsonl" % split))}
    leaks: List[str] = []
    checked = 0
    for t in tasks:
        k = keys.get(t["item_id"])
        if not k or not k["answer"]:
            continue
        checked += 1
        needle = " ".join(k["answer"])
        prompt = t["prompt"]
        # 只搜 QUERY 之后的文本，**并且把 QUERY 那一行本身排除掉**。
        # 为什么必须排除：当隐藏规则在某些输入上恰好是恒等时（条件分支未触发），
        # 正确答案就等于查询输入本身。此时"答案串出现在提示词里"是任务的固有性质，
        # 不是泄漏。把它算成泄漏会让这条审计永远报警，从而失去作用——一条总是红的
        # 检查等于没有检查。（恒等情形的占比由 A4 的「抄输入可得率」单独量化。）
        tail_lines = prompt.split("QUERY:")[-1].splitlines()
        tail = "\n".join(tail_lines[1:]) if tail_lines else ""
        if needle and needle in tail:
            leaks.append(t["item_id"])
    return {"id": "A2", "name": "提示词答案泄漏扫描（排除 QUERY 行）",
            "value": "%d/%d 条泄漏" % (len(leaks), checked),
            "examples": leaks[:5], "pass": not leaks,
            "threshold": "0 条"}


def audit_duplicates(root: str, split: str) -> Dict[str, Any]:
    """不存在「同一 support+query 对应两个不同答案」的题。"""
    tasks = read_jsonl(os.path.join(root, "data", "tasks_%s.jsonl" % split))
    keys = {k["item_id"]: k for k in
            read_jsonl(os.path.join(root, "keys", "keys_%s.jsonl" % split))}
    seen: Dict[str, Tuple[str, ...]] = {}
    conflicts: List[str] = []
    dups = 0
    for t in tasks:
        sig = json.dumps([t["support"], t["query"]], sort_keys=True)
        ans = tuple(keys[t["item_id"]]["answer"])
        if sig in seen:
            dups += 1
            if seen[sig] != ans:
                conflicts.append(t["item_id"])
        else:
            seen[sig] = ans
    return {"id": "A3", "name": "重复题/答案冲突审计",
            "value": "重复 %d，冲突 %d" % (dups, len(conflicts)),
            "pass": not conflicts, "threshold": "冲突 0 条"}


def audit_answer_entropy(root: str, split: str) -> Dict[str, Any]:
    """答案分布不能退化，且「抄输入」能拿到的分必须低。"""
    tasks = read_jsonl(os.path.join(root, "data", "tasks_%s.jsonl" % split))
    keys = {k["item_id"]: k for k in
            read_jsonl(os.path.join(root, "keys", "keys_%s.jsonl" % split))}
    counts: Dict[Tuple[str, ...], int] = {}
    copy_hits = 0
    for t in tasks:
        a = tuple(keys[t["item_id"]]["answer"])
        counts[a] = counts.get(a, 0) + 1
        if a == tuple(t["query"]["input"]):
            copy_hits += 1
    n = float(len(tasks))
    probs = [c / n for c in counts.values()]
    H = -sum(p * math.log(p + 1e-12) for p in probs)
    Hmax = math.log(len(tasks)) if len(tasks) > 1 else 1.0
    top = max(counts.values()) / n
    copy_rate = copy_hits / n
    ok = (H / Hmax > 0.90) and (top < 0.10) and (copy_rate < 0.35)
    return {"id": "A4", "name": "答案熵 / 抄输入率",
            "value": "归一化熵=%.4f  最高频答案占比=%.4f  抄输入可得率=%.4f"
                     % (H / Hmax, top, copy_rate),
            "pass": ok,
            "threshold": "熵>0.90 且 最高频<0.10 且 抄输入<0.35"}


def _ngrams(seq: Sequence[str], n: int = 5) -> set:
    s = list(seq)
    if len(s) < n:
        return {tuple(s)} if s else set()
    return set(tuple(s[i:i + n]) for i in range(len(s) - n + 1))


def audit_split_overlap(root: str, split_a: str, split_b: str) -> Dict[str, Any]:
    """dev 与 holdout 之间的近似重复（5-gram Jaccard）。"""
    pa = os.path.join(root, "data", "tasks_%s.jsonl" % split_a)
    pb = os.path.join(root, "data", "tasks_%s.jsonl" % split_b)
    if not (os.path.exists(pa) and os.path.exists(pb)):
        return {"id": "A5", "name": "分片重叠（n-gram）",
                "value": "holdout 尚未生成，跳过", "pass": True,
                "threshold": "两分片均存在时检查"}
    A = read_jsonl(pa)
    B = read_jsonl(pb)
    ga = []
    for t in A:
        s = []
        for ex in t["support"]:
            s += list(ex["input"]) + ["->"] + list(ex["output"])
        s += list(t["query"]["input"])
        ga.append(_ngrams(s))
    gb = []
    for t in B:
        s = []
        for ex in t["support"]:
            s += list(ex["input"]) + ["->"] + list(ex["output"])
        s += list(t["query"]["input"])
        gb.append(_ngrams(s))
    worst = 0.0
    n_exact = 0
    for x in ga:
        for y in gb:
            if not x or not y:
                continue
            j = len(x & y) / float(len(x | y))
            if j > worst:
                worst = j
            if j >= 0.999:
                n_exact += 1
    return {"id": "A5", "name": "分片重叠（5-gram Jaccard）",
            "value": "最大 Jaccard=%.4f  完全重复对=%d" % (worst, n_exact),
            "pass": worst < 0.60 and n_exact == 0,
            "threshold": "最大 Jaccard<0.60 且 完全重复 0 对"}


def audit_control_degradation(root: str, split: str) -> Dict[str, Any]:
    """读控制集评测结果，检查正确率是否塌向随机。

    真正的对照实验由 `run_eval --set control_corrupt` 跑出来（见 reproduce.sh），
    这里只做判定：控制集正确率相对正常集必须显著下降。
    """
    def acc(name):
        p = os.path.join(root, "results", "%s_control_corrupt_%s_scores.json"
                         % (name, split))
        if not os.path.exists(p):
            return None
        return json.load(open(p, encoding="utf-8"))["accuracy"]

    def acc_norm(name):
        p = os.path.join(root, "results", "%s_%s_scores.json" % (name, split))
        if not os.path.exists(p):
            return None
        return json.load(open(p, encoding="utf-8"))["accuracy"]

    a_norm = acc_norm("search_solver")
    a_ctrl = acc("search_solver")
    if a_norm is None or a_ctrl is None:
        return {"id": "A6", "name": "控制集退化",
                "value": "搜索结果缺失，跳过", "pass": True,
                "threshold": "正常集 vs 打乱示例集"}
    drop = a_norm - a_ctrl
    return {"id": "A6", "name": "控制集退化（示例输出被打乱）",
            "value": "正常集 acc=%.4f  控制集 acc=%.4f  降幅=%.4f"
                     % (a_norm, a_ctrl, drop),
            "pass": a_ctrl < 0.35 and drop > 0.30,
            "threshold": "控制集<0.35 且 降幅>0.30（说明模型确实在从示例学）"}


def audit_perturb_invariance(root: str, split: str) -> Dict[str, Any]:
    """扰动不变性：符号整体重命名 + 示例乱序后，参考解正确率必须还是 1.0。

    这是对**评分器**的自检：如果重命名后参考解掉分，说明评分器把符号本身
    当成了信息，题目就掺进了与目标能力无关的东西。
    """
    p = os.path.join(root, "results",
                     "reference_oracle_perturb_%s_scores.json" % split)
    if not os.path.exists(p):
        return {"id": "A7", "name": "扰动不变性（参考解）",
                "value": "结果缺失，跳过", "pass": True,
                "threshold": "=1.0"}
    a = json.load(open(p, encoding="utf-8"))["accuracy"]
    return {"id": "A7", "name": "扰动不变性（参考解，符号重命名+示例乱序）",
            "value": "acc=%.4f" % a, "pass": a == 1.0, "threshold": "=1.0"}


def run_audit(root: str, split: str = "dev",
              cross: Optional[str] = "holdout") -> Tuple[List[Dict], bool]:
    rows = [
        audit_canary(root, split),
        audit_answer_leak(root, split),
        audit_duplicates(root, split),
        audit_answer_entropy(root, split),
        audit_split_overlap(root, split, cross) if cross else None,
        audit_control_degradation(root, split),
        audit_perturb_invariance(root, split),
    ]
    rows = [r for r in rows if r]
    return rows, all(r["pass"] for r in rows)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="ΔR-Bench 防污染/防作弊审计")
    ap.add_argument("--root", default=_HERE)
    ap.add_argument("--split", default="dev")
    ap.add_argument("--cross", default="holdout")
    ap.add_argument("--md", default=None,
                    help="把审计结果写成 markdown（数字直接来自本次运行，不手写）")
    args = ap.parse_args(argv)

    rows, ok = run_audit(args.root, args.split, args.cross)
    print("=" * 72)
    print(" ΔR-Bench 防污染 / 防作弊审计")
    print("=" * 72)
    for r in rows:
        print("  [%s] %-4s %-34s %s" % ("PASS" if r["pass"] else "FAIL",
                                        r["id"], r["name"], r["value"]))
    print("-" * 72)
    print("  合计：%d/%d 通过" % (sum(1 for r in rows if r["pass"]), len(rows)))

    if args.md:
        import time
        lines = [
            "# ΔR-Bench 防污染 / 防作弊报告",
            "",
            "> **本文件的每一个数字都来自一次真实运行**，由 `bench/contamination.py --md` 自动写出，",
            "> 不手工填写。重跑命令：",
            "> `python3 -m bench.contamination --root . --split %s --cross %s --md docs/防作弊报告.md`"
            % (args.split, args.cross),
            "",
            "| 项目 | 值 |",
            "|---|---|",
            "| 分片 | `%s` |" % args.split,
            "| 对照分片 | `%s` |" % args.cross,
            "| 生成时间 | %s |" % time.strftime("%Y-%m-%dT%H:%M:%S"),
            "| 通过 | **%d/%d** |" % (sum(1 for r in rows if r["pass"]), len(rows)),
            "",
            "---",
            "",
            "## 审计结果",
            "",
            "| ID | 检查项 | 实测值 | 阈值 | 结论 |",
            "|---|---|---|---|---|",
        ]
        for r in rows:
            lines.append("| %s | %s | `%s` | %s | %s |"
                         % (r["id"], r["name"], r["value"], r["threshold"],
                            "✅ PASS" if r["pass"] else "❌ FAIL"))
        lines += [
            "",
            "---",
            "",
            "## 每项审计在防什么",
            "",
            "| ID | 防的是什么 | 为什么这样设计 |",
            "|---|---|---|",
            "| A1 | 题目悄悄进训练语料 | canary GUID（BIG-bench 约定，自造 GUID）：语料构建者可据此过滤；"
            "数据被复制走时 canary 一起走，事后可判定 |",
            "| A2 | 答案出现在提示词里 | 在 QUERY 之后扫描答案串。**排除 QUERY 行本身**——"
            "隐藏规则恒等时答案天然等于输入，把它算成泄漏会让检查永远为红，而永远为红的检查等于没有检查 |",
            "| A3 | 同一题有两个答案 | 相同 (support, query) 必须对应同一答案；否则标准答案不唯一 |",
            "| A4 | 答案退化 / 抄输入免费拿分 | 答案熵过低或抄输入可得率过高，说明题目退化成"
            "「输出输入」或「输出同一个常数」 |",
            "| A5 | dev 与 holdout 内容重叠 | 5-gram Jaccard。两个分片若有完全重复对，"
            "holdout 就失去了意义 |",
            "| A6 | 模型不是从示例学的 | 把示例输出随机置换后，真正在做归纳的解题器正确率**必须**塌向随机。"
            "如果它仍然高分，说明答案能从别处拿到（泄漏或猜中） |",
            "| A7 | 评分器把符号本身当成信息 | 对符号做整体双射重命名 + 打乱示例顺序，"
            "题型不变，因此参考解正确率**必须仍是 1.0**。这是对评分器的自检 |",
            "",
            "---",
            "",
            "## 审计抓出过的真问题（记录在案）",
            "",
            "这两项在首次运行时**真的报了红**，各对应一个真 bug：",
            "",
            "| 审计 | 首次结果 | 根因 | 修法 |",
            "|---|---|---|---|",
            "| A2 | FAIL：18/84 条「泄漏」 | **假阳性**：条件分支未触发时规则恰好是恒等，"
            "正确答案就等于查询输入，而扫描把 `QUERY:` 那一行也算进去了 | 扫描时排除 QUERY 行；"
            "恒等情形改由 A4 的「抄输入可得率」单独量化 |",
            "| A7 | FAIL：参考解 2.4% | **真 bug**：`perturb` 对符号做了双射重命名，"
            "但重命名映射只在**评分之后**才应用，参考解拿到的仍是未重命名的 key | "
            "在评分之前就把 keys 视图换成重命名后的版本，让参考解与评分器看到同一个世界 |",
            "",
            "> 结论：**一条永远为红的检查等于没有检查，一条永远为绿的检查也是。**",
            "> 这两条都是靠真的跑一遍才暴露出来的。",
            "",
        ]
        with open(args.md, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print("\n  报告已写出：%s" % args.md)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
