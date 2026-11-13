"""
配置管理系统

提供异常检测系统的配置管理功能，包括检测参数、路径配置、性能设置等。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any
import json
import os
from .exceptions import ConfigurationException


@dataclass
class RetryPolicy:
    """重试策略配置"""
    max_attempts: int = 3
    backoff_factor: float = 2.0
    initial_delay: float = 1.0
    max_delay: float = 60.0
    
    def __post_init__(self):
        if self.max_attempts < 1:
            raise ValueError("最大重试次数必须大于0")
        if self.backoff_factor < 1.0:
            raise ValueError("退避因子必须大于等于1.0")


@dataclass
class PerformanceConfig:
    """性能配置"""
    # 内存限制 (GB)
    max_memory_gb: float = 4.0
    
    # 处理速度基准 (RPU/秒)
    min_processing_speed: int = 1000
    
    # 并行处理配置
    max_workers: int = 8
    batch_size: int = 1000
    
    # 检查点配置
    checkpoint_interval: int = 10000  # 每处理多少条记录创建检查点
    max_checkpoints: int = 10  # 最多保留多少个检查点
    
    def __post_init__(self):
        if self.max_memory_gb <= 0:
            raise ValueError("内存限制必须大于0")
        if self.min_processing_speed <= 0:
            raise ValueError("最小处理速度必须大于0")
        if self.max_workers <= 0:
            raise ValueError("最大工作进程数必须大于0")


@dataclass
class DetectionThresholds:
    """检测阈值配置"""
    # 概念映射检测阈值
    case_similarity_threshold: float = 0.9
    plural_similarity_threshold: float = 0.85
    numerical_range_threshold: float = 100.0  # 数值范围超过此值视为异常
    cross_domain_threshold: float = 0.3  # 跨领域相似度低于此值视为异常
    
    # 语义相似性阈值
    semantic_similarity_threshold: float = 0.8
    synonym_threshold: float = 0.9
    abbreviation_threshold: float = 0.95
    
    # 统计异常阈值
    frequency_outlier_zscore: float = 3.0
    pmi_anomaly_threshold: float = 10.0
    entropy_anomaly_threshold: float = 2.0
    
    # RPU结构检测阈值
    rpu_semantic_threshold: float = 0.7
    rpu_completeness_threshold: float = 0.9
    
    def __post_init__(self):
        """验证阈值范围"""
        thresholds = [
            ("case_similarity_threshold", self.case_similarity_threshold),
            ("plural_similarity_threshold", self.plural_similarity_threshold),
            ("semantic_similarity_threshold", self.semantic_similarity_threshold),
            ("synonym_threshold", self.synonym_threshold),
            ("abbreviation_threshold", self.abbreviation_threshold),
            ("rpu_semantic_threshold", self.rpu_semantic_threshold),
            ("rpu_completeness_threshold", self.rpu_completeness_threshold)
        ]
        
        for name, value in thresholds:
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} 必须在0-1之间: {value}")


@dataclass
class PathConfig:
    """路径配置"""
    # 输入路径
    db_path: str = ""
    output_dir: str = ""
    mapping_path: str = ""
    
    # 输出路径
    results_dir: str = "artifacts/runtime/anomaly_detection_results"
    checkpoints_dir: str = "artifacts/runtime/anomaly_checkpoints"
    logs_dir: str = "artifacts/runtime/logs"
    reports_dir: str = "artifacts/runtime/reports"
    
    # 临时文件路径
    temp_dir: str = "artifacts/runtime/temp"
    
    # 验证控制
    validate_paths: bool = True
    
    def __post_init__(self):
        """验证和创建必要的目录"""
        if self.validate_paths:
            # 验证输入路径
            if self.db_path and not os.path.exists(self.db_path):
                raise ConfigurationException(f"数据库文件不存在: {self.db_path}")
            
            if self.output_dir and not os.path.exists(self.output_dir):
                raise ConfigurationException(f"输出目录不存在: {self.output_dir}")
            
            if self.mapping_path and not os.path.exists(self.mapping_path):
                raise ConfigurationException(f"映射文件不存在: {self.mapping_path}")
        
        # 创建输出目录
        for dir_path in [self.results_dir, self.checkpoints_dir, self.logs_dir, 
                        self.reports_dir, self.temp_dir]:
            Path(dir_path).mkdir(parents=True, exist_ok=True)
    
    def validate_input_paths(self):
        """手动验证输入路径"""
        if self.db_path and not os.path.exists(self.db_path):
            raise ConfigurationException(f"数据库文件不存在: {self.db_path}")
        
        if self.output_dir and not os.path.exists(self.output_dir):
            raise ConfigurationException(f"输出目录不存在: {self.output_dir}")
        
        if self.mapping_path and not os.path.exists(self.mapping_path):
            raise ConfigurationException(f"映射文件不存在: {self.mapping_path}")


@dataclass
class RecoveryConfig:
    """错误恢复配置"""
    # 重试策略
    retry_policies: Dict[str, RetryPolicy] = field(default_factory=dict)
    
    # 自动恢复设置
    auto_recovery_enabled: bool = True
    max_recovery_attempts: int = 3
    
    # 降级处理设置
    degraded_mode_enabled: bool = True
    degraded_accuracy_threshold: float = 0.8
    
    def __post_init__(self):
        """设置默认重试策略"""
        if not self.retry_policies:
            self.retry_policies = {
                "DataAccessException": RetryPolicy(max_attempts=3, backoff_factor=2),
                "DetectionLogicException": RetryPolicy(max_attempts=1, backoff_factor=1),
                "ResourceException": RetryPolicy(max_attempts=5, backoff_factor=1.5),
                "ConfigurationException": RetryPolicy(max_attempts=1, backoff_factor=1)
            }


@dataclass
class LoggingConfig:
    """日志配置"""
    # 日志级别
    log_level: str = "INFO"
    
    # 日志文件配置
    log_file: str = "anomaly_detection.log"
    max_log_size_mb: int = 100
    backup_count: int = 5
    
    # 日志格式
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"
    
    # 控制台输出
    console_output: bool = True
    console_level: str = "INFO"
    
    def __post_init__(self):
        """验证日志配置"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level not in valid_levels:
            raise ValueError(f"日志级别必须是 {valid_levels} 之一")
        if self.console_level not in valid_levels:
            raise ValueError(f"控制台日志级别必须是 {valid_levels} 之一")


