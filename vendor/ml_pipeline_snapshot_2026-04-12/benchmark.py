
import sys
import os
import time
import pandas as pd
from datetime import datetime, timedelta
import pytz

# Add project root and ml_pipeline to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'ml_pipeline'))

from ml_pipeline.data.exch_sim_data_loader import ExchSimDataLoader
from ml_pipeline.data.feature_engineering import FeatureEngineer

def benchmark():
    print("Initializing components...")
    loader = ExchSimDataLoader()
    engineer = FeatureEngineer()
    
    symbol = "G_FX_BTCJPY"
    
    # Get latest timestamp
    try:
        with loader.conn.cursor() as cur:
            cur.execute("SELECT MAX(timestamp) FROM market_board_snapshots WHERE symbol = %s", (symbol,))
            res = cur.fetchone()
            if res and res[0]:
                max_ts = res[0]
                if max_ts.tzinfo is None:
                    max_ts = pytz.utc.localize(max_ts)
                end_time = max_ts
            else:
                end_time = datetime.now(pytz.utc)
    except Exception:
        end_time = datetime.now(pytz.utc)

    # 5 minutes window
    start_time = end_time - timedelta(minutes=5)
    
    print(f"\n--- Benchmark Config ---")
    print(f"Symbol: {symbol}")
    print(f"Window: {start_time} to {end_time}")
    
    # 1. Measure Data Loading
    print(f"\n[1] Measuring Data Loading (load_training_data)...")
    t0 = time.time()
    try:
        df = loader.load_training_data(symbol, start_time, end_time, skip_min_samples_check=True)
        t_load = time.time() - t0
        print(f"-> Time: {t_load:.4f} seconds")
        print(f"-> Rows loaded: {len(df)}")
    except Exception as e:
        print(f"-> Failed: {e}")
        return

    # 2. Measure Feature Engineering
    print(f"\n[2] Measuring Feature Engineering (engineer_features)...")
    t0 = time.time()
    try:
        df_features = engineer.engineer_features(df)
        t_feat = time.time() - t0
        print(f"-> Time: {t_feat:.4f} seconds")
        print(f"-> Features generated: {len(df_features.columns)}")
    except Exception as e:
        print(f"-> Failed: {e}")
        return
        
    print(f"\n--- Total Summary ---")
    print(f"Data Loading:      {t_load:.4f}s")
    print(f"Feature Engineering: {t_feat:.4f}s")
    print(f"Total Time:        {t_load + t_feat:.4f}s")

    loader.close()

if __name__ == "__main__":
    benchmark()
