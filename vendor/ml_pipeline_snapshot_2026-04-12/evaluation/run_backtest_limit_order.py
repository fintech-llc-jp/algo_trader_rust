"""
Limit Order Backtest Execution Script
指値注文を使用したバックテストを実行
"""
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.data_loader import MarketDataLoader
from data.exch_sim_data_loader import ExchSimDataLoader
from data.feature_engineering import FeatureEngineer
from models.momentum_model import MomentumModel
from evaluation.limit_order_backtester import LimitOrderBacktester
from config.settings import DatabaseConfig, ModelConfig, BacktestConfig


def generate_labels(df: pd.DataFrame) -> tuple:
    """
    ラベルを生成（Momentum戦略用）
    """
    config = ModelConfig()
    horizon = config.LABEL_HORIZON
    threshold = config.LABEL_THRESHOLD
    
    # 将来の価格変化率
    future_return = df['mid_price'].shift(-horizon).pct_change(horizon)
    
    # ラベル生成: 1=BUY, 0=HOLD, -1=SELL
    labels = np.zeros(len(df))
    labels[future_return > threshold] = 1  # BUY
    labels[future_return < -threshold] = -1  # SELL
    
    # 特徴量の準備
    feature_cols = [col for col in df.columns 
                    if col not in ['symbol', 'mid_price']]
    X = df[feature_cols].values
    y = labels
    
    # NaNを含む行を削除
    valid_mask = ~(np.isnan(X).any(axis=1) | np.isnan(y))
    X = X[valid_mask]
    y = y[valid_mask]
    
    # ラベルを0, 1, 2に変換（XGBoost用）
    y = y.astype(int) + 1
    
    # すべてのクラスが存在することを確認
    unique_classes = np.unique(y)
    if len(unique_classes) < 2:
        raise ValueError(f"Insufficient classes in labels: {unique_classes}. Need at least 2 classes.")
    
    if len(unique_classes) == 2:
        y = np.where(y == unique_classes[0], 0, 1)
    
    return X, y


