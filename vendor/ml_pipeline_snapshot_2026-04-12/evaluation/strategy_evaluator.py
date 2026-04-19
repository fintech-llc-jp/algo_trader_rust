"""
Strategy Performance Evaluator
各戦略のバックテストを実行してパフォーマンスを評価
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import psycopg2
from config.settings import DatabaseConfig

from data.data_loader import MarketDataLoader
from data.arbitrage_data_loader import ArbitrageDataLoader
from data.feature_engineering import FeatureEngineer
from strategy.order_flow_imbalance_strategy import OrderFlowImbalanceStrategy
from strategy.mean_reversion_strategy import MeanReversionStrategy
from evaluation.run_backtest import run_backtest_with_model
from evaluation.run_arbitrage_backtest import run_arbitrage_backtest
from evaluation.run_spot_arbitrage_backtest import run_spot_arbitrage_backtest
from evaluation.run_limit_order_mean_reversion_backtest import run_limit_order_mean_reversion_backtest


class StrategyEvaluator:
    """
    各戦略のパフォーマンスを評価するクラス
    """
    
    def __init__(self, evaluation_window_hours: int = 24):
        """
        Args:
            evaluation_window_hours: 評価期間（時間、デフォルト24時間）
        """
        self.evaluation_window_hours = evaluation_window_hours
        self.db_config = DatabaseConfig()
    
    def evaluate_all_strategies(
        self,
        symbol: str = "G_FX_BTCJPY",
        symbol2: str = "B_FX_BTCJPY",
        end_date: datetime = None
    ) -> List[Dict]:
        """
        すべての戦略を評価
        
        Args:
            symbol: 第1シンボル
            symbol2: 第2シンボル（アービトラージ戦略用）
            end_date: 評価終了日時（Noneの場合は現在時刻）
        
        Returns:
            各戦略の評価結果のリスト
        """
        if end_date is None:
            end_date = datetime.now()
        
        start_date = end_date - timedelta(hours=self.evaluation_window_hours)
        
        results = []
        
        # 1. モメンタム戦略
        try:
            result = self._evaluate_momentum_strategy(symbol, start_date, end_date)
            result['strategy_name'] = 'momentum_ml'
            results.append(result)
        except Exception as e:
            print(f"Error evaluating momentum strategy: {e}")
            results.append({
                'strategy_name': 'momentum_ml',
                'status': 'error',
                'error': str(e)
            })
        
        # 2. アービトラージ戦略
        try:
            result = self._evaluate_arbitrage_strategy(symbol, symbol2, start_date, end_date)
            result['strategy_name'] = 'arbitrage_ml'
            results.append(result)
        except Exception as e:
            print(f"Error evaluating arbitrage strategy: {e}")
            results.append({
                'strategy_name': 'arbitrage_ml',
                'status': 'error',
                'error': str(e)
            })
        
        # 3. Order Flow Imbalance戦略
        try:
            result = self._evaluate_order_flow_imbalance_strategy(symbol, start_date, end_date)
            result['strategy_name'] = 'order_flow_imbalance'
            results.append(result)
        except Exception as e:
            print(f"Error evaluating order flow imbalance strategy: {e}")
            results.append({
                'strategy_name': 'order_flow_imbalance',
                'status': 'error',
                'error': str(e)
            })
        
        # 4. Mean Reversion戦略
        try:
            result = self._evaluate_mean_reversion_strategy(symbol, start_date, end_date)
            result['strategy_name'] = 'mean_reversion'
            results.append(result)
        except Exception as e:
            print(f"Error evaluating mean reversion strategy: {e}")
            results.append({
                'strategy_name': 'mean_reversion',
                'status': 'error',
                'error': str(e)
            })
        
        # 5. Multi-Timeframe戦略（モメンタム戦略の拡張として評価）
        try:
            result = self._evaluate_multi_timeframe_strategy(symbol, start_date, end_date)
            result['strategy_name'] = 'multi_timeframe'
            results.append(result)
        except Exception as e:
            print(f"Error evaluating multi-timeframe strategy: {e}")
            results.append({
                'strategy_name': 'multi_timeframe',
                'status': 'error',
                'error': str(e)
            })
        
        # 6. Spot Arbitrage戦略（FXと現物のアービトラージ）
        try:
            result = self._evaluate_spot_arbitrage_strategy(symbol, symbol2, start_date, end_date)
            result['strategy_name'] = 'spot_arbitrage'
            results.append(result)
        except Exception as e:
            print(f"Error evaluating spot arbitrage strategy: {e}")
            results.append({
                'strategy_name': 'spot_arbitrage',
                'status': 'error',
                'error': str(e)
            })
        
        # 7. Limit Order Mean Reversion戦略（指値注文を活用した平均回帰）
        try:
            result = self._evaluate_limit_order_mean_reversion_strategy(symbol, start_date, end_date)
            result['strategy_name'] = 'limit_order_mean_reversion'
            results.append(result)
        except Exception as e:
            print(f"Error evaluating limit order mean reversion strategy: {e}")
            results.append({
                'strategy_name': 'limit_order_mean_reversion',
                'status': 'error',
                'error': str(e)
            })
        
        return results
    
    def _evaluate_momentum_strategy(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict:
        """モメンタム戦略を評価"""
        result = run_backtest_with_model(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date
        )
        
        if result['status'] == 'success':
            metrics = result['metrics']
            return {
                'status': 'success',
                'evaluation_start': start_date,
                'evaluation_end': end_date,
                'total_return': metrics.get('total_return', 0.0),
                'sharpe_ratio': metrics.get('sharpe_ratio', 0.0),
                'max_drawdown': metrics.get('max_drawdown', 0.0),
                'win_rate': metrics.get('win_rate', 0.0),
                'profit_factor': metrics.get('profit_factor', 0.0),
                'total_trades': metrics.get('total_trades', 0)
            }
        else:
            return {
                'status': 'error',
                'error': result.get('error', 'Unknown error')
            }
    
    def _evaluate_arbitrage_strategy(
        self,
        symbol1: str,
        symbol2: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict:
        """アービトラージ戦略を評価"""
        result = run_arbitrage_backtest(
            symbol1=symbol1,
            symbol2=symbol2,
            start_date=start_date,
            end_date=end_date
        )
        
        if result['status'] == 'success':
            metrics = result['metrics']
            return {
                'status': 'success',
                'evaluation_start': start_date,
                'evaluation_end': end_date,
                'total_return': metrics.get('total_return', 0.0),
                'sharpe_ratio': metrics.get('sharpe_ratio', 0.0),
                'max_drawdown': metrics.get('max_drawdown', 0.0),
                'win_rate': metrics.get('win_rate', 0.0),
                'profit_factor': metrics.get('profit_factor', 0.0),
                'total_trades': metrics.get('total_trades', 0)
            }
        else:
            return {
                'status': 'error',
                'error': result.get('error', 'Unknown error')
            }
    
    def _evaluate_order_flow_imbalance_strategy(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict:
        """Order Flow Imbalance戦略を評価"""
        loader = MarketDataLoader()
        feature_engineer = FeatureEngineer()
        strategy = OrderFlowImbalanceStrategy()
        
        try:
            # データロード
            df = loader.load_training_data(symbol, start_date, end_date)
            
            # 特徴量エンジニアリング
            df = feature_engineer.engineer_features(df)
            
            # 訓練/テスト分割
            split_idx = int(len(df) * 0.8)
            train_df = df.iloc[:split_idx].copy()
            test_df = df.iloc[split_idx:].copy()
            
            # 訓練
            strategy.train(train_df)
            
            # 予測
            signals, confidence = strategy.predict(test_df)
            
            # バックテスト
            metrics = strategy.backtest(test_df, signals, confidence)
            
            return {
                'status': 'success',
                'evaluation_start': start_date,
                'evaluation_end': end_date,
                'total_return': metrics.get('total_return', 0.0),
                'sharpe_ratio': metrics.get('sharpe_ratio', 0.0),
                'max_drawdown': metrics.get('max_drawdown', 0.0),
                'win_rate': metrics.get('win_rate', 0.0),
                'profit_factor': metrics.get('profit_factor', 0.0),
                'total_trades': metrics.get('total_trades', 0)
            }
        finally:
            loader.close()
    
    def _evaluate_mean_reversion_strategy(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict:
        """Mean Reversion戦略を評価"""
        loader = MarketDataLoader()
        feature_engineer = FeatureEngineer()
        strategy = MeanReversionStrategy()
        
        try:
            # データロード
            df = loader.load_training_data(symbol, start_date, end_date)
            
            # 特徴量エンジニアリング
            df = feature_engineer.engineer_features(df)
            
            # 訓練/テスト分割
            split_idx = int(len(df) * 0.8)
            train_df = df.iloc[:split_idx].copy()
            test_df = df.iloc[split_idx:].copy()
            
            # 訓練
            strategy.train(train_df)
            
            # 予測
            signals, confidence = strategy.predict(test_df)
            
            # バックテスト
            metrics = strategy.backtest(test_df, signals, confidence)
            
            return {
                'status': 'success',
                'evaluation_start': start_date,
                'evaluation_end': end_date,
                'total_return': metrics.get('total_return', 0.0),
                'sharpe_ratio': metrics.get('sharpe_ratio', 0.0),
                'max_drawdown': metrics.get('max_drawdown', 0.0),
                'win_rate': metrics.get('win_rate', 0.0),
                'profit_factor': metrics.get('profit_factor', 0.0),
                'total_trades': metrics.get('total_trades', 0)
            }
        finally:
            loader.close()
    
    def _evaluate_multi_timeframe_strategy(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict:
        """Multi-Timeframe戦略を評価（モメンタム戦略の拡張として評価）"""
        # 現在はモメンタム戦略と同じ評価を使用
        # 将来的にマルチタイムフレームの特徴量を追加
        return self._evaluate_momentum_strategy(symbol, start_date, end_date)
    
    def _evaluate_spot_arbitrage_strategy(
        self,
        fx_symbol: str,
        spot_symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict:
        """Spot Arbitrage戦略を評価"""
        result = run_spot_arbitrage_backtest(
            fx_symbol=fx_symbol,
            spot_symbol=spot_symbol,
            start_date=start_date,
            end_date=end_date
        )
        
        if result['status'] == 'success':
            metrics = result['metrics']
            return {
                'status': 'success',
                'evaluation_start': start_date,
                'evaluation_end': end_date,
                'total_return': metrics.get('total_return', 0.0),
                'sharpe_ratio': metrics.get('sharpe_ratio', 0.0),
                'max_drawdown': metrics.get('max_drawdown', 0.0),
                'win_rate': metrics.get('win_rate', 0.0),
                'profit_factor': metrics.get('profit_factor', 0.0),
                'total_trades': metrics.get('total_trades', 0)
            }
        else:
            return {
                'status': 'error',
                'error': result.get('error', 'Unknown error')
            }
    
    def _evaluate_limit_order_mean_reversion_strategy(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict:
        """Limit Order Mean Reversion戦略を評価"""
        result = run_limit_order_mean_reversion_backtest(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date
        )
        
        if result['status'] == 'success':
            metrics = result['metrics']
            return {
                'status': 'success',
                'evaluation_start': start_date,
                'evaluation_end': end_date,
                'total_return': metrics.get('total_return', 0.0),
                'sharpe_ratio': metrics.get('sharpe_ratio', 0.0),
                'max_drawdown': metrics.get('max_drawdown', 0.0),
                'win_rate': metrics.get('win_rate', 0.0),
                'profit_factor': metrics.get('profit_factor', 0.0),
                'total_trades': metrics.get('total_trades', 0)
            }
        else:
            return {
                'status': 'error',
                'error': result.get('error', 'Unknown error')
            }
    
    def save_evaluation_results(self, results: List[Dict]):
        """
        評価結果をデータベースに保存
        
        Args:
            results: 評価結果のリスト
        """
        conn = psycopg2.connect(self.db_config.get_connection_string())
        try:
            with conn.cursor() as cur:
                for result in results:
                    if result['status'] == 'success':
                        # 総合スコアを計算
                        evaluation_score = self._calculate_evaluation_score(result)
                        
                        cur.execute("""
                            INSERT INTO strategy_performance (
                                strategy_name, evaluation_start_time, evaluation_end_time,
                                total_return, sharpe_ratio, max_drawdown,
                                win_rate, profit_factor, total_trades, evaluation_score
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                            )
                        """, (
                            result['strategy_name'],
                            result['evaluation_start'],
                            result['evaluation_end'],
                            result['total_return'],
                            result['sharpe_ratio'],
                            result['max_drawdown'],
                            result['win_rate'],
                            result['profit_factor'],
                            result['total_trades'],
                            evaluation_score
                        ))
            conn.commit()
        finally:
            conn.close()
    
    def _calculate_evaluation_score(self, result: Dict) -> float:
        """
        総合スコアを計算
        
        Args:
            result: 評価結果の辞書
        
        Returns:
            総合スコア
        """
        # 重み付け
        w_sharpe = 0.3
        w_return = 0.3
        w_drawdown = 0.2
        w_win_rate = 0.1
        w_profit_factor = 0.1
        
        # 正規化（簡易版）
        sharpe_score = max(0, result.get('sharpe_ratio', 0)) / 2.0  # 0-2の範囲を0-1に正規化
        return_score = max(0, result.get('total_return', 0)) / 100.0  # 0-100%の範囲を0-1に正規化
        drawdown_score = max(0, -result.get('max_drawdown', 0)) / 50.0  # 0-50%の範囲を0-1に正規化
        win_rate_score = result.get('win_rate', 0) / 100.0  # 0-100%の範囲を0-1に正規化
        profit_factor_score = min(1.0, result.get('profit_factor', 0) / 2.0)  # 0-2の範囲を0-1に正規化
        
        score = (
            w_sharpe * sharpe_score +
            w_return * return_score +
            w_drawdown * drawdown_score +
            w_win_rate * win_rate_score +
            w_profit_factor * profit_factor_score
        )
        
        return score

