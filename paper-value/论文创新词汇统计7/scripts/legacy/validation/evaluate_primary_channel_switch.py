# -*- coding: utf-8 -*-
"""
Evaluate Impact V6 primary-channel switch readiness.

This tool does not change any production score field. It only evaluates
candidate primary-channel strategies on existing impact_v6_final outputs.
"""

import argparse
import json
import math
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

try:
    from tqdm import tqdm
except Exception:  # pragma: no cover
    tqdm = None


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import load_project_config, get_paths, get_runtime, get_years


DEFAULT_PAIR_SPECS = (
    {
        "name": "main_vs_erratum_2020",
        "higher_paper_id": "21da5794b4f537271edb091a376f6860",
        "lower_paper_id": "4dae6853d4d99ecf314666735a8f01ec",
    },
)

CHANNEL_FALLBACK_FIELDS = {
    "diffusion_impact": ("diffusion_impact", "impact_score"),
    "foundation_utility": ("foundation_utility_norm",),
    "method_transferability": ("method_transferability_norm",),
}

RESUME_SCHEMA_VERSION = "impact_v6_primary_switch_resume_v1"


def _parse_finite_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        score = float(value)
    except Exception:
        return None
    if not math.isfinite(score):
        return None
    return score


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


def _parse_pair_text(text: str) -> Optional[dict]:
    raw = str(text or "").strip()
    if not raw or ">" not in raw:
        return None
    left, right = raw.split(">", 1)
    higher = left.strip()
    if "|" in right:
        lower, name = right.split("|", 1)
        lower = lower.strip()
        name = name.strip()
    else:
        lower = right.strip()
        name = ""
    if not higher or not lower:
        return None
    return {
        "name": name or f"{higher[:8]}>{lower[:8]}",
        "higher_paper_id": higher,
        "lower_paper_id": lower,
    }


def _load_pairs_from_file(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, dict):
        payload = payload.get("pairs", [])
    if not isinstance(payload, list):
        return []
    out = []
    for item in payload:
        normalized = _normalize_pair_spec(item)
        if normalized is not None:
            out.append(normalized)
    return out


def _resolve_pair_specs(pair_texts: Sequence[str], pairs_file: Optional[str]) -> List[dict]:
    out: List[dict] = []
    seen = set()

    if pairs_file:
        for row in _load_pairs_from_file(pairs_file):
            key = (row["higher_paper_id"], row["lower_paper_id"])
            if key in seen:
                continue
            seen.add(key)
            out.append(row)

    for text in pair_texts or []:
        parsed = _parse_pair_text(text)
        if parsed is None:
            continue
        key = (parsed["higher_paper_id"], parsed["lower_paper_id"])
        if key in seen:
            continue
        seen.add(key)
        out.append(parsed)

    if not out:
        for row in DEFAULT_PAIR_SPECS:
            normalized = _normalize_pair_spec(row)
            if normalized is None:
                continue
            out.append(normalized)
    return out


def _parse_blend_weights(raw: str) -> Tuple[float, float, float]:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("blend weights is empty")
    parts = [x.strip() for x in text.split(",")]
    if len(parts) != 3:
        raise ValueError("blend weights must contain 3 comma-separated values")
    values = [float(x) for x in parts]
    if any(v < 0 for v in values):
        raise ValueError("blend weights cannot be negative")
    total = sum(values)
    if total <= 0:
        raise ValueError("blend weights sum must be > 0")
    return values[0], values[1], values[2]


