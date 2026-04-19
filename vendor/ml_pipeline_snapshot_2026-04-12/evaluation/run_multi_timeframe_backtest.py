"""
Multi Timeframe Backtest Execution Script
マルチタイムフレーム戦略のバックテストを実行
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
from strategy.multi_timeframe_strategy import MultiTimeframeStrategy
from evaluation.backtester import Backtester
from evaluation.limit_order_backtester import LimitOrderBacktester
from config.settings import DatabaseConfig, ModelConfig, BacktestConfig


def run_multi_timeframe_backtest(
    symbol: str = "G_FX_BTCJPY",
    start_date: datetime = None,
    end_date: datetime = None,
    show_trades: bool = False,
    timeframes: list = None,
    trend_consensus_ratio: float = 1.0,
    label_threshold: float = None,
    confidence_threshold: float = None,
    invert_signals: bool = False,
    use_limit_orders: bool = False,
    limit_order_timeout_seconds: int = 60
):
    """
    マルチタイムフレーム戦略のバックテストを実行
    
    Args:
        symbol: シンボル
        start_date: 開始日時
        end_date: 終了日時
    """
    loader = MarketDataLoader()
    feature_engineer = FeatureEngineer()
    # タイムフレームが指定されていない場合はデフォルト値を使用
    if timeframes is None:
        timeframes = [1, 5, 30]  # デフォルト: 1秒、5秒、30秒
    strategy = MultiTimeframeStrategy(
        timeframes=timeframes,
        trend_consensus_ratio=trend_consensus_ratio,
        label_threshold=label_threshold
    )
    # タイムフレームの表示用フォーマット
    def format_timeframe(tf):
        if tf >= 3600:
            return f"{tf//3600}h"
        elif tf >= 60:
            return f"{tf//60}min"
        else:
            return f"{tf}s"
    tf_display = [format_timeframe(tf) for tf in timeframes]
    print(f"Timeframes: {timeframes} seconds ({', '.join(tf_display)})")
    
    try:
        # 日付の設定
        if end_date is None:
            end_date = datetime.now()
        if start_date is None:
            start_date = end_date - timedelta(days=1)
        
        print(f"\n{'='*70}")
        print(f"Multi Timeframe Backtest: {symbol}")
        print(f"Period: {start_date} to {end_date}")
        print(f"{'='*70}\n")
        
        # データロード
        print("Loading data...")
        df = loader.load_training_data(symbol, start_date, end_date)
        
        if len(df) == 0:
            raise ValueError("No data available for the specified period")
        
        print(f"Loaded {len(df)} records")
        
        # 特徴量エンジニアリング
        print("Engineering features...")
        df = feature_engineer.engineer_features(df)
        
        # 訓練/テスト分割
        print("Splitting data into training and test sets...")
        split_idx = int(len(df) * 0.5)  # 50:50に分割
        train_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()
        
        print(f"Training samples: {len(train_df)}, Test samples: {len(test_df)}")
        
        # 訓練
        print("Training model...")
        train_result = strategy.train(train_df)
        print(f"Model trained: Accuracy={train_result.get('accuracy', 0):.2%}")
        
        # 予測
        print("Generating predictions...")
        signals, confidence = strategy.predict(test_df)
        
        # シグナルを反転する場合
        if invert_signals:
            print("Inverting signals (BUY <-> SELL)...")
            signals = -signals  # 1 -> -1, -1 -> 1, 0 -> 0
        
        # バックテスト
        print("Running backtest...")
        if use_limit_orders:
            print(f"Using limit orders (timeout: {limit_order_timeout_seconds}s)")
            print("Loading execution history...")
            exch_sim_loader = ExchSimDataLoader()
            executions_df = exch_sim_loader.load_executions(symbol, test_df.index[0], test_df.index[-1])
            print(f"Loaded {len(executions_df)} executions")
            backtester = LimitOrderBacktester(
                limit_order_timeout_seconds=limit_order_timeout_seconds,
                executions_df=executions_df
            )
        else:
            print("Using market orders")
            backtester = Backtester()
        
        # 信頼度の閾値（指定されていない場合はデフォルト値を使用）
        conf_threshold = confidence_threshold if confidence_threshold is not None else strategy.backtest_config.CONFIDENCE_THRESHOLD
        
        if use_limit_orders:
            metrics = backtester.run(
                test_df,
                signals,
                confidence,
                confidence_threshold=conf_threshold,
                executions_df=executions_df
            )
        else:
            metrics = backtester.run(
                test_df,
                signals,
                confidence,
                confidence_threshold=conf_threshold
            )
        
        # 結果表示
        print("\n" + "="*70)
        print("MULTI TIMEFRAME BACKTEST RESULTS")
        print("="*70)
        print(f"Symbol: {symbol}")
        print(f"Test Period: {test_df.index[0]} to {test_df.index[-1]}")
        print(f"Test Samples: {len(test_df)}")
        print(f"\nPerformance Metrics:")
        print(f"  Total Return: {metrics.get('total_return', 0):.2f}%")
        print(f"  Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}")
        print(f"  Max Drawdown: {metrics.get('max_drawdown', 0):.2f}%")
        print(f"  Final Equity: {metrics.get('final_equity', 0):,.0f} JPY")
        print(f"\nTrading Statistics:")
        print(f"  Total Trades: {metrics.get('total_trades', 0)}")
        print(f"  Win Rate: {metrics.get('win_rate', 0):.2f}%")
        print(f"  Avg Win: {metrics.get('avg_win', 0):,.0f} JPY")
        print(f"  Avg Loss: {metrics.get('avg_loss', 0):,.0f} JPY")
        print(f"  Profit Factor: {metrics.get('profit_factor', 0):.2f}")
        print(f"\nCost Analysis:")
        print(f"  Avg Spread: {metrics.get('avg_spread_bps', 0):.2f} bps ({metrics.get('avg_spread_pct', 0):.4f}%)")
        print(f"  Total Commission: {metrics.get('total_commission', 0):,.0f} JPY")
        print(f"  Total Slippage Cost: {metrics.get('total_slippage_cost', 0):,.0f} JPY")
        print(f"  Avg Cost per Round Trip: {metrics.get('avg_cost_per_round_trip_pct', 0):.4f}%")
        print("="*70 + "\n")
        
        # トレード履歴の表示
        if show_trades:
            trades_df = backtester.get_trades()
            if len(trades_df) > 0:
                print("\n" + "="*90)
                print("TRADE HISTORY")
                print("="*90)
                
                # 時系列順にソート
                trades_df = trades_df.sort_index()
                
                # ヘッダー
                print(f"\n{'#':<4} {'Timestamp':<20} {'Action':<12} {'Price':<12} {'Quantity':<12} {'PNL':<15} {'Capital':<12}")
                print("-"*90)
                
                trade_num = 1
                open_positions = 0
                
                for idx, row in trades_df.iterrows():
                    timestamp = row['timestamp']
                    if isinstance(timestamp, pd.Timestamp):
                        timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        timestamp_str = str(timestamp)[:19]
                    
                    action = row['action']
                    # LimitOrderBacktesterの場合はexecution_price、Backtesterの場合はprice
                    price = row.get('execution_price', row.get('price', 0))
                    quantity = row.get('quantity', 0)
                    capital = row.get('capital', 0)
                    
                    # PNLの表示
                    if 'pnl' in row and pd.notna(row['pnl']):
                        pnl = row['pnl']
                        pnl_str = f"{pnl:>14,.0f} JPY"
                        if pnl > 0:
                            pnl_str = f"+{pnl:>13,.0f} JPY"
                    else:
                        pnl_str = "-"
                    
                    print(f"{trade_num:<4} {timestamp_str:<20} {action:<12} {price:>11,.0f} {quantity:>11.6f} {pnl_str:<15} {capital:>11,.0f}")
                    
                    if action in ['BUY', 'SHORT']:
                        open_positions += 1
                    elif action in ['SELL', 'COVER_SHORT']:
                        open_positions -= 1
                        trade_num += 1
                
                print("-"*90)
                
                # 未決済ポジションの詳細表示
                if open_positions > 0:
                    equity_curve_df = backtester.get_equity_curve()
                    if len(equity_curve_df) > 0:
                        final_equity = equity_curve_df['equity'].iloc[-1]
                        final_capital = trades_df['capital'].iloc[-1] if len(trades_df) > 0 else backtester.initial_capital
                        unrealized_pnl = final_equity - final_capital
                        
                        # 最後のエントリートレードを取得
                        last_entry = None
                        if len(trades_df[trades_df['action'] == 'BUY']) > 0:
                            last_entry = trades_df[trades_df['action'] == 'BUY'].iloc[-1]
                            position_type = 'LONG'
                        elif len(trades_df[trades_df['action'] == 'SHORT']) > 0:
                            last_entry = trades_df[trades_df['action'] == 'SHORT'].iloc[-1]
                            position_type = 'SHORT'
                        
                        if last_entry is not None:
                            # LimitOrderBacktesterの場合はexecution_price、Backtesterの場合はprice
                            entry_price = last_entry.get('execution_price', last_entry.get('price', 0))
                            entry_quantity = last_entry.get('quantity', 0)
                            
                            # 最後のデータから価格を取得
                            last_row = test_df.iloc[-1]
                            
                            if position_type == 'LONG':
                                current_bid_price = last_row.get('bid_price_1', last_row['mid_price'])
                                estimated_commission = entry_quantity * current_bid_price * backtester.commission_rate
                                unrealized_pnl_with_commission = (current_bid_price - entry_price) * entry_quantity - estimated_commission
                                
                                print(f"\n{'='*90}")
                                print("OPEN POSITION SUMMARY (LONG)")
                                print(f"{'='*90}")
                                print(f"  Entry Price:        {entry_price:>15,.0f} JPY (ASK price)")
                                print(f"  Entry Quantity:     {entry_quantity:>15.6f} BTC")
                                print(f"  Current Bid Price:  {current_bid_price:>15,.0f} JPY (sell price)")
                                print(f"  Cash (Capital):     {final_capital:>15,.0f} JPY")
                                print(f"  Unrealized P&L:     {unrealized_pnl_with_commission:>15,.0f} JPY")
                                print(f"  Total Equity:       {final_equity:>15,.0f} JPY")
                                print(f"  (Final Equity = Cash + Unrealized P&L)")
                                print(f"{'='*90}\n")
                            else:  # SHORT
                                current_ask_price = last_row.get('ask_price_1', last_row['mid_price'])
                                estimated_commission = entry_quantity * current_ask_price * backtester.commission_rate
                                unrealized_pnl_with_commission = (entry_price - current_ask_price) * entry_quantity - estimated_commission
                                
                                print(f"\n{'='*90}")
                                print("OPEN POSITION SUMMARY (SHORT)")
                                print(f"{'='*90}")
                                print(f"  Entry Price:        {entry_price:>15,.0f} JPY (BID price)")
                                print(f"  Entry Quantity:     {entry_quantity:>15.6f} BTC")
                                print(f"  Current Ask Price:  {current_ask_price:>15,.0f} JPY (cover price)")
                                print(f"  Cash (Capital):     {final_capital:>15,.0f} JPY")
                                print(f"  Unrealized P&L:     {unrealized_pnl_with_commission:>15,.0f} JPY")
                                print(f"  Total Equity:       {final_equity:>15,.0f} JPY")
                                print(f"  (Final Equity = Cash + Unrealized P&L)")
                                print(f"{'='*90}\n")
                
                print("="*90 + "\n")
            else:
                print("\nNo trades executed.\n")
        
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


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Run multi timeframe backtest')
    parser.add_argument('--symbol', type=str, default='G_FX_BTCJPY', help='Symbol to backtest')
    parser.add_argument('--days', type=float, default=1, help='Number of days to backtest')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--show-trades', action='store_true', help='Show detailed trade history')
    parser.add_argument('--timeframes', type=str, help='Comma-separated timeframes in seconds (e.g., "60,300,3600" for 1min,5min,1hour)')
    parser.add_argument('--trend-consensus-ratio', type=float, default=1.0, help='Trend consensus ratio (1.0=all match, 0.5=majority, default=1.0)')
    parser.add_argument('--label-threshold', type=float, help='Label generation threshold (default=0.0001)')
    parser.add_argument('--confidence-threshold', type=float, help='Confidence threshold for trading (default=0.7)')
    parser.add_argument('--invert-signals', action='store_true', help='Invert signals (BUY -> SELL, SELL -> BUY)')
    parser.add_argument('--use-limit-orders', action='store_true', help='Use limit orders (BUY at BID, SELL at ASK)')
    parser.add_argument('--limit-order-timeout', type=int, default=60, help='Limit order timeout in seconds (default=60)')
    
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
    
    # タイムフレームのパース
    timeframes = None
    if args.timeframes:
        try:
            timeframes = [int(tf.strip()) for tf in args.timeframes.split(',')]
            if len(timeframes) < 2:
                print("Error: At least 2 timeframes are required")
                sys.exit(1)
        except ValueError:
            print(f"Error: Invalid timeframes format: {args.timeframes}")
            print("Expected format: comma-separated integers (e.g., '60,300,3600')")
            sys.exit(1)
    
    result = run_multi_timeframe_backtest(
        symbol=args.symbol,
        start_date=start_date,
        end_date=end_date,
        show_trades=args.show_trades,
        timeframes=timeframes,
        trend_consensus_ratio=args.trend_consensus_ratio,
        label_threshold=args.label_threshold,
        confidence_threshold=args.confidence_threshold,
        invert_signals=args.invert_signals,
        use_limit_orders=args.use_limit_orders,
        limit_order_timeout_seconds=args.limit_order_timeout
    )
    
    if result['status'] == 'success':
        print("\nMulti timeframe backtest completed successfully!")
    else:
        print(f"\nMulti timeframe backtest failed: {result.get('error', 'Unknown error')}")
        sys.exit(1)

