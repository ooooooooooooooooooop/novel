"""
进度监控系统

实现实时进度跟踪、状态反馈和通知系统，以及性能指标收集。
"""

import time
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable, Union, Tuple
from enum import Enum
import json
import logging
from pathlib import Path
import queue
from collections import deque

from ..core.data_models import DetectionState, ProcessingStatus
from ..core.exceptions import AnomalyDetectionException


class NotificationType(Enum):
    """通知类型"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"
    PROGRESS = "progress"


class MetricType(Enum):
    """指标类型"""
    COUNTER = "counter"        # 计数器
    GAUGE = "gauge"           # 仪表盘
    HISTOGRAM = "histogram"   # 直方图
    TIMER = "timer"          # 计时器


@dataclass
class ProgressSnapshot:
    """进度快照"""
    timestamp: datetime
    session_id: str
    current_shard: int
    total_shards: int
    processed_records: int
    total_records: int
    detected_anomalies: int
    progress_percentage: float
    elapsed_time: float
    estimated_remaining_time: Optional[float]
    processing_rate: float  # 记录/秒
    memory_usage_mb: float
    cpu_usage_percent: float
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'session_id': self.session_id,
            'current_shard': self.current_shard,
            'total_shards': self.total_shards,
            'processed_records': self.processed_records,
            'total_records': self.total_records,
            'detected_anomalies': self.detected_anomalies,
            'progress_percentage': self.progress_percentage,
            'elapsed_time': self.elapsed_time,
            'estimated_remaining_time': self.estimated_remaining_time,
            'processing_rate': self.processing_rate,
            'memory_usage_mb': self.memory_usage_mb,
            'cpu_usage_percent': self.cpu_usage_percent
        }


@dataclass
class Notification:
    """通知消息"""
    notification_type: NotificationType
    title: str
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'type': self.notification_type.value,
            'title': self.title,
            'message': self.message,
            'timestamp': self.timestamp.isoformat(),
            'session_id': self.session_id,
            'metadata': self.metadata
        }


@dataclass
class PerformanceMetric:
    """性能指标"""
    name: str
    metric_type: MetricType
    value: Union[int, float]
    timestamp: datetime = field(default_factory=datetime.now)
    tags: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'name': self.name,
            'type': self.metric_type.value,
            'value': self.value,
            'timestamp': self.timestamp.isoformat(),
            'tags': self.tags
        }


class ProgressTracker:
    """进度跟踪器
    
    跟踪检测过程的进度信息，计算处理速度和剩余时间。
    """
    
    def __init__(self, session_id: str):
        """初始化进度跟踪器
        
        Args:
            session_id: 会话ID
        """
        self.session_id = session_id
        self.start_time = datetime.now()
        self.last_update_time = self.start_time
        
        # 进度历史记录（用于计算平均速度）
        self.progress_history: deque = deque(maxlen=100)  # 这是经验值，保留最近100个进度点
        
        # 当前状态
        self.current_state: Optional[DetectionState] = None
        
        # 性能统计
        self.total_processing_time = 0.0
        self.peak_memory_usage = 0.0
        self.peak_cpu_usage = 0.0
    
    def update_progress(self, state: DetectionState) -> ProgressSnapshot:
        """更新进度信息
        
        Args:
            state: 当前检测状态
            
        Returns:
            ProgressSnapshot: 进度快照
        """
        now = datetime.now()
        self.current_state = state
        
        # 计算基本进度信息
        progress_percentage = state.get_progress_percentage()
        elapsed_time = state.get_elapsed_time()
        estimated_remaining = state.estimate_remaining_time()
        
        # 计算处理速度
        processing_rate = self._calculate_processing_rate(state, now)
        
        # 获取系统资源使用情况
        memory_usage = self._get_memory_usage()
        cpu_usage = self._get_cpu_usage()
        
        # 更新峰值统计
        self.peak_memory_usage = max(self.peak_memory_usage, memory_usage)
        self.peak_cpu_usage = max(self.peak_cpu_usage, cpu_usage)
        
        # 创建进度快照
        snapshot = ProgressSnapshot(
            timestamp=now,
            session_id=self.session_id,
            current_shard=state.current_shard,
            total_shards=state.total_shards,
            processed_records=state.processed_records,
            total_records=state.total_records,
            detected_anomalies=state.detected_anomalies,
            progress_percentage=progress_percentage,
            elapsed_time=elapsed_time,
            estimated_remaining_time=estimated_remaining,
            processing_rate=processing_rate,
            memory_usage_mb=memory_usage,
            cpu_usage_percent=cpu_usage
        )
        
        # 添加到历史记录
        self.progress_history.append((now, state.processed_records))
        self.last_update_time = now
        
        return snapshot
    
    def _calculate_processing_rate(self, state: DetectionState, current_time: datetime) -> float:
        """计算处理速度（记录/秒）
        
        Args:
            state: 当前状态
            current_time: 当前时间
            
        Returns:
            float: 处理速度
        """
        if len(self.progress_history) < 2:
            # 历史记录不足，使用总体平均速度
            elapsed = (current_time - max(self.start_time, state.start_time)).total_seconds()
            if elapsed > 0:
                return state.processed_records / elapsed
            return 0.0
        
        # 使用最近的进度点计算瞬时速度
        recent_time, recent_records = self.progress_history[-1]
        time_diff = (current_time - recent_time).total_seconds()
        
        if time_diff > 0:
            record_diff = state.processed_records - recent_records
            # 确保处理速度不为负数
            return max(0.0, record_diff / time_diff)
        
        return 0.0
    
    def _get_memory_usage(self) -> float:
        """获取内存使用量（MB）
        
        Returns:
            float: 内存使用量
        """
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024  # 转换为MB
        except ImportError:
            # psutil不可用时返回0
            return 0.0
    
    def _get_cpu_usage(self) -> float:
        """获取CPU使用率（百分比）
        
        Returns:
            float: CPU使用率
        """
        try:
            import psutil
            return psutil.cpu_percent(interval=None)
        except ImportError:
            # psutil不可用时返回0
            return 0.0
    
    def get_summary_stats(self) -> Dict[str, Any]:
        """获取汇总统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        if not self.current_state:
            return {}
        
        elapsed = (datetime.now() - self.start_time).total_seconds()
        
        return {
            'session_id': self.session_id,
            'total_elapsed_time': elapsed,
            'peak_memory_usage_mb': self.peak_memory_usage,
            'peak_cpu_usage_percent': self.peak_cpu_usage,
            'average_processing_rate': (
                self.current_state.processed_records / elapsed 
                if elapsed > 0 else 0.0
            ),
            'total_processed_records': self.current_state.processed_records,
            'total_detected_anomalies': self.current_state.detected_anomalies,
            'anomaly_detection_rate': (
                self.current_state.detected_anomalies / self.current_state.processed_records
                if self.current_state.processed_records > 0 else 0.0
            )
        }


