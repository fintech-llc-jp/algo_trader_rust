"""
Order Book Only Feature Engineering
板情報のみを使用する特徴量エンジニアリング（約定データは使用しない）
"""
import pandas as pd
import numpy as np
from typing import List


class OrderBookOnlyFeatureEngineer:
    """
    板情報のみを使用する特徴量エンジニアリング
    約定データ（exec_price_all, exec_qty_all等）は使用しない
    """
    
    def __init__(self):
        self.feature_columns = []
    
    def engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        板情報のみの特徴量を生成
        
        Args:
            df: 板情報を含むDataFrame
        
        Returns:
            特徴量が追加されたDataFrame
        """
        df = df.copy()
        
        # 1. 価格ベースの特徴量（板情報から）
        df = self._add_price_features(df)
        
        # 2. 板の厚みベースの特徴量
        df = self._add_depth_features(df)
        
        # 3. オーダーインバランス特徴量
        df = self._add_imbalance_features(df)
        
        # 4. テクニカル指標（価格ベースのみ）
        df = self._add_technical_indicators(df)
        
        # 5. ラグ特徴量
        df = self._add_lag_features(df)
        
        # 6. ローリング統計量
        df = self._add_rolling_statistics(df)
        
        # NaNを0で埋める
        df = df.fillna(0)
        
        # 特徴量カラムを保存（約定データ関連のカラムを除外）
        exclude_cols = ['symbol', 'exec_price_all', 'exec_price_buy', 'exec_price_sell',
                        'exec_price_weighted_buy', 'exec_price_weighted_sell',
                        'exec_qty_all', 'volume_buy', 'volume_sell', 'volume_total', 'volume_imbalance']
        self.feature_columns = [col for col in df.columns 
                               if col not in exclude_cols]
        
        return df
    
    def _add_price_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """価格ベースの特徴量（板情報から）"""
        # スプレッド比率
        df['spread_ratio'] = df['spread'] / (df['mid_price'] + 1e-9)
        
        # 価格変化率（1秒前、5秒前、30秒前）
        df['return_1s'] = df['mid_price'].pct_change(1)
        df['return_5s'] = df['mid_price'].pct_change(5)
        df['return_30s'] = df['mid_price'].pct_change(30)
        
        return df
    
    def _add_depth_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """板の厚みベースの特徴量"""
        # 板の厚み比率（BID/ASK）
        if 'bid_depth' in df.columns and 'ask_depth' in df.columns:
            df['depth_ratio'] = df['bid_depth'] / (df['ask_depth'] + 1e-9)
            df['depth_imbalance'] = (df['bid_depth'] - df['ask_depth']) / (df['bid_depth'] + df['ask_depth'] + 1e-9)
        
        return df
    
    def _add_imbalance_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """オーダーインバランス特徴量"""
        # 板情報からインバランスを計算
        if 'bid_depth' in df.columns and 'ask_depth' in df.columns:
            df['order_imbalance'] = (df['bid_depth'] - df['ask_depth']) / (df['bid_depth'] + df['ask_depth'] + 1e-9)
        
        return df
    
    def _add_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """テクニカル指標"""
        # 移動平均
        df['sma_5'] = df['mid_price'].rolling(window=5).mean()
        df['sma_30'] = df['mid_price'].rolling(window=30).mean()
        
        # RSI（相対力指数）
        delta = df['mid_price'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df['rsi'] = 100 - (100 / (1 + rs))
        
        return df
    
    def _add_lag_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """ラグ特徴量"""
        # 1秒前、5秒前、30秒前の価格
        df['price_lag_1'] = df['mid_price'].shift(1)
        df['price_lag_5'] = df['mid_price'].shift(5)
        df['price_lag_30'] = df['mid_price'].shift(30)
        
        return df
    
    def _add_rolling_statistics(self, df: pd.DataFrame) -> pd.DataFrame:
        """ローリング統計量"""
        # ローリング標準偏差
        df['price_std_5'] = df['mid_price'].rolling(window=5).std()
        df['price_std_30'] = df['mid_price'].rolling(window=30).std()
        
        # ローリング最大値・最小値
        df['price_max_5'] = df['mid_price'].rolling(window=5).max()
        df['price_min_5'] = df['mid_price'].rolling(window=5).min()
        
        return df
    
    def get_feature_columns(self) -> List[str]:
        """特徴量カラムのリストを取得"""
        return self.feature_columns

