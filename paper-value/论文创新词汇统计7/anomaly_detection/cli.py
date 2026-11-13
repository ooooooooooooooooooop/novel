"""
命令行接口

提供用户友好的命令行工具，支持配置文件和各种检测选项。
"""

import argparse
import sys
import json
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from .core.config import DetectionConfig, create_default_config
from .core.logging import setup_logging, shutdown_logging, get_logger
from .core.exceptions import AnomalyDetectionException
from .engine.integrated_engine import IntegratedDetectionEngine
from .engine.detection_engine import AnomalyDetectionEngine


def create_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器
    
    Returns:
        参数解析器
    """
    parser = argparse.ArgumentParser(
        description="RIPER-Core 创新结果异常检测系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 使用默认配置运行检测
  python -m anomaly_detection.cli --db-path data.db --output-dir output_7_deberta

  # 使用配置文件运行检测
  python -m anomaly_detection.cli --config config.json

  # 从检查点恢复检测
  python -m anomaly_detection.cli --config config.json --resume checkpoint_123456

  # 生成默认配置文件
  python -m anomaly_detection.cli --generate-config default_config.json

  # 运行性能基准测试
  python -m anomaly_detection.cli --benchmark --record-count 1000

  # 交互式检测模式
  python -m anomaly_detection.cli --interactive

  # 监控模式（实时检测）
  python -m anomaly_detection.cli --monitor --watch-dir /path/to/data
        """
    )
    
    # 基本选项
    parser.add_argument(
        '--config', '-c',
        type=str,
        help='配置文件路径 (JSON格式)'
    )
    
    parser.add_argument(
        '--db-path',
        type=str,
        help='SQLite数据库文件路径'
    )
    
    parser.add_argument(
        '--output-dir',
        type=str,
        help='输出目录路径'
    )
    
    parser.add_argument(
        '--mapping-path',
        type=str,
        help='概念映射文件路径'
    )
    
    # 检测选项
    parser.add_argument(
        '--detectors',
        nargs='+',
        choices=[
            'ConceptMappingDetector',
            'MissingDuplicateDetector',
            'RPUStructureDetector',
            'TimeSeriesDetector',
            'StatisticalDistributionDetector',
            'FormatEncodingDetector',
            'ConsistencyDetector'
        ],
        help='要启用的检测器列表'
    )
    
    parser.add_argument(
        '--parallel',
        action='store_true',
        help='启用并行处理'
    )
    
    parser.add_argument(
        '--serial',
        action='store_true',
        help='强制使用串行处理'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        help='批处理大小 (默认: 1000，这是经验值，可根据内存情况调整)'
    )
    
    parser.add_argument(
        '--max-workers',
        type=int,
        help='最大并行工作进程数'
    )
    
    # 会话管理
    parser.add_argument(
        '--session-id',
        type=str,
        help='检测会话ID'
    )
    
    parser.add_argument(
        '--resume',
        type=str,
        help='从指定检查点恢复检测'
    )
    
    parser.add_argument(
        '--checkpoint-interval',
        type=int,
        help='检查点创建间隔（处理记录数）'
    )
    
    # 输出选项
    parser.add_argument(
        '--output-format',
        nargs='+',
        choices=['json', 'excel', 'html', 'csv'],
        default=['json'],
        help='报告输出格式 (默认: json)'
    )
    
    parser.add_argument(
        '--results-dir',
        type=str,
        default='artifacts/runtime/anomaly_detection_results',
        help='结果输出目录 (默认: artifacts/runtime/anomaly_detection_results)'
    )
    
    parser.add_argument(
        '--export-report',
        type=str,
        help='导出详细报告到指定文件'
    )
    
    # 过滤选项
    parser.add_argument(
        '--severity-filter',
        nargs='+',
        choices=['low', 'medium', 'high', 'critical'],
        help='按严重性过滤异常'
    )
    
    parser.add_argument(
        '--detector-filter',
        nargs='+',
        help='按检测器名称过滤异常'
    )
    
    parser.add_argument(
        '--min-confidence',
        type=float,
        help='最小置信度阈值'
    )
    
    # 日志选项
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='INFO',
        help='日志级别 (默认: INFO)'
    )
    
    parser.add_argument(
        '--log-file',
        type=str,
        help='日志文件路径'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='详细输出模式'
    )
    
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='静默模式，只输出错误信息'
    )
    
    # 工具选项
    parser.add_argument(
        '--generate-config',
        type=str,
        help='生成默认配置文件到指定路径'
    )
    
    parser.add_argument(
        '--validate-config',
        type=str,
        help='验证配置文件有效性'
    )
    
    parser.add_argument(
        '--list-checkpoints',
        action='store_true',
        help='列出可用的检查点'
    )
    
    parser.add_argument(
        '--delete-checkpoint',
        type=str,
        help='删除指定的检查点'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='试运行模式，不执行实际检测'
    )
    
    # 高级选项
    parser.add_argument(
        '--interactive',
        action='store_true',
        help='交互式模式'
    )
    
    parser.add_argument(
        '--benchmark',
        action='store_true',
        help='运行性能基准测试'
    )
    
    parser.add_argument(
        '--record-count',
        type=int,
        default=1000,
        help='基准测试的记录数量 (默认: 1000)'
    )
    
    parser.add_argument(
        '--monitor',
        action='store_true',
        help='监控模式，持续检测新数据'
    )
    
    parser.add_argument(
        '--watch-dir',
        type=str,
        help='监控目录路径'
    )
    
    parser.add_argument(
        '--watch-interval',
        type=int,
        default=60,
        help='监控间隔（秒）(默认: 60，这是经验值，可根据数据更新频率调整)'
    )
    
    # 内存和性能选项
    parser.add_argument(
        '--memory-limit',
        type=float,
        help='内存使用限制 (GB)'
    )
    
    parser.add_argument(
        '--profile',
        action='store_true',
        help='启用性能分析'
    )
    
    parser.add_argument(
        '--profile-output',
        type=str,
        help='性能分析结果输出文件'
    )
    
    return parser


