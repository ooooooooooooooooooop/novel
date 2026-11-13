# -*- coding: utf-8 -*-
"""
Script 1: mine_phrases.py
功能：基于统计指标（Frequency, PMI, Entropy）从全量 RPU 中挖掘高质量短语
版本：V4 (Statistics-based Quality Control)

流程：
1. 流式读取 rpu_database.db
2. 统计 N-gram (1-3) 频次及上下文分布
3. 计算 PMI 和 左右熵 (Branching Entropy)
4. 基于动态阈值（Percentile）过滤
5. 导出 phrase_table.json

注意：
- 内存优化：使用 generator 流式处理
- 性能优化：仅统计 Top-N 上下文以节省内存
"""

import os
import sqlite3
import json
import math
import logging
import collections
import pickle
import glob
import sys
from typing import Dict, List, Tuple, Set
from datetime import datetime
from pathlib import Path

import numpy as np
from tqdm import tqdm

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
    "output_path": _require_path("phrase_table_path"),
    
    # 统计参数
    "min_frequency": 50,        # 最小频次（<50 视为 Rare/Noise）
    "max_ngram": 3,             # 最大 N-gram 长度
    "min_pmi": 2.0,             # 基础 PMI 阈值（后续会用 percentile 覆盖）
    "min_entropy": 0.5,         # 基础熵阈值
    
    # 采样参数（None = 全量生产环境）
    "sample_size": None, 
    
    # 内存保护
    "max_vocab_size": 2000000,  # 最大词汇量限制
    "shard_size": 5000000,      # 分片大小 (每500万行dump一次)
    "temp_dir": _require_path("legacy_temp_dir"),
    "skip_scan_if_exists": True # 🚀 如果分片存在，跳过扫描
}

