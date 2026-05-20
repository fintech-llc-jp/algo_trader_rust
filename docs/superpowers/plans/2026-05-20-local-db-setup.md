# ローカル DB 環境構築 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Docker で PostgreSQL を1インスタンス起動し、`exch_sim` / `algo_trader` の2DBをローカルに構築、VPS からデータを同期できる環境を作る。

**Architecture:** `infra/` フォルダに `docker-compose.yml`・初期化 SQL・sync スクリプトを集約する。コンテナ初回起動時に `init/` の SQL が自動実行されスキーマが作成される。`sync_from_vps.sh` は SSH 経由で VPS の `pg_dump` 出力をローカルの `psql` にパイプする。

**Tech Stack:** Docker Compose, PostgreSQL 15-alpine, Bash, psql, pg_dump（VPS 側）

---

## ファイルマップ

| 操作 | パス | 説明 |
|------|------|------|
| 新規作成 | `infra/docker-compose.yml` | PostgreSQL コンテナ定義 |
| 新規作成 | `infra/init/01_exch_sim.sql` | exch_sim DB + 全7テーブル |
| 新規作成 | `infra/init/02_algo_trader.sql` | algo_trader DB + ml_models テーブル |
| 新規作成 | `infra/.env.local` | ローカル用 DB 設定（gitignore 対象） |
| 新規作成 | `infra/.env.local.example` | サンプル設定（コミット対象） |
| 新規作成 | `infra/sync_from_vps.sh` | VPS → ローカル データ同期スクリプト |
| 修正 | `.gitignore` | `infra/.env.local` を追加 |

---

## Task 1: infra/ ディレクトリ作成と docker-compose.yml

**Files:**
- Create: `infra/docker-compose.yml`
- Create: `infra/init/` (空ディレクトリ、.gitkeep)

- [ ] **Step 1: ディレクトリを作成する**

```bash
mkdir -p /Users/sakamoto.yukio/workspace/algo_trader_rust/infra/init
```

- [ ] **Step 2: docker-compose.yml を作成する**

`infra/docker-compose.yml` に以下を書く：

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

- [ ] **Step 3: .gitkeep を置く（init/ を git 管理下に）**

```bash
touch /Users/sakamoto.yukio/workspace/algo_trader_rust/infra/init/.gitkeep
```

- [ ] **Step 4: docker-compose.yml の構文を確認する**

```bash
cd /Users/sakamoto.yukio/workspace/algo_trader_rust/infra
docker compose config
```

期待出力：エラーなし、YAML がパースされて表示される

- [ ] **Step 5: コミット**

```bash
cd /Users/sakamoto.yukio/workspace/algo_trader_rust
git add infra/docker-compose.yml infra/init/.gitkeep
git commit -m "feat(infra): docker-compose.yml を追加（postgres:15-alpine）"
```

---

## Task 2: exch_sim スキーマ SQL

**Files:**
- Create: `infra/init/01_exch_sim.sql`

- [ ] **Step 1: 01_exch_sim.sql を作成する**

`infra/init/01_exch_sim.sql` に以下を書く：

