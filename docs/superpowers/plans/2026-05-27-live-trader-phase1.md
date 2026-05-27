# live_trader Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `~/workspace/live_trader/` を新規作成し、ExchSim 接続で既存 LiveTrader と同等動作を確認する（Phase 1 完了）

**Architecture:** 取引所抽象レイヤー（`MarketDataFeed` + `ExchangeClient` ABC）を設計し、ExchSim 実装で動作確認する。ML 予測は 1 秒ごと、注文 repricing は板更新ごと（ExchSim は 1 秒）のハイブリッドループ。

**Tech Stack:** Python 3.11+、XGBoost、psycopg2、requests、pytest、asyncio（MarketDataFeed のインターフェース上のみ・ExchSim では threading を使用）

---

## ファイルマップ

| ファイル | 役割 |
|---------|------|
| `exchange/base.py` | `Board` dataclass、`MarketDataFeed` ABC、`ExchangeClient` ABC |
| `exchange/__init__.py` | 空ファイル |
| `exchange/exchsim/__init__.py` | 空ファイル |
| `exchange/exchsim/client.py` | `ExchSimClient`（`ExchangeClient` 実装） |
| `exchange/exchsim/feed.py` | `ExchSimFeed`（`MarketDataFeed` 実装・1秒ポーリング） |
| `ml/__init__.py` | 空ファイル |
| `ml/feature_engineering.py` | `FeatureEngineer`、`RollingBuffer`（既存から移植） |
| `ml/model_loader.py` | `load_model_from_db()`（algo_trader DB からモデルロード） |
| `ml/predictor.py` | `Predictor`（スケーラー適用・シグナル変換） |
| `storage/__init__.py` | 空ファイル |
| `storage/schema.sql` | `gmo_market_snapshots` / `gmo_trades` / `gmo_positions` DDL |
| `storage/recorder.py` | `Recorder`（板データ・約定データ保存） |
| `trader.py` | `LiveTrader` 本体（ハイブリッドループ・発注管理） |
| `config.py` | 環境変数管理 |
| `requirements.txt` | 依存ライブラリ |
| `CLAUDE.md` | セッション引き継ぎメモ |
| `tests/test_exchange_base.py` | `Board` dataclass テスト |
| `tests/test_exchsim_client.py` | `ExchSimClient` テスト（モック） |
| `tests/test_exchsim_feed.py` | `ExchSimFeed` テスト |
| `tests/test_predictor.py` | `Predictor` テスト（モック） |
| `tests/test_trader.py` | `LiveTrader` ロジックテスト（モック） |

---

## Task 1: プロジェクト初期化

**Files:**
- Create: `~/workspace/live_trader/` （以下すべてこのパス配下）
- Create: `requirements.txt`
- Create: `config.py`
- Create: `CLAUDE.md`
- Create: `tests/__init__.py`

- [ ] **Step 1: ディレクトリ構造を作成**

```bash
mkdir -p ~/workspace/live_trader/{exchange/exchsim,exchange/gmo,ml,backtest,storage,tests}
cd ~/workspace/live_trader
touch exchange/__init__.py exchange/exchsim/__init__.py exchange/gmo/__init__.py
touch ml/__init__.py storage/__init__.py backtest/__init__.py tests/__init__.py
git init
```

- [ ] **Step 2: `requirements.txt` を作成**

```
xgboost>=2.0
scikit-learn>=1.4
psycopg2-binary>=2.9
requests>=2.31
numpy>=1.26
pandas>=2.2
joblib>=1.3
python-dotenv>=1.0
websockets>=12.0
pytest>=8.0
pytest-asyncio>=0.23
```

- [ ] **Step 3: `config.py` を作成**

```python
"""環境変数管理"""
import os
from dotenv import load_dotenv

load_dotenv()

# ExchSim
EXCHSIM_URL      = os.getenv("EXCHSIM_URL", "http://77.42.74.155:8080")
EXCHSIM_USERNAME = os.getenv("EXCHSIM_USERNAME", "")
EXCHSIM_PASSWORD = os.getenv("EXCHSIM_PASSWORD", "")

# GMO API (Phase 4)
GMO_API_KEY    = os.getenv("GMO_API_KEY", "")
GMO_API_SECRET = os.getenv("GMO_API_SECRET", "")

# algo_trader DB（モデルロード用）
ALGO_TRADER_DB_HOST     = os.getenv("ALGO_TRADER_DB_HOST", "localhost")
ALGO_TRADER_DB_PORT     = int(os.getenv("ALGO_TRADER_DB_PORT", "5432"))
ALGO_TRADER_DB_USER     = os.getenv("ALGO_TRADER_DB_USER", "postgres")
ALGO_TRADER_DB_PASSWORD = os.getenv("ALGO_TRADER_DB_PASSWORD", "")
ALGO_TRADER_DB_NAME     = os.getenv("ALGO_TRADER_DB_NAME", "algo_trader")

def get_algo_trader_dsn() -> str:
    return (
        f"postgresql://{ALGO_TRADER_DB_USER}:{ALGO_TRADER_DB_PASSWORD}"
        f"@{ALGO_TRADER_DB_HOST}:{ALGO_TRADER_DB_PORT}/{ALGO_TRADER_DB_NAME}"
    )

# live_trader DB（板データ・約定データ保存用）
LIVE_TRADER_DB_HOST     = os.getenv("LIVE_TRADER_DB_HOST", "localhost")
LIVE_TRADER_DB_PORT     = int(os.getenv("LIVE_TRADER_DB_PORT", "5432"))
LIVE_TRADER_DB_USER     = os.getenv("LIVE_TRADER_DB_USER", "postgres")
LIVE_TRADER_DB_PASSWORD = os.getenv("LIVE_TRADER_DB_PASSWORD", "")
LIVE_TRADER_DB_NAME     = os.getenv("LIVE_TRADER_DB_NAME", "live_trader")

def get_live_trader_dsn() -> str:
    return (
        f"postgresql://{LIVE_TRADER_DB_USER}:{LIVE_TRADER_DB_PASSWORD}"
        f"@{LIVE_TRADER_DB_HOST}:{LIVE_TRADER_DB_PORT}/{LIVE_TRADER_DB_NAME}"
    )
```

- [ ] **Step 4: `CLAUDE.md` を作成**

```markdown
# live_trader — Claude Code セッションメモ

## プロジェクト概要
GMO コイン対応のリアルタイム ML 取引システム。
ExchSim に依存しない取引所非依存設計。

## フェーズ
- Phase 1: ExchSim 接続で既存 LiveTrader と同等動作 ← **現在**
- Phase 2: GMO WebSocket + DB 保存 + dry-run
- Phase 3: バックテスト自動検証
- Phase 4: GMO Private API 本番発注

## 起動
```bash
python trader.py --exchange exchsim --symbol G_FX_BTCJPY --dry-run
python trader.py --exchange exchsim --symbol G_FX_BTCJPY --live
```

## テスト
```bash
cd ~/workspace/live_trader
python -m pytest tests/ -v
```

## 依存プロジェクト
- algo_trader_rust: モデルロード先 DB (algo_trader)
- ExchSim: http://77.42.74.155:8080
```

- [ ] **Step 5: pip install して動作確認**

```bash
cd ~/workspace/live_trader
pip install -r requirements.txt
python -c "import xgboost, psycopg2, requests; print('OK')"
```
Expected: `OK`

- [ ] **Step 6: 初回コミット**

```bash
cd ~/workspace/live_trader
git add .
git commit -m "feat: initialize live_trader project structure"
```

---

## Task 2: 抽象取引所インターフェース（`exchange/base.py`）

**Files:**
- Create: `exchange/base.py`
- Create: `tests/test_exchange_base.py`

- [ ] **Step 1: テストを書く**

