"""
ExchSim Database Data Loader
exch_simデータベースからマーケットデータを取得して、algo_trader形式に変換
"""
import pandas as pd
import numpy as np
import psycopg2
from datetime import datetime, timedelta
from typing import Optional
from config.settings import TrainingConfig, DatabaseConfig
from data.db_pool import DatabaseConnectionPool


class ExchSimDataLoader:
    """
    exch_simデータベースからマーケットデータを取得するローダー
    market_board_snapshotsとmarket_board_price_levelsを結合して、
    algo_traderのmarket_dataテーブルと同じ形式に変換
    """
    
    def __init__(self, use_connection_pool: bool = True):
        """
        初期化
        
        Args:
            use_connection_pool: True の場合は接続プールを使用、False の場合は直接接続
        """
        self.use_connection_pool = use_connection_pool
        self.config = TrainingConfig()
        
        if use_connection_pool:
            # 接続プールから接続を取得（使用時に取得するため、ここでは保持しない）
            self.conn = None
        else:
            # 直接接続（後方互換性のため）
            self.conn = psycopg2.connect(DatabaseConfig.get_exch_sim_connection_string())
    
    def _get_connection(self):
        """接続を取得（接続プールを使用する場合はプールから取得）"""
        if self.use_connection_pool:
            return DatabaseConnectionPool.get_connection(use_exch_sim_db=True)
        else:
            return self.conn
    
    def _return_connection(self, conn):
        """接続を返却（接続プールを使用する場合はプールに返却）"""
        if self.use_connection_pool and conn is not None:
            DatabaseConnectionPool.put_connection(conn, use_exch_sim_db=True)
    
    def load_market_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        min_levels: int = 5,
        skip_min_samples_check: bool = False
    ) -> pd.DataFrame:
        """
        exch_simデータベースから板情報をロードして、algo_trader形式に変換
        
        Args:
            symbol: 銘柄名
            start_date: 開始日時（UTC、tzinfoがNoneの場合はUTCとして扱う）
            end_date: 終了日時（UTC、tzinfoがNoneの場合はUTCとして扱う）
            min_levels: 最小価格レベル数（デフォルト5）
        
        Returns:
            algo_traderのmarket_dataテーブルと同じ形式のDataFrame
        """
        # datetimeオブジェクトのタイムゾーンを正規化（UTCとして扱う）
        from datetime import timezone
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        else:
            start_date = start_date.astimezone(timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        else:
            end_date = end_date.astimezone(timezone.utc)
        
        # timestamp without time zoneカラムと比較するため、タイムゾーン情報を削除
        # （PostgreSQLのtimestamp without time zoneはタイムゾーン情報を持たない）
        start_date_naive = start_date.replace(tzinfo=None)
        end_date_naive = end_date.replace(tzinfo=None)
        
        # 最適化されたクエリ: サブクエリを使用して必要なデータのみを事前にフィルタリング
        # インデックス idx_price_levels_snapshot_side_level_0_4 を活用
        # timestamp without time zoneカラムと比較するため、文字列として渡して明示的にキャスト
        start_str = start_date_naive.strftime('%Y-%m-%d %H:%M:%S')
        end_str = end_date_naive.strftime('%Y-%m-%d %H:%M:%S')
        
        query = """
        WITH filtered_snapshots AS (
            -- まず、条件に合うスナップショットのみを取得（インデックス idx_snapshots_symbol_timestamp_id を活用）
            SELECT 
                s.id,
                s.timestamp,
                s.symbol
            FROM market_board_snapshots s
            WHERE s.symbol = %s
              AND s.timestamp BETWEEN %s::timestamp AND %s::timestamp
        ),
        price_levels_aggregated AS (
            -- 必要な price_levels のみを集計（インデックス idx_price_levels_snapshot_side_level_0_4 を活用）
            SELECT 
                l.snapshot_id,
                -- 最良BID/ASK（level_index=0）
                MAX(CASE WHEN l.side = 'BID' AND l.level_index = 0 THEN l.price END) as bid_price_1,
                MAX(CASE WHEN l.side = 'BID' AND l.level_index = 0 THEN l.quantity END) as bid_qty_1,
                MAX(CASE WHEN l.side = 'ASK' AND l.level_index = 0 THEN l.price END) as ask_price_1,
                MAX(CASE WHEN l.side = 'ASK' AND l.level_index = 0 THEN l.quantity END) as ask_qty_1,
                -- 深度（level_index 0-4の合計）
                COALESCE(SUM(CASE WHEN l.side = 'BID' AND l.level_index < 5 THEN l.quantity END), 0) as bid_depth_5,
                COALESCE(SUM(CASE WHEN l.side = 'ASK' AND l.level_index < 5 THEN l.quantity END), 0) as ask_depth_5
            FROM market_board_price_levels l
            WHERE l.snapshot_id IN (SELECT id FROM filtered_snapshots)
              AND l.level_index < 5  -- 必要な範囲のみをフィルタリング
            GROUP BY l.snapshot_id
            HAVING COUNT(CASE WHEN l.side = 'BID' AND l.level_index = 0 THEN 1 END) > 0
               AND COUNT(CASE WHEN l.side = 'ASK' AND l.level_index = 0 THEN 1 END) > 0
        )
        SELECT 
            s.timestamp,
            s.symbol,
            s.id as snapshot_id,
            COALESCE(p.bid_price_1, NULL) as bid_price_1,
            COALESCE(p.bid_qty_1, NULL) as bid_qty_1,
            COALESCE(p.ask_price_1, NULL) as ask_price_1,
            COALESCE(p.ask_qty_1, NULL) as ask_qty_1,
            COALESCE(p.bid_depth_5, 0) as bid_depth_5,
            COALESCE(p.ask_depth_5, 0) as ask_depth_5
        FROM filtered_snapshots s
        INNER JOIN price_levels_aggregated p ON s.id = p.snapshot_id
        ORDER BY s.timestamp
        """
        
        print(f"[DEBUG] ExchSimDataLoader.load_market_data: symbol={symbol}, start_date={start_date}, end_date={end_date}, skip_min_samples_check={skip_min_samples_check}")
        
        # 接続を取得
        conn = self._get_connection()
        try:
            # タイムゾーンをUTCに設定（timestamp without time zoneカラムとの比較を正しく行うため）
            with conn.cursor() as cur:
                cur.execute("SET timezone = 'UTC'")
                conn.commit()
            
            # まず、スナップショットの件数を確認
            # timestamp without time zoneカラムと比較するため、文字列として渡して明示的にキャスト
            check_query = """
                SELECT COUNT(*) as count
                FROM market_board_snapshots
                WHERE symbol = %s
                  AND timestamp BETWEEN %s::timestamp AND %s::timestamp
            """
            start_str = start_date_naive.strftime('%Y-%m-%d %H:%M:%S')
            end_str = end_date_naive.strftime('%Y-%m-%d %H:%M:%S')
            with conn.cursor() as cur:
                cur.execute(check_query, (symbol, start_str, end_str))
                snapshot_count = cur.fetchone()[0]
                print(f"[DEBUG] ExchSimDataLoader.load_market_data: snapshot count={snapshot_count}")
            
            # pandasの警告を避けるため、SQLAlchemyエンジンを使用
            from sqlalchemy import create_engine
            from config.settings import DatabaseConfig
            connection_string = DatabaseConfig.get_exch_sim_connection_string()
            # タイムゾーンを明示的に設定
            if '?' in connection_string:
                connection_string += "&options=-c timezone=UTC"
            else:
                connection_string += "?options=-c timezone=UTC"
            engine = create_engine(connection_string, connect_args={"options": "-c timezone=UTC"})
            try:
                df = pd.read_sql_query(
                query,
                    engine,
                params=(symbol, start_str, end_str)
            )
            finally:
                engine.dispose()  # エンジンを閉じる
        except Exception as e:
            print(f"[ERROR] ExchSimDataLoader.load_market_data: Failed to load data: {e}")
            import traceback
            traceback.print_exc()
            raise
        finally:
            # 接続を返却
            self._return_connection(conn)
        
        print(f"[DEBUG] ExchSimDataLoader.load_market_data: loaded {len(df)} samples after JOIN")
        
        # JOIN後のデータ件数チェック
        if len(df) == 0:
            # より詳細なエラーメッセージを提供
            error_msg = (
                f"No data found for symbol {symbol} between {start_date} and {end_date} (after filtering). "
                f"Snapshot count: {snapshot_count}. "
                f"This may indicate that price_levels data is missing or JOIN failed."
            )
            raise ValueError(error_msg)
        
        if not skip_min_samples_check and len(df) < self.config.MIN_SAMPLES:
            print(f"[WARN] Insufficient data: {len(df)} samples (minimum: {self.config.MIN_SAMPLES})")
            raise ValueError(
                f"Insufficient data: {len(df)} samples "
                f"(minimum: {self.config.MIN_SAMPLES})"
            )
        
        print(f"[DEBUG] ExchSimDataLoader.load_market_data: MIN_SAMPLES check passed (skip={skip_min_samples_check})")
        
        # 特徴量を計算
        df['spread'] = df['ask_price_1'] - df['bid_price_1']
        df['mid_price'] = (df['bid_price_1'] + df['ask_price_1']) / 2
        
        # クロス市場（BID >= ASK）の除外
        initial_count = len(df)
        df = df[df['bid_price_1'] < df['ask_price_1']].copy()
        crossed_count = initial_count - len(df)
        if crossed_count > 0:
            print(f"[WARN] Excluded {crossed_count} crossed market records ({crossed_count/initial_count*100:.2f}%)")
        
        # オーダーインバランス
        total_depth = df['bid_depth_5'] + df['ask_depth_5']
        df['order_imbalance'] = np.where(
            total_depth > 0,
            (df['bid_depth_5'] - df['ask_depth_5']) / total_depth,
            0
        )
        
        # データ品質スコア（簡易版）
        spread_ratio = df['spread'] / (df['mid_price'] + 1e-9)
        df['data_quality_score'] = np.where(
            (spread_ratio < 0.001) & (total_depth >= 0.01),
            100,
            np.where(
                (spread_ratio < 0.002) & (total_depth >= 0.005),
                80,
                60
            )
        )
        
        # timestampをindexに設定（TimezoneをUTCとして扱う）
        # まずpd.to_datetimeで変換してから、タイムゾーン情報を確認
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        # 既にタイムゾーン情報がある場合はtz_convertを使用、ない場合はtz_localizeを使用
        if df['timestamp'].iloc[0].tz is not None:
            df['timestamp'] = df['timestamp'].dt.tz_convert('UTC')
        else:
            df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
        df.set_index('timestamp', inplace=True)
        
        # 不要なカラムを削除
        df.drop(columns=['snapshot_id'], inplace=True, errors='ignore')
        
        return df
    
    def get_execution_count(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> int:
        """
        指定期間の約定データ件数を取得
        
        Args:
            symbol: 銘柄
            start_date: 開始日時
            end_date: 終了日時
        
        Returns:
            約定データ件数
        """
        conn = self._get_connection()
        try:
            query = """
                SELECT COUNT(*)
                FROM executions
                WHERE symbol = %s
                  AND created_at BETWEEN %s AND %s
                  AND exec_status = 'FILLED'
            """
            with conn.cursor() as cur:
                cur.execute(query, (symbol, start_date, end_date))
                result = cur.fetchone()
                return result[0] if result else 0
        finally:
            self._return_connection(conn)
    
    def load_executions(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        約定履歴をロード（exch_simデータベースのexecutionsテーブルから）
        """
        # exch_simのexecutionsテーブルの構造を確認してから適切なクエリを使用
        # まず、テーブルが存在するか、カラム名を確認
        try:
            query = """
            SELECT 
                created_at as timestamp,
                symbol,
                last_px as price,
                last_qty as quantity,
                side
            FROM executions
            WHERE symbol = %s
              AND created_at BETWEEN %s AND %s
              AND exec_status = 'FILLED'
              AND last_px > 0
              AND last_qty > 0
            ORDER BY created_at
            """
            
            # pandasの警告を避けるため、SQLAlchemyエンジンを使用
            from sqlalchemy import create_engine
            from config.settings import DatabaseConfig
            connection_string = DatabaseConfig.get_exch_sim_connection_string()
            engine = create_engine(connection_string)
            try:
                df = pd.read_sql_query(
                    query,
                    engine,
                    params=(symbol, start_date, end_date)
                )
            finally:
                engine.dispose()  # エンジンを閉じる

            print(f"[DEBUG] ExchSimDataLoader.load_executions: len={len(df)}")
            
            if len(df) > 0:
                # timestampをUTCとして扱う
                # まずpd.to_datetimeで変換してから、タイムゾーン情報を確認
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                # 既にタイムゾーン情報がある場合はtz_convertを使用、ない場合はtz_localizeを使用
                if df['timestamp'].iloc[0].tz is not None:
                    df['timestamp'] = df['timestamp'].dt.tz_convert('UTC')
                else:
                    df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
            
            return df
        except Exception as e:
            # テーブルが存在しない、またはカラム名が異なる場合は空のDataFrameを返す
            print(f"Warning: Could not load executions from exch_sim: {e}")
            return pd.DataFrame(columns=['timestamp', 'symbol', 'price', 'quantity', 'side'])
    
    def load_training_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        resample_freq: str = '1S',
        skip_min_samples_check: bool = False,
        use_batch_loading: bool = False,
        batch_size_days: int = 1
    ) -> pd.DataFrame:
        """
        訓練用データセットを生成
        板情報 + 約定情報を統合
        
        約定データは、各マーケットデータレコードのタイムスタンプから
        次のマーケットデータレコードのタイムスタンプまでの間の約定を集計する
        
        Args:
            skip_min_samples_check: Trueの場合、MIN_SAMPLESチェックをスキップ（リアルタイムシグナル生成用）
            use_batch_loading: Trueの場合、バッチ読み込みを使用（大量データの場合に推奨）
            batch_size_days: バッチ読み込み時の1バッチあたりの日数（デフォルト: 1日）
        """
        print(f"[DEBUG] ExchSimDataLoader.load_training_data: symbol={symbol}, start_date={start_date}, end_date={end_date}, skip_min_samples_check={skip_min_samples_check}, use_batch_loading={use_batch_loading}")
        
        # バッチ読み込みを使用する場合
        if use_batch_loading:
            total_days = (end_date - start_date).total_seconds() / 86400
            if total_days > batch_size_days:
                print(f"[INFO] Using batch loading: {total_days:.1f} days, batch size: {batch_size_days} days")
                
                market_dfs = []
                exec_dfs = []
                
                current_start = start_date
                batch_num = 0
                
                while current_start < end_date:
                    current_end = min(current_start + timedelta(days=batch_size_days), end_date)
                    batch_num += 1
                    
                    print(f"[INFO] Loading batch {batch_num}: {current_start} to {current_end}")
                    
                    # 板情報をバッチで読み込み
                    batch_market_df = self.load_market_data(
                        symbol,
                        current_start,
                        current_end,
                        min_levels=5,
                        skip_min_samples_check=skip_min_samples_check
                    )
                    
                    if len(batch_market_df) > 0:
                        market_dfs.append(batch_market_df)
                    
                    # 約定情報をバッチで読み込み
                    batch_exec_df = self.load_executions(symbol, current_start, current_end)
                    if len(batch_exec_df) > 0:
                        exec_dfs.append(batch_exec_df)
                    
                    current_start = current_end
                
                # バッチ結果を結合
                if market_dfs:
                    market_df = pd.concat(market_dfs, ignore_index=False).sort_index()
                    print(f"[DEBUG] ExchSimDataLoader.load_training_data: market_df loaded (batched), {len(market_df)} samples")

                    # マーケットデータの詳細をログ出力
                    market_start = market_df.index.min()
                    market_end = market_df.index.max()
                    print(f"[INFO] Market data (batched): {len(market_df)} records, from {market_start} to {market_end}")
                else:
                    raise ValueError(f"No market data found for symbol {symbol} between {start_date} and {end_date}")

                if exec_dfs:
                    exec_df = pd.concat(exec_dfs, ignore_index=True)
                    # 約定データの詳細をログ出力
                    if len(exec_df) > 0:
                        exec_start = exec_df['timestamp'].min()
                        exec_end = exec_df['timestamp'].max()
                        print(f"[INFO] Execution data (batched): {len(exec_df)} records, from {exec_start} to {exec_end}")
                else:
                    exec_df = pd.DataFrame(columns=['timestamp', 'symbol', 'price', 'quantity', 'side'])
                    print(f"[INFO] Execution data (batched): 0 records")
            else:
                # バッチサイズより小さい場合は通常の読み込み
                market_df = self.load_market_data(
                    symbol,
                    start_date,
                    end_date,
                    min_levels=5,
                    skip_min_samples_check=skip_min_samples_check
                )
                print(f"[DEBUG] ExchSimDataLoader.load_training_data: market_df loaded, {len(market_df)} samples")

                # マーケットデータの詳細をログ出力
                if len(market_df) > 0:
                    market_start = market_df.index.min()
                    market_end = market_df.index.max()
                    print(f"[INFO] Market data: {len(market_df)} records, from {market_start} to {market_end}")
                else:
                    print(f"[WARNING] Market data: 0 records")

                exec_df = self.load_executions(symbol, start_date, end_date)

                # 約定データの詳細をログ出力
                if len(exec_df) > 0:
                    exec_start = exec_df['timestamp'].min()
                    exec_end = exec_df['timestamp'].max()
                    print(f"[INFO] Execution data: {len(exec_df)} records, from {exec_start} to {exec_end}")
                else:
                    print(f"[INFO] Execution data: 0 records")
        else:
            # 通常の読み込み
            market_df = self.load_market_data(
                symbol, 
                start_date, 
                end_date, 
                min_levels=5,
                skip_min_samples_check=skip_min_samples_check
            )
            
            print(f"[DEBUG] ExchSimDataLoader.load_training_data: market_df loaded, {len(market_df)} samples")

            # マーケットデータの詳細をログ出力
            if len(market_df) > 0:
                market_start = market_df.index.min()
                market_end = market_df.index.max()
                print(f"[INFO] Market data: {len(market_df)} records, from {market_start} to {market_end}")
            else:
                print(f"[WARNING] Market data: 0 records")

            # 約定情報（出来高計算用）
            exec_df = self.load_executions(symbol, start_date, end_date)

            # 約定データの詳細をログ出力
            if len(exec_df) > 0:
                exec_start = exec_df['timestamp'].min()
                exec_end = exec_df['timestamp'].max()
                print(f"[INFO] Execution data: {len(exec_df)} records, from {exec_start} to {exec_end}")
            else:
                print(f"[INFO] Execution data: 0 records")
        
        # 結果のDataFrame（最初はmarket_dfのコピー）
        df = market_df.copy()
        
        if len(exec_df) > 0:
            # timestampをindexに設定してソート
            exec_df = exec_df.set_index('timestamp').sort_index()
            market_df = market_df.sort_index()
            
            # 各約定がどのマーケットデータ区間に属するかを判定
            # direction='backward' で、約定時刻以前の直近のマーケットデータ時刻にマッピング
            
            # マッピング用のDataFrame作成
            market_ts_df = pd.DataFrame({'market_timestamp': market_df.index}, index=market_df.index)
            
            # 約定データに直近のマーケットデータ時刻を紐付け
            exec_with_bucket = pd.merge_asof(
                exec_df,
                market_ts_df,
                left_index=True,
                right_index=True,
                direction='backward'
            )
            
            # 約定金額計算
            exec_with_bucket['amount'] = exec_with_bucket['price'] * exec_with_bucket['quantity']
            
            # 1. 出来高の集計
            volume_stats = exec_with_bucket.groupby(['market_timestamp', 'side'])['quantity'].sum().unstack(fill_value=0)
            
            # カラム名が BID/ASK/BUY/SELL などデータによって異なる可能性に注意
            if 'BUY' not in volume_stats.columns: volume_stats['BUY'] = 0.0
            if 'SELL' not in volume_stats.columns: volume_stats['SELL'] = 0.0
            
            # 2. 単純平均価格の集計
            price_mean_stats = exec_with_bucket.groupby(['market_timestamp', 'side'])['price'].mean().unstack()
            if 'BUY' not in price_mean_stats.columns: price_mean_stats['BUY'] = np.nan
            if 'SELL' not in price_mean_stats.columns: price_mean_stats['SELL'] = np.nan
            
            # 全体の平均価格
            price_mean_all = exec_with_bucket.groupby('market_timestamp')['price'].mean()
            
            # 3. 加重平均価格の集計
            # まずサイドごとの合計金額と合計数量を計算
            amount_sum = exec_with_bucket.groupby(['market_timestamp', 'side'])['amount'].sum().unstack(fill_value=0)
            if 'BUY' not in amount_sum.columns: amount_sum['BUY'] = 0.0
            if 'SELL' not in amount_sum.columns: amount_sum['SELL'] = 0.0
            
            # 加重平均 = 合計金額 / 合計数量
            vwap_buy = amount_sum['BUY'] / (volume_stats['BUY'] + 1e-9)
            vwap_sell = amount_sum['SELL'] / (volume_stats['SELL'] + 1e-9)
            
            # 集計結果をmarket_dfに結合
            # joinはindex（timestamp）基準で行われる
            
            # 出来高
            df['volume_buy'] = volume_stats['BUY']
            df['volume_sell'] = volume_stats['SELL']
            
            # NaN（約定なし）を0で埋める
            df['volume_buy'] = df['volume_buy'].fillna(0)
            df['volume_sell'] = df['volume_sell'].fillna(0)
            
            df['volume_total'] = df['volume_buy'] + df['volume_sell']
            df['volume_imbalance'] = (df['volume_buy'] - df['volume_sell']) / (df['volume_total'] + 1e-9)
            
            # 約定価格
            df['exec_price_buy'] = price_mean_stats['BUY']
            df['exec_price_sell'] = price_mean_stats['SELL']
            df['exec_price_all'] = price_mean_all
            
            df['exec_price_weighted_buy'] = vwap_buy
            df['exec_price_weighted_sell'] = vwap_sell
            
            # 約定がない期間はNaNになるので、ffillして、それでもNaNならmid_priceで埋める
            cols_to_fill = [
                'exec_price_buy', 'exec_price_sell', 'exec_price_all',
                'exec_price_weighted_buy', 'exec_price_weighted_sell'
            ]
            
            for col in cols_to_fill:
                if col in df.columns:
                    df[col] = df[col].ffill().fillna(df['mid_price'])
                else:
                    df[col] = df['mid_price']
            
        else:
            # 約定データがない場合
            df['volume_buy'] = 0.0
            df['volume_sell'] = 0.0
            df['volume_total'] = 0.0
            df['volume_imbalance'] = 0.0
            
            price_cols = [
                'exec_price_buy', 'exec_price_sell', 'exec_price_all',
                'exec_price_weighted_buy', 'exec_price_weighted_sell'
            ]
            for col in price_cols:
                df[col] = df['mid_price']
        
        return df.fillna(0)
    
    def close(self):
        """接続を閉じる（接続プールを使用する場合は何もしない）"""
        if not self.use_connection_pool and self.conn is not None:
            self.conn.close()
            self.conn = None

