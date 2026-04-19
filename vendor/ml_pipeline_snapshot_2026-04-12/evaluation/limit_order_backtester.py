"""
Limit Order Backtesting Module
指値注文をサポートするバックテスター
ベストBID/ASKに指値を置いて約定を待つ戦略
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging

from config.settings import BacktestConfig

# ロガーの設定
logger = logging.getLogger(__name__)


class LimitOrderBacktester:
    """
    指値注文をサポートするバックテスター
    ベストBID/ASKに指値を置いて約定を待つ戦略
    """
    
    def __init__(
        self,
        initial_capital: float = None,
        commission_rate: float = None,
        limit_order_timeout_seconds: int = 60,
        executions_df: pd.DataFrame = None,
        auto_exit: bool = False
    ):
        """
        Args:
            initial_capital: 初期資金
            commission_rate: 手数料率
            limit_order_timeout_seconds: 指値注文のタイムアウト時間（秒、デフォルト60秒=1分）
            executions_df: 約定履歴データ（timestamp, price, sideを含むDataFrame）
            auto_exit: エントリー約定後に即座に反対売買の指値を出す（スキャルピングモード）
        """
        config = BacktestConfig()
        self.initial_capital = initial_capital or config.INITIAL_CAPITAL
        self.commission_rate = commission_rate or config.COMMISSION_RATE
        self.limit_order_timeout = limit_order_timeout_seconds
        self.executions_df = executions_df  # 約定履歴データ
        self.auto_exit = auto_exit

        self.trades = []
        self.equity_curve = []
        self.pending_orders = []  # 未約定の指値注文リスト
    
    def run(
        self,
        df: pd.DataFrame,
        signals: pd.Series,
        confidence: pd.Series,
        confidence_threshold: float = None,
        executions_df: pd.DataFrame = None,
        stop_loss: float = None,
        take_profit: float = None,
        fixed_quantity: float = None,
        progress_callback: callable = None
    ) -> Dict:
        """
        バックテストの実行（指値注文版）
        
        Args:
            df: 市場データ（mid_price, bid_price_1, ask_price_1等を含むDataFrame、timestampをindexに）
            signals: シグナル (-1: SELL, 0: HOLD, 1: BUY)
            confidence: 信頼度 (0.0 - 1.0)
            confidence_threshold: 取引を実行する最小信頼度
        
        Returns:
            パフォーマンス指標の辞書
        """
        config = BacktestConfig()
        confidence_threshold = confidence_threshold or config.CONFIDENCE_THRESHOLD
        
        # 約定履歴データの設定
        if executions_df is not None:
            self.executions_df = executions_df
        if self.executions_df is None:
            raise ValueError("executions_df is required for realistic limit order backtesting")
        
        # 約定履歴データをタイムスタンプでインデックス化（存在する場合）
        if 'timestamp' in self.executions_df.columns:
            exec_df_indexed = self.executions_df.set_index('timestamp').sort_index()
        else:
            exec_df_indexed = self.executions_df.copy()
        
        # リセット
        self.trades = []
        self.equity_curve = []
        self.pending_orders = []
        
        capital = self.initial_capital
        position = 0  # BTC数量
        entry_price = 0
        entry_commission = 0  # エントリー時の手数料（SHORT/BUYの時）
        
        # 必要なカラムの確認
        required_cols = ['mid_price', 'bid_price_1', 'ask_price_1']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns: {missing_cols}")
        
        # 約定履歴データのカラム確認
        exec_required_cols = ['price', 'side']
        exec_missing_cols = [col for col in exec_required_cols if col not in exec_df_indexed.columns]
        if exec_missing_cols:
            raise ValueError(f"Missing required columns in executions_df: {exec_missing_cols}")
        
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
            
            mid_price = row['mid_price']
            best_bid = row['bid_price_1']
            best_ask = row['ask_price_1']
            
            # 未約定の指値注文のベストBID/ASKを更新（差し替え）
            for order in self.pending_orders:
                if order['side'] == 'BUY':
                    # ベストBIDが変わった場合、指値価格を更新
                    if best_bid != order.get('current_best_bid', best_bid):
                        order['limit_price'] = best_bid  # ベストBIDを差し替え
                    order['current_best_bid'] = best_bid
                elif order['side'] == 'SELL':
                    # ベストASKが変わった場合、指値価格を更新
                    if best_ask != order.get('current_best_ask', best_ask):
                        order['limit_price'] = best_ask  # ベストASKを差し替え
                    order['current_best_ask'] = best_ask
            
            # 未約定の指値注文をチェック（約定履歴データを使用）
            filled_orders = self._check_pending_orders_with_executions(
                idx, best_bid, best_ask, exec_df_indexed
            )
            
            # 約定した注文を処理
            for order in filled_orders:
                if order['side'] == 'BUY':
                    if order.get('is_cover', False) and position < 0:
                        # ショートポジションをクローズ（COVER_SHORT）
                        execution_price = order['execution_price']
                        # 実際にクローズする数量はabs(position)を使用（quantityと異なる可能性があるため）
                        close_quantity = abs(position)
                        position_value = close_quantity * execution_price
                        exit_commission = position_value * self.commission_rate
                        
                        # ショートポジションの損益計算
                        # SHORTの時の手数料（entry_commission）とCOVER_SHORTの時の手数料（exit_commission）の両方を考慮
                        pnl = (entry_price - execution_price) * close_quantity - entry_commission - exit_commission
                        capital += pnl
                        
                        logger.info(f"[Backtest] {idx} - LIMIT ORDER FILLED: COVER_SHORT - limit: {order['limit_price']:.2f}, execution: {execution_price:.2f}, quantity: {abs(position):.6f}, PnL: {pnl:.2f}, delay: {order.get('fill_delay_seconds', 0):.1f}s")
                        
                        self.trades.append({
                            'timestamp': idx,
                            'action': 'COVER_SHORT',
                            'order_type': 'LIMIT',
                            'limit_price': order['limit_price'],
                            'execution_price': execution_price,
                            'quantity': close_quantity,
                            'pnl': pnl,
                            'commission': exit_commission,
                            'capital': capital,
                            'fill_delay_seconds': order.get('fill_delay_seconds', 0)
                        })
                        
                        position = 0
                        entry_price = 0
                        entry_commission = 0
                    elif not order.get('is_cover', False) and position == 0:
                        # ロングポジションを建てる（BUY）
                        execution_price = order['execution_price']
                        quantity = order['quantity']
                        position_value = quantity * execution_price
                        commission = position_value * self.commission_rate

                        capital -= (position_value + commission)
                        position = quantity
                        entry_price = execution_price
                        entry_commission = commission

                        logger.info(f"[Backtest] {idx} - LIMIT ORDER FILLED: BUY - limit: {order['limit_price']:.2f}, execution: {execution_price:.2f}, quantity: {quantity:.6f}, commission: {commission:.2f}, delay: {order.get('fill_delay_seconds', 0):.1f}s")

                        self.trades.append({
                            'timestamp': idx,
                            'action': 'BUY',
                            'order_type': 'LIMIT',
                            'limit_price': order['limit_price'],
                            'execution_price': execution_price,
                            'quantity': quantity,
                            'commission': commission,
                            'capital': capital,
                            'fill_delay_seconds': order.get('fill_delay_seconds', 0)
                        })

                        # Auto Exit: BUY約定後に即座にSELL close注文をBestAskに配置
                        if self.auto_exit and position > 0:
                            has_pending_close = any(o['side'] == 'SELL' and o.get('is_close', False) for o in self.pending_orders)
                            if not has_pending_close:
                                close_order = {
                                    'side': 'SELL',
                                    'limit_price': best_ask,
                                    'quantity': position,
                                    'placed_at': idx,
                                    'status': 'PENDING',
                                    'current_best_ask': best_ask,
                                    'is_close': True,
                                    'is_auto_exit': True
                                }
                                self.pending_orders.append(close_order)
                                logger.info(f"[Backtest] {idx} - AUTO EXIT: SELL close order placed @ BestAsk {best_ask:.2f}, quantity: {position:.6f}")
                elif order['side'] == 'SELL':
                    if order.get('is_close', False) and position > 0:
                        # ロングポジションをクローズ（SELL）
                        execution_price = order['execution_price']
                        position_value = position * execution_price
                        commission = position_value * self.commission_rate
                        
                        # ロングポジションの損益計算
                        # BUYの時の手数料（entry_commission）とSELLの時の手数料（commission）の両方を考慮
                        pnl = (execution_price - entry_price) * position - entry_commission - commission
                        # PNLをcapitalに加算（BUYの時に引いた金額 + PNL = SELLの時の受取金額）
                        capital += pnl
                        
                        logger.info(f"[Backtest] {idx} - LIMIT ORDER FILLED: SELL (close long) - limit: {order['limit_price']:.2f}, execution: {execution_price:.2f}, quantity: {position:.6f}, PnL: {pnl:.2f}, delay: {order.get('fill_delay_seconds', 0):.1f}s")
                        
                        self.trades.append({
                            'timestamp': idx,
                            'action': 'SELL',
                            'order_type': 'LIMIT',
                            'limit_price': order['limit_price'],
                            'execution_price': execution_price,
                            'quantity': position,
                            'pnl': pnl,
                            'commission': commission,
                            'capital': capital,
                            'fill_delay_seconds': order.get('fill_delay_seconds', 0)
                        })
                        
                        position = 0
                        entry_price = 0
                        entry_commission = 0
                    elif order.get('is_short', False) and position == 0:
                        # ショートポジションを建てる（SHORT）
                        execution_price = order['execution_price']
                        quantity = order['quantity']
                        position_value = quantity * execution_price
                        commission = position_value * self.commission_rate

                        # ショートポジションの場合は手数料のみをcapitalから引く
                        capital -= commission
                        position = -quantity  # 負の値でショートを表現
                        entry_price = execution_price
                        entry_commission = commission

                        logger.info(f"[Backtest] {idx} - LIMIT ORDER FILLED: SHORT - limit: {order['limit_price']:.2f}, execution: {execution_price:.2f}, quantity: {quantity:.6f}, commission: {commission:.2f}, delay: {order.get('fill_delay_seconds', 0):.1f}s")

                        self.trades.append({
                            'timestamp': idx,
                            'action': 'SHORT',
                            'order_type': 'LIMIT',
                            'limit_price': order['limit_price'],
                            'execution_price': execution_price,
                            'quantity': quantity,
                            'commission': commission,
                            'capital': capital,
                            'fill_delay_seconds': order.get('fill_delay_seconds', 0)
                        })

                        # Auto Exit: SHORT約定後に即座にBUY cover注文をBestBidに配置
                        if self.auto_exit and position < 0:
                            has_pending_cover = any(o['side'] == 'BUY' and o.get('is_cover', False) for o in self.pending_orders)
                            if not has_pending_cover:
                                cover_order = {
                                    'side': 'BUY',
                                    'limit_price': best_bid,
                                    'quantity': abs(position),
                                    'placed_at': idx,
                                    'status': 'PENDING',
                                    'current_best_bid': best_bid,
                                    'is_cover': True,
                                    'is_auto_exit': True
                                }
                                self.pending_orders.append(cover_order)
                                logger.info(f"[Backtest] {idx} - AUTO EXIT: BUY cover order placed @ BestBid {best_bid:.2f}, quantity: {abs(position):.6f}")
            
            # 損切・利益確定のチェック（ポジションがある場合）
            if position != 0 and entry_price > 0:
                unrealized_pnl = 0.0
                if position > 0:
                    # ロングポジション: BID価格で評価（成り行きで売る場合の価格）
                    unrealized_pnl = (best_bid - entry_price) * position
                elif position < 0:
                    # ショートポジション: ASK価格で評価（成り行きで買い戻す場合の価格）
                    unrealized_pnl = (entry_price - best_ask) * abs(position)
                
                # 損切チェック（損失がstop_lossを超えた場合）
                if stop_loss is not None and unrealized_pnl < -stop_loss:
                    if position > 0:
                        # ロングポジションを損切（SELL）
                        has_pending_sell = any(o['side'] == 'SELL' and o.get('is_close', False) and o.get('is_stop_loss', False) for o in self.pending_orders)
                        if not has_pending_sell:
                            order = {
                                'side': 'SELL',
                                'limit_price': best_bid,  # ベストBIDに指値を置く
                                'quantity': position,
                                'placed_at': idx,
                                'status': 'PENDING',
                                'current_best_bid': best_bid,
                                'is_close': True,
                                'is_stop_loss': True  # 損切フラグ
                            }
                            self.pending_orders.append(order)
                    elif position < 0:
                        # ショートポジションを損切（COVER_SHORT）
                        has_pending_buy = any(o['side'] == 'BUY' and o.get('is_cover', False) and o.get('is_stop_loss', False) for o in self.pending_orders)
                        if not has_pending_buy:
                            order = {
                                'side': 'BUY',
                                'limit_price': best_ask,  # ショートをクローズするためASKに指値を置く
                                'quantity': abs(position),
                                'placed_at': idx,
                                'status': 'PENDING',
                                'current_best_ask': best_ask,
                                'is_cover': True,
                                'is_stop_loss': True  # 損切フラグ
                            }
                            self.pending_orders.append(order)
                
                # 利益確定チェック（利益がtake_profitを超えた場合）
                elif take_profit is not None and unrealized_pnl > take_profit:
                    if position > 0:
                        # ロングポジションを利益確定（SELL）
                        has_pending_sell = any(o['side'] == 'SELL' and o.get('is_close', False) and o.get('is_take_profit', False) for o in self.pending_orders)
                        if not has_pending_sell:
                            order = {
                                'side': 'SELL',
                                'limit_price': best_ask,  # ベストASKに指値を置く
                                'quantity': position,
                                'placed_at': idx,
                                'status': 'PENDING',
                                'current_best_ask': best_ask,
                                'is_close': True,
                                'is_take_profit': True  # 利益確定フラグ
                            }
                            self.pending_orders.append(order)
                    elif position < 0:
                        # ショートポジションを利益確定（COVER_SHORT）
                        has_pending_buy = any(o['side'] == 'BUY' and o.get('is_cover', False) and o.get('is_take_profit', False) for o in self.pending_orders)
                        if not has_pending_buy:
                            order = {
                                'side': 'BUY',
                                'limit_price': best_bid,  # ショートをクローズするためBIDに指値を置く
                                'quantity': abs(position),
                                'placed_at': idx,
                                'status': 'PENDING',
                                'current_best_bid': best_bid,
                                'is_cover': True,
                                'is_take_profit': True  # 利益確定フラグ
                            }
                            self.pending_orders.append(order)
            
            # 信頼度が閾値以下ならスキップ（ただし未約定注文のチェックは継続）
            if conf < confidence_threshold:
                # ポジションがある場合は評価のみ
                current_equity = capital
                if position > 0:
                    current_equity += position * mid_price
                elif position < 0:
                    # ショートポジションはASK価格で評価（成り行きで買い戻す場合の価格）
                    current_equity += abs(position) * (entry_price - best_ask)
                self.equity_curve.append({
                    'timestamp': idx,
                    'equity': current_equity,
                    'position': position,
                    'pending_orders': len(self.pending_orders)
                })
                # シグナルがあっても信頼度が低い場合はログ出力
                if signal != 0:
                    logger.info(f"[Backtest] {idx} - Signal: {'BUY' if signal == 1 else 'SELL'}, Confidence: {conf:.3f} < Threshold: {confidence_threshold:.3f} - SKIPPED (low confidence)")
                continue
            
            # Auto Exit: ポジション保有中にクローズ注文がpending中なら、シグナルによる重複クローズをスキップ
            if self.auto_exit and position != 0:
                has_auto_exit_pending = any(o.get('is_auto_exit', False) for o in self.pending_orders)
                if has_auto_exit_pending:
                    if signal != 0:
                        logger.info(f"[Backtest] {idx} - Auto-exit close order pending, skipping signal {'BUY' if signal == 1 else 'SELL'}")
                    # 資金曲線を記録
                    current_equity = capital
                    if position > 0:
                        current_equity += position * mid_price
                    elif position < 0:
                        current_equity += abs(position) * (entry_price - best_ask)
                    self.equity_curve.append({
                        'timestamp': idx,
                        'equity': current_equity,
                        'position': position,
                        'pending_orders': len(self.pending_orders)
                    })
                    continue

            # BUYシグナル
            if signal == 1:
                logger.info(f"[Backtest] {idx} - BUY signal detected (confidence: {conf:.3f}, price: {mid_price:.2f}, bid: {best_bid:.2f}, ask: {best_ask:.2f}, position: {position:.6f}, pending_orders: {len(self.pending_orders)})")
                # ショートポジションがある場合は先にクローズ
                if position < 0:
                    # ショートポジションをクローズするための買い注文を配置
                    has_pending_buy = any(o['side'] == 'BUY' and o.get('is_cover', False) for o in self.pending_orders)
                    if not has_pending_buy:
                        order = {
                            'side': 'BUY',
                            'limit_price': best_ask,  # ショートをクローズするためASKに指値を置く
                            'quantity': abs(position),
                            'placed_at': idx,
                            'status': 'PENDING',
                            'current_best_ask': best_ask,
                            'is_cover': True  # ショートクローズ用のフラグ
                        }
                        self.pending_orders.append(order)
                        logger.info(f"[Backtest] {idx} - Action: LIMIT ORDER PLACED (COVER_SHORT) - limit: {best_ask:.2f}, quantity: {abs(position):.6f}")
                    else:
                        logger.info(f"[Backtest] {idx} - BUY signal but NO ACTION (already have pending COVER_SHORT order)")
                
                # ポジションがない場合のみ新規ロング注文を出す
                elif position == 0:
                    # 既に未約定の買い注文がある場合はスキップ
                    has_pending_buy = any(o['side'] == 'BUY' and not o.get('is_cover', False) for o in self.pending_orders)
                    if not has_pending_buy:
                        # 指値注文を配置（ベストBIDに指値を置く）
                        if fixed_quantity is not None:
                            quantity = fixed_quantity
                        else:
                            position_value = capital * 0.1  # 資金の10%
                            quantity = position_value / best_bid
                        
                        # 指値注文を配置（約定履歴を確認するため、PENDINGとして配置）
                        order = {
                            'side': 'BUY',
                            'limit_price': best_bid,
                            'quantity': quantity,
                            'placed_at': idx,
                            'status': 'PENDING',
                            'current_best_bid': best_bid,  # 現在のベストBIDを記録
                            'is_cover': False
                        }
                        self.pending_orders.append(order)
                        logger.info(f"[Backtest] {idx} - Action: LIMIT ORDER PLACED (BUY) - limit: {best_bid:.2f}, quantity: {quantity:.6f}")
                    else:
                        logger.info(f"[Backtest] {idx} - BUY signal but NO ACTION (already have pending BUY order)")
                else:
                    logger.info(f"[Backtest] {idx} - BUY signal but NO ACTION (already have long position: {position:.6f})")
            
            # SELLシグナル
            elif signal == -1:
                logger.info(f"[Backtest] {idx} - SELL signal detected (confidence: {conf:.3f}, price: {mid_price:.2f}, bid: {best_bid:.2f}, ask: {best_ask:.2f}, position: {position:.6f}, pending_orders: {len(self.pending_orders)})")
                # ロングポジションがある場合は先にクローズ
                if position > 0:
                    # ロングポジションをクローズするための売り注文を配置
                    has_pending_sell = any(o['side'] == 'SELL' and o.get('is_close', False) for o in self.pending_orders)
                    if not has_pending_sell:
                        order = {
                            'side': 'SELL',
                            'limit_price': best_ask,  # ベストASKに指値を置く
                            'quantity': position,
                            'placed_at': idx,
                            'status': 'PENDING',
                            'current_best_ask': best_ask,
                            'is_close': True  # ロングクローズ用のフラグ
                        }
                        self.pending_orders.append(order)
                        logger.info(f"[Backtest] {idx} - Action: LIMIT ORDER PLACED (SELL close long) - limit: {best_ask:.2f}, quantity: {position:.6f}")
                    else:
                        logger.info(f"[Backtest] {idx} - SELL signal but NO ACTION (already have pending SELL close order)")
                
                # ポジションがない場合のみ新規ショート注文を出す
                elif position == 0:
                    # 既に未約定の売り注文がある場合はスキップ
                    has_pending_sell = any(o['side'] == 'SELL' and not o.get('is_close', False) and o.get('is_short', False) for o in self.pending_orders)
                    if not has_pending_sell:
                        # ショートポジションを建てるための売り注文を配置（ベストBIDに指値を置く）
                        if fixed_quantity is not None:
                            quantity = fixed_quantity
                        else:
                            position_value = capital * 0.1  # 資金の10%相当
                            quantity = position_value / best_bid
                        
                        order = {
                            'side': 'SELL',
                            'limit_price': best_bid,  # ショートはBIDに指値を置く
                            'quantity': quantity,
                            'placed_at': idx,
                            'status': 'PENDING',
                            'current_best_bid': best_bid,
                            'is_close': False,
                            'is_short': True  # ショートエントリー用のフラグ
                        }
                        self.pending_orders.append(order)
                        logger.info(f"[Backtest] {idx} - Action: LIMIT ORDER PLACED (SHORT) - limit: {best_bid:.2f}, quantity: {quantity:.6f}")
                    else:
                        logger.info(f"[Backtest] {idx} - SELL signal but NO ACTION (already have pending SHORT order)")
                else:
                    logger.info(f"[Backtest] {idx} - SELL signal but NO ACTION (already have short position: {position:.6f})")
            
            # 資金曲線を記録
            current_equity = capital
            if position > 0:
                current_equity += position * mid_price
            elif position < 0:
                # ショートポジションはASK価格で評価（成り行きで買い戻す場合の価格）
                current_equity += abs(position) * (entry_price - best_ask)
            
            self.equity_curve.append({
                'timestamp': idx,
                'equity': current_equity,
                'position': position,
                'pending_orders': len(self.pending_orders)
            })
        
        # パフォーマンス指標の計算
        metrics = self._calculate_performance_metrics()
        
        return metrics
    
    def _place_limit_order(
        self,
        side: str,
        limit_price: float,
        quantity: float,
        timestamp: datetime,
        best_bid: float,
        best_ask: float
    ) -> Dict:
        """
        指値注文を配置
        
        Args:
            side: 'BUY' or 'SELL'
            limit_price: 指値価格
            quantity: 数量
            timestamp: タイムスタンプ
            best_bid: 現在のベストBID
            best_ask: 現在のベストASK
        
        Returns:
            注文情報の辞書
        """
        order = {
            'side': side,
            'limit_price': limit_price,
            'quantity': quantity,
            'placed_at': timestamp,
            'status': 'PENDING'
        }
        
        # 約定可能性をチェック
        if self.use_aggressive_limit:
            if side == 'BUY':
                if limit_price >= best_ask:
                    # 指値がASK以上なら即座に約定（成り行き扱い）
                    order['status'] = 'FILLED'
                    order['execution_price'] = best_ask
                    order['fill_delay_seconds'] = 0
                elif limit_price == best_bid:
                    # 指値がBIDと同じなら即座に約定
                    order['status'] = 'FILLED'
                    order['execution_price'] = best_bid
                    order['fill_delay_seconds'] = 0
                else:
                    # 指値注文として待機
                    self.pending_orders.append(order)
            elif side == 'SELL':
                if limit_price <= best_bid:
                    # 指値がBID以下なら即座に約定（成り行き扱い）
                    order['status'] = 'FILLED'
                    order['execution_price'] = best_bid
                    order['fill_delay_seconds'] = 0
                elif limit_price == best_ask:
                    # 指値がASKと同じなら即座に約定
                    order['status'] = 'FILLED'
                    order['execution_price'] = best_ask
                    order['fill_delay_seconds'] = 0
                else:
                    # 指値注文として待機
                    self.pending_orders.append(order)
        else:
            # 厳密な指値注文（指値価格で約定するまで待つ）
            if side == 'BUY':
                if limit_price >= best_ask:
                    # 指値がASK以上なら即座に約定
                    order['status'] = 'FILLED'
                    order['execution_price'] = best_ask
                    order['fill_delay_seconds'] = 0
                elif limit_price == best_bid:
                    # 指値がBIDと同じなら即座に約定
                    order['status'] = 'FILLED'
                    order['execution_price'] = best_bid
                    order['fill_delay_seconds'] = 0
                else:
                    # 指値注文として待機
                    self.pending_orders.append(order)
            elif side == 'SELL':
                if limit_price <= best_bid:
                    # 指値がBID以下なら即座に約定
                    order['status'] = 'FILLED'
                    order['execution_price'] = best_bid
                    order['fill_delay_seconds'] = 0
                elif limit_price == best_ask:
                    # 指値がASKと同じなら即座に約定
                    order['status'] = 'FILLED'
                    order['execution_price'] = best_ask
                    order['fill_delay_seconds'] = 0
                else:
                    # 指値注文として待機
                    self.pending_orders.append(order)
        
        return order
    
    def _check_pending_orders_with_executions(
        self,
        timestamp: datetime,
        best_bid: float,
        best_ask: float,
        executions_df: pd.DataFrame
    ) -> List[Dict]:
        """
        未約定の指値注文をチェックして約定判定（約定履歴データを使用）
        
        Args:
            timestamp: 現在のタイムスタンプ
            best_bid: 現在のベストBID
            best_ask: 現在のベストASK
            executions_df: 約定履歴データ（timestampをindex、price, sideを含む）
        
        Returns:
            約定した注文のリスト
        """
        filled_orders = []
        remaining_orders = []
        
        # 現在のタイムスタンプ以降の約定履歴を取得
        # 注文が置かれた時点から現在までの約定履歴を確認
        for order in self.pending_orders:
            elapsed = (timestamp - order['placed_at']).total_seconds()
            
            # タイムアウトチェック（1分経過）
            if elapsed > self.limit_order_timeout:
                # タイムアウト: 成り行きに切り替え
                if order['side'] == 'BUY':
                    order['execution_price'] = best_ask  # 成り行き買い
                else:
                    order['execution_price'] = best_bid  # 成り行き売り
                order['status'] = 'FILLED_TIMEOUT'
                order['fill_delay_seconds'] = elapsed
                logger.info(f"[Backtest] {timestamp} - LIMIT ORDER TIMEOUT: {order['side']} - limit: {order['limit_price']:.2f}, execution: {order['execution_price']:.2f}, elapsed: {elapsed:.1f}s")
                filled_orders.append(order)
                continue
            
            # 約定履歴を確認（注文が置かれた時点から現在まで）
            order_placed_time = order['placed_at']
            relevant_executions = executions_df[
                (executions_df.index >= order_placed_time) & 
                (executions_df.index <= timestamp)
            ]
            
            if len(relevant_executions) == 0:
                # 約定履歴がない場合は待機継続
                remaining_orders.append(order)
                continue
            
            # 買い指値注文の約定判定
            if order['side'] == 'BUY':
                # 買い指値注文は、誰かが売り注文を出して約定した場合に約定
                # 約定履歴のside='SELL'は、売り注文による約定を意味
                # 買い指値注文が約定するには、約定価格が指値価格以下である必要がある
                # （指値価格以下で買える）
                
                # 売り注文による約定履歴を確認
                sell_executions = relevant_executions[
                    (relevant_executions['side'].str.upper() == 'SELL') |
                    (relevant_executions['side'].str.upper() == 'S')
                ]
                
                if len(sell_executions) > 0:
                    # 指値価格以下で約定したか確認
                    filled_executions = sell_executions[sell_executions['price'] <= order['limit_price']]
                    
                    if len(filled_executions) > 0:
                        # 約定: 最初の約定価格を使用
                        execution_price = filled_executions['price'].iloc[0]
                        order['execution_price'] = execution_price
                        order['status'] = 'FILLED'
                        order['fill_delay_seconds'] = elapsed
                        logger.info(f"[Backtest] {timestamp} - LIMIT ORDER MATCHED (BUY): limit: {order['limit_price']:.2f}, execution: {execution_price:.2f}, delay: {elapsed:.1f}s")
                        filled_orders.append(order)
                        continue
                
                # 約定していない場合、ベストBIDを更新して待機継続
                # （既に更新済みなので、待機継続）
                remaining_orders.append(order)
            
            # 売り指値注文の約定判定
            elif order['side'] == 'SELL':
                # 売り指値注文は、誰かが買い注文を出して約定した場合に約定
                # 約定履歴のside='BUY'は、買い注文による約定を意味
                # 売り指値注文が約定するには、約定価格が指値価格以上である必要がある
                # （指値価格以上で売れる）
                
                # 買い注文による約定履歴を確認
                buy_executions = relevant_executions[
                    (relevant_executions['side'].str.upper() == 'BUY') |
                    (relevant_executions['side'].str.upper() == 'B')
                ]
                
                if len(buy_executions) > 0:
                    # 指値価格以上で約定したか確認
                    filled_executions = buy_executions[buy_executions['price'] >= order['limit_price']]
                    
                    if len(filled_executions) > 0:
                        # 約定: 最初の約定価格を使用
                        execution_price = filled_executions['price'].iloc[0]
                        order['execution_price'] = execution_price
                        order['status'] = 'FILLED'
                        order['fill_delay_seconds'] = elapsed
                        logger.info(f"[Backtest] {timestamp} - LIMIT ORDER MATCHED (SELL): limit: {order['limit_price']:.2f}, execution: {execution_price:.2f}, delay: {elapsed:.1f}s")
                        filled_orders.append(order)
                        continue
                
                # 約定していない場合、ベストASKを更新して待機継続
                # （既に更新済みなので、待機継続）
                remaining_orders.append(order)
            else:
                remaining_orders.append(order)
        
        self.pending_orders = remaining_orders
        return filled_orders
    
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
                'final_equity': self.initial_capital,
                'avg_fill_delay_seconds': 0.0,
                'limit_order_fill_rate': 0.0
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
        sharpe_ratio = (mean_return / std_return) * np.sqrt(365 * 24 * 3600) if std_return > 0 else 0
        
        # 最大ドローダウン
        equity_df['cummax'] = equity_df['equity'].cummax()
        equity_df['drawdown'] = (equity_df['equity'] - equity_df['cummax']) / equity_df['cummax']
        max_drawdown = equity_df['drawdown'].min() * 100
        
        # 取引統計
        trades_df = pd.DataFrame(self.trades)
        if len(trades_df) > 0 and 'pnl' in trades_df.columns:
            exit_trades = trades_df[trades_df['action'] == 'SELL']
            if len(exit_trades) > 0:
                winning_trades = exit_trades[exit_trades['pnl'] > 0]
                losing_trades = exit_trades[exit_trades['pnl'] < 0]
                
                win_rate = len(winning_trades) / len(exit_trades) * 100 if len(exit_trades) > 0 else 0
                avg_win = winning_trades['pnl'].mean() if len(winning_trades) > 0 else 0
                avg_loss = losing_trades['pnl'].mean() if len(losing_trades) > 0 else 0
                profit_factor = abs(winning_trades['pnl'].sum() / losing_trades['pnl'].sum()) \
                               if len(losing_trades) > 0 and losing_trades['pnl'].sum() != 0 else 0
            else:
                win_rate = 0
                avg_win = 0
                avg_loss = 0
                profit_factor = 0
        else:
            win_rate = 0
            avg_win = 0
            avg_loss = 0
            profit_factor = 0
        
        # 指値注文の統計
        if len(trades_df) > 0 and 'fill_delay_seconds' in trades_df.columns:
            avg_fill_delay = trades_df['fill_delay_seconds'].mean()
            limit_orders = trades_df[trades_df['order_type'].str.contains('LIMIT', na=False)]
            limit_order_fill_rate = len(limit_orders) / len(trades_df) * 100 if len(trades_df) > 0 else 0
        else:
            avg_fill_delay = 0.0
            limit_order_fill_rate = 0.0
        
        return {
            'total_return': total_return,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'total_trades': len(trades_df),
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'final_equity': final_equity,
            'avg_fill_delay_seconds': avg_fill_delay,
            'limit_order_fill_rate': limit_order_fill_rate
        }
    
    def get_equity_curve(self) -> pd.DataFrame:
        """資金曲線を取得"""
        return pd.DataFrame(self.equity_curve)
    
    def get_trades(self) -> pd.DataFrame:
        """取引履歴を取得"""
        return pd.DataFrame(self.trades)

