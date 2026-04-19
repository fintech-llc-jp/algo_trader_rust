"""
Simple Training and Backtest Script
ExchSimデータベースからデータを読み取り、モデルをトレーニングし、バックテストを実行するシンプルなスクリプト

モード1: 訓練 + バックテスト
モード2: バックテストのみ（既存モデルを使用）
"""
import sys
import os
import argparse
import json
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Tuple

# .envファイルを読み込む（存在する場合）
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.exch_sim_data_loader import ExchSimDataLoader
from data.feature_engineering import FeatureEngineer
from data.configurable_feature_engineering import ConfigurableFeatureEngineer
from strategy.price_prediction_strategy import PricePredictionStrategy
from strategy.momentum_intensity_strategy import MomentumIntensityStrategy
from evaluation.backtester import Backtester
from evaluation.limit_order_backtester import LimitOrderBacktester
from evaluation.run_price_prediction_backtest import generate_signals_from_predictions
from config.settings import DatabaseConfig, ModelConfig, BacktestConfig
from models.price_prediction_model import PricePredictionModel
from models.momentum_intensity_model import MomentumIntensityModel


def parse_datetime(date_str: str) -> datetime:
    """文字列をdatetimeに変換（UTC）"""
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except ValueError:
        dt = datetime.fromisoformat(date_str)
    
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    return dt


def load_model_from_file_or_db(
    model_type: str,
    symbol: str,
    model_path: Optional[str] = None,
    model_name: Optional[str] = None,
    use_db_model: bool = False
):
    """
    モデルをファイルまたはDBからロード
    
    Args:
        model_type: モデルタイプ ("price_prediction" or "momentum_intensity")
        symbol: シンボル
        model_path: モデルファイルパス（指定された場合）
        model_name: モデル名（DBからロードする場合）
        use_db_model: DBからロードするか
    
    Returns:
        ロードされたモデルインスタンス
    """
    if model_path:
        # ファイルパスが指定されている場合
        if model_type == "price_prediction":
            return PricePredictionModel.load(model_path)
        elif model_type == "momentum_intensity":
            return MomentumIntensityModel.load(model_path)
        else:
            raise ValueError(f"Unsupported model type: {model_type}")
    
    elif use_db_model and model_name:
        # DBからロード
        from api.model_manager import ModelManager
        connection_string = DatabaseConfig.get_algo_trader_connection_string()
        model_manager = ModelManager(connection_string=connection_string, use_file_backend=False)
        return model_manager.load_model(model_name, model_type, symbol)
    
    else:
        # デフォルトパスからロード
        model_dir = ModelConfig.MODEL_DIR
        if model_type == "price_prediction":
            default_path = os.path.join(model_dir, f'price_prediction_{symbol}.joblib')
        elif model_type == "momentum_intensity":
            default_path = os.path.join(model_dir, f'momentum_intensity_{symbol}.joblib')
        else:
            raise ValueError(f"Unsupported model type: {model_type}")
        
        if os.path.exists(default_path):
            if model_type == "price_prediction":
                return PricePredictionModel.load(default_path)
            elif model_type == "momentum_intensity":
                return MomentumIntensityModel.load(default_path)
        else:
            raise FileNotFoundError(f"Model file not found: {default_path}")


