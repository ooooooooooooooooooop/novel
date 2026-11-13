# -*- coding: utf-8 -*-
"""
Innovation Signal Calculation Script
Phase 3.1 of Execution Plan

Goal: Calculate innovation signals (Peak Novelty, Synergy Novelty, Modifier Bonus) 
based on historical RPU data.

Logic:
1. Stream papers chronologically from DB.
2. Maintain a running state of historical counts (State t depends on 0...t-1).
3. Compute signals for current paper using current state.
4. Update state with current paper.
"""

import os
import sys
import json
import math
import time
import sqlite3
import re
import logging
import argparse
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional, TYPE_CHECKING
from datetime import datetime
import numpy as np
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import load_project_config, get_paths

try:
    _cfg = load_project_config()
    _paths = get_paths(_cfg)
except Exception:
    _paths = {}

_default_logs_dir = Path(_paths.get("logs_dir", str(PROJECT_ROOT / "artifacts" / "runtime" / "logs")))
_default_logs_dir.mkdir(parents=True, exist_ok=True)

DEFAULT_INPUT_PATH = _paths.get("rpu_db_path", str(PROJECT_ROOT / "output_7_deberta_full" / "rpu_database.db"))
DEFAULT_VERB_WEIGHTS_PATH = _paths.get(
    "verb_innovation_weights_path",
    str(PROJECT_ROOT / "verb_innovation_weights.json"),
)
DEFAULT_INNOVATION_LOG_PATH = _paths.get(
    "innovation_log_path",
    str(_default_logs_dir / "innovation_calculation.log"),
)

# 导入性能监控模块
from src.innovation_core.performance_metrics import PerformanceMetrics
# 导入配置管理模块
from src.innovation_core.config_manager import ConfigManager, load_config_from_args
# 导入错误处理模块
from src.innovation_core.error_handling import (
    ErrorHandler,
    ErrorHandlingContext,
    with_error_handling,
)

