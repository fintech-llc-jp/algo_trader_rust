
import logging
import logging.handlers
import asyncio
from datetime import datetime, timedelta, timezone
from collections import deque
import json
import os
import pandas as pd
import numpy as np
from typing import Dict, Optional
import psycopg2

from config.settings import PredictionTrackerConfig, DatabaseConfig

# Configure dedicated logger for prediction verification with rotation
tracker_logger = logging.getLogger("prediction_tracker")
tracker_logger.setLevel(logging.INFO)

# Remove existing handlers to avoid duplicates
if tracker_logger.handlers:
    tracker_logger.handlers.clear()

# Create rotating file handler
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "prediction_verification.log")
handler = logging.handlers.RotatingFileHandler(
    log_file,
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=5  # 5つのバックアップファイルを保持
)
formatter = logging.Formatter('%(asctime)s - %(message)s')
handler.setFormatter(formatter)
tracker_logger.addHandler(handler)

class PredictionMetrics:
    """予測精度のメトリクス"""
    def __init__(self):
        self.errors_by_horizon = {
            '1m': [],
            '5m': [],
            '10m': []
        }
    
    def add_verification(self, horizon: str, error: float, error_pct: float):
        self.errors_by_horizon[horizon].append({
            'error': error,
            'error_pct': error_pct,
            'timestamp': datetime.now(timezone.utc)
        })
        
        # 最新1000件のみ保持
        if len(self.errors_by_horizon[horizon]) > 1000:
            self.errors_by_horizon[horizon] = self.errors_by_horizon[horizon][-1000:]
    
    def get_metrics(self, horizon: str, window_hours: int = 24) -> Optional[Dict]:
        """指定時間窓のメトリクスを計算"""
        errors = self.errors_by_horizon.get(horizon, [])
        
        if not errors:
            return None
        
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        recent_errors = [
            e for e in errors 
            if e['timestamp'] >= cutoff
        ]
        
        if not recent_errors:
            return None
        
        error_values = [e['error'] for e in recent_errors]
        error_pct_values = [e['error_pct'] for e in recent_errors]
        
        return {
            'horizon': horizon,
            'window_hours': window_hours,
            'sample_count': len(recent_errors),
            'mae': float(np.mean(np.abs(error_values))),
            'rmse': float(np.sqrt(np.mean(np.array(error_values) ** 2))),
            'mape': float(np.mean(np.abs(error_pct_values))),
            'max_error': float(np.max(np.abs(error_values))),
            'min_error': float(np.min(np.abs(error_values)))
        }


