# strategy-api

## 責務

戦略プラグインの **共通入力** と **トレイト定義** を提供する。投票型 `StrategyVote` は **`engine-core`** で定義され、本クレートはそれを返す契約として参照する。

## MarketSnapshot

| フィールド | 型 | 説明 |
|------------|-----|------|
| `symbol` | `String` | 対象シンボル |
| `book` | `OrderBookTop` | 最良気配など |
| `bars` | `Vec<Bar>` | 古い順のバー（長さは呼び出し側規約） |
| `now_ms` | `i64` | エポックミリ秒 |

### OrderBookTop

- `best_bid`, `best_ask`, `bid_qty`, `ask_qty`（いずれも `Option<f64>`）
- `mid()`: 両方あれば中値
- `spread()`: 両方あれば ask − bid

### Bar

- OHLCV（`f64`）

## Strategy トレイト

```text
fn id(&self) -> &'static str;
async fn evaluate(&self, snapshot: &MarketSnapshot) -> StrategyVote;
```

- `id` は **`VotePolicy::WeightedMajority` の `weights` キー**と一致させる必要がある（不一致時は重み 1.0 扱い）。
- 評価はティックごとに呼ばれる想定。

## 拡張時の注意

- 戦略が追加されたら `app` の戦略ベクタと `config.toml` の `vote.weights` を整合させる。
- 非同期で外部 API を呼ぶ場合はタイムアウトとフォールバック（棄権）を戦略内で定義すること。
