#!/bin/bash
# トレーニングAPI起動スクリプト

cd "$(dirname "$0")/.."
python -m uvicorn api.training_app:app --host 0.0.0.0 --port 8001

