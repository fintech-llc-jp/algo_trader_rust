"""
live_trader.py の単体テスト

テスト対象:
  1. _chase_side()       - BUY/SELL の bid+N / ask-N チェイスロジック
  2. _manage_orders()    - ポジション対応の注文管理
  3. _sync_position()    - 約定検知 + 損益計算（Maker Rebate 込み）

実行方法:
  cd vendor/ml_pipeline_snapshot_2026-04-12/evaluation
  python -m pytest test_live_trader.py -v
"""

import sys
import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch, call

# live_trader をインポート（DB・ネットワーク不要なユニットテスト用）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# live_trader のトップレベルインポートをモック化（psycopg2 などが入っていない環境対応）
with patch.dict("sys.modules", {
    "psycopg2":                       MagicMock(),
    "data.feature_engineering":       MagicMock(),
    "config.settings":                MagicMock(),
}):
    from evaluation.live_trader import LiveTrader


SYMBOL = "G_FX_BTCJPY"
MAKER_REBATE_RATE = 0.0001   # live_trader.py 内の定数と同じ


# ─────────────────────────────────────────────────────────────
# テスト用ファクトリ（DB/ネットワーク不要）
# ─────────────────────────────────────────────────────────────

def _make_trader(
    symbol: str = SYMBOL,
    quantity: float = 0.001,
    confidence_threshold: float = 0.70,
    tick_size: float = 1.0,
    dry_run: bool = False,   # False にして client を mock する
) -> LiveTrader:
    """__init__ をバイパスして LiveTrader の状態を直接初期化する。"""
    trader = object.__new__(LiveTrader)

    # 設定
    trader.symbol               = symbol
    trader.quantity             = quantity
    trader.confidence_threshold = confidence_threshold
    trader.tick_size            = tick_size
    trader.dry_run              = dry_run

    # mock クライアント（デフォルト: 全操作成功）
    trader.client = MagicMock()
    trader.client.cancel_order.return_value = True
    trader.client.place_limit_order.return_value = "mock-cl-ord-id"

    # 注文状態
    trader._pending_cl_ord_id  = None
    trader._pending_side       = None
    trader._pending_price      = 0.0
    trader._chase_count        = 0
    trader._last_placed_price  = 0.0

    # ポジション・損益
    trader._position_qty       = 0.0
    trader._entry_price        = 0.0
    trader._realized_pnl       = 0.0
    trader._fill_count         = 0

    # タイムアウト決済（新フィールド）
    trader.timeout_seconds     = 0          # テストでは無効（0=off）
    trader._entry_time         = None       # エントリー時刻（タイムアウト計測用）
    trader._timeout_exit_mode  = False      # タイムアウト強制決済モード
    trader._last_mid           = 0.0        # cancel失敗時のfallback mid価格

    # 統計
    trader._tick_count         = 0
    trader._trade_count        = 0
    trader._start_time         = datetime.now()

    return trader


# ─────────────────────────────────────────────────────────────
# 1. _chase_side() のテスト
# ─────────────────────────────────────────────────────────────

