# -*- coding: utf-8 -*-
"""
Script 2: apply_abstract_layer.py
功能：基于挖掘的高质量短语表，对 RPU 数据库进行双轨制（Core + Modifier）抽象层映射
版本：V4 (Dual-Track Abstract Mapping)

流程：
1. 加载 phrase_table.json
2. 构建 Aho-Corasick 自动机 (AC 自动机) 实现高效多模式匹配
3. 给数据库添加新字段 (task_core, task_modifier, etc.)
4. 流式批量更新数据库

注意：
- 严格控制 SQLite 事务，避免 4000w 行更新卡死
- 禁用 Auto Checkpoint，手动 Commit
"""

import os
import sqlite3
import json
import logging
import time
import sys
from typing import List, Dict, Tuple, Set
from pathlib import Path
from tqdm import tqdm

import ahocorasick

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import load_project_config, get_paths

_cfg = load_project_config()
_paths = get_paths(_cfg)


def _require_path(key: str) -> str:
    value = _paths.get(key)
    if value:
        return value
    raise KeyError(f"Missing required path key in project config: paths.{key}")

# ============================================================
# 配置
# ============================================================
CONFIG = {
    "db_path": _require_path("rpu_db_path"),
    "phrase_table_path": _require_path("phrase_table_path"),
    # 可选: Core Mapping (同义词表)
    "core_mapping_path": _require_path("core_mapping_path"),
    
    "batch_size": 10000,
    "log_interval": 10,
    
    # Top-K 选择阈值
    "iou_threshold_max": 0.8, # 超过此重合度则丢弃 (认为是子集或高度冗余)
    "iou_threshold_min": 0.1, # 低于此重合度则保留 (认为是正交)
}

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class AbstractMapper:
    def __init__(self):
        self.automaton = ahocorasick.Automaton()
        self.phrase_dict = {} # phrase -> status
        self.core_mapping = {} # original -> canonical

    def load_phrases(self):
        # 1. 加载 Core Mapping (如果存在)
        if os.path.exists(CONFIG.get("core_mapping_path", "")):
            logger.info(f"加载 Core Mapping: {CONFIG['core_mapping_path']}")
            with open(CONFIG["core_mapping_path"], 'r', encoding='utf-8') as f:
                self.core_mapping = json.load(f)
        
        # 2. 加载 Phrase Table
        logger.info(f"加载短语表: {CONFIG['phrase_table_path']}")
        with open(CONFIG['phrase_table_path'], 'r', encoding='utf-8') as f:
            phrases = json.load(f)
            
        # 计算 Specificity Threshold
        scores = []
        for p in phrases:
            freq = p.get('frequency', 0)
            task_cnt = p.get('task_count', 1)
            score = freq / (task_cnt + 1)
            p['specificity_score'] = score
            scores.append(score)
            
        import numpy as np
        stable_threshold = np.percentile(scores, 80) if scores else 0
        logger.info(f"Stable Specificity Threshold (P80): {stable_threshold:.4f}")
            
        count = 0
        for item in phrases:
            p = item['phrase']
            score = item['specificity_score']
            status = "stable" if score >= stable_threshold else "emerging"
            
            self.automaton.add_word(p, (p, status))
            self.phrase_dict[p] = status
            count += 1
            
        # 3. 将 Core Mapping 中的 source (变体/缩写) 也加入 AC 自动机
        # 这样即使 phrase_table 里没有 "ConvNet"，只要 mapping 里有 "ConvNet" -> "CNN"，也能匹配到
        # 状态继承自 canonical form (如果 canonical 也没有，则默认为 stable)
        mapping_count = 0
        for src, canonical in self.core_mapping.items():
            if src not in self.phrase_dict:
                # 尝试获取 canonical 的状态
                status = self.phrase_dict.get(canonical, "stable") # 默认 stable，因为能进 mapping 通常是高频词
                self.automaton.add_word(src, (src, status))
                self.phrase_dict[src] = status
                mapping_count += 1
                
        logger.info(f"构建 AC 自动机... ({count} phrases + {mapping_count} from mapping)")
        self.automaton.make_automaton()

    def _calculate_iou(self, range1: Tuple[int, int], range2: Tuple[int, int]) -> float:
        """计算两个区间的 IoU (Intersection over Union)"""
        start1, end1 = range1
        start2, end2 = range2
        
        # 计算交集
        inter_start = max(start1, start2)
        inter_end = min(end1, end2)
        inter_len = max(0, inter_end - inter_start)
        
        # 计算并集
        len1 = end1 - start1
        len2 = end2 - start2
        union_len = len1 + len2 - inter_len
        
        if union_len == 0: return 0.0
        return inter_len / union_len

    def match_cores_topk(self, text: str) -> Dict:
        """
        执行 Top-K Core 匹配 (Interval Selection)
        返回: {
            "cores": [List of canonical cores],
            "modifiers": str (residual text),
            "coverage": float,
            "density": float,
            "status": str (summary status)
        }
        """
        if not text:
            return {"cores": [], "modifiers": "", "coverage": 0.0, "density": 0.0, "status": "rare"}
            
        # 1. 找出所有匹配项
        # 转换为小写进行匹配 (Case-insensitive matching)
        text_lower = text.lower()
        
        # iter 返回 (end_index, (phrase, status))
        # 转换为 (start, end, phrase, status)
        all_matches = []
        for end_idx, (phrase, status) in self.automaton.iter(text_lower):
            start_idx = end_idx - len(phrase) + 1
            # end_idx 是包含的，为了切片方便，我们用 start:end (exclusive)
            all_matches.append((start_idx, end_idx + 1, phrase, status))
            
        if not all_matches:
            return {
                "cores": [f"RAW:{text}"], 
                "modifiers": "", 
                "coverage": 0.0, 
                "density": 0.0, 
                "status": "rare"
            }
            
        # 2. 贪婪选择 Top-K
        # 策略：优先选最长的 -> 其次选不重叠的
        # 排序：长度降序 -> 位置升序
        all_matches.sort(key=lambda x: (-(x[1]-x[0]), x[0]))
        
        selected_matches = []
        
        # 选 Primary Core (最长)
        primary = all_matches[0]
        selected_matches.append(primary)
        
        # 选 Secondary Cores
        for match in all_matches[1:]:
            is_valid = True
            for selected in selected_matches:
                iou = self._calculate_iou((match[0], match[1]), (selected[0], selected[1]))
                # 如果重叠度太高，认为是冗余（父集/子集），丢弃
                if iou > CONFIG["iou_threshold_max"]:
                    is_valid = False
                    break
                # 如果有一定重叠但不大 (0.1 < IoU < 0.8)，或者是完全分离 (<0.1)，都保留
                
            if is_valid:
                selected_matches.append(match)
                if len(selected_matches) >= 3: # 最多保留 3 个 Core
                    break
                    
        # 3. 构建结果
        # 将 phrase 转换为 canonical form (归一化)
        final_cores = []
        final_statuses = []
        covered_mask = [False] * len(text)
        
        for start, end, phrase, status in selected_matches:
            # 归一化
            canonical = self.core_mapping.get(phrase, phrase)
            final_cores.append(canonical)
            final_statuses.append(status)
            
            # 标记覆盖区域
            for i in range(start, end):
                if i < len(text): covered_mask[i] = True
                
        # 4. 提取 Modifier (未覆盖的文本)
        modifier_chars = []
        for i, char in enumerate(text):
            if not covered_mask[i]:
                modifier_chars.append(char)
            else:
                modifier_chars.append(" ") # 用空格替换 Core
        
        modifier = "".join(modifier_chars)
        modifier = " ".join(modifier.split()) # 清洗空格
        
        # 5. 计算 Coverage & Density
        covered_len = sum(1 for x in covered_mask if x)
        coverage = covered_len / len(text) if len(text) > 0 else 0
        
        tokens = text.split()
        # 简单估算 Token Density: 覆盖字符数 / 总Token数 (只是一个近似指标)
        # 或者：Covered Tokens / Total Tokens
        # 这里用更精确的 Token Coverage
        # 但为了性能，暂用字符级 Coverage，足以区分
        density = coverage # 暂时简化，后续可优化为 Token 级
        
        # 6. 综合 Status
        # 如果有任意 Stable，则整体 Stable
        summary_status = "emerging"
        if "stable" in final_statuses:
            summary_status = "stable"
        elif not final_statuses:
            summary_status = "rare"
            
        return {
            "cores": final_cores, # JSON List
            "modifiers": modifier,
            "coverage": round(coverage, 3),
            "density": round(density, 3),
            "status": summary_status
        }

    def update_database(self):
        logger.info(f"连接数据库: {CONFIG['db_path']}")
        conn = sqlite3.connect(CONFIG['db_path'])
        
        # 1. 添加新列 (支持 JSON 和 Float)
        cursor = conn.cursor()
        existing_cols = [row[1] for row in cursor.execute("PRAGMA table_info(rpu)")]
        
        new_cols = [
            ("task_cores", "TEXT"), # JSON List
            ("task_modifier", "TEXT"),
            ("task_coverage", "REAL"),
            ("object_cores", "TEXT"), # JSON List
            ("object_modifier", "TEXT"),
            ("object_coverage", "REAL"),
            ("abstraction_status", "TEXT")
        ]
        
        for col_name, col_type in new_cols:
            if col_name not in existing_cols:
                try:
                    cursor.execute(f"ALTER TABLE rpu ADD COLUMN {col_name} {col_type}")
                except Exception as e: pass
        conn.commit()
        
        # 2. 批量处理
        logger.info("开始批量更新 (Top-K Core Mode)...")
        read_cursor = conn.cursor()
        read_cursor.execute("SELECT id, task, object FROM rpu")
        
        batch_data = []
        pbar = tqdm(desc="Updating RPU")
        
        while True:
            rows = read_cursor.fetchmany(CONFIG['batch_size'])
            if not rows: break
                
            for rpu_id, task, obj in rows:
                t_res = self.match_cores_topk(task)
                o_res = self.match_cores_topk(obj)
                
                # 综合状态
                final_status = "rare"
                if t_res['status'] == "stable" and o_res['status'] == "stable":
                    final_status = "stable"
                elif t_res['status'] == "stable" or o_res['status'] == "stable":
                    final_status = "emerging"
                
                batch_data.append((
                    json.dumps(t_res['cores'], ensure_ascii=False), 
                    t_res['modifiers'],
                    t_res['coverage'],
                    json.dumps(o_res['cores'], ensure_ascii=False),
                    o_res['modifiers'],
                    o_res['coverage'],
                    final_status,
                    rpu_id
                ))
            
            conn.executemany("""
                UPDATE rpu 
                SET task_cores=?, task_modifier=?, task_coverage=?,
                    object_cores=?, object_modifier=?, object_coverage=?,
                    abstraction_status=?
                WHERE id=?
            """, batch_data)
            conn.commit()
            
            pbar.update(len(rows))
            batch_data = []
            
        pbar.close()
        conn.close()
        logger.info("更新完成！")

def main():
    if not os.path.exists(CONFIG['phrase_table_path']):
        logger.error(f"找不到短语表: {CONFIG['phrase_table_path']}")
        return

    mapper = AbstractMapper()
    mapper.load_phrases()
    mapper.update_database()

if __name__ == "__main__":
    main()
