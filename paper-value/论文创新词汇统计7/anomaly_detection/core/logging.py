"""
日志管理系统

提供统一的日志记录功能，支持文件输出、控制台输出和日志轮转。
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional
from .config import LoggingConfig
from .exceptions import ConfigurationException


class AnomalyDetectionLogger:
    """异常检测系统专用日志器
    
    提供统一的日志记录接口，支持多种输出方式和日志级别。
    """
    
    def __init__(self, name: str, config: LoggingConfig):
        """初始化日志器
        
        Args:
            name: 日志器名称
            config: 日志配置
        """
        self.name = name
        self.config = config
        self.logger = logging.getLogger(name)
        self._setup_logger()
    
    def _setup_logger(self) -> None:
        """设置日志器配置"""
        # 清除现有处理器
        self.logger.handlers.clear()
        
        # 设置日志级别
        self.logger.setLevel(getattr(logging, self.config.log_level))
        
        # 创建格式器
        formatter = logging.Formatter(
            self.config.log_format,
            datefmt=self.config.date_format
        )
        
        # 添加文件处理器
        if self.config.log_file:
            self._add_file_handler(formatter)
        
        # 添加控制台处理器
        if self.config.console_output:
            self._add_console_handler(formatter)
    
    def _add_file_handler(self, formatter: logging.Formatter) -> None:
        """添加文件处理器"""
        try:
            # 确保日志目录存在
            log_path = Path(self.config.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 创建轮转文件处理器
            file_handler = logging.handlers.RotatingFileHandler(
                self.config.log_file,
                maxBytes=self.config.max_log_size_mb * 1024 * 1024,
                backupCount=self.config.backup_count,
                encoding='utf-8'
            )
            
            file_handler.setFormatter(formatter)
            file_handler.setLevel(getattr(logging, self.config.log_level))
            self.logger.addHandler(file_handler)
            
        except Exception as e:
            raise ConfigurationException(f"创建文件日志处理器失败: {e}")
    
    def _add_console_handler(self, formatter: logging.Formatter) -> None:
        """添加控制台处理器"""
        try:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            console_handler.setLevel(getattr(logging, self.config.console_level))
            self.logger.addHandler(console_handler)
            
        except Exception as e:
            raise ConfigurationException(f"创建控制台日志处理器失败: {e}")
    
    def debug(self, message: str, **kwargs) -> None:
        """记录调试信息"""
        self.logger.debug(message, **kwargs)
    
    def info(self, message: str, **kwargs) -> None:
        """记录一般信息"""
        self.logger.info(message, **kwargs)
    
    def warning(self, message: str, **kwargs) -> None:
        """记录警告信息"""
        self.logger.warning(message, **kwargs)
    
    def error(self, message: str, **kwargs) -> None:
        """记录错误信息"""
        self.logger.error(message, **kwargs)
    
    def critical(self, message: str, **kwargs) -> None:
        """记录严重错误信息"""
        self.logger.critical(message, **kwargs)
    
    def exception(self, message: str, **kwargs) -> None:
        """记录异常信息（包含堆栈跟踪）"""
        self.logger.exception(message, **kwargs)


class LoggerManager:
    """日志器管理器
    
    管理系统中所有的日志器实例，确保配置一致性。
    """
    
    _instance: Optional['LoggerManager'] = None
    _loggers: dict = {}
    _config: Optional[LoggingConfig] = None
    
    def __new__(cls) -> 'LoggerManager':
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def initialize(cls, config: LoggingConfig) -> None:
        """初始化日志管理器
        
        Args:
            config: 日志配置
        """
        cls._config = config
        cls._loggers.clear()
    
    @classmethod
    def get_logger(cls, name: str) -> AnomalyDetectionLogger:
        """获取日志器实例
        
        Args:
            name: 日志器名称
            
        Returns:
            日志器实例
            
        Raises:
            ConfigurationException: 日志管理器未初始化
        """
        if cls._config is None:
            raise ConfigurationException("日志管理器未初始化，请先调用 initialize() 方法")
        
        if name not in cls._loggers:
            cls._loggers[name] = AnomalyDetectionLogger(name, cls._config)
        
        return cls._loggers[name]
    
    @classmethod
    def shutdown(cls) -> None:
        """关闭所有日志器"""
        for logger in cls._loggers.values():
            for handler in logger.logger.handlers:
                handler.close()
        cls._loggers.clear()


def get_logger(name: str) -> AnomalyDetectionLogger:
    """获取日志器的便捷函数
    
    Args:
        name: 日志器名称
        
    Returns:
        日志器实例
    """
    return LoggerManager.get_logger(name)


def setup_logging(config: LoggingConfig) -> None:
    """设置系统日志配置
    
    Args:
        config: 日志配置
    """
    LoggerManager.initialize(config)


def shutdown_logging() -> None:
    """关闭日志系统"""
    LoggerManager.shutdown()