def load_config(args: argparse.Namespace) -> DetectionConfig:
    """加载配置
    
    Args:
        args: 命令行参数
        
    Returns:
        检测配置
        
    Raises:
        AnomalyDetectionException: 配置加载失败
    """
    try:
        if args.config:
            # 从配置文件加载
            config = DetectionConfig.from_file(args.config)
        else:
            # 使用默认配置
            config = create_default_config(
                db_path=args.db_path or "",
                output_dir=args.output_dir or "",
                mapping_path=args.mapping_path or ""
            )
        
        # 命令行参数覆盖配置文件设置
        if args.detectors:
            config.enabled_detectors = args.detectors
        
        if args.parallel:
            config.parallel_processing = True
        
        if args.serial:
            config.parallel_processing = False
        
        if args.batch_size:
            config.performance.batch_size = args.batch_size
        
        if args.max_workers:
            config.performance.max_workers = args.max_workers
        
        if args.checkpoint_interval:
            config.performance.checkpoint_interval = args.checkpoint_interval
        
        if args.memory_limit:
            config.performance.max_memory_gb = args.memory_limit
        
        if args.output_format:
            config.report_formats = args.output_format
        
        if args.results_dir:
            config.paths.results_dir = args.results_dir
        
        if args.log_level:
            config.logging.log_level = args.log_level
        
        if args.log_file:
            config.logging.log_file = args.log_file
        
        if args.verbose:
            config.verbose_output = True
            config.logging.console_level = 'DEBUG'
        
        if args.quiet:
            config.logging.console_level = 'ERROR'
        
        # 验证配置
        config.validate()
        
        return config
        
    except Exception as e:
        raise AnomalyDetectionException(f"配置加载失败: {e}")


