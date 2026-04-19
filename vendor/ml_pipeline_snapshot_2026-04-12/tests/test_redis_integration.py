# ml_pipeline/tests/test_redis_integration.py
"""
Redis統合テスト

Redis Pub/Sub とキャッシュ機能のテスト
"""

import pytest
import time
import json
from datetime import datetime
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestRedisClient:
    """RedisClient のテスト"""

    def test_redis_client_import(self):
        """インポートテスト"""
        from utils.redis_client import RedisClient, get_redis_client
        assert RedisClient is not None
        assert get_redis_client is not None

    @patch('utils.redis_client.redis.ConnectionPool')
    @patch('utils.redis_client.redis.Redis')
    def test_redis_client_init(self, mock_redis, mock_pool):
        """初期化テスト（Mockを使用）"""
        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True
        mock_redis.return_value = mock_redis_instance

        from utils.redis_client import RedisClient
        client = RedisClient(host='localhost', port=6379)

        assert client.host == 'localhost'
        assert client.port == 6379
        mock_redis_instance.ping.assert_called_once()

    @patch('utils.redis_client.redis.ConnectionPool')
    @patch('utils.redis_client.redis.Redis')
    def test_redis_get_set(self, mock_redis, mock_pool):
        """GET/SET テスト"""
        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.get.return_value = 'test_value'
        mock_redis_instance.setex.return_value = True
        mock_redis.return_value = mock_redis_instance

        from utils.redis_client import RedisClient
        client = RedisClient()

        # SET
        result = client.set('test_key', 'test_value', ttl=60)
        assert result is True

        # GET
        value = client.get('test_key')
        assert value == 'test_value'

    @patch('utils.redis_client.redis.ConnectionPool')
    @patch('utils.redis_client.redis.Redis')
    def test_redis_json_operations(self, mock_redis, mock_pool):
        """JSON操作テスト"""
        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.get.return_value = '{"key": "value", "number": 42}'
        mock_redis_instance.setex.return_value = True
        mock_redis.return_value = mock_redis_instance

        from utils.redis_client import RedisClient
        client = RedisClient()

        # SET JSON
        test_data = {'key': 'value', 'number': 42}
        result = client.set_json('json_key', test_data, ttl=60)
        assert result is True

        # GET JSON
        value = client.get_json('json_key')
        assert value == test_data


class TestSignalPublisher:
    """SignalPublisher のテスト"""

    def test_signal_publisher_import(self):
        """インポートテスト"""
        from utils.signal_publisher import SignalPublisher, TradingSignal, get_signal_publisher
        assert SignalPublisher is not None
        assert TradingSignal is not None
        assert get_signal_publisher is not None

    def test_trading_signal_creation(self):
        """TradingSignal 作成テスト"""
        from utils.signal_publisher import TradingSignal

        signal = TradingSignal(
            symbol='G_FX_BTCJPY',
            strategy_name='momentum',
            signal_type='BUY',
            confidence=0.85,
            predicted_price=14500000.0,
            current_price=14450000.0
        )

        assert signal.symbol == 'G_FX_BTCJPY'
        assert signal.strategy_name == 'momentum'
        assert signal.signal_type == 'BUY'
        assert signal.confidence == 0.85
        assert signal.source == 'ml_pipeline'

    def test_trading_signal_to_dict(self):
        """TradingSignal 辞書変換テスト"""
        from utils.signal_publisher import TradingSignal

        signal = TradingSignal(
            symbol='G_FX_BTCJPY',
            strategy_name='momentum',
            signal_type='SELL',
            confidence=0.75
        )

        signal_dict = signal.to_dict()

        assert signal_dict['symbol'] == 'G_FX_BTCJPY'
        assert signal_dict['strategy_name'] == 'momentum'
        assert signal_dict['signal_type'] == 'SELL'
        assert signal_dict['confidence'] == 0.75
        assert 'timestamp' in signal_dict

    def test_trading_signal_to_json(self):
        """TradingSignal JSON変換テスト"""
        from utils.signal_publisher import TradingSignal

        signal = TradingSignal(
            symbol='G_FX_BTCJPY',
            strategy_name='test_strategy',
            signal_type='HOLD',
            confidence=0.5
        )

        json_str = signal.to_json()

        # JSONとしてパース可能か確認
        parsed = json.loads(json_str)
        assert parsed['symbol'] == 'G_FX_BTCJPY'
        assert parsed['signal_type'] == 'HOLD'

    @patch('utils.signal_publisher.get_redis_client')
    def test_signal_publisher_publish(self, mock_get_client):
        """シグナルパブリッシュテスト"""
        mock_redis = MagicMock()
        mock_redis.publish.return_value = 1  # 1 subscriber
        mock_get_client.return_value = mock_redis

        from utils.signal_publisher import SignalPublisher, TradingSignal

        publisher = SignalPublisher(redis_client=mock_redis)

        signal = TradingSignal(
            symbol='G_FX_BTCJPY',
            strategy_name='momentum',
            signal_type='BUY',
            confidence=0.9
        )

        result = publisher.publish(signal)

        assert result is True
        mock_redis.publish.assert_called_once()

    @patch('utils.signal_publisher.get_redis_client')
    def test_signal_publisher_stats(self, mock_get_client):
        """統計情報テスト"""
        mock_redis = MagicMock()
        mock_redis.publish.return_value = 1
        mock_get_client.return_value = mock_redis

        from utils.signal_publisher import SignalPublisher, TradingSignal

        publisher = SignalPublisher(redis_client=mock_redis)

        # 複数シグナルをパブリッシュ
        for i in range(5):
            signal = TradingSignal(
                symbol='G_FX_BTCJPY',
                strategy_name='test',
                signal_type='BUY',
                confidence=0.8
            )
            publisher.publish(signal)

        stats = publisher.get_stats()

        assert stats['publish_count'] == 5
        assert stats['error_count'] == 0
        assert stats['success_rate'] == 100.0


class TestLLMCache:
    """LLMCache のテスト"""

    def test_llm_cache_import(self):
        """インポートテスト"""
        from utils.llm_cache import LLMCache, PositionContext, MarketContext, LLMDecision
        assert LLMCache is not None
        assert PositionContext is not None
        assert MarketContext is not None
        assert LLMDecision is not None

    def test_cache_key_generation(self):
        """キャッシュキー生成テスト"""
        from utils.llm_cache import LLMCache, PositionContext, MarketContext

        # Mock Redis client
        mock_redis = MagicMock()
        mock_redis.is_connected.return_value = True

        cache = LLMCache(redis_client=mock_redis)

        position = PositionContext(
            symbol='G_FX_BTCJPY',
            current_quantity=0.001,
            average_price=14500000.0,
            unrealized_pnl_pct=0.32
        )

        market = MarketContext(
            current_price=14550000.0,
            price_change_1m=0.15,
            price_change_5m=0.25,
            volatility=0.0045
        )

        key1 = cache.generate_cache_key(position, market)

        # 同じ丸め値で同じキーが生成されることを確認
        position2 = PositionContext(
            symbol='G_FX_BTCJPY',
            current_quantity=0.001,
            average_price=14500000.0,
            unrealized_pnl_pct=0.35  # 0.3に丸められる
        )

        market2 = MarketContext(
            current_price=14550000.0,
            price_change_1m=0.18,  # 0.2に丸められる
            price_change_5m=0.28,  # 0.3に丸められる
            volatility=0.0048  # 0.005に丸められる
        )

        key2 = cache.generate_cache_key(position2, market2)

        assert key1 == key2  # 丸め処理により同じキー


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
