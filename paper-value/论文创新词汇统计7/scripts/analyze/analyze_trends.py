# -*- coding: utf-8 -*-
"""
Phase 5.3: 趋势可视化

1. 年度 Impact 分布变化
2. 分类比例时序趋势
3. 阈值演化趋势
4. 高影响力论文特征分析
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
    'stats_file': os.path.join(_paths['paper_signals_output_dir'], 'merge_stats.json'),
    'output_dir': _paths['analysis_output_dir'],
    'years': get_years(_runtime),
}


def apply_config(config_path: str = None):
    cfg = load_project_config(config_path)
    paths = get_paths(cfg)
    runtime = get_runtime(cfg)
    CONFIG.update({
        'input_dir': paths['paper_signals_output_dir'],
        'stats_file': os.path.join(paths['paper_signals_output_dir'], 'merge_stats.json'),
        'output_dir': paths['analysis_output_dir'],
        'years': get_years(runtime),
    })

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# 中文标签
ROLE_CN = {
    'Pioneer': '先驱者',
    'Ahead-of-time': '超前者',
    'Diffuser': '传播者',
    'Routine': '常规者'
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


def load_merge_stats():
    """加载合并统计数据"""
    with open(CONFIG['stats_file'], 'r', encoding='utf-8') as f:
        return json.load(f)


def plot_impact_distribution_evolution():
    """1. 年度 Impact 分布演化"""
    log("Plotting Impact distribution evolution...")

    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    axes = axes.flatten()

    selected_years = [2010, 2013, 2016, 2019, 2022, 2025]

    for idx, year in enumerate(selected_years):
        data = load_year_data(year)
        if not data:
            continue

        impacts = [d.get('impact_score', 0) for d in data]

        ax = axes[idx]

        # 使用对数分箱更好展示长尾分布
        bins = np.concatenate([[0], np.logspace(-1, 2, 50)])
        ax.hist(impacts, bins=bins, color='#e74c3c', alpha=0.7, edgecolor='white')
        ax.set_xscale('symlog', linthresh=1)
        ax.set_xlabel('影响力分数')
        ax.set_ylabel('论文数量')
        ax.set_title(f'{year}年 (n={len(data):,})')

        # 添加统计信息
        mean_val = np.mean(impacts)
        p70 = np.percentile(impacts, 70)
        ax.axvline(p70, color='blue', linestyle='--', alpha=0.7, label=f'P70={p70:.1f}')
        ax.legend(fontsize=8)

    plt.suptitle('影响力分数分布年度演化', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(CONFIG['output_dir'], 'impact_evolution.png'), dpi=150)
    plt.close()
    log("  Saved: impact_evolution.png")


def plot_threshold_trends():
    """2. 阈值演化趋势"""
    log("Plotting threshold trends...")

    stats = load_merge_stats()

    years = []
    innov_thresholds = []
    impact_thresholds = []
    paper_counts = []

    for year_stat in stats['years']:
        if year_stat['status'] != 'ok':
            continue
        years.append(year_stat['year'])
        innov_thresholds.append(year_stat['thresholds']['innovation_p70'])
        impact_thresholds.append(year_stat['thresholds']['impact_p70'])
        paper_counts.append(year_stat['total'])

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 左上：创新度阈值趋势
    ax1 = axes[0, 0]
    ax1.plot(years, innov_thresholds, 'b-o', linewidth=2, markersize=6)
    ax1.fill_between(years, innov_thresholds, alpha=0.3)
    ax1.set_xlabel('年份')
    ax1.set_ylabel('P70 阈值')
    ax1.set_title('创新度 P70 阈值年度趋势')
    ax1.grid(True, alpha=0.3)

    # 添加趋势说明
    ax1.annotate(f'从 {innov_thresholds[0]:.1f} 升至 {innov_thresholds[-1]:.1f}',
                xy=(years[-1], innov_thresholds[-1]), fontsize=10)

    # 右上：影响力阈值趋势
    ax2 = axes[0, 1]
    ax2.plot(years, impact_thresholds, 'r-o', linewidth=2, markersize=6)
    ax2.fill_between(years, impact_thresholds, alpha=0.3, color='red')
    ax2.set_xlabel('年份')
    ax2.set_ylabel('P70 阈值')
    ax2.set_title('影响力 P70 阈值年度趋势')
    ax2.grid(True, alpha=0.3)

    # 左下：论文数量趋势
    ax3 = axes[1, 0]
    ax3.bar(years, [c/1e6 for c in paper_counts], color='#2ecc71', alpha=0.7)
    ax3.set_xlabel('年份')
    ax3.set_ylabel('论文数量 (百万)')
    ax3.set_title('年度论文总量')
    ax3.grid(True, alpha=0.3, axis='y')

    # 右下：双轴对比
    ax4 = axes[1, 1]
    ax4_twin = ax4.twinx()

    line1, = ax4.plot(years, innov_thresholds, 'b-o', label='创新度 P70')
    line2, = ax4_twin.plot(years, impact_thresholds, 'r-s', label='影响力 P70')

    ax4.set_xlabel('年份')
    ax4.set_ylabel('创新度阈值', color='blue')
    ax4_twin.set_ylabel('影响力阈值', color='red')
    ax4.set_title('创新度 vs 影响力阈值对比')
    ax4.legend(handles=[line1, line2], loc='upper right')
    ax4.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(CONFIG['output_dir'], 'threshold_trends.png'), dpi=150)
    plt.close()
    log("  Saved: threshold_trends.png")


def plot_role_trends():
    """3. 分类角色比例趋势"""
    log("Plotting role proportion trends...")

    stats = load_merge_stats()

    years = []
    role_data = {role: [] for role in ['Pioneer', 'Ahead-of-time', 'Diffuser', 'Routine']}

    for year_stat in stats['years']:
        if year_stat['status'] != 'ok':
            continue
        years.append(year_stat['year'])
        for role in role_data:
            role_data[role].append(year_stat['role_pct'][role])

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    colors = {'Pioneer': '#e74c3c', 'Ahead-of-time': '#f39c12',
              'Diffuser': '#3498db', 'Routine': '#95a5a6'}

    for idx, role in enumerate(['Pioneer', 'Ahead-of-time', 'Diffuser', 'Routine']):
        ax = axes[idx // 2, idx % 2]
        ax.plot(years, role_data[role], '-o', color=colors[role], linewidth=2, markersize=6)
        ax.fill_between(years, role_data[role], alpha=0.3, color=colors[role])
        ax.set_xlabel('年份')
        ax.set_ylabel('比例 (%)')
        ax.set_title(f'{ROLE_CN[role]}比例趋势')
        ax.grid(True, alpha=0.3)

        # 显示范围
        min_val = min(role_data[role])
        max_val = max(role_data[role])
        ax.set_ylim(min_val - 2, max_val + 2)

        # 标注异常点
        if role == 'Pioneer' and role_data[role][0] < 5:
            ax.annotate(f'{role_data[role][0]:.1f}%\n(2010异常)',
                       xy=(years[0], role_data[role][0]),
                       xytext=(years[0]+1, role_data[role][0]+3),
                       arrowprops=dict(arrowstyle='->', color='gray'),
                       fontsize=9)

    plt.suptitle('四类论文比例年度趋势', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(CONFIG['output_dir'], 'role_trends.png'), dpi=150)
    plt.close()
    log("  Saved: role_trends.png")


def plot_pioneer_analysis():
    """4. 先驱者论文特征分析"""
    log("Analyzing Pioneer papers...")

    # 收集先驱者数据
    pioneer_data = []
    for year in [2015, 2018, 2020]:  # 选取代表年份
        data = load_year_data(year)
        for d in data:
            if d.get('role') == 'Pioneer':
                pioneer_data.append(d)

    if not pioneer_data:
        log("  No Pioneer data found")
        return

    # 提取特征
    innov_scores = [d['innovation_score'] for d in pioneer_data]
    impact_scores = [d['impact_score'] for d in pioneer_data]
    object_counts = [d.get('object_count', 0) for d in pioneer_data]

    fig, axes = plt.subplots(2, 2, figsize=(12, 10))

    # 左上：创新度分布
    ax1 = axes[0, 0]
    ax1.hist(innov_scores, bins=30, color='#e74c3c', alpha=0.7, edgecolor='white')
    ax1.axvline(np.mean(innov_scores), color='black', linestyle='--',
                label=f'均值={np.mean(innov_scores):.1f}')
    ax1.set_xlabel('创新度分数')
    ax1.set_ylabel('论文数量')
    ax1.set_title('先驱者论文的创新度分布')
    ax1.legend()

    # 右上：影响力分布
    ax2 = axes[0, 1]
    ax2.hist(impact_scores, bins=30, color='#3498db', alpha=0.7, edgecolor='white')
    ax2.axvline(np.mean(impact_scores), color='black', linestyle='--',
                label=f'均值={np.mean(impact_scores):.1f}')
    ax2.set_xlabel('影响力分数')
    ax2.set_ylabel('论文数量')
    ax2.set_title('先驱者论文的影响力分布')
    ax2.legend()

    # 左下：创新度 vs 影响力散点
    ax3 = axes[1, 0]
    ax3.scatter(innov_scores, impact_scores, alpha=0.3, s=10, c='#e74c3c')
    ax3.set_xlabel('创新度分数')
    ax3.set_ylabel('影响力分数')
    ax3.set_title('先驱者: 创新度 vs 影响力')
    ax3.grid(True, alpha=0.3)

    # 右下：概念数量分布
    ax4 = axes[1, 1]
    ax4.hist(object_counts, bins=range(1, 20), color='#2ecc71', alpha=0.7, edgecolor='white')
    ax4.axvline(np.mean(object_counts), color='black', linestyle='--',
                label=f'均值={np.mean(object_counts):.1f}')
    ax4.set_xlabel('概念数量 (object_count)')
    ax4.set_ylabel('论文数量')
    ax4.set_title('先驱者论文的概念数量分布')
    ax4.legend()

    plt.suptitle(f'先驱者论文特征分析 (n={len(pioneer_data):,})', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(CONFIG['output_dir'], 'pioneer_analysis.png'), dpi=150)
    plt.close()
    log("  Saved: pioneer_analysis.png")


def plot_summary_dashboard():
    """5. 综合仪表盘"""
    log("Creating summary dashboard...")

    stats = load_merge_stats()

    fig = plt.figure(figsize=(16, 12))

    # 布局：3行2列
    ax1 = fig.add_subplot(3, 2, 1)  # 论文总量
    ax2 = fig.add_subplot(3, 2, 2)  # 分类饼图
    ax3 = fig.add_subplot(3, 2, 3)  # 阈值趋势
    ax4 = fig.add_subplot(3, 2, 4)  # 分类趋势
    ax5 = fig.add_subplot(3, 1, 3)  # 年度详情表

    years = [s['year'] for s in stats['years'] if s['status'] == 'ok']
    totals = [s['total'] for s in stats['years'] if s['status'] == 'ok']

    # 1. 论文总量柱状图
    ax1.bar(years, [t/1e6 for t in totals], color='#3498db', alpha=0.7)
    ax1.set_xlabel('年份')
    ax1.set_ylabel('论文数量 (百万)')
    ax1.set_title('年度论文总量')
    ax1.set_xticks(years[::2])

    # 2. 总体分类饼图
    total_roles = defaultdict(int)
    for s in stats['years']:
        if s['status'] == 'ok':
            for role, count in s['roles'].items():
                total_roles[role] += count

    colors = ['#e74c3c', '#f39c12', '#3498db', '#95a5a6']
    labels = [f"{ROLE_CN[r]}\n{total_roles[r]/1e6:.1f}M" for r in ['Pioneer', 'Ahead-of-time', 'Diffuser', 'Routine']]
    sizes = [total_roles[r] for r in ['Pioneer', 'Ahead-of-time', 'Diffuser', 'Routine']]

    ax2.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
    ax2.set_title('总体分类分布')

    # 3. 阈值趋势
    innov_p70 = [s['thresholds']['innovation_p70'] for s in stats['years'] if s['status'] == 'ok']
    impact_p70 = [s['thresholds']['impact_p70'] for s in stats['years'] if s['status'] == 'ok']

    ax3.plot(years, innov_p70, 'b-o', label='创新度 P70', markersize=4)
    ax3.plot(years, impact_p70, 'r-s', label='影响力 P70', markersize=4)
    ax3.set_xlabel('年份')
    ax3.set_ylabel('P70 阈值')
    ax3.set_title('阈值年度变化')
    ax3.legend()
    ax3.set_xticks(years[::2])
    ax3.grid(True, alpha=0.3)

    # 4. 分类比例堆叠面积图
    role_pcts = {role: [] for role in ['Pioneer', 'Ahead-of-time', 'Diffuser', 'Routine']}
    for s in stats['years']:
        if s['status'] == 'ok':
            for role in role_pcts:
                role_pcts[role].append(s['role_pct'][role])

    bottom = np.zeros(len(years))
    for role, color in zip(['Routine', 'Diffuser', 'Ahead-of-time', 'Pioneer'],
                           ['#95a5a6', '#3498db', '#f39c12', '#e74c3c']):
        ax4.fill_between(years, bottom, bottom + role_pcts[role],
                        label=ROLE_CN[role], color=color, alpha=0.8)
        bottom += role_pcts[role]

    ax4.set_xlabel('年份')
    ax4.set_ylabel('比例 (%)')
    ax4.set_title('分类比例年度趋势')
    ax4.legend(loc='upper right', fontsize=8)
    ax4.set_xticks(years[::2])

    # 5. 统计摘要文本
    ax5.axis('off')
    summary_text = f"""
    ══════════════════════════════════════════════════════════════════════
                              论文价值信号系统 - 数据摘要
    ══════════════════════════════════════════════════════════════════════

    数据范围: {years[0]} - {years[-1]}年
    论文总量: {stats['total_papers']:,} 篇

    分类统计:
      • 先驱者 (Pioneer):     {total_roles['Pioneer']:>10,} 篇 ({100*total_roles['Pioneer']/stats['total_papers']:.1f}%)
      • 超前者 (Ahead-of-time): {total_roles['Ahead-of-time']:>10,} 篇 ({100*total_roles['Ahead-of-time']/stats['total_papers']:.1f}%)
      • 传播者 (Diffuser):    {total_roles['Diffuser']:>10,} 篇 ({100*total_roles['Diffuser']/stats['total_papers']:.1f}%)
      • 常规者 (Routine):     {total_roles['Routine']:>10,} 篇 ({100*total_roles['Routine']/stats['total_papers']:.1f}%)

    关键发现:
      • 创新度与影响力近乎正交 (Pearson r ≈ 0.04)
      • 只有原创论文能成为先驱者或超前者
      • 创新度阈值逐年上升 ({innov_p70[0]:.1f} → {innov_p70[-1]:.1f})

    生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    ══════════════════════════════════════════════════════════════════════
    """
    ax5.text(0.5, 0.5, summary_text, transform=ax5.transAxes, fontsize=10,
             verticalalignment='center', horizontalalignment='center',
             fontfamily='monospace',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.suptitle('论文价值信号系统 - 综合仪表盘', fontsize=16, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(CONFIG['output_dir'], 'summary_dashboard.png'), dpi=150)
    plt.close()
    log("  Saved: summary_dashboard.png")


def main():
    parser = argparse.ArgumentParser(description="Phase 5.3 Trend Visualization")
    parser.add_argument("--config", type=str, default=None, help="配置文件路径（JSON）")
    args = parser.parse_args()
    apply_config(args.config)

    print("=" * 60)
    print("Phase 5.3: 趋势可视化")
    print("=" * 60)
    print()

    # 1. Impact 分布演化
    plot_impact_distribution_evolution()

    # 2. 阈值趋势
    plot_threshold_trends()

    # 3. 分类角色趋势
    plot_role_trends()

    # 4. 先驱者分析
    plot_pioneer_analysis()

    # 5. 综合仪表盘
    plot_summary_dashboard()

    print("\n" + "=" * 60)
    print("输出文件:")
    print("=" * 60)
    for f in ['impact_evolution.png', 'threshold_trends.png', 'role_trends.png',
              'pioneer_analysis.png', 'summary_dashboard.png']:
        print(f"  • {f}")
    print(f"\n输出目录: {CONFIG['output_dir']}")
    print("=" * 60 + "\n完成!\n")


if __name__ == "__main__":
    main()
