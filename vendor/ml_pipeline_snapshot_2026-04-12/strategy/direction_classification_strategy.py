"""
Direction Classification Strategy
価格の方向性（上昇/下降/横ばい）を分類する戦略
"""
import pandas as pd
import numpy as np
from typing import Dict, Tuple
from data.feature_engineering import FeatureEngineer
from models.direction_classification_model import DirectionClassificationModel
from config.settings import ModelConfig, BacktestConfig


class DirectionClassificationStrategy:
    """
    方向性分類戦略
    複数のタイムフレームの特徴量を組み合わせて将来の価格方向性を予測
    """
    
    def __init__(self, timeframes: list = [1, 5, 30], 
                 prediction_horizon: int = 60,
                 threshold: float = 0.001):
        """
        Args:
            timeframes: タイムフレームのリスト（秒、デフォルト[1, 5, 30]）
            prediction_horizon: 予測ホライズン（秒、デフォルト60秒=1分）
            threshold: 横ばいとみなす価格変化率の閾値（デフォルト0.1%）
        """
        self.model = DirectionClassificationModel()
        self.feature_engineer = FeatureEngineer()
        self.config = ModelConfig()
        self.backtest_config = BacktestConfig()
        self.timeframes = timeframes
        self.prediction_horizon = prediction_horizon
        self.threshold = threshold
    
    def add_multi_timeframe_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Multi-Timeframe特徴量を追加"""
        df = df.copy()
        
        for tf in self.timeframes:
            df[f'sma_{tf}s'] = df['mid_price'].rolling(window=tf).mean()
            df[f'return_{tf}s'] = df['mid_price'].pct_change(tf)
            df[f'volatility_{tf}s'] = df['mid_price'].rolling(window=tf).std()
        
        return df.fillna(0)
    
    def generate_labels(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """
        将来の価格方向性をラベルとして生成
        
        Returns:
            (X, y)
            y: 方向性クラス（1=上昇, 0=横ばい, -1=下降）
        """
        df = self.add_multi_timeframe_features(df.copy())
        
        if 'exec_price_all' in df.columns:
            price_col = 'exec_price_all'
        else:
            price_col = 'mid_price'
        
        current_price = df[price_col]
        future_price = current_price.shift(-self.prediction_horizon)
        
        # 価格変化率を計算
        price_change_pct = (future_price - current_price) / current_price * 100
        
        # 方向性クラスに変換（1=上昇, 0=横ばい, -1=下降）
        y = np.where(price_change_pct > self.threshold, 1,
                    np.where(price_change_pct < -self.threshold, -1, 0))
        
        # 特徴量を抽出
        feature_cols = [col for col in df.columns 
                       if col not in ['symbol', 'mid_price', 'exec_price_all', 
                                     'exec_price_buy', 'exec_price_sell',
                                     'exec_price_weighted_buy', 'exec_price_weighted_sell']]
        X = df[feature_cols].values
        
        # NaNを含む行を削除
        valid_mask = ~(np.isnan(X).any(axis=1) | np.isnan(y))
        X = X[valid_mask]
        y = y[valid_mask]
        
        self.model.feature_columns = feature_cols
        
        return X, y
    
    def train(self, df: pd.DataFrame) -> Dict:
        """モデルを訓練"""
        df = self.add_multi_timeframe_features(df.copy())
        X, y = self.generate_labels(df)
        
        if len(X) == 0:
            raise ValueError("No training samples generated")
        
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]
        
        feature_cols = [col for col in df.columns 
                       if col not in ['symbol', 'mid_price', 'exec_price_all', 
                                     'exec_price_buy', 'exec_price_sell',
                                     'exec_price_weighted_buy', 'exec_price_weighted_sell']]
        self.model.feature_columns = feature_cols
        self.model.train(X_train, y_train, X_val, y_val)
        
        # 評価
        val_pred = self.model.predict(X_val)
        accuracy = np.mean(val_pred == y_val)
        
        return {
            'accuracy': float(accuracy),
            'training_samples': len(X_train),
            'validation_samples': len(X_val)
        }
    
    def predict(self, df: pd.DataFrame) -> pd.Series:
        """予測を実行"""
        df = self.add_multi_timeframe_features(df)
        
        if not self.model.feature_columns:
            feature_cols = [col for col in df.columns 
                           if col not in ['symbol', 'mid_price', 'exec_price_all', 
                                         'exec_price_buy', 'exec_price_sell',
                                         'exec_price_weighted_buy', 'exec_price_weighted_sell']]
            self.model.feature_columns = feature_cols
        
        feature_cols = self.model.feature_columns
        available_cols = [col for col in feature_cols if col in df.columns]
        missing_cols = [col for col in feature_cols if col not in df.columns]
        
        if missing_cols:
            for col in missing_cols:
                df[col] = 0
        
        X = df[feature_cols].values
        predictions = self.model.predict(X)
        
        return pd.Series(predictions, index=df.index)