class TestChaseSide(unittest.TestCase):
    """bid+N / ask-N チェイスロジックの単体テスト。"""

    def setUp(self):
        self.trader = _make_trader()

    # ── BUY チェイス ─────────────────────────────────────────

    def test_buy_first_tick_places_mid(self):
        """BUY: 初回は mid（int((bid+ask)/2)）に発注される。"""
        self.trader._chase_side("BUY", bid=100, ask=105)
        self.assertEqual(self.trader._pending_side, "BUY")
        self.assertEqual(self.trader._chase_count, 1)
        self.assertEqual(self.trader._pending_price, 102.0)   # int((100+105)/2)=102

    def test_buy_second_tick_chases_toward_ask(self):
        """BUY: 同じ側が続くと chase_count が増えて mid+1 になる。"""
        self.trader._chase_side("BUY", bid=100, ask=105)
        self.trader._chase_side("BUY", bid=100, ask=105)
        self.assertEqual(self.trader._chase_count, 2)
        self.assertEqual(self.trader._pending_price, 103.0)   # mid+1=103

    def test_buy_price_capped_below_ask(self):
        """BUY: ask-tick を超えないようにキャップされる（Taker にならない）。"""
        # bid=100, ask=102 → bid+3=103 だが ask-tick=101 にキャップ
        self.trader._chase_count = 2  # 次は3回目
        self.trader._pending_side = "BUY"
        self.trader._chase_side("BUY", bid=100, ask=102)
        self.assertEqual(self.trader._pending_price, 101.0)   # ask-tick

    def test_buy_cancels_when_spread_too_narrow(self):
        """BUY: スプレッドが1tick しかない場合（bid+1 >= ask）はキャンセル。"""
        # bid=100, ask=101 → bid+1=101=ask → 発注不可
        self.trader._chase_side("BUY", bid=100, ask=101)
        self.assertIsNone(self.trader._pending_side)
        self.assertEqual(self.trader._chase_count, 0)

    # ── SELL チェイス ────────────────────────────────────────

    def test_sell_first_tick_places_mid_plus_1(self):
        """SELL: 初回は mid+1（int((bid+ask)/2)+1）に発注される。"""
        self.trader._chase_side("SELL", bid=100, ask=105)
        self.assertEqual(self.trader._pending_side, "SELL")
        self.assertEqual(self.trader._chase_count, 1)
        self.assertEqual(self.trader._pending_price, 103.0)   # int((100+105)/2)+1=103

    def test_sell_second_tick_chases_toward_bid(self):
        """SELL: 同じ側が続くと chase_count が増えて mid になる。"""
        self.trader._chase_side("SELL", bid=100, ask=105)
        self.trader._chase_side("SELL", bid=100, ask=105)
        self.assertEqual(self.trader._chase_count, 2)
        self.assertEqual(self.trader._pending_price, 102.0)   # mid+1-1=102

    def test_sell_price_floored_above_bid(self):
        """SELL: bid+tick を下回らないようにフロアされる（Taker にならない）。"""
        # bid=100, ask=102 → ask-3=99 だが bid+tick=101 にフロア
        self.trader._chase_count = 2
        self.trader._pending_side = "SELL"
        self.trader._chase_side("SELL", bid=100, ask=102)
        self.assertEqual(self.trader._pending_price, 101.0)   # bid+tick

    def test_sell_cancels_when_spread_too_narrow(self):
        """SELL: スプレッドが1tick しかない場合はキャンセル。"""
        # bid=100, ask=101 → ask-1=100=bid → 発注不可
        self.trader._chase_side("SELL", bid=100, ask=101)
        self.assertIsNone(self.trader._pending_side)
        self.assertEqual(self.trader._chase_count, 0)

    # ── サイド切り替え ───────────────────────────────────────

    def test_switch_from_buy_to_sell_resets_chase(self):
        """BUY から SELL に切り替わったとき chase_count がリセットされる。"""
        # BUY を2回チェイス
        self.trader._chase_side("BUY", bid=100, ask=110)
        self.trader._chase_side("BUY", bid=100, ask=110)
        self.assertEqual(self.trader._chase_count, 2)

        # SELL に切り替え
        self.trader._chase_side("SELL", bid=100, ask=110)
        self.assertEqual(self.trader._pending_side, "SELL")
        self.assertEqual(self.trader._chase_count, 1)
        self.assertEqual(self.trader._pending_price, 106.0)   # int((100+110)/2)+1=106

    def test_switch_cancels_previous_order(self):
        """サイド切り替え時に前の注文がキャンセルされる（dry_run=False）。"""
        # BUY 注文を出す
        self.trader._chase_side("BUY", bid=100, ask=110)
        prev_id = self.trader._pending_cl_ord_id

        # SELL に切り替え → cancel_order が呼ばれるはず
        self.trader._chase_side("SELL", bid=100, ask=110)
        self.trader.client.cancel_order.assert_called_once_with(prev_id, SYMBOL)

    def test_no_reorder_when_price_unchanged(self):
        """価格が変わっていなければ再発注しない。"""
        self.trader._chase_side("BUY", bid=100, ask=110)
        self.trader.client.place_limit_order.reset_mock()

        # 同じ bid/ask でもう一度（chase_count=2 → mid+1=106、前回は mid=105 なので発注）
        # 価格変化なし のケース: _pending_price をあらかじめ設定
        self.trader._pending_price = 106.0   # 次のチェイス価格と同じにする（mid+1=106）
        self.trader._chase_side("BUY", bid=100, ask=110)   # chase_count=2, new_price=106
        # 価格が同じなら place_limit_order は呼ばれない
        self.trader.client.place_limit_order.assert_not_called()


