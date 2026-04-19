"""
Backtest Service for API
バックテスト実行をAPI経由で提供するサービス
"""
import os
import sys
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
import pandas as pd
import numpy as np

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 共通ロガーのインポートと設定
from api.shared.logger import setup_logger
logger = setup_logger("backtest_service")

from data.data_loader import MarketDataLoader
from data.exch_sim_data_loader import ExchSimDataLoader
from data.feature_engineering import FeatureEngineer
from data.configurable_feature_engineering import ConfigurableFeatureEngineer
from strategy.price_prediction_strategy import PricePredictionStrategy
from strategy.momentum_intensity_strategy import MomentumIntensityStrategy
from models.price_prediction_model import PricePredictionModel
from models.momentum_intensity_model import MomentumIntensityModel
# LightGBMは遅延インポート（libomp依存関係の問題を回避）
from evaluation.run_price_prediction_backtest import run_price_prediction_backtest, generate_signals_from_predictions
from evaluation.backtester import Backtester
from evaluation.limit_order_backtester import LimitOrderBacktester
from config.settings import DatabaseConfig, ModelConfig, BacktestConfig
from api.model_manager import ModelManager


def run_backtest_task(
    model_name: str,
    model_type: str,
    symbol: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    initial_capital: float = 10000000,
    commission_rate: float = 0.0,
    confidence_threshold: float = 0.7,
    max_position_size: float = 0.01,
    stop_loss_pct: float = 0.36,
    use_limit_orders: bool = False,
    limit_order_timeout_seconds: int = 60,
    show_trades: bool = True,
    show_equity_curve: bool = True,
    progress_callback: callable = None,
    data_quality_callback: callable = None
) -> Dict:
    """
    バックテストを実行
    
    Args:
        model_name: モデル名
        model_type: モデルタイプ ("price_prediction", "momentum_intensity", or "lightgbm_price_prediction")
        symbol: シンボル
        start_date: 開始日時
        end_date: 終了日時
        initial_capital: 初期資金
        commission_rate: 手数料率
        confidence_threshold: 信頼度閾値
        max_position_size: 最大ポジションサイズ
        stop_loss_pct: ストップロス率
        use_limit_orders: Limit Orderを使用するか
        limit_order_timeout_seconds: Limit Orderのタイムアウト（秒）
        show_trades: 取引履歴を表示するか
        show_equity_curve: エクイティカーブを表示するか
    
    Returns:
        バックテスト結果の辞書
    """
    try:
        # データローダーの初期化
        use_exch_sim_db = DatabaseConfig.USE_EXCH_SIM_DB
        if use_exch_sim_db:
            data_loader = ExchSimDataLoader()
        else:
            data_loader = MarketDataLoader()
        
        # モデルマネージャーの初期化（algo_traderデータベースを使用）
        connection_string = DatabaseConfig.get_algo_trader_connection_string()
        model_manager = ModelManager(connection_string=connection_string, use_file_backend=False)
        
        # モデルの読み込み
        models = model_manager.get_models(model_name=model_name, model_type=model_type, symbol=symbol)
        if not models:
            raise ValueError(f"Model not found: {model_name} ({model_type}, {symbol})")
        
        # 最新のモデルを取得（trained_atでソート済み）
        model_info = models[0]
        
        # DBベースの場合、file_pathは仮のパス（db://...）になっている
        # 実際のモデルはDBから直接ロードする
        model_path = model_info.get("file_path")
        use_db_model = model_path and model_path.startswith("db://")
        
        if not use_db_model:
            # ファイルベースの場合、ファイルの存在確認
            if not model_path:
                # file_pathが存在しない場合はDBベースとして扱う
                use_db_model = True
                print(f"Warning: model_path is None for model {model_name}, treating as DB-based model")
            elif not os.path.exists(model_path):
                # ファイルが存在しない場合もDBベースとして扱う（後方互換性）
                use_db_model = True
                print(f"Warning: Model file not found: {model_path}, treating as DB-based model")
        
        # 日付の設定
        if end_date is None:
            end_date = datetime.now(timezone.utc)
        if start_date is None:
            start_date = end_date - timedelta(days=1)
        
        # タイムゾーンの処理（naive datetimeの場合はJSTとして扱い、UTCに変換）
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone(timedelta(hours=9)))  # JST
            start_date = start_date.astimezone(timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone(timedelta(hours=9)))  # JST
            end_date = end_date.astimezone(timezone.utc)
        
        # データの読み込み
        if progress_callback:
            progress_callback(0, 0, 0.0, "loading", "Loading data from database...")
        
        print(f"Loading data from {start_date} to {end_date}")
        
        # データ量に応じてバッチ読み込みを使用
        total_days = (end_date - start_date).total_seconds() / 86400
        use_batch = total_days > 3  # 3日以上の場合にバッチ読み込みを使用
        
        try:
            df = data_loader.load_training_data(
                symbol, 
                start_date, 
                end_date, 
                skip_min_samples_check=True,
                use_batch_loading=use_batch,
                batch_size_days=1  # 1日ずつ読み込み
            )
        except Exception as e:
            print(f"Error loading data: {e}")
            raise
        
        if len(df) == 0:
            raise ValueError("No data available for the specified period")
        
        print(f"Loaded {len(df)} records")
        
        # データ品質チェック
        if progress_callback:
            progress_callback(0, len(df), 0.0, "quality_check", "Checking data quality...")
        
        data_quality = _check_data_quality(df, symbol, start_date, end_date)
        
        # データ品質情報をコールバックで通知
        if data_quality_callback:
            data_quality_callback(data_quality)
        
        if progress_callback:
            progress_callback(0, len(df), 0.0, "feature_engineering", "Engineering features...")
        
        # 特徴量エンジニアリング
        feature_set_name = os.getenv('FEATURE_SET_NAME', 'standard_features')
        use_configurable = os.getenv('USE_CONFIGURABLE_FEATURES', 'true').lower() == 'true'
        
        if use_configurable:
            try:
                feature_engineer = ConfigurableFeatureEngineer(feature_set_name=feature_set_name)
            except Exception as e:
                print(f"Warning: Failed to initialize ConfigurableFeatureEngineer: {e}")
                print("Falling back to standard FeatureEngineer")
                feature_engineer = FeatureEngineer()
        else:
            feature_engineer = FeatureEngineer()
        
        # モデルタイプに応じてバックテストを実行
        if model_type == "price_prediction":
            # 価格予測モデルのバックテスト
            # run_price_prediction_backtestは辞書を返すが、構造を確認する必要がある
            # 実際の実装では、バックテスターから直接メトリクスを取得する方が確実
            
            # モデルの読み込み
            price_strategy = PricePredictionStrategy(
                timeframes=[1, 5, 30],
                prediction_horizon=60
            )
            
            # DBベースの場合はmodel_managerから直接ロード、ファイルベースの場合はファイルからロード
            if use_db_model:
                loaded_model = model_manager.load_model(model_name, model_type, symbol)
                price_strategy.model = loaded_model
            else:
                price_strategy.model = PricePredictionModel.load(model_path)
            
            # 特徴量エンジニアリング
            df = feature_engineer.engineer_features(df)
            logger.info(f"Data after feature engineering: {len(df)} records, columns: {list(df.columns)[:10]}...")
            
            # 予測とシグナル生成
            logger.info("Generating predictions...")
            predictions = price_strategy.predict(df)
            logger.info(f"Predictions generated: {len(predictions)} predictions, type: {type(predictions)}")
            
            if len(predictions) == 0:
                logger.warning("WARNING: No predictions generated!")
            else:
                logger.info(f"Predictions sample: min={predictions.min():.2f}, max={predictions.max():.2f}, mean={predictions.mean():.2f}")
                logger.info(f"Predictions index sample: {list(predictions.index[:5])}")
                logger.info(f"Data index sample: {list(df.index[:5])}")
                
                # インデックスの一致確認
                common_indices = predictions.index.intersection(df.index)
                if len(common_indices) == 0:
                    logger.warning(f"WARNING: No common indices between predictions and data!")
                    logger.warning(f"Predictions index length: {len(predictions.index)}, Data index length: {len(df.index)}")
                else:
                    logger.info(f"Common indices: {len(common_indices)} out of {len(predictions.index)} predictions")
            
            signals, confidence = generate_signals_from_predictions(
                df, predictions, price_change_threshold=0.0001
            )
            logger.info(f"Signals generated: {len(signals)} signals")
            logger.info(f"Signals summary: BUY={int((signals == 1).sum())}, SELL={int((signals == -1).sum())}, HOLD={int((signals == 0).sum())}")
            logger.info(f"Confidence summary: min={confidence.min():.4f}, max={confidence.max():.4f}, mean={confidence.mean():.4f}")
            
            # 警告ログの追加
            if len(signals) > 0:
                buy_count = int((signals == 1).sum())
                sell_count = int((signals == -1).sum())
                hold_count = int((signals == 0).sum())
                if buy_count == 0 and sell_count == 0:
                    logger.warning("WARNING: All signals are HOLD (0)! No BUY or SELL signals generated.")
                if len(confidence) > 0 and confidence.max() == 0.0:
                    logger.warning("WARNING: All confidence values are 0.0!")
            
            if len(signals) > 0 and (signals != 0).any():
                logger.info(f"Non-zero signals sample: {signals[signals != 0].head(10).to_dict()}")
            if len(confidence) > 0 and (confidence > 0).any():
                logger.info(f"Non-zero confidence sample: {confidence[confidence > 0].head(10).to_dict()}")
            
            # バックテスト実行
            if use_limit_orders:
                exch_sim_loader = ExchSimDataLoader()
                executions_df = exch_sim_loader.load_executions(symbol, df.index[0], df.index[-1])
                backtester = LimitOrderBacktester(
                    initial_capital=initial_capital,
                    commission_rate=commission_rate,
                    limit_order_timeout_seconds=limit_order_timeout_seconds,
                    executions_df=executions_df
                )
            else:
                backtester = Backtester(
                    initial_capital=initial_capital,
                    commission_rate=commission_rate
                )
            
            metrics = backtester.run(
                df,
                signals,
                confidence,
                confidence_threshold=confidence_threshold,
                stop_loss=stop_loss_pct * initial_capital if stop_loss_pct else None,
                fixed_quantity=max_position_size,
                progress_callback=progress_callback
            )
            
            # トレード履歴とエクイティカーブを取得
            trades_df = backtester.get_trades()
            equity_curve_df = backtester.get_equity_curve()
            
            # シグナルとコンフィデンスの統計を計算
            signal_counts = {
                'BUY': int((signals == 1).sum()) if hasattr(signals, 'sum') else len([s for s in signals if s == 1]),
                'SELL': int((signals == -1).sum()) if hasattr(signals, 'sum') else len([s for s in signals if s == -1]),
                'HOLD': int((signals == 0).sum()) if hasattr(signals, 'sum') else len([s for s in signals if s == 0])
            }
            total_signals = len(signals) if hasattr(signals, '__len__') else (signal_counts['BUY'] + signal_counts['SELL'] + signal_counts['HOLD'])
            signal_percentages = {
                'BUY': (signal_counts['BUY'] / total_signals * 100) if total_signals > 0 else 0.0,
                'SELL': (signal_counts['SELL'] / total_signals * 100) if total_signals > 0 else 0.0,
                'HOLD': (signal_counts['HOLD'] / total_signals * 100) if total_signals > 0 else 0.0
            }
            
            # コンフィデンスの統計を計算
            if hasattr(confidence, 'mean'):
                confidence_stats = {
                    'mean': float(confidence.mean()) if len(confidence) > 0 else 0.0,
                    'min': float(confidence.min()) if len(confidence) > 0 else 0.0,
                    'max': float(confidence.max()) if len(confidence) > 0 else 0.0,
                    'std': float(confidence.std()) if len(confidence) > 0 else 0.0
                }
            else:
                confidence_list = list(confidence) if hasattr(confidence, '__iter__') else [confidence]
                if len(confidence_list) > 0:
                    import numpy as np
                    confidence_array = np.array(confidence_list)
                    confidence_stats = {
                        'mean': float(np.mean(confidence_array)),
                        'min': float(np.min(confidence_array)),
                        'max': float(np.max(confidence_array)),
                        'std': float(np.std(confidence_array))
                    }
                else:
                    confidence_stats = {'mean': 0.0, 'min': 0.0, 'max': 0.0, 'std': 0.0}
            
            return {
                "status": "success",
                "metrics": metrics,
                "equity_curve": equity_curve_df.to_dict('records') if show_equity_curve and len(equity_curve_df) > 0 else [],
                "trades": trades_df.to_dict('records') if show_trades and len(trades_df) > 0 else [],
                "signal_summary": {
                    "counts": signal_counts,
                    "percentages": signal_percentages
                },
                "confidence_summary": confidence_stats,
                "data_info": {
                    "total_records": len(df),
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
                    "duration_hours": (end_date - start_date).total_seconds() / 3600 if start_date and end_date else None
                }
            }
        
        elif model_type == "lightgbm_price_prediction":
            # LightGBM価格予測モデルのバックテスト（price_predictionと同じ処理）
            try:
                from strategy.lightgbm_price_prediction_strategy import LightGBMPricePredictionStrategy
            except ImportError as e:
                if "libomp" in str(e).lower() or "Library not loaded" in str(e):
                    raise ImportError(
                        f"LightGBM requires libomp library. "
                        f"Please install it: brew install libomp\n"
                        f"Then create a symlink: sudo mkdir -p /usr/local/opt/libomp/lib && "
                        f"sudo ln -sf /opt/homebrew/opt/libomp/lib/libomp.dylib /usr/local/opt/libomp/lib/libomp.dylib"
                    )
                raise
            
            # モデルの読み込み
            lightgbm_strategy = LightGBMPricePredictionStrategy(
                timeframes=[1, 5, 30],
                prediction_horizon=60
            )
            
            # DBベースの場合はmodel_managerから直接ロード、ファイルベースの場合はファイルからロード
            if use_db_model:
                loaded_model = model_manager.load_model(model_name, model_type, symbol)
                lightgbm_strategy.model = loaded_model
            else:
                # LightGBMモデルをロード
                from models.lightgbm_price_prediction_model import LightGBMPricePredictionModel
                lightgbm_strategy.model = LightGBMPricePredictionModel.load(model_path)
            
            # 特徴量エンジニアリング
            df = feature_engineer.engineer_features(df)
            logger.info(f"Data after feature engineering: {len(df)} records, columns: {list(df.columns)[:10]}...")
            
            # 予測とシグナル生成
            logger.info("Generating predictions (LightGBM)...")
            predictions = lightgbm_strategy.predict(df)
            logger.info(f"Predictions generated: {len(predictions)} predictions, type: {type(predictions)}")
            
            if len(predictions) == 0:
                logger.warning("WARNING: No predictions generated!")
            else:
                logger.info(f"Predictions sample: min={predictions.min():.2f}, max={predictions.max():.2f}, mean={predictions.mean():.2f}")
                logger.info(f"Predictions index sample: {list(predictions.index[:5])}")
                logger.info(f"Data index sample: {list(df.index[:5])}")
                
                # インデックスの一致確認
                common_indices = predictions.index.intersection(df.index)
                if len(common_indices) == 0:
                    logger.warning(f"WARNING: No common indices between predictions and data!")
                    logger.warning(f"Predictions index length: {len(predictions.index)}, Data index length: {len(df.index)}")
                else:
                    logger.info(f"Common indices: {len(common_indices)} out of {len(predictions.index)} predictions")
            
            signals, confidence = generate_signals_from_predictions(
                df, predictions, price_change_threshold=0.0001
            )
            logger.info(f"Signals generated: {len(signals)} signals")
            logger.info(f"Signals summary: BUY={int((signals == 1).sum())}, SELL={int((signals == -1).sum())}, HOLD={int((signals == 0).sum())}")
            logger.info(f"Confidence summary: min={confidence.min():.4f}, max={confidence.max():.4f}, mean={confidence.mean():.4f}")
            
            # 警告ログの追加
            if len(signals) > 0:
                buy_count = int((signals == 1).sum())
                sell_count = int((signals == -1).sum())
                hold_count = int((signals == 0).sum())
                if buy_count == 0 and sell_count == 0:
                    logger.warning("WARNING: All signals are HOLD (0)! No BUY or SELL signals generated.")
                if len(confidence) > 0 and confidence.max() == 0.0:
                    logger.warning("WARNING: All confidence values are 0.0!")
            
            if len(signals) > 0 and (signals != 0).any():
                logger.info(f"Non-zero signals sample: {signals[signals != 0].head(10).to_dict()}")
            if len(confidence) > 0 and (confidence > 0).any():
                logger.info(f"Non-zero confidence sample: {confidence[confidence > 0].head(10).to_dict()}")
            
            # バックテスト実行
            if use_limit_orders:
                exch_sim_loader = ExchSimDataLoader()
                executions_df = exch_sim_loader.load_executions(symbol, df.index[0], df.index[-1])
                backtester = LimitOrderBacktester(
                    initial_capital=initial_capital,
                    commission_rate=commission_rate,
                    limit_order_timeout_seconds=limit_order_timeout_seconds,
                    executions_df=executions_df
                )
            else:
                backtester = Backtester(
                    initial_capital=initial_capital,
                    commission_rate=commission_rate
                )
            
            metrics = backtester.run(
                df,
                signals,
                confidence,
                confidence_threshold=confidence_threshold,
                stop_loss=stop_loss_pct * initial_capital if stop_loss_pct else None,
                fixed_quantity=max_position_size,
                progress_callback=progress_callback
            )
            
            # トレード履歴とエクイティカーブを取得
            trades_df = backtester.get_trades()
            equity_curve_df = backtester.get_equity_curve()
            
            # シグナルとコンフィデンスの統計を計算
            signal_counts = {
                'BUY': int((signals == 1).sum()) if hasattr(signals, 'sum') else len([s for s in signals if s == 1]),
                'SELL': int((signals == -1).sum()) if hasattr(signals, 'sum') else len([s for s in signals if s == -1]),
                'HOLD': int((signals == 0).sum()) if hasattr(signals, 'sum') else len([s for s in signals if s == 0])
            }
            total_signals = len(signals) if hasattr(signals, '__len__') else (signal_counts['BUY'] + signal_counts['SELL'] + signal_counts['HOLD'])
            signal_percentages = {
                'BUY': (signal_counts['BUY'] / total_signals * 100) if total_signals > 0 else 0.0,
                'SELL': (signal_counts['SELL'] / total_signals * 100) if total_signals > 0 else 0.0,
                'HOLD': (signal_counts['HOLD'] / total_signals * 100) if total_signals > 0 else 0.0
            }
            
            # コンフィデンスの統計を計算
            if hasattr(confidence, 'mean'):
                confidence_stats = {
                    'mean': float(confidence.mean()) if len(confidence) > 0 else 0.0,
                    'min': float(confidence.min()) if len(confidence) > 0 else 0.0,
                    'max': float(confidence.max()) if len(confidence) > 0 else 0.0,
                    'std': float(confidence.std()) if len(confidence) > 0 else 0.0
                }
            else:
                confidence_list = list(confidence) if hasattr(confidence, '__iter__') else [confidence]
                if len(confidence_list) > 0:
                    import numpy as np
                    confidence_array = np.array(confidence_list)
                    confidence_stats = {
                        'mean': float(np.mean(confidence_array)),
                        'min': float(np.min(confidence_array)),
                        'max': float(np.max(confidence_array)),
                        'std': float(np.std(confidence_array))
                    }
                else:
                    confidence_stats = {'mean': 0.0, 'min': 0.0, 'max': 0.0, 'std': 0.0}
            
            return {
                "status": "success",
                "metrics": metrics,
                "equity_curve": equity_curve_df.to_dict('records') if show_equity_curve and len(equity_curve_df) > 0 else [],
                "trades": trades_df.to_dict('records') if show_trades and len(trades_df) > 0 else [],
                "signal_summary": {
                    "counts": signal_counts,
                    "percentages": signal_percentages
                },
                "confidence_summary": confidence_stats,
                "data_info": {
                    "total_records": len(df),
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
                    "duration_hours": (end_date - start_date).total_seconds() / 3600 if start_date and end_date else None
                }
            }
        
        elif model_type == "momentum_intensity":
            # モメンタム強度モデルのバックテスト
            strategy = MomentumIntensityStrategy(
                timeframes=[1, 5, 30],
                prediction_horizon=60
            )
            # DBベースの場合はmodel_managerから直接ロード、ファイルベースの場合はファイルからロード
            if use_db_model:
                loaded_model = model_manager.load_model(model_name, model_type, symbol)
                strategy.model = loaded_model
            else:
                strategy.model = MomentumIntensityModel.load(model_path)
            
            # 特徴量エンジニアリング
            df = feature_engineer.engineer_features(df)
            logger.info(f"Data after feature engineering: {len(df)} records, columns: {list(df.columns)[:10]}...")
            
            # シグナル生成
            logger.info("Generating signals (Momentum Intensity)...")
            signals = strategy.generate_signals(df)
            confidence = strategy.get_confidence(df)
            logger.info(f"Signals generated: {len(signals)} signals")
            logger.info(f"Signals summary: BUY={int((signals == 1).sum())}, SELL={int((signals == -1).sum())}, HOLD={int((signals == 0).sum())}")
            logger.info(f"Confidence summary: min={confidence.min():.4f}, max={confidence.max():.4f}, mean={confidence.mean():.4f}")
            
            # 警告ログの追加
            if len(signals) > 0:
                buy_count = int((signals == 1).sum())
                sell_count = int((signals == -1).sum())
                if buy_count == 0 and sell_count == 0:
                    logger.warning("WARNING: All signals are HOLD (0)! No BUY or SELL signals generated.")
                if len(confidence) > 0 and confidence.max() == 0.0:
                    logger.warning("WARNING: All confidence values are 0.0!")
            
            if len(signals) > 0 and (signals != 0).any():
                logger.info(f"Non-zero signals sample: {signals[signals != 0].head(10).to_dict()}")
            if len(confidence) > 0 and (confidence > 0).any():
                logger.info(f"Non-zero confidence sample: {confidence[confidence > 0].head(10).to_dict()}")
            
            # バックテスト実行
            if use_limit_orders:
                exch_sim_loader = ExchSimDataLoader()
                executions_df = exch_sim_loader.load_executions(symbol, df.index[0], df.index[-1])
                backtester = LimitOrderBacktester(
                    initial_capital=initial_capital,
                    commission_rate=commission_rate,
                    limit_order_timeout_seconds=limit_order_timeout_seconds,
                    executions_df=executions_df
                )
            else:
                backtester = Backtester(
                    initial_capital=initial_capital,
                    commission_rate=commission_rate
                )
            
            metrics = backtester.run(
                df,
                signals,
                confidence,
                confidence_threshold=confidence_threshold,
                stop_loss=stop_loss_pct * initial_capital if stop_loss_pct else None,
                fixed_quantity=max_position_size,
                progress_callback=progress_callback
            )
            
            # トレード履歴とエクイティカーブを取得
            trades_df = backtester.get_trades()
            equity_curve_df = backtester.get_equity_curve()
            
            # シグナルとコンフィデンスの統計を計算
            signal_counts = {
                'BUY': int((signals == 1).sum()) if hasattr(signals, 'sum') else len([s for s in signals if s == 1]),
                'SELL': int((signals == -1).sum()) if hasattr(signals, 'sum') else len([s for s in signals if s == -1]),
                'HOLD': int((signals == 0).sum()) if hasattr(signals, 'sum') else len([s for s in signals if s == 0])
            }
            total_signals = len(signals) if hasattr(signals, '__len__') else (signal_counts['BUY'] + signal_counts['SELL'] + signal_counts['HOLD'])
            signal_percentages = {
                'BUY': (signal_counts['BUY'] / total_signals * 100) if total_signals > 0 else 0.0,
                'SELL': (signal_counts['SELL'] / total_signals * 100) if total_signals > 0 else 0.0,
                'HOLD': (signal_counts['HOLD'] / total_signals * 100) if total_signals > 0 else 0.0
            }
            
            # コンフィデンスの統計を計算
            if hasattr(confidence, 'mean'):
                confidence_stats = {
                    'mean': float(confidence.mean()) if len(confidence) > 0 else 0.0,
                    'min': float(confidence.min()) if len(confidence) > 0 else 0.0,
                    'max': float(confidence.max()) if len(confidence) > 0 else 0.0,
                    'std': float(confidence.std()) if len(confidence) > 0 else 0.0
                }
            else:
                confidence_list = list(confidence) if hasattr(confidence, '__iter__') else [confidence]
                if len(confidence_list) > 0:
                    import numpy as np
                    confidence_array = np.array(confidence_list)
                    confidence_stats = {
                        'mean': float(np.mean(confidence_array)),
                        'min': float(np.min(confidence_array)),
                        'max': float(np.max(confidence_array)),
                        'std': float(np.std(confidence_array))
                    }
                else:
                    confidence_stats = {'mean': 0.0, 'min': 0.0, 'max': 0.0, 'std': 0.0}
            
            return {
                "status": "success",
                "metrics": metrics,
                "equity_curve": equity_curve_df.to_dict('records') if show_equity_curve and len(equity_curve_df) > 0 else [],
                "trades": trades_df.to_dict('records') if show_trades and len(trades_df) > 0 else [],
                "signal_summary": {
                    "counts": signal_counts,
                    "percentages": signal_percentages
                },
                "confidence_summary": confidence_stats,
                "data_info": {
                    "total_records": len(df),
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
                    "duration_hours": (end_date - start_date).total_seconds() / 3600 if start_date and end_date else None
                }
            }
        
        else:
            raise ValueError(f"Unsupported model type: {model_type}")
    
    except Exception as e:
        print(f"Error in run_backtest_task: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "error": str(e)
        }


