# ml_pipeline/utils/llm_cache.py
"""
LLM判断キャッシュ

- 類似状況を同一視するハッシュキー生成
- TTL管理
- 緊急実行フラグ管理
"""

import hashlib
import json
import os
import logging
from typing import Optional, Any
from dataclasses import dataclass, asdict

from .redis_client import get_redis_client, RedisClient

logger = logging.getLogger(__name__)


@dataclass
class PositionContext:
    """ポジションコンテキスト"""
    symbol: str
    current_quantity: float
    average_price: float
    unrealized_pnl_pct: float


@dataclass
class MarketContext:
    """マーケットコンテキスト"""
    current_price: float
    price_change_1m: float
    price_change_5m: float
    volatility: float


@dataclass
class LLMDecision:
    """LLM判断結果"""
    action: str  # HOLD, TAKE_PROFIT, CUT_LOSS, ADD_POSITION
    reasoning: str
    confidence: float
    urgent_execution: bool = False
    risk_level: str = "MEDIUM"  # LOW, MEDIUM, HIGH
    timestamp: str = None


class LLMCache:
    """
    LLM判断キャッシュ

    - 類似状況を同一視するハッシュキー生成
    - TTL管理
    - 緊急実行フラグ管理
    """

    def __init__(self, redis_client: RedisClient = None):
        self.redis = redis_client or get_redis_client()
        self.llm_ttl = int(os.getenv("REDIS_LLM_TTL", 60))
        self.urgent_ttl = int(os.getenv("REDIS_URGENT_EXECUTION_TTL", 120))

    # ===================================
    # LLM判断キャッシュ
    # ===================================

    def generate_cache_key(
        self,
        position: PositionContext,
        market: MarketContext
    ) -> str:
        """
        キャッシュキー生成

        類似状況を同一視するため、丸め処理を行う:
        - PnL: 0.1%単位
        - 価格変動: 0.1%単位
        - ボラティリティ: 0.001単位
        """
        key_data = {
            "symbol": position.symbol,
            "pnl_pct": round(position.unrealized_pnl_pct, 1),
            "change_1m": round(market.price_change_1m, 1),
            "change_5m": round(market.price_change_5m, 1),
            "volatility": round(market.volatility, 3),
            "direction": "LONG" if position.current_quantity > 0 else "SHORT"
        }

        # JSON文字列化してハッシュ
        json_str = json.dumps(key_data, sort_keys=True)
        hash_val = hashlib.md5(json_str.encode()).hexdigest()[:16]

        return f"llm_decision:{hash_val}"

    def get_decision(
        self,
        position: PositionContext,
        market: MarketContext
    ) -> Optional[LLMDecision]:
        """キャッシュから判断取得"""
        key = self.generate_cache_key(position, market)
        cached = self.redis.get_json(key)

        if cached:
            logger.debug(f"LLM Cache HIT: {key}")
            return LLMDecision(**cached)

        logger.debug(f"LLM Cache MISS: {key}")
        return None

    def set_decision(
        self,
        position: PositionContext,
        market: MarketContext,
        decision: LLMDecision
    ) -> bool:
        """判断をキャッシュに保存"""
        key = self.generate_cache_key(position, market)
        decision_dict = asdict(decision) if hasattr(decision, '__dataclass_fields__') else decision.__dict__
        result = self.redis.set_json(key, decision_dict, ttl=self.llm_ttl)

        if result:
            logger.debug(f"LLM Cache SET: {key}, TTL={self.llm_ttl}s")
        return result

    # ===================================
    # 緊急実行フラグ
    # ===================================

    def set_urgent_execution(self, symbol: str, urgent: bool = True) -> bool:
        """緊急実行フラグ設定"""
        key = f"urgent_execution:{symbol}"
        result = self.redis.set(key, str(urgent).lower(), ttl=self.urgent_ttl)

        if result:
            logger.info(f"Urgent execution flag SET: {symbol} = {urgent}, TTL={self.urgent_ttl}s")
        return result

    def get_urgent_execution(self, symbol: str) -> bool:
        """緊急実行フラグ取得"""
        key = f"urgent_execution:{symbol}"
        value = self.redis.get(key)
        return value == "true" if value else False

    def clear_urgent_execution(self, symbol: str) -> bool:
        """緊急実行フラグクリア"""
        key = f"urgent_execution:{symbol}"
        result = self.redis.delete(key)

        if result:
            logger.debug(f"Urgent execution flag CLEARED: {symbol}")
        return result

    # ===================================
    # 統計
    # ===================================

    def get_cache_stats(self) -> dict:
        """キャッシュ統計"""
        return self.redis.get_stats()


# シングルトンインスタンス
_llm_cache: Optional[LLMCache] = None


def get_llm_cache() -> LLMCache:
    """LLMキャッシュ取得（シングルトン）"""
    global _llm_cache
    if _llm_cache is None:
        _llm_cache = LLMCache()
    return _llm_cache
