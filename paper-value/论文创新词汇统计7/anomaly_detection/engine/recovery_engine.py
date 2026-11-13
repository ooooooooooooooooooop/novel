"""
恢复引擎

实现异常恢复、重试逻辑和断点续传功能的高级管理。
"""

import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable, Union
from pathlib import Path
import json

from ..core.config import DetectionConfig
from ..core.data_models import DetectionResult, DetectionSession, ProcessingStatus
from ..core.exceptions import DetectionLogicException, ResourceException, CheckpointException
from ..core.logging import get_logger
from ..core.error_recovery import DetectionState, ErrorRecoveryManager
from .checkpoint_manager import CheckpointManager, StateManager, ProgressTracker


class RecoveryStrategy:
    """恢复策略
    
    定义不同类型异常的恢复方法。
    """
    
    def __init__(self, strategy_name: str, max_retries: int = 3, 
                 backoff_factor: float = 2.0, timeout_seconds: float = 300.0):
        """初始化恢复策略
        
        Args:
            strategy_name: 策略名称
            max_retries: 最大重试次数，这是经验值，可根据异常类型调整
            backoff_factor: 退避因子，这是经验值，指数退避策略
            timeout_seconds: 超时时间（秒），这是经验值，可根据操作复杂度调整
        """
        self.strategy_name = strategy_name
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.timeout_seconds = timeout_seconds
        
        # 统计信息
        self.retry_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.last_used = None
    
    def should_retry(self, exception: Exception, attempt: int) -> bool:
        """判断是否应该重试
        
        Args:
            exception: 发生的异常
            attempt: 当前尝试次数
            
        Returns:
            是否应该重试
        """
        if attempt >= self.max_retries:
            return False
        
        # 根据异常类型决定是否重试
        if isinstance(exception, ResourceException):
            return True  # 资源异常通常是临时的
        elif isinstance(exception, CheckpointException):
            return attempt < 2  # 检查点异常最多重试1次
        elif isinstance(exception, DetectionLogicException):
            return False  # 逻辑异常通常不应该重试
        else:
            return attempt < 1  # 未知异常最多重试1次
    
    def get_delay(self, attempt: int) -> float:
        """获取重试延迟时间
        
        Args:
            attempt: 当前尝试次数
            
        Returns:
            延迟时间（秒）
        """
        # 指数退避策略
        base_delay = 1.0  # 基础延迟1秒，这是经验值
        return min(base_delay * (self.backoff_factor ** attempt), 60.0)  # 最大延迟60秒
    
    def record_attempt(self, success: bool) -> None:
        """记录尝试结果
        
        Args:
            success: 是否成功
        """
        self.last_used = datetime.now()
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
            self.retry_count += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """获取策略统计信息"""
        total_attempts = self.success_count + self.failure_count
        success_rate = (self.success_count / total_attempts * 100) if total_attempts > 0 else 0
        
        return {
            'strategy_name': self.strategy_name,
            'max_retries': self.max_retries,
            'retry_count': self.retry_count,
            'success_count': self.success_count,
            'failure_count': self.failure_count,
            'success_rate': success_rate,
            'last_used': self.last_used.isoformat() if self.last_used else None
        }