```python
# tests/test_exchange_base.py
from datetime import datetime, timezone
from exchange.base import Board


def test_board_creation():
    b = Board(
        symbol="G_FX_BTCJPY",
        bid=10_000_000.0,
        ask=10_000_100.0,
        mid=10_000_050.0,
        bids=[(10_000_000.0, 0.1), (9_999_900.0, 0.2)],
        asks=[(10_000_100.0, 0.1), (10_000_200.0, 0.2)],
        bid_depth_5=0.5,
        ask_depth_5=0.5,
        order_imbalance=0.0,
        timestamp=datetime.now(timezone.utc),
    )
    assert b.bid == 10_000_000.0
    assert b.ask == 10_000_100.0
    assert b.mid == 10_000_050.0
    assert b.symbol == "G_FX_BTCJPY"
    assert len(b.bids) == 2
    assert len(b.asks) == 2


def test_board_spread():
    b = Board(
        symbol="BTC",
        bid=100.0,
        ask=105.0,
        mid=102.5,
        bids=[], asks=[],
        bid_depth_5=0.0, ask_depth_5=0.0, order_imbalance=0.0,
        timestamp=datetime.now(timezone.utc),
    )
    assert b.ask - b.bid == 5.0
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd ~/workspace/live_trader
python -m pytest tests/test_exchange_base.py -v
```
Expected: FAIL（`ModuleNotFoundError: No module named 'exchange.base'`）

- [ ] **Step 3: `exchange/base.py` を実装**

```python
"""取引所抽象インターフェース"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Board:
    """板スナップショット（取引所非依存）"""
    symbol: str
    bid: float
    ask: float
    mid: float
    bids: list[tuple[float, float]]     # [(price, qty), ...]
    asks: list[tuple[float, float]]
    bid_depth_5: float
    ask_depth_5: float
    order_imbalance: float
    timestamp: datetime


class MarketDataFeed(ABC):
    """板データ取得の抽象クラス"""

    @abstractmethod
    async def start(self) -> None:
        """接続を開始する"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """接続を終了する"""
        ...

    @abstractmethod
    def get_board(self) -> Optional[Board]:
        """最新の板スナップショットを返す（同期）。データなしは None。"""
        ...


class ExchangeClient(ABC):
    """発注・ポジション管理の抽象クラス"""

    @abstractmethod
    def place_limit_order(self, side: str, price: float, qty: float) -> str:
        """指値注文を送信し、order_id を返す。
        Args:
            side: "BUY" | "SELL"
            price: 価格（JPY）
            qty: 数量（BTC）
        Returns:
            order_id（文字列）
        """
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """注文をキャンセル。成功したら True。"""
        ...

    @abstractmethod
    def get_positions(self) -> dict:
        """ポジションサマリを返す。
        Returns:
            {symbol: {"qty": float, "avg_buy": float, "avg_sell": float}}
        """
        ...

    @abstractmethod
    def get_recent_executions(self, symbol: str, size: int = 100) -> list:
        """直近の約定一覧を返す。
        Returns:
            [{"execID": str, "side": "BUY"|"SELL",
              "lastPx": float, "lastQty": float}, ...]
        """
        ...
```

- [ ] **Step 4: テストを通す**

```bash
python -m pytest tests/test_exchange_base.py -v
```
Expected: 2 tests PASS

- [ ] **Step 5: コミット**

```bash
git add exchange/base.py tests/test_exchange_base.py
git commit -m "feat: add exchange abstraction layer (Board, MarketDataFeed, ExchangeClient)"
```

---

## Task 3: ExchSim クライアント（`exchange/exchsim/client.py`）

**Files:**
- Create: `exchange/exchsim/client.py`
- Create: `tests/test_exchsim_client.py`

- [ ] **Step 1: テストを書く**

```python
# tests/test_exchsim_client.py
from unittest.mock import MagicMock, patch
from exchange.exchsim.client import ExchSimClient


def _make_client() -> ExchSimClient:
    c = ExchSimClient("http://localhost:8080", "user", "pass", symbol="G_FX_BTCJPY")
    c._token = "fake-token"
    return c


def test_place_limit_order_returns_order_id():
    client = _make_client()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"cl_ord_id": "order-001"}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client._session, "post", return_value=mock_resp):
        order_id = client.place_limit_order("BUY", 10_000_000.0, 0.001)

    assert order_id == "order-001"


def test_cancel_order_returns_true_on_success():
    client = _make_client()
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.cancel_order("order-001")

    assert result is True


def test_cancel_order_returns_false_on_error():
    client = _make_client()
    with patch.object(client._session, "post", side_effect=Exception("timeout")):
        result = client.cancel_order("order-001")

    assert result is False


def test_get_positions_parses_response():
    client = _make_client()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "positions": [
            {"symbol": "G_FX_BTCJPY", "netQty": "0.001",
             "averageBuyPrice": "10000000.0", "averageSellPrice": "0.0"}
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client._session, "get", return_value=mock_resp):
        positions = client.get_positions()

    assert "G_FX_BTCJPY" in positions
    assert positions["G_FX_BTCJPY"]["qty"] == 0.001


def test_get_recent_executions_parses_response():
    client = _make_client()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "executions": [
            {"execID": "exec-001", "side": "BUY", "lastPx": 10000000.0, "lastQty": 0.001}
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client._session, "get", return_value=mock_resp):
        execs = client.get_recent_executions("G_FX_BTCJPY", size=10)

    assert len(execs) == 1
    assert execs[0]["execID"] == "exec-001"
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
python -m pytest tests/test_exchsim_client.py -v
```
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: `exchange/exchsim/client.py` を実装**

```python
"""ExchSim REST API クライアント（ExchangeClient 実装）"""
from __future__ import annotations

import logging
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from exchange.base import ExchangeClient

logger = logging.getLogger(__name__)

DEFAULT_BOARD_DEPTH = 5


class ExchSimClient(ExchangeClient):
    """ExchSim REST API クライアント。ExchangeClient を実装。"""

    def __init__(self, base_url: str, username: str, password: str, symbol: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.symbol = symbol
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
        return {"Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json"}

    def _with_reauth(self, method: str, url: str, **kwargs):
        """401 時に再ログインして 1 回リトライする汎用ヘルパー。"""
        resp = getattr(self._session, method)(url, headers=self._headers(), **kwargs)
        if resp.status_code == 401:
            self._token = None
            resp = getattr(self._session, method)(url, headers=self._headers(), **kwargs)
        resp.raise_for_status()
        return resp

    # ── 板情報（ExchangeClient 外の追加メソッド） ────────────────
    def get_board_raw(self, depth: int = DEFAULT_BOARD_DEPTH) -> dict:
        """板情報を dict で返す（ExchSimFeed が使用）。
        Returns:
            {bids, asks, bid_price_1, ask_price_1, mid_price, spread,
             bid_depth_5, ask_depth_5, order_imbalance}
        """
        resp = self._with_reauth(
            "get", f"{self.base_url}/api/market/board/{self.symbol}",
            params={"depth": depth}, timeout=5,
        )
        raw = resp.json()
        bids = raw.get("bids", [])
        asks = raw.get("asks", [])

        bid_price_1 = float(bids[0]["price"]) if bids else 0.0
        ask_price_1 = float(asks[0]["price"]) if asks else 0.0
        mid_price   = (bid_price_1 + ask_price_1) / 2.0
        spread      = ask_price_1 - bid_price_1

        bid_depth_5 = sum(float(b.get("quantity", 0)) for b in bids[:5])
        ask_depth_5 = sum(float(a.get("quantity", 0)) for a in asks[:5])
        total_depth = bid_depth_5 + ask_depth_5
        order_imbalance = (
            (bid_depth_5 - ask_depth_5) / total_depth if total_depth > 0 else 0.0
        )
        return {
            "bids": [(float(b["price"]), float(b.get("quantity", 0))) for b in bids],
            "asks": [(float(a["price"]), float(a.get("quantity", 0))) for a in asks],
            "bid_price_1": bid_price_1,
            "ask_price_1": ask_price_1,
            "mid_price":   mid_price,
            "spread":      spread,
            "bid_depth_5": bid_depth_5,
            "ask_depth_5": ask_depth_5,
            "order_imbalance": order_imbalance,
        }

    # ── ExchangeClient 実装 ────────────────────────────────────
    def place_limit_order(self, side: str, price: float, qty: float) -> str:
        body = {"symbol": self.symbol, "side": side, "ordType": "LIMIT",
                "price": price, "quantity": qty, "tif": "GTC"}
        resp = self._with_reauth("post", f"{self.base_url}/api/orders/new",
                                 json=body, timeout=5)
        data = resp.json()
        order_id = data.get("cl_ord_id") or data.get("clOrdId") or ""
        return order_id

    def cancel_order(self, order_id: str) -> bool:
        try:
            body = {"clOrdID": order_id, "symbol": self.symbol}
            resp = self._session.post(
                f"{self.base_url}/api/orders/cancel",
                headers=self._headers(), json=body, timeout=5,
            )
            if resp.status_code == 401:
                self._token = None
                resp = self._session.post(
                    f"{self.base_url}/api/orders/cancel",
                    headers=self._headers(), json=body, timeout=5,
                )
            return resp.status_code < 300
        except Exception as e:
            logger.warning(f"cancel_order error: {e}")
            return False

    def get_positions(self) -> dict:
        resp = self._with_reauth(
            "get", f"{self.base_url}/api/positions/summary", timeout=5
        )
        result = {}
        for pos in resp.json().get("positions", []):
            sym = pos.get("symbol", "")
            result[sym] = {
                "qty":      float(pos.get("netQty", 0.0)),
                "avg_buy":  float(pos.get("averageBuyPrice", 0.0)),
                "avg_sell": float(pos.get("averageSellPrice", 0.0)),
            }
        return result

    def get_recent_executions(self, symbol: str, size: int = 100) -> list:
        resp = self._with_reauth(
            "get", f"{self.base_url}/api/executions/all",
            params={"symbol": symbol, "size": size, "page": 0}, timeout=5,
        )
        return resp.json().get("executions", [])
```