# ─────────────────────────────────────────────────────────────
# 2. _manage_orders() のテスト
# ─────────────────────────────────────────────────────────────

class TestManageOrders(unittest.TestCase):
    """ポジション対応の注文管理ロジック。"""

    BID = 10_000_000.0
    ASK = 10_000_010.0
    MID = 10_000_005.0

    def setUp(self):
        self.trader = _make_trader()

    def _call(self, signal: int, confidence: float = 0.80):
        self.trader._manage_orders(signal, confidence, self.BID, self.ASK, self.MID)

    # ── ポジションなし ───────────────────────────────────────

    def test_no_pos_buy_signal_places_buy(self):
        """ポジションなし + BUY → BUY 発注（mid から）。"""
        self._call(signal=1)
        self.assertEqual(self.trader._pending_side, "BUY")
        self.assertEqual(self.trader._pending_price, int(self.MID))  # 10_000_005

    def test_no_pos_sell_signal_places_sell(self):
        """ポジションなし + SELL → SELL 発注（mid+1 から）。"""
        self._call(signal=-1)
        self.assertEqual(self.trader._pending_side, "SELL")
        self.assertEqual(self.trader._pending_price, int(self.MID) + 1)  # 10_000_006

    def test_no_pos_hold_cancels_pending(self):
        """ポジションなし + HOLD → pending をキャンセル。"""
        # 先に BUY 注文を出す
        self._call(signal=1)
        self.assertIsNotNone(self.trader._pending_cl_ord_id)

        self._call(signal=0)
        self.assertIsNone(self.trader._pending_side)
        self.assertIsNone(self.trader._pending_cl_ord_id)

    def test_no_pos_low_confidence_treated_as_hold(self):
        """確信度が閾値未満 → HOLD 扱いでキャンセル。"""
        self._call(signal=1)
        self.trader.client.cancel_order.reset_mock()

        self._call(signal=1, confidence=0.50)   # threshold=0.70 未満
        self.assertIsNone(self.trader._pending_side)

    # ── ロング保有中 ─────────────────────────────────────────

    def test_long_sell_signal_places_sell_to_close(self):
        """ロング保有中 + SELL → SELL 発注（決済、mid+1 から）。"""
        self.trader._position_qty = 0.001
        self._call(signal=-1)
        self.assertEqual(self.trader._pending_side, "SELL")
        self.assertEqual(self.trader._pending_price, int(self.MID) + 1)  # 10_000_006

    def test_long_buy_signal_cancels_buy_waits(self):
        """ロング保有中 + BUY → 追加 BUY 発注しない、待機。"""
        self.trader._position_qty = 0.001
        # ロング保有中に既存 BUY pending がある（誤状態）
        self.trader._pending_side       = "BUY"
        self.trader._pending_price      = self.BID + 1
        self.trader._pending_cl_ord_id  = "stale-buy-id"

        self._call(signal=1)
        # 余分な BUY pending はキャンセルされる
        self.assertIsNone(self.trader._pending_side)
        self.trader.client.cancel_order.assert_called_once_with("stale-buy-id", SYMBOL)

    def test_long_hold_does_not_cancel_sell_close(self):
        """ロング保有中 + HOLD → 決済用 SELL pending は維持される。"""
        self.trader._position_qty       = 0.001
        self.trader._pending_side       = "SELL"
        self.trader._pending_price      = self.ASK - 1
        self.trader._pending_cl_ord_id  = "sell-close-id"
        self.trader._chase_count        = 1

        self._call(signal=0)   # HOLD
        # SELL（決済注文）はキャンセルしない
        self.trader.client.cancel_order.assert_not_called()
        self.assertEqual(self.trader._pending_side, "SELL")

    # ── ショート保有中 ───────────────────────────────────────

    def test_short_buy_signal_places_buy_to_close(self):
        """ショート保有中 + BUY → BUY 発注（決済、mid から）。"""
        self.trader._position_qty = -0.001
        self._call(signal=1)
        self.assertEqual(self.trader._pending_side, "BUY")
        self.assertEqual(self.trader._pending_price, int(self.MID))  # 10_000_005

    def test_short_sell_signal_cancels_sell_waits(self):
        """ショート保有中 + SELL → 追加 SELL 発注しない、待機。"""
        self.trader._position_qty       = -0.001
        self.trader._pending_side       = "SELL"
        self.trader._pending_price      = self.ASK - 1
        self.trader._pending_cl_ord_id  = "stale-sell-id"

        self._call(signal=-1)
        self.assertIsNone(self.trader._pending_side)
        self.trader.client.cancel_order.assert_called_once_with("stale-sell-id", SYMBOL)

    def test_short_hold_does_not_cancel_buy_close(self):
        """ショート保有中 + HOLD → 決済用 BUY pending は維持される。"""
        self.trader._position_qty       = -0.001
        self.trader._pending_side       = "BUY"
        self.trader._pending_price      = self.BID + 1
        self.trader._pending_cl_ord_id  = "buy-close-id"
        self.trader._chase_count        = 1

        self._call(signal=0)   # HOLD
        self.trader.client.cancel_order.assert_not_called()
        self.assertEqual(self.trader._pending_side, "BUY")

    # ── chase 継続 ───────────────────────────────────────────

    def test_consecutive_buy_signals_increment_chase(self):
        """BUY シグナルが続く → 毎 tick chase_count が増える。"""
        for expected_chase in range(1, 5):
            self._call(signal=1)
            self.assertEqual(self.trader._chase_count, expected_chase)

    def test_consecutive_sell_signals_increment_chase(self):
        """SELL シグナルが続く → 毎 tick chase_count が増える。"""
        for expected_chase in range(1, 5):
            self._call(signal=-1)
            self.assertEqual(self.trader._chase_count, expected_chase)

    # ── タイムアウト決済モード ───────────────────────────────

    def test_timeout_mode_overrides_hold_to_close_long(self):
        """タイムアウトモード中: HOLD シグナルでもロングを SELL で決済チェイス。"""
        self.trader._position_qty      = 0.001
        self.trader._timeout_exit_mode = True
        self._call(signal=0)   # HOLD
        # timeout_exit_mode が SELL を強制する
        self.assertEqual(self.trader._pending_side, "SELL")

    def test_timeout_mode_overrides_buy_to_close_long(self):
        """タイムアウトモード中: BUY シグナルでもロングを SELL で決済。"""
        self.trader._position_qty      = 0.001
        self.trader._timeout_exit_mode = True
        self._call(signal=1)   # BUY（同方向でも決済に転換）
        self.assertEqual(self.trader._pending_side, "SELL")

    def test_timeout_mode_overrides_hold_to_close_short(self):
        """タイムアウトモード中: HOLD シグナルでもショートを BUY で決済チェイス。"""
        self.trader._position_qty      = -0.001
        self.trader._timeout_exit_mode = True
        self._call(signal=0)   # HOLD
        self.assertEqual(self.trader._pending_side, "BUY")

    def test_timeout_mode_resets_when_position_closed(self):
        """タイムアウトモード中にポジションが 0 になると timeout_exit_mode がリセット。"""
        self.trader._position_qty      = 0.0   # 約定済み
        self.trader._timeout_exit_mode = True
        self._call(signal=0)
        self.assertFalse(self.trader._timeout_exit_mode)

    def test_timeout_triggered_by_elapsed_time(self):
        """timeout_seconds を 0 秒に設定 → 即タイムアウトで決済モードへ移行。"""
        from datetime import timedelta
        self.trader.timeout_seconds = 1   # 1秒
        self.trader._position_qty   = 0.001
        # entry_time を 2秒前に設定して経過を模擬
        self.trader._entry_time = datetime.now() - timedelta(seconds=2)
        self._call(signal=0)   # HOLD でもタイムアウト検出
        self.assertTrue(self.trader._timeout_exit_mode)
        self.assertEqual(self.trader._pending_side, "SELL")   # 決済 SELL

    def test_no_timeout_when_disabled(self):
        """timeout_seconds=0 のとき → タイムアウトしない。"""
        from datetime import timedelta
        self.trader.timeout_seconds = 0   # 無効
        self.trader._position_qty   = 0.001
        self.trader._entry_time     = datetime.now() - timedelta(seconds=9999)
        self._call(signal=0)   # HOLD
        self.assertFalse(self.trader._timeout_exit_mode)
        # pending はキャンセル（HOLDでポジなしでなくWAIT）
        # ロング+HOLDの場合は何も発注しない（SELL pending がある場合は維持）
        self.assertIsNone(self.trader._pending_side)


