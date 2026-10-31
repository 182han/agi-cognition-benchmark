#!/usr/bin/env bash
# =============================================================================
# ΔR-Bench · 一条命令复现全部结果
#
#   用法：
#     bash scripts/reproduce.sh              # 完整复现（dev + holdout，约 10–15 分钟）
#     bash scripts/reproduce.sh --fast       # 跳过最强的归纳解题器（约 1 分钟）
#     bash scripts/reproduce.sh --regen      # 额外重生成 dev 数据集（+约 4 分钟）
#
#   产出：
#     results/<adapter>_<split>_scores.json        每个解题器的指标
#     results/<adapter>_<split>_predictions.jsonl  逐题明细
#     results/leaderboard.md                       汇总榜（本脚本生成）
#
# 依据《Elite20 挑战提交总则 v1.3》§5.4「复现性硬要求：一条命令跑完」。
#
# ⚠️ 设计原则：**失败必须非零退出**。本脚本不使用「打印警告然后 exit 0」的写法——
#    那正是「不可复现」这条红线惩罚的静默故障。
#
# ⚠️ 关于确定性：生成器完全确定（同 seed 两次生成字节一致，见 [2/8]）。
#    本脚本**不重新生成**已发布的数据集，而是**复核**它：所有指标都从
#    data/ 与 keys/ 的现有文件重算。--regen 才是重生成。
#
# 步骤顺序（新克隆上必须一次跑通）：
#   [1/8] 环境与依赖 → [2/8] 生成器确定性 → [3/8] 数据集完整性
#   [4/8] 全部解题器与基线 → [5/8] 控制集与扰动集
#   [6/8] 汇总榜（**在检查之前生成**：冒烟测试会检查 results/leaderboard.md）
#   [7/8] 防污染/防作弊审计 → [8/8] 基准自检 + 基准冒烟测试
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT"

FAST=0
REGEN=0
for a in "$@"; do
  case "$a" in
    --fast) FAST=1 ;;
    --regen) REGEN=1 ;;
    *) echo "未知参数：$a" >&2; exit 2 ;;
  esac
done

PY="${PYTHON:-python3}"
export PYTHONPATH="$ROOT"

banner() { printf '\n%s\n %s\n%s\n' "======================================================================" "$1" "======================================================================"; }
fail() { printf '\n❌ 失败：%s\n' "$1" >&2; exit 1; }

banner "ΔR-Bench 复现流水线"
echo " 包根目录 : $ROOT"
echo " Python   : $($PY -V 2>&1)"
echo " 时间     : $(date '+%Y-%m-%d %H:%M:%S')"
echo " 模式     : $([ $FAST = 1 ] && echo 快速 || echo 完整)$([ $REGEN = 1 ] && echo ' + 重生成' || echo '')"

# ---------------------------------------------------------------------------
banner "[1/8] 环境与依赖检查"
$PY - <<'PYEOF' || fail "依赖检查不通过"
import sys, json, os
assert sys.version_info >= (3, 7), "需要 Python 3.7+，当前 %s" % sys.version
print("  ✅ Python %s" % sys.version.split()[0])
# 本包**只用标准库**：没有第三方依赖，因此不存在「装不上就复现不了」的问题。
mods = ["random", "hashlib", "json", "math", "re", "subprocess"]
import importlib
for m in mods:
    importlib.import_module(m)
print("  ✅ 标准库模块齐全：%s" % ", ".join(mods))
print("  ✅ 无第三方依赖（requirements.txt 为空即是有意为之）")
PYEOF
[ -d data ] || fail "找不到 data/ 目录"
[ -d keys ] || fail "找不到 keys/ 目录"
for f in data/tasks_dev.jsonl keys/keys_dev.jsonl data/manifest_dev.json; do
  [ -s "$f" ] || fail "缺少或为空：$f"
done
echo "  ✅ 数据集文件齐全"

# ---------------------------------------------------------------------------
banner "[2/8] 生成器确定性（mini 数据集，同 seed 生成两次，字节比对）"
if [ $FAST = 1 ]; then
  echo "  ⏭  快速模式跳过"
