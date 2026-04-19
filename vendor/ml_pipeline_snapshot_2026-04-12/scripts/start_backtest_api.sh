#!/bin/bash
# バックテストAPI起動スクリプト

cd "$(dirname "$0")/.."
python -m uvicorn api.backtest_app:app --host 0.0.0.0 --port 8002

