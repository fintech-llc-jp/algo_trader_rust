"""
Backtesting Module
"""
import pandas as pd
import numpy as np
from typing import Dict, List
from datetime import datetime
import logging

from config.settings import BacktestConfig

# ロガーの設定
logger = logging.getLogger(__name__)


class Backtester:
    """
    バックテスト実行クラス
    過去データを使ってトレーディング戦略のパフォーマンスを評価
    """
    
    def __init__(
        self,
        initial_capital: float = None,
        commission_rate: float = None,
        slippage_bps: float = None,
        maker_order: bool = False,
    ):
        config = BacktestConfig()
        self.initial_capital = initial_capital or config.INITIAL_CAPITAL
        # commission_rate は負値（リベート）もあり得るので or を使わず明示的に None チェック
        self.commission_rate = commission_rate if commission_rate is not None else config.COMMISSION_RATE
        self.slippage_bps = slippage_bps if slippage_bps is not None else config.SLIPPAGE_BPS
        # maker_order=True のとき: mid_price で約定 + commission_rate をリベートとして扱う
        self.maker_order = maker_order

        self.trades = []
        self.equity_curve = []
    
    def run(
        self,
        df: pd.DataFrame,
        signals: pd.Series,
        confidence: pd.Series,
        confidence_threshold: float = None,
        stop_loss: float = None,
        take_profit: float = None,
        fixed_quantity: float = None,
        progress_callback: callable = None
    ) -> Dict:
        """
        バックテストの実行
        
        Args:
            df: 市場データ（mid_price等を含むDataFrame、timestampをindexに）
            signals: シグナル (-1: SELL, 0: HOLD, 1: BUY)
            confidence: 信頼度 (0.0 - 1.0)
            confidence_threshold: 取引を実行する最小信頼度
        
        Returns:
            パフォーマンス指標の辞書
        """
        config = BacktestConfig()
        confidence_threshold = confidence_threshold or config.CONFIDENCE_THRESHOLD
        
        # リセット
        self.trades = []
        self.equity_curve = []
        
        capital = self.initial_capital
        position = 0  # BTC数量（正の値=ロング、負の値=ショート）
        entry_price = 0
        
        total_records = len(df)
        processed_records = 0
        
        for idx, row in df.iterrows():
            processed_records += 1
            
            # 進捗コールバック（10レコードごと、または最後のレコード）
            if progress_callback and (processed_records % 10 == 0 or processed_records == total_records):
                progress_pct = (processed_records / total_records) * 100
                progress_callback(processed_records, total_records, progress_pct)
            
            signal = signals.loc[idx] if idx in signals.index else 0
            conf = confidence.loc[idx] if idx in confidence.index else 0.0
            price = row['mid_price']

            # ASK/BID価格を取得（存在する場合）
            ask_price = row.get('ask_price_1', price)
            bid_price = row.get('bid_price_1', price)

            # Maker注文モード: 全約定をmid_priceで実施（スプレッド内側の指値想定）
            if self.maker_order:
                ask_price = price
                bid_price = price
            
            # 損切・利益確定のチェック（ポジションがある場合）
            if position != 0 and entry_price > 0:
                unrealized_pnl = 0.0
                if position > 0:
                    # ロングポジション: BID価格で評価（成り行きで売る場合の価格）
                    unrealized_pnl = (bid_price - entry_price) * position
                elif position < 0:
                    # ショートポジション: ASK価格で評価（成り行きで買い戻す場合の価格）
                    unrealized_pnl = (entry_price - ask_price) * abs(position)
                
                # 損切チェック（損失がstop_lossを超えた場合）
                if stop_loss is not None and unrealized_pnl < -stop_loss:
                    if position > 0:
                        # ロングポジションを損切（SELL）
                        execution_price = bid_price * (1 - self.slippage_bps / 10000)
                        position_value = position * execution_price
                        commission = position_value * self.commission_rate
                        
                        pnl = (execution_price - entry_price) * position - commission
                        capital += (position_value - commission)
                        
                        self.trades.append({
                            'timestamp': idx,
                            'action': 'SELL',
                            'price': execution_price,
                            'quantity': position,
                            'pnl': pnl,
                            'commission': commission,
                            'capital': capital,
                            'is_stop_loss': True
                        })
                        
                        position = 0
                        entry_price = 0
                    elif position < 0:
                        # ショートポジションを損切（COVER_SHORT）
                        execution_price = ask_price * (1 + self.slippage_bps / 10000)
                        position_value = abs(position) * execution_price
                        commission = position_value * self.commission_rate
                        
                        pnl = (entry_price - execution_price) * abs(position) - commission
                        capital += pnl
                        
                        self.trades.append({
                            'timestamp': idx,
                            'action': 'COVER_SHORT',
                            'price': execution_price,
                            'quantity': abs(position),
                            'pnl': pnl,
                            'commission': commission,
                            'capital': capital,
                            'is_stop_loss': True
                        })
                        
                        position = 0
                        entry_price = 0
                
                # 利益確定チェック（利益がtake_profitを超えた場合）
                elif take_profit is not None and unrealized_pnl > take_profit:
                    if position > 0:
                        # ロングポジションを利益確定（SELL）
                        execution_price = bid_price * (1 - self.slippage_bps / 10000)
                        position_value = position * execution_price
                        commission = position_value * self.commission_rate
                        
                        pnl = (execution_price - entry_price) * position - commission
                        capital += (position_value - commission)
                        
                        self.trades.append({
                            'timestamp': idx,
                            'action': 'SELL',
                            'price': execution_price,
                            'quantity': position,
                            'pnl': pnl,
                            'commission': commission,
                            'capital': capital,
                            'is_take_profit': True
                        })
                        
                        position = 0
                        entry_price = 0
                    elif position < 0:
                        # ショートポジションを利益確定（COVER_SHORT）
                        execution_price = ask_price * (1 + self.slippage_bps / 10000)
                        position_value = abs(position) * execution_price
                        commission = position_value * self.commission_rate
                        
                        pnl = (entry_price - execution_price) * abs(position) - commission
                        capital += pnl
                        
                        self.trades.append({
                            'timestamp': idx,
                            'action': 'COVER_SHORT',
                            'price': execution_price,
                            'quantity': abs(position),
                            'pnl': pnl,
                            'commission': commission,
                            'capital': capital,
                            'is_take_profit': True
                        })
                        
                        position = 0
                        entry_price = 0
            
            # 信頼度が閾値以下ならスキップ
            if conf < confidence_threshold:
                # ポジションがある場合は評価のみ
                current_equity = capital
                if position > 0:
                    # ロングポジションはBID価格で評価（成り行きで売る場合の価格）
                    current_equity += position * bid_price
                elif position < 0:
                    # ショートポジションはASK価格で評価（成り行きで買い戻す場合の価格）
                    # ショートポジションの評価損益 = エントリー価格 - 現在のASK価格
                    current_equity += abs(position) * (entry_price - ask_price)
                self.equity_curve.append({
                    'timestamp': idx,
                    'equity': current_equity,
                    'position': position
                })
                # シグナルがあっても信頼度が低い場合はログ出力
                if signal != 0:
                    logger.info(f"[Backtest] {idx} - Signal: {'BUY' if signal == 1 else 'SELL'}, Confidence: {conf:.3f} < Threshold: {confidence_threshold:.3f} - SKIPPED (low confidence)")
                continue
            
            # BUYシグナル
            if signal == 1:
                logger.info(f"[Backtest] {idx} - BUY signal detected (confidence: {conf:.3f}, price: {price:.2f}, position: {position:.6f})")
                # ショートポジションがある場合は先にクローズ
                if position < 0:
                    # ショートポジションをクローズ（ASK価格で買い戻す）
                    execution_price = ask_price * (1 + self.slippage_bps / 10000)
                    position_value = abs(position) * execution_price
                    commission = position_value * self.commission_rate
                    
                    # ショートポジションの損益計算
                    pnl = (entry_price - execution_price) * abs(position) - commission
                    capital += pnl
                    
                    logger.info(f"[Backtest] {idx} - Action: COVER_SHORT (close short position before BUY) - price: {execution_price:.2f}, quantity: {abs(position):.6f}, PnL: {pnl:.2f}")
                    
                    self.trades.append({
                        'timestamp': idx,
                        'action': 'COVER_SHORT',
                        'price': execution_price,
                        'quantity': abs(position),
                        'pnl': pnl,
                        'commission': commission,
                        'capital': capital
                    })
                    
                    position = 0
                    entry_price = 0
                
                # ロングポジションを建てる（ポジションがない場合）
                if position == 0:
                    # ASK価格で買う（スリッページを考慮）
                    execution_price = ask_price * (1 + self.slippage_bps / 10000)
                    
                    # ポジションサイズ
                    if fixed_quantity is not None:
                        position = fixed_quantity
                        position_value = position * execution_price
                    else:
                        position_value = capital * 0.1  # 資金の10%
                        position = position_value / execution_price
                    
                    # 手数料
                    commission = position_value * self.commission_rate
                    # エントリー時に使った資金と手数料をcapitalから引く
                    capital -= (position_value + commission)
                    
                    entry_price = execution_price
                    
                    logger.info(f"[Backtest] {idx} - Action: BUY executed - price: {execution_price:.2f}, quantity: {position:.6f}, commission: {commission:.2f}, capital: {capital:.2f}")
                    
                    self.trades.append({
                        'timestamp': idx,
                        'action': 'BUY',
                        'price': execution_price,
                        'quantity': position,
                        'commission': commission,
                        'capital': capital
                    })
                else:
                    logger.info(f"[Backtest] {idx} - BUY signal but NO ACTION (already have long position: {position:.6f})")
            
            # SELLシグナル
            elif signal == -1:
                logger.info(f"[Backtest] {idx} - SELL signal detected (confidence: {conf:.3f}, price: {price:.2f}, position: {position:.6f})")
                # ロングポジションがある場合は先にクローズ
                if position > 0:
                    # ロングポジションをクローズ（BID価格で売る）
                    execution_price = bid_price * (1 - self.slippage_bps / 10000)
                    
                    position_value = position * execution_price
                    commission = position_value * self.commission_rate
                    
                    # 損益計算（エントリー時にcapitalから引いた資金を考慮）
                    # 売却額から手数料を引いてcapitalに加算
                    capital += (position_value - commission)
                    
                    # 表示用の損益計算
                    pnl = (execution_price - entry_price) * position - commission
                    
                    logger.info(f"[Backtest] {idx} - Action: SELL executed (close long position) - price: {execution_price:.2f}, quantity: {position:.6f}, PnL: {pnl:.2f}, capital: {capital:.2f}")
                    
                    self.trades.append({
                        'timestamp': idx,
                        'action': 'SELL',
                        'price': execution_price,
                        'quantity': position,
                        'pnl': pnl,
                        'commission': commission,
                        'capital': capital
                    })
                    
                    position = 0
                    entry_price = 0
                
                # ショートポジションを建てる（ポジションがない場合）
                if position == 0:
                    # BID価格で売る（借りて売る、スリッページを考慮）
                    execution_price = bid_price * (1 - self.slippage_bps / 10000)
                    
                    # ポジションサイズ
                    if fixed_quantity is not None:
                        position = -fixed_quantity  # 負の値でショートを表現
                        position_value = abs(position) * execution_price
                    else:
                        position_value = capital * 0.1  # 資金の10%相当
                        position = -(position_value / execution_price)  # 負の値でショートを表現
                    
                    # 手数料
                    commission = position_value * self.commission_rate
                    # ショートポジションの場合は手数料のみをcapitalから引く
                    capital -= commission
                    
                    entry_price = execution_price
                    
                    logger.info(f"[Backtest] {idx} - Action: SHORT executed - price: {execution_price:.2f}, quantity: {abs(position):.6f}, commission: {commission:.2f}, capital: {capital:.2f}")
                    
                    self.trades.append({
                        'timestamp': idx,
                        'action': 'SHORT',
                        'price': execution_price,
                        'quantity': abs(position),
                        'commission': commission,
                        'capital': capital
                    })
                else:
                    logger.info(f"[Backtest] {idx} - SELL signal but NO ACTION (already have short position: {position:.6f})")
            
            # 資金曲線を記録
            current_equity = capital
            if position > 0:
                # ロングポジションはBID価格で評価（成り行きで売る場合の価格）
                current_equity += position * bid_price
            elif position < 0:
                # ショートポジションはASK価格で評価（成り行きで買い戻す場合の価格）
                # ショートポジションの評価損益 = エントリー価格 - 現在のASK価格
                current_equity += abs(position) * (entry_price - ask_price)
            
            self.equity_curve.append({
                'timestamp': idx,
                'equity': current_equity,
                'position': position
            })
        
        # パフォーマンス指標の計算
        metrics = self._calculate_performance_metrics()
        
        # 取引コストの統計を追加
        cost_stats = self._calculate_cost_statistics(df)
        metrics.update(cost_stats)
        
        return metrics
    
    def _calculate_performance_metrics(self) -> Dict:
        """
        パフォーマンス指標の計算
        """
        if not self.equity_curve:
            return {
                'total_return': 0.0,
                'sharpe_ratio': 0.0,
                'max_drawdown': 0.0,
                'total_trades': 0,
                'win_rate': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0,
                'final_equity': self.initial_capital
            }
        
        equity_df = pd.DataFrame(self.equity_curve)
        equity_df.set_index('timestamp', inplace=True)
        
        # 総リターン
        final_equity = equity_df['equity'].iloc[-1]
        total_return = (final_equity / self.initial_capital - 1) * 100
        
        # リターンの計算
        equity_df['returns'] = equity_df['equity'].pct_change()
        
        # シャープレシオ（年率換算、1秒ごとのデータと仮定）
        mean_return = equity_df['returns'].mean()
        std_return = equity_df['returns'].std()
        # 1秒ごとのデータとして、年率換算（365*24*3600秒）
        sharpe_ratio = (mean_return / std_return) * np.sqrt(365 * 24 * 3600) if std_return > 0 else 0
        
        # 最大ドローダウン
        equity_df['cummax'] = equity_df['equity'].cummax()
        equity_df['drawdown'] = (equity_df['equity'] - equity_df['cummax']) / equity_df['cummax']
        max_drawdown = equity_df['drawdown'].min() * 100
        
        # 取引統計
        trades_df = pd.DataFrame(self.trades)
        if len(trades_df) > 0 and 'pnl' in trades_df.columns:
            winning_trades = trades_df[trades_df['pnl'] > 0]
            losing_trades = trades_df[trades_df['pnl'] < 0]
            
            win_rate = len(winning_trades) / len(trades_df) * 100 if len(trades_df) > 0 else 0
            avg_win = winning_trades['pnl'].mean() if len(winning_trades) > 0 else 0
            avg_loss = losing_trades['pnl'].mean() if len(losing_trades) > 0 else 0
            profit_factor = abs(winning_trades['pnl'].sum() / losing_trades['pnl'].sum()) \
                           if len(losing_trades) > 0 and losing_trades['pnl'].sum() != 0 else 0
        else:
            win_rate = 0
            avg_win = 0
            avg_loss = 0
            profit_factor = 0
        
        metrics = {
            'total_return': float(total_return),
            'sharpe_ratio': float(sharpe_ratio),
            'max_drawdown': float(max_drawdown),
            'total_trades': len(trades_df),
            'win_rate': float(win_rate),
            'avg_win': float(avg_win),
            'avg_loss': float(avg_loss),
            'profit_factor': float(profit_factor),
            'final_equity': float(final_equity)
        }
        
        return metrics
    
    def run_maker_limit(
        self,
        df: pd.DataFrame,
        signals: pd.Series,
        confidence: pd.Series,
        confidence_threshold: float = 0.60,
        fixed_quantity: float = 0.01,
        tick_size: float = 1.0,
        max_hold_seconds: int = 0,
    ) -> Dict:
        """
        リアルなMaker指値注文シミュレーション

        BUYシグナル時:
          - 初回: current_bid + 1*tick で指値
          - シグナル継続中: 毎秒 tick を加算 (ask-tick を上限, Takerにならない)
          - 約定判定: exec_price_sell <= 指値価格 かつ exec_price_sell > 0

        SELLシグナル時 (対称):
          - 初回: current_ask - 1*tick で指値
          - シグナル継続中: 毎秒 tick を減算 (bid+tick を下限)
          - 約定判定: exec_price_buy >= 指値価格 かつ exec_price_buy > 0

        シグナル変化 / HOLD:
          - 未約定注文をキャンセル

        max_hold_seconds > 0 のとき:
          - ポジション保有が max_hold_seconds 秒を超えたら、
            逆方向の Maker 指値チェイス（bid+N / ask-N）で決済を開始する
          - シグナルに関係なく決済方向のチェイスを継続し、約定したら終了

        commission_rate < 0 のとき、各約定でリベートを受け取る。
        """
        self.trades = []
        self.equity_curve = []

        capital     = self.initial_capital
        position    = 0.0
        entry_price = 0.0

        pending_side  = None   # 'BUY' | 'SELL' | None
        pending_price = 0.0
        chase_count   = 0      # シグナルが継続した秒数

        entry_tick        = 0      # ポジション開始時の tick カウンタ
        tick_counter      = 0      # 全体 tick カウンタ（1秒 = 1tick 想定）
        timeout_exit_mode = False  # タイムアウト指値決済モード

        for idx, row in df.iterrows():
            tick_counter += 1
            mid    = float(row['mid_price'])
            spread = float(row.get('spread', 0.0))
            bid    = float(row.get('bid_price_1', mid - spread / 2.0))
            ask    = float(row.get('ask_price_1', mid + spread / 2.0))

            raw_sell = row.get('exec_price_sell', 0.0)
            raw_buy  = row.get('exec_price_buy',  0.0)
            exec_sell = 0.0 if (raw_sell is None or raw_sell != raw_sell) else float(raw_sell)
            exec_buy  = 0.0 if (raw_buy  is None or raw_buy  != raw_buy ) else float(raw_buy)

            sig  = int(signals.loc[idx])      if idx in signals.index   else 0
            conf = float(confidence.loc[idx]) if idx in confidence.index else 0.0
            if conf < confidence_threshold:
                sig = 0

            # ─── Step T: タイムアウト → 指値チェイス決済モード ─────────────
            if max_hold_seconds > 0 and position != 0.0:
                if (tick_counter - entry_tick) >= max_hold_seconds:
                    timeout_exit_mode = True   # 決済チェイス開始

            # タイムアウト決済モード中: 逆方向シグナルで上書き（チェイス継続）
            if timeout_exit_mode:
                if position == 0.0:
                    timeout_exit_mode = False  # 約定完了 → モード解除
                else:
                    # ロングなら SELL チェイス、ショートなら BUY チェイス
                    sig = -1 if position > 0 else 1

            # ─── Step A: 指値注文の約定チェック ─────────────────────────────
            if pending_side == 'BUY' and 0 < pending_price < ask:
                # sell takerが指値価格以下で約定していれば、こちらのbid limitが刺さる
                if exec_sell > 0 and exec_sell <= pending_price:
                    fill   = pending_price
                    rebate = fill * fixed_quantity * abs(self.commission_rate)

                    if position < 0:
                        # ショートカバー
                        pnl = (entry_price - fill) * fixed_quantity + rebate
                        capital += pnl
                        action = 'TIMEOUT_COVER' if timeout_exit_mode else 'COVER_SHORT'
                        self.trades.append({
                            'timestamp': idx, 'action': action,
                            'price': fill, 'quantity': fixed_quantity,
                            'pnl': pnl, 'commission': -rebate, 'capital': capital,
                        })
                        position = 0.0; entry_price = 0.0
                        timeout_exit_mode = False
                    elif position == 0:
                        capital -= fill * fixed_quantity
                        capital += rebate
                        position    = fixed_quantity
                        entry_price = fill
                        entry_tick  = tick_counter   # ← タイムアウト計測開始
                        self.trades.append({
                            'timestamp': idx, 'action': 'BUY',
                            'price': fill, 'quantity': fixed_quantity,
                            'pnl': 0.0, 'commission': -rebate, 'capital': capital,
                        })
                    pending_side = None; pending_price = 0.0; chase_count = 0

            elif pending_side == 'SELL' and pending_price > bid:
                # buy takerが指値価格以上で約定していれば、こちらのask limitが刺さる
                if exec_buy > 0 and exec_buy >= pending_price:
                    fill   = pending_price
                    rebate = fill * fixed_quantity * abs(self.commission_rate)

                    if position > 0:
                        # ロングクローズ
                        pnl = (fill - entry_price) * position + rebate
                        capital += fill * fixed_quantity + rebate
                        action = 'TIMEOUT_SELL' if timeout_exit_mode else 'SELL'
                        self.trades.append({
                            'timestamp': idx, 'action': action,
                            'price': fill, 'quantity': fixed_quantity,
                            'pnl': pnl, 'commission': -rebate, 'capital': capital,
                        })
                        position = 0.0; entry_price = 0.0
                        timeout_exit_mode = False
                    elif position == 0:
                        capital += rebate
                        position    = -fixed_quantity
                        entry_price = fill
                        entry_tick  = tick_counter   # ← タイムアウト計測開始
                        self.trades.append({
                            'timestamp': idx, 'action': 'SHORT',
                            'price': fill, 'quantity': fixed_quantity,
                            'pnl': 0.0, 'commission': -rebate, 'capital': capital,
                        })
                    pending_side = None; pending_price = 0.0; chase_count = 0

            # ─── Step B: シグナルに基づいて指値注文を管理 ──────────────────
            if sig == 1:   # BUY → ロングを持ちたい
                if position <= 0:
                    if pending_side != 'BUY':
                        # 新規 or SELL注文をキャンセルしてBUYへ
                        chase_count  = 1
                        pending_side = 'BUY'
                    else:
                        chase_count += 1

                    # 今の bid + chase_count * tick（ask-tick を上限）
                    new_price = bid + chase_count * tick_size
                    new_price = min(new_price, ask - tick_size)
                    if new_price > bid:
                        pending_price = new_price
                    else:
                        # スプレッドが狭すぎて内側に出せない
                        pending_side = None; pending_price = 0.0; chase_count = 0

            elif sig == -1:  # SELL → ショートを持ちたい
                if position >= 0:
                    if pending_side != 'SELL':
                        chase_count  = 1
                        pending_side = 'SELL'
                    else:
                        chase_count += 1

                    new_price = ask - chase_count * tick_size
                    new_price = max(new_price, bid + tick_size)
                    if new_price < ask:
                        pending_price = new_price
                    else:
                        pending_side = None; pending_price = 0.0; chase_count = 0

            elif not timeout_exit_mode:  # HOLD → 未約定注文をキャンセル（タイムアウト中は継続）
                if pending_side is not None:
                    pending_side = None; pending_price = 0.0; chase_count = 0

            # ─── Step C: equity curve 更新 ──────────────────────────────
            eq = capital
            if position > 0:
                eq += position * bid          # ロングはBIDで評価
            elif position < 0:
                eq += abs(position) * (entry_price - ask)  # ショート評価
            self.equity_curve.append({'timestamp': idx, 'equity': eq, 'position': position})

        metrics    = self._calculate_performance_metrics()
        cost_stats = self._calculate_cost_statistics(df)
        metrics.update(cost_stats)
        return metrics

    def get_equity_curve(self) -> pd.DataFrame:
        """資金曲線を取得"""
        return pd.DataFrame(self.equity_curve)
    
    def get_trades(self) -> pd.DataFrame:
        """取引履歴を取得"""
        return pd.DataFrame(self.trades)
    
    def _calculate_cost_statistics(self, df: pd.DataFrame) -> Dict:
        """
        取引コストの統計を計算
        """
        trades_df = pd.DataFrame(self.trades)
        
        if len(trades_df) == 0:
            return {
                'avg_spread_pct': 0.0,
                'avg_spread_bps': 0.0,
                'total_commission': 0.0,
                'total_slippage_cost': 0.0,
                'avg_cost_per_round_trip_pct': 0.0
            }
        
        # スプレッドの計算（取引が発生した時点でのスプレッド）
        spreads = []
        for idx, row in trades_df.iterrows():
            if idx in df.index:
                market_row = df.loc[idx]
                ask = market_row.get('ask_price_1', market_row['mid_price'])
                bid = market_row.get('bid_price_1', market_row['mid_price'])
                mid = market_row['mid_price']
                if mid > 0:
                    spread_pct = ((ask - bid) / mid) * 100
                    spreads.append(spread_pct)
        
        avg_spread_pct = np.mean(spreads) if spreads else 0.0
        avg_spread_bps = avg_spread_pct * 100  # パーセントからベーシスポイントへ
        
        # 手数料の合計
        total_commission = trades_df['commission'].sum() if 'commission' in trades_df.columns else 0.0
        
        # スリッページコストの推定
        # 各取引でスリッページ1bpが発生（往復で2bp）
        total_slippage_cost = 0.0
        if len(trades_df) > 0:
            for idx, row in trades_df.iterrows():
                if idx in df.index:
                    market_row = df.loc[idx]
                    price = market_row['mid_price']
                    quantity = row.get('quantity', 0)
                    slippage_cost = price * quantity * (self.slippage_bps / 10000)
                    total_slippage_cost += slippage_cost
        
        # 往復取引あたりの平均コスト
        round_trips = len(trades_df[trades_df['action'].isin(['SELL', 'COVER_SHORT'])])
        if round_trips > 0:
            # スプレッド(%) + スリッページ(2bp = 0.02%) + 手数料(0.1%)
            # スリッページ: 1bp = 0.01%, 往復で2bp = 0.02%
            # 手数料: 0.05% × 2 = 0.1%
            avg_cost_per_round_trip_pct = avg_spread_pct + (self.slippage_bps * 2 / 100) + (self.commission_rate * 2 * 100)
        else:
            avg_cost_per_round_trip_pct = 0.0
        
        return {
            'avg_spread_pct': float(avg_spread_pct),
            'avg_spread_bps': float(avg_spread_bps),
            'total_commission': float(total_commission),
            'total_slippage_cost': float(total_slippage_cost),
            'avg_cost_per_round_trip_pct': float(avg_cost_per_round_trip_pct)
        }

