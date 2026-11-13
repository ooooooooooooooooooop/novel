import os
import json
import pickle
from pathlib import Path
from collections import defaultdict, Counter
from itertools import combinations
import math
import multiprocessing as mp
from functools import partial
import sqlite3
import tempfile

import numpy as np
try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False
import pandas as pd
import networkx as nx
from tqdm import tqdm
from scipy.stats import chi2_contingency
import matplotlib.pyplot as plt
import seaborn as sns

try:
    import lmdb
    HAS_LMDB = True
except ImportError:
    HAS_LMDB = False

# =========================
# 配置区
# =========================
OUTPUT_BASE_DIR = Path("output_5_concept_cooccurrence")
STAGE1_DIR = OUTPUT_BASE_DIR / "stage1_concept_extraction"
MENTIONS_DIR = STAGE1_DIR / "mentions_by_year"
CONCEPTS_FILE = str(STAGE1_DIR / "concepts_catalog_streaming.parquet")

COOCCURRENCE_DIR = OUTPUT_BASE_DIR / "stage2_cooccurrence_networks"
COOCCURRENCE_DIR.mkdir(exist_ok=True)

# 已处理论文ID记录文件
PROCESSED_PAPERS_FILE = COOCCURRENCE_DIR / "processed_papers.parquet"

# 共现网络参数
MIN_CONCEPT_FREQ = 5        # 概念最小出现频次
MIN_COOCCUR_FREQ = 3        # 共现最小频次
NPMI_THRESHOLD = 0.2        # NPMI阈值（范围[-1,1]，0.2表示中等强度关联）
MAX_CONCEPTS_PER_PAPER = 50 # 单篇论文最大概念数（防爆炸）

# 社区检测参数
COMMUNITY_MIN_SIZE = 3      # 社区最小规模
COMMUNITY_RESOLUTION = 1.0  # 社区检测分辨率

# 网络分析参数
TOP_N_EDGES = 10000        # 保留的最强边数
CENTRALITY_TOP_N = 100     # 中心性分析的top概念数

# 可视化参数
VIS_MAX_NODES = 500        # 可视化最大节点数
VIS_MIN_EDGE_WEIGHT = 0.1  # 可视化最小边权重

# 流式处理参数
CHUNK_SIZE = 50000         # 每次处理的提及记录数
NUM_WORKERS = min(8, mp.cpu_count())  # 并行进程数
USE_DISK_STORAGE = True   # 使用磁盘存储共现对（避免内存溢出）
TEMP_DIR = COOCCURRENCE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

# =========================
# 数据加载与预处理（流式版本）
# =========================
def load_concept_info():
    """加载概念目录数据（仅元数据，不加载提及数据）"""
    print("📂 加载概念目录...")
    concepts_df = pd.read_parquet(CONCEPTS_FILE)
    print(f"已加载 {len(concepts_df)} 个唯一概念")
    
    concept_info = {}
    for _, row in concepts_df.iterrows():
        concept_info[row['concept_id']] = {
            'text': row['concept_text'],
            'canonical': row['canonical_label'],
            'first_year': row['first_seen_year'],
            'aliases': row['aliases'].split('; ') if pd.notna(row['aliases']) else []
        }
    
    return concept_info

def stream_mentions_chunks(chunk_size=CHUNK_SIZE, valid_concepts=None, years=None):
    """流式加载概念提及数据（分块）"""
    mentions_files = list(MENTIONS_DIR.glob("*_mentions.parquet"))
    if not mentions_files:
        raise FileNotFoundError(f"未找到概念提及文件，请检查路径: {MENTIONS_DIR}")
    
    def sort_key(f):
        name = f.stem.replace("_mentions", "")
        if name == "unknown":
            return (1, 0)
        try:
            year = int(name)
            return (0, year)
        except ValueError:
            return (1, 0)
    
    mentions_files = sorted(mentions_files, key=sort_key)
    
    if years is not None:
        year_set = set(int(y) for y in years)
        filtered_files = []
        for f in mentions_files:
            name = f.stem.replace("_mentions", "")
            try:
                file_year = int(name)
            except ValueError:
                continue
            if file_year in year_set:
                filtered_files.append(f)
        mentions_files = filtered_files
    
    print(f"找到 {len(mentions_files)} 个年度提及文件，将分块流式处理")
    
    for f in mentions_files:
        df = pd.read_parquet(f)
        if valid_concepts is not None:
            df = df[df['concept_id'].isin(valid_concepts)]
        
        for i in range(0, len(df), chunk_size):
            chunk = df.iloc[i:i+chunk_size].copy()
            yield chunk

def get_total_mentions_count(years=None):
    """获取总提及记录数（用于进度条）"""
    mentions_files = list(MENTIONS_DIR.glob("*_mentions.parquet"))
    
    if years is not None:
        year_set = set(int(y) for y in years)
        filtered_files = []
        for f in mentions_files:
            name = f.stem.replace("_mentions", "")
            try:
                file_year = int(name)
            except ValueError:
                continue
            if file_year in year_set:
                filtered_files.append(f)
        mentions_files = filtered_files
    
    total = 0
    for f in mentions_files:
        df = pd.read_parquet(f)
        total += len(df)
    return total

def get_all_years():
    """根据文件名获取所有年份列表"""
    mentions_files = list(MENTIONS_DIR.glob("*_mentions.parquet"))
    years = set()
    for f in mentions_files:
        name = f.stem.replace("_mentions", "")
        try:
            year = int(name)
        except ValueError:
            continue
        years.add(year)
    return sorted(years)

def build_current_yearly_paper_ids_streaming(valid_concepts=None, processed_papers=None):
    """在流式模式下构建年度-论文ID映射（仅用于增量更新检测）
    
    参数:
        valid_concepts: 有效概念集合，只统计包含这些概念的论文
        processed_papers: 已处理论文集合，排除这些论文
    """
    mentions_files = list(MENTIONS_DIR.glob("*_mentions.parquet"))
    current_yearly_papers = {}
    processed_set = set(processed_papers) if processed_papers else set()
    
    for f in mentions_files:
        name = f.stem.replace("_mentions", "")
        try:
            year = int(name)
        except ValueError:
            continue
        
        df = pd.read_parquet(f, columns=['paper_id', 'concept_id'])
        if 'paper_id' not in df.columns:
            continue
        
        df = df[df['paper_id'].notna()]
        
        if valid_concepts is not None:
            valid_set = set(valid_concepts) if isinstance(valid_concepts, (set, list)) else valid_concepts
            df = df[df['concept_id'].isin(valid_set)]
        
        if processed_set:
            df = df[~df['paper_id'].isin(processed_set)]
        
        paper_ids = set(df['paper_id'].astype(str).unique())
        if paper_ids:
            current_yearly_papers[year] = dict.fromkeys(paper_ids, None)
    
    return current_yearly_papers

