# 演示步骤（别人照着能跑出来）

> 目标：让一个**从没听过这个项目的人**，在 15 分钟内亲手跑出真实结果，并看懂数字的含义。
> 所有命令都在包根目录 `赵怡涵_C2A_提交包/` 下执行。

---

## 0. 前置条件

| 项目 | 要求 |
|---|---|
| Python | ≥ 3.7（实测 3.9.6 / macOS arm64） |
| 第三方依赖 | **无**。不需要 `pip install` 任何东西 |
| 网络 | **不需要** |
| GPU | **不需要** |
| 磁盘 / 内存 | < 20 MB / < 200 MB |

```bash
cd 赵怡涵_C2A_提交包
python3 -V          # 应该 >= 3.7
```

---

## 1. 一分钟：看这套题长什么样

```bash
cd 赵怡涵_C9_benchmark
python3 - <<'PY'
import json
tasks=[json.loads(l) for l in open('data/tasks_dev.jsonl',encoding='utf-8')
       if l.strip() and not l.startswith('#')]
print([t for t in tasks if t['phase']=='B'][0]['prompt'])
PY
```

你会看到：一段公开的规则语法 + 3–7 条标注示例（实测；设计目标 5）+ 一个待答查询。
**注意示例里没有任何答案可抄——查询的答案不在提示词里。**

---

## 2. 三分钟：自己当一次解题器

拿上面那道题，用示例推出规则，再算查询的答案。然后核对你对不对：

```bash
python3 - <<'PY'
import json
keys={json.loads(l)['item_id']:json.loads(l) for l in open('keys/keys_dev.jsonl',encoding='utf-8')
      if not l.startswith('#')}
tasks=[json.loads(l) for l in open('data/tasks_dev.jsonl',encoding='utf-8')
       if l.strip() and not l.startswith('#')]
t=[x for x in tasks if x['phase']=='B'][0]
print("答案   :", keys[t['item_id']]['answer'])
print("真规则 :", keys[t['item_id']]['rule_text'])
PY
```

> 💡 这一步顺便演示了本包的**结构保障**：题目在 `data/`，答案在 `keys/`，
> 两个目录分开。评测脚本只在评分阶段才把两者 join 起来。

---

## 3. 五分钟：跑完整流水线

```bash
bash scripts/reproduce.sh --fast      # 约 1 分钟：冒烟 + 审计 + 基线
```

看到什么算成功：

- `[2/8]` 生成器确定性：两次生成的 SHA-256 **完全一致**；
- `[6/8]` 汇总榜：生成 `results/leaderboard.md`（**排在检查之前**，新克隆也能一次跑通）；
- `[7/8]` 防污染审计：`A1–A7` 七项 **全 PASS**；
- `[8/8]` 基准自检：`S1–S7` 全绿，其中 **S5 是「可归纳性复核」** ——
  每个宇宙的示例集在独立探针集上唯一确定真规则；
- 最后打印包级与基准层两份冒烟测试的通过计数。

完整复现（含最重的归纳解题器，dev + holdout 两个分片）约 10–15 分钟：

```bash
bash scripts/reproduce.sh
```

---

## 4. 两分钟：看懂结果表

```bash
cat 赵怡涵_C9_benchmark/results/leaderboard.md
```

**怎么读这张表**（这是本演示最要紧的一步）：

| 你看到的 | 它意味着什么 |
|---|---|
| `reference_oracle` 的 acc = **1.0000** | 题目可解、评分器没有系统性错误。这是一条**校准线**，不是能力证据 |
| `baseline_copy_input` 的 acc | **免费分的天花板**。任何模型的分数必须先减去它才有意义 |
| `acc_phase_A` ≈ 抄输入率 | Phase A 不给示例，所以这个数就是"什么都不学"的水平 |
| `LearningGain_B_minus_A` | 示例真正带来了多少。**要对照 copy_input 基线的 A 阶段分数读** |
| `acc_id_B` vs `acc_ood_B` | 分布内 vs 组合新异。差距越大，说明模型越"会拟合"而不是"会外推" |
| `proxy_bounded_search` 的 acc | 人类难度的**模拟器代理**，**不是人类数据**（表里与文档里都标了） |

