"""
既存モデルのメトリクスを計算してmetadata.jsonを更新するスクリプト
モデルファイルを読み込んで検証データで評価し、メトリクスを計算します
"""
import sys
import os
from datetime import datetime, timedelta, timezone
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
from config.settings import DatabaseConfig, ModelConfig
from api.model_manager import ModelManager


def evaluate_price_prediction_model(model_path: str, symbol: str, validation_days: int = 1) -> dict:
    """
    価格予測モデルを評価してメトリクスを計算
    
    Args:
        model_path: モデルファイルのパス
        symbol: シンボル
        validation_days: 検証データの日数
    
    Returns:
        メトリクスの辞書
    """
    # データローダーの初期化
    use_exch_sim_db = DatabaseConfig.USE_EXCH_SIM_DB
    if use_exch_sim_db:
        data_loader = ExchSimDataLoader()
    else:
        data_loader = MarketDataLoader()
    
    # 特徴量エンジニアの初期化
    feature_set_name = os.getenv('FEATURE_SET_NAME', 'standard_features')
    use_configurable = os.getenv('USE_CONFIGURABLE_FEATURES', 'true').lower() == 'true'
    
    if use_configurable:
        try:
            feature_engineer = ConfigurableFeatureEngineer(feature_set_name=feature_set_name)
        except Exception as e:
            print(f"Warning: Failed to initialize ConfigurableFeatureEngineer: {e}")
            feature_engineer = FeatureEngineer()
    else:
        feature_engineer = FeatureEngineer()
    
    # 検証データの期間を設定
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=validation_days)
    
    # データの読み込み
    print(f"  Loading validation data from {start_date} to {end_date}...")
    df = data_loader.load_training_data(symbol, start_date, end_date, skip_min_samples_check=True)
    
    if len(df) == 0:
        print(f"  ⚠️  検証データが見つかりませんでした")
        return {
            'mae': 0.0,
            'rmse': 0.0,
            'mape': 0.0,
            'training_samples': 0,
            'validation_samples': 0
        }
    
    # 特徴量エンジニアリング
    df = feature_engineer.engineer_features(df)
    
    # モデルを読み込んで評価
    strategy = PricePredictionStrategy(
        timeframes=[1, 5, 30],
        prediction_horizon=60
    )
    strategy.model.load(model_path)
    
    # データを訓練/検証に分割（80/20）
    split_idx = int(len(df) * 0.8)
    train_df = df.iloc[:split_idx].copy()
    val_df = df.iloc[split_idx:].copy()
    
    print(f"  Training samples: {len(train_df)}, Validation samples: {len(val_df)}")
    
    # 検証データで予測
    val_predictions = strategy.predict(val_df)
    
    # 実際の価格を取得
    if 'exec_price_all' in val_df.columns:
        actual_prices = val_df['exec_price_all']
    else:
        actual_prices = val_df['mid_price']
    
    # prediction_horizon秒後の実際の価格
    prediction_horizon = 60
    actual_prices_future = actual_prices.shift(-prediction_horizon)
    
    # 有効なデータのみを使用
    valid_mask = val_predictions.notna() & actual_prices_future.notna()
    valid_predictions = val_predictions[valid_mask]
    valid_actuals = actual_prices_future[valid_mask]
    
    if len(valid_predictions) == 0:
        print(f"  ⚠️  有効な予測データがありませんでした")
        return {
            'mae': 0.0,
            'rmse': 0.0,
            'mape': 0.0,
            'training_samples': len(train_df),
            'validation_samples': len(val_df)
        }
    
    # メトリクスを計算
    errors = valid_predictions - valid_actuals
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors ** 2)))
    mape = float(np.mean(np.abs(errors / (valid_actuals + 1e-9) * 100)))
    
    print(f"  ✅ MAE: {mae:,.0f} JPY, RMSE: {rmse:,.0f} JPY, MAPE: {mape:.2f}%")
    
    return {
        'mae': mae,
        'rmse': rmse,
        'mape': mape,
        'training_samples': len(train_df),
        'validation_samples': len(val_df)
    }


