"""
跨文件一致性检测器

检测多个文件间的数据一致性问题，包括ID引用一致性、重叠数据处理、元数据异常等。
"""

import hashlib
import sqlite3
from typing import Dict, List, Set, Tuple, Any, Optional
from collections import defaultdict, Counter
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field

from ..core.data_models import (
    Anomaly, AnomalySeverity, DetectionResult, ShardMetadata, RPURecord
)
from ..core.exceptions import DetectionLogicException, DataAccessException
from ..core.logging import get_logger
from ..data_access.manager import DataAccessManager


@dataclass
class ConsistencyAnomaly(Anomaly):
    """一致性异常基类"""
    files_involved: List[str] = field(default_factory=list)
    consistency_type: str = ""
    
    def __init__(self, severity: AnomalySeverity, description: str, affected_data: Dict[str, Any], 
                 suggested_fix: str, files_involved: List[str] = None, 
                 consistency_type: str = "", **kwargs):
        """初始化一致性异常"""
        super().__init__(
            anomaly_type="consistency_anomaly",
            severity=severity,
            description=description,
            affected_data=affected_data,
            suggested_fix=suggested_fix,
            **kwargs
        )
        self.files_involved = files_involved or []
        self.consistency_type = consistency_type


@dataclass
class IDReferenceAnomaly(ConsistencyAnomaly):
    """ID引用一致性异常"""
    missing_ids: List[str] = field(default_factory=list)
    orphaned_references: List[str] = field(default_factory=list)
    
    def __init__(self, severity: AnomalySeverity, description: str, affected_data: Dict[str, Any], 
                 suggested_fix: str, missing_ids: List[str] = None, 
                 orphaned_references: List[str] = None, **kwargs):
        """初始化ID引用异常"""
        super().__init__(
            consistency_type="id_reference",
            severity=severity,
            description=description,
            affected_data=affected_data,
            suggested_fix=suggested_fix,
            **kwargs
        )
        self.missing_ids = missing_ids or []
        self.orphaned_references = orphaned_references or []


@dataclass
class OverlapDataAnomaly(ConsistencyAnomaly):
    """重叠数据异常"""
    overlap_type: str = ""  # duplicate, conflict, missing
    overlap_details: Dict[str, Any] = field(default_factory=dict)
    
    def __init__(self, severity: AnomalySeverity, description: str, affected_data: Dict[str, Any], 
                 suggested_fix: str, overlap_type: str = "", 
                 overlap_details: Dict[str, Any] = None, **kwargs):
        """初始化重叠数据异常"""
        super().__init__(
            consistency_type="overlap_data",
            severity=severity,
            description=description,
            affected_data=affected_data,
            suggested_fix=suggested_fix,
            **kwargs
        )
        self.overlap_type = overlap_type
        self.overlap_details = overlap_details or {}


@dataclass
class MetadataAnomaly(ConsistencyAnomaly):
    """元数据异常"""
    metadata_field: str = ""
    expected_value: Any = None
    actual_value: Any = None
    
    def __init__(self, severity: AnomalySeverity, description: str, affected_data: Dict[str, Any], 
                 suggested_fix: str, metadata_field: str = "", 
                 expected_value: Any = None, actual_value: Any = None, **kwargs):
        """初始化元数据异常"""
        super().__init__(
            consistency_type="metadata",
            severity=severity,
            description=description,
            affected_data=affected_data,
            suggested_fix=suggested_fix,
            **kwargs
        )
        self.metadata_field = metadata_field
        self.expected_value = expected_value
        self.actual_value = actual_value


