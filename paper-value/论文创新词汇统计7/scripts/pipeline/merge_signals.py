# -*- coding: utf-8 -*-
"""
Phase 5.1: 鍚堝苟 Innovation + Impact 淇″彿

杈撳叆锛?- <innovation_output_dir>/innovation_v2_{year}.jsonl
- <impact_output_dir>/impact_final_{year}.jsonl

杈撳嚭锛?- <paper_signals_output_dir>/paper_signals_{year}.jsonl

鍒嗙被鏍囩浣撶郴 (鍩轰簬骞村害鍐?P70):
             Impact >= P70    Impact < P70
Innovation   鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?
>= P70       鈹?  Pioneer    鈹?Ahead-of-time鈹?
             鈹溾攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹尖攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?
<  P70       鈹?  Diffuser   鈹?  Routine    鈹?
             鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹粹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?
"""

import os
import sys
import json
import math
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import load_project_config, get_paths, get_runtime, get_years

# ============== 閰嶇疆 ==============

_cfg = load_project_config()
_paths = get_paths(_cfg)
_runtime = get_runtime(_cfg)

CONFIG = {
    'innovation_dir': _paths['innovation_output_dir'],
    'impact_dir': _paths['impact_output_dir'],
    'output_dir': _paths['paper_signals_output_dir'],
    'years': get_years(_runtime),
    'percentile_threshold': int(_runtime.get('percentile_threshold', 70)),  # P70 浣滀负楂?浣庡垎鐣?    'impact_prefix': str(_runtime.get('impact_merge_prefix', 'impact_final')),
    'classification_mode': str(_runtime.get('merge_classification_mode', 'rank_top_share')),
    'simpson_alert_gap': float(_runtime.get('merge_simpson_alert_gap', 5.0)),
}

IMPACT_PRIMARY_SCORE_FIELDS = ("impact_score", "diffusion_impact")
IMPACT_DEFAULT_SEMANTIC = "diffusion_impact"


def apply_config(config_path: str = None):
    cfg = load_project_config(config_path)
    paths = get_paths(cfg)
    runtime = get_runtime(cfg)
    CONFIG.update({
        'innovation_dir': paths['innovation_output_dir'],
        'impact_dir': paths['impact_output_dir'],
        'output_dir': paths['paper_signals_output_dir'],
        'years': get_years(runtime),
        'percentile_threshold': int(runtime.get('percentile_threshold', 70)),
        'impact_prefix': str(runtime.get('impact_merge_prefix', 'impact_final')),
        'classification_mode': str(runtime.get('merge_classification_mode', 'rank_top_share')),
        'simpson_alert_gap': float(runtime.get('merge_simpson_alert_gap', 5.0)),
    })


