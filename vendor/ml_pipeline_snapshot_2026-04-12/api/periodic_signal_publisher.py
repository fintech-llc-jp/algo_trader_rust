"""
定期シグナル配信タスク

一定間隔で BackgroundDataLoader のデータを使ってシグナルを生成し、
Redis (trading_signals) に publish する。
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional, Any

from api.signal_generation import generate_signal_from_features
from utils.signal_publisher import TradingSignal, get_signal_publisher

logger = logging.getLogger(__name__)
# ターミナル・ログファイル両方に出すため、シグナル出力時は ml_api ロガーを使用
ml_api_logger = logging.getLogger("ml_api")


class PeriodicSignalPublisher:
    """定期的にシグナルを生成して Redis に publish するタスク"""

    def __init__(
        self,
        bg_loader: Any,
        price_strategy: Any,
        momentum_strategy: Any,
        *,
        symbol: Optional[str] = None,
        enabled: Optional[bool] = None,
        interval_seconds: Optional[float] = None,
        strategy_name: Optional[str] = None,
        publish_hold: Optional[bool] = None,
    ):
        self.bg_loader = bg_loader
        self.price_strategy = price_strategy
        self.momentum_strategy = momentum_strategy
        self.symbol = symbol or getattr(bg_loader, "symbol", "G_FX_BTCJPY")

        env_true = os.getenv("PERIODIC_SIGNAL_ENABLED", "true").strip().lower() == "true"
        self.enabled = enabled if enabled is not None else env_true

        self.interval_seconds = float(
            interval_seconds
            if interval_seconds is not None
            else os.getenv("PERIODIC_SIGNAL_INTERVAL_SECONDS", "1")
        )
        self.strategy_name = (
            strategy_name
            or os.getenv("PERIODIC_SIGNAL_STRATEGY_NAME", "price_prediction")
        )
        pub_hold_env = os.getenv("PERIODIC_SIGNAL_PUBLISH_HOLD", "true").strip().lower() == "true"
        self.publish_hold = publish_hold if publish_hold is not None else pub_hold_env

        self._task: Optional[asyncio.Task] = None
        self._stop = False

    async def start(self) -> None:
        if not self.enabled:
            logger.info("[PeriodicSignal] Disabled by config")
            return
        if self._task is not None:
            return
        self._stop = False
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "[PeriodicSignal] Started (interval=%.1fs, symbol=%s, strategy_name=%s)",
            self.interval_seconds,
            self.symbol,
            self.strategy_name,
        )

    async def stop(self) -> None:
        self._stop = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[PeriodicSignal] Stopped")

    async def _loop(self) -> None:
        while not self._stop:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("[PeriodicSignal] _tick error: %s", e)
            await asyncio.sleep(self.interval_seconds)

    async def _tick(self) -> None:
        if self.bg_loader is None or not getattr(self.bg_loader, "running", False):
            return

        try:
            df, features = await self.bg_loader.get_data()
        except Exception as e:
            logger.warning("[PeriodicSignal] get_data failed: %s", e)
            return

        if df is None or len(df) == 0 or features is None or len(features) == 0:
            logger.debug("[PeriodicSignal] No data for %s, skipping", self.symbol)
            return

        if "mid_price" in df.columns:
            current_price = float(df["mid_price"].iloc[-1])
        elif "exec_price_all" in df.columns:
            current_price = float(df["exec_price_all"].iloc[-1])
        else:
            logger.warning("[PeriodicSignal] No price column in df, skipping")
            return

        result = generate_signal_from_features(
            self.symbol,
            df,
            features,
            current_price,
            self.price_strategy,
            self.momentum_strategy,
            log=ml_api_logger,
        )

        if result is None:
            return

        signal_type = result["signal_type"]
        if signal_type == "HOLD" and not self.publish_hold:
            return

        from datetime import datetime

        signal = TradingSignal(
            symbol=result["symbol"],
            strategy_name=self.strategy_name,
            signal_type=signal_type,
            confidence=result["confidence"],
            timestamp=datetime.utcnow().isoformat(),
            predicted_price=result["predicted_price"],
            current_price=result["current_price"],
            price_change_pct=result["price_change_pct"],
            momentum_intensity=result.get("momentum_intensity"),
            source="ml_pipeline",
        )

        publisher = get_signal_publisher()
        if publisher.publish(signal):
            ml_api_logger.info(
                "[PeriodicSignal] %s %s predicted_price=%.2f confidence=%.2f",
                result["symbol"],
                signal_type,
                result["predicted_price"],
                result["confidence"],
            )
