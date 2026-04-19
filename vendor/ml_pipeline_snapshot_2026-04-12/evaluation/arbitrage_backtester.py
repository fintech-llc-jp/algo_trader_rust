"""
Arbitrage Backtesting Module
アービトラージ戦略用のバックテスター
2つのシンボル間の同時取引をシミュレート
"""
import pandas as pd
import numpy as np
from typing import Dict, List
from datetime import datetime

from config.settings import BacktestConfig


class ArbitrageBacktester:
    """
    アービトラージ戦略用のバックテスター
    2つのシンボル（G_FX_BTCJPYとB_FX_BTCJPY）間の同時取引をシミュレート
    """
    
    def __init__(
        self,
        initial_capital: float = None,
        commission_rate: float = None,
        slippage_bps: float = None
    ):
        config = BacktestConfig()
        self.initial_capital = initial_capital or config.INITIAL_CAPITAL
        self.commission_rate = commission_rate or config.COMMISSION_RATE
        self.slippage_bps = slippage_bps or config.SLIPPAGE_BPS
        
        self.trades = []
        self.equity_curve = []
    
    def run(
        self,
        df: pd.DataFrame,
        signals: pd.Series,
        confidence: pd.Series,
        symbol1: str = "G_FX_BTCJPY",
        symbol2: str = "B_FX_BTCJPY",
        confidence_threshold: float = None,
        zscore_exit_threshold: float = 0.5,
        max_hold_seconds: int = 3600
    ) -> Dict:
        """
        アービトラージ戦略のバックテスト実行
        
        Args:
            df: 2つのシンボルの統合データ（spread, G_FX_BTCJPY_mid_price, B_FX_BTCJPY_mid_priceを含む）
            signals: シグナル (-1: SHORT_G_LONG_B, 0: HOLD, 1: LONG_G_SHORT_B)
            confidence: 信頼度 (0.0 - 1.0)
            symbol1: 第1シンボル（デフォルト: G_FX_BTCJPY）
            symbol2: 第2シンボル（デフォルト: B_FX_BTCJPY）
            confidence_threshold: 取引を実行する最小信頼度
            zscore_exit_threshold: エグジットするZスコアの閾値（デフォルト0.5）
            max_hold_seconds: 最大保持時間（秒、デフォルト3600秒=1時間）
        
        Returns:
            パフォーマンス指標の辞書
        """
        config = BacktestConfig()
        confidence_threshold = confidence_threshold or config.CONFIDENCE_THRESHOLD
        
        # リセット
        self.trades = []
        self.equity_curve = []
        
        capital = self.initial_capital
        position = None  # {'direction': 'long_g_short_b' or 'short_g_long_b', 'quantity': float, 'entry_time': timestamp, 'entry_spread': float, 'entry_zscore': float}
        
        symbol1_price_col = f'{symbol1}_mid_price'
        symbol2_price_col = f'{symbol2}_mid_price'
        spread_col = 'spread'
        zscore_col = 'spread_zscore'
        
        # 価格カラムが存在するか確認
        if symbol1_price_col not in df.columns or symbol2_price_col not in df.columns:
            raise ValueError(f"Price columns not found: {symbol1_price_col}, {symbol2_price_col}")
        
        if spread_col not in df.columns:
            raise ValueError(f"Spread column not found: {spread_col}")
        
        for idx, row in df.iterrows():
            signal = signals.loc[idx] if idx in signals.index else 0
            conf = confidence.loc[idx] if idx in confidence.index else 0.0
            
            price1 = row[symbol1_price_col]
            price2 = row[symbol2_price_col]
            spread = row[spread_col]
            zscore = row.get(zscore_col, 0.0) if zscore_col in df.columns else 0.0
            
            # ポジションがない場合
            if position is None:
                # 信頼度が閾値以上で、シグナルがある場合のみエントリー
                if conf >= confidence_threshold and signal != 0:
                    # エントリー
                    position = self._enter_position(
                        signal, price1, price2, spread, zscore, idx, capital
                    )
                    
                    if position:
                        capital = position['capital_after_entry']
                        self.trades.append({
                            'timestamp': idx,
                            'action': 'ENTER',
                            'direction': position['direction'],
                            'price1': price1,
                            'price2': price2,
                            'spread': spread,
                            'zscore': zscore,
                            'quantity': position['quantity'],
                            'capital': capital
                        })
            
            # ポジションがある場合
            else:
                # エグジット条件をチェック
                should_exit = False
                exit_reason = None
                
                # 1. Zスコアが閾値以下になった（収束）
                if abs(zscore) <= zscore_exit_threshold:
                    should_exit = True
                    exit_reason = 'convergence'
                
                # 2. 最大保持時間に達した
                hold_seconds = (idx - position['entry_time']).total_seconds()
                if hold_seconds >= max_hold_seconds:
                    should_exit = True
                    exit_reason = 'max_hold_time'
                
                # 3. 逆方向のシグナル（信頼度が高い場合）
                if signal != 0 and signal != (1 if position['direction'] == 'long_g_short_b' else -1):
                    if conf >= confidence_threshold * 1.5:  # より高い信頼度が必要
                        should_exit = True
                        exit_reason = 'reverse_signal'
                
                if should_exit:
                    # エグジット
                    pnl, commission = self._exit_position(
                        position, price1, price2, spread, idx
                    )
                    
                    capital += pnl
                    
                    self.trades.append({
                        'timestamp': idx,
                        'action': 'EXIT',
                        'direction': position['direction'],
                        'price1': price1,
                        'price2': price2,
                        'spread': spread,
                        'zscore': zscore,
                        'pnl': pnl,
                        'commission': commission,
                        'hold_seconds': hold_seconds,
                        'exit_reason': exit_reason,
                        'capital': capital
                    })
                    
                    position = None
            
            # 資金曲線を記録
            current_equity = capital
            if position:
                # 現在のポジションの評価損益を計算
                current_pnl = self._calculate_unrealized_pnl(position, price1, price2, spread)
                current_equity += current_pnl
            
            self.equity_curve.append({
                'timestamp': idx,
                'equity': current_equity,
                'position': position['direction'] if position else None,
                'spread': spread,
                'zscore': zscore
            })
        
        # パフォーマンス指標の計算
        metrics = self._calculate_performance_metrics()
        
        return metrics
    
    def _enter_position(
        self,
        signal: int,
        price1: float,
        price2: float,
        spread: float,
        zscore: float,
        timestamp: datetime,
        capital: float
    ) -> Dict:
        """
        ポジションをエントリー
        
        Args:
            signal: 1=LONG_G_SHORT_B, -1=SHORT_G_LONG_B
            price1: 第1シンボルの価格
            price2: 第2シンボルの価格
            spread: スプレッド
            zscore: Zスコア
            timestamp: タイムスタンプ
            capital: 現在の資金
        
        Returns:
            ポジション情報の辞書
        """
        # ポジションサイズ（資金の10%）
        position_value = capital * 0.1
        
        # スリッページを考慮した実行価格
        if signal == 1:  # LONG_G_SHORT_B
            exec_price1 = price1 * (1 + self.slippage_bps / 10000)
            exec_price2 = price2 * (1 - self.slippage_bps / 10000)
            direction = 'long_g_short_b'
        else:  # SHORT_G_LONG_B
            exec_price1 = price1 * (1 - self.slippage_bps / 10000)
            exec_price2 = price2 * (1 + self.slippage_bps / 10000)
            direction = 'short_g_long_b'
        
        # 数量（両方のシンボルで同じ数量）
        quantity = position_value / max(exec_price1, exec_price2)
        
        # 手数料（両側）
        commission = position_value * self.commission_rate * 2
        
        return {
            'direction': direction,
            'quantity': quantity,
            'entry_time': timestamp,
            'entry_price1': exec_price1,
            'entry_price2': exec_price2,
            'entry_spread': spread,
            'entry_zscore': zscore,
            'capital_after_entry': capital - commission
        }
    
    def _exit_position(
        self,
        position: Dict,
        price1: float,
        price2: float,
        spread: float,
        timestamp: datetime
    ) -> tuple:
        """
        ポジションをエグジット
        
        Returns:
            (pnl, commission)
        """
        # スリッページを考慮した実行価格
        if position['direction'] == 'long_g_short_b':
            # Gを売り、Bを買い戻す
            exec_price1 = price1 * (1 - self.slippage_bps / 10000)
            exec_price2 = price2 * (1 + self.slippage_bps / 10000)
        else:  # short_g_long_b
            # Gを買い戻し、Bを売る
            exec_price1 = price1 * (1 + self.slippage_bps / 10000)
            exec_price2 = price2 * (1 - self.slippage_bps / 10000)
        
        quantity = position['quantity']
        
        # エントリー時の価値
        entry_value1 = position['entry_price1'] * quantity
        entry_value2 = position['entry_price2'] * quantity
        
        # エグジット時の価値
        exit_value1 = exec_price1 * quantity
        exit_value2 = exec_price2 * quantity
        
        # 損益計算
        if position['direction'] == 'long_g_short_b':
            # Gを買ってBを売った -> Gを売ってBを買い戻す
            pnl = (exit_value1 - entry_value1) + (entry_value2 - exit_value2)
        else:  # short_g_long_b
            # Gを売ってBを買った -> Gを買い戻してBを売る
            pnl = (entry_value1 - exit_value1) + (exit_value2 - entry_value2)
        
        # 手数料（両側）
        position_value = max(exit_value1, exit_value2)
        commission = position_value * self.commission_rate * 2
        
        pnl -= commission
        
        return pnl, commission
    
    def _calculate_unrealized_pnl(
        self,
        position: Dict,
        price1: float,
        price2: float,
        spread: float
    ) -> float:
        """
        未実現損益を計算
        """
        quantity = position['quantity']
        
        if position['direction'] == 'long_g_short_b':
            # Gを買ってBを売った -> 現在の価値
            current_value1 = price1 * quantity
            current_value2 = price2 * quantity
            entry_value1 = position['entry_price1'] * quantity
            entry_value2 = position['entry_price2'] * quantity
            unrealized_pnl = (current_value1 - entry_value1) + (entry_value2 - current_value2)
        else:  # short_g_long_b
            # Gを売ってBを買った -> 現在の価値
            current_value1 = price1 * quantity
            current_value2 = price2 * quantity
            entry_value1 = position['entry_price1'] * quantity
            entry_value2 = position['entry_price2'] * quantity
            unrealized_pnl = (entry_value1 - current_value1) + (current_value2 - entry_value2)
        
        return unrealized_pnl
    
    def _calculate_performance_metrics(self) -> Dict:
        """
        パフォーマンス指標の計算
        """
        if not self.equity_curve:
            return {
                'total_return': 0.0,
                'sharpe_ratio': 0.0,
                'max_drawdown': 0.0,
                'final_equity': self.initial_capital,
                'total_trades': 0,
                'win_rate': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0
            }
        
        equity_df = pd.DataFrame(self.equity_curve)
        equity_df.set_index('timestamp', inplace=True)
        
        # 総リターン
        final_equity = equity_df['equity'].iloc[-1]
        total_return = ((final_equity - self.initial_capital) / self.initial_capital) * 100
        
        # リターン系列
        equity_df['returns'] = equity_df['equity'].pct_change()
        returns = equity_df['returns'].dropna()
        
        # シャープレシオ（年率換算）
        if len(returns) > 0 and returns.std() > 0:
            sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252 * 24 * 3600)  # 年率換算
        else:
            sharpe_ratio = 0.0
        
        # 最大ドローダウン
        equity_df['cummax'] = equity_df['equity'].cummax()
        equity_df['drawdown'] = ((equity_df['equity'] - equity_df['cummax']) / equity_df['cummax']) * 100
        max_drawdown = equity_df['drawdown'].min()
        
        # 取引統計
        exit_trades = [t for t in self.trades if t['action'] == 'EXIT']
        total_trades = len(exit_trades)
        
        if total_trades > 0:
            pnls = [t['pnl'] for t in exit_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            
            win_rate = (len(wins) / total_trades) * 100 if total_trades > 0 else 0.0
            avg_win = np.mean(wins) if wins else 0.0
            avg_loss = abs(np.mean(losses)) if losses else 0.0
            
            total_win = sum(wins) if wins else 0.0
            total_loss = abs(sum(losses)) if losses else 0.0
            profit_factor = total_win / total_loss if total_loss > 0 else 0.0
        else:
            win_rate = 0.0
            avg_win = 0.0
            avg_loss = 0.0
            profit_factor = 0.0
        
        return {
            'total_return': total_return,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'final_equity': final_equity,
            'total_trades': total_trades,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor
        }

