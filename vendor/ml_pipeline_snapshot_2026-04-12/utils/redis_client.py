# ml_pipeline/utils/redis_client.py
"""
Redisクライアントラッパー

- 自動再接続
- JSON自動シリアライズ
- エラーハンドリング
- キャッシュヘルパー
"""

import redis
import json
import os
import logging
from typing import Optional, Any, Callable

logger = logging.getLogger(__name__)


class RedisClient:
    """
    Redisクライアントラッパー

    - 自動再接続
    - JSON自動シリアライズ
    - エラーハンドリング
    - キャッシュヘルパー
    """

    def __init__(
        self,
        host: str = None,
        port: int = None,
        db: int = None,
        password: str = None,
        max_connections: int = 50,
        socket_timeout: int = 5,
        socket_connect_timeout: int = 5
    ):
        self.host = host or os.getenv("REDIS_HOST", "localhost")
        self.port = int(port or os.getenv("REDIS_PORT", 6379))
        self.db = int(db or os.getenv("REDIS_DB", 0))
        self.password = password or os.getenv("REDIS_PASSWORD", None)

        # 接続プール作成
        self.pool = redis.ConnectionPool(
            host=self.host,
            port=self.port,
            db=self.db,
            password=self.password if self.password else None,
            max_connections=max_connections,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            decode_responses=True  # 文字列として取得
        )

        self.client = redis.Redis(connection_pool=self.pool)

        # 接続確認
        self._test_connection()

    def _test_connection(self):
        """接続テスト"""
        try:
            self.client.ping()
            logger.info(f"Redis connected: {self.host}:{self.port} (db={self.db})")
        except redis.ConnectionError as e:
            logger.error(f"Redis connection failed: {e}")
            raise

    # ===================================
    # 基本操作
    # ===================================

    def get(self, key: str) -> Optional[str]:
        """値取得"""
        try:
            return self.client.get(key)
        except redis.RedisError as e:
            logger.error(f"Redis GET error: {key}, {e}")
            return None

    def set(
        self,
        key: str,
        value: str,
        ttl: int = None
    ) -> bool:
        """
        値設定

        Args:
            key: キー
            value: 値
            ttl: TTL（秒）、Noneの場合は永続
        """
        try:
            if ttl:
                return self.client.setex(key, ttl, value)
            else:
                return self.client.set(key, value)
        except redis.RedisError as e:
            logger.error(f"Redis SET error: {key}, {e}")
            return False

    def delete(self, key: str) -> bool:
        """キー削除"""
        try:
            return bool(self.client.delete(key))
        except redis.RedisError as e:
            logger.error(f"Redis DELETE error: {key}, {e}")
            return False

    def exists(self, key: str) -> bool:
        """キー存在確認"""
        try:
            return bool(self.client.exists(key))
        except redis.RedisError as e:
            logger.error(f"Redis EXISTS error: {key}, {e}")
            return False

    def ttl(self, key: str) -> int:
        """
        TTL取得

        Returns:
            TTL（秒）、-1: 永続、-2: キー不存在
        """
        try:
            return self.client.ttl(key)
        except redis.RedisError as e:
            logger.error(f"Redis TTL error: {key}, {e}")
            return -2

    # ===================================
    # JSON操作
    # ===================================

    def get_json(self, key: str) -> Optional[Any]:
        """JSON取得・デシリアライズ"""
        value = self.get(key)
        if value is None:
            return None

        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {key}, {e}")
            return None

    def set_json(
        self,
        key: str,
        value: Any,
        ttl: int = None
    ) -> bool:
        """JSON設定・シリアライズ"""
        try:
            json_str = json.dumps(value, ensure_ascii=False, default=str)
            return self.set(key, json_str, ttl)
        except (TypeError, ValueError) as e:
            logger.error(f"JSON encode error: {key}, {e}")
            return False

    # ===================================
    # キャッシュヘルパー
    # ===================================

    def cache_get_or_set(
        self,
        key: str,
        fetch_func: Callable,
        ttl: int = 60
    ) -> Optional[Any]:
        """
        キャッシュ取得、ミス時は関数実行して保存

        Args:
            key: キャッシュキー
            fetch_func: キャッシュミス時に実行する関数
            ttl: TTL（秒）

        Returns:
            キャッシュ値または関数実行結果
        """
        # キャッシュヒット
        cached = self.get_json(key)
        if cached is not None:
            logger.debug(f"Cache HIT: {key}")
            return cached

        # キャッシュミス → 関数実行
        logger.debug(f"Cache MISS: {key}")
        value = fetch_func()

        # 保存
        if value is not None:
            self.set_json(key, value, ttl)

        return value

    # ===================================
    # Pub/Sub操作
    # ===================================

    def publish(self, channel: str, message: Any) -> int:
        """
        メッセージをチャンネルにパブリッシュ

        Args:
            channel: チャンネル名
            message: メッセージ（dictの場合はJSON変換）

        Returns:
            受信したサブスクライバー数
        """
        try:
            if isinstance(message, (dict, list)):
                message = json.dumps(message, ensure_ascii=False, default=str)
            return self.client.publish(channel, message)
        except redis.RedisError as e:
            logger.error(f"Redis PUBLISH error: {channel}, {e}")
            return 0

    def subscribe(self, *channels):
        """
        チャンネルをサブスクライブ

        Args:
            channels: サブスクライブするチャンネル名

        Returns:
            PubSubオブジェクト
        """
        pubsub = self.client.pubsub()
        pubsub.subscribe(*channels)
        return pubsub

    # ===================================
    # 統計
    # ===================================

    def get_stats(self) -> dict:
        """Redis統計取得"""
        try:
            info = self.client.info()
            return {
                "used_memory": info.get("used_memory_human"),
                "connected_clients": info.get("connected_clients"),
                "total_commands_processed": info.get("total_commands_processed"),
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
                "hit_rate": self._calculate_hit_rate(info)
            }
        except redis.RedisError as e:
            logger.error(f"Redis INFO error: {e}")
            return {}

    def _calculate_hit_rate(self, info: dict) -> float:
        """キャッシュヒット率計算"""
        hits = info.get("keyspace_hits", 0)
        misses = info.get("keyspace_misses", 0)
        total = hits + misses

        if total == 0:
            return 0.0

        return round(hits / total * 100, 2)

    # ===================================
    # クリーンアップ
    # ===================================

    def close(self):
        """接続クローズ"""
        if self.client:
            self.client.close()
        if self.pool:
            self.pool.disconnect()
        logger.info("Redis connection closed")

    def is_connected(self) -> bool:
        """接続状態確認"""
        try:
            self.client.ping()
            return True
        except redis.RedisError:
            return False


# シングルトンインスタンス
_redis_client: Optional[RedisClient] = None


def get_redis_client() -> RedisClient:
    """Redisクライアント取得（シングルトン）"""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
    return _redis_client


def reset_redis_client():
    """Redisクライアントをリセット（テスト用）"""
    global _redis_client
    if _redis_client is not None:
        _redis_client.close()
        _redis_client = None
