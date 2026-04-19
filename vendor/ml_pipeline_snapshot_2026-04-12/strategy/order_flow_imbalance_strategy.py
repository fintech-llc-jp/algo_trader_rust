"""
Order Flow Imbalance Strategy
板の厚みやオーダーフローの不均衡から、短期的な価格変動の方向を予測する戦略
"""
import pandas as pd
import numpy as np
from typing import Dict, Tuple
from data.data_loader import MarketDataLoader
from data.feature_engineering import FeatureEngineer
from models.momentum_model import MomentumModel  # 同じモデル構造を使用
from evaluation.backtester import Backtester
from config.settings import ModelConfig, BacktestConfig


class OrderFlowImbalanceStrategy:
    """
    Order Flow Imbalance戦略
    板の厚みや約定データのBuy/Sell比率の不均衡を利用
    """
    
    def __init__(self):
        self.model = MomentumModel()  # 同じモデル構造を使用
        self.feature_engineer = FeatureEngineer()
        self.config = ModelConfig()
        self.backtest_config = BacktestConfig()
    
    def generate_labels(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """
        Order Flow Imbalance戦略用のラベルを生成
        
        Args:
            df: 特徴量がエンジニアリング済みのDataFrame
        
        Returns:
            (X, y)
            y: 0=HOLD, 1=BUY, -1=SELL
        """
        # Order Flow Imbalanceの特徴量を使用
        # order_imbalance, volume_imbalance, depth_ratioなど
        
        # 将来の価格変動を予測
        horizon = self.config.LABEL_HORIZON
        threshold = self.config.LABEL_THRESHOLD
        
        # 5秒後の価格変化率
        future_return = df['mid_price'].shift(-horizon).pct_change(horizon)
        
        # 現在のオーダーインバランス
        order_imbalance = df.get('order_imbalance', 0)
        volume_imbalance = df.get('volume_imbalance', 0)
        
        # ラベル生成: オーダーインバランスと将来の価格変動が一致する場合
        labels = np.zeros(len(df))
        
        # BUYシグナル: オーダーインバランスが正（買い優勢）かつ将来価格上昇
        buy_mask = (order_imbalance > threshold) & (future_return > threshold)
        labels[buy_mask] = 1
        
        # SELLシグナル: オーダーインバランスが負（売り優勢）かつ将来価格下落
        sell_mask = (order_imbalance < -threshold) & (future_return < -threshold)
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
        # -1 -> 0 (SELL), 0 -> 1 (HOLD), 1 -> 2 (BUY)
        y = y.astype(int) + 1
        
        # すべてのクラスが存在することを確認
        unique_classes = np.unique(y)
        if len(unique_classes) < 2:
            raise ValueError(f"Insufficient classes in labels: {unique_classes}. Need at least 2 classes.")
        
        # クラス数が3未満の場合は調整
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
            signals: -1=SELL, 0=HOLD, 1=BUY
            confidence: 信頼度（0.0-1.0）
        """
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
        
        # 信頼度は最大確率を使用
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