# ─────────────────────────────────────────────────────────────
# 3. _sync_position() のテスト（約定検知 + 損益計算）
# ─────────────────────────────────────────────────────────────

class TestSyncPosition(unittest.TestCase):
    """約定検知と損益計算（Maker Rebate 込み）の単体テスト。"""

    ENTRY_PX = 10_000_000.0   # エントリー価格
    CLOSE_PX = 10_001_000.0   # 決済価格（+1,000 円）
    QTY      = 0.001          # 取引数量 BTC

    def setUp(self):
        self.trader = _make_trader()
        self.trader._last_placed_price = self.ENTRY_PX

    def _pos(self, qty: float, avg_buy: float = 0.0, avg_sell: float = 0.0) -> dict:
        """_sync_position() が期待する get_positions() の戻り値形式を生成。"""
        return {SYMBOL: {"qty": qty, "avg_buy": avg_buy, "avg_sell": avg_sell}}

    def _sync(self, positions: dict, mid: float = 0.0):
        self.trader.client.get_positions.return_value = positions
        self.trader._sync_position(mid)

    # ── エントリー約定 ───────────────────────────────────────

    def test_entry_long_records_entry_price(self):
        """0 → +0.001: ロングエントリー、entry_price に発注価格が記録される。"""
        self._sync(self._pos(self.QTY, avg_buy=self.ENTRY_PX))
        self.assertAlmostEqual(self.trader._entry_price, self.ENTRY_PX)
        self.assertEqual(self.trader._position_qty, self.QTY)
        self.assertEqual(self.trader._fill_count, 1)
        self.assertAlmostEqual(self.trader._realized_pnl, 0.0)   # 確定損益はまだ 0
        # タイムアウト用 entry_time が記録される
        self.assertIsNotNone(self.trader._entry_time)

    def test_entry_short_records_entry_price(self):
        """0 → -0.001: ショートエントリー、entry_price に発注価格が記録される。"""
        self._sync(self._pos(-self.QTY, avg_sell=self.ENTRY_PX))
        self.assertAlmostEqual(self.trader._entry_price, self.ENTRY_PX)
        self.assertEqual(self.trader._position_qty, -self.QTY)

    def test_no_change_no_update(self):
        """ポジション変化なし → 何も更新しない。"""
        self.trader._position_qty = self.QTY
        self._sync(self._pos(self.QTY))
        self.assertEqual(self.trader._fill_count, 0)

    # ── ロング決済の損益 ─────────────────────────────────────

    def test_close_long_profit(self):
        """ロング決済（利益）: entry<close → 正の realized_pnl。"""
        # エントリー
        self.trader._position_qty  = self.QTY
        self.trader._entry_price   = self.ENTRY_PX
        self.trader._last_placed_price = self.CLOSE_PX

        self._sync(self._pos(0.0, avg_sell=self.CLOSE_PX))

        raw_pnl   = (self.CLOSE_PX - self.ENTRY_PX) * self.QTY         # +1.0
        rebate    = (self.ENTRY_PX + self.CLOSE_PX) * self.QTY * MAKER_REBATE_RATE
        expected  = raw_pnl + rebate

        self.assertAlmostEqual(self.trader._realized_pnl, expected, places=6)
        self.assertGreater(self.trader._realized_pnl, 0)
        self.assertEqual(self.trader._fill_count, 1)
        self.assertEqual(self.trader._entry_price, 0.0)   # リセット

    def test_close_long_loss(self):
        """ロング決済（損失）: entry>close → 負の raw_pnl（rebate で一部相殺）。"""
        close_px = self.ENTRY_PX - 2000.0   # -2,000 円

        self.trader._position_qty      = self.QTY
        self.trader._entry_price       = self.ENTRY_PX
        self.trader._last_placed_price = close_px

        self._sync(self._pos(0.0))

        raw_pnl   = (close_px - self.ENTRY_PX) * self.QTY   # -2.0
        rebate    = (self.ENTRY_PX + close_px) * self.QTY * MAKER_REBATE_RATE
        expected  = raw_pnl + rebate

        self.assertAlmostEqual(self.trader._realized_pnl, expected, places=6)
        self.assertLess(self.trader._realized_pnl, 0)

    # ── ショート決済の損益 ───────────────────────────────────

    def test_close_short_profit(self):
        """ショート決済（利益）: entry>close → 正の realized_pnl。"""
        close_px = self.ENTRY_PX - 1000.0   # 価格が下落 → ショート利益

        self.trader._position_qty      = -self.QTY
        self.trader._entry_price       = self.ENTRY_PX
        self.trader._last_placed_price = close_px

        self._sync(self._pos(0.0))

        raw_pnl   = (self.ENTRY_PX - close_px) * self.QTY   # +1.0
        rebate    = (self.ENTRY_PX + close_px) * self.QTY * MAKER_REBATE_RATE
        expected  = raw_pnl + rebate

        self.assertAlmostEqual(self.trader._realized_pnl, expected, places=6)
        self.assertGreater(self.trader._realized_pnl, 0)

    def test_close_short_loss(self):
        """ショート決済（損失）: entry<close → 負の raw_pnl。
        rebate = (10M + 10.05M) * 0.001 * 0.01% ≈ 2円 なので、
        損失が rebate を上回るよう 50,000円以上の逆行を設定する。
        """
        close_px = self.ENTRY_PX + 50_000.0   # 5万円上昇 → ショート損失（rebate≈2円を大幅超過）

        self.trader._position_qty      = -self.QTY
        self.trader._entry_price       = self.ENTRY_PX
        self.trader._last_placed_price = close_px

        self._sync(self._pos(0.0))

        raw_pnl   = (self.ENTRY_PX - close_px) * self.QTY   # -50.0
        rebate    = (self.ENTRY_PX + close_px) * self.QTY * MAKER_REBATE_RATE   # ≈ +2.0
        expected  = raw_pnl + rebate  # ≈ -48円（損失がrebateを大幅に上回る）

        self.assertAlmostEqual(self.trader._realized_pnl, expected, places=6)
        self.assertLess(self.trader._realized_pnl, 0)

    # ── Maker Rebate の確認 ──────────────────────────────────

    def test_maker_rebate_is_positive_and_reasonable(self):
        """Maker Rebate（0.01%）が正の値で reasonable な大きさであること。"""
        self.trader._position_qty      = self.QTY
        self.trader._entry_price       = self.ENTRY_PX
        self.trader._last_placed_price = self.ENTRY_PX   # エントリー = 決済（ブレークイーブン）

        self._sync(self._pos(0.0))

        # raw_pnl = 0、rebate だけが残る
        rebate = self.ENTRY_PX * 2 * self.QTY * MAKER_REBATE_RATE
        self.assertAlmostEqual(self.trader._realized_pnl, rebate, places=6)
        self.assertGreater(self.trader._realized_pnl, 0)
        # 10,000,000 * 2 * 0.001 * 0.0001 = 2円
        self.assertAlmostEqual(rebate, 2.0, places=1)

    # ── fill_count の累積 ────────────────────────────────────

    def test_fill_count_increments_on_each_fill(self):
        """fill_count: エントリーで+1、決済で+1 → 計2になる。"""
        # エントリー
        self.trader._last_placed_price = self.ENTRY_PX
        self._sync(self._pos(self.QTY))
        self.assertEqual(self.trader._fill_count, 1)

        # 決済
        self.trader._last_placed_price = self.CLOSE_PX
        self._sync(self._pos(0.0))
        self.assertEqual(self.trader._fill_count, 2)

    def test_realized_pnl_accumulates_over_multiple_trades(self):
        """複数トレードの realized_pnl が累積される。"""
        # 1回目: ロング → 利益
        self.trader._last_placed_price = self.ENTRY_PX
        self._sync(self._pos(self.QTY))

        self.trader._last_placed_price = self.CLOSE_PX
        self._sync(self._pos(0.0))
        pnl_1 = self.trader._realized_pnl

        # 2回目: ショート → 利益
        self.trader._last_placed_price = self.CLOSE_PX
        self._sync(self._pos(-self.QTY))

        self.trader._last_placed_price = self.ENTRY_PX   # close < entry → ショート利益
        self._sync(self._pos(0.0))
        pnl_2 = self.trader._realized_pnl - pnl_1

        # 両トレードが正で累積されていること
        self.assertGreater(pnl_1, 0)
        self.assertGreater(pnl_2, 0)
        self.assertAlmostEqual(
            self.trader._realized_pnl, pnl_1 + pnl_2, places=6
        )

    def test_fallback_to_mid_when_no_placed_price(self):
        """last_placed_price が 0.0 のとき mid を代替で使う。"""
        self.trader._last_placed_price = 0.0   # 未発注
        mid = 9_999_000.0

        self._sync(self._pos(self.QTY), mid=mid)  # avg_buy=0 → fallback to mid
        self.assertAlmostEqual(self.trader._entry_price, mid)

    def test_unexpected_position_change_logged_but_no_crash(self):
        """ロング→ショート の直接切り替え（部分約定）: クラッシュしない。"""
        self.trader._position_qty  = self.QTY
        self.trader._entry_price   = self.ENTRY_PX
        self.trader._last_placed_price = self.CLOSE_PX

        # 0 を経由せずにショートになる（想定外）
        self._sync(self._pos(-self.QTY))
        # クラッシュせず position だけ更新
        self.assertEqual(self.trader._position_qty, -self.QTY)


