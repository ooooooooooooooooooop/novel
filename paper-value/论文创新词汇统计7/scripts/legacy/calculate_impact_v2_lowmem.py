# -*- coding: utf-8 -*-
"""
Impact V5.0 计算脚本 - 低内存版

核心改动：不预加载 132M objects 到内存，改用 SQLite 实时查询
内存占用：< 4GB（vs 原版 96GB+）

设计文档: IMPACT_V2_DESIGN.md (V5.0)
"""

import os
import sys
import json
import sqlite3
import logging
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Tuple, Optional

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

_default_impact_dir = Path(_paths.get("impact_output_dir", str(PROJECT_ROOT / "artifacts" / "runtime" / "impact_output")))
_default_temporal_db_path = _paths.get("legacy_temporal_db_path", str(_default_impact_dir / "temporal_stats.db"))

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
    'temporal_db_path': _default_temporal_db_path,
    'output_dir': _paths['impact_output_dir'],
    'years': get_years(_runtime),
    'top_k': 3,
    'persistence_threshold': 0.5,
    'current_year': int(_runtime.get('current_year', 2025)),
    'min_observable_years': 1,
    'batch_size': 10000,  # 每批处理的论文数
    'temporal_cache_size': 200000,  # 热门 object LRU 缓存
}


def build_runtime_config(config_path: str = None) -> dict:
    cfg = load_project_config(config_path)
    paths = get_paths(cfg)
    runtime = get_runtime(cfg)
    merged = dict(CONFIG)
    impact_dir = paths['impact_output_dir']
    merged.update({
        'rpu_db_path': paths['rpu_db_path'],
        'temporal_db_path': paths.get('legacy_temporal_db_path', str(Path(impact_dir) / 'temporal_stats.db')),
        'output_dir': impact_dir,
        'years': get_years(runtime),
        'current_year': int(runtime.get('current_year', 2025)),
    })
    return merged

# Task 权重表
TASK_WEIGHTS = {
    'invent': 1.5, 'pioneer': 1.5, 'propose': 1.5, 'discover': 1.5,
    'devise': 1.5, 'originate': 1.5, 'innovate': 1.5,
    'develop': 1.2, 'design': 1.2, 'implement': 1.2, 'build': 1.2,
    'create': 1.2, 'construct': 1.2, 'establish': 1.2,
    'improve': 1.1, 'enhance': 1.1, 'extend': 1.1, 'optimize': 1.1,
    'refine': 1.1, 'upgrade': 1.1, 'advance': 1.1,
    'apply': 0.8, 'use': 0.8, 'employ': 0.8, 'utilize': 0.8,
    'adopt': 0.8, 'deploy': 0.8, 'leverage': 0.8,
    'analyze': 0.6, 'study': 0.6, 'examine': 0.6, 'investigate': 0.6,
    'explore': 0.6, 'assess': 0.6, 'evaluate': 0.6,
    'describe': 0.3, 'report': 0.3, 'present': 0.3, 'show': 0.3,
    'review': 0.3, 'summarize': 0.3, 'discuss': 0.3, 'demonstrate': 0.3,
}


def get_task_weight(task_lemma: str) -> float:
    """获取任务权重"""
    if not task_lemma:
        return 1.0
    return TASK_WEIGHTS.get(task_lemma.lower(), 1.0)


