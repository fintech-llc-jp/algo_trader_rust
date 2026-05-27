"""
LightGBM Price Prediction Model (Regression)
LightGBMを使用して1分後の約定価格を予測する回帰モデル
"""
import os
import joblib
import numpy as np
from sklearn.preprocessing import StandardScaler
from typing import Dict, Optional
from config.settings import ModelConfig


class LightGBMPricePredictionModel:
    """
    LightGBMを使用した価格予測用の回帰モデル
    LightGBM Regressorを使用して将来の約定価格を予測
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
            y_train: 訓練データのラベル（将来の約定価格）
            X_val: 検証データの特徴量（オプション）
            y_val: 検証データのラベル（オプション）
        """
        # LightGBMを遅延インポート（pandas 2.1.3との互換性問題を回避）
        import lightgbm as lgb
        
        # 特徴量のスケーリング
        X_train_scaled = self.scaler.fit_transform(X_train)
        
        # LightGBM回帰モデルのパラメータ
        lgb_params = {
            'objective': 'regression',
            'metric': 'rmse',
            'boosting_type': 'gbdt',
            'num_leaves': 31,
            'learning_rate': 0.1,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'verbose': -1,
            'random_state': 42
        }
        
        # LightGBMデータセットの作成
        train_data = lgb.Dataset(X_train_scaled, label=y_train)
        
        if X_val is not None and y_val is not None:
            X_val_scaled = self.scaler.transform(X_val)
            val_data = lgb.Dataset(X_val_scaled, label=y_val, reference=train_data)
            self.model = lgb.train(
                lgb_params,
                train_data,
                num_boost_round=200,
                valid_sets=[val_data],
                callbacks=[lgb.early_stopping(stopping_rounds=10), lgb.log_evaluation(0)]
            )
        else:
            self.model = lgb.train(
                lgb_params,
                train_data,
                num_boost_round=200,
                callbacks=[lgb.log_evaluation(0)]
            )
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        予測を実行
        
        Args:
            X: 予測データの特徴量
        
        Returns:
            予測された約定価格の配列
        """
        if self.model is None:
            raise ValueError("Model not trained yet")
        
        X_scaled = self.scaler.transform(X)
        predictions = self.model.predict(X_scaled)
        
        return predictions
    
    def get_feature_importance(self) -> Dict[str, float]:
        """
        特徴量重要度を取得
        
        Returns:
            特徴量名と重要度の辞書
        """
        if self.model is None:
            return {}
        
        # LightGBMを遅延インポート（pandas 2.1.3との互換性問題を回避）
        import lightgbm as lgb
        
        importances = self.model.feature_importance(importance_type='gain')
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
            'model_type': 'LightGBMRegressor'
        }, filepath)
    
    @classmethod
    def load(cls, filepath: str) -> 'LightGBMPricePredictionModel':
        """
        モデルをファイルからロード
        
        Args:
            filepath: モデルファイルのパス
        
        Returns:
            ロードされたLightGBMPricePredictionModelインスタンス
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