else
  DET="$(mktemp -d)"
  trap 'rm -rf "$DET"' EXIT
  $PY -m bench.generate --split dev --seed 999001 --mini --out "$DET/a" >/dev/null \
    || fail "mini 生成（第一次）失败"
  $PY -m bench.generate --split dev --seed 999001 --mini --out "$DET/b" >/dev/null \
    || fail "mini 生成（第二次）失败"
  HA=$(shasum -a 256 "$DET/a/data/tasks_dev.jsonl" | cut -d' ' -f1)
  HB=$(shasum -a 256 "$DET/b/data/tasks_dev.jsonl" | cut -d' ' -f1)
  KA=$(shasum -a 256 "$DET/a/keys/keys_dev.jsonl" | cut -d' ' -f1)
  KB=$(shasum -a 256 "$DET/b/keys/keys_dev.jsonl" | cut -d' ' -f1)
  echo "  tasks 第一次 : $HA"
  echo "  tasks 第二次 : $HB"
  echo "  keys  第一次 : $KA"
  echo "  keys  第二次 : $KB"
  [ "$HA" = "$HB" ] || fail "生成器不确定：两次生成的题目不一致"
  [ "$KA" = "$KB" ] || fail "生成器不确定：两次生成的答案不一致"
  echo "  ✅ 两次生成字节完全一致 —— 生成器是确定性的"
fi

# ---------------------------------------------------------------------------
banner "[3/8] 数据集完整性"
$PY - <<'PYEOF' || fail "数据集完整性检查不通过"
import json, os
for split in ("dev", "holdout"):
    tp = "data/tasks_%s.jsonl" % split
    kp = "keys/keys_%s.jsonl" % split
    if not os.path.exists(tp):
        print("  ⚠️  %s 不存在（holdout 需用 DRBENCH_HOLDOUT_SEED 生成）" % split)
        continue
    def rd(p):
        return [json.loads(l) for l in open(p, encoding="utf-8")
                if l.strip() and not l.startswith("#")]
    T, K = rd(tp), rd(kp)
    ids_t = set(t["item_id"] for t in T)
    ids_k = set(k["item_id"] for k in K)
    assert ids_t == ids_k, "%s: 题目与答案的 item_id 不匹配" % split
    ph = {}
    for t in T:
        ph[t["phase"]] = ph.get(t["phase"], 0) + 1
    print("  ✅ %-8s 题量=%d  宇宙=%d  阶段=%s"
          % (split, len(T), len(set(t["universe_public_id"] for t in T)), ph))
PYEOF

# ---------------------------------------------------------------------------
if [ $REGEN = 1 ]; then
  banner "[3b] 重新生成 dev 数据集（--regen）"
  $PY -m bench.generate --split dev --seed 20261031 || fail "重生成失败"
fi

# ---------------------------------------------------------------------------
banner "[4/8] 运行全部解题器与基线"
SPLITS="dev"
[ -f data/tasks_holdout.jsonl ] && SPLITS="dev holdout"
echo " 分片：$SPLITS"
for SP in $SPLITS; do
  echo " --- [$SP] 确定性基线 + 全知参考解 ---"
  for model in reference copy_input frequent_support_output random; do
    $PY -m bench.run_eval --model "$model" --split "$SP" >/dev/null \
      || fail "解题器 $model @ $SP 运行失败"
    echo "  ✅ [$SP] $model"
  done
  if [ $FAST = 0 ]; then
    echo " --- [$SP] 假设空间搜索器（本题集最强的非 LLM 解题器，约 1–2 分钟）---"
    $PY -m bench.run_eval --model search --split "$SP" --max-len 2 --beam 160 >/dev/null \
      || fail "search @ $SP 运行失败"
    echo "  ✅ [$SP] search"
    echo " --- [$SP] 受限搜索（人类难度代理）---"
    $PY -m bench.run_eval --model bounded_search --split "$SP" --max-len 1 --beam 6 >/dev/null \
      || fail "bounded_search @ $SP 运行失败"
    echo "  ✅ [$SP] bounded_search"
  else
    echo "  ⏭  [$SP] 快速模式跳过 search / bounded_search"
  fi
