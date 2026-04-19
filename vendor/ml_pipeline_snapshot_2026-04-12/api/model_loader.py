"""
シンボルごとのモデルローダー
動的にモデルをロードしてキャッシュする
"""
import os
import logging
from typing import Optional, Dict, Any
from models.price_prediction_model import PricePredictionModel
from models.momentum_intensity_model import MomentumIntensityModel
from api.model_manager import ModelManager
from config.settings import ModelConfig

logger = logging.getLogger("ml_api")


def load_model_for_symbol(
    symbol: str,
    model_type: str,
    model_manager: ModelManager,
    strategy_instance = None
) -> Optional:
    """
    指定されたシンボルとモデルタイプのモデルをロード
    
    Args:
        symbol: シンボル（例: "B_FX_BTCJPY"）
        model_type: モデルタイプ（"price_prediction" または "momentum_intensity"）
        model_manager: ModelManagerインスタンス
        strategy_instance: 戦略インスタンス（モデルを設定する場合）
    
    Returns:
        ロードされたモデル、またはNone（見つからない場合）
    """
    if model_manager is None:
        logger.warning(f"ModelManager not initialized, cannot load model for {symbol}")
        return None
    
    try:
        # まずDBからアクティブモデルを取得
        if not model_manager.use_file_backend:
            try:
                active_model = model_manager.get_active_model(model_type, symbol)
                if active_model:
                    loaded_model = model_manager.load_model(
                        model_name=active_model['model_name'],
                        model_type=model_type,
                        symbol=symbol
                    )
                    logger.info(f"Loaded active {model_type} model for {symbol} from DB: {active_model['model_name']}")
                    
                    # 戦略インスタンスに設定
                    if strategy_instance is not None:
                        strategy_instance.model = loaded_model
                    
                    return loaded_model
                else:
                    all_models = model_manager.get_models(model_type=model_type, symbol=symbol)
                    logger.info(
                        f"get_active_model returned None for {model_type}/{symbol}: "
                        f"total_models={len(all_models)}, use_file_backend={model_manager.use_file_backend}"
                    )
                    if all_models:
                        logger.info(
                            f"Models in DB: {[(m.get('model_name'), m.get('is_active')) for m in all_models]}"
                        )
            except Exception as e:
                logger.warning(f"Failed to load {model_type} model for {symbol} from DB: {e}")
        
        # DBから取得できなかった場合、ファイルからロードを試みる
        model_dir = ModelConfig.MODEL_DIR
        if model_type == "price_prediction":
            model_path = os.path.join(model_dir, f'price_prediction_{symbol}.joblib')
            if os.path.exists(model_path):
                try:
                    loaded_model = PricePredictionModel.load(model_path)
                    logger.info(f"Loaded {model_type} model for {symbol} from file: {model_path}")
                    
                    # 戦略インスタンスに設定
                    if strategy_instance is not None:
                        strategy_instance.model = loaded_model
                    
                    return loaded_model
                except Exception as e:
                    logger.warning(f"Failed to load {model_type} model for {symbol} from file: {e}")
        
        elif model_type == "momentum_intensity":
            model_path = os.path.join(model_dir, f'momentum_intensity_{symbol}.joblib')
            if os.path.exists(model_path):
                try:
                    loaded_model = MomentumIntensityModel.load(model_path)
                    logger.info(f"Loaded {model_type} model for {symbol} from file: {model_path}")
                    
                    # 戦略インスタンスに設定
                    if strategy_instance is not None:
                        strategy_instance.model = loaded_model
                    
                    return loaded_model
                except Exception as e:
                    logger.warning(f"Failed to load {model_type} model for {symbol} from file: {e}")
        
        logger.warning(f"{model_type} model for {symbol} not found in DB or files")
        return None
        
    except Exception as e:
        logger.error(f"Error loading {model_type} model for {symbol}: {e}", exc_info=True)
        return None

