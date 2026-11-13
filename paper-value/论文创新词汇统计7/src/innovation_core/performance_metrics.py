# -*- coding: utf-8 -*-
"""
Performance Metrics Collection System
用于创新引擎优化的综合性能监控

功能:
1. 计时统计 - 每年处理时间、各阶段耗时
2. 内存使用监控 - 峰值内存、缓存内存使用
3. 缓存统计 - 命中率、缓存效率分析
4. 处理统计 - 论文数量、RPU数量、过滤统计
"""

import time
import psutil
import os
import logging
from typing import Dict, List, Optional, Any
from collections import defaultdict, deque
from datetime import datetime
import json

logger = logging.getLogger(__name__)

class PerformanceMetrics:
    """
    综合性能指标收集类
    
    收集创新引擎处理过程中的各项性能指标：
    - 时间统计：每年处理时间、各阶段耗时
    - 内存监控：系统内存使用、缓存内存占用
    - 缓存统计：命中率、效率分析
    - 处理统计：论文数量、RPU处理量、过滤效果
    """
    
    def __init__(self, enable_memory_monitoring: bool = True, 
                 memory_sample_interval: int = 10):
        """
        初始化性能监控系统
        
        Args:
            enable_memory_monitoring: 是否启用内存监控
            memory_sample_interval: 内存采样间隔（年数）
        """
        # 时间统计
        self.timing_stats = {
            'total_start_time': None,
            'total_end_time': None,
            'year_timings': {},  # year -> {'start': time, 'end': time, 'calculation': time, 'merge': time}
            'phase_timings': defaultdict(list),  # phase_name -> [duration1, duration2, ...]
        }
        
        # 内存监控
        self.memory_stats = {
            'enable_monitoring': enable_memory_monitoring,
            'sample_interval': memory_sample_interval,
            'peak_memory_mb': 0,
            'memory_samples': [],  # [(timestamp, year, memory_mb), ...]
            'cache_memory_samples': [],  # [(timestamp, year, cache_memory_bytes), ...]
        }
        
        # 缓存统计
        self.cache_stats = {
            'log_cache_snapshots': [],  # 定期快照
            'pmi_cache_snapshots': [],
            'cache_efficiency_history': [],  # [(year, hit_rate, memory_efficiency), ...]
        }
        
        # 处理统计
        self.processing_stats = {
            'total_papers_processed': 0,
            'total_rpus_processed': 0,
            'papers_per_year': {},  # year -> count
            'rpus_per_year': {},    # year -> count
            'year_processing_rates': {},  # year -> papers_per_second
        }
        
        # 过滤统计
        self.filtering_stats = {
            'modifier_filter_snapshots': [],  # 定期快照
            'synergy_filter_snapshots': [],
            'filtering_efficiency_history': [],  # [(year, filter_rate, performance_gain), ...]
        }
        
        # 里程碑记录
        self.milestones = []  # [(timestamp, year, milestone_type, description, metrics), ...]
        
        # 进程监控
        self.process = psutil.Process(os.getpid()) if enable_memory_monitoring else None
        
    def start_total_timing(self) -> None:
        """开始总体计时"""
        self.timing_stats['total_start_time'] = time.time()
        logger.info("PerformanceMetrics: 开始总体性能监控")
        
    def end_total_timing(self) -> None:
        """结束总体计时"""
        self.timing_stats['total_end_time'] = time.time()
        total_duration = self.get_total_duration()
        logger.info(f"PerformanceMetrics: 总体处理完成，耗时 {total_duration:.2f}s")
        
    def start_year_timing(self, year: str) -> None:
        """开始年度计时"""
        if year not in self.timing_stats['year_timings']:
            self.timing_stats['year_timings'][year] = {}
        self.timing_stats['year_timings'][year]['start'] = time.time()
        
    def end_year_timing(self, year: str, calculation_time: float, merge_time: float) -> None:
        """
        结束年度计时并记录各阶段耗时
        
        Args:
            year: 年份
            calculation_time: 计算阶段耗时
            merge_time: 合并阶段耗时
        """
        if year in self.timing_stats['year_timings']:
            self.timing_stats['year_timings'][year]['end'] = time.time()
            self.timing_stats['year_timings'][year]['calculation'] = calculation_time
            self.timing_stats['year_timings'][year]['merge'] = merge_time
            
            # 计算处理速率
            year_duration = (self.timing_stats['year_timings'][year]['end'] - 
                           self.timing_stats['year_timings'][year]['start'])
            papers_count = self.processing_stats['papers_per_year'].get(year, 0)
            if year_duration > 0 and papers_count > 0:
                self.processing_stats['year_processing_rates'][year] = papers_count / year_duration
                
    def record_phase_timing(self, phase_name: str, duration: float) -> None:
        """
        记录特定阶段的耗时
        
        Args:
            phase_name: 阶段名称
            duration: 耗时（秒）
        """
        self.timing_stats['phase_timings'][phase_name].append(duration)
        
    def sample_memory_usage(self, year: str, context: str = "") -> Optional[float]:
        """
        采样当前内存使用情况
        
        Args:
            year: 当前处理年份
            context: 采样上下文描述
            
        Returns:
            当前内存使用量（MB），如果监控未启用则返回None
        """
        if not self.memory_stats['enable_monitoring'] or not self.process:
            return None
            
        try:
            # 获取当前进程内存使用
            memory_info = self.process.memory_info()
            memory_mb = memory_info.rss / (1024 * 1024)  # 转换为MB
            
            # 更新峰值内存
            if memory_mb > self.memory_stats['peak_memory_mb']:
                self.memory_stats['peak_memory_mb'] = memory_mb
                
            # 记录内存样本
            timestamp = time.time()
            self.memory_stats['memory_samples'].append((timestamp, year, memory_mb, context))
            
            return memory_mb
            
        except Exception as e:
            logger.warning(f"内存采样失败: {e}")
            return None
            
    def record_cache_memory(self, year: str, cache_memory_bytes: int) -> None:
        """
        记录缓存内存使用情况
        
        Args:
            year: 当前年份
            cache_memory_bytes: 缓存内存使用量（字节）
        """
        timestamp = time.time()
        self.memory_stats['cache_memory_samples'].append((timestamp, year, cache_memory_bytes))
        
    def record_processing_stats(self, year: str, papers_count: int, rpus_count: int) -> None:
        """
        记录处理统计信息
        
        Args:
            year: 年份
            papers_count: 论文数量
            rpus_count: RPU数量
        """
        self.processing_stats['papers_per_year'][year] = papers_count
        self.processing_stats['rpus_per_year'][year] = rpus_count
        self.processing_stats['total_papers_processed'] += papers_count
        self.processing_stats['total_rpus_processed'] += rpus_count
        
    def snapshot_cache_stats(self, year: str, cache_stats: Dict[str, Any]) -> None:
        """
        快照缓存统计信息
        
        Args:
            year: 当前年份
            cache_stats: 缓存统计数据
        """
        timestamp = time.time()
        
        # 记录log缓存快照
        if 'log_cache' in cache_stats:
            log_snapshot = {
                'timestamp': timestamp,
                'year': year,
                'size': cache_stats['log_cache']['size'],
                'hits': cache_stats['log_cache']['hits'],
                'misses': cache_stats['log_cache']['misses'],
                'hit_rate': cache_stats['log_cache']['hit_rate'],
                'memory_bytes': cache_stats['log_cache']['memory_bytes']
            }
            self.cache_stats['log_cache_snapshots'].append(log_snapshot)
            
        # 记录PMI缓存快照
        if 'pmi_cache' in cache_stats:
            pmi_snapshot = {
                'timestamp': timestamp,
                'year': year,
                'size': cache_stats['pmi_cache']['size'],
                'hits': cache_stats['pmi_cache']['hits'],
                'misses': cache_stats['pmi_cache']['misses'],
                'hit_rate': cache_stats['pmi_cache']['hit_rate'],
                'memory_bytes': cache_stats['pmi_cache']['memory_bytes']
            }
            self.cache_stats['pmi_cache_snapshots'].append(pmi_snapshot)
            
        # 计算缓存效率指标
        total_hit_rate = 0
        total_memory = cache_stats.get('total_memory_bytes', 0)
        cache_count = 0
        
        if 'log_cache' in cache_stats:
            total_hit_rate += cache_stats['log_cache']['hit_rate']
            cache_count += 1
        if 'pmi_cache' in cache_stats:
            total_hit_rate += cache_stats['pmi_cache']['hit_rate']
            cache_count += 1
            
        if cache_count > 0:
            avg_hit_rate = total_hit_rate / cache_count
            # 内存效率 = 命中率 / 内存使用量(MB)
            memory_efficiency = avg_hit_rate / max(total_memory / (1024*1024), 0.1)
            
            self.cache_stats['cache_efficiency_history'].append((year, avg_hit_rate, memory_efficiency))
            
    def snapshot_filtering_stats(self, year: str, modifier_filter_stats: Dict[str, Any], 
                                integration_stats: Dict[str, Any]) -> None:
        """
        快照过滤统计信息
        
        Args:
            year: 当前年份
            modifier_filter_stats: 修饰符过滤统计
            integration_stats: 集成统计信息
        """
        timestamp = time.time()
        
        # 修饰符过滤快照
        modifier_snapshot = {
            'timestamp': timestamp,
            'year': year,
            'total_processed': modifier_filter_stats.get('total_processed', 0),
            'filtered_count': modifier_filter_stats.get('filtered_count', 0),
            'filter_rate': modifier_filter_stats.get('filter_rate', 0.0),
            'current_threshold': modifier_filter_stats.get('current_threshold', 0),
            'unique_modifiers': modifier_filter_stats.get('unique_modifiers', 0)
        }
        self.filtering_stats['modifier_filter_snapshots'].append(modifier_snapshot)
        
        # 协同过滤快照
        synergy_snapshot = {
            'timestamp': timestamp,
            'year': year,
            'total_synergy_concepts': integration_stats.get('total_synergy_concepts_processed', 0),
            'filtered_synergy_concepts': integration_stats.get('synergy_concepts_filtered', 0),
            'synergy_filter_rate': integration_stats.get('synergy_filter_rate', 0.0)
        }
        self.filtering_stats['synergy_filter_snapshots'].append(synergy_snapshot)
        
        # 计算过滤效率（这是经验值 - 基于过滤率和处理量的综合指标）
        total_filter_rate = (modifier_filter_stats.get('filter_rate', 0.0) + 
                           integration_stats.get('synergy_filter_rate', 0.0)) / 2
        total_processed = (modifier_filter_stats.get('total_processed', 0) + 
                         integration_stats.get('total_synergy_concepts_processed', 0))
        
        # 性能增益估算：过滤率 * 处理量的对数（避免线性增长）
        import math
        performance_gain = total_filter_rate * math.log(max(total_processed, 1))
        
        self.filtering_stats['filtering_efficiency_history'].append((year, total_filter_rate, performance_gain))
        
    def record_milestone(self, year: str, milestone_type: str, description: str, 
                        metrics: Optional[Dict[str, Any]] = None) -> None:
        """
        记录重要里程碑
        
        Args:
            year: 年份
            milestone_type: 里程碑类型（如 'cache_optimization', 'memory_peak', 'processing_rate'）
            description: 描述
            metrics: 相关指标数据
        """
        timestamp = time.time()
        milestone = {
            'timestamp': timestamp,
            'year': year,
            'type': milestone_type,
            'description': description,
            'metrics': metrics or {}
        }
        self.milestones.append(milestone)
        logger.info(f"里程碑记录 [{milestone_type}] {year}: {description}")
        
    def get_total_duration(self) -> float:
        """获取总处理时长"""
        if (self.timing_stats['total_start_time'] is not None and 
            self.timing_stats['total_end_time'] is not None):
            return self.timing_stats['total_end_time'] - self.timing_stats['total_start_time']
        return 0.0
        
    def get_year_duration(self, year: str) -> float:
        """获取指定年份的处理时长"""
        year_timing = self.timing_stats['year_timings'].get(year, {})
        if 'start' in year_timing and 'end' in year_timing:
            return year_timing['end'] - year_timing['start']
        return 0.0
        
    def get_average_processing_rate(self) -> float:
        """获取平均处理速率（论文/秒）"""
        total_duration = self.get_total_duration()
        if total_duration > 0:
            return self.processing_stats['total_papers_processed'] / total_duration
        return 0.0
        
    def get_memory_peak_info(self) -> Dict[str, Any]:
        """获取内存峰值信息"""
        if not self.memory_stats['memory_samples']:
            return {'peak_memory_mb': 0, 'peak_year': None, 'peak_context': None}
            
        # 找到峰值内存样本
        peak_sample = max(self.memory_stats['memory_samples'], key=lambda x: x[2])
        
        return {
            'peak_memory_mb': peak_sample[2],
            'peak_year': peak_sample[1],
            'peak_context': peak_sample[3] if len(peak_sample) > 3 else None,
            'peak_timestamp': peak_sample[0]
        }
        
    def get_cache_efficiency_summary(self) -> Dict[str, Any]:
        """获取缓存效率摘要"""
        if not self.cache_stats['cache_efficiency_history']:
            return {'average_hit_rate': 0.0, 'average_memory_efficiency': 0.0, 'trend': 'unknown'}
            
        history = self.cache_stats['cache_efficiency_history']
        hit_rates = [item[1] for item in history]
        memory_efficiencies = [item[2] for item in history]
        
        avg_hit_rate = sum(hit_rates) / len(hit_rates)
        avg_memory_efficiency = sum(memory_efficiencies) / len(memory_efficiencies)
        
        # 计算趋势（最后25%与前25%比较）
        trend = 'stable'
        if len(hit_rates) >= 4:
            early_quarter = hit_rates[:len(hit_rates)//4]
            late_quarter = hit_rates[-len(hit_rates)//4:]
            early_avg = sum(early_quarter) / len(early_quarter)
            late_avg = sum(late_quarter) / len(late_quarter)
            
            if late_avg > early_avg * 1.1:
                trend = 'improving'
            elif late_avg < early_avg * 0.9:
                trend = 'declining'
                
        return {
            'average_hit_rate': avg_hit_rate,
            'average_memory_efficiency': avg_memory_efficiency,
            'trend': trend,
            'samples_count': len(history)
        }
        
    def get_filtering_efficiency_summary(self) -> Dict[str, Any]:
        """获取过滤效率摘要"""
        if not self.filtering_stats['filtering_efficiency_history']:
            return {'average_filter_rate': 0.0, 'average_performance_gain': 0.0, 'trend': 'unknown'}
            
        history = self.filtering_stats['filtering_efficiency_history']
        filter_rates = [item[1] for item in history]
        performance_gains = [item[2] for item in history]
        
        avg_filter_rate = sum(filter_rates) / len(filter_rates)
        avg_performance_gain = sum(performance_gains) / len(performance_gains)
        
        # 计算趋势
        trend = 'stable'
        if len(performance_gains) >= 4:
            early_quarter = performance_gains[:len(performance_gains)//4]
            late_quarter = performance_gains[-len(performance_gains)//4:]
            early_avg = sum(early_quarter) / len(early_quarter)
            late_avg = sum(late_quarter) / len(late_quarter)
            
            if late_avg > early_avg * 1.1:
                trend = 'improving'
            elif late_avg < early_avg * 0.9:
                trend = 'declining'
                
        return {
            'average_filter_rate': avg_filter_rate,
            'average_performance_gain': avg_performance_gain,
            'trend': trend,
            'samples_count': len(history)
        }
        
    def generate_comprehensive_report(self) -> Dict[str, Any]:
        """
        生成综合性能报告
        
        Returns:
            包含所有性能指标的综合报告
        """
        report = {
            'report_timestamp': time.time(),
            'report_date': datetime.now().isoformat(),
            
            # 时间统计摘要
            'timing_summary': {
                'total_duration_seconds': self.get_total_duration(),
                'total_years_processed': len(self.timing_stats['year_timings']),
                'average_year_duration': (
                    sum(self.get_year_duration(year) for year in self.timing_stats['year_timings']) /
                    max(len(self.timing_stats['year_timings']), 1)
                ),
                'fastest_year': None,
                'slowest_year': None
            },
            
            # 处理统计摘要
            'processing_summary': {
                'total_papers': self.processing_stats['total_papers_processed'],
                'total_rpus': self.processing_stats['total_rpus_processed'],
                'average_processing_rate': self.get_average_processing_rate(),
                'papers_per_year_stats': {
                    'min': min(self.processing_stats['papers_per_year'].values()) if self.processing_stats['papers_per_year'] else 0,
                    'max': max(self.processing_stats['papers_per_year'].values()) if self.processing_stats['papers_per_year'] else 0,
                    'average': (sum(self.processing_stats['papers_per_year'].values()) / 
                              max(len(self.processing_stats['papers_per_year']), 1))
                }
            },
            
            # 内存使用摘要
            'memory_summary': self.get_memory_peak_info(),
            
            # 缓存效率摘要
            'cache_summary': self.get_cache_efficiency_summary(),
            
            # 过滤效率摘要
            'filtering_summary': self.get_filtering_efficiency_summary(),
            
            # 里程碑摘要
            'milestones_summary': {
                'total_milestones': len(self.milestones),
                'milestone_types': list(set(m['type'] for m in self.milestones)),
                'recent_milestones': self.milestones[-5:] if self.milestones else []
            }
        }
        
        # 计算最快/最慢年份
        if self.timing_stats['year_timings']:
            year_durations = {year: self.get_year_duration(year) 
                            for year in self.timing_stats['year_timings']}
            if year_durations:
                fastest_year = min(year_durations.items(), key=lambda x: x[1])
                slowest_year = max(year_durations.items(), key=lambda x: x[1])
                report['timing_summary']['fastest_year'] = {
                    'year': fastest_year[0], 'duration': fastest_year[1]
                }
                report['timing_summary']['slowest_year'] = {
                    'year': slowest_year[0], 'duration': slowest_year[1]
                }
                
        return report
        
    def export_detailed_metrics(self, output_path: str) -> None:
        """
        导出详细的性能指标数据到JSON文件
        
        Args:
            output_path: 输出文件路径
        """
        detailed_data = {
            'export_timestamp': time.time(),
            'export_date': datetime.now().isoformat(),
            'timing_stats': self.timing_stats,
            'memory_stats': self.memory_stats,
            'cache_stats': self.cache_stats,
            'processing_stats': self.processing_stats,
            'filtering_stats': self.filtering_stats,
            'milestones': self.milestones,
            'comprehensive_report': self.generate_comprehensive_report()
        }
        
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(detailed_data, f, indent=2, ensure_ascii=False)
            logger.info(f"详细性能指标已导出到: {output_path}")
        except Exception as e:
            logger.error(f"导出性能指标失败: {e}")
            
    def log_performance_summary(self, log_level: int = logging.INFO) -> None:
        """
        记录性能摘要到日志
        
        Args:
            log_level: 日志级别
        """
        report = self.generate_comprehensive_report()
        
        logger.log(log_level, "=== 性能监控摘要 ===")
        logger.log(log_level, f"总处理时间: {report['timing_summary']['total_duration_seconds']:.2f}s")
        logger.log(log_level, f"处理年份数: {report['timing_summary']['total_years_processed']}")
        logger.log(log_level, f"总论文数: {report['processing_summary']['total_papers']:,}")
        logger.log(log_level, f"总RPU数: {report['processing_summary']['total_rpus']:,}")
        logger.log(log_level, f"平均处理速率: {report['processing_summary']['average_processing_rate']:.1f} 论文/秒")
        
        if report['memory_summary']['peak_memory_mb'] > 0:
            logger.log(log_level, f"峰值内存: {report['memory_summary']['peak_memory_mb']:.1f}MB "
                      f"(年份: {report['memory_summary']['peak_year']})")
                      
        if report['cache_summary']['samples_count'] > 0:
            logger.log(log_level, f"平均缓存命中率: {report['cache_summary']['average_hit_rate']:.3f}")
            logger.log(log_level, f"缓存效率趋势: {report['cache_summary']['trend']}")
            
        if report['filtering_summary']['samples_count'] > 0:
            logger.log(log_level, f"平均过滤率: {report['filtering_summary']['average_filter_rate']:.3f}")
            logger.log(log_level, f"过滤效率趋势: {report['filtering_summary']['trend']}")
            
        logger.log(log_level, f"记录里程碑数: {report['milestones_summary']['total_milestones']}")