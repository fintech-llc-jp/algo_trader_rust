"""
ML Pipeline Configuration
"""
import os
from datetime import datetime

# .envファイルを読み込む（存在する場合）
try:
    from dotenv import load_dotenv
    # プロジェクトルートの.envファイルを読み込む
    # このファイルは ml_pipeline/config/settings.py なので、2階層上がプロジェクトルート
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenvがインストールされていない場合はスキップ

class TrainingConfig:
    """ML訓練の設定"""
    
    # 訓練期間
    TRAINING_WINDOW_DAYS = int(os.getenv('TRAINING_WINDOW_DAYS', '3'))  # 3日間のスライディングウィンドウ
    VALIDATION_SPLIT = 0.2  # 最後の20%を検証用
    RETRAIN_FREQUENCY_HOURS = 24  # 24時間ごとに再訓練（既存設定）
    
    # データ品質要件
    MIN_SAMPLES = int(os.getenv('MIN_SAMPLES', '1000'))  # 最低1,000サンプル（テスト用に下げる）
    MIN_DATA_QUALITY_SCORE = 70  # データ品質スコア閾値
    
    # モデルアクティベーション基準
    MIN_VALIDATION_ACCURACY = 0.55
    MIN_BACKTEST_SHARPE = 0.5
    MAX_BACKTEST_DRAWDOWN = -0.15
    
    # アラート
    ALERT_ON_TRAINING_FAILURE = True
    ALERT_ON_POOR_PERFORMANCE = True
    
    # 定期再訓練の設定（既存のRETRAIN_FREQUENCY_HOURSを活用）
    RETRAIN_ENABLED = os.getenv('RETRAIN_ENABLED', 'true').lower() == 'true'
    RETRAIN_INTERVAL_HOURS = int(os.getenv('RETRAIN_INTERVAL_HOURS', str(RETRAIN_FREQUENCY_HOURS)))  # 既存設定をデフォルトに
    RETRAIN_TRAINING_WINDOW_DAYS = int(os.getenv('RETRAIN_TRAINING_WINDOW_DAYS', str(TRAINING_WINDOW_DAYS)))  # 既存設定をデフォルトに


class DatabaseConfig:
    """データベース設定"""
    
    # exch_simデータベース設定（データ読み込み用）
    HOST = os.getenv('DB_HOST', 'localhost')
    PORT = int(os.getenv('DB_PORT', '5432'))
    USER = os.getenv('DB_USER', 'postgres')
    PASSWORD = os.getenv('DB_PASSWORD', '')
    EXCH_SIM_DB_NAME = os.getenv('EXCH_SIM_DB_NAME', 'exch_sim')
    
    # algo_traderデータベース設定（モデル保存用、個別に設定可能）
    # 注意: ALGO_TRADER_DB_*が設定されていない場合、DB_*の値が使われる
    # しかし、DB_*はexch_sim用の設定である可能性があるため、明示的に設定することを推奨
    # デフォルト値はalgo_traderデータベース用（ローカルPostgreSQL）
    ALGO_TRADER_DB_HOST = os.getenv('ALGO_TRADER_DB_HOST', 'localhost')
    ALGO_TRADER_DB_PORT = int(os.getenv('ALGO_TRADER_DB_PORT', '5432'))
    # DB_USERがexch_sim用の設定（exch_sim_user）である可能性があるため、デフォルトは'postgres'を使用
    # 環境変数ALGO_TRADER_DB_USERが設定されていない場合のみ、DB_USERをフォールバックとして使用
    ALGO_TRADER_DB_USER = os.getenv('ALGO_TRADER_DB_USER') or os.getenv('DB_USER', 'postgres')
    # DB_PASSWORDがexch_sim用の設定である可能性があるため、明示的に設定することを推奨
    # 環境変数ALGO_TRADER_DB_PASSWORDが設定されていない場合のみ、DB_PASSWORDをフォールバックとして使用
    # 両方とも設定されていない場合は空文字列（接続エラーになるが、明示的な設定を促す）
    ALGO_TRADER_DB_PASSWORD = os.getenv('ALGO_TRADER_DB_PASSWORD') or os.getenv('DB_PASSWORD', '')
    NAME = os.getenv('ALGO_TRADER_DB_NAME', os.getenv('DB_NAME', 'algo_trader'))
    
    # デフォルトでexch_simデータベースを使用（データがexch_simにあるため）
    # 環境変数が設定されている場合はそれを使用、なければ'true'をデフォルトとする
    use_exch_sim_db_env = os.getenv('USE_EXCH_SIM_DB')
    if use_exch_sim_db_env is not None:
        USE_EXCH_SIM_DB = use_exch_sim_db_env.lower() == 'true'
    else:
        USE_EXCH_SIM_DB = True  # デフォルトでexch_simを使用
    
    @classmethod
    def get_connection_string(cls, db_name=None):
        """exch_simデータベースへの接続文字列を取得（デフォルト）"""
        if db_name is None:
            db_name = cls.EXCH_SIM_DB_NAME if cls.USE_EXCH_SIM_DB else cls.NAME
        return f"postgresql://{cls.USER}:{cls.PASSWORD}@{cls.HOST}:{cls.PORT}/{db_name}"
    
    @classmethod
    def get_exch_sim_connection_string(cls):
        """exch_simデータベースへの接続文字列を取得"""
        return f"postgresql://{cls.USER}:{cls.PASSWORD}@{cls.HOST}:{cls.PORT}/{cls.EXCH_SIM_DB_NAME}"
    
    @classmethod
    def get_algo_trader_connection_string(cls):
        """algo_traderデータベースへの接続文字列を取得（モデル保存用）"""
        return f"postgresql://{cls.ALGO_TRADER_DB_USER}:{cls.ALGO_TRADER_DB_PASSWORD}@{cls.ALGO_TRADER_DB_HOST}:{cls.ALGO_TRADER_DB_PORT}/{cls.NAME}"
    
    # 接続プール設定
    POOL_MIN_CONNECTIONS = int(os.getenv('DB_POOL_MIN_CONNECTIONS', '2'))
    POOL_MAX_CONNECTIONS = int(os.getenv('DB_POOL_MAX_CONNECTIONS', '10'))
    POOL_CONNECTION_TIMEOUT = int(os.getenv('DB_POOL_CONNECTION_TIMEOUT', '30'))


