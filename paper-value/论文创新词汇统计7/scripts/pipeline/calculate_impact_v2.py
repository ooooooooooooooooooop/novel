# -*- coding: utf-8 -*-
"""
Impact V5.0 计算脚本

核心设计：
- IU = object（概念），不是 combo
- Task = 权重因子，不是匹配键
- 聚合 = Top-3，避免 RPU 数量偏倚

设计文档: IMPACT_V2_DESIGN.md (V5.0)

Usage:
    python scripts/pipeline/calculate_impact_v2.py                    # 全量运行
    python scripts/pipeline/calculate_impact_v2.py --pass 0          # 只运行 Pass 0
    python scripts/pipeline/calculate_impact_v2.py --pass 1          # 只运行 Pass 1
    python scripts/pipeline/calculate_impact_v2.py --year 2015       # 单年测试
    python scripts/pipeline/calculate_impact_v2.py --resume          # 断点续传
"""

import os
import sys
import json
import sqlite3
import logging
import argparse
import math
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from functools import lru_cache
from typing import Dict, List, Tuple, Optional, Set

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import load_project_config, get_paths, get_runtime, get_years

_cfg = load_project_config()
_paths = get_paths(_cfg)
_runtime = get_runtime(_cfg)

_default_logs_dir = Path(_paths.get("logs_dir", str(PROJECT_ROOT / "artifacts" / "runtime" / "logs")))
_default_logs_dir.mkdir(parents=True, exist_ok=True)
_impact_log_path = _paths.get("impact_log_path", str(_default_logs_dir / "impact_calculation.log"))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(_impact_log_path, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============== 配置 ==============

CONFIG = {
    'rpu_db_path': _paths['rpu_db_path'],
    'output_dir': _paths['impact_output_dir'],
    'years': get_years(_runtime),
    'top_k': 3,  # Top-K 聚合
    'persistence_threshold': 0.5,  # Survival ratio 阈值
    'current_year': int(_runtime.get('current_year', 2025)),
    'min_observable_years': 1,  # 最小可观测年份
    'exclude_correction_papers': True,  # 过滤更正/勘误类论文
}


def build_runtime_config(config_path: str = None) -> dict:
    cfg = load_project_config(config_path)
    paths = get_paths(cfg)
    runtime = get_runtime(cfg)
    merged = dict(CONFIG)
    merged.update({
        'rpu_db_path': paths['rpu_db_path'],
        'output_dir': paths['impact_output_dir'],
        'years': get_years(runtime),
        'current_year': int(runtime.get('current_year', 2025)),
        'exclude_correction_papers': bool(runtime.get('exclude_correction_papers', True)),
    })
    return merged


STATS_SCHEMA_VERSION = "impact_v5_1_concept_key_v1"

CORRECTION_TITLE_KEYWORDS = (
    "correction",
    "erratum",
    "corrigendum",
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
    "a", "an", "the", "of", "for", "to", "in", "on", "by", "with", "without",
    "from", "at", "as", "and", "or", "that", "this", "these", "those", "our",
    "their", "its", "is", "are", "was", "were", "be", "been", "being", "we",
    "it", "into", "through", "over", "under",
}

OBJECT_GENERIC_TOKENS = {
    "paper", "article", "study", "result", "results", "method", "methods",
    "approach", "approaches", "analysis", "overview", "description", "review",
    "development", "developments", "capability", "capabilities", "practice",
    "practices", "introduction", "framework", "model", "models", "system",
    "systems", "correction", "erratum", "corrigendum", "amendment", "publisher",
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
    "scipy", "numpy", "matplotlib", "pytorch", "tensorflow", "transformer",
    "bert", "gpt", "alphafold", "crispr", "chatgpt", "xgboost", "lightgbm",
}

# Task 权重表
TASK_WEIGHTS = {
    # 创造类 (1.5)
    'invent': 1.5, 'pioneer': 1.5, 'propose': 1.5, 'discover': 1.5,
    'devise': 1.5, 'originate': 1.5, 'innovate': 1.5,
    # 开发类 (1.2)
    'develop': 1.2, 'design': 1.2, 'implement': 1.2, 'build': 1.2,
    'create': 1.2, 'construct': 1.2, 'establish': 1.2,
    # 改进类 (1.1)
    'improve': 1.1, 'enhance': 1.1, 'extend': 1.1, 'optimize': 1.1,
    'refine': 1.1, 'upgrade': 1.1, 'advance': 1.1,
    # 应用类 (0.8)
    'apply': 0.8, 'use': 0.8, 'employ': 0.8, 'utilize': 0.8,
    'adopt': 0.8, 'deploy': 0.8, 'leverage': 0.8,
    # 分析类 (0.6)
    'analyze': 0.6, 'study': 0.6, 'examine': 0.6, 'investigate': 0.6,
    'explore': 0.6, 'assess': 0.6, 'evaluate': 0.6,
    # 描述类 (0.3)
    'describe': 0.3, 'report': 0.3, 'present': 0.3, 'show': 0.3,
    'review': 0.3, 'summarize': 0.3, 'discuss': 0.3, 'demonstrate': 0.3,
}

# 简单的 lemmatization 规则（避免依赖 spacy）
LEMMA_RULES = {
    # 动词不规则变化
    'proposed': 'propose', 'proposing': 'propose', 'proposes': 'propose',
    'developed': 'develop', 'developing': 'develop', 'develops': 'develop',
    'designed': 'design', 'designing': 'design', 'designs': 'design',
    'implemented': 'implement', 'implementing': 'implement', 'implements': 'implement',
    'applied': 'apply', 'applying': 'apply', 'applies': 'apply',
    'used': 'use', 'using': 'use', 'uses': 'use',
    'analyzed': 'analyze', 'analyzing': 'analyze', 'analyzes': 'analyze',
    'analysed': 'analyze', 'analysing': 'analyze', 'analyses': 'analyze',
    'studied': 'study', 'studying': 'study', 'studies': 'study',
    'showed': 'show', 'showing': 'show', 'shows': 'show',
    'shown': 'show',
    'demonstrated': 'demonstrate', 'demonstrating': 'demonstrate', 'demonstrates': 'demonstrate',
    'discovered': 'discover', 'discovering': 'discover', 'discovers': 'discover',
    'created': 'create', 'creating': 'create', 'creates': 'create',
    'built': 'build', 'building': 'build', 'builds': 'build',
    'improved': 'improve', 'improving': 'improve', 'improves': 'improve',
    'enhanced': 'enhance', 'enhancing': 'enhance', 'enhances': 'enhance',
    'extended': 'extend', 'extending': 'extend', 'extends': 'extend',
    'optimized': 'optimize', 'optimizing': 'optimize', 'optimizes': 'optimize',
    'evaluated': 'evaluate', 'evaluating': 'evaluate', 'evaluates': 'evaluate',
    'examined': 'examine', 'examining': 'examine', 'examines': 'examine',
    'investigated': 'investigate', 'investigating': 'investigate', 'investigates': 'investigate',
    'explored': 'explore', 'exploring': 'explore', 'explores': 'explore',
    'described': 'describe', 'describing': 'describe', 'describes': 'describe',
    'reported': 'report', 'reporting': 'report', 'reports': 'report',
    'presented': 'present', 'presenting': 'present', 'presents': 'present',
    'reviewed': 'review', 'reviewing': 'review', 'reviews': 'review',
    'summarized': 'summarize', 'summarizing': 'summarize', 'summarizes': 'summarize',
    'discussed': 'discuss', 'discussing': 'discuss', 'discusses': 'discuss',
    'adopted': 'adopt', 'adopting': 'adopt', 'adopts': 'adopt',
    'employed': 'employ', 'employing': 'employ', 'employs': 'employ',
    'utilized': 'utilize', 'utilizing': 'utilize', 'utilizes': 'utilize',
}


def lemmatize_task(task: str) -> str:
    """简单的任务动词 lemmatization"""
    if not task:
        return ''
    task = task.lower().strip()

    # 查找规则表
    if task in LEMMA_RULES:
        return LEMMA_RULES[task]

    # 基于后缀的简单规则
    if task.endswith('ing') and len(task) > 4:
        base = task[:-3]
        if base + 'e' in TASK_WEIGHTS:
            return base + 'e'
        if base in TASK_WEIGHTS:
            return base
    if task.endswith('ed') and len(task) > 3:
        base = task[:-2]
        if base + 'e' in TASK_WEIGHTS:
            return base + 'e'
        if base in TASK_WEIGHTS:
            return base
        base = task[:-1]  # doubled consonant
        if base in TASK_WEIGHTS:
            return base
    if task.endswith('s') and not task.endswith('ss') and len(task) > 2:
        base = task[:-1]
        if base in TASK_WEIGHTS:
            return base

    return task


def lemmatize_object(obj: str) -> str:
    """简单的 object lemmatization（主要处理复数）"""
    if not obj:
        return ''
    obj = obj.lower().strip()

    # 跳过太短的
    if len(obj) <= 3:
        return obj

    # 处理复数
    if obj.endswith('ies') and len(obj) > 4:
        return obj[:-3] + 'y'
    if obj.endswith('es') and len(obj) > 3:
        if obj.endswith('ses') or obj.endswith('xes') or obj.endswith('ches') or obj.endswith('shes'):
            return obj[:-2]
        return obj[:-1]
    if obj.endswith('s') and not obj.endswith('ss') and len(obj) > 3:
        # 避免破坏已经是单数的词
        if not obj.endswith('sis') and not obj.endswith('ous') and not obj.endswith('ess'):
            return obj[:-1]

    return obj


def get_task_weight(task: str) -> float:
    """获取任务动词权重"""
    task_lemma = lemmatize_task(task)
    return TASK_WEIGHTS.get(task_lemma, 1.0)


def is_correction_title(title: str) -> bool:
    """判断标题是否属于更正/勘误类"""
    text = (title or "").lower()
    return any(keyword in text for keyword in CORRECTION_TITLE_KEYWORDS)


def build_correction_filter_sql(alias: str = "p") -> str:
    """构造用于 SQL 的更正/勘误过滤条件"""
    title_expr = f"LOWER(COALESCE({alias}.title, ''))"
    clauses = [f"{title_expr} NOT LIKE '%{kw}%'" for kw in CORRECTION_TITLE_KEYWORDS]
    return " AND ".join(clauses)


@lru_cache(maxsize=500000)
def normalize_object_concept(obj: str) -> str:
    """
    将 object 文本归一化为概念键。
    目标是缓解整句级 object_lemma 过稀疏导致的“后续采用计数为 0”问题。
    """
    if not obj:
        return ""

    text = obj.lower().strip()
    for pattern, repl in OBJECT_ALIAS_PATTERNS:
        text = re.sub(pattern, repl, text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9.+\-\s]", " ", text)
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
        # 版本号通常会导致过稀疏，保留信息词，移除纯数字碎片
        if token.isdigit():
            continue
        tokens.append(token)

    if not tokens:
        return ""

    if all(token in OBJECT_GENERIC_TOKENS for token in tokens):
        return ""

    anchor = next((token for token in tokens if token in CONCEPT_ANCHOR_TERMS), None)
    if anchor:
        return anchor

    tokens = [token for token in tokens if token not in OBJECT_GENERIC_TOKENS]
    if not tokens:
        return ""

    if len(tokens) > 6:
        tokens = tokens[-6:]

    return " ".join(tokens)


class ImpactCalculator:
    """Impact V5.0 计算器"""

    def __init__(self, config: dict = None):
        self.config = config or CONFIG
        self.rpu_db_path = self.config['rpu_db_path']
        self.output_dir = Path(self.config['output_dir'])
        self.output_dir.mkdir(exist_ok=True)

        # 时序统计数据库
        self.stats_db_path = self.output_dir / 'temporal_stats.db'

        # Checkpoint
        self.checkpoint_path = self.output_dir / 'checkpoint.json'
        self.checkpoint = self._load_checkpoint()

    def _load_checkpoint(self) -> dict:
        """加载 checkpoint"""
        if self.checkpoint_path.exists():
            with open(self.checkpoint_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {'pass0_complete': False, 'pass1_complete': False, 'pass2_years': [], 'pass3_complete': False}

    def _save_checkpoint(self):
        """保存 checkpoint"""
        with open(self.checkpoint_path, 'w', encoding='utf-8') as f:
            json.dump(self.checkpoint, f, indent=2)

    def _is_stats_db_compatible(self) -> bool:
        """检查 temporal_stats.db 是否与当前统计口径兼容"""
        if not self.stats_db_path.exists():
            return False

        conn = None
        try:
            conn = sqlite3.connect(str(self.stats_db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='meta'")
            if not cursor.fetchone():
                return False
            cursor.execute("SELECT value FROM meta WHERE key = 'stats_schema_version'")
            row = cursor.fetchone()
            return bool(row and row[0] == STATS_SCHEMA_VERSION)
        except Exception:
            return False
        finally:
            if conn:
                conn.close()

    # ============== Pass 0: 预处理 ==============

    def run_pass0(self, force: bool = False):
        """
        Pass 0: 预处理 - 添加 object_lemma 和 task_lemma 列
        """
        if self.checkpoint.get('pass0_complete') and not force:
            logger.info("Pass 0 已完成，跳过")
            return

        logger.info("=" * 60)
        logger.info("Pass 0: 预处理 - 添加 lemma 列")
        logger.info("=" * 60)

        conn = sqlite3.connect(self.rpu_db_path)
        cursor = conn.cursor()

        # 检查列是否存在
        cursor.execute("PRAGMA table_info(rpu)")
        columns = [col[1] for col in cursor.fetchall()]

        # 添加新列（如果不存在）
        if 'object_lemma' not in columns:
            logger.info("添加 object_lemma 列...")
            cursor.execute("ALTER TABLE rpu ADD COLUMN object_lemma TEXT")

        if 'task_lemma' not in columns:
            logger.info("添加 task_lemma 列...")
            cursor.execute("ALTER TABLE rpu ADD COLUMN task_lemma TEXT")

        conn.commit()

        # 统计总数
        cursor.execute("SELECT COUNT(*) FROM rpu WHERE object_lemma IS NULL")
        total = cursor.fetchone()[0]
        logger.info(f"需要处理的 RPU 数量: {total:,}")

        if total == 0:
            logger.info("所有 RPU 已有 lemma，跳过")
            self.checkpoint['pass0_complete'] = True
            self._save_checkpoint()
            conn.close()
            return

        # 批量更新
        batch_size = 100000
        processed = 0
        start_time = datetime.now()

        while True:
            cursor.execute("""
                SELECT id, task, object FROM rpu
                WHERE object_lemma IS NULL
                LIMIT ?
            """, (batch_size,))
            rows = cursor.fetchall()

            if not rows:
                break

            updates = []
            for row_id, task, obj in rows:
                task_lemma = lemmatize_task(task) if task else ''
                obj_lemma = lemmatize_object(obj) if obj else ''
                updates.append((task_lemma, obj_lemma, row_id))

            cursor.executemany("""
                UPDATE rpu SET task_lemma = ?, object_lemma = ? WHERE id = ?
            """, updates)
            conn.commit()

            processed += len(rows)
            elapsed = (datetime.now() - start_time).total_seconds()
            rate = processed / elapsed if elapsed > 0 else 0
            eta = (total - processed) / rate / 60 if rate > 0 else 0
            logger.info(f"Pass 0: {processed:,}/{total:,} ({processed/total*100:.1f}%) - {rate:.0f} RPU/s - ETA: {eta:.1f}min")

        # 创建索引
        logger.info("创建索引...")
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rpu_object_lemma ON rpu(object_lemma)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rpu_task_lemma ON rpu(task_lemma)")
            conn.commit()
        except Exception as e:
            logger.warning(f"创建索引失败: {e}")

        conn.close()

        self.checkpoint['pass0_complete'] = True
        self._save_checkpoint()

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Pass 0 完成，耗时 {elapsed/60:.1f} 分钟")

    # ============== Pass 1: 时序统计 ==============

    def run_pass1(self, force: bool = False):
        """
        Pass 1: 时序统计 - 按 object_lemma + year 统计
        """
        if self.checkpoint.get('pass1_complete') and not force and self._is_stats_db_compatible():
            logger.info("Pass 1 已完成且统计库版本匹配，跳过")
            return

        if self.checkpoint.get('pass1_complete') and not force and not self._is_stats_db_compatible():
            logger.info("检测到 temporal_stats.db 为旧版本，将自动重建 Pass 1（勘误过滤 + 概念键）")

        logger.info("=" * 60)
        logger.info("Pass 1: 时序统计")
        logger.info("=" * 60)

        start_time = datetime.now()

        # 创建统计数据库
        if self.stats_db_path.exists():
            os.remove(self.stats_db_path)

        stats_conn = sqlite3.connect(str(self.stats_db_path))
        stats_cursor = stats_conn.cursor()

        # 创建表
        stats_cursor.execute("""
            CREATE TABLE object_yearly (
                object_lemma TEXT NOT NULL,
                year INTEGER NOT NULL,
                rpu_count INTEGER DEFAULT 0,
                paper_count INTEGER DEFAULT 0,
                PRIMARY KEY (object_lemma, year)
            )
        """)

        stats_cursor.execute("""
            CREATE TABLE total_papers (
                year INTEGER PRIMARY KEY,
                count INTEGER DEFAULT 0
            )
        """)

        stats_cursor.execute("""
            CREATE TABLE meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        stats_cursor.executemany(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            [
                ("stats_schema_version", STATS_SCHEMA_VERSION),
                ("exclude_correction_papers", "1" if self.config.get('exclude_correction_papers', True) else "0"),
            ]
        )

        stats_conn.commit()

        # 连接 RPU 数据库
        rpu_conn = sqlite3.connect(self.rpu_db_path)
        rpu_cursor = rpu_conn.cursor()

        correction_filter_sql = ""
        if self.config.get('exclude_correction_papers', True):
            correction_filter_sql = f" AND {build_correction_filter_sql('p')}"
            logger.info("Pass 1 将过滤更正/勘误类标题")

        # 统计每年论文数
        logger.info("统计每年论文数...")
        rpu_cursor.execute(f"""
            SELECT p.pub_year, COUNT(DISTINCT p.paper_id)
            FROM papers p
            WHERE p.pub_year BETWEEN 2010 AND 2025
              {correction_filter_sql}
            GROUP BY p.pub_year
        """)
        for year, count in rpu_cursor.fetchall():
            stats_cursor.execute("INSERT INTO total_papers (year, count) VALUES (?, ?)", (year, count))
            logger.info(f"  {year}: {count:,} 篇论文")
        stats_conn.commit()

        # 统计 object_lemma × year
        logger.info("统计 object_lemma × year (这可能需要较长时间)...")

        # 使用 JOIN 一次性统计
        rpu_cursor.execute(f"""
            SELECT r.object_lemma, p.pub_year, COUNT(*) as rpu_count, COUNT(DISTINCT r.paper_id) as paper_count
            FROM rpu r
            JOIN papers p ON r.paper_id = p.paper_id
            WHERE r.object_lemma IS NOT NULL
              AND r.object_lemma != ''
              AND p.pub_year BETWEEN 2010 AND 2025
              {correction_filter_sql}
            GROUP BY r.object_lemma, p.pub_year
        """)

        batch = []
        batch_size = 100000
        total_inserted = 0

        for row in rpu_cursor:
            batch.append(row)
            if len(batch) >= batch_size:
                stats_cursor.executemany("""
                    INSERT INTO object_yearly (object_lemma, year, rpu_count, paper_count)
                    VALUES (?, ?, ?, ?)
                """, batch)
                stats_conn.commit()
                total_inserted += len(batch)
                elapsed = (datetime.now() - start_time).total_seconds()
                logger.info(f"Pass 1: 已插入 {total_inserted:,} 条记录 ({elapsed/60:.1f}min)")
                batch = []

        # 插入剩余
        if batch:
            stats_cursor.executemany("""
                INSERT INTO object_yearly (object_lemma, year, rpu_count, paper_count)
                VALUES (?, ?, ?, ?)
            """, batch)
            stats_conn.commit()
            total_inserted += len(batch)

        # 创建索引
        logger.info("创建索引...")
        stats_cursor.execute("CREATE INDEX idx_object_yearly_year ON object_yearly(year)")
        stats_cursor.execute("CREATE INDEX idx_object_yearly_obj ON object_yearly(object_lemma)")
        stats_conn.commit()

        rpu_conn.close()
        stats_conn.close()

        self.checkpoint['pass1_complete'] = True
        self._save_checkpoint()

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Pass 1 完成，共 {total_inserted:,} 条记录，耗时 {elapsed/60:.1f} 分钟")

    # ============== Pass 2: Diffusion + Persistence 计算 ==============

    def run_pass2(self, years: List[int] = None, force: bool = False):
        """
        Pass 2: 计算 Diffusion 和 Persistence
        """
        logger.info("=" * 60)
        logger.info("Pass 2: Diffusion + Persistence 计算")
        logger.info("=" * 60)

        years = years or list(self.config['years'])

        # 跳过已完成的年份
        if not force:
            completed = set(self.checkpoint.get('pass2_years', []))
            years = [y for y in years if y not in completed]

        if not years:
            logger.info("所有年份已完成，跳过 Pass 2")
            return

        if not self._is_stats_db_compatible():
            logger.warning("temporal_stats.db 非当前版本，建议先执行: --pass 1 --force")

        # 加载时序统计
        logger.info("加载时序统计到内存...")
        stats_conn = sqlite3.connect(str(self.stats_db_path))
        stats_cursor = stats_conn.cursor()

        stats_cursor.execute("SELECT year, count FROM total_papers")
        total_papers_by_year = {int(year): int(count) for year, count in stats_cursor.fetchall()}

        # 加载 object_yearly 数据并映射为概念级 yearly 计数
        stats_cursor.execute("SELECT object_lemma, year, paper_count FROM object_yearly")
        concept_yearly: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        row_count = 0
        for obj, year, paper_count in stats_cursor.fetchall():
            concept_key = normalize_object_concept(obj)
            if not concept_key:
                continue
            concept_yearly[concept_key][year] += int(paper_count)
            row_count += 1

        # object_lemma->concept_key 聚合时，理论上可能出现同年重复计数，按年度总论文数做上限裁剪
        for yearly_counts in concept_yearly.values():
            for y in list(yearly_counts.keys()):
                cap = total_papers_by_year.get(y)
                if cap is not None and yearly_counts[y] > cap:
                    yearly_counts[y] = cap

        logger.info(f"加载了 {len(concept_yearly):,} 个 unique concept keys ({row_count:,} 条年度记录)")

        stats_conn.close()

        # 连接 RPU 数据库
        rpu_conn = sqlite3.connect(self.rpu_db_path)
        rpu_cursor = rpu_conn.cursor()

        current_year = self.config['current_year']
        top_k = self.config['top_k']
        correction_filter_sql = ""
        if self.config.get('exclude_correction_papers', True):
            correction_filter_sql = f" AND {build_correction_filter_sql('p')}"

        for year in sorted(years):
            logger.info(f"\n{'='*40}")
            logger.info(f"处理年份: {year}")
            logger.info(f"{'='*40}")
            start_time = datetime.now()

            # 获取该年份的所有论文
            rpu_cursor.execute(f"""
                SELECT p.paper_id, r.task, r.object, r.task_lemma, r.object_lemma
                FROM papers p
                JOIN rpu r ON p.paper_id = r.paper_id
                WHERE p.pub_year = ?
                  AND r.object_lemma IS NOT NULL
                  AND r.object_lemma != ''
                  {correction_filter_sql}
                ORDER BY p.paper_id
            """, (year,))

            # 按论文分组
            paper_rpus: Dict[str, List[Tuple]] = defaultdict(list)
            for paper_id, task, obj, task_lemma, obj_lemma in rpu_cursor:
                paper_rpus[paper_id].append((task, obj, task_lemma, obj_lemma))

            logger.info(f"  论文数: {len(paper_rpus):,}")

            # 计算每篇论文的 Impact 信号
            results = []
            observable_years = current_year - year

            processed = 0
            for paper_id, rpus in paper_rpus.items():
                # 按概念键分组，取每个概念的最高 task_weight
                object_info: Dict[str, dict] = {}

                for task, obj, task_lemma, obj_lemma in rpus:
                    task_w = get_task_weight(task_lemma or task)
                    concept_key = normalize_object_concept(obj_lemma or obj or '')
                    if not concept_key:
                        continue

                    if concept_key not in object_info or task_w > object_info[concept_key]['task_weight']:
                        object_info[concept_key] = {
                            'object': obj,
                            'object_lemma': obj_lemma,
                            'concept_key': concept_key,
                            'task': task,
                            'task_lemma': task_lemma or lemmatize_task(task),
                            'task_weight': task_w,
                        }

                # 计算每个 object 的贡献
                diffusion_contribs = []

                for concept_key, info in object_info.items():
                    yearly_counts = concept_yearly.get(concept_key, {})

                    # prior_papers: 发表前有多少论文用过
                    prior_papers = sum(
                        yearly_counts.get(y, 0)
                        for y in range(2010, year)
                    )

                    # scarcity_weight
                    scarcity_w = 1.0 / (prior_papers + 1)

                    # post_papers: 发表后有多少论文用过
                    post_papers = sum(
                        yearly_counts.get(y, 0)
                        for y in range(year + 1, current_year + 1)
                    )

                    # Diffusion contribution
                    diff_contrib = info['task_weight'] * scarcity_w * post_papers

                    # Persistence: active_years
                    active_years = sum(
                        1 for y in range(year + 1, current_year + 1)
                        if yearly_counts.get(y, 0) > 0
                    )
                    survival_ratio = active_years / observable_years if observable_years > 0 else 0

                    # Persistence contribution
                    pers_contrib = info['task_weight'] * scarcity_w * survival_ratio

                    diffusion_contribs.append({
                        **info,
                        'prior_papers': prior_papers,
                        'scarcity_weight': scarcity_w,
                        'post_papers': post_papers,
                        'diffusion_contrib': diff_contrib,
                        'active_years': active_years,
                        'survival_ratio': survival_ratio,
                        'persistence_contrib': pers_contrib,
                    })

                # Top-K 聚合
                diffusion_contribs.sort(key=lambda x: x['diffusion_contrib'], reverse=True)
                top_objects = diffusion_contribs[:top_k]

                diffusion_raw = sum(x['diffusion_contrib'] for x in top_objects)
                persistence_raw = sum(x['persistence_contrib'] for x in top_objects)

                # 计算 avg_survival（加权平均）
                sum_weight = sum(x['task_weight'] * x['scarcity_weight'] for x in top_objects)
                avg_survival = persistence_raw / sum_weight if sum_weight > 0 else 0

                results.append({
                    'paper_id': paper_id,
                    'pub_year': year,
                    'diffusion_raw': diffusion_raw,
                    'persistence_raw': persistence_raw,
                    'avg_survival': avg_survival,
                    'observable_years': observable_years,
                    'object_count': len(object_info),
                    'top_objects': top_objects,
                })

                processed += 1
                if processed % 100000 == 0:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    rate = processed / elapsed if elapsed > 0 else 0
                    logger.info(f"  进度: {processed:,}/{len(paper_rpus):,} ({rate:.0f} 篇/s)")

            # 保存结果
            output_path = self.output_dir / f'impact_signals_{year}.jsonl'
            with open(output_path, 'w', encoding='utf-8') as f:
                for r in results:
                    f.write(json.dumps(r, ensure_ascii=False) + '\n')

            # 更新 checkpoint
            if 'pass2_years' not in self.checkpoint:
                self.checkpoint['pass2_years'] = []
            self.checkpoint['pass2_years'].append(year)
            self._save_checkpoint()

            elapsed = (datetime.now() - start_time).total_seconds()
            rate = len(results) / elapsed if elapsed > 0 else 0
            logger.info(f"  完成: {len(results):,} 篇论文, {elapsed:.1f}s ({rate:.0f} 篇/s)")

        rpu_conn.close()

    # ============== Pass 3: 归一化 + 输出 ==============

    def run_pass3(self, force: bool = False):
        """
        Pass 3: 归一化 + 最终输出
        """
        if self.checkpoint.get('pass3_complete') and not force:
            logger.info("Pass 3 已完成，跳过")
            return

        logger.info("=" * 60)
        logger.info("Pass 3: 归一化 + 输出")
        logger.info("=" * 60)

        threshold = self.config['persistence_threshold']
        all_stats = []

        for year in self.config['years']:
            signals_path = self.output_dir / f'impact_signals_{year}.jsonl'
            if not signals_path.exists():
                logger.warning(f"跳过 {year}：信号文件不存在")
                continue

            logger.info(f"处理年份: {year}")

            # 加载信号
            results = []
            with open(signals_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        results.append(json.loads(line))

            if not results:
                continue

            # 计算 log(diffusion + 1)
            log_diffusions = [math.log(r['diffusion_raw'] + 1) for r in results]

            # 年度百分位归一化
            sorted_diffs = sorted(log_diffusions)
            n = len(sorted_diffs)

            for r in results:
                log_d = math.log(r['diffusion_raw'] + 1)
                # 计算百分位
                rank = sum(1 for d in sorted_diffs if d < log_d)
                percentile = (rank / n) * 100 if n > 0 else 0
                r['diffusion_norm'] = round(percentile, 2)

                # Persistence gate
                avg_survival = r['avg_survival']
                p_gate = min(avg_survival / threshold, 1.0)
                r['persistence_gate'] = round(p_gate, 3)

                # Impact score
                r['impact_score'] = round(r['diffusion_norm'] * p_gate, 2)

                # 简化输出（移除详细的 top_objects）
                if 'top_objects' in r:
                    r['top_objects_summary'] = [
                        {
                            'object': o['object'],
                            'concept_key': o.get('concept_key', ''),
                            'task': o['task'],
                            'diffusion_contrib': round(o['diffusion_contrib'], 2),
                            'survival_ratio': round(o['survival_ratio'], 3),
                        }
                        for o in r['top_objects'][:3]
                    ]
                    del r['top_objects']

            # 保存最终结果
            output_path = self.output_dir / f'impact_final_{year}.jsonl'
            with open(output_path, 'w', encoding='utf-8') as f:
                for r in results:
                    f.write(json.dumps(r, ensure_ascii=False) + '\n')

            # 统计
            scores = [r['impact_score'] for r in results]
            mean_score = sum(scores) / len(scores) if scores else 0
            median_score = sorted(scores)[len(scores)//2] if scores else 0
            max_score = max(scores) if scores else 0
            high_impact = sum(1 for s in scores if s >= 50) / len(scores) * 100 if scores else 0

            stats = {
                'year': year,
                'count': len(results),
                'mean': round(mean_score, 2),
                'median': round(median_score, 2),
                'max': round(max_score, 2),
                'high_impact_pct': round(high_impact, 2),
            }
            all_stats.append(stats)

            logger.info(f"  {year}: {len(results):,} 篇, "
                       f"mean={mean_score:.2f}, median={median_score:.2f}, "
                       f"max={max_score:.2f}, high_impact={high_impact:.1f}%")

        # 保存统计汇总
        stats_path = self.output_dir / 'impact_summary.json'
        with open(stats_path, 'w', encoding='utf-8') as f:
            json.dump(all_stats, f, indent=2)

        self.checkpoint['pass3_complete'] = True
        self._save_checkpoint()

        logger.info("\nPass 3 完成")
        logger.info(f"汇总统计已保存到: {stats_path}")

    # ============== 主运行函数 ==============

    def run_all(self, years: List[int] = None, force: bool = False):
        """运行所有 Pass"""
        start_time = datetime.now()

        logger.info("=" * 60)
        logger.info("Impact V5.0 计算开始")
        logger.info(f"配置: Top-{self.config['top_k']} 聚合, 持续性阈值={self.config['persistence_threshold']}")
        logger.info(f"配置: 勘误过滤={self.config.get('exclude_correction_papers', True)}, 概念匹配=normalize_object_concept")
        logger.info("=" * 60)

        self.run_pass0(force=force)
        self.run_pass1(force=force)
        self.run_pass2(years=years, force=force)
        self.run_pass3(force=force)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info("\n" + "=" * 60)
        logger.info(f"全部完成，总耗时 {elapsed/3600:.2f} 小时")
        logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='Impact V5.0 计算')
    parser.add_argument('--pass', dest='pass_num', type=int, choices=[0, 1, 2, 3],
                       help='只运行指定的 Pass')
    parser.add_argument('--year', type=int, help='只处理指定年份')
    parser.add_argument('--years', type=str, help='年份范围，如 2010-2015')
    parser.add_argument('--force', action='store_true', help='强制重新运行')
    parser.add_argument('--resume', action='store_true', help='断点续传（默认行为）')
    parser.add_argument('--config', type=str, default=None, help='配置文件路径（JSON）')

    args = parser.parse_args()

    calculator = ImpactCalculator(config=build_runtime_config(args.config))

    # 解析年份
    years = None
    if args.year:
        years = [args.year]
    elif args.years:
        start, end = map(int, args.years.split('-'))
        years = list(range(start, end + 1))

    # 运行
    if args.pass_num is not None:
        if args.pass_num == 0:
            calculator.run_pass0(force=args.force)
        elif args.pass_num == 1:
            calculator.run_pass1(force=args.force)
        elif args.pass_num == 2:
            calculator.run_pass2(years=years, force=args.force)
        elif args.pass_num == 3:
            calculator.run_pass3(force=args.force)
    else:
        calculator.run_all(years=years, force=args.force)


if __name__ == '__main__':
    main()

