"""
トレーニング専用FastAPIアプリケーション
モデルのトレーニングを実行する独立したAPIサーバー
"""
import os
import sys
import asyncio
from datetime import datetime
from typing import Optional, Dict
import uuid

from fastapi import FastAPI, HTTPException, BackgroundTasks
from contextlib import asynccontextmanager

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 共通モジュールのインポート
from api.shared.logger import setup_logger
from api.shared.models import RetrainRequest, RetrainResponse, RetrainStatusResponse

# ロガーの設定
logger = setup_logger("training_api")

# その他のインポート
from data.data_loader import MarketDataLoader
from data.exch_sim_data_loader import ExchSimDataLoader
from data.feature_engineering import FeatureEngineer
from data.configurable_feature_engineering import ConfigurableFeatureEngineer
from api.training_service import train_models
from api.model_manager import ModelManager
from config.settings import DatabaseConfig

# グローバル変数
feature_engineer: Optional[FeatureEngineer] = None
data_loader: Optional[MarketDataLoader] = None
model_manager: Optional[ModelManager] = None

# 訓練ジョブの状態管理
training_jobs: Dict[str, Dict] = {}

# トレーニングジョブの同時実行制限
MAX_CONCURRENT_TRAINING_JOBS = int(os.getenv('MAX_CONCURRENT_TRAINING_JOBS', '2'))
training_queue = asyncio.Queue()
active_training_jobs = set()
training_lock = asyncio.Lock()


def _job_cancel_requested(job_id: str) -> bool:
    return bool(training_jobs.get(job_id, {}).get("cancel_requested", False))