def generate_default_config(output_path: str) -> None:
    """生成默认配置文件
    
    Args:
        output_path: 输出文件路径
    """
    try:
        config = create_default_config()
        config.save_to_file(output_path)
        print(f"默认配置文件已生成: {output_path}")
        
    except Exception as e:
        print(f"生成配置文件失败: {e}", file=sys.stderr)
        sys.exit(1)


def validate_config_file(config_path: str) -> None:
    """验证配置文件
    
    Args:
        config_path: 配置文件路径
    """
    try:
        config = DetectionConfig.from_file(config_path)
        config.validate()
        print(f"配置文件验证通过: {config_path}")
        
    except Exception as e:
        print(f"配置文件验证失败: {e}", file=sys.stderr)
        sys.exit(1)


def list_checkpoints(config: DetectionConfig) -> None:
    """列出可用的检查点
    
    Args:
        config: 检测配置
    """
    try:
        with IntegratedDetectionEngine(config) as engine:
            checkpoints = engine.list_checkpoints()
            
            if checkpoints:
                print("可用的检查点:")
                print("-" * 80)
                for checkpoint in checkpoints:
                    print(f"ID: {checkpoint.get('checkpoint_id', 'N/A')}")
                    print(f"会话: {checkpoint.get('session_id', 'N/A')}")
                    print(f"创建时间: {checkpoint.get('creation_time', 'N/A')}")
                    print(f"描述: {checkpoint.get('description', 'N/A')}")
                    print("-" * 40)
            else:
                print("没有找到检查点文件")
                
    except Exception as e:
        print(f"列出检查点失败: {e}", file=sys.stderr)
        sys.exit(1)


def delete_checkpoint(config: DetectionConfig, checkpoint_id: str) -> None:
    """删除指定的检查点
    
    Args:
        config: 检测配置
        checkpoint_id: 检查点ID
    """
    try:
        with IntegratedDetectionEngine(config) as engine:
            success = engine.delete_checkpoint(checkpoint_id)
            
            if success:
                print(f"检查点 {checkpoint_id} 已删除")
            else:
                print(f"删除检查点 {checkpoint_id} 失败")
                
    except Exception as e:
        print(f"删除检查点失败: {e}", file=sys.stderr)
        sys.exit(1)


