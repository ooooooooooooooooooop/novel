# -*- coding: utf-8 -*-
"""
V2 创新度评分 - 全量数据运行脚本

处理全部 4000 万论文，按年份顺序处理，支持断点续传。

使用方法:
  python scripts/pipeline/run_v2_full.py                    # 从头开始运行
  python scripts/pipeline/run_v2_full.py --resume           # 从检查点恢复
  python scripts/pipeline/run_v2_full.py --years 2018-2020  # 只处理指定年份范围
  python scripts/pipeline/run_v2_full.py --dry-run          # 只显示计划，不实际运行
  python scripts/pipeline/run_v2_full.py --years 2021-2025 --warmup-to 2021  # 预热后重跑指定年份

内存优化: cooc_counts 使用 Count-Min Sketch，固定 ~256MB 内存（原方案需要 ~77GB）
"""

import sqlite3
import json
import time
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.pipeline.calculate_innovation import InnovationState, PaperTypePostProcessor
from project_config import load_project_config, get_paths

# 配置
_cfg = load_project_config()
_paths = get_paths(_cfg)
DB_PATH = _paths["rpu_db_path"]
OUTPUT_DIR = _paths["innovation_output_dir"]
CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "checkpoint.json")
LOG_FILE = os.path.join(OUTPUT_DIR, "run_log.txt")


def apply_config(config_path: str = None):
    global DB_PATH, OUTPUT_DIR, CHECKPOINT_FILE, LOG_FILE
    cfg = load_project_config(config_path)
    paths = get_paths(cfg)
    DB_PATH = paths["rpu_db_path"]
    OUTPUT_DIR = paths["innovation_output_dir"]
    CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "checkpoint.json")
    LOG_FILE = os.path.join(OUTPUT_DIR, "run_log.txt")


def log_message(msg: str, also_print: bool = True):
    """写入日志并可选打印"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {msg}"
    if also_print:
        print(msg, flush=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_line + '\n')


def get_years_from_db(db_path: str) -> list:
    """获取数据库中所有有效年份"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT pub_year FROM papers
        WHERE pub_year IS NOT NULL
          AND pub_year >= 2010
          AND pub_year <= 2025
        ORDER BY pub_year
    """)
    years = [row[0] for row in cur.fetchall()]
    conn.close()
    return years


def get_year_paper_count(db_path: str, year: int) -> int:
    """获取指定年份的论文数量"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM papers WHERE pub_year = ?", (year,))
    count = cur.fetchone()[0]
    conn.close()
    return count


def load_year_papers(db_path: str, year: int, progress_callback=None):
    """加载指定年份的所有论文及其RPU"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 获取该年份所有论文
    cur.execute("""
        SELECT paper_id, title FROM papers WHERE pub_year = ?
        ORDER BY paper_id
    """, (year,))
    paper_rows = cur.fetchall()
    total_papers = len(paper_rows)

    papers = []
    paper_titles = {}

    # 进度报告间隔
    progress_interval = max(10000, total_papers // 10)
    load_start = time.time()

    for idx, p in enumerate(paper_rows):
        paper_id = p['paper_id']
        title = p['title'] or ''
        paper_titles[paper_id] = title

        # 获取 RPU
        cur.execute("""
            SELECT task, object, aspect, context, task_modifier, object_modifier,
                   task_cores, object_cores
            FROM rpu WHERE paper_id = ?
        """, (paper_id,))
        rpu_rows = cur.fetchall()

        if not rpu_rows:
            # 没有 RPU 的论文也要处理（会得到 0 分）
            papers.append((paper_id, []))
            continue

        rpus = []
        for r in rpu_rows:
            rpu = {
                'task': r['task'],
                'object': r['object'],
                'aspect': r['aspect'],
                'context': r['context'],
                'task_modifier': r['task_modifier'],
                'object_modifier': r['object_modifier'],
            }
            # 使用 core 字段
            if r['task_cores']:
                try:
                    cores = json.loads(r['task_cores'])
                    if cores:
                        rpu['task_core'] = cores[0]
                except:
                    pass
            if r['object_cores']:
                try:
                    cores = json.loads(r['object_cores'])
                    if cores:
                        rpu['object_core'] = cores[0]
                except:
                    pass
            # modifier 字段合并
            mods = []
            if r['task_modifier']:
                mods.append(r['task_modifier'])
            if r['object_modifier']:
                mods.append(r['object_modifier'])
            if mods:
                rpu['modifier'] = ' '.join(mods)

            rpus.append(rpu)

        papers.append((paper_id, rpus))

        # 进度报告
        if progress_callback and idx > 0 and idx % progress_interval == 0:
            elapsed = time.time() - load_start
            rate = idx / elapsed if elapsed > 0 else 0
            eta = (total_papers - idx) / rate if rate > 0 else 0
            progress_callback(idx, total_papers, rate, eta)

    conn.close()
    return papers, paper_titles


def save_checkpoint(year: int, processed_papers: int, total_time: float,
                   completed_years: list, year_stats: dict):
    """保存检查点"""
    checkpoint = {
        'last_completed_year': year,
        'processed_papers': processed_papers,
        'total_time': total_time,
        'completed_years': completed_years,
        'year_stats': year_stats,
        'timestamp': datetime.now().isoformat()
    }
    with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
        json.dump(checkpoint, f, indent=2, ensure_ascii=False)


def load_checkpoint():
    """加载检查点"""
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def format_time(seconds: float) -> str:
    """格式化时间显示"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.2f}h"


