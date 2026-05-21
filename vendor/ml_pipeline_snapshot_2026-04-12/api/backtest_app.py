"""
バックテスト専用FastAPIアプリケーション
モデルのバックテストを実行する独立したAPIサーバー
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
from api.shared.models import BacktestRequest, BacktestResponse, BacktestStatusResponse

# ロガーの設定
logger = setup_logger("backtest_api")

# その他のインポート
from api.backtest_service import run_backtest_task

# バックテストジョブの状態管理
backtest_jobs: Dict[str, Dict] = {}


def _job_cancel_requested(job_id: str) -> bool:
    return bool(backtest_jobs.get(job_id, {}).get("cancel_requested", False))


def _mark_job_stopped(job_id: str, message: str = "Backtest cancelled") -> None:
    if job_id not in backtest_jobs:
        return
    backtest_jobs[job_id]["status"] = "stopped"
    backtest_jobs[job_id]["message"] = message
    backtest_jobs[job_id]["stage"] = "stopped"
    backtest_jobs[job_id]["cancel_requested"] = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリケーションのライフサイクル管理"""
    # 起動時の初期化
    logger.info("Initializing Backtest API...")
    
    try:
        logger.info("Backtest API initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Backtest API: {e}")
        raise
    
    yield
    
    # シャットダウン時の処理
    logger.info("Shutting down Backtest API...")


app = FastAPI(
    title="Algo Trader Backtest API",
    description="Model backtesting API",
    version="1.0.0",
    lifespan=lifespan
)


def _convert_to_json_serializable(obj):
    """numpy型やpandas型をPython標準型に変換（nan/infも処理）"""
    import numpy as np
    import pandas as pd
    import math
    
    if isinstance(obj, (np.integer, np.floating)):
        val = float(obj)
        # nan や inf を None に変換（JSON準拠）
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    elif isinstance(obj, np.ndarray):
        # 配列内のnan/infも処理
        arr = obj.tolist()
        return [_convert_to_json_serializable(item) for item in arr]
    elif isinstance(obj, pd.DataFrame):
        # DataFrame内のnan/infも処理
        df_dict = obj.to_dict('records')
        return [_convert_to_json_serializable(record) for record in df_dict]
    elif isinstance(obj, pd.Series):
        # Series内のnan/infも処理
        series_dict = obj.to_dict()
        return {k: _convert_to_json_serializable(v) for k, v in series_dict.items()}
    elif isinstance(obj, dict):
        return {k: _convert_to_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_to_json_serializable(item) for item in obj]
    elif isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, float):
        # 通常のfloat型でもnan/infをチェック
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    else:
        return obj


