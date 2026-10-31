# ΔR-Bench 结果汇总（由 scripts/reproduce.sh 自动生成）

> `前沿模型` 一列由代码（`Adapter.is_frontier_model`）填写，不由人手工标注。
> 本表中**没有任何前沿模型分数**——详见 `赵怡涵_C9_测试结果.md` 的说明。
> **作废的评测运行不进本表、不参与排序或对照**，单独列在文末。

| 适配器 | 类型 | 前沿模型 | 题组 | acc | A | B | C | LearningGain | FeedbackGain | ID | OOD | 抄输入率 | 解析失败率 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `reference_oracle` | reference | **否** | dev/tasks | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.167 | 0.000 |
| `reference_oracle` | reference | **否** | holdout/tasks | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.250 | 0.000 |
| `reference_oracle` | reference | **否** | dev/perturb | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.167 | 0.000 |
| `reference_oracle` | reference | **否** | holdout/perturb | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.250 | 0.000 |
| `search_solver` | inductive | **否** | dev/tasks | 0.786 | 0.250 | 1.000 | 1.000 | 0.750 | 0.000 | 0.500 | 1.000 | 0.381 | 0.000 |
| `search_solver` | inductive | **否** | holdout/tasks | 0.762 | 0.167 | 1.000 | 1.000 | 0.833 | 0.000 | 0.444 | 1.000 | 0.488 | 0.000 |
| `proxy_bounded_search` | inductive | **否** | holdout/tasks | 0.417 | 0.167 | 0.500 | 0.542 | 0.333 | 0.042 | 0.250 | 0.542 | 0.833 | 0.000 |
| `proxy_bounded_search` | inductive | **否** | dev/tasks | 0.405 | 0.250 | 0.417 | 0.542 | 0.167 | 0.125 | 0.306 | 0.417 | 0.762 | 0.000 |
| `search_solver` | inductive | **否** | holdout/control_corrupt | 0.274 | 0.167 | 0.306 | 0.333 | 0.139 | 0.028 | 0.139 | 0.417 | 0.976 | 0.000 |
| `baseline_copy_input` | baseline | **否** | holdout/tasks | 0.250 | 0.167 | 0.306 | 0.250 | 0.139 | -0.056 | 0.139 | 0.417 | 1.000 | 0.000 |
| `search_solver` | inductive | **否** | dev/control_corrupt | 0.179 | 0.250 | 0.083 | 0.250 | -0.167 | 0.167 | 0.194 | 0.083 | 0.988 | 0.000 |
| `baseline_copy_input` | baseline | **否** | dev/tasks | 0.167 | 0.250 | 0.056 | 0.250 | -0.194 | 0.194 | 0.194 | 0.042 | 1.000 | 0.000 |
| `llm_qwen3-4b-q4km` | llm | **否** | holdout/tasks | 0.107 | 0.042 | 0.167 | 0.083 | 0.125 | -0.083 | 0.083 | 0.167 | 0.131 | 0.000 |
| `llm_gemma4-e2b-q4km` | llm | **否** | holdout/tasks | 0.083 | 0.000 | 0.167 | 0.042 | 0.167 | -0.125 | 0.028 | 0.208 | 0.202 | 0.000 |
| `baseline_frequent_support_output` | baseline | **否** | dev/tasks | 0.071 | 0.250 | 0.000 | 0.000 | -0.250 | 0.000 | 0.167 | 0.000 | 0.286 | 0.000 |
| `baseline_random` | baseline | **否** | dev/tasks | 0.071 | 0.250 | 0.000 | 0.000 | -0.250 | 0.000 | 0.167 | 0.000 | 0.286 | 0.000 |
| `llm_qwen3-4b-q4km` | llm | **否** | dev/tasks | 0.059 | 0.042 | 0.056 | 0.083 | 0.014 | 0.028 | 0.056 | 0.042 | 0.131 | 0.000 |
| `baseline_frequent_support_output` | baseline | **否** | holdout/tasks | 0.048 | 0.167 | 0.000 | 0.000 | -0.167 | 0.000 | 0.111 | 0.000 | 0.286 | 0.000 |
| `baseline_random` | baseline | **否** | holdout/tasks | 0.048 | 0.167 | 0.000 | 0.000 | -0.167 | 0.000 | 0.111 | 0.000 | 0.286 | 0.000 |
| `llm_gemma4-e2b-q4km` | llm | **否** | dev/tasks | 0.036 | 0.000 | 0.000 | 0.125 | 0.000 | 0.125 | 0.000 | 0.000 | 0.202 | 0.000 |

## ⚠️ 已作废条目（不计入排序，也不作为任何对照）

| 适配器 | 分片/题组 | 存档 acc | 为什么作废 |
|---|---|---|---|
| `deepseek-v4-flash` | holdout/tasks | 0.798 | 评测完成于 19:42:31，而 bench/generate.py 于 19:48:18 被修改、holdout 于 19:53:48 重新生成；其预测文件里存的 gold 与当前 keys/keys_holdout.jsonl 在 63/84 题上不一致（同一次运行的 reference/search 适配器则为 0/84 不一致）。 |

## 本地模型行的调用配置（**本地小模型，不是前沿模型**）

> 配置写在 `results/<适配器>_<分片>_scores.json` 的 `adapter_config` 字段里，
> 逐题原始回答在 `results/raw/` 里；数据冻结/复核哈希见 `results/llm_run_manifest.json`。

- `llm_gemma4-e2b-q4km` @ dev：端点 `http://127.0.0.1:11436/v1`，num_predict=1024，thinking=off，temperature=0.0，seed=20261031；生成 339 tokens / 7.9s（≈42.91 tok/s），解析失败（重试后）0 次。
- `llm_gemma4-e2b-q4km` @ holdout：端点 `http://127.0.0.1:11436/v1`，num_predict=1024，thinking=off，temperature=0.0，seed=20261031；生成 375 tokens / 8.3s（≈45.18 tok/s），解析失败（重试后）0 次。
- `llm_qwen3-4b-q4km` @ dev：端点 `http://127.0.0.1:11435/v1`，num_predict=1024，thinking=off，temperature=0.0，seed=20261031；生成 409 tokens / 12.1s（≈33.8 tok/s），解析失败（重试后）0 次。
- `llm_qwen3-4b-q4km` @ holdout：端点 `http://127.0.0.1:11435/v1`，num_predict=1024，thinking=off，temperature=0.0，seed=20261031；生成 440 tokens / 12.9s（≈34.11 tok/s），解析失败（重试后）0 次。
