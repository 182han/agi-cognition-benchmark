#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ΔR-Bench · 基准冒烟测试（不依赖 pytest，只用标准库）

    python3 tests/test_smoke.py

退出码 0 = 全绿；非 0 = 有未通过项，每项都带修复提示。

检查的是**基准包本身能不能被独立使用**：文件在不在、数据自不自洽、评分器对不对、
答案能不能被独立核验。**不**检查「题目设计得好不好」——那是 `bench/selfcheck.py`
（可归纳性复核）和人的判断。
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from bench.rules import apply_rule, parse_rule_text, rule_fingerprint  # noqa: E402
from bench.scoring import compute_metrics, parse_answer  # noqa: E402

RESULTS = []


def check(name, ok, detail="", fix=""):
    RESULTS.append((name, ok, detail, fix))
    line = "  %s %s" % ("✅" if ok else "❌", name)
    if detail:
        line += " — %s" % detail
    print(line)


def read_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip() and not l.startswith("#")]


def main():
    print("=" * 72)
    print(" ΔR-Bench · 基准冒烟测试")
    print(" 包根目录：%s" % ROOT)
    print("=" * 72)

    # ---------------------------------------------------------------- 文件
    print("\n[1] 必备文件")
    for rel, why in [
        ("README.md", "六段必备：是什么/解决什么/快速开始/示例/结构/技术栈"),
        ("requirements.txt", "依赖清单（本包只用标准库，文件为空即是有意为之）"),
        ("LICENSE", "许可证（MIT）"),
        ("CHANGELOG.md", "真实开发记录"),
        ("scripts/reproduce.sh", "一条命令复现"),
        ("bench/__init__.py", "包入口"),
        ("bench/rules.py", "规则引擎"),
        ("bench/hypothesis.py", "假设搜索与可归纳性判定"),
        ("bench/generate.py", "数据集生成器"),
        ("bench/scoring.py", "评分与指标"),
        ("bench/run_eval.py", "评测运行器"),
        ("bench/contamination.py", "防污染/防作弊审计"),
        ("bench/selfcheck.py", "基准自检"),
        ("bench/models/__init__.py", "解题器适配器"),
        ("data/manifest_dev.json", "数据集生成统计"),
        ("keys/keys_dev.jsonl", "答案 key"),
        ("results/leaderboard.md", "结果汇总榜"),
        ("canary.txt", "canary GUID（沿用 BIG-bench 约定）"),
    ]:
        check("文件 · %s" % rel, os.path.exists(os.path.join(ROOT, rel)), why,
              fix="补齐 %s —— %s" % (rel, why))

    # ---------------------------------------------------------------- 数据
    print("\n[2] 数据集自洽")
    tp = os.path.join(ROOT, "data", "tasks_dev.jsonl")
    kp = os.path.join(ROOT, "keys", "keys_dev.jsonl")
    if not (os.path.exists(tp) and os.path.exists(kp)):
        check("数据文件可读", False, "缺少 tasks_dev.jsonl 或 keys_dev.jsonl",
              "跑 python3 -m bench.generate --split dev --seed 20261031")
        return summarize()

    T = read_jsonl(tp)
    K = {k["item_id"]: k for k in read_jsonl(kp)}

    check("题量 ≥ 20（实际 %d）" % len(T), len(T) >= 20,
          "挑战硬指标",
          "增加 COMPLEXITY_PLAN 里的宇宙数")
    check("题目与答案一一对应",
          set(t["item_id"] for t in T) == set(K),
          "%d 题 / %d 答案" % (len(T), len(K)),
          "重新生成数据集")
    phases = sorted(set(t["phase"] for t in T))
    check("三阶段 A/B/C 齐全", phases == ["A", "B", "C"], "实际 %s" % phases,
          "检查生成器的 emit 调用")
    missing = [t["item_id"] for t in T
               if not t.get("prompt") or not t.get("query")]
    check("每题都有 prompt 与 query", not missing,
          "缺失：%s" % missing[:3], "重新生成")

    # ---------------------------------------------------------------- 答案可核验
    print("\n[3] 答案可独立核验（rule_text → 结构 → 重施 → 等于 answer）")
    bad = []
    for t in T:
        k = K.get(t["item_id"])
        if not k:
            continue
        try:
            rule = parse_rule_text(k["rule_text"])
        except Exception as e:
            bad.append("%s(%s)" % (t["item_id"], e))
            continue
        if rule_fingerprint(rule) != k["rule_fingerprint"]:
            bad.append("%s(指纹)" % t["item_id"])
        elif tuple(apply_rule(tuple(t["query"]["input"]), rule)) != tuple(k["answer"]):
            bad.append("%s(答案)" % t["item_id"])
    check("全部 %d 题的答案可由 rule_text 复算" % len(T), not bad,
          "" if not bad else "不符：%s" % bad[:5],
          "答案 key 与规则不一致 —— 这是最严重的一类错误，必须重生成")

    # ---------------------------------------------------------------- 评分器
    print("\n[4] 评分器行为")
    cases = [
        ("ze mi mi", ["ze", "mi", "mi"], True, "空格分隔"),
        ("[ze, mi, mi]", ["ze", "mi", "mi"], True, "JSON 数组"),
        (" ZE,MI,MI ", ["ze", "mi", "mi"], True, "大写+逗号+空白"),
        ("Answer: ze mi mi", ["ze", "mi", "mi"], True, "带前缀"),
        ("ze mi mi\n此外……", ["ze", "mi", "mi"], True, "多行只取首行"),
        ("none", [], True, "空序列"),
        ("我不知道", ["ze"], False, "非序列 → 解析失败（必须与答错区分）"),
    ]
    ok_all = True
    for raw, gold, want_ok, why in cases:
        got = parse_answer(raw)
        hit = (got is not None) and (tuple(got) == tuple(gold))
        if hit != want_ok:
            ok_all = False
            print("      ✗ %-22r 期望 ok=%s 实际 %r" % (raw, want_ok, got))
    check("规范化与判分正确（%d 个用例）" % len(cases), ok_all, "",
          "检查 bench/scoring.py 的 parse_answer")

    ms = compute_metrics([
        {"item_id": "x1", "phase": "A", "difficulty": "easy",
         "generalization": "id", "universe_public_id": "u",
         "correct": False, "parse_ok": True, "confidence": 0.9,
         "is_copy_input": False},
        {"item_id": "x2", "phase": "B", "difficulty": "easy",
         "generalization": "id", "universe_public_id": "u",
         "correct": True, "parse_ok": True, "confidence": 0.8,
         "is_copy_input": False},
    ])
    check("指标计算（LearningGain = B − A）",
          abs(ms["LearningGain_B_minus_A"] - 1.0) < 1e-9,
          "LearningGain=%s" % ms["LearningGain_B_minus_A"],
          "检查 compute_metrics")
    check("ECE 可计算", ms["ECE"] is not None and ms["ECE"] >= 0,
          "ECE=%s" % ms["ECE"], "检查 expected_calibration_error")

    # ---------------------------------------------------------------- 防作弊结构
    print("\n[5] 防作弊的结构性保障")
    leak = []
    for t in T:
        k = K.get(t["item_id"])
        if k and k["answer"]:
            # 只搜 QUERY 之后的文本，**并排除 QUERY 那一行本身**——与
            # bench/contamination.py 的 A2 审计保持同一口径。
            # 为什么必须排除：当隐藏规则在某些输入上恰好是恒等时（条件分支未触发），
            # 正确答案就等于查询输入本身，此时"答案串出现在提示词里"是任务的固有性质，
            # 不是泄漏。不排除的话这条检查会永远报警（实测 3/84 假阳性），
            # 而一条永远为红的检查等于没有检查。恒等情形由 A4「抄输入可得率」单独量化。
            tail_lines = t["prompt"].split("QUERY:")[-1].splitlines()
            tail = "\n".join(tail_lines[1:]) if tail_lines else ""
            if " ".join(k["answer"]) in tail:
                leak.append(t["item_id"])
    check("提示词里没有答案泄漏（排除 QUERY 行）", not leak, "泄漏：%s" % leak[:3],
          "检查 render_prompt 是否误把答案写进题面")
    check("题目与答案物理分离（keys/ 不在 data/ 里）",
          os.path.exists(kp) and not os.path.exists(
              os.path.join(ROOT, "data", "keys_dev.jsonl")),
          "keys/ 与 data/ 是两个目录",
          "保持目录分离——这是防止答案进提示词的第一道结构保障")
    cm = os.path.exists(os.path.join(ROOT, "data", "control_corrupt_dev.jsonl"))
    pm = os.path.exists(os.path.join(ROOT, "data", "perturb_dev.jsonl"))
    check("控制集与扰动集存在", cm and pm,
          "control_corrupt=%s perturb=%s" % (cm, pm),
          "重新生成数据集")

    return summarize()


def summarize():
    print("\n" + "=" * 72)
    npass = sum(1 for _, ok, _, _ in RESULTS if ok)
    print(" 结果：%d/%d 通过" % (npass, len(RESULTS)))
    print("=" * 72)
    failed = [(n, d, f) for n, ok, d, f in RESULTS if not ok]
    if failed:
        print("\n未通过 %d 项：\n" % len(failed))
        for i, (n, d, f) in enumerate(failed, 1):
            print("  %d. ❌ %s" % (i, n))
            if d:
                print("     现象：%s" % d)
            if f:
                print("     修复：%s" % f)
        return 1
    print("\n✅ 全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