def load_concept_data():
    """加载概念提及和目录数据（非流式版本，保留用于兼容）"""
    print("📂 加载概念数据...")
    
    mentions_files = list(MENTIONS_DIR.glob("*_mentions.parquet"))
    if not mentions_files:
        raise FileNotFoundError(f"未找到概念提及文件，请检查路径: {MENTIONS_DIR}")
    
    def sort_key(f):
        name = f.stem.replace("_mentions", "")
        if name == "unknown":
            return (1, 0)
        try:
            year = int(name)
            return (0, year)
        except ValueError:
            return (1, 0)
    
    mentions_files = sorted(mentions_files, key=sort_key)
    print(f"找到 {len(mentions_files)} 个年度提及文件")
    mentions_dfs = []
    for f in tqdm(mentions_files, desc="加载年度提及文件"):
        df = pd.read_parquet(f)
        mentions_dfs.append(df)
    
    mentions_df = pd.concat(mentions_dfs, ignore_index=True)
    print(f"已加载 {len(mentions_df)} 条概念提及记录")
    
    concepts_df = pd.read_parquet(CONCEPTS_FILE)
    print(f"已加载 {len(concepts_df)} 个唯一概念")
    
    concept_info = {}
    for _, row in concepts_df.iterrows():
        concept_info[row['concept_id']] = {
            'text': row['concept_text'],
            'canonical': row['canonical_label'],
            'first_year': row['first_seen_year'],
            'aliases': row['aliases'].split('; ') if pd.notna(row['aliases']) else []
        }
    
    return mentions_df, concept_info

def filter_concepts_by_frequency(mentions_df, min_freq=MIN_CONCEPT_FREQ):
    """过滤低频概念（非流式版本，保留用于兼容）"""
    concept_counts = mentions_df['concept_id'].value_counts()
    valid_concepts = concept_counts[concept_counts >= min_freq].index
    
    filtered_df = mentions_df[mentions_df['concept_id'].isin(valid_concepts)].copy()
    print(f"概念过滤: {len(concept_counts)} -> {len(valid_concepts)} (最小频次={min_freq})")
    
    return filtered_df, valid_concepts

def filter_concepts_by_frequency_streaming(min_freq=MIN_CONCEPT_FREQ):
    """流式过滤低频概念（分块统计）"""
    print("📊 统计概念频次（流式处理）...")
    concept_counts = Counter()
    total_mentions = 0
    
    for chunk in tqdm(stream_mentions_chunks(), desc="统计概念频次"):
        concept_counts.update(chunk['concept_id'].tolist())
        total_mentions += len(chunk)
    
    valid_concepts = set(c for c, count in concept_counts.items() if count >= min_freq)
    print(f"概念过滤: {len(concept_counts)} -> {len(valid_concepts)} (最小频次={min_freq})")
    print(f"总提及记录: {total_mentions:,}")
    
    return valid_concepts

# =========================
# 磁盘存储共现对计数器（避免内存溢出）
# =========================
class DiskCooccurrenceCounter:
    """使用DuckDB存储共现对计数器，避免内存溢出（优化：批量聚合写入）"""
    def __init__(self, db_path, use_duckdb=None):
        self.db_path = db_path
        if use_duckdb is None:
            use_duckdb = HAS_DUCKDB
        self.use_duckdb = use_duckdb
        
        if self.use_duckdb:
            self.conn = duckdb.connect(db_path)
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS cooccurrence (
                    concept1 INTEGER,
                    concept2 INTEGER,
                    frequency INTEGER,
                    PRIMARY KEY (concept1, concept2)
                )
            ''')
        else:
            self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
            self.conn.execute('PRAGMA journal_mode=WAL')
            self.conn.execute('PRAGMA synchronous=NORMAL')
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS cooccurrence (
                    concept1 INTEGER,
                    concept2 INTEGER,
                    frequency INTEGER,
                    PRIMARY KEY (concept1, concept2)
                )
            ''')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_pair ON cooccurrence(concept1, concept2)')
            self.conn.commit()
        
        self.buffer = {}
        self.buffer_size = 100000
    
    def add_batch(self, cooccur_pairs):
        """批量添加共现对（优化：直接批量处理）"""
        for (c1, c2), freq in cooccur_pairs.items():
            pair = tuple(sorted([int(c1), int(c2)]))
            self.buffer[pair] = self.buffer.get(pair, 0) + int(freq)
        
        if len(self.buffer) >= self.buffer_size:
            self.flush()
    
    def increment(self, c1, c2):
        """增加共现对计数（保留兼容性）"""
        pair = tuple(sorted([c1, c2]))
        self.buffer[pair] = self.buffer.get(pair, 0) + 1
        
        if len(self.buffer) >= self.buffer_size:
            self.flush()
    
    def flush(self):
        """将缓冲区批量写入数据库（优化：使用批量INSERT SELECT）"""
        if not self.buffer:
            return
        
        if self.use_duckdb:
            pairs_data = [(c1, c2, int(freq)) for (c1, c2), freq in self.buffer.items()]
            if pairs_data:
                df = pd.DataFrame(pairs_data, columns=['concept1', 'concept2', 'frequency'])
                df_agg = df.groupby(['concept1', 'concept2'])['frequency'].sum().reset_index()
                self.conn.register('temp_pairs', df_agg)
                self.conn.execute('''
                    MERGE INTO cooccurrence AS target
                    USING temp_pairs AS source
                    ON target.concept1 = source.concept1 AND target.concept2 = source.concept2
                    WHEN MATCHED THEN
                        UPDATE SET frequency = target.frequency + source.frequency
                    WHEN NOT MATCHED THEN
                        INSERT (concept1, concept2, frequency)
                        VALUES (source.concept1, source.concept2, source.frequency)
                ''')
                self.conn.unregister('temp_pairs')
        else:
            self.conn.executemany('''
                INSERT INTO cooccurrence (concept1, concept2, frequency)
                VALUES (?, ?, ?)
                ON CONFLICT(concept1, concept2) DO UPDATE SET
                    frequency = frequency + excluded.frequency
            ''', [(c1, c2, int(freq)) for (c1, c2), freq in self.buffer.items()])
            self.conn.commit()
        
        self.buffer.clear()
    
    def get_all(self):
        """获取所有共现对"""
        self.flush()
        if self.use_duckdb:
            result = self.conn.execute('SELECT concept1, concept2, frequency FROM cooccurrence').fetchall()
        else:
            cursor = self.conn.execute('SELECT concept1, concept2, frequency FROM cooccurrence')
            result = cursor.fetchall()
        return {(row[0], row[1]): row[2] for row in result}
    
    def clear(self):
        """清空计数器"""
        if self.use_duckdb:
            self.conn.execute('DELETE FROM cooccurrence')
        else:
            self.conn.execute('DELETE FROM cooccurrence')
            self.conn.commit()
        self.buffer.clear()
    
    def close(self):
        """关闭连接"""
        self.flush()
        if self.use_duckdb:
            self.conn.close()
        else:
            self.conn.close()

def vectorized_combinations(concepts):
    """使用NumPy向量化生成概念对组合（优化：提升10-50倍速度）"""
    concepts = np.array(concepts, dtype=np.int64)
    n = len(concepts)
    if n < 2:
        return []
    
    i, j = np.triu_indices(n, k=1)
    pairs = np.column_stack([concepts[i], concepts[j]])
    pairs = np.sort(pairs, axis=1)
    return [tuple(pair) for pair in pairs]

