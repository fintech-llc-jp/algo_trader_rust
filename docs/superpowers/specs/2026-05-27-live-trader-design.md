# live_trader プロジェクト 設計仕様書

**作成日**: 2026-05-27  
**ステータス**: 承認待ち  
**リポジトリ**: `~/workspace/live_trader/`

---

## 1. 概要

ExchSim に依存しない、取引所非依存のリアルタイム ML 取引システム。  
現フェーズは GMO コイン対応を主目的とし、将来的に他取引所（bitFlyer 等）へも拡張できる抽象設計とする。

### 目的

1. GMO WebSocket から sub-second で板データを取得する
2. ML モデルでシグナルを生成し、GMO Private API で本番発注する
3. 取引データ・板データをローカル DB に保存し、バックテスト・再訓練に活用する
4. 再訓練のたびに自動バックテスト検証を行い、合格モデルのみ本番投入する
5. dry-run（ペーパートレード）で人間が動作を確認してから本番切替できる

---

## 2. プロジェクト構成

```
~/workspace/live_trader/
├── exchange/
│   ├── base.py                  # 抽象インターフェース
│   ├── gmo/
│   │   ├── __init__.py
│   │   ├── client.py            # GMO Private API クライアント
│   │   └── feed.py              # GMO WebSocket フィード
│   └── exchsim/
│       ├── __init__.py
│       ├── client.py            # ExchSim REST クライアント（既存コードを移植）
│       └── feed.py              # ExchSim REST ポーリングフィード
├── ml/
│   ├── feature_engineering.py  # 特徴量エンジニアリング（既存コードを移植）
│   ├── model_loader.py          # algo_trader DB からモデルロード
│   └── predictor.py             # 予測ロジック（スケーラー適用・シグナル変換）
├── backtest/
│   └── validator.py             # 再訓練後バックテスト自動検証
├── storage/
│   ├── schema.sql               # DB テーブル定義
│   └── recorder.py              # 板データ・約定データ保存
├── trader.py                    # LiveTrader 本体
├── config.py                    # 設定・環境変数管理
├── requirements.txt
└── CLAUDE.md                    # セッション引き継ぎメモ
```

---

## 3. 取引所抽象レイヤー

### 3.1 抽象インターフェース（`exchange/base.py`）

```python
@dataclass
class Board:
    symbol: str
    bid: float
    ask: float
    mid: float
    bids: list[tuple[float, float]]   # [(price, qty), ...]
    asks: list[tuple[float, float]]
    timestamp: datetime

class MarketDataFeed(ABC):
    """板データ取得の抽象クラス"""
    @abstractmethod
    async def start(self) -> None: ...          # 接続開始
    @abstractmethod
    async def stop(self) -> None: ...           # 接続終了
    @abstractmethod
    def get_board(self) -> Optional[Board]: ... # 最新板を返す（同期）

class ExchangeClient(ABC):
    """発注・ポジション管理の抽象クラス"""
    @abstractmethod
    def place_limit_order(self, side: str, price: float, qty: float) -> str: ...
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool: ...
    @abstractmethod
    def get_positions(self) -> dict: ...
    @abstractmethod
    def get_recent_executions(self, symbol: str, size: int) -> list: ...
```

### 3.2 実装クラス

| クラス | ファイル | 用途 |
|--------|----------|------|
| `GMOWebSocketFeed` | `exchange/gmo/feed.py` | GMO WebSocket で板取得（sub-second） |
| `GMOPrivateClient` | `exchange/gmo/client.py` | GMO Private API で発注・照会 |
| `ExchSimFeed` | `exchange/exchsim/feed.py` | ExchSim REST ポーリング（1秒） |
| `ExchSimClient` | `exchange/exchsim/client.py` | ExchSim REST で発注・照会 |

---

## 4. GMO 接続仕様

### 4.1 板データ（Public WebSocket）

- **URL**: `wss://api.coin.z.com/ws/public/v1`
- **チャンネル**: `orderbooks`（`BTC_JPY`, `BTC`）
- **シンボルマッピング**: `BTC_JPY` → `G_FX_BTCJPY`、`BTC` → `G_BTCJPY`
- **更新頻度**: sub-second（GMO 側の配信頻度に依存）
- **LiveTrader への供給**: 最新板を内部バッファに保持し、1秒ごとに `RollingBuffer` へ追加
- **DB 保存**: 1秒ごとに `gmo_market_snapshots` へ保存（バックテスト用）

### 4.2 本番発注（Private REST API）

| 機能 | エンドポイント |
|------|--------------|
| 指値発注 | `POST /private/v1/order` |
| 注文キャンセル | `POST /private/v1/cancelOrder` |
| 建玉照会 | `GET /private/v1/openPositions` |
| 約定履歴 | `GET /private/v1/latestExecutions` |

- **認証**: `API_KEY` + `API_SECRET` を環境変数で管理
- **HMAC-SHA256** 署名を各リクエストヘッダに付与

---

## 5. データ保存スキーマ（`storage/schema.sql`）

