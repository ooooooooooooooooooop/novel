"""
统计分布异常检测器

检测统计分布中的异常，包括频率分布离群值、PMI计算异常、熵值异常和共现矩阵稀疏性问题。
"""

import numpy as np
import math
from typing import Dict, List, Tuple, Any, Optional, Set
from collections import defaultdict, Counter
from dataclasses import dataclass
import statistics
from scipy import stats
from scipy.sparse import csr_matrix

from ..core.data_models import (
    Anomaly, AnomalySeverity, FrequencyOutlier, PMIAnomaly, EntropyAnomaly
)
from ..core.exceptions import DetectionLogicException
from ..core.logging import get_logger


@dataclass
class StatisticalData:
    """统计数据基类"""
    concept: str
    frequency: int
    total_count: int


@dataclass
class FrequencyData(StatisticalData):
    """频率数据"""
    relative_frequency: float = 0.0
    
    def __post_init__(self):
        if self.total_count > 0:
            self.relative_frequency = self.frequency / self.total_count


@dataclass
class PMIData:
    """PMI数据"""
    concept_a: str
    concept_b: str
    joint_frequency: int
    frequency_a: int
    frequency_b: int
    total_count: int
    pmi_value: float = 0.0
    
    def __post_init__(self):
        """计算PMI值"""
        if (self.joint_frequency > 0 and self.frequency_a > 0 and 
            self.frequency_b > 0 and self.total_count > 0):
            
            # P(A,B) = joint_frequency / total_count
            p_ab = self.joint_frequency / self.total_count
            # P(A) = frequency_a / total_count
            p_a = self.frequency_a / self.total_count
            # P(B) = frequency_b / total_count
            p_b = self.frequency_b / self.total_count
            
            # PMI = log(P(A,B) / (P(A) * P(B)))
            if p_a * p_b > 0:
                self.pmi_value = math.log(p_ab / (p_a * p_b))
            else:
                self.pmi_value = float('-inf')
        else:
            self.pmi_value = float('-inf')


@dataclass
class EntropyData:
    """熵值数据"""
    concept: str
    distribution: List[float]
    entropy_value: float = 0.0
    
    def __post_init__(self):
        """计算熵值"""
        if self.distribution and sum(self.distribution) > 0:
            # 归一化分布
            total = sum(self.distribution)
            normalized = [p / total for p in self.distribution if p > 0]
            
            # 计算Shannon熵: H = -Σ p_i * log(p_i)
            self.entropy_value = -sum(p * math.log(p) for p in normalized if p > 0)
        else:
            self.entropy_value = 0.0


@dataclass
class CooccurrenceMatrix:
    """共现矩阵数据"""
    concepts: List[str]
    matrix: np.ndarray
    sparsity: float = 0.0
    
    def __post_init__(self):
        """计算稀疏性"""
        if self.matrix.size > 0:
            non_zero_count = np.count_nonzero(self.matrix)
            total_elements = self.matrix.size
            self.sparsity = 1.0 - (non_zero_count / total_elements)
        else:
            self.sparsity = 1.0


@dataclass
class CooccurrenceSparsityAnomaly(Anomaly):
    """共现矩阵稀疏性异常"""
    sparsity_level: float = 0.0
    expected_sparsity: float = 0.0
    matrix_size: int = 0
    
    def __post_init__(self):
        super().__post_init__()
        self.anomaly_type = "cooccurrence_sparsity_anomaly"


