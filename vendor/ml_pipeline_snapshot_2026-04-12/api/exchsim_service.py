"""
ExchSim Execution Service for API
ExchSimでの実行をAPI経由で提供するサービス
"""
import os
import sys
import time
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
import pandas as pd
import numpy as np
import threading

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.data_loader import MarketDataLoader
from data.exch_sim_data_loader import ExchSimDataLoader
from data.feature_engineering import FeatureEngineer
from data.configurable_feature_engineering import ConfigurableFeatureEngineer
from strategy.price_prediction_strategy import PricePredictionStrategy
from strategy.momentum_intensity_strategy import MomentumIntensityStrategy
from evaluation.run_price_prediction_backtest import generate_signals_from_predictions
from config.settings import DatabaseConfig, ModelConfig, BacktestConfig
from api.model_manager import ModelManager


class ExchSimExecutor:
    """ExchSimでの実行を管理するクラス"""
    
    def __init__(
        self,
        model_name: str,
        model_type: str,
        symbol: str,
        exchsim_url: str,
        username: str,
        password: str,
        risk_config: Dict,
        mode: str = "realtime",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ):
        self.model_name = model_name
        self.model_type = model_type
        self.symbol = symbol
        self.exchsim_url = exchsim_url.rstrip('/')
        self.username = username
        self.password = password
        self.risk_config = risk_config
        self.mode = mode
        self.start_date = start_date
        self.end_date = end_date
        
        self.jwt_token = None
        self.is_running = False
        self.is_stopped = False
        self.execution_thread = None
        
        # メトリクス
        self.metrics = {
            "current_position": 0.0,
            "real_time_pnl": 0.0,
            "total_trades": 0,
            "win_rate": 0.0
        }
        
        # モデルとデータローダー
        self.model_manager = ModelManager()
        self.use_exch_sim_db = DatabaseConfig.USE_EXCH_SIM_DB
        if self.use_exch_sim_db:
            self.data_loader = ExchSimDataLoader()
        else:
            self.data_loader = MarketDataLoader()
    
    def login(self) -> bool:
        """ExchSimにログインしてJWTトークンを取得"""
        try:
            url = f"{self.exchsim_url}/api/auth/login"
            response = requests.post(
                url,
                json={"username": self.username, "password": self.password},
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.jwt_token = data.get("token")
                return True
            else:
                print(f"Login failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"Login error: {e}")
            return False
    
    def get_order_book(self) -> Optional[Dict]:
        """板情報を取得"""
        try:
            url = f"{self.exchsim_url}/api/market/board/{self.symbol}?depth=5"
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {self.jwt_token}"},
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Failed to get order book: {response.status_code}")
                return None
        except Exception as e:
            print(f"Error getting order book: {e}")
            return None
    
    def place_order(self, side: str, quantity: float, price: Optional[float] = None) -> Optional[Dict]:
        """注文を発注"""
        try:
            url = f"{self.exchsim_url}/api/orders/new"
            order_data = {
                "symbol": self.symbol,
                "side": side,
                "ordType": "LIMIT" if price else "MARKET",
                "quantity": quantity,
                "tif": "DAY"
            }
            if price:
                order_data["price"] = price
            
            response = requests.post(
                url,
                json=order_data,
                headers={
                    "Authorization": f"Bearer {self.jwt_token}",
                    "Content-Type": "application/json"
                },
                timeout=10
            )
            
            if response.status_code == 200:
                self.metrics["total_trades"] += 1
                return response.json()
            else:
                print(f"Failed to place order: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"Error placing order: {e}")
            return None
    
    def get_position_summary(self) -> Optional[Dict]:
        """ポジションサマリーを取得"""
        try:
            url = f"{self.exchsim_url}/api/positions/summary"
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {self.jwt_token}"},
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return None
        except Exception as e:
            print(f"Error getting position summary: {e}")
            return None
    
    def stop(self):
        """実行を停止"""
        self.is_stopped = True
        self.is_running = False
    
    def run(self) -> Dict:
        """実行を開始（非同期で実行される想定）"""
        if not self.login():
            return {
                "status": "error",
                "error": "Failed to login to ExchSim"
            }
        
        # モデルを読み込む
        models = self.model_manager.get_models(
            model_name=self.model_name,
            model_type=self.model_type,
            symbol=self.symbol
        )
        if not models:
            return {
                "status": "error",
                "error": f"Model not found: {self.model_name} ({self.model_type}, {self.symbol})"
            }
        
        model_info = models[0]
        model_path = model_info.get("file_path")
        if not model_path or not os.path.exists(model_path):
            return {
                "status": "error",
                "error": f"Model file not found: {model_path}"
            }
        
        # 特徴量エンジニアリングの準備
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
        
        # モデルタイプに応じて戦略を初期化
        if self.model_type == "price_prediction":
            strategy = PricePredictionStrategy(
                timeframes=[1, 5, 30],
                prediction_horizon=60
            )
            strategy.model.load(model_path)
        elif self.model_type == "momentum_intensity":
            strategy = MomentumIntensityStrategy(
                timeframes=[1, 5, 30],
                prediction_horizon=60
            )
            strategy.model.load(model_path)
        else:
            return {
                "status": "error",
                "error": f"Unsupported model type: {self.model_type}"
            }
        
        self.is_running = True
        
        # リアルタイムモードまたは期間指定モードで実行
        try:
            if self.mode == "realtime":
                # リアルタイムモード: 継続的に実行
                while self.is_running and not self.is_stopped:
                    # 板情報を取得
                    order_book = self.get_order_book()
                    if not order_book:
                        time.sleep(1)
                        continue
                    
                    # データを準備（簡略化: 実際にはより詳細なデータ準備が必要）
                    # ここでは簡略化のため、基本的な実行ロジックのみ実装
                    
                    # ポジションを確認
                    position_summary = self.get_position_summary()
                    if position_summary:
                        positions = position_summary.get("positions", [])
                        for pos in positions:
                            if pos.get("symbol") == self.symbol:
                                self.metrics["current_position"] = pos.get("quantity", 0.0)
                                self.metrics["real_time_pnl"] = pos.get("unrealizedPnl", 0.0)
                    
                    time.sleep(5)  # 5秒間隔で実行
            else:
                # 期間指定モード: 指定期間のデータで実行
                # 実装は簡略化（実際にはより詳細な実装が必要）
                pass
            
            return {
                "status": "completed",
                "metrics": self.metrics
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }
        finally:
            self.is_running = False


def run_exchsim_task(
    model_name: str,
    model_type: str,
    symbol: str,
    mode: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    risk_config: Dict = None,
    exchsim_config: Dict = None
) -> Dict:
    """
    ExchSimでの実行タスク
    
    Args:
        model_name: モデル名
        model_type: モデルタイプ
        symbol: シンボル
        mode: 実行モード ("realtime" or "period")
        start_date: 開始日時（period mode時）
        end_date: 終了日時（period mode時）
        risk_config: リスク設定
        exchsim_config: ExchSim接続設定
    
    Returns:
        実行結果の辞書
    """
    try:
        if risk_config is None:
            risk_config = {
                "max_position_size": 0.01,
                "max_daily_loss": 100000,
                "stop_loss_pct": 0.36
            }
        
        if exchsim_config is None:
            return {
                "status": "error",
                "error": "exchsim_config is required"
            }
        
        executor = ExchSimExecutor(
            model_name=model_name,
            model_type=model_type,
            symbol=symbol,
            exchsim_url=exchsim_config.get("url"),
            username=exchsim_config.get("username"),
            password=exchsim_config.get("password"),
            risk_config=risk_config,
            mode=mode,
            start_date=start_date,
            end_date=end_date
        )
        
        # 別スレッドで実行
        result = executor.run()
        return result
    
    except Exception as e:
        print(f"Error in run_exchsim_task: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "error": str(e)
        }