def compute_chunk_cooccurrence(chunk_data, valid_concepts, processed_papers, max_concepts_per_paper):
    """处理一个数据块的共现对（用于并行处理，优化：NumPy向量化组合生成）"""
    concept_freq = Counter()
    cooccur_freq = Counter()
    yearly_papers = defaultdict(lambda: defaultdict(list))
    
    if valid_concepts is None:
        valid_concepts = set()
    elif not isinstance(valid_concepts, set):
        valid_concepts = set(valid_concepts)
    
    if processed_papers is None:
        processed_papers = set()
    elif not isinstance(processed_papers, set):
        processed_papers = set(processed_papers)
    
    for _, row in chunk_data.iterrows():
        if row['concept_id'] not in valid_concepts:
            continue
        
        year = row['year']
        paper_id = row['paper_id']
        concept_id = row['concept_id']
        
        if pd.notna(year) and pd.notna(paper_id) and paper_id not in processed_papers:
            year_int = int(year)
            yearly_papers[year_int][paper_id].append(concept_id)
    
    for year in yearly_papers:
        for paper_id, concepts in yearly_papers[year].items():
            concepts = list(set(concepts))
            if len(concepts) > max_concepts_per_paper:
                concept_counts = Counter(concepts)
                concepts = [c for c, _ in concept_counts.most_common(max_concepts_per_paper)]
            
            for concept in concepts:
                concept_freq[concept] += 1
            
            if len(concepts) >= 2:
                pairs = vectorized_combinations(concepts)
                cooccur_freq.update(pairs)
    
    return dict(concept_freq), dict(cooccur_freq), yearly_papers

def compute_chi2_worker(args):
    """并行计算卡方检验的worker函数"""
    (c1, c2), freq, concept_freq, total_papers = args
    
    p_c1 = concept_freq[c1] / total_papers
    p_c2 = concept_freq[c2] / total_papers
    p_c1_c2 = freq / total_papers
    
    if p_c1_c2 <= 0 or p_c1 <= 0 or p_c2 <= 0:
        return None
    
    pmi = math.log2(p_c1_c2 / (p_c1 * p_c2))
    npmi = pmi / (-math.log2(p_c1_c2)) if p_c1_c2 < 1 else 0
    
    a = freq
    b = concept_freq[c1] - freq
    c = concept_freq[c2] - freq
    d = total_papers - concept_freq[c1] - concept_freq[c2] + freq
    
    chi2, p_value, _, _ = chi2_contingency([[a, b], [c, d]])
    
    return (c1, c2), {
        'frequency': freq,
        'pmi': pmi,
        'npmi': npmi,
        'chi2': chi2,
        'p_value': p_value,
        'lift': (freq / total_papers) / (p_c1 * p_c2),
        'jaccard': freq / (concept_freq[c1] + concept_freq[c2] - freq)
    }

