#!/bin/bash
# 容量探针：在不改题目、不改评分器的前提下，只把搜索器的「思考预算」调大，
# 看 0.786/0.762 与 1.000 之间的差距有多少是搜索宽度造成的。
#
#   P1  beam 160 → 600，max_len 仍为 2（同一条假设语言，只是搜得更宽）
#   P2  max_len 2 → 3，beam 仍为 160（假设语言变大：允许更长的规则）
#
# 注意：run_eval 的输出文件名由适配器名决定（search_solver_*），会覆盖正式结果。
# 因此本脚本先把正式结果备份到 /tmp/c2a_official，探针输出改名到 results/probe/，
# 跑完再把正式结果放回原位 —— 正式排行榜的数字不被探针污染。
#
# 数据/答案与代码在跑之前已用 bench/freeze_check.py --create 冻结，
# 探针只读 data/ 与 keys/，因此跑完 --check 仍应通过。
set -u
cd "/Users/zhanghao/Desktop/赵怡涵_C2A_提交包/赵怡涵_C9_benchmark" || exit 2
mkdir -p results/probe /tmp/c2a_official

cp results/search_solver_dev_scores.json        /tmp/c2a_official/
cp results/search_solver_dev_predictions.jsonl  /tmp/c2a_official/
cp results/search_solver_holdout_scores.json    /tmp/c2a_official/
cp results/search_solver_holdout_predictions.jsonl /tmp/c2a_official/

echo "== P1 dev (beam 600) =="
python3 -m bench.run_eval --model search --split dev --beam 600 > results/probe/p1_dev.log 2>&1
echo "  exit=$?"
mv results/search_solver_dev_scores.json       results/probe/probe_search_beam600_dev_scores.json
mv results/search_solver_dev_predictions.jsonl results/probe/probe_search_beam600_dev_predictions.jsonl

echo "== P1 holdout (beam 600) =="
python3 -m bench.run_eval --model search --split holdout --beam 600 > results/probe/p1_holdout.log 2>&1
echo "  exit=$?"
mv results/search_solver_holdout_scores.json       results/probe/probe_search_beam600_holdout_scores.json
mv results/search_solver_holdout_predictions.jsonl results/probe/probe_search_beam600_holdout_predictions.jsonl

echo "== P2 dev (max_len 3) =="
python3 -m bench.run_eval --model search --split dev --max-len 3 --beam 160 > results/probe/p2_dev.log 2>&1
echo "  exit=$?"
mv results/search_solver_dev_scores.json       results/probe/probe_search_maxlen3_dev_scores.json
mv results/search_solver_dev_predictions.jsonl results/probe/probe_search_maxlen3_dev_predictions.jsonl

echo "== P2 holdout (max_len 3) =="
python3 -m bench.run_eval --model search --split holdout --max-len 3 --beam 160 > results/probe/p2_holdout.log 2>&1
echo "  exit=$?"
mv results/search_solver_holdout_scores.json       results/probe/probe_search_maxlen3_holdout_scores.json
mv results/search_solver_holdout_predictions.jsonl results/probe/probe_search_maxlen3_holdout_predictions.jsonl

# 复原正式结果（探针不得改动排行榜）
cp /tmp/c2a_official/search_solver_dev_scores.json          results/
cp /tmp/c2a_official/search_solver_dev_predictions.jsonl    results/
cp /tmp/c2a_official/search_solver_holdout_scores.json      results/
cp /tmp/c2a_official/search_solver_holdout_predictions.jsonl results/

echo "== 探针完成，正式结果已复原 =="
python3 -m bench.freeze_check --check
