#!/usr/bin/env python3
"""
クエリパフォーマンス測定スクリプト
バックテスト用のデータ読み込みクエリのパフォーマンスを測定します
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import psycopg2
import pandas as pd
from datetime import datetime, timedelta, timezone
from config.settings import DatabaseConfig


def explain_analyze_query(query, params, conn):
    """EXPLAIN ANALYZE を実行してクエリプランを取得"""
    cur = conn.cursor()
    
    explain_query = f"EXPLAIN (ANALYZE, BUFFERS, VERBOSE) {query}"
    cur.execute(explain_query, params)
    
    plan = cur.fetchall()
    cur.close()
    
    return '\n'.join([row[0] for row in plan])


def benchmark_query(query, params, conn, iterations=3):
    """クエリの実行時間を測定"""
    times = []
    
    for i in range(iterations):
        start_time = time.time()
        
        df = pd.read_sql_query(query, conn, params=params)
        
        end_time = time.time()
        elapsed = end_time - start_time
        times.append(elapsed)
        
        print(f"  実行 {i+1}: {elapsed:.3f}秒 (行数: {len(df):,})")
    
    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)
    
    return {
        'avg': avg_time,
        'min': min_time,
        'max': max_time,
        'times': times,
        'row_count': len(df) if 'df' in locals() else 0
    }


def main():
    """メイン処理"""
    
    print("=" * 80)
    print("クエリパフォーマンス測定")
    print("=" * 80)
    print(f"データベース: {DatabaseConfig.EXCH_SIM_DB_NAME}")
    print(f"ホスト: {DatabaseConfig.HOST}:{DatabaseConfig.PORT}")
    print()
    
    # テストパラメータ
    symbol = 'G_FX_BTCJPY'
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=1)
    
    print(f"テストパラメータ:")
    print(f"  シンボル: {symbol}")
    print(f"  開始日時: {start_date}")
    print(f"  終了日時: {end_date}")
    print()
    
    try:
        conn = psycopg2.connect(DatabaseConfig.get_exch_sim_connection_string())
        
        # 1. 元のクエリ（最適化前）
        print("【1. 元のクエリ（最適化前）】")
        print("-" * 80)
        
        original_query = """
        SELECT 
            s.timestamp,
            s.symbol,
            s.id as snapshot_id,
            MAX(CASE WHEN l.side = 'BID' AND l.level_index = 0 THEN l.price END) as bid_price_1,
            MAX(CASE WHEN l.side = 'BID' AND l.level_index = 0 THEN l.quantity END) as bid_qty_1,
            MAX(CASE WHEN l.side = 'ASK' AND l.level_index = 0 THEN l.price END) as ask_price_1,
            MAX(CASE WHEN l.side = 'ASK' AND l.level_index = 0 THEN l.quantity END) as ask_qty_1,
            COALESCE(SUM(CASE WHEN l.side = 'BID' AND l.level_index < 5 THEN l.quantity END), 0) as bid_depth_5,
            COALESCE(SUM(CASE WHEN l.side = 'ASK' AND l.level_index < 5 THEN l.quantity END), 0) as ask_depth_5
        FROM market_board_snapshots s
        LEFT JOIN market_board_price_levels l ON s.id = l.snapshot_id
        WHERE s.symbol = %s
          AND s.timestamp BETWEEN %s AND %s
        GROUP BY s.id, s.timestamp, s.symbol
        HAVING COUNT(CASE WHEN l.side = 'BID' AND l.level_index = 0 THEN 1 END) > 0
           AND COUNT(CASE WHEN l.side = 'ASK' AND l.level_index = 0 THEN 1 END) > 0
        ORDER BY s.timestamp
        """
        
        print("実行計画:")
        plan = explain_analyze_query(original_query, (symbol, start_date, end_date), conn)
        print(plan)
        print()
        
        print("実行時間測定（3回実行）:")
        original_result = benchmark_query(original_query, (symbol, start_date, end_date), conn)
        print(f"  平均: {original_result['avg']:.3f}秒")
        print(f"  最小: {original_result['min']:.3f}秒")
        print(f"  最大: {original_result['max']:.3f}秒")
        print()
        
        # 2. 最適化されたクエリ
        print("【2. 最適化されたクエリ】")
        print("-" * 80)
        
        optimized_query = """
        WITH filtered_snapshots AS (
            SELECT 
                s.id,
                s.timestamp,
                s.symbol
            FROM market_board_snapshots s
            WHERE s.symbol = %s
              AND s.timestamp BETWEEN %s AND %s
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
        """
        
        print("実行計画:")
        plan = explain_analyze_query(optimized_query, (symbol, start_date, end_date), conn)
        print(plan)
        print()
        
        print("実行時間測定（3回実行）:")
        optimized_result = benchmark_query(optimized_query, (symbol, start_date, end_date), conn)
        print(f"  平均: {optimized_result['avg']:.3f}秒")
        print(f"  最小: {optimized_result['min']:.3f}秒")
        print(f"  最大: {optimized_result['max']:.3f}秒")
        print()
        
        # 3. 比較結果
        print("【3. 比較結果】")
        print("-" * 80)
        
        if original_result['avg'] > 0:
            improvement = ((original_result['avg'] - optimized_result['avg']) / original_result['avg']) * 100
            speedup = original_result['avg'] / optimized_result['avg'] if optimized_result['avg'] > 0 else 0
            
            print(f"平均実行時間:")
            print(f"  元のクエリ: {original_result['avg']:.3f}秒")
            print(f"  最適化後: {optimized_result['avg']:.3f}秒")
            print(f"  改善率: {improvement:.1f}%")
            print(f"  高速化: {speedup:.2f}x")
            print()
            
            if improvement > 0:
                print(f"✓ 最適化により {improvement:.1f}% の改善が見られました。")
            else:
                print(f"⚠ 最適化の効果が限定的です。インデックスの確認を推奨します。")
        else:
            print("実行時間の比較ができませんでした。")
        
        print()
        print("=" * 80)
        print("測定完了")
        print("=" * 80)
        
        conn.close()
        
    except psycopg2.Error as e:
        print(f"データベースエラー: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