def run_backtest_only(
    symbol: str,
    test_start_date: datetime,
    test_end_date: datetime,
    model_path_price: Optional[str] = None,
    model_path_momentum: Optional[str] = None,
    model_name: Optional[str] = None,
    use_db_model: bool = False,
    timeframes: list = [1, 5, 30],
    prediction_horizon: int = 60,
    price_change_threshold: float = 0.0001,
    use_limit_orders: bool = False,
    limit_order_timeout_seconds: int = 60,
    output_dir: Optional[str] = None,
    show_trades: bool = True,
    confidence_threshold: float = 0.7
) -> Dict:
    """
    モード2: 既存モデルを使用してバックテストのみを実行
    
    Args:
        confidence_threshold: 取引を実行するための最小信頼度閾値（デフォルト: 0.7）
                             値を下げるとより多くの取引が実行される
    
    Returns:
        バックテスト結果の辞書
    """
    print("="*70)
    print("BACKTEST ONLY MODE (Using Existing Models)")
    print("="*70)
    print(f"Symbol: {symbol}")
    print(f"Test Period: {test_start_date} to {test_end_date}")
    print()
    
    # データローダーと特徴量エンジニアの初期化
    data_loader = ExchSimDataLoader(use_connection_pool=True)
    
    # 特徴量エンジニアの設定
    feature_set_name = os.getenv('FEATURE_SET_NAME', 'standard_features')
    use_configurable = os.getenv('USE_CONFIGURABLE_FEATURES', 'true').lower() == 'true'
    
    if use_configurable:
        try:
            feature_engineer = ConfigurableFeatureEngineer(feature_set_name=feature_set_name)
            print(f"Using ConfigurableFeatureEngineer with feature set: {feature_set_name}")
        except Exception as e:
            print(f"Warning: Failed to initialize ConfigurableFeatureEngineer: {e}")
            print("Falling back to standard FeatureEngineer")
            feature_engineer = FeatureEngineer()
    else:
        feature_engineer = FeatureEngineer()
        print("Using standard FeatureEngineer")
    
    try:
        # テストデータのロード
        print(f"\nLoading test data from {test_start_date} to {test_end_date}...")
        test_df = data_loader.load_training_data(
            symbol,
            test_start_date,
            test_end_date,
            skip_min_samples_check=True
        )
        
        if len(test_df) == 0:
            raise ValueError(f"No test data available for {symbol} in the specified period")
        
        print(f"Loaded {len(test_df)} test records")
        
        # データの価格統計を確認
        if 'mid_price' in test_df.columns:
            print(f"\nTest data price statistics:")
            print(f"  mid_price: min={test_df['mid_price'].min():,.0f}, max={test_df['mid_price'].max():,.0f}, mean={test_df['mid_price'].mean():,.0f}")
            print(f"  mid_price unique values: {test_df['mid_price'].nunique()}")
            if 'bid_price_1' in test_df.columns:
                print(f"  bid_price_1: min={test_df['bid_price_1'].min():,.0f}, max={test_df['bid_price_1'].max():,.0f}")
            if 'ask_price_1' in test_df.columns:
                print(f"  ask_price_1: min={test_df['ask_price_1'].min():,.0f}, max={test_df['ask_price_1'].max():,.0f}")
        
        # 特徴量エンジニアリング
        print("Engineering features...")
        test_df = feature_engineer.engineer_features(test_df)
        
        # モデルのロード
        print("\nLoading models...")
        price_strategy = PricePredictionStrategy(
            timeframes=timeframes,
            prediction_horizon=prediction_horizon
        )
        
        momentum_strategy = MomentumIntensityStrategy(
            timeframes=timeframes,
            prediction_horizon=prediction_horizon
        )
        
        # 価格予測モデルのロード
        try:
            price_model = load_model_from_file_or_db(
                "price_prediction",
                symbol,
                model_path_price,
                model_name,
                use_db_model
            )
            price_strategy.model = price_model
            print(f"✓ Price prediction model loaded")
        except Exception as e:
            print(f"Warning: Failed to load price prediction model: {e}")
            print("Continuing without price prediction model...")
            price_strategy = None
        
        # モメンタム強度モデルのロード
        try:
            momentum_model = load_model_from_file_or_db(
                "momentum_intensity",
                symbol,
                model_path_momentum,
                model_name,
                use_db_model
            )
            momentum_strategy.model = momentum_model
            print(f"✓ Momentum intensity model loaded")
        except Exception as e:
            print(f"Warning: Failed to load momentum intensity model: {e}")
            print("Continuing without momentum intensity model...")
            momentum_strategy = None
        
        if price_strategy is None and momentum_strategy is None:
            raise ValueError("No models loaded. Cannot run backtest.")
        
        # 予測生成
        print("\nGenerating predictions...")
        price_predictions = None
        momentum_intensity = None
        
        if price_strategy and price_strategy.model:
            price_predictions = price_strategy.predict(test_df)
            print(f"Price predictions generated: {len(price_predictions)} predictions")
        
        if momentum_strategy and momentum_strategy.model:
            momentum_intensity = momentum_strategy.predict_intensity(test_df)
            print(f"Momentum intensity generated: {len(momentum_intensity)} predictions")
        
        # シグナル生成
        print("\nGenerating signals...")
        signals, confidence = generate_signals_from_predictions(
            test_df,
            price_predictions if price_predictions is not None else pd.Series(dtype=float),
            price_change_threshold=price_change_threshold,
            momentum_intensity=momentum_intensity,
            momentum_threshold=4,
            use_momentum=(momentum_intensity is not None),
            max_prediction_error_pct=0.5
        )
        
        print(f"Signals generated: {len(signals)} signals")
        print(f"  BUY: {int((signals == 1).sum())}, SELL: {int((signals == -1).sum())}, HOLD: {int((signals == 0).sum())}")
        print(f"  Confidence: min={confidence.min():.4f}, max={confidence.max():.4f}, mean={confidence.mean():.4f}")
        
        # バックテスト実行
        print("\nRunning backtest...")
        if use_limit_orders:
            executions_df = data_loader.load_executions(symbol, test_start_date, test_end_date)
            backtester = LimitOrderBacktester(
                initial_capital=10000000,
                commission_rate=0.0,
                limit_order_timeout_seconds=limit_order_timeout_seconds,
                executions_df=executions_df
            )
        else:
            backtester = Backtester(
                initial_capital=10000000,
                commission_rate=0.0
            )
        
        metrics = backtester.run(
            test_df,
            signals,
            confidence,
            confidence_threshold=confidence_threshold,
            fixed_quantity=0.01
        )
        
        # 結果の整理
        trades_df = backtester.get_trades()
        equity_curve_df = backtester.get_equity_curve()
        
        signal_counts = {
            'BUY': int((signals == 1).sum()),
            'SELL': int((signals == -1).sum()),
            'HOLD': int((signals == 0).sum())
        }
        total_signals = len(signals)
        signal_percentages = {
            'BUY': (signal_counts['BUY'] / total_signals * 100) if total_signals > 0 else 0.0,
            'SELL': (signal_counts['SELL'] / total_signals * 100) if total_signals > 0 else 0.0,
            'HOLD': (signal_counts['HOLD'] / total_signals * 100) if total_signals > 0 else 0.0
        }
        
        confidence_stats = {
            'mean': float(confidence.mean()) if len(confidence) > 0 else 0.0,
            'min': float(confidence.min()) if len(confidence) > 0 else 0.0,
            'max': float(confidence.max()) if len(confidence) > 0 else 0.0,
            'std': float(confidence.std()) if len(confidence) > 0 else 0.0
        }
        
        result = {
            "status": "success",
            "mode": "backtest_only",
            "symbol": symbol,
            "test_period": {
                "start": test_start_date.isoformat(),
                "end": test_end_date.isoformat()
            },
            "metrics": metrics,
            "signal_summary": {
                "counts": signal_counts,
                "percentages": signal_percentages
            },
            "confidence_summary": confidence_stats,
            "data_info": {
                "total_records": len(test_df),
                "duration_hours": (test_end_date - test_start_date).total_seconds() / 3600
            }
        }
        
        # 結果出力
        print_results(result, output_dir, trades_df, show_trades)
        
        return result
        
    finally:
        data_loader.close()


