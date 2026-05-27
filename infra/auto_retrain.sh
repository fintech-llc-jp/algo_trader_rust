#!/usr/bin/env bash
# =============================================================
# 自動再訓練パイプライン
#
# 実行内容:
#   1. VPS からデータ差分同期
#   2. ML モデル再訓練（直近3日）
#
# cron 設定例（1時間ごと）:
#   0 * * * * /Users/sakamoto.yukio/workspace/algo_trader_rust/infra/auto_retrain.sh >> /tmp/auto_retrain.log 2>&1
#
# 使い方:
#   ./auto_retrain.sh           # 通常実行
#   ./auto_retrain.sh --dry-run # 同期のみ・訓練スキップ
# =============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ML_DIR="${SCRIPT_DIR}/../vendor/ml_pipeline_snapshot_2026-04-12"
LOG_PREFIX="[auto_retrain $(date '+%Y-%m-%d %H:%M:%S')]"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "=========================================="
echo "${LOG_PREFIX} パイプライン開始"
echo "=========================================="

# ── Step 1: データ同期 ──────────────────────────────────────
echo "${LOG_PREFIX} [1/2] VPS データ同期（差分1日分）..."
if ! "${SCRIPT_DIR}/sync_from_vps.sh" --incremental 1; then
    echo "${LOG_PREFIX} ERROR: データ同期失敗 → 再訓練をスキップ"
    exit 1
fi
echo "${LOG_PREFIX} データ同期完了"

if [[ "${DRY_RUN}" == "true" ]]; then
    echo "${LOG_PREFIX} --dry-run モード: 訓練をスキップ"
    exit 0
fi

# ── Step 2: モデル再訓練 ────────────────────────────────────
echo "${LOG_PREFIX} [2/2] モデル再訓練（直近3日）..."
cd "${ML_DIR}"
RESULT=$(python3 -m training.daily_trainer --symbol G_FX_BTCJPY --days 3 2>&1)
echo "${RESULT}"

# 結果からmodel_idとaccuracyを抽出
MODEL_ID=$(echo "${RESULT}" | grep "model_id:" | awk '{print $2}')
ACCURACY=$(echo "${RESULT}" | grep "accuracy:" | awk '{print $2}')
STATUS=$(echo "${RESULT}"   | grep "status:"   | awk '{print $2}')

if [[ "${STATUS}" == "success" ]]; then
    echo "=========================================="
    echo "${LOG_PREFIX} ✅ 再訓練完了"
    echo "  model_id : ${MODEL_ID}"
    echo "  accuracy : ${ACCURACY}"
    echo "  → LiveTrader が次のポジションなし時に自動切替"
    echo "=========================================="
else
    echo "${LOG_PREFIX} ERROR: 訓練失敗"
    exit 1
fi
