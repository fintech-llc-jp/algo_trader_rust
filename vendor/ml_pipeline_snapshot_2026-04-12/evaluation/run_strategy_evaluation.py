"""
Strategy Evaluation Runner
定期的に各戦略を評価して、最良の戦略を選択
"""
import sys
import os
from datetime import datetime, timedelta
import schedule
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.strategy_evaluator import StrategyEvaluator
from evaluation.strategy_selector import StrategySelector
from config.settings import DatabaseConfig


def run_evaluation_and_selection(
    evaluation_window_hours: int = 24,
    symbol: str = "G_FX_BTCJPY",
    symbol2: str = "B_FX_BTCJPY"
):
    """
    各戦略を評価して、最良の戦略を選択
    
    Args:
        evaluation_window_hours: 評価期間（時間）
        symbol: 第1シンボル
        symbol2: 第2シンボル
    """
    print(f"\n{'='*70}")
    print(f"Strategy Evaluation and Selection")
    print(f"Time: {datetime.now()}")
    print(f"Evaluation Window: {evaluation_window_hours} hours")
    print(f"{'='*70}\n")
    
    # 評価実行
    evaluator = StrategyEvaluator(evaluation_window_hours=evaluation_window_hours)
    results = evaluator.evaluate_all_strategies(
        symbol=symbol,
        symbol2=symbol2,
        end_date=datetime.now()
    )
    
    # 結果を表示
    print("\nEvaluation Results:")
    print("-" * 70)
    for result in results:
        if result['status'] == 'success':
            print(f"\n{result['strategy_name']}:")
            print(f"  Total Return: {result.get('total_return', 0):.2f}%")
            print(f"  Sharpe Ratio: {result.get('sharpe_ratio', 0):.2f}")
            print(f"  Max Drawdown: {result.get('max_drawdown', 0):.2f}%")
            print(f"  Win Rate: {result.get('win_rate', 0):.2f}%")
            print(f"  Total Trades: {result.get('total_trades', 0)}")
        else:
            print(f"\n{result['strategy_name']}: ERROR - {result.get('error', 'Unknown error')}")
    
    # 結果をデータベースに保存
    evaluator.save_evaluation_results(results)
    
    # 最良の戦略を選択
    selector = StrategySelector()
    best_strategy = selector.select_best_strategy(
        evaluation_window_hours=evaluation_window_hours
    )
    
    if best_strategy:
        print(f"\n{'='*70}")
        print(f"Selected Best Strategy: {best_strategy['strategy_name']}")
        print(f"  Evaluation Score: {best_strategy['evaluation_score']:.4f}")
        print(f"  Total Return: {best_strategy['total_return']:.2f}%")
        print(f"  Sharpe Ratio: {best_strategy['sharpe_ratio']:.2f}")
        print(f"  Max Drawdown: {best_strategy['max_drawdown']:.2f}%")
        print(f"  Win Rate: {best_strategy['win_rate']:.2f}%")
        print(f"  Total Trades: {best_strategy['total_trades']}")
        print(f"{'='*70}\n")
        
        # 選択された戦略をファイルに保存（Trading Engineが読み込む）
        strategy_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'selected_strategy.txt'
        )
        with open(strategy_file, 'w') as f:
            f.write(best_strategy['strategy_name'])
        
        print(f"Selected strategy saved to: {strategy_file}")
    else:
        print("\nNo strategy selected (insufficient evaluation data)")
    
    print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Run strategy evaluation and selection')
    parser.add_argument('--evaluation-window-hours', type=int, default=24,
                       help='Evaluation window in hours (default: 24)')
    parser.add_argument('--interval-minutes', type=int, default=60,
                       help='Evaluation interval in minutes (default: 60)')
    parser.add_argument('--once', action='store_true',
                       help='Run once instead of scheduling')
    parser.add_argument('--symbol', type=str, default='G_FX_BTCJPY',
                       help='First symbol')
    parser.add_argument('--symbol2', type=str, default='B_FX_BTCJPY',
                       help='Second symbol')
    
    args = parser.parse_args()
    
    if args.once:
        # 一度だけ実行
        run_evaluation_and_selection(
            evaluation_window_hours=args.evaluation_window_hours,
            symbol=args.symbol,
            symbol2=args.symbol2
        )
    else:
        # 定期実行
        print(f"Scheduling strategy evaluation every {args.interval_minutes} minutes...")
        schedule.every(args.interval_minutes).minutes.do(
            run_evaluation_and_selection,
            evaluation_window_hours=args.evaluation_window_hours,
            symbol=args.symbol,
            symbol2=args.symbol2
        )
        
        # 初回実行
        run_evaluation_and_selection(
            evaluation_window_hours=args.evaluation_window_hours,
            symbol=args.symbol,
            symbol2=args.symbol2
        )
        
        # スケジューラー実行
        while True:
            schedule.run_pending()
            time.sleep(60)

