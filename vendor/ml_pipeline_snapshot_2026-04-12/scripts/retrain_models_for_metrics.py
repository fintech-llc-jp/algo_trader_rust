"""
既存モデルを再訓練してメトリクスを計算し、metadata.jsonを更新するスクリプト
モデルファイルが古いバージョンで保存されている場合など、再訓練が必要な場合に使用
"""
import sys
import os
from datetime import datetime, timedelta, timezone

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.training_service import train_models
from api.model_manager import ModelManager
from config.settings import DatabaseConfig


def retrain_model_and_update_metrics(
    model_name: str,
    model_type: str,
    symbol: str,
    model_manager: ModelManager,
    training_window_days: int = 1
) -> bool:
    """
    モデルを再訓練してメトリクスを計算し、metadata.jsonを更新
    
    Args:
        model_name: モデル名
        model_type: モデルタイプ ("price_prediction" or "momentum_intensity")
        symbol: シンボル
        model_manager: ModelManagerインスタンス
        training_window_days: 訓練データの期間（日数）
    
    Returns:
        成功した場合はTrue
    """
    print(f"\n🔄 Retraining model: {model_name} ({model_type}, {symbol})")
    
    # 訓練するモデルを決定
    if model_type == "price_prediction":
        models_to_train = ["price"]
    elif model_type == "momentum_intensity":
        models_to_train = ["momentum"]
    else:
        print(f"  ❌ サポートされていないモデルタイプ: {model_type}")
        return False
    
    try:
        # モデルを訓練
        print(f"  Training with {training_window_days} days of data...")
        results = train_models(
            symbol=symbol,
            model_name=f"{model_name}_retrained",  # 一時的なモデル名
            training_window_days=training_window_days,
            models=models_to_train
        )
        
        # 訓練結果の取得
        if results.get("status") != "success":
            error_msg = results.get("error", "Unknown error")
            print(f"  ❌ 訓練に失敗しました: {error_msg}")
            return False
        
        # results辞書から該当モデルの結果を取得
        model_results = results.get("results", {})
        if model_type == "price_prediction":
            train_result = model_results.get("price_prediction")
        else:
            train_result = model_results.get("momentum_intensity")
        
        if not train_result:
            print(f"  ❌ 訓練結果が取得できませんでした")
            return False
        
        # メトリクスを取得
        metrics = {
            'mae': train_result.get('mae', 0.0),
            'rmse': train_result.get('rmse', 0.0),
            'mape': train_result.get('mape', 0.0),
            'training_samples': train_result.get('training_samples', 0),
            'validation_samples': train_result.get('validation_samples', 0)
        }
        
        if model_type == "momentum_intensity":
            metrics['direction_accuracy'] = train_result.get('direction_accuracy', 0.0)
        
        print(f"  ✅ Metrics calculated:")
        if model_type == "price_prediction":
            print(f"     MAE: {metrics['mae']:,.0f} JPY")
            print(f"     RMSE: {metrics['rmse']:,.0f} JPY")
            print(f"     MAPE: {metrics['mape']:.2f}%")
        else:
            print(f"     MAE: {metrics['mae']:.4f}%")
            print(f"     RMSE: {metrics['rmse']:.4f}%")
            print(f"     MAPE: {metrics['mape']:.4f}%")
            print(f"     Direction Accuracy: {metrics['direction_accuracy']:.2f}%")
        
        # 元のモデル情報を取得
        original_models = model_manager.get_models(
            model_name=model_name,
            model_type=model_type,
            symbol=symbol
        )
        
        if not original_models:
            print(f"  ⚠️  元のモデル情報が見つかりませんでした")
            return False
        
        # 最初のモデル（最新のもの）のメトリクスを更新
        original_model = original_models[0]
        
        # metadata.jsonの該当モデルを更新
        all_models = model_manager.get_models()
        for model in all_models:
            if (model['model_name'] == model_name and
                model['model_type'] == model_type and
                model['symbol'] == symbol and
                model['file_path'] == original_model['file_path']):
                model['metrics'] = metrics
                break
        
        # メタデータを保存
        model_manager._save_metadata()
        
        print(f"  ✅ Metrics updated in metadata.json")
        
        # 一時的に作成されたモデルファイルを削除（オプション）
        # 必要に応じてコメントアウトを解除
        # retrained_file_path = train_result.get('file_path')
        # if retrained_file_path and os.path.exists(retrained_file_path):
        #     os.remove(retrained_file_path)
        #     print(f"  🗑️  Temporary model file removed")
        
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
    print("モデル再訓練によるメトリクス計算スクリプト")
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
    
    # 各モデルを再訓練してメトリクスを更新
    updated_count = 0
    error_count = 0
    
    for model in models_to_update:
        model_name = model['model_name']
        model_type = model['model_type']
        symbol = model['symbol']
        
        if retrain_model_and_update_metrics(
            model_name=model_name,
            model_type=model_type,
            symbol=symbol,
            model_manager=model_manager,
            training_window_days=1
        ):
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

