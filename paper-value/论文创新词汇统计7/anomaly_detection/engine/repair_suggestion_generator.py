"""
修复建议生成器

为检测到的异常生成具体的修复建议，包括优先级评估、风险分析和修复历史追踪。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional, Tuple
import json
import logging
from pathlib import Path

from ..core.data_models import (
    Anomaly, DetectionResult, RepairHistory, AnomalySeverity,
    CaseInconsistency, PluralSingularConflict, NumericalRangeAnomaly,
    CrossDomainMerge, SemanticInconsistency, MissingComponent,
    FrequencyOutlier, PMIAnomaly, EntropyAnomaly, MissingDuplicate
)
from ..core.exceptions import AnomalyDetectionException


class RepairPriority(Enum):
    """修复优先级"""
    IMMEDIATE = "immediate"  # 立即修复
    HIGH = "high"           # 高优先级
    MEDIUM = "medium"       # 中等优先级
    LOW = "low"            # 低优先级
    DEFERRED = "deferred"   # 延期处理


class RiskLevel(Enum):
    """风险级别"""
    MINIMAL = "minimal"     # 最小风险
    LOW = "low"            # 低风险
    MODERATE = "moderate"   # 中等风险
    HIGH = "high"          # 高风险
    CRITICAL = "critical"   # 关键风险


@dataclass
class RepairAction:
    """修复操作"""
    action_type: str
    description: str
    parameters: Dict[str, Any]
    reversible: bool = True
    estimated_time: int = 0  # 预估时间(分钟)
    required_resources: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'action_type': self.action_type,
            'description': self.description,
            'parameters': self.parameters,
            'reversible': self.reversible,
            'estimated_time': self.estimated_time,
            'required_resources': self.required_resources
        }


@dataclass
class RepairSuggestion:
    """修复建议"""
    anomaly_id: str
    anomaly_type: str
    priority: RepairPriority
    risk_level: RiskLevel
    actions: List[RepairAction]
    rationale: str
    prerequisites: List[str] = field(default_factory=list)
    side_effects: List[str] = field(default_factory=list)
    validation_steps: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'anomaly_id': self.anomaly_id,
            'anomaly_type': self.anomaly_type,
            'priority': self.priority.value,
            'risk_level': self.risk_level.value,
            'actions': [action.to_dict() for action in self.actions],
            'rationale': self.rationale,
            'prerequisites': self.prerequisites,
            'side_effects': self.side_effects,
            'validation_steps': self.validation_steps,
            'created_at': self.created_at.isoformat()
        }


class RepairSuggestionGenerator:
    """修复建议生成器
    
    根据异常类型生成具体的修复建议，包括优先级评估和风险分析。
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """初始化修复建议生成器
        
        Args:
            config: 配置参数，包含阈值和策略设置
        """
        self.config = config or {}
        self.logger = logging.getLogger(__name__)
        
        # 异常类型到修复策略的映射
        self.repair_strategies = {
            'case_inconsistency': self._generate_case_inconsistency_repair,
            'plural_singular_conflict': self._generate_plural_singular_repair,
            'numerical_range_anomaly': self._generate_numerical_range_repair,
            'cross_domain_merge': self._generate_cross_domain_repair,
            'semantic_inconsistency': self._generate_semantic_inconsistency_repair,
            'missing_component': self._generate_missing_component_repair,
            'frequency_outlier': self._generate_frequency_outlier_repair,
            'pmi_anomaly': self._generate_pmi_anomaly_repair,
            'entropy_anomaly': self._generate_entropy_anomaly_repair,
            'missing_duplicate': self._generate_missing_duplicate_repair
        }
        
        # 修复历史记录 - 每个实例独立的历史记录
        self.repair_history: List[RepairHistory] = []
        
        # 优先级权重配置
        self.priority_weights = self.config.get('priority_weights', {
            AnomalySeverity.CRITICAL: 10,
            AnomalySeverity.HIGH: 7,
            AnomalySeverity.MEDIUM: 4,
            AnomalySeverity.LOW: 1
        })
    
    def generate_repair_suggestion(self, anomaly: Anomaly) -> RepairSuggestion:
        """为异常生成修复建议
        
        Args:
            anomaly: 检测到的异常
            
        Returns:
            RepairSuggestion: 修复建议
            
        Raises:
            AnomalyDetectionException: 当异常类型不支持时
        """
        try:
            # 获取对应的修复策略
            strategy = self.repair_strategies.get(anomaly.anomaly_type)
            if not strategy:
                raise AnomalyDetectionException(
                    f"不支持的异常类型: {anomaly.anomaly_type}"
                )
            
            # 生成修复建议
            suggestion = strategy(anomaly)
            
            # 记录生成历史
            self.logger.info(
                f"为异常 {anomaly.anomaly_id} 生成修复建议，"
                f"优先级: {suggestion.priority.value}, "
                f"风险级别: {suggestion.risk_level.value}"
            )
            
            return suggestion
            
        except Exception as e:
            self.logger.error(f"生成修复建议失败: {e}")
            raise AnomalyDetectionException(f"修复建议生成失败: {e}")
    
    def generate_batch_suggestions(self, anomalies: List[Anomaly]) -> List[RepairSuggestion]:
        """批量生成修复建议
        
        Args:
            anomalies: 异常列表
            
        Returns:
            List[RepairSuggestion]: 修复建议列表
        """
        suggestions = []
        
        for anomaly in anomalies:
            try:
                suggestion = self.generate_repair_suggestion(anomaly)
                suggestions.append(suggestion)
            except Exception as e:
                self.logger.error(f"为异常 {anomaly.anomaly_id} 生成建议失败: {e}")
                continue
        
        # 按优先级排序
        suggestions.sort(key=self._get_priority_score, reverse=True)
        
        return suggestions
    
    def _generate_case_inconsistency_repair(self, anomaly: CaseInconsistency) -> RepairSuggestion:
        """生成大小写不一致的修复建议"""
        priority = self._assess_priority(anomaly.severity, impact_factor=0.8)
        risk_level = RiskLevel.LOW  # 大小写修复风险较低
        
        actions = [
            RepairAction(
                action_type="normalize_case",
                description="统一概念的大小写格式",
                parameters={
                    "source_variants": anomaly.source_variants,
                    "target_conflicts": anomaly.target_conflicts,
                    "normalization_rule": "lowercase"  # 默认转为小写
                },
                reversible=True,
                estimated_time=5,
                required_resources=["mapping_file_access"]
            ),
            RepairAction(
                action_type="update_mapping",
                description="更新概念映射文件",
                parameters={
                    "mapping_updates": self._generate_case_mapping_updates(anomaly)
                },
                reversible=True,
                estimated_time=10,
                required_resources=["mapping_file_write"]
            )
        ]
        
        return RepairSuggestion(
            anomaly_id=anomaly.anomaly_id,
            anomaly_type=anomaly.anomaly_type,
            priority=priority,
            risk_level=risk_level,
            actions=actions,
            rationale="大小写不一致会导致概念重复和统计错误，需要统一格式",
            prerequisites=["备份原始映射文件"],
            side_effects=["可能影响依赖大小写的下游处理"],
            validation_steps=[
                "验证映射更新的正确性",
                "检查是否有新的冲突产生",
                "确认统计结果的一致性"
            ]
        )
    
    def _generate_plural_singular_repair(self, anomaly: PluralSingularConflict) -> RepairSuggestion:
        """生成单复数冲突的修复建议"""
        priority = self._assess_priority(anomaly.severity, impact_factor=0.9)
        risk_level = RiskLevel.MODERATE  # 单复数修复可能影响语义
        
        actions = [
            RepairAction(
                action_type="resolve_plural_conflict",
                description="解决单复数映射冲突",
                parameters={
                    "singular_form": anomaly.singular_form,
                    "plural_form": anomaly.plural_form,
                    "conflicting_mappings": anomaly.conflicting_mappings,
                    "resolution_strategy": "prefer_singular"  # 默认优先使用单数形式
                },
                reversible=True,
                estimated_time=15,
                required_resources=["mapping_file_access", "nlp_tools"]
            )
        ]
        
        return RepairSuggestion(
            anomaly_id=anomaly.anomaly_id,
            anomaly_type=anomaly.anomaly_type,
            priority=priority,
            risk_level=risk_level,
            actions=actions,
            rationale="单复数冲突会导致概念分割和统计不准确",
            prerequisites=["确认单复数形式的语义等价性"],
            side_effects=["可能改变概念的语义表达"],
            validation_steps=[
                "验证单复数统一后的语义一致性",
                "检查相关概念的频率统计",
                "确认RPU提取结果的正确性"
            ]
        )
    
    def _generate_numerical_range_repair(self, anomaly: NumericalRangeAnomaly) -> RepairSuggestion:
        """生成数值范围异常的修复建议"""
        priority = self._assess_priority(anomaly.severity, impact_factor=1.0)
        risk_level = RiskLevel.HIGH  # 数值范围修复风险较高
        
        actions = [
            RepairAction(
                action_type="split_numerical_range",
                description="拆分过大的数值范围合并",
                parameters={
                    "min_value": anomaly.min_value,
                    "max_value": anomaly.max_value,
                    "range_size": anomaly.range_size,
                    "threshold": anomaly.threshold,
                    "split_strategy": "semantic_clustering"
                },
                reversible=True,
                estimated_time=30,
                required_resources=["mapping_file_access", "semantic_analysis"]
            ),
            RepairAction(
                action_type="validate_split_results",
                description="验证拆分结果的合理性",
                parameters={
                    "validation_method": "semantic_coherence"
                },
                reversible=False,
                estimated_time=20,
                required_resources=["validation_tools"]
            )
        ]
        
        return RepairSuggestion(
            anomaly_id=anomaly.anomaly_id,
            anomaly_type=anomaly.anomaly_type,
            priority=priority,
            risk_level=risk_level,
            actions=actions,
            rationale="过大的数值范围合并可能包含不相关的概念，影响创新计算准确性",
            prerequisites=["分析数值范围内概念的语义相关性"],
            side_effects=["可能增加概念数量，影响统计分布"],
            validation_steps=[
                "验证拆分后概念的语义一致性",
                "检查创新信号计算的变化",
                "确认没有引入新的异常"
            ]
        )
    
    def _generate_cross_domain_repair(self, anomaly: CrossDomainMerge) -> RepairSuggestion:
        """生成跨领域合并的修复建议"""
        priority = self._assess_priority(anomaly.severity, impact_factor=1.2)
        risk_level = RiskLevel.HIGH
        
        actions = [
            RepairAction(
                action_type="separate_cross_domain",
                description="分离跨领域的错误合并",
                parameters={
                    "domain_a": anomaly.domain_a,
                    "domain_b": anomaly.domain_b,
                    "similarity_score": anomaly.similarity_score,
                    "separation_strategy": "domain_specific"
                },
                reversible=True,
                estimated_time=45,
                required_resources=["domain_knowledge", "mapping_file_access"]
            )
        ]
        
        return RepairSuggestion(
            anomaly_id=anomaly.anomaly_id,
            anomaly_type=anomaly.anomaly_type,
            priority=priority,
            risk_level=risk_level,
            actions=actions,
            rationale="跨领域合并会混淆不同研究领域的概念，严重影响创新分析",
            prerequisites=["确认领域分类的准确性"],
            side_effects=["可能需要重新计算相关的创新信号"],
            validation_steps=[
                "验证领域分离的正确性",
                "检查概念在各自领域内的一致性",
                "确认创新计算结果的改善"
            ]
        )
    
    def _generate_semantic_inconsistency_repair(self, anomaly: SemanticInconsistency) -> RepairSuggestion:
        """生成语义不一致的修复建议"""
        priority = self._assess_priority(anomaly.severity, impact_factor=0.9)
        risk_level = RiskLevel.MODERATE
        
        actions = [
            RepairAction(
                action_type="fix_semantic_inconsistency",
                description="修复RPU语义不一致",
                parameters={
                    "rpu_components": anomaly.rpu_components,
                    "inconsistency_type": anomaly.inconsistency_type,
                    "fix_strategy": "component_replacement"
                },
                reversible=True,
                estimated_time=25,
                required_resources=["rpu_database_access", "semantic_analysis"]
            )
        ]
        
        return RepairSuggestion(
            anomaly_id=anomaly.anomaly_id,
            anomaly_type=anomaly.anomaly_type,
            priority=priority,
            risk_level=risk_level,
            actions=actions,
            rationale="语义不一致的RPU会影响研究问题的准确表达",
            prerequisites=["确认正确的语义组合"],
            side_effects=["可能需要重新提取相关RPU"],
            validation_steps=[
                "验证修复后RPU的语义合理性",
                "检查相关论文的RPU一致性"
            ]
        )
    
    def _generate_missing_component_repair(self, anomaly: MissingComponent) -> RepairSuggestion:
        """生成缺失组件的修复建议"""
        priority = self._assess_priority(anomaly.severity, impact_factor=0.7)
        risk_level = RiskLevel.LOW
        
        actions = [
            RepairAction(
                action_type="fill_missing_components",
                description="填充缺失的RPU组件",
                parameters={
                    "missing_fields": anomaly.missing_fields,
                    "rpu_id": anomaly.rpu_id,
                    "fill_strategy": "context_inference"
                },
                reversible=True,
                estimated_time=20,
                required_resources=["rpu_database_access", "nlp_tools"]
            )
        ]
        
        return RepairSuggestion(
            anomaly_id=anomaly.anomaly_id,
            anomaly_type=anomaly.anomaly_type,
            priority=priority,
            risk_level=risk_level,
            actions=actions,
            rationale="缺失组件会导致RPU不完整，影响分析质量",
            prerequisites=["确认可以从上下文推断缺失信息"],
            side_effects=["推断的组件可能不够准确"],
            validation_steps=[
                "验证填充组件的准确性",
                "检查RPU的完整性"
            ]
        )
    
    def _generate_frequency_outlier_repair(self, anomaly: FrequencyOutlier) -> RepairSuggestion:
        """生成频率离群值的修复建议"""
        priority = self._assess_priority(anomaly.severity, impact_factor=0.6)
        risk_level = RiskLevel.LOW
        
        actions = [
            RepairAction(
                action_type="investigate_frequency_outlier",
                description="调查频率异常的原因",
                parameters={
                    "concept": anomaly.concept,
                    "frequency": anomaly.frequency,
                    "expected_range": anomaly.expected_range,
                    "investigation_method": "data_source_analysis"
                },
                reversible=False,
                estimated_time=30,
                required_resources=["data_analysis_tools"]
            )
        ]
        
        return RepairSuggestion(
            anomaly_id=anomaly.anomaly_id,
            anomaly_type=anomaly.anomaly_type,
            priority=priority,
            risk_level=risk_level,
            actions=actions,
            rationale="频率离群值可能表明数据质量问题或真实的研究热点",
            prerequisites=["确认数据来源的可靠性"],
            side_effects=["可能需要调整统计模型"],
            validation_steps=[
                "验证频率异常的合理性",
                "检查相关概念的分布"
            ]
        )
    
    def _generate_pmi_anomaly_repair(self, anomaly: PMIAnomaly) -> RepairSuggestion:
        """生成PMI异常的修复建议"""
        priority = self._assess_priority(anomaly.severity, impact_factor=0.8)
        risk_level = RiskLevel.MODERATE
        
        actions = [
            RepairAction(
                action_type="recalculate_pmi",
                description="重新计算PMI值",
                parameters={
                    "concept_pair": anomaly.concept_pair,
                    "current_pmi": anomaly.pmi_value,
                    "expected_range": anomaly.expected_range,
                    "calculation_method": "smoothed_pmi"
                },
                reversible=True,
                estimated_time=15,
                required_resources=["statistical_tools"]
            )
        ]
        
        return RepairSuggestion(
            anomaly_id=anomaly.anomaly_id,
            anomaly_type=anomaly.anomaly_type,
            priority=priority,
            risk_level=risk_level,
            actions=actions,
            rationale="PMI异常可能影响创新信号的准确计算",
            prerequisites=["确认共现数据的正确性"],
            side_effects=["可能改变相关的创新分数"],
            validation_steps=[
                "验证重新计算的PMI值",
                "检查创新信号的变化"
            ]
        )
    
    def _generate_entropy_anomaly_repair(self, anomaly: EntropyAnomaly) -> RepairSuggestion:
        """生成熵值异常的修复建议"""
        priority = self._assess_priority(anomaly.severity, impact_factor=0.7)
        risk_level = RiskLevel.MODERATE
        
        actions = [
            RepairAction(
                action_type="recalculate_entropy",
                description="重新计算熵值",
                parameters={
                    "concept": anomaly.concept,
                    "current_entropy": anomaly.entropy_value,
                    "expected_range": anomaly.expected_range,
                    "calculation_method": "shannon_entropy"
                },
                reversible=True,
                estimated_time=10,
                required_resources=["statistical_tools"]
            )
        ]
        
        return RepairSuggestion(
            anomaly_id=anomaly.anomaly_id,
            anomaly_type=anomaly.anomaly_type,
            priority=priority,
            risk_level=risk_level,
            actions=actions,
            rationale="熵值异常可能表明概念分布的问题",
            prerequisites=["确认概念频率数据的准确性"],
            side_effects=["可能影响相关的统计分析"],
            validation_steps=[
                "验证重新计算的熵值",
                "检查概念分布的合理性"
            ]
        )
    
    def _generate_missing_duplicate_repair(self, anomaly: MissingDuplicate) -> RepairSuggestion:
        """生成遗漏重复的修复建议"""
        priority = self._assess_priority(anomaly.severity, impact_factor=0.8)
        risk_level = RiskLevel.MODERATE
        
        actions = [
            RepairAction(
                action_type="merge_similar_concepts",
                description="合并相似的概念",
                parameters={
                    "concept_a": anomaly.concept_a,
                    "concept_b": anomaly.concept_b,
                    "similarity_score": anomaly.similarity_score,
                    "similarity_type": anomaly.similarity_type,
                    "merge_strategy": "semantic_priority"
                },
                reversible=True,
                estimated_time=20,
                required_resources=["mapping_file_access", "semantic_analysis"]
            )
        ]
        
        return RepairSuggestion(
            anomaly_id=anomaly.anomaly_id,
            anomaly_type=anomaly.anomaly_type,
            priority=priority,
            risk_level=risk_level,
            actions=actions,
            rationale="遗漏的重复概念会导致统计分散和创新信号不准确",
            prerequisites=["确认概念的语义等价性"],
            side_effects=["可能需要重新计算相关统计"],
            validation_steps=[
                "验证合并后概念的一致性",
                "检查统计结果的改善"
            ]
        )
    
    def _assess_priority(self, severity: AnomalySeverity, impact_factor: float = 1.0) -> RepairPriority:
        """评估修复优先级
        
        Args:
            severity: 异常严重性
            impact_factor: 影响因子 (0.0-2.0)
            
        Returns:
            RepairPriority: 修复优先级
        """
        base_score = self.priority_weights.get(severity, 1)
        adjusted_score = base_score * impact_factor
        
        if adjusted_score >= 10:
            return RepairPriority.IMMEDIATE
        elif adjusted_score >= 7:
            return RepairPriority.HIGH
        elif adjusted_score >= 4:
            return RepairPriority.MEDIUM
        elif adjusted_score >= 2:
            return RepairPriority.LOW
        else:
            return RepairPriority.DEFERRED
    
    def _get_priority_score(self, suggestion: RepairSuggestion) -> int:
        """获取优先级分数用于排序"""
        priority_scores = {
            RepairPriority.IMMEDIATE: 5,
            RepairPriority.HIGH: 4,
            RepairPriority.MEDIUM: 3,
            RepairPriority.LOW: 2,
            RepairPriority.DEFERRED: 1
        }
        return priority_scores.get(suggestion.priority, 0)
    
    def _generate_case_mapping_updates(self, anomaly: CaseInconsistency) -> Dict[str, str]:
        """生成大小写映射更新"""
        updates = {}
        
        # 将所有变体统一为小写
        for variant in anomaly.source_variants:
            normalized = variant.lower()
            if variant != normalized:
                updates[variant] = normalized
        
        return updates
    
    def record_repair_execution(self, suggestion: RepairSuggestion, 
                              result: str, details: Dict[str, Any]) -> RepairHistory:
        """记录修复执行结果
        
        Args:
            suggestion: 修复建议
            result: 修复结果 (success, failed, partial)
            details: 修复详情
            
        Returns:
            RepairHistory: 修复历史记录
        """
        history = RepairHistory(
            anomaly_id=suggestion.anomaly_id,
            repair_action=f"{len(suggestion.actions)} actions executed",
            repair_timestamp=datetime.now(),
            repair_result=result,
            repair_details=details
        )
        
        self.repair_history.append(history)
        
        self.logger.info(
            f"记录修复执行: 异常 {suggestion.anomaly_id}, "
            f"结果: {result}, 操作数: {len(suggestion.actions)}"
        )
        
        return history
    
    def get_repair_history(self, anomaly_id: Optional[str] = None) -> List[RepairHistory]:
        """获取修复历史
        
        Args:
            anomaly_id: 可选的异常ID，如果提供则只返回该异常的历史
            
        Returns:
            List[RepairHistory]: 修复历史列表
        """
        if anomaly_id:
            return [h for h in self.repair_history if h.anomaly_id == anomaly_id]
        return self.repair_history.copy()
    
    def export_suggestions(self, suggestions: List[RepairSuggestion], 
                          output_path: Path) -> None:
        """导出修复建议到文件
        
        Args:
            suggestions: 修复建议列表
            output_path: 输出文件路径
        """
        try:
            export_data = {
                'generated_at': datetime.now().isoformat(),
                'total_suggestions': len(suggestions),
                'suggestions': [s.to_dict() for s in suggestions]
            }
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"修复建议已导出到: {output_path}")
            
        except Exception as e:
            self.logger.error(f"导出修复建议失败: {e}")
            raise AnomalyDetectionException(f"导出失败: {e}")