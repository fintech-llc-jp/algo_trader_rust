#!/usr/bin/env python3
"""
ML APIサーバーのトレードシグナル生成をテストするスクリプト
"""
import os
import sys
import requests
from datetime import datetime, timedelta, timezone
import json
import psycopg2
import pandas as pd

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.exch_sim_data_loader import ExchSimDataLoader
from config.settings import DatabaseConfig


def get_latest_market_data(symbol: str, loader: ExchSimDataLoader):
    """最新の市場データを取得"""
    end_time = datetime.now(timezone.utc).replace(tzinfo=None)
    
    # MIN_SAMPLESを満たすために、より長い期間のデータを取得
    # 1秒間隔で1000サンプル = 約17分、余裕を持って20分間のデータを取得
    start_time = end_time - timedelta(minutes=20)
    
    try:
        # MIN_SAMPLESチェックを回避するため、直接SQLクエリを使用して最新のデータのみを取得
        conn = psycopg2.connect(DatabaseConfig.get_exch_sim_connection_string())
        query = """
        SELECT 
            s.timestamp,
            s.symbol,
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
        ORDER BY s.timestamp DESC
        LIMIT 1
        """
        
        df = pd.read_sql_query(query, conn, params=(symbol, start_time, end_time))
        conn.close()
        
        if len(df) == 0:
            print(f"   警告: {start_time} ～ {end_time} の期間にデータが見つかりません")
            # より長い期間を試す
            start_time = end_time - timedelta(hours=1)
            conn = psycopg2.connect(DatabaseConfig.get_exch_sim_connection_string())
            df = pd.read_sql_query(query, conn, params=(symbol, start_time, end_time))
            conn.close()
            
            if len(df) == 0:
                return None
        
        # 最新のデータを取得
        latest = df.iloc[0]  # DESCでソートされているので最初の行が最新
        
        # タイムスタンプを取得
        timestamp_str = latest['timestamp'].isoformat() + 'Z' if isinstance(latest['timestamp'], datetime) else str(latest['timestamp']) + 'Z'
        
        bid_price = float(latest['bid_price_1'])
        ask_price = float(latest['ask_price_1'])
        
        return {
            'symbol': symbol,
            'timestamp': timestamp_str,
            'mid_price': float((bid_price + ask_price) / 2),
            'bid_price_1': bid_price,
            'ask_price_1': ask_price,
            'bid_qty_1': float(latest.get('bid_qty_1', 0.1)),
            'ask_qty_1': float(latest.get('ask_qty_1', 0.1)),
            'spread': float(ask_price - bid_price),
            'order_imbalance': 0.0,  # 簡易版
            'bid_depth_5': float(latest.get('bid_depth_5', 0.5)),
            'ask_depth_5': float(latest.get('ask_depth_5', 0.4))
        }
    except Exception as e:
        print(f"エラー: データの取得に失敗しました: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_signal_generation(api_url: str = "http://localhost:8000", symbol: str = "G_FX_BTCJPY"):
    """トレードシグナル生成をテスト"""
    
    print("="*70)
    print("ML APIサーバー - トレードシグナル生成テスト")
    print("="*70)
    print(f"API URL: {api_url}")
    print(f"シンボル: {symbol}\n")
    
    # 1. ヘルスチェック
    print("1. ヘルスチェック中...")
    try:
        response = requests.get(f"{api_url}/health", timeout=5)
        if response.status_code == 200:
            health = response.json()
            print(f"   ✓ ステータス: {health['status']}")
            print(f"   ✓ モデルロード済み: {health['models_loaded']}")
            print(f"   ✓ データベース接続: {health['database_connected']}\n")
            
            if not health['models_loaded']:
                print("   ⚠ 警告: モデルがロードされていません")
                return False
        else:
            print(f"   ✗ エラー: HTTP {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"   ✗ エラー: APIサーバーに接続できません ({api_url})")
        print("   → サーバーが起動しているか確認してください")
        return False
    except Exception as e:
        print(f"   ✗ エラー: {e}")
        return False
    
    # 2. 最新の市場データを取得
    print("2. 最新の市場データを取得中...")
    try:
        loader = ExchSimDataLoader()
        market_data = get_latest_market_data(symbol, loader)
        loader.close()
        
        if market_data is None:
            print("   ✗ エラー: 市場データを取得できませんでした")
            print("   → データベースにデータが存在するか確認してください")
            return False
        
        print(f"   ✓ タイムスタンプ: {market_data['timestamp']}")
        print(f"   ✓ 中間価格: {market_data['mid_price']:,.0f} JPY")
        print(f"   ✓ BID価格: {market_data['bid_price_1']:,.0f} JPY")
        print(f"   ✓ ASK価格: {market_data['ask_price_1']:,.0f} JPY")
        print(f"   ✓ スプレッド: {market_data['spread']:,.0f} JPY\n")
    except Exception as e:
        print(f"   ✗ エラー: {e}")
        return False
    
    # 3. シグナル生成APIを呼び出し
    print("3. トレードシグナルを生成中...")
    try:
        response = requests.post(
            f"{api_url}/signal",
            json=market_data,
            timeout=30
        )
        
        if response.status_code == 200:
            signal = response.json()
            
            print("   ✓ シグナル生成成功！\n")
            print("="*70)
            print("トレードシグナル結果")
            print("="*70)
            print(f"シンボル: {signal['symbol']}")
            print(f"タイムスタンプ: {signal['timestamp']}")
            print(f"シグナルタイプ: {signal['signal_type']}")
            print(f"信頼度: {signal['confidence']:.2%}")
            print(f"現在価格: {signal['current_price']:,.0f} JPY")
            print(f"予測価格: {signal['predicted_price']:,.0f} JPY")
            print(f"価格変動率: {signal['price_change_pct']:.2f}%")
            if signal.get('momentum_intensity') is not None:
                print(f"モメンタム強度: {signal['momentum_intensity']}")
            print("="*70)
            
            # シグナルの解釈
            print("\nシグナルの解釈:")
            if signal['signal_type'] == 'BUY':
                print("  → 買いシグナル: 価格上昇が予測されています")
            elif signal['signal_type'] == 'SELL':
                print("  → 売りシグナル: 価格下落が予測されています")
            else:
                print("  → ホールド: 明確な方向性がありません")
            
            print(f"  → 信頼度: {signal['confidence']:.2%} ({'高' if signal['confidence'] > 0.7 else '中' if signal['confidence'] > 0.5 else '低'})")
            print(f"  → 予測価格変動: {signal['price_change_pct']:.2f}%")
            
            return True
        else:
            print(f"   ✗ エラー: HTTP {response.status_code}")
            try:
                error_detail = response.json()
                print(f"   詳細: {error_detail.get('detail', 'Unknown error')}")
            except:
                print(f"   レスポンス: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        print("   ✗ エラー: リクエストがタイムアウトしました（30秒）")
        print("   → データベースの応答が遅い可能性があります")
        return False
    except Exception as e:
        print(f"   ✗ エラー: {e}")
        return False


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='ML APIサーバーのトレードシグナル生成をテスト')
    parser.add_argument(
        '--url',
        type=str,
        default='http://localhost:8000',
        help='APIサーバーのURL（デフォルト: http://localhost:8000）'
    )
    parser.add_argument(
        '--symbol',
        type=str,
        default='G_FX_BTCJPY',
        help='テストするシンボル（デフォルト: G_FX_BTCJPY）'
    )
    
    args = parser.parse_args()
    
    success = test_signal_generation(args.url, args.symbol)
    
    if success:
        print("\n✓ テスト成功！")
        sys.exit(0)
    else:
        print("\n✗ テスト失敗")
        sys.exit(1)


if __name__ == '__main__':
    main()

