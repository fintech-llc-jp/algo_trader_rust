# strategies-*（各戦略クレート）

## 共通

- いずれも `strategy_api::Strategy` を実装。
- 返却型は常に `engine_core::StrategyVote`。

---

## strategies-mm（`MarketMakerStrategy`）

### 目的

スプレッドが十分広いときに **買い方向** の票を出す MVP（在庫管理は未実装）。

### コンストラクタ

- `new(min_spread_abs: f64, quote_strength: f64)`
  - `quote_strength` は [0, 1] にクランプ。

### 挙動

- `book.spread()` が `None` → `Abstain`
- `spread < min_spread_abs` → `Hold`（弱い強度 0.2）
- それ以外 → `Buy`（`quote_strength`）

### 戦略 ID

`"market_maker"`

---

## strategies-arb（`ArbitrageStrategy`）

### 目的

将来、複数シンボル／複数板からの裁定用。現状は **データ未配線のため常に棄権**。

### フィールド

- `threshold_pct` — 将来の閾値（現在は未使用）

### 挙動

- 常に `Abstain`（強度 0）

### 戦略 ID

`"arbitrage"`

---

## strategies-momentum（`MomentumStrategy`）

### 目的

直近 2 本の終値からリターンを取り、方向と強度を付与。

### コンストラクタ

- `new(min_bars: usize, strength: f64)` — `strength` は [0, 1] にクランプ。

### 挙動

- `bars.len() < min_bars` → `Abstain`
- 直近 2 本の `(close[t]-close[t-1])/close[t-1]` が正 → `Buy`、負 → `Sell`、ゼロ → `Hold`
- 強度は `strength * min(|ret|, 1.0)`

### 戦略 ID

`"momentum"`

---

## strategies-predict（`PricePredictionStrategy` / `OnnxPredictor`）

### 目的

`ml_bridge/model.onnx` と `feature_schema.json` に従い特徴ベクトルを組み、ONNX で推論し、方向票に変換。

### 設定（`PredictStrategyConfig`）

| フィールド | 説明 |
|------------|------|
| `model_path` | ONNX ファイルパス |
| `schema_path` | JSON スキーマパス |
| `input_name` | モデル入力名（例: `input`） |
| `output_name` | モデル出力名（例: `output`） |
| `three_class` | `true` のとき出力先頭 3 要素を [down, neutral, up] とみなす |

### 特徴量ベクトル（`OnnxPredictor::build_features`）

- 次元は `feature_schema.json` の `feature_dim`
- `[0]` ミッド、`[1]` スプレッド（次元が 2 以上の場合）、以降は **新しいバーから** 終値を詰める

### 推論失敗時

- `PricePredictionStrategy::new` でロード失敗 → ログ警告後、評価は常に `Abstain`
- 実行時エラー → `Abstain`

### 戦略 ID

`"price_prediction"`
