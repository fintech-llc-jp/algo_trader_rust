#!/bin/bash
# ML-API起動スクリプト
# algo_traderデータベース用の接続情報を明示的に設定

cd "$(dirname "$0")"

# algo_traderデータベース用の接続情報を設定
export ALGO_TRADER_DB_HOST="${ALGO_TRADER_DB_HOST:-localhost}"
export ALGO_TRADER_DB_PORT="${ALGO_TRADER_DB_PORT:-5432}"
export ALGO_TRADER_DB_USER="${ALGO_TRADER_DB_USER:-postgres}"
export ALGO_TRADER_DB_PASSWORD="${ALGO_TRADER_DB_PASSWORD:-postgres123}"
export ALGO_TRADER_DB_NAME="${ALGO_TRADER_DB_NAME:-algo_trader}"

echo "Starting ML-API with algo_trader DB settings:"
echo "  ALGO_TRADER_DB_HOST: $ALGO_TRADER_DB_HOST"
echo "  ALGO_TRADER_DB_PORT: $ALGO_TRADER_DB_PORT"
echo "  ALGO_TRADER_DB_USER: $ALGO_TRADER_DB_USER"
echo "  ALGO_TRADER_DB_NAME: $ALGO_TRADER_DB_NAME"
echo ""

python -m uvicorn api.app:app --host 0.0.0.0 --port 8000
