"""
Run All Strategy Backtests with Timing
すべての戦略のバックテストを実行して、実行時間を計測
"""
import sys
import os
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.data_loader import MarketDataLoader
from data.arbitrage_data_loader import ArbitrageDataLoader
from data.feature_engineering import FeatureEngineer
from data.arbitrage_feature_engineering import ArbitrageFeatureEngineer
from strategy.order_flow_imbalance_strategy import OrderFlowImbalanceStrategy
from strategy.mean_reversion_strategy import MeanReversionStrategy
from strategy.multi_timeframe_strategy import MultiTimeframeStrategy
from evaluation.run_backtest import run_backtest_with_model
from evaluation.run_arbitrage_backtest import run_arbitrage_backtest
from evaluation.run_spot_arbitrage_backtest import run_spot_arbitrage_backtest
from evaluation.run_limit_order_mean_reversion_backtest import run_limit_order_mean_reversion_backtest
from config.settings import DatabaseConfig


def run_backtest_with_timing(strategy_name, func, *args, **kwargs):
    """
    バックテストを実行して時間を計測
    
    Args:
        strategy_name: 戦略名
        func: 実行する関数
        *args, **kwargs: 関数の引数
    
    Returns:
        (result, execution_time_seconds)
    """
    print(f"\n{'='*70}")
    print(f"Running {strategy_name} Backtest...")
    print(f"{'='*70}")
    
    start_time = time.time()
    
    try:
        result = func(*args, **kwargs)
        execution_time = time.time() - start_time
        
        if result.get('status') == 'success':
            metrics = result.get('metrics', {})
            print(f"\n✓ {strategy_name} completed in {execution_time:.2f} seconds")
            print(f"  Total Return: {metrics.get('total_return', 0):.2f}%")
            print(f"  Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}")
            print(f"  Max Drawdown: {metrics.get('max_drawdown', 0):.2f}%")
            print(f"  Total Trades: {metrics.get('total_trades', 0)}")
        else:
            print(f"\n✗ {strategy_name} failed: {result.get('error', 'Unknown error')}")
        
        return result, execution_time
    except Exception as e:
        execution_time = time.time() - start_time
        print(f"\n✗ {strategy_name} failed after {execution_time:.2f} seconds: {e}")
        import traceback
        traceback.print_exc()
        return {'status': 'error', 'error': str(e)}, execution_time