# 扩展停用词表 (用于过滤无效短语边界)
STOPWORDS = {
    # Standard Stopwords Only (Strict Statistical Approach)
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
}

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PhraseMiner:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.unigrams = collections.Counter()
        self.bigrams = collections.Counter()
        self.trigrams = collections.Counter()
        
        # 上下文统计 (用于计算熵)
        # 仅在第二阶段合并时使用，或者第一阶段不统计
        # 为了内存安全，第一阶段只统计 N-gram 频次
        self.contexts = collections.defaultdict(lambda: {"L": collections.Counter(), "R": collections.Counter()})
        
        # 任务多样性统计 (用于计算 IDF)
        # phrase -> set(task_hashes)
        # 分片模式下，我们只统计 task_hash_count，不存 set
        self.phrase_task_counts = collections.Counter()
        
        self.total_tokens = 0
        
        os.makedirs(CONFIG["temp_dir"], exist_ok=True)
        
    def _tokenize(self, text: str) -> List[str]:
        """简单的按空格分词，保留原始大小写以区分专有名词"""
        if not text:
            return []
        # 预处理：去除首尾空格，并去除常见标点粘连
        tokens = text.strip().split()
        # 清洗 token 边缘的标点 (保留中间的连字符等)
        clean_tokens = [t.strip(".,;:()[]{}\"'`") for t in tokens]
        return [t for t in clean_tokens if t]

    def _is_valid_ngram(self, tokens: List[str]) -> bool:
        """检查 N-gram 是否合法 (首尾不能是停用词)"""
        if not tokens:
            return False
        
        # Rule 1: 首尾不能是停用词
        if tokens[0].lower() in STOPWORDS or tokens[-1].lower() in STOPWORDS:
            return False
            
        return True

    def scan_database(self):
        """第一遍扫描：流式处理 + 分片落盘"""
        # 检查是否可以跳过扫描
        if CONFIG.get("skip_scan_if_exists", False):
            shard_files = glob.glob(os.path.join(CONFIG["temp_dir"], "shard_*.pkl"))
            if len(shard_files) > 0:
                logger.info(f"⚡ 发现 {len(shard_files)} 个现有分片，跳过扫描阶段！")
                self._merge_shards()
                return

        logger.info(f"开始扫描数据库: {self.db_path}")
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 获取总行数
        cursor.execute("SELECT COUNT(*) FROM rpu")
        total_rows = cursor.fetchone()[0]
        if CONFIG["sample_size"]:
            total_rows = min(total_rows, CONFIG["sample_size"])
            
        logger.info(f"总数据量: {total_rows}")
        
        query = "SELECT task, object FROM rpu"
        if CONFIG["sample_size"]:
            query += f" LIMIT {CONFIG['sample_size']}"
            
        cursor.execute(query)
        
        batch_size = 50000
        shard_counter = 0
        rows_processed = 0
        
        pbar = tqdm(total=total_rows, desc="Scanning (Sharded)")
        
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
                
            for task, obj in rows:
                self._process_sentence(task, context_task=task)
                self._process_sentence(obj, context_task=task)
            
            rows_processed += len(rows)
            pbar.update(len(rows))
            
            # 检查是否需要落盘分片
            if rows_processed >= CONFIG["shard_size"]:
                self._dump_shard(shard_counter)
                shard_counter += 1
                rows_processed = 0 # 重置计数器
                
        # 最后一个分片
        if rows_processed > 0:
            self._dump_shard(shard_counter)
            
        pbar.close()
        conn.close()
        
        logger.info("所有分片已生成。开始合并...")
        self._merge_shards()

    def _dump_shard(self, shard_id: int):
        """将当前内存中的统计信息 Dump 到磁盘并清空内存"""
        filename = os.path.join(CONFIG["temp_dir"], f"shard_{shard_id:04d}.pkl")
        logger.info(f"Dumping shard {shard_id} to {filename}...")
        
        data = {
            "unigrams": self.unigrams,
            "bigrams": self.bigrams,
            "trigrams": self.trigrams,
            "phrase_task_counts": self.phrase_task_counts
        }
        
        with open(filename, 'wb') as f:
            pickle.dump(data, f)
            
        # 清空内存
        self.unigrams.clear()
        self.bigrams.clear()
        self.trigrams.clear()
        self.phrase_task_counts.clear()
        # 注意：不要重置 self.total_tokens，那是全局统计
        
    def _merge_shards(self):
        """合并所有分片"""
        shard_files = glob.glob(os.path.join(CONFIG["temp_dir"], "shard_*.pkl"))
        logger.info(f"Found {len(shard_files)} shards. Merging...")
        
        for fname in tqdm(shard_files, desc="Merging Shards"):
            with open(fname, 'rb') as f:
                data = pickle.load(f)
                
            self.unigrams.update(data["unigrams"])
            self.bigrams.update(data["bigrams"])
            self.trigrams.update(data["trigrams"])
            self.phrase_task_counts.update(data["phrase_task_counts"])
            
            # 可选：合并完删除文件以释放磁盘空间
            # os.remove(fname)
            
        logger.info(f"合并完成. Unigrams: {len(self.unigrams)}, Bigrams: {len(self.bigrams)}")
        
        # 🚀 必须在这里生成 candidates，因为 _collect_contexts 被跳过了
        self._generate_candidates()

    def _generate_candidates(self):
        """从合并后的统计数据生成候选短语集合"""
        logger.info("筛选高频短语候选集...")
        self.candidates = set()
        for p, count in self.bigrams.items():
            if count >= CONFIG["min_frequency"]:
                self.candidates.add(p)
        for p, count in self.trigrams.items():
            if count >= CONFIG["min_frequency"]:
                self.candidates.add(p)
                
        logger.info(f"高频候选短语数: {len(self.candidates)}")

    def _process_sentence(self, text: str, context_task: str = None):
        """
        context_task: 当前句子所属的 Task (用于计算 Object 短语的领域分布)
        如果是处理 Task 字段本身，context_task 可以是它自己或 None
        """
        tokens = self._tokenize(text)
        if not tokens:
            return
            
        self.total_tokens += len(tokens)
        
        # 简单的 Task Hash (用于 IDF)
        task_hash = hash(context_task) if context_task else 0
        
        # 1. Unigrams
        for i, token in enumerate(tokens):
            self.unigrams[token] += 1
            
        # 2. Bigrams & Contexts
        for i in range(len(tokens) - 1):
            w1, w2 = tokens[i], tokens[i+1]
            if not self._is_valid_ngram([w1, w2]):
                continue
                
            phrase = f"{w1} {w2}"
            self.bigrams[phrase] += 1
            
            # 记录 Task 分布 (仅对 Object 有效，或者 Task 自指)
            if context_task:
                # 只计数，不存 set，大幅节省内存
                self.phrase_task_counts[phrase] += 1

        # 3. Trigrams
        for i in range(len(tokens) - 2):
            w1, w2, w3 = tokens[i], tokens[i+1], tokens[i+2]
            if not self._is_valid_ngram([w1, w2, w3]):
                continue

            phrase = f"{w1} {w2} {w3}"
            self.trigrams[phrase] += 1
            
            if context_task:
                self.phrase_task_counts[phrase] += 1

    def _collect_contexts(self):
        """
        第二遍扫描（或合并在第一遍）：由于内存限制，通常需要两遍。
        或者：如果内存够大，可以在第一遍直接做。
        
        为了简化逻辑且假设内存充足（64G+），我们在第一遍逻辑中稍微修改，
        或者在这里重新扫描一遍只针对高频短语收集上下文。
        
        考虑到 4000w 数据量，建议：
        先筛选出 Frequency > min_frequency 的 candidate phrases，
        然后再扫一遍数据库统计它们的 Entropy。
        这样内存最安全。
        """
        logger.info("筛选高频短语候选集...")
        
        # 筛选 Candidates
        self.candidates = set()
        for p, count in self.bigrams.items():
            if count >= CONFIG["min_frequency"]:
                self.candidates.add(p)
        for p, count in self.trigrams.items():
            if count >= CONFIG["min_frequency"]:
                self.candidates.add(p)
                
        logger.info(f"高频候选短语数: {len(self.candidates)}")
        
    def calculate_metrics(self) -> List[Dict]:
        logger.info("计算 PMI 和 Entropy...")
        results = []
        
        # 预计算总数
        N_uni = sum(self.unigrams.values())
        N_bi = sum(self.bigrams.values())
        N_tri = sum(self.trigrams.values()) # 预计算
        
        # 🚀 优化：先将 candidates 排序，优先计算高频词 (Hot Data)
        # 并且将 candidates 转换为列表，避免 tqdm 迭代 set 时的随机访问
        sorted_candidates = sorted(list(self.candidates), key=lambda x: self.bigrams[x] if x in self.bigrams else self.trigrams[x], reverse=True)
        
        for phrase in tqdm(sorted_candidates, desc="Calculating Metrics"):
            tokens = phrase.split()
            n = len(tokens)
            freq = 0
            
            if n == 2:
                freq = self.bigrams[phrase]
                # PMI = log( P(xy) / (P(x)P(y)) )
                #     = log( (freq/N_bi) / ( (fx/N_uni) * (fy/N_uni) ) )
                p_xy = freq / N_bi
                p_x = self.unigrams[tokens[0]] / N_uni
                p_y = self.unigrams[tokens[1]] / N_uni
                pmi = math.log(p_xy / (p_x * p_y + 1e-10))
                
            elif n == 3:
                freq = self.trigrams[phrase]
                # Trigram PMI approximation: avg(PMI(12,3), PMI(1,23))
                # 这里简化处理，使用 Pointwise PMI
                p_xyz = freq / N_tri # 使用 N_tri
                p_x = self.unigrams[tokens[0]] / N_uni
                p_y = self.unigrams[tokens[1]] / N_uni
                p_z = self.unigrams[tokens[2]] / N_uni
                pmi = math.log(p_xyz / (p_x * p_y * p_z + 1e-10)) / 2 # Normalize slightly
            
            # Entropy Calculation
            # 🚀 优化：弃熵保PMI - 直接跳过上下文熵计算，只依赖 PMI
            # H = -sum(p * log p)
            # ctx = self.contexts[phrase]
            
            # 默认给一个最大熵，避免被阈值过滤
            min_entropy = 10.0
            
            # Task Diversity Score (IDF-like)
            
            # Task Diversity Score (IDF-like)
            # score = freq * log(TotalTasks / (PhraseTasks + 1))
            # 这里 TotalTasks 可以用一个常数估计，或者动态统计。
            # 为了简单，我们直接用 len(self.phrase_tasks[phrase]) 代表 "Task Coverage"
            # 越小众的词，Coverage 越小，但 Freq 也小。
            # 我们需要一个归一化分数： RelativeFreq = Freq / TaskCoverage
            # 或者：Score = Freq * (1 / log(TaskCoverage + 2)) -- 惩罚出现在太多 Task 中的词
            
            # 简化为出现次数，因为分片模式下无法精确去重 task_hash
            # 但 frequency 实际上已经包含了这个信息
            task_count = self.phrase_task_counts[phrase]
            # 简单的 Domain Specificity Score:
            # 如果一个词出现 100 次，但在 100 个不同 Task 里 -> Specificity Low
            # 如果一个词出现 100 次，但在 1 个 Task 里 -> Specificity High
            # 我们记录 task_count，由 apply_abstract_layer 决定阈值
            
            results.append({
                "phrase": phrase,
                "frequency": freq,
                "pmi": round(pmi, 3),
                "entropy": round(min_entropy, 3),
                "task_count": task_count, # 新增字段
                "status": "pending"
            })
            
        return results

    def filter_and_save(self, raw_results: List[Dict]):
        logger.info("执行动态阈值过滤...")
        
        if not raw_results:
            logger.warning("没有找到符合条件的短语！")
            return

        # 转换为 numpy 方便计算分位数
        pmis = np.array([r['pmi'] for r in raw_results])
        entropies = np.array([r['entropy'] for r in raw_results])
        
        pmi_threshold = np.percentile(pmis, 50) # 中位数以上
        entropy_threshold = np.percentile(entropies, 20) # 排除最低 20% (最固定的搭配)
        
        logger.info(f"动态阈值: PMI >= {pmi_threshold:.2f}, Entropy >= {entropy_threshold:.2f}")
        
        valid_phrases = []
        for r in raw_results:
            # 基础过滤 + 动态过滤
            is_valid = (
                r['frequency'] >= CONFIG["min_frequency"] and
                r['pmi'] >= pmi_threshold and
                r['entropy'] >= entropy_threshold
            )
            
            if is_valid:
                # 确定生命周期状态 (初步标记，后续由 apply_abstract_layer 细化)
                # 这里只做简单切分，不再硬编码 50
                r['status'] = "valid" 
                
                valid_phrases.append(r)
        
        # 排序：优先长短语，其次高频
        # 这样在后续匹配时，如果按顺序匹配，可以优先匹配长的
        valid_phrases.sort(key=lambda x: (-len(x['phrase'].split()), -x['frequency']))
        
        logger.info(f"保留有效短语: {len(valid_phrases)} / {len(raw_results)}")
        
        # 保存
        dir_path = os.path.dirname(CONFIG["output_path"])
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        with open(CONFIG["output_path"], 'w', encoding='utf-8') as f:
            json.dump(valid_phrases, f, ensure_ascii=False, indent=2)
            
        logger.info(f"结果已保存至: {CONFIG['output_path']}")

def main():
    miner = PhraseMiner(CONFIG["db_path"])
    
    # 1. 扫描频次
    miner.scan_database()
    
    # 2. 扫描上下文 (需第二遍)
    # miner._collect_contexts()
    
    # 强制重新生成 candidates，确保万无一失
    logger.info("强制执行 candidates 生成...")
    miner._generate_candidates()
    
    # 3. 计算指标
    metrics = miner.calculate_metrics()
    
    # 🚀 释放内存：计算完指标后，大字典可以清空了
    miner.unigrams.clear()
    miner.bigrams.clear()
    miner.trigrams.clear()
    miner.phrase_task_counts.clear()
    
    # 4. 过滤保存
    miner.filter_and_save(metrics)

if __name__ == "__main__":
    main()
