"""
板データと約定データの価格乖離を確認するスクリプト
指定時点での板情報と約定情報の価格を比較
"""
import sys
import os
import pandas as pd
from datetime import datetime, timezone, timedelta
import psycopg2

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# .envファイルを読み込む
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
except ImportError:
    pass

from config.settings import DatabaseConfig

def check_price_discrepancy(symbol: str, timestamp: datetime, time_window_seconds: int = 60):
    """
    指定時点での板データと約定データの価格乖離を確認
    
    Args:
        symbol: シンボル（例: B_FX_BTCJPY）
        timestamp: 確認する時点
        time_window_seconds: 約定データを確認する時間窓（秒）
    """
    print("="*80)
    print(f"価格乖離チェック: {symbol}")
    print(f"時点: {timestamp}")
    print(f"時間窓: ±{time_window_seconds}秒")
    print("="*80)
    
    # データベース接続（環境変数から取得、または直接指定）
    # 環境変数が設定されている場合はそれを使用、なければ直接指定
    db_host = os.getenv('DB_HOST', '77.42.74.155')
    db_port = int(os.getenv('DB_PORT', '5432'))
    db_user = os.getenv('DB_USER', 'exch_sim_user')
    db_password = os.getenv('DB_PASSWORD', 'sr3110ysi')
    db_name = os.getenv('EXCH_SIM_DB_NAME', 'exch_sim')
    
    # 接続文字列から接続情報を取得（既存の設定を使用）
    try:
        connection_string = DatabaseConfig.get_exch_sim_connection_string()
        # postgresql://user:password@host:port/dbname から接続情報を抽出
        from urllib.parse import urlparse
        parsed = urlparse(connection_string)
        db_host = parsed.hostname or db_host
        db_port = parsed.port or db_port
        db_user = parsed.username or db_user
        db_password = parsed.password or db_password
        db_name = parsed.path.lstrip('/') or db_name
    except:
        pass  # 環境変数から取得できない場合は直接指定の値を使用
    
    print(f"\nデータベース接続情報:")
    print(f"  Host: {db_host}")
    print(f"  Port: {db_port}")
    print(f"  User: {db_user}")
    print(f"  Database: {db_name}")
    
    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_password,
        database=db_name
    )
    
    try:
        # 1. 指定時点の板データを取得（created_atとtimestampの両方を確認）
        print("\n[1] 板データ（market_board_snapshots + market_board_price_levels）を取得...")
        board_query = """
        WITH snapshot_at_time AS (
            SELECT 
                s.id,
                s.timestamp,
                s.created_at,
                s.symbol
            FROM market_board_snapshots s
            WHERE s.symbol = %s
              AND s.timestamp <= %s
            ORDER BY s.timestamp DESC
            LIMIT 1
        ),
        price_levels AS (
            SELECT 
                l.snapshot_id,
                MAX(CASE WHEN l.side = 'BID' AND l.level_index = 0 THEN l.price END) as bid_price_1,
                MAX(CASE WHEN l.side = 'BID' AND l.level_index = 0 THEN l.quantity END) as bid_qty_1,
                MAX(CASE WHEN l.side = 'ASK' AND l.level_index = 0 THEN l.price END) as ask_price_1,
                MAX(CASE WHEN l.side = 'ASK' AND l.level_index = 0 THEN l.quantity END) as ask_qty_1
            FROM market_board_price_levels l
            WHERE l.snapshot_id IN (SELECT id FROM snapshot_at_time)
              AND l.level_index = 0
            GROUP BY l.snapshot_id
        )
        SELECT 
            s.timestamp,
            s.created_at,
            s.symbol,
            p.bid_price_1,
            p.bid_qty_1,
            p.ask_price_1,
            p.ask_qty_1,
            (p.bid_price_1 + p.ask_price_1) / 2.0 as mid_price,
            p.ask_price_1 - p.bid_price_1 as spread
        FROM snapshot_at_time s
        LEFT JOIN price_levels p ON s.id = p.snapshot_id
        """
        
        with conn.cursor() as cur:
            cur.execute(board_query, (symbol, timestamp))
            board_result = cur.fetchone()
            
            if board_result:
                board_timestamp = board_result[0]  # UTC
                board_created_at = board_result[1]  # JST
                board_symbol = board_result[2]
                board_bid = board_result[3]
                board_bid_qty = board_result[4]
                board_ask = board_result[5]
                board_ask_qty = board_result[6]
                board_mid = board_result[7]
                board_spread = board_result[8]
                
                print(f"  板データのタイムスタンプ（UTC）: {board_timestamp}")
                print(f"  板データのcreated_at: {board_created_at}")
                if board_created_at and board_timestamp:
                    # タイムゾーン情報を統一してから計算
                    try:
                        if hasattr(board_created_at, 'tzinfo') and board_created_at.tzinfo is not None:
                            # created_atがawareな場合
                            if hasattr(board_timestamp, 'tzinfo') and board_timestamp.tzinfo is None:
                                # timestampがnaiveな場合、UTCとして扱う
                                board_timestamp_aware = board_timestamp.replace(tzinfo=timezone.utc)
                            else:
                                board_timestamp_aware = board_timestamp
                            time_diff = board_created_at - board_timestamp_aware
                        else:
                            # created_atがnaiveな場合
                            if hasattr(board_timestamp, 'tzinfo') and board_timestamp.tzinfo is not None:
                                board_created_at_aware = board_created_at.replace(tzinfo=timezone.utc)
                                time_diff = board_created_at_aware - board_timestamp
                            else:
                                time_diff = board_created_at - board_timestamp
                        print(f"  時間差（created_at - timestamp）: {time_diff}")
                        # JSTとUTCの差（9時間）と比較
                        jst_utc_diff = timedelta(hours=9)
                        if abs(time_diff - jst_utc_diff) < timedelta(minutes=1):
                            print(f"  ⚠️  created_atがJST、timestampがUTCの可能性があります（9時間の差）")
                        elif abs(time_diff) < timedelta(seconds=10):
                            print(f"  ✓ created_atとtimestampはほぼ同じ時刻です")
                    except Exception as e:
                        print(f"  時間差の計算エラー: {e}")
                print(f"  BID: {board_bid:,.0f} (数量: {board_bid_qty})")
                print(f"  ASK: {board_ask:,.0f} (数量: {board_ask_qty})")
                print(f"  MID: {board_mid:,.0f}")
                print(f"  Spread: {board_spread:,.0f}")
            else:
                print("  板データが見つかりませんでした")
                return
        
        # 2. 指定時点前後の約定データを取得（UTCとJSTの両方で確認）
        print(f"\n[2] 約定データ（executions）を取得...")
        print(f"  検索範囲（UTC）: {timestamp - timedelta(seconds=time_window_seconds)} ～ {timestamp + timedelta(seconds=time_window_seconds)}")
        exec_start = timestamp - timedelta(seconds=time_window_seconds)
        exec_end = timestamp + timedelta(seconds=time_window_seconds)
        
        # 約定データのcreated_atがJSTの場合、UTCに変換して検索
        # JST = UTC + 9時間
        exec_query_utc = """
        SELECT 
            created_at,
            created_at AT TIME ZONE 'Asia/Tokyo' as created_at_jst,
            symbol,
            last_px as price,
            last_qty as quantity,
            side,
            exec_status
        FROM executions
        WHERE symbol = %s
          AND created_at BETWEEN %s AND %s
          AND exec_status = 'FILLED'
          AND last_px > 0
          AND last_qty > 0
        ORDER BY created_at
        """
        
        # 約定データのcreated_atがJSTとして保存されている場合の検索
        exec_query_jst = """
        SELECT 
            created_at,
            created_at AT TIME ZONE 'Asia/Tokyo' as created_at_jst,
            symbol,
            last_px as price,
            last_qty as quantity,
            side,
            exec_status
        FROM executions
        WHERE symbol = %s
          AND created_at AT TIME ZONE 'Asia/Tokyo' BETWEEN %s AND %s
          AND exec_status = 'FILLED'
          AND last_px > 0
          AND last_qty > 0
        ORDER BY created_at
        """
        
        # まずUTCで検索
        exec_df = pd.read_sql_query(exec_query_utc, conn, params=(symbol, exec_start, exec_end))
        
        if len(exec_df) == 0:
            # UTCで見つからない場合、JSTとして検索
            print("  UTCで約定データが見つかりませんでした。JSTとして検索します...")
            exec_start_jst = exec_start + timedelta(hours=9)
            exec_end_jst = exec_end + timedelta(hours=9)
            exec_df = pd.read_sql_query(exec_query_jst, conn, params=(symbol, exec_start_jst, exec_end_jst))
        
        if len(exec_df) > 0:
            print(f"  約定データ件数: {len(exec_df)}")
            if 'created_at_jst' in exec_df.columns:
                print(f"  約定データのcreated_at範囲（UTC）: {exec_df['created_at'].min()} ～ {exec_df['created_at'].max()}")
                print(f"  約定データのcreated_at範囲（JST）: {exec_df['created_at_jst'].min()} ～ {exec_df['created_at_jst'].max()}")
            else:
                print(f"  約定データのcreated_at範囲: {exec_df['created_at'].min()} ～ {exec_df['created_at'].max()}")
            print(f"  約定価格範囲: min={exec_df['price'].min():,.0f}, max={exec_df['price'].max():,.0f}, mean={exec_df['price'].mean():,.0f}")
            print(f"  約定価格のユニーク値数: {exec_df['price'].nunique()}")
            
            # 板データの価格範囲との比較
            print(f"\n[3] 価格乖離の分析:")
            print(f"  板データのBID/ASK範囲: {board_bid:,.0f} ～ {board_ask:,.0f}")
            print(f"  約定データの価格範囲: {exec_df['price'].min():,.0f} ～ {exec_df['price'].max():,.0f}")
            
            # 約定価格が板データの範囲外にあるか確認
            outside_bid_ask = exec_df[
                (exec_df['price'] < board_bid) | (exec_df['price'] > board_ask)
            ]
            
            if len(outside_bid_ask) > 0:
                print(f"\n  ⚠️  警告: {len(outside_bid_ask)}件の約定が板データのBID/ASK範囲外です")
                print(f"  範囲外の約定データ（最初の10件）:")
                for idx, row in outside_bid_ask.head(10).iterrows():
                    timestamp_col = 'created_at' if 'created_at' in row else 'timestamp'
                    print(f"    {row[timestamp_col]}: price={row['price']:,.0f}, side={row['side']}, qty={row['quantity']}")
            else:
                print(f"  ✓ すべての約定価格が板データのBID/ASK範囲内です")
            
            # 約定価格と板データのMID価格の差
            price_diff_from_mid = exec_df['price'] - board_mid
            print(f"\n  約定価格とMID価格の差:")
            print(f"    min: {price_diff_from_mid.min():,.0f} JPY")
            print(f"    max: {price_diff_from_mid.max():,.0f} JPY")
            print(f"    mean: {price_diff_from_mid.mean():,.0f} JPY")
            print(f"    std: {price_diff_from_mid.std():,.0f} JPY")
            
            # 約定データの詳細（時系列順）
            print(f"\n[4] 約定データの詳細（時系列順）:")
            if 'created_at_jst' in exec_df.columns:
                print(f"{'Created_at (UTC)':<30} {'Created_at (JST)':<30} {'Price':<15} {'Quantity':<12} {'Side':<8} {'Diff from MID':<15}")
                print("-"*120)
                for idx, row in exec_df.head(20).iterrows():
                    diff = row['price'] - board_mid
                    print(f"{str(row['created_at']):<30} {str(row['created_at_jst']):<30} {row['price']:>14,.0f} {row['quantity']:>11.6f} {row['side']:<8} {diff:>14,.0f}")
            else:
                print(f"{'Created_at':<30} {'Price':<15} {'Quantity':<12} {'Side':<8} {'Diff from MID':<15}")
                print("-"*90)
                for idx, row in exec_df.head(20).iterrows():
                    diff = row['price'] - board_mid
                    print(f"{str(row['created_at']):<30} {row['price']:>14,.0f} {row['quantity']:>11.6f} {row['side']:<8} {diff:>14,.0f}")
            
            if len(exec_df) > 20:
                print(f"  ... (他 {len(exec_df) - 20} 件)")
        else:
            print("  約定データが見つかりませんでした")
        
        # 3. 指定時点前後の板データの変化を確認（created_atとtimestampの両方を確認）
        print(f"\n[5] 指定時点前後の板データの変化を確認...")
        board_history_query = """
        WITH snapshots AS (
            SELECT 
                s.id,
                s.timestamp,
                s.created_at,
                s.symbol
            FROM market_board_snapshots s
            WHERE s.symbol = %s
              AND s.timestamp BETWEEN %s AND %s
            ORDER BY s.timestamp
        ),
        price_levels AS (
            SELECT 
                l.snapshot_id,
                MAX(CASE WHEN l.side = 'BID' AND l.level_index = 0 THEN l.price END) as bid_price_1,
                MAX(CASE WHEN l.side = 'ASK' AND l.level_index = 0 THEN l.price END) as ask_price_1
            FROM market_board_price_levels l
            WHERE l.snapshot_id IN (SELECT id FROM snapshots)
              AND l.level_index = 0
            GROUP BY l.snapshot_id
        )
        SELECT 
            s.timestamp,
            s.created_at,
            p.bid_price_1,
            p.ask_price_1,
            (p.bid_price_1 + p.ask_price_1) / 2.0 as mid_price
        FROM snapshots s
        LEFT JOIN price_levels p ON s.id = p.snapshot_id
        ORDER BY s.timestamp
        """
        
        board_history_df = pd.read_sql_query(
            board_history_query, 
            conn, 
            params=(symbol, exec_start, exec_end)
        )
        
        if len(board_history_df) > 0:
            print(f"  板データの件数: {len(board_history_df)}")
            if 'created_at' in board_history_df.columns:
                print(f"  板データのタイムスタンプ範囲（UTC）: {board_history_df['timestamp'].min()} ～ {board_history_df['timestamp'].max()}")
                print(f"  板データのcreated_at範囲（JST）: {board_history_df['created_at'].min()} ～ {board_history_df['created_at'].max()}")
            print(f"  板データの価格範囲:")
            print(f"    BID: min={board_history_df['bid_price_1'].min():,.0f}, max={board_history_df['bid_price_1'].max():,.0f}")
            print(f"    ASK: min={board_history_df['ask_price_1'].min():,.0f}, max={board_history_df['ask_price_1'].max():,.0f}")
            print(f"    MID: min={board_history_df['mid_price'].min():,.0f}, max={board_history_df['mid_price'].max():,.0f}")
            
            # 板データの価格変動
            if len(board_history_df) > 1:
                bid_changes = board_history_df['bid_price_1'].diff().dropna()
                ask_changes = board_history_df['ask_price_1'].diff().dropna()
                mid_changes = board_history_df['mid_price'].diff().dropna()
                
                print(f"\n  板データの価格変動:")
                print(f"    BID変動: min={bid_changes.min():,.0f}, max={bid_changes.max():,.0f}")
                print(f"    ASK変動: min={ask_changes.min():,.0f}, max={ask_changes.max():,.0f}")
                print(f"    MID変動: min={mid_changes.min():,.0f}, max={mid_changes.max():,.0f}")
        else:
            print("  板データが見つかりませんでした")
        
    finally:
        conn.close()


if __name__ == "__main__":
    # バックテスト結果から確認する時点を指定
    symbol = "B_FX_BTCJPY"
    
    # 12:00:14のSHORTと12:01:14のCOVER_SHORTを確認
    timestamps = [
        datetime(2026, 1, 15, 12, 0, 14, tzinfo=timezone.utc),
        datetime(2026, 1, 15, 12, 1, 14, tzinfo=timezone.utc)
    ]
    
    for ts in timestamps:
        check_price_discrepancy(symbol, ts, time_window_seconds=60)
        print("\n" + "="*80 + "\n")
