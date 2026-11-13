"""
并行异常检测引擎

实现多进程并行检测，支持任务分片、负载均衡和结果聚合。
"""

import multiprocessing as mp
import time
import pickle
import queue
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, Iterator, Tuple, Callable
from datetime import datetime
from pathlib import Path
import threading

from ..core.config import DetectionConfig
from ..core.data_models import DetectionResult, DetectionSession, ProcessingStatus, DetectionState
from ..core.exceptions import DetectionLogicException, ResourceException
from ..core.logging import get_logger
from ..core.error_recovery import ErrorRecoveryManager
from ..data_access.manager import DataAccessManager
from .detection_engine import AnomalyDetectionEngine


class TaskShard:
    """任务分片
    
    表示一个可独立处理的数据分片任务。
    """
    
    def __init__(self, shard_id: str, data_range: Tuple[int, int], 
                 detector_names: List[str], config_dict: Dict[str, Any]):
        """初始化任务分片
        
        Args:
            shard_id: 分片ID
            data_range: 数据范围 (start_index, end_index)
            detector_names: 要运行的检测器名称列表
            config_dict: 配置字典
        """
        self.shard_id = shard_id
        self.data_range = data_range
        self.detector_names = detector_names
        self.config_dict = config_dict
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.status = ProcessingStatus.RUNNING
        self.results: List[DetectionResult] = []
        self.error_message: Optional[str] = None
    
    def get_size(self) -> int:
        """获取分片大小"""
        return self.data_range[1] - self.data_range[0]
    
    def get_processing_time(self) -> Optional[float]:
        """获取处理时间（秒）"""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


