# C2A 提案：ΔR-Bench —— 少样本规则归纳与反馈修正基准

**ΔR-Bench: Measuring Genuine Learning, Not Recall**

| 项目 | 内容 |
|---|---|
| **赛道** | Track 1 — Learning（学习） |
| **作者** | 赵怡涵 ｜ **日期** 2026-10-03 ｜ **版本** v1（首版，按群内反馈迭代 v2/v3） |
| **状态** | 提案 + **可运行原型**：`赵怡涵_C9_benchmark/`，84 题/分片，`bash scripts/reproduce.sh` 一条命令跑通 |

> 四部分配比：赛道与动机 ≈20%、Benchmark 设计 ≈40%、人类基线 ≈20%、创新与可行性 ≈20%。
> 全流程 AI 辅助，决策节点见 `赵怡涵_C2A_AI日志.md`，借鉴来源见 `赵怡涵_C2A_拿来说明.md`。

---

## 一、赛道选择与动机（≈20%）

我选 Track 1 — Learning，因为它是唯一一个**连"测到了什么"都还没解决**的能力。

现有学习评估的分数里混着四种与学习无关的东西：**记忆**（答案可能在预训练语料里）、
**抄输入**（原样输出就能拿分）、**表面拟合**（示例全拟合、换个合法组合就崩，SCAN 与 COGS 反复
证明过）、**欠定**（示例不足以唯一确定规则，标准答案只是出题人偏好）。前三条众所周知，第四条
几乎没人正面处理，**而它最致命：含 30% 欠定题的基准，分数解释力上限只有 70%。**

KSTAR 映射很直接：闭环里藏着**两个不同的"学"**——从示例建立 K，以及拿到 ΔR 后修正 K。
绝大多数 benchmark 只测第一次，本方案把两次分开测。

---

## 二、Benchmark 设计思路（≈40%）

### 2.1 题面：程序化生成的"规则宇宙"

每题来自一个新造的规则宇宙：自造符号表（`ka ro mi tu ve`）+ 一条隐藏变换规则，由 7 类原语
组合而成：`sub(a,b)` `del(a)` `dup(a)` `swap(a,b)` `rev()` `rot(k)` 与条件原语 `if[P]{X}`
（P ∈ `contains`/`count≥n`/`len≥n`/`head=`）。**规则链长度 1–2 条，上限在题面里明确告知。**

它能隔离"学习"：自造音节压低预训练先验；每次生成都是新符号表加新映射，**答案在任何语料里都
不存在**；规则空间公开，"猜出题人想什么"被堵死，只剩归纳；精确匹配判分，不需要 LLM-as-judge，
也就没有评分器噪声。

### 2.2 三阶段协议：把 ΔR 变成可测的两轮交互

| 阶段 | 给什么 | 测什么 | KSTAR |
|---|---|---|---|
| **A** | 不给示例 | 先验 / 抄输入天花板 | K₀ |
| **B** | 3–7 个标注示例（实测；设计目标 5） | 从示例建立 K | 示例→K |
| **C** | 回灌"你自己在 B 的答案 + 正确答案"，再问同宇宙新题 | ΔR 是否真的回流更新 K | A→R→ΔR→K |

C 的题不是随便挑的，而是**判别性探针**：枚举所有与示例一致的候选规则，挑出让真规则与最像它
的错规则分歧最大的输入。**只把反馈当成"再来一个示例"、不修正假设的模型会再错一次**——这就是
ΔR 的可观测证据。指标各有可证伪解释：`LearningGain = acc_B − acc_A`、
`FeedbackGain = acc_C − acc_B`、`RevisionRate`、`GeneralizationGap`。

### 2.3 四个效度威胁，四条对症机制

**① 污染 → 程序化生成 + 先承诺后生成的 holdout。** holdout 的种子在**生成之前**就把 SHA-256
写进仓库，之后才公开：哈希对得上，就证明这套题没根据结果挑过。数据带 canary GUID
（沿用 BIG-bench 约定，用自造 GUID）。

