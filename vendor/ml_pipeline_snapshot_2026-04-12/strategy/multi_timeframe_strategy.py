"""
Multi-Timeframe Strategy
複数のタイムフレーム（1秒、5秒、30秒など）のトレンドを組み合わせて、より精度の高いシグナルを生成する戦略
"""
import pandas as pd
import numpy as np
from typing import Dict, Tuple
from data.data_loader import MarketDataLoader
from data.feature_engineering import FeatureEngineer
from models.momentum_model import MomentumModel
from evaluation.backtester import Backtester
from config.settings import ModelConfig, BacktestConfig


class MultiTimeframeStrategy:
    """
    Multi-Timeframe戦略
    複数のタイムフレームのトレンドを組み合わせてシグナルを生成
    """
    
    def __init__(self, timeframes: list = [1, 5, 30], 
                 trend_consensus_ratio: float = 1.0,
                 label_threshold: float = None):
        """
        Args:
            timeframes: タイムフレームのリスト（秒、デフォルト[1, 5, 30]）
            trend_consensus_ratio: タイムフレームの一致率（1.0=全一致、0.5=過半数、デフォルト1.0）
            label_threshold: ラベル生成の閾値（Noneの場合はModelConfigの値を使用）
        """
        self.model = MomentumModel()
        self.feature_engineer = FeatureEngineer()
        self.config = ModelConfig()
        self.backtest_config = BacktestConfig()
        self.timeframes = timeframes
        self.trend_consensus_ratio = trend_consensus_ratio
        self.label_threshold = label_threshold or self.config.LABEL_THRESHOLD
    
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
    
    def generate_labels(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """
        Multi-Timeframe戦略用のラベルを生成
        
        Args:
            df: 特徴量がエンジニアリング済みのDataFrame
        
        Returns:
            (X, y)
            y: 0=HOLD, 1=BUY, -1=SELL
        """
        # Multi-Timeframe特徴量を追加（ラベル生成時にも追加）
        df = self.add_multi_timeframe_features(df.copy())
        
        # 将来の価格変動を予測
        horizon = self.config.LABEL_HORIZON
        threshold = self.label_threshold
        
        # 5秒後の価格変化率
        future_return = df['mid_price'].shift(-horizon).pct_change(horizon)
        
        # 各タイムフレームでのトレンド
        trends = []
        for tf in self.timeframes:
            trend = np.where(df[f'return_{tf}s'] > threshold, 1,
                           np.where(df[f'return_{tf}s'] < -threshold, -1, 0))
            trends.append(trend)
        
        # ラベル生成: 複数のタイムフレームで同じ方向のトレンドがある場合
        labels = np.zeros(len(df))
        
        # タイムフレームの一致数を計算
        num_timeframes = len(self.timeframes)
        required_consensus = int(num_timeframes * self.trend_consensus_ratio)
        
        # BUYトレンドの一致数をカウント
        buy_consensus = np.sum([t == 1 for t in trends], axis=0)
        buy_mask = (buy_consensus >= required_consensus) & (future_return > threshold)
        labels[buy_mask] = 1
        
        # SELLトレンドの一致数をカウント
        sell_consensus = np.sum([t == -1 for t in trends], axis=0)
        sell_mask = (sell_consensus >= required_consensus) & (future_return < -threshold)
        labels[sell_mask] = -1
        
        # 特徴量の準備
        feature_cols = [col for col in df.columns 
                       if col not in ['symbol', 'mid_price']]
        X = df[feature_cols].values
        y = labels
        
        # NaNを含む行を削除
        valid_mask = ~(np.isnan(X).any(axis=1) | np.isnan(y))
        X = X[valid_mask]
        y = y[valid_mask]
        
        # ラベルを0, 1, 2に変換（XGBoost用）
        y = y.astype(int) + 1
        
        # すべてのクラスが存在することを確認
        unique_classes = np.unique(y)
        if len(unique_classes) < 2:
            raise ValueError(f"Insufficient classes in labels: {unique_classes}. Need at least 2 classes.")
        
        if len(unique_classes) == 2:
            y = np.where(y == unique_classes[0], 0, 1)
        
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
                       if col not in ['symbol', 'mid_price']]
        self.model.feature_columns = feature_cols
        self.model.train(X_train, y_train, X_val, y_val)
        
        # 評価
        val_pred, val_proba = self.model.predict(X_val)
        accuracy = np.mean(val_pred == y_val)
        
        return {
            'accuracy': float(accuracy),
            'training_samples': len(X_train),
            'validation_samples': len(X_val)
        }
    
    def predict(self, df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
        """
        予測を実行
        
        Args:
            df: 予測データ（特徴量がエンジニアリング済み）
        
        Returns:
            (signals, confidence)
        """
        # Multi-Timeframe特徴量を追加
        df = self.add_multi_timeframe_features(df)
        
        # 特徴量カラムが設定されていない場合は設定
        if not self.model.feature_columns:
            feature_cols = [col for col in df.columns 
                           if col not in ['symbol', 'mid_price']]
            self.model.feature_columns = feature_cols
        
        feature_cols = self.model.feature_columns
        # 存在する特徴量のみを使用
        available_cols = [col for col in feature_cols if col in df.columns]
        if not available_cols:
            raise ValueError("No matching feature columns found in dataframe")
        
        X = df[available_cols].values
        
        # NaNを含む行を削除
        valid_mask = ~(pd.isna(X).any(axis=1))
        df_valid = df[valid_mask]
        X_valid = X[valid_mask]
        
        # 予測
        predictions, probabilities = self.model.predict(X_valid)
        
        # 予測をシグナルに変換
        signals = predictions - 1
        confidence = probabilities.max(axis=1)
        
        # Seriesに変換
        signals_series = pd.Series(signals, index=df_valid.index)
        confidence_series = pd.Series(confidence, index=df_valid.index)
        
        return signals_series, confidence_series
    
    def backtest(self, df: pd.DataFrame, signals: pd.Series, confidence: pd.Series) -> Dict:
        """
        バックテストを実行
        
        Args:
            df: バックテストデータ
            signals: シグナル
            confidence: 信頼度
        
        Returns:
            パフォーマンス指標の辞書
        """
        backtester = Backtester()
        metrics = backtester.run(
            df,
            signals,
            confidence,
            confidence_threshold=self.backtest_config.CONFIDENCE_THRESHOLD
        )
        
        return metrics

