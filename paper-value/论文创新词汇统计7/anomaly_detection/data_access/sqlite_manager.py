"""
SQLite数据库管理器

提供对SQLite数据库的访问接口，支持RPU数据的流式读取和查询。
"""

import sqlite3
import threading
from typing import Iterator, List, Dict, Any, Optional, Set
from datetime import datetime
from pathlib import Path

from ..core.data_models import RPURecord
from ..core.exceptions import DataAccessException
from ..core.logging import get_logger


class SQLiteManager:
    """SQLite数据库管理器
    
    负责管理SQLite数据库连接和数据访问操作。
    支持线程安全的数据库访问。
    """
    
    def __init__(self, db_path: str):
        """初始化SQLite管理器
        
        Args:
            db_path: 数据库文件路径
            
        Raises:
            DataAccessException: 数据库连接失败
        """
        self.db_path = Path(db_path)
        self.logger = get_logger(self.__class__.__name__)
        self._local = threading.local()  # 线程本地存储
        
        # 验证数据库文件存在
        if not self.db_path.exists():
            raise DataAccessException(f"数据库文件不存在: {db_path}",
                                    data_source="sqlite",
                                    operation="connect")
        
        # 初始化主线程连接并验证数据库结构
        try:
            connection = self._get_connection()
            cursor = connection.cursor()
            
            # 验证数据库结构
            self._validate_database_schema(cursor)
            
            self.logger.info(f"SQLite数据库连接成功: {db_path}")
            
        except Exception as e:
            raise DataAccessException(f"SQLite数据库连接失败: {e}",
                                    data_source="sqlite",
                                    operation="connect")
    
    def _get_connection(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接
        
        Returns:
            SQLite连接对象
        """
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(str(self.db_path))
            self._local.connection.row_factory = sqlite3.Row  # 使用字典式访问
            self._local.cursor = self._local.connection.cursor()
        
        return self._local.connection
    
    def _get_cursor(self) -> sqlite3.Cursor:
        """获取当前线程的数据库游标
        
        Returns:
            SQLite游标对象
        """
        connection = self._get_connection()
        if not hasattr(self._local, 'cursor') or self._local.cursor is None:
            self._local.cursor = connection.cursor()
        
        return self._local.cursor
    
    def _validate_database_schema(self, cursor: Optional[sqlite3.Cursor] = None) -> None:
        """验证数据库表结构
        
        Args:
            cursor: 可选的游标对象，如果不提供则使用当前线程的游标
        
        Raises:
            DataAccessException: 数据库结构无效
        """
        if cursor is None:
            cursor = self._get_cursor()
            
        try:
            # 检查必要的表是否存在
            required_tables = ['papers', 'rpu', 'shard_status']  # 根据实际表结构调整
            
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """)
            
            existing_tables = {row[0] for row in cursor.fetchall()}
            self.logger.debug(f"数据库中的表: {existing_tables}")
            
            # 检查核心表是否存在
            missing_tables = []
            for table in required_tables:
                if table not in existing_tables:
                    missing_tables.append(table)
            
            if missing_tables:
                raise DataAccessException(f"缺少必要的表: {missing_tables}",
                                        data_source="sqlite",
                                        operation="validate_schema")
            
            # 验证RPU表结构
            self._validate_rpu_table_structure(cursor)
            
            self.logger.info(f"数据库结构验证成功，包含表: {existing_tables}")
            
        except Exception as e:
            raise DataAccessException(f"验证数据库结构失败: {e}",
                                    data_source="sqlite",
                                    operation="validate_schema")
    
    def _validate_rpu_table_structure(self, cursor: Optional[sqlite3.Cursor] = None) -> None:
        """验证RPU表的结构
        
        Args:
            cursor: 可选的游标对象，如果不提供则使用当前线程的游标
        
        Raises:
            DataAccessException: RPU表结构无效
        """
        if cursor is None:
            cursor = self._get_cursor()
            
        try:
            # 获取RPU表的列信息
            cursor.execute("PRAGMA table_info(rpu)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}  # column_name: data_type
            
            # 检查必要的列
            required_columns = {
                'paper_id': 'TEXT',
                'sentence_index': 'INTEGER', 
                'task': 'TEXT',
                'object': 'TEXT'
            }
            
            missing_columns = []
            for col_name, expected_type in required_columns.items():
                if col_name not in columns:
                    missing_columns.append(col_name)
            
            if missing_columns:
                raise DataAccessException(f"RPU表缺少必要的列: {missing_columns}",
                                        data_source="sqlite",
                                        operation="validate_rpu_structure")
            
            self.logger.debug(f"RPU表结构验证成功，包含列: {list(columns.keys())}")
            
        except Exception as e:
            raise DataAccessException(f"验证RPU表结构失败: {e}",
                                    data_source="sqlite",
                                    operation="validate_rpu_structure")
    
    def get_rpu_batches(self, 
                       batch_size: int = 1000,
                       start_offset: int = 0,
                       filters: Optional[Dict[str, Any]] = None) -> Iterator[List[RPURecord]]:
        """流式获取RPU数据批次
        
        Args:
            batch_size: 批次大小，这是经验值，可根据内存情况调整
            start_offset: 起始偏移量
            filters: 过滤条件
            
        Yields:
            RPU记录批次
            
        Raises:
            DataAccessException: 数据查询失败
        """
        try:
            cursor = self._get_cursor()
            
            # 构建查询语句
            base_query = self._build_rpu_query(filters)
            query = f"{base_query} LIMIT ? OFFSET ?"
            
            offset = start_offset
            
            while True:
                cursor.execute(query, (batch_size, offset))
                rows = cursor.fetchall()
                
                if not rows:
                    break
                
                # 转换为RPURecord对象
                batch = []
                for row in rows:
                    try:
                        rpu_record = self._row_to_rpu_record(row)
                        batch.append(rpu_record)
                    except Exception as e:
                        self.logger.warning(f"转换RPU记录失败: {e}, 跳过记录")
                        continue
                
                if batch:
                    yield batch
                
                offset += batch_size
                
                # 如果返回的记录数少于批次大小，说明已到末尾
                if len(rows) < batch_size:
                    break
        
        except Exception as e:
            raise DataAccessException(f"获取RPU数据批次失败: {e}",
                                    data_source="sqlite",
                                    operation="get_rpu_batches")
    
    def _build_rpu_query(self, filters: Optional[Dict[str, Any]] = None) -> str:
        """构建RPU查询语句
        
        Args:
            filters: 过滤条件
            
        Returns:
            SQL查询语句
        """
        # 基础查询 - 根据实际表结构调整
        base_query = """
        SELECT 
            paper_id,
            sentence_index as sentence_id,
            task,
            object,
            COALESCE(aspect, '') as modifier,
            1.0 as confidence,
            COALESCE(model_version, 'unknown') as extraction_method,
            created_at as timestamp,
            '' as shard_id
        FROM rpu
        """
        
        # 添加过滤条件
        where_conditions = []
        if filters:
            if 'paper_id' in filters:
                where_conditions.append(f"paper_id = '{filters['paper_id']}'")
            
            if 'min_confidence' in filters:
                # 由于实际表中没有confidence字段，这里跳过此过滤条件
                self.logger.warning("实际数据库中没有confidence字段，跳过置信度过滤")
            
            if 'extraction_method' in filters:
                where_conditions.append(f"model_version = '{filters['extraction_method']}'")
            
            if 'date_range' in filters:
                start_date, end_date = filters['date_range']
                where_conditions.append(f"created_at BETWEEN '{start_date}' AND '{end_date}'")
            
            if 'pub_year_range' in filters:
                # 需要连接papers表来获取发表年份
                start_year, end_year = filters['pub_year_range']
                base_query = """
                SELECT 
                    r.paper_id,
                    r.sentence_index as sentence_id,
                    r.task,
                    r.object,
                    COALESCE(r.aspect, '') as modifier,
                    1.0 as confidence,
                    COALESCE(r.model_version, 'unknown') as extraction_method,
                    r.created_at as timestamp,
                    '' as shard_id
                FROM rpu r
                JOIN papers p ON r.paper_id = p.paper_id
                """
                where_conditions.append(f"p.pub_year BETWEEN {start_year} AND {end_year}")
        
        if where_conditions:
            base_query += " WHERE " + " AND ".join(where_conditions)
        
        base_query += " ORDER BY paper_id, sentence_index"
        
        return base_query
    
    def _row_to_rpu_record(self, row: sqlite3.Row) -> RPURecord:
        """将数据库行转换为RPURecord对象
        
        Args:
            row: 数据库行
            
        Returns:
            RPURecord对象
        """
        # 处理时间戳
        timestamp = row['timestamp']
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except ValueError:
                try:
                    # 尝试其他时间格式
                    timestamp = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    timestamp = datetime.now()
        elif timestamp is None:
            timestamp = datetime.now()
        
        # 处理sentence_id - 实际数据库中是sentence_index
        # sqlite3.Row对象支持字典式访问但没有get方法，需要使用try/except
        try:
            sentence_id = row['sentence_id']
        except (KeyError, IndexError):
            try:
                sentence_id = row['sentence_index']
            except (KeyError, IndexError):
                sentence_id = ''
        
        # 安全获取其他字段
        def safe_get(row, key, default=''):
            try:
                value = row[key]
                return value if value is not None else default
            except (KeyError, IndexError):
                return default
        
        return RPURecord(
            paper_id=str(safe_get(row, 'paper_id', '')),
            sentence_id=str(sentence_id),
            task=str(safe_get(row, 'task', '')),
            object=str(safe_get(row, 'object', '')),
            modifier=str(safe_get(row, 'modifier', '')),
            confidence=float(safe_get(row, 'confidence', 1.0)),
            extraction_method=str(safe_get(row, 'extraction_method', 'unknown')),
            timestamp=timestamp,
            shard_id=str(safe_get(row, 'shard_id', ''))
        )
    
    def get_total_count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """获取总记录数
        
        Args:
            filters: 过滤条件
            
        Returns:
            记录总数
            
        Raises:
            DataAccessException: 查询失败
        """
        try:
            cursor = self._get_cursor()
            base_query = self._build_rpu_query(filters)
            count_query = f"SELECT COUNT(*) FROM ({base_query})"
            
            cursor.execute(count_query)
            result = cursor.fetchone()
            
            return result[0] if result else 0
        
        except Exception as e:
            raise DataAccessException(f"获取记录总数失败: {e}",
                                    data_source="sqlite",
                                    operation="get_total_count")
    
    def get_all_paper_ids(self) -> Set[str]:
        """获取所有paper_id
        
        Returns:
            paper_id集合
            
        Raises:
            DataAccessException: 查询失败
        """
        try:
            cursor = self._get_cursor()
            cursor.execute("SELECT DISTINCT paper_id FROM rpu")
            rows = cursor.fetchall()
            
            return {str(row[0]) for row in rows}
        
        except Exception as e:
            raise DataAccessException(f"获取paper_id列表失败: {e}",
                                    data_source="sqlite",
                                    operation="get_all_paper_ids")
    
    def get_all_concepts(self) -> Set[str]:
        """获取所有概念（task, object, aspect）
        
        Returns:
            概念集合
            
        Raises:
            DataAccessException: 查询失败
        """
        try:
            cursor = self._get_cursor()
            concepts = set()
            
            # 获取所有task
            cursor.execute("SELECT DISTINCT task FROM rpu WHERE task IS NOT NULL AND task != ''")
            concepts.update(str(row[0]) for row in cursor.fetchall())
            
            # 获取所有object
            cursor.execute("SELECT DISTINCT object FROM rpu WHERE object IS NOT NULL AND object != ''")
            concepts.update(str(row[0]) for row in cursor.fetchall())
            
            # 获取所有aspect (对应modifier)
            cursor.execute("SELECT DISTINCT aspect FROM rpu WHERE aspect IS NOT NULL AND aspect != ''")
            concepts.update(str(row[0]) for row in cursor.fetchall())
            
            return concepts
        
        except Exception as e:
            raise DataAccessException(f"获取概念列表失败: {e}",
                                    data_source="sqlite",
                                    operation="get_all_concepts")
    
    def validate_consistency(self) -> List[str]:
        """验证数据库一致性
        
        Returns:
            发现的问题列表
        """
        issues = []
        
        try:
            cursor = self._get_cursor()
            
            # 检查空值
            cursor.execute("""
                SELECT COUNT(*) FROM rpu 
                WHERE paper_id IS NULL OR paper_id = ''
            """)
            null_paper_ids = cursor.fetchone()[0]
            if null_paper_ids > 0:
                issues.append(f"发现 {null_paper_ids} 条记录的paper_id为空")
            
            # 检查重复记录
            cursor.execute("""
                SELECT paper_id, sentence_index, COUNT(*) as cnt
                FROM rpu 
                GROUP BY paper_id, sentence_index
                HAVING cnt > 1
            """)
            duplicates = cursor.fetchall()
            if duplicates:
                issues.append(f"发现 {len(duplicates)} 组重复的paper_id+sentence_index组合")
            
            # 检查必要字段
            cursor.execute("""
                SELECT COUNT(*) FROM rpu 
                WHERE (task IS NULL OR task = '') 
                AND (object IS NULL OR object = '')
            """)
            empty_content = cursor.fetchone()[0]
            if empty_content > 0:
                issues.append(f"发现 {empty_content} 条记录的task和object都为空")
            
            # 检查papers表和rpu表的一致性
            cursor.execute("""
                SELECT COUNT(DISTINCT r.paper_id) as rpu_papers,
                       (SELECT COUNT(*) FROM papers) as total_papers
                FROM rpu r
            """)
            result = cursor.fetchone()
            rpu_papers, total_papers = result[0], result[1]
            if rpu_papers != total_papers:
                issues.append(f"RPU表中的论文数({rpu_papers})与papers表中的论文数({total_papers})不一致")
        
        except Exception as e:
            issues.append(f"数据库一致性检查异常: {e}")
        
        return issues
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取数据库统计信息
        
        Returns:
            统计信息字典
        """
        stats = {}
        
        try:
            cursor = self._get_cursor()
            
            # 总记录数
            cursor.execute("SELECT COUNT(*) FROM rpu")
            stats['total_records'] = cursor.fetchone()[0]
            
            # 唯一paper数量
            cursor.execute("SELECT COUNT(DISTINCT paper_id) FROM rpu")
            stats['unique_papers'] = cursor.fetchone()[0]
            
            # 模型版本分布
            cursor.execute("""
                SELECT model_version, COUNT(*) 
                FROM rpu 
                WHERE model_version IS NOT NULL
                GROUP BY model_version
            """)
            stats['model_versions'] = dict(cursor.fetchall())
            
            # 年份分布（需要连接papers表）
            cursor.execute("""
                SELECT p.pub_year, COUNT(r.id) as rpu_count
                FROM papers p
                LEFT JOIN rpu r ON p.paper_id = r.paper_id
                WHERE p.pub_year IS NOT NULL
                GROUP BY p.pub_year
                ORDER BY p.pub_year
            """)
            stats['year_distribution'] = dict(cursor.fetchall())
            
            # 分片状态统计
            cursor.execute("""
                SELECT status, COUNT(*) 
                FROM shard_status 
                GROUP BY status
            """)
            stats['shard_status'] = dict(cursor.fetchall())
            
            # 数据库文件大小
            stats['file_size_mb'] = self.db_path.stat().st_size / (1024 * 1024)
            
            # 平均每篇论文的RPU数量
            if stats['unique_papers'] > 0:
                stats['avg_rpu_per_paper'] = stats['total_records'] / stats['unique_papers']
            else:
                stats['avg_rpu_per_paper'] = 0
            
        except Exception as e:
            self.logger.error(f"获取数据库统计信息失败: {e}")
            stats['error'] = str(e)
        
        return stats
    
    def execute_custom_query(self, query: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        """执行自定义查询
        
        Args:
            query: SQL查询语句
            params: 查询参数
            
        Returns:
            查询结果
            
        Raises:
            DataAccessException: 查询执行失败
        """
        try:
            cursor = self._get_cursor()
            
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            rows = cursor.fetchall()
            
            # 转换为字典列表
            return [dict(row) for row in rows]
        
        except Exception as e:
            raise DataAccessException(f"执行自定义查询失败: {e}",
                                    data_source="sqlite",
                                    operation="execute_custom_query")
    
    def optimize_database(self) -> Dict[str, Any]:
        """优化数据库性能
        
        执行数据库优化操作，包括分析表、重建索引等。
        
        Returns:
            优化结果统计
        """
        optimization_results = {}
        
        try:
            cursor = self._get_cursor()
            connection = self._get_connection()
            
            # 分析表统计信息
            cursor.execute("ANALYZE")
            optimization_results['analyze_completed'] = True
            
            # 检查索引使用情况
            index_info = self._check_index_usage()
            optimization_results['index_info'] = index_info
            
            # 建议创建的索引
            suggested_indexes = self._suggest_indexes()
            optimization_results['suggested_indexes'] = suggested_indexes
            
            # 数据库完整性检查
            cursor.execute("PRAGMA integrity_check")
            integrity_result = cursor.fetchone()[0]
            optimization_results['integrity_check'] = integrity_result
            
            # 获取数据库配置信息
            db_config = self._get_database_config()
            optimization_results['database_config'] = db_config
            
            self.logger.info("数据库优化完成")
            
        except Exception as e:
            self.logger.error(f"数据库优化失败: {e}")
            optimization_results['error'] = str(e)
        
        return optimization_results
    
    def _check_index_usage(self) -> Dict[str, Any]:
        """检查索引使用情况
        
        Returns:
            索引使用统计
        """
        index_info = {}
        
        try:
            cursor = self._get_cursor()
            
            # 获取所有索引信息
            cursor.execute("""
                SELECT name, tbl_name, sql 
                FROM sqlite_master 
                WHERE type = 'index' AND name NOT LIKE 'sqlite_%'
            """)
            indexes = cursor.fetchall()
            
            index_info['total_indexes'] = len(indexes)
            index_info['indexes'] = [dict(row) for row in indexes]
            
            # 检查表的统计信息
            for table in ['rpu', 'papers', 'shard_status']:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    index_info[f'{table}_count'] = count
                except:
                    pass
            
        except Exception as e:
            index_info['error'] = str(e)
        
        return index_info
    
    def _suggest_indexes(self) -> List[str]:
        """建议创建的索引
        
        Returns:
            建议的索引创建语句列表
        """
        suggestions = []
        
        try:
            cursor = self._get_cursor()
            
            # 检查是否存在常用查询的索引
            existing_indexes = set()
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type = 'index' AND name NOT LIKE 'sqlite_%'
            """)
            for row in cursor.fetchall():
                existing_indexes.add(row[0])
            
            # 建议的索引（基于常见查询模式）
            suggested_indexes = [
                ("idx_rpu_task", "CREATE INDEX IF NOT EXISTS idx_rpu_task ON rpu(task)"),
                ("idx_rpu_object", "CREATE INDEX IF NOT EXISTS idx_rpu_object ON rpu(object)"),
                ("idx_rpu_aspect", "CREATE INDEX IF NOT EXISTS idx_rpu_aspect ON rpu(aspect)"),
                ("idx_rpu_created_at", "CREATE INDEX IF NOT EXISTS idx_rpu_created_at ON rpu(created_at)"),
                ("idx_rpu_model_version", "CREATE INDEX IF NOT EXISTS idx_rpu_model_version ON rpu(model_version)"),
                ("idx_papers_title", "CREATE INDEX IF NOT EXISTS idx_papers_title ON papers(title)"),
                ("idx_shard_status_status", "CREATE INDEX IF NOT EXISTS idx_shard_status_status ON shard_status(status)")
            ]
            
            # 只建议不存在的索引
            for idx_name, idx_sql in suggested_indexes:
                if idx_name not in existing_indexes:
                    suggestions.append(idx_sql)
            
        except Exception as e:
            suggestions.append(f"# 索引建议生成失败: {e}")
        
        return suggestions
    
    def _get_database_config(self) -> Dict[str, Any]:
        """获取数据库配置信息
        
        Returns:
            数据库配置字典
        """
        config = {}
        
        try:
            cursor = self._get_cursor()
            
            # 获取重要的PRAGMA设置
            pragma_settings = [
                'cache_size',
                'journal_mode', 
                'synchronous',
                'temp_store',
                'mmap_size',
                'page_size'
            ]
            
            for setting in pragma_settings:
                try:
                    cursor.execute(f"PRAGMA {setting}")
                    result = cursor.fetchone()
                    config[setting] = result[0] if result else None
                except:
                    config[setting] = "unknown"
            
        except Exception as e:
            config['error'] = str(e)
        
        return config
    
    def create_suggested_indexes(self) -> Dict[str, bool]:
        """创建建议的索引
        
        Returns:
            索引创建结果字典
        """
        results = {}
        
        try:
            cursor = self._get_cursor()
            connection = self._get_connection()
            suggested_indexes = self._suggest_indexes()
            
            for idx_sql in suggested_indexes:
                if idx_sql.startswith('#'):
                    continue
                
                try:
                    cursor.execute(idx_sql)
                    connection.commit()
                    
                    # 提取索引名称
                    idx_name = idx_sql.split('idx_')[1].split(' ')[0] if 'idx_' in idx_sql else 'unknown'
                    results[f'idx_{idx_name}'] = True
                    self.logger.info(f"成功创建索引: {idx_sql}")
                    
                except Exception as e:
                    idx_name = idx_sql.split('idx_')[1].split(' ')[0] if 'idx_' in idx_sql else 'unknown'
                    results[f'idx_{idx_name}'] = False
                    self.logger.warning(f"创建索引失败: {idx_sql}, 错误: {e}")
            
        except Exception as e:
            results['error'] = str(e)
        
        return results
    
    def get_query_plan(self, query: str) -> List[Dict[str, Any]]:
        """获取查询执行计划
        
        Args:
            query: SQL查询语句
            
        Returns:
            查询执行计划
        """
        try:
            cursor = self._get_cursor()
            cursor.execute(f"EXPLAIN QUERY PLAN {query}")
            plan = cursor.fetchall()
            
            return [dict(row) for row in plan]
        
        except Exception as e:
            self.logger.error(f"获取查询执行计划失败: {e}")
            return [{'error': str(e)}]
    
    def close(self) -> None:
        """关闭数据库连接"""
        try:
            # 关闭当前线程的连接
            if hasattr(self._local, 'cursor') and self._local.cursor:
                self._local.cursor.close()
                self._local.cursor = None
            
            if hasattr(self._local, 'connection') and self._local.connection:
                self._local.connection.close()
                self._local.connection = None
            
            self.logger.info("SQLite数据库连接已关闭")
        
        except Exception as e:
            self.logger.error(f"关闭SQLite数据库连接失败: {e}")
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()