class ResumableOperation:
    """可恢复操作
    
    封装可以中断和恢复的操作。
    """
    
    def __init__(self, operation_id: str, operation_func: Callable, 
                 checkpoint_interval: int = 1000):
        """初始化可恢复操作
        
        Args:
            operation_id: 操作ID
            operation_func: 操作函数
            checkpoint_interval: 检查点间隔，这是经验值，可根据操作复杂度调整
        """
        self.operation_id = operation_id
        self.operation_func = operation_func
        self.checkpoint_interval = checkpoint_interval
        
        # 状态管理
        self.start_time = None
        self.last_checkpoint_time = None
        self.processed_count = 0
        self.total_count = 0
        self.is_paused = False
        self.is_cancelled = False
        
        # 结果存储
        self.intermediate_results = []
        self.final_result = None
        
        self.logger = get_logger(f"{self.__class__.__name__}_{operation_id}")
    
    def execute(self, *args, **kwargs) -> Any:
        """执行操作
        
        Args:
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            操作结果
        """
        self.start_time = datetime.now()
        self.logger.info(f"开始执行操作: {self.operation_id}")
        
        try:
            # 执行操作函数
            result = self.operation_func(*args, **kwargs)
            self.final_result = result
            
            self.logger.info(f"操作执行完成: {self.operation_id}")
            return result
        
        except Exception as e:
            self.logger.error(f"操作执行失败: {self.operation_id} - {e}")
            raise
    
    def pause(self) -> None:
        """暂停操作"""
        self.is_paused = True
        self.logger.info(f"操作已暂停: {self.operation_id}")
    
    def resume(self) -> None:
        """恢复操作"""
        self.is_paused = False
        self.logger.info(f"操作已恢复: {self.operation_id}")
    
    def cancel(self) -> None:
        """取消操作"""
        self.is_cancelled = True
        self.logger.info(f"操作已取消: {self.operation_id}")
    
    def update_progress(self, processed_count: int, total_count: int = None) -> None:
        """更新进度
        
        Args:
            processed_count: 已处理数量
            total_count: 总数量
        """
        self.processed_count = processed_count
        if total_count is not None:
            self.total_count = total_count
    
    def should_checkpoint(self) -> bool:
        """判断是否应该创建检查点"""
        if not self.last_checkpoint_time:
            return self.processed_count >= self.checkpoint_interval
        
        return self.processed_count % self.checkpoint_interval == 0
    
    def get_progress_info(self) -> Dict[str, Any]:
        """获取进度信息"""
        progress_pct = (self.processed_count / self.total_count * 100) if self.total_count > 0 else 0
        
        elapsed_time = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
        processing_speed = self.processed_count / elapsed_time if elapsed_time > 0 else 0
        
        eta = (self.total_count - self.processed_count) / processing_speed if processing_speed > 0 else None
        
        return {
            'operation_id': self.operation_id,
            'processed_count': self.processed_count,
            'total_count': self.total_count,
            'progress_percentage': progress_pct,
            'processing_speed': processing_speed,
            'eta_seconds': eta,
            'is_paused': self.is_paused,
            'is_cancelled': self.is_cancelled,
            'elapsed_time': elapsed_time
        }


