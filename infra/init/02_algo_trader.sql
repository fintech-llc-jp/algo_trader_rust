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