# =========================
# 共现矩阵构建
# =========================
class CooccurrenceAnalyzer:
    def __init__(self, mentions_df=None, concept_info=None, valid_concepts=None, processed_papers=None, streaming_mode=False):
        self.mentions_df = mentions_df
        self.concept_info = concept_info
        self.valid_concepts = set(valid_concepts) if valid_concepts else set()
        self.processed_papers = processed_papers or set()
        self.streaming_mode = streaming_mode
        
        if not streaming_mode and mentions_df is not None:
            # 按年份组织数据（不过滤已处理论文，用于判断）
            self.yearly_papers_all = defaultdict(lambda: defaultdict(list))
            # 按年份组织数据（过滤已处理论文，用于处理）
            self.yearly_papers = defaultdict(lambda: defaultdict(list))
            self._build_yearly_papers()
        else:
            self.yearly_papers_all = defaultdict(lambda: defaultdict(list))
            self.yearly_papers = defaultdict(lambda: defaultdict(list))
        
        # 存储结果
        self.yearly_networks = {}
        self.yearly_stats = {}

    def _build_yearly_papers(self):
        """构建年度-论文-概念映射"""
        print("📊 构建年度论文-概念映射...")
        
        filtered_count = 0
        for _, row in tqdm(self.mentions_df.iterrows(), total=len(self.mentions_df), desc="处理提及记录"):
            if row['concept_id'] not in self.valid_concepts:
                continue
                
            year = row['year']
            paper_id = row['paper_id']
            concept_id = row['concept_id']
            
            if pd.notna(year) and pd.notna(paper_id):
                year_int = int(year)
                # 构建完整映射（用于判断）
                self.yearly_papers_all[year_int][paper_id].append(concept_id)
                # 构建过滤映射（用于处理）
                if paper_id not in self.processed_papers:
                    self.yearly_papers[year_int][paper_id].append(concept_id)
                else:
                    filtered_count += 1
        
        if filtered_count > 0:
            print(f"已过滤 {filtered_count} 条已处理论文的记录")
        
        # 限制每篇论文的概念数量
        for yearly_dict in [self.yearly_papers_all, self.yearly_papers]:
            for year in yearly_dict:
                for paper_id in yearly_dict[year]:
                    concepts = list(set(yearly_dict[year][paper_id]))  # 去重
                    if len(concepts) > MAX_CONCEPTS_PER_PAPER:
                        # 保留频次最高的概念
                        concept_counts = Counter(yearly_dict[year][paper_id])
                        top_concepts = [c for c, _ in concept_counts.most_common(MAX_CONCEPTS_PER_PAPER)]
                        yearly_dict[year][paper_id] = top_concepts
                    else:
                        yearly_dict[year][paper_id] = concepts
        
        print(f"已构建 {len(self.yearly_papers_all)} 年的映射（完整）")
        print(f"待处理 {len(self.yearly_papers)} 年的映射（已过滤）")

    def compute_yearly_cooccurrence(self, year):
        """计算指定年份的共现矩阵"""
        if year not in self.yearly_papers:
            return None, {}
        
        papers = self.yearly_papers[year]
        print(f"计算 {year} 年共现矩阵（{len(papers)} 篇论文）")
        
        # 统计概念频次和共现频次
        concept_freq = Counter()
        cooccur_freq = Counter()
        total_papers = len(papers)
        
        for paper_id, concepts in tqdm(papers.items(), desc=f"{year}年"):
            # 概念频次
            for concept in concepts:
                concept_freq[concept] += 1
            
            # 共现频次（概念对，优化：使用NumPy向量化）
            if len(concepts) >= 2:
                pairs = vectorized_combinations(concepts)
                cooccur_freq.update(pairs)
        
        # 计算PMI和其他指标
        cooccur_matrix = {}
        valid_pairs = 0
        
        for (c1, c2), freq in cooccur_freq.items():
            if freq < MIN_COOCCUR_FREQ:
                continue
            
            # PMI计算
            p_c1 = concept_freq[c1] / total_papers
            p_c2 = concept_freq[c2] / total_papers  
            p_c1_c2 = freq / total_papers
            
            if p_c1_c2 > 0 and p_c1 > 0 and p_c2 > 0:
                pmi = math.log2(p_c1_c2 / (p_c1 * p_c2))
                
                # 归一化PMI (NPMI)
                npmi = pmi / (-math.log2(p_c1_c2)) if p_c1_c2 < 1 else 0
                
                # 卡方检验（独立性）
                # 构建2x2列联表
                a = freq
                b = concept_freq[c1] - freq
                c = concept_freq[c2] - freq
                d = total_papers - concept_freq[c1] - concept_freq[c2] + freq
                
                chi2, p_value, _, _ = chi2_contingency([[a, b], [c, d]])
                
                cooccur_matrix[(c1, c2)] = {
                    'frequency': freq,
                    'pmi': pmi,
                    'npmi': npmi,
                    'chi2': chi2,
                    'p_value': p_value,
                    'lift': (freq / total_papers) / (p_c1 * p_c2),
                    'jaccard': freq / (concept_freq[c1] + concept_freq[c2] - freq)
                }
                valid_pairs += 1
        
        stats = {
            'year': year,
            'total_papers': total_papers,
            'unique_concepts': len(concept_freq),
            'total_pairs': len(cooccur_freq),
            'valid_pairs': valid_pairs,
            'concept_freq': dict(concept_freq)
        }
        
        print(f"{year}年: {valid_pairs} 个有效共现对（共 {len(cooccur_freq)} 个）")
        return cooccur_matrix, stats

    def compute_yearly_cooccurrence_streaming(self, year, use_disk_storage=True):
        """流式计算指定年份的共现矩阵（支持大规模数据）"""
        print(f"计算 {year} 年共现矩阵（流式处理）...")
        
        if use_disk_storage:
            db_path = TEMP_DIR / f"cooccur_{year}.db"
            if db_path.exists():
                db_path.unlink()
            disk_counter = DiskCooccurrenceCounter(str(db_path))
        else:
            disk_counter = None
            cooccur_freq = Counter()
        
        concept_freq = Counter()
        yearly_papers_all = defaultdict(list)
        total_papers = 0
        processed_papers_set = set(self.processed_papers) if self.processed_papers else set()
        
        chunk_iter = stream_mentions_chunks(valid_concepts=self.valid_concepts, years=[year])
        total_mentions = get_total_mentions_count(years=[year])
        total_chunks = (total_mentions + CHUNK_SIZE - 1) // CHUNK_SIZE if total_mentions > 0 else 0
        
        chunk_args = []
        for chunk in tqdm(chunk_iter, total=total_chunks, desc=f"{year}年-处理数据块"):
            chunk_year = chunk[chunk['year'] == year].copy()
            if len(chunk_year) == 0:
                continue
            
            chunk_args.append((chunk_year, self.valid_concepts, processed_papers_set, MAX_CONCEPTS_PER_PAPER))
        
        if chunk_args:
            with mp.Pool(processes=NUM_WORKERS) as pool:
                results = pool.starmap(compute_chunk_cooccurrence, chunk_args)
                
                paper_ids_seen = set()
                for chunk_concept_freq, chunk_cooccur_freq, chunk_yearly_papers in results:
                    concept_freq.update(chunk_concept_freq)
                    
                    if use_disk_storage:
                        disk_counter.add_batch(chunk_cooccur_freq)
                    else:
                        cooccur_freq.update(chunk_cooccur_freq)
                    
                    for y, papers in chunk_yearly_papers.items():
                        if y == year:
                            for paper_id, concepts in papers.items():
                                if paper_id not in paper_ids_seen:
                                    paper_ids_seen.add(paper_id)
                                    total_papers += 1
                                if paper_id in yearly_papers_all:
                                    existing_concepts = set(yearly_papers_all[paper_id])
                                    new_concepts = set(concepts)
                                    yearly_papers_all[paper_id] = list(existing_concepts | new_concepts)
                                else:
                                    yearly_papers_all[paper_id] = concepts.copy()
            
            self.yearly_papers_all[year] = yearly_papers_all
        else:
            print(f"警告: {year}年没有找到数据")
            if use_disk_storage:
                disk_counter.close()
            return None, {}
        
        if use_disk_storage:
            disk_counter.flush()
            cooccur_freq = disk_counter.get_all()
            disk_counter.close()
        
        print(f"{year}年: {total_papers} 篇论文, {len(concept_freq)} 个概念, {len(cooccur_freq)} 个共现对")
        
        if len(cooccur_freq) == 0:
            return None, {}
        
        print(f"计算统计指标（并行处理 {len(cooccur_freq)} 个共现对）...")
        total_papers = max(total_papers, 1)
        
        chi2_args = [
            ((c1, c2), freq, concept_freq, total_papers)
            for (c1, c2), freq in cooccur_freq.items()
            if freq >= MIN_COOCCUR_FREQ
        ]
        
        cooccur_matrix = {}
        if chi2_args:
            with mp.Pool(processes=NUM_WORKERS) as pool:
                results = pool.map(compute_chi2_worker, tqdm(chi2_args, desc=f"{year}年-计算统计指标"))
                for result in results:
                    if result is not None:
                        pair, metrics = result
                        cooccur_matrix[pair] = metrics
        
        stats = {
            'year': year,
            'total_papers': total_papers,
            'unique_concepts': len(concept_freq),
            'total_pairs': len(cooccur_freq),
            'valid_pairs': len(cooccur_matrix),
            'concept_freq': dict(concept_freq)
        }
        
        print(f"{year}年: {len(cooccur_matrix)} 个有效共现对（共 {len(cooccur_freq)} 个）")
        return cooccur_matrix, stats

    def build_network_from_cooccurrence(self, cooccur_matrix, stats, weight_metric='npmi', threshold=NPMI_THRESHOLD):
        """从共现矩阵构建网络图"""
        G = nx.Graph()
        
        # 添加节点（概念）
        for concept_id, freq in stats['concept_freq'].items():
            if concept_id in self.concept_info:
                G.add_node(concept_id, 
                          frequency=freq,
                          canonical=self.concept_info[concept_id]['canonical'],
                          text=self.concept_info[concept_id]['text'])
        
        # 添加边（共现关系）
        edges_added = 0
        for (c1, c2), metrics in cooccur_matrix.items():
            weight = metrics[weight_metric]
            
            if weight >= threshold and metrics['p_value'] < 0.05:  # 显著性检验
                G.add_edge(c1, c2, 
                          weight=weight,
                          frequency=metrics['frequency'],
                          pmi=metrics['pmi'],
                          npmi=metrics['npmi'],
                          chi2=metrics['chi2'],
                          p_value=metrics['p_value'],
                          lift=metrics['lift'],
                          jaccard=metrics['jaccard'])
                edges_added += 1
        
        print(f"网络构建完成: {G.number_of_nodes()} 个节点, {G.number_of_edges()} 条边")
        return G

    def detect_communities(self, G, resolution=COMMUNITY_RESOLUTION):
        """社区检测"""
        if G.number_of_edges() == 0:
            return {}
        
        try:
            import networkx.algorithms.community as nx_comm
            
            # Louvain社区检测
            communities = nx_comm.louvain_communities(G, resolution=resolution, weight='weight')
            
            # 过滤小社区
            large_communities = [c for c in communities if len(c) >= COMMUNITY_MIN_SIZE]
            
            # 构建概念到社区的映射
            concept_to_community = {}
            for i, community in enumerate(large_communities):
                for concept in community:
                    concept_to_community[concept] = i
            
            print(f"检测到 {len(large_communities)} 个社区（最小规模={COMMUNITY_MIN_SIZE}）")
            return concept_to_community
            
        except ImportError:
            print("⚠️  警告: 社区检测需要 python-louvain 包")
            return {}

    def analyze_network_centrality(self, G):
        """计算网络中心性指标"""
        centrality_metrics = {}
        
        if G.number_of_edges() == 0:
            return centrality_metrics
        
        print("📈 计算网络中心性指标...")
        
        # 度中心性
        centrality_metrics['degree'] = nx.degree_centrality(G)
        
        # 介数中心性（对大网络采样计算）
        if G.number_of_nodes() > 1000:
            k = min(100, G.number_of_nodes())
            centrality_metrics['betweenness'] = nx.betweenness_centrality(G, k=k, weight='weight')
        else:
            centrality_metrics['betweenness'] = nx.betweenness_centrality(G, weight='weight')
        
        # 特征向量中心性
        try:
            centrality_metrics['eigenvector'] = nx.eigenvector_centrality(G, weight='weight', max_iter=1000)
        except (nx.PowerIterationFailedConvergence, ValueError, ZeroDivisionError) as e:
            centrality_metrics['eigenvector'] = {}
        
        # PageRank
        centrality_metrics['pagerank'] = nx.pagerank(G, weight='weight')
        
        return centrality_metrics

    def process_all_years(self, years_to_process=None, saved_yearly_papers=None, use_streaming=False):
        """处理指定年份的共现网络"""
        if use_streaming or self.streaming_mode:
            return self.process_all_years_streaming(years_to_process, saved_yearly_papers)
        
        if years_to_process is None:
            years_to_process = sorted(self.yearly_papers.keys())
        else:
            years_to_process = sorted(years_to_process)
        
        print(f"处理共现网络，年份: {years_to_process}")
        
        for year in years_to_process:
            if year not in self.yearly_papers:
                continue
            
            # 如果有已保存的该年论文数据，需要合并新旧论文重新计算
            if saved_yearly_papers and year in saved_yearly_papers:
                saved_papers = saved_yearly_papers[year]
                current_papers = self.yearly_papers[year]
                
                # 验证：确保新旧论文无交集
                saved_set = set(saved_papers.keys())
                current_set = set(current_papers.keys())
                overlap = saved_set & current_set
                if overlap:
                    print(f"  ⚠️  警告: {year}年发现 {len(overlap)} 篇论文重复（已保存与新论文重叠），将使用新论文数据")
                
                merged_papers = {**saved_papers, **current_papers}
                saved_concepts = set()
                current_concepts = set()
                for concepts in saved_papers.values():
                    saved_concepts.update(concepts)
                for concepts in current_papers.values():
                    current_concepts.update(concepts)
                
                print(f"\n=== 处理 {year} 年（合并 {len(saved_papers)} 篇已处理 + {len(current_papers)} 篇新增） ===")
                print(f"  合并前: {len(saved_papers)} 篇论文, {len(saved_concepts)} 个概念")
                print(f"  新增: {len(current_papers)} 篇论文, {len(current_concepts)} 个概念")
                print(f"  合并后: {len(merged_papers)} 篇论文, {len(saved_concepts | current_concepts)} 个概念")
                
                original_papers = self.yearly_papers[year]
                self.yearly_papers[year] = merged_papers
            else:
                print(f"\n=== 处理 {year} 年 ===")
            
            # 计算共现矩阵
            cooccur_matrix, stats = self.compute_yearly_cooccurrence(year)
            
            if cooccur_matrix is None:
                if saved_yearly_papers and year in saved_yearly_papers:
                    self.yearly_papers[year] = original_papers
                continue
            
            # 验证：记录计算后的统计信息
            if saved_yearly_papers and year in saved_yearly_papers:
                print(f"  计算完成: {stats['total_papers']} 篇论文, {stats['unique_concepts']} 个概念, {stats['valid_pairs']} 个有效共现对")
            
            # 构建网络
            G = self.build_network_from_cooccurrence(cooccur_matrix, stats)
            
            if G.number_of_nodes() == 0:
                if saved_yearly_papers and year in saved_yearly_papers:
                    self.yearly_papers[year] = original_papers
                continue
            
            # 社区检测
            communities = self.detect_communities(G)
            
            # 中心性分析
            centrality = self.analyze_network_centrality(G)
            
            # 保存结果
            self.yearly_networks[year] = {
                'graph': G,
                'communities': communities,
                'centrality': centrality,
                'cooccurrence_matrix': cooccur_matrix,
                'stats': stats
            }
            
            self.yearly_stats[year] = stats
            
            # 恢复原始论文列表（如果合并过）
            if saved_yearly_papers and year in saved_yearly_papers:
                self.yearly_papers[year] = original_papers
        
        return self.yearly_networks, self.yearly_stats
    
    def process_all_years_streaming(self, years_to_process=None, saved_yearly_papers=None):
        """流式处理指定年份的共现网络（支持大规模数据）"""
        if years_to_process is None:
            years_to_process = get_all_years()
        else:
            years_to_process = sorted(years_to_process)
        
        print(f"流式处理共现网络，年份: {years_to_process}")
        
        for year in years_to_process:
            print(f"\n=== 流式处理 {year} 年 ===")
            
            # 使用流式方法计算共现矩阵
            cooccur_matrix, stats = self.compute_yearly_cooccurrence_streaming(year, use_disk_storage=USE_DISK_STORAGE)
            
            if cooccur_matrix is None:
                continue
            
            # 构建网络
            G = self.build_network_from_cooccurrence(cooccur_matrix, stats)
            
            if G.number_of_nodes() == 0:
                continue
            
            # 社区检测
            communities = self.detect_communities(G)
            
            # 中心性分析
            centrality = self.analyze_network_centrality(G)
            
            # 保存结果
            self.yearly_networks[year] = {
                'graph': G,
                'communities': communities,
                'centrality': centrality,
                'cooccurrence_matrix': cooccur_matrix,
                'stats': stats
            }
            
            self.yearly_stats[year] = stats
        
        return self.yearly_networks, self.yearly_stats