class HistogramStats:
    __slots__ = ("count", "sum_value", "sum_sq", "min_value", "max_value", "bins")

    def __init__(self):
        self.count = 0
        self.sum_value = 0.0
        self.sum_sq = 0.0
        self.min_value = float("inf")
        self.max_value = float("-inf")
        self.bins = Counter()

    def add(self, value: float):
        x = float(value)
        self.count += 1
        self.sum_value += x
        self.sum_sq += x * x
        if x < self.min_value:
            self.min_value = x
        if x > self.max_value:
            self.max_value = x
        key = int(round(x * 100.0))
        self.bins[key] += 1

    def mean(self) -> float:
        if self.count <= 0:
            return 0.0
        return self.sum_value / self.count

    def std(self) -> float:
        if self.count <= 0:
            return 0.0
        mean = self.mean()
        var = max(self.sum_sq / self.count - mean * mean, 0.0)
        return math.sqrt(var)

    def unique_bins(self) -> int:
        return int(len(self.bins))

    def top_bin_share(self) -> Optional[float]:
        if self.count <= 0:
            return None
        max_count = max(self.bins.values()) if self.bins else 0
        return float(max_count / self.count) if self.count > 0 else None

    def percentile(self, pct: float) -> float:
        if self.count <= 0:
            return 0.0
        target = max(0.0, min(float(pct), 100.0))
        rank = int(math.ceil((target / 100.0) * self.count))
        rank = max(rank, 1)
        acc = 0
        for key in sorted(self.bins.keys()):
            acc += int(self.bins[key])
            if acc >= rank:
                return key / 100.0
        return self.max_value if math.isfinite(self.max_value) else 0.0

    def summary(self) -> dict:
        if self.count <= 0:
            return {
                "count": 0,
                "mean": 0.0,
                "std": 0.0,
                "p50": 0.0,
                "p90": 0.0,
                "min": 0.0,
                "max": 0.0,
                "unique_bins_2dp": 0,
                "top_bin_share_2dp": None,
            }
        return {
            "count": int(self.count),
            "mean": float(self.mean()),
            "std": float(self.std()),
            "p50": float(self.percentile(50)),
            "p90": float(self.percentile(90)),
            "min": float(self.min_value),
            "max": float(self.max_value),
            "unique_bins_2dp": int(self.unique_bins()),
            "top_bin_share_2dp": self.top_bin_share(),
        }

    def to_state(self) -> dict:
        if self.count <= 0:
            min_value = None
            max_value = None
        else:
            min_value = float(self.min_value)
            max_value = float(self.max_value)
        return {
            "count": int(self.count),
            "sum_value": float(self.sum_value),
            "sum_sq": float(self.sum_sq),
            "min_value": min_value,
            "max_value": max_value,
            "bins": {str(int(k)): int(v) for k, v in self.bins.items()},
        }

    @classmethod
    def from_state(cls, payload: Optional[dict]) -> "HistogramStats":
        obj = cls()
        if not isinstance(payload, dict):
            return obj
        obj.count = int(payload.get("count", 0) or 0)
        obj.sum_value = float(payload.get("sum_value", 0.0) or 0.0)
        obj.sum_sq = float(payload.get("sum_sq", 0.0) or 0.0)
        if obj.count > 0:
            obj.min_value = float(payload.get("min_value", 0.0) or 0.0)
            obj.max_value = float(payload.get("max_value", 0.0) or 0.0)
        bins = payload.get("bins") or {}
        if isinstance(bins, dict):
            for key, value in bins.items():
                try:
                    k = int(key)
                    v = int(value)
                except Exception:
                    continue
                if v > 0:
                    obj.bins[k] = v
        return obj


class PearsonAccumulator:
    __slots__ = ("n", "sx", "sy", "sxx", "syy", "sxy")

    def __init__(self):
        self.n = 0
        self.sx = 0.0
        self.sy = 0.0
        self.sxx = 0.0
        self.syy = 0.0
        self.sxy = 0.0

    def add(self, x: float, y: float):
        fx = float(x)
        fy = float(y)
        self.n += 1
        self.sx += fx
        self.sy += fy
        self.sxx += fx * fx
        self.syy += fy * fy
        self.sxy += fx * fy

    def corr(self) -> Optional[float]:
        if self.n <= 1:
            return None
        n = float(self.n)
        num = n * self.sxy - self.sx * self.sy
        den_x = n * self.sxx - self.sx * self.sx
        den_y = n * self.syy - self.sy * self.sy
        if den_x <= 0 or den_y <= 0:
            return None
        den = math.sqrt(den_x * den_y)
        if den <= 0:
            return None
        return float(num / den)

    def to_state(self) -> dict:
        return {
            "n": int(self.n),
            "sx": float(self.sx),
            "sy": float(self.sy),
            "sxx": float(self.sxx),
            "syy": float(self.syy),
            "sxy": float(self.sxy),
        }

    @classmethod
    def from_state(cls, payload: Optional[dict]) -> "PearsonAccumulator":
        obj = cls()
        if not isinstance(payload, dict):
            return obj
        obj.n = int(payload.get("n", 0) or 0)
        obj.sx = float(payload.get("sx", 0.0) or 0.0)
        obj.sy = float(payload.get("sy", 0.0) or 0.0)
        obj.sxx = float(payload.get("sxx", 0.0) or 0.0)
        obj.syy = float(payload.get("syy", 0.0) or 0.0)
        obj.sxy = float(payload.get("sxy", 0.0) or 0.0)
        return obj


