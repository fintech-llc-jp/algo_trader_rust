"""
Spot Arbitrage Strategy
FXと現物のアービトラージ戦略
現物は買いからしか入れないという制約を考慮
"""
import pandas as pd
import numpy as np
from typing import Dict, Tuple
from data.spot_arbitrage_data_loader import SpotArbitrageDataLoader
from data.spot_arbitrage_feature_engineering import SpotArbitrageFeatureEngineer
from models.arbitrage_model import ArbitrageModel
from evaluation.arbitrage_backtester import ArbitrageBacktester
from config.settings import ModelConfig, BacktestConfig


class SpotArbitrageStrategy:
    """
    Spot Arbitrage戦略
    FXと現物のアービトラージ（現物は買いからしか入れない）
    """
    
    def __init__(self, fx_symbol: str = "G_FX_BTCJPY", spot_symbol: str = "B_FX_BTCJPY"):
        """
        Args:
            fx_symbol: FXシンボル（ロング/ショート両方可能）
            spot_symbol: 現物シンボル（買いのみ可能）
        """
        self.fx_symbol = fx_symbol
        self.spot_symbol = spot_symbol
        self.model = ArbitrageModel()
        self.feature_engineer = SpotArbitrageFeatureEngineer()
        self.config = ModelConfig()
        self.backtest_config = BacktestConfig()
    
    def generate_labels(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """
        Spot Arbitrage戦略用のラベルを生成
        
        現物は買いからしか入れないため：
        - LONG_SPOT_SHORT_FX: 現物を買い、FXを売る（現物がFXより安い場合）
        - HOLD: その他
        
        Args:
            df: 特徴量がエンジニアリング済みのDataFrame（spread, spread_zscoreを含む）
        
        Returns:
            (X, y)
            y: 0=HOLD, 1=LONG_SPOT_SHORT_FX
        """
        if 'spread_zscore' not in df.columns:
            raise ValueError("spread_zscore column not found")
        
        # スプレッド = FX価格 - 現物価格
        # スプレッドが正 = FXが高い = 現物が安い = 現物を買い、FXを売るチャンス
        # スプレッドが負 = FXが安い = 現物が高い = 現物を売れないので取引しない
        
        # 将来のZスコアを計算
        horizon = self.config.LABEL_HORIZON
        threshold = self.config.LABEL_THRESHOLD
        
        future_zscore = df['spread_zscore'].shift(-horizon)
        
        # ラベル生成
        labels = np.zeros(len(df))
        
        # LONG_SPOT_SHORT_FX: 現在Zスコア > threshold（現物が安い）かつ将来収束する
        # スプレッドが正で大きい = 現物がFXより安い = 現物を買い、FXを売る
        mask_long_spot_short_fx = (
            (df['spread_zscore'] > threshold) &  # 現物がFXより安い
            (future_zscore < df['spread_zscore'])  # 将来収束する
        )
        labels[mask_long_spot_short_fx] = 1
        
        # 特徴量の準備
        feature_cols = []
        for col in df.columns:
            if col in ['spread', 'symbol1', 'symbol2', 'spread_ratio']:
                continue
            if col.startswith(f'{self.fx_symbol}_mid_price') or col.startswith(f'{self.spot_symbol}_mid_price'):
                continue
            # 数値型のカラムのみを追加
            if df[col].dtype in [np.int64, np.int32, np.float64, np.float32]:
                feature_cols.append(col)
        
        if len(feature_cols) == 0:
            raise ValueError("No numeric feature columns found")
        
        X = df[feature_cols].values.astype(float)
        y = labels.astype(float)
        
        # 無限大を0に置換
        X = np.where(np.isfinite(X), X, 0)
        
        # NaNを含む行を削除
        valid_mask = ~(np.isnan(X).any(axis=1) | np.isnan(y) | ~np.isfinite(X).all(axis=1))
        X = X[valid_mask]
        y = y[valid_mask]
        
        # すべてのクラスが存在することを確認
        unique_classes = np.unique(y)
        if len(unique_classes) < 2:
            raise ValueError(f"Insufficient classes in labels: {unique_classes}. Need at least 2 classes.")
        
        # クラス数が2未満の場合は調整
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
        feature_cols = []
        for col in df.columns:
            if col in ['spread', 'symbol1', 'symbol2', 'spread_ratio']:
                continue
            if col.startswith(f'{self.fx_symbol}_mid_price') or col.startswith(f'{self.spot_symbol}_mid_price'):
                continue
            if df[col].dtype in [np.int64, np.int32, np.float64, np.float32]:
                feature_cols.append(col)
        
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
            signals: 0=HOLD, 1=LONG_SPOT_SHORT_FX
            confidence: 信頼度（0.0-1.0）
        """
        # 特徴量カラムが設定されていない場合は設定
        if not self.model.feature_columns:
            feature_cols = []
            for col in df.columns:
                if col in ['spread', 'symbol1', 'symbol2', 'spread_ratio']:
                    continue
                if col.startswith(f'{self.fx_symbol}_mid_price') or col.startswith(f'{self.spot_symbol}_mid_price'):
                    continue
                if df[col].dtype in [np.int64, np.int32, np.float64, np.float32]:
                    feature_cols.append(col)
            self.model.feature_columns = feature_cols
        
        feature_cols = self.model.feature_columns
        # 存在する特徴量のみを使用
        available_cols = []
        for col in feature_cols:
            if col in df.columns:
                if df[col].dtype in [np.int64, np.int32, np.float64, np.float32]:
                    available_cols.append(col)
        
        if len(available_cols) == 0:
            raise ValueError("No matching numeric feature columns found in dataframe")
        
        X = df[available_cols].values.astype(float)
        
        # 無限大を0に置換
        X = np.where(np.isfinite(X), X, 0)
        
        # NaNを含む行を削除
        valid_mask = ~(pd.isna(X).any(axis=1))
        df_valid = df[valid_mask]
        X_valid = X[valid_mask]
        
        # 予測
        predictions, probabilities = self.model.predict(X_valid)
        
        # 予測をシグナルに変換
        # 0=HOLD, 1=LONG_SPOT_SHORT_FX -> 0=HOLD, 1=LONG_SPOT_SHORT_FX
        signals = predictions
        
        # 信頼度は最大確率を使用
        confidence = probabilities.max(axis=1)
        
        # Seriesに変換
        signals_series = pd.Series(signals, index=df_valid.index)
        confidence_series = pd.Series(confidence, index=df_valid.index)
        
        return signals_series, confidence_series

