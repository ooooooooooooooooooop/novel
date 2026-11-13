"""
时间序列异常检测器

检测创新信号时间序列中的异常，包括峰谷值异常、时间因果性违反、趋势突变等。
"""

import numpy as np
from typing import Dict, List, Tuple, Any, Optional
from collections import defaultdict
from datetime import datetime, timedelta
from dataclasses import dataclass
import statistics

from ..core.data_models import (
    Anomaly, AnomalySeverity, DetectionResult
)
from ..core.exceptions import DetectionLogicException
from ..core.logging import get_logger


@dataclass
class TimeSeriesPoint:
    """时间序列数据点"""
    timestamp: datetime
    value: float
    paper_id: str = ""
    concept: str = ""
    signal_type: str = ""  # peak_novelty, synergy_novelty, modifier_bonus


@dataclass
class PeakValleyAnomaly(Anomaly):
    """峰谷值异常"""
    peak_value: float = 0.0
    valley_value: float = 0.0
    expected_range: Tuple[float, float] = (0.0, 0.0)
    z_score: float = 0.0
    
    def __post_init__(self):
        super().__post_init__()
        self.anomaly_type = "peak_valley_anomaly"


@dataclass
class CausalityViolation(Anomaly):
    """时间因果性违反异常"""
    earlier_timestamp: datetime = None
    later_timestamp: datetime = None
    violation_type: str = ""  # future_reference, retroactive_change
    
    def __post_init__(self):
        super().__post_init__()
        self.anomaly_type = "causality_violation"


@dataclass
class TrendAnomalyDetection(Anomaly):
    """趋势突变异常"""
    change_point: datetime = None
    before_trend: float = 0.0
    after_trend: float = 0.0
    change_magnitude: float = 0.0
    
    def __post_init__(self):
        super().__post_init__()
        self.anomaly_type = "trend_anomaly"


@dataclass
class StateInconsistency(Anomaly):
    """状态不一致异常"""
    expected_state: Dict[str, Any] = None
    actual_state: Dict[str, Any] = None
    inconsistency_fields: List[str] = None
    
    def __post_init__(self):
        super().__post_init__()
        self.anomaly_type = "state_inconsistency"
        if self.expected_state is None:
            self.expected_state = {}
        if self.actual_state is None:
            self.actual_state = {}
        if self.inconsistency_fields is None:
            self.inconsistency_fields = []


