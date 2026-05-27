"""
Direction Classification Model (Classification)
価格の方向性（上昇/下降/横ばい）を分類するモデル
"""
import os
import joblib
import xgboost as xgb
import numpy as np
from sklearn.preprocessing import StandardScaler
from typing import Dict, Optional
from config.settings import ModelConfig


class DirectionClassificationModel:
    """
    方向性分類用の分類モデル
    XGBoost Classifierを使用して将来の価格方向性を予測
    クラス: 1 (上昇), 0 (横ばい), -1 (下降)
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
            y_train: 訓練データのラベル（方向性: 1=上昇, 0=横ばい, -1=下降）
            X_val: 検証データの特徴量（オプション）
            y_val: 検証データのラベル（オプション）
        """
        # 特徴量のスケーリング
        X_train_scaled = self.scaler.fit_transform(X_train)
        
        # XGBoost分類モデルのパラメータ
        xgb_params = {
            'n_estimators': 200,
            'max_depth': 6,
            'learning_rate': 0.1,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'objective': 'multi:softprob',
            'num_class': 3,  # 3クラス分類（上昇、横ばい、下降）
            'random_state': 42,
            'eval_metric': 'mlogloss'
        }
        
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
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        予測を実行（クラスを予測）
        
        Args:
            X: 予測データの特徴量
        
        Returns:
            予測された方向性の配列（1=上昇, 0=横ばい, -1=下降）
        """
        if self.model is None:
            raise ValueError("Model not trained yet")
        
        X_scaled = self.scaler.transform(X)
        predictions = self.model.predict(X_scaled)
        
        return predictions
    
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        予測確率を取得
        
        Args:
            X: 予測データの特徴量
        
        Returns:
            各クラスの確率の配列
        """
        if self.model is None:
            raise ValueError("Model not trained yet")
        
        X_scaled = self.scaler.transform(X)
        probabilities = self.model.predict_proba(X_scaled)
        
        return probabilities
    
    def get_feature_importance(self) -> Dict[str, float]:
        """
        特徴量重要度を取得
        
        Returns:
            特徴量名と重要度の辞書
        """
        if self.model is None:
            return {}
        
        importances = self.model.feature_importances_
        return dict(zip(self.feature_columns, importances))
    
    def save(self, filepath: str):
        """
        モデルをファイルに保存
        
        Args:
            filepath: 保存先のファイルパス（.joblib拡張子推奨）
        """
        if self.model is None:
            raise ValueError("Model not trained yet. Cannot save untrained model.")
        
        # ディレクトリが存在しない場合は作成
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # モデル、スケーラー、特徴量カラムを保存
        joblib.dump({
            'model': self.model,
            'scaler': self.scaler,
            'feature_columns': self.feature_columns,
            'model_type': 'XGBoostClassifier'
        }, filepath)
    
    @classmethod
    def load(cls, filepath: str) -> 'DirectionClassificationModel':
        """
        モデルをファイルからロード
        
        Args:
            filepath: モデルファイルのパス
        
        Returns:
            ロードされたDirectionClassificationModelインスタンス
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Model file not found: {filepath}")
        
        data = joblib.load(filepath)
        
        # データの検証
        if not isinstance(data, dict):
            raise ValueError(f"Invalid model file format: expected dict, got {type(data)}")
        
        if 'model' not in data:
            raise ValueError(f"Model file missing 'model' key. Available keys: {list(data.keys())}")
        
        if data['model'] is None:
            raise ValueError("Model file contains None model. Model may not be properly saved.")
        
        instance = cls()
        instance.model = data['model']
        instance.scaler = data.get('scaler')
        instance.feature_columns = data.get('feature_columns', [])
        
        if instance.model is None:
            raise ValueError("Failed to load model: model is None after loading")
        
        return instance