**② 欠定 → query-by-committee 选题 + 终局可归纳性关卡。** 先用「一步对抗委员会」（恒等 + 全部
单原语 + 全部"条件包一个原语"，约 1700 条）贪心选题；再用真实候选集迭代劈分；**最后一道关卡在真正会被打分的输入上统计候选规则的行为等价类数，
>1 就整题作废、换种子重造。** 第一版只在随机探针上验唯一性，而考核用的是对抗探针，解题器 B 阶段 100%、C 阶段掉分；
修掉这个"验证分布 ≠ 考核分布"的漏洞后，题目才真正良定义。

**③ 表面拟合 → SCAN/COGS 式系统性泛化题。** 每个宇宙至少 2 道 OOD 题：每个"零件"（符号子集、
长度、条件分支取值）都在示例里出现过，但这个**组合**没有；规则完全由示例确定。

**④ 抄输入与退化 → 三重对照集 + 基线。** 同时生成 `control_corrupt`（示例输出随机置换，正确率
应塌向随机）与 `perturb`（符号重命名加示例乱序，正确率须不变），再加 `copy_input`、
`frequent_support_output` 两个确定性基线，把"学到了"与"抄到了"分开报。

### 2.4 设计灵感

**ARC** 拿"智能 = 技能获取效率"，去掉视觉网格；**SCAN / COGS** 拿系统性泛化的切分法；
**BIG-bench** 拿 canary 机制；**MMLU** 作反例（测知识广度、测不到学习），只取工程规范；
**Tamkin et al. 2023** 催生了可归纳性关卡。逐条取舍见拿来说明。

---

## 三、人类基线考量（≈20%）

### 3.1 预期分布与依据

| 难度 | 规则链 | 预期人类正确率 | 依据 |
|---|---|---|---|
| easy | 1 条原语 | 85–95% | 单条映射/删除，负荷约 2–3 chunk |
| medium | 2 条（无条件） | 55–75% | 需同时保持两条规则并按序施加 |
| hard | 2 条（含条件分支） | 35–55% | 分支额外需要抑制"无条件执行"的默认反应 |
| OOD（各档内） | — | 比同档 ID 低 15–25 个百分点 | 需组合外推，而非套用记下的映射 |

依据来自工作记忆容量文献（Miller 1956 的 7±2；Cowan 2001 修正为约 4 chunk）：示例数、1–2 条
规则、外加一个查询，负荷正压在容量边界附近——有区分度但不全军覆没。

### 3.2 区分度设计

**防过易**：出题时把"抄输入可得率"压到 35% 以下（holdout 实测 **0.2500**）。**防过难**：hard 档
不靠加长规则链（见 §4.3），靠条件分支与 OOD 占比。**难度可验伪**：受限搜索器（beam=6）作为人类
难度**代理**，实测梯度 easy **0.8929** / medium **0.0571** / hard **0.3333**——**不是人类数据**，
只是可被真人实验推翻的预测。

### 3.3 协议与它的诚实边界

计划 n = 30 名成人（按"有/无逻辑训练"分层各半），界面与原提示词逐字一致，单题计时并记录自答置信度，每人 30 题。

**边界**：n=30 便利样本**不具备人口统计学代表性**，是 DeepMind 三步协议第二步的**降级版**；足以
判断"对人类是否可解/是否过难"，不足以支撑"AI 已达人类中位水平"。真人数据**尚未采集**，包内标记
`【待赵怡涵执行】`，涉及人类的现有数字一律来自模拟器并逐处标注。

---

## 四、预期创新点与可行性（≈20%）

### 4.1 创新点

| 现有做法的局限 | ΔR-Bench |
|---|---|
| few-shot 题排除不了记忆 | 程序化生成 + holdout 种子先承诺后生成 + canary |
| 只测一次表现（snapshot） | 两轮协议，专测 ΔR 回流后的修正 |
| 不检查题目是否良定义 | **可归纳性关卡**：等价类 >1 的题一律作废重造 |
| 示例随机抽（可能很含糊） | query-by-committee 主动选题 |
| OOD 靠换数据集 | 同宇宙内构造"零件都见过、组合没见过"的题 |
| 分数里混着抄输入 | 内置 copy_input / control_corrupt / perturb 三重对照 |

