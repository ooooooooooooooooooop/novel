import os
import json
import re
from pathlib import Path
from collections import defaultdict, Counter
from itertools import combinations
import math
import multiprocessing as mp
from functools import partial
import sqlite3
import tempfile

import numpy as np
import pandas as pd
import spacy
from tqdm import tqdm
from sentence_transformers import SentenceTransformer
import torch

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
STAGE2_DIR = OUTPUT_BASE_DIR / "stage2_cooccurrence_networks"
STAGE3_DIR = OUTPUT_BASE_DIR / "stage3_semantic_relations"
STAGE3_DIR.mkdir(exist_ok=True)

INPUT_CSV = "2025外文论文全字段.csv"
CONCEPTS_FILE = str(STAGE1_DIR / "concepts_catalog_streaming.parquet")
MENTIONS_DIR = STAGE1_DIR / "mentions_by_year"

# 关系抽取参数
MIN_RELATION_CONFIDENCE = 0.3  # 最小关系置信度
MAX_CONTEXT_WINDOW = 100        # 上下文窗口大小（字符数）
MIN_CONTEXT_LENGTH = 10         # 最小上下文长度
MAX_RELATIONS_PER_PAIR = 5      # 每对概念最多抽取的关系数

# 关系类型定义
RELATION_TYPES = {
    'causes': ['cause', 'lead to', 'result in', 'trigger', 'induce', 'produce'],
    'inhibits': ['inhibit', 'prevent', 'block', 'suppress', 'reduce', 'decrease'],
    'enhances': ['enhance', 'improve', 'increase', 'promote', 'boost', 'strengthen'],
    'contains': ['contain', 'include', 'comprise', 'consist of', 'compose'],
    'related_to': ['relate', 'associate', 'connect', 'link', 'correlate'],
    'similar_to': ['similar', 'like', 'analogous', 'comparable', 'equivalent'],
    'different_from': ['different', 'distinct', 'unlike', 'opposite', 'contrary'],
    'uses': ['use', 'utilize', 'employ', 'apply', 'adopt'],
    'produces': ['produce', 'generate', 'create', 'yield', 'form'],
    'requires': ['require', 'need', 'demand', 'necessitate']
}

# 流式处理参数
CHUNK_SIZE = 50000
# 默认工作进程数（在main函数中会根据实际设备调整）
NUM_WORKERS_DEFAULT = min(8, mp.cpu_count())
TEMP_DIR = STAGE3_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

# 批量处理参数（优化）
PAPER_BATCH_SIZE = 50  # 每批并行处理的论文数
EMBED_BATCH_SIZE = 128  # 嵌入编码批量大小
SPACY_BATCH_SIZE = 1024  # spaCy批量处理大小

# NLP模型
EMB_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
SPACY_MODEL = "en_core_web_sm"

# =========================
# 数据加载
# =========================
def load_concept_info():
    """加载概念目录数据"""
    print("📂 加载概念目录...")
    concepts_df = pd.read_parquet(CONCEPTS_FILE)
    print(f"已加载 {len(concepts_df)} 个唯一概念")
    
    concept_info = {}
    concept_text_to_id = {}
    for _, row in concepts_df.iterrows():
        concept_id = row['concept_id']
        concept_text = row['concept_text']
        canonical = row['canonical_label']
        
        concept_info[concept_id] = {
            'text': concept_text,
            'canonical': canonical,
            'aliases': row['aliases'].split('; ') if pd.notna(row['aliases']) else []
        }
        
        concept_text_to_id[canonical.lower()] = concept_id
        concept_text_to_id[concept_text.lower()] = concept_id
        if pd.notna(row['aliases']):
            for alias in row['aliases'].split('; '):
                concept_text_to_id[alias.lower()] = concept_id
    
    return concept_info, concept_text_to_id

def load_cooccurrence_edges(years=None):
    """加载共现网络边数据"""
    print("📂 加载共现网络边...")
    edges_by_year = {}
    
    if years is None:
        year_dirs = [d for d in STAGE2_DIR.iterdir() if d.is_dir() and d.name.isdigit()]
        years = sorted([int(d.name) for d in year_dirs])
    
    for year in years:
        year_dir = STAGE2_DIR / str(year)
        edges_file = year_dir / f"edges_{year}.parquet"
        
        if edges_file.exists():
            edges_df = pd.read_parquet(edges_file)
            edges_by_year[year] = edges_df
            print(f"  {year}年: {len(edges_df)} 条边")
        else:
            print(f"  ⚠️  {year}年: 未找到边文件")
    
    return edges_by_year

