"""
异常检测系统的核心数据模型

定义了系统中使用的所有数据结构，包括RPU记录、概念映射、检测结果等。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional
import uuid


class AnomalySeverity(Enum):
    """异常严重性级别"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DetectionStatus(Enum):
    """检测状态"""
    DETECTED = "detected"
    ACKNOWLEDGED = "acknowledged"
    FIXED = "fixed"
    IGNORED = "ignored"


class ProcessingStatus(Enum):
    """处理状态"""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class RPURecord:
    """研究问题单元(RPU)记录
    
    包含从学术论文中提取的Task-Object-Modifier三元组信息。
    """
    paper_id: str
    sentence_id: str
    task: str
    object: str
    modifier: str
    confidence: float
    extraction_method: str
    timestamp: datetime
    shard_id: str
    
    def __post_init__(self):
        """验证数据完整性"""
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"置信度必须在0-1之间，当前值: {self.confidence}")
        
        if not all([self.paper_id, self.sentence_id, self.task, self.object]):
            raise ValueError("paper_id, sentence_id, task, object 不能为空")


@dataclass
class ConceptMapping:
    """概念映射记录
    
    记录概念合并的映射关系和相关元数据。
    """
    source_concept: str
    target_concept: str
    mapping_confidence: float
    mapping_method: str
    creation_timestamp: datetime
    last_updated: datetime
    
    def __post_init__(self):
        """验证映射数据"""
        if not (0.0 <= self.mapping_confidence <= 1.0):
            raise ValueError(f"映射置信度必须在0-1之间，当前值: {self.mapping_confidence}")
        
        if not all([self.source_concept, self.target_concept]):
            raise ValueError("源概念和目标概念不能为空")


@dataclass
class ShardMetadata:
    """分片文件元数据
    
    记录分片文件的基本信息和处理状态。
    """
    shard_id: str
    file_path: str
    file_size: int
    record_count: int
    creation_time: datetime
    last_modified: datetime
    checksum: str
    processing_status: ProcessingStatus = ProcessingStatus.RUNNING
    
    def __post_init__(self):
        """验证元数据"""
        if self.file_size < 0:
            raise ValueError(f"文件大小不能为负数: {self.file_size}")
        
        if self.record_count < 0:
            raise ValueError(f"记录数量不能为负数: {self.record_count}")


@dataclass
class Anomaly:
    """异常基类
    
    所有异常检测结果的基础数据结构。
    """
    anomaly_type: str
    severity: AnomalySeverity
    description: str
    affected_data: Dict[str, Any]
    suggested_fix: str
    timestamp: datetime = field(default_factory=datetime.now)
    anomaly_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    confidence_score: float = 1.0
    
    def __post_init__(self):
        """验证异常数据"""
        if not (0.0 <= self.confidence_score <= 1.0):
            raise ValueError(f"置信度分数必须在0-1之间: {self.confidence_score}")
        
        if not self.anomaly_type:
            raise ValueError("异常类型不能为空")


@dataclass
class DetectionResult:
    """异常检测结果
    
    包含完整的异常检测信息和处理建议。
    """
    anomaly_id: str
    detector_name: str
    anomaly_type: str
    severity: AnomalySeverity
    description: str
    affected_entities: List[str]
    evidence: Dict[str, Any]
    suggested_fixes: List[str]
    confidence_score: float
    detection_timestamp: datetime
    status: DetectionStatus = DetectionStatus.DETECTED
    
    def __post_init__(self):
        """验证检测结果数据"""
        if not (0.0 <= self.confidence_score <= 1.0):
            raise ValueError(f"置信度分数必须在0-1之间: {self.confidence_score}")
        
        if not all([self.anomaly_id, self.detector_name, self.anomaly_type]):
            raise ValueError("异常ID、检测器名称和异常类型不能为空")


@dataclass
class DetectionSession:
    """检测会话
    
    记录一次完整的异常检测过程的信息。
    """
    session_id: str
    config_hash: str
    start_time: datetime
    end_time: Optional[datetime] = None
    total_anomalies: int = 0
    status: ProcessingStatus = ProcessingStatus.RUNNING
    created_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """验证会话数据"""
        if self.total_anomalies < 0:
            raise ValueError(f"异常总数不能为负数: {self.total_anomalies}")


