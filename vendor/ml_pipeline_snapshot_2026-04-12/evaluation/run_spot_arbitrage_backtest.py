"""
Spot Arbitrage Backtest Execution Script
現物アービトラージ戦略のバックテストを実行
"""
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.spot_arbitrage_data_loader import SpotArbitrageDataLoader
from data.spot_arbitrage_feature_engineering import SpotArbitrageFeatureEngineer
from strategy.spot_arbitrage_strategy import SpotArbitrageStrategy
from evaluation.spot_arbitrage_backtester import SpotArbitrageBacktester
from config.settings import DatabaseConfig, ModelConfig, BacktestConfig


def run_spot_arbitrage_backtest(
    fx_symbol: str = "G_FX_BTCJPY",
    spot_symbol: str = "B_FX_BTCJPY",
    start_date: datetime = None,
    end_date: datetime = None,
    use_trained_model: bool = False,
    model_version: int = None
):
    """
    現物アービトラージ戦略のバックテストを実行
    
    Args:
        fx_symbol: FXシンボル（デフォルト: G_FX_BTCJPY）
        spot_symbol: 現物シンボル（デフォルト: B_FX_BTCJPY）
        start_date: 開始日時
        end_date: 終了日時
        use_trained_model: Trueの場合、訓練済みモデルを使用（現在は未実装）
        model_version: 使用するモデルのバージョン
    """
    loader = SpotArbitrageDataLoader()
    feature_engineer = SpotArbitrageFeatureEngineer()
    strategy = SpotArbitrageStrategy(fx_symbol=fx_symbol, spot_symbol=spot_symbol)
    backtester = SpotArbitrageBacktester()
    
    try:
        # 日付の設定
        if end_date is None:
            end_date = datetime.now()
        if start_date is None:
            start_date = end_date - timedelta(days=1)
        
        print(f"\n{'='*70}")
        print(f"Spot Arbitrage Backtest: {fx_symbol} (FX) vs {spot_symbol} (Spot)")
        print(f"Period: {start_date} to {end_date}")
        print(f"{'='*70}\n")
        
        # データロード
        print("Loading spot arbitrage data...")
        df = loader.load_spot_arbitrage_training_data(fx_symbol, spot_symbol, start_date, end_date)
        
        if len(df) == 0:
            raise ValueError("No data available for the specified period")
        
        print(f"Loaded {len(df)} records")
        
        # 特徴量エンジニアリング
        print("Engineering features...")
        df = feature_engineer.engineer_features(df)
        
        # モデルの訓練または読み込み
        if use_trained_model:
            print("Loading trained model...")
            raise NotImplementedError("Loading trained models is not yet implemented")
        else:
            print("Training model on training period...")
            # 訓練期間とテスト期間を分割
            split_idx = int(len(df) * 0.8)
            train_df = df.iloc[:split_idx].copy()
            test_df = df.iloc[split_idx:].copy()
            
            # 訓練データでラベル生成
            print("Generating labels...")
            X_train, y_train = strategy.generate_labels(train_df)
            
            if len(X_train) == 0:
                raise ValueError("No training samples generated")
            
            # モデル訓練
            strategy.train(train_df)
            
            print(f"Model trained on {len(X_train)} samples")
            print(f"Feature columns: {len(strategy.model.feature_columns)}")
        
        # テストデータで予測
        print("Generating predictions on test period...")
        signals, confidence = strategy.predict(test_df)
        
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
            fx_symbol=fx_symbol,
            spot_symbol=spot_symbol,
            confidence_threshold=config.CONFIDENCE_THRESHOLD
        )
        
        # 結果表示
        print("\n" + "="*70)
        print("SPOT ARBITRAGE BACKTEST RESULTS")
        print("="*70)
        print(f"Symbols: {fx_symbol} (FX) vs {spot_symbol} (Spot)")
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
            'fx_symbol': fx_symbol,
            'spot_symbol': spot_symbol,
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
    
    parser = argparse.ArgumentParser(description='Run spot arbitrage backtest')
    parser.add_argument('--fx-symbol', type=str, default='G_FX_BTCJPY', help='FX symbol')
    parser.add_argument('--spot-symbol', type=str, default='B_FX_BTCJPY', help='Spot symbol')
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
    
    result = run_spot_arbitrage_backtest(
        fx_symbol=args.fx_symbol,
        spot_symbol=args.spot_symbol,
        start_date=start_date,
        end_date=end_date
    )
    
    if result['status'] == 'success':
        print("\nSpot arbitrage backtest completed successfully!")
    else:
        print(f"\nSpot arbitrage backtest failed: {result.get('error', 'Unknown error')}")
        sys.exit(1)

