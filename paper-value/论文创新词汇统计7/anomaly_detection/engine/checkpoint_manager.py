"""
检查点和状态管理系统

实现状态序列化、恢复机制、进度跟踪和异常恢复功能。
"""

import pickle
import json
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable, TypeVar, Tuple
from dataclasses import dataclass, field, asdict
import hashlib
import shutil

from ..core.config import DetectionConfig
from ..core.data_models import DetectionResult, DetectionSession, ProcessingStatus
from ..core.exceptions import CheckpointException, ResourceException
from ..core.logging import get_logger
from ..core.error_recovery import DetectionState

T = TypeVar('T')


@dataclass
class CheckpointMetadata:
    """检查点元数据"""
    checkpoint_id: str
    session_id: str
    creation_time: datetime
    file_size: int
    record_count: int
    progress_percentage: float
    config_hash: str
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'checkpoint_id': self.checkpoint_id,
            'session_id': self.session_id,
            'creation_time': self.creation_time.isoformat(),
            'file_size': self.file_size,
            'record_count': self.record_count,
            'progress_percentage': self.progress_percentage,
            'config_hash': self.config_hash,
            'description': self.description
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CheckpointMetadata':
        """从字典创建"""
        data['creation_time'] = datetime.fromisoformat(data['creation_time'])
        return cls(**data)


@dataclass
class ProgressSnapshot:
    """进度快照"""
    timestamp: datetime
    processed_count: int
    total_count: int
    current_step: str
    processing_speed: float  # 记录/秒
    memory_usage_mb: float
    anomalies_found: int
    
    def get_progress_percentage(self) -> float:
        """获取进度百分比"""
        if self.total_count == 0:
            return 0.0
        return (self.processed_count / self.total_count) * 100.0
    
    def get_eta_seconds(self) -> Optional[float]:
        """估算剩余时间（秒）"""
        if self.processing_speed <= 0 or self.processed_count >= self.total_count:
            return None
        
        remaining_records = self.total_count - self.processed_count
        return remaining_records / self.processing_speed


