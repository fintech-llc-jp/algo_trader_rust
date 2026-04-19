"""
Daily Training Pipeline
"""
import json
import psycopg2
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from typing import Dict, Tuple

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
    
    def train(self, symbol: str = "G_FX_BTCJPY") -> Dict:
        """
        日次訓練を実行
        """
        loader = MarketDataLoader()
        feature_engineer = FeatureEngineer()
        
        try:
            # データロード
            end_date = datetime.now()
            start_date = end_date - timedelta(days=self.config.TRAINING_WINDOW_DAYS)
            
            print(f"Loading data from {start_date} to {end_date}")
            df = loader.load_training_data(symbol, start_date, end_date)
            
            # 特徴量エンジニアリング
            print("Engineering features...")
            df = feature_engineer.engineer_features(df)
            
            # ラベル生成
            print("Generating labels...")
            X, y = self._generate_labels(df)
            
            if len(X) == 0:
                raise ValueError("No training samples generated")
            
            # 訓練/検証データ分割
            split_idx = int(len(X) * (1 - self.config.VALIDATION_SPLIT))
            X_train, X_val = X[:split_idx], X[split_idx:]
            y_train, y_val = y[:split_idx], y[split_idx:]
            
            # モデル訓練
            print("Training model...")
            model = MomentumModel()
            model.feature_columns = feature_engineer.get_feature_columns()
            model.train(X_train, y_train, X_val, y_val)
            
            # 評価
            print("Evaluating model...")
            val_pred, val_proba = model.predict(X_val)
            accuracy = np.mean(val_pred == y_val)
            
            print(f"Validation Accuracy: {accuracy:.4f}")
            
            # モデルパラメータを保存
            model_params = self._extract_model_params(model, symbol, start_date, end_date, accuracy)
            self._save_model_parameters(model_params)
            
            return {
                'status': 'success',
                'accuracy': float(accuracy),
                'training_samples': len(X_train),
                'validation_samples': len(X_val),
                'model_version': model_params['version']
            }
            
        except Exception as e:
            print(f"Training failed: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
        finally:
            loader.close()
    
    def _generate_labels(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """
        ラベルを生成（5秒後の価格変動に基づく）
        """
        horizon = self.model_config.LABEL_HORIZON
        threshold = self.model_config.LABEL_THRESHOLD
        
        # 5秒後の価格変化率
        future_return = df['mid_price'].shift(-horizon).pct_change(horizon)
        
        # ラベル生成: 1=BUY, 0=HOLD, -1=SELL
        labels = np.zeros(len(df))
        labels[future_return > threshold] = 1  # BUY
        labels[future_return < -threshold] = -1  # SELL
        
        # 特徴量とラベルの準備
        feature_cols = [col for col in df.columns 
                       if col not in ['symbol', 'mid_price']]
        X = df[feature_cols].values
        y = labels
        
        # NaNを含む行を削除
        valid_mask = ~(np.isnan(X).any(axis=1) | np.isnan(y))
        X = X[valid_mask]
        y = y[valid_mask]
        
        # ラベルを0, 1, 2に変換（XGBoost用）
        # -1 -> 0 (SELL), 0 -> 1 (HOLD), 1 -> 2 (BUY)
        y = y.astype(int) + 1
        
        # すべてのクラスが存在することを確認
        unique_classes = np.unique(y)
        if len(unique_classes) < 2:
            raise ValueError(f"Insufficient classes in labels: {unique_classes}. Need at least 2 classes.")
        
        # クラス数が3未満の場合は、XGBoostのnum_classを調整
        if len(unique_classes) == 2:
            # 2クラスの場合、0と1にマッピング
            y = np.where(y == unique_classes[0], 0, 1)
        
        return X, y
    
    def _extract_model_params(
        self,
        model: MomentumModel,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        accuracy: float
    ) -> Dict:
        """
        モデルパラメータを抽出
        """
        # 最新のバージョンを取得
        version = self._get_next_version("momentum_ml")
        
        return {
            'strategy_name': 'momentum_ml',
            'version': version,
            'model_type': 'XGBoost',
            'parameters': json.dumps(self.model_config.XGBOOST_PARAMS),
            'feature_columns': model.feature_columns,
            'scaler_params': json.dumps(model.get_scaler_params()),
            'training_period_start': start_date,
            'training_period_end': end_date,
            'training_samples': len(model.scaler.mean_),
            'validation_accuracy': accuracy,
            'is_active': False  # 手動でアクティベート
        }
    
    def _get_next_version(self, strategy_name: str) -> int:
        """
        次のバージョン番号を取得
        """
        conn = psycopg2.connect(self.db_config.get_connection_string())
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT MAX(version) FROM model_parameters WHERE strategy_name = %s",
                    (strategy_name,)
                )
                result = cur.fetchone()
                return (result[0] or 0) + 1
        finally:
            conn.close()
    
    def _save_model_parameters(self, params: Dict):
        """
        モデルパラメータをデータベースに保存
        """
        conn = psycopg2.connect(self.db_config.get_connection_string())
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO model_parameters (
                        strategy_name, version, model_type, parameters,
                        feature_columns, scaler_params,
                        training_period_start, training_period_end,
                        training_samples, validation_accuracy, is_active
                    ) VALUES (
                        %s, %s, %s, %s::jsonb,
                        %s, %s::jsonb,
                        %s, %s,
                        %s, %s, %s
                    )
                """, (
                    params['strategy_name'],
                    params['version'],
                    params['model_type'],
                    params['parameters'],
                    params['feature_columns'],
                    params['scaler_params'],
                    params['training_period_start'],
                    params['training_period_end'],
                    params['training_samples'],
                    params['validation_accuracy'],
                    params['is_active']
                ))
                conn.commit()
        finally:
            conn.close()

