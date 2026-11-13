# -*- coding: utf-8 -*-
"""
Configuration Management System for Innovation Engine Optimization
配置管理系统 - 创新引擎优化

This module provides comprehensive configuration loading, validation, and management
for the Innovation Engine optimization system.

主要功能:
1. 配置模式定义和验证
2. 参数范围检查和错误处理
3. 配置文件加载和保存
4. 运行时配置管理
"""

import os
import json
import logging
from typing import Dict, Any, Optional, Union, List
from pathlib import Path
from dataclasses import dataclass, asdict, field
import yaml

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """配置相关错误的基础异常类"""
    pass


class ValidationError(ConfigurationError):
    """参数验证错误"""
    pass


class ConfigurationNotFoundError(ConfigurationError):
    """配置文件未找到错误"""
    pass


@dataclass
class CacheConfig:
    """缓存配置参数"""
    # YearCache 配置
    max_log_cache_size: int = 10000  # 这是经验值 - 数学对数缓存最大条目数
    max_pmi_cache_size: int = 5000   # 这是经验值 - PMI计算缓存最大条目数
    enable_cache: bool = True        # 是否启用缓存优化
    
    # 缓存内存估算参数 (这些是经验值)
    log_entry_size_bytes: int = 64   # 每个对数缓存条目的估算字节数
    pmi_entry_base_size_bytes: int = 128  # PMI缓存条目基础字节数
    
    def validate(self) -> List[str]:
        """验证缓存配置参数"""
        errors = []
        
        if self.max_log_cache_size <= 0:
            errors.append("max_log_cache_size 必须大于 0")
        elif self.max_log_cache_size > 1_000_000:
            errors.append("max_log_cache_size 不应超过 1,000,000 (内存使用过大)")
            
        if self.max_pmi_cache_size <= 0:
            errors.append("max_pmi_cache_size 必须大于 0")
        elif self.max_pmi_cache_size > 100_000:
            errors.append("max_pmi_cache_size 不应超过 100,000 (内存使用过大)")
            
        if self.log_entry_size_bytes <= 0:
            errors.append("log_entry_size_bytes 必须大于 0")
            
        if self.pmi_entry_base_size_bytes <= 0:
            errors.append("pmi_entry_base_size_bytes 必须大于 0")
            
        return errors


@dataclass
class ModifierFilterConfig:
    """修饰符过滤配置参数"""
    enable_modifier_filter: bool = True      # 是否启用修饰符过滤
    percentile_threshold: float = 99.0       # 这是经验值 - 百分位阈值 (默认99%)
    min_samples_for_filtering: int = 1000    # 这是经验值 - 启用过滤的最小样本数
    
    def validate(self) -> List[str]:
        """验证修饰符过滤配置参数"""
        errors = []
        
        if not (0.0 <= self.percentile_threshold <= 100.0):
            errors.append("percentile_threshold 必须在 0.0 到 100.0 之间")
        elif self.percentile_threshold < 50.0:
            errors.append("percentile_threshold 不应小于 50.0 (可能过度过滤)")
        elif self.percentile_threshold > 99.9:
            errors.append("percentile_threshold 不应超过 99.9 (过滤效果微弱)")
            
        if self.min_samples_for_filtering <= 0:
            errors.append("min_samples_for_filtering 必须大于 0")
        elif self.min_samples_for_filtering > 100_000:
            errors.append("min_samples_for_filtering 过大，可能导致过滤启动过晚")
            
        return errors


