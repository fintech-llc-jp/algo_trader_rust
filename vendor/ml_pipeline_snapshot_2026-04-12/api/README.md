# ML API Server

FastAPIサーバーでリアルタイム価格予測とシグナル生成を提供します。

## 起動方法

```bash
cd ml_pipeline
export USE_EXCH_SIM_DB=true
export DB_HOST=localhost
export DB_PORT=5432
export DB_USER=postgres
export DB_PASSWORD=your_password
export API_PORT=8000

python -m api.app
```

または、uvicornを直接使用：

```bash
uvicorn api.app:app --host 0.0.0.0 --port 8000
```

## API エンドポイント

### GET /health
ヘルスチェック

**レスポンス:**
```json
{
  "status": "healthy",
  "models_loaded": true,
  "database_connected": true
}
```

### POST /predict
価格予測を実行

**リクエスト:**
```json
{
  "symbol": "G_FX_BTCJPY",
  "timestamp": "2025-01-20T10:00:00Z",
  "mid_price": 14200000.0,
  "bid_price_1": 14199500.0,
  "ask_price_1": 14200500.0,
  "bid_qty_1": 0.1,
  "ask_qty_1": 0.1,
  "spread": 100.0,
  "order_imbalance": 0.1,
  "bid_depth_5": 0.5,
  "ask_depth_5": 0.4
}
```

**レスポンス:**
```json
{
  "symbol": "G_FX_BTCJPY",
  "timestamp": "2025-01-20T10:00:00Z",
  "predicted_price": 14210000.0,
  "current_price": 14200000.0,
  "price_change_pct": 0.7,
  "confidence": 0.85
}
```

### POST /signal
取引シグナルを生成

**リクエスト:**
```json
{
  "symbol": "G_FX_BTCJPY",
  "timestamp": "2025-01-20T10:00:00Z",
  "mid_price": 14200000.0,
  "bid_price_1": 14199500.0,
  "ask_price_1": 14200500.0
}
```

**レスポンス:**
```json
{
  "symbol": "G_FX_BTCJPY",
  "timestamp": "2025-01-20T10:00:00Z",
  "signal_type": "BUY",
  "confidence": 0.85,
  "predicted_price": 14210000.0,
  "current_price": 14200000.0,
  "price_change_pct": 0.7,
  "momentum_intensity": 5
}
```

## 環境変数

- `API_PORT`: APIサーバーのポート番号（デフォルト: 8000）
- `USE_EXCH_SIM_DB`: exch_simデータベースを使用するか（true/false）
- `DB_HOST`: データベースホスト
- `DB_PORT`: データベースポート
- `DB_USER`: データベースユーザー名
- `DB_PASSWORD`: データベースパスワード
- `MODEL_DIR`: モデルファイルの保存ディレクトリ（デフォルト: `ml_pipeline/models/saved/`）

## モデルの保存場所

訓練されたモデルは以下の場所に保存されます：

- **価格予測モデル**: `ml_pipeline/models/saved/price_prediction_{SYMBOL}.joblib`
- **モメンタム強度モデル**: `ml_pipeline/models/saved/momentum_intensity_{SYMBOL}.joblib`

例：
- `ml_pipeline/models/saved/price_prediction_G_FX_BTCJPY.joblib`
- `ml_pipeline/models/saved/momentum_intensity_G_FX_BTCJPY.joblib`

## モデルの訓練と保存

モデルは`run_price_prediction_backtest.py`を実行すると自動的に保存されます：

```bash
python ml_pipeline/evaluation/run_price_prediction_backtest.py \
  --symbol G_FX_BTCJPY \
  --days 1
```

訓練が完了すると、モデルファイルが`ml_pipeline/models/saved/`ディレクトリに保存されます。

## トラブルシューティング

### モデルがロードされない
モデルを訓練してからAPIサーバーを起動してください。

### データベース接続エラー
環境変数を確認し、データベースにアクセスできることを確認してください。

