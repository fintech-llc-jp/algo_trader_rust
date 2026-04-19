"""
Limit Order Mean Reversion Backtest Execution Script
指値注文を活用した平均回帰戦略のバックテストを実行
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
from strategy.limit_order_mean_reversion_strategy import LimitOrderMeanReversionStrategy
from config.settings import DatabaseConfig, ModelConfig, BacktestConfig


def run_limit_order_mean_reversion_backtest(
    symbol: str = "G_FX_BTCJPY",
    start_date: datetime = None,
    end_date: datetime = None,
    lookback_period: int = 300,
    zscore_threshold: float = 2.0
):
    """
    指値注文を活用した平均回帰戦略のバックテストを実行
    
    Args:
        symbol: シンボル
        start_date: 開始日時
        end_date: 終了日時
        lookback_period: Zスコア計算のルックバック期間（秒）
        zscore_threshold: Zスコアの閾値
    """
    loader = MarketDataLoader()
    exch_sim_loader = ExchSimDataLoader()
    feature_engineer = FeatureEngineer()
    strategy = LimitOrderMeanReversionStrategy(
        lookback_period=lookback_period,
        zscore_threshold=zscore_threshold
    )
    
    try:
        # 日付の設定
        if end_date is None:
            end_date = datetime.now()
        if start_date is None:
            start_date = end_date - timedelta(days=1)
        
        print(f"\n{'='*70}")
        print(f"Limit Order Mean Reversion Backtest: {symbol}")
        print(f"Period: {start_date} to {end_date}")
        print(f"Lookback Period: {lookback_period} seconds")
        print(f"Z-Score Threshold: {zscore_threshold}")
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
        
        # 約定履歴データをロード
        print("Loading execution history...")
        executions_df = exch_sim_loader.load_executions(symbol, start_date, end_date)
        print(f"Loaded {len(executions_df)} executions")
        
        # 特徴量エンジニアリング
        print("Engineering features...")
        df = feature_engineer.engineer_features(df)
        
        # モデルの訓練
        print("Training model on training period...")
        split_idx = int(len(df) * 0.8)
        train_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()
        
        # 訓練
        train_result = strategy.train(train_df)
        print(f"Model trained: Accuracy={train_result['accuracy']:.2%}")
        
        # 予測
        print("Generating predictions on test period...")
        signals, confidence = strategy.predict(test_df)
        
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
        
        # バックテスト実行（指値注文を使用）
        print("Running limit order backtest...")
        config = BacktestConfig()
        metrics = strategy.backtest(
            test_df,
            signals,
            confidence,
            executions_df=test_executions_df
        )
        
        # 結果表示
        print("\n" + "="*70)
        print("LIMIT ORDER MEAN REVERSION BACKTEST RESULTS")
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
        print(f"  Avg Fill Delay: {metrics.get('avg_fill_delay_seconds', 0):.2f} seconds")
        print(f"  Limit Order Fill Rate: {metrics.get('limit_order_fill_rate', 0):.2f}%")
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
    
    parser = argparse.ArgumentParser(description='Run limit order mean reversion backtest')
    parser.add_argument('--symbol', type=str, default='G_FX_BTCJPY', help='Symbol to backtest')
    parser.add_argument('--days', type=float, default=1, help='Number of days to backtest')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--lookback', type=int, default=300, help='Lookback period in seconds')
    parser.add_argument('--zscore-threshold', type=float, default=2.0, help='Z-score threshold')
    
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
    
    result = run_limit_order_mean_reversion_backtest(
        symbol=args.symbol,
        start_date=start_date,
        end_date=end_date,
        lookback_period=args.lookback,
        zscore_threshold=args.zscore_threshold
    )
    
    if result['status'] == 'success':
        print("\nLimit order mean reversion backtest completed successfully!")
    else:
        print(f"\nLimit order mean reversion backtest failed: {result.get('error', 'Unknown error')}")
        sys.exit(1)

