"""
共通のPydanticモデル
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class RetrainRequest(BaseModel):
    """再訓練リクエスト"""
    model_name: str = Field(..., description="Model name (e.g., my_model_v1)")
    symbol: str = Field(..., description="Symbol (e.g., G_FX_BTCJPY)")
    training_window_days: Optional[int] = Field(None, description="Training window in days (used if start_date/end_date not provided)")
    start_date: Optional[str] = Field(None, description="Start date (ISO 8601 format, e.g., 2025-12-25T14:00:00Z)")
    end_date: Optional[str] = Field(None, description="End date (ISO 8601 format, e.g., 2025-12-28T14:00:00Z)")
    models: List[str] = Field(["price", "momentum"], description="Models to train: ['price', 'momentum', 'direction', 'volatility', 'volume', 'lightgbm_price', 'order_book_only']")
    timeframes: List[int] = Field([1, 5, 30], description="Timeframes in seconds")
    prediction_horizon: int = Field(60, description="Prediction horizon in seconds")


class RetrainResponse(BaseModel):
    """再訓練レスポンス"""
    status: str
    job_id: str
    message: str


class RetrainStatusResponse(BaseModel):
    """再訓練ステータスレスポンス"""
    job_id: str
    status: str  # "pending", "running", "completed", "error"
    progress: Optional[float] = None
    message: Optional[str] = None
    result: Optional[Dict] = None


class BacktestRequest(BaseModel):
    """バックテストリクエスト"""
    model_name: str = Field(..., description="Model name")
    model_type: str = Field(..., description="Model type: 'price_prediction', 'momentum_intensity', or 'lightgbm_price_prediction'")
    symbol: str = Field(..., description="Symbol (e.g., G_FX_BTCJPY)")
    start_date: str = Field(..., description="Start date (ISO 8601 format)")
    end_date: str = Field(..., description="End date (ISO 8601 format)")
    initial_capital: float = Field(10000000, description="Initial capital")
    commission_rate: float = Field(0.0, description="Commission rate")
    confidence_threshold: float = Field(0.7, description="Confidence threshold")
    max_position_size: float = Field(0.01, description="Max position size")
    stop_loss_pct: float = Field(0.36, description="Stop loss percentage")
    use_limit_orders: bool = Field(False, description="Use limit orders")
    limit_order_timeout_seconds: int = Field(60, description="Limit order timeout in seconds")
    show_trades: bool = Field(True, description="Include trades in result")
    show_equity_curve: bool = Field(True, description="Include equity curve in result")


class BacktestResponse(BaseModel):
    """バックテストレスポンス"""
    status: str
    job_id: str
    message: str


class BacktestStatusResponse(BaseModel):
    """バックテストステータスレスポンス"""
    job_id: str
    status: str  # "pending", "running", "completed", "error"
    progress: Optional[float] = None
    message: Optional[str] = None
    result: Optional[Dict] = None
    current_record: Optional[int] = None
    total_records: Optional[int] = None
    data_quality: Optional[Dict] = None
    stage: Optional[str] = None  # "loading", "quality_check", "feature_engineering", "backtesting", "completed", "error"

