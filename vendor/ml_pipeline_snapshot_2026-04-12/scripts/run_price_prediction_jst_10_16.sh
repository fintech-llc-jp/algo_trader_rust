#!/bin/bash
# JST 10:00-16:00で価格予測とトレードを実行するスクリプト
# 今日の日付を自動的に使用

# 今日の日付を取得（YYYY-MM-DD形式）
TODAY=$(date +%Y-%m-%d)

# シンボル（デフォルト: G_FX_BTCJPY）
SYMBOL=${1:-G_FX_BTCJPY}

echo "Running price prediction backtest for $SYMBOL"
echo "Period: JST ${TODAY} 10:00:00 to ${TODAY} 16:00:00"
echo ""

# 価格予測とトレードを実行
python ml_pipeline/evaluation/run_price_prediction_backtest.py \
  --symbol "$SYMBOL" \
  --start-date "${TODAY} 10:00:00" \
  --end-date "${TODAY} 16:00:00" \
  --show-trades \
  --output-dir "./evaluation_results/${TODAY}"

