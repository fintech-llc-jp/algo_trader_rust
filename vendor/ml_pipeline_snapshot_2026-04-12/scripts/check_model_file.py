"""
モデルファイルの内容を確認するスクリプト
"""
import sys
import os
import joblib

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def check_model_file(filepath: str):
    """
    モデルファイルの内容を確認
    
    Args:
        filepath: モデルファイルのパス
    """
    if not os.path.exists(filepath):
        print(f"❌ モデルファイルが存在しません: {filepath}")
        return
    
    print(f"📁 モデルファイル: {filepath}")
    print(f"📊 ファイルサイズ: {os.path.getsize(filepath) / 1024:.2f} KB")
    print()
    
    try:
        data = joblib.load(filepath)
        print(f"✅ ファイルの読み込みに成功しました")
        print(f"📦 データタイプ: {type(data)}")
        print()
        
        if isinstance(data, dict):
            print("🔑 含まれるキー:")
            for key in data.keys():
                value = data[key]
                value_type = type(value).__name__
                
                if key == 'model':
                    if value is None:
                        print(f"  ❌ {key}: None (⚠️ モデルがNoneです)")
                    else:
                        print(f"  ✅ {key}: {value_type} (モデルオブジェクト)")
                        if hasattr(value, '__class__'):
                            print(f"     クラス: {value.__class__.__name__}")
                elif key == 'scaler':
                    if value is None:
                        print(f"  ⚠️  {key}: None")
                    else:
                        print(f"  ✅ {key}: {value_type} (スケーラーオブジェクト)")
                elif key == 'feature_columns':
                    if isinstance(value, list):
                        print(f"  ✅ {key}: list (特徴量数: {len(value)})")
                        if len(value) > 0:
                            print(f"     最初の5つ: {value[:5]}")
                    else:
                        print(f"  ⚠️  {key}: {value_type} (期待される型: list)")
                else:
                    print(f"  ℹ️  {key}: {value_type}")
            
            print()
            
            # 必須キーの確認
            required_keys = ['model', 'scaler', 'feature_columns']
            missing_keys = [key for key in required_keys if key not in data]
            if missing_keys:
                print(f"❌ 必須キーが不足しています: {missing_keys}")
            else:
                print("✅ 必須キーはすべて存在します")
            
            # モデルの検証
            if 'model' in data:
                if data['model'] is None:
                    print("❌ モデルがNoneです。モデルが正しく保存されていない可能性があります。")
                else:
                    print("✅ モデルオブジェクトが存在します")
            
            # 特徴量カラムの確認
            if 'feature_columns' in data:
                feature_cols = data['feature_columns']
                if isinstance(feature_cols, list):
                    print(f"✅ 特徴量カラム数: {len(feature_cols)}")
                    if len(feature_cols) == 0:
                        print("⚠️  特徴量カラムが空です")
                else:
                    print(f"⚠️  特徴量カラムの型が不正です: {type(feature_cols)}")
            
        else:
            print(f"⚠️  データが辞書型ではありません: {type(data)}")
            print("   モデルファイルのフォーマットが正しくない可能性があります")
    
    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python check_model_file.py <モデルファイルのパス>")
        print()
        print("例:")
        print("  python check_model_file.py models/saved/my_model_price_G_FX_BTCJPY_20251220_155838.joblib")
        sys.exit(1)
    
    filepath = sys.argv[1]
    check_model_file(filepath)

