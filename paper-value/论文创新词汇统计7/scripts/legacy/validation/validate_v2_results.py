# -*- coding: utf-8 -*-
"""
V2 创新度评分结果验证脚本

验证内容：
1. 各信号分布统计
2. 高分/低分论文抽检
3. 论文类型权重验证
4. 年度趋势分析
"""

import json
import sqlite3
import os
import numpy as np
from collections import defaultdict, Counter
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import load_project_config, get_paths, get_runtime, get_years

_cfg = load_project_config()
_paths = get_paths(_cfg)
_runtime = get_runtime(_cfg)
DB_PATH = _paths["rpu_db_path"]
OUTPUT_DIR = _paths["innovation_output_dir"]
DEFAULT_YEARS = list(get_years(_runtime))


def apply_config(config_path: str = None):
    global DB_PATH, OUTPUT_DIR, DEFAULT_YEARS
    cfg = load_project_config(config_path)
    paths = get_paths(cfg)
    runtime = get_runtime(cfg)
    DB_PATH = paths["rpu_db_path"]
    OUTPUT_DIR = paths["innovation_output_dir"]
    DEFAULT_YEARS = list(get_years(runtime))


def load_year_results(year: int) -> list:
    """加载指定年份的结果"""
    file_path = os.path.join(OUTPUT_DIR, f"innovation_v2_{year}.jsonl")
    if not os.path.exists(file_path):
        return []

    results = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            results.append(json.loads(line))
    return results