class ConsistencyDetector:
    """跨文件一致性检测器
    
    检测多个文件间的数据一致性问题。
    """
    
    def __init__(self, config, data_manager: DataAccessManager):
        """初始化一致性检测器
        
        Args:
            config: 检测配置
            data_manager: 数据访问管理器
        """
        self.config = config
        self.data_manager = data_manager
        self.logger = get_logger(self.__class__.__name__)
        
        # 检测阈值配置 - 从配置对象中读取，避免硬编码经验值
        self.max_duplicate_ratio = getattr(config.thresholds, 'max_duplicate_ratio', 0.05)  # 经验值：5%重复率阈值
        self.metadata_tolerance = getattr(config.thresholds, 'metadata_tolerance', 0.1)  # 经验值：10%元数据差异容忍度
        
    def detect_id_reference_consistency(self) -> List[IDReferenceAnomaly]:
        """检测ID引用一致性
        
        Returns:
            检测到的ID引用异常列表
        """
        anomalies = []
        
        try:
            # 获取所有分片的元数据
            shard_metadata = self.data_manager.get_shard_metadata()
            
            # 收集所有paper_id和sentence_id
            all_paper_ids = set()
            all_sentence_ids = set()
            shard_paper_ids = defaultdict(set)
            shard_sentence_ids = defaultdict(set)
            
            for shard in shard_metadata:
                # 从每个分片读取ID信息
                try:
                    rpu_data = list(self.data_manager.get_rpu_data_by_shard(shard.shard_id))
                    
                    paper_ids = {rpu.paper_id for rpu in rpu_data}
                    sentence_ids = {rpu.sentence_id for rpu in rpu_data}
                    
                    all_paper_ids.update(paper_ids)
                    all_sentence_ids.update(sentence_ids)
                    shard_paper_ids[shard.shard_id] = paper_ids
                    shard_sentence_ids[shard.shard_id] = sentence_ids
                    
                except Exception as e:
                    self.logger.warning(f"读取分片 {shard.shard_id} 数据时出错: {str(e)}")
                    continue
            
            # 检查概念映射文件中的ID引用
            mapping_data = self.data_manager.get_mapping_data()
            
            # 从映射数据中提取可能的ID引用
            referenced_ids = self._extract_ids_from_mapping(mapping_data)
            
            # 检查缺失的ID引用
            missing_paper_ids = referenced_ids['paper_ids'] - all_paper_ids
            missing_sentence_ids = referenced_ids['sentence_ids'] - all_sentence_ids
            
            if missing_paper_ids:
                anomaly = IDReferenceAnomaly(
                    severity=AnomalySeverity.HIGH,
                    description=f"映射文件中引用了 {len(missing_paper_ids)} 个不存在的paper_id",
                    affected_data={
                        "missing_paper_ids": list(missing_paper_ids)[:10],  # 只显示前10个
                        "total_missing": len(missing_paper_ids)
                    },
                    suggested_fix="检查映射文件的ID引用是否正确，或补充缺失的数据",
                    missing_ids=list(missing_paper_ids),
                    files_involved=["mapping_file", "rpu_database"]
                )
                anomalies.append(anomaly)
            
            if missing_sentence_ids:
                anomaly = IDReferenceAnomaly(
                    severity=AnomalySeverity.MEDIUM,
                    description=f"映射文件中引用了 {len(missing_sentence_ids)} 个不存在的sentence_id",
                    affected_data={
                        "missing_sentence_ids": list(missing_sentence_ids)[:10],
                        "total_missing": len(missing_sentence_ids)
                    },
                    suggested_fix="检查映射文件的sentence_id引用是否正确",
                    missing_ids=list(missing_sentence_ids),
                    files_involved=["mapping_file", "rpu_database"]
                )
                anomalies.append(anomaly)
            
            # 检查分片间的ID重叠情况
            overlap_anomalies = self._check_id_overlaps(shard_paper_ids, shard_sentence_ids)
            anomalies.extend(overlap_anomalies)
            
        except Exception as e:
            self.logger.error(f"检测ID引用一致性时发生错误: {str(e)}")
            raise DetectionLogicException(f"ID引用一致性检测失败: {str(e)}")
        
        return anomalies
    
    def detect_overlap_data_consistency(self) -> List[OverlapDataAnomaly]:
        """检测重叠数据处理一致性
        
        Returns:
            检测到的重叠数据异常列表
        """
        anomalies = []
        
        try:
            # 获取所有分片的数据
            shard_metadata = self.data_manager.get_shard_metadata()
            
            # 按paper_id分组检查重叠
            paper_rpu_map = defaultdict(list)
            
            for shard in shard_metadata:
                try:
                    rpu_data = list(self.data_manager.get_rpu_data_by_shard(shard.shard_id))
                    
                    for rpu in rpu_data:
                        paper_rpu_map[rpu.paper_id].append({
                            'rpu': rpu,
                            'shard_id': shard.shard_id
                        })
                        
                except Exception as e:
                    self.logger.warning(f"读取分片 {shard.shard_id} 数据时出错: {str(e)}")
                    continue
            
            # 检查每个paper的RPU是否在多个分片中重复
            for paper_id, rpu_list in paper_rpu_map.items():
                if len(rpu_list) <= 1:
                    continue
                
                # 按分片分组
                shard_groups = defaultdict(list)
                for item in rpu_list:
                    shard_groups[item['shard_id']].append(item['rpu'])
                
                if len(shard_groups) > 1:
                    # 检查是否为重复数据
                    duplicate_rpus = self._find_duplicate_rpus(shard_groups)
                    
                    if duplicate_rpus:
                        anomaly = OverlapDataAnomaly(
                            severity=AnomalySeverity.MEDIUM,
                            description=f"论文 {paper_id} 的RPU在多个分片中重复",
                            affected_data={
                                "paper_id": paper_id,
                                "involved_shards": list(shard_groups.keys()),
                                "duplicate_count": len(duplicate_rpus),
                                "duplicates": duplicate_rpus[:5]  # 只显示前5个
                            },
                            suggested_fix="检查数据分片逻辑，确保同一论文的数据不会重复处理",
                            overlap_type="duplicate",
                            overlap_details={"duplicates": duplicate_rpus},
                            files_involved=list(shard_groups.keys())
                        )
                        anomalies.append(anomaly)
                    
                    # 检查是否存在冲突的RPU（相同位置但内容不同）
                    conflicting_rpus = self._find_conflicting_rpus(shard_groups)
                    
                    if conflicting_rpus:
                        anomaly = OverlapDataAnomaly(
                            severity=AnomalySeverity.HIGH,
                            description=f"论文 {paper_id} 的RPU在不同分片中存在冲突",
                            affected_data={
                                "paper_id": paper_id,
                                "involved_shards": list(shard_groups.keys()),
                                "conflict_count": len(conflicting_rpus),
                                "conflicts": conflicting_rpus[:3]  # 只显示前3个
                            },
                            suggested_fix="检查数据处理逻辑，解决RPU提取的不一致性",
                            overlap_type="conflict",
                            overlap_details={"conflicts": conflicting_rpus},
                            files_involved=list(shard_groups.keys())
                        )
                        anomalies.append(anomaly)
            
            # 检查整体重复率
            total_rpus = sum(len(rpu_list) for rpu_list in paper_rpu_map.values())
            unique_rpus = len(paper_rpu_map)
            
            if total_rpus > 0:
                duplicate_ratio = 1 - (unique_rpus / total_rpus)
                
                if duplicate_ratio > self.max_duplicate_ratio:
                    anomaly = OverlapDataAnomaly(
                        severity=AnomalySeverity.MEDIUM,
                        description=f"整体数据重复率过高: {duplicate_ratio:.2%}",
                        affected_data={
                            "total_rpus": total_rpus,
                            "unique_papers": unique_rpus,
                            "duplicate_ratio": duplicate_ratio,
                            "threshold": self.max_duplicate_ratio
                        },
                        suggested_fix="优化数据分片策略，减少重复处理",
                        overlap_type="high_duplicate_ratio",
                        files_involved=[shard.shard_id for shard in shard_metadata]
                    )
                    anomalies.append(anomaly)
                    
        except Exception as e:
            self.logger.error(f"检测重叠数据一致性时发生错误: {str(e)}")
            raise DetectionLogicException(f"重叠数据一致性检测失败: {str(e)}")
        
        return anomalies
    
    def detect_metadata_consistency(self) -> List[MetadataAnomaly]:
        """检测元数据一致性
        
        Returns:
            检测到的元数据异常列表
        """
        anomalies = []
        
        try:
            # 获取所有分片的元数据
            shard_metadata = self.data_manager.get_shard_metadata()
            
            if not shard_metadata:
                return anomalies
            
            # 检查文件大小的一致性
            file_sizes = [shard.file_size for shard in shard_metadata]
            size_anomalies = self._check_size_consistency(file_sizes, shard_metadata)
            anomalies.extend(size_anomalies)
            
            # 检查记录数量的一致性
            record_counts = [shard.record_count for shard in shard_metadata]
            count_anomalies = self._check_count_consistency(record_counts, shard_metadata)
            anomalies.extend(count_anomalies)
            
            # 检查文件完整性（通过校验和）
            integrity_anomalies = self._check_file_integrity(shard_metadata)
            anomalies.extend(integrity_anomalies)
            
            # 检查时间戳的合理性
            timestamp_anomalies = self._check_timestamp_consistency(shard_metadata)
            anomalies.extend(timestamp_anomalies)
            
        except Exception as e:
            self.logger.error(f"检测元数据一致性时发生错误: {str(e)}")
            raise DetectionLogicException(f"元数据一致性检测失败: {str(e)}")
        
        return anomalies
    
    def _extract_ids_from_mapping(self, mapping_data: Dict[str, str]) -> Dict[str, Set[str]]:
        """从映射数据中提取ID引用"""
        paper_ids = set()
        sentence_ids = set()
        
        # 这里假设映射数据的键或值中可能包含ID信息
        # 实际实现需要根据具体的映射文件格式调整
        id_patterns = {
            'paper_id': r'paper_(\w+)',
            'sentence_id': r'sent_(\w+)'
        }
        
        for source, target in mapping_data.items():
            for text in [source, target]:
                # 尝试从文本中提取paper_id
                import re
                paper_matches = re.findall(id_patterns['paper_id'], text)
                paper_ids.update(paper_matches)
                
                # 尝试从文本中提取sentence_id
                sentence_matches = re.findall(id_patterns['sentence_id'], text)
                sentence_ids.update(sentence_matches)
        
        return {
            'paper_ids': paper_ids,
            'sentence_ids': sentence_ids
        }
    
    def _check_id_overlaps(self, shard_paper_ids: Dict[str, Set[str]], 
                          shard_sentence_ids: Dict[str, Set[str]]) -> List[IDReferenceAnomaly]:
        """检查分片间的ID重叠"""
        anomalies = []
        
        # 检查paper_id重叠
        shard_list = list(shard_paper_ids.keys())
        for i in range(len(shard_list)):
            for j in range(i + 1, len(shard_list)):
                shard_a, shard_b = shard_list[i], shard_list[j]
                
                overlap_papers = shard_paper_ids[shard_a] & shard_paper_ids[shard_b]
                if overlap_papers:
                    anomaly = IDReferenceAnomaly(
                        severity=AnomalySeverity.MEDIUM,
                        description=f"分片 {shard_a} 和 {shard_b} 存在 {len(overlap_papers)} 个重叠的paper_id",
                        affected_data={
                            "shard_a": shard_a,
                            "shard_b": shard_b,
                            "overlap_count": len(overlap_papers),
                            "overlap_ids": list(overlap_papers)[:10]
                        },
                        suggested_fix="检查数据分片逻辑，确保paper_id不会重复分配",
                        orphaned_references=list(overlap_papers),
                        files_involved=[shard_a, shard_b]
                    )
                    anomalies.append(anomaly)
        
        return anomalies
    
    def _find_duplicate_rpus(self, shard_groups: Dict[str, List[RPURecord]]) -> List[Dict[str, Any]]:
        """查找重复的RPU"""
        duplicates = []
        
        # 创建RPU的唯一标识符
        rpu_signatures = defaultdict(list)
        
        for shard_id, rpus in shard_groups.items():
            for rpu in rpus:
                # 使用task, object, modifier组合作为签名
                signature = f"{rpu.task}|{rpu.object}|{rpu.modifier}"
                rpu_signatures[signature].append({
                    'shard_id': shard_id,
                    'rpu': rpu
                })
        
        # 找出出现在多个分片中的相同RPU
        for signature, rpu_list in rpu_signatures.items():
            if len(rpu_list) > 1:
                shards_involved = {item['shard_id'] for item in rpu_list}
                if len(shards_involved) > 1:
                    duplicates.append({
                        'signature': signature,
                        'shards': list(shards_involved),
                        'count': len(rpu_list)
                    })
        
        return duplicates
    
    def _find_conflicting_rpus(self, shard_groups: Dict[str, List[RPURecord]]) -> List[Dict[str, Any]]:
        """查找冲突的RPU（相同位置但内容不同）"""
        conflicts = []
        
        # 按sentence_id分组
        sentence_groups = defaultdict(lambda: defaultdict(list))
        
        for shard_id, rpus in shard_groups.items():
            for rpu in rpus:
                sentence_groups[rpu.sentence_id][shard_id].append(rpu)
        
        # 检查同一sentence_id在不同分片中的RPU是否一致
        for sentence_id, shard_rpus in sentence_groups.items():
            if len(shard_rpus) > 1:
                # 比较不同分片中的RPU
                shard_list = list(shard_rpus.keys())
                for i in range(len(shard_list)):
                    for j in range(i + 1, len(shard_list)):
                        shard_a, shard_b = shard_list[i], shard_list[j]
                        
                        rpus_a = shard_rpus[shard_a]
                        rpus_b = shard_rpus[shard_b]
                        
                        # 检查是否存在不一致
                        if not self._are_rpu_lists_consistent(rpus_a, rpus_b):
                            conflicts.append({
                                'sentence_id': sentence_id,
                                'shard_a': shard_a,
                                'shard_b': shard_b,
                                'rpus_a': [self._rpu_to_dict(rpu) for rpu in rpus_a],
                                'rpus_b': [self._rpu_to_dict(rpu) for rpu in rpus_b]
                            })
        
        return conflicts
    
    def _are_rpu_lists_consistent(self, rpus_a: List[RPURecord], rpus_b: List[RPURecord]) -> bool:
        """检查两个RPU列表是否一致"""
        if len(rpus_a) != len(rpus_b):
            return False
        
        # 创建RPU签名进行比较
        signatures_a = {f"{rpu.task}|{rpu.object}|{rpu.modifier}" for rpu in rpus_a}
        signatures_b = {f"{rpu.task}|{rpu.object}|{rpu.modifier}" for rpu in rpus_b}
        
        return signatures_a == signatures_b
    
    def _rpu_to_dict(self, rpu: RPURecord) -> Dict[str, Any]:
        """将RPU转换为字典格式"""
        return {
            'task': rpu.task,
            'object': rpu.object,
            'modifier': rpu.modifier,
            'confidence': rpu.confidence,
            'extraction_method': rpu.extraction_method
        }
    
    def _check_size_consistency(self, file_sizes: List[int], 
                               shard_metadata: List[ShardMetadata]) -> List[MetadataAnomaly]:
        """检查文件大小一致性"""
        anomalies = []
        
        if not file_sizes:
            return anomalies
        
        # 计算统计信息
        avg_size = sum(file_sizes) / len(file_sizes)
        max_size = max(file_sizes)
        min_size = min(file_sizes)
        
        # 检查是否有异常大或异常小的文件
        size_threshold = avg_size * self.metadata_tolerance  # 经验值：平均值的10%作为容忍度
        
        for shard in shard_metadata:
            if abs(shard.file_size - avg_size) > size_threshold:
                severity = AnomalySeverity.HIGH if abs(shard.file_size - avg_size) > avg_size * 0.5 else AnomalySeverity.MEDIUM
                
                anomaly = MetadataAnomaly(
                    severity=severity,
                    description=f"分片文件 {shard.shard_id} 大小异常: {shard.file_size} bytes",
                    affected_data={
                        "shard_id": shard.shard_id,
                        "file_size": shard.file_size,
                        "average_size": avg_size,
                        "deviation": abs(shard.file_size - avg_size)
                    },
                    suggested_fix="检查文件是否完整或数据分片是否均匀",
                    metadata_field="file_size",
                    expected_value=avg_size,
                    actual_value=shard.file_size,
                    files_involved=[shard.shard_id]
                )
                anomalies.append(anomaly)
        
        return anomalies
    
    def _check_count_consistency(self, record_counts: List[int], 
                                shard_metadata: List[ShardMetadata]) -> List[MetadataAnomaly]:
        """检查记录数量一致性"""
        anomalies = []
        
        if not record_counts:
            return anomalies
        
        # 计算统计信息
        avg_count = sum(record_counts) / len(record_counts)
        
        # 检查是否有记录数量异常的分片
        count_threshold = avg_count * self.metadata_tolerance
        
        for shard in shard_metadata:
            if abs(shard.record_count - avg_count) > count_threshold:
                severity = AnomalySeverity.MEDIUM if shard.record_count > 0 else AnomalySeverity.HIGH
                
                anomaly = MetadataAnomaly(
                    severity=severity,
                    description=f"分片 {shard.shard_id} 记录数量异常: {shard.record_count}",
                    affected_data={
                        "shard_id": shard.shard_id,
                        "record_count": shard.record_count,
                        "average_count": avg_count,
                        "deviation": abs(shard.record_count - avg_count)
                    },
                    suggested_fix="检查数据处理是否完整或分片策略是否合理",
                    metadata_field="record_count",
                    expected_value=avg_count,
                    actual_value=shard.record_count,
                    files_involved=[shard.shard_id]
                )
                anomalies.append(anomaly)
        
        return anomalies
    
    def _check_file_integrity(self, shard_metadata: List[ShardMetadata]) -> List[MetadataAnomaly]:
        """检查文件完整性"""
        anomalies = []
        
        for shard in shard_metadata:
            try:
                # 重新计算文件校验和
                file_path = Path(shard.file_path)
                if not file_path.exists():
                    anomaly = MetadataAnomaly(
                        severity=AnomalySeverity.CRITICAL,
                        description=f"分片文件不存在: {shard.file_path}",
                        affected_data={
                            "shard_id": shard.shard_id,
                            "file_path": shard.file_path
                        },
                        suggested_fix="检查文件路径或恢复缺失的文件",
                        metadata_field="file_existence",
                        expected_value=True,
                        actual_value=False,
                        files_involved=[shard.shard_id]
                    )
                    anomalies.append(anomaly)
                    continue
                
                # 计算当前校验和
                current_checksum = self._calculate_file_checksum(file_path)
                
                if current_checksum != shard.checksum:
                    anomaly = MetadataAnomaly(
                        severity=AnomalySeverity.HIGH,
                        description=f"分片文件 {shard.shard_id} 校验和不匹配",
                        affected_data={
                            "shard_id": shard.shard_id,
                            "expected_checksum": shard.checksum,
                            "actual_checksum": current_checksum
                        },
                        suggested_fix="检查文件是否被修改或损坏，考虑重新生成",
                        metadata_field="checksum",
                        expected_value=shard.checksum,
                        actual_value=current_checksum,
                        files_involved=[shard.shard_id]
                    )
                    anomalies.append(anomaly)
                    
            except Exception as e:
                self.logger.warning(f"检查分片 {shard.shard_id} 完整性时出错: {str(e)}")
        
        return anomalies
    
    def _check_timestamp_consistency(self, shard_metadata: List[ShardMetadata]) -> List[MetadataAnomaly]:
        """检查时间戳一致性"""
        anomalies = []
        
        if len(shard_metadata) < 2:
            return anomalies
        
        # 检查创建时间的合理性
        creation_times = [shard.creation_time for shard in shard_metadata]
        min_time = min(creation_times)
        max_time = max(creation_times)
        
        # 如果时间跨度过大，可能存在问题
        time_span = (max_time - min_time).total_seconds()
        max_reasonable_span = 24 * 3600  # 经验值：24小时内完成处理是合理的
        
        if time_span > max_reasonable_span:
            anomaly = MetadataAnomaly(
                severity=AnomalySeverity.MEDIUM,
                description=f"分片文件创建时间跨度过大: {time_span/3600:.1f} 小时",
                affected_data={
                    "time_span_hours": time_span / 3600,
                    "min_time": min_time.isoformat(),
                    "max_time": max_time.isoformat(),
                    "threshold_hours": max_reasonable_span / 3600
                },
                suggested_fix="检查数据处理流程是否存在异常延迟",
                metadata_field="creation_time_span",
                expected_value=max_reasonable_span,
                actual_value=time_span,
                files_involved=[shard.shard_id for shard in shard_metadata]
            )
            anomalies.append(anomaly)
        
        # 检查修改时间是否晚于创建时间
        for shard in shard_metadata:
            if shard.last_modified < shard.creation_time:
                anomaly = MetadataAnomaly(
                    severity=AnomalySeverity.HIGH,
                    description=f"分片 {shard.shard_id} 修改时间早于创建时间",
                    affected_data={
                        "shard_id": shard.shard_id,
                        "creation_time": shard.creation_time.isoformat(),
                        "last_modified": shard.last_modified.isoformat()
                    },
                    suggested_fix="检查时间戳设置是否正确",
                    metadata_field="timestamp_order",
                    expected_value="last_modified >= creation_time",
                    actual_value="last_modified < creation_time",
                    files_involved=[shard.shard_id]
                )
                anomalies.append(anomaly)
        
        return anomalies
    
    def _calculate_file_checksum(self, file_path: Path) -> str:
        """计算文件的MD5校验和"""
        hash_md5 = hashlib.md5()
        
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        
        return hash_md5.hexdigest()
    
    def get_detector_name(self) -> str:
        """获取检测器名称"""
        return "ConsistencyDetector"
    
    def get_supported_data_types(self) -> List[str]:
        """获取支持的数据类型"""
        return ["multi_file", "metadata", "id_reference", "overlap_data"]