@dataclass
class AlgorithmConfig:
    """算法核心参数配置"""
    synergy_min_support: int = 2             # 这是经验值 - 协同计算最小支持度
    prune_threshold: int = 10_000_000        # 这是经验值 - 字典修剪阈值
    top_k_signals: int = 3                   # 这是经验值 - Top-K信号计算参数
    core_stability_smoothing: int = 1000     # 这是经验值 - 核心概念稳定性平滑参数
    object_coverage_policy: str = "soft_weight"  # off | hard_filter | soft_weight
    object_coverage_threshold: float = 0.2
    object_coverage_soft_floor: float = 0.25
    pair_normalization_mode: str = "lower_compact"  # raw | lower_compact
    pca_feature_source: str = "phase1_snapshot"  # phase1_snapshot | phase2_recompute
    pca_bias_diagnostic_enabled: bool = True
    pca_bias_min_group_size: int = 500
    pca_bias_alert_shift_pp: float = 8.0
    pca_bias_top_groups: int = 20
    synergy_granularity_mode: str = "task_object"  # task_object | object_only | hybrid
    synergy_blend_object_weight: float = 0.5
    synergy_granularity_ab_enabled: bool = True
    synergy_granularity_ab_top_share: float = 0.01
    
    def validate(self) -> List[str]:
        """验证算法配置参数"""
        errors = []
        
        if self.synergy_min_support < 1:
            errors.append("synergy_min_support 必须至少为 1")
        elif self.synergy_min_support > 10:
            errors.append("synergy_min_support 过大可能导致协同信号过少")
            
        if self.prune_threshold <= 0:
            errors.append("prune_threshold 必须大于 0")
        elif self.prune_threshold < 1_000_000:
            errors.append("prune_threshold 过小可能导致频繁修剪，影响性能")
            
        if self.top_k_signals < 1:
            errors.append("top_k_signals 必须至少为 1")
        elif self.top_k_signals > 10:
            errors.append("top_k_signals 过大可能稀释信号强度")
            
        if self.core_stability_smoothing <= 0:
            errors.append("core_stability_smoothing 必须大于 0")

        if self.object_coverage_policy not in {"off", "hard_filter", "soft_weight"}:
            errors.append("object_coverage_policy 必须是 off|hard_filter|soft_weight")
        if not (0.0 <= self.object_coverage_threshold <= 1.0):
            errors.append("object_coverage_threshold 必须在 0.0 到 1.0 之间")
        if not (0.0 <= self.object_coverage_soft_floor <= 1.0):
            errors.append("object_coverage_soft_floor 必须在 0.0 到 1.0 之间")

        if self.pair_normalization_mode not in {"raw", "lower_compact"}:
            errors.append("pair_normalization_mode 必须是 raw|lower_compact")
        if self.pca_feature_source not in {"phase1_snapshot", "phase2_recompute"}:
            errors.append("pca_feature_source 必须是 phase1_snapshot|phase2_recompute")
        if self.pca_bias_min_group_size < 10:
            errors.append("pca_bias_min_group_size 不应小于 10")
        if self.pca_bias_alert_shift_pp < 0.0:
            errors.append("pca_bias_alert_shift_pp 必须大于等于 0")
        if self.pca_bias_top_groups < 1:
            errors.append("pca_bias_top_groups 必须大于等于 1")

        if self.synergy_granularity_mode not in {"task_object", "object_only", "hybrid"}:
            errors.append("synergy_granularity_mode 必须是 task_object|object_only|hybrid")
        if not (0.0 <= self.synergy_blend_object_weight <= 1.0):
            errors.append("synergy_blend_object_weight 必须在 0.0 到 1.0 之间")
        if not (0.0 < self.synergy_granularity_ab_top_share <= 0.5):
            errors.append("synergy_granularity_ab_top_share 必须在 (0, 0.5] 区间")
            
        return errors


@dataclass
class PerformanceConfig:
    """性能监控配置参数"""
    enable_performance_metrics: bool = True   # 是否启用性能监控
    memory_sample_interval: int = 10          # 这是经验值 - 内存采样间隔(年)
    cache_report_interval: int = 5            # 这是经验值 - 缓存报告间隔(年)
    modifier_filter_report_interval: int = 10 # 这是经验值 - 修饰符过滤报告间隔(年)
    high_performance_threshold: float = 100.0 # 这是经验值 - 高性能处理阈值(论文/秒)
    
    def validate(self) -> List[str]:
        """验证性能监控配置参数"""
        errors = []
        
        if self.memory_sample_interval <= 0:
            errors.append("memory_sample_interval 必须大于 0")
        elif self.memory_sample_interval > 100:
            errors.append("memory_sample_interval 过大可能导致内存监控不及时")
            
        if self.cache_report_interval <= 0:
            errors.append("cache_report_interval 必须大于 0")
            
        if self.modifier_filter_report_interval <= 0:
            errors.append("modifier_filter_report_interval 必须大于 0")
            
        if self.high_performance_threshold <= 0:
            errors.append("high_performance_threshold 必须大于 0")
            
        return errors


@dataclass
class LoggingConfig:
    """日志配置参数"""
    level: str = "INFO"                      # 日志级别
    format: str = "%(asctime)s - %(levelname)s - %(message)s"  # 日志格式
    file_path: Optional[str] = "innovation_calculation.log"     # 日志文件路径
    enable_console: bool = True              # 是否启用控制台输出
    enable_file: bool = True                 # 是否启用文件输出
    encoding: str = "utf-8"                  # 文件编码
    
    def validate(self) -> List[str]:
        """验证日志配置参数"""
        errors = []
        
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.level.upper() not in valid_levels:
            errors.append(f"level 必须是以下之一: {valid_levels}")
            
        if self.file_path and not self.enable_file:
            errors.append("如果指定了 file_path，应启用 enable_file")
            
        if not self.enable_console and not self.enable_file:
            errors.append("至少需要启用控制台输出或文件输出之一")
            
        return errors