def run_train_and_backtest(
    symbol: str,
    train_start_date: datetime,
    train_end_date: datetime,
    test_start_date: datetime,
    test_end_date: datetime,
    timeframes: list = [1, 5, 30],
    prediction_horizon: int = 60,
    price_change_threshold: float = 0.0001,
    use_limit_orders: bool = False,
    limit_order_timeout_seconds: int = 60,
    output_dir: Optional[str] = None,
    save_model: bool = False,
    model_name: Optional[str] = None,
    show_trades: bool = True,
    confidence_threshold: float = 0.7
) -> Dict:
    """
    モード1: 訓練 + バックテスト
    
    Args:
        confidence_threshold: 取引を実行するための最小信頼度閾値（デフォルト: 0.7）
                             値を下げるとより多くの取引が実行される
    
    Returns:
        トレーニングとバックテスト結果の辞書
    """
    print("="*70)
    print("TRAIN AND BACKTEST MODE")
    print("="*70)
    print(f"Symbol: {symbol}")
    print(f"Train Period: {train_start_date} to {train_end_date}")
    print(f"Test Period: {test_start_date} to {test_end_date}")
    print()
    
    # データローダーと特徴量エンジニアの初期化
    data_loader = ExchSimDataLoader(use_connection_pool=True)
    
    # 特徴量エンジニアの設定
    feature_set_name = os.getenv('FEATURE_SET_NAME', 'standard_features')
    use_configurable = os.getenv('USE_CONFIGURABLE_FEATURES', 'true').lower() == 'true'
    
    if use_configurable:
        try:
            feature_engineer = ConfigurableFeatureEngineer(feature_set_name=feature_set_name)
            print(f"Using ConfigurableFeatureEngineer with feature set: {feature_set_name}")
        except Exception as e:
            print(f"Warning: Failed to initialize ConfigurableFeatureEngineer: {e}")
            print("Falling back to standard FeatureEngineer")
            feature_engineer = FeatureEngineer()
    else:
        feature_engineer = FeatureEngineer()
        print("Using standard FeatureEngineer")
    
    try:
        # 訓練データのロード
        print(f"\nLoading training data from {train_start_date} to {train_end_date}...")
        train_df = data_loader.load_training_data(
            symbol,
            train_start_date,
            train_end_date,
            skip_min_samples_check=True
        )
        
        if len(train_df) == 0:
            raise ValueError(f"No training data available for {symbol} in the specified period")
        
        print(f"Loaded {len(train_df)} training records")
        
        # テストデータのロード
        print(f"\nLoading test data from {test_start_date} to {test_end_date}...")
        test_df = data_loader.load_training_data(
            symbol,
            test_start_date,
            test_end_date,
            skip_min_samples_check=True
        )
        
        if len(test_df) == 0:
            raise ValueError(f"No test data available for {symbol} in the specified period")
        
        print(f"Loaded {len(test_df)} test records")
        
        # 特徴量エンジニアリング
        print("\nEngineering features...")
        train_df = feature_engineer.engineer_features(train_df)
        test_df = feature_engineer.engineer_features(test_df)
        
        # モデルトレーニング
        print("\nTraining models...")
        price_strategy = PricePredictionStrategy(
            timeframes=timeframes,
            prediction_horizon=prediction_horizon
        )
        
        momentum_strategy = MomentumIntensityStrategy(
            timeframes=timeframes,
            prediction_horizon=prediction_horizon
        )
        
        # 価格予測モデルの訓練
        train_result_price = None
        try:
            print("Training price prediction model...")
            train_result_price = price_strategy.train(train_df)
            print(f"  MAE: {train_result_price.get('mae', 0):,.0f} JPY")
            print(f"  RMSE: {train_result_price.get('rmse', 0):,.0f} JPY")
            print(f"  MAPE: {train_result_price.get('mape', 0):.2f}%")
        except Exception as e:
            print(f"Error training price prediction model: {e}")
            import traceback
            traceback.print_exc()
            price_strategy = None
        
        # モメンタム強度モデルの訓練
        train_result_momentum = None
        try:
            print("Training momentum intensity model...")
            train_result_momentum = momentum_strategy.train(train_df)
            print(f"  MAE: {train_result_momentum.get('mae', 0):.4f}%")
            print(f"  Direction Accuracy: {train_result_momentum.get('direction_accuracy', 0):.2f}%")
        except Exception as e:
            print(f"Error training momentum intensity model: {e}")
            import traceback
            traceback.print_exc()
            momentum_strategy = None
        
        if price_strategy is None and momentum_strategy is None:
            raise ValueError("No models trained. Cannot run backtest.")
        
        # モデルをファイルに保存（--save-modelが指定された場合）
        saved_model_paths = {}
        if save_model:
            try:
                model_dir = ModelConfig.MODEL_DIR
                os.makedirs(model_dir, exist_ok=True)
                
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                model_name_to_use = model_name if model_name else f"{symbol}_{timestamp}"
                
                if price_strategy and price_strategy.model:
                    price_model_path = os.path.join(
                        model_dir,
                        f'price_prediction_{model_name_to_use}.joblib'
                    )
                    price_strategy.model.save(price_model_path)
                    saved_model_paths['price_prediction'] = price_model_path
                    print(f"\n✓ Price prediction model saved to: {price_model_path}")
                
                if momentum_strategy and momentum_strategy.model:
                    momentum_model_path = os.path.join(
                        model_dir,
                        f'momentum_intensity_{model_name_to_use}.joblib'
                    )
                    momentum_strategy.model.save(momentum_model_path)
                    saved_model_paths['momentum_intensity'] = momentum_model_path
                    print(f"✓ Momentum intensity model saved to: {momentum_model_path}")
            except Exception as e:
                print(f"Warning: Failed to save models: {e}")
                import traceback
                traceback.print_exc()
        
        # 予測生成
        print("\nGenerating predictions...")
        price_predictions = None
        momentum_intensity = None
        
        if price_strategy and price_strategy.model:
            price_predictions = price_strategy.predict(test_df)
            print(f"Price predictions generated: {len(price_predictions)} predictions")
        
        if momentum_strategy and momentum_strategy.model:
            momentum_intensity = momentum_strategy.predict_intensity(test_df)
            print(f"Momentum intensity generated: {len(momentum_intensity)} predictions")
        
        # シグナル生成
        print("\nGenerating signals...")
        signals, confidence = generate_signals_from_predictions(
            test_df,
            price_predictions if price_predictions is not None else pd.Series(dtype=float),
            price_change_threshold=price_change_threshold,
            momentum_intensity=momentum_intensity,
            momentum_threshold=4,
            use_momentum=(momentum_intensity is not None),
            max_prediction_error_pct=0.5
        )
        
        print(f"Signals generated: {len(signals)} signals")
        print(f"  BUY: {int((signals == 1).sum())}, SELL: {int((signals == -1).sum())}, HOLD: {int((signals == 0).sum())}")
        print(f"  Confidence: min={confidence.min():.4f}, max={confidence.max():.4f}, mean={confidence.mean():.4f}")
        
        # バックテスト実行
        print("\nRunning backtest...")
        if use_limit_orders:
            executions_df = data_loader.load_executions(symbol, test_start_date, test_end_date)
            backtester = LimitOrderBacktester(
                initial_capital=10000000,
                commission_rate=0.0,
                limit_order_timeout_seconds=limit_order_timeout_seconds,
                executions_df=executions_df
            )
        else:
            backtester = Backtester(
                initial_capital=10000000,
                commission_rate=0.0
            )
        
        metrics = backtester.run(
            test_df,
            signals,
            confidence,
            confidence_threshold=confidence_threshold,
            fixed_quantity=0.01
        )
        
        # 結果の整理
        trades_df = backtester.get_trades()
        equity_curve_df = backtester.get_equity_curve()
        
        signal_counts = {
            'BUY': int((signals == 1).sum()),
            'SELL': int((signals == -1).sum()),
            'HOLD': int((signals == 0).sum())
        }
        total_signals = len(signals)
        signal_percentages = {
            'BUY': (signal_counts['BUY'] / total_signals * 100) if total_signals > 0 else 0.0,
            'SELL': (signal_counts['SELL'] / total_signals * 100) if total_signals > 0 else 0.0,
            'HOLD': (signal_counts['HOLD'] / total_signals * 100) if total_signals > 0 else 0.0
        }
        
        confidence_stats = {
            'mean': float(confidence.mean()) if len(confidence) > 0 else 0.0,
            'min': float(confidence.min()) if len(confidence) > 0 else 0.0,
            'max': float(confidence.max()) if len(confidence) > 0 else 0.0,
            'std': float(confidence.std()) if len(confidence) > 0 else 0.0
        }
        
        result = {
            "status": "success",
            "mode": "train_and_backtest",
            "symbol": symbol,
            "train_period": {
                "start": train_start_date.isoformat(),
                "end": train_end_date.isoformat()
            },
            "test_period": {
                "start": test_start_date.isoformat(),
                "end": test_end_date.isoformat()
            },
            "training_results": {
                "price_prediction": train_result_price,
                "momentum_intensity": train_result_momentum
            },
            "metrics": metrics,
            "signal_summary": {
                "counts": signal_counts,
                "percentages": signal_percentages
            },
            "confidence_summary": confidence_stats,
            "data_info": {
                "training_records": len(train_df),
                "test_records": len(test_df),
                "train_duration_hours": (train_end_date - train_start_date).total_seconds() / 3600,
                "test_duration_hours": (test_end_date - test_start_date).total_seconds() / 3600
            },
            "saved_model_paths": saved_model_paths if save_model else {}
        }
        
        # 結果出力
        print_results(result, output_dir, trades_df, show_trades)
        
        return result
        
    finally:
        data_loader.close()