def evaluate_momentum_intensity_model(model_path: str, symbol: str, validation_days: int = 1) -> dict:
    """
    モメンタム強度モデルを評価してメトリクスを計算
    
    Args:
        model_path: モデルファイルのパス
        symbol: シンボル
        validation_days: 検証データの日数
    
    Returns:
        メトリクスの辞書
    """
    # データローダーの初期化
    use_exch_sim_db = DatabaseConfig.USE_EXCH_SIM_DB
    if use_exch_sim_db:
        data_loader = ExchSimDataLoader()
    else:
        data_loader = MarketDataLoader()
    
    # 特徴量エンジニアの初期化
    feature_set_name = os.getenv('FEATURE_SET_NAME', 'standard_features')
    use_configurable = os.getenv('USE_CONFIGURABLE_FEATURES', 'true').lower() == 'true'
    
    if use_configurable:
        try:
            feature_engineer = ConfigurableFeatureEngineer(feature_set_name=feature_set_name)
        except Exception as e:
            print(f"Warning: Failed to initialize ConfigurableFeatureEngineer: {e}")
            feature_engineer = FeatureEngineer()
    else:
        feature_engineer = FeatureEngineer()
    
    # 検証データの期間を設定
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=validation_days)
    
    # データの読み込み
    print(f"  Loading validation data from {start_date} to {end_date}...")
    df = data_loader.load_training_data(symbol, start_date, end_date, skip_min_samples_check=True)
    
    if len(df) == 0:
        print(f"  ⚠️  検証データが見つかりませんでした")
        return {
            'mae': 0.0,
            'rmse': 0.0,
            'mape': 0.0,
            'direction_accuracy': 0.0,
            'training_samples': 0,
            'validation_samples': 0
        }
    
    # 特徴量エンジニアリング
    df = feature_engineer.engineer_features(df)
    
    # モデルを読み込んで評価
    strategy = MomentumIntensityStrategy(
        timeframes=[1, 5, 30],
        prediction_horizon=60
    )
    strategy.model.load(model_path)
    
    # データを訓練/検証に分割（80/20）
    split_idx = int(len(df) * 0.8)
    train_df = df.iloc[:split_idx].copy()
    val_df = df.iloc[split_idx:].copy()
    
    print(f"  Training samples: {len(train_df)}, Validation samples: {len(val_df)}")
    
    # 検証データで予測
    val_predictions = strategy.predict_intensity(val_df)
    
    # 実際の価格を取得
    if 'exec_price_all' in val_df.columns:
        actual_prices = val_df['exec_price_all']
    else:
        actual_prices = val_df['mid_price']
    
    # prediction_horizon秒後の実際の価格
    prediction_horizon = 60
    actual_prices_future = actual_prices.shift(-prediction_horizon)
    
    # 有効なデータのみを使用
    valid_mask = val_predictions.notna() & actual_prices_future.notna()
    valid_predictions = val_predictions[valid_mask]
    valid_actuals = actual_prices_future[valid_mask]
    
    if len(valid_predictions) == 0:
        print(f"  ⚠️  有効な予測データがありませんでした")
        return {
            'mae': 0.0,
            'rmse': 0.0,
            'mape': 0.0,
            'direction_accuracy': 0.0,
            'training_samples': len(train_df),
            'validation_samples': len(val_df)
        }
    
    # 方向性の精度を計算
    current_prices = val_df.loc[valid_predictions.index, actual_prices.name]
    pred_changes = (valid_predictions.values / 100.0) * current_prices.values
    actual_changes = (valid_actuals.values - current_prices.values)
    direction_accuracy = float(
        np.mean(np.sign(pred_changes) == np.sign(actual_changes)) * 100
    )
    
    # 誤差の計算（変化率ベース）
    pred_change_pct = pred_changes / current_prices.values * 100
    actual_change_pct = actual_changes / current_prices.values * 100
    errors_pct = pred_change_pct - actual_change_pct
    
    mae = float(np.mean(np.abs(errors_pct)))
    rmse = float(np.sqrt(np.mean(errors_pct ** 2)))
    mape = float(np.mean(np.abs(errors_pct)))
    
    print(f"  ✅ MAE: {mae:.4f}%, RMSE: {rmse:.4f}%, MAPE: {mape:.4f}%, Direction Accuracy: {direction_accuracy:.2f}%")
    
    return {
        'mae': mae,
        'rmse': rmse,
        'mape': mape,
        'direction_accuracy': direction_accuracy,
        'training_samples': len(train_df),
        'validation_samples': len(val_df)
    }


def update_model_metrics(model_info: dict, model_manager: ModelManager, validation_days: int = 1) -> bool:
    """
    モデルのメトリクスを更新
    
    Args:
        model_info: モデル情報の辞書（metadata.jsonのエントリ）
        model_manager: ModelManagerインスタンス
        validation_days: 検証データの日数
    
    Returns:
        更新に成功した場合はTrue
    """
    model_name = model_info['model_name']
    model_type = model_info['model_type']
    symbol = model_info['symbol']
    model_path = model_info['file_path']
    
    print(f"\n📊 Evaluating model: {model_name} ({model_type}, {symbol})")
    
    # モデルファイルの存在確認
    if not os.path.exists(model_path):
        print(f"  ❌ モデルファイルが見つかりません: {model_path}")
        return False
    
    try:
        # モデルタイプに応じて評価
        if model_type == 'price_prediction':
            metrics = evaluate_price_prediction_model(model_path, symbol, validation_days)
        elif model_type == 'momentum_intensity':
            metrics = evaluate_momentum_intensity_model(model_path, symbol, validation_days)
        else:
            print(f"  ❌ サポートされていないモデルタイプ: {model_type}")
            return False
        
        # metadata.jsonの該当モデルを更新
        models = model_manager.get_models()
        for model in models:
            if (model['model_name'] == model_name and
                model['model_type'] == model_type and
                model['symbol'] == symbol and
                model['file_path'] == model_path):
                model['metrics'] = metrics
                break
        
        # メタデータを保存
        model_manager._save_metadata()
        
        print(f"  ✅ メトリクスを更新しました")
        return True
    
    except Exception as e:
        print(f"  ❌ エラー: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """メイン処理"""
    # ModelManagerの初期化
    model_manager = ModelManager()
    
    print("=" * 60)
    print("モデルメトリクス更新スクリプト")
    print("=" * 60)
    print()
    
    # すべてのモデルを取得
    all_models = model_manager.get_models()
    
    # メトリクスがデフォルト値（0.0）のモデルをフィルタ
    models_to_update = []
    for model in all_models:
        metrics = model.get('metrics', {})
        if metrics.get('mae', 0.0) == 0.0 and metrics.get('rmse', 0.0) == 0.0:
            models_to_update.append(model)
    
    print(f"📊 全モデル数: {len(all_models)}")
    print(f"🔄 更新対象モデル数: {len(models_to_update)}")
    print()
    
    if len(models_to_update) == 0:
        print("✅ 更新が必要なモデルはありません")
        return
    
    # 各モデルのメトリクスを更新
    updated_count = 0
    error_count = 0
    
    for model in models_to_update:
        if update_model_metrics(model, model_manager, validation_days=1):
            updated_count += 1
        else:
            error_count += 1
    
    print()
    print("=" * 60)
    print(f"✅ 更新完了: {updated_count}件")
    print(f"❌ エラー: {error_count}件")
    print("=" * 60)


if __name__ == "__main__":
    main()