def load_paper_texts(paper_ids=None, chunk_size=CHUNK_SIZE):
    """流式加载论文文本数据"""
    if not Path(INPUT_CSV).exists():
        raise FileNotFoundError(f"未找到论文文件: {INPUT_CSV}")
    
    usecols = ['入藏号', '标题', '摘要', '关键词', '出版年']
    dtype = {'入藏号': 'string', '标题': 'string', '摘要': 'string', 
             '关键词': 'string', '出版年': 'Int64'}
    
    paper_ids_set = set(paper_ids) if paper_ids else None
    
    for chunk in pd.read_csv(INPUT_CSV, usecols=usecols, dtype=dtype, 
                            chunksize=chunk_size, encoding_errors="ignore",
                            on_bad_lines='skip', keep_default_na=False):
        for _, row in chunk.iterrows():
            paper_id = str(row['入藏号'])
            if paper_ids_set and paper_id not in paper_ids_set:
                continue
            
            year = int(row['出版年']) if pd.notna(row['出版年']) else None
            if year is None:
                continue
            
            text_parts = []
            if pd.notna(row['标题']):
                text_parts.append(str(row['标题']))
            if pd.notna(row['摘要']):
                text_parts.append(str(row['摘要']))
            if pd.notna(row['关键词']):
                text_parts.append(str(row['关键词']))
            
            full_text = ' '.join(text_parts)
            if full_text.strip():
                yield {
                    'paper_id': paper_id,
                    'year': year,
                    'text': full_text,
                    'title': str(row['标题']) if pd.notna(row['标题']) else '',
                    'abstract': str(row['摘要']) if pd.notna(row['摘要']) else ''
                }

def get_paper_ids_from_edges(edges_by_year):
    """从边数据中提取论文ID"""
    paper_ids = set()
    for year, edges_df in edges_by_year.items():
        year_dir = STAGE2_DIR / str(year)
        paper_ids_file = year_dir / f"paper_ids_{year}.parquet"
        if paper_ids_file.exists():
            paper_ids_df = pd.read_parquet(paper_ids_file)
            paper_ids.update(paper_ids_df['paper_id'].tolist())
    return paper_ids

def load_paper_concepts(year):
    """加载指定年份的论文-概念映射"""
    year_dir = STAGE2_DIR / str(year)
    paper_concepts_file = year_dir / f"paper_concepts_{year}.parquet"
    
    if not paper_concepts_file.exists():
        return {}
    
    paper_concepts_df = pd.read_parquet(paper_concepts_file)
    paper_concepts = {}
    
    for _, row in paper_concepts_df.iterrows():
        paper_id = row['paper_id']
        concept_ids_str = row['concept_ids']
        if isinstance(concept_ids_str, str):
            concept_ids = json.loads(concept_ids_str)
        else:
            concept_ids = list(concept_ids_str) if concept_ids_str else []
        paper_concepts[paper_id] = concept_ids
    
    return paper_concepts