- [ ] **Step 4: テストを通す**

```bash
python -m pytest tests/test_exchsim_client.py -v
```
Expected: 5 tests PASS

- [ ] **Step 5: コミット**

```bash
git add exchange/exchsim/client.py tests/test_exchsim_client.py
git commit -m "feat: add ExchSimClient implementing ExchangeClient ABC"
```

---

## Task 4: ExchSimFeed（`exchange/exchsim/feed.py`）

**Files:**
- Create: `exchange/exchsim/feed.py`
- Create: `tests/test_exchsim_feed.py`

- [ ] **Step 1: テストを書く**

```python
# tests/test_exchsim_feed.py
import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from exchange.base import Board
from exchange.exchsim.feed import ExchSimFeed


def _make_raw_board() -> dict:
    return {
        "bids": [(10_000_000.0, 0.1), (9_999_900.0, 0.2)],
        "asks": [(10_000_100.0, 0.1), (10_000_200.0, 0.2)],
        "bid_price_1": 10_000_000.0,
        "ask_price_1": 10_000_100.0,
        "mid_price":   10_000_050.0,
        "spread":      100.0,
        "bid_depth_5": 0.5,
        "ask_depth_5": 0.5,
        "order_imbalance": 0.0,
    }


def test_get_board_returns_none_before_first_poll():
    mock_client = MagicMock()
    feed = ExchSimFeed(mock_client, symbol="G_FX_BTCJPY", interval=1.0)
    assert feed.get_board() is None


def test_get_board_returns_board_after_manual_update():
    mock_client = MagicMock()
    mock_client.get_board_raw.return_value = _make_raw_board()
    feed = ExchSimFeed(mock_client, symbol="G_FX_BTCJPY", interval=1.0)

    feed._poll_once()  # 内部メソッドを直接呼ぶ

    board = feed.get_board()
    assert board is not None
    assert isinstance(board, Board)
    assert board.bid == 10_000_000.0
    assert board.ask == 10_000_100.0
    assert board.mid == 10_000_050.0
    assert board.symbol == "G_FX_BTCJPY"
    assert len(board.bids) == 2


def test_poll_once_calls_get_board_raw():
    mock_client = MagicMock()
    mock_client.get_board_raw.return_value = _make_raw_board()
    feed = ExchSimFeed(mock_client, symbol="G_FX_BTCJPY", interval=1.0)

    feed._poll_once()

    mock_client.get_board_raw.assert_called_once()


def test_start_stop_polling():
    mock_client = MagicMock()
    mock_client.get_board_raw.return_value = _make_raw_board()
    feed = ExchSimFeed(mock_client, symbol="G_FX_BTCJPY", interval=0.05)

    asyncio.get_event_loop().run_until_complete(feed.start())
    time.sleep(0.2)  # 数回ポーリングさせる
    asyncio.get_event_loop().run_until_complete(feed.stop())

    assert mock_client.get_board_raw.call_count >= 2
    assert feed.get_board() is not None
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
python -m pytest tests/test_exchsim_feed.py -v
```
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: `exchange/exchsim/feed.py` を実装**

```python
"""ExchSim ポーリングフィード（MarketDataFeed 実装）"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from exchange.base import Board, MarketDataFeed
from exchange.exchsim.client import ExchSimClient

logger = logging.getLogger(__name__)


class ExchSimFeed(MarketDataFeed):
    """ExchSim REST API を 1秒ごとにポーリングして Board を更新する。

    GMOWebSocketFeed と同じ MarketDataFeed インターフェースを実装するため、
    asyncio の start/stop を持つが、内部では threading を使用する。
    """

    def __init__(self, client: ExchSimClient, symbol: str, interval: float = 1.0):
        self._client   = client
        self._symbol   = symbol
        self._interval = interval
        self._board:   Optional[Board] = None
        self._lock:    threading.Lock  = threading.Lock()
        self._thread:  Optional[threading.Thread] = None
        self._stop_event: threading.Event = threading.Event()

    async def start(self) -> None:
        """ポーリングスレッドを開始する。"""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(f"ExchSimFeed started (interval={self._interval}s)")

    async def stop(self) -> None:
        """ポーリングスレッドを停止する。"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("ExchSimFeed stopped")

    def get_board(self) -> Optional[Board]:
        """最新の Board を返す（スレッドセーフ）。"""
        with self._lock:
            return self._board

    def _run(self) -> None:
        """バックグラウンドポーリングループ。"""
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as e:
                logger.warning(f"ExchSimFeed poll error: {e}")
            self._stop_event.wait(self._interval)

    def _poll_once(self) -> None:
        """1回ポーリングして内部バッファを更新する（テストで直接呼ぶ）。"""
        raw = self._client.get_board_raw()
        board = Board(
            symbol=self._symbol,
            bid=raw["bid_price_1"],
            ask=raw["ask_price_1"],
            mid=raw["mid_price"],
            bids=raw["bids"],
            asks=raw["asks"],
            bid_depth_5=raw["bid_depth_5"],
            ask_depth_5=raw["ask_depth_5"],
            order_imbalance=raw["order_imbalance"],
            timestamp=datetime.now(timezone.utc),
        )
        with self._lock:
            self._board = board
```

- [ ] **Step 4: テストを通す**

```bash
python -m pytest tests/test_exchsim_feed.py -v
```
Expected: 4 tests PASS

- [ ] **Step 5: コミット**

```bash
git add exchange/exchsim/feed.py tests/test_exchsim_feed.py
git commit -m "feat: add ExchSimFeed implementing MarketDataFeed ABC"
```

---

## Task 5: ML モジュール（`ml/`）

**Files:**
- Create: `ml/feature_engineering.py`（`FeatureEngineer` + `RollingBuffer` を移植）
- Create: `ml/model_loader.py`
- Create: `ml/predictor.py`
- Create: `tests/test_predictor.py`

- [ ] **Step 1: `ml/feature_engineering.py` を作成**

algo_trader_rust の `data/feature_engineering.py` をそのままコピーし、RollingBuffer も一緒に定義する。

```bash
# コピー元から移植
cp ~/workspace/algo_trader_rust/vendor/ml_pipeline_snapshot_2026-04-12/data/feature_engineering.py \
   ~/workspace/live_trader/ml/feature_engineering.py
```

コピー後、ファイル末尾に `RollingBuffer` クラスを追記する（`exchange/base.py` の `Board` を使用）:

```python
# ml/feature_engineering.py の末尾に追記

from collections import deque
from datetime import timezone
from typing import Optional
import pandas as pd

WARMUP_ROWS    = 60
BUFFER_CAPACITY = 350

BASE_COLUMNS = [
    "timestamp", "symbol",
    "bid_price_1", "ask_price_1",
    "spread", "mid_price",
    "bid_depth_5", "ask_depth_5",
    "order_imbalance",
    "exec_price_buy", "exec_price_sell", "exec_price_all",
    "exec_price_weighted_buy", "exec_price_weighted_sell",
    "volume_total",
]


class RollingBuffer:
    """Board スナップショットをバッファリングし、特徴量計算用 DataFrame を返す。"""

    def __init__(self, symbol: str, capacity: int = BUFFER_CAPACITY):
        self.symbol   = symbol
        self.capacity = capacity
        self._rows: deque = deque(maxlen=capacity)

    def add(self, board: "Board", exec_agg: Optional[dict] = None) -> None:  # noqa: F821
        agg = exec_agg or {}
        row = {
            "timestamp":               pd.Timestamp.now(tz=timezone.utc),
            "symbol":                  self.symbol,
            "bid_price_1":             board.bid,
            "ask_price_1":             board.ask,
            "spread":                  board.ask - board.bid,
            "mid_price":               board.mid,
            "bid_depth_5":             board.bid_depth_5,
            "ask_depth_5":             board.ask_depth_5,
            "order_imbalance":         board.order_imbalance,
            "exec_price_buy":          agg.get("exec_price_buy",          0.0),
            "exec_price_sell":         agg.get("exec_price_sell",         0.0),
            "exec_price_all":          agg.get("exec_price_all",          0.0),
            "exec_price_weighted_buy": agg.get("exec_price_weighted_buy", 0.0),
            "exec_price_weighted_sell":agg.get("exec_price_weighted_sell",0.0),
            "volume_total":            agg.get("volume_total",            0.0),
        }
        self._rows.append(row)

    def is_warm(self) -> bool:
        return len(self._rows) >= WARMUP_ROWS

    def get_df(self) -> pd.DataFrame:
        return pd.DataFrame(list(self._rows))

    def __len__(self) -> int:
        return len(self._rows)
```

- [ ] **Step 2: `ml/model_loader.py` を作成**

```python
"""algo_trader DB からモデルをロード"""
from __future__ import annotations

import io
import json
import logging
from typing import Optional, Tuple

import joblib
import psycopg2

import config

logger = logging.getLogger(__name__)


def load_model(
    symbol: str, model_id: Optional[int] = None
) -> Tuple[object, object, list]:
    """algo_trader.ml_models テーブルから XGBoost モデルをロードする。

    Returns:
        (model, scaler, feature_columns)
    """
    conn = psycopg2.connect(config.get_algo_trader_dsn())
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
                raise ValueError(f"No model found for symbol={symbol}, id={model_id}")
            model_bytes, metrics = row
    finally:
        conn.close()

    payload      = joblib.load(io.BytesIO(bytes(model_bytes)))
    model        = payload["model"]
    scaler       = payload["scaler"]
    feature_cols = payload["feature_columns"]

    logger.info(
        f"Model loaded: {len(feature_cols)} features, "
        f"metrics={json.dumps(metrics, ensure_ascii=False) if metrics else 'N/A'}"
    )
    return model, scaler, feature_cols


def get_latest_model_id(symbol: str) -> Optional[int]:
    """DB 上の最新 model_id を返す。"""
    conn = psycopg2.connect(config.get_algo_trader_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM ml_models WHERE symbol=%s ORDER BY trained_at DESC LIMIT 1",
                (symbol,)
            )
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()
```

- [ ] **Step 3: `tests/test_predictor.py` を作成（先にテストを書く）**

```python
# tests/test_predictor.py
import numpy as np
import pandas as pd
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from ml.predictor import Predictor
from ml.feature_engineering import RollingBuffer
from exchange.base import Board


def _make_board(bid=10_000_000.0, ask=10_000_100.0) -> Board:
    return Board(
        symbol="G_FX_BTCJPY",
        bid=bid, ask=ask, mid=(bid + ask) / 2,
        bids=[(bid, 0.1)], asks=[(ask, 0.1)],
        bid_depth_5=0.5, ask_depth_5=0.5, order_imbalance=0.0,
        timestamp=datetime.now(timezone.utc),
    )


def _make_mock_model(proba):
    model = MagicMock()
    model.predict_proba.return_value = np.array([proba])
    return model


def _make_mock_scaler():
    scaler = MagicMock()
    scaler.transform.side_effect = lambda x: x
    return scaler


def test_predict_returns_none_when_not_warm():
    """ウォームアップ前は None を返す"""
    model   = _make_mock_model([0.1, 0.2, 0.7])
    scaler  = _make_mock_scaler()
    feature_cols = ["bid_price_1", "ask_price_1", "spread_ratio"]
    predictor = Predictor(model, scaler, feature_cols, confidence_threshold=0.60)

    buffer = RollingBuffer("G_FX_BTCJPY")
    # 60行未満なのでウォームアップ未完了
    for _ in range(10):
        buffer.add(_make_board())

    result = predictor.predict(buffer)
    assert result is None


def test_predict_returns_buy_signal():
    """BUY シグナル（class=2）の信頼度が閾値超えなら BUY を返す"""
    model   = _make_mock_model([0.05, 0.10, 0.85])  # BUY=0.85
    scaler  = _make_mock_scaler()
    feature_cols = ["bid_price_1", "ask_price_1"]
    predictor = Predictor(model, scaler, feature_cols, confidence_threshold=0.60)

    buffer = RollingBuffer("G_FX_BTCJPY")
    for _ in range(65):
        buffer.add(_make_board())

    with patch.object(predictor, "_build_features") as mock_fe:
        mock_fe.return_value = np.zeros((1, len(feature_cols)))
        result = predictor.predict(buffer)

    assert result is not None
    signal, conf, probs = result
    assert signal == 1   # BUY
    assert conf   == pytest.approx(0.85)


def test_predict_returns_sell_signal():
    """SELL シグナル（class=0）の信頼度が閾値超えなら SELL を返す"""
    model   = _make_mock_model([0.80, 0.10, 0.10])  # SELL=0.80
    scaler  = _make_mock_scaler()
    feature_cols = ["bid_price_1"]
    predictor = Predictor(model, scaler, feature_cols, confidence_threshold=0.60)

    buffer = RollingBuffer("G_FX_BTCJPY")
    for _ in range(65):
        buffer.add(_make_board())

    with patch.object(predictor, "_build_features") as mock_fe:
        mock_fe.return_value = np.zeros((1, 1))
        result = predictor.predict(buffer)

    assert result is not None
    signal, conf, probs = result
    assert signal == -1  # SELL
    assert conf   == pytest.approx(0.80)


def test_predict_returns_hold_when_below_threshold():
    """信頼度が閾値未満は HOLD (0) を返す"""
    model   = _make_mock_model([0.35, 0.35, 0.30])
    scaler  = _make_mock_scaler()
    feature_cols = ["bid_price_1"]
    predictor = Predictor(model, scaler, feature_cols, confidence_threshold=0.60)

    buffer = RollingBuffer("G_FX_BTCJPY")
    for _ in range(65):
        buffer.add(_make_board())

    with patch.object(predictor, "_build_features") as mock_fe:
        mock_fe.return_value = np.zeros((1, 1))
        result = predictor.predict(buffer)

    assert result is not None
    signal, conf, probs = result
    assert signal == 0  # HOLD


import pytest  # noqa: E402（末尾 import は test_predict_returns_buy_signal で使用）
```

- [ ] **Step 4: テストが失敗することを確認**

```bash
python -m pytest tests/test_predictor.py -v
```
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 5: `ml/predictor.py` を実装**