def run_limit_order_backtest(
    symbol: str = "G_FX_BTCJPY",
    start_date: datetime = None,
    end_date: datetime = None,
    limit_order_timeout_seconds: int = 5,
    use_aggressive_limit: bool = True
):
    """
    指値注文を使用したバックテストを実行
    
    Args:
        symbol: シンボル
        start_date: 開始日時
        end_date: 終了日時
        limit_order_timeout_seconds: 指値注文のタイムアウト時間（秒）
        use_aggressive_limit: Trueの場合、指値がASK以上/BID以下の場合は即座に約定
    """
    loader = MarketDataLoader()
    feature_engineer = FeatureEngineer()
    model = MomentumModel()
    backtester = LimitOrderBacktester(
        limit_order_timeout_seconds=limit_order_timeout_seconds,
        use_aggressive_limit=use_aggressive_limit
    )
    
    try:
        # 日付の設定
        if end_date is None:
            end_date = datetime.now()
        if start_date is None:
            start_date = end_date - timedelta(days=1)
        
        print(f"\n{'='*70}")
        print(f"Limit Order Backtest: {symbol}")
        print(f"Period: {start_date} to {end_date}")
        print(f"Limit Order Timeout: {limit_order_timeout_seconds} seconds")
        print(f"Aggressive Limit: {use_aggressive_limit}")
        print(f"{'='*70}\n")
        
        # データロード
        print("Loading data...")
        df = loader.load_training_data(symbol, start_date, end_date)
        
        if len(df) == 0:
            raise ValueError("No data available for the specified period")
        
        print(f"Loaded {len(df)} records")
        
        # 必要なカラムの確認
        required_cols = ['bid_price_1', 'ask_price_1']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns for limit orders: {missing_cols}")
        
        # 特徴量エンジニアリング
        print("Engineering features...")
        df = feature_engineer.engineer_features(df)
        
        # モデルの訓練または読み込み
        print("Training model on training period...")
        # 訓練期間とテスト期間を分割
        split_idx = int(len(df) * 0.8)
        train_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()
        
        # 訓練データでラベル生成
        print("Generating labels...")
        X_train, y_train = generate_labels(train_df)
        
        if len(X_train) == 0:
            raise ValueError("No training samples generated")
        
        # モデル訓練
        feature_cols = [col for col in train_df.columns 
                        if col not in ['symbol', 'mid_price']]
        model.feature_columns = feature_cols
        model.train(X_train, y_train)
        
        print(f"Model trained on {len(X_train)} samples")
        print(f"Feature columns: {len(model.feature_columns)}")
        
        # テストデータで予測
        print("Generating predictions on test period...")
        feature_cols = model.feature_columns
        available_cols = [col for col in feature_cols if col in test_df.columns]
        
        if len(available_cols) == 0:
            raise ValueError("No matching feature columns found in test data")
        
        X_test = test_df[available_cols].values.astype(float)
        X_test = np.where(np.isfinite(X_test), X_test, 0)
        
        valid_mask = ~(pd.isna(X_test).any(axis=1))
        test_df = test_df[valid_mask]
        X_test = X_test[valid_mask]
        
        if len(X_test) == 0:
            raise ValueError("No valid test data after feature engineering")
        
        # 予測
        predictions, probabilities = model.predict(X_test)
        
        # シグナルと信頼度をSeriesに変換（0=SELL, 1=HOLD, 2=BUY -> -1=SELL, 0=HOLD, 1=BUY）
        signals = predictions - 1
        signals_series = pd.Series(signals, index=test_df.index)
        confidence_series = pd.Series(probabilities.max(axis=1), index=test_df.index)
        
        # バックテスト実行
        print("Running limit order backtest...")
        config = BacktestConfig()
        
        # テスト期間の約定履歴をフィルタ
        test_executions_df = None
        if executions_df is not None and len(executions_df) > 0:
            test_start = test_df.index[0]
            test_end = test_df.index[-1]
            if 'timestamp' in executions_df.columns:
                test_executions_df = executions_df[
                    (executions_df['timestamp'] >= test_start) & 
                    (executions_df['timestamp'] <= test_end)
                ].copy()
            else:
                test_executions_df = executions_df.copy()
        
        metrics = backtester.run(
            test_df,
            signals_series,
            confidence_series,
            confidence_threshold=config.CONFIDENCE_THRESHOLD,
            executions_df=test_executions_df
        )
        
        # 結果表示
        print("\n" + "="*70)
        print("LIMIT ORDER BACKTEST RESULTS")
        print("="*70)
        print(f"Symbol: {symbol}")
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
        print(f"\nLimit Order Statistics:")
        print(f"  Avg Fill Delay: {metrics['avg_fill_delay_seconds']:.2f} seconds")
        print(f"  Limit Order Fill Rate: {metrics['limit_order_fill_rate']:.2f}%")
        print("="*70 + "\n")
        
        return {
            'status': 'success',
            'symbol': symbol,
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
        if 'exch_sim_loader' in locals():
            exch_sim_loader.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Run limit order backtest')
    parser.add_argument('--symbol', type=str, default='G_FX_BTCJPY', help='Symbol to backtest')
    parser.add_argument('--days', type=float, default=1, help='Number of days to backtest')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--timeout', type=int, default=5, help='Limit order timeout in seconds')
    parser.add_argument('--no-aggressive', action='store_true', help='Disable aggressive limit orders')
    
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
    
    result = run_limit_order_backtest(
        symbol=args.symbol,
        start_date=start_date,
        end_date=end_date,
        limit_order_timeout_seconds=args.timeout,
        use_aggressive_limit=not args.no_aggressive
    )
    
    if result['status'] == 'success':
        print("\nLimit order backtest completed successfully!")
    else:
        print(f"\nLimit order backtest failed: {result.get('error', 'Unknown error')}")
        sys.exit(1)

