"""
Configurable Feature Engineering
DBから特徴量設定を読み込んで動的に特徴量を生成
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Optional
import psycopg2
import json
from config.settings import DatabaseConfig
from data.feature_engineering import FeatureEngineer


class ConfigurableFeatureEngineer(FeatureEngineer):
    """
    設定可能な特徴量エンジニア
    DBから特徴量定義を読み込んで動的に特徴量を生成
    """
    
    def __init__(self, feature_set_name: str = 'standard_features'):
        """
        Args:
            feature_set_name: 特徴量セット名（feature_configsテーブルから読み込む）
        """
        super().__init__()
        self.feature_set_name = feature_set_name
        self.feature_definitions: Dict = {}
        self.preprocessing_config: Dict = {}
        self._load_config_from_db()
    
    def _load_config_from_db(self):
        """DBから特徴量設定を読み込む"""
        try:
            # algo_traderデータベースに接続（feature_configsはalgo_trader DBにある）
            conn = psycopg2.connect(
                DatabaseConfig.get_algo_trader_connection_string()
            )
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT feature_definitions, preprocessing_config
                        FROM feature_configs
                        WHERE feature_set_name = %s
                    """, (self.feature_set_name,))
                    
                    result = cur.fetchone()
                    if result:
                        self.feature_definitions = result[0] if result[0] else {}
                        self.preprocessing_config = result[1] if result[1] else {}
                        print(f"[ConfigurableFeatureEngineer] Loaded config: {self.feature_set_name}")
                    else:
                        print(f"[ConfigurableFeatureEngineer] Config not found: {self.feature_set_name}, using defaults")
                        self._load_default_config()
            finally:
                conn.close()
        except Exception as e:
            print(f"[ConfigurableFeatureEngineer] Failed to load config from DB: {e}, using defaults")
            self._load_default_config()
    
    def _load_default_config(self):
        """デフォルト設定を読み込む"""
        self.feature_definitions = {
            "price_features": {"enabled": True, "return_periods": [1, 5, 30], "spread_ratio": True},
            "depth_features": {"enabled": True, "depth_levels": [5], "depth_ratio": True},
            "imbalance_features": {"enabled": True, "imbalance_abs": True},
            "volume_features": {"enabled": True, "volume_ma_windows": [30, 300], "volume_ratio": True},
            "execution_features": {"enabled": True},
            "technical_indicators": {"enabled": False},
            "lag_features": {"enabled": True, "lag_periods": [1, 5]},
            "rolling_statistics": {"enabled": True, "windows": [30], "statistics": ["mean", "std"]}
        }
        self.preprocessing_config = {
            "fillna_method": "zero",
            "normalization": "none",
            "outlier_handling": "clip",
            "outlier_threshold": 3.0
        }
    
    def engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        設定に基づいて特徴量を生成
        """
        df = df.copy()
        
        # 1. 価格ベースの特徴量
        if self.feature_definitions.get('price_features', {}).get('enabled', True):
            df = self._add_price_features(df)
        
        # 2. 板の厚みベースの特徴量
        if self.feature_definitions.get('depth_features', {}).get('enabled', True):
            df = self._add_depth_features(df)
        
        # 3. オーダーインバランス特徴量
        if self.feature_definitions.get('imbalance_features', {}).get('enabled', True):
            df = self._add_imbalance_features(df)
        
        # 4. 出来高ベースの特徴量
        if self.feature_definitions.get('volume_features', {}).get('enabled', True):
            df = self._add_volume_features(df)
        
        # 5. 約定データベースの特徴量
        if self.feature_definitions.get('execution_features', {}).get('enabled', True):
            df = self._add_execution_features(df)
        
        # 6. テクニカル指標
        if self.feature_definitions.get('technical_indicators', {}).get('enabled', False):
            df = self._add_technical_indicators(df)
        
        # 7. ラグ特徴量
        if self.feature_definitions.get('lag_features', {}).get('enabled', True):
            df = self._add_lag_features(df)
        
        # 8. ローリング統計量
        if self.feature_definitions.get('rolling_statistics', {}).get('enabled', True):
            df = self._add_rolling_statistics(df)
        
        # 前処理を適用
        df = self._apply_preprocessing(df)
        
        # 特徴量カラムを保存
        self.feature_columns = [col for col in df.columns 
                                if col not in ['symbol']]
        
        return df
    
    def _add_price_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """価格ベースの特徴量（設定に基づく）"""
        config = self.feature_definitions.get('price_features', {})
        
        # スプレッド比率
        if config.get('spread_ratio', True):
            df['spread_ratio'] = df['spread'] / (df['mid_price'] + 1e-9)
        
        # 価格変化率
        return_periods = config.get('return_periods', [1, 5, 30])
        for period in return_periods:
            df[f'return_{period}s'] = df['mid_price'].pct_change(period)
        
        return df
    
    def _add_depth_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """板の厚みベースの特徴量（設定に基づく）"""
        config = self.feature_definitions.get('depth_features', {})
        depth_levels = config.get('depth_levels', [5])
        
        for level in depth_levels:
            if level == 5:
                df['total_depth'] = df['bid_depth_5'] + df['ask_depth_5']
                if config.get('depth_ratio', True):
                    df['depth_ratio'] = df['bid_depth_5'] / (df['ask_depth_5'] + 1e-9)
        
        return df
    
    def _add_imbalance_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """オーダーインバランス特徴量（設定に基づく）"""
        config = self.feature_definitions.get('imbalance_features', {})
        
        if config.get('imbalance_abs', True):
            df['imbalance_abs'] = df['order_imbalance'].abs()
        
        return df
    
    def _add_volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """出来高ベースの特徴量（設定に基づく）"""
        if 'volume_total' not in df.columns:
            return df
        
        config = self.feature_definitions.get('volume_features', {})
        volume_ma_windows = config.get('volume_ma_windows', [30, 300])
        
        for window in volume_ma_windows:
            df[f'volume_ma_{window}s'] = df['volume_total'].rolling(window=window).mean()
        
        if config.get('volume_ratio', True):
            if len(volume_ma_windows) > 0:
                df['volume_ratio'] = df['volume_total'] / (df[f'volume_ma_{volume_ma_windows[0]}s'] + 1e-9)
        
        return df
    
    def _add_execution_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """約定データベースの特徴量（親クラスの実装を使用）"""
        return super()._add_execution_features(df)
    
    def _add_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """テクニカル指標（設定に基づく）"""
        config = self.feature_definitions.get('technical_indicators', {})
        indicators = config.get('indicators', [])
        
        # 移動平均
        if 'sma' in indicators or len(indicators) == 0:
            df['sma_5'] = df['mid_price'].rolling(window=5).mean()
            df['sma_30'] = df['mid_price'].rolling(window=30).mean()
        
        # ボラティリティ
        df['volatility_30s'] = df['mid_price'].rolling(window=30).std()
        
        return df
    
    def _add_lag_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """ラグ特徴量（設定に基づく）"""
        config = self.feature_definitions.get('lag_features', {})
        lag_periods = config.get('lag_periods', [1, 5])
        
        for period in lag_periods:
            df[f'mid_price_lag{period}'] = df['mid_price'].shift(period)
        
        return df
    
    def _add_rolling_statistics(self, df: pd.DataFrame) -> pd.DataFrame:
        """ローリング統計量（設定に基づく）"""
        config = self.feature_definitions.get('rolling_statistics', {})
        windows = config.get('windows', [30])
        statistics = config.get('statistics', ['mean', 'std'])
        
        for window in windows:
            for stat in statistics:
                if stat == 'mean':
                    df[f'price_rolling_mean_{window}'] = df['mid_price'].rolling(window=window).mean()
                elif stat == 'std':
                    df[f'price_rolling_std_{window}'] = df['mid_price'].rolling(window=window).std()
                elif stat == 'max':
                    df[f'price_rolling_max_{window}'] = df['mid_price'].rolling(window=window).max()
                elif stat == 'min':
                    df[f'price_rolling_min_{window}'] = df['mid_price'].rolling(window=window).min()
        
        return df
    
    def _apply_preprocessing(self, df: pd.DataFrame) -> pd.DataFrame:
        """前処理を適用"""
        config = self.preprocessing_config
        
        # NaNの処理
        fillna_method = config.get('fillna_method', 'zero')
        if fillna_method == 'zero':
            df = df.fillna(0)
        elif fillna_method == 'forward':
            df = df.fillna(method='ffill')
        elif fillna_method == 'backward':
            df = df.fillna(method='bfill')
        elif fillna_method == 'mean':
            df = df.fillna(df.mean())
        
        # 外れ値の処理
        outlier_handling = config.get('outlier_handling', 'none')
        if outlier_handling == 'clip':
            threshold = config.get('outlier_threshold', 3.0)
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            for col in numeric_cols:
                if col != 'symbol':
                    mean = df[col].mean()
                    std = df[col].std()
                    if std > 0:
                        df[col] = df[col].clip(
                            lower=mean - threshold * std,
                            upper=mean + threshold * std
                        )
        
        # 正規化（現在は実装しない、必要に応じて追加）
        # normalization = config.get('normalization', 'none')
        # if normalization == 'standard':
        #     ...
        
        return df
    
    def reload_config(self, feature_set_name: Optional[str] = None):
        """設定を再読み込み"""
        if feature_set_name:
            self.feature_set_name = feature_set_name
        self._load_config_from_db()

