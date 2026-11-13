"""
报告生成和导出系统

创建结构化报告生成器，实现多格式导出功能(JSON, Excel, HTML)，
添加统计分析和可视化支持。
"""

import json
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging
from collections import defaultdict, Counter
import base64
import io

from ..core.data_models import (
    DetectionResult, Anomaly, AnomalySeverity, DetectionSession,
    ProcessingStatus, RepairHistory
)
from ..core.exceptions import AnomalyDetectionException
from .progress_monitor import ProgressSnapshot, Notification, PerformanceMetric


class ReportFormat(Enum):
    """报告格式"""
    JSON = "json"
    EXCEL = "excel"
    HTML = "html"
    CSV = "csv"
    PDF = "pdf"


class ChartType(Enum):
    """图表类型"""
    BAR = "bar"
    PIE = "pie"
    LINE = "line"
    HISTOGRAM = "histogram"
    SCATTER = "scatter"


@dataclass
class ReportSection:
    """报告章节"""
    title: str
    content: str
    data: Optional[Dict[str, Any]] = None
    charts: List[Dict[str, Any]] = field(default_factory=list)
    subsections: List['ReportSection'] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'title': self.title,
            'content': self.content,
            'data': self.data,
            'charts': self.charts,
            'subsections': [sub.to_dict() for sub in self.subsections]
        }


@dataclass
class ReportMetadata:
    """报告元数据"""
    title: str
    description: str
    generated_at: datetime
    session_id: str
    generator_version: str = "1.0.0"
    author: str = "异常检测系统"
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'title': self.title,
            'description': self.description,
            'generated_at': self.generated_at.isoformat(),
            'session_id': self.session_id,
            'generator_version': self.generator_version,
            'author': self.author,
            'tags': self.tags
        }


@dataclass
class DetectionReport:
    """检测报告"""
    metadata: ReportMetadata
    executive_summary: str
    sections: List[ReportSection]
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'metadata': self.metadata.to_dict(),
            'executive_summary': self.executive_summary,
            'sections': [section.to_dict() for section in self.sections],
            'raw_data': self.raw_data
        }


