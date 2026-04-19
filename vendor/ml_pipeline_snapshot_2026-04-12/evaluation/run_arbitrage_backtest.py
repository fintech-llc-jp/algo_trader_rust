"""
Arbitrage Backtest Execution Script
アービトラージ戦略のバックテストを実行
"""
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# パスを追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.arbitrage_data_loader import ArbitrageDataLoader
from data.arbitrage_feature_engineering import ArbitrageFeatureEngineer
from models.arbitrage_model import ArbitrageModel
from evaluation.arbitrage_backtester import ArbitrageBacktester
from training.daily_trainer import DailyTrainer
from config.settings import DatabaseConfig, ModelConfig, BacktestConfig


def generate_arbitrage_labels(df: pd.DataFrame, horizon: int = 5, threshold: float = 0.0001) -> tuple:
    """
    アービトラージ戦略用のラベルを生成
    
    Args:
        df: 2つのシンボルの統合データ（spread, spread_zscoreを含む）
        horizon: 予測期間（秒）
        threshold: Zスコアの閾値
    
    Returns:
        (X, y)
        y: 0=HOLD, 1=LONG_G_SHORT_B, 2=SHORT_G_LONG_B
    """
    if 'spread_zscore' not in df.columns:
        raise ValueError("spread_zscore column not found")
    
    # 将来のZスコアを計算
    future_zscore = df['spread_zscore'].shift(-horizon)
    
    # ラベル生成
    labels = np.zeros(len(df))
    
    # 現在のZスコアが閾値以上で、将来収束する場合
    # LONG_G_SHORT_B: 現在Zスコア > threshold かつ 将来Zスコア < 現在Zスコア
    mask_long = (df['spread_zscore'] > threshold) & (future_zscore < df['spread_zscore'])
    labels[mask_long] = 1
    
    # SHORT_G_LONG_B: 現在Zスコア < -threshold かつ 将来Zスコア > 現在Zスコア
    mask_short = (df['spread_zscore'] < -threshold) & (future_zscore > df['spread_zscore'])
    labels[mask_short] = 2
    
    # 特徴量の準備
    # 数値型のカラムのみを選択
    feature_cols = []
    for col in df.columns:
        if col in ['spread', 'symbol1', 'symbol2', 'spread_ratio']:
            continue
        if col.startswith('G_FX_BTCJPY_mid_price') or col.startswith('B_FX_BTCJPY_mid_price'):
            continue
        # 数値型のカラムのみを追加
        if df[col].dtype in [np.int64, np.int32, np.float64, np.float32]:
            feature_cols.append(col)
    
    if len(feature_cols) == 0:
        raise ValueError("No numeric feature columns found")
    
    X = df[feature_cols].values.astype(float)
    y = labels.astype(float)
    
    # 無限大を0に置換
    X = np.where(np.isfinite(X), X, 0)
    
    # NaNを含む行を削除
    valid_mask = ~(np.isnan(X).any(axis=1) | np.isnan(y) | ~np.isfinite(X).all(axis=1))
    X = X[valid_mask]
    y = y[valid_mask]
    
    # すべてのクラスが存在することを確認
    unique_classes = np.unique(y)
    if len(unique_classes) < 2:
        raise ValueError(f"Insufficient classes in labels: {unique_classes}. Need at least 2 classes.")
    
    # クラス数が3未満の場合は調整
    if len(unique_classes) == 2:
        # 2クラスの場合、0と1にマッピング
        y = np.where(y == unique_classes[0], 0, 1)
    
    return X, y