class PredictionTracker:
    """
    Prediction Tracker: Tracks and verifies predictions in real-time.
    Manages separate models for 1m, 5m, and 10m horizons.
    """
    def __init__(self, symbol: str, price_model, data_loader, feature_engineer):
        self.symbol = symbol
        # We ignore the passed price_model for shadow mode as we need specific horizon models
        self.models = {} 
        self.data_loader = data_loader
        self.feature_engineer = feature_engineer
        
        # Horizons to track: (name, minutes, seconds)
        self.horizons = {
            '1m': 60,
            '5m': 300,
            '10m': 600
        }
        
        # Store the last verification error for each horizon to feed back into next prediction
        self.last_prediction_errors = {
            '1m': 0.0,
            '5m': 0.0,
            '10m': 0.0
        }
        
        self.pending_predictions = deque()
        self.running = False
        self._task = None
        
        # 設定の読み込み
        self.config = PredictionTrackerConfig
        self.cycle_interval = self.config.CYCLE_INTERVAL_SECONDS
        self.model_retrain_interval_hours = self.config.RETRAIN_INTERVAL_HOURS
        self.model_training_window_hours = self.config.TRAINING_WINDOW_HOURS
        self.use_synthetic_data = self.config.USE_SYNTHETIC_DATA
        self.min_samples_training = self.config.MIN_SAMPLES_FOR_TRAINING
        self.min_samples_prediction = self.config.MIN_SAMPLES_FOR_PREDICTION
        
        self.last_model_retrain_time: Optional[datetime] = None
        
        # メトリクス収集
        self.metrics = PredictionMetrics()
        
        # データベース接続
        try:
            self.db_conn = psycopg2.connect(
                DatabaseConfig.get_connection_string()
            )
            self.db_conn.autocommit = True
        except Exception as e:
            tracker_logger.error(f"Failed to connect to database: {e}")
            self.db_conn = None
        
    async def start(self):
        if self.running:
            return
        self.running = True
        
        # Train/Init models on start
        print(f"[Tracker] Initializing shadow models for {self.symbol} (1m, 5m, 10m)...")
        await self._init_models()
        
        self._task = asyncio.create_task(self._loop())
        tracker_logger.info(f"PredictionTracker started for {self.symbol}")
        print(f"[Tracker] Started background prediction verification for {self.symbol}")

    async def _init_models(self):
        """Train temporary models for each horizon using recent data"""
        loop = asyncio.get_running_loop()
        
        # Load training data
        # Use UTC to match DB timestamps
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(hours=self.model_training_window_hours)
        
        df = None
        try:
            df = await loop.run_in_executor(
                None,
                lambda: self.data_loader.load_training_data(self.symbol, start_date, end_date, skip_min_samples_check=True)
            )
        except Exception as e:
            tracker_logger.error(f"Error loading init data: {e}")
            print(f"[Tracker] Error loading init data: {e}")
            df = None

        if df is None or len(df) < self.min_samples_training:
            if self.use_synthetic_data:
                tracker_logger.warning("No real data for init. Generating SYNTHETIC data (USE_SYNTHETIC_DATA=true)...")
                print("[Tracker] No real data for init. Generating SYNTHETIC data for demonstration...")
                # Generate synthetic data
                periods = self.model_training_window_hours * 3600
                timestamps = [end_date - timedelta(seconds=i) for i in range(periods, 0, -1)]
                
                mid_prices = 4000000 + np.linspace(0, 1000, periods) + np.random.normal(0, 5, periods)
                
                data = {
                    'symbol': [self.symbol] * periods,
                    'mid_price': mid_prices,
                    'spread': [100] * periods,
                    'bid_price_1': mid_prices - 50,
                    'ask_price_1': mid_prices + 50,
                    'bid_qty_1': [1.0] * periods, 
                    'ask_qty_1': [1.0] * periods,
                    'bid_depth_5': [5.0] * periods, 
                    'ask_depth_5': [5.0] * periods, 
                    'order_imbalance': [0.0] * periods,
                    'volume_buy': np.random.uniform(0, 1, periods),
                    'volume_sell': np.random.uniform(0, 1, periods),
                    'volume_total': np.random.uniform(0, 2, periods),
                }
                df = pd.DataFrame(data, index=timestamps)
            else:
                error_msg = f"Insufficient data for {self.symbol} (got {len(df) if df is not None else 0} samples, need {self.min_samples_training})"
                tracker_logger.error(error_msg)
                print(f"[Tracker] ERROR: {error_msg}")
                raise ValueError(error_msg)
            
        if df is None or len(df) < self.min_samples_training:
            error_msg = f"Insufficient data for initial training (got {len(df) if df is not None else 0} samples, need {self.min_samples_training})"
            tracker_logger.warning(error_msg)
            print(f"[Tracker] Warn: {error_msg}")
            return

        try:
            features = await loop.run_in_executor(
                    None,
                    lambda: self.feature_engineer.engineer_features(df)
            )
            feature_cols_v1 = self.feature_engineer.get_feature_columns()

            from models.price_prediction_model import PricePredictionModel
            
            for name, seconds in self.horizons.items():
                print(f"[Tracker] Training shadow model for {name} (Stage 1)...")
                
                # --- Stage 1: Train Base Model ---
                y_col = f'target_{name}'
                df_train = features.copy()
                df_train[y_col] = df_train['mid_price'].shift(-seconds)
                
                df_v1 = df_train.dropna(subset=feature_cols_v1 + [y_col])
                
                if len(df_v1) < 50:
                    print(f"[Tracker] Warn: Not enough samples for {name}")
                    continue
                    
                X_v1 = df_v1[feature_cols_v1].values
                y_v1 = df_v1[y_col].values
                
                model_v1 = PricePredictionModel()
                model_v1.feature_columns = feature_cols_v1
                await loop.run_in_executor(None, lambda: model_v1.train(X_v1, y_v1))
                
                # --- Stage 2: Generate Residuals & Train Feedback Model ---
                print(f"[Tracker] generating residuals for {name}...")
                
                # Predict in-sample (Note: this is slightly biased but simplest for shadow mode)
                y_pred_v1 = model_v1.predict(X_v1)
                residuals = y_v1 - y_pred_v1 # Actual - Predicted
                
                # Add 'prev_error' feature: Shift residuals by 1 step forward (lag)
                # We need to map residuals back to the original timestamps
                df_v1['residual'] = residuals
                df_v1['prev_error'] = df_v1['residual'].shift(1).fillna(0)
                
                # Define Feature Set V2 (Original + prev_error)
                feature_cols_v2 = feature_cols_v1 + ['prev_error']
                
                # Filter again for NaNs created by shift
                df_v2 = df_v1.dropna(subset=['prev_error'])
                
                X_v2 = df_v2[feature_cols_v2].values
                y_v2 = df_v2[y_col].values
                
                print(f"[Tracker] Training shadow model for {name} (Stage 2: Feedback)...")
                model_v2 = PricePredictionModel()
                model_v2.feature_columns = feature_cols_v2
                
                await loop.run_in_executor(None, lambda: model_v2.train(X_v2, y_v2))
                self.models[name] = model_v2
                
                # Estimate current error for init
                self.last_prediction_errors[name] = 0.0 # Start neutral
                print(f"[Tracker] {name} Feedback Model ready.")
                
        except Exception as e:
            print(f"[Tracker] Error initializing models: {e}")

    async def stop(self):
        self.running = False
        if self._task:
            await self._task
        if self.db_conn:
            self.db_conn.close()

    async def _loop(self):
        while self.running:
            try:
                await self._run_cycle()
                
                # モデル再訓練チェック
                await self._check_and_retrain_models()
            except Exception as e:
                tracker_logger.error(f"Error in prediction cycle: {e}")
                print(f"[Tracker] Error: {e}")
            
            await asyncio.sleep(self.cycle_interval)
    
    async def _check_and_retrain_models(self):
        """必要に応じてモデルを再訓練"""
        now = datetime.now(timezone.utc)
        
        if self.last_model_retrain_time is None:
            self.last_model_retrain_time = now
            return
        
        hours_since_retrain = (now - self.last_model_retrain_time).total_seconds() / 3600
        
        if hours_since_retrain >= self.model_retrain_interval_hours:
            tracker_logger.info(f"Retraining models (last retrain: {self.last_model_retrain_time})")
            await self._retrain_models()
            self.last_model_retrain_time = now
    
    async def _retrain_models(self):
        """モデルを再訓練"""
        try:
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(hours=self.model_training_window_hours)
            loop = asyncio.get_running_loop()
            
            df = await loop.run_in_executor(
                None,
                lambda: self.data_loader.load_training_data(
                    self.symbol, start_date, end_date, skip_min_samples_check=True
                )
            )
            
            if df is None or len(df) < self.min_samples_training:
                tracker_logger.warning("Insufficient data for retraining, skipping")
                return
            
            # 既存の_init_modelsと同じロジックで再訓練
            await self._init_models()
            tracker_logger.info("Models retrained successfully")
        except Exception as e:
            tracker_logger.error(f"Failed to retrain models: {e}")
            print(f"[Tracker] Failed to retrain models: {e}")

    async def _run_cycle(self):
        # Use UTC
        now = datetime.now(timezone.utc)
        loop = asyncio.get_running_loop()
        
        # 1. Fetch current data
        end_time = now
        start_time = now - timedelta(minutes=15) # Need enough context for features
        
        try:
            df = await loop.run_in_executor(
                None, 
                lambda: self.data_loader.load_training_data(self.symbol, start_time, end_time, skip_min_samples_check=True)
            )
        except Exception as e:
            tracker_logger.warning(f"Failed to load market data: {e}")
            df = None
        
        # データがない場合の処理を改善
        if df is None or len(df) == 0:
            if self.use_synthetic_data:
                tracker_logger.warning(f"No real data. Generating synthetic data (USE_SYNTHETIC_DATA=true)...")
                print(f"[Tracker] No real data. Generating synthetic data for demonstration...")
                # Generate synthetic data
                timestamps = [end_time - timedelta(seconds=i) for i in range(300, -1, -1)] # 5 mins history
                t = np.linspace(0, 10, len(timestamps))
                
                mid_prices = 4000000 + 100 * np.sin(t) + np.random.normal(0, 5, len(timestamps))
                
                data = {
                    'symbol': [self.symbol] * len(timestamps),
                    'mid_price': mid_prices,
                    'spread': [100] * len(timestamps),
                    'bid_price_1': mid_prices - 50,
                    'ask_price_1': mid_prices + 50,
                    'bid_qty_1': [1.0] * len(timestamps),
                    'ask_qty_1': [1.0] * len(timestamps),
                    'bid_depth_5': [5.0] * len(timestamps),
                    'ask_depth_5': [5.0] * len(timestamps),
                    'order_imbalance': [0.0] * len(timestamps),
                    'volume_buy': [0.1] * len(timestamps),
                    'volume_sell': [0.1] * len(timestamps),
                    'volume_total': [0.2] * len(timestamps),
                }
                df = pd.DataFrame(data, index=timestamps)
            else:
                tracker_logger.warning(
                    f"No data available for {self.symbol} between {start_time} and {end_time}. "
                    f"Skipping this cycle."
                )
                return
        
        # 最小データ要件のチェック
        if len(df) < self.min_samples_prediction:
            tracker_logger.warning(
                f"Insufficient data points ({len(df)}) for prediction. Skipping."
            )
            return

        current_price = df['mid_price'].iloc[-1]
        current_ts = df.index[-1]
        
        # 2. Verify pending predictions
        remaining_predictions = deque()
        
        while self.pending_predictions:
            pred = self.pending_predictions.popleft()
            target_ts = pred['target_timestamp']
            
            if current_ts >= target_ts:
                self._verify_prediction(pred, current_price, current_ts)
            else:
                remaining_predictions.append(pred)
        
        self.pending_predictions = remaining_predictions

        # 3. Make NEW predictions for all horizons
        await self._make_predictions(df, now, current_price)

    def _verify_prediction(self, pred, actual_price, actual_ts):
        predicted = pred['predicted_price']
        horizon = pred['horizon_name']
        pred_ts = pred['timestamp']
        
        error = actual_price - predicted
        error_pct = (error / actual_price) * 100
        
        # Log result
        log_entry = {
            'event': 'VERIFICATION',
            'horizon': horizon,
            'prediction_time': str(pred_ts),
            'target_time': str(pred['target_timestamp']),
            'actual_time': str(actual_ts),
            'predicted_price': round(predicted, 2),
            'actual_price': round(actual_price, 2),
            'error': round(error, 2),
            'error_pct': round(error_pct, 4)
        }
        tracker_logger.info(json.dumps(log_entry))
        print(f"[Tracker] Verified {horizon}: Pred={predicted:.1f}, Act={actual_price:.1f}, Err={error:.1f} ({error_pct:.3f}%)")
        
        # メトリクスに追加
        self.metrics.add_verification(horizon, error, error_pct)
        
        # データベースに保存
        if self.db_conn:
            try:
                with self.db_conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO prediction_tracker_verifications
                        (prediction_id, symbol, horizon, prediction_timestamp,
                         target_timestamp, actual_timestamp, predicted_price,
                         actual_price, error, error_pct)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        pred.get('id'), self.symbol, horizon,
                        pred_ts, pred['target_timestamp'], actual_ts,
                        predicted, actual_price, error, error_pct
                    ))
            except Exception as e:
                tracker_logger.error(f"Failed to save verification to DB: {e}")
        
        # Store for feedback loop (Residual Learning)
        # Error = Actual - Predicted
        self.last_prediction_errors[horizon] = error

    async def _make_predictions(self, df, now, current_price):
        loop = asyncio.get_running_loop()
        
        # Feature Engineering
        features = await loop.run_in_executor(
            None,
            lambda: self.feature_engineer.engineer_features(df)
        )
        latest_features = features.tail(1)
        
        # Predict for each horizon
        for name, model in self.models.items():
            try:
                # Use the X_latest (needs to match feature columns of model)
                # Assuming features don't change between calls/restarts too much
                
                # Check columns safety
                # model.feature_columns vs latest_features.columns
                # Just passing latest_features should be handled by model.predict usually if using dataframe, 
                # but PricePredictionModel expects numpy array?
                # Let's check model.predict signature. It calls scalar.transform(X).
                # latest_features is DataFrame.
                
                # Ensure we pass the right columns in right order
                # Inject 'prev_error' feature manually for inference
                # We need to add it to the DF before extracting values
                
                # Check if model expects 'prev_error'
                if 'prev_error' in model.feature_columns:
                    latest_features_with_error = latest_features.copy()
                    error_val = self.last_prediction_errors.get(name, 0.0)
                    latest_features_with_error['prev_error'] = error_val
                    X_input = latest_features_with_error[model.feature_columns].values
                    # Print debug info occasionally?
                else:
                    X_input = latest_features[model.feature_columns].values
                
                predictions = model.predict(X_input)
                pred_price = float(predictions[-1])
                
                seconds = self.horizons[name]
                
                # Log prediction
                log_entry = {
                    'event': 'PREDICTION',
                    'horizon': name,
                    'is_feedback_enabled': 'prev_error' in model.feature_columns,
                    'timestamp': str(now),
                    'current_price': round(current_price, 2),
                    'predicted_price': round(pred_price, 2),
                    'input_prev_error': round(self.last_prediction_errors.get(name, 0.0), 2)
                }
                tracker_logger.info(json.dumps(log_entry))
                
                # データベースに保存
                prediction_id = None
                if self.db_conn:
                    try:
                        with self.db_conn.cursor() as cur:
                            price_change_pct = ((pred_price - current_price) / current_price) * 100 if current_price > 0 else 0.0
                            cur.execute("""
                                INSERT INTO prediction_tracker_predictions
                                (symbol, horizon, prediction_timestamp, target_timestamp,
                                 current_price, predicted_price, price_change_pct,
                                 prev_error, is_feedback_enabled)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                RETURNING id
                            """, (
                                self.symbol, name, now, now + timedelta(seconds=seconds),
                                current_price, pred_price, price_change_pct,
                                self.last_prediction_errors.get(name, 0.0),
                                'prev_error' in model.feature_columns
                            ))
                            prediction_id = cur.fetchone()[0]
                    except Exception as e:
                        tracker_logger.error(f"Failed to save prediction to DB: {e}")
                
                # Store for verification
                self.pending_predictions.append({
                    'id': prediction_id,
                    'timestamp': now,
                    'horizon_name': name,
                    'target_timestamp': now + timedelta(seconds=seconds),
                    'predicted_price': pred_price,
                    'current_price_at_pred': current_price
                })
            except Exception as e:
                print(f"[Tracker] Pred failed for {name}: {e}")

