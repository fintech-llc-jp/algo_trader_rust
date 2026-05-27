"""
Live Trader - ML モデル駆動の ExchSim ライブ取引

概要:
  1. algo_trader.ml_models DB から最新の学習済み XGBoost モデルをロード
  2. ExchSim REST API から 1秒ごとに板情報をポーリング
  3. ローリングバッファ（300行）で特徴量エンジニアリング
  4. モデルでシグナル生成
  5. Maker 指値注文（bid+N chase）を送信・管理

使い方:
    # dry-run（注文ログのみ、実際には送信しない）
    python -m evaluation.live_trader --symbol G_FX_BTCJPY

    # ライブ実行（実際に注文送信）
    python -m evaluation.live_trader --symbol G_FX_BTCJPY --live

    # 環境変数（必須）:
    #   EXCHSIM_USERNAME=xxx
    #   EXCHSIM_PASSWORD=xxx
    #   または EXCHSIM_URL=http://xxx （デフォルト: http://77.42.74.155:8080）

注意事項:
    - 最初の 60 秒はウォームアップ期間（特徴量計算に十分なデータが溜まるまで注文しない）
    - Ctrl+C で安全に停止（未約定注文をキャンセルしてから終了）
"""

import argparse
import io
import json
import logging
import os
import sys
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional, Tuple

import joblib
import numpy as np
import pandas as pd
import psycopg2
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# プロジェクト内モジュール
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.feature_engineering import FeatureEngineer
from config.settings import DatabaseConfig

# ─────────────────────────────────────────────────────────────
# ロギング設定
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# 定数
# ─────────────────────────────────────────────────────────────
DEFAULT_EXCHSIM_URL      = "http://77.42.74.155:8080"
DEFAULT_QUANTITY         = 0.001    # BTC（ユーザー指定）
DEFAULT_TICK_SIZE        = 1.0      # 1 JPY
DEFAULT_CONFIDENCE       = 0.70
DEFAULT_TIMEOUT_SECONDS  = 30       # ポジション最大保有秒数（0=無効）
DEFAULT_BOARD_DEPTH      = 5        # 板の深さ（depth_5 特徴量用）
WARMUP_ROWS              = 60       # ウォームアップに必要な最低行数
BUFFER_CAPACITY          = 350      # ローリングバッファ容量