def get_memory_usage_gb():
    """获取当前进程内存使用（GB）"""
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / (1024 ** 3)
    except ImportError:
        return -1  # psutil 未安装


def get_state_memory_stats(state):
    """获取 InnovationState 各组件的条目数量（用于监控增长）"""
    # cooc_counts 现在是 CMS，获取其统计信息
    if hasattr(state.cooc_counts, 'stats'):
        cms_stats = state.cooc_counts.stats()
        cooc_info = f"{cms_stats['memory_mb']:.0f}MB"
    else:
        cooc_info = len(state.cooc_counts)

    stats = {
        'term_counts': len(state.term_counts),
        'pair_counts': len(state.pair_counts),
        'cooc_counts': cooc_info,  # CMS 返回内存大小，dict 返回条目数
        'mod_given_core': len(state.mod_given_core_counts),
        'accumulated_features': len(state.regular_space_model.accumulated_features),
        'task_idf_tasks': len(state.task_idf_tracker.task_doc_freq),
    }
    return stats


def warmup_state(state, warmup_to: int, db_path: str):
    """
    预热模型状态：重放历史年份的 Phase 2（状态更新），不计算分数、不产出文件。

    用于 --resume 恢复时恢复 InnovationState、PCA、IDF 等内存中模型状态。

    内存优化：
    - 分批从数据库流式加载（每批 10000 篇）
    - 单次遍历同时更新所有状态
    - 处理完一批立即释放
    - cooc_counts 使用 Count-Min Sketch，固定 256MB 内存

    Args:
        state: InnovationState 实例
        warmup_to: 预热到该年份（不含），如 2021 表示预热 2010-2020
        db_path: 数据库路径
    """
    from scripts.pipeline.calculate_innovation import YearBuffer
    import gc

    BATCH_SIZE = 10000  # 每批处理的论文数

    # 获取预热年份列表（数据库中所有 < warmup_to 的年份）
    warmup_years = [y for y in get_years_from_db(db_path) if y < warmup_to]

    if not warmup_years:
        log_message(f"[预热] 没有需要预热的年份（warmup_to={warmup_to}）")
        return

    log_message(f"\n{'='*50}")
    log_message(f"[预热] 开始预热模型: {warmup_years[0]}-{warmup_years[-1]} ({len(warmup_years)} 年)")
    log_message(f"[预热] 两遍处理以匹配原始 process_year_atomic 行为")
    log_message(f"{'='*50}")

    warmup_start = time.time()

    for idx, year in enumerate(warmup_years):
        year_start = time.time()

        # 获取该年论文数量
        paper_count = get_year_paper_count(db_path, year)
        log_message(f"  [{idx+1}/{len(warmup_years)}] 预热 {year} 年 ({paper_count:,} 篇)...")

        if paper_count == 0:
            log_message(f"    跳过（无论文）")
            continue

        # ============================================================
        # 模拟 Phase 1 开始时的状态更新（与 process_year_atomic 一致）
        # ============================================================
        state.update_modifier_filter_at_year_boundary(str(year))
        state.precompute_idf_range()

        # 创建 YearBuffer
        year_buffer = YearBuffer()

        # ============================================================
        # 第一遍：加载数据 + 更新 YearBuffer + 更新 TaskIDF
        # （保存 rpu_list 供第二遍使用）
        # ============================================================
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("SELECT paper_id FROM papers WHERE pub_year = ? ORDER BY paper_id", (year,))
        paper_ids = [row[0] for row in cur.fetchall()]

        # 保存所有论文的 rpu_list 供第二遍使用
        all_papers_rpus = []

        processed = 0
        for batch_start in range(0, len(paper_ids), BATCH_SIZE):
            batch_ids = paper_ids[batch_start:batch_start + BATCH_SIZE]

            for paper_id in batch_ids:
                cur.execute("""
                    SELECT task, object, aspect, context, task_modifier, object_modifier,
                           task_cores, object_cores
                    FROM rpu WHERE paper_id = ?
                """, (paper_id,))
                rpu_rows = cur.fetchall()

                if not rpu_rows:
                    continue

                rpus = []
                for r in rpu_rows:
                    rpu = {
                        'task': r['task'],
                        'object': r['object'],
                        'aspect': r['aspect'],
                        'context': r['context'],
                        'task_modifier': r['task_modifier'],
                        'object_modifier': r['object_modifier'],
                    }
                    if r['task_cores']:
                        try:
                            cores = json.loads(r['task_cores'])
                            if cores:
                                rpu['task_core'] = cores[0]
                        except:
                            pass
                    if r['object_cores']:
                        try:
                            cores = json.loads(r['object_cores'])
                            if cores:
                                rpu['object_core'] = cores[0]
                        except:
                            pass
                    mods = []
                    if r['task_modifier']:
                        mods.append(r['task_modifier'])
                    if r['object_modifier']:
                        mods.append(r['object_modifier'])
                    if mods:
                        rpu['modifier'] = ' '.join(mods)
                    rpus.append(rpu)

                if rpus:
                    # 第一遍：只更新 buffer 和 TaskIDF，保存 rpus
                    year_buffer.accumulate_from_paper(rpus)
                    state.task_idf_tracker.update_from_paper(rpus)
                    all_papers_rpus.append(rpus)

                processed += 1

            if batch_start > 0 and batch_start % (BATCH_SIZE * 10) == 0:
                print(f"\r    第一遍: {processed:,}/{paper_count:,} ({100*processed/paper_count:.0f}%)", end="", flush=True)

        conn.close()

        if processed > BATCH_SIZE * 10:
            print()

        # ============================================================
        # 合并状态（顺序与原始 process_year_atomic 一致）
        # ============================================================
        # 先更新 modifier_filter（原始代码是先 filter 再 merge）
        if state.modifier_filter:
            year_buffer.update_modifier_filter_from_buffer(state)

        # 再合并 buffer
        year_buffer.merge_into_state(state)

        # ============================================================
        # 第二遍：提取特征（此时 TaskIDF 已包含完整的当年数据）
        # ============================================================
        year_feature_vecs = []
        for rpus in all_papers_rpus:
            fv = state.feature_extractor.extract_features(rpus)
            year_feature_vecs.append(fv)

        # 更新 PCA
        state.regular_space_model.update_at_year_boundary(year_feature_vecs, str(year))

        # 清理
        year_buffer.cleanup()
        del all_papers_rpus
        del year_feature_vecs
        gc.collect()

        year_time = time.time() - year_start
        mem_gb = get_memory_usage_gb()
        stats = get_state_memory_stats(state)
        log_message(f"    完成 ({year_time:.1f}s, {processed:,} 篇)")
        log_message(f"    内存: {mem_gb:.1f}GB | cooc={stats['cooc_counts']} pair={stats['pair_counts']:,} term={stats['term_counts']:,}")

    warmup_time = time.time() - warmup_start

    # 报告预热后的模型状态
    pca_info = state.regular_space_model.explained_variance_info
    mem_gb = get_memory_usage_gb()
    stats = get_state_memory_stats(state)

    log_message(f"\n[预热完成] 耗时 {format_time(warmup_time)}")
    log_message(f"  TaskIDF total_docs: {state.task_idf_tracker.total_docs}")
    log_message(f"  PCA: k={pca_info.get('k', '?')}, var={pca_info.get('cumulative_variance', 0):.1%}, "
                f"n={pca_info.get('n_samples', 0):,}")
    log_message(f"  内存使用: {mem_gb:.1f} GB")
    log_message(f"  状态大小:")
    log_message(f"    cooc_counts (CMS): {stats['cooc_counts']}")
    log_message(f"    pair_counts: {stats['pair_counts']:,} 条目")
    log_message(f"    term_counts: {stats['term_counts']:,} 条目")
    log_message(f"    accumulated_features: {stats['accumulated_features']:,} / 2,000,000")
    log_message(f"{'='*50}\n")


