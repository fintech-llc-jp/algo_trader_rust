"""
共通のロギング設定
"""
import os
import logging
from logging.handlers import RotatingFileHandler


def setup_logger(name: str, log_file: str = None) -> logging.Logger:
    """
    ロガーを設定
    
    Args:
        name: ロガー名
        log_file: ログファイルパス（Noneの場合はデフォルト）
    
    Returns:
        設定済みのロガー
    """
    # ログディレクトリの作成
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    # ログファイルパス（環境変数で指定可能）
    if log_file is None:
        log_file = os.getenv(f"{name.upper()}_LOG_FILE", os.path.join(log_dir, f"{name}.log"))
    
    # ロガーの設定
    logger = logging.getLogger(name)
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
    
    logger.info(f"{name} logging initialized. Log file: {log_file}")
    
    return logger