class StatisticalDistributionDetector:
    """统计分布异常检测器
    
    检测统计分布中的各类异常情况。
    """
    
    def __init__(self, config):
        """初始化统计分布检测器
        
        Args:
            config: 检测配置
        """
        self.config = config
        self.logger = get_logger(self.__class__.__name__)
        
        # 检测阈值配置 - 从配置对象中读取，避免硬编码经验值
        self.frequency_outlier_z_threshold = getattr(config.thresholds, 'frequency_outlier_z_threshold', 3.0)
        self.pmi_outlier_threshold = getattr(config.thresholds, 'pmi_outlier_threshold', 5.0)
        self.entropy_outlier_z_threshold = getattr(config.thresholds, 'entropy_outlier_z_threshold', 2.5)
        self.sparsity_threshold = getattr(config.thresholds, 'sparsity_threshold', 0.95)
        self.min_frequency_threshold = getattr(config.thresholds, 'min_frequency_threshold', 5)
        
        self.logger.info(f"统计分布检测器初始化完成，阈值配置: "
                        f"频率离群值Z阈值={self.frequency_outlier_z_threshold}, "
                        f"PMI离群值阈值={self.pmi_outlier_threshold}, "
                        f"熵值离群值Z阈值={self.entropy_outlier_z_threshold}, "
                        f"稀疏性阈值={self.sparsity_threshold}")
    
    def detect_frequency_outliers(self, frequency_data: List[FrequencyData]) -> List[FrequencyOutlier]:
        """检测频率分布离群值
        
        Args:
            frequency_data: 频率数据列表
            
        Returns:
            频率离群值异常列表
        """
        anomalies = []
        
        try:
            if len(frequency_data) < 3:
                self.logger.warning("频率数据不足，无法进行离群值检测")
                return anomalies
            
            # 提取频率值
            frequencies = [data.frequency for data in frequency_data]
            
            # 计算统计量
            mean_freq = statistics.mean(frequencies)
            std_freq = statistics.stdev(frequencies) if len(frequencies) > 1 else 0
            
            if std_freq == 0:
                self.logger.warning("频率标准差为0，无法进行Z分数计算")
                return anomalies
            
            # 检测离群值
            for data in frequency_data:
                z_score = (data.frequency - mean_freq) / std_freq
                
                if abs(z_score) > self.frequency_outlier_z_threshold:
                    # 确定异常类型
                    outlier_type = "high_frequency" if z_score > 0 else "low_frequency"
                    
                    anomaly = FrequencyOutlier(
                        severity=self._get_severity_by_z_score(z_score),
                        description=f"检测到频率离群值: 概念='{data.concept}', "
                                  f"频率={data.frequency}, Z分数={z_score:.2f}, "
                                  f"类型={outlier_type}",
                        affected_data={
                            "concept": data.concept,
                            "frequency": data.frequency,
                            "relative_frequency": data.relative_frequency,
                            "z_score": z_score,
                            "outlier_type": outlier_type,
                            "mean_frequency": mean_freq,
                            "std_frequency": std_freq
                        },
                        suggested_fix=self._get_frequency_fix_suggestion(outlier_type, data),
                        concept=data.concept,
                        frequency=data.frequency,
                        expected_range=(mean_freq - 2*std_freq, mean_freq + 2*std_freq),
                        z_score=z_score
                    )
                    anomalies.append(anomaly)
            
            self.logger.debug(f"频率离群值检测完成，发现{len(anomalies)}个异常")
            return anomalies
            
        except Exception as e:
            self.logger.error(f"频率离群值检测失败: {str(e)}")
            raise DetectionLogicException(f"频率离群值检测错误: {str(e)}")
    
    def detect_pmi_anomalies(self, pmi_data: List[PMIData]) -> List[PMIAnomaly]:
        """检测PMI计算异常
        
        Args:
            pmi_data: PMI数据列表
            
        Returns:
            PMI异常列表
        """
        anomalies = []
        
        try:
            if len(pmi_data) < 3:
                self.logger.warning("PMI数据不足，无法进行异常检测")
                return anomalies
            
            # 过滤有效的PMI值（排除-inf）
            valid_pmi_data = [data for data in pmi_data if not math.isinf(data.pmi_value)]
            
            if len(valid_pmi_data) < 3:
                self.logger.warning("有效PMI数据不足，无法进行异常检测")
                return anomalies
            
            # 提取PMI值
            pmi_values = [data.pmi_value for data in valid_pmi_data]
            
            # 计算统计量
            mean_pmi = statistics.mean(pmi_values)
            std_pmi = statistics.stdev(pmi_values) if len(pmi_values) > 1 else 0
            
            # 检测异常PMI值
            for data in valid_pmi_data:
                # 检测极端PMI值
                if abs(data.pmi_value) > self.pmi_outlier_threshold:
                    anomaly_type = "extremely_high_pmi" if data.pmi_value > 0 else "extremely_low_pmi"
                    
                    anomaly = PMIAnomaly(
                        severity=self._get_severity_by_pmi_value(data.pmi_value),
                        description=f"检测到异常PMI值: 概念对=({data.concept_a}, {data.concept_b}), "
                                  f"PMI={data.pmi_value:.4f}, 类型={anomaly_type}",
                        affected_data={
                            "concept_a": data.concept_a,
                            "concept_b": data.concept_b,
                            "pmi_value": data.pmi_value,
                            "joint_frequency": data.joint_frequency,
                            "frequency_a": data.frequency_a,
                            "frequency_b": data.frequency_b,
                            "total_count": data.total_count,
                            "anomaly_type": anomaly_type
                        },
                        suggested_fix=self._get_pmi_fix_suggestion(anomaly_type, data),
                        concept_pair=(data.concept_a, data.concept_b),
                        pmi_value=data.pmi_value,
                        expected_range=(mean_pmi - 2*std_pmi, mean_pmi + 2*std_pmi)
                    )
                    anomalies.append(anomaly)
            
            # 检测无效PMI计算（-inf值）
            invalid_pmi_data = [data for data in pmi_data if math.isinf(data.pmi_value)]
            for data in invalid_pmi_data:
                anomaly = PMIAnomaly(
                    severity=AnomalySeverity.HIGH,
                    description=f"检测到无效PMI计算: 概念对=({data.concept_a}, {data.concept_b}), "
                              f"联合频率={data.joint_frequency}, 个体频率=({data.frequency_a}, {data.frequency_b})",
                    affected_data={
                        "concept_a": data.concept_a,
                        "concept_b": data.concept_b,
                        "pmi_value": data.pmi_value,
                        "joint_frequency": data.joint_frequency,
                        "frequency_a": data.frequency_a,
                        "frequency_b": data.frequency_b,
                        "total_count": data.total_count,
                        "anomaly_type": "invalid_pmi_calculation"
                    },
                    suggested_fix="检查频率计算逻辑，确保联合频率和个体频率的正确性",
                    concept_pair=(data.concept_a, data.concept_b),
                    pmi_value=data.pmi_value,
                    expected_range=(float('-inf'), float('inf'))
                )
                anomalies.append(anomaly)
            
            self.logger.debug(f"PMI异常检测完成，发现{len(anomalies)}个异常")
            return anomalies
            
        except Exception as e:
            self.logger.error(f"PMI异常检测失败: {str(e)}")
            raise DetectionLogicException(f"PMI异常检测错误: {str(e)}")
    
    def detect_entropy_anomalies(self, entropy_data: List[EntropyData]) -> List[EntropyAnomaly]:
        """检测熵值异常
        
        Args:
            entropy_data: 熵值数据列表
            
        Returns:
            熵值异常列表
        """
        anomalies = []
        
        try:
            if len(entropy_data) < 3:
                self.logger.warning("熵值数据不足，无法进行异常检测")
                return anomalies
            
            # 提取熵值
            entropy_values = [data.entropy_value for data in entropy_data]
            
            # 计算统计量
            mean_entropy = statistics.mean(entropy_values)
            std_entropy = statistics.stdev(entropy_values) if len(entropy_values) > 1 else 0
            
            if std_entropy == 0:
                self.logger.warning("熵值标准差为0，无法进行Z分数计算")
                return anomalies
            
            # 检测熵值异常
            for data in entropy_data:
                z_score = (data.entropy_value - mean_entropy) / std_entropy
                
                if abs(z_score) > self.entropy_outlier_z_threshold:
                    anomaly_type = "high_entropy" if z_score > 0 else "low_entropy"
                    
                    anomaly = EntropyAnomaly(
                        severity=self._get_severity_by_z_score(z_score),
                        description=f"检测到熵值异常: 概念='{data.concept}', "
                                  f"熵值={data.entropy_value:.4f}, Z分数={z_score:.2f}, "
                                  f"类型={anomaly_type}",
                        affected_data={
                            "concept": data.concept,
                            "entropy_value": data.entropy_value,
                            "distribution_size": len(data.distribution),
                            "z_score": z_score,
                            "anomaly_type": anomaly_type,
                            "mean_entropy": mean_entropy,
                            "std_entropy": std_entropy
                        },
                        suggested_fix=self._get_entropy_fix_suggestion(anomaly_type, data),
                        concept=data.concept,
                        entropy_value=data.entropy_value,
                        expected_range=(mean_entropy - 2*std_entropy, mean_entropy + 2*std_entropy)
                    )
                    anomalies.append(anomaly)
            
            self.logger.debug(f"熵值异常检测完成，发现{len(anomalies)}个异常")
            return anomalies
            
        except Exception as e:
            self.logger.error(f"熵值异常检测失败: {str(e)}")
            raise DetectionLogicException(f"熵值异常检测错误: {str(e)}")
    
    def detect_cooccurrence_sparsity_anomalies(self, cooccurrence_data: CooccurrenceMatrix) -> List[CooccurrenceSparsityAnomaly]:
        """检测共现矩阵稀疏性异常
        
        Args:
            cooccurrence_data: 共现矩阵数据
            
        Returns:
            共现矩阵稀疏性异常列表
        """
        anomalies = []
        
        try:
            if cooccurrence_data.matrix.size == 0:
                self.logger.warning("共现矩阵为空，无法进行稀疏性检测")
                return anomalies
            
            # 检测过度稀疏
            if cooccurrence_data.sparsity > self.sparsity_threshold:
                anomaly = CooccurrenceSparsityAnomaly(
                    severity=self._get_severity_by_sparsity(cooccurrence_data.sparsity),
                    description=f"检测到共现矩阵过度稀疏: 稀疏性={cooccurrence_data.sparsity:.4f}, "
                              f"阈值={self.sparsity_threshold}, 矩阵大小={cooccurrence_data.matrix.shape}",
                    affected_data={
                        "sparsity_level": cooccurrence_data.sparsity,
                        "matrix_shape": cooccurrence_data.matrix.shape,
                        "total_elements": cooccurrence_data.matrix.size,
                        "non_zero_elements": np.count_nonzero(cooccurrence_data.matrix),
                        "concept_count": len(cooccurrence_data.concepts)
                    },
                    suggested_fix="检查数据收集过程，验证概念共现关系的计算逻辑，考虑增加数据量或调整概念粒度",
                    sparsity_level=cooccurrence_data.sparsity,
                    expected_sparsity=self.sparsity_threshold,
                    matrix_size=cooccurrence_data.matrix.size
                )
                anomalies.append(anomaly)
            
            # 检测矩阵结构异常
            structure_anomalies = self._detect_matrix_structure_anomalies(cooccurrence_data)
            anomalies.extend(structure_anomalies)
            
            self.logger.debug(f"共现矩阵稀疏性检测完成，发现{len(anomalies)}个异常")
            return anomalies
            
        except Exception as e:
            self.logger.error(f"共现矩阵稀疏性检测失败: {str(e)}")
            raise DetectionLogicException(f"共现矩阵稀疏性检测错误: {str(e)}")
    
    def detect_anomalies(self, statistical_data: Dict[str, Any]) -> List[Anomaly]:
        """检测统计分布异常
        
        Args:
            statistical_data: 包含各种统计数据的字典
            
        Returns:
            检测到的异常列表
        """
        try:
            anomalies = []
            
            # 检测频率分布离群值
            if 'frequency_data' in statistical_data:
                frequency_anomalies = self.detect_frequency_outliers(statistical_data['frequency_data'])
                anomalies.extend(frequency_anomalies)
            
            # 检测PMI异常
            if 'pmi_data' in statistical_data:
                pmi_anomalies = self.detect_pmi_anomalies(statistical_data['pmi_data'])
                anomalies.extend(pmi_anomalies)
            
            # 检测熵值异常
            if 'entropy_data' in statistical_data:
                entropy_anomalies = self.detect_entropy_anomalies(statistical_data['entropy_data'])
                anomalies.extend(entropy_anomalies)
            
            # 检测共现矩阵稀疏性异常
            if 'cooccurrence_data' in statistical_data:
                sparsity_anomalies = self.detect_cooccurrence_sparsity_anomalies(statistical_data['cooccurrence_data'])
                anomalies.extend(sparsity_anomalies)
            
            self.logger.info(f"统计分布异常检测完成，共检测到{len(anomalies)}个异常")
            return anomalies
            
        except Exception as e:
            self.logger.error(f"统计分布异常检测失败: {str(e)}")
            raise DetectionLogicException(f"统计分布检测错误: {str(e)}")
    
    def _detect_matrix_structure_anomalies(self, cooccurrence_data: CooccurrenceMatrix) -> List[CooccurrenceSparsityAnomaly]:
        """检测矩阵结构异常
        
        Args:
            cooccurrence_data: 共现矩阵数据
            
        Returns:
            矩阵结构异常列表
        """
        anomalies = []
        
        # 检测矩阵对称性（共现矩阵应该是对称的）
        if cooccurrence_data.matrix.shape[0] == cooccurrence_data.matrix.shape[1]:
            if not np.allclose(cooccurrence_data.matrix, cooccurrence_data.matrix.T, rtol=1e-5):
                anomaly = CooccurrenceSparsityAnomaly(
                    severity=AnomalySeverity.HIGH,
                    description="检测到共现矩阵不对称，可能存在计算错误",
                    affected_data={
                        "matrix_shape": cooccurrence_data.matrix.shape,
                        "symmetry_error": "matrix_not_symmetric"
                    },
                    suggested_fix="检查共现矩阵计算逻辑，确保矩阵的对称性",
                    sparsity_level=cooccurrence_data.sparsity,
                    expected_sparsity=cooccurrence_data.sparsity,
                    matrix_size=cooccurrence_data.matrix.size
                )
                anomalies.append(anomaly)
        
        # 检测对角线异常（对角线元素通常应该是最大的）
        if cooccurrence_data.matrix.shape[0] == cooccurrence_data.matrix.shape[1]:
            diagonal = np.diag(cooccurrence_data.matrix)
            if len(diagonal) > 0 and np.any(diagonal == 0):
                zero_diagonal_count = np.sum(diagonal == 0)
                anomaly = CooccurrenceSparsityAnomaly(
                    severity=AnomalySeverity.MEDIUM,
                    description=f"检测到{zero_diagonal_count}个概念的自共现为0，可能存在数据缺失",
                    affected_data={
                        "zero_diagonal_count": int(zero_diagonal_count),
                        "total_concepts": len(diagonal),
                        "diagonal_error": "zero_self_cooccurrence"
                    },
                    suggested_fix="检查概念自共现的计算逻辑，验证数据完整性",
                    sparsity_level=cooccurrence_data.sparsity,
                    expected_sparsity=cooccurrence_data.sparsity,
                    matrix_size=cooccurrence_data.matrix.size
                )
                anomalies.append(anomaly)
        
        return anomalies
    
    def _get_frequency_fix_suggestion(self, outlier_type: str, data: FrequencyData) -> str:
        """获取频率异常的修复建议
        
        Args:
            outlier_type: 异常类型
            data: 频率数据
            
        Returns:
            修复建议
        """
        if outlier_type == "high_frequency":
            return (f"概念'{data.concept}'频率异常高({data.frequency})，"
                   "建议检查是否存在重复计算或数据质量问题")
        else:
            return (f"概念'{data.concept}'频率异常低({data.frequency})，"
                   "建议检查是否存在数据缺失或提取不完整问题")
    
    def _get_pmi_fix_suggestion(self, anomaly_type: str, data: PMIData) -> str:
        """获取PMI异常的修复建议
        
        Args:
            anomaly_type: 异常类型
            data: PMI数据
            
        Returns:
            修复建议
        """
        if anomaly_type == "extremely_high_pmi":
            return (f"概念对({data.concept_a}, {data.concept_b})的PMI值异常高({data.pmi_value:.4f})，"
                   "建议检查联合频率计算是否正确，或概念是否过度相关")
        elif anomaly_type == "extremely_low_pmi":
            return (f"概念对({data.concept_a}, {data.concept_b})的PMI值异常低({data.pmi_value:.4f})，"
                   "建议检查是否存在负相关或计算错误")
        else:
            return "检查PMI计算的输入数据，确保频率统计的准确性"
    
    def _get_entropy_fix_suggestion(self, anomaly_type: str, data: EntropyData) -> str:
        """获取熵值异常的修复建议
        
        Args:
            anomaly_type: 异常类型
            data: 熵值数据
            
        Returns:
            修复建议
        """
        if anomaly_type == "high_entropy":
            return (f"概念'{data.concept}'的熵值异常高({data.entropy_value:.4f})，"
                   "表示分布过于均匀，建议检查数据聚合逻辑")
        else:
            return (f"概念'{data.concept}'的熵值异常低({data.entropy_value:.4f})，"
                   "表示分布过于集中，建议检查是否存在数据偏斜")
    
    def _get_severity_by_z_score(self, z_score: float) -> AnomalySeverity:
        """根据Z分数确定异常严重性
        
        Args:
            z_score: Z分数
            
        Returns:
            异常严重性级别
        """
        abs_z = abs(z_score)
        if abs_z >= 5.0:
            return AnomalySeverity.CRITICAL
        elif abs_z >= 4.0:
            return AnomalySeverity.HIGH
        elif abs_z >= 3.0:
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW
    
    def _get_severity_by_pmi_value(self, pmi_value: float) -> AnomalySeverity:
        """根据PMI值确定异常严重性
        
        Args:
            pmi_value: PMI值
            
        Returns:
            异常严重性级别
        """
        abs_pmi = abs(pmi_value)
        if abs_pmi >= 10.0:
            return AnomalySeverity.CRITICAL
        elif abs_pmi >= 7.0:
            return AnomalySeverity.HIGH
        elif abs_pmi >= 5.0:
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW
    
    def _get_severity_by_sparsity(self, sparsity: float) -> AnomalySeverity:
        """根据稀疏性确定异常严重性
        
        Args:
            sparsity: 稀疏性值
            
        Returns:
            异常严重性级别
        """
        if sparsity >= 0.99:
            return AnomalySeverity.CRITICAL
        elif sparsity >= 0.98:
            return AnomalySeverity.HIGH
        elif sparsity >= 0.95:
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW
    
    def get_detector_name(self) -> str:
        """获取检测器名称"""
        return "StatisticalDistributionDetector"
    
    def get_supported_data_types(self) -> List[str]:
        """获取支持的数据类型"""
        return ["frequency_data", "pmi_data", "entropy_data", "cooccurrence_data", "statistical_distributions"]