async def backtest_task(job_id: str, request: BacktestRequest):
    """バックグラウンドでバックテストを実行するタスク"""
    global backtest_jobs
    
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
    
    backtest_jobs.setdefault(job_id, {})
    backtest_jobs[job_id].update({
        "status": "running",
        "progress": backtest_jobs[job_id].get("progress", 0.0),
        "message": "Loading data...",
        "result": backtest_jobs[job_id].get("result"),
        "current_record": backtest_jobs[job_id].get("current_record", 0),
        "total_records": backtest_jobs[job_id].get("total_records", 0),
        "data_quality": backtest_jobs[job_id].get("data_quality"),
        "stage": "loading",  # "loading", "quality_check", "feature_engineering", "backtesting"
        "model_name": request.model_name,
        "model_type": request.model_type,
        "symbol": request.symbol,
        "cancel_requested": backtest_jobs[job_id].get("cancel_requested", False)
    })
    
    # 進捗コールバック関数
    def update_progress(current: int, total: int, progress_pct: float, stage: str = None, message: str = None):
        if _job_cancel_requested(job_id):
            return
        if job_id in backtest_jobs:
            if total > 0:
                backtest_jobs[job_id]["progress"] = progress_pct / 100.0
                backtest_jobs[job_id]["current_record"] = current
                backtest_jobs[job_id]["total_records"] = total
            if stage:
                backtest_jobs[job_id]["stage"] = stage
            if message:
                backtest_jobs[job_id]["message"] = message
            elif total > 0:
                backtest_jobs[job_id]["message"] = f"Processing record {current}/{total} ({progress_pct:.1f}%)"
    
    # データ品質コールバック関数
    def update_data_quality(data_quality: Dict):
        if _job_cancel_requested(job_id):
            return
        if job_id in backtest_jobs:
            backtest_jobs[job_id]["data_quality"] = data_quality
            backtest_jobs[job_id]["stage"] = "quality_check"
            quality_score = data_quality.get("quality_score", 0)
            issues_count = len(data_quality.get("issues", []))
            if issues_count > 0:
                backtest_jobs[job_id]["message"] = f"Data quality: {quality_score}/100 ({issues_count} issues found)"
            else:
                backtest_jobs[job_id]["message"] = f"Data quality: {quality_score}/100 (No issues)"
    
    try:
        if _job_cancel_requested(job_id):
            _mark_job_stopped(job_id, "Backtest cancelled before execution")
            return

        # バックテストを実行（別スレッドで実行してイベントループをブロックしない）
        # asyncio.to_thread()を使用することで、同期的なrun_backtest_taskが
        # イベントループをブロックせず、APIサーバーが応答可能になる
        result = await asyncio.to_thread(
            run_backtest_task,
            model_name=request.model_name,
            model_type=request.model_type,
            symbol=request.symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=request.initial_capital,
            commission_rate=request.commission_rate,
            confidence_threshold=request.confidence_threshold,
            max_position_size=request.max_position_size,
            stop_loss_pct=request.stop_loss_pct,
            use_limit_orders=request.use_limit_orders,
            limit_order_timeout_seconds=request.limit_order_timeout_seconds,
            show_trades=request.show_trades,
            show_equity_curve=request.show_equity_curve,
            progress_callback=update_progress,
            data_quality_callback=update_data_quality
        )
        
        if _job_cancel_requested(job_id):
            _mark_job_stopped(job_id)
            return

        if result.get("status") == "success":
            # 既存のjob_statusを保持しつつ、完了状態を更新
            current_record = backtest_jobs[job_id].get("current_record", 0)
            total_records = backtest_jobs[job_id].get("total_records", 0)
            data_quality = backtest_jobs[job_id].get("data_quality")
            
            if job_id in backtest_jobs:
                backtest_jobs[job_id].update({
                    "status": "completed",
                    "progress": 1.0,
                    "message": "Backtest completed successfully",
                    "result": result,
                    "current_record": current_record if current_record is not None else total_records,
                    "total_records": total_records if total_records is not None else 0,
                    "data_quality": data_quality,
                    "stage": "completed",
                    "model_name": request.model_name,
                    "model_type": request.model_type,
                    "symbol": request.symbol,
                    "cancel_requested": False
                })
            else:
                backtest_jobs[job_id] = {
                    "status": "completed",
                    "progress": 1.0,
                    "message": "Backtest completed successfully",
                    "result": result,
                    "current_record": total_records if total_records is not None else 0,
                    "total_records": total_records if total_records is not None else 0,
                    "data_quality": data_quality,
                    "stage": "completed",
                    "model_name": request.model_name,
                    "model_type": request.model_type,
                    "symbol": request.symbol,
                    "cancel_requested": False
                }
            logger.info(f"Backtest job {job_id} completed successfully")
        else:
            # 既存のjob_statusを保持しつつ、エラー状態を更新
            current_record = backtest_jobs[job_id].get("current_record", 0) if job_id in backtest_jobs else 0
            total_records = backtest_jobs[job_id].get("total_records", 0) if job_id in backtest_jobs else 0
            data_quality = backtest_jobs[job_id].get("data_quality") if job_id in backtest_jobs else None
            
            if job_id in backtest_jobs:
                backtest_jobs[job_id].update({
                    "status": "error",
                    "progress": backtest_jobs[job_id].get("progress", 0.0),
                    "message": f"Backtest failed: {result.get('error', 'Unknown error')}",
                    "result": result,
                    "current_record": current_record if current_record is not None else 0,
                    "total_records": total_records if total_records is not None else 0,
                    "data_quality": data_quality,
                    "stage": "error",
                    "cancel_requested": backtest_jobs.get(job_id, {}).get("cancel_requested", False)
                })
            else:
                backtest_jobs[job_id] = {
                    "status": "error",
                    "progress": 0.0,
                    "message": f"Backtest failed: {result.get('error', 'Unknown error')}",
                    "result": result,
                    "current_record": 0,
                    "total_records": 0,
                    "data_quality": None,
                    "stage": "error",
                    "cancel_requested": backtest_jobs.get(job_id, {}).get("cancel_requested", False)
                }
            logger.error(f"Backtest job {job_id} failed: {result.get('error', 'Unknown error')}")
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_detail = traceback.format_exc()
        error_type = type(e).__name__
        logger.error(f"Backtest job {job_id} exception: {error_type}: {error_msg}\n{error_detail}")
        
        # 既存のjob_statusから値を取得（可能な場合）
        current_record = backtest_jobs.get(job_id, {}).get("current_record", 0) if job_id in backtest_jobs else 0
        total_records = backtest_jobs.get(job_id, {}).get("total_records", 0) if job_id in backtest_jobs else 0
        data_quality = backtest_jobs.get(job_id, {}).get("data_quality") if job_id in backtest_jobs else None
        
        backtest_jobs[job_id] = {
            "status": "error",
            "progress": backtest_jobs.get(job_id, {}).get("progress", 0.0) if job_id in backtest_jobs else 0.0,
            "message": f"Backtest error: {error_type}: {error_msg}",
            "result": {
                "status": "error",
                "error": error_msg,
                "error_type": error_type,
                "traceback": error_detail
            },
            "current_record": current_record if current_record is not None else 0,
            "total_records": total_records if total_records is not None else 0,
            "data_quality": data_quality,
            "stage": "error",
            "cancel_requested": backtest_jobs.get(job_id, {}).get("cancel_requested", False)
        }


