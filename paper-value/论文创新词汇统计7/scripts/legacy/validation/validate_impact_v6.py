# -*- coding: utf-8 -*-
"""
Impact V6 缁撴灉楠岃瘉鑴氭湰

瀛楁鍙ｅ緞锛?- adoption_norm
- consistency
- consistency_gate
- impact_score锛堝吋瀹瑰埆鍚嶏級
- diffusion_impact锛圴6.1 涓昏涔夛級
"""

import argparse
import heapq
import json
import os
import sys
import time
from array import array
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

import numpy as np
try:
    from tqdm import tqdm
except Exception:  # pragma: no cover
    tqdm = None

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import get_paths, get_runtime, get_years, load_project_config

_cfg = load_project_config()
_paths = get_paths(_cfg)
_runtime = get_runtime(_cfg)

OUTPUT_DIR = _paths["impact_output_dir"]
DEFAULT_YEARS = list(get_years(_runtime))
DEFAULT_FINAL_PREFIX = str(_runtime.get("impact_v6_final_prefix", "impact_v6_final"))
IMPACT_SCORE_FALLBACK_FIELDS = ("impact_score", "diffusion_impact")
IMPACT_DEFAULT_SEMANTIC = "diffusion_impact"
DEFAULT_GATE_PAIRS = (
    {
        "name": "main_vs_erratum_2020",
        "higher_paper_id": "21da5794b4f537271edb091a376f6860",
        "lower_paper_id": "4dae6853d4d99ecf314666735a8f01ec",
    },
)
VALIDATION_RESUME_SCHEMA_VERSION = "impact_v6_validate_resume_v1"
PROGRESS_ENABLED = True


def apply_config(config_path: str = None):
    global OUTPUT_DIR, DEFAULT_YEARS, DEFAULT_FINAL_PREFIX
    cfg = load_project_config(config_path)
    paths = get_paths(cfg)
    runtime = get_runtime(cfg)
    OUTPUT_DIR = paths["impact_output_dir"]
    DEFAULT_YEARS = list(get_years(runtime))
    DEFAULT_FINAL_PREFIX = str(runtime.get("impact_v6_final_prefix", "impact_v6_final"))


def _year_file(year: int, prefix: str) -> str:
    return os.path.join(OUTPUT_DIR, f"{prefix}_{year}.jsonl")


def iter_year_data(
    year: int,
    prefix: str,
    *,
    show_progress: bool = False,
    progress_desc: str = "",
) -> Iterator[dict]:
    path = _year_file(year, prefix)
    if not os.path.exists(path):
        return

    pbar = None
    row_count = 0
    valid_count = 0
    started_at = time.time()
    next_heartbeat = started_at + 20.0
    if show_progress and PROGRESS_ENABLED and tqdm is not None:
        try:
            total_bytes = os.path.getsize(path)
        except OSError:
            total_bytes = None
        desc = f"{progress_desc} {year}".strip() or f"year {year}"
        pbar = tqdm(
            total=total_bytes,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc=desc,
            leave=False,
        )

    try:
        with open(path, "rb") as f:
            for raw_line in f:
                row_count += 1
                if pbar is not None:
                    pbar.update(len(raw_line))
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    rec = json.loads(raw_line)
                except Exception:
                    continue
                if isinstance(rec, dict):
                    valid_count += 1
                    now = time.time()
                    if show_progress and now >= next_heartbeat:
                        elapsed = now - started_at
                        rate = valid_count / elapsed if elapsed > 0 else 0.0
                        desc = f"{progress_desc} {year}".strip() or f"year {year}"
                        print(
                            f"[PROGRESS] {desc}: rows={row_count:,}, valid={valid_count:,}, "
                            f"rate={rate:,.0f}/s, elapsed={elapsed:.1f}s"
                        )
                        next_heartbeat = now + 20.0
                    yield rec
    finally:
        if pbar is not None:
            pbar.close()
        if show_progress:
            elapsed = time.time() - started_at
            rate = valid_count / elapsed if elapsed > 0 else 0.0
            desc = f"{progress_desc} {year}".strip() or f"year {year}"
            print(
                f"[PROGRESS] {desc}: done, rows={row_count:,}, valid={valid_count:,}, "
                f"rate={rate:,.0f}/s, elapsed={elapsed:.1f}s"
            )


def load_year_data(year: int, prefix: str, *, show_progress: bool = False, progress_desc: str = "") -> List[dict]:
    return list(iter_year_data(year, prefix, show_progress=show_progress, progress_desc=progress_desc))


class OnlineStats:
    __slots__ = ("count", "mean", "m2", "max_value")

    def __init__(self):
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.max_value = float("-inf")

    def add(self, value: float):
        x = float(value)
        self.count += 1
        delta = x - self.mean
        self.mean += delta / self.count
        delta2 = x - self.mean
        self.m2 += delta * delta2
        if x > self.max_value:
            self.max_value = x

    def std(self) -> float:
        if self.count <= 0:
            return 0.0
        return float(np.sqrt(max(self.m2 / self.count, 0.0)))

    def summary(self, values: np.ndarray) -> Dict[str, float]:
        if self.count <= 0:
            return {
                "count": 0,
                "mean": 0.0,
                "std": 0.0,
                "p50": 0.0,
                "p90": 0.0,
                "max": 0.0,
            }
        if values.size <= 0:
            p50 = 0.0
            p90 = 0.0
        else:
            p50 = float(np.percentile(values, 50))
            p90 = float(np.percentile(values, 90))
        return {
            "count": int(self.count),
            "mean": float(self.mean),
            "std": float(self.std()),
            "p50": p50,
            "p90": p90,
            "max": float(self.max_value if np.isfinite(self.max_value) else 0.0),
        }


def _default_validation_resume_path(prefix: str, years: List[int]) -> str:
    safe_prefix = str(prefix).replace("/", "_").replace("\\", "_")
    sorted_years = sorted(int(y) for y in years) if years else [0]
    return os.path.join(
        OUTPUT_DIR,
        f"impact_v6_validate_resume_{safe_prefix}_{sorted_years[0]}_{sorted_years[-1]}.json",
    )


def _json_roundtrip_clone(obj):
    return json.loads(json.dumps(obj, ensure_ascii=False))


def _build_resume_context(prefix: str, years: List[int], args: argparse.Namespace) -> Dict[str, object]:
    return {
        "prefix": str(prefix),
        "years": [int(y) for y in sorted(years)],
        "score_field": str(args.score_field),
        "sample": int(args.sample),
        "skip_gate_report": bool(args.skip_gate_report),
        "gate_require_three_channel": bool(args.gate_require_three_channel),
        "gate_thresholds": {
            "pair_min_gap": float(args.gate_min_gap),
            "zero_top_share_max": float(args.gate_zero_top_share_max),
            "zero_min_unique": int(args.gate_zero_min_unique),
            "threshold_jump_max": float(args.gate_threshold_jump_max),
            "high_share_jump_max": float(args.gate_high_share_jump_max),
            "cross_max_insufficient_ratio": float(args.gate_cross_max_insufficient_ratio),
            "three_channel_min_presence": float(args.gate_three_channel_min_presence),
            "three_channel_min_std": float(args.gate_three_channel_min_std),
            "three_channel_min_unique": int(args.gate_three_channel_min_unique),
        },
        "gate_pairs_file": str(args.gate_pairs_file or ""),
        "gate_pair_count": int(len(args.gate_pair or [])),
    }


