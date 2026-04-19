# ml_pipeline/utils/signal_publisher.py
"""
取引シグナル Pub/Sub パブリッシャー

ML パイプラインから Trading Engine へシグナルを Redis Pub/Sub で配信
"""

import json
import os
import logging
from datetime import datetime
from typing import Optional, Any
from dataclasses import dataclass, asdict, field

from .redis_client import get_redis_client, RedisClient

logger = logging.getLogger(__name__)


@dataclass
class TradingSignal:
    """取引シグナルデータ"""
    symbol: str
    strategy_name: str
    signal_type: str  # BUY, SELL, HOLD
    confidence: float
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # 追加情報（オプション）
    predicted_price: Optional[float] = None
    current_price: Optional[float] = None
    price_change_pct: Optional[float] = None
    momentum_intensity: Optional[int] = None

    # メタ情報
    account_id: Optional[int] = None
    source: str = "ml_pipeline"

    def to_dict(self) -> dict:
        """辞書に変換"""
        return {k: v for k, v in asdict(self).items() if v is not None}

    def to_json(self) -> str:
        """JSON文字列に変換"""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


class SignalPublisher:
    """
    取引シグナル パブリッシャー

    Redis Pub/Sub を使用してシグナルを配信
    """

    DEFAULT_CHANNEL = "trading_signals"

    def __init__(
        self,
        redis_client: RedisClient = None,
        channel: str = None
    ):
        self.redis = redis_client or get_redis_client()
        self.channel = channel or os.getenv("REDIS_SIGNAL_CHANNEL", self.DEFAULT_CHANNEL)
        self._publish_count = 0
        self._error_count = 0

    def publish(self, signal: TradingSignal) -> bool:
        """
        シグナルをパブリッシュ

        Args:
            signal: 取引シグナル

        Returns:
            成功した場合 True
        """
        try:
            message = signal.to_json()
            subscribers = self.redis.publish(self.channel, message)

            self._publish_count += 1

            logger.info(
                f"Signal published: {signal.symbol} {signal.signal_type} "
                f"(confidence={signal.confidence:.2f}, subscribers={subscribers})"
            )

            return True

        except Exception as e:
            self._error_count += 1
            logger.error(f"Failed to publish signal: {e}")
            return False

    def publish_dict(self, signal_dict: dict) -> bool:
        """
        辞書形式でシグナルをパブリッシュ

        Args:
            signal_dict: シグナル辞書

        Returns:
            成功した場合 True
        """
        try:
            # 必須フィールド確認
            required_fields = ["symbol", "strategy_name", "signal_type", "confidence"]
            for field in required_fields:
                if field not in signal_dict:
                    raise ValueError(f"Missing required field: {field}")

            # タイムスタンプ追加
            if "timestamp" not in signal_dict:
                signal_dict["timestamp"] = datetime.utcnow().isoformat()

            # ソース追加
            if "source" not in signal_dict:
                signal_dict["source"] = "ml_pipeline"

            message = json.dumps(signal_dict, ensure_ascii=False, default=str)
            subscribers = self.redis.publish(self.channel, message)

            self._publish_count += 1

            logger.info(
                f"Signal published: {signal_dict['symbol']} {signal_dict['signal_type']} "
                f"(confidence={signal_dict['confidence']:.2f}, subscribers={subscribers})"
            )

            return True

        except Exception as e:
            self._error_count += 1
            logger.error(f"Failed to publish signal dict: {e}")
            return False

    def publish_batch(self, signals: list[TradingSignal]) -> int:
        """
        複数シグナルを一括パブリッシュ

        Args:
            signals: シグナルリスト

        Returns:
            成功した数
        """
        success_count = 0
        for signal in signals:
            if self.publish(signal):
                success_count += 1

        logger.info(f"Batch publish completed: {success_count}/{len(signals)} signals")
        return success_count

    def get_stats(self) -> dict:
        """統計情報取得"""
        return {
            "channel": self.channel,
            "publish_count": self._publish_count,
            "error_count": self._error_count,
            "success_rate": (
                self._publish_count / (self._publish_count + self._error_count) * 100
                if (self._publish_count + self._error_count) > 0
                else 0.0
            )
        }

    def reset_stats(self):
        """統計情報リセット"""
        self._publish_count = 0
        self._error_count = 0


# シングルトンインスタンス
_signal_publisher: Optional[SignalPublisher] = None


def get_signal_publisher() -> SignalPublisher:
    """シグナルパブリッシャー取得（シングルトン）"""
    global _signal_publisher
    if _signal_publisher is None:
        _signal_publisher = SignalPublisher()
    return _signal_publisher
