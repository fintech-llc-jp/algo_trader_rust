"""
価格データの検証スクリプト
バックテストで使用される価格データが正しいか確認する
"""
import sys
import os
from datetime import datetime, timezone, timedelta

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.exch_sim_data_loader import ExchSimDataLoader
import pandas as pd

def parse_datetime(date_str: str) -> datetime:
    """文字列をdatetimeに変換（UTC）"""
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except ValueError:
        dt = datetime.fromisoformat(date_str)
    
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    return dt

def verify_price_data(symbol: str, start_date: datetime, end_date: datetime):
    """指定期間の価格データを検証"""
    print("="*80)
    print(f"価格データ検証: {symbol}")
    print(f"期間: {start_date} ～ {end_date}")
    print("="*80)
    
    # B_FX_BTCJPYの場合、実際のバックテストで使用された期間を確認
    if symbol == "B_FX_BTCJPY":
        print("\n注意: B_FX_BTCJPYのバックテスト結果では14,251,444や15,348,463などの価格が表示されています。")
        print("これらの価格が実際にデータベースに存在するか確認します。\n")
    
    loader = ExchSimDataLoader(use_connection_pool=True)
    
    try:
        # マーケットデータを読み込む
        df = loader.load_market_data(
            symbol,
            start_date,
            end_date,
            skip_min_samples_check=True
        )
        
        if len(df) == 0:
            print("データが見つかりませんでした")
            return
        
        print(f"\n読み込まれたデータ件数: {len(df)}")
        print(f"期間: {df.index.min()} ～ {df.index.max()}")
        
        # 価格の統計情報
        print("\n価格統計:")
        print(f"  bid_price_1: min={df['bid_price_1'].min():,.0f}, max={df['bid_price_1'].max():,.0f}, mean={df['bid_price_1'].mean():,.0f}")
        print(f"  ask_price_1: min={df['ask_price_1'].min():,.0f}, max={df['ask_price_1'].max():,.0f}, mean={df['ask_price_1'].mean():,.0f}")
        print(f"  mid_price:   min={df['mid_price'].min():,.0f}, max={df['mid_price'].max():,.0f}, mean={df['mid_price'].mean():,.0f}")
        
        # 価格変動の統計
        price_changes = df['mid_price'].diff()
        print(f"\n価格変動統計（1秒間）:")
        print(f"  min: {price_changes.min():,.0f} JPY")
        print(f"  max: {price_changes.max():,.0f} JPY")
        print(f"  mean: {price_changes.mean():,.2f} JPY")
        print(f"  std: {price_changes.std():,.2f} JPY")
        
        # 大きな価格変動を検出
        large_changes = price_changes[abs(price_changes) > 100000]
        if len(large_changes) > 0:
            print(f"\n⚠️  警告: 100万円以上の価格変動が {len(large_changes)} 件検出されました")
            print("\n大きな価格変動の例:")
            for idx, change in large_changes.head(10).items():
                prev_idx = df.index[df.index < idx][-1] if len(df.index[df.index < idx]) > 0 else None
                if prev_idx is not None:
                    prev_price = df.loc[prev_idx, 'mid_price']
                    curr_price = df.loc[idx, 'mid_price']
                    time_diff = (idx - prev_idx).total_seconds()
                    print(f"  {prev_idx} → {idx} ({time_diff:.1f}秒): {prev_price:,.0f} → {curr_price:,.0f} (変動: {change:,.0f} JPY)")
        
        # 特定の価格値の出現頻度を確認
        print("\n頻繁に出現する価格値（上位10件）:")
        price_counts = df['mid_price'].value_counts().head(10)
        for price, count in price_counts.items():
            pct = count / len(df) * 100
            print(f"  {price:,.0f}: {count}回 ({pct:.2f}%)")
        
        # 問題のある価格値（14,251,444と15,348,463）を確認
        suspicious_prices = [14251444, 15348463, 14219685]
        print("\n疑わしい価格値の出現:")
        for price in suspicious_prices:
            count = len(df[df['mid_price'] == price])
            if count > 0:
                pct = count / len(df) * 100
                print(f"  {price:,}: {count}回 ({pct:.2f}%)")
                # 出現時刻を表示
                occurrences = df[df['mid_price'] == price].index[:5]
                print(f"    出現時刻の例: {list(occurrences)}")
        
        # 時系列での価格変動を確認（最初の10分間）
        print("\n最初の10分間の価格変動（10秒ごと）:")
        sample_df = df.resample('10S').first()
        for i in range(min(60, len(sample_df))):
            idx = sample_df.index[i]
            if idx in df.index:
                row = df.loc[idx]
                print(f"  {idx}: mid={row['mid_price']:,.0f}, bid={row['bid_price_1']:,.0f}, ask={row['ask_price_1']:,.0f}")
        
        # 約定データの価格を確認
        print("\n約定データ（executions）の価格を確認:")
        exec_df = loader.load_executions(symbol, start_date, end_date)
        if len(exec_df) > 0:
            print(f"  約定データ件数: {len(exec_df)}")
            print(f"  価格範囲: min={exec_df['price'].min():,.0f}, max={exec_df['price'].max():,.0f}, mean={exec_df['price'].mean():,.0f}")
            print(f"  価格のユニーク値数: {exec_df['price'].nunique()}")
            
            # 頻繁に出現する価格値
            print("\n  約定データで頻繁に出現する価格値（上位10件）:")
            price_counts = exec_df['price'].value_counts().head(10)
            for price, count in price_counts.items():
                pct = count / len(exec_df) * 100
                print(f"    {price:,.0f}: {count}回 ({pct:.2f}%)")
            
            # 疑わしい価格値の確認
            suspicious_prices = [14251444, 15348463, 14219685]
            print("\n  約定データでの疑わしい価格値の出現:")
            for price in suspicious_prices:
                count = len(exec_df[exec_df['price'] == price])
                if count > 0:
                    pct = count / len(exec_df) * 100
                    print(f"    {price:,}: {count}回 ({pct:.2f}%)")
        else:
            print("  約定データが見つかりませんでした")
        
        # load_training_dataが返すデータを確認
        print("\nload_training_dataが返すデータを確認:")
        training_df = loader.load_training_data(symbol, start_date, end_date, skip_min_samples_check=True)
        print(f"  データ件数: {len(training_df)}")
        print(f"  mid_price統計: min={training_df['mid_price'].min():,.0f}, max={training_df['mid_price'].max():,.0f}, mean={training_df['mid_price'].mean():,.0f}")
        print(f"  mid_priceのユニーク値数: {training_df['mid_price'].nunique()}")
        
        # 疑わしい価格値の確認
        suspicious_prices = [14251444, 15348463, 14219685]
        print("\n  load_training_dataでの疑わしい価格値の出現:")
        for price in suspicious_prices:
            count = len(training_df[training_df['mid_price'] == price])
            if count > 0:
                pct = count / len(training_df) * 100
                print(f"    {price:,}: {count}回 ({pct:.2f}%)")
                # 出現時刻を表示
                occurrences = training_df[training_df['mid_price'] == price].index[:5]
                print(f"      出現時刻の例: {list(occurrences)}")
        
        # 最初の10件のデータを表示
        print("\n  load_training_dataの最初の10件:")
        for i in range(min(10, len(training_df))):
            idx = training_df.index[i]
            row = training_df.loc[idx]
            bid_str = f"{row.get('bid_price_1', 0):,.0f}" if 'bid_price_1' in row else 'N/A'
            ask_str = f"{row.get('ask_price_1', 0):,.0f}" if 'ask_price_1' in row else 'N/A'
            print(f"    {idx}: mid={row['mid_price']:,.0f}, bid={bid_str}, ask={ask_str}")
        
    finally:
        loader.close()

if __name__ == "__main__":
    import sys
    
    # 引数からシンボルと期間を取得（デフォルト値あり）
    symbol = sys.argv[1] if len(sys.argv) > 1 else "G_FX_BTCJPY"
    
    if len(sys.argv) > 4:
        # 期間を引数から取得
        start_date = parse_datetime(sys.argv[2])
        end_date = parse_datetime(sys.argv[3])
    else:
        # デフォルト期間
        if symbol == "B_FX_BTCJPY":
            # B_FX_BTCJPYのバックテスト期間
            start_date = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
            end_date = datetime(2026, 1, 15, 23, 59, 0, tzinfo=timezone.utc)
        else:
            # G_FX_BTCJPYのデフォルト期間
            start_date = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
            end_date = datetime(2026, 1, 15, 19, 0, 0, tzinfo=timezone.utc)
    
    verify_price_data(symbol, start_date, end_date)