class ProgressTracker:
    """进度跟踪器
    
    实时跟踪检测进度，提供性能监控和ETA估算。
    """
    
    def __init__(self, total_count: int, update_interval: float = 5.0):
        """初始化进度跟踪器
        
        Args:
            total_count: 总记录数
            update_interval: 更新间隔（秒），这是经验值，可根据需要调整
        """
        self.total_count = total_count
        self.update_interval = update_interval
        
        # 进度状态
        self.processed_count = 0
        self.current_step = "initialization"
        self.start_time = datetime.now()
        self.last_update_time = self.start_time
        self.anomalies_found = 0
        
        # 性能监控
        self.snapshots: List[ProgressSnapshot] = []
        self.max_snapshots = 100  # 最多保留100个快照，这是经验值
        
        # 线程安全
        self._lock = threading.Lock()
        
        self.logger = get_logger(self.__class__.__name__)
    
    def update_progress(self, processed_count: int, current_step: str = None, 
                       anomalies_found: int = None) -> None:
        """更新进度
        
        Args:
            processed_count: 已处理记录数
            current_step: 当前步骤
            anomalies_found: 发现的异常数量
        """
        with self._lock:
            now = datetime.now()
            
            # 更新基本信息
            self.processed_count = processed_count
            if current_step:
                self.current_step = current_step
            if anomalies_found is not None:
                self.anomalies_found = anomalies_found
            
            # 计算处理速度
            time_elapsed = (now - self.last_update_time).total_seconds()
            if time_elapsed >= self.update_interval:
                # 计算自上次更新以来的处理速度
                if len(self.snapshots) > 0:
                    last_snapshot = self.snapshots[-1]
                    records_processed = processed_count - last_snapshot.processed_count
                    processing_speed = records_processed / time_elapsed if time_elapsed > 0 else 0
                else:
                    # 第一次更新，计算从开始的平均速度
                    total_elapsed = (now - self.start_time).total_seconds()
                    processing_speed = processed_count / total_elapsed if total_elapsed > 0 else 0
                
                # 获取内存使用情况
                memory_usage = self._get_memory_usage()
                
                # 创建快照
                snapshot = ProgressSnapshot(
                    timestamp=now,
                    processed_count=processed_count,
                    total_count=self.total_count,
                    current_step=self.current_step,
                    processing_speed=processing_speed,
                    memory_usage_mb=memory_usage,
                    anomalies_found=self.anomalies_found
                )
                
                self.snapshots.append(snapshot)
                
                # 限制快照数量
                if len(self.snapshots) > self.max_snapshots:
                    self.snapshots.pop(0)
                
                self.last_update_time = now
                
                # 记录进度日志
                progress_pct = snapshot.get_progress_percentage()
                eta = snapshot.get_eta_seconds()
                eta_str = f"{eta/60:.1f}分钟" if eta else "未知"
                
                self.logger.info(
                    f"进度: {progress_pct:.1f}% ({processed_count}/{self.total_count}), "
                    f"速度: {processing_speed:.1f} 记录/秒, "
                    f"预计剩余时间: {eta_str}, "
                    f"内存使用: {memory_usage:.1f}MB, "
                    f"发现异常: {self.anomalies_found}"
                )
    
    def _get_memory_usage(self) -> float:
        """获取内存使用情况（MB）"""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            return 0.0
        except Exception:
            return 0.0
    
    def get_current_snapshot(self) -> ProgressSnapshot:
        """获取当前进度快照"""
        with self._lock:
            memory_usage = self._get_memory_usage()
            
            # 计算当前处理速度
            if len(self.snapshots) > 0:
                last_snapshot = self.snapshots[-1]
                time_elapsed = (datetime.now() - last_snapshot.timestamp).total_seconds()
                records_processed = self.processed_count - last_snapshot.processed_count
                processing_speed = records_processed / time_elapsed if time_elapsed > 0 else 0
            else:
                total_elapsed = (datetime.now() - self.start_time).total_seconds()
                processing_speed = self.processed_count / total_elapsed if total_elapsed > 0 else 0
            
            return ProgressSnapshot(
                timestamp=datetime.now(),
                processed_count=self.processed_count,
                total_count=self.total_count,
                current_step=self.current_step,
                processing_speed=processing_speed,
                memory_usage_mb=memory_usage,
                anomalies_found=self.anomalies_found
            )
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """获取性能统计信息"""
        with self._lock:
            if not self.snapshots:
                return {}
            
            # 计算统计信息
            speeds = [s.processing_speed for s in self.snapshots if s.processing_speed > 0]
            memory_usages = [s.memory_usage_mb for s in self.snapshots]
            
            current_snapshot = self.get_current_snapshot()
            
            return {
                'total_runtime_seconds': (datetime.now() - self.start_time).total_seconds(),
                'current_progress_percentage': current_snapshot.get_progress_percentage(),
                'current_processing_speed': current_snapshot.processing_speed,
                'average_processing_speed': sum(speeds) / len(speeds) if speeds else 0,
                'max_processing_speed': max(speeds) if speeds else 0,
                'min_processing_speed': min(speeds) if speeds else 0,
                'current_memory_usage_mb': current_snapshot.memory_usage_mb,
                'average_memory_usage_mb': sum(memory_usages) / len(memory_usages) if memory_usages else 0,
                'max_memory_usage_mb': max(memory_usages) if memory_usages else 0,
                'eta_seconds': current_snapshot.get_eta_seconds(),
                'anomalies_found': self.anomalies_found,
                'snapshots_count': len(self.snapshots)
            }


