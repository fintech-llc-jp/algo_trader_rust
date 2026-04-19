"""
Backtest Runner
モデルを使ってバックテストを実行するスクリプト
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict

from data.data_loader import MarketDataLoader
from data.feature_engineering import FeatureEngineer
from models.momentum_model import MomentumModel
from evaluation.backtester import Backtester
from config.settings import DatabaseConfig, ModelConfig, BacktestConfig


class BacktestRunner:
    """
    バックテスト実行クラス
    訓練済みモデルを使って過去データでバックテストを実行
    """
    
    def __init__(self):
        self.db_config = DatabaseConfig()
        self.model_config = ModelConfig()
        self.backtest_config = BacktestConfig()
    
    def run_backtest(
        self,
        symbol: str = "G_FX_BTCJPY",
        start_date: datetime = None,
        end_date: datetime = None,
        model_version: int = None
    ) -> Dict:
        """
        バックテストを実行
        
        Args:
            symbol: 銘柄名
            start_date: 開始日時（Noneの場合は過去1日）
            end_date: 終了日時（Noneの場合は現在）
            model_version: モデルバージョン（Noneの場合は最新のアクティブモデル）
        
        Returns:
            バックテスト結果の辞書
        """
        loader = MarketDataLoader()
        feature_engineer = FeatureEngineer()
        backtester = Backtester()
        
        try:
            # 日付の設定
            if end_date is None:
                end_date = datetime.now()
            if start_date is None:
                start_date = end_date - timedelta(days=1)
            
            print(f"Loading data from {start_date} to {end_date}")
            df = loader.load_training_data(symbol, start_date, end_date)
            
            if len(df) == 0:
                raise ValueError("No data available for the specified period")
            
            print(f"Loaded {len(df)} records")
            
            # 特徴量エンジニアリング
            print("Engineering features...")
            df = feature_engineer.engineer_features(df)
            
            # モデルの読み込み
            print("Loading model...")
            model = self._load_model(symbol, model_version)
            
            if model is None:
                raise ValueError("No model found. Please train a model first.")
            
            # 特徴量の準備
            feature_cols = model.feature_columns
            X = df[feature_cols].values
            
            # NaNを含む行を削除
            valid_mask = ~np.isnan(X).any(axis=1)
            df = df[valid_mask]
            X = X[valid_mask]
            
            if len(X) == 0:
                raise ValueError("No valid data after feature engineering")
            
            # 予測
            print("Generating predictions...")
            predictions, probabilities = model.predict(X)
            
            # シグナルと信頼度の準備
            # predictions: 0=SELL, 1=HOLD, 2=BUY -> -1=SELL, 0=HOLD, 1=BUYに変換
            signals = pd.Series(predictions - 1, index=df.index)
            
            # 信頼度は最大確率を使用
            confidence = pd.Series(probabilities.max(axis=1), index=df.index)
            
            # バックテスト実行
            print("Running backtest...")
            metrics = backtester.run(
                df,
                signals,
                confidence,
                confidence_threshold=self.backtest_config.CONFIDENCE_THRESHOLD
            )
            
            print("\n=== Backtest Results ===")
            print(f"Total Return: {metrics['total_return']:.2f}%")
            print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
            print(f"Max Drawdown: {metrics['max_drawdown']:.2f}%")
            print(f"Total Trades: {metrics['total_trades']}")
            print(f"Win Rate: {metrics['win_rate']:.2f}%")
            print(f"Final Equity: {metrics['final_equity']:,.0f}")
            
            return {
                'status': 'success',
                'symbol': symbol,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'metrics': metrics,
                'equity_curve': backtester.get_equity_curve().to_dict('records'),
                'trades': backtester.get_trades().to_dict('records')
            }
            
        except Exception as e:
            print(f"Backtest failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                'status': 'error',
                'error': str(e)
            }
        finally:
            loader.close()
    
    def _load_model(self, symbol: str, version: int = None) -> MomentumModel:
        """
        モデルを読み込む
        
        Args:
            symbol: 銘柄名
            version: モデルバージョン（Noneの場合は最新のアクティブモデル）
        
        Returns:
            MomentumModelインスタンス
        """
        import psycopg2
        import json
        
        conn = psycopg2.connect(self.db_config.get_connection_string())
        try:
            with conn.cursor() as cur:
                if version is None:
                    # 最新のアクティブモデルを取得
                    cur.execute("""
                        SELECT version, model_type, parameters, feature_columns, scaler_params
                        FROM model_parameters
                        WHERE strategy_name = 'momentum_ml'
                        AND is_active = true
                        ORDER BY version DESC
                        LIMIT 1
                    """)
                else:
                    # 指定バージョンのモデルを取得
                    cur.execute("""
                        SELECT version, model_type, parameters, feature_columns, scaler_params
                        FROM model_parameters
                        WHERE strategy_name = 'momentum_ml'
                        AND version = %s
                    """, (version,))
                
                result = cur.fetchone()
                
                if result is None:
                    return None
                
                version_num, model_type, params_json, feature_cols_json, scaler_params_json = result
                
                # モデルの構築
                model = MomentumModel()
                model.feature_columns = json.loads(feature_cols_json) if feature_cols_json else []
                model.scaler.mean_ = np.array(json.loads(scaler_params_json)['mean'])
                model.scaler.scale_ = np.array(json.loads(scaler_params_json)['scale'])
                
                # モデルパラメータの設定（実際のモデルファイルは保存されていないため、
                # ここでは簡易的にモデルを再構築する必要があります）
                # 実際の実装では、モデルファイルを保存・読み込みする必要があります
                print(f"Warning: Model file not found. Using model parameters from database.")
                print(f"Model version: {version_num}")
                
                # 注意: 実際のモデルオブジェクトは保存されていないため、
                # バックテストには訓練済みモデルが必要です
                # ここでは、モデルが存在することを前提とします
                return None  # 実際の実装では、モデルファイルを読み込む必要があります
                
        finally:
            conn.close()


if __name__ == "__main__":
    runner = BacktestRunner()
    result = runner.run_backtest()
    print("\nBacktest completed!")

