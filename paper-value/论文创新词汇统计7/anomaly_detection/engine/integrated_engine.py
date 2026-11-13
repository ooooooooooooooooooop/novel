"""
集成检测引擎

结合并行处理、检查点管理和异常恢复功能的统一检测引擎。
"""

import time
import threading
from datetime import datetime
from typing import Dict, Any, Optional, List, Union
from pathlib import Path

from ..core.config import DetectionConfig
from ..core.data_models import DetectionResult, DetectionSession, ProcessingStatus
from ..core.exceptions import DetectionLogicException, CheckpointException
from ..core.logging import get_logger
from ..core.error_recovery import DetectionState
from ..data_access.manager import DataAccessManager
from .parallel_engine import ParallelDetectionEngine
from .detection_engine import AnomalyDetectionEngine
from .checkpoint_manager import StateManager
from .recovery_engine import RecoveryEngine


class IntegratedDetectionEngine:
    """集成检测引擎
    
    提供完整的异常检测功能，包括：
    - 并行和串行检测模式
    - 自动检查点和断点续传
    - 异常恢复和重试机制
    - 进度监控和状态管理
    """
    
    def __init__(self, config: DetectionConfig):
        """初始化集成检测引擎
        
        Args:
            config: 检测配置
        """
        self.config = config
        self.logger = get_logger(self.__class__.__name__)
        
        # 核心组件
        self.data_manager = DataAccessManager(config)
        self.state_manager = StateManager(config)
        self.recovery_engine = RecoveryEngine(config)
        
        # 检测引擎
        self.parallel_engine = None
        self.serial_engine = None
        
        # 当前会话状态
        self.current_session: Optional[DetectionSession] = None
        self.detection_results: List[DetectionResult] = []
        self.is_running = False
        
        # 监控和控制
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        
        self.logger.info("集成检测引擎初始化完成")
    
    def run_detection(self, 
                     session_id: Optional[str] = None,
                     checkpoint_id: Optional[str] = None,
                     force_serial: bool = False) -> DetectionSession:
        """运行异常检测
        
        Args:
            session_id: 会话ID
            checkpoint_id: 检查点ID，用于恢复检测
            force_serial: 强制使用串行模式
            
        Returns:
            检测会话信息
            
        Raises:
            DetectionLogicException: 检测执行失败
        """
        try:
            # 设置运行状态
            self.is_running = True
            self._stop_event.clear()
            self._pause_event.clear()
            
            # 启动恢复引擎监控
            self.recovery_engine.start_monitoring()
            
            # 决定使用并行还是串行模式
            use_parallel = (self.config.parallel_processing and 
                          not force_serial and 
                          self.config.performance.max_workers > 1)
            
            if checkpoint_id:
                # 从检查点恢复
                session = self._resume_from_checkpoint(checkpoint_id, use_parallel)
            else:
                # 开始新的检测
                session = self._start_new_detection(session_id, use_parallel)
            
            return session
        
        except Exception as e:
            self.is_running = False
            raise DetectionLogicException(f"集成检测执行失败: {e}",
                                        detector_name="IntegratedDetectionEngine")
        finally:
            # 清理资源
            self._cleanup()
    
    def _start_new_detection(self, session_id: Optional[str], use_parallel: bool) -> DetectionSession:
        """开始新的检测
        
        Args:
            session_id: 会话ID
            use_parallel: 是否使用并行模式
            
        Returns:
            检测会话
        """
        self.logger.info(f"开始新的检测，模式: {'并行' if use_parallel else '串行'}")
        
        # 获取数据统计
        data_stats = self.data_manager.get_data_statistics()
        total_records = data_stats.get('total_records', 0)
        
        if total_records == 0:
            self.logger.warning("没有数据可供检测")
            # 创建空会话
            session = DetectionSession(
                session_id=session_id or f"empty_detection_{int(time.time())}",
                config_hash=self.config.get_config_hash(),
                start_time=datetime.now(),
                end_time=datetime.now(),
                status=ProcessingStatus.COMPLETED,
                total_anomalies=0
            )
            return session
        
        # 创建检测会话
        if session_id is None:
            session_id = f"detection_{int(time.time())}"
        
        session = DetectionSession(
            session_id=session_id,
            config_hash=self.config.get_config_hash(),
            start_time=datetime.now(),
            status=ProcessingStatus.RUNNING
        )
        
        self.current_session = session
        
        # 启动状态管理
        self.state_manager.start_session(session, total_records)
        
        # 执行检测
        if use_parallel:
            session = self._run_parallel_detection(session)
        else:
            session = self._run_serial_detection(session)
        
        return session
    
    def _resume_from_checkpoint(self, checkpoint_id: str, use_parallel: bool) -> DetectionSession:
        """从检查点恢复检测
        
        Args:
            checkpoint_id: 检查点ID
            use_parallel: 是否使用并行模式
            
        Returns:
            检测会话
        """
        self.logger.info(f"从检查点恢复检测: {checkpoint_id}")
        
        try:
            # 恢复会话状态
            session = self.state_manager.restore_from_checkpoint(checkpoint_id)
            self.current_session = session
            
            # 获取当前状态
            current_status = self.state_manager.get_current_status()
            
            self.logger.info(f"恢复会话: {session.session_id}, "
                           f"进度: {current_status.get('progress_percentage', 0):.1f}%")
            
            # 继续执行检测
            if use_parallel:
                session = self._continue_parallel_detection(session)
            else:
                session = self._continue_serial_detection(session)
            
            return session
        
        except Exception as e:
            raise CheckpointException(f"从检查点恢复失败: {e}",
                                    checkpoint_id=checkpoint_id,
                                    operation="resume")
    
    def _run_parallel_detection(self, session: DetectionSession) -> DetectionSession:
        """运行并行检测
        
        Args:
            session: 检测会话
            
        Returns:
            完成的检测会话
        """
        try:
            # 创建并行引擎
            self.parallel_engine = ParallelDetectionEngine(self.config)
            
            # 创建可恢复操作
            operation = self.recovery_engine.create_resumable_operation(
                operation_id=f"parallel_detection_{session.session_id}",
                operation_func=self._execute_parallel_detection_with_monitoring
            )
            
            # 执行检测
            result_session = self.recovery_engine.execute_with_recovery(
                operation_func=operation.execute,
                operation_id=operation.operation_id,
                strategy_name='detection_logic',
                session=session
            )
            
            return result_session
        
        except Exception as e:
            session.status = ProcessingStatus.FAILED
            session.end_time = datetime.now()
            raise DetectionLogicException(f"并行检测执行失败: {e}")
    
    def _run_serial_detection(self, session: DetectionSession) -> DetectionSession:
        """运行串行检测
        
        Args:
            session: 检测会话
            
        Returns:
            完成的检测会话
        """
        try:
            # 创建串行引擎
            self.serial_engine = AnomalyDetectionEngine(self.config)
            
            # 创建可恢复操作
            operation = self.recovery_engine.create_resumable_operation(
                operation_id=f"serial_detection_{session.session_id}",
                operation_func=self._execute_serial_detection_with_monitoring
            )
            
            # 执行检测
            result_session = self.recovery_engine.execute_with_recovery(
                operation_func=operation.execute,
                operation_id=operation.operation_id,
                strategy_name='detection_logic',
                session=session
            )
            
            return result_session
        
        except Exception as e:
            session.status = ProcessingStatus.FAILED
            session.end_time = datetime.now()
            raise DetectionLogicException(f"串行检测执行失败: {e}")
    
    def _execute_parallel_detection_with_monitoring(self, session: DetectionSession) -> DetectionSession:
        """执行带监控的并行检测
        
        Args:
            session: 检测会话
            
        Returns:
            完成的检测会话
        """
        # 启动监控线程
        monitor_thread = threading.Thread(
            target=self._monitor_detection_progress,
            args=(session.session_id,),
            daemon=True
        )
        monitor_thread.start()
        
        try:
            # 执行并行检测
            result_session = self.parallel_engine.run_parallel_detection(
                session_id=session.session_id
            )
            
            # 获取结果
            self.detection_results = self.parallel_engine.get_detection_results()
            
            # 更新状态管理器
            self.state_manager.update_progress(
                processed_count=result_session.total_anomalies,
                current_step="completed",
                new_results=self.detection_results
            )
            
            # 完成会话
            self.state_manager.finish_session()
            
            return result_session
        
        finally:
            # 等待监控线程结束
            self._stop_event.set()
            if monitor_thread.is_alive():
                monitor_thread.join(timeout=5)
    
    def _execute_serial_detection_with_monitoring(self, session: DetectionSession) -> DetectionSession:
        """执行带监控的串行检测
        
        Args:
            session: 检测会话
            
        Returns:
            完成的检测会话
        """
        # 启动监控线程
        monitor_thread = threading.Thread(
            target=self._monitor_detection_progress,
            args=(session.session_id,),
            daemon=True
        )
        monitor_thread.start()
        
        try:
            # 执行串行检测
            result_session = self.serial_engine.run_detection(
                session_id=session.session_id
            )
            
            # 获取结果
            self.detection_results = self.serial_engine.get_detection_results()
            
            # 更新状态管理器
            self.state_manager.update_progress(
                processed_count=result_session.total_anomalies,
                current_step="completed",
                new_results=self.detection_results
            )
            
            # 完成会话
            self.state_manager.finish_session()
            
            return result_session
        
        finally:
            # 等待监控线程结束
            self._stop_event.set()
            if monitor_thread.is_alive():
                monitor_thread.join(timeout=5)
    
    def _continue_parallel_detection(self, session: DetectionSession) -> DetectionSession:
        """继续并行检测
        
        Args:
            session: 恢复的检测会话
            
        Returns:
            完成的检测会话
        """
        # 实现从检查点继续并行检测的逻辑
        # 这里简化为重新开始检测
        self.logger.warning("并行检测的断点续传功能尚未完全实现，将重新开始检测")
        return self._run_parallel_detection(session)
    
    def _continue_serial_detection(self, session: DetectionSession) -> DetectionSession:
        """继续串行检测
        
        Args:
            session: 恢复的检测会话
            
        Returns:
            完成的检测会话
        """
        # 实现从检查点继续串行检测的逻辑
        # 这里简化为重新开始检测
        self.logger.warning("串行检测的断点续传功能尚未完全实现，将重新开始检测")
        return self._run_serial_detection(session)
    
    def _monitor_detection_progress(self, session_id: str) -> None:
        """监控检测进度
        
        Args:
            session_id: 会话ID
        """
        while not self._stop_event.is_set():
            try:
                # 检查暂停状态
                if self._pause_event.is_set():
                    self.logger.info("检测已暂停")
                    self._pause_event.wait()
                    continue
                
                # 获取当前状态
                current_status = self.state_manager.get_current_status()
                
                if current_status.get('status') != 'no_active_session':
                    progress_pct = current_status.get('progress_percentage', 0)
                    processing_speed = current_status.get('processing_speed', 0)
                    memory_usage = current_status.get('memory_usage_mb', 0)
                    
                    self.logger.debug(f"检测进度: {progress_pct:.1f}%, "
                                    f"速度: {processing_speed:.1f} 记录/秒, "
                                    f"内存: {memory_usage:.1f}MB")
                
                # 检查是否需要创建检查点
                if self.state_manager.progress_tracker:
                    current_snapshot = self.state_manager.progress_tracker.get_current_snapshot()
                    
                    # 每处理一定数量的记录创建检查点
                    if (current_snapshot.processed_count > 0 and 
                        current_snapshot.processed_count % self.config.performance.checkpoint_interval == 0):
                        
                        try:
                            checkpoint_id = self.state_manager.create_manual_checkpoint(
                                f"自动检查点 - {current_snapshot.processed_count} 条记录"
                            )
                            self.logger.info(f"创建自动检查点: {checkpoint_id}")
                        except Exception as e:
                            self.logger.error(f"创建自动检查点失败: {e}")
                
                time.sleep(10)  # 每10秒检查一次，这是经验值
                
            except Exception as e:
                self.logger.error(f"监控检测进度失败: {e}")
                time.sleep(5)
    
    def pause_detection(self) -> bool:
        """暂停检测
        
        Returns:
            是否成功暂停
        """
        if not self.is_running:
            return False
        
        self._pause_event.set()
        
        # 暂停相关引擎
        if self.parallel_engine:
            self.parallel_engine.stop_detection()
        
        self.logger.info("检测已暂停")
        return True
    
    def resume_detection(self) -> bool:
        """恢复检测
        
        Returns:
            是否成功恢复
        """
        if not self.is_running or not self._pause_event.is_set():
            return False
        
        self._pause_event.clear()
        
        self.logger.info("检测已恢复")
        return True
    
    def stop_detection(self) -> bool:
        """停止检测
        
        Returns:
            是否成功停止
        """
        if not self.is_running:
            return False
        
        self._stop_event.set()
        self._pause_event.clear()
        
        # 停止相关引擎
        if self.parallel_engine:
            self.parallel_engine.stop_detection()
        
        # 更新会话状态
        if self.current_session:
            self.current_session.status = ProcessingStatus.PAUSED
            self.current_session.end_time = datetime.now()
        
        self.is_running = False
        
        self.logger.info("检测已停止")
        return True
    
    def create_checkpoint(self, description: str = "") -> str:
        """创建检查点
        
        Args:
            description: 检查点描述
            
        Returns:
            检查点ID
        """
        if not self.current_session:
            raise CheckpointException("没有活动的检测会话")
        
        return self.state_manager.create_manual_checkpoint(
            description or f"手动检查点 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    
    def list_checkpoints(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出检查点
        
        Args:
            session_id: 会话ID，如果不指定则列出所有检查点
            
        Returns:
            检查点信息列表
        """
        checkpoints = self.state_manager.checkpoint_manager.list_checkpoints(session_id)
        return [cp.to_dict() for cp in checkpoints]
    
    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """删除检查点
        
        Args:
            checkpoint_id: 检查点ID
            
        Returns:
            是否删除成功
        """
        return self.state_manager.checkpoint_manager.delete_checkpoint(checkpoint_id)
    
    def get_detection_results(self) -> List[DetectionResult]:
        """获取检测结果
        
        Returns:
            检测结果列表
        """
        return self.detection_results.copy()
    
    def get_detection_summary(self) -> Dict[str, Any]:
        """获取检测摘要
        
        Returns:
            检测摘要信息
        """
        if not self.current_session:
            return {'error': '没有活动的检测会话'}
        
        # 获取基础摘要
        base_summary = {
            'session_id': self.current_session.session_id,
            'status': self.current_session.status.value,
            'start_time': self.current_session.start_time.isoformat(),
            'end_time': self.current_session.end_time.isoformat() if self.current_session.end_time else None,
            'total_anomalies': len(self.detection_results),
            'config_hash': self.current_session.config_hash
        }
        
        # 添加状态管理信息
        current_status = self.state_manager.get_current_status()
        base_summary.update(current_status)
        
        # 添加恢复引擎信息
        recovery_status = self.recovery_engine.get_recovery_status()
        base_summary['recovery_info'] = recovery_status
        
        return base_summary
    
    def export_detection_report(self, output_path: str, format: str = 'json') -> None:
        """导出检测报告
        
        Args:
            output_path: 输出路径
            format: 报告格式 ('json', 'excel', 'html')
        """
        report_data = {
            'export_time': datetime.now().isoformat(),
            'detection_summary': self.get_detection_summary(),
            'detection_results': [
                {
                    'anomaly_id': result.anomaly_id,
                    'detector_name': result.detector_name,
                    'anomaly_type': result.anomaly_type,
                    'severity': result.severity.value,
                    'description': result.description,
                    'affected_entities': result.affected_entities,
                    'confidence_score': result.confidence_score,
                    'detection_timestamp': result.detection_timestamp.isoformat()
                }
                for result in self.detection_results
            ],
            'checkpoints': self.list_checkpoints()
        }
        
        if format.lower() == 'json':
            import json
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False)
        
        elif format.lower() == 'excel':
            # 实现Excel导出
            self.logger.warning("Excel格式导出尚未实现")
        
        elif format.lower() == 'html':
            # 实现HTML导出
            self.logger.warning("HTML格式导出尚未实现")
        
        else:
            raise ValueError(f"不支持的报告格式: {format}")
        
        self.logger.info(f"检测报告已导出到: {output_path}")
    
    def _cleanup(self) -> None:
        """清理资源"""
        try:
            self.is_running = False
            
            # 停止监控
            self._stop_event.set()
            
            # 关闭引擎
            if self.parallel_engine:
                self.parallel_engine.close()
                self.parallel_engine = None
            
            if self.serial_engine:
                self.serial_engine.close()
                self.serial_engine = None
            
            # 停止恢复引擎监控
            self.recovery_engine.stop_monitoring()
            
        except Exception as e:
            self.logger.error(f"清理资源失败: {e}")
    
    def close(self) -> None:
        """关闭集成检测引擎"""
        try:
            # 停止检测
            self.stop_detection()
            
            # 清理资源
            self._cleanup()
            
            # 关闭组件
            if self.data_manager:
                self.data_manager.close()
            
            if self.recovery_engine:
                self.recovery_engine.close()
            
            self.logger.info("集成检测引擎已关闭")
        
        except Exception as e:
            self.logger.error(f"关闭集成检测引擎失败: {e}")
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()