def _extract_channel_score(rec: dict, channel_name: str) -> Optional[float]:
    channels = rec.get("impact_channels")
    if isinstance(channels, dict):
        score = _parse_finite_float(channels.get(channel_name))
        if score is not None:
            return score
    for field in CHANNEL_FALLBACK_FIELDS.get(channel_name, ()):
        score = _parse_finite_float(rec.get(field))
        if score is not None:
            return score
    return None


def _extract_candidate_score(
    rec: dict,
    candidate: str,
    blend_weights: Tuple[float, float, float],
    blend_mode: str,
) -> Optional[float]:
    if candidate in ("diffusion_impact", "foundation_utility", "method_transferability"):
        return _extract_channel_score(rec, candidate)

    if candidate != "blend_v1":
        return None

    diffusion = _extract_channel_score(rec, "diffusion_impact")
    foundation = _extract_channel_score(rec, "foundation_utility")
    method = _extract_channel_score(rec, "method_transferability")
    weights = {
        "diffusion_impact": float(blend_weights[0]),
        "foundation_utility": float(blend_weights[1]),
        "method_transferability": float(blend_weights[2]),
    }
    values = {
        "diffusion_impact": diffusion,
        "foundation_utility": foundation,
        "method_transferability": method,
    }

    if blend_mode == "strict":
        if any(values[k] is None for k in values.keys()):
            return None
        total = sum(weights.values())
        if total <= 0:
            return None
        score = (
            values["diffusion_impact"] * weights["diffusion_impact"]
            + values["foundation_utility"] * weights["foundation_utility"]
            + values["method_transferability"] * weights["method_transferability"]
        ) / total
        return float(score)

    weighted_sum = 0.0
    available_weight = 0.0
    for name, val in values.items():
        if val is None:
            continue
        w = weights[name]
        if w <= 0:
            continue
        weighted_sum += val * w
        available_weight += w
    if available_weight <= 0:
        return None
    return float(weighted_sum / available_weight)


def _build_output_path(
    output_dir: str,
    candidate: str,
    years: List[int],
    explicit_output: Optional[str],
) -> str:
    if explicit_output:
        return explicit_output
    sorted_years = sorted(int(y) for y in years) if years else [0]
    return os.path.join(
        output_dir,
        f"impact_v6_primary_switch_eval_{candidate}_{sorted_years[0]}_{sorted_years[-1]}.json",
    )


def _default_resume_path(output_dir: str, prefix: str, candidate: str, years: List[int]) -> str:
    sorted_years = sorted(int(y) for y in years) if years else [0]
    safe_prefix = str(prefix).replace("/", "_").replace("\\", "_")
    safe_candidate = str(candidate).replace("/", "_").replace("\\", "_")
    return os.path.join(
        output_dir,
        (
            f"impact_v6_primary_switch_resume_{safe_candidate}_{safe_prefix}_"
            f"{sorted_years[0]}_{sorted_years[-1]}.json"
        ),
    )


def _build_resume_context(
    args: argparse.Namespace,
    prefix: str,
    years: List[int],
    pair_specs: List[dict],
    blend_weights: Tuple[float, float, float],
) -> dict:
    return {
        "prefix": str(prefix),
        "years": [int(y) for y in sorted(years)],
        "baseline": str(args.baseline),
        "candidate": str(args.candidate),
        "blend_mode": str(args.blend_mode),
        "blend_weights": [float(blend_weights[0]), float(blend_weights[1]), float(blend_weights[2])],
        "pairs": [
            {
                "name": str(p.get("name", "")),
                "higher_paper_id": str(p.get("higher_paper_id", "")),
                "lower_paper_id": str(p.get("lower_paper_id", "")),
            }
            for p in pair_specs
        ],
        "pair_min_gap": float(args.pair_min_gap),
        "coverage_min": float(args.coverage_min),
        "std_min": float(args.std_min),
        "unique_min": int(args.unique_min),
        "zero_top_share_max": float(args.zero_top_share_max),
        "max_records_per_year": int(args.max_records_per_year),
    }