# ─────────────────────────────────────────────────────────────
# ExchSim HTTP クライアント
# ─────────────────────────────────────────────────────────────
class ExchSimClient:
    """ExchSim REST API クライアント（Python requests ベース）"""

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._token: Optional[str] = None

        session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.3,
                      status_forcelist=[500, 502, 503, 504])
        session.mount("http://", HTTPAdapter(max_retries=retry))
        session.mount("https://", HTTPAdapter(max_retries=retry))
        self._session = session

    # ── 認証 ──────────────────────────────────────────────────
    def login(self) -> None:
        resp = self._session.post(
            f"{self.base_url}/api/auth/login",
            json={"username": self.username, "password": self.password},
            timeout=10,
        )
        resp.raise_for_status()
        self._token = resp.json()["token"]
        logger.info("ExchSim login OK")

    def _headers(self) -> dict:
        if not self._token:
            self.login()
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    # ── 板情報 ─────────────────────────────────────────────────
    def get_board(self, symbol: str, depth: int = DEFAULT_BOARD_DEPTH) -> dict:
        """板情報を取得して dict で返す。
        Returns:
            {
              "bids": [{"price": float, "quantity": float}, ...],
              "asks": [...],
              "bid_price_1": float, "ask_price_1": float,
              "mid_price": float, "spread": float,
              "bid_depth_5": float, "ask_depth_5": float,
              "order_imbalance": float,
            }
        """
        resp = self._session.get(
            f"{self.base_url}/api/market/board/{symbol}?depth={depth}",
            headers=self._headers(),
            timeout=5,
        )
        if resp.status_code == 401:
            self._token = None
            self.login()
            resp = self._session.get(
                f"{self.base_url}/api/market/board/{symbol}?depth={depth}",
                headers=self._headers(),
                timeout=5,
            )
        resp.raise_for_status()
        raw = resp.json()

        bids = raw.get("bids", [])
        asks = raw.get("asks", [])

        bid_price_1 = float(bids[0]["price"])   if bids else 0.0
        ask_price_1 = float(asks[0]["price"])   if asks else 0.0
        mid_price   = (bid_price_1 + ask_price_1) / 2.0
        spread      = ask_price_1 - bid_price_1

        bid_depth_5 = sum(float(b.get("quantity", 0)) for b in bids[:5])
        ask_depth_5 = sum(float(a.get("quantity", 0)) for a in asks[:5])
        total_depth = bid_depth_5 + ask_depth_5
        order_imbalance = (
            (bid_depth_5 - ask_depth_5) / total_depth if total_depth > 0 else 0.0
        )

        return {
            "bids":             bids,
            "asks":             asks,
            "bid_price_1":      bid_price_1,
            "ask_price_1":      ask_price_1,
            "mid_price":        mid_price,
            "spread":           spread,
            "bid_depth_5":      bid_depth_5,
            "ask_depth_5":      ask_depth_5,
            "order_imbalance":  order_imbalance,
        }

    # ── 注文 ───────────────────────────────────────────────────
    def place_limit_order(
        self, symbol: str, side: str, price: float, quantity: float
    ) -> Optional[str]:
        """指値注文を送信。cl_ord_id を返す。dry_run=True のときは None。"""
        body = {
            "symbol":   symbol,
            "side":     side,       # "BUY" | "SELL"
            "ordType":  "LIMIT",
            "price":    price,
            "quantity": quantity,
            "tif":      "GTC",
        }
        resp = self._session.post(
            f"{self.base_url}/api/orders/new",
            headers=self._headers(),
            json=body,
            timeout=5,
        )
        if resp.status_code == 401:
            self._token = None
            self.login()
            resp = self._session.post(
                f"{self.base_url}/api/orders/new",
                headers=self._headers(),
                json=body,
                timeout=5,
            )
        resp.raise_for_status()
        data = resp.json()
        return data.get("cl_ord_id") or data.get("clOrdId")

    def cancel_order(self, cl_ord_id: str, symbol: str) -> bool:
        """注文キャンセル。成功したら True。"""
        body = {"clOrdID": cl_ord_id, "symbol": symbol}
        try:
            resp = self._session.post(
                f"{self.base_url}/api/orders/cancel",
                headers=self._headers(),
                json=body,
                timeout=5,
            )
            if resp.status_code == 401:
                self._token = None
                self.login()
                resp = self._session.post(
                    f"{self.base_url}/api/orders/cancel",
                    headers=self._headers(),
                    json=body,
                    timeout=5,
                )
            return resp.status_code < 300
        except Exception as e:
            logger.warning(f"cancel_order error: {e}")
            return False

    def get_recent_executions(self, symbol: str, size: int = 100) -> list:
        """全ユーザーの直近約定を新しい順で取得する。
        Returns:
            [{"execID": str, "side": "BUY"|"SELL",
              "lastPx": float, "lastQty": float, "createdAt": str}, ...]
        """
        resp = self._session.get(
            f"{self.base_url}/api/executions/all",
            params={"symbol": symbol, "size": size, "page": 0},
            headers=self._headers(),
            timeout=5,
        )
        if resp.status_code == 401:
            self._token = None
            self.login()
            resp = self._session.get(
                f"{self.base_url}/api/executions/all",
                params={"symbol": symbol, "size": size, "page": 0},
                headers=self._headers(),
                timeout=5,
            )
        resp.raise_for_status()
        return resp.json().get("executions", [])

    def get_positions(self) -> dict:
        """
        ポジションサマリを取得。
        Returns: {symbol: {"qty": float, "avg_buy": float, "avg_sell": float}}
        """
        resp = self._session.get(
            f"{self.base_url}/api/positions/summary",
            headers=self._headers(),
            timeout=5,
        )
        if resp.status_code == 401:
            self._token = None
            self.login()
            resp = self._session.get(
                f"{self.base_url}/api/positions/summary",
                headers=self._headers(),
                timeout=5,
            )
        resp.raise_for_status()
        data = resp.json()
        result = {}
        for pos in data.get("positions", []):
            sym = pos.get("symbol", "")
            result[sym] = {
                "qty":      float(pos.get("netQty", 0.0)),
                "avg_buy":  float(pos.get("averageBuyPrice",  0.0)),
                "avg_sell": float(pos.get("averageSellPrice", 0.0)),
            }
        return result


# ─────────────────────────────────────────────────────────────
# DB からモデルをロード
# ─────────────────────────────────────────────────────────────
def load_latest_model(symbol: str, model_id: Optional[int] = None) -> Tuple[object, list]:
    """
    algo_trader.ml_models テーブルから最新モデルをロード。
    Returns: (xgboost_model_with_scaler_dict, feature_columns)
    """
    conn = psycopg2.connect(DatabaseConfig.get_algo_trader_connection_string())
    try:
        with conn.cursor() as cur:
            if model_id is not None:
                cur.execute(
                    "SELECT model_data, metrics FROM ml_models WHERE id = %s",
                    (model_id,)
                )
            else:
                cur.execute(
                    """
                    SELECT model_data, metrics
                    FROM   ml_models
                    WHERE  symbol = %s
                    ORDER  BY trained_at DESC
                    LIMIT  1
                    """,
                    (symbol,)
                )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"No model found for symbol={symbol}")
            model_bytes, metrics = row
    finally:
        conn.close()

    # joblib で逆シリアライズ
    payload = joblib.load(io.BytesIO(bytes(model_bytes)))
    model          = payload["model"]
    scaler         = payload["scaler"]
    feature_cols   = payload["feature_columns"]

    logger.info(
        f"Model loaded: {len(feature_cols)} features, "
        f"metrics={json.dumps(metrics, ensure_ascii=False) if metrics else 'N/A'}"
    )
    return model, scaler, feature_cols


