#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ΔR-Bench 规则引擎（rule engine）

本模块定义「规则宇宙」（rule universe）：一套程序化生成的、可由少量示例归纳出来的
符号序列变换规则。它是整个 benchmark 的语义内核——生成器、参考解、假设搜索器、
自检脚本全部复用这里的同一份实现，保证「题目」与「答案」出自同一语义。

设计约束（对应 docs/设计说明 与 拿来说明）：
  1. **可程序化生成**：任何种子都能产出一个全新的规则宇宙，且答案不依赖任何语料。
  2. **可精确评分**：输出是离散符号序列，判分是精确匹配，不需要人工或模型评审。
  3. **可声明假设空间**：所有规则都由有限的原语组合而成，因此「这题是否可被唯一
     归纳」可以被机械判定（见 hypothesis.py 的 identifiability 检查）。

本文件只依赖标准库。
"""

from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# 符号表：刻意使用「自造双字母音节」而不是 emoji / 常见英文单词
#   - 自造音节在自然语料中几乎不出现 → 降低预训练记忆带来的先验
#   - 纯 ASCII → Kaggle / CSV / 终端 / 各种 API 都能无损传输
# ---------------------------------------------------------------------------
SYMBOL_POOL: Tuple[str, ...] = (
    "ka", "ro", "mi", "tu", "ve", "sa", "lo", "ni",
    "pa", "du", "ze", "qi", "fu", "go", "ha", "ji",
)

Seq = Tuple[str, ...]

# ---------------------------------------------------------------------------
# 原语（primitive）
# ---------------------------------------------------------------------------
# 一条原语是一个「序列 → 序列」的纯函数，并且可以被序列化成可读文本。
#
#   ("sub",  a, b)        把所有 a 换成 b
#   ("del",  a)           删掉所有 a
#   ("dup",  a)           把每个 a 复制一份（就地展开）
#   ("rev",)              反转序列
#   ("rot",  k)           左旋 k 位
#   ("swap", a, b)        交换 a 与 b 的全部出现
#   ("cond", pred, inner) 仅当 pred 成立时施加 inner，否则原样返回
#
# 谓词（predicate）：
#   ("contains", a)       序列中含 a
#   ("count_ge", a, n)    a 的出现次数 >= n
#   ("len_ge",  n)        序列长度 >= n
#   ("first_is", a)       首符号是 a

PRED_KINDS = ("contains", "count_ge", "len_ge", "first_is")


def apply_primitive(seq: Seq, prim: Tuple) -> Seq:
    """施加一条原语。"""
    kind = prim[0]

    if kind == "sub":
        a, b = prim[1], prim[2]
        return tuple(b if x == a else x for x in seq)

    if kind == "del":
        a = prim[1]
        return tuple(x for x in seq if x != a)

    if kind == "dup":
        a = prim[1]
        out: List[str] = []
        for x in seq:
            out.append(x)
            if x == a:
                out.append(x)
        return tuple(out)

    if kind == "rev":
        return tuple(reversed(seq))

    if kind == "rot":
        k = prim[1]
        if not seq:
            return seq
        k = k % len(seq)
        return tuple(seq[k:] + seq[:k])

    if kind == "swap":
        a, b = prim[1], prim[2]
        return tuple(b if x == a else (a if x == b else x) for x in seq)

    if kind == "cond":
        pred, inner = prim[1], prim[2]
        if eval_predicate(seq, pred):
            return apply_primitive(seq, inner)
        return seq

    raise ValueError("unknown primitive: %r" % (prim,))


def eval_predicate(seq: Seq, pred: Tuple) -> bool:
    kind = pred[0]
    if kind == "contains":
        return pred[1] in seq
    if kind == "count_ge":
        return seq.count(pred[1]) >= pred[2]
    if kind == "len_ge":
        return len(seq) >= pred[1]
    if kind == "first_is":
        return len(seq) > 0 and seq[0] == pred[1]
    raise ValueError("unknown predicate: %r" % (pred,))


def apply_rule(seq: Seq, rule: Sequence[Tuple]) -> Seq:
    """按顺序施加一条规则链。"""
    out = tuple(seq)
    for prim in rule:
        out = apply_primitive(out, prim)
    return out


# ---------------------------------------------------------------------------
# 规则的序列化 / 可读化
# ---------------------------------------------------------------------------
def predicate_text(pred: Tuple) -> str:
    kind = pred[0]
    if kind == "contains":
        return "%s ∈ seq" % pred[1]
    if kind == "count_ge":
        return "count(%s) ≥ %d" % (pred[1], pred[2])
    if kind == "len_ge":
        return "len(seq) ≥ %d" % pred[1]
    if kind == "first_is":
        return "head(seq) = %s" % pred[1]
    return "?"


def primitive_text(prim: Tuple) -> str:
    kind = prim[0]
    if kind == "sub":
        return "sub(%s→%s)" % (prim[1], prim[2])
    if kind == "del":
        return "del(%s)" % prim[1]
    if kind == "dup":
        return "dup(%s)" % prim[1]
    if kind == "rev":
        return "reverse()"
    if kind == "rot":
        return "rotate_left(%d)" % prim[1]
    if kind == "swap":
        return "swap(%s↔%s)" % (prim[1], prim[2])
    if kind == "cond":
        return "if[%s]{ %s }" % (predicate_text(prim[1]), primitive_text(prim[2]))
    return "?"


def rule_text(rule: Sequence[Tuple]) -> str:
    return " ; ".join(primitive_text(p) for p in rule)


def rule_fingerprint(rule: Sequence[Tuple]) -> str:
    """稳定指纹，用于「同一规则」的去重与统计。"""
    return "|".join(primitive_text(p) for p in rule)


# ---------------------------------------------------------------------------
# 规则宇宙（universe）生成
# ---------------------------------------------------------------------------
class Universe(object):
    """一个规则宇宙 = 一套符号表 + 一条规则链。"""

    __slots__ = ("uid", "seed", "alphabet", "rule", "complexity", "attempt")

    def __init__(self, uid: str, seed: int, alphabet: Sequence[str],
                 rule: Sequence[Tuple], complexity: int, attempt: int = 0):
        self.uid = uid
        self.seed = seed
        self.alphabet = tuple(alphabet)
        self.rule = tuple(rule)
        self.complexity = complexity
        self.attempt = attempt

    # -- 行为 ---------------------------------------------------------------
    def run(self, seq: Seq) -> Seq:
        return apply_rule(seq, self.rule)

    def describe(self) -> str:
        return rule_text(self.rule)

    def to_json(self) -> Dict[str, Any]:
        return {
            "uid": self.uid,
            "seed": self.seed,
            "alphabet": list(self.alphabet),
            "complexity": self.complexity,
            "attempt": self.attempt,
            "rule_text": self.describe(),
            "rule_fingerprint": rule_fingerprint(self.rule),
        }


# ---- 原语构造 -------------------------------------------------------------

def referenced_symbols(rule: Sequence[Tuple]) -> List[str]:
    """规则里被引用到的全部符号（用于保证示例覆盖这些符号）。"""
    out = []

    def walk(p):
        k = p[0]
        if k in ("sub", "swap"):
            out.extend([p[1], p[2]])
        elif k in ("del", "dup"):
            out.append(p[1])
        elif k == "cond":
            pred, inner = p[1], p[2]
            if pred[0] in ("contains", "first_is"):
                out.append(pred[1])
            elif pred[0] == "count_ge":
                out.append(pred[1])
            walk(inner)

    for prim in rule:
        walk(prim)
    seen, res = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            res.append(x)
    return sorted(res)


def _make_predicates(alphabet: Sequence[str], rng: random.Random) -> List[Tuple]:
    preds: List[Tuple] = [("contains", a) for a in alphabet]
    preds += [("len_ge", n) for n in (3, 4, 5)]
    preds += [("first_is", a) for a in alphabet]
    preds += [("count_ge", a, n) for a in alphabet for n in (2, 3)]
    return preds


def _make_simple_primitives(alphabet: Sequence[str]) -> List[Tuple]:
    """不带 cond 的原语集合（cond 的 inner 也从这里取，保证嵌套深度 ≤ 1）。"""
    prims: List[Tuple] = []
    for a in alphabet:
        prims.append(("del", a))
        prims.append(("dup", a))
        for b in alphabet:
            if a != b:
                prims.append(("sub", a, b))
    for i in range(len(alphabet)):
        for j in range(i + 1, len(alphabet)):
            prims.append(("swap", alphabet[i], alphabet[j]))
    prims.append(("rev",))
    if len(alphabet) >= 3:
        prims.append(("rot", 1))
        prims.append(("rot", 2))
    return prims


def simple_primitives(alphabet: Sequence[str]) -> List[Tuple]:
    """不含 cond 的原语（公开给 support.py 与 hypothesis.py 复用）。"""
    return _make_simple_primitives(alphabet)


def predicate_space(alphabet: Sequence[str]) -> List[Tuple]:
    """声明的全部条件谓词。"""
    return _make_predicates(alphabet, random.Random(0))


def build_hypothesis_space(alphabet: Sequence[str],
                           allow_cond: bool = True) -> List[Tuple]:
    """声明式假设空间：一条规则链里的每个位置可以取哪些原语。

    这个空间就是我们在文档里承诺的「可声明假设空间」。它的规模刻意保持在
    「一个认真的解题者用手算也能枚举」的量级——这既让「题目是否唯一可归纳」
    可以机械判定，也让 bounded solver 可以作为人类难度的代理。
    """
    simple = _make_simple_primitives(alphabet)
    space = list(simple)
    if allow_cond:
        for pred in _make_predicates(alphabet, random.Random(0)):
            for inner in simple:
                # 条件规则套自身会造成无限递归语义，故 inner 只允许简单原语
                if inner[0] == "cond":
                    continue
                space.append(("cond", pred, inner))
    return space


# ---- 复杂度分层 -----------------------------------------------------------
# 1 条 = easy，2 条 = medium，3 条 = hard
# (难度标签, 规则链长度, 是否强制含条件, 字母表大小, 该难度下的宇宙个数)
#
# ⚠️ 这张表是**被可归纳性检查改过**的，改动本身有证据（见 docs/可归纳性试点.md）：
#    原设计把 hard 定为「3 条原语组合」。实测：8 个对抗性示例（query-by-committee
#    挑出来的）下，3 原语规则在探针集上仍有 9~11 个行为等价类——标准答案不唯一。
#    加到 10~15 个示例、单宇宙 30~60 秒搜索后仍有约 1/5 的宇宙不可判别。
#    这不是调参问题，是数学问题：3 原语链的空间是 |space|³ ≈ 10⁹ 量级，
#    十几个短示例提供的约束远不足以把等价类压到 1。
#    结论：**基准声明的规则长度上限降为 2**，难度改由「是否含条件分支 + 字母表大小 +
#    序列长度 + OOD 组合新异题占比」来拉开。这样每题都可证明是良定义的。
COMPLEXITY_PLAN = (
    ("easy",   1, False, 5, 4),
    ("medium", 2, False, 6, 5),
    ("hard",   2, True,  6, 3),
)


def _random_rule(alphabet: Sequence[str], length: int, rng: random.Random,
                 require_cond: bool = False) -> List[Tuple]:
    simple = _make_simple_primitives(alphabet)
    rule: List[Tuple] = []
    for i in range(length):
        use_cond = (rng.random() < 0.30) or (require_cond and i == length - 1)
        if use_cond:
            pred = rng.choice(_make_predicates(alphabet, rng))
            inner = rng.choice(simple)
            rule.append(("cond", pred, inner))
        else:
            rule.append(rng.choice(simple))
    if require_cond and not any(p[0] == "cond" for p in rule):
        pred = rng.choice(_make_predicates(alphabet, rng))
        rule[-1] = ("cond", pred, rng.choice(simple))
    return rule


def make_universe(uid: str, seed: int, complexity: int,
                  attempt: int = 0,
                  alphabet_size: Optional[int] = None,
                  require_cond: bool = False,
                  max_len: int = 6) -> Universe:
    """由种子确定性地造一个规则宇宙。"""
    rng = random.Random(seed)
    k = alphabet_size if alphabet_size is not None else rng.randint(5, 6)
    alphabet = tuple(sorted(rng.sample(SYMBOL_POOL, k)))
    rule = _random_rule(alphabet, complexity, rng, require_cond=require_cond)
    return Universe(uid, seed, alphabet, rule, complexity, attempt)


def sample_inputs(universe: Universe, n: int, rng: random.Random,
                  min_len: int = 3, max_len: int = 6) -> List[Seq]:
    """造 n 个互不相同的输入序列。"""
    seen = set()
    out: List[Seq] = []
    guard = 0
    while len(out) < n and guard < n * 400:
        guard += 1
        L = rng.randint(min_len, max_len)
        seq = tuple(rng.choice(universe.alphabet) for _ in range(L))
        if seq in seen:
            continue
        seen.add(seq)
        out.append(seq)
    return out


def is_degenerate(universe: Universe, probes: Sequence[Seq]) -> bool:
    """太「退化的」规则宇宙不适合出题：

    - 规则在多数输入上是恒等（答案 = 输入）→ 抄输入就能得高分
    - 输出长度爆炸（dup 叠加）→ 提示词过长
    - 输出恒为空 → 答案退化
    """
    identity = 0
    for seq in probes:
        out = universe.run(seq)
        if out == seq:
            identity += 1
        if len(out) > 24:
            return True
        if len(out) == 0:
            return True
    return identity * 2 > len(probes)


__all__ = [
    "parse_rule_text", "parse_primitive_text", "parse_predicate_text",
    "SYMBOL_POOL", "Seq", "apply_primitive", "eval_predicate", "apply_rule",
    "predicate_text", "primitive_text", "rule_text", "rule_fingerprint",
    "Universe", "build_hypothesis_space", "simple_primitives",
    "predicate_space", "make_universe", "sample_inputs",
    "is_degenerate", "COMPLEXITY_PLAN", "referenced_symbols",
]

# ---------------------------------------------------------------------------
# 规则文本 → 规则结构（反向解析）
# ---------------------------------------------------------------------------
# 存在的理由：答案 key 里存的是人可读的 rule_text。如果只能靠「相信它」，
# 那答案就是不可核验的。有了反向解析，自检脚本可以独立地把 rule_text 变回
# 规则结构、重新施加到查询上，再和答案比——整条链路可机械核验，不需要信任。
_PRED_PATTERNS = (
    (re.compile(r"^(.+) ∈ seq$"), lambda m: ("contains", m.group(1))),
    (re.compile(r"^count\((.+)\) ≥ (\d+)$"),
     lambda m: ("count_ge", m.group(1), int(m.group(2)))),
    (re.compile(r"^len\(seq\) ≥ (\d+)$"), lambda m: ("len_ge", int(m.group(1)))),
    (re.compile(r"^head\(seq\) = (.+)$"), lambda m: ("first_is", m.group(1))),
)


def parse_predicate_text(t: str) -> Tuple:
    for pat, fn in _PRED_PATTERNS:
        m = pat.match(t.strip())
        if m:
            return fn(m)
    raise ValueError("cannot parse predicate: %r" % t)


def parse_primitive_text(t: str) -> Tuple:
    t = t.strip()
    m = re.match(r"^if\[(.+)\]\{\s*(.+?)\s*\}$", t)
    if m:
        return ("cond", parse_predicate_text(m.group(1)),
                parse_primitive_text(m.group(2)))
    m = re.match(r"^sub\((.+?)→(.+?)\)$", t)
    if m:
        return ("sub", m.group(1), m.group(2))
    m = re.match(r"^del\((.+)\)$", t)
    if m:
        return ("del", m.group(1))
    m = re.match(r"^dup\((.+)\)$", t)
    if m:
        return ("dup", m.group(1))
    m = re.match(r"^swap\((.+?)↔(.+?)\)$", t)
    if m:
        return ("swap", m.group(1), m.group(2))
    if t == "reverse()":
        return ("rev",)
    m = re.match(r"^rotate_left\((\d+)\)$", t)
    if m:
        return ("rot", int(m.group(1)))
    raise ValueError("cannot parse primitive: %r" % t)


def parse_rule_text(text: str) -> Tuple[Tuple, ...]:
    """把 rule_text 反向解析回规则结构。用于答案 key 的独立核验。"""
    text = text.strip()
    if not text:
        return tuple()
    return tuple(parse_primitive_text(p) for p in text.split(" ; "))

