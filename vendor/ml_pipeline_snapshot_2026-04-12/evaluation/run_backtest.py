"""
Backtest Execution Script
訓練済みモデルまたは新規訓練モデルを使ってバックテストを実行
"""
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# パスを追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.data_loader import MarketDataLoader
from data.feature_engineering import FeatureEngineer
from models.momentum_model import MomentumModel
from evaluation.backtester import Backtester
from training.daily_trainer import DailyTrainer
from config.settings import DatabaseConfig, ModelConfig, BacktestConfig


def run_backtest_with_model(
    symbol: str = "G_FX_BTCJPY",
    start_date: datetime = None,
    end_date: datetime = None,
    use_trained_model: bool = False,
    model_version: int = None,
    show_trades: bool = False
):
    """
    バックテストを実行
    
    Args:
        symbol: 銘柄名
        start_date: 開始日時
        end_date: 終了日時
        use_trained_model: Trueの場合、訓練済みモデルを使用（現在は未実装）
        model_version: 使用するモデルのバージョン
    """
    loader = MarketDataLoader()
    feature_engineer = FeatureEngineer()
    backtester = Backtester()
    
    try:
        # 日付の設定
        if end_date is None:
            end_date = datetime.now()
        if start_date is None:
            start_date = end_date - timedelta(days=1)
        
        print(f"\n{'='*70}")
        print(f"Backtest: {symbol}")
        print(f"Period: {start_date} to {end_date}")
        print(f"{'='*70}\n")
        
        # データロード
        print("Loading data...")
        df = loader.load_training_data(symbol, start_date, end_date)
        
        if len(df) == 0:
            raise ValueError("No data available for the specified period")
        
        print(f"Loaded {len(df)} records")
        
        # 特徴量エンジニアリング（全データに対して一度だけ実行）
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
            # 前半50%を訓練、後半50%をテスト
            split_idx = int(len(df) * 0.5)
            train_df = df.iloc[:split_idx].copy()
            test_df = df.iloc[split_idx:].copy()
            
            # 訓練データでラベル生成
            trainer = DailyTrainer()
            X_train, y_train = trainer._generate_labels(train_df)
            
            if len(X_train) == 0:
                raise ValueError("No training samples generated")
            
            # モデル訓練
            model = MomentumModel()
            # _generate_labelsで使用された特徴量カラムを取得
            # (mid_priceとsymbolを除いたすべてのカラム)
            feature_cols_from_train = [col for col in train_df.columns 
                                      if col not in ['symbol', 'mid_price']]
            model.feature_columns = feature_cols_from_train
            model.train(X_train, y_train)
            
            # 特徴量カラムの数を確認
            print(f"Training features: {len(model.feature_columns)}, X_train shape: {X_train.shape}")
            
            print(f"Model trained on {len(X_train)} samples")
            print(f"Feature columns: {len(model.feature_columns)}")
        
        # テストデータで予測
        print("Generating predictions on test period...")
        feature_cols = model.feature_columns
        
        # 特徴量カラムが存在するか確認
        missing_cols = [col for col in feature_cols if col not in test_df.columns]
        if missing_cols:
            raise ValueError(f"Missing feature columns in test data: {missing_cols}")
        
        # 特徴量の順序を確認（model.feature_columnsの順序に合わせる）
        X_test = test_df[feature_cols].values
        
        # 特徴量数の確認
        if X_test.shape[1] != len(model.feature_columns):
            raise ValueError(
                f"Feature count mismatch. Expected {len(model.feature_columns)}, "
                f"got {X_test.shape[1]}"
            )
        
        # NaNを含む行を削除
        valid_mask = ~(pd.isna(X_test).any(axis=1))
        test_df = test_df[valid_mask]
        X_test = X_test[valid_mask]
        
        if len(X_test) == 0:
            raise ValueError("No valid test data after feature engineering")
        
        # 予測
        predictions, probabilities = model.predict(X_test)
        
        # シグナルと信頼度の準備
        # predictions: 0=SELL, 1=HOLD, 2=BUY -> -1=SELL, 0=HOLD, 1=BUYに変換
        signals = pd.Series(predictions - 1, index=test_df.index)
        
        # 信頼度は最大確率を使用
        confidence = pd.Series(probabilities.max(axis=1), index=test_df.index)
        
        # バックテスト実行
        print("Running backtest...")
        config = BacktestConfig()
        metrics = backtester.run(
            test_df,
            signals,
            confidence,
            confidence_threshold=config.CONFIDENCE_THRESHOLD
        )
        
        # 結果表示
        print("\n" + "="*70)
        print("BACKTEST RESULTS")
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
                    price = row['price']
                    quantity = row['quantity']
                    capital = row['capital']
                    
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
                            entry_price = last_entry['price']
                            entry_quantity = last_entry['quantity']
                            
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
    
    parser = argparse.ArgumentParser(description='Run backtest')
    parser.add_argument('--symbol', type=str, default='G_FX_BTCJPY', help='Symbol to backtest')
    parser.add_argument('--days', type=float, default=1, help='Number of days to backtest')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--show-trades', action='store_true', help='Show detailed trade history')
    
    args = parser.parse_args()
    
    start_date = None
    end_date = None
    
    if args.start_date:
        # 日付形式を自動判定
        try:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
            except ValueError:
                print(f"Error: Invalid start date format: {args.start_date}")
                sys.exit(1)
    
    if args.end_date:
        # 日付形式を自動判定
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
    
    result = run_backtest_with_model(
        symbol=args.symbol,
        start_date=start_date,
        end_date=end_date,
        show_trades=args.show_trades
    )
    
    if result['status'] == 'success':
        print("\nBacktest completed successfully!")
    else:
        print(f"\nBacktest failed: {result.get('error', 'Unknown error')}")
        sys.exit(1)

