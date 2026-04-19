#!/usr/bin/env python3
"""
ModelManagerの動作確認スクリプト
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.model_manager import ModelManager
from config.settings import DatabaseConfig

def test_model_manager():
    print("=" * 60)
    print("ModelManager Test")
    print("=" * 60)
    
    # 接続文字列を取得
    conn_str = DatabaseConfig.get_algo_trader_connection_string()
    print(f"\n1. Connection String: {conn_str.split('@')[0]}@...")
    
    # ModelManagerを初期化
    try:
        mm = ModelManager(connection_string=conn_str, use_file_backend=False)
        print(f"2. ModelManager initialized: use_file_backend={mm.use_file_backend}")
        print(f"3. Connection status: {mm.conn is not None}")
        
        if not mm.conn:
            print("ERROR: Connection is None!")
            return
        
        # モデル一覧取得
        print("\n4. Getting all models...")
        models = mm.get_models()
        print(f"   Total models: {len(models)}")
        
        if len(models) > 0:
            print(f"\n5. Sample model:")
            sample = models[0]
            for key, value in sample.items():
                if key != 'model_data':  # BLOBは表示しない
                    print(f"   {key}: {value}")
        
        # LightGBMモデルの確認
        print("\n6. Getting LightGBM models...")
        lightgbm_models = mm.get_models(model_type='lightgbm_price_prediction')
        print(f"   LightGBM models: {len(lightgbm_models)}")
        
        if len(lightgbm_models) > 0:
            print(f"\n7. Sample LightGBM model:")
            sample = lightgbm_models[0]
            for key, value in sample.items():
                if key != 'model_data':  # BLOBは表示しない
                    print(f"   {key}: {value}")
        else:
            print("   WARNING: No LightGBM models found!")
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_model_manager()
