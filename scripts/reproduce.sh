#!/usr/bin/env bash
# =============================================================================
# C2A / C9 提交包 · 一条命令复现全部
#
# 本文件是**包级**入口：它做两件事
#   1) 委派给基准自带的完整流水线（跑数据、解题器、审计、自检、汇总榜）
#   2) 跑包级冒烟测试（检查六件套、交付物、诚实性标记是否齐全）
#
# 用法：
#   bash scripts/reproduce.sh              # 完整（dev + holdout，约 10–15 分钟）
#   bash scripts/reproduce.sh --fast       # 快速（跳过最重的归纳解题器，约 1 分钟）
#   bash scripts/reproduce.sh --pkg-only   # 只跑包级自检（约 5 秒）
#
# ⚠️ 失败必须非零退出。本脚本不用「打印警告然后 exit 0」的写法。
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
BENCH="$ROOT/赵怡涵_C9_benchmark"
PY="${PYTHON:-python3}"

MODE="${1:-full}"

echo "======================================================================"
echo " C2A / C9 提交包 · 复现"
echo " 包根目录 : $ROOT"
echo " 基准目录 : $BENCH"
echo " Python   : $($PY -V 2>&1)"
echo " 模式     : $MODE"
echo "======================================================================"

if [ "$MODE" != "--pkg-only" ]; then
  [ -d "$BENCH" ] || { echo "❌ 找不到基准目录 $BENCH" >&2; exit 1; }
  echo
  echo "### [A] 基准流水线（委派给 赵怡涵_C9_benchmark/scripts/reproduce.sh）"
  if [ "$MODE" = "--fast" ]; then
    bash "$BENCH/scripts/reproduce.sh" --fast
  else
    bash "$BENCH/scripts/reproduce.sh"
  fi
fi

echo
echo "### [B] 包级冒烟测试（六件套 / 交付物 / 诚实性标记）"
$PY "$ROOT/tests/test_smoke.py"

echo
echo "### [C] 基准冒烟测试"
if [ -d "$BENCH" ]; then
  ( cd "$BENCH" && $PY tests/test_smoke.py )
fi

echo
echo "======================================================================"
echo " ✅ 全部完成"
echo "======================================================================"
echo " 结果目录 : $BENCH/results/"
echo " 汇总榜   : $BENCH/results/leaderboard.md"
echo
echo " 待本人执行（见 00_先读我_待办清单.md）："
echo "   1) 群内发起 G1：赵怡涵_C2A_G1背书.md 里的模板"
echo "   2) 采集人类基线（n=30）：赵怡涵_C9_task说明.md §4.2"
echo "   3) 接前沿模型 API：python3 -m bench.run_eval --model openai_compat ..."
echo "   4) Kaggle 平台正式提交"