# =========================
# 网络分析与可视化
# =========================
def analyze_network_evolution(yearly_networks, concept_info):
    """分析网络演化特征"""
    evolution_stats = []
    
    for year, data in sorted(yearly_networks.items()):
        G = data['graph']
        stats = data['stats']
        
        # 基础网络统计
        basic_stats = {
            'year': year,
            'nodes': G.number_of_nodes(),
            'edges': G.number_of_edges(),
            'density': nx.density(G),
            'total_papers': stats['total_papers']
        }
        
        # 连通性统计
        if G.number_of_edges() > 0:
            components = list(nx.connected_components(G))
            basic_stats.update({
                'num_components': len(components),
                'largest_component_size': len(max(components, key=len)) if components else 0,
                'avg_clustering': nx.average_clustering(G, weight='weight'),
                'avg_degree': sum(dict(G.degree()).values()) / G.number_of_nodes()
            })
            
            # 小世界特征
            if G.number_of_nodes() > 10:
                try:
                    largest_cc = G.subgraph(max(components, key=len))
                    if largest_cc.number_of_nodes() > 10:
                        basic_stats['avg_path_length'] = nx.average_shortest_path_length(largest_cc, weight='weight')
                except (nx.NetworkXError, ValueError, ZeroDivisionError) as e:
                    basic_stats['avg_path_length'] = np.nan
        else:
            basic_stats.update({
                'num_components': 0,
                'largest_component_size': 0,
                'avg_clustering': 0,
                'avg_degree': 0,
                'avg_path_length': np.nan
            })
        
        # 社区统计
        communities = data['communities']
        if communities:
            community_sizes = Counter(communities.values())
            basic_stats.update({
                'num_communities': len(community_sizes),
                'avg_community_size': np.mean(list(community_sizes.values())),
                'max_community_size': max(community_sizes.values()),
                'modularity': nx.community.modularity(G, 
                    [set(k for k, v in communities.items() if v == c) 
                     for c in set(communities.values())], weight='weight')
            })
        else:
            basic_stats.update({
                'num_communities': 0,
                'avg_community_size': 0,
                'max_community_size': 0,
                'modularity': 0
            })
        
        evolution_stats.append(basic_stats)
    
    return pd.DataFrame(evolution_stats)