class NotificationManager:
    """通知管理器
    
    管理系统通知的发送和存储。
    """
    
    def __init__(self, max_notifications: int = 1000):  # 这是经验值，保留最近1000条通知
        """初始化通知管理器
        
        Args:
            max_notifications: 最大通知数量
        """
        self.max_notifications = max_notifications
        self.notifications: deque = deque(maxlen=max_notifications)
        self.subscribers: List[Callable[[Notification], None]] = []
        self.logger = logging.getLogger(__name__)
    
    def subscribe(self, callback: Callable[[Notification], None]) -> None:
        """订阅通知
        
        Args:
            callback: 通知回调函数
        """
        self.subscribers.append(callback)
    
    def unsubscribe(self, callback: Callable[[Notification], None]) -> None:
        """取消订阅通知
        
        Args:
            callback: 通知回调函数
        """
        if callback in self.subscribers:
            self.subscribers.remove(callback)
    
    def send_notification(self, notification: Notification) -> None:
        """发送通知
        
        Args:
            notification: 通知消息
        """
        # 存储通知
        self.notifications.append(notification)
        
        # 记录日志
        log_level = {
            NotificationType.INFO: logging.INFO,
            NotificationType.WARNING: logging.WARNING,
            NotificationType.ERROR: logging.ERROR,
            NotificationType.SUCCESS: logging.INFO,
            NotificationType.PROGRESS: logging.DEBUG
        }.get(notification.notification_type, logging.INFO)
        
        self.logger.log(log_level, f"{notification.title}: {notification.message}")
        
        # 通知订阅者
        for callback in self.subscribers:
            try:
                callback(notification)
            except Exception as e:
                self.logger.error(f"通知回调执行失败: {e}")
    
    def get_notifications(self, 
                         notification_type: Optional[NotificationType] = None,
                         session_id: Optional[str] = None,
                         limit: Optional[int] = None) -> List[Notification]:
        """获取通知列表
        
        Args:
            notification_type: 通知类型过滤
            session_id: 会话ID过滤
            limit: 数量限制
            
        Returns:
            List[Notification]: 通知列表
        """
        notifications = list(self.notifications)
        
        # 应用过滤条件
        if notification_type:
            notifications = [n for n in notifications if n.notification_type == notification_type]
        
        if session_id:
            notifications = [n for n in notifications if n.session_id == session_id]
        
        # 按时间倒序排列
        notifications.sort(key=lambda x: x.timestamp, reverse=True)
        
        # 应用数量限制
        if limit:
            notifications = notifications[:limit]
        
        return notifications


