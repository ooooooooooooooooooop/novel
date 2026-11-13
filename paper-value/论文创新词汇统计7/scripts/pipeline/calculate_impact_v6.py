# -*- coding: utf-8 -*-
"""
Impact V6.1 calculation script.

Core design (aligned with IMPACT_V6_DESIGN.md):
- Adoption Magnitude = Top-K(verb_weight * novelty_drop)
- novelty_drop = max(0, log2(freq_current / freq_pub))
- Consistency = persistence of top-K concepts over time
  (yearly frequency stays above the publication-year baseline)
- Impact = adoption_norm * consistency_gate
- V6.1 semantic clarification: the primary score is diffusion_impact;
  impact_score is retained as a backward-compatible alias.
"""

import argparse
import json
import logging
import math
import re
import sqlite3
import sys
import time
from bisect import bisect_right
from collections import OrderedDict, defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
try:
    from tqdm import tqdm
except Exception:  # pragma: no cover
    tqdm = None

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import get_paths, get_runtime, get_years, load_project_config
from scripts.pipeline.calculate_innovation import PaperTypePostProcessor

_cfg = load_project_config()
_paths = get_paths(_cfg)
_runtime = get_runtime(_cfg)

_default_logs_dir = Path(_paths.get("logs_dir", str(PROJECT_ROOT / "artifacts" / "runtime" / "logs")))
_default_logs_dir.mkdir(parents=True, exist_ok=True)
_impact_v6_log_path = _paths.get("impact_v6_log_path", str(_default_logs_dir / "impact_v6_calculation.log"))
DEFAULT_VERB_WEIGHTS_PATH = _paths.get(
    "verb_innovation_weights_path",
    str(PROJECT_ROOT / "verb_innovation_weights.json"),
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(_impact_v6_log_path, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

STATS_SCHEMA_VERSION = "impact_v6_0_novelty_drop_v1"
IMPACT_OUTPUT_SCHEMA_VERSION = "impact_v6_3_multi_channel_v1"
IMPACT_PRIMARY_CHANNEL = "diffusion_impact"

CORRECTION_TITLE_KEYWORDS = (
    "correction",
    "erratum",
    "corrigendum",
    "amendment",
    "retraction",
    "withdrawn",
    "addendum",
    "expression of concern",
)

OBJECT_ALIAS_PATTERNS = (
    (r"\bsci\s*py\b", "scipy"),
    (r"\bnum\s*py\b", "numpy"),
    (r"\bmat\s*plot\s*lib\b", "matplotlib"),
    (r"\bp\s*y\s*torch\b", "pytorch"),
)

OBJECT_GENERIC_PHRASES = {
    "an amendment to this paper",
    "an amendment to the paper",
    "this paper",
    "this article",
    "the original paper",
    "the original article",
}

OBJECT_STOPWORDS = {
    "a",
    "an",
    "the",
    "of",
    "for",
    "to",
    "in",
    "on",
    "by",
    "with",
    "without",
    "from",
    "at",
    "as",
    "and",
    "or",
    "that",
    "this",
    "these",
    "those",
    "our",
    "their",
    "its",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "we",
    "it",
    "into",
    "through",
    "over",
    "under",
}

OBJECT_GENERIC_TOKENS = {
    "paper",
    "article",
    "study",
    "result",
    "results",
    "method",
    "methods",
    "approach",
    "approaches",
    "analysis",
    "overview",
    "description",
    "review",
    "development",
    "developments",
    "capability",
    "capabilities",
    "practice",
    "practices",
    "introduction",
    "framework",
    "model",
    "models",
    "system",
    "systems",
    "correction",
    "erratum",
    "corrigendum",
    "amendment",
    "publisher",
    "author",
}

OBJECT_PREFIX_PATTERNS = (
    r"^(an?|the)\s+overview\s+of\s+",
    r"^(an?|the)\s+description\s+of\s+",
    r"^(an?|the)\s+development\s+and\s+capabilities\s+of\s+",
    r"^(an?|the)\s+development\s+of\s+",
    r"^(an?|the)\s+capabilities\s+of\s+",
    r"^(an?|the)\s+application\s+of\s+",
    r"^(an?|the)\s+use\s+of\s+",
)

CONCEPT_ANCHOR_TERMS = {
    "scipy",
    "numpy",
    "matplotlib",
    "pytorch",
    "tensorflow",
    "transformer",
    "bert",
    "gpt",
    "alphafold",
    "crispr",
    "chatgpt",
    "xgboost",
    "lightgbm",
}

STRICT_CREATIVE_VERBS = {
    "propose",
    "introduce",
    "define",
    "formulate",
    "derive",
    "invent",
    "originate",
    "devise",
    "discover",
    "uncover",
    "establish",
    "create",
    "pioneer",
}

STRICT_USAGE_VERBS = {
    "use",
    "adopt",
    "apply",
    "utilize",
    "employ",
    "analyze",
    "evaluate",
    "test",
    "assess",
    "benchmark",
    "compare",
    "replicate",
    "reproduce",
    "implement",
    "run",
    "train",
    "fine",
    "infer",
}

IRREGULAR_VERB_FORMS = {
    "run": {"runs", "ran", "running"},
    "build": {"builds", "built", "building"},
    "make": {"makes", "made", "making"},
    "write": {"writes", "wrote", "written", "writing"},
    "read": {"reads", "reading"},
    "lead": {"leads", "led", "leading"},
    "use": {"uses", "used", "using"},
    "apply": {"applies", "applied", "applying"},
    "analyze": {"analyzes", "analyzed", "analyzing"},
}


def _as_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _as_str_list(value, default: Optional[List[str]] = None) -> List[str]:
    if value is None:
        return list(default or [])
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return list(default or [])
        if "," in text:
            return [x.strip() for x in text.split(",") if x.strip()]
        return [text]
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                out.append(text)
        return out or list(default or [])
    return list(default or [])


def build_runtime_config(config_path: str = None) -> dict:
    cfg = load_project_config(config_path)
    paths = get_paths(cfg)
    runtime = get_runtime(cfg)

    output_dir = paths["impact_output_dir"]
    years_list = list(get_years(runtime))
    if not years_list:
        years_list = list(range(2010, 2026))

    return {
        "rpu_db_path": paths["rpu_db_path"],
        "output_dir": output_dir,
        "innovation_output_dir": paths.get(
            "innovation_output_dir",
            str(PROJECT_ROOT / "artifacts" / "runtime" / "innovation_v2_output"),
        ),
        "years": years_list,
        "current_year": int(runtime.get("current_year", max(years_list))),
        "top_k": int(runtime.get("impact_top_k", 3)),
        "consistency_threshold": float(runtime.get("impact_consistency_threshold", 0.5)),
        "min_observable_years": int(runtime.get("impact_min_observable_years", 1)),
        "exclude_correction_papers": _as_bool(runtime.get("exclude_correction_papers", True), True),
        "vocab_size_estimate": int(runtime.get("impact_vocab_size_estimate", 100000)),
        "min_core_coverage": float(runtime.get("impact_min_core_coverage", 0.2)),
        "early_adopter_strength": float(runtime.get("impact_early_adopter_strength", 0.35)),
        "early_adopter_ref_bits": float(runtime.get("impact_early_adopter_ref_bits", 10.0)),
        "common_object_df_ratio_cap": float(runtime.get("impact_common_object_df_ratio_cap", 0.01)),
        "stability_bonus_weight": float(runtime.get("impact_stability_bonus_weight", 0.08)),
        "stability_floor_ratio": float(runtime.get("impact_stability_floor_ratio", 0.85)),
        "stability_bonus_growth_power": float(runtime.get("impact_stability_bonus_growth_power", 0.6)),
        "stability_bonus_max_ratio": float(runtime.get("impact_stability_bonus_max_ratio", 0.5)),
        "consistency_prior_strength": float(runtime.get("impact_consistency_prior_strength", 2.0)),
        "consistency_prior_mean": float(runtime.get("impact_consistency_prior_mean", 0.55)),
        "consistency_prior_observable_scale": float(runtime.get("impact_consistency_prior_observable_scale", 2.0)),
        "consistency_baseline_window": int(runtime.get("impact_consistency_baseline_window", 3)),
        "novelty_freq_source": str(runtime.get("impact_novelty_freq_source", "cumulative")),
        "consistency_freq_source": str(runtime.get("impact_consistency_freq_source", "yearly")),
        "concept_tf_weight": float(runtime.get("impact_concept_tf_weight", 0.15)),
        "use_unified_concept_representation": _as_bool(
            runtime.get("impact_use_unified_concept_representation", True), True
        ),
        "fallback_anchor_shortcut_enabled": _as_bool(runtime.get("impact_fallback_anchor_shortcut_enabled", True), True),
        "fallback_anchor_shortcut_max_tokens": int(runtime.get("impact_fallback_anchor_shortcut_max_tokens", 2)),
        "object_long_concept_max_tokens": int(runtime.get("impact_object_long_concept_max_tokens", 8)),
        "object_long_concept_truncate_mode": str(runtime.get("impact_object_long_concept_truncate_mode", "head_tail")),
        "yearly_freq_smoothing_mode": str(runtime.get("impact_yearly_freq_smoothing_mode", "laplace_adaptive")),
        "yearly_freq_smoothing_alpha": float(runtime.get("impact_yearly_freq_smoothing_alpha", 1.0)),
        "yearly_freq_smoothing_vocab_size": int(
            runtime.get("impact_yearly_freq_smoothing_vocab_size", runtime.get("impact_vocab_size_estimate", 100000))
        ),
        "yearly_freq_smoothing_vocab_scale": float(runtime.get("impact_yearly_freq_smoothing_vocab_scale", 0.12)),
        "cumulative_freq_smoothing_mode": str(runtime.get("impact_cumulative_freq_smoothing_mode", "laplace_adaptive")),
        "cumulative_freq_smoothing_alpha": float(runtime.get("impact_cumulative_freq_smoothing_alpha", 1.0)),
        "cumulative_freq_smoothing_vocab_size": int(
            runtime.get("impact_cumulative_freq_smoothing_vocab_size", runtime.get("impact_vocab_size_estimate", 100000))
        ),
        "cumulative_freq_smoothing_vocab_scale": float(
            runtime.get("impact_cumulative_freq_smoothing_vocab_scale", 0.12)
        ),
        "density_penalty_floor_count": int(runtime.get("impact_density_penalty_floor_count", 2)),
        "density_scope": str(runtime.get("impact_density_scope", "all_positive")),
        "scarcity_sigmoid_alpha": float(runtime.get("impact_scarcity_sigmoid_alpha", 8000.0)),
        "scarcity_sigmoid_threshold": float(runtime.get("impact_scarcity_sigmoid_threshold", 5e-4)),
        "scarcity_min_weight": float(runtime.get("impact_scarcity_min_weight", 1.0)),
        "scarcity_max_weight": float(runtime.get("impact_scarcity_max_weight", 1.3)),
        "stability_requires_growth": _as_bool(runtime.get("impact_stability_requires_growth", True), True),
        "insufficient_window_policy": str(runtime.get("impact_insufficient_window_policy", "diagnostic")),
        "insufficient_window_downweight": float(runtime.get("impact_insufficient_window_downweight", 0.5)),
        "materialize_object_cumulative": _as_bool(runtime.get("impact_materialize_object_cumulative", False), False),
        "use_global_consistency_gate": _as_bool(runtime.get("impact_use_global_consistency_gate", False), False),
        "global_consistency_gate_mode": str(runtime.get("impact_global_consistency_gate_mode", "off")),
        "global_consistency_gate_floor": float(runtime.get("impact_global_consistency_gate_floor", 0.8)),
        "object_verb_weight_mode": str(runtime.get("impact_object_verb_weight_mode", "blended")),
        "object_verb_weight_blend_alpha": float(runtime.get("impact_object_verb_weight_blend_alpha", 0.65)),
        "strict_verb_policy_enabled": _as_bool(runtime.get("impact_strict_verb_policy_enabled", True), True),
        "strict_creative_verb_weight": float(runtime.get("impact_strict_creative_verb_weight", 1.0)),
        "strict_usage_verb_max_weight": float(runtime.get("impact_strict_usage_verb_max_weight", 0.18)),
        "strict_unknown_verb_max_weight": float(runtime.get("impact_strict_unknown_verb_max_weight", 0.6)),
        "strict_creative_verbs": _as_str_list(runtime.get("impact_strict_creative_verbs"), list(STRICT_CREATIVE_VERBS)),
        "strict_usage_verbs": _as_str_list(runtime.get("impact_strict_usage_verbs"), list(STRICT_USAGE_VERBS)),
        "verb_tier1_weight": float(runtime.get("impact_verb_tier1_weight", 1.0)),
        "verb_tier2_weight": float(runtime.get("impact_verb_tier2_weight", 0.6)),
        "verb_tier3_weight": float(runtime.get("impact_verb_tier3_weight", 0.2)),
        "verb_tier4_weight": float(runtime.get("impact_verb_tier4_weight", 0.1)),
        "verb_tier1_verbs": _as_str_list(
            runtime.get("impact_verb_tier1_verbs"),
            ["propose", "present", "introduce", "define", "formulate", "devise"],
        ),
        "verb_tier2_verbs": _as_str_list(
            runtime.get("impact_verb_tier2_verbs"),
            ["improve", "optimize", "enhance", "extend", "modify"],
        ),
        "verb_tier3_verbs": _as_str_list(
            runtime.get("impact_verb_tier3_verbs"),
            ["use", "apply", "employ", "utilize", "adopt", "base_on"],
        ),
        "verb_tier4_verbs": _as_str_list(
            runtime.get("impact_verb_tier4_verbs"),
            ["survey", "review", "compare", "summarize", "analyze"],
        ),
        "cache_max_objects": int(runtime.get("impact_v6_cache_max_objects", 200000)),
        "stats_db_name": runtime.get("impact_v6_stats_db_name", "impact_freq_stats_v6.db"),
        "checkpoint_name": runtime.get("impact_v6_checkpoint_name", "checkpoint_v6.json"),
        "signals_prefix": runtime.get("impact_v6_signals_prefix", "impact_v6_signals"),
        "final_prefix": runtime.get("impact_v6_final_prefix", "impact_v6_final"),
        "summary_name": runtime.get("impact_v6_summary_name", "impact_v6_summary.json"),
        "progress_name": runtime.get("impact_v6_progress_name", "impact_v6_progress.json"),
        "adoption_norm_mode": str(runtime.get("impact_adoption_norm_mode", "global_zscore")),
        "adoption_rank_method": str(runtime.get("impact_adoption_rank_method", "mid")),
        "adoption_global_reference_scope": str(
            runtime.get("impact_adoption_global_reference_scope", "configured_years")
        ),
        "adoption_global_zscore_scale": float(runtime.get("impact_adoption_global_zscore_scale", 1.0)),
        "foundation_utility_enabled": _as_bool(runtime.get("impact_foundation_utility_enabled", True), True),
        "foundation_utility_norm_mode": str(runtime.get("impact_foundation_utility_norm_mode", "yearly_percentile")),
        "foundation_utility_global_reference_scope": str(
            runtime.get(
                "impact_foundation_utility_global_reference_scope",
                runtime.get("impact_adoption_global_reference_scope", "configured_years"),
            )
        ),
        "foundation_utility_global_zscore_scale": float(
            runtime.get("impact_foundation_utility_global_zscore_scale", 1.0)
        ),
        "foundation_utility_object_count_cap": int(runtime.get("impact_foundation_utility_object_count_cap", 8)),
        "foundation_utility_baseline_guard_penalty": float(
            runtime.get("impact_foundation_utility_baseline_guard_penalty", 0.5)
        ),
        "method_transferability_enabled": _as_bool(runtime.get("impact_method_transferability_enabled", True), True),
        "method_transferability_norm_mode": str(
            runtime.get("impact_method_transferability_norm_mode", "yearly_percentile")
        ),
        "method_transferability_global_reference_scope": str(
            runtime.get(
                "impact_method_transferability_global_reference_scope",
                runtime.get("impact_adoption_global_reference_scope", "configured_years"),
            )
        ),
        "method_transferability_global_zscore_scale": float(
            runtime.get("impact_method_transferability_global_zscore_scale", 1.0)
        ),
        "method_transferability_object_count_cap": int(
            runtime.get("impact_method_transferability_object_count_cap", 8)
        ),
        "method_transferability_task_diversity_weight": float(
            runtime.get("impact_method_transferability_task_diversity_weight", 0.5)
        ),
        "method_transferability_object_diversity_weight": float(
            runtime.get("impact_method_transferability_object_diversity_weight", 0.5)
        ),
        "method_transferability_usage_verb_boost": float(
            runtime.get("impact_method_transferability_usage_verb_boost", 0.1)
        ),
        "method_transferability_creative_verb_weight": float(
            runtime.get("impact_method_transferability_creative_verb_weight", 0.85)
        ),
        "concept_year_attribution_enabled": _as_bool(
            runtime.get("impact_concept_year_attribution_enabled", False), False
        ),
        "concept_year_seed_prefix": str(runtime.get("impact_concept_year_seed_prefix", "innovation_v2")),
        "concept_year_seed_field": str(runtime.get("impact_concept_year_seed_field", "s_peak")),
        "concept_year_seed_power": float(runtime.get("impact_concept_year_seed_power", 1.0)),
        "concept_year_weight_floor": float(runtime.get("impact_concept_year_weight_floor", 0.0)),
        "concept_year_leader_relative_threshold": float(
            runtime.get("impact_concept_year_leader_relative_threshold", 0.8)
        ),
        "concept_year_co_leader_relative_threshold": float(
            runtime.get("impact_concept_year_co_leader_relative_threshold", 0.4)
        ),
        "schema_version": STATS_SCHEMA_VERSION,
        "verb_weights_path": paths.get(
            "verb_innovation_weights_path", str(PROJECT_ROOT / "verb_innovation_weights.json")
        ),
        "enable_progress_bar": _as_bool(runtime.get("impact_v6_enable_progress_bar", True), True),
        "progress_refresh_sec": float(runtime.get("impact_v6_progress_refresh_sec", 1.0)),
    }


def build_correction_filter_sql(alias: str = "p") -> str:
    title_expr = f"LOWER(COALESCE({alias}.title, ''))"
    clauses = [f"{title_expr} NOT LIKE '%{kw}%'" for kw in CORRECTION_TITLE_KEYWORDS]
    # Treat "(vol xx, pg yy, yyyy)" style titles as correction/erratum wrappers.
    clauses.append(
        "NOT ("
        f"({title_expr} LIKE '%(vol %' OR {title_expr} LIKE '%(vol.%') "
        f"AND ({title_expr} LIKE '%, pg %' OR {title_expr} LIKE '%, pg.%') "
        f"AND ({title_expr} LIKE '%, 19__%' OR {title_expr} LIKE '%, 20__%')"
        ")"
    )
    return " AND ".join(clauses)


@lru_cache(maxsize=1000000)
def normalize_object_concept(
    obj: str,
    *,
    max_tokens: int = 8,
    truncate_mode: str = "head_tail",
    enable_anchor_shortcut: bool = True,
    anchor_shortcut_max_tokens: int = 2,
) -> str:
    if not obj:
        return ""

    text = obj.lower().strip()
    for pattern, repl in OBJECT_ALIAS_PATTERNS:
        text = re.sub(pattern, repl, text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9_+.\-\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if not text or text in OBJECT_GENERIC_PHRASES:
        return ""

    changed = True
    while changed and text:
        changed = False
        for pattern in OBJECT_PREFIX_PATTERNS:
            reduced = re.sub(pattern, "", text).strip()
            if reduced != text:
                text = reduced
                changed = True

    if not text or text in OBJECT_GENERIC_PHRASES:
        return ""

    tokens = []
    for token in text.split():
        token = token.strip(".-+")
        if not token:
            continue
        if token in OBJECT_STOPWORDS:
            continue
        if token.isdigit():
            continue
        tokens.append(token)

    if not tokens:
        return ""

    if all(token in OBJECT_GENERIC_TOKENS for token in tokens):
        return ""

    tokens = [token for token in tokens if token not in OBJECT_GENERIC_TOKENS]
    if not tokens:
        return ""

    anchor = next((token for token in tokens if token in CONCEPT_ANCHOR_TERMS), None)
    if anchor and enable_anchor_shortcut:
        # Prefer anchor-only fallback only when context is weak.
        non_anchor_tokens = [token for token in tokens if token != anchor]
        if not non_anchor_tokens or len(tokens) <= max(anchor_shortcut_max_tokens, 1):
            return anchor

    max_tokens = max(int(max_tokens), 1)
    mode = str(truncate_mode or "head_tail").strip().lower()
    if len(tokens) > max_tokens:
        if mode == "tail":
            tokens = tokens[-max_tokens:]
        elif mode == "head":
            tokens = tokens[:max_tokens]
        else:
            head = max_tokens // 2
            tail = max_tokens - head
            tokens = tokens[:head] + tokens[-tail:]

    return " ".join(tokens)


def normalize_object_core(text: str) -> str:
    if not text:
        return ""
    value = text.strip()
    if not value or value.startswith("RAW:"):
        return ""
    value = value.lower()
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_task_token(task: str) -> str:
    if not task:
        return ""
    value = task
    if value.startswith("RAW:"):
        value = value[4:]
    value = value.strip().lower()
    if not value:
        return ""
    value = value.split()[0]
    value = re.sub(r"[^a-z0-9+\-_.]", "", value)
    return value


def resolve_task_key(task_core: str, task_lemma: str, task: str) -> str:
    for candidate in (task_core, task_lemma, task):
        token = normalize_task_token(candidate or "")
        if token:
            return token
    return ""


def resolve_object_concept(
    object_core: str,
    object_lemma: str,
    object_raw: str,
    object_coverage: float,
    min_core_coverage: float,
    use_unified_concept_representation: bool = True,
    fallback_anchor_shortcut_enabled: bool = True,
    fallback_anchor_shortcut_max_tokens: int = 2,
    object_long_concept_max_tokens: int = 8,
    object_long_concept_truncate_mode: str = "head_tail",
) -> str:
    core = normalize_object_core(object_core or "")
    if core and (object_coverage <= 0.0 or object_coverage >= min_core_coverage):
        if use_unified_concept_representation:
            unified = normalize_object_concept(
                core,
                max_tokens=object_long_concept_max_tokens,
                truncate_mode=object_long_concept_truncate_mode,
                enable_anchor_shortcut=False,
                anchor_shortcut_max_tokens=fallback_anchor_shortcut_max_tokens,
            )
            if unified:
                return unified
        return core

    fallback = normalize_object_concept(
        object_lemma or "",
        max_tokens=object_long_concept_max_tokens,
        truncate_mode=object_long_concept_truncate_mode,
        enable_anchor_shortcut=fallback_anchor_shortcut_enabled,
        anchor_shortcut_max_tokens=fallback_anchor_shortcut_max_tokens,
    )
    if fallback:
        return fallback

    return normalize_object_concept(
        object_raw or "",
        max_tokens=object_long_concept_max_tokens,
        truncate_mode=object_long_concept_truncate_mode,
        enable_anchor_shortcut=fallback_anchor_shortcut_enabled,
        anchor_shortcut_max_tokens=fallback_anchor_shortcut_max_tokens,
    )


class VerbWeightModel:
    """
    Lightweight verb-weight model reused from innovation scoring.
    - anchor verbs use fixed weights
    - other verbs use adaptive IDF mapping
    """

    def __init__(
        self,
        task_doc_freq: Dict[str, int],
        total_docs: int,
        config_path: str,
        strict_policy: Optional[Dict[str, object]] = None,
    ):
        self.task_doc_freq = task_doc_freq
        self.total_docs = max(int(total_docs), 0)
        self.verb_anchors: Dict[str, float] = {}
        self.idf_weight_min = 0.2
        self.idf_weight_max = 1.0

        strict_policy = dict(strict_policy or {})
        self.strict_policy_enabled = _as_bool(strict_policy.get("enabled", True), True)
        self.strict_tier_form_weights: Dict[str, float] = {}
        self.strict_creative_weight = max(0.0, min(1.0, _safe_float(strict_policy.get("creative_weight", 1.0), 1.0)))
        self.strict_usage_max_weight = max(
            0.0, min(1.0, _safe_float(strict_policy.get("usage_max_weight", 0.18), 0.18))
        )
        self.strict_unknown_max_weight = max(
            0.0, min(1.0, _safe_float(strict_policy.get("unknown_max_weight", 0.6), 0.6))
        )
        creative_verbs = _as_str_list(strict_policy.get("creative_verbs"), list(STRICT_CREATIVE_VERBS))
        usage_verbs = _as_str_list(strict_policy.get("usage_verbs"), list(STRICT_USAGE_VERBS))
        tier_definitions = strict_policy.get("tier_definitions", [])
        if isinstance(tier_definitions, list):
            for item in tier_definitions:
                if not isinstance(item, dict):
                    continue
                weight = max(0.0, min(1.0, _safe_float(item.get("weight", 0.0), 0.0)))
                verbs = _as_str_list(item.get("verbs"), [])
                self._register_tier_forms(verbs, weight)
        self.strict_creative_forms = self._expand_forms(creative_verbs)
        self.strict_usage_forms = self._expand_forms(usage_verbs)

        self._load_anchor_config(config_path)
        self.idf_range = self._compute_idf_range()
        if self.strict_policy_enabled:
            logger.info(
                "Strict verb policy enabled: tier=%s forms, creative=%s forms, usage=%s forms, usage_max=%.2f, unknown_max=%.2f",
                len(self.strict_tier_form_weights),
                len(self.strict_creative_forms),
                len(self.strict_usage_forms),
                self.strict_usage_max_weight,
                self.strict_unknown_max_weight,
            )

    def _load_anchor_config(self, config_path: str):
        candidate_paths = [Path(config_path), Path(DEFAULT_VERB_WEIGHTS_PATH)]
        config_file = next((p for p in candidate_paths if p.exists()), None)
        if config_file is None:
            logger.warning("Verb anchor config not found, fallback to IDF-only weights")
            return

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)

            anchor_groups = [
                ("anchor_high", 0.95),
                ("anchor_medium_high", 0.8),
                ("anchor_low", 0.25),
                ("anchor_very_low", 0.1),
            ]
            for group_name, weight in anchor_groups:
                for verb in config.get(group_name, {}).get("verbs", []):
                    for form in self._generate_verb_forms(verb.lower()):
                        self.verb_anchors[form] = weight

            idf_range = config.get("idf_weight_range", {})
            self.idf_weight_min = float(idf_range.get("min", 0.2))
            self.idf_weight_max = float(idf_range.get("max", 1.0))

            logger.info(
                "Loaded %s anchor verb forms, IDF range [%.2f, %.2f]",
                len(self.verb_anchors),
                self.idf_weight_min,
                self.idf_weight_max,
            )
        except Exception as exc:
            logger.warning("Failed to load verb anchor config: %s", exc)

    @staticmethod
    def _is_cvc_ending(verb: str) -> bool:
        if len(verb) < 3:
            return False
        a, b, c = verb[-3], verb[-2], verb[-1]
        return (a not in "aeiou") and (b in "aeiou") and (c not in "aeiouwxy")

    @staticmethod
    def _generate_verb_forms(verb: str) -> List[str]:
        token = (verb or "").strip().lower()
        if not token:
            return []

        forms: set[str] = {token}
        if "_" in token or "-" in token:
            # Multi-word verbs get only light expansion to avoid noisy variants.
            forms.add(token.replace("-", "_"))
            if not token.endswith("s"):
                forms.add(token + "s")
            irregular = IRREGULAR_VERB_FORMS.get(token, set())
            forms.update(irregular)
            return sorted(forms)

        if token.endswith(("s", "x", "z", "ch", "sh", "o")):
            forms.add(token + "es")
        elif token.endswith("y") and len(token) > 1 and token[-2] not in "aeiou":
            forms.add(token[:-1] + "ies")
        else:
            forms.add(token + "s")

        if token.endswith("e"):
            forms.add(token + "d")
        elif token.endswith("y") and len(token) > 1 and token[-2] not in "aeiou":
            forms.add(token[:-1] + "ied")
        elif token.endswith("ic"):
            forms.add(token + "ked")
        elif VerbWeightModel._is_cvc_ending(token):
            forms.add(token + token[-1] + "ed")
        else:
            forms.add(token + "ed")

        if token.endswith("ie"):
            forms.add(token[:-2] + "ying")
        elif token.endswith("e") and not token.endswith("ee"):
            forms.add(token[:-1] + "ing")
        elif token.endswith("ic"):
            forms.add(token + "king")
        elif VerbWeightModel._is_cvc_ending(token):
            forms.add(token + token[-1] + "ing")
        else:
            forms.add(token + "ing")

        forms.update(IRREGULAR_VERB_FORMS.get(token, set()))
        return sorted(forms)

    @staticmethod
    def _normalize_verb(task: str) -> str:
        token = normalize_task_token(task)
        token = token.replace("-", "_")
        token = re.sub(r"_+", "_", token).strip("_")
        return token

    def _expand_forms(self, verbs: List[str]) -> set[str]:
        forms: set[str] = set()
        for verb in verbs:
            token = self._normalize_verb(verb)
            if not token:
                continue
            forms.add(token)
            for item in self._generate_verb_forms(token):
                norm = self._normalize_verb(item)
                if norm:
                    forms.add(norm)
        return forms

    def _register_tier_forms(self, verbs: List[str], weight: float):
        for token in self._expand_forms(verbs):
            prev = self.strict_tier_form_weights.get(token)
            if prev is None:
                self.strict_tier_form_weights[token] = weight
            else:
                # Overlap terms take the stricter (lower) tier weight.
                self.strict_tier_form_weights[token] = min(prev, weight)

    def _apply_strict_policy(self, verb: str, weight: float) -> float:
        if not self.strict_policy_enabled:
            return weight

        base_weight = max(0.0, min(1.0, weight))
        tier_weight = self.strict_tier_form_weights.get(verb)
        if tier_weight is not None:
            base_weight = max(0.0, min(1.0, tier_weight))

        if verb in self.strict_creative_forms:
            # Creative verbs keep higher weight but still obey tier cap when present.
            if tier_weight is not None:
                return min(base_weight, self.strict_creative_weight)
            return self.strict_creative_weight

        if verb in self.strict_usage_forms:
            return min(base_weight, self.strict_usage_max_weight)

        if self.strict_tier_form_weights:
            return min(base_weight, self.strict_unknown_max_weight)

        return base_weight

    def _compute_idf_range(self) -> Tuple[float, float]:
        if self.total_docs < 1000 or not self.task_doc_freq:
            return (2.0, 12.0)

        min_idf = float("inf")
        max_idf = float("-inf")
        for _, df in self.task_doc_freq.items():
            if df < 5:
                continue
            idf = max(0.0, math.log2(self.total_docs / (df + 1)))
            if idf < min_idf:
                min_idf = idf
            if idf > max_idf:
                max_idf = idf

        if not math.isfinite(min_idf) or not math.isfinite(max_idf):
            return (2.0, 12.0)
        return (min_idf, max_idf)

    def get_weight(self, task: str) -> float:
        if not task:
            return 0.5

        verb = self._normalize_verb(task)
        if not verb:
            return 0.5

        if verb in self.verb_anchors:
            return self._apply_strict_policy(verb, self.verb_anchors[verb])

        if self.total_docs < 1000:
            return self._apply_strict_policy(verb, 0.5)

        df = self.task_doc_freq.get(verb, 0)
        idf = max(0.0, math.log2(self.total_docs / (df + 1)))

        idf_min, idf_max = self.idf_range
        idf_span = max(idf_max - idf_min, 1e-6)
        normalized = (idf - idf_min) / idf_span
        normalized = max(0.0, min(1.0, normalized))
        weight = self.idf_weight_min + (self.idf_weight_max - self.idf_weight_min) * normalized
        return self._apply_strict_policy(verb, weight)


class FrequencyTable:
    """
    Reads Pass0 outputs (`object_yearly` + `total_papers`) and provides
    yearly/cumulative frequency lookup with LRU caching.
    """

    def __init__(
        self,
        stats_db_path: Path,
        vocab_size_estimate: int,
        cache_max_objects: int,
        yearly_freq_smoothing_mode: str = "laplace_adaptive",
        yearly_freq_smoothing_alpha: float = 1.0,
        yearly_freq_smoothing_vocab_size: Optional[int] = None,
        yearly_freq_smoothing_vocab_scale: float = 0.12,
        cumulative_freq_smoothing_mode: str = "laplace_adaptive",
        cumulative_freq_smoothing_alpha: float = 1.0,
        cumulative_freq_smoothing_vocab_size: Optional[int] = None,
        cumulative_freq_smoothing_vocab_scale: float = 0.12,
    ):
        self.stats_db_path = str(stats_db_path)
        self.vocab_size_estimate = int(vocab_size_estimate)
        self.cache_max_objects = int(cache_max_objects)
        self.yearly_freq_smoothing_mode = str(yearly_freq_smoothing_mode or "laplace_adaptive").strip().lower()
        if self.yearly_freq_smoothing_mode not in {"none", "laplace", "laplace_adaptive"}:
            self.yearly_freq_smoothing_mode = "laplace_adaptive"
        self.yearly_freq_smoothing_alpha = max(float(yearly_freq_smoothing_alpha), 0.0)
        self.yearly_freq_smoothing_vocab_size = max(
            int(yearly_freq_smoothing_vocab_size or self.vocab_size_estimate),
            1,
        )
        self.yearly_freq_smoothing_vocab_scale = max(float(yearly_freq_smoothing_vocab_scale), 1e-6)
        self.cumulative_freq_smoothing_mode = str(cumulative_freq_smoothing_mode or "laplace_adaptive").strip().lower()
        if self.cumulative_freq_smoothing_mode not in {"none", "laplace", "laplace_adaptive"}:
            self.cumulative_freq_smoothing_mode = "laplace_adaptive"
        self.cumulative_freq_smoothing_alpha = max(float(cumulative_freq_smoothing_alpha), 0.0)
        self.cumulative_freq_smoothing_vocab_size = max(
            int(cumulative_freq_smoothing_vocab_size or self.vocab_size_estimate),
            1,
        )
        self.cumulative_freq_smoothing_vocab_scale = max(float(cumulative_freq_smoothing_vocab_scale), 1e-6)
        self.min_adaptive_smoothing_vocab = 256

        self.conn = sqlite3.connect(self.stats_db_path)
        self.conn.row_factory = sqlite3.Row
        self.cur = self.conn.cursor()

        self.total_by_year: Dict[int, int] = {}
        self.cumulative_by_year: Dict[int, int] = {}
        for row in self.cur.execute("SELECT year, count, cumulative_count FROM total_papers ORDER BY year"):
            y = int(row["year"])
            self.total_by_year[y] = int(row["count"])
            self.cumulative_by_year[y] = int(row["cumulative_count"])

        self.sorted_years = sorted(self.total_by_year.keys())
        self.latest_total_year = self.sorted_years[-1] if self.sorted_years else 0
        self.total_docs = self.cumulative_by_year.get(self.latest_total_year, 0)

        self.object_yearly_cache: "OrderedDict[str, Dict[int, int]]" = OrderedDict()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def _get_effective_year(self, year: int) -> Optional[int]:
        if not self.sorted_years:
            return None
        if year in self.cumulative_by_year:
            return year
        idx = bisect_right(self.sorted_years, year) - 1
        if idx < 0:
            return None
        return self.sorted_years[idx]

    def get_total_papers(self, year: int) -> int:
        return self.total_by_year.get(year, 0)

    def get_cumulative_total(self, up_to_year: int) -> int:
        effective = self._get_effective_year(up_to_year)
        if effective is None:
            return 0
        return self.cumulative_by_year.get(effective, 0)

    def _fetch_missing_objects(self, objects: List[str]):
        if not objects:
            return
        chunk_size = 500
        for i in range(0, len(objects), chunk_size):
            chunk = objects[i : i + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            query = (
                f"SELECT object_core, year, paper_count FROM object_yearly "
                f"WHERE object_core IN ({placeholders})"
            )
            rows = self.cur.execute(query, chunk).fetchall()

            grouped: Dict[str, Dict[int, int]] = {obj: {} for obj in chunk}
            for row in rows:
                grouped[row["object_core"]][int(row["year"])] = int(row["paper_count"])

            for obj in chunk:
                self.object_yearly_cache[obj] = grouped.get(obj, {})
                self.object_yearly_cache.move_to_end(obj)

            while len(self.object_yearly_cache) > self.cache_max_objects:
                self.object_yearly_cache.popitem(last=False)

    def get_object_series_batch(self, objects: Iterable[str]) -> Dict[str, Dict[int, int]]:
        unique = []
        seen = set()
        for obj in objects:
            if not obj or obj in seen:
                continue
            unique.append(obj)
            seen.add(obj)

        missing = [obj for obj in unique if obj not in self.object_yearly_cache]
        if missing:
            self._fetch_missing_objects(missing)

        result = {}
        for obj in unique:
            series = self.object_yearly_cache.get(obj)
            if series is None:
                series = {}
                self.object_yearly_cache[obj] = series
            self.object_yearly_cache.move_to_end(obj)
            result[obj] = series
        return result

    def _effective_smoothing_vocab(self, total: int, base_vocab: int, mode: str, scale: float) -> int:
        base_vocab = max(int(base_vocab), 1)
        if mode != "laplace_adaptive":
            return base_vocab
        dynamic_vocab = max(int(max(total, 0) * max(scale, 1e-6)), self.min_adaptive_smoothing_vocab)
        return max(min(base_vocab, dynamic_vocab), 1)

    def get_yearly_freq_from_series(self, series: Dict[int, int], year: int) -> float:
        total = self.get_total_papers(year)
        mode = self.yearly_freq_smoothing_mode
        if total <= 0 and mode == "none":
            return 0.0
        count = int(series.get(year, 0))
        if mode in {"laplace", "laplace_adaptive"}:
            smooth_vocab = self._effective_smoothing_vocab(
                total=total,
                base_vocab=self.yearly_freq_smoothing_vocab_size,
                mode=mode,
                scale=self.yearly_freq_smoothing_vocab_scale,
            )
            return (count + self.yearly_freq_smoothing_alpha) / (
                max(total, 0) + smooth_vocab
            )
        total = max(total, 1)
        return count / total

    def get_cumulative_freq_from_series(self, series: Dict[int, int], up_to_year: int) -> float:
        cum_total = self.get_cumulative_total(up_to_year)
        mode = self.cumulative_freq_smoothing_mode
        if cum_total <= 0 and mode == "none":
            return 0.0

        cum_count = 0
        for year, count in series.items():
            if year <= up_to_year:
                cum_count += int(count)

        if mode in {"laplace", "laplace_adaptive"}:
            smooth_vocab = self._effective_smoothing_vocab(
                total=cum_total,
                base_vocab=self.cumulative_freq_smoothing_vocab_size,
                mode=mode,
                scale=self.cumulative_freq_smoothing_vocab_scale,
            )
            return (cum_count + self.cumulative_freq_smoothing_alpha) / (
                max(cum_total, 0) + smooth_vocab
            )

        if cum_total <= 0:
            return 0.0
        return cum_count / max(cum_total, 1)

    def load_task_doc_freq_upto_year(self, up_to_year: int) -> Dict[str, int]:
        data: Dict[str, int] = {}
        for row in self.cur.execute(
            """
            SELECT task_key, SUM(paper_count) AS doc_count
            FROM task_yearly
            WHERE year <= ?
            GROUP BY task_key
            """,
            (int(up_to_year),),
        ):
            data[row["task_key"]] = int(row["doc_count"])
        return data

    def load_task_doc_freq(self) -> Dict[str, int]:
        data: Dict[str, int] = {}
        for row in self.cur.execute("SELECT task_key, doc_count FROM task_doc_freq"):
            data[row["task_key"]] = int(row["doc_count"])
        return data


class ImpactCalculatorV6:
    def __init__(self, config: dict = None):
        self.config = config or build_runtime_config()
        self.rpu_db_path = self.config["rpu_db_path"]
        self.output_dir = Path(self.config["output_dir"])
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.stats_db_path = self.output_dir / self.config["stats_db_name"]
        self.checkpoint_path = self.output_dir / self.config["checkpoint_name"]
        self.summary_path = self.output_dir / self.config["summary_name"]
        self.progress_path = self.output_dir / self.config["progress_name"]
        self.checkpoint = self._load_checkpoint()

    def _load_checkpoint(self) -> dict:
        defaults = {
            "pass0_complete": False,
            "pass0_years_completed": [],
            "pass0_current_year": None,
            "pass1_years": [],
            "pass2_years": [],
            "pass2_complete": False,
            "schema_version": self.config["schema_version"],
        }
        if self.checkpoint_path.exists():
            with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return defaults
            merged = dict(defaults)
            merged.update(data)
            return merged
        return defaults

    def _save_checkpoint(self):
        self.checkpoint["schema_version"] = self.config["schema_version"]
        self.checkpoint["updated_at"] = datetime.now().isoformat()
        with open(self.checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(self.checkpoint, f, indent=2, ensure_ascii=False)

    def _write_progress_status(self, stage: str, payload: Dict):
        """
        Write progress status to a JSON file for external real-time monitoring.
        """
        body = {
            "updated_at": datetime.now().isoformat(),
            "stage": stage,
        }
        body.update(payload or {})
        try:
            with open(self.progress_path, "w", encoding="utf-8") as f:
                json.dump(body, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Failed to write progress status file: %s", exc)

    def _create_progress_bar(self, total: Optional[int], desc: str, unit: str = "paper", leave: bool = True):
        if not self.config.get("enable_progress_bar", True):
            return None
        if tqdm is None:
            return None
        try:
            kwargs = {
                "desc": desc,
                "unit": unit,
                "dynamic_ncols": True,
                "mininterval": max(float(self.config.get("progress_refresh_sec", 1.0)), 0.2),
                "leave": leave,
            }
            if total is not None:
                kwargs["total"] = max(int(total), 0)
            return tqdm(**kwargs)
        except Exception:
            return None

    @staticmethod
    def _update_progress_bar(pbar, n: int):
        if pbar is not None and n > 0:
            pbar.update(n)

    def _is_stats_db_compatible(self) -> bool:
        if not self.stats_db_path.exists():
            return False
        conn = None
        try:
            conn = sqlite3.connect(str(self.stats_db_path))
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='meta'")
            if not cur.fetchone():
                return False
            row = cur.execute("SELECT value FROM meta WHERE key='stats_schema_version'").fetchone()
            return bool(row and row[0] == self.config["schema_version"])
        except Exception:
            return False
        finally:
            if conn is not None:
                conn.close()

    def _is_pass0_partial_resumable(self, completed_years: set[int]) -> bool:
        """
        Allow resuming Pass0 by completed years after interruption
        (meta may not be fully flushed yet).
        """
        if not self.stats_db_path.exists():
            return False
        if not completed_years:
            return False

        conn = None
        try:
            conn = sqlite3.connect(str(self.stats_db_path))
            cur = conn.cursor()
            tables = {
                row[0]
                for row in cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('object_yearly','task_yearly','meta')"
                ).fetchall()
            }
            if not {"object_yearly", "task_yearly", "meta"}.issubset(tables):
                return False

            existing_years = {
                int(row[0])
                for row in cur.execute("SELECT DISTINCT year FROM object_yearly").fetchall()
                if row and row[0] is not None
            }
            # Resume only when stats DB already covers checkpoint-completed years.
            return set(int(y) for y in completed_years).issubset(existing_years)
        except Exception:
            return False
        finally:
            if conn is not None:
                conn.close()

    def _get_pass0_years_from_stats_db(self) -> set[int]:
        if not self.stats_db_path.exists():
            return set()
        conn = None
        try:
            conn = sqlite3.connect(str(self.stats_db_path))
            cur = conn.cursor()
            rows = cur.execute("SELECT year FROM total_papers WHERE count > 0").fetchall()
            return {int(row[0]) for row in rows if row and row[0] is not None}
        except Exception:
            return set()
        finally:
            if conn is not None:
                conn.close()

    def _assert_pass0_ready_for_years(self, years: List[int]):
        required_years = sorted({int(y) for y in years})
        if not required_years:
            return
        checkpoint_years = {
            int(y)
            for y in self.checkpoint.get("pass0_years_completed", [])
            if y is not None
        }
        stats_years = self._get_pass0_years_from_stats_db()
        missing_checkpoint = sorted(set(required_years) - checkpoint_years)
        missing_stats = sorted(set(required_years) - stats_years)
        if missing_checkpoint or missing_stats:
            raise RuntimeError(
                "Pass0 does not fully cover requested years."
                f" Missing checkpoint years={missing_checkpoint},"
                f" missing stats-db years={missing_stats}."
                " Run --pass 0 for these years first."
            )

    def _prepare_stats_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.stats_db_path))
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA temp_store=MEMORY")
        cur.execute("PRAGMA cache_size=-200000")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS object_yearly (
                object_core TEXT NOT NULL,
                year INTEGER NOT NULL,
                paper_count INTEGER DEFAULT 0,
                PRIMARY KEY (object_core, year)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS object_cumulative (
                object_core TEXT NOT NULL,
                up_to_year INTEGER NOT NULL,
                cumulative_papers INTEGER DEFAULT 0,
                cumulative_freq REAL DEFAULT 0.0,
                PRIMARY KEY (object_core, up_to_year)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS total_papers (
                year INTEGER PRIMARY KEY,
                count INTEGER DEFAULT 0,
                cumulative_count INTEGER DEFAULT 0
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS task_doc_freq (
                task_key TEXT PRIMARY KEY,
                doc_count INTEGER DEFAULT 0
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS task_yearly (
                task_key TEXT NOT NULL,
                year INTEGER NOT NULL,
                paper_count INTEGER DEFAULT 0,
                PRIMARY KEY (task_key, year)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.commit()
        return conn

    @staticmethod
    def _flush_object_counts(cur: sqlite3.Cursor, pending: Dict[Tuple[str, int], int]):
        if not pending:
            return 0
        rows = [(obj, year, count) for (obj, year), count in pending.items()]
        cur.executemany(
            """
            INSERT INTO object_yearly (object_core, year, paper_count)
            VALUES (?, ?, ?)
            ON CONFLICT(object_core, year)
            DO UPDATE SET paper_count = paper_count + excluded.paper_count
            """,
            rows,
        )
        pending.clear()
        return len(rows)

    @staticmethod
    def _flush_task_year_counts(cur: sqlite3.Cursor, pending: Dict[Tuple[str, int], int]):
        if not pending:
            return 0
        rows = [(task, year, count) for (task, year), count in pending.items()]
        cur.executemany(
            """
            INSERT INTO task_yearly (task_key, year, paper_count)
            VALUES (?, ?, ?)
            ON CONFLICT(task_key, year)
            DO UPDATE SET paper_count = paper_count + excluded.paper_count
            """,
            rows,
        )
        pending.clear()
        return len(rows)


    def _build_pass0_query_for_year(self, year: int) -> Tuple[str, List[object]]:
        correction_filter = ""
        if self.config.get("exclude_correction_papers", True):
            correction_filter = f" AND {build_correction_filter_sql('p')}"

        # Explicit ordering keeps per-paper streaming aggregation deterministic.
        query = f"""
            SELECT r.paper_id,
                   p.pub_year,
                   json_extract(r.task_cores, '$[0]') AS task_core,
                   r.task_lemma,
                   r.task,
                   json_extract(r.object_cores, '$[0]') AS object_core,
                   r.object_lemma,
                   r.object,
                   r.object_coverage
            FROM papers p
            JOIN rpu r ON p.paper_id = r.paper_id
            WHERE p.pub_year = ?
              {correction_filter}
            ORDER BY r.paper_id
        """
        return query, [year]

    def _count_pass0_papers(self) -> int:
        years = self.config["years"]
        start_year, end_year = min(years), max(years)
        correction_filter = ""
        if self.config.get("exclude_correction_papers", True):
            correction_filter = f" AND {build_correction_filter_sql('p')}"
        conn = sqlite3.connect(self.rpu_db_path)
        cur = conn.cursor()
        row = cur.execute(
            f"""
            SELECT COUNT(*)
            FROM papers p
            WHERE p.pub_year BETWEEN ? AND ?
              {correction_filter}
            """,
            (start_year, end_year),
        ).fetchone()
        conn.close()
        return int(row[0]) if row else 0

    def _count_pass0_papers_by_year(self, years: Optional[List[int]] = None) -> Dict[int, int]:
        target_years = sorted(set(int(y) for y in (years if years is not None else self.config["years"])))
        if not target_years:
            return {}

        conn = sqlite3.connect(self.rpu_db_path)
        cur = conn.cursor()

        # With correction filtering enabled, count by year for earlier progress feedback.
        if self.config.get("exclude_correction_papers", True):
            correction_filter = f" AND {build_correction_filter_sql('p')}"
            yearly_counts: Dict[int, int] = {}
            started_at = time.time()

            logger.info("Pass 0 stage 0: pre-count papers per year (with correction filter)...")
            self._write_progress_status(
                "pass0_counting",
                {
                    "phase": "pass0_counting",
                    "years": target_years,
                    "completed_years": 0,
                    "total_years": len(target_years),
                },
            )

            for idx, year in enumerate(target_years, start=1):
                row = cur.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM papers p
                    WHERE p.pub_year = ?
                      {correction_filter}
                    """,
                    (year,),
                ).fetchone()
                yearly_counts[year] = int(row[0]) if row else 0

                elapsed = time.time() - started_at
                rate = idx / elapsed if elapsed > 0 else 0.0
                eta_sec = (len(target_years) - idx) / rate if rate > 0 else 0.0
                logger.info(
                    "Pass 0 pre-count: %s/%s year=%s papers=%s | ETA %.1f s",
                    idx,
                    len(target_years),
                    year,
                    f"{yearly_counts[year]:,}",
                    eta_sec,
                )
                self._write_progress_status(
                    "pass0_counting",
                    {
                        "phase": "pass0_counting",
                        "years": target_years,
                        "completed_years": idx,
                        "total_years": len(target_years),
                        "current_year": year,
                        "current_year_count": yearly_counts[year],
                        "years_per_sec": round(rate, 3),
                        "eta_seconds": round(eta_sec, 1),
                    },
                )

            conn.close()
            return yearly_counts

        # Without correction filtering, grouped range counting is faster.
        start_year, end_year = min(target_years), max(target_years)
        rows = cur.execute(
            """
            SELECT p.pub_year, COUNT(*)
            FROM papers p
            WHERE p.pub_year BETWEEN ? AND ?
            GROUP BY p.pub_year
            """,
            (start_year, end_year),
        ).fetchall()
        conn.close()

        raw = {int(year): int(count) for year, count in rows}
        return {int(year): int(raw.get(int(year), 0)) for year in target_years}

    def run_pass0(self, years: List[int] = None, force: bool = False):
        all_years = sorted(set(int(y) for y in self.config["years"]))
        all_years_set = set(all_years)
        requested_years = sorted(set(int(y) for y in (years if years is not None else all_years)))
        invalid_years = sorted(set(requested_years) - all_years_set)
        if invalid_years:
            logger.warning("Pass 0 skipping years outside configured range: %s", invalid_years)
        years = [y for y in requested_years if y in all_years_set]
        if not years:
            logger.warning("Pass 0 has no valid years to process; skipping.")
            return

        stats_compatible = self._is_stats_db_compatible()
        completed_years = set(int(y) for y in self.checkpoint.get("pass0_years_completed", []))
        partial_resume_ok = (not stats_compatible) and self._is_pass0_partial_resumable(completed_years)
        if not force and stats_compatible and set(years).issubset(completed_years):
            logger.info("Pass 0 target years already complete and stats DB compatible; skipping: %s", years)
            return

        logger.info("=" * 60)
        logger.info("Pass 0: building object/year frequency tables (V6)")
        logger.info("=" * 60)

        started_at = time.time()
        all_papers_by_year = self._count_pass0_papers_by_year(years=all_years)
        total_papers_by_year = {y: int(all_papers_by_year.get(y, 0)) for y in years}
        total_papers_target = sum(total_papers_by_year.values())
        logger.info("Pass 0 target paper count: %s", f"{total_papers_target:,}")

        stats_conn = self._prepare_stats_db()
        stats_cur = stats_conn.cursor()

        rebuild_all = ((not stats_compatible) and (not partial_resume_ok)) or (force and set(years) == all_years_set)
        if partial_resume_ok:
            logger.info("Pass 0: detected resumable partial progress; resume by year.")
        if rebuild_all:
            logger.info("Pass 0: entering full rebuild mode.")
            for table in ("object_yearly", "object_cumulative", "total_papers", "task_doc_freq", "task_yearly", "meta"):
                stats_cur.execute(f"DELETE FROM {table}")
            stats_conn.commit()
            self.checkpoint["pass0_years_completed"] = []
            self.checkpoint["pass0_complete"] = False
            self.checkpoint["pass0_current_year"] = None
            self._save_checkpoint()
        elif force:
            logger.info("Pass 0: force rerun for selected years=%s", years)
            force_years = set(years)
            existing_completed = set(int(y) for y in self.checkpoint.get("pass0_years_completed", []))
            existing_completed -= force_years
            self.checkpoint["pass0_years_completed"] = sorted(existing_completed)
            self.checkpoint["pass0_complete"] = False
            self.checkpoint["pass0_current_year"] = None
            self._save_checkpoint()

        completed_years = set(int(y) for y in self.checkpoint.get("pass0_years_completed", []))
        years_to_process = [y for y in years if y not in completed_years]
        processed_papers = sum(total_papers_by_year.get(y, 0) for y in years if y in completed_years)

        if completed_years:
            logger.info(
                "Pass 0 resume: completed_years=%s, processed_papers=%s",
                sorted(completed_years),
                f"{processed_papers:,}",
            )

        # Bootstrap schema/version metadata before the main write loop.
        meta_rows_bootstrap = [
            ("stats_schema_version", self.config["schema_version"]),
            ("created_at", datetime.now().isoformat()),
            ("exclude_correction_papers", "1" if self.config["exclude_correction_papers"] else "0"),
            ("vocab_size_estimate", str(self.config["vocab_size_estimate"])),
            ("current_year", str(self.config["current_year"])),
        ]
        stats_cur.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", meta_rows_bootstrap)
        stats_conn.commit()

        self._write_progress_status(
            "pass0_running",
            {
                "phase": "pass0",
                "completed_years": sorted(completed_years),
                "current_year": None,
                "processed_papers": processed_papers,
                "total_papers": total_papers_target,
            },
        )
        logger.info("Pass 0 stage 1: yearly scan and write object_yearly/task_yearly.")
        overall_pbar = self._create_progress_bar(total_papers_target, "Pass0 total")
        overall_pending = 0
        if overall_pbar is not None and processed_papers > 0:
            self._update_progress_bar(overall_pbar, processed_papers)

        rpu_conn = sqlite3.connect(self.rpu_db_path)
        rpu_cur = rpu_conn.cursor()

        inserted_object_keys = 0
        inserted_task_keys = 0
        flush_threshold = 1_000_000
        progress_log_interval = 200_000

        for year in years_to_process:
            year_target = int(total_papers_by_year.get(year, 0))

            # Clear yearly rows before replay to avoid duplicate accumulation.
            stats_cur.execute("DELETE FROM object_yearly WHERE year = ?", (year,))
            stats_cur.execute("DELETE FROM task_yearly WHERE year = ?", (year,))
            stats_conn.commit()

            self.checkpoint["pass0_current_year"] = year
            self._save_checkpoint()

            self._write_progress_status(
                "pass0_running",
                {
                    "phase": "pass0",
                    "completed_years": sorted(completed_years),
                    "current_year": year,
                    "current_year_target": year_target,
                    "current_year_processed": 0,
                    "processed_papers": processed_papers,
                    "total_papers": total_papers_target,
                },
            )

            query, params = self._build_pass0_query_for_year(year)
            rpu_cur.execute(query, params)

            pending_object_counts: Dict[Tuple[str, int], int] = defaultdict(int)
            pending_task_counts: Dict[Tuple[str, int], int] = defaultdict(int)

            current_paper_id: Optional[str] = None
            current_year: Optional[int] = year
            paper_objects = set()
            paper_tasks = set()
            year_processed = 0

            def flush_current_paper():
                nonlocal inserted_object_keys, inserted_task_keys
                nonlocal processed_papers, year_processed, overall_pending
                if current_paper_id is None or current_year is None:
                    return

                year_processed += 1
                processed_papers += 1
                overall_pending += 1

                for obj in paper_objects:
                    pending_object_counts[(obj, current_year)] += 1
                for task in paper_tasks:
                    pending_task_counts[(task, current_year)] += 1

                if len(pending_object_counts) >= flush_threshold:
                    inserted_object_keys += self._flush_object_counts(stats_cur, pending_object_counts)
                    stats_conn.commit()
                if len(pending_task_counts) >= flush_threshold:
                    inserted_task_keys += self._flush_task_year_counts(stats_cur, pending_task_counts)
                    stats_conn.commit()

                if overall_pending >= 2000:
                    self._update_progress_bar(overall_pbar, overall_pending)
                    elapsed = time.time() - started_at
                    rate = processed_papers / elapsed if elapsed > 0 else 0.0
                    eta_min = (
                        (total_papers_target - processed_papers) / rate / 60.0
                        if rate > 0 and total_papers_target > 0
                        else 0.0
                    )
                    if overall_pbar is not None:
                        overall_pbar.set_postfix_str(
                            f"year={year} y={year_processed:,}/{year_target:,} rate={rate:.0f}/s eta={eta_min:.1f}m",
                            refresh=False,
                        )
                    overall_pending = 0

                if year_processed % progress_log_interval == 0:
                    elapsed = time.time() - started_at
                    rate = processed_papers / elapsed if elapsed > 0 else 0.0
                    eta_min = (
                        (total_papers_target - processed_papers) / rate / 60.0
                        if rate > 0 and total_papers_target > 0
                        else 0.0
                    )
                    self._write_progress_status(
                        "pass0_running",
                        {
                            "phase": "pass0",
                            "completed_years": sorted(completed_years),
                            "current_year": year,
                            "current_year_target": year_target,
                            "current_year_processed": year_processed,
                            "processed_papers": processed_papers,
                            "total_papers": total_papers_target,
                            "papers_per_sec": round(rate, 2),
                            "eta_minutes": round(eta_min, 2),
                        },
                    )

            while True:
                rows = rpu_cur.fetchmany(200000)
                if not rows:
                    break

                for row in rows:
                    paper_id, pub_year, task_core, task_lemma, task, object_core, object_lemma, object_raw, object_coverage = row
                    if paper_id != current_paper_id:
                        flush_current_paper()
                        current_paper_id = paper_id
                        current_year = int(pub_year) if pub_year is not None else year
                        paper_objects = set()
                        paper_tasks = set()

                    object_key = resolve_object_concept(
                        object_core=object_core or "",
                        object_lemma=object_lemma or "",
                        object_raw=object_raw or "",
                        object_coverage=_safe_float(object_coverage, 0.0),
                        min_core_coverage=self.config["min_core_coverage"],
                        use_unified_concept_representation=self.config.get(
                            "use_unified_concept_representation", True
                        ),
                        fallback_anchor_shortcut_enabled=self.config.get(
                            "fallback_anchor_shortcut_enabled", True
                        ),
                        fallback_anchor_shortcut_max_tokens=self.config.get(
                            "fallback_anchor_shortcut_max_tokens", 2
                        ),
                        object_long_concept_max_tokens=self.config.get("object_long_concept_max_tokens", 8),
                        object_long_concept_truncate_mode=self.config.get(
                            "object_long_concept_truncate_mode",
                            "head_tail",
                        ),
                    )
                    if object_key:
                        paper_objects.add(object_key)

                    task_key = resolve_task_key(task_core or "", task_lemma or "", task or "")
                    if task_key:
                        paper_tasks.add(task_key)

            flush_current_paper()
            inserted_object_keys += self._flush_object_counts(stats_cur, pending_object_counts)
            inserted_task_keys += self._flush_task_year_counts(stats_cur, pending_task_counts)
            stats_conn.commit()

            completed_years.add(year)
            self.checkpoint["pass0_years_completed"] = sorted(completed_years)
            self.checkpoint["pass0_current_year"] = None
            self._save_checkpoint()

        self._update_progress_bar(overall_pbar, overall_pending)
        if overall_pbar is not None:
            overall_pbar.close()

        # Rebuild aggregate tables from yearly stats; object_cumulative is optional.
        materialize_object_cumulative = _as_bool(
            self.config.get("materialize_object_cumulative", False),
            False,
        )
        logger.info(
            "Pass 0 stage 2: rebuild total_papers/task_doc_freq%s and indexes.",
            "/object_cumulative" if materialize_object_cumulative else "",
        )
        stats_cur.execute("DELETE FROM total_papers")
        cumulative = 0
        total_rows = []
        for year in all_years:
            count = int(all_papers_by_year.get(year, 0))
            cumulative += count
            total_rows.append((year, count, cumulative))
        stats_cur.executemany(
            "INSERT INTO total_papers (year, count, cumulative_count) VALUES (?, ?, ?)",
            total_rows,
        )

        stats_cur.execute("DELETE FROM task_doc_freq")
        stats_cur.execute(
            """
            INSERT INTO task_doc_freq (task_key, doc_count)
            SELECT task_key, SUM(paper_count) AS doc_count
            FROM task_yearly
            GROUP BY task_key
            """
        )

        stats_cur.execute("DELETE FROM object_cumulative")
        if materialize_object_cumulative:
            logger.info("Pass 0: materializing object_cumulative ...")
            stats_cur.execute(
                """
                INSERT INTO object_cumulative (object_core, up_to_year, cumulative_papers, cumulative_freq)
                SELECT object_core,
                       year AS up_to_year,
                       SUM(paper_count) OVER (
                           PARTITION BY object_core
                           ORDER BY year
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                       ) AS cumulative_papers,
                       0.0
                FROM object_yearly
                ORDER BY object_core, year
                """
            )
            stats_cur.execute(
                """
                UPDATE object_cumulative
                SET cumulative_freq = (cumulative_papers + 1.0) / (
                    COALESCE(
                        (SELECT cumulative_count FROM total_papers tp WHERE tp.year = object_cumulative.up_to_year),
                        0
                    ) + ?
                )
                """,
                (self.config["vocab_size_estimate"],),
            )

        logger.info("Pass 0: creating indexes ...")
        stats_cur.execute("CREATE INDEX IF NOT EXISTS idx_object_yearly_core ON object_yearly(object_core)")
        stats_cur.execute("CREATE INDEX IF NOT EXISTS idx_object_yearly_year ON object_yearly(year)")
        stats_cur.execute("CREATE INDEX IF NOT EXISTS idx_task_yearly_task ON task_yearly(task_key)")
        stats_cur.execute("CREATE INDEX IF NOT EXISTS idx_task_yearly_year ON task_yearly(year)")
        if materialize_object_cumulative:
            stats_cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_object_cumulative_lookup ON object_cumulative(object_core, up_to_year)"
            )
        stats_cur.execute("CREATE INDEX IF NOT EXISTS idx_task_doc_freq_count ON task_doc_freq(doc_count)")

        meta_rows = [
            ("stats_schema_version", self.config["schema_version"]),
            ("created_at", datetime.now().isoformat()),
            ("exclude_correction_papers", "1" if self.config["exclude_correction_papers"] else "0"),
            ("vocab_size_estimate", str(self.config["vocab_size_estimate"])),
            ("current_year", str(self.config["current_year"])),
        ]
        stats_cur.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", meta_rows)
        stats_conn.commit()

        rpu_conn.close()
        stats_conn.close()

        self.checkpoint["pass0_complete"] = all_years_set.issubset(completed_years)
        self.checkpoint["pass0_years_completed"] = sorted(completed_years)
        self.checkpoint["pass0_current_year"] = None
        # A fresh Pass0 invalidates downstream pass caches.
        self.checkpoint["pass1_years"] = []
        self.checkpoint["pass2_years"] = []
        self.checkpoint["pass2_complete"] = False
        self._save_checkpoint()

        elapsed = time.time() - started_at
        logger.info("Pass 0: object_yearly upsert keys=%s", f"{inserted_object_keys:,}")
        logger.info("Pass 0: task_yearly upsert keys=%s", f"{inserted_task_keys:,}")
        logger.info(
            "Pass 0 completed: elapsed=%.1f min, processed_papers=%s",
            elapsed / 60.0,
            f"{processed_papers:,}",
        )
        self._write_progress_status(
            "pass0_complete",
            {
                "phase": "pass0",
                "completed_years": sorted(completed_years),
                "processed_papers": processed_papers,
                "total_papers": total_papers_target,
            },
        )

    def _build_year_pass1_query(self, year: int) -> Tuple[str, List[object]]:
        correction_filter = ""
        if self.config.get("exclude_correction_papers", True):
            correction_filter = f" AND {build_correction_filter_sql('p')}"

        query = f"""
            SELECT r.paper_id,
                   p.pub_year,
                   json_extract(r.task_cores, '$[0]') AS task_core,
                   r.task_lemma,
                   r.task,
                   json_extract(r.object_cores, '$[0]') AS object_core,
                   r.object_lemma,
                   r.object,
                   r.object_coverage
            FROM papers p
            JOIN rpu r ON p.paper_id = r.paper_id
            WHERE p.pub_year = ?
              {correction_filter}
            ORDER BY r.paper_id
        """
        return query, [year]

    def _count_year_papers(self, conn: sqlite3.Connection, year: int) -> int:
        correction_filter = ""
        if self.config.get("exclude_correction_papers", True):
            correction_filter = f" AND {build_correction_filter_sql('p')}"
        cur = conn.cursor()
        row = cur.execute(
            f"""
            SELECT COUNT(*) FROM papers p
            WHERE p.pub_year = ?
              {correction_filter}
            """,
            (year,),
        ).fetchone()
        return int(row[0]) if row else 0

    def _resolve_object_verb_weight(self, info: Dict[str, object]) -> float:
        max_weight = float(info.get("verb_weight_max", info.get("verb_weight", 0.0)))
        total_weight = float(info.get("verb_weight_sum", max_weight))
        weight_count = max(int(info.get("verb_weight_count", 1)), 1)
        mean_weight = total_weight / weight_count

        mode = str(self.config.get("object_verb_weight_mode", "blended")).strip().lower()
        if mode in {"mean", "average"}:
            resolved = mean_weight
        elif mode in {"max"}:
            resolved = max_weight
        else:
            blend_alpha = max(0.0, min(float(self.config.get("object_verb_weight_blend_alpha", 0.65)), 1.0))
            resolved = blend_alpha * max_weight + (1.0 - blend_alpha) * mean_weight

        return max(0.0, min(1.0, resolved))


    def _compute_paper_signals(
        self,
        paper_id: str,
        pub_year: int,
        object_entries: Dict[str, dict],
        freq_table: FrequencyTable,
    ) -> dict:
        top_k = self.config["top_k"]
        current_year = self.config["current_year"]
        min_observable_years = self.config["min_observable_years"]
        stability_bonus_weight = max(float(self.config.get("stability_bonus_weight", 0.08)), 0.0)
        stability_floor_ratio = max(0.0, min(float(self.config.get("stability_floor_ratio", 0.85)), 0.999999))
        stability_bonus_growth_power = max(float(self.config.get("stability_bonus_growth_power", 0.6)), 1e-6)
        stability_bonus_max_ratio = max(float(self.config.get("stability_bonus_max_ratio", 0.5)), 0.0)
        consistency_prior_strength = max(float(self.config.get("consistency_prior_strength", 2.0)), 0.0)
        consistency_prior_mean = max(0.0, min(float(self.config.get("consistency_prior_mean", 0.55)), 1.0))
        consistency_prior_observable_scale = max(
            float(self.config.get("consistency_prior_observable_scale", 2.0)),
            1e-6,
        )
        consistency_baseline_window = max(int(self.config.get("consistency_baseline_window", 3)), 1)
        novelty_freq_source = str(self.config.get("novelty_freq_source", "cumulative")).strip().lower()
        if novelty_freq_source not in {"yearly", "cumulative"}:
            novelty_freq_source = "cumulative"
        consistency_freq_source = str(self.config.get("consistency_freq_source", "yearly")).strip().lower()
        if consistency_freq_source not in {"yearly", "cumulative"}:
            consistency_freq_source = "yearly"
        concept_tf_weight = max(float(self.config.get("concept_tf_weight", 0.15)), 0.0)
        consistency_threshold = max(float(self.config.get("consistency_threshold", 0.5)), 1e-6)
        density_penalty_floor_count = max(int(self.config.get("density_penalty_floor_count", 2)), 2)
        density_scope = str(self.config.get("density_scope", "all_positive")).strip().lower()
        if density_scope not in {"all_positive", "top_k_capped"}:
            density_scope = "all_positive"
        stability_requires_growth = _as_bool(self.config.get("stability_requires_growth", True), True)
        insufficient_window_policy = str(self.config.get("insufficient_window_policy", "diagnostic")).strip().lower()
        if insufficient_window_policy not in {"diagnostic", "downweight", "filter"}:
            insufficient_window_policy = "diagnostic"
        insufficient_window_downweight = max(
            0.0,
            min(float(self.config.get("insufficient_window_downweight", 0.5)), 1.0),
        )
        scarcity_sigmoid_alpha = max(float(self.config.get("scarcity_sigmoid_alpha", 8000.0)), 1e-6)
        scarcity_sigmoid_threshold = max(float(self.config.get("scarcity_sigmoid_threshold", 5e-4)), 1e-12)
        scarcity_min_weight = float(self.config.get("scarcity_min_weight", 1.0))
        scarcity_max_weight = float(self.config.get("scarcity_max_weight", 1.3))
        if scarcity_max_weight < scarcity_min_weight:
            scarcity_min_weight, scarcity_max_weight = scarcity_max_weight, scarcity_min_weight

        observable_years = max(0, current_year - pub_year)
        insufficient_window = observable_years < min_observable_years

        if not object_entries:
            return {
                "paper_id": paper_id,
                "pub_year": pub_year,
                "adoption_raw": 0.0,
                "adoption_raw_before_density": 0.0,
                "density_penalty": 1.0,
                "density_penalty_divisor": 1.0,
                "effective_concept_count": 0,
                "consistency": 0.0,
                "novelty_freq_source": novelty_freq_source,
                "consistency_freq_source": consistency_freq_source,
                "observable_years": observable_years,
                "insufficient_observable_window": insufficient_window,
                "insufficient_window_policy": insufficient_window_policy,
                "insufficient_window_factor": 1.0,
                "object_count": 0,
                "top_objects": [],
            }

        object_keys = list(object_entries.keys())
        series_map = freq_table.get_object_series_batch(object_keys)

        details = []
        for object_key, info in object_entries.items():
            series = series_map.get(object_key, {})
            if novelty_freq_source == "yearly":
                freq_at_pub = freq_table.get_yearly_freq_from_series(series, pub_year)
                freq_at_current = freq_table.get_yearly_freq_from_series(series, current_year)
            else:
                freq_at_pub = freq_table.get_cumulative_freq_from_series(series, pub_year)
                freq_at_current = freq_table.get_cumulative_freq_from_series(series, current_year)

            if consistency_freq_source == "cumulative":
                get_consistency_freq = lambda y: freq_table.get_cumulative_freq_from_series(series, y)
            else:
                get_consistency_freq = lambda y: freq_table.get_yearly_freq_from_series(series, y)

            if freq_at_current > freq_at_pub and freq_at_pub > 0.0:
                novelty_drop = math.log2(freq_at_current / freq_at_pub)
            else:
                novelty_drop = 0.0

            novelty_at_pub = max(0.0, -math.log2(max(freq_at_pub, 1e-12)))
            sigmoid_x = scarcity_sigmoid_alpha * (freq_at_pub - scarcity_sigmoid_threshold)
            sigmoid_x = max(-50.0, min(50.0, sigmoid_x))
            scarcity_sigmoid = 1.0 / (1.0 + math.exp(sigmoid_x))
            # Scarcity weight shrinks toward floor as publication-year frequency rises.
            scarcity_weight = scarcity_min_weight + (scarcity_max_weight - scarcity_min_weight) * scarcity_sigmoid
            # Keep legacy alias for compatibility with older analysis scripts.
            early_adopter_multiplier = scarcity_weight
            commonness_weight = 1.0

            mentions = max(int(info.get("mentions", 1)), 1)
            verb_weight = self._resolve_object_verb_weight(info)
            relevance_weight = 1.0 + concept_tf_weight * math.log1p(max(mentions - 1, 0))

            baseline_values = []
            baseline_start = pub_year - (consistency_baseline_window // 2)
            baseline_end = pub_year + (consistency_baseline_window // 2)
            for y in range(baseline_start, baseline_end + 1):
                if freq_table.get_total_papers(y) <= 0:
                    continue
                baseline_values.append(get_consistency_freq(y))
            positive_baseline_values = [x for x in baseline_values if x > 0.0]
            baseline_freq = float(np.median(positive_baseline_values)) if positive_baseline_values else 0.0
            baseline_guard_triggered = baseline_freq <= 0.0
            sustained_years = 0
            if observable_years > 0 and not baseline_guard_triggered:
                for y in range(pub_year + 1, current_year + 1):
                    consistency_freq = get_consistency_freq(y)
                    if consistency_freq >= baseline_freq:
                        sustained_years += 1

            if observable_years > 0 and not baseline_guard_triggered:
                raw_consistency = sustained_years / observable_years
                prior_ratio = observable_years / (observable_years + consistency_prior_observable_scale)
                effective_prior_strength = consistency_prior_strength * prior_ratio
                consistency = (sustained_years + effective_prior_strength * consistency_prior_mean) / (
                    observable_years + effective_prior_strength
                )
            else:
                raw_consistency = 0.0
                consistency = 0.0
            concept_consistency_gate = min(consistency / consistency_threshold, 1.0)

            retention_ratio = 0.0
            if observable_years > 0 and freq_at_pub > 0:
                retention_ratio = min(freq_at_current / freq_at_pub, 1.0)
            stability_bonus = 0.0
            growth_component = novelty_drop * scarcity_weight
            if (
                observable_years > 0
                and not baseline_guard_triggered
                and retention_ratio > stability_floor_ratio
                and stability_floor_ratio < 1.0
            ):
                if stability_requires_growth and novelty_drop <= 0.0:
                    pass
                else:
                    retention_lift = (retention_ratio - stability_floor_ratio) / (1.0 - stability_floor_ratio)
                    growth_signal = max(novelty_drop, 0.0)
                    if growth_signal > 0.0:
                        growth_scale = growth_signal ** stability_bonus_growth_power
                        raw_stability_bonus = stability_bonus_weight * growth_scale * retention_lift
                        growth_cap = abs(growth_component) * stability_bonus_max_ratio
                        if growth_cap > 0.0:
                            stability_bonus = min(raw_stability_bonus, growth_cap)
                        else:
                            stability_bonus = raw_stability_bonus

            contribution = verb_weight * relevance_weight * (
                (growth_component + stability_bonus) * concept_consistency_gate
            )

            details.append(
                {
                    "object_core": object_key,
                    "task_core": info["task_core"],
                    "verb_weight": round(verb_weight, 6),
                    "verb_weight_max": round(float(info.get("verb_weight_max", info.get("verb_weight", 0.0))), 6),
                    "verb_weight_mean": round(
                        float(info.get("verb_weight_sum", info.get("verb_weight", 0.0)))
                        / max(int(info.get("verb_weight_count", 1)), 1),
                        6,
                    ),
                    "mentions": mentions,
                    "relevance_weight": round(relevance_weight, 6),
                    "freq_at_pub": round(freq_at_pub, 12),
                    "freq_at_current": round(freq_at_current, 12),
                    "novelty_freq_source": novelty_freq_source,
                    "consistency_freq_source": consistency_freq_source,
                    "novelty_at_pub": round(novelty_at_pub, 6),
                    "novelty_drop": round(novelty_drop, 6),
                    "scarcity_sigmoid": round(scarcity_sigmoid, 6),
                    "scarcity_weight": round(scarcity_weight, 6),
                    "early_adopter_multiplier": round(early_adopter_multiplier, 6),
                    "commonness_weight": round(commonness_weight, 6),
                    "growth_component": round(growth_component, 6),
                    "stability_bonus": round(stability_bonus, 6),
                    "concept_consistency_gate": round(concept_consistency_gate, 6),
                    "contribution": round(contribution, 6),
                    "baseline_freq": round(baseline_freq, 12),
                    "baseline_guard_triggered": bool(baseline_guard_triggered),
                    "sustained_years": sustained_years,
                    "raw_consistency": round(raw_consistency, 6),
                    "consistency": round(consistency, 6),
                }
            )

        details.sort(key=lambda x: x["contribution"], reverse=True)
        top_objects = details[:top_k]
        adoption_raw_before_density = sum(x["contribution"] for x in top_objects)

        effective_concept_count = sum(1 for x in details if x["contribution"] > 0.0)
        if effective_concept_count <= 0:
            effective_concept_count = len(object_entries)

        if density_scope == "top_k_capped":
            density_count = min(max(effective_concept_count, 1), max(top_k, 1))
        else:
            density_count = max(effective_concept_count, 1)

        density_penalty_divisor = math.log2(max(float(density_count), float(density_penalty_floor_count)))
        density_penalty_factor = 1.0 / max(density_penalty_divisor, 1e-6)
        adoption_raw = adoption_raw_before_density * density_penalty_factor

        insufficient_window_factor = 1.0
        if insufficient_window:
            if insufficient_window_policy == "filter":
                insufficient_window_factor = 0.0
            elif insufficient_window_policy == "downweight":
                insufficient_window_factor = insufficient_window_downweight
        adoption_raw *= insufficient_window_factor

        top_consistency = [float(x.get("consistency", 0.0)) for x in top_objects]
        consistency = sum(top_consistency) / len(top_consistency) if top_consistency else 0.0

        return {
            "paper_id": paper_id,
            "pub_year": pub_year,
            "adoption_raw": round(adoption_raw, 6),
            "adoption_raw_before_density": round(adoption_raw_before_density, 6),
            "density_penalty": round(density_penalty_factor, 6),
            "density_penalty_divisor": round(density_penalty_divisor, 6),
            "effective_concept_count": int(effective_concept_count),
            "density_scope": density_scope,
            "consistency": round(consistency, 6),
            "novelty_freq_source": novelty_freq_source,
            "consistency_freq_source": consistency_freq_source,
            "observable_years": observable_years,
            "insufficient_observable_window": insufficient_window,
            "insufficient_window_policy": insufficient_window_policy,
            "insufficient_window_factor": round(insufficient_window_factor, 3),
            "object_count": len(object_entries),
            "top_objects": top_objects,
        }

    def _load_concept_year_seed_map(self, year: int) -> Dict[str, float]:
        seed_prefix = str(self.config.get("concept_year_seed_prefix", "innovation_v2")).strip() or "innovation_v2"
        seed_field = str(self.config.get("concept_year_seed_field", "s_peak")).strip() or "s_peak"
        innovation_dir = Path(self.config.get("innovation_output_dir", self.output_dir))
        path = innovation_dir / f"{seed_prefix}_{year}.jsonl"
        if not path.exists():
            logger.warning(
                "Pass 1 year %s: concept-year seed file not found, fallback to uniform attribution: %s",
                year,
                path,
            )
            return {}

        seed_map: Dict[str, float] = {}
        loaded = 0
        invalid = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    paper_id = str(rec.get("paper_id", "")).strip()
                    if not paper_id:
                        invalid += 1
                        continue
                    value = float(rec.get(seed_field, 0.0))
                    if not math.isfinite(value):
                        value = 0.0
                    seed_map[paper_id] = max(value, 0.0)
                    loaded += 1
                except Exception:
                    invalid += 1

        logger.info(
            "Pass 1 year %s: loaded concept-year seeds %s (field=%s, invalid=%s).",
            year,
            f"{loaded:,}",
            seed_field,
            f"{invalid:,}",
        )
        return seed_map

    @staticmethod
    def _accumulate_concept_year_stats(
        rec: dict,
        seed_value: float,
        concept_year_stats: Dict[str, Dict[str, float]],
    ) -> None:
        if not rec:
            return
        top_objects = rec.get("top_objects", [])
        if not isinstance(top_objects, list):
            return

        seed = max(float(seed_value), 0.0)
        seen = set()
        for obj in top_objects:
            if not isinstance(obj, dict):
                continue
            object_core = str(obj.get("object_core", "")).strip()
            if not object_core or object_core in seen:
                continue
            seen.add(object_core)

            stat = concept_year_stats.get(object_core)
            if stat is None:
                stat = {"paper_count": 0.0, "seed_sum": 0.0, "seed_max": 0.0}
                concept_year_stats[object_core] = stat
            stat["paper_count"] += 1.0
            stat["seed_sum"] += seed
            if seed > stat["seed_max"]:
                stat["seed_max"] = seed

    @staticmethod
    def _resolve_concept_year_role(
        *,
        group_size: int,
        relative_to_peak: float,
        relative_share: float,
        uniform_share: float,
        leader_threshold: float,
        co_leader_threshold: float,
    ) -> str:
        if group_size <= 1:
            return "solo"
        if relative_to_peak >= leader_threshold or relative_share >= max(uniform_share * 2.0, 0.5):
            return "leader"
        if relative_to_peak >= co_leader_threshold or relative_share >= uniform_share:
            return "co_leader"
        return "follower"

    def _apply_concept_year_attribution(
        self,
        *,
        year: int,
        input_path: Path,
        output_path: Path,
        concept_year_stats: Dict[str, Dict[str, float]],
    ) -> None:
        seed_field = str(self.config.get("concept_year_seed_field", "s_peak")).strip() or "s_peak"
        seed_power = max(float(self.config.get("concept_year_seed_power", 1.0)), 1e-6)
        weight_floor = max(0.0, min(float(self.config.get("concept_year_weight_floor", 0.0)), 0.95))
        leader_threshold = max(float(self.config.get("concept_year_leader_relative_threshold", 0.8)), 0.0)
        co_leader_threshold = max(
            float(self.config.get("concept_year_co_leader_relative_threshold", 0.4)),
            0.0,
        )
        if co_leader_threshold > leader_threshold:
            co_leader_threshold = leader_threshold

        processed = 0
        with open(input_path, "r", encoding="utf-8") as fin, open(output_path, "w", encoding="utf-8") as fout:
            for line in fin:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                base_adoption_raw = float(rec.get("adoption_raw", 0.0))
                base_adoption_before_density = float(rec.get("adoption_raw_before_density", 0.0))
                seed_value = max(float(rec.get("concept_year_attribution_seed", 0.0)), 0.0)

                rec["concept_year_attribution_enabled"] = True
                rec["concept_year_attribution_seed_field"] = seed_field
                rec["adoption_raw_without_concept_year"] = round(base_adoption_raw, 6)
                rec["adoption_raw_before_density_without_concept_year"] = round(base_adoption_before_density, 6)

                role_counts = {"solo": 0, "leader": 0, "co_leader": 0, "follower": 0}
                adjusted_top_objects = []
                for obj in rec.get("top_objects", []) or []:
                    if not isinstance(obj, dict):
                        continue
                    object_core = str(obj.get("object_core", "")).strip()
                    stat = concept_year_stats.get(object_core, {"paper_count": 1.0, "seed_sum": 0.0, "seed_max": 0.0})
                    group_size = max(int(stat.get("paper_count", 1.0)), 1)
                    seed_sum = max(float(stat.get("seed_sum", 0.0)), 0.0)
                    seed_max = max(float(stat.get("seed_max", 0.0)), 0.0)

                    if seed_sum > 1e-12:
                        relative_share = min(max(seed_value / seed_sum, 0.0), 1.0)
                    else:
                        relative_share = 1.0 / group_size
                    weighted_share = min(max(relative_share ** seed_power, 0.0), 1.0)
                    attribution_weight = weight_floor + (1.0 - weight_floor) * weighted_share
                    attribution_weight = min(max(attribution_weight, 0.0), 1.0)

                    relative_to_peak = seed_value / seed_max if seed_max > 1e-12 else 1.0
                    uniform_share = 1.0 / group_size
                    role = self._resolve_concept_year_role(
                        group_size=group_size,
                        relative_to_peak=relative_to_peak,
                        relative_share=relative_share,
                        uniform_share=uniform_share,
                        leader_threshold=leader_threshold,
                        co_leader_threshold=co_leader_threshold,
                    )
                    role_counts[role] = role_counts.get(role, 0) + 1

                    contribution_before = float(obj.get("contribution", 0.0))
                    contribution_after = contribution_before * attribution_weight

                    obj["contribution_before_concept_year"] = round(contribution_before, 6)
                    obj["contribution"] = round(contribution_after, 6)
                    obj["concept_year_group_size"] = group_size
                    obj["concept_year_seed_sum"] = round(seed_sum, 6)
                    obj["concept_year_relative_share"] = round(relative_share, 6)
                    obj["concept_year_relative_to_peak"] = round(relative_to_peak, 6)
                    obj["concept_year_attribution_weight"] = round(attribution_weight, 6)
                    obj["concept_year_role"] = role
                    adjusted_top_objects.append(obj)

                adjusted_top_objects.sort(key=lambda item: float(item.get("contribution", 0.0)), reverse=True)
                rec["top_objects"] = adjusted_top_objects
                rec["concept_year_role_counts"] = role_counts
                if not adjusted_top_objects:
                    rec["concept_year_role"] = "none"
                elif role_counts.get("leader", 0) > 0:
                    rec["concept_year_role"] = "leader"
                elif role_counts.get("co_leader", 0) > 0:
                    rec["concept_year_role"] = "co_leader"
                elif role_counts.get("solo", 0) > 0:
                    rec["concept_year_role"] = "solo"
                else:
                    rec["concept_year_role"] = "follower"

                adoption_before_density = sum(float(obj.get("contribution", 0.0)) for obj in adjusted_top_objects)
                rec["adoption_raw_before_density"] = round(adoption_before_density, 6)
                density_penalty = float(rec.get("density_penalty", 1.0))
                insufficient_factor = float(rec.get("insufficient_window_factor", 1.0))
                rec["adoption_raw"] = round(adoption_before_density * density_penalty * insufficient_factor, 6)

                top_consistency = [float(obj.get("consistency", 0.0)) for obj in adjusted_top_objects]
                rec["consistency"] = round(sum(top_consistency) / len(top_consistency), 6) if top_consistency else 0.0

                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                processed += 1

        logger.info(
            "Pass 1 year %s: concept-year attribution rewrite complete, records=%s, concepts=%s, output=%s",
            year,
            f"{processed:,}",
            f"{len(concept_year_stats):,}",
            output_path,
        )

    def run_pass1(self, years: List[int] = None, force: bool = False):
        logger.info("=" * 60)
        logger.info("Pass 1: calculate Adoption Magnitude + Consistency (V6)")
        logger.info("=" * 60)

        if not self._is_stats_db_compatible():
            raise RuntimeError("Frequency stats DB is missing or incompatible; run --pass 0 first.")

        years = years or list(self.config["years"])
        if not force:
            completed = set(self.checkpoint.get("pass1_years", []))
            years = [y for y in years if y not in completed]
        if not years:
            logger.info("Pass 1 has no pending years; skipping.")
            return
        self._assert_pass0_ready_for_years(years)

        self._write_progress_status(
            "pass1_running",
            {
                "phase": "pass1",
                "years_pending": sorted(years),
                "completed_years": sorted(self.checkpoint.get("pass1_years", [])),
            },
        )

        freq_table = FrequencyTable(
            stats_db_path=self.stats_db_path,
            vocab_size_estimate=self.config["vocab_size_estimate"],
            cache_max_objects=self.config["cache_max_objects"],
            yearly_freq_smoothing_mode=self.config.get("yearly_freq_smoothing_mode", "laplace_adaptive"),
            yearly_freq_smoothing_alpha=self.config.get("yearly_freq_smoothing_alpha", 1.0),
            yearly_freq_smoothing_vocab_size=self.config.get(
                "yearly_freq_smoothing_vocab_size",
                self.config["vocab_size_estimate"],
            ),
            yearly_freq_smoothing_vocab_scale=self.config.get("yearly_freq_smoothing_vocab_scale", 0.12),
            cumulative_freq_smoothing_mode=self.config.get("cumulative_freq_smoothing_mode", "laplace_adaptive"),
            cumulative_freq_smoothing_alpha=self.config.get("cumulative_freq_smoothing_alpha", 1.0),
            cumulative_freq_smoothing_vocab_size=self.config.get(
                "cumulative_freq_smoothing_vocab_size",
                self.config["vocab_size_estimate"],
            ),
            cumulative_freq_smoothing_vocab_scale=self.config.get("cumulative_freq_smoothing_vocab_scale", 0.12),
        )

        rpu_conn = sqlite3.connect(self.rpu_db_path)
        rpu_cur = rpu_conn.cursor()

        for year in sorted(years):
            task_doc_freq = freq_table.load_task_doc_freq_upto_year(year)
            total_docs_upto_year = max(freq_table.get_cumulative_total(year), 0)
            verb_weight_model = VerbWeightModel(
                task_doc_freq=task_doc_freq,
                total_docs=total_docs_upto_year,
                config_path=self.config["verb_weights_path"],
                strict_policy={
                    "enabled": self.config.get("strict_verb_policy_enabled", True),
                    "creative_weight": self.config.get("strict_creative_verb_weight", 1.0),
                    "usage_max_weight": self.config.get("strict_usage_verb_max_weight", 0.18),
                    "unknown_max_weight": self.config.get("strict_unknown_verb_max_weight", 0.6),
                    "creative_verbs": self.config.get("strict_creative_verbs", list(STRICT_CREATIVE_VERBS)),
                    "usage_verbs": self.config.get("strict_usage_verbs", list(STRICT_USAGE_VERBS)),
                    "tier_definitions": [
                        {
                            "name": "tier1_create",
                            "weight": self.config.get("verb_tier1_weight", 1.0),
                            "verbs": self.config.get("verb_tier1_verbs", []),
                        },
                        {
                            "name": "tier2_improve",
                            "weight": self.config.get("verb_tier2_weight", 0.6),
                            "verbs": self.config.get("verb_tier2_verbs", []),
                        },
                        {
                            "name": "tier3_use",
                            "weight": self.config.get("verb_tier3_weight", 0.2),
                            "verbs": self.config.get("verb_tier3_verbs", []),
                        },
                        {
                            "name": "tier4_analysis",
                            "weight": self.config.get("verb_tier4_weight", 0.1),
                            "verbs": self.config.get("verb_tier4_verbs", []),
                        },
                    ],
                },
            )
            year_start = datetime.now()
            year_target = self._count_year_papers(rpu_conn, year)
            logger.info("Pass 1 processing year %s, target papers=%s", year, f"{year_target:,}")
            pbar = self._create_progress_bar(year_target, f"Pass1 {year}")
            pbar_pending = 0

            concept_year_attribution_enabled = _as_bool(
                self.config.get("concept_year_attribution_enabled", False),
                False,
            )
            concept_year_seed_map: Dict[str, float] = {}
            concept_year_stats: Dict[str, Dict[str, float]] = {}
            if concept_year_attribution_enabled:
                concept_year_seed_map = self._load_concept_year_seed_map(year)

            output_path = self.output_dir / f"{self.config['signals_prefix']}_{year}.jsonl"
            temp_output_path = output_path
            if concept_year_attribution_enabled:
                temp_output_path = output_path.with_suffix(".tmp.jsonl")

            query, params = self._build_year_pass1_query(year)
            rpu_cur.execute(query, params)

            processed = 0
            current_paper_id = None
            current_pub_year = year
            object_entries: Dict[str, dict] = {}

            with open(temp_output_path, "w", encoding="utf-8") as fout:
                while True:
                    rows = rpu_cur.fetchmany(200000)
                    if not rows:
                        break

                    for row in rows:
                        paper_id, pub_year, task_core, task_lemma, task, object_core, object_lemma, object_raw, object_coverage = row
                        if paper_id != current_paper_id:
                            if current_paper_id is not None:
                                result = self._compute_paper_signals(
                                    paper_id=current_paper_id,
                                    pub_year=current_pub_year,
                                    object_entries=object_entries,
                                    freq_table=freq_table,
                                )
                                if concept_year_attribution_enabled:
                                    seed_value = max(float(concept_year_seed_map.get(current_paper_id, 0.0)), 0.0)
                                    result["concept_year_attribution_seed"] = round(seed_value, 6)
                                    self._accumulate_concept_year_stats(result, seed_value, concept_year_stats)
                                fout.write(json.dumps(result, ensure_ascii=False) + "\n")
                                processed += 1
                                pbar_pending += 1
                                if pbar_pending >= 2000:
                                    self._update_progress_bar(pbar, pbar_pending)
                                    elapsed = (datetime.now() - year_start).total_seconds()
                                    rate = processed / elapsed if elapsed > 0 else 0
                                    if pbar is not None:
                                        pbar.set_postfix_str(
                                            f"rate={rate:.0f}/s y={processed:,}/{year_target:,}",
                                            refresh=False,
                                        )
                                    pbar_pending = 0
                                if processed % 100000 == 0:
                                    elapsed = (datetime.now() - year_start).total_seconds()
                                    rate = processed / elapsed if elapsed > 0 else 0
                                    self._write_progress_status(
                                        "pass1_running",
                                        {
                                            "phase": "pass1",
                                            "year": year,
                                            "year_target": year_target,
                                            "year_processed": processed,
                                            "papers_per_sec": round(rate, 2),
                                            "years_pending": sorted(years),
                                            "completed_years": sorted(self.checkpoint.get("pass1_years", [])),
                                        },
                                    )

                            current_paper_id = paper_id
                            current_pub_year = int(pub_year) if pub_year is not None else year
                            object_entries = {}

                        object_key = resolve_object_concept(
                            object_core=object_core or "",
                            object_lemma=object_lemma or "",
                            object_raw=object_raw or "",
                            object_coverage=_safe_float(object_coverage, 0.0),
                            min_core_coverage=self.config["min_core_coverage"],
                            use_unified_concept_representation=self.config.get(
                                "use_unified_concept_representation", True
                            ),
                            fallback_anchor_shortcut_enabled=self.config.get(
                                "fallback_anchor_shortcut_enabled", True
                            ),
                            fallback_anchor_shortcut_max_tokens=self.config.get(
                                "fallback_anchor_shortcut_max_tokens", 2
                            ),
                            object_long_concept_max_tokens=self.config.get("object_long_concept_max_tokens", 8),
                            object_long_concept_truncate_mode=self.config.get(
                                "object_long_concept_truncate_mode",
                                "head_tail",
                            ),
                        )
                        if not object_key:
                            continue

                        task_key = resolve_task_key(task_core or "", task_lemma or "", task or "")
                        verb_weight = verb_weight_model.get_weight(task_key)

                        prev = object_entries.get(object_key)
                        if prev is None:
                            object_entries[object_key] = {
                                "task_core": task_key,
                                "verb_weight": verb_weight,
                                "verb_weight_max": verb_weight,
                                "verb_weight_sum": verb_weight,
                                "verb_weight_count": 1,
                                "mentions": 1,
                            }
                        else:
                            prev["mentions"] = int(prev.get("mentions", 1)) + 1
                            prev["verb_weight_sum"] = float(prev.get("verb_weight_sum", 0.0)) + verb_weight
                            prev["verb_weight_count"] = int(prev.get("verb_weight_count", 1)) + 1
                            if verb_weight > prev.get("verb_weight_max", prev.get("verb_weight", 0.0)):
                                prev["task_core"] = task_key
                                prev["verb_weight_max"] = verb_weight
                                prev["verb_weight"] = verb_weight

                if current_paper_id is not None:
                    result = self._compute_paper_signals(
                        paper_id=current_paper_id,
                        pub_year=current_pub_year,
                        object_entries=object_entries,
                        freq_table=freq_table,
                    )
                    if concept_year_attribution_enabled:
                        seed_value = max(float(concept_year_seed_map.get(current_paper_id, 0.0)), 0.0)
                        result["concept_year_attribution_seed"] = round(seed_value, 6)
                        self._accumulate_concept_year_stats(result, seed_value, concept_year_stats)
                    fout.write(json.dumps(result, ensure_ascii=False) + "\n")
                    processed += 1
                    pbar_pending += 1

            if concept_year_attribution_enabled:
                self._apply_concept_year_attribution(
                    year=year,
                    input_path=temp_output_path,
                    output_path=output_path,
                    concept_year_stats=concept_year_stats,
                )
                try:
                    temp_output_path.unlink()
                except Exception:
                    pass

            self._update_progress_bar(pbar, pbar_pending)
            if pbar is not None:
                pbar.close()

            if "pass1_years" not in self.checkpoint:
                self.checkpoint["pass1_years"] = []
            if year not in self.checkpoint["pass1_years"]:
                self.checkpoint["pass1_years"].append(year)
            self._save_checkpoint()

            elapsed = (datetime.now() - year_start).total_seconds()
            logger.info(
                "Pass 1 year %s completed: papers=%s, %.1fs, %.0f papers/s",
                year,
                f"{processed:,}",
                elapsed,
                processed / elapsed if elapsed > 0 else 0,
            )
            self._write_progress_status(
                "pass1_running",
                {
                    "phase": "pass1",
                    "year": year,
                    "year_target": year_target,
                    "year_processed": processed,
                    "completed_years": sorted(self.checkpoint.get("pass1_years", [])),
                },
            )

        rpu_conn.close()
        freq_table.close()
        self._write_progress_status(
            "pass1_complete",
            {
                "phase": "pass1",
                "completed_years": sorted(self.checkpoint.get("pass1_years", [])),
            },
        )

    def _load_titles_for_year(self, year: int) -> Dict[str, str]:
        # Pass2 paper-type detection must see the original title text for every
        # record that reached signals output. Do not apply correction filtering
        # here, otherwise erratum-like titles become empty and are mislabeled as
        # `original`, which breaks paper_type_weight down-weighting.
        conn = sqlite3.connect(self.rpu_db_path)
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT p.paper_id, COALESCE(p.title, '')
            FROM papers p
            WHERE p.pub_year = ?
            """,
            (year,),
        ).fetchall()
        conn.close()
        return {paper_id: title for paper_id, title in rows}

    @staticmethod
    def _read_adoption_values(path: Path) -> np.ndarray:
        values = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    values.append(float(rec.get("adoption_raw", 0.0)))
                except Exception:
                    continue
        if not values:
            return np.array([], dtype=np.float64)
        arr = np.asarray(values, dtype=np.float64)
        arr.sort()
        return arr

    def _compute_foundation_utility_raw(self, rec: dict) -> float:
        if not isinstance(rec, dict):
            return 0.0

        top_objects = rec.get("top_objects", [])
        if not isinstance(top_objects, list):
            top_objects = []
        object_count = max(int(rec.get("object_count", 0)), 0)
        object_count_cap = max(int(self.config.get("foundation_utility_object_count_cap", 8)), 1)
        guard_penalty = max(
            0.0,
            min(float(self.config.get("foundation_utility_baseline_guard_penalty", 0.5)), 1.0),
        )

        if not top_objects:
            return math.log1p(min(object_count, object_count_cap))

        components = []
        for obj in top_objects:
            if not isinstance(obj, dict):
                continue
            consistency = max(0.0, min(float(obj.get("consistency", 0.0)), 1.0))
            mentions = max(float(obj.get("mentions", 1.0)), 1.0)
            mention_support = math.log1p(mentions)
            baseline_guard_triggered = bool(obj.get("baseline_guard_triggered", False))
            baseline_factor = guard_penalty if baseline_guard_triggered else 1.0
            components.append(consistency * mention_support * baseline_factor)

        if not components:
            return math.log1p(min(object_count, object_count_cap))

        breadth = math.log1p(min(object_count, object_count_cap))
        return max(0.0, (sum(components) / len(components)) * max(breadth, 1e-6))

    def _read_foundation_utility_values(self, path: Path) -> np.ndarray:
        values = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    values.append(float(self._compute_foundation_utility_raw(rec)))
                except Exception:
                    continue
        if not values:
            return np.array([], dtype=np.float64)
        arr = np.asarray(values, dtype=np.float64)
        arr.sort()
        return arr

    def _get_transfer_verb_forms(self) -> Tuple[set[str], set[str]]:
        cached = getattr(self, "_method_transfer_verb_forms_cache", None)
        if cached is not None:
            return cached

        usage_forms: set[str] = set()
        creative_forms: set[str] = set()

        for verb in self.config.get("strict_usage_verbs", list(STRICT_USAGE_VERBS)):
            token = normalize_task_token(str(verb or ""))
            if not token:
                continue
            usage_forms.add(token)
            for form in VerbWeightModel._generate_verb_forms(token):
                norm = normalize_task_token(form)
                if norm:
                    usage_forms.add(norm)

        for verb in self.config.get("strict_creative_verbs", list(STRICT_CREATIVE_VERBS)):
            token = normalize_task_token(str(verb or ""))
            if not token:
                continue
            creative_forms.add(token)
            for form in VerbWeightModel._generate_verb_forms(token):
                norm = normalize_task_token(form)
                if norm:
                    creative_forms.add(norm)

        cached = (usage_forms, creative_forms)
        setattr(self, "_method_transfer_verb_forms_cache", cached)
        return cached

    def _compute_method_transferability_raw(self, rec: dict) -> float:
        if not isinstance(rec, dict):
            return 0.0

        top_objects = rec.get("top_objects", [])
        if not isinstance(top_objects, list):
            top_objects = []
        if not top_objects:
            return 0.0

        object_count = max(int(rec.get("object_count", 0)), 0)
        object_count_cap = max(int(self.config.get("method_transferability_object_count_cap", 8)), 1)
        task_diversity_weight = max(float(self.config.get("method_transferability_task_diversity_weight", 0.5)), 0.0)
        object_diversity_weight = max(float(self.config.get("method_transferability_object_diversity_weight", 0.5)), 0.0)
        diversity_den = task_diversity_weight + object_diversity_weight
        if diversity_den <= 1e-12:
            task_diversity_weight = 0.5
            object_diversity_weight = 0.5
            diversity_den = 1.0
        usage_boost = max(min(float(self.config.get("method_transferability_usage_verb_boost", 0.1)), 1.0), -0.5)
        creative_weight = max(min(float(self.config.get("method_transferability_creative_verb_weight", 0.85)), 1.5), 0.0)

        usage_forms, creative_forms = self._get_transfer_verb_forms()

        task_set = set()
        object_set = set()
        consistencies = []
        mention_scores = []
        verb_factors = []

        for obj in top_objects:
            if not isinstance(obj, dict):
                continue
            task_token = normalize_task_token(str(obj.get("task_core", "")))
            object_token = str(obj.get("object_core", "")).strip()
            consistency = max(0.0, min(float(obj.get("consistency", 0.0)), 1.0))
            mentions = max(float(obj.get("mentions", 1.0)), 1.0)
            mention_score = math.log1p(mentions)

            if task_token:
                task_set.add(task_token)
            if object_token:
                object_set.add(object_token)
            consistencies.append(consistency)
            mention_scores.append(mention_score)

            if task_token in usage_forms:
                verb_factor = 1.0 + usage_boost
            elif task_token in creative_forms:
                verb_factor = creative_weight
            else:
                verb_factor = 1.0
            verb_factors.append(max(0.0, verb_factor))

        if not consistencies:
            return 0.0

        valid_n = len(consistencies)
        task_diversity = len(task_set) / max(valid_n, 1)
        object_diversity_base = max(1, min(object_count, valid_n))
        object_diversity = len(object_set) / object_diversity_base
        diversity_component = (
            task_diversity_weight * task_diversity + object_diversity_weight * object_diversity
        ) / diversity_den

        consistency_component = sum(consistencies) / valid_n
        mention_component = sum(mention_scores) / valid_n
        verb_component = sum(verb_factors) / valid_n
        breadth_component = math.log1p(min(object_count, object_count_cap))

        return max(
            0.0,
            breadth_component * diversity_component * consistency_component * mention_component * verb_component,
        )

    def _read_method_transferability_values(self, path: Path) -> np.ndarray:
        values = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    values.append(float(self._compute_method_transferability_raw(rec)))
                except Exception:
                    continue
        if not values:
            return np.array([], dtype=np.float64)
        arr = np.asarray(values, dtype=np.float64)
        arr.sort()
        return arr

    @staticmethod
    def _percentile_rank(sorted_values: np.ndarray, value: float, method: str = "mid") -> float:
        n = int(len(sorted_values))
        if n <= 0:
            return 0.0
        side = str(method or "mid").strip().lower()
        left = float(np.searchsorted(sorted_values, value, side="left"))
        right = float(np.searchsorted(sorted_values, value, side="right"))
        if side == "right":
            rank = right
        elif side == "left":
            rank = left
        else:
            rank = 0.5 * (left + right)
        return max(0.0, min(100.0, (rank / n) * 100.0))

    def _collect_global_stats_with_progress(
        self,
        paths: List[Path],
        value_extractor,
        progress_desc: str,
    ) -> Dict[str, float]:
        count = 0
        mean = 0.0
        m2 = 0.0
        rows_seen = 0
        files_seen = 0
        started_at = time.time()
        last_heartbeat = started_at
        pbar = self._create_progress_bar(None, progress_desc, unit="row", leave=False)
        pbar_pending = 0
        logger.info("%s: start pre-scan over %s files", progress_desc, len(paths))
        try:
            for file_index, path in enumerate(paths, start=1):
                if not path.exists():
                    logger.warning(
                        "%s: missing file skipped (%s/%s): %s",
                        progress_desc,
                        file_index,
                        len(paths),
                        path,
                    )
                    continue
                files_seen += 1
                logger.info(
                    "%s: scanning file %s/%s: %s",
                    progress_desc,
                    file_index,
                    len(paths),
                    path.name,
                )
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        rows_seen += 1
                        pbar_pending += 1
                        if pbar_pending >= 2000:
                            self._update_progress_bar(pbar, pbar_pending)
                            if pbar is not None:
                                pbar.set_postfix_str(f"valid={count:,}", refresh=False)
                            pbar_pending = 0

                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                            raw_value = float(value_extractor(rec))
                        except Exception:
                            continue
                        if not math.isfinite(raw_value):
                            continue
                        x = math.log1p(max(raw_value, 0.0))
                        count += 1
                        delta = x - mean
                        mean += delta / count
                        m2 += delta * (x - mean)

                        now = time.time()
                        if now - last_heartbeat >= 20.0:
                            logger.info(
                                "%s heartbeat: files=%s/%s rows=%s valid=%s elapsed=%.1fs",
                                progress_desc,
                                files_seen,
                                len(paths),
                                f"{rows_seen:,}",
                                f"{count:,}",
                                now - started_at,
                            )
                            last_heartbeat = now
        finally:
            self._update_progress_bar(pbar, pbar_pending)
            if pbar is not None:
                pbar.close()

        logger.info(
            "%s: done files=%s/%s rows=%s valid=%s elapsed=%.1fs",
            progress_desc,
            files_seen,
            len(paths),
            f"{rows_seen:,}",
            f"{count:,}",
            time.time() - started_at,
        )

        if count <= 1:
            return {"count": count, "mean": mean, "std": 0.0}
        variance = max(m2 / (count - 1), 0.0)
        return {"count": count, "mean": mean, "std": math.sqrt(variance)}

    def _collect_adoption_global_stats(self, paths: List[Path]) -> Dict[str, float]:
        return self._collect_global_stats_with_progress(
            paths=paths,
            value_extractor=lambda rec: rec.get("adoption_raw", 0.0),
            progress_desc="Pass2 pre-scan adoption",
        )

    def _collect_foundation_global_stats(self, paths: List[Path]) -> Dict[str, float]:
        return self._collect_global_stats_with_progress(
            paths=paths,
            value_extractor=self._compute_foundation_utility_raw,
            progress_desc="Pass2 pre-scan foundation_utility",
        )

    def _collect_method_global_stats(self, paths: List[Path]) -> Dict[str, float]:
        return self._collect_global_stats_with_progress(
            paths=paths,
            value_extractor=self._compute_method_transferability_raw,
            progress_desc="Pass2 pre-scan method_transferability",
        )

    def _load_summary_stats_map(self) -> Dict[int, dict]:
        if not self.summary_path.exists():
            return {}
        try:
            with open(self.summary_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return {}
            result: Dict[int, dict] = {}
            for item in data:
                if not isinstance(item, dict):
                    continue
                year = item.get("year")
                if year is None:
                    continue
                result[int(year)] = item
            return result
        except Exception:
            return {}


    def run_pass2(self, years: List[int] = None, force: bool = False):
        logger.info("=" * 60)
        logger.info("Pass 2: normalization + gating + final output (V6)")
        logger.info("=" * 60)

        years = years or list(self.config["years"])
        if not force:
            completed = set(self.checkpoint.get("pass2_years", []))
            years = [y for y in years if y not in completed]
        if not years:
            logger.info("Pass 2 has no pending years; skipping.")
            return

        self._write_progress_status(
            "pass2_running",
            {
                "phase": "pass2",
                "years_pending": sorted(years),
                "completed_years": sorted(self.checkpoint.get("pass2_years", [])),
            },
        )

        threshold = self.config["consistency_threshold"]
        legacy_global_gate = _as_bool(self.config.get("use_global_consistency_gate", False), False)
        global_consistency_gate_mode = str(self.config.get("global_consistency_gate_mode", "")).strip().lower()
        if not global_consistency_gate_mode:
            global_consistency_gate_mode = "legacy_ratio" if legacy_global_gate else "off"
        if global_consistency_gate_mode in {"on", "enabled"}:
            global_consistency_gate_mode = "legacy_ratio"
        if global_consistency_gate_mode not in {"off", "legacy_ratio", "residual_soft"}:
            global_consistency_gate_mode = "off"
        global_consistency_gate_floor = max(
            0.0,
            min(float(self.config.get("global_consistency_gate_floor", 0.8)), 1.0),
        )
        adoption_norm_mode = str(self.config.get("adoption_norm_mode", "global_zscore")).strip().lower()
        if adoption_norm_mode not in {"yearly_percentile", "global_zscore"}:
            adoption_norm_mode = "global_zscore"
        adoption_rank_method = str(self.config.get("adoption_rank_method", "mid")).strip().lower()
        if adoption_rank_method not in {"left", "right", "mid"}:
            adoption_rank_method = "mid"
        adoption_global_reference_scope = str(
            self.config.get("adoption_global_reference_scope", "configured_years")
        ).strip().lower()
        if adoption_global_reference_scope not in {"configured_years", "run_years"}:
            adoption_global_reference_scope = "configured_years"
        adoption_global_zscore_scale = max(float(self.config.get("adoption_global_zscore_scale", 1.0)), 1e-6)
        foundation_utility_enabled = _as_bool(self.config.get("foundation_utility_enabled", True), True)
        foundation_utility_norm_mode = str(
            self.config.get("foundation_utility_norm_mode", "yearly_percentile")
        ).strip().lower()
        if foundation_utility_norm_mode not in {"yearly_percentile", "global_zscore"}:
            foundation_utility_norm_mode = "yearly_percentile"
        foundation_utility_global_reference_scope = str(
            self.config.get("foundation_utility_global_reference_scope", "configured_years")
        ).strip().lower()
        if foundation_utility_global_reference_scope not in {"configured_years", "run_years"}:
            foundation_utility_global_reference_scope = "configured_years"
        foundation_utility_global_zscore_scale = max(
            float(self.config.get("foundation_utility_global_zscore_scale", 1.0)),
            1e-6,
        )
        method_transferability_enabled = _as_bool(self.config.get("method_transferability_enabled", True), True)
        method_transferability_norm_mode = str(
            self.config.get("method_transferability_norm_mode", "yearly_percentile")
        ).strip().lower()
        if method_transferability_norm_mode not in {"yearly_percentile", "global_zscore"}:
            method_transferability_norm_mode = "yearly_percentile"
        method_transferability_global_reference_scope = str(
            self.config.get("method_transferability_global_reference_scope", "configured_years")
        ).strip().lower()
        if method_transferability_global_reference_scope not in {"configured_years", "run_years"}:
            method_transferability_global_reference_scope = "configured_years"
        method_transferability_global_zscore_scale = max(
            float(self.config.get("method_transferability_global_zscore_scale", 1.0)),
            1e-6,
        )

        global_adoption_stats = None
        if adoption_norm_mode == "global_zscore":
            if adoption_global_reference_scope == "run_years":
                reference_years = sorted(set(int(y) for y in years))
            else:
                reference_years = sorted({int(y) for y in self.config.get("years", years)})
            reference_paths = [
                self.output_dir / f"{self.config['signals_prefix']}_{year}.jsonl"
                for year in reference_years
            ]
            global_adoption_stats = self._collect_adoption_global_stats(reference_paths)
            if (
                global_adoption_stats.get("count", 0) <= 1
                or global_adoption_stats.get("std", 0.0) <= 1e-12
            ):
                logger.warning(
                    "Pass 2: global_zscore reference distribution is insufficient (count=%s, std=%.6g); fallback to yearly_percentile.",
                    global_adoption_stats.get("count", 0),
                    global_adoption_stats.get("std", 0.0),
                )
                adoption_norm_mode = "yearly_percentile"

        global_foundation_stats = None
        if foundation_utility_enabled and foundation_utility_norm_mode == "global_zscore":
            if foundation_utility_global_reference_scope == "run_years":
                foundation_reference_years = sorted(set(int(y) for y in years))
            else:
                foundation_reference_years = sorted({int(y) for y in self.config.get("years", years)})
            foundation_reference_paths = [
                self.output_dir / f"{self.config['signals_prefix']}_{year}.jsonl"
                for year in foundation_reference_years
            ]
            global_foundation_stats = self._collect_foundation_global_stats(foundation_reference_paths)
            if (
                global_foundation_stats.get("count", 0) <= 1
                or global_foundation_stats.get("std", 0.0) <= 1e-12
            ):
                logger.warning(
                    "Pass 2: foundation_utility global_zscore reference is insufficient (count=%s, std=%.6g); fallback to yearly_percentile.",
                    global_foundation_stats.get("count", 0),
                    global_foundation_stats.get("std", 0.0),
                )
                foundation_utility_norm_mode = "yearly_percentile"

        global_method_stats = None
        if method_transferability_enabled and method_transferability_norm_mode == "global_zscore":
            if method_transferability_global_reference_scope == "run_years":
                method_reference_years = sorted(set(int(y) for y in years))
            else:
                method_reference_years = sorted({int(y) for y in self.config.get("years", years)})
            method_reference_paths = [
                self.output_dir / f"{self.config['signals_prefix']}_{year}.jsonl"
                for year in method_reference_years
            ]
            global_method_stats = self._collect_method_global_stats(method_reference_paths)
            if (
                global_method_stats.get("count", 0) <= 1
                or global_method_stats.get("std", 0.0) <= 1e-12
            ):
                logger.warning(
                    "Pass 2: method_transferability global_zscore reference is insufficient (count=%s, std=%.6g); fallback to yearly_percentile.",
                    global_method_stats.get("count", 0),
                    global_method_stats.get("std", 0.0),
                )
                method_transferability_norm_mode = "yearly_percentile"

        post_processor = PaperTypePostProcessor()
        summary_stats = []

        for year in sorted(years):
            signals_path = self.output_dir / f"{self.config['signals_prefix']}_{year}.jsonl"
            if not signals_path.exists():
                logger.warning("Pass 2 skipping year %s: signals file not found %s", year, signals_path)
                continue

            logger.info("Pass 2 processing year %s", year)
            sorted_values = self._read_adoption_values(signals_path)
            n = len(sorted_values)
            if n == 0:
                logger.warning("  year %s has no valid records, skipping", year)
                continue
            foundation_sorted_values = np.array([], dtype=np.float64)
            if foundation_utility_enabled and foundation_utility_norm_mode == "yearly_percentile":
                foundation_sorted_values = self._read_foundation_utility_values(signals_path)
                if len(foundation_sorted_values) == 0:
                    logger.warning("  year %s foundation_utility has empty raw values; norm falls back to 0.", year)
            method_sorted_values = np.array([], dtype=np.float64)
            if method_transferability_enabled and method_transferability_norm_mode == "yearly_percentile":
                method_sorted_values = self._read_method_transferability_values(signals_path)
                if len(method_sorted_values) == 0:
                    logger.warning("  year %s method_transferability has empty raw values; norm falls back to 0.", year)

            title_map = self._load_titles_for_year(year)
            output_path = self.output_dir / f"{self.config['final_prefix']}_{year}.jsonl"
            pbar = self._create_progress_bar(n, f"Pass2 {year}")
            pbar_pending = 0

            impact_scores = []
            adoption_norms = []
            foundation_norms = []
            foundation_raws = []
            method_norms = []
            method_raws = []

            with open(signals_path, "r", encoding="utf-8") as fin, open(output_path, "w", encoding="utf-8") as fout:
                processed = 0
                for line in fin:
                    line = line.strip()
                    if not line:
                        continue

                    rec = json.loads(line)
                    adoption_raw = float(rec.get("adoption_raw", 0.0))
                    consistency = float(rec.get("consistency", 0.0))

                    if adoption_norm_mode == "global_zscore" and global_adoption_stats is not None:
                        mean = float(global_adoption_stats.get("mean", 0.0))
                        std = max(float(global_adoption_stats.get("std", 0.0)), 1e-12)
                        z = (math.log1p(max(adoption_raw, 0.0)) - mean) / std
                        z_scaled = max(min(z / adoption_global_zscore_scale, 50.0), -50.0)
                        adoption_norm_unweighted = 100.0 / (1.0 + math.exp(-z_scaled))
                    else:
                        adoption_norm_unweighted = self._percentile_rank(
                            sorted_values=sorted_values,
                            value=adoption_raw,
                            method=adoption_rank_method,
                        )

                    if global_consistency_gate_mode == "legacy_ratio":
                        consistency_gate = min(consistency / threshold, 1.0) if threshold > 0 else 1.0
                    elif global_consistency_gate_mode == "residual_soft":
                        ratio = min(consistency / threshold, 1.0) if threshold > 0 else 1.0
                        consistency_gate = global_consistency_gate_floor + (1.0 - global_consistency_gate_floor) * ratio
                    else:
                        consistency_gate = 1.0
                    impact_score_unweighted = adoption_norm_unweighted * consistency_gate

                    title = title_map.get(rec["paper_id"], "")
                    paper_type, paper_type_weight = post_processor.detect_paper_type(title)

                    adoption_norm = adoption_norm_unweighted * paper_type_weight
                    impact_score = impact_score_unweighted * paper_type_weight
                    diffusion_norm_unweighted = adoption_norm_unweighted
                    diffusion_norm = adoption_norm
                    diffusion_impact_unweighted = impact_score_unweighted
                    diffusion_impact = impact_score
                    foundation_utility_raw = self._compute_foundation_utility_raw(rec) if foundation_utility_enabled else 0.0
                    if foundation_utility_enabled:
                        if (
                            foundation_utility_norm_mode == "global_zscore"
                            and global_foundation_stats is not None
                        ):
                            f_mean = float(global_foundation_stats.get("mean", 0.0))
                            f_std = max(float(global_foundation_stats.get("std", 0.0)), 1e-12)
                            f_z = (math.log1p(max(foundation_utility_raw, 0.0)) - f_mean) / f_std
                            f_z_scaled = max(min(f_z / foundation_utility_global_zscore_scale, 50.0), -50.0)
                            foundation_utility_norm_unweighted = 100.0 / (1.0 + math.exp(-f_z_scaled))
                        else:
                            foundation_utility_norm_unweighted = self._percentile_rank(
                                sorted_values=foundation_sorted_values,
                                value=foundation_utility_raw,
                                method="mid",
                            )
                        foundation_utility_norm = foundation_utility_norm_unweighted * paper_type_weight
                    else:
                        foundation_utility_norm_unweighted = 0.0
                        foundation_utility_norm = 0.0
                    method_transferability_raw = (
                        self._compute_method_transferability_raw(rec) if method_transferability_enabled else 0.0
                    )
                    if method_transferability_enabled:
                        if (
                            method_transferability_norm_mode == "global_zscore"
                            and global_method_stats is not None
                        ):
                            m_mean = float(global_method_stats.get("mean", 0.0))
                            m_std = max(float(global_method_stats.get("std", 0.0)), 1e-12)
                            m_z = (math.log1p(max(method_transferability_raw, 0.0)) - m_mean) / m_std
                            m_z_scaled = max(min(m_z / method_transferability_global_zscore_scale, 50.0), -50.0)
                            method_transferability_norm_unweighted = 100.0 / (1.0 + math.exp(-m_z_scaled))
                        else:
                            method_transferability_norm_unweighted = self._percentile_rank(
                                sorted_values=method_sorted_values,
                                value=method_transferability_raw,
                                method="mid",
                            )
                        method_transferability_norm = method_transferability_norm_unweighted * paper_type_weight
                    else:
                        method_transferability_norm_unweighted = 0.0
                        method_transferability_norm = 0.0

                    rec["adoption_norm_unweighted"] = round(adoption_norm_unweighted, 2)
                    rec["adoption_norm"] = round(adoption_norm, 2)
                    rec["diffusion_norm_unweighted"] = round(diffusion_norm_unweighted, 2)
                    rec["diffusion_norm"] = round(diffusion_norm, 2)
                    rec["consistency_gate"] = round(consistency_gate, 3)
                    rec["global_consistency_gate_mode"] = global_consistency_gate_mode
                    rec["use_global_consistency_gate"] = global_consistency_gate_mode != "off"
                    rec["diffusion_impact_unweighted"] = round(diffusion_impact_unweighted, 2)
                    rec["diffusion_impact"] = round(diffusion_impact, 2)
                    # Keep backward compatibility: impact_score aliases diffusion_impact.
                    rec["impact_score_unweighted"] = rec["diffusion_impact_unweighted"]
                    rec["impact_score"] = rec["diffusion_impact"]
                    rec["impact_score_semantic"] = IMPACT_PRIMARY_CHANNEL
                    rec["impact_primary_channel"] = IMPACT_PRIMARY_CHANNEL
                    rec["foundation_utility_raw"] = round(foundation_utility_raw, 6)
                    rec["foundation_utility_norm_unweighted"] = round(foundation_utility_norm_unweighted, 2)
                    rec["foundation_utility_norm"] = round(foundation_utility_norm, 2)
                    rec["foundation_utility_norm_mode"] = foundation_utility_norm_mode
                    rec["method_transferability_raw"] = round(method_transferability_raw, 6)
                    rec["method_transferability_norm_unweighted"] = round(method_transferability_norm_unweighted, 2)
                    rec["method_transferability_norm"] = round(method_transferability_norm, 2)
                    rec["method_transferability_norm_mode"] = method_transferability_norm_mode
                    rec["impact_channels"] = {
                        IMPACT_PRIMARY_CHANNEL: rec["diffusion_impact"],
                    }
                    if foundation_utility_enabled:
                        rec["impact_channels"]["foundation_utility"] = rec["foundation_utility_norm"]
                    if method_transferability_enabled:
                        rec["impact_channels"]["method_transferability"] = rec["method_transferability_norm"]
                    rec["impact_output_schema_version"] = IMPACT_OUTPUT_SCHEMA_VERSION
                    rec["paper_type_detected"] = paper_type
                    rec["paper_type_weight"] = paper_type_weight
                    rec["adoption_norm_mode"] = adoption_norm_mode
                    rec["adoption_rank_method"] = adoption_rank_method
                    if adoption_norm_mode == "global_zscore":
                        rec["adoption_global_ref_count"] = int(global_adoption_stats.get("count", 0)) if global_adoption_stats else 0
                    if foundation_utility_enabled and foundation_utility_norm_mode == "global_zscore":
                        rec["foundation_utility_global_ref_count"] = (
                            int(global_foundation_stats.get("count", 0)) if global_foundation_stats else 0
                        )
                    if method_transferability_enabled and method_transferability_norm_mode == "global_zscore":
                        rec["method_transferability_global_ref_count"] = (
                            int(global_method_stats.get("count", 0)) if global_method_stats else 0
                        )

                    impact_scores.append(rec["impact_score"])
                    adoption_norms.append(rec["adoption_norm"])
                    foundation_norms.append(rec["foundation_utility_norm"])
                    foundation_raws.append(rec["foundation_utility_raw"])
                    method_norms.append(rec["method_transferability_norm"])
                    method_raws.append(rec["method_transferability_raw"])

                    fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    processed += 1
                    pbar_pending += 1
                    if pbar_pending >= 2000:
                        self._update_progress_bar(pbar, pbar_pending)
                        if pbar is not None:
                            pbar.set_postfix_str(
                                f"y={processed:,}/{n:,}",
                                refresh=False,
                            )
                        pbar_pending = 0
                    if processed % 200000 == 0:
                        self._write_progress_status(
                            "pass2_running",
                            {
                                "phase": "pass2",
                                "year": year,
                                "year_target": n,
                                "year_processed": processed,
                                "completed_years": sorted(self.checkpoint.get("pass2_years", [])),
                            },
                        )

            self._update_progress_bar(pbar, pbar_pending)
            if pbar is not None:
                pbar.close()

            impact_array = np.asarray(impact_scores, dtype=np.float64)
            adopt_array = np.asarray(adoption_norms, dtype=np.float64)
            foundation_norm_array = np.asarray(foundation_norms, dtype=np.float64) if foundation_norms else np.array([], dtype=np.float64)
            foundation_raw_array = np.asarray(foundation_raws, dtype=np.float64) if foundation_raws else np.array([], dtype=np.float64)
            method_norm_array = np.asarray(method_norms, dtype=np.float64) if method_norms else np.array([], dtype=np.float64)
            method_raw_array = np.asarray(method_raws, dtype=np.float64) if method_raws else np.array([], dtype=np.float64)

            stats = {
                "year": year,
                "count": int(len(impact_scores)),
                "impact_mean": round(float(impact_array.mean()), 4),
                "impact_median": round(float(np.percentile(impact_array, 50)), 4),
                "impact_p90": round(float(np.percentile(impact_array, 90)), 4),
                "impact_max": round(float(impact_array.max()), 4),
                "diffusion_impact_mean": round(float(impact_array.mean()), 4),
                "diffusion_impact_median": round(float(np.percentile(impact_array, 50)), 4),
                "diffusion_impact_p90": round(float(np.percentile(impact_array, 90)), 4),
                "diffusion_impact_max": round(float(impact_array.max()), 4),
                "adoption_mean": round(float(adopt_array.mean()), 4),
                "adoption_norm_mode": adoption_norm_mode,
                "adoption_rank_method": adoption_rank_method,
                "foundation_utility_enabled": bool(foundation_utility_enabled),
                "foundation_utility_norm_mode": foundation_utility_norm_mode,
                "method_transferability_enabled": bool(method_transferability_enabled),
                "method_transferability_norm_mode": method_transferability_norm_mode,
                "global_consistency_gate_mode": global_consistency_gate_mode,
                "impact_score_semantic": IMPACT_PRIMARY_CHANNEL,
                "impact_primary_channel": IMPACT_PRIMARY_CHANNEL,
                "impact_output_schema_version": IMPACT_OUTPUT_SCHEMA_VERSION,
            }
            if foundation_norm_array.size > 0:
                stats["foundation_utility_norm_mean"] = round(float(foundation_norm_array.mean()), 4)
                stats["foundation_utility_norm_p90"] = round(float(np.percentile(foundation_norm_array, 90)), 4)
            if foundation_raw_array.size > 0:
                stats["foundation_utility_raw_mean"] = round(float(foundation_raw_array.mean()), 6)
                stats["foundation_utility_raw_p90"] = round(float(np.percentile(foundation_raw_array, 90)), 6)
            if method_norm_array.size > 0:
                stats["method_transferability_norm_mean"] = round(float(method_norm_array.mean()), 4)
                stats["method_transferability_norm_p90"] = round(float(np.percentile(method_norm_array, 90)), 4)
            if method_raw_array.size > 0:
                stats["method_transferability_raw_mean"] = round(float(method_raw_array.mean()), 6)
                stats["method_transferability_raw_p90"] = round(float(np.percentile(method_raw_array, 90)), 6)
            if adoption_norm_mode == "global_zscore" and global_adoption_stats is not None:
                stats["adoption_global_ref_count"] = int(global_adoption_stats.get("count", 0))
                stats["adoption_global_ref_scope"] = adoption_global_reference_scope
            if (
                foundation_utility_enabled
                and foundation_utility_norm_mode == "global_zscore"
                and global_foundation_stats is not None
            ):
                stats["foundation_utility_global_ref_count"] = int(global_foundation_stats.get("count", 0))
                stats["foundation_utility_global_ref_scope"] = foundation_utility_global_reference_scope
            if (
                method_transferability_enabled
                and method_transferability_norm_mode == "global_zscore"
                and global_method_stats is not None
            ):
                stats["method_transferability_global_ref_count"] = int(global_method_stats.get("count", 0))
                stats["method_transferability_global_ref_scope"] = method_transferability_global_reference_scope
            summary_stats.append(stats)
            logger.info(
                "  %s: count=%s, impact_mean=%.2f, impact_p90=%.2f, impact_max=%.2f",
                year,
                f"{stats['count']:,}",
                stats["impact_mean"],
                stats["impact_p90"],
                stats["impact_max"],
            )

            if "pass2_years" not in self.checkpoint:
                self.checkpoint["pass2_years"] = []
            if year not in self.checkpoint["pass2_years"]:
                self.checkpoint["pass2_years"].append(year)
            self._save_checkpoint()
            self._write_progress_status(
                "pass2_running",
                {
                    "phase": "pass2",
                    "year": year,
                    "year_target": n,
                    "year_processed": n,
                    "completed_years": sorted(self.checkpoint.get("pass2_years", [])),
                },
            )

        if summary_stats:
            merged_summary = self._load_summary_stats_map()
            for item in summary_stats:
                merged_summary[int(item["year"])] = item
            merged_rows = [merged_summary[y] for y in sorted(merged_summary)]
            with open(self.summary_path, "w", encoding="utf-8") as f:
                json.dump(merged_rows, f, indent=2, ensure_ascii=False)
            logger.info("Pass 2 summary written: %s", self.summary_path)

        self.checkpoint["pass2_complete"] = True
        self._save_checkpoint()
        self._write_progress_status(
            "pass2_complete",
            {
                "phase": "pass2",
                "completed_years": sorted(self.checkpoint.get("pass2_years", [])),
            },
        )

    def run_all(self, years: List[int] = None, force: bool = False):
        start_time = datetime.now()
        logger.info("=" * 60)
        logger.info("Impact V6 run started")
        logger.info(
            "Config: Top-%s, consistency_threshold=%s, current_year=%s",
            self.config["top_k"],
            self.config["consistency_threshold"],
            self.config["current_year"],
        )
        logger.info(
            "Config: exclude_correction_papers=%s, min_core_coverage=%.2f, vocab_size=%s",
            self.config["exclude_correction_papers"],
            self.config["min_core_coverage"],
            self.config["vocab_size_estimate"],
        )
        logger.info(
            "Config: concept_year_attribution_enabled=%s, seed=%s",
            _as_bool(self.config.get("concept_year_attribution_enabled", False), False),
            self.config.get("concept_year_seed_field", "s_peak"),
        )
        logger.info(
            "Config: foundation_utility_enabled=%s, foundation_norm_mode=%s",
            _as_bool(self.config.get("foundation_utility_enabled", True), True),
            str(self.config.get("foundation_utility_norm_mode", "yearly_percentile")),
        )
        logger.info(
            "Config: method_transferability_enabled=%s, method_norm_mode=%s",
            _as_bool(self.config.get("method_transferability_enabled", True), True),
            str(self.config.get("method_transferability_norm_mode", "yearly_percentile")),
        )
        logger.info(
            "Config: impact_primary_channel=%s, impact_score_alias=%s",
            IMPACT_PRIMARY_CHANNEL,
            True,
        )
        logger.info("=" * 60)
        self._write_progress_status(
            "started",
            {
                "phase": "all",
                "years": list(years or self.config["years"]),
                "force": bool(force),
            },
        )

        self.run_pass0(years=years, force=force)
        self.run_pass1(years=years, force=force)
        self.run_pass2(years=years, force=force)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info("=" * 60)
        logger.info("Impact V6 completed, total elapsed %.2f hours", elapsed / 3600)
        logger.info("=" * 60)
        self._write_progress_status(
            "completed",
            {
                "phase": "all",
                "elapsed_hours": round(elapsed / 3600, 3),
                "pass0_complete": bool(self.checkpoint.get("pass0_complete", False)),
                "pass1_years": sorted(self.checkpoint.get("pass1_years", [])),
                "pass2_years": sorted(self.checkpoint.get("pass2_years", [])),
            },
        )


def parse_years(args) -> Optional[List[int]]:
    if args.year is not None:
        return [int(args.year)]
    if args.years:
        start, end = map(int, args.years.split("-"))
        return list(range(start, end + 1))
    return None


def main():
    parser = argparse.ArgumentParser(description="Impact V6 calculator")
    parser.add_argument("--pass", dest="pass_num", type=int, choices=[0, 1, 2], help="Run only selected pass")
    parser.add_argument("--year", type=int, help="Process specific year only")
    parser.add_argument("--years", type=str, help="Year range, e.g. 2010-2015")
    parser.add_argument("--force", action="store_true", help="Force re-run")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint (enabled by default)")
    parser.add_argument("--config", type=str, default=None, help="Config JSON path")
    args = parser.parse_args()

    config = build_runtime_config(args.config)
    calculator = ImpactCalculatorV6(config=config)
    years = parse_years(args)

    if args.pass_num is None:
        calculator.run_all(years=years, force=args.force)
        return

    if args.pass_num == 0:
        calculator.run_pass0(years=years, force=args.force)
    elif args.pass_num == 1:
        calculator.run_pass1(years=years, force=args.force)
    elif args.pass_num == 2:
        calculator.run_pass2(years=years, force=args.force)


if __name__ == "__main__":
    main()


