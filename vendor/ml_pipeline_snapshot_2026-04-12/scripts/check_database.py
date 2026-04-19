"""
データベース接続とデータの存在を確認するスクリプト
"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.data_loader import MarketDataLoader
from config.settings import DatabaseConfig


def check_database():
    """データベース接続とデータの存在を確認"""
    print("="*70)
    print("Database Connection Check")
    print("="*70)
    
    # 設定の確認
    print("\nDatabase Configuration:")
    print(f"  Host: {DatabaseConfig.HOST}")
    print(f"  Port: {DatabaseConfig.PORT}")
    print(f"  Database: {DatabaseConfig.NAME}")
    print(f"  User: {DatabaseConfig.USER}")
    print(f"  Use ExchSim DB: {DatabaseConfig.USE_EXCH_SIM_DB}")
    if DatabaseConfig.USE_EXCH_SIM_DB:
        print(f"  ExchSim DB Name: {DatabaseConfig.EXCH_SIM_DB_NAME}")
    
    # データローダーの作成
    try:
        loader = MarketDataLoader()
        print("\n✓ Database connection successful")
    except Exception as e:
        print(f"\n✗ Database connection failed: {e}")
        return False
    
    # シンボルのリスト
    symbols = ["G_FX_BTCJPY", "B_FX_BTCJPY"]
    
    # 各シンボルのデータを確認
    print("\n" + "="*70)
    print("Data Availability Check")
    print("="*70)
    
    for symbol in symbols:
        print(f"\nSymbol: {symbol}")
        
        # 最新のデータを確認
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)  # 過去7日間
        
        try:
            # 市場データの確認
            market_df = loader.load_market_data(symbol, start_date, end_date, min_quality_score=0)
            print(f"  Market Data: {len(market_df)} records")
            if len(market_df) > 0:
                print(f"    First record: {market_df.index[0]}")
                print(f"    Last record: {market_df.index[-1]}")
            
            # 約定データの確認
            exec_df = loader.load_executions(symbol, start_date, end_date)
            print(f"  Execution Data: {len(exec_df)} records")
            if len(exec_df) > 0:
                print(f"    First execution: {exec_df['timestamp'].iloc[0] if 'timestamp' in exec_df.columns else exec_df.index[0]}")
                print(f"    Last execution: {exec_df['timestamp'].iloc[-1] if 'timestamp' in exec_df.columns else exec_df.index[-1]}")
            
            # 訓練データの確認
            train_df = loader.load_training_data(symbol, start_date, end_date)
            print(f"  Training Data: {len(train_df)} records")
            if len(train_df) > 0:
                print(f"    Columns: {len(train_df.columns)}")
                print(f"    Date range: {train_df.index[0]} to {train_df.index[-1]}")
            
        except Exception as e:
            print(f"  ✗ Error loading data: {e}")
            import traceback
            traceback.print_exc()
    
    loader.close()
    print("\n" + "="*70)
    print("Check completed")
    print("="*70)
    
    return True


if __name__ == "__main__":
    check_database()

