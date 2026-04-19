# engine-core

## 責務

- **ドメイン型**: `Side`, `ExecutionMode`, `Intent`
- **投票**: `VoteSide`, `StrategyVote`, `VotePolicy`, `VoteEngine`, `VoteOutcome`
- **オーケストレーション**: `TradingPipeline`（投票 → Intent → リスク適用）
- **リスク**: `RiskLimits`, `RiskService`, `RiskDecision`
- **設定**: `AppConfig`, `RuntimeConfig`（`serde` + TOML）
- **取引所抽象**: `Exchange` トレイトと入出力 DTO（`NewOrderRequest`, `OrderBook`, …）
- **運用**: `kill_switch_active`

## 主要型

### StrategyVote

- `strategy_id: String`
- `side: VoteSide` — `Buy` | `Sell` | `Hold` | `Abstain`
- `strength: f64` — 想定レンジ [0, 1]（呼び出し側の約束）

### VotePolicy（serde、タグ `mode`）

| モード | フィールド | 集約の意味 |
|--------|------------|------------|
| `weighted_majority` | `weights: HashMap<String, f64>`, `min_net_strength: f64` | 戦略 ID ごとに重みを掛け、Buy と Sell にそれぞれ `strength * weight` を加算。`Abstain`/`Hold` は集計に入れない。ネット = buy − sell。`\|net\| < min_net_strength` なら `Hold`。 |
| `quorum` | `required_same_side: usize`, `min_strength_per_vote: f64` | 閾値以上の強度の票だけを数え、Buy または Sell の枚数が `required_same_side` 以上ならその側。同数優先などの細則は実装参照。 |
| `simple_plurality` | なし | Buy と Sell にそれぞれ強度を合計し、多い方。ほぼ同値は `Hold`。 |

### TradingPipeline

- 入力: `&[StrategyVote]`
- 内部: `VoteEngine::aggregate` → 合意が `Buy`/`Sell` なら `Intent::PlaceOrder`（数量は設定のデフォルト値）、それ以外は `Intent::NoTrade`
- その後 `RiskService::apply` で `PlaceOrder` をブロックし得る

### RiskLimits / RiskService

- `max_position_units`: 次の注文後の想定ポジション（単一シンボル MVP の符号付き数量）の絶対値上限
- `max_order_size`: 1 注文あたりの数量上限
- `max_daily_loss_abs`: `daily_pnl` が `-max_daily_loss_abs` 未満ならブロック（`RiskService::set_daily_pnl` で注入）

### Exchange トレイト

非同期メソッド:

- `login_or_refresh()` — JWT 未取得時にログイン（アダプタ実装依存）
- `place_order(NewOrderRequest)`
- `cancel_order(CancelOrderRequest)`
- `get_order_book(symbol)`

### runtime

- `kill_switch_active(path: Option<&PathBuf>)` — `path` が存在すれば `true`

## エラー

- `VoteError`: 票が空など
- `ExchangeError`: HTTP/JSON/レスポンス不正
