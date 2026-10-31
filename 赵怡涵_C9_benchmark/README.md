# ΔR-Bench · 少样本规则归纳与反馈修正基准

**ΔR-Bench: Measuring Genuine Learning, Not Recall**

| 项目 | 内容 |
|---|---|
| 赛道 | Track 1 — **Learning**（学习） |
| 作者 | 赵怡涵 ｜ 2026-10-03 ｜ v1.0 |
| 任务说明（输入/输出/评分/指标） | [`../赵怡涵_C9_task说明.md`](../赵怡涵_C9_task说明.md) |
| 测试结果（真实数字） | [`../赵怡涵_C9_测试结果.md`](../赵怡涵_C9_测试结果.md) |
| 上层交付包 | [`../README.md`](../README.md) |
| 授权 | MIT（见 [`LICENSE`](LICENSE)） |

---

## 🎯 一、这是什么 / 解决什么问题

> **一句话**：一个**会拒绝出题**的 benchmark —— 只有当一组示例能**唯一确定**隐藏规则时，
> 这道题才被采纳；否则整题作废、换种子重造。
>
> 它测的是**归纳**（从少量示例真正学到一条它从未见过的规则），不是**回忆**
> （答案在世界任何语料里都不存在，因为符号表自造、规则程序生成）。

现有"学习评估"的分数里混着四种与学习无关的东西：**记忆**、**抄输入**、**表面拟合**、
**欠定**（示例不足以唯一确定规则，"标准答案"只是出题人的偏好）。前三条众所周知；
第四条几乎没人正面处理，而它最致命——含 30% 欠定题的基准，分数解释力上限只有 70%。

**本基准的边界（不遮掩）**：这里的"学习"是**窄义的归纳规则学习**（从示例归纳程序性规则
并依据反馈修正），**不等于**开放域持续学习或在线适应。规则链上限为 2 条原语，不是设计
偏好，而是可归纳性检查逼出来的结论（见 [`docs/可归纳性试点.md`](docs/可归纳性试点.md)）。

---

## ✅ 二、Demo / 演示入口

| 入口 | 位置 | 说明 |
|---|---|---|
| **一条命令复现全部** | `bash scripts/reproduce.sh` | 生成器确定性 → 全部解题器 → 审计 → 自检 → 汇总榜 |
| 快速跑（跳过最重的解题器） | `bash scripts/reproduce.sh --fast` | 约 1 分钟 |
| **看一道题长什么样** | `data/tasks_dev.jsonl` 的 `prompt` 字段 | 公开规则语法 + 3–7 条标注示例 + 待答查询 |
| **结果汇总榜** | [`results/leaderboard.md`](results/leaderboard.md) | 由 `reproduce.sh` 自动生成，不由手工填写 |
| 防污染/防作弊报告（A1–A7） | [`docs/防作弊报告.md`](docs/防作弊报告.md) | 每项都有实测值与阈值 |
| 可归纳性试点（为什么上限是 2） | [`docs/可归纳性试点.md`](docs/可归纳性试点.md) | 真实等价类分布 |
| 逐题原始回答留痕 | [`results/raw/`](results/raw/) | 任何 LLM 分数都必须能追溯到逐题原文 |

**三分钟上手**（在 `赵怡涵_C9_benchmark/` 下）：

```bash
python3 - <<'PY'
import json
T=[json.loads(l) for l in open('data/tasks_dev.jsonl',encoding='utf-8') if l.strip() and not l.startswith('#')]
print([t for t in T if t['phase']=='B'][0]['prompt'])   # 看一道 Phase B 题
PY
```

---

## ✅ 三、Quick Start（≤5 行，复制即跑）

```bash
cd 赵怡涵_C9_benchmark
bash scripts/reproduce.sh --fast                    # ① 约 1 分钟：审计 + 自检 + 基线
python3 -m bench.selfcheck --split dev              # ② 基准自检（含 S5 可归纳性复核）
python3 -m bench.run_eval --model search --split dev --max-len 2 --beam 160   # ③ 本包方法（约 1 分钟）
bash scripts/reproduce.sh                           # ④ 完整复现（dev + holdout，约 10–15 分钟）
```

**无需联网、无需 API key、无需 GPU、无需 `pip install`**（只用 Python ≥ 3.7 标准库）。

