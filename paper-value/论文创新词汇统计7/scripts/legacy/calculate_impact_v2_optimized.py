# -*- coding: utf-8 -*-
"""
Impact V5.0 计算脚本 - 极限优化版

优化点：
1. Pass 0: SQLite UDF + PRAGMA 优化（关闭同步、内存日志）
2. Pass 1: ATTACH + INSERT SELECT 纯 SQL（避免 Python 循环）
3. Pass 2: NumPy 向量化 + 预计算累积和 + 多进程
4. Pass 3: NumPy searchsorted（比 bisect 更快）

设计文档: IMPACT_V2_DESIGN.md (V5.0)

Usage:
    python calculate_impact_v2_optimized.py                    # 全量运行
    python calculate_impact_v2_optimized.py --pass 0          # 只运行 Pass 0
    python calculate_impact_v2_optimized.py --year 2015       # 单年测试
    python calculate_impact_v2_optimized.py --workers 8       # 指定并行数
"""

import os
import sys
import json
import sqlite3
import logging
import argparse
import math
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Set
from multiprocessing import Pool, cpu_count
import pickle

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

# 尝试导入 NumPy（可选优化）
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    print("Warning: NumPy not found, using fallback implementation")

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
    'top_k': 3,
    'persistence_threshold': 0.5,
    'current_year': int(_runtime.get('current_year', 2025)),
    'min_observable_years': 1,
    'num_workers': 4,
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
    })
    return merged

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