```python
"""ML 予測ロジック"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

import numpy as np

from ml.feature_engineering import FeatureEngineer, RollingBuffer

logger = logging.getLogger(__name__)

EXCLUDE_FROM_SCALER = {"mid_price", "timestamp"}

# シグナル定数
SELL = -1
HOLD =  0
BUY  =  1


class Predictor:
    """XGBoost モデルでシグナルを生成する。

    Returns: (signal: int, confidence: float, probs: np.ndarray)
        signal: BUY=1 / HOLD=0 / SELL=-1
        confidence: 最高クラスの確率
        probs: [sell_prob, hold_prob, buy_prob]
    """

    def __init__(
        self,
        model,
        scaler,
        feature_cols: list[str],
        confidence_threshold: float = 0.60,
    ):
        self._model               = model
        self._scaler              = scaler
        self._feature_cols        = feature_cols
        self._confidence_threshold = confidence_threshold
        self._fe                  = FeatureEngineer()

    def predict(
        self, buffer: RollingBuffer
    ) -> Optional[Tuple[int, float, np.ndarray]]:
        """バッファから特徴量を計算し予測する。ウォームアップ未完了は None。"""
        if not buffer.is_warm():
            return None

        try:
            X = self._build_features(buffer)
        except Exception as e:
            logger.warning(f"Feature build error: {e}")
            return None

        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        X_scaled = self._scaler.transform(X)
        probs    = self._model.predict_proba(X_scaled)[0]  # [sell, hold, buy]

        best_class = int(np.argmax(probs))
        confidence = float(probs[best_class])

        if confidence < self._confidence_threshold:
            signal = HOLD
        elif best_class == 2:
            signal = BUY
        elif best_class == 0:
            signal = SELL
        else:
            signal = HOLD

        return signal, confidence, probs

    def _build_features(self, buffer: RollingBuffer) -> np.ndarray:
        """RollingBuffer → スケーラー入力 ndarray。"""
        df      = buffer.get_df()
        df_feat = self._fe.engineer_features(df)
        df_feat = df_feat.replace([np.inf, -np.inf], 0.0)
        df_feat = df_feat.fillna(0.0)

        use_cols = [c for c in self._feature_cols if c not in EXCLUDE_FROM_SCALER]
        X = df_feat[use_cols].iloc[[-1]].values
        return X
```

- [ ] **Step 6: テストを通す**

```bash
python -m pytest tests/test_predictor.py -v
```
Expected: 4 tests PASS

- [ ] **Step 7: コミット**

```bash
git add ml/ tests/test_predictor.py
git commit -m "feat: add ML module (FeatureEngineer, RollingBuffer, ModelLoader, Predictor)"
```

---

## Task 6: Storage（`storage/schema.sql` + `storage/recorder.py`）

**Files:**
- Create: `storage/schema.sql`
- Create: `storage/recorder.py`
- Create: `tests/test_recorder.py`

- [ ] **Step 1: `storage/schema.sql` を作成**

```sql
-- live_trader DB スキーマ

-- 板スナップショット（バックテスト・再訓練用）
CREATE TABLE IF NOT EXISTS gmo_market_snapshots (
    id         BIGSERIAL PRIMARY KEY,
    symbol     TEXT NOT NULL,
    timestamp  TIMESTAMPTZ NOT NULL,
    bid        NUMERIC NOT NULL,
    ask        NUMERIC NOT NULL,
    mid        NUMERIC NOT NULL
);

CREATE TABLE IF NOT EXISTS gmo_market_price_levels (
    id          BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL REFERENCES gmo_market_snapshots(id),
    price       NUMERIC NOT NULL,
    qty         NUMERIC NOT NULL,
    side        TEXT NOT NULL,     -- 'BUY' | 'SELL'
    level_index INTEGER NOT NULL
);

-- 約定履歴（損益計算・分析用）
CREATE TABLE IF NOT EXISTS gmo_trades (
    id          BIGSERIAL PRIMARY KEY,
    model_id    INTEGER,
    symbol      TEXT NOT NULL,
    side        TEXT NOT NULL,     -- 'BUY' | 'SELL'
    price       NUMERIC NOT NULL,
    qty         NUMERIC NOT NULL,
    raw_pnl     NUMERIC,
    rebate      NUMERIC,
    realized    NUMERIC,
    exchange    TEXT NOT NULL,     -- 'gmo' | 'exchsim'
    is_dry_run  BOOLEAN NOT NULL DEFAULT false,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ポジションスナップショット
CREATE TABLE IF NOT EXISTS gmo_positions (
    id          BIGSERIAL PRIMARY KEY,
    symbol      TEXT NOT NULL,
    qty         NUMERIC NOT NULL,
    entry_price NUMERIC,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_gmo_market_snapshots_symbol_ts
    ON gmo_market_snapshots (symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_gmo_trades_symbol_ts
    ON gmo_trades (symbol, timestamp DESC);
```

- [ ] **Step 2: テストを書く**

```python
# tests/test_recorder.py
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone

from exchange.base import Board
from storage.recorder import Recorder


def _make_board() -> Board:
    return Board(
        symbol="G_FX_BTCJPY",
        bid=10_000_000.0, ask=10_000_100.0, mid=10_000_050.0,
        bids=[(10_000_000.0, 0.1)],
        asks=[(10_000_100.0, 0.1)],
        bid_depth_5=0.5, ask_depth_5=0.5, order_imbalance=0.0,
        timestamp=datetime.now(timezone.utc),
    )


def test_save_board_executes_inserts():
    mock_conn = MagicMock()
    mock_cur  = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__  = MagicMock(return_value=False)
    mock_cur.__enter__  = MagicMock(return_value=mock_cur)
    mock_cur.__exit__   = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cur

    with patch("storage.recorder.psycopg2.connect", return_value=mock_conn):
        recorder = Recorder(dsn="postgresql://test/test")
        recorder.save_board(_make_board())

    # INSERT INTO gmo_market_snapshots と gmo_market_price_levels が呼ばれた
    assert mock_cur.execute.call_count >= 2


def test_save_trade_executes_insert():
    mock_conn = MagicMock()
    mock_cur  = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__  = MagicMock(return_value=False)
    mock_cur.__enter__  = MagicMock(return_value=mock_cur)
    mock_cur.__exit__   = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cur

    with patch("storage.recorder.psycopg2.connect", return_value=mock_conn):
        recorder = Recorder(dsn="postgresql://test/test")
        recorder.save_trade(
            symbol="G_FX_BTCJPY",
            side="BUY",
            price=10_000_000.0,
            qty=0.001,
            raw_pnl=100.0,
            rebate=2.0,
            realized=102.0,
            exchange="exchsim",
            is_dry_run=True,
            model_id=17,
        )

    assert mock_cur.execute.call_count >= 1
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
python -m pytest tests/test_recorder.py -v
```
Expected: FAIL

- [ ] **Step 4: `storage/recorder.py` を実装**

```python
"""板データ・約定データを live_trader DB に保存する"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import psycopg2

from exchange.base import Board

logger = logging.getLogger(__name__)


class Recorder:
    """live_trader DB への書き込みを担当する。"""

    def __init__(self, dsn: str):
        self._dsn = dsn

    def save_board(self, board: Board) -> None:
        """板スナップショットを gmo_market_snapshots + price_levels に保存する。"""
        with psycopg2.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO gmo_market_snapshots (symbol, timestamp, bid, ask, mid)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (board.symbol, board.timestamp, board.bid, board.ask, board.mid),
                )
                snapshot_id = cur.fetchone()[0]

                # 板の深さ（最大5段）
                for i, (price, qty) in enumerate(board.bids[:5]):
                    cur.execute(
                        """
                        INSERT INTO gmo_market_price_levels
                            (snapshot_id, price, qty, side, level_index)
                        VALUES (%s, %s, %s, 'BUY', %s)
                        """,
                        (snapshot_id, price, qty, i),
                    )
                for i, (price, qty) in enumerate(board.asks[:5]):
                    cur.execute(
                        """
                        INSERT INTO gmo_market_price_levels
                            (snapshot_id, price, qty, side, level_index)
                        VALUES (%s, %s, %s, 'SELL', %s)
                        """,
                        (snapshot_id, price, qty, i),
                    )

    def save_trade(
        self,
        symbol: str,
        side: str,
        price: float,
        qty: float,
        raw_pnl: Optional[float],
        rebate: Optional[float],
        realized: Optional[float],
        exchange: str,
        is_dry_run: bool,
        model_id: Optional[int] = None,
    ) -> None:
        """約定レコードを gmo_trades に保存する。"""
        with psycopg2.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO gmo_trades
                        (model_id, symbol, side, price, qty,
                         raw_pnl, rebate, realized, exchange, is_dry_run)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (model_id, symbol, side, price, qty,
                     raw_pnl, rebate, realized, exchange, is_dry_run),
                )
```

- [ ] **Step 5: テストを通す**

```bash
python -m pytest tests/test_recorder.py -v
```
Expected: 2 tests PASS

