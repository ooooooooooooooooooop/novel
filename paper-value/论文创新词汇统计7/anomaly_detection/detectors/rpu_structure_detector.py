"""
RPU结构异常检测器

实现RPU三元组(Task-Object-Modifier)的完整性和一致性检测，包括：
1. Task-Object-Modifier组合的语义一致性验证
2. 缺失组件和完整性检测 (需求 7.2)
3. 论文内RPU矛盾检测 (需求 7.3)
4. RPU分布异常分析 (需求 7.4)
5. 异常RPU模式识别

验证需求: 7.1, 7.2, 7.3, 7.4 - RPU结构异常检测
"""

import re
import logging
from typing import Union
from typing import List, Dict, Set, Tuple, Optional, Any
from collections import defaultdict, Counter
from dataclasses import dataclass, field
import math

from ..core.data_models import (
    RPURecord, Anomaly, AnomalySeverity, 
    SemanticInconsistency, MissingComponent
)
from ..core.exceptions import DetectionLogicException


@dataclass
class ContradictoryRPU(Anomaly):
    """论文内矛盾RPU异常"""
    paper_id: str = ""
    conflicting_rpus: List[Dict[str, Any]] = field(default_factory=list)
    contradiction_type: str = ""
    semantic_distance: float = 0.0
    
    def __init__(self, severity: AnomalySeverity, description: str, affected_data: Dict[str, Any], 
                 suggested_fix: str, paper_id: str = "", conflicting_rpus: List[Dict[str, Any]] = None,
                 contradiction_type: str = "", semantic_distance: float = 0.0, 
                 confidence_score: float = 1.0, **kwargs):
        """初始化论文内矛盾RPU异常"""
        super().__init__(
            anomaly_type="intra_paper_contradiction",
            severity=severity,
            description=description,
            affected_data=affected_data,
            suggested_fix=suggested_fix,
            confidence_score=confidence_score,
            **kwargs
        )
        self.paper_id = paper_id
        self.conflicting_rpus = conflicting_rpus or []
        self.contradiction_type = contradiction_type
        self.semantic_distance = semantic_distance


@dataclass
class RPUDistributionAnomaly(Anomaly):
    """RPU分布异常"""
    distribution_type: str = ""  # 'component_imbalance', 'temporal_anomaly', 'frequency_outlier'
    statistical_measures: Dict[str, float] = field(default_factory=dict)
    anomaly_score: float = 0.0
    
    def __init__(self, severity: AnomalySeverity, description: str, affected_data: Dict[str, Any], 
                 suggested_fix: str, distribution_type: str = "", 
                 statistical_measures: Dict[str, float] = None, anomaly_score: float = 0.0,
                 confidence_score: float = 1.0, **kwargs):
        """初始化RPU分布异常"""
        # 根据分布类型设置异常类型
        anomaly_type_map = {
            'component_imbalance': 'component_distribution_imbalance',
            'temporal_anomaly': 'temporal_distribution_anomaly', 
            'frequency_outlier': 'frequency_distribution_outlier'
        }
        anomaly_type = anomaly_type_map.get(distribution_type, 'distribution_anomaly')
        
        super().__init__(
            anomaly_type=anomaly_type,
            severity=severity,
            description=description,
            affected_data=affected_data,
            suggested_fix=suggested_fix,
            confidence_score=confidence_score,
            **kwargs
        )
        self.distribution_type = distribution_type
        self.statistical_measures = statistical_measures or {}
        self.anomaly_score = anomaly_score


@dataclass
class IntegrityViolation(Anomaly):
    """完整性违反异常"""
    violation_type: str = ""  # 'structural', 'semantic', 'format'
    integrity_score: float = 0.0
    repair_suggestions: List[str] = field(default_factory=list)
    
    def __init__(self, severity: AnomalySeverity, description: str, affected_data: Dict[str, Any], 
                 suggested_fix: str, violation_type: str = "", integrity_score: float = 0.0,
                 repair_suggestions: List[str] = None, confidence_score: float = 1.0, **kwargs):
        """初始化完整性违反异常"""
        super().__init__(
            anomaly_type="integrity_violation",
            severity=severity,
            description=description,
            affected_data=affected_data,
            suggested_fix=suggested_fix,
            confidence_score=confidence_score,
            **kwargs
        )
        self.violation_type = violation_type
        self.integrity_score = integrity_score
        self.repair_suggestions = repair_suggestions or []


@dataclass
class SemanticPattern:
    """语义模式定义"""
    task_keywords: Set[str]
    object_keywords: Set[str] 
    modifier_keywords: Set[str]
    pattern_name: str
    confidence: float = 1.0


