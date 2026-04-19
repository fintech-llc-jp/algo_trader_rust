"""
Market Order vs Limit Order Comparison
成り行き注文と指値注文のバックテスト結果を比較
"""
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.data_loader import MarketDataLoader
from data.exch_sim_data_loader import ExchSimDataLoader
from data.feature_engineering import FeatureEngineer
from models.momentum_model import MomentumModel
from evaluation.backtester import Backtester
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


def compare_market_vs_limit_order(
    symbol: str = "G_FX_BTCJPY",
    start_date: datetime = None,
    end_date: datetime = None,
    limit_order_timeout_seconds: int = 5
):
    """
    成り行き注文と指値注文のバックテスト結果を比較
    
    Args:
        symbol: シンボル
        start_date: 開始日時
        end_date: 終了日時
        limit_order_timeout_seconds: 指値注文のタイムアウト時間（秒）
    """
    loader = MarketDataLoader()
    exch_sim_loader = ExchSimDataLoader()
    feature_engineer = FeatureEngineer()
    model = MomentumModel()
    
    try:
        # 約定履歴データをロード
        print("Loading execution history...")
        executions_df = exch_sim_loader.load_executions(symbol, start_date, end_date)
        print(f"Loaded {len(executions_df)} executions")
        # 日付の設定
        if end_date is None:
            end_date = datetime.now()
        if start_date is None:
            start_date = end_date - timedelta(days=1)
        
        print(f"\n{'='*80}")
        print(f"MARKET ORDER vs LIMIT ORDER COMPARISON")
        print(f"{'='*80}")
        print(f"Symbol: {symbol}")
        print(f"Period: {start_date} to {end_date}")
        print(f"Limit Order Timeout: {limit_order_timeout_seconds} seconds")
        print(f"{'='*80}\n")
        
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
        
        # モデルの訓練
        print("Training model on training period...")
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
        
        # シグナルと信頼度をSeriesに変換
        signals = predictions - 1
        signals_series = pd.Series(signals, index=test_df.index)
        confidence_series = pd.Series(probabilities.max(axis=1), index=test_df.index)
        
        config = BacktestConfig()
        
        # 1. 成り行き注文のバックテスト
        print("\n" + "="*80)
        print("Running Market Order Backtest...")
        print("="*80)
        market_backtester = Backtester()
        start_time = time.time()
        market_metrics = market_backtester.run(
            test_df,
            signals_series,
            confidence_series,
            confidence_threshold=config.CONFIDENCE_THRESHOLD
        )
        market_exec_time = time.time() - start_time
        
        # 2. 指値注文のバックテスト
        print("\n" + "="*80)
        print("Running Limit Order Backtest...")
        print("="*80)
        
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
        
        limit_backtester = LimitOrderBacktester(
            limit_order_timeout_seconds=limit_order_timeout_seconds,
            executions_df=test_executions_df
        )
        start_time = time.time()
        limit_metrics = limit_backtester.run(
            test_df,
            signals_series,
            confidence_series,
            confidence_threshold=config.CONFIDENCE_THRESHOLD,
            executions_df=test_executions_df
        )
        limit_exec_time = time.time() - start_time
        
        # 結果の比較
        print("\n" + "="*80)
        print("COMPARISON RESULTS")
        print("="*80)
        print(f"Test Period: {test_df.index[0]} to {test_df.index[-1]}")
        print(f"Test Samples: {len(test_df)}")
        print(f"\n{'Metric':<30} {'Market Order':<20} {'Limit Order':<20} {'Difference':<20}")
        print("-" * 90)
        
        metrics_to_compare = [
            ('Total Return (%)', 'total_return', '{:.2f}%'),
            ('Sharpe Ratio', 'sharpe_ratio', '{:.2f}'),
            ('Max Drawdown (%)', 'max_drawdown', '{:.2f}%'),
            ('Final Equity (JPY)', 'final_equity', '{:,.0f}'),
            ('Total Trades', 'total_trades', '{:d}'),
            ('Win Rate (%)', 'win_rate', '{:.2f}%'),
            ('Avg Win (JPY)', 'avg_win', '{:,.0f}'),
            ('Avg Loss (JPY)', 'avg_loss', '{:,.0f}'),
            ('Profit Factor', 'profit_factor', '{:.2f}'),
        ]
        
        for metric_name, metric_key, format_str in metrics_to_compare:
            market_val = market_metrics.get(metric_key, 0)
            limit_val = limit_metrics.get(metric_key, 0)
            diff = limit_val - market_val
            
            if 'Return' in metric_name or 'Drawdown' in metric_name or 'Win Rate' in metric_name:
                diff_str = f"{diff:+.2f}%"
            elif 'Equity' in metric_name or 'Win' in metric_name or 'Loss' in metric_name:
                diff_str = f"{diff:+,.0f}"
            else:
                diff_str = f"{diff:+.2f}"
            
            print(f"{metric_name:<30} {format_str.format(market_val):<20} {format_str.format(limit_val):<20} {diff_str:<20}")
        
        # 指値注文特有の統計
        print("\n" + "-" * 90)
        print("Limit Order Specific Statistics:")
        print(f"  Avg Fill Delay: {limit_metrics.get('avg_fill_delay_seconds', 0):.2f} seconds")
        print(f"  Limit Order Fill Rate: {limit_metrics.get('limit_order_fill_rate', 0):.2f}%")
        
        # 実行時間の比較
        print("\n" + "-" * 90)
        print("Execution Time:")
        print(f"  Market Order: {market_exec_time:.2f} seconds")
        print(f"  Limit Order: {limit_exec_time:.2f} seconds")
        print(f"  Difference: {limit_exec_time - market_exec_time:+.2f} seconds")
        
        # 改善率の計算
        print("\n" + "-" * 90)
        print("Improvement Analysis:")
        market_return = market_metrics.get('total_return', 0)
        limit_return = limit_metrics.get('total_return', 0)
        
        if market_return != 0:
            return_improvement = ((limit_return - market_return) / abs(market_return)) * 100
            print(f"  Return Improvement: {return_improvement:+.2f}%")
        
        market_sharpe = market_metrics.get('sharpe_ratio', 0)
        limit_sharpe = limit_metrics.get('sharpe_ratio', 0)
        
        if market_sharpe != 0:
            sharpe_improvement = ((limit_sharpe - market_sharpe) / abs(market_sharpe)) * 100
            print(f"  Sharpe Ratio Improvement: {sharpe_improvement:+.2f}%")
        
        market_trades = market_metrics.get('total_trades', 0)
        limit_trades = limit_metrics.get('total_trades', 0)
        
        if market_trades > 0:
            trade_reduction = ((limit_trades - market_trades) / market_trades) * 100
            print(f"  Trade Count Change: {trade_reduction:+.2f}%")
        
        print("="*80 + "\n")
        
        return {
            'status': 'success',
            'symbol': symbol,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'market_order': market_metrics,
            'limit_order': limit_metrics,
            'market_exec_time': market_exec_time,
            'limit_exec_time': limit_exec_time
        }
        
    except Exception as e:
        print(f"\nComparison failed: {e}")
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
    
    parser = argparse.ArgumentParser(description='Compare market order vs limit order backtest')
    parser.add_argument('--symbol', type=str, default='G_FX_BTCJPY', help='Symbol to backtest')
    parser.add_argument('--days', type=float, default=1, help='Number of days to backtest')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--timeout', type=int, default=5, help='Limit order timeout in seconds')
    
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
    
    result = compare_market_vs_limit_order(
        symbol=args.symbol,
        start_date=start_date,
        end_date=end_date,
        limit_order_timeout_seconds=args.timeout
    )
    
    if result['status'] == 'success':
        print("\nComparison completed successfully!")
    else:
        print(f"\nComparison failed: {result.get('error', 'Unknown error')}")
        sys.exit(1)