def _mark_job_stopped(job_id: str, message: str = "Training cancelled") -> None:
    if job_id not in training_jobs:
        return
    training_jobs[job_id]["status"] = "stopped"
    training_jobs[job_id]["message"] = message
    training_jobs[job_id]["progress"] = training_jobs[job_id].get("progress", 0.0)
    training_jobs[job_id]["result"] = training_jobs[job_id].get("result")
    training_jobs[job_id]["cancel_requested"] = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリケーションのライフサイクル管理"""
    global feature_engineer, data_loader, model_manager
    
    # 起動時の初期化
    logger.info("Initializing Training API...")
    try:
        # データローダーの初期化
        use_exch_sim_db = os.getenv('USE_EXCH_SIM_DB', 'false').lower() == 'true'
        if use_exch_sim_db:
            logger.info("Using ExchSimDataLoader (exch_sim database)")
            data_loader = ExchSimDataLoader()
        else:
            logger.info("Using MarketDataLoader (algo_trader database)")
            data_loader = MarketDataLoader()
        
        # 特徴量エンジニアの初期化
        feature_set_name = os.getenv('FEATURE_SET_NAME', 'standard_features')
        use_configurable = os.getenv('USE_CONFIGURABLE_FEATURES', 'true').lower() == 'true'
        
        if use_configurable:
            try:
                feature_engineer = ConfigurableFeatureEngineer(feature_set_name=feature_set_name)
                logger.info(f"Using ConfigurableFeatureEngineer with feature set: {feature_set_name}")
            except Exception as e:
                logger.warning(f"Failed to initialize ConfigurableFeatureEngineer: {e}")
                logger.info("Falling back to standard FeatureEngineer")
                feature_engineer = FeatureEngineer()
        else:
            feature_engineer = FeatureEngineer()
            logger.info("Using standard FeatureEngineer")
        
        # モデルマネージャーの初期化（DBベースに統一）
        connection_string = DatabaseConfig.get_algo_trader_connection_string()
        model_manager = ModelManager(connection_string=connection_string, use_file_backend=False)
        logger.info("ModelManager initialized with DB-based backend")
        
        logger.info("Training API initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize Training API: {e}")
        raise
    
    yield
    
    # シャットダウン時の処理
    logger.info("Shutting down Training API...")


app = FastAPI(
    title="Algo Trader Training API",
    description="Model training API",
    version="1.0.0",
    lifespan=lifespan
)


def _convert_to_json_serializable(obj):
    """numpy型やpandas型をPython標準型に変換"""
    import numpy as np
    import pandas as pd
    
    if isinstance(obj, (np.integer, np.floating)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, pd.DataFrame):
        return obj.to_dict('records')
    elif isinstance(obj, pd.Series):
        return obj.to_dict()
    elif isinstance(obj, dict):
        return {k: _convert_to_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_to_json_serializable(item) for item in obj]
    elif isinstance(obj, datetime):
        return obj.isoformat()
    else:
        return obj


# 再訓練ジョブの実行タスク
async def train_model_task(job_id: str, request: RetrainRequest):
    """バックグラウンドでモデルを訓練するタスク"""
    global training_jobs, model_manager, active_training_jobs
    
    # キューに追加
    await training_queue.put((job_id, request))
    
    # 同時実行数が上限に達している場合は待機
    while len(active_training_jobs) >= MAX_CONCURRENT_TRAINING_JOBS:
        if _job_cancel_requested(job_id):
            _mark_job_stopped(job_id, "Training cancelled while waiting in queue")
            return
        await asyncio.sleep(1)
    
    # アクティブジョブに追加
    async with training_lock:
        active_training_jobs.add(job_id)
    
    training_jobs.setdefault(job_id, {})
    training_jobs[job_id].update({
        "status": "running",
        "progress": training_jobs[job_id].get("progress", 0.0),
        "message": "Training started",
        "result": training_jobs[job_id].get("result"),
        "cancel_requested": training_jobs[job_id].get("cancel_requested", False),
    })
    
    logger.info(f"Training job {job_id} started: model_name={request.model_name}, symbol={request.symbol}, models={request.models}")
    
    try:
        if _job_cancel_requested(job_id):
            _mark_job_stopped(job_id, "Training cancelled before execution")
            return

        # 日時文字列をdatetimeに変換
        start_date = None
        end_date = None
        if request.start_date:
            try:
                start_date = datetime.fromisoformat(request.start_date.replace('Z', '+00:00'))
            except ValueError:
                start_date = datetime.fromisoformat(request.start_date)
        if request.end_date:
            try:
                end_date = datetime.fromisoformat(request.end_date.replace('Z', '+00:00'))
            except ValueError:
                end_date = datetime.fromisoformat(request.end_date)
        
        # 訓練を実行
        result = train_models(
            symbol=request.symbol,
            model_name=request.model_name,
            training_window_days=request.training_window_days,
            start_date=start_date,
            end_date=end_date,
            models=request.models,
            timeframes=request.timeframes,
            prediction_horizon=request.prediction_horizon,
            feature_engineer=feature_engineer,
            data_loader=data_loader
        )
        
        if _job_cancel_requested(job_id):
            _mark_job_stopped(job_id, "Training cancelled")
            return

        if result["status"] == "success":
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
            
            # 訓練データ統計情報を取得
            training_data_stats = result.get("training_data_stats")
            
            # メタデータに登録
            if "price_prediction" in result.get("file_paths", {}):
                price_metrics = result.get("results", {}).get("price_prediction", {})
                model_manager.register_model(
                    model_name=request.model_name,
                    model_type="price_prediction",
                    symbol=request.symbol,
                    file_path=result["file_paths"]["price_prediction"],
                    training_window_days=request.training_window_days or 3,
                    metrics=price_metrics,
                    is_active=False,
                    training_start_time=training_start_time,
                    training_end_time=training_end_time,
                    training_data_stats=training_data_stats
                )
                # 登録成功後、モデルをアクティブ化
                model_manager.activate_model(request.model_name, "price_prediction", request.symbol)
                logger.info(f"Price prediction model activated: {request.model_name} ({request.symbol})")

            if "momentum_intensity" in result.get("file_paths", {}):
                momentum_metrics = result.get("results", {}).get("momentum_intensity", {})
                model_manager.register_model(
                    model_name=request.model_name,
                    model_type="momentum_intensity",
                    symbol=request.symbol,
                    file_path=result["file_paths"]["momentum_intensity"],
                    training_window_days=request.training_window_days or 3,
                    metrics=momentum_metrics,
                    is_active=False,
                    training_start_time=training_start_time,
                    training_end_time=training_end_time,
                    training_data_stats=training_data_stats
                )
                # 登録成功後、モデルをアクティブ化
                model_manager.activate_model(request.model_name, "momentum_intensity", request.symbol)
                logger.info(f"Momentum intensity model activated: {request.model_name} ({request.symbol})")
            
            if "direction_classification" in result.get("file_paths", {}):
                direction_metrics = result.get("results", {}).get("direction_classification", {})
                model_manager.register_model(
                    model_name=request.model_name,
                    model_type="direction_classification",
                    symbol=request.symbol,
                    file_path=result["file_paths"]["direction_classification"],
                    training_window_days=request.training_window_days or 3,
                    metrics=direction_metrics,
                    is_active=False,
                    training_start_time=training_start_time,
                    training_end_time=training_end_time,
                    training_data_stats=training_data_stats
                )
            
            if "volatility_prediction" in result.get("file_paths", {}):
                volatility_metrics = result.get("results", {}).get("volatility_prediction", {})
                model_manager.register_model(
                    model_name=request.model_name,
                    model_type="volatility_prediction",
                    symbol=request.symbol,
                    file_path=result["file_paths"]["volatility_prediction"],
                    training_window_days=request.training_window_days or 3,
                    metrics=volatility_metrics,
                    is_active=False,
                    training_start_time=training_start_time,
                    training_end_time=training_end_time,
                    training_data_stats=training_data_stats
                )
            
            if "volume_prediction" in result.get("file_paths", {}):
                volume_metrics = result.get("results", {}).get("volume_prediction", {})
                model_manager.register_model(
                    model_name=request.model_name,
                    model_type="volume_prediction",
                    symbol=request.symbol,
                    file_path=result["file_paths"]["volume_prediction"],
                    training_window_days=request.training_window_days or 3,
                    metrics=volume_metrics,
                    is_active=False,
                    training_start_time=training_start_time,
                    training_end_time=training_end_time,
                    training_data_stats=training_data_stats
                )
            
            if "lightgbm_price_prediction" in result.get("file_paths", {}):
                lightgbm_metrics = result.get("results", {}).get("lightgbm_price_prediction", {})
                model_manager.register_model(
                    model_name=request.model_name,
                    model_type="lightgbm_price_prediction",
                    symbol=request.symbol,
                    file_path=result["file_paths"]["lightgbm_price_prediction"],
                    training_window_days=request.training_window_days or 3,
                    metrics=lightgbm_metrics,
                    is_active=False,
                    training_start_time=training_start_time,
                    training_end_time=training_end_time,
                    training_data_stats=training_data_stats
                )
            
            if "order_book_only" in result.get("file_paths", {}):
                orderbook_metrics = result.get("results", {}).get("order_book_only", {})
                model_manager.register_model(
                    model_name=request.model_name,
                    model_type="order_book_only",
                    symbol=request.symbol,
                    file_path=result["file_paths"]["order_book_only"],
                    training_window_days=request.training_window_days or 3,
                    metrics=orderbook_metrics,
                    is_active=False,
                    training_start_time=training_start_time,
                    training_end_time=training_end_time,
                    training_data_stats=training_data_stats
                )
            
            logger.info(f"Training job {job_id} completed successfully: model_name={request.model_name}, symbol={request.symbol}")
            training_jobs[job_id] = {
                "status": "completed",
                "progress": 1.0,
                "message": "Training completed successfully",
                "result": result,
                "cancel_requested": False
            }
        else:
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"Training job {job_id} failed: {error_msg}")
            training_jobs[job_id] = {
                "status": "error",
                "progress": 0.0,
                "message": f"Training failed: {error_msg}",
                "result": result,
                "cancel_requested": training_jobs.get(job_id, {}).get("cancel_requested", False)
            }
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = type(e).__name__
        error_detail = traceback.format_exc()
        logger.error(f"Training job {job_id} failed: {error_type}: {error_msg}\n{error_detail}")
        training_jobs[job_id] = {
            "status": "error",
            "progress": 0.0,
            "message": f"Training error: {error_msg}",
            "result": {"status": "error", "error": error_msg, "error_type": error_type, "traceback": error_detail},
            "cancel_requested": training_jobs.get(job_id, {}).get("cancel_requested", False)
        }
    finally:
        # アクティブジョブから削除
        async with training_lock:
            active_training_jobs.discard(job_id)
            logger.info(f"Training job {job_id} completed: {len(active_training_jobs)}/{MAX_CONCURRENT_TRAINING_JOBS} jobs running")
        
        # 次のジョブを開始
        if not training_queue.empty():
            try:
                next_job_id, next_request = await training_queue.get()
                # 次のジョブをバックグラウンドで開始
                asyncio.create_task(train_model_task(next_job_id, next_request))
            except Exception as e:
                logger.error(f"Failed to start next training job: {e}")


@app.post("/retrain", response_model=RetrainResponse)
async def retrain_model(request: RetrainRequest, background_tasks: BackgroundTasks):
    """
    モデルを再訓練して名前付きで保存
    
    非同期で実行され、即座にジョブIDを返します。
    進捗は GET /retrain/{job_id}/status で確認できます。
    """
    if model_manager is None:
        raise HTTPException(status_code=503, detail="ModelManager not initialized")
    
    job_id = str(uuid.uuid4())

    training_jobs[job_id] = {
        "status": "pending",
        "progress": 0.0,
        "message": "Training job accepted",
        "result": None,
        "cancel_requested": False
    }
    
    # バックグラウンドタスクとして実行
    background_tasks.add_task(train_model_task, job_id, request)
    
    return RetrainResponse(
        status="accepted",
        job_id=job_id,
        message="Training job started"
    )


@app.delete("/retrain/{job_id}")
async def cancel_retrain_job(job_id: str):
    """再訓練ジョブのキャンセル"""
    if job_id not in training_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    status = training_jobs[job_id].get("status")
    if status in {"completed", "error", "stopped"}:
        return {
            "status": status,
            "job_id": job_id,
            "message": f"Job already finished with status={status}"
        }

    training_jobs[job_id]["cancel_requested"] = True
    _mark_job_stopped(job_id)
    return {
        "status": "stopped",
        "job_id": job_id,
        "message": "Training cancellation requested"
    }


@app.get("/retrain/{job_id}/status", response_model=RetrainStatusResponse)
async def get_retrain_status(job_id: str):
    """再訓練ジョブのステータスを取得"""
    try:
        if job_id not in training_jobs:
            logger.warning(f"Training job not found: {job_id}")
            raise HTTPException(status_code=404, detail="Job not found")
        
        job_status = training_jobs[job_id]
        result = job_status.get("result")
        
        # resultをJSONシリアライズ可能な形式に変換
        if result is not None:
            try:
                result = _convert_to_json_serializable(result)
                # 変換後の結果がJSONシリアライズ可能か確認
                import json
                json.dumps(result, default=str)
            except (TypeError, ValueError) as e:
                logger.warning(f"Failed to serialize result for training job {job_id}: {e}, converting to error message")
                result = {"status": "error", "error": f"Failed to serialize result: {str(e)}"}
        
        return RetrainStatusResponse(
            job_id=job_id,
            status=job_status["status"],
            progress=job_status.get("progress"),
            message=job_status.get("message"),
            result=result
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get training status for job {job_id}: {e}")
        error_msg = str(e)
        raise HTTPException(status_code=500, detail=error_msg)


@app.get("/health")
async def health_check():
    """ヘルスチェック"""
    return {
        "status": "healthy",
        "service": "training_api",
        "active_jobs": len(active_training_jobs),
        "max_concurrent_jobs": MAX_CONCURRENT_TRAINING_JOBS,
        "queued_jobs": training_queue.qsize()
    }