class RPUStructureDetector:
    """RPU结构异常检测器
    
    检测RPU三元组中的完整性和一致性异常，包括：
    - 语义不合理组合检测
    - 缺失组件和完整性检测 (需求 7.2)
    - 论文内RPU矛盾检测 (需求 7.3)  
    - RPU分布异常分析 (需求 7.4)
    """
    
    def __init__(self, config: Optional[Union[Dict[str, Any], 'DetectionConfig']] = None):
        """初始化RPU结构检测器
        
        Args:
            config: 检测器配置参数，可以是字典或DetectionConfig对象
        """
        self.logger = logging.getLogger(__name__)
        
        # 处理不同类型的配置
        if config is None:
            self.config = {}
        elif hasattr(config, 'thresholds'):
            # DetectionConfig对象
            self.config = {
                'semantic_threshold': config.thresholds.rpu_semantic_threshold,
                'integrity_threshold': config.thresholds.rpu_completeness_threshold,
                'frequency_threshold': 0.001,  # 经验值
                'contradiction_threshold': 0.5,  # 经验值
            }
        else:
            # 字典配置
            self.config = config or {}
        
        # 语义一致性阈值 - 这是经验值，需要根据实际数据调整
        self.semantic_threshold = self.config.get('semantic_threshold', 0.3)  # 经验值
        self.logger.info(f"语义一致性阈值设为 {self.semantic_threshold} (这是经验值，建议根据实际数据调整)")
        
        # 频率异常阈值 - 这是经验值
        self.frequency_threshold = self.config.get('frequency_threshold', 0.001)  # 经验值
        self.logger.info(f"频率异常阈值设为 {self.frequency_threshold} (这是经验值，建议根据实际数据调整)")
        
        # 完整性检测阈值 - 这是经验值
        self.integrity_threshold = self.config.get('integrity_threshold', 0.7)  # 经验值
        self.logger.info(f"完整性阈值设为 {self.integrity_threshold} (这是经验值，建议根据实际数据调整)")
        
        # 矛盾检测阈值 - 这是经验值
        self.contradiction_threshold = self.config.get('contradiction_threshold', 0.5)  # 经验值：降低阈值以提高敏感性
        self.logger.info(f"矛盾检测阈值设为 {self.contradiction_threshold} (这是经验值，建议根据实际数据调整)")
        
        # 分布异常检测参数 - 这些是经验值
        self.distribution_config = {
            'outlier_std_threshold': self.config.get('outlier_std_threshold', 2.5),  # 经验值
            'imbalance_ratio_threshold': self.config.get('imbalance_ratio_threshold', 10.0),  # 经验值
            'min_sample_size': self.config.get('min_sample_size', 10)  # 经验值
        }
        self.logger.info(f"分布异常检测参数: {self.distribution_config} (这些是经验值，建议根据实际数据调整)")
        
        # 初始化语义模式库
        self._initialize_semantic_patterns()
        
        # 统计信息
        self.rpu_stats = defaultdict(int)
        self.component_stats = {
            'task': defaultdict(int),
            'object': defaultdict(int), 
            'modifier': defaultdict(int)
        }
        self.combination_stats = defaultdict(int)
        self.paper_stats = defaultdict(list)  # 按论文统计RPU
        self.temporal_stats = defaultdict(list)  # 时间序列统计
        
    def _initialize_semantic_patterns(self) -> None:
        """初始化语义模式库
        
        定义常见的Task-Object-Modifier语义模式，用于验证组合的合理性。
        这些模式基于学术论文中常见的研究活动模式。
        """
        self.semantic_patterns = [
            # 分析类模式
            SemanticPattern(
                task_keywords={'analyze', 'analysis', 'examine', 'investigate', 'study', 'evaluate'},
                object_keywords={'data', 'information', 'results', 'performance', 'behavior', 'pattern'},
                modifier_keywords={'statistical', 'empirical', 'quantitative', 'qualitative', 'comprehensive'},
                pattern_name="analysis_pattern"
            ),
            
            # 处理类模式  
            SemanticPattern(
                task_keywords={'process', 'processing', 'transform', 'convert', 'generate', 'produce'},
                object_keywords={'signal', 'image', 'text', 'data', 'information', 'content'},
                modifier_keywords={'digital', 'automatic', 'real-time', 'batch', 'parallel'},
                pattern_name="processing_pattern"
            ),
            
            # 提取类模式
            SemanticPattern(
                task_keywords={'extract', 'extraction', 'identify', 'detect', 'recognize', 'find'},
                object_keywords={'feature', 'pattern', 'information', 'knowledge', 'structure', 'component'},
                modifier_keywords={'key', 'important', 'relevant', 'significant', 'critical'},
                pattern_name="extraction_pattern"
            ),
            
            # 建模类模式
            SemanticPattern(
                task_keywords={'model', 'modeling', 'simulate', 'predict', 'estimate', 'forecast'},
                object_keywords={'system', 'process', 'behavior', 'relationship', 'dynamics', 'trend'},
                modifier_keywords={'mathematical', 'computational', 'statistical', 'predictive', 'dynamic'},
                pattern_name="modeling_pattern"
            ),
            
            # 优化类模式
            SemanticPattern(
                task_keywords={'optimize', 'optimization', 'improve', 'enhance', 'maximize', 'minimize'},
                object_keywords={'performance', 'efficiency', 'accuracy', 'speed', 'quality', 'cost'},
                modifier_keywords={'optimal', 'efficient', 'effective', 'improved', 'enhanced'},
                pattern_name="optimization_pattern"
            )
        ]
        
        self.logger.info(f"初始化了 {len(self.semantic_patterns)} 个语义模式")
    
    def detect(self, rpus: List[RPURecord]) -> List[Anomaly]:
        """检测RPU结构异常
        
        Args:
            rpus: RPU记录列表
            
        Returns:
            检测到的异常列表
        """
        if not rpus:
            return []
            
        try:
            self.logger.info(f"开始检测 {len(rpus)} 个RPU的结构异常")
            
            # 收集统计信息
            self._collect_statistics(rpus)
            
            anomalies = []
            
            # 1. 检测语义不一致
            semantic_anomalies = self._detect_semantic_inconsistencies(rpus)
            anomalies.extend(semantic_anomalies)
            
            # 2. 检测缺失组件和完整性问题 (需求 7.2)
            missing_component_anomalies = self._detect_missing_components(rpus)
            anomalies.extend(missing_component_anomalies)
            
            integrity_anomalies = self._detect_integrity_violations(rpus)
            anomalies.extend(integrity_anomalies)
            
            # 3. 检测论文内RPU矛盾 (需求 7.3)
            contradiction_anomalies = self._detect_intra_paper_contradictions(rpus)
            anomalies.extend(contradiction_anomalies)
            
            # 4. 检测RPU分布异常 (需求 7.4)
            distribution_anomalies = self._detect_distribution_anomalies(rpus)
            anomalies.extend(distribution_anomalies)
            
            # 5. 检测异常频繁或稀少的RPU模式
            frequency_anomalies = self._detect_frequency_anomalies(rpus)
            anomalies.extend(frequency_anomalies)
            
            # 6. 检测语义冲突
            conflict_anomalies = self._detect_semantic_conflicts(rpus)
            anomalies.extend(conflict_anomalies)
            
            self.logger.info(f"RPU结构检测完成，发现 {len(anomalies)} 个异常")
            return anomalies
            
        except Exception as e:
            raise DetectionLogicException(f"RPU结构检测失败: {e}") from e
    
    def _collect_statistics(self, rpus: List[RPURecord]) -> None:
        """收集RPU统计信息"""
        self.rpu_stats.clear()
        for component in self.component_stats:
            self.component_stats[component].clear()
        self.combination_stats.clear()
        self.paper_stats.clear()
        self.temporal_stats.clear()
        
        for rpu in rpus:
            # 统计各组件频率
            self.component_stats['task'][rpu.task.lower()] += 1
            self.component_stats['object'][rpu.object.lower()] += 1
            if rpu.modifier:
                self.component_stats['modifier'][rpu.modifier.lower()] += 1
            
            # 统计组合频率
            combination = f"{rpu.task.lower()}|{rpu.object.lower()}|{rpu.modifier.lower() if rpu.modifier else ''}"
            self.combination_stats[combination] += 1
            
            # 按论文统计
            self.paper_stats[rpu.paper_id].append(rpu)
            
            # 时间序列统计（如果有时间戳）
            if hasattr(rpu, 'timestamp') and rpu.timestamp:
                self.temporal_stats[rpu.timestamp.date()].append(rpu)
            
        self.logger.debug(f"统计完成: {len(self.component_stats['task'])} 个task, "
                         f"{len(self.component_stats['object'])} 个object, "
                         f"{len(self.component_stats['modifier'])} 个modifier, "
                         f"{len(self.paper_stats)} 篇论文")
    
    
    def _detect_semantic_inconsistencies(self, rpus: List[RPURecord]) -> List[SemanticInconsistency]:
        """检测语义不一致的RPU组合
        
        通过语义模式匹配和词汇相关性分析检测不合理的Task-Object-Modifier组合。
        """
        anomalies = []
        
        for rpu in rpus:
            semantic_score = self._calculate_semantic_consistency_score(rpu)
            
            if semantic_score < self.semantic_threshold:
                # 生成详细的不一致描述
                inconsistency_details = self._analyze_semantic_inconsistency(rpu)
                
                anomaly = SemanticInconsistency(
                    anomaly_type="semantic_inconsistency",
                    severity=self._determine_severity(semantic_score),
                    description=f"RPU语义不一致: Task '{rpu.task}' 与 Object '{rpu.object}' 和 Modifier '{rpu.modifier}' 的组合语义不合理",
                    affected_data={
                        'paper_id': rpu.paper_id,
                        'sentence_id': rpu.sentence_id,
                        'rpu_components': {
                            'task': rpu.task,
                            'object': rpu.object,
                            'modifier': rpu.modifier
                        },
                        'semantic_score': semantic_score,
                        'inconsistency_details': inconsistency_details
                    },
                    suggested_fix=f"建议重新检查RPU提取结果，或验证Task-Object-Modifier组合的语义合理性。语义分数: {semantic_score:.3f}",
                    rpu_components={
                        'task': rpu.task,
                        'object': rpu.object,
                        'modifier': rpu.modifier
                    },
                    inconsistency_type=inconsistency_details.get('type', 'semantic_mismatch'),
                    semantic_score=semantic_score,
                    confidence_score=1.0 - semantic_score  # 语义分数越低，异常置信度越高
                )
                
                anomalies.append(anomaly)
        
        return anomalies
    
    def _calculate_semantic_consistency_score(self, rpu: RPURecord) -> float:
        """计算RPU的语义一致性分数
        
        Args:
            rpu: RPU记录
            
        Returns:
            语义一致性分数 (0-1，越高越一致)
        """
        task_lower = rpu.task.lower()
        object_lower = rpu.object.lower()
        modifier_lower = rpu.modifier.lower() if rpu.modifier else ""
        
        max_score = 0.0
        
        # 与预定义语义模式匹配
        for pattern in self.semantic_patterns:
            pattern_score = self._match_semantic_pattern(task_lower, object_lower, modifier_lower, pattern)
            max_score = max(max_score, pattern_score)
        
        # 基于词汇相关性的额外评分
        lexical_score = self._calculate_lexical_consistency(task_lower, object_lower, modifier_lower)
        
        # 组合最终分数 (权重是经验值)
        final_score = 0.7 * max_score + 0.3 * lexical_score  # 经验值权重
        
        return min(final_score, 1.0)
    
    def _match_semantic_pattern(self, task: str, object_: str, modifier: str, pattern: SemanticPattern) -> float:
        """匹配语义模式
        
        Args:
            task: 任务词汇
            object_: 对象词汇  
            modifier: 修饰词汇
            pattern: 语义模式
            
        Returns:
            匹配分数 (0-1)
        """
        task_match = any(keyword in task for keyword in pattern.task_keywords)
        object_match = any(keyword in object_ for keyword in pattern.object_keywords)
        modifier_match = any(keyword in modifier for keyword in pattern.modifier_keywords) if modifier else True
        
        # 计算匹配分数
        matches = sum([task_match, object_match, modifier_match])
        total_components = 3 if modifier else 2
        
        base_score = matches / total_components
        
        # 应用模式置信度
        return base_score * pattern.confidence
    
    def _calculate_lexical_consistency(self, task: str, object_: str, modifier: str) -> float:
        """计算词汇一致性分数
        
        基于词汇的语义相关性计算一致性分数。
        这是一个简化的实现，实际应用中可以使用词向量或语言模型。
        """
        # 检查明显的语义冲突
        conflict_patterns = [
            # 动作与对象不匹配
            (r'(delete|remove|destroy)', r'(create|generate|produce)'),
            (r'(analyze|examine)', r'(ignore|skip)'),
            (r'(optimize|improve)', r'(degrade|worsen)'),
            # 修饰词与动作不匹配
            (r'(manual|human)', r'(automatic|automated)'),
            (r'(static|fixed)', r'(dynamic|adaptive)'),
        ]
        
        text = f"{task} {object_} {modifier}".lower()
        
        for pattern1, pattern2 in conflict_patterns:
            if re.search(pattern1, text) and re.search(pattern2, text):
                return 0.1  # 发现冲突，返回低分
        
        # 检查积极的语义关联
        positive_patterns = [
            (r'(process|processing)', r'(data|information|signal)'),
            (r'(analyze|analysis)', r'(result|performance|behavior)'),
            (r'(extract|extraction)', r'(feature|pattern|information)'),
            (r'(model|modeling)', r'(system|process|relationship)'),
        ]
        
        for pattern1, pattern2 in positive_patterns:
            if re.search(pattern1, text) and re.search(pattern2, text):
                return 0.8  # 发现积极关联
        
        # 默认中等分数
        return 0.5
    
    def _analyze_semantic_inconsistency(self, rpu: RPURecord) -> Dict[str, Any]:
        """分析语义不一致的具体原因"""
        details = {
            'type': 'semantic_mismatch',
            'issues': []
        }
        
        task_lower = rpu.task.lower()
        object_lower = rpu.object.lower()
        modifier_lower = rpu.modifier.lower() if rpu.modifier else ""
        
        # 检查具体的不一致类型
        if 'delete' in task_lower and 'create' in object_lower:
            details['issues'].append('动作与对象语义冲突: 删除动作与创建对象')
            details['type'] = 'action_object_conflict'
        
        if 'manual' in modifier_lower and 'automatic' in task_lower:
            details['issues'].append('修饰词与动作冲突: 手动修饰与自动动作')
            details['type'] = 'modifier_action_conflict'
        
        # 检查是否没有匹配任何已知模式
        pattern_matches = [self._match_semantic_pattern(task_lower, object_lower, modifier_lower, p) 
                          for p in self.semantic_patterns]
        if max(pattern_matches) < 0.2:  # 经验值阈值
            details['issues'].append('未匹配任何已知语义模式')
            details['type'] = 'unknown_pattern'
        
        return details
    
    def _detect_missing_components(self, rpus: List[RPURecord]) -> List[MissingComponent]:
        """检测缺失组件的RPU"""
        anomalies = []
        
        for rpu in rpus:
            missing_fields = []
            
            # 检查必需字段
            if not rpu.task or rpu.task.strip() == "":
                missing_fields.append('task')
            
            if not rpu.object or rpu.object.strip() == "":
                missing_fields.append('object')
            
            # modifier是可选的，但如果存在应该有意义
            if rpu.modifier is not None and rpu.modifier.strip() == "":
                missing_fields.append('modifier')
            
            # 检查字段长度异常 (这些是经验值)
            if rpu.task and len(rpu.task) > 200:  # 经验值：task不应该太长
                missing_fields.append('task_too_long')
            
            if rpu.object and len(rpu.object) > 200:  # 经验值：object不应该太长
                missing_fields.append('object_too_long')
            
            if missing_fields:
                severity = AnomalySeverity.HIGH if 'task' in missing_fields or 'object' in missing_fields else AnomalySeverity.MEDIUM
                
                anomaly = MissingComponent(
                    anomaly_type="missing_component",
                    severity=severity,
                    description=f"RPU缺失或异常组件: {', '.join(missing_fields)}",
                    affected_data={
                        'paper_id': rpu.paper_id,
                        'sentence_id': rpu.sentence_id,
                        'missing_fields': missing_fields,
                        'current_values': {
                            'task': rpu.task,
                            'object': rpu.object,
                            'modifier': rpu.modifier
                        }
                    },
                    suggested_fix=f"重新提取或验证RPU组件: {', '.join(missing_fields)}",
                    missing_fields=missing_fields,
                    rpu_id=f"{rpu.paper_id}_{rpu.sentence_id}",
                    confidence_score=0.9
                )
                
                anomalies.append(anomaly)
        
        return anomalies
    
    def _detect_integrity_violations(self, rpus: List[RPURecord]) -> List[IntegrityViolation]:
        """检测RPU完整性违反 (需求 7.2)
        
        检测结构完整性、语义完整性和格式完整性问题。
        """
        anomalies = []
        
        for rpu in rpus:
            violations = []
            integrity_score = 1.0
            
            # 1. 结构完整性检查
            structural_issues = self._check_structural_integrity(rpu)
            if structural_issues:
                violations.extend(structural_issues)
                integrity_score -= 0.3  # 经验值权重
            
            # 2. 语义完整性检查
            semantic_issues = self._check_semantic_integrity(rpu)
            if semantic_issues:
                violations.extend(semantic_issues)
                integrity_score -= 0.4  # 经验值权重
            
            # 3. 格式完整性检查
            format_issues = self._check_format_integrity(rpu)
            if format_issues:
                violations.extend(format_issues)
                integrity_score -= 0.3  # 经验值权重
            
            # 如果完整性分数低于阈值，创建异常
            if integrity_score < self.integrity_threshold:
                repair_suggestions = self._generate_integrity_repair_suggestions(violations)
                
                # 确保完整性分数在有效范围内（处理浮点精度问题）
                integrity_score = max(0.0, min(1.0, integrity_score))
                
                anomaly = IntegrityViolation(
                    severity=self._determine_integrity_severity(integrity_score),
                    description=f"RPU完整性违反: {'; '.join([v['description'] for v in violations])}",
                    affected_data={
                        'paper_id': rpu.paper_id,
                        'sentence_id': rpu.sentence_id,
                        'rpu_components': {
                            'task': rpu.task,
                            'object': rpu.object,
                            'modifier': rpu.modifier
                        },
                        'violations': violations,
                        'integrity_score': integrity_score
                    },
                    suggested_fix=f"修复完整性问题: {'; '.join(repair_suggestions)}",
                    violation_type=self._classify_violation_type(violations),
                    integrity_score=integrity_score,
                    repair_suggestions=repair_suggestions,
                    confidence_score=1.0 - integrity_score
                )
                
                anomalies.append(anomaly)
        
        return anomalies
    
    def _check_structural_integrity(self, rpu: RPURecord) -> List[Dict[str, Any]]:
        """检查结构完整性"""
        issues = []
        
        # 检查必需字段的存在性和有效性
        if not rpu.task or len(rpu.task.strip()) == 0:
            issues.append({
                'type': 'missing_task',
                'description': 'Task字段缺失或为空',
                'severity': 'high'
            })
        
        if not rpu.object or len(rpu.object.strip()) == 0:
            issues.append({
                'type': 'missing_object',
                'description': 'Object字段缺失或为空',
                'severity': 'high'
            })
        
        # 检查字段长度合理性 (这些是经验值)
        if rpu.task and len(rpu.task) > 500:  # 经验值
            issues.append({
                'type': 'task_too_long',
                'description': f'Task字段过长 ({len(rpu.task)} 字符)',
                'severity': 'medium'
            })
        
        if rpu.object and len(rpu.object) > 500:  # 经验值
            issues.append({
                'type': 'object_too_long',
                'description': f'Object字段过长 ({len(rpu.object)} 字符)',
                'severity': 'medium'
            })
        
        # 检查字段是否只包含空白字符
        if rpu.task and rpu.task.strip() == "":
            issues.append({
                'type': 'task_whitespace_only',
                'description': 'Task字段只包含空白字符',
                'severity': 'high'
            })
        
        if rpu.object and rpu.object.strip() == "":
            issues.append({
                'type': 'object_whitespace_only',
                'description': 'Object字段只包含空白字符',
                'severity': 'high'
            })
        
        # 检查字段是否包含异常字符
        for field_name, field_value in [('task', rpu.task), ('object', rpu.object), ('modifier', rpu.modifier)]:
            if field_value and self._contains_anomalous_characters(field_value):
                issues.append({
                    'type': 'anomalous_characters',
                    'description': f'{field_name}字段包含异常字符',
                    'severity': 'low'
                })
        
        return issues
    
    def _check_semantic_integrity(self, rpu: RPURecord) -> List[Dict[str, Any]]:
        """检查语义完整性"""
        issues = []
        
        # 检查是否为无意义的重复词汇
        if rpu.task and rpu.object and rpu.task.lower() == rpu.object.lower():
            issues.append({
                'type': 'task_object_identical',
                'description': 'Task和Object完全相同',
                'severity': 'medium'
            })
        
        # 检查是否包含停用词或无意义词汇
        meaningless_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        
        if rpu.task and rpu.task.lower().strip() in meaningless_words:
            issues.append({
                'type': 'meaningless_task',
                'description': 'Task为无意义词汇',
                'severity': 'high'
            })
        
        if rpu.object and rpu.object.lower().strip() in meaningless_words:
            issues.append({
                'type': 'meaningless_object',
                'description': 'Object为无意义词汇',
                'severity': 'high'
            })
        
        # 检查语义一致性
        semantic_score = self._calculate_semantic_consistency_score(rpu)
        if semantic_score < 0.2:  # 经验值阈值
            issues.append({
                'type': 'semantic_inconsistency',
                'description': f'语义一致性过低 (分数: {semantic_score:.3f})',
                'severity': 'medium'
            })
        
        return issues
    
    def _check_format_integrity(self, rpu: RPURecord) -> List[Dict[str, Any]]:
        """检查格式完整性"""
        issues = []
        
        # 检查是否包含HTML标签或特殊格式
        html_pattern = re.compile(r'<[^>]+>')
        
        for field_name, field_value in [('task', rpu.task), ('object', rpu.object), ('modifier', rpu.modifier)]:
            if field_value and html_pattern.search(field_value):
                issues.append({
                    'type': 'html_tags',
                    'description': f'{field_name}字段包含HTML标签',
                    'severity': 'low'
                })
        
        # 检查是否包含过多的标点符号
        punctuation_pattern = re.compile(r'[^\w\s]')
        
        for field_name, field_value in [('task', rpu.task), ('object', rpu.object), ('modifier', rpu.modifier)]:
            if field_value:
                punct_count = len(punctuation_pattern.findall(field_value))
                if punct_count > len(field_value) * 0.3:  # 经验值：标点符号超过30%
                    issues.append({
                        'type': 'excessive_punctuation',
                        'description': f'{field_name}字段标点符号过多',
                        'severity': 'low'
                    })
        
        return issues
    
    def _contains_anomalous_characters(self, text: str) -> bool:
        """检查是否包含异常字符"""
        # 检查控制字符、特殊Unicode字符等
        anomalous_patterns = [
            r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]',  # 控制字符
            r'[\uFFF0-\uFFFF]',  # 特殊Unicode字符
            r'[^\x00-\x7F\u4e00-\u9fff\u3400-\u4dbf]'  # 非ASCII非中文字符
        ]
        
        for pattern in anomalous_patterns:
            if re.search(pattern, text):
                return True
        
        return False
    
    def _generate_integrity_repair_suggestions(self, violations: List[Dict[str, Any]]) -> List[str]:
        """生成完整性修复建议"""
        suggestions = []
        
        violation_types = {v['type'] for v in violations}
        
        if 'missing_task' in violation_types or 'missing_object' in violation_types:
            suggestions.append("重新运行RPU提取算法")
        
        if 'task_too_long' in violation_types or 'object_too_long' in violation_types:
            suggestions.append("检查提取算法的边界检测逻辑")
        
        if 'anomalous_characters' in violation_types:
            suggestions.append("应用文本清洗和标准化处理")
        
        if 'semantic_inconsistency' in violation_types:
            suggestions.append("验证语义模型的准确性")
        
        if 'html_tags' in violation_types:
            suggestions.append("移除HTML标签和格式化字符")
        
        if 'task_object_identical' in violation_types:
            suggestions.append("检查RPU提取算法的组件区分逻辑")
        
        if 'meaningless_task' in violation_types or 'meaningless_object' in violation_types:
            suggestions.append("改进语义过滤和验证机制")
        
        if 'task_whitespace_only' in violation_types or 'object_whitespace_only' in violation_types:
            suggestions.append("加强输入验证和空值检测")
        
        if 'excessive_punctuation' in violation_types:
            suggestions.append("优化文本预处理和标点符号处理")
        
        # 如果没有匹配到具体类型，提供通用建议
        if not suggestions:
            suggestions.append("检查数据质量和提取算法的准确性")
        
        return suggestions
    
    def _classify_violation_type(self, violations: List[Dict[str, Any]]) -> str:
        """分类违反类型"""
        violation_types = {v['type'] for v in violations}
        
        if any(t in violation_types for t in ['missing_task', 'missing_object', 'task_too_long', 'object_too_long']):
            return 'structural'
        elif any(t in violation_types for t in ['semantic_inconsistency', 'meaningless_task', 'meaningless_object']):
            return 'semantic'
        else:
            return 'format'
    
    def _determine_integrity_severity(self, integrity_score: float) -> AnomalySeverity:
        """根据完整性分数确定严重性"""
        # 这些阈值是经验值
        if integrity_score < 0.3:  # 经验值
            return AnomalySeverity.CRITICAL
        elif integrity_score < 0.5:  # 经验值
            return AnomalySeverity.HIGH
        elif integrity_score < 0.7:  # 经验值
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW
    
    def _detect_intra_paper_contradictions(self, rpus: List[RPURecord]) -> List[ContradictoryRPU]:
        """检测论文内RPU矛盾 (需求 7.3)
        
        检测同一论文内语义矛盾的RPU表达。
        """
        anomalies = []
        
        # 按论文分组检测
        for paper_id, paper_rpus in self.paper_stats.items():
            if len(paper_rpus) < 2:
                continue
            
            contradictions = self._find_semantic_contradictions(paper_rpus)
            
            for contradiction in contradictions:
                anomaly = ContradictoryRPU(
                    severity=self._determine_contradiction_severity(contradiction['semantic_distance']),
                    description=f"论文内RPU语义矛盾: {contradiction['description']}",
                    affected_data={
                        'paper_id': paper_id,
                        'contradicting_rpus': contradiction['rpus'],
                        'contradiction_evidence': contradiction['evidence']
                    },
                    suggested_fix=f"检查RPU提取的一致性，或验证论文是否确实包含矛盾观点。语义距离: {contradiction['semantic_distance']:.3f}",
                    paper_id=paper_id,
                    conflicting_rpus=contradiction['rpus'],
                    contradiction_type=contradiction['type'],
                    semantic_distance=contradiction['semantic_distance'],
                    confidence_score=contradiction['confidence']
                )
                
                anomalies.append(anomaly)
        
        return anomalies
    
    def _detect_frequency_anomalies(self, rpus: List[RPURecord]) -> List[Anomaly]:
        """检测异常频繁或稀少的RPU模式"""
        anomalies = []
        total_rpus = len(rpus)
        
        if total_rpus == 0:
            return anomalies
        
        # 检测异常稀少的组合
        for combination, count in self.combination_stats.items():
            frequency = count / total_rpus
            
            if frequency < self.frequency_threshold and count == 1:  # 只出现一次且频率极低
                task, object_, modifier = combination.split('|')
                
                anomaly = Anomaly(
                    anomaly_type="rare_rpu_pattern",
                    severity=AnomalySeverity.LOW,
                    description=f"极稀少的RPU模式: Task='{task}', Object='{object_}', Modifier='{modifier}' (频率: {frequency:.6f})",
                    affected_data={
                        'combination': combination,
                        'frequency': frequency,
                        'count': count,
                        'total_rpus': total_rpus
                    },
                    suggested_fix="验证此RPU是否为提取错误或确实是罕见的研究模式",
                    confidence_score=0.6
                )
                
                anomalies.append(anomaly)
        
        # 检测异常频繁的组合 (这是经验值阈值)
        high_frequency_threshold = 0.1  # 经验值：超过10%认为异常频繁
        for combination, count in self.combination_stats.items():
            frequency = count / total_rpus
            
            if frequency > high_frequency_threshold:
                task, object_, modifier = combination.split('|')
                
                anomaly = Anomaly(
                    anomaly_type="frequent_rpu_pattern", 
                    severity=AnomalySeverity.MEDIUM,
                    description=f"异常频繁的RPU模式: Task='{task}', Object='{object_}', Modifier='{modifier}' (频率: {frequency:.3f})",
                    affected_data={
                        'combination': combination,
                        'frequency': frequency,
                        'count': count,
                        'total_rpus': total_rpus
                    },
                    suggested_fix="检查是否存在RPU提取偏差或数据重复",
                    confidence_score=0.7
                )
                
                anomalies.append(anomaly)
        
        return anomalies
    
    def _find_semantic_contradictions(self, rpus: List[RPURecord]) -> List[Dict[str, Any]]:
        """查找语义矛盾"""
        contradictions = []
        
        # 定义矛盾模式 - 这些是基于语言学分析的经验模式
        contradiction_patterns = [
            {
                'positive': r'(increase|enhance|improve|boost|strengthen|optimize|maximize)',
                'negative': r'(decrease|reduce|degrade|weaken|minimize|worsen)',
                'type': 'directional_contradiction',
                'description': '方向性矛盾：同时包含增强和减弱的表达'
            },
            {
                'positive': r'(create|generate|produce|build|construct|establish)',
                'negative': r'(delete|remove|destroy|eliminate|discard)',
                'type': 'existence_contradiction',
                'description': '存在性矛盾：同时包含创建和销毁的表达'
            },
            {
                'positive': r'(enable|activate|start|begin|initiate)',
                'negative': r'(disable|deactivate|stop|end|terminate)',
                'type': 'state_contradiction',
                'description': '状态矛盾：同时包含启用和禁用的表达'
            },
            {
                'positive': r'(manual|human|interactive)',
                'negative': r'(automatic|automated|autonomous)',
                'type': 'automation_contradiction',
                'description': '自动化矛盾：同时包含手动和自动的表达'
            }
        ]
        
        # 检查每对RPU的矛盾
        for i in range(len(rpus)):
            for j in range(i + 1, len(rpus)):
                rpu1, rpu2 = rpus[i], rpus[j]
                
                # 构建RPU的完整文本表示
                text1 = f"{rpu1.task} {rpu1.object} {rpu1.modifier or ''}".lower()
                text2 = f"{rpu2.task} {rpu2.object} {rpu2.modifier or ''}".lower()
                
                for pattern in contradiction_patterns:
                    # 检查是否一个RPU匹配正面模式，另一个匹配负面模式
                    pos_in_1 = bool(re.search(pattern['positive'], text1))
                    neg_in_1 = bool(re.search(pattern['negative'], text1))
                    pos_in_2 = bool(re.search(pattern['positive'], text2))
                    neg_in_2 = bool(re.search(pattern['negative'], text2))
                    
                    if (pos_in_1 and neg_in_2) or (neg_in_1 and pos_in_2):
                        # 计算语义距离
                        semantic_distance = self._calculate_semantic_distance(rpu1, rpu2)
                        
                        # 只有当语义距离超过阈值时才认为是矛盾
                        if semantic_distance > self.contradiction_threshold:
                            contradictions.append({
                                'type': pattern['type'],
                                'description': pattern['description'],
                                'rpus': [
                                    {
                                        'sentence_id': rpu1.sentence_id,
                                        'task': rpu1.task,
                                        'object': rpu1.object,
                                        'modifier': rpu1.modifier,
                                        'text': text1
                                    },
                                    {
                                        'sentence_id': rpu2.sentence_id,
                                        'task': rpu2.task,
                                        'object': rpu2.object,
                                        'modifier': rpu2.modifier,
                                        'text': text2
                                    }
                                ],
                                'evidence': {
                                    'pattern_type': pattern['type'],
                                    'matched_positive': pattern['positive'],
                                    'matched_negative': pattern['negative']
                                },
                                'semantic_distance': semantic_distance,
                                'confidence': min(0.9, semantic_distance)  # 经验值置信度计算
                            })
        
        return contradictions
    
    def _calculate_semantic_distance(self, rpu1: RPURecord, rpu2: RPURecord) -> float:
        """计算两个RPU之间的语义距离
        
        这是一个简化的语义距离计算，实际应用中可以使用更复杂的语义模型。
        """
        # 基于词汇重叠的简单距离计算
        words1 = set(f"{rpu1.task} {rpu1.object} {rpu1.modifier or ''}".lower().split())
        words2 = set(f"{rpu2.task} {rpu2.object} {rpu2.modifier or ''}".lower().split())
        
        # 计算Jaccard距离
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        if union == 0:
            return 1.0
        
        jaccard_similarity = intersection / union
        jaccard_distance = 1.0 - jaccard_similarity
        
        # 考虑语义对立词汇的权重
        opposition_weight = self._calculate_opposition_weight(words1, words2)
        
        # 最终距离 = Jaccard距离 + 对立权重
        final_distance = min(1.0, jaccard_distance + opposition_weight)
        
        return final_distance
    
    def _calculate_opposition_weight(self, words1: Set[str], words2: Set[str]) -> float:
        """计算对立词汇权重"""
        # 定义对立词组 - 这些是基于语言学分析的经验对立关系
        # 使用词组而不是词对，以支持更灵活的匹配
        opposition_groups = [
            # 创建vs销毁组
            (['create', 'generate', 'produce', 'build', 'construct', 'establish'], 
             ['delete', 'remove', 'destroy', 'eliminate', 'discard', 'demolish']),
            # 增强vs减弱组
            (['increase', 'enhance', 'improve', 'boost', 'strengthen', 'optimize', 'maximize'], 
             ['decrease', 'reduce', 'degrade', 'weaken', 'minimize', 'worsen']),
            # 启用vs禁用组
            (['enable', 'activate', 'start', 'begin', 'initiate', 'turn_on'], 
             ['disable', 'deactivate', 'stop', 'end', 'terminate', 'turn_off']),
            # 手动vs自动组
            (['manual', 'human', 'interactive', 'supervised'], 
             ['automatic', 'automated', 'autonomous', 'unsupervised'])
        ]
        
        weight = 0.0
        for word1 in words1:
            for word2 in words2:
                for group1, group2 in opposition_groups:
                    # 检查是否一个词在第一组，另一个词在第二组
                    if (word1 in group1 and word2 in group2) or (word1 in group2 and word2 in group1):
                        weight += 0.4  # 经验值：每个对立词组匹配增加0.4的权重
        
        return min(0.6, weight)  # 经验值：最大权重限制为0.6
    
    def _determine_contradiction_severity(self, semantic_distance: float) -> AnomalySeverity:
        """根据语义距离确定矛盾严重性"""
        # 这些阈值是经验值
        if semantic_distance > 0.9:  # 经验值
            return AnomalySeverity.HIGH
        elif semantic_distance > 0.8:  # 经验值
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW
    
    def _detect_distribution_anomalies(self, rpus: List[RPURecord]) -> List[RPUDistributionAnomaly]:
        """检测RPU分布异常 (需求 7.4)
        
        分析RPU分布模式，检测异常的分布特征。
        """
        anomalies = []
        
        if len(rpus) < self.distribution_config['min_sample_size']:
            return anomalies
        
        # 1. 检测组件分布不平衡
        component_anomalies = self._detect_component_imbalance(rpus)
        anomalies.extend(component_anomalies)
        
        # 2. 检测时间分布异常
        temporal_anomalies = self._detect_temporal_distribution_anomalies(rpus)
        anomalies.extend(temporal_anomalies)
        
        # 3. 检测频率分布离群值
        frequency_outliers = self._detect_frequency_distribution_outliers(rpus)
        anomalies.extend(frequency_outliers)
        
        return anomalies
    
    def _detect_component_imbalance(self, rpus: List[RPURecord]) -> List[RPUDistributionAnomaly]:
        """检测组件分布不平衡"""
        anomalies = []
        
        # 计算各组件的分布统计
        for component_type in ['task', 'object', 'modifier']:
            component_counts = self.component_stats[component_type]
            
            if not component_counts:
                continue
            
            # 计算分布统计量
            counts = list(component_counts.values())
            mean_count = sum(counts) / len(counts)
            std_count = math.sqrt(sum((x - mean_count) ** 2 for x in counts) / len(counts))
            
            # 检测极端不平衡
            max_count = max(counts)
            min_count = min(counts)
            
            imbalance_ratio = max_count / min_count if min_count > 0 else float('inf')
            
            if imbalance_ratio > self.distribution_config['imbalance_ratio_threshold']:
                # 找出最频繁和最稀少的组件
                most_frequent = max(component_counts.items(), key=lambda x: x[1])
                least_frequent = min(component_counts.items(), key=lambda x: x[1])
                
                anomaly = RPUDistributionAnomaly(
                    severity=self._determine_distribution_severity(imbalance_ratio),
                    description=f"{component_type}组件分布严重不平衡: 最频繁'{most_frequent[0]}'({most_frequent[1]}次) vs 最稀少'{least_frequent[0]}'({least_frequent[1]}次)",
                    affected_data={
                        'component_type': component_type,
                        'imbalance_ratio': imbalance_ratio,
                        'most_frequent': most_frequent,
                        'least_frequent': least_frequent,
                        'total_unique_components': len(component_counts)
                    },
                    suggested_fix=f"检查{component_type}提取算法的偏差，或验证数据源的多样性",
                    distribution_type='component_imbalance',
                    statistical_measures={
                        'mean': mean_count,
                        'std': std_count,
                        'imbalance_ratio': imbalance_ratio,
                        'gini_coefficient': self._calculate_gini_coefficient(counts)
                    },
                    anomaly_score=min(1.0, imbalance_ratio / self.distribution_config['imbalance_ratio_threshold']),
                    confidence_score=0.8
                )
                
                anomalies.append(anomaly)
        
        return anomalies
    
    def _detect_temporal_distribution_anomalies(self, rpus: List[RPURecord]) -> List[RPUDistributionAnomaly]:
        """检测时间分布异常"""
        anomalies = []
        
        if not self.temporal_stats:
            return anomalies
        
        # 计算每日RPU数量
        daily_counts = [len(rpus_list) for rpus_list in self.temporal_stats.values()]
        
        if len(daily_counts) < 3:  # 经验值：至少需要3天的数据
            return anomalies
        
        mean_daily = sum(daily_counts) / len(daily_counts)
        std_daily = math.sqrt(sum((x - mean_daily) ** 2 for x in daily_counts) / len(daily_counts))
        
        # 检测异常日期
        outlier_threshold = self.distribution_config['outlier_std_threshold']
        
        for date, rpus_list in self.temporal_stats.items():
            daily_count = len(rpus_list)
            z_score = abs(daily_count - mean_daily) / std_daily if std_daily > 0 else 0
            
            if z_score > outlier_threshold:
                anomaly = RPUDistributionAnomaly(
                    severity=AnomalySeverity.MEDIUM,
                    description=f"时间分布异常: {date}日期的RPU数量异常 ({daily_count}个，Z分数: {z_score:.2f})",
                    affected_data={
                        'date': str(date),
                        'daily_count': daily_count,
                        'mean_daily': mean_daily,
                        'std_daily': std_daily,
                        'z_score': z_score
                    },
                    suggested_fix="检查该日期的数据处理是否正常，或验证是否存在数据质量问题",
                    distribution_type='temporal_anomaly',
                    statistical_measures={
                        'z_score': z_score,
                        'mean_daily': mean_daily,
                        'std_daily': std_daily
                    },
                    anomaly_score=min(1.0, z_score / outlier_threshold),
                    confidence_score=0.7
                )
                
                anomalies.append(anomaly)
        
        return anomalies
    
    def _detect_frequency_distribution_outliers(self, rpus: List[RPURecord]) -> List[RPUDistributionAnomaly]:
        """检测频率分布离群值"""
        anomalies = []
        
        # 分析组合频率分布
        combination_counts = list(self.combination_stats.values())
        
        if len(combination_counts) < 10:  # 经验值：至少需要10个不同组合
            return anomalies
        
        # 计算频率分布统计
        mean_freq = sum(combination_counts) / len(combination_counts)
        std_freq = math.sqrt(sum((x - mean_freq) ** 2 for x in combination_counts) / len(combination_counts))
        
        outlier_threshold = self.distribution_config['outlier_std_threshold']
        
        for combination, count in self.combination_stats.items():
            z_score = abs(count - mean_freq) / std_freq if std_freq > 0 else 0
            
            if z_score > outlier_threshold:
                task, object_, modifier = combination.split('|')
                
                anomaly = RPUDistributionAnomaly(
                    severity=AnomalySeverity.LOW,
                    description=f"频率分布离群值: RPU组合'{task}|{object_}|{modifier}'出现频率异常 ({count}次，Z分数: {z_score:.2f})",
                    affected_data={
                        'combination': combination,
                        'count': count,
                        'mean_frequency': mean_freq,
                        'std_frequency': std_freq,
                        'z_score': z_score
                    },
                    suggested_fix="验证此RPU组合是否为提取错误或确实是异常模式",
                    distribution_type='frequency_outlier',
                    statistical_measures={
                        'z_score': z_score,
                        'mean_frequency': mean_freq,
                        'std_frequency': std_freq
                    },
                    anomaly_score=min(1.0, z_score / outlier_threshold),
                    confidence_score=0.6
                )
                
                anomalies.append(anomaly)
        
        return anomalies
    
    def _calculate_gini_coefficient(self, values: List[float]) -> float:
        """计算基尼系数衡量分布不平等程度"""
        if not values or len(values) == 1:
            return 0.0
        
        sorted_values = sorted(values)
        n = len(sorted_values)
        cumsum = sum(sorted_values)
        
        if cumsum == 0:
            return 0.0
        
        # 计算基尼系数
        gini = (2 * sum((i + 1) * val for i, val in enumerate(sorted_values))) / (n * cumsum) - (n + 1) / n
        
        return gini
    
    def _determine_distribution_severity(self, imbalance_ratio: float) -> AnomalySeverity:
        """根据不平衡比例确定严重性"""
        # 这些阈值是经验值
        if imbalance_ratio > 100:  # 经验值
            return AnomalySeverity.HIGH
        elif imbalance_ratio > 50:  # 经验值
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW
    
    def _detect_semantic_conflicts(self, rpus: List[RPURecord]) -> List[Anomaly]:
        """检测同一论文内的语义冲突RPU"""
        anomalies = []
        
        # 按论文分组
        paper_rpus = defaultdict(list)
        for rpu in rpus:
            paper_rpus[rpu.paper_id].append(rpu)
        
        # 检查每篇论文内的冲突
        for paper_id, paper_rpu_list in paper_rpus.items():
            if len(paper_rpu_list) < 2:
                continue
                
            conflicts = self._find_intra_paper_conflicts(paper_rpu_list)
            
            for conflict in conflicts:
                anomaly = Anomaly(
                    anomaly_type="intra_paper_semantic_conflict",
                    severity=AnomalySeverity.MEDIUM,
                    description=f"论文内RPU语义冲突: {conflict['description']}",
                    affected_data={
                        'paper_id': paper_id,
                        'conflicting_rpus': conflict['rpus'],
                        'conflict_type': conflict['type']
                    },
                    suggested_fix="检查RPU提取的一致性，或验证论文是否确实包含矛盾的研究内容",
                    confidence_score=conflict['confidence']
                )
                
                anomalies.append(anomaly)
        
        return anomalies
    
    def _find_intra_paper_conflicts(self, rpus: List[RPURecord]) -> List[Dict[str, Any]]:
        """查找论文内的RPU冲突"""
        conflicts = []
        
        # 定义冲突模式
        conflict_patterns = [
            {
                'pattern': (r'(create|generate|produce)', r'(delete|remove|destroy)'),
                'type': 'creation_destruction_conflict',
                'description': '创建与销毁动作冲突'
            },
            {
                'pattern': (r'(increase|enhance|improve)', r'(decrease|reduce|degrade)'),
                'type': 'enhancement_degradation_conflict', 
                'description': '增强与降级动作冲突'
            },
            {
                'pattern': (r'(manual|human)', r'(automatic|automated)'),
                'type': 'manual_automatic_conflict',
                'description': '手动与自动方式冲突'
            }
        ]
        
        # 检查每对RPU的冲突
        for i in range(len(rpus)):
            for j in range(i + 1, len(rpus)):
                rpu1, rpu2 = rpus[i], rpus[j]
                
                text1 = f"{rpu1.task} {rpu1.object} {rpu1.modifier}".lower()
                text2 = f"{rpu2.task} {rpu2.object} {rpu2.modifier}".lower()
                
                for conflict_pattern in conflict_patterns:
                    pattern1, pattern2 = conflict_pattern['pattern']
                    
                    if ((re.search(pattern1, text1) and re.search(pattern2, text2)) or
                        (re.search(pattern2, text1) and re.search(pattern1, text2))):
                        
                        conflicts.append({
                            'type': conflict_pattern['type'],
                            'description': conflict_pattern['description'],
                            'rpus': [
                                {
                                    'sentence_id': rpu1.sentence_id,
                                    'task': rpu1.task,
                                    'object': rpu1.object,
                                    'modifier': rpu1.modifier
                                },
                                {
                                    'sentence_id': rpu2.sentence_id,
                                    'task': rpu2.task,
                                    'object': rpu2.object,
                                    'modifier': rpu2.modifier
                                }
                            ],
                            'confidence': 0.8  # 经验值置信度
                        })
        
        return conflicts
    
    def _determine_severity(self, semantic_score: float) -> AnomalySeverity:
        """根据语义分数确定异常严重性
        
        Args:
            semantic_score: 语义一致性分数 (0-1)
            
        Returns:
            异常严重性级别
        """
        # 这些阈值是经验值，需要根据实际数据调整
        if semantic_score < 0.1:  # 经验值
            return AnomalySeverity.CRITICAL
        elif semantic_score < 0.2:  # 经验值
            return AnomalySeverity.HIGH
        elif semantic_score < 0.3:  # 经验值
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW
    
    def get_detector_name(self) -> str:
        """获取检测器名称"""
        return "RPUStructureDetector"
    
    def get_supported_data_types(self) -> List[str]:
        """获取支持的数据类型"""
        return ["rpu_records"]
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取检测统计信息"""
        return {
            'component_stats': dict(self.component_stats),
            'combination_stats': dict(self.combination_stats),
            'paper_stats': {k: len(v) for k, v in self.paper_stats.items()},
            'temporal_stats': {str(k): len(v) for k, v in self.temporal_stats.items()},
            'total_patterns': len(self.semantic_patterns),
            'config': {
                'semantic_threshold': self.semantic_threshold,
                'frequency_threshold': self.frequency_threshold,
                'integrity_threshold': self.integrity_threshold,
                'contradiction_threshold': self.contradiction_threshold,
                'distribution_config': self.distribution_config
            }
        }