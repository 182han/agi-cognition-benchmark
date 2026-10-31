# ΔR-Bench 任务说明

**Task Specification: ΔR-Bench — Few-Shot Rule Induction with Feedback Revision**

| 项目 | 内容 |
|---|---|
| 赛道 | Track 1 — Learning（学习） |
| 版本 | v1.0 ｜ 2026-10-03 |
| 代码 | `赵怡涵_C9_benchmark/` |
| 授权 | MIT（见 `赵怡涵_C9_benchmark/LICENSE`） |
| 对应提案 | `赵怡涵_C2A_proposal.md` §2 |

---

## 1. 任务定义

被测系统（模型或人）面对**一个规则宇宙**：一套符号表 + 一条隐藏的符号序列变换规则。
系统只能看到若干条「输入 → 输出」的标注示例，需要回答新查询的正确答案。

**这是一个归纳任务，不是检索任务。** 每个宇宙的符号表是自造的、规则是程序随机生成的，
答案在世界上任何语料里都不存在。规则空间在题面里**完全公开**（见 §2），所以"猜出题人
想什么"不是可行策略，唯一的路径是从示例中归纳。

### 1.1 三阶段协议

| 阶段 | 给什么 | 测什么 | 在 KSTAR 里的位置 |
|---|---|---|---|
| **A** | 只有查询，**没有任何示例** | 先验水平 / 抄输入的天花板 | K₀（尚未学习） |
| **B** | 3–7 条标注示例（实测；设计目标 5）+ 查询 | 从示例中归纳规则的能力 | 示例 → K |
| **C** | 把**模型自己在 B 阶段的答案与正确答案**一起回灌，再问同一宇宙的新查询 | ΔR（预期与实际的偏差）是否真的回流去更新 K | A→R→ΔR→K 更新 |

Round 2（Phase C）由评测脚本**按写死的规则**构造，见 `bench/run_eval.py::build_round2`：

1. 每个宇宙取 Round 1 的第一道 Phase B 题作为「被反馈的那道题」；
2. 反馈里写明：当时的问题、模型当时的答案、判对判错、以及正确答案；
3. 该「(查询 → 正确答案)」对同时并入 Round 2 的 support —— 这样确定性解题器和 LLM
   看到的是**同一份信息**，指标才可比。

---

## 2. 输入输出格式

### 2.1 输入（提示词）

每个宇宙的提示词结构（逐字模板见 `bench/generate.py::GRAMMAR_TEXT`）：

```
TASK: rule induction over symbol sequences.
A hidden rule maps an input sequence to an output sequence.
The hidden rule is a CHAIN of 1 to 2 primitives, applied LEFT TO RIGHT.
Only these primitives exist:

  sub(a,b)   replace every occurrence of symbol a with symbol b
  del(a)     delete every occurrence of symbol a
  dup(a)     duplicate every occurrence of symbol a (in place)
  swap(a,b)  exchange every a with b and every b with a
  rev()      reverse the whole sequence
  rot(k)     rotate the sequence left by k positions (k is 1 or 2)
  if[P]{X}   apply X only if condition P holds, otherwise change nothing

Conditions P used by this benchmark:
  contains(a)     count(a) >= n     len(seq) >= n     head(seq) == a

Answer with the output sequence as space-separated symbols.
If the output is empty, answer exactly: none

=== UNIVERSE <公开 id> ===

Labelled examples for THIS universe:
  ex1: <符号序列>  ->  <符号序列>
  ...

QUERY: <符号序列>

ANSWER:
```

Round 2 的提示词在 `QUERY` 之前多一段：

```
FEEDBACK on your previous answer in this universe:
  previous query : <符号序列>
  your answer    : <符号序列>   (WRONG 或 CORRECT)
  correct answer : <符号序列>
```

**符号表**：16 个自造双字母音节（`ka ro mi tu ve sa lo ni pa du ze qi fu go ha ji`）中
每个宇宙随机取 5–6 个。纯 ASCII，任何传输通道都无损。

**规则空间（声明的假设空间）**：上表 7 类原语，链长 1–2，条件原语的内部只允许非条件原语
（避免无限递归语义）。

### 2.2 输出格式

模型输出**一行符号序列**，符号之间用空格分隔：

| 情况 | 正确写法 |
|---|---|
| 非空输出 | `ka ro mi` |
| 空输出 | `none` |

**评分器会做规范化**，以下写法都接受（见 `bench/scoring.py::parse_answer`）：
`[ka, ro, mi]`（JSON 数组）、`KA,RO,MI`（大写+逗号）、`Answer: ka ro mi`（带前缀）、
`  ka ro mi  `（多余空白）、多行输出只取第一行。

