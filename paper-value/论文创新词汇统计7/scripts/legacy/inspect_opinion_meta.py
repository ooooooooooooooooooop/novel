# -*- coding: utf-8 -*-
"""
Script: inspect_opinion_meta.py
功能：抽样检查 opinion_meta.lmdb 的数据质量，评估其用于 RPU 标准化的可行性
"""

import os
import json
import lmdb
import logging
import sys
from pathlib import Path
from collections import Counter, defaultdict
from tabulate import tabulate

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from project_config import load_project_config, get_paths

# ============================================================
# 配置（以项目根为基准）
# ============================================================
_cfg = load_project_config()
_paths = get_paths(_cfg)


def _require_path(key: str) -> str:
    value = _paths.get(key)
    if value:
        return value
    raise KeyError(f"Missing required path key in project config: paths.{key}")


def _resolve_lmdb_path() -> str:
    primary = _require_path("legacy_opinion_meta_lmdb_path")
    fallback = _require_path("legacy_opinion_meta_lmdb_fallback_path")
    if os.path.exists(primary):
        return primary
    if os.path.exists(fallback):
        return fallback
    return primary


CONFIG = {
    "lmdb_path": _resolve_lmdb_path(),
    "sample_size": 100, # 随机抽样检查的数量
    "top_k_aliases": 20, # 检查别名最多的 Top K 实体
}

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def inspect_lmdb():
    if not os.path.exists(CONFIG["lmdb_path"]):
        logger.error(f"LMDB not found: {CONFIG['lmdb_path']}")
        return

    logger.info(f"Opening LMDB: {CONFIG['lmdb_path']}")
    env = lmdb.open(CONFIG["lmdb_path"], readonly=True, lock=False)
    
    stats = {
        "total_entries": 0,
        "entries_with_aliases": 0,
        "total_aliases": 0,
        "max_aliases": 0,
        "alias_counts": []
    }
    
    alias_distribution = Counter()
    top_alias_entities = []
    
    # 随机抽样缓存
    samples = []
    
    with env.begin() as txn:
        cursor = txn.cursor()
        stats["total_entries"] = txn.stat()['entries']
        
        logger.info(f"Total entries in DB: {stats['total_entries']:,}")

        if stats["total_entries"] == 0:
            logger.warning("DB is empty! Please check if the source file is correct.")
            return

        count = 0
        for key, value in cursor:
            try:
                # 尝试解码（原代码可能用 json 或 msgpack）
                try:
                    meta = json.loads(value.decode())
                except:
                    # 简单尝试 msgpack 如果 json 失败 (这里为了简化依赖暂只尝试 json，通常是 json)
                    continue
                    
                cid = int(key.decode())
                canonical = meta.get('canonical_label', 'N/A')
                aliases = meta.get('aliases', [])
                year = meta.get('first_seen_year', 'N/A')
                
                num_aliases = len(aliases)
                stats["alias_counts"].append(num_aliases)
                stats["total_aliases"] += num_aliases
                
                if num_aliases > 0:
                    stats["entries_with_aliases"] += 1
                    stats["max_aliases"] = max(stats["max_aliases"], num_aliases)
                
                # 记录 Top Alias 实体
                if num_aliases > 1: # 只关注有多个别名的
                    top_alias_entities.append({
                        "id": cid,
                        "canonical": canonical,
                        "aliases": aliases,
                        "count": num_aliases,
                        "year": year
                    })
                
                # 抽样（前 20 个）
                if count < 20:
                    samples.append({
                        "id": cid,
                        "canonical": canonical,
                        "aliases": aliases,
                        "year": year
                    })
                
                count += 1
                
                # 快速扫描前 50000 个即可得出大致分布，不用全扫
                if count >= 50000:
                    break
                    
            except Exception as e:
                continue

    # 分析结果
    top_alias_entities.sort(key=lambda x: x["count"], reverse=True)
    
    print("\n" + "="*60)
    print("DATA QUALITY REPORT")
    print("="*60)
    
    print(f"\n[1] Overall Statistics (Sampled first {count:,} entries)")
    print(f"- Total scanned: {count:,}")
    print(f"- Entries with aliases: {stats['entries_with_aliases']:,} ({stats['entries_with_aliases']/count*100:.1f}%)")
    print(f"- Avg aliases per entry: {stats['total_aliases']/count:.2f}")
    print(f"- Max aliases found: {stats['max_aliases']}")
    
    print("\n[2] Top Entities with Most Aliases (Potential Over-Merging?)")
    headers = ["ID", "Canonical Label", "Alias Count", "Sample Aliases (Top 3)"]
    table_data = []
    for item in top_alias_entities[:10]:
        aliases_preview = ", ".join(item["aliases"][:3])
        if len(item["aliases"]) > 3: aliases_preview += "..."
        table_data.append([item["id"], item["canonical"], item["count"], aliases_preview])
    print(tabulate(table_data, headers=headers, tablefmt="grid"))
    
    print("\n[3] Random Samples (Check Normalization Quality)")
    headers = ["ID", "Canonical Label", "Year", "Aliases"]
    table_data = []
    for item in samples:
        aliases_str = ", ".join(item["aliases"]) if item["aliases"] else "-"
        # 截断过长字符串
        if len(aliases_str) > 50: aliases_str = aliases_str[:47] + "..."
        if len(item["canonical"]) > 40: item["canonical"] = item["canonical"][:37] + "..."
        table_data.append([item["id"], item["canonical"], item["year"], aliases_str])
    print(tabulate(table_data, headers=headers, tablefmt="simple"))

    print("\n[4] Reliability Assessment")
    print("- High Quality Signs: Aliases represent true synonyms (e.g., 'CNN', 'ConvNet').")
    print("- Low Quality Signs: Generic words merged into specific terms; mixed concepts.")
    
if __name__ == "__main__":
    inspect_lmdb()
