"""
Spot Arbitrage Data Loader
FXと現物のアービトラージ戦略専用のデータローダー
現物は買いからしか入れないという制約を考慮
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional
from data.exch_sim_data_loader import ExchSimDataLoader
from config.settings import TrainingConfig, DatabaseConfig


class SpotArbitrageDataLoader:
    """
    現物アービトラージ戦略用のデータローダー
    FXと現物の2つのシンボルのデータを同時に読み込んで統合
    """
    
    def __init__(self):
        self.exch_sim_loader = ExchSimDataLoader()
        self.config = TrainingConfig()
    
    def load_spot_arbitrage_data(
        self,
        fx_symbol: str,
        spot_symbol: str,
        start_date: datetime,
        end_date: datetime,
        min_quality_score: int = 70
    ) -> pd.DataFrame:
        """
        FXと現物の2つのシンボルのデータを読み込んで統合
        
        Args:
            fx_symbol: FXシンボル（例: G_FX_BTCJPY）
            spot_symbol: 現物シンボル（例: B_FX_BTCJPY）
            start_date: 開始日時
            end_date: 終了日時
            min_quality_score: 最小データ品質スコア
        
        Returns:
            統合されたDataFrame（タイムスタンプでマージ、スプレッド等を計算）
        """
        # 各シンボルのマーケットデータを読み込む
        fx_df = self.exch_sim_loader.load_market_data(fx_symbol, start_date, end_date, min_quality_score)
        spot_df = self.exch_sim_loader.load_market_data(spot_symbol, start_date, end_date, min_quality_score)
        
        # カラム名にシンボル名を付与
        fx_df_renamed = fx_df.copy()
        fx_df_renamed.columns = [f'{fx_symbol}_{col}' if col != 'symbol' else col for col in fx_df_renamed.columns]
        
        spot_df_renamed = spot_df.copy()
        spot_df_renamed.columns = [f'{spot_symbol}_{col}' if col != 'symbol' else col for col in spot_df_renamed.columns]
        
        # タイムスタンプでマージ（外側結合）
        df_merged = pd.merge(
            fx_df_renamed,
            spot_df_renamed,
            left_index=True,
            right_index=True,
            how='outer',
            suffixes=('', '_2')
        )
        
        # タイムスタンプでソート
        df_merged = df_merged.sort_index()
        
        # 前進フィル（forward fill）で欠損値を埋める
        df_merged = df_merged.ffill()
        
        # 両方のシンボルのデータが存在する行のみを残す
        fx_price_col = f'{fx_symbol}_mid_price'
        spot_price_col = f'{spot_symbol}_mid_price'
        
        if fx_price_col in df_merged.columns and spot_price_col in df_merged.columns:
            df_merged = df_merged.dropna(subset=[fx_price_col, spot_price_col])
        
        if len(df_merged) == 0:
            raise ValueError(
                f"No overlapping data found for {fx_symbol} (FX) and {spot_symbol} (Spot) "
                f"between {start_date} and {end_date}"
            )
        
        # スプレッドを計算（FX - Spot）
        if fx_price_col in df_merged.columns and spot_price_col in df_merged.columns:
            df_merged['spread'] = df_merged[fx_price_col] - df_merged[spot_price_col]
            df_merged['spread_ratio'] = df_merged['spread'] / (df_merged[spot_price_col] + 1e-9)
        
        # シンボル情報を追加
        df_merged['fx_symbol'] = fx_symbol
        df_merged['spot_symbol'] = spot_symbol
        
        return df_merged
    
    def load_spot_arbitrage_training_data(
        self,
        fx_symbol: str,
        spot_symbol: str,
        start_date: datetime,
        end_date: datetime,
        resample_freq: str = '1S'
    ) -> pd.DataFrame:
        """
        訓練用データセットを生成
        板情報 + 約定情報を統合（FXと現物の2つのシンボル）
        
        Args:
            fx_symbol: FXシンボル
            spot_symbol: 現物シンボル
            start_date: 開始日時
            end_date: 終了日時
            resample_freq: リサンプル頻度
        
        Returns:
            統合された訓練用DataFrame
        """
        # 各シンボルの訓練データを読み込む
        fx_df = self.exch_sim_loader.load_training_data(fx_symbol, start_date, end_date, resample_freq)
        spot_df = self.exch_sim_loader.load_training_data(spot_symbol, start_date, end_date, resample_freq)
        
        # カラム名にシンボル名を付与
        fx_df_renamed = fx_df.copy()
        fx_df_renamed.columns = [f'{fx_symbol}_{col}' if col != 'symbol' else col for col in fx_df_renamed.columns]
        
        spot_df_renamed = spot_df.copy()
        spot_df_renamed.columns = [f'{spot_symbol}_{col}' if col != 'symbol' else col for col in spot_df_renamed.columns]
        
        # タイムスタンプでマージ
        df_merged = pd.merge(
            fx_df_renamed,
            spot_df_renamed,
            left_index=True,
            right_index=True,
            how='outer',
            suffixes=('', '_2')
        )
        
        # タイムスタンプでソート
        df_merged = df_merged.sort_index()
        
        # 前進フィルで欠損値を埋める
        df_merged = df_merged.ffill()
        
        # 両方のシンボルのデータが存在する行のみを残す
        fx_price_col = f'{fx_symbol}_mid_price'
        spot_price_col = f'{spot_symbol}_mid_price'
        
        if fx_price_col in df_merged.columns and spot_price_col in df_merged.columns:
            df_merged = df_merged.dropna(subset=[fx_price_col, spot_price_col])
        
        if len(df_merged) == 0:
            raise ValueError(
                f"No overlapping training data found for {fx_symbol} (FX) and {spot_symbol} (Spot) "
                f"between {start_date} and {end_date}"
            )
        
        # スプレッドを計算（FX - Spot）
        if fx_price_col in df_merged.columns and spot_price_col in df_merged.columns:
            df_merged['spread'] = df_merged[fx_price_col] - df_merged[spot_price_col]
            df_merged['spread_ratio'] = df_merged['spread'] / (df_merged[spot_price_col] + 1e-9)
        
        # 両市場の出来高合計
        fx_volume_col = f'{fx_symbol}_volume_total'
        spot_volume_col = f'{spot_symbol}_volume_total'
        
        if fx_volume_col in df_merged.columns and spot_volume_col in df_merged.columns:
            df_merged['total_volume'] = df_merged[fx_volume_col] + df_merged[spot_volume_col]
            df_merged['volume_ratio'] = df_merged[fx_volume_col] / (df_merged[spot_volume_col] + 1e-9)
        
        # シンボル情報を追加
        df_merged['fx_symbol'] = fx_symbol
        df_merged['spot_symbol'] = spot_symbol
        
        return df_merged.fillna(0)
    
    def close(self):
        """接続を閉じる"""
        self.exch_sim_loader.close()

