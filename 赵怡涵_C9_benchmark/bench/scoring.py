#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ΔR-Bench 评分与指标

两条设计原则：

  1. **解析失败 ≠ 推理失败。**
     模型输出 `[ze, mi, mi]`、`ze mi mi`、`  ZE MI MI `、`ze,mi,mi` 是同一件事。
     评分前先做规范化；规范化失败（比如模型答了一段解释）单独计入
     `parse_failure_rate`，绝不混进正确率里——否则「格式不合规」会被当成
     「能力不行」，这是 LLM 评测里最常见的效度污染源之一。

  2. **每个指标都要有可证伪的解释。**
     LearningGain / FeedbackGain / RevisionRate 这些差值的意义，取决于它们能不能
     被一个「什么都不学」的基线打平。所以评分永远和基线一起报（见 run_eval）。

只依赖标准库。
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

Seq = Tuple[str, ...]

_NONE_WORDS = {"none", "empty", "nil", "null", "无", "(empty)", "<empty>", "-"}

# 允许出现在输出里的装饰性字符
_STRIP_CHARS = "[](){}\"'`,;:."


def parse_answer(raw: Any) -> Optional[Seq]:
    """把模型的自由文本解析成符号序列。解析不出来返回 None。"""
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        toks = [str(x).strip().lower() for x in raw if str(x).strip()]
        return tuple(t for t in toks if t)

    s = str(raw).strip()
    if not s:
        return ()

    # 有些模型会返回 JSON 数组
    if s.startswith("[") and s.endswith("]"):
        try:
            val = json.loads(s)
            if isinstance(val, list):
                return tuple(str(x).strip().lower() for x in val if str(x).strip())
        except Exception:
            pass

    # 去掉常见包装：Answer: xxx / = xxx / 反引号
    s = re.sub(r"^\s*(answer|output|答案|结果)\s*[:：=]\s*", "", s, flags=re.I)
    s = s.strip().strip("`").strip()
    # 只取第一行（模型常常多写一句解释）
    s = s.splitlines()[0] if s else s

    s = s.strip().strip(_STRIP_CHARS)
    if not s:
        return ()
    low = s.lower().strip()
    if low in _NONE_WORDS:
        return ()

    toks = [t for t in re.split(r"[\s,;|]+", s) if t]
    toks = [t.strip(_STRIP_CHARS).lower() for t in toks]
    toks = [t for t in toks if t]
    if not toks:
        return ()
    # 规范化后每个 token 必须是纯字母数字（符号表就是自造双字母音节）。
    # 只要有一个 token 不是，就说明模型答的不是序列，判为解析失败。
    for t in toks:
        if not re.fullmatch(r"[a-z0-9]+", t):
            return None
    return tuple(toks)


def exact_match(pred: Optional[Seq], gold: Sequence[str]) -> bool:
    return pred is not None and tuple(pred) == tuple(gold)


def parse_confidence(raw: Any) -> Optional[float]:
    """从模型输出里抠出一个 [0,1] 的确信度。找不到返回 None。"""
    if isinstance(raw, dict):
        for k in ("confidence", "conf", "p"):
            if k in raw:
                try:
                    v = float(raw[k])
                    return v if 0.0 <= v <= 1.0 else (v / 100.0 if 0 <= v <= 100 else None)
                except Exception:
                    return None
        return None
    if raw is None:
        return None
    m = re.search(r"(?:confidence|conf|确信度|置信度)\s*[:：=]?\s*([0-9]*\.?[0-9]+)\s*%?",
                  str(raw), flags=re.I)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except Exception:
        return None
    if "%" in m.group(0):
        v = v / 100.0
    elif v > 1.0:
        v = v / 100.0
    return v if 0.0 <= v <= 1.0 else None


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------
def _acc(rows: Sequence[Dict[str, Any]]) -> Optional[float]:
    if not rows:
        return None
    return sum(1 for r in rows if r["correct"]) / float(len(rows))


def expected_calibration_error(pairs: Sequence[Tuple[float, int]],
                               n_bins: int = 10) -> Optional[float]:
    """ECE = Σ (n_b/N) · |acc(b) − conf(b)|（Guo et al., ICML 2017）。"""
    if not pairs:
        return None
    bins: List[List[Tuple[float, int]]] = [[] for _ in range(n_bins)]
    for conf, hit in pairs:
        idx = min(n_bins - 1, max(0, int(conf * n_bins)))
        bins[idx].append((conf, hit))
    n = float(len(pairs))
    ece = 0.0
    for b in bins:
        if not b:
            continue
        acc = sum(h for _, h in b) / float(len(b))
        conf = sum(c for c, _ in b) / float(len(b))
        ece += (len(b) / n) * abs(acc - conf)
    return ece


