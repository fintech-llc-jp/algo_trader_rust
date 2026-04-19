"""
Migrate Models from File-Based to Database-Based Storage
既存のmetadata.jsonとモデルファイルをDBに移行するスクリプト
"""
import os
import sys
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.model_manager import ModelManager
from config.settings import DatabaseConfig, ModelConfig


def migrate_models_to_db(backup_metadata: bool = True):
    """
    既存のmetadata.jsonとモデルファイルをDBに移行
    
    Args:
        backup_metadata: Trueの場合はmetadata.jsonをバックアップ（デフォルト: True）
    """
    print("=" * 60)
    print("ML Models Migration: File-Based to Database-Based")
    print("=" * 60)
    print()
    
    # ModelManagerをDBベースで初期化
    try:
        connection_string = DatabaseConfig.get_connection_string(db_name=DatabaseConfig.NAME)
        db_model_manager = ModelManager(connection_string=connection_string, use_file_backend=False)
        print("✅ Database connection established")
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        print("Migration aborted.")
        return False
    
    # ファイルベースのModelManagerで既存データを読み込む
    file_model_manager = ModelManager(use_file_backend=True)
    existing_models = file_model_manager.get_models()
    
    if not existing_models:
        print("ℹ️  No existing models found in metadata.json")
        return True
    
    print(f"📊 Found {len(existing_models)} models in metadata.json")
    print()
    
    # DBに既に存在するモデルを確認
    db_models = db_model_manager.get_models()
    db_model_keys = {(m['model_name'], m['model_type'], m['symbol']) for m in db_models}
    
    migrated_count = 0
    skipped_count = 0
    error_count = 0
    
    for model in existing_models:
        model_name = model.get('model_name')
        model_type = model.get('model_type')
        symbol = model.get('symbol')
        file_path = model.get('file_path')
        training_window_days = model.get('training_window_days', 1)
        metrics = model.get('metrics', {})
        is_active = model.get('is_active', False)
        trained_at_str = model.get('trained_at')
        
        model_key = (model_name, model_type, symbol)
        
        # 既にDBに存在する場合はスキップ
        if model_key in db_model_keys:
            print(f"⏭️  Skipping {model_name} ({model_type}, {symbol}) - already exists in DB")
            skipped_count += 1
            continue
        
        # ファイルパスの確認
        if not file_path or not os.path.exists(file_path):
            print(f"⚠️  Skipping {model_name} ({model_type}, {symbol}) - file not found: {file_path}")
            skipped_count += 1
            continue
        
        # trained_atからtraining_start_time/end_timeを推定
        training_start_time = None
        training_end_time = None
        if trained_at_str:
            try:
                trained_at = datetime.fromisoformat(trained_at_str.replace('Z', '+00:00'))
                # trained_atを終了時刻として、training_window_daysから開始時刻を推定
                training_end_time = trained_at
                training_start_time = trained_at - timedelta(days=training_window_days)
            except:
                # パースに失敗した場合はNULLのまま
                pass
        
        try:
            # DBに登録
            db_model_manager.register_model(
                model_name=model_name,
                model_type=model_type,
                symbol=symbol,
                file_path=file_path,
                training_window_days=training_window_days,
                metrics=metrics,
                is_active=is_active,
                training_start_time=training_start_time,
                training_end_time=training_end_time
            )
            
            print(f"✅ Migrated: {model_name} ({model_type}, {symbol})")
            if is_active:
                print(f"   → Active model")
            migrated_count += 1
        except Exception as e:
            print(f"❌ Failed to migrate {model_name} ({model_type}, {symbol}): {e}")
            error_count += 1
    
    print()
    print("=" * 60)
    print(f"Migration Summary:")
    print(f"  ✅ Migrated: {migrated_count}")
    print(f"  ⏭️  Skipped: {skipped_count}")
    print(f"  ❌ Errors: {error_count}")
    print("=" * 60)
    
    # metadata.jsonをバックアップ
    if backup_metadata and migrated_count > 0:
        metadata_file = file_model_manager.metadata_file
        if os.path.exists(metadata_file):
            backup_file = f"{metadata_file}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy(metadata_file, backup_file)
            print(f"\n📦 Backed up metadata.json to: {backup_file}")
    
    # データベース接続を閉じる
    db_model_manager.close()
    
    return error_count == 0


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Migrate models from file-based to database-based storage")
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not backup metadata.json"
    )
    
    args = parser.parse_args()
    
    success = migrate_models_to_db(backup_metadata=not args.no_backup)
    
    if success:
        print("\n✅ Migration completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ Migration completed with errors. Please check the output above.")
        sys.exit(1)