@dataclass
class RepairHistory:
    """修复历史记录
    
    记录异常修复的详细信息和结果。
    """
    anomaly_id: str
    repair_action: str
    repair_timestamp: datetime
    repair_result: str  # success, failed, partial
    repair_details: Dict[str, Any]
    created_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """验证修复历史数据"""
        valid_results = {"success", "failed", "partial"}
        if self.repair_result not in valid_results:
            raise ValueError(f"修复结果必须是 {valid_results} 之一: {self.repair_result}")


@dataclass
class DetectionState:
    """检测状态
    
    记录检测过程的当前状态，用于检查点和恢复。
    """
    session_id: str
    current_shard: int = 0
    total_shards: int = 0
    processed_records: int = 0
    total_records: int = 0
    detected_anomalies: int = 0
    start_time: datetime = field(default_factory=datetime.now)
    last_checkpoint: Optional[datetime] = None
    checkpoint_data: Dict[str, Any] = field(default_factory=dict)
    
    def get_progress_percentage(self) -> float:
        """获取进度百分比"""
        if self.total_records == 0:
            return 0.0
        return (self.processed_records / self.total_records) * 100.0
    
    def get_elapsed_time(self) -> float:
        """获取已用时间（秒）"""
        return (datetime.now() - self.start_time).total_seconds()
    
    def estimate_remaining_time(self) -> Optional[float]:
        """估算剩余时间（秒）"""
        if self.processed_records == 0:
            return None
        
        elapsed = self.get_elapsed_time()
        progress = self.get_progress_percentage() / 100.0
        
        if progress == 0:
            return None
        
        total_estimated = elapsed / progress
        return total_estimated - elapsed


# 特定异常类型的数据模型

@dataclass
class CaseInconsistency(Anomaly):
    """大小写不一致异常"""
    source_variants: List[str] = field(default_factory=list)
    target_conflicts: List[str] = field(default_factory=list)
    
    def __init__(self, severity: AnomalySeverity, description: str, affected_data: Dict[str, Any], 
                 suggested_fix: str, source_variants: List[str] = None, 
                 target_conflicts: List[str] = None, **kwargs):
        """初始化大小写不一致异常"""
        super().__init__(
            anomaly_type="case_inconsistency",
            severity=severity,
            description=description,
            affected_data=affected_data,
            suggested_fix=suggested_fix,
            **kwargs
        )
        self.source_variants = source_variants or []
        self.target_conflicts = target_conflicts or []


@dataclass
class PluralSingularConflict(Anomaly):
    """单复数冲突异常"""
    singular_form: str = ""
    plural_form: str = ""
    conflicting_mappings: List[str] = field(default_factory=list)
    
    def __init__(self, severity: AnomalySeverity, description: str, affected_data: Dict[str, Any], 
                 suggested_fix: str, singular_form: str = "", plural_form: str = "", 
                 conflicting_mappings: List[str] = None, **kwargs):
        """初始化单复数冲突异常"""
        super().__init__(
            anomaly_type="plural_singular_conflict",
            severity=severity,
            description=description,
            affected_data=affected_data,
            suggested_fix=suggested_fix,
            **kwargs
        )
        self.singular_form = singular_form
        self.plural_form = plural_form
        self.conflicting_mappings = conflicting_mappings or []


@dataclass
class NumericalRangeAnomaly(Anomaly):
    """数值范围异常"""
    min_value: float = 0.0
    max_value: float = 0.0
    range_size: float = 0.0
    threshold: float = 0.0
    
    def __init__(self, severity: AnomalySeverity, description: str, affected_data: Dict[str, Any], 
                 suggested_fix: str, min_value: float = 0.0, max_value: float = 0.0, 
                 range_size: float = 0.0, threshold: float = 0.0, **kwargs):
        """初始化数值范围异常"""
        super().__init__(
            anomaly_type="numerical_range_anomaly",
            severity=severity,
            description=description,
            affected_data=affected_data,
            suggested_fix=suggested_fix,
            **kwargs
        )
        self.min_value = min_value
        self.max_value = max_value
        self.range_size = range_size
        self.threshold = threshold
        
        if self.min_value > self.max_value:
            raise ValueError(f"最小值不能大于最大值: {self.min_value} > {self.max_value}")