def _save_resume_state(path: str, payload: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _load_resume_state(path: str, context: dict, enabled: bool) -> dict:
    base = {
        "schema_version": RESUME_SCHEMA_VERSION,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "context": context,
        "completed_years": [],
        "current_year": None,
        "current_year_offset": 0,
        "current_year_valid_count": 0,
        "runtime": {},
    }
    if not enabled:
        return base
    if not os.path.exists(path):
        return base
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"[RESUME] Resume file unreadable; restart from scratch: {path} ({exc})")
        return base

    if payload.get("schema_version") != RESUME_SCHEMA_VERSION:
        print("[RESUME] Resume schema changed; restart from scratch.")
        return base
    if payload.get("context") != context:
        print("[RESUME] Resume context changed; restart from scratch.")
        return base

    payload.setdefault("completed_years", [])
    payload.setdefault("current_year", None)
    payload.setdefault("current_year_offset", 0)
    payload.setdefault("current_year_valid_count", 0)
    payload.setdefault("runtime", {})
    payload["updated_at"] = datetime.now().isoformat()
    return payload


def _serialize_runtime_state(
    *,
    total_records: int,
    baseline_count: int,
    candidate_count: int,
    common_count: int,
    zero_adoption_count: int,
    baseline_zero_count: int,
    candidate_zero_count: int,
    baseline_stats: HistogramStats,
    candidate_stats: HistogramStats,
    delta_stats: HistogramStats,
    baseline_zero_stats: HistogramStats,
    candidate_zero_stats: HistogramStats,
    corr_acc: PearsonAccumulator,
    pair_lookup: Dict[str, dict],
) -> dict:
    return {
        "total_records": int(total_records),
        "baseline_count": int(baseline_count),
        "candidate_count": int(candidate_count),
        "common_count": int(common_count),
        "zero_adoption_count": int(zero_adoption_count),
        "baseline_zero_count": int(baseline_zero_count),
        "candidate_zero_count": int(candidate_zero_count),
        "baseline_stats": baseline_stats.to_state(),
        "candidate_stats": candidate_stats.to_state(),
        "delta_stats": delta_stats.to_state(),
        "baseline_zero_stats": baseline_zero_stats.to_state(),
        "candidate_zero_stats": candidate_zero_stats.to_state(),
        "corr_acc": corr_acc.to_state(),
        "pair_lookup": pair_lookup,
    }


def _restore_runtime_state(runtime: dict):
    runtime = runtime if isinstance(runtime, dict) else {}
    total_records = int(runtime.get("total_records", 0) or 0)
    baseline_count = int(runtime.get("baseline_count", 0) or 0)
    candidate_count = int(runtime.get("candidate_count", 0) or 0)
    common_count = int(runtime.get("common_count", 0) or 0)
    zero_adoption_count = int(runtime.get("zero_adoption_count", 0) or 0)
    baseline_zero_count = int(runtime.get("baseline_zero_count", 0) or 0)
    candidate_zero_count = int(runtime.get("candidate_zero_count", 0) or 0)

    baseline_stats = HistogramStats.from_state(runtime.get("baseline_stats"))
    candidate_stats = HistogramStats.from_state(runtime.get("candidate_stats"))
    delta_stats = HistogramStats.from_state(runtime.get("delta_stats"))
    baseline_zero_stats = HistogramStats.from_state(runtime.get("baseline_zero_stats"))
    candidate_zero_stats = HistogramStats.from_state(runtime.get("candidate_zero_stats"))
    corr_acc = PearsonAccumulator.from_state(runtime.get("corr_acc"))

    pair_lookup: Dict[str, dict] = {}
    raw_pairs = runtime.get("pair_lookup")
    if isinstance(raw_pairs, dict):
        for key, value in raw_pairs.items():
            if isinstance(value, dict):
                pair_lookup[str(key)] = value

    return (
        total_records,
        baseline_count,
        candidate_count,
        common_count,
        zero_adoption_count,
        baseline_zero_count,
        candidate_zero_count,
        baseline_stats,
        candidate_stats,
        delta_stats,
        baseline_zero_stats,
        candidate_zero_stats,
        corr_acc,
        pair_lookup,
    )