def find_emerging_connections(yearly_networks, window_size=3):
    """检测新兴的概念连接"""
    years = sorted(yearly_networks.keys())
    emerging_connections = []
    
    for i, year in enumerate(years[window_size:], window_size):
        current_G = yearly_networks[year]['graph']
        
        # 收集前window_size年的所有边
        historical_edges = set()
        for prev_year in years[i-window_size:i]:
            if prev_year in yearly_networks:
                prev_G = yearly_networks[prev_year]['graph']
                historical_edges.update(prev_G.edges())
        
        # 找到新出现的边
        new_edges = set(current_G.edges()) - historical_edges
        
        for edge in new_edges:
            c1, c2 = edge
            edge_data = current_G[c1][c2]
            
            emerging_connections.append({
                'year': year,
                'concept_1': c1,
                'concept_2': c2,
                'weight': edge_data['weight'],
                'frequency': edge_data['frequency'],
                'pmi': edge_data['pmi'],
                'npmi': edge_data['npmi']
            })
    
    return pd.DataFrame(emerging_connections)

def save_yearly_networks(yearly_networks, yearly_stats, output_dir, yearly_papers=None):
    """保存年度网络数据"""
    output_dir = Path(output_dir)
    
    # 保存网络统计
    stats_df = pd.DataFrame.from_dict(yearly_stats, orient='index')
    stats_df.to_parquet(output_dir / "yearly_network_stats.parquet", index=False)
    
    # 保存每年的网络
    for year, data in yearly_networks.items():
        year_dir = output_dir / str(year)
        year_dir.mkdir(exist_ok=True)
        
        G = data['graph']
        
        # 保存网络图
        nx.write_gml(G, year_dir / f"network_{year}.gml")
        
        # 保存边列表
        edges_data = []
        for u, v, attr in G.edges(data=True):
            edges_data.append({
                'source': u, 'target': v, **attr
            })
        pd.DataFrame(edges_data).to_parquet(year_dir / f"edges_{year}.parquet", index=False)
        
        # 保存节点列表
        nodes_data = []
        for node, attr in G.nodes(data=True):
            nodes_data.append({
                'concept_id': node, **attr
            })
        pd.DataFrame(nodes_data).to_parquet(year_dir / f"nodes_{year}.parquet", index=False)
        
        # 保存社区信息
        if data['communities']:
            community_df = pd.DataFrame([
                {'concept_id': concept, 'community': community}
                for concept, community in data['communities'].items()
            ])
            community_df.to_parquet(year_dir / f"communities_{year}.parquet", index=False)
        
        # 保存中心性指标
        centrality_data = []
        for concept in G.nodes():
            row = {'concept_id': concept}
            for metric, values in data['centrality'].items():
                row[f'{metric}_centrality'] = values.get(concept, 0)
            centrality_data.append(row)
        pd.DataFrame(centrality_data).to_parquet(year_dir / f"centrality_{year}.parquet", index=False)
        
        # 保存论文ID集合（用于增量更新检测）
        if yearly_papers and year in yearly_papers:
            paper_ids = list(yearly_papers[year].keys())
            paper_ids_df = pd.DataFrame({'paper_id': paper_ids})
            paper_ids_df.to_parquet(year_dir / f"paper_ids_{year}.parquet", index=False)
            
            # 保存论文-概念映射（优化增量更新性能）
            paper_concepts_data = []
            for paper_id, concepts in yearly_papers[year].items():
                paper_concepts_data.append({
                    'paper_id': paper_id,
                    'concept_ids': json.dumps(concepts) if concepts else '[]'
                })
            if paper_concepts_data:
                paper_concepts_df = pd.DataFrame(paper_concepts_data)
                paper_concepts_df.to_parquet(year_dir / f"paper_concepts_{year}.parquet", index=False)
    
    print(f"网络已保存至: {output_dir}")

def load_processed_papers(output_dir):
    """加载已处理的论文ID集合"""
    processed_file = Path(output_dir) / "processed_papers.parquet"
    if processed_file.exists():
        df = pd.read_parquet(processed_file)
        return set(df['paper_id'].tolist())
    return set()

def save_processed_papers(processed_papers, output_dir):
    """保存已处理的论文ID集合"""
    processed_file = Path(output_dir) / "processed_papers.parquet"
    if processed_papers:
        df = pd.DataFrame({'paper_id': list(processed_papers)})
        df.to_parquet(processed_file, index=False)