# 类型检查导入
if TYPE_CHECKING:
    from src.innovation_core.config_manager import InnovationEngineConfig

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(DEFAULT_INNOVATION_LOG_PATH, encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


def _normalize_space_text(value: str) -> str:
    if not value:
        return ""
    return " ".join(str(value).strip().split())


def _normalize_task_concept(value: str) -> str:
    text = _normalize_space_text(value)
    if not text:
        return ""
    if text.startswith("RAW:"):
        text = text[4:]
    text = _normalize_space_text(text).lower()
    return text


def _normalize_object_concept(value: str) -> str:
    text = _normalize_space_text(value)
    if not text:
        return ""
    if text.startswith("RAW:"):
        text = text[4:]
    text = _normalize_space_text(text).lower()
    return text


def _normalize_modifier_text(value: str) -> str:
    text = _normalize_space_text(value)
    if not text:
        return ""
    if text.lower() == "null":
        return ""
    return text.lower()


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _derive_diagnostics_path(performance_report_path: str) -> str:
    if not performance_report_path:
        return "innovation_year_diagnostics.json"
    path_obj = Path(performance_report_path)
    stem = path_obj.stem
    suffix = path_obj.suffix if path_obj.suffix else ".json"
    return str(path_obj.with_name(f"{stem}_innovation_diagnostics{suffix}"))


# ============================================================
# Count-Min Sketch: 内存高效的近似计数数据结构
# ============================================================
class CountMinSketch:
    """
    Count-Min Sketch 用于近似频率计数，固定内存开销。

    特性：
    - 只会高估计数，不会低估
    - 高频项准确，低频项可能有小误差
    - 内存固定：width * depth * 4 bytes

    默认参数 (width=2^24, depth=4) 使用约 256MB 内存，
    误差率约 0.01%，适合数十亿级别的 key。
    """

    def __init__(self, width: int = 2**24, depth: int = 4):
        """
        初始化 Count-Min Sketch。

        Args:
            width: 每行的桶数，越大越准确，默认 2^24 (约 1600 万)
            depth: 哈希函数数量（行数），越多越准确，默认 4
        """
        self.width = width
        self.depth = depth
        # 使用 numpy uint32 数组，每个元素 4 字节
        self.table = np.zeros((depth, width), dtype=np.uint32)
        # 不同的哈希种子
        self.seeds = tuple(i * 0x9e3779b9 for i in range(depth))
        # 统计信息
        self.total_increments = 0

    def _deterministic_hash(self, key) -> int:
        """使用确定性哈希（跨进程一致）"""
        import hashlib
        # 将 key 转换为字符串并编码
        key_bytes = str(key).encode('utf-8')
        # 使用 MD5 的前 8 字节作为 64 位整数
        h = hashlib.md5(key_bytes).digest()[:8]
        return int.from_bytes(h, byteorder='little')

    def _hashes(self, key) -> tuple:
        """计算 key 在每行的索引"""
        h = self._deterministic_hash(key)
        return tuple((h ^ seed) % self.width for seed in self.seeds)

    def increment(self, key, count: int = 1):
        """增加 key 的计数"""
        for i, idx in enumerate(self._hashes(key)):
            self.table[i, idx] += count
        self.total_increments += count

    def get(self, key, default: int = 0) -> int:
        """获取 key 的近似计数（取所有行的最小值）"""
        indices = self._hashes(key)
        min_count = min(self.table[i, idx] for i, idx in enumerate(indices))
        return int(min_count) if min_count > 0 else default

    def __getitem__(self, key) -> int:
        """支持 cms[key] 语法"""
        return self.get(key, 0)

    def __len__(self) -> int:
        """返回总增量次数（不是唯一 key 数）"""
        return self.total_increments

    def memory_usage_mb(self) -> float:
        """返回内存使用量（MB）"""
        return self.table.nbytes / (1024 * 1024)

    def stats(self) -> dict:
        """返回统计信息"""
        return {
            'width': self.width,
            'depth': self.depth,
            'memory_mb': self.memory_usage_mb(),
            'total_increments': self.total_increments,
            'table_fill_rate': np.count_nonzero(self.table) / self.table.size
        }


# ============================================================
# Year Cache Class: YearCache
# ============================================================
class YearCache:
    """
    Caching system for mathematical computations within year processing loops.
    Implements LRU eviction for math.log() and PMI calculations to optimize performance.
    """
    def __init__(self, max_log_cache_size: int = 10000, max_pmi_cache_size: int = 5000):
        # Math.log() cache with LRU eviction
        from collections import OrderedDict
        self.log_cache = OrderedDict()  # value -> log(value)
        self.max_log_cache_size = max_log_cache_size

        # PMI cache using frozen state identifiers as keys
        self.pmi_cache = OrderedDict()  # (state_id, term1, term2) -> pmi_value
        self.max_pmi_cache_size = max_pmi_cache_size

        # Cache statistics tracking
        self.log_hits = 0
        self.log_misses = 0
        self.pmi_hits = 0
        self.pmi_misses = 0

        # Memory usage tracking (approximate)
        self.log_cache_memory = 0  # bytes
        self.pmi_cache_memory = 0  # bytes

        # State ID cache - avoid recomputing on every call
        self._cached_state_id = None
        self._cached_state_key = None  # (total_docs, term_count_len, pair_count_len)
        
    def get_log(self, value: float) -> float:
        """
        Get cached math.log() result with LRU eviction.
        
        Args:
            value: Input value for logarithm calculation
            
        Returns:
            float: log(value) result
        """
        if value <= 0:
            raise ValueError(f"Cannot compute log of non-positive value: {value}")
            
        # Check cache first
        if value in self.log_cache:
            # Move to end (most recently used)
            result = self.log_cache.pop(value)
            self.log_cache[value] = result
            self.log_hits += 1
            return result
        
        # Cache miss - compute and store
        result = math.log(value)
        self._add_to_log_cache(value, result)
        self.log_misses += 1
        return result
        
    def get_log2(self, value: float) -> float:
        """
        Get cached math.log2() result with LRU eviction.
        
        Args:
            value: Input value for log2 calculation
            
        Returns:
            float: log2(value) result
        """
        if value <= 0:
            raise ValueError(f"Cannot compute log2 of non-positive value: {value}")
            
        # Use log cache with conversion: log2(x) = log(x) / log(2)
        log_value = self.get_log(value)
        log_2 = self.get_log(2.0)
        return log_value / log_2
        
    def get_pmi(self, state_id: str, term1: str, term2: str, 
                compute_func: callable) -> float:
        """
        Get cached PMI result using frozen state identifiers as keys.
        
        Args:
            state_id: Frozen state identifier for cache key
            term1: First term for PMI calculation
            term2: Second term for PMI calculation  
            compute_func: Function to compute PMI if not cached
            
        Returns:
            float: PMI value
        """
        cache_key = (state_id, term1, term2)
        
        # Check cache first
        if cache_key in self.pmi_cache:
            # Move to end (most recently used)
            result = self.pmi_cache.pop(cache_key)
            self.pmi_cache[cache_key] = result
            self.pmi_hits += 1
            return result
            
        # Cache miss - compute and store
        result = compute_func()
        self._add_to_pmi_cache(cache_key, result)
        self.pmi_misses += 1
        return result
        
    def _add_to_log_cache(self, value: float, result: float) -> None:
        """Add entry to log cache with LRU eviction."""
        # Evict oldest if at capacity
        if len(self.log_cache) >= self.max_log_cache_size:
            oldest_key, oldest_value = self.log_cache.popitem(last=False)
            self.log_cache_memory -= self._estimate_log_entry_size(oldest_key, oldest_value)
            
        # Add new entry
        self.log_cache[value] = result
        self.log_cache_memory += self._estimate_log_entry_size(value, result)
        
    def _add_to_pmi_cache(self, cache_key: tuple, result: float) -> None:
        """Add entry to PMI cache with LRU eviction."""
        # Evict oldest if at capacity
        if len(self.pmi_cache) >= self.max_pmi_cache_size:
            oldest_key, oldest_value = self.pmi_cache.popitem(last=False)
            self.pmi_cache_memory -= self._estimate_pmi_entry_size(oldest_key, oldest_value)
            
        # Add new entry
        self.pmi_cache[cache_key] = result
        self.pmi_cache_memory += self._estimate_pmi_entry_size(cache_key, result)
        
    def _estimate_log_entry_size(self, key: float, value: float) -> int:
        """Estimate memory size of a log cache entry in bytes."""
        # 这是经验值 - float objects + dict overhead
        return 64  # Approximate size per entry
        
    def _estimate_pmi_entry_size(self, key: tuple, value: float) -> int:
        """Estimate memory size of a PMI cache entry in bytes."""
        # 这是经验值 - tuple with strings + float + dict overhead
        state_id, term1, term2 = key
        return 128 + len(state_id) + len(term1) + len(term2)  # Approximate size
        
    def get_cache_stats(self) -> Dict[str, any]:
        """
        Get comprehensive cache statistics.
        
        Returns:
            Dict with cache hit/miss rates and memory usage
        """
        total_log_requests = self.log_hits + self.log_misses
        total_pmi_requests = self.pmi_hits + self.pmi_misses
        
        return {
            'log_cache': {
                'size': len(self.log_cache),
                'max_size': self.max_log_cache_size,
                'hits': self.log_hits,
                'misses': self.log_misses,
                'hit_rate': self.log_hits / total_log_requests if total_log_requests > 0 else 0.0,
                'memory_bytes': self.log_cache_memory
            },
            'pmi_cache': {
                'size': len(self.pmi_cache),
                'max_size': self.max_pmi_cache_size,
                'hits': self.pmi_hits,
                'misses': self.pmi_misses,
                'hit_rate': self.pmi_hits / total_pmi_requests if total_pmi_requests > 0 else 0.0,
                'memory_bytes': self.pmi_cache_memory
            },
            'total_memory_bytes': self.log_cache_memory + self.pmi_cache_memory
        }
        
    def clear_cache(self) -> None:
        """Clear all caches and reset statistics."""
        self.log_cache.clear()
        self.pmi_cache.clear()
        self.log_hits = 0
        self.log_misses = 0
        self.pmi_hits = 0
        self.pmi_misses = 0
        self.log_cache_memory = 0
        self.pmi_cache_memory = 0
        
    def get_state_id(self, innovation_state: 'InnovationState') -> str:
        """
        Generate a frozen state identifier for PMI cache keys.
        Uses caching to avoid expensive sorting on every call.

        Args:
            innovation_state: Current innovation state

        Returns:
            str: Unique identifier representing the state
        """
        # Check if state has changed using lightweight key metrics
        current_key = (
            innovation_state.total_docs,
            len(innovation_state.term_counts),
            len(innovation_state.pair_counts)
        )

        # Return cached state_id if state hasn't changed
        if self._cached_state_key == current_key and self._cached_state_id is not None:
            return self._cached_state_id

        # State changed - recompute state_id
        import hashlib

        # Use total_docs and key count metrics to create state signature
        state_signature = f"{innovation_state.total_docs}_{len(innovation_state.term_counts)}_{len(innovation_state.pair_counts)}"

        # Add hash of a sample of term counts for uniqueness
        # Use itertools.islice to avoid sorting entire dictionary
        if innovation_state.term_counts:
            import itertools
            # Take first 10 items without sorting (deterministic enough for cache key)
            sample_items = list(itertools.islice(innovation_state.term_counts.items(), 10))
            sample_str = "_".join(f"{term}:{count}" for term, count in sample_items)
            state_signature += f"_{hashlib.md5(sample_str.encode()).hexdigest()[:8]}"

        # Cache the result
        self._cached_state_key = current_key
        self._cached_state_id = state_signature

        return state_signature

    def invalidate_state_id_cache(self):
        """Invalidate the cached state_id. Call after state changes."""
        self._cached_state_id = None
        self._cached_state_key = None

# ============================================================
# Modifier Filter Class: ModifierFilter
# ============================================================
class ModifierFilter:
    """
    Frequency-based modifier filtering system for optimization.
    Tracks global modifier frequency and filters out high-frequency modifiers
    that add noise rather than meaningful innovation signals.
    """
    def __init__(self, percentile_threshold: float = 99.0, min_samples_for_filtering: int = 1000):
        """
        Initialize ModifierFilter with frequency tracking.
        
        Args:
            percentile_threshold: Percentile threshold for filtering (default 99th percentile)
            min_samples_for_filtering: Minimum number of modifiers before filtering activates
        """
        # Global modifier frequency tracking
        self.modifier_frequencies = defaultdict(int)
        self.total_modifier_occurrences = 0
        
        # Filtering configuration
        self.percentile_threshold = percentile_threshold
        self.min_samples_for_filtering = min_samples_for_filtering
        
        # Current filtering threshold (frequency count)
        self.current_frequency_threshold = 0
        
        # Filtering statistics
        self.filtered_count = 0
        self.total_processed = 0
        self.last_threshold_update_year = None
        
        # Year-boundary tracking for temporal consistency
        self.year_boundary_updates = []
        
    def update_frequencies(self, modifiers: List[str]) -> None:
        """
        Update global modifier frequencies with cumulative counts.
        
        Args:
            modifiers: List of modifiers from current paper/batch
        """
        # Use set to avoid double counting within same paper (Bernoulli model)
        unique_modifiers = set(modifier for modifier in modifiers if modifier)
        
        for modifier in unique_modifiers:
            self.modifier_frequencies[modifier] += 1
            self.total_modifier_occurrences += 1
            
    def calculate_percentile_threshold(self) -> int:
        """
        Calculate frequency threshold based on percentile of current distribution.
        
        Returns:
            int: Frequency threshold for filtering
        """
        if len(self.modifier_frequencies) < self.min_samples_for_filtering:
            return 0  # No filtering until we have enough samples
            
        # Get all frequency values
        frequencies = list(self.modifier_frequencies.values())
        
        if not frequencies:
            return 0
            
        # Calculate percentile threshold
        import numpy as np
        threshold = np.percentile(frequencies, self.percentile_threshold)
        
        # Ensure threshold is at least 1 to avoid filtering everything
        return max(1, int(threshold))
        
    def update_threshold_at_year_boundary(self, year: str) -> None:
        """
        Update filtering threshold at year boundaries for temporal consistency.
        
        Args:
            year: Current year being processed
        """
        # Calculate new threshold based on current distribution
        new_threshold = self.calculate_percentile_threshold()
        
        # Only update if threshold has changed significantly or this is first update
        if (self.current_frequency_threshold == 0 or 
            abs(new_threshold - self.current_frequency_threshold) >= 1):
            
            old_threshold = self.current_frequency_threshold
            self.current_frequency_threshold = new_threshold
            self.last_threshold_update_year = year
            
            # Record threshold update for statistics
            self.year_boundary_updates.append({
                'year': year,
                'old_threshold': old_threshold,
                'new_threshold': new_threshold,
                'total_modifiers': len(self.modifier_frequencies),
                'total_occurrences': self.total_modifier_occurrences
            })
            
            logger.info(f"ModifierFilter threshold updated at year {year}: "
                       f"{old_threshold} -> {new_threshold} "
                       f"(based on {len(self.modifier_frequencies)} unique modifiers)")
                       
    def should_filter_modifier(self, modifier: str) -> bool:
        """
        Check if a modifier should be filtered based on frequency threshold.
        
        Args:
            modifier: Modifier to check
            
        Returns:
            bool: True if modifier should be filtered (skipped), False otherwise
        """
        if not modifier:
            return True  # Filter empty/None modifiers
            
        self.total_processed += 1
        
        # No filtering if threshold not set or insufficient data
        if self.current_frequency_threshold <= 0:
            return False
            
        # Check if modifier frequency exceeds threshold
        modifier_freq = self.modifier_frequencies.get(modifier, 0)
        should_filter = modifier_freq >= self.current_frequency_threshold
        
        if should_filter:
            self.filtered_count += 1
            
        return should_filter
        
    def get_filtering_stats(self) -> Dict[str, any]:
        """
        Get comprehensive filtering statistics.
        
        Returns:
            Dict with filtering statistics and performance metrics
        """
        filter_rate = self.filtered_count / self.total_processed if self.total_processed > 0 else 0.0
        
        # Get top frequent modifiers for analysis
        top_modifiers = sorted(
            self.modifier_frequencies.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:10]
        
        return {
            'total_processed': self.total_processed,
            'filtered_count': self.filtered_count,
            'filter_rate': filter_rate,
            'current_threshold': self.current_frequency_threshold,
            'percentile_threshold': self.percentile_threshold,
            'unique_modifiers': len(self.modifier_frequencies),
            'total_occurrences': self.total_modifier_occurrences,
            'last_update_year': self.last_threshold_update_year,
            'threshold_updates': len(self.year_boundary_updates),
            'top_frequent_modifiers': top_modifiers,
            'filtering_active': self.current_frequency_threshold > 0
        }
        
    def get_filtered_modifiers(self) -> Set[str]:
        """
        Get set of currently filtered modifiers based on threshold.
        
        Returns:
            Set of modifier strings that would be filtered
        """
        if self.current_frequency_threshold <= 0:
            return set()
            
        return {
            modifier for modifier, freq in self.modifier_frequencies.items()
            if freq >= self.current_frequency_threshold
        }
        
    def reset_statistics(self) -> None:
        """
        Reset filtering statistics while preserving frequency data.
        Useful for performance measurement comparisons.
        """
        self.filtered_count = 0
        self.total_processed = 0
        
    def clear_all_data(self) -> None:
        """
        Clear all frequency data and statistics.
        Use with caution - this resets the entire filter state.
        """
        self.modifier_frequencies.clear()
        self.total_modifier_occurrences = 0
        self.current_frequency_threshold = 0
        self.filtered_count = 0
        self.total_processed = 0
        self.last_threshold_update_year = None
        self.year_boundary_updates.clear()

# ============================================================
# Year Buffer Class: YearBuffer
# ============================================================
class YearBuffer:
    """
    Temporary buffer for accumulating RPU counts within a year before atomic merge.
    Implements Year-Atomic Update pattern for performance optimization.
    """
    def __init__(self, synergy_granularity_mode: str = "task_object"):
        # Temporary counts that mirror InnovationState structure
        self.term_counts = defaultdict(int)
        self.pair_counts = defaultdict(int)
        self.cooc_counts = defaultdict(int)
        self.mod_given_core_counts = defaultdict(int)
        self.core_counts_for_mod = defaultdict(int)
        self.total_docs = 0
        self.synergy_granularity_mode = (synergy_granularity_mode or "task_object").strip().lower()
        if self.synergy_granularity_mode not in {"task_object", "object_only", "hybrid"}:
            self.synergy_granularity_mode = "task_object"
        
        # Validation tracking
        self.papers_processed = 0
        self.rpus_processed = 0
        
    def _build_synergy_term_sets(self, task_object_pairs: Set[Tuple[str, str]]) -> Tuple[Set[str], Set[str]]:
        task_object_terms = set()
        object_only_terms = set()
        for t, o in task_object_pairs:
            if not t or not o:
                continue
            task_object_terms.add(f"SY_TO:T:{t}|O:{o}")
            object_only_terms.add(f"SY_O:{o}")
        return task_object_terms, object_only_terms

    def _select_state_terms(self, task_object_terms: Set[str], object_only_terms: Set[str]) -> Set[str]:
        if self.synergy_granularity_mode == "object_only":
            return set(object_only_terms)
        if self.synergy_granularity_mode == "hybrid":
            return set(task_object_terms) | set(object_only_terms)
        return set(task_object_terms)

    def accumulate_from_paper(self, rpu_list: List[Dict]):
        """
        Accumulate counts from a single paper's RPUs without updating global state.
        
        Args:
            rpu_list: List of RPU dictionaries with 'task', 'object', 'modifier' fields
        """
        if not rpu_list:
            return
            
        self.total_docs += 1
        self.papers_processed += 1
        
        # Sets to avoid double counting within same paper (Bernoulli model)
        seen_terms = set()
        seen_pairs = set()
        seen_mods = set()
        
        task_object_pairs = set()
        
        for rpu in rpu_list:
            self.rpus_processed += 1
            
            t = rpu.get('task_norm') or rpu.get('task_core') or rpu.get('task')
            o = rpu.get('object_norm') or rpu.get('object_core') or rpu.get('object')
            m = rpu.get('modifier_norm') or rpu.get('modifier')
            
            # Construct unique string for Synergy
            if t and o:
                task_object_pairs.add((t, o))
                
                # Peak Novelty Pairs
                pair = (t, o)
                if pair not in seen_pairs:
                    self.pair_counts[pair] += 1
                    seen_pairs.add(pair)
            
            # Modifier Conditional (Core = Object for modifier attachment)
            if o and m:
                mod_pair = (o, m)
                if mod_pair not in seen_mods:
                    self.mod_given_core_counts[mod_pair] += 1
                    self.core_counts_for_mod[o] += 1
                    seen_mods.add(mod_pair)
            
            if t: seen_terms.add(t)
            if o: seen_terms.add(o)
            
        # Update Term Counts
        for term in seen_terms:
            self.term_counts[term] += 1
            
        # Update Synergy Co-occurrence
        task_object_terms, object_only_terms = self._build_synergy_term_sets(task_object_pairs)
        selected_terms = self._select_state_terms(task_object_terms, object_only_terms)
        sorted_rpus = sorted(list(selected_terms))
        for i in range(len(sorted_rpus)):
            for j in range(i + 1, len(sorted_rpus)):
                self.cooc_counts[(sorted_rpus[i], sorted_rpus[j])] += 1
                
        # Update RPU counts for synergy P(x)
        for r in sorted_rpus:
            self.term_counts[r] += 1
    
    def merge_into_state(self, innovation_state: 'InnovationState') -> None:
        """
        Atomically merge all buffered counts into the global InnovationState.
        
        Args:
            innovation_state: The global state to merge into
        """
        # Merge all count dictionaries
        for key, count in self.term_counts.items():
            innovation_state.term_counts[key] += count
            
        for key, count in self.pair_counts.items():
            innovation_state.pair_counts[key] += count

        # cooc_counts 使用 CMS，需要调用 increment 而非 +=
        for key, count in self.cooc_counts.items():
            innovation_state.cooc_counts.increment(key, count)
            
        for key, count in self.mod_given_core_counts.items():
            innovation_state.mod_given_core_counts[key] += count
            
        for key, count in self.core_counts_for_mod.items():
            innovation_state.core_counts_for_mod[key] += count
            
        # Update total document count
        innovation_state.total_docs += self.total_docs
        
        logger.info(f"Merged YearBuffer: {self.papers_processed} papers, {self.rpus_processed} RPUs")
    
    def update_modifier_filter_from_buffer(self, innovation_state: 'InnovationState') -> None:
        """
        Update modifier filter frequencies from buffered data.
        
        Args:
            innovation_state: The global state containing the modifier filter
        """
        if not innovation_state.modifier_filter:
            return
            
        # Extract modifiers from buffered modifier pairs
        modifiers_in_buffer = []
        for (core, modifier), count in self.mod_given_core_counts.items():
            # Add modifier 'count' times to represent its frequency in buffer
            modifiers_in_buffer.extend([modifier] * count)
            
        # Update filter frequencies
        innovation_state.modifier_filter.update_frequencies(modifiers_in_buffer)
    
    def validate_buffer(self) -> bool:
        """
        Validate buffer state for consistency and completeness.
        
        Returns:
            bool: True if buffer is valid, False otherwise
        """
        # Check basic consistency
        if self.total_docs != self.papers_processed:
            logger.error(f"Buffer validation failed: total_docs ({self.total_docs}) != papers_processed ({self.papers_processed})")
            return False
            
        if self.papers_processed < 0 or self.rpus_processed < 0:
            logger.error(f"Buffer validation failed: negative counts detected")
            return False
            
        # Check that we have some data if papers were processed
        if self.papers_processed > 0:
            if not self.term_counts and not self.pair_counts:
                logger.warning(f"Buffer validation warning: {self.papers_processed} papers processed but no counts accumulated")
                
        return True
    
    def cleanup(self) -> None:
        """
        Clear all buffer contents and reset counters.
        """
        self.term_counts.clear()
        self.pair_counts.clear()
        self.cooc_counts.clear()
        self.mod_given_core_counts.clear()
        self.core_counts_for_mod.clear()
        self.total_docs = 0
        self.papers_processed = 0
        self.rpus_processed = 0
        
    def get_buffer_stats(self) -> Dict[str, int]:
        """
        Get statistics about the current buffer state.
        
        Returns:
            Dict with buffer statistics
        """
        return {
            'papers_processed': self.papers_processed,
            'rpus_processed': self.rpus_processed,
            'total_docs': self.total_docs,
            'unique_terms': len(self.term_counts),
            'unique_pairs': len(self.pair_counts),
            'unique_cooccurrences': len(self.cooc_counts),
            'unique_modifier_pairs': len(self.mod_given_core_counts),
            'unique_cores_for_mods': len(self.core_counts_for_mod)
        }

# ============================================================
# V2: Task IDF Tracker
# ============================================================
class TaskIDFTracker:
    """
    Tracks document frequency of task verbs across papers for IDF computation.
    Accumulated incrementally at year boundaries.
    """
    def __init__(self):
        self.task_doc_freq = defaultdict(int)  # task -> number of papers containing it
        self.total_docs = 0

    def update_from_paper(self, rpu_list: List[Dict]):
        """Update task document frequencies from a single paper's RPUs."""
        if not rpu_list:
            return
        self.total_docs += 1
        seen_tasks = set()
        for rpu in rpu_list:
            t = rpu.get('task_norm') or rpu.get('task_core') or rpu.get('task')
            if t and t not in seen_tasks:
                self.task_doc_freq[t] += 1
                seen_tasks.add(t)

    def get_idf(self, task: str) -> float:
        """Get IDF value for a task verb. Returns 0 if no docs yet."""
        if self.total_docs == 0 or not task:
            return 0.0
        df = self.task_doc_freq.get(task, 0)
        return max(0.0, math.log2(self.total_docs / (df + 1)))


# ============================================================
# V2: Feature Extractor
# ============================================================
class FeatureExtractor:
    """
    Extracts a d-dimensional feature vector from a paper's RPU list.
    Features: [avg_task_idf, task_diversity, aspect_ratio, modifier_ratio,
               avg_object_len, rpu_count_log]
    """
    FEATURE_DIM = 6

    def __init__(self, task_idf_tracker: TaskIDFTracker):
        self.task_idf_tracker = task_idf_tracker

    def extract_features(self, rpu_list: List[Dict]) -> np.ndarray:
        """Extract feature vector from a paper's RPU list."""
        if not rpu_list:
            return np.zeros(self.FEATURE_DIM)

        n_rpus = len(rpu_list)
        tasks = []
        unique_tasks = set()
        n_has_aspect = 0
        n_has_modifier = 0
        object_lens = []

        for rpu in rpu_list:
            t = rpu.get('task_norm') or rpu.get('task_core') or rpu.get('task')
            o = rpu.get('object_norm') or rpu.get('object_core') or rpu.get('object')
            m = rpu.get('modifier_norm') or rpu.get('modifier')

            if t:
                tasks.append(t)
                unique_tasks.add(t)
            if o:
                object_lens.append(len(o.split()))
            # aspect_ratio: use modifier as proxy for aspect coverage
            if rpu.get('aspect') or rpu.get('modifier'):
                n_has_aspect += 1
            if m:
                n_has_modifier += 1

        # avg_task_idf
        if tasks:
            avg_task_idf = np.mean([self.task_idf_tracker.get_idf(t) for t in tasks])
        else:
            avg_task_idf = 0.0

        # task_diversity
        task_diversity = len(unique_tasks) / n_rpus if n_rpus > 0 else 0.0

        # aspect_ratio
        aspect_ratio = n_has_aspect / n_rpus if n_rpus > 0 else 0.0

        # modifier_ratio
        modifier_ratio = n_has_modifier / n_rpus if n_rpus > 0 else 0.0

        # avg_object_len
        avg_object_len = np.mean(object_lens) if object_lens else 0.0

        # rpu_count_log
        rpu_count_log = math.log(1 + n_rpus)

        return np.array([
            avg_task_idf,
            task_diversity,
            aspect_ratio,
            modifier_ratio,
            avg_object_len,
            rpu_count_log
        ])


# ============================================================
# V2: Regular Space Model (PCA-based with Directional Constraint)
# ============================================================
class RegularSpaceModel:
    """
    Models the 'regular academic space' using PCA on historical feature vectors.
    Innovation signal = signed residual projected onto expected innovation direction.

    Key improvement: Directional constraint + signed residual
    - Defines "expected innovation direction" vector w
    - Only counts residuals that align with this direction (toward complexity/novelty)
    - Residuals toward "degradation" (simpler/shorter) are ignored
    """

    # Expected innovation direction weights for each feature dimension:
    # [avg_task_idf, task_diversity, aspect_ratio, modifier_ratio, avg_object_len, rpu_count_log]
    # Positive weight = higher value indicates innovation
    # Negative weight = lower value indicates innovation (none in our case)
    INNOVATION_DIRECTION = np.array([
        1.0,   # avg_task_idf: rare tasks are innovative
        1.0,   # task_diversity: diverse tasks are innovative
        1.0,   # aspect_ratio: having aspects is innovative
        1.0,   # modifier_ratio: having modifiers is innovative
        0.5,   # avg_object_len: longer objects slightly innovative (but not dominant)
        -0.3,  # rpu_count_log: fewer RPUs can still be innovative (slight negative to avoid review bias)
    ])

    def __init__(self, min_papers_for_full_mode: int = 10000, min_variance_threshold: float = 0.01,
                 max_accumulated_features: int = 2_000_000):
        self.is_degraded = True
        self.degraded_reason = "no_data"
        self.min_papers_for_full_mode = min_papers_for_full_mode
        self.min_variance_threshold = min_variance_threshold
        self.max_accumulated_features = max_accumulated_features  # 限制内存使用

        self.mean_history = None
        self.std_history = None
        self.P_k = None
        self.accumulated_features = []  # list of np.ndarray
        self.explained_variance_info = {}

        # Normalize innovation direction to unit vector
        self.innovation_direction = self.INNOVATION_DIRECTION / np.linalg.norm(self.INNOVATION_DIRECTION)

    def update_at_year_boundary(self, year_features: List[np.ndarray], year: str = ""):
        """Accumulate features and refit PCA at year boundary."""
        self.accumulated_features.extend(year_features)

        # 限制累积特征数量，防止内存无限增长
        # 保留最近的样本，丢弃最早的（PCA 只需足够多样本即可准确估计）
        if len(self.accumulated_features) > self.max_accumulated_features:
            excess = len(self.accumulated_features) - self.max_accumulated_features
            self.accumulated_features = self.accumulated_features[excess:]
            logger.info(f"RegularSpaceModel [{year}]: trimmed {excess:,} old features, "
                       f"keeping {self.max_accumulated_features:,}")

        n = len(self.accumulated_features)

        if n < 100:
            self.is_degraded = True
            self.degraded_reason = "insufficient_data"
            logger.info(f"RegularSpaceModel [{year}]: insufficient data ({n} papers), degraded mode")
            return

        if n < self.min_papers_for_full_mode:
            self.is_degraded = True
            self.degraded_reason = "warming_up"
        else:
            self.is_degraded = False
            self.degraded_reason = None

        X = np.array(self.accumulated_features)
        self.mean_history = X.mean(axis=0)
        self.std_history = X.std(axis=0) + 1e-8
        X_norm = (X - self.mean_history) / self.std_history

        from sklearn.decomposition import PCA as _PCA
        # 使用 svd_solver='full' 确保完全确定性（避免随机化 SVD）
        pca = _PCA(svd_solver='full', random_state=42)
        pca.fit(X_norm)

        cumvar = np.cumsum(pca.explained_variance_ratio_)
        k = int(np.searchsorted(cumvar, 0.80)) + 1
        k = max(1, min(k, X.shape[1] - 1))
        self.P_k = pca.components_[:k]

        self.explained_variance_info = {
            'k': k,
            'cumulative_variance': float(cumvar[k - 1]),
            'n_samples': n,
            'degraded': self.is_degraded,
        }
        logger.info(f"RegularSpaceModel [{year}]: fitted PCA with k={k}, "
                     f"explained_var={cumvar[k-1]:.2%}, n={n}, degraded={self.is_degraded}")

    def transform(self, feature_vector: np.ndarray):
        """
        Compute innovation magnitude with directional constraint.

        Returns: (magnitude, is_degraded, degraded_reason)

        The innovation magnitude is computed as:
        1. Compute residual: r = x_norm - PCA_projection(x_norm)
        2. Project residual onto innovation direction: proj = r · w
        3. Only keep positive projection (innovation direction), clamp negative to 0
        4. Add small contribution from perpendicular residual (novelty not captured by direction)

        This ensures:
        - Papers deviating toward "simpler/shorter" get low scores
        - Papers deviating toward "more complex/rare" get high scores
        """
        if self.P_k is None:
            # No model yet - use directional projection of raw features
            proj = float(np.dot(feature_vector, self.innovation_direction))
            return max(0.0, proj), True, "no_model"

        x_norm = (feature_vector - self.mean_history) / self.std_history

        # Compute PCA reconstruction and residual
        x_regular = self.P_k.T @ (self.P_k @ x_norm)
        x_residual = x_norm - x_regular

        # Project residual onto innovation direction (signed projection)
        directional_component = float(np.dot(x_residual, self.innovation_direction))

        # Only keep positive direction (toward innovation)
        # Negative direction means "degradation" - ignore it
        signed_innovation = max(0.0, directional_component)

        # Add small contribution from perpendicular residual (captures other novelty)
        perpendicular = x_residual - directional_component * self.innovation_direction
        perpendicular_magnitude = float(np.linalg.norm(perpendicular))

        # Combine: mainly directional, with small perpendicular bonus
        # Weight: 80% directional, 20% perpendicular
        magnitude = 0.8 * signed_innovation + 0.2 * perpendicular_magnitude

        return magnitude, self.is_degraded, self.degraded_reason

    @staticmethod
    @staticmethod
    def percentile_rank(value: float, values: List[float]) -> float:
        """Compute percentile rank of value within values list (0-100).

        DEPRECATED: Use percentile_rank_batch for better performance.
        """
        if not values:
            return 50.0
        arr = np.array(values)
        return float(np.searchsorted(np.sort(arr), value) / len(arr) * 100)

    @staticmethod
    def percentile_rank_batch(values: List[float]) -> List[float]:
        """Compute percentile ranks for all values efficiently (O(n log n))."""
        if not values:
            return []
        arr = np.array(values)
        n = len(arr)
        # Get sorted indices
        sorted_indices = np.argsort(arr)
        # Create rank array: ranks[sorted_indices[i]] = i
        ranks = np.empty(n, dtype=np.float64)
        ranks[sorted_indices] = np.arange(n)
        # Convert to percentile (0-100)
        return (ranks / n * 100).tolist()

    def check_variance(self, magnitudes: List[float], year: str = ""):
        """Check if innovation magnitude distribution has sufficient variance."""
        if not magnitudes:
            return
        var = np.var(magnitudes)
        if var < self.min_variance_threshold:
            logger.warning(f"RegularSpaceModel [{year}]: innovation variance too low ({var:.4f})")


# ============================================================
# V2: Signal Combiner
# ============================================================
class SignalCombiner:
    """
    Combines original V1 signals with V2 PCA-based innovation signal.
    Weights are set proportional to 1/std of each signal for equal contribution.
    """
    @staticmethod
    def combine(s_peak: float, s_synergy: float, s_bonus: float,
                score_v2: float, stds: Optional[Dict[str, float]] = None) -> float:
        """
        Combine signals into final total_score_v2.
        If stds not provided, use equal weights.
        """
        if stds and all(v > 0 for v in stds.values()):
            w1 = 1.0 / stds['s_peak']
            w2 = 1.0 / stds['s_synergy']
            w3 = 1.0 / stds['s_bonus']
            w4 = 1.0 / stds['score_v2']
            total_w = w1 + w2 + w3 + w4
            return (w1 * s_peak + w2 * s_synergy + w3 * s_bonus + w4 * score_v2) / total_w
        else:
            return (s_peak + s_synergy + s_bonus + score_v2) / 4.0


# ============================================================
# V2: Paper Type Post-Processor
# ============================================================
class PaperTypePostProcessor:
    """
    Post-processor to apply paper type weighting to innovation scores.
    Detects paper type from title and applies discount factor.

    Usage:
        processor = PaperTypePostProcessor()
        results = state.process_year_atomic(year_papers, year)
        # If paper_titles is available:
        processor.apply_type_weights(results, paper_titles)
    """

    # Paper type detection patterns and discount weights
    # Lower weight = lower final score
    # Matches titles like:
    #   "... (vol 33, pg 219, 2020)"
    VOLUME_PAGE_CORRECTION_RE = re.compile(
        r"\(\s*vol\.?\s*\d+\s*,\s*pg\.?\s*\d+\s*,\s*(?:19|20)\d{2}\s*\)",
        re.IGNORECASE,
    )

    PAPER_TYPE_WEIGHTS = {
        'erratum': {
            'patterns': ['erratum', 'corrigendum', 'correction', 'retraction', 'amendment'],
            'weight': 0.1,  # 90% discount
        },
        'editorial': {
            'patterns': ['editorial', 'letter to editor', 'response to', 'reply to'],
            'weight': 0.3,  # 70% discount
        },
        'commentary': {
            'patterns': ['commentary', 'comment on', 'opinion', 'perspective'],
            'weight': 0.4,  # 60% discount
        },
        'review': {
            'patterns': ['review', 'survey', 'overview', 'meta-analysis', 'systematic review'],
            'weight': 0.7,  # 30% discount
        },
        'case_report': {
            'patterns': ['case report', 'case study', 'clinical case'],
            'weight': 0.8,  # 20% discount
        },
        'original': {
            'patterns': [],
            'weight': 1.0,  # No discount
        },
    }

    def __init__(self, custom_weights: Optional[Dict[str, float]] = None):
        """
        Initialize with optional custom weights.

        Args:
            custom_weights: Dict mapping paper_type to weight (0.0-1.0)
        """
        self.weights = {k: v['weight'] for k, v in self.PAPER_TYPE_WEIGHTS.items()}
        if custom_weights:
            self.weights.update(custom_weights)

    def detect_paper_type(self, title: str) -> Tuple[str, float]:
        """
        Detect paper type from title.

        Returns: (paper_type, weight)
        """
        if not title:
            return ('original', 1.0)

        title_lower = title.lower()

        if self.VOLUME_PAGE_CORRECTION_RE.search(title):
            return ('erratum', self.weights['erratum'])

        for ptype, config in self.PAPER_TYPE_WEIGHTS.items():
            if ptype == 'original':
                continue
            for pattern in config['patterns']:
                if pattern in title_lower:
                    return (ptype, self.weights[ptype])

        return ('original', self.weights['original'])

    def apply_type_weights(self, results: List[Dict], paper_titles: Dict[str, str],
                           fields_to_weight: List[str] = None) -> List[Dict]:
        """
        Apply paper type weights to results.

        Args:
            results: List of result dicts from process_year_atomic
            paper_titles: Dict mapping paper_id to title
            fields_to_weight: List of fields to apply weight to.
                              Default: ['innovation_magnitude', 'score_v2', 'total_score_v2']

        Returns:
            Modified results list (also modified in-place)
        """
        if fields_to_weight is None:
            fields_to_weight = ['innovation_magnitude', 'score_v2', 'total_score_v2']

        for r in results:
            paper_id = r['paper_id']
            title = paper_titles.get(paper_id, '')
            paper_type, weight = self.detect_paper_type(title)

            # Store detected type and weight
            r['paper_type_detected'] = paper_type
            r['paper_type_weight'] = weight

            # Apply weight to specified fields
            for field in fields_to_weight:
                if field in r:
                    original_value = r[field]
                    r[field] = round(original_value * weight, 4)
                    # Optionally store original value
                    r[f'{field}_unweighted'] = original_value

        return results

    def get_weight_stats(self, results: List[Dict]) -> Dict:
        """Get statistics about applied weights."""
        type_counts = defaultdict(int)
        for r in results:
            ptype = r.get('paper_type_detected', 'unknown')
            type_counts[ptype] += 1
        return dict(type_counts)


# ============================================================
# Core Logic Class: InnovationState
# ============================================================
class InnovationState:
    """
    Maintains the global historical state for innovation calculation.
    Strictly adheres to causal causality: State at time t only contains info from papers < t.
    """
    def __init__(self, config: Optional['InnovationEngineConfig'] = None, vocab_size_estimate: int = 100000, 
                 enable_cache: bool = True, enable_modifier_filter: bool = True, 
                 modifier_filter_percentile: float = 99.0, enable_performance_metrics: bool = True):
        """
        初始化创新状态管理器
        
        Args:
            config: 配置对象，如果提供则优先使用配置中的参数
            vocab_size_estimate: 词汇表大小估计（向后兼容参数）
            enable_cache: 是否启用缓存（向后兼容参数）
            enable_modifier_filter: 是否启用修饰符过滤（向后兼容参数）
            modifier_filter_percentile: 修饰符过滤百分位阈值（向后兼容参数）
            enable_performance_metrics: 是否启用性能监控（向后兼容参数）
        """
        # 如果提供了配置对象，使用配置中的参数
        if config:
            cache_config = config.cache
            modifier_config = config.modifier_filter
            algorithm_config = config.algorithm
            performance_config = config.performance
            
            # 使用配置中的参数
            enable_cache = cache_config.enable_cache
            enable_modifier_filter = modifier_config.enable_modifier_filter
            modifier_filter_percentile = modifier_config.percentile_threshold
            enable_performance_metrics = performance_config.enable_performance_metrics
            
            # 算法参数
            self.prune_threshold = algorithm_config.prune_threshold
            self.SYNERGY_MIN_SUPPORT = algorithm_config.synergy_min_support
            self.top_k_signals = algorithm_config.top_k_signals
            self.core_stability_smoothing = algorithm_config.core_stability_smoothing
            self.object_coverage_policy = str(
                getattr(algorithm_config, "object_coverage_policy", "soft_weight")
            ).strip().lower()
            self.object_coverage_threshold = float(
                getattr(algorithm_config, "object_coverage_threshold", 0.2)
            )
            self.object_coverage_soft_floor = float(
                getattr(algorithm_config, "object_coverage_soft_floor", 0.25)
            )
            self.pair_normalization_mode = str(
                getattr(algorithm_config, "pair_normalization_mode", "lower_compact")
            ).strip().lower()
            self.pca_feature_source = str(
                getattr(algorithm_config, "pca_feature_source", "phase1_snapshot")
            ).strip().lower()
            self.pca_bias_diagnostic_enabled = bool(
                getattr(algorithm_config, "pca_bias_diagnostic_enabled", True)
            )
            self.pca_bias_min_group_size = int(
                getattr(algorithm_config, "pca_bias_min_group_size", 500)
            )
            self.pca_bias_alert_shift_pp = float(
                getattr(algorithm_config, "pca_bias_alert_shift_pp", 8.0)
            )
            self.pca_bias_top_groups = int(
                getattr(algorithm_config, "pca_bias_top_groups", 20)
            )
            self.synergy_granularity_mode = str(
                getattr(algorithm_config, "synergy_granularity_mode", "task_object")
            ).strip().lower()
            self.synergy_blend_object_weight = float(
                getattr(algorithm_config, "synergy_blend_object_weight", 0.5)
            )
            self.synergy_granularity_ab_enabled = bool(
                getattr(algorithm_config, "synergy_granularity_ab_enabled", True)
            )
            self.synergy_granularity_ab_top_share = float(
                getattr(algorithm_config, "synergy_granularity_ab_top_share", 0.01)
            )
            
            # 缓存参数
            cache_max_log_size = cache_config.max_log_cache_size
            cache_max_pmi_size = cache_config.max_pmi_cache_size
            
            # 性能监控参数
            self.memory_sample_interval = performance_config.memory_sample_interval
            self.cache_report_interval = performance_config.cache_report_interval
            self.modifier_filter_report_interval = performance_config.modifier_filter_report_interval
            self.high_performance_threshold = performance_config.high_performance_threshold
            
        else:
            # 使用传统参数（向后兼容）
            self.prune_threshold = 10_000_000  # 这是经验值
            self.SYNERGY_MIN_SUPPORT = 2       # 这是经验值
            self.top_k_signals = 3             # 这是经验值
            self.core_stability_smoothing = 1000  # 这是经验值
            self.object_coverage_policy = "soft_weight"
            self.object_coverage_threshold = 0.2
            self.object_coverage_soft_floor = 0.25
            self.pair_normalization_mode = "lower_compact"
            self.pca_feature_source = "phase1_snapshot"
            self.pca_bias_diagnostic_enabled = True
            self.pca_bias_min_group_size = 500
            self.pca_bias_alert_shift_pp = 8.0
            self.pca_bias_top_groups = 20
            self.synergy_granularity_mode = "task_object"
            self.synergy_blend_object_weight = 0.5
            self.synergy_granularity_ab_enabled = True
            self.synergy_granularity_ab_top_share = 0.01
            
            cache_max_log_size = 10000
            cache_max_pmi_size = 5000
            
            self.memory_sample_interval = 10
            self.cache_report_interval = 5
            self.modifier_filter_report_interval = 10
            self.high_performance_threshold = 100.0

        if self.object_coverage_policy not in {"off", "hard_filter", "soft_weight"}:
            self.object_coverage_policy = "soft_weight"
        self.object_coverage_threshold = max(0.0, min(self.object_coverage_threshold, 1.0))
        self.object_coverage_soft_floor = max(0.0, min(self.object_coverage_soft_floor, 1.0))

        if self.pair_normalization_mode not in {"raw", "lower_compact"}:
            self.pair_normalization_mode = "lower_compact"
        if self.pca_feature_source not in {"phase1_snapshot", "phase2_recompute"}:
            self.pca_feature_source = "phase1_snapshot"

        if self.synergy_granularity_mode not in {"task_object", "object_only", "hybrid"}:
            self.synergy_granularity_mode = "task_object"
        self.synergy_blend_object_weight = max(0.0, min(self.synergy_blend_object_weight, 1.0))
        self.synergy_granularity_ab_top_share = max(1e-6, min(self.synergy_granularity_ab_top_share, 0.5))
        self.pca_bias_min_group_size = max(self.pca_bias_min_group_size, 10)
        self.pca_bias_top_groups = max(self.pca_bias_top_groups, 1)
        self.pca_bias_alert_shift_pp = max(self.pca_bias_alert_shift_pp, 0.0)
        
        # Global counts for PMI and Novelty
        self.term_counts = defaultdict(int)  # Count(Core_Task), Count(Core_Object), Count(Modifier)
        self.pair_counts = defaultdict(int)  # Count(Task, Object)
        # 使用 Count-Min Sketch 存储 cooc_counts，节省内存（从 ~77GB 降到 ~256MB）
        # CMS 只会轻微高估低频项，对 PMI 计算影响可忽略
        self.cooc_counts = CountMinSketch(width=2**24, depth=4)  # ~256MB
        
        # Conditional counts for Modifier Bonus
        self.mod_given_core_counts = defaultdict(int) # Count(Modifier | Core)
        self.core_counts_for_mod = defaultdict(int)   # Count(Core) specifically for mod calc
        
        self.total_docs = 0
        self.vocab_size_estimate = vocab_size_estimate
        
        # Year Cache for mathematical computation optimization
        if enable_cache:
            self.cache = YearCache(
                max_log_cache_size=cache_max_log_size,
                max_pmi_cache_size=cache_max_pmi_size
            )
        else:
            self.cache = None
        
        # Modifier Filter for high-frequency modifier filtering
        if enable_modifier_filter:
            self.modifier_filter = ModifierFilter(
                percentile_threshold=modifier_filter_percentile,
                min_samples_for_filtering=modifier_config.min_samples_for_filtering if config else 1000
            )
        else:
            self.modifier_filter = None
        
        # Performance Metrics for comprehensive monitoring
        self.performance_metrics = PerformanceMetrics() if enable_performance_metrics else None
        
        # Error Handler for comprehensive error handling and recovery
        self.error_handler = ErrorHandler(config=config) if config else ErrorHandler()
        
        # Filtering statistics tracking for integration monitoring
        self.modifier_filter_stats = {
            'total_modifier_bonus_calls': 0,
            'filtered_modifier_calls': 0,
            'synergy_concepts_filtered': 0,
            'total_synergy_concepts_processed': 0
        }

        # ============================================================
        # V2: PCA-based innovation scoring components
        # ============================================================
        self.task_idf_tracker = TaskIDFTracker()
        self.feature_extractor = FeatureExtractor(self.task_idf_tracker)
        self.regular_space_model = RegularSpaceModel()
        self.signal_combiner = SignalCombiner()

        # ============================================================
        # V3: Verb Innovation Weight System (IDF自适应 + 锚点微调)
        # ============================================================
        self.verb_anchor_config = {}
        self.verb_anchors = {}  # verb -> fixed_weight
        self.idf_weight_min = 0.2
        self.idf_weight_max = 1.0
        self._load_verb_anchor_config()
        self.last_year_diagnostics: Dict[str, dict] = {}

    def _load_verb_anchor_config(self) -> None:
        """
        加载动词锚点配置文件。
        只定义少量锚点词，其余动词权重由IDF自动计算。
        为每个锚点词生成常见变形以提高匹配率。
        """
        candidate_paths = [
            Path(DEFAULT_VERB_WEIGHTS_PATH),
            Path(__file__).resolve().parent / "verb_innovation_weights.json",
        ]
        config_file = next((p for p in candidate_paths if p.exists()), None)

        if config_file is not None:
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                # 解析锚点并生成变形
                self.verb_anchors = {}
                anchor_groups = [
                    ('anchor_high', 0.95),
                    ('anchor_medium_high', 0.8),
                    ('anchor_low', 0.25),
                    ('anchor_very_low', 0.1),
                ]
                for group_name, weight in anchor_groups:
                    for verb in config.get(group_name, {}).get('verbs', []):
                        for form in self._generate_verb_forms(verb.lower()):
                            self.verb_anchors[form] = weight

                # IDF 映射范围
                idf_range = config.get('idf_weight_range', {})
                self.idf_weight_min = idf_range.get('min', 0.2)
                self.idf_weight_max = idf_range.get('max', 1.0)

                logger.info(
                    f"Loaded {len(self.verb_anchors)} anchor verb forms from {config_file}, "
                    f"IDF range [{self.idf_weight_min}, {self.idf_weight_max}]"
                )
            except Exception as e:
                logger.warning(f"Failed to load verb anchor config: {e}")
        else:
            logger.info("Verb anchor config not found, using pure IDF-based weights")

    def _generate_verb_forms(self, verb: str) -> List[str]:
        """
        为动词生成常见变形（原形、第三人称单数、过去式、进行时）。
        """
        forms = [verb]

        # 第三人称单数 -s/-es
        if verb.endswith(('s', 'x', 'z', 'ch', 'sh')):
            forms.append(verb + 'es')
        elif verb.endswith('y') and len(verb) > 1 and verb[-2] not in 'aeiou':
            forms.append(verb[:-1] + 'ies')
        else:
            forms.append(verb + 's')

        # 过去式/过去分词 -ed
        if verb.endswith('e'):
            forms.append(verb + 'd')
        elif verb.endswith('y') and len(verb) > 1 and verb[-2] not in 'aeiou':
            forms.append(verb[:-1] + 'ied')
        else:
            forms.append(verb + 'ed')

        # 进行时 -ing
        if verb.endswith('e') and not verb.endswith('ee'):
            forms.append(verb[:-1] + 'ing')
        elif verb.endswith('ie'):
            forms.append(verb[:-2] + 'ying')
        else:
            forms.append(verb + 'ing')

        return forms

    def _normalize_verb(self, task: str) -> str:
        """
        标准化动词：去除RAW:前缀，提取核心动词，词形还原。
        """
        if not task:
            return ''

        verb = task
        if verb.startswith('RAW:'):
            verb = verb[4:]

        # 提取第一个词
        verb = verb.split()[0] if verb else ''
        verb = verb.lower().strip()

        # 简单词形还原
        if verb.endswith('ing') and len(verb) > 5:
            if verb[-4] == verb[-5]:
                verb = verb[:-4]
            else:
                verb = verb[:-3]
        elif verb.endswith('ed') and len(verb) > 4:
            if verb[-3] == verb[-4]:
                verb = verb[:-3]
            elif verb.endswith('ied'):
                verb = verb[:-3] + 'y'
            else:
                verb = verb[:-2] if not verb.endswith('eed') else verb[:-1]
        elif verb.endswith('es') and len(verb) > 4:
            if verb.endswith('ies'):
                verb = verb[:-3] + 'y'
            elif verb.endswith(('shes', 'ches', 'xes', 'sses', 'zes')):
                verb = verb[:-2]
            else:
                verb = verb[:-1]
        elif verb.endswith('s') and len(verb) > 3 and not verb.endswith('ss'):
            verb = verb[:-1]

        return verb

    def _resolve_coverage_weight(self, coverage_value: float) -> Tuple[float, bool]:
        coverage = max(0.0, min(float(coverage_value), 1.0))
        policy = self.object_coverage_policy
        threshold = self.object_coverage_threshold

        if policy == "off":
            return 1.0, False
        if policy == "hard_filter":
            if coverage < threshold:
                return 0.0, True
            return 1.0, False

        if threshold <= 1e-9:
            return 1.0, False
        if coverage >= threshold:
            return 1.0, False

        scaled = coverage / threshold
        floor = self.object_coverage_soft_floor
        weight = floor + (1.0 - floor) * scaled
        return max(0.0, min(weight, 1.0)), False

    def _normalize_task_for_counts(self, text: str) -> str:
        if self.pair_normalization_mode == "raw":
            return _normalize_space_text(text)
        return _normalize_task_concept(text)

    def _normalize_object_for_counts(self, text: str) -> str:
        if self.pair_normalization_mode == "raw":
            return _normalize_space_text(text)
        return _normalize_object_concept(text)

    def _prepare_effective_rpus(self, rpu_list: List[Dict]) -> List[Dict]:
        if not rpu_list:
            return []

        effective = []
        for rpu in rpu_list:
            task_raw = rpu.get('task_core') or rpu.get('task') or ""
            object_raw = rpu.get('object_core') or rpu.get('object') or ""
            modifier_raw = rpu.get('modifier')

            task_norm = self._normalize_task_for_counts(task_raw)
            object_norm = self._normalize_object_for_counts(object_raw)
            modifier_norm = _normalize_modifier_text(modifier_raw)

            if not task_norm or not object_norm:
                continue

            coverage = _safe_float(rpu.get('object_coverage'), 1.0)
            if coverage <= 0.0:
                coverage = _safe_float(rpu.get('coverage'), 1.0)
            coverage_weight, dropped = self._resolve_coverage_weight(coverage)
            if dropped:
                continue

            effective.append(
                {
                    "task": task_norm,
                    "object": object_norm,
                    "task_norm": task_norm,
                    "object_norm": object_norm,
                    "modifier": modifier_norm or None,
                    "modifier_norm": modifier_norm or None,
                    "aspect": _normalize_space_text(rpu.get('aspect') or ""),
                    "object_coverage": max(0.0, min(coverage, 1.0)),
                    "coverage_weight": coverage_weight,
                }
            )

        return effective

    @staticmethod
    def _build_synergy_term_sets(effective_rpus: List[Dict]) -> Tuple[Set[str], Set[str]]:
        task_object_terms = set()
        object_only_terms = set()
        for rpu in effective_rpus:
            t = rpu.get("task_norm") or rpu.get("task")
            o = rpu.get("object_norm") or rpu.get("object")
            if not t or not o:
                continue
            task_object_terms.add(f"SY_TO:T:{t}|O:{o}")
            object_only_terms.add(f"SY_O:{o}")
        return task_object_terms, object_only_terms

    def _select_synergy_terms_for_state(self, task_object_terms: Set[str], object_only_terms: Set[str]) -> List[str]:
        if self.synergy_granularity_mode == "object_only":
            return sorted(object_only_terms)
        if self.synergy_granularity_mode == "hybrid":
            return sorted(set(task_object_terms) | set(object_only_terms))
        return sorted(task_object_terms)

    @staticmethod
    def _format_synergy_token(token: str) -> str:
        if token.startswith("SY_TO:T:"):
            body = token[len("SY_TO:T:"):]
            parts = body.split("|O:", 1)
            if len(parts) == 2:
                return f"T:{parts[0]}|O:{parts[1]}"
            return body
        if token.startswith("SY_O:"):
            return f"O:{token[len('SY_O:'):]}"
        return token

    def _compute_synergy_with_granularity(
        self,
        task_object_terms: Set[str],
        object_only_terms: Set[str],
        top_k: int,
    ) -> Tuple[float, Optional[str], Dict[str, float]]:
        task_terms = sorted(task_object_terms)
        object_terms = sorted(object_only_terms)

        score_task, top_task = self.get_synergy(task_terms, top_k=top_k) if len(task_terms) >= 2 else (0.0, [])
        score_object, top_object = self.get_synergy(object_terms, top_k=top_k) if len(object_terms) >= 2 else (0.0, [])

        mode = self.synergy_granularity_mode
        trigger = None

        if mode == "object_only":
            final_score = score_object
            if top_object:
                trigger = (
                    f"{self._format_synergy_token(top_object[0][1])} + "
                    f"{self._format_synergy_token(top_object[0][2])}"
                )
        elif mode == "hybrid":
            w_obj = self.synergy_blend_object_weight
            final_score = (1.0 - w_obj) * score_task + w_obj * score_object
            task_component = (1.0 - w_obj) * score_task
            object_component = w_obj * score_object
            if top_task and (task_component >= object_component or not top_object):
                trigger = (
                    f"[TO] {self._format_synergy_token(top_task[0][1])} + "
                    f"{self._format_synergy_token(top_task[0][2])}"
                )
            elif top_object:
                trigger = (
                    f"[O] {self._format_synergy_token(top_object[0][1])} + "
                    f"{self._format_synergy_token(top_object[0][2])}"
                )
        else:
            final_score = score_task
            if top_task:
                trigger = (
                    f"{self._format_synergy_token(top_task[0][1])} + "
                    f"{self._format_synergy_token(top_task[0][2])}"
                )

        return max(0.0, final_score), trigger, {
            "task_object": float(score_task),
            "object_only": float(score_object),
        }

    @staticmethod
    def _infer_domain_proxy(effective_rpus: List[Dict]) -> str:
        if not effective_rpus:
            return "unknown"
        counts = defaultdict(int)
        for rpu in effective_rpus:
            task = str(rpu.get("task_norm") or rpu.get("task") or "").strip().lower()
            if not task:
                continue
            token = re.split(r"[^a-z0-9_]+", task)[0]
            if token:
                counts[token] += 1
        if not counts:
            return "unknown"
        return max(counts.items(), key=lambda item: item[1])[0]

    def _build_pca_bias_diagnostic(self, year_results: List[Dict], year: str) -> Optional[Dict]:
        if not self.pca_bias_diagnostic_enabled:
            return None
        if not year_results:
            return None

        global_scores = np.asarray(
            [float(r.get("score_v2", 0.0)) for r in year_results],
            dtype=np.float64,
        )
        if global_scores.size == 0:
            return None
        global_p70 = float(np.percentile(global_scores, 70))

        grouped = defaultdict(list)
        for rec in year_results:
            grouped[str(rec.get("domain_proxy", "unknown"))].append(float(rec.get("score_v2", 0.0)))

        rows = []
        for domain, values in grouped.items():
            if len(values) < self.pca_bias_min_group_size:
                continue
            arr = np.asarray(values, dtype=np.float64)
            domain_p70 = float(np.percentile(arr, 70))
            threshold_shift = domain_p70 - global_p70
            selected_by_global = float(np.mean(arr >= global_p70))
            rows.append(
                {
                    "domain_proxy": domain,
                    "count": int(arr.size),
                    "score_mean": float(arr.mean()),
                    "score_p70": domain_p70,
                    "threshold_shift_pp": float(threshold_shift),
                    "global_threshold_selection_rate": selected_by_global,
                }
            )

        rows.sort(key=lambda item: item["count"], reverse=True)
        rows = rows[: self.pca_bias_top_groups]

        max_abs_shift = max((abs(item["threshold_shift_pp"]) for item in rows), default=0.0)
        return {
            "year": str(year),
            "global_score_p70": global_p70,
            "min_group_size": self.pca_bias_min_group_size,
            "groups_analyzed": len(rows),
            "max_abs_threshold_shift_pp": float(max_abs_shift),
            "alert_shift_pp": float(self.pca_bias_alert_shift_pp),
            "risk_alert": bool(max_abs_shift >= self.pca_bias_alert_shift_pp),
            "group_rows": rows,
        }

    def _build_synergy_granularity_diagnostic(self, year_results: List[Dict], year: str) -> Optional[Dict]:
        if not self.synergy_granularity_ab_enabled:
            return None
        if not year_results:
            return None

        to_scores = np.asarray(
            [float(r.get("synergy_task_object", 0.0)) for r in year_results],
            dtype=np.float64,
        )
        obj_scores = np.asarray(
            [float(r.get("synergy_object_only", 0.0)) for r in year_results],
            dtype=np.float64,
        )
        if to_scores.size == 0 or obj_scores.size == 0:
            return None

        n = int(to_scores.size)
        top_share = self.synergy_granularity_ab_top_share
        top_n = max(1, int(n * top_share))
        to_idx = set(np.argsort(to_scores)[-top_n:])
        obj_idx = set(np.argsort(obj_scores)[-top_n:])
        inter = len(to_idx & obj_idx)
        union = len(to_idx | obj_idx)
        overlap = inter / top_n if top_n > 0 else 0.0
        jaccard = inter / union if union > 0 else 1.0

        corr = float(np.corrcoef(to_scores, obj_scores)[0, 1]) if n > 1 else 1.0
        if not np.isfinite(corr):
            corr = 0.0

        if overlap < 0.4:
            recommended_mode = "hybrid"
            reason = "task_object 与 object_only 头部重合较低，建议折中融合。"
        elif float(np.mean(to_scores)) >= float(np.mean(obj_scores)) * 1.05:
            recommended_mode = "task_object"
            reason = "task_object 贡献更强且与 object_only 一致性可接受。"
        else:
            recommended_mode = "object_only"
            reason = "object_only 更稳健，适合降低 task 粒度碎片化影响。"

        return {
            "year": str(year),
            "top_share": float(top_share),
            "top_n": int(top_n),
            "head_overlap_ratio": float(overlap),
            "head_jaccard": float(jaccard),
            "pearson_corr": float(corr),
            "task_object_mean": float(np.mean(to_scores)),
            "object_only_mean": float(np.mean(obj_scores)),
            "task_object_p90": float(np.percentile(to_scores, 90)),
            "object_only_p90": float(np.percentile(obj_scores, 90)),
            "recommended_mode": recommended_mode,
            "recommendation_reason": reason,
        }

    def get_verb_weight(self, task: str) -> float:
        """
        获取动词的创新性权重（IDF自适应 + 锚点微调）。

        逻辑：
        1. 如果动词是锚点词，返回固定权重
        2. 否则，根据动词的IDF值计算权重：
           weight = idf_min + (idf_max - idf_min) * normalized_idf
           其中 normalized_idf 基于当前语料库的IDF分布

        Args:
            task: 任务/动词字符串

        Returns:
            float: 动词权重 (0.0 - 1.0)
        """
        if not task:
            return 0.5

        # 提取原始动词：去 RAW: 前缀，取第一个词，转小写
        verb = task
        if verb.startswith('RAW:'):
            verb = verb[4:]
        verb = verb.split()[0].lower().strip() if verb else ''

        if not verb:
            return 0.5

        # 1. 检查是否为锚点词（锚点已包含各种变形）
        if verb in self.verb_anchors:
            return self.verb_anchors[verb]

        # 2. 使用IDF计算权重
        # 注意：IDF tracker 存储的是原始 task 字符串（如 RAW:shows），
        # 而非标准化后的形式（show），所以必须用原始字符串查询
        idf = self.task_idf_tracker.get_idf(task)

        # 如果IDF数据不足，返回中间值
        if self.task_idf_tracker.total_docs < 1000:
            return 0.5

        # 使用缓存的IDF分布范围（避免每次重新计算）
        idf_min_val, idf_max_val = self._get_idf_range()
        idf_range = idf_max_val - idf_min_val

        if idf_range < 0.1:
            return 0.5

        # 归一化到 [0, 1]
        normalized = (idf - idf_min_val) / idf_range
        normalized = max(0.0, min(1.0, normalized))

        # 映射到权重范围
        weight = self.idf_weight_min + (self.idf_weight_max - self.idf_weight_min) * normalized
        return weight

    def _get_idf_range(self) -> Tuple[float, float]:
        """
        获取当前IDF分布的min/max，带缓存。
        缓存在Phase 1开始时通过 precompute_idf_range() 初始化，
        Phase 1期间（read-only）不会失效。
        """
        docs = self.task_idf_tracker.total_docs
        # 缓存命中
        if hasattr(self, '_idf_range_cache') and hasattr(self, '_idf_range_cache_docs'):
            return self._idf_range_cache

        # 首次计算或缓存未初始化 - 使用默认值
        # 正常情况下应该通过 precompute_idf_range() 预先初始化
        return (2.0, 12.0)

    def precompute_idf_range(self) -> None:
        """
        预计算IDF范围。应在Phase 1开始前调用（当有历史数据时）。
        使用单次遍历计算min/max，避免创建大型列表。
        """
        docs = self.task_idf_tracker.total_docs
        if docs < 1000:
            # 数据量不足，使用默认值
            self._idf_range_cache = (2.0, 12.0)
            self._idf_range_cache_docs = docs
            return

        # 单次遍历计算min/max（避免创建百万级列表）
        min_idf = float('inf')
        max_idf = float('-inf')
        count = 0
        log2_total = math.log2(docs)

        for t, df in self.task_idf_tracker.task_doc_freq.items():
            if df >= 5:
                # IDF = log2(total_docs / (df + 1))
                idf = max(0.0, log2_total - math.log2(df + 1))
                if idf < min_idf:
                    min_idf = idf
                if idf > max_idf:
                    max_idf = idf
                count += 1

        if count > 0:
            result = (min_idf, max_idf)
        else:
            result = (2.0, 12.0)

        self._idf_range_cache = result
        self._idf_range_cache_docs = docs
        logger.info(f"IDF range precomputed: [{result[0]:.2f}, {result[1]:.2f}] from {count} tasks")

    def get_peak_novelty(self, task: str, obj: str) -> float:
        """
        Calculate Peak Novelty: Surprisal of the Task-Object pair.
        S_peak = -log2( P(Task, Object) )
        """
        if not task or not obj:
            return 0.0

        # Laplace Smoothing: (count + 1) / (total + vocab)
        count = self.pair_counts.get((task, obj), 0)
        prob = (count + 1) / (self.total_docs + self.vocab_size_estimate)

        # Use cached log2 computation if available
        if self.cache:
            return -self.cache.get_log2(prob)
        else:
            return -math.log2(prob)

    def get_synergy(self, rpus: List[str], top_k: int = 3) -> Tuple[float, List[Tuple[float, str, str]]]:
        """
        Calculate Synergy Novelty: Top-k Mean PMI of intra-paper RPU combinations.
        Returns: (top_k_mean_score, top_items_list)
        S_synergy = Mean(Top-k PMI(rpu_i, rpu_j))
        PMI(x, y) = log2( P(x, y) / (P(x) * P(y)) )
        
        Applies SYNERGY_MIN_SUPPORT=2 filter to reduce noise from singleton concepts.
        """
        if len(rpus) < 2:
            return 0.0, []
            
        unique_rpus = sorted(list(set(rpus)))
        
        # Apply SYNERGY_MIN_SUPPORT filter to reduce noise from rare concepts
        # 只有在历史中出现至少SYNERGY_MIN_SUPPORT次的概念才参与协同计算
        filtered_rpus = []
        for rpu in unique_rpus:
            count = self.term_counts.get(rpu, 0)
            self.modifier_filter_stats['total_synergy_concepts_processed'] += 1
            
            if count >= self.SYNERGY_MIN_SUPPORT:
                filtered_rpus.append(rpu)
            else:
                self.modifier_filter_stats['synergy_concepts_filtered'] += 1
                
        if len(filtered_rpus) < 2:
            return 0.0, []
            
        pmi_list = []
        
        # Get state identifier for PMI caching
        state_id = self.cache.get_state_id(self) if self.cache else None
        
        for i in range(len(filtered_rpus)):
            for j in range(i + 1, len(filtered_rpus)):
                u = filtered_rpus[i]
                v = filtered_rpus[j]
                
                # Use cached PMI computation if available
                if self.cache and state_id:
                    def compute_pmi():
                        return self._compute_pmi_uncached(u, v)
                    pmi = self.cache.get_pmi(state_id, u, v, compute_pmi)
                else:
                    pmi = self._compute_pmi_uncached(u, v)
                    
                pmi_list.append((pmi, u, v))
                    
        if not pmi_list:
            return 0.0, []

        # Sort descending
        pmi_list.sort(key=lambda x: x[0], reverse=True)

        # Top-k Mean
        top_items = pmi_list[:top_k]
        mean_score = sum(item[0] for item in top_items) / len(top_items)

        # Clamp to non-negative: negative PMI means anti-correlation, not innovation
        mean_score = max(0.0, mean_score)

        return mean_score, top_items
        
    def _compute_pmi_uncached(self, u: str, v: str) -> float:
        """
        Compute PMI without caching (internal helper method).
        
        Args:
            u: First term
            v: Second term
            
        Returns:
            float: PMI value
        """
        # Counts
        count_uv = self.cooc_counts.get((u, v), 0)
        count_u = self.term_counts.get(u, 0)
        count_v = self.term_counts.get(v, 0)
        
        # Probabilities (Smoothed)
        p_uv = (count_uv + 1) / (self.total_docs + self.vocab_size_estimate**2)
        p_u = (count_u + 1) / (self.total_docs + self.vocab_size_estimate)
        p_v = (count_v + 1) / (self.total_docs + self.vocab_size_estimate)
        
        # Use cached log2 computation if available
        if self.cache:
            return self.cache.get_log2(p_uv / (p_u * p_v))
        else:
            return math.log2(p_uv / (p_u * p_v))

    def get_modifier_bonus(self, core: str, modifier: str) -> float:
        """
        Calculate Modifier Bonus: Conditional Surprisal of Modifier given Core.
        S_bonus = -log2( P(Modifier | Core) )
        Used to detect "Old Core + New Modifier".
        
        Integrates with ModifierFilter to skip high-frequency modifiers that add noise.
        Tracks filtering statistics for performance monitoring.
        """
        if not core or not modifier:
            return 0.0
            
        # Track total modifier bonus calls for statistics
        self.modifier_filter_stats['total_modifier_bonus_calls'] += 1
            
        # Apply modifier filtering if enabled
        if self.modifier_filter and self.modifier_filter.should_filter_modifier(modifier):
            self.modifier_filter_stats['filtered_modifier_calls'] += 1
            return 0.0  # Skip high-frequency modifiers
            
        # P(M | C) = Count(M, C) / Count(C)
        count_mc = self.mod_given_core_counts.get((core, modifier), 0)
        count_c = self.core_counts_for_mod.get(core, 0)
        
        # If Core is rare (count_c is low), bonus should be low (we want OLD core)
        # However, the formula -log(P) gives high surprise for rare events.
        # We need to balance this. If Core is new, it's just standard Peak Novelty.
        # This metric specifically highlights ESTABLISHED cores with UNSEEN modifiers.
        
        # Smoothing - 这是经验值，用于要求核心概念的稳定性
        prob_given_core = (count_mc + 1) / (count_c + self.core_stability_smoothing) # Higher smoothing for Core to require stability
        
        # Use cached log2 computation if available
        if self.cache:
            return -self.cache.get_log2(prob_given_core)
        else:
            return -math.log2(prob_given_core)

    def update(self, tasks: List[str], objects: List[str], modifiers: List[str], all_rpus: List[str]):
        """
        Update global state with the contents of the current paper.
        """
        self.total_docs += 1
        
        # 1. Update Term Counts
        for t in tasks: self.term_counts[t] += 1
        for o in objects: self.term_counts[o] += 1
        for m in modifiers: self.term_counts[m] += 1 # Optional if needed globally
        
        # 2. Update Pair Counts (Task-Object)
        # Assuming Task and Object are aligned by index or we take Cartesian product?
        # Requirement says: (Core_Task, Core_Object) pairs.
        # In RPU structure, one RPU has one Task and one Object.
        # So we iterate through RPUs.
        # NOTE: The input `tasks` and `objects` here are flattened lists. 
        # Ideally we should pass list of RPUs objects to be precise.
        # Refactoring `update` signature to take RPUs directly would be better, but let's handle via logic below.
        pass # Implemented in specific update_from_paper method

    def update_from_paper(self, rpu_list: List[Dict]):
        """
        Update state from a list of RPU dictionaries of a single paper.
        RPU Dict: {'task': ..., 'object': ..., 'modifier': ...}
        """
        effective_rpus = self._prepare_effective_rpus(rpu_list)
        if not effective_rpus:
            return

        self.total_docs += 1
        
        # Sets to avoid double counting within same paper (Bernoulli model vs Multinomial)
        # Usually for IDF-like metrics we use binary occurrence (set).
        seen_terms = set()
        seen_pairs = set()
        seen_mods = set()
        
        task_object_pairs = set()
        
        # Collect modifiers for frequency tracking
        paper_modifiers = []
        
        for rpu in effective_rpus:
            t = rpu.get('task_norm') or rpu.get('task')
            o = rpu.get('object_norm') or rpu.get('object')
            m = rpu.get('modifier_norm') or rpu.get('modifier')
            
            # Collect modifier for frequency tracking
            if m:
                paper_modifiers.append(m)
            
            if t and o:
                task_object_pairs.add((t, o))
                
                # Peak Novelty Pairs
                pair = (t, o)
                if pair not in seen_pairs:
                    self.pair_counts[pair] += 1
                    seen_pairs.add(pair)
            
            # Modifier Conditional
            # We treat "Core" as the Task-Object pair or just Object?
            # Usually Core = Object in many contexts, or Task+Object.
            # Let's assume Core = Object for modifier attachment (e.g. "Efficient Transformer")
            if o and m:
                mod_pair = (o, m)
                if mod_pair not in seen_mods:
                    self.mod_given_core_counts[mod_pair] += 1
                    self.core_counts_for_mod[o] += 1
                    seen_mods.add(mod_pair)
            
            if t: seen_terms.add(t)
            if o: seen_terms.add(o)
            
        # Update modifier filter frequencies
        if self.modifier_filter:
            self.modifier_filter.update_frequencies(paper_modifiers)
            
        # Update Term Counts
        for term in seen_terms:
            self.term_counts[term] += 1

        # Update Synergy Co-occurrence
        task_object_terms, object_only_terms = self._build_synergy_term_sets(effective_rpus)
        sorted_rpus = self._select_synergy_terms_for_state(task_object_terms, object_only_terms)
        for i in range(len(sorted_rpus)):
            for j in range(i + 1, len(sorted_rpus)):
                self.cooc_counts.increment((sorted_rpus[i], sorted_rpus[j]), 1)

        # Update RPU counts for synergy P(x)
        for r in sorted_rpus:
            self.term_counts[r] += 1

    def update_modifier_filter_at_year_boundary(self, year: str) -> None:
        """
        Update modifier filter threshold at year boundaries for temporal consistency.
        
        Args:
            year: Current year being processed
        """
        if self.modifier_filter:
            self.modifier_filter.update_threshold_at_year_boundary(year)
            
    def get_filtering_integration_stats(self) -> Dict[str, any]:
        """
        Get comprehensive statistics about modifier filtering integration.
        
        Returns:
            Dict with integration statistics and performance metrics
        """
        stats = self.modifier_filter_stats.copy()
        
        # Calculate derived metrics
        if stats['total_modifier_bonus_calls'] > 0:
            stats['modifier_filter_rate'] = stats['filtered_modifier_calls'] / stats['total_modifier_bonus_calls']
        else:
            stats['modifier_filter_rate'] = 0.0
            
        if stats['total_synergy_concepts_processed'] > 0:
            stats['synergy_filter_rate'] = stats['synergy_concepts_filtered'] / stats['total_synergy_concepts_processed']
        else:
            stats['synergy_filter_rate'] = 0.0
        
        # Add modifier filter stats if available
        if self.modifier_filter:
            modifier_filter_stats = self.modifier_filter.get_filtering_stats()
            stats['modifier_filter_details'] = modifier_filter_stats
        else:
            stats['modifier_filter_details'] = None
            
        # Add synergy filter configuration
        stats['synergy_min_support'] = self.SYNERGY_MIN_SUPPORT
        
        return stats
        
    def reset_filtering_integration_stats(self) -> None:
        """
        Reset filtering integration statistics while preserving filter state.
        Useful for performance measurement comparisons.
        """
        self.modifier_filter_stats = {
            'total_modifier_bonus_calls': 0,
            'filtered_modifier_calls': 0,
            'synergy_concepts_filtered': 0,
            'total_synergy_concepts_processed': 0
        }
        
    def process_year_atomic(self, year_papers: List[Tuple[str, List[Dict]]], year: str) -> List[Dict]:
        """
        Process all papers from a year using Year-Atomic Update pattern.
        
        This method implements the core Year-Atomic Update pattern that transforms
        the Innovation Engine from Stream Update to Year-Atomic Update. It processes
        all papers from a year using consistent historical state, then atomically
        merges the results.
        
        Architecture:
        1. Calculation Phase: Historical state remains read-only, all calculations
           use consistent state from before the year
        2. Update Phase: Atomic merge of year buffer into historical state
        
        Args:
            year_papers: List of (paper_id, rpu_list) tuples for the year
            year: Year being processed (for logging and cache management)
            
        Returns:
            List[Dict]: Innovation signals for all papers in the year
            
        Requirements Addressed:
        - 1.1: Year-Atomic Processing with read-only historical state during calculation
        - 1.2: Atomic merge operations via YearBuffer
        - 1.3: Temporal causality preservation
        - 1.5: Performance optimization through consistent state access
        - 4.1, 4.2, 4.5: Comprehensive performance metrics collection
        """
        if not year_papers:
            logger.warning(f"No papers to process for year {year}")
            return []
            
        logger.info(f"Starting Year-Atomic processing for {year}: {len(year_papers)} papers")
        
        # ============================================================
        # Error Handling Context: Monitor system health and handle errors
        # ============================================================
        components = {
            'cache': self.cache,
            'filter': self.modifier_filter,
            'buffer': None  # Will be set when buffer is created
        }
        
        # ============================================================
        # Performance Monitoring: Start Year Timing
        # ============================================================
        if self.performance_metrics:
            self.performance_metrics.start_year_timing(year)
            # 采样年度开始时的内存使用
            self.performance_metrics.sample_memory_usage(year, "year_start")
        
        start_time = time.time()
        
        # ============================================================
        # Phase 1: Calculation Phase (Read-Only Historical State)
        # ============================================================
        
        # Create year buffer for accumulating counts without updating global state
        year_buffer = YearBuffer(synergy_granularity_mode=self.synergy_granularity_mode)
        
        # Update components dictionary with the buffer
        components['buffer'] = year_buffer
        
        # Store results for all papers in the year
        year_results = []
        year_effective_papers: List[Tuple[str, List[Dict]]] = []
        year_feature_snapshots: List[np.ndarray] = []
        
        # Get current state identifier for cache keys
        state_id = None
        if self.cache:
            state_id = self.cache.get_state_id(self)
            
        # Update modifier filter at year boundary for temporal consistency
        self.update_modifier_filter_at_year_boundary(year)
        
        # 预计算IDF范围（Phase 1期间历史状态不变，只需计算一次）
        self.precompute_idf_range()

        logger.info(f"Phase 1: Calculating innovation signals using historical state (read-only)")
        calculation_phase_start = time.time()

        # 统计RPU数量用于性能监控
        total_rpus_in_year = sum(len(rpu_list) for _, rpu_list in year_papers if rpu_list)

        # Progress tracking
        total_papers = len(year_papers)
        progress_interval = max(10000, total_papers // 20)  # Report every 5% or 10k papers
        last_progress_time = time.time()

        # DEBUG: 性能分析计时器
        debug_timing = {'peak': 0, 'verb_weight': 0, 'modifier': 0, 'synergy': 0, 'feature': 0, 'transform': 0, 'buffer': 0}
        debug_count = 0

        for idx, (paper_id, rpu_list) in enumerate(year_papers):
            # DEBUG: 前1000篇详细计时
            do_debug = idx < 1000

            # Progress reporting (改为每1000篇报告一次用于调试)
            if idx > 0 and idx % 1000 == 0 and idx <= 10000:
                elapsed = time.time() - calculation_phase_start
                papers_per_sec = idx / elapsed if elapsed > 0 else 0
                print(f"    [DEBUG] {idx:,} papers, {papers_per_sec:.0f}/s, "
                      f"peak={debug_timing['peak']/debug_count*1000:.2f}ms, "
                      f"verb_w={debug_timing['verb_weight']/debug_count*1000:.2f}ms, "
                      f"synergy={debug_timing['synergy']/debug_count*1000:.2f}ms, "
                      f"feature={debug_timing['feature']/debug_count*1000:.2f}ms", flush=True)

            if idx > 0 and idx % progress_interval == 0:
                elapsed = time.time() - calculation_phase_start
                papers_per_sec = idx / elapsed if elapsed > 0 else 0
                remaining = total_papers - idx
                eta = remaining / papers_per_sec if papers_per_sec > 0 else 0
                print(f"    Phase 1 进度: {idx:,}/{total_papers:,} ({100*idx/total_papers:.1f}%) | "
                      f"{papers_per_sec:.0f} 篇/秒 | ETA: {eta:.0f}s", flush=True)
            # ========================================
            # Calculate Innovation Signals (Read-Only)
            # ========================================
            
            # Initialize default values for papers with no valid RPUs
            final_s_peak = 0.0
            final_s_synergy = 0.0
            final_s_bonus = 0.0
            synergy_task_object = 0.0
            synergy_object_only = 0.0
            peak_trigger = None
            synergy_trigger = None
            bonus_trigger = None
            domain_proxy = "unknown"
            paper_coverage_weight = 1.0

            effective_rpus = self._prepare_effective_rpus(rpu_list) if rpu_list else []

            if effective_rpus:
                year_effective_papers.append((paper_id, effective_rpus))
                coverage_weights = [float(r.get("coverage_weight", 1.0)) for r in effective_rpus]
                paper_coverage_weight = (
                    float(sum(coverage_weights) / len(coverage_weights))
                    if coverage_weights else 1.0
                )

                # Extract terms for signal calculation
                s_peak_list = []
                s_bonus_list = []

                _t0 = time.time() if do_debug else 0
                for rpu in effective_rpus:
                    t = rpu.get('task_norm') or rpu.get('task')
                    o = rpu.get('object_norm') or rpu.get('object')
                    m = rpu.get('modifier_norm') or rpu.get('modifier')
                    coverage_weight = float(rpu.get("coverage_weight", 1.0))

                    if t and o:
                        # Peak Novelty: P(Task, Object) - uses historical state only
                        # 应用动词创新性权重（配置驱动）
                        s_peak_raw = self.get_peak_novelty(t, o)
                        verb_w = self.get_verb_weight(t)
                        s_peak = s_peak_raw * verb_w * coverage_weight
                        s_peak_list.append((s_peak, t, o))

                        # Modifier Bonus: P(Modifier | Object_Core) - uses historical state only
                        if m:
                            s_bonus = self.get_modifier_bonus(o, m) * coverage_weight
                            s_bonus_list.append((s_bonus, o, m))
                if do_debug:
                    debug_timing['peak'] += time.time() - _t0

                # Aggregation for Peak Novelty (Top-k Mean)
                if s_peak_list:
                    s_peak_list.sort(key=lambda x: x[0], reverse=True)
                    top_k_peak = s_peak_list[:self.top_k_signals]  # 使用配置的Top-K参数
                    final_s_peak = sum(item[0] for item in top_k_peak) / len(top_k_peak)
                    peak_trigger = f"{top_k_peak[0][1]} - {top_k_peak[0][2]}"

                # Aggregation for Modifier Bonus (Top-k Mean)
                if s_bonus_list:
                    s_bonus_list.sort(key=lambda x: x[0], reverse=True)
                    top_k_bonus = s_bonus_list[:self.top_k_signals]  # 使用配置的Top-K参数
                    final_s_bonus = sum(item[0] for item in top_k_bonus) / len(top_k_bonus)
                    bonus_trigger = f"{top_k_bonus[0][2]} | {top_k_bonus[0][1]}"  # Mod | Core

                # Synergy (Top-k Mean) - uses historical state only
                _t0 = time.time() if do_debug else 0
                task_object_terms, object_only_terms = self._build_synergy_term_sets(effective_rpus)
                synergy_score, synergy_trigger, synergy_components = self._compute_synergy_with_granularity(
                    task_object_terms,
                    object_only_terms,
                    top_k=self.top_k_signals,
                )
                final_s_synergy = synergy_score * paper_coverage_weight
                synergy_task_object = float(synergy_components.get("task_object", 0.0)) * paper_coverage_weight
                synergy_object_only = float(synergy_components.get("object_only", 0.0)) * paper_coverage_weight
                domain_proxy = self._infer_domain_proxy(effective_rpus)
                if do_debug:
                    debug_timing['synergy'] += time.time() - _t0

            # ========================================
            # V2: Extract features and compute innovation magnitude
            # ========================================
            _t0 = time.time() if do_debug else 0
            feature_vec = (
                self.feature_extractor.extract_features(effective_rpus)
                if effective_rpus else np.zeros(FeatureExtractor.FEATURE_DIM)
            )
            if do_debug:
                debug_timing['feature'] += time.time() - _t0

            _t0 = time.time() if do_debug else 0
            innovation_magnitude, v2_degraded, v2_degraded_reason = self.regular_space_model.transform(feature_vec)
            if do_debug:
                debug_timing['transform'] += time.time() - _t0
                debug_count += 1

            if effective_rpus:
                year_feature_snapshots.append(feature_vec.copy())

            # Store result for this paper (even if RPU list was empty)
            result = {
                "paper_id": paper_id,
                "s_peak": round(final_s_peak, 4),
                "peak_trigger": peak_trigger,
                "s_synergy": round(final_s_synergy, 4),
                "synergy_trigger": synergy_trigger,
                "synergy_task_object": round(synergy_task_object, 4),
                "synergy_object_only": round(synergy_object_only, 4),
                "s_bonus": round(final_s_bonus, 4),
                "bonus_trigger": bonus_trigger,
                "domain_proxy": domain_proxy,
                "paper_coverage_weight": round(paper_coverage_weight, 4),
                "raw_rpu_count": int(len(rpu_list) if rpu_list else 0),
                "effective_rpu_count": int(len(effective_rpus)),
                "innovation_magnitude": round(innovation_magnitude, 4),
                "v2_degraded": v2_degraded,
                "v2_degraded_reason": v2_degraded_reason,
                "_feature_vec": feature_vec,  # temporary, removed after scoring
            }
            year_results.append(result)
            
            # ========================================
            # Accumulate into Year Buffer (No Global State Update)
            # ========================================
            
            # Accumulate counts into buffer (only if RPU list is not empty)
            if effective_rpus:
                year_buffer.accumulate_from_paper(effective_rpus)
        
        calculation_time = time.time() - calculation_phase_start

        # ============================================================
        # V2: Compute score_v2 (percentile normalization) and total_score_v2
        # ============================================================
        magnitudes = [r['innovation_magnitude'] for r in year_results]
        s_peaks = [r['s_peak'] for r in year_results]
        s_synergies = [r['s_synergy'] for r in year_results]
        s_bonuses = [r['s_bonus'] for r in year_results]

        # Compute stds for signal combining (avoid div by zero)
        stds = {
            's_peak': float(np.std(s_peaks)) if s_peaks else 1.0,
            's_synergy': float(np.std(s_synergies)) if s_synergies else 1.0,
            's_bonus': float(np.std(s_bonuses)) if s_bonuses else 1.0,
            'score_v2': float(np.std(magnitudes)) if magnitudes else 1.0,
        }
        # Replace zero stds with 1.0 to avoid division by zero
        for k in stds:
            if stds[k] < 1e-8:
                stds[k] = 1.0

        # Check variance constraint
        self.regular_space_model.check_variance(magnitudes, year)

        # Batch compute percentile ranks (O(n log n) instead of O(n² log n))
        percentile_ranks = RegularSpaceModel.percentile_rank_batch(magnitudes)

        # Update results with score_v2 and total_score_v2
        for i, r in enumerate(year_results):
            r['score_v2'] = round(percentile_ranks[i], 2)
            r['total_score_v2'] = round(
                SignalCombiner.combine(r['s_peak'], r['s_synergy'], r['s_bonus'], r['score_v2'], stds),
                4
            )
            # Remove temporary feature vector
            del r['_feature_vec']
        
        # ============================================================
        # Performance Monitoring: Calculation Phase Complete
        # ============================================================
        if self.performance_metrics:
            self.performance_metrics.record_phase_timing("calculation", calculation_time)
            # 采样计算阶段完成时的内存使用
            self.performance_metrics.sample_memory_usage(year, "calculation_complete")
            
            # 记录缓存内存使用
            if self.cache:
                cache_stats = self.cache.get_cache_stats()
                self.performance_metrics.record_cache_memory(year, cache_stats['total_memory_bytes'])
        
        logger.info(f"Phase 1 completed: {len(year_results)} papers processed in {calculation_time:.2f}s")
        
        # ============================================================
        # Phase 2: Update Phase (Atomic Merge)
        # ============================================================
        
        logger.info(f"Phase 2: Atomically merging year buffer into historical state")
        merge_start_time = time.time()
        
        # Validate buffer before merge
        success, validation_result = self.error_handler.safe_execute(
            year_buffer.validate_buffer
        )
        
        if not success or not validation_result:
            logger.error(f"Year buffer validation failed for year {year}")
            # Try to handle the buffer error
            if self.error_handler.handle_buffer_error(year_buffer, 
                                                    Exception("Buffer validation failed"), 
                                                    "validation"):
                logger.info("Buffer validation error handled successfully")
            else:
                raise ValueError(f"Invalid year buffer state for year {year}")
        
        # Update modifier filter frequencies from buffer with error handling
        if self.modifier_filter:
            success, _ = self.error_handler.safe_execute(
                year_buffer.update_modifier_filter_from_buffer, self
            )
            if not success:
                logger.warning("Failed to update modifier filter from buffer, continuing...")
        
        # Atomic merge: Transfer all buffered counts to global state with error handling
        success, _ = self.error_handler.safe_execute(
            year_buffer.merge_into_state, self
        )
        
        if not success:
            logger.error(f"Failed to merge year buffer for year {year}")
            raise ValueError(f"Buffer merge failed for year {year}")

        # ============================================================
        # V2: Update TaskIDFTracker and RegularSpaceModel at year boundary
        # ============================================================
        # Update task IDF from this year's papers
        for _, effective_rpus in year_effective_papers:
            self.task_idf_tracker.update_from_paper(effective_rpus)

        # Collect feature vectors for RegularSpaceModel update
        if self.pca_feature_source == "phase2_recompute":
            year_feature_vecs = [
                self.feature_extractor.extract_features(effective_rpus)
                for _, effective_rpus in year_effective_papers
            ]
        else:
            year_feature_vecs = list(year_feature_snapshots)

        self.regular_space_model.update_at_year_boundary(year_feature_vecs, year)

        logger.info(f"V2 model updated: TaskIDF total_docs={self.task_idf_tracker.total_docs}, "
                     f"PCA info={self.regular_space_model.explained_variance_info}")

        pca_diag = self._build_pca_bias_diagnostic(year_results, year)
        synergy_diag = self._build_synergy_granularity_diagnostic(year_results, year)
        self.last_year_diagnostics[str(year)] = {
            "year": str(year),
            "papers": int(len(year_results)),
            "effective_papers": int(len(year_effective_papers)),
            "pca_feature_source": self.pca_feature_source,
            "synergy_granularity_mode": self.synergy_granularity_mode,
            "pca_bias": pca_diag,
            "synergy_granularity": synergy_diag,
        }

        # Clear year buffer after successful merge with error handling
        success, _ = self.error_handler.safe_execute(year_buffer.cleanup)
        if not success:
            logger.warning("Failed to cleanup year buffer, continuing...")

        # Invalidate state_id cache after state change
        if self.cache:
            self.cache.invalidate_state_id_cache()

        merge_time = time.time() - merge_start_time
        total_time = time.time() - start_time
        
        # ============================================================
        # Performance Monitoring: Year Complete
        # ============================================================
        if self.performance_metrics:
            # 记录年度处理统计
            self.performance_metrics.record_processing_stats(year, len(year_papers), total_rpus_in_year)
            
            # 结束年度计时
            self.performance_metrics.end_year_timing(year, calculation_time, merge_time)
            
            # 记录合并阶段耗时
            self.performance_metrics.record_phase_timing("merge", merge_time)
            
            # 采样年度结束时的内存使用
            self.performance_metrics.sample_memory_usage(year, "year_complete")
            
            # 快照缓存统计
            if self.cache:
                cache_stats = self.cache.get_cache_stats()
                self.performance_metrics.snapshot_cache_stats(year, cache_stats)
                
            # 快照过滤统计
            if self.modifier_filter:
                modifier_filter_stats = self.modifier_filter.get_filtering_stats()
                integration_stats = self.get_filtering_integration_stats()
                self.performance_metrics.snapshot_filtering_stats(year, modifier_filter_stats, integration_stats)
            
            # 记录性能里程碑
            processing_rate = len(year_papers) / total_time if total_time > 0 else 0
            if processing_rate > self.high_performance_threshold:  # 使用配置的高性能阈值
                self.performance_metrics.record_milestone(
                    year, "high_performance", 
                    f"高性能处理: {processing_rate:.1f} 论文/秒",
                    {"processing_rate": processing_rate, "papers": len(year_papers), "duration": total_time}
                )
        
        logger.info(f"Phase 2 completed: Buffer merged in {merge_time:.2f}s")
        logger.info(f"Year-Atomic processing for {year} completed: "
                   f"Total time {total_time:.2f}s, "
                   f"Calculation: {calculation_time:.2f}s, "
                   f"Merge: {merge_time:.2f}s")
        
        # Clear cache for next year to prevent cross-year pollution with error handling
        if self.cache:
            success, _ = self.error_handler.safe_execute(self.cache.clear_cache)
            if not success:
                logger.warning("Failed to clear cache, continuing...")
            
        return year_results


# ============================================================
# Main Script
# ============================================================
def load_papers_generator(input_path: str, paper_metadata_path: str = None):
    """
    Generator that yields papers chronologically from CSV or DB.
    Returns: (paper_id, List[RPU_Dict], year)

    Args:
        input_path: Path to RPU CSV or DB file
        paper_metadata_path: Optional path to paper metadata CSV with pub_year column.
                            Used when RPU CSV lacks year information.
    """
    if not os.path.exists(input_path):
        logger.error(f"Input file not found: {input_path}")
        return

    logger.info(f"Reading from: {input_path}")

    # CSV Mode
    if input_path.lower().endswith('.csv'):
        import csv

        # Load paper metadata (pub_year mapping) if provided
        year_lookup = {}
        if paper_metadata_path and os.path.exists(paper_metadata_path):
            logger.info(f"Loading paper metadata from: {paper_metadata_path}")
            with open(paper_metadata_path, 'r', encoding='utf-8-sig') as mf:
                meta_reader = csv.DictReader(mf)
                for mrow in meta_reader:
                    mid = mrow.get('paper_id') or mrow.get('id')
                    myear = mrow.get('pub_year') or mrow.get('year')
                    if mid and myear:
                        year_lookup[mid] = str(myear)
            logger.info(f"Loaded year info for {len(year_lookup)} papers from metadata")

        # Read all rows, sort by date/id if possible, then yield grouped by paper_id
        # Assuming CSV has header
        rows = []
        with open(input_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        
        # Sort by date if available, else paper_id (as proxy for time)
        # We try 'publish_date' then 'date' then 'year', else maintain order
        if rows and 'publish_date' in rows[0]:
            rows.sort(key=lambda x: x['publish_date'])
        elif rows and 'year' in rows[0]:
            rows.sort(key=lambda x: x.get('year', '0'))
        
        current_paper_id = None
        current_rpus = []
        
        for row in rows:
            # 支持 'paper_id' 或 'id' 列名
            pid = row.get('paper_id') or row.get('id')
            
            # Extract year information from available fields
            # 支持 'year', 'pub_year', 'publish_date' 等多种年份字段
            paper_year = None
            if 'year' in row and row['year']:
                paper_year = str(row['year'])
            elif 'pub_year' in row and row['pub_year']:
                paper_year = str(row['pub_year'])
            elif pid and pid in year_lookup:
                paper_year = year_lookup[pid]
            elif 'publish_date' in row and row['publish_date']:
                try:
                    # Try to extract year from date string
                    date_str = row['publish_date']
                    if len(date_str) >= 4 and date_str[:4].isdigit():
                        paper_year = date_str[:4]
                except:
                    pass
            
            # Fallback: 这是经验值 - 如果无法提取年份，使用基于计数的简化年份分配
            if not paper_year:
                # Use a simple counter-based year assignment for demonstration
                # In production, year should come from proper paper metadata
                row_index = rows.index(row)
                paper_year = str(2020 + (row_index // 10000))  # 每10000篇论文为一年
            
            # Map CSV fields to RPU dict
            # Handle empty strings and literal "null" as None
            # 支持 'modifier' 或 'aspect' 列名
            raw_modifier = row.get('modifier') or row.get('aspect') or None
            if raw_modifier and raw_modifier.strip().lower() == 'null':
                raw_modifier = None
            raw_aspect = row.get('aspect') or None
            if raw_aspect and raw_aspect.strip().lower() == 'null':
                raw_aspect = None
            raw_object_coverage = row.get('object_coverage')
            if raw_object_coverage in (None, ""):
                raw_object_coverage = row.get('coverage')
            if isinstance(raw_object_coverage, str) and raw_object_coverage.strip().lower() == 'null':
                raw_object_coverage = None
            rpu = {
                'task': row.get('task') or None,
                'object': row.get('object') or None,
                'modifier': raw_modifier,
                'aspect': raw_aspect,
                'task_core': row.get('task_core') or None,
                'object_core': row.get('object_core') or None,
                'object_coverage': raw_object_coverage
            }
            
            if pid != current_paper_id:
                if current_paper_id is not None:
                    yield current_paper_id, current_rpus, current_year
                current_paper_id = pid
                current_rpus = []
                current_year = paper_year
            
            current_rpus.append(rpu)
            
        if current_paper_id is not None:
            yield current_paper_id, current_rpus, current_year

    # DB Mode (Legacy/Production)
    elif input_path.lower().endswith('.db'):
        logger.warning("Database access is currently restricted or deprecated in favor of CSV for this step.")
        # ... (Legacy code omitted for safety) ...
        return
    
    else:
        logger.error("Unsupported file format. Use .csv")
        return

def group_papers_by_year(input_path: str, paper_metadata_path: str = None, limit: int = None) -> Dict[str, List[Tuple[str, List[Dict]]]]:
    """
    Group papers by year while maintaining chronological order within each year.
    
    Args:
        input_path: Path to input CSV or DB file
        
    Returns:
        Dict mapping year -> list of (paper_id, rpu_list) tuples
        
    Requirements Addressed:
    - 1.4: Group papers by year while maintaining chronological order
    - 5.2: Year-based iteration for temporal causality preservation
    """
    logger.info("Grouping papers by year for Year-Atomic processing...")
    
    year_groups = defaultdict(list)
    total_papers = 0
    
    # Collect all papers and group by year
    for paper_id, rpus, year in load_papers_generator(input_path, paper_metadata_path=paper_metadata_path):
        year_groups[year].append((paper_id, rpus))
        total_papers += 1

        if limit and total_papers >= limit:
            logger.info(f"Reached paper limit: {limit}")
            break

        if total_papers % 10000 == 0:
            logger.info(f"Grouped {total_papers} papers into {len(year_groups)} years...")
    
    # Sort years chronologically
    sorted_years = sorted(year_groups.keys())
    
    logger.info(f"Completed grouping: {total_papers} papers across {len(sorted_years)} years")
    if not sorted_years:
        logger.warning("No valid year groups generated")
        return {}
    logger.info(f"Year range: {sorted_years[0]} - {sorted_years[-1]}")
    
    # Log papers per year for monitoring
    for year in sorted_years[:5]:  # Show first 5 years
        logger.info(f"  {year}: {len(year_groups[year])} papers")
    if len(sorted_years) > 5:
        logger.info(f"  ... (showing first 5 years)")
        for year in sorted_years[-2:]:  # Show last 2 years
            logger.info(f"  {year}: {len(year_groups[year])} papers")
    
    # Return as regular dict with sorted years
    return {year: year_groups[year] for year in sorted_years}

def main():
    parser = argparse.ArgumentParser(description="Calculate Innovation Signals")
    parser.add_argument(
        "--input_path",
        type=str,
        default=DEFAULT_INPUT_PATH,
        help="Path to input CSV or DB (default: rpu_db_path from project_config)",
    )
    parser.add_argument("--paper_metadata", type=str, default=None,
                       help="Path to paper metadata CSV with pub_year column (used when RPU CSV lacks year info)")
    parser.add_argument("--output_path", type=str, default="innovation_signals.jsonl")
    parser.add_argument("--limit", type=int, default=None,
                       help="Limit number of papers to process (for testing/sampling)")
    parser.add_argument("--config", type=str, help="Path to configuration file (JSON or YAML)")
    parser.add_argument("--disable_cache", action="store_true", help="Disable YearCache optimization")
    parser.add_argument("--disable_modifier_filter", action="store_true", help="Disable ModifierFilter optimization")
    parser.add_argument("--disable_performance_metrics", action="store_true", help="Disable comprehensive performance metrics collection")
    parser.add_argument("--modifier_filter_percentile", type=float, default=99.0, 
                       help="Percentile threshold for modifier filtering (default: 99.0)")
    parser.add_argument("--performance_report_path", type=str, default="performance_metrics.json",
                       help="Path to export detailed performance metrics (default: performance_metrics.json)")
    parser.add_argument("--memory_sample_interval", type=int, default=10,
                       help="Memory sampling interval in years (default: 10)")
    args = parser.parse_args()
    
    # ============================================================
    # Configuration Management: Load and Validate Configuration
    # ============================================================
    try:
        config_manager = ConfigManager()
        
        if args.config:
            # 从配置文件加载
            logger.info(f"加载配置文件: {args.config}")
            config = config_manager.load_config(args.config)
        else:
            # 从命令行参数创建配置
            logger.info("使用命令行参数创建配置")
            config = load_config_from_args(args)
            
        # 验证配置
        validation_results = config.validate()
        if validation_results:
            logger.error("配置验证失败:")
            for section, errors in validation_results.items():
                for error in errors:
                    logger.error(f"  [{section}] {error}")
            return
            
        logger.info("✓ 配置验证通过")
        
        # 应用日志配置
        if config.logging.level != "INFO":
            logging.getLogger().setLevel(getattr(logging, config.logging.level.upper()))
            logger.info(f"日志级别已设置为: {config.logging.level}")
            
    except Exception as e:
        logger.error(f"配置加载失败: {e}")
        logger.info("使用默认配置继续执行...")
        config = None
    
    # ============================================================
    # Initialize InnovationState with Configuration
    # ============================================================
    logger.info("初始化创新状态管理器...")
    state = InnovationState(config=config)
    
    # ============================================================
    # Performance Monitoring: Initialize and Start Total Timing
    # ============================================================
    if state.performance_metrics:
        # 开始总体计时
        state.performance_metrics.start_total_timing()
        # 记录初始化里程碑
        state.performance_metrics.record_milestone(
            "initialization", "system_start", 
            "创新引擎优化系统启动",
            {
                "cache_enabled": state.cache is not None,
                "modifier_filter_enabled": state.modifier_filter is not None,
                "modifier_filter_percentile": state.modifier_filter.percentile_threshold if state.modifier_filter else None,
                "memory_sample_interval": state.memory_sample_interval,
                "config_source": "file" if args.config else "command_line"
            }
        )
        logger.info("PerformanceMetrics: 综合性能监控已启用")
    
    logger.info("Starting Innovation Signal Calculation with Year-Atomic Processing...")
    if state.cache:
        logger.info(f"YearCache optimization enabled (log: {state.cache.max_log_cache_size}, pmi: {state.cache.max_pmi_cache_size})")
    else:
        logger.info("YearCache optimization disabled")
        
    if state.modifier_filter:
        logger.info(f"ModifierFilter optimization enabled (percentile: {state.modifier_filter.percentile_threshold}%)")
    else:
        logger.info("ModifierFilter optimization disabled")
        
    if state.performance_metrics:
        logger.info(f"PerformanceMetrics enabled (memory sampling every {state.memory_sample_interval} years)")
    else:
        logger.info("PerformanceMetrics disabled")
    
    # 输出配置摘要
    if config:
        logger.info("配置摘要:")
        logger.info(f"  - 输入路径: {config.input_path}")
        logger.info(f"  - 输出路径: {config.output_path}")
        logger.info(f"  - 协同最小支持度: {config.algorithm.synergy_min_support}")
        logger.info(f"  - Top-K信号数: {config.algorithm.top_k_signals}")
        logger.info(f"  - 修剪阈值: {config.algorithm.prune_threshold:,}")
        
        # 使用配置中的路径
        input_path = config.input_path
        output_path = config.output_path
        performance_report_path = config.performance_report_path
    else:
        # 使用命令行参数
        input_path = args.input_path
        output_path = args.output_path
        performance_report_path = args.performance_report_path
    diagnostics_report_path = _derive_diagnostics_path(performance_report_path)

    # 获取paper_metadata路径
    paper_metadata_path = args.paper_metadata if hasattr(args, 'paper_metadata') else None
    
    # Output file
    f_out = open(output_path, 'w', encoding='utf-8')
    
    # Progress tracking
    start_time = time.time()
    
    # ============================================================
    # Year-Based Processing Pipeline
    # ============================================================
    
    # Step 1: Group papers by year while maintaining chronological order
    logger.info("Step 1: Grouping papers by year...")
    grouping_start_time = time.time()
    year_groups = group_papers_by_year(input_path, paper_metadata_path=paper_metadata_path, limit=args.limit)
    grouping_time = time.time() - grouping_start_time
    
    if not year_groups:
        logger.error("No papers found to process")
        return
    
    # 记录分组阶段性能
    if state.performance_metrics:
        state.performance_metrics.record_phase_timing("grouping", grouping_time)
        state.performance_metrics.record_milestone(
            "initialization", "grouping_complete",
            f"论文分组完成: {len(year_groups)} 年份",
            {"years_count": len(year_groups), "grouping_time": grouping_time}
        )
    
    # Step 2: Process each year atomically in chronological order
    logger.info("Step 2: Processing years atomically in chronological order...")
    
    # Progress tracking
    total_papers_processed = 0
    total_years = len(year_groups)
    
    # Statistics reporting intervals - 使用配置的报告间隔
    cache_report_interval = state.cache_report_interval
    modifier_filter_report_interval = state.modifier_filter_report_interval
    performance_report_interval = args.memory_sample_interval  # Performance report interval
    
    # Process each year in chronological order
    for year_index, (year, year_papers) in enumerate(year_groups.items(), 1):
        logger.info(f"Processing year {year} ({year_index}/{total_years}): {len(year_papers)} papers")
        
        year_start_time = time.time()
        
        # ========================================
        # Year-Atomic Processing
        # ========================================
        
        try:
            # Process entire year atomically using the process_year_atomic method
            # This implements Requirements 1.1, 1.2, 1.3, 1.5, 4.1, 4.2, 4.5
            year_results = state.process_year_atomic(year_papers, year)
            
            # Write all results for this year
            for result in year_results:
                f_out.write(json.dumps(result) + "\n")
            
            total_papers_processed += len(year_papers)
            year_processing_time = time.time() - year_start_time
            
            logger.info(f"Year {year} completed: {len(year_results)} papers processed in {year_processing_time:.2f}s")
            
            # Flush output periodically
            if year_index % 5 == 0:
                f_out.flush()
                
        except Exception as e:
            logger.error(f"Error processing year {year}: {e}")
            
            # Try to handle the error using the error handler
            components = {
                'cache': state.cache,
                'filter': state.modifier_filter,
                'buffer': None
            }
            
            # Check if this is a memory-related error
            if "memory" in str(e).lower():
                logger.info("Attempting memory pressure recovery...")
                if state.error_handler.handle_memory_pressure(components):
                    logger.info("Memory pressure recovery successful")
                else:
                    logger.error("Memory pressure recovery failed")
            
            # Record error milestone if performance metrics are enabled
            if state.performance_metrics:
                state.performance_metrics.record_milestone(
                    year, "processing_error",
                    f"年份处理错误: {str(e)}",
                    {"error_type": type(e).__name__, "error_message": str(e)}
                )
            
            # Continue with next year rather than failing completely
            continue
        
        # ========================================
        # Performance Monitoring and Reporting
        # ========================================
        
        # Report cache statistics periodically
        if state.cache and year_index % cache_report_interval == 0:
            cache_stats = state.cache.get_cache_stats()
            logger.info(f"Cache Stats after {year_index} years: "
                       f"Log hit rate: {cache_stats['log_cache']['hit_rate']:.3f}, "
                       f"PMI hit rate: {cache_stats['pmi_cache']['hit_rate']:.3f}, "
                       f"Total memory: {cache_stats['total_memory_bytes']:,} bytes")

        # Report modifier filter statistics periodically
        if state.modifier_filter and year_index % modifier_filter_report_interval == 0:
            filter_stats = state.modifier_filter.get_filtering_stats()
            integration_stats = state.get_filtering_integration_stats()
            logger.info(f"ModifierFilter Stats after {year_index} years: "
                       f"Filter rate: {filter_stats['filter_rate']:.3f}, "
                       f"Threshold: {filter_stats['current_threshold']}, "
                       f"Unique modifiers: {filter_stats['unique_modifiers']:,}, "
                       f"Integration filter rate: {integration_stats['modifier_filter_rate']:.3f}")

        # Comprehensive performance reporting
        if state.performance_metrics and year_index % performance_report_interval == 0:
            # 记录中期性能里程碑
            current_rate = total_papers_processed / (time.time() - start_time)
            state.performance_metrics.record_milestone(
                year, "performance_checkpoint",
                f"性能检查点: 已处理 {year_index}/{total_years} 年份",
                {
                    "years_completed": year_index,
                    "papers_processed": total_papers_processed,
                    "current_processing_rate": current_rate,
                    "elapsed_time": time.time() - start_time
                }
            )
            
            # 记录性能摘要到日志
            logger.info(f"=== 性能检查点 ({year_index}/{total_years} 年份) ===")
            logger.info(f"已处理论文: {total_papers_processed:,}")
            logger.info(f"当前处理速率: {current_rate:.1f} 论文/秒")
            
            if state.performance_metrics.memory_stats['enable_monitoring']:
                memory_peak = state.performance_metrics.get_memory_peak_info()
                if memory_peak['peak_memory_mb'] > 0:
                    logger.info(f"峰值内存: {memory_peak['peak_memory_mb']:.1f}MB")
    
    f_out.close()

    diagnostics_exported = False
    if state.last_year_diagnostics:
        diagnostics_payload = {
            "generated_at": datetime.now().isoformat(),
            "pca_feature_source": state.pca_feature_source,
            "synergy_granularity_mode": state.synergy_granularity_mode,
            "years": state.last_year_diagnostics,
        }
        try:
            with open(diagnostics_report_path, 'w', encoding='utf-8') as diag_f:
                json.dump(diagnostics_payload, diag_f, ensure_ascii=False, indent=2)
            logger.info(f"Year diagnostics exported to: {diagnostics_report_path}")
            diagnostics_exported = True
        except Exception as e:
            logger.error(f"Failed to export year diagnostics: {e}")
    else:
        logger.info("No year diagnostics to export")
    
    # ============================================================
    # Performance Monitoring: Finalize and Generate Reports
    # ============================================================
    
    if state.performance_metrics:
        # 结束总体计时
        state.performance_metrics.end_total_timing()
        
        # 记录最终里程碑
        final_processing_rate = total_papers_processed / state.performance_metrics.get_total_duration()
        state.performance_metrics.record_milestone(
            "final", "processing_complete",
            "创新引擎处理完成",
            {
                "total_papers": total_papers_processed,
                "total_years": total_years,
                "final_processing_rate": final_processing_rate,
                "total_duration": state.performance_metrics.get_total_duration()
            }
        )
        
        # 生成并记录综合性能报告
        logger.info("=== 生成综合性能报告 ===")
        state.performance_metrics.log_performance_summary(logging.INFO)
        
        # 导出详细性能指标
        try:
            state.performance_metrics.export_detailed_metrics(performance_report_path)
            logger.info(f"详细性能指标已导出到: {performance_report_path}")
        except Exception as e:
            logger.error(f"导出性能指标失败: {e}")
    
    # ============================================================
    # Final Statistics and Performance Reports
    # ============================================================
    
    total_processing_time = time.time() - start_time
    
    logger.info("=== Year-Atomic Processing Completed ===")
    logger.info(f"Total papers processed: {total_papers_processed:,}")
    logger.info(f"Total years processed: {total_years}")
    logger.info(f"Total processing time: {total_processing_time:.2f}s")
    logger.info(f"Average time per year: {total_processing_time/total_years:.2f}s")
    logger.info(f"Average papers per second: {total_papers_processed/total_processing_time:.1f}")
    
    # Final cache statistics
    if state.cache:
        final_cache_stats = state.cache.get_cache_stats()
        logger.info("=== Final Cache Statistics ===")
        logger.info(f"Log Cache: {final_cache_stats['log_cache']['hits']:,} hits, "
                   f"{final_cache_stats['log_cache']['misses']:,} misses, "
                   f"hit rate: {final_cache_stats['log_cache']['hit_rate']:.3f}")
        logger.info(f"PMI Cache: {final_cache_stats['pmi_cache']['hits']:,} hits, "
                   f"{final_cache_stats['pmi_cache']['misses']:,} misses, "
                   f"hit rate: {final_cache_stats['pmi_cache']['hit_rate']:.3f}")
        logger.info(f"Total cache memory usage: {final_cache_stats['total_memory_bytes']:,} bytes")

    # Final modifier filter statistics
    if state.modifier_filter:
        final_filter_stats = state.modifier_filter.get_filtering_stats()
        final_integration_stats = state.get_filtering_integration_stats()
        
        logger.info("=== Final ModifierFilter Statistics ===")
        logger.info(f"Total processed: {final_filter_stats['total_processed']:,}")
        logger.info(f"Filtered count: {final_filter_stats['filtered_count']:,}")
        logger.info(f"Filter rate: {final_filter_stats['filter_rate']:.3f}")
        logger.info(f"Final threshold: {final_filter_stats['current_threshold']}")
        logger.info(f"Unique modifiers: {final_filter_stats['unique_modifiers']:,}")
        logger.info(f"Threshold updates: {final_filter_stats['threshold_updates']}")
        
        logger.info("=== Integration Statistics ===")
        logger.info(f"Modifier bonus calls: {final_integration_stats['total_modifier_bonus_calls']:,}")
        logger.info(f"Filtered modifier calls: {final_integration_stats['filtered_modifier_calls']:,}")
        logger.info(f"Integration filter rate: {final_integration_stats['modifier_filter_rate']:.3f}")
        logger.info(f"Synergy concepts processed: {final_integration_stats['total_synergy_concepts_processed']:,}")
        logger.info(f"Synergy concepts filtered: {final_integration_stats['synergy_concepts_filtered']:,}")
        logger.info(f"Synergy filter rate: {final_integration_stats['synergy_filter_rate']:.3f}")
        
        # Log top frequent modifiers for analysis
        top_modifiers = final_filter_stats['top_frequent_modifiers']
        if top_modifiers:
            logger.info("Top 10 frequent modifiers:")
            for i, (modifier, freq) in enumerate(top_modifiers, 1):
                logger.info(f"  {i}. '{modifier}': {freq} occurrences")
    
    logger.info(f"Year-Atomic processing completed successfully!")
    logger.info(f"Results written to: {output_path}")
    if diagnostics_exported:
        logger.info(f"Year diagnostics exported to: {diagnostics_report_path}")
    
    if state.performance_metrics:
        logger.info(f"Performance metrics exported to: {performance_report_path}")
    
    # ============================================================
    # Error Handling: Generate and Export Error Report
    # ============================================================
    
    if state.error_handler:
        try:
            # Generate comprehensive error report
            error_report = state.error_handler.get_error_report()
            
            # Log error summary
            if error_report['summary']['total_errors'] > 0:
                logger.info("=== 错误处理摘要 ===")
                logger.info(f"总错误数: {error_report['summary']['total_errors']}")
                logger.info(f"成功恢复数: {error_report['summary']['total_recoveries']}")
                logger.info(f"恢复成功率: {error_report['summary']['recovery_rate']:.1%}")
                logger.info(f"内存警告数: {error_report['summary']['memory_warnings']}")
                logger.info(f"性能降级事件数: {error_report['summary']['degradation_events']}")
                
                # Show recommendations
                logger.info("建议:")
                for rec in error_report['recommendations']:
                    logger.info(f"  {rec}")
            else:
                logger.info("✓ 无错误发生 - 系统运行正常")
            
            # Export detailed error report
            error_report_path = performance_report_path.replace('.json', '_errors.json')
            state.error_handler.export_error_report(error_report_path)
            logger.info(f"Error report exported to: {error_report_path}")
            
        except Exception as e:
            logger.error(f"Failed to generate error report: {e}")
    
    # Final system health check
    if state.error_handler:
        final_health = state.error_handler.check_system_health()
        if final_health.get('healthy', True):
            logger.info("✓ System health check passed")
        else:
            logger.warning("⚠ System health check indicates potential issues")
            logger.warning(f"Memory usage: {final_health.get('system_memory_percent', 0):.1f}%")

if __name__ == "__main__":
    main()
