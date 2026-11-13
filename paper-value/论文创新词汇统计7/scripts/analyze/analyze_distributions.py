# -*- coding: utf-8 -*-
"""
Phase 5.2: 分布分析

1. 年度分类比例趋势
2. Innovation vs Impact 散点图（验证正交性）
3. 分类标签与论文类型交叉分析
4. 相关性分析
"""

import os
import sys
import json
import argparse
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict
from datetime import datetime
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import load_project_config, get_paths, get_runtime, get_years

# 配置
_cfg = load_project_config()
_paths = get_paths(_cfg)
_runtime = get_runtime(_cfg)
CONFIG = {
    'input_dir': _paths['paper_signals_output_dir'],
    'output_dir': _paths['analysis_output_dir'],
    'years': get_years(_runtime),
}


def apply_config(config_path: str = None):
    cfg = load_project_config(config_path)
    paths = get_paths(cfg)
    runtime = get_runtime(cfg)
    CONFIG.update({
        'input_dir': paths['paper_signals_output_dir'],
        'output_dir': paths['analysis_output_dir'],
        'years': get_years(runtime),
    })

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# 中文标签映射
ROLE_CN = {
    'Pioneer': '先驱者',
    'Ahead-of-time': '超前者',
    'Diffuser': '传播者',
    'Routine': '常规者'
}

TYPE_CN = {
    'original': '原创论文',
    'review': '综述',
    'editorial': '社论',
    'commentary': '评论',
    'erratum': '勘误',
    'letter': '通讯'
}


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def load_year_data(year: int):
    """加载单年数据"""
    path = os.path.join(CONFIG['input_dir'], f'paper_signals_{year}.jsonl')
    if not os.path.exists(path):
        return []
    data = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                data.append(json.loads(line.strip()))
            except:
                continue
    return data


def analyze_yearly_trends():
    """1. 年度分类比例趋势"""
    log("Analyzing yearly trends...")

    years = []
    role_data = {role: [] for role in ['Pioneer', 'Ahead-of-time', 'Diffuser', 'Routine']}
    paper_counts = []

    for year in CONFIG['years']:
        data = load_year_data(year)
        if not data:
            continue

        years.append(year)
        paper_counts.append(len(data))

        role_counts = defaultdict(int)
        for d in data:
            role_counts[d.get('role', 'Unknown')] += 1

        total = len(data)
        for role in role_data:
            role_data[role].append(100 * role_counts[role] / total)

    # 绘图
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

    # 上图：分类比例堆叠面积图
    colors = {'Pioneer': '#e74c3c', 'Ahead-of-time': '#f39c12',
              'Diffuser': '#3498db', 'Routine': '#95a5a6'}

    bottom = np.zeros(len(years))
    for role in ['Routine', 'Diffuser', 'Ahead-of-time', 'Pioneer']:
        ax1.fill_between(years, bottom, bottom + role_data[role],
                        label=ROLE_CN[role], color=colors[role], alpha=0.8)
        bottom += role_data[role]

    ax1.set_xlabel('年份')
    ax1.set_ylabel('比例 (%)')
    ax1.set_title('论文分类分布年度趋势')
    ax1.legend(loc='upper right')
    ax1.set_xlim(years[0], years[-1])
    ax1.set_ylim(0, 100)
    ax1.grid(True, alpha=0.3)

    # 下图：论文数量趋势
    ax2.bar(years, [c/1e6 for c in paper_counts], color='#2ecc71', alpha=0.7)
    ax2.set_xlabel('年份')
    ax2.set_ylabel('论文数量 (百万)')
    ax2.set_title('各年度论文总量')
    ax2.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(os.path.join(CONFIG['output_dir'], 'yearly_trends.png'), dpi=150)
    plt.close()

    log(f"  Saved: yearly_trends.png")
    return years, role_data


