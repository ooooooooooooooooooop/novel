# -*- coding: utf-8 -*-
"""
Script: check_extraction_quality.py (V3.0 Final)
功能：全维度抗腐蚀抽取质量门禁系统 (Semantic QA Gate)
版本：V3.0 (Adaptive Thresholds, Drift Detection, Strict Decision)

核心能力：
1. 基础健康度：Schema 完整性、字段非空率。
2. 语义抗腐蚀：
   - Global Collapse: 全局 Unique Token Ratio
   - Local Collapse: 单篇论文内部复读机检测 (P10 < 0.2)
   - Top-N Coverage: 领域停用词剔除后的内容多样性
3. 历史基线对比：检测长期语义漂移 (Drift Detection)。
4. 强决策输出：
   - Exit Code 0 (PASS), 1 (WARN), 2 (BLOCK)
   - JSON 结构化报告

使用方法：
    python check_extraction_quality.py
    echo $?  # 查看退出码

"""

import os
import sys
import sqlite3
import json
import logging
import statistics
import time
import collections
import argparse
from typing import Dict, List, Tuple, Set, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import load_project_config, get_paths

# ============================================================
# 配置
# ============================================================
CONFIG = {
    "db_path": "",
    "history_path": "",
    
    # 领域停用词表 (Domain Stoplist)
    "domain_stoplist": {
        "method", "system", "approach", "algorithm", "model", "data", "dataset",
        "based", "using", "proposed", "paper", "framework", "technique", 
        "analysis", "application", "study", "performance", "result", "problem",
        # Common Verbs (often extracted as tasks erroneously)
        "used", "showed", "found", "investigated", "observed", "increased", "decreased",
        "demonstrated", "suggested", "presented", "given", "shown", "compared", "analyzed",
        "described", "proposed", "reported", "obtained", "performed", "measured", "calculated",
        "estimated", "identified", "discussed", "examined", "developed", "applied",
        # Prepositions/Conjunctions (often extracted as tasks erroneously)
        "between", "among", "during", "within", "without", "against", "versus", "via",
        # Symbols
        "<", ">", "=", "+", "-", "~",
        # Standard Stopwords
        "the", "a", "an", "of", "and", "or", "but", "in", "on", "at", "to", "for", "with", "by", 
        "from", "up", "down", "over", "under", "again", "further", "then", "once", "here", "there", 
        "when", "where", "why", "how", "all", "any", "both", "each", "few", "more", "most", "other", 
        "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very", 
        "s", "t", "can", "will", "just", "don", "should", "now", "d", "ll", "m", "o", "re", "ve", "y",
        "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did",
        "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your", "yours", "yourself",
        "yourselves", "he", "him", "his", "himself", "she", "her", "hers", "herself", "it", "its", "itself",
        "they", "them", "their", "theirs", "themselves", "what", "which", "who", "whom", "this", "that", 
        "these", "those", "am", "is", "are", "was", "were", "be", "been", "being",
        ".", ",", ";", ":", "(", ")", "[", "]", "{", "}", "-", "/", "\\", "'", "\"", "`",
        "1", "2", "3", "4", "5", "6", "7", "8", "9", "0"
    },
    
    # 阈值配置
    "thresholds": {
        "min_rpu_per_paper": 0.5,       # 平均每篇论文最少 RPU 数
        "max_rpu_per_paper": 50.0,      # 平均每篇论文最多 RPU 数 (防幻觉)
        "min_global_unique_ratio": 0.01,# 全局词汇丰富度下限
        "max_top10_coverage": 0.40,     # Top-10 实词覆盖率上限 (防语义塌缩)
        "min_local_unique_p10": 0.20,   # P10 论文内部 Unique Ratio 下限 (防复读机)
        "max_overlap_concentration": 0.5, # 单一重合模式在单篇论文中的最大占比
        "max_garbage_ratio": 0.05,        # 垃圾词（纯通用动词/符号）作为 Task/Object 的最大比例
        
        "drift_tolerance": 0.20,        # 历史基线允许偏离度 (20%)
    },
    
    # 垃圾词黑名单 (用于检测提取质量是否崩坏)
    "garbage_blacklist": {
        "used", "showed", "found", "investigated", "observed", "increased", "decreased",
        "demonstrated", "suggested", "presented", "given", "shown", "compared", "analyzed",
        "described", "proposed", "reported", "obtained", "performed", "measured",
        "between", "among", "during", "within", "<", ">", "=",
        "c", "p", "n", "b" # Single letters often noise
    },
    
    # 采样配置
    "sample_size": 20000,               # 统计分析采样数 (None 为全量，建议 20k-50k)
    "min_tokens_for_local_check": 50,   # 论文总 token 数少于此值不进行局部塌缩检查
}

