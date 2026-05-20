# ローカル DB 環境構築 設計書

**日付:** 2026-05-20  
**対象:** `algo_trader_rust` — ローカル ML 学習テスト用 PostgreSQL 環境  
**ステータス:** 承認済み

---

## 背景・目的

VPS でマーケットデータを再収集中のため、ローカルで ML モデル学習のテストができる環境が必要。  
VPS の `exch_sim` DB からデータをインポートし、ローカルで学習パイプライン（`ml_pipeline_snapshot_2026-04-12`）を完全に動かせるようにする。

---

## 構成概要

### 1インスタンス・2データベース方式

```
Docker PostgreSQL（ポート 5432）
├── exch_sim       ← 市場データ（VPS から sync）
└── algo_trader    ← ML モデル保存（ローカル新規作成）
```

- イメージ: `postgres:15-alpine`（既存イメージを流用）
- ユーザー: `postgres` / パスワード: `postgres123`（既存 `.env` 設定に合わせる）
- データ永続化: named volume `pgdata`

---

## ファイル構成

```
algo_trader_rust/
└── infra/
    ├── docker-compose.yml       # PostgreSQL コンテナ定義
    ├── .env.local               # ローカル用 DB 設定（.gitignore 対象）
    ├── .env.local.example       # サンプル（コミット対象）
    ├── init/
    │   ├── 01_exch_sim.sql      # exch_sim DB + 全テーブル作成
    │   └── 02_algo_trader.sql   # algo_trader DB + ml_models テーブル作成
    └── sync_from_vps.sh         # VPS → ローカル データ同期スクリプト
```

---

## 詳細設計

### docker-compose.yml

```yaml
services:
  postgres:
    image: postgres:15-alpine
    container_name: algo_trader_postgres
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres123
      POSTGRES_DB: postgres
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./init:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

**備考:** `./init/` フォルダ内の `.sql` ファイルはファイル名順（01_, 02_）に自動実行される。

---

### 01_exch_sim.sql — exch_sim スキーマ（VPS 完全再現）

#### テーブル一覧（VPS 実スキーマから取得）

**market_board_snapshots**（ML 学習の主要入力）
```sql
CREATE TABLE market_board_snapshots (
    id        BIGSERIAL PRIMARY KEY,
    symbol    VARCHAR(50) NOT NULL,
    timestamp TIMESTAMP NOT NULL
);
CREATE INDEX idx_market_board_snapshots_symbol_timestamp
    ON market_board_snapshots (symbol, timestamp);