def run_benchmark(config: DetectionConfig, record_count: int) -> None:
    """运行性能基准测试
    
    Args:
        config: 检测配置
        record_count: 测试记录数量
    """
    try:
        import tempfile
        import sqlite3
        from datetime import datetime, timedelta
        
        print(f"开始性能基准测试 - {record_count} 条记录")
        print("=" * 60)
        
        # 创建临时测试数据
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # 创建测试数据库
            db_path = temp_path / "benchmark.db"
            conn = sqlite3.connect(str(db_path))
            
            conn.execute("""
                CREATE TABLE rpu_records (
                    id INTEGER PRIMARY KEY,
                    paper_id TEXT,
                    sentence_id TEXT,
                    task TEXT,
                    object TEXT,
                    modifier TEXT,
                    confidence REAL,
                    extraction_method TEXT,
                    timestamp TEXT,
                    shard_id TEXT
                )
            """)
            
            # 生成测试数据
            tasks = ["analyze", "predict", "classify", "detect", "measure"]
            objects = ["protein", "gene", "cell", "tissue", "organism"]
            modifiers = ["structure", "function", "expression", "activity", ""]
            
            test_data = []
            for i in range(record_count):
                test_data.append((
                    f"paper_{i:06d}",
                    f"sent_{i:06d}",
                    tasks[i % len(tasks)],
                    objects[i % len(objects)],
                    modifiers[i % len(modifiers)],
                    0.8 + (i % 20) * 0.01,
                    "deberta",
                    (datetime.now() + timedelta(seconds=i)).isoformat(),
                    f"shard_{i % 10:03d}"
                ))
            
            conn.executemany("""
                INSERT INTO rpu_records 
                (paper_id, sentence_id, task, object, modifier, confidence, extraction_method, timestamp, shard_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, test_data)
            
            conn.commit()
            conn.close()
            
            # 创建映射文件
            mapping_data = {obj: f"{obj}_canonical" for obj in objects}
            mapping_path = temp_path / "mapping.json"
            with open(mapping_path, 'w') as f:
                json.dump(mapping_data, f)
            
            # 更新配置
            config.paths.db_path = str(db_path)
            config.paths.mapping_path = str(mapping_path)
            
            # 运行基准测试
            start_time = time.time()
            
            with IntegratedDetectionEngine(config) as engine:
                session = engine.run_detection(
                    session_id=f"benchmark_{record_count}",
                    force_serial=not config.parallel_processing
                )
                
                results = engine.get_detection_results()
                summary = engine.get_detection_summary()
            
            end_time = time.time()
            processing_time = end_time - start_time
            
            # 输出基准测试结果
            print(f"基准测试完成!")
            print(f"记录数量: {record_count}")
            print(f"处理时间: {processing_time:.2f} 秒")
            print(f"处理速度: {record_count / processing_time:.1f} 记录/秒")
            print(f"发现异常: {len(results)} 个")
            print(f"并行模式: {'是' if config.parallel_processing else '否'}")
            
            if summary.get('severity_distribution'):
                print("异常严重性分布:")
                for severity, count in summary['severity_distribution'].items():
                    print(f"  {severity}: {count}")
            
    except Exception as e:
        print(f"基准测试失败: {e}", file=sys.stderr)
        sys.exit(1)


def run_interactive_mode(config: DetectionConfig) -> None:
    """运行交互式模式
    
    Args:
        config: 检测配置
    """
    print("=" * 60)
    print("RIPER-Core 异常检测系统 - 交互式模式")
    print("=" * 60)
    print("输入 'help' 查看可用命令，输入 'quit' 退出")
    
    engine = None
    
    try:
        while True:
            try:
                command = input("\n> ").strip().lower()
                
                if command == 'quit' or command == 'exit':
                    break
                
                elif command == 'help':
                    print_interactive_help()
                
                elif command == 'status':
                    if engine:
                        summary = engine.get_detection_summary()
                        print_status(summary)
                    else:
                        print("没有活动的检测会话")
                
                elif command == 'start':
                    if engine:
                        print("检测已在运行中")
                    else:
                        engine = IntegratedDetectionEngine(config)
                        session_id = f"interactive_{int(time.time())}"
                        print(f"开始检测会话: {session_id}")
                        session = engine.run_detection(session_id=session_id)
                        print(f"检测完成: {session.status}")
                
                elif command == 'results':
                    if engine:
                        results = engine.get_detection_results()
                        print_results_summary(results)
                    else:
                        print("没有活动的检测会话")
                
                elif command == 'checkpoints':
                    if engine:
                        checkpoints = engine.list_checkpoints()
                        print_checkpoints(checkpoints)
                    else:
                        print("没有活动的检测会话")
                
                elif command.startswith('checkpoint'):
                    if engine:
                        parts = command.split()
                        description = " ".join(parts[1:]) if len(parts) > 1 else "交互式检查点"
                        checkpoint_id = engine.create_checkpoint(description)
                        print(f"检查点已创建: {checkpoint_id}")
                    else:
                        print("没有活动的检测会话")
                
                elif command == 'stop':
                    if engine:
                        engine.close()
                        engine = None
                        print("检测会话已停止")
                    else:
                        print("没有活动的检测会话")
                
                else:
                    print(f"未知命令: {command}，输入 'help' 查看可用命令")
                    
            except KeyboardInterrupt:
                print("\n使用 'quit' 命令退出")
            except Exception as e:
                print(f"命令执行错误: {e}")
    
    finally:
        if engine:
            engine.close()


def run_monitor_mode(config: DetectionConfig, watch_dir: str, interval: int) -> None:
    """运行监控模式
    
    Args:
        config: 检测配置
        watch_dir: 监控目录
        interval: 监控间隔（秒）
    """
    print(f"开始监控模式")
    print(f"监控目录: {watch_dir}")
    print(f"检查间隔: {interval} 秒")
    print("按 Ctrl+C 停止监控")
    
    watch_path = Path(watch_dir)
    if not watch_path.exists():
        print(f"监控目录不存在: {watch_dir}", file=sys.stderr)
        sys.exit(1)
    
    last_check = {}  # 文件修改时间缓存
    
    try:
        while True:
            try:
                # 检查目录中的文件变化
                current_files = {}
                for file_path in watch_path.rglob("*"):
                    if file_path.is_file():
                        current_files[str(file_path)] = file_path.stat().st_mtime
                
                # 检测新文件或修改的文件
                changed_files = []
                for file_path, mtime in current_files.items():
                    if file_path not in last_check or last_check[file_path] != mtime:
                        changed_files.append(file_path)
                
                if changed_files:
                    print(f"\n检测到 {len(changed_files)} 个文件变化")
                    
                    # 更新配置以处理新文件
                    # 这里简化处理，实际应用中需要更复杂的逻辑
                    session_id = f"monitor_{int(time.time())}"
                    
                    with IntegratedDetectionEngine(config) as engine:
                        session = engine.run_detection(session_id=session_id)
                        results = engine.get_detection_results()
                        
                        if results:
                            print(f"发现 {len(results)} 个新异常")
                            for result in results[:5]:  # 只显示前5个
                                print(f"  - {result.anomaly_type}: {result.description[:100]}...")
                        else:
                            print("未发现新异常")
                
                last_check = current_files
                time.sleep(interval)
                
            except KeyboardInterrupt:
                print("\n监控已停止")
                break
            except Exception as e:
                print(f"监控过程中出错: {e}")
                time.sleep(interval)
                
    except Exception as e:
        print(f"监控模式失败: {e}", file=sys.stderr)
        sys.exit(1)


def print_interactive_help() -> None:
    """打印交互式模式帮助信息"""
    print("""
可用命令:
  help        - 显示此帮助信息
  start       - 开始新的检测会话
  stop        - 停止当前检测会话
  status      - 显示当前状态
  results     - 显示检测结果摘要
  checkpoints - 列出检查点
  checkpoint [描述] - 创建检查点
  quit/exit   - 退出交互式模式
    """)


def print_status(summary: Dict[str, Any]) -> None:
    """打印状态信息"""
    print(f"会话ID: {summary.get('session_id', 'N/A')}")
    print(f"状态: {summary.get('status', 'N/A')}")
    print(f"总异常数: {summary.get('total_anomalies', 0)}")
    
    if summary.get('progress_percentage'):
        print(f"进度: {summary['progress_percentage']:.1f}%")


def print_results_summary(results: List) -> None:
    """打印结果摘要"""
    if not results:
        print("没有检测结果")
        return
    
    print(f"总异常数: {len(results)}")
    
    # 按严重性统计
    severity_counts = {}
    for result in results:
        severity = result.severity.value
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
    
    print("严重性分布:")
    for severity, count in severity_counts.items():
        print(f"  {severity}: {count}")


def print_checkpoints(checkpoints: List[Dict[str, Any]]) -> None:
    """打印检查点信息"""
    if not checkpoints:
        print("没有检查点")
        return
    
    print(f"检查点数量: {len(checkpoints)}")
    for checkpoint in checkpoints[-5:]:  # 显示最近5个
        print(f"  {checkpoint.get('checkpoint_id', 'N/A')}: {checkpoint.get('description', 'N/A')}")


def filter_results(results: List, args: argparse.Namespace) -> List:
    """根据命令行参数过滤结果
    
    Args:
        results: 检测结果列表
        args: 命令行参数
        
    Returns:
        过滤后的结果列表
    """
    filtered_results = results
    
    # 按严重性过滤
    if args.severity_filter:
        filtered_results = [
            r for r in filtered_results 
            if r.severity.value in args.severity_filter
        ]
    
    # 按检测器过滤
    if args.detector_filter:
        filtered_results = [
            r for r in filtered_results 
            if r.detector_name in args.detector_filter
        ]
    
    # 按置信度过滤
    if args.min_confidence:
        filtered_results = [
            r for r in filtered_results 
            if r.confidence_score >= args.min_confidence
        ]
    
    return filtered_results


def run_detection(config: DetectionConfig, args: argparse.Namespace) -> None:
    """运行异常检测

    Args:
        config: 检测配置
        args: 命令行参数
    """
    # 设置日志（必须在get_logger之前）
    setup_logging(config.logging)
    logger = get_logger("CLI")

    try:
        
        if not args.quiet:
            print("=" * 60)
            print("RIPER-Core 创新结果异常检测系统")
            print("=" * 60)
        
        if args.dry_run:
            print("试运行模式 - 不执行实际检测")
            print(f"配置摘要:")
            print(f"  - 启用的检测器: {config.enabled_detectors}")
            print(f"  - 并行处理: {config.parallel_processing}")
            print(f"  - 批处理大小: {config.performance.batch_size}")
            print(f"  - 输出格式: {config.report_formats}")
            print(f"  - 内存限制: {config.performance.max_memory_gb}GB")
            return
        
        # 性能分析设置
        profiler = None
        if args.profile:
            try:
                import cProfile
                profiler = cProfile.Profile()
                profiler.enable()
            except ImportError:
                print("警告: 无法启用性能分析，cProfile模块不可用")
        
        # 创建结果目录
        results_dir = Path(config.paths.results_dir)
        results_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建集成检测引擎
        with IntegratedDetectionEngine(config) as engine:
            if not args.quiet:
                print(f"开始异常检测...")
                print(f"会话ID: {args.session_id or '自动生成'}")
                print(f"处理模式: {'并行' if config.parallel_processing else '串行'}")
            
            # 运行检测
            start_time = time.time()
            
            session = engine.run_detection(
                session_id=args.session_id,
                checkpoint_id=args.resume,
                force_serial=args.serial
            )
            
            end_time = time.time()
            processing_time = end_time - start_time
            
            # 获取检测结果和摘要
            results = engine.get_detection_results()
            summary = engine.get_detection_summary()
            
            # 应用过滤器
            filtered_results = filter_results(results, args)
            
            if not args.quiet:
                print("\n检测完成!")
                print(f"会话ID: {summary['session_id']}")
                print(f"检测状态: {summary['status']}")
                print(f"处理时间: {processing_time:.2f} 秒")
                print(f"发现异常: {len(results)} 个")
                
                if len(filtered_results) != len(results):
                    print(f"过滤后异常: {len(filtered_results)} 个")
                
                if summary.get('severity_distribution'):
                    print("严重性分布:")
                    for severity, count in summary['severity_distribution'].items():
                        print(f"  - {severity}: {count}")
                
                if summary.get('detector_distribution'):
                    print("检测器分布:")
                    for detector, count in summary['detector_distribution'].items():
                        print(f"  - {detector}: {count}")
                
                # 显示处理速度
                if summary.get('total_records'):
                    speed = summary['total_records'] / processing_time if processing_time > 0 else 0
                    print(f"处理速度: {speed:.1f} 记录/秒")
            
            # 保存结果
            session_id = session.session_id
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # 保存JSON格式结果
            if 'json' in config.report_formats:
                json_file = results_dir / f"detection_results_{session_id}_{timestamp}.json"
                
                results_data = {
                    'session_info': {
                        'session_id': session_id,
                        'start_time': session.start_time.isoformat(),
                        'end_time': session.end_time.isoformat() if session.end_time else None,
                        'processing_time': processing_time,
                        'status': session.status.value,
                        'config_hash': session.config_hash
                    },
                    'summary': summary,
                    'results': [
                        {
                            'anomaly_id': result.anomaly_id,
                            'detector_name': result.detector_name,
                            'anomaly_type': result.anomaly_type,
                            'severity': result.severity.value,
                            'description': result.description,
                            'affected_entities': result.affected_entities,
                            'evidence': result.evidence,
                            'suggested_fixes': result.suggested_fixes,
                            'confidence_score': result.confidence_score,
                            'detection_timestamp': result.detection_timestamp.isoformat()
                        }
                        for result in filtered_results
                    ]
                }
                
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(results_data, f, indent=2, ensure_ascii=False)
                
                if not args.quiet:
                    print(f"JSON结果已保存到: {json_file}")
            
            # 导出详细报告
            if args.export_report:
                export_format = Path(args.export_report).suffix.lower().lstrip('.')
                if not export_format:
                    export_format = 'json'
                
                engine.export_detection_report(args.export_report, format=export_format)
                
                if not args.quiet:
                    print(f"详细报告已导出到: {args.export_report}")
            
            # 显示高优先级异常
            if not args.quiet and filtered_results:
                critical_results = [r for r in filtered_results if r.severity.value == 'critical']
                high_results = [r for r in filtered_results if r.severity.value == 'high']
                
                if critical_results:
                    print(f"\n严重异常 ({len(critical_results)} 个):")
                    for result in critical_results[:3]:  # 只显示前3个
                        print(f"  - {result.anomaly_type}: {result.description[:100]}...")
                
                if high_results:
                    print(f"\n高优先级异常 ({len(high_results)} 个):")
                    for result in high_results[:3]:  # 只显示前3个
                        print(f"  - {result.anomaly_type}: {result.description[:100]}...")
        
        # 性能分析结果
        if profiler:
            profiler.disable()
            
            if args.profile_output:
                profiler.dump_stats(args.profile_output)
                print(f"性能分析结果已保存到: {args.profile_output}")
            else:
                import pstats
                stats = pstats.Stats(profiler)
                stats.sort_stats('cumulative')
                print("\n性能分析结果 (前10个函数):")
                stats.print_stats(10)
        
    except KeyboardInterrupt:
        print("\n检测被用户中断")
        sys.exit(1)
        
    except Exception as e:
        logger.error(f"检测执行失败: {e}")
        print(f"检测执行失败: {e}", file=sys.stderr)
        sys.exit(1)
        
    finally:
        shutdown_logging()


def main() -> None:
    """主函数"""
    parser = create_parser()
    args = parser.parse_args()
    
    # 处理工具选项
    if args.generate_config:
        generate_default_config(args.generate_config)
        return
    
    if args.validate_config:
        validate_config_file(args.validate_config)
        return
    
    # 加载配置
    try:
        config = load_config(args)
    except Exception as e:
        print(f"配置加载失败: {e}", file=sys.stderr)
        sys.exit(1)
    
    # 处理其他工具选项
    if args.list_checkpoints:
        list_checkpoints(config)
        return
    
    if args.delete_checkpoint:
        delete_checkpoint(config, args.delete_checkpoint)
        return
    
    if args.benchmark:
        run_benchmark(config, args.record_count)
        return
    
    if args.interactive:
        run_interactive_mode(config)
        return
    
    if args.monitor:
        if not args.watch_dir:
            print("监控模式需要指定 --watch-dir 参数", file=sys.stderr)
            sys.exit(1)
        run_monitor_mode(config, args.watch_dir, args.watch_interval)
        return
    
    # 验证必要参数
    if not any([config.paths.db_path, config.paths.output_dir, config.paths.mapping_path]):
        print("错误: 至少需要指定一个数据源 (--db-path, --output-dir, 或 --mapping-path)", file=sys.stderr)
        print("或者使用 --config 指定配置文件", file=sys.stderr)
        sys.exit(1)
    
    # 运行检测
    run_detection(config, args)


if __name__ == '__main__':
    main()