def _check_data_quality(df: pd.DataFrame, symbol: str, start_date: datetime, end_date: datetime) -> Dict:
    """
    データ品質をチェック
    
    Args:
        df: データフレーム
        symbol: シンボル
        start_date: 開始日時
        end_date: 終了日時
    
    Returns:
        データ品質情報の辞書
    """
    if len(df) == 0:
        return {
            "total_records": 0,
            "quality_score": 0,
            "issues": ["No data available"]
        }
    
    issues = []
    quality_score = 100
    
    # 1. データの完全性チェック
    expected_duration = (end_date - start_date).total_seconds()
    expected_records = int(expected_duration)  # 1秒間隔を想定
    actual_records = len(df)
    completeness_pct = (actual_records / expected_records * 100) if expected_records > 0 else 0
    
    if completeness_pct < 50:
        issues.append(f"Low completeness: {completeness_pct:.1f}% (expected: {expected_records}, actual: {actual_records})")
        quality_score -= 30
    elif completeness_pct < 80:
        issues.append(f"Moderate completeness: {completeness_pct:.1f}%")
        quality_score -= 10
    
    # 2. クロス市場チェック
    if 'bid_price_1' in df.columns and 'ask_price_1' in df.columns:
        crossed_market = (df['bid_price_1'] >= df['ask_price_1']).sum()
        if crossed_market > 0:
            crossed_pct = (crossed_market / len(df)) * 100
            issues.append(f"Crossed market: {crossed_market} records ({crossed_pct:.2f}%)")
            quality_score -= min(20, crossed_pct * 2)
    
    # 3. 価格の妥当性チェック
    if 'mid_price' in df.columns:
        invalid_prices = (df['mid_price'] <= 0).sum()
        if invalid_prices > 0:
            issues.append(f"Invalid prices: {invalid_prices} records")
            quality_score -= 20
    
    # 4. スプレッドチェック
    if 'spread' in df.columns and 'mid_price' in df.columns:
        spread_ratio = (df['spread'] / (df['mid_price'] + 1e-9)) * 100
        high_spread = (spread_ratio > 1.0).sum()  # 1%以上のスプレッド
        if high_spread > 0:
            high_spread_pct = (high_spread / len(df)) * 100
            issues.append(f"High spread: {high_spread} records ({high_spread_pct:.2f}%)")
            quality_score -= min(10, high_spread_pct)
    
    # 5. 欠損値チェック
    missing_values = df.isnull().sum().sum()
    if missing_values > 0:
        missing_pct = (missing_values / (len(df) * len(df.columns))) * 100
        issues.append(f"Missing values: {missing_values} ({missing_pct:.2f}%)")
        quality_score -= min(10, missing_pct)
    
    quality_score = max(0, quality_score)
    
    return {
        "total_records": len(df),
        "expected_records": expected_records,
        "completeness_pct": completeness_pct,
        "quality_score": quality_score,
        "issues": issues,
        "date_range": {
            "start": df.index[0].isoformat() if len(df) > 0 else None,
            "end": df.index[-1].isoformat() if len(df) > 0 else None
        }
    }