```sql
-- 板スナップショット（バックテスト・再訓練用）
CREATE TABLE gmo_market_snapshots (
    id         BIGSERIAL PRIMARY KEY,
    symbol     TEXT NOT NULL,
    timestamp  TIMESTAMPTZ NOT NULL,
    bid        NUMERIC NOT NULL,
    ask        NUMERIC NOT NULL,
    mid        NUMERIC NOT NULL
);

CREATE TABLE gmo_market_price_levels (
    id          BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL REFERENCES gmo_market_snapshots(id),
    price       NUMERIC NOT NULL,
    qty         NUMERIC NOT NULL,
    side        TEXT NOT NULL,     -- 'BUY' | 'SELL'
    level_index INTEGER NOT NULL
);

-- 約定履歴（損益計算・分析用）
CREATE TABLE gmo_trades (
    id          BIGSERIAL PRIMARY KEY,
    model_id    INTEGER,            -- 使用したMLモデルのID
    symbol      TEXT NOT NULL,
    side        TEXT NOT NULL,      -- 'BUY' | 'SELL'
    price       NUMERIC NOT NULL,
    qty         NUMERIC NOT NULL,
    raw_pnl     NUMERIC,            -- 手数料前損益（円）
    rebate      NUMERIC,            -- Maker リベート（円）
    realized    NUMERIC,            -- 確定損益（円）
    exchange    TEXT NOT NULL,      -- 'gmo' | 'exchsim'
    is_dry_run  BOOLEAN NOT NULL DEFAULT false,  -- dry-run 時は true
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ポジションスナップショット
CREATE TABLE gmo_positions (
    id          BIGSERIAL PRIMARY KEY,
    symbol      TEXT NOT NULL,
    qty         NUMERIC NOT NULL,
    entry_price NUMERIC,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## 6. バックテスト自動検証（`backtest/validator.py`）

`algo_trader_rust/infra/auto_retrain.sh` から呼び出し、再訓練後に自動実行する。

### 合格基準

| 指標 | 閾値 |
|------|------|
| 実現損益 | > 0 円 |
| 勝率 | > 45% |

### 動作フロー

```
validator.py --model-id N --hours 24
  ↓
gmo_market_snapshots（直近24時間）を取得
  ↓
algo_trader_rust/vendor/ml_pipeline_snapshot_2026-04-12/evaluation/
  LimitOrderBacktester でシミュレーション実行
  （Maker rebate・タイムアウト・指値チェイスを再現）
  ↓
合格 → 終了コード 0（auto_retrain.sh が次のステップへ）
不合格 → 終了コード 1 + ログ出力（auto_retrain.sh がモデルを破棄）
```

---

## 7. LiveTrader 本体（`trader.py`）

### 7.1 起動引数

```bash
python trader.py \
  --exchange  gmo|exchsim  \   # 必須: 取引所選択
  --symbol    G_FX_BTCJPY  \   # デフォルト: G_FX_BTCJPY
  --live | --dry-run        \   # 必須: どちらか一方（両方またはなしはエラー）
  --confidence 0.60         \   # デフォルト: 0.60
  --timeout-seconds 30      \   # デフォルト: 30
  --quantity  0.001             # デフォルト: 0.001
```

**起動時バリデーション:**
- `--live` と `--dry-run` のどちらも指定なし → エラー終了
- `--live` と `--dry-run` を同時指定 → エラー終了

### 7.2 メインループ（1秒ごと）

```
1. MarketDataFeed.get_board() → 最新板取得
2. storage.Recorder.save_board() → DB 保存（dry-run 時も保存）
3. RollingBuffer.add(board)
4. ウォームアップ確認（60秒）
5. Predictor.predict() → signal, confidence
6. _manage_orders(signal, confidence, board)
7. 自動モデルリロードチェック（30分ごと・ポジションなし時）
8. 定期ログ（30秒ごと）
```

### 7.3 dry-run 動作

- `ExchangeClient` の発注・キャンセルメソッドは呼ばない
- 板データ保存・ログ・損益計算はすべて実行
- `gmo_trades` への保存も行う（実取引の代わりに `dry_run=true` フラグ付きで）

---

## 8. 開発フェーズ

| フェーズ | 内容 | 前提 |
|----------|------|------|
| **Phase 1** | プロジェクト骨格・抽象レイヤー・ExchSim 移植 | 既存 LiveTrader の動作確認 |
| **Phase 2** | GMOWebSocketFeed・DB 保存・dry-run 動作確認 | GMO Public API アクセス |
| **Phase 3** | バックテスト自動検証・auto_retrain.sh 統合 | Phase 2 完了 |
| **Phase 4** | GMOPrivateClient・本番発注 | GMO API Key 取得 |

---

## 9. 環境変数

```bash
# GMO API（Phase 4 で使用）
GMO_API_KEY=xxx
GMO_API_SECRET=xxx

# ML モデル DB（algo_trader）
ALGO_TRADER_DB_HOST=localhost
ALGO_TRADER_DB_PORT=5432
ALGO_TRADER_DB_USER=postgres
ALGO_TRADER_DB_PASSWORD=xxx
ALGO_TRADER_DB_NAME=algo_trader

# live_trader ローカル DB
LIVE_TRADER_DB_HOST=localhost
LIVE_TRADER_DB_PORT=5432
LIVE_TRADER_DB_USER=postgres
LIVE_TRADER_DB_PASSWORD=xxx
LIVE_TRADER_DB_NAME=live_trader
```

---

## 10. 既存プロジェクトとの関係

| 項目 | algo_trader_rust（既存） | live_trader（新規） |
|------|--------------------------|---------------------|
| ML 訓練 | `vendor/ml_pipeline_snapshot_2026-04-12` | 依存（モデルを読み込む） |
| 板データ収集 | ExchSim VPS + sync | GMOWebSocketFeed が自前保存 |
| 発注 | ExchSim シミュレーション | GMO Private API |
| DB | `exch_sim` / `algo_trader` | `live_trader`（独立） |
| バックテスト | backtester.py（既存） | validator.py（新規・薄いラッパー） |

---

## 11. 将来拡張

- `exchange/bitflyer/` を追加することで bitFlyer 対応
- `--exchange bitflyer --dry-run` で即座に検証可能
- `gmo_trades` の `exchange` カラムで取引所別分析が可能
