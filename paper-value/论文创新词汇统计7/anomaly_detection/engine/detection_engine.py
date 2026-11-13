"""
异常检测引擎

协调各个检测器的工作，提供统一的检测接口和结果聚合功能。
"""

from typing import List, Dict, Any, Optional, Iterator
from datetime import datetime
import time

from ..core.config import DetectionConfig
from ..core.data_models import DetectionResult, DetectionSession, ProcessingStatus
from ..core.exceptions import DetectionLogicException, ResourceException
from ..core.logging import get_logger
from ..core.error_recovery import ErrorRecoveryManager, DetectionState
from ..data_access.manager import DataAccessManager


class AnomalyDetectionEngine:
    """异常检测引擎
    
    协调各个检测器的工作，管理检测流程和结果聚合。
    """
    
    def __init__(self, config: DetectionConfig):
        """初始化检测引擎
        
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
        
        # 检测器注册表
        self.detectors: Dict[str, Any] = {}
        self._register_detectors()
        
        # 检测状态
        self.current_session: Optional[DetectionSession] = None
        self.detection_results: List[DetectionResult] = []
        
        self.logger.info("异常检测引擎初始化完成")
    
    def _register_detectors(self) -> None:
        """注册检测器
        
        根据配置启用相应的检测器。
        """
        # 导入检测器类
        try:
            from ..detectors.concept_mapping_detector import ConceptMappingDetector
        except ImportError:
            ConceptMappingDetector = None
        
        try:
            from ..detectors.missing_duplicate_detector import MissingDuplicateDetector
        except ImportError:
            MissingDuplicateDetector = None
        
        try:
            from ..detectors.rpu_structure_detector import RPUStructureDetector
        except ImportError:
            RPUStructureDetector = None
        
        try:
            from ..detectors.time_series_detector import TimeSeriesDetector
        except ImportError:
            TimeSeriesDetector = None
        
        try:
            from ..detectors.statistical_distribution_detector import StatisticalDistributionDetector
        except ImportError:
            StatisticalDistributionDetector = None
        
        try:
            from ..detectors.format_encoding_detector import FormatEncodingDetector
        except ImportError:
            FormatEncodingDetector = None
        
        try:
            from ..detectors.consistency_detector import ConsistencyDetector
        except ImportError:
            ConsistencyDetector = None
        
        detector_classes = {
            'ConceptMappingDetector': ConceptMappingDetector,
            'MissingDuplicateDetector': MissingDuplicateDetector,
            'RPUStructureDetector': RPUStructureDetector,
            'TimeSeriesDetector': TimeSeriesDetector,
            'StatisticalDistributionDetector': StatisticalDistributionDetector,
            'FormatEncodingDetector': FormatEncodingDetector,
            'ConsistencyDetector': ConsistencyDetector
        }
        
        for detector_name in self.config.enabled_detectors:
            if detector_name in detector_classes:
                detector_class = detector_classes[detector_name]
                if detector_class is not None:
                    try:
                        # 一致性检测器需要数据管理器参数
                        if detector_name == 'ConsistencyDetector':
                            self.detectors[detector_name] = detector_class(self.config, self.data_manager)
                        else:
                            self.detectors[detector_name] = detector_class(self.config)
                        self.logger.info(f"注册检测器: {detector_name}")
                    except Exception as e:
                        self.logger.error(f"注册检测器失败 {detector_name}: {e}")
                else:
                    self.logger.warning(f"检测器 {detector_name} 尚未实现")
            else:
                self.logger.warning(f"未知的检测器: {detector_name}")
    
    def run_detection(self, 
                     session_id: Optional[str] = None,
                     checkpoint_id: Optional[str] = None) -> DetectionSession:
        """执行完整的异常检测
        
        Args:
            session_id: 会话ID，如果不提供则自动生成
            checkpoint_id: 检查点ID，用于恢复检测
            
        Returns:
            检测会话信息
            
        Raises:
            DetectionLogicException: 检测执行失败
        """
        try:
            # 创建或恢复检测会话
            if checkpoint_id:
                session = self._resume_detection(checkpoint_id)
            else:
                session = self._create_detection_session(session_id)
            
            self.current_session = session
            self.logger.info(f"开始异常检测会话: {session.session_id}")
            
            # 获取数据统计信息
            data_stats = self.data_manager.get_data_statistics()
            total_records = data_stats.get('total_records', 0)
            
            # 创建检测状态
            detection_state = DetectionState(
                session_id=session.session_id,
                current_step="initialization",
                processed_count=0,
                total_count=total_records,
                start_time=session.start_time,
                last_checkpoint_time=session.start_time
            )
            
            # 执行检测流程
            self._execute_detection_pipeline(detection_state)
            
            # 完成检测会话
            session.end_time = datetime.now()
            session.status = ProcessingStatus.COMPLETED
            session.total_anomalies = len(self.detection_results)
            
            self.logger.info(f"异常检测完成，发现 {session.total_anomalies} 个异常")
            
            return session
        
        except Exception as e:
            if self.current_session:
                self.current_session.status = ProcessingStatus.FAILED
            
            raise DetectionLogicException(f"异常检测执行失败: {e}",
                                        detector_name="AnomalyDetectionEngine")
    
    def _create_detection_session(self, session_id: Optional[str] = None) -> DetectionSession:
        """创建新的检测会话
        
        Args:
            session_id: 会话ID
            
        Returns:
            检测会话
        """
        if session_id is None:
            session_id = f"detection_{int(time.time())}"
        
        config_hash = self.config.get_config_hash()
        
        return DetectionSession(
            session_id=session_id,
            config_hash=config_hash,
            start_time=datetime.now(),
            status=ProcessingStatus.RUNNING
        )
    
    def _resume_detection(self, checkpoint_id: str) -> DetectionSession:
        """从检查点恢复检测会话
        
        Args:
            checkpoint_id: 检查点ID
            
        Returns:
            检测会话
        """
        try:
            detection_state = self.recovery_manager.restore_from_checkpoint(checkpoint_id)
            
            # 重新创建会话信息
            session = DetectionSession(
                session_id=detection_state.session_id,
                config_hash=self.config.get_config_hash(),
                start_time=detection_state.start_time,
                status=ProcessingStatus.RUNNING
            )
            
            self.logger.info(f"从检查点恢复检测会话: {checkpoint_id}")
            
            return session
        
        except Exception as e:
            raise DetectionLogicException(f"恢复检测会话失败: {e}",
                                        detector_name="AnomalyDetectionEngine")
    
    def _execute_detection_pipeline(self, detection_state: DetectionState) -> None:
        """执行检测管道
        
        Args:
            detection_state: 检测状态
        """
        try:
            # 步骤1: 数据一致性验证
            detection_state.current_step = "data_consistency_validation"
            self._validate_data_consistency(detection_state)
            
            # 步骤2: 概念映射检测
            if 'ConceptMappingDetector' in self.detectors:
                detection_state.current_step = "concept_mapping_detection"
                self._run_concept_mapping_detection(detection_state)
            
            # 步骤3: 遗漏重复检测
            if 'MissingDuplicateDetector' in self.detectors:
                detection_state.current_step = "missing_duplicate_detection"
                self._run_missing_duplicate_detection(detection_state)
            
            # 步骤4: RPU结构检测
            if 'RPUStructureDetector' in self.detectors:
                detection_state.current_step = "rpu_structure_detection"
                self._run_rpu_structure_detection(detection_state)
            
            # 步骤5: 时间序列检测
            if 'TimeSeriesDetector' in self.detectors:
                detection_state.current_step = "time_series_detection"
                self._run_time_series_detection(detection_state)
            
            # 步骤6: 统计分布检测
            if 'StatisticalDistributionDetector' in self.detectors:
                detection_state.current_step = "statistical_distribution_detection"
                self._run_statistical_distribution_detection(detection_state)
            
            # 步骤7: 格式编码检测
            if 'FormatEncodingDetector' in self.detectors:
                detection_state.current_step = "format_encoding_detection"
                self._run_format_encoding_detection(detection_state)
            
            # 步骤8: 跨文件一致性检测
            if 'ConsistencyDetector' in self.detectors:
                detection_state.current_step = "consistency_detection"
                self._run_consistency_detection(detection_state)
            
            # 步骤9: 结果聚合和分析
            detection_state.current_step = "result_aggregation"
            self._aggregate_results(detection_state)
            
        except Exception as e:
            self.logger.error(f"检测管道执行失败: {e}")
            raise
    
    def _validate_data_consistency(self, detection_state: DetectionState) -> None:
        """验证数据一致性"""
        try:
            self.logger.info("开始数据一致性验证")
            
            consistency_results = self.data_manager.validate_data_consistency()
            
            # 如果发现一致性问题，创建异常记录
            if consistency_results['issues']:
                for issue in consistency_results['issues']:
                    result = DetectionResult(
                        anomaly_id=f"consistency_{int(time.time())}_{len(self.detection_results)}",
                        detector_name="DataConsistencyValidator",
                        anomaly_type="data_consistency_issue",
                        severity=self._assess_consistency_severity(issue),
                        description=issue,
                        affected_entities=[],
                        evidence={'consistency_check': consistency_results},
                        suggested_fixes=[self._suggest_consistency_fix(issue)],
                        confidence_score=0.9,
                        detection_timestamp=datetime.now()
                    )
                    
                    self.detection_results.append(result)
            
            self.logger.info(f"数据一致性验证完成，发现 {len(consistency_results['issues'])} 个问题")
            
        except Exception as e:
            self.logger.error(f"数据一致性验证失败: {e}")
            raise
    
    def _assess_consistency_severity(self, issue: str) -> str:
        """评估一致性问题的严重性
        
        Args:
            issue: 问题描述
            
        Returns:
            严重性级别
        """
        # 经验值判断规则，建议基于历史异常数据进行优化
        if any(keyword in issue.lower() for keyword in ['不存在', '缺失', '损坏']):
            return 'critical'
        elif any(keyword in issue.lower() for keyword in ['冲突', '不一致', '重复']):
            return 'high'
        elif any(keyword in issue.lower() for keyword in ['异常', '超限']):
            return 'medium'
        else:
            return 'low'
    
    def _suggest_consistency_fix(self, issue: str) -> str:
        """为一致性问题提供修复建议
        
        Args:
            issue: 问题描述
            
        Returns:
            修复建议
        """
        # 基于问题类型提供相应的修复建议
        if '不存在' in issue:
            return "检查文件路径和权限，确保数据文件可访问"
        elif '冲突' in issue or '不一致' in issue:
            return "检查数据处理流程，确保数据同步更新"
        elif '重复' in issue:
            return "运行数据去重程序，清理重复记录"
        else:
            return "请检查相关数据源和处理逻辑"
    
    def _run_concept_mapping_detection(self, detection_state: DetectionState) -> None:
        """运行概念映射检测"""
        try:
            self.logger.info("开始概念映射检测")
            
            if 'ConceptMappingDetector' not in self.detectors:
                self.logger.warning("概念映射检测器未注册")
                return
            
            detector = self.detectors['ConceptMappingDetector']
            
            # 获取映射文件管理器
            mapping_manager = self.data_manager.get_mapping_manager()
            
            # 执行检测
            mapping_results = detector.detect_all_anomalies(mapping_manager)
            
            # 添加到总结果中
            self.detection_results.extend(mapping_results)
            
            self.logger.info(f"概念映射检测完成，发现 {len(mapping_results)} 个异常")
            
        except Exception as e:
            self.logger.error(f"概念映射检测失败: {e}")
            raise
    
    def _run_missing_duplicate_detection(self, detection_state: DetectionState) -> None:
        """运行遗漏重复检测"""
        try:
            self.logger.info("开始遗漏重复检测")
            
            if 'MissingDuplicateDetector' not in self.detectors:
                self.logger.warning("遗漏重复检测器未注册")
                return
            
            detector = self.detectors['MissingDuplicateDetector']
            
            # 获取映射文件管理器
            mapping_manager = self.data_manager.get_mapping_manager()
            
            # 从现有数据中提取概念全集
            # 这里可以从数据库或其他数据源获取更完整的概念集合
            concept_universe = None  # 让检测器自动从映射中提取
            
            # 执行检测
            missing_duplicate_results = detector.detect_all_anomalies(
                mapping_manager, concept_universe)
            
            # 添加到总结果中
            self.detection_results.extend(missing_duplicate_results)
            
            self.logger.info(f"遗漏重复检测完成，发现 {len(missing_duplicate_results)} 个异常")
            
        except Exception as e:
            self.logger.error(f"遗漏重复检测失败: {e}")
            raise
    
    def _run_rpu_structure_detection(self, detection_state: DetectionState) -> None:
        """运行RPU结构检测"""
        try:
            self.logger.info("开始RPU结构检测")
            
            if 'RPUStructureDetector' not in self.detectors:
                self.logger.warning("RPUStructureDetector未启用，跳过RPU结构检测")
                return
            
            detector = self.detectors['RPUStructureDetector']
            
            # 获取RPU数据
            rpu_data = []
            batch_count = 0
            
            for rpu_batch in self.data_manager.get_rpu_batches(batch_size=1000):
                rpu_data.extend(rpu_batch)
                batch_count += 1
                
                if batch_count % 10 == 0:
                    self.logger.debug(f"已加载 {len(rpu_data)} 个RPU记录")
            
            self.logger.info(f"总共加载了 {len(rpu_data)} 个RPU记录用于结构检测")
            
            if not rpu_data:
                self.logger.warning("没有RPU数据可供检测")
                return
            
            # 执行RPU结构检测
            rpu_structure_results = detector.detect(rpu_data)
            
            # 更新检测状态
            detection_state.rpus_processed = len(rpu_data)
            detection_state.anomalies_found += len(rpu_structure_results)
            
            # 添加到总结果中
            self.detection_results.extend(rpu_structure_results)
            
            self.logger.info(f"RPU结构检测完成，发现 {len(rpu_structure_results)} 个异常")
            
        except Exception as e:
            self.logger.error(f"RPU结构检测失败: {e}")
            raise
    
    def _run_time_series_detection(self, detection_state: DetectionState) -> None:
        """运行时间序列检测"""
        try:
            self.logger.info("开始时间序列检测")
            
            if 'TimeSeriesDetector' not in self.detectors:
                self.logger.warning("TimeSeriesDetector未启用，跳过时间序列检测")
                return
            
            detector = self.detectors['TimeSeriesDetector']
            
            # 获取时间序列数据 - 这里需要从数据管理器获取创新信号的时间序列
            # 由于当前系统主要处理RPU数据，我们模拟时间序列数据的获取
            time_series_data = self._extract_time_series_data()
            
            if not time_series_data:
                self.logger.warning("没有时间序列数据可供检测")
                return
            
            # 执行时间序列检测
            time_series_results = detector.detect_anomalies(time_series_data)
            
            # 转换为DetectionResult格式
            converted_results = []
            for anomaly in time_series_results:
                result = DetectionResult(
                    anomaly_id=f"ts_{int(time.time())}_{len(converted_results)}",
                    detector_name="TimeSeriesDetector",
                    anomaly_type=anomaly.anomaly_type,
                    severity=anomaly.severity,
                    description=anomaly.description,
                    affected_entities=[],
                    evidence=anomaly.affected_data,
                    suggested_fixes=[anomaly.suggested_fix],
                    confidence_score=0.8,  # 经验值：时间序列检测的默认置信度
                    detection_timestamp=datetime.now()
                )
                converted_results.append(result)
            
            # 添加到总结果中
            self.detection_results.extend(converted_results)
            
            self.logger.info(f"时间序列检测完成，发现 {len(converted_results)} 个异常")
            
        except Exception as e:
            self.logger.error(f"时间序列检测失败: {e}")
            raise
    
    def _run_statistical_distribution_detection(self, detection_state: DetectionState) -> None:
        """运行统计分布检测"""
        try:
            self.logger.info("开始统计分布检测")
            
            if 'StatisticalDistributionDetector' not in self.detectors:
                self.logger.warning("StatisticalDistributionDetector未启用，跳过统计分布检测")
                return
            
            detector = self.detectors['StatisticalDistributionDetector']
            
            # 获取统计数据
            statistical_data = self._extract_statistical_data()
            
            if not statistical_data:
                self.logger.warning("没有统计数据可供检测")
                return
            
            # 执行统计分布检测
            statistical_results = detector.detect_anomalies(statistical_data)
            
            # 转换为DetectionResult格式
            converted_results = []
            for anomaly in statistical_results:
                result = DetectionResult(
                    anomaly_id=f"stat_{int(time.time())}_{len(converted_results)}",
                    detector_name="StatisticalDistributionDetector",
                    anomaly_type=anomaly.anomaly_type,
                    severity=anomaly.severity,
                    description=anomaly.description,
                    affected_entities=[],
                    evidence=anomaly.affected_data,
                    suggested_fixes=[anomaly.suggested_fix],
                    confidence_score=0.85,  # 经验值：统计检测的默认置信度
                    detection_timestamp=datetime.now()
                )
                converted_results.append(result)
            
            # 添加到总结果中
            self.detection_results.extend(converted_results)
            
            self.logger.info(f"统计分布检测完成，发现 {len(converted_results)} 个异常")
            
        except Exception as e:
            self.logger.error(f"统计分布检测失败: {e}")
            raise
    
    def _run_format_encoding_detection(self, detection_state: DetectionState) -> None:
        """运行格式编码检测"""
        try:
            self.logger.info("开始格式编码检测")
            
            if 'FormatEncodingDetector' not in self.detectors:
                self.logger.warning("FormatEncodingDetector未启用，跳过格式编码检测")
                return
            
            detector = self.detectors['FormatEncodingDetector']
            
            # 获取需要检测的文件列表
            files_to_check = self._get_files_for_format_check()
            
            format_results = []
            
            for file_info in files_to_check:
                file_path = file_info['path']
                file_type = file_info['type']
                
                try:
                    # 根据文件类型执行相应的检测
                    if file_type == 'json':
                        anomalies = detector.detect_json_format_anomalies(file_path)
                    elif file_type == 'csv':
                        anomalies = detector.detect_csv_format_anomalies(file_path)
                    else:
                        # 通用编码检测
                        anomalies = detector.detect_encoding_anomalies(file_path)
                    
                    format_results.extend(anomalies)
                    
                except Exception as e:
                    self.logger.warning(f"检测文件 {file_path} 时出错: {e}")
                    continue
            
            # 转换为DetectionResult格式
            converted_results = []
            for anomaly in format_results:
                result = DetectionResult(
                    anomaly_id=f"fmt_{int(time.time())}_{len(converted_results)}",
                    detector_name="FormatEncodingDetector",
                    anomaly_type=anomaly.anomaly_type,
                    severity=anomaly.severity,
                    description=anomaly.description,
                    affected_entities=[],
                    evidence=anomaly.affected_data,
                    suggested_fixes=[anomaly.suggested_fix],
                    confidence_score=0.9,  # 经验值：格式检测的默认置信度
                    detection_timestamp=datetime.now()
                )
                converted_results.append(result)
            
            # 添加到总结果中
            self.detection_results.extend(converted_results)
            
            self.logger.info(f"格式编码检测完成，发现 {len(converted_results)} 个异常")
            
        except Exception as e:
            self.logger.error(f"格式编码检测失败: {e}")
            raise
    
    def _run_consistency_detection(self, detection_state: DetectionState) -> None:
        """运行跨文件一致性检测"""
        try:
            self.logger.info("开始跨文件一致性检测")
            
            if 'ConsistencyDetector' not in self.detectors:
                self.logger.warning("ConsistencyDetector未启用，跳过一致性检测")
                return
            
            detector = self.detectors['ConsistencyDetector']
            
            # 执行各种一致性检测
            consistency_results = []
            
            # ID引用一致性检测
            id_anomalies = detector.detect_id_reference_consistency()
            consistency_results.extend(id_anomalies)
            
            # 重叠数据一致性检测
            overlap_anomalies = detector.detect_overlap_data_consistency()
            consistency_results.extend(overlap_anomalies)
            
            # 元数据一致性检测
            metadata_anomalies = detector.detect_metadata_consistency()
            consistency_results.extend(metadata_anomalies)
            
            # 转换为DetectionResult格式
            converted_results = []
            for anomaly in consistency_results:
                result = DetectionResult(
                    anomaly_id=f"cons_{int(time.time())}_{len(converted_results)}",
                    detector_name="ConsistencyDetector",
                    anomaly_type=anomaly.anomaly_type,
                    severity=anomaly.severity,
                    description=anomaly.description,
                    affected_entities=anomaly.files_involved,
                    evidence=anomaly.affected_data,
                    suggested_fixes=[anomaly.suggested_fix],
                    confidence_score=0.88,  # 经验值：一致性检测的默认置信度
                    detection_timestamp=datetime.now()
                )
                converted_results.append(result)
            
            # 添加到总结果中
            self.detection_results.extend(converted_results)
            
            self.logger.info(f"跨文件一致性检测完成，发现 {len(converted_results)} 个异常")
            
        except Exception as e:
            self.logger.error(f"跨文件一致性检测失败: {e}")
            raise
    
    def _aggregate_results(self, detection_state: DetectionState) -> None:
        """聚合检测结果"""
        try:
            self.logger.info("开始结果聚合")
            
            # 按严重性排序
            self.detection_results.sort(
                key=lambda x: {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}.get(x.severity.value, 0),
                reverse=True
            )
            
            # 统计结果
            severity_counts = {}
            detector_counts = {}
            
            for result in self.detection_results:
                severity = result.severity.value
                detector = result.detector_name
                
                severity_counts[severity] = severity_counts.get(severity, 0) + 1
                detector_counts[detector] = detector_counts.get(detector, 0) + 1
            
            self.logger.info(f"结果聚合完成: {severity_counts}")
            
        except Exception as e:
            self.logger.error(f"结果聚合失败: {e}")
            raise
    
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
        
        # 统计异常类型和严重性
        type_counts = {}
        severity_counts = {}
        detector_counts = {}
        
        for result in self.detection_results:
            anomaly_type = result.anomaly_type
            severity = result.severity.value
            detector = result.detector_name
            
            type_counts[anomaly_type] = type_counts.get(anomaly_type, 0) + 1
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
            detector_counts[detector] = detector_counts.get(detector, 0) + 1
        
        return {
            'session_id': self.current_session.session_id,
            'status': self.current_session.status.value,
            'start_time': self.current_session.start_time.isoformat(),
            'end_time': self.current_session.end_time.isoformat() if self.current_session.end_time else None,
            'total_anomalies': len(self.detection_results),
            'anomaly_types': type_counts,
            'severity_distribution': severity_counts,
            'detector_distribution': detector_counts,
            'config_hash': self.current_session.config_hash
        }
    
    def create_checkpoint(self) -> str:
        """创建检查点
        
        Returns:
            检查点ID
        """
        if not self.current_session:
            raise DetectionLogicException("没有活动的检测会话")
        
        detection_state = DetectionState(
            session_id=self.current_session.session_id,
            current_step="checkpoint",
            processed_count=len(self.detection_results),
            total_count=0,  # 将在实际实现中更新
            start_time=self.current_session.start_time,
            last_checkpoint_time=datetime.now(),
            metadata={
                'detection_results_count': len(self.detection_results),
                'config_hash': self.current_session.config_hash
            }
        )
        
        return self.recovery_manager.create_checkpoint(detection_state)
    
    def close(self) -> None:
        """关闭检测引擎"""
        try:
            if self.data_manager:
                self.data_manager.close()
            
            self.logger.info("异常检测引擎已关闭")
        
        except Exception as e:
            self.logger.error(f"关闭异常检测引擎失败: {e}")
    
    def _extract_time_series_data(self) -> List:
        """提取时间序列数据
        
        Returns:
            时间序列数据点列表
        """
        try:
            # 从TimeSeriesDetector导入数据类型
            from ..detectors.time_series_detector import TimeSeriesPoint
            
            time_series_data = []
            
            # 获取RPU数据并按时间排序
            rpu_batches = self.data_manager.get_rpu_batches(batch_size=1000)
            
            for batch in rpu_batches:
                for rpu in batch:
                    # 将RPU数据转换为时间序列点
                    # 这里使用confidence作为信号值，timestamp需要从其他地方获取
                    if hasattr(rpu, 'timestamp') and rpu.timestamp:
                        point = TimeSeriesPoint(
                            timestamp=rpu.timestamp,
                            value=rpu.confidence,
                            paper_id=rpu.paper_id,
                            concept=f"{rpu.task}_{rpu.object}",
                            signal_type="confidence"
                        )
                        time_series_data.append(point)
            
            # 按时间排序
            time_series_data.sort(key=lambda x: x.timestamp)
            
            self.logger.debug(f"提取了 {len(time_series_data)} 个时间序列数据点")
            return time_series_data
            
        except Exception as e:
            self.logger.warning(f"提取时间序列数据失败: {e}")
            return []
    
    def _extract_statistical_data(self) -> Dict[str, Any]:
        """提取统计数据
        
        Returns:
            包含各种统计数据的字典
        """
        try:
            # 从StatisticalDistributionDetector导入数据类型
            from ..detectors.statistical_distribution_detector import (
                FrequencyData, PMIData, EntropyData, CooccurrenceMatrix
            )
            import numpy as np
            from collections import Counter
            
            statistical_data = {}
            
            # 收集概念频率数据
            concept_counts = Counter()
            total_rpus = 0
            
            rpu_batches = self.data_manager.get_rpu_batches(batch_size=1000)
            
            for batch in rpu_batches:
                for rpu in batch:
                    # 统计task, object, modifier的频率
                    if rpu.task:
                        concept_counts[f"task:{rpu.task}"] += 1
                    if rpu.object:
                        concept_counts[f"object:{rpu.object}"] += 1
                    if rpu.modifier:
                        concept_counts[f"modifier:{rpu.modifier}"] += 1
                    total_rpus += 1
            
            # 创建频率数据
            frequency_data = []
            for concept, count in concept_counts.items():
                freq_data = FrequencyData(
                    concept=concept,
                    frequency=count,
                    total_count=total_rpus
                )
                frequency_data.append(freq_data)
            
            statistical_data['frequency_data'] = frequency_data
            
            # 创建简单的PMI数据（概念对的共现）
            pmi_data = []
            concept_pairs = {}
            
            # 重新遍历数据计算共现
            rpu_batches = self.data_manager.get_rpu_batches(batch_size=1000)
            
            for batch in rpu_batches:
                for rpu in batch:
                    if rpu.task and rpu.object:
                        pair_key = (f"task:{rpu.task}", f"object:{rpu.object}")
                        concept_pairs[pair_key] = concept_pairs.get(pair_key, 0) + 1
            
            # 创建PMI数据
            for (concept_a, concept_b), joint_freq in list(concept_pairs.items())[:100]:  # 限制数量避免过多计算
                freq_a = concept_counts.get(concept_a, 0)
                freq_b = concept_counts.get(concept_b, 0)
                
                pmi = PMIData(
                    concept_a=concept_a,
                    concept_b=concept_b,
                    joint_frequency=joint_freq,
                    frequency_a=freq_a,
                    frequency_b=freq_b,
                    total_count=total_rpus
                )
                pmi_data.append(pmi)
            
            statistical_data['pmi_data'] = pmi_data
            
            # 创建熵值数据
            entropy_data = []
            for concept, count in list(concept_counts.items())[:50]:  # 限制数量
                # 创建简单的分布（这里简化处理）
                distribution = [count, total_rpus - count]
                entropy = EntropyData(
                    concept=concept,
                    distribution=distribution
                )
                entropy_data.append(entropy)
            
            statistical_data['entropy_data'] = entropy_data
            
            # 创建共现矩阵
            concepts = list(concept_counts.keys())[:20]  # 限制矩阵大小，经验值：20x20矩阵便于处理
            if concepts:
                matrix_size = len(concepts)
                cooccurrence_matrix = np.zeros((matrix_size, matrix_size))
                
                # 填充共现矩阵（简化实现）
                for i, concept_a in enumerate(concepts):
                    for j, concept_b in enumerate(concepts):
                        if i != j:
                            pair_key = (concept_a, concept_b)
                            cooccurrence_matrix[i][j] = concept_pairs.get(pair_key, 0)
                        else:
                            cooccurrence_matrix[i][j] = concept_counts[concept_a]
                
                cooccurrence_data = CooccurrenceMatrix(
                    concepts=concepts,
                    matrix=cooccurrence_matrix
                )
                statistical_data['cooccurrence_data'] = cooccurrence_data
            
            self.logger.debug(f"提取了统计数据: {len(frequency_data)} 个频率项, "
                            f"{len(pmi_data)} 个PMI项, {len(entropy_data)} 个熵值项")
            
            return statistical_data
            
        except Exception as e:
            self.logger.warning(f"提取统计数据失败: {e}")
            return {}
    
    def _get_files_for_format_check(self) -> List[Dict[str, str]]:
        """获取需要进行格式检查的文件列表
        
        Returns:
            文件信息列表，包含路径和类型
        """
        files_to_check = []
        
        try:
            # 检查映射文件
            mapping_path = getattr(self.config.paths, 'mapping_file', None)
            if mapping_path and Path(mapping_path).exists():
                files_to_check.append({
                    'path': mapping_path,
                    'type': 'json'
                })
            
            # 检查分片文件
            shard_metadata = self.data_manager.get_shard_metadata()
            for shard in shard_metadata[:10]:  # 限制检查数量，经验值：检查前10个分片文件
                if Path(shard.file_path).exists():
                    # 根据文件扩展名确定类型
                    file_ext = Path(shard.file_path).suffix.lower()
                    if file_ext == '.json':
                        file_type = 'json'
                    elif file_ext == '.csv':
                        file_type = 'csv'
                    else:
                        file_type = 'text'
                    
                    files_to_check.append({
                        'path': shard.file_path,
                        'type': file_type
                    })
            
            # 检查数据库文件
            db_path = getattr(self.config.paths, 'database_path', None)
            if db_path and Path(db_path).exists():
                files_to_check.append({
                    'path': db_path,
                    'type': 'database'
                })
            
            self.logger.debug(f"找到 {len(files_to_check)} 个文件需要格式检查")
            
        except Exception as e:
            self.logger.warning(f"获取格式检查文件列表失败: {e}")
        
        return files_to_check
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()