```

**market_board_price_levels**（板情報、ML 特徴量）
```sql
CREATE TABLE market_board_price_levels (
    id          BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL
        REFERENCES market_board_snapshots(id) ON DELETE CASCADE,
    price       DOUBLE PRECISION NOT NULL,
    quantity    DOUBLE PRECISION NOT NULL,
    side        VARCHAR(3) NOT NULL,
    level_index INTEGER NOT NULL
);
```

**executions**（約定履歴）
```sql
CREATE TABLE executions (
    exec_id                VARCHAR(255) PRIMARY KEY,
    order_id               VARCHAR(255),
    username               VARCHAR(255),
    symbol                 VARCHAR(255),
    exec_status            VARCHAR(50),
    last_px                BIGINT,
    last_qty               BIGINT,
    counter_party_username VARCHAR(255),
    created_at             TIMESTAMP,
    is_market_maker        BOOLEAN,
    side                   VARCHAR(10)
);
CREATE INDEX idx_execution_count_calc         ON executions (is_market_maker, exec_status, created_at, symbol);
CREATE INDEX idx_execution_market_maker_status ON executions (is_market_maker, exec_status);
CREATE INDEX idx_execution_symbol_time_status_mm ON executions (symbol, created_at, exec_status, is_market_maker);
CREATE INDEX idx_execution_time_status_mm     ON executions (created_at, exec_status, is_market_maker);
CREATE INDEX idx_execution_volume_calc        ON executions (is_market_maker, exec_status, created_at, symbol, last_qty);
```

**positions**（ポジション）
```sql
CREATE TABLE positions (
    id                  VARCHAR(255) PRIMARY KEY,
    username            VARCHAR(255) NOT NULL,
    symbol              VARCHAR(255) NOT NULL,
    unit                VARCHAR(50)  NOT NULL,
    total_buy_qty       BIGINT       NOT NULL,
    total_buy_amount    DOUBLE PRECISION NOT NULL,
    total_sell_qty      BIGINT       NOT NULL,
    total_sell_amount   DOUBLE PRECISION NOT NULL,
    net_qty             BIGINT       NOT NULL,
    average_buy_price   DOUBLE PRECISION NOT NULL,
    average_sell_price  DOUBLE PRECISION NOT NULL,
    realized_pnl        DOUBLE PRECISION NOT NULL,
    last_updated        TIMESTAMP    NOT NULL
);
```

**trade_history**（取引履歴）
```sql
CREATE TABLE trade_history (
    exec_id                VARCHAR(255) PRIMARY KEY,
    username               VARCHAR(255) NOT NULL,
    symbol                 VARCHAR(255) NOT NULL,
    side                   VARCHAR(10)  NOT NULL,
    quantity               DOUBLE PRECISION NOT NULL,
    price                  DOUBLE PRECISION NOT NULL,
    amount                 DOUBLE PRECISION NOT NULL,
    counter_party_username VARCHAR(255),
    timestamp              TIMESTAMP    NOT NULL,
    cl_ord_id              VARCHAR(255),
    is_market_maker        BOOLEAN      NOT NULL,
    open_close             VARCHAR(10),
    profit_loss            DOUBLE PRECISION,
    matched_open_exec_ids  TEXT
);
CREATE INDEX idx_trade_history_cl_ord_id        ON trade_history (cl_ord_id);
CREATE INDEX idx_trade_history_exec_id           ON trade_history (exec_id);
CREATE INDEX idx_trade_history_open_close        ON trade_history (open_close);
CREATE INDEX idx_trade_history_user_symbol_open  ON trade_history (username, symbol, open_close, timestamp);
```

**users / user_roles**（ユーザー管理）
```sql
CREATE TABLE users (
    username   VARCHAR(255) PRIMARY KEY,
    password   VARCHAR(255) NOT NULL,
    created_at TIMESTAMP    NOT NULL,
    updated_at TIMESTAMP    NOT NULL
);
CREATE TABLE user_roles (
    username VARCHAR(255) NOT NULL
        REFERENCES users(username) ON DELETE CASCADE,
    role     VARCHAR(255) NOT NULL,
    PRIMARY KEY (username, role)
);
```

---

### 02_algo_trader.sql — algo_trader スキーマ

**ml_models**（学習済みモデルの保存）
```sql
CREATE TABLE ml_models (
    id                   BIGSERIAL PRIMARY KEY,
    model_name           VARCHAR(255) NOT NULL,
    model_type           VARCHAR(100) NOT NULL,
    symbol               VARCHAR(50)  NOT NULL,
    model_data           BYTEA        NOT NULL,
    training_window_days INTEGER,
    training_start_time  TIMESTAMP,
    training_end_time    TIMESTAMP,
    metrics              JSONB,
    trained_at           TIMESTAMP    NOT NULL DEFAULT NOW(),
    is_active            BOOLEAN      NOT NULL DEFAULT FALSE,
    training_data_stats  JSONB
);
CREATE INDEX idx_ml_models_symbol_type ON ml_models (symbol, model_type);
CREATE INDEX idx_ml_models_is_active   ON ml_models (is_active);
```

---

### .env.local

```env
# ローカル Docker 用（VPS 設定を上書き）
USE_EXCH_SIM_DB=true
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=postgres123
EXCH_SIM_DB_NAME=exch_sim
ALGO_TRADER_DB_HOST=localhost
ALGO_TRADER_DB_PORT=5432
ALGO_TRADER_DB_NAME=algo_trader
ALGO_TRADER_DB_USER=postgres
ALGO_TRADER_DB_PASSWORD=postgres123
```

---

### sync_from_vps.sh — VPS → ローカル同期

#### 動作モード

| モード | コマンド | 説明 |
|--------|----------|------|
| インクリメンタル（デフォルト） | `./sync_from_vps.sh` | 直近3日分の market_board_* を同期 |
| 日数指定 | `./sync_from_vps.sh --incremental 7` | 直近7日分 |
| 全件 | `./sync_from_vps.sh --full` | 全テーブル全件を同期 |

#### 処理フロー

```
1. ローカル PostgreSQL（5432）の接続確認
   └─ 未起動なら案内メッセージ + exit 1