class MetricsCollector:
    """性能指标收集器
    
    收集和存储系统性能指标。
    """
    
    def __init__(self, max_metrics: int = 10000):  # 这是经验值，保留最近10000个指标
        """初始化指标收集器
        
        Args:
            max_metrics: 最大指标数量
        """
        self.max_metrics = max_metrics
        self.metrics: deque = deque(maxlen=max_metrics)
        self.metric_aggregates: Dict[str, Dict[str, Any]] = {}
        self.logger = logging.getLogger(__name__)
    
    def record_metric(self, metric: PerformanceMetric) -> None:
        """记录性能指标
        
        Args:
            metric: 性能指标
        """
        self.metrics.append(metric)
        
        # 更新聚合统计
        self._update_aggregates(metric)
        
        self.logger.debug(f"记录指标: {metric.name} = {metric.value}")
    
    def record_counter(self, name: str, value: int = 1, tags: Optional[Dict[str, str]] = None) -> None:
        """记录计数器指标
        
        Args:
            name: 指标名称
            value: 计数值
            tags: 标签
        """
        metric = PerformanceMetric(
            name=name,
            metric_type=MetricType.COUNTER,
            value=value,
            tags=tags or {}
        )
        self.record_metric(metric)
    
    def record_gauge(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """记录仪表盘指标
        
        Args:
            name: 指标名称
            value: 数值
            tags: 标签
        """
        metric = PerformanceMetric(
            name=name,
            metric_type=MetricType.GAUGE,
            value=value,
            tags=tags or {}
        )
        self.record_metric(metric)
    
    def record_timer(self, name: str, duration: float, tags: Optional[Dict[str, str]] = None) -> None:
        """记录计时器指标
        
        Args:
            name: 指标名称
            duration: 持续时间（秒）
            tags: 标签
        """
        metric = PerformanceMetric(
            name=name,
            metric_type=MetricType.TIMER,
            value=duration,
            tags=tags or {}
        )
        self.record_metric(metric)
    
    def _update_aggregates(self, metric: PerformanceMetric) -> None:
        """更新聚合统计
        
        Args:
            metric: 性能指标
        """
        key = f"{metric.name}:{metric.metric_type.value}"
        
        if key not in self.metric_aggregates:
            self.metric_aggregates[key] = {
                'count': 0,
                'sum': 0.0,
                'min': float('inf'),
                'max': float('-inf'),
                'avg': 0.0
            }
        
        agg = self.metric_aggregates[key]
        agg['count'] += 1
        agg['sum'] += metric.value
        agg['min'] = min(agg['min'], metric.value)
        agg['max'] = max(agg['max'], metric.value)
        agg['avg'] = agg['sum'] / agg['count']
    
    def get_metrics(self, 
                   name_pattern: Optional[str] = None,
                   metric_type: Optional[MetricType] = None,
                   time_range: Optional[Tuple[datetime, datetime]] = None,
                   limit: Optional[int] = None) -> List[PerformanceMetric]:
        """获取指标列表
        
        Args:
            name_pattern: 名称模式过滤
            metric_type: 指标类型过滤
            time_range: 时间范围过滤
            limit: 数量限制
            
        Returns:
            List[PerformanceMetric]: 指标列表
        """
        metrics = list(self.metrics)
        
        # 应用过滤条件
        if name_pattern:
            metrics = [m for m in metrics if name_pattern in m.name]
        
        if metric_type:
            metrics = [m for m in metrics if m.metric_type == metric_type]
        
        if time_range:
            start_time, end_time = time_range
            metrics = [m for m in metrics if start_time <= m.timestamp <= end_time]
        
        # 按时间倒序排列
        metrics.sort(key=lambda x: x.timestamp, reverse=True)
        
        # 应用数量限制
        if limit:
            metrics = metrics[:limit]
        
        return metrics
    
    def get_aggregates(self) -> Dict[str, Dict[str, Any]]:
        """获取聚合统计
        
        Returns:
            Dict[str, Dict[str, Any]]: 聚合统计
        """
        return self.metric_aggregates.copy()


class ProgressMonitor:
    """进度监控系统
    
    集成进度跟踪、通知管理和指标收集的完整监控系统。
    """
    
    def __init__(self, session_id: str, config: Optional[Dict[str, Any]] = None):
        """初始化进度监控系统
        
        Args:
            session_id: 会话ID
            config: 配置参数
        """
        self.session_id = session_id
        self.config = config or {}
        
        # 初始化组件
        self.progress_tracker = ProgressTracker(session_id)
        self.notification_manager = NotificationManager(
            max_notifications=self.config.get('max_notifications', 1000)
        )
        self.metrics_collector = MetricsCollector(
            max_metrics=self.config.get('max_metrics', 10000)
        )
        
        # 监控线程
        self.monitoring_thread: Optional[threading.Thread] = None
        self.monitoring_active = False
        self.monitoring_interval = self.config.get('monitoring_interval', 5.0)  # 这是经验值，5秒监控间隔
        
        # 进度快照历史
        self.progress_snapshots: deque = deque(maxlen=self.config.get('max_snapshots', 1000))
        
        self.logger = logging.getLogger(__name__)
    
    def start_monitoring(self) -> None:
        """启动监控"""
        if self.monitoring_active:
            return
        
        self.monitoring_active = True
        self.monitoring_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitoring_thread.start()
        
        self.send_notification(
            NotificationType.INFO,
            "监控启动",
            f"会话 {self.session_id} 的进度监控已启动"
        )
        
        self.logger.info(f"进度监控已启动，会话ID: {self.session_id}")
    
    def stop_monitoring(self) -> None:
        """停止监控"""
        if not self.monitoring_active:
            return
        
        self.monitoring_active = False
        
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            self.monitoring_thread.join(timeout=10.0)  # 这是经验值，10秒超时
        
        self.send_notification(
            NotificationType.INFO,
            "监控停止",
            f"会话 {self.session_id} 的进度监控已停止"
        )
        
        self.logger.info(f"进度监控已停止，会话ID: {self.session_id}")
    
    def update_progress(self, state: DetectionState) -> ProgressSnapshot:
        """更新进度
        
        Args:
            state: 检测状态
            
        Returns:
            ProgressSnapshot: 进度快照
        """
        snapshot = self.progress_tracker.update_progress(state)
        self.progress_snapshots.append(snapshot)
        
        # 记录进度指标
        self.metrics_collector.record_gauge("progress_percentage", snapshot.progress_percentage)
        self.metrics_collector.record_gauge("processing_rate", snapshot.processing_rate)
        self.metrics_collector.record_gauge("memory_usage_mb", snapshot.memory_usage_mb)
        self.metrics_collector.record_gauge("cpu_usage_percent", snapshot.cpu_usage_percent)
        self.metrics_collector.record_counter("processed_records", snapshot.processed_records)
        self.metrics_collector.record_counter("detected_anomalies", snapshot.detected_anomalies)
        
        # 发送进度通知
        if snapshot.progress_percentage % 10 == 0:  # 这是经验值，每10%发送一次通知
            self.send_notification(
                NotificationType.PROGRESS,
                "进度更新",
                f"已完成 {snapshot.progress_percentage:.1f}%，"
                f"处理速度: {snapshot.processing_rate:.1f} 记录/秒"
            )
        
        return snapshot
    
    def send_notification(self, 
                         notification_type: NotificationType,
                         title: str,
                         message: str,
                         metadata: Optional[Dict[str, Any]] = None) -> None:
        """发送通知
        
        Args:
            notification_type: 通知类型
            title: 标题
            message: 消息
            metadata: 元数据
        """
        notification = Notification(
            notification_type=notification_type,
            title=title,
            message=message,
            session_id=self.session_id,
            metadata=metadata or {}
        )
        
        self.notification_manager.send_notification(notification)
    
    def _monitoring_loop(self) -> None:
        """监控循环"""
        while self.monitoring_active:
            try:
                # 收集系统指标
                self._collect_system_metrics()
                
                # 检查异常情况
                self._check_anomalous_conditions()
                
                time.sleep(self.monitoring_interval)
                
            except Exception as e:
                self.logger.error(f"监控循环异常: {e}")
                time.sleep(self.monitoring_interval)
    
    def _collect_system_metrics(self) -> None:
        """收集系统指标"""
        try:
            import psutil
            
            # CPU和内存使用率
            cpu_percent = psutil.cpu_percent(interval=None)
            memory_info = psutil.virtual_memory()
            
            self.metrics_collector.record_gauge("system_cpu_percent", cpu_percent)
            self.metrics_collector.record_gauge("system_memory_percent", memory_info.percent)
            self.metrics_collector.record_gauge("system_memory_available_mb", 
                                               memory_info.available / 1024 / 1024)
            
            # 磁盘使用率
            disk_usage = psutil.disk_usage('/')
            self.metrics_collector.record_gauge("system_disk_percent", 
                                               (disk_usage.used / disk_usage.total) * 100)
            
        except ImportError:
            # psutil不可用时跳过系统指标收集
            pass
        except Exception as e:
            self.logger.warning(f"系统指标收集失败: {e}")
    
    def _check_anomalous_conditions(self) -> None:
        """检查异常情况"""
        if not self.progress_snapshots:
            return
        
        latest_snapshot = self.progress_snapshots[-1]
        
        # 检查内存使用过高
        if latest_snapshot.memory_usage_mb > self.config.get('memory_warning_threshold', 3000):  # 这是经验值，3GB内存警告阈值
            self.send_notification(
                NotificationType.WARNING,
                "内存使用过高",
                f"当前内存使用: {latest_snapshot.memory_usage_mb:.1f} MB"
            )
        
        # 检查处理速度过慢
        if (latest_snapshot.processing_rate < self.config.get('speed_warning_threshold', 100) and  # 这是经验值，100记录/秒警告阈值
            latest_snapshot.processed_records > 1000):  # 这是经验值，处理1000条记录后才检查速度
            self.send_notification(
                NotificationType.WARNING,
                "处理速度过慢",
                f"当前处理速度: {latest_snapshot.processing_rate:.1f} 记录/秒"
            )
        
        # 检查CPU使用过高
        if latest_snapshot.cpu_usage_percent > self.config.get('cpu_warning_threshold', 90):  # 这是经验值，90% CPU警告阈值
            self.send_notification(
                NotificationType.WARNING,
                "CPU使用过高",
                f"当前CPU使用率: {latest_snapshot.cpu_usage_percent:.1f}%"
            )
    
    def get_current_status(self) -> Dict[str, Any]:
        """获取当前状态
        
        Returns:
            Dict[str, Any]: 当前状态信息
        """
        if not self.progress_snapshots:
            return {'status': 'no_data'}
        
        latest_snapshot = self.progress_snapshots[-1]
        summary_stats = self.progress_tracker.get_summary_stats()
        
        return {
            'session_id': self.session_id,
            'monitoring_active': self.monitoring_active,
            'latest_snapshot': latest_snapshot.to_dict(),
            'summary_stats': summary_stats,
            'total_notifications': len(self.notification_manager.notifications),
            'total_metrics': len(self.metrics_collector.metrics)
        }
    
    def export_monitoring_data(self, output_path: Path) -> None:
        """导出监控数据
        
        Args:
            output_path: 输出路径
        """
        try:
            monitoring_data = {
                'session_id': self.session_id,
                'export_timestamp': datetime.now().isoformat(),
                'progress_snapshots': [s.to_dict() for s in self.progress_snapshots],
                'notifications': [n.to_dict() for n in self.notification_manager.notifications],
                'metrics': [m.to_dict() for m in self.metrics_collector.metrics],
                'metric_aggregates': self.metrics_collector.get_aggregates(),
                'summary_stats': self.progress_tracker.get_summary_stats()
            }
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(monitoring_data, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"监控数据已导出到: {output_path}")
            
        except Exception as e:
            self.logger.error(f"导出监控数据失败: {e}")
            raise AnomalyDetectionException(f"导出失败: {e}")