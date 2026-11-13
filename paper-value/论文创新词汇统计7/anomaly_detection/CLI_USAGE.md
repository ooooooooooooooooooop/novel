# RIPER-Core 异常检测系统 CLI 使用指南

## 概述

RIPER-Core 异常检测系统提供了功能丰富的命令行界面，支持多种检测模式、配置选项和输出格式。

## 基本用法

### 快速开始

```bash
# 使用基本参数运行检测
python -m anomaly_detection.cli --db-path data.db --output-dir output_7_deberta

# 使用配置文件运行
python -m anomaly_detection.cli --config detection_config.json

# 生成默认配置文件
python -m anomaly_detection.cli --generate-config my_config.json
```

### 配置文件

推荐使用配置文件来管理复杂的检测设置：

```bash
# 生成默认配置
python -m anomaly_detection.cli --generate-config config.json

# 验证配置文件
python -m anomaly_detection.cli --validate-config config.json

# 使用配置文件运行
python -m anomaly_detection.cli --config config.json
```

## 检测模式

### 1. 标准检测模式

```bash
# 串行处理（默认）
python -m anomaly_detection.cli --config config.json --serial

# 并行处理
python -m anomaly_detection.cli --config config.json --parallel --max-workers 4

# 指定检测器
python -m anomaly_detection.cli --config config.json \
  --detectors ConceptMappingDetector RPUStructureDetector
```

### 2. 交互式模式

```bash
# 启动交互式模式
python -m anomaly_detection.cli --config config.json --interactive
```

交互式命令：
- `start` - 开始新的检测会话
- `status` - 显示当前状态
- `results` - 显示检测结果摘要
- `checkpoint [描述]` - 创建检查点
- `checkpoints` - 列出检查点
- `stop` - 停止当前会话
- `help` - 显示帮助
- `quit` - 退出

### 3. 监控模式

```bash
# 监控目录变化并自动检测
python -m anomaly_detection.cli --config config.json \
  --monitor --watch-dir /path/to/data --watch-interval 60
```

### 4. 基准测试模式

```bash
# 运行性能基准测试
python -m anomaly_detection.cli --config config.json \
  --benchmark --record-count 1000
```

## 会话管理

### 检查点操作

```bash
# 列出所有检查点
python -m anomaly_detection.cli --config config.json --list-checkpoints

# 从检查点恢复
python -m anomaly_detection.cli --config config.json --resume checkpoint_123456

# 删除检查点
python -m anomaly_detection.cli --config config.json --delete-checkpoint checkpoint_123456
```

### 会话控制

```bash
# 指定会话ID
python -m anomaly_detection.cli --config config.json --session-id my_detection_001

# 设置检查点间隔
python -m anomaly_detection.cli --config config.json --checkpoint-interval 500
```

## 输出和报告

### 输出格式

```bash
# 指定输出格式
python -m anomaly_detection.cli --config config.json \
  --output-format json excel html

# 指定结果目录
python -m anomaly_detection.cli --config config.json \
  --results-dir /path/to/results

# 导出详细报告
python -m anomaly_detection.cli --config config.json \
  --export-report detailed_report.json
```

### 结果过滤

```bash
# 按严重性过滤
python -m anomaly_detection.cli --config config.json \
  --severity-filter critical high

# 按检测器过滤
python -m anomaly_detection.cli --config config.json \
  --detector-filter ConceptMappingDetector RPUStructureDetector

# 按置信度过滤
python -m anomaly_detection.cli --config config.json \
  --min-confidence 0.8
```

## 性能调优

### 内存和处理

```bash
# 设置内存限制
python -m anomaly_detection.cli --config config.json \
  --memory-limit 4.0

# 调整批处理大小
python -m anomaly_detection.cli --config config.json \
  --batch-size 2000

# 并行处理设置
python -m anomaly_detection.cli --config config.json \
  --parallel --max-workers 8
```

### 性能分析

```bash
# 启用性能分析
python -m anomaly_detection.cli --config config.json \
  --profile --profile-output performance.prof

# 试运行模式（不执行实际检测）
python -m anomaly_detection.cli --config config.json --dry-run
```

## 日志和调试

### 日志控制

```bash
# 设置日志级别
python -m anomaly_detection.cli --config config.json --log-level DEBUG

# 输出到日志文件
python -m anomaly_detection.cli --config config.json \
  --log-file detection.log

# 详细输出
python -m anomaly_detection.cli --config config.json --verbose

# 静默模式
python -m anomaly_detection.cli --config config.json --quiet
```

## 常用场景

### 1. 日常检测

