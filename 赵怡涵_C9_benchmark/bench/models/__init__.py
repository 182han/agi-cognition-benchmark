#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ΔR-Bench 解题器适配器

统一接口，让「确定性基线 / 归纳搜索器 / 真实 LLM」跑在同一套题目、同一套评分下：

    class Adapter:
        name: str                 # 结果文件的前缀
        kind: str                 # reference | inductive | baseline | llm
        is_frontier_model: bool   # **必须诚实填写**：本地小模型 / 确定性基线一律 False
        notes: str                # 写进结果文件的模型说明
        def solve_batch(tasks) -> Dict[item_id, Prediction]

    Prediction = {"raw": 任意, "answer": Optional[Seq], "confidence": Optional[float]}

硬性约束（写在代码里，不靠自觉）：
  * 所有适配器**只能看到 task 字典**（support / query / prompt / alphabet）。
    答案 key 由 run_eval 持有，绝不下发。这就是「题目与答案物理分离」在接口层的落地。
  * `reference` 适配器是全知参考解，用来证明题目可解、评分器正确；
    它的分数**不能**当作任何模型的能力证据。
"""

from __future__ import annotations

import os
import random
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from bench.rules import apply_rule  # noqa: E402
from bench.scoring import parse_answer  # noqa: E402

Prediction = Dict[str, Any]


class Adapter(object):
    name = "adapter"
    kind = "baseline"
    is_frontier_model = False
    notes = ""

    def solve_batch(self, tasks: Sequence[Dict[str, Any]]
                    ) -> Dict[str, Prediction]:
        raise NotImplementedError

    # 便利方法：按 support 分组缓存，避免同一宇宙重复搜索
    def _group_by_universe(self, tasks):
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for t in tasks:
            groups.setdefault(t["universe_public_id"], []).append(t)
        return groups


# ---------------------------------------------------------------------------
# 1. 参考解（全知）：证明题目可解 + 评分器正确
# ---------------------------------------------------------------------------
class ReferenceAdapter(Adapter):
    name = "reference_oracle"
    kind = "reference"
    is_frontier_model = False
    notes = ("全知参考解：直接施加生成该宇宙时使用的真规则。"
             "它证明「题目在本评分器下可解」「评分器无系统性错误」，"
             "其分数不是任何模型的能力证据。")

    def __init__(self, keys: Dict[str, Dict[str, Any]]):
        # 参考解是全知的，允许它拿到 rule_text —— 但仅此一个适配器可以。
        from bench.rules import (  # 局部导入，避免其他适配器误用
            apply_primitive,
        )
        self._keys = keys

    def solve_batch(self, tasks):
        out: Dict[str, Prediction] = {}
        for t in tasks:
            k = self._keys.get(t["item_id"])
            if k is None:
                out[t["item_id"]] = {"raw": None, "answer": None, "confidence": None}
                continue
            out[t["item_id"]] = {
                "raw": " ".join(k["answer"]) if k["answer"] else "none",
                "answer": tuple(k["answer"]),
                "confidence": 1.0,
            }
        return out


# ---------------------------------------------------------------------------
# 2. 确定性基线（**不是模型**）
# ---------------------------------------------------------------------------
class CopyInputAdapter(Adapter):
    """抄输入。用来说明「答案 = 输入的频率」有多高——这是最容易被忽略的免费分。"""
    name = "baseline_copy_input"
    kind = "baseline"
    is_frontier_model = False
    notes = "确定性基线：直接把查询序列当答案输出。不是模型。"

    def solve_batch(self, tasks):
        out = {}
        for t in tasks:
            q = tuple(t["query"]["input"])
            out[t["item_id"]] = {"raw": " ".join(q) if q else "none",
                                 "answer": q, "confidence": 0.25}
        return out


class MostFrequentSupportOutputAdapter(Adapter):
    """输出示例里出现次数最多的那个输出序列（不推理，只数数）。"""
    name = "baseline_frequent_support_output"
    kind = "baseline"
    is_frontier_model = False
    notes = "确定性基线：返回示例输出中的众数。不是模型。"

    def solve_batch(self, tasks):
        out = {}
        for t in tasks:
            cnt: Dict[Tuple[str, ...], int] = {}
            for ex in t["support"]:
                o = tuple(ex["output"])
                cnt[o] = cnt.get(o, 0) + 1
            if cnt:
                best = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            else:
                best = tuple(t["query"]["input"])
            out[t["item_id"]] = {"raw": " ".join(best) if best else "none",
                                 "answer": best, "confidence": 0.2}
        return out


class RandomAdapter(Adapter):
    """随机基线：从示例输出里随机挑一个；没有示例就抄输入。

    这是「不做任何归纳」的下界。Phase A 的随机与抄输入会重合成同一个数，
    这是正常的——Phase A 本来就没什么可学。
    """
    name = "baseline_random"
    kind = "baseline"
    is_frontier_model = False
    notes = "确定性随机基线（固定种子）。不是模型。"

    def __init__(self, seed: int = 20261031):
        self.seed = seed

    def solve_batch(self, tasks):
        rng = random.Random(self.seed)
        out = {}
        for t in tasks:
            outs = [tuple(ex["output"]) for ex in t["support"]]
            if outs:
                a = rng.choice(outs)
            else:
                a = tuple(t["query"]["input"])
            out[t["item_id"]] = {"raw": " ".join(a) if a else "none",
                                 "answer": a, "confidence": 0.1}
        return out


# ---------------------------------------------------------------------------
# 3. 归纳搜索器（**非 LLM 的强基线**）
# ---------------------------------------------------------------------------
class SearchSolverAdapter(Adapter):
    """在声明的假设空间里做 beam search 的归纳解题器。

    它只能看到示例和查询——真规则对它不可见。它是本包里除 LLM 之外最强的
    自动解题器，也是「这道题到底能不能从示例里解出来」的直接证据。
    通过 `max_len` / `beam` 两个旋钮，同一个实现还可以当人类难度的代理：
    预算越小 ≈ 工作记忆容量越小（Miller 1956；Cowan 2001）。
    """

    name = "search_solver"
    kind = "inductive"
    is_frontier_model = False
    notes = "假设空间 beam search 归纳器（确定性，非 LLM）。"

    def __init__(self, max_len: int = 2, beam: int = 160,
                 use_feedback: bool = True, label: Optional[str] = None):
        self.max_len = max_len
        self.beam = beam
        self.use_feedback = use_feedback
        if label:
            self.name = label
        self._cache: Dict[Any, Any] = {}
        self.notes = ("假设空间 beam search 归纳器（max_len=%d, beam=%d，确定性，非 LLM）。"
                      % (max_len, beam))

    def _support_of(self, t):
        sup = [(tuple(ex["input"]), tuple(ex["output"])) for ex in t["support"]]
        fb = t.get("feedback")
        if fb and self.use_feedback:
            sup.append((tuple(fb["query"]), tuple(fb["correct_answer"])))
        return sup

    def solve_batch(self, tasks):
        """按 (字母表, 示例集) 分组，每组只跑一次假设搜索，再回答组内全部查询。

        这不只是提速：它保证同一个宇宙里的所有题目**看到的是同一条被归纳出来的
        规则**，而不是每题各搜各的。否则「同一宇宙里 B0 用规则甲、B1 用规则乙」
        会让 LearningGain 混进搜索抖动，指标就不可解释了。
        """
        from bench.hypothesis import enumerate_consistent
        from bench.rules import apply_rule
        out: Dict[str, Prediction] = {}
        groups: Dict[Any, List[Dict[str, Any]]] = {}
        for t in tasks:
            sup = tuple(self._support_of(t))
            groups.setdefault((tuple(t["alphabet"]), sup), []).append(t)

        for (alpha, sup), items in groups.items():
            if (alpha, sup) in self._cache:
                cands = self._cache[(alpha, sup)]
            else:
                cands = enumerate_consistent(alpha, sup, max_len=self.max_len,
                                             beam=self.beam, max_results=900)
                self._cache[(alpha, sup)] = cands
            # 奥卡姆剃刀：偏好更短、更简单的规则；同长度按指纹稳定排序
            from bench.rules import rule_fingerprint
            cands = sorted(cands, key=lambda r: (len(r), rule_fingerprint(r)))
            best = cands[0] if cands else tuple()
            nc = max(1, len(cands))
            conf = round(1.0 / float(nc), 4)
            for t in items:
                ans = apply_rule(tuple(t["query"]["input"]), best)
                out[t["item_id"]] = {
                    "raw": " ".join(ans) if ans else "none",
                    "answer": tuple(ans),
                    "confidence": conf,
                    "info": {"n_candidates": len(cands),
                             "chosen_rule": " ; ".join(str(x) for x in best)},
                }
        return out


class BoundedSearchAdapter(SearchSolverAdapter):
    """人类难度代理：把搜索预算压到「工作记忆只有 1~2 个假设」的水平。

    **它不是人类数据。** 人类基线必须真的找人测（见 task说明.md 的人类基线协议）。
    它在这里的作用只有一个：给出「难度梯度是不是真的在升」的可证伪预测，
    供后续的人类实验去对照。把它当人类分数引用，属于伪造证据。
    """
    name = "proxy_bounded_search"
    kind = "inductive"
    is_frontier_model = False

    def __init__(self, max_len: int = 1, beam: int = 6):
        SearchSolverAdapter.__init__(self, max_len=max_len, beam=beam,
                                     label="proxy_bounded_search")
        self.notes = ("人类难度**代理**（不是人类数据）：max_len=%d, beam=%d 的受限搜索，"
                      "用来预测难度梯度，不可当作人类基线引用。" % (max_len, beam))


# ---------------------------------------------------------------------------
# 4. 真实 LLM 适配器
# ---------------------------------------------------------------------------
class RecordedLLMAdapter(Adapter):
    """读取**真实跑出来的**模型回答记录（离线重放）。

    这是本包对「不许编造模型分数」这条红线的工程化回应：
    任何 LLM 分数都必须在 `results/raw/<name>.jsonl` 里有一份逐题原始回答，
    每一行都要有 item_id 与原始文本。没有原始记录的分数，本包一律不认——
    `tests/test_smoke.py` 会检查这份原始记录是否存在且行数对得上。

    记录文件格式（JSONL）：
        {"item_id": "...", "raw": "ze mi mi tu go", "confidence": 0.7,
         "round": 1, "model": "...", "run_at": "..."}
    """
    kind = "llm"

    def __init__(self, name: str, raw_path: str, notes: str = "",
                 is_frontier_model: bool = False):
        self.name = name
        self.raw_path = raw_path
        self.is_frontier_model = is_frontier_model
        self.notes = notes
        self._rows = self._load(raw_path)

    @staticmethod
    def _load(path: str) -> Dict[Tuple[str, int], Dict[str, Any]]:
        import json
        rows: Dict[Tuple[str, int], Dict[str, Any]] = {}
        if not os.path.exists(path):
            return rows
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                r = json.loads(line)
                rows[(r["item_id"], int(r.get("round", 1)))] = r
        return rows

    def solve_batch(self, tasks):
        out: Dict[str, Prediction] = {}
        for t in tasks:
            rnd = int(t.get("round", 1))
            r = self._rows.get((t["item_id"], rnd))
            if r is None:
                out[t["item_id"]] = {"raw": None, "answer": None,
                                     "confidence": None}
                continue
            out[t["item_id"]] = {
                "raw": r.get("raw"),
                "answer": parse_answer(r.get("raw")),
                "confidence": r.get("confidence"),
                # 留痕字段回放：离线重放后的 raw 文件不应丢掉原始推理痕迹
                "thinking": r.get("thinking"),
                "usage": r.get("usage"),
                "finish_reason": r.get("finish_reason"),
                "attempts": r.get("attempts"),
                "repairs": r.get("repairs"),
                "latency_ms": r.get("latency_ms"),
                "error": r.get("error"),
            }
        return out


class OpenAICompatAdapter(Adapter):
    """接前沿模型 API 的即插即用适配器（OpenAI 兼容 /chat/completions）。

    本包**不内置任何 API Key，也没有联网调用过它**——这一点在 README 的
    「已知缺口」与测试结果里都写明了。它存在是为了让「拿到 key 之后怎么复跑」
    成为一条可执行的命令，而不是一句承诺：

        export DRBENCH_API_BASE=https://api.example.com/v1
        export DRBENCH_API_KEY=sk-...
        python3 -m bench.run_eval --model openai_compat \\
            --model-name gpt-x --split holdout

    提示词直接取 task["prompt"]，与人类/其他模型看到的完全一致。
    """

    name = "openai_compat"
    kind = "llm"

    def __init__(self, model_name: str, api_base: Optional[str] = None,
                 api_key: Optional[str] = None, temperature: float = 0.0,
                 max_tokens: int = 64, timeout: int = 60,
                 is_frontier_model: bool = True):
        self.model_name = model_name
        self.api_base = (api_base or os.environ.get("DRBENCH_API_BASE")
                         or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("DRBENCH_API_KEY")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.is_frontier_model = is_frontier_model
        self.name = "llm_" + model_name.replace("/", "_")
        self.notes = ("通过 OpenAI 兼容接口调用 %s（temperature=%s）。"
                      % (model_name, temperature))

    def solve_batch(self, tasks):
        import json
        import urllib.request
        if not self.api_key:
            raise RuntimeError(
                "未设置 DRBENCH_API_KEY —— 本包不内置任何密钥，也不会伪造分数。\n"
                "拿到 key 后用: export DRBENCH_API_KEY=... 再重跑本命令。")
        out: Dict[str, Prediction] = {}
        for t in tasks:
            body = {
                "model": self.model_name,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "messages": [
                    {"role": "system",
                     "content": "You solve rule-induction puzzles. "
                                "Reply with ONLY the output sequence "
                                "(space-separated symbols, or the word none)."},
                    {"role": "user", "content": t["prompt"]},
                ],
            }
            req = urllib.request.Request(
                self.api_base + "/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + self.api_key},
            )
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                raw = data["choices"][0]["message"]["content"]
            except Exception as e:  # 网络/额度/模型名错误都要如实记，不许静默
                raw = "ERROR: %s" % e
            out[t["item_id"]] = {
                "raw": raw,
                "answer": parse_answer(raw),
                "confidence": None,
                "latency_ms": int((time.time() - t0) * 1000),
            }
        return out


# ---------------------------------------------------------------------------
# 5. 本地权重推理（llama.cpp `llama-server`，OpenAI 兼容 /v1/chat/completions）
# ---------------------------------------------------------------------------
class LlamaCppServerAdapter(Adapter):
    """真实本地模型：由 llama.cpp `llama-server` 提供的 OpenAI 兼容端点。

    与 `openai_compat` 的区别（为什么另写一个适配器而不是复用它）：

      * `is_frontier_model = False` —— 本地 4B 级权重，**不是前沿模型**，分数不能外推；
        `openai_compat` 默认把这一位写成 True。
      * `num_predict` 默认 1024，可配；`openai_compat` 写死 64。
      * 解析失败**重试 2 次**（只改格式，不改内容）；仍失败如实记 parse_failure，
        **绝不替模型编答案**。重试的每一次原始输出都留在 `repairs` 里。
      * 每条预测保留 `raw` / `thinking` / `usage` / `finish_reason` / `attempts` /
        `latency_ms`，由 run_eval 原样写进 `results/raw/libm_*.jsonl` 留痕。

    典型用法（权重来自 Ollama 的同一份 GGUF blob）：

        llama-server -m <model.gguf> --host 127.0.0.1 --port 11435 --alias <name>
        python3 -m bench.run_eval --model llamacpp --model-name <name> \\
            --endpoint http://127.0.0.1:11435/v1 --thinking off --split dev

    提示词取 `task["prompt"]`，与其它适配器看到的完全一致；适配器接口只收到 task，
    拿不到 keys（答案与题目在接口层物理分离）。
    """

    kind = "llm"
    is_frontier_model = False

    SYSTEM_PROMPT = ("You solve rule-induction puzzles. Reply with ONLY the output "
                     "sequence as space-separated symbols. If the output is empty, "
                     "reply exactly: none. Do not explain.")
    REPAIR_PROMPT = ("Your reply above could not be parsed. Reply with ONLY the "
                     "output sequence as space-separated symbols (or the word none). "
                     "Nothing else.")

    def __init__(self, model_name: str,
                 endpoint: str = "http://127.0.0.1:11435/v1",
                 num_predict: int = 1024, thinking: str = "off",
                 max_parse_retries: int = 2, temperature: float = 0.0,
                 seed: int = 20261031, timeout: int = 1800):
        if thinking not in ("on", "off"):
            raise ValueError("thinking 只能是 on/off，实际 %r" % thinking)
        self.model_name = model_name
        self.endpoint = endpoint.rstrip("/")
        self.num_predict = int(num_predict)
        self.thinking = thinking
        self.max_parse_retries = int(max_parse_retries)
        self.temperature = temperature
        self.seed = seed
        self.timeout = timeout
        self.name = "llm_" + model_name.replace("/", "_")
        self.notes = ("本地权重推理（llama.cpp llama-server，%s）：%s，num_predict=%d，"
                      "thinking=%s，temperature=%s，seed=%d。"
                      "**本地小模型，不是前沿模型，分数不可外推到任何榜单。**"
                      % (self.endpoint, model_name, self.num_predict, self.thinking,
                         self.temperature, self.seed))
        self.config = {
            "endpoint": self.endpoint,
            "model": model_name,
            "num_predict": self.num_predict,
            "thinking": self.thinking,
            "max_parse_retries": self.max_parse_retries,
            "temperature": self.temperature,
            "seed": self.seed,
            "system_prompt": self.SYSTEM_PROMPT,
            "repair_prompt": self.REPAIR_PROMPT,
        }
        self.stats = {
            "requests": 0, "completion_tokens": 0, "prompt_tokens": 0,
            "gen_sec": 0.0, "parse_failure_after_retry": 0, "repairs": 0,
            "http_errors": 0,
        }

    # -- 单次请求 ----------------------------------------------------------
    def _chat(self, messages):
        import json
        import urllib.request
        body = {
            "model": self.model_name,
            "temperature": self.temperature,
            "seed": self.seed,
            "max_tokens": self.num_predict,
            "messages": messages,
        }
        if self.thinking == "off":
            # 关键：thinking 模型的 CoT 会吃掉整个 num_predict 预算，
            # 导致 message.content 为空（实测见测试结果 §2.1）。这里显式关闭思考，
            # 让最终答案落在 content 里；开启思考的实测数据单独记录。
            body["chat_template_kwargs"] = {"enable_thinking": False}
        req = urllib.request.Request(
            self.endpoint + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # 网络/端点/模型名错误都如实记，不许静默
            self.stats["http_errors"] += 1
            return {"content": None, "thinking": None, "error": str(e),
                    "finish_reason": None, "usage": {},
                    "latency_ms": int((time.time() - t0) * 1000)}
        ch = (data.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        usage = data.get("usage") or {}
        self.stats["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        self.stats["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        return {"content": msg.get("content"),
                "thinking": msg.get("reasoning_content") or msg.get("thinking"),
                "error": None,
                "finish_reason": ch.get("finish_reason"),
                "usage": usage,
                "latency_ms": int((time.time() - t0) * 1000)}

    # -- 批量作答（含格式修复重试）----------------------------------------
    def solve_batch(self, tasks):
        out: Dict[str, Prediction] = {}
        t0 = time.time()
        for t in tasks:
            messages = [{"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": t["prompt"]}]
            repairs = []
            r = self._chat(messages)
            self.stats["requests"] += 1
            content = r["content"]
            ans = parse_answer(content)
            attempts = 1
            while ans is None and attempts <= self.max_parse_retries:
                repairs.append(content)
                self.stats["repairs"] += 1
                messages = messages + [
                    {"role": "assistant", "content": content or ""},
                    {"role": "user", "content": self.REPAIR_PROMPT}]
                r = self._chat(messages)
                self.stats["requests"] += 1
                content = r["content"]
                ans = parse_answer(content)
                attempts += 1
            if ans is None:
                self.stats["parse_failure_after_retry"] += 1
            out[t["item_id"]] = {
                "raw": content,
                "answer": ans,
                "confidence": None,
                "thinking": r["thinking"],
                "usage": r["usage"],
                "finish_reason": r["finish_reason"],
                "attempts": attempts,
                "repairs": repairs,
                "latency_ms": r["latency_ms"],
                "error": r["error"],
            }
        self.stats["gen_sec"] = round(time.time() - t0, 1)
        self.stats["tok_per_sec"] = (
            round(self.stats["completion_tokens"] / self.stats["gen_sec"], 2)
            if self.stats["gen_sec"] else None)
        return out


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------
def build_adapter(name: str, keys: Dict[str, Dict[str, Any]],
                  **kw) -> Adapter:
    if name == "reference":
        return ReferenceAdapter(keys)
    if name == "copy_input":
        return CopyInputAdapter()
    if name == "frequent_support_output":
        return MostFrequentSupportOutputAdapter()
    if name == "random":
        return RandomAdapter(seed=kw.get("seed", 20261031))
    if name == "search":
        return SearchSolverAdapter(max_len=kw.get("max_len", 2),
                                   beam=kw.get("beam", 160))
    if name == "bounded_search":
        return BoundedSearchAdapter(max_len=kw.get("max_len", 1),
                                    beam=kw.get("beam", 6))
    if name == "recorded_llm":
        return RecordedLLMAdapter(kw["model_name"], kw["raw_path"],
                                  notes=kw.get("notes", ""),
                                  is_frontier_model=kw.get(
                                      "is_frontier_model", False))
    if name == "openai_compat":
        return OpenAICompatAdapter(kw["model_name"],
                                   is_frontier_model=kw.get(
                                       "is_frontier_model", True))
    if name == "llamacpp":
        return LlamaCppServerAdapter(
            kw["model_name"],
            endpoint=kw.get("endpoint", "http://127.0.0.1:11435/v1"),
            num_predict=kw.get("num_predict", 1024),
            thinking=kw.get("thinking", "off"),
            max_parse_retries=kw.get("max_parse_retries", 2),
            temperature=kw.get("temperature", 0.0),
            seed=kw.get("seed", 20261031),
            timeout=kw.get("timeout", 1800))
    raise ValueError("unknown adapter: %s" % name)


__all__ = [
    "Adapter", "ReferenceAdapter", "CopyInputAdapter",
    "MostFrequentSupportOutputAdapter", "RandomAdapter",
    "SearchSolverAdapter", "BoundedSearchAdapter", "RecordedLLMAdapter",
    "OpenAICompatAdapter", "LlamaCppServerAdapter", "build_adapter",
]