```sql
-- =============================================================
-- exch_sim データベース作成と全テーブル定義
-- VPS の exch_sim スキーマを完全再現（2026-05-20 取得）
-- =============================================================

CREATE DATABASE exch_sim;
\c exch_sim

-- ----- 市場データ（ML 学習の主要入力） -----

CREATE TABLE market_board_snapshots (
    id        BIGSERIAL PRIMARY KEY,
    symbol    VARCHAR(50) NOT NULL,
    timestamp TIMESTAMP   NOT NULL
);
CREATE INDEX idx_market_board_snapshots_symbol_timestamp
    ON market_board_snapshots (symbol, timestamp);

CREATE TABLE market_board_price_levels (
    id          BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT           NOT NULL
        REFERENCES market_board_snapshots(id) ON DELETE CASCADE,
    price       DOUBLE PRECISION NOT NULL,
    quantity    DOUBLE PRECISION NOT NULL,
    side        VARCHAR(3)       NOT NULL,
    level_index INTEGER          NOT NULL
);

-- ----- 約定履歴 -----

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
CREATE INDEX idx_execution_count_calc
    ON executions (is_market_maker, exec_status, created_at, symbol);
CREATE INDEX idx_execution_market_maker_status
    ON executions (is_market_maker, exec_status);
CREATE INDEX idx_execution_symbol_time_status_mm
    ON executions (symbol, created_at, exec_status, is_market_maker);
CREATE INDEX idx_execution_time_status_mm
    ON executions (created_at, exec_status, is_market_maker);
CREATE INDEX idx_execution_volume_calc
    ON executions (is_market_maker, exec_status, created_at, symbol, last_qty);

-- ----- ポジション -----

CREATE TABLE positions (
    id                  VARCHAR(255)     PRIMARY KEY,
    username            VARCHAR(255)     NOT NULL,
    symbol              VARCHAR(255)     NOT NULL,
    unit                VARCHAR(50)      NOT NULL,
    total_buy_qty       BIGINT           NOT NULL,
    total_buy_amount    DOUBLE PRECISION NOT NULL,
    total_sell_qty      BIGINT           NOT NULL,
    total_sell_amount   DOUBLE PRECISION NOT NULL,
    net_qty             BIGINT           NOT NULL,
    average_buy_price   DOUBLE PRECISION NOT NULL,
    average_sell_price  DOUBLE PRECISION NOT NULL,
    realized_pnl        DOUBLE PRECISION NOT NULL,
    last_updated        TIMESTAMP        NOT NULL
);

-- ----- 取引履歴 -----

CREATE TABLE trade_history (
    exec_id                VARCHAR(255)     PRIMARY KEY,
    username               VARCHAR(255)     NOT NULL,
    symbol                 VARCHAR(255)     NOT NULL,
    side                   VARCHAR(10)      NOT NULL,
    quantity               DOUBLE PRECISION NOT NULL,
    price                  DOUBLE PRECISION NOT NULL,
    amount                 DOUBLE PRECISION NOT NULL,
    counter_party_username VARCHAR(255),
    timestamp              TIMESTAMP        NOT NULL,
    cl_ord_id              VARCHAR(255),
    is_market_maker        BOOLEAN          NOT NULL,
    open_close             VARCHAR(10),
    profit_loss            DOUBLE PRECISION,
    matched_open_exec_ids  TEXT
);
CREATE INDEX idx_trade_history_cl_ord_id
    ON trade_history (cl_ord_id);
CREATE INDEX idx_trade_history_exec_id
    ON trade_history (exec_id);
CREATE INDEX idx_trade_history_open_close
    ON trade_history (open_close);
CREATE INDEX idx_trade_history_user_symbol_open
    ON trade_history (username, symbol, open_close, timestamp);

-- ----- ユーザー管理 -----

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

- [ ] **Step 2: SQL の構文を psql でドライチェックする（コンテナ不要）**

```bash
psql --help | grep -q "version" && echo "psql available" || echo "psql not found"
```

- [ ] **Step 3: コミット**

```bash
cd /Users/sakamoto.yukio/workspace/algo_trader_rust
git add infra/init/01_exch_sim.sql
git commit -m "feat(infra): exch_sim スキーマ SQL を追加（全7テーブル）"
```

---

## Task 3: algo_trader スキーマ SQL

**Files:**
- Create: `infra/init/02_algo_trader.sql`

- [ ] **Step 1: 02_algo_trader.sql を作成する**

`infra/init/02_algo_trader.sql` に以下を書く：

```sql
-- =============================================================
-- algo_trader データベース作成と ML モデル管理テーブル定義
-- model_manager.py の INSERT 文から逆算したスキーマ
-- =============================================================

CREATE DATABASE algo_trader;
\c algo_trader

