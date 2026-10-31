#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ΔR-Bench 假设搜索 / 可归纳性判定

本模块回答 benchmark 设计里最容易被糊弄过去、却最要紧的一个问题：

    **这道题真的能被唯一归纳出来吗？**

如果一组示例同时被多条互不等价的规则满足，那么「标准答案」就只是出题人的偏好，
拿它去判模型的对错是不公平的——被扣分的是歧义，不是能力。

本模块做了三件事：

  1. `restrict_space`   —— 把声明的假设空间按「在示例上的行为」裁剪：
     在示例上恒等的原语等价于什么都不做，可直接丢掉。这是**行为等价意义下**的
     无损压缩（对一致性搜索无损），把 |space| 从约 1700 压到几百。
  2. `enumerate_consistent` —— 逐层 beam search，找出与示例一致的全部候选规则。
     候选以「规则链 + 在示例上的输出」增量扩展，避免重复施加整条链。
  3. `ambiguity_report` —— 统计候选在**探针集**上的行为等价类数。
     等价类 = 1 才叫可唯一归纳。beam 宽度是结论的边界条件，会写进报告。

同一个搜索器还兼任两个角色（刻意的复用）：
  - 受限预算 → 作为**人类难度的代理**（明确标注为模拟，非人类数据）
  - 充足预算 → 作为**非 LLM 的强基线**

只依赖标准库。
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .rules import (
    Seq,
    apply_primitive,
    referenced_symbols,
    apply_rule,
    build_hypothesis_space,
    predicate_space,
    rule_fingerprint,
    rule_text,
    simple_primitives,
)

Rule = Tuple[Tuple, ...]
Outs = Tuple[Seq, ...]


# ---------------------------------------------------------------------------
# 1. 行为裁剪
# ---------------------------------------------------------------------------
def restrict_space(alphabet: Sequence[str],
                   support_inputs: Sequence[Seq],
                   ) -> Tuple[List[Tuple], Dict[str, int]]:
    """按「在示例上的行为」裁剪假设空间。

    裁剪规则（都是行为等价意义下的，对一致性搜索无损）：

      * 在**全部**示例输入上都等于恒等的原语直接丢掉
        —— 例如示例里根本没出现过的符号 x，则 sub(x→y)、del(x)、dup(x) 都是恒等；
        —— 恒定不成立的条件谓词（如 len(seq) ≥ 5 而示例都短于 5）也使其成为恒等。
      * 恒定成立的条件 `if[P]{X}` 行为上就是 X，而 X 本身已在空间里，故也丢掉。

    副作用（**要写进文档的边界条件**）：如果真规则里含有「在示例上恒等、在查询上
    非恒等」的原语，那么查询的答案在逻辑上就不可能由示例确定 —— 这类宇宙会被
    歧义检查正确拒绝，而不是被误判为难题。
    """
    ins = list(support_inputs)
    space = build_hypothesis_space(alphabet, allow_cond=True)

    identity = tuple(ins)
    kept: List[Tuple] = []
    for prim in space:
        outs = tuple(apply_primitive(i, prim) for i in ins)
        if outs == identity:
            continue
        kept.append(prim)

    return kept, {"space_full": len(space), "space_restricted": len(kept)}


# ---------------------------------------------------------------------------
# 2. 逐层 beam search
# ---------------------------------------------------------------------------
def _proximity(outs: Outs, targets: Outs) -> int:
    """候选与目标的粗糙贴近度，用于 beam 打分（越大越好）。"""
    s = 0
    for got, want in zip(outs, targets):
        if got == want:
            s += 4
        else:
            s += sum(1 for x, y in zip(got, want) if x == y)
            s -= abs(len(got) - len(want))
    return s


