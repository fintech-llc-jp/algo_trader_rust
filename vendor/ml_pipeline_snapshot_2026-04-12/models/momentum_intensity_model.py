"""
Momentum Intensity Model (Regression)
将来の価格変化率を予測する回帰モデル
予測された変化率は-10から10の整数スコアにスケーリングされる
"""
import os
import joblib
import xgboost as xgb
import numpy as np
from sklearn.preprocessing import StandardScaler
from typing import Dict, Optional
from config.settings import ModelConfig


class MomentumIntensityModel:
    """
    モメンタム強度予測用の回帰モデル
    XGBoost Regressorを使用して将来の価格変化率（パーセンテージ）を予測
    
    価格予測モデルとの違い:
    - ラベル: 絶対価格ではなく価格変化率（パーセンテージ）
    - 出力: 変化率（例: 0.05%）
    - 後処理: 変化率を-10から10の整数にスケーリング
    """
    
    def __init__(self, base_change_pct: float = 0.01):
        """
        Args:
            base_change_pct: 0.01%の変化率を強度1にマッピング（デフォルト0.01%）
                            例: base_change_pct=0.01 → 0.01%変化 = 強度1
        """
        self.model = None
        self.scaler = StandardScaler()
        self.feature_columns = []
        self.config = ModelConfig()
        self.base_change_pct = base_change_pct
        self.scale_factor = 1.0 / base_change_pct  # 0.01% = 1の強度
    
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
            y_train: 訓練データのラベル（将来の価格変化率、パーセンテージ）
                    例: 0.05 (0.05%上昇), -0.03 (-0.03%下落)
            X_val: 検証データの特徴量（オプション）
            y_val: 検証データのラベル（オプション）
        """
        # 特徴量のスケーリング
        X_train_scaled = self.scaler.fit_transform(X_train)
        
        # XGBoost回帰モデルのパラメータ
        # 価格予測モデルと同じパラメータを使用
        xgb_params = {
            'n_estimators': 200,
            'max_depth': 6,
            'learning_rate': 0.1,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'objective': 'reg:squarederror',
            'random_state': 42,
            'eval_metric': 'rmse'
        }
        
        # XGBoostモデルの訓練
        self.model = xgb.XGBRegressor(**xgb_params)
        
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
        予測を実行（変化率を予測）
        
        Args:
            X: 予測データの特徴量
        
        Returns:
            予測された価格変化率の配列（パーセンテージ）
            例: [0.05, -0.03, 0.01] (0.05%上昇、-0.03%下落、0.01%上昇)
        """
        if self.model is None:
            raise ValueError("Model not trained yet")

        # スケーラー適用
        try:
            X_scaled = self.scaler.transform(X)
        except Exception as e:
            print(f"\n❌ ERROR in scaler.transform:")
            print(f"   {type(e).__name__}: {e}")
            print(f"   Input shape: {X.shape}")
            print(f"   Input stats: min={X.min()}, max={X.max()}, mean={X.mean()}")
            print(f"   Infinity count: {np.isinf(X).sum()}")
            print(f"   NaN count: {np.isnan(X).sum()}")
            raise
        predictions = self.model.predict(X_scaled)
        
        return predictions
    
    def predict_intensity(self, X: np.ndarray) -> np.ndarray:
        """
        予測を実行し、強度スコア（-10から10の整数）に変換
        
        Args:
            X: 予測データの特徴量
        
        Returns:
            予測されたモメンタム強度の配列（-10から10の整数）
            例: [5, -3, 1] (強度5上昇、強度3下落、強度1上昇)
        """
        # 変化率を予測
        predicted_change_pct = self.predict(X)
        
        # 強度に変換
        intensity_float = predicted_change_pct * self.scale_factor
        intensity = np.clip(np.round(intensity_float), -10, 10).astype(int)
        
        return intensity
    
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
    
    def get_scaler_params(self) -> Dict:
        """
        スケーラーのパラメータを取得（保存用）
        
        Returns:
            スケーラーのパラメータ辞書
        """
        return {
            'mean': self.scaler.mean_.tolist() if self.scaler.mean_ is not None else None,
            'scale': self.scaler.scale_.tolist() if self.scaler.scale_ is not None else None
        }
    
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
        
        # モデル、スケーラー、特徴量カラム、設定を保存
        joblib.dump({
            'model': self.model,
            'scaler': self.scaler,
            'feature_columns': self.feature_columns,
            'base_change_pct': self.base_change_pct,
            'scale_factor': self.scale_factor,
            'model_type': 'XGBoostRegressor'
        }, filepath)
    
    @classmethod
    def load(cls, filepath: str) -> 'MomentumIntensityModel':
        """
        モデルをファイルからロード
        
        Args:
            filepath: モデルファイルのパス
        
        Returns:
            ロードされたMomentumIntensityModelインスタンス
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
        
        base_change_pct = data.get('base_change_pct', 0.01)
        instance = cls(base_change_pct=base_change_pct)
        instance.model = data['model']
        instance.scaler = data.get('scaler')
        instance.feature_columns = data.get('feature_columns', [])
        instance.scale_factor = data.get('scale_factor', instance.scale_factor)
        
        # 読み込み後の検証
        if instance.model is None:
            raise ValueError("Failed to load model: model is None after loading")
        
        return instance

