# RIPER-Core 创新结果异常检测系统

## 概述

创新结果异常检测系统是RIPER-Core创新计算系统的质量保证组件，用于检验已生成的计算结果中的异常情况。系统识别重复检测错误、概念映射异常和数据一致性问题，确保创新计算结果的准确性和可靠性。

## 功能特性

- **多层次异常检测**: 支持概念映射、RPU结构、时间序列、统计分布等多种异常检测
- **大规模数据处理**: 支持处理超过1000个分片文件和4000万条记录
- **流式处理架构**: 内存高效的数据处理，支持增量检测和断点续传
- **智能修复建议**: 为检测到的异常提供具体的修复操作建议
- **多格式报告**: 支持JSON、Excel、HTML等多种格式的检测报告

## 项目结构

```
anomaly_detection/
├── __init__.py                 # 包初始化文件
├── README.md                   # 项目说明文档
├── cli.py                      # 命令行接口
│
├── core/                       # 核心模块
│   ├── __init__.py
│   ├── config.py              # 配置管理系统
│   ├── data_models.py         # 核心数据模型
│   ├── exceptions.py          # 异常类定义
│   ├── logging.py             # 日志管理系统
│   └── error_recovery.py      # 错误恢复管理
│
├── data_access/               # 数据访问层
│   ├── __init__.py
│   ├── manager.py             # 数据访问管理器
│   ├── sqlite_manager.py      # SQLite数据库管理
│   ├── shard_file_manager.py  # 分片文件管理
│   └── mapping_file_manager.py # 映射文件管理
│
├── engine/                    # 检测引擎层
│   ├── __init__.py
│   └── detection_engine.py    # 主检测引擎
│
├── detectors/                 # 检测器模块 (待实现)
│   └── (将在后续任务中实现)
│
└── reports/                   # 报告生成模块 (待实现)
    └── (将在后续任务中实现)
```

## 快速开始

### 1. 环境要求

- Python 3.12+
- 依赖包: sqlite3, json, pathlib, datetime, typing

### 2. 基本使用

#### 命令行方式

```bash
# 生成默认配置文件
python -m anomaly_detection.cli --generate-config config.json

# 使用配置文件运行检测
python -m anomaly_detection.cli --config config.json

# 直接指定数据源运行检测
python -m anomaly_detection.cli \
    --db-path /path/to/database.db \
    --output-dir /path/to/output \
    --mapping-path /path/to/core_mapping.json
```

#### 编程方式

```python
from anomaly_detection import DetectionConfig, AnomalyDetectionEngine

# 创建配置
config = DetectionConfig.from_file('config.json')

# 运行检测
with AnomalyDetectionEngine(config) as engine:
    session = engine.run_detection()
    results = engine.get_detection_results()
    summary = engine.get_detection_summary()
```

### 3. 配置文件示例

```json
{
  "paths": {
    "db_path": "/path/to/database.db",
    "output_dir": "/path/to/output",
    "mapping_path": "/path/to/core_mapping.json",
    "results_dir": "anomaly_detection_results"
  },
  "performance": {
    "max_memory_gb": 4.0,
    "min_processing_speed": 1000,
    "max_workers": 8,
    "batch_size": 1000
  },
  "enabled_detectors": [
    "ConceptMappingDetector",
    "RPUStructureDetector",
    "TimeSeriesDetector",
    "StatisticalDistributionDetector"
  ],
  "parallel_processing": true,
  "report_formats": ["json", "excel"]
}
```

## 核心组件

### 1. 配置管理系统 (core/config.py)

提供灵活的配置管理，支持:
- JSON配置文件加载和保存
- 命令行参数覆盖
- 配置验证和默认值设置
- 性能参数和检测阈值配置

### 2. 数据访问层 (data_access/)

统一的数据访问接口，支持:
- SQLite数据库的流式读取
- 分片文件的批量处理
- 概念映射文件的加载和验证
- 跨数据源的一致性检查

### 3. 异常检测引擎 (engine/detection_engine.py)

核心检测协调器，提供:
- 多检测器的统一调度
- 检测流程的状态管理
- 结果聚合和分析
- 检查点和恢复机制

### 4. 错误恢复系统 (core/error_recovery.py)

健壮的错误处理，包括:
- 自动重试机制
- 检查点创建和恢复
- 降级模式处理
- 资源监控和限制

## 异常检测类型

### 已实现的基础检测
- **数据一致性验证**: 检查数据库、分片文件和映射文件之间的一致性
- **配置验证**: 验证系统配置的有效性和完整性

### 计划实现的检测器 (后续任务)
- **概念映射检测**: 大小写不一致、单复数冲突、数值范围异常等
- **RPU结构检测**: 语义合理性、完整性、一致性检测
- **时间序列检测**: 异常峰谷值、时间因果性验证
- **统计分布检测**: 频率离群值、PMI异常、熵值异常
- **格式编码检测**: 字符编码异常、数据格式错误
- **性能异常检测**: 内存使用、处理时间异常
- **跨文件一致性检测**: ID引用、重叠数据处理检查

## 测试

运行基础功能测试:

```bash
cd 论文创新词汇统计7
python test_anomaly_detection_basic.py
```

测试覆盖:
- 模块导入验证
- 数据模型功能测试
- 配置系统测试
- 日志系统测试
- 异常处理测试
- 命令行接口测试
- 检测引擎基础功能

## 开发指南

### 添加新的检测器

1. 在 `detectors/` 目录下创建检测器类
2. 继承 `AnomalyDetector` 基类
3. 实现 `detect()` 方法
4. 在 `detection_engine.py` 中注册检测器

### 扩展数据模型

1. 在 `core/data_models.py` 中添加新的数据类
2. 使用 `@dataclass` 装饰器
3. 添加必要的验证逻辑
4. 更新相关的类型提示

### 配置新的检测参数

1. 在 `core/config.py` 中的相应配置类中添加参数
2. 设置合理的默认值
3. 添加验证逻辑
4. 更新配置文档

## 性能考虑

### 内存优化
- 使用生成器进行流式数据处理
- 实现检查点机制避免重复计算
- 配置内存使用限制和监控

### 处理速度
- 支持并行处理提高效率
- 批量处理减少I/O开销
- 智能缓存减少重复访问

### 可扩展性
- 模块化设计便于功能扩展
- 插件式检测器架构
- 配置驱动的功能启用

## 注意事项

### 经验值说明
系统中使用的一些数值参数是基于经验设定的，包括:
- `batch_size=1000`: 批处理大小，可根据内存情况调整
- `max_memory_gb=4.0`: 内存限制，可根据系统配置调整
- `checkpoint_interval=10000`: 检查点间隔，可根据处理速度调整
- `numerical_range_threshold=100.0`: 数值范围阈值，可根据数据特征调整

这些参数可以通过配置文件进行调整以适应不同的使用场景。

### 数据源要求
- SQLite数据库需要包含RPU相关表结构
- 分片文件支持JSONL、JSON、CSV格式
- 概念映射文件需要是有效的JSON格式

## 许可证

本项目是RIPER-Core创新计算系统的一部分，遵循项目整体的许可证协议。

## 贡献

欢迎提交问题报告和功能建议。在提交代码前，请确保:
1. 遵循项目的编码规范
2. 添加适当的测试用例
3. 更新相关文档
4. 通过所有现有测试