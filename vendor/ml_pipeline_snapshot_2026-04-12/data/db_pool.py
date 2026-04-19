"""
データベース接続プール
psycopg2 の接続プールを使用してデータベース接続を管理します
"""
import psycopg2
from psycopg2 import pool
from typing import Optional
from config.settings import DatabaseConfig


class DatabaseConnectionPool:
    """データベース接続プール管理クラス"""
    
    _exch_sim_pool: Optional[pool.ThreadedConnectionPool] = None
    _algo_trader_pool: Optional[pool.ThreadedConnectionPool] = None
    
    @classmethod
    def get_exch_sim_pool(cls) -> pool.ThreadedConnectionPool:
        """exch_simデータベースの接続プールを取得（シングルトン）"""
        if cls._exch_sim_pool is None:
            connection_string = DatabaseConfig.get_exch_sim_connection_string()
            
            # 接続文字列をパース
            # postgresql://user:password@host:port/dbname 形式から
            # psycopg2.connect() に渡す形式に変換
            import re
            match = re.match(r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', connection_string)
            if not match:
                raise ValueError(f"Invalid connection string format: {connection_string}")
            
            user, password, host, port, dbname = match.groups()
            
            cls._exch_sim_pool = pool.ThreadedConnectionPool(
                minconn=DatabaseConfig.POOL_MIN_CONNECTIONS,
                maxconn=DatabaseConfig.POOL_MAX_CONNECTIONS,
                host=host,
                port=int(port),
                database=dbname,
                user=user,
                password=password,
                connect_timeout=DatabaseConfig.POOL_CONNECTION_TIMEOUT
            )
        
        return cls._exch_sim_pool
    
    @classmethod
    def get_algo_trader_pool(cls) -> pool.ThreadedConnectionPool:
        """algo_traderデータベースの接続プールを取得（シングルトン）"""
        if cls._algo_trader_pool is None:
            connection_string = DatabaseConfig.get_connection_string()
            
            # 接続文字列をパース
            import re
            match = re.match(r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', connection_string)
            if not match:
                raise ValueError(f"Invalid connection string format: {connection_string}")
            
            user, password, host, port, dbname = match.groups()
            
            cls._algo_trader_pool = pool.ThreadedConnectionPool(
                minconn=DatabaseConfig.POOL_MIN_CONNECTIONS,
                maxconn=DatabaseConfig.POOL_MAX_CONNECTIONS,
                host=host,
                port=int(port),
                database=dbname,
                user=user,
                password=password,
                connect_timeout=DatabaseConfig.POOL_CONNECTION_TIMEOUT
            )
        
        return cls._algo_trader_pool
    
    @classmethod
    def get_connection(cls, use_exch_sim_db: bool = True):
        """
        接続プールから接続を取得
        
        Args:
            use_exch_sim_db: True の場合は exch_sim データベース、False の場合は algo_trader データベース
        
        Returns:
            psycopg2 の接続オブジェクト
        
        Raises:
            pool.PoolError: 接続プールから接続を取得できない場合
        """
        if use_exch_sim_db:
            pool_instance = cls.get_exch_sim_pool()
        else:
            pool_instance = cls.get_algo_trader_pool()
        
        return pool_instance.getconn()
    
    @classmethod
    def put_connection(cls, conn, use_exch_sim_db: bool = True):
        """
        接続をプールに返却
        
        Args:
            conn: 返却する接続オブジェクト
            use_exch_sim_db: True の場合は exch_sim データベース、False の場合は algo_trader データベース
        """
        if conn is None:
            return
        
        try:
            if use_exch_sim_db:
                pool_instance = cls.get_exch_sim_pool()
            else:
                pool_instance = cls.get_algo_trader_pool()
            
            pool_instance.putconn(conn)
        except Exception as e:
            # 接続の返却に失敗した場合は接続を閉じる
            try:
                conn.close()
            except:
                pass
            print(f"Warning: Failed to return connection to pool: {e}")
    
    @classmethod
    def close_all_pools(cls):
        """すべての接続プールを閉じる"""
        if cls._exch_sim_pool is not None:
            cls._exch_sim_pool.closeall()
            cls._exch_sim_pool = None
        
        if cls._algo_trader_pool is not None:
            cls._algo_trader_pool.closeall()
            cls._algo_trader_pool = None
    
    @classmethod
    def get_pool_stats(cls, use_exch_sim_db: bool = True) -> dict:
        """
        接続プールの統計情報を取得
        
        Args:
            use_exch_sim_db: True の場合は exch_sim データベース、False の場合は algo_trader データベース
        
        Returns:
            統計情報の辞書
        """
        if use_exch_sim_db:
            pool_instance = cls.get_exch_sim_pool()
        else:
            pool_instance = cls.get_algo_trader_pool()
        
        return {
            'minconn': pool_instance.minconn,
            'maxconn': pool_instance.maxconn,
            'closed': pool_instance.closed
        }