def get_paper_info(paper_id: str) -> dict:
    """从数据库获取论文信息"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT paper_id, title, pub_year FROM papers WHERE paper_id = ?", (paper_id,))
    row = cur.fetchone()

    cur.execute("SELECT task, object, aspect, task_cores, object_cores FROM rpu WHERE paper_id = ?", (paper_id,))
    rpus = cur.fetchall()

    conn.close()

    if row:
        return {
            'paper_id': row['paper_id'],
            'title': row['title'],
            'pub_year': row['pub_year'],
            'rpus': [dict(r) for r in rpus]
        }
    return None


def analyze_distribution(results: list, year: int):
    """分析各信号的分布"""
    signals = ['s_peak', 's_synergy', 's_bonus', 'score_v2', 'total_score_v2', 'innovation_magnitude']

    print(f"\n{'='*60}")
    print(f"年份 {year} 分布统计 ({len(results):,} 篇论文)")
    print(f"{'='*60}")

    for signal in signals:
        values = [r.get(signal, 0) or 0 for r in results]
        values = np.array(values)

        print(f"\n{signal}:")
        print(f"  均值: {np.mean(values):.4f}")
        print(f"  标准差: {np.std(values):.4f}")
        print(f"  最小值: {np.min(values):.4f}")
        print(f"  最大值: {np.max(values):.4f}")
        print(f"  中位数: {np.median(values):.4f}")
        print(f"  25%分位: {np.percentile(values, 25):.4f}")
        print(f"  75%分位: {np.percentile(values, 75):.4f}")
        print(f"  99%分位: {np.percentile(values, 99):.4f}")

        # 检查异常值
        zero_count = np.sum(values == 0)
        if zero_count > 0:
            print(f"  零值数量: {zero_count:,} ({100*zero_count/len(values):.1f}%)")


def analyze_paper_types(results: list, year: int):
    """分析论文类型分布及其分数"""
    print(f"\n{'='*60}")
    print(f"年份 {year} 论文类型分析")
    print(f"{'='*60}")

    type_stats = defaultdict(lambda: {'count': 0, 'scores': []})

    for r in results:
        ptype = r.get('paper_type_detected', 'unknown')
        score = r.get('total_score_v2', 0)
        type_stats[ptype]['count'] += 1
        type_stats[ptype]['scores'].append(score)

    print(f"\n{'类型':<15} {'数量':>10} {'占比':>8} {'平均分':>10} {'中位数':>10}")
    print("-" * 60)

    for ptype in sorted(type_stats.keys(), key=lambda x: type_stats[x]['count'], reverse=True):
        stats = type_stats[ptype]
        count = stats['count']
        scores = np.array(stats['scores'])
        pct = 100 * count / len(results)
        mean_score = np.mean(scores)
        median_score = np.median(scores)
        print(f"{ptype:<15} {count:>10,} {pct:>7.2f}% {mean_score:>10.2f} {median_score:>10.2f}")

    # 验证预期：erratum < editorial < commentary < review < original
    expected_order = ['erratum', 'editorial', 'commentary', 'review', 'case_report', 'original']
    print(f"\n类型权重验证 (预期: erratum < review < original):")
    prev_score = -float('inf')
    for ptype in expected_order:
        if ptype in type_stats:
            mean_score = np.mean(type_stats[ptype]['scores'])
            status = "✓" if mean_score >= prev_score else "✗"
            print(f"  {status} {ptype}: {mean_score:.2f}")
            prev_score = mean_score


def sample_extreme_papers(results: list, year: int, n: int = 5):
    """抽检高分和低分论文"""
    print(f"\n{'='*60}")
    print(f"年份 {year} 极值论文抽检")
    print(f"{'='*60}")

    # 按 total_score_v2 排序
    sorted_results = sorted(results, key=lambda x: x.get('total_score_v2', 0), reverse=True)

    print(f"\n--- Top {n} 高分论文 ---")
    for i, r in enumerate(sorted_results[:n]):
        paper_info = get_paper_info(r['paper_id'])
        print(f"\n{i+1}. [总分: {r['total_score_v2']:.2f}]")
        print(f"   ID: {r['paper_id']}")
        if paper_info:
            print(f"   标题: {paper_info['title'][:100]}..." if len(paper_info['title'] or '') > 100 else f"   标题: {paper_info['title']}")
        print(f"   s_peak: {r['s_peak']:.2f} | s_synergy: {r['s_synergy']:.2f} | s_bonus: {r['s_bonus']:.2f} | score_v2: {r['score_v2']:.2f}")
        print(f"   peak_trigger: {r.get('peak_trigger', 'N/A')}")
        print(f"   synergy_trigger: {r.get('synergy_trigger', 'N/A')}")
        print(f"   类型: {r.get('paper_type_detected', 'N/A')}")

    # 过滤掉 original 类型后的低分
    original_results = [r for r in sorted_results if r.get('paper_type_detected') == 'original']
    low_results = original_results[-n:][::-1]

    print(f"\n--- Bottom {n} 低分论文 (仅 original 类型) ---")
    for i, r in enumerate(low_results):
        paper_info = get_paper_info(r['paper_id'])
        print(f"\n{i+1}. [总分: {r['total_score_v2']:.2f}]")
        print(f"   ID: {r['paper_id']}")
        if paper_info:
            print(f"   标题: {paper_info['title'][:100]}..." if len(paper_info['title'] or '') > 100 else f"   标题: {paper_info['title']}")
        print(f"   s_peak: {r['s_peak']:.2f} | s_synergy: {r['s_synergy']:.2f} | s_bonus: {r['s_bonus']:.2f} | score_v2: {r['score_v2']:.2f}")
        print(f"   peak_trigger: {r.get('peak_trigger', 'N/A')}")


def analyze_yearly_trends(years: list):
    """分析年度趋势（流式读取，避免内存问题）"""
    print(f"\n{'='*60}")
    print("年度趋势分析")
    print(f"{'='*60}")

    yearly_stats = []

    for year in years:
        file_path = os.path.join(OUTPUT_DIR, f"innovation_v2_{year}.jsonl")
        if not os.path.exists(file_path):
            continue

        # 流式读取，只保留分数
        scores = []
        count = 0
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    r = json.loads(line)
                    scores.append(r.get('total_score_v2', 0) or 0)
                    count += 1
                except:
                    pass

        if not scores:
            continue

        scores = np.array(scores)

        # 高分论文比例（总分 > 50）
        high_score_pct = 100 * np.sum(scores > 50) / len(scores)

        yearly_stats.append({
            'year': year,
            'count': count,
            'mean': np.mean(scores),
            'median': np.median(scores),
            'std': np.std(scores),
            'p99': np.percentile(scores, 99),
            'high_pct': high_score_pct
        })

    print(f"\n{'年份':>6} {'论文数':>12} {'均值':>8} {'中位数':>8} {'标准差':>8} {'99分位':>8} {'高分%':>8}")
    print("-" * 70)

    for s in yearly_stats:
        print(f"{s['year']:>6} {s['count']:>12,} {s['mean']:>8.2f} {s['median']:>8.2f} "
              f"{s['std']:>8.2f} {s['p99']:>8.2f} {s['high_pct']:>7.2f}%")


def check_data_quality(results: list, year: int):
    """数据质量检查"""
    print(f"\n{'='*60}")
    print(f"年份 {year} 数据质量检查")
    print(f"{'='*60}")

    issues = []

    # 检查空值
    null_counts = defaultdict(int)
    for r in results:
        for key in ['s_peak', 's_synergy', 's_bonus', 'total_score_v2']:
            if r.get(key) is None:
                null_counts[key] += 1

    if null_counts:
        print("\n空值检查:")
        for key, count in null_counts.items():
            print(f"  {key}: {count} 个空值")
            issues.append(f"{key} 有 {count} 个空值")
    else:
        print("\n✓ 无空值")

    # 检查异常值
    total_scores = [r.get('total_score_v2', 0) or 0 for r in results]
    negative_count = sum(1 for s in total_scores if s < 0)
    if negative_count > 0:
        print(f"\n⚠ 负分论文: {negative_count} 篇")
        issues.append(f"{negative_count} 篇负分论文")
    else:
        print("✓ 无负分")

    # 检查 v2_degraded 比例
    degraded_count = sum(1 for r in results if r.get('v2_degraded'))
    if degraded_count > 0:
        pct = 100 * degraded_count / len(results)
        print(f"\n⚠ PCA 降级模式: {degraded_count} 篇 ({pct:.2f}%)")
    else:
        print("✓ 无 PCA 降级")

    # 检查 synergy 为 0 的比例
    zero_synergy = sum(1 for r in results if (r.get('s_synergy') or 0) == 0)
    zero_pct = 100 * zero_synergy / len(results)
    print(f"\nSynergy=0 比例: {zero_synergy:,} 篇 ({zero_pct:.1f}%)")

    if issues:
        print(f"\n⚠ 发现 {len(issues)} 个问题")
    else:
        print("\n✓ 数据质量良好")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="V2 result validation")
    parser.add_argument("--year", type=int, default=None, help="year to validate")
    parser.add_argument("--all-years", action="store_true", help="analyze all years")
    parser.add_argument("--sample", type=int, default=5, help="sample size")
    parser.add_argument("--config", type=str, default=None, help="JSON config override path")
    parser.add_argument("--year-start", type=int, default=None, help="override start year")
    parser.add_argument("--year-end", type=int, default=None, help="override end year")
    args = parser.parse_args()
    apply_config(args.config)

    years = list(DEFAULT_YEARS)
    if args.year_start is not None or args.year_end is not None:
        if not years:
            years = list(range(2010, 2026))
        start = args.year_start if args.year_start is not None else years[0]
        end = args.year_end if args.year_end is not None else years[-1]
        years = list(range(start, end + 1))

    if args.all_years:
        analyze_yearly_trends(years)
    else:
        target_year = args.year if args.year is not None else (2020 if 2020 in years else years[0])
        results = load_year_results(target_year)
        if not results:
            print(f"无法加载 {target_year} 年的结果")
            return

        analyze_distribution(results, target_year)
        analyze_paper_types(results, target_year)
        check_data_quality(results, target_year)
        sample_extreme_papers(results, target_year, args.sample)


if __name__ == "__main__":
    main()