def enumerate_consistent(alphabet: Sequence[str],
                         examples: Sequence[Tuple[Seq, Seq]],
                         max_len: int = 3,
                         beam: int = 96,
                         allow_cond: bool = True,
                         max_results: int = 900,
                         restrict: bool = True) -> List[Rule]:
    """找出长度 ≤ max_len 且与 examples 一致的候选规则。

    实现要点（都是为了让 beam 能开到足够宽，否则「可归纳」的结论不可信）：

      * **整数索引表示**：候选规则在搜索内部用「原语下标元组」表示，去重与排序
        都在整数元组上做。早期版本对每个候选调用 rule_fingerprint（拼字符串），
        在 10⁵ 量级的候选上是主要开销；换成整数元组后单宇宙从十几秒降到几秒。
      * **增量施加**：候选携带「在示例上的输出向量」，扩展一条原语只需对输出向量
        施加一次，而不是重放整条链。
      * **贴近度缓存**：beam 排序用的 proximity 只算一次。

    返回的候选按（长度，指纹）排序。beam 截断发生在每一层，因此结果集合是
    「beam 可达」的子集，不是完整解集——beam 宽度必须写进报告，它是结论的边界。
    """
    ins = tuple(tuple(i) for i, _ in examples)
    targets = tuple(tuple(o) for _, o in examples)

    if restrict:
        space, _ = restrict_space(alphabet, ins)
    else:
        space = (build_hypothesis_space(alphabet, allow_cond=True)
                 if allow_cond else simple_primitives(alphabet))

    def to_rule(idxs) -> Rule:
        return tuple(space[i] for i in idxs)

    survivor_idx: List[Tuple[int, ...]] = []
    seen = set()

    identity_outs: Outs = ins
    if identity_outs == targets:
        survivor_idx.append(tuple())
        seen.add(tuple())
        if max_len == 0:
            return [tuple()]

    # frontier: [(idxs, outs, proximity)]
    frontier: List[Tuple[Tuple[int, ...], Outs, int]] = [
        (tuple(), identity_outs, _proximity(identity_outs, targets))]

    for _depth in range(1, max_len + 1):
        table: Dict[Tuple[int, ...], Tuple[Outs, int]] = {}
        for idxs, outs, _score in frontier:
            for i, prim in enumerate(space):
                cand = idxs + (i,)
                if cand in table or cand in seen:
                    continue
                nouts = tuple(apply_primitive(o, prim) for o in outs)
                table[cand] = (nouts, _proximity(nouts, targets))

        for cand, (outs, _sc) in table.items():
            if outs == targets:
                survivor_idx.append(cand)
                seen.add(cand)

        if len(survivor_idx) >= max_results:
            break

        items = sorted(table.items(),
                       key=lambda kv: (-kv[1][1], len(kv[0]), kv[0]))
        frontier = [(k, v[0], v[1]) for k, v in items[:beam]]
        if not frontier:
            break

    rules = [to_rule(i) for i in survivor_idx]
    rules.sort(key=lambda r: (len(r), rule_fingerprint(r)))
    return rules[:max_results]


# ---------------------------------------------------------------------------
# 3. 行为等价 / 歧义度
# ---------------------------------------------------------------------------
def behavior_signature(rule: Sequence[Tuple], probes: Sequence[Seq]) -> Tuple[Seq, ...]:
    """规则在探针集上的行为签名。签名相同 = 在探针集上不可区分。"""
    return tuple(apply_rule(p, rule) for p in probes)


def ambiguity_report(truth: Sequence[Tuple],
                     alphabet: Sequence[str],
                     examples: Sequence[Tuple[Seq, Seq]],
                     probes: Sequence[Seq],
                     max_len: int = 3,
                     beam: int = 96,
                     allow_cond: bool = True,
                     max_candidates: int = 900) -> Dict[str, Any]:
    """判定「这组示例能否唯一确定真规则」。

      n_candidates   与示例一致的候选规则数（截断到 max_candidates）
      n_equivalence  这些候选在探针集上的行为等价类数
      identifiable   n_equivalence == 1
      truth_in_space beam 是否够宽、把真规则本身找到了（不够宽则结论不可信）
      rivals         与真规则不等价的候选（最多列 5 条），供人工复核
      space_stats    裁剪前后的空间规模
    """
    ins = tuple(tuple(i) for i, _ in examples)
    _, space_stats = restrict_space(alphabet, ins)

    cands = enumerate_consistent(
        alphabet, examples, max_len=max_len, beam=beam,
        allow_cond=allow_cond, max_results=max_candidates,
    )
    truth_sig = behavior_signature(truth, probes)

    sigs: Dict[Tuple[Seq, ...], Rule] = {}
    rivals: List[str] = []
    for c in cands:
        sig = behavior_signature(c, probes)
        if sig not in sigs:
            sigs[sig] = c
        if sig != truth_sig and len(rivals) < 5:
            rivals.append(rule_text(c))

    return {
        "n_candidates": len(cands),
        "n_equivalence": len(sigs),
        "identifiable": len(sigs) == 1,
        "rivals": rivals,
        "truth_in_space": truth_sig in sigs,
        "beam": beam,
        "max_len": max_len,
        "space_stats": space_stats,
        "candidates": cands,
    }


