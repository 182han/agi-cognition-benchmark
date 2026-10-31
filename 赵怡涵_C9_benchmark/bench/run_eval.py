#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ΔR-Bench 评测运行器

两轮交互协议（这是本基准与「一次性答题」型基准的关键差别）：

    Round 1：Phase A（不给示例）+ Phase B（给示例）
    Round 2：Phase C —— **把模型自己在 Round 1 的答案与正确答案一起回灌给它**，
             再问同一宇宙的新问题。

Round 2 的构造由本脚本完成，规则写死在这里：

  * 每个宇宙取 Round 1 的第一道 Phase B 题作为「被反馈的那道题」；
  * 反馈里写明它当时的答案、判对判错、以及正确答案；
  * 该「(查询 → 正确答案)」对同时被并入 Round 2 的 support，
    这样确定性解题器和 LLM 看到的是同一份信息，指标才可比。

用法：
    python3 -m bench.run_eval --model reference --split dev
    python3 -m bench.run_eval --model search --split dev
    python3 -m bench.run_eval --model recorded_llm --model-name deepseek-v4-flash \\
        --raw results/raw/llm_deepseek-v4-flash_holdout.jsonl --split holdout
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from bench.generate import read_jsonl, render_prompt  # noqa: E402
from bench.models import build_adapter  # noqa: E402
from bench.scoring import compute_metrics, parse_answer, round_floats  # noqa: E402

HERE = _HERE


# ---------------------------------------------------------------------------
def load_split(root: str, split: str):
    tasks = read_jsonl(os.path.join(root, "data", "tasks_%s.jsonl" % split))
    keys = {k["item_id"]: k for k in
            read_jsonl(os.path.join(root, "keys", "keys_%s.jsonl" % split))}
    return tasks, keys


def load_keys_any(root: str, name: str) -> Dict[str, Dict[str, Any]]:
    """参考解需要答案；其它适配器永远拿不到它。"""
    p = os.path.join(root, "keys", "keys_%s.jsonl" % name)
    if not os.path.exists(p):
        return {}
    return {k["item_id"]: k for k in read_jsonl(p)}


def build_round2(c_tasks: Sequence[Dict[str, Any]],
                 r1_tasks: Sequence[Dict[str, Any]],
                 r1_preds: Dict[str, Dict[str, Any]],
                 keys: Dict[str, Dict[str, Any]],
                 ) -> List[Dict[str, Any]]:
    """按上面写死的规则构造 Round 2（Phase C）。"""
    first_b: Dict[str, Dict[str, Any]] = {}
    for t in r1_tasks:
        if t["phase"] == "B":
            first_b.setdefault(t["universe_public_id"], t)

    out: List[Dict[str, Any]] = []
    for t in c_tasks:
        b = first_b.get(t["universe_public_id"])
        item = json.loads(json.dumps(t))
        item["round"] = 2
        if b is None:
            item["prompt"] = render_prompt(item)
            out.append(item)
            continue
        gold = keys[b["item_id"]]["answer"]
        pred = r1_preds.get(b["item_id"], {})
        model_ans = pred.get("answer")
        verdict = "CORRECT" if (model_ans is not None
                                and tuple(model_ans) == tuple(gold)) else "WRONG"
        fb = {
            "query": list(b["query"]["input"]),
            "model_answer": list(model_ans) if model_ans else [],
            "correct_answer": list(gold),
            "verdict": verdict,
            "ref_item_id": b["item_id"],
        }
        item["feedback"] = fb
        # 把「查询 → 正确答案」并进 support，保证不同适配器信息等价
        extra = {"input": list(b["query"]["input"]), "output": list(gold)}
        if extra not in item["support"]:
            item["support"] = list(item["support"]) + [extra]
        item["prompt"] = render_prompt(item)
        out.append(item)
    return out


