"""
Arbitrage Strategy Model
アービトラージ戦略用のMLモデル
スプレッドの収束時間予測、エントリー/エグジットシグナル生成
"""
import xgboost as xgb
import numpy as np
from sklearn.preprocessing import StandardScaler
from typing import Dict, Tuple
from config.settings import ModelConfig


class ArbitrageModel:
    """
    アービトラージ戦略用のMLモデル
    """
    
    def __init__(self):
        self.model = None
        self.scaler = StandardScaler()
        self.feature_columns = []
        self.config = ModelConfig()
    
    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray = None,
        y_val: np.ndarray = None
    ):
        """
        モデルを訓練
        
        Args:
            X_train: 訓練データの特徴量
            y_train: 訓練データのラベル
                - 0: HOLD（エントリーしない）
                - 1: LONG_G_SHORT_B（G_FX_BTCJPYを買い、B_FX_BTCJPYを売る）
                - 2: SHORT_G_LONG_B（G_FX_BTCJPYを売り、B_FX_BTCJPYを買う）
            X_val: 検証データの特徴量（オプション）
            y_val: 検証データのラベル（オプション）
        """
        # 特徴量のスケーリング
        X_train_scaled = self.scaler.fit_transform(X_train)
        
        # クラス数を動的に決定
        num_classes = len(np.unique(y_train))
        xgb_params = self.config.XGBOOST_PARAMS.copy()
        xgb_params['num_class'] = num_classes
        
        # XGBoostモデルの訓練
        self.model = xgb.XGBClassifier(**xgb_params)
        
        if X_val is not None and y_val is not None:
            X_val_scaled = self.scaler.transform(X_val)
            self.model.fit(
                X_train_scaled, y_train,
                eval_set=[(X_val_scaled, y_val)],
                verbose=False
            )
        else:
            self.model.fit(X_train_scaled, y_train)
    
    def predict(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        予測を実行
        
        Returns:
            (predictions, probabilities)
            predictions: 0=HOLD, 1=LONG_G_SHORT_B, 2=SHORT_G_LONG_B
            probabilities: 各クラスの確率
        """
        if self.model is None:
            raise ValueError("Model not trained yet")
        
        X_scaled = self.scaler.transform(X)
        predictions = self.model.predict(X_scaled)
        probabilities = self.model.predict_proba(X_scaled)
        
        return predictions, probabilities
    
    def predict_entry_signal(
        self,
        X: np.ndarray,
        zscore_threshold: float = 2.0
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        エントリーシグナルを予測
        
        Args:
            X: 特徴量
            zscore_threshold: Zスコアの閾値（デフォルト2.0）
        
        Returns:
            (signals, confidence)
            signals: -1=SHORT_G_LONG_B, 0=HOLD, 1=LONG_G_SHORT_B
            confidence: 信頼度（0.0-1.0）
        """
        predictions, probabilities = self.predict(X)
        
        # 予測をシグナルに変換
        # 0=HOLD -> 0
        # 1=LONG_G_SHORT_B -> 1
        # 2=SHORT_G_LONG_B -> -1
        signals = np.where(predictions == 2, -1, predictions)
        
        # 信頼度は最大確率を使用
        confidence = probabilities.max(axis=1)
        
        return signals, confidence
    
    def get_feature_importance(self) -> Dict[str, float]:
        """
        特徴量重要度を取得
        """
        if self.model is None:
            return {}
        
        importances = self.model.feature_importances_
        return dict(zip(self.feature_columns, importances))
    
    def get_scaler_params(self) -> Dict:
        """
        スケーラーのパラメータを取得（保存用）
        """
        return {
            'mean': self.scaler.mean_.tolist(),
            'scale': self.scaler.scale_.tolist()
        }