def run_arbitrage_backtest(
    symbol1: str = "G_FX_BTCJPY",
    symbol2: str = "B_FX_BTCJPY",
    start_date: datetime = None,
    end_date: datetime = None,
    use_trained_model: bool = False,
    model_version: int = None
):
    """
    アービトラージ戦略のバックテストを実行
    
    Args:
        symbol1: 第1シンボル（デフォルト: G_FX_BTCJPY）
        symbol2: 第2シンボル（デフォルト: B_FX_BTCJPY）
        start_date: 開始日時
        end_date: 終了日時
        use_trained_model: Trueの場合、訓練済みモデルを使用（現在は未実装）
        model_version: 使用するモデルのバージョン
    """
    loader = ArbitrageDataLoader(use_exch_sim_db=True)
    feature_engineer = ArbitrageFeatureEngineer()
    backtester = ArbitrageBacktester()
    
    try:
        # 日付の設定
        if end_date is None:
            end_date = datetime.now()
        if start_date is None:
            start_date = end_date - timedelta(days=1)
        
        print(f"\n{'='*70}")
        print(f"Arbitrage Backtest: {symbol1} vs {symbol2}")
        print(f"Period: {start_date} to {end_date}")
        print(f"{'='*70}\n")
        
        # データロード
        print("Loading arbitrage data...")
        df = loader.load_arbitrage_training_data(symbol1, symbol2, start_date, end_date)
        
        if len(df) == 0:
            raise ValueError("No data available for the specified period")
        
        print(f"Loaded {len(df)} records")
        
        # 特徴量エンジニアリング
        print("Engineering features...")
        df = feature_engineer.engineer_features(df)
        
        # モデルの訓練または読み込み
        if use_trained_model:
            print("Loading trained model...")
            # TODO: 訓練済みモデルの読み込み実装
            raise NotImplementedError("Loading trained models is not yet implemented")
        else:
            print("Training model on training period...")
            # 訓練期間とテスト期間を分割
            split_idx = int(len(df) * 0.8)
            train_df = df.iloc[:split_idx].copy()
            test_df = df.iloc[split_idx:].copy()
            
            # 訓練データでラベル生成
            print("Generating labels...")
            X_train, y_train = generate_arbitrage_labels(train_df)
            
            if len(X_train) == 0:
                raise ValueError("No training samples generated")
            
            # モデル訓練
            model = ArbitrageModel()
            model.feature_columns = feature_engineer.get_feature_columns()
            model.train(X_train, y_train)
            
            print(f"Model trained on {len(X_train)} samples")
            print(f"Feature columns: {len(model.feature_columns)}")
        
        # テストデータで予測
        print("Generating predictions on test period...")
        feature_cols = model.feature_columns
        
        # 特徴量カラムが存在するか確認（数値型のみ）
        available_cols = []
        for col in feature_cols:
            if col in test_df.columns:
                # 数値型のカラムのみを使用
                if test_df[col].dtype in [np.int64, np.int32, np.float64, np.float32]:
                    available_cols.append(col)
        
        if len(available_cols) == 0:
            raise ValueError("No matching numeric feature columns found in test data")
        
        if len(available_cols) != len(feature_cols):
            print(f"Warning: Using {len(available_cols)} features instead of {len(feature_cols)}")
        
        X_test = test_df[available_cols].values.astype(float)
        
        # 無限大を0に置換
        X_test = np.where(np.isfinite(X_test), X_test, 0)
        
        # NaNを含む行を削除
        valid_mask = ~(pd.isna(X_test).any(axis=1))
        test_df = test_df[valid_mask]
        X_test = X_test[valid_mask]
        
        if len(X_test) == 0:
            raise ValueError("No valid test data after feature engineering")
        
        # 予測
        signals, confidence = model.predict_entry_signal(X_test)
        
        # シグナルと信頼度をSeriesに変換
        signals_series = pd.Series(signals, index=test_df.index)
        confidence_series = pd.Series(confidence, index=test_df.index)
        
        # バックテスト実行
        print("Running backtest...")
        config = BacktestConfig()
        metrics = backtester.run(
            test_df,
            signals_series,
            confidence_series,
            symbol1=symbol1,
            symbol2=symbol2,
            confidence_threshold=config.CONFIDENCE_THRESHOLD
        )
        
        # 結果表示
        print("\n" + "="*70)
        print("ARBITRAGE BACKTEST RESULTS")
        print("="*70)
        print(f"Symbols: {symbol1} vs {symbol2}")
        print(f"Test Period: {test_df.index[0]} to {test_df.index[-1]}")
        print(f"Test Samples: {len(test_df)}")
        print(f"\nPerformance Metrics:")
        print(f"  Total Return: {metrics['total_return']:.2f}%")
        print(f"  Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
        print(f"  Max Drawdown: {metrics['max_drawdown']:.2f}%")
        print(f"  Final Equity: {metrics['final_equity']:,.0f} JPY")
        print(f"\nTrading Statistics:")
        print(f"  Total Trades: {metrics['total_trades']}")
        print(f"  Win Rate: {metrics['win_rate']:.2f}%")
        print(f"  Avg Win: {metrics['avg_win']:,.0f} JPY")
        print(f"  Avg Loss: {metrics['avg_loss']:,.0f} JPY")
        print(f"  Profit Factor: {metrics['profit_factor']:.2f}")
        print("="*70 + "\n")
        
        return {
            'status': 'success',
            'symbol1': symbol1,
            'symbol2': symbol2,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'metrics': metrics
        }
        
    except Exception as e:
        print(f"\nBacktest failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error': str(e)
        }
    finally:
        loader.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Run arbitrage backtest')
    parser.add_argument('--symbol1', type=str, default='G_FX_BTCJPY', help='First symbol')
    parser.add_argument('--symbol2', type=str, default='B_FX_BTCJPY', help='Second symbol')
    parser.add_argument('--days', type=float, default=1, help='Number of days to backtest')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)')
    
    args = parser.parse_args()
    
    start_date = None
    end_date = None
    
    if args.start_date:
        try:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
            except ValueError:
                print(f"Error: Invalid start date format: {args.start_date}")
                sys.exit(1)
    
    if args.end_date:
        try:
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
            except ValueError:
                print(f"Error: Invalid end date format: {args.end_date}")
                sys.exit(1)
    elif args.days:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=args.days)
    
    result = run_arbitrage_backtest(
        symbol1=args.symbol1,
        symbol2=args.symbol2,
        start_date=start_date,
        end_date=end_date
    )
    
    if result['status'] == 'success':
        print("\nArbitrage backtest completed successfully!")
    else:
        print(f"\nArbitrage backtest failed: {result.get('error', 'Unknown error')}")
        sys.exit(1)

