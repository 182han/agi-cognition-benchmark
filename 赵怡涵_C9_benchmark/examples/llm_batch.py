#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 ΔR-Bench 的题目导出成「任何模型（或人类）都能答」的批次文件。

这是「不伪造模型分数」这条红线的工程化落地：**模型只看到 prompt，看不到答案**。
导出 → 外部真实作答 → 回收原始回答 → 由 run_eval 评分。中间任何一步都不许手改。

三个子命令：

  export1  --split <s> --out <dir>
      导出 Round 1（Phase A + B）批次：batch1.json（含每题 item_id 与 prompt）

  ingest1  --raw <jsonl> --answers <jsonl>
      回收 Round 1 的原始回答（{"item_id","raw","confidence"?}），写进 raw 记录

  export2  --split <s> --raw <jsonl> --out <dir>
      用 Round 1 的真实回答构造 Round 2（Phase C）批次 —— 反馈内容全部来自
      模型自己的真实作答，不是模板化的假反馈

  ingest2  --raw <jsonl> --answers <jsonl>
      回收 Round 2 的原始回答，追加进 raw 记录

raw 记录交给 run_eval 复算：

  python3 -m bench.run_eval --model recorded_llm \
      --model-name <模型名> --raw <raw.jsonl> --split <s>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from bench.generate import read_jsonl  # noqa: E402
from bench.run_eval import build_round2, load_split  # noqa: E402
from bench.scoring import parse_answer  # noqa: E402


def _dump_batch(tasks, path):
    rows = [{"item_id": t["item_id"], "round": t.get("round", 1),
             "prompt": t["prompt"]} for t in tasks]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    return len(rows)


def _load_raw(path):
    """读原始回答记录 → {item_id: {...}}（同 id 以最后一次为准）。"""
    out: Dict[str, Dict[str, Any]] = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                r = json.loads(line)
                out[r["item_id"]] = r
    return out


def cmd_export1(args):
    tasks, _ = load_split(args.root, args.split)
    r1 = [t for t in tasks if t["phase"] in ("A", "B")]
    p = os.path.join(args.out, "batch1.json")
    os.makedirs(args.out, exist_ok=True)
    n = _dump_batch(r1, p)
    print("Round 1 批次已导出：%d 题 → %s" % (n, p))
    return 0


def cmd_ingest1(args):
    answers = read_jsonl(args.answers) if args.answers.endswith(".jsonl") \
        else json.load(open(args.answers, encoding="utf-8"))
    rows = []
    for a in answers:
        rows.append({
            "item_id": a["item_id"],
            "round": 1,
            "model": args.model_name,
            "raw": a.get("raw"),
            "confidence": a.get("confidence"),
            "run_at": args.run_at,
        })
    with open(args.raw, "w", encoding="utf-8") as f:
        f.write("# 原始回答记录 —— 不许手改。任何 LLM 分数都必须能追溯到这里的逐题原文。\n")
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("Round 1 回收 %d 条 → %s" % (len(rows), args.raw))
    return 0


def cmd_export2(args):
    tasks, keys = load_split(args.root, args.split)
    r1 = [t for t in tasks if t["phase"] in ("A", "B")]
    c_tasks = [t for t in tasks if t["phase"] == "C"]
    raw = _load_raw(args.raw)
    preds = {}
    for iid, r in raw.items():
        preds[iid] = {"raw": r.get("raw"), "answer": parse_answer(r.get("raw")),
                      "confidence": r.get("confidence")}
    r2 = build_round2(c_tasks, r1, preds, keys)
    os.makedirs(args.out, exist_ok=True)
    p = os.path.join(args.out, "batch2.json")
    n = _dump_batch(r2, p)
    n_wrong = sum(1 for t in r2
                  if t.get("feedback", {}).get("verdict") == "WRONG")
    print("Round 2 批次已导出：%d 题（其中 %d 题的反馈是「你答错了」）→ %s"
          % (n, n_wrong, p))
    return 0


def cmd_ingest2(args):
    answers = read_jsonl(args.answers) if args.answers.endswith(".jsonl") \
        else json.load(open(args.answers, encoding="utf-8"))
    with open(args.raw, "a", encoding="utf-8") as f:
        for a in answers:
            f.write(json.dumps({
                "item_id": a["item_id"], "round": 2, "model": args.model_name,
                "raw": a.get("raw"), "confidence": a.get("confidence"),
                "run_at": args.run_at,
            }, ensure_ascii=False) + "\n")
    print("Round 2 回收 %d 条 → %s（已追加）" % (len(answers), args.raw))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="ΔR-Bench 批次导出/回收")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("export1", "export2", "ingest1", "ingest2"):
        s = sub.add_parser(name)
        s.add_argument("--root", default=_HERE)
        s.add_argument("--split", default="holdout")
        s.add_argument("--out", default=os.path.join(_HERE, "results", "batch"))
        s.add_argument("--raw", default=None)
        s.add_argument("--answers", default=None)
        s.add_argument("--model-name", default="unknown")
        s.add_argument("--run-at", default="")
    args = ap.parse_args(argv)
    if args.cmd == "export1":
        return cmd_export1(args)
    if args.cmd == "export2":
        return cmd_export2(args)
    if args.cmd == "ingest1":
        return cmd_ingest1(args)
    return cmd_ingest2(args)


if __name__ == "__main__":
    sys.exit(main())