class TemporalStatsDB:
    """
    基于 SQLite 的时序统计查询（低内存版）

    不预加载数据，每次查询时实时从数据库获取
    使用 LRU 缓存热门 object 以提高性能
    """

    def __init__(self, db_path: str, cache_size: int = 100000):
        self.db_path = db_path
        self.conn = None
        self.cache_size = cache_size

        # 简单的 LRU 缓存（只缓存最常用的 objects）
        self.cache = {}
        self.cache_order = []

        # 预加载年度论文数（很小，只有16个数字）
        self.yearly_papers = {}

    def connect(self):
        """连接数据库"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

        # 优化读取性能
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA cache_size = -500000")  # 500MB cache
        cursor.execute("PRAGMA mmap_size = 10000000000")  # 10GB mmap
        cursor.execute("PRAGMA temp_store = MEMORY")

        # 加载年度论文数
        cursor.execute("SELECT year, count FROM total_papers")
        for row in cursor.fetchall():
            self.yearly_papers[row['year']] = row['count']

        logger.info(f"连接 temporal_stats.db，年度数据: {len(self.yearly_papers)} 年")

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def _get_object_data(self, obj: str) -> Optional[Dict[int, int]]:
        """获取单个 object 的年度数据"""
        # 检查缓存
        if obj in self.cache:
            return self.cache[obj]

        # 查询数据库
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT year, paper_count
            FROM object_yearly
            WHERE object_lemma = ?
        """, (obj,))

        rows = cursor.fetchall()
        if not rows:
            return None

        data = {row['year']: row['paper_count'] for row in rows}

        # 添加到缓存
        self._add_to_cache(obj, data)

        return data

    def _add_to_cache(self, obj: str, data: Dict[int, int]):
        """添加到 LRU 缓存"""
        if len(self.cache) >= self.cache_size:
            # 移除最旧的
            oldest = self.cache_order.pop(0)
            del self.cache[oldest]

        self.cache[obj] = data
        self.cache_order.append(obj)

    def get_stats(self, obj: str, pub_year: int, max_year: int = 2025) -> Tuple[int, int, int]:
        """
        获取 object 的统计数据

        Returns:
            (prior_papers, post_papers, active_years)
        """
        data = self._get_object_data(obj)
        if data is None:
            return 0, 0, 0

        prior = 0
        post = 0
        active = 0

        for year, count in data.items():
            if year < pub_year:
                prior += count
            elif year > pub_year:
                post += count
                if count > 0:
                    active += 1

        return prior, post, active

    def batch_get_stats(self, objects: List[str], pub_year: int, max_year: int = 2025) -> Dict[str, Tuple[int, int, int]]:
        """
        批量获取多个 objects 的统计数据（减少数据库往返）
        """
        results = {}
        uncached = []

        # 先检查缓存
        for obj in objects:
            if obj in self.cache:
                data = self.cache[obj]
                prior = sum(c for y, c in data.items() if y < pub_year)
                post = sum(c for y, c in data.items() if y > pub_year)
                active = sum(1 for y, c in data.items() if y > pub_year and c > 0)
                results[obj] = (prior, post, active)
            else:
                uncached.append(obj)

        if not uncached:
            return results

        # 批量查询未缓存的
        placeholders = ','.join('?' * len(uncached))
        cursor = self.conn.cursor()
        cursor.execute(f"""
            SELECT object_lemma, year, paper_count
            FROM object_yearly
            WHERE object_lemma IN ({placeholders})
        """, uncached)

        # 组织数据
        obj_data = defaultdict(dict)
        for row in cursor.fetchall():
            obj_data[row['object_lemma']][row['year']] = row['paper_count']

        # 计算统计并缓存
        for obj in uncached:
            data = obj_data.get(obj, {})
            if data:
                self._add_to_cache(obj, data)
                prior = sum(c for y, c in data.items() if y < pub_year)
                post = sum(c for y, c in data.items() if y > pub_year)
                active = sum(1 for y, c in data.items() if y > pub_year and c > 0)
                results[obj] = (prior, post, active)
            else:
                results[obj] = (0, 0, 0)

        return results