def _iter_year_records(
    impact_dir: str,
    prefix: str,
    year: int,
    show_progress: bool,
    max_records_per_year: int,
    start_offset: int = 0,
    start_valid_count: int = 0,
) -> Iterator[Tuple[dict, int, int]]:
    path = os.path.join(impact_dir, f"{prefix}_{year}.jsonl")
    if not os.path.exists(path):
        return

    if max_records_per_year > 0 and int(start_valid_count) >= int(max_records_per_year):
        return

    safe_start_offset = max(int(start_offset), 0)
    safe_start_valid_count = max(int(start_valid_count), 0)

    pbar = None
    row_count = 0
    valid_count = safe_start_valid_count
    started_at = time.time()
    next_heartbeat = started_at + 20.0
    total_bytes = None
    try:
        total_bytes = os.path.getsize(path)
    except OSError:
        total_bytes = None
    if total_bytes is not None and safe_start_offset >= total_bytes:
        return

    if show_progress and tqdm is not None:
        pbar = tqdm(
            total=total_bytes,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc=f"switch_eval {year}",
            leave=False,
        )

    try:
        with open(path, "rb") as f:
            if safe_start_offset > 0:
                f.seek(safe_start_offset, os.SEEK_SET)
                if pbar is not None and total_bytes is not None:
                    pbar.n = min(safe_start_offset, total_bytes)
                    pbar.refresh()
            for raw in f:
                current_offset = int(f.tell())
                row_count += 1
                if pbar is not None:
                    pbar.update(len(raw))
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                valid_count += 1
                if show_progress and time.time() >= next_heartbeat:
                    elapsed = max(time.time() - started_at, 1e-9)
                    rate = valid_count / elapsed
                    print(
                        f"[PROGRESS] year={year}, rows={row_count:,}, valid={valid_count:,}, "
                        f"rate={rate:,.0f}/s, elapsed={elapsed:.1f}s"
                    )
                    next_heartbeat = time.time() + 20.0
                yield rec, current_offset, valid_count
                if max_records_per_year > 0 and valid_count >= max_records_per_year:
                    break
    finally:
        if pbar is not None:
            pbar.close()