def run_all_backtests(
    symbol: str = "G_FX_BTCJPY",
    symbol2: str = "B_FX_BTCJPY",
    start_date: datetime = None,
    end_date: datetime = None,
    days: float = None
):
    """
    すべての戦略のバックテストを実行して時間を計測
    
    Args:
        symbol: 第1シンボル
        symbol2: 第2シンボル（アービトラージ戦略用）
        start_date: 開始日時
        end_date: 終了日時
        days: 日数（start_date/end_dateがNoneの場合）
    """
    # 日付の設定
    if end_date is None:
        end_date = datetime.now()
    if start_date is None:
        if days is not None:
            start_date = end_date - timedelta(days=days)
        else:
            start_date = end_date - timedelta(hours=24)
    
    print(f"\n{'='*70}")
    print(f"ALL STRATEGIES BACKTEST WITH TIMING")
    print(f"{'='*70}")
    print(f"Symbol: {symbol}")
    print(f"Period: {start_date} to {end_date}")
    print(f"{'='*70}\n")
    
    results = {}
    total_start_time = time.time()
    
    # 1. Momentum Strategy
    result, exec_time = run_backtest_with_timing(
        "Momentum Strategy",
        run_backtest_with_model,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date
    )
    results['momentum'] = {
        'result': result,
        'execution_time': exec_time
    }
    
    # 2. Arbitrage Strategy
    result, exec_time = run_backtest_with_timing(
        "Arbitrage Strategy",
        run_arbitrage_backtest,
        symbol1=symbol,
        symbol2=symbol2,
        start_date=start_date,
        end_date=end_date
    )
    results['arbitrage'] = {
        'result': result,
        'execution_time': exec_time
    }
    
    # 3. Order Flow Imbalance Strategy
    loader = MarketDataLoader()
    feature_engineer = FeatureEngineer()
    strategy = OrderFlowImbalanceStrategy()
    
    try:
        print(f"\n{'='*70}")
        print(f"Running Order Flow Imbalance Strategy Backtest...")
        print(f"{'='*70}")
        
        start_time = time.time()
        
        # データロード
        df = loader.load_training_data(symbol, start_date, end_date)
        print(f"Loaded {len(df)} records")
        
        # 特徴量エンジニアリング
        df = feature_engineer.engineer_features(df)
        
        # 訓練/テスト分割
        split_idx = int(len(df) * 0.8)
        train_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()
        
        # 訓練
        train_result = strategy.train(train_df)
        
        # 予測
        signals, confidence = strategy.predict(test_df)
        
        # バックテスト
        metrics = strategy.backtest(test_df, signals, confidence)
        
        exec_time = time.time() - start_time
        
        print(f"\n✓ Order Flow Imbalance Strategy completed in {exec_time:.2f} seconds")
        print(f"  Total Return: {metrics.get('total_return', 0):.2f}%")
        print(f"  Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}")
        print(f"  Max Drawdown: {metrics.get('max_drawdown', 0):.2f}%")
        print(f"  Total Trades: {metrics.get('total_trades', 0)}")
        
        results['order_flow_imbalance'] = {
            'result': {'status': 'success', 'metrics': metrics},
            'execution_time': exec_time
        }
    except Exception as e:
        exec_time = time.time() - start_time
        print(f"\n✗ Order Flow Imbalance Strategy failed after {exec_time:.2f} seconds: {e}")
        results['order_flow_imbalance'] = {
            'result': {'status': 'error', 'error': str(e)},
            'execution_time': exec_time
        }
    finally:
        loader.close()
    
    # 4. Mean Reversion Strategy
    loader = MarketDataLoader()
    feature_engineer = FeatureEngineer()
    strategy = MeanReversionStrategy()
    
    try:
        print(f"\n{'='*70}")
        print(f"Running Mean Reversion Strategy Backtest...")
        print(f"{'='*70}")
        
        start_time = time.time()
        
        # データロード
        df = loader.load_training_data(symbol, start_date, end_date)
        print(f"Loaded {len(df)} records")
        
        # 特徴量エンジニアリング
        df = feature_engineer.engineer_features(df)
        
        # 訓練/テスト分割
        split_idx = int(len(df) * 0.8)
        train_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()
        
        # 訓練
        train_result = strategy.train(train_df)
        
        # 予測
        signals, confidence = strategy.predict(test_df)
        
        # バックテスト
        metrics = strategy.backtest(test_df, signals, confidence)
        
        exec_time = time.time() - start_time
        
        print(f"\n✓ Mean Reversion Strategy completed in {exec_time:.2f} seconds")
        print(f"  Total Return: {metrics.get('total_return', 0):.2f}%")
        print(f"  Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}")
        print(f"  Max Drawdown: {metrics.get('max_drawdown', 0):.2f}%")
        print(f"  Total Trades: {metrics.get('total_trades', 0)}")
        
        results['mean_reversion'] = {
            'result': {'status': 'success', 'metrics': metrics},
            'execution_time': exec_time
        }
    except Exception as e:
        exec_time = time.time() - start_time
        print(f"\n✗ Mean Reversion Strategy failed after {exec_time:.2f} seconds: {e}")
        results['mean_reversion'] = {
            'result': {'status': 'error', 'error': str(e)},
            'execution_time': exec_time
        }
    finally:
        loader.close()
    
    # 5. Multi-Timeframe Strategy
    loader = MarketDataLoader()
    feature_engineer = FeatureEngineer()
    strategy = MultiTimeframeStrategy()
    
    try:
        print(f"\n{'='*70}")
        print(f"Running Multi-Timeframe Strategy Backtest...")
        print(f"{'='*70}")
        
        start_time = time.time()
        
        # データロード
        df = loader.load_training_data(symbol, start_date, end_date)
        print(f"Loaded {len(df)} records")
        
        # 特徴量エンジニアリング
        df = feature_engineer.engineer_features(df)
        
        # 訓練/テスト分割
        split_idx = int(len(df) * 0.8)
        train_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()
        
        # 訓練
        train_result = strategy.train(train_df)
        
        # 予測
        signals, confidence = strategy.predict(test_df)
        
        # バックテスト
        metrics = strategy.backtest(test_df, signals, confidence)
        
        exec_time = time.time() - start_time
        
        print(f"\n✓ Multi-Timeframe Strategy completed in {exec_time:.2f} seconds")
        print(f"  Total Return: {metrics.get('total_return', 0):.2f}%")
        print(f"  Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}")
        print(f"  Max Drawdown: {metrics.get('max_drawdown', 0):.2f}%")
        print(f"  Total Trades: {metrics.get('total_trades', 0)}")
        
        results['multi_timeframe'] = {
            'result': {'status': 'success', 'metrics': metrics},
            'execution_time': exec_time
        }
    except Exception as e:
        exec_time = time.time() - start_time
        print(f"\n✗ Multi-Timeframe Strategy failed after {exec_time:.2f} seconds: {e}")
        results['multi_timeframe'] = {
            'result': {'status': 'error', 'error': str(e)},
            'execution_time': exec_time
        }
    finally:
        loader.close()
    
    # 6. Spot Arbitrage Strategy
    result, exec_time = run_backtest_with_timing(
        "Spot Arbitrage Strategy",
        run_spot_arbitrage_backtest,
        fx_symbol=symbol,
        spot_symbol=symbol2,
        start_date=start_date,
        end_date=end_date
    )
    results['spot_arbitrage'] = {
        'result': result,
        'execution_time': exec_time
    }
    
    # 7. Limit Order Mean Reversion Strategy
    result, exec_time = run_backtest_with_timing(
        "Limit Order Mean Reversion Strategy",
        run_limit_order_mean_reversion_backtest,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date
    )
    results['limit_order_mean_reversion'] = {
        'result': result,
        'execution_time': exec_time
    }
    
    # 結果サマリー
    total_time = time.time() - total_start_time
    
    print(f"\n{'='*70}")
    print(f"BACKTEST TIMING SUMMARY")
    print(f"{'='*70}")
    print(f"Total Execution Time: {total_time:.2f} seconds ({total_time/60:.2f} minutes)")
    print(f"\nIndividual Strategy Times:")
    
    for strategy_name, data in results.items():
        status = "✓" if data['result'].get('status') == 'success' else "✗"
        print(f"  {status} {strategy_name.replace('_', ' ').title()}: {data['execution_time']:.2f} seconds")
    
    print(f"\nPerformance Summary:")
    print(f"{'Strategy':<30} {'Time (s)':<12} {'Return (%)':<12} {'Sharpe':<12} {'Trades':<10}")
    print("-" * 80)
    
    for strategy_name, data in results.items():
        exec_time = data['execution_time']
        if data['result'].get('status') == 'success':
            metrics = data['result'].get('metrics', {})
            return_val = metrics.get('total_return', 0)
            sharpe = metrics.get('sharpe_ratio', 0)
            trades = metrics.get('total_trades', 0)
            print(f"{strategy_name.replace('_', ' ').title():<30} {exec_time:<12.2f} {return_val:<12.2f} {sharpe:<12.2f} {trades:<10}")
        else:
            print(f"{strategy_name.replace('_', ' ').title():<30} {exec_time:<12.2f} {'ERROR':<12} {'-':<12} {'-':<10}")
    
    print(f"{'='*80}\n")
    
    return results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Run all strategy backtests with timing')
    parser.add_argument('--symbol', type=str, default='G_FX_BTCJPY', help='First symbol')
    parser.add_argument('--symbol2', type=str, default='B_FX_BTCJPY', help='Second symbol')
    parser.add_argument('--days', type=float, help='Number of days to backtest')
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
    
    results = run_all_backtests(
        symbol=args.symbol,
        symbol2=args.symbol2,
        start_date=start_date,
        end_date=end_date,
        days=args.days
    )