class RecoveryEngine:
    """恢复引擎
    
    统一管理异常恢复、重试逻辑和断点续传功能。
    """
    
    def __init__(self, config: DetectionConfig):
        """初始化恢复引擎
        
        Args:
            config: 检测配置
        """
        self.config = config
        self.logger = get_logger(self.__class__.__name__)
        
        # 核心组件
        self.error_recovery_manager = ErrorRecoveryManager(
            config.recovery, 
            config.paths.checkpoints_dir
        )
        self.state_manager = StateManager(config)
        
        # 恢复策略
        self.recovery_strategies: Dict[str, RecoveryStrategy] = {}
        self._initialize_recovery_strategies()
        
        # 可恢复操作管理
        self.active_operations: Dict[str, ResumableOperation] = {}
        self.operation_history: List[Dict[str, Any]] = []
        
        # 监控线程
        self._monitoring_thread = None
        self._stop_monitoring = threading.Event()
        
        self.logger.info("恢复引擎初始化完成")
    
    def _initialize_recovery_strategies(self) -> None:
        """初始化恢复策略"""
        # 数据访问异常策略
        self.recovery_strategies['data_access'] = RecoveryStrategy(
            strategy_name='data_access',
            max_retries=3,
            backoff_factor=2.0,
            timeout_seconds=60.0
        )
        
        # 检测逻辑异常策略
        self.recovery_strategies['detection_logic'] = RecoveryStrategy(
            strategy_name='detection_logic',
            max_retries=1,
            backoff_factor=1.0,
            timeout_seconds=300.0
        )
        
        # 资源异常策略
        self.recovery_strategies['resource'] = RecoveryStrategy(
            strategy_name='resource',
            max_retries=5,
            backoff_factor=1.5,
            timeout_seconds=120.0
        )
        
        # 检查点异常策略
        self.recovery_strategies['checkpoint'] = RecoveryStrategy(
            strategy_name='checkpoint',
            max_retries=2,
            backoff_factor=2.0,
            timeout_seconds=30.0
        )
    
    def execute_with_recovery(self, operation_func: Callable, operation_id: str,
                            strategy_name: str = 'data_access', 
                            *args, **kwargs) -> Any:
        """执行带恢复功能的操作
        
        Args:
            operation_func: 要执行的操作函数
            operation_id: 操作ID
            strategy_name: 恢复策略名称
            *args: 操作函数的位置参数
            **kwargs: 操作函数的关键字参数
            
        Returns:
            操作结果
            
        Raises:
            Exception: 重试失败后抛出最后一次的异常
        """
        strategy = self.recovery_strategies.get(strategy_name)
        if not strategy:
            raise ValueError(f"未知的恢复策略: {strategy_name}")
        
        last_exception = None
        
        for attempt in range(strategy.max_retries + 1):
            try:
                self.logger.debug(f"执行操作 {operation_id}，第 {attempt + 1} 次尝试")
                
                # 执行操作
                result = operation_func(*args, **kwargs)
                
                # 记录成功
                strategy.record_attempt(success=True)
                
                if attempt > 0:
                    self.logger.info(f"操作 {operation_id} 在第 {attempt + 1} 次尝试后成功")
                
                return result
            
            except Exception as e:
                last_exception = e
                strategy.record_attempt(success=False)
                
                self.logger.warning(f"操作 {operation_id} 第 {attempt + 1} 次尝试失败: {e}")
                
                # 判断是否应该重试
                if not strategy.should_retry(e, attempt):
                    break
                
                # 等待重试延迟
                if attempt < strategy.max_retries:
                    delay = strategy.get_delay(attempt)
                    self.logger.info(f"等待 {delay} 秒后重试操作 {operation_id}")
                    time.sleep(delay)
        
        # 所有重试都失败了
        self.logger.error(f"操作 {operation_id} 在 {strategy.max_retries + 1} 次尝试后仍然失败")
        
        if last_exception:
            raise last_exception
        else:
            raise RuntimeError(f"操作 {operation_id} 执行失败")
    
    def create_resumable_operation(self, operation_id: str, operation_func: Callable,
                                 checkpoint_interval: int = None) -> ResumableOperation:
        """创建可恢复操作
        
        Args:
            operation_id: 操作ID
            operation_func: 操作函数
            checkpoint_interval: 检查点间隔
            
        Returns:
            可恢复操作对象
        """
        if checkpoint_interval is None:
            checkpoint_interval = self.config.performance.checkpoint_interval
        
        operation = ResumableOperation(
            operation_id=operation_id,
            operation_func=operation_func,
            checkpoint_interval=checkpoint_interval
        )
        
        self.active_operations[operation_id] = operation
        
        self.logger.info(f"创建可恢复操作: {operation_id}")
        
        return operation
    
    def pause_operation(self, operation_id: str) -> bool:
        """暂停操作
        
        Args:
            operation_id: 操作ID
            
        Returns:
            是否成功暂停
        """
        operation = self.active_operations.get(operation_id)
        if operation:
            operation.pause()
            self.logger.info(f"暂停操作: {operation_id}")
            return True
        
        self.logger.warning(f"未找到操作: {operation_id}")
        return False
    
    def resume_operation(self, operation_id: str) -> bool:
        """恢复操作
        
        Args:
            operation_id: 操作ID
            
        Returns:
            是否成功恢复
        """
        operation = self.active_operations.get(operation_id)
        if operation:
            operation.resume()
            self.logger.info(f"恢复操作: {operation_id}")
            return True
        
        self.logger.warning(f"未找到操作: {operation_id}")
        return False
    
    def cancel_operation(self, operation_id: str) -> bool:
        """取消操作
        
        Args:
            operation_id: 操作ID
            
        Returns:
            是否成功取消
        """
        operation = self.active_operations.get(operation_id)
        if operation:
            operation.cancel()
            
            # 移动到历史记录
            self.operation_history.append({
                'operation_id': operation_id,
                'status': 'cancelled',
                'end_time': datetime.now().isoformat(),
                'progress_info': operation.get_progress_info()
            })
            
            del self.active_operations[operation_id]
            
            self.logger.info(f"取消操作: {operation_id}")
            return True
        
        self.logger.warning(f"未找到操作: {operation_id}")
        return False
    
    def create_checkpoint_for_operation(self, operation_id: str, 
                                      additional_data: Dict[str, Any] = None) -> Optional[str]:
        """为操作创建检查点
        
        Args:
            operation_id: 操作ID
            additional_data: 额外数据
            
        Returns:
            检查点ID，如果失败则返回None
        """
        operation = self.active_operations.get(operation_id)
        if not operation:
            self.logger.warning(f"未找到操作: {operation_id}")
            return None
        
        try:
            # 创建检测状态
            detection_state = DetectionState(
                session_id=operation_id,
                current_step="operation_checkpoint",
                processed_count=operation.processed_count,
                total_count=operation.total_count,
                start_time=operation.start_time or datetime.now(),
                last_checkpoint_time=datetime.now(),
                metadata={
                    'operation_info': operation.get_progress_info(),
                    'additional_data': additional_data or {}
                }
            )
            
            # 创建检查点
            checkpoint_id = self.state_manager.checkpoint_manager.create_checkpoint(
                detection_state=detection_state,
                results=operation.intermediate_results,
                description=f"操作检查点 - {operation_id}"
            )
            
            operation.last_checkpoint_time = datetime.now()
            
            self.logger.info(f"为操作 {operation_id} 创建检查点: {checkpoint_id}")
            
            return checkpoint_id
        
        except Exception as e:
            self.logger.error(f"为操作 {operation_id} 创建检查点失败: {e}")
            return None
    
    def restore_operation_from_checkpoint(self, checkpoint_id: str) -> Optional[ResumableOperation]:
        """从检查点恢复操作
        
        Args:
            checkpoint_id: 检查点ID
            
        Returns:
            恢复的操作对象，如果失败则返回None
        """
        try:
            # 恢复检查点
            detection_state, results = self.state_manager.checkpoint_manager.restore_checkpoint(checkpoint_id)
            
            # 提取操作信息
            operation_info = detection_state.metadata.get('operation_info', {})
            operation_id = operation_info.get('operation_id', detection_state.session_id)
            
            # 创建恢复的操作（需要重新提供操作函数）
            # 这里只能恢复状态，实际的操作函数需要外部提供
            operation = ResumableOperation(
                operation_id=operation_id,
                operation_func=lambda: None,  # 占位符，需要外部设置
                checkpoint_interval=self.config.performance.checkpoint_interval
            )
            
            # 恢复状态
            operation.start_time = detection_state.start_time
            operation.processed_count = detection_state.processed_count
            operation.total_count = detection_state.total_count
            operation.intermediate_results = results
            operation.last_checkpoint_time = detection_state.last_checkpoint_time
            
            self.active_operations[operation_id] = operation
            
            self.logger.info(f"从检查点 {checkpoint_id} 恢复操作: {operation_id}")
            
            return operation
        
        except Exception as e:
            self.logger.error(f"从检查点 {checkpoint_id} 恢复操作失败: {e}")
            return None
    
    def start_monitoring(self) -> None:
        """启动监控线程"""
        if self._monitoring_thread and self._monitoring_thread.is_alive():
            return
        
        self._stop_monitoring.clear()
        self._monitoring_thread = threading.Thread(target=self._monitor_operations, daemon=True)
        self._monitoring_thread.start()
        
        self.logger.info("启动恢复引擎监控")
    
    def stop_monitoring(self) -> None:
        """停止监控线程"""
        self._stop_monitoring.set()
        
        if self._monitoring_thread and self._monitoring_thread.is_alive():
            self._monitoring_thread.join(timeout=5)
        
        self.logger.info("停止恢复引擎监控")
    
    def _monitor_operations(self) -> None:
        """监控操作状态"""
        while not self._stop_monitoring.is_set():
            try:
                # 检查活动操作
                for operation_id, operation in list(self.active_operations.items()):
                    # 检查是否需要自动创建检查点
                    if operation.should_checkpoint():
                        self.create_checkpoint_for_operation(operation_id)
                    
                    # 检查操作是否完成或取消
                    if operation.is_cancelled:
                        self.cancel_operation(operation_id)
                
                # 检查资源使用情况
                try:
                    self.error_recovery_manager.check_resource_limits(
                        max_memory_gb=self.config.performance.max_memory_gb
                    )
                except ResourceException as e:
                    self.logger.warning(f"资源使用超限: {e}")
                    # 可以在这里实现自动暂停操作等策略
                
                time.sleep(30)  # 每30秒检查一次，这是经验值
                
            except Exception as e:
                self.logger.error(f"监控操作失败: {e}")
                time.sleep(5)
    
    def get_recovery_status(self) -> Dict[str, Any]:
        """获取恢复状态
        
        Returns:
            恢复状态信息
        """
        # 统计策略信息
        strategy_stats = {
            name: strategy.get_stats() 
            for name, strategy in self.recovery_strategies.items()
        }
        
        # 统计活动操作
        active_operations_info = {
            op_id: operation.get_progress_info()
            for op_id, operation in self.active_operations.items()
        }
        
        # 获取检查点信息
        checkpoint_stats = self.state_manager.checkpoint_manager.get_storage_stats()
        
        return {
            'recovery_strategies': strategy_stats,
            'active_operations': active_operations_info,
            'operation_history_count': len(self.operation_history),
            'checkpoint_stats': checkpoint_stats,
            'monitoring_active': self._monitoring_thread and self._monitoring_thread.is_alive(),
            'degraded_mode': self.error_recovery_manager.is_degraded_mode()
        }
    
    def cleanup_completed_operations(self, max_age_hours: int = 24) -> int:
        """清理已完成的操作记录
        
        Args:
            max_age_hours: 最大保留时间（小时），这是经验值，可根据需要调整
            
        Returns:
            清理的记录数量
        """
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        
        original_count = len(self.operation_history)
        
        # 过滤掉过期的记录
        self.operation_history = [
            record for record in self.operation_history
            if datetime.fromisoformat(record['end_time']) > cutoff_time
        ]
        
        cleaned_count = original_count - len(self.operation_history)
        
        if cleaned_count > 0:
            self.logger.info(f"清理了 {cleaned_count} 个过期的操作记录")
        
        return cleaned_count
    
    def export_recovery_report(self, output_path: str) -> None:
        """导出恢复报告
        
        Args:
            output_path: 输出路径
        """
        report = {
            'export_time': datetime.now().isoformat(),
            'recovery_status': self.get_recovery_status(),
            'operation_history': self.operation_history,
            'config_summary': {
                'max_memory_gb': self.config.performance.max_memory_gb,
                'checkpoint_interval': self.config.performance.checkpoint_interval,
                'max_workers': self.config.performance.max_workers
            }
        }
        
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"恢复报告已导出到: {output_path}")
        
        except Exception as e:
            self.logger.error(f"导出恢复报告失败: {e}")
    
    def close(self) -> None:
        """关闭恢复引擎"""
        try:
            # 停止监控
            self.stop_monitoring()
            
            # 取消所有活动操作
            for operation_id in list(self.active_operations.keys()):
                self.cancel_operation(operation_id)
            
            self.logger.info("恢复引擎已关闭")
        
        except Exception as e:
            self.logger.error(f"关闭恢复引擎失败: {e}")
    
    def __enter__(self):
        """上下文管理器入口"""
        self.start_monitoring()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()