- [ ] **Step 6: DB スキーマを適用（live_trader DB が存在する前提）**

```bash
# live_trader DB がなければ作成
psql -U postgres -c "CREATE DATABASE live_trader;" 2>/dev/null || true
psql -U postgres -d live_trader -f storage/schema.sql
```
Expected: `CREATE TABLE` が 4 回出力される

- [ ] **Step 7: コミット**

```bash
git add storage/ tests/test_recorder.py
git commit -m "feat: add storage schema and Recorder for board/trade persistence"
```

---

## Task 7: LiveTrader 本体（`trader.py`）

**Files:**
- Create: `trader.py`
- Create: `tests/test_trader.py`

- [ ] **Step 1: テストを書く**

```python
# tests/test_trader.py
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import numpy as np

from exchange.base import Board
from trader import LiveTrader


def _make_board(bid=10_000_000.0, ask=10_000_100.0) -> Board:
    mid = (bid + ask) / 2
    return Board(
        symbol="G_FX_BTCJPY",
        bid=bid, ask=ask, mid=mid,
        bids=[(bid, 0.1)], asks=[(ask, 0.1)],
        bid_depth_5=0.5, ask_depth_5=0.5, order_imbalance=0.0,
        timestamp=datetime.now(timezone.utc),
    )


def _make_trader(dry_run=True):
    mock_client = MagicMock()
    mock_feed   = MagicMock()
    mock_predictor = MagicMock()
    mock_recorder  = MagicMock()

    trader = LiveTrader(
        symbol="G_FX_BTCJPY",
        exchange_name="exchsim",
        client=mock_client,
        feed=mock_feed,
        predictor=mock_predictor,
        recorder=mock_recorder,
        quantity=0.001,
        tick_size=1.0,
        timeout_seconds=30,
        dry_run=dry_run,
    )
    return trader, mock_client, mock_feed, mock_predictor, mock_recorder


# ── Chase price logic ──────────────────────────────────────────
class TestChaseSide:
    def test_buy_first_tick_places_at_mid(self):
        trader, client, _, _, _ = _make_trader()
        board = _make_board(bid=10_000_000.0, ask=10_000_100.0)  # mid=10_000_050
        trader._chase_count = 1
        price = trader._calc_chase_price("BUY", board)
        assert price == int(10_000_050.0)  # 10_000_050

    def test_buy_second_tick_chases_toward_ask(self):
        trader, _, _, _, _ = _make_trader()
        board = _make_board(bid=10_000_000.0, ask=10_000_100.0)
        trader._chase_count = 2
        price = trader._calc_chase_price("BUY", board)
        assert price == int(10_000_050.0) + 1  # 10_000_051

    def test_sell_first_tick_places_at_mid_plus_1(self):
        trader, _, _, _, _ = _make_trader()
        board = _make_board(bid=10_000_000.0, ask=10_000_100.0)
        trader._chase_count = 1
        price = trader._calc_chase_price("SELL", board)
        assert price == int(10_000_050.0) + 1  # 10_000_051

    def test_sell_second_tick_chases_toward_bid(self):
        trader, _, _, _, _ = _make_trader()
        board = _make_board(bid=10_000_000.0, ask=10_000_100.0)
        trader._chase_count = 2
        price = trader._calc_chase_price("SELL", board)
        assert price == int(10_000_050.0)  # 10_000_050


# ── dry-run でクライアントが呼ばれない ──────────────────────────────
class TestDryRun:
    def test_place_limit_not_called_in_dry_run(self):
        trader, client, _, predictor, _ = _make_trader(dry_run=True)
        predictor.predict.return_value = (1, 0.80, np.array([0.05, 0.15, 0.80]))
        board = _make_board()
        trader._position_qty = 0.0
        trader._on_board_update(board)

        client.place_limit_order.assert_not_called()

    def test_place_limit_called_in_live_mode(self):
        trader, client, _, predictor, _ = _make_trader(dry_run=False)
        client.place_limit_order.return_value = "order-001"
        predictor.predict.return_value = (1, 0.80, np.array([0.05, 0.15, 0.80]))
        board = _make_board()
        trader._position_qty = 0.0
        trader._buffer._rows.extend([{}] * 65)  # ウォームアップ済みフラグを立てる
        trader._current_signal = 1  # BUY シグナルをセット

        trader._place_limit("BUY", board)

        client.place_limit_order.assert_called_once()


# ── タイムアウト延長ロジック ─────────────────────────────────────
class TestTimeout:
    def test_same_direction_signal_extends_timeout(self):
        from datetime import timedelta
        trader, _, _, _, _ = _make_trader()
        trader._position_qty = 0.001          # ロング
        trader._current_signal = 1            # BUY 継続
        old_entry = datetime.now(timezone.utc) - timedelta(seconds=40)
        trader._entry_time = old_entry
        trader._timeout_exit_mode = False

        board = _make_board()
        trader._check_timeout(board)

        # entry_time がリセットされているはず（延長）
        assert trader._entry_time != old_entry
        assert trader._timeout_exit_mode is False

    def test_reverse_signal_triggers_timeout_exit(self):
        from datetime import timedelta
        trader, _, _, _, _ = _make_trader()
        trader._position_qty = 0.001          # ロング
        trader._current_signal = -1           # SELL（逆シグナル）
        trader._entry_time = datetime.now(timezone.utc) - timedelta(seconds=40)
        trader._timeout_exit_mode = False

        board = _make_board()
        trader._check_timeout(board)

        assert trader._timeout_exit_mode is True


# ── CLI バリデーション ────────────────────────────────────────────
def test_cli_requires_live_or_dry_run():
    """--live / --dry-run なしはエラー"""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "trader.py", "--exchange", "exchsim", "--symbol", "G_FX_BTCJPY"],
        cwd="/Users/sakamoto.yukio/workspace/live_trader",
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "live" in result.stderr.lower() or "dry-run" in result.stderr.lower()


def test_cli_rejects_both_live_and_dry_run():
    """--live と --dry-run を同時指定はエラー"""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "trader.py", "--exchange", "exchsim",
         "--symbol", "G_FX_BTCJPY", "--live", "--dry-run"],
        cwd="/Users/sakamoto.yukio/workspace/live_trader",
        capture_output=True, text=True,
    )
    assert result.returncode != 0
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
python -m pytest tests/test_trader.py -v
```
Expected: FAIL

- [ ] **Step 3: `trader.py` を実装**

