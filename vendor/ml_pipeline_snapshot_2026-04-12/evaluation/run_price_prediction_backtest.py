"""
Price Prediction Backtest Execution Script
1分後の約定価格を予測するモデルのバックテストを実行
"""
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Tuple, Optional
import matplotlib
matplotlib.use('Agg')  # バックエンドを設定（GUI不要）
import matplotlib.pyplot as plt
import seaborn as sns

# .envファイルを読み込む（存在する場合）
try:
    from dotenv import load_dotenv
    # プロジェクトルートの.envファイルを読み込む
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenvがインストールされていない場合はスキップ

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.data_loader import MarketDataLoader
from data.exch_sim_data_loader import ExchSimDataLoader
from data.feature_engineering import FeatureEngineer
from strategy.price_prediction_strategy import PricePredictionStrategy
from strategy.momentum_intensity_strategy import MomentumIntensityStrategy
from evaluation.backtester import Backtester
from evaluation.limit_order_backtester import LimitOrderBacktester
from config.settings import DatabaseConfig, ModelConfig, BacktestConfig


def apply_error_correction(
    predictions: pd.Series,
    actual_prices: pd.Series,
    error_window_size: int = 100,
    min_samples: int = 10
) -> pd.Series:
    """
    過去の予測エラーの平均値（バイアス）を計算して予測値を補正
    
    Args:
        predictions: 予測された価格
        actual_prices: 実際の価格（エラー計算用）
        error_window_size: エラー履歴のウィンドウサイズ（過去N件のエラーを使用）
        min_samples: 補正を適用する最小サンプル数
    
    Returns:
        補正された予測値
    """
    corrected_predictions = predictions.copy()
    
    # 有効なデータのみを使用
    valid_mask = predictions.notna() & actual_prices.notna()
    valid_indices = predictions.index[valid_mask]
    
    if len(valid_indices) < min_samples:
        return corrected_predictions
    
    # 時系列順にソート
    sorted_indices = valid_indices.sort_values()
    
    # 各時点で過去のエラーを計算して補正
    for i, idx in enumerate(sorted_indices):
        if i < min_samples:
            # 最小サンプル数に達するまで補正なし
            continue
        
        # 過去のエラーを計算
        past_start = max(0, i - error_window_size)
        past_indices = sorted_indices[past_start:i]
        
        if len(past_indices) < min_samples:
            continue
        
        # 過去の予測エラーを計算
        past_errors = predictions.loc[past_indices] - actual_prices.loc[past_indices]
        
        # エラーの平均（バイアス）を計算
        bias = past_errors.mean()
        
        # 予測値からバイアスを引く（バイアスが正なら予測が高すぎるので下げる）
        # dtype を揃えて代入し FutureWarning を回避
        val = predictions.loc[idx] - bias
        corrected_predictions.loc[idx] = corrected_predictions.dtype.type(val)
    
    return corrected_predictions


def generate_signals_from_predictions(
    df: pd.DataFrame,
    predictions: pd.Series,
    price_change_threshold: float = 0.0001,
    momentum_intensity: pd.Series = None,
    momentum_threshold: int = 4,
    use_momentum: bool = True,
    max_prediction_error_pct: float = 0.5
) -> Tuple[pd.Series, pd.Series]:
    """
    予測価格とモメンタム強度から取引シグナルを生成（OR条件：どちらかがシグナルを出す場合に取引）
    
    Args:
        df: 市場データ
        predictions: 予測された約定価格
        price_change_threshold: 価格変動の閾値（デフォルト0.01%）
        momentum_intensity: モメンタム強度（-10から10の整数、オプション）
        momentum_threshold: モメンタム強度の閾値（デフォルト5）
        use_momentum: モメンタム強度を使用するか（デフォルトTrue）
        max_prediction_error_pct: 予測誤差の最大許容値（パーセンテージ、デフォルト0.5%）
    
    Returns:
        (signals, confidence)
        signals: -1=SELL, 0=HOLD, 1=BUY
        confidence: 予測の信頼度（価格変動とモメンタム強度に基づく）
    """
    # 予測が存在するインデックスのみを使用
    valid_indices = predictions.index.intersection(df.index)
    if len(valid_indices) == 0:
        return pd.Series(0, index=predictions.index), pd.Series(0.0, index=predictions.index)
    
    # 現在の価格（約定価格があればそれを使用、なければmid_price）
    if 'exec_price_all' in df.columns:
        current_price = df.loc[valid_indices, 'exec_price_all']
    else:
        current_price = df.loc[valid_indices, 'mid_price']
    
    # 予測価格と現在価格の差分
    price_diff = predictions.loc[valid_indices] - current_price
    price_change_pct = price_diff / (current_price + 1e-9)
    
    # 予測誤差を計算（予測価格と現在価格の差分の絶対値が大きすぎる場合は取引しない）
    # 予測価格が現在価格から大きく乖離している場合は、予測の信頼度が低いと判断
    abs_price_change_pct = np.abs(price_change_pct) * 100  # パーセンテージに変換
    
    # 価格予測ベースのシグナル
    price_signals = pd.Series(0, index=predictions.index)
    price_signals.loc[valid_indices] = np.where(
        price_change_pct > price_change_threshold, 1,
        np.where(price_change_pct < -price_change_threshold, -1, 0)
    )
    
    # モメンタム強度ベースのシグナル（オプション）
    momentum_signals = pd.Series(0, index=predictions.index)
    if use_momentum and momentum_intensity is not None:
        # モメンタム強度が利用可能なインデックスのみ
        momentum_indices = valid_indices.intersection(momentum_intensity.index)
        if len(momentum_indices) > 0:
            momentum_values = momentum_intensity.loc[momentum_indices]
            momentum_signals.loc[momentum_indices] = np.where(
                momentum_values >= momentum_threshold, 1,
                np.where(momentum_values <= -momentum_threshold, -1, 0)
            )
    
    # シグナルの統合（OR条件：どちらかがシグナルを出す場合に取引）
    signals = pd.Series(0, index=predictions.index)
    
    if use_momentum and momentum_intensity is not None:
        # OR条件：価格予測またはモメンタム強度のどちらかがシグナルを出す場合に取引
        for idx in valid_indices:
            price_sig = price_signals.loc[idx]
            momentum_sig = momentum_signals.loc[idx] if idx in momentum_signals.index else 0
            
            # 予測誤差が大きい場合は取引しない（予測価格と現在価格の差分が大きすぎる場合）
            if idx in abs_price_change_pct.index:
                if abs_price_change_pct.loc[idx] > max_prediction_error_pct:
                    signals.loc[idx] = 0
                    continue
            
            # OR条件：どちらかがシグナルを出す場合に取引
            # 両方が同じ方向を示す場合は優先度が高い
            if price_sig == 1 and momentum_sig == 1:
                signals.loc[idx] = 1  # BUY（両方一致）
            elif price_sig == -1 and momentum_sig == -1:
                signals.loc[idx] = -1  # SELL（両方一致）
            elif price_sig == 1 or momentum_sig == 1:
                signals.loc[idx] = 1  # BUY（どちらかがBUY）
            elif price_sig == -1 or momentum_sig == -1:
                signals.loc[idx] = -1  # SELL（どちらかがSELL）
            else:
                signals.loc[idx] = 0  # HOLD（両方HOLD）
    else:
        # モメンタム強度を使用しない場合：価格予測のみ
        # 予測誤差が大きい場合は取引しない（予測価格と現在価格の差分が大きすぎる場合）
        for idx in valid_indices:
            if idx in abs_price_change_pct.index:
                if abs_price_change_pct.loc[idx] > max_prediction_error_pct:
                    signals.loc[idx] = 0
                    continue
            
            signals.loc[idx] = price_signals.loc[idx]
    
    # 信頼度の計算（価格変動とモメンタム強度の両方を考慮）
    abs_price_change = np.abs(price_change_pct)
    
    # 1行だけのデータフレームの場合、quantile_95の計算が正しく行われないため、固定値を使用
    if len(abs_price_change) == 1:
        # 1行だけの場合、価格変動の絶対値に基づいてconfidenceを計算
        # 0.1%未満: 0.3, 0.1-0.5%: 0.5, 0.5-1.0%: 0.7, 1.0%以上: 0.9
        quantile_95 = 1.0  # 固定値として使用
    else:
        quantile_95 = abs_price_change.quantile(0.95) if len(abs_price_change) > 0 else 1.0
    
    confidence = pd.Series(0.0, index=predictions.index)
    
    for idx in valid_indices:
        if len(abs_price_change) == 1:
            # 1行だけの場合、価格変動の絶対値に基づいてconfidenceを計算
            abs_change = abs_price_change.loc[idx]
            if abs_change < 0.001:  # 0.1%未満
                price_conf = 0.3
            elif abs_change < 0.005:  # 0.5%未満
                price_conf = 0.5
            elif abs_change < 0.01:  # 1.0%未満
                price_conf = 0.7
            else:  # 1.0%以上
                price_conf = min(0.9, 0.5 + abs_change / 0.1)  # 最大0.9
        else:
            price_conf = np.clip(abs_price_change.loc[idx] / (quantile_95 + 1e-9), 0.0, 1.0)
        
        # モメンタム強度による信頼度の調整
        if use_momentum and momentum_intensity is not None and idx in momentum_intensity.index:
            intensity = momentum_intensity.loc[idx]
            # モメンタム強度を0-1に正規化（-10から10を0から1に）
            momentum_conf = np.clip((abs(intensity) / 10.0), 0.0, 1.0)
            # 価格予測とモメンタム強度の平均（AND条件に合わせて）
            confidence.loc[idx] = (price_conf + momentum_conf) / 2.0
        else:
            confidence.loc[idx] = price_conf
    
    return signals, confidence