---

## 5. 五分钟：验证一件"通常没人验证的事"

**每一道题是不是良定义的？** 也就是：给定这组示例，标准答案是不是唯一的？

```bash
cd 赵怡涵_C9_benchmark
python3 -m bench.selfcheck --split dev --skip-determinism
```

重点是 `[S5] 可归纳性复核（独立探针集）`：它重新枚举所有与示例一致的候选规则，
统计它们在探针集上的行为等价类数。**输出必须显示所有宇宙的等价类都是 1。**

想亲手看一次"题目被判为欠定"是什么样子：

```bash
python3 - <<'PY'
import sys; sys.path.insert(0,'.')
from bench.rules import make_universe, sample_inputs, rule_text
from bench.hypothesis import ambiguity_report
import random
# 故意只用"随机抽"的示例（本基准确认过这会产生欠定题）
u = make_universe("demo", 20261031*1000003 + 2*7919 + 2*104729, 2)
rng = random.Random(1)
probes = sample_inputs(u, 48, rng)
sup = [(s, u.run(s)) for s in sample_inputs(u, 5, rng)]
rep = ambiguity_report(u.rule, u.alphabet, sup, probes, max_len=2, beam=96)
print("真规则      :", rule_text(u.rule))
print("行为等价类数:", rep["n_equivalence"], "（>1 就是欠定）")
print("像它的错规则:", rep["rivals"][:2])
PY
```

这就是本基准**会拒绝出题**的那道门槛。正式生成时，等价类 > 1 的宇宙会被整题作废、
换种子重造（拒绝统计见 `data/manifest_dev.json` 的 `reject_stats`）。

---

## 6. 演示结束时的三个"可以带走"的结论

1. **这个 benchmark 的每一道题都能被证明有唯一标准答案** —— 不是靠声明，是靠
   `selfcheck.py` S5 每次都会重跑的机械检查。
2. **答案不靠信任** —— `rule_text` 能反向解析、重新施加到查询上、与答案比对，
   全量 84 题都过。
3. **本包没有伪造任何东西** —— 没有前沿模型分数（未接入）、没有人类数据（未采集）、
   没有 Kaggle 提交（未做）。三件事都在 `00_先读我_待办清单.md` 里标着。

---

## 附：常见问题

**Q：为什么 `requirements.txt` 是空的？**
A：不是漏写。本包只用 Python 标准库，这是刻意选择——少一个依赖就少一类"装不上"的
失败面。文件里逐条写明了"本来可以用但刻意不用"的依赖及原因。

**Q：为什么规则链最多只有 2 条原语？**
A：可归纳性检查逼出来的。3 条原语时，规则的假设空间约 10⁹ 量级，十几个短示例提供的
约束远远不够，探针集上会剩下 9–11 个行为等价类——标准答案不唯一。
实测数字见 `赵怡涵_C9_benchmark/CHANGELOG.md` 的 D1 与 `bench/rules.py` 的
`COMPLEXITY_PLAN` 注释。

**Q：为什么没有 GPT/Claude 的分数？**
A：因为**没跑过**。本机 `/tmp/ollama/ollama` 不存在、11434 端口 connection refused、
环境里没有 API key。适配器已实现（`--model openai_compat`），拿到 key 后一条命令即可
复跑；**在真的跑出来之前，本包不写任何前沿模型分数。**

**Q：为什么 `search_solver` 的 B 阶段接近满分，OOD 却差很多？**
A：这正是本基准想测的东西。它能完美拟合示例，但把规则外推到"零件都见过、组合没见过"
的输入上就露馅了——SCAN/COGS 意义上的系统性泛化失败。
