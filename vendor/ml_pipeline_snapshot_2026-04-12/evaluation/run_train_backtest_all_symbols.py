"""
全シンボル 学習 + バックテスト スクリプト

学習期間 : 2026-05-23 03:00 〜 2026-05-24 03:00（24時間・約定あり行のみ）
バックテスト期間: 2026-05-24 03:00 〜 2026-05-25 08:48（残り約30時間・全行）

使い方:
    python -m evaluation.run_train_backtest_all_symbols
    python -m evaluation.run_train_backtest_all_symbols --symbols G_FX_BTCJPY G_BTCJPY
    python -m evaluation.run_train_backtest_all_symbols \\
        --train-start "2026-05-23 03:00" --train-end "2026-05-24 03:00" \\
        --test-start  "2026-05-24 03:00" --test-end   "2026-05-25 08:48"
"""
import argparse
import io
import json
import sys
import psycopg2
import joblib
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Tuple

sys.path.insert(0, ".")

from data.data_loader import MarketDataLoader
from data.feature_engineering import FeatureEngineer
from models.momentum_model import MomentumModel
from evaluation.backtester import Backtester
from config.settings import DatabaseConfig, ModelConfig

# ──────────────────────────────────────────────────────────────
# デフォルト期間
# ──────────────────────────────────────────────────────────────
DEFAULT_TRAIN_START = datetime(2026, 5, 23, 3, 0, 0)
DEFAULT_TRAIN_END   = datetime(2026, 5, 24, 3, 0, 0)
DEFAULT_TEST_START  = datetime(2026, 5, 24, 3, 0, 0)
DEFAULT_TEST_END    = datetime(2026, 5, 25, 8, 48, 0)
DEFAULT_SYMBOLS     = ["G_FX_BTCJPY", "G_BTCJPY", "B_FX_BTCJPY", "B_BTCJPY"]

INITIAL_CAPITAL     = 10_000_000   # 1000万円
FIXED_QTY_BTC       = 0.01         # 1回の取引量
CONFIDENCE_THRESH   = 0.60         # シグナル実行の確信度閾値


# ──────────────────────────────────────────────────────────────
# ラベル生成
# ──────────────────────────────────────────────────────────────
def make_labels(mid: pd.Series, horizon: int, threshold: float) -> np.ndarray:
    future_return = mid.shift(-horizon).pct_change(horizon)
    y = np.zeros(len(mid))
    y[future_return.values >  threshold] =  1
    y[future_return.values < -threshold] = -1
    return y