def main():
    parser = argparse.ArgumentParser(
        description="V2 创新度全量计算",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/pipeline/run_v2_full.py                    # 从头开始运行
  python scripts/pipeline/run_v2_full.py --resume           # 从检查点恢复
  python scripts/pipeline/run_v2_full.py --years 2018-2020  # 只处理指定年份
  python scripts/pipeline/run_v2_full.py --dry-run          # 只显示计划
  python scripts/pipeline/run_v2_full.py --years 2021-2025 --warmup-to 2021  # 预热后重跑
        """
    )
    parser.add_argument("--resume", action="store_true", help="从检查点恢复")
    parser.add_argument("--years", type=str, help="指定年份范围，如 '2018-2022'")
    parser.add_argument("--warmup-to", type=int, help="预热模型到指定年份（不含），如 --warmup-to 2021 会用 2010-2020 预热")
    parser.add_argument("--no-postprocess", action="store_true", help="不应用论文类型后处理")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划，不实际运行")
    parser.add_argument("--config", type=str, default=None, help="配置文件路径（JSON）")
    args = parser.parse_args()

    apply_config(args.config)

    # 创建输出目录
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 70)
    print("V2 创新度评分 - 全量数据运行")
    print("=" * 70)
    print(f"数据库: {DB_PATH}")
    print(f"输出目录: {OUTPUT_DIR}")
    print(f"日志文件: {LOG_FILE}")

    # 检查数据库是否存在
    if not os.path.exists(DB_PATH):
        print(f"\n[错误] 数据库文件不存在: {DB_PATH}")
        sys.exit(1)

    # 获取年份列表
    all_years = get_years_from_db(DB_PATH)
    if not all_years:
        print("\n[错误] 数据库中没有找到有效年份")
        sys.exit(1)
    print(f"数据库年份范围: {min(all_years)} - {max(all_years)}")

    # 过滤年份
    if args.years:
        try:
            start_year, end_year = map(int, args.years.split('-'))
            all_years = [y for y in all_years if start_year <= y <= end_year]
            print(f"指定处理年份: {start_year} - {end_year}")
        except ValueError:
            print(f"\n[错误] 无效的年份范围格式: {args.years}")
            print("正确格式: --years 2018-2022")
            sys.exit(1)

    if not all_years:
        print("\n[错误] 指定范围内没有可处理的年份")
        sys.exit(1)

    # 检查点恢复
    start_year_idx = 0
    total_processed = 0
    total_time_elapsed = 0.0
    completed_years = []
    year_stats = {}

    if args.resume:
        checkpoint = load_checkpoint()
        if checkpoint:
            last_year = checkpoint['last_completed_year']
            if last_year in all_years:
                start_year_idx = all_years.index(last_year) + 1
                total_processed = checkpoint.get('processed_papers', 0)
                total_time_elapsed = checkpoint.get('total_time', 0.0)
                completed_years = checkpoint.get('completed_years', [])
                year_stats = checkpoint.get('year_stats', {})
                print(f"\n[断点恢复] 已完成到 {last_year} 年")
                print(f"  已处理论文: {total_processed:,} 篇")
                print(f"  已用时间: {format_time(total_time_elapsed)}")
                print(f"  警告: 恢复时 PCA 模型将从头训练，但不影响已保存结果")
            else:
                print(f"\n[警告] 检查点年份 {last_year} 不在当前处理范围内，从头开始")
        else:
            print("\n[信息] 未找到检查点，从头开始")

    years_to_process = all_years[start_year_idx:]

    if not years_to_process:
        print("\n[完成] 所有年份已处理完毕")
        sys.exit(0)

    # 预估总工作量
    print(f"\n待处理年份: {len(years_to_process)} 年 ({years_to_process[0]} - {years_to_process[-1]})")

    if args.dry_run or len(years_to_process) <= 5:
        print("\n各年份论文数量预估:")
        total_papers_estimate = 0
        for year in years_to_process:
            count = get_year_paper_count(DB_PATH, year)
            total_papers_estimate += count
            print(f"  {year}: {count:,} 篇")
        print(f"  总计: {total_papers_estimate:,} 篇")

        if args.dry_run:
            # 估算时间 (按 5000 篇/秒估算)
            est_time = total_papers_estimate / 5000
            print(f"\n预计运行时间: {format_time(est_time)}")
            print("\n[Dry Run] 使用 --resume 或不带 --dry-run 参数运行")
            sys.exit(0)

    # 初始化
    log_message("\n初始化 InnovationState...")
    state = InnovationState(config=None, enable_performance_metrics=True)
    processor = PaperTypePostProcessor() if not args.no_postprocess else None

    if processor:
        log_message("论文类型后处理: 启用")
    else:
        log_message("论文类型后处理: 禁用")

    # 预热模型状态（如果指定了 --warmup-to）
    if args.warmup_to:
        warmup_state(state, args.warmup_to, DB_PATH)

    # 处理各年份
    log_message("\n" + "=" * 70)
    log_message("开始处理")
    log_message("=" * 70)

    start_time = time.time()

    for year_idx, year in enumerate(years_to_process):
        year_start = time.time()

        log_message(f"\n{'='*50}")
        log_message(f"[{year_idx + 1}/{len(years_to_process)}] 处理年份 {year}")
        log_message(f"{'='*50}")

        # 检查是否已有输出文件
        output_file = os.path.join(OUTPUT_DIR, f"innovation_v2_{year}.jsonl")
        if os.path.exists(output_file):
            log_message(f"  [警告] 输出文件已存在，将被覆盖: {output_file}")

        # 加载数据
        log_message(f"  [1/4] 加载论文数据...")

        def load_progress(current, total, rate, eta):
            print(f"\r    加载进度: {current:,}/{total:,} ({100*current/total:.1f}%) | "
                  f"{rate:.0f} 篇/秒 | ETA: {eta:.0f}s", end="", flush=True)

        load_start = time.time()
        year_papers, paper_titles = load_year_papers(DB_PATH, year, load_progress)
        load_time = time.time() - load_start
        print()  # 换行
        log_message(f"    完成: {len(year_papers):,} 篇, 耗时 {load_time:.1f}s")

        if not year_papers:
            log_message(f"  [跳过] 无论文")
            continue

        # 计算创新度
        log_message(f"  [2/4] 计算创新度...")
        calc_start = time.time()
        results = state.process_year_atomic(year_papers, str(year))
        calc_time = time.time() - calc_start
        log_message(f"    完成: 耗时 {calc_time:.1f}s, 速率 {len(results)/calc_time:.0f} 篇/秒")

        # 后处理
        if processor:
            log_message(f"  [3/4] 应用论文类型后处理...")
            processor.apply_type_weights(results, paper_titles)
            type_stats = processor.get_weight_stats(results)
            log_message(f"    类型分布: {dict(type_stats)}")
        else:
            log_message(f"  [3/4] 跳过后处理")

        # 保存结果
        log_message(f"  [4/4] 保存结果...")
        save_start = time.time()
        with open(output_file, 'w', encoding='utf-8') as f:
            for r in results:
                # 移除临时字段，减小文件大小
                r_clean = {k: v for k, v in r.items() if not k.endswith('_unweighted')}
                f.write(json.dumps(r_clean, ensure_ascii=False) + '\n')
        save_time = time.time() - save_start
        file_size = os.path.getsize(output_file) / (1024 * 1024)  # MB
        log_message(f"    完成: {output_file}")
        log_message(f"    文件大小: {file_size:.1f} MB, 耗时 {save_time:.1f}s")

        # 更新统计
        total_processed += len(results)
        year_time = time.time() - year_start
        total_time_elapsed += year_time
        completed_years.append(year)

        # 保存年度统计
        year_stats[str(year)] = {
            'papers': len(results),
            'time': year_time,
            'load_time': load_time,
            'calc_time': calc_time,
            'save_time': save_time,
            'file_size_mb': file_size
        }

        # 保存检查点
        save_checkpoint(year, total_processed, total_time_elapsed,
                       completed_years, year_stats)

        # 进度报告
        elapsed = time.time() - start_time
        papers_per_sec = total_processed / elapsed if elapsed > 0 else 0
        remaining_years = len(years_to_process) - year_idx - 1

        # 估算剩余时间
        if year_idx > 0:
            avg_time_per_year = elapsed / (year_idx + 1)
            eta_seconds = avg_time_per_year * remaining_years
            eta_str = format_time(eta_seconds)
        else:
            eta_str = "计算中..."

        log_message(f"\n  [年度汇总]")
        log_message(f"    本年耗时: {format_time(year_time)}")
        log_message(f"    累计论文: {total_processed:,} 篇")
        log_message(f"    平均速率: {papers_per_sec:.0f} 篇/秒")
        log_message(f"    剩余年份: {remaining_years} 年")
        log_message(f"    预计剩余: {eta_str}")

        # 内存监控
        mem_gb = get_memory_usage_gb()
        stats = get_state_memory_stats(state)
        log_message(f"    内存: {mem_gb:.1f}GB | cooc={stats['cooc_counts']}")

        # PCA 模型状态
        pca_info = state.regular_space_model.explained_variance_info
        if pca_info:
            log_message(f"    PCA状态: k={pca_info.get('k', '?')}, "
                       f"var={pca_info.get('cumulative_variance', 0):.1%}, "
                       f"n={pca_info.get('n_samples', 0):,}, "
                       f"degraded={pca_info.get('degraded', True)}")

    # 完成
    total_time = time.time() - start_time

    log_message("\n" + "=" * 70)
    log_message("处理完成!")
    log_message("=" * 70)
    log_message(f"总论文数: {total_processed:,}")
    log_message(f"总耗时: {format_time(total_time)}")
    log_message(f"平均速率: {total_processed/total_time:.0f} 篇/秒")
    log_message(f"输出目录: {OUTPUT_DIR}")

    # 最终统计
    log_message("\n最终 PCA 模型状态:")
    pca_info = state.regular_space_model.explained_variance_info
    log_message(f"  主成分数 k: {pca_info.get('k', '?')}")
    log_message(f"  累计解释方差: {pca_info.get('cumulative_variance', 0):.2%}")
    log_message(f"  累计样本数: {pca_info.get('n_samples', 0):,}")
    log_message(f"  降级模式: {pca_info.get('degraded', True)}")

    # 各年度统计
    log_message("\n各年度处理统计:")
    log_message(f"{'年份':>6} {'论文数':>12} {'耗时':>10} {'速率':>12} {'文件大小':>10}")
    log_message("-" * 56)
    for year in completed_years:
        stats = year_stats.get(str(year), {})
        papers = stats.get('papers', 0)
        t = stats.get('time', 0)
        rate = papers / t if t > 0 else 0
        size = stats.get('file_size_mb', 0)
        log_message(f"{year:>6} {papers:>12,} {format_time(t):>10} {rate:>10.0f}/s {size:>8.1f}MB")

    log_message(f"\n检查点文件: {CHECKPOINT_FILE}")
    log_message(f"日志文件: {LOG_FILE}")


if __name__ == "__main__":
    main()

