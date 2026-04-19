"""
Market Data Loader
"""
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
from typing import Optional
from config.settings import TrainingConfig, DatabaseConfig
from data.exch_sim_data_loader import ExchSimDataLoader


class MarketDataLoader:
    def __init__(self, use_exch_sim_db=None):
        """
        Args:
            use_exch_sim_db: Trueの場合、exch_simデータベースを使用
                            Noneの場合、設定ファイルのUSE_EXCH_SIM_DBを参照
        """
        self.config = TrainingConfig()
        
        # exch_simデータベースを使用するかどうか
        if use_exch_sim_db is None:
            use_exch_sim_db = DatabaseConfig.USE_EXCH_SIM_DB
        
        if use_exch_sim_db:
            # exch_simデータベースから読み込む
            self.exch_sim_loader = ExchSimDataLoader()
            self.use_exch_sim = True
        else:
            # algo_traderデータベースから読み込む
            self.conn = psycopg2.connect(DatabaseConfig.get_connection_string())
            self.use_exch_sim = False
    
    def load_market_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        min_quality_score: int = 70,
        skip_min_samples_check: bool = False
    ) -> pd.DataFrame:
        """
        板情報の時系列データをロード
        """
        if self.use_exch_sim:
            # exch_simデータベースから読み込む
            df = self.exch_sim_loader.load_market_data(
                symbol, start_date, end_date, 
                skip_min_samples_check=skip_min_samples_check
            )
            # データ品質スコアでフィルタリング
            df = df[df['data_quality_score'] >= min_quality_score]
            return df
        else:
            # algo_traderデータベースから読み込む
            query = """
            SELECT 
                timestamp,
                symbol,
                bid_price_1, bid_qty_1,
                ask_price_1, ask_qty_1,
                spread, mid_price,
                bid_depth_5, ask_depth_5,
                order_imbalance
            FROM market_data
            WHERE symbol = %s
              AND timestamp BETWEEN %s AND %s
              AND data_quality_score >= %s
            ORDER BY timestamp
            """
            
            try:
                df = pd.read_sql_query(
                    query,
                    self.conn,
                    params=(symbol, start_date, end_date, min_quality_score)
                )
            except Exception as e:
                # より詳細なエラーメッセージを提供
                print(f"\nError querying database:")
                print(f"  Symbol: {symbol}")
                print(f"  Start Date: {start_date}")
                print(f"  End Date: {end_date}")
                print(f"  Min Quality Score: {min_quality_score}")
                print(f"  Error: {e}")
                
                # データが存在するか確認
                check_query = """
                SELECT COUNT(*) as count,
                       MIN(timestamp) as min_ts,
                       MAX(timestamp) as max_ts
                FROM market_data
                WHERE symbol = %s
                """
                try:
                    check_df = pd.read_sql_query(check_query, self.conn, params=(symbol,))
                    if len(check_df) > 0:
                        count = check_df['count'].iloc[0]
                        min_ts = check_df['min_ts'].iloc[0]
                        max_ts = check_df['max_ts'].iloc[0]
                        print(f"\nAvailable data in database:")
                        print(f"  Total records: {count}")
                        if min_ts:
                            print(f"  Earliest timestamp: {min_ts}")
                        if max_ts:
                            print(f"  Latest timestamp: {max_ts}")
                        if min_ts and max_ts:
                            print(f"\nRequested period: {start_date} to {end_date}")
                            print(f"Available period: {min_ts} to {max_ts}")
                except:
                    pass
                
                raise
            
            if len(df) == 0:
                # データが存在しない場合、より詳細な情報を提供
                print(f"\nNo data found for the specified period:")
                print(f"  Symbol: {symbol}")
                print(f"  Start Date: {start_date}")
                print(f"  End Date: {end_date}")
                print(f"  Min Quality Score: {min_quality_score}")
                
                # データが存在するか確認
                check_query = """
                SELECT COUNT(*) as count,
                       MIN(timestamp) as min_ts,
                       MAX(timestamp) as max_ts
                FROM market_data
                WHERE symbol = %s
                """
                try:
                    check_df = pd.read_sql_query(check_query, self.conn, params=(symbol,))
                    if len(check_df) > 0:
                        count = check_df['count'].iloc[0]
                        min_ts = check_df['min_ts'].iloc[0]
                        max_ts = check_df['max_ts'].iloc[0]
                        print(f"\nAvailable data in database:")
                        print(f"  Total records: {count}")
                        if min_ts:
                            print(f"  Earliest timestamp: {min_ts}")
                        if max_ts:
                            print(f"  Latest timestamp: {max_ts}")
                        if min_ts and max_ts:
                            print(f"\nSuggestion: Use --start-date and --end-date to specify a period with data")
                            print(f"  Example: --start-date '{min_ts}' --end-date '{max_ts}'")
                except Exception as check_e:
                    print(f"  Could not check available data: {check_e}")
                
                raise ValueError(
                    f"Insufficient data: {len(df)} samples "
                    f"(minimum: {self.config.MIN_SAMPLES}). "
                    f"Please check if data exists in the database for the specified period."
                )
            
            if not skip_min_samples_check and len(df) < self.config.MIN_SAMPLES:
                raise ValueError(
                    f"Insufficient data: {len(df)} samples "
                    f"(minimum: {self.config.MIN_SAMPLES})"
                )
            
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
            
            return df
    
    def load_recent_training_data(
        self,
        symbol: str,
        days: int = None
    ) -> pd.DataFrame:
        """
        直近N日間の訓練データをロード（デフォルト3日間）
        """
        if days is None:
            days = self.config.TRAINING_WINDOW_DAYS
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        return self.load_training_data(symbol, start_date, end_date)
    
    def load_executions(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        約定履歴をロード
        """
        if self.use_exch_sim:
            # exch_simデータベースから読み込む
            return self.exch_sim_loader.load_executions(symbol, start_date, end_date)
        else:
            # algo_traderデータベースから読み込む
            query = """
            SELECT 
                timestamp,
                symbol,
                price,
                quantity,
                side
            FROM executions
            WHERE symbol = %s
              AND timestamp BETWEEN %s AND %s
              AND (is_maker IS NULL OR is_maker = FALSE)
            ORDER BY timestamp
            """
            
            df = pd.read_sql_query(
                query,
                self.conn,
                params=(symbol, start_date, end_date)
            )
            
            if len(df) > 0:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            return df
    
    def load_training_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        resample_freq: str = '1S',
        skip_min_samples_check: bool = False
    ) -> pd.DataFrame:
        """
        訓練用データセットを生成
        板情報 + 約定情報を統合
        
        Args:
            skip_min_samples_check: Trueの場合、MIN_SAMPLESチェックをスキップ（リアルタイムシグナル生成用）
        """
        if self.use_exch_sim:
            # exch_simデータベースから読み込む
            return self.exch_sim_loader.load_training_data(
                symbol, start_date, end_date, resample_freq, 
                skip_min_samples_check=skip_min_samples_check
            )
        else:
            # algo_traderデータベースから読み込む
            # 板情報
            market_df = self.load_market_data(symbol, start_date, end_date, skip_min_samples_check=skip_min_samples_check)
            
            # 約定情報（出来高計算用）
            exec_df = self.load_executions(symbol, start_date, end_date)
            
            if len(exec_df) > 0:
                exec_df = exec_df.set_index('timestamp')
                
                # 1秒ごとの出来高計算
                volume_buy = exec_df[exec_df['side'] == 'BUY'].resample(resample_freq)['quantity'].sum()
                volume_sell = exec_df[exec_df['side'] == 'SELL'].resample(resample_freq)['quantity'].sum()
                
                # 約定価格の計算（Buy/Sell別、全体）
                exec_price_buy = exec_df[exec_df['side'] == 'BUY'].resample(resample_freq)['price'].mean()
                exec_price_sell = exec_df[exec_df['side'] == 'SELL'].resample(resample_freq)['price'].mean()
                exec_price_all = exec_df.resample(resample_freq)['price'].mean()
                
                # 約定価格の加重平均（数量で重み付け）
                exec_df_weighted = exec_df.copy()
                exec_df_weighted['weight'] = exec_df_weighted['quantity'] * exec_df_weighted['price']
                exec_price_weighted_buy = exec_df_weighted[exec_df_weighted['side'] == 'BUY'].resample(resample_freq)['weight'].sum() / (volume_buy + 1e-9)
                exec_price_weighted_sell = exec_df_weighted[exec_df_weighted['side'] == 'SELL'].resample(resample_freq)['weight'].sum() / (volume_sell + 1e-9)
                
                # 統合
                df = market_df.copy()
                df['volume_buy'] = volume_buy.fillna(0)
                df['volume_sell'] = volume_sell.fillna(0)
                df['volume_total'] = df['volume_buy'] + df['volume_sell']
                df['volume_imbalance'] = (df['volume_buy'] - df['volume_sell']) / (df['volume_total'] + 1e-9)
                
                # 約定価格特徴量
                df['exec_price_buy'] = exec_price_buy
                df['exec_price_sell'] = exec_price_sell
                df['exec_price_all'] = exec_price_all
                df['exec_price_weighted_buy'] = exec_price_weighted_buy
                df['exec_price_weighted_sell'] = exec_price_weighted_sell
                
                # NaNを前の値で埋める（約定がない場合はmid_priceを使用）
                df['exec_price_buy'] = df['exec_price_buy'].ffill().fillna(df['mid_price'])
                df['exec_price_sell'] = df['exec_price_sell'].ffill().fillna(df['mid_price'])
                df['exec_price_all'] = df['exec_price_all'].ffill().fillna(df['mid_price'])
                df['exec_price_weighted_buy'] = df['exec_price_weighted_buy'].ffill().fillna(df['mid_price'])
                df['exec_price_weighted_sell'] = df['exec_price_weighted_sell'].ffill().fillna(df['mid_price'])
            else:
                df = market_df.copy()
                df['volume_buy'] = 0
                df['volume_sell'] = 0
                df['volume_total'] = 0
                df['volume_imbalance'] = 0
                df['exec_price_buy'] = df['mid_price']
                df['exec_price_sell'] = df['mid_price']
                df['exec_price_all'] = df['mid_price']
                df['exec_price_weighted_buy'] = df['mid_price']
                df['exec_price_weighted_sell'] = df['mid_price']
            
            return df.fillna(0)
    
    def close(self):
        if self.use_exch_sim:
            self.exch_sim_loader.close()
        else:
            self.conn.close()