def log(msg: str):
    """Print log message with time prefix."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def innovation_file_path(year: int) -> str:
    return os.path.join(CONFIG['innovation_dir'], f'innovation_v2_{year}.jsonl')


def impact_file_path(year: int) -> str:
    return os.path.join(CONFIG['impact_dir'], f"{CONFIG['impact_prefix']}_{year}.jsonl")


def summarize_years(years: List[int]) -> str:
    if not years:
        return "-"
    years = sorted(years)
    if len(years) <= 8:
        return ",".join(str(y) for y in years)
    return f"{years[0]}-{years[-1]} ({len(years)} years)"


def validate_input_files(years: List[int]) -> Tuple[List[int], List[int]]:
    """杩斿洖 (missing_innovation_years, missing_impact_years)"""
    missing_innovation = []
    missing_impact = []
    for year in years:
        if not os.path.exists(innovation_file_path(year)):
            missing_innovation.append(year)
        if not os.path.exists(impact_file_path(year)):
            missing_impact.append(year)
    return missing_innovation, missing_impact


def _load_jsonl_by_paper_id(path: str, source_name: str, year: int) -> Tuple[Dict[str, dict], Dict[str, int]]:
    """鍔犺浇 JSONL锛岃繑鍥?({paper_id: data}, 瑙ｆ瀽璇婃柇)"""
    if not os.path.exists(path):
        return {}, {'parse_error': 0, 'missing_paper_id': 0, 'duplicate_paper_id': 0}

    result: Dict[str, dict] = {}
    diagnostics = {'parse_error': 0, 'missing_paper_id': 0, 'duplicate_paper_id': 0}
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                diagnostics['parse_error'] += 1
                continue

            paper_id = str(d.get('paper_id', '')).strip()
            if not paper_id:
                diagnostics['missing_paper_id'] += 1
                continue

            if paper_id in result:
                diagnostics['duplicate_paper_id'] += 1
            result[paper_id] = d

    if any(v > 0 for v in diagnostics.values()):
        log(
            f"  [WARNING] {source_name} {year}: parse_error={diagnostics['parse_error']}, "
            f"missing_paper_id={diagnostics['missing_paper_id']}, duplicate_paper_id={diagnostics['duplicate_paper_id']}"
        )
    return result, diagnostics


def load_innovation_data(year: int) -> Tuple[Dict[str, dict], Dict[str, int]]:
    """Load innovation data for one year."""
    return _load_jsonl_by_paper_id(innovation_file_path(year), "innovation", year)


def load_impact_data(year: int) -> Tuple[Dict[str, dict], Dict[str, int]]:
    """Load impact data for one year."""
    return _load_jsonl_by_paper_id(impact_file_path(year), "impact", year)


def _parse_finite_score(value) -> Optional[float]:
    if value is None:
        return None
    try:
        score = float(value)
    except Exception:
        return None
    if not np.isfinite(score):
        return None
    return score


def _extract_impact_score(rec: dict) -> Optional[float]:
    for field in IMPACT_PRIMARY_SCORE_FIELDS:
        score = _parse_finite_score(rec.get(field))
        if score is not None:
            return score
    return None


def _extract_impact_semantic(rec: dict) -> str:
    text = str(rec.get('impact_score_semantic', '')).strip()
    if text:
        return text
    text = str(rec.get('impact_primary_channel', '')).strip()
    if text:
        return text
    if _parse_finite_score(rec.get('diffusion_impact')) is not None:
        return 'diffusion_impact'
    return IMPACT_DEFAULT_SEMANTIC


def _extract_impact_channels(rec: dict, fallback_score: float) -> Dict[str, float]:
    raw = rec.get('impact_channels')
    foundation_norm = _parse_finite_score(rec.get('foundation_utility_norm'))
    method_norm = _parse_finite_score(rec.get('method_transferability_norm'))
    if isinstance(raw, dict):
        out: Dict[str, float] = {}
        for key, value in raw.items():
            score = _parse_finite_score(value)
            if score is None:
                continue
            name = str(key).strip()
            if not name:
                continue
            out[name] = float(score)
        if foundation_norm is not None and 'foundation_utility' not in out:
            out['foundation_utility'] = float(foundation_norm)
        if method_norm is not None and 'method_transferability' not in out:
            out['method_transferability'] = float(method_norm)
        if out:
            return out
    diffusion_score = _parse_finite_score(rec.get('diffusion_impact'))
    if diffusion_score is None:
        diffusion_score = float(fallback_score)
    out = {'diffusion_impact': float(diffusion_score)}
    if foundation_norm is not None:
        out['foundation_utility'] = float(foundation_norm)
    if method_norm is not None:
        out['method_transferability'] = float(method_norm)
    return out


def calculate_thresholds(innovation_scores: List[float],
                         impact_scores: List[float],
                         percentile: int = 70) -> Tuple[float, float]:
    """Calculate yearly percentile thresholds."""
    innov_threshold = np.percentile(innovation_scores, percentile) if innovation_scores else 0
    impact_threshold = np.percentile(impact_scores, percentile) if impact_scores else 0
    return innov_threshold, impact_threshold


def classify_paper(high_innovation: bool, high_impact: bool) -> str:
    """Assign role label from high/low innovation-impact flags."""
    high_innovation = bool(high_innovation)
    high_impact = bool(high_impact)

    if high_innovation and high_impact:
        return 'Pioneer'
    elif high_innovation and not high_impact:
        return 'Ahead-of-time'
    elif not high_innovation and high_impact:
        return 'Diffuser'
    else:
        return 'Routine'


def _select_high_flags(primary_scores: List[float],
                       secondary_scores: List[float],
                       paper_ids: List[str],
                       percentile: int) -> Tuple[List[bool], dict]:
    """Select top-share flags with deterministic tie-breaking."""
    n = len(primary_scores)
    if n <= 0:
        return [], {
            'target_high_count': 0,
            'actual_high_count': 0,
            'constant_distribution': True,
            'cutoff_score': None,
            'boundary_tie_count': 0,
        }

    max_score = max(primary_scores)
    min_score = min(primary_scores)
    if not math.isfinite(max_score) or not math.isfinite(min_score) or abs(max_score - min_score) <= 1e-12:
        return [False] * n, {
            'target_high_count': 0,
            'actual_high_count': 0,
            'constant_distribution': True,
            'cutoff_score': float(min_score) if math.isfinite(min_score) else None,
            'boundary_tie_count': n,
        }

    high_share = max(0.0, min(1.0, (100.0 - float(percentile)) / 100.0))
    target_high = int(math.ceil(high_share * n))
    target_high = max(0, min(target_high, n))
    if target_high <= 0:
        return [False] * n, {
            'target_high_count': 0,
            'actual_high_count': 0,
            'constant_distribution': False,
            'cutoff_score': None,
            'boundary_tie_count': 0,
        }

    order = sorted(
        range(n),
        key=lambda i: (primary_scores[i], secondary_scores[i], paper_ids[i]),
    )
    flags = [False] * n
    selected = order[-target_high:]
    for idx in selected:
        flags[idx] = True

    cutoff_idx = order[-target_high]
    cutoff_score = float(primary_scores[cutoff_idx])
    boundary_tie_count = sum(1 for s in primary_scores if abs(float(s) - cutoff_score) <= 1e-12)
    actual_high = sum(1 for x in flags if x)
    return flags, {
        'target_high_count': target_high,
        'actual_high_count': actual_high,
        'constant_distribution': False,
        'cutoff_score': cutoff_score,
        'boundary_tie_count': boundary_tie_count,
    }


def merge_year(year: int) -> dict:
    """Merge one year's innovation and impact outputs."""
    log(f"Processing {year}...")

    # 鍔犺浇鏁版嵁
    innovation_data, innovation_diag = load_innovation_data(year)
    impact_data, impact_diag = load_impact_data(year)

    if not innovation_data:
        log(f"  [WARNING] No innovation data for {year}")
        return {
            'year': year,
            'status': 'missing_innovation',
            'diagnostics': {
                'innovation_load': innovation_diag,
                'impact_load': impact_diag,
            },
        }
    if not impact_data:
        log(f"  [WARNING] No impact data for {year}")
        return {
            'year': year,
            'status': 'missing_impact',
            'diagnostics': {
                'innovation_load': innovation_diag,
                'impact_load': impact_diag,
            },
        }

    # 鎵惧埌鍏卞悓鐨?paper_id
    innovation_ids = set(innovation_data.keys())
    impact_ids = set(impact_data.keys())
    common_ids = innovation_ids & impact_ids
    innovation_only_ids = sorted(innovation_ids - impact_ids)
    impact_only_ids = sorted(impact_ids - innovation_ids)
    log(f"  Innovation: {len(innovation_data):,}, Impact: {len(impact_data):,}, Common: {len(common_ids):,}")
    if innovation_only_ids or impact_only_ids:
        log(
            f"  [INFO] Dropped by join: innovation_only={len(innovation_only_ids):,}, "
            f"impact_only={len(impact_only_ids):,}"
        )

    if not common_ids:
        return {
            'year': year,
            'status': 'no_common_ids',
            'diagnostics': {
                'innovation_only_count': len(innovation_only_ids),
                'impact_only_count': len(impact_only_ids),
                'innovation_only_sample': innovation_only_ids[:5],
                'impact_only_sample': impact_only_ids[:5],
                'innovation_load': innovation_diag,
                'impact_load': impact_diag,
            },
        }

    # Collect scores for threshold calculation.
    innovation_scores: List[float] = []
    impact_scores: List[float] = []
    valid_common_ids: List[str] = []
    invalid_score_ids: List[str] = []

    for pid in sorted(common_ids):
        innov_score = _parse_finite_score(innovation_data[pid].get('total_score_v2'))
        impact_score = _extract_impact_score(impact_data[pid])
        if innov_score is None or impact_score is None:
            invalid_score_ids.append(pid)
            continue
        valid_common_ids.append(pid)
        innovation_scores.append(innov_score)
        impact_scores.append(impact_score)

    if not valid_common_ids:
        log(f"  [WARNING] No valid score pairs for {year}")
        return {
            'year': year,
            'status': 'no_valid_score_pairs',
            'diagnostics': {
                'raw_common_count': len(common_ids),
                'invalid_score_count': len(invalid_score_ids),
                'invalid_score_sample': invalid_score_ids[:5],
                'innovation_only_count': len(innovation_only_ids),
                'impact_only_count': len(impact_only_ids),
                'innovation_load': innovation_diag,
                'impact_load': impact_diag,
            },
        }

    # Compute thresholds.
    innov_threshold, impact_threshold = calculate_thresholds(
        innovation_scores, impact_scores, CONFIG['percentile_threshold']
    )
    log(f"  Thresholds: Innovation P70={innov_threshold:.2f}, Impact P70={impact_threshold:.2f}")
    if invalid_score_ids:
        log(f"  [INFO] Ignored invalid score pairs: {len(invalid_score_ids):,}")

    classification_mode = str(CONFIG.get('classification_mode', 'rank_top_share')).strip().lower()
    if classification_mode != 'rank_top_share':
        classification_mode = 'rank_top_share'
    innovation_high_flags, innovation_rank_diag = _select_high_flags(
        primary_scores=innovation_scores,
        secondary_scores=impact_scores,
        paper_ids=valid_common_ids,
        percentile=CONFIG['percentile_threshold'],
    )
    impact_high_flags, impact_rank_diag = _select_high_flags(
        primary_scores=impact_scores,
        secondary_scores=innovation_scores,
        paper_ids=valid_common_ids,
        percentile=CONFIG['percentile_threshold'],
    )

    # Merge records and assign roles.
    output_path = os.path.join(CONFIG['output_dir'], f'paper_signals_{year}.jsonl')
    role_counts = defaultdict(int)
    impact_semantic_counts = defaultdict(int)
    impact_channel_values: Dict[str, List[float]] = defaultdict(list)

    with open(output_path, 'w', encoding='utf-8') as f:
        for idx, pid in enumerate(valid_common_ids):
            innov = innovation_data[pid]
            impact = impact_data[pid]

            innovation_score = float(innovation_scores[idx])
            impact_score = float(impact_scores[idx])
            high_innovation = bool(innovation_high_flags[idx])
            high_impact = bool(impact_high_flags[idx])
            role = classify_paper(high_innovation, high_impact)
            role_counts[role] += 1
            impact_score_semantic = _extract_impact_semantic(impact)
            impact_primary_channel = str(impact.get('impact_primary_channel', '')).strip() or impact_score_semantic
            impact_channels = _extract_impact_channels(impact, impact_score)
            foundation_utility_norm = impact_channels.get(
                'foundation_utility',
                _parse_finite_score(impact.get('foundation_utility_norm')) or 0.0,
            )
            foundation_utility_raw = _parse_finite_score(impact.get('foundation_utility_raw'))
            if foundation_utility_raw is None:
                foundation_utility_raw = 0.0
            method_transferability_norm = impact_channels.get(
                'method_transferability',
                _parse_finite_score(impact.get('method_transferability_norm')) or 0.0,
            )
            method_transferability_raw = _parse_finite_score(impact.get('method_transferability_raw'))
            if method_transferability_raw is None:
                method_transferability_raw = 0.0
            impact_semantic_counts[impact_score_semantic] += 1
            for channel_name, channel_score in impact_channels.items():
                if np.isfinite(float(channel_score)):
                    impact_channel_values[channel_name].append(float(channel_score))

            merged = {
                'paper_id': pid,
                'pub_year': year,
                # Innovation 瀛楁
                'innovation_score': innovation_score,
                'innovation_magnitude': innov.get('innovation_magnitude', 0),
                'paper_type': innov.get('paper_type_detected', 'unknown'),
                # Impact 瀛楁
                'impact_score': impact_score,
                'impact_score_semantic': impact_score_semantic,
                'impact_primary_channel': impact_primary_channel,
                'impact_channels': impact_channels,
                'diffusion_impact': impact_channels.get('diffusion_impact', impact_score),
                'foundation_utility_norm': float(foundation_utility_norm),
                'foundation_utility_raw': float(foundation_utility_raw),
                'method_transferability_norm': float(method_transferability_norm),
                'method_transferability_raw': float(method_transferability_raw),
                'impact_norm': impact.get('adoption_norm', impact.get('diffusion_norm', 0)),
                'consistency_gate': impact.get('consistency_gate', impact.get('persistence_gate', 0)),
                # backward-compatible aliases
                'diffusion_norm': impact.get('diffusion_norm', impact.get('adoption_norm', 0)),
                'persistence_gate': impact.get('persistence_gate', impact.get('consistency_gate', 0)),
                'object_count': impact.get('object_count', 0),
                'high_innovation': high_innovation,
                'high_impact': high_impact,
                'classification_mode': classification_mode,
                # 鍒嗙被
                'role': role,
            }
            f.write(json.dumps(merged, ensure_ascii=False) + '\n')

    # 缁熻
    total = len(valid_common_ids)
    impact_channel_summary = {}
    for channel_name, channel_values in impact_channel_values.items():
        if not channel_values:
            continue
        arr = np.asarray(channel_values, dtype=np.float64)
        impact_channel_summary[channel_name] = {
            'count': int(arr.size),
            'mean': round(float(arr.mean()), 4),
            'p50': round(float(np.percentile(arr, 50)), 4),
            'p90': round(float(np.percentile(arr, 90)), 4),
            'max': round(float(arr.max()), 4),
        }

    stats = {
        'year': year,
        'status': 'ok',
        'total': total,
        'thresholds': {
            'innovation_p70': round(innov_threshold, 2),
            'impact_p70': round(impact_threshold, 2),
        },
        'diagnostics': {
            'raw_common_count': len(common_ids),
            'valid_common_count': len(valid_common_ids),
            'invalid_score_count': len(invalid_score_ids),
            'invalid_score_sample': invalid_score_ids[:5],
            'innovation_only_count': len(innovation_only_ids),
            'impact_only_count': len(impact_only_ids),
            'innovation_only_sample': innovation_only_ids[:5],
            'impact_only_sample': impact_only_ids[:5],
            'innovation_load': innovation_diag,
            'impact_load': impact_diag,
            'classification_mode': classification_mode,
            'innovation_high_selection': innovation_rank_diag,
            'impact_high_selection': impact_rank_diag,
            'impact_semantics': dict(sorted(impact_semantic_counts.items())),
            'impact_score_fields': list(IMPACT_PRIMARY_SCORE_FIELDS),
            'impact_channel_summary': impact_channel_summary,
        },
        'roles': {
            'Pioneer': role_counts['Pioneer'],
            'Ahead-of-time': role_counts['Ahead-of-time'],
            'Diffuser': role_counts['Diffuser'],
            'Routine': role_counts['Routine'],
        },
        'role_pct': {
            'Pioneer': round(100 * role_counts['Pioneer'] / total, 1),
            'Ahead-of-time': round(100 * role_counts['Ahead-of-time'] / total, 1),
            'Diffuser': round(100 * role_counts['Diffuser'] / total, 1),
            'Routine': round(100 * role_counts['Routine'] / total, 1),
        }
    }

    log(f"  Pioneer: {stats['role_pct']['Pioneer']}%, "
        f"Ahead: {stats['role_pct']['Ahead-of-time']}%, "
        f"Diffuser: {stats['role_pct']['Diffuser']}%, "
        f"Routine: {stats['role_pct']['Routine']}%")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Merge Innovation + Impact signals")
    parser.add_argument("--year", type=int, help="Process specific year only")
    parser.add_argument("--years", type=str, help="Year range, e.g., 2010-2015")
    parser.add_argument("--impact-prefix", type=str, default=None, help="Impact file prefix, e.g. impact_final / impact_v6_final")
    parser.add_argument(
        "--allow-missing-inputs",
        action="store_true",
        help="Allow missing inputs and continue (strict mode by default).",
    )
    parser.add_argument("--config", type=str, default=None, help="Config JSON path")
    args = parser.parse_args()

    apply_config(args.config)
    if args.impact_prefix:
        CONFIG['impact_prefix'] = args.impact_prefix

    # Resolve target years.
    if args.year is not None:
        years = [args.year]
    elif args.years:
        start, end = map(int, args.years.split('-'))
        years = list(range(start, end + 1))
    else:
        years = list(CONFIG['years'])

    # 鍒涘缓杈撳嚭鐩綍
    os.makedirs(CONFIG['output_dir'], exist_ok=True)

    print("=" * 60)
    print("Phase 5.1: Merge Innovation + Impact Signals")
    print("=" * 60)
    log(f"Years: {years[0]}-{years[-1]}")
    log(f"Output: {CONFIG['output_dir']}")
    log(f"Impact Prefix: {CONFIG['impact_prefix']}")
    print()

    # 鍓嶇疆鏍￠獙锛氶粯璁や弗鏍兼ā寮忥紝闃叉闈欓粯 missing_impact/missing_innovation
    missing_innovation, missing_impact = validate_input_files(years)
    if missing_innovation or missing_impact:
        if not args.allow_missing_inputs:
            log("[ERROR] Input file validation failed; merge aborted.")
            if missing_innovation:
                sample_path = innovation_file_path(missing_innovation[0])
                log(f"[ERROR] 缂哄け innovation 鏂囦欢骞翠唤: {summarize_years(missing_innovation)}")
                log(f"[ERROR] 绀轰緥缂哄け璺緞: {sample_path}")
            if missing_impact:
                sample_path = impact_file_path(missing_impact[0])
                log(f"[ERROR] 缂哄け impact 鏂囦欢骞翠唤: {summarize_years(missing_impact)}")
                log(f"[ERROR] 绀轰緥缂哄け璺緞: {sample_path}")
                log(f"[ERROR] 褰撳墠 impact_prefix={CONFIG['impact_prefix']}")
            log("[ERROR] 濡傞渶淇濈暀鏃ц涓哄彲鍔?--allow-missing-inputs")
            sys.exit(2)

        log("[WARNING] 妫€娴嬪埌杈撳叆缂哄け锛屾寜 --allow-missing-inputs 缁х画杩愯")
        if missing_innovation:
            log(f"[WARNING] 缂哄け innovation 鏂囦欢骞翠唤: {summarize_years(missing_innovation)}")
        if missing_impact:
            log(f"[WARNING] 缂哄け impact 鏂囦欢骞翠唤: {summarize_years(missing_impact)}")

    # Process each year.
    all_stats = []
    for year in years:
        stats = merge_year(year)
        all_stats.append(stats)
        print()

    # 姹囨€荤粺璁?
    print("=" * 60)
    print("Summary")
    print("=" * 60)

    total_papers = 0
    total_roles = defaultdict(int)

    print(f"\n{'Year':<6} {'Papers':>10} {'Pioneer':>10} {'Ahead':>10} {'Diffuser':>10} {'Routine':>10}")
    print("-" * 66)

    for s in all_stats:
        if s['status'] != 'ok':
            print(f"{s['year']:<6} [{s['status']}]")
            continue

        total_papers += s['total']
        for role, count in s['roles'].items():
            total_roles[role] += count

        print(f"{s['year']:<6} {s['total']:>10,} "
              f"{s['role_pct']['Pioneer']:>9.1f}% "
              f"{s['role_pct']['Ahead-of-time']:>9.1f}% "
              f"{s['role_pct']['Diffuser']:>9.1f}% "
              f"{s['role_pct']['Routine']:>9.1f}%")

    print("-" * 66)
    if total_papers > 0:
        print(f"{'Total':<6} {total_papers:>10,} "
              f"{100*total_roles['Pioneer']/total_papers:>9.1f}% "
              f"{100*total_roles['Ahead-of-time']/total_papers:>9.1f}% "
              f"{100*total_roles['Diffuser']/total_papers:>9.1f}% "
              f"{100*total_roles['Routine']/total_papers:>9.1f}%")

    simpson_diag = {
        'enabled': True,
        'year_count': 0,
        'risk_alert': False,
    }
    valid_years = [s for s in all_stats if s.get('status') == 'ok' and s.get('total', 0) > 0]
    if total_papers > 0 and valid_years:
        pooled_pct = {
            'Pioneer': 100.0 * total_roles['Pioneer'] / total_papers,
            'Ahead-of-time': 100.0 * total_roles['Ahead-of-time'] / total_papers,
            'Diffuser': 100.0 * total_roles['Diffuser'] / total_papers,
            'Routine': 100.0 * total_roles['Routine'] / total_papers,
        }
        yearly_mean_pct = {
            'Pioneer': float(np.mean([float(s['role_pct']['Pioneer']) for s in valid_years])),
            'Ahead-of-time': float(np.mean([float(s['role_pct']['Ahead-of-time']) for s in valid_years])),
            'Diffuser': float(np.mean([float(s['role_pct']['Diffuser']) for s in valid_years])),
            'Routine': float(np.mean([float(s['role_pct']['Routine']) for s in valid_years])),
        }
        gaps = {k: abs(pooled_pct[k] - yearly_mean_pct[k]) for k in pooled_pct}
        max_gap_role, max_gap = max(gaps.items(), key=lambda kv: kv[1])
        simpson_alert_gap = max(float(CONFIG.get('simpson_alert_gap', 5.0)), 0.0)
        simpson_diag = {
            'enabled': True,
            'year_count': len(valid_years),
            'alert_gap_pp': round(simpson_alert_gap, 3),
            'risk_alert': bool(max_gap >= simpson_alert_gap),
            'max_gap_role': max_gap_role,
            'max_gap_pp': round(float(max_gap), 3),
            'pooled_role_pct': {k: round(v, 3) for k, v in pooled_pct.items()},
            'mean_yearly_role_pct': {k: round(v, 3) for k, v in yearly_mean_pct.items()},
            'gap_pp': {k: round(v, 3) for k, v in gaps.items()},
        }
        if simpson_diag['risk_alert']:
            log(
                f"[WARNING] Simpson 椋庨櫓鎻愮ず: 鏈€澶ц法骞存睜鍖栧亸宸?{simpson_diag['max_gap_role']}="
                f"{simpson_diag['max_gap_pp']:.2f}pp (闃堝€?{simpson_diag['alert_gap_pp']:.2f}pp)"
            )

    # 淇濆瓨缁熻淇℃伅
    stats_path = os.path.join(CONFIG['output_dir'], 'merge_stats.json')
    with open(stats_path, 'w', encoding='utf-8') as f:
        json.dump({
            'generated_at': datetime.now().isoformat(),
            'total_papers': total_papers,
            'years': all_stats,
            'cross_year_diagnostics': {
                'simpson_check': simpson_diag,
            },
        }, f, indent=2, ensure_ascii=False)

    print(f"\nStats saved to: {stats_path}")
    print("=" * 60 + "\nDone\n")


if __name__ == "__main__":
    main()



