#!/usr/bin/env python3
"""
データローディングのデバッグスクリプト
"""
import sys
import os
from datetime import datetime, timezone

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.exch_sim_data_loader import ExchSimDataLoader

def main():
    symbol = "B_FX_BTCJPY"
    start_date = datetime(2026, 1, 7, 15, 0, 0, tzinfo=timezone.utc)
    end_date = datetime(2026, 1, 8, 1, 0, 0, tzinfo=timezone.utc)
    
    print(f"デバッグ: データローディングテスト")
    print(f"Symbol: {symbol}")
    print(f"Start Date: {start_date}")
    print(f"End Date: {end_date}")
    print()
    
    loader = ExchSimDataLoader(use_connection_pool=True)
    
    try:
        print("1. load_market_data()を呼び出し...")
        df = loader.load_market_data(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            skip_min_samples_check=True
        )
        print(f"  結果: {len(df)}件のデータが取得されました")
        if len(df) > 0:
            print(f"  最初の行:")
            print(df.head(1))
            print(f"  最後の行:")
            print(df.tail(1))
    except Exception as e:
        print(f"  エラー: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    print("2. load_training_data()を呼び出し...")
    try:
        df2 = loader.load_training_data(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            skip_min_samples_check=True
        )
        print(f"  結果: {len(df2)}件のデータが取得されました")
        if len(df2) > 0:
            print(f"  最初の行:")
            print(df2.head(1))
    except Exception as e:
        print(f"  エラー: {e}")
        import traceback
        traceback.print_exc()
    finally:
        loader.close()

if __name__ == "__main__":
    main()