---

## 📊 四、效果数据（全部为本机真实运行，可复算）

`n = 84 题/分片`（12 个规则宇宙 × 7 题；Phase A 24 / B 36 / C 24）。

| 系统 | 分片 | acc | A（无示例） | B（归纳） | C（反馈修正） | 抄输入率 | LearningGain |
|---|---|---|---|---|---|---|---|
| `reference_oracle`（全知参考解，校准线） | dev / holdout | **1.0000** | 1.0000 | 1.0000 | 1.0000 | 0.17 / 0.25 | 0 |
| `search_solver`（**本包方法**：假设空间 beam search） | dev | **0.7857** | 0.2500 | 1.0000 | 1.0000 | 0.3810 | +0.7500 |
| `search_solver` | holdout | **0.7619** | 0.1667 | 1.0000 | 1.0000 | 0.4881 | +0.8333 |
| `deepseek-v4-flash`（真实 LLM，**非前沿模型**） | holdout | **0.7976** | 0.3333 | 1.0000 | 0.9583 | 0.4762 | +0.6667 |
| `proxy_bounded_search`（人类难度**代理**，非人类数据） | dev / holdout | 0.4048 / 0.4167 | 0.25 / 0.17 | 0.4167 / 0.5000 | 0.5417 / 0.5417 | 0.76 / 0.83 | +0.17 / +0.33 |
| `baseline_copy_input`（抄输入） | dev / holdout | 0.1667 / 0.2500 | 0.25 / 0.17 | 0.0556 / 0.3056 | 0.2500 / 0.2500 | **1.00** | −0.19 / +0.14 |
| `baseline_frequent_support_output`（众数） | dev / holdout | 0.0714 / 0.0476 | 0.25 / 0.17 | 0 / 0 | 0 / 0 | 0.2857 | −0.25 / −0.17 |
| `baseline_random`（随机） | dev / holdout | 0.0714 / 0.0476 | 0.25 / 0.17 | 0 / 0 | 0 / 0 | 0.2857 | −0.25 / −0.17 |

**对照与扰动集**（证明"确实在从示例学"，而不是"答案能从别处拿到"）：

| 对照 | 实测 | 期望 |
|---|---|---|
| `search_solver` @ `control_corrupt`（示例输出被打乱） | dev 0.1786 ／ holdout **0.2738** | 必须塌向随机（正常集 0.7857 / 0.7619） |
| `reference_oracle` @ `perturb`（符号重命名 + 示例乱序） | dev 1.0000 ／ holdout **1.0000** | 必须仍是 1.0（评分器自检） |

> **这里没有任何前沿模型的分数**：本机无可用 API key、`/tmp/ollama` 不存在、11434 端口
> connection refused，**从未联网调用过任何前沿模型**。适配器已实现，拿到 key 后一条命令复跑。
> `is_frontier_model` 字段由**代码**填写，不由人手工标注。
> 完整说明与结论边界见 [`../赵怡涵_C9_测试结果.md`](../赵怡涵_C9_测试结果.md)。

### 关键指标定义

| 指标 | 定义 | 怎么读 |
|---|---|---|
| `acc_phase_A/B/C` | 三阶段正确率 | A 是先验/抄输入天花板，B 是归纳，C 是 ΔR 回流后的修正 |
| `LearningGain_B_minus_A` | `acc_B − acc_A` | 示例带来了多少（须对照 `copy_input` 的 A 阶段分数读） |
| `FeedbackGain_C_minus_B` | `acc_C − acc_B` | 反馈带来了多少 |
| `copy_input_rate` | 答案恰等于查询输入的比例 | **免费分**的天花板，必须单列 |
| `acc_id` / `acc_ood` | 分布内 / 组合新异 | OOD = 零件都见过、组合没见过（SCAN/COGS 意义） |
| `parse_failure_rate` | 规范化失败比例 | 格式问题，**不计入错误率**，避免效度污染 |
| `ECE` | 期望校准误差 | **辅助指标**（属 Track 2 元认知），不单独作分数 |

---

## 🧪 五、验证（真实终端输出）

```bash
bash scripts/reproduce.sh
```

关键步骤的真实输出（2026-10-03 本机 macOS arm64 / Python 3.9.6）：

