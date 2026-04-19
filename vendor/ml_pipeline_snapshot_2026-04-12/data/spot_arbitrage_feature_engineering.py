"""
Spot Arbitrage Feature Engineering
FXと現物のアービトラージ戦略専用の特徴量エンジニアリング
現物は買いからしか入れないという制約を考慮
"""
import pandas as pd
import numpy as np
from typing import List


class SpotArbitrageFeatureEngineer:
    """
    現物アービトラージ戦略用の特徴量エンジニアリング
    FXと現物の価格差（スプレッド）を中心とした特徴量を生成
    """
    
    def __init__(self, lookback_period: int = 300):
        """
        Args:
            lookback_period: Zスコアなどの計算に使用するルックバック期間（秒）
        """
        self.lookback_period = lookback_period
        self.feature_columns = []
    
    def engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        現物アービトラージ戦略用の特徴量を生成
        
        Args:
            df: FXと現物の統合データ（spread, fx_symbol, spot_symbolを含む）
        
        Returns:
            特徴量が追加されたDataFrame
        """
        df = df.copy()
        
        fx_symbol = df['fx_symbol'].iloc[0] if 'fx_symbol' in df.columns else 'G_FX_BTCJPY'
        spot_symbol = df['spot_symbol'].iloc[0] if 'spot_symbol' in df.columns else 'B_FX_BTCJPY'
        
        # 1. スプレッドベースの特徴量
        df = self._add_spread_features(df, fx_symbol, spot_symbol)
        
        # 2. Zスコア特徴量
        df = self._add_zscore_features(df)
        
        # 3. FXと現物の板の厚み・出来高比率特徴量
        df = self._add_market_comparison_features(df, fx_symbol, spot_symbol)
        
        # 4. テクニカル指標（スプレッドに対して）
        df = self._add_technical_indicators(df)
        
        # 5. ラグ特徴量
        df = self._add_lag_features(df)
        
        # NaNを0で埋める
        df = df.fillna(0)
        
        # 特徴量カラムを保存（価格やシンボル情報を除く）
        exclude_cols = ['spread', 'spread_ratio', 'fx_symbol', 'spot_symbol', 
                       f'{fx_symbol}_mid_price', f'{spot_symbol}_mid_price']
        self.feature_columns = [col for col in df.columns if col not in exclude_cols]
        
        return df
    
    def _add_spread_features(self, df: pd.DataFrame, fx_symbol: str, spot_symbol: str) -> pd.DataFrame:
        """スプレッドベースの特徴量"""
        # スプレッドの変化率
        df['spread_return_1s'] = df['spread'].pct_change(1)
        df['spread_return_5s'] = df['spread'].pct_change(5)
        df['spread_return_10s'] = df['spread'].pct_change(10)
        
        # スプレッドの絶対値
        df['spread_abs'] = df['spread'].abs()
        
        # スプレッドの比率（FX/Spot）
        fx_price_col = f'{fx_symbol}_mid_price'
        spot_price_col = f'{spot_symbol}_mid_price'
        if fx_price_col in df.columns and spot_price_col in df.columns:
            df['fx_spot_ratio'] = df[fx_price_col] / (df[spot_price_col] + 1e-9)
            df['fx_spot_ratio_return_1s'] = df['fx_spot_ratio'].pct_change(1)
        
        return df
    
    def _add_zscore_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Zスコア特徴量"""
        # スプレッドのローリング平均と標準偏差
        df['spread_mean'] = df['spread'].rolling(window=self.lookback_period).mean()
        df['spread_std'] = df['spread'].rolling(window=self.lookback_period).std()
        
        # Zスコア
        df['spread_zscore'] = (df['spread'] - df['spread_mean']) / (df['spread_std'] + 1e-9)
        df['spread_zscore_abs'] = df['spread_zscore'].abs()
        
        # Zスコアの変化率
        df['spread_zscore_return_1s'] = df['spread_zscore'].pct_change(1)
        df['spread_zscore_return_5s'] = df['spread_zscore'].pct_change(5)
        
        return df
    
    def _add_market_comparison_features(self, df: pd.DataFrame, fx_symbol: str, spot_symbol: str) -> pd.DataFrame:
        """FXと現物の比較特徴量"""
        # 板の厚み比率
        fx_bid_depth_col = f'{fx_symbol}_bid_depth_5'
        spot_ask_depth_col = f'{spot_symbol}_ask_depth_5'
        
        if fx_bid_depth_col in df.columns and spot_ask_depth_col in df.columns:
            df['depth_ratio_fx_spot'] = df[fx_bid_depth_col] / (df[spot_ask_depth_col] + 1e-9)
        
        # 出来高比率
        fx_volume_col = f'{fx_symbol}_volume_total'
        spot_volume_col = f'{spot_symbol}_volume_total'
        
        if fx_volume_col in df.columns and spot_volume_col in df.columns:
            df['volume_total_ratio'] = df[fx_volume_col] / (df[spot_volume_col] + 1e-9)
            df['volume_imbalance_diff'] = df.get(f'{fx_symbol}_volume_imbalance', 0) - df.get(f'{spot_symbol}_volume_imbalance', 0)
        
        # スプレッドの方向性（現物がFXより安いかどうか）
        df['spot_cheaper'] = (df['spread'] > 0).astype(int)  # spread = FX - Spot > 0 なら現物が安い
        
        return df
    
    def _add_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """テクニカル指標（スプレッドに対して）"""
        # スプレッドの移動平均
        df['spread_sma_5'] = df['spread'].rolling(window=5).mean()
        df['spread_sma_30'] = df['spread'].rolling(window=30).mean()
        df['spread_sma_60'] = df['spread'].rolling(window=60).mean()
        
        # スプレッドのボラティリティ
        df['spread_volatility_30s'] = df['spread'].rolling(window=30).std()
        df['spread_volatility_60s'] = df['spread'].rolling(window=60).std()
        
        # スプレッドのモメンタム
        df['spread_momentum_5s'] = df['spread'] - df['spread'].shift(5)
        df['spread_momentum_10s'] = df['spread'] - df['spread'].shift(10)
        
        return df
    
    def _add_lag_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """ラグ特徴量"""
        # 1秒前、5秒前、10秒前のスプレッド
        df['spread_lag1'] = df['spread'].shift(1)
        df['spread_lag5'] = df['spread'].shift(5)
        df['spread_lag10'] = df['spread'].shift(10)
        
        # 1秒前、5秒前のZスコア
        df['spread_zscore_lag1'] = df['spread_zscore'].shift(1)
        df['spread_zscore_lag5'] = df['spread_zscore'].shift(5)
        
        return df
    
    def get_feature_columns(self) -> List[str]:
        """特徴量カラムのリストを取得"""
        return self.feature_columns