def load_saved_networks(output_dir):
    """加载已保存的网络数据"""
    output_dir = Path(output_dir)
    if not output_dir.exists():
        return {}, {}, {}
    
    yearly_networks = {}
    yearly_paper_ids = {}
    yearly_papers_data = {}
    
    # 检查是否有已保存的统计文件
    stats_file = output_dir / "yearly_network_stats.parquet"
    if not stats_file.exists():
        return {}, {}, {}
    
    stats_df = pd.read_parquet(stats_file)
    saved_years = stats_df['year'].tolist() if 'year' in stats_df.columns else []
    
    for year in saved_years:
        year_dir = output_dir / str(year)
        if not year_dir.exists():
            continue
        
        # 加载网络图
        gml_file = year_dir / f"network_{year}.gml"
        if gml_file.exists():
            try:
                G = nx.read_gml(gml_file)
            except (IOError, OSError, nx.NetworkXError, ValueError) as e:
                continue
        else:
            continue
        
        # 加载社区信息
        communities = {}
        community_file = year_dir / f"communities_{year}.parquet"
        if community_file.exists():
            community_df = pd.read_parquet(community_file)
            communities = dict(zip(community_df['concept_id'], community_df['community']))
        
        # 加载中心性指标
        centrality = {}
        centrality_file = year_dir / f"centrality_{year}.parquet"
        if centrality_file.exists():
            centrality_df = pd.read_parquet(centrality_file)
            for metric in ['degree', 'betweenness', 'eigenvector', 'pagerank']:
                col = f'{metric}_centrality'
                if col in centrality_df.columns:
                    centrality[metric] = dict(zip(centrality_df['concept_id'], centrality_df[col]))
        
        # 加载共现矩阵（从边列表重建）
        cooccur_matrix = {}
        edges_file = year_dir / f"edges_{year}.parquet"
        if edges_file.exists():
            edges_df = pd.read_parquet(edges_file)
            for _, row in edges_df.iterrows():
                pair = (row['source'], row['target'])
                cooccur_matrix[pair] = {
                    'frequency': row.get('frequency', 0),
                    'pmi': row.get('pmi', 0),
                    'npmi': row.get('npmi', 0),
                    'chi2': row.get('chi2', 0),
                    'p_value': row.get('p_value', 1),
                    'lift': row.get('lift', 0),
                    'jaccard': row.get('jaccard', 0)
                }
        
        # 加载统计信息
        stats = {}
        if 'year' in stats_df.columns and year in stats_df['year'].values:
            year_stats = stats_df[stats_df['year'] == year].iloc[0]
            stats = year_stats.to_dict()
            if 'concept_freq' in stats and isinstance(stats['concept_freq'], str):
                import ast
                stats['concept_freq'] = ast.literal_eval(stats['concept_freq'])
        
        yearly_networks[year] = {
            'graph': G,
            'communities': communities,
            'centrality': centrality,
            'cooccurrence_matrix': cooccur_matrix,
            'stats': stats
        }
        
        # 加载论文ID集合
        paper_ids_file = year_dir / f"paper_ids_{year}.parquet"
        if paper_ids_file.exists():
            paper_ids_df = pd.read_parquet(paper_ids_file)
            paper_ids = set(paper_ids_df['paper_id'].tolist())
            yearly_paper_ids[year] = paper_ids
            
            # 加载论文-概念映射（优化：直接加载，避免重建）
            paper_concepts_file = year_dir / f"paper_concepts_{year}.parquet"
            if paper_concepts_file.exists():
                paper_concepts_df = pd.read_parquet(paper_concepts_file)
                yearly_papers_data[year] = {}
                for _, row in paper_concepts_df.iterrows():
                    concept_ids = row['concept_ids']
                    if isinstance(concept_ids, str):
                        concept_ids = json.loads(concept_ids)
                    elif not isinstance(concept_ids, list):
                        concept_ids = list(concept_ids) if concept_ids else []
                    yearly_papers_data[year][row['paper_id']] = concept_ids
            else:
                yearly_papers_data[year] = {}
        else:
            yearly_paper_ids[year] = set()
            yearly_papers_data[year] = {}
    
    return yearly_networks, yearly_paper_ids, yearly_papers_data

def detect_years_to_update(current_yearly_papers, saved_yearly_paper_ids):
    """检测需要更新的年份
    
    判断逻辑：
    - 如果输入数据中某年的论文ID集合等于已保存的论文ID集合，且都不为空，则已完全处理，跳过
    - 如果输入数据中某年的论文ID集合包含已保存的论文ID集合，且有新增，则需要更新
    - 如果输入数据中某年的论文ID集合是已保存论文ID集合的真子集，说明输入数据不完整，需要更新
    - 如果已保存集合为空，需要处理
    """
    years_to_update = []
    years_to_skip = []
    
    for year, current_paper_ids in current_yearly_papers.items():
        current_set = set(current_paper_ids.keys())
        saved_set = saved_yearly_paper_ids.get(year, set())
        
        if not saved_set:
            years_to_update.append(year)
        elif current_set == saved_set and len(current_set) > 0:
            years_to_skip.append(year)
        else:
            new_papers = current_set - saved_set
            removed_papers = saved_set - current_set
            if new_papers:
                years_to_update.append(year)
                print(f"  {year}年: 新增 {len(new_papers)} 篇论文")
            elif removed_papers:
                years_to_update.append(year)
                print(f"  {year}年: 输入数据缺少 {len(removed_papers)} 篇已保存论文，重新处理")
            else:
                years_to_update.append(year)
    
    return years_to_update, years_to_skip

def visualize_network_evolution(evolution_df, output_dir):
    """可视化网络演化趋势"""
    fig, axes = plt.subplots(2, 3, figsize=(18, 12))
    axes = axes.ravel()
    
    metrics = [
        ('nodes', 'Number of Concepts'),
        ('edges', 'Number of Connections'), 
        ('density', 'Network Density'),
        ('avg_clustering', 'Average Clustering'),
        ('num_communities', 'Number of Communities'),
        ('modularity', 'Modularity')
    ]
    
    for i, (metric, title) in enumerate(metrics):
        if metric in evolution_df.columns:
            axes[i].plot(evolution_df['year'], evolution_df[metric], marker='o', linewidth=2)
            axes[i].set_title(title, fontsize=12, fontweight='bold')
            axes[i].set_xlabel('Year')
            axes[i].grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(Path(output_dir) / "network_evolution.png", dpi=300, bbox_inches='tight')
    plt.show()