def evaluate_primary_switch(args: argparse.Namespace) -> dict:
    cfg = load_project_config(args.config)
    paths = get_paths(cfg)
    runtime = get_runtime(cfg)
    impact_dir = paths["impact_output_dir"]
    output_dir = paths["impact_output_dir"]
    default_years = list(get_years(runtime))
    prefix = args.prefix or str(runtime.get("impact_v6_final_prefix", "impact_v6_final"))
    years = [args.year] if args.year is not None else default_years
    years = sorted(int(y) for y in years)

    pairs = _resolve_pair_specs(args.pair, args.pairs_file)
    pair_lookup: Dict[str, dict] = {}
    pair_ids = set()
    for pair in pairs:
        pair_ids.add(pair["higher_paper_id"])
        pair_ids.add(pair["lower_paper_id"])

    blend_weights = _parse_blend_weights(args.blend_weights)
    baseline_name = str(args.baseline)
    candidate_name = str(args.candidate)
    blend_mode = str(args.blend_mode)
    resume_enabled = bool(args.resume)
    resume_path = args.resume_path or _default_resume_path(output_dir, prefix, candidate_name, years)
    resume_file_exists = os.path.exists(resume_path)
    resume_context = _build_resume_context(args, prefix, years, pairs, blend_weights)
    resume_state = _load_resume_state(resume_path, resume_context, enabled=resume_enabled)

    (
        total_records,
        baseline_count,
        candidate_count,
        common_count,
        zero_adoption_count,
        baseline_zero_count,
        candidate_zero_count,
        baseline_stats,
        candidate_stats,
        delta_stats,
        baseline_zero_stats,
        candidate_zero_stats,
        corr_acc,
        pair_lookup,
    ) = _restore_runtime_state(resume_state.get("runtime"))
    pair_lookup = {k: v for k, v in pair_lookup.items() if k in pair_ids}
    completed_years = set(int(y) for y in (resume_state.get("completed_years") or []))

    def persist_resume(current_year: Optional[int], current_offset: int, current_valid_count: int):
        if not resume_enabled:
            return
        resume_state["updated_at"] = datetime.now().isoformat()
        resume_state["context"] = resume_context
        resume_state["completed_years"] = sorted(int(y) for y in completed_years)
        resume_state["current_year"] = int(current_year) if current_year is not None else None
        resume_state["current_year_offset"] = int(max(current_offset, 0))
        resume_state["current_year_valid_count"] = int(max(current_valid_count, 0))
        resume_state["runtime"] = _serialize_runtime_state(
            total_records=total_records,
            baseline_count=baseline_count,
            candidate_count=candidate_count,
            common_count=common_count,
            zero_adoption_count=zero_adoption_count,
            baseline_zero_count=baseline_zero_count,
            candidate_zero_count=candidate_zero_count,
            baseline_stats=baseline_stats,
            candidate_stats=candidate_stats,
            delta_stats=delta_stats,
            baseline_zero_stats=baseline_zero_stats,
            candidate_zero_stats=candidate_zero_stats,
            corr_acc=corr_acc,
            pair_lookup=pair_lookup,
        )
        _save_resume_state(resume_path, resume_state)

    if resume_enabled:
        if resume_file_exists:
            print(f"[RESUME] Loaded checkpoint: {resume_path}")
        else:
            persist_resume(current_year=None, current_offset=0, current_valid_count=0)
            print(f"[RESUME] Created checkpoint: {resume_path}")

    for year in years:
        if year in completed_years:
            if resume_enabled:
                print(f"[RESUME] Skip completed year: {year}")
            continue

        year_path = os.path.join(impact_dir, f"{prefix}_{year}.jsonl")
        if not os.path.exists(year_path):
            print(f"[WARN] Missing year file, skip year: {year_path}")
            completed_years.add(year)
            persist_resume(current_year=None, current_offset=0, current_valid_count=0)
            continue

        start_offset = 0
        start_valid_count = 0
        if (
            resume_enabled
            and resume_state.get("current_year") is not None
            and int(resume_state.get("current_year")) == int(year)
        ):
            start_offset = int(resume_state.get("current_year_offset", 0) or 0)
            start_valid_count = int(resume_state.get("current_year_valid_count", 0) or 0)
            if start_offset > 0 or start_valid_count > 0:
                print(
                    f"[RESUME] Continue year {year} from offset={start_offset:,}, "
                    f"valid_count={start_valid_count:,}"
                )

        if int(args.max_records_per_year) > 0 and start_valid_count >= int(args.max_records_per_year):
            completed_years.add(year)
            persist_resume(current_year=None, current_offset=0, current_valid_count=0)
            continue

        last_flush_time = time.time()
        for rec, current_offset, current_valid_count in _iter_year_records(
            impact_dir=impact_dir,
            prefix=prefix,
            year=year,
            show_progress=bool(args.show_progress),
            max_records_per_year=int(args.max_records_per_year),
            start_offset=start_offset,
            start_valid_count=start_valid_count,
        ):
            total_records += 1
            paper_id = str(rec.get("paper_id", "")).strip()

            baseline_score = _extract_candidate_score(
                rec,
                candidate=baseline_name,
                blend_weights=blend_weights,
                blend_mode=blend_mode,
            )
            candidate_score = _extract_candidate_score(
                rec,
                candidate=candidate_name,
                blend_weights=blend_weights,
                blend_mode=blend_mode,
            )

            if baseline_score is not None:
                baseline_count += 1
                baseline_stats.add(baseline_score)
            if candidate_score is not None:
                candidate_count += 1
                candidate_stats.add(candidate_score)
            if baseline_score is not None and candidate_score is not None:
                common_count += 1
                corr_acc.add(baseline_score, candidate_score)
                delta_stats.add(candidate_score - baseline_score)

            adoption_raw = _parse_finite_float(rec.get("adoption_raw"))
            if adoption_raw is not None and adoption_raw <= 0.0:
                zero_adoption_count += 1
                if baseline_score is not None:
                    baseline_zero_count += 1
                    baseline_zero_stats.add(baseline_score)
                if candidate_score is not None:
                    candidate_zero_count += 1
                    candidate_zero_stats.add(candidate_score)

            if paper_id and paper_id in pair_ids and paper_id not in pair_lookup:
                pair_lookup[paper_id] = {
                    "paper_id": paper_id,
                    "year": int(year),
                    "baseline_score": baseline_score,
                    "candidate_score": candidate_score,
                }

            if (
                resume_enabled
                and float(args.resume_flush_seconds) > 0
                and (time.time() - last_flush_time) >= float(args.resume_flush_seconds)
            ):
                persist_resume(
                    current_year=year,
                    current_offset=current_offset,
                    current_valid_count=current_valid_count,
                )
                last_flush_time = time.time()

        completed_years.add(year)
        persist_resume(current_year=None, current_offset=0, current_valid_count=0)
        print(f"[YEAR] Completed: {year}")

    pair_results = []
    pair_valid_count = 0
    pair_pass_count = 0
    for pair in pairs:
        higher = pair_lookup.get(pair["higher_paper_id"])
        lower = pair_lookup.get(pair["lower_paper_id"])
        row = {
            "name": pair["name"],
            "higher_paper_id": pair["higher_paper_id"],
            "lower_paper_id": pair["lower_paper_id"],
        }
        if higher is None or lower is None:
            row["status"] = "insufficient_data"
            row["reason"] = "missing_pair_record"
            pair_results.append(row)
            continue

        h_base = _parse_finite_float(higher.get("baseline_score"))
        l_base = _parse_finite_float(lower.get("baseline_score"))
        h_cand = _parse_finite_float(higher.get("candidate_score"))
        l_cand = _parse_finite_float(lower.get("candidate_score"))

        row["baseline_gap"] = None if h_base is None or l_base is None else float(h_base - l_base)
        row["candidate_gap"] = None if h_cand is None or l_cand is None else float(h_cand - l_cand)

        if row["candidate_gap"] is None:
            row["status"] = "insufficient_data"
            row["reason"] = "candidate_gap_missing"
            pair_results.append(row)
            continue

        pair_valid_count += 1
        passed = row["candidate_gap"] >= float(args.pair_min_gap)
        if passed:
            pair_pass_count += 1
        row["status"] = "ok" if passed else "alert"
        row["min_gap"] = float(args.pair_min_gap)
        pair_results.append(row)

    candidate_coverage_ratio = float(candidate_count / total_records) if total_records > 0 else 0.0
    common_ratio = float(common_count / total_records) if total_records > 0 else 0.0
    pairwise_ok = pair_valid_count > 0 and pair_pass_count == pair_valid_count
    baseline_zero_top_share = baseline_zero_stats.top_bin_share()
    candidate_zero_top_share = candidate_zero_stats.top_bin_share()

    coverage_ok = candidate_coverage_ratio >= float(args.coverage_min)
    dispersion_ok = (
        candidate_stats.std() >= float(args.std_min)
        and candidate_stats.unique_bins() >= int(args.unique_min)
    )
    zero_pileup_ok = (
        True
        if candidate_zero_top_share is None
        else candidate_zero_top_share <= float(args.zero_top_share_max)
    )
    ready = coverage_ok and dispersion_ok and zero_pileup_ok and pairwise_ok

    result = {
        "generated_at": datetime.now().isoformat(),
        "input": {
            "impact_dir": impact_dir,
            "prefix": prefix,
            "years": years,
            "max_records_per_year": int(args.max_records_per_year),
        },
        "resume": {
            "enabled": bool(resume_enabled),
            "path": resume_path if resume_enabled else None,
            "preexisting_checkpoint": bool(resume_enabled and resume_file_exists),
            "completed_years": sorted(int(y) for y in completed_years),
        },
        "candidate": {
            "baseline": baseline_name,
            "name": candidate_name,
            "blend_mode": blend_mode,
            "blend_weights": {
                "diffusion_impact": float(blend_weights[0]),
                "foundation_utility": float(blend_weights[1]),
                "method_transferability": float(blend_weights[2]),
            },
        },
        "counts": {
            "total_records": int(total_records),
            "baseline_count": int(baseline_count),
            "candidate_count": int(candidate_count),
            "common_count": int(common_count),
            "candidate_coverage_ratio": candidate_coverage_ratio,
            "common_ratio": common_ratio,
            "zero_adoption_count": int(zero_adoption_count),
            "baseline_zero_count": int(baseline_zero_count),
            "candidate_zero_count": int(candidate_zero_count),
        },
        "distribution": {
            "baseline": baseline_stats.summary(),
            "candidate": candidate_stats.summary(),
            "delta_candidate_minus_baseline": delta_stats.summary(),
            "baseline_zero_adoption": baseline_zero_stats.summary(),
            "candidate_zero_adoption": candidate_zero_stats.summary(),
        },
        "relationship": {
            "pearson_corr_common": corr_acc.corr(),
        },
        "pairwise": {
            "pairs": pair_results,
            "valid_count": int(pair_valid_count),
            "pass_count": int(pair_pass_count),
            "pairwise_ok": bool(pairwise_ok),
        },
        "readiness": {
            "coverage_ok": bool(coverage_ok),
            "dispersion_ok": bool(dispersion_ok),
            "zero_pileup_ok": bool(zero_pileup_ok),
            "pairwise_ok": bool(pairwise_ok),
            "coverage_min": float(args.coverage_min),
            "std_min": float(args.std_min),
            "unique_min": int(args.unique_min),
            "zero_top_share_max": float(args.zero_top_share_max),
            "pair_min_gap": float(args.pair_min_gap),
            "candidate_zero_top_share": candidate_zero_top_share,
            "baseline_zero_top_share": baseline_zero_top_share,
            "ready_to_switch": bool(ready),
        },
    }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Impact V6 primary-channel switch readiness")
    parser.add_argument("--year", type=int, default=None, help="Evaluate a specific year")
    parser.add_argument("--prefix", type=str, default=None, help="Impact file prefix, default from runtime config")
    parser.add_argument(
        "--baseline",
        type=str,
        default="diffusion_impact",
        choices=["diffusion_impact", "foundation_utility", "method_transferability", "blend_v1"],
        help="Baseline channel for comparison",
    )
    parser.add_argument(
        "--candidate",
        type=str,
        default="blend_v1",
        choices=["diffusion_impact", "foundation_utility", "method_transferability", "blend_v1"],
        help="Candidate primary channel strategy",
    )
    parser.add_argument(
        "--blend-weights",
        type=str,
        default="0.60,0.25,0.15",
        help="Weights for blend_v1 (diffusion,foundation,method)",
    )
    parser.add_argument(
        "--blend-mode",
        type=str,
        default="strict",
        choices=["strict", "normalized"],
        help="strict: require all 3 channels; normalized: use available channels only",
    )
    parser.add_argument("--pair", action="append", default=[], help="Pair rule: higher_id>lower_id|name")
    parser.add_argument("--pairs-file", type=str, default=None, help="Pair JSON file path")
    parser.add_argument("--pair-min-gap", type=float, default=0.01, help="Pair minimal positive gap threshold")
    parser.add_argument("--coverage-min", type=float, default=0.98, help="Coverage gate threshold")
    parser.add_argument("--std-min", type=float, default=0.01, help="Dispersion gate: minimum std")
    parser.add_argument("--unique-min", type=int, default=5, help="Dispersion gate: minimum unique 2dp bins")
    parser.add_argument(
        "--zero-top-share-max",
        type=float,
        default=0.95,
        help="Zero-adoption pile-up gate: max top-bin share",
    )
    parser.add_argument("--output", type=str, default=None, help="Output report path (JSON)")
    parser.add_argument("--config", type=str, default=None, help="Config path")
    parser.add_argument(
        "--max-records-per-year",
        type=int,
        default=0,
        help="For smoke runs: max valid records to scan per year (0=full)",
    )
    parser.add_argument(
        "--resume",
        dest="resume",
        action="store_true",
        help="Resume from checkpoint (default: enabled)",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Disable checkpoint resume and rerun from scratch",
    )
    parser.add_argument("--resume-path", type=str, default=None, help="Checkpoint file path")
    parser.add_argument(
        "--resume-flush-seconds",
        type=float,
        default=20.0,
        help="Checkpoint flush interval in seconds",
    )
    parser.add_argument("--progress", dest="show_progress", action="store_true", help="Enable progress bars")
    parser.add_argument("--no-progress", dest="show_progress", action="store_false", help="Disable progress bars")
    parser.set_defaults(show_progress=True, resume=True)
    return parser.parse_args()


