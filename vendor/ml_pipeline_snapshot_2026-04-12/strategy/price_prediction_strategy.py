"""
Price Prediction Strategy
1分後の約定価格を予測する戦略
Multi-Timeframe特徴量を使用して価格予測を行う
"""
import pandas as pd
import numpy as np
from typing import Dict, Tuple
from data.data_loader import MarketDataLoader
from data.feature_engineering import FeatureEngineer
from models.price_prediction_model import PricePredictionModel
from config.settings import ModelConfig, BacktestConfig


class PricePredictionStrategy:
    """
    価格予測戦略
    複数のタイムフレームの特徴量を組み合わせて1分後の約定価格を予測
    """
    
    def __init__(self, timeframes: list = [1, 5, 30], 
                 prediction_horizon: int = 60):
        """
        Args:
            timeframes: タイムフレームのリスト（秒、デフォルト[1, 5, 30]）
            prediction_horizon: 予測ホライズン（秒、デフォルト60秒=1分）
        """
        self.model = PricePredictionModel()
        self.feature_engineer = FeatureEngineer()
        self.config = ModelConfig()
        self.backtest_config = BacktestConfig()
        self.timeframes = timeframes
        self.prediction_horizon = prediction_horizon
    
    def add_multi_timeframe_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Multi-Timeframe特徴量を追加
        
        Args:
            df: 特徴量がエンジニアリング済みのDataFrame
        
        Returns:
            特徴量が追加されたDataFrame
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
                # 相関計算（標準偏差が0の場合はinfinityが発生する可能性があるため、NaNを0で埋める）
                correlation = df[f'return_{tf1}s'].rolling(window=30).corr(df[f'return_{tf2}s'])
                # infinity/NaNを0で埋める（標準偏差が0の場合の対処）
                df[f'return_correlation_{tf1}s_{tf2}s'] = correlation.replace([np.inf, -np.inf], np.nan).fillna(0)
        
        # 短期トレンドと長期トレンドの一致度
        if len(self.timeframes) >= 2:
            short_tf = self.timeframes[0]
            long_tf = self.timeframes[-1]
            
            short_trend = np.where(df[f'return_{short_tf}s'] > 0, 1, -1)
            long_trend = np.where(df[f'return_{long_tf}s'] > 0, 1, -1)
            df['trend_alignment'] = (short_trend == long_trend).astype(int)
        
        return df.fillna(0)
    
    def generate_labels(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """
        1分後の約定価格をラベルとして生成
        
        Args:
            df: 特徴量がエンジニアリング済みのDataFrame
        
        Returns:
            (X, y)
            y: 将来の約定価格（prediction_horizon秒後）
        """
        # Multi-Timeframe特徴量を追加
        df = self.add_multi_timeframe_features(df.copy())
        
        # 将来の約定価格を取得
        # exec_price_all（全約定の平均価格）を使用、なければmid_priceを使用
        if 'exec_price_all' in df.columns:
            future_price_col = 'exec_price_all'
        else:
            future_price_col = 'mid_price'
        
        # prediction_horizon秒後の価格
        future_price = df[future_price_col].shift(-self.prediction_horizon)
        
        # 特徴量の準備
        feature_cols = [col for col in df.columns 
                       if col not in ['symbol', 'mid_price', 'exec_price_all', 
                                     'exec_price_buy', 'exec_price_sell',
                                     'exec_price_weighted_buy', 'exec_price_weighted_sell']]
        X = df[feature_cols].values
        y = future_price.values
        
        # NaNを含む行を削除
        valid_mask = ~(np.isnan(X).any(axis=1) | np.isnan(y))
        X = X[valid_mask]
        y = y[valid_mask]
        
        # 特徴量カラムを保存（すべての特徴量カラムを保存）
        self.model.feature_columns = feature_cols
        
        return X, y
    
    def train(self, df: pd.DataFrame) -> Dict:
        """
        モデルを訓練
        
        Args:
            df: 訓練データ（特徴量がエンジニアリング済み）
        
        Returns:
            訓練結果の辞書
        """
        # Multi-Timeframe特徴量を追加
        df = self.add_multi_timeframe_features(df.copy())
        
        # ラベル生成
        X, y = self.generate_labels(df)
        
        if len(X) == 0:
            raise ValueError("No training samples generated")
        
        # 訓練/検証データ分割
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]
        
        # モデル訓練
        # 特徴量カラムを設定（訓練データから取得）
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
        """
        予測を実行
        
        Args:
            df: 予測データ（特徴量がエンジニアリング済み）
        
        Returns:
            予測された約定価格のSeries
        """
        # Multi-Timeframe特徴量を追加
        df = self.add_multi_timeframe_features(df)
        
        # 特徴量カラムが設定されていない場合は設定
        if not self.model.feature_columns:
            feature_cols = [col for col in df.columns 
                           if col not in ['symbol', 'mid_price', 'exec_price_all', 
                                         'exec_price_buy', 'exec_price_sell',
                                         'exec_price_weighted_buy', 'exec_price_weighted_sell']]
            self.model.feature_columns = feature_cols
        
        feature_cols = self.model.feature_columns
        if not feature_cols:
            raise ValueError("Model feature_columns is empty. Model may not be trained or loaded.")
        
        # モデルが期待する特徴量を確認し、不足している特徴量を補完
        # 存在する特徴量を抽出
        available_cols = [col for col in feature_cols if col in df.columns]
        missing_cols = [col for col in feature_cols if col not in df.columns]
        
        if not available_cols:
            raise ValueError(f"No matching feature columns found in dataframe. "
                           f"Expected features: {feature_cols[:10]}... (total: {len(feature_cols)})")
        
        # 不足している特徴量がある場合は0で補完
        if missing_cols:
            for col in missing_cols:
                df[col] = 0.0
        
        # モデルが期待する順序で特徴量を抽出
        X = df[feature_cols].values
        
        # NaNを含む行を削除
        valid_mask = ~(pd.isna(X).any(axis=1))
        df_valid = df[valid_mask]
        X_valid = X[valid_mask]
        
        if len(X_valid) == 0:
            raise ValueError("No valid samples after removing NaN values")
        
        # 1. 各特徴量でinfinity/NaN/極端な値をチェックしクリーニング
        feature_df = pd.DataFrame(X_valid, columns=feature_cols)
        infinity_cols = [c for c in feature_df.columns if np.isinf(feature_df[c]).any()]
        nan_cols = [c for c in feature_df.columns if feature_df[c].isna().any()]
        large_value_cols = [c for c in feature_df.columns if feature_df[c].abs().max() > 1e10]

        if infinity_cols or nan_cols:
            X_valid = np.where(np.isinf(X_valid), np.nan, X_valid)
            X_valid = pd.DataFrame(X_valid, columns=feature_cols).fillna(0).values
        if large_value_cols:
            X_valid = np.clip(X_valid, -1e10, 1e10)

        # 予測
        try:
            predictions = self.model.predict(X_valid)
        except ValueError as e:
            # 特徴量数の不一致エラーを詳細に報告
            expected_features = len(feature_cols)
            actual_features = X_valid.shape[1] if len(X_valid.shape) > 1 else 0
            raise ValueError(
                f"Feature dimension mismatch: Model expects {expected_features} features, "
                f"but got {actual_features}. "
                f"Model feature_columns: {len(feature_cols)}, "
                f"Available in DataFrame: {len(available_cols)}, "
                f"Missing: {len(missing_cols)}. "
                f"Original error: {str(e)}"
            ) from e
        
        # Seriesに変換
        predictions_series = pd.Series(predictions, index=df_valid.index)
        
        return predictions_series

