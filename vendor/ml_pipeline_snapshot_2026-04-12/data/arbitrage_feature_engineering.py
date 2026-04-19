"""
Arbitrage Feature Engineering
アービトラージ戦略用の特徴量エンジニアリング
"""
import pandas as pd
import numpy as np
from typing import List


class ArbitrageFeatureEngineer:
    """
    アービトラージ戦略用の特徴量エンジニアリング
    """
    
    def __init__(self, lookback_period: int = 3600):
        """
        Args:
            lookback_period: Zスコア計算用の履歴期間（秒、デフォルト3600秒=1時間）
        """
        self.lookback_period = lookback_period
        self.feature_columns = []
    
    def engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        アービトラージ戦略用の特徴量を生成
        
        Args:
            df: 2つのシンボルの統合データ（spread列を含む）
        
        Returns:
            特徴量が追加されたDataFrame
        """
        df = df.copy()
        
        # 1. スプレッドベースの特徴量
        df = self._add_spread_features(df)
        
        # 2. Zスコア特徴量
        df = self._add_zscore_features(df)
        
        # 3. 両市場の板の厚み比率特徴量
        df = self._add_depth_ratio_features(df)
        
        # 4. 両市場の出来高比率特徴量
        df = self._add_volume_ratio_features(df)
        
        # 5. スプレッドのテクニカル指標
        df = self._add_spread_technical_indicators(df)
        
        # 6. ラグ特徴量
        df = self._add_lag_features(df)
        
        # 7. ローリング統計量
        df = self._add_rolling_statistics(df)
        
        # NaNを0で埋める
        df = df.fillna(0)
        
        # 特徴量カラムを保存（spread, symbol1, symbol2, 各シンボルの価格等を除く）
        exclude_cols = ['spread', 'symbol1', 'symbol2', 'spread_ratio']
        self.feature_columns = [col for col in df.columns 
                               if col not in exclude_cols and not col.startswith('G_FX_BTCJPY_mid_price') 
                               and not col.startswith('B_FX_BTCJPY_mid_price')]
        
        return df
    
    def _add_spread_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """スプレッドベースの特徴量"""
        if 'spread' not in df.columns:
            return df
        
        # スプレッドの変化率
        df['spread_return_1s'] = df['spread'].pct_change(1)
        df['spread_return_5s'] = df['spread'].pct_change(5)
        df['spread_return_30s'] = df['spread'].pct_change(30)
        
        # スプレッドの絶対値
        df['spread_abs'] = df['spread'].abs()
        
        # スプレッド比率（既に計算済みの場合はスキップ）
        if 'spread_ratio' not in df.columns:
            # 両市場の平均価格で正規化
            symbol1_price_col = None
            symbol2_price_col = None
            for col in df.columns:
                if 'G_FX_BTCJPY_mid_price' in col:
                    symbol1_price_col = col
                if 'B_FX_BTCJPY_mid_price' in col:
                    symbol2_price_col = col
            
            if symbol1_price_col and symbol2_price_col:
                avg_price = (df[symbol1_price_col] + df[symbol2_price_col]) / 2
                df['spread_ratio'] = df['spread'] / (avg_price + 1e-9)
        
        return df
    
    def _add_zscore_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Zスコア特徴量"""
        if 'spread' not in df.columns:
            return df
        
        # ローリング平均と標準偏差
        window = min(self.lookback_period, len(df))
        if window < 30:
            window = min(30, len(df))
        
        df['spread_mean'] = df['spread'].rolling(window=window, min_periods=30).mean()
        df['spread_std'] = df['spread'].rolling(window=window, min_periods=30).std()
        
        # Zスコア
        df['spread_zscore'] = np.where(
            df['spread_std'] > 1e-6,
            (df['spread'] - df['spread_mean']) / df['spread_std'],
            0
        )
        
        # Zスコアの絶対値
        df['spread_zscore_abs'] = df['spread_zscore'].abs()
        
        # Zスコアの変化率
        df['spread_zscore_return_1s'] = df['spread_zscore'].pct_change(1)
        df['spread_zscore_return_5s'] = df['spread_zscore'].pct_change(5)
        
        return df
    
    def _add_depth_ratio_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """両市場の板の厚み比率特徴量"""
        # シンボル1の深度カラムを探す
        symbol1_depth_cols = [col for col in df.columns if 'G_FX_BTCJPY_bid_depth' in col or 'G_FX_BTCJPY_ask_depth' in col]
        symbol2_depth_cols = [col for col in df.columns if 'B_FX_BTCJPY_bid_depth' in col or 'B_FX_BTCJPY_ask_depth' in col]
        
        if not symbol1_depth_cols or not symbol2_depth_cols:
            return df
        
        # 各シンボルの総深度を計算
        symbol1_bid_depth = None
        symbol1_ask_depth = None
        symbol2_bid_depth = None
        symbol2_ask_depth = None
        
        for col in df.columns:
            if 'G_FX_BTCJPY_bid_depth' in col:
                symbol1_bid_depth = col
            if 'G_FX_BTCJPY_ask_depth' in col:
                symbol1_ask_depth = col
            if 'B_FX_BTCJPY_bid_depth' in col:
                symbol2_bid_depth = col
            if 'B_FX_BTCJPY_ask_depth' in col:
                symbol2_ask_depth = col
        
        if symbol1_bid_depth and symbol1_ask_depth and symbol2_bid_depth and symbol2_ask_depth:
            symbol1_total_depth = df[symbol1_bid_depth] + df[symbol1_ask_depth]
            symbol2_total_depth = df[symbol2_bid_depth] + df[symbol2_ask_depth]
            
            # 深度比率
            df['depth_ratio'] = symbol1_total_depth / (symbol2_total_depth + 1e-9)
            
            # 深度インバランス
            df['depth_imbalance_1'] = (df[symbol1_bid_depth] - df[symbol1_ask_depth]) / (symbol1_total_depth + 1e-9)
            df['depth_imbalance_2'] = (df[symbol2_bid_depth] - df[symbol2_ask_depth]) / (symbol2_total_depth + 1e-9)
            df['depth_imbalance_diff'] = df['depth_imbalance_1'] - df['depth_imbalance_2']
        
        return df
    
    def _add_volume_ratio_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """両市場の出来高比率特徴量"""
        # シンボル1の出来高カラムを探す
        symbol1_volume_col = None
        symbol2_volume_col = None
        
        for col in df.columns:
            if 'G_FX_BTCJPY_volume_total' in col:
                symbol1_volume_col = col
            if 'B_FX_BTCJPY_volume_total' in col:
                symbol2_volume_col = col
        
        if symbol1_volume_col and symbol2_volume_col:
            # 出来高比率（既に計算済みの場合はスキップ）
            if 'volume_ratio' not in df.columns:
                df['volume_ratio'] = df[symbol1_volume_col] / (df[symbol2_volume_col] + 1e-9)
            
            # 出来高インバランス
            if 'total_volume' in df.columns:
                df['volume_imbalance'] = (df[symbol1_volume_col] - df[symbol2_volume_col]) / (df['total_volume'] + 1e-9)
            
            # 出来高の移動平均比率
            df['volume_ma_ratio_30s'] = (
                df[symbol1_volume_col].rolling(window=30).mean() / 
                (df[symbol2_volume_col].rolling(window=30).mean() + 1e-9)
            )
        
        return df
    
    def _add_spread_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """スプレッドのテクニカル指標"""
        if 'spread' not in df.columns:
            return df
        
        # 移動平均
        df['spread_sma_5'] = df['spread'].rolling(window=5).mean()
        df['spread_sma_30'] = df['spread'].rolling(window=30).mean()
        df['spread_sma_300'] = df['spread'].rolling(window=300).mean()
        
        # ボラティリティ
        df['spread_volatility_30s'] = df['spread'].rolling(window=30).std()
        df['spread_volatility_300s'] = df['spread'].rolling(window=300).std()
        
        # スプレッドが移動平均からどれだけ離れているか
        df['spread_deviation_from_sma'] = df['spread'] - df['spread_sma_30']
        df['spread_deviation_ratio'] = df['spread_deviation_from_sma'] / (df['spread_sma_30'].abs() + 1e-9)
        
        return df
    
    def _add_lag_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """ラグ特徴量"""
        if 'spread' not in df.columns:
            return df
        
        # 1秒前、5秒前のスプレッド
        df['spread_lag1'] = df['spread'].shift(1)
        df['spread_lag5'] = df['spread'].shift(5)
        
        # Zスコアのラグ
        if 'spread_zscore' in df.columns:
            df['spread_zscore_lag1'] = df['spread_zscore'].shift(1)
            df['spread_zscore_lag5'] = df['spread_zscore'].shift(5)
        
        return df
    
    def _add_rolling_statistics(self, df: pd.DataFrame) -> pd.DataFrame:
        """ローリング統計量"""
        if 'spread' not in df.columns:
            return df
        
        window = 30
        
        # スプレッドのローリング統計
        df['spread_rolling_mean'] = df['spread'].rolling(window=window).mean()
        df['spread_rolling_std'] = df['spread'].rolling(window=window).std()
        df['spread_rolling_min'] = df['spread'].rolling(window=window).min()
        df['spread_rolling_max'] = df['spread'].rolling(window=window).max()
        
        # スプレッドがローリング範囲内のどこに位置するか
        spread_range = df['spread_rolling_max'] - df['spread_rolling_min']
        df['spread_position_in_range'] = np.where(
            spread_range > 1e-6,
            (df['spread'] - df['spread_rolling_min']) / spread_range,
            0.5
        )
        
        return df
    
    def get_feature_columns(self) -> List[str]:
        """特徴量カラムのリストを取得"""
        return self.feature_columns