```
 [2/8] 生成器确定性（mini 数据集，同 seed 生成两次，字节比对）
  tasks 第一次 : daea149d3645de76517f43121eeea751ffe600734988c6a8fe180f3240fafb04
  tasks 第二次 : daea149d3645de76517f43121eeea751ffe600734988c6a8fe180f3240fafb04
  keys  第一次 : 688dcf8d0460bd9bf2d982f747244175cee826e203d580106739c40f132cb7e1
  keys  第二次 : 688dcf8d0460bd9bf2d982f747244175cee826e203d580106739c40f132cb7e1
  ✅ 两次生成字节完全一致 —— 生成器是确定性的

 [3/8] 数据集完整性
  ✅ dev      题量=84  宇宙=12  阶段={'A': 24, 'B': 36, 'C': 24}
  ✅ holdout  题量=84  宇宙=12  阶段={'A': 24, 'B': 36, 'C': 24}

 [6/8] 汇总榜（**在检查之前生成**）
 [7/8] 防污染 / 防作弊审计 → 合计：7/7 通过

 [8/8] 基准自检
  ✅ [S2] 答案 key 可独立核验        84 题全部通过（rule_text→结构→重施→等于 answer）
  ✅ [S4] 参考解满分                  dev=1.0000  holdout=1.0000
  ✅ [S5a] 被判分的输入全部唯一确定（硬门槛）  12 个宇宙全部通过（最大等价类=1）
  ℹ️  [S5b] 更大探针集上的歧义（诊断量，不设门槛）: dev 3/12、holdout 2/12 个宇宙，
         分歧只出现在**从未被问过**的输入上，不影响判分公平
  ✅ [S7] 控制集退化                  正常=0.7857 控制=0.1786 降幅=0.6071
```

> 上表数字全部来自真实运行，可由任何人重跑复算；防作弊报告的完整七项表格见
> [`docs/防作弊报告.md`](docs/防作弊报告.md)，逐题明细见 [`results/`](results/)。
>
> **审计抓出过的真问题**（记录在案，不是"一次就绿"）：A2 首次报 18/84 条"泄漏"，实为
> 假阳性（恒等题把 QUERY 行本身算进去了）；A7 首次报参考解 2.4%，是真 bug（重命名映射
> 只在评分后应用）。两者的修法见 [`docs/防作弊报告.md`](docs/防作弊报告.md) 末节。

---

## 📁 六、项目结构

```
赵怡涵_C9_benchmark/
├── README.md                  ← 本文件
├── LICENSE                    ← MIT
├── requirements.txt           ← 刻意为空：只用标准库
├── CHANGELOG.md               ← 真实开发过程（D1–D5，含被证据逼出来的改动）
├── canary.txt                 ← 自造 canary GUID（BIG-bench 约定）
├── bench/                     ← 基准实现
│   ├── rules.py               ← 规则引擎：7 类原语 + 4 类谓词 + rule_text 反向解析器
│   ├── hypothesis.py          ← 假设空间：行为裁剪 / beam 搜索 / 等价类统计 / 主动选题
│   ├── generate.py            ← 数据集生成器（A/B/C、ID/OOD、控制集、holdout 承诺）
│   ├── scoring.py             ← 规范化 + 精确匹配 + 指标 + ECE
│   ├── run_eval.py            ← 两轮评测运行器（Round 2 反馈构造写死在代码里）
│   ├── contamination.py       ← A1–A7 防污染/防作弊审计
│   ├── selfcheck.py           ← S1–S7 基准自检（含可归纳性复核）
│   ├── pilot_identifiability.py ← 可归纳性试点（规则链上限的证据）
│   └── models/__init__.py     ← 8 个适配器（共用同一接口，跑同一套题与评分）
├── data/                      ← 题目（只有 support / query / prompt）+ manifest + 控制/扰动集
├── keys/                      ← 答案（**与 data/ 物理分离**，评测时才 join）
├── results/                   ← 每个适配器的 *_scores.json 与 *_predictions.jsonl + raw/ 逐题原文
├── examples/llm_batch.py      ← 批次导出/回收（让「模型只看到 prompt」成为结构性事实）
├── scripts/reproduce.sh       ← 一条命令复现
├── tests/test_smoke.py        ← 基准冒烟测试（29 项）
└── docs/                      ← 防作弊报告、可归纳性试点
```

