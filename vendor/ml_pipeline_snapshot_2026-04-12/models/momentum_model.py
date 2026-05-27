"""
Momentum Strategy Model
"""
import xgboost as xgb
import numpy as np
from sklearn.preprocessing import StandardScaler
from typing import Dict, Tuple
from config.settings import ModelConfig


class MomentumModel:
    
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
        """
        if self.model is None:
            raise ValueError("Model not trained yet")
        
        X_scaled = self.scaler.transform(X)
        predictions = self.model.predict(X_scaled)
        probabilities = self.model.predict_proba(X_scaled)
        
        return predictions, probabilities
    
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