# ──────────────────────────────────────────────────────────────
# 1シンボルの学習
# ──────────────────────────────────────────────────────────────
def train_symbol(
    symbol: str,
    train_start: datetime,
    train_end: datetime,
    df_train_all: pd.DataFrame,
) -> Tuple[MomentumModel, List[str], Dict]:
    """約定あり行のみで学習し、(model, feat_cols, metrics) を返す"""
    cfg = ModelConfig()

    # 約定あり行に絞る
    df = df_train_all[df_train_all["volume_total"] > 0].copy()

    future_return = df_train_all["mid_price"].shift(-cfg.LABEL_HORIZON).pct_change(cfg.LABEL_HORIZON)
    fr_exec = future_return[df_train_all["volume_total"] > 0]

    labels = np.zeros(len(df))
    labels[fr_exec.values >  cfg.LABEL_THRESHOLD] =  1
    labels[fr_exec.values < -cfg.LABEL_THRESHOLD] = -1

    feat_cols = [c for c in df.columns if c not in ["symbol", "mid_price"]]
    X = df[feat_cols].values
    y = labels

    valid = ~(np.isnan(X).any(axis=1) | np.isnan(y))
    X, y = X[valid], y[valid]
    y = y.astype(int) + 1   # -1→0(SELL), 0→1(HOLD), 1→2(BUY)

    if len(X) == 0:
        raise ValueError(f"[{symbol}] No valid training samples")

    # 訓練/検証分割（時系列 80/20）
    split = int(len(X) * 0.8)
    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]

    model = MomentumModel()
    model.feature_columns = feat_cols
    model.train(X_train, y_train, X_val, y_val)

    y_pred = model.predict(X_val)[0]
    acc     = float(np.mean(y_pred == y_val))

    from sklearn.metrics import balanced_accuracy_score, confusion_matrix
    bal_acc = float(balanced_accuracy_score(y_val, y_pred))
    cm = confusion_matrix(y_val, y_pred, labels=[0, 1, 2])

    metrics = {
        "exec_only_rows": int(len(df)),
        "train_samples":  int(len(X_train)),
        "val_samples":    int(len(X_val)),
        "accuracy":       round(acc,     4),
        "balanced_acc":   round(bal_acc, 4),
        "sell_recall":    round(float(cm[0,0]/cm[0].sum()) if cm[0].sum() else 0, 4),
        "hold_recall":    round(float(cm[1,1]/cm[1].sum()) if cm[1].sum() else 0, 4),
        "buy_recall":     round(float(cm[2,2]/cm[2].sum()) if cm[2].sum() else 0, 4),
    }

    label_dist = {
        "SELL": int((y==0).sum()),
        "HOLD": int((y==1).sum()),
        "BUY":  int((y==2).sum()),
    }
    metrics["label_dist"] = label_dist

    return model, feat_cols, metrics


# ──────────────────────────────────────────────────────────────
# 1シンボルのバックテスト
# ──────────────────────────────────────────────────────────────
def backtest_symbol(
    symbol: str,
    model: MomentumModel,
    feat_cols: List[str],
    df_test: pd.DataFrame,
    confidence_threshold: float = CONFIDENCE_THRESH,
    order_type: str = "taker",   # "taker" | "maker" | "maker-limit"
    max_hold_seconds: int = 0,   # 0=無効, >0 でタイムアウト強制決済（秒）
) -> Dict:
    """全行でシグナル生成 → Backtester で評価

    order_type:
      "taker"       : 成行 (ask/bid約定, スリッページ 1bps, 手数料 0%)
      "maker"       : Maker指値シンプル版 (mid_price約定, リベート -0.01%)
      "maker-limit" : Maker指値リアル版 (bid+N chase, exec_price で約定判定)
    """
    X_test = df_test[feat_cols].values
    X_test = np.nan_to_num(X_test, nan=0.0)
    X_scaled = model.scaler.transform(X_test)

    raw_pred  = model.model.predict(X_scaled)          # 0,1,2
    raw_proba = model.model.predict_proba(X_scaled)    # (n, 3)

    # シグナル: 0→SELL(-1), 1→HOLD(0), 2→BUY(1)
    signals    = pd.Series(raw_pred.astype(int) - 1, index=df_test.index)
    confidence = pd.Series(raw_proba.max(axis=1),    index=df_test.index)

    sig_counts = {
        "BUY":  int((signals ==  1).sum()),
        "HOLD": int((signals ==  0).sum()),
        "SELL": int((signals == -1).sum()),
    }

    if order_type == "maker":
        # Maker指値シンプル版: mid_price約定 + GMOリベート -0.01%
        backtester = Backtester(
            initial_capital=INITIAL_CAPITAL,
            commission_rate=-0.0001,
            slippage_bps=0.0,
            maker_order=True,
        )
        metrics = backtester.run(
            df_test, signals, confidence,
            confidence_threshold=confidence_threshold,
            fixed_quantity=FIXED_QTY_BTC,
        )

    elif order_type == "maker-limit":
        # Maker指値リアル版: bid+N chase / exec_price で約定判定 / リベート -0.01%
        backtester = Backtester(
            initial_capital=INITIAL_CAPITAL,
            commission_rate=-0.0001,
            slippage_bps=0.0,
        )
        metrics = backtester.run_maker_limit(
            df_test, signals, confidence,
            confidence_threshold=confidence_threshold,
            fixed_quantity=FIXED_QTY_BTC,
            tick_size=1.0,
            max_hold_seconds=max_hold_seconds,
        )

    else:
        # Taker成行: ask/bid約定 + スリッページ 1bps + 手数料 0%
        backtester = Backtester(
            initial_capital=INITIAL_CAPITAL,
            commission_rate=0.0,
            slippage_bps=1.0,
            maker_order=False,
        )
        metrics = backtester.run(
            df_test, signals, confidence,
            confidence_threshold=confidence_threshold,
            fixed_quantity=FIXED_QTY_BTC,
        )

    trades_df = backtester.get_trades()

    return {
        "signal_counts": sig_counts,
        "metrics":       metrics,
        "trades_df":     trades_df,
    }


