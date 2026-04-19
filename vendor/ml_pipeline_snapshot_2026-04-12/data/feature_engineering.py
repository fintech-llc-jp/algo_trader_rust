"""
Feature Engineering
"""
import pandas as pd
import numpy as np
from typing import List


class FeatureEngineer:
    
    def __init__(self):
        self.feature_columns = []
    
    def engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        機械学習用の特徴量を生成
        """
        df = df.copy()
        
        # 1. 価格ベースの特徴量
        df = self._add_price_features(df)
        
        # 2. 板の厚みベースの特徴量
        df = self._add_depth_features(df)
        
        # 3. オーダーインバランス特徴量
        df = self._add_imbalance_features(df)
        
        # 4. 出来高ベースの特徴量
        df = self._add_volume_features(df)
        
        # 5. 約定データベースの特徴量
        df = self._add_execution_features(df)
        
        # 6. テクニカル指標
        df = self._add_technical_indicators(df)
        
        # 7. ラグ特徴量
        df = self._add_lag_features(df)
        
        # 8. ローリング統計量
        df = self._add_rolling_statistics(df)
        
        # NaNを0で埋める
        df = df.fillna(0)
        
        # 特徴量カラムを保存
        self.feature_columns = [col for col in df.columns 
                                if col not in ['symbol']]
        
        return df
    
    def _add_price_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """価格ベースの特徴量"""
        # スプレッド比率
        df['spread_ratio'] = df['spread'] / (df['mid_price'] + 1e-9)
        
        # 価格変化率（1秒前、5秒前、30秒前）
        df['return_1s'] = df['mid_price'].pct_change(1)
        df['return_5s'] = df['mid_price'].pct_change(5)
        df['return_30s'] = df['mid_price'].pct_change(30)
        
        return df
    
    def _add_depth_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """板の厚みベースの特徴量"""
        # 総深度
        df['total_depth'] = df['bid_depth_5'] + df['ask_depth_5']
        
        # 深度比率
        df['depth_ratio'] = df['bid_depth_5'] / (df['ask_depth_5'] + 1e-9)
        
        return df
    
    def _add_imbalance_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """オーダーインバランス特徴量"""
        # 既にorder_imbalanceがあるので、追加の特徴量を生成
        df['imbalance_abs'] = df['order_imbalance'].abs()
        
        return df
    
    def _add_volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """出来高ベースの特徴量"""
        if 'volume_total' in df.columns:
            # 出来高移動平均
            df['volume_ma_30s'] = df['volume_total'].rolling(window=30).mean()
            df['volume_ma_5m'] = df['volume_total'].rolling(window=300).mean()
            
            # 出来高比率
            df['volume_ratio'] = df['volume_total'] / (df['volume_ma_30s'] + 1e-9)
        
        return df
    
    def _add_execution_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """約定データベースの特徴量"""
        if 'exec_price_buy' not in df.columns:
            # 約定データがない場合はスキップ
            return df
        
        # 1. 約定価格とmid_priceの差
        df['exec_price_diff_buy'] = df['exec_price_buy'] - df['mid_price']
        df['exec_price_diff_sell'] = df['exec_price_sell'] - df['mid_price']
        df['exec_price_diff_all'] = df['exec_price_all'] - df['mid_price']
        
        # 2. 約定価格のBuy/Sell比率
        df['exec_price_ratio'] = df['exec_price_buy'] / (df['exec_price_sell'] + 1e-9)
        
        # 3. 約定価格の移動平均（Buy/Sell別、全体）
        df['exec_price_ma_buy_5s'] = df['exec_price_buy'].rolling(window=5).mean()
        df['exec_price_ma_sell_5s'] = df['exec_price_sell'].rolling(window=5).mean()
        df['exec_price_ma_all_5s'] = df['exec_price_all'].rolling(window=5).mean()
        
        df['exec_price_ma_buy_30s'] = df['exec_price_buy'].rolling(window=30).mean()
        df['exec_price_ma_sell_30s'] = df['exec_price_sell'].rolling(window=30).mean()
        df['exec_price_ma_all_30s'] = df['exec_price_all'].rolling(window=30).mean()
        
        # 4. 約定価格のボラティリティ
        df['exec_price_volatility_buy_30s'] = df['exec_price_buy'].rolling(window=30).std()
        df['exec_price_volatility_sell_30s'] = df['exec_price_sell'].rolling(window=30).std()
        df['exec_price_volatility_all_30s'] = df['exec_price_all'].rolling(window=30).std()
        
        # 5. 約定価格の変化率
        df['exec_price_return_buy_1s'] = df['exec_price_buy'].pct_change(1)
        df['exec_price_return_sell_1s'] = df['exec_price_sell'].pct_change(1)
        df['exec_price_return_all_1s'] = df['exec_price_all'].pct_change(1)
        
        df['exec_price_return_buy_5s'] = df['exec_price_buy'].pct_change(5)
        df['exec_price_return_sell_5s'] = df['exec_price_sell'].pct_change(5)
        df['exec_price_return_all_5s'] = df['exec_price_all'].pct_change(5)
        
        # 6. 約定価格と加重平均価格の差
        if 'exec_price_weighted_buy' in df.columns:
            df['exec_price_weighted_diff_buy'] = df['exec_price_weighted_buy'] - df['exec_price_buy']
            df['exec_price_weighted_diff_sell'] = df['exec_price_weighted_sell'] - df['exec_price_sell']
        
        # 7. Buy/Sellの約定価格のスプレッド
        df['exec_price_spread'] = df['exec_price_sell'] - df['exec_price_buy']
        df['exec_price_spread_ratio'] = df['exec_price_spread'] / (df['mid_price'] + 1e-9)
        
        return df
    
    def _add_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """テクニカル指標"""
        # 移動平均
        df['sma_5'] = df['mid_price'].rolling(window=5).mean()
        df['sma_30'] = df['mid_price'].rolling(window=30).mean()
        
        # ボラティリティ
        df['volatility_30s'] = df['mid_price'].rolling(window=30).std()
        
        return df
    
    def _add_lag_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """ラグ特徴量"""
        # 1秒前、5秒前の価格
        df['mid_price_lag1'] = df['mid_price'].shift(1)
        df['mid_price_lag5'] = df['mid_price'].shift(5)
        
        return df
    
    def _add_rolling_statistics(self, df: pd.DataFrame) -> pd.DataFrame:
        """ローリング統計量"""
        window = 30
        
        # 価格のローリング統計
        df['price_rolling_mean'] = df['mid_price'].rolling(window=window).mean()
        df['price_rolling_std'] = df['mid_price'].rolling(window=window).std()
        
        return df
    
    def get_feature_columns(self) -> List[str]:
        """特徴量カラムのリストを取得"""
        return self.feature_columns

