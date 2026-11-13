# -*- coding: utf-8 -*-
"""
Impact V5 Results Validation Script

适配 V5 字段: diffusion_norm, persistence_gate, impact_score, object_count
"""

import os
import json
import argparse
import sys
from pathlib import Path
from collections import defaultdict
from typing import List, Dict
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import load_project_config, get_paths, get_runtime, get_years

_cfg = load_project_config()
_paths = get_paths(_cfg)
_runtime = get_runtime(_cfg)
OUTPUT_DIR = _paths["impact_output_dir"]
DEFAULT_YEARS = list(get_years(_runtime))


def apply_config(config_path: str = None):
    global OUTPUT_DIR, DEFAULT_YEARS
    cfg = load_project_config(config_path)
    paths = get_paths(cfg)
    runtime = get_runtime(cfg)
    OUTPUT_DIR = paths["impact_output_dir"]
    DEFAULT_YEARS = list(get_years(runtime))


def load_year_data(year: int) -> List[dict]:
    path = os.path.join(OUTPUT_DIR, f"impact_final_{year}.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return [json.loads(line) for line in f]


def validate_completeness(years: List[int]):
    print("\n" + "=" * 60)
    print("1. Data Completeness Check")
    print("=" * 60)
    total = 0
    for year in years:
        path = os.path.join(OUTPUT_DIR, f"impact_final_{year}.jsonl")
        if not os.path.exists(path):
            print(f"  [MISSING] {year}")
            continue
        count = sum(1 for _ in open(path, 'r', encoding='utf-8'))
        total += count
        print(f"  {year}: {count:>10,} papers")
    print(f"\n  Total: {total:,} papers")


def validate_distributions(years: List[int]):
    """V5 字段分布验证"""
    print("\n" + "=" * 60)
    print("2. Score Distribution Analysis (V5)")
    print("=" * 60)

    all_impact = []
    all_diffusion = []
    all_persistence = []
    all_objects = []

    for year in years:
        for d in load_year_data(year):
            all_impact.append(d.get('impact_score', 0))
            all_diffusion.append(d.get('diffusion_norm', 0))
            all_persistence.append(d.get('persistence_gate', 0))
            all_objects.append(d.get('object_count', 0))

    if not all_impact:
        print("  [FAIL] No data")
        return

    print(f"\n  {'Signal':<20} {'Mean':>10} {'Std':>10} {'P50':>10} {'P90':>10} {'Max':>10}")
    print("  " + "-" * 70)

    for name, arr in [
        ('impact_score', all_impact),
        ('diffusion_norm', all_diffusion),
        ('persistence_gate', all_persistence),
        ('object_count', all_objects)
    ]:
        a = np.array(arr)
        print(f"  {name:<20} {a.mean():>10.2f} {a.std():>10.2f} "
              f"{np.percentile(a, 50):>10.2f} {np.percentile(a, 90):>10.2f} {a.max():>10.2f}")


def validate_yearly_trends(years: List[int]):
    """年度趋势分析"""
    print("\n" + "=" * 60)
    print("3. Yearly Trend Analysis")
    print("=" * 60)

    print(f"\n  {'Year':<6} {'Papers':>10} {'Mean':>10} {'P50':>10} {'P90':>10} {'>50':>10}")
    print("  " + "-" * 60)

    for year in years:
        data = load_year_data(year)
        if not data:
            print(f"  {year:<6} [MISSING]")
            continue

        scores = [d.get('impact_score', 0) for d in data]
        a = np.array(scores)
        high_ratio = 100 * np.sum(a > 50) / len(a)

        print(f"  {year:<6} {len(data):>10,} {a.mean():>10.2f} "
              f"{np.percentile(a, 50):>10.2f} {np.percentile(a, 90):>10.2f} {high_ratio:>9.1f}%")


def validate_persistence_distribution(years: List[int]):
    """Persistence Gate 分布分析"""
    print("\n" + "=" * 60)
    print("4. Persistence Gate Distribution")
    print("=" * 60)

    all_pg = []
    for year in years:
        for d in load_year_data(year):
            all_pg.append(d.get('persistence_gate', 0))

    if not all_pg:
        print("  [FAIL] No data")
        return

    a = np.array(all_pg)

    # 分段统计
    bins = [(0, 0.001, 'Zero (no survival)'),
            (0.001, 0.1, 'Low (0-0.1)'),
            (0.1, 0.5, 'Medium (0.1-0.5)'),
            (0.5, 1.0, 'High (0.5-1.0)'),
            (1.0, 1.01, 'Max (1.0)')]

    print(f"\n  {'Range':<25} {'Count':>12} {'Percent':>10}")
    print("  " + "-" * 50)

    for low, high, label in bins:
        count = np.sum((a >= low) & (a < high))
        pct = 100 * count / len(a)
        print(f"  {label:<25} {count:>12,} {pct:>9.1f}%")


def sample_inspection(years: List[int], n: int = 3):
    """抽样检查"""
    print("\n" + "=" * 60)
    print("5. Sample Inspection (High/Low Impact)")
    print("=" * 60)

    # 收集所有数据
    all_data = []
    for year in years:
        all_data.extend(load_year_data(year))

    if not all_data:
        print("  [FAIL] No data")
        return

    # 按 impact_score 排序
    sorted_data = sorted(all_data, key=lambda x: x.get('impact_score', 0), reverse=True)

    # Top N
    print(f"\n  === Top {n} Impact ===")
    for d in sorted_data[:n]:
        print(f"  {d['paper_id'][:16]}... ({d['pub_year']}): "
              f"impact={d.get('impact_score', 0):.1f}, "
              f"diffusion={d.get('diffusion_norm', 0):.1f}, "
              f"persist={d.get('persistence_gate', 0):.3f}, "
              f"objects={d.get('object_count', 0)}")

    # Bottom N (non-zero)
    non_zero = [d for d in sorted_data if d.get('impact_score', 0) > 0]
    print(f"\n  === Bottom {n} Impact (non-zero) ===")
    for d in non_zero[-n:]:
        print(f"  {d['paper_id'][:16]}... ({d['pub_year']}): "
              f"impact={d.get('impact_score', 0):.1f}, "
              f"diffusion={d.get('diffusion_norm', 0):.1f}, "
              f"persist={d.get('persistence_gate', 0):.3f}, "
              f"objects={d.get('object_count', 0)}")

    # Zero impact 统计
    zero_count = len(sorted_data) - len(non_zero)
    print(f"\n  Zero impact papers: {zero_count:,} ({100*zero_count/len(sorted_data):.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="Validate Impact V5")
    parser.add_argument("--year", type=int, help="Validate specific year")
    parser.add_argument("--sample", type=int, default=5, help="Sample size for inspection")
    parser.add_argument("--config", type=str, default=None, help="配置文件路径（JSON）")
    args = parser.parse_args()
    apply_config(args.config)

    print("=" * 60)
    print("Impact V5 Validation")
    print("=" * 60)

    years = [args.year] if args.year else DEFAULT_YEARS

    validate_completeness(years)
    validate_distributions(years)
    validate_yearly_trends(years)
    validate_persistence_distribution(years)
    sample_inspection(years, args.sample)

    print("\n" + "=" * 60 + "\nDone\n")


if __name__ == "__main__":
    main()