class StatisticalAnalyzer:
    """统计分析器
    
    对检测结果进行统计分析，生成趋势和分布信息。
    """
    
    def __init__(self):
        """初始化统计分析器"""
        self.logger = logging.getLogger(__name__)
    
    def analyze_anomaly_distribution(self, anomalies: List[DetectionResult]) -> Dict[str, Any]:
        """分析异常分布
        
        Args:
            anomalies: 异常检测结果列表
            
        Returns:
            Dict[str, Any]: 分布分析结果
        """
        if not anomalies:
            return {
                'total_count': 0,
                'by_type': {},
                'by_severity': {},
                'by_detector': {},
                'temporal_distribution': {}
            }
        
        # 按类型分布
        type_counts = Counter(anomaly.anomaly_type for anomaly in anomalies)
        
        # 按严重性分布
        severity_counts = Counter(anomaly.severity.value for anomaly in anomalies)
        
        # 按检测器分布
        detector_counts = Counter(anomaly.detector_name for anomaly in anomalies)
        
        # 时间分布（按小时）
        temporal_counts = defaultdict(int)
        for anomaly in anomalies:
            hour_key = anomaly.detection_timestamp.strftime('%Y-%m-%d %H:00')
            temporal_counts[hour_key] += 1
        
        return {
            'total_count': len(anomalies),
            'by_type': dict(type_counts),
            'by_severity': dict(severity_counts),
            'by_detector': dict(detector_counts),
            'temporal_distribution': dict(temporal_counts)
        }
    
    def analyze_confidence_distribution(self, anomalies: List[DetectionResult]) -> Dict[str, Any]:
        """分析置信度分布
        
        Args:
            anomalies: 异常检测结果列表
            
        Returns:
            Dict[str, Any]: 置信度分析结果
        """
        if not anomalies:
            return {
                'mean': 0.0,
                'median': 0.0,
                'std': 0.0,
                'min': 0.0,
                'max': 0.0,
                'histogram': {}
            }
        
        confidence_scores = [anomaly.confidence_score for anomaly in anomalies]
        
        # 基本统计
        mean_confidence = sum(confidence_scores) / len(confidence_scores)
        sorted_scores = sorted(confidence_scores)
        median_confidence = sorted_scores[len(sorted_scores) // 2]
        
        # 标准差计算
        variance = sum((x - mean_confidence) ** 2 for x in confidence_scores) / len(confidence_scores)
        std_confidence = variance ** 0.5
        
        # 直方图（10个区间）
        histogram = defaultdict(int)
        for score in confidence_scores:
            bin_index = min(int(score * 10), 9)  # 0.0-0.1 -> bin 0, 0.1-0.2 -> bin 1, etc.
            bin_range = f"{bin_index/10:.1f}-{(bin_index+1)/10:.1f}"
            histogram[bin_range] += 1
        
        return {
            'mean': mean_confidence,
            'median': median_confidence,
            'std': std_confidence,
            'min': min(confidence_scores),
            'max': max(confidence_scores),
            'histogram': dict(histogram)
        }
    
    def analyze_performance_trends(self, snapshots: List[ProgressSnapshot]) -> Dict[str, Any]:
        """分析性能趋势
        
        Args:
            snapshots: 进度快照列表
            
        Returns:
            Dict[str, Any]: 性能趋势分析
        """
        if not snapshots:
            return {
                'processing_rate_trend': [],
                'memory_usage_trend': [],
                'cpu_usage_trend': [],
                'average_processing_rate': 0.0,
                'peak_memory_usage': 0.0,
                'peak_cpu_usage': 0.0
            }
        
        # 时间序列数据
        processing_rate_trend = [
            {'timestamp': s.timestamp.isoformat(), 'value': s.processing_rate}
            for s in snapshots
        ]
        
        memory_usage_trend = [
            {'timestamp': s.timestamp.isoformat(), 'value': s.memory_usage_mb}
            for s in snapshots
        ]
        
        cpu_usage_trend = [
            {'timestamp': s.timestamp.isoformat(), 'value': s.cpu_usage_percent}
            for s in snapshots
        ]
        
        # 聚合统计
        processing_rates = [s.processing_rate for s in snapshots]
        memory_usages = [s.memory_usage_mb for s in snapshots]
        cpu_usages = [s.cpu_usage_percent for s in snapshots]
        
        return {
            'processing_rate_trend': processing_rate_trend,
            'memory_usage_trend': memory_usage_trend,
            'cpu_usage_trend': cpu_usage_trend,
            'average_processing_rate': sum(processing_rates) / len(processing_rates),
            'peak_memory_usage': max(memory_usages),
            'peak_cpu_usage': max(cpu_usages)
        }
    
    def generate_summary_statistics(self, 
                                  anomalies: List[DetectionResult],
                                  snapshots: List[ProgressSnapshot],
                                  session_duration: float) -> Dict[str, Any]:
        """生成汇总统计
        
        Args:
            anomalies: 异常检测结果
            snapshots: 进度快照
            session_duration: 会话持续时间（秒）
            
        Returns:
            Dict[str, Any]: 汇总统计
        """
        anomaly_stats = self.analyze_anomaly_distribution(anomalies)
        confidence_stats = self.analyze_confidence_distribution(anomalies)
        performance_stats = self.analyze_performance_trends(snapshots)
        
        # 计算检测效率
        total_records = snapshots[-1].total_records if snapshots else 0
        detection_rate = len(anomalies) / total_records if total_records > 0 else 0.0
        
        return {
            'session_duration_hours': session_duration / 3600,
            'total_anomalies_detected': len(anomalies),
            'total_records_processed': total_records,
            'anomaly_detection_rate': detection_rate,
            'average_confidence': confidence_stats['mean'],
            'average_processing_rate': performance_stats['average_processing_rate'],
            'peak_memory_usage_mb': performance_stats['peak_memory_usage'],
            'most_common_anomaly_type': max(anomaly_stats['by_type'].items(), 
                                           key=lambda x: x[1])[0] if anomaly_stats['by_type'] else 'None',
            'severity_distribution': anomaly_stats['by_severity']
        }


class VisualizationGenerator:
    """可视化生成器
    
    生成图表和可视化内容。
    """
    
    def __init__(self):
        """初始化可视化生成器"""
        self.logger = logging.getLogger(__name__)
    
    def generate_pie_chart_data(self, data: Dict[str, int], title: str) -> Dict[str, Any]:
        """生成饼图数据
        
        Args:
            data: 数据字典
            title: 图表标题
            
        Returns:
            Dict[str, Any]: 图表配置
        """
        return {
            'type': ChartType.PIE.value,
            'title': title,
            'data': {
                'labels': list(data.keys()),
                'values': list(data.values())
            },
            'config': {
                'responsive': True,
                'legend': {'position': 'right'}
            }
        }
    
    def generate_bar_chart_data(self, data: Dict[str, Union[int, float]], 
                               title: str, x_label: str = "", y_label: str = "") -> Dict[str, Any]:
        """生成柱状图数据
        
        Args:
            data: 数据字典
            title: 图表标题
            x_label: X轴标签
            y_label: Y轴标签
            
        Returns:
            Dict[str, Any]: 图表配置
        """
        return {
            'type': ChartType.BAR.value,
            'title': title,
            'data': {
                'labels': list(data.keys()),
                'datasets': [{
                    'label': y_label or title,
                    'data': list(data.values()),
                    'backgroundColor': 'rgba(54, 162, 235, 0.6)',
                    'borderColor': 'rgba(54, 162, 235, 1)',
                    'borderWidth': 1
                }]
            },
            'config': {
                'responsive': True,
                'scales': {
                    'x': {'title': {'display': True, 'text': x_label}},
                    'y': {'title': {'display': True, 'text': y_label}}
                }
            }
        }
    
    def generate_line_chart_data(self, time_series: List[Dict[str, Any]], 
                                title: str, y_label: str = "") -> Dict[str, Any]:
        """生成折线图数据
        
        Args:
            time_series: 时间序列数据
            title: 图表标题
            y_label: Y轴标签
            
        Returns:
            Dict[str, Any]: 图表配置
        """
        return {
            'type': ChartType.LINE.value,
            'title': title,
            'data': {
                'labels': [item['timestamp'] for item in time_series],
                'datasets': [{
                    'label': y_label or title,
                    'data': [item['value'] for item in time_series],
                    'borderColor': 'rgba(75, 192, 192, 1)',
                    'backgroundColor': 'rgba(75, 192, 192, 0.2)',
                    'tension': 0.1
                }]
            },
            'config': {
                'responsive': True,
                'scales': {
                    'x': {'title': {'display': True, 'text': '时间'}},
                    'y': {'title': {'display': True, 'text': y_label}}
                }
            }
        }
    
    def generate_histogram_data(self, histogram: Dict[str, int], 
                               title: str, x_label: str = "", y_label: str = "频次") -> Dict[str, Any]:
        """生成直方图数据
        
        Args:
            histogram: 直方图数据
            title: 图表标题
            x_label: X轴标签
            y_label: Y轴标签
            
        Returns:
            Dict[str, Any]: 图表配置
        """
        return {
            'type': ChartType.HISTOGRAM.value,
            'title': title,
            'data': {
                'labels': list(histogram.keys()),
                'datasets': [{
                    'label': y_label,
                    'data': list(histogram.values()),
                    'backgroundColor': 'rgba(255, 99, 132, 0.6)',
                    'borderColor': 'rgba(255, 99, 132, 1)',
                    'borderWidth': 1
                }]
            },
            'config': {
                'responsive': True,
                'scales': {
                    'x': {'title': {'display': True, 'text': x_label}},
                    'y': {'title': {'display': True, 'text': y_label}}
                }
            }
        }


class ReportGenerator:
    """报告生成器
    
    生成结构化的异常检测报告，支持多种格式导出。
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """初始化报告生成器
        
        Args:
            config: 配置参数
        """
        self.config = config or {}
        self.logger = logging.getLogger(__name__)
        self.analyzer = StatisticalAnalyzer()
        self.visualizer = VisualizationGenerator()
    
    def generate_report(self,
                       session_id: str,
                       anomalies: List[DetectionResult],
                       snapshots: List[ProgressSnapshot],
                       notifications: List[Notification],
                       metrics: List[PerformanceMetric],
                       repair_history: List[RepairHistory],
                       session_info: Optional[Dict[str, Any]] = None) -> DetectionReport:
        """生成完整的检测报告
        
        Args:
            session_id: 会话ID
            anomalies: 异常检测结果
            snapshots: 进度快照
            notifications: 通知列表
            metrics: 性能指标
            repair_history: 修复历史
            session_info: 会话信息
            
        Returns:
            DetectionReport: 生成的报告
        """
        try:
            # 计算会话持续时间
            session_duration = 0.0
            if snapshots:
                start_time = min(s.timestamp for s in snapshots)
                end_time = max(s.timestamp for s in snapshots)
                session_duration = (end_time - start_time).total_seconds()
            
            # 生成报告元数据
            metadata = ReportMetadata(
                title=f"异常检测报告 - 会话 {session_id}",
                description="RIPER-Core创新结果异常检测系统生成的综合分析报告",
                generated_at=datetime.now(),
                session_id=session_id,
                tags=['异常检测', '质量保证', '统计分析']
            )
            
            # 生成执行摘要
            summary_stats = self.analyzer.generate_summary_statistics(
                anomalies, snapshots, session_duration
            )
            executive_summary = self._generate_executive_summary(summary_stats)
            
            # 生成报告章节
            sections = [
                self._generate_overview_section(summary_stats, session_info),
                self._generate_anomaly_analysis_section(anomalies),
                self._generate_performance_analysis_section(snapshots, metrics),
                self._generate_repair_analysis_section(repair_history),
                self._generate_recommendations_section(anomalies, summary_stats)
            ]
            
            # 准备原始数据
            raw_data = {
                'anomalies': [self._anomaly_to_dict(a) for a in anomalies],
                'snapshots': [s.to_dict() for s in snapshots],
                'notifications': [n.to_dict() for n in notifications],
                'metrics': [m.to_dict() for m in metrics],
                'repair_history': [asdict(r) for r in repair_history],
                'summary_statistics': summary_stats
            }
            
            report = DetectionReport(
                metadata=metadata,
                executive_summary=executive_summary,
                sections=sections,
                raw_data=raw_data
            )
            
            self.logger.info(f"报告生成完成，会话ID: {session_id}")
            return report
            
        except Exception as e:
            self.logger.error(f"报告生成失败: {e}")
            raise AnomalyDetectionException(f"报告生成失败: {e}")
    
    def _generate_executive_summary(self, summary_stats: Dict[str, Any]) -> str:
        """生成执行摘要
        
        Args:
            summary_stats: 汇总统计
            
        Returns:
            str: 执行摘要
        """
        return f"""
本次异常检测会话共处理 {summary_stats['total_records_processed']:,} 条记录，
历时 {summary_stats['session_duration_hours']:.2f} 小时，
检测到 {summary_stats['total_anomalies_detected']} 个异常，
异常检测率为 {summary_stats['anomaly_detection_rate']:.4f}。

平均处理速度为 {summary_stats['average_processing_rate']:.1f} 记录/秒，
峰值内存使用 {summary_stats['peak_memory_usage_mb']:.1f} MB。
最常见的异常类型为 {summary_stats['most_common_anomaly_type']}，
平均置信度为 {summary_stats['average_confidence']:.3f}。

系统运行稳定，检测结果可靠，建议根据修复建议进行相应的数据质量改进。
        """.strip()
    
    def _generate_overview_section(self, summary_stats: Dict[str, Any], 
                                 session_info: Optional[Dict[str, Any]]) -> ReportSection:
        """生成概览章节
        
        Args:
            summary_stats: 汇总统计
            session_info: 会话信息
            
        Returns:
            ReportSection: 概览章节
        """
        content = f"""
本次检测会话的基本信息和关键指标概览。

**处理概况:**
- 总处理记录数: {summary_stats['total_records_processed']:,}
- 会话持续时间: {summary_stats['session_duration_hours']:.2f} 小时
- 平均处理速度: {summary_stats['average_processing_rate']:.1f} 记录/秒

**检测结果:**
- 检测到异常总数: {summary_stats['total_anomalies_detected']}
- 异常检测率: {summary_stats['anomaly_detection_rate']:.4f}
- 平均置信度: {summary_stats['average_confidence']:.3f}

**资源使用:**
- 峰值内存使用: {summary_stats['peak_memory_usage_mb']:.1f} MB
- 最常见异常类型: {summary_stats['most_common_anomaly_type']}
        """.strip()
        
        # 生成严重性分布图表
        severity_chart = self.visualizer.generate_pie_chart_data(
            summary_stats['severity_distribution'],
            "异常严重性分布"
        )
        
        return ReportSection(
            title="检测概览",
            content=content,
            data=summary_stats,
            charts=[severity_chart]
        )
    
    def _generate_anomaly_analysis_section(self, anomalies: List[DetectionResult]) -> ReportSection:
        """生成异常分析章节
        
        Args:
            anomalies: 异常检测结果
            
        Returns:
            ReportSection: 异常分析章节
        """
        anomaly_stats = self.analyzer.analyze_anomaly_distribution(anomalies)
        confidence_stats = self.analyzer.analyze_confidence_distribution(anomalies)
        
        content = f"""
详细的异常检测结果分析，包括异常类型分布、严重性分析和置信度统计。

**异常分布统计:**
- 总异常数量: {anomaly_stats['total_count']}
- 异常类型数量: {len(anomaly_stats['by_type'])}
- 涉及检测器数量: {len(anomaly_stats['by_detector'])}

**置信度统计:**
- 平均置信度: {confidence_stats['mean']:.3f}
- 置信度中位数: {confidence_stats['median']:.3f}
- 置信度标准差: {confidence_stats['std']:.3f}
- 置信度范围: {confidence_stats['min']:.3f} - {confidence_stats['max']:.3f}
        """.strip()
        
        # 生成图表
        charts = [
            self.visualizer.generate_bar_chart_data(
                anomaly_stats['by_type'], "异常类型分布", "异常类型", "数量"
            ),
            self.visualizer.generate_bar_chart_data(
                anomaly_stats['by_detector'], "检测器异常分布", "检测器", "数量"
            ),
            self.visualizer.generate_histogram_data(
                confidence_stats['histogram'], "置信度分布", "置信度区间", "频次"
            )
        ]
        
        return ReportSection(
            title="异常分析",
            content=content,
            data={
                'distribution': anomaly_stats,
                'confidence': confidence_stats
            },
            charts=charts
        )
    
    def _generate_performance_analysis_section(self, snapshots: List[ProgressSnapshot],
                                             metrics: List[PerformanceMetric]) -> ReportSection:
        """生成性能分析章节
        
        Args:
            snapshots: 进度快照
            metrics: 性能指标
            
        Returns:
            ReportSection: 性能分析章节
        """
        performance_stats = self.analyzer.analyze_performance_trends(snapshots)
        
        content = f"""
系统性能分析，包括处理速度趋势、资源使用情况和性能指标统计。

**性能概况:**
- 平均处理速度: {performance_stats['average_processing_rate']:.1f} 记录/秒
- 峰值内存使用: {performance_stats['peak_memory_usage']:.1f} MB
- 峰值CPU使用: {performance_stats['peak_cpu_usage']:.1f}%

**趋势分析:**
- 处理速度数据点: {len(performance_stats['processing_rate_trend'])}
- 内存使用数据点: {len(performance_stats['memory_usage_trend'])}
- CPU使用数据点: {len(performance_stats['cpu_usage_trend'])}
        """.strip()
        
        # 生成趋势图表
        charts = [
            self.visualizer.generate_line_chart_data(
                performance_stats['processing_rate_trend'], "处理速度趋势", "记录/秒"
            ),
            self.visualizer.generate_line_chart_data(
                performance_stats['memory_usage_trend'], "内存使用趋势", "MB"
            ),
            self.visualizer.generate_line_chart_data(
                performance_stats['cpu_usage_trend'], "CPU使用趋势", "%"
            )
        ]
        
        return ReportSection(
            title="性能分析",
            content=content,
            data=performance_stats,
            charts=charts
        )
    
    def _generate_repair_analysis_section(self, repair_history: List[RepairHistory]) -> ReportSection:
        """生成修复分析章节
        
        Args:
            repair_history: 修复历史
            
        Returns:
            ReportSection: 修复分析章节
        """
        if not repair_history:
            return ReportSection(
                title="修复分析",
                content="本次会话中未执行任何修复操作。",
                data={'repair_count': 0}
            )
        
        # 统计修复结果
        result_counts = Counter(r.repair_result for r in repair_history)
        
        content = f"""
修复操作执行情况分析，包括修复成功率和操作统计。

**修复统计:**
- 总修复操作数: {len(repair_history)}
- 成功修复数: {result_counts.get('success', 0)}
- 失败修复数: {result_counts.get('failed', 0)}
- 部分修复数: {result_counts.get('partial', 0)}
- 修复成功率: {result_counts.get('success', 0) / len(repair_history) * 100:.1f}%
        """.strip()
        
        # 生成修复结果分布图
        repair_chart = self.visualizer.generate_pie_chart_data(
            dict(result_counts), "修复结果分布"
        )
        
        return ReportSection(
            title="修复分析",
            content=content,
            data={
                'repair_count': len(repair_history),
                'result_distribution': dict(result_counts)
            },
            charts=[repair_chart]
        )
    
    def _generate_recommendations_section(self, anomalies: List[DetectionResult],
                                        summary_stats: Dict[str, Any]) -> ReportSection:
        """生成建议章节
        
        Args:
            anomalies: 异常检测结果
            summary_stats: 汇总统计
            
        Returns:
            ReportSection: 建议章节
        """
        recommendations = []
        
        # 基于异常数量的建议
        if summary_stats['total_anomalies_detected'] > 100:  # 这是经验值，超过100个异常需要关注
            recommendations.append("检测到大量异常，建议优先处理高严重性异常，并检查数据源质量。")
        
        # 基于异常检测率的建议
        if summary_stats['anomaly_detection_rate'] > 0.1:  # 这是经验值，10%以上的异常率需要关注
            recommendations.append("异常检测率较高，建议审查数据处理流程和质量控制措施。")
        
        # 基于置信度的建议
        if summary_stats['average_confidence'] < 0.7:  # 这是经验值，平均置信度低于0.7需要关注
            recommendations.append("平均置信度较低，建议人工审核部分检测结果，并考虑调整检测参数。")
        
        # 基于性能的建议
        if summary_stats['peak_memory_usage_mb'] > 4000:  # 这是经验值，超过4GB内存需要关注
            recommendations.append("内存使用量较高，建议优化数据处理算法或增加系统内存。")
        
        # 基于最常见异常类型的建议
        most_common_type = summary_stats['most_common_anomaly_type']
        if most_common_type != 'None':
            recommendations.append(f"最常见异常类型为 {most_common_type}，建议重点关注此类异常的根本原因。")
        
        # 默认建议
        if not recommendations:
            recommendations.append("系统运行正常，检测结果良好。建议定期执行异常检测以维护数据质量。")
        
        content = "基于本次检测结果的改进建议：\n\n" + "\n".join(f"• {rec}" for rec in recommendations)
        
        return ReportSection(
            title="改进建议",
            content=content,
            data={'recommendations': recommendations}
        )
    
    def _anomaly_to_dict(self, anomaly: DetectionResult) -> Dict[str, Any]:
        """将异常结果转换为字典
        
        Args:
            anomaly: 异常检测结果
            
        Returns:
            Dict[str, Any]: 字典格式的异常数据
        """
        return {
            'anomaly_id': anomaly.anomaly_id,
            'detector_name': anomaly.detector_name,
            'anomaly_type': anomaly.anomaly_type,
            'severity': anomaly.severity.value,
            'description': anomaly.description,
            'affected_entities': anomaly.affected_entities,
            'evidence': anomaly.evidence,
            'suggested_fixes': anomaly.suggested_fixes,
            'confidence_score': anomaly.confidence_score,
            'detection_timestamp': anomaly.detection_timestamp.isoformat(),
            'status': anomaly.status.value
        }
    
    def export_report(self, report: DetectionReport, output_path: Path, 
                     format_type: ReportFormat) -> None:
        """导出报告到文件
        
        Args:
            report: 检测报告
            output_path: 输出路径
            format_type: 导出格式
        """
        try:
            if format_type == ReportFormat.JSON:
                self._export_json(report, output_path)
            elif format_type == ReportFormat.EXCEL:
                self._export_excel(report, output_path)
            elif format_type == ReportFormat.HTML:
                self._export_html(report, output_path)
            elif format_type == ReportFormat.CSV:
                self._export_csv(report, output_path)
            else:
                raise AnomalyDetectionException(f"不支持的导出格式: {format_type}")
            
            self.logger.info(f"报告已导出到: {output_path}")
            
        except Exception as e:
            self.logger.error(f"报告导出失败: {e}")
            raise AnomalyDetectionException(f"报告导出失败: {e}")
    
    def _export_json(self, report: DetectionReport, output_path: Path) -> None:
        """导出JSON格式报告"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
    
    def _export_excel(self, report: DetectionReport, output_path: Path) -> None:
        """导出Excel格式报告"""
        try:
            import pandas as pd
            
            # 创建Excel写入器
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                # 写入元数据
                metadata_df = pd.DataFrame([report.metadata.to_dict()])
                metadata_df.to_excel(writer, sheet_name='元数据', index=False)
                
                # 写入异常数据
                if report.raw_data.get('anomalies'):
                    anomalies_df = pd.DataFrame(report.raw_data['anomalies'])
                    anomalies_df.to_excel(writer, sheet_name='异常检测结果', index=False)
                
                # 写入汇总统计
                if report.raw_data.get('summary_statistics'):
                    summary_df = pd.DataFrame([report.raw_data['summary_statistics']])
                    summary_df.to_excel(writer, sheet_name='汇总统计', index=False)
                
                # 写入修复历史
                if report.raw_data.get('repair_history'):
                    repair_df = pd.DataFrame(report.raw_data['repair_history'])
                    repair_df.to_excel(writer, sheet_name='修复历史', index=False)
        
        except ImportError:
            # 如果pandas不可用，使用基本的CSV导出
            self.logger.warning("pandas不可用，使用CSV格式导出")
            csv_path = output_path.with_suffix('.csv')
            self._export_csv(report, csv_path)
    
    def _export_html(self, report: DetectionReport, output_path: Path) -> None:
        """导出HTML格式报告"""
        html_content = self._generate_html_content(report)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
    
    def _export_csv(self, report: DetectionReport, output_path: Path) -> None:
        """导出CSV格式报告"""
        if not report.raw_data.get('anomalies'):
            return
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=report.raw_data['anomalies'][0].keys())
            writer.writeheader()
            writer.writerows(report.raw_data['anomalies'])
    
    def _generate_html_content(self, report: DetectionReport) -> str:
        """生成HTML报告内容
        
        Args:
            report: 检测报告
            
        Returns:
            str: HTML内容
        """
        html_template = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; margin: 20px; line-height: 1.6; }}
        .header {{ background-color: #f8f9fa; padding: 20px; border-radius: 5px; margin-bottom: 20px; }}
        .section {{ margin-bottom: 30px; padding: 15px; border: 1px solid #dee2e6; border-radius: 5px; }}
        .section h2 {{ color: #495057; border-bottom: 2px solid #007bff; padding-bottom: 10px; }}
        .summary {{ background-color: #e9ecef; padding: 15px; border-radius: 5px; }}
        .chart-placeholder {{ background-color: #f8f9fa; padding: 20px; text-align: center; 
                             border: 1px dashed #6c757d; margin: 10px 0; }}
        .metadata {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
        .metadata-item {{ background-color: #f8f9fa; padding: 10px; border-radius: 3px; }}
        pre {{ background-color: #f8f9fa; padding: 10px; border-radius: 3px; overflow-x: auto; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{title}</h1>
        <p><strong>生成时间:</strong> {generated_at}</p>
        <p><strong>会话ID:</strong> {session_id}</p>
        <p><strong>描述:</strong> {description}</p>
    </div>
    
    <div class="section">
        <h2>执行摘要</h2>
        <div class="summary">
            <pre>{executive_summary}</pre>
        </div>
    </div>
    
    {sections_html}
    
    <div class="section">
        <h2>报告元数据</h2>
        <div class="metadata">
            <div class="metadata-item"><strong>生成器版本:</strong> {generator_version}</div>
            <div class="metadata-item"><strong>作者:</strong> {author}</div>
            <div class="metadata-item"><strong>标签:</strong> {tags}</div>
        </div>
    </div>
</body>
</html>
        """
        
        # 生成章节HTML
        sections_html = ""
        for section in report.sections:
            section_html = f"""
    <div class="section">
        <h2>{section.title}</h2>
        <pre>{section.content}</pre>
        """
            
            # 添加图表占位符
            for chart in section.charts:
                section_html += f"""
        <div class="chart-placeholder">
            <h3>{chart['title']}</h3>
            <p>图表类型: {chart['type']}</p>
            <p>数据点数量: {len(chart['data'].get('labels', []))}</p>
        </div>
                """
            
            section_html += "</div>"
            sections_html += section_html
        
        return html_template.format(
            title=report.metadata.title,
            generated_at=report.metadata.generated_at.strftime('%Y-%m-%d %H:%M:%S'),
            session_id=report.metadata.session_id,
            description=report.metadata.description,
            executive_summary=report.executive_summary,
            sections_html=sections_html,
            generator_version=report.metadata.generator_version,
            author=report.metadata.author,
            tags=', '.join(report.metadata.tags)
        )