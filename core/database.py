"""
数据库连接管理
使用 SQLModel 和 SQLAlchemy 进行数据库操作
"""

from typing import Generator
from sqlmodel import SQLModel, create_engine, Session
from contextlib import contextmanager

from core.local_paths import database_path, ensure_local_dirs
from core.logger import get_logger

# 获取日志器
logger = get_logger(__name__)


class DatabaseManager:
    """数据库管理器"""

    def __init__(self):
        self.engine = None
        self._initialize_engine()

    def _initialize_engine(self):
        """初始化数据库引擎"""
        try:
            ensure_local_dirs()
            database_url = f"sqlite:///{database_path()}"
            self.engine = create_engine(
                database_url,
                connect_args={"check_same_thread": False},
                echo=False,
                future=True,
            )

            logger.info(f"SQLite 数据库引擎初始化成功: {database_path()}")

        except Exception as e:
            logger.error(f"数据库引擎初始化失败: {e}")
            self.engine = None
            raise

    def create_tables(self):
        """创建数据库表"""
        try:
            if self.engine is None:
                raise Exception("数据库引擎未初始化")

            SQLModel.metadata.create_all(self.engine)
            logger.info("数据库表创建成功")

        except Exception as e:
            logger.error(f"创建数据库表失败: {e}")
            raise

    def get_session(self) -> Session:
        """获取数据库会话"""
        if self.engine is None:
            raise Exception("数据库引擎未初始化")

        return Session(self.engine)

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """数据库会话上下文管理器"""
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def test_connection(self) -> bool:
        """测试数据库连接"""
        try:
            from sqlalchemy import text

            with self.session_scope() as session:
                session.exec(text("SELECT 1"))
            logger.info("数据库连接测试成功")
            return True
        except Exception as e:
            logger.error(f"数据库连接测试失败: {e}")
            return False

    def close(self):
        """关闭数据库连接"""
        if self.engine:
            self.engine.dispose()
            logger.info("数据库连接已关闭")


# 创建全局数据库管理器实例
try:
    db_manager = DatabaseManager()
except Exception as e:
    logger.warning(f"数据库管理器初始化失败: {e}")
    db_manager = None

__all__ = ["db_manager", "DatabaseManager"]
