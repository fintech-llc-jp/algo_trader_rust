"""
Periodic Model Retrainer
バックグラウンドで定期的にモデルを再訓練するクラス
"""
import os
import asyncio
from datetime import datetime, timedelta
from typing import Optional
import logging

from config.settings import TrainingConfig
from api.training_service import train_models

logger = logging.getLogger(__name__)


class PeriodicRetrainer:
    """
    バックグラウンドで定期的にモデルを再訓練するクラス
    BackgroundDataLoaderと同様のパターンで実装
    """
    
    def __init__(
        self,
        symbol: str = "G_FX_BTCJPY",
        feature_engineer=None,
        data_loader=None
    ):
        """
        初期化
        
        Args:
            symbol: 銘柄（デフォルト: "G_FX_BTCJPY"）
            feature_engineer: 特徴量エンジニア（Noneの場合は新規作成）
            data_loader: データローダー（Noneの場合は新規作成）
        """
        self.symbol = symbol
        self.feature_engineer = feature_engineer
        self.data_loader = data_loader
        
        # 設定の読み込み
        self.enabled = TrainingConfig.RETRAIN_ENABLED
        self.interval_hours = TrainingConfig.RETRAIN_INTERVAL_HOURS
        self.training_window_days = TrainingConfig.RETRAIN_TRAINING_WINDOW_DAYS
        
        # 状態管理
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()
        
        # 最後の訓練時刻
        self.last_training_time: Optional[datetime] = None
        
        # デフォルトのモデル名（定期訓練用）
        self.default_model_name = f"auto_retrained_{symbol}"
        
        logger.info(
            f"PeriodicRetrainer initialized: symbol={symbol}, "
            f"enabled={self.enabled}, interval={self.interval_hours}h, "
            f"window={self.training_window_days}d"
        )
    
    async def start(self):
        """バックグラウンドタスクを開始"""
        if self.running:
            logger.warning("PeriodicRetrainer is already running")
            return
        
        if not self.enabled:
            logger.info("PeriodicRetrainer is disabled (RETRAIN_ENABLED=false)")
            return
        
        self.running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"PeriodicRetrainer started for {self.symbol}")
    
    async def stop(self):
        """バックグラウンドタスクを停止"""
        self.running = False
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PeriodicRetrainer stopped")
    
    async def _loop(self):
        """メインループ"""
        # 初回実行までの待機時間を計算（起動直後は実行しない）
        # 最初の実行は interval_hours 後
        await asyncio.sleep(self.interval_hours * 3600)
        
        while self.running:
            try:
                await self._retrain()
            except Exception as e:
                logger.error(f"Error in periodic retrainer: {e}", exc_info=True)
            
            # 次の実行まで待機
            await asyncio.sleep(self.interval_hours * 3600)
    
    async def _retrain(self):
        """モデルを再訓練"""
        async with self.lock:
            if not self.running:
                return
            
            logger.info(
                f"Starting periodic retraining for {self.symbol} "
                f"(window={self.training_window_days}d)"
            )
            
            try:
                # モデル名にタイムスタンプを追加（一意性を確保）
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                model_name = f"{self.default_model_name}_{timestamp}"
                
                # 訓練を実行（非同期で実行するため、executorを使用）
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: train_models(
                        symbol=self.symbol,
                        model_name=model_name,
                        training_window_days=self.training_window_days,
                        models=["price", "momentum"],
                        timeframes=[1, 5, 30],
                        prediction_horizon=60,
                        feature_engineer=self.feature_engineer,
                        data_loader=self.data_loader
                    )
                )
                
                if result["status"] == "success":
                    self.last_training_time = datetime.now()
                    logger.info(
                        f"Periodic retraining completed successfully for {self.symbol}. "
                        f"Model: {model_name}"
                    )
                    
                    # メタデータへの登録
                    # train_models はモデルファイルを保存するが、メタデータへの登録は行わない
                    # そのため、ModelManagerを取得して登録する必要がある
                    try:
                        from api.model_manager import ModelManager
                        from config.settings import DatabaseConfig
                        
                        # DBベースでModelManagerを初期化
                        try:
                            connection_string = DatabaseConfig.get_connection_string(db_name=DatabaseConfig.NAME)
                            model_manager = ModelManager(connection_string=connection_string, use_file_backend=False)
                        except Exception as e:
                            logger.warning(f"Failed to initialize ModelManager with database: {e}, falling back to file backend")
                            model_manager = ModelManager(use_file_backend=True)
                        
                        # 訓練期間の時刻を取得
                        training_start_time = None
                        training_end_time = None
                        if result.get("training_start_time"):
                            try:
                                training_start_time = datetime.fromisoformat(result["training_start_time"].replace('Z', '+00:00'))
                            except:
                                try:
                                    training_start_time = datetime.fromisoformat(result["training_start_time"])
                                except:
                                    pass
                        if result.get("training_end_time"):
                            try:
                                training_end_time = datetime.fromisoformat(result["training_end_time"].replace('Z', '+00:00'))
                            except:
                                try:
                                    training_end_time = datetime.fromisoformat(result["training_end_time"])
                                except:
                                    pass
                        
                        # 価格予測モデルの登録
                        if "price_prediction" in result.get("file_paths", {}):
                            price_metrics = result.get("results", {}).get("price_prediction", {})
                            model_manager.register_model(
                                model_name=model_name,
                                model_type="price_prediction",
                                symbol=self.symbol,
                                file_path=result["file_paths"]["price_prediction"],
                                training_window_days=self.training_window_days,
                                metrics=price_metrics,
                                is_active=False,
                                training_start_time=training_start_time,
                                training_end_time=training_end_time
                            )
                        
                        # モメンタム強度モデルの登録
                        if "momentum_intensity" in result.get("file_paths", {}):
                            momentum_metrics = result.get("results", {}).get("momentum_intensity", {})
                            model_manager.register_model(
                                model_name=model_name,
                                model_type="momentum_intensity",
                                symbol=self.symbol,
                                file_path=result["file_paths"]["momentum_intensity"],
                                training_window_days=self.training_window_days,
                                metrics=momentum_metrics,
                                is_active=False,
                                training_start_time=training_start_time,
                                training_end_time=training_end_time
                            )
                        
                        logger.info(f"Models registered in metadata: {model_name}")
                        model_manager.close()
                    except Exception as e:
                        logger.warning(f"Failed to register models in metadata: {e}")
                else:
                    error_msg = result.get("error", "Unknown error")
                    logger.error(
                        f"Periodic retraining failed for {self.symbol}: {error_msg}"
                    )
                    
            except Exception as e:
                logger.error(
                    f"Exception during periodic retraining for {self.symbol}: {e}",
                    exc_info=True
                )
    
    def get_status(self) -> dict:
        """現在のステータスを取得"""
        return {
            "running": self.running,
            "enabled": self.enabled,
            "interval_hours": self.interval_hours,
            "training_window_days": self.training_window_days,
            "symbol": self.symbol,
            "last_training_time": (
                self.last_training_time.isoformat() 
                if self.last_training_time else None
            )
        }

