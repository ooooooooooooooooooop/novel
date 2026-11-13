# -*- coding: utf-8 -*-
"""
Performance Reporting and Comparison System
性能报告和对比系统

功能:
1. 性能对比报告 - 优化前后性能指标对比
2. 修饰符过滤统计报告 - 详细的过滤效果分析
3. 可配置日志详细程度 - 支持不同级别的性能数据记录
4. 性能趋势分析 - 历史性能数据趋势分析
"""

import logging
import json
import time
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum
import statistics

logger = logging.getLogger(__name__)

class LoggingVerbosity(Enum):
    """日志详细程度级别"""
    MINIMAL = "minimal"      # 仅关键指标
    STANDARD = "standard"    # 标准性能指标
    DETAILED = "detailed"    # 详细性能数据
    VERBOSE = "verbose"      # 完整调试信息

@dataclass
class PerformanceComparison:
    """性能对比数据结构"""
    metric_name: str
    original_value: float
    optimized_value: float
    improvement_ratio: float
    improvement_percentage: float
    is_better: bool
    higher_is_better: bool = True  # 添加方向指示
    unit: str = ""
    
    def __post_init__(self):
        """计算改进指标"""
        if self.original_value != 0:
            self.improvement_ratio = self.optimized_value / self.original_value
            raw_percentage = ((self.optimized_value - self.original_value) / 
                            abs(self.original_value)) * 100
            
            # 根据改进方向调整百分比：如果是改进，百分比为正；如果是退化，百分比为负
            if self.higher_is_better:
                self.improvement_percentage = raw_percentage
            else:
                # 对于"越小越好"的指标，需要反转百分比符号
                self.improvement_percentage = -raw_percentage
        else:
            self.improvement_ratio = float('inf') if self.optimized_value > 0 else 0
            self.improvement_percentage = float('inf') if self.optimized_value > 0 else 0

@dataclass
class FilteringReport:
    """过滤统计报告数据结构"""
    filter_type: str
    total_processed: int
    filtered_count: int
    filter_rate: float
    performance_impact: float
    memory_saved_mb: float
    time_saved_seconds: float
    effectiveness_score: float