class CheckpointManager:
    """检查点管理器
    
    负责创建、保存、恢复和管理检测过程的检查点。
    """
    
    def __init__(self, checkpoints_dir: str, config: DetectionConfig):
        """初始化检查点管理器
        
        Args:
            checkpoints_dir: 检查点目录
            config: 检测配置
        """
        self.checkpoints_dir = Path(checkpoints_dir)
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        self.config = config
        
        # 元数据管理
        self.metadata_file = self.checkpoints_dir / "checkpoints_metadata.json"
        self.metadata: Dict[str, CheckpointMetadata] = {}
        self._load_metadata()
        
        # 自动清理配置
        self.max_checkpoints_per_session = config.performance.max_checkpoints
        self.max_checkpoint_age_days = 7  # 检查点最大保留天数，这是经验值
        
        # 线程安全
        self._lock = threading.Lock()
        
        self.logger = get_logger(self.__class__.__name__)
    
    def _load_metadata(self) -> None:
        """加载检查点元数据"""
        try:
            if self.metadata_file.exists():
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    metadata_dict = json.load(f)
                
                self.metadata = {
                    k: CheckpointMetadata.from_dict(v) 
                    for k, v in metadata_dict.items()
                }
                
                self.logger.info(f"加载了 {len(self.metadata)} 个检查点元数据")
        
        except Exception as e:
            self.logger.error(f"加载检查点元数据失败: {e}")
            self.metadata = {}
    
    def _save_metadata(self) -> None:
        """保存检查点元数据"""
        try:
            metadata_dict = {
                k: v.to_dict() 
                for k, v in self.metadata.items()
            }
            
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata_dict, f, indent=2, ensure_ascii=False)
        
        except Exception as e:
            self.logger.error(f"保存检查点元数据失败: {e}")
    
    def create_checkpoint(self, detection_state: DetectionState, 
                         results: List[DetectionResult] = None,
                         description: str = "") -> str:
        """创建检查点
        
        Args:
            detection_state: 检测状态
            results: 当前检测结果
            description: 检查点描述
            
        Returns:
            检查点ID
            
        Raises:
            CheckpointException: 创建检查点失败
        """
        try:
            with self._lock:
                # 生成检查点ID
                timestamp = int(time.time())
                checkpoint_id = f"{detection_state.session_id}_{timestamp}"
                
                # 准备检查点数据
                checkpoint_data = {
                    'detection_state': asdict(detection_state),
                    'results': [asdict(result) for result in (results or [])],
                    'config_hash': self.config.get_config_hash(),
                    'creation_time': datetime.now().isoformat(),
                    'checkpoint_version': '1.0'
                }
                
                # 保存检查点文件
                checkpoint_file = self.checkpoints_dir / f"{checkpoint_id}.pkl"
                with open(checkpoint_file, 'wb') as f:
                    pickle.dump(checkpoint_data, f)
                
                # 创建元数据
                file_size = checkpoint_file.stat().st_size
                progress_pct = detection_state.get_progress_percentage()
                
                metadata = CheckpointMetadata(
                    checkpoint_id=checkpoint_id,
                    session_id=detection_state.session_id,
                    creation_time=datetime.now(),
                    file_size=file_size,
                    record_count=detection_state.processed_count,
                    progress_percentage=progress_pct,
                    config_hash=self.config.get_config_hash(),
                    description=description or f"自动检查点 - {progress_pct:.1f}%"
                )
                
                self.metadata[checkpoint_id] = metadata
                self._save_metadata()
                
                self.logger.info(f"创建检查点: {checkpoint_id} ({file_size} 字节)")
                
                # 清理旧检查点
                self._cleanup_old_checkpoints(detection_state.session_id)
                
                return checkpoint_id
        
        except Exception as e:
            raise CheckpointException(f"创建检查点失败: {e}",
                                    checkpoint_id=checkpoint_id,
                                    operation="create")
    
    def restore_checkpoint(self, checkpoint_id: str) -> Tuple[DetectionState, List[DetectionResult]]:
        """恢复检查点
        
        Args:
            checkpoint_id: 检查点ID
            
        Returns:
            (检测状态, 检测结果列表)
            
        Raises:
            CheckpointException: 恢复检查点失败
        """
        try:
            with self._lock:
                # 检查检查点是否存在
                if checkpoint_id not in self.metadata:
                    raise CheckpointException(f"检查点不存在: {checkpoint_id}",
                                            checkpoint_id=checkpoint_id,
                                            operation="restore")
                
                checkpoint_file = self.checkpoints_dir / f"{checkpoint_id}.pkl"
                if not checkpoint_file.exists():
                    raise CheckpointException(f"检查点文件不存在: {checkpoint_file}",
                                            checkpoint_id=checkpoint_id,
                                            operation="restore")
                
                # 加载检查点数据
                with open(checkpoint_file, 'rb') as f:
                    checkpoint_data = pickle.load(f)
                
                # 验证检查点版本
                version = checkpoint_data.get('checkpoint_version', '1.0')
                if version != '1.0':
                    self.logger.warning(f"检查点版本不匹配: {version}")
                
                # 重建检测状态
                state_dict = checkpoint_data['detection_state']
                detection_state = DetectionState(**state_dict)
                
                # 重建检测结果
                results = []
                for result_dict in checkpoint_data.get('results', []):
                    # 这里需要根据实际的DetectionResult结构进行重建
                    # 由于DetectionResult包含枚举类型，需要特殊处理
                    from ..core.data_models import AnomalySeverity, DetectionStatus
                    
                    result_dict['severity'] = AnomalySeverity(result_dict['severity'])
                    result_dict['status'] = DetectionStatus(result_dict['status'])
                    result_dict['detection_timestamp'] = datetime.fromisoformat(result_dict['detection_timestamp'])
                    
                    result = DetectionResult(**result_dict)
                    results.append(result)
                
                self.logger.info(f"恢复检查点: {checkpoint_id}，包含 {len(results)} 个结果")
                
                return detection_state, results
        
        except Exception as e:
            raise CheckpointException(f"恢复检查点失败: {e}",
                                    checkpoint_id=checkpoint_id,
                                    operation="restore")
    
    def list_checkpoints(self, session_id: Optional[str] = None) -> List[CheckpointMetadata]:
        """列出检查点
        
        Args:
            session_id: 会话ID，如果指定则只返回该会话的检查点
            
        Returns:
            检查点元数据列表
        """
        with self._lock:
            checkpoints = list(self.metadata.values())
            
            if session_id:
                checkpoints = [cp for cp in checkpoints if cp.session_id == session_id]
            
            # 按创建时间排序
            checkpoints.sort(key=lambda x: x.creation_time, reverse=True)
            
            return checkpoints
    
    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """删除检查点
        
        Args:
            checkpoint_id: 检查点ID
            
        Returns:
            是否删除成功
        """
        try:
            with self._lock:
                if checkpoint_id not in self.metadata:
                    return False
                
                # 删除文件
                checkpoint_file = self.checkpoints_dir / f"{checkpoint_id}.pkl"
                if checkpoint_file.exists():
                    checkpoint_file.unlink()
                
                # 删除元数据
                del self.metadata[checkpoint_id]
                self._save_metadata()
                
                self.logger.info(f"删除检查点: {checkpoint_id}")
                return True
        
        except Exception as e:
            self.logger.error(f"删除检查点失败 {checkpoint_id}: {e}")
            return False
    
    def _cleanup_old_checkpoints(self, session_id: str) -> None:
        """清理旧检查点
        
        Args:
            session_id: 会话ID
        """
        try:
            # 获取该会话的所有检查点
            session_checkpoints = [
                cp for cp in self.metadata.values() 
                if cp.session_id == session_id
            ]
            
            # 按创建时间排序
            session_checkpoints.sort(key=lambda x: x.creation_time, reverse=True)
            
            # 删除超出数量限制的检查点
            if len(session_checkpoints) > self.max_checkpoints_per_session:
                to_delete = session_checkpoints[self.max_checkpoints_per_session:]
                for cp in to_delete:
                    self.delete_checkpoint(cp.checkpoint_id)
            
            # 删除过期的检查点
            cutoff_date = datetime.now() - timedelta(days=self.max_checkpoint_age_days)
            expired_checkpoints = [
                cp for cp in self.metadata.values()
                if cp.creation_time < cutoff_date
            ]
            
            for cp in expired_checkpoints:
                self.delete_checkpoint(cp.checkpoint_id)
        
        except Exception as e:
            self.logger.error(f"清理旧检查点失败: {e}")
    
    def get_checkpoint_info(self, checkpoint_id: str) -> Optional[CheckpointMetadata]:
        """获取检查点信息
        
        Args:
            checkpoint_id: 检查点ID
            
        Returns:
            检查点元数据，如果不存在则返回None
        """
        return self.metadata.get(checkpoint_id)
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """获取存储统计信息
        
        Returns:
            存储统计信息
        """
        with self._lock:
            total_size = 0
            total_checkpoints = len(self.metadata)
            sessions = set()
            
            for metadata in self.metadata.values():
                total_size += metadata.file_size
                sessions.add(metadata.session_id)
            
            return {
                'total_checkpoints': total_checkpoints,
                'total_size_mb': total_size / 1024 / 1024,
                'unique_sessions': len(sessions),
                'checkpoints_dir': str(self.checkpoints_dir),
                'oldest_checkpoint': min(
                    (cp.creation_time for cp in self.metadata.values()),
                    default=None
                ),
                'newest_checkpoint': max(
                    (cp.creation_time for cp in self.metadata.values()),
                    default=None
                )
            }


