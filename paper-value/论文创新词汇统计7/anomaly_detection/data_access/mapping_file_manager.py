"""
概念映射文件管理器

管理概念映射文件的加载、验证和访问，支持JSON格式的映射数据。
"""

import json
from typing import Dict, List, Set, Any, Optional
from datetime import datetime
from pathlib import Path

from ..core.data_models import ConceptMapping
from ..core.exceptions import DataAccessException
from ..core.logging import get_logger


class MappingFileManager:
    """概念映射文件管理器
    
    负责管理概念映射文件的访问和验证。
    """
    
    def __init__(self, mapping_path: str):
        """初始化映射文件管理器
        
        Args:
            mapping_path: 映射文件路径
            
        Raises:
            DataAccessException: 映射文件不存在或无法访问
        """
        self.mapping_path = Path(mapping_path)
        self.logger = get_logger(self.__class__.__name__)
        
        # 验证映射文件
        if not self.mapping_path.exists():
            raise DataAccessException(f"映射文件不存在: {mapping_path}",
                                    data_source="mapping_file",
                                    operation="initialize")
        
        if not self.mapping_path.is_file():
            raise DataAccessException(f"映射路径不是文件: {mapping_path}",
                                    data_source="mapping_file",
                                    operation="initialize")
        
        # 缓存映射数据
        self._mappings_cache: Optional[Dict[str, str]] = None
        self._last_modified: Optional[datetime] = None
        
        try:
            # 验证文件格式
            self._validate_file_format()
            self.logger.info(f"映射文件管理器初始化完成: {mapping_path}")
        
        except Exception as e:
            raise DataAccessException(f"验证映射文件格式失败: {e}",
                                    data_source="mapping_file",
                                    operation="validate_format")
    
    def _validate_file_format(self) -> None:
        """验证映射文件格式
        
        Raises:
            DataAccessException: 文件格式无效
        """
        try:
            with open(self.mapping_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, dict):
                raise DataAccessException("映射文件必须是JSON对象格式",
                                        data_source="mapping_file",
                                        operation="validate_format")
            
            # 检查映射关系的有效性
            invalid_mappings = []
            for source, target in data.items():
                if not isinstance(source, str) or not isinstance(target, str):
                    invalid_mappings.append(f"{source} -> {target}")
                
                if not source.strip() or not target.strip():
                    invalid_mappings.append(f"空字符串映射: '{source}' -> '{target}'")
            
            if invalid_mappings:
                self.logger.warning(f"发现 {len(invalid_mappings)} 个无效映射")
                if len(invalid_mappings) <= 5:  # 只记录前5个
                    for mapping in invalid_mappings:
                        self.logger.warning(f"无效映射: {mapping}")
        
        except json.JSONDecodeError as e:
            raise DataAccessException(f"映射文件JSON格式错误: {e}",
                                    data_source="mapping_file",
                                    operation="validate_format")
    
    def load_mappings(self, force_reload: bool = False) -> Dict[str, str]:
        """加载概念映射数据
        
        Args:
            force_reload: 是否强制重新加载
            
        Returns:
            概念映射字典
            
        Raises:
            DataAccessException: 加载失败
        """
        try:
            # 检查文件是否被修改
            current_modified = datetime.fromtimestamp(self.mapping_path.stat().st_mtime)
            
            if (not force_reload and 
                self._mappings_cache is not None and 
                self._last_modified is not None and
                current_modified <= self._last_modified):
                return self._mappings_cache
            
            # 加载映射数据
            with open(self.mapping_path, 'r', encoding='utf-8') as f:
                mappings = json.load(f)
            
            # 清理和验证映射数据
            cleaned_mappings = self._clean_mappings(mappings)
            
            # 更新缓存
            self._mappings_cache = cleaned_mappings
            self._last_modified = current_modified
            
            self.logger.info(f"加载概念映射完成，共 {len(cleaned_mappings)} 个映射关系")
            
            return cleaned_mappings
        
        except Exception as e:
            raise DataAccessException(f"加载概念映射失败: {e}",
                                    data_source="mapping_file",
                                    operation="load_mappings")
    
    def _clean_mappings(self, raw_mappings: Dict[str, Any]) -> Dict[str, str]:
        """清理和验证映射数据
        
        Args:
            raw_mappings: 原始映射数据
            
        Returns:
            清理后的映射数据
        """
        cleaned = {}
        skipped_count = 0
        
        for source, target in raw_mappings.items():
            # 转换为字符串并去除空白
            source_str = str(source).strip()
            target_str = str(target).strip()
            
            # 跳过空字符串
            if not source_str or not target_str:
                skipped_count += 1
                continue
            
            # 跳过自映射
            if source_str == target_str:
                skipped_count += 1
                continue
            
            cleaned[source_str] = target_str
        
        if skipped_count > 0:
            self.logger.info(f"跳过 {skipped_count} 个无效映射关系")
        
        return cleaned
    
    def get_mapping_statistics(self) -> Dict[str, Any]:
        """获取映射统计信息
        
        Returns:
            映射统计信息
        """
        try:
            mappings = self.load_mappings()
            
            stats = {
                'total_mappings': len(mappings),
                'unique_sources': len(set(mappings.keys())),
                'unique_targets': len(set(mappings.values())),
                'file_size_mb': self.mapping_path.stat().st_size / (1024 * 1024),
                'last_modified': self._last_modified.isoformat() if self._last_modified else None
            }
            
            # 分析映射模式
            stats.update(self._analyze_mapping_patterns(mappings))
            
            return stats
        
        except Exception as e:
            self.logger.error(f"获取映射统计信息失败: {e}")
            return {'error': str(e)}
    
    def _analyze_mapping_patterns(self, mappings: Dict[str, str]) -> Dict[str, Any]:
        """分析映射模式
        
        Args:
            mappings: 映射数据
            
        Returns:
            模式分析结果
        """
        patterns = {
            'case_variations': 0,
            'plural_singular': 0,
            'numerical_ranges': 0,
            'abbreviations': 0,
            'multi_target_sources': 0
        }
        
        # 统计目标概念的出现频率
        target_counts = {}
        for target in mappings.values():
            target_counts[target] = target_counts.get(target, 0) + 1
        
        # 多对一映射统计
        patterns['multi_target_sources'] = sum(1 for count in target_counts.values() if count > 1)
        
        # 分析具体模式
        for source, target in mappings.items():
            # 大小写变化
            if source.lower() == target.lower() and source != target:
                patterns['case_variations'] += 1
            
            # 单复数变化（简单检测）
            elif (source.endswith('s') and source[:-1] == target) or \
                 (target.endswith('s') and target[:-1] == source):
                patterns['plural_singular'] += 1
            
            # 数值范围（包含数字和连字符）
            elif any(char.isdigit() for char in source) and '-' in source:
                patterns['numerical_ranges'] += 1
            
            # 缩写（长度差异较大）
            elif abs(len(source) - len(target)) > 3:
                patterns['abbreviations'] += 1
        
        return patterns
    
    def get_reverse_mappings(self) -> Dict[str, List[str]]:
        """获取反向映射（目标概念到源概念列表）
        
        Returns:
            反向映射字典
        """
        try:
            mappings = self.load_mappings()
            reverse_mappings = {}
            
            for source, target in mappings.items():
                if target not in reverse_mappings:
                    reverse_mappings[target] = []
                reverse_mappings[target].append(source)
            
            return reverse_mappings
        
        except Exception as e:
            self.logger.error(f"获取反向映射失败: {e}")
            return {}
    
    def find_mapping_conflicts(self) -> List[Dict[str, Any]]:
        """查找映射冲突
        
        Returns:
            冲突列表
        """
        conflicts = []
        
        try:
            mappings = self.load_mappings()
            reverse_mappings = self.get_reverse_mappings()
            
            # 查找一对多映射冲突
            for target, sources in reverse_mappings.items():
                if len(sources) > 1:
                    # 检查是否为合理的合并
                    conflict_severity = self._assess_conflict_severity(sources, target)
                    
                    conflicts.append({
                        'type': 'one_to_many',
                        'target': target,
                        'sources': sources,
                        'severity': conflict_severity,
                        'count': len(sources)
                    })
            
            # 查找循环映射
            cycles = self._find_mapping_cycles(mappings)
            for cycle in cycles:
                conflicts.append({
                    'type': 'cycle',
                    'concepts': cycle,
                    'severity': 'high',
                    'count': len(cycle)
                })
        
        except Exception as e:
            self.logger.error(f"查找映射冲突失败: {e}")
            conflicts.append({
                'type': 'error',
                'message': str(e),
                'severity': 'critical'
            })
        
        return conflicts
    
    def _assess_conflict_severity(self, sources: List[str], target: str) -> str:
        """评估冲突严重性
        
        Args:
            sources: 源概念列表
            target: 目标概念
            
        Returns:
            严重性级别
        """
        # 如果只是大小写差异，严重性较低
        if all(s.lower() == target.lower() for s in sources):
            return 'low'
        
        # 如果包含数值范围，可能严重性较高
        if any(any(c.isdigit() for c in s) for s in sources):
            return 'high'
        
        # 如果源概念数量很多，严重性较高
        # 经验值：超过10个源概念认为是高严重性，建议基于实际数据分布确定
        if len(sources) > 10:  
            return 'high'
        
        return 'medium'
    
    def _find_mapping_cycles(self, mappings: Dict[str, str]) -> List[List[str]]:
        """查找映射中的循环
        
        Args:
            mappings: 映射数据
            
        Returns:
            循环列表
        """
        cycles = []
        visited = set()
        
        def dfs(concept: str, path: List[str]) -> None:
            if concept in path:
                # 找到循环
                cycle_start = path.index(concept)
                cycle = path[cycle_start:] + [concept]
                cycles.append(cycle)
                return
            
            if concept in visited or concept not in mappings:
                return
            
            visited.add(concept)
            path.append(concept)
            dfs(mappings[concept], path)
            path.pop()
        
        for source in mappings:
            if source not in visited:
                dfs(source, [])
        
        return cycles
    
    def validate_consistency(self) -> List[str]:
        """验证映射文件一致性
        
        Returns:
            发现的问题列表
        """
        issues = []
        
        try:
            # 检查文件可读性
            mappings = self.load_mappings()
            
            # 检查映射冲突
            conflicts = self.find_mapping_conflicts()
            high_severity_conflicts = [c for c in conflicts if c.get('severity') == 'high']
            
            if high_severity_conflicts:
                issues.append(f"发现 {len(high_severity_conflicts)} 个高严重性映射冲突")
            
            # 检查空映射
            empty_mappings = sum(1 for s, t in mappings.items() if not s.strip() or not t.strip())
            if empty_mappings > 0:
                issues.append(f"发现 {empty_mappings} 个空映射")
            
            # 检查自映射
            self_mappings = sum(1 for s, t in mappings.items() if s == t)
            if self_mappings > 0:
                issues.append(f"发现 {self_mappings} 个自映射")
            
            # 检查文件大小异常
            file_size_mb = self.mapping_path.stat().st_size / (1024 * 1024)
            # 经验值：超过100MB可能异常，建议根据实际系统资源和处理能力调整
            if file_size_mb > 100:  
                issues.append(f"映射文件过大: {file_size_mb:.2f}MB")
        
        except Exception as e:
            issues.append(f"映射文件一致性检查异常: {e}")
        
        return issues
    
    def save_mappings(self, mappings: Dict[str, str], backup: bool = True) -> None:
        """保存映射数据到文件
        
        Args:
            mappings: 映射数据
            backup: 是否创建备份
            
        Raises:
            DataAccessException: 保存失败
        """
        try:
            # 创建备份
            if backup and self.mapping_path.exists():
                backup_path = self.mapping_path.with_suffix(f'.bak.{int(datetime.now().timestamp())}')
                backup_path.write_bytes(self.mapping_path.read_bytes())
                self.logger.info(f"创建映射文件备份: {backup_path}")
            
            # 保存新映射
            with open(self.mapping_path, 'w', encoding='utf-8') as f:
                json.dump(mappings, f, indent=2, ensure_ascii=False, sort_keys=True)
            
            # 清除缓存
            self._mappings_cache = None
            self._last_modified = None
            
            self.logger.info(f"映射文件保存成功，共 {len(mappings)} 个映射关系")
        
        except Exception as e:
            raise DataAccessException(f"保存映射文件失败: {e}",
                                    data_source="mapping_file",
                                    operation="save_mappings")
    
    def close(self) -> None:
        """关闭映射文件管理器"""
        try:
            # 清理缓存
            self._mappings_cache = None
            self._last_modified = None
            
            self.logger.info("映射文件管理器已关闭")
        
        except Exception as e:
            self.logger.error(f"关闭映射文件管理器失败: {e}")
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()