class ModelConfig:
    """モデル設定"""
    
    # モデル保存ディレクトリ
    MODEL_DIR = os.getenv('MODEL_DIR', os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
        'models', 'saved'
    ))
    
    # XGBoost
    XGBOOST_PARAMS = {
        'n_estimators': 200,
        'max_depth': 6,
        'learning_rate': 0.1,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'objective': 'multi:softmax',
        'num_class': 3,
        'random_state': 42,
        'eval_metric': 'mlogloss'
    }
    
    # 特徴量生成
    LABEL_HORIZON = 5  # 5秒後の価格で予測
    LABEL_THRESHOLD = 0.0001  # 0.01%の閾値（テスト用に下げる）


class BacktestConfig:
    """バックテスト設定"""
    
    INITIAL_CAPITAL = 1_000_000  # 初期資金100万円
    COMMISSION_RATE = 0.0  # 手数料0%（デフォルト）
    SLIPPAGE_BPS = 1.0  # スリッページ1bp
    CONFIDENCE_THRESHOLD = 0.7  # 取引実行の最小信頼度


class PredictionTrackerConfig:
    """Prediction Tracker設定"""
    
    # 有効/無効
    ENABLED = os.getenv('PREDICTION_TRACKER_ENABLED', 'true').lower() == 'true'
    
    # 実行間隔（秒）
    CYCLE_INTERVAL_SECONDS = int(os.getenv('PREDICTION_TRACKER_CYCLE_INTERVAL', '60'))
    
    # モデル再訓練間隔（時間）
    RETRAIN_INTERVAL_HOURS = int(os.getenv('PREDICTION_TRACKER_RETRAIN_INTERVAL_HOURS', '24'))
    
    # 訓練データ期間（時間）
    TRAINING_WINDOW_HOURS = int(os.getenv('PREDICTION_TRACKER_TRAINING_WINDOW_HOURS', '5'))
    
    # 合成データフォールバック（開発/テスト用のみ）
    USE_SYNTHETIC_DATA = os.getenv('PREDICTION_TRACKER_USE_SYNTHETIC_DATA', 'false').lower() == 'true'
    
    # 最小データ要件
    MIN_SAMPLES_FOR_TRAINING = int(os.getenv('PREDICTION_TRACKER_MIN_SAMPLES', '100'))
    MIN_SAMPLES_FOR_PREDICTION = int(os.getenv('PREDICTION_TRACKER_MIN_SAMPLES_PRED', '10'))
