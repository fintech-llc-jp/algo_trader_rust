#!/usr/bin/env python3
"""
データベースクエリのテストプログラム
実際のSQLを実行して結果を確認
"""
import sys
import os
import json
from datetime import datetime, timezone
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import DatabaseConfig
import psycopg2
from data.db_pool import DatabaseConnectionPool

# ログファイルパス
LOG_PATH = "/Users/sakamoto.yukio/workspace/algo_trader_v1/.cursor/debug.log"

def log_debug(session_id, run_id, hypothesis_id, location, message, data):
    """デバッグログを書き込む"""
    log_entry = {
        "sessionId": session_id,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(datetime.now().timestamp() * 1000)
    }
    try:
        with open(LOG_PATH, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    except Exception as e:
        print(f"Failed to write log: {e}")

def test_direct_connection():
    """直接接続でテスト"""
    print("="*70)
    print("TEST 1: 直接接続（psycopg2.connect）")
    print("="*70)
    
    session_id = "test-db-query"
    run_id = "direct-connection"
    
    symbol = 'G_FX_BTCJPY'
    # 実際のデータが存在する期間を使用（2025年12月）
    start_date = datetime(2025, 12, 14, 0, 0, 0)
    end_date = datetime(2025, 12, 15, 0, 0, 0)
    
    log_debug(session_id, run_id, "A", "test_db_query.py:test_direct_connection", 
              "Test parameters", {
                  "symbol": symbol,
                  "start_date": str(start_date),
                  "end_date": str(end_date),
                  "start_date_tzinfo": str(start_date.tzinfo),
                  "end_date_tzinfo": str(end_date.tzinfo)
              })
    
    try:
        conn = psycopg2.connect(DatabaseConfig.get_exch_sim_connection_string())
        log_debug(session_id, run_id, "A", "test_db_query.py:test_direct_connection", 
                  "Connection established", {"connection_string": "connected"})
        
        cur = conn.cursor()
        
        # タイムゾーンを確認・設定
        cur.execute("SHOW timezone")
        timezone_before = cur.fetchone()[0]
        log_debug(session_id, run_id, "A", "test_db_query.py:test_direct_connection", 
                  "Timezone before SET", {"timezone": timezone_before})
        
        cur.execute("SET timezone = 'UTC'")
        conn.commit()
        
        cur.execute("SHOW timezone")
        timezone_after = cur.fetchone()[0]
        log_debug(session_id, run_id, "A", "test_db_query.py:test_direct_connection", 
                  "Timezone after SET", {"timezone": timezone_after})
        
        # テスト1: datetimeオブジェクトを直接渡す
        print(f"\n1. datetimeオブジェクトを直接渡す:")
        print(f"   start_date: {start_date} (tzinfo: {start_date.tzinfo})")
        print(f"   end_date: {end_date} (tzinfo: {end_date.tzinfo})")
        
        query1 = """
            SELECT COUNT(*) as count
            FROM market_board_snapshots
            WHERE symbol = %s
              AND timestamp BETWEEN %s AND %s
        """
        cur.execute(query1, (symbol, start_date, end_date))
        result1 = cur.fetchone()[0]
        print(f"   結果: {result1}件")
        log_debug(session_id, run_id, "A", "test_db_query.py:test_direct_connection", 
                  "Query result with datetime objects", {
                      "query": query1,
                      "result": result1,
                      "params": [symbol, str(start_date), str(end_date)]
                  })
        
        # テスト2: 文字列として渡してキャスト
        start_str = start_date.strftime('%Y-%m-%d %H:%M:%S')
        end_str = end_date.strftime('%Y-%m-%d %H:%M:%S')
        print(f"\n2. 文字列として渡してキャスト:")
        print(f"   start_str: {start_str}")
        print(f"   end_str: {end_str}")
        
        query2 = """
            SELECT COUNT(*) as count
            FROM market_board_snapshots
            WHERE symbol = %s
              AND timestamp BETWEEN %s::timestamp AND %s::timestamp
        """
        cur.execute(query2, (symbol, start_str, end_str))
        result2 = cur.fetchone()[0]
        print(f"   結果: {result2}件")
        log_debug(session_id, run_id, "B", "test_db_query.py:test_direct_connection", 
                  "Query result with string cast", {
                      "query": query2,
                      "result": result2,
                      "params": [symbol, start_str, end_str]
                  })
        
        # テスト2b: 文字列を直接SQLに埋め込む（パラメータ化しない）
        print(f"\n2b. 文字列を直接SQLに埋め込む（パラメータ化しない）:")
        query2b = f"""
            SELECT COUNT(*) as count
            FROM market_board_snapshots
            WHERE symbol = '{symbol}'
              AND timestamp BETWEEN '{start_str}'::timestamp AND '{end_str}'::timestamp
        """
        cur.execute(query2b)
        result2b = cur.fetchone()[0]
        print(f"   結果: {result2b}件")
        log_debug(session_id, run_id, "B2", "test_db_query.py:test_direct_connection", 
                  "Query result with string interpolation", {
                      "query": query2b,
                      "result": result2b
                  })
        
        # テスト3: 実際のデータ範囲を確認
        print(f"\n3. 実際のデータ範囲を確認:")
        query3 = """
            SELECT MIN(timestamp) as min_ts, MAX(timestamp) as max_ts, COUNT(*) as count
            FROM market_board_snapshots
            WHERE symbol = %s
              AND timestamp >= '2025-12-14'::date
              AND timestamp < '2025-12-15'::date
        """
        cur.execute(query3, (symbol,))
        result3 = cur.fetchone()
        print(f"   min_ts: {result3[0]}")
        print(f"   max_ts: {result3[1]}")
        print(f"   count: {result3[2]}件")
        log_debug(session_id, run_id, "C", "test_db_query.py:test_direct_connection", 
                  "Actual data range", {
                      "query": query3,
                      "min_ts": str(result3[0]),
                      "max_ts": str(result3[1]),
                      "count": result3[2]
                  })
        
        # テスト4: 実際のSQLを出力して確認
        print(f"\n4. 実際に実行されるSQLを確認:")
        cur.execute("""
            EXPLAIN (FORMAT JSON)
            SELECT COUNT(*) as count
            FROM market_board_snapshots
            WHERE symbol = %s
              AND timestamp BETWEEN %s::timestamp AND %s::timestamp
        """, (symbol, start_str, end_str))
        explain_result = cur.fetchone()[0]
        print(f"   EXPLAIN結果: {json.dumps(explain_result, indent=2, default=str)}")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        log_debug(session_id, run_id, "ERROR", "test_db_query.py:test_direct_connection", 
                  "Exception occurred", {"error": str(e), "traceback": traceback.format_exc()})

def test_connection_pool():
    """接続プールでテスト"""
    print("\n" + "="*70)
    print("TEST 2: 接続プール経由")
    print("="*70)
    
    session_id = "test-db-query"
    run_id = "connection-pool"
    
    symbol = 'G_FX_BTCJPY'
    # 実際のデータが存在する期間を使用（2025年12月）
    start_date = datetime(2025, 12, 14, 0, 0, 0)
    end_date = datetime(2025, 12, 15, 0, 0, 0)
    start_str = start_date.strftime('%Y-%m-%d %H:%M:%S')
    end_str = end_date.strftime('%Y-%m-%d %H:%M:%S')
    
    log_debug(session_id, run_id, "D", "test_db_query.py:test_connection_pool", 
              "Test parameters", {
                  "symbol": symbol,
                  "start_str": start_str,
                  "end_str": end_str
              })
    
    try:
        conn = DatabaseConnectionPool.get_connection(use_exch_sim_db=True)
        log_debug(session_id, run_id, "D", "test_db_query.py:test_connection_pool", 
                  "Connection from pool", {"connection": "obtained"})
        
        cur = conn.cursor()
        
        # タイムゾーンを確認・設定
        cur.execute("SHOW timezone")
        timezone_before = cur.fetchone()[0]
        log_debug(session_id, run_id, "D", "test_db_query.py:test_connection_pool", 
                  "Timezone before SET", {"timezone": timezone_before})
        
        cur.execute("SET timezone = 'UTC'")
        conn.commit()
        
        cur.execute("SHOW timezone")
        timezone_after = cur.fetchone()[0]
        log_debug(session_id, run_id, "D", "test_db_query.py:test_connection_pool", 
                  "Timezone after SET", {"timezone": timezone_after})
        
        # クエリを実行
        query = """
            SELECT COUNT(*) as count
            FROM market_board_snapshots
            WHERE symbol = %s
              AND timestamp BETWEEN %s::timestamp AND %s::timestamp
        """
        print(f"\nクエリ: {query}")
        print(f"パラメータ: symbol={symbol}, start={start_str}, end={end_str}")
        
        cur.execute(query, (symbol, start_str, end_str))
        result = cur.fetchone()[0]
        print(f"結果: {result}件")
        log_debug(session_id, run_id, "D", "test_db_query.py:test_connection_pool", 
                  "Query result", {
                      "query": query,
                      "result": result,
                      "params": [symbol, start_str, end_str],
                      "timezone_before": timezone_before,
                      "timezone_after": timezone_after
                  })
        
        cur.close()
        DatabaseConnectionPool.put_connection(conn, use_exch_sim_db=True)
        
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        log_debug(session_id, run_id, "ERROR", "test_db_query.py:test_connection_pool", 
                  "Exception occurred", {"error": str(e), "traceback": traceback.format_exc()})

def test_full_query():
    """完全なクエリ（JOIN含む）をテスト"""
    print("\n" + "="*70)
    print("TEST 3: 完全なクエリ（JOIN含む）")
    print("="*70)
    
    session_id = "test-db-query"
    run_id = "full-query"
    
    symbol = 'G_FX_BTCJPY'
    # 実際のデータが存在する期間を使用（2025年12月）
    start_str = '2025-12-14 00:00:00'
    end_str = '2025-12-15 00:00:00'
    
    query = """
    WITH filtered_snapshots AS (
        SELECT 
            s.id,
            s.timestamp,
            s.symbol
        FROM market_board_snapshots s
        WHERE s.symbol = %s
          AND s.timestamp BETWEEN %s::timestamp AND %s::timestamp
    ),
    price_levels_aggregated AS (
        SELECT 
            l.snapshot_id,
            MAX(CASE WHEN l.side = 'BID' AND l.level_index = 0 THEN l.price END) as bid_price_1,
            MAX(CASE WHEN l.side = 'BID' AND l.level_index = 0 THEN l.quantity END) as bid_qty_1,
            MAX(CASE WHEN l.side = 'ASK' AND l.level_index = 0 THEN l.price END) as ask_price_1,
            MAX(CASE WHEN l.side = 'ASK' AND l.level_index = 0 THEN l.quantity END) as ask_qty_1,
            COALESCE(SUM(CASE WHEN l.side = 'BID' AND l.level_index < 5 THEN l.quantity END), 0) as bid_depth_5,
            COALESCE(SUM(CASE WHEN l.side = 'ASK' AND l.level_index < 5 THEN l.quantity END), 0) as ask_depth_5
        FROM market_board_price_levels l
        WHERE l.snapshot_id IN (SELECT id FROM filtered_snapshots)
          AND l.level_index < 5
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
    LIMIT 5
    """
    
    log_debug(session_id, run_id, "E", "test_db_query.py:test_full_query", 
              "Full query test", {
                  "query": query,
                  "params": [symbol, start_str, end_str]
              })
    
    try:
        conn = DatabaseConnectionPool.get_connection(use_exch_sim_db=True)
        cur = conn.cursor()
        
        cur.execute("SET timezone = 'UTC'")
        conn.commit()
        
        print(f"\nクエリを実行中...")
        print(f"パラメータ: symbol={symbol}, start={start_str}, end={end_str}")
        
        cur.execute(query, (symbol, start_str, end_str))
        results = cur.fetchall()
        
        print(f"\n結果: {len(results)}件（最初の5件を表示）")
        for row in results:
            print(f"  {row}")
        
        log_debug(session_id, run_id, "E", "test_db_query.py:test_full_query", 
                  "Full query result", {
                      "row_count": len(results),
                      "first_row": str(results[0]) if results else None
                  })
        
        cur.close()
        DatabaseConnectionPool.put_connection(conn, use_exch_sim_db=True)
        
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        log_debug(session_id, run_id, "ERROR", "test_db_query.py:test_full_query", 
                  "Exception occurred", {"error": str(e), "traceback": traceback.format_exc()})

if __name__ == '__main__':
    # ログファイルをクリア
    if os.path.exists(LOG_PATH):
        os.remove(LOG_PATH)
    
    print("データベースクエリのテストを開始します...")
    print(f"ログファイル: {LOG_PATH}\n")
    
    test_direct_connection()
    test_connection_pool()
    test_full_query()
    
    print("\n" + "="*70)
    print("テスト完了")
    print("="*70)
