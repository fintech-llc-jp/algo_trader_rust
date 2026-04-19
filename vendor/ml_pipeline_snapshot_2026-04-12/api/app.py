"""
FastAPI server for real-time price prediction and signal generation
"""
import os
import sys
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any
import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
import logging
from logging.handlers import RotatingFileHandler

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ロギング設定
log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
os.makedirs(log_dir, exist_ok=True)

# ログファイルパス（環境変数で指定可能）
log_file = os.getenv("ML_API_LOG_FILE", os.path.join(log_dir, "ml_api.log"))

# ロガーの設定
logger = logging.getLogger("ml_api")
logger.setLevel(logging.INFO)

# 既存のハンドラをクリア（重複を防ぐ）
logger.handlers.clear()

# ファイルハンドラ（ローテーション付き、10MB、5ファイルまで保持）
file_handler = RotatingFileHandler(
    log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
)
file_handler.setLevel(logging.INFO)

# コンソールハンドラ
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# フォーマッタ
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

logger.info(f"ML-API logging initialized. Log file: {log_file}")

from data.data_loader import MarketDataLoader
from data.exch_sim_data_loader import ExchSimDataLoader
from data.feature_engineering import FeatureEngineer
from data.configurable_feature_engineering import ConfigurableFeatureEngineer
from strategy.price_prediction_strategy import PricePredictionStrategy
from strategy.momentum_intensity_strategy import MomentumIntensityStrategy
from config.settings import DatabaseConfig, ModelConfig
from models.price_prediction_model import PricePredictionModel
from models.momentum_intensity_model import MomentumIntensityModel
from api.model_manager import ModelManager
from api.periodic_retrainer import PeriodicRetrainer
from api.exchsim_service import run_exchsim_task, ExchSimExecutor
from api.model_loader import load_model_for_symbol
from fastapi import BackgroundTasks
import uuid
import shutil

# グローバル変数
price_strategy: Optional[PricePredictionStrategy] = None
momentum_strategy: Optional[MomentumIntensityStrategy] = None
feature_engineer: Optional[FeatureEngineer] = None
data_loader: Optional[MarketDataLoader] = None
model_manager: Optional[ModelManager] = None
prediction_tracker = None  # PredictionTracker instance (imported later to avoid circular dependency)

# シンボルごとのモデルキャッシュ
# {symbol: {'price_model': model, 'momentum_model': model}}
symbol_model_cache: Dict[str, Dict] = {}

# トレーニングとバックテストは別のAPIサーバーに分離されました
# training_app.py (Port 8001) と backtest_app.py (Port 8002) を参照してください

# ExchSim実行ジョブの状態管理
exchsim_jobs: Dict[str, Dict] = {}

# ExchSim実行ジョブの管理（executorインスタンスを保持）
exchsim_executors: Dict[str, ExchSimExecutor] = {}

# 予測誤差補正用の履歴（シンボルごとに保持）
# {symbol: {'predictions': pd.Series, 'actual_prices': pd.Series}}
prediction_history: dict = {}

# キャッシング機構：5分間のマーケットデータと特徴量をメモリに保持
# {symbol: {'timestamp': datetime, 'df': pd.DataFrame, 'features': pd.DataFrame}}
market_data_cache: dict = {}
CACHE_TTL_SECONDS = 60  # キャッシュ有効期限（秒）


import asyncio
from datetime import timedelta
import pytz

class BackgroundDataLoader:
    """
    バックグラウンドでデータを定期的にロードし、メモリ上に保持するクラス
    """
    def __init__(self, symbol: str, window_minutes: int = 5):
        self.symbol = symbol
        self.window_minutes = window_minutes
        self.data_buffer: Optional[pd.DataFrame] = None
        self.features_buffer: Optional[pd.DataFrame] = None
        self.running = False
        self.update_interval_seconds = 1  # 1秒ごとに更新
        self._task = None
        self.lock = asyncio.Lock()
        
    async def start(self):
        """バックグラウンドタスクを開始"""
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"BackgroundDataLoader started for {self.symbol}")
        
    async def stop(self):
        """バックグラウンドタスクを停止"""
        self.running = False
        if self._task:
            await self._task
            
    async def get_data(self) -> tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """現在のバッファを取得（スレッドセーフ）"""
        async with self.lock:
            if self.data_buffer is None:
                return None, None
            return self.data_buffer.copy(), self.features_buffer.copy() if self.features_buffer is not None else None

    async def _loop(self):
        """メインループ"""
        while self.running:
            try:
                await self._update()
            except Exception as e:
                logger.error(f"Error in background loader: {e}")
            
            await asyncio.sleep(self.update_interval_seconds)
            
    async def _update(self):
        """データの更新"""
        now = datetime.now(pytz.utc)
        start_time = now - timedelta(minutes=self.window_minutes)
        
        # 初回ロードまたはバッファがない場合
        async with self.lock:
            current_buffer = self.data_buffer
            
        if current_buffer is None:
            # 初回は同期的に全ロード（ブロッキング注意だが、初回のみ）
            # 非同期で実行したいが、data_loader自体が同期なのでexecutorで実行
            loop = asyncio.get_running_loop()
            df = await loop.run_in_executor(
                None, 
                lambda: data_loader.load_training_data(self.symbol, start_time, now, skip_min_samples_check=True)
            )
            
            if len(df) > 0:
                features = await loop.run_in_executor(
                    None,
                    lambda: feature_engineer.engineer_features(df)
                )
                async with self.lock:
                    self.data_buffer = df
                    self.features_buffer = features
                logger.info(f"[BG] Initial load complete: {len(df)} rows")
        else:
            # 差分更新（実装簡易化のため、現時点ではウィンドウごとリロードするが、非同期で実行するためメインスレッドをブロックしない）
            # 本来は差分のみ取得してconcatするのが理想だが、load_training_dataの設計上、期間指定で取得する方が確実
            loop = asyncio.get_running_loop()
            df = await loop.run_in_executor(
                None, 
                lambda: data_loader.load_training_data(self.symbol, start_time, now, skip_min_samples_check=True)
            )
            
            if len(df) > 0:
                features = await loop.run_in_executor(
                    None,
                    lambda: feature_engineer.engineer_features(df)
                )
                async with self.lock:
                    self.data_buffer = df
                    self.features_buffer = features
                # print(f"[BG] Updated: {len(df)} rows") # ログ過多になるのでコメントアウト


