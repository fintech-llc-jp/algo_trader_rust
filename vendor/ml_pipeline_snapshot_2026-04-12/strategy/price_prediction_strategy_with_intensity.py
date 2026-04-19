"""
Price Prediction Strategy with Intensity Prediction
価格予測と強度予測を同時に行う戦略
"""
import pandas as pd
import numpy as np
from typing import Dict, Tuple
from data.data_loader import MarketDataLoader
from data.feature_engineering import FeatureEngineer
from models.price_prediction_model import PricePredictionModel
from config.settings import ModelConfig, BacktestConfig


class PricePredictionStrategyWithIntensity:
    """
    価格予測と強度予測を同時に行う戦略
    1分後の約定価格と価格変化の強度（-10から10）を予測
    """
    
    def __init__(self, timeframes: list = [1, 5, 30], 
                 prediction_horizon: int = 60,
                 intensity_max_change_pct: float = 0.5):
        """
        Args:
            timeframes: タイムフレームのリスト（秒、デフォルト[1, 5, 30]）
            prediction_horizon: 予測ホライズン（秒、デフォルト60秒=1分）
            intensity_max_change_pct: 強度10に対応する最大変化率（デフォルト0.5%）
        """
        self.price_model = PricePredictionModel()
        self.intensity_model = PricePredictionModel()  # 強度予測用の別モデル
        self.feature_engineer = FeatureEngineer()
        self.config = ModelConfig()
        self.backtest_config = BacktestConfig()
        self.timeframes = timeframes
        self.prediction_horizon = prediction_horizon
        self.intensity_max_change_pct = intensity_max_change_pct
        self.intensity_scale_factor = 10.0 / intensity_max_change_pct
    
    def add_multi_timeframe_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Multi-Timeframe特徴量を追加
        """
        df = df.copy()
        
        # 各タイムフレームでの移動平均
        for tf in self.timeframes:
            df[f'sma_{tf}s'] = df['mid_price'].rolling(window=tf).mean()
            df[f'return_{tf}s'] = df['mid_price'].pct_change(tf)
            df[f'volatility_{tf}s'] = df['mid_price'].rolling(window=tf).std()
        
        # タイムフレーム間の相関
        if len(self.timeframes) >= 2:
            for i in range(len(self.timeframes) - 1):
                tf1 = self.timeframes[i]
                tf2 = self.timeframes[i + 1]
                df[f'return_correlation_{tf1}s_{tf2}s'] = (
                    df[f'return_{tf1}s'].rolling(window=30).corr(df[f'return_{tf2}s'])
                )
        
        # 短期トレンドと長期トレンドの一致度
        if len(self.timeframes) >= 2:
            short_tf = self.timeframes[0]
            long_tf = self.timeframes[-1]
            
            short_trend = np.where(df[f'return_{short_tf}s'] > 0, 1, -1)
            long_trend = np.where(df[f'return_{long_tf}s'] > 0, 1, -1)
            df['trend_alignment'] = (short_trend == long_trend).astype(int)
        
        return df.fillna(0)
    
    def generate_labels(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        価格ラベルと強度ラベルを生成
        
        Returns:
            (X, y_price, y_intensity)
            y_price: 将来の約定価格
            y_intensity: 価格変化の強度（-10から10）
        """
        # Multi-Timeframe特徴量を追加
        df = self.add_multi_timeframe_features(df.copy())
        
        # 将来の約定価格を取得
        if 'exec_price_all' in df.columns:
            future_price_col = 'exec_price_all'
        else:
            future_price_col = 'mid_price'
        
        current_price = df[future_price_col]
        future_price = df[future_price_col].shift(-self.prediction_horizon)
        
        # 価格変化率を計算（パーセンテージ）
        change_pct = ((future_price - current_price) / (current_price + 1e-9)) * 100
        
        # 強度ラベルを生成（-10から10の範囲にクリップ）
        intensity = np.clip(change_pct * self.intensity_scale_factor, -10, 10)
        
        # 特徴量の準備
        feature_cols = [col for col in df.columns 
                       if col not in ['symbol', 'mid_price', 'exec_price_all', 
                                     'exec_price_buy', 'exec_price_sell',
                                     'exec_price_weighted_buy', 'exec_price_weighted_sell']]
        X = df[feature_cols].values
        y_price = future_price.values
        y_intensity = intensity.values
        
        # NaNを含む行を削除
        valid_mask = ~(np.isnan(X).any(axis=1) | np.isnan(y_price) | np.isnan(y_intensity))
        X = X[valid_mask]
        y_price = y_price[valid_mask]
        y_intensity = y_intensity[valid_mask]
        
        # 特徴量カラムを保存
        self.price_model.feature_columns = feature_cols
        self.intensity_model.feature_columns = feature_cols
        
        return X, y_price, y_intensity
    
    def train(self, df: pd.DataFrame) -> Dict:
        """
        価格予測モデルと強度予測モデルを訓練
        """
        # Multi-Timeframe特徴量を追加
        df = self.add_multi_timeframe_features(df.copy())
        
        # ラベル生成
        X, y_price, y_intensity = self.generate_labels(df)
        
        if len(X) == 0:
            raise ValueError("No training samples generated")
        
        # 訓練/検証データ分割
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_price_train, y_price_val = y_price[:split_idx], y_price[split_idx:]
        y_intensity_train, y_intensity_val = y_intensity[:split_idx], y_intensity[split_idx:]
        
        # 特徴量カラムを設定
        feature_cols = [col for col in df.columns 
                       if col not in ['symbol', 'mid_price', 'exec_price_all', 
                                     'exec_price_buy', 'exec_price_sell',
                                     'exec_price_weighted_buy', 'exec_price_weighted_sell']]
        self.price_model.feature_columns = feature_cols
        self.intensity_model.feature_columns = feature_cols
        
        # 価格予測モデルの訓練
        self.price_model.train(X_train, y_price_train, X_val, y_price_val)
        
        # 強度予測モデルの訓練
        self.intensity_model.train(X_train, y_intensity_train, X_val, y_intensity_val)
        
        # 評価
        val_price_pred = self.price_model.predict(X_val)
        val_intensity_pred = self.intensity_model.predict(X_val)
        
        price_mae = np.mean(np.abs(val_price_pred - y_price_val))
        price_rmse = np.sqrt(np.mean((val_price_pred - y_price_val) ** 2))
        price_mape = np.mean(np.abs((val_price_pred - y_price_val) / (y_price_val + 1e-9))) * 100
        
        intensity_mae = np.mean(np.abs(val_intensity_pred - y_intensity_val))
        intensity_rmse = np.sqrt(np.mean((val_intensity_pred - y_intensity_val) ** 2))
        
        return {
            'price_mae': float(price_mae),
            'price_rmse': float(price_rmse),
            'price_mape': float(price_mape),
            'intensity_mae': float(intensity_mae),
            'intensity_rmse': float(intensity_rmse),
            'training_samples': len(X_train),
            'validation_samples': len(X_val)
        }
    
    def predict(self, df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
        """
        価格と強度を予測
        
        Returns:
            (predictions_price, predictions_intensity)
        """
        # Multi-Timeframe特徴量を追加
        df = self.add_multi_timeframe_features(df)
        
        # 特徴量カラムが設定されていない場合は設定
        if not self.price_model.feature_columns:
            feature_cols = [col for col in df.columns 
                           if col not in ['symbol', 'mid_price', 'exec_price_all', 
                                         'exec_price_buy', 'exec_price_sell',
                                         'exec_price_weighted_buy', 'exec_price_weighted_sell']]
            self.price_model.feature_columns = feature_cols
            self.intensity_model.feature_columns = feature_cols
        
        feature_cols = self.price_model.feature_columns
        available_cols = [col for col in feature_cols if col in df.columns]
        if not available_cols:
            raise ValueError("No matching feature columns found in dataframe")
        
        X = df[available_cols].values
        
        # NaNを含む行を削除
        valid_mask = ~(pd.isna(X).any(axis=1))
        df_valid = df[valid_mask]
        X_valid = X[valid_mask]
        
        # 予測
        predictions_price = self.price_model.predict(X_valid)
        predictions_intensity = self.intensity_model.predict(X_valid)
        
        # 強度を-10から10の範囲にクリップして整数に変換
        predictions_intensity = np.clip(predictions_intensity, -10, 10)
        predictions_intensity = np.round(predictions_intensity).astype(int)
        
        # Seriesに変換
        predictions_price_series = pd.Series(predictions_price, index=df_valid.index)
        predictions_intensity_series = pd.Series(predictions_intensity, index=df_valid.index)
        
        return predictions_price_series, predictions_intensity_series