def apply_config(config_path: str = None):
    cfg = load_project_config(config_path)
    paths = get_paths(cfg)
    CONFIG["db_path"] = paths["rpu_db_path"]
    CONFIG["history_path"] = str((PROJECT_ROOT / "extraction_quality_history.json").resolve())


apply_config(None)

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# ============================================================
# 数据结构
# ============================================================
@dataclass
class QualityMetrics:
    timestamp: str
    total_rpus: int
    total_papers: int
    mean_rpu_per_paper: float
    
    # 分布指标
    mean_task_len: float
    mean_obj_len: float
    
    # 多样性指标
    global_unique_ratio: float
    top10_coverage: float       # 剔除停用词后
    local_unique_p10: float     # 局部塌缩指标
    
    # 异常指标
    empty_rate: float
    overlap_ratio: float        # Task/Object 高度重合比例
    garbage_ratio: float        # 垃圾词比例

class QualityGate:
    def __init__(self):
        self.metrics: Optional[QualityMetrics] = None
        self.history: List[Dict] = []
        self.blockers: List[str] = []
        self.warnings: List[str] = []
        self.conn = None
        
    def run(self):
        logger.info("="*60)
        logger.info("🚀 STARTING SEMANTIC QA GATE (V3.0)")
        logger.info("="*60)
        
        try:
            self._connect_db()
            self._calculate_metrics()
            self._check_thresholds()
            self._check_drift()
            self._analyze_overlap_concentration()
            self._save_history()
            self._print_report()
            
        except Exception as e:
            logger.error(f"❌ QA 过程发生严重错误: {e}")
            sys.exit(2) # BLOCK
        finally:
            if self.conn:
                self.conn.close()
                
        # 最终决策
        self._final_decision()

    def _connect_db(self):
        if not os.path.exists(CONFIG["db_path"]):
            raise FileNotFoundError(f"Database not found: {CONFIG['db_path']}")
        self.conn = sqlite3.connect(CONFIG["db_path"])

    def _calculate_metrics(self):
        logger.info("正在计算统计指标...")
        cursor = self.conn.cursor()
        
        # 1. 基础计数
        cursor.execute("SELECT COUNT(*) FROM rpu")
        total_rpus = cursor.fetchone()[0]
        if total_rpus == 0:
            self.blockers.append("EMPTY_DATABASE")
            return

        cursor.execute("SELECT COUNT(DISTINCT paper_id) FROM rpu")
        total_papers = cursor.fetchone()[0]
        
        # 2. 流式采样分析
        logger.info(f"正在采样分析 (Sample Size: {CONFIG['sample_size'] or 'ALL'})...")
        
        if CONFIG["sample_size"]:
            # 优化采样：避免 ORDER BY RANDOM() 全表扫描
            try:
                # 1. 获取最大 ID
                cursor.execute("SELECT MAX(id) FROM rpu")
                max_id = cursor.fetchone()[0]
                
                if max_id:
                    import random
                    # 2. 生成随机 ID 列表
                    # 注意：如果 ID 不连续（有删除），可能取不到部分数据，但在大量数据下可接受
                    target_ids = random.sample(range(1, max_id + 1), min(CONFIG["sample_size"], max_id))
                    id_str = ",".join(map(str, target_ids))
                    query = f"SELECT paper_id, task, object FROM rpu WHERE id IN ({id_str})"
                else:
                    # 表是空的
                    query = "SELECT paper_id, task, object FROM rpu"
            except Exception as e:
                logger.warning(f"优化采样失败，回退到普通查询: {e}")
                query = f"SELECT paper_id, task, object FROM rpu LIMIT {CONFIG['sample_size']}"
        else:
            query = "SELECT paper_id, task, object FROM rpu"
            
        cursor.execute(query)
        
        # 统计容器
        task_lens = []
        obj_lens = []
        all_tokens = [] # Global
        paper_tokens = collections.defaultdict(list) # Local
        empty_count = 0
        overlap_count = 0
        garbage_count = 0
        
        # 重合模式统计 (Pattern -> {count, paper_counts})
        self.overlap_patterns = collections.defaultdict(lambda: {"total": 0, "papers": collections.Counter()})
        
        for pid, task, obj in cursor:
            if not task or not obj:
                empty_count += 1
                continue
                
            t_tokens = task.lower().split()
            o_tokens = obj.lower().split()
            
            task_lens.append(len(task))
            obj_lens.append(len(obj))
            
            # Global Tokens (只统计实词)
            all_tokens.extend([t for t in t_tokens if t not in CONFIG["domain_stoplist"]])
            all_tokens.extend([o for o in o_tokens if o not in CONFIG["domain_stoplist"]])
            
            # Local Tokens (全量，含停用词，因为复读机通常包含停用词)
            paper_tokens[pid].extend(t_tokens + o_tokens)
            
            # Overlap Check (简单 Jaccard 或 字符串包含)
            # 这里用归一化字符串比较
            t_norm = " ".join(sorted(t_tokens))
            o_norm = " ".join(sorted(o_tokens))
            if t_norm == o_norm or task in obj or obj in task:
                overlap_count += 1
                pattern = f"{task} | {obj}"
                self.overlap_patterns[pattern]["total"] += 1
                self.overlap_patterns[pattern]["papers"][pid] += 1

            # Garbage Check
            if task.lower() in CONFIG["garbage_blacklist"] or obj.lower() in CONFIG["garbage_blacklist"]:
                garbage_count += 1
        
        # 3. 计算衍生指标
        # Global Diversity
        token_counts = collections.Counter(all_tokens)
        total_valid_tokens = sum(token_counts.values())
        unique_tokens = len(token_counts)
        
        global_unique_ratio = unique_tokens / total_valid_tokens if total_valid_tokens > 0 else 0
        
        top10_count = sum(count for word, count in token_counts.most_common(10))
        top10_coverage = top10_count / total_valid_tokens if total_valid_tokens > 0 else 0
        
        # Local Diversity (P10)
        local_ratios = []
        for pid, tokens in paper_tokens.items():
            if len(tokens) >= CONFIG["min_tokens_for_local_check"]:
                ratio = len(set(tokens)) / len(tokens)
                local_ratios.append(ratio)
        
        local_unique_p10 = 1.0
        if local_ratios:
            local_ratios.sort()
            p10_idx = int(len(local_ratios) * 0.1)
            local_unique_p10 = local_ratios[p10_idx]
            
        self.metrics = QualityMetrics(
            timestamp=datetime.now().isoformat(),
            total_rpus=total_rpus,
            total_papers=total_papers,
            mean_rpu_per_paper=total_rpus / max(1, total_papers),
            mean_task_len=statistics.mean(task_lens) if task_lens else 0,
            mean_obj_len=statistics.mean(obj_lens) if obj_lens else 0,
            global_unique_ratio=global_unique_ratio,
            top10_coverage=top10_coverage,
            local_unique_p10=local_unique_p10,
            empty_rate=empty_count / CONFIG["sample_size"] if CONFIG["sample_size"] else 0,
            overlap_ratio=overlap_count / len(task_lens) if task_lens else 0,
            garbage_ratio=garbage_count / len(task_lens) if task_lens else 0
        )
        
        # 保存 Top Tokens 供展示
        self.top_tokens = token_counts.most_common(20)

    def _check_thresholds(self):
        logger.info("执行阈值检查...")
        m = self.metrics
        t = CONFIG["thresholds"]
        
        # 1. 基础覆盖率
        if m.mean_rpu_per_paper < t["min_rpu_per_paper"]:
            self.blockers.append(f"LOW_COVERAGE: {m.mean_rpu_per_paper:.2f} RPU/paper < {t['min_rpu_per_paper']}")
        if m.mean_rpu_per_paper > t["max_rpu_per_paper"]:
            self.warnings.append(f"HIGH_COVERAGE: {m.mean_rpu_per_paper:.2f} RPU/paper > {t['max_rpu_per_paper']}")
            
        # 2. 全局语义塌缩
        if m.global_unique_ratio < t["min_global_unique_ratio"]:
            self.blockers.append(f"GLOBAL_COLLAPSE: Unique Ratio {m.global_unique_ratio:.3f} < {t['min_global_unique_ratio']}")
        
        if m.top10_coverage > t["max_top10_coverage"]:
            self.blockers.append(f"SEMANTIC_POVERTY: Top-10 Coverage {m.top10_coverage:.2%} > {t['max_top10_coverage']:.2%}")
            
        # 3. 局部复读机
        if m.local_unique_p10 < t["min_local_unique_p10"]:
            self.warnings.append(f"LOCAL_COLLAPSE: P10 Unique Ratio {m.local_unique_p10:.2f} < {t['min_local_unique_p10']}")

        # 4. 垃圾词污染 (改为 WARN，因为下游会进行精细化清洗)
        if m.garbage_ratio > t["max_garbage_ratio"]:
            self.warnings.append(f"GARBAGE_CONTAMINATION: {m.garbage_ratio:.2%} > {t['max_garbage_ratio']:.2%} (Generic verbs detected, will be handled in Phase 2)")

    def _check_drift(self):
        if not os.path.exists(CONFIG["history_path"]):
            logger.info("ℹ️ 无历史基线，本次运行将作为基线。")
            return
            
        try:
            with open(CONFIG["history_path"], 'r') as f:
                history = json.load(f)
                if not history: return
                baseline = history[-1] # 取最近一次
                
            # 简单 Diff
            # 1. 长度漂移
            len_change = abs(self.metrics.mean_task_len - baseline["mean_task_len"]) / baseline["mean_task_len"]
            if len_change > CONFIG["thresholds"]["drift_tolerance"]:
                self.warnings.append(f"DRIFT_LENGTH: Task Length changed by {len_change:.1%}")
                
            # 2. 多样性漂移
            div_change = (baseline["global_unique_ratio"] - self.metrics.global_unique_ratio) / baseline["global_unique_ratio"]
            if div_change > CONFIG["thresholds"]["drift_tolerance"]:
                self.warnings.append(f"DRIFT_DIVERSITY: Unique Ratio dropped by {div_change:.1%}")
                
        except Exception as e:
            logger.warning(f"历史基线读取失败: {e}")

    def _analyze_overlap_concentration(self):
        logger.info("分析重合模式集中度...")
        
        # 获取 Top-5 重合模式
        sorted_patterns = sorted(self.overlap_patterns.items(), key=lambda x: x[1]["total"], reverse=True)[:5]
        
        for pattern, stats in sorted_patterns:
            total = stats["total"]
            papers = stats["papers"]
            max_per_paper = papers.most_common(1)[0][1]
            paper_count = len(papers)
            
            # 判定集中度
            # 估算该论文的总 RPU 数（这里用采样数据估算，可能有误差，但足以发现极端异常）
            # 严格来说应该查库，这里为了性能用 max_per_paper / total_rpu_of_that_paper
            # 简化规则：如果 max_per_paper 很大 (>10) 且占该模式总数的比例很大 (>50%) -> 单篇异常
            # 或者：如果 max_per_paper 非常大 (>50) -> 单篇异常
            
            concentration = max_per_paper / total if total > 0 else 0
            
            if max_per_paper > 50 and concentration > 0.5:
                self.warnings.append(f"OVERLAP_CONCENTRATION: Pattern '{pattern}' dominated by single paper ({max_per_paper} times)")

    def _save_history(self):
        # 读取旧历史
        history = []
        if os.path.exists(CONFIG["history_path"]):
            try:
                with open(CONFIG["history_path"], 'r') as f:
                    history = json.load(f)
            except: pass
            
        # 添加新记录
        record = asdict(self.metrics)
        history.append(record)
        
        # 保留最近 50 条
        history = history[-50:]
        
        # 原子写入
        temp_path = CONFIG["history_path"] + ".tmp"
        with open(temp_path, 'w') as f:
            json.dump(history, f, indent=2)
        os.replace(temp_path, CONFIG["history_path"])
        logger.info("历史基线已更新。")

    def _print_report(self):
        m = self.metrics
        
        print("\n" + "="*60)
        print("📊 QUALITY REPORT")
        print("="*60)
        print(f"Total RPUs:       {m.total_rpus:,}")
        print(f"Coverage:         {m.mean_rpu_per_paper:.2f} RPU/paper")
        print(f"Task Length:      {m.mean_task_len:.1f} chars")
        print(f"Global Unique:    {m.global_unique_ratio:.4f}")
        print(f"Top-10 Cov:       {m.top10_coverage:.1%} (stoplist filtered)")
        print(f"Local P10 Unique: {m.local_unique_p10:.2f}")
        print(f"Garbage Ratio:    {m.garbage_ratio:.2%} (generic verbs/symbols)")
        print("-" * 60)
        
        print("\n🔍 Top-20 Tokens (Candidate for Stoplist):")
        for word, count in self.top_tokens:
            ratio = count / (m.total_rpus * 2) # 估算
            marker = " [HIGH]" if ratio > 0.05 else ""
            print(f"  - {word:<15} : {count:<6} ({ratio:.1%}){marker}")
            
        print("-" * 60)

    def _final_decision(self):
        print("\n" + "="*60)
        print("🚦 FINAL DECISION")
        print("="*60)
        
        decision = "PASS"
        exit_code = 0
        
        if self.blockers:
            decision = "BLOCK"
            exit_code = 2
        elif self.warnings:
            decision = "WARN"
            exit_code = 1
            
        result_json = {
            "final_decision": decision,
            "qa_level": "CONSISTENCY_ONLY",
            "blockers": self.blockers,
            "warnings": self.warnings
        }
        
        print(json.dumps(result_json, indent=2))
        
        print("-" * 60)
        print("NOTICE: This QA gate verifies Internal Consistency & Stability.")
        print("It DOES NOT verify Ground Truth Alignment.")
        print("-" * 60)
        
        sys.exit(exit_code)

def main():
    parser = argparse.ArgumentParser(description="semantic extraction quality gate")
    parser.add_argument("--config", type=str, default=None, help="JSON config override path")
    args = parser.parse_args()
    apply_config(args.config)

    gate = QualityGate()
    gate.run()


if __name__ == "__main__":
    main()