# ──────────────────────────────────────────────────────────────
# モデルを ml_models に保存
# ──────────────────────────────────────────────────────────────
def save_model_to_db(
    model: MomentumModel,
    symbol: str,
    train_start: datetime,
    train_end: datetime,
    train_metrics: Dict,
    bt_metrics: Dict,
) -> int:
    buf = io.BytesIO()
    joblib.dump(
        {"model": model.model, "scaler": model.scaler,
         "feature_columns": model.feature_columns},
        buf,
    )
    conn = psycopg2.connect(DatabaseConfig.get_algo_trader_connection_string())
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ml_models
                  (model_name, model_type, symbol, model_data,
                   training_window_days, training_start_time, training_end_time,
                   metrics, trained_at, is_active)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                RETURNING id
                """,
                (
                    "momentum_ml_exec_only", "XGBoost", symbol,
                    psycopg2.Binary(buf.getvalue()), 1,
                    train_start, train_end,
                    json.dumps({**train_metrics, "backtest": bt_metrics}),
                    datetime.now(), False,
                ),
            )
            mid = cur.fetchone()[0]
            conn.commit()
            return mid
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────
# 結果表示
# ──────────────────────────────────────────────────────────────
def print_symbol_result(symbol: str, tm: Dict, bt: Dict):
    m = bt["metrics"]
    sc = bt["signal_counts"]
    trades = bt["trades_df"]

    print(f"\n{'='*65}")
    print(f"  {symbol}")
    print(f"{'='*65}")
    print(f"  【学習】")
    print(f"    約定あり行数    : {tm['exec_only_rows']:,}")
    print(f"    訓練/検証       : {tm['train_samples']:,} / {tm['val_samples']:,}")
    print(f"    ラベル分布      : SELL {tm['label_dist']['SELL']:,}  "
          f"HOLD {tm['label_dist']['HOLD']:,}  BUY {tm['label_dist']['BUY']:,}")
    print(f"    正解率          : {tm['accuracy']:.4f}  "
          f"(バランス: {tm['balanced_acc']:.4f})")
    print(f"    Recall          : SELL {tm['sell_recall']:.1%}  "
          f"HOLD {tm['hold_recall']:.1%}  BUY {tm['buy_recall']:.1%}")
    print(f"  【バックテスト】")
    print(f"    シグナル        : BUY {sc['BUY']:,}  "
          f"HOLD {sc['HOLD']:,}  SELL {sc['SELL']:,}")
    print(f"    総トレード数    : {m.get('total_trades', 0)}")
    print(f"    勝率            : {m.get('win_rate', 0):.1f}%")
    print(f"    総リターン      : {m.get('total_return', 0):.3f}%")
    print(f"    シャープレシオ  : {m.get('sharpe_ratio', 0):.3f}")
    print(f"    最大ドローダウン: {m.get('max_drawdown', 0):.3f}%")
    print(f"    最終資産        : ¥{m.get('final_equity', INITIAL_CAPITAL):,.0f}")
    pnl = m.get("final_equity", INITIAL_CAPITAL) - INITIAL_CAPITAL
    pnl_sign = "+" if pnl >= 0 else ""
    print(f"    損益            : {pnl_sign}¥{pnl:,.0f}")

    if len(trades) > 0 and "pnl" in trades.columns:
        exits = trades[trades["action"].isin(["SELL", "COVER_SHORT"])]
        if len(exits) > 0:
            total_pnl = exits["pnl"].sum()
            sign = "+" if total_pnl >= 0 else ""
            print(f"    クローズ取引損益: {sign}¥{total_pnl:,.0f}")


# ──────────────────────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="全シンボル 学習 + バックテスト")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--train-start", default=DEFAULT_TRAIN_START.strftime("%Y-%m-%d %H:%M"))
    parser.add_argument("--train-end",   default=DEFAULT_TRAIN_END.strftime("%Y-%m-%d %H:%M"))
    parser.add_argument("--test-start",  default=DEFAULT_TEST_START.strftime("%Y-%m-%d %H:%M"))
    parser.add_argument("--test-end",    default=DEFAULT_TEST_END.strftime("%Y-%m-%d %H:%M"))
    parser.add_argument("--confidence",  type=float, default=CONFIDENCE_THRESH)
    parser.add_argument(
        "--order-type",
        choices=["taker", "maker", "maker-limit"],
        default="taker",
        help="約定方式: taker=成行, maker=指値シンプル(mid), maker-limit=指値リアル(bid+N chase)",
    )
    parser.add_argument(
        "--max-hold-seconds", type=int, default=0,
        help="ポジション最大保有秒数（0=無効）。超過したら成行で強制決済（Taker fee 0.05%%）",
    )
    parser.add_argument("--no-save",     action="store_true", help="DBへのモデル保存をスキップ")
    args = parser.parse_args()

    fmt = "%Y-%m-%d %H:%M"
    train_start = datetime.strptime(args.train_start, fmt)
    train_end   = datetime.strptime(args.train_end,   fmt)
    test_start  = datetime.strptime(args.test_start,  fmt)
    test_end    = datetime.strptime(args.test_end,    fmt)
    confidence_thresh = args.confidence

    train_h = (train_end  - train_start).total_seconds() / 3600
    test_h  = (test_end   - test_start ).total_seconds() / 3600

    print("=" * 65)
    print("  全シンボル 学習 + バックテスト")
    print("=" * 65)
    print(f"  シンボル        : {', '.join(args.symbols)}")
    print(f"  学習期間        : {train_start} 〜 {train_end}  ({train_h:.1f}h)")
    print(f"  バックテスト期間: {test_start} 〜 {test_end}  ({test_h:.1f}h)")
    print(f"  確信度閾値      : {confidence_thresh}")
    order_label = {
        "taker":       "Taker成行 (ask/bid, スリッページ 1bps)",
        "maker":       "Maker指値シンプル (mid_price, リベート -0.01%)",
        "maker-limit": "Maker指値リアル (bid+N chase, exec_price 約定判定, リベート -0.01%)",
    }
    print(f"  注文方式        : {order_label[args.order_type]}")
    timeout_str = f"{args.max_hold_seconds}秒" if args.max_hold_seconds > 0 else "なし（逆シグナルのみ）"
    print(f"  タイムアウト決済: {timeout_str}")
    print(f"  初期資本        : ¥{INITIAL_CAPITAL:,}")

    fe = FeatureEngineer()
    all_results = {}

    for symbol in args.symbols:
        print(f"\n{'─'*65}")
        print(f"  Processing: {symbol}")
        print(f"{'─'*65}")

        loader = MarketDataLoader()
        try:
            # ── 学習データ ──
            print(f"  [1/4] 学習データ読み込み ({train_start.date()} 〜 {train_end.date()})...")
            df_train_raw = loader.load_training_data(
                symbol, train_start, train_end, skip_min_samples_check=True
            )
            df_train = fe.engineer_features(df_train_raw)
            n_exec = int((df_train["volume_total"] > 0).sum())
            print(f"        全行: {len(df_train):,}  約定あり: {n_exec:,} ({n_exec/len(df_train)*100:.1f}%)")

            # ── モデル学習 ──
            print(f"  [2/4] XGBoost 学習中（約定あり行のみ）...")
            model, feat_cols, train_metrics = train_symbol(
                symbol, train_start, train_end, df_train
            )
            print(f"        正解率: {train_metrics['accuracy']:.4f}  "
                  f"バランス: {train_metrics['balanced_acc']:.4f}  "
                  f"SELL/BUY Recall: "
                  f"{train_metrics['sell_recall']:.1%}/{train_metrics['buy_recall']:.1%}")

            # ── バックテストデータ ──
            print(f"  [3/4] バックテストデータ読み込み ({test_start.date()} 〜 {test_end.date()})...")
            df_test_raw = loader.load_training_data(
                symbol, test_start, test_end, skip_min_samples_check=True
            )
            df_test = fe.engineer_features(df_test_raw)
            print(f"        全行: {len(df_test):,}")

            # ── バックテスト ──
            print(f"  [4/4] バックテスト実行中...")
            bt_result = backtest_symbol(symbol, model, feat_cols, df_test, confidence_thresh, args.order_type, args.max_hold_seconds)
            m = bt_result["metrics"]
            print(f"        トレード: {m.get('total_trades',0)}件  "
                  f"勝率: {m.get('win_rate',0):.1f}%  "
                  f"リターン: {m.get('total_return',0):.3f}%  "
                  f"シャープ: {m.get('sharpe_ratio',0):.3f}")

            # ── DB保存 ──
            if not args.no_save:
                model_id = save_model_to_db(
                    model, symbol, train_start, train_end,
                    train_metrics, {k: v for k, v in m.items()
                                    if isinstance(v, (int, float))}
                )
                print(f"        モデル保存: ml_models.id = {model_id}")

            all_results[symbol] = {
                "train": train_metrics,
                "backtest": bt_result,
            }

        except Exception as e:
            import traceback
            print(f"  ❌ エラー: {e}")
            traceback.print_exc()
            all_results[symbol] = {"error": str(e)}
        finally:
            loader.close()

    # ── 最終サマリ ──
    print("\n\n" + "=" * 65)
    print("  最終サマリ")
    print("=" * 65)
    print(f"  {'シンボル':<14}  {'Acc':>6}  {'Bal':>6}  "
          f"{'S/B Recall':>12}  {'Trades':>7}  {'WinRate':>8}  "
          f"{'Return':>8}  {'Sharpe':>7}  {'損益':>14}")
    print("  " + "─" * 90)

    for symbol, res in all_results.items():
        if "error" in res:
            print(f"  {symbol:<14}  ERROR: {res['error']}")
            continue
        tm = res["train"]
        m  = res["backtest"]["metrics"]
        pnl = m.get("final_equity", INITIAL_CAPITAL) - INITIAL_CAPITAL
        sign = "+" if pnl >= 0 else ""
        sb = f"{tm['sell_recall']:.0%}/{tm['buy_recall']:.0%}"
        print(
            f"  {symbol:<14}  "
            f"{tm['accuracy']:>6.4f}  {tm['balanced_acc']:>6.4f}  "
            f"{sb:>12}  "
            f"{m.get('total_trades',0):>7}  "
            f"{m.get('win_rate',0):>7.1f}%  "
            f"{m.get('total_return',0):>7.3f}%  "
            f"{m.get('sharpe_ratio',0):>7.3f}  "
            f"{sign}¥{pnl:>12,.0f}"
        )

    # シンボル別詳細
    for symbol, res in all_results.items():
        if "error" not in res:
            print_symbol_result(symbol, res["train"], res["backtest"])


if __name__ == "__main__":
    main()