# Lemmatization 规则
LEMMA_RULES = {
    'proposed': 'propose', 'proposing': 'propose', 'proposes': 'propose',
    'developed': 'develop', 'developing': 'develop', 'develops': 'develop',
    'designed': 'design', 'designing': 'design', 'designs': 'design',
    'implemented': 'implement', 'implementing': 'implement', 'implements': 'implement',
    'applied': 'apply', 'applying': 'apply', 'applies': 'apply',
    'used': 'use', 'using': 'use', 'uses': 'use',
    'analyzed': 'analyze', 'analyzing': 'analyze', 'analyzes': 'analyze',
    'analysed': 'analyze', 'analysing': 'analyze', 'analyses': 'analyze',
    'studied': 'study', 'studying': 'study', 'studies': 'study',
    'showed': 'show', 'showing': 'show', 'shows': 'show', 'shown': 'show',
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

    if task in LEMMA_RULES:
        return LEMMA_RULES[task]

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
        base = task[:-1]
        if base in TASK_WEIGHTS:
            return base
    if task.endswith('s') and not task.endswith('ss') and len(task) > 2:
        base = task[:-1]
        if base in TASK_WEIGHTS:
            return base

    return task


def lemmatize_object(obj: str) -> str:
    """简单的 object lemmatization"""
    if not obj:
        return ''
    obj = obj.lower().strip()

    if len(obj) <= 3:
        return obj

    if obj.endswith('ies') and len(obj) > 4:
        return obj[:-3] + 'y'
    if obj.endswith('es') and len(obj) > 3:
        if obj.endswith('ses') or obj.endswith('xes') or obj.endswith('ches') or obj.endswith('shes'):
            return obj[:-2]
        return obj[:-1]
    if obj.endswith('s') and not obj.endswith('ss') and len(obj) > 3:
        if not obj.endswith('sis') and not obj.endswith('ous') and not obj.endswith('ess'):
            return obj[:-1]

    return obj


def get_task_weight(task: str) -> float:
    """获取任务动词权重"""
    task_lemma = lemmatize_task(task)
    return TASK_WEIGHTS.get(task_lemma, 1.0)


def optimize_sqlite_for_speed(conn):
    """优化 SQLite 连接以获得最大写入速度"""
    cursor = conn.cursor()
    cursor.execute("PRAGMA synchronous = OFF")      # 关闭同步写入
    cursor.execute("PRAGMA journal_mode = MEMORY")  # 内存日志
    cursor.execute("PRAGMA cache_size = -2000000")  # 2GB 缓存
    cursor.execute("PRAGMA temp_store = MEMORY")    # 临时表存内存
    cursor.execute("PRAGMA mmap_size = 30000000000") # 30GB mmap
    conn.commit()


# ============== 预计算数据结构（NumPy 优化版）==============

class ObjectStats:
    """预计算的 object 统计数据（NumPy 优化）"""

    def __init__(self):
        self.cumsum = {}        # object -> cumsum array (16,)
        self.active_mask = {}   # object -> bool array (16,)
        self.year_base = 2010
        self.year_count = 16

    def build(self, object_yearly: Dict[str, Dict[int, int]]):
        """从 object_yearly 构建预计算数据"""
        logger.info("构建预计算统计数据 (NumPy 优化)...")
        start_time = datetime.now()

        if HAS_NUMPY:
            for obj, years_data in object_yearly.items():
                # 构建年度计数数组
                counts = np.zeros(self.year_count, dtype=np.int32)
                for y in range(self.year_base, self.year_base + self.year_count):
                    counts[y - self.year_base] = years_data.get(y, 0)

                # 累积和
                self.cumsum[obj] = np.cumsum(counts)
                # 活跃掩码
                self.active_mask[obj] = counts > 0
        else:
            # 无 NumPy 的 fallback
            for obj, years_data in object_yearly.items():
                cumsum = []
                active = []
                total = 0
                for y in range(self.year_base, self.year_base + self.year_count):
                    count = years_data.get(y, 0)
                    total += count
                    cumsum.append(total)
                    active.append(count > 0)
                self.cumsum[obj] = cumsum
                self.active_mask[obj] = active

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"预计算完成: {len(self.cumsum):,} objects, {elapsed:.1f}s")

    def get_prior_papers(self, obj: str, year: int) -> int:
        """O(1) 获取发表前论文数"""
        if obj not in self.cumsum:
            return 0
        idx = year - 1 - self.year_base
        if idx < 0:
            return 0
        if HAS_NUMPY:
            return int(self.cumsum[obj][idx])
        else:
            return self.cumsum[obj][idx]

    def get_post_papers(self, obj: str, year: int, max_year: int = 2025) -> int:
        """O(1) 获取发表后论文数"""
        if obj not in self.cumsum:
            return 0
        max_idx = min(max_year - self.year_base, self.year_count - 1)
        year_idx = year - self.year_base
        if year_idx < 0:
            year_idx = -1
        if HAS_NUMPY:
            total = int(self.cumsum[obj][max_idx])
            before = int(self.cumsum[obj][year_idx]) if year_idx >= 0 else 0
        else:
            total = self.cumsum[obj][max_idx]
            before = self.cumsum[obj][year_idx] if year_idx >= 0 else 0
        return total - before

    def get_active_years(self, obj: str, year: int, max_year: int = 2025) -> int:
        """O(1) 获取活跃年份数（NumPy 向量化）"""
        if obj not in self.active_mask:
            return 0
        start_idx = year + 1 - self.year_base
        end_idx = min(max_year - self.year_base + 1, self.year_count)
        if start_idx >= end_idx or start_idx < 0:
            return 0
        if HAS_NUMPY:
            return int(np.sum(self.active_mask[obj][start_idx:end_idx]))
        else:
            return sum(self.active_mask[obj][start_idx:end_idx])

    def get_all(self, obj: str, year: int, max_year: int = 2025) -> Tuple[int, int, int]:
        """一次性获取 prior, post, active（减少函数调用开销）"""
        if obj not in self.cumsum:
            return 0, 0, 0

        year_idx = year - self.year_base
        max_idx = min(max_year - self.year_base, self.year_count - 1)
        start_idx = year + 1 - self.year_base
        end_idx = min(max_year - self.year_base + 1, self.year_count)

        if HAS_NUMPY:
            cumsum = self.cumsum[obj]
            active = self.active_mask[obj]

            prior = int(cumsum[year_idx - 1]) if year_idx > 0 else 0
            total = int(cumsum[max_idx])
            before = int(cumsum[year_idx]) if year_idx >= 0 else 0
            post = total - before

            if start_idx >= end_idx or start_idx < 0:
                active_years = 0
            else:
                active_years = int(np.sum(active[start_idx:end_idx]))
        else:
            cumsum = self.cumsum[obj]
            active = self.active_mask[obj]

            prior = cumsum[year_idx - 1] if year_idx > 0 else 0
            total = cumsum[max_idx]
            before = cumsum[year_idx] if year_idx >= 0 else 0
            post = total - before

            if start_idx >= end_idx or start_idx < 0:
                active_years = 0
            else:
                active_years = sum(active[start_idx:end_idx])

        return prior, post, active_years

    def save(self, path: str):
        """保存到文件"""
        with open(path, 'wb') as f:
            pickle.dump({
                'cumsum': self.cumsum,
                'active_mask': self.active_mask,
                'year_base': self.year_base,
                'year_count': self.year_count,
            }, f, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load(cls, path: str) -> 'ObjectStats':
        """从文件加载"""
        stats = cls()
        with open(path, 'rb') as f:
            data = pickle.load(f)
            stats.cumsum = data['cumsum']
            stats.active_mask = data['active_mask']
            stats.year_base = data.get('year_base', 2010)
            stats.year_count = data.get('year_count', 16)
        return stats


# ============== 多进程处理单年 ==============

def process_single_year(args):
    """处理单个年份（用于多进程）"""
    year, rpu_db_path, stats_cache_path, output_dir, config = args

    # 加载预计算数据
    stats = ObjectStats.load(stats_cache_path)

    # 连接数据库
    rpu_conn = sqlite3.connect(rpu_db_path)
    rpu_cursor = rpu_conn.cursor()

    current_year = config['current_year']
    top_k = config['top_k']
    observable_years = current_year - year

    # 获取该年份的所有论文 RPU
    rpu_cursor.execute("""
        SELECT p.paper_id, r.task, r.object, r.task_lemma, r.object_lemma
        FROM papers p
        JOIN rpu r ON p.paper_id = r.paper_id
        WHERE p.pub_year = ?
          AND r.object_lemma IS NOT NULL
          AND r.object_lemma != ''
        ORDER BY p.paper_id
    """, (year,))

    # 按论文分组
    paper_rpus = defaultdict(list)
    for paper_id, task, obj, task_lemma, obj_lemma in rpu_cursor:
        paper_rpus[paper_id].append((task, obj, task_lemma, obj_lemma))

    rpu_conn.close()

    # 计算每篇论文的 Impact 信号
    results = []

    for paper_id, rpus in paper_rpus.items():
        # 按 object_lemma 分组，取最高 task_weight
        object_info = {}

        for task, obj, task_lemma, obj_lemma in rpus:
            task_w = get_task_weight(task_lemma or task)

            if obj_lemma not in object_info or task_w > object_info[obj_lemma]['task_weight']:
                object_info[obj_lemma] = {
                    'object': obj,
                    'object_lemma': obj_lemma,
                    'task': task,
                    'task_lemma': task_lemma or lemmatize_task(task),
                    'task_weight': task_w,
                }

        # 计算每个 object 的贡献
        diffusion_contribs = []

        for obj_lemma, info in object_info.items():
            # O(1) 批量查询
            prior_papers, post_papers, active_years = stats.get_all(obj_lemma, year, current_year)

            scarcity_w = 1.0 / (prior_papers + 1)
            diff_contrib = info['task_weight'] * scarcity_w * post_papers
            survival_ratio = active_years / observable_years if observable_years > 0 else 0
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

    # 保存结果
    output_path = Path(output_dir) / f'impact_signals_{year}.jsonl'
    with open(output_path, 'w', encoding='utf-8') as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    return year, len(results)


class ImpactCalculatorOptimized:
    """Impact V5.0 计算器 - 极限优化版"""

    def __init__(self, config: dict = None):
        self.config = config or CONFIG
        self.rpu_db_path = self.config['rpu_db_path']
        self.output_dir = Path(self.config['output_dir'])
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.stats_db_path = self.output_dir / 'temporal_stats.db'
        self.stats_cache_path = self.output_dir / 'object_stats.pkl'
        self.checkpoint_path = self.output_dir / 'checkpoint.json'
        self.checkpoint = self._load_checkpoint()

    def _load_checkpoint(self) -> dict:
        if self.checkpoint_path.exists():
            with open(self.checkpoint_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {'pass0_complete': False, 'pass1_complete': False, 'pass2_years': [], 'pass3_complete': False}

    def _save_checkpoint(self):
        with open(self.checkpoint_path, 'w', encoding='utf-8') as f:
            json.dump(self.checkpoint, f, indent=2)

    # ============== Pass 0: SQLite UDF + PRAGMA 优化 ==============

    def run_pass0(self, force: bool = False):
        """Pass 0: 使用 SQLite UDF + PRAGMA 优化"""
        if self.checkpoint.get('pass0_complete') and not force:
            logger.info("Pass 0 已完成，跳过")
            return

        logger.info("=" * 60)
        logger.info("Pass 0: 预处理 - SQLite UDF + PRAGMA 极限优化")
        logger.info("=" * 60)

        conn = sqlite3.connect(self.rpu_db_path)

        # PRAGMA 优化（关闭同步，极限速度）
        logger.info("应用 PRAGMA 优化...")
        optimize_sqlite_for_speed(conn)

        cursor = conn.cursor()

        # 检查列是否存在
        cursor.execute("PRAGMA table_info(rpu)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'object_lemma' not in columns:
            logger.info("添加 object_lemma 列...")
            cursor.execute("ALTER TABLE rpu ADD COLUMN object_lemma TEXT")

        if 'task_lemma' not in columns:
            logger.info("添加 task_lemma 列...")
            cursor.execute("ALTER TABLE rpu ADD COLUMN task_lemma TEXT")

        conn.commit()

        # 检查需要更新的数量
        cursor.execute("SELECT COUNT(*) FROM rpu WHERE object_lemma IS NULL")
        total = cursor.fetchone()[0]
        logger.info(f"需要处理的 RPU 数量: {total:,}")

        if total == 0:
            logger.info("所有 RPU 已有 lemma，跳过")
            self.checkpoint['pass0_complete'] = True
            self._save_checkpoint()
            conn.close()
            return

        # 注册 UDF
        logger.info("注册 SQLite UDF...")
        conn.create_function("py_lemmatize_task", 1, lemmatize_task)
        conn.create_function("py_lemmatize_object", 1, lemmatize_object)

        # 一条 SQL 完成所有更新
        logger.info("执行批量更新...")
        start_time = datetime.now()

        cursor.execute("""
            UPDATE rpu
            SET task_lemma = py_lemmatize_task(task),
                object_lemma = py_lemmatize_object(object)
            WHERE object_lemma IS NULL
        """)

        conn.commit()

        # 创建索引
        logger.info("创建索引...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rpu_object_lemma ON rpu(object_lemma)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rpu_task_lemma ON rpu(task_lemma)")
        conn.commit()

        conn.close()

        self.checkpoint['pass0_complete'] = True
        self._save_checkpoint()

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Pass 0 完成，耗时 {elapsed/60:.1f} 分钟")

    # ============== Pass 1: ATTACH + INSERT SELECT 纯 SQL ==============

    def run_pass1(self, force: bool = False):
        """Pass 1: 纯 SQL 时序统计（ATTACH 优化）"""
        if self.checkpoint.get('pass1_complete') and not force:
            logger.info("Pass 1 已完成，跳过")
            return

        logger.info("=" * 60)
        logger.info("Pass 1: 时序统计 - ATTACH + INSERT SELECT 优化")
        logger.info("=" * 60)

        start_time = datetime.now()

        # 创建统计数据库
        if self.stats_db_path.exists():
            os.remove(self.stats_db_path)

        stats_conn = sqlite3.connect(str(self.stats_db_path))
        optimize_sqlite_for_speed(stats_conn)
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

        stats_conn.commit()

        # ATTACH 源数据库
        logger.info("ATTACH 源数据库...")
        stats_cursor.execute(f"ATTACH DATABASE '{self.rpu_db_path}' AS rpu_db")

        # 统计每年论文数（纯 SQL）
        logger.info("统计每年论文数...")
        stats_cursor.execute("""
            INSERT INTO total_papers (year, count)
            SELECT pub_year, COUNT(DISTINCT paper_id)
            FROM rpu_db.papers
            WHERE pub_year BETWEEN 2010 AND 2025
            GROUP BY pub_year
        """)
        stats_conn.commit()

        # 打印论文数
        stats_cursor.execute("SELECT year, count FROM total_papers ORDER BY year")
        for year, count in stats_cursor.fetchall():
            logger.info(f"  {year}: {count:,} 篇论文")

        # 统计 object_lemma × year（纯 SQL，一条语句完成）
        logger.info("统计 object_lemma × year (纯 SQL)...")

        stats_cursor.execute("""
            INSERT INTO object_yearly (object_lemma, year, rpu_count, paper_count)
            SELECT r.object_lemma, p.pub_year, COUNT(*), COUNT(DISTINCT r.paper_id)
            FROM rpu_db.rpu r
            JOIN rpu_db.papers p ON r.paper_id = p.paper_id
            WHERE r.object_lemma IS NOT NULL
              AND r.object_lemma != ''
              AND p.pub_year BETWEEN 2010 AND 2025
            GROUP BY r.object_lemma, p.pub_year
        """)

        stats_conn.commit()

        # 统计插入数量
        stats_cursor.execute("SELECT COUNT(*) FROM object_yearly")
        total_inserted = stats_cursor.fetchone()[0]

        # 创建索引
        logger.info("创建索引...")
        stats_cursor.execute("CREATE INDEX idx_object_yearly_year ON object_yearly(year)")
        stats_cursor.execute("CREATE INDEX idx_object_yearly_obj ON object_yearly(object_lemma)")
        stats_conn.commit()

        # DETACH
        stats_cursor.execute("DETACH DATABASE rpu_db")
        stats_conn.close()

        # 构建预计算缓存
        logger.info("构建预计算统计缓存...")
        self._build_stats_cache()

        self.checkpoint['pass1_complete'] = True
        self._save_checkpoint()

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Pass 1 完成，共 {total_inserted:,} 条记录，耗时 {elapsed/60:.1f} 分钟")

    def _build_stats_cache(self):
        """构建预计算统计缓存（NumPy 优化）"""
        stats_conn = sqlite3.connect(str(self.stats_db_path))
        stats_cursor = stats_conn.cursor()

        stats_cursor.execute("SELECT object_lemma, year, paper_count FROM object_yearly")
        object_yearly = defaultdict(dict)
        for obj, year, paper_count in stats_cursor.fetchall():
            object_yearly[obj][year] = paper_count

        stats_conn.close()

        # 构建预计算数据
        stats = ObjectStats()
        stats.build(object_yearly)
        stats.save(str(self.stats_cache_path))

        logger.info(f"预计算缓存已保存: {self.stats_cache_path}")

    # ============== Pass 2: 多进程优化 ==============

    def run_pass2(self, years: List[int] = None, force: bool = False, num_workers: int = None):
        """Pass 2: 多进程并行计算"""
        logger.info("=" * 60)
        logger.info("Pass 2: Diffusion + Persistence (多进程 + NumPy)")
        logger.info("=" * 60)

        years = years or list(self.config['years'])
        num_workers = num_workers or self.config.get('num_workers', 4)

        # 跳过已完成的年份
        if not force:
            completed = set(self.checkpoint.get('pass2_years', []))
            years = [y for y in years if y not in completed]

        if not years:
            logger.info("所有年份已完成，跳过 Pass 2")
            return

        # 确保预计算缓存存在
        if not self.stats_cache_path.exists():
            logger.info("预计算缓存不存在，正在构建...")
            self._build_stats_cache()

        logger.info(f"待处理年份: {years}")
        logger.info(f"并行进程数: {num_workers}")
        logger.info(f"NumPy 优化: {'已启用' if HAS_NUMPY else '未启用'}")

        start_time = datetime.now()

        # 准备参数
        args_list = [
            (year, self.rpu_db_path, str(self.stats_cache_path), str(self.output_dir), self.config)
            for year in years
        ]

        # 多进程处理
        if num_workers > 1 and len(years) > 1:
            with Pool(processes=num_workers) as pool:
                results = pool.map(process_single_year, args_list)
        else:
            results = [process_single_year(args) for args in args_list]

        # 更新 checkpoint
        for year, count in results:
            if 'pass2_years' not in self.checkpoint:
                self.checkpoint['pass2_years'] = []
            self.checkpoint['pass2_years'].append(year)
            logger.info(f"  {year}: {count:,} 篇论文")

        self._save_checkpoint()

        elapsed = (datetime.now() - start_time).total_seconds()
        total_papers = sum(count for _, count in results)
        rate = total_papers / elapsed if elapsed > 0 else 0
        logger.info(f"Pass 2 完成: {total_papers:,} 篇论文, {elapsed:.1f}s ({rate:.0f} 篇/s)")

    # ============== Pass 3: NumPy searchsorted 优化 ==============

    def run_pass3(self, force: bool = False):
        """Pass 3: 归一化（NumPy searchsorted 优化）"""
        if self.checkpoint.get('pass3_complete') and not force:
            logger.info("Pass 3 已完成，跳过")
            return

        logger.info("=" * 60)
        logger.info("Pass 3: 归一化 (NumPy searchsorted 优化)")
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

            n = len(results)

            if HAS_NUMPY:
                # NumPy 向量化计算
                log_diffs = np.array([math.log(r['diffusion_raw'] + 1) for r in results])
                sorted_indices = np.argsort(log_diffs)
                sorted_diffs = log_diffs[sorted_indices]

                # 使用 searchsorted 计算百分位
                ranks = np.searchsorted(sorted_diffs, log_diffs)
                percentiles = (ranks / n) * 100

                for i, r in enumerate(results):
                    r['diffusion_norm'] = round(float(percentiles[i]), 2)
                    avg_survival = r['avg_survival']
                    p_gate = min(avg_survival / threshold, 1.0)
                    r['persistence_gate'] = round(p_gate, 3)
                    r['impact_score'] = round(r['diffusion_norm'] * p_gate, 2)

                    if 'top_objects' in r:
                        r['top_objects_summary'] = [
                            {
                                'object': o['object'],
                                'task': o['task'],
                                'diffusion_contrib': round(o['diffusion_contrib'], 2),
                                'survival_ratio': round(o['survival_ratio'], 3),
                            }
                            for o in r['top_objects'][:3]
                        ]
                        del r['top_objects']
            else:
                # Fallback: bisect
                import bisect
                log_diffs = [math.log(r['diffusion_raw'] + 1) for r in results]
                sorted_diffs = sorted(log_diffs)

                for i, r in enumerate(results):
                    rank = bisect.bisect_left(sorted_diffs, log_diffs[i])
                    percentile = (rank / n) * 100
                    r['diffusion_norm'] = round(percentile, 2)

                    avg_survival = r['avg_survival']
                    p_gate = min(avg_survival / threshold, 1.0)
                    r['persistence_gate'] = round(p_gate, 3)
                    r['impact_score'] = round(r['diffusion_norm'] * p_gate, 2)

                    if 'top_objects' in r:
                        r['top_objects_summary'] = [
                            {
                                'object': o['object'],
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

            logger.info(f"  {year}: {len(results):,} 篇, mean={mean_score:.2f}, "
                       f"median={median_score:.2f}, high_impact={high_impact:.1f}%")

        # 保存统计汇总
        stats_path = self.output_dir / 'impact_summary.json'
        with open(stats_path, 'w', encoding='utf-8') as f:
            json.dump(all_stats, f, indent=2)

        self.checkpoint['pass3_complete'] = True
        self._save_checkpoint()

        logger.info(f"\nPass 3 完成，汇总统计已保存: {stats_path}")

    # ============== 主运行函数 ==============

    def run_all(self, years: List[int] = None, force: bool = False, num_workers: int = None):
        """运行所有 Pass"""
        start_time = datetime.now()

        logger.info("=" * 60)
        logger.info("Impact V5.0 计算 - 极限优化版")
        logger.info(f"配置: Top-{self.config['top_k']}, 阈值={self.config['persistence_threshold']}")
        logger.info(f"并行: {num_workers or self.config.get('num_workers', 4)} 进程")
        logger.info(f"NumPy: {'已启用' if HAS_NUMPY else '未启用'}")
        logger.info("=" * 60)

        self.run_pass0(force=force)
        self.run_pass1(force=force)
        self.run_pass2(years=years, force=force, num_workers=num_workers)
        self.run_pass3(force=force)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info("\n" + "=" * 60)
        logger.info(f"全部完成，总耗时 {elapsed/3600:.2f} 小时")
        logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='Impact V5.0 计算 - 极限优化版')
    parser.add_argument('--pass', dest='pass_num', type=int, choices=[0, 1, 2, 3],
                       help='只运行指定的 Pass')
    parser.add_argument('--year', type=int, help='只处理指定年份')
    parser.add_argument('--years', type=str, help='年份范围，如 2010-2015')
    parser.add_argument('--force', action='store_true', help='强制重新运行')
    parser.add_argument('--workers', type=int, default=4, help='并行进程数（默认4）')
    parser.add_argument('--config', type=str, default=None, help='配置文件路径（JSON）')

    args = parser.parse_args()

    config = build_runtime_config(args.config)
    config['num_workers'] = args.workers

    calculator = ImpactCalculatorOptimized(config)

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
            calculator.run_pass2(years=years, force=args.force, num_workers=args.workers)
        elif args.pass_num == 3:
            calculator.run_pass3(force=args.force)
    else:
        calculator.run_all(years=years, force=args.force, num_workers=args.workers)


if __name__ == '__main__':
    main()
