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
VPS_HOST="vps"
VPS_PSQL="sudo -u postgres psql -d exch_sim"

MODE="--incremental"
DAYS=3

# ----- 引数パース -----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --full)        MODE="--full";        shift ;;
        --incremental) MODE="--incremental"; shift
            if [[ $# -gt 0 ]]; then
                [[ "$1" =~ ^[0-9]+$ ]] || { echo "ERROR: DAYS は正の整数で指定してください（例: --incremental 7）"; exit 1; }
                DAYS="$1"; shift
            fi
            ;;
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

# ----- フル同期 -----
if [[ "${MODE}" == "--full" ]]; then
    echo "[3/5] ローカル exch_sim を TRUNCATE..."
    psql "${LOCAL_EXCH_SIM}" -c "
        TRUNCATE TABLE
            market_board_price_levels,
            market_board_snapshots,
            trade_history,
            executions,
            positions,
            user_roles,
            users
        RESTART IDENTITY CASCADE;
    "
    echo "  完了"

    echo "[4/5] VPS から全テーブルをコピー..."

    # prediction_tracker_* は VPS に存在しないためコピーしない（ローカルで ML パイプラインが生成）

    # users → user_roles（FK 順）
    echo "  コピー中: users..."
    ssh "${VPS_HOST}" "${VPS_PSQL} -c \"\COPY (SELECT username, password, created_at, updated_at FROM users) TO stdout\"" \
        | psql "${LOCAL_EXCH_SIM}" -c "\COPY users (username, password, created_at, updated_at) FROM stdin"

    echo "  コピー中: user_roles..."
    ssh "${VPS_HOST}" "${VPS_PSQL} -c \"\COPY (SELECT username, role FROM user_roles) TO stdout\"" \
        | psql "${LOCAL_EXCH_SIM}" -c "\COPY user_roles (username, role) FROM stdin"

    # market_board_snapshots → market_board_price_levels（FK 順）
    echo "  コピー中: market_board_snapshots..."
    ssh "${VPS_HOST}" "${VPS_PSQL} -c \"\COPY (SELECT id, symbol, timestamp FROM market_board_snapshots ORDER BY id) TO stdout\"" \
        | psql "${LOCAL_EXCH_SIM}" -c "\COPY market_board_snapshots (id, symbol, timestamp) FROM stdin"

    echo "  コピー中: market_board_price_levels..."
    ssh "${VPS_HOST}" "${VPS_PSQL} -c \"\COPY (SELECT id, snapshot_id, price, quantity, side, level_index FROM market_board_price_levels ORDER BY id) TO stdout\"" \
        | psql "${LOCAL_EXCH_SIM}" -c "\COPY market_board_price_levels (id, snapshot_id, price, quantity, side, level_index) FROM stdin"

    # 独立テーブル
    echo "  コピー中: executions..."
    ssh "${VPS_HOST}" "${VPS_PSQL} -c \"\COPY (SELECT exec_id, order_id, username, symbol, exec_status, last_px, last_qty, counter_party_username, created_at, is_market_maker, side FROM executions) TO stdout\"" \
        | psql "${LOCAL_EXCH_SIM}" -c "\COPY executions (exec_id, order_id, username, symbol, exec_status, last_px, last_qty, counter_party_username, created_at, is_market_maker, side) FROM stdin"

    echo "  コピー中: positions..."
    ssh "${VPS_HOST}" "${VPS_PSQL} -c \"\COPY (SELECT id, username, symbol, unit, total_buy_qty, total_buy_amount, total_sell_qty, total_sell_amount, net_qty, average_buy_price, average_sell_price, realized_pnl, last_updated FROM positions) TO stdout\"" \
        | psql "${LOCAL_EXCH_SIM}" -c "\COPY positions (id, username, symbol, unit, total_buy_qty, total_buy_amount, total_sell_qty, total_sell_amount, net_qty, average_buy_price, average_sell_price, realized_pnl, last_updated) FROM stdin"

    echo "  コピー中: trade_history..."
    ssh "${VPS_HOST}" "${VPS_PSQL} -c \"\COPY (SELECT exec_id, username, symbol, side, quantity, price, amount, counter_party_username, timestamp, cl_ord_id, is_market_maker, open_close, profit_loss, matched_open_exec_ids FROM trade_history) TO stdout\"" \
        | psql "${LOCAL_EXCH_SIM}" -c "\COPY trade_history (exec_id, username, symbol, side, quantity, price, amount, counter_party_username, timestamp, cl_ord_id, is_market_maker, open_close, profit_loss, matched_open_exec_ids) FROM stdin"

    # シーケンスをリセット
    psql "${LOCAL_EXCH_SIM}" -c "
        SELECT setval('market_board_snapshots_id_seq',    COALESCE(MAX(id), 1)) FROM market_board_snapshots;
        SELECT setval('market_board_price_levels_id_seq', COALESCE(MAX(id), 1)) FROM market_board_price_levels;
    " > /dev/null

# ----- インクリメンタル同期 -----
else
    echo "[3/5] ローカルの最大 snapshot ID を取得..."
    LOCAL_MAX_ID=$(psql "${LOCAL_EXCH_SIM}" -t -c "SELECT COALESCE(MAX(id), 0) FROM market_board_snapshots;" | tr -d ' \n')
    echo "  ローカル最大 snapshot id = ${LOCAL_MAX_ID}"

    echo "[4/5] VPS から差分をコピー（直近 ${DAYS} 日分、id > ${LOCAL_MAX_ID}）..."

    # market_board_snapshots: 日付フィルタ AND id > ローカル最大
    ssh "${VPS_HOST}" "${VPS_PSQL} -c \"\COPY (
        SELECT id, symbol, timestamp FROM market_board_snapshots
        WHERE timestamp > NOW() - INTERVAL '${DAYS} days'
          AND id > ${LOCAL_MAX_ID}
        ORDER BY id
    ) TO stdout\"" \
        | psql "${LOCAL_EXCH_SIM}" -c "\COPY market_board_snapshots (id, symbol, timestamp) FROM stdin"

    # 新しい最大 id を取得
    NEW_MAX_ID=$(psql "${LOCAL_EXCH_SIM}" -t -c "SELECT COALESCE(MAX(id), 0) FROM market_board_snapshots;" | tr -d ' \n')
    echo "  取得後の最大 snapshot id = ${NEW_MAX_ID}"

    if [[ "${NEW_MAX_ID}" -gt "${LOCAL_MAX_ID}" ]]; then
        # market_board_price_levels: 新しい snapshots に対応する分のみ
        ssh "${VPS_HOST}" "${VPS_PSQL} -c \"\COPY (
            SELECT id, snapshot_id, price, quantity, side, level_index
            FROM market_board_price_levels
            WHERE snapshot_id > ${LOCAL_MAX_ID}
              AND snapshot_id <= ${NEW_MAX_ID}
            ORDER BY id
        ) TO stdout\"" \
            | psql "${LOCAL_EXCH_SIM}" -c "\COPY market_board_price_levels (id, snapshot_id, price, quantity, side, level_index) FROM stdin"

    else
        echo "  新規データなし（price_levels スキップ）"
    fi
    # prediction_tracker_* は VPS に存在しないためスキップ（ローカル生成データ）

    # シーケンスをリセット（新規データがなくてもリセット）
    psql "${LOCAL_EXCH_SIM}" -c "
        SELECT setval('market_board_snapshots_id_seq',    COALESCE(MAX(id), 1)) FROM market_board_snapshots;
        SELECT setval('market_board_price_levels_id_seq', COALESCE(MAX(id), 1)) FROM market_board_price_levels;
    " > /dev/null
