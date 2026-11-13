"""
数据访问管理器

统一管理对各种数据源的访问，包括SQLite数据库、分片文件和映射文件。
提供统一的接口、错误处理、资源管理和配置管理功能。

主要功能：
1. 统一数据源访问接口
2. 自动资源管理和连接池
3. 统一错误处理和重试机制
4. 数据一致性验证
5. 性能监控和优化建议
"""

import threading
import time
from contextlib import contextmanager
from typing import Iterator, List, Dict, Optional, Any, Union, Tuple
from pathlib import Path
from datetime import datetime, timedelta

from ..core.config import DetectionConfig
from ..core.data_models import RPURecord, ConceptMapping, ShardMetadata
from ..core.exceptions import (
    DataAccessException, ConfigurationException, 
    ResourceException, ValidationException
)
from ..core.logging import get_logger

from .sqlite_manager import SQLiteManager
from .shard_file_manager import ShardFileManager
from .mapping_file_manager import MappingFileManager


class DataAccessManager:
    """数据访问管理器
    
    提供对所有数据源的统一访问接口，协调各个数据管理器的工作。
    
    特性：
    - 统一的数据源访问接口
    - 自动资源管理和连接池
    - 统一错误处理和重试机制
    - 数据一致性验证
    - 性能监控和优化
    """
    
    def __init__(self, config: DetectionConfig):
        """初始化数据访问管理器
        
        Args:
            config: 检测配置
            
        Raises:
            ConfigurationException: 配置无效
            DataAccessException: 数据源初始化失败
        """
        self.config = config
        self.logger = get_logger(self.__class__.__name__)
        
        # 线程安全锁
        self._lock = threading.RLock()
        
        # 连接状态管理
        self._initialized = False
        self._closed = False
        
        # 性能统计
        self._stats = {
            'total_queries': 0,
            'failed_queries': 0,
            'total_processing_time': 0.0,
            'last_access_time': None,
            'connection_errors': 0
        }
        
        # 验证配置
        self._validate_config()
        
        # 初始化各个数据管理器
        self._initialize_managers()
        
        self._initialized = True
        self.logger.info("数据访问管理器初始化完成")
    
    def _validate_config(self) -> None:
        """验证配置有效性
        
        Raises:
            ConfigurationException: 配置无效
        """
        paths = self.config.paths
        
        # 检查至少有一个数据源可用
        if not any([paths.db_path, paths.output_dir, paths.mapping_path]):
            raise ConfigurationException("至少需要配置一个数据源路径")
        
        # 检查路径存在性和可访问性
        validation_errors = []
        
        if paths.db_path:
            db_path = Path(paths.db_path)
            if not db_path.exists():
                validation_errors.append(f"数据库文件不存在: {paths.db_path}")
            elif not db_path.is_file():
                validation_errors.append(f"数据库路径不是文件: {paths.db_path}")
            else:
                # 检查文件权限
                try:
                    with open(db_path, 'rb') as f:
                        f.read(1)  # 尝试读取一个字节
                except PermissionError:
                    validation_errors.append(f"数据库文件无读取权限: {paths.db_path}")
                except Exception as e:
                    validation_errors.append(f"数据库文件访问异常: {e}")
        
        if paths.output_dir:
            output_dir = Path(paths.output_dir)
            if not output_dir.exists():
                validation_errors.append(f"输出目录不存在: {paths.output_dir}")
            elif not output_dir.is_dir():
                validation_errors.append(f"输出路径不是目录: {paths.output_dir}")
        
        if paths.mapping_path:
            mapping_path = Path(paths.mapping_path)
            if not mapping_path.exists():
                validation_errors.append(f"映射文件不存在: {paths.mapping_path}")
            elif not mapping_path.is_file():
                validation_errors.append(f"映射路径不是文件: {paths.mapping_path}")
        
        if validation_errors:
            raise ConfigurationException(f"配置验证失败: {'; '.join(validation_errors)}")
    
    def _initialize_managers(self) -> None:
        """初始化各个数据管理器
        
        Raises:
            DataAccessException: 数据源初始化失败
        """
        paths = self.config.paths
        initialization_errors = []
        
        # 初始化数据库管理器
        self.db_manager = None
        if paths.db_path:
            try:
                self.db_manager = SQLiteManager(paths.db_path)
                self.logger.info(f"SQLite管理器初始化成功: {paths.db_path}")
            except Exception as e:
                error_msg = f"SQLite管理器初始化失败: {e}"
                initialization_errors.append(error_msg)
                self.logger.error(error_msg)
        
        # 初始化分片文件管理器
        self.file_manager = None
        if paths.output_dir:
            try:
                self.file_manager = ShardFileManager(paths.output_dir)
                self.logger.info(f"分片文件管理器初始化成功: {paths.output_dir}")
            except Exception as e:
                error_msg = f"分片文件管理器初始化失败: {e}"
                initialization_errors.append(error_msg)
                self.logger.error(error_msg)
        
        # 初始化映射文件管理器
        self.mapping_manager = None
        if paths.mapping_path:
            try:
                self.mapping_manager = MappingFileManager(paths.mapping_path)
                self.logger.info(f"映射文件管理器初始化成功: {paths.mapping_path}")
            except Exception as e:
                error_msg = f"映射文件管理器初始化失败: {e}"
                initialization_errors.append(error_msg)
                self.logger.error(error_msg)
        
        # 检查是否至少有一个管理器初始化成功
        active_managers = sum(1 for manager in [self.db_manager, self.file_manager, self.mapping_manager] 
                            if manager is not None)
        
        if active_managers == 0:
            raise DataAccessException(
                f"所有数据管理器初始化失败: {'; '.join(initialization_errors)}",
                data_source="all",
                operation="initialize"
            )
        
        if initialization_errors:
            self.logger.warning(f"部分数据管理器初始化失败，但系统可继续运行: {'; '.join(initialization_errors)}")
    
    @contextmanager
    def _performance_tracking(self, operation: str):
        """性能跟踪上下文管理器"""
        start_time = time.time()
        self._stats['total_queries'] += 1
        self._stats['last_access_time'] = datetime.now()
        
        try:
            yield
        except Exception as e:
            self._stats['failed_queries'] += 1
            self.logger.error(f"操作失败 {operation}: {e}")
            raise
        finally:
            elapsed_time = time.time() - start_time
            self._stats['total_processing_time'] += elapsed_time
            
            if elapsed_time > 5.0:  # 这是经验值：超过5秒的操作记录为慢查询，可根据系统性能需求调整
                self.logger.warning(f"慢操作检测 {operation}: {elapsed_time:.2f}秒")
    
    def _ensure_initialized(self) -> None:
        """确保管理器已初始化且未关闭"""
        if self._closed:
            raise DataAccessException("数据访问管理器已关闭", 
                                    data_source="manager", 
                                    operation="access_check")
        
        if not self._initialized:
            raise DataAccessException("数据访问管理器未初始化", 
                                    data_source="manager", 
                                    operation="access_check")
    
    def get_rpu_data(self, 
                     batch_size: int = 1000,
                     start_offset: int = 0,
                     filters: Optional[Dict[str, Any]] = None) -> Iterator[List[RPURecord]]:
        """流式获取RPU数据
        
        Args:
            batch_size: 批次大小，这是经验值，可根据内存情况调整
            start_offset: 起始偏移量
            filters: 过滤条件
            
        Yields:
            RPU记录批次
            
        Raises:
            DataAccessException: 数据访问失败
        """
        self._ensure_initialized()
        
        if not self.db_manager:
            raise DataAccessException("数据库管理器未初始化", 
                                    data_source="database",
                                    operation="get_rpu_data")
        
        with self._lock:
            with self._performance_tracking("get_rpu_data"):
                try:
                    self.logger.info(f"开始获取RPU数据，批次大小: {batch_size}, 偏移量: {start_offset}")
                    
                    batch_count = 0
                    total_records = 0
                    
                    for batch in self.db_manager.get_rpu_batches(
                        batch_size=batch_size,
                        start_offset=start_offset,
                        filters=filters
                    ):
                        batch_count += 1
                        total_records += len(batch)
                        
                        # 记录进度（每100批次记录一次）
                        if batch_count % 100 == 0:
                            self.logger.debug(f"已处理 {batch_count} 批次，共 {total_records} 条记录")
                        
                        yield batch
                    
                    self.logger.info(f"RPU数据获取完成，共处理 {batch_count} 批次，{total_records} 条记录")
                    
                except Exception as e:
                    self._stats['connection_errors'] += 1
                    raise DataAccessException(f"获取RPU数据失败: {e}",
                                            data_source="database",
                                            operation="get_rpu_data")
    
    def get_rpu_data_with_retry(self, 
                               batch_size: int = 1000,
                               start_offset: int = 0,
                               filters: Optional[Dict[str, Any]] = None,
                               max_retries: int = 3) -> Iterator[List[RPURecord]]:
        """带重试机制的RPU数据获取
        
        Args:
            batch_size: 批次大小
            start_offset: 起始偏移量
            filters: 过滤条件
            max_retries: 最大重试次数，这是经验值，可根据网络稳定性调整
            
        Yields:
            RPU记录批次
        """
        retry_count = 0
        last_exception = None
        
        while retry_count <= max_retries:
            try:
                yield from self.get_rpu_data(batch_size, start_offset, filters)
                return  # 成功完成，退出重试循环
                
            except DataAccessException as e:
                last_exception = e
                retry_count += 1
                
                if retry_count <= max_retries:
                    # 指数退避重试，经验值：基础延迟1秒，最大延迟16秒
                    delay = min(2 ** (retry_count - 1), 16)
                    self.logger.warning(f"RPU数据获取失败，{delay}秒后重试 (第{retry_count}次): {e}")
                    time.sleep(delay)
                else:
                    self.logger.error(f"RPU数据获取重试失败，已达最大重试次数 {max_retries}")
                    raise last_exception
    
    def get_mapping_manager(self) -> MappingFileManager:
        """获取映射文件管理器
        
        Returns:
            映射文件管理器实例
            
        Raises:
            DataAccessException: 映射管理器未初始化
        """
        self._ensure_initialized()
        
        if not self.mapping_manager:
            raise DataAccessException("映射文件管理器未初始化",
                                    data_source="mapping_file",
                                    operation="get_mapping_manager")
        
        return self.mapping_manager
    
    def get_mapping_data(self, force_reload: bool = False) -> Dict[str, str]:
        """获取概念映射数据
        
        Args:
            force_reload: 是否强制重新加载
        
        Returns:
            概念映射字典
            
        Raises:
            DataAccessException: 数据访问失败
        """
        self._ensure_initialized()
        
        if not self.mapping_manager:
            raise DataAccessException("映射文件管理器未初始化",
                                    data_source="mapping_file",
                                    operation="get_mapping_data")
        
        with self._performance_tracking("get_mapping_data"):
            try:
                self.logger.info(f"获取概念映射数据，强制重载: {force_reload}")
                mappings = self.mapping_manager.load_mappings(force_reload=force_reload)
                self.logger.info(f"成功加载 {len(mappings)} 个概念映射")
                return mappings
                
            except Exception as e:
                raise DataAccessException(f"获取概念映射数据失败: {e}",
                                        data_source="mapping_file",
                                        operation="get_mapping_data")
    
    def get_shard_metadata(self, refresh: bool = False) -> List[ShardMetadata]:
        """获取分片元数据
        
        Args:
            refresh: 是否刷新索引
        
        Returns:
            分片元数据列表
            
        Raises:
            DataAccessException: 数据访问失败
        """
        self._ensure_initialized()
        
        if not self.file_manager:
            raise DataAccessException("分片文件管理器未初始化",
                                    data_source="shard_files",
                                    operation="get_shard_metadata")
        
        with self._performance_tracking("get_shard_metadata"):
            try:
                if refresh:
                    self.logger.info("刷新分片文件索引")
                    self.file_manager.refresh_index()
                
                self.logger.info("获取分片元数据")
                metadata_list = self.file_manager.get_all_shard_metadata()
                self.logger.info(f"成功获取 {len(metadata_list)} 个分片的元数据")
                return metadata_list
                
            except Exception as e:
                raise DataAccessException(f"获取分片元数据失败: {e}",
                                        data_source="shard_files",
                                        operation="get_shard_metadata")
    
    def get_shard_data(self, 
                      shard_id: str,
                      batch_size: int = 1000) -> Iterator[List[Dict[str, Any]]]:
        """获取指定分片的数据
        
        Args:
            shard_id: 分片ID
            batch_size: 批次大小，这是经验值，可根据内存情况调整
            
        Yields:
            数据记录批次
            
        Raises:
            DataAccessException: 数据访问失败
        """
        self._ensure_initialized()
        
        if not self.file_manager:
            raise DataAccessException("分片文件管理器未初始化",
                                    data_source="shard_files",
                                    operation="get_shard_data")
        
        with self._performance_tracking(f"get_shard_data_{shard_id}"):
            try:
                self.logger.info(f"获取分片数据: {shard_id}, 批次大小: {batch_size}")
                
                batch_count = 0
                total_records = 0
                
                for batch in self.file_manager.read_shard_data(shard_id, batch_size):
                    batch_count += 1
                    total_records += len(batch)
                    yield batch
                
                self.logger.info(f"分片数据获取完成 {shard_id}: {batch_count} 批次，{total_records} 条记录")
                
            except Exception as e:
                raise DataAccessException(f"获取分片数据失败: {e}",
                                        data_source="shard_files",
                                        operation="get_shard_data")
    
    def get_all_shard_data(self, 
                          batch_size: int = 1000,
                          shard_filter: Optional[callable] = None) -> Iterator[Tuple[str, List[Dict[str, Any]]]]:
        """获取所有分片的数据
        
        Args:
            batch_size: 批次大小
            shard_filter: 分片过滤函数，接收ShardMetadata返回bool
            
        Yields:
            (shard_id, 数据批次) 元组
            
        Raises:
            DataAccessException: 数据访问失败
        """
        self._ensure_initialized()
        
        try:
            metadata_list = self.get_shard_metadata()
            
            # 应用过滤器
            if shard_filter:
                metadata_list = [meta for meta in metadata_list if shard_filter(meta)]
                self.logger.info(f"应用过滤器后剩余 {len(metadata_list)} 个分片")
            
            for metadata in metadata_list:
                shard_id = metadata.shard_id
                try:
                    for batch in self.get_shard_data(shard_id, batch_size):
                        yield shard_id, batch
                        
                except Exception as e:
                    self.logger.error(f"处理分片失败 {shard_id}: {e}")
                    # 继续处理其他分片，不中断整个流程
                    continue
                    
        except Exception as e:
            raise DataAccessException(f"获取所有分片数据失败: {e}",
                                    data_source="shard_files",
                                    operation="get_all_shard_data")
    
    def get_total_record_count(self, use_cache: bool = True) -> Dict[str, int]:
        """获取各数据源的记录数统计
        
        Args:
            use_cache: 是否使用缓存的统计信息
        
        Returns:
            各数据源记录数字典
            
        Raises:
            DataAccessException: 数据访问失败
        """
        self._ensure_initialized()
        
        with self._performance_tracking("get_total_record_count"):
            counts = {
                'database_records': 0,
                'shard_records': 0,
                'mapping_records': 0,
                'total_records': 0
            }
            
            # 从数据库获取记录数
            if self.db_manager:
                try:
                    db_count = self.db_manager.get_total_count()
                    counts['database_records'] = db_count
                    self.logger.debug(f"数据库记录数: {db_count}")
                except Exception as e:
                    self.logger.warning(f"获取数据库记录数失败: {e}")
            
            # 从分片文件获取记录数
            if self.file_manager:
                try:
                    if use_cache:
                        # 使用缓存的元数据
                        shard_metadata = self.file_manager.get_all_shard_metadata()
                        shard_count = sum(meta.record_count for meta in shard_metadata)
                    else:
                        # 重新计算记录数
                        shard_count = 0
                        for shard_id, _ in self.file_manager._shard_index.items():
                            try:
                                for batch in self.get_shard_data(shard_id, batch_size=1000):
                                    shard_count += len(batch)
                            except Exception as e:
                                self.logger.warning(f"计算分片记录数失败 {shard_id}: {e}")
                    
                    counts['shard_records'] = shard_count
                    self.logger.debug(f"分片文件记录数: {shard_count}")
                except Exception as e:
                    self.logger.warning(f"获取分片文件记录数失败: {e}")
            
            # 从映射文件获取记录数
            if self.mapping_manager:
                try:
                    mappings = self.mapping_manager.load_mappings()
                    mapping_count = len(mappings)
                    counts['mapping_records'] = mapping_count
                    self.logger.debug(f"映射记录数: {mapping_count}")
                except Exception as e:
                    self.logger.warning(f"获取映射记录数失败: {e}")
            
            # 计算总记录数（这里使用数据库记录数作为主要指标）
            counts['total_records'] = counts['database_records'] or counts['shard_records']
            
            return counts
    
    def validate_data_consistency(self, 
                                 deep_check: bool = False,
                                 sample_size: int = 1000) -> Dict[str, Any]:
        """验证数据一致性
        
        Args:
            deep_check: 是否进行深度检查
            sample_size: 深度检查的样本大小，这是经验值，可根据性能需求调整
        
        Returns:
            一致性检查结果
        """
        self._ensure_initialized()
        
        with self._performance_tracking("validate_data_consistency"):
            results = {
                'database_consistency': True,
                'shard_consistency': True,
                'mapping_consistency': True,
                'cross_source_consistency': True,
                'issues': [],
                'warnings': [],
                'statistics': {},
                'check_timestamp': datetime.now().isoformat()
            }
            
            try:
                # 验证数据库一致性
                if self.db_manager:
                    self.logger.info("验证数据库一致性")
                    db_issues = self.db_manager.validate_consistency()
                    if db_issues:
                        results['database_consistency'] = False
                        results['issues'].extend([f"数据库: {issue}" for issue in db_issues])
                    
                    # 获取数据库统计信息
                    results['statistics']['database'] = self.db_manager.get_statistics()
                
                # 验证分片文件一致性
                if self.file_manager:
                    self.logger.info("验证分片文件一致性")
                    shard_issues = self.file_manager.validate_consistency()
                    if shard_issues:
                        results['shard_consistency'] = False
                        results['issues'].extend([f"分片文件: {issue}" for issue in shard_issues])
                    
                    # 获取分片文件统计信息
                    results['statistics']['shard_files'] = self.file_manager.get_statistics()
                
                # 验证映射文件一致性
                if self.mapping_manager:
                    self.logger.info("验证映射文件一致性")
                    mapping_issues = self.mapping_manager.validate_consistency()
                    if mapping_issues:
                        results['mapping_consistency'] = False
                        results['issues'].extend([f"映射文件: {issue}" for issue in mapping_issues])
                    
                    # 获取映射文件统计信息
                    results['statistics']['mappings'] = self.mapping_manager.get_mapping_statistics()
                
                # 验证跨数据源一致性
                self.logger.info("验证跨数据源一致性")
                cross_issues = self._validate_cross_source_consistency(deep_check, sample_size)
                if cross_issues:
                    results['cross_source_consistency'] = False
                    results['issues'].extend([f"跨数据源: {issue}" for issue in cross_issues])
                
                # 添加记录数统计
                record_counts = self.get_total_record_count()
                results['statistics']['record_counts'] = record_counts
                
                # 生成一致性摘要
                total_issues = len(results['issues'])
                if total_issues == 0:
                    results['summary'] = "所有数据源一致性检查通过"
                else:
                    results['summary'] = f"发现 {total_issues} 个一致性问题"
                
                self.logger.info(f"数据一致性验证完成: {results['summary']}")
                
            except Exception as e:
                self.logger.error(f"数据一致性验证失败: {e}")
                results['issues'].append(f"验证过程异常: {e}")
                results['database_consistency'] = False
                results['shard_consistency'] = False
                results['mapping_consistency'] = False
                results['cross_source_consistency'] = False
            
            return results
    
    def _validate_cross_source_consistency(self, 
                                          deep_check: bool = False,
                                          sample_size: int = 1000) -> List[str]:
        """验证跨数据源一致性
        
        Args:
            deep_check: 是否进行深度检查
            sample_size: 深度检查的样本大小
        
        Returns:
            发现的问题列表
        """
        issues = []
        
        try:
            # 检查数据库和分片文件中的记录是否一致
            if self.db_manager and self.file_manager:
                self.logger.debug("检查数据库与分片文件的一致性")
                
                # 获取数据库中的paper_id集合
                try:
                    db_paper_ids = set(self.db_manager.get_all_paper_ids())
                    self.logger.debug(f"数据库中的paper_id数量: {len(db_paper_ids)}")
                except Exception as e:
                    issues.append(f"获取数据库paper_id失败: {e}")
                    db_paper_ids = set()
                
                # 获取分片文件中的paper_id集合
                shard_paper_ids = set()
                try:
                    shard_metadata = self.file_manager.get_all_shard_metadata()
                    
                    if deep_check:
                        # 深度检查：遍历所有分片文件
                        for metadata in shard_metadata:
                            try:
                                shard_ids = self.file_manager.get_paper_ids_from_shard(metadata.shard_id)
                                shard_paper_ids.update(shard_ids)
                            except Exception as e:
                                issues.append(f"获取分片{metadata.shard_id}的paper_id失败: {e}")
                    else:
                        # 快速检查：只检查部分分片
                        check_count = min(len(shard_metadata), 10)  # 经验值：最多检查10个分片
                        for metadata in shard_metadata[:check_count]:
                            try:
                                shard_ids = self.file_manager.get_paper_ids_from_shard(metadata.shard_id)
                                shard_paper_ids.update(shard_ids)
                            except Exception as e:
                                issues.append(f"获取分片{metadata.shard_id}的paper_id失败: {e}")
                    
                    self.logger.debug(f"分片文件中的paper_id数量: {len(shard_paper_ids)}")
                    
                except Exception as e:
                    issues.append(f"获取分片文件paper_id失败: {e}")
                
                # 检查差异
                if db_paper_ids and shard_paper_ids:
                    db_only = db_paper_ids - shard_paper_ids
                    shard_only = shard_paper_ids - db_paper_ids
                    
                    if db_only:
                        issues.append(f"数据库中存在但分片文件中不存在的paper_id: {len(db_only)}个")
                        if len(db_only) <= 5:  # 只显示前5个示例
                            issues.append(f"示例: {list(db_only)[:5]}")
                    
                    if shard_only:
                        issues.append(f"分片文件中存在但数据库中不存在的paper_id: {len(shard_only)}个")
                        if len(shard_only) <= 5:  # 只显示前5个示例
                            issues.append(f"示例: {list(shard_only)[:5]}")
                    
                    # 计算一致性比例
                    if db_paper_ids or shard_paper_ids:
                        intersection = db_paper_ids & shard_paper_ids
                        union = db_paper_ids | shard_paper_ids
                        consistency_ratio = len(intersection) / len(union) if union else 0
                        
                        if consistency_ratio < 0.9:  # 经验值：一致性低于90%认为有问题
                            issues.append(f"数据库与分片文件一致性较低: {consistency_ratio:.2%}")
            
            # 检查映射文件和数据源的一致性
            if self.mapping_manager and (self.db_manager or self.file_manager):
                self.logger.debug("检查映射文件与数据源的一致性")
                
                try:
                    mappings = self.mapping_manager.load_mappings()
                    mapped_concepts = set(mappings.keys()) | set(mappings.values())
                    
                    # 获取数据源中的所有概念
                    all_concepts = set()
                    
                    if self.db_manager:
                        try:
                            db_concepts = self.db_manager.get_all_concepts()
                            all_concepts.update(db_concepts)
                        except Exception as e:
                            issues.append(f"获取数据库概念失败: {e}")
                    
                    # 如果进行深度检查，也从分片文件中提取概念
                    if deep_check and self.file_manager:
                        try:
                            concept_sample = set()
                            processed_records = 0
                            
                            for shard_id, batch in self.get_all_shard_data(batch_size=100):
                                for record in batch:
                                    # 提取RPU概念
                                    if 'task' in record and record['task']:
                                        concept_sample.add(str(record['task']))
                                    if 'object' in record and record['object']:
                                        concept_sample.add(str(record['object']))
                                    if 'modifier' in record and record['modifier']:
                                        concept_sample.add(str(record['modifier']))
                                    
                                    processed_records += 1
                                    if processed_records >= sample_size:
                                        break
                                
                                if processed_records >= sample_size:
                                    break
                            
                            all_concepts.update(concept_sample)
                            self.logger.debug(f"从分片文件采样获取 {len(concept_sample)} 个概念")
                            
                        except Exception as e:
                            issues.append(f"从分片文件提取概念失败: {e}")
                    
                    # 检查映射中的概念是否在数据源中存在
                    if all_concepts:
                        missing_concepts = mapped_concepts - all_concepts
                        
                        if missing_concepts:
                            missing_count = len(missing_concepts)
                            total_mapped = len(mapped_concepts)
                            missing_ratio = missing_count / total_mapped if total_mapped > 0 else 0
                            
                            issues.append(f"映射文件中存在但数据源中不存在的概念: {missing_count}个 ({missing_ratio:.2%})")
                            
                            # 如果缺失比例过高，提供示例
                            if missing_ratio > 0.1:  # 经验值：缺失超过10%认为有问题
                                sample_missing = list(missing_concepts)[:5]
                                issues.append(f"缺失概念示例: {sample_missing}")
                
                except Exception as e:
                    issues.append(f"映射文件一致性检查异常: {e}")
            
            # 检查数据源的时间戳一致性
            if self.db_manager and self.file_manager:
                try:
                    # 获取数据库最后更新时间
                    db_stats = self.db_manager.get_statistics()
                    
                    # 获取分片文件最后修改时间
                    shard_metadata = self.file_manager.get_all_shard_metadata()
                    if shard_metadata:
                        latest_shard_time = max(meta.last_modified for meta in shard_metadata)
                        
                        # 检查时间差异（这里简化处理，实际可能需要更复杂的逻辑）
                        time_diff_hours = 24  # 经验值：时间差异超过24小时可能有问题
                        if 'last_update' in db_stats:
                            try:
                                db_time = datetime.fromisoformat(db_stats['last_update'])
                                time_diff = abs((latest_shard_time - db_time).total_seconds() / 3600)
                                
                                if time_diff > time_diff_hours:
                                    issues.append(f"数据库与分片文件时间差异过大: {time_diff:.1f}小时")
                            except Exception:
                                pass  # 时间解析失败，跳过此检查
                
                except Exception as e:
                    issues.append(f"时间戳一致性检查异常: {e}")
        
        except Exception as e:
            issues.append(f"跨数据源一致性检查异常: {e}")
        
        return issues
    
    def get_data_statistics(self, include_performance: bool = True) -> Dict[str, Any]:
        """获取数据统计信息
        
        Args:
            include_performance: 是否包含性能统计
        
        Returns:
            数据统计信息
        """
        self._ensure_initialized()
        
        with self._performance_tracking("get_data_statistics"):
            stats = {
                'database': {},
                'shard_files': {},
                'mappings': {},
                'record_counts': {},
                'manager_info': {
                    'initialized_managers': [],
                    'available_data_sources': [],
                    'configuration_hash': self.config.get_config_hash(),
                    'last_access_time': self._stats['last_access_time'].isoformat() if self._stats['last_access_time'] else None
                },
                'timestamp': datetime.now().isoformat()
            }
            
            try:
                # 数据库统计
                if self.db_manager:
                    stats['database'] = self.db_manager.get_statistics()
                    stats['manager_info']['initialized_managers'].append('SQLiteManager')
                    stats['manager_info']['available_data_sources'].append('database')
                
                # 分片文件统计
                if self.file_manager:
                    stats['shard_files'] = self.file_manager.get_statistics()
                    stats['manager_info']['initialized_managers'].append('ShardFileManager')
                    stats['manager_info']['available_data_sources'].append('shard_files')
                
                # 映射文件统计
                if self.mapping_manager:
                    stats['mappings'] = self.mapping_manager.get_mapping_statistics()
                    stats['manager_info']['initialized_managers'].append('MappingFileManager')
                    stats['manager_info']['available_data_sources'].append('mappings')
                
                # 记录数统计
                stats['record_counts'] = self.get_total_record_count()
                
                # 性能统计
                if include_performance:
                    stats['performance'] = {
                        'total_queries': self._stats['total_queries'],
                        'failed_queries': self._stats['failed_queries'],
                        'success_rate': (self._stats['total_queries'] - self._stats['failed_queries']) / max(self._stats['total_queries'], 1),
                        'average_query_time': self._stats['total_processing_time'] / max(self._stats['total_queries'], 1),
                        'total_processing_time': self._stats['total_processing_time'],
                        'connection_errors': self._stats['connection_errors']
                    }
                
                # 健康状态评估
                stats['health_status'] = self._assess_health_status(stats)
                
            except Exception as e:
                self.logger.error(f"获取数据统计信息失败: {e}")
                stats['error'] = str(e)
            
            return stats
    
    def _assess_health_status(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        """评估系统健康状态
        
        Args:
            stats: 统计信息
            
        Returns:
            健康状态评估结果
        """
        health = {
            'overall_status': 'healthy',
            'issues': [],
            'warnings': [],
            'recommendations': []
        }
        
        try:
            # 检查管理器可用性
            available_managers = len(stats['manager_info']['initialized_managers'])
            if available_managers == 0:
                health['overall_status'] = 'critical'
                health['issues'].append('没有可用的数据管理器')
            elif available_managers == 1:
                health['warnings'].append('只有一个数据管理器可用，建议配置多个数据源')
            
            # 检查性能指标
            if 'performance' in stats:
                perf = stats['performance']
                
                # 检查成功率
                if perf['success_rate'] < 0.9:  # 经验值：成功率低于90%认为有问题
                    health['overall_status'] = 'degraded'
                    health['issues'].append(f"查询成功率较低: {perf['success_rate']:.2%}")
                
                # 检查平均查询时间
                if perf['average_query_time'] > 10.0:  # 经验值：平均查询时间超过10秒认为较慢
                    health['warnings'].append(f"平均查询时间较长: {perf['average_query_time']:.2f}秒")
                    health['recommendations'].append('考虑优化数据库索引或增加缓存')
                
                # 检查连接错误
                if perf['connection_errors'] > 0:
                    health['warnings'].append(f"发生了 {perf['connection_errors']} 次连接错误")
                    health['recommendations'].append('检查网络连接和数据源可用性')
            
            # 检查记录数一致性
            if 'record_counts' in stats:
                counts = stats['record_counts']
                db_count = counts.get('database_records', 0)
                shard_count = counts.get('shard_records', 0)
                
                if db_count > 0 and shard_count > 0:
                    diff_ratio = abs(db_count - shard_count) / max(db_count, shard_count)
                    if diff_ratio > 0.1:  # 经验值：差异超过10%认为不一致
                        health['warnings'].append(f"数据库与分片文件记录数差异较大: {diff_ratio:.2%}")
                        health['recommendations'].append('运行数据一致性检查以确定差异原因')
            
            # 根据问题严重性确定整体状态
            if health['issues']:
                if any('critical' in issue.lower() or 'failed' in issue.lower() for issue in health['issues']):
                    health['overall_status'] = 'critical'
                else:
                    health['overall_status'] = 'degraded'
            elif health['warnings']:
                health['overall_status'] = 'warning'
        
        except Exception as e:
            health['overall_status'] = 'unknown'
            health['issues'].append(f"健康状态评估失败: {e}")
        
        return health
    
    def optimize_performance(self) -> Dict[str, Any]:
        """优化性能
        
        Returns:
            优化结果
        """
        self._ensure_initialized()
        
        optimization_results = {
            'database_optimization': {},
            'file_system_optimization': {},
            'memory_optimization': {},
            'recommendations': [],
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            # 数据库优化
            if self.db_manager:
                self.logger.info("执行数据库优化")
                db_optimization = self.db_manager.optimize_database()
                optimization_results['database_optimization'] = db_optimization
                
                # 根据优化结果生成建议
                if 'suggested_indexes' in db_optimization and db_optimization['suggested_indexes']:
                    optimization_results['recommendations'].append(
                        f"建议创建 {len(db_optimization['suggested_indexes'])} 个数据库索引以提高查询性能"
                    )
            
            # 文件系统优化
            if self.file_manager:
                self.logger.info("执行文件系统优化")
                # 刷新分片文件索引
                self.file_manager.refresh_index()
                optimization_results['file_system_optimization']['index_refreshed'] = True
                
                # 检查文件系统状态
                shard_stats = self.file_manager.get_statistics()
                if shard_stats.get('total_size_mb', 0) > 10000:  # 经验值：超过10GB建议清理
                    optimization_results['recommendations'].append(
                        "分片文件总大小较大，建议定期清理旧文件或压缩存储"
                    )
            
            # 内存优化建议
            import psutil
            memory_info = psutil.virtual_memory()
            memory_usage_percent = memory_info.percent
            
            optimization_results['memory_optimization'] = {
                'current_usage_percent': memory_usage_percent,
                'available_gb': memory_info.available / (1024**3)
            }
            
            if memory_usage_percent > 80:  # 经验值：内存使用超过80%建议优化
                optimization_results['recommendations'].append(
                    f"系统内存使用率较高 ({memory_usage_percent:.1f}%)，建议减小批处理大小或增加内存"
                )
            
            # 配置优化建议
            batch_size = self.config.performance.batch_size
            if batch_size > 5000:  # 经验值：批次大小过大可能影响性能
                optimization_results['recommendations'].append(
                    f"当前批次大小 ({batch_size}) 较大，如遇到内存问题建议调整为1000-2000"
                )
            
            self.logger.info(f"性能优化完成，生成 {len(optimization_results['recommendations'])} 条建议")
            
        except Exception as e:
            self.logger.error(f"性能优化失败: {e}")
            optimization_results['error'] = str(e)
        
        return optimization_results
    
    def create_backup(self, backup_dir: Optional[str] = None) -> Dict[str, Any]:
        """创建数据备份
        
        Args:
            backup_dir: 备份目录，如果为None则使用默认目录
            
        Returns:
            备份结果
        """
        self._ensure_initialized()
        
        if backup_dir is None:
            backup_dir = Path(self.config.paths.temp_dir) / "backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
        else:
            backup_dir = Path(backup_dir)
        
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        backup_results = {
            'backup_directory': str(backup_dir),
            'backed_up_files': [],
            'failed_backups': [],
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            # 备份映射文件
            if self.mapping_manager and self.config.paths.mapping_path:
                try:
                    mapping_backup = backup_dir / "core_mapping.json"
                    mapping_backup.write_bytes(Path(self.config.paths.mapping_path).read_bytes())
                    backup_results['backed_up_files'].append(str(mapping_backup))
                    self.logger.info(f"映射文件备份完成: {mapping_backup}")
                except Exception as e:
                    backup_results['failed_backups'].append(f"映射文件备份失败: {e}")
            
            # 备份数据库文件（如果是文件数据库）
            if self.db_manager and self.config.paths.db_path:
                try:
                    db_backup = backup_dir / f"database_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                    db_backup.write_bytes(Path(self.config.paths.db_path).read_bytes())
                    backup_results['backed_up_files'].append(str(db_backup))
                    self.logger.info(f"数据库文件备份完成: {db_backup}")
                except Exception as e:
                    backup_results['failed_backups'].append(f"数据库文件备份失败: {e}")
            
            # 备份配置文件
            try:
                config_backup = backup_dir / "config.json"
                self.config.save_to_file(str(config_backup))
                backup_results['backed_up_files'].append(str(config_backup))
                self.logger.info(f"配置文件备份完成: {config_backup}")
            except Exception as e:
                backup_results['failed_backups'].append(f"配置文件备份失败: {e}")
            
            # 创建备份清单
            manifest = {
                'backup_timestamp': backup_results['timestamp'],
                'backed_up_files': backup_results['backed_up_files'],
                'failed_backups': backup_results['failed_backups'],
                'original_paths': {
                    'db_path': self.config.paths.db_path,
                    'mapping_path': self.config.paths.mapping_path,
                    'output_dir': self.config.paths.output_dir
                }
            }
            
            manifest_file = backup_dir / "backup_manifest.json"
            import json
            with open(manifest_file, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            
            backup_results['manifest_file'] = str(manifest_file)
            
            success_count = len(backup_results['backed_up_files'])
            failure_count = len(backup_results['failed_backups'])
            
            self.logger.info(f"备份完成: {success_count} 个文件成功，{failure_count} 个文件失败")
            
        except Exception as e:
            self.logger.error(f"创建备份失败: {e}")
            backup_results['error'] = str(e)
        
        return backup_results
    
    def close(self) -> None:
        """关闭所有数据连接和资源"""
        if self._closed:
            return
        
        with self._lock:
            try:
                self.logger.info("开始关闭数据访问管理器")
                
                # 关闭各个管理器
                managers_closed = []
                managers_failed = []
                
                if self.db_manager:
                    try:
                        self.db_manager.close()
                        managers_closed.append('SQLiteManager')
                    except Exception as e:
                        managers_failed.append(f'SQLiteManager: {e}')
                
                if self.file_manager:
                    try:
                        self.file_manager.close()
                        managers_closed.append('ShardFileManager')
                    except Exception as e:
                        managers_failed.append(f'ShardFileManager: {e}')
                
                if self.mapping_manager:
                    try:
                        self.mapping_manager.close()
                        managers_closed.append('MappingFileManager')
                    except Exception as e:
                        managers_failed.append(f'MappingFileManager: {e}')
                
                # 清理资源
                self.db_manager = None
                self.file_manager = None
                self.mapping_manager = None
                
                # 记录关闭统计
                final_stats = {
                    'total_queries_processed': self._stats['total_queries'],
                    'total_processing_time': self._stats['total_processing_time'],
                    'success_rate': (self._stats['total_queries'] - self._stats['failed_queries']) / max(self._stats['total_queries'], 1),
                    'managers_closed': managers_closed,
                    'managers_failed': managers_failed
                }
                
                self._closed = True
                
                if managers_failed:
                    self.logger.warning(f"数据访问管理器已关闭，但部分管理器关闭失败: {managers_failed}")
                else:
                    self.logger.info(f"数据访问管理器已成功关闭，处理统计: {final_stats}")
                
            except Exception as e:
                self.logger.error(f"关闭数据访问管理器失败: {e}")
                self._closed = True  # 即使失败也标记为已关闭
    
    def is_healthy(self) -> bool:
        """检查管理器是否健康
        
        Returns:
            健康状态
        """
        if self._closed or not self._initialized:
            return False
        
        try:
            # 检查至少有一个管理器可用
            active_managers = sum(1 for manager in [self.db_manager, self.file_manager, self.mapping_manager] 
                                if manager is not None)
            
            if active_managers == 0:
                return False
            
            # 检查成功率
            if self._stats['total_queries'] > 0:
                success_rate = (self._stats['total_queries'] - self._stats['failed_queries']) / self._stats['total_queries']
                if success_rate < 0.5:  # 经验值：成功率低于50%认为不健康
                    return False
            
            return True
            
        except Exception:
            return False
    
    def reset_statistics(self) -> None:
        """重置性能统计"""
        with self._lock:
            self._stats = {
                'total_queries': 0,
                'failed_queries': 0,
                'total_processing_time': 0.0,
                'last_access_time': None,
                'connection_errors': 0
            }
            self.logger.info("性能统计已重置")
    
    def get_manager_info(self) -> Dict[str, Any]:
        """获取管理器信息
        
        Returns:
            管理器信息字典
        """
        return {
            'initialized': self._initialized,
            'closed': self._closed,
            'healthy': self.is_healthy(),
            'available_managers': {
                'database': self.db_manager is not None,
                'shard_files': self.file_manager is not None,
                'mappings': self.mapping_manager is not None
            },
            'configuration': {
                'db_path': self.config.paths.db_path,
                'output_dir': self.config.paths.output_dir,
                'mapping_path': self.config.paths.mapping_path,
                'batch_size': self.config.performance.batch_size,
                'max_workers': self.config.performance.max_workers
            },
            'statistics': self._stats.copy()
        }
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()
        
        # 如果有异常，记录异常信息
        if exc_type is not None:
            self.logger.error(f"数据访问管理器上下文中发生异常: {exc_type.__name__}: {exc_val}")
        
        # 不抑制异常，让异常继续传播
        return False
    
    def __repr__(self) -> str:
        """字符串表示"""
        manager_count = sum(1 for manager in [self.db_manager, self.file_manager, self.mapping_manager] 
                          if manager is not None)
        
        status = "healthy" if self.is_healthy() else "unhealthy"
        
        return (f"DataAccessManager(managers={manager_count}, "
                f"status={status}, "
                f"queries={self._stats['total_queries']}, "
                f"closed={self._closed})")