@dataclass
class CrossDomainMerge(Anomaly):
    """跨领域合并异常"""
    domain_a: str = ""
    domain_b: str = ""
    similarity_score: float = 0.0
    
    def __init__(self, severity: AnomalySeverity, description: str, affected_data: Dict[str, Any], 
                 suggested_fix: str, domain_a: str = "", domain_b: str = "", 
                 similarity_score: float = 0.0, **kwargs):
        """初始化跨领域合并异常"""
        super().__init__(
            anomaly_type="cross_domain_merge",
            severity=severity,
            description=description,
            affected_data=affected_data,
            suggested_fix=suggested_fix,
            **kwargs
        )
        self.domain_a = domain_a
        self.domain_b = domain_b
        self.similarity_score = similarity_score


@dataclass
class SemanticInconsistency(Anomaly):
    """语义不一致异常"""
    rpu_components: Dict[str, str] = field(default_factory=dict)
    inconsistency_type: str = ""
    semantic_score: float = 0.0
    
    def __post_init__(self):
        super().__post_init__()
        self.anomaly_type = "semantic_inconsistency"


@dataclass
class MissingComponent(Anomaly):
    """缺失组件异常"""
    missing_fields: List[str] = field(default_factory=list)
    rpu_id: str = ""
    
    def __post_init__(self):
        super().__post_init__()
        self.anomaly_type = "missing_component"


@dataclass
class FrequencyOutlier(Anomaly):
    """频率离群值异常"""
    concept: str = ""
    frequency: int = 0
    expected_range: tuple = field(default_factory=tuple)
    z_score: float = 0.0
    
    def __post_init__(self):
        super().__post_init__()
        self.anomaly_type = "frequency_outlier"


@dataclass
class PMIAnomaly(Anomaly):
    """PMI计算异常"""
    concept_pair: tuple = field(default_factory=tuple)
    pmi_value: float = 0.0
    expected_range: tuple = field(default_factory=tuple)
    
    def __post_init__(self):
        super().__post_init__()
        self.anomaly_type = "pmi_anomaly"


@dataclass
class EntropyAnomaly(Anomaly):
    """熵值异常"""
    concept: str = ""
    entropy_value: float = 0.0
    expected_range: tuple = field(default_factory=tuple)
    
    def __post_init__(self):
        super().__post_init__()
        self.anomaly_type = "entropy_anomaly"


@dataclass
class MissingDuplicate(Anomaly):
    """遗漏重复异常
    
    表示语义相似但未合并的概念对。
    """
    concept_a: str = ""
    concept_b: str = ""
    similarity_score: float = 0.0
    similarity_type: str = ""  # semantic, synonym, abbreviation, word_order
    threshold: float = 0.0
    
    def __init__(self, severity: AnomalySeverity, description: str, affected_data: Dict[str, Any], 
                 suggested_fix: str, concept_a: str = "", concept_b: str = "", 
                 similarity_score: float = 0.0, similarity_type: str = "", 
                 threshold: float = 0.0, **kwargs):
        """初始化遗漏重复异常"""
        super().__init__(
            anomaly_type="missing_duplicate",
            severity=severity,
            description=description,
            affected_data=affected_data,
            suggested_fix=suggested_fix,
            **kwargs
        )
        self.concept_a = concept_a
        self.concept_b = concept_b
        self.similarity_score = similarity_score
        self.similarity_type = similarity_type
        self.threshold = threshold
        
        if not (0.0 <= self.similarity_score <= 1.0):
            raise ValueError(f"相似度分数必须在0-1之间: {self.similarity_score}")


@dataclass
class SynonymPair(Anomaly):
    """同义词对异常"""
    synonym_a: str = ""
    synonym_b: str = ""
    confidence_score: float = 0.0
    
    def __post_init__(self):
        super().__post_init__()
        self.anomaly_type = "synonym_pair"


@dataclass
class AbbreviationPair(Anomaly):
    """缩写-全称对异常"""
    abbreviation: str = ""
    full_form: str = ""
    confidence_score: float = 0.0
    
    def __post_init__(self):
        super().__post_init__()
        self.anomaly_type = "abbreviation_pair"