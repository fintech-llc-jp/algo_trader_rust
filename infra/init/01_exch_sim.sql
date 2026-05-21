-- =============================================================
-- exch_sim データベース作成と全テーブル定義
-- VPS の exch_sim スキーマを完全再現（2026-05-20 取得）
-- =============================================================

CREATE DATABASE exch_sim;
\c exch_sim

-- ----- 市場データ（ML 学習の主要入力） -----

CREATE TABLE IF NOT EXISTS market_board_snapshots (
    id        BIGSERIAL PRIMARY KEY,
    symbol    VARCHAR(50) NOT NULL,
    timestamp TIMESTAMP   NOT NULL
);
CREATE INDEX idx_market_board_snapshots_symbol_timestamp
    ON market_board_snapshots (symbol, timestamp);

CREATE TABLE IF NOT EXISTS market_board_price_levels (
    id          BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT           NOT NULL
        REFERENCES market_board_snapshots(id) ON DELETE CASCADE,
    price       DOUBLE PRECISION NOT NULL,
    quantity    DOUBLE PRECISION NOT NULL,
    side        VARCHAR(3)       NOT NULL,
    level_index INTEGER          NOT NULL
);
-- FK カラムへのインデックス（JOIN クエリの高速化）
CREATE INDEX idx_market_board_price_levels_snapshot_id
    ON market_board_price_levels (snapshot_id);

-- ----- 約定履歴 -----

CREATE TABLE IF NOT EXISTS executions (
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

CREATE TABLE IF NOT EXISTS positions (
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

CREATE TABLE IF NOT EXISTS trade_history (
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

CREATE TABLE IF NOT EXISTS users (
    username   VARCHAR(255) PRIMARY KEY,
    password   VARCHAR(255) NOT NULL,
    created_at TIMESTAMP    NOT NULL,
    updated_at TIMESTAMP    NOT NULL
);

CREATE TABLE IF NOT EXISTS user_roles (
    username VARCHAR(255) NOT NULL
        REFERENCES users(username) ON DELETE CASCADE,
    role     VARCHAR(255) NOT NULL,
    PRIMARY KEY (username, role)
);

-- ----- 予測トラッカー（prediction_tracker.py が使用） -----

CREATE TABLE IF NOT EXISTS prediction_tracker_predictions (
    id                   BIGSERIAL        PRIMARY KEY,
    symbol               VARCHAR(50)      NOT NULL,
    horizon              VARCHAR(20)      NOT NULL,
    prediction_timestamp TIMESTAMP        NOT NULL,
    target_timestamp     TIMESTAMP        NOT NULL,
    current_price        DOUBLE PRECISION NOT NULL,
    predicted_price      DOUBLE PRECISION NOT NULL,
    price_change_pct     DOUBLE PRECISION,
    prev_error           DOUBLE PRECISION,
    is_feedback_enabled  BOOLEAN          NOT NULL DEFAULT FALSE
);
CREATE INDEX idx_prediction_tracker_predictions_symbol_horizon
    ON prediction_tracker_predictions (symbol, horizon, prediction_timestamp);

CREATE TABLE IF NOT EXISTS prediction_tracker_verifications (
    id                   BIGSERIAL        PRIMARY KEY,
    prediction_id        BIGINT           NOT NULL
        REFERENCES prediction_tracker_predictions(id) ON DELETE CASCADE,
    symbol               VARCHAR(50)      NOT NULL,
    horizon              VARCHAR(20)      NOT NULL,
    prediction_timestamp TIMESTAMP        NOT NULL,
    target_timestamp     TIMESTAMP        NOT NULL,
    actual_timestamp     TIMESTAMP        NOT NULL,
    predicted_price      DOUBLE PRECISION NOT NULL,
    actual_price         DOUBLE PRECISION NOT NULL,
    error                DOUBLE PRECISION NOT NULL,
    error_pct            DOUBLE PRECISION NOT NULL
);
CREATE INDEX idx_prediction_tracker_verifications_symbol
    ON prediction_tracker_verifications (symbol, horizon, prediction_timestamp);
CREATE INDEX idx_prediction_tracker_verifications_prediction_id
    ON prediction_tracker_verifications (prediction_id);
