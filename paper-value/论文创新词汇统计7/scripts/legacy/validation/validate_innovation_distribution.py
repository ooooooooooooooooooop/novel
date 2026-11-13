# -*- coding: utf-8 -*-
"""
创新度结果验证脚本 - P0 检查

1. 分布检查：每年度的均值/中位数/标准差/偏度/峰度
2. 年度趋势：检测系统性通胀

输出：控制台报告 + validation_report.json
"""

import json
import os
import numpy as np
from scipy import stats
from collections import defaultdict
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import load_project_config, get_paths, get_runtime, get_years

_cfg = load_project_config()
_paths = get_paths(_cfg)
_runtime = get_runtime(_cfg)
OUTPUT_DIR = _paths["innovation_output_dir"]
DEFAULT_YEARS = list(get_years(_runtime))


def apply_config(config_path: str = None):
    global OUTPUT_DIR, DEFAULT_YEARS
    cfg = load_project_config(config_path)
    paths = get_paths(cfg)
    runtime = get_runtime(cfg)
    OUTPUT_DIR = paths["innovation_output_dir"]
    DEFAULT_YEARS = list(get_years(runtime))

def load_year_scores(year: int) -> dict:
    """加载指定年份的所有分数"""
    filepath = os.path.join(OUTPUT_DIR, f"innovation_v2_{year}.jsonl")
    if not os.path.exists(filepath):
        return None

    scores = {
        'total_score_v2': [],
        's_peak': [],
        's_synergy': [],
        's_bonus': [],
        'score_v2': [],
        'innovation_magnitude': [],
    }

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
                for key in scores:
                    if key in r:
                        scores[key].append(r[key])
            except:
                continue

    return scores


def compute_distribution_stats(values: list) -> dict:
    """计算分布统计量"""
    if not values:
        return None

    arr = np.array(values)

    return {
        'count': len(arr),
        'mean': float(np.mean(arr)),
        'median': float(np.median(arr)),
        'std': float(np.std(arr)),
        'min': float(np.min(arr)),
        'max': float(np.max(arr)),
        'p25': float(np.percentile(arr, 25)),
        'p75': float(np.percentile(arr, 75)),
        'p95': float(np.percentile(arr, 95)),
        'p99': float(np.percentile(arr, 99)),
        'skewness': float(stats.skew(arr)),
        'kurtosis': float(stats.kurtosis(arr)),
        # 零值比例（可能表示无效数据）
        'zero_ratio': float(np.sum(arr == 0) / len(arr)),
    }


def check_anomalies(year_stats: dict) -> list:
    """检测异常年份"""
    anomalies = []

    years = sorted(year_stats.keys())
    if len(years) < 3:
        return anomalies

    # 提取各年的统计量
    means = [year_stats[y]['total_score_v2']['mean'] for y in years]
    stds = [year_stats[y]['total_score_v2']['std'] for y in years]

    # 计算全局均值和标准差的均值
    global_mean = np.mean(means)
    global_std_of_means = np.std(means)

    for i, year in enumerate(years):
        issues = []

        # 检查1: 均值异常偏离
        if global_std_of_means > 0:
            z_score = (means[i] - global_mean) / global_std_of_means
            if abs(z_score) > 2.5:
                issues.append(f"均值异常偏离 (z={z_score:.2f})")

        # 检查2: 标准差过小（区分力丧失）
        if stds[i] < 0.5:
            issues.append(f"标准差过小 ({stds[i]:.3f})，区分力不足")

        # 检查3: 零值比例过高
        zero_ratio = year_stats[year]['total_score_v2']['zero_ratio']
        if zero_ratio > 0.1:
            issues.append(f"零值比例过高 ({zero_ratio:.1%})")

        # 检查4: 极端偏度
        skew = year_stats[year]['total_score_v2']['skewness']
        if abs(skew) > 2:
            issues.append(f"偏度异常 ({skew:.2f})")

        if issues:
            anomalies.append({'year': year, 'issues': issues})

    return anomalies