done

# ---------------------------------------------------------------------------
banner "[5/8] 控制集与扰动集"
for SP in $SPLITS; do
  if [ $FAST = 0 ]; then
    echo " --- [$SP] 控制集：示例输出被打乱（正确率应塌向随机）---"
    $PY -m bench.run_eval --model search --split "$SP" --set control_corrupt \
        --max-len 2 --beam 160 >/dev/null || fail "控制集 @ $SP 运行失败"
    echo "  ✅ [$SP] control_corrupt"
  else
    echo "  ⏭  [$SP] 快速模式跳过控制集"
  fi
  echo " --- [$SP] 扰动集：符号重命名 + 示例乱序（参考解应仍是 1.0）---"
  $PY -m bench.run_eval --model reference --split "$SP" --set perturb >/dev/null \
    || fail "扰动集 @ $SP 运行失败"
  echo "  ✅ [$SP] perturb"
done

# ---------------------------------------------------------------------------
banner "[6/8] 汇总榜（**必须早于审计、自检与冒烟测试**）"
# 顺序说明：基准冒烟测试（[8/8]）会检查 results/leaderboard.md 是否存在，所以本步
# 必须排在它前面。原实现把汇总榜放在最后一步，导致**全新克隆第一次跑必然失败**在
# 「缺一个自己马上就要生成的产物」上（管线顺序缺陷，见 CHANGELOG v1.0.3）。
$PY - <<'PYEOF' || fail "汇总榜生成失败"
import glob, json, os

rows = []
for p in sorted(glob.glob("results/*_scores.json")):
    d = json.load(open(p, encoding="utf-8"))
    rows.append(d)
if not rows:
    raise SystemExit("results/ 下没有任何 *_scores.json")

# ---- 作废清单（results/void_runs.json）--------------------------------------
# 判据：该次运行评分用的 gold 与当前 keys 不一致 ⇒ 它跑在**另一版数据**上。
# 作废行**不进入排序、不作为对照、不参与任何结论**，只在文末单独列出并写明理由。
void = {}
if os.path.exists("results/void_runs.json"):
    for v in json.load(open("results/void_runs.json", encoding="utf-8")).get("void", []):
        void[(v.get("adapter"), v.get("split"), v.get("task_set", "tasks"))] = v

def is_void(d):
    return (d.get("adapter"), d.get("split"), d.get("task_set")) in void

live = [d for d in rows if not is_void(d)]
dead = [d for d in rows if is_void(d)]

def fmt(v):
    return "—" if v is None else ("%.3f" % v if isinstance(v, float) else str(v))

hdr = ["适配器", "类型", "前沿模型", "题组", "acc", "A", "B", "C",
       "LearningGain", "FeedbackGain", "ID", "OOD", "抄输入率", "解析失败率"]
lines = ["# ΔR-Bench 结果汇总（由 scripts/reproduce.sh 自动生成）", "",
         "> `前沿模型` 一列由代码（`Adapter.is_frontier_model`）填写，不由人手工标注。",
         "> 本表中**没有任何前沿模型分数**——详见 `赵怡涵_C9_测试结果.md` 的说明。",
         "> **作废的评测运行不进本表、不参与排序或对照**，单独列在文末。", "",
         "| " + " | ".join(hdr) + " |",
         "|" + "---|" * len(hdr)]
for d in sorted(live, key=lambda x: -(x.get("accuracy") or 0)):
    tag = "%s/%s" % (d.get("split"), d.get("task_set"))
    lines.append("| `%s` | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
        d["adapter"], d.get("adapter_kind"), "是" if d.get("is_frontier_model") else "**否**",
        tag, fmt(d.get("accuracy")), fmt(d.get("acc_phase_A")), fmt(d.get("acc_phase_B")),
        fmt(d.get("acc_phase_C")), fmt(d.get("LearningGain_B_minus_A")),
        fmt(d.get("FeedbackGain_C_minus_B")), fmt(d.get("acc_id")), fmt(d.get("acc_ood")),
        fmt(d.get("copy_input_rate")), fmt(d.get("parse_failure_rate"))))

