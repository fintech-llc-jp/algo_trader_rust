"""
Limit Order Mean Reversion Strategy
指値注文を活用した平均回帰戦略
価格が極端に動いた後に平均価格に戻る傾向を利用し、指値注文でより有利な価格で約定
"""
import pandas as pd
import numpy as np
from typing import Dict, Tuple
from data.data_loader import MarketDataLoader
from data.exch_sim_data_loader import ExchSimDataLoader
from data.feature_engineering import FeatureEngineer
from models.momentum_model import MomentumModel
from evaluation.limit_order_backtester import LimitOrderBacktester
from config.settings import ModelConfig, BacktestConfig


class LimitOrderMeanReversionStrategy:
    """
    指値注文を活用した平均回帰戦略
    価格が極端に動いた後に平均価格に戻る傾向を利用
    """
    
    def __init__(self, lookback_period: int = 300, zscore_threshold: float = 2.0):
        """
        Args:
            lookback_period: Zスコアなどの計算に使用するルックバック期間（秒）
            zscore_threshold: Zスコアの閾値（デフォルト2.0）
        """
        self.model = MomentumModel()
        self.feature_engineer = FeatureEngineer()
        self.config = ModelConfig()
        self.backtest_config = BacktestConfig()
        self.lookback_period = lookback_period
        self.zscore_threshold = zscore_threshold
    
    def add_mean_reversion_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        平均回帰特徴量を追加
        """
        df = df.copy()
        
        # 価格のローリング平均と標準偏差
        df['price_mean'] = df['mid_price'].rolling(window=self.lookback_period).mean()
        df['price_std'] = df['mid_price'].rolling(window=self.lookback_period).std()
        
        # Zスコア
        df['price_zscore'] = (df['mid_price'] - df['price_mean']) / (df['price_std'] + 1e-9)
        df['price_zscore_abs'] = df['price_zscore'].abs()
        
        # RSI (簡易版)
        delta = df['mid_price'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # ボラティリティ
        df['volatility'] = df['mid_price'].rolling(window=self.lookback_period).std()
        
        # 価格と平均からの乖離
        df['price_deviation_from_mean'] = df['mid_price'] - df['price_mean']
        df['price_deviation_ratio'] = df['price_deviation_from_mean'] / (df['price_mean'] + 1e-9)
        
        return df.fillna(0)
    
    def generate_labels(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """
        平均回帰戦略用のラベルを生成
        
        Args:
            df: 特徴量がエンジニアリング済みのDataFrame
        
        Returns:
            (X, y)
            y: 0=HOLD, 1=BUY, -1=SELL
        """
        # 平均回帰特徴量を追加
        df = self.add_mean_reversion_features(df.copy())
        
        # 将来の価格変動を予測
        horizon = self.config.LABEL_HORIZON
        threshold = self.config.LABEL_THRESHOLD
        
        # 5秒後の価格変化率
        future_return = df['mid_price'].shift(-horizon).pct_change(horizon)
        
        # 現在のZスコア
        zscore = df.get('price_zscore', 0)
        zscore_abs = df.get('price_zscore_abs', 0)
        
        # ラベル生成: Zスコアが極端で、将来平均に戻る場合
        labels = np.zeros(len(df))
        
        # BUYシグナル: Zスコアが負（価格が低い）かつ将来価格上昇（平均回帰）
        buy_mask = (zscore < -self.zscore_threshold) & (future_return > threshold)
        labels[buy_mask] = 1
        
        # SELLシグナル: Zスコアが正（価格が高い）かつ将来価格下落（平均回帰）
        sell_mask = (zscore > self.zscore_threshold) & (future_return < -threshold)
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
        # 平均回帰特徴量を追加
        df = self.add_mean_reversion_features(df.copy())
        
        # ラベル生成
        X, y = self.generate_labels(df)
        
        if len(X) == 0:
            raise ValueError("No training samples generated")
        
        # 訓練/検証データ分割
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]
        
        # モデル訓練
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
            signals: -1=SELL, 0=HOLD, 1=BUY
            confidence: 信頼度（0.0-1.0）
        """
        # 平均回帰特徴量を追加
        df = self.add_mean_reversion_features(df.copy())
        
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
        # 0=SELL, 1=HOLD, 2=BUY -> -1=SELL, 0=HOLD, 1=BUY
        signals = predictions - 1
        confidence = probabilities.max(axis=1)
        
        return pd.Series(signals, index=df_valid.index), pd.Series(confidence, index=df_valid.index)
    
    def backtest(
        self,
        df: pd.DataFrame,
        signals: pd.Series,
        confidence: pd.Series,
        executions_df: pd.DataFrame = None
    ) -> Dict:
        """
        指値注文を使用したバックテスト
        
        Args:
            df: テストデータ
            signals: シグナル
            confidence: 信頼度
            executions_df: 約定履歴データ
        
        Returns:
            パフォーマンス指標の辞書
        """
        backtester = LimitOrderBacktester(
            limit_order_timeout_seconds=60,  # 1分
            executions_df=executions_df
        )
        
        config = BacktestConfig()
        metrics = backtester.run(
            df,
            signals,
            confidence,
            confidence_threshold=config.CONFIDENCE_THRESHOLD,
            executions_df=executions_df
        )
        
        return metrics

