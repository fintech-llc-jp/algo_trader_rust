"""
Daily Training Pipeline

使い方:
    # デフォルト（直近3日分、G_FX_BTCJPY）
    python -m training.daily_trainer

    # シンボル指定
    python -m training.daily_trainer --symbol G_BTCJPY

    # 日数指定（直近N日）
    python -m training.daily_trainer --days 7

    # 開始・終了日付を直接指定
    python -m training.daily_trainer --start-date 2026-05-20 --end-date 2026-05-23

    # すべて指定
    python -m training.daily_trainer --symbol G_FX_BTCJPY --start-date 2026-05-20 --end-date 2026-05-23
"""
import argparse
import io
import json
import joblib
import psycopg2
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple

from data.data_loader import MarketDataLoader
from data.feature_engineering import FeatureEngineer
from models.momentum_model import MomentumModel
from config.settings import TrainingConfig, DatabaseConfig, ModelConfig, BacktestConfig


class DailyTrainer:

    def __init__(self):
        self.config = TrainingConfig()
        self.db_config = DatabaseConfig()
        self.model_config = ModelConfig()
        self.backtest_config = BacktestConfig()

    def train(
        self,
        symbol: str = "G_FX_BTCJPY",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict:
        """
        訓練を実行

        Args:
            symbol: 銘柄名
            start_date: 訓練データ開始日時（Noneの場合は end_date - TRAINING_WINDOW_DAYS）
            end_date: 訓練データ終了日時（Noneの場合は現在時刻）
        """
        loader = MarketDataLoader()
        feature_engineer = FeatureEngineer()

        try:
            # 日付の決定
            if end_date is None:
                end_date = datetime.now()
            if start_date is None:
                start_date = end_date - timedelta(days=self.config.TRAINING_WINDOW_DAYS)

            print(f"Symbol       : {symbol}")
            print(f"Training from: {start_date}")
            print(f"Training to  : {end_date}")
            print(f"Window days  : {(end_date - start_date).days:.1f}")

            # データロード
            print("\nLoading data...")
            df = loader.load_training_data(symbol, start_date, end_date)

            # 特徴量エンジニアリング
            print("Engineering features...")
            df = feature_engineer.engineer_features(df)

            # ラベル生成
            print("Generating labels...")
            X, y = self._generate_labels(df)

            if len(X) == 0:
                raise ValueError("No training samples generated")

            print(f"Total samples: {len(X)}")

            # 訓練/検証データ分割
            split_idx = int(len(X) * (1 - self.config.VALIDATION_SPLIT))
            X_train, X_val = X[:split_idx], X[split_idx:]
            y_train, y_val = y[:split_idx], y[split_idx:]

            print(f"Train: {len(X_train)}  Val: {len(X_val)}")

            # モデル訓練
            print("\nTraining model...")
            model = MomentumModel()
            model.feature_columns = feature_engineer.get_feature_columns()
            model.train(X_train, y_train, X_val, y_val)

            # 評価
            print("Evaluating model...")
            val_pred, val_proba = model.predict(X_val)
            accuracy = float(np.mean(val_pred == y_val))
            print(f"Validation Accuracy: {accuracy:.4f}")

            # モデルを ml_models テーブルに保存
            print("\nSaving model to ml_models...")
            model_id = self._save_model(
                model=model,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                accuracy=accuracy,
                training_samples=len(X_train),
                validation_samples=len(X_val),
            )
            print(f"Saved: ml_models.id = {model_id}")

            return {
                "status": "success",
                "model_id": model_id,
                "accuracy": accuracy,
                "training_samples": len(X_train),
                "validation_samples": len(X_val),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            }

        except Exception as e:
            import traceback
            print(f"\nTraining failed: {e}")
            traceback.print_exc()
            return {"status": "error", "error": str(e)}
        finally:
            loader.close()

    # ------------------------------------------------------------------
    # ラベル生成
    # ------------------------------------------------------------------

    def _generate_labels(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """
        ラベルを生成（LABEL_HORIZON 秒後の価格変動に基づく）
        """
        horizon = self.model_config.LABEL_HORIZON
        threshold = self.model_config.LABEL_THRESHOLD

        # N秒後の価格変化率
        future_return = df["mid_price"].shift(-horizon).pct_change(horizon)

        # ラベル: 1=BUY, 0=HOLD, -1=SELL
        labels = np.zeros(len(df))
        labels[future_return > threshold] = 1
        labels[future_return < -threshold] = -1

        feature_cols = [col for col in df.columns if col not in ["symbol", "mid_price"]]
        X = df[feature_cols].values
        y = labels

        # NaN除去
        valid_mask = ~(np.isnan(X).any(axis=1) | np.isnan(y))
        X = X[valid_mask]
        y = y[valid_mask]

        # -1→0, 0→1, 1→2 (XGBoost 多クラス用)
        y = y.astype(int) + 1

        unique_classes = np.unique(y)
        if len(unique_classes) < 2:
            raise ValueError(
                f"Insufficient label classes: {unique_classes}. Need at least 2."
            )

        if len(unique_classes) == 2:
            y = np.where(y == unique_classes[0], 0, 1)

        return X, y

    # ------------------------------------------------------------------
    # モデル保存（ml_models テーブル）
    # ------------------------------------------------------------------

    def _save_model(
        self,
        model: MomentumModel,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        accuracy: float,
        training_samples: int,
        validation_samples: int,
    ) -> int:
        """
        学習済みモデルを algo_trader.ml_models テーブルに保存する。

        Returns:
            保存されたレコードの id
        """
        # モデルをバイト列にシリアライズ（joblib）
        buffer = io.BytesIO()
        joblib.dump(
            {
                "model": model.model,
                "scaler": model.scaler,
                "feature_columns": model.feature_columns,
            },
            buffer,
        )
        model_bytes = buffer.getvalue()

        metrics = {
            "validation_accuracy": accuracy,
            "training_samples": training_samples,
            "validation_samples": validation_samples,
        }

        window_days = max(1, (end_date - start_date).days)

        conn = psycopg2.connect(DatabaseConfig.get_algo_trader_connection_string())
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ml_models (
                        model_name, model_type, symbol, model_data,
                        training_window_days, training_start_time, training_end_time,
                        metrics, trained_at, is_active
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    RETURNING id
                    """,
                    (
                        "momentum_ml",
                        "XGBoost",
                        symbol,
                        psycopg2.Binary(model_bytes),
                        window_days,
                        start_date,
                        end_date,
                        json.dumps(metrics),
                        datetime.now(),
                        False,  # 手動でアクティベート
                    ),
                )
                model_id = cur.fetchone()[0]
                conn.commit()
                return model_id
        finally:
            conn.close()


# ----------------------------------------------------------------------
# CLI エントリポイント
# ----------------------------------------------------------------------


def _parse_date(s: str) -> datetime:
    """'YYYY-MM-DD' または 'YYYY-MM-DD HH:MM:SS' を datetime に変換"""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"日付形式が不正です: '{s}'  (例: 2026-05-20 または 2026-05-20 09:00:00)"
    )


def main():
    parser = argparse.ArgumentParser(
        description="DailyTrainer: MomentumML モデルの学習",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # デフォルト（直近3日・G_FX_BTCJPY）
  python -m training.daily_trainer

  # シンボル指定
  python -m training.daily_trainer --symbol G_BTCJPY

  # 日数指定（直近N日）
  python -m training.daily_trainer --days 7

  # 開始・終了日を直接指定
  python -m training.daily_trainer --start-date 2026-05-20 --end-date 2026-05-23

  # 組み合わせ
  python -m training.daily_trainer --symbol G_FX_BTCJPY --start-date 2026-05-20 --end-date 2026-05-23
        """,
    )
    parser.add_argument(
        "--symbol",
        default="G_FX_BTCJPY",
        help="学習対象シンボル (デフォルト: G_FX_BTCJPY)",
    )
    parser.add_argument(
        "--start-date",
        type=_parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="学習データ開始日 (例: 2026-05-20)",
    )
    parser.add_argument(
        "--end-date",
        type=_parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="学習データ終了日 (例: 2026-05-23)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        metavar="N",
        help="直近N日分を学習 (--start-date/--end-date が未指定の場合に使用)",
    )

    args = parser.parse_args()

    # 日付の決定ロジック
    end_date = args.end_date  # None なら train() 内で datetime.now() を使用
    start_date = args.start_date

    if start_date is None and args.days is not None:
        base = end_date if end_date is not None else datetime.now()
        start_date = base - timedelta(days=args.days)

    trainer = DailyTrainer()
    result = trainer.train(
        symbol=args.symbol,
        start_date=start_date,
        end_date=end_date,
    )

    print("\n" + "=" * 50)
    print("結果:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    print("=" * 50)

    if result.get("status") != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