**规范化失败会被单列为 `parse_failure_rate`，不计入错误率。** 这是刻意的：把"格式不合规"
混进"能力不行"是 LLM 评测里最常见的效度污染源之一。一个模型可以答对但格式跑偏，那样的
分数不该被当成推理失败。

---

## 3. 评分规则

### 3.1 判分

**精确匹配**。规范化后的符号序列与标准答案逐元素相等即得分，否则不得分。没有部分分——
理由是部分分需要人为定义"错几个符号算几分"，那个权重没有理论依据，只会引入噪声。

答案 key 存放在 `keys/keys_<split>.jsonl`，**与题目文件物理分离**，评测脚本在读提示词时
永远不加载它。任何 LLM 分数还必须在 `results/raw/` 里留下逐题原始回答，否则不予采信。

### 3.2 答案的正确性可被独立核验

每道题的 key 里存了人可读的 `rule_text`（例如
`del(ha) ; if[ka ∈ seq]{ sub(ha→du) }`）。`bench/rules.py::parse_rule_text` 能把它**反向
解析回规则结构**，重新施加到查询上，结果**必须**等于存下来的答案。这个往返在
`bench/selfcheck.py`（S2）与 `tests/test_smoke.py` 里都会被全量复核。

这一步的意义：把"答案"从一个**需要信任的断言**，变成一个**可机械复核的结论**。

### 3.3 核心指标

| 指标 | 定义 | 怎么读 |
|---|---|---|
| `accuracy` | 全题正确率 | 总览，但**必须**与下面的分解一起看 |
| `acc_phase_A/B/C` | 三个阶段的正确率 | A 是天花板校准，B 是归纳，C 是反馈修正 |
| `LearningGain_B_minus_A` | `acc_B − acc_A` | 示例带来了多少。**需要对照 copy_input 基线的 A 阶段分数**，否则会高估 |
| `FeedbackGain_C_minus_B` | `acc_C − acc_B` | 反馈带来了多少 |
| `RevisionRate_C_given_B` | 在 B 阶段没满分的宇宙里，C 阶段的正确率 | 反馈后是否真的改 |
| `OvercorrectionRate` | 在 B 阶段有得分的宇宙里，C 阶段的错误率 | 反馈后是否被带偏 |
| `acc_id` / `acc_ood` | 分布内 / 组合新异题正确率 | OOD 的定义见 §3.4 |
| `GeneralizationGap_id_minus_ood` | `acc_id − acc_ood` | **"会拟合"与"会外推"的距离** |
| `copy_input_rate` | 答案恰好等于查询输入的比例 | 免费分的占比 |
| `parse_failure_rate` | 规范化失败比例 | 格式问题，不是能力问题 |
| `ECE` | 期望校准误差（Guo et al., 2017） | **辅助指标**，见 §3.5 |

### 3.4 OOD（组合新异）题的判定

对每个宇宙，把每条序列映射为一个特征向量：
`(条件谓词的真值元组, 出现过的符号集合, 序列长度)`。

- **ID 题**：查询的特征向量**出现过**在示例里；
- **OOD 题**：查询的特征向量**没出现过**，但它的每个"零件"都在示例里出现过
  （符号 ⊆ 示例符号集、长度 ∈ 示例长度集、分支取值 ∈ 示例分支取值集）。

这是 SCAN / COGS 意义上的系统性泛化：每个零件都熟，但这个**组合**没练过。规则完全由示例
确定，所以题目是公平的——它考的只是"能不能真的组合"，而不是"记住没记住"。

### 3.5 为什么 ECE 只是辅助指标

置信度校准属于 **Track 2 — Metacognition**。把 ECE 当主指标会违反"一个 benchmark 只测一个
能力"的原则，也会让分数无法归因。

本基准保留 ECE 的唯一用途：**区分"答对是因为知道，还是因为蒙对"**。它在结果里单独一列，
并且在 `results/*_scores.json` 里与 `mean_confidence`、`confidence_gap` 一起呈现。

⚠️ **确定性解题器（search / bounded_search）的 ECE 不是校准主张**：它们报出的
"置信度"是 `1/|候选规则数|` 这个**启发式代理**，只用于横向比较歧义程度，不是概率。
只有真正自己输出概率的模型（如 LLM）的 ECE 才有校准含义。

---

## 4. 人类基线

### 4.1 预期分布（**预测，不是实测**）

| 难度 | 规则链 | 预期人类正确率 | 依据 |
|---|---|---|---|
| easy | 1 条原语 | 85–95% | 单条映射/删除，工作记忆负荷约 2–3 个 chunk |
| medium | 2 条原语（无条件） | 55–75% | 需同时保持两条规则并按序施加 |
| hard | 2 条原语（含条件分支） | 35–55% | 分支额外需要抑制"无条件执行"的默认反应 |
| OOD（各档内） | — | 比同档 ID 低 15–25 个百分点 | 需组合外推，而非套用记下的映射 |

