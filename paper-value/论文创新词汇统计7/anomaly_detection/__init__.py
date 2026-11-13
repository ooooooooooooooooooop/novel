"""
创新结果异常检测系统

RIPER-Core创新计算系统的质量保证组件，用于检验已生成的计算结果中的异常情况。
系统识别重复检测错误、概念映射异常和数据一致性问题，确保创新计算结果的准确性和可靠性。
"""

__version__ = "1.0.0"
__author__ = "RIPER-Core Team"

from .core.exceptions import (
    AnomalyDetectionException,
    DataAccessException,
    DetectionLogicException,
    ResourceException,
    ConfigurationException
)

from .core.data_models import (
    RPURecord,
    ConceptMapping,
    DetectionResult,
    AnomalySeverity,
    ShardMetadata
)

from .core.config import DetectionConfig
from .engine.detection_engine import AnomalyDetectionEngine
from .data_access.manager import DataAccessManager

__all__ = [
    # 异常类
    'AnomalyDetectionException',
    'DataAccessException', 
    'DetectionLogicException',
    'ResourceException',
    'ConfigurationException',
    
    # 数据模型
    'RPURecord',
    'ConceptMapping',
    'DetectionResult',
    'AnomalySeverity',
    'ShardMetadata',
    
    # 核心组件
    'DetectionConfig',
    'AnomalyDetectionEngine',
    'DataAccessManager'
]