def analyze_scatter_correlation(sample_size=100000):
    """2. Innovation vs Impact 散点图 + 相关性分析"""
    log(f"Analyzing Innovation-Impact correlation (sample={sample_size:,})...")

    # 收集数据（采样避免内存问题）
    all_innovation = []
    all_impact = []
    all_roles = []

    np.random.seed(42)
    for year in CONFIG['years']:
        data = load_year_data(year)
        if not data:
            continue

        # 按比例采样
        n_sample = min(len(data), sample_size // len(list(CONFIG['years'])))
        indices = np.random.choice(len(data), n_sample, replace=False)

        for i in indices:
            d = data[i]
            all_innovation.append(d.get('innovation_score', 0))
            all_impact.append(d.get('impact_score', 0))
            all_roles.append(d.get('role', 'Unknown'))

    innovation = np.array(all_innovation)
    impact = np.array(all_impact)
    roles = np.array(all_roles)

    # 计算相关性
    # 只用非零值计算相关性更有意义
    nonzero_mask = (innovation > 0) & (impact > 0)
    if nonzero_mask.sum() > 100:
        corr_pearson, p_pearson = stats.pearsonr(innovation[nonzero_mask], impact[nonzero_mask])
        corr_spearman, p_spearman = stats.spearmanr(innovation[nonzero_mask], impact[nonzero_mask])
    else:
        corr_pearson, corr_spearman = 0, 0

    log(f"  Pearson r = {corr_pearson:.4f}, Spearman rho = {corr_spearman:.4f}")

    # 绘制散点图
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # 左图：全局散点图（带密度）
    ax1 = axes[0]
    colors = {'Pioneer': '#e74c3c', 'Ahead-of-time': '#f39c12',
              'Diffuser': '#3498db', 'Routine': '#95a5a6'}

    for role in ['Routine', 'Diffuser', 'Ahead-of-time', 'Pioneer']:
        mask = roles == role
        ax1.scatter(innovation[mask], impact[mask],
                   c=colors[role], label=ROLE_CN[role], alpha=0.3, s=5)

    ax1.set_xlabel('创新度分数')
    ax1.set_ylabel('影响力分数')
    ax1.set_title(f'创新度 vs 影响力 (n={len(innovation):,})\n'
                  f'Pearson r={corr_pearson:.3f}, Spearman ρ={corr_spearman:.3f}')
    ax1.legend(loc='upper right', markerscale=3)
    ax1.grid(True, alpha=0.3)

    # 右图：分类边界可视化
    ax2 = axes[1]

    # 画四象限
    innov_median = np.percentile(innovation, 70)
    impact_median = np.percentile(impact, 70)

    ax2.axvline(x=innov_median, color='black', linestyle='--', alpha=0.5)
    ax2.axhline(y=impact_median, color='black', linestyle='--', alpha=0.5)

    # 标注四象限
    ax2.text(innov_median * 1.5, impact_median * 1.5, '先驱者', fontsize=12, fontweight='bold')
    ax2.text(innov_median * 1.5, impact_median * 0.3, '超前者', fontsize=12, fontweight='bold')
    ax2.text(innov_median * 0.3, impact_median * 1.5, '传播者', fontsize=12, fontweight='bold')
    ax2.text(innov_median * 0.3, impact_median * 0.3, '常规者', fontsize=12, fontweight='bold')

    # 绘制散点
    ax2.scatter(innovation, impact, c='gray', alpha=0.1, s=3)

    ax2.set_xlabel('创新度分数')
    ax2.set_ylabel('影响力分数')
    ax2.set_title(f'四象限分类边界\nP70阈值: 创新度={innov_median:.1f}, 影响力={impact_median:.1f}')
    ax2.set_xlim(0, 100)
    ax2.set_ylim(0, 100)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(CONFIG['output_dir'], 'innovation_impact_scatter.png'), dpi=150)
    plt.close()

    log(f"  Saved: innovation_impact_scatter.png")

    return {
        'pearson_r': corr_pearson,
        'spearman_rho': corr_spearman,
        'sample_size': len(innovation),
        'nonzero_count': int(nonzero_mask.sum()),
    }


def analyze_paper_type_cross():
    """3. 分类标签与论文类型交叉分析"""
    log("Analyzing paper type cross-tabulation...")

    # 收集交叉统计
    cross_table = defaultdict(lambda: defaultdict(int))
    type_totals = defaultdict(int)
    role_totals = defaultdict(int)

    for year in CONFIG['years']:
        data = load_year_data(year)
        for d in data:
            ptype = d.get('paper_type', 'unknown')
            role = d.get('role', 'Unknown')
            cross_table[ptype][role] += 1
            type_totals[ptype] += 1
            role_totals[role] += 1

    # 只保留主要论文类型
    main_types = ['original', 'review', 'editorial', 'commentary', 'erratum', 'letter']
    main_types = [t for t in main_types if type_totals.get(t, 0) > 1000]

    # 计算百分比
    print("\n" + "=" * 70)
    print("论文类型 × 分类 交叉统计表")
    print("=" * 70)
    print(f"\n{'类型':<12} {'总数':>12} {'先驱者':>10} {'超前者':>10} {'传播者':>10} {'常规者':>10}")
    print("-" * 70)

    cross_pct = {}
    for ptype in main_types:
        total = type_totals[ptype]
        pcts = {}
        for role in ['Pioneer', 'Ahead-of-time', 'Diffuser', 'Routine']:
            pcts[role] = 100 * cross_table[ptype][role] / total if total > 0 else 0
        cross_pct[ptype] = pcts

        type_cn = TYPE_CN.get(ptype, ptype)
        print(f"{type_cn:<12} {total:>12,} "
              f"{pcts['Pioneer']:>9.1f}% "
              f"{pcts['Ahead-of-time']:>9.1f}% "
              f"{pcts['Diffuser']:>9.1f}% "
              f"{pcts['Routine']:>9.1f}%")

    # 绘制热力图
    fig, ax = plt.subplots(figsize=(10, 6))

    roles = ['Pioneer', 'Ahead-of-time', 'Diffuser', 'Routine']
    roles_cn = [ROLE_CN[r] for r in roles]
    data_matrix = np.array([[cross_pct[t][r] for r in roles] for t in main_types])

    im = ax.imshow(data_matrix, cmap='YlOrRd', aspect='auto')

    ax.set_xticks(range(len(roles)))
    ax.set_xticklabels(roles_cn)
    ax.set_yticks(range(len(main_types)))
    ax.set_yticklabels([TYPE_CN.get(t, t) for t in main_types])

    # 添加数值标注
    for i in range(len(main_types)):
        for j in range(len(roles)):
            text = ax.text(j, i, f'{data_matrix[i, j]:.1f}%',
                          ha='center', va='center', color='black', fontsize=10)

    ax.set_title('各论文类型的分类分布 (%)')
    plt.colorbar(im, ax=ax, label='百分比')

    plt.tight_layout()
    plt.savefig(os.path.join(CONFIG['output_dir'], 'paper_type_cross.png'), dpi=150)
    plt.close()

    log(f"  Saved: paper_type_cross.png")

    return cross_pct


