#!/usr/bin/env python3
"""
ExchSim データ品質評価ツール

exch_simデータベースのデータ品質を包括的に評価します。
"""
import os
import sys
import argparse
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple
import pandas as pd
import numpy as np
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.exch_sim_data_loader import ExchSimDataLoader
from config.settings import DatabaseConfig


class DataQualityEvaluator:
    """データ品質評価クラス"""
    
    def __init__(self, loader: ExchSimDataLoader):
        self.loader = loader
        self.results = {}
    
    def evaluate(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        expected_interval_seconds: int = 1
    ) -> Dict:
        """
        データ品質を包括的に評価
        
        Args:
            symbol: 銘柄名
            start_date: 開始日時
            end_date: 終了日時
            expected_interval_seconds: 期待される記録間隔（秒）
        
        Returns:
            評価結果の辞書
        """
        print(f"\n{'='*60}")
        print(f"データ品質評価: {symbol}")
        print(f"期間: {start_date} ～ {end_date}")
        print(f"{'='*60}\n")
        
        # データをロード
        print("データをロード中...")
        try:
            df = self.loader.load_market_data(symbol, start_date, end_date)
        except Exception as e:
            print(f"エラー: データのロードに失敗しました: {e}")
            return {}
        
        if len(df) == 0:
            print("警告: データが存在しません")
            return {}
        
        print(f"ロード完了: {len(df)} レコード\n")
        
        # 評価項目を実行
        results = {
            'symbol': symbol,
            'start_date': start_date,
            'end_date': end_date,
            'total_records': len(df),
            'evaluations': {}
        }
        
        # 1. データの完全性
        results['evaluations']['completeness'] = self._evaluate_completeness(
            df, start_date, end_date, expected_interval_seconds
        )
        
        # 2. データの正確性
        results['evaluations']['accuracy'] = self._evaluate_accuracy(df)
        
        # 3. データの一貫性
        results['evaluations']['consistency'] = self._evaluate_consistency(df)
        
        # 4. データの頻度
        results['evaluations']['frequency'] = self._evaluate_frequency(
            df, expected_interval_seconds
        )
        
        # 5. データの範囲
        results['evaluations']['range'] = self._evaluate_range(df)
        
        # 6. 統計サマリー
        results['evaluations']['statistics'] = self._calculate_statistics(df)
        
        # 総合スコアを計算
        results['overall_score'] = self._calculate_overall_score(results['evaluations'])
        
        self.results = results
        return results
    
    def _evaluate_completeness(
        self,
        df: pd.DataFrame,
        start_date: datetime,
        end_date: datetime,
        expected_interval_seconds: int
    ) -> Dict:
        """データの完全性を評価"""
        print("1. データの完全性を評価中...")
        
        # 期待されるレコード数
        expected_duration = (end_date - start_date).total_seconds()
        expected_records = int(expected_duration / expected_interval_seconds)
        actual_records = len(df)
        completeness_ratio = actual_records / expected_records if expected_records > 0 else 0
        
        # 欠損値のチェック
        missing_values = df.isnull().sum()
        missing_ratio = missing_values / len(df)
        
        # 必須カラムのチェック
        required_columns = ['bid_price_1', 'ask_price_1', 'bid_qty_1', 'ask_qty_1']
        missing_required = {}
        for col in required_columns:
            if col in df.columns:
                missing_required[col] = int(df[col].isnull().sum())
            else:
                missing_required[col] = len(df)  # カラムが存在しない
        
        result = {
            'expected_records': expected_records,
            'actual_records': actual_records,
            'completeness_ratio': float(completeness_ratio),
            'missing_values': missing_values.to_dict(),
            'missing_ratio': missing_ratio.to_dict(),
            'missing_required_columns': missing_required,
            'score': float(min(100, completeness_ratio * 100))
        }
        
        print(f"  期待レコード数: {expected_records:,}")
        print(f"  実際のレコード数: {actual_records:,}")
        print(f"  完全性比率: {completeness_ratio:.2%}")
        print(f"  スコア: {result['score']:.1f}/100")
        
        return result
    
    def _evaluate_accuracy(self, df: pd.DataFrame) -> Dict:
        """データの正確性を評価"""
        print("\n2. データの正確性を評価中...")
        
        issues = []
        score = 100
        
        # 価格の妥当性
        if 'bid_price_1' in df.columns:
            invalid_bid = (df['bid_price_1'] <= 0).sum()
            if invalid_bid > 0:
                issues.append(f"無効なBID価格: {invalid_bid}件")
                score -= min(20, invalid_bid / len(df) * 100)
        
        if 'ask_price_1' in df.columns:
            invalid_ask = (df['ask_price_1'] <= 0).sum()
            if invalid_ask > 0:
                issues.append(f"無効なASK価格: {invalid_ask}件")
                score -= min(20, invalid_ask / len(df) * 100)
        
        # スプレッドの妥当性
        if 'spread' in df.columns:
            negative_spread = (df['spread'] < 0).sum()
            zero_spread = (df['spread'] == 0).sum()
            if negative_spread > 0:
                issues.append(f"負のスプレッド: {negative_spread}件")
                score -= min(30, negative_spread / len(df) * 100)
            if zero_spread > 0:
                issues.append(f"ゼロスプレッド: {zero_spread}件")
                score -= min(10, zero_spread / len(df) * 100)
        
        # 板の順序チェック（BID < ASK）
        if 'bid_price_1' in df.columns and 'ask_price_1' in df.columns:
            crossed_market = (df['bid_price_1'] >= df['ask_price_1']).sum()
            if crossed_market > 0:
                issues.append(f"クロス市場（BID >= ASK）: {crossed_market}件")
                score -= min(40, crossed_market / len(df) * 100)
        
        # 数量の妥当性
        if 'bid_qty_1' in df.columns:
            invalid_bid_qty = (df['bid_qty_1'] < 0).sum()
            if invalid_bid_qty > 0:
                issues.append(f"負のBID数量: {invalid_bid_qty}件")
                score -= min(10, invalid_bid_qty / len(df) * 100)
        
        if 'ask_qty_1' in df.columns:
            invalid_ask_qty = (df['ask_qty_1'] < 0).sum()
            if invalid_ask_qty > 0:
                issues.append(f"負のASK数量: {invalid_ask_qty}件")
                score -= min(10, invalid_ask_qty / len(df) * 100)
        
        result = {
            'issues': issues,
            'issue_count': len(issues),
            'score': float(max(0, score))
        }
        
        if issues:
            print(f"  問題: {len(issues)}件")
            for issue in issues:
                print(f"    - {issue}")
        else:
            print("  問題なし")
        print(f"  スコア: {result['score']:.1f}/100")
        
        return result
    
    def _evaluate_consistency(self, df: pd.DataFrame) -> Dict:
        """データの一貫性を評価"""
        print("\n3. データの一貫性を評価中...")
        
        issues = []
        score = 100
        
        # スプレッド比率の異常値
        if 'spread' in df.columns and 'mid_price' in df.columns:
            spread_ratio = df['spread'] / (df['mid_price'] + 1e-9)
            # スプレッド比率が1%を超える場合は異常
            abnormal_spread = (spread_ratio > 0.01).sum()
            if abnormal_spread > 0:
                issues.append(f"異常なスプレッド比率（>1%）: {abnormal_spread}件")
                score -= min(20, abnormal_spread / len(df) * 100)
        
        # オーダーインバランスの極端な値
        if 'order_imbalance' in df.columns:
            extreme_imbalance = (df['order_imbalance'].abs() > 0.9).sum()
            if extreme_imbalance > 0:
                issues.append(f"極端なオーダーインバランス（|imbalance|>0.9）: {extreme_imbalance}件")
                score -= min(10, extreme_imbalance / len(df) * 100)
        
        # 価格変動の異常値
        if 'mid_price' in df.columns:
            price_change = df['mid_price'].pct_change().abs()
            # 1秒で10%以上の価格変動は異常
            abnormal_change = (price_change > 0.10).sum()
            if abnormal_change > 0:
                issues.append(f"異常な価格変動（>10%）: {abnormal_change}件")
                score -= min(20, abnormal_change / len(df) * 100)
        
        # 板の厚みの一貫性
        if 'bid_depth_5' in df.columns and 'ask_depth_5' in df.columns:
            total_depth = df['bid_depth_5'] + df['ask_depth_5']
            # 板の厚みがゼロの場合は問題
            zero_depth = (total_depth == 0).sum()
            if zero_depth > 0:
                issues.append(f"板の厚みがゼロ: {zero_depth}件")
                score -= min(15, zero_depth / len(df) * 100)
        
        result = {
            'issues': issues,
            'issue_count': len(issues),
            'score': float(max(0, score))
        }
        
        if issues:
            print(f"  問題: {len(issues)}件")
            for issue in issues:
                print(f"    - {issue}")
        else:
            print("  問題なし")
        print(f"  スコア: {result['score']:.1f}/100")
        
        return result
    
    def _evaluate_frequency(
        self,
        df: pd.DataFrame,
        expected_interval_seconds: int
    ) -> Dict:
        """データの頻度を評価"""
        print("\n4. データの頻度を評価中...")
        
        if len(df) < 2:
            return {
                'average_interval': None,
                'expected_interval': expected_interval_seconds,
                'gaps': [],
                'score': 0
            }
        
        # タイムスタンプの間隔を計算
        timestamps = df.index
        intervals = timestamps.to_series().diff().dt.total_seconds()
        intervals = intervals[intervals > 0]  # ゼロを除外
        
        if len(intervals) == 0:
            return {
                'average_interval': None,
                'expected_interval': expected_interval_seconds,
                'gaps': [],
                'score': 0
            }
        
        avg_interval = intervals.mean()
        median_interval = intervals.median()
        
        # 期待される間隔との差
        interval_diff = abs(avg_interval - expected_interval_seconds)
        interval_diff_ratio = interval_diff / expected_interval_seconds
        
        # 大きなギャップを検出（期待される間隔の2倍以上）
        large_gaps = intervals[intervals > expected_interval_seconds * 2]
        gap_count = len(large_gaps)
        
        # スコア計算
        score = 100
        if interval_diff_ratio > 0.1:  # 10%以上の差
            score -= min(30, interval_diff_ratio * 100)
        if gap_count > 0:
            score -= min(30, gap_count / len(intervals) * 100)
        
        result = {
            'average_interval': float(avg_interval),
            'median_interval': float(median_interval),
            'expected_interval': expected_interval_seconds,
            'interval_diff': float(interval_diff),
            'interval_diff_ratio': float(interval_diff_ratio),
            'large_gaps': large_gaps.tolist() if len(large_gaps) > 0 else [],
            'gap_count': gap_count,
            'score': float(max(0, score))
        }
        
        print(f"  平均間隔: {avg_interval:.2f}秒")
        print(f"  中央値間隔: {median_interval:.2f}秒")
        print(f"  期待間隔: {expected_interval_seconds}秒")
        print(f"  大きなギャップ: {gap_count}件")
        print(f"  スコア: {result['score']:.1f}/100")
        
        return result
    
    def _evaluate_range(self, df: pd.DataFrame) -> Dict:
        """データの範囲を評価"""
        print("\n5. データの範囲を評価中...")
        
        ranges = {}
        score = 100
        
        # 各カラムの範囲を計算
        numeric_columns = df.select_dtypes(include=[np.number]).columns
        
        for col in numeric_columns:
            if col in ['bid_price_1', 'ask_price_1', 'mid_price', 'spread']:
                ranges[col] = {
                    'min': float(df[col].min()),
                    'max': float(df[col].max()),
                    'mean': float(df[col].mean()),
                    'std': float(df[col].std())
                }
        
        # 異常値の検出（3シグマルール）
        issues = []
        for col in ['bid_price_1', 'ask_price_1', 'mid_price']:
            if col in df.columns:
                mean = df[col].mean()
                std = df[col].std()
                outliers = ((df[col] < mean - 3 * std) | (df[col] > mean + 3 * std)).sum()
                if outliers > 0:
                    issues.append(f"{col}の異常値: {outliers}件")
                    score -= min(10, outliers / len(df) * 100)
        
        result = {
            'ranges': ranges,
            'outlier_issues': issues,
            'score': float(max(0, score))
        }
        
        print(f"  評価カラム数: {len(ranges)}")
        if issues:
            print(f"  異常値: {len(issues)}件")
            for issue in issues:
                print(f"    - {issue}")
        print(f"  スコア: {result['score']:.1f}/100")
        
        return result
    
    def _calculate_statistics(self, df: pd.DataFrame) -> Dict:
        """統計サマリーを計算"""
        print("\n6. 統計サマリーを計算中...")
        
        stats = {}
        
        # 基本統計
        if 'spread' in df.columns:
            stats['spread'] = {
                'mean': float(df['spread'].mean()),
                'median': float(df['spread'].median()),
                'std': float(df['spread'].std()),
                'min': float(df['spread'].min()),
                'max': float(df['spread'].max())
            }
        
        if 'mid_price' in df.columns:
            stats['mid_price'] = {
                'mean': float(df['mid_price'].mean()),
                'median': float(df['mid_price'].median()),
                'std': float(df['mid_price'].std()),
                'min': float(df['mid_price'].min()),
                'max': float(df['mid_price'].max())
            }
        
        if 'order_imbalance' in df.columns:
            stats['order_imbalance'] = {
                'mean': float(df['order_imbalance'].mean()),
                'median': float(df['order_imbalance'].median()),
                'std': float(df['order_imbalance'].std()),
                'min': float(df['order_imbalance'].min()),
                'max': float(df['order_imbalance'].max())
            }
        
        print("  計算完了")
        
        return stats
    
    def _calculate_overall_score(self, evaluations: Dict) -> float:
        """総合スコアを計算"""
        scores = []
        weights = {
            'completeness': 0.25,
            'accuracy': 0.30,
            'consistency': 0.20,
            'frequency': 0.15,
            'range': 0.10
        }
        
        for key, weight in weights.items():
            if key in evaluations and 'score' in evaluations[key]:
                scores.append(evaluations[key]['score'] * weight)
        
        overall_score = sum(scores) if scores else 0
        return float(overall_score)
    
    def print_summary(self):
        """評価結果のサマリーを表示"""
        if not self.results:
            print("評価結果がありません")
            return
        
        print(f"\n{'='*60}")
        print("評価結果サマリー")
        print(f"{'='*60}\n")
        
        print(f"銘柄: {self.results['symbol']}")
        print(f"期間: {self.results['start_date']} ～ {self.results['end_date']}")
        print(f"総レコード数: {self.results['total_records']:,}")
        print(f"\n総合スコア: {self.results['overall_score']:.1f}/100\n")
        
        print("各評価項目のスコア:")
        for key, eval_result in self.results['evaluations'].items():
            if 'score' in eval_result:
                print(f"  {key}: {eval_result['score']:.1f}/100")
    
    def save_report(self, output_path: str):
        """評価レポートを保存"""
        if not self.results:
            print("評価結果がありません")
            return
        
        import json
        
        # JSON形式で保存
        report = {
            'evaluation_date': datetime.now().isoformat(),
            'results': self.results
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        
        print(f"\nレポートを保存しました: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='ExchSim データ品質評価ツール',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # 過去1時間のデータを評価
  python evaluate_data_quality.py G_FX_BTCJPY --hours 1
  
  # 指定期間のデータを評価
  python evaluate_data_quality.py G_FX_BTCJPY --start "2024-01-01 00:00:00" --end "2024-01-01 23:59:59"
  
  # レポートを保存
  python evaluate_data_quality.py G_FX_BTCJPY --hours 24 --output report.json
        """
    )
    
    parser.add_argument(
        'symbol',
        help='評価する銘柄（例: G_FX_BTCJPY）'
    )
    
    parser.add_argument(
        '--start',
        type=str,
        help='開始日時（YYYY-MM-DD HH:MM:SS形式、UTC）'
    )
    
    parser.add_argument(
        '--end',
        type=str,
        help='終了日時（YYYY-MM-DD HH:MM:SS形式、UTC）'
    )
    
    parser.add_argument(
        '--hours',
        type=int,
        help='過去N時間のデータを評価'
    )
    
    parser.add_argument(
        '--days',
        type=int,
        help='過去N日間のデータを評価'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        help='レポートの保存先（JSON形式）'
    )
    
    parser.add_argument(
        '--interval',
        type=int,
        default=1,
        help='期待される記録間隔（秒、デフォルト: 1）'
    )
    
    args = parser.parse_args()
    
    # 日時の設定（UTCとして扱う）
    # datetime.utcnow()は非推奨のため、timezone.utcを使用
    end_date = datetime.now(timezone.utc).replace(tzinfo=None)
    
    if args.end:
        # 入力された時刻をUTCとして扱う（タイムゾーン情報なしの場合はUTCと仮定）
        end_date = datetime.strptime(args.end, '%Y-%m-%d %H:%M:%S')
        # UTCとして扱う（tzinfo=Noneのまま、UTCとして扱う）
        print(f"指定された終了時刻（UTCとして扱う）: {end_date}")
    
    if args.start:
        # 入力された時刻をUTCとして扱う
        start_date = datetime.strptime(args.start, '%Y-%m-%d %H:%M:%S')
        print(f"指定された開始時刻（UTCとして扱う）: {start_date}")
    elif args.days:
        start_date = end_date - timedelta(days=args.days)
    elif args.hours:
        start_date = end_date - timedelta(hours=args.hours)
    else:
        # デフォルト: 過去1時間
        start_date = end_date - timedelta(hours=1)
    
    # UTCとして扱うことを明示
    print(f"\n評価期間（UTC）: {start_date} ～ {end_date}")
    
    # データローダーの初期化
    try:
        loader = ExchSimDataLoader()
    except Exception as e:
        print(f"エラー: データベース接続に失敗しました: {e}")
        print("\n環境変数を確認してください:")
        print("  USE_EXCH_SIM_DB=true")
        print("  DB_HOST, DB_PORT, DB_USER, DB_PASSWORD")
        sys.exit(1)
    
    # 評価の実行
    evaluator = DataQualityEvaluator(loader)
    try:
        results = evaluator.evaluate(
            args.symbol,
            start_date,
            end_date,
            args.interval
        )
        
        # サマリーを表示
        evaluator.print_summary()
        
        # レポートを保存
        if args.output:
            evaluator.save_report(args.output)
        
    except Exception as e:
        print(f"\nエラー: 評価中にエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        loader.close()


if __name__ == '__main__':
    main()

