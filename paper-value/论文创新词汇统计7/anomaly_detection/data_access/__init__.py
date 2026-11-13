"""
数据访问层 - 提供对各种数据源的统一访问接口
"""

from .manager import DataAccessManager
from .sqlite_manager import SQLiteManager
from .shard_file_manager import ShardFileManager
from .mapping_file_manager import MappingFileManager

__all__ = [
    'DataAccessManager',
    'SQLiteManager',
    'ShardFileManager', 
    'MappingFileManager'
]