def main():
    args = parse_args()
    result = evaluate_primary_switch(args)

    cfg = load_project_config(args.config)
    output_dir = get_paths(cfg)["impact_output_dir"]
    out_path = _build_output_path(output_dir, args.candidate, result["input"]["years"], args.output)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("=" * 60)
    print("Impact V6 Primary-Channel Switch Evaluation")
    print("=" * 60)
    print(f"years: {result['input']['years']}")
    print(f"baseline: {result['candidate']['baseline']}")
    print(f"candidate: {result['candidate']['name']}")
    if result.get("resume", {}).get("enabled"):
        print(f"resume: ON ({result['resume'].get('path')})")
    else:
        print("resume: OFF")
    print(f"ready_to_switch: {result['readiness']['ready_to_switch']}")
    print(f"candidate_coverage_ratio: {result['counts']['candidate_coverage_ratio']:.4f}")
    corr = result["relationship"]["pearson_corr_common"]
    if corr is None:
        print("pearson_corr_common: null")
    else:
        print(f"pearson_corr_common: {corr:.6f}")
    print(
        "pairwise_ok: {pairwise_ok} ({pass_count}/{valid_count})".format(
            pairwise_ok=result["pairwise"]["pairwise_ok"],
            pass_count=result["pairwise"]["pass_count"],
            valid_count=result["pairwise"]["valid_count"],
        )
    )
    print(f"report: {out_path}")


if __name__ == "__main__":
    main()