# ─────────────────────────────────────────────────────────────
# 4. 統合シナリオテスト
# ─────────────────────────────────────────────────────────────

class TestIntegrationScenario(unittest.TestCase):
    """エントリー → チェイス → 約定 → 決済 の一連シナリオ。"""

    BID = 10_000_000.0
    ASK = 10_000_100.0

    def setUp(self):
        self.trader = _make_trader()

    def test_full_long_round_trip(self):
        """
        シナリオ:
          1. BUY シグナル 3 回 → mid, mid+1, mid+2 とチェイス
          2. エントリー約定 (0 → +0.001) を検知
          3. SELL シグナル → 決済 SELL 発注（mid+1 から）
          4. 決済約定 (0.001 → 0) → realized_pnl 計算
        """
        trader = self.trader
        BID, ASK = self.BID, self.ASK
        MID = int((BID + ASK) / 2)   # 10_000_050

        # ─ Step 1: BUY チェイス ─
        trader._manage_orders(1, 0.80, BID, ASK, (BID + ASK) / 2)
        self.assertEqual(trader._pending_price, MID)          # chase=1: mid+0

        trader._manage_orders(1, 0.80, BID, ASK, (BID + ASK) / 2)
        self.assertEqual(trader._pending_price, MID + 1)      # chase=2: mid+1

        trader._manage_orders(1, 0.80, BID, ASK, (BID + ASK) / 2)
        self.assertEqual(trader._pending_price, MID + 2)      # chase=3: mid+2

        entry_px = MID + 2

        # ─ Step 2: エントリー約定 ─
        trader._last_placed_price = entry_px
        trader.client.get_positions.return_value = {SYMBOL: {"qty": 0.001, "avg_buy": 0.0, "avg_sell": 0.0}}
        trader._sync_position()

        self.assertEqual(trader._position_qty, 0.001)
        self.assertAlmostEqual(trader._entry_price, entry_px)
        self.assertEqual(trader._fill_count, 1)
        self.assertAlmostEqual(trader._realized_pnl, 0.0)

        # ─ Step 3: SELL シグナル → 決済発注 ─
        trader._manage_orders(-1, 0.80, BID, ASK, (BID + ASK) / 2)
        self.assertEqual(trader._pending_side, "SELL")
        close_px = MID + 1                                    # chase=1: mid+1
        self.assertAlmostEqual(trader._pending_price, close_px)

        # ─ Step 4: 決済約定 → 損益計算 ─
        trader._last_placed_price = close_px
        trader.client.get_positions.return_value = {SYMBOL: {"qty": 0.0, "avg_buy": 0.0, "avg_sell": 0.0}}
        trader._sync_position()

        self.assertEqual(trader._position_qty, 0.0)
        self.assertEqual(trader._fill_count, 2)
        self.assertEqual(trader._entry_price, 0.0)

        raw_pnl  = (close_px - entry_px) * 0.001
        rebate   = (entry_px + close_px) * 0.001 * MAKER_REBATE_RATE
        expected = raw_pnl + rebate
        self.assertAlmostEqual(trader._realized_pnl, expected, places=6)
        self.assertGreater(trader._realized_pnl, 0,
                           msg="スプレッド内チェイス → 利益が出るはず")

    def test_full_short_round_trip(self):
        """
        シナリオ:
          1. SELL シグナル → ショートエントリー
          2. エントリー約定
          3. BUY シグナル → 決済
          4. 決済約定 → realized_pnl 計算
        """
        trader = self.trader
        BID, ASK = self.BID, self.ASK

        MID = int((BID + ASK) / 2)   # 10_000_050

        # SELL エントリー
        trader._manage_orders(-1, 0.80, BID, ASK, (BID + ASK) / 2)
        entry_px = MID + 1                                    # chase=1: mid+1
        self.assertAlmostEqual(trader._pending_price, entry_px)

        # エントリー約定
        trader._last_placed_price = entry_px
        trader.client.get_positions.return_value = {SYMBOL: {"qty": -0.001, "avg_buy": 0.0, "avg_sell": 0.0}}
        trader._sync_position()
        self.assertAlmostEqual(trader._entry_price, entry_px)

        # BUY 決済
        trader._manage_orders(1, 0.80, BID, ASK, (BID + ASK) / 2)
        close_px = MID                                        # chase=1: mid
        self.assertAlmostEqual(trader._pending_price, close_px)

        # 決済約定
        trader._last_placed_price = close_px
        trader.client.get_positions.return_value = {SYMBOL: {"qty": 0.0, "avg_buy": 0.0, "avg_sell": 0.0}}
        trader._sync_position()

        raw_pnl  = (entry_px - close_px) * 0.001
        rebate   = (entry_px + close_px) * 0.001 * MAKER_REBATE_RATE
        expected = raw_pnl + rebate
        self.assertAlmostEqual(trader._realized_pnl, expected, places=6)
        self.assertGreater(trader._realized_pnl, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
