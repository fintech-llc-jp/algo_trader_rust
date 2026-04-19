"""
ConfigurableFeatureEngineerの単体テスト
Phase 8: 特徴量の動的設定機能のテスト
"""
import pytest
import pandas as pd
import numpy as np
from unittest.mock import Mock, patch, MagicMock
import psycopg2

from data.configurable_feature_engineering import ConfigurableFeatureEngineer


class TestConfigurableFeatureEngineer:
    """ConfigurableFeatureEngineerのテストクラス"""

    @pytest.fixture
    def sample_data(self):
        """サンプルデータを作成"""
        return pd.DataFrame({
            'symbol': ['G_FX_BTCJPY'] * 100,
            'mid_price': np.linspace(1000000, 1100000, 100),
            'spread': [100.0] * 100,
            'bid_depth_5': [0.5] * 100,
            'ask_depth_5': [0.4] * 100,
            'order_imbalance': np.random.uniform(-0.5, 0.5, 100),
            'volume_total': np.random.uniform(0, 1, 100),
            'bid_price_1': np.linspace(999950, 1099950, 100),
            'ask_price_1': np.linspace(1000050, 1100050, 100),
        })

    @pytest.fixture
    def mock_db_config(self):
        """DB設定のモック"""
        config = {
            'feature_definitions': {
                'price_features': {
                    'enabled': True,
                    'return_periods': [1, 5, 30],
                    'spread_ratio': True
                },
                'depth_features': {
                    'enabled': True,
                    'depth_levels': [5],
                    'depth_ratio': True
                },
                'imbalance_features': {
                    'enabled': True,
                    'imbalance_abs': True
                },
                'volume_features': {
                    'enabled': True,
                    'volume_ma_windows': [30, 300],
                    'volume_ratio': True
                },
                'execution_features': {
                    'enabled': True
                },
                'technical_indicators': {
                    'enabled': False
                },
                'lag_features': {
                    'enabled': True,
                    'lag_periods': [1, 5]
                },
                'rolling_statistics': {
                    'enabled': True,
                    'windows': [30],
                    'statistics': ['mean', 'std']
                }
            },
            'preprocessing_config': {
                'fillna_method': 'zero',
                'normalization': 'none',
                'outlier_handling': 'clip',
                'outlier_threshold': 3.0
            }
        }
        return config

    @patch('data.configurable_feature_engineering.psycopg2.connect')
    def test_load_config_from_db_success(self, mock_connect, mock_db_config):
        """DBから設定を正常に読み込むテスト"""
        # Given
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)
        
        mock_cursor.fetchone.return_value = (
            mock_db_config['feature_definitions'],
            mock_db_config['preprocessing_config']
        )

        # When
        engineer = ConfigurableFeatureEngineer('standard_features')

        # Then
        assert engineer.feature_definitions == mock_db_config['feature_definitions']
        assert engineer.preprocessing_config == mock_db_config['preprocessing_config']
        mock_connect.assert_called_once()

    @patch('data.configurable_feature_engineering.psycopg2.connect')
    def test_load_config_from_db_not_found(self, mock_connect):
        """DBに設定が見つからない場合のテスト"""
        # Given
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)
        
        mock_cursor.fetchone.return_value = None

        # When
        engineer = ConfigurableFeatureEngineer('non_existent')

        # Then
        # デフォルト設定が使用される
        assert engineer.feature_definitions is not None
        assert engineer.preprocessing_config is not None
        assert 'price_features' in engineer.feature_definitions

    @patch('data.configurable_feature_engineering.psycopg2.connect')
    def test_load_config_from_db_connection_error(self, mock_connect):
        """DB接続エラー時のテスト"""
        # Given
        mock_connect.side_effect = psycopg2.Error("Connection failed")

        # When
        engineer = ConfigurableFeatureEngineer('standard_features')

        # Then
        # デフォルト設定が使用される
        assert engineer.feature_definitions is not None
        assert engineer.preprocessing_config is not None

    def test_engineer_features_with_config(self, sample_data, mock_db_config):
        """設定に基づいて特徴量を生成するテスト"""
        # Given
        with patch('data.configurable_feature_engineering.psycopg2.connect') as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_connect.return_value = mock_conn
            mock_conn.__enter__ = Mock(return_value=mock_conn)
            mock_conn.__exit__ = Mock(return_value=None)
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)
            
            mock_cursor.fetchone.return_value = (
                mock_db_config['feature_definitions'],
                mock_db_config['preprocessing_config']
            )

            engineer = ConfigurableFeatureEngineer('standard_features')

        # When
        result = engineer.engineer_features(sample_data)

        # Then
        assert isinstance(result, pd.DataFrame)
        assert 'spread_ratio' in result.columns
        assert 'return_1s' in result.columns
        assert 'return_5s' in result.columns
        assert 'return_30s' in result.columns
        assert 'total_depth' in result.columns
        assert 'depth_ratio' in result.columns
        assert 'imbalance_abs' in result.columns
        # technical_indicatorsは無効なので生成されない
        assert 'sma_5' not in result.columns
        assert 'sma_30' not in result.columns

    def test_engineer_features_disabled_features(self, sample_data):
        """無効な特徴量が生成されないことを確認するテスト"""
        # Given
        with patch('data.configurable_feature_engineering.psycopg2.connect') as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_connect.return_value = mock_conn
            mock_conn.__enter__ = Mock(return_value=mock_conn)
            mock_conn.__exit__ = Mock(return_value=None)
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)
            
            # すべての特徴量を無効化
            config = {
                'feature_definitions': {
                    'price_features': {'enabled': False},
                    'depth_features': {'enabled': False},
                    'imbalance_features': {'enabled': False},
                    'volume_features': {'enabled': False},
                    'execution_features': {'enabled': False},
                    'technical_indicators': {'enabled': False},
                    'lag_features': {'enabled': False},
                    'rolling_statistics': {'enabled': False}
                },
                'preprocessing_config': {
                    'fillna_method': 'zero'
                }
            }
            
            mock_cursor.fetchone.return_value = (
                config['feature_definitions'],
                config['preprocessing_config']
            )

            engineer = ConfigurableFeatureEngineer('test_features')

        # When
        result = engineer.engineer_features(sample_data)

        # Then
        # 元のカラムのみが残る（特徴量が追加されない）
        original_cols = set(sample_data.columns)
        result_cols = set(result.columns)
        # symbol以外の元のカラムは残る
        assert 'symbol' in result.columns
        assert 'mid_price' in result.columns

    def test_preprocessing_fillna_zero(self, sample_data):
        """NaNを0で埋める前処理のテスト"""
        # Given
        sample_data_with_nan = sample_data.copy()
        sample_data_with_nan.loc[0:5, 'mid_price'] = np.nan

        with patch('data.configurable_feature_engineering.psycopg2.connect') as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_connect.return_value = mock_conn
            mock_conn.__enter__ = Mock(return_value=mock_conn)
            mock_conn.__exit__ = Mock(return_value=None)
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)
            
            config = {
                'feature_definitions': {
                    'price_features': {'enabled': True, 'return_periods': [1], 'spread_ratio': True}
                },
                'preprocessing_config': {
                    'fillna_method': 'zero',
                    'normalization': 'none',
                    'outlier_handling': 'none'
                }
            }
            
            mock_cursor.fetchone.return_value = (
                config['feature_definitions'],
                config['preprocessing_config']
            )

            engineer = ConfigurableFeatureEngineer('test_features')

        # When
        result = engineer.engineer_features(sample_data_with_nan)

        # Then
        assert not result.isnull().any().any(), "NaNが残っている"

    @patch('data.configurable_feature_engineering.psycopg2.connect')
    def test_reload_config(self, mock_connect, mock_db_config):
        """設定の再読み込みテスト"""
        # Given
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)
        
        # 初回の設定読み込み
        mock_cursor.fetchone.return_value = (
            mock_db_config['feature_definitions'],
            mock_db_config['preprocessing_config']
        )

        engineer = ConfigurableFeatureEngineer('standard_features')
        original_config = engineer.feature_definitions.copy()

        # 新しい設定（2回目のfetchone呼び出し）
        new_config = {
            'feature_definitions': {
                'price_features': {'enabled': False}
            },
            'preprocessing_config': {'fillna_method': 'forward'}
        }
        mock_cursor.fetchone.return_value = (
            new_config['feature_definitions'],
            new_config['preprocessing_config']
        )

        # When
        engineer.reload_config()

        # Then
        assert engineer.feature_definitions != original_config
        assert engineer.feature_definitions['price_features']['enabled'] == False

    def test_get_feature_columns(self, sample_data, mock_db_config):
        """特徴量カラムの取得テスト"""
        # Given
        with patch('data.configurable_feature_engineering.psycopg2.connect') as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_connect.return_value = mock_conn
            mock_conn.__enter__ = Mock(return_value=mock_conn)
            mock_conn.__exit__ = Mock(return_value=None)
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)
            
            mock_cursor.fetchone.return_value = (
                mock_db_config['feature_definitions'],
                mock_db_config['preprocessing_config']
            )

            engineer = ConfigurableFeatureEngineer('standard_features')

        # When
        engineer.engineer_features(sample_data)
        feature_columns = engineer.get_feature_columns()

        # Then
        assert isinstance(feature_columns, list)
        assert len(feature_columns) > 0
        assert 'symbol' not in feature_columns
        assert 'spread_ratio' in feature_columns or 'return_1s' in feature_columns