# ---------------------------------------------------------------------------
# 4. 一步对抗委员会 + 贪心示例选择
# ---------------------------------------------------------------------------
def one_step_committee(alphabet: Sequence[str]) -> List[Rule]:
    """「最容易被误认成真规则」的那批假设：恒等 + 全部单原语 + 全部「条件包单原语」。

    经验观察：让题目变含糊的，几乎总是「把真规则多包一层条件」这类只差一个原语的
    邻居，而不是隔了三层的远亲。原因很直接——

        if[count(a) ≥ 3]{ X }   与   X

    在「所有示例里 a 都出现 ≥3 次」的示例集上完全一致。出题人若偷懒，示例全是同一
    长度、同一符号构成，那这道题的标准答案就只是出题人的偏好。

    规模约 1 + 60 + 27×60 ≈ 1700，毫秒级可枚举，代价极低而收益很大。
    """
    simple = simple_primitives(alphabet)
    preds = predicate_space(alphabet)
    comm: List[Rule] = [tuple()]
    comm.extend((p,) for p in simple)
    comm.extend((("cond", pred, inner),) for pred in preds for inner in simple)
    return comm


def select_support(universe, pool: Sequence[Seq], k: int,
                   n_candidates: int = 40) -> List[Tuple[Seq, Seq]]:
    """先保证符号覆盖，再贪心挑示例使「一步委员会」被消灭得最多。

    **覆盖优先**不是锦上添花，而是必要条件：如果真规则里的 sub(x→y) 用到的 x
    在示例里一次都没出现，那么 sub(x→y) 在示例上就是恒等，示例根本约束不到它——
    这类宇宙会被 `restrict_space` 正确判为「查询不可由示例确定」并拒掉。
    与其事后拒，不如在选示例时先把覆盖补齐。动机是**效度**而非效率：只有当示例
    把假设空间里所有不等于真规则的候选都证伪了，本题才良定义。
    """
    rng = random.Random(universe.seed ^ 0x5150)
    truth_fp = rule_fingerprint(tuple(universe.rule))
    comm = [c for c in one_step_committee(universe.alphabet)
            if rule_fingerprint(c) != truth_fp]

    cands = list(pool)
    rng.shuffle(cands)
    cands = cands[:n_candidates]

    remaining = list(comm)
    chosen: List[Tuple[Seq, Seq]] = []
    used = set()

    # ---- 阶段 0：符号覆盖 -------------------------------------------------
    must = referenced_symbols(tuple(universe.rule))
    for sym in must:
        if len(chosen) >= k:
            break
        if any(sym in inp for inp, _ in chosen):
            continue
        for inp in cands:
            if inp in used:
                continue
            if sym in inp:
                chosen.append((inp, universe.run(inp)))
                used.add(inp)
                remaining = [c for c in remaining
                             if apply_rule(inp, c) == universe.run(inp)]
                break

    for _step in range(k):
        if not remaining:
            break
        best, best_kill = None, -1
        for inp in cands:
            if inp in used:
                continue
            out = universe.run(inp)
            kill = sum(1 for c in remaining if apply_rule(inp, c) != out)
            if kill > best_kill:
                best_kill, best = kill, inp
        if best is None:
            break
        out = universe.run(best)
        chosen.append((best, out))
        used.add(best)
        remaining = [c for c in remaining if apply_rule(best, c) == out]

    for inp in cands:
        if len(chosen) >= k:
            break
        if inp in used:
            continue
        chosen.append((inp, universe.run(inp)))
        used.add(inp)
    return chosen[:k]