class WorkerProcess:
    """工作进程
    
    在独立进程中执行检测任务。
    """
    
    def __init__(self, worker_id: int):
        """初始化工作进程
        
        Args:
            worker_id: 工作进程ID
        """
        self.worker_id = worker_id
        self.processed_shards = 0
        self.total_results = 0
        self.start_time = datetime.now()
        self.last_activity = datetime.now()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取工作进程统计信息"""
        return {
            'worker_id': self.worker_id,
            'processed_shards': self.processed_shards,
            'total_results': self.total_results,
            'uptime_seconds': (datetime.now() - self.start_time).total_seconds(),
            'last_activity': self.last_activity.isoformat()
        }


def execute_detection_shard(shard: TaskShard) -> TaskShard:
    """执行单个检测分片
    
    这个函数在独立进程中运行，执行指定分片的异常检测。
    
    Args:
        shard: 任务分片
        
    Returns:
        完成的任务分片（包含结果）
    """
    try:
        shard.start_time = datetime.now()
        
        # 从配置字典重建配置对象
        config = DetectionConfig.from_dict(shard.config_dict)
        
        # 创建数据访问管理器
        data_manager = DataAccessManager(config)
        
        # 获取分片数据
        start_idx, end_idx = shard.data_range
        
        # 根据检测器类型获取相应数据
        shard_results = []
        
        for detector_name in shard.detector_names:
            if detector_name == "ConceptMappingDetector":
                # 概念映射检测不需要分片，在主进程中处理
                continue
            
            elif detector_name == "MissingDuplicateDetector":
                # 遗漏重复检测需要完整的概念集合，在主进程中处理
                continue
            
            elif detector_name == "RPUStructureDetector":
                # RPU结构检测可以分片处理
                rpu_data = []
                batch_count = 0
                current_idx = 0
                
                for rpu_batch in data_manager.get_rpu_batches(batch_size=1000):
                    batch_end = current_idx + len(rpu_batch)
                    
                    # 检查是否在分片范围内
                    if batch_end > start_idx and current_idx < end_idx:
                        # 计算实际需要的数据范围
                        batch_start_offset = max(0, start_idx - current_idx)
                        batch_end_offset = min(len(rpu_batch), end_idx - current_idx)
                        
                        if batch_start_offset < batch_end_offset:
                            rpu_data.extend(rpu_batch[batch_start_offset:batch_end_offset])
                    
                    current_idx = batch_end
                    
                    # 如果已经超出分片范围，停止加载
                    if current_idx >= end_idx:
                        break
                
                if rpu_data:
                    # 导入并创建检测器
                    from ..detectors.rpu_structure_detector import RPUStructureDetector
                    detector = RPUStructureDetector(config)
                    
                    # 执行检测
                    results = detector.detect(rpu_data)
                    shard_results.extend(results)
            
            elif detector_name in ["TimeSeriesDetector", "StatisticalDistributionDetector", 
                                 "EncodingFormatDetector", "ConsistencyDetector"]:
                # 这些检测器的分片实现将在后续任务中添加
                pass
        
        shard.results = shard_results
        shard.status = ProcessingStatus.COMPLETED
        shard.end_time = datetime.now()
        
        return shard
    
    except Exception as e:
        shard.status = ProcessingStatus.FAILED
        shard.error_message = str(e)
        shard.end_time = datetime.now()
        return shard
    
    finally:
        # 清理资源
        if 'data_manager' in locals():
            data_manager.close()


class LoadBalancer:
    """负载均衡器
    
    管理任务分片的分配和工作进程的负载均衡。
    """
    
    def __init__(self, max_workers: int):
        """初始化负载均衡器
        
        Args:
            max_workers: 最大工作进程数
        """
        self.max_workers = max_workers
        self.worker_stats: Dict[int, WorkerProcess] = {}
        self.pending_shards: List[TaskShard] = []
        self.completed_shards: List[TaskShard] = []
        self.failed_shards: List[TaskShard] = []
        self.logger = get_logger(self.__class__.__name__)
    
    def create_shards(self, total_records: int, detector_names: List[str], 
                     config: DetectionConfig) -> List[TaskShard]:
        """创建任务分片
        
        Args:
            total_records: 总记录数
            detector_names: 检测器名称列表
            config: 检测配置
            
        Returns:
            任务分片列表
        """
        shards = []
        
        # 计算分片大小，这是经验值，可根据数据特征调整
        shard_size = max(1000, total_records // (self.max_workers * 2))
        
        # 创建分片
        for i in range(0, total_records, shard_size):
            end_idx = min(i + shard_size, total_records)
            shard_id = f"shard_{i}_{end_idx}"
            
            shard = TaskShard(
                shard_id=shard_id,
                data_range=(i, end_idx),
                detector_names=detector_names,
                config_dict=config.to_dict()
            )
            
            shards.append(shard)
        
        self.pending_shards = shards
        self.logger.info(f"创建了 {len(shards)} 个任务分片，每个分片大小约 {shard_size} 条记录")
        
        return shards
    
    def get_next_shard(self) -> Optional[TaskShard]:
        """获取下一个待处理的分片
        
        Returns:
            下一个任务分片，如果没有则返回None
        """
        if self.pending_shards:
            return self.pending_shards.pop(0)
        return None
    
    def complete_shard(self, shard: TaskShard) -> None:
        """标记分片完成
        
        Args:
            shard: 完成的分片
        """
        if shard.status == ProcessingStatus.COMPLETED:
            self.completed_shards.append(shard)
        else:
            self.failed_shards.append(shard)
    
    def get_progress(self) -> Dict[str, Any]:
        """获取处理进度
        
        Returns:
            进度信息
        """
        total_shards = len(self.pending_shards) + len(self.completed_shards) + len(self.failed_shards)
        completed_count = len(self.completed_shards)
        failed_count = len(self.failed_shards)
        
        return {
            'total_shards': total_shards,
            'completed_shards': completed_count,
            'failed_shards': failed_count,
            'pending_shards': len(self.pending_shards),
            'completion_percentage': (completed_count / total_shards * 100) if total_shards > 0 else 0,
            'failure_rate': (failed_count / total_shards * 100) if total_shards > 0 else 0
        }


class ResultAggregator:
    """结果聚合器
    
    收集和合并来自多个工作进程的检测结果。
    """
    
    def __init__(self):
        """初始化结果聚合器"""
        self.all_results: List[DetectionResult] = []
        self.results_by_detector: Dict[str, List[DetectionResult]] = {}
        self.results_by_severity: Dict[str, List[DetectionResult]] = {}
        self.processing_stats: Dict[str, Any] = {}
        self.logger = get_logger(self.__class__.__name__)
    
    def add_shard_results(self, shard: TaskShard) -> None:
        """添加分片结果
        
        Args:
            shard: 完成的任务分片
        """
        if shard.status != ProcessingStatus.COMPLETED:
            self.logger.warning(f"分片 {shard.shard_id} 处理失败: {shard.error_message}")
            return
        
        # 添加到总结果列表
        self.all_results.extend(shard.results)
        
        # 按检测器分类
        for result in shard.results:
            detector_name = result.detector_name
            if detector_name not in self.results_by_detector:
                self.results_by_detector[detector_name] = []
            self.results_by_detector[detector_name].append(result)
            
            # 按严重性分类
            severity = result.severity.value
            if severity not in self.results_by_severity:
                self.results_by_severity[severity] = []
            self.results_by_severity[severity].append(result)
        
        # 更新处理统计
        processing_time = shard.get_processing_time()
        if processing_time:
            shard_size = shard.get_size()
            processing_speed = shard_size / processing_time if processing_time > 0 else 0
            
            self.processing_stats[shard.shard_id] = {
                'size': shard_size,
                'processing_time': processing_time,
                'processing_speed': processing_speed,
                'results_count': len(shard.results)
            }
    
    def get_aggregated_results(self) -> List[DetectionResult]:
        """获取聚合后的结果
        
        Returns:
            所有检测结果
        """
        # 按严重性和置信度排序
        sorted_results = sorted(
            self.all_results,
            key=lambda x: (
                {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}.get(x.severity.value, 0),
                x.confidence_score
            ),
            reverse=True
        )
        
        return sorted_results
    
    def get_summary_statistics(self) -> Dict[str, Any]:
        """获取汇总统计信息
        
        Returns:
            统计信息
        """
        total_results = len(self.all_results)
        
        # 计算平均处理速度
        speeds = [stats['processing_speed'] for stats in self.processing_stats.values() 
                 if stats['processing_speed'] > 0]
        avg_speed = sum(speeds) / len(speeds) if speeds else 0
        
        return {
            'total_results': total_results,
            'results_by_detector': {k: len(v) for k, v in self.results_by_detector.items()},
            'results_by_severity': {k: len(v) for k, v in self.results_by_severity.items()},
            'average_processing_speed': avg_speed,
            'total_shards_processed': len(self.processing_stats),
            'processing_stats': self.processing_stats
        }


class ParallelDetectionEngine:
    """并行异常检测引擎
    
    协调多进程并行检测，实现任务分片、负载均衡和结果聚合。
    """
    
    def __init__(self, config: DetectionConfig):
        """初始化并行检测引擎
        
        Args:
            config: 检测配置
        """
        self.config = config
        self.logger = get_logger(self.__class__.__name__)
        
        # 初始化组件
        self.data_manager = DataAccessManager(config)
        self.recovery_manager = ErrorRecoveryManager(
            config.recovery, 
            config.paths.checkpoints_dir
        )
        
        # 并行处理组件
        self.load_balancer = LoadBalancer(config.performance.max_workers)
        self.result_aggregator = ResultAggregator()
        
        # 状态管理
        self.current_session: Optional[DetectionSession] = None
        self.detection_state: Optional[DetectionState] = None
        
        # 进度监控
        self._progress_lock = threading.Lock()
        self._stop_event = threading.Event()
        
        self.logger.info(f"并行检测引擎初始化完成，最大工作进程数: {config.performance.max_workers}")
    
    def run_parallel_detection(self, 
                             session_id: Optional[str] = None,
                             checkpoint_id: Optional[str] = None) -> DetectionSession:
        """执行并行异常检测
        
        Args:
            session_id: 会话ID
            checkpoint_id: 检查点ID，用于恢复检测
            
        Returns:
            检测会话信息
            
        Raises:
            DetectionLogicException: 检测执行失败
        """
        try:
            # 创建或恢复检测会话
            if checkpoint_id:
                session = self._resume_parallel_detection(checkpoint_id)
            else:
                session = self._create_detection_session(session_id)
            
            self.current_session = session
            self.logger.info(f"开始并行异常检测会话: {session.session_id}")
            
            # 获取数据统计信息
            data_stats = self.data_manager.get_data_statistics()
            total_records = data_stats.get('total_records', 0)
            
            if total_records == 0:
                self.logger.warning("没有数据可供检测")
                session.status = ProcessingStatus.COMPLETED
                return session
            
            # 创建检测状态
            self.detection_state = DetectionState(
                session_id=session.session_id,
                current_step="parallel_detection",
                processed_count=0,
                total_count=total_records,
                start_time=session.start_time,
                last_checkpoint_time=session.start_time
            )
            
            # 执行并行检测流程
            self._execute_parallel_detection_pipeline()
            
            # 完成检测会话
            session.end_time = datetime.now()
            session.status = ProcessingStatus.COMPLETED
            session.total_anomalies = len(self.result_aggregator.get_aggregated_results())
            
            self.logger.info(f"并行异常检测完成，发现 {session.total_anomalies} 个异常")
            
            return session
        
        except Exception as e:
            if self.current_session:
                self.current_session.status = ProcessingStatus.FAILED
            
            raise DetectionLogicException(f"并行异常检测执行失败: {e}",
                                        detector_name="ParallelDetectionEngine")
    
    def _create_detection_session(self, session_id: Optional[str] = None) -> DetectionSession:
        """创建新的检测会话"""
        if session_id is None:
            session_id = f"parallel_detection_{int(time.time())}"
        
        config_hash = self.config.get_config_hash()
        
        return DetectionSession(
            session_id=session_id,
            config_hash=config_hash,
            start_time=datetime.now(),
            status=ProcessingStatus.RUNNING
        )
    
    def _resume_parallel_detection(self, checkpoint_id: str) -> DetectionSession:
        """从检查点恢复并行检测会话"""
        try:
            self.detection_state = self.recovery_manager.restore_from_checkpoint(checkpoint_id)
            
            # 重新创建会话信息
            session = DetectionSession(
                session_id=self.detection_state.session_id,
                config_hash=self.config.get_config_hash(),
                start_time=self.detection_state.start_time,
                status=ProcessingStatus.RUNNING
            )
            
            self.logger.info(f"从检查点恢复并行检测会话: {checkpoint_id}")
            
            return session
        
        except Exception as e:
            raise DetectionLogicException(f"恢复并行检测会话失败: {e}",
                                        detector_name="ParallelDetectionEngine")
    
    def _execute_parallel_detection_pipeline(self) -> None:
        """执行并行检测管道"""
        try:
            # 步骤1: 执行不可分片的检测（在主进程中）
            self._run_non_shardable_detections()
            
            # 步骤2: 执行可分片的并行检测
            self._run_shardable_parallel_detections()
            
            # 步骤3: 聚合所有结果
            self._finalize_results()
            
        except Exception as e:
            self.logger.error(f"并行检测管道执行失败: {e}")
            raise
    
    def _run_non_shardable_detections(self) -> None:
        """运行不可分片的检测（在主进程中执行）"""
        self.logger.info("开始执行不可分片的检测")
        
        # 概念映射检测
        if 'ConceptMappingDetector' in self.config.enabled_detectors:
            try:
                from ..detectors.concept_mapping_detector import ConceptMappingDetector
                detector = ConceptMappingDetector(self.config)
                mapping_manager = self.data_manager.get_mapping_manager()
                results = detector.detect_all_anomalies(mapping_manager)
                
                # 将结果添加到聚合器
                for result in results:
                    self.result_aggregator.all_results.append(result)
                
                self.logger.info(f"概念映射检测完成，发现 {len(results)} 个异常")
                
            except Exception as e:
                self.logger.error(f"概念映射检测失败: {e}")
        
        # 遗漏重复检测
        if 'MissingDuplicateDetector' in self.config.enabled_detectors:
            try:
                from ..detectors.missing_duplicate_detector import MissingDuplicateDetector
                detector = MissingDuplicateDetector(self.config)
                mapping_manager = self.data_manager.get_mapping_manager()
                results = detector.detect_all_anomalies(mapping_manager, None)
                
                # 将结果添加到聚合器
                for result in results:
                    self.result_aggregator.all_results.append(result)
                
                self.logger.info(f"遗漏重复检测完成，发现 {len(results)} 个异常")
                
            except Exception as e:
                self.logger.error(f"遗漏重复检测失败: {e}")
    
    def _run_shardable_parallel_detections(self) -> None:
        """运行可分片的并行检测"""
        self.logger.info("开始执行可分片的并行检测")
        
        # 确定可分片的检测器
        shardable_detectors = []
        for detector_name in self.config.enabled_detectors:
            if detector_name in ['RPUStructureDetector', 'TimeSeriesDetector', 
                               'StatisticalDistributionDetector', 'EncodingFormatDetector', 
                               'ConsistencyDetector']:
                shardable_detectors.append(detector_name)
        
        if not shardable_detectors:
            self.logger.info("没有可分片的检测器需要执行")
            return
        
        # 获取总记录数
        data_stats = self.data_manager.get_data_statistics()
        total_records = data_stats.get('total_records', 0)
        
        # 创建任务分片
        shards = self.load_balancer.create_shards(
            total_records, shardable_detectors, self.config
        )
        
        if not shards:
            self.logger.info("没有创建任务分片")
            return
        
        # 执行并行处理
        self._execute_parallel_processing(shards)
    
    def _execute_parallel_processing(self, shards: List[TaskShard]) -> None:
        """执行并行处理
        
        Args:
            shards: 任务分片列表
        """
        max_workers = min(self.config.performance.max_workers, len(shards))
        
        self.logger.info(f"开始并行处理，工作进程数: {max_workers}，分片数: {len(shards)}")
        
        # 启动进度监控线程
        progress_thread = threading.Thread(target=self._monitor_progress, daemon=True)
        progress_thread.start()
        
        try:
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有任务
                future_to_shard = {
                    executor.submit(execute_detection_shard, shard): shard 
                    for shard in shards
                }
                
                # 收集结果
                completed_count = 0
                for future in as_completed(future_to_shard):
                    if self._stop_event.is_set():
                        self.logger.info("检测到停止信号，取消剩余任务")
                        break
                    
                    shard = future_to_shard[future]
                    
                    try:
                        completed_shard = future.result(timeout=300)  # 5分钟超时，这是经验值
                        self.load_balancer.complete_shard(completed_shard)
                        self.result_aggregator.add_shard_results(completed_shard)
                        
                        completed_count += 1
                        
                        # 更新检测状态
                        with self._progress_lock:
                            if self.detection_state:
                                self.detection_state.processed_count = completed_count
                        
                        # 定期创建检查点
                        if completed_count % 10 == 0:  # 每10个分片创建一次检查点，这是经验值
                            self._create_progress_checkpoint()
                        
                    except Exception as e:
                        self.logger.error(f"分片 {shard.shard_id} 处理失败: {e}")
                        shard.status = ProcessingStatus.FAILED
                        shard.error_message = str(e)
                        self.load_balancer.complete_shard(shard)
        
        finally:
            # 停止进度监控
            self._stop_event.set()
            if progress_thread.is_alive():
                progress_thread.join(timeout=5)
    
    def _monitor_progress(self) -> None:
        """监控处理进度"""
        while not self._stop_event.is_set():
            try:
                progress = self.load_balancer.get_progress()
                
                with self._progress_lock:
                    if self.detection_state:
                        self.detection_state.metadata['progress'] = progress
                
                self.logger.debug(f"处理进度: {progress['completion_percentage']:.1f}%")
                
                # 检查资源使用情况
                self.recovery_manager.check_resource_limits(
                    max_memory_gb=self.config.performance.max_memory_gb
                )
                
                time.sleep(10)  # 每10秒检查一次，这是经验值
                
            except Exception as e:
                self.logger.error(f"进度监控失败: {e}")
                time.sleep(5)
    
    def _create_progress_checkpoint(self) -> None:
        """创建进度检查点"""
        try:
            if self.detection_state:
                checkpoint_id = self.recovery_manager.create_checkpoint(self.detection_state)
                self.logger.debug(f"创建进度检查点: {checkpoint_id}")
        except Exception as e:
            self.logger.error(f"创建进度检查点失败: {e}")
    
    def _finalize_results(self) -> None:
        """完成结果处理"""
        self.logger.info("开始最终结果处理")
        
        # 获取汇总统计
        summary_stats = self.result_aggregator.get_summary_statistics()
        progress_stats = self.load_balancer.get_progress()
        
        self.logger.info(f"并行检测统计: {summary_stats}")
        self.logger.info(f"分片处理统计: {progress_stats}")
        
        # 更新检测状态
        if self.detection_state:
            self.detection_state.metadata.update({
                'summary_stats': summary_stats,
                'progress_stats': progress_stats,
                'finalized_at': datetime.now().isoformat()
            })
    
    def get_detection_results(self) -> List[DetectionResult]:
        """获取检测结果"""
        return self.result_aggregator.get_aggregated_results()
    
    def get_detection_summary(self) -> Dict[str, Any]:
        """获取检测摘要"""
        if not self.current_session:
            return {'error': '没有活动的检测会话'}
        
        summary_stats = self.result_aggregator.get_summary_statistics()
        progress_stats = self.load_balancer.get_progress()
        
        return {
            'session_id': self.current_session.session_id,
            'status': self.current_session.status.value,
            'start_time': self.current_session.start_time.isoformat(),
            'end_time': self.current_session.end_time.isoformat() if self.current_session.end_time else None,
            'total_anomalies': summary_stats['total_results'],
            'results_by_detector': summary_stats['results_by_detector'],
            'results_by_severity': summary_stats['results_by_severity'],
            'processing_performance': {
                'average_speed': summary_stats['average_processing_speed'],
                'total_shards': progress_stats['total_shards'],
                'completed_shards': progress_stats['completed_shards'],
                'failed_shards': progress_stats['failed_shards'],
                'completion_percentage': progress_stats['completion_percentage']
            },
            'config_hash': self.current_session.config_hash
        }
    
    def stop_detection(self) -> None:
        """停止检测"""
        self.logger.info("收到停止检测请求")
        self._stop_event.set()
        
        if self.current_session:
            self.current_session.status = ProcessingStatus.PAUSED
    
    def create_checkpoint(self) -> str:
        """创建检查点"""
        if not self.detection_state:
            raise DetectionLogicException("没有活动的检测状态")
        
        return self.recovery_manager.create_checkpoint(self.detection_state)
    
    def close(self) -> None:
        """关闭并行检测引擎"""
        try:
            self._stop_event.set()
            
            if self.data_manager:
                self.data_manager.close()
            
            self.logger.info("并行检测引擎已关闭")
        
        except Exception as e:
            self.logger.error(f"关闭并行检测引擎失败: {e}")
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()