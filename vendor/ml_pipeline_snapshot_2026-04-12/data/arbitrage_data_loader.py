"""
Arbitrage Data Loader
2つのシンボル（G_FX_BTCJPYとB_FX_BTCJPY）のデータを同時に読み込んで統合
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional
from data.exch_sim_data_loader import ExchSimDataLoader
from config.settings import TrainingConfig, DatabaseConfig


class ArbitrageDataLoader:
    """
    アービトラージ戦略用のデータローダー
    2つのシンボルのデータを同時に読み込んで統合
    """
    
    def __init__(self, use_exch_sim_db=None):
        """
        Args:
            use_exch_sim_db: Trueの場合、exch_simデータベースを使用
        """
        if use_exch_sim_db is None:
            use_exch_sim_db = DatabaseConfig.USE_EXCH_SIM_DB
        
        self.exch_sim_loader = ExchSimDataLoader()
        self.config = TrainingConfig()
    
    def load_arbitrage_data(
        self,
        symbol1: str,
        symbol2: str,
        start_date: datetime,
        end_date: datetime,
        min_quality_score: int = 70
    ) -> pd.DataFrame:
        """
        2つのシンボルのデータを読み込んで統合
        
        Args:
            symbol1: 第1シンボル（例: G_FX_BTCJPY）
            symbol2: 第2シンボル（例: B_FX_BTCJPY）
            start_date: 開始日時
            end_date: 終了日時
            min_quality_score: 最小データ品質スコア
        
        Returns:
            統合されたDataFrame（タイムスタンプでマージ、スプレッド等を計算）
        """
        # 各シンボルのマーケットデータを読み込む
        df1 = self.exch_sim_loader.load_market_data(symbol1, start_date, end_date, min_quality_score)
        df2 = self.exch_sim_loader.load_market_data(symbol2, start_date, end_date, min_quality_score)
        
        # カラム名にシンボル名を付与
        df1_renamed = df1.copy()
        df1_renamed.columns = [f'{symbol1}_{col}' if col != 'symbol' else col for col in df1_renamed.columns]
        
        df2_renamed = df2.copy()
        df2_renamed.columns = [f'{symbol2}_{col}' if col != 'symbol' else col for col in df2_renamed.columns]
        
        # タイムスタンプでマージ（外側結合）
        df_merged = pd.merge(
            df1_renamed,
            df2_renamed,
            left_index=True,
            right_index=True,
            how='outer',
            suffixes=('', '_2')
        )
        
        # タイムスタンプでソート
        df_merged = df_merged.sort_index()
        
        # 前進フィル（forward fill）で欠損値を埋める
        # 各シンボルのデータが存在する範囲内で前の値を使用
        df_merged = df_merged.ffill()
        
        # 両方のシンボルのデータが存在する行のみを残す
        symbol1_price_col = f'{symbol1}_mid_price'
        symbol2_price_col = f'{symbol2}_mid_price'
        
        if symbol1_price_col in df_merged.columns and symbol2_price_col in df_merged.columns:
            df_merged = df_merged.dropna(subset=[symbol1_price_col, symbol2_price_col])
        
        if len(df_merged) == 0:
            raise ValueError(
                f"No overlapping data found for {symbol1} and {symbol2} "
                f"between {start_date} and {end_date}"
            )
        
        # スプレッドを計算
        if symbol1_price_col in df_merged.columns and symbol2_price_col in df_merged.columns:
            df_merged['spread'] = df_merged[symbol1_price_col] - df_merged[symbol2_price_col]
            df_merged['spread_ratio'] = df_merged['spread'] / (df_merged[symbol2_price_col] + 1e-9)
        
        # シンボル情報を追加
        df_merged['symbol1'] = symbol1
        df_merged['symbol2'] = symbol2
        
        return df_merged
    
    def load_arbitrage_training_data(
        self,
        symbol1: str,
        symbol2: str,
        start_date: datetime,
        end_date: datetime,
        resample_freq: str = '1S'
    ) -> pd.DataFrame:
        """
        訓練用データセットを生成
        板情報 + 約定情報を統合（2つのシンボル）
        
        Args:
            symbol1: 第1シンボル
            symbol2: 第2シンボル
            start_date: 開始日時
            end_date: 終了日時
            resample_freq: リサンプル頻度
        
        Returns:
            統合された訓練用DataFrame
        """
        # 各シンボルの訓練データを読み込む
        df1 = self.exch_sim_loader.load_training_data(symbol1, start_date, end_date, resample_freq)
        df2 = self.exch_sim_loader.load_training_data(symbol2, start_date, end_date, resample_freq)
        
        # カラム名にシンボル名を付与
        df1_renamed = df1.copy()
        df1_renamed.columns = [f'{symbol1}_{col}' if col != 'symbol' else col for col in df1_renamed.columns]
        
        df2_renamed = df2.copy()
        df2_renamed.columns = [f'{symbol2}_{col}' if col != 'symbol' else col for col in df2_renamed.columns]
        
        # タイムスタンプでマージ
        df_merged = pd.merge(
            df1_renamed,
            df2_renamed,
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
        symbol1_price_col = f'{symbol1}_mid_price'
        symbol2_price_col = f'{symbol2}_mid_price'
        
        if symbol1_price_col in df_merged.columns and symbol2_price_col in df_merged.columns:
            df_merged = df_merged.dropna(subset=[symbol1_price_col, symbol2_price_col])
        
        if len(df_merged) == 0:
            raise ValueError(
                f"No overlapping training data found for {symbol1} and {symbol2} "
                f"between {start_date} and {end_date}"
            )
        
        # スプレッドを計算
        if symbol1_price_col in df_merged.columns and symbol2_price_col in df_merged.columns:
            df_merged['spread'] = df_merged[symbol1_price_col] - df_merged[symbol2_price_col]
            df_merged['spread_ratio'] = df_merged['spread'] / (df_merged[symbol2_price_col] + 1e-9)
        
        # 両市場の出来高合計
        symbol1_volume_col = f'{symbol1}_volume_total'
        symbol2_volume_col = f'{symbol2}_volume_total'
        
        if symbol1_volume_col in df_merged.columns and symbol2_volume_col in df_merged.columns:
            df_merged['total_volume'] = df_merged[symbol1_volume_col] + df_merged[symbol2_volume_col]
            df_merged['volume_ratio'] = df_merged[symbol1_volume_col] / (df_merged[symbol2_volume_col] + 1e-9)
        
        # シンボル情報を追加
        df_merged['symbol1'] = symbol1
        df_merged['symbol2'] = symbol2
        
        return df_merged.fillna(0)
    
    def close(self):
        """接続を閉じる"""
        self.exch_sim_loader.close()

