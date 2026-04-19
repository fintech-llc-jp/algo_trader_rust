"""
既存のモデルファイルをmetadata.jsonに登録するスクリプト
ファイル名からmodel_typeとsymbolを抽出して登録します
"""
import sys
import os
import re
from datetime import datetime
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.model_manager import ModelManager


def extract_model_info_from_filename(filename: str) -> dict:
    """
    ファイル名からモデル情報を抽出
    
    Args:
        filename: モデルファイル名（例: price_prediction_G_FX_BTCJPY.joblib）
    
    Returns:
        model_type, symbol, model_nameを含む辞書
    """
    # 拡張子を除く
    basename = os.path.splitext(filename)[0]
    
    # モデルタイプとシンボルを抽出
    # パターン1: {model_type}_{symbol} (例: price_prediction_G_FX_BTCJPY)
    # パターン2: {model_type}_{symbol}_{timestamp} (例: my_test_model_price_G_FX_BTCJPY_20251220_155838)
    
    # まず、既知のモデルタイプをチェック
    model_types = ['price_prediction', 'momentum_intensity']
    
    for model_type in model_types:
        # モデルタイプで始まるパターン
        pattern = f'^{model_type}_(.+)$'
        match = re.match(pattern, basename)
        if match:
            symbol = match.group(1)
            return {
                'model_type': model_type,
                'symbol': symbol,
                'model_name': basename  # ファイル名をそのままmodel_nameとして使用
            }
        
        # モデルタイプが含まれるパターン（例: my_test_model_price_G_FX_BTCJPY_20251220_155838）
        pattern = f'(.+?)(?:_{model_type})_(.+)$'
        match = re.match(pattern, basename)
        if match:
            model_name_prefix = match.group(1)
            symbol = match.group(2)
            # timestamp部分を除去（最後の_YYYYMMDD_HHMMSS形式）
            symbol = re.sub(r'_\d{8}_\d{6}$', '', symbol)
            return {
                'model_type': model_type,
                'symbol': symbol,
                'model_name': basename
            }
    
    # パターンが見つからない場合は、ファイル名をそのまま使用
    return {
        'model_type': 'unknown',
        'symbol': 'unknown',
        'model_name': basename
    }


def register_model_file(model_file_path: str, model_manager: ModelManager) -> bool:
    """
    モデルファイルをmetadata.jsonに登録
    
    Args:
        model_file_path: モデルファイルのフルパス
        model_manager: ModelManagerインスタンス
    
    Returns:
        登録に成功した場合はTrue、失敗またはスキップした場合はFalse
    """
    filename = os.path.basename(model_file_path)
    
    # ファイル名から情報を抽出
    info = extract_model_info_from_filename(filename)
    model_type = info['model_type']
    symbol = info['symbol']
    model_name = info['model_name']
    
    if model_type == 'unknown' or symbol == 'unknown':
        print(f"⚠️  スキップ: {filename} - モデルタイプまたはシンボルを特定できませんでした")
        return False
    
    # 既に登録されているかチェック
    existing_models = model_manager.get_models(
        model_name=model_name,
        model_type=model_type,
        symbol=symbol
    )
    
    # 同じファイルパスが既に登録されているかチェック
    for existing_model in existing_models:
        if existing_model.get('file_path') == model_file_path:
            print(f"⏭️  スキップ: {filename} - 既に登録されています")
            return False
    
    # ファイルの更新日時を取得
    file_stat = os.stat(model_file_path)
    trained_at = datetime.fromtimestamp(file_stat.st_mtime).isoformat()
    
    # デフォルトメタデータ
    default_metrics = {
        'mae': 0.0,
        'rmse': 0.0,
        'mape': 0.0,
        'training_samples': 0,
        'validation_samples': 0
    }
    
    # momentum_intensityの場合、追加のmetrics
    if model_type == 'momentum_intensity':
        default_metrics['direction_accuracy'] = 0.0
    
    # モデルを登録
    try:
        model_manager.register_model(
            model_name=model_name,
            model_type=model_type,
            symbol=symbol,
            file_path=model_file_path,
            training_window_days=1,  # デフォルト値
            metrics=default_metrics,
            is_active=False
        )
        
        # trained_atを更新（register_modelは現在時刻を使用するため、手動でファイルの更新日時に設定）
        models = model_manager.get_models(model_name=model_name, model_type=model_type, symbol=symbol)
        for model in models:
            if model.get('file_path') == model_file_path:
                model['trained_at'] = trained_at
                break
        
        model_manager._save_metadata()
        
        print(f"✅ 登録完了: {filename} ({model_type}, {symbol})")
        return True
    
    except Exception as e:
        print(f"❌ エラー: {filename} - {str(e)}")
        return False


def main():
    """メイン処理"""
    # ModelManagerの初期化
    model_manager = ModelManager()
    
    # モデルディレクトリ
    model_dir = model_manager.model_dir
    print(f"📁 モデルディレクトリ: {model_dir}")
    print()
    
    # 未登録のモデルファイルのリスト
    unregistered_files = [
        'momentum_intensity_B_FX_BTCJPY.joblib',
        'momentum_intensity_G_FX_BTCJPY.joblib',
        'price_prediction_B_FX_BTCJPY.joblib',
        'price_prediction_G_FX_BTCJPY.joblib'
    ]
    
    # 登録済みモデルのファイルパスを取得
    registered_models = model_manager.get_models()
    registered_paths = {model.get('file_path') for model in registered_models}
    
    print(f"📊 登録済みモデル数: {len(registered_models)}")
    print(f"📝 登録対象ファイル数: {len(unregistered_files)}")
    print()
    
    # 各モデルファイルを登録
    registered_count = 0
    skipped_count = 0
    error_count = 0
    
    for filename in unregistered_files:
        file_path = os.path.join(model_dir, filename)
        
        if not os.path.exists(file_path):
            print(f"⚠️  ファイルが存在しません: {filename}")
            error_count += 1
            continue
        
        # 絶対パスに変換
        file_path = os.path.abspath(file_path)
        
        # 既に登録されている場合はスキップ
        if file_path in registered_paths:
            print(f"⏭️  スキップ: {filename} - 既に登録されています")
            skipped_count += 1
            continue
        
        # モデルを登録
        if register_model_file(file_path, model_manager):
            registered_count += 1
        else:
            skipped_count += 1
    
    print()
    print("=" * 60)
    print(f"✅ 登録完了: {registered_count}件")
    print(f"⏭️  スキップ: {skipped_count}件")
    print(f"❌ エラー: {error_count}件")
    print("=" * 60)


if __name__ == "__main__":
    main()