```bash
# 标准日常检测流程
python -m anomaly_detection.cli \
  --config production_config.json \
  --session-id daily_$(date +%Y%m%d) \
  --parallel \
  --export-report daily_report_$(date +%Y%m%d).json \
  --log-file daily_detection.log
```

### 2. 快速验证

```bash
# 快速验证新数据
python -m anomaly_detection.cli \
  --db-path new_data.db \
  --detectors ConceptMappingDetector RPUStructureDetector \
  --serial \
  --verbose
```

### 3. 大规模处理

```bash
# 大规模数据处理
python -m anomaly_detection.cli \
  --config large_scale_config.json \
  --parallel \
  --max-workers 16 \
  --memory-limit 8.0 \
  --batch-size 5000 \
  --checkpoint-interval 1000 \
  --log-level INFO
```

### 4. 问题诊断

```bash
# 问题诊断模式
python -m anomaly_detection.cli \
  --config config.json \
  --detectors ConsistencyDetector FormatEncodingDetector \
  --verbose \
  --log-level DEBUG \
  --severity-filter critical high
```

## 配置文件示例

### 基本配置

```json
{
  "paths": {
    "database_path": "data/rpu_database.db",
    "mapping_file": "data/core_mapping.json",
    "output_dir": "output_7_deberta",
    "results_dir": "detection_results",
    "checkpoints_dir": "checkpoints"
  },
  "enabled_detectors": [
    "ConceptMappingDetector",
    "MissingDuplicateDetector",
    "RPUStructureDetector",
    "TimeSeriesDetector",
    "StatisticalDistributionDetector",
    "FormatEncodingDetector",
    "ConsistencyDetector"
  ],
  "parallel_processing": true,
  "performance": {
    "max_workers": 4,
    "batch_size": 1000,
    "memory_limit_gb": 4.0,
    "checkpoint_interval": 500
  },
  "thresholds": {
    "frequency_outlier_z_threshold": 3.0,
    "pmi_outlier_threshold": 5.0,
    "entropy_outlier_z_threshold": 2.5,
    "sparsity_threshold": 0.95
  },
  "logging": {
    "log_level": "INFO",
    "console_level": "INFO",
    "log_file": null
  },
  "report_formats": ["json", "excel"]
}
```

### 高性能配置

```json
{
  "paths": {
    "database_path": "data/large_rpu_database.db",
    "mapping_file": "data/core_mapping.json",
    "output_dir": "output_7_deberta",
    "results_dir": "detection_results",
    "checkpoints_dir": "checkpoints"
  },
  "enabled_detectors": [
    "ConceptMappingDetector",
    "RPUStructureDetector",
    "ConsistencyDetector"
  ],
  "parallel_processing": true,
  "performance": {
    "max_workers": 16,
    "batch_size": 5000,
    "memory_limit_gb": 16.0,
    "checkpoint_interval": 2000
  },
  "thresholds": {
    "frequency_outlier_z_threshold": 4.0,
    "pmi_outlier_threshold": 6.0,
    "entropy_outlier_z_threshold": 3.0,
    "sparsity_threshold": 0.98
  },
  "logging": {
    "log_level": "WARNING",
    "console_level": "INFO",
    "log_file": "high_performance_detection.log"
  },
  "report_formats": ["json"]
}
```

## 故障排除

### 常见问题

1. **内存不足**
   ```bash
   # 减少批处理大小和并行度
   --batch-size 500 --max-workers 2 --memory-limit 2.0
   ```

2. **处理速度慢**
   ```bash
   # 启用并行处理并增加工作进程
   --parallel --max-workers 8 --batch-size 2000
   ```

3. **检测结果过多**
   ```bash
   # 使用过滤器
   --severity-filter high critical --min-confidence 0.9
   ```

4. **配置错误**
   ```bash
   # 验证配置文件
   --validate-config config.json
   ```

### 调试技巧

```bash
# 启用详细日志
--verbose --log-level DEBUG

# 使用试运行模式
--dry-run

# 启用性能分析
--profile --profile-output debug.prof

# 交互式调试
--interactive
```

## 最佳实践

1. **使用配置文件**：避免长命令行，便于版本控制和重复使用
2. **设置合适的检查点间隔**：平衡性能和恢复能力
3. **监控内存使用**：根据系统资源调整批处理大小
4. **使用过滤器**：专注于高优先级异常
5. **保存日志**：便于问题诊断和性能分析
6. **定期清理检查点**：避免磁盘空间浪费

## 环境要求

- Python 3.12+
- 足够的内存（推荐8GB+用于大规模处理）
- 磁盘空间（用于检查点和结果存储）
- 可选：多核CPU（用于并行处理）

## 更多信息

- 查看 `--help` 获取完整参数列表
- 使用 `--interactive` 模式进行实时操作
- 参考配置文件示例进行定制化设置