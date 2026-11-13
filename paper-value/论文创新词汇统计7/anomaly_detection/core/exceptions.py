"""
异常检测系统的异常类定义

定义了系统中使用的所有异常类型，采用分层异常处理策略。
"""

from typing import Optional, Dict, Any


class AnomalyDetectionException(Exception):
    """异常检测系统基础异常类
    
    所有异常检测系统相关异常的基类，提供统一的异常处理接口。
    """
    
    def __init__(self, message: str, error_code: Optional[str] = None, 
                 context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.context = context or {}
    
    def __str__(self) -> str:
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message


class DataAccessException(AnomalyDetectionException):
    """数据访问异常
    
    当访问文件、数据库或其他数据源时发生错误时抛出。
    包括：文件不存在、数据库连接失败、权限问题等。
    """
    
    def __init__(self, message: str, data_source: Optional[str] = None, 
                 operation: Optional[str] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.data_source = data_source
        self.operation = operation


class DetectionLogicException(AnomalyDetectionException):
    """检测逻辑异常
    
    当检测算法执行过程中发生错误时抛出。
    包括：算法错误、内存不足、计算超时等。
    """
    
    def __init__(self, message: str, detector_name: Optional[str] = None,
                 algorithm: Optional[str] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.detector_name = detector_name
        self.algorithm = algorithm


class ResourceException(AnomalyDetectionException):
    """系统资源异常
    
    当系统资源不足或访问失败时抛出。
    包括：磁盘空间不足、网络连接问题、内存不足等。
    """
    
    def __init__(self, message: str, resource_type: Optional[str] = None,
                 required_amount: Optional[str] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.resource_type = resource_type
        self.required_amount = required_amount


class ConfigurationException(AnomalyDetectionException):
    """配置异常
    
    当配置参数错误或无效时抛出。
    包括：参数错误、路径无效、格式不正确等。
    """
    
    def __init__(self, message: str, config_key: Optional[str] = None,
                 config_value: Optional[str] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.config_key = config_key
        self.config_value = config_value


class CheckpointException(AnomalyDetectionException):
    """检查点异常
    
    当检查点创建、保存或恢复过程中发生错误时抛出。
    """
    
    def __init__(self, message: str, checkpoint_id: Optional[str] = None,
                 operation: Optional[str] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.checkpoint_id = checkpoint_id
        self.operation = operation


class ValidationException(AnomalyDetectionException):
    """验证异常
    
    当数据验证失败时抛出。
    """
    
    def __init__(self, message: str, validation_type: Optional[str] = None,
                 failed_value: Optional[Any] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.validation_type = validation_type
        self.failed_value = failed_value


class ParallelProcessingException(AnomalyDetectionException):
    """并行处理异常
    
    当并行处理过程中发生错误时抛出。
    """
    
    def __init__(self, message: str, process_id: Optional[str] = None,
                 worker_count: Optional[int] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.process_id = process_id
        self.worker_count = worker_count