def evaluate_predictions(
    predictions: pd.Series,
    actual_prices: pd.Series,
    current_prices: pd.Series,
    output_dir: Optional[str] = None,
    symbol: str = "G_FX_BTCJPY",
    trades_df: pd.DataFrame = None,
    df: pd.DataFrame = None,
    momentum_intensity_strategy: MomentumIntensityStrategy = None
) -> dict:
    """
    予測結果と実際の価格を詳細に評価
    
    Args:
        predictions: 予測された価格
        actual_prices: 実際の価格
        current_prices: 現在の価格（方向性評価用）
        output_dir: 出力ディレクトリ（Noneの場合は出力しない）
        symbol: シンボル名（ファイル名用）
    
    Returns:
        評価指標の辞書
    """
    # 有効なデータのみを使用
    valid_mask = predictions.notna() & actual_prices.notna() & current_prices.notna()
    valid_predictions = predictions[valid_mask]
    valid_actuals = actual_prices[valid_mask]
    valid_current = current_prices[valid_mask]
    
    if len(valid_predictions) == 0:
        return {
            'mae': None,
            'rmse': None,
            'mape': None,
            'direction_accuracy': None,
            'r2_score': None,
            'median_ae': None,
            'percentile_errors': None
        }
    
    # 誤差の計算
    errors = valid_predictions - valid_actuals
    abs_errors = np.abs(errors)
    pct_errors = errors / (valid_actuals + 1e-9) * 100
    
    # 基本統計量
    mae = np.mean(abs_errors)
    rmse = np.sqrt(np.mean(errors ** 2))
    mape = np.mean(np.abs(pct_errors))
    median_ae = np.median(abs_errors)
    
    # R²スコア
    ss_res = np.sum((valid_actuals - valid_predictions) ** 2)
    ss_tot = np.sum((valid_actuals - np.mean(valid_actuals)) ** 2)
    r2_score = 1 - (ss_res / (ss_tot + 1e-9))
    
    # 分位点誤差
    percentile_errors = {
        'p25': np.percentile(abs_errors, 25),
        'p50': np.percentile(abs_errors, 50),
        'p75': np.percentile(abs_errors, 75),
        'p90': np.percentile(abs_errors, 90),
        'p95': np.percentile(abs_errors, 95),
        'p99': np.percentile(abs_errors, 99)
    }
    
    # 方向性の精度（強度付き）
    # 価格変化率を計算（パーセンテージ）
    # 予測方向: 予測価格と予測時点の現在価格を比較
    pred_change_pct = ((valid_predictions - valid_current) / (valid_current + 1e-9)) * 100
    # 実際の方向: 実際の価格（60秒後）と予測時点の現在価格を比較
    # これにより、予測と実際を同じ基準（予測時点の現在価格）で比較できる
    actual_change_pct = ((valid_actuals - valid_current) / (valid_current + 1e-9)) * 100
    
    # 実際の値の統計を計算（デバッグ用）
    pred_change_stats = {
        'min': float(np.min(pred_change_pct)),
        'max': float(np.max(pred_change_pct)),
        'mean': float(np.mean(pred_change_pct)),
        'std': float(np.std(pred_change_pct)),
        'p95': float(np.percentile(np.abs(pred_change_pct), 95))
    }
    actual_change_stats = {
        'min': float(np.min(actual_change_pct)),
        'max': float(np.max(actual_change_pct)),
        'mean': float(np.mean(actual_change_pct)),
        'std': float(np.std(actual_change_pct)),
        'p95': float(np.percentile(np.abs(actual_change_pct), 95))
    }
    
    # 実際の値に基づいてスケーリングを調整
    # より細かいスケーリングを使用：0.01% = 強度1、0.1% = 強度10
    # これにより、小さな変化率でも整数値が得られる
    base_change_pct = 0.01  # 0.01%の変化率を強度1にマッピング
    scale_factor = 1.0 / base_change_pct  # 0.01% = 1の強度
    
    # 予測結果の強度（-10から10の範囲にクリップして整数に変換）
    # より細かいスケーリングを使用してから整数に変換
    pred_result_float = pred_change_pct * scale_factor
    pred_result = np.clip(np.round(pred_result_float), -10, 10).astype(int)
    
    # 実際の結果の強度（-10から10の範囲にクリップして整数に変換）
    actual_result_float = actual_change_pct * scale_factor
    actual_result = np.clip(np.round(actual_result_float), -10, 10).astype(int)
    
    # 方向性の精度（符号が一致しているか）
    direction_accuracy = np.mean(np.sign(pred_result) == np.sign(actual_result)) * 100
    
    # デバッグ情報を出力（最初の実行時のみ）
    if output_dir:
        debug_info = {
            'pred_change_stats': pred_change_stats,
            'actual_change_stats': actual_change_stats,
            'base_change_pct_for_scaling': float(base_change_pct),
            'scale_factor': float(scale_factor),
            'pred_result_range': [int(np.min(pred_result)), int(np.max(pred_result))],
            'actual_result_range': [int(np.min(actual_result)), int(np.max(actual_result))],
            'pred_result_unique_values': sorted(np.unique(pred_result).tolist()),
            'actual_result_unique_values': sorted(np.unique(actual_result).tolist()),
            'pred_result_value_counts': {int(k): int(v) for k, v in zip(*np.unique(pred_result, return_counts=True))},
            'actual_result_value_counts': {int(k): int(v) for k, v in zip(*np.unique(actual_result, return_counts=True))}
        }
        import json
        debug_file = os.path.join(output_dir, f'{symbol}_direction_scaling_debug.json')
        with open(debug_file, 'w') as f:
            json.dump(debug_info, f, indent=2)
    
    # 結果を辞書にまとめる
    metrics = {
        'mae': float(mae),
        'rmse': float(rmse),
        'mape': float(mape),
        'median_ae': float(median_ae),
        'r2_score': float(r2_score),
        'direction_accuracy': float(direction_accuracy),
        'percentile_errors': percentile_errors,
        'num_samples': len(valid_predictions)
    }
    
    # 可視化とCSV出力
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        
        # 1. 時系列比較グラフ
        plt.figure(figsize=(15, 8))
        plt.plot(valid_predictions.index, valid_predictions.values, 
                label='Predicted Price', alpha=0.7, linewidth=1.5)
        plt.plot(valid_actuals.index, valid_actuals.values, 
                label='Actual Price', alpha=0.7, linewidth=1.5)
        plt.xlabel('Time')
        plt.ylabel('Price (JPY)')
        plt.title(f'Price Prediction vs Actual: {symbol}')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, f'{symbol}_prediction_comparison.png'), dpi=150)
        plt.close()
        
        # 2. 誤差の分布ヒストグラム
        plt.figure(figsize=(12, 6))
        plt.hist(errors, bins=50, alpha=0.7, edgecolor='black')
        plt.xlabel('Prediction Error (JPY)')
        plt.ylabel('Frequency')
        plt.title(f'Prediction Error Distribution: {symbol}\nMAE={mae:,.0f} JPY, RMSE={rmse:,.0f} JPY')
        plt.axvline(x=0, color='r', linestyle='--', linewidth=2, label='Zero Error')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, f'{symbol}_error_distribution.png'), dpi=150)
        plt.close()
        
        # 3. 誤差の時系列グラフ
        plt.figure(figsize=(15, 6))
        plt.plot(valid_predictions.index, errors.values, alpha=0.7, linewidth=1)
        plt.axhline(y=0, color='r', linestyle='--', linewidth=2)
        plt.xlabel('Time')
        plt.ylabel('Prediction Error (JPY)')
        plt.title(f'Prediction Error Over Time: {symbol}')
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, f'{symbol}_error_timeseries.png'), dpi=150)
        plt.close()
        
        # 4. 散布図（予測 vs 実際）
        plt.figure(figsize=(10, 10))
        plt.scatter(valid_actuals.values, valid_predictions.values, alpha=0.5, s=10)
        
        # 45度線を追加
        min_price = min(valid_actuals.min(), valid_predictions.min())
        max_price = max(valid_actuals.max(), valid_predictions.max())
        plt.plot([min_price, max_price], [min_price, max_price], 
                'r--', linewidth=2, label='Perfect Prediction')
        
        plt.xlabel('Actual Price (JPY)')
        plt.ylabel('Predicted Price (JPY)')
        plt.title(f'Predicted vs Actual Price: {symbol}\nR²={r2_score:.4f}')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, f'{symbol}_scatter_plot.png'), dpi=150)
        plt.close()
        
        # 5. パーセンテージ誤差の分布
        plt.figure(figsize=(12, 6))
        plt.hist(pct_errors, bins=50, alpha=0.7, edgecolor='black')
        plt.xlabel('Prediction Error (%)')
        plt.ylabel('Frequency')
        plt.title(f'Percentage Error Distribution: {symbol}\nMAPE={mape:.2f}%')
        plt.axvline(x=0, color='r', linestyle='--', linewidth=2, label='Zero Error')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, f'{symbol}_pct_error_distribution.png'), dpi=150)
        plt.close()
        
        # 6. トレード情報をマージとポジション保有中のPL計算
        trade_info = pd.Series('', index=valid_predictions.index, dtype=str)
        trade_pnl = pd.Series(0.0, index=valid_predictions.index, dtype=float)
        
        # ポジション状態を追跡（エントリー価格、数量、方向）
        current_position = {
            'entry_price': 0.0,
            'quantity': 0.0,
            'direction': 0  # 1=ロング, -1=ショート, 0=なし
        }
        
        # bid_price_1とask_price_1を取得
        bid_price_col = 'bid_price_1' if df is not None and 'bid_price_1' in df.columns else None
        ask_price_col = 'ask_price_1' if df is not None and 'ask_price_1' in df.columns else None
        
        # トレード情報を時系列順にソート
        if trades_df is not None and len(trades_df) > 0:
            # タイムスタンプでソート
            trades_sorted = trades_df.copy()
            if 'timestamp' in trades_sorted.columns:
                trades_sorted['timestamp'] = pd.to_datetime(trades_sorted['timestamp'])
                trades_sorted = trades_sorted.sort_values('timestamp')
        
        # 時系列順に処理
        sorted_indices = valid_predictions.index.sort_values()
        
        # trades_dfのtimestampを確実にpd.Timestampに変換
        if trades_df is not None and len(trades_df) > 0:
            trades_df = trades_df.copy()
            if 'timestamp' in trades_df.columns:
                trades_df['timestamp'] = pd.to_datetime(trades_df['timestamp'])
            elif trades_df.index.name == 'timestamp' or isinstance(trades_df.index, pd.DatetimeIndex):
                # インデックスがタイムスタンプの場合はカラムとして追加
                trades_df['timestamp'] = pd.to_datetime(trades_df.index)
        
        for idx in sorted_indices:
            # この時点で発生したトレードを確認
            if trades_df is not None and len(trades_df) > 0:
                for trade_idx, row in trades_df.iterrows():
                    timestamp = row.get('timestamp', trade_idx)
                    # timestampを確実にpd.Timestampに変換
                    if not isinstance(timestamp, pd.Timestamp):
                        try:
                            timestamp = pd.to_datetime(timestamp)
                        except:
                            # 変換できない場合はスキップ
                            continue
                    
                    # idxも確実にpd.Timestampに変換
                    if not isinstance(idx, pd.Timestamp):
                        try:
                            idx_ts = pd.to_datetime(idx)
                        except:
                            continue
                    else:
                        idx_ts = idx
                    
                    time_diff = abs((idx_ts - timestamp).total_seconds())
                    if time_diff < 1.0:  # 1秒以内のトレードをマッチング
                        action = row.get('action', '')
                        pnl = row.get('pnl', 0.0)
                        # LimitOrderBacktesterの場合はexecution_price、Backtesterの場合はprice
                        price = row.get('execution_price', row.get('price', 0.0))
                        quantity = row.get('quantity', 0.0)
                        
                        # 値の妥当性チェック
                        if price <= 0 or quantity <= 0:
                            continue
                        
                        # トレード情報を記録（すべてのアクションを記録）
                        if action in ['BUY', 'SELL', 'SHORT', 'COVER_SHORT']:
                            trade_info.loc[idx] = action
                            trade_pnl.loc[idx] = pnl if pd.notna(pnl) else 0.0
                            
                            # ポジション状態を更新（実際のトレード量を使用）
                            # fixed_quantityが設定されている場合はその値、そうでない場合は資金の10%相当
                            if action == 'BUY':
                                current_position['entry_price'] = float(price)
                                current_position['quantity'] = float(quantity)  # 実際のトレード量を使用
                                current_position['direction'] = 1  # ロング
                            elif action == 'SHORT':
                                current_position['entry_price'] = float(price)
                                current_position['quantity'] = float(quantity)  # 実際のトレード量を使用
                                current_position['direction'] = -1  # ショート
                            elif action in ['SELL', 'COVER_SHORT']:
                                # ポジションをクローズ
                                current_position['entry_price'] = 0.0
                                current_position['quantity'] = 0.0
                                current_position['direction'] = 0
                        break
            
            # ポジションがある場合、未実現PLを計算してtrade_actionに表示
            if current_position['direction'] != 0 and df is not None and idx in df.index:
                if bid_price_col and ask_price_col:
                    bid_price = df.loc[idx, bid_price_col] if pd.notna(df.loc[idx, bid_price_col]) else None
                    ask_price = df.loc[idx, ask_price_col] if pd.notna(df.loc[idx, ask_price_col]) else None
                    
                    if bid_price is not None and ask_price is not None and current_position['entry_price'] > 0 and current_position['quantity'] > 0:
                        # 数量とエントリー価格の妥当性チェック
                        # quantityはBTCの数量（例：0.001）で、entry_priceはJPY（例：14,000,000）
                        # 異常に大きい値の場合はスキップ
                        if current_position['quantity'] > 1.0:  # BTCの数量が1を超えるのは異常
                            continue
                        if current_position['entry_price'] < 1000000 or current_position['entry_price'] > 50000000:  # 価格の妥当性チェック
                            continue
                        
                        # 未実現PLを計算
                        if current_position['direction'] == 1:  # ロングポジション
                            # エントリー時: BestAskで買う
                            # 現在: BestBidで売る（評価価格）
                            # PL = (現在のBestBid - エントリー時のBestAsk) × 数量
                            # 数量は実際のトレード量（fixed_quantityが設定されている場合はその値）
                            unrealized_pnl = (bid_price - current_position['entry_price']) * current_position['quantity']
                        else:  # ショートポジション
                            # エントリー時: BestBidで売る
                            # 現在: BestAskで買い戻す（評価価格）
                            # PL = (エントリー時のBestBid - 現在のBestAsk) × 数量
                            # 数量は実際のトレード量（fixed_quantityが設定されている場合はその値）
                            unrealized_pnl = (current_position['entry_price'] - ask_price) * current_position['quantity']
                        
                        # trade_actionに未実現PLを追加
                        current_action = trade_info.loc[idx] if idx in trade_info.index else ''
                        if current_action == '':
                            # アクションがない場合は、PLのみを表示
                            trade_info.loc[idx] = f"PL({unrealized_pnl:.1f})"
                        else:
                            # 既存のアクションがある場合は、その後にPLを追加
                            trade_info.loc[idx] = f"{current_action} PL({unrealized_pnl:.1f})"
        
        # 7. モメンタム強度を計算
        momentum_intensity = pd.Series(0, index=valid_predictions.index, dtype=int)
        if momentum_intensity_strategy is not None and df is not None:
            try:
                # モメンタム強度を予測
                momentum_intensity_pred = momentum_intensity_strategy.predict_intensity(df)
                # インデックスが一致する部分のみを取得
                common_indices = valid_predictions.index.intersection(momentum_intensity_pred.index)
                if len(common_indices) > 0:
                    momentum_intensity.loc[common_indices] = momentum_intensity_pred.loc[common_indices].values
            except Exception as e:
                print(f"Warning: Failed to calculate momentum intensity: {e}")
                # エラーが発生した場合は0のまま
        
        # 8. CSVファイルに結果を出力
        comparison_df = pd.DataFrame({
            'timestamp': valid_predictions.index,
            'current_price': valid_current.values,
            'predicted_price': valid_predictions.values,
            'actual_price': valid_actuals.values,
            'error': errors.values,
            'abs_error': abs_errors.values,
            'pct_error': pct_errors.values,
            'predicted_result': pred_result,
            'actual_result': actual_result,
            'momentum_intensity': momentum_intensity.values,
            'trade_action': trade_info.values,
            'trade_pnl': trade_pnl.values
        })
        comparison_df.to_csv(
            os.path.join(output_dir, f'{symbol}_prediction_comparison.csv'),
            index=False
        )
        
        # 7. 評価指標をCSVに出力
        metrics_df = pd.DataFrame([{
            'metric': 'MAE',
            'value': mae,
            'unit': 'JPY'
        }, {
            'metric': 'RMSE',
            'value': rmse,
            'unit': 'JPY'
        }, {
            'metric': 'MAPE',
            'value': mape,
            'unit': '%'
        }, {
            'metric': 'Median AE',
            'value': median_ae,
            'unit': 'JPY'
        }, {
            'metric': 'R² Score',
            'value': r2_score,
            'unit': ''
        }, {
            'metric': 'Direction Accuracy',
            'value': direction_accuracy,
            'unit': '%'
        }, {
            'metric': 'P25 Error',
            'value': percentile_errors['p25'],
            'unit': 'JPY'
        }, {
            'metric': 'P50 Error',
            'value': percentile_errors['p50'],
            'unit': 'JPY'
        }, {
            'metric': 'P75 Error',
            'value': percentile_errors['p75'],
            'unit': 'JPY'
        }, {
            'metric': 'P90 Error',
            'value': percentile_errors['p90'],
            'unit': 'JPY'
        }, {
            'metric': 'P95 Error',
            'value': percentile_errors['p95'],
            'unit': 'JPY'
        }, {
            'metric': 'P99 Error',
            'value': percentile_errors['p99'],
            'unit': 'JPY'
        }])
        metrics_df.to_csv(
            os.path.join(output_dir, f'{symbol}_evaluation_metrics.csv'),
            index=False
        )
        
        print(f"\nEvaluation results saved to: {output_dir}")
    
    return metrics