def pick_splitter(universe, support: Sequence[Tuple[Seq, Seq]],
                  pool: Sequence[Seq], probes: Sequence[Seq],
                  complexity: int, beam: int = 96,
                  n_candidates: int = 80) -> Optional[Seq]:
    """在当前候选集合里挑一个「劈得最开」的新示例（真正的 query-by-committee）。

    用来在 `select_support` 之后再补几轮，直到假设空间坍缩成一个行为等价类。
    """
    cands = enumerate_consistent(universe.alphabet, support,
                                 max_len=complexity, beam=beam,
                                 max_results=900)
    if not cands:
        return None
    truth_sig = behavior_signature(universe.rule, probes)
    rivals = [c for c in cands if behavior_signature(c, probes) != truth_sig]
    if not rivals:
        return None

    used = set(i for i, _ in support)
    best, best_kill = None, -1
    for inp in list(pool)[:n_candidates]:
        if inp in used:
            continue
        out = universe.run(inp)
        kill = sum(1 for r in rivals if apply_rule(inp, r) != out)
        if kill > best_kill:
            best_kill, best = kill, inp
    return best


def build_support(universe, pool: Sequence[Seq], k_target: int,
                  complexity: int, probes: Sequence[Seq],
                  verify_beam: int = 96,
                  max_extra: int = 5,
                  verbose: bool = False) -> Tuple[List[Tuple[Seq, Seq]], Dict[str, Any]]:
    """两阶段造示例集：先一步委员会贪心，再按真实候选集合迭代劈分。

    返回 (support, 最终歧义报告)。报告里的 `identifiable` / `truth_in_space`
    是两个硬门槛，生成器据此决定这个宇宙是收下还是丢掉重造。
    """
    seed_k = max(3, k_target - 2)
    sup = select_support(universe, pool, seed_k, n_candidates=48)
    if len(sup) >= k_target:
        sup = sup[:k_target]

    # 迭代引导只用一个小探针集：它决定「下一个示例加哪个」，用不着全量探针。
    # 全量探针（含所有被判分的查询）留给生成器末尾的终局关卡，那里才是
    # 「这题良不良定义」的判据。
    guide_probes = list(probes)[:64]

    report = ambiguity_report(universe.rule, universe.alphabet, sup, guide_probes,
                              max_len=complexity, beam=verify_beam)
    extra = 0
    while (not (report["identifiable"] and report["truth_in_space"])
           and extra < max_extra):
        nxt = pick_splitter(universe, sup, pool, guide_probes, complexity,
                            beam=verify_beam)
        if nxt is None:
            break
        sup.append((nxt, universe.run(nxt)))
        extra += 1
        report = ambiguity_report(universe.rule, universe.alphabet, sup,
                                  guide_probes, max_len=complexity,
                                  beam=verify_beam)
        if verbose:
            print("    +extra%d → |S|=%d cand=%d eq=%d"
                  % (extra, len(sup), report["n_candidates"],
                     report["n_equivalence"]))
    return sup, report


# ---------------------------------------------------------------------------
# 5. 解题器（同一搜索器的两种预算）
# ---------------------------------------------------------------------------
def solve_by_search(alphabet: Sequence[str],
                    examples: Sequence[Tuple[Seq, Seq]],
                    query: Seq,
                    max_len: int = 3,
                    beam: int = 96,
                    allow_cond: bool = True) -> Tuple[Seq, Dict[str, Any]]:
    """在假设空间里搜出一条与示例一致的规则，并用它回答 query。

    真规则不可见——这是它与 reference_solver 的根本区别：它是**归纳**，不是**回忆**。
    偏好更短、更简单的规则（奥卡姆剃刀），同长度按指纹稳定排序，保证可复现。
    """
    cands = enumerate_consistent(
        alphabet, examples, max_len=max_len, beam=beam,
        allow_cond=allow_cond, max_results=900,
    )
    if not cands:
        return tuple(query), {"n_candidates": 0, "fallback": "copy_input"}
    best = sorted(cands, key=lambda r: (len(r), rule_fingerprint(r)))[0]
    return apply_rule(query, best), {
        "n_candidates": len(cands),
        "chosen_rule": rule_text(best),
        "chosen_len": len(best),
        "has_cond": any(p[0] == "cond" for p in best),
    }


def matches(rule: Sequence[Tuple], examples: Sequence[Tuple[Seq, Seq]]) -> bool:
    """候选规则是否把每个输入都映射到给定的输出。"""
    for inp, out in examples:
        if apply_rule(inp, rule) != tuple(out):
            return False
    return True


__all__ = [
    "matches", "restrict_space", "enumerate_consistent", "behavior_signature",
    "ambiguity_report", "solve_by_search", "Rule", "one_step_committee",
    "select_support", "pick_splitter", "build_support",
]
