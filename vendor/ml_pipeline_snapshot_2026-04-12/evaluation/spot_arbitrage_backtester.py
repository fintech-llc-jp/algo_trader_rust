"""
Spot Arbitrage Backtesting Module
現物アービトラージ戦略用のバックテスター
現物は買いからしか入れないという制約を考慮
"""
import pandas as pd
import numpy as np
from typing import Dict
from datetime import datetime

from config.settings import BacktestConfig


class SpotArbitrageBacktester:
    """
    現物アービトラージ戦略用のバックテスター
    FXと現物のアービトラージ（現物は買いからしか入れない）
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
        fx_symbol: str = "G_FX_BTCJPY",
        spot_symbol: str = "B_FX_BTCJPY",
        confidence_threshold: float = None,
        zscore_exit_threshold: float = 0.5,
        max_hold_seconds: int = 3600
    ) -> Dict:
        """
        現物アービトラージ戦略のバックテスト実行
        
        Args:
            df: 2つのシンボルの統合データ（spread, G_FX_BTCJPY_mid_price, B_FX_BTCJPY_mid_priceを含む）
            signals: シグナル (0: HOLD, 1: LONG_SPOT_SHORT_FX)
            confidence: 信頼度 (0.0 - 1.0)
            fx_symbol: FXシンボル（デフォルト: G_FX_BTCJPY）
            spot_symbol: 現物シンボル（デフォルト: B_FX_BTCJPY）
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
        position = None  # {'fx_position': float, 'spot_position': float, 'entry_time': timestamp, 'entry_spread': float, 'entry_zscore': float}
        
        fx_price_col = f'{fx_symbol}_mid_price'
        spot_price_col = f'{spot_symbol}_mid_price'
        spread_col = 'spread'
        zscore_col = 'spread_zscore'
        
        # 価格カラムが存在するか確認
        if fx_price_col not in df.columns or spot_price_col not in df.columns:
            raise ValueError(f"Price columns not found: {fx_price_col}, {spot_price_col}")
        
        if spread_col not in df.columns:
            raise ValueError(f"Spread column not found: {spread_col}")
        
        for idx, row in df.iterrows():
            signal = signals.loc[idx] if idx in signals.index else 0
            conf = confidence.loc[idx] if idx in confidence.index else 0.0
            
            fx_price = row[fx_price_col]
            spot_price = row[spot_price_col]
            spread = row[spread_col]
            zscore = row.get(zscore_col, 0.0) if zscore_col in df.columns else 0.0
            
            # ポジションがない場合
            if position is None:
                # 信頼度が閾値以上で、シグナルがある場合のみエントリー
                if conf >= confidence_threshold and signal == 1:  # LONG_SPOT_SHORT_FX
                    # エントリー: 現物を買い、FXを売る
                    position = self._enter_position(
                        fx_price, spot_price, spread, zscore, idx, capital
                    )
                    
                    if position:
                        capital = position['capital_after_entry']
                        self.trades.append({
                            'timestamp': idx,
                            'action': 'ENTER',
                            'fx_position': position['fx_position'],
                            'spot_position': position['spot_position'],
                            'fx_price': fx_price,
                            'spot_price': spot_price,
                            'spread': spread,
                            'zscore': zscore,
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
                if signal == 0 and conf >= confidence_threshold * 1.5:
                    should_exit = True
                    exit_reason = 'reverse_signal'
                
                if should_exit:
                    # エグジット: 現物を売り、FXを買い戻す
                    pnl, commission = self._exit_position(
                        position, fx_price, spot_price, spread, idx
                    )
                    
                    capital += pnl
                    
                    self.trades.append({
                        'timestamp': idx,
                        'action': 'EXIT',
                        'fx_position': position['fx_position'],
                        'spot_position': position['spot_position'],
                        'fx_price': fx_price,
                        'spot_price': spot_price,
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
                current_pnl = self._calculate_unrealized_pnl(position, fx_price, spot_price, spread)
                current_equity += current_pnl
            
            self.equity_curve.append({
                'timestamp': idx,
                'equity': current_equity,
                'fx_position': position['fx_position'] if position else 0,
                'spot_position': position['spot_position'] if position else 0,
                'spread': spread,
                'zscore': zscore
            })
        
        # パフォーマンス指標の計算
        metrics = self._calculate_performance_metrics()
        
        return metrics
    
    def _enter_position(
        self,
        fx_price: float,
        spot_price: float,
        spread: float,
        zscore: float,
        timestamp: datetime,
        capital: float
    ) -> Dict:
        """
        ポジションをエントリー（現物を買い、FXを売る）
        
        Args:
            fx_price: FX価格
            spot_price: 現物価格
            spread: スプレッド（FX - 現物）
            zscore: Zスコア
            timestamp: タイムスタンプ
            capital: 現在の資金
        
        Returns:
            ポジション情報の辞書
        """
        # ポジションサイズ（資金の10%）
        position_value = capital * 0.1
        
        # スリッページを考慮した実行価格
        # 現物を買う
        exec_spot_price = spot_price * (1 + self.slippage_bps / 10000)
        # FXを売る
        exec_fx_price = fx_price * (1 - self.slippage_bps / 10000)
        
        # 数量（両方のシンボルで同じ数量）
        quantity = position_value / max(exec_spot_price, exec_fx_price)
        
        # 手数料（両側）
        commission = position_value * self.commission_rate * 2
        
        return {
            'fx_position': -quantity,  # FXはショート（負の値）
            'spot_position': quantity,  # 現物はロング（正の値）
            'entry_time': timestamp,
            'entry_fx_price': exec_fx_price,
            'entry_spot_price': exec_spot_price,
            'entry_spread': spread,
            'entry_zscore': zscore,
            'capital_after_entry': capital - commission
        }
    
    def _exit_position(
        self,
        position: Dict,
        fx_price: float,
        spot_price: float,
        spread: float,
        timestamp: datetime
    ) -> tuple:
        """
        ポジションをエグジット（現物を売り、FXを買い戻す）
        
        Returns:
            (pnl, commission)
        """
        # スリッページを考慮した実行価格
        # 現物を売る
        exec_spot_price = spot_price * (1 - self.slippage_bps / 10000)
        # FXを買い戻す
        exec_fx_price = fx_price * (1 + self.slippage_bps / 10000)
        
        spot_qty = position['spot_position']
        fx_qty = abs(position['fx_position'])  # 絶対値
        
        # エントリー時の価値
        entry_spot_value = position['entry_spot_price'] * spot_qty
        entry_fx_value = position['entry_fx_price'] * fx_qty
        
        # エグジット時の価値
        exit_spot_value = exec_spot_price * spot_qty
        exit_fx_value = exec_fx_price * fx_qty
        
        # 損益計算
        # 現物: 買って売る = exit - entry
        spot_pnl = exit_spot_value - entry_spot_value
        # FX: 売って買い戻す = entry - exit
        fx_pnl = entry_fx_value - exit_fx_value
        
        pnl = spot_pnl + fx_pnl
        
        # 手数料（両側）
        position_value = max(exit_spot_value, exit_fx_value)
        commission = position_value * self.commission_rate * 2
        
        pnl -= commission
        
        return pnl, commission
    
    def _calculate_unrealized_pnl(
        self,
        position: Dict,
        fx_price: float,
        spot_price: float,
        spread: float
    ) -> float:
        """
        未実現損益を計算
        """
        spot_qty = position['spot_position']
        fx_qty = abs(position['fx_position'])
        
        # 現在の価値
        current_spot_value = spot_price * spot_qty
        current_fx_value = fx_price * fx_qty
        
        # エントリー時の価値
        entry_spot_value = position['entry_spot_price'] * spot_qty
        entry_fx_value = position['entry_fx_price'] * fx_qty
        
        # 未実現損益
        spot_unrealized = current_spot_value - entry_spot_value
        fx_unrealized = entry_fx_value - current_fx_value
        
        return spot_unrealized + fx_unrealized
    
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
            sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252 * 24 * 3600)
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