if dead:
    lines += ["", "## ⚠️ 已作废条目（不计入排序，也不作为任何对照）", "",
              "| 适配器 | 分片/题组 | 存档 acc | 为什么作废 |", "|---|---|---|---|"]
    for d in dead:
        v = void[(d["adapter"], d["split"], d["task_set"])]
        lines.append("| `%s` | %s/%s | %s | %s |" % (
            d["adapter"], d.get("split"), d.get("task_set"),
            fmt(d.get("accuracy")), v.get("reason", "")))

# ---- 本地模型行说明（不是前沿模型；配置必须随行可见）------------------------
llm_rows = [d for d in live if d.get("adapter_kind") == "llm"]
if llm_rows:
    lines += ["", "## 本地模型行的调用配置（**本地小模型，不是前沿模型**）", "",
              "> 配置写在 `results/<适配器>_<分片>_scores.json` 的 `adapter_config` 字段里，",
              "> 逐题原始回答在 `results/raw/` 里；数据冻结/复核哈希见 `results/llm_run_manifest.json`。", ""]
    seen = set()
    for d in llm_rows:
        key = (d["adapter"], d.get("split"))
        if key in seen:
            continue
        seen.add(key)
        cfg = d.get("adapter_config") or {}
        st = d.get("adapter_stats") or {}
        lines.append("- `%s` @ %s：端点 `%s`，num_predict=%s，thinking=%s，"
                     "temperature=%s，seed=%s；生成 %s tokens / %ss（≈%s tok/s），"
                     "解析失败（重试后）%s 次。" % (
                         d["adapter"], d.get("split"), cfg.get("endpoint"),
                         cfg.get("num_predict"), cfg.get("thinking"),
                         cfg.get("temperature"), cfg.get("seed"),
                         st.get("completion_tokens"), st.get("gen_sec"),
                         st.get("tok_per_sec"), st.get("parse_failure_after_retry")))

open("results/leaderboard.md", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
PYEOF

# ---------------------------------------------------------------------------
banner "[7/8] 防污染 / 防作弊审计"
for SP in $SPLITS; do
  # cross 必须是**另一个**分片：早期版本写死 --cross holdout，导致 holdout 自己跟
  # 自己比对，A5 报出 84 对完全重复 —— 那是脚本的错，不是数据的错。
  if [ "$SP" = "dev" ]; then CROSS=holdout; else CROSS=dev; fi
  $PY -m bench.contamination --root "$ROOT" --split "$SP" --cross "$CROSS" \
      --md "$ROOT/docs/防作弊报告.md" \
    || fail "防污染审计 @ $SP 未全部通过（见上表 FAIL 行）"
done

# ---------------------------------------------------------------------------
banner "[8/8] 基准自检（可归纳性 / 答案可核验 / 参考解满分）"
for SP in $SPLITS; do
  $PY -m bench.selfcheck --root "$ROOT" --split "$SP" --skip-determinism \
      || fail "基准自检 @ $SP 未通过"
done
echo " --- 基准冒烟测试 ---"
$PY tests/test_smoke.py >/dev/null || fail "冒烟测试未通过"
echo "  ✅ tests/test_smoke.py"

banner "✅ 全部完成"
echo " 结果目录：$ROOT/results/"
ls -1 "$ROOT/results" | sed 's/^/   /'
echo
echo " 下一步（需要本人执行，见 00_先读我_待办清单.md）："
echo "   1) 采集人类基线（n=30）"
echo "   2) 接前沿模型 API：export DRBENCH_API_KEY=... && \\"
echo "      python3 -m bench.run_eval --model openai_compat --model-name <模型> --split holdout"
echo "   3) 提交 Kaggle Community Benchmarks"