def run_price_prediction_backtest(
    symbol: str = "G_FX_BTCJPY",
    start_date: datetime = None,
    end_date: datetime = None,
    show_trades: bool = False,
    timeframes: list = None,
    prediction_horizon: int = 60,
    price_change_threshold: float = 0.0001,
    confidence_threshold: float = None,
    use_limit_orders: bool = False,
    limit_order_timeout_seconds: int = 60,
    evaluate_prediction_only: bool = False,
    output_dir: Optional[str] = None,
    apply_error_correction_flag: bool = True,
    error_window_size: int = 100,
    stop_loss: float = None,
    take_profit: float = None,
    fixed_quantity: float = None,
    model_name: Optional[str] = None
):
    """
    価格予測モデルのバックテストを実行
    
    Args:
        symbol: シンボル
        start_date: 開始日時
        end_date: 終了日時
        show_trades: トレード履歴を表示するか
        timeframes: タイムフレームのリスト（秒）
        prediction_horizon: 予測ホライズン（秒、デフォルト60秒=1分）
        price_change_threshold: 価格変動の閾値（シグナル生成用）
        confidence_threshold: 信頼度閾値
        use_limit_orders: Limit Orderを使用するか
        limit_order_timeout_seconds: Limit Orderのタイムアウト（秒）
        evaluate_prediction_only: Trueの場合、予測精度のみを評価（取引は行わない）
        stop_loss: 損切の閾値（JPY、損失がこの値を超えるとLIMIT注文で損切）
        take_profit: 利益確定の閾値（JPY、利益がこの値を超えるとLIMIT注文で利益確定）
        fixed_quantity: 固定トレード量（BTC、指定された場合はこの値を使用、Noneの場合は資金の10%を使用）
        model_name: モデル保存時の名前（指定されていない場合はシンボル名を使用）
    """
    # データベース設定の確認と表示
    print(f"Database Configuration:")
    print(f"  Use ExchSim DB: {DatabaseConfig.USE_EXCH_SIM_DB}")
    print(f"  Database Name: {DatabaseConfig.EXCH_SIM_DB_NAME if DatabaseConfig.USE_EXCH_SIM_DB else DatabaseConfig.NAME}")
    print(f"  Host: {DatabaseConfig.HOST}")
    print(f"  Port: {DatabaseConfig.PORT}")
    print(f"  User: {DatabaseConfig.USER}")
    print()
    
    loader = MarketDataLoader()
    feature_engineer = FeatureEngineer()
    
    # タイムフレームが指定されていない場合はデフォルト値を使用
    if timeframes is None:
        timeframes = [1, 5, 30]  # デフォルト: 1秒、5秒、30秒
    
    strategy = PricePredictionStrategy(
        timeframes=timeframes,
        prediction_horizon=prediction_horizon
    )
    
    # タイムフレームの表示用フォーマット
    def format_timeframe(tf):
        if tf >= 3600:
            return f"{tf//3600}h"
        elif tf >= 60:
            return f"{tf//60}min"
        else:
            return f"{tf}s"
    
    tf_display = [format_timeframe(tf) for tf in timeframes]
    print(f"Timeframes: {timeframes} seconds ({', '.join(tf_display)})")
    print(f"Prediction Horizon: {prediction_horizon} seconds ({prediction_horizon//60} minutes)")
    
    try:
        # 日付の設定
        if end_date is None:
            end_date = datetime.now()
        if start_date is None:
            start_date = end_date - timedelta(days=1)
        
        # JSTからUTCへの変換（exch_simデータベースはUTCで保存されているため）
        # 入力された時間がnaive datetimeの場合、JSTとして扱う
        # JSTからUTC: UTC = JST - 9時間
        if start_date.tzinfo is None:
            # naive datetimeをJSTとして扱い、UTCに変換
            start_date_utc = start_date - timedelta(hours=9)
            end_date_utc = end_date - timedelta(hours=9)
            print(f"\n{'='*70}")
            print(f"Price Prediction Backtest: {symbol}")
            print(f"Period (JST): {start_date} to {end_date}")
            print(f"Period (UTC): {start_date_utc} to {end_date_utc}")
            print(f"{'='*70}\n")
            # UTCに変換した時間を使用
            start_date = start_date_utc
            end_date = end_date_utc
        else:
            # 既にタイムゾーン情報がある場合はそのまま使用
            print(f"\n{'='*70}")
            print(f"Price Prediction Backtest: {symbol}")
            print(f"Period: {start_date} to {end_date}")
            print(f"{'='*70}\n")
        
        # データロード
        print("Loading data...")
        try:
            df = loader.load_training_data(symbol, start_date, end_date)
        except ValueError as e:
            print(f"\nError loading data: {e}")
            print("\nSuggestions:")
            print("1. Check if the database is running and accessible")
            print("2. Verify that data exists for the specified symbol and period")
            print("3. Try running: python ml_pipeline/scripts/check_database.py")
            print("4. Use --start-date and --end-date to specify a period with data")
            raise
        
        if len(df) == 0:
            raise ValueError("No data available for the specified period")
        
        print(f"Loaded {len(df)} records")
        
        # 特徴量エンジニアリング
        print("Engineering features...")
        df = feature_engineer.engineer_features(df)
        
        # 訓練/テスト分割
        print("Splitting data into training and test sets...")
        split_idx = int(len(df) * 0.5)  # 50:50に分割
        train_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()
        
        print(f"Training samples: {len(train_df)}, Test samples: {len(test_df)}")
        
        # モメンタム強度モデルの初期化と訓練
        momentum_intensity_strategy = None
        try:
            print("Training momentum intensity model...")
            momentum_intensity_strategy = MomentumIntensityStrategy(
                timeframes=timeframes,
                prediction_horizon=prediction_horizon
            )
            momentum_train_result = momentum_intensity_strategy.train(train_df)
            print(f"Momentum intensity model trained:")
            print(f"  MAE: {momentum_train_result.get('mae', 0):.4f}%")
            print(f"  Direction Accuracy: {momentum_train_result.get('direction_accuracy', 0):.2f}%")
        except Exception as e:
            print(f"Warning: Failed to train momentum intensity model: {e}")
            print("Continuing without momentum intensity...")
        
        # 訓練
        print("Training price prediction model...")
        train_result = strategy.train(train_df)
        print(f"Model trained:")
        print(f"  MAE: {train_result.get('mae', 0):,.0f} JPY")
        print(f"  RMSE: {train_result.get('rmse', 0):,.0f} JPY")
        print(f"  MAPE: {train_result.get('mape', 0):.2f}%")
        
        # モデルをファイルに保存
        try:
            model_dir = ModelConfig.MODEL_DIR
            os.makedirs(model_dir, exist_ok=True)
            
            # モデル名を決定（指定されていない場合はシンボル名を使用）
            model_name_to_use = model_name if model_name else symbol
            
            # 価格予測モデルを保存
            price_model_path = os.path.join(model_dir, f'price_prediction_{model_name_to_use}.joblib')
            strategy.model.save(price_model_path)
            print(f"Price prediction model saved to: {price_model_path}")
            
            # モメンタム強度モデルを保存（訓練済みの場合）
            if momentum_intensity_strategy is not None and momentum_intensity_strategy.model.model is not None:
                momentum_model_path = os.path.join(model_dir, f'momentum_intensity_{model_name_to_use}.joblib')
                momentum_intensity_strategy.model.save(momentum_model_path)
                print(f"Momentum intensity model saved to: {momentum_model_path}")
        except Exception as e:
            print(f"Warning: Failed to save models: {e}")
        
        # 予測
        print("Generating predictions...")
        predictions = strategy.predict(test_df)
        
        # 実際の価格を取得（prediction_horizon秒後）
        if 'exec_price_all' in test_df.columns:
            actual_price_col = 'exec_price_all'
        else:
            actual_price_col = 'mid_price'
        
        # 予測時点からprediction_horizon秒後の実際の価格
        actual_prices = test_df[actual_price_col].shift(-prediction_horizon)
        
        # 予測と実際の価格が両方存在するデータのみを使用
        valid_mask = predictions.notna() & actual_prices.notna()
        valid_predictions = predictions[valid_mask]
        valid_actuals = actual_prices[valid_mask]
        
        # 現在の価格を取得（方向性評価用）
        current_prices = test_df.loc[valid_predictions.index, actual_price_col] if len(valid_predictions) > 0 else pd.Series()
        
        # 予測精度の評価（補正前）
        print("\n" + "="*70)
        print("PREDICTION ACCURACY METRICS (BEFORE ERROR CORRECTION)")
        print("="*70)
        
        # 補正前の詳細な評価を実行
        if len(valid_predictions) > 0:
            eval_metrics_before = evaluate_predictions(
                valid_predictions,
                valid_actuals,
                current_prices,
                output_dir=output_dir,
                symbol=f"{symbol}_before_correction" if apply_error_correction_flag else symbol,
                trades_df=None,  # 補正前はトレード情報なし
                df=test_df,
                momentum_intensity_strategy=momentum_intensity_strategy
            )
            
            mae_before = eval_metrics_before['mae']
            rmse_before = eval_metrics_before['rmse']
            mape_before = eval_metrics_before['mape']
            median_ae_before = eval_metrics_before['median_ae']
            r2_score_before = eval_metrics_before['r2_score']
            direction_accuracy_before = eval_metrics_before['direction_accuracy']
            percentile_errors_before = eval_metrics_before['percentile_errors']
            
            print(f"Mean Absolute Error (MAE): {mae_before:,.0f} JPY")
            print(f"Root Mean Squared Error (RMSE): {rmse_before:,.0f} JPY")
            print(f"Mean Absolute Percentage Error (MAPE): {mape_before:.2f}%")
            print(f"Median Absolute Error: {median_ae_before:,.0f} JPY")
            print(f"R² Score: {r2_score_before:.4f}")
            print(f"Direction Accuracy: {direction_accuracy_before:.2f}%")
            print(f"\nPercentile Errors:")
            print(f"  P25: {percentile_errors_before['p25']:,.0f} JPY")
            print(f"  P50 (Median): {percentile_errors_before['p50']:,.0f} JPY")
            print(f"  P75: {percentile_errors_before['p75']:,.0f} JPY")
            print(f"  P90: {percentile_errors_before['p90']:,.0f} JPY")
            print(f"  P95: {percentile_errors_before['p95']:,.0f} JPY")
            print(f"  P99: {percentile_errors_before['p99']:,.0f} JPY")
            print(f"\nValid Predictions: {len(valid_predictions)}")
        else:
            print("No valid predictions available for evaluation")
            eval_metrics_before = {
                'mae': None,
                'rmse': None,
                'mape': None,
                'median_ae': None,
                'r2_score': None,
                'direction_accuracy': None,
                'percentile_errors': None
            }
            mae_before = rmse_before = mape_before = median_ae_before = r2_score_before = direction_accuracy_before = None
            percentile_errors_before = None
        
        # エラー補正を適用
        valid_corrected = None  # 初期化
        if apply_error_correction_flag and len(valid_predictions) > error_window_size:
            print("\n" + "="*70)
            print("APPLYING ERROR CORRECTION")
            print("="*70)
            print(f"Error Window Size: {error_window_size}")
            print(f"Using past prediction errors to correct future predictions...")
            
            corrected_predictions = apply_error_correction(
                predictions,
                actual_prices,
                error_window_size=error_window_size,
                min_samples=10
            )
            
            # 補正後の予測を評価
            valid_corrected = corrected_predictions[valid_mask]
            
            print("\n" + "="*70)
            print("PREDICTION ACCURACY METRICS (AFTER ERROR CORRECTION)")
            print("="*70)
            
            eval_metrics_after = evaluate_predictions(
                valid_corrected,
                valid_actuals,
                current_prices,
                output_dir=output_dir,
                symbol=f"{symbol}_after_correction",
                trades_df=None,  # 後で設定
                df=test_df,
                momentum_intensity_strategy=momentum_intensity_strategy
            )
            
            mae_after = eval_metrics_after['mae']
            rmse_after = eval_metrics_after['rmse']
            mape_after = eval_metrics_after['mape']
            median_ae_after = eval_metrics_after['median_ae']
            r2_score_after = eval_metrics_after['r2_score']
            direction_accuracy_after = eval_metrics_after['direction_accuracy']
            percentile_errors_after = eval_metrics_after['percentile_errors']
            
            print(f"Mean Absolute Error (MAE): {mae_after:,.0f} JPY")
            print(f"Root Mean Squared Error (RMSE): {rmse_after:,.0f} JPY")
            print(f"Mean Absolute Percentage Error (MAPE): {mape_after:.2f}%")
            print(f"Median Absolute Error: {median_ae_after:,.0f} JPY")
            print(f"R² Score: {r2_score_after:.4f}")
            print(f"Direction Accuracy: {direction_accuracy_after:.2f}%")
            print(f"\nPercentile Errors:")
            print(f"  P25: {percentile_errors_after['p25']:,.0f} JPY")
            print(f"  P50 (Median): {percentile_errors_after['p50']:,.0f} JPY")
            print(f"  P75: {percentile_errors_after['p75']:,.0f} JPY")
            print(f"  P90: {percentile_errors_after['p90']:,.0f} JPY")
            print(f"  P95: {percentile_errors_after['p95']:,.0f} JPY")
            print(f"  P99: {percentile_errors_after['p99']:,.0f} JPY")
            
            # 改善率を表示
            print("\n" + "="*70)
            print("IMPROVEMENT FROM ERROR CORRECTION")
            print("="*70)
            if mae_before and mae_after:
                mae_improvement = (mae_before - mae_after) / mae_before * 100
                print(f"MAE Improvement: {mae_improvement:+.2f}% ({mae_before:,.0f} → {mae_after:,.0f} JPY)")
            if rmse_before and rmse_after:
                rmse_improvement = (rmse_before - rmse_after) / rmse_before * 100
                print(f"RMSE Improvement: {rmse_improvement:+.2f}% ({rmse_before:,.0f} → {rmse_after:,.0f} JPY)")
            if mape_before and mape_after:
                mape_improvement = (mape_before - mape_after) / mape_before * 100
                print(f"MAPE Improvement: {mape_improvement:+.2f}% ({mape_before:.2f}% → {mape_after:.2f}%)")
            if r2_score_before and r2_score_after:
                r2_improvement = r2_score_after - r2_score_before
                print(f"R² Score Improvement: {r2_improvement:+.4f} ({r2_score_before:.4f} → {r2_score_after:.4f})")
            if direction_accuracy_before and direction_accuracy_after:
                direction_improvement = direction_accuracy_after - direction_accuracy_before
                print(f"Direction Accuracy Improvement: {direction_improvement:+.2f}% ({direction_accuracy_before:.2f}% → {direction_accuracy_after:.2f}%)")
            
            # 補正後の予測を使用
            predictions = corrected_predictions
            eval_metrics = eval_metrics_after
            mae = mae_after
            rmse = rmse_after
            mape = mape_after
            median_ae = median_ae_after
            r2_score = r2_score_after
            direction_accuracy = direction_accuracy_after
            percentile_errors = percentile_errors_after
        else:
            # 補正なしの場合
            if not apply_error_correction_flag:
                print("\nError correction is disabled.")
            else:
                print(f"\nError correction skipped: insufficient data (need at least {error_window_size} samples, got {len(valid_predictions)})")
            
            eval_metrics = eval_metrics_before
            mae = mae_before
            rmse = rmse_before
            mape = mape_before
            median_ae = median_ae_before
            r2_score = r2_score_before
            direction_accuracy = direction_accuracy_before
            percentile_errors = percentile_errors_before
        
        print("="*70 + "\n")
        
        # 予測のみを評価する場合
        if evaluate_prediction_only:
            return {
                'status': 'success',
                'symbol': symbol,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'prediction_metrics': eval_metrics if len(valid_predictions) > 0 else {
                    'mae': None,
                    'rmse': None,
                    'mape': None,
                    'direction_accuracy': None
                }
            }
        
        # モメンタム強度を取得（利用可能な場合）
        momentum_intensity_pred = None
        if momentum_intensity_strategy is not None:
            try:
                print("Calculating momentum intensity...")
                momentum_intensity_pred = momentum_intensity_strategy.predict_intensity(test_df)
                print(f"Momentum intensity calculated for {len(momentum_intensity_pred)} timestamps")
            except Exception as e:
                print(f"Warning: Failed to calculate momentum intensity: {e}")
                print("Continuing with price prediction only...")
        
        # 予測からシグナルを生成（AND条件：価格予測とモメンタム強度が同じ方向を示す場合のみ取引）
        print("Generating trading signals from predictions and momentum intensity (AND condition)...")
        print("  - Momentum threshold: ±4")
        print("  - Max prediction error: 0.5%")
        signals, confidence = generate_signals_from_predictions(
            test_df,
            predictions,
            price_change_threshold=price_change_threshold,
            momentum_intensity=momentum_intensity_pred,
            momentum_threshold=4,  # モメンタム強度の閾値（±4以上でシグナル）
            use_momentum=(momentum_intensity_pred is not None),
            max_prediction_error_pct=0.5  # 予測誤差が0.5%を超える場合は取引しない
        )
        
        # バックテスト
        print("Running backtest...")
        if use_limit_orders:
            print(f"Using limit orders (timeout: {limit_order_timeout_seconds}s)")
            print("Loading execution history...")
            exch_sim_loader = ExchSimDataLoader()
            executions_df = exch_sim_loader.load_executions(symbol, test_df.index[0], test_df.index[-1])
            print(f"Loaded {len(executions_df)} executions")
            backtester = LimitOrderBacktester(
                limit_order_timeout_seconds=limit_order_timeout_seconds,
                executions_df=executions_df
            )
        else:
            print("Using market orders")
            backtester = Backtester()
        
        # 損切・利益確定の設定を表示
        if stop_loss is not None:
            print(f"Stop loss: {stop_loss:.0f} JPY (LIMIT order)")
        if take_profit is not None:
            print(f"Take profit: {take_profit:.0f} JPY (LIMIT order)")
        if fixed_quantity is not None:
            print(f"Fixed trade quantity: {fixed_quantity:.6f} BTC")
        else:
            print("Trade quantity: 10% of capital")
        
        # 信頼度の閾値（指定されていない場合はデフォルト値を使用）
        conf_threshold = confidence_threshold if confidence_threshold is not None else strategy.backtest_config.CONFIDENCE_THRESHOLD
        
        if use_limit_orders:
            metrics = backtester.run(
                test_df,
                signals,
                confidence,
                confidence_threshold=conf_threshold,
                executions_df=executions_df,
                stop_loss=stop_loss,
                take_profit=take_profit,
                fixed_quantity=fixed_quantity
            )
        else:
            metrics = backtester.run(
                test_df,
                signals,
                confidence,
                confidence_threshold=conf_threshold,
                stop_loss=stop_loss,
                take_profit=take_profit,
                fixed_quantity=fixed_quantity
            )
        
        # トレード情報を取得して、補正後のCSVファイルを更新
        if apply_error_correction_flag and output_dir and valid_corrected is not None:
            trades_df = backtester.get_trades()
            if len(trades_df) > 0:
                # 補正後のCSVファイルを再生成（トレード情報を含む）
                eval_metrics_after_with_trades = evaluate_predictions(
                    valid_corrected,
                    valid_actuals,
                    current_prices,
                    output_dir=output_dir,
                    symbol=f"{symbol}_after_correction",
                    trades_df=trades_df,
                    df=test_df,
                    momentum_intensity_strategy=momentum_intensity_strategy
                )
        
        # 結果表示
        print("\n" + "="*70)
        print("PRICE PREDICTION BACKTEST RESULTS")
        print("="*70)
        print(f"Symbol: {symbol}")
        print(f"Test Period: {test_df.index[0]} to {test_df.index[-1]}")
        print(f"Test Samples: {len(test_df)}")
        print(f"\nPrediction Metrics:")
        if len(valid_predictions) > 0:
            print(f"  MAE: {mae:,.0f} JPY")
            print(f"  RMSE: {rmse:,.0f} JPY")
            print(f"  MAPE: {mape:.2f}%")
            print(f"  Direction Accuracy: {direction_accuracy:.2f}%")
        print(f"\nTrading Performance Metrics:")
        print(f"  Total Return: {metrics.get('total_return', 0):.2f}%")
        print(f"  Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}")
        print(f"  Max Drawdown: {metrics.get('max_drawdown', 0):.2f}%")
        print(f"  Final Equity: {metrics.get('final_equity', 0):,.0f} JPY")
        print(f"\nTrading Statistics:")
        print(f"  Total Trades: {metrics.get('total_trades', 0)}")
        print(f"  Win Rate: {metrics.get('win_rate', 0):.2f}%")
        print(f"  Avg Win: {metrics.get('avg_win', 0):,.0f} JPY")
        print(f"  Avg Loss: {metrics.get('avg_loss', 0):,.0f} JPY")
        print(f"  Profit Factor: {metrics.get('profit_factor', 0):.2f}")
        print(f"\nCost Analysis:")
        print(f"  Avg Spread: {metrics.get('avg_spread_bps', 0):.2f} bps ({metrics.get('avg_spread_pct', 0):.4f}%)")
        print(f"  Total Commission: {metrics.get('total_commission', 0):,.0f} JPY")
        print(f"  Total Slippage Cost: {metrics.get('total_slippage_cost', 0):,.0f} JPY")
        print(f"  Avg Cost per Round Trip: {metrics.get('avg_cost_per_round_trip_pct', 0):.4f}%")
        print("="*70 + "\n")
        
        # トレード履歴の表示
        if show_trades:
            trades_df = backtester.get_trades()
            if len(trades_df) > 0:
                print("\n" + "="*90)
                print("TRADE HISTORY")
                print("="*90)
                
                # 時系列順にソート
                trades_df = trades_df.sort_index()
                
                # 予測価格と実際の価格の情報も取得
                equity_curve_df = backtester.get_equity_curve()
                
                # ヘッダー
                print(f"\n{'#':<4} {'Timestamp':<20} {'Action':<12} {'Price':<12} {'Quantity':<12} {'PNL':<15} {'Capital':<12}")
                print("-"*90)
                
                trade_num = 1
                open_positions = 0
                entry_trades = {}  # エントリートレードを記録
                
                for idx, row in trades_df.iterrows():
                    timestamp = row['timestamp']
                    if isinstance(timestamp, pd.Timestamp):
                        timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        timestamp_str = str(timestamp)[:19]
                    
                    action = row['action']
                    # LimitOrderBacktesterの場合はexecution_price、Backtesterの場合はprice
                    price = row.get('execution_price', row.get('price', 0))
                    quantity = row.get('quantity', 0)
                    capital = row.get('capital', 0)
                    
                    # PNLの表示
                    pnl_str = "-"
                    if 'pnl' in row and pd.notna(row['pnl']):
                        pnl = row['pnl']
                        pnl_str = f"{pnl:>14,.0f} JPY"
                        if pnl > 0:
                            pnl_str = f"+{pnl:>13,.0f} JPY"
                    
                    print(f"{trade_num:<4} {timestamp_str:<20} {action:<12} {price:>11,.0f} {quantity:>11.6f} {pnl_str:<15} {capital:>11,.0f}")
                    
                    # 予測価格と実際の価格の情報を表示
                    if action in ['BUY', 'SHORT']:
                        # エントリー時の予測価格を取得
                        if idx in predictions.index:
                            pred_price = predictions.loc[idx]
                            # 実際の価格（prediction_horizon秒後）を取得
                            actual_idx = test_df.index[test_df.index.get_loc(idx) + prediction_horizon] if test_df.index.get_loc(idx) + prediction_horizon < len(test_df) else None
                            if actual_idx and actual_idx in test_df.index:
                                if 'exec_price_all' in test_df.columns:
                                    actual_price = test_df.loc[actual_idx, 'exec_price_all']
                                else:
                                    actual_price = test_df.loc[actual_idx, 'mid_price']
                                current_price = test_df.loc[idx, 'mid_price']
                                
                                pred_change_pct = (pred_price - current_price) / current_price * 100
                                actual_change_pct = (actual_price - current_price) / current_price * 100
                                
                                print(f"     {'Predicted Price:':<20} {pred_price:>11,.0f} JPY ({pred_change_pct:>+6.2f}%)")
                                print(f"     {'Actual Price (1min later):':<20} {actual_price:>11,.0f} JPY ({actual_change_pct:>+6.2f}%)")
                                print(f"     {'Prediction Error:':<20} {pred_price - actual_price:>11,.0f} JPY")
                        
                        entry_trades[trade_num] = {
                            'timestamp': idx,
                            'action': action,
                            'entry_price': price,
                            'quantity': quantity
                        }
                        open_positions += 1
                    elif action in ['SELL', 'COVER_SHORT']:
                        # エグジット時の情報を表示
                        if trade_num in entry_trades:
                            entry_info = entry_trades[trade_num]
                            entry_price = entry_info['entry_price']
                            exit_price = price
                            price_diff = exit_price - entry_price if entry_info['action'] == 'BUY' else entry_price - exit_price
                            price_diff_pct = price_diff / entry_price * 100
                            
                            print(f"     {'Entry Price:':<20} {entry_price:>11,.0f} JPY")
                            print(f"     {'Exit Price:':<20} {exit_price:>11,.0f} JPY")
                            print(f"     {'Price Change:':<20} {price_diff:>11,.0f} JPY ({price_diff_pct:>+6.2f}%)")
                        
                        open_positions -= 1
                        trade_num += 1
                    
                    print()  # 空行を追加
                
                print("-"*90)
                
                # トレードサマリー
                print("\n" + "="*90)
                print("TRADE SUMMARY")
                print("="*90)
                
                # 各トレードの詳細を分析
                completed_trades = []
                for i in range(1, trade_num):
                    if i in entry_trades:
                        entry_info = entry_trades[i]
                        # 対応するエグジットを見つける
                        exit_rows = trades_df[(trades_df.index > entry_info['timestamp']) & 
                                            (trades_df['action'].isin(['SELL', 'COVER_SHORT']))]
                        if len(exit_rows) > 0:
                            exit_row = exit_rows.iloc[0]
                            entry_price = entry_info['entry_price']
                            exit_price = exit_row.get('execution_price', exit_row.get('price', 0))
                            pnl = exit_row.get('pnl', 0) if 'pnl' in exit_row and pd.notna(exit_row['pnl']) else 0
                            
                            completed_trades.append({
                                'entry_time': entry_info['timestamp'],
                                'exit_time': exit_row.name,
                                'entry_price': entry_price,
                                'exit_price': exit_price,
                                'pnl': pnl,
                                'action': entry_info['action']
                            })
                
                if len(completed_trades) > 0:
                    print(f"\n{'Trade':<6} {'Entry Time':<20} {'Exit Time':<20} {'Entry Price':<15} {'Exit Price':<15} {'PNL':<15} {'Return %':<10}")
                    print("-"*90)
                    total_pnl = 0.0
                    for i, trade in enumerate(completed_trades, 1):
                        entry_time_str = trade['entry_time'].strftime('%Y-%m-%d %H:%M:%S') if isinstance(trade['entry_time'], pd.Timestamp) else str(trade['entry_time'])[:19]
                        exit_time_str = trade['exit_time'].strftime('%Y-%m-%d %H:%M:%S') if isinstance(trade['exit_time'], pd.Timestamp) else str(trade['exit_time'])[:19]
                        return_pct = (trade['pnl'] / (trade['entry_price'] * trade.get('quantity', 0.01))) * 100 if trade.get('quantity', 0) > 0 else 0
                        pnl_str = f"{trade['pnl']:>14,.0f}" if trade['pnl'] != 0 else "-"
                        print(f"{i:<6} {entry_time_str:<20} {exit_time_str:<20} {trade['entry_price']:>14,.0f} {trade['exit_price']:>14,.0f} {pnl_str:<15} {return_pct:>9.2f}%")
                        # PNLの合計を計算
                        if trade['pnl'] != 0:
                            total_pnl += trade['pnl']
                    
                    # PNL合計を表示（trades_dfからも確認）
                    exit_trades = trades_df[trades_df['action'].isin(['SELL', 'COVER_SHORT'])]
                    if 'pnl' in exit_trades.columns:
                        total_pnl_from_df = exit_trades['pnl'].sum()
                        # より正確な値を使用（trades_dfから計算）
                        total_pnl = total_pnl_from_df if not pd.isna(total_pnl_from_df) else total_pnl
                    
                    print("-"*90)
                    total_pnl_str = f"{total_pnl:>14,.0f} JPY"
                    print(f"{'Total PNL:':<66} {total_pnl_str}")
                
                print("="*90 + "\n")
            else:
                print("\nNo trades executed.\n")
        
        return {
            'status': 'success',
            'symbol': symbol,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'prediction_metrics': eval_metrics if len(valid_predictions) > 0 else {
                'mae': None,
                'rmse': None,
                'mape': None,
                'direction_accuracy': None
            },
            'trading_metrics': metrics
        }
        
    except Exception as e:
        print(f"\nBacktest failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error': str(e)
        }
    finally:
        loader.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Run price prediction backtest')
    parser.add_argument('--symbol', type=str, default='G_FX_BTCJPY', help='Symbol to backtest')
    parser.add_argument('--days', type=float, default=1, help='Number of days to backtest')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--show-trades', action='store_true', help='Show detailed trade history')
    parser.add_argument('--timeframes', type=str, help='Comma-separated timeframes in seconds (e.g., "60,300,3600" for 1min,5min,1hour)')
    parser.add_argument('--prediction-horizon', type=int, default=60, help='Prediction horizon in seconds (default=60 for 1 minute)')
    parser.add_argument('--price-change-threshold', type=float, default=0.0001, help='Price change threshold for signal generation (default=0.0001=0.01%%)')
    parser.add_argument('--confidence-threshold', type=float, help='Confidence threshold for trading (default=0.7)')
    parser.add_argument('--use-limit-orders', action='store_true', help='Use limit orders (BUY at BID, SELL at ASK)')
    parser.add_argument('--limit-order-timeout', type=int, default=60, help='Limit order timeout in seconds (default=60)')
    parser.add_argument('--evaluate-prediction-only', action='store_true', help='Evaluate prediction accuracy only (no trading)')
    parser.add_argument('--output-dir', type=str, help='Output directory for evaluation results (plots and CSV files)')
    parser.add_argument('--no-error-correction', action='store_true', help='Disable error correction using past prediction errors')
    parser.add_argument('--error-window-size', type=int, default=100, help='Window size for error correction (default=100)')
    parser.add_argument('--stop-loss', type=float, help='Stop loss threshold in JPY (close position with LIMIT order when loss exceeds this value)')
    parser.add_argument('--take-profit', type=float, help='Take profit threshold in JPY (close position with LIMIT order when profit exceeds this value)')
    parser.add_argument('--fixed-quantity', type=float, help='Fixed trade quantity in BTC (e.g., 0.001 for minimum trade size)')
    parser.add_argument('--model-name', type=str, help='Model name for saving (default: uses symbol name)')
    
    args = parser.parse_args()
    
    start_date = None
    end_date = None
    
    if args.start_date:
        try:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
            except ValueError:
                print(f"Error: Invalid start date format: {args.start_date}")
                sys.exit(1)
    
    if args.end_date:
        try:
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
            except ValueError:
                print(f"Error: Invalid end date format: {args.end_date}")
                sys.exit(1)
    elif args.days:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=args.days)
    
    # タイムフレームのパース
    timeframes = None
    if args.timeframes:
        try:
            timeframes = [int(tf.strip()) for tf in args.timeframes.split(',')]
            if len(timeframes) < 2:
                print("Error: At least 2 timeframes are required")
                sys.exit(1)
        except ValueError:
            print(f"Error: Invalid timeframes format: {args.timeframes}")
            print("Expected format: comma-separated integers (e.g., '60,300,3600')")
            sys.exit(1)
    
    result = run_price_prediction_backtest(
        symbol=args.symbol,
        start_date=start_date,
        end_date=end_date,
        show_trades=args.show_trades,
        timeframes=timeframes,
        prediction_horizon=args.prediction_horizon,
        price_change_threshold=args.price_change_threshold,
        confidence_threshold=args.confidence_threshold,
        use_limit_orders=args.use_limit_orders,
        limit_order_timeout_seconds=args.limit_order_timeout,
        evaluate_prediction_only=args.evaluate_prediction_only,
        output_dir=args.output_dir,
        apply_error_correction_flag=not args.no_error_correction,
        error_window_size=args.error_window_size,
        stop_loss=args.stop_loss,
        take_profit=args.take_profit,
        fixed_quantity=args.fixed_quantity,
        model_name=args.model_name
    )
    
    if result['status'] == 'success':
        print("\nPrice prediction backtest completed successfully!")
    else:
        print(f"\nPrice prediction backtest failed: {result.get('error', 'Unknown error')}")
        sys.exit(1)