def analyze_score_distributions():
    """4. 分数分布分析"""
    log("Analyzing score distributions...")

    # 收集分数
    innovation_scores = []
    impact_scores = []

    for year in [2015, 2020]:  # 选取代表年份
        data = load_year_data(year)
        for d in data:
            innovation_scores.append((year, d.get('innovation_score', 0)))
            impact_scores.append((year, d.get('impact_score', 0)))

    # 绘制分布直方图
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))

    for idx, year in enumerate([2015, 2020]):
        innov = [s[1] for s in innovation_scores if s[0] == year]
        impact = [s[1] for s in impact_scores if s[0] == year]

        # Innovation 分布
        axes[0, idx].hist(innov, bins=50, color='#3498db', alpha=0.7, edgecolor='white')
        axes[0, idx].set_xlabel('创新度分数')
        axes[0, idx].set_ylabel('论文数量')
        axes[0, idx].set_title(f'创新度分布 ({year}年)')
        axes[0, idx].axvline(np.percentile(innov, 70), color='red', linestyle='--',
                            label=f'P70={np.percentile(innov, 70):.1f}')
        axes[0, idx].legend()

        # Impact 分布
        axes[1, idx].hist(impact, bins=50, color='#e74c3c', alpha=0.7, edgecolor='white')
        axes[1, idx].set_xlabel('影响力分数')
        axes[1, idx].set_ylabel('论文数量')
        axes[1, idx].set_title(f'影响力分布 ({year}年)')
        axes[1, idx].axvline(np.percentile(impact, 70), color='blue', linestyle='--',
                            label=f'P70={np.percentile(impact, 70):.1f}')
        axes[1, idx].legend()

    plt.tight_layout()
    plt.savefig(os.path.join(CONFIG['output_dir'], 'score_distributions.png'), dpi=150)
    plt.close()

    log(f"  Saved: score_distributions.png")


def main():
    parser = argparse.ArgumentParser(description="Phase 5.2 Distribution Analysis")
    parser.add_argument("--sample", type=int, default=100000, help="Sample size for scatter plot")
    parser.add_argument("--config", type=str, default=None, help="配置文件路径（JSON）")
    args = parser.parse_args()
    apply_config(args.config)

    # 创建输出目录
    os.makedirs(CONFIG['output_dir'], exist_ok=True)

    print("=" * 60)
    print("Phase 5.2: Distribution Analysis")
    print("=" * 60)
    print()

    # 1. 年度趋势
    years, role_data = analyze_yearly_trends()

    # 2. 散点图 + 相关性
    corr_stats = analyze_scatter_correlation(args.sample)

    # 3. 论文类型交叉分析
    cross_pct = analyze_paper_type_cross()

    # 4. 分数分布
    analyze_score_distributions()

    # 保存分析结果
    results = {
        'generated_at': datetime.now().isoformat(),
        'correlation': corr_stats,
        'cross_tabulation': cross_pct,
    }

    with open(os.path.join(CONFIG['output_dir'], 'analysis_results.json'), 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"\nCorrelation (Innovation vs Impact):")
    print(f"  Pearson r  = {corr_stats['pearson_r']:.4f}")
    print(f"  Spearman ρ = {corr_stats['spearman_rho']:.4f}")
    print(f"\nOutput files saved to: {CONFIG['output_dir']}")
    print("=" * 60 + "\nDone\n")


if __name__ == "__main__":
    main()