fi

# ----- 完了レポート -----
echo "[5/5] 完了レポート"
psql "${LOCAL_EXCH_SIM}" -c "
    SELECT 'market_board_snapshots'         AS table_name, COUNT(*) AS rows FROM market_board_snapshots
    UNION ALL
    SELECT 'market_board_price_levels'      AS table_name, COUNT(*) AS rows FROM market_board_price_levels
    UNION ALL
    SELECT 'executions'                     AS table_name, COUNT(*) AS rows FROM executions
    UNION ALL
    SELECT 'positions'                      AS table_name, COUNT(*) AS rows FROM positions
    UNION ALL
    SELECT 'trade_history'                  AS table_name, COUNT(*) AS rows FROM trade_history
    UNION ALL
    SELECT 'users'                          AS table_name, COUNT(*) AS rows FROM users
    UNION ALL
    SELECT 'user_roles'                     AS table_name, COUNT(*) AS rows FROM user_roles
    UNION ALL
    SELECT 'prediction_tracker_predictions' AS table_name, COUNT(*) AS rows FROM prediction_tracker_predictions
    UNION ALL
    SELECT 'prediction_tracker_verifications' AS table_name, COUNT(*) AS rows FROM prediction_tracker_verifications
    ORDER BY table_name;
"
echo "=========================================="
echo "  同期完了"
echo "=========================================="