class PerformanceReporter:
    """
    性能报告和对比系统
    
    提供优化前后性能对比、详细的过滤统计报告和可配置的日志记录功能
    """
    
    def __init__(self, verbosity: LoggingVerbosity = LoggingVerbosity.STANDARD):
        """
        初始化性能报告器
        
        Args:
            verbosity: 日志详细程度级别
        """
        self.verbosity = verbosity
        self.comparison_data = []
        self.filtering_reports = []
        
        # 配置日志格式
        self._configure_logging()
        
    def _configure_logging(self) -> None:
        """配置日志记录格式和级别"""
        # 根据详细程度设置日志级别
        level_mapping = {
            LoggingVerbosity.MINIMAL: logging.WARNING,
            LoggingVerbosity.STANDARD: logging.INFO,
            LoggingVerbosity.DETAILED: logging.DEBUG,
            LoggingVerbosity.VERBOSE: logging.DEBUG
        }
        
        # 设置性能相关日志的级别
        perf_logger = logging.getLogger('performance')
        perf_logger.setLevel(level_mapping[self.verbosity])
        
        # 创建格式化器
        if self.verbosity in [LoggingVerbosity.DETAILED, LoggingVerbosity.VERBOSE]:
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
        else:
            formatter = logging.Formatter('%(levelname)s - %(message)s')
            
        # 如果没有处理器，添加一个
        if not perf_logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            perf_logger.addHandler(handler)
            
    def compare_performance_metrics(self, original_metrics: Dict[str, Any], 
                                  optimized_metrics: Dict[str, Any]) -> List[PerformanceComparison]:
        """
        对比优化前后的性能指标
        
        Args:
            original_metrics: 原始系统性能指标
            optimized_metrics: 优化后系统性能指标
            
        Returns:
            性能对比结果列表
        """
        comparisons = []
        
        # 定义需要对比的指标及其改进方向（True表示数值越大越好）
        metrics_to_compare = {
            'total_duration_seconds': (False, 's'),  # 处理时间越短越好
            'average_processing_rate': (True, '论文/s'),  # 处理速率越高越好
            'peak_memory_mb': (False, 'MB'),  # 内存使用越少越好
            'average_hit_rate': (True, ''),  # 缓存命中率越高越好
            'average_filter_rate': (True, ''),  # 过滤率越高越好（在合理范围内）
        }
        
        for metric_name, (higher_is_better, unit) in metrics_to_compare.items():
            original_value = self._extract_nested_value(original_metrics, metric_name)
            optimized_value = self._extract_nested_value(optimized_metrics, metric_name)
            
            if original_value is not None and optimized_value is not None:
                comparison = PerformanceComparison(
                    metric_name=metric_name,
                    original_value=original_value,
                    optimized_value=optimized_value,
                    improvement_ratio=0,  # 将在__post_init__中计算
                    improvement_percentage=0,  # 将在__post_init__中计算
                    is_better=False,  # 将在下面设置
                    higher_is_better=higher_is_better,  # 传递方向信息
                    unit=unit
                )
                
                # 判断是否改进
                if higher_is_better:
                    comparison.is_better = optimized_value > original_value
                else:
                    comparison.is_better = optimized_value < original_value
                    
                comparisons.append(comparison)
                
        self.comparison_data.extend(comparisons)
        return comparisons
        
    def _extract_nested_value(self, data: Dict[str, Any], key: str) -> Optional[float]:
        """
        从嵌套字典中提取指标值
        
        Args:
            data: 数据字典
            key: 指标键名
            
        Returns:
            指标值，如果不存在则返回None
        """
        # 尝试直接访问
        if key in data:
            return float(data[key])
            
        # 尝试在各个子部分中查找
        sections = ['timing_summary', 'processing_summary', 'memory_summary', 
                   'cache_summary', 'filtering_summary']
        
        for section in sections:
            if section in data and key in data[section]:
                return float(data[section][key])
                
        return None
        
    def generate_filtering_report(self, modifier_filter_stats: Dict[str, Any],
                                synergy_filter_stats: Dict[str, Any],
                                performance_impact: Dict[str, float]) -> List[FilteringReport]:
        """
        生成详细的过滤统计报告
        
        Args:
            modifier_filter_stats: 修饰符过滤统计
            synergy_filter_stats: 协同过滤统计
            performance_impact: 性能影响数据
            
        Returns:
            过滤报告列表
        """
        reports = []
        
        # 修饰符过滤报告
        if modifier_filter_stats:
            modifier_report = FilteringReport(
                filter_type="modifier_filter",
                total_processed=modifier_filter_stats.get('total_processed', 0),
                filtered_count=modifier_filter_stats.get('filtered_count', 0),
                filter_rate=modifier_filter_stats.get('filter_rate', 0.0),
                performance_impact=performance_impact.get('modifier_filter_speedup', 1.0),
                memory_saved_mb=performance_impact.get('modifier_filter_memory_saved', 0.0),
                time_saved_seconds=performance_impact.get('modifier_filter_time_saved', 0.0),
                effectiveness_score=self._calculate_effectiveness_score(
                    modifier_filter_stats.get('filter_rate', 0.0),
                    performance_impact.get('modifier_filter_speedup', 1.0)
                )
            )
            reports.append(modifier_report)
            
        # 协同过滤报告
        if synergy_filter_stats:
            synergy_report = FilteringReport(
                filter_type="synergy_filter",
                total_processed=synergy_filter_stats.get('total_processed', 0),
                filtered_count=synergy_filter_stats.get('filtered_count', 0),
                filter_rate=synergy_filter_stats.get('filter_rate', 0.0),
                performance_impact=performance_impact.get('synergy_filter_speedup', 1.0),
                memory_saved_mb=performance_impact.get('synergy_filter_memory_saved', 0.0),
                time_saved_seconds=performance_impact.get('synergy_filter_time_saved', 0.0),
                effectiveness_score=self._calculate_effectiveness_score(
                    synergy_filter_stats.get('filter_rate', 0.0),
                    performance_impact.get('synergy_filter_speedup', 1.0)
                )
            )
            reports.append(synergy_report)
            
        self.filtering_reports.extend(reports)
        return reports
        
    def _calculate_effectiveness_score(self, filter_rate: float, speedup: float) -> float:
        """
        计算过滤效果评分
        
        Args:
            filter_rate: 过滤率
            speedup: 性能提升倍数
            
        Returns:
            效果评分（0-100）
        """
        # 这是经验值 - 基于过滤率和性能提升的综合评分
        # 过滤率权重0.4，性能提升权重0.6
        filter_score = min(filter_rate * 100, 50)  # 过滤率最高贡献50分
        speedup_score = min((speedup - 1) * 50, 50)  # 性能提升最高贡献50分
        
        return filter_score + speedup_score
        
    def log_performance_data(self, data: Dict[str, Any], context: str = "") -> None:
        """
        根据配置的详细程度记录性能数据
        
        Args:
            data: 性能数据
            context: 上下文描述
        """
        perf_logger = logging.getLogger('performance')
        
        if self.verbosity == LoggingVerbosity.MINIMAL:
            # 仅记录关键指标
            if 'total_duration_seconds' in data:
                perf_logger.warning(f"{context} 处理时间: {data['total_duration_seconds']:.2f}s")
            if 'total_papers' in data:
                perf_logger.warning(f"{context} 论文数: {data['total_papers']:,}")
                
        elif self.verbosity == LoggingVerbosity.STANDARD:
            # 标准性能指标
            perf_logger.info(f"=== {context} 性能摘要 ===")
            if 'total_duration_seconds' in data:
                perf_logger.info(f"处理时间: {data['total_duration_seconds']:.2f}s")
            if 'total_papers' in data:
                perf_logger.info(f"论文数: {data['total_papers']:,}")
            if 'average_processing_rate' in data:
                perf_logger.info(f"处理速率: {data['average_processing_rate']:.1f} 论文/s")
            if 'peak_memory_mb' in data:
                perf_logger.info(f"峰值内存: {data['peak_memory_mb']:.1f}MB")
                
        elif self.verbosity == LoggingVerbosity.DETAILED:
            # 详细性能数据
            perf_logger.debug(f"=== {context} 详细性能数据 ===")
            for key, value in data.items():
                if isinstance(value, (int, float)):
                    perf_logger.debug(f"{key}: {value}")
                elif isinstance(value, dict):
                    perf_logger.debug(f"{key}: {json.dumps(value, indent=2)}")
                    
        elif self.verbosity == LoggingVerbosity.VERBOSE:
            # 完整调试信息
            perf_logger.debug(f"=== {context} 完整性能数据 ===")
            perf_logger.debug(json.dumps(data, indent=2, ensure_ascii=False))
            
    def generate_comparison_report(self, title: str = "性能对比报告") -> Dict[str, Any]:
        """
        生成综合性能对比报告
        
        Args:
            title: 报告标题
            
        Returns:
            对比报告数据
        """
        if not self.comparison_data:
            logger.warning("没有性能对比数据，无法生成对比报告")
            return {}
            
        # 计算总体改进统计
        improvements = [comp.improvement_percentage for comp in self.comparison_data 
                       if comp.is_better and comp.improvement_percentage > 0]
        regressions = [abs(comp.improvement_percentage) for comp in self.comparison_data 
                      if not comp.is_better and comp.improvement_percentage < 0]
        
        overall_stats = {
            'total_metrics_compared': len(self.comparison_data),
            'improved_metrics': len(improvements),
            'regressed_metrics': len(regressions),
            'improvement_rate': len(improvements) / len(self.comparison_data) if self.comparison_data else 0,
            'average_improvement': statistics.mean(improvements) if improvements else 0,
            'max_improvement': max(improvements) if improvements else 0,
            'average_regression': statistics.mean(regressions) if regressions else 0
        }
        
        # 生成详细对比数据
        detailed_comparisons = [asdict(comp) for comp in self.comparison_data]
        
        # 生成过滤报告摘要
        filtering_summary = {}
        if self.filtering_reports:
            filtering_summary = {
                'total_filters': len(self.filtering_reports),
                'average_filter_rate': statistics.mean([r.filter_rate for r in self.filtering_reports]),
                'total_memory_saved': sum([r.memory_saved_mb for r in self.filtering_reports]),
                'total_time_saved': sum([r.time_saved_seconds for r in self.filtering_reports]),
                'average_effectiveness': statistics.mean([r.effectiveness_score for r in self.filtering_reports])
            }
            
        report = {
            'report_title': title,
            'generation_timestamp': time.time(),
            'generation_date': datetime.now().isoformat(),
            'overall_statistics': overall_stats,
            'detailed_comparisons': detailed_comparisons,
            'filtering_summary': filtering_summary,
            'filtering_details': [asdict(report) for report in self.filtering_reports]
        }
        
        return report
        
    def export_comparison_report(self, report: Dict[str, Any], output_path: str) -> None:
        """
        导出对比报告到文件
        
        Args:
            report: 报告数据
            output_path: 输出文件路径
        """
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            logger.info(f"性能对比报告已导出到: {output_path}")
        except Exception as e:
            logger.error(f"导出对比报告失败: {e}")
            
    def log_comparison_summary(self, report: Dict[str, Any]) -> None:
        """
        记录对比报告摘要到日志
        
        Args:
            report: 报告数据
        """
        if not report:
            return
            
        overall = report.get('overall_statistics', {})
        filtering = report.get('filtering_summary', {})
        
        logger.info("=== 性能优化效果摘要 ===")
        logger.info(f"对比指标数: {overall.get('total_metrics_compared', 0)}")
        logger.info(f"改进指标数: {overall.get('improved_metrics', 0)}")
        logger.info(f"改进率: {overall.get('improvement_rate', 0):.1%}")
        
        if overall.get('average_improvement', 0) > 0:
            logger.info(f"平均改进幅度: {overall.get('average_improvement', 0):.1f}%")
        if overall.get('max_improvement', 0) > 0:
            logger.info(f"最大改进幅度: {overall.get('max_improvement', 0):.1f}%")
            
        if filtering:
            logger.info(f"过滤器数量: {filtering.get('total_filters', 0)}")
            logger.info(f"平均过滤率: {filtering.get('average_filter_rate', 0):.1%}")
            logger.info(f"节省内存: {filtering.get('total_memory_saved', 0):.1f}MB")
            logger.info(f"节省时间: {filtering.get('total_time_saved', 0):.1f}s")
            
    def analyze_performance_trends(self, historical_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        分析历史性能数据趋势
        
        Args:
            historical_data: 历史性能数据列表
            
        Returns:
            趋势分析结果
        """
        if len(historical_data) < 2:
            return {'error': '需要至少2个数据点进行趋势分析'}
            
        trends = {}
        
        # 分析关键指标的趋势
        key_metrics = ['total_duration_seconds', 'average_processing_rate', 'peak_memory_mb']
        
        for metric in key_metrics:
            values = []
            timestamps = []
            
            for data_point in historical_data:
                value = self._extract_nested_value(data_point, metric)
                timestamp = data_point.get('report_timestamp', time.time())
                
                if value is not None:
                    values.append(value)
                    timestamps.append(timestamp)
                    
            if len(values) >= 2:
                # 计算简单的线性趋势
                trend_direction = 'stable'
                if values[-1] > values[0] * 1.1:
                    trend_direction = 'increasing'
                elif values[-1] < values[0] * 0.9:
                    trend_direction = 'decreasing'
                    
                trends[metric] = {
                    'direction': trend_direction,
                    'start_value': values[0],
                    'end_value': values[-1],
                    'change_percentage': ((values[-1] - values[0]) / values[0]) * 100 if values[0] != 0 else 0,
                    'data_points': len(values)
                }
                
        return {
            'analysis_timestamp': time.time(),
            'data_points_analyzed': len(historical_data),
            'trends': trends
        }
        
    def set_verbosity(self, verbosity: LoggingVerbosity) -> None:
        """
        设置日志详细程度
        
        Args:
            verbosity: 新的详细程度级别
        """
        self.verbosity = verbosity
        self._configure_logging()
        logger.info(f"日志详细程度已设置为: {verbosity.value}")