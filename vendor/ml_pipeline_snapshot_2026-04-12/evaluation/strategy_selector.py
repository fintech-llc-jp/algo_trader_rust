"""
Strategy Selector
直近n時間のデータで最良の戦略を選択
"""
import psycopg2
from datetime import datetime, timedelta
from typing import Optional, Dict
from config.settings import DatabaseConfig


class StrategySelector:
    """
    最良の戦略を選択するクラス
    """
    
    def __init__(self, min_trades_for_evaluation: int = 10):
        """
        Args:
            min_trades_for_evaluation: 評価に必要な最小取引数（デフォルト10）
        """
        self.min_trades_for_evaluation = min_trades_for_evaluation
        self.db_config = DatabaseConfig()
    
    def select_best_strategy(
        self,
        evaluation_window_hours: int = 24,
        end_date: datetime = None
    ) -> Optional[Dict]:
        """
        最良の戦略を選択
        
        Args:
            evaluation_window_hours: 評価期間（時間、デフォルト24時間）
            end_date: 評価終了日時（Noneの場合は現在時刻）
        
        Returns:
            選択された戦略の情報、またはNone（評価結果がない場合）
        """
        if end_date is None:
            end_date = datetime.now()
        
        start_date = end_date - timedelta(hours=evaluation_window_hours)
        
        conn = psycopg2.connect(self.db_config.get_connection_string())
        try:
            with conn.cursor() as cur:
                # 最新の評価結果を取得
                cur.execute("""
                    SELECT DISTINCT ON (strategy_name)
                        strategy_name,
                        evaluation_start_time,
                        evaluation_end_time,
                        total_return,
                        sharpe_ratio,
                        max_drawdown,
                        win_rate,
                        profit_factor,
                        total_trades,
                        evaluation_score,
                        created_at
                    FROM strategy_performance
                    WHERE evaluation_start_time >= %s
                      AND evaluation_end_time <= %s
                      AND total_trades >= %s
                    ORDER BY strategy_name, created_at DESC
                """, (start_date, end_date, self.min_trades_for_evaluation))
                
                results = cur.fetchall()
                
                if not results:
                    return None
                
                # 最もスコアの高い戦略を選択
                best_strategy = max(results, key=lambda x: x[9])  # evaluation_scoreで比較
                
                return {
                    'strategy_name': best_strategy[0],
                    'evaluation_start': best_strategy[1],
                    'evaluation_end': best_strategy[2],
                    'total_return': float(best_strategy[3]),
                    'sharpe_ratio': float(best_strategy[4]),
                    'max_drawdown': float(best_strategy[5]),
                    'win_rate': float(best_strategy[6]),
                    'profit_factor': float(best_strategy[7]),
                    'total_trades': best_strategy[8],
                    'evaluation_score': float(best_strategy[9]),
                    'evaluated_at': best_strategy[10]
                }
        finally:
            conn.close()
    
    def get_all_strategy_scores(
        self,
        evaluation_window_hours: int = 24,
        end_date: datetime = None
    ) -> list:
        """
        すべての戦略のスコアを取得
        
        Args:
            evaluation_window_hours: 評価期間（時間）
            end_date: 評価終了日時
        
        Returns:
            すべての戦略のスコアのリスト
        """
        if end_date is None:
            end_date = datetime.now()
        
        start_date = end_date - timedelta(hours=evaluation_window_hours)
        
        conn = psycopg2.connect(self.db_config.get_connection_string())
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT ON (strategy_name)
                        strategy_name,
                        evaluation_score,
                        total_return,
                        sharpe_ratio,
                        total_trades
                    FROM strategy_performance
                    WHERE evaluation_start_time >= %s
                      AND evaluation_end_time <= %s
                      AND total_trades >= %s
                    ORDER BY strategy_name, created_at DESC
                """, (start_date, end_date, self.min_trades_for_evaluation))
                
                results = cur.fetchall()
                
                return [
                    {
                        'strategy_name': r[0],
                        'evaluation_score': float(r[1]),
                        'total_return': float(r[2]),
                        'sharpe_ratio': float(r[3]),
                        'total_trades': r[4]
                    }
                    for r in results
                ]
        finally:
            conn.close()