# ─────────────────────────────────────────────────────────────
# ローリングバッファ
# ─────────────────────────────────────────────────────────────
class RollingBuffer:
    """板情報を 1行ずつ追加し、特徴量計算用の DataFrame を返す。"""

    # 板から得られる列のみ（約定データは 0 で補完）
    BASE_COLUMNS = [
        "timestamp", "symbol",
        "bid_price_1", "ask_price_1",
        "spread", "mid_price",
        "bid_depth_5", "ask_depth_5",
        "order_imbalance",
        # 約定データ（ExchSimからは取得できないため0固定）
        "exec_price_buy", "exec_price_sell", "exec_price_all",
        "exec_price_weighted_buy", "exec_price_weighted_sell",
        "volume_total",
    ]

    def __init__(self, symbol: str, capacity: int = BUFFER_CAPACITY):
        self.symbol   = symbol
        self.capacity = capacity
        self._rows: deque = deque(maxlen=capacity)

    def add(self, board: dict, exec_agg: Optional[dict] = None) -> None:
        """板情報と（あれば）約定集計をバッファに1行追加する。

        Args:
            board:    get_board() の戻り値
            exec_agg: _aggregate_executions() の戻り値（なければ全フィールド 0）
        """
        agg = exec_agg or {}
        row = {
            "timestamp":                 pd.Timestamp.now(tz=timezone.utc),
            "symbol":                    self.symbol,
            "bid_price_1":               board["bid_price_1"],
            "ask_price_1":               board["ask_price_1"],
            "spread":                    board["spread"],
            "mid_price":                 board["mid_price"],
            "bid_depth_5":               board["bid_depth_5"],
            "ask_depth_5":               board["ask_depth_5"],
            "order_imbalance":           board["order_imbalance"],
            # 約定データ（取得できた場合は実値、なければ 0）
            "exec_price_buy":            agg.get("exec_price_buy",           0.0),
            "exec_price_sell":           agg.get("exec_price_sell",          0.0),
            "exec_price_all":            agg.get("exec_price_all",           0.0),
            "exec_price_weighted_buy":   agg.get("exec_price_weighted_buy",  0.0),
            "exec_price_weighted_sell":  agg.get("exec_price_weighted_sell", 0.0),
            "volume_total":              agg.get("volume_total",             0.0),
        }
        self._rows.append(row)

    def is_warm(self) -> bool:
        return len(self._rows) >= WARMUP_ROWS

    def get_df(self) -> pd.DataFrame:
        return pd.DataFrame(list(self._rows))

    def __len__(self):
        return len(self._rows)


