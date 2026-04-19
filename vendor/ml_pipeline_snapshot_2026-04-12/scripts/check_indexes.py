#!/usr/bin/env python3
"""
インデックス確認スクリプト
exch_simデータベースのインデックスの存在確認と使用状況を確認します
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from config.settings import DatabaseConfig


def check_indexes():
    """インデックスの存在確認と使用状況を確認"""
    
    # データベース接続
    try:
        conn = psycopg2.connect(DatabaseConfig.get_exch_sim_connection_string())
        cur = conn.cursor()
        
        print("=" * 80)
        print("インデックス確認レポート")
        print("=" * 80)
        print(f"データベース: {DatabaseConfig.EXCH_SIM_DB_NAME}")
        print(f"ホスト: {DatabaseConfig.HOST}:{DatabaseConfig.PORT}")
        print()
        
        # 1. すべてのインデックスを一覧表示
        print("【1. インデックス一覧】")
        print("-" * 80)
        
        query = """
        SELECT 
            schemaname,
            tablename,
            indexname,
            indexdef
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND tablename IN ('market_board_snapshots', 'market_board_price_levels', 'executions')
        ORDER BY tablename, indexname;
        """
        
        cur.execute(query)
        indexes = cur.fetchall()
        
        if not indexes:
            print("インデックスが見つかりませんでした。")
        else:
            current_table = None
            for schema, table, index_name, index_def in indexes:
                if table != current_table:
                    if current_table is not None:
                        print()
                    print(f"\nテーブル: {table}")
                    current_table = table
                print(f"  - {index_name}")
                print(f"    {index_def}")
        
        print()
        print()
        
        # 2. 最適化インデックスの存在確認
        print("【2. 最適化インデックスの存在確認】")
        print("-" * 80)
        
        required_indexes = [
            ('market_board_snapshots', 'idx_snapshots_symbol_timestamp_id'),
            ('market_board_price_levels', 'idx_price_levels_snapshot_side_level'),
            ('market_board_price_levels', 'idx_price_levels_snapshot_side_level_0_4'),
            ('executions', 'idx_executions_symbol_created_at_status'),
        ]
        
        existing_indexes = {f"{row[1]}.{row[2]}": row[3] for row in indexes}
        
        all_exist = True
        for table, index_name in required_indexes:
            key = f"{table}.{index_name}"
            if key in existing_indexes:
                print(f"✓ {index_name} (テーブル: {table}) - 存在します")
            else:
                print(f"✗ {index_name} (テーブル: {table}) - 存在しません")
                all_exist = False
        
        print()
        
        if all_exist:
            print("すべての最適化インデックスが存在します。")
        else:
            print("警告: 一部の最適化インデックスが存在しません。")
            print("      infrastructure/sql/optimize_backtest_indexes.sql を実行してください。")
        
        print()
        print()
        
        # 3. インデックスのサイズ確認
        print("【3. インデックスサイズ】")
        print("-" * 80)
        
        query = """
        SELECT
            schemaname,
            relname AS tablename,
            indexrelname AS indexname,
            pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
        FROM pg_stat_user_indexes
        WHERE schemaname = 'public'
          AND relname IN ('market_board_snapshots', 'market_board_price_levels', 'executions')
          AND indexrelname LIKE 'idx_%'
        ORDER BY relname, indexrelname;
        """
        
        cur.execute(query)
        index_sizes = cur.fetchall()
        
        if index_sizes:
            for schema, table, index_name, size in index_sizes:
                print(f"{table}.{index_name}: {size}")
        else:
            print("インデックスサイズ情報が見つかりませんでした。")
        
        print()
        print()
        
        # 4. テーブルの統計情報確認
        print("【4. テーブル統計情報】")
        print("-" * 80)
        
        query = """
        SELECT
            schemaname,
            relname AS tablename,
            n_live_tup AS row_count,
            last_vacuum,
            last_analyze
        FROM pg_stat_user_tables
        WHERE schemaname = 'public'
          AND relname IN ('market_board_snapshots', 'market_board_price_levels', 'executions')
        ORDER BY relname;
        """
        
        cur.execute(query)
        table_stats = cur.fetchall()
        
        if table_stats:
            for schema, table, row_count, last_vacuum, last_analyze in table_stats:
                print(f"\nテーブル: {table}")
                print(f"  行数: {row_count:,}")
                print(f"  最終VACUUM: {last_vacuum or '未実行'}")
                print(f"  最終ANALYZE: {last_analyze or '未実行'}")
        else:
            print("テーブル統計情報が見つかりませんでした。")
        
        print()
        print()
        
        # 5. インデックス使用状況の確認（PostgreSQL 9.2以降）
        print("【5. インデックス使用状況（サンプル）】")
        print("-" * 80)
        print("注意: この情報は統計情報に基づくため、実際の使用状況とは異なる場合があります。")
        print()
        
        query = """
        SELECT
            schemaname,
            relname AS tablename,
            indexrelname AS index_name,
            idx_scan AS index_scans,
            idx_tup_read AS tuples_read,
            idx_tup_fetch AS tuples_fetched
        FROM pg_stat_user_indexes
        WHERE schemaname = 'public'
          AND relname IN ('market_board_snapshots', 'market_board_price_levels', 'executions')
          AND indexrelname LIKE 'idx_%'
        ORDER BY relname, indexrelname
        LIMIT 20;
        """
        
        cur.execute(query)
        usage_stats = cur.fetchall()
        
        if usage_stats:
            for schema, table, index_name, scans, read, fetched in usage_stats:
                print(f"{table}.{index_name}:")
                print(f"  スキャン回数: {scans:,}")
                print(f"  読み取りタプル数: {read:,}")
                print(f"  フェッチタプル数: {fetched:,}")
                print()
        else:
            print("インデックス使用状況情報が見つかりませんでした。")
        
        print()
        print("=" * 80)
        print("確認完了")
        print("=" * 80)
        
        cur.close()
        conn.close()
        
    except psycopg2.Error as e:
        print(f"データベースエラー: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"エラー: {e}")
        sys.exit(1)


if __name__ == '__main__':
    check_indexes()