class ImpactCalculatorLowMem:
    """低内存版 Impact 计算器"""

    def __init__(self, config: dict):
        self.config = config
        self.rpu_db_path = config['rpu_db_path']
        self.temporal_db_path = config['temporal_db_path']
        self.output_dir = Path(config['output_dir'])
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.checkpoint_path = self.output_dir / 'checkpoint_lowmem.json'
        self.checkpoint = self._load_checkpoint()

        self.temporal_stats = None

    def _load_checkpoint(self) -> dict:
        if self.checkpoint_path.exists():
            with open(self.checkpoint_path, 'r') as f:
                return json.load(f)
        return {'pass': 0, 'year': None, 'status': 'init'}

    def _save_checkpoint(self):
        self.checkpoint['timestamp'] = datetime.now().isoformat()
        with open(self.checkpoint_path, 'w') as f:
            json.dump(self.checkpoint, f, indent=2)

    def run(self):
        """运行完整计算流程"""
        logger.info("=" * 60)
        logger.info("Impact V5.0 计算 - 低内存版")
        logger.info(f"配置: Top-{self.config['top_k']}, 阈值={self.config['persistence_threshold']}")
        logger.info("=" * 60)

        # 检查 temporal_stats.db 是否存在
        if not os.path.exists(self.temporal_db_path):
            logger.error(f"temporal_stats.db 不存在: {self.temporal_db_path}")
            logger.error("请先运行 calculate_impact_v2_optimized.py 完成 Pass 0-1")
            return

        # 连接时序统计数据库
        self.temporal_stats = TemporalStatsDB(
            self.temporal_db_path,
            cache_size=int(self.config.get('temporal_cache_size', 200000))
        )
        self.temporal_stats.connect()

        try:
            # Pass 2: 计算 Diffusion + Persistence
            self.run_pass2()

            # Pass 3: 归一化
            self.run_pass3()

        finally:
            self.temporal_stats.close()

        logger.info("=" * 60)
        logger.info("Impact V5.0 计算完成！")
        logger.info("=" * 60)

    def run_pass2(self):
        """Pass 2: 计算 Diffusion + Persistence"""
        logger.info("=" * 60)
        logger.info("Pass 2: Diffusion + Persistence 计算 (低内存版)")
        logger.info("=" * 60)

        # 连接 RPU 数据库
        rpu_conn = sqlite3.connect(self.rpu_db_path)
        rpu_conn.row_factory = sqlite3.Row

        for year in self.config['years']:
            # 检查断点
            if self.checkpoint.get('pass2_year', 0) > year:
                logger.info(f"  {year}: 已完成，跳过")
                continue

            output_path = self.output_dir / f'impact_signals_{year}.jsonl'
            self._process_year(rpu_conn, year, output_path)

            self.checkpoint['pass2_year'] = year
            self._save_checkpoint()

        rpu_conn.close()

        self.checkpoint['pass2_complete'] = True
        self._save_checkpoint()
        logger.info("Pass 2 完成")

    def _process_year(self, rpu_conn: sqlite3.Connection, year: int, output_path: Path):
        """处理单年数据"""
        start_time = datetime.now()

        # 获取该年所有论文（从 papers 表）
        cursor = rpu_conn.cursor()
        cursor.execute("""
            SELECT paper_id
            FROM papers
            WHERE pub_year = ?
            ORDER BY paper_id
        """, (year,))

        paper_ids = [row['paper_id'] for row in cursor.fetchall()]
        total_papers = len(paper_ids)

        logger.info(f"  {year}: {total_papers:,} 篇论文")

        # 批量处理
        batch_size = self.config['batch_size']
        processed = 0

        with open(output_path, 'w', encoding='utf-8') as f:
            for i in range(0, total_papers, batch_size):
                batch_ids = paper_ids[i:i+batch_size]
                results = self._process_batch(rpu_conn, batch_ids, year)

                for result in results:
                    f.write(json.dumps(result, ensure_ascii=False) + '\n')

                processed += len(batch_ids)
                if processed % 100000 == 0:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    speed = processed / elapsed if elapsed > 0 else 0
                    logger.info(f"    {year}: {processed:,}/{total_papers:,} ({100*processed/total_papers:.1f}%) - {speed:.0f} 篇/秒")

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"    {year} 完成，耗时 {elapsed/60:.1f} 分钟")

    def _process_batch(self, rpu_conn: sqlite3.Connection, paper_ids: List[str], year: int) -> List[dict]:
        """处理一批论文"""
        results = []

        # 获取这批论文的所有 RPU
        placeholders = ','.join('?' * len(paper_ids))
        cursor = rpu_conn.cursor()
        cursor.execute(f"""
            SELECT paper_id, object_lemma, task_lemma
            FROM rpu
            WHERE paper_id IN ({placeholders})
            AND object_lemma IS NOT NULL
        """, paper_ids)

        # 按论文分组
        paper_rpus = defaultdict(list)
        all_objects = set()

        for row in cursor.fetchall():
            paper_rpus[row['paper_id']].append({
                'object': row['object_lemma'],
                'task': row['task_lemma']
            })
            all_objects.add(row['object_lemma'])

        # 批量查询所有涉及的 objects 的统计数据
        if all_objects:
            obj_stats = self.temporal_stats.batch_get_stats(
                list(all_objects), year, self.config['current_year']
            )
        else:
            obj_stats = {}

        # 计算每篇论文的分数
        observable_years = self.config['current_year'] - year

        for paper_id in paper_ids:
            rpus = paper_rpus.get(paper_id, [])

            if not rpus or observable_years <= 0:
                results.append({
                    'paper_id': paper_id,
                    'pub_year': year,
                    'diffusion_raw': 0,
                    'persistence_raw': 0,
                    'avg_survival': 0,
                    'object_count': 0
                })
                continue

            # 按 object 分组，计算贡献
            object_contribs = {}

            for rpu in rpus:
                obj = rpu['object']
                task_w = get_task_weight(rpu['task'])

                prior, post, active = obj_stats.get(obj, (0, 0, 0))
                scarcity_w = 1.0 / (prior + 1)

                # Diffusion 贡献
                diff_contrib = task_w * scarcity_w * post

                # Persistence 贡献
                survival = active / observable_years if observable_years > 0 else 0
                pers_contrib = task_w * scarcity_w * survival

                # 同一 object 取最大贡献
                if obj not in object_contribs:
                    object_contribs[obj] = (diff_contrib, pers_contrib, task_w * scarcity_w)
                else:
                    old = object_contribs[obj]
                    if diff_contrib > old[0]:
                        object_contribs[obj] = (diff_contrib, pers_contrib, task_w * scarcity_w)

            # Top-K 聚合
            top_k = self.config['top_k']
            sorted_contribs = sorted(object_contribs.values(), key=lambda x: x[0], reverse=True)[:top_k]

            diffusion_raw = sum(c[0] for c in sorted_contribs)
            persistence_raw = sum(c[1] for c in sorted_contribs)
            weight_sum = sum(c[2] for c in sorted_contribs)

            avg_survival = persistence_raw / weight_sum if weight_sum > 0 else 0

            results.append({
                'paper_id': paper_id,
                'pub_year': year,
                'diffusion_raw': diffusion_raw,
                'persistence_raw': persistence_raw,
                'avg_survival': avg_survival,
                'object_count': len(object_contribs)
            })

        return results

    def run_pass3(self):
        """Pass 3: 归一化 + 输出"""
        logger.info("=" * 60)
        logger.info("Pass 3: 归一化")
        logger.info("=" * 60)

        for year in self.config['years']:
            input_path = self.output_dir / f'impact_signals_{year}.jsonl'
            output_path = self.output_dir / f'impact_final_{year}.jsonl'

            if not input_path.exists():
                logger.warning(f"  {year}: 信号文件不存在，跳过")
                continue

            self._normalize_year(input_path, output_path, year)

        self.checkpoint['pass3_complete'] = True
        self._save_checkpoint()
        logger.info("Pass 3 完成")

    def _normalize_year(self, input_path: Path, output_path: Path, year: int):
        """归一化单年数据"""
        import math

        # 第一遍：收集分数
        diffusion_scores = []

        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                data = json.loads(line)
                d_raw = data.get('diffusion_raw', 0)
                if d_raw > 0:
                    diffusion_scores.append(math.log(d_raw + 1))

        if not diffusion_scores:
            logger.warning(f"  {year}: 无有效分数")
            return

        # 排序用于百分位计算
        diffusion_scores.sort()
        n = len(diffusion_scores)

        def get_percentile(value: float, sorted_scores: list) -> float:
            if not sorted_scores:
                return 0
            # 二分查找
            left, right = 0, len(sorted_scores)
            while left < right:
                mid = (left + right) // 2
                if sorted_scores[mid] < value:
                    left = mid + 1
                else:
                    right = mid
            return 100.0 * left / len(sorted_scores)

        # 第二遍：计算归一化分数
        threshold = self.config['persistence_threshold']

        with open(input_path, 'r', encoding='utf-8') as fin, \
             open(output_path, 'w', encoding='utf-8') as fout:

            for line in fin:
                data = json.loads(line)

                d_raw = data.get('diffusion_raw', 0)
                avg_survival = data.get('avg_survival', 0)

                # Diffusion 归一化
                if d_raw > 0:
                    d_log = math.log(d_raw + 1)
                    d_norm = get_percentile(d_log, diffusion_scores)
                else:
                    d_norm = 0

                # Persistence 门控
                p_gate = min(avg_survival / threshold, 1.0)

                # Impact 分数
                impact_score = d_norm * p_gate

                result = {
                    'paper_id': data['paper_id'],
                    'pub_year': year,
                    'diffusion_raw': d_raw,
                    'diffusion_norm': round(d_norm, 2),
                    'avg_survival': round(avg_survival, 4),
                    'persistence_gate': round(p_gate, 4),
                    'impact_score': round(impact_score, 2),
                    'object_count': data.get('object_count', 0)
                }

                fout.write(json.dumps(result, ensure_ascii=False) + '\n')

        logger.info(f"  {year}: 归一化完成")


def main():
    parser = argparse.ArgumentParser(description='Impact V5.0 计算 - 低内存版')
    parser.add_argument('--year', type=int, help='只处理指定年份')
    parser.add_argument('--cache-size', type=int, default=200000, help='LRU 缓存大小')
    parser.add_argument('--config', type=str, default=None, help='配置文件路径（JSON）')
    args = parser.parse_args()

    config = build_runtime_config(args.config)
    config['temporal_cache_size'] = int(args.cache_size)

    if args.year:
        config['years'] = [args.year]

    calculator = ImpactCalculatorLowMem(config)
    calculator.run()


if __name__ == '__main__':
    main()