---

## 🔧 七、技术栈

| 项目 | 选择 | 理由 |
|---|---|---|
| 语言/依赖 | **Python ≥ 3.7，纯标准库** | 复现者零安装成本；没有 `pip install` 失败面 |
| 任务形式 | 符号序列变换 | 可无限程序化生成；精确匹配判分，无需 LLM-as-judge；不引入视觉/语言能力，保护"学习"的纯度 |
| 符号表 | 16 个自造双字母音节中随机取 5–6 个 | 自然语料里几乎不出现，压低预训练先验；纯 ASCII |
| 判分 | 精确匹配（含规范化） | 没有人为权重、没有额外噪声；规范化失败单列 |
| 随机性 | 全部 seeded RNG | 同 seed 生成字节一致，复现是硬要求 |
| 运行时间 | 全量复现约 10–15 分钟（单机 CPU） | 最重的是 `search` 解题器与 `control_corrupt`（约 1–2 分钟/分片） |

---

## 🤖 八、AI 生成说明（诚实披露）

- **全流程 AI 辅助**（AI-First 原则）：论文精读、方案构思、代码编写、文档撰写均由
  DeepSeek Harness 内的编码智能体（`deepseek-v4-flash`）配合人工判断完成。
  **人的关键决策 6 个**（验证器先于生成器、委员会定义、难度上限降为 2、终局关卡改为验证
  "被打分的输入"、四基线+两对照集、LLM 批次的结构性隔离），**明确驳回 AI 建议 4 次**，
  **AI 最大的误导**（把指标异常解释成"任务更难"而非"检查写错了"）逐条记录在
  [`../赵怡涵_C9_AI日志.md`](../赵怡涵_C9_AI日志.md)（10 个决策节点）。
- 本仓库**没有**任何伪造的模型分数、人类数据或 Kaggle 提交；**没有**接入过前沿模型 API。

## 🙏 九、借鉴来源（拿来主义）

| 来源 | 拿了什么 | 用在哪 |
|---|---|---|
| Chollet (2019) *On the Measure of Intelligence* | "智能 = 技能获取效率"；任务不得依赖预训练知识 | 自造符号 + 程序化生成的设计前提 |
| Lake & Baroni (2018) SCAN ／ Kim & Linzen (2020) COGS | 系统性泛化的切分思想与"零件熟、组合生"的操作定义 | `generate.py::choose_queries` 的 OOD 划分 |
| Srivastava et al. (2022) BIG-bench | canary GUID 约定 | `canary.txt`（**自造 GUID**，不冒用官方 hex） |
| Hendrycks et al. (2021) MMLU | 题目/答案分离、输出标准化等工程规范 | `data/` 与 `keys/` 物理分目录、`parse_answer` |
| Chen et al. (2021) HumanEval | 判分必须自动执行，不靠模型当裁判 | 精确匹配判分 |
| Garg et al. (2022) | 合成任务 + 已知真函数，把"学"与"记"分开 | 真规则对解题器不可见的接口设计 |
| Tamkin et al. (2023) *Task Ambiguity in Humans and Language Models* | 歧义提示会让模型锁死在一个规则上 | `ambiguity_report` 的**存在理由** |
| Coda-Forno et al. (2024) CogBench | 用认知科学范式评 AI | 三阶段协议（先验/归纳/反馈修正） |
| 主动学习 query-by-committee | 主动选题 | 换用途：不是省标注，而是**保效度** |
| 机器学习实验规范 | holdout + pre-registration | `data/holdout_seed_commitment.json`（先承诺后生成） |

**自己长出来的部分**（未找到现成做法可抄）：可归纳性关卡（会拒绝出题的机械门槛）、
判别性探针（Phase C 题目的来源）、`rule_text` 反向解析器、七项自动审计 A1–A7 与自检 S1–S7。
逐条取舍见 [`../赵怡涵_C9_拿来说明.md`](../赵怡涵_C9_拿来说明.md)。

## 📄 十、License

代码与数据：**MIT**（见 [`LICENSE`](LICENSE)）。引用文献版权归各原作者，仅作学术引用。