class TimeSeriesDetector:
    """时间序列异常检测器
    
    检测创新信号时间序列中的各类异常情况。
    """
    
    def __init__(self, config):
        """初始化时间序列检测器
        
        Args:
            config: 检测配置
        """
        self.config = config
        self.logger = get_logger(self.__class__.__name__)
        
        # 检测阈值配置 - 从配置对象中读取，避免硬编码经验值
        self.peak_valley_z_threshold = getattr(config.thresholds, 'peak_valley_z_threshold', 3.0)
        self.trend_change_threshold = getattr(config.thresholds, 'trend_change_threshold', 2.0)
        self.causality_window_hours = getattr(config.thresholds, 'causality_window_hours', 24)
        self.min_data_points = getattr(config.thresholds, 'min_data_points', 10)
        
        self.logger.info(f"时间序列检测器初始化完成，阈值配置: "
                        f"峰谷Z分数阈值={self.peak_valley_z_threshold}, "
                        f"趋势变化阈值={self.trend_change_threshold}, "
                        f"因果性窗口={self.causality_window_hours}小时")
    
    def detect_anomalies(self, time_series_data: List[TimeSeriesPoint]) -> List[Anomaly]:
        """检测时间序列异常
        
        Args:
            time_series_data: 时间序列数据点列表
            
        Returns:
            检测到的异常列表
        """
        try:
            anomalies = []
            
            if len(time_series_data) < self.min_data_points:
                self.logger.warning(f"数据点不足，需要至少{self.min_data_points}个点，当前{len(time_series_data)}个")
                return anomalies
            
            # 按时间排序
            sorted_data = sorted(time_series_data, key=lambda x: x.timestamp)
            
            # 检测峰谷值异常
            peak_valley_anomalies = self.detect_peak_valley_anomalies(sorted_data)
            anomalies.extend(peak_valley_anomalies)
            
            # 检测时间因果性违反
            causality_anomalies = self.detect_causality_violations(sorted_data)
            anomalies.extend(causality_anomalies)
            
            # 检测趋势突变
            trend_anomalies = self.detect_trend_anomalies(sorted_data)
            anomalies.extend(trend_anomalies)
            
            # 检测状态不一致
            state_anomalies = self.detect_state_inconsistencies(sorted_data)
            anomalies.extend(state_anomalies)
            
            self.logger.info(f"时间序列异常检测完成，共检测到{len(anomalies)}个异常")
            return anomalies
            
        except Exception as e:
            self.logger.error(f"时间序列异常检测失败: {str(e)}")
            raise DetectionLogicException(f"时间序列检测错误: {str(e)}")
    
    def detect_peak_valley_anomalies(self, sorted_data: List[TimeSeriesPoint]) -> List[PeakValleyAnomaly]:
        """检测峰谷值异常
        
        Args:
            sorted_data: 按时间排序的数据点
            
        Returns:
            峰谷值异常列表
        """
        anomalies = []
        
        try:
            # 提取数值序列
            values = [point.value for point in sorted_data]
            
            if len(values) < 3:
                return anomalies
            
            # 计算统计量
            mean_val = statistics.mean(values)
            std_val = statistics.stdev(values) if len(values) > 1 else 0
            
            if std_val == 0:
                self.logger.warning("标准差为0，无法进行峰谷值检测")
                return anomalies
            
            # 寻找局部极值点
            peaks, valleys = self._find_local_extrema(values)
            
            # 检测异常峰值
            for peak_idx in peaks:
                z_score = (values[peak_idx] - mean_val) / std_val
                if abs(z_score) > self.peak_valley_z_threshold:
                    anomaly = PeakValleyAnomaly(
                        severity=self._get_severity_by_z_score(z_score),
                        description=f"检测到异常峰值: 时间={sorted_data[peak_idx].timestamp}, "
                                  f"值={values[peak_idx]:.4f}, Z分数={z_score:.2f}",
                        affected_data={
                            "timestamp": sorted_data[peak_idx].timestamp.isoformat(),
                            "value": values[peak_idx],
                            "paper_id": sorted_data[peak_idx].paper_id,
                            "concept": sorted_data[peak_idx].concept,
                            "signal_type": sorted_data[peak_idx].signal_type
                        },
                        suggested_fix="检查该时间点的数据计算逻辑，验证创新信号计算是否正确",
                        peak_value=values[peak_idx],
                        expected_range=(mean_val - 2*std_val, mean_val + 2*std_val),
                        z_score=z_score
                    )
                    anomalies.append(anomaly)
            
            # 检测异常谷值
            for valley_idx in valleys:
                z_score = (values[valley_idx] - mean_val) / std_val
                if abs(z_score) > self.peak_valley_z_threshold:
                    anomaly = PeakValleyAnomaly(
                        severity=self._get_severity_by_z_score(z_score),
                        description=f"检测到异常谷值: 时间={sorted_data[valley_idx].timestamp}, "
                                  f"值={values[valley_idx]:.4f}, Z分数={z_score:.2f}",
                        affected_data={
                            "timestamp": sorted_data[valley_idx].timestamp.isoformat(),
                            "value": values[valley_idx],
                            "paper_id": sorted_data[valley_idx].paper_id,
                            "concept": sorted_data[valley_idx].concept,
                            "signal_type": sorted_data[valley_idx].signal_type
                        },
                        suggested_fix="检查该时间点的数据计算逻辑，验证创新信号计算是否正确",
                        valley_value=values[valley_idx],
                        expected_range=(mean_val - 2*std_val, mean_val + 2*std_val),
                        z_score=z_score
                    )
                    anomalies.append(anomaly)
            
            self.logger.debug(f"峰谷值检测完成，发现{len(anomalies)}个异常")
            return anomalies
            
        except Exception as e:
            self.logger.error(f"峰谷值检测失败: {str(e)}")
            raise DetectionLogicException(f"峰谷值检测错误: {str(e)}")
    
    def detect_causality_violations(self, sorted_data: List[TimeSeriesPoint]) -> List[CausalityViolation]:
        """检测时间因果性违反
        
        Args:
            sorted_data: 按时间排序的数据点
            
        Returns:
            因果性违反异常列表
        """
        anomalies = []
        
        try:
            # 检查时间序列是否严格递增
            for i in range(1, len(sorted_data)):
                current_time = sorted_data[i].timestamp
                previous_time = sorted_data[i-1].timestamp
                
                if current_time <= previous_time:
                    anomaly = CausalityViolation(
                        severity=AnomalySeverity.HIGH,
                        description=f"检测到时间因果性违反: 当前时间{current_time} <= 前一时间{previous_time}",
                        affected_data={
                            "current_timestamp": current_time.isoformat(),
                            "previous_timestamp": previous_time.isoformat(),
                            "current_paper": sorted_data[i].paper_id,
                            "previous_paper": sorted_data[i-1].paper_id
                        },
                        suggested_fix="检查数据时间戳的正确性，确保创新计算严格按时间顺序进行",
                        earlier_timestamp=previous_time,
                        later_timestamp=current_time,
                        violation_type="time_order_violation"
                    )
                    anomalies.append(anomaly)
            
            # 检查未来引用（在创新计算中使用了未来的数据）
            future_reference_anomalies = self._detect_future_references(sorted_data)
            anomalies.extend(future_reference_anomalies)
            
            # 检查追溯性变更（历史状态的不当修改）
            retroactive_anomalies = self._detect_retroactive_changes(sorted_data)
            anomalies.extend(retroactive_anomalies)
            
            self.logger.debug(f"因果性检测完成，发现{len(anomalies)}个异常")
            return anomalies
            
        except Exception as e:
            self.logger.error(f"因果性检测失败: {str(e)}")
            raise DetectionLogicException(f"因果性检测错误: {str(e)}")
    
    def detect_trend_anomalies(self, sorted_data: List[TimeSeriesPoint]) -> List[TrendAnomalyDetection]:
        """检测趋势突变异常
        
        Args:
            sorted_data: 按时间排序的数据点
            
        Returns:
            趋势突变异常列表
        """
        anomalies = []
        
        try:
            if len(sorted_data) < 6:  # 需要足够的点来检测趋势变化
                return anomalies
            
            values = [point.value for point in sorted_data]
            
            # 使用滑动窗口检测趋势变化
            window_size = min(len(values) // 3, 10)  # 经验值：窗口大小为数据长度的1/3，最大10
            
            for i in range(window_size, len(values) - window_size):
                # 计算前后窗口的趋势
                before_window = values[i-window_size:i]
                after_window = values[i:i+window_size]
                
                before_trend = self._calculate_trend(before_window)
                after_trend = self._calculate_trend(after_window)
                
                # 检测趋势突变
                trend_change = abs(after_trend - before_trend)
                
                if trend_change > self.trend_change_threshold:
                    anomaly = TrendAnomalyDetection(
                        severity=self._get_severity_by_trend_change(trend_change),
                        description=f"检测到趋势突变: 时间={sorted_data[i].timestamp}, "
                                  f"前趋势={before_trend:.4f}, 后趋势={after_trend:.4f}, "
                                  f"变化幅度={trend_change:.4f}",
                        affected_data={
                            "change_timestamp": sorted_data[i].timestamp.isoformat(),
                            "before_trend": before_trend,
                            "after_trend": after_trend,
                            "change_magnitude": trend_change,
                            "window_size": window_size
                        },
                        suggested_fix="检查该时间点前后的数据处理逻辑，验证是否存在算法变更或数据质量问题",
                        change_point=sorted_data[i].timestamp,
                        before_trend=before_trend,
                        after_trend=after_trend,
                        change_magnitude=trend_change
                    )
                    anomalies.append(anomaly)
            
            self.logger.debug(f"趋势检测完成，发现{len(anomalies)}个异常")
            return anomalies
            
        except Exception as e:
            self.logger.error(f"趋势检测失败: {str(e)}")
            raise DetectionLogicException(f"趋势检测错误: {str(e)}")
    
    def detect_state_inconsistencies(self, sorted_data: List[TimeSeriesPoint]) -> List[StateInconsistency]:
        """检测状态不一致异常
        
        Args:
            sorted_data: 按时间排序的数据点
            
        Returns:
            状态不一致异常列表
        """
        anomalies = []
        
        try:
            # 按概念分组检测状态一致性
            concept_groups = defaultdict(list)
            for point in sorted_data:
                if point.concept:
                    concept_groups[point.concept].append(point)
            
            for concept, points in concept_groups.items():
                if len(points) < 2:
                    continue
                
                # 检测同一概念在相近时间的状态不一致
                state_anomalies = self._detect_concept_state_inconsistencies(concept, points)
                anomalies.extend(state_anomalies)
            
            # 检测全局状态不一致
            global_anomalies = self._detect_global_state_inconsistencies(sorted_data)
            anomalies.extend(global_anomalies)
            
            self.logger.debug(f"状态一致性检测完成，发现{len(anomalies)}个异常")
            return anomalies
            
        except Exception as e:
            self.logger.error(f"状态一致性检测失败: {str(e)}")
            raise DetectionLogicException(f"状态一致性检测错误: {str(e)}")
    
    def _find_local_extrema(self, values: List[float]) -> Tuple[List[int], List[int]]:
        """寻找局部极值点
        
        Args:
            values: 数值序列
            
        Returns:
            (峰值索引列表, 谷值索引列表)
        """
        peaks = []
        valleys = []
        
        for i in range(1, len(values) - 1):
            if values[i] > values[i-1] and values[i] > values[i+1]:
                peaks.append(i)
            elif values[i] < values[i-1] and values[i] < values[i+1]:
                valleys.append(i)
        
        return peaks, valleys
    
    def _calculate_trend(self, values: List[float]) -> float:
        """计算趋势（简单线性回归斜率）
        
        Args:
            values: 数值序列
            
        Returns:
            趋势值（斜率）
        """
        if len(values) < 2:
            return 0.0
        
        n = len(values)
        x = list(range(n))
        
        # 计算线性回归斜率
        sum_x = sum(x)
        sum_y = sum(values)
        sum_xy = sum(x[i] * values[i] for i in range(n))
        sum_x2 = sum(xi * xi for xi in x)
        
        denominator = n * sum_x2 - sum_x * sum_x
        if denominator == 0:
            return 0.0
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        return slope
    
    def _detect_future_references(self, sorted_data: List[TimeSeriesPoint]) -> List[CausalityViolation]:
        """检测未来引用异常
        
        Args:
            sorted_data: 按时间排序的数据点
            
        Returns:
            未来引用异常列表
        """
        anomalies = []
        
        # 这里可以实现更复杂的未来引用检测逻辑
        # 例如检查创新计算中是否使用了未来时间的数据
        
        return anomalies
    
    def _detect_retroactive_changes(self, sorted_data: List[TimeSeriesPoint]) -> List[CausalityViolation]:
        """检测追溯性变更异常
        
        Args:
            sorted_data: 按时间排序的数据点
            
        Returns:
            追溯性变更异常列表
        """
        anomalies = []
        
        # 这里可以实现检测历史状态不当修改的逻辑
        # 例如检查是否有对过去时间点数据的修改
        
        return anomalies
    
    def _detect_concept_state_inconsistencies(self, concept: str, points: List[TimeSeriesPoint]) -> List[StateInconsistency]:
        """检测概念状态不一致
        
        Args:
            concept: 概念名称
            points: 该概念的时间序列点
            
        Returns:
            状态不一致异常列表
        """
        anomalies = []
        
        # 检测同一概念在相近时间的值是否存在不合理的跳跃
        sorted_points = sorted(points, key=lambda x: x.timestamp)
        
        for i in range(1, len(sorted_points)):
            current = sorted_points[i]
            previous = sorted_points[i-1]
            
            time_diff = (current.timestamp - previous.timestamp).total_seconds() / 3600  # 小时
            value_diff = abs(current.value - previous.value)
            
            # 如果时间间隔很短但值变化很大，可能存在状态不一致
            if time_diff < self.causality_window_hours and value_diff > 1.0:  # 经验值：1.0为值变化阈值
                anomaly = StateInconsistency(
                    severity=AnomalySeverity.MEDIUM,
                    description=f"概念'{concept}'在短时间内值变化过大: "
                              f"时间间隔={time_diff:.2f}小时, 值变化={value_diff:.4f}",
                    affected_data={
                        "concept": concept,
                        "previous_timestamp": previous.timestamp.isoformat(),
                        "current_timestamp": current.timestamp.isoformat(),
                        "previous_value": previous.value,
                        "current_value": current.value,
                        "time_diff_hours": time_diff,
                        "value_diff": value_diff
                    },
                    suggested_fix="检查该概念在相近时间的计算逻辑，验证状态更新的合理性",
                    expected_state={"value_change": "gradual"},
                    actual_state={"value_change": "abrupt"},
                    inconsistency_fields=["value"]
                )
                anomalies.append(anomaly)
        
        return anomalies
    
    def _detect_global_state_inconsistencies(self, sorted_data: List[TimeSeriesPoint]) -> List[StateInconsistency]:
        """检测全局状态不一致
        
        Args:
            sorted_data: 按时间排序的数据点
            
        Returns:
            全局状态不一致异常列表
        """
        anomalies = []
        
        # 检测全局统计量的异常变化
        # 例如检查整体创新信号的分布是否在某个时间点发生了不合理的变化
        
        return anomalies
    
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
    
    def _get_severity_by_trend_change(self, change_magnitude: float) -> AnomalySeverity:
        """根据趋势变化幅度确定异常严重性
        
        Args:
            change_magnitude: 趋势变化幅度
            
        Returns:
            异常严重性级别
        """
        if change_magnitude >= 5.0:
            return AnomalySeverity.CRITICAL
        elif change_magnitude >= 3.0:
            return AnomalySeverity.HIGH
        elif change_magnitude >= 2.0:
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW
    
    def get_detector_name(self) -> str:
        """获取检测器名称"""
        return "TimeSeriesDetector"
    
    def get_supported_data_types(self) -> List[str]:
        """获取支持的数据类型"""
        return ["time_series", "innovation_signals", "temporal_data"]