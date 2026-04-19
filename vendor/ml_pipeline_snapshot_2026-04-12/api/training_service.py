"""
Training Service for Model Retraining
既存の訓練ロジックを再利用可能な関数として提供
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple, List
import pandas as pd
import numpy as np

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.data_loader import MarketDataLoader
from data.exch_sim_data_loader import ExchSimDataLoader
from data.feature_engineering import FeatureEngineer
from data.configurable_feature_engineering import ConfigurableFeatureEngineer
from strategy.price_prediction_strategy import PricePredictionStrategy
from strategy.momentum_intensity_strategy import MomentumIntensityStrategy
from strategy.direction_classification_strategy import DirectionClassificationStrategy
from strategy.volatility_prediction_strategy import VolatilityPredictionStrategy
from strategy.volume_prediction_strategy import VolumePredictionStrategy
# LightGBM戦略は遅延インポート（pandas 2.1.3との互換性問題を回避）
# from strategy.lightgbm_price_prediction_strategy import LightGBMPricePredictionStrategy
from strategy.order_book_only_strategy import OrderBookOnlyStrategy
from config.settings import DatabaseConfig, ModelConfig, TrainingConfig


def _calculate_simple_quality_score(df: pd.DataFrame) -> float:
    """
    データクオリティスコアを簡易計算（0-100）
    詳細な評価は別途レポートファイルに保存
    
    Args:
        df: 訓練データのDataFrame
    
    Returns:
        データクオリティスコア（0-100）
    """
    if len(df) == 0:
        return 0.0
    
    score = 100.0
    
    # 欠損値チェック（-10点）
    missing_ratio = df.isnull().sum().sum() / (len(df) * len(df.columns))
    score -= min(10, missing_ratio * 100)
    
    # クロス市場チェック（-20点）
    if 'bid_price_1' in df.columns and 'ask_price_1' in df.columns:
        crossed = (df['bid_price_1'] >= df['ask_price_1']).sum()
        crossed_ratio = crossed / len(df)
        score -= min(20, crossed_ratio * 200)
    
    # 無効な価格チェック（-15点）
    if 'bid_price_1' in df.columns:
        invalid_bid = (df['bid_price_1'] <= 0).sum()
        invalid_bid_ratio = invalid_bid / len(df)
        score -= min(15, invalid_bid_ratio * 150)
    
    if 'ask_price_1' in df.columns:
        invalid_ask = (df['ask_price_1'] <= 0).sum()
        invalid_ask_ratio = invalid_ask / len(df)
        score -= min(15, invalid_ask_ratio * 150)
    
    return max(0.0, score)


def train_models(
    symbol: str,
    model_name: str,
    training_window_days: int = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    models: List[str] = None,
    timeframes: List[int] = None,
    prediction_horizon: int = 60,
    feature_engineer: Optional[FeatureEngineer] = None,
    data_loader: Optional[MarketDataLoader] = None
) -> Dict:
    """
    モデルを訓練して保存
    
    Args:
        symbol: 銘柄（例: "G_FX_BTCJPY"）
        model_name: モデル名（例: "my_model_v1"）
        training_window_days: 訓練データの期間（日数、デフォルト: 3）
                              start_dateとend_dateが指定されている場合は無視される
        start_date: 訓練データの開始日時（datetime、オプション）
                    指定されていない場合は、end_dateからtraining_window_daysを引いた日時を使用
        end_date: 訓練データの終了日時（datetime、オプション）
                  指定されていない場合は現在時刻を使用
        models: 訓練するモデルのリスト（["price", "momentum", "direction", "volatility", "volume", "lightgbm_price", "order_book_only"]、デフォルト: ["price", "momentum"]）
        timeframes: タイムフレームのリスト（秒、デフォルト: [1, 5, 30]）
        prediction_horizon: 予測ホライズン（秒、デフォルト: 60）
        feature_engineer: 特徴量エンジニア（Noneの場合は新規作成）
        data_loader: データローダー（Noneの場合は新規作成）
    
    Returns:
        訓練結果の辞書:
        {
            "status": "success" or "error",
            "model_name": str,
            "symbol": str,
            "file_paths": {
                "price_prediction": str (optional),
                "momentum_intensity": str (optional),
                "direction_classification": str (optional),
                "volatility_prediction": str (optional),
                "volume_prediction": str (optional),
                "lightgbm_price_prediction": str (optional),
                "order_book_only": str (optional)
            },
            "results": {
                "price_prediction": {
                    "mae": float,
                    "rmse": float,
                    "mape": float,
                    "training_samples": int,
                    "validation_samples": int
                },
                "momentum_intensity": {
                    "mae": float,
                    "rmse": float,
                    "mape": float,
                    "direction_accuracy": float,
                    "training_samples": int,
                    "validation_samples": int
                } (optional),
                "direction_classification": {
                    "accuracy": float,
                    "training_samples": int,
                    "validation_samples": int
                } (optional),
                "volatility_prediction": {
                    "mae": float,
                    "rmse": float,
                    "mape": float,
                    "training_samples": int,
                    "validation_samples": int
                } (optional),
                "volume_prediction": {
                    "mae": float,
                    "rmse": float,
                    "mape": float,
                    "training_samples": int,
                    "validation_samples": int
                } (optional),
                "lightgbm_price_prediction": {
                    "mae": float,
                    "rmse": float,
                    "mape": float,
                    "training_samples": int,
                    "validation_samples": int
                } (optional),
                "order_book_only": {
                    "mae": float,
                    "rmse": float,
                    "mape": float,
                    "training_samples": int,
                    "validation_samples": int
                } (optional)
            },
            "error": str (if status == "error")
        }
    """
    # デフォルト値の設定
    if models is None:
        models = ["price", "momentum"]
    if timeframes is None:
        timeframes = [1, 5, 30]
    
    # データローダーの初期化
    if data_loader is None:
        use_exch_sim_db = DatabaseConfig.USE_EXCH_SIM_DB
        if use_exch_sim_db:
            data_loader = ExchSimDataLoader()
        else:
            data_loader = MarketDataLoader()
    
    # 特徴量エンジニアの初期化
    if feature_engineer is None:
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
    
    try:
        # 訓練データの期間を決定
        if end_date is None:
            end_date = datetime.now()
        
        if start_date is None:
            if training_window_days is None:
                training_window_days = 3  # デフォルト値
            start_date = end_date - timedelta(days=training_window_days)
        
        # タイムゾーンの統一（UTC）
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        
        print(f"Loading training data for {symbol} from {start_date} to {end_date}")
        df = data_loader.load_training_data(symbol, start_date, end_date)
        
        if len(df) == 0:
            raise ValueError(f"No data available for {symbol} in the specified period")
        
        # 最小サンプル数のチェック
        min_samples = TrainingConfig.MIN_SAMPLES
        if len(df) < min_samples:
            raise ValueError(
                f"Insufficient data: {len(df)} samples (minimum required: {min_samples})"
            )
        
        print(f"Loaded {len(df)} records")
        
        # データ統計情報を収集
        market_data_count = len(df)
        
        # 約定データ件数を取得
        execution_data_count = 0
        try:
            if isinstance(data_loader, ExchSimDataLoader):
                execution_data_count = data_loader.get_execution_count(symbol, start_date, end_date)
        except Exception as e:
            print(f"Warning: Failed to get execution count: {e}")
        
        # 簡易的なデータクオリティスコアを計算
        data_quality_score = _calculate_simple_quality_score(df)
        
        # 統計情報をまとめる
        training_data_stats = {
            "market_data_count": market_data_count,
            "execution_data_count": execution_data_count,
            "data_quality_score": data_quality_score
        }
        
        print(f"Training data stats: market_data={market_data_count}, execution_data={execution_data_count}, quality_score={data_quality_score:.1f}")
        
        # 特徴量エンジニアリング
        print("Engineering features...")
        df = feature_engineer.engineer_features(df)

        print(f"Total samples after feature engineering: {len(df)}")

        results = {}
        file_paths = {}

        # 価格予測モデルの訓練
        if "price" in models:
            try:
                print("Training price prediction model...")
                price_strategy = PricePredictionStrategy(
                    timeframes=timeframes,
                    prediction_horizon=prediction_horizon
                )

                # 全データを渡す（戦略内部で80:20に分割される）
                train_result = price_strategy.train(df)

                # 戦略が返したメトリクスをそのまま使用
                mae = train_result.get('mae', 0.0)
                rmse = train_result.get('rmse', 0.0)
                mape = train_result.get('mape', 0.0)
                training_samples = train_result.get('training_samples', 0)
                validation_samples = train_result.get('validation_samples', 0)

                print(f"[INFO] Using metrics from strategy internal validation:")
                print(f"  Training samples: {training_samples}, Validation samples: {validation_samples}")

                # モデルを保存
                model_dir = ModelConfig.MODEL_DIR
                os.makedirs(model_dir, exist_ok=True)

                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                price_model_path = os.path.join(
                    model_dir,
                    f'{model_name}_price_{symbol}_{timestamp}.joblib'
                )
                price_strategy.model.save(price_model_path)
                file_paths["price_prediction"] = price_model_path

                results["price_prediction"] = {
                    "mae": mae,
                    "rmse": rmse,
                    "mape": mape,
                    "training_samples": training_samples,
                    "validation_samples": validation_samples
                }

                print(f"Price prediction model trained:")
                print(f"  MAE: {mae:,.0f} JPY")
                print(f"  RMSE: {rmse:,.0f} JPY")
                print(f"  MAPE: {mape:.2f}%")
                print(f"  Saved to: {price_model_path}")
                
            except Exception as e:
                print(f"Error training price prediction model: {e}")
                import traceback
                traceback.print_exc()
                if "price" in models and len(models) == 1:
                    # 価格予測モデルのみを訓練しようとした場合、エラーを返す
                    raise
                # その他の場合は警告のみ
        
        # モメンタム強度モデルの訓練
        if "momentum" in models:
            try:
                print("Training momentum intensity model...")
                momentum_strategy = MomentumIntensityStrategy(
                    timeframes=timeframes,
                    prediction_horizon=prediction_horizon
                )

                # 全データを渡す（戦略内部で80:20に分割される）
                momentum_train_result = momentum_strategy.train(df)

                # 戦略が返したメトリクスをそのまま使用
                mae = momentum_train_result.get('mae', 0.0)
                rmse = momentum_train_result.get('rmse', 0.0)
                mape = momentum_train_result.get('mape', 0.0)
                direction_accuracy = momentum_train_result.get('direction_accuracy', 0.0)
                training_samples = momentum_train_result.get('training_samples', 0)
                validation_samples = momentum_train_result.get('validation_samples', 0)

                print(f"[INFO] Using metrics from strategy internal validation:")
                print(f"  Training samples: {training_samples}, Validation samples: {validation_samples}")

                # モデルを保存
                model_dir = ModelConfig.MODEL_DIR
                os.makedirs(model_dir, exist_ok=True)

                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                momentum_model_path = os.path.join(
                    model_dir,
                    f'{model_name}_momentum_{symbol}_{timestamp}.joblib'
                )
                momentum_strategy.model.save(momentum_model_path)
                file_paths["momentum_intensity"] = momentum_model_path

                results["momentum_intensity"] = {
                    "mae": mae,
                    "rmse": rmse,
                    "mape": mape,
                    "direction_accuracy": direction_accuracy,
                    "training_samples": training_samples,
                    "validation_samples": validation_samples
                }

                print(f"Momentum intensity model trained:")
                print(f"  MAE: {mae:.4f}%")
                print(f"  Direction Accuracy: {direction_accuracy:.2f}%")
                print(f"  Saved to: {momentum_model_path}")
                
            except Exception as e:
                print(f"Error training momentum intensity model: {e}")
                import traceback
                traceback.print_exc()
                if "momentum" in models and len(models) == 1:
                    # モメンタム強度モデルのみを訓練しようとした場合、エラーを返す
                    raise
                # その他の場合は警告のみ
        
        # 方向性分類モデルの訓練
        if "direction" in models:
            try:
                print("Training direction classification model...")
                direction_strategy = DirectionClassificationStrategy(
                    timeframes=timeframes,
                    prediction_horizon=prediction_horizon
                )

                # 全データを渡す（戦略内部で80:20に分割される）
                direction_train_result = direction_strategy.train(df)

                # 戦略が返したメトリクスをそのまま使用
                accuracy = direction_train_result.get('accuracy', 0.0)
                if accuracy <= 1.0:  # If it's a fraction, convert to percentage
                    accuracy = accuracy * 100
                training_samples = direction_train_result.get('training_samples', 0)
                validation_samples = direction_train_result.get('validation_samples', 0)

                print(f"[INFO] Using metrics from strategy internal validation:")
                print(f"  Training samples: {training_samples}, Validation samples: {validation_samples}")

                # モデルを保存
                model_dir = ModelConfig.MODEL_DIR
                os.makedirs(model_dir, exist_ok=True)

                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                direction_model_path = os.path.join(
                    model_dir,
                    f'{model_name}_direction_{symbol}_{timestamp}.joblib'
                )
                direction_strategy.model.save(direction_model_path)
                file_paths["direction_classification"] = direction_model_path

                results["direction_classification"] = {
                    "accuracy": accuracy,
                    "training_samples": training_samples,
                    "validation_samples": validation_samples
                }

                print(f"Direction classification model trained:")
                print(f"  Accuracy: {accuracy:.2f}%")
                print(f"  Saved to: {direction_model_path}")
                
            except Exception as e:
                print(f"Error training direction classification model: {e}")
                import traceback
                traceback.print_exc()
                if "direction" in models and len(models) == 1:
                    raise
        
        # ボラティリティ予測モデルの訓練
        if "volatility" in models:
            try:
                print("Training volatility prediction model...")
                volatility_strategy = VolatilityPredictionStrategy(
                    timeframes=timeframes,
                    prediction_horizon=prediction_horizon
                )

                # 全データを渡す（戦略内部で80:20に分割される）
                volatility_train_result = volatility_strategy.train(df)

                # 戦略が返したメトリクスをそのまま使用
                mae = volatility_train_result.get('mae', 0.0)
                rmse = volatility_train_result.get('rmse', 0.0)
                mape = volatility_train_result.get('mape', 0.0)
                training_samples = volatility_train_result.get('training_samples', 0)
                validation_samples = volatility_train_result.get('validation_samples', 0)

                print(f"[INFO] Using metrics from strategy internal validation:")
                print(f"  Training samples: {training_samples}, Validation samples: {validation_samples}")

                # モデルを保存
                model_dir = ModelConfig.MODEL_DIR
                os.makedirs(model_dir, exist_ok=True)

                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                volatility_model_path = os.path.join(
                    model_dir,
                    f'{model_name}_volatility_{symbol}_{timestamp}.joblib'
                )
                volatility_strategy.model.save(volatility_model_path)
                file_paths["volatility_prediction"] = volatility_model_path

                results["volatility_prediction"] = {
                    "mae": mae,
                    "rmse": rmse,
                    "mape": mape,
                    "training_samples": training_samples,
                    "validation_samples": validation_samples
                }

                print(f"Volatility prediction model trained:")
                print(f"  MAE: {mae:.6f}")
                print(f"  RMSE: {rmse:.6f}")
                print(f"  MAPE: {mape:.2f}%")
                print(f"  Saved to: {volatility_model_path}")
                
            except Exception as e:
                print(f"Error training volatility prediction model: {e}")
                import traceback
                traceback.print_exc()
                if "volatility" in models and len(models) == 1:
                    raise
        
        # 取引量予測モデルの訓練
        if "volume" in models:
            try:
                print("Training volume prediction model...")
                volume_strategy = VolumePredictionStrategy(
                    timeframes=timeframes,
                    prediction_horizon=prediction_horizon
                )

                # 全データを渡す（戦略内部で80:20に分割される）
                volume_train_result = volume_strategy.train(df)

                # 戦略が返したメトリクスをそのまま使用
                mae = volume_train_result.get('mae', 0.0)
                rmse = volume_train_result.get('rmse', 0.0)
                mape = volume_train_result.get('mape', 0.0)
                training_samples = volume_train_result.get('training_samples', 0)
                validation_samples = volume_train_result.get('validation_samples', 0)

                print(f"[INFO] Using metrics from strategy internal validation:")
                print(f"  Training samples: {training_samples}, Validation samples: {validation_samples}")

                # モデルを保存
                model_dir = ModelConfig.MODEL_DIR
                os.makedirs(model_dir, exist_ok=True)

                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                volume_model_path = os.path.join(
                    model_dir,
                    f'{model_name}_volume_{symbol}_{timestamp}.joblib'
                )
                volume_strategy.model.save(volume_model_path)
                file_paths["volume_prediction"] = volume_model_path

                results["volume_prediction"] = {
                    "mae": mae,
                    "rmse": rmse,
                    "mape": mape,
                    "training_samples": training_samples,
                    "validation_samples": validation_samples
                }

                print(f"Volume prediction model trained:")
                print(f"  MAE: {mae:.2f}")
                print(f"  RMSE: {rmse:.2f}")
                print(f"  MAPE: {mape:.2f}%")
                print(f"  Saved to: {volume_model_path}")
                
            except Exception as e:
                print(f"Error training volume prediction model: {e}")
                import traceback
                traceback.print_exc()
                if "volume" in models and len(models) == 1:
                    raise
        
        # LightGBM価格予測モデルの訓練
        if "lightgbm_price" in models:
            try:
                # LightGBM戦略を遅延インポート（pandas 2.1.3との互換性問題を回避）
                try:
                    from strategy.lightgbm_price_prediction_strategy import LightGBMPricePredictionStrategy
                except ImportError as e:
                    if "libomp" in str(e).lower() or "Library not loaded" in str(e):
                        raise ImportError(
                            f"LightGBM requires libomp library. "
                            f"Please install it: brew install libomp\n"
                            f"Then create a symlink: sudo mkdir -p /usr/local/opt/libomp/lib && "
                            f"sudo ln -sf /opt/homebrew/opt/libomp/lib/libomp.dylib /usr/local/opt/libomp/lib/libomp.dylib\n"
                            f"Or set environment variable: export DYLD_LIBRARY_PATH=/opt/homebrew/opt/libomp/lib:$DYLD_LIBRARY_PATH"
                        )
                    raise
                
                print("Training LightGBM price prediction model...")
                lightgbm_strategy = LightGBMPricePredictionStrategy(
                    timeframes=timeframes,
                    prediction_horizon=prediction_horizon
                )

                # 全データを渡す（戦略内部で80:20に分割される）
                lightgbm_train_result = lightgbm_strategy.train(df)

                # 戦略が返したメトリクスをそのまま使用
                mae = lightgbm_train_result.get('mae', 0.0)
                rmse = lightgbm_train_result.get('rmse', 0.0)
                mape = lightgbm_train_result.get('mape', 0.0)
                training_samples = lightgbm_train_result.get('training_samples', 0)
                validation_samples = lightgbm_train_result.get('validation_samples', 0)

                print(f"[INFO] Using metrics from strategy internal validation:")
                print(f"  Training samples: {training_samples}, Validation samples: {validation_samples}")

                # モデルを保存
                model_dir = ModelConfig.MODEL_DIR
                os.makedirs(model_dir, exist_ok=True)

                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                lightgbm_model_path = os.path.join(
                    model_dir,
                    f'{model_name}_lightgbm_price_{symbol}_{timestamp}.joblib'
                )
                lightgbm_strategy.model.save(lightgbm_model_path)
                file_paths["lightgbm_price_prediction"] = lightgbm_model_path

                results["lightgbm_price_prediction"] = {
                    "mae": mae,
                    "rmse": rmse,
                    "mape": mape,
                    "training_samples": training_samples,
                    "validation_samples": validation_samples
                }

                print(f"LightGBM price prediction model trained:")
                print(f"  MAE: {mae:,.0f} JPY")
                print(f"  RMSE: {rmse:,.0f} JPY")
                print(f"  MAPE: {mape:.2f}%")
                print(f"  Saved to: {lightgbm_model_path}")
                
            except Exception as e:
                print(f"Error training LightGBM price prediction model: {e}")
                import traceback
                traceback.print_exc()
                if "lightgbm_price" in models and len(models) == 1:
                    raise
        
        # Order Book Onlyモデルの訓練
        if "order_book_only" in models:
            try:
                print("Training order book only model...")
                orderbook_strategy = OrderBookOnlyStrategy(
                    timeframes=timeframes,
                    prediction_horizon=prediction_horizon
                )

                # 全データを渡す（戦略内部で80:20に分割される）
                orderbook_train_result = orderbook_strategy.train(df)

                # 戦略が返したメトリクスをそのまま使用
                mae = orderbook_train_result.get('mae', 0.0)
                rmse = orderbook_train_result.get('rmse', 0.0)
                mape = orderbook_train_result.get('mape', 0.0)
                training_samples = orderbook_train_result.get('training_samples', 0)
                validation_samples = orderbook_train_result.get('validation_samples', 0)

                print(f"[INFO] Using metrics from strategy internal validation:")
                print(f"  Training samples: {training_samples}, Validation samples: {validation_samples}")

                # モデルを保存
                model_dir = ModelConfig.MODEL_DIR
                os.makedirs(model_dir, exist_ok=True)

                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                orderbook_model_path = os.path.join(
                    model_dir,
                    f'{model_name}_order_book_only_{symbol}_{timestamp}.joblib'
                )
                orderbook_strategy.model.save(orderbook_model_path)
                file_paths["order_book_only"] = orderbook_model_path

                results["order_book_only"] = {
                    "mae": mae,
                    "rmse": rmse,
                    "mape": mape,
                    "training_samples": training_samples,
                    "validation_samples": validation_samples
                }

                print(f"Order book only model trained:")
                print(f"  MAE: {mae:,.0f} JPY")
                print(f"  RMSE: {rmse:,.0f} JPY")
                print(f"  MAPE: {mape:.2f}%")
                print(f"  Saved to: {orderbook_model_path}")
                
            except Exception as e:
                print(f"Error training order book only model: {e}")
                import traceback
                traceback.print_exc()
                if "order_book_only" in models and len(models) == 1:
                    raise
        
        # 結果を返す
        return {
            "status": "success",
            "model_name": model_name,
            "symbol": symbol,
            "file_paths": file_paths,
            "results": results,
            "training_start_time": start_date.isoformat() if start_date else None,
            "training_end_time": end_date.isoformat() if end_date else None,
            "training_data_stats": training_data_stats
        }
        
    except Exception as e:
        print(f"Error in train_models: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "model_name": model_name,
            "symbol": symbol,
            "error": str(e)
        }
    finally:
        # data_loaderは呼び出し元で管理されるため、ここではcloseしない
        # 新規作成した場合のみcloseする
        pass

