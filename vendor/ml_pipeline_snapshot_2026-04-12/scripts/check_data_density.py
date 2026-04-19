"""
データ密度を確認するスクリプト
指定期間のデータの密度（時間ごとの件数、欠損など）を調査
"""
import sys
import os
from datetime import datetime, timedelta
import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DatabaseConfig


def check_data_density(
    symbol: str = "G_FX_BTCJPY",
    start_time: datetime = None,
    end_time: datetime = None,
    timezone: str = "Asia/Tokyo"
):
    """
    データ密度を確認
    
    Args:
        symbol: シンボル
        start_time: 開始時刻（JST）
        end_time: 終了時刻（JST）
        timezone: タイムゾーン（デフォルト: Asia/Tokyo）
    """
    # デフォルト値の設定（今日の10時から16時）
    if start_time is None:
        today = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        start_time = today
    if end_time is None:
        today = datetime.now().replace(hour=16, minute=0, second=0, microsecond=0)
        end_time = today
    
    print("="*70)
    print("Data Density Check")
    print("="*70)
    print(f"Symbol: {symbol}")
    print(f"Period: {start_time} to {end_time} ({timezone})")
    print(f"="*70 + "\n")
    
    # データベース接続
    try:
        conn = psycopg2.connect(DatabaseConfig.get_exch_sim_connection_string())
        print(f"✓ Connected to database: {DatabaseConfig.EXCH_SIM_DB_NAME}")
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        return
    
    try:
        # UTCに変換（データベースはUTCで保存されているため）
        # JSTからUTCへの変換: UTC = JST - 9時間
        # 入力された時間がnaive datetimeの場合、JSTとして扱う
        if timezone == "Asia/Tokyo":
            # naive datetimeをJSTとして扱い、UTCに変換
            if start_time.tzinfo is None:
                # naive datetimeをJSTとして扱う（UTC-9時間）
                start_time_utc = start_time - timedelta(hours=9)
                end_time_utc = end_time - timedelta(hours=9)
            else:
                # 既にタイムゾーン情報がある場合はUTCに変換
                start_time_utc = start_time.astimezone(pd.Timestamp.now(tz='UTC').tz).replace(tzinfo=None)
                end_time_utc = end_time.astimezone(pd.Timestamp.now(tz='UTC').tz).replace(tzinfo=None)
        else:
            start_time_utc = start_time
            end_time_utc = end_time
        
        print(f"Input period ({timezone}): {start_time} to {end_time}")
        print(f"Query period (UTC): {start_time_utc} to {end_time_utc}\n")
        
        # 1. 板データ（market_board_snapshots）の密度確認
        print("="*70)
        print("Market Board Snapshots Density")
        print("="*70)
        
        query_snapshots = """
        SELECT 
            timestamp,
            symbol
        FROM market_board_snapshots
        WHERE symbol = %s
          AND timestamp >= %s
          AND timestamp <= %s
        ORDER BY timestamp
        """
        
        df_snapshots = pd.read_sql_query(
            query_snapshots,
            conn,
            params=(symbol, start_time_utc, end_time_utc)
        )
        
        if len(df_snapshots) == 0:
            print("No data found for the specified period.")
            return
        
        df_snapshots['timestamp'] = pd.to_datetime(df_snapshots['timestamp'], utc=True)
        df_snapshots.set_index('timestamp', inplace=True)
        
        print(f"Total records: {len(df_snapshots):,}")
        print(f"First record: {df_snapshots.index[0]}")
        print(f"Last record: {df_snapshots.index[-1]}")
        print(f"Duration: {df_snapshots.index[-1] - df_snapshots.index[0]}")
        
        # 時間ごとのデータ件数
        df_snapshots['hour'] = df_snapshots.index.hour
        df_snapshots['minute'] = df_snapshots.index.minute
        
        # 1時間ごとの件数
        hourly_counts = df_snapshots.groupby(df_snapshots.index.floor('H')).size()
        print(f"\nHourly counts:")
        print(f"{'Hour (UTC)':<20} {'Hour (JST)':<20} {'Count':<10} {'Expected':<10} {'Coverage':<10}")
        print("-"*80)
        
        expected_per_hour = 3600  # 1秒間隔なら3600件/時間
        for hour_utc, count in hourly_counts.items():
            # UTC時刻をJSTに変換（UTC + 9時間）
            hour_jst = hour_utc + timedelta(hours=9)
            coverage = (count / expected_per_hour * 100) if expected_per_hour > 0 else 0
            print(f"{hour_utc.strftime('%Y-%m-%d %H:%M'):<20} {hour_jst.strftime('%Y-%m-%d %H:%M'):<20} {count:<10} {expected_per_hour:<10} {coverage:>8.1f}%")
        
        # 1分ごとの件数（最初の1時間のみ）
        print(f"\nMinute-by-minute counts (first hour):")
        first_hour = df_snapshots[df_snapshots.index < df_snapshots.index[0] + timedelta(hours=1)]
        minute_counts = first_hour.groupby(first_hour.index.floor('T')).size()
        print(f"{'Minute (UTC)':<20} {'Count':<10} {'Expected':<10} {'Status':<10}")
        print("-"*50)
        expected_per_minute = 60  # 1秒間隔なら60件/分
        for minute, count in minute_counts.head(10).items():
            status = "✓" if count >= expected_per_minute * 0.9 else "✗"
            print(f"{minute.strftime('%Y-%m-%d %H:%M'):<20} {count:<10} {expected_per_minute:<10} {status:<10}")
        
        # データ間隔の統計
        time_diffs = df_snapshots.index.to_series().diff().dropna()
        time_diffs_seconds = time_diffs.dt.total_seconds()
        
        print(f"\nData interval statistics:")
        print(f"  Mean interval: {time_diffs_seconds.mean():.2f} seconds")
        print(f"  Median interval: {time_diffs_seconds.median():.2f} seconds")
        print(f"  Min interval: {time_diffs_seconds.min():.2f} seconds")
        print(f"  Max interval: {time_diffs_seconds.max():.2f} seconds")
        print(f"  Std deviation: {time_diffs_seconds.std():.2f} seconds")
        
        # 欠損時間帯の検出（1分以上データがない場合）
        gaps = time_diffs[time_diffs > timedelta(minutes=1)]
        if len(gaps) > 0:
            print(f"\nData gaps (>1 minute): {len(gaps)}")
            print(f"{'Gap Start (UTC)':<25} {'Gap Duration':<15}")
            print("-"*40)
            for i, (gap_start, gap_duration) in enumerate(gaps.head(10).items()):
                gap_duration_seconds = gap_duration.total_seconds()
                print(f"{gap_start.strftime('%Y-%m-%d %H:%M:%S'):<25} {gap_duration_seconds:>13.0f} seconds")
            if len(gaps) > 10:
                print(f"... and {len(gaps) - 10} more gaps")
        else:
            print(f"\n✓ No significant data gaps found")
        
        # 2. 約定データ（executions）の密度確認
        print("\n" + "="*70)
        print("Executions Density")
        print("="*70)
        
        query_executions = """
        SELECT 
            created_at as timestamp,
            symbol
        FROM executions
        WHERE symbol = %s
          AND created_at >= %s
          AND created_at <= %s
          AND exec_status = 'FILLED'
        ORDER BY created_at
        """
        
        df_executions = pd.read_sql_query(
            query_executions,
            conn,
            params=(symbol, start_time_utc, end_time_utc)
        )
        
        if len(df_executions) > 0:
            df_executions['timestamp'] = pd.to_datetime(df_executions['timestamp'], utc=True)
            df_executions.set_index('timestamp', inplace=True)
            
            print(f"Total executions: {len(df_executions):,}")
            print(f"First execution: {df_executions.index[0]}")
            print(f"Last execution: {df_executions.index[-1]}")
            
            # 時間ごとの約定件数
            hourly_executions = df_executions.groupby(df_executions.index.floor('H')).size()
            print(f"\nHourly execution counts:")
            print(f"{'Hour (UTC)':<20} {'Hour (JST)':<20} {'Count':<10}")
            print("-"*50)
            for hour_utc, count in hourly_executions.items():
                # UTC時刻をJSTに変換（UTC + 9時間）
                hour_jst = hour_utc + timedelta(hours=9)
                print(f"{hour_utc.strftime('%Y-%m-%d %H:%M'):<20} {hour_jst.strftime('%Y-%m-%d %H:%M'):<20} {count:<10}")
        else:
            print("No executions found for the specified period.")
        
        # 3. データ品質のサマリー
        print("\n" + "="*70)
        print("Data Quality Summary")
        print("="*70)
        
        total_seconds = (end_time_utc - start_time_utc).total_seconds()
        expected_records = int(total_seconds)  # 1秒間隔の場合
        actual_records = len(df_snapshots)
        coverage_rate = (actual_records / expected_records * 100) if expected_records > 0 else 0
        
        print(f"Expected records (1 sec interval): {expected_records:,}")
        print(f"Actual records: {actual_records:,}")
        print(f"Coverage rate: {coverage_rate:.2f}%")
        print(f"Missing records: {expected_records - actual_records:,}")
        
        if coverage_rate >= 95:
            print("✓ Excellent data coverage")
        elif coverage_rate >= 80:
            print("⚠ Good data coverage")
        elif coverage_rate >= 50:
            print("⚠ Moderate data coverage")
        else:
            print("✗ Poor data coverage")
        
        print("="*70)
        
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Check data density in exch_sim database')
    parser.add_argument('--symbol', type=str, default='G_FX_BTCJPY', help='Symbol to check')
    parser.add_argument('--start-time', type=str, help='Start time (YYYY-MM-DD HH:MM:SS) in JST')
    parser.add_argument('--end-time', type=str, help='End time (YYYY-MM-DD HH:MM:SS) in JST')
    parser.add_argument('--hours', type=int, help='Number of hours from now (default: check today 10:00-16:00)')
    
    args = parser.parse_args()
    
    if args.start_time and args.end_time:
        start_time = datetime.strptime(args.start_time, '%Y-%m-%d %H:%M:%S')
        end_time = datetime.strptime(args.end_time, '%Y-%m-%d %H:%M:%S')
    elif args.hours:
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=args.hours)
    else:
        # デフォルト: 今日の10時から16時
        today = datetime.now().date()
        start_time = datetime.combine(today, datetime.min.time().replace(hour=10))
        end_time = datetime.combine(today, datetime.min.time().replace(hour=16))
    
    check_data_density(
        symbol=args.symbol,
        start_time=start_time,
        end_time=end_time
    )