# グローバルなバックグラウンドローダー
bg_loader: Optional[BackgroundDataLoader] = None

# グローバルな定期再訓練タスク
periodic_retrainer: Optional[PeriodicRetrainer] = None
# 定期シグナル配信タスク（Redis に publish）
periodic_signal_publisher = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリケーションのライフサイクル管理"""
    global price_strategy, momentum_strategy, feature_engineer, data_loader, bg_loader, model_manager, periodic_retrainer, periodic_signal_publisher
    
    # 起動時の初期化
    logger.info("Initializing ML models...")
    try:
        # データローダーの初期化（USE_EXCH_SIM_DB環境変数に応じて選択）
        use_exch_sim_db = os.getenv('USE_EXCH_SIM_DB', 'false').lower() == 'true'
        if use_exch_sim_db:
            logger.info("Using ExchSimDataLoader (exch_sim database)")
            data_loader = ExchSimDataLoader()
        else:
            logger.info("Using MarketDataLoader (algo_trader database)")
            data_loader = MarketDataLoader()
        
        # 特徴量エンジニアの初期化（環境変数で特徴量セット名を指定可能）
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
        
        # 価格予測戦略の初期化
        timeframes = [1, 5, 30]  # デフォルトのタイムフレーム
        prediction_horizon = 60  # 1分後を予測
        
        price_strategy = PricePredictionStrategy(
            timeframes=timeframes,
            prediction_horizon=prediction_horizon
        )
        
        # モメンタム強度戦略の初期化
        momentum_strategy = MomentumIntensityStrategy(
            timeframes=timeframes,
            prediction_horizon=prediction_horizon
        )
        
        # モデルのロード（最新のモデルをロード）
        logger.info("Loading trained models...")
        model_dir = ModelConfig.MODEL_DIR
        os.makedirs(model_dir, exist_ok=True)
        
        # デフォルトのシンボル
        default_symbol = "G_FX_BTCJPY"
        
        # ModelManagerを先に初期化（DBからモデル取得するために必要）
        try:
            connection_string = DatabaseConfig.get_algo_trader_connection_string()
            algo_host = DatabaseConfig.ALGO_TRADER_DB_HOST
            algo_port = DatabaseConfig.ALGO_TRADER_DB_PORT
            algo_db = DatabaseConfig.NAME
            logger.info(
                f"DB (algo_trader): host={algo_host}, port={algo_port}, db={algo_db}, "
                f"use_exch_sim_db={DatabaseConfig.USE_EXCH_SIM_DB}"
            )
            model_manager = ModelManager(connection_string=connection_string, use_file_backend=False)
            logger.info(
                f"ModelManager: use_file_backend={model_manager.use_file_backend}, "
                f"conn={model_manager.conn is not None}"
            )
            if model_manager.use_file_backend:
                logger.warning("ModelManager fell back to file backend (DB connection failed)")
            else:
                logger.info("ModelManager initialized with database backend (algo_trader)")
        except Exception as e:
            logger.warning(f"Failed to initialize ModelManager with database: {e}, falling back to file backend")
            import traceback
            logger.warning(traceback.format_exc())
            model_manager = ModelManager(use_file_backend=True)
        globals()['model_manager'] = model_manager
        
        # 価格予測モデルをロード（DBからアクティブモデルを取得、なければファイルから）
        price_model_path = os.path.join(model_dir, f'price_prediction_{default_symbol}.joblib')
        price_model_loaded = False
        
        # まずDBからアクティブモデルを取得を試みる
        if model_manager and not model_manager.use_file_backend:
            try:
                active_model = model_manager.get_active_model("price_prediction", default_symbol)
                if active_model:
                    loaded_model = model_manager.load_model(
                        model_name=active_model['model_name'],
                        model_type="price_prediction",
                        symbol=default_symbol
                    )
                    price_strategy.model = loaded_model
                    logger.info(f"Loaded active price prediction model from DB: {active_model['model_name']}")
                    price_model_loaded = True
            except Exception as e:
                logger.warning(f"Failed to load price prediction model from DB: {e}")
        
        # DBから取得できなかった場合、ファイルからロードを試みる
        if not price_model_loaded and os.path.exists(price_model_path):
            try:
                loaded_model = PricePredictionModel.load(price_model_path)
                price_strategy.model = loaded_model
                logger.info(f"Loaded price prediction model from file: {price_model_path}")
                price_model_loaded = True
            except Exception as e:
                logger.warning(f"Failed to load price prediction model from file: {e}")
        
        if not price_model_loaded:
            logger.info("Price prediction model not found. Will train new model on first request")
        
        # モメンタム強度モデルをロード（DBからアクティブモデルを取得、なければファイルから）
        momentum_model_path = os.path.join(model_dir, f'momentum_intensity_{default_symbol}.joblib')
        momentum_model_loaded = False
        
        # まずDBからアクティブモデルを取得を試みる
        if model_manager and not model_manager.use_file_backend:
            try:
                active_model = model_manager.get_active_model("momentum_intensity", default_symbol)
                if active_model:
                    loaded_momentum_model = model_manager.load_model(
                        model_name=active_model['model_name'],
                        model_type="momentum_intensity",
                        symbol=default_symbol
                    )
                    momentum_strategy.model = loaded_momentum_model
                    logger.info(f"Loaded active momentum intensity model from DB: {active_model['model_name']}")
                    momentum_model_loaded = True
            except Exception as e:
                logger.warning(f"Failed to load momentum intensity model from DB: {e}")
        
        # DBから取得できなかった場合、ファイルからロードを試みる
        if not momentum_model_loaded and os.path.exists(momentum_model_path):
            try:
                loaded_momentum_model = MomentumIntensityModel.load(momentum_model_path)
                momentum_strategy.model = loaded_momentum_model
                logger.info(f"Loaded momentum intensity model from file: {momentum_model_path}")
                momentum_model_loaded = True
            except Exception as e:
                logger.warning(f"Failed to load momentum intensity model from file: {e}")
        
        if not momentum_model_loaded:
            logger.info("Momentum intensity model not found. Will train new model on first request")
        
        logger.info("Models initialized successfully")
        
        # バックグラウンドローダーの開始
        bg_loader = BackgroundDataLoader(default_symbol)
        await bg_loader.start()
        
        # 定期再訓練タスクの開始（オプション）
        periodic_retrainer = PeriodicRetrainer(
            symbol=default_symbol,
            feature_engineer=feature_engineer,
            data_loader=data_loader
        )
        await periodic_retrainer.start()
        logger.info("PeriodicRetrainer started")
        
        # Prediction Tracker の開始（設定で有効/無効を制御）
        from config.settings import PredictionTrackerConfig
        from api.prediction_tracker import PredictionTracker
        
        if PredictionTrackerConfig.ENABLED:
            try:
                prediction_tracker = PredictionTracker(
                    symbol=default_symbol,
                    price_model=price_strategy.model,
                    data_loader=data_loader,
                    feature_engineer=feature_engineer
                )
                await prediction_tracker.start()
                globals()['prediction_tracker'] = prediction_tracker
                logger.info("PredictionTracker started")
            except Exception as e:
                logger.warning(f"Failed to start PredictionTracker: {e}")
                logger.warning("Continuing without PredictionTracker (models API will still work)")
                globals()['prediction_tracker'] = None
        else:
            logger.info("PredictionTracker disabled")
            globals()['prediction_tracker'] = None

        # 定期シグナル配信（Redis に publish）
        if os.getenv("PERIODIC_SIGNAL_ENABLED", "true").strip().lower() == "true":
            try:
                from api.periodic_signal_publisher import PeriodicSignalPublisher
                periodic_signal_publisher = PeriodicSignalPublisher(
                    bg_loader, price_strategy, momentum_strategy
                )
                await periodic_signal_publisher.start()
                globals()["periodic_signal_publisher"] = periodic_signal_publisher
            except Exception as e:
                logger.warning("Failed to start PeriodicSignalPublisher: %s", e)
                globals()["periodic_signal_publisher"] = None
        else:
            logger.info("Periodic signal publishing disabled")
            periodic_signal_publisher = None
        
    except Exception as e:
        logger.error(f"Error initializing models: {e}", exc_info=True)
        raise
    
    yield
    
    # シャットダウン時のクリーンアップ
    logger.info("Shutting down...")
    _periodic_signal = globals().get("periodic_signal_publisher")
    if _periodic_signal is not None:
        await _periodic_signal.stop()
        globals()["periodic_signal_publisher"] = None
    prediction_tracker = globals().get('prediction_tracker')
    if prediction_tracker:
        await prediction_tracker.stop()
    if 'periodic_retrainer' in locals() and periodic_retrainer:
        await periodic_retrainer.stop()
    if 'bg_loader' in locals() and bg_loader:
        await bg_loader.stop()
    if data_loader:
        data_loader.close()


app = FastAPI(
    title="Algo Trader ML API",
    description="Real-time price prediction and signal generation API",
    version="1.0.0",
    lifespan=lifespan
)


# リクエスト/レスポンスモデル
class MarketDataRequest(BaseModel):
    """市場データリクエスト"""
    symbol: str = Field(..., description="Symbol (e.g., G_FX_BTCJPY)")
    timestamp: datetime = Field(..., description="Timestamp for prediction")
    mid_price: float = Field(..., description="Mid price")
    bid_price_1: float = Field(..., description="Best bid price")
    ask_price_1: float = Field(..., description="Best ask price")
    bid_qty_1: Optional[float] = Field(None, description="Best bid quantity")
    ask_qty_1: Optional[float] = Field(None, description="Best ask quantity")
    spread: Optional[float] = Field(None, description="Spread")
    order_imbalance: Optional[float] = Field(None, description="Order imbalance")
    bid_depth_5: Optional[float] = Field(None, description="Bid depth (5 levels)")
    ask_depth_5: Optional[float] = Field(None, description="Ask depth (5 levels)")
    feature_set_name: Optional[str] = Field(None, description="Feature set name (optional, overrides default)")


class PredictionResponse(BaseModel):
    """予測レスポンス"""
    symbol: str
    timestamp: datetime
    predicted_price: float
    current_price: float
    price_change_pct: float
    confidence: float


class SignalResponse(BaseModel):
    """シグナルレスポンス"""
    symbol: str
    timestamp: datetime
    signal_type: str  # BUY, SELL, HOLD
    confidence: float
    predicted_price: float
    current_price: float
    price_change_pct: float
    momentum_intensity: Optional[int] = None


class HealthResponse(BaseModel):
    """ヘルスチェックレスポンス"""
    status: str
    models_loaded: bool
    database_connected: bool


# 再訓練関連のリクエスト/レスポンスモデルは shared/models.py に移動しました
# トレーニングAPI (training_app.py) とバックテストAPI (backtest_app.py) を参照してください


class ModelInfoResponse(BaseModel):
    """モデル情報レスポンス"""
    model_name: str
    symbol: str
    model_type: str
    file_path: Optional[str] = None  # DBベースの場合はNone（後方互換性のため）
    trained_at: str
    training_window_days: Optional[int] = None
    metrics: Optional[Dict[str, Any]] = {}
    is_active: bool


class ModelsListResponse(BaseModel):
    """モデル一覧レスポンス"""
    models: List[ModelInfoResponse]


class ActivateModelRequest(BaseModel):
    """モデルアクティベートリクエスト"""
    model_name: str
    model_type: str  # "price_prediction", "momentum_intensity", "direction_classification", "volatility_prediction", "volume_prediction", "lightgbm_price_prediction", "order_book_only"
    symbol: str


# バックテスト関連のリクエスト/レスポンスモデルは shared/models.py に移動しました
# バックテストAPI (backtest_app.py) を参照してください


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """ヘルスチェック"""
    models_loaded = price_strategy is not None and momentum_strategy is not None
    database_connected = data_loader is not None

    return HealthResponse(
        status="healthy" if models_loaded and database_connected else "degraded",
        models_loaded=models_loaded,
        database_connected=database_connected
    )


def get_cached_market_data(symbol: str, start_time: pd.Timestamp, end_time: pd.Timestamp):
    """
    キャッシュされたマーケットデータを取得。キャッシュが古い場合は更新
    """
    global market_data_cache

    now = datetime.now()

    # キャッシュの有効性を確認
    if symbol in market_data_cache:
        cache_entry = market_data_cache[symbol]
        cache_age = (now - cache_entry['timestamp']).total_seconds()

        if cache_age < CACHE_TTL_SECONDS:
            logger.debug(f"[CACHE HIT] {symbol}: cache age={cache_age:.1f}s, using cached data")
            return cache_entry['df'], cache_entry['features']
        else:
            logger.debug(f"[CACHE MISS] {symbol}: cache expired (age={cache_age:.1f}s > {CACHE_TTL_SECONDS}s)")
    else:
        logger.debug(f"[CACHE MISS] {symbol}: no cache available")

    # キャッシュがない or 古い場合はDB から取得
    logger.info(f"[LOAD] {symbol}: loading from database...")
    try:
        df = data_loader.load_training_data(symbol, start_time, end_time, skip_min_samples_check=True)
    except ValueError as e:
        # データが見つからない場合のエラーハンドリング
        error_msg = str(e)
        logger.error(f"[ERROR] Failed to load data for {symbol}: {error_msg}")
        # エラーメッセージを詳細に出力して、デバッグを容易にする
        logger.error(f"[ERROR] Requested time range: {start_time} to {end_time}")
        raise HTTPException(
            status_code=500,
            detail=f"Signal generation error: {error_msg}"
        )
    except Exception as e:
        # その他のエラー
        error_msg = str(e)
        logger.error(f"[ERROR] Unexpected error loading data for {symbol}: {error_msg}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Signal generation error: {error_msg}"
        )

    if df is None or len(df) == 0:
        logger.warning(f"[WARN] No data returned for {symbol} (empty DataFrame)")
        return None, None

    # 特徴量を計算
    features = feature_engineer.engineer_features(df)

    # キャッシュに保存
    market_data_cache[symbol] = {
        'timestamp': now,
        'df': df,
        'features': features
    }

    logger.debug(f"[CACHE UPDATE] {symbol}: updated cache with {len(df)} samples, {len(features.columns)} features")

    return df, features


@app.post("/predict", response_model=PredictionResponse)
async def predict_price(request: MarketDataRequest):
    """
    価格予測を実行
    
    現在の市場データから1分後の約定価格を予測します。
    """
    if price_strategy is None:
        raise HTTPException(status_code=503, detail="Price prediction model not loaded")
    
    if data_loader is None:
        raise HTTPException(status_code=503, detail="Data loader not initialized")
    
    try:
        # 最新の市場データを取得（過去数分間のデータが必要）
        end_time = request.timestamp
        start_time = end_time - pd.Timedelta(minutes=5)
        
        # 市場データを取得
        df = data_loader.load_training_data(request.symbol, start_time, end_time)
        
        if len(df) == 0:
            raise HTTPException(status_code=404, detail="No market data available")
        
        # 特徴量エンジニアリング
        df = feature_engineer.engineer_features(df)
        
        # 最新のデータポイントのみを使用
        latest_df = df.tail(1)
        
        # 予測を実行
        predictions = price_strategy.predict(latest_df)
        
        if len(predictions) == 0:
            raise HTTPException(status_code=500, detail="Prediction failed")
        
        predicted_price = float(predictions.iloc[-1])
        current_price = request.mid_price
        price_change_pct = ((predicted_price - current_price) / current_price) * 100
        
        # 信頼度の計算（簡易版）
        confidence = min(0.95, max(0.5, abs(price_change_pct) / 0.5))
        
        return PredictionResponse(
            symbol=request.symbol,
            timestamp=request.timestamp,
            predicted_price=predicted_price,
            current_price=current_price,
            price_change_pct=price_change_pct,
            confidence=confidence
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction error: {str(e)}")


@app.post("/signal", response_model=SignalResponse)
async def generate_signal(request: MarketDataRequest):
    """
    取引シグナルを生成
    
    価格予測とモメンタム強度から取引シグナル（BUY/SELL/HOLD）を生成します。
    """
    global price_strategy, momentum_strategy, symbol_model_cache
    
    if price_strategy is None or momentum_strategy is None:
        raise HTTPException(status_code=503, detail="Models not loaded")
    
    if data_loader is None:
        raise HTTPException(status_code=503, detail="Data loader not initialized")
    
    # 現在のモデルを保存（後で復元するため）
    original_price_model = price_strategy.model if price_strategy else None
    original_momentum_model = momentum_strategy.model if momentum_strategy else None
    
    try:
        # リクエストされたシンボル用のモデルをロード（必要に応じて）
        symbol = request.symbol
        
        # シンボルごとのモデルキャッシュを確認
        if symbol not in symbol_model_cache:
            symbol_model_cache[symbol] = {}
        
        # シンボルごとのモデルをロードまたは取得
        # まずキャッシュから取得を試みる
        price_model = symbol_model_cache[symbol].get('price_model')
        momentum_model = symbol_model_cache[symbol].get('momentum_model')
        
        # 価格予測モデルをロード（まだロードされていない場合）
        if price_model is None:
            logger.info(f"Loading price prediction model for {symbol}...")
            price_model = load_model_for_symbol(
                symbol=symbol,
                model_type="price_prediction",
                model_manager=model_manager,
                strategy_instance=None  # 戦略インスタンスには設定しない（後で手動で設定）
            )
            if price_model:
                symbol_model_cache[symbol]['price_model'] = price_model
                logger.info(f"Successfully loaded price prediction model for {symbol}")
            else:
                logger.warning(f"Price prediction model for {symbol} not found in DB or files. Checking default model...")
        
        # モメンタム強度モデルをロード（まだロードされていない場合）
        if momentum_model is None:
            logger.info(f"Loading momentum intensity model for {symbol}...")
            momentum_model = load_model_for_symbol(
                symbol=symbol,
                model_type="momentum_intensity",
                model_manager=model_manager,
                strategy_instance=None  # 戦略インスタンスには設定しない（後で手動で設定）
            )
            if momentum_model:
                symbol_model_cache[symbol]['momentum_model'] = momentum_model
            else:
                logger.warning(f"Momentum intensity model for {symbol} not found. Using default model if available.")
        
        # シンボル用のモデルを設定
        if price_model:
            price_strategy.model = price_model
            logger.debug(f"Using loaded price prediction model for {symbol}")
        else:
            # シンボル固有のモデルが見つからない場合、デフォルトモデルをチェック
            if price_strategy.model is not None and hasattr(price_strategy.model, 'model'):
                if price_strategy.model.model is not None:
                    # デフォルトモデルが有効（訓練済み）の場合、それを使用
                    logger.info(f"Using default price prediction model for {symbol} (symbol-specific model not found)")
                else:
                    # デフォルトモデルも無効（未訓練）の場合、エラー
                    error_detail = (
                        f"Price prediction model for {symbol} is not available. "
                        f"StrategyConfig may exist, but no trained model found. "
                        f"Please: 1) Train a model for {symbol}, 2) Activate it, or 3) Delete the StrategyConfig."
                    )
                    if model_manager:
                        active = model_manager.get_active_model("price_prediction", symbol) if not model_manager.use_file_backend else None
                        all_m = model_manager.get_models(model_type="price_prediction", symbol=symbol)
                        logger.info(
                            f"503 diagnostic: use_file_backend={model_manager.use_file_backend}, "
                            f"active_model={active}, models_count={len(all_m) if all_m else 0}"
                        )
                    logger.error(error_detail)
                    raise HTTPException(
                        status_code=503,
                        detail=error_detail
                    )
            else:
                # price_strategy.modelがNoneの場合（通常は発生しない）
                if model_manager:
                    active = model_manager.get_active_model("price_prediction", symbol) if not model_manager.use_file_backend else None
                    all_m = model_manager.get_models(model_type="price_prediction", symbol=symbol)
                    logger.info(
                        f"503 diagnostic: use_file_backend={model_manager.use_file_backend}, "
                        f"active_model={active}, models_count={len(all_m) if all_m else 0}"
                    )
                logger.error(
                    f"Price prediction model for {symbol} is not available. "
                    f"price_strategy.model is None. "
                    f"Please train and activate a model for this symbol."
                )
                raise HTTPException(
                    status_code=503,
                    detail=(
                        f"Price prediction model for {symbol} is not available. "
                        "Please train and activate a model for this symbol."
                    )
                )
        
        if momentum_model:
            momentum_strategy.model = momentum_model
        elif momentum_strategy.model is None or (hasattr(momentum_strategy.model, 'model') and momentum_strategy.model.model is None):
            logger.warning(f"Momentum intensity model for {symbol} is not available. Signal generation will continue without momentum.")
        
        # 最新の市場データを取得（過去数分間のデータが必要）
        end_time = request.timestamp
        start_time = end_time - pd.Timedelta(minutes=5)

        logger.debug(f"/signal endpoint called: symbol={symbol}, request_timestamp={request.timestamp}, end_time={end_time}, start_time={start_time}")

        # バックグラウンドローダーからデータを取得（優先）
        if bg_loader and bg_loader.running:
            df, features = await bg_loader.get_data()
            if df is None:
                # フォールバック: キャッシュ/同期ロード
                try:
                    df, features = get_cached_market_data(request.symbol, start_time, end_time)
                except Exception as e:
                    logger.warning("Background data not ready, get_cached_market_data failed: %s", e)
                    raise
        else:
            # キャッシュを使用してマーケットデータと特徴量を取得
            try:
                df, features = get_cached_market_data(request.symbol, start_time, end_time)
            except Exception as e:
                logger.warning("get_cached_market_data failed: %s", e)
                raise

        if df is None or len(df) == 0:
            error_detail = (
                f"No market data available for {request.symbol} "
                f"between {start_time} and {end_time}. "
                f"Please check if data exists in the database for this time range."
            )
            raise HTTPException(status_code=404, detail=error_detail)

        from api.signal_generation import generate_signal_from_features

        result = generate_signal_from_features(
            request.symbol,
            df,
            features,
            request.mid_price,
            price_strategy,
            momentum_strategy,
            log=logger,
        )
        if result is None:
            raise HTTPException(
                status_code=500,
                detail="Signal generation failed (no prediction or index mismatch)",
            )

        signal_type = result["signal_type"]
        confidence = result["confidence"]
        predicted_price = result["predicted_price"]
        current_price = result["current_price"]
        price_change_pct = result["price_change_pct"]
        momentum_intensity_value = result.get("momentum_intensity")

        # 価格予測と信頼度を1行でターミナル・ログファイルに出力
        logger.info(
            "[SIGNAL] %s %s predicted_price=%.2f confidence=%.2f",
            request.symbol,
            signal_type,
            predicted_price,
            confidence,
        )

        return SignalResponse(
            symbol=request.symbol,
            timestamp=request.timestamp,
            signal_type=signal_type,
            confidence=confidence,
            predicted_price=predicted_price,
            current_price=current_price,
            price_change_pct=price_change_pct,
            momentum_intensity=momentum_intensity_value
        )
    
    except HTTPException:
        # HTTPExceptionはそのまま再スロー
        raise
    except Exception as e:
        import traceback
        error_msg = f"Signal generation error: {type(e).__name__}: {str(e)}"
        logger.error(f"[ERROR] {error_msg}", exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)


# 再訓練関連のリクエスト/レスポンスモデルは上で既に定義されているため、重複定義を削除


# トレーニングとバックテストは別のAPIサーバーに分離されました
# training_app.py (Port 8001) と backtest_app.py (Port 8002) を参照してください

# トレーニングとバックテストのエンドポイントは training_app.py と backtest_app.py に移動しました
# 以下のコードは削除されています

def _convert_to_json_serializable(obj):
    """numpy型やpandas型をPython標準型に変換"""
    import numpy as np
    import pandas as pd
    
    if isinstance(obj, (np.integer, np.floating)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, pd.Series):
        return obj.tolist()
    elif isinstance(obj, pd.DataFrame):
        return obj.to_dict('records')
    elif isinstance(obj, dict):
        return {k: _convert_to_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_convert_to_json_serializable(item) for item in obj]
    elif pd.isna(obj):
        return None
    else:
        return obj


# ExchSim実行関連のリクエスト/レスポンスモデル
class ExchSimRequest(BaseModel):
    """ExchSim実行リクエスト"""
    model_name: str = Field(..., description="Model name (e.g., my_model_v1)")
    model_type: str = Field(..., description="Model type: 'price_prediction' or 'momentum_intensity'")
    symbol: str = Field(..., description="Symbol (e.g., G_FX_BTCJPY)")
    mode: str = Field(..., description="Execution mode: 'realtime' or 'period'")
    start_date: Optional[str] = Field(None, description="Start date (ISO 8601 format, period mode only)")
    end_date: Optional[str] = Field(None, description="End date (ISO 8601 format, period mode only)")
    risk_config: Dict = Field(default_factory=lambda: {
        "max_position_size": 0.01,
        "max_daily_loss": 100000,
        "stop_loss_pct": 0.36
    }, description="Risk configuration")
    exchsim_config: Dict = Field(..., description="ExchSim connection configuration (url, username, password)")


class ExchSimResponse(BaseModel):
    """ExchSim実行レスポンス"""
    status: str
    job_id: str
    message: str


class ExchSimStatusResponse(BaseModel):
    """ExchSim実行ステータスレスポンス"""
    job_id: str
    status: str  # "pending", "running", "completed", "stopped", "error"
    progress: Optional[float] = None
    message: Optional[str] = None
    metrics: Optional[Dict] = None


async def exchsim_task(job_id: str, request: ExchSimRequest):
    """バックグラウンドでExchSim実行を実行するタスク"""
    global exchsim_jobs, exchsim_executors
    
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
    
    exchsim_jobs[job_id] = {
        "status": "running",
        "progress": 0.0,
        "message": "ExchSim execution started",
        "metrics": None
    }
    
    try:
        # ExchSim実行を開始
        executor = ExchSimExecutor(
            model_name=request.model_name,
            model_type=request.model_type,
            symbol=request.symbol,
            exchsim_url=request.exchsim_config.get("url"),
            username=request.exchsim_config.get("username"),
            password=request.exchsim_config.get("password"),
            risk_config=request.risk_config,
            mode=request.mode,
            start_date=start_date,
            end_date=end_date
        )
        
        # executorを保存（停止用）
        exchsim_executors[job_id] = executor
        
        # 実行（別スレッドで実行される想定）
        result = executor.run()
        
        if result.get("status") == "completed":
            exchsim_jobs[job_id] = {
                "status": "completed",
                "progress": 1.0,
                "message": "ExchSim execution completed successfully",
                "metrics": result.get("metrics", {})
            }
        elif result.get("status") == "error":
            exchsim_jobs[job_id] = {
                "status": "error",
                "progress": 0.0,
                "message": f"ExchSim execution failed: {result.get('error', 'Unknown error')}",
                "metrics": None
            }
    except Exception as e:
        import traceback
        error_msg = str(e)
        traceback.print_exc()
        exchsim_jobs[job_id] = {
            "status": "error",
            "progress": 0.0,
            "message": f"ExchSim execution error: {error_msg}",
            "metrics": None
        }
    finally:
        # executorを削除
        if job_id in exchsim_executors:
            del exchsim_executors[job_id]


@app.post("/exchsim/run", response_model=ExchSimResponse)
async def run_exchsim(request: ExchSimRequest, background_tasks: BackgroundTasks):
    """
    ExchSimでの実行を開始
    
    非同期で実行され、即座にジョブIDを返します。
    進捗は GET /exchsim/{job_id}/status で確認できます。
    """
    job_id = str(uuid.uuid4())
    
    # バックグラウンドタスクとして実行
    background_tasks.add_task(exchsim_task, job_id, request)
    
    return ExchSimResponse(
        status="accepted",
        job_id=job_id,
        message="ExchSim execution started"
    )


@app.get("/exchsim/{job_id}/status", response_model=ExchSimStatusResponse)
async def get_exchsim_status(job_id: str):
    """ExchSim実行ジョブのステータスを取得"""
    try:
        if job_id not in exchsim_jobs:
            logger.warning(f"ExchSim job not found: {job_id}")
            raise HTTPException(status_code=404, detail="Job not found")
        
        job_status = exchsim_jobs[job_id]
        
        # executorから最新のメトリクスを取得
        if job_id in exchsim_executors:
            executor = exchsim_executors[job_id]
            if executor.is_running:
                # ポジションサマリーを取得してメトリクスを更新
                position_summary = executor.get_position_summary()
                if position_summary:
                    positions = position_summary.get("positions", [])
                    for pos in positions:
                        if pos.get("symbol") == executor.symbol:
                            job_status["metrics"] = {
                                "current_position": pos.get("quantity", 0.0),
                                "real_time_pnl": pos.get("unrealizedPnl", 0.0),
                                "total_trades": executor.metrics.get("total_trades", 0),
                                "win_rate": executor.metrics.get("win_rate", 0.0)
                            }
        
        metrics = job_status.get("metrics")
        
        # metricsをJSONシリアライズ可能な形式に変換
        if metrics is not None:
            try:
                metrics = _convert_to_json_serializable(metrics)
                # 変換後の結果がJSONシリアライズ可能か確認
                import json
                json.dumps(metrics, default=str)
            except (TypeError, ValueError) as e:
                logger.warning(f"Failed to serialize metrics for ExchSim job {job_id}: {e}, converting to None")
                metrics = None
        
        return ExchSimStatusResponse(
            job_id=job_id,
            status=job_status["status"],
            progress=job_status.get("progress"),
            message=job_status.get("message"),
            metrics=metrics
        )
    except HTTPException:
        # HTTPExceptionはそのまま再スロー
        raise
    except Exception as e:
        import traceback
        error_msg = f"Error getting ExchSim status: {str(e)}"
        error_detail = traceback.format_exc()
        logger.error(f"{error_msg}\n{error_detail}")
        raise HTTPException(status_code=500, detail=error_msg)


@app.post("/exchsim/{job_id}/stop")
async def stop_exchsim(job_id: str):
    """ExchSim実行を停止"""
    if job_id not in exchsim_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job_status = exchsim_jobs[job_id]
    
    if job_id in exchsim_executors:
        executor = exchsim_executors[job_id]
        executor.stop()
        
        exchsim_jobs[job_id] = {
            "status": "stopped",
            "progress": job_status.get("progress", 0.0),
            "message": "ExchSim execution stopped",
            "metrics": job_status.get("metrics")
        }
        
        return {"status": "success", "message": "ExchSim execution stopped"}
    else:
        raise HTTPException(status_code=400, detail="Execution is not running")


@app.get("/models", response_model=ModelsListResponse)
async def get_models(
    model_name: Optional[str] = None,
    model_type: Optional[str] = None,
    symbol: Optional[str] = None
):
    """保存されたモデルの一覧を取得"""
    try:
        logger.info(f"get_models called with: model_name={model_name}, model_type={model_type}, symbol={symbol}")
        if model_manager is None:
            logger.error("ModelManager is None")
            raise HTTPException(status_code=503, detail="ModelManager not initialized")
        
        try:
            # ModelManagerの状態を確認
            logger.info(f"ModelManager state: use_file_backend={model_manager.use_file_backend}, conn={model_manager.conn is not None}")
            if model_manager.conn:
                logger.info(f"Connection closed: {model_manager.conn.closed}")
            
            models = model_manager.get_models(
                model_name=model_name,
                model_type=model_type,
                symbol=symbol
            )
            logger.info(f"model_manager.get_models returned {len(models)} models")
        except Exception as e:
            logger.error(f"Error calling model_manager.get_models: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # エラーが発生した場合は空のリストを返す
            models = []
        
        logger.info(f"Processing {len(models)} models for serialization")
        # 各モデルのmetricsをJSONシリアライズ可能な形式に変換
        serialized_models = []
        for model in models:
            model_dict = dict(model)
            # metricsフィールドの処理
            if "metrics" not in model_dict or model_dict["metrics"] is None:
                model_dict["metrics"] = {}
            else:
                try:
                    model_dict["metrics"] = _convert_to_json_serializable(model_dict["metrics"])
                except Exception as e:
                    logger.warning(f"Failed to serialize metrics for model {model_dict.get('model_name')}: {e}")
                    # エラーが発生した場合は空の辞書に置き換え
                    model_dict["metrics"] = {}
            
            # DBベースの場合はfile_pathが存在しないため、仮のパスを生成（後方互換性のため）
            if "file_path" not in model_dict or model_dict.get("file_path") is None:
                # DBベースの場合、仮のファイルパスを生成（実際のファイルはDBに保存されている）
                model_dict["file_path"] = f"db://{model_dict.get('model_name', 'unknown')}_{model_dict.get('model_type', 'unknown')}_{model_dict.get('symbol', 'unknown')}.joblib"
            
            # datetimeオブジェクトを文字列に変換
            datetime_fields = ["trained_at", "training_start_time", "training_end_time", "created_at", "updated_at"]
            for field in datetime_fields:
                if field in model_dict and isinstance(model_dict[field], datetime):
                    model_dict[field] = model_dict[field].isoformat()
                elif field == "trained_at" and field not in model_dict:
                    model_dict["trained_at"] = ""
            
            # trained_atが必須フィールドなので、存在しない場合は空文字列を設定
            if "trained_at" not in model_dict:
                model_dict["trained_at"] = ""
            
            # ModelInfoResponseに必要なフィールドのみを抽出
            # 不要なフィールド（id, training_start_time, training_end_time, created_at, updated_at, training_data_stats, model_data）を除外
            response_dict = {
                "model_name": model_dict.get("model_name", ""),
                "symbol": model_dict.get("symbol", ""),
                "model_type": model_dict.get("model_type", ""),
                "file_path": model_dict.get("file_path"),
                "trained_at": model_dict.get("trained_at", ""),
                "training_window_days": model_dict.get("training_window_days"),
                "metrics": model_dict.get("metrics", {}),
                "is_active": model_dict.get("is_active", False)
            }
            
            # すべての必須フィールドが存在することを確認
            try:
                serialized_models.append(ModelInfoResponse(**response_dict))
            except Exception as e:
                logger.error(f"Failed to create ModelInfoResponse for model {model_dict.get('model_name')}: {e}")
                logger.error(f"Model dict keys: {list(model_dict.keys())}")
                logger.error(f"Response dict: {response_dict}")
                import traceback
                logger.error(traceback.format_exc())
                # エラーが発生したモデルはスキップ
                continue
        
        logger.info(f"Successfully serialized {len(serialized_models)} models")
        return ModelsListResponse(models=serialized_models)
    except HTTPException:
        # HTTPExceptionはそのまま再スロー
        raise
    except Exception as e:
        import traceback
        error_msg = f"Error getting models: {str(e)}"
        error_detail = traceback.format_exc()
        logger.error(f"{error_msg}\n{error_detail}")
        raise HTTPException(status_code=500, detail=error_msg)


@app.post("/models/activate")
async def activate_model(request: ActivateModelRequest):
    """指定したモデルをアクティブにする（予測APIで使用）"""
    global price_strategy, momentum_strategy, model_manager
    
    if model_manager is None:
        raise HTTPException(status_code=503, detail="ModelManager not initialized")
    
    try:
        # 1. まずDBでis_activeを更新（モデルがロードできなくてもアクティベートは成功させる）
        success = model_manager.activate_model(
            model_name=request.model_name,
            model_type=request.model_type,
            symbol=request.symbol
        )
        if not success:
            # 診断: 利用可能なモデルタイプを返す
            try:
                all_for_symbol = model_manager.get_models(
                    model_name=request.model_name, symbol=request.symbol
                )
                if all_for_symbol:
                    types_found = list({m.get("model_type") for m in all_for_symbol})
                    raise HTTPException(
                        status_code=404,
                        detail=(
                            f"Model not found: model_name={request.model_name!r}, "
                            f"model_type={request.model_type!r}, symbol={request.symbol!r}. "
                            f"Available model_types for this model: {types_found}. "
                            f"Try model_type from the list above."
                        )
                    )
            except HTTPException:
                raise
            raise HTTPException(status_code=404, detail="Model not found or activation failed")
        
        # 2. モデルを読み込んでメモリにキャッシュ（失敗してもDBのアクティベートは成功）
        model = None
        try:
            model = model_manager.load_model(
                model_name=request.model_name,
                model_type=request.model_type,
                symbol=request.symbol
            )
        except Exception as load_err:
            logger.warning(
                f"Failed to load model into memory (DB activation succeeded): "
                f"{type(load_err).__name__}: {load_err}"
            )
        
        # 3. ロード成功時のみグローバル変数とキャッシュを更新
        if model is not None:
            if request.model_type == "price_prediction":
                if price_strategy is not None:
                    price_strategy.model = model
                    # シンボルキャッシュをクリア（次の/signalで再ロード）
                    if request.symbol in symbol_model_cache:
                        symbol_model_cache[request.symbol].pop('price_model', None)
                model_dir = ModelConfig.MODEL_DIR
                default_path = os.path.join(model_dir, f'price_prediction_{request.symbol}.joblib')
                if os.path.exists(default_path):
                    backup_path = f"{default_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    shutil.copy(default_path, backup_path)
                try:
                    exported_path = model_manager.get_model_file_path(
                        model_type=request.model_type,
                        symbol=request.symbol,
                        export_path=default_path
                    )
                    logger.info(f"Exported active model to {exported_path} for backward compatibility")
                except Exception as e:
                    logger.warning(f"Failed to export model for backward compatibility: {e}")
            elif request.model_type == "momentum_intensity":
                if momentum_strategy is not None:
                    momentum_strategy.model = model
                    if request.symbol in symbol_model_cache:
                        symbol_model_cache[request.symbol].pop('momentum_model', None)
                model_dir = ModelConfig.MODEL_DIR
                default_path = os.path.join(model_dir, f'momentum_intensity_{request.symbol}.joblib')
                if os.path.exists(default_path):
                    backup_path = f"{default_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    shutil.copy(default_path, backup_path)
                try:
                    exported_path = model_manager.get_model_file_path(
                        model_type=request.model_type,
                        symbol=request.symbol,
                        export_path=default_path
                    )
                    logger.info(f"Exported active model to {exported_path} for backward compatibility")
                except Exception as e:
                    logger.warning(f"Failed to export model for backward compatibility: {e}")
        
        return {
            "status": "success",
            "message": f"Model {request.model_name} ({request.model_type}) activated for {request.symbol}"
        }
        
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        import traceback
        logger.error(f"Activate model failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to activate model: {type(e).__name__}: {str(e) or repr(e)}"
        )


@app.delete("/models/{model_name}")
async def delete_model(
    model_name: str,
    model_type: Optional[str] = None,
    symbol: Optional[str] = None
):
    """指定したモデルを削除"""
    if model_manager is None:
        raise HTTPException(status_code=503, detail="ModelManager not initialized")
    
    try:
        success = model_manager.delete_model(
            model_name=model_name,
            model_type=model_type,
            symbol=symbol
        )
        
        if success:
            return {
                "status": "success",
                "message": f"Model {model_name} deleted"
            }
        else:
            raise HTTPException(status_code=404, detail="Model not found")
            
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to delete model: {str(e)}")


# Prediction Tracker API Endpoints
@app.get("/prediction-tracker/predictions")
async def get_predictions(
    symbol: Optional[str] = None,
    horizon: Optional[str] = None,
    limit: int = 100
):
    """予測結果を取得"""
    import psycopg2
    from config.settings import DatabaseConfig
    
    conn = psycopg2.connect(DatabaseConfig.get_connection_string())
    try:
        with conn.cursor() as cur:
            query = """
                SELECT * FROM prediction_tracker_predictions
                WHERE 1=1
            """
            params = []
            
            if symbol:
                query += " AND symbol = %s"
                params.append(symbol)
            if horizon:
                query += " AND horizon = %s"
                params.append(horizon)
            
            query += " ORDER BY prediction_timestamp DESC LIMIT %s"
            params.append(limit)
            
            cur.execute(query, params)
            results = cur.fetchall()
            
            # 結果を辞書形式に変換
            columns = [desc[0] for desc in cur.description]
            predictions = [dict(zip(columns, row)) for row in results]
            
            return {"predictions": predictions}
    finally:
        conn.close()


@app.get("/prediction-tracker/verifications")
async def get_verifications(
    symbol: Optional[str] = None,
    horizon: Optional[str] = None,
    limit: int = 100
):
    """検証結果を取得"""
    import psycopg2
    from config.settings import DatabaseConfig
    
    conn = psycopg2.connect(DatabaseConfig.get_connection_string())
    try:
        with conn.cursor() as cur:
            query = """
                SELECT * FROM prediction_tracker_verifications
                WHERE 1=1
            """
            params = []
            
            if symbol:
                query += " AND symbol = %s"
                params.append(symbol)
            if horizon:
                query += " AND horizon = %s"
                params.append(horizon)
            
            query += " ORDER BY actual_timestamp DESC LIMIT %s"
            params.append(limit)
            
            cur.execute(query, params)
            results = cur.fetchall()
            
            # 結果を辞書形式に変換
            columns = [desc[0] for desc in cur.description]
            verifications = [dict(zip(columns, row)) for row in results]
            
            return {"verifications": verifications}
    finally:
        conn.close()


@app.get("/prediction-tracker/metrics")
async def get_metrics(
    horizon: Optional[str] = None,
    window_hours: int = 24
):
    """予測精度のメトリクスを取得"""
    try:
        prediction_tracker = globals().get('prediction_tracker')
        if prediction_tracker is None:
            raise HTTPException(status_code=503, detail="PredictionTracker not initialized")
        
        if horizon:
            metrics = prediction_tracker.metrics.get_metrics(horizon, window_hours)
            if metrics:
                metrics = _convert_to_json_serializable(metrics)
            return {"metrics": metrics} if metrics else {"metrics": None}
        else:
            all_metrics = {}
            for h in ['1m', '5m', '10m']:
                m = prediction_tracker.metrics.get_metrics(h, window_hours)
                if m:
                    all_metrics[h] = _convert_to_json_serializable(m)
            return {"metrics": all_metrics}
    except HTTPException:
        # HTTPExceptionはそのまま再スロー
        raise
    except Exception as e:
        import traceback
        error_msg = f"Error getting prediction tracker metrics: {str(e)}"
        error_detail = traceback.format_exc()
        logger.error(f"{error_msg}\n{error_detail}")
        raise HTTPException(status_code=500, detail=error_msg)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)