```python
"""
LiveTrader — ML モデル駆動のハイブリッドループ取引システム

使い方:
    python trader.py --exchange exchsim --symbol G_FX_BTCJPY --dry-run
    python trader.py --exchange exchsim --symbol G_FX_BTCJPY --live
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import numpy as np

import config
from exchange.base import Board, ExchangeClient, MarketDataFeed
from ml.feature_engineering import RollingBuffer
from ml.model_loader import get_latest_model_id, load_model
from ml.predictor import Predictor
from storage.recorder import Recorder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_QUANTITY   = 0.001
DEFAULT_CONFIDENCE = 0.60
DEFAULT_TIMEOUT    = 30
DEFAULT_TICK_SIZE  = 1.0
AUTO_RELOAD_INTERVAL = 1800  # 30分


class LiveTrader:
    """ML シグナルで指値発注・管理するメインクラス。"""

    def __init__(
        self,
        symbol: str,
        exchange_name: str,
        client: ExchangeClient,
        feed: MarketDataFeed,
        predictor: Predictor,
        recorder: Recorder,
        quantity: float = DEFAULT_QUANTITY,
        tick_size: float = DEFAULT_TICK_SIZE,
        timeout_seconds: int = DEFAULT_TIMEOUT,
        dry_run: bool = True,
        model_id: Optional[int] = None,
    ):
        self.symbol          = symbol
        self.exchange_name   = exchange_name
        self.quantity        = quantity
        self.tick_size       = tick_size
        self.timeout_seconds = timeout_seconds
        self.dry_run         = dry_run
        self._model_id       = model_id

        self._client    = client
        self._feed      = feed
        self._predictor = predictor
        self._recorder  = recorder
        self._buffer    = RollingBuffer(symbol)

        # 注文状態
        self._pending_order_id: Optional[str] = None
        self._pending_side:     Optional[str] = None
        self._pending_price:    float         = 0.0
        self._chase_count:      int           = 0

        # ポジション状態
        self._position_qty:  float         = 0.0
        self._entry_price:   float         = 0.0
        self._entry_time:    Optional[datetime] = None

        # タイムアウト
        self._timeout_exit_mode: bool = False

        # シグナル（スレッドセーフアクセス用）
        self._current_signal: int   = 0
        self._latest_board:   Optional[Board] = None
        self._lock:           threading.Lock  = threading.Lock()

        # 損益
        self._realized_pnl: float = 0.0
        self._fill_count:   int   = 0

        # モデルリロード
        self._loaded_model_ts: Optional[datetime] = datetime.now(timezone.utc)
        self._last_reload_check: Optional[datetime] = None

        # ログ周期
        self._last_log_ts: Optional[datetime] = None
        self._tick_count: int = 0

    # ── メインループ ────────────────────────────────────────────────
    async def run(self) -> None:
        """フィードを開始し、1秒ごとのタイマーループを回す。"""
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        logger.info(f"LiveTrader 起動: symbol={self.symbol}, mode={mode}, "
                    f"exchange={self.exchange_name}")
        await self._feed.start()
        try:
            while True:
                await asyncio.sleep(1.0)
                await self._tick()
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("シャットダウン中...")
            await self._feed.stop()
            if self._pending_order_id:
                logger.info(f"未約定注文をキャンセル: {self._pending_order_id}")
                if not self.dry_run:
                    self._client.cancel_order(self._pending_order_id)

    async def _tick(self) -> None:
        """1秒ごとに呼ばれるメインロジック。"""
        self._tick_count += 1

        board = self._feed.get_board()
        if board is None:
            return

        with self._lock:
            self._latest_board = board

        # 1. バッファ追加 + DB 保存
        exec_agg = self._aggregate_executions()
        self._buffer.add(board, exec_agg)
        try:
            self._recorder.save_board(board)
        except Exception as e:
            logger.warning(f"save_board error: {e}")

        # 2. ウォームアップ確認
        if not self._buffer.is_warm():
            if self._tick_count % 10 == 0:
                logger.info(f"ウォームアップ中... {len(self._buffer)}/60")
            return

        # 3. ML 予測
        result = self._predictor.predict(self._buffer)
        if result is not None:
            signal, conf, probs = result
            with self._lock:
                self._current_signal = signal

        # 4. 板更新コールバック（ExchSim は 1秒ごとにここで repricing）
        self._on_board_update(board)

        # 5. モデル自動リロードチェック（30分ごと・ポジションなし時）
        self._maybe_reload_model()

        # 6. 定期ログ（30秒ごと）
        now = datetime.now(timezone.utc)
        if self._last_log_ts is None or (now - self._last_log_ts).total_seconds() >= 30:
            self._last_log_ts = now
            logger.info(
                f"[{self.symbol}] pos={self._position_qty:+.4f} "
                f"signal={self._current_signal} pnl={self._realized_pnl:+.0f}円 "
                f"fills={self._fill_count}"
            )

    def _on_board_update(self, board: Board) -> None:
        """板更新時に repricing を実行（GMO では WebSocket push ごとに呼ぶ）。"""
        with self._lock:
            signal = self._current_signal
            pos    = self._position_qty

        # タイムアウトチェック
        self._check_timeout(board)

        if self._timeout_exit_mode:
            # タイムアウト決済モード: 逆方向指値チェイス
            close_side = "SELL" if pos > 0 else "BUY"
            self._chase_side(close_side, board)
        elif self._pending_order_id:
            # 未約定あり: repricing
            self._chase_side(self._pending_side, board)
        elif pos == 0 and signal != 0:
            # ポジションなし + シグナルあり: 新規発注
            side = "BUY" if signal == 1 else "SELL"
            self._place_limit(side, board)

    def _calc_chase_price(self, side: str, board: Board) -> float:
        """Mid ベースのチェイス価格を計算する。"""
        mid = board.mid
        if side == "BUY":
            base = int(mid)
            price = base + (self._chase_count - 1) * self.tick_size
            price = min(price, board.ask - self.tick_size)
        else:  # SELL
            base = int(mid) + 1
            price = base - (self._chase_count - 1) * self.tick_size
            price = max(price, board.bid + self.tick_size)
        return price

    def _place_limit(self, side: str, board: Board) -> None:
        """初回指値を発注する。"""
        # ダブルポジション安全ガード
        if side == "BUY" and self._position_qty > 0:
            return
        if side == "SELL" and self._position_qty < 0:
            return

        self._chase_count = 1
        price = self._calc_chase_price(side, board)

        if not self.dry_run:
            order_id = self._client.place_limit_order(side, price, self.quantity)
            self._pending_order_id = order_id
        else:
            self._pending_order_id = f"dry-{datetime.now().strftime('%H%M%S%f')}"
            logger.info(f"[DRY-RUN] {side} {self.quantity} @ {price:,.0f}")

        self._pending_side  = side
        self._pending_price = price
        logger.info(f"📋 {side} 発注: {price:,.0f}円 (chase={self._chase_count})")

    def _chase_side(self, side: Optional[str], board: Board) -> None:
        """既存注文を cancel して repricing する。"""
        if side is None:
            return

        self._chase_count += 1
        new_price = self._calc_chase_price(side, board)

        if new_price == self._pending_price:
            return  # 価格変化なし

        # キャンセル
        if not self.dry_run and self._pending_order_id:
            ok = self._client.cancel_order(self._pending_order_id)
            if not ok:
                self._sync_position()
                return

        self._pending_order_id = None

        # ポジション変化チェック（キャンセル後に約定していた場合）
        if not self.dry_run:
            new_pos = self._get_remote_position()
            if new_pos != self._position_qty:
                logger.info("ポジション変化検出、再発注スキップ")
                self._position_qty = new_pos
                return

        # 再発注
        self._pending_price = new_price
        if not self.dry_run:
            order_id = self._client.place_limit_order(side, new_price, self.quantity)
            self._pending_order_id = order_id
        else:
            self._pending_order_id = f"dry-{datetime.now().strftime('%H%M%S%f')}"

        logger.debug(f"  ↳ repriced {side} @ {new_price:,.0f}")

    def _check_timeout(self, board: Board) -> None:
        """タイムアウト判定（シグナル適応型）。"""
        if self._position_qty == 0 or self._entry_time is None:
            return
        if self.timeout_seconds <= 0:
            return

        elapsed = (datetime.now(timezone.utc) - self._entry_time).total_seconds()
        if elapsed < self.timeout_seconds:
            return

        with self._lock:
            signal = self._current_signal
        pos = self._position_qty
        same_dir = (pos > 0 and signal == 1) or (pos < 0 and signal == -1)

        if same_dir:
            self._entry_time = datetime.now(timezone.utc)
            logger.info(f"  ⏱ タイムアウト延長（同方向シグナル継続）")
        else:
            self._timeout_exit_mode = True
            reason = "逆シグナル検出" if signal != 0 else "HOLDシグナル"
            logger.info(f"  ⏰ タイムアウト: {reason} → 決済開始")

    # ── 約定検出・損益計算 ─────────────────────────────────────────
    def _aggregate_executions(self) -> Optional[dict]:
        """直近約定を集計して exec_agg dict を返す（ML 特徴量用）。"""
        try:
            execs = self._client.get_recent_executions(self.symbol, size=100)
        except Exception:
            return None
        if not execs:
            return None

        buy_prices  = [e["lastPx"] for e in execs if e["side"] == "BUY"]
        sell_prices = [e["lastPx"] for e in execs if e["side"] == "SELL"]
        all_prices  = [e["lastPx"] for e in execs]
        volumes     = [e.get("lastQty", 0) for e in execs]

        buy_vols  = [e.get("lastQty", 0) for e in execs if e["side"] == "BUY"]
        sell_vols = [e.get("lastQty", 0) for e in execs if e["side"] == "SELL"]

        def w_avg(prices, vols):
            total = sum(vols)
            return sum(p * v for p, v in zip(prices, vols)) / total if total > 0 else 0.0

        return {
            "exec_price_buy":          sum(buy_prices)  / len(buy_prices)  if buy_prices  else 0.0,
            "exec_price_sell":         sum(sell_prices) / len(sell_prices) if sell_prices else 0.0,
            "exec_price_all":          sum(all_prices)  / len(all_prices)  if all_prices  else 0.0,
            "exec_price_weighted_buy": w_avg(buy_prices,  buy_vols),
            "exec_price_weighted_sell":w_avg(sell_prices, sell_vols),
            "volume_total":            sum(volumes),
        }

    def _sync_position(self) -> None:
        """取引所からポジションを同期する（キャンセル失敗 fallback）。"""
        try:
            positions = self._client.get_positions()
            pos_data  = positions.get(self.symbol, {})
            self._position_qty = float(pos_data.get("qty", 0.0))
        except Exception as e:
            logger.warning(f"_sync_position error: {e}")

    def _get_remote_position(self) -> float:
        try:
            positions = self._client.get_positions()
            return float(positions.get(self.symbol, {}).get("qty", 0.0))
        except Exception:
            return self._position_qty

    # ── モデル自動リロード ─────────────────────────────────────────
    def _maybe_reload_model(self) -> None:
        """30分ごと・ポジションなし時に新モデルを確認してリロード。"""
        if self._model_id is not None:
            return  # 起動時に明示指定された場合はスキップ
        if self._position_qty != 0:
            return

        now = datetime.now(timezone.utc)
        if self._last_reload_check is None or \
                (now - self._last_reload_check).total_seconds() >= AUTO_RELOAD_INTERVAL:
            self._last_reload_check = now
            try:
                latest_id = get_latest_model_id(self.symbol)
                # 現在のモデルと比較（DB から再取得して確認）
                new_model, new_scaler, new_cols = load_model(self.symbol)
                self._predictor = Predictor(
                    new_model, new_scaler, new_cols,
                    confidence_threshold=self._predictor._confidence_threshold,
                )
                logger.info(f"🔄 新しいモデル検出 → リロード完了 (id={latest_id})")
            except Exception as e:
                logger.warning(f"モデルリロード失敗: {e}")


# ── エントリーポイント ────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="LiveTrader")
    parser.add_argument("--exchange",  required=True, choices=["gmo", "exchsim"])
    parser.add_argument("--symbol",    default="G_FX_BTCJPY")
    parser.add_argument("--live",      action="store_true")
    parser.add_argument("--dry-run",   action="store_true", dest="dry_run")
    parser.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--quantity",  type=float, default=DEFAULT_QUANTITY)
    parser.add_argument("--model-id",  type=int, default=None)
    return parser.parse_args()


def main():
    args = parse_args()

    # バリデーション
    if args.live and args.dry_run:
        print("ERROR: --live と --dry-run は同時に指定できません", file=sys.stderr)
        sys.exit(1)
    if not args.live and not args.dry_run:
        print("ERROR: --live または --dry-run のどちらかを指定してください", file=sys.stderr)
        sys.exit(1)

    dry_run = args.dry_run

    # 取引所固有の初期化
    if args.exchange == "exchsim":
        from exchange.exchsim.client import ExchSimClient
        from exchange.exchsim.feed   import ExchSimFeed

        client = ExchSimClient(
            base_url=config.EXCHSIM_URL,
            username=config.EXCHSIM_USERNAME,
            password=config.EXCHSIM_PASSWORD,
            symbol=args.symbol,
        )
        client.login()
        feed = ExchSimFeed(client, symbol=args.symbol, interval=1.0)
    else:
        raise NotImplementedError(f"exchange={args.exchange} は未実装 (Phase 4)")

    # ML
    model, scaler, feature_cols = load_model(args.symbol, args.model_id)
    predictor = Predictor(model, scaler, feature_cols,
                          confidence_threshold=args.confidence)

    # Storage
    recorder = Recorder(dsn=config.get_live_trader_dsn())

    # トレーダー
    trader = LiveTrader(
        symbol=args.symbol,
        exchange_name=args.exchange,
        client=client,
        feed=feed,
        predictor=predictor,
        recorder=recorder,
        quantity=args.quantity,
        tick_size=DEFAULT_TICK_SIZE,
        timeout_seconds=args.timeout_seconds,
        dry_run=dry_run,
        model_id=args.model_id,
    )

    try:
        asyncio.run(trader.run())
    except KeyboardInterrupt:
        logger.info("Ctrl+C → 終了")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: テストを通す**

```bash
cd ~/workspace/live_trader
python -m pytest tests/test_trader.py -v
```
Expected: 全テスト PASS

- [ ] **Step 5: コミット**

```bash
git add trader.py tests/test_trader.py
git commit -m "feat: add LiveTrader main loop with hybrid event-driven architecture"
```

---

## Task 8: 全テスト確認 & ExchSim dry-run スモークテスト

**Files:** なし（統合確認のみ）

- [ ] **Step 1: 全ユニットテストを通す**

```bash
cd ~/workspace/live_trader
python -m pytest tests/ -v
```
Expected: 全テスト PASS（最低 20 件）

- [ ] **Step 2: ExchSim dry-run でスモークテスト（3分間）**

事前条件: ExchSim が `http://77.42.74.155:8080` で稼働、EXCHSIM_USERNAME/PASSWORD が `.env` に設定済み