# =========================
# 主流程
# =========================
def main(use_streaming=True):
    print("=== 阶段3: 构建共现网络 ===\n")
    
    if HAS_DUCKDB:
        print("✅ DuckDB已启用（性能优化：3-8倍提升）")
    else:
        print("ℹ️  DuckDB未安装，使用SQLite（建议安装: pip install duckdb）")
    
    if use_streaming:
        print("🚀 使用流式处理模式（支持大规模数据）")
        print(f"   块大小: {CHUNK_SIZE:,} 条记录/块")
        print(f"   并行进程数: {NUM_WORKERS}")
        print(f"   磁盘存储: {'启用' if USE_DISK_STORAGE else '禁用'}")
        print(f"   优化: NumPy向量化组合生成\n")
    
    # 1. 加载概念信息（不加载提及数据）
    concept_info = load_concept_info()
    
    # 2. 加载已处理的论文ID
    processed_papers = load_processed_papers(COOCCURRENCE_DIR)
    if processed_papers:
        print(f"📋 已加载 {len(processed_papers)} 篇已处理论文ID")
    
    # 2.1 数据一致性检查
    saved_networks, saved_paper_ids, saved_papers_data = load_saved_networks(COOCCURRENCE_DIR)
    if saved_networks and processed_papers:
        all_saved_papers = set()
        for year_papers in saved_paper_ids.values():
            all_saved_papers.update(year_papers)
        
        missing_in_processed = all_saved_papers - processed_papers
        if missing_in_processed:
            print(f"⚠️  警告: {len(missing_in_processed)} 篇已保存论文未在processed_papers中，可能存在数据不一致")
        
        extra_in_processed = processed_papers - all_saved_papers
        if extra_in_processed:
            print(f"ℹ️  信息: {len(extra_in_processed)} 篇论文在processed_papers中但未保存到网络（可能是新处理但未构建网络）")
    
    # 3. 过滤低频概念
    if use_streaming:
        valid_concepts = filter_concepts_by_frequency_streaming()
    else:
        mentions_df, concept_info_old = load_concept_data()
        filtered_mentions, valid_concepts = filter_concepts_by_frequency(mentions_df)
        concept_info = concept_info_old
    
    # 4. 构建共现分析器
    if use_streaming:
        analyzer = CooccurrenceAnalyzer(
            concept_info=concept_info, 
            valid_concepts=valid_concepts, 
            processed_papers=processed_papers,
            streaming_mode=True
        )
    else:
        analyzer = CooccurrenceAnalyzer(
            mentions_df=filtered_mentions, 
            concept_info=concept_info, 
            valid_concepts=valid_concepts, 
            processed_papers=processed_papers,
            streaming_mode=False
        )
    
    # 5. 检测增量更新
    print("🔍 检测增量更新...")
    # saved_networks已在一致性检查中加载
    
    yearly_networks = {}
    yearly_stats = {}
    
    if saved_networks:
        print(f"已找到 {len(saved_networks)} 年的已保存网络")
        if use_streaming:
            current_yearly_papers_streaming = build_current_yearly_paper_ids_streaming(
                valid_concepts=valid_concepts, 
                processed_papers=processed_papers
            )
            years_to_update, years_to_skip = detect_years_to_update(
                current_yearly_papers_streaming, saved_paper_ids
            )
        else:
            years_to_update, years_to_skip = detect_years_to_update(
                analyzer.yearly_papers_all, saved_paper_ids
            )
        
        if years_to_skip:
            print(f"跳过 {len(years_to_skip)} 年（已完全处理）: {years_to_skip}")
            for year in years_to_skip:
                yearly_networks[year] = saved_networks[year]
                if 'stats' in saved_networks[year]:
                    yearly_stats[year] = saved_networks[year]['stats']
        
        if years_to_update:
            print(f"需要更新 {len(years_to_update)} 年: {years_to_update}")
            if not use_streaming:
                # 对于有新增论文的年份，优先使用已加载的paper_concepts映射，否则从原始数据重建
                for year in years_to_update:
                    if year in saved_paper_ids and saved_paper_ids[year]:
                        if not saved_papers_data.get(year):
                            print(f"  {year}年: 从原始数据重建已保存论文的映射...")
                            saved_papers = {}
                            year_mentions = filtered_mentions[filtered_mentions['year'] == year]
                            for paper_id in saved_paper_ids[year]:
                                paper_mentions = year_mentions[year_mentions['paper_id'] == paper_id]
                                concepts = []
                                for _, row in paper_mentions.iterrows():
                                    if row['concept_id'] in valid_concepts:
                                        concepts.append(row['concept_id'])
                                if concepts:
                                    concepts = list(set(concepts))
                                    if len(concepts) > MAX_CONCEPTS_PER_PAPER:
                                        concept_counts = Counter(concepts)
                                        concepts = [c for c, _ in concept_counts.most_common(MAX_CONCEPTS_PER_PAPER)]
                                    saved_papers[paper_id] = concepts
                            saved_papers_data[year] = saved_papers
                        else:
                            print(f"  {year}年: 使用已加载的论文-概念映射（{len(saved_papers_data[year])} 篇论文）")
            
            updated_networks, updated_stats = analyzer.process_all_years(years_to_update, saved_papers_data, use_streaming=use_streaming)
            yearly_networks.update(updated_networks)
            yearly_stats.update(updated_stats)
            
            if not use_streaming:
                for year in years_to_update:
                    if year in saved_paper_ids:
                        analyzer.yearly_papers_all[year] = {
                            **saved_papers_data.get(year, {}),
                            **analyzer.yearly_papers.get(year, {})
                        }
        elif not years_to_skip:
            print("所有年份均无变化，无需更新")
    else:
        print("未找到已保存网络，执行全量处理")
        yearly_networks, yearly_stats = analyzer.process_all_years(use_streaming=use_streaming)
    
    if not yearly_networks:
        print("❌ 未生成网络，请检查数据和参数")
        return
    
    # 6. 收集所有已处理的论文ID
    all_processed_papers = processed_papers.copy()
    # 从当前处理的年份收集
    for year in analyzer.yearly_papers:
        all_processed_papers.update(analyzer.yearly_papers[year].keys())
    # 从已保存的年份收集（包括跳过的年份和已保存的论文）
    if saved_paper_ids:
        for year in saved_paper_ids:
            all_processed_papers.update(saved_paper_ids[year])
    
    # 7. 分析网络演化
    print("\n=== 分析网络演化 ===")
    evolution_df = analyze_network_evolution(yearly_networks, concept_info)
    print(evolution_df)
    
    # 8. 检测新兴连接
    print("\n=== 检测新兴连接 ===") 
    emerging_df = find_emerging_connections(yearly_networks)
    if not emerging_df.empty:
        print(f"发现 {len(emerging_df)} 个新兴连接")
        print(emerging_df.head(10))
    
    # 9. 保存结果
    print("\n=== 保存结果 ===")
    # 构建完整的年度论文映射（用于保存论文ID）
    yearly_papers_for_save = {}
    for year in yearly_networks.keys():
        if year in analyzer.yearly_papers_all:
            yearly_papers_for_save[year] = analyzer.yearly_papers_all[year]
        elif year in analyzer.yearly_papers:
            yearly_papers_for_save[year] = analyzer.yearly_papers[year]
        elif year in saved_paper_ids:
            # 从已保存的论文ID重建（跳过年份）
            yearly_papers_for_save[year] = {pid: [] for pid in saved_paper_ids[year]}
    save_yearly_networks(yearly_networks, yearly_stats, COOCCURRENCE_DIR, yearly_papers_for_save)
    save_processed_papers(all_processed_papers, COOCCURRENCE_DIR)
    print(f"已保存 {len(all_processed_papers)} 篇已处理论文ID")
    
    evolution_df.to_parquet(COOCCURRENCE_DIR / "network_evolution.parquet", index=False)
    if not emerging_df.empty:
        emerging_df.to_parquet(COOCCURRENCE_DIR / "emerging_connections.parquet", index=False)
    
    # 10. 可视化
    print("\n=== 生成可视化 ===")
    visualize_network_evolution(evolution_df, COOCCURRENCE_DIR)
    
    # 11. 输出摘要
    print(f"\n✅ 阶段3完成！")
    print(f"已生成 {len(yearly_networks)} 年的网络")
    print(f"结果保存在: {COOCCURRENCE_DIR}")
    print(f"演化趋势: {COOCCURRENCE_DIR}/network_evolution.parquet")
    if not emerging_df.empty:
        print(f"新兴连接: {COOCCURRENCE_DIR}/emerging_connections.parquet")

if __name__ == "__main__":
    main()