def score_run(tasks: Sequence[Dict[str, Any]],
              preds: Dict[str, Dict[str, Any]],
              keys: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict], Dict]:
    rows: List[Dict[str, Any]] = []
    for t in tasks:
        k = keys.get(t["item_id"])
        if k is None:
            continue
        p = preds.get(t["item_id"], {})
        raw = p.get("raw")
        ans = p.get("answer")
        if ans is None and raw is not None:
            ans = parse_answer(raw)
        parse_ok = ans is not None
        gold = tuple(k["answer"])
        rows.append({
            "item_id": t["item_id"],
            "round": t.get("round", 1),
            "universe_public_id": t["universe_public_id"],
            "phase": t["phase"],
            "difficulty": t["difficulty"],
            "generalization": t["generalization"],
            "gold": list(gold),
            "pred": list(ans) if ans is not None else None,
            "raw": raw,
            "parse_ok": parse_ok,
            "correct": bool(parse_ok and tuple(ans) == gold),
            "confidence": p.get("confidence"),
            "is_copy_input": bool(ans is not None
                                  and tuple(ans) == tuple(t["query"]["input"])),
        })
    return rows, compute_metrics(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ΔR-Bench 评测运行器")
    ap.add_argument("--model", required=True,
                    help="reference|copy_input|frequent_support_output|random|"
                         "search|bounded_search|recorded_llm|openai_compat")
    ap.add_argument("--model-name", default=None)
    ap.add_argument("--raw", default=None, help="recorded_llm 的原始回答文件")
    ap.add_argument("--split", default="dev", choices=["dev", "holdout"])
    ap.add_argument("--set", default="tasks",
                    help="tasks|control_corrupt|perturb")
    ap.add_argument("--root", default=HERE)
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-len", type=int, default=2)
    ap.add_argument("--beam", type=int, default=160)
    # ---- 本地权重推理（--model llamacpp）--------------------------------
    ap.add_argument("--endpoint", default=os.environ.get(
                        "DRBENCH_LLM_ENDPOINT", "http://127.0.0.1:11435/v1"),
                    help="llamacpp 适配器的 OpenAI 兼容端点（llama-server 的 /v1）")
    ap.add_argument("--num-predict", type=int, default=1024,
                    help="llamacpp: 单次生成上限（thinking 模型 1024 以下 content 常为空）")
    ap.add_argument("--thinking", default="off", choices=["on", "off"],
                    help="llamacpp: 是否开启 thinking（默认 off，见测试结果 §2.1）")
    ap.add_argument("--gen-seed", type=int, default=20261031,
                    help="llamacpp: 采样种子（temperature=0 时仍固定，便于复跑）")
    args = ap.parse_args(argv)

    tasks, keys = load_split(args.root, args.split)
    key_source = args.split
    if args.set != "tasks":
        tasks = read_jsonl(os.path.join(
            args.root, "data", "%s_%s.jsonl" % (args.set, args.split)))
        # 控制集/扰动集的 item_id 有前缀，映射回原 key
        tasks = [dict(t, item_id=t["item_id"].split("-", 1)[1],
                      _control=t["item_id"]) for t in tasks]
    if args.limit:
        tasks = tasks[:args.limit]

    # 扰动集的 golden 必须**同步重命名**：perturb 对符号做了整体双射重命名，
    # 因此正确答案也随之改名。早期版本只在评分后做事后映射，而参考解拿到的仍是
    # 未重命名的 key，于是参考解在扰动集上只有 2.4% ——被 A7 审计抓了出来。
    # 正确做法是在评分之前就把 keys 视图换成重命名后的版本，让参考解和评分器
    # 看到同一个世界。
    if args.set == "perturb":
        view = {}
        for t in tasks:
            k = keys.get(t["item_id"])
            if not k:
                continue
            ren = t.get("rename_map") or {}
            view[t["item_id"]] = dict(
                k, answer=[ren.get(x, x) for x in k["answer"]])
        keys = view

    r1 = [t for t in tasks if t["phase"] in ("A", "B")]
    c_tasks = [t for t in tasks if t["phase"] == "C"]

    kw = {"max_len": args.max_len, "beam": args.beam}
    if args.model == "reference":
        kw["keys"] = keys
        adapter = build_adapter("reference", keys)
    elif args.model == "recorded_llm":
        if not args.raw:
            print("ERROR: recorded_llm 需要 --raw 指向真实原始回答文件", file=sys.stderr)
            return 2
        adapter = build_adapter("recorded_llm", keys, model_name=args.model_name,
                                raw_path=args.raw)
    elif args.model == "openai_compat":
        adapter = build_adapter("openai_compat", keys,
                                model_name=args.model_name or "gpt-x")
    elif args.model == "llamacpp":
        if not args.model_name:
            print("ERROR: llamacpp 需要 --model-name（llama-server 的 --alias）",
                  file=sys.stderr)
            return 2
        adapter = build_adapter("llamacpp", keys,
                                model_name=args.model_name,
                                endpoint=args.endpoint,
                                num_predict=args.num_predict,
                                thinking=args.thinking,
                                seed=args.gen_seed)
    else:
        adapter = build_adapter(args.model, keys, **kw)

    print("=" * 70)
    print(" ΔR-Bench 评测")
    print(" 适配器 : %s (%s)" % (adapter.name, adapter.kind))
    print(" split  : %s   题目集: %s" % (args.split, args.set))
    print(" 题量   : Round1=%d  Round2=%d" % (len(r1), len(c_tasks)))
    print(" 前沿模型: %s" % ("是" if adapter.is_frontier_model else "**否**"))
    print("=" * 70)

    t0 = time.time()
    p1 = adapter.solve_batch(r1)

    # 控制集/扰动集没有 Phase C，直接评分
    if not c_tasks:
        rows, metrics = score_run(tasks, p1, keys)
        preds_all = p1
        r2 = []
    else:
        r2 = build_round2(c_tasks, r1, p1, keys)
        p2 = adapter.solve_batch(r2)
        preds_all = dict(p1)
        preds_all.update(p2)
        rows, metrics = score_run(list(r1) + r2, preds_all, keys)
    elapsed = time.time() - t0

    metrics = round_floats(metrics)
    metrics["adapter"] = adapter.name
    metrics["adapter_kind"] = adapter.kind
    metrics["is_frontier_model"] = adapter.is_frontier_model
    metrics["adapter_notes"] = adapter.notes
    # 真实 LLM 适配器：把**调用配置**与**token 统计**写进结果 JSON，
    # 这样「这个分数是在什么协议下拿到的」不必靠人记得。
    if getattr(adapter, "config", None):
        metrics["adapter_config"] = adapter.config
    if getattr(adapter, "stats", None):
        metrics["adapter_stats"] = adapter.stats
    metrics["split"] = args.split
    metrics["task_set"] = args.set
    metrics["n_round1"] = len(r1)
    metrics["n_round2"] = len(r2)
    metrics["elapsed_sec"] = round(elapsed, 1)
    metrics["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    outdir = os.path.join(args.root, "results")
    os.makedirs(outdir, exist_ok=True)
    stem = "%s_%s" % (adapter.name, args.split if args.set == "tasks"
                      else "%s_%s" % (args.set, args.split))
    ppath = os.path.join(outdir, stem + "_predictions.jsonl")
    with open(ppath, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    mpath = os.path.join(outdir, stem + "_scores.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    # 原始回答留痕：任何 LLM 分数都必须有逐题原始输出，否则不予采信
    if adapter.kind == "llm":
        rawdir = os.path.join(outdir, "raw")
        os.makedirs(rawdir, exist_ok=True)
        rpath = os.path.join(rawdir, "%s_%s.jsonl" % (adapter.name, args.split))
        with open(rpath, "w", encoding="utf-8") as f:
            for t in list(r1) + list(r2):
                p = preds_all.get(t["item_id"], {})
                row = {
                    "item_id": t["item_id"],
                    "round": t.get("round", 1),
                    "model": adapter.name,
                    "raw": p.get("raw"),
                    "confidence": p.get("confidence"),
                    "run_at": metrics["generated_at"],
                }
                # 真实推理的留痕字段（thinking 模型的 CoT、token 计数、重试次数…）
                # 只在适配器确实产出了这些字段时才写，避免给离线重放凭添噪声。
                for k in ("answer", "thinking", "usage", "finish_reason",
                          "attempts", "repairs", "latency_ms", "error"):
                    if p.get(k) is not None:
                        row[k] = (list(p[k]) if isinstance(p[k], tuple) else p[k])
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print("\n结果：")
    for k in ("n", "accuracy", "parse_failure_rate",
              "acc_phase_A", "acc_phase_B", "acc_phase_C",
              "LearningGain_B_minus_A", "FeedbackGain_C_minus_B",
              "acc_easy", "acc_medium", "acc_hard",
              "acc_id", "acc_ood", "GeneralizationGap_id_minus_ood",
              "RevisionRate_C_given_B", "OvercorrectionRate",
              "copy_input_rate", "ECE", "confidence_gap"):
        if k in metrics:
            print("  %-32s %s" % (k, metrics[k]))
    print("\n  明细 : %s" % ppath)
    print("  分数 : %s" % mpath)
    print("  耗时 : %.1fs" % elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