@dataclass
class DetectionConfig:
    """异常检测系统主配置类
    
    包含所有检测相关的配置参数和设置。
    """
    # 基础配置
    paths: PathConfig = field(default_factory=PathConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    thresholds: DetectionThresholds = field(default_factory=DetectionThresholds)
    recovery: RecoveryConfig = field(default_factory=RecoveryConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    
    # 检测器启用配置
    enabled_detectors: List[str] = field(default_factory=lambda: [
        "ConceptMappingDetector",
        "MissingDuplicateDetector",
        "RPUStructureDetector", 
        "TimeSeriesDetector",
        "StatisticalDistributionDetector",
        "EncodingFormatDetector",
        "PerformanceDetector",
        "ConsistencyDetector"
    ])
    
    # 并行处理配置
    parallel_processing: bool = True
    
    # 增量检测配置
    incremental_detection: bool = True
    
    # 报告配置
    generate_reports: bool = True
    report_formats: List[str] = field(default_factory=lambda: ["json", "excel", "html"])
    
    # 调试配置
    debug_mode: bool = False
    verbose_output: bool = False
    
    @classmethod
    def from_file(cls, config_path: str) -> 'DetectionConfig':
        """从配置文件加载配置
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            DetectionConfig实例
            
        Raises:
            ConfigurationException: 配置文件不存在或格式错误
        """
        if not os.path.exists(config_path):
            raise ConfigurationException(f"配置文件不存在: {config_path}")
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            return cls.from_dict(config_data)
        except json.JSONDecodeError as e:
            raise ConfigurationException(f"配置文件JSON格式错误: {e}")
        except Exception as e:
            raise ConfigurationException(f"加载配置文件失败: {e}")
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'DetectionConfig':
        """从字典创建配置实例
        
        Args:
            config_dict: 配置字典
            
        Returns:
            DetectionConfig实例
        """
        # 创建子配置对象
        paths = PathConfig(**config_dict.get('paths', {}))
        performance = PerformanceConfig(**config_dict.get('performance', {}))
        thresholds = DetectionThresholds(**config_dict.get('thresholds', {}))
        
        # 处理recovery配置
        recovery_dict = config_dict.get('recovery', {})
        recovery = RecoveryConfig()
        
        # 处理retry_policies
        if 'retry_policies' in recovery_dict:
            retry_policies = {}
            for key, policy_dict in recovery_dict['retry_policies'].items():
                retry_policies[key] = RetryPolicy(**policy_dict)
            recovery.retry_policies = retry_policies
        
        # 设置其他recovery属性
        if 'auto_recovery_enabled' in recovery_dict:
            recovery.auto_recovery_enabled = recovery_dict['auto_recovery_enabled']
        if 'max_recovery_attempts' in recovery_dict:
            recovery.max_recovery_attempts = recovery_dict['max_recovery_attempts']
        if 'degraded_mode_enabled' in recovery_dict:
            recovery.degraded_mode_enabled = recovery_dict['degraded_mode_enabled']
        if 'degraded_accuracy_threshold' in recovery_dict:
            recovery.degraded_accuracy_threshold = recovery_dict['degraded_accuracy_threshold']
        
        logging = LoggingConfig(**config_dict.get('logging', {}))
        
        # 创建主配置对象
        main_config = {k: v for k, v in config_dict.items() 
                      if k not in ['paths', 'performance', 'thresholds', 'recovery', 'logging']}
        
        return cls(
            paths=paths,
            performance=performance,
            thresholds=thresholds,
            recovery=recovery,
            logging=logging,
            **main_config
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式
        
        Returns:
            配置字典
        """
        return {
            'paths': {
                'db_path': self.paths.db_path,
                'output_dir': self.paths.output_dir,
                'mapping_path': self.paths.mapping_path,
                'results_dir': self.paths.results_dir,
                'checkpoints_dir': self.paths.checkpoints_dir,
                'logs_dir': self.paths.logs_dir,
                'reports_dir': self.paths.reports_dir,
                'temp_dir': self.paths.temp_dir
            },
            'performance': {
                'max_memory_gb': self.performance.max_memory_gb,
                'min_processing_speed': self.performance.min_processing_speed,
                'max_workers': self.performance.max_workers,
                'batch_size': self.performance.batch_size,
                'checkpoint_interval': self.performance.checkpoint_interval,
                'max_checkpoints': self.performance.max_checkpoints
            },
            'thresholds': {
                'case_similarity_threshold': self.thresholds.case_similarity_threshold,
                'plural_similarity_threshold': self.thresholds.plural_similarity_threshold,
                'numerical_range_threshold': self.thresholds.numerical_range_threshold,
                'cross_domain_threshold': self.thresholds.cross_domain_threshold,
                'semantic_similarity_threshold': self.thresholds.semantic_similarity_threshold,
                'synonym_threshold': self.thresholds.synonym_threshold,
                'abbreviation_threshold': self.thresholds.abbreviation_threshold,
                'frequency_outlier_zscore': self.thresholds.frequency_outlier_zscore,
                'pmi_anomaly_threshold': self.thresholds.pmi_anomaly_threshold,
                'entropy_anomaly_threshold': self.thresholds.entropy_anomaly_threshold,
                'rpu_semantic_threshold': self.thresholds.rpu_semantic_threshold,
                'rpu_completeness_threshold': self.thresholds.rpu_completeness_threshold
            },
            'recovery': {
                'retry_policies': {k: {
                    'max_attempts': v.max_attempts,
                    'backoff_factor': v.backoff_factor,
                    'initial_delay': v.initial_delay,
                    'max_delay': v.max_delay
                } for k, v in self.recovery.retry_policies.items()},
                'auto_recovery_enabled': self.recovery.auto_recovery_enabled,
                'max_recovery_attempts': self.recovery.max_recovery_attempts,
                'degraded_mode_enabled': self.recovery.degraded_mode_enabled,
                'degraded_accuracy_threshold': self.recovery.degraded_accuracy_threshold
            },
            'logging': {
                'log_level': self.logging.log_level,
                'log_file': self.logging.log_file,
                'max_log_size_mb': self.logging.max_log_size_mb,
                'backup_count': self.logging.backup_count,
                'log_format': self.logging.log_format,
                'date_format': self.logging.date_format,
                'console_output': self.logging.console_output,
                'console_level': self.logging.console_level
            },
            'enabled_detectors': self.enabled_detectors,
            'parallel_processing': self.parallel_processing,
            'incremental_detection': self.incremental_detection,
            'generate_reports': self.generate_reports,
            'report_formats': self.report_formats,
            'debug_mode': self.debug_mode,
            'verbose_output': self.verbose_output
        }
    
    def save_to_file(self, config_path: str) -> None:
        """保存配置到文件
        
        Args:
            config_path: 配置文件路径
            
        Raises:
            ConfigurationException: 保存失败
        """
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception as e:
            raise ConfigurationException(f"保存配置文件失败: {e}")
    
    def validate(self) -> None:
        """验证配置的有效性
        
        Raises:
            ConfigurationException: 配置无效
        """
        # 验证检测器名称
        valid_detectors = {
            "ConceptMappingDetector",
            "MissingDuplicateDetector",
            "RPUStructureDetector", 
            "TimeSeriesDetector",
            "StatisticalDistributionDetector",
            "EncodingFormatDetector",
            "PerformanceDetector",
            "ConsistencyDetector"
        }
        
        invalid_detectors = set(self.enabled_detectors) - valid_detectors
        if invalid_detectors:
            raise ConfigurationException(f"无效的检测器名称: {invalid_detectors}")
        
        # 验证报告格式
        valid_formats = {"json", "excel", "html", "csv"}
        invalid_formats = set(self.report_formats) - valid_formats
        if invalid_formats:
            raise ConfigurationException(f"无效的报告格式: {invalid_formats}")
        
        # 验证子配置
        try:
            self.paths.__post_init__()
            self.performance.__post_init__()
            self.thresholds.__post_init__()
        except Exception as e:
            raise ConfigurationException(f"配置验证失败: {e}")
    
    def get_config_hash(self) -> str:
        """获取配置的哈希值，用于检测配置变更
        
        Returns:
            配置哈希值
        """
        import hashlib
        config_str = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.md5(config_str.encode()).hexdigest()


def create_default_config(
    db_path: str = "",
    output_dir: str = "",
    mapping_path: str = ""
) -> DetectionConfig:
    """创建默认配置
    
    Args:
        db_path: 数据库路径
        output_dir: 输出目录
        mapping_path: 映射文件路径
        
    Returns:
        默认配置实例
    """
    paths = PathConfig(
        db_path=db_path,
        output_dir=output_dir,
        mapping_path=mapping_path
    )
    
    return DetectionConfig(paths=paths)