2. VPS SSH 接続確認
   └─ 失敗なら案内メッセージ + exit 1

3. モードに応じてテーブルごとに pg_dump（VPS側）
   ├─ market_board_snapshots     ← WHERE timestamp > NOW() - INTERVAL（市場データのみ日付フィルタ）
   ├─ market_board_price_levels  ← snapshot_id IN (上記の id)
   ├─ executions / positions / trade_history / users / user_roles
   │   ├─ --incremental: スキップ（構造変更時のみ --full で取得）
   │   └─ --full: 全件取得
   └─ 各テーブルを psql（ローカル）へパイプ

4. 重複処理: INSERT ... ON CONFLICT DO NOTHING
5. 完了メッセージ（取り込み件数を表示）
```

#### SSH 設定

VPS 接続は `~/.ssh/config` の `Host vps` エントリを使用（`HostName 77.42.74.155`, `User root`）。

---

## 使い方

### 初回セットアップ

```bash
cd algo_trader_rust/infra

# 1. コンテナ起動（初回は init SQL が自動実行される）
docker compose up -d

# 2. 起動確認
docker compose ps

# 3. VPS からデータ同期
./sync_from_vps.sh

# 4. ml_pipeline から接続テスト
cd ../vendor/ml_pipeline_snapshot_2026-04-12
cp .env .env.vps_backup           # 既存の VPS 設定をバックアップ
cp ../../infra/.env.local .env    # ローカル用設定を反映
python test_db_query.py
```

### 日常的なデータ更新

```bash
cd algo_trader_rust/infra
./sync_from_vps.sh           # 直近3日分
./sync_from_vps.sh --incremental 7  # 直近7日分
./sync_from_vps.sh --full    # 全件（初回 or 全削除後）
```

### コンテナ管理

```bash
docker compose up -d    # 起動
docker compose down     # 停止（データは保持）
docker compose down -v  # 停止＋データ削除（リセット）
```

---

## 設定ファイルの関係

```
vendor/ml_pipeline_snapshot_2026-04-12/.env  ← VPS 接続設定（既存）
infra/.env.local                              ← ローカル用上書き設定（新規）
```

ML パイプラインを**ローカルで動かす際**は `infra/.env.local` の内容を `.env` に反映して使う。  
VPS 接続に戻すときは元の `.env` に戻す。（将来的に `python-dotenv` の `override` 機能で自動化可能）

---

## 注意事項

- `infra/.env.local` は `.gitignore` に追加すること（パスワード含むため）
- VPS の `exch_sim` に `algo_trader` DB は存在しない（ローカル専用）
- `market_board_price_levels` は snapshot との FK 制約あり。sync 時は snapshots → price_levels の順で挿入する
- 現在 VPS のデータは本日分のみ（約33K スナップショット）。`MIN_SAMPLES=1000` は満たしているため ML テスト可能

---

## 完了条件

- [ ] `docker compose up -d` で PostgreSQL が起動する
- [ ] `exch_sim` / `algo_trader` 両 DB が自動作成される
- [ ] `./sync_from_vps.sh` でデータが取り込まれる
- [ ] `python test_db_query.py` でクエリが通る
- [ ] `training/daily_trainer.py` でモデル学習が完走する