# ─────────────────────────────────────────────────────────────
# メインのライブトレーダー
# ─────────────────────────────────────────────────────────────
class LiveTrader:
    """
    ML モデルで 1秒ごとにシグナルを生成し、
    Maker 指値注文（bid+N chase）で ExchSim と取引する。
    """

    def __init__(
        self,
        symbol: str,
        exchsim_url: str,
        username: str,
        password: str,
        quantity: float = DEFAULT_QUANTITY,
        confidence_threshold: float = DEFAULT_CONFIDENCE,
        tick_size: float = DEFAULT_TICK_SIZE,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        model_id: Optional[int] = None,
        dry_run: bool = True,
    ):
        self.symbol               = symbol
        self.quantity             = quantity
        self.confidence_threshold = confidence_threshold
        self.tick_size            = tick_size
        self.timeout_seconds      = timeout_seconds   # 0=無効
        self.dry_run              = dry_run

        # クライアント・モデル
        self.client = ExchSimClient(exchsim_url, username, password)
        self.buffer = RollingBuffer(symbol)
        self.fe     = FeatureEngineer()

        # モデルロード
        self.model, self.scaler, self.feature_cols = load_latest_model(symbol, model_id)
        self._model_id        = model_id          # 起動時指定（None = 常に最新）
        self._loaded_model_ts: Optional[datetime] = datetime.now()  # 現在モデルのロード時刻
        self._auto_reload_interval = 1800         # 30分ごとに新モデルを確認

        # 指値注文の状態
        self._pending_cl_ord_id: Optional[str] = None
        self._pending_side:      Optional[str] = None   # "BUY" | "SELL"
        self._pending_price:     float         = 0.0
        self._chase_count:       int           = 0
        self._last_placed_price: float         = 0.0   # 直近の発注価格（約定推定に使用）

        # ポジション状態
        self._position_qty:      float = 0.0    # + = long, - = short
        self._entry_price:       float = 0.0    # エントリー価格（約定推定値）
        self._entry_time:        Optional[datetime] = None   # エントリー時刻

        # タイムアウト決済
        self._timeout_exit_mode: bool  = False  # True の間は逆方向指値チェイスで決済

        # 損益
        self._realized_pnl:  float = 0.0   # 確定損益（円）
        self._fill_count:    int   = 0     # 約定回数（エントリー+決済の合計）

        # 直近の板中値（cancel失敗時の fallback 用）
        self._last_mid: float = 0.0

        # 約定テープ取得用（重複排除）
        self._last_exec_id: Optional[str] = None   # 前回取得の最新 execID

        # 統計
        self._tick_count     = 0
        self._trade_count    = 0
        self._start_time     = datetime.now()

    # ── メインループ ───────────────────────────────────────────
    def run(self) -> None:
        logger.info(
            f"LiveTrader start: symbol={self.symbol}, qty={self.quantity}, "
            f"conf={self.confidence_threshold}, tick={self.tick_size}, "
            f"dry_run={self.dry_run}"
        )
        if self.dry_run:
            logger.info("*** DRY-RUN MODE: 注文は送信されません ***")

        self.client.login()

        # 起動時に既存ポジションを同期（再起動後も正しい状態から開始）
        logger.info("起動時ポジション確認...")
        self._sync_position()
        if self._position_qty != 0.0:
            logger.warning(
                f"  既存ポジション検出: {self._position_qty:+.4f} BTC "
                f"@ entry≈{self._entry_price:.0f} — 逆シグナルで決済します"
            )

        try:
            while True:
                t_start = time.monotonic()
                try:
                    self._tick()
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    logger.error(f"tick error: {e}", exc_info=True)

                # 残り時間をスリープ（1秒サイクル）
                elapsed = time.monotonic() - t_start
                sleep_s = max(0.0, 1.0 - elapsed)
                time.sleep(sleep_s)

        except KeyboardInterrupt:
            logger.info("停止シグナル受信 — 未約定注文をキャンセルします...")
            self._cancel_pending()
            logger.info("LiveTrader 停止完了")

    # ── 1 ティック処理 ─────────────────────────────────────────
    def _tick(self) -> None:
        self._tick_count += 1

        # 1. 板情報取得
        board = self.client.get_board(self.symbol)
        bid   = board["bid_price_1"]
        ask   = board["ask_price_1"]
        mid   = board["mid_price"]

        if bid <= 0 or ask <= 0:
            logger.warning("Invalid board prices, skipping tick")
            return

        self._last_mid = mid   # cancel失敗時の fallback 用に保持

        # 2. 約定テープ取得・集計（dry_run でなければ毎tick）
        exec_agg = {}
        if not self.dry_run:
            exec_agg = self._aggregate_executions()

        # 3. バッファに追加（板 + 約定集計）
        self.buffer.add(board, exec_agg)

        # 4. ポジション同期（pending注文があれば毎tick、なければ10tickごと）
        if self._pending_cl_ord_id or self._tick_count % 10 == 0:
            self._sync_position(mid)

        # 5. ウォームアップ中はシグナル生成しない
        if not self.buffer.is_warm():
            remaining = WARMUP_ROWS - len(self.buffer)
            if self._tick_count % 10 == 0:
                logger.info(f"[warmup] {len(self.buffer)}/{WARMUP_ROWS} rows "
                            f"({remaining}秒後に開始)")
            return

        # 6. 特徴量生成 → シグナル判定
        signal, confidence = self._predict()

        # 7. 指値注文管理
        self._manage_orders(signal, confidence, bid, ask, mid)

        # 8. 定期ログ（含み損益 + タイムアウト残秒含む）
        if self._tick_count % 30 == 0:
            sig_str  = {1: "BUY↑", -1: "SELL↓", 0: "HOLD─"}.get(signal, "?")
            pos_str  = (f"+{self._position_qty:.4f}" if self._position_qty >= 0
                        else f"{self._position_qty:.4f}")
            pend_str = (f"{self._pending_side}@{self._pending_price:.0f}(×{self._chase_count})"
                        if self._pending_side else "none")
            # 含み損益
            if self._position_qty != 0.0 and self._entry_price > 0:
                unreal = (mid - self._entry_price) * self._position_qty
                unreal_str = f"{unreal:+.0f}円"
            else:
                unreal_str = "±0円"
            # タイムアウト残秒
            if self._timeout_exit_mode:
                timeout_str = "⏰EXIT中"
            elif self._entry_time and self.timeout_seconds > 0:
                remain = self.timeout_seconds - (datetime.now() - self._entry_time).total_seconds()
                timeout_str = f"⏱{remain:.0f}s"
            else:
                timeout_str = ""
            logger.info(
                f"[tick={self._tick_count}] mid={mid:.0f} sig={sig_str} conf={confidence:.3f} "
                f"pos={pos_str} entry={self._entry_price:.0f} "
                f"含み={unreal_str} 確定={self._realized_pnl:+.0f}円 "
                f"pending={pend_str} fills={self._fill_count} {timeout_str}"
            )

        # 9. 自動モデルリロードチェック（30分ごと・ポジションなし時のみ）
        self._check_and_reload_model()

    # ── 自動モデルリロード ─────────────────────────────────────
    def _check_and_reload_model(self) -> None:
        """
        ポジションなし・かつ一定時間経過時に DB で新しいモデルを確認し、
        あれば自動でリロードする。model_id 指定起動時はスキップ。
        """
        # model_id 明示指定の場合はスキップ（固定モデル運用）
        if self._model_id is not None:
            return
        # ポジション保有中はスキップ（途中切替を避ける）
        if self._position_qty != 0.0:
            return
        # 前回チェックから _auto_reload_interval 秒未満はスキップ
        if (datetime.now() - self._loaded_model_ts).total_seconds() < self._auto_reload_interval:
            return

        try:
            conn = psycopg2.connect(DatabaseConfig.get_algo_trader_connection_string())
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, trained_at, metrics
                        FROM   ml_models
                        WHERE  symbol = %s
                        ORDER  BY trained_at DESC
                        LIMIT  1
                        """,
                        (self.symbol,)
                    )
                    row = cur.fetchone()
            finally:
                conn.close()

            if row is None:
                return

            latest_id, latest_trained_at, latest_metrics = row
            current_acc = None
            new_acc     = None
            try:
                # 現在のモデル精度を metrics から取得（起動時ログに記録済み）
                if latest_metrics and "validation_accuracy" in latest_metrics:
                    new_acc = float(latest_metrics["validation_accuracy"])
            except Exception:
                pass

            # 現在のモデルより新しければリロード
            if latest_trained_at > self._loaded_model_ts:
                logger.info(
                    f"  🔄 新しいモデル検出: id={latest_id} "
                    f"trained_at={latest_trained_at.strftime('%Y-%m-%d %H:%M')} "
                    f"accuracy={new_acc:.4f if new_acc else 'N/A'} → リロード"
                )
                self.model, self.scaler, self.feature_cols = load_latest_model(self.symbol)
                self._loaded_model_ts = datetime.now()
                logger.info(f"  ✅ モデルリロード完了 (id={latest_id})")
            else:
                logger.info(
                    f"  ✓ モデル確認: 最新モデル id={latest_id} は既にロード済み"
                )
                self._loaded_model_ts = datetime.now()  # チェック時刻を更新

        except Exception as e:
            logger.warning(f"  ⚠ モデル自動リロード確認エラー: {e}")

    # ── 約定テープ取得・集計 ────────────────────────────────────
    def _aggregate_executions(self) -> dict:
        """
        /api/executions/all から前回取得以降の新規約定を取り出し、
        1 tick 分の exec 集計値を返す。

        Returns:
            {
              "exec_price_buy":           float,  # 買い約定の単純平均価格
              "exec_price_sell":          float,  # 売り約定の単純平均価格
              "exec_price_all":           float,  # 全約定の単純平均価格
              "exec_price_weighted_buy":  float,  # 買い約定の数量加重平均価格
              "exec_price_weighted_sell": float,  # 売り約定の数量加重平均価格
              "volume_total":             float,  # 総約定数量
            }
            約定がなかった場合は空 dict（→ buffer では全フィールド 0）
        """
        try:
            execs = self.client.get_recent_executions(self.symbol, size=100)
        except Exception as e:
            logger.debug(f"exec fetch failed: {e}")
            return {}

        if not execs:
            return {}

        # 新規約定のみ抽出（API は新しい順なので先頭が最新）
        new_execs: list = []
        for ex in execs:
            if ex["execID"] == self._last_exec_id:
                break          # ここ以降は前回取得済み → 停止
            new_execs.append(ex)

        if not new_execs:
            return {}

        # 次回呼び出し用に最新 ID を記録
        self._last_exec_id = execs[0]["execID"]

        buys  = [e for e in new_execs if e["side"] == "BUY"]
        sells = [e for e in new_execs if e["side"] == "SELL"]

        result: dict = {}

        if buys:
            buy_px  = [e["lastPx"]  for e in buys]
            buy_qty = [e["lastQty"] for e in buys]
            result["exec_price_buy"]          = float(np.mean(buy_px))
            result["exec_price_weighted_buy"] = float(
                np.average(buy_px, weights=buy_qty)
            )

        if sells:
            sell_px  = [e["lastPx"]  for e in sells]
            sell_qty = [e["lastQty"] for e in sells]
            result["exec_price_sell"]          = float(np.mean(sell_px))
            result["exec_price_weighted_sell"] = float(
                np.average(sell_px, weights=sell_qty)
            )

        all_px  = [e["lastPx"]  for e in new_execs]
        all_qty = [e["lastQty"] for e in new_execs]
        result["exec_price_all"] = float(np.mean(all_px))
        result["volume_total"]   = float(sum(all_qty))

        logger.debug(
            f"  exec_agg: {len(new_execs)}件 "
            f"buy={len(buys)} sell={len(sells)} "
            f"vol={result['volume_total']:.4f}"
        )
        return result

    # ── ML 予測 ────────────────────────────────────────────────
    def _predict(self) -> Tuple[int, float]:
        """
        Returns: (signal, confidence)
          signal: 1=BUY, 0=HOLD, -1=SELL
        """
        df = self.buffer.get_df()
        try:
            df_feat = self.fe.engineer_features(df)
            # Inf は fillna(0) では除去されないので明示的に置換
            df_feat = df_feat.replace([np.inf, -np.inf], 0.0)
        except Exception as e:
            logger.debug(f"feature engineering error: {e}")
            return 0, 0.0

        # feature_cols に含まれる列だけを抽出（順序保持）
        available = [c for c in self.feature_cols if c in df_feat.columns]
        missing   = [c for c in self.feature_cols if c not in df_feat.columns]
        if missing:
            # 欠損特徴量は 0 で補完
            for c in missing:
                df_feat[c] = 0.0

        # mid_price と timestamp はスケーラー学習時に除外されているため、ここでも除外
        # （モデルの feature_columns がこれらを含む場合のバージョン差を吸収）
        EXCLUDE_FROM_SCALER = {"mid_price", "timestamp"}
        use_cols = [c for c in self.feature_cols if c not in EXCLUDE_FROM_SCALER]
        # use_cols に含まれる列が df_feat に存在するか補完
        for c in use_cols:
            if c not in df_feat.columns:
                df_feat[c] = 0.0

        X = df_feat[use_cols].iloc[[-1]].values   # 最新行だけ
        # NaN・±Inf をすべて 0 に置換（exec 特徴量のゼロ除算で Inf が生まれる場合がある）
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        X_scaled = self.scaler.transform(X)

        raw_pred  = int(self.model.predict(X_scaled)[0])         # 0,1,2
        raw_proba = self.model.predict_proba(X_scaled)[0]        # 長さ 2 or 3

        confidence = float(raw_proba.max())
        signal     = raw_pred - 1     # 0→SELL(-1), 1→HOLD(0), 2→BUY(1)

        return signal, confidence

    # ── 指値注文管理 ───────────────────────────────────────────
    def _manage_orders(
        self, signal: int, confidence: float,
        bid: float, ask: float, mid: float
    ) -> None:
        """
        ポジション対応の指値注文管理。

        ポジションなし:
          BUY シグナル  → BUY limit chase（bid+N、ask 未満）でエントリー
          SELL シグナル → SELL limit chase（ask-N、bid 超）でエントリー
          HOLD          → pending をキャンセル

        ロングポジション保有中:
          SELL シグナル → SELL limit chase で決済（逆シグナルで出口）
          BUY / HOLD    → pending をキャンセルして待機（ポジション追加しない）

        ショートポジション保有中:
          BUY シグナル  → BUY limit chase で決済（逆シグナルで出口）
          SELL / HOLD   → pending をキャンセルして待機（ポジション追加しない）

        タイムアウト（timeout_seconds 経過）:
          ポジション保有中に時間超過 → 逆方向指値チェイスで強制決済
          シグナルに関係なく決済チェイスを継続（HOLD でもキャンセルしない）
        """
        effective_signal = signal if confidence >= self.confidence_threshold else 0
        pos = self._position_qty

        # ── タイムアウト検出（シグナル適応型） ──────────────────
        if (self.timeout_seconds > 0
                and pos != 0.0
                and self._entry_time is not None
                and not self._timeout_exit_mode):
            elapsed = (datetime.now() - self._entry_time).total_seconds()
            if elapsed >= self.timeout_seconds:
                # ポジションと同方向の強いシグナルがあれば延長（モデルがまだ正しいと判断）
                same_dir = (pos > 0 and effective_signal == 1) or (pos < 0 and effective_signal == -1)
                if same_dir:
                    # タイマーをリセットして延長（最大1回分 timeout_seconds 延長）
                    self._entry_time = datetime.now()
                    logger.info(
                        f"  ⏱ タイムアウト延長: {elapsed:.0f}秒経過だがシグナル継続中"
                        f"({'BUY↑' if effective_signal == 1 else 'SELL↓'} conf={confidence:.3f})"
                        f" → {self.timeout_seconds}秒延長"
                    )
                else:
                    # 逆シグナル or HOLD → タイムアウト決済開始
                    self._timeout_exit_mode = True
                    reason = (
                        "逆シグナル検出" if (
                            (pos > 0 and effective_signal == -1) or
                            (pos < 0 and effective_signal == 1)
                        ) else "HOLDシグナル"
                    )
                    logger.info(
                        f"  ⏰ タイムアウト ({elapsed:.0f}秒経過, {reason}) → "
                        f"指値チェイス決済モード開始 "
                        f"(pos={'ロング' if pos > 0 else 'ショート'} {pos:+.4f})"
                    )

        # タイムアウト決済モード: シグナルを決済方向に上書き
        if self._timeout_exit_mode:
            if pos == 0.0:
                self._timeout_exit_mode = False   # 約定完了
            else:
                effective_signal = -1 if pos > 0 else 1  # ロング→SELL、ショート→BUY

        if pos == 0.0:
            # ── ポジションなし: 新規エントリー ──────────────────
            if effective_signal == 1:
                self._chase_side("BUY", bid, ask)
            elif effective_signal == -1:
                self._chase_side("SELL", bid, ask)
            else:
                self._cancel_pending()

        elif pos > 0:
            # ── ロング保有中: SELL シグナルで決済 ───────────────
            if effective_signal == -1:
                self._chase_side("SELL", bid, ask)
            else:
                # BUY/HOLD → 待機（追加発注しない）
                if self._pending_side == "BUY":
                    logger.debug("ロング保有中: 追加BUY → キャンセル待機")
                    self._cancel_pending()
                elif self._pending_side is None:
                    pass  # 待機中
                else:
                    pass  # SELL（決済注文）は継続

        elif pos < 0:
            # ── ショート保有中: BUY シグナルで決済 ──────────────
            if effective_signal == 1:
                self._chase_side("BUY", bid, ask)
            else:
                # SELL/HOLD → 待機（追加発注しない）
                if self._pending_side == "SELL":
                    logger.debug("ショート保有中: 追加SELL → キャンセル待機")
                    self._cancel_pending()
                elif self._pending_side is None:
                    pass  # 待機中
                else:
                    pass  # BUY（決済注文）は継続

    def _chase_side(self, side: str, bid: float, ask: float) -> None:
        """BUY/SELL の bid+N / ask-N チェイス発注。"""
        if self._pending_side == side:
            self._chase_count += 1
        else:
            self._cancel_pending()
            self._chase_count = 1
            self._pending_side = side

        mid = (bid + ask) / 2
        if side == "BUY":
            # mid から発注開始し、約定しなければ ask 方向へ 1円ずつチェイス
            # bid+1 から始めると非対称スプレッドで約定できないケースが多い
            base = int(mid)                                      # mid を切り捨て
            new_price = base + (self._chase_count - 1) * self.tick_size
            new_price = min(new_price, ask - self.tick_size)    # Taker にならない
            if new_price <= bid:
                self._cancel_pending()
                return
        else:  # SELL
            # mid から発注開始し、約定しなければ bid 方向へ 1円ずつチェイス
            base = int(mid) + 1                                  # mid を切り上げ
            new_price = base - (self._chase_count - 1) * self.tick_size
            new_price = max(new_price, bid + self.tick_size)    # Taker にならない
            if new_price >= ask:
                self._cancel_pending()
                return

        if new_price != self._pending_price:
            pos_before = self._position_qty
            self._cancel_pending_keep_state()
            # キャンセル失敗→sync でポジションが変わっていたら新規発注を中止
            if self._position_qty != pos_before:
                logger.info(
                    f"  ⚠ ポジション変化検出 "
                    f"({pos_before:+.4f} → {self._position_qty:+.4f}) "
                    f"→ 新規 {side} 発注を中止"
                )
                return
            self._place_limit(side, new_price)

    # ── 発注ヘルパー ───────────────────────────────────────────
    def _place_limit(self, side: str, price: float) -> None:
        # ── 安全ガード: 同方向への追加エントリーをブロック ──────
        pos = self._position_qty
        if pos > 0 and side == "BUY":
            logger.warning(
                f"  ⚠ 安全ガード発動: ロング({pos:+.4f})保有中の追加BUYを拒否"
            )
            self._pending_side  = None
            self._pending_price = 0.0
            self._chase_count   = 0
            return
        if pos < 0 and side == "SELL":
            logger.warning(
                f"  ⚠ 安全ガード発動: ショート({pos:+.4f})保有中の追加SELLを拒否"
            )
            self._pending_side  = None
            self._pending_price = 0.0
            self._chase_count   = 0
            return

        self._pending_price      = price
        self._last_placed_price  = price   # 約定推定価格として保存
        log_prefix = "[DRY-RUN] " if self.dry_run else ""
        logger.info(
            f"{log_prefix}→ LIMIT {side} {self.quantity} BTC @ {price:.0f} "
            f"(chase={self._chase_count})"
        )
        if self.dry_run:
            self._pending_cl_ord_id = f"dry_{side}_{price:.0f}_{self._tick_count}"
            return

        try:
            cl_ord_id = self.client.place_limit_order(
                self.symbol, side, price, self.quantity
            )
            self._pending_cl_ord_id = cl_ord_id
            self._trade_count += 1
            logger.info(f"  ✓ 注文受付: cl_ord_id={cl_ord_id}")
        except Exception as e:
            logger.error(f"  ✗ place_limit_order failed: {e}")
            self._pending_side = None
            self._pending_price = 0.0
            self._chase_count = 0

    def _cancel_pending(self) -> None:
        """未約定注文をキャンセルして状態をリセット。"""
        if self._pending_cl_ord_id and not self.dry_run:
            ok = self.client.cancel_order(self._pending_cl_ord_id, self.symbol)
            if ok:
                logger.debug(f"  ✓ キャンセル: {self._pending_cl_ord_id}")
            else:
                # キャンセル失敗 = 約定済みの可能性が高い → 即座にポジション同期
                logger.warning(
                    f"  ✗ キャンセル失敗（約定済みの可能性）: {self._pending_cl_ord_id} "
                    f"→ ポジション同期を実行"
                )
                self._sync_position(self._last_mid)
        self._pending_cl_ord_id = None
        self._pending_side      = None
        self._pending_price     = 0.0
        self._chase_count       = 0

    def _cancel_pending_keep_state(self) -> None:
        """注文IDのみキャンセル（side/chase_count は保持）。
        キャンセル失敗時はポジション同期を実行して約定を検知する。
        """
        if self._pending_cl_ord_id and not self.dry_run:
            ok = self.client.cancel_order(self._pending_cl_ord_id, self.symbol)
            if not ok:
                # キャンセル失敗 = 約定済みの可能性 → _cancel_pending() と同じく同期
                logger.warning(
                    f"  ✗ キャンセル失敗（約定済みの可能性）: {self._pending_cl_ord_id} "
                    f"→ ポジション同期を実行"
                )
                self._sync_position(self._last_mid)
        self._pending_cl_ord_id = None

    def _sync_position(self, mid: float = 0.0) -> None:
        """ExchSim からポジションを同期し、約定検知・損益計算を行う。"""
        MAKER_REBATE_RATE = 0.0001   # 0.01% 受取（GMO Maker rebate）

        try:
            positions = self.client.get_positions()
            info = positions.get(self.symbol, {"qty": 0.0, "avg_buy": 0.0, "avg_sell": 0.0})
            qty      = info["qty"]
            avg_buy  = info["avg_buy"]
            avg_sell = info["avg_sell"]

            if qty == self._position_qty:
                return

            old_qty = self._position_qty

            if old_qty == 0.0 and qty != 0.0:
                # ── エントリー約定 ───────────────────────────────
                # API の平均約定価格を優先、なければ発注価格 → mid の順
                if qty > 0:
                    fill_px = avg_buy if avg_buy > 0 else (self._last_placed_price or mid)
                else:
                    fill_px = avg_sell if avg_sell > 0 else (self._last_placed_price or mid)
                self._entry_price = fill_px
                self._entry_time  = datetime.now()   # タイムアウト計測開始
                self._fill_count += 1
                dir_str = "ロング" if qty > 0 else "ショート"
                logger.info(
                    f"  ✓ 約定[エントリー] {dir_str} {qty:+.4f} BTC @ {fill_px:.0f} "
                    f"(タイムアウト: {self.timeout_seconds}秒後)"
                    if self.timeout_seconds > 0 else
                    f"  ✓ 約定[エントリー] {dir_str} {qty:+.4f} BTC @ {fill_px:.0f}"
                )

            elif qty == 0.0 and old_qty != 0.0:
                # ── 決済約定 → 確定損益計算 ──────────────────────
                if old_qty > 0:   # ロング決済（売り）
                    fill_px = avg_sell if avg_sell > 0 else (self._last_placed_price or mid)
                    raw_pnl = (fill_px - self._entry_price) * old_qty
                else:             # ショート決済（買い戻し）
                    fill_px = avg_buy if avg_buy > 0 else (self._last_placed_price or mid)
                    raw_pnl = (self._entry_price - fill_px) * abs(old_qty)

                # Maker rebate: エントリー + 決済 両側
                rebate = (self._entry_price + fill_px) * abs(old_qty) * MAKER_REBATE_RATE
                pnl    = raw_pnl + rebate
                self._realized_pnl += pnl
                self._fill_count   += 1
                logger.info(
                    f"  ✓ 約定[決済] {old_qty:+.4f}→0 BTC @ {fill_px:.0f} | "
                    f"entry={self._entry_price:.0f} raw={raw_pnl:+.0f}円 "
                    f"rebate=+{rebate:.0f}円 → 実現={pnl:+.0f}円 "
                    f"(累計={self._realized_pnl:+.0f}円)"
                )
                self._entry_price        = 0.0
                self._entry_time         = None
                self._timeout_exit_mode  = False   # 決済完了 → リセット

            else:
                # 部分約定 or 方向転換（想定外）
                logger.warning(
                    f"  ポジション変化(想定外): {old_qty:+.4f} → {qty:+.4f} "
                    f"avg_buy={avg_buy:.0f} avg_sell={avg_sell:.0f}"
                )

            self._position_qty = qty

        except Exception as e:
            logger.warning(f"position sync failed: {e}", exc_info=True)


# ─────────────────────────────────────────────────────────────
# CLI エントリポイント
# ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="LiveTrader: ML モデル駆動の ExchSim ライブ取引",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
環境変数:
  EXCHSIM_USERNAME   ExchSim ユーザー名
  EXCHSIM_PASSWORD   ExchSim パスワード
  EXCHSIM_URL        ExchSim URL (default: http://77.42.74.155:8080)

使用例:
  # dry-run（デフォルト）
  EXCHSIM_USERNAME=u EXCHSIM_PASSWORD=p \\
    python -m evaluation.live_trader --symbol G_FX_BTCJPY

  # ライブ実行
  EXCHSIM_USERNAME=u EXCHSIM_PASSWORD=p \\
    python -m evaluation.live_trader --symbol G_FX_BTCJPY --live

  # モデルID指定
  python -m evaluation.live_trader --symbol G_FX_BTCJPY --model-id 12
        """
    )
    parser.add_argument(
        "--symbol", default="G_FX_BTCJPY",
        help="取引シンボル (default: G_FX_BTCJPY)"
    )
    parser.add_argument(
        "--live", action="store_true",
        help="ライブ実行（指定しない場合 dry-run）"
    )
    parser.add_argument(
        "--quantity", type=float, default=DEFAULT_QUANTITY,
        help=f"注文数量 BTC (default: {DEFAULT_QUANTITY})"
    )
    parser.add_argument(
        "--confidence", type=float, default=DEFAULT_CONFIDENCE,
        help=f"確信度閾値 (default: {DEFAULT_CONFIDENCE})"
    )
    parser.add_argument(
        "--tick-size", type=float, default=DEFAULT_TICK_SIZE,
        help=f"指値の最小単位 JPY (default: {DEFAULT_TICK_SIZE})"
    )
    parser.add_argument(
        "--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS,
        help=f"ポジション最大保有秒数・0=無効 (default: {DEFAULT_TIMEOUT_SECONDS})"
    )
    parser.add_argument(
        "--model-id", type=int, default=None,
        help="使用するモデルID（未指定時は最新モデル）"
    )
    parser.add_argument(
        "--url", default=None,
        help="ExchSim URL（未指定時は EXCHSIM_URL 環境変数 or デフォルト）"
    )
    args = parser.parse_args()

    # 接続情報
    exchsim_url = (
        args.url
        or os.environ.get("EXCHSIM_URL")
        or DEFAULT_EXCHSIM_URL
    )
    username = os.environ.get("EXCHSIM_USERNAME", "")
    password = os.environ.get("EXCHSIM_PASSWORD", "")

    if not username or not password:
        parser.error(
            "EXCHSIM_USERNAME と EXCHSIM_PASSWORD を環境変数に設定してください"
        )

    trader = LiveTrader(
        symbol               = args.symbol,
        exchsim_url          = exchsim_url,
        username             = username,
        password             = password,
        quantity             = args.quantity,
        confidence_threshold = args.confidence,
        tick_size            = args.tick_size,
        timeout_seconds      = args.timeout_seconds,
        model_id             = args.model_id,
        dry_run              = not args.live,
    )
    trader.run()


if __name__ == "__main__":
    main()