**最核心的一条**：把"这道题是否良定义"从自我声明变成会**拒绝出题**的机械门槛。实测 dev 分片
21 次尝试中，4 次因规则退化、4 次因示例不足以唯一确定规则、1 次因 beam 未覆盖真规则被拒
——**数字本身就是证据**。

### 4.2 可行性：一周内已落地

不需要 GPU、API key 或采数据，纯 Python 标准库，单机可跑。当前状态（**已实现，非计划**）：
84 题 / 12 宇宙 / 3 难度档，A/B/C 齐全；生成器确定性可复现（同 seed 两次字节一致）；答案可
**独立核验**（规则文本反解回结构、重施到查询须等于答案）；已实测基线与解题器，见
`赵怡涵_C9_测试结果.md`。

### 4.3 风险与边界（不遮掩）

1. 原设计把 hard 定为"3 条原语"。可归纳性检查显示：8 个对抗性示例下，3 原语规则在探针集上仍有
   大量等价类；加到 12 个示例后仍约 1/5 不可判别。这是数学问题不是调参问题，**故上限降为 2 条**。
2. 这里的"学习"是**窄义的归纳规则学习**，不等于开放域持续学习。
3. 人类基线尚未采集（§3.3）。
4. 前沿模型 API 未接入（本机无可用本地大模型、无 API key）。适配器已实现，拿到 key 后一条
   命令复跑；**接入之前本包不发布任何前沿模型分数**。

---

## 参考文献

1. Chollet, F. (2019). *On the Measure of Intelligence.* arXiv:1911.01547.
2. Lake, B. M., & Baroni, M. (2018). *Generalization without Systematicity.* ICML 2018. arXiv:1711.00350.
3. Kim, N., & Linzen, T. (2020). *COGS: A Compositional Generalization Challenge Based on Semantic Interpretation.* EMNLP 2020.
4. Srivastava, A. et al. (2022). *Beyond the Imitation Game: Quantifying and extrapolating the capabilities of language models.* arXiv:2206.04615.
5. Hendrycks, D. et al. (2021). *Measuring Massive Multitask Language Understanding.* ICLR 2021. arXiv:2009.03300.
6. Chen, M. et al. (2021). *Evaluating Large Language Models Trained on Code.* arXiv:2107.03374.
7. Garg, S., Tsipras, D., Liang, P., & Valiant, G. (2022). *What Can Transformers Learn In-Context? A Case Study of Simple Function Classes.* NeurIPS 2022. arXiv:2208.01066.
8. Tamkin, A., Handa, K., Shrestha, V., & Goodman, N. (2023). *Task Ambiguity in Humans and Language Models.* ICLR 2023.
9. Coda-Forno, J., Binz, M., Wang, J. X., & Schulz, E. (2024). *CogBench: a large language model walks into a psychology lab.* ICML 2024. arXiv:2402.18225.
10. Guo, C., Pleiss, G., Sun, Y., & Weinberger, K. Q. (2017). *On Calibration of Modern Neural Networks.* ICML 2017. arXiv:1706.04599.
11. Miller, G. A. (1956). *The Magical Number Seven, Plus or Minus Two.* Psychological Review 63(2), 81–97.
12. Cowan, N. (2001). *The magical number 4 in short-term memory.* Behavioral and Brain Sciences 24(1), 87–114.
13. Google DeepMind. *Measuring Progress Toward AGI: A Cognitive Framework.* <https://blog.google/innovation-and-ai/models-and-research/google-deepmind/measuring-agi-cognitive-framework/>

> 引用核验说明：以上条目逐条联网核查过存在性与元数据；核验过程与未能完全确认的字段
> （DeepMind 框架的日期与 arXiv 编号）记在 `赵怡涵_C2A_拿来说明.md`「核验记录」一节。
> 未核实的条目一律不入引用。
