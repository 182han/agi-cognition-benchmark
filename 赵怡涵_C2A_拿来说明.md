# 拿来说明 · C2A 提案

**作者：** 赵怡涵 ｜ **挑战：** C2A — Track 1 Learning ｜ **日期：** 2026-10-03

> 「拿来主义」不是罗列参考文献，而是说清三件事：**拿了什么、为什么它好用、改了什么**，
> 以及**拿不掉、只能承认的边界**。本文件同时是提案 §2.4 的展开版。

---

## 一、借鉴来源总表（全部经联网核验）

| # | 来源 | 链接 | 核心思想 | 我拿了什么 |
|---|---|---|---|---|
| 1 | Chollet, *On the Measure of Intelligence* (2019) | [arXiv:1911.01547](https://arxiv.org/abs/1911.01547) | 智能 = **技能获取效率**，而非技能本身；提出 ARC | 度量观 + 「任务不得依赖预训练知识」的设计原则 |
| 2 | Lake & Baroni, *Generalization without Systematicity* (SCAN, ICML 2018) | [arXiv:1711.00350](https://arxiv.org/abs/1711.00350) | seq2seq 能拟合训练分布，却在新的原语组合上崩溃 | **系统性泛化的切分方法** → 我的 OOD 题 |
| 3 | Kim & Linzen, *COGS* (EMNLP 2020) | [ACL Anthology](https://aclanthology.org/2020.emnlp-main.731/) | 把泛化失败拆成结构性 / 词汇性两类 | 「零件都见过、组合没见过」这个**可操作**的 OOD 定义 |
| 4 | Srivastava et al., *Beyond the Imitation Game* (BIG-bench, 2022) | [arXiv:2206.04615](https://arxiv.org/abs/2206.04615) | 大规模多任务评估框架；首创 **canary GUID** 约定 | canary 机制（**自造 GUID，不冒用官方字符串**） |
| 5 | Hendrycks et al., *MMLU* (ICLR 2021) | [arXiv:2009.03300](https://arxiv.org/abs/2009.03300) | 57 学科多选题，测**知识广度** | **作反例**：它常被当成能力评估，其实测不到学习。只取工程规范（题目/答案分离、输出标准化） |
| 6 | Chen et al., *Evaluating LLMs Trained on Code* (HumanEval, 2021) | [arXiv:2107.03374](https://arxiv.org/abs/2107.03374) | 164 道题，用单元测试**自动执行**判分 | 「判分必须可自动执行、不靠人/模型当裁判」 |
| 7 | Garg et al., *What Can Transformers Learn In-Context?* (NeurIPS 2022) | [arXiv:2208.01066](https://arxiv.org/abs/2208.01066) | 用**合成函数类**控制 ICL 与记忆的混淆 | 方法论：合成任务 + 已知真函数，才能把「学」与「记」分开 |
| 8 | Tamkin, Handa, Shrestha & Goodman, *Task Ambiguity in Humans and Language Models* (ICLR 2023) | [OpenReview/Semantic Scholar](https://www.semanticscholar.org/paper/e9d6cad994fd48567198ef260fbc5f5241aa9746) | 歧义提示下，模型会**锁定其中一个规则**，人类则会追问或 hedge | **直接催生了「可归纳性关卡」**：歧义不是难度，是效度问题 |
| 9 | Coda-Forno, Binz, Wang & Schulz, *CogBench* (ICML 2024) | [arXiv:2402.18225](https://arxiv.org/abs/2402.18225) | 用 10 个经典心理学实验范式评 LLM | 「用认知科学的实验设计来评 AI」的取向 |
| 10 | Guo, Pleiss, Sun & Weinberger, *On Calibration of Modern Neural Networks* (ICML 2017) | [arXiv:1706.04599](https://arxiv.org/abs/1706.04599) | 定义 **ECE** = Σ (n_b/N)·\|acc(b) − conf(b)\| | ECE 的定义（**仅作辅助指标**，理由见 §三） |
| 11 | Miller, *The Magical Number Seven, Plus or Minus Two* (1956) | [PsycNet](https://psycnet.apa.org/record/1957-02914-001) | 即时记忆容量约 7±2 | 人类基线的先验 |
| 12 | Cowan, *The magical number 4 in short-term memory* (2001) | [Cambridge Core](https://www.cambridge.org/core/journals/behavioral-and-brain-sciences/article/magical-number-4-in-shortterm-memory-a-reconsideration-of-mental-storage-capacity/44023F1147D4A1D44BDC0AD226838496) | 控制复述后纯存储约 4 chunk | **示例数 3–7（设计目标 5）+ 两条规则**的负荷设计依据 |
| 13 | Google DeepMind, *Measuring Progress Toward AGI: A Cognitive Framework* | [Blog](https://blog.google/innovation-and-ai/models-and-research/google-deepmind/measuring-agi-cognitive-framework/) | 10 项认知能力分类法 + 三阶段评估协议 | 赛道划分与「AI 表现要放进人类分布里读」的取向 |

---

## 二、核验记录（**这一步救了提案**）

我并不假设自己记得的引用是对的，而是让一个独立子任务去**联网逐条核查** 15 项文献的
「标题 / 作者 / 年份 / 会议或 arXiv 编号 / URL / 一句话主张」，并逐条打
`已核验 / 部分核验 / 未核验` 标签。结果有两条**必须纠正**、一条**必须降级**：

| 我原本要写的 | 核验结果 | 处理 |
|---|---|---|
| "Beyond the **Imprint**: BIG-Bench" | **不存在**。真名是 *Beyond the **Imitation Game**...*（arXiv:2206.04615） | 改正标题；canary 机制的 hex 字符串**无法逐字确认**，故**不引用官方 hex**，改用本基准自造 GUID |
| "**Ambiguity in In-Context Learning**" | **不存在**这个标题。真正相关的是 Tamkin et al. 的 *Task Ambiguity in Humans and Language Models*（ICLR 2023） | 换成真实存在的这一篇；其 arXiv 编号来自镜像、未完全确认，故只给 Semantic Scholar 链接 |
| DeepMind 认知框架「2026 年，arXiv:2605.28405」 | 框架**真实存在**（Google 博客 + Semantic Scholar 可查），但 **2026 这个日期与 arXiv 编号只有弱证据**，原始发布是 2025 年 | **降级**：只写 2025–2026 + 博客链接，**不写那个 arXiv 编号** |

另外确认存在但本次未采用的：MMLU-Pro（arXiv:2406.01574）、GPQA（arXiv:2311.12022）、
BIG-Bench Hard（arXiv:2210.09261）、Kadavath et al. *Language Models (Mostly) Know What
They Know*（arXiv:2207.05221）、Self-Refine（arXiv:2303.17651）、Reflexion
（arXiv:2303.11366）、ARC-AGI-2（arXiv:2505.11831）。

> **方法学边界（必须写明）**：核验依靠联网检索结果的交叉比对，**没有逐篇打开原文页面**。
> 被标为「部分核验」的字段（见上表第三行）在正式引用前应再打开链接确认一次。**未核验的
> 条目一律没有进入提案的参考文献列表。**

---

## 三、拿不来的部分（以及为什么）

| 来源 | 他们做了什么 | 我不要 | 原因 |
|---|---|---|---|
| ARC | 视觉网格（2D 彩色网格变换） | 去掉视觉格式，改符号序列 | 网格难程序化生成**海量**新题，且精确匹配容错极低；符号序列可无限生成、可精确评分 |
| ARC-AGI-2 / 3 | 大规模人类标定面板、交互式 agent 环境 | 不做交互式环境 | 一周内无法落地；只保留「反馈后是否改进」这一个核心机制 |
| SCAN | 固定命令→动作映射规则集 | 去掉固定规则集 | 固定规则集有训练数据泄漏风险（LLM 可能已"见过"SCAN） |
| COGS | 自然语言句子 → 逻辑式 | 不用自然语言输入 | 自然语言会引入语言理解能力，**污染"学习"这个目标能力**；符号序列把语言因素剥掉 |
| MMLU | 知识广度多选题 | 不做知识题 | 知识题测的是记忆与知识覆盖，与"从经验中学习"是两件事 |
| BIG-bench | 204 个人工撰写任务 | 不写人工任务 | 人工任务无法规模化，也无法做 holdout 种子承诺 |
| HumanEval | 代码生成 + 单元测试执行 | 不做代码任务 | 代码能力会引入编程先验；且执行环境有安全面 |
| CogBench | 心理学实验范式的行为对齐 | 不做行为对齐研究 | 目标是**能力测量**不是**行为相似性**；两者会被混淆 |
| Guo et al. ECE | 校准误差作为主指标之一 | **ECE 只作辅助指标** | 元认知/置信度校准属于 Track 2。放进 Track 1 会违反「一个 benchmark 只测一个能力」；这里只把它当**辅助诊断**，用来区分"答对是知道还是蒙的"，并在结果里明确标注**不是本基准的主张** |

---

## 四、我的改进（相对每个来源）

### 改进 1：把「题目是否良定义」变成机械门槛（核心改进）

- **现有做法的问题**：ARC 靠人工设计、SCAN/COGS 用固定切分，**没有任何一个 benchmark
  检查过「给定这组示例，标准答案是不是唯一的」**。Tamkin et al. 证明了这个问题的现实性
  （模型会锁死在一个规则上，而这个规则可能不是出题人想的那个），但没有给出评测侧的解法。
- **我的做法**：① 用「一步对抗委员会」（恒等 + 全部单原语 + 全部"条件包一个原语"，
  约 1700 条）做 query-by-committee 主动选题；② 用真实候选集合迭代劈分；③ **终局关卡**：
  在**真正会被打分的那批输入**上统计候选规则的行为等价类数，**> 1 就整题作废、换种子重造**。
- **效果**：每一道出现在数据集里的题目，都能被证明是唯一可归纳的（`bench/selfcheck.py`
  的 S5 项会复核这一点）。**这是本方案区别于已有 benchmark 的最主要一点。**

### 改进 2：把 KSTAR 的 ΔR 做成可测的两轮协议

- **现有做法的问题**：几乎全部 benchmark 只测一次表现（snapshot）。ARC-AGI-3 引入了交互式
  学习，但代价是需要完整 agent 环境。
- **我的做法**：轻量两轮协议——Round 2 把模型自己在 Round 1 的答案、判对判错、以及正确答案
  一起回灌，再问同一宇宙的新题。**关键是 C 组题目的挑选方式**：用「真规则与最像它的错规则
  分歧最大」的输入做判别性探针。一个只把反馈当成"再来一个示例"的模型会在这里再错一次。
- **效果**：`FeedbackGain`、`RevisionRate`、`OvercorrectionRate` 三个指标互相制衡，
  共同给出「ΔR 有没有真的回流去更新 K」的证据。

### 改进 3：三重对照集，把「学到了」与「抄到了」拆开

- **现有做法的问题**：分数是混合的。抄输入能拿多少分，通常没人报。
- **我的做法**：同时生成 `control_corrupt`（示例输出随机置换）与 `perturb`（符号整体重命名 +
  示例乱序），再加 `copy_input`、`frequent_support_output` 两个确定性基线。
- **效果**：`perturb` 在参考解上**必须**仍是 1.0（作为评分器的自检）；`control_corrupt`
  上归纳解题器的正确率**必须**塌向随机（证明它确实在从示例学，而不是从别处泄漏）。

### 改进 4：holdout 种子「先承诺后生成」

- **现有做法的问题**：公开 benchmark 的题目一旦发布，就能被针对性训练。
- **我的做法**：holdout 的随机种子在**生成之前**就把 SHA-256 写进仓库
  （`data/holdout_seed_commitment.json`），生成之后才公开种子供复现。
- **效果**：承诺哈希与公开种子一致，就证明这套题没有根据结果挑过。**这是可验证的**，
  不是一句承诺。

---

## 五、明确不拿的东西

- **不拿官方的 canary hex 字符串**（未逐字确认，冒用等于伪造出处）；
- **不拿任何未核实的引用**；
- **不拿任何我没跑过的模型分数**（`bench/models/__init__.py` 里的 `is_frontier_model`
  字段由代码强制标注，`tests/test_smoke.py` 会检查 LLM 分数是否有逐题原始记录）；
- **不拿 starter 示例提案的设计**（只借鉴了它的命名规范与交付结构，设计与实现全部独立）。