def analyze_trend(year_stats: dict) -> dict:
    """分析年度趋势，检测通胀"""
    years = sorted(year_stats.keys())

    means = [year_stats[y]['total_score_v2']['mean'] for y in years]
    medians = [year_stats[y]['total_score_v2']['median'] for y in years]
    stds = [year_stats[y]['total_score_v2']['std'] for y in years]

    # 线性回归检测趋势
    x = np.arange(len(years))

    # 均值趋势
    slope_mean, intercept_mean, r_mean, p_mean, _ = stats.linregress(x, means)

    # 标准差趋势
    slope_std, intercept_std, r_std, p_std, _ = stats.linregress(x, stds)

    # 判断通胀类型
    inflation_type = "unknown"
    if p_mean < 0.05:  # 统计显著
        if slope_mean > 0:
            if slope_std >= 0:
                inflation_type = "strong_inflation"  # 均值上升 + 方差稳定/扩大
            else:
                inflation_type = "compression_inflation"  # 均值上升 + 方差缩小（最需要归一化）
        else:
            inflation_type = "deflation"
    else:
        inflation_type = "stable"  # 无显著趋势

    return {
        'years': years,
        'means': means,
        'medians': medians,
        'stds': stds,
        'trend_analysis': {
            'mean_slope': float(slope_mean),
            'mean_r_squared': float(r_mean ** 2),
            'mean_p_value': float(p_mean),
            'std_slope': float(slope_std),
            'std_r_squared': float(r_std ** 2),
            'std_p_value': float(p_std),
            'inflation_type': inflation_type,
            'zscore_required': inflation_type in ['strong_inflation', 'compression_inflation'],
        }
    }


def print_report(year_stats: dict, trend: dict, anomalies: list):
    """打印验证报告"""
    print("=" * 80)
    print("创新度结果验证报告 - P0 检查")
    print("=" * 80)

    # 1. 分布检查
    print("\n" + "=" * 80)
    print("1. 年度分布统计 (total_score_v2)")
    print("=" * 80)
    print(f"{'年份':>6} {'论文数':>12} {'均值':>8} {'中位数':>8} {'标准差':>8} {'偏度':>8} {'峰度':>8} {'零值%':>8}")
    print("-" * 80)

    for year in sorted(year_stats.keys()):
        s = year_stats[year]['total_score_v2']
        print(f"{year:>6} {s['count']:>12,} {s['mean']:>8.3f} {s['median']:>8.3f} "
              f"{s['std']:>8.3f} {s['skewness']:>8.2f} {s['kurtosis']:>8.2f} {s['zero_ratio']*100:>7.1f}%")

    # 2. 异常检测
    print("\n" + "=" * 80)
    print("2. 异常检测")
    print("=" * 80)
    if anomalies:
        for a in anomalies:
            print(f"  [{a['year']}] {', '.join(a['issues'])}")
    else:
        print("  未检测到明显异常")

    # 3. 年度趋势
    print("\n" + "=" * 80)
    print("3. 年度趋势分析")
    print("=" * 80)
    t = trend['trend_analysis']
    print(f"  均值趋势斜率: {t['mean_slope']:.4f} (R²={t['mean_r_squared']:.3f}, p={t['mean_p_value']:.4f})")
    print(f"  标准差趋势斜率: {t['std_slope']:.4f} (R²={t['std_r_squared']:.3f}, p={t['std_p_value']:.4f})")
    print(f"  通胀类型: {t['inflation_type']}")
    print(f"  是否需要 Z-Score 归一化: {'是' if t['zscore_required'] else '否'}")

    # 4. 结论
    print("\n" + "=" * 80)
    print("4. 结论")
    print("=" * 80)

    has_critical_issue = False

    # 检查是否有严重问题
    for year in year_stats:
        s = year_stats[year]['total_score_v2']
        if s['std'] < 0.3:
            print(f"  [严重] {year} 年标准差过小 ({s['std']:.3f})，创新度失去区分力")
            has_critical_issue = True
        if s['zero_ratio'] > 0.2:
            print(f"  [严重] {year} 年零值比例过高 ({s['zero_ratio']:.1%})")
            has_critical_issue = True

    if anomalies:
        print(f"  [警告] 检测到 {len(anomalies)} 个年份存在异常")

    if t['zscore_required']:
        print(f"  [建议] 检测到系统性通胀，Phase 5 的 Z-Score 归一化是必要的")

    if not has_critical_issue and not anomalies:
        print("  [通过] 分布形态健康，未发现结构性错误")


def main():
    parser = argparse.ArgumentParser(description="validate innovation distribution")
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

    print("加载各年度数据...")

    year_stats = {}

    for year in years:
        scores = load_year_scores(year)
        if scores is None:
            print(f"  {year}: 文件不存在，跳过")
            continue

        stats_dict = {}
        for key, values in scores.items():
            if values:
                stats_dict[key] = compute_distribution_stats(values)

        year_stats[year] = stats_dict
        print(f"  {year}: {stats_dict['total_score_v2']['count']:,} 篇")

    if not year_stats:
        print("没有找到任何数据文件")
        return

    # 异常检测
    anomalies = check_anomalies(year_stats)

    # 趋势分析
    trend = analyze_trend(year_stats)

    # 打印报告
    print_report(year_stats, trend, anomalies)

    # 保存完整报告
    report = {
        'year_stats': year_stats,
        'anomalies': anomalies,
        'trend': trend,
    }

    report_path = os.path.join(OUTPUT_DIR, "validation_report.json")
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n完整报告已保存: {report_path}")


if __name__ == "__main__":
    main()