依据：Miller (1956) 的 7±2、Cowan (2001) 修正为约 4 个 chunk。示例数 3–7（设计目标 5）、规则 1–2 原语、
外加一个待答查询，负荷正压在容量边界附近。

### 4.2 采集协议（**待执行**）

| 项目 | 设计 |
|---|---|
| 样本 | n = 30 名成人，按"有 / 无离散数学或逻辑训练"分层各半 |
| 界面 | 与原提示词**逐字一致**的纯文本（保证与 AI 条件可比） |
| 题量 | 每人 30 题，跨三档难度、含至少 6 道 OOD |
| 记录 | 每题正确与否、作答耗时、自答置信度（0–100%） |
| 筛查 | 正确率 >95% 或 <10% 的题标记并替换 |
| 导出工具 | `python3 examples/llm_batch.py export1 --split dev --out /tmp/human_batch` —— **同一份批次文件可以同时喂给人**，这是刻意的：人与模型看到的题面完全相同 |
| 伦理 | 知情同意 + 匿名化；不采集任何个人可识别信息 |

**状态：`【待赵怡涵执行】`** —— 真人数据**尚未采集**，本包含有的、涉及人类难度的数字
全部来自 `bounded_search` 模拟器，并在每一处都标注了「这不是人类数据」。

### 4.3 必须写明的边界

n = 30 的**便利样本不具备人口统计学代表性**，这是 DeepMind 三阶段评估协议里第二步的
**降级版**。它足以支撑"这道题对人类是否可解 / 是否过难"的判断，**不足以**支撑
"AI 已达到人类中位水平"这类结论。任何把本基准的便利样本当作人口基线来读的结论都是无效的。

---

## 5. 数据分片与防污染

| 分片 | 生成种子 | 状态 |
|---|---|---|
| `dev` | 20261031（公开、写死） | 公开，用于开发与调试 |
| `holdout` | 承诺哈希 `data/holdout_seed_commitment.json`；真实种子（`seed: 255399336`）在 `data/manifest_holdout.json` 里公开以便复现 | 评测用 |

**先承诺后生成**：holdout 的随机种子在生成**之前**就把 SHA-256 写进仓库，生成之后才公开
种子。这样"这套题是不是根据结果挑出来的"就成了一个可验证的事实，而不是一句承诺。

每一项防污染措施都有对应的自动审计（`bench/contamination.py`，A1–A7）：canary 存在、
提示词答案泄漏扫描、重复题/答案冲突、答案熵与抄输入率、dev×holdout 的 5-gram 重叠、
控制集退化、扰动不变性。审计结果见 `赵怡涵_C9_benchmark/docs/防作弊报告.md`。

---

## 6. 怎么跑

```bash
cd 赵怡涵_C9_benchmark
bash scripts/reproduce.sh                 # 一条命令跑完全部（dev + holdout）
python3 -m bench.run_eval --model search --split dev --max-len 2 --beam 160
python3 -m bench.selfcheck --split dev    # 基准自检：可归纳性 / 答案可核验 / 参考解满分
```

接前沿模型 API（**本包不内置任何 API Key，也没有联网调用过**）：

```bash
export DRBENCH_API_BASE=https://api.example.com/v1
export DRBENCH_API_KEY=sk-...
python3 -m bench.run_eval --model openai_compat --model-name <模型名> --split holdout
```

或者走"逐题留痕"的离线路线（推荐，能防止分数无法追溯）：

```bash
python3 examples/llm_batch.py export1 --split holdout --out /tmp/batch
# 把 /tmp/batch/batch1.json 里的 prompt 交给模型，回收回答
python3 examples/llm_batch.py ingest1 --raw results/raw/llm_<模型>_holdout.jsonl \
        --answers <模型回答.jsonl> --model-name <模型名>
python3 examples/llm_batch.py export2 --split holdout \
        --raw results/raw/llm_<模型>_holdout.jsonl --out /tmp/batch
# 再回收第二轮
python3 examples/llm_batch.py ingest2 --raw results/raw/llm_<模型>_holdout.jsonl \
        --answers <第二轮回答.jsonl> --model-name <模型名>
python3 -m bench.run_eval --model recorded_llm --model-name <模型名> \
        --raw results/raw/llm_<模型>_holdout.jsonl --split holdout
```

---

## 7. 已知边界

1. **规则链上限为 2 条原语**，不是设计偏好，是可归纳性检查逼出来的结论（3 原语规则在
   8–15 个对抗性示例下仍有多达 9–11 个行为等价类）。代价：题目的复杂度上限较低。
2. **"学习"是窄义的归纳规则学习**，不等于开放域持续学习或在线适应。
3. **人类基线未采集**（§4.2）。
4. **未接入前沿模型 API**，因此本包不发布任何前沿模型分数。