def _load_resume_state(resume_path: str, context: Dict[str, object], enabled: bool) -> Dict[str, object]:
    base = {
        "schema_version": VALIDATION_RESUME_SCHEMA_VERSION,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "context": _json_roundtrip_clone(context),
        "running_stage": None,
        "completed_stages": {},
        "gate_partial": {},
    }
    if not enabled:
        return base
    if not os.path.exists(resume_path):
        return base
    try:
        with open(resume_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"  [WARN] Resume file unreadable, restart from scratch: {resume_path} ({exc})")
        return base

    if payload.get("schema_version") != VALIDATION_RESUME_SCHEMA_VERSION:
        print("  [WARN] Resume schema changed, restart from scratch.")
        return base
    if payload.get("context") != context:
        print("  [WARN] Resume context changed, restart from scratch.")
        return base
    payload.setdefault("completed_stages", {})
    payload.setdefault("gate_partial", {})
    payload["updated_at"] = datetime.now().isoformat()
    return payload


def _save_resume_state(resume_path: str, state: Dict[str, object]):
    state["updated_at"] = datetime.now().isoformat()
    os.makedirs(os.path.dirname(resume_path), exist_ok=True)
    with open(resume_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _stage_is_completed(state: Dict[str, object], stage_key: str) -> bool:
    stage_row = (state.get("completed_stages") or {}).get(stage_key) or {}
    return bool(stage_row.get("done"))


def _mark_stage_running(state: Dict[str, object], resume_path: str, stage_key: str):
    state["running_stage"] = stage_key
    _save_resume_state(resume_path, state)


def _mark_stage_done(state: Dict[str, object], resume_path: str, stage_key: str, meta: Optional[Dict[str, object]] = None):
    completed = state.setdefault("completed_stages", {})
    completed[stage_key] = {
        "done": True,
        "completed_at": datetime.now().isoformat(),
        "meta": _json_roundtrip_clone(meta or {}),
    }
    state["running_stage"] = None
    _save_resume_state(resume_path, state)


def _run_stage_with_resume(
    stage_key: str,
    stage_label: str,
    run_fn: Callable[[], Optional[Dict[str, object]]],
    state: Dict[str, object],
    resume_path: str,
    resume_enabled: bool,
):
    if resume_enabled and _stage_is_completed(state, stage_key):
        print(f"[RESUME] Skip completed stage: {stage_label}")
        return
    if resume_enabled:
        _mark_stage_running(state, resume_path, stage_key)
    meta = run_fn() or {}
    if resume_enabled:
        _mark_stage_done(state, resume_path, stage_key, meta=meta)

def _parse_finite_float(value, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        score = float(value)
    except Exception:
        return default
    if not np.isfinite(score):
        return default
    return score


def _extract_score_with_fallback(rec: dict, score_field: str = "impact_score") -> float:
    fields = []
    normalized = str(score_field or "").strip()
    if normalized and normalized != "auto":
        fields.append(normalized)
    fields.extend([f for f in IMPACT_SCORE_FALLBACK_FIELDS if f not in fields])
    for field in fields:
        score = _parse_finite_float(rec.get(field))
        if score is not None:
            return float(score)
    return 0.0


def _extract_semantic(rec: dict) -> str:
    semantic = str(rec.get("impact_score_semantic", "")).strip()
    if semantic:
        return semantic
    semantic = str(rec.get("impact_primary_channel", "")).strip()
    if semantic:
        return semantic
    if _parse_finite_float(rec.get("diffusion_impact")) is not None:
        return "diffusion_impact"
    return IMPACT_DEFAULT_SEMANTIC


def _extract_channel_score(rec: dict, channel_name: str, fallback_fields: Optional[List[str]] = None) -> Optional[float]:
    channels = rec.get("impact_channels")
    if isinstance(channels, dict):
        score = _parse_finite_float(channels.get(channel_name))
        if score is not None:
            return float(score)
    for field in fallback_fields or []:
        score = _parse_finite_float(rec.get(field))
        if score is not None:
            return float(score)
    return None


def _normalize_pair_spec(raw: dict) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None

    higher = str(
        raw.get("higher_paper_id")
        or raw.get("higher")
        or raw.get("main_paper_id")
        or ""
    ).strip()
    lower = str(
        raw.get("lower_paper_id")
        or raw.get("lower")
        or raw.get("correction_paper_id")
        or ""
    ).strip()
    if not higher or not lower:
        return None

    name = str(raw.get("name") or raw.get("label") or f"{higher[:8]}>{lower[:8]}").strip()
    return {
        "name": name,
        "higher_paper_id": higher,
        "lower_paper_id": lower,
    }


def _parse_gate_pair_text(text: str) -> Optional[dict]:
    raw = str(text or "").strip()
    if not raw:
        return None

    if "|" in raw:
        pair_text, name = raw.split("|", 1)
        name = name.strip()
    else:
        pair_text, name = raw, ""

    for sep in (">", ",", ":"):
        if sep in pair_text:
            higher, lower = pair_text.split(sep, 1)
            higher = higher.strip()
            lower = lower.strip()
            if not higher or not lower:
                return None
            if not name:
                name = f"{higher[:8]}>{lower[:8]}"
            return {
                "name": name,
                "higher_paper_id": higher,
                "lower_paper_id": lower,
            }
    return None


def load_gate_pairs(pair_specs: Optional[List[str]] = None, pairs_file: Optional[str] = None) -> List[dict]:
    pairs: List[dict] = []

    for spec in pair_specs or []:
        item = _parse_gate_pair_text(spec)
        if item is not None:
            pairs.append(item)

    if pairs_file:
        try:
            with open(pairs_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:
            print(f"  [WARN] gate-pairs-file 璇诲彇澶辫触: {pairs_file} ({exc})")
            payload = None

        if isinstance(payload, dict):
            payload = payload.get("pairs", [])
        if isinstance(payload, list):
            for raw in payload:
                item = _normalize_pair_spec(raw)
                if item is not None:
                    pairs.append(item)

    if not pairs:
        pairs = [dict(item) for item in DEFAULT_GATE_PAIRS]

    dedup: Dict[tuple, dict] = {}
    for item in pairs:
        key = (item["higher_paper_id"], item["lower_paper_id"])
        if key not in dedup:
            dedup[key] = item
    return list(dedup.values())


def _default_gate_report_path(prefix: str, years: List[int]) -> str:
    safe_prefix = str(prefix).replace("/", "_").replace("\\", "_")
    sorted_years = sorted(int(y) for y in years) if years else [0]
    return os.path.join(
        OUTPUT_DIR,
        f"impact_v6_gate_report_{safe_prefix}_{sorted_years[0]}_{sorted_years[-1]}.json",
    )


def evaluate_zero_value_pileup_gate(
    years: List[int],
    prefix: str,
    score_field: str,
    max_top_share: float = 0.95,
    min_unique_scores: int = 3,
    score_round_decimals: int = 2,
    show_progress: bool = False,
) -> dict:
    total_count = 0
    zero_score_bins: Counter = Counter()

    for year in years:
        for rec in iter_year_data(year, prefix, show_progress=show_progress, progress_desc="gate.zero"):
            total_count += 1
            adoption_raw = _parse_finite_float(rec.get("adoption_raw"), 0.0) or 0.0
            if adoption_raw <= 1e-12:
                rounded_score = round(
                    _extract_score_with_fallback(rec, score_field=score_field),
                    int(max(score_round_decimals, 0)),
                )
                zero_score_bins[rounded_score] += 1

    if total_count <= 0:
        return {
            "name": "zero_value_pileup",
            "required": True,
            "passed": False,
            "status": "no_data",
            "total_count": 0,
            "zero_adoption_count": 0,
            "zero_adoption_ratio": 0.0,
        }

    zero_count = int(sum(zero_score_bins.values()))
    if zero_count <= 0:
        return {
            "name": "zero_value_pileup",
            "required": True,
            "passed": True,
            "status": "no_zero_adoption",
            "total_count": int(total_count),
            "zero_adoption_count": 0,
            "zero_adoption_ratio": 0.0,
        }

    sorted_bins = sorted(zero_score_bins.items(), key=lambda kv: (-kv[1], kv[0]))
    top_share = float(sorted_bins[0][1] / max(zero_count, 1))
    unique_count = int(len(zero_score_bins))
    passed = bool(unique_count >= int(max(min_unique_scores, 1)) and top_share <= float(max_top_share))
    top_bins = []
    for score_value, score_count in sorted_bins[:5]:
        top_bins.append(
            {
                "score": float(score_value),
                "count": int(score_count),
                "share": float(score_count / max(zero_count, 1)),
            }
        )

    return {
        "name": "zero_value_pileup",
        "required": True,
        "passed": passed,
        "status": "ok" if passed else "alert",
        "total_count": int(total_count),
        "zero_adoption_count": int(zero_count),
        "zero_adoption_ratio": float(zero_count / total_count),
        "unique_scores_rounded": unique_count,
        "top_score_share": top_share,
        "thresholds": {
            "max_top_share": float(max_top_share),
            "min_unique_scores": int(max(min_unique_scores, 1)),
            "score_round_decimals": int(max(score_round_decimals, 0)),
        },
        "top_score_bins": top_bins,
    }


def evaluate_pairwise_sanity_gate(
    years: List[int],
    prefix: str,
    score_field: str,
    pairs: List[dict],
    min_gap: float = 0.01,
    show_progress: bool = False,
) -> dict:
    if not pairs:
        return {
            "name": "pairwise_sanity",
            "required": False,
            "passed": True,
            "status": "skipped_no_pairs",
            "pair_count": 0,
        }

    target_ids = set()
    for pair in pairs:
        target_ids.add(pair["higher_paper_id"])
        target_ids.add(pair["lower_paper_id"])

    score_index: Dict[str, dict] = {}
    for year in years:
        for rec in iter_year_data(year, prefix, show_progress=show_progress, progress_desc="gate.pairwise"):
            pid = str(rec.get("paper_id", "")).strip()
            if not pid or pid not in target_ids or pid in score_index:
                continue
            score_index[pid] = {
                "paper_id": pid,
                "year": int(rec.get("pub_year", year) or year),
                "score": float(_extract_score_with_fallback(rec, score_field=score_field)),
            }

    checks = []
    missing = []
    for pair in pairs:
        high = score_index.get(pair["higher_paper_id"])
        low = score_index.get(pair["lower_paper_id"])
        if high is None or low is None:
            missing.append(pair["name"])
            checks.append(
                {
                    "name": pair["name"],
                    "status": "missing",
                    "higher_paper_id": pair["higher_paper_id"],
                    "lower_paper_id": pair["lower_paper_id"],
                }
            )
            continue

        gap = float(high["score"] - low["score"])
        direction_ok = bool(gap > float(min_gap))
        checks.append(
            {
                "name": pair["name"],
                "status": "ok" if direction_ok else "alert",
                "higher_paper_id": pair["higher_paper_id"],
                "lower_paper_id": pair["lower_paper_id"],
                "higher_score": float(high["score"]),
                "lower_score": float(low["score"]),
                "score_gap": gap,
                "higher_year": int(high["year"]),
                "lower_year": int(low["year"]),
            }
        )

    evaluated = [c for c in checks if c.get("status") != "missing"]
    direction_failed = [c for c in evaluated if c.get("status") == "alert"]
    passed = bool(len(missing) == 0 and len(direction_failed) == 0 and len(evaluated) > 0)

    if len(evaluated) <= 0:
        status = "insufficient_data"
    elif missing:
        status = "partial_data"
    elif direction_failed:
        status = "alert"
    else:
        status = "ok"

    return {
        "name": "pairwise_sanity",
        "required": True,
        "passed": passed,
        "status": status,
        "pair_count": int(len(pairs)),
        "evaluated_count": int(len(evaluated)),
        "missing_count": int(len(missing)),
        "direction_failed_count": int(len(direction_failed)),
        "thresholds": {
            "min_gap": float(min_gap),
        },
        "checks": checks,
    }


def evaluate_cross_year_stability_gate(
    years: List[int],
    prefix: str,
    score_field: str,
    percentile: float = 70.0,
    max_threshold_jump_ratio: float = 0.35,
    max_high_share_jump: float = 0.15,
    max_insufficient_ratio: float = 0.80,
    show_progress: bool = False,
) -> dict:
    yearly_stats = []
    pct = float(min(max(percentile, 1.0), 99.0))
    max_insufficient_ratio = float(min(max(max_insufficient_ratio, 0.0), 1.0))

    for year in years:
        score_buffer = array("f")
        insufficient_count = 0
        for rec in iter_year_data(year, prefix, show_progress=show_progress, progress_desc="gate.cross_year"):
            score_buffer.append(float(_extract_score_with_fallback(rec, score_field=score_field)))
            if bool(rec.get("insufficient_observable_window", False)):
                insufficient_count += 1
        scores = np.asarray(score_buffer, dtype=np.float64)
        if scores.size <= 0:
            continue
        pxx = float(np.percentile(scores, pct))
        high_share = float(np.mean(scores >= pxx))
        insufficient_ratio = float(insufficient_count / max(scores.size, 1))
        yearly_stats.append(
            {
                "year": int(year),
                "count": int(scores.size),
                "mean": float(scores.mean()),
                "p50": float(np.percentile(scores, 50)),
                "p70": pxx,
                "p90": float(np.percentile(scores, 90)),
                "high_share_at_p70": high_share,
                "insufficient_observable_ratio": insufficient_ratio,
            }
        )

    required = len(years) > 1
    if len(yearly_stats) < 2:
        return {
            "name": "cross_year_stability",
            "required": required,
            "passed": not required,
            "status": "insufficient_data",
            "yearly_stats": yearly_stats,
            "thresholds": {
                "percentile": pct,
                "max_threshold_jump_ratio": float(max_threshold_jump_ratio),
                "max_high_share_jump": float(max_high_share_jump),
                "max_insufficient_ratio": max_insufficient_ratio,
            },
        }

    yearly_stats = sorted(yearly_stats, key=lambda x: x["year"])
    excluded_years = [
        {
            "year": int(row["year"]),
            "insufficient_observable_ratio": float(row["insufficient_observable_ratio"]),
        }
        for row in yearly_stats
        if float(row.get("insufficient_observable_ratio", 0.0)) > max_insufficient_ratio
    ]
    effective_yearly_stats = [
        row for row in yearly_stats if float(row.get("insufficient_observable_ratio", 0.0)) <= max_insufficient_ratio
    ]

    if len(effective_yearly_stats) < 2:
        return {
            "name": "cross_year_stability",
            "required": required,
            "passed": not required,
            "status": "insufficient_effective_years",
            "year_count": int(len(yearly_stats)),
            "effective_year_count": int(len(effective_yearly_stats)),
            "excluded_year_count": int(len(excluded_years)),
            "excluded_years": excluded_years,
            "thresholds": {
                "percentile": pct,
                "max_threshold_jump_ratio": float(max_threshold_jump_ratio),
                "max_high_share_jump": float(max_high_share_jump),
                "max_insufficient_ratio": max_insufficient_ratio,
            },
            "yearly_stats": yearly_stats,
        }

    alerts = []
    jumps = []
    for prev, curr in zip(effective_yearly_stats, effective_yearly_stats[1:]):
        p70_jump_ratio = float(abs(curr["p70"] - prev["p70"]) / max(abs(prev["p70"]), 1e-6))
        high_share_jump = float(abs(curr["high_share_at_p70"] - prev["high_share_at_p70"]))
        jump_row = {
            "from_year": int(prev["year"]),
            "to_year": int(curr["year"]),
            "p70_jump_ratio": p70_jump_ratio,
            "high_share_jump": high_share_jump,
        }
        jumps.append(jump_row)
        if (
            p70_jump_ratio > float(max_threshold_jump_ratio)
            or high_share_jump > float(max_high_share_jump)
        ):
            alerts.append(jump_row)

    passed = len(alerts) == 0
    return {
        "name": "cross_year_stability",
        "required": required,
        "passed": passed,
        "status": "ok" if passed else "alert",
        "year_count": int(len(yearly_stats)),
        "effective_year_count": int(len(effective_yearly_stats)),
        "excluded_year_count": int(len(excluded_years)),
        "excluded_years": excluded_years,
        "thresholds": {
            "percentile": pct,
            "max_threshold_jump_ratio": float(max_threshold_jump_ratio),
            "max_high_share_jump": float(max_high_share_jump),
            "max_insufficient_ratio": max_insufficient_ratio,
        },
        "jumps": jumps,
        "alert_count": int(len(alerts)),
        "alerts": alerts,
        "yearly_stats": yearly_stats,
    }


def evaluate_three_channel_switch_gate(
    years: List[int],
    prefix: str,
    min_presence_ratio: float = 0.98,
    min_channel_std: float = 0.01,
    min_unique_scores: int = 5,
    required: bool = False,
    show_progress: bool = False,
) -> dict:
    channel_fallbacks = {
        "diffusion_impact": ["diffusion_impact", "impact_score"],
        "foundation_utility": ["foundation_utility_norm"],
        "method_transferability": ["method_transferability_norm"],
    }
    channel_present_counts: Dict[str, int] = {k: 0 for k in channel_fallbacks.keys()}
    channel_stats: Dict[str, OnlineStats] = {k: OnlineStats() for k in channel_fallbacks.keys()}
    channel_unique_rounded: Dict[str, set] = {k: set() for k in channel_fallbacks.keys()}
    total_count = 0
    complete_count = 0
    missing_samples = []

    min_presence_ratio = float(min(max(min_presence_ratio, 0.0), 1.0))
    min_channel_std = float(max(min_channel_std, 0.0))
    min_unique_scores = int(max(min_unique_scores, 1))

    for year in years:
        for rec in iter_year_data(year, prefix, show_progress=show_progress, progress_desc="gate.three_channel"):
            total_count += 1
            paper_id = str(rec.get("paper_id", "")).strip() or f"year:{year}"
            missing_channels = []
            for channel_name, fallback_fields in channel_fallbacks.items():
                score = _extract_channel_score(rec, channel_name, fallback_fields=fallback_fields)
                if score is None:
                    missing_channels.append(channel_name)
                    continue
                score = float(score)
                channel_present_counts[channel_name] += 1
                channel_stats[channel_name].add(score)
                channel_unique_rounded[channel_name].add(round(score, 2))

            if missing_channels:
                if len(missing_samples) < 5:
                    missing_samples.append(
                        {
                            "paper_id": paper_id,
                            "missing_channels": missing_channels,
                        }
                    )
            else:
                complete_count += 1

    if total_count <= 0:
        return {
            "name": "three_channel_switch_readiness",
            "required": bool(required),
            "passed": False,
            "status": "no_data",
            "total_count": 0,
            "complete_count": 0,
            "complete_ratio": 0.0,
            "channels": {},
        }

    channel_metrics = {}
    presence_ok = True
    std_ok = True
    unique_ok = True
    for channel_name in channel_fallbacks.keys():
        present_count = int(channel_present_counts[channel_name])
        presence_ratio = float(present_count / max(total_count, 1))
        std_value = float(channel_stats[channel_name].std()) if present_count > 0 else 0.0
        unique_count = int(len(channel_unique_rounded[channel_name])) if present_count > 0 else 0
        channel_metrics[channel_name] = {
            "count": present_count,
            "presence_ratio": presence_ratio,
            "std": std_value,
            "unique_scores_rounded": unique_count,
        }
        if presence_ratio < min_presence_ratio:
            presence_ok = False
        if std_value < min_channel_std:
            std_ok = False
        if unique_count < min_unique_scores:
            unique_ok = False

    complete_ratio = float(complete_count / max(total_count, 1))
    complete_ok = bool(complete_ratio >= min_presence_ratio)
    passed = bool(presence_ok and std_ok and unique_ok and complete_ok)

    return {
        "name": "three_channel_switch_readiness",
        "required": bool(required),
        "passed": passed,
        "status": "ok" if passed else "alert",
        "total_count": int(total_count),
        "complete_count": int(complete_count),
        "complete_ratio": complete_ratio,
        "thresholds": {
            "min_presence_ratio": min_presence_ratio,
            "min_channel_std": min_channel_std,
            "min_unique_scores_rounded": min_unique_scores,
        },
        "checks": {
            "presence_ok": bool(presence_ok),
            "std_ok": bool(std_ok),
            "unique_ok": bool(unique_ok),
            "complete_ok": bool(complete_ok),
        },
        "channels": channel_metrics,
        "sample_missing": missing_samples,
    }


def generate_feasibility_gate_report(
    years: List[int],
    prefix: str,
    score_field: str,
    output_path: Optional[str] = None,
    pair_specs: Optional[List[str]] = None,
    pairs_file: Optional[str] = None,
    pair_min_gap: float = 0.01,
    zero_max_top_share: float = 0.90,
    zero_min_unique_scores: int = 3,
    threshold_jump_ratio_max: float = 0.35,
    high_share_jump_max: float = 0.15,
    cross_max_insufficient_ratio: float = 0.80,
    require_three_channel_gate: bool = False,
    three_channel_min_presence: float = 0.98,
    three_channel_min_std: float = 0.01,
    three_channel_min_unique: int = 5,
    cached_gates: Optional[Dict[str, dict]] = None,
    on_partial_update: Optional[Callable[[Dict[str, dict]], None]] = None,
    show_progress: bool = False,
) -> tuple:
    years = sorted(int(y) for y in years)
    pairs = load_gate_pairs(pair_specs=pair_specs, pairs_file=pairs_file)
    gates = dict(cached_gates or {})

    if "zero_value_pileup" not in gates:
        gates["zero_value_pileup"] = evaluate_zero_value_pileup_gate(
            years=years,
            prefix=prefix,
            score_field=score_field,
            max_top_share=zero_max_top_share,
            min_unique_scores=zero_min_unique_scores,
            show_progress=show_progress,
        )
        if on_partial_update is not None:
            on_partial_update(gates)

    if "pairwise_sanity" not in gates:
        gates["pairwise_sanity"] = evaluate_pairwise_sanity_gate(
            years=years,
            prefix=prefix,
            score_field=score_field,
            pairs=pairs,
            min_gap=pair_min_gap,
            show_progress=show_progress,
        )
        if on_partial_update is not None:
            on_partial_update(gates)

    if "cross_year_stability" not in gates:
        gates["cross_year_stability"] = evaluate_cross_year_stability_gate(
            years=years,
            prefix=prefix,
            score_field=score_field,
            percentile=70.0,
            max_threshold_jump_ratio=threshold_jump_ratio_max,
            max_high_share_jump=high_share_jump_max,
            max_insufficient_ratio=cross_max_insufficient_ratio,
            show_progress=show_progress,
        )
        if on_partial_update is not None:
            on_partial_update(gates)

    if "three_channel_switch_readiness" not in gates:
        gates["three_channel_switch_readiness"] = evaluate_three_channel_switch_gate(
            years=years,
            prefix=prefix,
            min_presence_ratio=three_channel_min_presence,
            min_channel_std=three_channel_min_std,
            min_unique_scores=three_channel_min_unique,
            required=require_three_channel_gate,
            show_progress=show_progress,
        )
        if on_partial_update is not None:
            on_partial_update(gates)

    required_gates = [g for g in gates.values() if bool(g.get("required", True))]
    overall_passed = bool(all(bool(g.get("passed", False)) for g in required_gates))

    if output_path is None:
        output_path = _default_gate_report_path(prefix=prefix, years=years)

    report = {
        "generated_at": datetime.now().isoformat(),
        "prefix": prefix,
        "years": years,
        "score_field": score_field,
        "overall_passed": overall_passed,
        "required_gate_count": int(len(required_gates)),
        "passed_required_gate_count": int(sum(1 for g in required_gates if g.get("passed", False))),
        "gates": gates,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return report, output_path


def load_year_score_map(
    year: int,
    prefix: str,
    score_field: str = "impact_score",
    *,
    show_progress: bool = False,
) -> Dict[str, float]:
    score_map: Dict[str, float] = {}
    for rec in iter_year_data(year, prefix, show_progress=show_progress, progress_desc="ab.score_map"):
        paper_id = str(rec.get("paper_id", "")).strip()
        if not paper_id:
            continue
        score = _extract_score_with_fallback(rec, score_field=score_field)
        score_map[paper_id] = score
    return score_map


def summarize_values(values: np.ndarray) -> Dict[str, float]:
    if values.size == 0:
        return {
            "count": 0,
            "mean": 0.0,
            "std": 0.0,
            "p50": 0.0,
            "p90": 0.0,
            "max": 0.0,
        }
    return {
        "count": int(values.size),
        "mean": float(values.mean()),
        "std": float(values.std()),
        "p50": float(np.percentile(values, 50)),
        "p90": float(np.percentile(values, 90)),
        "max": float(values.max()),
    }


def compare_prefixes(
    years: List[int],
    prefix_a: str,
    prefix_b: str,
    top_share: float = 0.01,
    score_field: str = "impact_score",
    output_path: Optional[str] = None,
    show_progress: bool = False,
):
    print("\n" + "=" * 60)
    print("A/B Compare (Impact V6)")
    print("=" * 60)
    print(f"  A: {prefix_a}")
    print(f"  B: {prefix_b}")
    print(f"  Top-share: {top_share:.2%}")
    print(f"  Score field: {score_field} (fallback: {', '.join(IMPACT_SCORE_FALLBACK_FIELDS)})")

    top_share = min(max(float(top_share), 1e-6), 0.5)
    yearly_metrics = []
    total_overlap = 0
    weighted_head_overlap = 0.0
    weighted_jaccard = 0.0
    weighted_mean_delta = 0.0

    for year in years:
        scores_a = load_year_score_map(year, prefix_a, score_field=score_field, show_progress=show_progress)
        scores_b = load_year_score_map(year, prefix_b, score_field=score_field, show_progress=show_progress)
        if not scores_a and not scores_b:
            print(f"  {year}: [MISSING] both files missing")
            continue

        a_vals = np.asarray(list(scores_a.values()), dtype=np.float64)
        b_vals = np.asarray(list(scores_b.values()), dtype=np.float64)
        common_ids = [pid for pid in scores_a.keys() if pid in scores_b]
        overlap_n = len(common_ids)

        if overlap_n > 0:
            a_common = np.asarray([scores_a[pid] for pid in common_ids], dtype=np.float64)
            b_common = np.asarray([scores_b[pid] for pid in common_ids], dtype=np.float64)
            delta = b_common - a_common
            mean_delta = float(delta.mean())
            median_delta = float(np.percentile(delta, 50))
            p90_delta = float(np.percentile(delta, 90))

            top_n = max(1, int(overlap_n * top_share))
            top_a = {
                pid
                for pid, _ in heapq.nlargest(
                    top_n,
                    ((pid, scores_a[pid]) for pid in common_ids),
                    key=lambda item: item[1],
                )
            }
            top_b = {
                pid
                for pid, _ in heapq.nlargest(
                    top_n,
                    ((pid, scores_b[pid]) for pid in common_ids),
                    key=lambda item: item[1],
                )
            }
            inter = len(top_a & top_b)
            union = len(top_a | top_b)
            head_overlap = inter / top_n if top_n > 0 else 0.0
            head_jaccard = inter / union if union > 0 else 1.0
        else:
            mean_delta = 0.0
            median_delta = 0.0
            p90_delta = 0.0
            top_n = 0
            head_overlap = 0.0
            head_jaccard = 0.0

        metric = {
            "year": int(year),
            "a_count": int(len(scores_a)),
            "b_count": int(len(scores_b)),
            "overlap_count": int(overlap_n),
            "overlap_ratio_a": float(overlap_n / len(scores_a)) if scores_a else 0.0,
            "overlap_ratio_b": float(overlap_n / len(scores_b)) if scores_b else 0.0,
            "a_distribution": summarize_values(a_vals),
            "b_distribution": summarize_values(b_vals),
            "delta_mean": mean_delta,
            "delta_median": median_delta,
            "delta_p90": p90_delta,
            "top_n": int(top_n),
            "head_overlap_ratio": float(head_overlap),
            "head_jaccard": float(head_jaccard),
        }
        yearly_metrics.append(metric)

        total_overlap += overlap_n
        weighted_head_overlap += head_overlap * overlap_n
        weighted_jaccard += head_jaccard * overlap_n
        weighted_mean_delta += mean_delta * overlap_n

        print(
            f"  {year}: overlap={overlap_n:,}, "
            f"螖mean={mean_delta:+.3f}, head@{top_share:.1%} overlap={head_overlap:.3f}, jaccard={head_jaccard:.3f}"
        )

    if total_overlap > 0:
        overall = {
            "overlap_count": int(total_overlap),
            "weighted_delta_mean": float(weighted_mean_delta / total_overlap),
            "weighted_head_overlap_ratio": float(weighted_head_overlap / total_overlap),
            "weighted_head_jaccard": float(weighted_jaccard / total_overlap),
        }
    else:
        overall = {
            "overlap_count": 0,
            "weighted_delta_mean": 0.0,
            "weighted_head_overlap_ratio": 0.0,
            "weighted_head_jaccard": 0.0,
        }

    if output_path is None:
        safe_a = prefix_a.replace("/", "_")
        safe_b = prefix_b.replace("/", "_")
        output_path = os.path.join(
            OUTPUT_DIR,
            f"impact_v6_ab_compare_{safe_a}_vs_{safe_b}_{min(years)}_{max(years)}.json",
        )

    report = {
        "prefix_a": prefix_a,
        "prefix_b": prefix_b,
        "years": [int(y) for y in years],
        "top_share": float(top_share),
        "overall": overall,
        "yearly_metrics": yearly_metrics,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n  Report written: {output_path}")
    print(
        "  Overall: overlap={overlap:,}, 螖mean={delta:+.3f}, head_overlap={head:.3f}, jaccard={jaccard:.3f}".format(
            overlap=overall["overlap_count"],
            delta=overall["weighted_delta_mean"],
            head=overall["weighted_head_overlap_ratio"],
            jaccard=overall["weighted_head_jaccard"],
        )
    )


def _count_records(path: str, *, show_progress: bool = False, progress_desc: str = "count") -> int:
    if not os.path.exists(path):
        return 0
    count = 0
    pbar = None
    if show_progress and PROGRESS_ENABLED and tqdm is not None:
        try:
            total_bytes = os.path.getsize(path)
        except OSError:
            total_bytes = None
        pbar = tqdm(
            total=total_bytes,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc=progress_desc,
            leave=False,
        )
    try:
        with open(path, "rb") as f:
            for raw_line in f:
                if pbar is not None:
                    pbar.update(len(raw_line))
                if raw_line.strip():
                    count += 1
    finally:
        if pbar is not None:
            pbar.close()
    return count


def validate_completeness(years: List[int], prefix: str, *, show_progress: bool = False):
    print("\n" + "=" * 60)
    print("1. Data Completeness Check")
    print("=" * 60)
    total = 0
    for year in years:
        path = _year_file(year, prefix)
        if not os.path.exists(path):
            print(f"  [MISSING] {year}")
            continue
        count = _count_records(path, show_progress=show_progress, progress_desc=f"count {year}")
        total += count
        print(f"  {year}: {count:>10,} papers")
    print(f"\n  Total: {total:,} papers")


def validate_distributions(
    years: List[int],
    prefix: str,
    score_field: str = "impact_score",
    *,
    show_progress: bool = False,
):
    print("\n" + "=" * 60)
    print("2. Score Distribution Analysis (V6)")
    print("=" * 60)

    signal_buffers: Dict[str, array] = {
        f"{score_field}(resolved)": array("f"),
        "adoption_norm": array("f"),
        "consistency": array("f"),
        "consistency_gate": array("f"),
        "object_count": array("f"),
        "foundation_raw": array("f"),
        "foundation_norm": array("f"),
        "method_raw": array("f"),
        "method_norm": array("f"),
    }
    semantic_counts = defaultdict(int)

    for year in years:
        for d in iter_year_data(year, prefix, show_progress=show_progress, progress_desc="dist"):
            signal_buffers[f"{score_field}(resolved)"].append(float(_extract_score_with_fallback(d, score_field=score_field)))
            signal_buffers["adoption_norm"].append(float(_parse_finite_float(d.get("adoption_norm"), 0.0) or 0.0))
            signal_buffers["consistency"].append(float(_parse_finite_float(d.get("consistency"), 0.0) or 0.0))
            signal_buffers["consistency_gate"].append(float(_parse_finite_float(d.get("consistency_gate"), 0.0) or 0.0))
            signal_buffers["object_count"].append(float(_parse_finite_float(d.get("object_count"), 0.0) or 0.0))
            signal_buffers["foundation_raw"].append(
                float(_parse_finite_float(d.get("foundation_utility_raw"), 0.0) or 0.0)
            )
            signal_buffers["foundation_norm"].append(
                float(_parse_finite_float(d.get("foundation_utility_norm"), 0.0) or 0.0)
            )
            signal_buffers["method_raw"].append(
                float(_parse_finite_float(d.get("method_transferability_raw"), 0.0) or 0.0)
            )
            signal_buffers["method_norm"].append(
                float(_parse_finite_float(d.get("method_transferability_norm"), 0.0) or 0.0)
            )
            semantic_counts[_extract_semantic(d)] += 1

    if len(signal_buffers[f"{score_field}(resolved)"]) <= 0:
        print("  [FAIL] No data")
        return

    print(f"\n  {'Signal':<20} {'Mean':>10} {'Std':>10} {'P50':>10} {'P90':>10} {'Max':>10}")
    print("  " + "-" * 72)

    for name, buf in signal_buffers.items():
        a = np.asarray(buf, dtype=np.float64)
        print(
            f"  {name:<20} {a.mean():>10.2f} {a.std():>10.2f} "
            f"{np.percentile(a, 50):>10.2f} {np.percentile(a, 90):>10.2f} {a.max():>10.2f}"
        )

    if semantic_counts:
        print("\n  Impact semantics:")
        for key, value in sorted(semantic_counts.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  - {key}: {value:,}")


def validate_yearly_trends(
    years: List[int],
    prefix: str,
    score_field: str = "impact_score",
    *,
    show_progress: bool = False,
):
    print("\n" + "=" * 60)
    print("3. Yearly Trend Analysis")
    print("=" * 60)

    print(f"\n  {'Year':<6} {'Papers':>10} {'Mean':>10} {'P50':>10} {'P90':>10} {'>50':>10}")
    print("  " + "-" * 60)

    for year in years:
        score_buffer = array("f")
        for rec in iter_year_data(year, prefix, show_progress=show_progress, progress_desc="trend"):
            score_buffer.append(float(_extract_score_with_fallback(rec, score_field=score_field)))

        if len(score_buffer) <= 0:
            print(f"  {year:<6} [MISSING]")
            continue

        scores = np.asarray(score_buffer, dtype=np.float64)
        high_ratio = 100.0 * np.sum(scores > 50.0) / len(scores)
        print(
            f"  {year:<6} {len(score_buffer):>10,} {scores.mean():>10.2f} "
            f"{np.percentile(scores, 50):>10.2f} {np.percentile(scores, 90):>10.2f} {high_ratio:>9.1f}%"
        )


def validate_gate_distribution(years: List[int], prefix: str, *, show_progress: bool = False):
    print("\n" + "=" * 60)
    print("4. Consistency Gate Distribution")
    print("=" * 60)

    gates = array("f")
    for year in years:
        for d in iter_year_data(year, prefix, show_progress=show_progress, progress_desc="gate_dist"):
            gates.append(float(_parse_finite_float(d.get("consistency_gate"), 0.0) or 0.0))

    if len(gates) <= 0:
        print("  [FAIL] No data")
        return

    a = np.asarray(gates, dtype=np.float64)
    bins = [
        (0.0, 0.001, "Zero (gate=0)"),
        (0.001, 0.25, "Low (0-0.25)"),
        (0.25, 0.5, "Medium (0.25-0.5)"),
        (0.5, 1.0, "High (0.5-1.0)"),
        (1.0, 1.01, "Max (1.0)"),
    ]

    print(f"\n  {'Range':<25} {'Count':>12} {'Percent':>10}")
    print("  " + "-" * 50)
    for low, high, label in bins:
        count = int(np.sum((a >= low) & (a < high)))
        pct = 100.0 * count / len(a)
        print(f"  {label:<25} {count:>12,} {pct:>9.1f}%")


def sample_inspection(
    years: List[int],
    prefix: str,
    n: int = 5,
    score_field: str = "impact_score",
    *,
    show_progress: bool = False,
):
    print("\n" + "=" * 60)
    print("5. Sample Inspection (High/Low Impact)")
    print("=" * 60)

    top_heap: List[Tuple[float, int, dict]] = []
    bottom_non_zero_heap: List[Tuple[float, int, dict]] = []
    total_count = 0
    zero_count = 0
    seq = 0

    for year in years:
        for rec in iter_year_data(year, prefix, show_progress=show_progress, progress_desc="sample"):
            total_count += 1
            score = float(_extract_score_with_fallback(rec, score_field=score_field))
            row = {
                "paper_id": str(rec.get("paper_id", "")),
                "pub_year": int(rec.get("pub_year", year) or year),
                "impact": score,
                "adoption_norm": float(_parse_finite_float(rec.get("adoption_norm"), 0.0) or 0.0),
                "consistency_gate": float(_parse_finite_float(rec.get("consistency_gate"), 0.0) or 0.0),
                "object_count": int(_parse_finite_float(rec.get("object_count"), 0.0) or 0.0),
            }

            if len(top_heap) < n:
                heapq.heappush(top_heap, (score, seq, row))
            elif score > top_heap[0][0]:
                heapq.heapreplace(top_heap, (score, seq, row))

            if score > 0.0:
                if len(bottom_non_zero_heap) < n:
                    heapq.heappush(bottom_non_zero_heap, (-score, seq, row))
                elif score < -bottom_non_zero_heap[0][0]:
                    heapq.heapreplace(bottom_non_zero_heap, (-score, seq, row))
            else:
                zero_count += 1
            seq += 1

    if total_count <= 0:
        print("  [FAIL] No data")
        return

    top_rows = [item[2] for item in sorted(top_heap, key=lambda x: x[0], reverse=True)]
    bottom_rows = [item[2] for item in sorted(bottom_non_zero_heap, key=lambda x: -x[0])]

    print(f"\n  === Top {n} Impact ===")
    for d in top_rows:
        impact = float(d["impact"])
        print(
            f"  {d['paper_id'][:16]}... ({d['pub_year']}): "
            f"impact={impact:.1f}, "
            f"adoption={d['adoption_norm']:.1f}, "
            f"gate={d['consistency_gate']:.3f}, "
            f"objects={d['object_count']}"
        )

    print(f"\n  === Bottom {n} Impact (non-zero) ===")
    for d in bottom_rows:
        impact = float(d["impact"])
        print(
            f"  {d['paper_id'][:16]}... ({d['pub_year']}): "
            f"impact={impact:.1f}, "
            f"adoption={d['adoption_norm']:.1f}, "
            f"gate={d['consistency_gate']:.3f}, "
            f"objects={d['object_count']}"
        )

    print(f"\n  Zero impact papers: {zero_count:,} ({100.0*zero_count/max(total_count,1):.1f}%)")


def validate_type_distribution(years: List[int], prefix: str, *, show_progress: bool = False):
    print("\n" + "=" * 60)
    print("6. Paper Type Distribution")
    print("=" * 60)

    counts = defaultdict(int)
    total = 0
    for year in years:
        for d in iter_year_data(year, prefix, show_progress=show_progress, progress_desc="type_dist"):
            counts[d.get("paper_type_detected", "unknown")] += 1
            total += 1

    if total == 0:
        print("  [FAIL] No data")
        return

    for k, v in sorted(counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {k:<16} {v:>10,} ({100.0*v/total:>5.1f}%)")


def validate_channel_traceability(years: List[int], prefix: str, *, show_progress: bool = False):
    print("\n" + "=" * 60)
    print("8. Channel Traceability Check (V6.3)")
    print("=" * 60)

    total = 0
    has_channel_vector = 0
    has_three_channel_vector = 0
    diffusion_traceable = 0
    foundation_traceable = 0
    method_traceable = 0
    missing_diffusion_samples = []
    missing_foundation_samples = []
    missing_method_samples = []

    for year in years:
        for rec in iter_year_data(year, prefix, show_progress=show_progress, progress_desc="trace"):
            total += 1
            paper_id = str(rec.get("paper_id", "")).strip()
            top_objects = rec.get("top_objects", [])
            has_top_objects = isinstance(top_objects, list) and len(top_objects) > 0
            has_object_count = int(_parse_finite_float(rec.get("object_count"), 0.0) or 0.0) > 0

            impact_channels = rec.get("impact_channels")
            if isinstance(impact_channels, dict) and len(impact_channels) > 0:
                has_channel_vector += 1
                if (
                    _parse_finite_float(impact_channels.get("diffusion_impact")) is not None
                    and _parse_finite_float(impact_channels.get("foundation_utility")) is not None
                    and _parse_finite_float(impact_channels.get("method_transferability")) is not None
                ):
                    has_three_channel_vector += 1

            diffusion_score = _extract_channel_score(
                rec,
                "diffusion_impact",
                fallback_fields=["diffusion_impact", "impact_score"],
            )
            impact_score = _parse_finite_float(rec.get("impact_score"))
            if (diffusion_score is not None or impact_score is not None) and has_top_objects:
                diffusion_traceable += 1
            elif len(missing_diffusion_samples) < 5:
                missing_diffusion_samples.append(paper_id or f"year:{year}")

            foundation_raw = _parse_finite_float(rec.get("foundation_utility_raw"))
            foundation_norm = _extract_channel_score(
                rec,
                "foundation_utility",
                fallback_fields=["foundation_utility_norm"],
            )
            if foundation_raw is not None and foundation_norm is not None and (has_top_objects or has_object_count):
                foundation_traceable += 1
            elif len(missing_foundation_samples) < 5:
                missing_foundation_samples.append(paper_id or f"year:{year}")

            method_raw = _parse_finite_float(rec.get("method_transferability_raw"))
            method_norm = _extract_channel_score(
                rec,
                "method_transferability",
                fallback_fields=["method_transferability_norm"],
            )
            has_task_core = False
            if isinstance(top_objects, list):
                for item in top_objects:
                    if isinstance(item, dict) and str(item.get("task_core", "")).strip():
                        has_task_core = True
                        break
            if method_raw is not None and method_norm is not None and (has_task_core or has_top_objects):
                method_traceable += 1
            elif len(missing_method_samples) < 5:
                missing_method_samples.append(paper_id or f"year:{year}")

    if total <= 0:
        print("  [FAIL] No data")
        return

    print(f"  total_records: {total:,}")
    print(f"  channel_vector_presence: {has_channel_vector:,} ({100.0*has_channel_vector/total:.1f}%)")
    print(f"  three_channel_vector_presence: {has_three_channel_vector:,} ({100.0*has_three_channel_vector/total:.1f}%)")
    print(f"  diffusion_traceable: {diffusion_traceable:,} ({100.0*diffusion_traceable/total:.1f}%)")
    print(f"  foundation_traceable: {foundation_traceable:,} ({100.0*foundation_traceable/total:.1f}%)")
    print(f"  method_traceable: {method_traceable:,} ({100.0*method_traceable/total:.1f}%)")

    if missing_diffusion_samples:
        print(f"  sample_missing_diffusion_trace: {missing_diffusion_samples}")
    if missing_foundation_samples:
        print(f"  sample_missing_foundation_trace: {missing_foundation_samples}")
    if missing_method_samples:
        print(f"  sample_missing_method_trace: {missing_method_samples}")


def main():
    global PROGRESS_ENABLED
    parser = argparse.ArgumentParser(description="Validate Impact V6")
    parser.add_argument("--year", type=int, help="Validate a specific year")
    parser.add_argument("--sample", type=int, default=5, help="Sample size for inspection")
    parser.add_argument("--prefix", type=str, default=None, help="File prefix, default impact_v6_final")
    parser.add_argument(
        "--score-field",
        type=str,
        default="impact_score",
        help="Primary score field (impact_score|diffusion_impact|auto)",
    )
    parser.add_argument("--compare-prefix-a", type=str, default=None, help="A version file prefix")
    parser.add_argument("--compare-prefix-b", type=str, default=None, help="B version file prefix")
    parser.add_argument(
        "--compare-top-share",
        type=float,
        default=0.01,
        help="Top-share used by head overlap comparison (default 0.01 = Top 1%%)",
    )
    parser.add_argument("--compare-output", type=str, default=None, help="A/B comparison output JSON path")
    parser.add_argument("--compare-only", action="store_true", help="Only run A/B comparison")
    parser.add_argument("--skip-gate-report", action="store_true", help="Skip feasibility gate report")
    parser.add_argument("--gate-report-output", type=str, default=None, help="Feasibility gate report output path")
    parser.add_argument(
        "--gate-pair",
        action="append",
        default=[],
        help="Pair constraint format higher_id>lower_id, optional suffix |name",
    )
    parser.add_argument("--gate-pairs-file", type=str, default=None, help="Pair file path in JSON")
    parser.add_argument("--gate-min-gap", type=float, default=0.01, help="Pair minimal gap threshold")
    parser.add_argument(
        "--gate-zero-top-share-max",
        type=float,
        default=0.95,
        help="Zero-value pile-up gate: max share of top score bin",
    )
    parser.add_argument(
        "--gate-zero-min-unique",
        type=int,
        default=3,
        help="Zero-value pile-up gate: minimum unique rounded scores",
    )
    parser.add_argument(
        "--gate-threshold-jump-max",
        type=float,
        default=0.35,
        help="Cross-year gate: maximum year-over-year P70 jump ratio",
    )
    parser.add_argument(
        "--gate-high-share-jump-max",
        type=float,
        default=0.15,
        help="Cross-year gate: maximum year-over-year high-share jump",
    )
    parser.add_argument(
        "--gate-cross-max-insufficient-ratio",
        type=float,
        default=0.80,
        help="Cross-year gate: exclude years whose insufficient_observable_window ratio is above this value",
    )
    parser.add_argument(
        "--gate-require-three-channel",
        action="store_true",
        help="将三通道切换门禁设为 required（默认仅报告不阻断）",
    )
    parser.add_argument(
        "--gate-three-channel-min-presence",
        type=float,
        default=0.98,
        help="三通道门禁最小覆盖率阈值",
    )
    parser.add_argument(
        "--gate-three-channel-min-std",
        type=float,
        default=0.01,
        help="三通道门禁最小标准差阈值",
    )
    parser.add_argument(
        "--gate-three-channel-min-unique",
        type=int,
        default=5,
        help="三通道门禁最小离散分段数阈值（两位小数）",
    )
    parser.add_argument("--config", type=str, default=None, help="Config JSON path")
    parser.add_argument(
        "--resume",
        dest="resume",
        action="store_true",
        help="Resume from validation checkpoint (default: enabled)",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Disable resume and rerun all validation stages",
    )
    parser.add_argument(
        "--resume-path",
        type=str,
        default=None,
        help="Validation checkpoint file path",
    )
    parser.add_argument(
        "--progress",
        dest="show_progress",
        action="store_true",
        help="Enable realtime progress bars (default: enabled)",
    )
    parser.add_argument(
        "--no-progress",
        dest="show_progress",
        action="store_false",
        help="Disable progress bars",
    )
    parser.set_defaults(resume=True, show_progress=True)
    args = parser.parse_args()

    PROGRESS_ENABLED = bool(args.show_progress)
    apply_config(args.config)
    prefix = args.prefix or DEFAULT_FINAL_PREFIX

    years = [args.year] if args.year else DEFAULT_YEARS
    resume_path = args.resume_path or _default_validation_resume_path(prefix, years)
    resume_context = _build_resume_context(prefix, years, args)
    resume_state = _load_resume_state(resume_path, resume_context, enabled=bool(args.resume))
    if args.resume:
        _save_resume_state(resume_path, resume_state)

    print("=" * 60)
    print("Impact V6 Validation")
    print("=" * 60)
    print(f"Output Dir: {OUTPUT_DIR}")
    print(f"File Prefix: {prefix}")
    print(f"Score Field: {args.score_field} (fallback: {', '.join(IMPACT_SCORE_FALLBACK_FIELDS)})")
    print(f"Progress Bars: {'ON' if PROGRESS_ENABLED and tqdm is not None else 'OFF'}")
    print(f"Resume: {'ON' if args.resume else 'OFF'}")
    if args.resume:
        print(f"Resume Path: {resume_path}")

    def run_stage(stage_key: str, stage_label: str, fn: Callable[[], Optional[Dict[str, object]]]):
        _run_stage_with_resume(
            stage_key=stage_key,
            stage_label=stage_label,
            run_fn=fn,
            state=resume_state,
            resume_path=resume_path,
            resume_enabled=bool(args.resume),
        )

    if args.compare_prefix_a and args.compare_prefix_b:
        def _stage_compare():
            compare_prefixes(
                years=years,
                prefix_a=args.compare_prefix_a,
                prefix_b=args.compare_prefix_b,
                top_share=args.compare_top_share,
                score_field=args.score_field,
                output_path=args.compare_output,
                show_progress=PROGRESS_ENABLED,
            )
            return {
                "prefix_a": args.compare_prefix_a,
                "prefix_b": args.compare_prefix_b,
                "top_share": float(args.compare_top_share),
            }

        run_stage("00_ab_compare", "A/B Compare", _stage_compare)
        if args.compare_only:
            print("\n" + "=" * 60 + "\nDone\n")
            return
    elif args.compare_prefix_a or args.compare_prefix_b:
        print("  [WARN] compare-prefix-a and compare-prefix-b must be provided together; skipped A/B compare.")

    run_stage(
        "01_completeness",
        "Data Completeness Check",
        lambda: (
            validate_completeness(years, prefix, show_progress=PROGRESS_ENABLED),
            {"years": len(years)},
        )[1],
    )
    run_stage(
        "02_distribution",
        "Score Distribution Analysis",
        lambda: (
            validate_distributions(years, prefix, score_field=args.score_field, show_progress=PROGRESS_ENABLED),
            {"years": len(years), "score_field": args.score_field},
        )[1],
    )
    run_stage(
        "03_yearly_trend",
        "Yearly Trend Analysis",
        lambda: (
            validate_yearly_trends(years, prefix, score_field=args.score_field, show_progress=PROGRESS_ENABLED),
            {"years": len(years), "score_field": args.score_field},
        )[1],
    )
    run_stage(
        "04_gate_distribution",
        "Consistency Gate Distribution",
        lambda: (
            validate_gate_distribution(years, prefix, show_progress=PROGRESS_ENABLED),
            {"years": len(years)},
        )[1],
    )
    run_stage(
        "05_sample_inspection",
        "Sample Inspection",
        lambda: (
            sample_inspection(years, prefix, args.sample, score_field=args.score_field, show_progress=PROGRESS_ENABLED),
            {"years": len(years), "sample": int(args.sample)},
        )[1],
    )
    run_stage(
        "06_type_distribution",
        "Paper Type Distribution",
        lambda: (
            validate_type_distribution(years, prefix, show_progress=PROGRESS_ENABLED),
            {"years": len(years)},
        )[1],
    )

    if not args.skip_gate_report:
        def _update_gate_partial(gates: Dict[str, dict]):
            if not args.resume:
                return
            resume_state["gate_partial"] = {
                "updated_at": datetime.now().isoformat(),
                "gates": _json_roundtrip_clone(gates),
            }
            _save_resume_state(resume_path, resume_state)

        def _stage_gate_report():
            print("\n" + "=" * 60)
            print("7. Feasibility Gate Report (V6.3)")
            print("=" * 60)
            cached_gates = {}
            if args.resume:
                cached_gates = dict((resume_state.get("gate_partial") or {}).get("gates") or {})
                if cached_gates:
                    print(f"[RESUME] Gate sub-steps restored: {', '.join(sorted(cached_gates.keys()))}")
            gate_report, gate_report_path = generate_feasibility_gate_report(
                years=years,
                prefix=prefix,
                score_field=args.score_field,
                output_path=args.gate_report_output,
                pair_specs=args.gate_pair,
                pairs_file=args.gate_pairs_file,
                pair_min_gap=args.gate_min_gap,
                zero_max_top_share=args.gate_zero_top_share_max,
                zero_min_unique_scores=args.gate_zero_min_unique,
                threshold_jump_ratio_max=args.gate_threshold_jump_max,
                high_share_jump_max=args.gate_high_share_jump_max,
                cross_max_insufficient_ratio=args.gate_cross_max_insufficient_ratio,
                require_three_channel_gate=args.gate_require_three_channel,
                three_channel_min_presence=args.gate_three_channel_min_presence,
                three_channel_min_std=args.gate_three_channel_min_std,
                three_channel_min_unique=args.gate_three_channel_min_unique,
                cached_gates=cached_gates,
                on_partial_update=_update_gate_partial if args.resume else None,
                show_progress=PROGRESS_ENABLED,
            )
            print(f"  overall_passed: {gate_report.get('overall_passed')}")
            for gate_name, gate_row in gate_report.get("gates", {}).items():
                print(
                    "  - {name}: required={required}, passed={passed}, status={status}".format(
                        name=gate_name,
                        required=gate_row.get("required"),
                        passed=gate_row.get("passed"),
                        status=gate_row.get("status"),
                    )
                )
            print(f"  Report written: {gate_report_path}")
            if args.resume:
                resume_state["gate_partial"] = {}
                _save_resume_state(resume_path, resume_state)
            return {
                "report_path": gate_report_path,
                "overall_passed": bool(gate_report.get("overall_passed")),
            }

        run_stage("07_gate_report", "Feasibility Gate Report", _stage_gate_report)

    run_stage(
        "08_channel_traceability",
        "Channel Traceability Check",
        lambda: (
            validate_channel_traceability(years, prefix, show_progress=PROGRESS_ENABLED),
            {"years": len(years)},
        )[1],
    )

    print("\n" + "=" * 60 + "\nDone\n")


if __name__ == "__main__":
    main()