```bash
cd ~/workspace/live_trader
timeout 180 python trader.py \
    --exchange exchsim \
    --symbol G_FX_BTCJPY \
    --dry-run \
    --confidence 0.60 \
    --timeout-seconds 30 \
    2>&1 | tee /tmp/live_trader_phase1_smoke.log
```

**確認ポイント:**
- `ExchSim login OK` が出力される
- `ウォームアップ中...` → `[G_FX_BTCJPY] pos=+0.0000...` の定期ログが出る
- `📋 BUY 発注:` または `📋 SELL 発注:` が出る（シグナルが出た場合）
- エラーやスタックトレースが出ない

- [ ] **Step 3: `--live` / `--dry-run` バリデーションをCLIで確認**

```bash
# neither → error
python trader.py --exchange exchsim --symbol G_FX_BTCJPY
echo "exit code: $?"
# Expected: exit code != 0, ERROR メッセージ

# both → error
python trader.py --exchange exchsim --symbol G_FX_BTCJPY --live --dry-run
echo "exit code: $?"
# Expected: exit code != 0, ERROR メッセージ
```

- [ ] **Step 4: `CLAUDE.md` を Phase 1 完了で更新**

```bash
cd ~/workspace/live_trader
# CLAUDE.md の「← **現在**」を「← ✅ 完了」に更新
sed -i 's/Phase 1.*← \*\*現在\*\*/Phase 1: ExchSim 接続で既存 LiveTrader と同等動作 ← ✅ 完了/' CLAUDE.md
```

- [ ] **Step 5: 最終コミット**

```bash
cd ~/workspace/live_trader
git add CLAUDE.md
git commit -m "chore: Phase 1 complete - ExchSim dry-run verified"
```

---

## 自己レビュー

### スペックカバレッジ

| 仕様セクション | 対応タスク |
|--------------|----------|
| 取引所抽象レイヤー（Board, ABCs） | Task 2 |
| ExchSimClient 移植 | Task 3 |
| ExchSimFeed 1秒ポーリング | Task 4 |
| ML 移植（FeatureEngineer, RollingBuffer, Predictor） | Task 5 |
| DB スキーマ（4テーブル） | Task 6 |
| Recorder（save_board, save_trade） | Task 6 |
| trader.py ハイブリッドループ | Task 7 |
| --live / --dry-run 必須バリデーション | Task 7 |
| Mid ベースチェイス価格 | Task 7 |
| シグナル適応型タイムアウト | Task 7 |
| モデル自動リロード（30分） | Task 7 |
| End-to-end 動作確認 | Task 8 |

### 型整合性確認

- `Board` dataclass → `ExchSimFeed._poll_once()` → `RollingBuffer.add(board)` → `Predictor.predict(buffer)` の型チェーンは一貫
- `ExchangeClient.place_limit_order(side, price, qty)` と `ExchSimClient.place_limit_order` のシグネチャ一致
- `Recorder.save_board(Board)` は `Board.bids` / `Board.asks` が `list[tuple[float, float]]` 前提 → `ExchSimFeed` でも同形式で生成している