@app.post("/backtest/run", response_model=BacktestResponse)
async def run_backtest(request: BacktestRequest, background_tasks: BackgroundTasks):
    """
    バックテストを実行
    
    非同期で実行され、即座にジョブIDを返します。
    進捗は GET /backtest/{job_id}/status で確認できます。
    """
    job_id = str(uuid.uuid4())

    backtest_jobs[job_id] = {
        "status": "pending",
        "progress": 0.0,
        "message": "Backtest job accepted",
        "result": None,
        "current_record": 0,
        "total_records": 0,
        "data_quality": None,
        "stage": "pending",
        "model_name": request.model_name,
        "model_type": request.model_type,
        "symbol": request.symbol,
        "cancel_requested": False
    }
    
    # バックグラウンドタスクとして実行
    background_tasks.add_task(backtest_task, job_id, request)
    
    return BacktestResponse(
        status="accepted",
        job_id=job_id,
        message="Backtest job started"
    )


@app.delete("/backtest/{job_id}")
async def cancel_backtest_job(job_id: str):
    """バックテストジョブのキャンセル"""
    if job_id not in backtest_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    status = backtest_jobs[job_id].get("status")
    if status in {"completed", "error", "stopped"}:
        return {
            "status": status,
            "job_id": job_id,
            "message": f"Job already finished with status={status}"
        }

    backtest_jobs[job_id]["cancel_requested"] = True
    _mark_job_stopped(job_id)
    return {
        "status": "stopped",
        "job_id": job_id,
        "message": "Backtest cancellation requested"
    }


@app.get("/backtest/{job_id}/status", response_model=BacktestStatusResponse)
async def get_backtest_status(job_id: str):
    """バックテストジョブのステータスを取得"""
    try:
        if job_id not in backtest_jobs:
            logger.warning(f"Backtest job not found: {job_id}")
            raise HTTPException(status_code=404, detail="Job not found")
        
        job_status = backtest_jobs[job_id]
        
        # すべてのフィールドをJSONシリアライズ可能な形式に変換
        # nan/infを含む可能性のあるフィールドを変換
        result = _convert_to_json_serializable(job_status.get("result"))
        progress = _convert_to_json_serializable(job_status.get("progress"))
        data_quality = _convert_to_json_serializable(job_status.get("data_quality"))
        
        # 変換後の結果がJSONシリアライズ可能か確認
        try:
            import json
            test_data = {
                "result": result,
                "progress": progress,
                "data_quality": data_quality
            }
            json.dumps(test_data, default=str)
        except (TypeError, ValueError) as e:
            logger.warning(f"Failed to serialize data for backtest job {job_id}: {e}")
            # エラーが発生した場合は、resultをエラーメッセージに変換
            result = {"status": "error", "error": f"Failed to serialize result: {str(e)}"}
            progress = None
            data_quality = None
        
        return BacktestStatusResponse(
            job_id=job_id,
            status=job_status["status"],
            progress=progress,
            message=job_status.get("message"),
            result=result,
            current_record=job_status.get("current_record"),
            total_records=job_status.get("total_records"),
            data_quality=data_quality,
            stage=job_status.get("stage")
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get backtest status for job {job_id}: {e}")
        error_msg = str(e)
        raise HTTPException(status_code=500, detail=error_msg)


@app.get("/backtest/{job_id}/result")
async def get_backtest_result(job_id: str):
    """バックテストジョブの結果を取得"""
    try:
        if job_id not in backtest_jobs:
            logger.warning(f"Backtest job not found: {job_id}")
            raise HTTPException(status_code=404, detail="Job not found")
        
        job_status = backtest_jobs[job_id]
        
        if job_status["status"] != "completed":
            raise HTTPException(status_code=400, detail=f"Job not completed. Current status: {job_status['status']}")
        
        result = job_status.get("result")
        if result is None:
            raise HTTPException(status_code=404, detail="Result not available")
        
        # resultをJSONシリアライズ可能な形式に変換
        result = _convert_to_json_serializable(result)
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get backtest result for job {job_id}: {e}")
        error_msg = str(e)
        raise HTTPException(status_code=500, detail=error_msg)


@app.get("/health")
async def health_check():
    """ヘルスチェック"""
    return {
        "status": "healthy",
        "service": "backtest_api",
        "active_jobs": len([j for j in backtest_jobs.values() if j.get("status") == "running"]),
        "total_jobs": len(backtest_jobs)
    }

