"""
Model Manager for Database-Based Model Management
モデルの保存、読み込み、一覧取得、削除、メタデータ管理を担当（DBベース）
"""
import os
import json
import tempfile
import psycopg2
from psycopg2 import errors as psycopg2_errors
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

from config.settings import DatabaseConfig, ModelConfig
from models.price_prediction_model import PricePredictionModel
from models.momentum_intensity_model import MomentumIntensityModel
from models.direction_classification_model import DirectionClassificationModel
from models.volatility_prediction_model import VolatilityPredictionModel
from models.volume_prediction_model import VolumePredictionModel
# LightGBMは遅延インポート（libomp依存関係の問題を回避）
# from models.lightgbm_price_prediction_model import LightGBMPricePredictionModel
from models.order_book_only_model import OrderBookOnlyModel


class ModelManager:
    """モデル管理クラス（DBベース）"""
    
    def __init__(self, connection_string: Optional[str] = None, use_file_backend: bool = False):
        """
        初期化
        
        Args:
            connection_string: データベース接続文字列（Noneの場合はDatabaseConfigから取得）
            use_file_backend: Trueの場合はファイルベースの後方互換モード（デフォルト: False）
        """
        self.use_file_backend = use_file_backend
        
        if use_file_backend:
            # 後方互換モード: ファイルベース
            self.model_dir = ModelConfig.MODEL_DIR
            os.makedirs(self.model_dir, exist_ok=True)
            self.metadata_file = os.path.join(self.model_dir, 'metadata.json')
            self._load_metadata()
            self.conn = None
        else:
            # DBベースモード
            if connection_string is None:
                # algo_traderデータベースを使用（ml_modelsテーブルはalgo_traderに保存）
                # algo_trader専用の接続設定を使用（exch_simとは別の接続設定を使用可能）
                connection_string = DatabaseConfig.get_algo_trader_connection_string()
            
            try:
                self.conn = psycopg2.connect(connection_string)
                self.conn.autocommit = False  # トランザクション管理
                # 接続成功を確認
                print(f"Successfully connected to database: {connection_string.split('@')[1] if '@' in connection_string else 'unknown'}")
            except Exception as e:
                print(f"Warning: Failed to connect to database: {e}")
                print(f"Connection string: {connection_string.split('@')[0] if '@' in connection_string else connection_string}@...")
                import traceback
                print(traceback.format_exc())
                print("Falling back to file-based backend")
                self.use_file_backend = True
                self.model_dir = ModelConfig.MODEL_DIR
                os.makedirs(self.model_dir, exist_ok=True)
                self.metadata_file = os.path.join(self.model_dir, 'metadata.json')
                self._load_metadata()
                self.conn = None
    
    def _load_metadata(self) -> Dict:
        """メタデータを読み込む（ファイルベースのみ）"""
        if not self.use_file_backend:
            return {}
        
        if os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    self.metadata = json.load(f)
            except Exception as e:
                print(f"Warning: Failed to load metadata: {e}")
                self.metadata = {"models": []}
        else:
            self.metadata = {"models": []}
        return self.metadata
    
    def _save_metadata(self):
        """メタデータを保存（ファイルベースのみ）"""
        if not self.use_file_backend:
            return
        
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving metadata: {e}")
            raise
    
    def register_model(
        self,
        model_name: str,
        model_type: str,
        symbol: str,
        file_path: str,
        training_window_days: int,
        metrics: Dict,
        is_active: bool = False,
        training_start_time: Optional[datetime] = None,
        training_end_time: Optional[datetime] = None,
        training_data_stats: Optional[Dict] = None
    ):
        """
        モデルをDBまたはファイルに登録
        
        Args:
            model_name: モデル名
            model_type: モデルタイプ
            symbol: 銘柄
            file_path: モデルファイルのパス
            training_window_days: 訓練期間（日数）
            metrics: 評価指標の辞書
            is_active: アクティブかどうか
            training_start_time: 訓練データの開始時刻（オプション）
            training_end_time: 訓練データの終了時刻（オプション）
            training_data_stats: 訓練データの統計情報（オプション）
                {
                    "market_data_count": int,
                    "execution_data_count": int,
                    "data_quality_score": float
                }
        """
        if self.use_file_backend:
            # ファイルベース（後方互換）
            model_entry = {
                "model_name": model_name,
                "model_type": model_type,
                "symbol": symbol,
                "file_path": file_path,
                "trained_at": datetime.now().isoformat(),
                "training_window_days": training_window_days,
                "metrics": metrics,
                "is_active": is_active
            }
            if training_data_stats:
                model_entry["training_data_stats"] = training_data_stats
            self.metadata["models"].append(model_entry)
            self._save_metadata()
        else:
            # DBベース
            if not self.conn:
                raise RuntimeError("Database connection not available")
            
            # ファイルを読み込んでBLOBに変換
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Model file not found: {file_path}")
            
            with open(file_path, 'rb') as f:
                model_blob = f.read()
            
            # DBに保存
            try:
                with self.conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO ml_models 
                        (model_name, model_type, symbol, model_data, 
                         training_window_days, training_start_time, training_end_time,
                         metrics, trained_at, is_active, training_data_stats)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        model_name, model_type, symbol, psycopg2.Binary(model_blob),
                        training_window_days, training_start_time, training_end_time,
                        json.dumps(metrics), datetime.now(), is_active,
                        json.dumps(training_data_stats) if training_data_stats else None
                    ))
                    self.conn.commit()
            except Exception as e:
                self.conn.rollback()
                raise
    
    def get_models(
        self,
        model_name: Optional[str] = None,
        model_type: Optional[str] = None,
        symbol: Optional[str] = None
    ) -> List[Dict]:
        """
        モデル一覧を取得
        
        Args:
            model_name: モデル名でフィルタ（Noneの場合はすべて）
            model_type: モデルタイプでフィルタ（Noneの場合はすべて）
            symbol: 銘柄でフィルタ（Noneの場合はすべて）
        
        Returns:
            モデル情報のリスト
        """
        if self.use_file_backend:
            # ファイルベース（後方互換）
            models = self.metadata.get("models", [])
            
            # フィルタリング
            if model_name:
                models = [m for m in models if m.get("model_name") == model_name]
            if model_type:
                models = [m for m in models if m.get("model_type") == model_type]
            if symbol:
                models = [m for m in models if m.get("symbol") == symbol]
            
            # 重複排除: 同じmodel_name, model_type, symbolの組み合わせで最新のもののみを保持
            # trained_atでソート（存在する場合）
            models_with_trained_at = [m for m in models if m.get("trained_at")]
            models_without_trained_at = [m for m in models if not m.get("trained_at")]
            
            # trained_atでソート（降順）
            from datetime import datetime
            models_with_trained_at.sort(
                key=lambda x: datetime.fromisoformat(x["trained_at"].replace('Z', '+00:00')) if isinstance(x.get("trained_at"), str) else datetime.min,
                reverse=True
            )
            
            # 重複排除
            seen_keys = set()
            unique_models = []
            for model in models_with_trained_at + models_without_trained_at:
                key = (model.get("model_name"), model.get("model_type"), model.get("symbol"))
                if key not in seen_keys:
                    seen_keys.add(key)
                    unique_models.append(model)
            
            return unique_models
        else:
            # DBベース
            if not self.conn:
                print(f"Warning: ModelManager.get_models: Connection is None (use_file_backend={self.use_file_backend})")
                return []
            
            # 接続が閉じられている場合は再接続を試みる
            if self.conn.closed:
                print(f"Warning: ModelManager.get_models: Connection is closed, attempting to reconnect...")
                try:
                    connection_string = DatabaseConfig.get_algo_trader_connection_string()
                    self.conn = psycopg2.connect(connection_string)
                    self.conn.autocommit = False
                    print(f"Successfully reconnected to database")
                except Exception as e:
                    print(f"Error reconnecting to database: {e}")
                return []
            
            try:
                with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                    conditions = []
                    params = []
                    
                    if model_name:
                        conditions.append("model_name = %s")
                        params.append(model_name)
                    if model_type:
                        conditions.append("model_type = %s")
                        params.append(model_type)
                    if symbol:
                        conditions.append("symbol = %s")
                        params.append(symbol)
                    
                    where_clause = " AND ".join(conditions) if conditions else "1=1"
                    
                    cur.execute(f"""
                        SELECT 
                            id,
                            model_name,
                            model_type,
                            symbol,
                            training_window_days,
                            training_start_time,
                            training_end_time,
                            metrics,
                            trained_at,
                            is_active,
                            created_at,
                            updated_at,
                            training_data_stats
                        FROM ml_models
                        WHERE {where_clause}
                        ORDER BY trained_at DESC NULLS LAST
                    """, params)
                    
                    rows = cur.fetchall()
                    models = []
                    seen_keys = set()  # 重複排除用（model_name, model_type, symbolの組み合わせ）
                    
                    for row in rows:
                        model_dict = dict(row)
                        # JSONBフィールドをPython辞書に変換
                        if isinstance(model_dict.get('metrics'), str):
                            model_dict['metrics'] = json.loads(model_dict['metrics'])
                        if isinstance(model_dict.get('training_data_stats'), str):
                            model_dict['training_data_stats'] = json.loads(model_dict['training_data_stats'])
                        
                        # 重複排除: 同じmodel_name, model_type, symbolの組み合わせで最新のもののみを保持
                        # (trained_atでソート済みなので、最初に見つかったものが最新)
                        key = (model_dict.get('model_name'), model_dict.get('model_type'), model_dict.get('symbol'))
                        if key not in seen_keys:
                            seen_keys.add(key)
                            models.append(model_dict)
                    
                    return models
            except psycopg2_errors.UndefinedTable as e:
                # テーブルが存在しない場合は空のリストを返す（後方互換性のため）
                print(f"Warning: ml_models table does not exist: {e}")
                return []
            except Exception as e:
                # その他のエラーもログに記録して空のリストを返す
                print(f"Error getting models from database: {e}")
                import traceback
                traceback.print_exc()
                return []
    
    def get_active_model(
        self,
        model_type: str,
        symbol: str
    ) -> Optional[Dict]:
        """
        アクティブなモデルを取得
        
        Args:
            model_type: モデルタイプ
            symbol: 銘柄
        
        Returns:
            アクティブなモデルの情報（見つからない場合はNone）
        """
        models = self.get_models(model_type=model_type, symbol=symbol)
        active_models = [m for m in models if m.get("is_active", False)]
        
        if active_models:
            # 最新のアクティブモデルを返す
            return sorted(active_models, key=lambda x: x.get("trained_at", ""), reverse=True)[0]
        return None
    
    def activate_model(
        self,
        model_name: str,
        model_type: str,
        symbol: str
    ) -> bool:
        """
        モデルをアクティブにする
        
        Args:
            model_name: モデル名
            model_type: モデルタイプ
            symbol: 銘柄
        
        Returns:
            成功した場合はTrue、失敗した場合はFalse
        """
        if self.use_file_backend:
            # ファイルベース（後方互換）
            models = self.get_models(model_name=model_name, model_type=model_type, symbol=symbol)
            
            if not models:
                return False
            
            # 同じタイプとシンボルの他のモデルを非アクティブにする
            all_models = self.get_models(model_type=model_type, symbol=symbol)
            for model in all_models:
                model["is_active"] = False
            
            # 指定されたモデルをアクティブにする
            target_model = models[0]
            target_model["is_active"] = True
            
            self._save_metadata()
            return True
        else:
            # DBベース
            if not self.conn:
                return False
            
            try:
                with self.conn.cursor() as cur:
                    # トランザクション開始
                    # 1. 同じタイプ・シンボルの他モデルを非アクティブ化
                    cur.execute("""
                        UPDATE ml_models 
                        SET is_active = FALSE, updated_at = NOW()
                        WHERE model_type = %s AND symbol = %s AND is_active = TRUE
                    """, (model_type, symbol))
                    
                    # 2. 指定モデルをアクティブ化
                    cur.execute("""
                        UPDATE ml_models 
                        SET is_active = TRUE, updated_at = NOW()
                        WHERE model_name = %s AND model_type = %s AND symbol = %s
                    """, (model_name, model_type, symbol))
                    
                    if cur.rowcount == 0:
                        # 診断: 該当レコードが存在するか確認
                        cur.execute("""
                            SELECT model_name, model_type, symbol, is_active
                            FROM ml_models
                            WHERE model_name = %s AND symbol = %s
                            LIMIT 10
                        """, (model_name, symbol))
                        existing = cur.fetchall()
                        if existing:
                            print(
                                f"Activate failed: no row for model_type={model_type!r}. "
                                f"Existing rows for {model_name}/{symbol}: "
                                f"{[(r[1], r[3]) for r in existing]}"
                            )
                        else:
                            print(
                                f"Activate failed: no row for model_name={model_name!r}, symbol={symbol!r}"
                            )
                        return False
                    
                    self.conn.commit()
                    return True
            except Exception as e:
                self.conn.rollback()
                print(f"Error activating model: {e}")
                return False
    
    def delete_model(
        self,
        model_name: str,
        model_type: Optional[str] = None,
        symbol: Optional[str] = None
    ) -> bool:
        """
        モデルを削除
        
        Args:
            model_name: モデル名
            model_type: モデルタイプ（Noneの場合はすべてのタイプ）
            symbol: 銘柄（Noneの場合はすべての銘柄）
        
        Returns:
            成功した場合はTrue、失敗した場合はFalse
        """
        if self.use_file_backend:
            # ファイルベース（後方互換）
            models_to_delete = self.get_models(model_name=model_name, model_type=model_type, symbol=symbol)
            
            if not models_to_delete:
                return False
            
            # アクティブなモデルは削除できない
            active_models = [m for m in models_to_delete if m.get("is_active", False)]
            if active_models:
                raise ValueError("Cannot delete active model. Please deactivate it first.")
            
            # モデルファイルを削除
            for model in models_to_delete:
                file_path = model.get("file_path")
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        print(f"Deleted model file: {file_path}")
                    except Exception as e:
                        print(f"Warning: Failed to delete model file {file_path}: {e}")
            
            # メタデータから削除
            self.metadata["models"] = [
                m for m in self.metadata["models"]
                if not (
                    m.get("model_name") == model_name and
                    (model_type is None or m.get("model_type") == model_type) and
                    (symbol is None or m.get("symbol") == symbol)
                )
            ]
            
            self._save_metadata()
            return True
        else:
            # DBベース
            if not self.conn:
                return False
            
            try:
                with self.conn.cursor() as cur:
                    # アクティブなモデルは削除できない
                    conditions = ["model_name = %s"]
                    params = [model_name]
                    
                    if model_type:
                        conditions.append("model_type = %s")
                        params.append(model_type)
                    if symbol:
                        conditions.append("symbol = %s")
                        params.append(symbol)
                    
                    where_clause = " AND ".join(conditions)
                    
                    cur.execute(f"""
                        SELECT is_active FROM ml_models
                        WHERE {where_clause}
                    """, params)
                    
                    rows = cur.fetchall()
                    if not rows:
                        return False
                    
                    active_models = [r[0] for r in rows if r[0]]
                    if active_models:
                        raise ValueError("Cannot delete active model. Please deactivate it first.")
                    
                    # 削除
                    cur.execute(f"""
                        DELETE FROM ml_models
                        WHERE {where_clause}
                    """, params)
                    
                    self.conn.commit()
                    return cur.rowcount > 0
            except Exception as e:
                self.conn.rollback()
                print(f"Error deleting model: {e}")
                raise
    
    def load_model(
        self,
        model_name: str,
        model_type: str,
        symbol: str
    ):
        """
        モデルを読み込む
        
        Args:
            model_name: モデル名
            model_type: モデルタイプ
            symbol: 銘柄
        
        Returns:
            ロードされたモデルインスタンス
        """
        if self.use_file_backend:
            # ファイルベース（後方互換）
            models = self.get_models(model_name=model_name, model_type=model_type, symbol=symbol)
            
            if not models:
                raise FileNotFoundError(
                    f"Model not found: {model_name} ({model_type}, {symbol})"
                )
            
            # 最新のモデルを取得
            latest_model = sorted(models, key=lambda x: x.get("trained_at", ""), reverse=True)[0]
            file_path = latest_model.get("file_path")
            
            if not file_path or not os.path.exists(file_path):
                raise FileNotFoundError(f"Model file not found: {file_path}")
            
            # モデルを読み込む
            return self._load_model_from_file(file_path, model_type)
        else:
            # DBベース
            if not self.conn:
                raise RuntimeError("Database connection not available")
            
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT model_data FROM ml_models
                    WHERE model_name = %s AND model_type = %s AND symbol = %s
                    ORDER BY trained_at DESC
                    LIMIT 1
                """, (model_name, model_type, symbol))
                
                result = cur.fetchone()
                if not result:
                    raise FileNotFoundError(
                        f"Model not found: {model_name} ({model_type}, {symbol})"
                    )
                
                # BLOBを一時ファイルに保存してロード
                with tempfile.NamedTemporaryFile(delete=False, suffix='.joblib') as tmp:
                    tmp.write(result[0])
                    tmp_path = tmp.name

                # 一時ファイルからモデルをロード
                loaded_model = self._load_model_from_file(tmp_path, model_type)

                # モデルロード成功後に一時ファイルを削除
                try:
                    os.unlink(tmp_path)
                except Exception as e:
                    logger.warning(f"Failed to delete temp file {tmp_path}: {e}")

                return loaded_model
    
    def _load_model_from_file(self, file_path: str, model_type: str):
        """ファイルからモデルを読み込む（共通処理）"""
        if model_type == "price_prediction":
            return PricePredictionModel.load(file_path)
        elif model_type == "momentum_intensity":
            return MomentumIntensityModel.load(file_path)
        elif model_type == "direction_classification":
            return DirectionClassificationModel.load(file_path)
        elif model_type == "volatility_prediction":
            return VolatilityPredictionModel.load(file_path)
        elif model_type == "volume_prediction":
            return VolumePredictionModel.load(file_path)
        elif model_type == "lightgbm_price_prediction":
            # LightGBMは遅延インポート（libomp依存関係の問題を回避）
            try:
                from models.lightgbm_price_prediction_model import LightGBMPricePredictionModel
                return LightGBMPricePredictionModel.load(file_path)
            except ImportError as e:
                raise ImportError(f"Failed to import LightGBM: {e}. Please install libomp: brew install libomp")
            except Exception as e:
                # libompが見つからない場合のエラー
                if "libomp" in str(e).lower() or "Library not loaded" in str(e):
                    raise ImportError(
                        f"LightGBM requires libomp library. "
                        f"Please install it: brew install libomp\n"
                        f"Then create a symlink: sudo mkdir -p /usr/local/opt/libomp/lib && "
                        f"sudo ln -sf /opt/homebrew/opt/libomp/lib/libomp.dylib /usr/local/opt/libomp/lib/libomp.dylib"
                    )
                raise
        elif model_type == "order_book_only":
            return OrderBookOnlyModel.load(file_path)
        else:
            raise ValueError(f"Unknown model type: {model_type}")

    def activate_model(self, model_name: str, model_type: str, symbol: str) -> bool:
        """
        指定されたモデルをアクティブ化し、同じ(model_type, symbol)の他のモデルを非アクティブ化

        Args:
            model_name: モデル名
            model_type: モデルタイプ
            symbol: シンボル

        Returns:
            bool: 成功した場合True
        """
        if self.use_file_backend or not self.conn:
            raise RuntimeError("Database connection not available")

        try:
            with self.conn.cursor() as cur:
                # 同じmodel_type + symbolの他のモデルを非アクティブ化
                cur.execute("""
                    UPDATE ml_models
                    SET is_active = FALSE
                    WHERE model_type = %s AND symbol = %s AND is_active = TRUE
                """, (model_type, symbol))

                # 指定されたモデルをアクティブ化（複数行ある場合は最新trained_atの1行のみ）
                cur.execute("""
                    UPDATE ml_models
                    SET is_active = TRUE, updated_at = NOW()
                    WHERE id = (
                        SELECT id FROM ml_models
                        WHERE model_name = %s AND model_type = %s AND symbol = %s
                        ORDER BY trained_at DESC NULLS LAST
                        LIMIT 1
                    )
                """, (model_name, model_type, symbol))

                self.conn.commit()
                affected_rows = cur.rowcount
                print(f"Model activated: {model_name} ({model_type}, {symbol}), affected rows: {affected_rows}")
                return affected_rows > 0
        except Exception as e:
            self.conn.rollback()
            print(f"Error activating model: {e}")
            return False

    def get_model_file_path(
        self,
        model_type: str,
        symbol: str,
        export_path: Optional[str] = None
    ) -> str:
        """
        アクティブモデルを一時ファイルにエクスポート（後方互換性のため）
        
        Args:
            model_type: モデルタイプ
            symbol: 銘柄
            export_path: エクスポート先のパス（Noneの場合は一時ファイル）
        
        Returns:
            エクスポートされたファイルのパス
        """
        active_model = self.get_active_model(model_type, symbol)
        if not active_model:
            raise FileNotFoundError(f"Active model not found: {model_type}, {symbol}")
        
        if self.use_file_backend:
            # ファイルベースの場合、既存のファイルパスを返す
            file_path = active_model.get("file_path")
            if file_path and os.path.exists(file_path):
                return file_path
            raise FileNotFoundError(f"Model file not found: {file_path}")
        else:
            # DBベースの場合、BLOBを一時ファイルにエクスポート
            if not self.conn:
                raise RuntimeError("Database connection not available")
            
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT model_data FROM ml_models
                    WHERE model_type = %s AND symbol = %s AND is_active = TRUE
                    ORDER BY trained_at DESC
                    LIMIT 1
                """, (model_type, symbol))
                
                result = cur.fetchone()
                if not result:
                    raise FileNotFoundError(f"Active model not found: {model_type}, {symbol}")
                
                if export_path is None:
                    # デフォルトパス（後方互換性のため）
                    model_dir = ModelConfig.MODEL_DIR
                    os.makedirs(model_dir, exist_ok=True)
                    export_path = os.path.join(model_dir, f"{model_type}_{symbol}.joblib")
                
                # BLOBをファイルに保存
                with open(export_path, 'wb') as f:
                    f.write(result[0])
                
                return export_path
    
    def close(self):
        """データベース接続を閉じる"""
        if self.conn:
            self.conn.close()
            self.conn = None