@dataclass
class InnovationEngineConfig:
    """创新引擎完整配置"""
    cache: CacheConfig = field(default_factory=CacheConfig)
    modifier_filter: ModifierFilterConfig = field(default_factory=ModifierFilterConfig)
    algorithm: AlgorithmConfig = field(default_factory=AlgorithmConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    
    # 输入输出配置
    input_path: str = r"test_rpus.csv"
    output_path: str = "innovation_signals.jsonl"
    performance_report_path: str = "performance_metrics.json"
    
    def validate(self) -> Dict[str, List[str]]:
        """验证所有配置参数"""
        validation_results = {}
        
        # 验证各个配置模块
        cache_errors = self.cache.validate()
        if cache_errors:
            validation_results["cache"] = cache_errors
            
        modifier_filter_errors = self.modifier_filter.validate()
        if modifier_filter_errors:
            validation_results["modifier_filter"] = modifier_filter_errors
            
        algorithm_errors = self.algorithm.validate()
        if algorithm_errors:
            validation_results["algorithm"] = algorithm_errors
            
        performance_errors = self.performance.validate()
        if performance_errors:
            validation_results["performance"] = performance_errors
            
        logging_errors = self.logging.validate()
        if logging_errors:
            validation_results["logging"] = logging_errors
            
        # 验证路径配置
        path_errors = []
        if not self.input_path:
            path_errors.append("input_path 不能为空")
        if not self.output_path:
            path_errors.append("output_path 不能为空")
        if not self.performance_report_path:
            path_errors.append("performance_report_path 不能为空")
            
        if path_errors:
            validation_results["paths"] = path_errors
            
        return validation_results
    
    def is_valid(self) -> bool:
        """检查配置是否有效"""
        return len(self.validate()) == 0


class ConfigManager:
    """配置管理器 - 负责加载、验证和管理配置"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置管理器
        
        Args:
            config_path: 配置文件路径，如果为None则使用默认配置
        """
        self.config_path = config_path
        self.config: Optional[InnovationEngineConfig] = None
        
    def load_config(self, config_path: Optional[str] = None) -> InnovationEngineConfig:
        """
        加载配置文件
        
        Args:
            config_path: 配置文件路径，如果为None则使用初始化时的路径
            
        Returns:
            InnovationEngineConfig: 加载的配置对象
            
        Raises:
            ConfigurationNotFoundError: 配置文件不存在
            ValidationError: 配置验证失败
        """
        if config_path:
            self.config_path = config_path
            
        if not self.config_path:
            # 使用默认配置
            logger.info("未指定配置文件，使用默认配置")
            self.config = InnovationEngineConfig()
        else:
            # 加载配置文件
            config_file = Path(self.config_path)
            if not config_file.exists():
                raise ConfigurationNotFoundError(f"配置文件不存在: {self.config_path}")
                
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    if config_file.suffix.lower() in ['.yaml', '.yml']:
                        config_data = yaml.safe_load(f)
                    else:
                        config_data = json.load(f)
                        
                self.config = self._dict_to_config(config_data)
                logger.info(f"成功加载配置文件: {self.config_path}")
                
            except (json.JSONDecodeError, yaml.YAMLError) as e:
                raise ValidationError(f"配置文件格式错误: {e}")
            except Exception as e:
                raise ConfigurationError(f"加载配置文件失败: {e}")
        
        # 验证配置
        self._validate_config()
        return self.config
    
    def save_config(self, config_path: Optional[str] = None, format: str = "json") -> None:
        """
        保存配置到文件
        
        Args:
            config_path: 保存路径，如果为None则使用当前配置路径
            format: 保存格式 ("json" 或 "yaml")
        """
        if not self.config:
            raise ConfigurationError("没有可保存的配置")
            
        save_path = config_path or self.config_path
        if not save_path:
            raise ConfigurationError("未指定保存路径")
            
        config_dict = asdict(self.config)
        
        try:
            with open(save_path, 'w', encoding='utf-8') as f:
                if format.lower() == "yaml":
                    yaml.dump(config_dict, f, default_flow_style=False, 
                             allow_unicode=True, indent=2)
                else:
                    json.dump(config_dict, f, ensure_ascii=False, indent=2)
                    
            logger.info(f"配置已保存到: {save_path}")
            
        except Exception as e:
            raise ConfigurationError(f"保存配置文件失败: {e}")
    
    def get_config(self) -> InnovationEngineConfig:
        """获取当前配置"""
        if not self.config:
            raise ConfigurationError("配置未加载，请先调用 load_config()")
        return self.config
    
    def update_config(self, **kwargs) -> None:
        """
        更新配置参数
        
        Args:
            **kwargs: 要更新的配置参数
        """
        if not self.config:
            raise ConfigurationError("配置未加载，请先调用 load_config()")
            
        # 更新配置
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
            else:
                # 尝试更新子配置
                updated = False
                for attr_name in ['cache', 'modifier_filter', 'algorithm', 'performance', 'logging']:
                    attr = getattr(self.config, attr_name)
                    if hasattr(attr, key):
                        setattr(attr, key, value)
                        updated = True
                        break
                        
                if not updated:
                    logger.warning(f"未知的配置参数: {key}")
        
        # 重新验证配置
        self._validate_config()
    
    def _dict_to_config(self, config_data: Dict[str, Any]) -> InnovationEngineConfig:
        """将字典转换为配置对象"""
        try:
            # 提取各个配置模块
            cache_data = config_data.get('cache', {})
            modifier_filter_data = config_data.get('modifier_filter', {})
            algorithm_data = config_data.get('algorithm', {})
            performance_data = config_data.get('performance', {})
            logging_data = config_data.get('logging', {})
            
            # 创建配置对象
            config = InnovationEngineConfig(
                cache=CacheConfig(**cache_data),
                modifier_filter=ModifierFilterConfig(**modifier_filter_data),
                algorithm=AlgorithmConfig(**algorithm_data),
                performance=PerformanceConfig(**performance_data),
                logging=LoggingConfig(**logging_data),
                input_path=config_data.get('input_path', 'test_rpus.csv'),
                output_path=config_data.get('output_path', 'innovation_signals.jsonl'),
                performance_report_path=config_data.get('performance_report_path', 'performance_metrics.json')
            )
            
            return config
            
        except TypeError as e:
            raise ValidationError(f"配置参数类型错误: {e}")
        except Exception as e:
            raise ValidationError(f"配置转换失败: {e}")
    
    def _validate_config(self) -> None:
        """验证配置并抛出详细错误"""
        if not self.config:
            return
            
        validation_results = self.config.validate()
        if validation_results:
            error_messages = []
            for section, errors in validation_results.items():
                for error in errors:
                    error_messages.append(f"[{section}] {error}")
            
            raise ValidationError(
                f"配置验证失败:\n" + "\n".join(error_messages)
            )
    
    def create_default_config_file(self, file_path: str, format: str = "json") -> None:
        """
        创建默认配置文件
        
        Args:
            file_path: 配置文件路径
            format: 文件格式 ("json" 或 "yaml")
        """
        default_config = InnovationEngineConfig()
        
        # 临时设置配置以便保存
        original_config = self.config
        original_path = self.config_path
        
        self.config = default_config
        self.config_path = file_path
        
        try:
            self.save_config(format=format)
            logger.info(f"默认配置文件已创建: {file_path}")
        finally:
            # 恢复原始配置
            self.config = original_config
            self.config_path = original_path


def load_config_from_args(args) -> InnovationEngineConfig:
    """
    从命令行参数创建配置对象
    
    Args:
        args: argparse解析的参数对象
        
    Returns:
        InnovationEngineConfig: 配置对象
    """
    config = InnovationEngineConfig()
    
    # 更新基础路径配置
    if hasattr(args, 'input_path'):
        config.input_path = args.input_path
    if hasattr(args, 'output_path'):
        config.output_path = args.output_path
    if hasattr(args, 'performance_report_path'):
        config.performance_report_path = args.performance_report_path
    
    # 更新缓存配置
    if hasattr(args, 'disable_cache'):
        config.cache.enable_cache = not args.disable_cache
    
    # 更新修饰符过滤配置
    if hasattr(args, 'disable_modifier_filter'):
        config.modifier_filter.enable_modifier_filter = not args.disable_modifier_filter
    if hasattr(args, 'modifier_filter_percentile'):
        config.modifier_filter.percentile_threshold = args.modifier_filter_percentile
    
    # 更新性能监控配置
    if hasattr(args, 'disable_performance_metrics'):
        config.performance.enable_performance_metrics = not args.disable_performance_metrics
    if hasattr(args, 'memory_sample_interval'):
        config.performance.memory_sample_interval = args.memory_sample_interval
    
    return config


# 配置验证辅助函数
def validate_config_file(config_path: str) -> Dict[str, List[str]]:
    """
    验证配置文件而不加载到内存
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        Dict[str, List[str]]: 验证结果，空字典表示验证通过
    """
    try:
        manager = ConfigManager()
        config = manager.load_config(config_path)
        return config.validate()
    except Exception as e:
        return {"file_error": [str(e)]}


if __name__ == "__main__":
    # 示例用法
    manager = ConfigManager()
    
    # 创建默认配置文件
    manager.create_default_config_file("default_config.json")
    manager.create_default_config_file("default_config.yaml", format="yaml")
    
    # 加载和验证配置
    try:
        config = manager.load_config("default_config.json")
        print("配置加载成功!")
        print(f"缓存启用: {config.cache.enable_cache}")
        print(f"修饰符过滤阈值: {config.modifier_filter.percentile_threshold}")
    except Exception as e:
        print(f"配置加载失败: {e}")
