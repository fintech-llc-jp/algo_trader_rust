"""
大きな損失の原因を分析するスクリプト
"""
import sys
import os
import pandas as pd
import numpy as np

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def analyze_losses(csv_path: str):
    """大きな損失の原因を分析"""
    df = pd.read_csv(csv_path)
    
    # トレードがある行を抽出
    trades = df[df['trade_action'].isin(['BUY', 'SELL', 'SHORT', 'COVER_SHORT'])].copy()
    
    # PnLが計算されている行（SELL/COVER_SHORT）を抽出
    closed_trades = trades[trades['trade_pnl'] != 0.0].copy()
    
    print("="*80)
    print("大きな損失の分析")
    print("="*80)
    
    # 基本統計
    print(f"\n総トレード数: {len(closed_trades)}")
    print(f"利益トレード数: {len(closed_trades[closed_trades['trade_pnl'] > 0])}")
    print(f"損失トレード数: {len(closed_trades[closed_trades['trade_pnl'] < 0])}")
    print(f"勝率: {len(closed_trades[closed_trades['trade_pnl'] > 0]) / len(closed_trades) * 100:.2f}%")
    
    if len(closed_trades) > 0:
        print(f"\n最大利益: {closed_trades['trade_pnl'].max():.0f} JPY")
        print(f"最大損失: {closed_trades['trade_pnl'].min():.0f} JPY")
        print(f"平均利益: {closed_trades[closed_trades['trade_pnl'] > 0]['trade_pnl'].mean():.0f} JPY")
        print(f"平均損失: {closed_trades[closed_trades['trade_pnl'] < 0]['trade_pnl'].mean():.0f} JPY")
    
    # 大きな損失のトップ10
    print("\n" + "="*80)
    print("大きな損失のトップ10")
    print("="*80)
    large_losses = closed_trades.nsmallest(10, 'trade_pnl')
    for idx, row in large_losses.iterrows():
        print(f"\n時刻: {row['timestamp']}")
        print(f"  アクション: {row['trade_action']}")
        print(f"  損失: {row['trade_pnl']:.0f} JPY")
        print(f"  現在価格: {row['current_price']:,.0f} JPY")
        print(f"  予測価格: {row['predicted_price']:,.0f} JPY")
        print(f"  実際価格: {row['actual_price']:,.0f} JPY")
        print(f"  予測結果: {row['predicted_result']}")
        print(f"  実際結果: {row['actual_result']}")
        print(f"  モメンタム強度: {row['momentum_intensity']}")
        print(f"  予測誤差: {row['error']:,.0f} JPY ({row['pct_error']:.2f}%)")
    
    # モメンタム強度と価格予測の不一致を分析
    print("\n" + "="*80)
    print("モメンタム強度と価格予測の不一致分析")
    print("="*80)
    
    # 予測結果とモメンタム強度の符号が異なる場合
    trades_with_momentum = trades[trades['momentum_intensity'].notna()].copy()
    if len(trades_with_momentum) > 0:
        # 予測結果とモメンタム強度の符号が異なる場合
        trades_with_momentum['pred_sign'] = np.sign(trades_with_momentum['predicted_result'])
        trades_with_momentum['momentum_sign'] = np.sign(trades_with_momentum['momentum_intensity'])
        trades_with_momentum['sign_mismatch'] = trades_with_momentum['pred_sign'] != trades_with_momentum['momentum_sign']
        
        mismatch_trades = trades_with_momentum[trades_with_momentum['sign_mismatch']]
        print(f"\n符号不一致のトレード数: {len(mismatch_trades)}")
        
        if len(mismatch_trades) > 0:
            mismatch_closed = mismatch_trades[mismatch_trades['trade_pnl'] != 0.0]
            if len(mismatch_closed) > 0:
                print(f"符号不一致のクローズ済みトレード数: {len(mismatch_closed)}")
                print(f"符号不一致の平均PnL: {mismatch_closed['trade_pnl'].mean():.0f} JPY")
                print(f"符号不一致の勝率: {len(mismatch_closed[mismatch_closed['trade_pnl'] > 0]) / len(mismatch_closed) * 100:.2f}%")
    
    # 予測誤差が大きい場合の損失
    print("\n" + "="*80)
    print("予測誤差と損失の関係")
    print("="*80)
    
    closed_trades['abs_error'] = closed_trades['error'].abs()
    large_error_trades = closed_trades[closed_trades['abs_error'] > closed_trades['abs_error'].quantile(0.9)]
    print(f"\n予測誤差が大きい（上位10%）トレード数: {len(large_error_trades)}")
    if len(large_error_trades) > 0:
        print(f"予測誤差が大きいトレードの平均PnL: {large_error_trades['trade_pnl'].mean():.0f} JPY")
        print(f"予測誤差が大きいトレードの勝率: {len(large_error_trades[large_error_trades['trade_pnl'] > 0]) / len(large_error_trades) * 100:.2f}%")

if __name__ == "__main__":
    csv_path = "/Users/sakamoto.yukio/workspace/algo_trader_v1/evaluation_results_1119/G_FX_BTCJPY_after_correction_prediction_comparison.csv"
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    
    analyze_losses(csv_path)

