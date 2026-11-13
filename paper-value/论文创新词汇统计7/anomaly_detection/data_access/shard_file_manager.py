"""
分片文件管理器

管理分片输出文件的访问，支持元数据解析、文件完整性检查和数据读取。
"""

import json
import hashlib
from typing import Iterator, List, Dict, Any, Optional, Set
from datetime import datetime
from pathlib import Path

from ..core.data_models import ShardMetadata, ProcessingStatus
from ..core.exceptions import DataAccessException
from ..core.logging import get_logger


class ShardFileManager:
    """分片文件管理器
    
    负责管理和访问分片输出文件，提供元数据解析和数据读取功能。
    """
    
    def __init__(self, output_dir: str):
        """初始化分片文件管理器
        
        Args:
            output_dir: 输出目录路径
            
        Raises:
            DataAccessException: 输出目录不存在或无法访问
        """
        self.output_dir = Path(output_dir)
        self.logger = get_logger(self.__class__.__name__)
        
        # 验证输出目录
        if not self.output_dir.exists():
            raise DataAccessException(f"输出目录不存在: {output_dir}",
                                    data_source="shard_files",
                                    operation="initialize")
        
        if not self.output_dir.is_dir():
            raise DataAccessException(f"输出路径不是目录: {output_dir}",
                                    data_source="shard_files",
                                    operation="initialize")
        
        # 扫描和索引分片文件
        self._shard_index: Dict[str, Path] = {}
        self._metadata_cache: Dict[str, ShardMetadata] = {}
        
        try:
            self._scan_shard_files()
            self.logger.info(f"分片文件管理器初始化完成，发现 {len(self._shard_index)} 个分片文件")
        
        except Exception as e:
            raise DataAccessException(f"扫描分片文件失败: {e}",
                                    data_source="shard_files",
                                    operation="scan_files")
    
    def _scan_shard_files(self) -> None:
        """扫描输出目录中的分片文件"""
        # 支持的文件格式
        supported_extensions = {'.jsonl', '.json', '.csv'}
        
        # 扫描所有子目录
        for file_path in self.output_dir.rglob('*'):
            if file_path.is_file() and file_path.suffix in supported_extensions:
                # 生成分片ID（基于相对路径）
                relative_path = file_path.relative_to(self.output_dir)
                shard_id = str(relative_path).replace('/', '_').replace('\\', '_')
                
                self._shard_index[shard_id] = file_path
                
                self.logger.debug(f"发现分片文件: {shard_id} -> {file_path}")
    
    def get_all_shard_metadata(self) -> List[ShardMetadata]:
        """获取所有分片的元数据
        
        Returns:
            分片元数据列表
            
        Raises:
            DataAccessException: 获取元数据失败
        """
        try:
            metadata_list = []
            
            for shard_id, file_path in self._shard_index.items():
                try:
                    metadata = self._get_shard_metadata(shard_id, file_path)
                    metadata_list.append(metadata)
                except Exception as e:
                    self.logger.warning(f"获取分片元数据失败 {shard_id}: {e}")
                    continue
            
            return metadata_list
        
        except Exception as e:
            raise DataAccessException(f"获取分片元数据失败: {e}",
                                    data_source="shard_files",
                                    operation="get_all_metadata")
    
    def _get_shard_metadata(self, shard_id: str, file_path: Path) -> ShardMetadata:
        """获取单个分片的元数据
        
        Args:
            shard_id: 分片ID
            file_path: 文件路径
            
        Returns:
            分片元数据
        """
        # 检查缓存
        if shard_id in self._metadata_cache:
            return self._metadata_cache[shard_id]
        
        # 获取文件统计信息
        stat = file_path.stat()
        
        # 计算文件校验和
        checksum = self._calculate_file_checksum(file_path)
        
        # 计算记录数量
        record_count = self._count_records(file_path)
        
        # 创建元数据对象
        metadata = ShardMetadata(
            shard_id=shard_id,
            file_path=str(file_path),
            file_size=stat.st_size,
            record_count=record_count,
            creation_time=datetime.fromtimestamp(stat.st_ctime),
            last_modified=datetime.fromtimestamp(stat.st_mtime),
            checksum=checksum,
            processing_status=ProcessingStatus.COMPLETED
        )
        
        # 缓存元数据
        self._metadata_cache[shard_id] = metadata
        
        return metadata
    
    def _calculate_file_checksum(self, file_path: Path) -> str:
        """计算文件MD5校验和
        
        Args:
            file_path: 文件路径
            
        Returns:
            MD5校验和
        """
        try:
            hash_md5 = hashlib.md5()
            
            with open(file_path, 'rb') as f:
                # 分块读取以处理大文件
                chunk_size = 8192  # 这是经验值，可根据性能需求调整
                while chunk := f.read(chunk_size):
                    hash_md5.update(chunk)
            
            return hash_md5.hexdigest()
        
        except Exception as e:
            self.logger.warning(f"计算文件校验和失败 {file_path}: {e}")
            return ""
    
    def _count_records(self, file_path: Path) -> int:
        """计算文件中的记录数量
        
        Args:
            file_path: 文件路径
            
        Returns:
            记录数量
        """
        try:
            if file_path.suffix == '.jsonl':
                return self._count_jsonl_records(file_path)
            elif file_path.suffix == '.json':
                return self._count_json_records(file_path)
            elif file_path.suffix == '.csv':
                return self._count_csv_records(file_path)
            else:
                return 0
        
        except Exception as e:
            self.logger.warning(f"计算记录数量失败 {file_path}: {e}")
            return 0
    
    def _count_jsonl_records(self, file_path: Path) -> int:
        """计算JSONL文件的记录数量"""
        count = 0
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:  # 跳过空行
                    count += 1
        return count
    
    def _count_json_records(self, file_path: Path) -> int:
        """计算JSON文件的记录数量"""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            if isinstance(data, list):
                return len(data)
            elif isinstance(data, dict):
                return 1
            else:
                return 0
    
    def _count_csv_records(self, file_path: Path) -> int:
        """计算CSV文件的记录数量"""
        count = 0
        with open(file_path, 'r', encoding='utf-8') as f:
            # 跳过标题行
            next(f, None)
            for line in f:
                if line.strip():
                    count += 1
        return count
    
    def read_shard_data(self, 
                       shard_id: str, 
                       batch_size: int = 1000) -> Iterator[List[Dict[str, Any]]]:
        """读取指定分片的数据
        
        Args:
            shard_id: 分片ID
            batch_size: 批次大小，这是经验值，可根据内存情况调整
            
        Yields:
            数据记录批次
            
        Raises:
            DataAccessException: 读取数据失败
        """
        if shard_id not in self._shard_index:
            raise DataAccessException(f"分片不存在: {shard_id}",
                                    data_source="shard_files",
                                    operation="read_shard_data")
        
        file_path = self._shard_index[shard_id]
        
        try:
            if file_path.suffix == '.jsonl':
                yield from self._read_jsonl_batches(file_path, batch_size)
            elif file_path.suffix == '.json':
                yield from self._read_json_batches(file_path, batch_size)
            elif file_path.suffix == '.csv':
                yield from self._read_csv_batches(file_path, batch_size)
            else:
                raise DataAccessException(f"不支持的文件格式: {file_path.suffix}",
                                        data_source="shard_files",
                                        operation="read_shard_data")
        
        except Exception as e:
            raise DataAccessException(f"读取分片数据失败 {shard_id}: {e}",
                                    data_source="shard_files",
                                    operation="read_shard_data")
    
    def _read_jsonl_batches(self, 
                           file_path: Path, 
                           batch_size: int) -> Iterator[List[Dict[str, Any]]]:
        """批量读取JSONL文件"""
        batch = []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    record = json.loads(line)
                    batch.append(record)
                    
                    if len(batch) >= batch_size:
                        yield batch
                        batch = []
                
                except json.JSONDecodeError as e:
                    self.logger.warning(f"解析JSON行失败: {e}")
                    continue
        
        # 返回最后一批数据
        if batch:
            yield batch
    
    def _read_json_batches(self, 
                          file_path: Path, 
                          batch_size: int) -> Iterator[List[Dict[str, Any]]]:
        """批量读取JSON文件"""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if isinstance(data, list):
            # 分批返回列表数据
            for i in range(0, len(data), batch_size):
                yield data[i:i + batch_size]
        elif isinstance(data, dict):
            # 单个对象作为一批返回
            yield [data]
    
    def _read_csv_batches(self, 
                         file_path: Path, 
                         batch_size: int) -> Iterator[List[Dict[str, Any]]]:
        """批量读取CSV文件"""
        import csv
        
        batch = []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                batch.append(dict(row))
                
                if len(batch) >= batch_size:
                    yield batch
                    batch = []
        
        # 返回最后一批数据
        if batch:
            yield batch
    
    def get_paper_ids_from_shard(self, shard_id: str) -> Set[str]:
        """从分片中提取paper_id集合
        
        Args:
            shard_id: 分片ID
            
        Returns:
            paper_id集合
            
        Raises:
            DataAccessException: 提取失败
        """
        try:
            paper_ids = set()
            
            for batch in self.read_shard_data(shard_id, batch_size=1000):
                for record in batch:
                    if 'paper_id' in record:
                        paper_ids.add(str(record['paper_id']))
            
            return paper_ids
        
        except Exception as e:
            raise DataAccessException(f"从分片提取paper_id失败 {shard_id}: {e}",
                                    data_source="shard_files",
                                    operation="get_paper_ids")
    
    def validate_consistency(self) -> List[str]:
        """验证分片文件一致性
        
        Returns:
            发现的问题列表
        """
        issues = []
        
        try:
            for shard_id, file_path in self._shard_index.items():
                # 检查文件是否存在
                if not file_path.exists():
                    issues.append(f"分片文件不存在: {shard_id}")
                    continue
                
                # 检查文件是否可读
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        f.read(1)  # 尝试读取一个字符
                except Exception as e:
                    issues.append(f"分片文件无法读取 {shard_id}: {e}")
                    continue
                
                # 检查文件格式
                try:
                    record_count = 0
                    for batch in self.read_shard_data(shard_id, batch_size=100):
                        record_count += len(batch)
                        if record_count >= 100:  # 只检查前100条记录
                            break
                except Exception as e:
                    issues.append(f"分片文件格式错误 {shard_id}: {e}")
                
                # 检查文件大小异常
                file_size_mb = file_path.stat().st_size / (1024 * 1024)
                if file_size_mb > 1000:  # 这是经验值，超过1GB的文件可能异常
                    issues.append(f"分片文件过大 {shard_id}: {file_size_mb:.2f}MB")
                elif file_size_mb == 0:
                    issues.append(f"分片文件为空 {shard_id}")
        
        except Exception as e:
            issues.append(f"分片文件一致性检查异常: {e}")
        
        return issues
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取分片文件统计信息
        
        Returns:
            统计信息字典
        """
        stats = {
            'total_shards': len(self._shard_index),
            'total_records': 0,
            'total_size_mb': 0.0,
            'file_formats': {},
            'largest_shard': {'id': '', 'size_mb': 0.0},
            'smallest_shard': {'id': '', 'size_mb': float('inf')}
        }
        
        try:
            for shard_id, file_path in self._shard_index.items():
                # 文件大小
                file_size_mb = file_path.stat().st_size / (1024 * 1024)
                stats['total_size_mb'] += file_size_mb
                
                # 记录最大和最小分片
                if file_size_mb > stats['largest_shard']['size_mb']:
                    stats['largest_shard'] = {'id': shard_id, 'size_mb': file_size_mb}
                
                if file_size_mb < stats['smallest_shard']['size_mb']:
                    stats['smallest_shard'] = {'id': shard_id, 'size_mb': file_size_mb}
                
                # 文件格式统计
                file_format = file_path.suffix
                stats['file_formats'][file_format] = stats['file_formats'].get(file_format, 0) + 1
                
                # 记录数量（从缓存获取）
                if shard_id in self._metadata_cache:
                    stats['total_records'] += self._metadata_cache[shard_id].record_count
        
        except Exception as e:
            self.logger.error(f"获取分片文件统计信息失败: {e}")
            stats['error'] = str(e)
        
        return stats
    
    def refresh_index(self) -> None:
        """刷新分片文件索引"""
        try:
            self._shard_index.clear()
            self._metadata_cache.clear()
            self._scan_shard_files()
            
            self.logger.info(f"分片文件索引已刷新，发现 {len(self._shard_index)} 个文件")
        
        except Exception as e:
            self.logger.error(f"刷新分片文件索引失败: {e}")
    
    def close(self) -> None:
        """关闭文件管理器"""
        try:
            # 清理缓存
            self._shard_index.clear()
            self._metadata_cache.clear()
            
            self.logger.info("分片文件管理器已关闭")
        
        except Exception as e:
            self.logger.error(f"关闭分片文件管理器失败: {e}")
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()