class StateManager:
    """状态管理器
    
    统一管理检测状态、进度跟踪和检查点功能。
    """
    
    def __init__(self, config: DetectionConfig):
        """初始化状态管理器
        
        Args:
            config: 检测配置
        """
        self.config = config
        self.checkpoint_manager = CheckpointManager(
            config.paths.checkpoints_dir, 
            config
        )
        
        # 当前状态
        self.current_session: Optional[DetectionSession] = None
        self.progress_tracker: Optional[ProgressTracker] = None
        self.detection_results: List[DetectionResult] = []
        
        # 自动检查点配置
        self.auto_checkpoint_enabled = True
        self.checkpoint_interval = config.performance.checkpoint_interval
        self.last_checkpoint_count = 0
        
        self.logger = get_logger(self.__class__.__name__)
    
    def start_session(self, session: DetectionSession, total_count: int) -> None:
        """开始检测会话
        
        Args:
            session: 检测会话
            total_count: 总记录数
        """
        self.current_session = session
        self.progress_tracker = ProgressTracker(total_count)
        self.detection_results = []
        self.last_checkpoint_count = 0
        
        self.logger.info(f"开始检测会话: {session.session_id}")
    
    def update_progress(self, processed_count: int, current_step: str = None,
                       new_results: List[DetectionResult] = None) -> None:
        """更新进度
        
        Args:
            processed_count: 已处理记录数
            current_step: 当前步骤
            new_results: 新的检测结果
        """
        if not self.progress_tracker:
            return
        
        # 添加新结果
        if new_results:
            self.detection_results.extend(new_results)
        
        # 更新进度
        self.progress_tracker.update_progress(
            processed_count=processed_count,
            current_step=current_step,
            anomalies_found=len(self.detection_results)
        )
        
        # 检查是否需要自动创建检查点
        if (self.auto_checkpoint_enabled and 
            processed_count - self.last_checkpoint_count >= self.checkpoint_interval):
            self._create_auto_checkpoint(processed_count, current_step)
    
    def _create_auto_checkpoint(self, processed_count: int, current_step: str) -> None:
        """创建自动检查点
        
        Args:
            processed_count: 已处理记录数
            current_step: 当前步骤
        """
        try:
            if not self.current_session or not self.progress_tracker:
                return
            
            # 创建检测状态
            detection_state = DetectionState(
                session_id=self.current_session.session_id,
                current_step=current_step,
                processed_count=processed_count,
                total_count=self.progress_tracker.total_count,
                start_time=self.current_session.start_time,
                last_checkpoint_time=datetime.now(),
                metadata=self.progress_tracker.get_performance_stats()
            )
            
            # 创建检查点
            checkpoint_id = self.checkpoint_manager.create_checkpoint(
                detection_state=detection_state,
                results=self.detection_results,
                description=f"自动检查点 - {current_step}"
            )
            
            self.last_checkpoint_count = processed_count
            self.logger.info(f"创建自动检查点: {checkpoint_id}")
        
        except Exception as e:
            self.logger.error(f"创建自动检查点失败: {e}")
    
    def create_manual_checkpoint(self, description: str = "") -> str:
        """创建手动检查点
        
        Args:
            description: 检查点描述
            
        Returns:
            检查点ID
        """
        if not self.current_session or not self.progress_tracker:
            raise CheckpointException("没有活动的检测会话")
        
        current_snapshot = self.progress_tracker.get_current_snapshot()
        
        detection_state = DetectionState(
            session_id=self.current_session.session_id,
            current_step=current_snapshot.current_step,
            processed_count=current_snapshot.processed_count,
            total_count=current_snapshot.total_count,
            start_time=self.current_session.start_time,
            last_checkpoint_time=datetime.now(),
            metadata=self.progress_tracker.get_performance_stats()
        )
        
        return self.checkpoint_manager.create_checkpoint(
            detection_state=detection_state,
            results=self.detection_results,
            description=description or "手动检查点"
        )
    
    def restore_from_checkpoint(self, checkpoint_id: str) -> DetectionSession:
        """从检查点恢复
        
        Args:
            checkpoint_id: 检查点ID
            
        Returns:
            恢复的检测会话
        """
        detection_state, results = self.checkpoint_manager.restore_checkpoint(checkpoint_id)
        
        # 重建会话
        session = DetectionSession(
            session_id=detection_state.session_id,
            config_hash=self.config.get_config_hash(),
            start_time=detection_state.start_time,
            status=ProcessingStatus.RUNNING
        )
        
        # 重建进度跟踪器
        self.current_session = session
        self.progress_tracker = ProgressTracker(detection_state.total_count)
        self.progress_tracker.processed_count = detection_state.processed_count
        self.progress_tracker.current_step = detection_state.current_step
        self.progress_tracker.start_time = detection_state.start_time
        
        # 恢复结果
        self.detection_results = results
        
        self.logger.info(f"从检查点恢复会话: {session.session_id}")
        
        return session
    
    def get_current_status(self) -> Dict[str, Any]:
        """获取当前状态
        
        Returns:
            当前状态信息
        """
        if not self.current_session or not self.progress_tracker:
            return {'status': 'no_active_session'}
        
        current_snapshot = self.progress_tracker.get_current_snapshot()
        performance_stats = self.progress_tracker.get_performance_stats()
        
        return {
            'session_id': self.current_session.session_id,
            'session_status': self.current_session.status.value,
            'current_step': current_snapshot.current_step,
            'progress_percentage': current_snapshot.get_progress_percentage(),
            'processed_count': current_snapshot.processed_count,
            'total_count': current_snapshot.total_count,
            'processing_speed': current_snapshot.processing_speed,
            'memory_usage_mb': current_snapshot.memory_usage_mb,
            'anomalies_found': current_snapshot.anomalies_found,
            'eta_seconds': current_snapshot.get_eta_seconds(),
            'performance_stats': performance_stats,
            'available_checkpoints': len(self.checkpoint_manager.list_checkpoints(self.current_session.session_id))
        }
    
    def finish_session(self) -> None:
        """结束检测会话"""
        if self.current_session:
            self.current_session.end_time = datetime.now()
            self.current_session.status = ProcessingStatus.COMPLETED
            self.current_session.total_anomalies = len(self.detection_results)
            
            # 创建最终检查点
            if self.auto_checkpoint_enabled:
                try:
                    self.create_manual_checkpoint("会话完成")
                except Exception as e:
                    self.logger.error(f"创建最终检查点失败: {e}")
            
            self.logger.info(f"检测会话完成: {self.current_session.session_id}")
    
    def get_checkpoint_manager(self) -> CheckpointManager:
        """获取检查点管理器"""
        return self.checkpoint_manager