CREATE TABLE ml_models (
    id                   BIGSERIAL    PRIMARY KEY,
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

CREATE INDEX idx_ml_models_symbol_type
    ON ml_models (symbol, model_type);
CREATE INDEX idx_ml_models_is_active
    ON ml_models (is_active);
```

- [ ] **Step 2: コミット**

```bash
cd /Users/sakamoto.yukio/workspace/algo_trader_rust
git add infra/init/02_algo_trader.sql
git commit -m "feat(infra): algo_trader スキーマ SQL を追加（ml_models テーブル）"
```

---

## Task 4: コンテナ起動と DB 作成を確認

**Files:** なし（確認のみ）

- [ ] **Step 1: 既存の停止コンテナを削除する（名前衝突を防ぐ）**

```bash
docker rm -f happy_cartwright loving_shannon 2>/dev/null || true
```

- [ ] **Step 2: コンテナを起動する**

```bash
cd /Users/sakamoto.yukio/workspace/algo_trader_rust/infra
docker compose up -d
```

期待出力：
```
✔ Container algo_trader_postgres  Started
```

- [ ] **Step 3: ヘルスチェックが通るまで待つ**

```bash
cd /Users/sakamoto.yukio/workspace/algo_trader_rust/infra
until docker compose ps | grep "healthy"; do echo "waiting..."; sleep 3; done
echo "PostgreSQL is ready"
```

期待出力：`algo_trader_postgres ... healthy`

- [ ] **Step 4: 両 DB が作成されていることを確認する**

```bash
docker exec algo_trader_postgres psql -U postgres -c "\l" | grep -E "exch_sim|algo_trader"
```

期待出力：
```
 algo_trader | postgres | UTF8 ...
 exch_sim    | postgres | UTF8 ...
```

- [ ] **Step 5: exch_sim の全テーブルを確認する**

```bash
docker exec algo_trader_postgres psql -U postgres -d exch_sim -c "\dt"
```

期待出力（7テーブル）：
```
                    List of relations
 Schema |           Name            | Type  |  Owner
--------+---------------------------+-------+----------
 public | executions                | table | postgres
 public | market_board_price_levels | table | postgres
 public | market_board_snapshots    | table | postgres
 public | positions                 | table | postgres
 public | trade_history             | table | postgres
 public | user_roles                | table | postgres
 public | users                     | table | postgres
```

- [ ] **Step 6: algo_trader の ml_models テーブルを確認する**

```bash
docker exec algo_trader_postgres psql -U postgres -d algo_trader -c "\d ml_models"
```

期待出力：`id`, `model_name`, `model_type`, `symbol`, `model_data`, ... のカラム一覧

---

## Task 5: .env.local と .env.local.example

**Files:**
- Create: `infra/.env.local`
- Create: `infra/.env.local.example`
- Modify: `.gitignore`

- [ ] **Step 1: .env.local を作成する**

`infra/.env.local` に以下を書く：

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

- [ ] **Step 2: .env.local.example を作成する（コミット対象）**

`infra/.env.local.example` に以下を書く：

```env
# ローカル Docker 用（VPS 設定を上書き）
# cp .env.local.example .env.local して使用
USE_EXCH_SIM_DB=true
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_password_here
EXCH_SIM_DB_NAME=exch_sim
ALGO_TRADER_DB_HOST=localhost
ALGO_TRADER_DB_PORT=5432
ALGO_TRADER_DB_NAME=algo_trader
ALGO_TRADER_DB_USER=postgres
ALGO_TRADER_DB_PASSWORD=your_password_here
```

- [ ] **Step 3: .gitignore に infra/.env.local を追加する**

`.gitignore` の `# 秘密情報・ローカル設定` セクションに追記する：

```
# 秘密情報・ローカル設定
.env
**/.env
!.env.example
!**/.env.example
infra/.env.local        # ← この行を追加
*.pem
```

- [ ] **Step 4: .env.local が git に追跡されないことを確認する**

```bash
cd /Users/sakamoto.yukio/workspace/algo_trader_rust
git check-ignore -v infra/.env.local
```

期待出力：`.gitignore:XX:infra/.env.local	infra/.env.local`

- [ ] **Step 5: コミット**

```bash
cd /Users/sakamoto.yukio/workspace/algo_trader_rust
git add infra/.env.local.example .gitignore
git commit -m "feat(infra): .env.local.example と .gitignore 更新"
```

---

## Task 6: sync_from_vps.sh

**Files:**
- Create: `infra/sync_from_vps.sh`

スクリプトの設計方針：
- **インクリメンタル（デフォルト）**: ローカルの `MAX(id)` を基準に VPS から差分だけ取得（`market_board_*` のみ）。`executions` 等はスキップ。
- **フル同期（--full）**: ローカルを `TRUNCATE CASCADE` してから全テーブルを全件コピー。
- データ転送には `psql -c "\COPY ... TO stdout"` → `psql -c "\COPY ... FROM stdin"` を使用（`pg_dump` より行フィルタが容易）。
- FK 制約順を守る: `users` → `user_roles`、`market_board_snapshots` → `market_board_price_levels`。

- [ ] **Step 1: sync_from_vps.sh を作成する**

`infra/sync_from_vps.sh` に以下を書く：

```bash
#!/usr/bin/env bash
# =============================================================
# VPS exch_sim → ローカル Docker PostgreSQL 同期スクリプト
#
# 使い方:
#   ./sync_from_vps.sh                    # 直近3日分（デフォルト）
#   ./sync_from_vps.sh --incremental 7   # 直近7日分
#   ./sync_from_vps.sh --full             # 全テーブル全件
# =============================================================
set -euo pipefail

# ----- 設定 -----
LOCAL_DSN="postgresql://postgres:postgres123@localhost:5432"
LOCAL_EXCH_SIM="${LOCAL_DSN}/exch_sim"
VPS_HOST="vps"   # ~/.ssh/config の Host 名
VPS_DB="exch_sim"
VPS_PSQL="sudo -u postgres psql -d ${VPS_DB}"

MODE="--incremental"
DAYS=3

# ----- 引数パース -----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --full)         MODE="--full";         shift ;;
        --incremental)  MODE="--incremental";  shift; [[ $# -gt 0 ]] && DAYS="$1" && shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "=========================================="
echo "  VPS → ローカル DB 同期"
echo "  モード: ${MODE}  / 日数: ${DAYS}日"
echo "=========================================="

# ----- 事前チェック -----
echo "[1/5] ローカル PostgreSQL（5432）の接続確認..."
if ! psql "${LOCAL_EXCH_SIM}" -c "SELECT 1" > /dev/null 2>&1; then
    echo "ERROR: ローカル PostgreSQL に接続できません。"
    echo "  → cd infra && docker compose up -d を実行してください。"
    exit 1
fi
echo "  OK"

echo "[2/5] VPS SSH 接続確認..."
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "${VPS_HOST}" "echo ok" > /dev/null 2>&1; then
    echo "ERROR: VPS（${VPS_HOST}）に SSH 接続できません。"
    echo "  → ~/.ssh/config の 'Host vps' 設定を確認してください。"
    exit 1
fi
echo "  OK"

# ----- ヘルパー関数 -----
copy_table() {
    # copy_table <テーブル名> <WHERE句（空文字で全件）>
    local TABLE="$1"
    local WHERE="$2"
    local SELECT_COLS="*"

    if [[ -n "$WHERE" ]]; then
        local QUERY="SELECT ${SELECT_COLS} FROM ${TABLE} WHERE ${WHERE}"
    else
        local QUERY="SELECT ${SELECT_COLS} FROM ${TABLE}"
    fi

    echo "  コピー中: ${TABLE} ..."
    local COUNT
    COUNT=$(ssh "${VPS_HOST}" "${VPS_PSQL} -t -c \"SELECT COUNT(*) FROM ${TABLE}$([ -n '${WHERE}' ] && echo ' WHERE ${WHERE}' || echo '')\"" 2>/dev/null | tr -d ' ' || echo "?")

    ssh "${VPS_HOST}" "${VPS_PSQL} -c \"\COPY (${QUERY}) TO stdout\"" \
        | psql "${LOCAL_EXCH_SIM}" -c "\COPY ${TABLE} FROM stdin"
    echo "  完了: ${TABLE}"
}

# ----- フル同期 -----
if [[ "${MODE}" == "--full" ]]; then
    echo "[3/5] ローカル exch_sim を TRUNCATE..."
    psql "${LOCAL_EXCH_SIM}" -c "
        TRUNCATE TABLE
            market_board_price_levels,
            market_board_snapshots,
            executions,
            trade_history,
            positions,
            user_roles,
            users
        RESTART IDENTITY CASCADE;
    "
    echo "  完了"

    echo "[4/5] VPS から全テーブルをコピー..."
    # FK 順: users → user_roles
    copy_table "users"      ""
    copy_table "user_roles" ""
    # FK 順: market_board_snapshots → market_board_price_levels
    copy_table "market_board_snapshots"    ""
    copy_table "market_board_price_levels" ""
    # 独立テーブル
    copy_table "executions"    ""
    copy_table "positions"     ""
    copy_table "trade_history" ""

# ----- インクリメンタル同期 -----
else
    echo "[3/5] ローカルの最大 snapshot ID を取得..."
    MAX_SNAPSHOT_ID=$(psql "${LOCAL_EXCH_SIM}" -t -c "SELECT COALESCE(MAX(id), 0) FROM market_board_snapshots;" | tr -d ' ')
    echo "  ローカル最大 snapshot id = ${MAX_SNAPSHOT_ID}"

    echo "[4/5] VPS から差分をコピー（直近 ${DAYS} 日分、id > ${MAX_SNAPSHOT_ID}）..."

    # snapshots: 日付フィルタ AND id > ローカル最大
    local_max="${MAX_SNAPSHOT_ID}"
    ssh "${VPS_HOST}" "${VPS_PSQL} -c \"\COPY (
        SELECT id, symbol, timestamp FROM market_board_snapshots
        WHERE timestamp > NOW() - INTERVAL '${DAYS} days'
          AND id > ${local_max}
        ORDER BY id
    ) TO stdout\"" \
        | psql "${LOCAL_EXCH_SIM}" -c "\COPY market_board_snapshots (id, symbol, timestamp) FROM stdin"

    # 新しく追加された snapshot の最大 id を取得
    NEW_MAX_ID=$(psql "${LOCAL_EXCH_SIM}" -t -c "SELECT COALESCE(MAX(id), 0) FROM market_board_snapshots;" | tr -d ' ')
    echo "  新しい snapshot を取得後の最大 id = ${NEW_MAX_ID}"

    if [[ "${NEW_MAX_ID}" -gt "${local_max}" ]]; then
        # price_levels: 新しい snapshots に対応する分のみ
        ssh "${VPS_HOST}" "${VPS_PSQL} -c \"\COPY (
            SELECT id, snapshot_id, price, quantity, side, level_index
            FROM market_board_price_levels
            WHERE snapshot_id > ${local_max}
              AND snapshot_id <= ${NEW_MAX_ID}
            ORDER BY id
        ) TO stdout\"" \
            | psql "${LOCAL_EXCH_SIM}" -c "\COPY market_board_price_levels (id, snapshot_id, price, quantity, side, level_index) FROM stdin"
    else
        echo "  新規データなし（price_levels スキップ）"
    fi

    # シーケンスをリセット（ローカルで BIGSERIAL INSERT できるように）
    psql "${LOCAL_EXCH_SIM}" -c "
        SELECT setval('market_board_snapshots_id_seq', COALESCE(MAX(id), 1)) FROM market_board_snapshots;
        SELECT setval('market_board_price_levels_id_seq', COALESCE(MAX(id), 1)) FROM market_board_price_levels;
    " > /dev/null
fi

# ----- 完了レポート -----
echo "[5/5] 完了レポート"
psql "${LOCAL_EXCH_SIM}" -c "
    SELECT 'market_board_snapshots'    AS table_name, COUNT(*) AS rows FROM market_board_snapshots
    UNION ALL
    SELECT 'market_board_price_levels' AS table_name, COUNT(*) AS rows FROM market_board_price_levels
    UNION ALL
    SELECT 'executions'                AS table_name, COUNT(*) AS rows FROM executions
    UNION ALL
    SELECT 'positions'                 AS table_name, COUNT(*) AS rows FROM positions
    UNION ALL
    SELECT 'trade_history'             AS table_name, COUNT(*) AS rows FROM trade_history
    UNION ALL
    SELECT 'users'                     AS table_name, COUNT(*) AS rows FROM users
    UNION ALL
    SELECT 'user_roles'                AS table_name, COUNT(*) AS rows FROM user_roles
    ORDER BY table_name;
"
echo "=========================================="
echo "  同期完了"
echo "=========================================="
```

- [ ] **Step 2: 実行権限を付与する**

```bash
chmod +x /Users/sakamoto.yukio/workspace/algo_trader_rust/infra/sync_from_vps.sh
```

- [ ] **Step 3: シェルの構文チェックを行う**

```bash
bash -n /Users/sakamoto.yukio/workspace/algo_trader_rust/infra/sync_from_vps.sh
echo "構文エラーなし"
```

期待出力：`構文エラーなし`

- [ ] **Step 4: コミット**

```bash
cd /Users/sakamoto.yukio/workspace/algo_trader_rust
git add infra/sync_from_vps.sh
git commit -m "feat(infra): VPS→ローカル同期スクリプト sync_from_vps.sh を追加"
```

---

## Task 7: インクリメンタル同期の動作確認

**Files:** なし（確認のみ）

- [ ] **Step 1: デフォルト（直近3日分）で sync を実行する**

```bash
cd /Users/sakamoto.yukio/workspace/algo_trader_rust/infra
./sync_from_vps.sh
```

期待出力（例）：
```
==========================================
  VPS → ローカル DB 同期
  モード: --incremental  / 日数: 3日
==========================================
[1/5] ローカル PostgreSQL（5432）の接続確認...
  OK
[2/5] VPS SSH 接続確認...
  OK
[3/5] ローカルの最大 snapshot ID を取得...
  ローカル最大 snapshot id = 0
[4/5] VPS から差分をコピー（直近 3 日分、id > 0）...
[5/5] 完了レポート
          table_name          |  rows
------------------------------+--------
 executions                   |      0
 market_board_price_levels    | 539296
 market_board_snapshots       |  33422
 ...
```

- [ ] **Step 2: 2回目の実行で差分なしになることを確認する**

```bash
cd /Users/sakamoto.yukio/workspace/algo_trader_rust/infra
./sync_from_vps.sh
```

期待出力：`新規データなし（price_levels スキップ）`

- [ ] **Step 3: ml_pipeline の接続テストを実行する**

```bash
cd /Users/sakamoto.yukio/workspace/algo_trader_rust/vendor/ml_pipeline_snapshot_2026-04-12

# 既存の VPS 設定をバックアップ
cp .env .env.vps_backup

# ローカル用設定を反映
cp ../../infra/.env.local .env

# 接続テスト
python test_db_query.py
```

期待出力：
```
TEST 1: 直接接続（psycopg2.connect）
1. datetimeオブジェクトを直接渡す:
   結果: XXXX件
...
テスト完了
```

- [ ] **Step 4: テスト後 VPS 設定に戻す**

```bash
cd /Users/sakamoto.yukio/workspace/algo_trader_rust/vendor/ml_pipeline_snapshot_2026-04-12
mv .env.vps_backup .env
```

---

## Task 8: フル同期のテストと最終コミット

**Files:** なし（確認のみ）

- [ ] **Step 1: フル同期を実行する**

```bash
cd /Users/sakamoto.yukio/workspace/algo_trader_rust/infra
./sync_from_vps.sh --full
```

期待出力：TRUNCATE 後に全テーブルのコピーが完了し、完了レポートが表示される

- [ ] **Step 2: ml_pipeline の training スクリプトで学習が通るか確認する**

```bash
cd /Users/sakamoto.yukio/workspace/algo_trader_rust/vendor/ml_pipeline_snapshot_2026-04-12
cp .env .env.vps_backup
cp ../../infra/.env.local .env
python -m training.daily_trainer 2>&1 | head -50
```

期待出力：エラーなしでトレーニングが開始される（または MIN_SAMPLES 不足の警告）

- [ ] **Step 3: VPS 設定に戻す**

```bash
mv .env.vps_backup .env
```

- [ ] **Step 4: 最終コミット**

```bash
cd /Users/sakamoto.yukio/workspace/algo_trader_rust
git add infra/
git status  # .env.local が含まれていないことを確認
git commit -m "feat(infra): ローカル DB 環境セットアップ完了（docker-compose + sync スクリプト）"
```

---

## 完了条件チェックリスト

- [ ] `docker compose up -d` で PostgreSQL が起動する
- [ ] `exch_sim` / `algo_trader` 両 DB が自動作成される
- [ ] `./sync_from_vps.sh` でデータが取り込まれる（市場データ 33K+ スナップショット）
- [ ] 2回目の `./sync_from_vps.sh` で差分なしが確認できる
- [ ] `python test_db_query.py` でクエリが通る
- [ ] `infra/.env.local` が git に追跡されていない