def print_results(result: Dict, output_dir: Optional[str] = None, trades_df: Optional[pd.DataFrame] = None, show_trades: bool = True):
    """結果をコンソールに出力し、オプションでJSONファイルに保存"""
    print("\n" + "="*70)
    print("RESULTS SUMMARY")
    print("="*70)
    
    if result.get("mode") == "train_and_backtest":
        print("\nTraining Results:")
        if result.get("training_results", {}).get("price_prediction"):
            pr = result["training_results"]["price_prediction"]
            print(f"  Price Prediction Model:")
            print(f"    MAE: {pr.get('mae', 0):,.0f} JPY")
            print(f"    RMSE: {pr.get('rmse', 0):,.0f} JPY")
            print(f"    MAPE: {pr.get('mape', 0):.2f}%")
            print(f"    Training samples: {pr.get('training_samples', 0)}")
            print(f"    Validation samples: {pr.get('validation_samples', 0)}")
        
        if result.get("training_results", {}).get("momentum_intensity"):
            mr = result["training_results"]["momentum_intensity"]
            print(f"  Momentum Intensity Model:")
            print(f"    MAE: {mr.get('mae', 0):.4f}%")
            print(f"    Direction Accuracy: {mr.get('direction_accuracy', 0):.2f}%")
            print(f"    Training samples: {mr.get('training_samples', 0)}")
            print(f"    Validation samples: {mr.get('validation_samples', 0)}")
    
    print("\nSignal Summary:")
    signal_summary = result.get("signal_summary", {})
    counts = signal_summary.get("counts", {})
    percentages = signal_summary.get("percentages", {})
    print(f"  BUY: {counts.get('BUY', 0)} ({percentages.get('BUY', 0):.1f}%)")
    print(f"  SELL: {counts.get('SELL', 0)} ({percentages.get('SELL', 0):.1f}%)")
    print(f"  HOLD: {counts.get('HOLD', 0)} ({percentages.get('HOLD', 0):.1f}%)")
    
    print("\nConfidence Summary:")
    conf_summary = result.get("confidence_summary", {})
    print(f"  Mean: {conf_summary.get('mean', 0):.4f}")
    print(f"  Min: {conf_summary.get('min', 0):.4f}")
    print(f"  Max: {conf_summary.get('max', 0):.4f}")
    print(f"  Std Dev: {conf_summary.get('std', 0):.4f}")
    
    print("\nPerformance Metrics:")
    metrics = result.get("metrics", {})
    print(f"  Total Return: {metrics.get('total_return', 0):.2f}%")
    print(f"  Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}")
    print(f"  Max Drawdown: {metrics.get('max_drawdown', 0):.2f}%")
    print(f"  Win Rate: {metrics.get('win_rate', 0):.2f}%")
    print(f"  Total Trades: {metrics.get('total_trades', 0)}")
    print(f"  Final Equity: ¥{metrics.get('final_equity', 0):,.0f}")
    
    print("="*70)
    
    # トレード履歴の表示
    if show_trades and trades_df is not None and len(trades_df) > 0:
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
            timestamp = row.get('timestamp', idx)
            if isinstance(timestamp, pd.Timestamp):
                timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
            else:
                timestamp_str = str(timestamp)[:19]
            
            action = row.get('action', '')
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
        
        # PNL合計の計算と表示
        if 'pnl' in trades_df.columns:
            exit_trades = trades_df[trades_df['action'].isin(['SELL', 'COVER_SHORT'])]
            if len(exit_trades) > 0:
                total_pnl = exit_trades['pnl'].sum()
                if pd.notna(total_pnl):
                    total_pnl_str = f"{total_pnl:>14,.0f} JPY"
                    if total_pnl > 0:
                        total_pnl_str = f"+{total_pnl:>13,.0f} JPY"
                    print(f"\n{'Total PNL:':<66} {total_pnl_str}")
    
    # JSONファイルに保存
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = os.path.join(output_dir, f"backtest_result_{timestamp}.json")
        
        # JSONシリアライズ可能な形式に変換
        def convert_to_serializable(obj):
            if isinstance(obj, (np.integer, np.int64)):
                return int(obj)
            elif isinstance(obj, (np.floating, np.float64)):
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, dict):
                return {k: convert_to_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_to_serializable(item) for item in obj]
            elif pd.isna(obj):
                return None
            return obj
        
        serializable_result = convert_to_serializable(result)
        
        with open(output_file, 'w') as f:
            json.dump(serializable_result, f, indent=2, default=str)
        
        print(f"\nResults saved to: {output_file}")


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(
        description="Simple Training and Backtest Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Mode 1: Train and backtest
  python -m evaluation.run_simple_train_and_backtest \\
    --symbol G_FX_BTCJPY \\
    --train-start-date "2026-01-12 00:00:00" \\
    --train-end-date "2026-01-13 00:00:00" \\
    --test-start-date "2026-01-13 00:00:00" \\
    --test-end-date "2026-01-14 00:00:00"
  
  # Mode 2: Backtest only (load from default path)
  python -m evaluation.run_simple_train_and_backtest \\
    --symbol G_FX_BTCJPY \\
    --load-model \\
    --test-start-date "2026-01-13 00:00:00" \\
    --test-end-date "2026-01-14 00:00:00"
  
  # Mode 2: Backtest only (load from DB)
  python -m evaluation.run_simple_train_and_backtest \\
    --symbol G_FX_BTCJPY \\
    --load-model \\
    --use-db-model \\
    --load-model-name XG1 \\
    --test-start-date "2026-01-13 00:00:00" \\
    --test-end-date "2026-01-14 00:00:00"
  
  # Mode 1: Train and backtest with model saving
  python -m evaluation.run_simple_train_and_backtest \\
    --symbol G_FX_BTCJPY \\
    --train-start-date "2026-01-12 00:00:00" \\
    --train-end-date "2026-01-13 00:00:00" \\
    --test-start-date "2026-01-13 00:00:00" \\
    --test-end-date "2026-01-14 00:00:00" \\
    --save-model \\
    --model-name MyModel
        """
    )
    
    # 共通パラメータ
    parser.add_argument('--symbol', type=str, required=True, help='Symbol (e.g., G_FX_BTCJPY)')
    parser.add_argument('--test-start-date', type=str, required=True, help='Test data start date (ISO format)')
    parser.add_argument('--test-end-date', type=str, required=True, help='Test data end date (ISO format)')
    parser.add_argument('--timeframes', type=int, nargs='+', default=[1, 5, 30], help='Timeframes in seconds (default: 1 5 30)')
    parser.add_argument('--prediction-horizon', type=int, default=60, help='Prediction horizon in seconds (default: 60)')
    parser.add_argument('--price-change-threshold', type=float, default=0.0001, help='Price change threshold (default: 0.0001)')
    parser.add_argument('--use-limit-orders', action='store_true', help='Use limit orders for backtest')
    parser.add_argument('--limit-order-timeout', type=int, default=60, help='Limit order timeout in seconds (default: 60)')
    parser.add_argument('--output-dir', type=str, help='Output directory for JSON results (optional)')
    parser.add_argument('--show-trades', action='store_true', default=True, help='Show trade history (default: True)')
    parser.add_argument('--no-show-trades', dest='show_trades', action='store_false', help='Do not show trade history')
    parser.add_argument('--confidence-threshold', type=float, default=0.7, help='Minimum confidence threshold for executing trades (default: 0.7). Lower values result in more trades.')
    
    # モード2: バックテストのみ
    parser.add_argument('--load-model', action='store_true', help='Load existing model (backtest only mode)')
    parser.add_argument('--load-model-name', type=str, help='Model name (for DB loading, use with --load-model)')
    parser.add_argument('--model-path-price', type=str, help='Path to price prediction model file (for loading)')
    parser.add_argument('--model-path-momentum', type=str, help='Path to momentum intensity model file (for loading)')
    parser.add_argument('--use-db-model', action='store_true', help='Load model from database (use with --load-model)')
    
    # モード1: 訓練 + バックテスト
    parser.add_argument('--train-start-date', type=str, help='Training data start date (ISO format, required for train mode)')
    parser.add_argument('--train-end-date', type=str, help='Training data end date (ISO format, required for train mode)')
    parser.add_argument('--save-model', action='store_true', help='Save trained models to file (train mode only)')
    parser.add_argument('--model-name', type=str, help='Model name for saving (optional, defaults to symbol_timestamp)')
    
    args = parser.parse_args()
    
    # 日時をパース
    test_start_date = parse_datetime(args.test_start_date)
    test_end_date = parse_datetime(args.test_end_date)
    
    try:
        if args.load_model:
            # モード2: バックテストのみ
            if not args.model_path_price and not args.model_path_momentum and not args.use_db_model:
                print("Warning: No model path or DB model specified. Will try to load from default paths.")
            
            result = run_backtest_only(
                symbol=args.symbol,
                test_start_date=test_start_date,
                test_end_date=test_end_date,
                model_path_price=args.model_path_price,
                model_path_momentum=args.model_path_momentum,
                model_name=args.load_model_name,
                use_db_model=args.use_db_model,
                timeframes=args.timeframes,
                prediction_horizon=args.prediction_horizon,
                price_change_threshold=args.price_change_threshold,
                use_limit_orders=args.use_limit_orders,
                limit_order_timeout_seconds=args.limit_order_timeout,
                output_dir=args.output_dir,
                show_trades=args.show_trades,
                confidence_threshold=args.confidence_threshold
            )
        else:
            # モード1: 訓練 + バックテスト
            if not args.train_start_date or not args.train_end_date:
                parser.error("--train-start-date and --train-end-date are required when not using --load-model")
            
            train_start_date = parse_datetime(args.train_start_date)
            train_end_date = parse_datetime(args.train_end_date)
            
            result = run_train_and_backtest(
                symbol=args.symbol,
                train_start_date=train_start_date,
                train_end_date=train_end_date,
                test_start_date=test_start_date,
                test_end_date=test_end_date,
                timeframes=args.timeframes,
                prediction_horizon=args.prediction_horizon,
                price_change_threshold=args.price_change_threshold,
                use_limit_orders=args.use_limit_orders,
                limit_order_timeout_seconds=args.limit_order_timeout,
                output_dir=args.output_dir,
                save_model=args.save_model,
                model_name=args.model_name,
                show_trades=args.show_trades,
                confidence_threshold=args.confidence_threshold
            )
        
        return result
        
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