def compute_metrics(preds: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """preds: [{item_id, phase, difficulty, generalization, correct,
                parse_ok, confidence, gold, pred}, ...]"""
    out: Dict[str, Any] = {}
    n = len(preds)
    if n == 0:
        return {"n": 0}

    out["n"] = n
    out["accuracy"] = _acc(preds)
    out["parse_failure_rate"] = (
        sum(1 for r in preds if not r["parse_ok"]) / float(n))
    out["copy_input_rate"] = sum(
        1 for r in preds if r.get("is_copy_input")) / float(n)

    for ph in ("A", "B", "C"):
        sub = [r for r in preds if r["phase"] == ph]
        out["acc_phase_%s" % ph] = _acc(sub)
        out["n_phase_%s" % ph] = len(sub)
        out["copy_input_rate_phase_%s" % ph] = (
            sum(1 for r in sub if r.get("is_copy_input")) / float(len(sub))
            if sub else None)

    for d in ("easy", "medium", "hard"):
        sub = [r for r in preds if r["difficulty"] == d]
        out["acc_%s" % d] = _acc(sub)
        out["n_%s" % d] = len(sub)

    a = out.get("acc_phase_A")
    b = out.get("acc_phase_B")
    c = out.get("acc_phase_C")
    out["LearningGain_B_minus_A"] = (b - a) if (a is not None and b is not None) else None
    out["FeedbackGain_C_minus_B"] = (c - b) if (b is not None and c is not None) else None

    # ID / OOD 的整体口径
    idr = [r for r in preds if r["generalization"] == "id"]
    ood = [r for r in preds if r["generalization"] == "ood"]
    out["acc_id"] = _acc(idr)
    out["acc_ood"] = _acc(ood)
    out["n_id"] = len(idr)
    out["n_ood"] = len(ood)
    out["GeneralizationGap_all"] = ((out["acc_id"] - out["acc_ood"])
                                    if (idr and ood) else None)

    # **分阶段**的 ID / OOD —— 这才是可解释的口径。
    # 为什么必须分阶段：Phase A 完全不提供示例，那些题**不可能是"学会了但没外推"**，
    # 只可能是"没东西可学所以没得分"。把它们算进 OOD 分母，会让泛化差距里混进
    # 与泛化无关的成分（实测：不分阶段时差距 0.593，分到 Phase B 后是 0.60，
    # 但换一个 Phase A 抄对率更高的模型，两者的差别会非常大）。
    # 泛化差距是有意义的，只有在"本来有可能学会"的条件下才成立。
    for ph in ("B", "C"):
        idr_p = [r for r in preds
                 if r["generalization"] == "id" and r["phase"] == ph]
        ood_p = [r for r in preds
                 if r["generalization"] == "ood" and r["phase"] == ph]
        out["acc_id_%s" % ph] = _acc(idr_p)
        out["acc_ood_%s" % ph] = _acc(ood_p)
        out["n_id_%s" % ph] = len(idr_p)
        out["n_ood_%s" % ph] = len(ood_p)
        out["GeneralizationGap_%s" % ph] = (
            (out["acc_id_%s" % ph] - out["acc_ood_%s" % ph])
            if (idr_p and ood_p) else None)
    # 主口径：Phase B 上的泛化差距（有示例、且尚未接受反馈）
    out["GeneralizationGap_id_minus_ood"] = out["GeneralizationGap_B"]

    # ---- 修正率：ΔR 有没有真的回流去更新 K --------------------------------
    # 以每个宇宙为单位，把 Phase B 的对错与 Phase C 的对错配对比较是有偏的
    # （B/C 是不同题目）。这里退一步用可计算的口径：C 阶段里那些「反馈里给出的
    # 正是同类错误」的题目上的正确率，与 B 阶段整体正确率对比，并在文档里说明
    # 这个口径的边界。
    out["RevisionRate_C_given_B"] = None
    out["OvercorrectionRate"] = None
    by_u: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for r in preds:
        by_u.setdefault(r["universe_public_id"], {}).setdefault(
            r["phase"], []).append(r)
    rev_hits, rev_tot, over_hits, over_tot = 0, 0, 0, 0
    for u, d in by_u.items():
        bs = d.get("B", [])
        cs = d.get("C", [])
        if not bs or not cs:
            continue
        b_acc = sum(1 for r in bs if r["correct"]) / float(len(bs))
        c_acc = sum(1 for r in cs if r["correct"]) / float(len(cs))
        if b_acc < 1.0:
            rev_hits += sum(1 for r in cs if r["correct"])
            rev_tot += len(cs)
        if b_acc > 0.0:
            over_hits += sum(1 for r in cs if not r["correct"])
            over_tot += len(cs)
    out["RevisionRate_C_given_B"] = (rev_hits / rev_tot) if rev_tot else None
    out["OvercorrectionRate"] = (over_hits / over_tot) if over_tot else None

    pairs = [(r["confidence"], 1 if r["correct"] else 0)
             for r in preds if r.get("confidence") is not None]
    out["n_with_confidence"] = len(pairs)
    out["ECE"] = expected_calibration_error(pairs)
    if pairs:
        out["mean_confidence"] = sum(c for c, _ in pairs) / float(len(pairs))
        out["confidence_gap"] = out["mean_confidence"] - out["accuracy"]
    else:
        out["mean_confidence"] = None
        out["confidence_gap"] = None
    return out


def round_floats(d: Dict[str, Any], nd: int = 4) -> Dict[str, Any]:
    out = {}
    for k, v in d.items():
        out[k] = round(v, nd) if isinstance(v, float) else v
    return out


__all__ = [
    "parse_answer", "exact_match", "parse_confidence",
    "expected_calibration_error", "compute_metrics", "round_floats",
]