# =========================
# 关系抽取核心模块
# =========================
class RelationExtractor:
    """语义关系抽取器"""
    
    def __init__(self, concept_info, concept_text_to_id, emb_model=None, nlp=None):
        self.concept_info = concept_info
        self.concept_text_to_id = concept_text_to_id
        self.emb_model = emb_model
        self.nlp = nlp
        self.relation_patterns = self._build_relation_patterns()
        self._position_cache = {}  # 缓存概念位置
    
    def _build_relation_patterns(self):
        """构建关系模式"""
        patterns = {}
        for rel_type, keywords in RELATION_TYPES.items():
            patterns[rel_type] = re.compile(
                r'\b(?:' + '|'.join(keywords) + r')\b',
                re.IGNORECASE
            )
        return patterns
    
    def find_concept_positions(self, text, concept_id, paper_id=None):
        """在文本中查找概念的位置（带缓存）"""
        # 使用缓存
        if paper_id is not None:
            cache_key = (paper_id, concept_id)
            if cache_key in self._position_cache:
                return self._position_cache[cache_key]
        
        concept_data = self.concept_info.get(concept_id)
        if not concept_data:
            return []
        
        positions = []
        canonical = concept_data['canonical'].lower()
        text_lower = text.lower()
        
        start = 0
        while True:
            pos = text_lower.find(canonical, start)
            if pos == -1:
                break
            positions.append((pos, pos + len(canonical)))
            start = pos + 1
        
        for alias in concept_data.get('aliases', []):
            if not alias:
                continue
            alias_lower = alias.lower()
            start = 0
            while True:
                pos = text_lower.find(alias_lower, start)
                if pos == -1:
                    break
                positions.append((pos, pos + len(alias_lower)))
                start = pos + 1
        
        result = sorted(positions, key=lambda x: x[0])
        
        # 保存到缓存
        if paper_id is not None:
            cache_key = (paper_id, concept_id)
            self._position_cache[cache_key] = result
        
        return result
    
    def clear_position_cache(self):
        """清空位置缓存"""
        self._position_cache.clear()
    
    def extract_context(self, text, pos1, pos2, window_size=MAX_CONTEXT_WINDOW):
        """提取两个概念之间的上下文"""
        start = min(pos1[0], pos2[0])
        end = max(pos1[1], pos2[1])
        
        context_start = max(0, start - window_size // 2)
        context_end = min(len(text), end + window_size // 2)
        
        context = text[context_start:context_end]
        return context.strip()
    
    def extract_relations_rule_based(self, text, concept1_id, concept2_id, paper_id=None):
        """基于规则的关系抽取"""
        positions1 = self.find_concept_positions(text, concept1_id, paper_id)
        positions2 = self.find_concept_positions(text, concept2_id, paper_id)
        
        if not positions1 or not positions2:
            return []
        
        relations = []
        for pos1 in positions1:
            for pos2 in positions2:
                if abs(pos1[0] - pos2[0]) > MAX_CONTEXT_WINDOW:
                    continue
                
                context = self.extract_context(text, pos1, pos2)
                if len(context) < MIN_CONTEXT_LENGTH:
                    continue
                
                for rel_type, pattern in self.relation_patterns.items():
                    matches = list(pattern.finditer(context))
                    if matches:
                        for match in matches:
                            confidence = self._calculate_rule_confidence(
                                context, match, pos1, pos2, concept1_id, concept2_id
                            )
                            if confidence >= MIN_RELATION_CONFIDENCE:
                                relations.append({
                                    'relation_type': rel_type,
                                    'confidence': confidence,
                                    'context': context,
                                    'method': 'rule_based'
                                })
        
        return relations[:MAX_RELATIONS_PER_PAIR]
    
    def _calculate_rule_confidence(self, context, match, pos1, pos2, concept1_id, concept2_id):
        """计算基于规则的置信度"""
        base_confidence = 0.5
        
        match_pos = match.start()
        pos1_start = min(pos1[0], pos2[0])
        pos2_start = max(pos1[0], pos2[0])
        
        if pos1_start < match_pos < pos2_start:
            base_confidence += 0.3
        
        distance = abs(match_pos - (pos1_start + pos2_start) / 2)
        max_distance = len(context)
        if max_distance > 0:
            distance_score = 1 - (distance / max_distance)
            base_confidence += distance_score * 0.2
        
        return min(1.0, base_confidence)
    
    def extract_relations_dependency(self, text, concept1_id, concept2_id, paper_id=None, paper_doc=None):
        """基于依存句法分析的关系抽取（优化：批量处理）"""
        if not self.nlp:
            return []
        
        positions1 = self.find_concept_positions(text, concept1_id, paper_id)
        positions2 = self.find_concept_positions(text, concept2_id, paper_id)
        
        if not positions1 or not positions2:
            return []
        
        relations = []
        
        # 收集所有上下文
        contexts = []
        context_positions = []
        
        for pos1 in positions1[:3]:
            for pos2 in positions2[:3]:
                if abs(pos1[0] - pos2[0]) > MAX_CONTEXT_WINDOW:
                    continue
                
                context = self.extract_context(text, pos1, pos2)
                if len(context) >= MIN_CONTEXT_LENGTH:
                    contexts.append(context)
                    context_positions.append((pos1, pos2))
        
        if not contexts:
            return []
        
        # 批量处理上下文
        context_docs = list(self.nlp.pipe(contexts, batch_size=SPACY_BATCH_SIZE))
        
        for context_doc, (pos1, pos2) in zip(context_docs, context_positions):
            for token in context_doc:
                if token.pos_ == 'VERB':
                    head = token.head
                    deps = [child.dep_ for child in token.children]
                    
                    if 'nsubj' in deps or 'dobj' in deps:
                        rel_type = self._classify_verb_relation(token.text.lower())
                        if rel_type:
                            confidence = 0.6
                            relations.append({
                                'relation_type': rel_type,
                                'confidence': confidence,
                                'context': context_doc.text,
                                'method': 'dependency',
                                'verb': token.text
                            })
        
        return relations[:MAX_RELATIONS_PER_PAIR]
    
    def _classify_verb_relation(self, verb):
        """根据动词分类关系类型"""
        verb_lower = verb.lower()
        for rel_type, keywords in RELATION_TYPES.items():
            if any(kw in verb_lower for kw in keywords):
                return rel_type
        return 'related_to'
    
    def extract_relations_embedding(self, text, concept1_id, concept2_id, paper_id=None):
        """基于嵌入的语义关系抽取（优化：批量编码）"""
        if not self.emb_model:
            return []
        
        positions1 = self.find_concept_positions(text, concept1_id, paper_id)
        positions2 = self.find_concept_positions(text, concept2_id, paper_id)
        
        if not positions1 or not positions2:
            return []
        
        concept1_data = self.concept_info.get(concept1_id, {})
        concept2_data = self.concept_info.get(concept2_id, {})
        concept1_text = concept1_data.get('canonical', '')
        concept2_text = concept2_data.get('canonical', '')
        
        # 收集所有上下文
        contexts = []
        context_positions = []
        
        for pos1 in positions1[:2]:
            for pos2 in positions2[:2]:
                if abs(pos1[0] - pos2[0]) > MAX_CONTEXT_WINDOW:
                    continue
                
                context = self.extract_context(text, pos1, pos2)
                if len(context) >= MIN_CONTEXT_LENGTH:
                    contexts.append(context)
                    context_positions.append((pos1, pos2))
        
        if not contexts:
            return []
        
        context_embs = self.emb_model.encode(
            contexts, 
            convert_to_numpy=True,
            batch_size=EMBED_BATCH_SIZE,
            show_progress_bar=False
        )
        
        relation_templates = []
        for rel_type, keywords in RELATION_TYPES.items():
            for keyword in keywords[:3]:
                relation_templates.append(f"{concept1_text} {keyword} {concept2_text}")
        
        relation_embs = self.emb_model.encode(
            relation_templates,
            convert_to_numpy=True,
            batch_size=EMBED_BATCH_SIZE,
            show_progress_bar=False
        )
        
        relations = []
        for i, (context, context_emb) in enumerate(zip(contexts, context_embs)):
            best_relation = None
            best_confidence = MIN_RELATION_CONFIDENCE
            
            template_idx = 0
            for rel_type, keywords in RELATION_TYPES.items():
                for keyword in keywords[:3]:
                    relation_emb = relation_embs[template_idx]
                    similarity = np.dot(context_emb, relation_emb) / (
                        np.linalg.norm(context_emb) * np.linalg.norm(relation_emb) + 1e-8
                    )
                    
                    if similarity > best_confidence:
                        best_confidence = float(similarity)
                        best_relation = {
                            'relation_type': rel_type,
                            'confidence': best_confidence,
                            'context': context,
                            'method': 'embedding'
                        }
                    template_idx += 1
            
            if best_relation:
                relations.append(best_relation)
        
        return relations[:MAX_RELATIONS_PER_PAIR]
    
    def extract_relations(self, text, concept1_id, concept2_id, methods=['rule_based', 'dependency', 'embedding'], 
                         paper_id=None, paper_doc=None):
        """综合多种方法抽取关系"""
        all_relations = []
        
        if 'rule_based' in methods:
            relations = self.extract_relations_rule_based(text, concept1_id, concept2_id, paper_id)
            all_relations.extend(relations)
        
        if 'dependency' in methods and self.nlp:
            relations = self.extract_relations_dependency(text, concept1_id, concept2_id, paper_id, paper_doc)
            all_relations.extend(relations)
        
        if 'embedding' in methods and self.emb_model:
            relations = self.extract_relations_embedding(text, concept1_id, concept2_id, paper_id)
            all_relations.extend(relations)
        
        if not all_relations:
            return []
        
        merged_relations = self._merge_relations(all_relations)
        return merged_relations
    
    def _merge_relations(self, relations):
        """合并相同类型的关系，取最高置信度"""
        merged = {}
        for rel in relations:
            rel_type = rel['relation_type']
            if rel_type not in merged or rel['confidence'] > merged[rel_type]['confidence']:
                merged[rel_type] = rel
        
        return list(merged.values())[:MAX_RELATIONS_PER_PAIR]

# =========================
# 批量处理
# =========================
# 全局变量用于多进程（每个进程会复制）
_global_concept_info = None
_global_concept_text_to_id = None
_global_emb_model = None
_global_nlp = None

def init_worker(concept_info, concept_text_to_id, device="cpu"):
    """初始化工作进程（加载模型）"""
    global _global_concept_info, _global_concept_text_to_id, _global_emb_model, _global_nlp
    _global_concept_info = concept_info
    _global_concept_text_to_id = concept_text_to_id
    
    # 每个进程加载自己的模型，直接使用传入的device（最大化GPU利用）
    _global_emb_model = SentenceTransformer(EMB_MODEL, device=device)
    
    try:
        _global_nlp = spacy.load(SPACY_MODEL, disable=["ner"])
        _global_nlp.add_pipe("sentencizer")
    except OSError:
        _global_nlp = None

def process_paper_relations(args):
    """处理单篇论文的关系抽取（用于并行，优化版）"""
    global _global_concept_info, _global_concept_text_to_id, _global_emb_model, _global_nlp
    
    paper_data, edges = args
    
    paper_id = paper_data['paper_id']
    year = paper_data['year']
    text = paper_data['text']
    
    # 使用全局模型
    extractor = RelationExtractor(_global_concept_info, _global_concept_text_to_id, 
                                  _global_emb_model, _global_nlp)
    
    # 预过滤：先查找所有概念位置，过滤距离太远的对
    concept_positions = {}
    concept_pairs = []
    
    for _, edge in edges.iterrows():
        concept1_id = edge['source']
        concept2_id = edge['target']
        
        if concept1_id not in concept_positions:
            concept_positions[concept1_id] = extractor.find_concept_positions(text, concept1_id, paper_id)
        if concept2_id not in concept_positions:
            concept_positions[concept2_id] = extractor.find_concept_positions(text, concept2_id, paper_id)
        
        pos1 = concept_positions[concept1_id]
        pos2 = concept_positions[concept2_id]
        
        if not pos1 or not pos2:
            continue
        
        # 预过滤：检查是否有位置对在窗口内
        pos1_slice = pos1[:3]
        pos2_slice = pos2[:3]
        if not pos1_slice or not pos2_slice:
            continue
        
        min_distance = min(abs(p1[0] - p2[0]) for p1 in pos1_slice for p2 in pos2_slice)
        if min_distance <= MAX_CONTEXT_WINDOW:
            concept_pairs.append((concept1_id, concept2_id))
    
    if not concept_pairs:
        return []
    
    # 预处理：对整篇论文只处理一次spaCy（如果使用依存句法）
    paper_doc = None
    if _global_nlp:
        paper_doc = _global_nlp(text)
    
    relations = []
    
    for concept1_id, concept2_id in concept_pairs:
        paper_relations = extractor.extract_relations(
            text, concept1_id, concept2_id, 
            methods=['rule_based', 'dependency', 'embedding'],
            paper_id=paper_id, 
            paper_doc=paper_doc
        )
        
        for rel in paper_relations:
            relations.append({
                'paper_id': paper_id,
                'year': year,
                'concept1_id': concept1_id,
                'concept2_id': concept2_id,
                'relation_type': rel['relation_type'],
                'confidence': rel['confidence'],
                'context': rel['context'],
                'method': rel['method']
            })
    
    return relations

def process_paper_relations_single(paper_data, edges, extractor):
    """处理单篇论文的关系抽取（单进程模式，直接使用传入的extractor）"""
    paper_id = paper_data['paper_id']
    year = paper_data['year']
    text = paper_data['text']
    
    # 预过滤：先查找所有概念位置，过滤距离太远的对
    concept_positions = {}
    concept_pairs = []
    
    for _, edge in edges.iterrows():
        concept1_id = edge['source']
        concept2_id = edge['target']
        
        if concept1_id not in concept_positions:
            concept_positions[concept1_id] = extractor.find_concept_positions(text, concept1_id, paper_id)
        if concept2_id not in concept_positions:
            concept_positions[concept2_id] = extractor.find_concept_positions(text, concept2_id, paper_id)
        
        pos1 = concept_positions[concept1_id]
        pos2 = concept_positions[concept2_id]
        
        if not pos1 or not pos2:
            continue
        
        # 预过滤：检查是否有位置对在窗口内
        pos1_slice = pos1[:3]
        pos2_slice = pos2[:3]
        if not pos1_slice or not pos2_slice:
            continue
        
        min_distance = min(abs(p1[0] - p2[0]) for p1 in pos1_slice for p2 in pos2_slice)
        if min_distance <= MAX_CONTEXT_WINDOW:
            concept_pairs.append((concept1_id, concept2_id))
    
    if not concept_pairs:
        return []
    
    # 预处理：对整篇论文只处理一次spaCy（如果使用依存句法）
    paper_doc = None
    if extractor.nlp:
        paper_doc = extractor.nlp(text)
    
    relations = []
    
    for concept1_id, concept2_id in concept_pairs:
        paper_relations = extractor.extract_relations(
            text, concept1_id, concept2_id, 
            methods=['rule_based', 'dependency', 'embedding'],
            paper_id=paper_id, 
            paper_doc=paper_doc
        )
        
        for rel in paper_relations:
            relations.append({
                'paper_id': paper_id,
                'year': year,
                'concept1_id': concept1_id,
                'concept2_id': concept2_id,
                'relation_type': rel['relation_type'],
                'confidence': rel['confidence'],
                'context': rel['context'],
                'method': rel['method']
            })
    
    return relations

# =========================
# 数据保存与加载
# =========================
def save_relations(relations_by_year, output_dir):
    """保存关系三元组"""
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)
    
    all_relations = []
    for year, relations in relations_by_year.items():
        if not relations:
            continue
        
        relations_df = pd.DataFrame(relations)
        year_dir = output_dir / str(year)
        year_dir.mkdir(exist_ok=True)
        relations_df.to_parquet(year_dir / f"relations_{year}.parquet", index=False)
        
        all_relations.extend(relations)
    
    if not all_relations:
        print("⚠️  未找到关系数据")
        return
    
    relations_df = pd.DataFrame(all_relations)
    relations_df.to_parquet(output_dir / "semantic_relations.parquet", index=False)
    
    print(f"已保存 {len(all_relations)} 个关系三元组到: {output_dir}")

def load_processed_relations(output_dir):
    """加载已处理的关系数据"""
    output_dir = Path(output_dir)
    relations_file = output_dir / "semantic_relations.parquet"
    
    if not relations_file.exists():
        return pd.DataFrame()
    
    return pd.read_parquet(relations_file)

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

def load_saved_relations_by_year(output_dir):
    """加载已保存的年度关系数据"""
    output_dir = Path(output_dir)
    if not output_dir.exists():
        return {}, {}
    
    relations_by_year = {}
    paper_ids_by_year = {}
    
    year_dirs = [d for d in output_dir.iterdir() if d.is_dir() and d.name.isdigit()]
    
    for year_dir in year_dirs:
        year = int(year_dir.name)
        relations_file = year_dir / f"relations_{year}.parquet"
        
        if relations_file.exists():
            relations_df = pd.read_parquet(relations_file)
            relations_by_year[year] = relations_df
            
            paper_ids = set(relations_df['paper_id'].unique())
            paper_ids_by_year[year] = paper_ids
    
    return relations_by_year, paper_ids_by_year

def detect_papers_to_update(current_paper_ids, saved_paper_ids):
    """检测需要更新的论文
    
    返回:
        papers_to_skip: 已完全处理的论文集合（跳过）
        papers_to_process: 需要处理的论文集合（新增或更新）
    """
    current_set = set(current_paper_ids)
    saved_set = set(saved_paper_ids) if saved_paper_ids else set()
    
    if not saved_set:
        return set(), current_set
    
    papers_to_skip = current_set & saved_set
    papers_to_process = current_set - saved_set
    
    return papers_to_skip, papers_to_process

def merge_relations(old_relations_df, new_relations):
    """合并新旧关系数据
    
    策略：
    - 如果新关系与旧关系完全相同（paper_id, concept1_id, concept2_id, relation_type都相同），保留置信度更高的
    - 否则，直接添加新关系
    """
    if old_relations_df.empty:
        return pd.DataFrame(new_relations) if new_relations else pd.DataFrame()
    
    if not new_relations:
        return old_relations_df
    
    new_relations_df = pd.DataFrame(new_relations)
    
    old_relations_df = old_relations_df.copy()
    
    to_add = []
    for _, new_rel in new_relations_df.iterrows():
        mask = (
            (old_relations_df['paper_id'] == new_rel['paper_id']) &
            (old_relations_df['concept1_id'] == new_rel['concept1_id']) &
            (old_relations_df['concept2_id'] == new_rel['concept2_id']) &
            (old_relations_df['relation_type'] == new_rel['relation_type'])
        )
        
        matching = old_relations_df[mask]
        if len(matching) > 0:
            old_idx = matching.index[0]
            if new_rel['confidence'] > old_relations_df.loc[old_idx, 'confidence']:
                old_relations_df.loc[old_idx] = new_rel
        else:
            to_add.append(new_rel.to_dict())
    
    if to_add:
        old_relations_df = pd.concat([old_relations_df, pd.DataFrame(to_add)], ignore_index=True)
    
    return old_relations_df

# =========================
# 主流程
# =========================
def main(use_streaming=True, years=None, methods=['rule_based', 'dependency', 'embedding']):
    print("=== 阶段4: 语义关系抽取 ===\n")
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"使用设备: {device}")
    
    # 根据实际设备确定工作进程数
    # GPU模式下使用单进程，CPU模式下使用多进程
    NUM_WORKERS = 1 if device == "cuda" else NUM_WORKERS_DEFAULT
    
    if device == "cuda":
        print("ℹ️  单进程GPU模式: 使用GPU加速（避免多进程CUDA问题）")
    else:
        print(f"ℹ️  多进程CPU模式: {NUM_WORKERS}个工作进程并行处理")
    
    emb_model = SentenceTransformer(EMB_MODEL, device=device)
    print(f"已加载嵌入模型: {EMB_MODEL}")
    
    try:
        nlp = spacy.load(SPACY_MODEL, disable=["ner"])
        nlp.add_pipe("sentencizer")
        print(f"已加载spaCy模型: {SPACY_MODEL}")
    except OSError:
        print(f"⚠️  警告: 未找到spaCy模型 {SPACY_MODEL}，将跳过依存句法分析")
        nlp = None
    
    concept_info, concept_text_to_id = load_concept_info()
    extractor = RelationExtractor(concept_info, concept_text_to_id, emb_model, nlp)
    
    edges_by_year = load_cooccurrence_edges(years)
    if not edges_by_year:
        print("❌ 未找到共现网络边数据")
        return
    
    processed_papers_set = load_processed_papers(STAGE3_DIR)
    if processed_papers_set:
        print(f"📋 已加载 {len(processed_papers_set)} 篇已处理论文ID")
    
    saved_relations_by_year, saved_paper_ids_by_year = load_saved_relations_by_year(STAGE3_DIR)
    if saved_relations_by_year:
        print(f"📂 已找到 {len(saved_relations_by_year)} 年的已保存关系数据")
    
    paper_ids = get_paper_ids_from_edges(edges_by_year)
    print(f"共现网络包含 {len(paper_ids)} 篇论文")
    
    relations_by_year = defaultdict(list)
    all_processed_papers = processed_papers_set.copy()
    newly_processed_papers = set()
    skipped_papers_count = 0
    
    for year in sorted(edges_by_year.keys()):
        print(f"\n=== 处理 {year} 年 ===")
        
        edges_df = edges_by_year[year]
        print(f"共现边数: {len(edges_df)}")
        
        year_paper_ids = set()
        year_dir = STAGE2_DIR / str(year)
        paper_ids_file = year_dir / f"paper_ids_{year}.parquet"
        if paper_ids_file.exists():
            paper_ids_df = pd.read_parquet(paper_ids_file)
            year_paper_ids = set(paper_ids_df['paper_id'].tolist())
        
        saved_paper_ids = saved_paper_ids_by_year.get(year, set())
        papers_to_skip, papers_to_process = detect_papers_to_update(year_paper_ids, saved_paper_ids)
        
        all_processed_papers.update(papers_to_skip)
        
        if papers_to_skip:
            print(f"  跳过 {len(papers_to_skip)} 篇已处理论文")
            skipped_papers_count += len(papers_to_skip)
        
        if papers_to_process:
            print(f"  需要处理 {len(papers_to_process)} 篇论文（新增或更新）")
        else:
            print(f"  ℹ️  该年所有论文已处理，使用已保存数据")
            if year in saved_relations_by_year:
                relations_by_year[year] = saved_relations_by_year[year].to_dict('records')
            continue
        
        paper_concepts_map = load_paper_concepts(year)
        
        year_relations = []
        paper_count = 0
        
        edges_concept_pairs = set()
        for _, edge in edges_df.iterrows():
            edges_concept_pairs.add((edge['source'], edge['target']))
        
        # 批量收集论文数据
        paper_batch = []
        papers_list = []
        
        for paper_data in load_paper_texts(papers_to_process):
            paper_id = paper_data['paper_id']
            
            if paper_id not in paper_concepts_map:
                continue
            
            paper_concepts = set(paper_concepts_map[paper_id])
            if len(paper_concepts) < 2:
                continue
            
            # 筛选相关边
            paper_edges = []
            for concept1, concept2 in combinations(paper_concepts, 2):
                pair1 = (concept1, concept2)
                pair2 = (concept2, concept1)
                if pair1 in edges_concept_pairs or pair2 in edges_concept_pairs:
                    edge_row = edges_df[
                        ((edges_df['source'] == concept1) & (edges_df['target'] == concept2)) |
                        ((edges_df['source'] == concept2) & (edges_df['target'] == concept1))
                    ]
                    if len(edge_row) > 0:
                        paper_edges.append({
                            'source': concept1,
                            'target': concept2
                        })
            
            if len(paper_edges) > 0:
                paper_edges_df = pd.DataFrame(paper_edges)
                paper_batch.append((paper_data, paper_edges_df))
                papers_list.append(paper_id)
        
        # 处理论文（单进程或多进程）
        if paper_batch:
            # 准备任务参数
            tasks = []
            for paper_data, paper_edges_df in paper_batch:
                tasks.append((paper_data, paper_edges_df))
            
            if NUM_WORKERS == 1:
                # 单进程模式：直接串行处理，避免进程池开销
                print(f"  开始单进程处理 {len(paper_batch)} 篇论文...")
                
                # 直接在主进程中使用extractor（避免重复创建模型）
                for paper_data, paper_edges_df in tqdm(tasks, desc=f"{year}年-处理论文"):
                    relations = process_paper_relations_single(paper_data, paper_edges_df, extractor)
                    year_relations.extend(relations)
                    paper_count += 1
            else:
                # 多进程模式：使用进程池并行处理
                print(f"  开始多进程处理 {len(paper_batch)} 篇论文（{NUM_WORKERS}个工作进程，批大小: {PAPER_BATCH_SIZE}）...")
                
                # 分批并行处理
                total_batches = (len(tasks) + PAPER_BATCH_SIZE - 1) // PAPER_BATCH_SIZE
                
                # 初始化工作进程（每个进程加载自己的模型）
                with mp.Pool(processes=NUM_WORKERS, 
                            initializer=init_worker,
                            initargs=(concept_info, concept_text_to_id, device)) as pool:
                    for batch_idx in tqdm(range(total_batches), desc=f"{year}年-批量处理"):
                        batch_start = batch_idx * PAPER_BATCH_SIZE
                        batch_end = min(batch_start + PAPER_BATCH_SIZE, len(tasks))
                        batch_tasks = tasks[batch_start:batch_end]
                        
                        batch_results = pool.map(process_paper_relations, batch_tasks)
                        
                        # 合并结果
                        for relations in batch_results:
                            year_relations.extend(relations)
                        
                        paper_count += len(batch_tasks)
            
            # 更新已处理论文集合
            for paper_id in papers_list:
                newly_processed_papers.add(paper_id)
                all_processed_papers.add(paper_id)
        
        if year in saved_relations_by_year:
            old_relations_df = saved_relations_by_year[year]
            if year_relations:
                merged_df = merge_relations(old_relations_df, year_relations)
                relations_by_year[year] = merged_df.to_dict('records')
                print(f"{year}年: 处理了 {paper_count} 篇新论文，抽取了 {len(year_relations)} 个新关系")
                print(f"      合并后共 {len(relations_by_year[year])} 个关系（包含已保存的）")
            else:
                relations_by_year[year] = old_relations_df.to_dict('records')
                print(f"{year}年: 使用已保存的关系数据（{len(relations_by_year[year])} 个关系）")
        elif year_relations:
            relations_by_year[year] = year_relations
            print(f"{year}年: 处理了 {paper_count} 篇论文，抽取了 {len(year_relations)} 个关系")
        else:
            relations_by_year[year] = []
            print(f"{year}年: 未找到关系数据")
    
    save_relations(relations_by_year, STAGE3_DIR)
    save_processed_papers(all_processed_papers, STAGE3_DIR)
    
    print(f"\n✅ 阶段4完成！")
    print(f"新处理论文: {len(newly_processed_papers)} 篇")
    print(f"跳过论文: {skipped_papers_count} 篇")
    print(f"累计已处理: {len(all_processed_papers)} 篇论文")
    print(f"结果保存在: {STAGE3_DIR}")

if __name__ == "__main__":
    main()

