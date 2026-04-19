
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Add ml_pipeline to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from data.data_loader import MarketDataLoader
from data.feature_engineering import FeatureEngineer
from models.price_prediction_model import PricePredictionModel

def main():
    symbol = "G_FX_BTCJPY"
    loader = MarketDataLoader()
    engineer = FeatureEngineer()
    
    # 1. Load Data (Last 5 hours)
    end_date = datetime.now()
    start_date = end_date - timedelta(hours=5)
    
    print(f"Loading data from {start_date} to {end_date}...")
    df = None
    try:
        # Using skip_min_samples_check=True to allow running with whatever data we have
        df = loader.load_market_data(symbol, start_date, end_date, skip_min_samples_check=True)
    except Exception as e:
        print(f"Failed to load market data: {e}")

    # Fallback to synthetic data if no real data found
    if df is None or len(df) < 1000: 
        print(f"\n[WARNING] Insufficient real data found (rows={len(df) if df is not None else 0}).")
        print("Switching to SYNTHETIC DATA generation for verification purposes.")
        
        # Generate 5 hours of 1-second data
        periods = 5 * 3600
        timestamps = [start_date + timedelta(seconds=i) for i in range(periods)]
        
        # Generate price: Sine wave + Random Walk + Noise
        t = np.linspace(0, 100, periods)
        trend = np.linspace(0, 10, periods) # Slight upward trend
        sine = 100 * np.sin(t) # Cyclic component
        noise = np.random.normal(0, 5, periods) # Noise
        
        mid_prices = 4000000 + trend + sine + noise
        
        # Create DataFrame matching expected columns
        data = {
            'symbol': [symbol] * periods,
            'mid_price': mid_prices,
            'spread': [100] * periods,
            'bid_price_1': mid_prices - 50,
            'ask_price_1': mid_prices + 50,
            'bid_qty_1': np.random.uniform(0.1, 1.0, periods),
            'ask_qty_1': np.random.uniform(0.1, 1.0, periods),
            'bid_depth_5': np.random.uniform(1.0, 5.0, periods),
            'ask_depth_5': np.random.uniform(1.0, 5.0, periods),
            'order_imbalance': np.random.uniform(-1, 1, periods),
            # Mock volume data for feature engineering
            'volume_buy': np.random.uniform(0, 0.5, periods),
            'volume_sell': np.random.uniform(0, 0.5, periods),
            'volume_total': np.random.uniform(0, 1.0, periods),
        }
        
        df = pd.DataFrame(data, index=timestamps)
        print(f"Generated {len(df)} rows of synthetic data.")

    print(f"Processing {len(df)} rows for verification.")


    # 2. Features
    print("Engineering features...")
    df = engineer.engineer_features(df)
    feature_cols = engineer.get_feature_columns()
    print(f"Generated {len(feature_cols)} features.")
    
    # 3. Horizons
    horizons = {
        '1m': 60,
        '5m': 300,
        '10m': 600
    }
    
    results = {}
    
    print("\nStarting Verification...")
    
    for name, seconds in horizons.items():
        print(f"\n=== Verifying {name} ({seconds}s) horizon ===")
        
        # Prepare Target
        y_col = f'target_{name}'
        df[y_col] = df['mid_price'].shift(-seconds)
        
        # Drop NaNs created by shift and engineering
        # Make sure we don't drop rows that are valid for this specific horizon check
        valid_df = df.dropna(subset=feature_cols + [y_col])
        
        if len(valid_df) == 0:
            print(f"No valid data for {name} horizon after dropna.")
            continue
            
        print(f"Valid samples: {len(valid_df)}")
        
        # Split (80% train, 20% test) - simple time-based split
        split_idx = int(len(valid_df) * 0.8)
        
        train_df = valid_df.iloc[:split_idx]
        test_df = valid_df.iloc[split_idx:]
        
        X_train = train_df[feature_cols].values
        y_train = train_df[y_col].values
        
        X_test = test_df[feature_cols].values
        y_test = test_df[y_col].values
        
        # Current price for baseline (Predicting next price = current price)
        current_prices_test = test_df['mid_price'].values
        
        # Train Model
        print(f"Training model on {len(X_train)} samples...")
        model = PricePredictionModel()
        model.feature_columns = feature_cols
        model.train(X_train, y_train)
        
        # Predict
        print(f"Predicting on {len(X_test)} samples...")
        y_pred = model.predict(X_test)
        
        # Evaluation
        rmse = np.sqrt(np.mean((y_test - y_pred)**2))
        mae = np.mean(np.abs(y_test - y_pred))
        
        # Baseline Evaluation (hold current price)
        # If I predict price will not change: result = current_price
        baseline_preds = current_prices_test
        base_rmse = np.sqrt(np.mean((y_test - baseline_preds)**2))
        base_mae = np.mean(np.abs(y_test - baseline_preds))
        
        print(f"Model RMSE: {rmse:.4f}, MAE: {mae:.4f}")
        print(f"Base  RMSE: {base_rmse:.4f}, MAE: {base_mae:.4f}")
        
        improvement = (base_rmse - rmse) / base_rmse * 100
        print(f"Improvement over Baseline: {improvement:.2f}%")
        
        results[name] = {
            'RMSE': rmse,
            'MAE': mae,
            'BaseRMSE': base_rmse,
            'Improvement': improvement,
            'Samples': len(X_test)
        }
        
        # Sample predictions
        print("Sample predictions (Actual vs Pred vs Base):")
        indices = np.linspace(0, len(y_test)-1, 5, dtype=int)
        for i in indices:
            print(f"  Target: {y_test[i]:.1f}, Pred: {y_pred[i]:.1f}, Base: {baseline_preds[i]:.1f}, Diff: {y_pred[i]-y_test[i]:.1f}")

    print("\n=== Final Summary ===")
    if not results:
        print("No results collected.")
    else:
        for name, res in results.items():
            print(f"{name}: RMSE={res['RMSE']:.2f} vs Base={res['BaseRMSE']:.2f} (Imp: {res['Improvement']:.2f}%)")

if __name__ == "__main__":
    main()
