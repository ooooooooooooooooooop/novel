"""
错误恢复管理系统

提供异常处理、重试机制、检查点管理和降级处理功能。
"""

import time
import pickle
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Callable, TypeVar, Type, List
from dataclasses import dataclass, field

from .config import RecoveryConfig, RetryPolicy
from .exceptions import (
    AnomalyDetectionException, 
    CheckpointException,
    ResourceException
)
from .logging import get_logger

T = TypeVar('T')


@dataclass
class DetectionState:
    """检测状态数据结构
    
    用于保存和恢复检测过程的状态信息。
    """
    session_id: str
    current_step: str
    processed_count: int
    total_count: int
    start_time: datetime
    last_checkpoint_time: datetime
    detector_states: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_progress_percentage(self) -> float:
        """获取处理进度百分比"""
        if self.total_count == 0:
            return 0.0
        return (self.processed_count / self.total_count) * 100.0


@dataclass
class RecoveryAction:
    """恢复动作"""
    action_type: str  # retry, skip, abort, degrade
    retry_count: int = 0
    delay_seconds: float = 0.0
    degraded_mode: bool = False
    message: str = ""


class ErrorRecoveryManager:
    """错误恢复管理器
    
    负责异常处理、重试机制和状态恢复。
    """
    
    def __init__(self, config: RecoveryConfig, checkpoints_dir: str = "anomaly_checkpoints"):
        """初始化错误恢复管理器
        
        Args:
            config: 恢复配置
            checkpoints_dir: 检查点目录
        """
        self.config = config
        self.checkpoints_dir = Path(checkpoints_dir)
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger(self.__class__.__name__)
        
        # 重试计数器
        self._retry_counts: Dict[str, int] = {}
        
        # 降级模式状态
        self._degraded_mode = False
    
    def handle_exception(self, 
                        exception: Exception, 
                        context: Dict[str, Any],
                        operation_id: str) -> RecoveryAction:
        """处理异常并决定恢复策略
        
        Args:
            exception: 发生的异常
            context: 异常上下文信息
            operation_id: 操作标识符
            
        Returns:
            恢复动作
        """
        exception_type = type(exception).__name__
        self.logger.error(f"处理异常: {exception_type} - {str(exception)}", 
                         extra={'context': context, 'operation_id': operation_id})
        
        # 获取重试策略
        retry_policy = self.config.retry_policies.get(
            exception_type, 
            self.config.retry_policies.get('default', RetryPolicy())
        )
        
        # 获取当前重试次数
        retry_key = f"{operation_id}:{exception_type}"
        current_retries = self._retry_counts.get(retry_key, 0)
        
        # 决定恢复动作
        if current_retries < retry_policy.max_attempts:
            # 执行重试
            self._retry_counts[retry_key] = current_retries + 1
            delay = min(
                retry_policy.initial_delay * (retry_policy.backoff_factor ** current_retries),
                retry_policy.max_delay
            )
            
            self.logger.info(f"重试操作 {operation_id}，第 {current_retries + 1} 次，延迟 {delay} 秒")
            
            return RecoveryAction(
                action_type="retry",
                retry_count=current_retries + 1,
                delay_seconds=delay,
                message=f"重试第 {current_retries + 1} 次"
            )
        
        elif self.config.degraded_mode_enabled and not self._degraded_mode:
            # 启用降级模式
            self._degraded_mode = True
            self.logger.warning(f"启用降级模式处理操作 {operation_id}")
            
            return RecoveryAction(
                action_type="degrade",
                degraded_mode=True,
                message="启用降级模式继续处理"
            )
        
        else:
            # 放弃操作
            self.logger.error(f"放弃操作 {operation_id}，已达到最大重试次数")
            
            return RecoveryAction(
                action_type="abort",
                message="已达到最大重试次数，放弃操作"
            )
    
    def execute_with_retry(self, 
                          func: Callable[..., T], 
                          operation_id: str,
                          *args, **kwargs) -> T:
        """执行函数并在失败时自动重试
        
        Args:
            func: 要执行的函数
            operation_id: 操作标识符
            *args: 函数参数
            **kwargs: 函数关键字参数
            
        Returns:
            函数执行结果
            
        Raises:
            Exception: 重试失败后抛出最后一次的异常
        """
        last_exception = None
        
        while True:
            try:
                result = func(*args, **kwargs)
                # 成功执行，清除重试计数
                self._clear_retry_count(operation_id)
                return result
                
            except Exception as e:
                last_exception = e
                context = {
                    'function': func.__name__,
                    'args': str(args)[:200],  # 限制日志长度
                    'kwargs': str(kwargs)[:200]
                }
                
                recovery_action = self.handle_exception(e, context, operation_id)
                
                if recovery_action.action_type == "retry":
                    if recovery_action.delay_seconds > 0:
                        time.sleep(recovery_action.delay_seconds)
                    continue
                    
                elif recovery_action.action_type == "degrade":
                    # 在降级模式下重试一次
                    try:
                        return func(*args, **kwargs)
                    except Exception:
                        # 降级模式也失败，抛出异常
                        break
                        
                else:  # abort
                    break
        
        # 重试失败，抛出最后一次异常
        if last_exception:
            raise last_exception
        else:
            raise RuntimeError(f"操作 {operation_id} 执行失败")
    
    def _clear_retry_count(self, operation_id: str) -> None:
        """清除指定操作的重试计数"""
        keys_to_remove = [key for key in self._retry_counts.keys() 
                         if key.startswith(f"{operation_id}:")]
        for key in keys_to_remove:
            del self._retry_counts[key]
    
    def create_checkpoint(self, state: DetectionState) -> str:
        """创建检查点
        
        Args:
            state: 检测状态
            
        Returns:
            检查点ID
            
        Raises:
            CheckpointException: 创建检查点失败
        """
        try:
            # 生成检查点ID
            checkpoint_id = f"{state.session_id}_{int(time.time())}"
            checkpoint_path = self.checkpoints_dir / f"{checkpoint_id}.pkl"
            
            # 更新检查点时间
            state.last_checkpoint_time = datetime.now()
            
            # 保存状态
            with open(checkpoint_path, 'wb') as f:
                pickle.dump(state, f)
            
            self.logger.info(f"创建检查点: {checkpoint_id}")
            
            # 清理旧检查点
            self._cleanup_old_checkpoints(state.session_id)
            
            return checkpoint_id
            
        except Exception as e:
            raise CheckpointException(f"创建检查点失败: {e}", 
                                    checkpoint_id=checkpoint_id,
                                    operation="create")
    
    def restore_from_checkpoint(self, checkpoint_id: str) -> DetectionState:
        """从检查点恢复状态
        
        Args:
            checkpoint_id: 检查点ID
            
        Returns:
            恢复的检测状态
            
        Raises:
            CheckpointException: 恢复检查点失败
        """
        try:
            checkpoint_path = self.checkpoints_dir / f"{checkpoint_id}.pkl"
            
            if not checkpoint_path.exists():
                raise CheckpointException(f"检查点文件不存在: {checkpoint_path}",
                                        checkpoint_id=checkpoint_id,
                                        operation="restore")
            
            with open(checkpoint_path, 'rb') as f:
                state = pickle.load(f)
            
            self.logger.info(f"从检查点恢复状态: {checkpoint_id}")
            return state
            
        except Exception as e:
            raise CheckpointException(f"恢复检查点失败: {e}",
                                    checkpoint_id=checkpoint_id,
                                    operation="restore")
    
    def list_checkpoints(self, session_id: Optional[str] = None) -> List[str]:
        """列出可用的检查点
        
        Args:
            session_id: 会话ID，如果指定则只返回该会话的检查点
            
        Returns:
            检查点ID列表
        """
        checkpoints = []
        
        for checkpoint_file in self.checkpoints_dir.glob("*.pkl"):
            checkpoint_id = checkpoint_file.stem
            
            if session_id is None or checkpoint_id.startswith(session_id):
                checkpoints.append(checkpoint_id)
        
        return sorted(checkpoints)
    
    def _cleanup_old_checkpoints(self, session_id: str, max_keep: int = 5) -> None:
        """清理旧的检查点文件
        
        Args:
            session_id: 会话ID
            max_keep: 最多保留的检查点数量，这是经验值，可根据磁盘空间调整
        """
        session_checkpoints = [cp for cp in self.list_checkpoints() 
                             if cp.startswith(session_id)]
        
        if len(session_checkpoints) > max_keep:
            # 按时间戳排序，删除最旧的
            session_checkpoints.sort()
            to_delete = session_checkpoints[:-max_keep]
            
            for checkpoint_id in to_delete:
                checkpoint_path = self.checkpoints_dir / f"{checkpoint_id}.pkl"
                try:
                    checkpoint_path.unlink()
                    self.logger.debug(f"删除旧检查点: {checkpoint_id}")
                except Exception as e:
                    self.logger.warning(f"删除检查点失败 {checkpoint_id}: {e}")
    
    def get_memory_usage(self) -> Dict[str, float]:
        """获取内存使用情况
        
        Returns:
            内存使用信息 (MB)
        """
        try:
            import psutil
            process = psutil.Process()
            memory_info = process.memory_info()
            
            return {
                'rss_mb': memory_info.rss / 1024 / 1024,  # 物理内存
                'vms_mb': memory_info.vms / 1024 / 1024,  # 虚拟内存
                'percent': process.memory_percent()        # 内存使用百分比
            }
        except ImportError:
            self.logger.warning("psutil 未安装，无法获取内存使用信息")
            return {}
        except Exception as e:
            self.logger.error(f"获取内存使用信息失败: {e}")
            return {}
    
    def check_resource_limits(self, max_memory_gb: float = 4.0) -> None:
        """检查资源限制
        
        Args:
            max_memory_gb: 最大内存限制 (GB)，这是经验值，可根据系统配置调整
            
        Raises:
            ResourceException: 资源超限
        """
        memory_usage = self.get_memory_usage()
        
        if memory_usage and 'rss_mb' in memory_usage:
            current_memory_gb = memory_usage['rss_mb'] / 1024
            
            if current_memory_gb > max_memory_gb:
                raise ResourceException(
                    f"内存使用超限: {current_memory_gb:.2f}GB > {max_memory_gb}GB",
                    resource_type="memory",
                    required_amount=f"{current_memory_gb:.2f}GB"
                )
    
    def is_degraded_mode(self) -> bool:
        """检查是否处于降级模式"""
        return self._degraded_mode
    
    def reset_degraded_mode(self) -> None:
        """重置降级模式"""
        self._degraded_mode = False
        self.logger.info("重置降级模式")
    
    def get_recovery_stats(self) -> Dict[str, Any]:
        """获取恢复统计信息"""
        return {
            'total_retries': sum(self._retry_counts.values()),
            'retry_operations': len(self._retry_counts),
            'degraded_mode': self._degraded_mode,
            'available_checkpoints': len(self.list_checkpoints())
        }