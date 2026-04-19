"""
Volatility Prediction Strategy
将来のボラティリティ（価格変動の大きさ）を予測する戦略
"""
import pandas as pd
import numpy as np
from typing import Dict, Tuple
from data.feature_engineering import FeatureEngineer
from models.volatility_prediction_model import VolatilityPredictionModel
from config.settings import ModelConfig, BacktestConfig


class VolatilityPredictionStrategy:
    """
    ボラティリティ予測戦略
    複数のタイムフレームの特徴量を組み合わせて将来のボラティリティを予測
    """
    
    def __init__(self, timeframes: list = [1, 5, 30], 
                 prediction_horizon: int = 60,
                 window: int = 60):
        """
        Args:
            timeframes: タイムフレームのリスト（秒、デフォルト[1, 5, 30]）
            prediction_horizon: 予測ホライズン（秒、デフォルト60秒=1分）
            window: ボラティリティ計算のウィンドウサイズ（秒、デフォルト60秒）
        """
        self.model = VolatilityPredictionModel()
        self.feature_engineer = FeatureEngineer()
        self.config = ModelConfig()
        self.backtest_config = BacktestConfig()
        self.timeframes = timeframes
        self.prediction_horizon = prediction_horizon
        self.window = window
    
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
        将来のボラティリティをラベルとして生成
        
        Returns:
            (X, y)
            y: 将来のボラティリティ（標準偏差）
        """
        df = self.add_multi_timeframe_features(df.copy())
        
        if 'exec_price_all' in df.columns:
            price_col = 'exec_price_all'
        else:
            price_col = 'mid_price'
        
        # 将来のボラティリティを計算（prediction_horizon秒後のwindow秒間の標準偏差）
        future_returns = df[price_col].pct_change().shift(-self.prediction_horizon)
        future_volatility = future_returns.rolling(window=self.window).std()
        
        # 特徴量を抽出
        feature_cols = [col for col in df.columns 
                       if col not in ['symbol', 'mid_price', 'exec_price_all', 
                                     'exec_price_buy', 'exec_price_sell',
                                     'exec_price_weighted_buy', 'exec_price_weighted_sell']]
        X = df[feature_cols].values
        y = future_volatility.values
        
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
        mae = np.mean(np.abs(val_pred - y_val))
        rmse = np.sqrt(np.mean((val_pred - y_val) ** 2))
        mape = np.mean(np.abs((val_pred - y_val) / (y_val + 1e-9))) * 100
        
        return {
            'mae': float(mae),
            'rmse': float(rmse),
            'mape': float(mape),
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

