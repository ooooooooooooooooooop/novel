from __future__ import annotations

import os
import sys

# 配置第三方库的输出控制（必须在导入任何库之前设置）
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
# 禁用datasets库的进度条（transformers内部使用）
os.environ['HF_DATASETS_DISABLE_PROGRESS_BARS'] = '1'
os.environ['TRANSFORMERS_VERBOSITY'] = 'error'  # transformers详细级别
# 禁用所有tqdm输出
os.environ['TQDM_DISABLE'] = '1'

# 智能日志级别控制：保留WARNING以便排查问题，仅抑制INFO
import logging
logging.getLogger('transformers').setLevel(logging.WARNING)
logging.getLogger('sentence_transformers').setLevel(logging.WARNING)
logging.getLogger('fastcoref').setLevel(logging.ERROR)  # fastcoref的INFO过多
logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)  # 保留连接池警告
logging.getLogger('datasets').setLevel(logging.ERROR)  # datasets的进度条日志

# 检测终端Unicode支持
def _supports_unicode():
    """检测终端是否支持Unicode box-drawing字符"""
    try:
        import sys
        if sys.platform == 'win32':
            # Windows 10+ 支持，但需要检测
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # 检查是否支持UTF-8输出
            kernel32.SetConsoleOutputCP(65001)  # UTF-8
            return True
        else:
            # Unix-like系统通常支持
            import locale
            encoding = locale.getpreferredencoding()
            return encoding.lower() in ('utf-8', 'utf8')
    except (OSError, AttributeError, ImportError):
        return False

# 检测是否在Jupyter/IPython环境
def _is_jupyter():
    """检测是否在Jupyter/IPython环境中"""
    try:
        from IPython import get_ipython
        return get_ipython() is not None
    except ImportError:
        return False

# 全局格式配置
_SUPPORTS_UNICODE = _supports_unicode() or _is_jupyter()
_IS_JUPYTER = _is_jupyter()

# 格式化字符选择
if _SUPPORTS_UNICODE:
    FMT_HLINE = '═'
    FMT_VLINE = '│'
    FMT_CROSS = '┼'
    FMT_SEP = '─'
else:
    FMT_HLINE = '='
    FMT_VLINE = '|'
    FMT_CROSS = '+'
    FMT_SEP = '-'

# 输出宽度（根据环境调整）
OUTPUT_WIDTH = 70 if not _IS_JUPYTER else 80

def _setup_cuda_path_early():
    """在导入任何模块之前设置CUDA路径环境变量"""
    if 'CUDA_PATH' in os.environ:
        return
    
    possible_paths = [
        os.environ.get('CUDA_HOME'),
        r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.0',
        r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.1',
        r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.0',
        r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8',
        r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.7',
        r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.6',
    ]
    
    for cuda_path in possible_paths:
        if cuda_path and os.path.exists(cuda_path):
            os.environ['CUDA_PATH'] = cuda_path
            os.environ['CUDA_HOME'] = cuda_path
            return
    
    if 'torch' in sys.modules:
        import torch
        if torch.cuda.is_available():
            cuda_version = torch.version.cuda
            if cuda_version:
                version_parts = cuda_version.split('.')
                if len(version_parts) >= 2:
                    major, minor = version_parts[0], version_parts[1]
                    possible_version_path = rf'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v{major}.{minor}'
                    if os.path.exists(possible_version_path):
                        os.environ['CUDA_PATH'] = possible_version_path
                        os.environ['CUDA_HOME'] = possible_version_path
                        return

_setup_cuda_path_early()

import re
import json
import time
import sqlite3
import zlib
import threading
import queue
import struct
import copy
import uuid
import importlib.util
from pathlib import Path
from collections import OrderedDict, defaultdict
from functools import lru_cache
from typing import Optional, List, Dict, Tuple, Literal
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
import torch
import faiss
import spacy

# 安全的tqdm包装：必须在导入transformers/sentence_transformers之前完成
# 以影响其内部使用的tqdm
try:
    from tqdm import tqdm as _original_tqdm
    
    # 全局禁用tqdm显示，但保留对象结构
    class _SilentTqdm(_original_tqdm):
        def __init__(self, *args, **kwargs):
            if kwargs.get('disable') is not False:
                kwargs['disable'] = True
            kwargs.setdefault('miniters', float('inf'))
            super().__init__(*args, **kwargs)
    
    # 替换tqdm模块的tqdm类（影响所有导入tqdm的库）
    import tqdm
    tqdm.tqdm = _SilentTqdm
    # 也替换auto版本
    try:
        from tqdm import auto
        auto.tqdm = _SilentTqdm
    except (ImportError, AttributeError):
        pass
    
    # 替换tqdm.auto模块（datasets库使用）
    try:
        import tqdm.auto as tqdm_auto
        tqdm_auto.tqdm = _SilentTqdm
    except (ImportError, AttributeError):
        pass
    
    # 替换sys.modules中的tqdm（防止延迟导入）
    import sys
    if 'tqdm' in sys.modules:
        sys.modules['tqdm'].tqdm = _SilentTqdm
    if 'tqdm.auto' in sys.modules:
        sys.modules['tqdm.auto'].tqdm = _SilentTqdm
    
    # 导出函数接口
    def tqdm(*args, **kwargs):
        if kwargs.get('disable') is False:
            return _original_tqdm(*args, **kwargs)
        return _SilentTqdm(*args, **kwargs)
    
except ImportError:
    # 如果没有tqdm，创建一个兼容的迭代器包装
    def tqdm(iterable=None, *args, **kwargs):
        if iterable is None:
            return iter([])
        return iter(iterable)

# 现在可以安全导入transformers相关库
from sentence_transformers import SentenceTransformer, CrossEncoder
from fastcoref import FCoref
import xxhash
import msgpack
import lmdb
from pybloom_live import BloomFilter

def _setup_cuda_path_after_torch():
    """在导入torch后再次尝试设置CUDA路径"""
    if 'CUDA_PATH' in os.environ:
        return
    
    if torch.cuda.is_available():
        cuda_version = torch.version.cuda
        if cuda_version:
            version_parts = cuda_version.split('.')
            if len(version_parts) >= 2:
                major, minor = version_parts[0], version_parts[1]
                possible_version_path = rf'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v{major}.{minor}'
                if os.path.exists(possible_version_path):
                    os.environ['CUDA_PATH'] = possible_version_path
                    os.environ['CUDA_HOME'] = possible_version_path

_setup_cuda_path_after_torch()

import warnings
warnings.filterwarnings('ignore', message='.*CUDA path could not be detected.*', category=UserWarning)
warnings.filterwarnings('ignore', message='.*Failed to auto-detect CUDA root directory.*', category=UserWarning)

from nltk.corpus import wordnet as wn
HAS_WORDNET = True                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  


INPUT_CSV = "data/raw/2026外文论文.csv"
OUTPUT_BASE_DIR = Path("output/v6_opinion")
OUTPUT_BASE_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = OUTPUT_BASE_DIR / "stage1_opinion_extraction"
OUTPUT_DIR.mkdir(exist_ok=True)
OUT_OPINIONS = str(OUTPUT_DIR / "opinions_catalog_streaming.parquet")
CHECKPOINT_DIR = OUTPUT_DIR / "checkpoints_streaming"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS_DB = str(CHECKPOINT_DIR / "paper_progress.db")
MENTIONS_DB = str(OUTPUT_DIR / "opinion_mentions.db")

CHUNK_SIZE = 50_000
PAPERS_PER_MICROBATCH = 2000                         
CHECKPOINT_EVERY_MICROBATCH = 5
CHECKPOINT_EVERY_SECONDS = 120
DB_WRITE_BATCH_SIZE = 10000

EMB_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_BATCH_SIZE = 8192
EMBED_CACHE_SIZE = 800_000
SQLITE_CACHE_PATH = str(OUTPUT_DIR / "embed_cache.sqlite")
LMDB_META_PATH = str(OUTPUT_DIR / "opinion_meta.lmdb")
RAW_EMBEDDING_PATH = str(OUTPUT_DIR / "raw_embeddings.lmdb")
SQLITE_BATCH_SIZE = 10000

N_TOP_CANDIDATES = 20
CLUSTER_THRESHOLD = 0.80
ALIAS_LIMIT = 20
FAISS_SEARCH_K = 3

ADAPTIVE_THRESHOLD_PERCENTILE = 90
ADAPTIVE_THRESHOLD_MIN = 0.75
ADAPTIVE_THRESHOLD_MAX = 0.95

SPACY_BATCH_SIZE = 1024
SPACY_N_PROCESS = 1

USE_HNSW = True
HNSW_M = 16
HNSW_EF_SEARCH = 64
HNSW_EF_CONSTRUCTION = 64

USE_HASH_DEDUP = True
HASH_SET_SIZE = 100_000

USE_BLOOM_FILTER = True
BLOOM_CAPACITY = 10_000_000
BLOOM_ERROR_RATE = 0.001

USE_LMDB_META = True if lmdb else False
LMDB_META_CACHE_SIZE = 100_000

RAW_EMBEDDING_MAP_SIZE = 100 * 1024 * 1024 * 1024

USE_VECTOR_COMPRESSION = True
COMPRESSION_METHOD = "PCA"
COMPRESSED_DIM = 256
PCA_TRAIN_SAMPLES = 100_000
ENABLE_PCA_AT_OPINIONS = 1_000_000
ENABLE_PQ_AT_OPINIONS = 5_000_000
TRAIN_PCA_IN_SAVE = False

OPINION_STOPWORDS_FILE = "config/opinion_stopwords.txt"
_OPINION_STOPWORDS = None

SUCCESS_SAMPLE_RATE = 0.05
SUCCESS_SAMPLE_MIN = 10
SUCCESS_SAMPLE_MAX = 100

OPINION_VERBS_STRONG = {
    'demonstrate', 'prove', 'show', 'find', 'argue', 'claim', 
    'suggest', 'indicate', 'reveal', 'establish', 'confirm',
    'validate', 'verify', 'support', 'justify', 'assert', 'maintain', 'contend',
    'evidence', 'manifest', 'illustrate', 'exhibit', 'display', 'present',
    'believe', 'think', 'hypothesize', 'assume', 'presume', 'speculate',
    'conclude', 'determine', 'confirm', 'validate', 'verify', 'substantiate',
    'document', 'record', 'note', 'observe', 'witness', 'detect'
}
OPINION_VERBS_MEDIUM = {
    'propose', 'introduce', 'present', 'report', 'observe', 
    'discover', 'identify', 'demonstrate', 'develop', 'create', 
    'design', 'innovate', 'pioneer', 'recommend', 'advocate',
    'optimize', 'enhance', 'refine', 'advance', 'extend', 'generalize',
    'achieve', 'obtain', 'attain', 'accomplish', 'realize', 'implement',
    'formulate', 'construct', 'build', 'establish', 'found', 'initiate',
    'lead', 'cause', 'enable', 'allow', 'prevent', 'inhibit', 'facilitate',
    'promote', 'suppress', 'induce', 'trigger', 'result', 'contribute',
    'reduce', 'increase', 'decrease', 'improve', 'worsen', 'enhance',
    'boost', 'elevate', 'lower', 'raise', 'diminish', 'amplify',
    'compare', 'contrast', 'differentiate', 'distinguish',
    'value', 'evaluate', 'assess', 'appraise', 'rate', 'rank',
    'constrain', 'constrains', 'constrained', 'provide', 'provides', 'provided',
    'predict', 'explain', 'understand', 'characterize', 'quantify', 'measure',
    'calculate', 'estimate', 'approximate', 'model', 'simulate', 'approximate',
    'characterize', 'quantify', 'measure', 'calculate', 'estimate',
    'correlate', 'associate', 'link', 'connect', 'relate', 'associate',
    'influence', 'affect', 'impact', 'modify', 'alter', 'change',
    'determine', 'define', 'specify', 'characterize', 'represent',
    'reflect', 'represent', 'signify', 'denote', 'indicate', 'imply'
}
OPINION_VERBS_WEAK = {
    'describe', 'discuss', 'analyze', 'evaluate', 'examine', 
    'investigate', 'study', 'explore', 'attempt', 'try', 'seek',
    'consider', 'review', 'assess', 'appraise', 'inspect', 'scrutinize',
    'explain', 'clarify', 'interpret', 'test', 'search',
    'examine', 'inspect', 'survey', 'monitor', 'track', 'follow',
    'document', 'record', 'note', 'observe', 'witness', 'detect',
    'measure', 'quantify', 'calculate', 'estimate', 'approximate',
    'classify', 'categorize', 'group', 'organize', 'structure',
    'compare', 'contrast', 'differentiate', 'distinguish',     'separate'
}

SYNONYM_MAP = {
    'transformer architecture': 'transformer',
    'transformer model': 'transformer',
    'the transformer': 'transformer',
    'transformer encoder': 'transformer',
    'transformer decoder': 'transformer',
    'transformer network': 'transformer',
    'attention mechanism': 'attention',
    'self-attention': 'attention',
    'multi-head attention': 'attention',
    'rnn model': 'rnn',
    'recurrent neural network': 'rnn',
    'recurrent network': 'rnn',
    'lstm model': 'lstm',
    'long short-term memory': 'lstm',
    'lstm network': 'lstm',
    'gru model': 'gru',
    'gated recurrent unit': 'gru',
    'bert model': 'bert',
    'bidirectional encoder representations from transformers': 'bert',
    'bert encoder': 'bert',
    'bert-base': 'bert',
    'bert-large': 'bert',
    'resnet model': 'resnet',
    'residual network': 'resnet',
    'resnet architecture': 'resnet',
    'convolutional neural network': 'cnn',
    'cnn model': 'cnn',
    'convnet': 'cnn',
    'convolutional network': 'cnn',
    'generative adversarial network': 'gan',
    'gan model': 'gan',
    'adversarial network': 'gan',
    'vgg model': 'vgg',
    'vgg network': 'vgg',
    'alexnet': 'alexnet',
    'googlenet': 'googlenet',
    'inception': 'inception',
    'yolo': 'yolo',
    'you only look once': 'yolo',
    'deep learning': 'deep learning',
    'deep neural network': 'deep learning',
    'dnn': 'deep learning',
    'machine learning': 'machine learning',
    'ml': 'machine learning',
    'neural network': 'neural network',
    'nn': 'neural network',
    'natural language processing': 'nlp',
    'nlp': 'nlp',
    'computer vision': 'cv',
    'cv': 'cv',
    'image classification': 'image classification',
    'object detection': 'object detection',
    'semantic segmentation': 'semantic segmentation',
    'machine translation': 'machine translation',
    'text classification': 'text classification',
    'sentiment analysis': 'sentiment analysis',
}

GENERIC_RE = [re.compile(p, re.IGNORECASE) for p in [
    r"^this (paper|study|work|research)$",
    r"^our (method|approach|algorithm)$",
    r"^(novel|new|effective|efficient) (method|approach|algorithm)$",
    r"^(results?|experiments?|conclusion)$",
    r"^(introduction|related work|future work)$",
    r"^(analysis|evaluation|comparison)$",
]]

_successful_paper_details = []
_microbatch_hash_lru = OrderedDict()
_microbatch_hash_lock = threading.Lock()

class SpanBasedExtractor:
    """基于动词span和名词短语span的原子抽取器（路径A）
    
    主路径，置信度范围：0.7-1.0
    """
    
    def __init__(self, nlp_model):
        """初始化Span-based抽取器
        
        Args:
            nlp_model: spaCy模型实例
        """
        self.nlp = nlp_model
    
    def extract(self, sentence: str, doc) -> List[MAU]:
        """从句子中提取语义原子（Span-based方法）
        
        Args:
            sentence: 输入句子文本
            doc: spaCy doc对象
            
        Returns:
            List[MAU]: 提取的MAU列表
        """
        if not doc:
            doc = self.nlp(sentence)
        
        maus = []
        
        verb_tokens = self._extract_verb_spans(doc)
        np_spans = self._extract_noun_phrase_spans(doc)
        
        if not verb_tokens:
            return maus
        
        for verb_token in verb_tokens:
            verb_lemma = verb_token.lemma_.lower()
            
            if verb_lemma in ['be', 'is', 'are', 'was', 'were', 'am', 'have', 'has', 'had']:
                continue
            
            patient = self._find_patient_for_verb(verb_token, doc, np_spans)
            agent = self._find_agent_for_verb(verb_token, doc, np_spans)
            preposition = self._find_preposition_for_verb(verb_token, patient)
            
            granularity = _determine_granularity(agent, patient)
            confidence = _calculate_confidence_base(granularity, (0.5, 0.7), (0.9, 1.0), (0.7, 0.9))
            
            atom_text_parts = []
            if agent:
                atom_text_parts.append(agent)
            atom_text_parts.append(verb_token.text)
            if preposition:
                atom_text_parts.append(preposition)
            if patient:
                atom_text_parts.append(patient)
            atom_text = " ".join(atom_text_parts)
            
            mau = MAU(
                predicate=verb_lemma,
                patient=patient,
                agent=agent,
                context=sentence[:100] if len(sentence) > 100 else sentence,
                granularity=granularity,
                confidence=confidence,
                source_path="A",
                coref_resolved=False,
                atom_text=atom_text,
                atom_type="ACTION",
                sentence_id=-1,
                original_sentence=sentence
            )
            maus.append(mau)
        
        return maus
    
    def _extract_verb_spans(self, doc) -> List:
        """提取所有动词span
        
        Returns:
            List: 动词span列表（spaCy Span对象）
        """
        verb_spans = []
        verbs = [token for token in doc if token.pos_ == "VERB"]
        
        for verb in verbs:
            if verb.dep_ == "ROOT" or verb.head.pos_ == "VERB":
                verb_spans.append(verb)
        
        return verb_spans
    
    def _extract_noun_phrase_spans(self, doc) -> List:
        """提取所有名词短语span
        
        Returns:
            List: 名词短语span列表（spaCy Span对象）
        """
        np_spans = []
        for chunk in doc.noun_chunks:
            np_spans.append(chunk)
        
        return np_spans
    
    def _find_patient_for_verb(self, verb_token, doc, np_spans) -> Optional[str]:
        """为动词查找patient（宾语）
        
        Args:
            verb_token: 动词token
            doc: spaCy doc对象
            np_spans: 名词短语span列表
            
        Returns:
            Optional[str]: patient文本，如果不存在返回None
        """
        for child in verb_token.children:
            if child.dep_ in ['dobj', 'pobj', 'attr', 'acomp']:
                for np_span in np_spans:
                    if child in np_span:
                        return np_span.text
                return child.text
        
        for prep in verb_token.children:
            if prep.dep_ == 'prep' and prep.text.lower() in ['of', 'for', 'on', 'in']:
                for pobj in prep.children:
                    if pobj.dep_ == 'pobj':
                        for np_span in np_spans:
                            if pobj in np_span:
                                return np_span.text
                        return pobj.text
        
        return None
    
    def _find_preposition_for_verb(self, verb_token, patient: Optional[str]) -> Optional[str]:
        """查找动词的介词（当patient来自介词短语时）
        
        Args:
            verb_token: 动词token
            patient: 已找到的patient文本（如果存在）
            
        Returns:
            Optional[str]: 介词文本，如果不存在返回None
        """
        if not patient:
            return None
        
        for prep in verb_token.children:
            if prep.dep_ == 'prep' and prep.text.lower() in ['of', 'for', 'on', 'in', 'at', 'to', 'with', 'by']:
                for pobj in prep.children:
                    if pobj.dep_ == 'pobj':
                        pobj_text = pobj.text
                        if patient.startswith(pobj_text) or pobj_text in patient:
                            return prep.text.lower()
        
        return None
    
    def _find_agent_for_verb(self, verb_token, doc, np_spans) -> Optional[str]:
        """为动词查找agent（主语）
        
        Args:
            verb_token: 动词token
            doc: spaCy doc对象
            np_spans: 名词短语span列表
            
        Returns:
            Optional[str]: agent文本，如果不存在返回None
        """
        for child in verb_token.children:
            if child.dep_ in ['nsubj', 'nsubjpass', 'csubj']:
                for np_span in np_spans:
                    if child in np_span:
                        return np_span.text
                return child.text
        
        if verb_token.dep_ == "nsubjpass" or any(c.dep_ == "nsubjpass" for c in verb_token.children):
            for prep in verb_token.children:
                if prep.dep_ == 'prep' and prep.text.lower() == 'by':
                    for pobj in prep.children:
                        if pobj.dep_ == 'pobj':
                            for np_span in np_spans:
                                if pobj in np_span:
                                    return np_span.text
                            return pobj.text
        
        return None
    

class RuleBasedExtractor:
    """基于关键词和模式匹配的原子抽取器（路径C）
    
    备用路径，置信度范围：0.3-0.6
    当路径A和B都失败时使用
    """
    
    def __init__(self, nlp_model=None):
        """初始化Rule-based抽取器
        
        Args:
            nlp_model: spaCy模型实例（可选，用于基本分词）
        """
        self.nlp = nlp_model
        
        self.innovation_keywords = {
            'novel', 'new', 'proposed', 'introduce', 'develop', 'design',
            'innovative', 'original', 'pioneer', 'first', 'breakthrough'
        }
        
        self.research_action_keywords = {
            'propose', 'present', 'demonstrate', 'show', 'prove', 'establish',
            'achieve', 'obtain', 'find', 'discover', 'identify', 'reveal'
        }
        
        self.patterns = [
            re.compile(r'\b(we|our|this|the|a|an)\s+(propose|present|introduce|develop|design)\s+([^.!?]+)', re.IGNORECASE),
            re.compile(r'\b(we|our|this|the|results?|experiments?)\s+(show|demonstrate|prove|establish|reveal)\s+(?:that\s+)?([^.!?]+)', re.IGNORECASE),
            re.compile(r'\b([A-Z][^.!?]+?)\s+(?:is|are|was|were)\s+(?:proposed|presented|introduced|developed|designed)', re.IGNORECASE),
            re.compile(r'\b(novel|new|innovative|original)\s+([^.!?]+?)(?:\s+for|\s+to|\s+in|\.|$)', re.IGNORECASE),
            re.compile(r'\b(we|our|this|the|method|approach|system)\s+(?:achieve|obtain|attain|accomplish)\s+([^.!?]+)', re.IGNORECASE),
        ]
    
    def extract(self, sentence: str, doc=None, sentence_id: int = -1) -> List[MAU]:
        """从句子中提取语义原子（Rule-based方法）
        
        Args:
            sentence: 输入句子文本
            doc: spaCy doc对象（可选）
            sentence_id: 句子ID
            
        Returns:
            List[MAU]: 提取的MAU列表
        """
        if not sentence or len(sentence.strip()) < 10:
            return []
        
        maus = []
        sentence_lower = sentence.lower()
        
        has_innovation_keyword = any(kw in sentence_lower for kw in self.innovation_keywords)
        has_research_action = any(kw in sentence_lower for kw in self.research_action_keywords)
        
        if not (has_innovation_keyword or has_research_action):
            return []
        
        for pattern in self.patterns:
            matches = pattern.finditer(sentence)
            for match in matches:
                groups = match.groups()
                if len(groups) >= 2:
                    agent = None
                    predicate = None
                    patient = None
                    
                    if len(groups) == 2:
                        predicate = groups[0].lower()
                        patient = groups[1].strip()
                    elif len(groups) == 3:
                        agent = groups[0].strip()
                        predicate = groups[1].lower()
                        patient = groups[2].strip()
                    
                    if predicate and predicate in ['novel', 'new', 'innovative', 'original']:
                        predicate = "introduce"
                    
                    if not predicate:
                        continue
                    
                    if patient and len(patient) > 200:
                        patient = patient[:200]
                    
                    granularity = _determine_granularity(agent, patient)
                    base_confidence = _calculate_confidence_base(granularity, (0.3, 0.3), (0.5, 0.5), (0.4, 0.4))
                    if has_innovation_keyword:
                        base_confidence += 0.05
                    if has_research_action:
                        base_confidence += 0.05
                    confidence = min(0.6, base_confidence)
                    
                    atom_text_parts = []
                    if agent:
                        atom_text_parts.append(agent)
                    atom_text_parts.append(predicate)
                    if patient:
                        atom_text_parts.append(patient)
                    atom_text = " ".join(atom_text_parts)
                    
                    mau = MAU(
                        predicate=predicate,
                        patient=patient,
                        agent=agent,
                        context=sentence[:100] if len(sentence) > 100 else sentence,
                        granularity=granularity,
                        confidence=confidence,
                        source_path="C",
                        coref_resolved=False,
                        atom_text=atom_text,
                        atom_type="ACTION",
                        sentence_id=sentence_id,
                        original_sentence=sentence
                    )
                    maus.append(mau)
                    
                    if len(maus) >= 2:
                        break
            
            if maus:
                break
        
        return maus
    

class DependencyBasedExtractor:
    """基于依存分析的原子抽取器（路径B）
    
    辅助路径，置信度范围：0.5-0.8
    """
    
    def __init__(self, nlp_model, coref_model=None):
        """初始化Dependency-based抽取器
        
        Args:
            nlp_model: spaCy模型实例
            coref_model: 共指消解模型（可选）
        """
        self.nlp = nlp_model
        self.coref_model = coref_model
        
        self.atom_stats = {
            "total_atoms": 0,
            "valid_atoms": 0,
            "invalid_atoms": 0,
            "atoms_with_inherited_subject": 0,
            "nominalization_atoms": 0,
            "action_only_atoms": 0
        }
    
    def extract(self, sentence: str, doc, sentence_id: int = -1) -> List[MAU]:
        """从句子中提取语义原子（Dependency-based方法）
        
        Args:
            sentence: 输入句子文本
            doc: spaCy doc对象
            sentence_id: 句子ID
            
        Returns:
            List[MAU]: 提取的MAU列表
        """
        if not doc:
            doc = self.nlp(sentence)
        
        maus = []
        
        all_verbs = [token for token in doc if token.pos_ == "VERB"]
        root_verbs = [token for token in doc if token.pos_ == "VERB" and token.dep_ == "ROOT"]
        
        if not root_verbs and not all_verbs:
            return maus
        
        atom_id = 0
        processed_tokens = set()
        
        nominalization_nouns = [token for token in doc 
                               if token.pos_ == "NOUN" and self._is_nominalized_verb(token)]
        
        for noun_token in nominalization_nouns:
            if noun_token.i in processed_tokens:
                continue
            
            nom_atom = self._extract_atom_from_nominalization(noun_token, doc)
            if nom_atom:
                is_valid, reason = self._validate_atom_completeness(nom_atom)
                if is_valid:
                    mau = self._atom_dict_to_mau(nom_atom, sentence, sentence_id, atom_id)
                    maus.append(mau)
                    atom_id += 1
                    processed_tokens.add(noun_token.i)
                    self.atom_stats["nominalization_atoms"] += 1
                    self.atom_stats["total_atoms"] += 1
                    self.atom_stats["valid_atoms"] += 1
        
        verbs_to_process = root_verbs if root_verbs else all_verbs
        
        for verb in verbs_to_process:
            if verb.i in processed_tokens:
                continue
            
                verb_lemma = verb.lemma_.lower()
                root_verb_id = self._get_root_verb_id(verb, doc)
                
                if verb_lemma in FRAMEWORK_VERBS:
                    matrix_subject = None
                    for child in verb.children:
                        if child.dep_ in ['nsubj', 'nsubjpass']:
                            matrix_subject = child
                            break
                    
                    clause_verb = None
                    for child in verb.children:
                        if child.dep_ in ['ccomp', 'xcomp']:
                            for token in child.subtree:
                                if token.pos_ == "VERB" and token != child:
                                    clause_verb = token
                                    break
                            if clause_verb:
                                break
                    
                    if not clause_verb:
                        for child in verb.children:
                            if child.dep_ == 'dobj':
                                for token in child.subtree:
                                    if token.pos_ == "VERB":
                                        clause_verb = token
                                        break
                                if clause_verb:
                                    break
                    
                    if clause_verb and clause_verb.i not in processed_tokens:
                        atom_dict = self._extract_atom_from_verb(clause_verb, matrix_subject, doc, root_verb_id)
                        if atom_dict:
                            is_valid, reason = self._validate_atom_completeness(atom_dict)
                            if is_valid:
                                mau = self._atom_dict_to_mau(atom_dict, sentence, sentence_id, atom_id)
                                maus.append(mau)
                                atom_id += 1
                                processed_tokens.add(clause_verb.i)
                                processed_tokens.add(verb.i)
                                self.atom_stats["total_atoms"] += 1
                                self.atom_stats["valid_atoms"] += 1
                    continue
            
            root_verb_id = self._get_root_verb_id(verb, doc)
            atom_dict = self._extract_atom_from_verb(verb, None, doc, root_verb_id)
            if atom_dict:
                is_valid, reason = self._validate_atom_completeness(atom_dict)
                if is_valid:
                    mau = self._atom_dict_to_mau(atom_dict, sentence, sentence_id, atom_id)
                    maus.append(mau)
                    atom_id += 1
                    processed_tokens.add(verb.i)
                    self.atom_stats["total_atoms"] += 1
                    self.atom_stats["valid_atoms"] += 1
                else:
                    self.atom_stats["invalid_atoms"] += 1
        
        return maus
    
    def _atom_dict_to_mau(self, atom_dict: Dict, sentence: str, sentence_id: int, atom_id: int) -> MAU:
        """将atom_dict转换为MAU格式
        
        Args:
            atom_dict: 原子字典
            sentence: 原始句子
            sentence_id: 句子ID
            atom_id: 原子ID
            
        Returns:
            MAU: MAU对象
        """
        predicate = atom_dict.get("verb_lemma", "")
        if not predicate:
            atom_text = atom_dict.get("atom_text", "")
            if atom_text:
                words = atom_text.split()
                predicate = words[0] if words else ""
        
        has_subject = atom_dict.get("has_subject", False)
        has_object = atom_dict.get("has_object", False)
        agent = atom_dict.get("agent")
        patient = atom_dict.get("patient")
        granularity = _determine_granularity(agent, patient)
        confidence = _calculate_confidence_base(granularity, (0.5, 0.6), (0.7, 0.8), (0.6, 0.7))
        
        return MAU(
            predicate=predicate,
            patient=atom_dict.get("patient"),
            agent=atom_dict.get("agent"),
            context=sentence[:100] if len(sentence) > 100 else sentence,
            granularity=granularity,
            confidence=confidence,
            source_path="B",
            coref_resolved=False,
            atom_text=atom_dict.get("atom_text", ""),
            atom_type=atom_dict.get("atom_type"),
            sentence_id=sentence_id,
            original_sentence=sentence
        )
    
    def _get_root_verb_id(self, verb, sent_doc):
        """获取动词所属的根动词ID"""
        current = verb
        root_verb = None
        max_iterations = 20
        iteration = 0
        
        while current.head != current and iteration < max_iterations:
            if current.head.pos_ == "VERB" and current.head.dep_ == "ROOT":
                root_verb = current.head
                break
            current = current.head
            iteration += 1
        
        if root_verb is None:
            if sent_doc and len(sent_doc) > 0:
                if hasattr(sent_doc[0], 'sent') and sent_doc[0].sent.root:
                    root_verb = sent_doc[0].sent.root
        
        if root_verb is None:
            root_verb = verb
        
        return root_verb.i if root_verb else verb.i
    
    def _extract_noun_phrase(self, token):
        """提取完整的名词短语"""
        phrase_tokens = list(token.subtree)
        phrase_tokens.sort(key=lambda t: t.i)
        return " ".join([t.text for t in phrase_tokens])
    
    def _find_subject_for_verb(self, verb, sent_doc, root_verb_id=None, visited_verbs=None):
        """查找动词的主语"""
        if visited_verbs is None:
            visited_verbs = set()
        
        if verb.i in visited_verbs:
            return None, None, None, None
        
        visited_verbs.add(verb.i)
        
        if root_verb_id is None:
            root_verb_id = self._get_root_verb_id(verb, sent_doc)
        
        children_by_dep = {}
        for child in verb.children:
            if child.dep_ not in children_by_dep:
                children_by_dep[child.dep_] = []
            children_by_dep[child.dep_].append(child)
        
        if 'nsubj' in children_by_dep:
            return children_by_dep['nsubj'][0], "SELF", None, None
        elif 'nsubjpass' in children_by_dep:
            subject = children_by_dep['nsubjpass'][0]
            return subject, "SELF", None, None
        
        return None, None, None, None
    
    def _extract_atom_from_verb(self, verb, matrix_subject=None, sent_doc=None, root_verb_id=None):
        """从动词提取原子"""
        if not sent_doc:
            return None
        
        if root_verb_id is None:
            root_verb_id = self._get_root_verb_id(verb, sent_doc)
        
        subject, subj_source, logical_subject, logical_subject_type = \
            self._find_subject_for_verb(verb, sent_doc, root_verb_id)
        
        if not subject and matrix_subject:
            subject = matrix_subject
            subj_source = f"INHERITED({root_verb_id})"
        
        children_by_dep = {}
        for child in verb.children:
            if child.dep_ not in children_by_dep:
                children_by_dep[child.dep_] = []
            children_by_dep[child.dep_].append(child)
        
        obj = None
        preposition = None
        if 'dobj' in children_by_dep:
            obj = children_by_dep['dobj'][0]
        elif 'prep' in children_by_dep:
            for prep in children_by_dep['prep']:
                if prep.text.lower() in ['of', 'for', 'on', 'in', 'at', 'to', 'with', 'by']:
                    for pobj in prep.children:
                        if pobj.dep_ == 'pobj':
                            obj = pobj
                            preposition = prep.text.lower()
                            break
                    if obj:
                        break
        elif 'pobj' in children_by_dep:
            obj = children_by_dep['pobj'][0]
            if obj.head.dep_ == 'prep':
                preposition = obj.head.text.lower()
        
        atom_parts = []
        if subject:
            subject_text = self._extract_noun_phrase(subject)
            atom_parts.append(subject_text)
        atom_parts.append(verb.text)
        if preposition:
            atom_parts.append(preposition)
        if obj:
            obj_text = self._extract_noun_phrase(obj)
            atom_parts.append(obj_text)
        
        atom_text = " ".join(atom_parts)
        if not atom_text.strip():
            atom_text = verb.text
        
        verb_lemma = verb.lemma_.lower()
        atom_type = "ACTION"
        
        return {
            "atom_text": atom_text,
            "atom_type": atom_type,
            "verb_lemma": verb_lemma,
            "relation_type": None,
            "subj_source": subj_source if subj_source else "NONE",
            "has_subject": subject is not None,
            "has_object": obj is not None,
            "agent": self._extract_noun_phrase(subject) if subject else None,
            "patient": self._extract_noun_phrase(obj) if obj else None
        }
    
    def _is_nominalized_verb(self, noun_token):
        """判断是否为名词化动词"""
        if noun_token.pos_ != "NOUN":
            return False
        
        noun_lemma = noun_token.lemma_.lower()
        
        if noun_lemma in NOMINALIZATION_NOUNS:
            return True
        
        nominalization_suffixes = [
            "tion", "sion", "ment", "ance", "ence",
            "ability", "ibility", "ness"
        ]
        
        for suffix in nominalization_suffixes:
            if noun_lemma.endswith(suffix) and len(noun_lemma) > len(suffix) + 2:
                if noun_lemma not in ["thing", "something", "nothing", "anything", "everything"]:
                    return True
        
        return False
    
    def _extract_atom_from_nominalization(self, noun_token, sent_doc):
        """从名词化动词提取原子"""
        if not self._is_nominalized_verb(noun_token):
            return None
        
        noun_lemma = noun_token.lemma_.lower()
        
        children_by_dep = {}
        for child in noun_token.children:
            if child.dep_ not in children_by_dep:
                children_by_dep[child.dep_] = []
            children_by_dep[child.dep_].append(child)
        
        agent = None
        if 'prep' in children_by_dep:
            for prep in children_by_dep['prep']:
                if prep.text.lower() == 'by':
                    for pobj in prep.children:
                        if pobj.dep_ == 'pobj':
                            agent = pobj
                            break
                    if agent:
                        break
        
        patient = None
        if 'prep' in children_by_dep:
            for prep in children_by_dep['prep']:
                if prep.text.lower() == 'of':
                    for pobj in prep.children:
                        if pobj.dep_ == 'pobj':
                            patient = pobj
                            break
                    if patient:
                        break
        
        atom_parts = []
        if agent:
            agent_text = self._extract_noun_phrase(agent)
            atom_parts.append(agent_text)
        atom_parts.append(noun_lemma)
        if patient:
            patient_text = self._extract_noun_phrase(patient)
            atom_parts.append(patient_text)
        
        atom_text = " ".join(atom_parts)
        if not atom_text.strip():
            return None
        
        return {
            "atom_text": atom_text,
            "atom_type": "ACTION",
            "verb_lemma": noun_lemma,
            "relation_type": None,
            "subj_source": "NOMINALIZATION",
            "has_subject": agent is not None,
            "has_object": patient is not None,
            "is_nominalization": True,
            "agent": self._extract_noun_phrase(agent) if agent else None,
            "patient": self._extract_noun_phrase(patient) if patient else None
        }
    
    def _validate_atom_completeness(self, atom):
        """验证原子完整性"""
        if not atom:
            return False, "empty_atom"
        
        atom_text = atom.get("atom_text", "").strip()
        if not atom_text:
            return False, "no_text"
        
        has_action = atom.get("verb_lemma") is not None or atom.get("is_nominalization", False)
        if not has_action:
            return False, "no_action"
        
        has_subject = atom.get("has_subject", False)
        has_object = atom.get("has_object", False)
        has_agent = atom.get("agent") is not None
        has_patient = atom.get("patient") is not None
        
        has_role = has_subject or has_object or has_agent or has_patient
        
        if not has_role:
            atom["is_weak"] = True
            self.atom_stats["action_only_atoms"] += 1
            return True, "weak_atom"
        
        return True, "valid"

def calculate_string_similarity(phrase1: str, phrase2: str) -> float:
    """计算字符串相似度（Jaccard相似度）"""
    words1 = set(phrase1.lower().split())
    words2 = set(phrase2.lower().split())
    
    if not words1 or not words2:
        return 0.0
    
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    return intersection / union

def calculate_embedding_similarity(phrase1: str, phrase2: str, emb_model) -> float:
    """计算embedding相似度（余弦相似度）"""
    if not emb_model:
        return 0.0
    emb1 = emb_model.encode(phrase1, convert_to_numpy=True, normalize_embeddings=True)
    emb2 = emb_model.encode(phrase2, convert_to_numpy=True, normalize_embeddings=True)
    return float(np.dot(emb1, emb2))

def calculate_phrase_similarity(phrase1: str, phrase2: str, emb_model=None,
                                string_weight: float = 0.6, emb_weight: float = 0.4) -> float:
    """计算综合短语相似度"""
    if phrase1.lower() == phrase2.lower():
        return 1.0
    
    string_sim = calculate_string_similarity(phrase1, phrase2)
    
    if emb_model:
        emb_sim = calculate_embedding_similarity(phrase1, phrase2, emb_model)
        return string_weight * string_sim + emb_weight * emb_sim
    else:
        return string_sim

def calculate_similarity(text1: str, text2: str, emb_model) -> float:
    """计算相似度（归一化到0-1范围）"""
    if not emb_model or not text1 or not text2:
        return 0.0
    
    emb1 = emb_model.encode(text1, convert_to_numpy=True, normalize_embeddings=True)
    emb2 = emb_model.encode(text2, convert_to_numpy=True, normalize_embeddings=True)
    cosine_sim = float(np.dot(emb1, emb2))
    return max(0.0, (cosine_sim + 1) / 2)

class PredicateNormalizer:
    """Predicate抽象化模块
    
    功能：
    - 将语义等价的predicate归一化为canonical形式
    - 支持predicate聚类（基于embedding相似度）
    - 解决predicate字符串不稳定问题
    """
    
    def __init__(self, emb_model=None):
        """初始化Predicate归一化器
        
        Args:
            emb_model: 嵌入模型（用于计算语义相似度）
        """
        self.emb_model = emb_model
        
        # Predicate语义等价映射表（手动维护的核心映射）
        self.semantic_equivalents = {
            # 依赖/基于类
            'rely on': 'RELY',
            'depend on': 'RELY',
            'is based on': 'RELY',
            'based on': 'RELY',
            'depend upon': 'RELY',
            
            # 导致/引起类
            'lead to': 'CAUSE',
            'result in': 'CAUSE',
            'cause': 'CAUSE',
            'bring about': 'CAUSE',
            'give rise to': 'CAUSE',
            
            # 改善/提高类
            'improve': 'ENHANCE',
            'enhance': 'ENHANCE',
            'increase': 'ENHANCE',
            'boost': 'ENHANCE',
            'strengthen': 'ENHANCE',
            
            # 减少/降低类
            'reduce': 'REDUCE',
            'decrease': 'REDUCE',
            'lower': 'REDUCE',
            'diminish': 'REDUCE',
            'minimize': 'REDUCE',
            
            'show': 'DEMONSTRATE',
            'demonstrate': 'DEMONSTRATE',
            'indicate': 'DEMONSTRATE',
            'reveal': 'DEMONSTRATE',
            'suggest': 'DEMONSTRATE',
            
            # 整合/结合类
            'integrate': 'INTEGRATE',
            'combine': 'INTEGRATE',
            'merge': 'INTEGRATE',
            'incorporate': 'INTEGRATE',
        }
        
        # 反向映射：canonical -> 所有变体
        self.canonical_to_variants = defaultdict(list)
        for variant, canonical in self.semantic_equivalents.items():
            self.canonical_to_variants[canonical].append(variant)
        
        # 动态聚类缓存
        self.predicate_clusters: Dict[str, str] = {}  # predicate -> cluster_id
        self.cluster_representatives: Dict[str, str] = {}  # cluster_id -> canonical_predicate
    
    def normalize(self, predicate: str) -> str:
        """归一化predicate到canonical形式
        
        Args:
            predicate: 原始predicate文本
            
        Returns:
            str: canonical predicate（如果无法归一化，返回原始predicate的小写形式）
        """
        if not predicate:
            return ""
        
        predicate_lower = predicate.lower().strip()
        
        # 1. 直接查找语义等价表
        if predicate_lower in self.semantic_equivalents:
            return self.semantic_equivalents[predicate_lower]
        
        if predicate_lower in self.predicate_clusters:
            cluster_id = self.predicate_clusters[predicate_lower]
            if cluster_id in self.cluster_representatives:
                return self.cluster_representatives[cluster_id]
            else:
                del self.predicate_clusters[predicate_lower]
                return predicate_lower
        
        return predicate_lower
    
    def cluster_predicates(self, predicates: List[str], similarity_threshold: float = 0.82, clear_cache: bool = True) -> Dict[str, str]:
        """对predicate列表进行聚类（保守策略，避免误合并）
        
        Args:
            predicates: predicate列表
            similarity_threshold: 相似度阈值（提高至0.82，更保守）
            clear_cache: 是否清理之前的聚类缓存（默认True，避免跨文档状态污染）
            
        Returns:
            Dict[str, str]: predicate -> canonical_predicate映射
        """
        if not predicates or not self.emb_model:
            return {}
        
        if clear_cache:
            self.predicate_clusters.clear()
            self.cluster_representatives.clear()
        
        # 去重
        unique_predicates = list(set(p.lower().strip() for p in predicates if p))
        if len(unique_predicates) <= 1:
            return {p: self.normalize(p) for p in unique_predicates}
        
        predicate_embs = self.emb_model.encode(
            unique_predicates,
            convert_to_numpy=True,
            normalize_embeddings=True
        )
        
        clusters: Dict[int, List[int]] = defaultdict(list)
        cluster_representatives: Dict[int, str] = {}
        processed = set()
        
        def _string_similarity(s1: str, s2: str) -> float:
            """计算字符串相似度（Jaccard）"""
            words1 = set(s1.split())
            words2 = set(s2.split())
            if not words1 or not words2:
                return 0.0
            intersection = len(words1 & words2)
            union = len(words1 | words2)
            return intersection / union
        
        for i, pred1 in enumerate(unique_predicates):
            if i in processed:
                continue
            
            # 先尝试语义等价表归一化
            canonical = self.normalize(pred1)
            if canonical != pred1 and canonical in self.canonical_to_variants:
                cluster_id = len(clusters)
                clusters[cluster_id].append(i)
                cluster_representatives[cluster_id] = canonical
                processed.add(i)
                continue
            
            # 新建聚类
            cluster_id = len(clusters)
            clusters[cluster_id].append(i)
            cluster_representatives[cluster_id] = pred1
            processed.add(i)
            
            for j, pred2 in enumerate(unique_predicates[i+1:], start=i+1):
                if j in processed:
                    continue
                
                emb_similarity = float(np.dot(predicate_embs[i], predicate_embs[j]))
                str_similarity = _string_similarity(pred1, pred2)
                max_len = max(len(pred1), len(pred2))
                len_ratio = min(len(pred1), len(pred2)) / max_len
                
                # 保守合并条件：embedding相似度高 AND (字符串相似度高 OR 长度相近)
                if emb_similarity >= similarity_threshold:
                    if str_similarity >= 0.5 or len_ratio >= 0.6:
                        clusters[cluster_id].append(j)
                        processed.add(j)
                        
                        if len(pred2) < len(cluster_representatives[cluster_id]):
                            cluster_representatives[cluster_id] = pred2
        
        # 构建映射
        result = {}
        for cluster_id, indices in clusters.items():
            canonical = cluster_representatives[cluster_id]
            for idx in indices:
                pred = unique_predicates[idx]
                result[pred] = canonical
                self.predicate_clusters[pred] = str(cluster_id)
                self.cluster_representatives[str(cluster_id)] = canonical
        
        return result


class SimpleAggregationLayer:
    """简化汇聚层：快速索引 + 基础MAU对齐
    
    功能：
    - 快速索引（predicate/patient/agent）
    - 基于predicate聚类的MAU对齐（而非字符串匹配）
    """
    
    def __init__(self, emb_model=None, weight_model=None):
        """初始化汇聚层
        
        Args:
            emb_model: 嵌入模型（用于计算相似度）
            weight_model: 可学习权重模型（可选，阶段2.3）
        """
        self.emb_model = emb_model
        self.weight_model = weight_model
        self.predicate_normalizer = PredicateNormalizer(emb_model=emb_model)
        self.predicate_index: Dict[str, List[int]] = {}
        self.patient_index: Dict[str, List[int]] = {}
        self.agent_index: Dict[str, List[int]] = {}
    
    def align_maus(self, maus: List[MAU], path_weights: Optional[Dict[str, float]] = None, 
                   enable_cross_predicate: bool = True, predicate_sim_threshold: float = 0.82) -> List[MAU]:
        """对齐MAU列表（基于predicate聚类 + 跨predicate语义桥接）
        
        对齐流程：
        1. Predicate抽象化：归一化所有predicate到canonical形式
        2. Predicate聚类：对归一化后的predicate进行语义聚类
        3. 跨predicate语义桥接（可选）：如果enable_cross_predicate=True，允许语义相似的predicate合并
        4. 基于聚类对齐：相同聚类内的MAU进行合并
        5. 同predicate下合并patient：计算patient相似度，相似度>0.75合并
        6. 粒度标注：无法补全的标注粒度标签
        7. 使用路径权重进行加权合并（如果提供，阶段2.3）
        
        Args:
            maus: 输入MAU列表
            path_weights: 路径权重字典（可选，阶段2.3）
            enable_cross_predicate: 是否启用跨predicate语义对齐（默认True）
            predicate_sim_threshold: predicate语义相似度阈值（默认0.82，高于phrase的0.75）
            
        Returns:
            List[MAU]: 对齐后的MAU列表
        """
        if not maus:
            return []
        
        self.predicate_index.clear()
        self.patient_index.clear()
        self.agent_index.clear()
        
        predicates = [mau.predicate for mau in maus if mau.predicate]
        self.predicate_normalizer.cluster_predicates(predicates, similarity_threshold=predicate_sim_threshold)
        
        empty_predicate_counter = 0
        for mau in maus:
            normalized = self.predicate_normalizer.normalize(mau.predicate)
            if not normalized:
                normalized = f"__empty_predicate_{empty_predicate_counter}__"
                empty_predicate_counter += 1
            mau._normalized_predicate = normalized  # 临时属性
        
        self._build_indexes_with_normalization(maus)
        
        # 跨predicate语义桥接：构建predicate语义相似度映射
        predicate_semantic_clusters = {}
        if enable_cross_predicate and self.emb_model:
            predicate_semantic_clusters = self._build_predicate_semantic_clusters(maus, predicate_sim_threshold)
        
        aligned_maus = []
        processed_indices = set()
        
        for i, mau in enumerate(maus):
            if i in processed_indices:
                continue
            
            normalized_pred = mau._normalized_predicate
            # 获取语义等价的predicate组（包括跨predicate桥接）
            semantic_group = self._get_semantic_predicate_group(
                normalized_pred, predicate_semantic_clusters, self.predicate_index
            )
            
            # 收集该语义组内的所有MAU索引
            predicate_group_indices = []
            for pred in semantic_group:
                predicate_group_indices.extend(self.predicate_index.get(pred, []))
            
            if len(predicate_group_indices) <= 1:
                aligned_maus.append(mau)
                processed_indices.add(i)
                continue
            
            same_predicate_indices = [idx for idx in predicate_group_indices if idx not in processed_indices]
            same_predicate_maus = [maus[idx] for idx in same_predicate_indices]
            
            if len(same_predicate_maus) == 1:
                aligned_maus.append(mau)
            else:
                merged_mau = self._merge_same_predicate_maus(same_predicate_maus, path_weights)
                aligned_maus.append(merged_mau)
            
            for idx in same_predicate_indices:
                processed_indices.add(idx)
        
        for mau in maus:
            if hasattr(mau, '_normalized_predicate'):
                delattr(mau, '_normalized_predicate')
        
        return aligned_maus
    
    def _build_predicate_semantic_clusters(self, maus: List[MAU], threshold: float = 0.82) -> Dict[str, List[str]]:
        """构建predicate语义相似度聚类（轻量桥接层）
        
        只允许语义高度相似的predicate进行跨predicate合并。
        复杂度：O(n²)，但n（predicate数量）通常只有几十到一百多个，不会爆炸。
        
        Args:
            maus: MAU列表
            threshold: 语义相似度阈值（默认0.82，高于phrase的0.75）
            
        Returns:
            Dict[str, List[str]]: normalized_predicate -> [语义相似的predicate列表]
        """
        if not self.emb_model:
            return {}
        
        # 收集所有唯一的normalized predicate
        unique_normalized_preds = set()
        for mau in maus:
            if hasattr(mau, '_normalized_predicate') and mau._normalized_predicate:
                unique_normalized_preds.add(mau._normalized_predicate)
        
        unique_normalized_preds = list(unique_normalized_preds)
        if len(unique_normalized_preds) <= 1:
            return {}
        
        # 生成predicate语义向量
        predicate_embs = self.emb_model.encode(
            unique_normalized_preds,
            convert_to_numpy=True,
            normalize_embeddings=True
        )
        
        # 构建语义相似度聚类（增强日志）
        similarity_matrix = {}
        clusters: Dict[int, List[int]] = defaultdict(list)
        processed = set()
        cross_predicate_merges = []  # 记录跨predicate合并
        
        for i, pred1 in enumerate(unique_normalized_preds):
            if i in processed:
                continue
            
            cluster_id = len(clusters)
            clusters[cluster_id].append(i)
            processed.add(i)
            
            for j, pred2 in enumerate(unique_normalized_preds[i+1:], start=i+1):
                if j in processed:
                    continue
                
                # 计算语义相似度（cosine）
                emb_sim = float(np.dot(predicate_embs[i], predicate_embs[j]))
                
                # 记录相似度矩阵
                similarity_matrix[(pred1, pred2)] = emb_sim
                
                # 只合并语义高度相似的predicate（阈值0.82）
                if emb_sim >= threshold:
                    # 步骤6：上下文一致性检查（仅当启用跨predicate对齐时）
                    context_consistent = True
                    # 获取使用这两个predicate的MAU
                    pred1_maus = [mau for mau in maus if hasattr(mau, '_normalized_predicate') and mau._normalized_predicate == pred1]
                    pred2_maus = [mau for mau in maus if hasattr(mau, '_normalized_predicate') and mau._normalized_predicate == pred2]
                    
                    if pred1_maus and pred2_maus and self.emb_model:
                        # 计算上下文相似度（patient + agent的embedding）
                        pred1_contexts = []
                        pred2_contexts = []
                        
                        for mau in pred1_maus:
                            context_text = f"{mau.patient or ''} {mau.agent or ''}".strip()
                            if context_text:
                                pred1_contexts.append(context_text)
                        
                        for mau in pred2_maus:
                            context_text = f"{mau.patient or ''} {mau.agent or ''}".strip()
                            if context_text:
                                pred2_contexts.append(context_text)
                        
                        # 如果两个predicate都有上下文，检查上下文相似度
                        if pred1_contexts and pred2_contexts:
                            # 计算平均上下文embedding
                            pred1_ctx_embs = self.emb_model.encode(pred1_contexts[:5], convert_to_numpy=True, normalize_embeddings=True)  # 限制数量
                            pred2_ctx_embs = self.emb_model.encode(pred2_contexts[:5], convert_to_numpy=True, normalize_embeddings=True)
                            
                            pred1_ctx_mean = pred1_ctx_embs.mean(axis=0)
                            pred2_ctx_mean = pred2_ctx_embs.mean(axis=0)
                            pred1_ctx_mean = pred1_ctx_mean / (np.linalg.norm(pred1_ctx_mean) + 1e-12)
                            pred2_ctx_mean = pred2_ctx_mean / (np.linalg.norm(pred2_ctx_mean) + 1e-12)
                            
                            context_sim = float(np.dot(pred1_ctx_mean, pred2_ctx_mean))
                            # 上下文相似度阈值：0.7
                            context_consistent = context_sim >= 0.7
                    
                    # 仅当语义相似且上下文一致时才合并
                    if context_consistent:
                        clusters[cluster_id].append(j)
                        processed.add(j)
                        cross_predicate_merges.append((pred1, pred2, emb_sim))
        
        # 构建映射：每个predicate -> 其语义cluster中的所有predicate
        result = {}
        for cluster_id, indices in clusters.items():
            cluster_preds = [unique_normalized_preds[idx] for idx in indices]
            for pred in cluster_preds:
                result[pred] = cluster_preds
        
        # 输出跨predicate对齐诊断信息
        if len(unique_normalized_preds) > 1:
            print(f"\n[跨predicate对齐诊断]")
            print(f"  - Predicate数量: {len(unique_normalized_preds)}")
            print(f"  - 相似度阈值: {threshold:.2f}")
            
            # 输出相似度矩阵（只显示前10个pair，避免输出过多）
            if similarity_matrix:
                sorted_sims = sorted(similarity_matrix.items(), key=lambda x: x[1], reverse=True)
                print(f"  - 相似度矩阵（前10个最高）:")
                for (p1, p2), sim in sorted_sims[:10]:
                    status = "✓合并" if sim >= threshold else "✗未合并"
                    print(f"    {status}: '{p1}' vs '{p2}' = {sim:.3f}")
            
            # 统计跨predicate合并
            if cross_predicate_merges:
                print(f"  - 跨predicate合并: {len(cross_predicate_merges)} 个pair")
                for p1, p2, sim in cross_predicate_merges:
                    print(f"    ✓ '{p1}' + '{p2}' (相似度: {sim:.3f})")
            else:
                max_sim = max(similarity_matrix.values()) if similarity_matrix else 0.0
                print(f"  - 跨predicate合并: 0 个pair")
                print(f"  - 最高相似度: {max_sim:.3f} (阈值: {threshold:.2f})")
                if max_sim < threshold:
                    print(f"    ⚠️  建议: 如果最高相似度接近阈值，可考虑降低阈值至 {max(0.75, max_sim * 0.95):.2f}")
                
                # 显示所有未合并的pair（阈值筛选输出，避免过多）
                unmerged_pairs = [(p1, p2, sim) for (p1, p2), sim in similarity_matrix.items() if sim < threshold]
                sorted_unmerged = sorted(unmerged_pairs, key=lambda x: x[2], reverse=True)
                # 只显示相似度最高的20对，避免输出过多
                display_count = min(20, len(sorted_unmerged))
                if display_count > 0:
                    print(f"  - 未合并pair列表（共{len(unmerged_pairs)}个，显示相似度最高的{display_count}对）:")
                    for p1, p2, sim in sorted_unmerged[:display_count]:
                        print(f"    '{p1}' vs '{p2}' = {sim:.3f} (阈值: {threshold:.2f}, 差距: {threshold - sim:.3f})")
            
            # 统计cluster信息和跨predicate cluster原子数量占比（增强版）
            multi_pred_clusters = [c for c in clusters.values() if len(c) > 1]
            total_clusters = len(clusters)
            cross_predicate_clusters = []
            
            if multi_pred_clusters:
                print(f"  - 多predicate cluster数: {len(multi_pred_clusters)}")
                total_atoms_in_cross_clusters = 0
                for cluster_indices in multi_pred_clusters:
                    cluster_preds = [unique_normalized_preds[idx] for idx in cluster_indices]
                    # 判断是否跨predicate（包含多个不同的predicate）
                    is_cross_predicate = len(set(cluster_preds)) > 1
                    if is_cross_predicate:
                        total_atoms_in_cross_clusters += len(cluster_indices)
                        cross_predicate_clusters.append(cluster_indices)
                    print(f"    Cluster: {cluster_preds} (原子数: {len(cluster_indices)}, "
                          f"跨predicate={'是' if is_cross_predicate else '否'})")
                
                # 计算跨predicate cluster原子数量占比和cluster比例
                total_atoms = len(maus)
                if total_atoms > 0:
                    cross_cluster_atom_ratio = (total_atoms_in_cross_clusters / total_atoms * 100)
                    cross_cluster_ratio = (len(cross_predicate_clusters) / total_clusters * 100) if total_clusters > 0 else 0.0
                    print(f"  - 跨predicate cluster原子数量占比: {total_atoms_in_cross_clusters}/{total_atoms} = {cross_cluster_atom_ratio:.1f}%")
                    print(f"  - 跨predicate cluster数占比: {len(cross_predicate_clusters)}/{total_clusters} = {cross_cluster_ratio:.1f}%")
        
        return result
    
    def _get_semantic_predicate_group(self, normalized_pred: str, 
                                     predicate_semantic_clusters: Dict[str, List[str]],
                                     predicate_index: Dict[str, List[int]]) -> List[str]:
        """获取语义等价的predicate组（包括跨predicate桥接）
        
        Args:
            normalized_pred: 归一化后的predicate
            predicate_semantic_clusters: predicate语义聚类映射
            predicate_index: predicate索引
            
        Returns:
            List[str]: 语义等价的predicate列表（包括自身）
        """
        if normalized_pred in predicate_semantic_clusters:
            return predicate_semantic_clusters[normalized_pred]
        else:
            # 如果没有语义聚类，只返回自身
            return [normalized_pred] if normalized_pred in predicate_index else []
    
    def _build_indexes_with_normalization(self, maus: List[MAU]):
        """构建基于归一化predicate的索引
        
        Args:
            maus: MAU列表
        """
        self.predicate_index = defaultdict(list)
        self.patient_index = defaultdict(list)
        self.agent_index = defaultdict(list)
        
        for i, mau in enumerate(maus):
            if not hasattr(mau, '_normalized_predicate'):
                continue
            
            normalized_pred = mau._normalized_predicate
            if not normalized_pred:
                normalized_pred = "__empty__"
            
            self.predicate_index[normalized_pred].append(i)
            
            if mau.patient:
                patient_key = mau.patient.lower().strip()
                self.patient_index[patient_key].append(i)
            
            if mau.agent:
                agent_key = mau.agent.lower().strip()
                self.agent_index[agent_key].append(i)
    
    def _merge_same_predicate_maus(self, maus: List[MAU], path_weights: Optional[Dict[str, float]] = None) -> MAU:
        """合并相同predicate的MAU
        
        Args:
            maus: 相同predicate的MAU列表
            path_weights: 路径权重字典（可选，阶段2.3）
            
        Returns:
            MAU: 合并后的MAU
        """
        if len(maus) == 1:
            return maus[0]
        
        if path_weights:
            scored_maus = [(m.confidence * path_weights.get(m.source_path, 1.0), m) for m in maus]
            base_mau = max(scored_maus, key=lambda x: x[0])[1]
            confidences = [m.confidence for m in maus]
            weights = [path_weights.get(m.source_path, 1.0) for m in maus]
            total_weight = sum(weights)
            if total_weight > 0:
                merged_confidence = sum(c * w for c, w in zip(confidences, weights)) / total_weight
            else:
                merged_confidence = max(confidences)
        else:
            base_mau = max(maus, key=lambda m: m.confidence)
            merged_confidence = max(m.confidence for m in maus)
        
        # 合并patient和agent
        patients = [m.patient for m in maus if m.patient]
        agents = [m.agent for m in maus if m.agent]
        merged_patient = self._merge_similar_phrases(patients) or ""
        merged_agent = self._merge_similar_phrases(agents) or ""
        
        # 合并source_path
        source_paths = sorted(set(m.source_path for m in maus))
        merged_source_path = "+".join(source_paths)
        
        granularity = "complete"
        if not merged_agent and not merged_patient:
            granularity = "minimal"
        elif not merged_agent or not merged_patient:
            granularity = "partial"
        
        preposition = self._extract_preposition_from_atom_texts(maus, base_mau)
        
        merged_atom_text_parts = []
        if merged_agent:
            merged_atom_text_parts.append(merged_agent)
        merged_atom_text_parts.append(base_mau.predicate)
        if preposition:
            merged_atom_text_parts.append(preposition)
        if merged_patient:
            merged_atom_text_parts.append(merged_patient)
        merged_atom_text = " ".join(merged_atom_text_parts)
        
        return MAU(
            predicate=base_mau.predicate,
            patient=merged_patient,
            agent=merged_agent,
            context=base_mau.context,
            granularity=granularity,
            confidence=merged_confidence,
            source_path=merged_source_path,
            nested_events=base_mau.nested_events,
            coref_resolved=base_mau.coref_resolved,
            atom_text=merged_atom_text,
            atom_type=base_mau.atom_type,
            sentence_id=base_mau.sentence_id,
            original_sentence=base_mau.original_sentence
        )
    
    def _extract_preposition_from_atom_texts(self, maus: List[MAU], base_mau: MAU) -> Optional[str]:
        """从MAU的atom_text中提取介词
        
        Args:
            maus: MAU列表
            base_mau: 基础MAU（用于提取predicate）
            
        Returns:
            Optional[str]: 介词文本，如果不存在返回None
        """
        predicate = base_mau.predicate
        prepositions = ['of', 'for', 'on', 'in', 'at', 'to', 'with', 'by']
        
        for mau in maus:
            if not mau.atom_text:
                continue
            parts = mau.atom_text.split()
            predicate_idx = -1
            for i, part in enumerate(parts):
                if part.lower() == predicate or part.lower() == predicate.lower():
                    predicate_idx = i
                    break
            
            if predicate_idx >= 0 and predicate_idx + 1 < len(parts):
                next_part = parts[predicate_idx + 1].lower()
                if next_part in prepositions:
                    return next_part
        
        return None
    
    def _merge_similar_phrases(self, phrases: List[str], threshold: float = 0.75) -> str:
        """合并相似短语
        
        Args:
            phrases: 短语列表
            threshold: 相似度阈值
            
        Returns:
            str: 合并后的短语（选择最长的）
        """
        if not phrases:
            return None
        
        if len(phrases) == 1:
            return phrases[0]
        
        unique_phrases = []
        processed = set()
        
        for i, phrase1 in enumerate(phrases):
            if i in processed:
                continue
            
            similar_group = [phrase1]
            for j, phrase2 in enumerate(phrases[i+1:], start=i+1):
                if j in processed:
                    continue
                
                similarity = self._calculate_phrase_similarity(phrase1, phrase2)
                if similarity >= threshold:
                    similar_group.append(phrase2)
                    processed.add(j)
            
            unique_phrases.append(similar_group)
            processed.add(i)
        
        merged_phrases = [max(group, key=len) for group in unique_phrases]
        return max(merged_phrases, key=len)
    
    def _calculate_phrase_similarity(self, phrase1: str, phrase2: str) -> float:
        """计算短语相似度"""
        return calculate_phrase_similarity(phrase1, phrase2, self.emb_model)

class LowConfidenceHandler:
    """基础低置信度处理器
    
    功能：
    - 固定阈值过滤
    - 低置信度原子记录
    - 统计监控
    """
    
    def __init__(self, threshold: float = 0.5):
        """初始化低置信度处理器
        
        Args:
            threshold: 置信度阈值（默认0.5）
        """
        self.threshold = threshold
        self.low_confidence_atoms: List[MAU] = []
        self.stats = {
            "total": 0,
            "high_confidence": 0,
            "low_confidence": 0,
            "by_source_path": defaultdict(int)
        }
    
    def filter_low_confidence(self, maus: List[MAU], threshold: float = None) -> Tuple[List[MAU], List[MAU]]:
        """过滤低置信度MAU
        
        Args:
            maus: 输入MAU列表
            threshold: 置信度阈值（如果为None，使用self.threshold）
            
        Returns:
            Tuple[List[MAU], List[MAU]]: (高置信度MAU列表, 低置信度MAU列表)
        """
        if threshold is None:
            threshold = self.threshold
        
        high_confidence = []
        low_confidence = []
        
        self.stats["total"] += len(maus)
        
        for mau in maus:
            if mau.confidence >= threshold:
                high_confidence.append(mau)
                self.stats["high_confidence"] += 1
            else:
                low_confidence.append(mau)
                self.stats["low_confidence"] += 1
                self.stats["by_source_path"][mau.source_path] += 1
                self.low_confidence_atoms.append(mau)
        
        return high_confidence, low_confidence
    
    def get_stats(self) -> Dict:
        """获取统计信息
        
        Returns:
            Dict: 统计信息字典
        """
        stats = self.stats.copy()
        if stats["total"] > 0:
            stats["low_confidence_rate"] = stats["low_confidence"] / stats["total"]
        else:
            stats["low_confidence_rate"] = 0.0
        return stats
    
    def clear_low_confidence_atoms(self):
        """清空低置信度原子记录"""
        self.low_confidence_atoms.clear()

import lightgbm as lgb
HAS_LIGHTGBM = True

from sklearn.isotonic import IsotonicRegression
from sklearn.calibration import CalibratedClassifierCV
HAS_SKLEARN_CALIBRATION = True

class LearnableConfidenceModel:
    """可学习置信度模型
    
    使用LightGBM/XGBoost学习原子置信度，支持温度缩放和Isotonic校准
    """
    
    def __init__(self, model_type: str = "lightgbm", use_calibration: bool = True):
        """初始化可学习置信度模型
        
        Args:
            model_type: 模型类型，"lightgbm"或"xgboost"
            use_calibration: 是否使用校准（温度缩放/Isotonic回归）
        """
        self.model_type = model_type
        self.use_calibration = use_calibration
        self.model = None
        self.calibrator = None
        self.feature_names = None
        self.is_trained = False
        
        if model_type == "lightgbm":
            if not HAS_LIGHTGBM:
                raise ImportError("LightGBM未安装，请运行: pip install lightgbm")
        elif model_type == "xgboost":
            import xgboost as xgb
            self.xgb = xgb
        else:
            raise ValueError(f"不支持的模型类型: {model_type}")
    
    def extract_features(self, mau: MAU, sentence: str = "", doc=None) -> Dict[str, float]:
        """从MAU提取特征（支持 SRLEventUnit 转换后的 MAU）
        
        Args:
            mau: MAU对象（可能是从 SRLEventUnit 转换而来）
            sentence: 原始句子文本
            doc: spaCy doc对象（可选）
            
        Returns:
            Dict: 特征字典
        """
        features = {}
        
        features["path_srl"] = 1.0 if mau.source_path == "SRL" else 0.0
        
        sentence_len = len(sentence) if sentence else len(mau.original_sentence)
        features["sentence_length"] = float(sentence_len)
        features["sentence_length_log"] = np.log1p(sentence_len)
        
        features["has_agent"] = 1.0 if mau.agent else 0.0
        features["has_patient"] = 1.0 if mau.patient else 0.0
        features["has_both"] = 1.0 if (mau.agent and mau.patient) else 0.0
        
        features["granularity_minimal"] = 1.0 if mau.granularity == "minimal" else 0.0
        features["granularity_partial"] = 1.0 if mau.granularity == "partial" else 0.0
        features["granularity_complete"] = 1.0 if mau.granularity == "complete" else 0.0
        
        features["original_confidence"] = mau.confidence
        
        predicate = mau.predicate.lower() if mau.predicate else ""
        features["predicate_length"] = float(len(predicate))
        features["has_predicate"] = 1.0 if predicate else 0.0  # SRL 特征：是否有谓词
        features["predicate_in_strong_verbs"] = 1.0 if predicate in OPINION_VERBS_STRONG else 0.0
        features["predicate_in_medium_verbs"] = 1.0 if predicate in OPINION_VERBS_MEDIUM else 0.0
        features["predicate_in_weak_verbs"] = 1.0 if predicate in OPINION_VERBS_WEAK else 0.0
        
        features["agent_length"] = float(len(mau.agent)) if mau.agent else 0.0
        features["patient_length"] = float(len(mau.patient)) if mau.patient else 0.0
        features["agent_length_log"] = np.log1p(features["agent_length"])
        features["patient_length_log"] = np.log1p(features["patient_length"])
        
        atom_text = mau.atom_text if mau.atom_text else ""
        features["atom_text_length"] = float(len(atom_text))
        features["atom_text_length_log"] = np.log1p(len(atom_text))
        features["atom_text_word_count"] = float(len(atom_text.split()))
        
        # SRL 特征：从 atom_dict 中提取（如果是从 SRLEventUnit 转换而来）
        atom_dict = mau.to_dict() if hasattr(mau, 'to_dict') else {}
        srl_arguments = atom_dict.get("srl_arguments", {})
        features["srl_argument_count"] = float(len(srl_arguments))  # 论元个数
        features["srl_has_arg0"] = 1.0 if "ARG0" in srl_arguments else 0.0
        features["srl_has_arg1"] = 1.0 if "ARG1" in srl_arguments else 0.0
        features["srl_has_complete_structure"] = 1.0 if (features["srl_has_arg0"] and features["srl_has_arg1"] and features["has_predicate"]) else 0.0
        
        # 术语密度（简单估算：长词比例）
        words = atom_text.split()
        long_words = [w for w in words if len(w) > 6]
        features["term_density"] = float(len(long_words) / len(words)) if words else 0.0
        
        if doc:
            max_depth = 0
            for token in doc:
                depth = 0
                head = token.head
                while head != token and depth < 20:
                    depth += 1
                    head = head.head
                max_depth = max(max_depth, depth)
            features["dependency_depth"] = float(max_depth)
        else:
            features["dependency_depth"] = 0.0
        
        features["coref_resolved"] = 1.0 if mau.coref_resolved else 0.0
        
        return features
    
    def train(self, training_data: List[Tuple[MAU, float]], validation_data: Optional[List[Tuple[MAU, float]]] = None):
        """训练置信度模型
        
        Args:
            training_data: 训练数据列表，每个元素为(MAU, 真实置信度标签)
            validation_data: 验证数据列表（可选）
        """
        if not training_data:
            raise ValueError("训练数据不能为空")
        
        X_train = []
        y_train = []
        
        for mau, label in training_data:
            features = self.extract_features(mau, mau.original_sentence)
            X_train.append(list(features.values()))
            y_train.append(label)
        
        X_train = np.array(X_train)
        y_train = np.array(y_train)
        
        if not self.feature_names:
            self.feature_names = list(features.keys())
        
        if self.model_type == "lightgbm":
            train_data = lgb.Dataset(X_train, label=y_train)
            
            params = {
                'objective': 'regression',
                'metric': 'rmse',
                'boosting_type': 'gbdt',
                'num_leaves': 31,
                'learning_rate': 0.05,
                'feature_fraction': 0.9,
                'bagging_fraction': 0.8,
                'bagging_freq': 5,
                'verbose': -1
            }
            
            valid_sets = [train_data]
            if validation_data:
                X_val = []
                y_val = []
                for mau, label in validation_data:
                    features = self.extract_features(mau, mau.original_sentence)
                    X_val.append(list(features.values()))
                    y_val.append(label)
                X_val = np.array(X_val)
                y_val = np.array(y_val)
                valid_sets.append(lgb.Dataset(X_val, label=y_val))
            
            self.model = lgb.train(
                params,
                train_data,
                num_boost_round=100,
                valid_sets=valid_sets,
                callbacks=[lgb.early_stopping(stopping_rounds=10), lgb.log_evaluation(period=0)]
            )
        
        elif self.model_type == "xgboost":
            dtrain = self.xgb.DMatrix(X_train, label=y_train)
            
            params = {
                'objective': 'reg:squarederror',
                'eval_metric': 'rmse',
                'max_depth': 6,
                'learning_rate': 0.05,
                'subsample': 0.8,
                'colsample_bytree': 0.9
            }
            
            evals = [(dtrain, 'train')]
            if validation_data:
                X_val = []
                y_val = []
                for mau, label in validation_data:
                    features = self.extract_features(mau, mau.original_sentence)
                    X_val.append(list(features.values()))
                    y_val.append(label)
                X_val = np.array(X_val)
                y_val = np.array(y_val)
                dval = self.xgb.DMatrix(X_val, label=y_val)
                evals.append((dval, 'eval'))
            
            self.model = self.xgb.train(
                params,
                dtrain,
                num_boost_round=100,
                evals=evals,
                early_stopping_rounds=10,
                verbose_eval=False
            )
        
        if self.use_calibration and HAS_SKLEARN_CALIBRATION:
            train_pred = self._predict_raw(X_train)
            self.calibrator = IsotonicRegression(out_of_bounds='clip')
            self.calibrator.fit(train_pred, y_train)
        
        self.is_trained = True
    
    def predict(self, mau: MAU, sentence: str = "") -> float:
        """预测MAU的校准后置信度
        
        Args:
            mau: MAU对象
            sentence: 原始句子文本（可选）
            
        Returns:
            float: 校准后的置信度（0-1）
        """
        if not self.is_trained:
            return mau.confidence
        
        features = self.extract_features(mau, sentence or mau.original_sentence)
        X = np.array([list(features.values())])
        
        if self.model_type == "lightgbm":
            pred = self.model.predict(X)[0]
        else:
            dtest = self.xgb.DMatrix(X)
            pred = self.model.predict(dtest)[0]
        
        if self.calibrator:
            pred = self.calibrator.predict([pred])[0]
        
        return max(0.0, min(1.0, pred))
    
    def _predict_raw(self, X: np.ndarray) -> np.ndarray:
        """原始预测（未校准）"""
        if self.model_type == "lightgbm":
            return self.model.predict(X)
        else:
            dtest = self.xgb.DMatrix(X)
            return self.model.predict(dtest)
    
    def save(self, filepath: str):
        """保存模型到文件"""
        if not self.is_trained:
            raise ValueError("模型未训练，无法保存")
        
        model_data = {
            "model_type": self.model_type,
            "use_calibration": self.use_calibration,
            "feature_names": self.feature_names,
            "is_trained": self.is_trained
        }
        
        if self.model_type == "lightgbm":
            model_path = filepath + ".lgb"
            self.model.save_model(model_path)
            model_data["model_path"] = model_path
        else:
            model_path = filepath + ".xgb"
            self.model.save_model(model_path)
            model_data["model_path"] = model_path
        
        if self.calibrator:
            import pickle
            calibrator_path = filepath + "_calibrator.pkl"
            with open(calibrator_path, 'wb') as f:
                pickle.dump(self.calibrator, f)
            model_data["calibrator_path"] = calibrator_path
        
        import json
        with open(filepath + "_meta.json", 'w') as f:
            json.dump(model_data, f, indent=2)
    
    def load(self, filepath: str):
        """从文件加载模型"""
        import json
        import pickle
        
        with open(filepath + "_meta.json", 'r') as f:
            model_data = json.load(f)
        
        self.model_type = model_data.get("model_type", "lightgbm")
        self.use_calibration = model_data.get("use_calibration", True)
        self.feature_names = model_data.get("feature_names", [])
        self.is_trained = model_data.get("is_trained", False)
        
        if self.is_trained and "model_path" in model_data:
            if self.model_type == "lightgbm":
                if not HAS_LIGHTGBM or lgb is None:
                    raise ImportError("LightGBM未安装，无法加载模型。请运行: pip install lightgbm")
                self.model = lgb.Booster(model_file=model_data["model_path"])
            else:
                if not hasattr(self, 'xgb') or self.xgb is None:
                    import xgboost as xgb
                    self.xgb = xgb
                self.model = self.xgb.Booster()
                self.model.load_model(model_data["model_path"])
        
        if self.use_calibration and "calibrator_path" in model_data:
            with open(model_data["calibrator_path"], 'rb') as f:
                self.calibrator = pickle.load(f)

class LearnableWeightModel:
    """可学习权重模型
    
    动态调整路径A/B/C的权重，基于历史成功率和文档特征
    """
    
    def __init__(self, model_type: str = "linear"):
        """初始化可学习权重模型
        
        Args:
            model_type: 模型类型，"linear"（线性回归）或"lightgbm"
        """
        self.model_type = model_type
        self.model = None
        self.is_trained = False
        self.path_weights = {"A": 1.0, "B": 0.8, "C": 0.5}
        self.history = {
            "A": {"success": 0, "total": 0},
            "B": {"success": 0, "total": 0},
            "C": {"success": 0, "total": 0}
        }
        
        if model_type == "lightgbm" and not HAS_LIGHTGBM:
            self.model_type = "linear"
    
    def extract_features(self, document_context: Dict) -> Dict[str, float]:
        """提取权重预测特征
        
        Args:
            document_context: 文档上下文信息，包含：
                - path_success_rates: 各路径历史成功率
                - sentence_complexity: 句子复杂度（平均长度、依存深度等）
                - dependency_quality: 依存解析质量
                - document_type: 文档类型（可选）
                - domain: 文档领域（可选）
                
        Returns:
            Dict: 特征字典
        """
        features = {}
        
        path_success_rates = document_context.get("path_success_rates", {})
        features["path_srl_success_rate"] = path_success_rates.get("SRL", 0.0)
        
        complexity = document_context.get("sentence_complexity", {})
        features["avg_sentence_length"] = complexity.get("avg_length", 0.0)
        features["avg_dependency_depth"] = complexity.get("avg_depth", 0.0)
        features["max_sentence_length"] = complexity.get("max_length", 0.0)
        
        dep_quality = document_context.get("dependency_quality", {})
        features["parse_quality_score"] = dep_quality.get("quality_score", 0.0)
        features["parse_confidence"] = dep_quality.get("confidence", 0.0)
        
        doc_type = document_context.get("document_type", "unknown")
        features["doc_type_paper"] = 1.0 if doc_type == "paper" else 0.0
        features["doc_type_abstract"] = 1.0 if doc_type == "abstract" else 0.0
        features["doc_type_unknown"] = 1.0 if doc_type == "unknown" else 0.0
        
        domain = document_context.get("domain", "unknown")
        features["domain_known"] = 1.0 if domain != "unknown" else 0.0
        
        path_coverage = document_context.get("path_coverage", {})
        features["path_srl_coverage"] = path_coverage.get("SRL", 0.0)
        
        return features
    
    def update_history(self, path: str, success: bool):
        """更新路径历史统计
        
        Args:
            path: 路径标识（"A", "B", "C"）
            success: 是否成功抽取
        """
        if path in self.history:
            self.history[path]["total"] += 1
            if success:
                self.history[path]["success"] += 1
    
    def get_path_success_rates(self) -> Dict[str, float]:
        """获取各路径历史成功率"""
        rates = {}
        for path, stats in self.history.items():
            if stats["total"] > 0:
                rates[path] = stats["success"] / stats["total"]
            else:
                rates[path] = 0.0
        return rates
    
    def train(self, training_data: List[Tuple[Dict, Dict[str, float]]]):
        """训练权重模型
        
        Args:
            training_data: 训练数据列表，每个元素为(文档上下文, 目标权重字典)
        """
        if not training_data:
            raise ValueError("训练数据不能为空")
        
        X_train = []
        y_train_a = []
        y_train_b = []
        y_train_c = []
        
        for doc_context, target_weights in training_data:
            features = self.extract_features(doc_context)
            X_train.append(list(features.values()))
            y_train_a.append(target_weights.get("A", 1.0))
            y_train_b.append(target_weights.get("B", 0.8))
            y_train_c.append(target_weights.get("C", 0.5))
        
        X_train = np.array(X_train)
        
        if self.model_type == "linear":
            from sklearn.linear_model import LinearRegression
            self.model = {
                "A": LinearRegression(),
                "B": LinearRegression(),
                "C": LinearRegression()
            }
            self.model["A"].fit(X_train, y_train_a)
            self.model["B"].fit(X_train, y_train_b)
            self.model["C"].fit(X_train, y_train_c)
        
        elif self.model_type == "lightgbm":
            train_data_a = lgb.Dataset(X_train, label=y_train_a)
            train_data_b = lgb.Dataset(X_train, label=y_train_b)
            train_data_c = lgb.Dataset(X_train, label=y_train_c)
            
            params = {
                'objective': 'regression',
                'metric': 'rmse',
                'boosting_type': 'gbdt',
                'num_leaves': 15,
                'learning_rate': 0.05,
                'feature_fraction': 0.9,
                'verbose': -1
            }
            
            self.model = {
                "A": lgb.train(params, train_data_a, num_boost_round=50),
                "B": lgb.train(params, train_data_b, num_boost_round=50),
                "C": lgb.train(params, train_data_c, num_boost_round=50)
            }
        
        self.is_trained = True
    
    def predict_weights(self, document_context: Dict) -> Dict[str, float]:
        """预测路径权重
        
        Args:
            document_context: 文档上下文信息
            
        Returns:
            Dict: 路径权重字典 {"A": weight_a, "B": weight_b, "C": weight_c}
        """
        if not self.is_trained or self.model is None:
            success_rates = self.get_path_success_rates()
            weights = {
                "A": max(0.5, min(1.0, success_rates.get("A", 1.0))),
                "B": max(0.3, min(0.8, success_rates.get("B", 0.8))),
                "C": max(0.2, min(0.6, success_rates.get("C", 0.5)))
            }
            return weights
        
        features = self.extract_features(document_context)
        X = np.array([list(features.values())])
        
        if self.model_type == "linear":
            weights = {
                "A": max(0.5, min(1.0, self.model["A"].predict(X)[0])),
                "B": max(0.3, min(0.8, self.model["B"].predict(X)[0])),
                "C": max(0.2, min(0.6, self.model["C"].predict(X)[0]))
            }
        else:
            weights = {
                "A": max(0.5, min(1.0, self.model["A"].predict(X)[0])),
                "B": max(0.3, min(0.8, self.model["B"].predict(X)[0])),
                "C": max(0.2, min(0.6, self.model["C"].predict(X)[0]))
            }
        
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total * 2.3 for k, v in weights.items()}
        
        return weights
    
    def save(self, filepath: str):
        """保存模型到文件"""
        import json
        import pickle
        
        model_data = {
            "model_type": self.model_type,
            "is_trained": self.is_trained,
            "history": self.history,
            "path_weights": self.path_weights
        }
        
        if self.is_trained and self.model:
            if self.model_type == "linear":
                model_path = filepath + "_linear.pkl"
                with open(model_path, 'wb') as f:
                    pickle.dump(self.model, f)
                model_data["model_path"] = model_path
            else:
                model_path_a = filepath + "_A.lgb"
                model_path_b = filepath + "_B.lgb"
                model_path_c = filepath + "_C.lgb"
                self.model["A"].save_model(model_path_a)
                self.model["B"].save_model(model_path_b)
                self.model["C"].save_model(model_path_c)
                model_data["model_paths"] = {
                    "A": model_path_a,
                    "B": model_path_b,
                    "C": model_path_c
                }
        
        with open(filepath + "_meta.json", 'w') as f:
            json.dump(model_data, f, indent=2)
    
    def load(self, filepath: str):
        """从文件加载模型"""
        import json
        import pickle
        
        with open(filepath + "_meta.json", 'r') as f:
            model_data = json.load(f)
        
        self.model_type = model_data.get("model_type", "linear")
        self.is_trained = model_data.get("is_trained", False)
        self.history = model_data.get("history", {"A": {"success": 0, "total": 0}, "B": {"success": 0, "total": 0}, "C": {"success": 0, "total": 0}})
        self.path_weights = model_data.get("path_weights", {"A": 1.0, "B": 0.8, "C": 0.5})
        
        if self.is_trained:
            if self.model_type == "linear":
                if "model_path" not in model_data:
                    raise ValueError("模型元数据中缺少 model_path 字段（线性模型）")
                with open(model_data["model_path"], 'rb') as f:
                    self.model = pickle.load(f)
            else:
                if not HAS_LIGHTGBM:
                    raise ImportError("LightGBM未安装，无法加载模型。请运行: pip install lightgbm")
                if lgb is None:
                    import lightgbm as lgb
                if "model_paths" not in model_data:
                    raise ValueError("模型元数据中缺少 model_paths 字段（LightGBM模型）")
                model_paths = model_data["model_paths"]
                self.model = {
                    "A": lgb.Booster(model_file=model_paths["A"]),
                    "B": lgb.Booster(model_file=model_paths["B"]),
                    "C": lgb.Booster(model_file=model_paths["C"])
                }

class HierarchicalEmbeddingClustering:
    """分层embedding聚类
    
    三层聚类策略：
    - 层级1：predicate embedding（核心语义，粗粒度）
    - 层级2：patient+agent embedding（论元语义，中粒度）
    - 层级3：context embedding（上下文语义，细粒度）
    """
    
    def __init__(self, emb_model=None):
        """初始化分层聚类器
        
        Args:
            emb_model: 嵌入模型（用于计算embedding）
        """
        self.emb_model = emb_model
    
    def cluster_atoms(self, atoms: List[Dict], threshold_level1: float = 0.75, 
                     threshold_level2: float = 0.80, threshold_level3: float = 0.85) -> List[List[int]]:
        """分层聚类原子
        
        Args:
            atoms: 原子列表（字典格式）
            threshold_level1: 层级1聚类阈值（predicate）
            threshold_level2: 层级2聚类阈值（patient+agent）
            threshold_level3: 层级3聚类阈值（context）
            
        Returns:
            List[List[int]]: 聚类结果，每个子列表包含同一簇的原子索引
        """
        if not atoms or len(atoms) < 2:
            return []
        
        n_atoms = len(atoms)
        level1_clusters = self._cluster_by_predicate(atoms, threshold_level1)
        
        if not level1_clusters:
            return []
        
        level2_clusters = self._refine_by_patient_agent(atoms, level1_clusters, threshold_level2)
        level3_clusters = self._refine_by_context(atoms, level2_clusters, threshold_level3)
        
        return level3_clusters
    
    def _cluster_by_predicate(self, atoms: List[Dict], threshold: float) -> List[List[int]]:
        """层级1：基于predicate的粗粒度聚类"""
        if not self.emb_model:
            predicate_groups = defaultdict(list)
            for i, atom in enumerate(atoms):
                predicate = atom.get("verb_lemma", "").lower()
                predicate_groups[predicate].append(i)
            return [indices for indices in predicate_groups.values() if len(indices) > 1]
        
        predicates = []
        for atom in atoms:
            predicate = atom.get("verb_lemma", atom.get("predicate", ""))
            predicates.append(predicate)
        
        predicate_embeddings = self.emb_model.encode(predicates, convert_to_tensor=True, show_progress_bar=False)
        predicate_embeddings = predicate_embeddings.cpu().numpy()
        
        norms = np.linalg.norm(predicate_embeddings, axis=1, keepdims=True)
        normalized_embeddings = predicate_embeddings / (norms + 1e-12)
        
        dim = normalized_embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(normalized_embeddings.astype('float32'))
        
        n_atoms = len(atoms)
        parent = list(range(n_atoms))
        
        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        
        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py
        
        k = min(10, n_atoms - 1)
        if k > 0:
            similarities, indices = index.search(normalized_embeddings.astype('float32'), k + 1)
            for i in range(n_atoms):
                for j_idx, sim in zip(indices[i][1:], similarities[i][1:]):
                    if sim >= threshold:
                        union(i, j_idx)
        
        cluster_dict = {}
        for i in range(n_atoms):
            root = find(i)
            if root not in cluster_dict:
                cluster_dict[root] = []
            cluster_dict[root].append(i)
        
        return [indices for indices in cluster_dict.values() if len(indices) >= 2]
    
    def _refine_by_patient_agent(self, atoms: List[Dict], level1_clusters: List[List[int]], 
                                 threshold: float) -> List[List[int]]:
        """层级2：基于patient+agent的中粒度细化"""
        if not self.emb_model:
            return level1_clusters
        
        refined_clusters = []
        
        for cluster_indices in level1_clusters:
            if len(cluster_indices) < 2:
                refined_clusters.append(cluster_indices)
                continue
            
            patient_agent_texts = []
            for idx in cluster_indices:
                atom = atoms[idx]
                parts = []
                if atom.get("agent"):
                    parts.append(atom["agent"])
                if atom.get("patient"):
                    parts.append(atom["patient"])
                text = " ".join(parts) if parts else ""
                if not text:
                    text = atom.get("predicate", atom.get("verb_lemma", ""))
                patient_agent_texts.append(text)
            
            embeddings = self.emb_model.encode(patient_agent_texts, convert_to_tensor=True, show_progress_bar=False)
            embeddings = embeddings.cpu().numpy()
            
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            normalized_embeddings = embeddings / (norms + 1e-12)
            
            sub_clusters = self._cluster_within_group(normalized_embeddings, threshold)
            
            for sub_cluster in sub_clusters:
                refined_cluster = [cluster_indices[i] for i in sub_cluster]
                if len(refined_cluster) >= 2:
                    refined_clusters.append(refined_cluster)
        
        return refined_clusters
    
    def _refine_by_context(self, atoms: List[Dict], level2_clusters: List[List[int]], 
                          threshold: float) -> List[List[int]]:
        """层级3：基于context的细粒度精化"""
        if not self.emb_model:
            return level2_clusters
        
        refined_clusters = []
        
        for cluster_indices in level2_clusters:
            if len(cluster_indices) < 2:
                refined_clusters.append(cluster_indices)
                continue
            
            context_texts = []
            for idx in cluster_indices:
                atom = atoms[idx]
                context = atom.get("original_sentence", atom.get("context", ""))
                context_texts.append(context[:200])
            
            embeddings = self.emb_model.encode(context_texts, convert_to_tensor=True, show_progress_bar=False)
            embeddings = embeddings.cpu().numpy()
            
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            normalized_embeddings = embeddings / (norms + 1e-12)
            
            sub_clusters = self._cluster_within_group(normalized_embeddings, threshold)
            
            for sub_cluster in sub_clusters:
                refined_cluster = [cluster_indices[i] for i in sub_cluster]
                if len(refined_cluster) >= 2:
                    refined_clusters.append(refined_cluster)
                else:
                    refined_clusters.append(refined_cluster)
        
        return refined_clusters
    
    def _cluster_within_group(self, embeddings: np.ndarray, threshold: float) -> List[List[int]]:
        """在组内进行聚类（使用Union-Find）"""
        n = len(embeddings)
        if n < 2:
            return [[i] for i in range(n)]
        
        dim = embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(embeddings.astype('float32'))
        
        parent = list(range(n))
        
        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        
        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py
        
        k = min(5, n - 1)
        if k > 0:
            similarities, indices = index.search(embeddings.astype('float32'), k + 1)
            for i in range(n):
                for j_idx, sim in zip(indices[i][1:], similarities[i][1:]):
                    if sim >= threshold:
                        union(i, j_idx)
        
        cluster_dict = {}
        for i in range(n):
            root = find(i)
            if root not in cluster_dict:
                cluster_dict[root] = []
            cluster_dict[root].append(i)
        
        return list(cluster_dict.values())

class AlertManager:
    """告警管理器
    
    功能：
    - SLO/SLI监控
    - 异常检测
    - 告警触发
    - 自动回滚建议
    """
    
    def __init__(self):
        """初始化告警管理器"""
        self.slos = {
            "throughput": 100,
            "p95_latency_ms": 5000,
            "atom_generation_rate": 0.80,
            "extraction_f1": 0.70,
            "clustering_ari": 0.60,
            "error_rate": 0.01,
            "crash_rate": 0.05
        }
        
        self.alert_thresholds = {
            "warning": 0.10,
            "critical": 0.20,
            "auto_rollback": 0.30
        }
        
        self.alert_history: List[Dict] = []
        self.baseline_metrics: Optional[Dict] = None
    
    def check_slos(self, metrics: Dict) -> List[Dict]:
        """检查SLO是否满足
        
        Args:
            metrics: 当前指标字典
            
        Returns:
            List[Dict]: 告警列表
        """
        alerts = []
        
        throughput = metrics.get("performance", {}).get("throughput_docs_per_minute", 0)
        if throughput < self.slos["throughput"] * (1 - self.alert_thresholds["warning"]):
            severity = "critical" if throughput < self.slos["throughput"] * (1 - self.alert_thresholds["critical"]) else "warning"
            alerts.append({
                "type": "throughput",
                "severity": severity,
                "current": throughput,
                "target": self.slos["throughput"],
                "message": f"吞吐量低于目标: {throughput:.2f} < {self.slos['throughput']}"
            })
        
        p95_latency = metrics.get("performance", {}).get("p95_time_ms", float('inf'))
        if p95_latency > self.slos["p95_latency_ms"] * (1 + self.alert_thresholds["warning"]):
            severity = "critical" if p95_latency > self.slos["p95_latency_ms"] * (1 + self.alert_thresholds["critical"]) else "warning"
            alerts.append({
                "type": "latency",
                "severity": severity,
                "current": p95_latency,
                "target": self.slos["p95_latency_ms"],
                "message": f"P95延迟超过目标: {p95_latency:.2f} > {self.slos['p95_latency_ms']}"
            })
        
        # 检查extraction_rate（句子级别的提取率）
        extraction_rate = metrics.get("atom_extraction", {}).get("extraction_rate", 0) / 100.0
        if extraction_rate < self.slos["atom_generation_rate"] * (1 - self.alert_thresholds["warning"]):
            severity = "critical" if extraction_rate < self.slos["atom_generation_rate"] * (1 - self.alert_thresholds["critical"]) else "warning"
            alerts.append({
                "type": "atom_extraction",
                "severity": severity,
                "current": extraction_rate,
                "target": self.slos["atom_generation_rate"],
                "message": f"原子提取率低于目标: {extraction_rate:.3f} < {self.slos['atom_generation_rate']}"
            })
        
        # 同时检查usable_rate（原子级别的有效率）
        usable_rate = metrics.get("atom_extraction", {}).get("usable_rate", 0) / 100.0
        if usable_rate < 0.50:  # usable_rate目标设为50%（对齐后保留率）
            severity = "warning" if usable_rate < 0.30 else "info"
            alerts.append({
                "type": "atom_usable",
                "severity": severity,
                "current": usable_rate,
                "target": 0.50,
                "message": f"原子有效率偏低: {usable_rate:.3f} < 0.50（可能受predicate聚类影响）"
            })
        
        clustering_ari = metrics.get("clustering", {}).get("ari", None)
        if clustering_ari is not None and clustering_ari < self.slos["clustering_ari"] * (1 - self.alert_thresholds["warning"]):
            severity = "critical" if clustering_ari < self.slos["clustering_ari"] * (1 - self.alert_thresholds["critical"]) else "warning"
            alerts.append({
                "type": "clustering_quality",
                "severity": severity,
                "current": clustering_ari,
                "target": self.slos["clustering_ari"],
                "message": f"聚类质量低于目标: {clustering_ari:.3f} < {self.slos['clustering_ari']}"
            })
        
        for alert in alerts:
            alert["timestamp"] = time.time()
            self.alert_history.append(alert)
        
        return alerts
    
    def detect_drift(self, current_metrics: Dict, baseline_metrics: Optional[Dict] = None) -> List[Dict]:
        """检测数据漂移
        
        Args:
            current_metrics: 当前指标
            baseline_metrics: 基线指标（如果为None，使用self.baseline_metrics）
            
        Returns:
            List[Dict]: 漂移告警列表
        """
        if baseline_metrics is None:
            baseline_metrics = self.baseline_metrics
        
        if baseline_metrics is None:
            self.baseline_metrics = current_metrics.copy()
            return []
        
        drift_alerts = []
        
        current_predicates = current_metrics.get("atom_extraction", {}).get("predicate_distribution", {})
        baseline_predicates = baseline_metrics.get("atom_extraction", {}).get("predicate_distribution", {})
        
        if current_predicates and baseline_predicates:
            top_predicates = set(list(current_predicates.keys())[:10] + list(baseline_predicates.keys())[:10])
            for pred in top_predicates:
                current_freq = current_predicates.get(pred, 0)
                baseline_freq = baseline_predicates.get(pred, 0)
                if baseline_freq > 0:
                    change_ratio = abs(current_freq - baseline_freq) / baseline_freq
                    if change_ratio > 0.30:
                        drift_alerts.append({
                            "type": "predicate_distribution_drift",
                            "predicate": pred,
                            "baseline_freq": baseline_freq,
                            "current_freq": current_freq,
                            "change_ratio": change_ratio,
                            "message": f"Predicate '{pred}' 频率变化: {baseline_freq:.3f} → {current_freq:.3f} ({change_ratio*100:.1f}%)"
                        })
        
        current_path_a = current_metrics.get("atom_extraction", {}).get("path_a_coverage", 0) / 100.0
        baseline_path_a = baseline_metrics.get("atom_extraction", {}).get("path_a_coverage", 0) / 100.0
        
        if baseline_path_a > 0:
            path_a_change = abs(current_path_a - baseline_path_a) / baseline_path_a
            if path_a_change > 0.20:
                drift_alerts.append({
                    "type": "path_coverage_drift",
                    "path": "A",
                    "baseline": baseline_path_a,
                    "current": current_path_a,
                    "change_ratio": path_a_change,
                    "message": f"路径A覆盖率变化: {baseline_path_a:.3f} → {current_path_a:.3f} ({path_a_change*100:.1f}%)"
                })
        
        return drift_alerts
    
    def should_rollback(self, alerts: List[Dict]) -> bool:
        """判断是否应该自动回滚
        
        Args:
            alerts: 告警列表
            
        Returns:
            bool: 是否应该回滚
        """
        for alert in alerts:
            if alert["severity"] == "critical":
                if alert["type"] in ["throughput", "latency", "atom_generation", "clustering_quality"]:
                    current = alert["current"]
                    target = alert["target"]
                    
                    if alert["type"] in ["throughput", "atom_generation", "clustering_quality"]:
                        drop_ratio = (target - current) / target if target > 0 else 0
                    else:
                        drop_ratio = (current - target) / target if target > 0 else 0
                    
                    if drop_ratio >= self.alert_thresholds["auto_rollback"]:
                        return True
        
        return False
    
    def get_alert_summary(self) -> Dict:
        """获取告警摘要"""
        if not self.alert_history:
            return {"total": 0, "warnings": 0, "critical": 0}
        
        warnings = sum(1 for a in self.alert_history if a["severity"] == "warning")
        critical = sum(1 for a in self.alert_history if a["severity"] == "critical")
        
        return {
            "total": len(self.alert_history),
            "warnings": warnings,
            "critical": critical,
            "recent_alerts": self.alert_history[-10:]
        }

class CrossDocumentNormalizer:
    """跨文档归一化系统
    
    功能：
    - 增量式归一化：局部文档集合校正→局部归一化索引→逐步扩展到全局
    - 版本化索引：每次合并产生版本号，Git-like版本控制
    - 可回滚合并：合并前后质量回归测试，质量下降自动回滚
    - 质量门：合并前检查局部索引质量，合并后检查全局索引质量
    - 冷启动/热启动：初期高置信度入全局，低置信度入临时池
    """
    
    def __init__(self, emb_model=None, local_batch_size: int = 100, quality_threshold: float = 0.95):
        """初始化跨文档归一化系统
        
        Args:
            emb_model: 嵌入模型（用于相似度计算）
            local_batch_size: 局部文档集合大小（默认100篇）
            quality_threshold: 质量门阈值（质量下降<5%才允许合并，即0.95）
        """
        self.emb_model = emb_model
        self.local_batch_size = local_batch_size
        self.quality_threshold = quality_threshold
        
        self.global_index: Dict[str, Dict] = {}
        self.local_index: Dict[str, Dict] = {}
        self.version = 0
        self.version_history: List[Dict] = []
        
        self.temp_pool: List[MAU] = []
        self.current_batch: List[MAU] = []
        self.batch_count = 0
        
        self.quality_metrics = {
            "consistency": [],
            "coverage": [],
            "precision": []
        }
    
    def add_document_atoms(self, atoms: List[MAU], document_id: str = None):
        """添加文档的原子到当前批次
        
        Args:
            atoms: 文档提取的原子列表
            document_id: 文档ID（可选）
        """
        high_conf_atoms = [a for a in atoms if a.confidence >= 0.7]
        low_conf_atoms = [a for a in atoms if a.confidence < 0.7]
        
        for atom in high_conf_atoms:
            atom.context = document_id
            self.current_batch.append(atom)
        
        self.temp_pool.extend(low_conf_atoms)
        
        if len(self.current_batch) >= self.local_batch_size:
            self._normalize_local_batch()
    
    def _normalize_local_batch(self):
        """对当前批次进行局部归一化"""
        if not self.current_batch:
            return
        
        local_normalized = self._normalize_atoms(self.current_batch)
        local_quality = self._calculate_index_quality(local_normalized, is_local=True)
        
        global_state_before = self._save_global_state()
        merge_success = self._merge_to_global(local_normalized, local_quality)
        
        if merge_success:
            self.version += 1
            self.version_history.append({
                "version": self.version,
                "batch_size": len(self.current_batch),
                "local_quality": local_quality,
                "timestamp": time.time()
            })
        else:
            self._restore_global_state(global_state_before)
        
        self.current_batch = []
        self.batch_count += 1
    
    def _normalize_atoms(self, atoms: List[MAU]) -> Dict[str, Dict]:
        """归一化原子列表（将相同语义的原子归并）
        
        Args:
            atoms: 原子列表
            
        Returns:
            Dict: 归一化索引 {normalized_id: {atoms: [MAU], ...}}
        """
        normalized = {}
        
        if not self.emb_model:
            for atom in atoms:
                key = atom.predicate.lower()
                if key not in normalized:
                    normalized[key] = {"atoms": [], "representative": None}
                normalized[key]["atoms"].append(atom)
            
            for key, data in normalized.items():
                if data["atoms"]:
                    data["representative"] = max(data["atoms"], key=lambda a: a.confidence)
            return normalized
        
        atom_texts = [atom.atom_text for atom in atoms]
        embeddings = self.emb_model.encode(atom_texts, convert_to_tensor=True, show_progress_bar=False)
        embeddings = embeddings.cpu().numpy()
        
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        normalized_embeddings = embeddings / (norms + 1e-12)
        
        dim = normalized_embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(normalized_embeddings.astype('float32'))
        
        n = len(atoms)
        parent = list(range(n))
        
        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        
        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py
        
        threshold = 0.85
        k = min(10, n - 1)
        if k > 0:
            similarities, indices = index.search(normalized_embeddings.astype('float32'), k + 1)
            for i in range(n):
                for j_idx, sim in zip(indices[i][1:], similarities[i][1:]):
                    if sim >= threshold:
                        union(i, j_idx)
        
        cluster_dict = {}
        for i in range(n):
            root = find(i)
            if root not in cluster_dict:
                cluster_dict[root] = []
            cluster_dict[root].append(i)
        
        for cluster_indices in cluster_dict.values():
            cluster_atoms = [atoms[i] for i in cluster_indices]
            predicate = cluster_atoms[0].predicate.lower()
            predicate_clean = re.sub(r'[^a-z0-9]', '_', predicate)
            unique_suffix = uuid.uuid4().hex[:8]
            normalized_id = f"{predicate_clean}_{len(normalized)}_{unique_suffix}"
            
            representative = max(cluster_atoms, key=lambda a: a.confidence)
            
            normalized[normalized_id] = {
                "atoms": cluster_atoms,
                "representative": representative,
                "predicate": predicate
            }
        
        return normalized
    
    def _calculate_index_quality(self, normalized_index: Dict[str, Dict], is_local: bool = False) -> float:
        """计算索引质量
        
        Args:
            normalized_index: 归一化索引
            is_local: 是否为局部索引
            
        Returns:
            float: 质量分数（0-1）
        """
        if not normalized_index:
            return 0.0
        
        consistency_scores = []
        for normalized_id, data in normalized_index.items():
            atoms = data["atoms"]
            if len(atoms) < 2:
                continue
            
            if self.emb_model:
                texts = [a.atom_text for a in atoms]
                embeddings = self.emb_model.encode(texts, convert_to_tensor=True, show_progress_bar=False)
                embeddings = embeddings.cpu().numpy()
                norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
                normalized_emb = embeddings / (norms + 1e-12)
                
                similarities = []
                for i in range(len(atoms)):
                    for j in range(i + 1, len(atoms)):
                        sim = np.dot(normalized_emb[i], normalized_emb[j])
                        similarities.append(sim)
                
                if similarities:
                    consistency_scores.append(np.mean(similarities))
        
        consistency = np.mean(consistency_scores) if consistency_scores else 0.5
        
        normalized_concepts = len(normalized_index)
        total_atoms = sum(len(data["atoms"]) for data in normalized_index.values())
        
        if total_atoms > 0:
            # 归一化压缩比：归一化后概念数 / 原始原子数，越小越好
            # 转换为0-1分数：1 - (concepts / atoms)，归一化效果越好，分数越高
            compression_ratio = normalized_concepts / total_atoms
            coverage = max(0.0, 1.0 - compression_ratio)  # 归一化效果越好，coverage越高
        else:
            coverage = 0.0
        
        quality = (consistency * 0.7 + coverage * 0.3)
        return quality
    
    def _merge_to_global(self, local_normalized: Dict[str, Dict], local_quality: float) -> bool:
        """合并局部索引到全局索引
        
        Args:
            local_normalized: 局部归一化索引
            local_quality: 局部索引质量
            
        Returns:
            bool: 合并是否成功
        """
        if local_quality < 0.5:
            return False
        
        global_quality_before = self._calculate_index_quality(self.global_index, is_local=False)
        
        merged_count = 0
        for local_id, local_data in local_normalized.items():
            matched_global_id = self._find_similar_global_id(local_data["representative"])
            
            if matched_global_id:
                self.global_index[matched_global_id]["atoms"].extend(local_data["atoms"])
                all_atoms = self.global_index[matched_global_id]["atoms"]
                self.global_index[matched_global_id]["representative"] = max(all_atoms, key=lambda a: a.confidence)
                merged_count += 1
            else:
                global_id = f"global_{len(self.global_index)}"
                self.global_index[global_id] = {
                    "atoms": copy.deepcopy(local_data["atoms"]),
                    "representative": copy.deepcopy(local_data["representative"]),
                    "predicate": local_data["predicate"],  # 字符串，不需要深拷贝
                    "version": self.version + 1
                }
        
        global_quality_after = self._calculate_index_quality(self.global_index, is_local=False)
        
        if global_quality_before > 0:
            quality_drop = (global_quality_before - global_quality_after) / global_quality_before
        else:
            # 初始质量为0，任何合并都是质量提升
            quality_drop = -1.0 if global_quality_after > 0 else 0.0
        
        if quality_drop > (1 - self.quality_threshold):
            return False
        
        
        return True
    
    def _find_similar_global_id(self, atom: MAU) -> Optional[str]:
        """查找全局索引中相似的归一化ID
        
        Args:
            atom: 查询原子
            
        Returns:
            Optional[str]: 匹配的全局ID，如果没有返回None
        """
        if not self.emb_model or not self.global_index:
            return None
        
        global_representatives = []
        global_ids = []
        for global_id, data in self.global_index.items():
            if data["representative"]:
                global_representatives.append(data["representative"])
                global_ids.append(global_id)
        
        if not global_representatives:
            return None
        
        query_text = atom.atom_text
        candidate_texts = [r.atom_text for r in global_representatives]
        
        query_emb = self.emb_model.encode([query_text], convert_to_tensor=True, show_progress_bar=False)
        candidate_embs = self.emb_model.encode(candidate_texts, convert_to_tensor=True, show_progress_bar=False)
        
        query_emb = query_emb.cpu().numpy()
        candidate_embs = candidate_embs.cpu().numpy()
        
        query_norm = query_emb / (np.linalg.norm(query_emb, axis=1, keepdims=True) + 1e-12)
        candidate_norms = candidate_embs / (np.linalg.norm(candidate_embs, axis=1, keepdims=True) + 1e-12)
        
        similarities = np.dot(query_norm, candidate_norms.T)[0]
        max_idx = np.argmax(similarities)
        max_sim = similarities[max_idx]
        
        if max_sim >= 0.85:
            return global_ids[max_idx]
        
        return None
    
    def _save_global_state(self) -> Dict:
        """保存全局索引状态（用于回滚）"""
        return {
            "global_index": {k: {
                "atoms": copy.deepcopy(v["atoms"]),
                "representative": copy.deepcopy(v["representative"]),
                "predicate": v["predicate"],  # 字符串，不需要深拷贝
                "version": v.get("version", self.version)
            } for k, v in self.global_index.items()},
            "version": self.version
        }
    
    def _restore_global_state(self, state: Dict):
        """恢复全局索引状态（回滚）"""
        self.global_index = state["global_index"]
        self.version = state["version"]
    
    def finalize(self):
        """完成归一化（处理剩余批次和临时池）"""
        if self.current_batch:
            self._normalize_local_batch()
        
    
    def get_global_index(self) -> Dict[str, Dict]:
        """获取全局归一化索引"""
        return self.global_index
    
    def get_version_history(self) -> List[Dict]:
        """获取版本历史"""
        return self.version_history

class HardRuleFilter:
    """硬规则过滤：只过滤100%明显无意义的内容
    
    规则特点：
    - 高置信度：只过滤绝对不可能有语义的内容
    - 零误杀：确保不会误过滤有语义的内容
    - 规则精简：规则数量少但命中率高
    """
    
    def __init__(self):
        self.high_confidence_templates = [
            re.compile(r'^this study investigates$', re.IGNORECASE),
            re.compile(r'^results show that$', re.IGNORECASE),
            re.compile(r'^we discuss$', re.IGNORECASE),
            re.compile(r'^in this paper$', re.IGNORECASE),
            re.compile(r'^the following section$', re.IGNORECASE),
        ]
        
        self.section_markers = [
            'in conclusion',
            'the following section',
            'as mentioned above',
            'in summary',
            'to conclude'
        ]
    
    def check(self, atom: Dict) -> Tuple[bool, str]:
        """检查原子是否违反硬规则（支持 SRLEventUnit 转换后的原子）
        
        Args:
            atom: 原子字典（可能包含 srl_arguments 等 SRL 信息）
            
        Returns:
            (是否违反硬规则, 违反原因)
            - 如果违反：返回 (True, 原因字符串)
            - 如果不违反：返回 (False, "")
        """
        atom_text = atom.get("atom_text", "").strip()
        
        if not atom_text:
            return True, "empty_text"
        
        tokens = atom_text.split()
        if len(tokens) == 1:
            return True, "too_short_single_token"
        elif len(tokens) == 2:
            text_lower = atom_text.lower()
            if text_lower in ['this study', 'the paper', 'our work', 'this work']:
                return True, "too_short_generic_pair"
        
        if re.match(r'^[^\w\s]+$', atom_text):
            return True, "pure_symbol"
        
        if re.match(r'^(Fig\.|Figure|Table|Equation|Eq\.|Section|Sec\.)\s*\d+', atom_text, re.IGNORECASE):
            return True, "reference_marker"
        
        text_lower = atom_text.lower()
        for marker in self.section_markers:
            if marker in text_lower and len(tokens) <= 5:
                return True, "section_marker"
        
        for pattern in self.high_confidence_templates:
            if pattern.match(atom_text):
                return True, "template_phrase"
        
        if re.match(r'^[A-Z0-9\-_]+$', atom_text) and len(tokens) == 1:
            return True, "technical_id"
        
        # SRL 特殊处理：对于 predicate is None 但句子长度较长、含关键实体的 SRLEventUnit，仍然保留
        srl_arguments = atom.get("srl_arguments", {})
        srl_predicate = atom.get("srl_predicate")
        original_sentence = atom.get("original_sentence", "")
        
        # 如果没有谓词，但有关键实体和多个论元，且句子较长，不视为违反规则
        if not srl_predicate and srl_arguments:
            if len(srl_arguments) >= 2 and len(original_sentence) > 50:
                # 检查是否包含关键实体（适配列表结构：arguments是Dict[str, List[str]]）
                has_entities = False
                for arg_list in srl_arguments.values():
                    if isinstance(arg_list, list):
                        if any(len(arg) > 10 for arg in arg_list):
                            has_entities = True
                            break
                    else:
                        # 兼容旧格式（字符串）
                        if len(str(arg_list)) > 10:
                            has_entities = True
                            break
                if has_entities:
                    return False, ""  # 保留这种情况
        
        # 删除"必须有动词才保留"的规则（原规则已移除）
        # 现在允许没有谓词但有关键实体的 SRL 事件通过
        
        return False, ""


class SemanticStructureDetector:
    """语义结构检测器：判断原子是否具备基本语义结构
    
    检测目标：
    - 是否包含"实体 + 动作/关系"
    - 是否存在完整谓词结构（主/谓/宾）
    - 是否表达了某种明确关系（比较、因果、条件、描述）
    """
    
    def __init__(self, nlp_model, emb_model=None):
        self.nlp = nlp_model
        self.emb_model = emb_model
        self.structure_patterns = {
            'entity_action': re.compile(
                r'\b\w+\s+(?:increases?|decreases?|affects?|improves?|reduces?|enhances?|inhibits?|promotes?)\s+\w+',
                re.IGNORECASE
            ),
            'causal': re.compile(
                r'\b(?:leads? to|causes?|results? in|due to|because of|owing to)\b',
                re.IGNORECASE
            ),
            'conditional': re.compile(
                r'\b(?:when|if|under|given|provided that)\s+\w+',
                re.IGNORECASE
            ),
            'comparative': re.compile(
                r'\b(?:better than|higher than|more than|compared to|superior to|inferior to)\b',
                re.IGNORECASE
            ),
            'descriptive': re.compile(
                r'\b(?:characterized by|defined as|consists of|composed of)\b',
                re.IGNORECASE
            )
        }
    
    def detect_structure(self, atom: Dict, original_sentence: str = None) -> Dict:
        """检测语义结构
        
        Args:
            atom: 原子字典
            original_sentence: 原始句子（可选，用于增强检测）
            
        Returns:
            {
                'has_structure': bool,
                'structure_type': str,
                'completeness_score': float,
                'reason': str
            }
        """
        atom_text = atom.get("atom_text", "")
        
        has_agent = atom.get("agent") is not None
        has_patient = atom.get("patient") is not None
        has_verb = atom.get("verb_lemma") is not None
        relation_type = atom.get("relation_type")
        has_subject = atom.get("has_subject", False)
        has_object = atom.get("has_object", False)
        
        if has_verb and (has_agent or has_patient or has_subject or has_object):
            completeness = 0.6
            if (has_agent and has_patient) or (has_subject and has_object):
                completeness = 0.9
            elif has_agent or has_patient or has_subject or has_object:
                completeness = 0.7
            if relation_type:
                completeness = min(1.0, completeness + 0.1)
            
            structure_type = relation_type if relation_type else 'entity_action'
            
            return {
                'has_structure': True,
                'structure_type': structure_type,
                'completeness_score': completeness,
                'reason': 'has_agent_patient_verb'
            }
        
        if original_sentence:
            doc = self.nlp(original_sentence)
            has_predicate = any(token.pos_ == 'VERB' for token in doc)
            has_entity = any(token.ent_type_ for token in doc) or \
                        any(token.pos_ in ['NOUN', 'PROPN'] for token in doc)
            has_relation = any(
                pattern.search(original_sentence) 
                for pattern in self.structure_patterns.values()
            )
            
            if has_predicate and (has_entity or has_relation):
                detected_type = 'inferred'
                for stype, pattern in self.structure_patterns.items():
                    if pattern.search(original_sentence):
                        detected_type = stype
                        break
                    
                    completeness = 0.6
                    if has_entity and has_predicate:
                        completeness = 0.7
                    if has_relation:
                        completeness = min(1.0, completeness + 0.2)
                    
                    return {
                        'has_structure': True,
                        'structure_type': detected_type,
                        'completeness_score': completeness,
                        'reason': 'inferred_from_sentence'
                    }
        
        for stype, pattern in self.structure_patterns.items():
            if pattern.search(atom_text):
                return {
                    'has_structure': True,
                    'structure_type': stype,
                    'completeness_score': 0.65,
                    'reason': 'pattern_match'
                }
        
        if self.emb_model:
            structure_score = self._embedding_based_structure_detection(atom_text)
            if structure_score > 0.5:
                return {
                    'has_structure': True,
                    'structure_type': 'semantic',
                    'completeness_score': structure_score,
                    'reason': 'embedding_based'
                }
        
        return {
            'has_structure': False,
            'structure_type': 'none',
            'completeness_score': 0.0,
            'reason': 'no_structure_detected'
        }
    
    def _embedding_based_structure_detection(self, text: str) -> float:
        if not self.emb_model or not text:
            return 0.0
        
        structure_templates = [
            "X affects Y",
            "X leads to Y",
            "X improves Y",
            "X reduces Y",
            "X causes Y",
            "X increases Y",
            "X decreases Y",
            "When X occurs, Y happens",
            "X is better than Y",
            "X consists of Y"
        ]
        
        text_emb = self.emb_model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
        template_embs = self.emb_model.encode(
            structure_templates, 
            convert_to_numpy=True, 
            normalize_embeddings=True
        )
        
        similarities = np.dot(template_embs, text_emb)
        max_sim = float(np.max(similarities))
        normalized_score = (max_sim + 1) / 2
        
        return normalized_score


class SemanticGranularityQuantifier:
    """语义颗粒度量化器：计算具体性、信息增量、结构饱和度
    
    三个维度：
    1. 具体性（Specificity）：是否提到具体对象、范围、条件
    2. 信息增量（Information Gain）：是否表达新知识，而不是空泛套话
    3. 结构饱和度（Semantic Saturation）：三元组数量（实体、关系、属性）
    """
    
    def __init__(self, emb_model, nlp_model=None):
        self.emb_model = emb_model
        self.nlp = nlp_model
        self.generic_phrases = set([
            'important', 'significant', 'effective', 'efficient',
            'widely used', 'commonly', 'generally', 'typically',
            'often', 'usually', 'frequently', 'sometimes'
        ])
        self.empty_phrases = [
            'is important', 'plays a role', 'is widely used',
            'has implications', 'is significant', 'is crucial',
            'is essential', 'is necessary', 'is relevant',
            'contributes to', 'relates to', 'associated with'
        ]
        self.specificity_enhancers = [
            r'\d+%',
            r'\d+\.\d+',
            r'\b\d+\s*(?:times|fold|percent|%)',
            r'\b(?:under|when|if|given|provided that)\s+\w+',
            r'\b(?:in|at|during|within)\s+\w+',
        ]
    
    def quantify(self, atom: Dict, context_atoms: List[Dict] = None) -> Dict:
        """量化语义颗粒度
        
        Args:
            atom: 原子字典
            context_atoms: 上下文原子列表（用于计算信息增量，可选）
            
        Returns:
            {
                'specificity': float,
                'information_gain': float,
                'saturation': float,
                'overall_quality': float
            }
        """
        specificity = self._calculate_specificity(atom)
        information_gain = self._calculate_information_gain(atom, context_atoms)
        saturation = self._calculate_saturation(atom)
        
        overall_quality = (
            specificity * 0.4 +
            information_gain * 0.3 +
            saturation * 0.3
        )
        
        return {
            'specificity': specificity,
            'information_gain': information_gain,
            'saturation': saturation,
            'overall_quality': overall_quality
        }
    
    def _calculate_specificity(self, atom: Dict) -> float:
        """计算具体性（基于语义对比，而非结构标签）
        
        改进：不依赖agent/patient存在性，而是基于：
        1. 文本熵（信息量）
        2. 与通用模板的语义距离
        3. 实体密度
        """
        atom_text = atom.get("atom_text", "").lower()
        score = 0.0
        
        words = atom_text.split()
        if len(words) >= 3:
            score += 0.3
        if len(words) >= 5:
            score += 0.2
        
        if self.emb_model:
            generic_templates = [
                "this study shows that",
                "we found that",
                "results indicate that",
                "it is shown that"
            ]
            atom_emb = self.emb_model.encode(atom_text, convert_to_numpy=True, normalize_embeddings=True)
            template_embs = self.emb_model.encode(
                generic_templates,
                convert_to_numpy=True,
                normalize_embeddings=True
            )
            similarities = np.dot(template_embs, atom_emb)
            max_sim = float(np.max(similarities))
            # 距离越远（相似度越低），具体性越高
            specificity_from_distance = 1.0 - max_sim
            score += specificity_from_distance * 0.3
        
        if self.nlp:
            doc = self.nlp(atom_text)
            noun_count = sum(1 for token in doc if token.pos_ in ['NOUN', 'PROPN'])
            verb_count = sum(1 for token in doc if token.pos_ == 'VERB')
            total_tokens = len(doc)
            if total_tokens > 0:
                entity_density = (noun_count + verb_count) / total_tokens
                score += entity_density * 0.2
        
        for pattern in self.specificity_enhancers:
            if re.search(pattern, atom_text):
                score += 0.2
                break
        
        generic_count = sum(1 for phrase in self.generic_phrases if phrase in atom_text)
        score -= generic_count * 0.1
        
        score = max(0.0, min(1.0, score))
        return score
    
    def _calculate_information_gain(self, atom: Dict, context_atoms: List[Dict] = None) -> float:
        atom_text = atom.get("atom_text", "").lower()
        score = 1.0
        
        for phrase in self.empty_phrases:
            if phrase in atom_text:
                score -= 0.5
                break
        
        if context_atoms and self.emb_model:
            similarities = []
            for ctx_atom in context_atoms[:5]:
                ctx_text = ctx_atom.get("atom_text", "")
                if ctx_text:
                    sim = self._calculate_similarity(atom_text, ctx_text)
                    similarities.append(sim)
            
            if similarities:
                avg_sim = sum(similarities) / len(similarities)
                if avg_sim > 0.8:
                    score -= 0.3
                elif avg_sim > 0.6:
                    score -= 0.15
        
        has_specific_info = (
            atom.get("agent") is not None or
            atom.get("patient") is not None or
            re.search(r'\d+', atom_text)
        )
        if has_specific_info:
            score += 0.2
        
        score = max(0.0, min(1.0, score))
        return score
    
    def _calculate_saturation(self, atom: Dict) -> float:
        """计算结构饱和度（基于语义完整性，而非结构标签）
        
        改进：不依赖agent/patient存在性，而是基于：
        1. 语义完整性（通过embedding与完整模板的相似度）
        2. 文本结构复杂度
        3. 信息密度
        """
        score = 0.0
        atom_text = atom.get("atom_text", "")
        
        if self.emb_model and atom_text:
            complete_templates = [
                "X affects Y",
                "X leads to Y",
                "X improves Y",
                "X causes Y",
                "X increases Y"
            ]
            atom_emb = self.emb_model.encode(atom_text, convert_to_numpy=True, normalize_embeddings=True)
            template_embs = self.emb_model.encode(
                complete_templates,
                convert_to_numpy=True,
                normalize_embeddings=True
            )
            similarities = np.dot(template_embs, atom_emb)
            max_sim = float(np.max(similarities))
            score += max_sim * 0.4
        
        if self.nlp:
            doc = self.nlp(atom_text)
            pos_tags = set(token.pos_ for token in doc)
            pos_diversity = len(pos_tags) / 10.0  # 归一化
            score += min(0.3, pos_diversity)
            
            if len(doc) > 0:
                max_depth = max(
                    (len(list(token.ancestors)) for token in doc),
                    default=0
                )
                depth_score = min(0.2, max_depth / 5.0)
                score += depth_score
        
        words = atom_text.lower().split()
        relation_words = ['affects', 'leads', 'causes', 'improves', 'increases', 
                         'reduces', 'decreases', 'enhances', 'inhibits']
        relation_count = sum(1 for word in words if word in relation_words)
        if relation_count > 0:
            score += min(0.2, relation_count * 0.1)
        
        relation_type = atom.get("relation_type")
        if relation_type:
            score += 0.1
        
        return min(1.0, score)
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算相似度"""
        return calculate_similarity(text1, text2, self.emb_model)


class SentenceEventClassifier:
    """句子级事件分类器：使用语义embedding + 线性分类器替代关键词匹配
    
    核心改进：
    - 基于BGE-M3 embedding进行语义理解
    - 使用类别模板的embedding作为分类基准
    - 输出每个类别的概率分数（而非0/1硬匹配）
    """
    
    def __init__(self, emb_model, device='cuda'):
        """初始化事件分类器
        
        Args:
            emb_model: SentenceTransformer模型（BGE-M3）
            device: 计算设备
        """
        self.emb_model = emb_model
        self.device = device
        
        self.category_templates = {
            "AIM": [
                "This study aims to investigate",
                "We propose a new method",
                "The objective of this paper is",
                "This work presents",
                "We introduce a novel approach",
                "The goal is to develop",
                "This paper addresses the problem of",
                "We aim to solve"
            ],
            "CONCLUSION": [
                "Results show that",
                "We conclude that",
                "The findings demonstrate",
                "This indicates that",
                "The results reveal",
                "We found that",
                "This suggests that",
                "The data shows"
            ],
            "METHOD": [
                "We used the following method",
                "The dataset consists of",
                "We performed experiments",
                "The experimental setup",
                "We employed a technique",
                "The methodology involves",
                "We applied the following approach",
                "The procedure includes"
            ],
            "OBSERVATION": [
                "We observed that",
                "It was found that",
                "The analysis reveals",
                "We noticed that",
                "The evidence shows"
            ],
            "BACKGROUND": [
                "Previous studies have shown",
                "It is well known that",
                "The literature suggests",
                "Previous work has demonstrated",
                "Existing research indicates"
            ]
        }
        
        self.template_embeddings = {}
        for category, templates in self.category_templates.items():
            embs = self.emb_model.encode(
                templates,
                convert_to_tensor=True,
                normalize_embeddings=True,
                show_progress_bar=False
            )
            self.template_embeddings[category] = embs
    
    def classify(self, text: str, return_probs: bool = True) -> Dict[str, float]:
        """对文本进行事件分类
        
        Args:
            text: 输入文本（句子或原子）
            return_probs: 是否返回概率分数（True）或仅返回最高类别（False）
            
        Returns:
            Dict[str, float]: 每个类别的分数
        """
        if not text or not text.strip():
            return {"AIM": 0.0, "CONCLUSION": 0.0, "METHOD": 0.0, 
                   "OBSERVATION": 0.0, "BACKGROUND": 0.0}
        
        # 获取文本embedding
        text_emb = self.emb_model.encode(
            text,
            convert_to_tensor=True,
            normalize_embeddings=True,
            show_progress_bar=False
        )
        
        category_scores = {}
        for category, template_embs in self.template_embeddings.items():
            similarities = torch.nn.functional.cosine_similarity(
                text_emb.unsqueeze(0),
                template_embs,
                dim=1
            )
            max_sim = torch.max(similarities).item()
            avg_sim = torch.mean(similarities).item()
            category_scores[category] = max_sim * 0.7 + avg_sim * 0.3
        
        normalized_scores = {}
        for category, score in category_scores.items():
            normalized = (score + 1) / 2
            normalized_scores[category] = float(normalized)
        if return_probs:
            return {
                "AIM": normalized_scores.get("AIM", 0.0),
                "CONCLUSION": normalized_scores.get("CONCLUSION", 0.0),
                "METHOD": normalized_scores.get("METHOD", 0.0),
                "OBSERVATION": normalized_scores.get("OBSERVATION", 0.0),
                "BACKGROUND": normalized_scores.get("BACKGROUND", 0.0)
            }
        else:
            best_category = max(normalized_scores.items(), key=lambda x: x[1])[0]
            return {best_category: normalized_scores[best_category]}
    
    def classify_batch(self, texts: List[str]) -> List[Dict[str, float]]:
        """批量分类
        
        Args:
            texts: 文本列表
            
        Returns:
            List[Dict[str, float]]: 每个文本的分类结果
        """
        if not texts:
            return []
        text_embs = self.emb_model.encode(
            texts,
            convert_to_tensor=True,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=32
        )
        
        results = []
        for text_emb in text_embs:
            category_scores = {}
            for category, template_embs in self.template_embeddings.items():
                similarities = torch.nn.functional.cosine_similarity(
                    text_emb.unsqueeze(0),
                    template_embs,
                    dim=1
                )
                max_sim = torch.max(similarities).item()
                avg_sim = torch.mean(similarities).item()
                score = max_sim * 0.7 + avg_sim * 0.3
                normalized = (score + 1) / 2
                category_scores[category] = float(normalized)
            
            results.append({
                "AIM": category_scores.get("AIM", 0.0),
                "CONCLUSION": category_scores.get("CONCLUSION", 0.0),
                "METHOD": category_scores.get("METHOD", 0.0),
                "OBSERVATION": category_scores.get("OBSERVATION", 0.0),
                "BACKGROUND": category_scores.get("BACKGROUND", 0.0)
            })
        
        return results


class ResearchInsightMiner:
    def __init__(self, device: str = None):
        """初始化全流程 GPU 流水线
        
        Args:
            device: 设备名称，如果为None则自动检测并使用GPU
            
        Raises:
            RuntimeError: 如果GPU不可用
        """
        if device is None:
            if not torch.cuda.is_available():
                raise RuntimeError(
                    "GPU不可用！系统要求使用GPU运行。\n"
                    "请检查：\n"
                    "1. CUDA是否正确安装\n"
                    "2. PyTorch是否支持CUDA\n"
                    "3. GPU驱动是否正常\n"
                    "可以使用以下命令检查：\n"
                    "  - nvidia-smi\n"
                    "  - python -c 'import torch; print(torch.cuda.is_available())'"
                )
            device = 'cuda'
        
        if device != 'cuda':
            raise RuntimeError(f"系统仅支持GPU模式，不支持设备: {device}")
        
        if not torch.cuda.is_available():
            raise RuntimeError("GPU不可用，无法初始化系统")
        
        self.device = device

        spacy.require_gpu()
        
        self.coref_model = FCoref(device=self.device)
        self.nlp = spacy.load("en_core_web_trf")

        self.nli_model = CrossEncoder('cross-encoder/nli-deberta-v3-large', device=self.device)
        
        # 候选匹配专用的Cross-encoder（用于两段式评分链路的第二段）
        # 阶段3第一版：使用轻量级模型（速度快，显存压力小）
        # 后续优化方向：可升级为更重的模型（如 cross-encoder/ms-marco-electra-base）以提升质量
        # 配置参数：可通过环境变量 CANDIDATE_MATCHER_MODEL 指定模型
        candidate_matcher_model = os.environ.get(
            'CANDIDATE_MATCHER_MODEL', 
            'cross-encoder/ms-marco-MiniLM-L-6-v2'  # 默认轻量级
        )
        try:
            self.candidate_matcher = CrossEncoder(candidate_matcher_model, device=self.device)
            print(f"[初始化] 候选匹配Cross-encoder已加载: {candidate_matcher_model}")
        except Exception as e:
            error_msg = (
                f"无法加载候选匹配Cross-encoder模型: {candidate_matcher_model}\n"
                f"设备: {self.device}\n"
                f"错误详情: {str(e)}\n"
                f"可能原因:\n"
                f"  1. 网络连接问题，无法下载模型\n"
                f"  2. 模型路径不存在或无效\n"
                f"  3. 设备资源不足（显存/内存）\n"
                f"  4. 模型文件损坏\n"
                f"建议:\n"
                f"  - 检查网络连接或使用镜像站点（设置 HF_ENDPOINT 环境变量）\n"
                f"  - 检查设备资源是否充足\n"
                f"  - 验证模型名称是否正确"
            )
            raise RuntimeError(error_msg) from e
        
        self.hypotheses = {
            "AIM": "This study aims to investigate a specific problem or proposes a new method.",
            "CONCLUSION": "This sentence presents a key finding, result, or conclusion of the research.",
            "METHOD": "This sentence describes the methodology, dataset, or experimental setup."
        }
        
        self.theme_hypotheses = {
            "BACKGROUND": "This sentence provides background knowledge, context, or established facts in the field.",
            "GAP": "This sentence identifies a research gap, limitation, or unknown problem.",
            "FINDING": "This sentence presents a key discovery, result, or finding of this research.",
            "MECHANISM": "This sentence explains the mechanism, process, or how something works.",
            "SIGNIFICANCE": "This sentence describes the significance, impact, or implications of the research."
        }
        
        self.atom_type_to_theme_roles = {
            "FACT": ["BACKGROUND"],
            "ATTRIBUTE": ["BACKGROUND", "MECHANISM"],
            "ACTION": ["FINDING", "MECHANISM"],
            "RELATION": ["MECHANISM"],
            "QUANTITY": ["FINDING"],
            "CONTEXT": ["BACKGROUND", "GAP"]
        }
        
        self.significance_verbs = {
            "important", "crucial", "essential", "critical", "significant", "valuable",
            "beneficial", "advantageous", "effective", "efficient", "superior", "outperform"
        }
        
        self.causal_markers = {
            "cause", "lead", "result", "produce", "generate", "induce", "trigger", "drive",
            "because", "due to", "as a result", "consequently", "therefore", "thus"
        }
        self.conditional_markers = {
            "when", "if", "whenever", "provided", "assuming", "given that"
        }
        self.contrast_markers = {
            "however", "but", "although", "though", "despite", "whereas", "while", "yet"
        }
        
        self.explicit_gap_markers = {
            "unknown", "unclear", "unexplored", "uninvestigated", "remains unclear",
            "little is known", "not well understood", "poorly understood", "lacks"
        }
        self.implicit_gap_markers = {
            "debated", "controversial", "remains", "still", "yet to be", "needs further",
            "requires investigation", "open question", "unresolved", "inconclusive"
        }

        self.emb_model = SentenceTransformer('BAAI/bge-m3', device=self.device)
        
        # 初始化embedding缓存（LRU缓存，最大10000条）
        self._embedding_cache = {}
        self._embedding_cache_max_size = 10000
        
        # 初始化SEM分类器的类别描述（零样本分类）
        self.sem_category_descriptions = {
            "AIM": [
                "The research objective or goal",
                "What the paper aims to achieve",
                "The purpose of the study",
                "Research question or hypothesis",
                "The objective is to investigate",
                "We propose a new method",
                "The goal of this paper"
            ],
            "CONCLUSION": [
                "Research findings or results",
                "What was discovered or proven",
                "The outcome of the study",
                "Key conclusions drawn",
                "Results show that",
                "We conclude that",
                "Therefore the findings indicate"
            ],
            "METHOD": [
                "The experimental approach used",
                "Data collection or analysis method",
                "Technical procedure or algorithm",
                "How the research was conducted",
                "We utilized a dataset",
                "The experiment was performed",
                "The methodology involves"
            ]
        }
        
        # 预计算类别描述的embedding（用于零样本分类）
        self.sem_category_embeddings = {}
        for k, descriptions in self.sem_category_descriptions.items():
            self.sem_category_embeddings[k] = self.emb_model.encode(
                descriptions, 
                convert_to_tensor=True, 
                normalize_embeddings=True
            )
        
        # 保留原有anchors作为备选（向后兼容）
        self.anchors = {
            "AIM": self.emb_model.encode(["The objective is", "We propose", "The goal of this paper"], convert_to_tensor=True),
            "CONCLUSION": self.emb_model.encode(["Results show", "We conclude", "Therefore"], convert_to_tensor=True),
            "METHOD": self.emb_model.encode(["We utilized", "The dataset", "The experiment"], convert_to_tensor=True)
        }

        self.srl_module = SRLModule(self.nlp, device=self.device)  # 初始化 SRL 模块（唯一提取路径）
        self.hierarchical_clustering = HierarchicalEmbeddingClustering(self.emb_model)
        
        self.cross_doc_normalizer = CrossDocumentNormalizer(
            emb_model=self.emb_model,
            local_batch_size=100,
            quality_threshold=0.95
        )
        
        self.weight_model = LearnableWeightModel()
        
        self.agg_layer = SimpleAggregationLayer(self.emb_model, weight_model=self.weight_model)
        self.low_conf_handler = LowConfidenceHandler(threshold=0.5)
        
        self.confidence_model = None
        

        
        self.prep_to_role = {
            "of": "patient",
            "by": "agent",
            "with": "instrument",
            "on": "target",
            "in": "location",
            "for": "purpose",
            "to": "recipient"
        }
        
        self.atom_stats = {
            "total_atoms": 0,
            "valid_atoms": 0,
            "invalid_atoms": 0,
            "atoms_with_inherited_subject": 0,
            "nominalization_atoms": 0,
            "action_only_atoms": 0
        }
        
        self.lemma_group_map = self._build_lemma_group_map()
        
        self.hypernym_cache = {}
        
        self.concept_graph = defaultdict(set)
        
        if HAS_WORDNET:
            pass
        
        self.hard_rule_filter = HardRuleFilter()
        self.structure_detector = SemanticStructureDetector(self.nlp, self.emb_model)
        self.quality_quantifier = SemanticGranularityQuantifier(self.emb_model, self.nlp)
        
        # 初始化事件分类器（替代关键词匹配）
        self.event_classifier = SentenceEventClassifier(self.emb_model, device=self.device)
        
        # 已有事件向量池（用于候选合并）
        # 阶段3第一版：使用内存池（最近活跃事件cache）
        # 后续优化方向：需要持久化索引（FAISS/LanceDB）存储全局高频事件
        #   - existing_events_pool：最近活跃的cache（快速访问）
        #   - 持久化索引：全局事件账本（低频访问，但覆盖全量）
        self.existing_events_pool: List[Dict] = []  # 存储已有事件的embedding和文本
        # 可配置池大小（带验证和异常处理）
        try:
            pool_size_raw = int(os.environ.get('EXISTING_EVENTS_POOL_SIZE', '1000'))
            self.existing_events_max_size = max(100, min(10000, pool_size_raw))  # 限制在100-10000之间
            if pool_size_raw != self.existing_events_max_size:
                print(f"[警告] EXISTING_EVENTS_POOL_SIZE={pool_size_raw} 超出范围[100, 10000]，已限制为 {self.existing_events_max_size}")
        except (ValueError, TypeError) as e:
            print(f"[警告] EXISTING_EVENTS_POOL_SIZE 配置无效: {e}，使用默认值1000")
            self.existing_events_max_size = 1000
        
        # 融合权重配置（在初始化时读取一次，避免每次调用都读取环境变量）
        try:
            embedding_weight_raw = float(os.environ.get('EMBEDDING_WEIGHT', '0.6'))
            # 验证权重范围 [0, 1]
            self.embedding_weight = max(0.0, min(1.0, embedding_weight_raw))
            self.cross_encoder_weight = 1.0 - self.embedding_weight
            if embedding_weight_raw != self.embedding_weight:
                print(f"[警告] EMBEDDING_WEIGHT={embedding_weight_raw} 超出范围[0, 1]，已限制为 {self.embedding_weight}")
        except (ValueError, TypeError) as e:
            print(f"[警告] EMBEDDING_WEIGHT 配置无效: {e}，使用默认值0.6")
            self.embedding_weight = 0.6
            self.cross_encoder_weight = 0.4
        
        # 候选相似度与原型相似度的融合权重（可配置，默认0.7/0.3）
        try:
            candidate_weight_raw = float(os.environ.get('CANDIDATE_SIMILARITY_WEIGHT', '0.7'))
            self.candidate_similarity_weight = max(0.0, min(1.0, candidate_weight_raw))
            self.prototype_similarity_weight = 1.0 - self.candidate_similarity_weight
        except (ValueError, TypeError) as e:
            print(f"[警告] CANDIDATE_SIMILARITY_WEIGHT 配置无效: {e}，使用默认值0.7")
            self.candidate_similarity_weight = 0.7
            self.prototype_similarity_weight = 0.3
        
        # 初始化事件账本系统
        self.event_ledger = EventLedger()
        self.event_ledger_updater = EventLedgerExperimentalUpdater(
            self.event_ledger,
            sim_threshold=EVENT_LEDGER_SIM_THRESHOLD
        )
        self.event_ledger_worker = EventLedgerWorker(
            self.event_ledger_updater,
            batch_size=EVENT_LEDGER_BATCH_SIZE
        )
        self.event_ledger_worker.start()
        print(f"[初始化] 事件账本系统已启动（相似度阈值: {EVENT_LEDGER_SIM_THRESHOLD}）")

    def _encode_with_cache(self, texts, convert_to_tensor=True, convert_to_numpy=False, normalize_embeddings=True, force_recompute=False):
        """使用缓存的embedding编码方法
        
        Args:
            texts: 文本列表或单个文本
            convert_to_tensor: 是否转换为tensor
            convert_to_numpy: 是否转换为numpy数组
            normalize_embeddings: 是否归一化
            force_recompute: 是否强制重新计算
            
        Returns:
            embedding结果（tensor或numpy数组）
        """
        # 统一处理单个文本和文本列表
        is_single = isinstance(texts, str)
        if is_single:
            texts = [texts]
        
        # 检查缓存
        uncached_texts = []
        uncached_indices = []
        results = [None] * len(texts)
        
        if not force_recompute:
            for i, text in enumerate(texts):
                text_key = text.strip() if text else ""
                if text_key in self._embedding_cache:
                    results[i] = self._embedding_cache[text_key]
                else:
                    uncached_texts.append(text)
                    uncached_indices.append(i)
        else:
            uncached_texts = texts
            uncached_indices = list(range(len(texts)))
        
        # 批量编码未缓存的文本
        if uncached_texts:
            new_embs = self.emb_model.encode(
                uncached_texts,
                convert_to_tensor=convert_to_tensor,
                convert_to_numpy=convert_to_numpy,
                normalize_embeddings=normalize_embeddings,
                show_progress_bar=False
            )
            
            # 存储到缓存
            for idx, text, emb in zip(uncached_indices, uncached_texts, new_embs):
                text_key = text.strip() if text else ""
                if text_key:
                    # 简单的LRU淘汰：如果超过最大大小，删除最旧的（随机删除一个）
                    if len(self._embedding_cache) >= self._embedding_cache_max_size:
                        # 删除一个随机项（简单实现）
                        oldest_key = next(iter(self._embedding_cache))
                        del self._embedding_cache[oldest_key]
                    self._embedding_cache[text_key] = emb
                results[idx] = emb
        
        # 转换为tensor或numpy（如果需要）
        if convert_to_tensor and not isinstance(results[0], torch.Tensor):
            results = [torch.tensor(r) if not isinstance(r, torch.Tensor) else r for r in results]
        elif convert_to_numpy and not isinstance(results[0], np.ndarray):
            results = [r.cpu().numpy() if isinstance(r, torch.Tensor) else np.array(r) for r in results]
        
        # 堆叠结果
        if len(results) == 1 and is_single:
            return results[0]
        elif convert_to_tensor:
            return torch.stack(results) if results else torch.empty((0,))
        elif convert_to_numpy:
            return np.stack(results) if results else np.empty((0,))
        else:
            return results[0] if is_single else results

    def _classify_sem_zero_shot(self, atom_text: str) -> Dict[str, float]:
        """零样本SEM分类器：使用丰富的类别描述进行语义分类
        
        Args:
            atom_text: 原子文本
            
        Returns:
            Dict[str, float]: 每个类别的概率分数（0.0-1.0）
        """
        if not atom_text or not atom_text.strip():
            return {"AIM": 0.0, "CONCLUSION": 0.0, "METHOD": 0.0}
        
        # 计算原子文本的embedding
        atom_emb = self._encode_with_cache(
            atom_text, 
            convert_to_tensor=True, 
            normalize_embeddings=True
        )
        
        # 如果返回的是列表，取第一个
        if isinstance(atom_emb, list):
            atom_emb = atom_emb[0]
        if not isinstance(atom_emb, torch.Tensor):
            atom_emb = torch.tensor(atom_emb)
        if atom_emb.dim() == 1:
            atom_emb = atom_emb.unsqueeze(0)
        
        # 确保在正确的设备上
        if atom_emb.device != torch.device(self.device):
            atom_emb = atom_emb.to(self.device)
        
        scores = {}
        for category, desc_embs in self.sem_category_embeddings.items():
            # 确保类别描述embedding在正确的设备上
            if desc_embs.device != torch.device(self.device):
                desc_embs = desc_embs.to(self.device)
            
            # 计算与所有类别描述的相似度
            similarities = torch.nn.functional.cosine_similarity(
                atom_emb.unsqueeze(1), 
                desc_embs.unsqueeze(0), 
                dim=2
            )
            # 取平均相似度（也可以取最大值）
            avg_sim = similarities.mean().item()
            max_sim = similarities.max().item()
            # 使用加权平均（70%最大值 + 30%平均值）以提高稳定性
            scores[category] = 0.7 * max_sim + 0.3 * avg_sim
        
        # 归一化为概率分布（softmax风格，但使用原始分数范围）
        # 将分数从[-1, 1]映射到[0, 1]，然后归一化
        normalized_scores = {k: (v + 1) / 2 for k, v in scores.items()}
        total = sum(normalized_scores.values())
        if total > 0:
            normalized_scores = {k: v / total for k, v in normalized_scores.items()}
        else:
            # 如果总分为0，均匀分布
            normalized_scores = {k: 1.0 / len(scores) for k in scores.keys()}
        
        return normalized_scores

    def _two_stage_scoring(self, new_text: str, candidate_texts: List[str], 
                          prototype_embeddings: Optional[torch.Tensor] = None,
                          top_k: int = 10) -> Dict[str, float]:
        """两段式评分链路
        
        第一段：BGE embedding计算与原型/已有事件的相似度（粗粒度筛选）
        第二段：Cross-encoder对top-k候选进行精确匹配
        
        Args:
            new_text: 新句子/原子文本
            candidate_texts: 候选文本列表（已有事件或原型）
            prototype_embeddings: 原型向量（可选，用于第一段）
            top_k: 第二段处理的候选数量（默认10）
            
        Returns:
            Dict[str, float]: 每个候选的匹配分数
        """
        if not candidate_texts:
            return {}
        
        # 确保top_k不超过候选数量
        top_k = min(top_k, len(candidate_texts))
        if top_k <= 0:
            return {}
        
        # 第一段：BGE embedding计算相似度
        new_emb = self._encode_with_cache(
            new_text,
            convert_to_tensor=True,
            normalize_embeddings=True
        )
        if isinstance(new_emb, list):
            new_emb = new_emb[0]
        if not isinstance(new_emb, torch.Tensor):
            new_emb = torch.tensor(new_emb)
        if new_emb.dim() == 1:
            new_emb = new_emb.unsqueeze(0)
        if new_emb.device != torch.device(self.device):
            new_emb = new_emb.to(self.device)
        
        # 计算与候选的embedding相似度
        candidate_embs = self._encode_with_cache(
            candidate_texts,
            convert_to_tensor=True,
            normalize_embeddings=True
        )
        if not isinstance(candidate_embs, torch.Tensor):
            candidate_embs = torch.tensor(candidate_embs)
        if candidate_embs.device != torch.device(self.device):
            candidate_embs = candidate_embs.to(self.device)
        # 确保candidate_embs是二维的 [n_candidates, emb_dim]
        if candidate_embs.dim() == 1:
            candidate_embs = candidate_embs.unsqueeze(0)
        
        # 计算余弦相似度
        similarities = torch.nn.functional.cosine_similarity(
            new_emb.unsqueeze(1),
            candidate_embs.unsqueeze(0),
            dim=2
        ).squeeze(0).cpu().numpy()
        
        # 确保similarities数组有效
        if len(similarities) == 0:
            return {}
        
        # 如果提供了原型向量，也计算与原型的相似度
        if prototype_embeddings is not None:
            if prototype_embeddings.device != torch.device(self.device):
                prototype_embeddings = prototype_embeddings.to(self.device)
            proto_similarities = torch.nn.functional.cosine_similarity(
                new_emb.unsqueeze(1),
                prototype_embeddings.unsqueeze(0),
                dim=2
            ).squeeze(0).cpu().numpy()
            # 融合候选相似度和原型相似度（使用可配置权重）
            # 注意：proto_similarities是每个原型与new_text的相似度，取最大值作为整体原型相似度
            # 然后广播到所有候选（因为原型相似度对所有候选都是相同的）
            if len(proto_similarities) > 0:
                max_proto_sim = float(np.max(proto_similarities))
                similarities = self.candidate_similarity_weight * similarities + self.prototype_similarity_weight * max_proto_sim
        
        # 选择top-k候选进入第二段
        top_k_indices = np.argsort(similarities)[-top_k:][::-1]
        # 确保索引有效
        top_k_indices = [idx for idx in top_k_indices if idx < len(candidate_texts) and idx < len(similarities)]
        if not top_k_indices:
            # 如果没有有效索引，返回所有候选的embedding分数（归一化到[0, 1]范围）
            return {candidate: max(0.0, min(1.0, (float(similarities[i]) + 1) / 2)) 
                    for i, candidate in enumerate(candidate_texts) if i < len(similarities)}
        top_k_candidates = [candidate_texts[i] for i in top_k_indices]
        
        # 第二段：Cross-encoder精确匹配
        cross_encoder_scores = {}
        if top_k_candidates:
            pairs = [[new_text, candidate] for candidate in top_k_candidates]
            try:
                ce_scores = self.candidate_matcher.predict(pairs, batch_size=min(16, len(pairs)), show_progress_bar=False)
                if isinstance(ce_scores, (list, tuple)):
                    ce_scores = np.array(ce_scores)
                elif isinstance(ce_scores, torch.Tensor):
                    ce_scores = ce_scores.cpu().numpy()
                else:
                    ce_scores = np.array(ce_scores)
                
                # 归一化到[0, 1]范围（Cross-encoder输出可能是logits）
                if len(ce_scores) == 0:
                    # 如果Cross-encoder返回空结果，跳过第二段
                    ce_scores = np.array([])
                elif ce_scores.ndim > 1:
                    # 检查第二维是否为空（防止形状为[1, 0]等异常情况）
                    if ce_scores.shape[1] == 0:
                        ce_scores = np.array([])
                    else:
                        ce_scores = torch.softmax(torch.tensor(ce_scores), dim=1)[:, -1].numpy()
                else:
                    ce_scores = torch.sigmoid(torch.tensor(ce_scores)).numpy()
                
                # 如果ce_scores为空，跳过融合，仅使用embedding分数
                if len(ce_scores) == 0:
                    for idx in top_k_indices:
                        if idx < len(candidate_texts) and idx < len(similarities):
                            # 归一化余弦相似度到[0, 1]范围（保持一致性）
                            cosine_score = float(similarities[idx])
                            normalized_score = max(0.0, min(1.0, (cosine_score + 1) / 2))
                            cross_encoder_scores[candidate_texts[idx]] = normalized_score
                else:
                    # 融合第一段和第二段分数
                    # 阶段3第一版：固定权重融合（embedding 60% + Cross-encoder 40%，可配置）
                    # 后续优化方向：
                    #   1. 使用验证集做grid search找最优权重（如0.5/0.5, 0.4/0.6, 0.7/0.3）
                    #   2. 使用logistic regression / 小MLP学习式融合（两维输入 → 一维输出）
                    # 确保ce_scores长度与top_k_indices匹配
                    if len(ce_scores) != len(top_k_indices):
                        # 如果长度不匹配，截断或填充（取较小值）
                        min_len = min(len(ce_scores), len(top_k_indices))
                        ce_scores = ce_scores[:min_len]
                        top_k_indices = top_k_indices[:min_len]
                    
                    for idx, candidate_idx in enumerate(top_k_indices):
                        # 确保索引有效
                        if candidate_idx >= len(similarities) or candidate_idx >= len(candidate_texts):
                            continue
                        embedding_score = float(similarities[candidate_idx])
                        cross_encoder_score = float(ce_scores[idx]) if idx < len(ce_scores) else embedding_score
                        final_score = self.embedding_weight * embedding_score + self.cross_encoder_weight * cross_encoder_score
                        # 归一化到[0, 1]范围（与_module_2_3_compute_scores保持一致）
                        # 融合分数，范围[-embedding_weight, 1]
                        min_score = -self.embedding_weight
                        max_score = 1.0
                        if max_score > min_score:
                            normalized_score = (final_score - min_score) / (max_score - min_score)
                        else:
                            normalized_score = 0.5
                        cross_encoder_scores[candidate_texts[candidate_idx]] = max(0.0, min(1.0, normalized_score))
            except Exception as e:
                error_msg = (
                    f"Cross-encoder匹配失败\n"
                    f"输入文本: {new_text[:100]}...\n"
                    f"候选数量: {len(top_k_candidates)}\n"
                    f"设备: {self.device}\n"
                    f"错误详情: {str(e)}\n"
                    f"可能原因:\n"
                    f"  1. 模型未正确初始化\n"
                    f"  2. 输入数据格式错误\n"
                    f"  3. 设备资源不足（显存/内存）\n"
                    f"  4. 模型推理过程出错"
                )
                raise RuntimeError(error_msg) from e
        
        # 对于未进入第二段的候选，仅使用embedding分数
        for i, candidate in enumerate(candidate_texts):
            if candidate not in cross_encoder_scores:
                # 确保索引有效
                if i < len(similarities):
                    # 归一化余弦相似度到[0, 1]范围（保持一致性）
                    cosine_score = float(similarities[i])
                    normalized_score = max(0.0, min(1.0, (cosine_score + 1) / 2))
                    cross_encoder_scores[candidate] = normalized_score
        
        return cross_encoder_scores

    def _merge_similar_candidates(self, new_atoms: List[Dict], 
                                 similarity_threshold: float = 0.85,
                                 use_cross_encoder: bool = True) -> List[Dict]:
        """候选合并逻辑：与已有事件向量的相似度计算和合并
        
        Args:
            new_atoms: 新提取的原子列表
            similarity_threshold: 相似度阈值（默认0.85）
            use_cross_encoder: 是否使用Cross-encoder进行精确匹配（默认True）
            
        Returns:
            List[Dict]: 合并后的原子列表
        """
        if not new_atoms:
            return new_atoms
        
        merged_atoms = []
        
        for new_atom in new_atoms:
            atom_text = new_atom.get("atom_text", "").strip()
            if not atom_text:
                merged_atoms.append(new_atom)
                continue
            
            # 从已有事件池中查找相似事件
            if not self.existing_events_pool:
                # 池为空，直接添加
                merged_atoms.append(new_atom)
                # 添加到池中
                atom_emb = self._encode_with_cache(
                    atom_text,
                    convert_to_numpy=True,
                    normalize_embeddings=True
                )
                if isinstance(atom_emb, list):
                    atom_emb = atom_emb[0]
                if isinstance(atom_emb, torch.Tensor):
                    atom_emb = atom_emb.cpu().numpy()
                
                self.existing_events_pool.append({
                    "text": atom_text,
                    "embedding": atom_emb,
                    "atom": new_atom
                })
                
                # 限制池大小
                if len(self.existing_events_pool) > self.existing_events_max_size:
                    self.existing_events_pool = self.existing_events_pool[-self.existing_events_max_size:]
                continue
            
            # 提取已有事件的文本
            existing_texts = [item["text"] for item in self.existing_events_pool]
            
            # 使用两段式评分
            if use_cross_encoder:
                matching_scores = self._two_stage_scoring(
                    new_text=atom_text,
                    candidate_texts=existing_texts,
                    top_k=min(10, len(existing_texts))
                )
            else:
                # 仅使用embedding
                new_emb = self._encode_with_cache(
                    atom_text,
                    convert_to_tensor=True,
                    normalize_embeddings=True
                )
                if isinstance(new_emb, list):
                    new_emb = new_emb[0]
                if not isinstance(new_emb, torch.Tensor):
                    new_emb = torch.tensor(new_emb)
                if new_emb.dim() == 1:
                    new_emb = new_emb.unsqueeze(0)
                
                matching_scores = {}
                for item in self.existing_events_pool:
                    existing_emb = torch.tensor(item["embedding"], device=new_emb.device).unsqueeze(0)
                    cosine_sim = torch.nn.functional.cosine_similarity(
                        new_emb, existing_emb, dim=1
                    ).item()
                    # 归一化余弦相似度到[0, 1]范围（与_two_stage_scoring保持一致）
                    normalized_sim = max(0.0, min(1.0, (cosine_sim + 1) / 2))
                    matching_scores[item["text"]] = normalized_sim
            
            # 查找最相似的已有事件
            if not matching_scores:
                # 如果matching_scores为空（理论上不应该发生，但为了健壮性添加检查）
                merged_atoms.append(new_atom)
                # 添加到池中
                atom_emb = self._encode_with_cache(
                    atom_text,
                    convert_to_numpy=True,
                    normalize_embeddings=True
                )
                if isinstance(atom_emb, list):
                    atom_emb = atom_emb[0]
                if isinstance(atom_emb, torch.Tensor):
                    atom_emb = atom_emb.cpu().numpy()
                
                self.existing_events_pool.append({
                    "text": atom_text,
                    "embedding": atom_emb,
                    "atom": new_atom
                })
                
                # 限制池大小
                if len(self.existing_events_pool) > self.existing_events_max_size:
                    self.existing_events_pool = self.existing_events_pool[-self.existing_events_max_size:]
                continue
            
            best_match = max(matching_scores.items(), key=lambda x: x[1])
            best_text, best_score = best_match
            
            if best_score >= similarity_threshold:
                # 找到相似事件，合并（保留新事件，但标记为已合并）
                new_atom["_merged_with"] = best_text
                new_atom["_merge_score"] = best_score
                # 将合并后的新事件添加到结果中（保留标记信息）
                merged_atoms.append(new_atom)
                # 更新已有事件池中的对应事件（可选：更新为更完整的版本）
            else:
                # 未找到相似事件，作为新事件添加
                merged_atoms.append(new_atom)
                # 添加到池中
                atom_emb = self._encode_with_cache(
                    atom_text,
                    convert_to_numpy=True,
                    normalize_embeddings=True
                )
                if isinstance(atom_emb, list):
                    atom_emb = atom_emb[0]
                if isinstance(atom_emb, torch.Tensor):
                    atom_emb = atom_emb.cpu().numpy()
                
                self.existing_events_pool.append({
                    "text": atom_text,
                    "embedding": atom_emb,
                    "atom": new_atom
                })
                
                # 限制池大小
                if len(self.existing_events_pool) > self.existing_events_max_size:
                    self.existing_events_pool = self.existing_events_pool[-self.existing_events_max_size:]
        
        return merged_atoms

    def _apply_coref(self, text: str) -> str:
        """手动应用共指消解"""
        preds = self.coref_model.predict(texts=[text])
        clusters = preds[0].get_clusters(as_strings=False)
        
        replacements = []
        for cluster in clusters:
            main_span = cluster[0] 
            main_text = text[main_span[0]:main_span[1]]
            
            for mention_span in cluster[1:]:
                start, end = mention_span
                replacements.append((start, end, main_text))
        
        replacements.sort(key=lambda x: x[0], reverse=True)
        
        text_list = list(text)
        for start, end, new_str in replacements:
            text_list[start:end] = list(new_str)
            
        return "".join(text_list)

    def _module_1_process_text(self, text: str) -> Tuple[List[str], List]:
        """执行共指消解 + 智能分句，返回句子列表和spaCy doc对象列表"""
        clean_input = " ".join(text.split())
        resolved_text = self._apply_coref(clean_input)
        resolved_text = self._fix_sentence_boundaries(resolved_text)
        
        doc = self.nlp(resolved_text)
        sentences = []
        doc_objects = []
        for sent in doc.sents:
            sent_text = sent.text.strip()
            if len(sent_text) > 15:
                sentences.append(sent_text)
                doc_objects.append(sent)
        return sentences, doc_objects
    
    def _fix_sentence_boundaries(self, text: str) -> str:
        """修复句子边界问题，处理错误拼接的句子
        
        例如：修复 "stimuli OFlying insects" -> "stimuli. Flying insects"
        """
        text = re.sub(r'([a-z])\s*O([A-Z][a-z])', r'\1. \2', text)
        text = re.sub(r'([a-z])([A-Z][a-z])', r'\1. \2', text)
        text = " ".join(text.split())
        return text

    def _extract_noun_phrase(self, token):
        """提取完整的名词短语（包括所有修饰词和括号内容）"""
        doc = token.doc
        tokens = []
        visited = set()
        
        # 1. 收集subtree中的token
        for t in token.subtree:
            if t.i not in visited:
                tokens.append(t)
                visited.add(t.i)
        
        # 2. 显式处理括号内容：扫描与head相邻的括号对
        head_start = token.i
        head_end = max(t.i for t in token.subtree) if token.subtree else token.i
        
        # 查找左括号（在head附近，距离不超过10个token）
        for i in range(max(0, head_start - 10), min(len(doc), head_end + 10)):
            if i in visited:
                continue
            t = doc[i]
            if t.text == "(":
                # 找到匹配的右括号
                paren_tokens = [t]
                depth = 1
                idx = i + 1
                while idx < len(doc) and depth > 0:
                    if doc[idx].text == "(":
                        depth += 1
                    elif doc[idx].text == ")":
                        depth -= 1
                    if depth > 0:
                        paren_tokens.append(doc[idx])
                    elif depth == 0:
                        paren_tokens.append(doc[idx])
                    idx += 1
                
                # 检查括号是否与当前名词短语相邻（距离不超过5个token）
                if paren_tokens and any(abs(pt.i - head_start) <= 5 or abs(pt.i - head_end) <= 5 for pt in paren_tokens):
                    for pt in paren_tokens:
                        if pt.i not in visited:
                            tokens.append(pt)
                            visited.add(pt.i)
        
        # 3. 处理appos/flat/list/nmod等依存关系（与head相关的修饰）
        for t in doc:
            if t.i in visited:
                continue
            # 检查是否与head有直接或间接关系
            if (t.head == token or token in t.head.subtree) and \
               t.dep_ in ["appos", "flat", "list", "nmod"]:
                tokens.append(t)
                visited.add(t.i)
                # 同时收集该token的subtree
                for st in t.subtree:
                    if st.i not in visited:
                        tokens.append(st)
                        visited.add(st.i)
        
        # 4. 按位置排序
        tokens.sort(key=lambda x: x.i)
        return " ".join([t.text for t in tokens])
    
    def _extract_patient_head_modifier(self, patient_token, sent_doc):
        """提取 patient 的核心部分（head noun + modifier，不取介词短语尾部）
        
        增强版：支持
        - 并列名词（conj）
        - 多层介词（of/for/in/on）
        - compound 结构（如 "object detection model accuracy"）
        - NER entity span
        
        例如：
        "accuracy of object detection under low light"
        → "accuracy of object detection"（head + of短语，不取后续介词）
        
        "object detection and recognition model"
        → "object detection and recognition model"（包含并列）
        """
        if not patient_token:
            return None
        
        head = patient_token
        
        modifier_deps = ['amod', 'det', 'compound', 'nummod', 'nmod']
        phrase_tokens = [head]
        visited = {head.i}
        
        def collect_modifiers(token, include_compounds=True):
            """递归收集修饰词"""
            for child in token.children:
                if child.i in visited:
                    continue
                
                if child.dep_ in modifier_deps:
                    phrase_tokens.append(child)
                    visited.add(child.i)
                    if include_compounds:
                        collect_modifiers(child, include_compounds=True)
                
                elif child.dep_ == 'conj' and child.pos_ == 'NOUN':
                    phrase_tokens.append(child)
                    visited.add(child.i)
                    collect_modifiers(child, include_compounds=True)
        
        collect_modifiers(head, include_compounds=True)
        prep_priority = ['of', 'for', 'in', 'on']
        prep_processed = False
        
        for prep_word in prep_priority:
            if prep_processed:
                break
            for child in head.children:
                if child.dep_ == 'prep' and child.text.lower() == prep_word:
                    for pobj in child.children:
                        if pobj.dep_ == 'pobj':
                            phrase_tokens.append(child)
                            phrase_tokens.append(pobj)
                            visited.add(pobj.i)
                            
                            collect_modifiers(pobj, include_compounds=True)
                            for pobj_child in pobj.children:
                                if pobj_child.dep_ == 'prep' and pobj_child.text.lower() in prep_priority[:2]:
                                    for pobj2 in pobj_child.children:
                                        if pobj2.dep_ == 'pobj':
                                            phrase_tokens.append(pobj_child)
                                            phrase_tokens.append(pobj2)
                                            visited.add(pobj2.i)
                                            collect_modifiers(pobj2, include_compounds=False)
                                            break
                                    break
                            
                            prep_processed = True
                            break
                    if prep_processed:
                        break
        
        phrase_tokens.sort(key=lambda t: t.i)
        return " ".join([t.text for t in phrase_tokens])
    
    def _get_root_verb_id(self, verb, sent_doc):
        """获取动词所属的根动词ID（句法树中最顶层动词）"""
        current = verb
        root_verb = None
        max_iterations = 20
        iteration = 0
        
        while current.head != current and iteration < max_iterations:
            if current.head.pos_ == "VERB" and current.head.dep_ == "ROOT":
                root_verb = current.head
                break
            current = current.head
            iteration += 1
        
        if root_verb is None:
            if sent_doc and len(sent_doc) > 0:
                if hasattr(sent_doc[0], 'sent') and sent_doc[0].sent.root:
                    root_verb = sent_doc[0].sent.root
        
        if root_verb is None:
            root_verb = verb
        
        return root_verb.i if root_verb else verb.i
    
    def _classify_by_object(self, by_object_token):
        """分类 by 短语的 object：agent vs instrument vs method-agent
        
        Returns:
            "agent" | "instrument" | "method-agent" | "unknown"
        """
        if not by_object_token:
            return "unknown"
        
        obj_text = by_object_token.text.lower()
        obj_lemma = by_object_token.lemma_.lower()
        
        human_agent_keywords = ["human", "humans", "user", "users", "researcher", "researchers",
                               "person", "people", "population", "participant", "participants",
                               "subject", "subjects", "individual", "individuals", "expert", "experts"]
        if obj_lemma in human_agent_keywords or any(kw in obj_text for kw in human_agent_keywords):
            return "agent"
        
        organization_keywords = ["organization", "institution", "company", "team", "group", "committee"]
        if obj_lemma in organization_keywords or any(kw in obj_text for kw in organization_keywords):
            return "agent"
        method_agent_keywords = ["algorithm", "framework", "strategy", "approach", "method", 
                                "technique", "procedure", "protocol", "scheme", "mechanism",
                                "architecture", "model", "system", "network", "structure"]
        
        known_model_names = [
            "transformer", "bert", "gpt", "resnet", "vgg", "alexnet", "inception",
            "yolo", "rnn", "lstm", "gru", "cnn", "gan", "vae", "attention",
            "unet", "densenet", "mobilenet", "efficientnet", "swin",
            "vision transformer", "vit", "clip", "bert-base", "bert-large",
            "gpt-2", "gpt-3", "gpt-4", "t5", "roberta", "xlnet", "electra"
        ]
        
        physical_instrument_suffixes = ["tool", "device", "instrument", "apparatus",
                                        "spectrometer", "sensor", "detector", "machine", "equipment"]
        
        obj_text_lower = obj_text.lower()
        if any(model_name in obj_text_lower for model_name in known_model_names):
            if "our" in [t.text.lower() for t in by_object_token.lefts] or \
               "proposed" in [t.text.lower() for t in by_object_token.lefts]:
                return "agent"
            return "method-agent"
        
        if any(kw in obj_text or kw in obj_lemma for kw in method_agent_keywords):
            if "our" in [t.text.lower() for t in by_object_token.lefts] or \
               "proposed" in [t.text.lower() for t in by_object_token.lefts]:
                return "agent"
            return "method-agent"
        
        if any(obj_text.endswith(suffix) or obj_lemma.endswith(suffix) for suffix in physical_instrument_suffixes):
            return "instrument"
        
        if any(char.isdigit() for char in obj_text) or '-' in obj_text or '_' in obj_text:
            if obj_lemma not in human_agent_keywords:
                if any(kw in obj_text or kw in obj_lemma for kw in ["model", "system", "network", "architecture", "algorithm", "framework"]):
                    return "method-agent"
                return "instrument"
        
        if hasattr(by_object_token, 'ent_type_') and by_object_token.ent_type_:
            if by_object_token.ent_type_ in ["PERSON", "ORG", "GPE"]:
                if any(char.isdigit() for char in obj_text) or '-' in obj_text:
                    return "instrument"
                return "agent"
            elif by_object_token.ent_type_ in ["PRODUCT", "EVENT"]:
                return "instrument"
        
        if obj_text and obj_text[0].isupper() and len(obj_text.split()) <= 3:
            if not (any(char.isdigit() for char in obj_text) or '-' in obj_text):
                return "agent"
        
        return "unknown"
    
    def _find_subject_for_verb(self, verb, sent_doc, root_verb_id=None, visited_verbs=None):
        """查找动词的主语（基于最近有效主语）
        
        Args:
            verb: 目标动词token
            sent_doc: 句子doc对象
            root_verb_id: 根动词ID（用于继承锁）
            visited_verbs: 已访问的动词集合（防止循环）
        
        Returns:
            (subject_token, subj_source, logical_subject, logical_subject_type)
            subj_source: "SELF" | "INHERITED(root_id)"
        """
        if visited_verbs is None:
            visited_verbs = set()
        
        if verb.i in visited_verbs:
            return None, None, None, None
        
        visited_verbs.add(verb.i)
        
        if root_verb_id is None:
            root_verb_id = self._get_root_verb_id(verb, sent_doc)
        
        children_by_dep = {}
        for child in verb.children:
            if child.dep_ not in children_by_dep:
                children_by_dep[child.dep_] = []
            children_by_dep[child.dep_].append(child)
        
        if 'nsubj' in children_by_dep:
            return children_by_dep['nsubj'][0], "SELF", None, None
        elif 'nsubjpass' in children_by_dep:
            subject = children_by_dep['nsubjpass'][0]
            logical_subject = None
            logical_subject_type = None
            
            if 'agent' in children_by_dep:
                logical_subject = children_by_dep['agent'][0]
                logical_subject_type = self._classify_by_object(logical_subject)
            elif 'prep' in children_by_dep:
                for prep in children_by_dep['prep']:
                    if prep.text.lower() == 'by':
                        for pobj in prep.children:
                            if pobj.dep_ == 'pobj':
                                logical_subject = pobj
                                logical_subject_type = self._classify_by_object(pobj)
                                break
                        if logical_subject:
                            break
            
            return subject, "SELF", logical_subject, logical_subject_type
        elif 'csubj' in children_by_dep:
            return children_by_dep['csubj'][0], "SELF", None, None
        
        current = verb.head
        max_depth = 10
        depth = 0
        
        nearest_subject = None
        nearest_subject_source = None
        nearest_logical = None
        nearest_logical_type = None
        
        while current != current.head and depth < max_depth:
            if current.text in ['.', ';', ':']:
                break
            
            if current.pos_ == "VERB":
                parent_subj, parent_source, parent_logical, parent_logical_type = \
                    self._find_subject_for_verb(current, sent_doc, root_verb_id, visited_verbs.copy())
                
                if parent_subj:
                    if nearest_subject is None:
                        nearest_subject = parent_subj
                        nearest_subject_source = parent_source
                        nearest_logical = parent_logical
                        nearest_logical_type = parent_logical_type
                    
                    parent_root_id = self._get_root_verb_id(current, sent_doc)
                    if parent_root_id == root_verb_id:
                        inherited_source = f"INHERITED({root_verb_id})"
                        return parent_subj, inherited_source, parent_logical, parent_logical_type
            
            current = current.head
            depth += 1
        
        if nearest_subject:
            return nearest_subject, f"NEAREST_SUBJECT", nearest_logical, nearest_logical_type
        
        return None, None, None, None
    
    def _extract_atom_from_verb(self, verb, matrix_subject=None, sent_doc=None, root_verb_id=None):
        """从动词提取原子，支持主语继承和被动语态处理（带 subj_source 追踪）"""
        if not sent_doc:
            return None
        
        if root_verb_id is None:
            root_verb_id = self._get_root_verb_id(verb, sent_doc)
        
        subject, subj_source, logical_subject, logical_subject_type = \
            self._find_subject_for_verb(verb, sent_doc, root_verb_id)
        
        if not subject and matrix_subject:
            subject = matrix_subject
            subj_source = f"INHERITED({root_verb_id})"
        
        if subj_source and subj_source.startswith("INHERITED"):
            self.atom_stats["atoms_with_inherited_subject"] += 1
        
        children_by_dep = {}
        for child in verb.children:
            if child.dep_ not in children_by_dep:
                children_by_dep[child.dep_] = []
            children_by_dep[child.dep_].append(child)
        
        obj = None
        if 'dobj' in children_by_dep:
            obj = children_by_dep['dobj'][0]
        elif 'pobj' in children_by_dep:
            obj = children_by_dep['pobj'][0]
        elif 'prep' in children_by_dep:
            for prep in children_by_dep['prep']:
                for pobj in prep.children:
                    if pobj.dep_ == 'pobj':
                        obj = pobj
                        break
                if obj:
                    break
        
        attr = None
        if 'attr' in children_by_dep:
            attr = children_by_dep['attr'][0]
        elif 'acomp' in children_by_dep:
            attr = children_by_dep['acomp'][0]
        
        atom_parts = []
        
        if logical_subject and logical_subject_type in ["agent", "method-agent"]:
            logical_subject_text = self._extract_noun_phrase(logical_subject)
            atom_parts.append(logical_subject_text)
            atom_parts.append(verb.text)
            if subject:
                subject_text = self._extract_noun_phrase(subject)
                atom_parts.append(subject_text)
        else:
            if subject:
                subject_text = self._extract_noun_phrase(subject)
                atom_parts.append(subject_text)
            atom_parts.append(verb.text)
        
        if obj:
            obj_text = self._extract_noun_phrase(obj)
            atom_parts.append(obj_text)
        elif attr:
            attr_text = self._extract_noun_phrase(attr)
            atom_parts.append(attr_text)
        
        atom_text = " ".join(atom_parts)
        if not atom_text.strip():
            atom_text = verb.text
        
        if not atom_text.strip():
            return None
        
        verb_lemma = verb.lemma_.lower()
        if verb_lemma in ["be", "is", "are", "was", "were", "am"]:
            atom_type = "FACT"
        elif verb_lemma in ["have", "has", "had", "contain", "include", "possess"]:
            atom_type = "ATTRIBUTE"
        elif verb_lemma in ["cause", "lead", "result", "produce", "generate", "induce", "trigger", "drive"]:
            atom_type = "RELATION"
        elif verb_lemma in self.significance_verbs:
            atom_type = "ACTION"
        else:
            atom_type = "ACTION"
        
        relation_type = None
        atom_text_lower = atom_text.lower()
        
        if any(marker in atom_text_lower for marker in self.causal_markers):
            relation_type = "causal"
        elif any(marker in atom_text_lower for marker in self.conditional_markers):
            relation_type = "conditional"
        elif any(marker in atom_text_lower for marker in self.contrast_markers):
            relation_type = "contrast"
        
        atom_dict = {
            "atom_text": atom_text,
            "atom_type": atom_type,
            "verb_lemma": verb_lemma,
            "relation_type": relation_type,
            "subj_source": subj_source if subj_source else "NONE",
            "has_subject": subject is not None,
            "has_object": obj is not None or attr is not None
        }
        
        return atom_dict
    
    def _is_nominalized_verb(self, noun_token):
        """判断是否为名词化动词（词表 + 词缀规则 + POS 过滤）
        
        词缀规则：
        -tion, -sion, -ment, -ing, -ance, -ence, -ability, -ibility, -ness
        
        POS 过滤：
        - 仅当 token.pos_ == NOUN 且 token.tag_ == VBG 时才判断为名词化
        - 排除单纯 -ing 动名词（如 using, making, doing）
        """
        if noun_token.pos_ != "NOUN":
            return False
        
        noun_lemma = noun_token.lemma_.lower()
        
        if noun_lemma in NOMINALIZATION_NOUNS:
            return True
        
        nominalization_suffixes = [
            "tion", "sion", "ment", "ance", "ence",
            "ability", "ibility", "ness"
        ]
        
        for suffix in nominalization_suffixes:
            if noun_lemma.endswith(suffix) and len(noun_lemma) > len(suffix) + 2:
                if noun_lemma not in ["thing", "something", "nothing", "anything", "everything"]:
                    return True
        
        if noun_lemma.endswith("ing") and len(noun_lemma) > 4:
            gerund_exceptions = ["using", "making", "doing", "having", "being", "going", 
                               "getting", "taking", "coming", "seeing", "knowing", "saying",
                               "meeting", "building", "feeling", "meaning", "reading", "writing"]
            if noun_lemma not in gerund_exceptions:
                return True
        
        return False
    
    def _extract_atom_from_nominalization(self, noun_token, sent_doc):
        """从名词化动词提取原子（支持双参数结构）
        
        支持结构：
        1. NOUN + of + object
        2. NOUN + by + agent
        3. NOUN + of + object + by + agent（双参数）
        """
        if not self._is_nominalized_verb(noun_token):
            return None
        
        noun_lemma = noun_token.lemma_.lower()
        
        children_by_dep = {}
        for child in noun_token.children:
            if child.dep_ not in children_by_dep:
                children_by_dep[child.dep_] = []
            children_by_dep[child.dep_].append(child)
        
        agent = None
        agent_source = None
        
        if 'poss' in children_by_dep:
            agent = children_by_dep['poss'][0]
            agent_source = "possessive"
        elif 'prep' in children_by_dep:
            for prep in children_by_dep['prep']:
                if prep.text.lower() == 'by':
                    for pobj in prep.children:
                        if pobj.dep_ == 'pobj':
                            agent = pobj
                            agent_source = "by_phrase"
                            break
                    if agent:
                        break
        
        patient = None
        if 'prep' in children_by_dep:
            for prep in children_by_dep['prep']:
                if prep.text.lower() == 'of':
                    for pobj in prep.children:
                        if pobj.dep_ == 'pobj':
                            patient = pobj
                            break
                    if patient:
                        break
        
        atom_parts = []
        
        if agent:
            agent_text = self._extract_noun_phrase(agent)
            atom_parts.append(agent_text)
        
        action_verb = noun_lemma
        atom_parts.append(action_verb)
        
        if patient:
            patient_text = self._extract_noun_phrase(patient)
            atom_parts.append(patient_text)
        
        atom_text = " ".join(atom_parts)
        if not atom_text.strip():
            return None
        
        atom_type = "ACTION"
        
        return {
            "atom_text": atom_text,
            "atom_type": atom_type,
            "verb_lemma": action_verb,
            "relation_type": None,
            "subj_source": "NOMINALIZATION",
            "has_subject": agent is not None,
            "has_object": patient is not None,
            "is_nominalization": True,
            "agent": self._extract_noun_phrase(agent) if agent else None,
            "patient": self._extract_noun_phrase(patient) if patient else None
        }
    
    def _validate_atom_completeness(self, atom):
        """验证原子完整性
        
        检查：
        - 必须有 action
        - 必须至少有一个：[agent/patient/theme]
        - 严禁 action-only（除非标记为 weak）
        """
        if not atom:
            return False, "empty_atom"
        
        atom_text = atom.get("atom_text", "").strip()
        if not atom_text:
            return False, "no_text"
        
        has_action = atom.get("verb_lemma") is not None or atom.get("is_nominalization", False)
        if not has_action:
            return False, "no_action"
        
        has_subject = atom.get("has_subject", False)
        has_object = atom.get("has_object", False)
        has_agent = atom.get("agent") is not None
        has_patient = atom.get("patient") is not None
        
        has_role = has_subject or has_object or has_agent or has_patient
        
        if not has_role:
            atom["is_weak"] = True
            self.atom_stats["action_only_atoms"] += 1
            return True, "weak_atom"
        
        return True, "valid"
    
    def _build_lemma_group_map(self) -> Dict[str, str]:
        """构建词元归一化映射（lemma grouping）
        
        将同义词的不同形式映射到标准形式：
        - reduce/reduction -> reduce
        - analyze/analysis -> analyze
        - improve/improvement -> improve
        """
        lemma_map = {}
        
        nominalization_pairs = [
            ("reduction", "reduce"), ("analysis", "analyze"), ("improvement", "improve"),
            ("detection", "detect"), ("measurement", "measure"), ("activation", "activate"),
            ("regulation", "regulate"), ("inhibition", "inhibit"), ("compensation", "compensate"),
            ("enhancement", "enhance"), ("optimization", "optimize"), ("evaluation", "evaluate"),
            ("identification", "identify"), ("classification", "classify"), ("prediction", "predict"),
            ("recognition", "recognize"), ("extraction", "extract"), ("generation", "generate"),
            ("transformation", "transform"), ("modification", "modify"), ("adaptation", "adapt")
        ]
        
        for noun, verb in nominalization_pairs:
            lemma_map[noun] = verb
            lemma_map[verb] = verb
        
        return lemma_map
    
    def _get_wordnet_hypernym(self, word: str, pos: str = 'v') -> Optional[str]:
        """获取 WordNet 超级类（hypernym）
        
        Args:
            word: 单词
            pos: 词性 ('v'=verb, 'n'=noun)
        
        Returns:
            超级类名称，如果未找到返回 None
        """
        if not HAS_WORDNET:
            return None
        
        cache_key = f"{word}_{pos}"
        if cache_key in self.hypernym_cache:
            return self.hypernym_cache[cache_key]
        
        synsets = wn.synsets(word, pos=pos)
        if not synsets:
            self.hypernym_cache[cache_key] = None
            return None
        
        synset = synsets[0]
        hypernyms = synset.hypernyms()
        if hypernyms:
            hypernym_name = hypernyms[0].lemmas()[0].name().replace('_', ' ')
            self.hypernym_cache[cache_key] = hypernym_name
            return hypernym_name
        
        self.hypernym_cache[cache_key] = None
        return None
    
    def _normalize_action_to_concept(self, action_lemma: str) -> str:
        """将动作词元归一化到概念层
        
        步骤：
        1. 词元归一化（lemma grouping）
        2. WordNet 超级类映射（如果可用）
        
        Returns:
            概念层表示
        """
        if not action_lemma:
            return ""
        
        action_lower = action_lemma.lower()
        
        normalized = self.lemma_group_map.get(action_lower, action_lower)
        
        if HAS_WORDNET:
            hypernym = self._get_wordnet_hypernym(normalized, pos='v')
            if hypernym:
                return hypernym
        
        return normalized
    
    def _extract_concept_phrase(self, atom: Dict) -> str:
        """从原子提取概念短语（action + patient）
        
        用于构建概念嵌入，提升语义相似度
        """
        action = atom.get("verb_lemma", "")
        if not action:
            return atom.get("atom_text", "")
        
        patient = atom.get("patient")
        
        if not patient and atom.get("has_object"):
            atom_text = atom.get("atom_text", "")
            parts = atom_text.split()
            action_lower = action.lower()
            for i, part in enumerate(parts):
                if part.lower() == action_lower or part.lower().startswith(action_lower):
                    if i + 1 < len(parts):
                        patient_parts = parts[i + 1:i + 4]
                        patient = " ".join(patient_parts)
                    break
        
        if patient:
            patient_words = patient.split()[:5]
            concept_phrase = f"{action} {' '.join(patient_words)}"
        else:
            concept_phrase = action
        
        return concept_phrase
    
    def _map_atoms_to_concepts(self, atoms: List[Dict]) -> Tuple[Dict[str, List[int]], Dict[int, str]]:
        """将原子映射到概念节点
        
        Returns:
            (concept_to_atoms: 概念 -> 原子索引列表, atom_to_concept: 原子索引 -> 概念)
        """
        concept_to_atoms = defaultdict(list)
        atom_to_concept = {}
        
        for i, atom in enumerate(atoms):
            action = atom.get("verb_lemma", "")
            
            if not action:
                atom_text = atom.get("atom_text", "")
                if atom_text:
                    words = atom_text.split()[:3]
                    concept = " ".join(words).lower()
                else:
                    concept = "unknown"
                concept_to_atoms[concept].append(i)
                atom_to_concept[i] = concept
                continue
            
            concept = self._normalize_action_to_concept(action)
            
            patient = atom.get("patient")
            if patient:
                patient_words = patient.split()[:2]
                concept_with_patient = f"{concept} {' '.join(patient_words)}"
                concept_to_atoms[concept_with_patient].append(i)
                atom_to_concept[i] = concept_with_patient
            else:
                concept_to_atoms[concept].append(i)
                atom_to_concept[i] = concept
        
        return dict(concept_to_atoms), atom_to_concept
    
    def _compute_concept_embeddings(self, atoms: List[Dict]) -> torch.Tensor:
        """计算概念层嵌入（而非直接原子嵌入）
        
        使用 action + patient 构建概念短语，然后计算嵌入
        """
        concept_phrases = []
        for atom in atoms:
            concept_phrase = self._extract_concept_phrase(atom)
            if not concept_phrase or not concept_phrase.strip():
                concept_phrase = atom.get("atom_text", "unknown")
            concept_phrases.append(concept_phrase)
        
        concept_embeddings = self.emb_model.encode(concept_phrases, convert_to_tensor=True, device=self.device)
        return concept_embeddings
    
    def _module_4_apply_rules(self, atom: Dict) -> Dict[str, float]:
        """应用事件分类器评分（替代关键词匹配）
        
        核心改进：
        - 使用语义事件分类器替代硬关键词匹配
        - 基于embedding相似度进行语义理解
        - 输出概率分数而非0/1硬匹配
        
        Args:
            atom: 原子字典
            
        Returns:
            Dict[str, float]: 每个类别的事件分类分数（0.0-1.0）
        """
        atom_text = atom.get("atom_text", "")
        original_sentence = atom.get("original_sentence", "")
        
        # 优先使用原子文本，如果原子文本太短则使用原始句子
        text_for_classification = atom_text if len(atom_text.strip()) > 20 else original_sentence
        if not text_for_classification or not text_for_classification.strip():
            text_for_classification = atom_text or original_sentence or ""
        
        event_probs = self.event_classifier.classify(text_for_classification)
        
        boost = {
            "AIM": event_probs.get("AIM", 0.0),
            "CONCLUSION": event_probs.get("CONCLUSION", 0.0),
            "METHOD": event_probs.get("METHOD", 0.0)
        }
        
        atom['_event_classifier_probs'] = event_probs.copy()
        atom['_rule_scores'] = boost.copy()
        atom['_rule_matched_keywords'] = {
            "AIM": [] if boost["AIM"] < 0.3 else ["event_classifier"],
            "CONCLUSION": [] if boost["CONCLUSION"] < 0.3 else ["event_classifier"],
            "METHOD": [] if boost["METHOD"] < 0.3 else ["event_classifier"]
        }
        
        if hasattr(self, '_debug_rules') and self._debug_rules:
            print(f"  [Event Classifier] 原子文本: {atom_text[:60]}...")
            print(f"    - AIM: {boost['AIM']:.3f}, CONCLUSION: {boost['CONCLUSION']:.3f}, METHOD: {boost['METHOD']:.3f}")
        
        return boost

    def _compute_atom_quality(self, mau: MAU) -> float:
        """计算原子质量评分（统一质量评估）
        
        质量评分包含三个维度：
        1. 完整性：predicate + patient/agent 完整性（0-1）
        2. 结构性：MAU结构完整性（0-1）
        3. 局部置信度：基于 source_path 的初始置信度（A:0.7-1.0, B:0.5-0.8, C:0.3-0.6）
        
        Args:
            mau: MAU对象
            
        Returns:
            float: 质量评分 [0, 1]
        """
        # 1. 完整性评分：predicate + patient/agent 完整性
        completeness = 0.0
        if mau.predicate:
            completeness += 0.4  # predicate存在
            if mau.patient:
                completeness += 0.3  # patient存在
            if mau.agent:
                completeness += 0.3  # agent存在
        
        # 2. 结构性评分：MAU结构完整性
        structure = 0.0
        if mau.predicate and len(mau.predicate.strip()) > 0:
            structure += 0.5
        if mau.patient and len(mau.patient.strip()) > 0:
            structure += 0.3
        elif mau.agent and len(mau.agent.strip()) > 0:
            structure += 0.3
        if mau.atom_text and len(mau.atom_text.strip()) > 10:
            structure += 0.2
        
        # 3. 局部置信度：基于 source_path 的初始置信度
        path_confidence_map = {
            "A": 0.85,  # 路径A：0.7-1.0，取中值
            "B": 0.65,  # 路径B：0.5-0.8，取中值
            "C": 0.45,  # 路径C：0.3-0.6，取中值
            "SRL": 0.7  # SRL路径：使用structure_confidence作为基础
        }
        local_confidence = path_confidence_map.get(mau.source_path, 0.5)
        
        # 综合评分：加权平均
        quality = (completeness * 0.4 + structure * 0.3 + local_confidence * 0.3)
        
        # 限制在 [0, 1] 范围
        quality = max(0.0, min(1.0, quality))
        
        return quality

    def _deduplicate_srl_atoms(self, all_maus: List[MAU], similarity_threshold: float = 0.75) -> List[MAU]:
        """基于embedding + predicate内匹配的去重（SRL路径）
        
        对SRL路径的原子，计算embedding相似度，仅在同一predicate内比较。
        如果相似度 >= threshold，则视为重复，保留第一个出现的原子。
        
        Args:
            all_maus: 所有MAU列表（应该都是SRL路径）
            similarity_threshold: 相似度阈值（默认0.75）
            
        Returns:
            List[MAU]: 去重后的MAU列表
        """
        if not all_maus:
            return all_maus
        
        # 计算所有原子的embedding和predicate归一化
        mau_texts = [mau.atom_text if mau.atom_text else f"{mau.agent or ''} {mau.predicate or ''} {mau.patient or ''}".strip() for mau in all_maus]
        mau_embs = self.emb_model.encode(mau_texts, convert_to_numpy=True, normalize_embeddings=True)
        
        mau_normalized_preds = []
        for mau in all_maus:
            if mau.predicate:
                normalized = self.agg_layer.predicate_normalizer.normalize(mau.predicate)
                mau_normalized_preds.append(normalized)
            else:
                mau_normalized_preds.append("")
        
        # 对每个原子，检查是否与之前的原子重复（仅在同一predicate内）
        kept_maus = []
        filtered_count = 0
        
        for i, mau in enumerate(all_maus):
            if not mau.predicate:
                kept_maus.append(mau)
                continue
            
            i_normalized_pred = mau_normalized_preds[i]
            i_emb = mau_embs[i]
            
            is_duplicate = False
            for j, kept_mau in enumerate(kept_maus):
                j_idx = all_maus.index(kept_mau)
                j_normalized_pred = mau_normalized_preds[j_idx]
                
                # 仅在同一predicate内比较
                if j_normalized_pred == i_normalized_pred:
                    j_emb = mau_embs[j_idx]
                    similarity = np.dot(i_emb, j_emb)
                    
                    if similarity >= similarity_threshold:
                        is_duplicate = True
                        filtered_count += 1
                        break
            
            if not is_duplicate:
                kept_maus.append(mau)
        
        if filtered_count > 0:
            print(f"\n[SRL去重阶段] 完成")
            print(f"  - 原始原子数: {len(all_maus)}")
            print(f"  - 保留原子数: {len(kept_maus)}")
            print(f"  - 过滤重复数: {filtered_count} (相似度阈值: {similarity_threshold})")
        
        return kept_maus

    def _module_2_3_compute_scores(self, atoms: List[Dict], sentences: Optional[List[str]] = None):
        """计算原子评分（两段式：BGE embedding + Cross-encoder）
        
        阶段3改进：
        1. 第一段：BGE embedding计算与AIM/METHOD/RESULT原型向量的相似度
        2. 第二段：Cross-encoder对top-k候选进行精确匹配
        
        Args:
            atoms: 原子列表
            sentences: 句子列表（保留参数以兼容旧代码，但不再使用）
        """
        keys = ["AIM", "CONCLUSION", "METHOD"]
        
        atom_texts = []
        for i, atom in enumerate(atoms):
            atom_text = atom.get("atom_text", "")
            if atom_text and atom_text.strip():
                atom_texts.append(atom_text)
            else:
                atom_texts.append("placeholder text")
        
        if not atom_texts:
            return {}, None
        
        # 准备原型向量（用于第一段）
        prototype_texts = {
            "AIM": ["The objective is to investigate", "We propose a new method", "The goal of this paper"],
            "CONCLUSION": ["Results show that", "We conclude that", "The findings demonstrate"],
            "METHOD": ["We utilized a dataset", "The experiment was performed", "The methodology involves"]
        }
        
        prototype_embeddings = {}
        for k in keys:
            proto_texts = prototype_texts[k]
            proto_embs = self._encode_with_cache(
                proto_texts,
                convert_to_tensor=True,
                normalize_embeddings=True
            )
            if not isinstance(proto_embs, torch.Tensor):
                proto_embs = torch.tensor(proto_embs)
            if proto_embs.device != torch.device(self.device):
                proto_embs = proto_embs.to(self.device)
            prototype_embeddings[k] = proto_embs
        
        nli_scores = {}
        
        try:
            # 尝试使用两段式评分
            for i, atom_text in enumerate(atom_texts):
                nli_scores[i] = {}
                for k in keys:
                    # 第一段：BGE embedding计算与原型相似度
                    atom_emb = self._encode_with_cache(
                        atom_text,
                        convert_to_tensor=True,
                        normalize_embeddings=True
                    )
                    if isinstance(atom_emb, list):
                        atom_emb = atom_emb[0]
                    if not isinstance(atom_emb, torch.Tensor):
                        atom_emb = torch.tensor(atom_emb)
                    if atom_emb.dim() == 1:
                        atom_emb = atom_emb.unsqueeze(0)
                    if atom_emb.device != torch.device(self.device):
                        atom_emb = atom_emb.to(self.device)
                    
                    proto_embs = prototype_embeddings[k]
                    similarities = torch.nn.functional.cosine_similarity(
                        atom_emb.unsqueeze(1),
                        proto_embs.unsqueeze(0),
                        dim=2
                    )
                    embedding_score = torch.max(similarities).item()
                    
                    # 第二段：Cross-encoder精确匹配（仅对top候选）
                    # 构建候选列表：原型文本
                    candidate_texts = prototype_texts[k]
                    pairs = [[atom_text, candidate] for candidate in candidate_texts]
                    
                    try:
                        if not pairs:
                            cross_encoder_score = embedding_score
                        else:
                            ce_scores = self.candidate_matcher.predict(
                                pairs, 
                                batch_size=min(8, len(pairs)), 
                                show_progress_bar=False
                            )
                            if isinstance(ce_scores, (list, tuple)):
                                ce_scores = np.array(ce_scores)
                            elif isinstance(ce_scores, torch.Tensor):
                                ce_scores = ce_scores.cpu().numpy()
                            else:
                                ce_scores = np.array(ce_scores)
                            
                            # 归一化Cross-encoder分数
                            if len(ce_scores) == 0:
                                cross_encoder_score = embedding_score
                            elif ce_scores.ndim > 1:
                                # 检查第二维是否为空（防止形状为[1, 0]等异常情况）
                                if ce_scores.shape[1] == 0:
                                    cross_encoder_score = embedding_score
                                else:
                                    ce_scores = torch.softmax(torch.tensor(ce_scores), dim=1)[:, -1].numpy()
                                    cross_encoder_score = float(np.max(ce_scores)) if len(ce_scores) > 0 else embedding_score
                            else:
                                ce_scores = torch.sigmoid(torch.tensor(ce_scores)).numpy()
                                cross_encoder_score = float(np.max(ce_scores)) if len(ce_scores) > 0 else embedding_score
                    
                    except Exception as e:
                        error_msg = (
                            f"Cross-encoder预测失败\n"
                            f"原子文本: {atom_text[:100]}...\n"
                            f"类别: {k}\n"
                            f"候选对数量: {len(pairs)}\n"
                            f"设备: {self.device}\n"
                            f"错误详情: {str(e)}\n"
                            f"可能原因:\n"
                            f"  1. 模型未正确初始化\n"
                            f"  2. 输入数据格式错误\n"
                            f"  3. 设备资源不足（显存/内存）\n"
                            f"  4. 模型推理过程出错"
                        )
                        raise RuntimeError(error_msg) from e
                    
                    # 融合分数（使用初始化时配置的权重）
                    # embedding_score范围：[-1, 1]（余弦相似度）
                    # cross_encoder_score范围：[0, 1]（经过sigmoid/softmax）
                    final_score = self.embedding_weight * embedding_score + self.cross_encoder_weight * cross_encoder_score
                    # 归一化到[0, 1]范围
                    min_score = -self.embedding_weight
                    max_score = 1.0
                    if max_score > min_score:
                        normalized_score = (final_score - min_score) / (max_score - min_score)
                    else:
                        normalized_score = 0.5
                    nli_scores[i][k] = max(0.0, min(1.0, normalized_score))
        except Exception as e:
            error_msg = (
                f"两段式评分失败\n"
                f"原子数量: {len(atom_texts)}\n"
                f"类别: {keys}\n"
                f"设备: {self.device}\n"
                f"错误详情: {str(e)}\n"
                f"可能原因:\n"
                f"  1. Embedding模型调用失败\n"
                f"  2. Cross-encoder模型调用失败\n"
                f"  3. 输入数据格式错误\n"
                f"  4. 设备资源不足（显存/内存）\n"
                f"  5. 模型未正确初始化"
            )
            raise RuntimeError(error_msg) from e
        
        atom_embs = self._encode_with_cache(atom_texts, convert_to_tensor=True, normalize_embeddings=True)
        
        results_map = {i: {"AIM": {}, "CONCLUSION": {}, "METHOD": {}} for i in range(len(atoms))}
        
        # 存储分数（两段式评分）
        for i in range(len(atoms)):
            for k in keys:
                score = nli_scores.get(i, {}).get(k, 0.0)
                results_map[i][k]['nli'] = score
                results_map[i][k]['sentence_id'] = atoms[i].get('sentence_id', -1)
                results_map[i][k]['atom_id'] = atoms[i].get('atom_id', i)
            
        # SEM Score 计算（移除fallback，使用事件分类器替代）
        sem_debug_data = {
            'anchor_exists': self.anchors is not None,
            'anchor_keys': list(self.anchors.keys()) if self.anchors else [],
            'sem_scores_by_cat': {k: [] for k in keys},
            'anchor_matched': {k: [] for k in keys},
            'event_classifier_used': {k: 0 for k in keys}
        }
        
        atom_event_scores = []
        for atom in atoms:
            atom_text = atom.get("atom_text", "").strip()
            original_sentence = atom.get("original_sentence", "").strip()
            
            if atom_text and len(atom_text) > 20:
                text_for_classification = atom_text
            elif original_sentence:
                text_for_classification = original_sentence
            else:
                text_for_classification = atom_text or ""
            
            event_probs = self.event_classifier.classify(text_for_classification)
            atom_event_scores.append(event_probs)
        
        if self.anchors is not None:
            anchor_norms = {}
            anchor_norm_stats = {}
            for k in keys:
                if k in self.anchors:
                    anchor_emb = self.anchors[k]
                    norms = torch.norm(anchor_emb, dim=1).cpu().numpy()
                    anchor_norms[k] = float(norms.mean())
                    anchor_norm_stats[k] = {
                        'mean': float(norms.mean()),
                        'std': float(norms.std()),
                        'min': float(norms.min()),
                        'max': float(norms.max()),
                        'range': float(norms.max() - norms.min())
                    }
            
            # 使用零样本分类器计算SEM分数（替代模板匹配）
            for i, atom in enumerate(atoms):
                atom_text = atom.get("atom_text", "").strip()
                original_sentence = atom.get("original_sentence", "").strip()
                
                # 选择用于分类的文本
                if atom_text and len(atom_text) > 20:
                    text_for_classification = atom_text
                elif original_sentence:
                    text_for_classification = original_sentence
                else:
                    text_for_classification = atom_text or ""
                
                # 使用零样本分类器
                sem_probs = self._classify_sem_zero_shot(text_for_classification)
                
                for k in keys:
                    sem_score = sem_probs.get(k, 0.0)
                    results_map[i][k]['sem'] = sem_score
                    sem_debug_data['sem_scores_by_cat'][k].append(sem_score)
                    sem_debug_data['anchor_matched'][k].append(True)  # 标记为使用分类器
                    results_map[i][k]['_sem_source'] = 'zero_shot_classifier'
        else:
            # anchors不存在时，也使用零样本分类器
            for i, atom in enumerate(atoms):
                atom_text = atom.get("atom_text", "").strip()
                original_sentence = atom.get("original_sentence", "").strip()
                
                if atom_text and len(atom_text) > 20:
                    text_for_classification = atom_text
                elif original_sentence:
                    text_for_classification = original_sentence
                else:
                    text_for_classification = atom_text or ""
                
                sem_probs = self._classify_sem_zero_shot(text_for_classification)
                
                for k in keys:
                    sem_score = sem_probs.get(k, 0.0)
                    results_map[i][k]['sem'] = sem_score
                    sem_debug_data['sem_scores_by_cat'][k].append(sem_score)
                    sem_debug_data['anchor_matched'][k].append(True)
                    results_map[i][k]['_sem_source'] = 'zero_shot_classifier'
        
        # 输出 SEM Score 诊断信息（仅在需要时）
        if any(not all(matched) for matched in sem_debug_data['anchor_matched'].values()) or \
           any(np.mean(scores) < 0.5 for scores in sem_debug_data['sem_scores_by_cat'].values()):
            print(f"\n[SEM Score诊断]")
            print(f"  - Anchor存在: {sem_debug_data['anchor_exists']}")
            print(f"  - Anchor类别: {sem_debug_data['anchor_keys']}")
            
            # Anchor嵌入质量统计（明确统计方法）
            if 'anchor_norm_stats' in locals() and anchor_norm_stats:
                print(f"  - Anchor嵌入质量（norm统计）:")
                for k, stats in anchor_norm_stats.items():
                    print(f"    {k}: 均值={stats['mean']:.3f}, 标准差={stats['std']:.3f}, "
                          f"范围=[{stats['min']:.3f}, {stats['max']:.3f}], 跨度={stats['range']:.3f}")
            
            for k in keys:
                scores = sem_debug_data['sem_scores_by_cat'][k]
                matched = sem_debug_data['anchor_matched'][k]
                if scores:
                    scores_arr = np.array(scores)
                    mean_score = np.mean(scores_arr)
                    std_score = np.std(scores_arr)
                    min_score = np.min(scores_arr)
                    max_score = np.max(scores_arr)
                    median_score = np.median(scores_arr)
                    
                    # 计算分位数
                    p25 = np.percentile(scores_arr, 25)
                    p75 = np.percentile(scores_arr, 75)
                    p90 = np.percentile(scores_arr, 90)
                    p95 = np.percentile(scores_arr, 95)
                    
                    # 计算偏度和峰度（需要scipy，如果没有则跳过）
                    try:
                        from scipy import stats
                        skewness = stats.skew(scores_arr)
                        kurtosis = stats.kurtosis(scores_arr)
                        has_scipy = True
                    except ImportError:
                        has_scipy = False
                    
                    # 计算变异系数（CV）
                    cv = (std_score / mean_score * 100) if mean_score > 0 else 0.0
                    
                    print(f"  - {k}: 平均={mean_score:.3f}, 范围=[{min_score:.3f}, {max_score:.3f}], "
                          f"标准差={std_score:.3f}, 匹配率={sum(matched)/len(matched)*100:.1f}%")
                    print(f"    - 分位数统计: P25={p25:.3f}, 中位数={median_score:.3f}, P75={p75:.3f}, P90={p90:.3f}, P95={p95:.3f}")
                    print(f"    - 变异系数(CV): {cv:.1f}% ({'高变异' if cv > 30 else '中等变异' if cv > 15 else '低变异'})")
                    if has_scipy:
                        print(f"    - 分布特征: 偏度={skewness:.3f} ({'右偏' if skewness > 0.5 else '左偏' if skewness < -0.5 else '对称'}), "
                              f"峰度={kurtosis:.3f} ({'尖峰' if kurtosis > 0.5 else '平峰' if kurtosis < -0.5 else '正态'})")
                    
                    # SEM Score分布直方图数据（分10个桶）
                    hist_bins = np.linspace(0.0, 1.0, 11)
                    hist_counts, _ = np.histogram(scores, bins=hist_bins)
                    hist_percentages = (hist_counts / len(scores) * 100) if len(scores) > 0 else [0] * 10
                    print(f"    - 分布直方图 (10桶):")
                    for i in range(10):
                        bin_start = hist_bins[i]
                        bin_end = hist_bins[i+1]
                        count = int(hist_counts[i])
                        pct = hist_percentages[i]
                        bar = "█" * int(pct / 2)  # 每2%一个字符
                        print(f"      [{bin_start:.1f}-{bin_end:.1f}): {count:2d} ({pct:5.1f}%) {bar}")
                    
                    # 与 anchor 的相似度分析（如果 anchor 存在）
                    if self.anchors is not None and k in self.anchors:
                        anchor_emb = self.anchors[k]
                        atom_embs_for_cat = atom_embs  # 使用所有原子的嵌入
                        if len(atom_embs_for_cat) > 0:
                            # 计算每个原子与每个 anchor 模板的相似度
                            sims_matrix = torch.nn.functional.cosine_similarity(
                                atom_embs_for_cat.unsqueeze(1), anchor_emb.unsqueeze(0), dim=2
                            ).cpu().numpy()
                            max_sims_per_atom = np.max(sims_matrix, axis=1)
                            max_sims_per_template = np.max(sims_matrix, axis=0)
                            
                            print(f"    - Anchor相似度矩阵分析:")
                            print(f"      * 每个原子与最佳模板的相似度: 平均={np.mean(max_sims_per_atom):.3f}, "
                                  f"范围=[{np.min(max_sims_per_atom):.3f}, {np.max(max_sims_per_atom):.3f}]")
                            print(f"      * 每个模板的最佳匹配: {[f'{s:.3f}' for s in max_sims_per_template]}")
                            
                            # 分析匹配模式
                            best_template_indices = np.argmax(sims_matrix, axis=1)
                            template_counts = np.bincount(best_template_indices, minlength=len(anchor_emb))
                            print(f"      * 模板使用分布: {dict(zip(range(len(anchor_emb)), template_counts))}")
                    
                    # 输出低分原子详情（增强版）
                    low_score_indices = [i for i, s in enumerate(scores) if s < 0.5]
                    if low_score_indices:
                        print(f"    ⚠️  低分原子数: {len(low_score_indices)}/{len(scores)} "
                              f"(相似度<0.5，可能匹配不佳)")
                        print(f"    - 异常原子详细分析 (前5个):")
                        for rank, idx in enumerate(low_score_indices[:5], 1):
                            atom = atoms[idx] if idx < len(atoms) else None
                            if atom:
                                atom_text = atom.get("atom_text", "")
                                score_val = scores[idx]
                                atom_len = len(atom_text)
                                
                                # 分析可能的原因
                                reasons = []
                                if score_val < 0.3:
                                    reasons.append("极低相似度")
                                elif score_val < 0.4:
                                    reasons.append("低相似度")
                                
                                if atom_len < 20:
                                    reasons.append("文本过短")
                                elif atom_len > 200:
                                    reasons.append("文本过长")
                                
                                # 检查是否包含专业术语
                                has_scientific_terms = any(char.isupper() and len(word) > 3 
                                                          for word in atom_text.split() 
                                                          for char in word)
                                if has_scientific_terms:
                                    reasons.append("包含专业术语")
                                
                                # 检查是否包含括号（可能影响匹配）
                                if '(' in atom_text or ')' in atom_text:
                                    reasons.append("包含括号")
                                
                                reason_str = ", ".join(reasons) if reasons else "未知原因"
                                
                                print(f"      原子{idx+1} (排名{rank}): SEM={score_val:.3f}, 长度={atom_len}字符")
                                print(f"        文本: '{atom_text[:80]}{'...' if len(atom_text) > 80 else ''}'")
                                print(f"        可能原因: {reason_str}")
                if sem_debug_data['event_classifier_used'][k] > 0:
                    print(f"    - {k}类别使用事件分类器替代: {sem_debug_data['event_classifier_used'][k]}次 "
                          f"(anchor缺失或类别不存在)")
            
                
        return results_map, atom_embs

    def extract(self, raw_text: str, threshold: float = 0.75, mode: str = "core", 
                metrics_monitor: Optional[MetricsMonitor] = None,
                paper_id: str = "", year: int = 2025) -> List[Dict]:
        """语义识别主流程：候选原子抽取 → 原子筛选 → 抽象层构建
        
        Args:
            raw_text: 输入文本
            threshold: 筛选阈值
            mode: 模式（"core"或"full"）
            metrics_monitor: 指标监控器（可选）
            paper_id: 论文ID（可选，用于事件账本）
            year: 论文年份（可选，用于事件账本）
        """
        global _global_metrics_monitor
        
        extract_start_time = time.time()
        stage_times = {}  # 记录各阶段耗时
        function_times = {}  # 记录函数级耗时
        
        # 初始化权重历史记录（用于自适应阈值计算）
        if not hasattr(self, '_weight_history'):
            self._weight_history: List[Dict] = []
        
        print(f"\n{'='*80}")
        print(f"[提取开始] 模式: {mode}, 阈值: {threshold}")
        print(f"[提取开始] 输入文本长度: {len(raw_text)} 字符")
        
        if metrics_monitor is None:
            metrics_monitor = _global_metrics_monitor
        
        metrics_monitor.start_document()
        
        text_process_start = time.time()
        sentences, doc_objects = self._module_1_process_text(raw_text)
        text_process_time = (time.time() - text_process_start) * 1000
        stage_times['文本处理'] = text_process_time
        print(f"[文本处理] 完成，耗时: {text_process_time:.2f}ms, 句子数: {len(sentences)}")
        
        if not sentences:
            print(f"[提取结束] 未找到有效句子，耗时: {(time.time() - extract_start_time)*1000:.2f}ms")
            metrics_monitor.end_document()
            return []
        
        all_maus = []
        srl_count = 0
        
        # SRL 提取阶段（唯一提取路径）
        srl_extract_start = time.time()
        srl_events = []
        for sent_idx, (sent_text, sent_doc) in enumerate(zip(sentences, doc_objects)):
            srl_events_batch = self.srl_module.extract_srl_events(
                sentence=sent_text,
                sentence_id=sent_idx,
                paper_id=paper_id,
                year=year,
                section="abstract"
            )
            srl_events.extend(srl_events_batch)
            
            if srl_events_batch:
                print(f"  [句子 {sent_idx+1}/{len(sentences)}] SRL: 提取到 {len(srl_events_batch)} 个事件")
                for i, event in enumerate(srl_events_batch[:2]):  # 只显示前2个
                    print(f"    - 事件{i+1}: predicate='{event.predicate}', arguments={list(event.arguments.keys())}")
        
        # 事件账本：批量计算embedding并送入队列
        if srl_events and hasattr(self, 'event_ledger_worker'):
            try:
                valid_events = []
                valid_texts = []
                for event in srl_events:
                    if hasattr(event, 'sentence_text') and event.sentence_text and event.sentence_text.strip():
                        valid_events.append(event)
                        valid_texts.append(event.sentence_text)
                
                if valid_events:
                    embeddings = self.emb_model.encode(
                        valid_texts,
                        convert_to_numpy=True,
                        normalize_embeddings=True,
                        show_progress_bar=False
                    )
                    
                    # 验证embeddings数量与事件数量一致
                    if len(embeddings) != len(valid_events):
                        print(f"[警告] 事件账本: embedding数量({len(embeddings)})与事件数量({len(valid_events)})不匹配，跳过此批次")
                    else:
                        for srl_event, embedding_vec in zip(valid_events, embeddings):
                            self.event_ledger_worker.add_task(paper_id, year, srl_event, embedding_vec)
            except Exception as e:
                print(f"[警告] 事件账本处理失败: {e}")
        
        # 将 SRL 事件转换为 MAU 格式
        srl_maus = []
        for srl_event in srl_events:
            # 计算结构评分（更新structure_confidence字段）
            structure_score = compute_srl_structure_score(srl_event)
            # 注意：不在此处硬写confidence，由上层统一计算全局置信度
            
            # 转换为 MAU
            mau = srl_event.to_mau()
            mau.quality_score = self._compute_atom_quality(mau)
            srl_maus.append(mau)
        
        all_maus.extend(srl_maus)
        srl_count = len(srl_maus)
        srl_extract_time = (time.time() - srl_extract_start) * 1000
        stage_times['SRL提取'] = srl_extract_time
        
        extraction_time = (time.time() - extract_start_time) * 1000
        atom_extraction_time = extraction_time - text_process_time
        stage_times['原子提取'] = atom_extraction_time
        
        print(f"\n[SRL提取阶段] 完成")
        print(f"  - 总事件数: {len(srl_events)}")
        print(f"  - 总原子数: {len(all_maus)}")
        print(f"  - 提取耗时: {srl_extract_time:.2f}ms")
        
        # 计算成功提取原子的句子数
        sentences_with_atoms = len([i for i in range(len(sentences)) 
                                   if any(mau.sentence_id == i for mau in all_maus)])
        
        # 提取率诊断
        sentences_without_atoms = []
        for i in range(len(sentences)):
            has_atoms = any(mau.sentence_id == i for mau in all_maus)
            if not has_atoms:
                sentences_without_atoms.append(i)
        
        if sentences_without_atoms:
            print(f"\n[提取率诊断] 未提取事件的句子: {len(sentences_without_atoms)}/{len(sentences)}")
            for sent_idx in sentences_without_atoms[:5]:  # 只显示前5个
                sent_text = sentences[sent_idx]
                print(f"  - 句子 {sent_idx+1}: {sent_text[:80]}{'...' if len(sent_text) > 80 else ''}")
        
        metrics_monitor.record_atom_extraction(
            sentences_count=len(sentences),
            path_a_atoms=0,
            path_b_atoms=0,
            path_c_atoms=srl_count,
            aligned_atoms=0,
            sentences_with_atoms=sentences_with_atoms
        )
        
        if not all_maus:
            print(f"[提取结束] 未提取到原子，总耗时: {(time.time() - extract_start_time)*1000:.2f}ms")
            metrics_monitor.end_document()
            return []
        
        
        document_context = {
            "path_success_rates": {"SRL": 1.0},
            "sentence_complexity": {
                "avg_length": np.mean([len(s) for s in sentences]) if sentences else 0.0,
                "max_length": max([len(s) for s in sentences]) if sentences else 0.0,
                "avg_depth": 0.0
            },
            "dependency_quality": {
                "quality_score": 1.0,
                "confidence": 0.9
            },
            "document_type": "paper",
            "path_coverage": {
                "SRL": (srl_count / len(sentences) * 100) if sentences else 0.0
            }
        }
        
        path_weights = {"SRL": 1.0}  # SRL路径权重固定为1.0
        
        # 步骤4：去重（基于embedding + predicate内匹配）
        dedup_start = time.time()
        deduplicated_maus = self._deduplicate_srl_atoms(all_maus, similarity_threshold=0.75)
        dedup_time_ms = (time.time() - dedup_start) * 1000
        stage_times['去重'] = dedup_time_ms
        dedup_count = len(all_maus) - len(deduplicated_maus)
        
        if dedup_count > 0:
            print(f"  - 去重耗时: {dedup_time_ms:.2f}ms, 去重数量: {dedup_count}")
        
        alignment_start = time.time()
        # 禁用跨predicate语义对齐（提高稳定性）
        aligned_maus = self.agg_layer.align_maus(
            deduplicated_maus, 
            path_weights=path_weights,
            enable_cross_predicate=False,  # 禁用跨predicate语义对齐
            predicate_sim_threshold=0.82  # predicate语义相似度阈值（保留参数但不使用）
        )
        alignment_time_ms = (time.time() - alignment_start) * 1000
        stage_times['原子对齐'] = alignment_time_ms
        merged_count = len(deduplicated_maus) - len(aligned_maus)
        
        print(f"\n[原子对齐阶段] 完成")
        print(f"  - 去重后原子数: {len(deduplicated_maus)}")
        print(f"  - 对齐前: {len(deduplicated_maus)} 个原子")
        print(f"  - 对齐后: {len(aligned_maus)} 个原子")
        print(f"  - 合并数: {merged_count} 个")
        print(f"  - 对齐耗时: {alignment_time_ms:.2f}ms")
        print(f"  - 跨predicate对齐: 已禁用（提高稳定性）")
        
        for mau in deduplicated_maus:
            self.weight_model.update_history("SRL", True)
        
        metrics_monitor.record_alignment(
            total_maus=len(deduplicated_maus),
            aligned_maus=len(aligned_maus),
            merged_count=merged_count,
            alignment_time_ms=alignment_time_ms
        )
        
        metrics_monitor.metrics["atom_extraction"]["aligned_atoms"] = len(aligned_maus)
        
        if self.confidence_model and self.confidence_model.is_trained:
            calibrated_count = 0
            for mau in aligned_maus:
                original_conf = mau.confidence
                calibrated_conf = self.confidence_model.predict(mau, mau.original_sentence)
                if calibrated_conf is not None:
                    calibrated_conf = max(0.0, min(1.0, float(calibrated_conf)))  # 限制在[0,1]
                    mau.confidence = calibrated_conf
                    if abs(original_conf - calibrated_conf) > 0.05:
                        calibrated_count += 1
        
        confidence_filter_start = time.time()
        high_conf_maus, low_conf_maus = self.low_conf_handler.filter_low_confidence(aligned_maus)
        confidence_filter_time = (time.time() - confidence_filter_start) * 1000
        stage_times['置信度筛选'] = confidence_filter_time
        
        low_conf_by_path = defaultdict(int)
        for mau in low_conf_maus:
            low_conf_by_path[mau.source_path] += 1
        
        print(f"\n[置信度筛选阶段] 完成")
        print(f"  - 高置信度: {len(high_conf_maus)} 个")
        print(f"  - 低置信度: {len(low_conf_maus)} 个 (按路径: {dict(low_conf_by_path)})")
        
        metrics_monitor.record_low_confidence(
            total_atoms=len(aligned_maus),
            low_confidence_count=len(low_conf_maus),
            by_source_path=dict(low_conf_by_path)
        )
        
        if high_conf_maus:
            self.cross_doc_normalizer.add_document_atoms(high_conf_maus, document_id=None)
        
        atoms = []
        for idx, mau in enumerate(high_conf_maus):
            atom_dict = mau.to_dict()
            if "atom_id" not in atom_dict:
                atom_dict["atom_id"] = idx
            atoms.append(atom_dict)
        
        if not atoms:
            print(f"[提取结束] 高置信度原子为空，总耗时: {(time.time() - extract_start_time)*1000:.2f}ms")
            metrics_monitor.end_document()
            metrics_monitor.check_and_alert()
            return []
        
        hard_rule_start = time.time()
        hard_rule_filtered = []
        hard_rule_filtered_count = 0
        hard_rule_reasons = defaultdict(int)
        for i, atom in enumerate(atoms):
            is_violation, reason = self.hard_rule_filter.check(atom)
            if is_violation:
                hard_rule_filtered_count += 1
                hard_rule_reasons[reason] += 1
                continue
            hard_rule_filtered.append((i, atom))
        hard_rule_time = (time.time() - hard_rule_start) * 1000
        stage_times['硬规则筛选'] = hard_rule_time
        
        if hard_rule_filtered_count > 0:
            print(f"\n[硬规则筛选阶段] 完成")
            print(f"  - 过滤前: {len(atoms)} 个原子")
            print(f"  - 过滤后: {len(hard_rule_filtered)} 个原子")
            print(f"  - 过滤数: {hard_rule_filtered_count} 个")
            if hard_rule_reasons:
                print(f"  - 过滤原因: {dict(hard_rule_reasons)}")
        
        
        if not hard_rule_filtered:
            metrics_monitor.end_document()
            metrics_monitor.check_and_alert()
            return []
        
        structure_detected = []
        structure_filtered_count = 0
        structure_start = time.time()
        for idx, atom in hard_rule_filtered:
            original_sentence = atom.get("original_sentence", "")
            structure_result = self.structure_detector.detect_structure(atom, original_sentence)
            
            if not structure_result['has_structure']:
                structure_filtered_count += 1
                continue
            
            structure_detected.append((idx, atom, structure_result))
        
        structure_time = (time.time() - structure_start) * 1000
        stage_times['结构检测'] = structure_time
        if structure_filtered_count > 0 or structure_detected:
            print(f"\n[结构检测阶段] 完成")
            print(f"  - 检测前: {len(hard_rule_filtered)} 个原子")
            print(f"  - 检测后: {len(structure_detected)} 个原子")
            print(f"  - 过滤数: {structure_filtered_count} 个")
            print(f"  - 检测耗时: {structure_time:.2f}ms")
        
        
        if not structure_detected:
            metrics_monitor.end_document()
            metrics_monitor.check_and_alert()
            return []
        
        quality_quantified = []
        quality_start = time.time()
        for idx, atom, structure_result in structure_detected:
            context_atoms = [a for other_idx, a, _ in structure_detected if other_idx != idx][:10]
            
            quality_result = self.quality_quantifier.quantify(atom, context_atoms)
            
            overall_quality = (
                structure_result['completeness_score'] * 0.5 +
                quality_result['overall_quality'] * 0.5
            )
            
            atom['semantic_quality_coefficient'] = overall_quality
            atom['semantic_quality_details'] = {
                'structure_completeness': structure_result['completeness_score'],
                'structure_type': structure_result['structure_type'],
                'specificity': quality_result['specificity'],
                'information_gain': quality_result['information_gain'],
                'saturation': quality_result['saturation'],
                'overall_quality': quality_result['overall_quality'],
                'final_quality_coefficient': overall_quality
            }
            
            quality_quantified.append((idx, atom, overall_quality))
        
        quality_time = (time.time() - quality_start) * 1000
        stage_times['质量量化'] = quality_time
        if quality_quantified:
            avg_quality = np.mean([q for _, _, q in quality_quantified])
            print(f"\n[质量量化阶段] 完成")
            print(f"  - 量化原子数: {len(quality_quantified)} 个")
            print(f"  - 平均质量系数: {avg_quality:.3f}")
            print(f"  - 量化耗时: {quality_time:.2f}ms")
            
        
        
        atoms = [atom for idx, atom, _ in quality_quantified]
        
        
        if not atoms:
            metrics_monitor.end_document()
            metrics_monitor.check_and_alert()
            return []
        
        scoring_start = time.time()
        scores_map, atom_embs_all = self._module_2_3_compute_scores(atoms, sentences=sentences)
        
        # 添加 SRL 结构评分（用于排序和优先级，不做绝对过滤）
        for i, atom in enumerate(atoms):
            srl_arguments = atom.get("srl_arguments", {})
            if srl_arguments:  # 如果是 SRL 事件
                # 确保srl_arguments是列表格式（兼容旧格式）
                normalized_arguments = {}
                for k, v in srl_arguments.items():
                    if isinstance(v, list):
                        normalized_arguments[k] = v
                    else:
                        # 兼容旧格式（字符串），转换为列表
                        normalized_arguments[k] = [v] if v else []
                
                srl_event = SRLEventUnit(
                    paper_id=atom.get("paper_id", ""),
                    year=atom.get("year", 2025),
                    section=atom.get("section", "abstract"),
                    sentence_text=atom.get("original_sentence", ""),
                    predicate=atom.get("srl_predicate"),
                    arguments=normalized_arguments,
                    sentence_id=atom.get("sentence_id", -1),
                    original_sentence=atom.get("original_sentence", ""),
                    confidence=atom.get("confidence", 0.0),
                    source_path=atom.get("source_path", "SRL"),
                    # 从atom字典恢复新字段（如果有）
                    has_srl_structure=atom.get("has_srl_structure", bool(atom.get("srl_predicate") or normalized_arguments)),
                    low_info_predicate=atom.get("low_info_predicate", False),
                    structure_confidence=atom.get("structure_confidence", 0.0),
                    logical_agent=atom.get("logical_agent"),
                    logical_patient=atom.get("logical_patient")
                )
                structure_score = compute_srl_structure_score(srl_event)
                atom['srl_structure_score'] = structure_score
                # 将结构评分作为加分项（仅用于排序，不直接过滤）
                # 在最终得分计算时会考虑这个评分
        
        scoring_time = (time.time() - scoring_start) * 1000
        stage_times['评分计算'] = scoring_time
        
        # 诊断统计：NLI分数分布（用于监控NLI权重下降的影响）
        nli_scores_all = []
        for i in range(len(atoms)):
            for cat in ["AIM", "CONCLUSION", "METHOD"]:
                nli_score = scores_map[i][cat].get('nli', 0.0)
                nli_scores_all.append(nli_score)
        
        if nli_scores_all:
            nli_mean = np.mean(nli_scores_all)
            nli_std = np.std(nli_scores_all)
            nli_low_count = sum(1 for s in nli_scores_all if s < 0.3)
            print(f"\n[评分计算阶段] 完成")
            print(f"  - 评分原子数: {len(atoms)} 个")
            print(f"  - 评分耗时: {scoring_time:.2f}ms")
            print(f"  - NLI分数统计: 平均={nli_mean:.3f}, 标准差={nli_std:.3f}, 低分(<0.3)={nli_low_count}/{len(nli_scores_all)}")
            if nli_low_count / len(nli_scores_all) > 0.3:
                print(f"    ⚠️  注意: NLI低分比例较高 ({nli_low_count/len(nli_scores_all)*100:.1f}%)，可能影响最终评分")
        
        filtered_atoms_list = []
        all_scores = []
        atom_best_cats = []  # 保存每个原子的最佳类别
        
        # 诊断数据收集
        diagnostic_data = {
            'base_scores': [],
            'nli_scores': [],
            'sem_scores': [],
            'rule_scores': [],
            'position_bonuses': [],
            'quality_bonuses': [],
            'quality_coefficients': [],
            'final_scores': []
        }

        print(f"{'='*80}")

        # 启用规则调试（仅在需要时）
        rule_debug_enabled = False  # 可以通过参数控制
        rule_coverage_stats = {
            'total_atoms': len(atoms),
            'atoms_with_rules': 0,
            'atoms_by_category': {'AIM': 0, 'CONCLUSION': 0, 'METHOD': 0},
            'matched_keywords_by_atom': []
        }
        
        for i, atom in enumerate(atoms):
            rules = self._module_4_apply_rules(atom)
            
            # 统计Event Score覆盖率（事件分类器总是输出分数，使用阈值判断）
            # 使用0.3作为有效阈值（低于此值认为分类器不确定）
            has_any_event = any(score >= 0.3 for score in rules.values())
            if has_any_event:
                rule_coverage_stats['atoms_with_rules'] += 1
                for cat, score in rules.items():
                    if score >= 0.3:  # 使用阈值而非>0
                        rule_coverage_stats['atoms_by_category'][cat] += 1
            
            # 记录匹配的关键词（用于总览表格）
            matched_keywords = atom.get('_rule_matched_keywords', {})
            rule_coverage_stats['matched_keywords_by_atom'].append({
                'atom_id': i + 1,
                'atom_text_preview': atom.get("atom_text", "")[:50],
                'rule_scores': rules.copy(),
                'matched_keywords': matched_keywords
            })
            
            # 事件分类器诊断日志
            if rule_debug_enabled or (rules["AIM"] < 0.3 and rules["CONCLUSION"] < 0.3 and rules["METHOD"] < 0.3):
                atom_text_preview = atom.get("atom_text", "")[:60]
                print(f"  [Event诊断] 原子{i+1}: {atom_text_preview}...")
                print(f"    - 事件分类分数: AIM={rules['AIM']:.3f}, CONCLUSION={rules['CONCLUSION']:.3f}, METHOD={rules['METHOD']:.3f}")
                event_probs = atom.get('_event_classifier_probs', {})
                if event_probs:
                    print(f"    - 完整分类概率: {event_probs}")
                print(f"    - 原子文本长度: {len(atom.get('atom_text', ''))}")
                print(f"    - 原始句子长度: {len(atom.get('original_sentence', ''))}")
            
            best_cat = None
            best_final_score = -1.0
            score_details = {}
            
            for cat in ["AIM", "CONCLUSION", "METHOD"]:
                nli_score = scores_map[i][cat]['nli']
                sem_score = scores_map[i][cat]['sem']
                event_score = rules[cat]  # 事件分类器分数（已替代关键词匹配）
                
                # 自适应权重机制：根据SEM Score信度动态调整权重
                # 使用基于历史分布的自适应阈值（如果可用）
                if hasattr(self, '_weight_history') and self._weight_history:
                    hist_sem_scores = [r['sem_score'] for r in self._weight_history]
                    if len(hist_sem_scores) >= 10:  # 至少需要10条历史记录
                        p25_threshold = np.percentile(hist_sem_scores, 25)
                        p50_threshold = np.percentile(hist_sem_scores, 50)
                        # 使用P25和P50作为阈值
                        low_threshold = min(0.5, p25_threshold)  # 不超过0.5
                        medium_threshold = min(0.6, p50_threshold)  # 不超过0.6
                    else:
                        # 历史数据不足，使用固定阈值
                        low_threshold = 0.5
                        medium_threshold = 0.6
                else:
                    # 无历史数据，使用固定阈值
                    low_threshold = 0.5
                    medium_threshold = 0.6
                
                # 根据自适应阈值调整权重
                if sem_score < low_threshold:
                    # SEM信度低：降低SEM权重，提高NLI和Event权重
                    sem_weight = 0.20  # 从0.35降低到0.20
                    nli_weight = 0.25  # 从0.20提高到0.25
                    event_weight = 0.55  # 从0.45提高到0.55
                    sem_confidence_flag = "low"  # 标记为低置信度
                elif sem_score < medium_threshold:
                    # SEM信度中等：适度降低SEM权重
                    sem_weight = 0.28  # 从0.35降低到0.28
                    nli_weight = 0.22  # 从0.20提高到0.22
                    event_weight = 0.50  # 从0.45提高到0.50
                    sem_confidence_flag = "medium"
                else:
                    # SEM信度高：使用标准权重
                    sem_weight = 0.35
                    nli_weight = 0.20
                    event_weight = 0.45
                    sem_confidence_flag = "high"
                
                # 记录权重变化历史（用于自适应阈值计算）
                if not hasattr(self, '_weight_history'):
                    self._weight_history = []
                self._weight_history.append({
                    'timestamp': time.time(),
                    'sem_score': sem_score,
                    'sem_weight': sem_weight,
                    'nli_weight': nli_weight,
                    'event_weight': event_weight,
                    'confidence': sem_confidence_flag
                })
                # 限制历史记录数量
                if len(self._weight_history) > 1000:
                    self._weight_history = self._weight_history[-1000:]
                
                # 计算基础分数（使用自适应权重）
                base_score = (nli_score * nli_weight) + (event_score * event_weight) + (max(0, sem_score) * sem_weight)
                
                # 记录SEM置信度标志（用于异常标注）
                if 'sem_confidence' not in score_details:
                    score_details['sem_confidence'] = sem_confidence_flag
                    score_details['sem_weight_used'] = sem_weight
                    score_details['is_sem_anomaly'] = (sem_score < 0.5)
                
                sentence_id = scores_map[i][cat]['sentence_id']
                position_bonus = 0.0
                if sentence_id == 0 and cat == "AIM": 
                    base_score += 0.1
                    position_bonus = 0.1
                if sentence_id == len(sentences) - 1 and cat == "CONCLUSION": 
                    base_score += 0.1
                    position_bonus = 0.1
                
                # 质量系数改为加权相加，而非乘法惩罚
                semantic_quality_coefficient = atom.get('semantic_quality_coefficient', 1.0)
                if semantic_quality_coefficient >= 0.85:
                    # 高质量：非线性增长，激励更明显
                    quality_bonus = 0.15 + (semantic_quality_coefficient - 0.85) * 0.67  # 0.85-1.0映射到0.15-0.25
                elif semantic_quality_coefficient >= 0.7:
                    # 中等质量：线性增长
                    quality_bonus = 0.08 + (semantic_quality_coefficient - 0.7) * 0.47  # 0.7-0.85映射到0.08-0.15
                else:
                    # 低质量：最小bonus
                    quality_bonus = (semantic_quality_coefficient - 0.5) * 0.4  # 0.5-0.7映射到0-0.08
                
                quality_bonus = max(0.0, min(0.25, quality_bonus))  # 限制在0-0.25（提高上限）
                
                # SRL 结构评分加分（仅用于排序，不做绝对过滤）
                structure_bonus = 0.0
                srl_structure_score = atom.get('srl_structure_score', 0.0)
                if srl_structure_score > 0:
                    # 结构评分作为加分项：完整结构（ARG0+Predicate+ARG1）得高分
                    structure_bonus = srl_structure_score * 0.1  # 最多加0.1分
                
                final_score_with_quality = base_score + quality_bonus + structure_bonus
                
                score_details[cat] = {
                    'nli': nli_score,
                    'sem': sem_score,
                    'event': event_score,  # 事件分类器分数（替代rule_score）
                    'position_bonus': position_bonus,
                    'base': base_score,
                    'quality_coefficient': semantic_quality_coefficient,
                    'quality_bonus': quality_bonus,
                    'final_with_quality': final_score_with_quality
                }
                
                final_score = final_score_with_quality
                
                if final_score > best_final_score:
                    best_final_score = final_score
                    best_cat = cat
            
            # 收集最佳类别的诊断数据
            if best_cat:
                best_details = score_details[best_cat]
                diagnostic_data['base_scores'].append(best_details['base'])
                diagnostic_data['nli_scores'].append(best_details['nli'])
                diagnostic_data['sem_scores'].append(best_details['sem'])
                diagnostic_data['rule_scores'].append(best_details['event'])  # 使用事件分类器分数
                diagnostic_data['position_bonuses'].append(best_details['position_bonus'])
                diagnostic_data['quality_bonuses'].append(best_details['quality_bonus'])
                diagnostic_data['quality_coefficients'].append(best_details['quality_coefficient'])
                diagnostic_data['final_scores'].append(best_final_score)
            
            all_scores.append(best_final_score)
            
            if best_cat is None:
                best_cat = "METHOD"
            
            atom_best_cats.append(best_cat)
            
            should_include = True
            if mode == "core":
                should_include = best_final_score >= threshold
            
            
            if should_include:
                filtered_idx = len(filtered_atoms_list)
                filtered_atoms_list.append({
                    "id": i + 1,
                    "category": best_cat,
                    "confidence": round(best_final_score, 3),
                    "atom_text": atom["atom_text"],
                    "original_sentence": atom["original_sentence"],
                    "sentence_id": atom.get("sentence_id", -1),
                    "atom_id": atom.get("atom_id", i),
                    "atom_type": atom.get("atom_type"),
                    "original_nli_prob": round(scores_map[i][best_cat]['nli'], 3)
                })
        
        threshold_filter_start = time.time()
        
        # 输出诊断信息
        print(f"\n[评分诊断] 得分分布分析")
        if diagnostic_data['base_scores']:
            print(f"  - Base Score: 平均={np.mean(diagnostic_data['base_scores']):.3f}, "
                  f"中位数={np.median(diagnostic_data['base_scores']):.3f}, "
                  f"范围=[{np.min(diagnostic_data['base_scores']):.3f}, {np.max(diagnostic_data['base_scores']):.3f}]")
            print(f"  - NLI Score: 平均={np.mean(diagnostic_data['nli_scores']):.3f}, "
                  f"范围=[{np.min(diagnostic_data['nli_scores']):.3f}, {np.max(diagnostic_data['nli_scores']):.3f}]")
            print(f"  - SEM Score: 平均={np.mean(diagnostic_data['sem_scores']):.3f}, "
                  f"范围=[{np.min(diagnostic_data['sem_scores']):.3f}, {np.max(diagnostic_data['sem_scores']):.3f}], "
                  f"标准差={np.std(diagnostic_data['sem_scores']):.3f}")
            print(f"  - Event Score (事件分类器): 平均={np.mean(diagnostic_data['rule_scores']):.3f}, "
                  f"范围=[{np.min(diagnostic_data['rule_scores']):.3f}, {np.max(diagnostic_data['rule_scores']):.3f}]")
            # Event Score覆盖率统计（增强版）
            if 'rule_coverage_stats' in locals():
                coverage_rate = (rule_coverage_stats['atoms_with_rules'] / rule_coverage_stats['total_atoms'] * 100) if rule_coverage_stats['total_atoms'] > 0 else 0.0
                unmatched_rate = 100.0 - coverage_rate
                print(f"  - Event Score覆盖率: {rule_coverage_stats['atoms_with_rules']}/{rule_coverage_stats['total_atoms']} = {coverage_rate:.1f}%")
                print(f"  - 低分原子占比: {rule_coverage_stats['total_atoms'] - rule_coverage_stats['atoms_with_rules']}/{rule_coverage_stats['total_atoms']} = {unmatched_rate:.1f}%")
                print(f"    - 按类别: AIM={rule_coverage_stats['atoms_by_category']['AIM']}, "
                      f"CONCLUSION={rule_coverage_stats['atoms_by_category']['CONCLUSION']}, "
                      f"METHOD={rule_coverage_stats['atoms_by_category']['METHOD']}")
            print(f"  - Position Bonus: 平均={np.mean(diagnostic_data['position_bonuses']):.3f}, "
                  f"非零数={sum(1 for b in diagnostic_data['position_bonuses'] if b > 0)}/{len(diagnostic_data['position_bonuses'])}")
            print(f"  - Quality Bonus: 平均={np.mean(diagnostic_data['quality_bonuses']):.3f}, "
                  f"范围=[{np.min(diagnostic_data['quality_bonuses']):.3f}, {np.max(diagnostic_data['quality_bonuses']):.3f}]")
            print(f"  - Quality Coefficient: 平均={np.mean(diagnostic_data['quality_coefficients']):.3f}, "
                  f"范围=[{np.min(diagnostic_data['quality_coefficients']):.3f}, {np.max(diagnostic_data['quality_coefficients']):.3f}]")
            print(f"  - Final Score: 平均={np.mean(diagnostic_data['final_scores']):.3f}, "
                  f"范围=[{np.min(diagnostic_data['final_scores']):.3f}, {np.max(diagnostic_data['final_scores']):.3f}]")
            
            # 诊断建议
            avg_base = np.mean(diagnostic_data['base_scores'])
            avg_quality_bonus = np.mean(diagnostic_data['quality_bonuses'])
            avg_final = np.mean(diagnostic_data['final_scores'])
            
            if avg_base < 0.60:
                print(f"  ⚠️  诊断: Base Score偏低 (平均{avg_base:.3f} < 0.60)，建议优化NLI/SEM/Rule评分模块")
            if avg_quality_bonus < 0.10:
                print(f"  ⚠️  诊断: Quality Bonus偏低 (平均{avg_quality_bonus:.3f} < 0.10)，质量系数可能未充分生效")
            if avg_final < threshold * 0.9:
                print(f"  ⚠️  诊断: Final Score分布偏低 (平均{avg_final:.3f} < 阈值{threshold}*0.9)，建议调整阈值或优化评分")
        
        # 自适应阈值调整（增强日志）
        adaptive_threshold = threshold
        original_filtered_count = len(filtered_atoms_list)
        
        if all_scores and mode == "core":
            score_mean = np.mean(all_scores)
            score_median = np.median(all_scores)
            score_p75 = np.percentile(all_scores, 75, method='linear')  # 明确使用线性插值
            threshold_trigger = threshold * 0.9
            
            # 详细日志：显示触发条件验证（增强版）
            sorted_scores = sorted(all_scores)
            p75_index = int(len(all_scores) * 0.75)  # P75的索引位置
            if p75_index >= len(all_scores):
                p75_index = len(all_scores) - 1
            
            print(f"\n[自适应阈值验证]")
            print(f"  - 原子总数: {len(all_scores)}")
            print(f"  - 得分列表（排序后）: {[round(s, 3) for s in sorted_scores]}")
            print(f"  - P75计算: 索引={p75_index}/{len(all_scores)-1}, 值={score_p75:.3f} (线性插值)")
            print(f"  - 得分分布: 平均={score_mean:.3f}, 中位数={score_median:.3f}, P75={score_p75:.3f}")
            print(f"  - 触发条件: P75 ({score_p75:.3f}) < 阈值*0.9 ({threshold_trigger:.3f})")
            print(f"  - 条件满足: {score_p75 < threshold_trigger}")
            
            # 记录调整前Base Score分布
            if diagnostic_data['base_scores']:
                base_before = {
                    'mean': np.mean(diagnostic_data['base_scores']),
                    'median': np.median(diagnostic_data['base_scores']),
                    'min': np.min(diagnostic_data['base_scores']),
                    'max': np.max(diagnostic_data['base_scores'])
                }
            
            # 如果得分分布明显偏低，自动调整阈值
            if score_p75 < threshold_trigger:
                old_threshold = threshold
                adaptive_threshold = max(threshold * 0.85, score_p75 * 0.95)
                print(f"\n[自适应阈值] 检测到得分分布偏低，调整阈值: {old_threshold:.3f} → {adaptive_threshold:.3f}")
                print(f"  - 调整策略: max(阈值*0.85={threshold*0.85:.3f}, P75*0.95={score_p75*0.95:.3f})")
                print(f"  - 调整前筛选数: {original_filtered_count}/{len(atoms)}")
                
                # 重新筛选（保留最佳类别信息）
                filtered_atoms_list = []
                for i, atom in enumerate(atoms):
                    if all_scores[i] >= adaptive_threshold:
                        best_cat = atom_best_cats[i] if i < len(atom_best_cats) else "METHOD"
                        filtered_atoms_list.append({
                            "id": i + 1,
                            "category": best_cat,
                            "confidence": round(all_scores[i], 3),
                            "atom_text": atom["atom_text"],
                            "original_sentence": atom["original_sentence"],
                            "sentence_id": atom.get("sentence_id", -1),
                            "atom_id": atom.get("atom_id", i),
                            "atom_type": atom.get("atom_type"),
                            "original_nli_prob": round(scores_map[i][best_cat]['nli'], 3) if best_cat in scores_map[i] else 0.0
                        })
                
                print(f"  - 调整后筛选数: {len(filtered_atoms_list)}/{len(atoms)}")
                print(f"  - 筛选数量变化: {len(filtered_atoms_list) - original_filtered_count} 个原子")
                
                # 输出通过率百分比
                pass_rate_before = (original_filtered_count / len(atoms) * 100) if len(atoms) > 0 else 0.0
                pass_rate_after = (len(filtered_atoms_list) / len(atoms) * 100) if len(atoms) > 0 else 0.0
                print(f"  - 通过率对比: 调整前={pass_rate_before:.1f}%, 调整后={pass_rate_after:.1f}%, "
                      f"提升={pass_rate_after - pass_rate_before:.1f}%")
                if abs(pass_rate_after - pass_rate_before) < 5.0:
                    print(f"    ⚠️  通过率变化很小，阈值调整可能不够灵敏")
                
                # 记录调整后Base Score分布（仅筛选后的原子）
                if filtered_atoms_list and diagnostic_data['base_scores']:
                    filtered_base_scores = [diagnostic_data['base_scores'][i] for i in range(len(atoms)) 
                                           if all_scores[i] >= adaptive_threshold]
                    if filtered_base_scores:
                        base_after = {
                            'mean': np.mean(filtered_base_scores),
                            'median': np.median(filtered_base_scores),
                            'min': np.min(filtered_base_scores),
                            'max': np.max(filtered_base_scores)
                        }
                        print(f"  - Base Score分布对比:")
                        print(f"    调整前: 平均={base_before['mean']:.3f}, 中位数={base_before['median']:.3f}, "
                              f"范围=[{base_before['min']:.3f}, {base_before['max']:.3f}]")
                        print(f"    调整后: 平均={base_after['mean']:.3f}, 中位数={base_after['median']:.3f}, "
                              f"范围=[{base_after['min']:.3f}, {base_after['max']:.3f}]")
            else:
                print(f"  - 阈值未调整: P75 ({score_p75:.3f}) >= 触发阈值 ({threshold_trigger:.3f})")
        
        threshold_filter_time = (time.time() - threshold_filter_start) * 1000
        stage_times['阈值筛选'] = threshold_filter_time
        
        print(f"\n[阈值筛选阶段] 完成")
        print(f"  - 筛选前: {len(atoms)} 个原子")
        print(f"  - 筛选后: {len(filtered_atoms_list)} 个原子 (阈值: {adaptive_threshold:.3f})")
        print(f"  - 平均得分: {np.mean(all_scores):.3f} (最高: {max(all_scores):.3f}, 最低: {min(all_scores):.3f})")
        print(f"  - 筛选耗时: {threshold_filter_time:.2f}ms")
        
        # 总览表格：列出每条原子的关键指标（增强版）
        if len(atoms) <= 20:  # 只对少量原子显示详细表格
            print(f"\n[原子总览表格]")
            print(f"{'ID':<4} {'类别':<12} {'Final':<7} {'Base':<7} {'Event':<7} {'SEM':<7} {'NLI':<7} {'Pos':<5} {'Qty':<5} {'提取':<6}")
            print(f"{'-'*4} {'-'*12} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*5} {'-'*5} {'-'*6}")
            for i, atom in enumerate(atoms):
                best_cat = atom_best_cats[i] if i < len(atom_best_cats) else "METHOD"
                final_score = all_scores[i]
                base_score = diagnostic_data['base_scores'][i] if i < len(diagnostic_data['base_scores']) else 0.0
                event_score = diagnostic_data['rule_scores'][i] if i < len(diagnostic_data['rule_scores']) else 0.0
                sem_score = diagnostic_data['sem_scores'][i] if i < len(diagnostic_data['sem_scores']) else 0.0
                nli_score = diagnostic_data['nli_scores'][i] if i < len(diagnostic_data['nli_scores']) else 0.0
                pos_bonus = diagnostic_data['position_bonuses'][i] if i < len(diagnostic_data['position_bonuses']) else 0.0
                qty_bonus = diagnostic_data['quality_bonuses'][i] if i < len(diagnostic_data['quality_bonuses']) else 0.0
                extracted = "✓" if final_score >= adaptive_threshold else "✗"
                
                print(f"{i+1:<4} {best_cat:<12} {final_score:<7.3f} {base_score:<7.3f} {event_score:<7.3f} "
                      f"{sem_score:<7.3f} {nli_score:<7.3f} {pos_bonus:<5.2f} {qty_bonus:<5.2f} {extracted:<6}")
        else:
            # 原子数量较多时，提供摘要统计
            print(f"\n[原子总览摘要] 原子数量较多({len(atoms)})，显示摘要统计")
            extracted_count = sum(1 for score in all_scores if score >= adaptive_threshold)
            print(f"  - 总原子数: {len(atoms)}")
            print(f"  - 提取通过: {extracted_count} ({extracted_count/len(atoms)*100:.1f}%)")
            print(f"  - 平均得分: Final={np.mean(all_scores):.3f}, Base={np.mean(diagnostic_data['base_scores']):.3f}, "
                  f"Event={np.mean(diagnostic_data['rule_scores']):.3f}, SEM={np.mean(diagnostic_data['sem_scores']):.3f}")
            print(f"  - 类别分布: ", end="")
            cat_counts = {}
            for cat in atom_best_cats:
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
            print(", ".join([f"{k}={v}" for k, v in sorted(cat_counts.items())]))
            
            # 提供CSV导出建议
            print(f"  - 提示: 如需详细表格，可导出CSV文件查看")

        if not filtered_atoms_list:
            print(f"[提取结束] 阈值筛选后无原子，总耗时: {(time.time() - extract_start_time)*1000:.2f}ms")
            return []

        concept_start = time.time()
        concept_embeddings = self._compute_concept_embeddings(filtered_atoms_list)
        concept_to_atoms, atom_to_concept = self._map_atoms_to_concepts(filtered_atoms_list)
        concept_time = (time.time() - concept_start) * 1000
        stage_times['概念映射'] = concept_time
        print(f"\n[概念映射阶段] 完成")
        print(f"  - 概念嵌入数: {len(concept_embeddings)}")
        print(f"  - 概念映射耗时: {concept_time:.2f}ms")
        
        if len(concept_embeddings) != len(filtered_atoms_list):
            min_len = min(len(concept_embeddings), len(filtered_atoms_list))
            concept_embeddings = concept_embeddings[:min_len]
            filtered_atoms_list = filtered_atoms_list[:min_len]
            print(f"  - 警告: 概念嵌入与原子数量不匹配，已截断到 {min_len}")
        
        
        cluster_start = time.time()
        clusters = self.hierarchical_clustering.cluster_atoms(
            filtered_atoms_list,
            threshold_level1=0.75,
            threshold_level2=0.80,
            threshold_level3=0.85
        )
        cluster_time = (time.time() - cluster_start) * 1000
        stage_times['聚类'] = cluster_time
        
        cluster_sizes = [len(cluster) for cluster in clusters if cluster]
        print(f"\n[聚类阶段] 完成")
        print(f"  - 聚类数: {len(clusters)}")
        if cluster_sizes:
            print(f"  - 聚类大小: 平均={np.mean(cluster_sizes):.1f}, 最大={max(cluster_sizes)}, 最小={min(cluster_sizes)}")
        else:
            print(f"  - 聚类大小: 无聚类 (原子数: {len(filtered_atoms_list)})")
        print(f"  - 聚类耗时: {cluster_time:.2f}ms")
        
        metrics_monitor.record_clustering(
            total_atoms=len(filtered_atoms_list),
            clusters=len(clusters),
            cluster_sizes=cluster_sizes
        )
        
        if not clusters:
            print(f"[提取结束] 聚类后无结果，总耗时: {(time.time() - extract_start_time)*1000:.2f}ms")
            if len(filtered_atoms_list) == 1:
                print(f"  - 原因: 仅剩1个原子，无法进行聚类（需要至少2个原子）")
            elif len(filtered_atoms_list) == 0:
                print(f"  - 原因: 无可用原子")
            else:
                print(f"  - 原因: {len(filtered_atoms_list)}个原子无法形成聚类（相似度阈值过高或原子差异过大）")
            metrics_monitor.end_document()
            return filtered_atoms_list
        
        theme_roles = self._module_6_theme_role_detection(clusters, filtered_atoms_list, sentences)
        
        theme_fusion_start = time.time()
        fused_clusters = self._module_5_5_theme_fusion(clusters, filtered_atoms_list, concept_embeddings, theme_roles)
        theme_fusion_time = (time.time() - theme_fusion_start) * 1000
        stage_times['主题融合'] = theme_fusion_time
        
        fused_theme_roles = {}
        for new_id, new_cluster in enumerate(fused_clusters):
            if not new_cluster:
                fused_theme_roles[new_id] = "FINDING"
                continue
            candidate_roles = []
            for old_id, old_cluster in enumerate(clusters):
                if old_cluster and set(old_cluster).issubset(set(new_cluster)):
                    role = theme_roles.get(old_id, "FINDING")
                    candidate_roles.append(role)
            
            if "MECHANISM" in candidate_roles:
                fused_theme_roles[new_id] = "MECHANISM"
            elif candidate_roles:
                fused_theme_roles[new_id] = candidate_roles[0]
            else:
                fused_theme_roles[new_id] = "FINDING"
        
        theme_abstraction_start = time.time()
        themes = self._module_7_theme_abstraction(fused_clusters, filtered_atoms_list, concept_embeddings, fused_theme_roles)
        abstraction_time = (time.time() - theme_abstraction_start) * 1000
        stage_times['主题抽象'] = abstraction_time
        print(f"\n[主题抽象阶段] 完成")
        print(f"  - 主题数: {len(themes)}")
        print(f"  - 抽象耗时: {abstraction_time:.2f}ms")
        
        composition_start = time.time()
        composition_start = time.time()
        sorted_themes = self._module_8_structure_composition(themes)
        composition_time = (time.time() - composition_start) * 1000
        stage_times['结构化组合'] = composition_time
        print(f"\n[结构化组合阶段] 完成")
        print(f"  - 排序后主题数: {len(sorted_themes)}")
        print(f"  - 组合耗时: {composition_time:.2f}ms")
        
        final_output = []
        
        clustered_atom_indices = set()
        for theme in sorted_themes:
            final_output.append(theme)
            clustered_atom_indices.update(theme.get("constituent_atoms", []))
        unclustered_count = 0
        for i, atom in enumerate(filtered_atoms_list):
            if i not in clustered_atom_indices:
                final_output.append(atom)
                unclustered_count += 1
        
        total_time = (time.time() - extract_start_time) * 1000
        
        # 输出阶段耗时汇总表
        print(f"\n[阶段耗时剖析]")
        print(f"{'阶段名称':<20} {'耗时(ms)':<12} {'占比(%)':<10} {'状态':<8}")
        print(f"{'-'*20} {'-'*12} {'-'*10} {'-'*8}")
        total_stage_time = sum(stage_times.values())
        sorted_stages = sorted(stage_times.items(), key=lambda x: x[1], reverse=True)
        
        # 计算瓶颈阶段
        bottleneck_stages = []
        cumulative_time = 0.0
        for stage_name, stage_time in sorted_stages:
            percentage = (stage_time / total_time * 100) if total_time > 0 else 0.0
            cumulative_time += stage_time
            cumulative_pct = (cumulative_time / total_time * 100) if total_time > 0 else 0.0
            
            status = "🔴" if percentage > 30 else "🟡" if percentage > 15 else "🟢"
            print(f"{stage_name:<20} {stage_time:>10.2f}  {percentage:>8.1f}%  {status}")
            
            # 识别瓶颈（占比>20%或累计占比<80%的前N个阶段）
            if percentage > 20.0 or (cumulative_pct < 80.0 and len(bottleneck_stages) < 3):
                bottleneck_stages.append((stage_name, stage_time, percentage))
        
        print(f"{'-'*20} {'-'*12} {'-'*10} {'-'*8}")
        print(f"{'总计':<20} {total_time:>10.2f}  {100.0:>8.1f}%")
        if total_stage_time < total_time * 0.95:
            other_time = total_time - total_stage_time
            other_pct = (other_time / total_time * 100) if total_time > 0 else 0.0
            print(f"{'其他开销':<20} {other_time:>10.2f}  {other_pct:>8.1f}%")
        
        # 性能瓶颈详细分析
        if bottleneck_stages:
            print(f"\n[性能瓶颈分析]")
            print(f"  - 识别到 {len(bottleneck_stages)} 个主要瓶颈阶段:")
            for rank, (stage_name, stage_time, percentage) in enumerate(bottleneck_stages, 1):
                print(f"    {rank}. {stage_name}: {stage_time:.2f}ms ({percentage:.1f}%)")
                
                # 针对特定阶段的详细分析
                if stage_name == '文本处理':
                    print(f"      * 建议: 考虑批量处理或缓存spaCy结果")
                    if 'sentences' in locals():
                        avg_time_per_sent = stage_time / len(sentences) if sentences else 0
                        print(f"      * 平均每句耗时: {avg_time_per_sent:.2f}ms")
                        if avg_time_per_sent > 50:
                            print(f"      * ⚠️  单句处理耗时偏高，建议优化spaCy配置")
                
                elif stage_name == '质量量化':
                    print(f"      * 建议: 考虑减少质量量化维度或使用缓存")
                    if 'atoms' in locals():
                        avg_time_per_atom = stage_time / len(atoms) if atoms else 0
                        print(f"      * 平均每原子耗时: {avg_time_per_atom:.2f}ms")
                        if avg_time_per_atom > 100:
                            print(f"      * ⚠️  单原子量化耗时偏高，建议优化嵌入计算")
                
                elif stage_name == '评分计算':
                    print(f"      * 建议: 考虑批量计算NLI和SEM分数")
                    if 'atoms' in locals():
                        avg_time_per_atom = stage_time / len(atoms) if atoms else 0
                        print(f"      * 平均每原子耗时: {avg_time_per_atom:.2f}ms")
                
                elif stage_name == '原子提取':
                    print(f"      * 建议: 分析各路径耗时分布")
            
            # 计算瓶颈累计占比
            bottleneck_total = sum(stage_time for _, stage_time, _ in bottleneck_stages)
            bottleneck_pct = (bottleneck_total / total_time * 100) if total_time > 0 else 0.0
            print(f"  - 瓶颈阶段累计占比: {bottleneck_pct:.1f}%")
            if bottleneck_pct > 70:
                print(f"  - ⚠️  瓶颈集中度高，建议优先优化上述阶段")
        
        # 性能分布统计
        if len(sorted_stages) > 1:
            stage_times_list = [t for _, t in sorted_stages]
            print(f"\n[性能分布统计]")
            print(f"  - 阶段耗时: 平均={np.mean(stage_times_list):.2f}ms, "
                  f"中位数={np.median(stage_times_list):.2f}ms, "
                  f"标准差={np.std(stage_times_list):.2f}ms")
            print(f"  - 耗时范围: [{np.min(stage_times_list):.2f}, {np.max(stage_times_list):.2f}]ms")
            
            # 计算性能不均衡度（变异系数）
            cv = (np.std(stage_times_list) / np.mean(stage_times_list) * 100) if np.mean(stage_times_list) > 0 else 0
            print(f"  - 性能不均衡度(CV): {cv:.1f}% ({'高度不均衡' if cv > 50 else '中度不均衡' if cv > 30 else '相对均衡'})")
            
            if cv > 50:
                print(f"  - ⚠️  阶段耗时差异大，存在明显性能瓶颈")
        
        print(f"\n[提取完成] 总耗时: {total_time:.2f}ms")
        print(f"  - 最终输出: {len(final_output)} 个结果 (主题: {len(sorted_themes)}, 未聚类原子: {unclustered_count})")
        print(f"{'='*80}\n")
        
        metrics_monitor.end_document()
        metrics_monitor.check_and_alert()
        
        # 生成诊断报告（如果启用）
        return final_output

    def _compute_adaptive_distribution_threshold(self, similarities: np.ndarray, method: str = "auto") -> float:
        """计算自适应分布阈值
        
        Args:
            similarities: 相似度数组（所有原子对的相似度）
            method: 计算方法
                - "mean_std": 阈值 = 均值 + 0.5 * 标准差
                - "percentile": 阈值 = 分布前 20% 的最低值
                - "auto": 根据数据分布自动选择最佳方法
        
        Returns:
            自适应阈值
        """
        if len(similarities) == 0:
            return 0.80
        
        similarities = similarities[similarities > 0].copy()
        
        if len(similarities) == 0:
            return 0.80
        
        mean_sim = np.mean(similarities)
        std_sim = np.std(similarities)
        median_sim = np.median(similarities)
        
        threshold_mean_std = mean_sim + 0.5 * std_sim
        threshold_percentile = np.percentile(similarities, 80)
        
        if method == "auto":
            if std_sim < 0.15:
                method = "percentile"
            else:
                method = "mean_std"
        
        if method == "mean_std":
            threshold = threshold_mean_std
            method_name = "均值+0.5*标准差"
        elif method == "percentile":
            threshold = threshold_percentile
            method_name = "前20%最低值(80分位数)"
        else:
            threshold = threshold_mean_std
            method_name = "均值+0.5*标准差"
        
        threshold = max(0.40, min(0.95, threshold))
        
        
        return threshold

    def _module_5_atom_clustering(self, filtered_atoms: List[Dict], atom_embeddings: torch.Tensor) -> List[List[int]]:
        """Module 5.1: 原子聚类 - 将语义相似的原子聚成主题簇（使用自适应分布阈值）"""
        n_atoms = len(filtered_atoms)
        if n_atoms == 0:
            return []
        if n_atoms == 1:
            return []
        
        embeddings_np = atom_embeddings.cpu().numpy()
        norms = np.linalg.norm(embeddings_np, axis=1, keepdims=True)
        normalized_embeddings = embeddings_np / (norms + 1e-12)
        
        dim = normalized_embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(normalized_embeddings.astype('float32'))
        
        parent = list(range(n_atoms))
        
        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        
        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py
        
        k = min(10, n_atoms - 1)
        cluster_threshold = 0.80
        
        if k > 0:
            similarities, indices = index.search(normalized_embeddings.astype('float32'), k + 1)
            
            all_similarities = []
            for i in range(n_atoms):
                for j_idx, sim in zip(indices[i][1:], similarities[i][1:]):
                    if sim > 0:
                        all_similarities.append(sim)
            
            all_similarities_array = np.array(all_similarities)
            n_atoms = len(filtered_atoms)
            max_sim = np.max(all_similarities_array) if len(all_similarities_array) > 0 else 0.0
            std_sim = np.std(all_similarities_array) if len(all_similarities_array) > 0 else 0.0
            
            if n_atoms <= 5:
                if max_sim > 0:
                    if max_sim > 0.85 and std_sim < 0.10:
                        cluster_threshold = max_sim * 0.95
                        cluster_threshold = max_sim * 0.95
                    else:
                        cluster_threshold = max_sim * 0.9
                    cluster_threshold = max(0.40, min(0.95, cluster_threshold))
                else:
                    cluster_threshold = 0.40
            elif len(all_similarities_array) >= 3:
                mean_sim = np.mean(all_similarities_array)
                
                if max_sim > 0.85 and std_sim < 0.10:
                    cluster_threshold = max_sim * 0.95
                    cluster_threshold = max(0.40, min(0.95, cluster_threshold))
                    cluster_threshold = max_sim * 0.95
                    cluster_threshold = max(0.40, min(0.95, cluster_threshold))
                elif max_sim < 0.40 and std_sim < 0.15:
                    cluster_threshold = max_sim * 0.9
                    cluster_threshold = max(0.40, min(0.95, cluster_threshold))
                elif std_sim < 0.15:
                    cluster_threshold = np.percentile(all_similarities_array, 80)
                    cluster_threshold = max(0.40, min(0.95, cluster_threshold))
                else:
                    cluster_threshold = mean_sim + 0.5 * std_sim
                    cluster_threshold = max(0.40, min(0.95, cluster_threshold))
            else:
                cluster_threshold = 0.65
            
            merge_count = 0
            for i in range(n_atoms):
                for j_idx, sim in zip(indices[i][1:], similarities[i][1:]):
                    if sim >= cluster_threshold:
                        union(i, j_idx)
                        merge_count += 1
                        atom_i_text = filtered_atoms[i]["atom_text"][:40] + "..." if len(filtered_atoms[i]["atom_text"]) > 40 else filtered_atoms[i]["atom_text"]
                        atom_j_text = filtered_atoms[j_idx]["atom_text"][:40] + "..." if len(filtered_atoms[j_idx]["atom_text"]) > 40 else filtered_atoms[j_idx]["atom_text"]
            
            if merge_count == 0:
                pass
        
        cluster_dict = {}
        for i in range(n_atoms):
            root = find(i)
            if root not in cluster_dict:
                cluster_dict[root] = []
            cluster_dict[root].append(i)
        
        clusters = list(cluster_dict.values())
        valid_clusters = [c for c in clusters if len(c) >= 2]
        
        consistent_clusters = []
        consistency_threshold = 0.80  # 提高一致性阈值（从0.75提升至0.80）
        min_cluster_size = 2  # 最小簇大小限制
        
        for cluster_idx, cluster in enumerate(valid_clusters):
            if len(cluster) < min_cluster_size:
                continue
            
            cluster_embs = embeddings_np[cluster]
            n_pairs = 0
            total_sim = 0.0
            pair_sims = []
            
            for i in range(len(cluster)):
                for j in range(i + 1, len(cluster)):
                    sim = np.dot(cluster_embs[i], cluster_embs[j])
                    total_sim += sim
                    n_pairs += 1
                    pair_sims.append((cluster[i], cluster[j], sim))
            
            if n_pairs > 0:
                avg_sim = total_sim / n_pairs
                # 计算标准差，用于异常值检测
                sim_values = [sim for _, _, sim in pair_sims]
                std_sim = np.std(sim_values) if len(sim_values) > 1 else 0.0
                
                # 步骤7：异常值检测 - 移除距离簇中心 > 2σ 的异常原子
                cluster_centroid = cluster_embs.mean(axis=0)
                cluster_centroid = cluster_centroid / (np.linalg.norm(cluster_centroid) + 1e-12)
                
                atom_distances = []
                for atom_idx, atom_emb in zip(cluster, cluster_embs):
                    distance = 1.0 - np.dot(cluster_centroid, atom_emb)  # cosine distance
                    atom_distances.append((atom_idx, distance))
                
                outliers_removed = 0
                if std_sim > 0:
                    mean_distance = np.mean([d for _, d in atom_distances])
                    std_distance = np.std([d for _, d in atom_distances])
                    threshold_distance = mean_distance + 2 * std_distance  # 2σ阈值
                    
                    # 过滤异常原子
                    filtered_cluster = [atom_idx for atom_idx, dist in atom_distances if dist <= threshold_distance]
                    outliers_removed = len(cluster) - len(filtered_cluster)
                else:
                    filtered_cluster = cluster
                
                # 诊断统计：记录异常值过滤情况（用于监控是否过度丢弃）
                if not hasattr(self, '_clustering_diagnostics'):
                    self._clustering_diagnostics = {
                        'total_clusters': 0,
                        'outliers_removed': 0,
                        'atoms_before_filtering': 0,
                        'atoms_after_filtering': 0
                    }
                self._clustering_diagnostics['total_clusters'] += 1
                self._clustering_diagnostics['outliers_removed'] += outliers_removed
                self._clustering_diagnostics['atoms_before_filtering'] += len(cluster)
                self._clustering_diagnostics['atoms_after_filtering'] += len(filtered_cluster)
                
                # 确保过滤后的簇仍满足最小大小要求
                if len(filtered_cluster) >= min_cluster_size:
                    # 重新计算过滤后簇的平均相似度
                    if len(filtered_cluster) > 1:
                        filtered_avg_sim = np.mean([sim for atom_i, atom_j, sim in pair_sims 
                                                   if atom_i in filtered_cluster and atom_j in filtered_cluster])
                        
                        if filtered_avg_sim > consistency_threshold:
                            consistent_clusters.append(filtered_cluster)
                elif avg_sim > consistency_threshold:
                    # 如果过滤后太小但原簇满足阈值，保留原簇
                    consistent_clusters.append(cluster)
            else:
                consistent_clusters.append(cluster)
        
        # 输出聚类诊断统计（用于监控异常值过滤是否过度丢弃原子）
        if hasattr(self, '_clustering_diagnostics') and self._clustering_diagnostics['total_clusters'] > 0:
            diag = self._clustering_diagnostics
            outlier_ratio = (diag['outliers_removed'] / diag['atoms_before_filtering'] * 100) if diag['atoms_before_filtering'] > 0 else 0.0
            print(f"\n[聚类诊断统计]")
            print(f"  - 总簇数: {diag['total_clusters']}")
            print(f"  - 过滤前原子数: {diag['atoms_before_filtering']}")
            print(f"  - 过滤后原子数: {diag['atoms_after_filtering']}")
            print(f"  - 异常值移除数: {diag['outliers_removed']} ({outlier_ratio:.1f}%)")
            if outlier_ratio > 15.0:
                print(f"    ⚠️  警告: 异常值移除比例较高 ({outlier_ratio:.1f}%)，建议检查是否过度过滤")
            # 重置统计（每次聚类后重置）
            self._clustering_diagnostics = {
                'total_clusters': 0,
                'outliers_removed': 0,
                'atoms_before_filtering': 0,
                'atoms_after_filtering': 0
            }
        
        if consistent_clusters:
            pass
        
        return consistent_clusters
    
    def _module_5_5_theme_fusion(self, clusters: List[List[int]], filtered_atoms: List[Dict], 
                                 atom_embeddings: torch.Tensor, theme_roles: Dict[int, str]) -> List[List[int]]:
        """Module 5.5: 主题融合 - 合并语义相关的主题簇"""
        if len(clusters) <= 1:
            return clusters
        
        embeddings_np = atom_embeddings.cpu().numpy()
        fused_clusters = []
        merged = set()
        
        for i, cluster_i in enumerate(clusters):
            if i in merged:
                continue
            
            if not cluster_i or len(cluster_i) == 0:
                continue
            
            cluster_i_embs = embeddings_np[cluster_i]
            centroid_i = cluster_i_embs.mean(axis=0)
            centroid_i = centroid_i / (np.linalg.norm(centroid_i) + 1e-12)
            
            candidates_to_merge = [i]
            for j, cluster_j in enumerate(clusters):
                if j <= i or j in merged:
                    continue
                
                if not cluster_j or len(cluster_j) == 0:
                    continue
                
                role_i = theme_roles.get(i, "FINDING")
                role_j = theme_roles.get(j, "FINDING")
                
                can_fuse_by_role = (
                    (role_i == "MECHANISM" and role_j == "MECHANISM") or
                    (role_i == "MECHANISM" and role_j == "FINDING") or
                    (role_i == "FINDING" and role_j == "MECHANISM")
                )
                
                if not can_fuse_by_role:
                    continue
                
                if not cluster_i or not cluster_j:
                    continue
                if max(cluster_i) >= len(filtered_atoms) or max(cluster_j) >= len(filtered_atoms) or \
                   min(cluster_i) < 0 or min(cluster_j) < 0:
                    continue
                
                cluster_j_embs = embeddings_np[cluster_j]
                centroid_j = cluster_j_embs.mean(axis=0)
                centroid_j = centroid_j / (np.linalg.norm(centroid_j) + 1e-12)
                
                cluster_sim = np.dot(centroid_i, centroid_j)
                
                if cluster_sim <= 0.70:
                    continue
                
                atoms_i = [filtered_atoms[idx] for idx in cluster_i]
                atoms_j = [filtered_atoms[idx] for idx in cluster_j]
                
                entities_i = set()
                entities_j = set()
                for atom in atoms_i:
                    if "atom_text" in atom:
                        entities = self._extract_entities_from_atom(atom["atom_text"])
                        if entities["subject"]:
                            entities_i.add(entities["subject"].lower())
                        if entities["object"]:
                            entities_i.add(entities["object"].lower())
                
                for atom in atoms_j:
                    if "atom_text" in atom:
                        entities = self._extract_entities_from_atom(atom["atom_text"])
                        if entities["subject"]:
                            entities_j.add(entities["subject"].lower())
                        if entities["object"]:
                            entities_j.add(entities["object"].lower())
                
                has_common_entity = len(entities_i & entities_j) > 0
                
                if has_common_entity:
                    candidates_to_merge.append(j)
            
            if len(candidates_to_merge) > 1:
                merged_cluster = []
                merged_atom_set = set()
                for cid in candidates_to_merge:
                    if cid < len(clusters) and clusters[cid]:
                        for atom_idx in clusters[cid]:
                            if atom_idx not in merged_atom_set and 0 <= atom_idx < len(filtered_atoms):
                                merged_cluster.append(atom_idx)
                                merged_atom_set.add(atom_idx)
                if merged_cluster:
                    fused_clusters.append(merged_cluster)
                    for cid in candidates_to_merge:
                        merged.add(cid)
                else:
                    fused_clusters.append(cluster_i)
                    merged.add(i)
            else:
                fused_clusters.append(cluster_i)
                merged.add(i)
        
        return fused_clusters

    def _module_6_theme_role_detection(self, clusters: List[List[int]], filtered_atoms: List[Dict], 
                                       sentences: List[str]) -> Dict[int, str]:
        """Module 5.2: 主题角色识别 - 识别每个主题簇的科学叙事角色
        
        Args:
            clusters: 原子聚类结果（索引基于 filtered_atoms）
            filtered_atoms: 通过筛选的原子列表
            sentences: 原始句子列表
        
        Returns:
            theme_roles: {cluster_id: "FINDING", ...}
        """
        theme_roles = {}
        
        for cluster_id, atom_indices in enumerate(clusters):
            if not atom_indices:
                continue
            
            max_idx = max(atom_indices) if atom_indices else -1
            if max_idx >= len(filtered_atoms) or min(atom_indices) < 0:
                continue
            cluster_atoms = [filtered_atoms[i] for i in atom_indices]
            cluster_texts = [atom.get("atom_text", "") for atom in cluster_atoms if "atom_text" in atom]
            if not cluster_texts:
                continue
            
            role_scores = {
                "BACKGROUND": 0.0,
                "GAP": 0.0,
                "FINDING": 0.0,
                "MECHANISM": 0.0,
                "SIGNIFICANCE": 0.0
            }
            
            # 使用embedding替代NLI进行主题角色检测
            # 阶段3第一版：embedding-based替换NLI（满足"先把NLI主路径替换掉"的目标）
            # 后续优化方向：升级为专门训练的角色分类器
            #   - 使用人工/LLM标注句子作为训练集
            #   - 在BGE embedding上叠一个专门的分类头（RoBERTa-base/DeBERTa-base + MLP）
            #   - 这样可以获得更稳定的角色分类质量
            try:
                # 计算cluster文本的embedding
                cluster_embs = self._encode_with_cache(
                    cluster_texts,
                    convert_to_tensor=True,
                    normalize_embeddings=True
                )
                if not isinstance(cluster_embs, torch.Tensor):
                    cluster_embs = torch.tensor(cluster_embs)
                if cluster_embs.device != torch.device(self.device):
                    cluster_embs = cluster_embs.to(self.device)
                if cluster_embs.dim() == 1:
                    cluster_embs = cluster_embs.unsqueeze(0)
                
                # 计算与每个主题假设的相似度
                for role, hypothesis in self.theme_hypotheses.items():
                    # 计算假设的embedding
                    hypo_emb = self._encode_with_cache(
                        hypothesis,
                        convert_to_tensor=True,
                        normalize_embeddings=True
                    )
                    if isinstance(hypo_emb, list):
                        hypo_emb = hypo_emb[0]
                    if not isinstance(hypo_emb, torch.Tensor):
                        hypo_emb = torch.tensor(hypo_emb)
                    if hypo_emb.dim() == 1:
                        hypo_emb = hypo_emb.unsqueeze(0)
                    if hypo_emb.device != torch.device(self.device):
                        hypo_emb = hypo_emb.to(self.device)
                    
                    # 计算余弦相似度
                    similarities = torch.nn.functional.cosine_similarity(
                        cluster_embs,
                        hypo_emb.unsqueeze(0),
                        dim=1
                    )
                    # 取平均相似度
                    avg_sim = torch.mean(similarities).item()
                    # 归一化到[0, 1]范围
                    normalized_score = max(0.0, min(1.0, (avg_sim + 1) / 2))
                    role_scores[role] = normalized_score
            except Exception as e:
                error_msg = (
                    f"主题角色检测embedding方法失败\n"
                    f"聚类文本数量: {len(cluster_texts)}\n"
                    f"角色: {role}\n"
                    f"设备: {self.device}\n"
                    f"错误详情: {str(e)}\n"
                    f"可能原因:\n"
                    f"  1. Embedding模型未正确初始化\n"
                    f"  2. 输入数据格式错误\n"
                    f"  3. 设备资源不足（显存/内存）\n"
                    f"  4. Embedding计算过程出错"
                )
                raise RuntimeError(error_msg) from e
            
            combined_text = " ".join(cluster_texts).lower()
            
            if any(kw in combined_text for kw in ["background", "previous", "existing", "known", "established", 
                                                   "rely on", "depend on", "based on", "traditionally"]):
                role_scores["BACKGROUND"] += 0.3
            
            explicit_gap_count = sum(1 for kw in self.explicit_gap_markers if kw in combined_text)
            if explicit_gap_count > 0:
                role_scores["GAP"] += 0.5
            
            implicit_gap_count = sum(1 for kw in self.implicit_gap_markers if kw in combined_text)
            if implicit_gap_count > 0:
                role_scores["GAP"] += 0.3
            
            if any(kw in combined_text for kw in ["lack", "limited", "gap", "challenge", "problem", 
                                                   "difficulty", "however", "but", "yet"]):
                role_scores["GAP"] += 0.2
            
            if any(kw in combined_text for kw in ["find", "discover", "show", "demonstrate", "reveal", 
                                                  "identify", "observe", "result", "this study", "we found"]):
                role_scores["FINDING"] += 0.4
            
            if any(kw in combined_text for kw in ["mechanism", "process", "how", "trigger", "cause", 
                                                  "lead to", "result in", "through", "via", "by"]):
                role_scores["MECHANISM"] += 0.3
            
            if any(kw in combined_text for kw in ["significance", "important", "crucial", "essential", 
                                                    "critical", "impact", "implication", "contribute", 
                                                    "benefit", "advantage"]):
                role_scores["SIGNIFICANCE"] += 0.3
            
            atom_types = [atom.get("atom_type", "ACTION") for atom in cluster_atoms]
            for atom_type in atom_types:
                candidate_roles = self.atom_type_to_theme_roles.get(atom_type, ["FINDING"])
                for role in candidate_roles:
                    role_scores[role] += 0.2
            
            sentence_ids = [atom["sentence_id"] for atom in cluster_atoms]
            avg_sentence_pos = sum(sentence_ids) / len(sentence_ids) if sentence_ids else 0.5
            total_sentences = len(sentences)
            
            if total_sentences > 0:
                normalized_pos = avg_sentence_pos / total_sentences
                if normalized_pos < 0.3:
                    role_scores["BACKGROUND"] += 0.2
                elif normalized_pos > 0.7:
                    role_scores["FINDING"] += 0.15
                    role_scores["SIGNIFICANCE"] += 0.15
            
            best_role = max(role_scores.items(), key=lambda x: x[1])[0]
            theme_roles[cluster_id] = best_role
        
        return theme_roles

    def _extract_entities_from_atom(self, atom_text: str):
        """从原子文本中提取实体（主语、动词、宾语）- 改进版：使用spaCy NER + embedding相似度"""
        doc = self.nlp(atom_text)
        
        words = atom_text.split()
        if len(words) < 2:
            return {"subject": "", "verb": words[0] if words else "", "object": ""}
        
        subject = ""
        verb = ""
        object_part = ""
        
        for token in doc:
            if token.dep_ in ["nsubj", "nsubjpass"] and not subject:
                subject = self._extract_noun_phrase(token)
            elif token.dep_ in ["dobj", "pobj"] and not object_part:
                object_part = self._extract_noun_phrase(token)
            elif token.pos_ == "VERB" and token.dep_ == "ROOT" and not verb:
                verb = token.text
        
        if not subject or not verb:
            verb_positions = []
            for i, word in enumerate(words):
                if word.lower() in ["is", "are", "was", "were", "has", "have", "does", "do", 
                                   "causes", "leads", "triggers", "drives", "stabilizes", "ensures"]:
                    verb_positions.append(i)
            
            if verb_positions:
                verb_idx = verb_positions[0]
                if not subject:
                    subject = " ".join(words[:verb_idx]) if verb_idx > 0 else ""
                if not verb:
                    verb = words[verb_idx] if verb_idx < len(words) else ""
                if not object_part:
                    object_part = " ".join(words[verb_idx+1:]) if verb_idx + 1 < len(words) else ""
            else:
                if len(words) >= 2:
                    if not subject:
                        subject = words[0]
                    if not verb:
                        verb = words[1] if len(words) > 1 else ""
                    if not object_part:
                        object_part = " ".join(words[2:]) if len(words) > 2 else ""
        
        return {
            "subject": subject.strip(),
            "verb": verb.strip(),
            "object": object_part.strip()
        }
    
    def _find_paraphrase_mapping(self, text1: str, text2: str, threshold: float = 0.85) -> bool:
        """使用embedding相似度判断两个文本是否为paraphrase（近义表达）"""
        emb1 = self.emb_model.encode([text1], convert_to_tensor=True)
        emb2 = self.emb_model.encode([text2], convert_to_tensor=True)
        similarity = torch.nn.functional.cosine_similarity(emb1, emb2).item()
        return similarity >= threshold
    
    def _controlled_scientific_rewrite(self, base_text: str, cluster_atoms: List[Dict], 
                                       theme_role: str, entities: Dict) -> str:
        """可控式科学文本重写（半可控生成：模板+实体填充+关系推理）
        
        基于模板和实体进行可控生成，而不是完全依赖LLM
        """
        causal_atoms = [a for a in cluster_atoms if a.get("relation_type") == "causal"]
        conditional_atoms = [a for a in cluster_atoms if a.get("relation_type") == "conditional"]
        
        if causal_atoms and theme_role == "MECHANISM":
            causal_chain = []
            for atom in causal_atoms[:2]:
                if "atom_text" in atom:
                    atom_entities = self._extract_entities_from_atom(atom["atom_text"])
                    if atom_entities["subject"] and atom_entities["object"]:
                        causal_chain.append(f"{atom_entities['subject']} 导致 {atom_entities['object']}")
            
            if causal_chain:
                if "导致" not in base_text and "引发" not in base_text:
                    base_text = f"{base_text} 具体而言，{'；'.join(causal_chain)}。"
        
        if conditional_atoms and theme_role in ["MECHANISM", "FINDING"]:
            for atom in conditional_atoms[:1]:
                if "atom_text" in atom:
                    atom_text = atom["atom_text"]
                    if "when" in atom_text.lower() or "if" in atom_text.lower():
                        if "当" not in base_text and "如果" not in base_text:
                            base_text = f"当{atom_text}时，{base_text}"
        
        return base_text
    
    def _normalize_theme_text(self, text: str):
        """语言自然化：同义替换、代词消解、删除重复、动词格式统一"""
        words = text.split()
        seen_entities = set()
        filtered_words = []
        for word in words:
            word_lower = word.lower()
            if word_lower not in seen_entities or word_lower in ["the", "a", "an", "this", "that"]:
                filtered_words.append(word)
                if len(word) > 3:
                    seen_entities.add(word_lower)
        
        text = " ".join(filtered_words)
        
        text = text.replace("..", ".").replace("  ", " ").strip()
        
        return text
    
    def _generate_scientific_narrative_template(self, theme_role: str, entities: Dict, supplementary_info: List[str]):
        """根据主题角色生成科学叙事化模板文本"""
        subject = entities.get("subject", "")
        verb = entities.get("verb", "")
        object_part = entities.get("object", "")
        
        if theme_role == "BACKGROUND":
            if subject and verb and object_part:
                return f"{subject} {verb} {object_part}。"
            elif subject and object_part:
                return f"{subject} 依赖于 {object_part}。"
            else:
                base = " ".join([s for s in [subject, verb, object_part] if s])
                return f"{base}。"
        
        elif theme_role == "GAP":
            if subject and object_part:
                return f"{subject} 仍然未知。具体而言，{object_part}。"
            elif object_part:
                return f"{object_part} 此前未知。"
            else:
                base = " ".join([s for s in [subject, verb, object_part] if s])
                return f"{base} 仍然不清楚。"
        
        elif theme_role == "FINDING":
            if subject and verb and object_part:
                return f"本研究发现：{subject} {verb} {object_part}。"
            elif subject and object_part:
                return f"本研究发现：{subject} 导致 {object_part}。"
            else:
                base = " ".join([s for s in [subject, verb, object_part] if s])
                return f"本研究发现：{base}。"
        
        elif theme_role == "MECHANISM":
            if subject and verb and object_part:
                return f"{subject} 通过 {verb} 导致 {object_part}。"
            elif subject and object_part:
                return f"{subject} 引发 {object_part}。"
            else:
                base = " ".join([s for s in [subject, verb, object_part] if s])
                return f"{base} 的工作机制。"
        
        elif theme_role == "SIGNIFICANCE":
            if subject and object_part:
                return f"{subject} 具有重要意义，因为 {object_part}。"
            elif object_part:
                return f"{object_part} 具有重要的研究价值。"
            else:
                base = " ".join([s for s in [subject, verb, object_part] if s])
                return f"{base} 具有重要意义。"
        
        else:
            base = " ".join([s for s in [subject, verb, object_part] if s])
            return f"{base}。"
    
    def _module_3_1_multi_atom_relation_reasoning(self, atoms: List[Dict], sentences: List[str]) -> Dict[tuple, str]:
        """Module 3.1: 多原子关系推理（轻量级实现）- 识别原子间的因果/时序/条件关系
        
        Args:
            atoms: 原子列表
            sentences: 原始句子列表
        
        Returns:
            relations: {(atom_i, atom_j): "causal"/"temporal"/"conditional"} 关系映射
        """
        relations = {}
        
        for i, atom_i in enumerate(atoms):
            for j, atom_j in enumerate(atoms):
                if i >= j:
                    continue
                
                sent_i = atom_i.get("sentence_id", 0)
                sent_j = atom_j.get("sentence_id", 0)
                
                rel_type_i = atom_i.get("relation_type")
                rel_type_j = atom_j.get("relation_type")
                
                if rel_type_i == "causal" and abs(sent_i - sent_j) <= 1:
                    relations[(i, j)] = "causal"
                elif rel_type_i == "conditional" and abs(sent_i - sent_j) <= 1:
                    relations[(i, j)] = "conditional"
                elif rel_type_i == "contrast" and abs(sent_i - sent_j) <= 1:
                    relations[(i, j)] = "contrast"
                
                if "atom_text" not in atom_i or "atom_text" not in atom_j:
                    continue
                
                entities_i = self._extract_entities_from_atom(atom_i["atom_text"])
                entities_j = self._extract_entities_from_atom(atom_j["atom_text"])
                
                obj_i = entities_i["object"].lower().strip()
                subj_j = entities_j["subject"].lower().strip()
                obj_j = entities_j["object"].lower().strip()
                subj_i = entities_i["subject"].lower().strip()
                
                if obj_i and subj_j and (obj_i in subj_j or subj_j in obj_i):
                    if (i, j) not in relations:
                        relations[(i, j)] = "causal"
                elif obj_j and subj_i and (obj_j in subj_i or subj_i in obj_j):
                    if (i, j) not in relations:
                        relations[(i, j)] = "causal"
        
        return relations
    
    def _module_7_theme_abstraction(self, clusters: List[List[int]], filtered_atoms: List[Dict], 
                                    atom_embeddings: torch.Tensor, theme_roles: Dict[int, str]) -> List[Dict]:
        """Module 5.3: 主题抽象 - 生成主题级表达（改进版：科学叙事化模板 + 可控式重写）
        
        Args:
            clusters: 原子聚类结果
            filtered_atoms: 通过筛选的原子列表
            atom_embeddings: 原子嵌入向量
            theme_roles: 主题角色映射
        
        Returns:
            themes: 主题列表，每个主题包含 theme_text, theme_role, constituent_atoms 等字段
        """
        themes = []
        embeddings_np = atom_embeddings.cpu().numpy()
        theme_counter = 0
        
        for cluster_id, atom_indices in enumerate(clusters):
            if not atom_indices:
                continue
            
            max_idx = max(atom_indices) if atom_indices else -1
            if max_idx >= len(filtered_atoms) or min(atom_indices) < 0:
                continue
            
            cluster_atoms = [filtered_atoms[i] for i in atom_indices]
            cluster_embs = embeddings_np[atom_indices]
            
            centroid = cluster_embs.mean(axis=0)
            centroid = centroid / (np.linalg.norm(centroid) + 1e-12)
            similarities = cluster_embs @ centroid
            center_idx = np.argmax(similarities)
            
            if center_idx < 0 or center_idx >= len(cluster_atoms):
                center_idx = 0
            
            center_atom = cluster_atoms[center_idx]
            base_text = center_atom.get("atom_text", "")
            if not base_text:
                continue
            
            other_atoms = [a for i, a in enumerate(cluster_atoms) if i != center_idx]
            theme_role = theme_roles.get(cluster_id, "FINDING")
            
            center_entities = self._extract_entities_from_atom(base_text)
            
            supplementary_entities = []
            seen_paraphrases = set()
            
            for atom in other_atoms[:2]:
                if "atom_text" not in atom:
                    continue
                atom_text = atom.get("atom_text", "")
                if not atom_text or len(atom_text) <= 10:
                    continue
                
                is_paraphrase = False
                for seen_text in seen_paraphrases:
                    if self._find_paraphrase_mapping(atom_text, seen_text, threshold=0.85):
                        is_paraphrase = True
                        break
                
                if is_paraphrase:
                    continue
                
                base_words_set = set(w.lower() for w in base_text.split())
                atom_words_set = set(w.lower() for w in atom_text.split())
                overlap = len(base_words_set & atom_words_set) / max(len(atom_words_set), 1)
                
                if overlap < 0.7:
                    entities = self._extract_entities_from_atom(atom_text)
                    supplementary_entities.append(entities)
                    seen_paraphrases.add(atom_text)
            
            merged_entities = center_entities.copy()
            if supplementary_entities:
                for supp in supplementary_entities:
                    if not merged_entities["subject"] and supp["subject"]:
                        merged_entities["subject"] = supp["subject"]
                    if not merged_entities["object"] and supp["object"]:
                        merged_entities["object"] = supp["object"]
                    elif supp["object"] and merged_entities["object"]:
                        merged_entities["object"] = f"{merged_entities['object']}，{supp['object']}"
            
            supplementary_info = [atom.get("atom_text", "") for atom in other_atoms[:1] if "atom_text" in atom and len(atom.get("atom_text", "")) > 10]
            theme_text = self._generate_scientific_narrative_template(theme_role, merged_entities, supplementary_info)
            theme_text = self._controlled_scientific_rewrite(theme_text, cluster_atoms, theme_role, merged_entities)
            theme_text = self._normalize_theme_text(theme_text)
            
            theme_counter += 1
            theme = {
                "theme_id": theme_counter,
                "theme_text": theme_text,
                "theme_role": theme_role,
                "constituent_atoms": atom_indices,
                "center_atom_id": atom_indices[center_idx],
                "atom_count": len(atom_indices),
                "id": center_atom.get("id", theme_counter),
                "category": center_atom.get("category", "CONCLUSION"),
                "confidence": center_atom.get("confidence", 0.0),
                "atom_text": base_text,
                "original_sentence": center_atom.get("original_sentence", ""),
                "sentence_id": center_atom.get("sentence_id", 0),
                "atom_id": center_atom.get("atom_id", 0),
                "atom_type": center_atom.get("atom_type", "ACTION"),
                "original_nli_prob": center_atom.get("original_nli_prob", 0.0)
            }
            
            themes.append(theme)
        
        return themes

    def _module_8_structure_composition(self, themes: List[Dict]) -> List[Dict]:
        """Module 5.4: 结构化组合 - 按科学叙事顺序排列主题
        
        排序规则：BACKGROUND → GAP → FINDING → MECHANISM → SIGNIFICANCE
        
        Args:
            themes: 主题列表
        
        Returns:
            sorted_themes: 按科学叙事顺序排列的主题列表
        """
        role_order = {
            "BACKGROUND": 1,
            "GAP": 2,
            "FINDING": 3,
            "MECHANISM": 4,
            "SIGNIFICANCE": 5
        }
        
        sorted_themes = sorted(
            themes,
            key=lambda t: (
                role_order.get(t.get("theme_role", "FINDING"), 3),
                t.get("sentence_id", 0)
            )
        )
        
        return sorted_themes

def normalize_text(t: str):
    return re.sub(r'\s+', ' ', (t or '').lower().strip().replace('-', ' '))

@lru_cache(maxsize=200_000)
def normalize_text_cached(t: str):
    return normalize_text(t)

def load_opinion_stopwords():
    global _OPINION_STOPWORDS
    if _OPINION_STOPWORDS is None:
        _OPINION_STOPWORDS = set()
        with open(OPINION_STOPWORDS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    _OPINION_STOPWORDS.add(normalize_text(line))
    return _OPINION_STOPWORDS

def is_opinion_stopword(phrase: str) -> bool:
    stopwords = load_opinion_stopwords()
    n = normalize_text_cached(phrase)
    return n in stopwords

def adaptive_threshold(phrase: str, base=CLUSTER_THRESHOLD):
    n_tok = len(normalize_text_cached(phrase).split())
    if n_tok <= 2: return min(0.92, base + 0.07)
    if n_tok >= 6: return max(0.75, base - 0.05)
    return base

def is_generic_phrase(phrase: str) -> bool:
    n = normalize_text_cached(phrase)
    if len(n) <= 2:
        return True
    if is_opinion_stopword(phrase):
        return True
    
    if any(rgx.match(n) for rgx in GENERIC_RE):
        innovation_keywords = ['innovative', 'original', 'pioneering', 'breakthrough', 
                              'groundbreaking', 'state of the art', 'first', 'novel']
        has_innovation_keyword = any(keyword in n for keyword in innovation_keywords)
        has_sufficient_context = len(n) > 20
        
        if has_innovation_keyword or has_sufficient_context:
            return False
        
        return True
    
    return False

def abstract_object_phrase(phrase: str, doc=None) -> str:
    """对象抽象化：保留完整语义信息，仅去除无关限定词"""
    if not phrase:
        return ""
    
    phrase_lower = normalize_text(phrase)
    
    for synonym, canonical in SYNONYM_MAP.items():
        if phrase_lower == synonym:
            return canonical
    
    words = phrase_lower.split()
    filtered_words = [w for w in words if w not in ['the', 'a', 'an', 'this', 'that']]
    
    if filtered_words:
        return " ".join(filtered_words)
    
    return phrase_lower

def reset_microbatch_hash_set():
    global _microbatch_hash_lru
    with _microbatch_hash_lock:
        _microbatch_hash_lru.clear()

def _get_hash(text):
    normalized = normalize_text(text)
    if xxhash:
        return xxhash.xxh64(normalized.encode('utf-8')).intdigest()
    return hash(normalized)

# =========================
# 共享常量定义
# =========================
FRAMEWORK_VERBS = {
    "show", "demonstrate", "indicate", "suggest", "reveal", "find", "prove",
    "establish", "confirm", "verify", "illustrate", "exemplify", "exhibit",
    "present", "report", "describe", "state", "note", "observe", "see"
}

NOMINALIZATION_NOUNS = {
    "improvement", "improve", "analysis", "analyze", "reduction", "reduce",
    "detection", "detect", "measurement", "measure", "activation", "activate",
    "regulation", "regulate", "inhibition", "inhibit", "compensation", "compensate",
    "enhancement", "enhance", "optimization", "optimize", "evaluation", "evaluate",
    "identification", "identify", "classification", "classify", "prediction", "predict",
    "recognition", "recognize", "extraction", "extract", "generation", "generate",
    "transformation", "transform", "modification", "modify", "adaptation", "adapt"
}

# =========================
# 共享工具函数
# =========================
def _determine_granularity(agent: Optional[str], patient: Optional[str]) -> Literal["minimal", "partial", "complete"]:
    """确定原子粒度
    
    Args:
        agent: agent文本
        patient: patient文本
        
    Returns:
        Literal: 粒度标记
    """
    if agent and patient:
        return "complete"
    elif agent or patient:
        return "partial"
    else:
        return "minimal"

def _calculate_confidence_base(granularity: Literal["minimal", "partial", "complete"],
                              base_range: Tuple[float, float] = (0.5, 0.7),
                              complete_range: Tuple[float, float] = (0.7, 0.9),
                              partial_range: Tuple[float, float] = (0.5, 0.7)) -> float:
    """基础置信度计算函数（参数化）
    
    Args:
        granularity: 原子粒度
        base_range: minimal粒度的置信度范围
        complete_range: complete粒度的置信度范围
        partial_range: partial粒度的置信度范围
        
    Returns:
        float: 置信度值
    """
    if granularity == "complete":
        return complete_range[0] + np.random.uniform(0, complete_range[1] - complete_range[0])
    elif granularity == "partial":
        return partial_range[0] + np.random.uniform(0, partial_range[1] - partial_range[0])
    else:
        return base_range[0] + np.random.uniform(0, base_range[1] - base_range[0])

@dataclass
class StructuredOpinion:
    """结构化观点对象"""
    subject: Optional[str] = None
    object: str = ""
    predicate: str = ""
    target: Optional[str] = None
    polarity: str = "neutral"
    strength: Optional[str] = None
    context: Optional[str] = None
    stance: str = "neutral"
    opposed_to: List[int] = field(default_factory=list)

@dataclass
class MAU:
    """最小对齐单元（Minimal Alignment Unit）
    
    语义识别系统的核心数据格式，用于跨路径对齐和归一化。
    """
    predicate: str
    patient: Optional[str] = None
    agent: Optional[str] = None
    context: Optional[str] = None
    granularity: Literal["minimal", "partial", "complete"] = "complete"
    confidence: float = 0.0
    source_path: Literal["SRL"] = "SRL"
    nested_events: Optional[List] = None
    coref_resolved: bool = False
    
    atom_text: str = ""
    atom_type: Optional[str] = None
    sentence_id: int = -1
    original_sentence: str = ""
    
    def __post_init__(self):
        """后处理：确保atom_text有值"""
        if not self.atom_text:
            parts = []
            if self.agent:
                parts.append(self.agent)
            parts.append(self.predicate)
            if self.patient:
                parts.append(self.patient)
            self.atom_text = " ".join(parts) if parts else self.predicate
    
    def to_dict(self) -> Dict:
        """转换为字典格式（用于兼容旧代码）"""
        return {
            "atom_text": self.atom_text,
            "atom_type": self.atom_type,
            "verb_lemma": self.predicate,
            "patient": self.patient,
            "agent": self.agent,
            "sentence_id": self.sentence_id,
            "original_sentence": self.original_sentence,
            "granularity": self.granularity,
            "confidence": self.confidence,
            "source_path": self.source_path,
            "has_subject": self.agent is not None,
            "has_object": self.patient is not None,
            "atom_id": getattr(self, 'atom_id', self.sentence_id),
        }
    
    @classmethod
    def from_dict(cls, atom_dict: Dict) -> 'MAU':
        """从旧格式字典创建MAU"""
        predicate = atom_dict.get("verb_lemma", atom_dict.get("predicate", ""))
        if not predicate:
            atom_text = atom_dict.get("atom_text", "")
            if atom_text:
                words = atom_text.split()
                predicate = words[0] if words else ""
        
        granularity = "complete"
        if not atom_dict.get("has_subject") and not atom_dict.get("has_object"):
            granularity = "minimal"
        elif not atom_dict.get("has_subject") or not atom_dict.get("has_object"):
            granularity = "partial"
        
        return cls(
            predicate=predicate,
            patient=atom_dict.get("patient"),
            agent=atom_dict.get("agent"),
            context=atom_dict.get("context"),
            granularity=granularity,
            confidence=atom_dict.get("confidence", 0.0),
            source_path=atom_dict.get("source_path", "B"),
            coref_resolved=atom_dict.get("coref_resolved", False),
            atom_text=atom_dict.get("atom_text", ""),
            atom_type=atom_dict.get("atom_type"),
            sentence_id=atom_dict.get("sentence_id", -1),
            original_sentence=atom_dict.get("original_sentence", ""),
        )

@dataclass
class SRLEventUnit:
    """SRL 事件单元数据结构
    
    用于语义角色标注的信息单元，替代 MAU 作为 2.2-2.6 阶段的信息单元。
    
    字段说明：
    - arguments: Dict[str, List[str]] - 支持多个同类型论元（如多个ARG1）
    - logical_agent/patient: 逻辑施事/受事（补充字段，不覆盖原始ARG0/ARG1）
    - has_srl_structure: 是否有SRL结构（False表示无谓词/无结构，但仍保留句子信息）
    - low_info_predicate: 是否为低信息谓词（如"is important"），用于降权而非丢弃
    - structure_confidence: SRL结构质量置信度（由compute_srl_structure_score计算）
      注意：这是"SRL结构质量置信度"，不是"整条信息单元的总置信度"
    - confidence: 全局置信度（由上层模型统一计算，融合SRL结构+文本特征+embedding+NLI等）
    """
    paper_id: str = ""
    year: int = 2025
    section: str = "abstract"  # title/abstract
    sentence_text: str = ""
    predicate: Optional[str] = None
    arguments: Dict[str, List[str]] = field(default_factory=dict)  # ARG0, ARG1, ARGM-TMP, etc. (支持多个同类型论元)
    
    # 被动语态处理字段（保留原始ARG，逻辑角色作为补充）
    logical_agent: Optional[str] = None  # 逻辑施事（从ARG0或by-phrase提取）
    logical_patient: Optional[str] = None  # 逻辑受事（从ARG1或被动主语提取）
    
    # 结构质量标志位（不硬写置信度，交给上层评分）
    has_srl_structure: bool = True  # 是否有SRL结构（False表示无谓词/无结构）
    low_info_predicate: bool = False  # 是否为低信息谓词（如"is important"）
    structure_confidence: float = 0.0  # SRL结构置信度（由compute_srl_structure_score计算）
    
    # 兼容字段（用于与现有流程集成）
    sentence_id: int = -1
    original_sentence: str = ""
    confidence: float = 0.0  # 全局置信度（由上层模型统一计算，不在此处硬写）
    source_path: Literal["A", "B", "C", "SRL"] = "SRL"
    
    def __post_init__(self):
        """后处理：确保 original_sentence 有值"""
        if not self.original_sentence:
            self.original_sentence = self.sentence_text
    
    def to_dict(self) -> Dict:
        """转换为字典格式（兼容 MAU.to_dict）"""
        # 将 SRL arguments 映射到 MAU 格式（取第一个论元）
        arg0_list = self.arguments.get("ARG0", [])
        arg1_list = self.arguments.get("ARG1", [])
        agent = arg0_list[0] if arg0_list else (self.logical_agent if self.logical_agent else None)
        patient = arg1_list[0] if arg1_list else (self.logical_patient if self.logical_patient else None)
        
        # 构建 atom_text
        parts = []
        if agent:
            parts.append(agent)
        if self.predicate:
            parts.append(self.predicate)
        if patient:
            parts.append(patient)
        atom_text = " ".join(parts) if parts else (self.predicate or self.sentence_text[:50])
        
        # 确定粒度
        granularity = "complete"
        if not agent and not patient:
            granularity = "minimal"
        elif not agent or not patient:
            granularity = "partial"
        
        return {
            "atom_text": atom_text,
            "atom_type": "SRL_EVENT",
            "verb_lemma": self.predicate or "",
            "patient": patient,
            "agent": agent,
            "sentence_id": self.sentence_id,
            "original_sentence": self.original_sentence,
            "granularity": granularity,
            "confidence": self.confidence,
            "source_path": self.source_path,
            "has_subject": agent is not None,
            "has_object": patient is not None,
            "atom_id": getattr(self, 'atom_id', self.sentence_id),
            "srl_arguments": {k: v if isinstance(v, list) else [v] for k, v in self.arguments.items()},  # 保留完整 SRL 信息（列表格式）
            "srl_predicate": self.predicate,
            "logical_agent": self.logical_agent,
            "logical_patient": self.logical_patient,
            "has_srl_structure": self.has_srl_structure,  # 是否有SRL结构
            "low_info_predicate": self.low_info_predicate,  # 是否为低信息谓词
            "structure_confidence": self.structure_confidence  # SRL结构置信度
        }
    
    def to_mau(self) -> MAU:
        """转换为 MAU 对象（用于兼容现有流程）"""
        arg0_list = self.arguments.get("ARG0", [])
        arg1_list = self.arguments.get("ARG1", [])
        agent = arg0_list[0] if arg0_list else (self.logical_agent if self.logical_agent else None)
        patient = arg1_list[0] if arg1_list else (self.logical_patient if self.logical_patient else None)
        
        granularity = "complete"
        if not agent and not patient:
            granularity = "minimal"
        elif not agent or not patient:
            granularity = "partial"
        
        parts = []
        if agent:
            parts.append(agent)
        if self.predicate:
            parts.append(self.predicate)
        if patient:
            parts.append(patient)
        atom_text = " ".join(parts) if parts else (self.predicate or "")
        
        # 如果confidence是默认值0.0，使用structure_confidence作为初始值
        # 这样可以确保即使confidence_model不可用，也有一个合理的初始置信度
        initial_confidence = self.confidence if self.confidence > 0.0 else self.structure_confidence
        
        return MAU(
            predicate=self.predicate or "",
            patient=patient,
            agent=agent,
            granularity=granularity,
            confidence=initial_confidence,
            source_path=self.source_path,
            atom_text=atom_text,
            sentence_id=self.sentence_id,
            original_sentence=self.original_sentence
        )


class SRLModule:
    """SRL（语义角色标注）模块
    
    使用 pakkinlau/bert-base-uncased-finetuned-advanced-srl_arg 模型进行语义角色标注。
    支持：
    - 动词识别（VERB + AUX + 名词化结构）
    - 被动语态处理（提取逻辑施事/受事）
    - 多论元支持（同一类型论元保留为列表）
    """
    
    # 配置常量（避免硬编码）
    LOW_INFO_PREDICATE_PENALTY = 0.5  # 低信息谓词降权因子
    BASE_SCORE_MAX = 1.0  # base_score最大值
    BONUS_SCORE_MAX = 0.2  # bonus_score最大值
    
    def __init__(self, nlp_model, device: str = None):
        if device is None:
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.device = device
        self.nlp = nlp_model
        
        from transformers import AutoTokenizer, AutoModelForTokenClassification
        model_name = "pakkinlau/bert-base-uncased-finetuned-advanced-srl_arg"
        try:
            print(f"[SRL] 正在加载 {model_name} 模型（可能需要下载，请耐心等待）...")
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.srl_model = AutoModelForTokenClassification.from_pretrained(model_name)
            self.srl_model.to(device)
            self.srl_model.eval()
            print(f"[SRL] 已加载 {model_name} 模型")
        except Exception as e:
            print(f"[错误] 无法加载 SRL 模型: {e}")
            print("[提示] 可能是网络问题，请检查网络连接或使用镜像站点")
            print("[提示] 可以尝试设置环境变量: export HF_ENDPOINT=https://hf-mirror.com")
            raise RuntimeError("无法加载 SRL 模型，请检查网络连接")
    
    def extract_srl_events(self, sentence: str, sentence_id: int = -1, 
                          paper_id: str = "", year: int = 2025, section: str = "abstract") -> List[SRLEventUnit]:
        if not sentence or not sentence.strip():
            return []
        
        events = self._extract_with_bert_srl(sentence, sentence_id, paper_id, year, section)
        events = self._post_process_events(events, sentence)
        
        return events
    
    def _extract_with_bert_srl(self, sentence: str, sentence_id: int, 
                                paper_id: str, year: int, section: str) -> List[SRLEventUnit]:
        doc = self.nlp(sentence)
        
        if not sentence or not sentence.strip():
            return []
        
        # 改进1：放宽谓词候选条件，包括VERB、AUX和名词化结构
        verb_candidates = []
        
        # 1. 标准动词和助动词
        for token in doc:
            if token.pos_ in {"VERB", "AUX"} and not token.is_stop:
                verb_candidates.append(("verb", token))
        
        # 2. 名词化动词（启发式检测）
        for token in doc:
            if token.pos_ == "NOUN":
                lemma = token.lemma_.lower()
                # 检查名词化后缀
                if any(lemma.endswith(suffix) for suffix in ["tion", "sion", "ment", "ance", "ence", "ing"]):
                    # 检查是否有 "of" 介词结构（如 "expression of X"）
                    for child in token.children:
                        if child.dep_ == "prep" and child.text.lower() == "of":
                            verb_candidates.append(("nominalization", token))
                            break
        
        events = []
        
        if not verb_candidates:
            error_msg = (
                f"无法提取SRL事件：未找到候选谓词\n"
                f"句子: {sentence[:100]}...\n"
                f"句子ID: {sentence_id}\n"
                f"论文ID: {paper_id}\n"
                f"可能原因:\n"
                f"  1. 句子中没有动词或助动词\n"
                f"  2. 句子中没有名词化结构\n"
                f"  3. 句子结构不符合SRL处理要求\n"
                f"  4. spaCy解析结果异常"
            )
            raise ValueError(error_msg)
        
        # 对每个候选谓词单独处理：在谓词前添加 [V] 标记，单独标注
        for candidate_type, verb in verb_candidates:
            verb_text = verb.text
            verb_lemma = verb.lemma_.lower()
            verb_start = verb.idx
            
            # 改进3：细粒度处理系动词/助动词，而不是直接跳过
            is_low_info_predicate = False
            if verb_lemma in ['be', 'is', 'are', 'was', 'were', 'am']:
                # 检查是否是高价值结构（如 "has been shown", "is associated with"）
                # 通过检查后续token判断
                verb_idx = verb.i
                if verb_idx + 1 < len(doc):
                    next_token = doc[verb_idx + 1]
                    # 如果是被动结构或复合谓词，保留
                    if next_token.lemma_.lower() in ['show', 'report', 'demonstrate', 'associate', 'relate', 'link']:
                        is_low_info_predicate = False
                    elif next_token.pos_ == "ADJ":
                        # 简单形容词补语（如 "is important"），标记为低信息
                        is_low_info_predicate = True
                else:
                    is_low_info_predicate = True
            elif verb_lemma in ['have', 'has', 'had']:
                # "has been shown" 等结构保留
                is_low_info_predicate = False
            elif verb_lemma in ['do', 'does', 'did']:
                # 助动词do通常低信息
                is_low_info_predicate = True
            
            # 低信息谓词仍然处理，但会在后续评分中降权
            
            # 在动词前插入 [V] 标记
            if verb_start >= 0:
                marked_sentence = sentence[:verb_start] + "[V] " + sentence[verb_start:]
            else:
                # 如果找不到精确位置，尝试在动词词前添加（只替换第一个）
                marked_sentence = sentence.replace(verb_text, f"[V] {verb_text}", 1)
            
            # 准备输入：使用标记后的句子
            inputs = self.tokenizer(
                marked_sentence,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512,
                return_offsets_mapping=True
            )
            
            input_ids = inputs['input_ids'].to(self.device)
            attention_mask = inputs['attention_mask'].to(self.device)
            tokenized_tokens = self.tokenizer.convert_ids_to_tokens(input_ids[0])
            
            with torch.no_grad():
                outputs = self.srl_model(
                    input_ids=input_ids,
                    attention_mask=attention_mask
                )
            
            predictions = torch.argmax(outputs.logits, dim=-1)[0]
            
            # 提取所有token和标签（排除[V]标记和特殊token）
            token_label_pairs = []
            for idx, (token, pred_id) in enumerate(zip(tokenized_tokens, predictions)):
                if token in ['[CLS]', '[SEP]', '[PAD]']:
                    continue
                if token.startswith('[') and token.endswith(']'):  # 跳过[V]标记
                    continue
                label = self.srl_model.config.id2label.get(pred_id.item(), 'UNKNOWN')
                if label != '_':  # 只保留非空标签
                    token_label_pairs.append((token, label))
            
            # 合并连续的同标签span
            merged_spans = []
            if token_label_pairs:
                current_span = [token_label_pairs[0]]
                for token, label in token_label_pairs[1:]:
                    if label == current_span[0][1]:  # 同标签
                        current_span.append((token, label))
                    else:  # 标签变化，保存当前span，开始新span
                        merged_spans.append(current_span)
                        current_span = [(token, label)]
                merged_spans.append(current_span)  # 最后一个span
            
            # 改进4：构建arguments字典（列表结构，支持多个同类型论元）
            arguments = {}
            for span in merged_spans:
                span_text = " ".join([t[0].replace('##', '') for t in span])
                span_label = span[0][1]
                
                # 清理span文本
                span_text = span_text.strip()
                if not span_text:
                    continue
                
                # 检查是否是谓词标签（V, C-V等），如果是则跳过（谓词已从输入动词提取）
                if 'V' in span_label and span_label != '_':
                    continue
                
                # 验证论元有效性
                if self._is_valid_argument(span_text, verb_lemma):
                    # 使用列表结构，保留多个独立论元
                    if span_label not in arguments:
                        arguments[span_label] = []
                    arguments[span_label].append(span_text)
            
            # 过滤重复的论元（保留列表结构）
            arguments = self._filter_duplicate_arguments_list(arguments)
            
            # 改进5：被动语态处理
            logical_agent, logical_patient = self._extract_logical_roles(
                doc, verb, arguments, verb_lemma
            )
            
            # 构建SRLEventUnit（即使没有谓词或论元也保留）
            event = SRLEventUnit(
                paper_id=paper_id,
                year=year,
                section=section,
                sentence_text=sentence,
                predicate=verb_lemma,  # 保留谓词，即使低信息也保留
                arguments=arguments,
                logical_agent=logical_agent,
                logical_patient=logical_patient,
                sentence_id=sentence_id,
                original_sentence=sentence,
                source_path="SRL",
                has_srl_structure=bool(verb_lemma or arguments),  # 有谓词或论元才算有结构
                low_info_predicate=is_low_info_predicate,  # 标记低信息谓词，不硬写confidence
                structure_confidence=0.0  # 由compute_srl_structure_score统一计算
            )
            events.append(event)
        
        return events
    
    def _is_valid_argument(self, arg_text: str, predicate: str) -> bool:
        """过滤无效的论元"""
        if not arg_text or len(arg_text.strip()) < 2:
            return False
        
        arg_lower = arg_text.lower().strip()
        predicate_lower = predicate.lower().strip()
        
        if arg_lower == predicate_lower:
            return False
        
        if arg_lower in ['the', 'a', 'an', 'of', 'in', 'on', 'at', 'for', 'to', 'by', 'with']:
            return False
        
        if len(arg_lower.split()) == 1 and len(arg_lower) <= 2:
            return False
        
        return True
    
    def _filter_duplicate_arguments_list(self, arguments: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """过滤重复的论元（列表结构），保留独立的论元"""
        filtered = {}
        
        for arg_type, arg_list in arguments.items():
            seen_texts = set()
            unique_args = []
            for arg_text in arg_list:
                arg_normalized = arg_text.lower().strip()
                if arg_normalized not in seen_texts:
                    seen_texts.add(arg_normalized)
                    unique_args.append(arg_text)
            if unique_args:
                filtered[arg_type] = unique_args
        
        return filtered
    
    def _extract_logical_roles(self, doc, verb_token, arguments: Dict[str, List[str]], verb_lemma: str) -> Tuple[Optional[str], Optional[str]]:
        """提取逻辑施事和受事（处理被动语态）
        
        基于明确的依存关系规则检测被动语态，保留原始ARG0/ARG1，逻辑角色作为补充。
        
        Args:
            doc: spaCy文档对象
            verb_token: 动词token
            arguments: SRL论元字典（保留原始ARG0/ARG1）
            verb_lemma: 动词词根
            
        Returns:
            (logical_agent, logical_patient): 逻辑施事和受事（补充字段，不覆盖原始ARG）
        """
        logical_agent = None
        logical_patient = None
        
        # 明确规则检测被动语态：检查nsubjpass或auxpass依存关系
        is_passive = False
        has_nsubjpass = False
        has_auxpass = False
        
        for child in verb_token.children:
            if child.dep_ == "nsubjpass":
                has_nsubjpass = True
                is_passive = True
            if child.dep_ == "auxpass":
                has_auxpass = True
                is_passive = True
        
        # 额外检查：过去分词 + 助动词组合
        if not is_passive and verb_token.tag_ in ["VBN", "VBD"]:  # 过去分词或过去式
            # 检查前面是否有be/have等助动词
            for token in doc:
                if token.i < verb_token.i and token.lemma_.lower() in ['be', 'have']:
                    # 检查是否有被动标记
                    if any(c.dep_ == "auxpass" for c in verb_token.children):
                        is_passive = True
                        break
        
        # 检查是否有by-phrase（被动语态的施事）
        by_phrase = None
        for child in verb_token.children:
            if child.dep_ == "agent" or (child.dep_ == "prep" and child.text.lower() == "by"):
                for prep_child in child.children:
                    if prep_child.dep_ == "pobj":
                        by_phrase = self._get_full_phrase(prep_child)
                        break
                if by_phrase:
                    break
        
        if is_passive:
            # 被动语态：ARG1通常是受事（被动主语），ARG0或by-phrase是施事
            arg1_list = arguments.get("ARG1", [])
            arg0_list = arguments.get("ARG0", [])
            
            # 逻辑受事：通常是ARG1或被动主语
            if arg1_list:
                logical_patient = arg1_list[0]
            else:
                # 从依存树提取被动主语
                for child in verb_token.children:
                    if child.dep_ == "nsubjpass":
                        logical_patient = self._get_full_phrase(child)
                        break
            
            # 逻辑施事：by-phrase优先，然后是ARG0
            if by_phrase:
                logical_agent = by_phrase
            elif arg0_list:
                logical_agent = arg0_list[0]
        else:
            # 主动语态：ARG0是施事，ARG1是受事
            arg0_list = arguments.get("ARG0", [])
            arg1_list = arguments.get("ARG1", [])
            
            if arg0_list:
                logical_agent = arg0_list[0]
            if arg1_list:
                logical_patient = arg1_list[0]
        
        return logical_agent, logical_patient
    
    def _find_subject(self, verb, doc) -> Optional[str]:
        """查找动词的主语"""
        for child in verb.children:
            if child.dep_ in ["nsubj", "nsubjpass"]:
                return self._get_full_phrase(child)
        return None
    
    def _find_direct_object(self, verb, doc) -> Optional[str]:
        """查找直接宾语"""
        for child in verb.children:
            if child.dep_ == "dobj":
                return self._get_full_phrase(child)
        return None
    
    def _find_indirect_object(self, verb, doc) -> Optional[str]:
        """查找间接宾语"""
        for child in verb.children:
            if child.dep_ in ["dative", "pobj"]:
                return self._get_full_phrase(child)
        return None
    
    def _find_temporal_modifier(self, verb, doc) -> Optional[str]:
        """查找时间修饰语"""
        for child in verb.children:
            if child.dep_ == "npadvmod" and any(ent.label_ == "DATE" or ent.label_ == "TIME" 
                                                 for ent in doc.ents if child in ent):
                return child.text
        for child in verb.children:
            if child.dep_ == "advmod" and "time" in child.text.lower():
                return child.text
        return None
    
    def _find_location_modifier(self, verb, doc) -> Optional[str]:
        """查找地点修饰语"""
        for child in verb.children:
            if child.dep_ == "prep" and child.text.lower() in ["in", "on", "at", "from", "to"]:
                for prep_child in child.children:
                    if prep_child.dep_ == "pobj":
                        return self._get_full_phrase(prep_child)
        return None
    
    def _find_manner_modifier(self, verb, doc) -> Optional[str]:
        """查找方式修饰语"""
        for child in verb.children:
            if child.dep_ == "advmod" and child.pos_ == "ADV":
                return child.text
        return None
    
    def _get_full_phrase(self, token) -> str:
        """获取完整的短语（包括修饰语）"""
        phrase_tokens = [token]
        
        for child in token.lefts:
            if child.dep_ in ["det", "amod", "compound", "nummod"]:
                phrase_tokens.insert(0, child)
        
        for child in token.rights:
            if child.dep_ in ["amod", "compound", "nmod"]:
                phrase_tokens.append(child)
        
        phrase_tokens.sort(key=lambda t: t.i)
        return " ".join([t.text for t in phrase_tokens])
    
    def _post_process_events(self, events: List[SRLEventUnit], sentence: str) -> List[SRLEventUnit]:
        if not events:
            return events
        
        doc = self.nlp(sentence)
        processed_events = []
        
        for event in events:
            # 处理列表结构的论元
            refined_arguments = {}
            for arg_label, arg_list in event.arguments.items():
                refined_list = []
                for arg_text in arg_list:
                    refined_text = self._refine_argument_span(arg_text, sentence, doc)
                    if refined_text:
                        refined_list.append(refined_text)
                if refined_list:
                    refined_arguments[arg_label] = refined_list
            event.arguments = refined_arguments
            
            event = self._integrate_relative_clauses(event, doc)
            
            # 如果无谓词或谓词是系动词，尝试从名词化结构提取
            if not event.predicate or event.predicate in ["be", "have", "do"]:
                nominalized = self._detect_enhanced_nominalizations(doc, event)
                if nominalized:
                    event.predicate = nominalized['predicate']
                    # 合并名词化结构的论元（nominalized['arguments']已经是Dict[str, List[str]]格式）
                    for arg_label, arg_list in nominalized['arguments'].items():
                        if arg_label not in event.arguments:
                            event.arguments[arg_label] = []
                        # arg_list已经是列表，使用extend而不是append
                        if isinstance(arg_list, list):
                            event.arguments[arg_label].extend(arg_list)
                        else:
                            # 兼容旧格式（字符串）
                            event.arguments[arg_label].append(arg_list)
            
            processed_events.append(event)
        
        return processed_events
    
    def _refine_argument_span(self, arg_text: str, sentence: str, doc) -> str:
        if not arg_text:
            return arg_text
        
        arg_lower = arg_text.lower()
        sentence_lower = sentence.lower()
        start_idx = sentence_lower.find(arg_lower)
        if start_idx == -1:
            return arg_text
        
        arg_tokens = arg_text.split()
        if not arg_tokens:
            return arg_text
        
        first_token_text = arg_tokens[0].lower()
        first_token = None
        
        for token in doc:
            if token.text.lower() == first_token_text:
                first_token = token
                break
        
        if not first_token:
            return arg_text
        
        expanded_tokens = []
        for token in doc:
            if token.i < first_token.i:
                if token.dep_ in ["compound", "amod", "det", "nummod", "nmod"]:
                    if token.head == first_token or first_token in token.subtree:
                        expanded_tokens.append(token)
        
        last_token = first_token
        for i in range(1, len(arg_tokens)):
            for token in doc:
                if token.i > last_token.i and token.text.lower() == arg_tokens[i].lower():
                    last_token = token
                    break
        
        for token in doc:
            if token.i > last_token.i:
                if token.dep_ in ["amod", "compound", "nmod", "prep"]:
                    if token.head == last_token or last_token in token.subtree:
                        expanded_tokens.append(token)
                        if token.dep_ == "prep":
                            for prep_child in token.children:
                                if prep_child.dep_ == "pobj":
                                    expanded_tokens.append(prep_child)
        
        all_tokens = sorted(expanded_tokens + [first_token] + [last_token], key=lambda t: t.i)
        if all_tokens:
            return " ".join([t.text for t in all_tokens])
        
        return arg_text
    
    def _integrate_relative_clauses(self, event: SRLEventUnit, doc) -> SRLEventUnit:
        relative_markers = ["that", "which", "who", "whom", "whose", "where", "when"]
        
        # 处理列表结构的论元
        for arg_label, arg_list in event.arguments.items():
            updated_list = []
            for arg_text in arg_list:
                arg_lower = arg_text.lower()
                sentence_lower = event.sentence_text.lower()
                arg_pos = sentence_lower.find(arg_lower)
                if arg_pos == -1:
                    updated_list.append(arg_text)
                    continue
                
                after_arg = sentence_lower[arg_pos + len(arg_lower):].strip()
                found_relative = False
                
                for marker in relative_markers:
                    if after_arg.startswith(f" {marker} "):
                        relative_clause = self._extract_relative_clause(doc, arg_text, marker)
                        if relative_clause:
                            updated_list.append(f"{arg_text} {relative_clause}")
                            found_relative = True
                        break
                
                if not found_relative:
                    updated_list.append(arg_text)
            
            event.arguments[arg_label] = updated_list
        
        return event
    
    def _extract_relative_clause(self, doc, head_text: str, marker: str) -> Optional[str]:
        for token in doc:
            if token.text.lower() == marker and token.dep_ in ["relcl", "acl"]:
                clause_tokens = []
                for t in token.subtree:
                    if t.i >= token.i:
                        clause_tokens.append(t)
                
                if clause_tokens:
                    return " ".join([t.text for t in clause_tokens])
        
        return None
    
    def _detect_enhanced_nominalizations(self, doc, event: SRLEventUnit) -> Optional[Dict]:
        nominalization_patterns = [
            "development", "analysis", "study", "design", "application",
            "investigation", "examination", "evaluation", "assessment",
            "implementation", "utilization", "optimization", "improvement"
        ]
        
        for token in doc:
            if token.pos_ == "NOUN":
                lemma = token.lemma_.lower()
                
                if lemma in nominalization_patterns or any(lemma.endswith(suffix) for suffix in ["tion", "sion", "ment", "ing"]):
                    arguments = {}
                    
                    for child in token.children:
                        if child.dep_ in ["nmod:poss", "poss", "det"]:
                            if child.dep_ != "det":
                                arg0_text = self._get_full_phrase(child)
                                if arg0_text:
                                    arguments["ARG0"] = [arg0_text]  # 列表格式
                    
                    for child in token.children:
                        if child.dep_ == "prep" and child.text.lower() == "of":
                            for prep_child in child.children:
                                if prep_child.dep_ == "pobj":
                                    arg1_text = self._get_full_phrase(prep_child)
                                    if arg1_text:
                                        arguments["ARG1"] = [arg1_text]  # 列表格式
                    
                    for child in token.children:
                        if child.dep_ == "prep":
                            prep_text = child.text.lower()
                            if prep_text in ["for", "in", "on", "with", "by"]:
                                for prep_child in child.children:
                                    if prep_child.dep_ == "pobj":
                                        arg_label = f"ARGM-{prep_text.upper()}"
                                        arg_text = self._get_full_phrase(prep_child)
                                        if arg_text:
                                            if arg_label not in arguments:
                                                arguments[arg_label] = []
                                            arguments[arg_label].append(arg_text)  # 列表格式
                    
                    if arguments:
                        # 已经是列表格式
                        return {
                            "predicate": lemma,
                            "arguments": arguments
                        }
        
        return None
    
    def _extract_from_nominalizations(self, doc, sentence_id: int, paper_id: str, year: int, 
                                     section: str, sentence: str) -> List[SRLEventUnit]:
        events = []
        
        nominalization_result = self._detect_enhanced_nominalizations(doc, SRLEventUnit(
            sentence_text=sentence,
            predicate=None,
            arguments={}
        ))
        
        if nominalization_result:
            # 确保arguments是列表格式
            normalized_args = {}
            for k, v in nominalization_result["arguments"].items():
                if isinstance(v, list):
                    normalized_args[k] = v
                else:
                    normalized_args[k] = [v] if v else []
            
            event = SRLEventUnit(
                paper_id=paper_id,
                year=year,
                section=section,
                sentence_text=sentence,
                predicate=nominalization_result["predicate"],
                arguments=normalized_args,
                sentence_id=sentence_id,
                original_sentence=sentence,
                source_path="SRL",
                has_srl_structure=bool(nominalization_result["predicate"] or normalized_args),
                low_info_predicate=False,
                structure_confidence=0.0  # 由compute_srl_structure_score统一计算
            )
            events.append(event)
        
        return events


def compute_srl_structure_score(srl_event: SRLEventUnit) -> float:
    """计算 SRL 事件的结构评分
    
    完整结构（ARG0 + Predicate + ARG1）得高分，用于排序和优先级。
    避免双重计分：逻辑角色作为bonus，不重复计算ARG0/ARG1。
    低信息谓词降权：在最终分数上应用降权，而不是硬写confidence。
    
    注意：
    - structure_confidence 是"SRL结构质量置信度"，不是"整条信息单元的总置信度"
    - 全局置信度应由上层统一融合：SRL结构 + 文本特征 + embedding + NLI等
    - base_score ∈ [0, 1.0], bonus_score ∈ [0, 0.2]，避免bonus淹没base
    
    Args:
        srl_event: SRL 事件单元
        
    Returns:
        float: 结构评分 [0.0, 1.0]，同时更新srl_event.structure_confidence
    """
    # Base score: 基础结构完整性 [0, 1.0]
    base_score = 0.0
    
    # 基础分：有谓词
    if srl_event.predicate:
        base_score += 0.3
    
    # 完整结构加分：ARG0 + Predicate + ARG1（适配列表结构）
    has_arg0 = "ARG0" in srl_event.arguments and len(srl_event.arguments["ARG0"]) > 0
    has_arg1 = "ARG1" in srl_event.arguments and len(srl_event.arguments["ARG1"]) > 0
    
    if has_arg0 and has_arg1 and srl_event.predicate:
        base_score += 0.5  # 完整结构
    elif has_arg0 or has_arg1:
        base_score += 0.2  # 部分结构
    
    # 额外论元加分
    other_args = [k for k in srl_event.arguments.keys() if k not in ["ARG0", "ARG1"]]
    if other_args:
        base_score += min(0.2, len(other_args) * 0.05)
    
    # 即使没有谓词，如果有关键实体和多个论元，也给基础分
    if not srl_event.predicate and len(srl_event.arguments) >= 2:
        base_score += 0.1
    
    # 确保base_score不超过最大值
    base_score = min(base_score, SRLModule.BASE_SCORE_MAX)
    
    # Bonus score: 逻辑角色（不重复计分，作为额外加分）[0, 0.2]
    bonus_score = 0.0
    if srl_event.logical_agent and srl_event.logical_patient:
        # 只有在ARG0/ARG1不完整时，逻辑角色才作为bonus
        # 避免双重计分：如果ARG0/ARG1都不存在，逻辑角色补充了缺失的结构信息
        if not (has_arg0 and has_arg1):
            bonus_score += 0.1  # 逻辑角色补充了缺失的结构信息
    
    # 确保bonus_score不超过最大值
    bonus_score = min(bonus_score, SRLModule.BONUS_SCORE_MAX)
    
    # 低信息谓词降权（在最终分数上应用，使用配置常量）
    final_score = base_score + bonus_score
    if srl_event.low_info_predicate:
        final_score *= SRLModule.LOW_INFO_PREDICATE_PENALTY
    
    # 无SRL结构的情况
    if not srl_event.has_srl_structure:
        final_score = 0.0
    
    # 更新structure_confidence字段（不硬写全局confidence）
    # 注意：这是"SRL结构质量置信度"，不是"整条信息单元的总置信度"
    srl_event.structure_confidence = min(1.0, final_score)
    
    return min(1.0, final_score)


_global_miner = None

def extract_opinions_from_document(doc, emb_model, cache, has_abstract=False, paper_id=None, paper_title=None, paper_abstract=None, nlp_model=None) -> List[Tuple[str, StructuredOpinion]]:
    """从文档中执行语义识别流程
    
    完整流程：
    1. Module 1.5: 候选原子抽取（从句子中提取语义原子）
    2. Module 2-4: 原子评分与筛选（NLI评分、语义相似度、规则筛选）
    3. Module 5: 抽象层构建（概念映射 → 原子聚类 → 主题角色识别 → 主题融合 → 主题抽象 → 结构化组合）
    
    Returns:
        List[Tuple[str, StructuredOpinion]]: 语义识别结果列表（主题或原子文本，结构化语义对象）
    """
    global _global_miner
    
    doc_extract_start = time.time()
    print(f"\n{'='*80}")
    print(f"[文档提取开始] Paper ID: {paper_id}")
    if paper_title:
        print(f"  标题: {paper_title[:100]}{'...' if len(paper_title) > 100 else ''}")
    
    if _global_miner is None:
        if not torch.cuda.is_available():
            raise RuntimeError(
                "GPU不可用！系统要求使用GPU运行。\n"
                "请检查CUDA安装和GPU驱动。"
            )
        _global_miner = ResearchInsightMiner(device='cuda')
    
    paper_text = doc.text if doc else ""
    if not paper_title:
        if doc:
            doc_sents = list(doc.sents)
            if doc_sents and len(doc_sents[0].text) < 200:
                paper_title = doc_sents[0].text
    
    if paper_title and paper_abstract:
        combined_text = f"{paper_title}\n\n{paper_abstract}".strip()
        print(f"  使用: 标题 + 摘要 (长度: {len(combined_text)} 字符)")
    elif paper_title:
        combined_text = paper_title
        print(f"  使用: 仅标题 (长度: {len(combined_text)} 字符)")
    elif paper_abstract:
        combined_text = paper_abstract
        print(f"  使用: 仅摘要 (长度: {len(combined_text)} 字符)")
    else:
        combined_text = paper_text
        print(f"  使用: 全文 (长度: {len(combined_text)} 字符)")
    
    results = _global_miner.extract(combined_text, threshold=0.75)
    
    doc_extract_time = (time.time() - doc_extract_start) * 1000
    
    if results:
        semantic_results = []
        theme_count = 0
        atom_count = 0
        for res in results:
            atom_text = res.get('theme_text', res.get('atom_text', res.get('sentence', '')))
            category = res.get('category', res.get('theme_role', ''))
            confidence = res.get('confidence', 0.0)
            
            if 'theme_text' in res:
                theme_count += 1
            else:
                atom_count += 1
            
            structured_opinion = StructuredOpinion(
                object=atom_text,
                predicate=category,
                context=f"confidence:{confidence}"
            )
            
            normalized_text = atom_text
            semantic_results.append((normalized_text, structured_opinion))
        
        print(f"[文档提取完成] Paper ID: {paper_id}")
        print(f"  - 提取结果: {len(semantic_results)} 个 (主题: {theme_count}, 原子: {atom_count})")
        print(f"  - 文档提取耗时: {doc_extract_time:.2f}ms")
        print(f"{'='*80}\n")
        
        return semantic_results
    else:
        print(f"[文档提取完成] Paper ID: {paper_id}")
        print(f"  - 提取结果: 0 个")
        print(f"  - 文档提取耗时: {doc_extract_time:.2f}ms")
        print(f"{'='*80}\n")
        return []

class RawEmbeddingStore:
    def __init__(self, path: str, dim: int, map_size_bytes: int = 10 * 1024 * 1024 * 1024):
        """原始向量存储"""
        self.dim = dim
        self.path = Path(path)
        self.enabled = bool(lmdb)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.env = lmdb.open(str(self.path), map_size=map_size_bytes, subdir=False, writemap=False, lock=True)

    def put(self, cid: int, vector: np.ndarray):
        vec = np.asarray(vector, dtype='float32')
        if vec.ndim != 1 or vec.shape[0] != self.dim:
            raise ValueError(f"RawEmbeddingStore.put expects shape ({self.dim},), got {vec.shape}")
        key = struct.pack('>Q', cid)
        data = vec.tobytes()
        with self.env.begin(write=True) as txn:
            txn.put(key, data)

    def get(self, cid: int):
        key = struct.pack('>Q', cid)
        with self.env.begin() as txn:
            data = txn.get(key)
            if data is None:
                return None
            return np.frombuffer(data, dtype='float32').copy()

    def iterate(self):
        with self.env.begin() as txn:
            cursor = txn.cursor()
            for key, value in cursor:
                cid = struct.unpack('>Q', key)[0]
                yield cid, np.frombuffer(value, dtype='float32').copy()

    def count(self):
        with self.env.begin() as txn:
            stat = txn.stat()
            return stat.get('entries', 0)

    def close(self):
        if self.enabled and self.env is not None:
            self.env.close()

def encode_with_cache(phrases, emb_model, cache):
    if not phrases:
        return np.zeros((0, cache.dim), dtype='float32')

    if USE_HASH_DEDUP:
        unique_phrases = []
        hash_to_unique_idx = {}
        phrase_to_unique_idx = []
        
        for phrase in phrases:
            h = _get_hash(phrase)
            if h in hash_to_unique_idx:
                phrase_to_unique_idx.append(hash_to_unique_idx[h])
            else:
                unique_idx = len(unique_phrases)
                unique_phrases.append(phrase)
                hash_to_unique_idx[h] = unique_idx
                phrase_to_unique_idx.append(unique_idx)
        
        with _microbatch_hash_lock:
            for h in hash_to_unique_idx:
                if h in _microbatch_hash_lru:
                    _microbatch_hash_lru.move_to_end(h)
                else:
                    _microbatch_hash_lru[h] = None
            
            if len(_microbatch_hash_lru) > HASH_SET_SIZE:
                target_size = HASH_SET_SIZE // 2
                while len(_microbatch_hash_lru) > target_size:
                    _microbatch_hash_lru.popitem(last=False)
    else:
        unique_phrases = phrases
        phrase_to_unique_idx = list(range(len(phrases)))

    keys = [normalize_text_cached(p) for p in unique_phrases]
    vecs = [cache.get(k) for k in keys]
    misses_idx = [i for i, v in enumerate(vecs) if v is None]

    if misses_idx:
        to_encode = [unique_phrases[i] for i in misses_idx]
        
        short_texts = [t for t in to_encode if len(t) <= 512]
        medium_texts = [t for t in to_encode if 512 < len(t) <= 1024]
        long_texts = [t for t in to_encode if len(t) > 1024]
        
        all_new = []
        if short_texts:
            all_new.extend(_encode_batch(short_texts, emb_model, EMBED_BATCH_SIZE))
        if medium_texts:
            all_new.extend(_encode_batch(medium_texts, emb_model, EMBED_BATCH_SIZE // 4))
        if long_texts:
            all_new.extend(_encode_batch(long_texts, emb_model, max(32, EMBED_BATCH_SIZE // 16)))
        
        for j, i in enumerate(misses_idx):
            vecs[i] = all_new[j]
            cache.put(keys[i], all_new[j])

    if USE_HASH_DEDUP and len(unique_phrases) < len(phrases):
        result_vecs = [vecs[idx] for idx in phrase_to_unique_idx]
        return np.stack(result_vecs, axis=0).astype('float32', copy=False)
    else:
        return np.stack(vecs, axis=0).astype('float32', copy=False)

def _encode_batch(texts, emb_model, batch_size):
    emb_model.eval()
    all_vecs = []
    
    i = 0
    while i < len(texts):
        current_bs = min(batch_size, len(texts) - i)
        batch = texts[i:i + current_bs]
        
        with torch.no_grad():
            vecs = emb_model.encode(
                batch, convert_to_numpy=True, normalize_embeddings=True,
                batch_size=min(current_bs, 1024), show_progress_bar=False
            ).astype('float32', copy=False)
        all_vecs.append(vecs)
        i += len(batch)
    
    return np.vstack(all_vecs) if all_vecs else np.zeros((0, emb_model.get_sentence_embedding_dimension()), dtype='float32')

class TwoLevelEmbCache:
    def __init__(self, dim: int):
        self.dim = dim
        self.store = OrderedDict()
        self.hits = self.total = 0
        self._lock = threading.Lock()
        
        self.conn = sqlite3.connect(SQLITE_CACHE_PATH, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("CREATE TABLE IF NOT EXISTS emb (k TEXT PRIMARY KEY, v BLOB)")
        self.conn.commit()
        
        self.bloom = None
        self.bloom_count = 0
        self.bloom_rebuild_threshold = int(BLOOM_CAPACITY * 0.8)
        if USE_BLOOM_FILTER:
            self.bloom = BloomFilter(capacity=BLOOM_CAPACITY, error_rate=BLOOM_ERROR_RATE)
            self._load_bloom_from_sqlite(limit=min(100000, BLOOM_CAPACITY // 2))
        
        self.write_queue = queue.Queue(maxsize=10000)
        self.write_thread = threading.Thread(target=self._write_worker, daemon=True)
        self.write_thread.start()
        self._shutdown = False
        self._shutdown_lock = threading.Lock()
    
    def _load_bloom_from_sqlite(self, limit=None):
        if not self.bloom:
            return
        query = "SELECT k FROM emb"
        if limit:
            query += f" LIMIT {limit}"
        cur = self.conn.execute(query)
        count = 0
        for row in cur:
            self.bloom.add(row[0])
            count += 1
        self.bloom_count = count
    
    def _rebuild_bloom_if_needed(self):
        if not self.bloom or self.bloom_count < self.bloom_rebuild_threshold:
            return
        self.bloom = BloomFilter(capacity=BLOOM_CAPACITY, error_rate=BLOOM_ERROR_RATE)
        cur = self.conn.execute("SELECT k FROM emb ORDER BY rowid DESC LIMIT ?", (BLOOM_CAPACITY // 2,))
        count = 0
        for row in cur:
            self.bloom.add(row[0])
            count += 1
        self.bloom_count = count

    def _write_worker(self):
        batch = []
        while True:
            try:
                item = self.write_queue.get(timeout=1.0)
                if item is None:
                    if batch:
                        self._write_batch_safe(batch)
                        for _ in batch:
                            self.write_queue.task_done()
                        batch = []
                    self.write_queue.task_done()
                    break
                batch.append(item)
                if len(batch) >= SQLITE_BATCH_SIZE:
                    self._write_batch_safe(batch)
                    for _ in batch:
                        self.write_queue.task_done()
                    batch = []
            except queue.Empty:
                if batch:
                    self._write_batch_safe(batch)
                    for _ in batch:
                        self.write_queue.task_done()
                    batch = []
            except Exception as e:
                import traceback
                traceback.print_exc()
                for _ in batch:
                    self.write_queue.task_done()
                batch = []

    def _write_batch_safe(self, batch):
        self.conn.executemany("INSERT OR REPLACE INTO emb(k,v) VALUES(?,?)", batch)
        self.conn.commit()

    def get(self, key_norm: str):
        self.total += 1
        with self._lock:
            if key_norm in self.store:
                self.store.move_to_end(key_norm)
                self.hits += 1
                return self.store[key_norm]
        if self.bloom and key_norm not in self.bloom:
            return None
        cur = self.conn.execute("SELECT v FROM emb WHERE k=?", (key_norm,))
        row = cur.fetchone()
        if row:
            vec = np.frombuffer(zlib.decompress(row[0]), dtype=np.float16).astype(np.float32)
            with self._lock:
                self.store[key_norm] = vec
                self.store.move_to_end(key_norm)
                if len(self.store) > EMBED_CACHE_SIZE:
                    self.store.popitem(last=False)
            self.hits += 1
            return vec
        return None

    def put(self, key_norm: str, vec: np.ndarray):
        vec = vec.astype(np.float32, copy=False)
        if self.bloom:
            if self.bloom_count >= self.bloom_rebuild_threshold:
                self._rebuild_bloom_if_needed()
            if key_norm not in self.bloom:
                self.bloom.add(key_norm)
                self.bloom_count += 1
            else:
                self.bloom.add(key_norm)
        with self._lock:
            self.store[key_norm] = vec
            self.store.move_to_end(key_norm)
            if len(self.store) > EMBED_CACHE_SIZE:
                self.store.popitem(last=False)
        blob = zlib.compress(vec.astype(np.float16).tobytes())
        self.write_queue.put((key_norm, blob), block=True, timeout=5.0)

    def flush(self):
        if not self.write_thread.is_alive():
            return
        timeout = 30.0
        start_time = time.time()
        while self.write_queue.unfinished_tasks > 0:
            if time.time() - start_time > timeout:
                remaining_items = self.write_queue.qsize()
                unfinished = self.write_queue.unfinished_tasks
                break
            time.sleep(0.1)

    def get_stats(self):
        return {'hit_rate': self.hits / max(1, self.total), 'cache_size': len(self.store)}

    def close(self):
        with self._shutdown_lock:
            if self._shutdown:
                return
            self._shutdown = True
        shutdown_sent = False
        try:
            self.write_queue.put_nowait(None)
            shutdown_sent = True
        except queue.Full:
            self.write_queue.put(None, block=True, timeout=None)
            shutdown_sent = True
        if not shutdown_sent:
            remaining_batch = []
            while True:
                try:
                    item = self.write_queue.get_nowait()
                    if item is not None:
                        remaining_batch.append(item)
                except queue.Empty:
                    break
            if remaining_batch:
                self._write_batch_safe(remaining_batch)
        if self.write_thread.is_alive():
            self.write_thread.join(timeout=10.0)
            if self.write_thread.is_alive():
                pass
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()
    
    def __del__(self):
        if not self._shutdown:
            self.close()

class VectorCompressor:
    def __init__(self, original_dim=384, compressed_dim=256, use_pca=True):
        self.original_dim = original_dim
        self.compressed_dim = compressed_dim
        self.use_pca = use_pca
        self.pca = None
        self.trained = False
        self.mean = None
        self.components = None
    
    def train(self, vectors):
        """训练PCA"""
        if not self.use_pca or self.trained:
            return
        
        vectors = np.asarray(vectors, dtype='float32')
        if len(vectors) < 2:
            return
        
        estimated_memory_mb = len(vectors) * vectors.shape[1] * 4 * 3 / (1024 * 1024)
        available_memory_mb = self._get_available_memory_mb()
        
        if estimated_memory_mb > available_memory_mb * 0.5:
            max_samples = int(available_memory_mb * 0.5 * 1024 * 1024 / (vectors.shape[1] * 4 * 3))
            if max_samples < len(vectors):
                indices = np.random.choice(len(vectors), size=max_samples, replace=False)
                vectors = vectors[indices]
        
        self.mean = vectors.mean(axis=0)
        centered = vectors - self.mean
        
        U, s, Vt = np.linalg.svd(centered, full_matrices=False)
        
        self.components = Vt[:self.compressed_dim].T
        self.trained = True
    
    def _get_available_memory_mb(self):
        import psutil
        return psutil.virtual_memory().available / (1024 * 1024)
    
    def compress(self, vectors):
        """压缩向量"""
        if not self.trained:
            return vectors
        
        vectors = np.asarray(vectors, dtype='float32')
        was_1d = len(vectors.shape) == 1
        if was_1d:
            vectors = vectors.reshape(1, -1)
        
        centered = vectors - self.mean
        compressed = centered @ self.components
        
        if was_1d:
            return compressed.squeeze(0).astype('float32')
        return compressed.astype('float32')
    
    def save(self, path):
        if not self.trained:
            return
        
        data = {
            'original_dim': self.original_dim,
            'compressed_dim': self.compressed_dim,
            'mean': self.mean.tolist(),
            'components': self.components.tolist()
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f)
    
    @staticmethod
    def load(path):
        if not Path(path).exists():
            return None
        
        with open(path, 'r') as f:
            data = json.load(f)
        
        obj = VectorCompressor(
            original_dim=data['original_dim'],
            compressed_dim=data['compressed_dim'],
            use_pca=True
        )
        obj.mean = np.array(data['mean'], dtype='float32')
        obj.components = np.array(data['components'], dtype='float32')
        obj.trained = True
        return obj

class IncrementalOpinionIndex:
    def __init__(self, emb_dim=384):
        self.original_emb_dim = emb_dim
        
        self.use_lmdb = USE_LMDB_META and lmdb
        if self.use_lmdb:
            Path(LMDB_META_PATH).parent.mkdir(parents=True, exist_ok=True)
            self.lmdb_env = lmdb.open(LMDB_META_PATH, map_size=10*1024*1024*1024, readonly=False)
            self.meta_cache = OrderedDict()
        else:
            self.meta = {}
            self.lmdb_env = None
        
        self.raw_store = None
        if USE_VECTOR_COMPRESSION:
            self.raw_store = RawEmbeddingStore(RAW_EMBEDDING_PATH, emb_dim, RAW_EMBEDDING_MAP_SIZE)
        
        self.compressor = None
        self.compressed_dim = emb_dim
        if USE_VECTOR_COMPRESSION:
            compressor_path = CHECKPOINT_DIR / "vector_compressor.json"
            self.compressor = VectorCompressor.load(str(compressor_path))
            if self.compressor and self.compressor.trained:
                self.compressed_dim = self.compressor.compressed_dim
            elif self.raw_store and self.raw_store.count() >= ENABLE_PCA_AT_OPINIONS:
                self.compressor = VectorCompressor(
                    original_dim=emb_dim,
                    compressed_dim=COMPRESSED_DIM,
                    use_pca=True
                )
        
        index_dim = self.compressed_dim
        if USE_HNSW:
            base = faiss.IndexHNSWFlat(index_dim, HNSW_M, faiss.METRIC_INNER_PRODUCT)
            base.hnsw.efSearch = HNSW_EF_SEARCH
            base.hnsw.efConstruction = HNSW_EF_CONSTRUCTION
        else:
            base = faiss.IndexFlatIP(index_dim)
        
        self.index = faiss.IndexIDMap(base)
        self.next_id = 0
        
        self.pending_ids = []
        self.pending_meta = []
    
    def _get_meta_count(self):
        if self.use_lmdb:
            with self.lmdb_env.begin() as txn:
                return txn.stat()['entries']
        else:
            return len(self.meta) if hasattr(self, 'meta') else 0
    
    def _get_meta(self, cid):
        """获取元数据"""
        if self.use_lmdb:
            if cid in self.meta_cache:
                self.meta_cache.move_to_end(cid)
                return self.meta_cache[cid]
            with self.lmdb_env.begin() as txn:
                key = str(cid).encode()
                val = txn.get(key)
                if val:
                    if msgpack:
                        meta = msgpack.unpackb(val, raw=False)
                    else:
                        meta = json.loads(val.decode())
                    meta['alias_norm_set'] = {normalize_text(a) for a in meta.get('aliases', [])}
                    self.meta_cache[cid] = meta
                    self.meta_cache.move_to_end(cid)
                    if len(self.meta_cache) > LMDB_META_CACHE_SIZE:
                        self.meta_cache.popitem(last=False)
                    return meta
            return None
        else:
            return self.meta.get(cid)
    
    def _safe_get_meta(self, cid):
        """安全获取元数据，如果不存在返回最小结构"""
        meta = self._get_meta(cid)
        if meta is None:
            return {
                'opinion_text': '',
                'canonical_label': '',
                'first_seen_year': None,
                'aliases': [],
                'alias_norm_set': set()
            }
        return meta
    
    def _set_meta(self, cid, meta):
        if self.use_lmdb:
            self.meta_cache[cid] = meta
            self.meta_cache.move_to_end(cid)
            if len(self.meta_cache) > LMDB_META_CACHE_SIZE:
                self.meta_cache.popitem(last=False)
            
            self.pending_meta.append((cid, meta))
            if len(self.pending_meta) >= 100:
                self._flush_meta()
        else:
            self.meta[cid] = meta
    
    def _flush_meta(self):
        """刷新元数据到LMDB"""
        if not self.use_lmdb or not self.pending_meta:
            return
        
        with self.lmdb_env.begin(write=True) as txn:
            for cid, meta in self.pending_meta:
                meta_serializable = {k: v for k, v in meta.items() if k != 'alias_norm_set'}
                key = str(cid).encode()
                if msgpack:
                    val = msgpack.packb(meta_serializable, use_bin_type=True)
                else:
                    val = json.dumps(meta_serializable, ensure_ascii=False).encode()
                txn.put(key, val)
        self.pending_meta.clear()

    def add(self, opinion_text, embedding, year, aliases):
        cid = self.next_id
        self.next_id += 1
        
        if self.raw_store:
            vec = np.asarray(embedding, dtype='float32')
            if vec.shape[0] != self.raw_store.dim:
                raise ValueError(f"Embedding dimension ({vec.shape[0]}) doesn't match raw_store expected dimension ({self.raw_store.dim})")
            self.raw_store.put(cid, vec)
        
        meta = {
            'opinion_text': normalize_text(opinion_text),
            'canonical_label': opinion_text,
            'first_seen_year': int(year) if pd.notna(year) else None,
            'aliases': list(dict.fromkeys(aliases)),
            'alias_norm_set': {normalize_text(a) for a in aliases}
        }
        self._set_meta(cid, meta)
        
        self.pending_ids.append(cid)
        
        if len(self.pending_ids) >= 500:
            self._flush_pending()
        
        return cid

    def _flush_pending(self):
        if not self.pending_ids:
            return
        
        if self.raw_store:
            vecs = []
            valid_ids = []
            for cid in self.pending_ids:
                vec = self.raw_store.get(cid)
                if vec is not None:
                    vecs.append(vec)
                    valid_ids.append(cid)
            if not vecs:
                self.pending_ids.clear()
                return
            vecs = np.stack(vecs, axis=0).astype('float32')
            ids = np.array(valid_ids, dtype=np.int64)
        else:
            self.pending_ids.clear()
            return
        
        if self.compressor and not self.compressor.trained:
            total_count = self.raw_store.count()
            if total_count >= ENABLE_PCA_AT_OPINIONS:
                pending_before_rebuild = self.pending_ids.copy()
                self._train_compressor_and_rebuild()
                self.pending_ids.clear()
                self._flush_meta()
                return
        
        if self.compressor and self.compressor.trained:
            vecs = self.compressor.compress(vecs)
        
        if self.index.d != vecs.shape[1]:
            pending_ids_saved = ids.copy()
            if self.compressor and self.compressor.trained:
                raw_vecs = []
                raw_ids = []
                for cid in pending_ids_saved:
                    raw_vec = self.raw_store.get(cid)
                    if raw_vec is not None:
                        raw_vecs.append(raw_vec)
                        raw_ids.append(cid)
                if raw_vecs:
                    raw_vecs_array = np.stack(raw_vecs, axis=0).astype('float32')
                    raw_ids_array = np.array(raw_ids, dtype=np.int64)
                    self._rebuild_index_with_compression()
                    if self.compressor and self.compressor.trained:
                        compressed_vecs = self.compressor.compress(raw_vecs_array)
                        if self.index.d == compressed_vecs.shape[1]:
                            self.index.add_with_ids(compressed_vecs, raw_ids_array)
                            print(f"  重建后重新插入 {len(raw_ids_array)} 个向量")
                        else:
                            pass
                    else:
                        pass
                else:
                    pass
            else:
                pass
            self.pending_ids.clear()
            self._flush_meta()
            return
        
        self.index.add_with_ids(vecs, ids)
        
        self.pending_ids.clear()
        self._flush_meta()
    
    def _train_compressor_and_rebuild(self):
        """训练PCA压缩器并重建索引"""
        if not self.raw_store or not self.compressor:
            return
        
        training_samples = []
        sample_count = 0
        for cid, vec in self.raw_store.iterate():
            training_samples.append(vec)
            sample_count += 1
            if sample_count >= PCA_TRAIN_SAMPLES:
                break
        
        if len(training_samples) < 1000:
            return
        
        training_array = np.stack(training_samples, axis=0).astype('float32')
        self.compressor.train(training_array)
        self.compressed_dim = self.compressor.compressed_dim
        
        compressor_path = CHECKPOINT_DIR / "vector_compressor.json"
        self.compressor.save(str(compressor_path))
        self._rebuild_index_with_compression()
    
    def _rebuild_index_with_compression(self):
        """重建索引（优化：支持增量更新，避免全量重建）"""
        if not self.raw_store or not self.compressor or not self.compressor.trained:
            return
        
        print(f"使用压缩重建索引...")
        
        existing_ids = set()
        if self.index.ntotal > 0:
            if self.use_lmdb:
                with self.lmdb_env.begin() as txn:
                    cursor = txn.cursor()
                    for key, _ in cursor:
                        cid = int(key.decode())
                        existing_ids.add(cid)
            else:
                existing_ids = set(self.meta.keys())
        
        if self.index.ntotal == 0 or not existing_ids:
            if USE_HNSW:
                base = faiss.IndexHNSWFlat(self.compressed_dim, HNSW_M, faiss.METRIC_INNER_PRODUCT)
                base.hnsw.efSearch = HNSW_EF_SEARCH
                base.hnsw.efConstruction = HNSW_EF_CONSTRUCTION
            else:
                base = faiss.IndexFlatIP(self.compressed_dim)
            new_index = faiss.IndexIDMap(base)
        else:
            new_index = self.index
        
        batch_size = 1000
        batch_vecs = []
        batch_ids = []
        total_rebuilt = 0
        total_skipped = 0
        
        for cid, raw_vec in self.raw_store.iterate():
            if new_index.ntotal > 0 and cid in existing_ids:
                total_skipped += 1
                continue
            
            compressed_vec = self.compressor.compress(raw_vec)
            batch_vecs.append(compressed_vec)
            batch_ids.append(cid)
            
            if len(batch_vecs) >= batch_size:
                vecs_array = np.stack(batch_vecs, axis=0).astype('float32')
                ids_array = np.array(batch_ids, dtype=np.int64)
                new_index.add_with_ids(vecs_array, ids_array)
                total_rebuilt += len(batch_ids)
                batch_vecs.clear()
                batch_ids.clear()
                
                if total_rebuilt % 10000 == 0:
                    print(f"  已重建 {total_rebuilt} 个向量...")
        
        if batch_vecs:
            vecs_array = np.stack(batch_vecs, axis=0).astype('float32')
            ids_array = np.array(batch_ids, dtype=np.int64)
            new_index.add_with_ids(vecs_array, ids_array)
            total_rebuilt += len(batch_ids)
        
        self.index = new_index

    def search(self, embedding, threshold=None):
        self._flush_pending()
        
        if self.index.ntotal == 0:
            return None, None
        
        if self.compressor and self.compressor.trained:
            embedding = self.compressor.compress(embedding)
        
        k = min(FAISS_SEARCH_K, self.index.ntotal)
        D, I = self.index.search(np.array([embedding], dtype='float32'), k)
        
        for i in range(k):
            sim, cid = float(D[0][i]), int(I[0][i])
            if threshold is None or sim >= threshold:
                return cid, sim
        
        return None, None

    def batch_search(self, embeddings, thresholds=None):
        self._flush_pending()
        
        if self.index.ntotal == 0:
            return [(None, None)] * len(embeddings)
        
        if len(embeddings) == 0:
            return []
        
        embeddings = np.asarray(embeddings, dtype='float32')
        
        if self.compressor and self.compressor.trained:
            embeddings = self.compressor.compress(embeddings)
        
        k = min(FAISS_SEARCH_K, self.index.ntotal)
        D, I = self.index.search(embeddings, k)
        
        results = []
        for i in range(len(embeddings)):
            threshold = thresholds[i] if thresholds else None
            found = False
            
            for j in range(k):
                sim, cid = float(D[i][j]), int(I[i][j])
                if threshold is None or sim >= threshold:
                    results.append((cid, sim))
                    found = True
                    break
            
            if not found:
                results.append((None, None))
        
        return results

    def save(self, base_name: str):
        self._flush_pending()
        self._flush_meta()
        
        if TRAIN_PCA_IN_SAVE and self.compressor and not self.compressor.trained and self.raw_store:
            total_count = self.raw_store.count()
            if total_count >= ENABLE_PCA_AT_OPINIONS:
                self._train_compressor_and_rebuild()
        
        faiss_path = CHECKPOINT_DIR / f"{base_name}.faiss"
        faiss.write_index(self.index, str(faiss_path))
        
        if self.compressor and self.compressor.trained:
            compressor_path = CHECKPOINT_DIR / "vector_compressor.json"
            self.compressor.save(str(compressor_path))
        
        if not self.use_lmdb:
            meta_data = {
                'next_id': self.next_id,
                'meta': {str(cid): {k: v for k, v in rec.items() if k != 'alias_norm_set'} 
                        for cid, rec in self.meta.items()}
            }
            json_path = CHECKPOINT_DIR / f"{base_name}.json"
            json_path.write_text(json.dumps(meta_data, ensure_ascii=False), encoding='utf-8')
        else:
            meta_data = {'next_id': self.next_id}
            json_path = CHECKPOINT_DIR / f"{base_name}.json"
            json_path.write_text(json.dumps(meta_data, ensure_ascii=False), encoding='utf-8')

    @staticmethod
    def load(emb_dim=384, base_name="opinion_index"):
        faiss_path = CHECKPOINT_DIR / f"{base_name}.faiss"
        json_path = CHECKPOINT_DIR / f"{base_name}.json"
        
        if faiss_path.exists() and json_path.exists():
            obj = IncrementalOpinionIndex(emb_dim)
            
            compressor_path = CHECKPOINT_DIR / "vector_compressor.json"
            if compressor_path.exists():
                obj.compressor = VectorCompressor.load(str(compressor_path))
                if obj.compressor and obj.compressor.trained:
                    obj.compressed_dim = obj.compressor.compressed_dim
                    if obj.raw_store and obj.raw_store.dim != obj.compressor.original_dim:
                        obj.raw_store.close()
                        obj.raw_store = RawEmbeddingStore(RAW_EMBEDDING_PATH, obj.compressor.original_dim, RAW_EMBEDDING_MAP_SIZE)
            
            obj.index = faiss.read_index(str(faiss_path))
            
            if obj.compressor and obj.compressor.trained:
                if obj.index.d != obj.compressed_dim:
                    if obj.raw_store and obj.raw_store.count() > 0:
                        obj._rebuild_index_with_compression()
            
            data = json.loads(json_path.read_text(encoding='utf-8'))
            obj.next_id = data.get('next_id', 0)
            
            if not obj.use_lmdb:
                for cid_str, rec in data.get('meta', {}).items():
                    cid = int(cid_str)
                    obj.meta[cid] = {
                        **rec,
                        'alias_norm_set': {normalize_text(a) for a in rec.get('aliases', [])}
                    }
            
            return obj
        
        return IncrementalOpinionIndex(emb_dim)

class PaperProgressTracker:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_papers (
                paper_id TEXT PRIMARY KEY,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_id ON processed_papers(paper_id)")
        self.conn.commit()
        self._processed_set = self._load_processed_set()
        self._batch_buffer = []
        self._batch_size = 1000
    
    def _load_processed_set(self):
        cur = self.conn.execute("SELECT paper_id FROM processed_papers")
        return {row[0] for row in cur}
    
    def _get_paper_id(self, row):
        paper_id = getattr(row, 'paper_id', None) or ''
        if not paper_id or paper_id.strip() == '':
            title = getattr(row, 'title', '') or ''
            abstract = getattr(row, 'abstract', '') or ''
            year = getattr(row, 'year', None) or ''
            abstract_prefix = abstract[:100] if abstract else ''
            combined = f"{title}|{abstract_prefix}|{year}".strip()
            if xxhash:
                return str(xxhash.xxh64(combined.encode('utf-8')).intdigest())
            return str(hash(combined))
        return str(paper_id).strip()
    
    def is_processed(self, row):
        paper_id = self._get_paper_id(row)
        return paper_id in self._processed_set
    
    def mark_processed(self, row):
        paper_id = self._get_paper_id(row)
        if paper_id not in self._processed_set:
            self._processed_set.add(paper_id)
            self._batch_buffer.append(paper_id)
            if len(self._batch_buffer) >= self._batch_size:
                self._flush_batch()
    
    def _flush_batch(self):
        if not self._batch_buffer:
            return
        self.conn.executemany(
            "INSERT OR IGNORE INTO processed_papers(paper_id) VALUES(?)",
            [(pid,) for pid in self._batch_buffer]
        )
        self.conn.commit()
        self._batch_buffer.clear()
    
    def flush(self):
        self._flush_batch()
    
    def get_count(self):
        return len(self._processed_set)
    
    def close(self):
        self.flush()
        self.conn.close()

class MetaUpdateBuffer:
    def __init__(self):
        self.alias_buffer = {}
        self.year_buffer = {}
        self.label_buffer = {}
    
    def record_alias(self, cid, phrase):
        if cid not in self.alias_buffer:
            self.alias_buffer[cid] = set()
        self.alias_buffer[cid].add(phrase)
    
    def record_year(self, cid, year):
        if cid not in self.year_buffer:
            self.year_buffer[cid] = year
        else:
            self.year_buffer[cid] = min(self.year_buffer[cid], year)
    
    def record_label(self, cid, phrase, title):
        phrase_lower = phrase.lower().strip()
        title_lower = title.lower().strip()
        
        phrase_words = phrase_lower.split()
        if len(phrase_words) == 1:
            pattern = r'\b' + re.escape(phrase_lower) + r'\b'
            in_title = bool(re.search(pattern, title_lower))
        else:
            phrase_set = set(phrase_words)
            title_words = set(re.findall(r'\b\w+\b', title_lower))
            if len(phrase_set) >= 2:
                match_ratio = len(phrase_set & title_words) / len(phrase_set)
                in_title = match_ratio >= 0.8
            else:
                in_title = phrase_lower in title_lower
        
        phrase_len = len(phrase)
        
        if cid not in self.label_buffer:
            self.label_buffer[cid] = (phrase, phrase_len, in_title)
        else:
            _, old_len, old_in_title = self.label_buffer[cid]
            if in_title and (not old_in_title or phrase_len > old_len):
                self.label_buffer[cid] = (phrase, phrase_len, in_title)
            elif not old_in_title and phrase_len > old_len:
                self.label_buffer[cid] = (phrase, phrase_len, in_title)
    
    def flush_to_index(self, opinion_index):
        for cid, aliases in self.alias_buffer.items():
            meta = opinion_index._get_meta(cid)
            if meta is None:
                continue
            for phrase in aliases:
                norm_phrase = normalize_text(phrase)
                if norm_phrase not in meta['alias_norm_set']:
                    meta['aliases'].append(phrase)
                    meta['alias_norm_set'].add(norm_phrase)
            if len(meta['aliases']) > ALIAS_LIMIT:
                meta['aliases'] = meta['aliases'][:ALIAS_LIMIT]
            opinion_index._set_meta(cid, meta)
        
        for cid, year in self.year_buffer.items():
            meta = opinion_index._get_meta(cid)
            if meta is None:
                continue
            if meta['first_seen_year'] is None:
                meta['first_seen_year'] = year
            else:
                meta['first_seen_year'] = min(meta['first_seen_year'], year)
            opinion_index._set_meta(cid, meta)
        
        for cid, (phrase, phrase_len, in_title) in self.label_buffer.items():
            meta = opinion_index._get_meta(cid)
            if meta is None:
                continue
            if in_title and phrase_len > len(meta['canonical_label']):
                meta['canonical_label'] = phrase
            opinion_index._set_meta(cid, meta)
        
        self.clear()
    
    def clear(self):
        self.alias_buffer.clear()
        self.year_buffer.clear()
        self.label_buffer.clear()
    
    def size(self):
        return len(self.alias_buffer) + len(self.year_buffer) + len(self.label_buffer)

class YearlyDatabaseWriter:
    def __init__(self, db_path: str, buffer_size: int = DB_WRITE_BATCH_SIZE):
        self.db_path = db_path
        self.buffer_size = buffer_size
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA cache_size = -2000000")
        self.conn.execute("PRAGMA mmap_size = 30000000000")
        self.conn.execute("PRAGMA temp_store = MEMORY")
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS opinion_mentions (
                opinion_id INTEGER NOT NULL,
                opinion_text TEXT NOT NULL,
                canonical_label TEXT NOT NULL,
                first_seen_year INTEGER,
                alias TEXT NOT NULL,
                paper_id TEXT NOT NULL,
                year INTEGER,
                is_core_opinion INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (opinion_id, paper_id)
            )
        """)
        
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_opinion_mentions_year ON opinion_mentions(year)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_opinion_mentions_opinion_id ON opinion_mentions(opinion_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_opinion_mentions_paper_id ON opinion_mentions(paper_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_opinion_mentions_first_seen_year ON opinion_mentions(first_seen_year)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_opinion_mentions_is_core ON opinion_mentions(is_core_opinion)")
        
        self.conn.commit()
        
        self.buffer = []
        self.executemany_chunk_size = 20000
    
    def write_batch(self, df: pd.DataFrame):
        if df.empty:
            return
        
        records = []
        for _, row in df.iterrows():
            records.append((
                int(row['opinion_id']),
                str(row['opinion_text']),
                str(row['canonical_label']),
                int(row['first_seen_year']) if pd.notna(row['first_seen_year']) else None,
                str(row['alias']),
                str(row['paper_id']),
                int(row['year']) if pd.notna(row['year']) else None,
                int(row['is_core_opinion']) if 'is_core_opinion' in row and pd.notna(row['is_core_opinion']) else 0
            ))
        
        self.buffer.extend(records)
        
        if len(self.buffer) >= self.buffer_size:
            self._flush()
    
    def _flush(self):
        if not self.buffer:
            return
        
        sql = """
            INSERT INTO opinion_mentions 
            (opinion_id, opinion_text, canonical_label, first_seen_year, alias, paper_id, year, is_core_opinion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(opinion_id, paper_id) DO NOTHING
        """
        
        try:
            self.conn.execute('BEGIN TRANSACTION')
            for i in range(0, len(self.buffer), self.executemany_chunk_size):
                chunk = self.buffer[i:i + self.executemany_chunk_size]
                self.conn.executemany(sql, chunk)
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise
        finally:
            self.buffer.clear()
    
    def flush(self):
        self._flush()
    
    def close(self):
        self.flush()
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()
    
    def get_stats(self):
        if not hasattr(self, 'conn') or not self.conn:
            return {}
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM opinion_mentions")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT opinion_id) FROM opinion_mentions")
        unique_opinions = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT paper_id) FROM opinion_mentions")
        unique_papers = cursor.fetchone()[0]
        cursor.close()
        return {
            'total_mentions': total,
            'unique_opinions': unique_opinions,
            'unique_papers': unique_papers
        }

# =========================
# Event Ledger: 全局事件账本
# =========================

EVENT_LEDGER_DB = str(OUTPUT_DIR / "event_ledger.db")
EVENT_LEDGER_SIM_THRESHOLD = float(os.environ.get('EVENT_LEDGER_SIM_THRESHOLD', '0.85'))
EVENT_LEDGER_BATCH_SIZE = int(os.environ.get('EVENT_LEDGER_BATCH_SIZE', '100'))
BGE_M3_EMBEDDING_DIM = 1024

class EventLedger:
    """事件账本数据库管理类
    
    注意：所有公有方法只应从EventLedgerWorker线程调用，不要从主线程直接调用。
    主线程只应通过EventLedgerWorker.add_task()接口与账本交互。
    """
    
    def __init__(self, db_path: str = EVENT_LEDGER_DB):
        """初始化事件账本数据库
        
        Args:
            db_path: SQLite数据库路径
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA cache_size = -2000000")
        self.conn.execute("PRAGMA mmap_size = 30000000000")
        self.conn.execute("PRAGMA temp_store = MEMORY")
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_text TEXT NOT NULL,
                first_year INTEGER NOT NULL,
                total_count INTEGER NOT NULL DEFAULT 1,
                yearly_stats TEXT NOT NULL,
                embedding_vec BLOB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_event (
                paper_id TEXT NOT NULL,
                event_id INTEGER NOT NULL,
                PRIMARY KEY (paper_id, event_id)
            )
        """)
        
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_event_paper ON paper_event(paper_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_event_event ON paper_event(event_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_events_first_year ON events(first_year)")
        
        self.conn.commit()
    
    def get_event(self, event_id: int) -> Optional[Dict]:
        """获取事件信息
        
        Args:
            event_id: 事件ID
            
        Returns:
            事件字典，包含所有字段；如果不存在返回None
        """
        cursor = self.conn.execute(
            "SELECT event_id, canonical_text, first_year, total_count, yearly_stats, embedding_vec FROM events WHERE event_id = ?",
            (event_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        
        try:
            yearly_stats = json.loads(row[4])
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(f"Invalid yearly_stats JSON for event {row[0]}: {e}")
        
        return {
            'event_id': row[0],
            'canonical_text': row[1],
            'first_year': row[2],
            'total_count': row[3],
            'yearly_stats': yearly_stats,
            'embedding_vec': np.frombuffer(row[5], dtype=np.float32)
        }
    
    def get_all_events(self) -> List[Dict]:
        """获取所有事件（用于初始化FAISS索引）
        
        Returns:
            事件列表，每个事件包含event_id和embedding_vec
        """
        cursor = self.conn.execute(
            "SELECT event_id, embedding_vec FROM events"
        )
        events = []
        for row in cursor:
            events.append({
                'event_id': row[0],
                'embedding_vec': np.frombuffer(row[1], dtype=np.float32)
            })
        return events
    
    def create_event(self, canonical_text: str, year: int, embedding_vec: np.ndarray) -> int:
        """创建新事件
        
        Args:
            canonical_text: 规范化文本
            year: 首次出现年份
            embedding_vec: 归一化后的embedding向量（float32）
            
        Returns:
            新创建的事件ID
        """
        try:
            yearly_stats = json.dumps({str(year): 1})
        except (TypeError, ValueError) as e:
            raise ValueError(f"Failed to serialize yearly_stats: {e}")
        
        embedding_blob = embedding_vec.astype(np.float32).tobytes()
        
        cursor = self.conn.execute(
            """INSERT INTO events (canonical_text, first_year, total_count, yearly_stats, embedding_vec)
               VALUES (?, ?, 1, ?, ?)""",
            (canonical_text, year, yearly_stats, embedding_blob)
        )
        self.conn.commit()
        return cursor.lastrowid
    
    def update_event(self, event_id: int, year: int):
        """更新事件统计信息
        
        Args:
            event_id: 事件ID
            year: 出现年份
            
        Raises:
            ValueError: 如果事件不存在
        """
        cursor = self.conn.execute(
            "SELECT yearly_stats, total_count, first_year FROM events WHERE event_id = ?",
            (event_id,)
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"Event {event_id} not found")
        
        try:
            yearly_stats = json.loads(row[0])
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(f"Invalid yearly_stats JSON for event {event_id}: {e}")
        
        total_count = row[1] + 1
        first_year = min(row[2], year)
        
        yearly_stats[str(year)] = yearly_stats.get(str(year), 0) + 1
        
        try:
            yearly_stats_json = json.dumps(yearly_stats)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Failed to serialize yearly_stats for update: {e}")
        
        self.conn.execute(
            """UPDATE events 
               SET total_count = ?, yearly_stats = ?, first_year = ?, updated_at = CURRENT_TIMESTAMP
               WHERE event_id = ?""",
            (total_count, yearly_stats_json, first_year, event_id)
        )
        self.conn.commit()
    
    def link_paper_event(self, paper_id: str, event_id: int):
        """关联论文和事件
        
        Args:
            paper_id: 论文ID
            event_id: 事件ID
        """
        self.conn.execute(
            "INSERT OR IGNORE INTO paper_event (paper_id, event_id) VALUES (?, ?)",
            (paper_id, event_id)
        )
        self.conn.commit()
    
    def close(self):
        """关闭数据库连接"""
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()


class EventLedgerExperimentalUpdater:
    """事件账本实验性更新器
    
    负责：
    - 管理FAISS索引（仅在Worker线程中操作）
    - 向量搜索和相似度判断
    - 事件更新/新建逻辑
    
    注意：所有方法只应从EventLedgerWorker线程调用。
    """
    
    def __init__(self, event_ledger: EventLedger, sim_threshold: float = EVENT_LEDGER_SIM_THRESHOLD):
        """初始化更新器
        
        Args:
            event_ledger: EventLedger实例
            sim_threshold: 相似度阈值（默认0.85）
        """
        self.event_ledger = event_ledger
        self.sim_threshold = sim_threshold
        
        base_index = faiss.IndexFlatIP(BGE_M3_EMBEDDING_DIM)
        self.index = faiss.IndexIDMap(base_index)
        self.event_id_to_index = {}  # event_id -> FAISS索引中的ID（用于更新）
        self.index_to_event_id = {}  # FAISS索引ID -> event_id
        
        self._load_existing_events()
    
    def _load_existing_events(self):
        """从数据库加载现有事件到FAISS索引"""
        events = self.event_ledger.get_all_events()
        if not events:
            return
        
        total_events = len(events)
        if total_events > 0:
            print(f"[EventLedger] 开始加载 {total_events} 个现有事件到FAISS索引...")
        
        vectors = []
        faiss_ids = []
        skipped_count = 0
        for event in events:
            vec = event['embedding_vec']
            event_id = event['event_id']
            
            try:
                vec_normalized = self._normalize_vec(vec)
                vectors.append(vec_normalized)
                faiss_ids.append(event_id)
            except (ValueError, Exception) as e:
                skipped_count += 1
                print(f"[EventLedger] 警告: 跳过无效向量 (event_id={event_id}): {e}")
                continue
        
        if vectors:
            if len(vectors) != len(faiss_ids):
                print(f"[EventLedger] 错误: 向量数量({len(vectors)})与ID数量({len(faiss_ids)})不匹配")
                return
            
            try:
                vectors_array = np.stack(vectors, axis=0).astype(np.float32)
            except ValueError as e:
                print(f"[EventLedger] 错误: 无法堆叠向量（可能维度不一致）: {e}")
                print(f"  提示: 检查数据库中的embedding_vec维度是否一致")
                raise
            
            ids_array = np.array(faiss_ids, dtype=np.int64)
            
            try:
                self.index.add_with_ids(vectors_array, ids_array)
                for event_id in faiss_ids:
                    self.event_id_to_index[event_id] = event_id
                    self.index_to_event_id[event_id] = event_id
                if skipped_count > 0:
                    print(f"[EventLedger] 已加载 {len(vectors)} 个现有事件到FAISS索引（跳过 {skipped_count} 个无效向量）")
                else:
                    print(f"[EventLedger] 已加载 {len(vectors)} 个现有事件到FAISS索引")
            except Exception as e:
                print(f"[EventLedger] 错误: 加载事件到FAISS索引失败: {e}")
                raise
    
    def _normalize_vec(self, vec: np.ndarray) -> np.ndarray:
        """L2归一化向量（FAISS IndexFlatIP要求）
        
        Args:
            vec: 输入向量（应该是1D数组）
            
        Returns:
            归一化后的向量
            
        Raises:
            ValueError: 如果向量维度不匹配
        """
        vec = np.asarray(vec, dtype=np.float32)
        if vec.ndim != 1:
            raise ValueError(f"Expected 1D array, got {vec.ndim}D array")
        if vec.shape[0] != BGE_M3_EMBEDDING_DIM:
            raise ValueError(f"Expected vector dimension {BGE_M3_EMBEDDING_DIM}, got {vec.shape[0]}")
        
        norm = np.linalg.norm(vec)
        if norm < 1e-12:
            return vec
        return vec / norm
    
    def search_similar_event(self, embedding_vec: np.ndarray) -> Optional[Tuple[int, float]]:
        """搜索相似事件
        
        Args:
            embedding_vec: 归一化后的embedding向量（应该已经归一化，但会再次归一化以确保安全）
            
        Returns:
            (event_id, similarity) 如果找到相似事件，否则返回None
        """
        if self.index.ntotal == 0:
            return None
        
        vec_normalized = self._normalize_vec(embedding_vec)
        vec_array = np.array([vec_normalized], dtype=np.float32)
        
        k = min(1, self.index.ntotal)
        if k <= 0:
            return None
        
        try:
            D, I = self.index.search(vec_array, k)
            
            if D.shape[0] == 0 or I.shape[0] == 0:
                return None
            
            if I[0][0] >= 0:
                similarity = float(D[0][0])
                faiss_id = int(I[0][0])
                event_id = self.index_to_event_id.get(faiss_id)
                
                if event_id is None:
                    print(f"[EventLedger] 警告: FAISS索引ID {faiss_id} 不在映射字典中，可能索引与映射不同步")
                    return None
                
                if similarity >= self.sim_threshold:
                    return (event_id, similarity)
        except (IndexError, ValueError, Exception) as e:
            print(f"[EventLedger] 警告: FAISS搜索失败: {e}")
            return None
        
        return None
    
    def _clean_canonical_text(self, text: str) -> str:
        """轻度清洗文本，生成canonical_text
        
        去除：
        - 前后空格
        - 常见的section标签（AIM:, METHODS:, RESULTS:, CONCLUSION:等）
        
        Args:
            text: 原始句子文本
            
        Returns:
            清洗后的规范化文本
        """
        if not text or not isinstance(text, str):
            return ""
        
        text = text.strip()
        if not text:
            return ""
        
        section_prefixes = [
            'AIM:', 'OBJECTIVE:', 'GOAL:', 'PURPOSE:',
            'METHODS:', 'METHOD:', 'METHODOLOGY:',
            'RESULTS:', 'FINDINGS:', 'RESULT:',
            'CONCLUSION:', 'CONCLUSIONS:', 'SUMMARY:',
            'BACKGROUND:', 'INTRODUCTION:',
            'DISCUSSION:', 'IMPLICATIONS:'
        ]
        
        text_upper = text.upper()
        for prefix in section_prefixes:
            prefix_upper = prefix.upper()
            if text_upper.startswith(prefix_upper):
                prefix_len = len(prefix)
                text = text[prefix_len:].strip()
                break
        
        return text.strip()
    
    def process_event(self, paper_id: str, year: int, srl_event, embedding_vec: np.ndarray) -> int:
        """处理单个事件
        
        Args:
            paper_id: 论文ID
            year: 年份
            srl_event: SRLEventUnit对象
            embedding_vec: 已归一化的embedding向量（由extract方法计算）
            
        Returns:
            事件ID（可能是新建的，也可能是已存在的）
            
        Raises:
            ValueError: 如果srl_event无效或canonical_text为空
        """
        if not hasattr(srl_event, 'sentence_text') or not srl_event.sentence_text:
            raise ValueError("srl_event must have a non-empty sentence_text")
        
        if not paper_id or not isinstance(paper_id, str):
            raise ValueError("paper_id must be a non-empty string")
        
        if not isinstance(year, int) or year < 1900 or year > 2100:
            raise ValueError(f"year must be an integer between 1900 and 2100, got: {year}")
        
        if embedding_vec is None:
            raise ValueError("embedding_vec cannot be None")
        
        canonical_text = self._clean_canonical_text(srl_event.sentence_text)
        if not canonical_text:
            raise ValueError("canonical_text cannot be empty after cleaning")
        
        vec_normalized = self._normalize_vec(embedding_vec)
        
        result = self.search_similar_event(vec_normalized)
        
        if result is not None:
            event_id, similarity = result
            try:
                self.event_ledger.update_event(event_id, year)
            except ValueError as e:
                print(f"[EventLedger] 警告: 事件不存在 (event_id={event_id}): {e}")
                return event_id
            except Exception as e:
                print(f"[EventLedger] 警告: 更新事件失败 (event_id={event_id}): {e}")
                return event_id
            
            # 只有在update_event成功后才关联论文和事件
            try:
                self.event_ledger.link_paper_event(paper_id, event_id)
            except Exception as e:
                print(f"[EventLedger] 警告: 关联论文事件失败 (paper_id={paper_id}, event_id={event_id}): {e}")
            
            return event_id
        else:
            try:
                event_id = self.event_ledger.create_event(canonical_text, year, vec_normalized)
                
                try:
                    self.index.add_with_ids(
                        np.array([vec_normalized], dtype=np.float32),
                        np.array([event_id], dtype=np.int64)
                    )
                    self.event_id_to_index[event_id] = event_id
                    self.index_to_event_id[event_id] = event_id
                except Exception as idx_error:
                    print(f"[EventLedger] 警告: FAISS索引更新失败，但事件已创建 (event_id={event_id}): {idx_error}")
                    print(f"  提示: 下次启动时会从数据库重新加载此事件到索引")
                
                try:
                    self.event_ledger.link_paper_event(paper_id, event_id)
                except Exception as e:
                    print(f"[EventLedger] 警告: 关联论文事件失败 (paper_id={paper_id}, event_id={event_id}): {e}")
                return event_id
            except Exception as e:
                print(f"[EventLedger] 错误: 创建事件失败: {e}")
                raise


class EventLedgerWorker(threading.Thread):
    """事件账本后台工作线程
    
    从队列获取任务，批量处理并更新数据库。
    """
    
    def __init__(self, updater: EventLedgerExperimentalUpdater, batch_size: int = EVENT_LEDGER_BATCH_SIZE):
        """初始化工作线程
        
        Args:
            updater: EventLedgerExperimentalUpdater实例
            batch_size: 批量处理大小
        """
        super().__init__(daemon=True)
        self.updater = updater
        self.batch_size = batch_size
        self.task_queue = queue.Queue()
        self.shutdown_flag = threading.Event()
        self.pending_tasks = []
    
    def add_task(self, paper_id: str, year: int, srl_event, embedding_vec: np.ndarray):
        """添加任务到队列
        
        Args:
            paper_id: 论文ID
            year: 年份
            srl_event: SRLEventUnit对象
            embedding_vec: 已归一化的embedding向量
        """
        self.task_queue.put((paper_id, year, srl_event, embedding_vec))
    
    def run(self):
        """工作线程主循环"""
        while not self.shutdown_flag.is_set():
            try:
                task = self.task_queue.get(timeout=1.0)
                if task is None:
                    break
                self.pending_tasks.append(task)
                
                if len(self.pending_tasks) >= self.batch_size:
                    self._process_batch()
            except queue.Empty:
                if self.pending_tasks:
                    self._process_batch()
                continue
        
        self._process_batch()
    
    def _process_batch(self):
        """处理批量任务"""
        if not self.pending_tasks:
            return
        
        batch = self.pending_tasks[:]
        self.pending_tasks.clear()
        
        success_count = 0
        error_count = 0
        
        for paper_id, year, srl_event, embedding_vec in batch:
            try:
                self.updater.process_event(paper_id, year, srl_event, embedding_vec)
                success_count += 1
            except ValueError as e:
                error_count += 1
                print(f"[EventLedgerWorker] 参数错误: {e}")
            except Exception as e:
                error_count += 1
                print(f"[EventLedgerWorker] 处理事件时出错: {e}")
        
        if error_count > 0:
            if success_count == 0:
                print(f"[EventLedgerWorker] 警告: 批量处理 {len(batch)} 个事件全部失败")
            else:
                print(f"[EventLedgerWorker] 警告: 批量处理 {len(batch)} 个事件，成功 {success_count} 个，失败 {error_count} 个")
    
    def shutdown(self):
        """优雅关闭工作线程"""
        if not self.is_alive():
            # 即使线程未启动，也要关闭数据库连接
            if hasattr(self, 'updater') and hasattr(self.updater, 'event_ledger'):
                try:
                    self.updater.event_ledger.close()
                except Exception as e:
                    print(f"[EventLedgerWorker] 警告: 关闭数据库连接失败: {e}")
            return
        
        self.shutdown_flag.set()
        
        try:
            self.task_queue.put_nowait(None)
        except queue.Full:
            self.task_queue.put(None, block=True, timeout=5.0)
        
        self.join(timeout=10.0)
        if self.is_alive():
            print(f"[EventLedgerWorker] 警告: 线程未在超时时间内退出")
        else:
            # 线程已退出，关闭数据库连接
            if hasattr(self, 'updater') and hasattr(self.updater, 'event_ledger'):
                try:
                    self.updater.event_ledger.close()
                except Exception as e:
                    print(f"[EventLedgerWorker] 警告: 关闭数据库连接失败: {e}")


def select_top_opinions_from_embeddings(candidates, embeddings):
    """选择有效观点：通过聚类去重，保留所有有效观点"""
    valid_indices = [i for i, c in enumerate(candidates) if not is_generic_phrase(c)]
    if not valid_indices:
        return []
    
    valid_candidates = [candidates[i] for i in valid_indices]
    valid_embeddings = embeddings[valid_indices]
    n = len(valid_candidates)
    
    if n == 1:
        return [(valid_candidates[0], valid_embeddings[0])]

    if n < 100:
        return _cluster_exact(valid_candidates, valid_embeddings, n)
    
    return _cluster_approximate(valid_candidates, valid_embeddings, n)

def _cluster_exact(candidates, embeddings, n):
    """精确聚类方法（适用于小规模数据）"""
    sim_mat = embeddings @ embeddings.T
    visited = np.zeros(n, dtype=bool)
    clusters = []
    
    if n >= 10:
        nearest_similarities = []
        for i in range(n):
            row_sims = sim_mat[i]
            non_diag_sims = np.delete(row_sims, i)
            if len(non_diag_sims) > 0:
                max_sim = np.max(non_diag_sims)
                if max_sim > 0:
                    nearest_similarities.append(max_sim)
        
        if len(nearest_similarities) >= 5:
            adaptive_threshold = np.percentile(nearest_similarities, ADAPTIVE_THRESHOLD_PERCENTILE)
            cluster_threshold = max(ADAPTIVE_THRESHOLD_MIN, 
                                   min(ADAPTIVE_THRESHOLD_MAX, adaptive_threshold))
        else:
            cluster_threshold = ADAPTIVE_THRESHOLD_MIN
    else:
        cluster_threshold = ADAPTIVE_THRESHOLD_MIN
    
    for i in range(n):
        if visited[i]:
            continue
        members = np.where(sim_mat[i] > cluster_threshold)[0]
        visited[members] = True
        clusters.append(members.tolist())

    return _select_representatives(candidates, embeddings, clusters)

def _cluster_approximate(candidates, embeddings, n):
    """近似聚类方法（使用FAISS，适用于大规模数据）"""
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normalized_embeddings = embeddings / (norms + 1e-12)
    
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(normalized_embeddings.astype('float32'))
    
    parent = list(range(n))
    
    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    
    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py
    
    k = min(50, n - 1)
    if k > 0:
        similarities, indices = index.search(normalized_embeddings.astype('float32'), k + 1)
        
        if n >= 10:
            nearest_similarities = []
            for i in range(n):
                if len(indices[i]) > 1:
                    nearest_sim = similarities[i][1]
                    if nearest_sim > 0:
                        nearest_similarities.append(nearest_sim)
            
            if len(nearest_similarities) >= 5:
                adaptive_threshold = np.percentile(nearest_similarities, ADAPTIVE_THRESHOLD_PERCENTILE)
                cluster_threshold = max(ADAPTIVE_THRESHOLD_MIN, 
                                       min(ADAPTIVE_THRESHOLD_MAX, adaptive_threshold))
            else:
                cluster_threshold = ADAPTIVE_THRESHOLD_MIN
        else:
            cluster_threshold = ADAPTIVE_THRESHOLD_MIN
        
        for i in range(n):
            for j_idx, sim in zip(indices[i][1:], similarities[i][1:]):
                if sim >= cluster_threshold:
                    union(i, j_idx)
    
    cluster_dict = {}
    for i in range(n):
        root = find(i)
        if root not in cluster_dict:
            cluster_dict[root] = []
        cluster_dict[root].append(i)
    
    clusters = list(cluster_dict.values())
    return _select_representatives(candidates, embeddings, clusters)

def _select_representatives(candidates, embeddings, clusters):
    """选择聚类代表并计算中心性排序"""
    if not clusters:
        return []
    
    representatives, rep_embs = [], []
    for members in clusters:
        if not members:
            continue
        cemb = embeddings[members]
        centroid = cemb.mean(axis=0)
        centroid = centroid / (np.linalg.norm(centroid) + 1e-12)
        best_idx = members[np.argmax(cemb @ centroid)]
        representatives.append(candidates[best_idx])
        rep_embs.append(embeddings[best_idx])

    if len(representatives) == 0:
        return []
    if len(representatives) == 1:
        return list(zip(representatives, rep_embs))
    
    if len(representatives) > 100:
        sample_size = min(50, len(representatives))
        sample_indices = np.random.choice(len(representatives), sample_size, replace=False)
        sample_embs = np.stack([rep_embs[i] for i in sample_indices])
        rep_embs_stack = np.stack(rep_embs)
        
        R_sample = sample_embs @ sample_embs.T
        centrality_sample = R_sample.sum(axis=1) / (sample_size - 1)
        
        R_all = rep_embs_stack @ sample_embs.T
        centrality = R_all.mean(axis=1)
    else:
        rep_embs_stack = np.stack(rep_embs)
        R = rep_embs_stack @ rep_embs_stack.T
        centrality = (R.sum(axis=1) - 1.0) / (len(representatives) - 1)
    
    sorted_idx = np.argsort(-centrality)
    return [(representatives[i], rep_embs[i]) for i in sorted_idx]

def calculate_opinion_importance_score(phrase: str, structured_opinion: Optional[StructuredOpinion] = None) -> float:
    """计算观点重要性分数（用于非创新观点的选择）"""
    score = 0.0
    
    if structured_opinion and structured_opinion.predicate:
        predicate_lower = structured_opinion.predicate.lower()
        if any(verb in predicate_lower for verb in OPINION_VERBS_STRONG):
            score += 0.4
        elif any(verb in predicate_lower for verb in OPINION_VERBS_MEDIUM):
            score += 0.25
        elif any(verb in predicate_lower for verb in OPINION_VERBS_WEAK):
            score += 0.1
    
    phrase_len = len(phrase)
    if 15 <= phrase_len <= 80:
        score += 0.2
    elif 10 <= phrase_len < 15 or 80 < phrase_len <= 120:
        score += 0.1
    
    innovation_keywords = ['novel', 'first', 'pioneering', 'breakthrough', 
                          'groundbreaking', 'innovative', 'original', 'state-of-the-art']
    phrase_lower = phrase.lower()
    if any(keyword in phrase_lower for keyword in innovation_keywords):
        score += 0.2
    
    if any(c.isupper() or c.isdigit() for c in phrase):
        score += 0.1
    word_count = len(phrase.split())
    if word_count >= 3:
        score += 0.1
    
    return min(score, 1.0)

def save_progress(processed_papers: int):
    progress_file = CHECKPOINT_DIR / "progress.json"
    progress_file.write_text(json.dumps({"processed_papers": processed_papers}, ensure_ascii=False), encoding='utf-8')

def load_progress():
    progress_file = CHECKPOINT_DIR / "progress.json"
    if progress_file.exists():
        data = json.loads(progress_file.read_text(encoding='utf-8'))
        processed = data.get("processed_papers", 0)
        if processed > 0:
            return processed
    return 0

def clear_progress():
    progress_file = CHECKPOINT_DIR / "progress.json"
    if progress_file.exists():
        progress_file.unlink()

def _extract_polarity_from_meta(meta):
    """从元数据中提取极性"""
    if 'polarity' in meta:
        return meta['polarity']
    
    opinion_text = meta.get('opinion_text', '').lower()
    if any(word in opinion_text for word in ['does not', 'fails', 'worse', 'inferior', 'not better']):
        return "negative"
    elif any(word in opinion_text for word in ['outperforms', 'better', 'superior', 'improves', 'effective']):
        return "positive"
    return "neutral"

def _update_opposed_to_lmdb(opinion_index, cid, opposed_cid):
    """更新LMDB中的opposed_to字段"""
    with opinion_index.lmdb_env.begin(write=True) as txn:
        key = str(cid).encode()
        val = txn.get(key)
        if val:
            if msgpack:
                meta = msgpack.unpackb(val, raw=False)
            else:
                meta = json.loads(val.decode())
            
            if 'opposed_to' not in meta:
                meta['opposed_to'] = []
            if opposed_cid not in meta['opposed_to']:
                meta['opposed_to'].append(opposed_cid)
            
            if msgpack:
                new_val = msgpack.packb(meta, use_bin_type=True)
            else:
                new_val = json.dumps(meta, ensure_ascii=False).encode()
            txn.put(key, new_val)

def detect_opinion_conflicts(opinion_index, emb_model, cache, conflict_threshold=0.85):
    """检测语义冲突：识别同一对象上的对立语义（正负极性冲突）"""
    conflict_pairs = []
    
    opinion_objects = {}
    
    if opinion_index.use_lmdb:
        with opinion_index.lmdb_env.begin() as txn:
            cursor = txn.cursor()
            for key, val in cursor:
                cid = int(key.decode())
                if msgpack:
                    meta = msgpack.unpackb(val, raw=False)
                else:
                    meta = json.loads(val.decode())
                
                if meta and 'opinion_text' in meta:
                    opinion_text = meta.get('opinion_text', '')
                    words = opinion_text.split()
                    if len(words) >= 2:
                        candidate_obj = " ".join(words[:2])
                        obj_key = abstract_object_phrase(candidate_obj)
                    else:
                        obj_key = abstract_object_phrase(words[0] if words else str(cid))
                    
                    if obj_key not in opinion_objects:
                        opinion_objects[obj_key] = []
                    
                    if opinion_index.raw_store:
                        vec = opinion_index.raw_store.get(cid)
                        if vec is None:
                            vec = encode_with_cache([opinion_text], emb_model, cache)[0]
                    else:
                        vec = encode_with_cache([opinion_text], emb_model, cache)[0]
                    
                    opinion_objects[obj_key].append((cid, meta, vec))
    else:
        for cid, meta in opinion_index.meta.items():
            if meta and 'opinion_text' in meta:
                opinion_text = meta.get('opinion_text', '')
                words = opinion_text.split()
                if len(words) >= 2:
                    candidate_obj = " ".join(words[:2])
                    obj_key = abstract_object_phrase(candidate_obj)
                else:
                    obj_key = abstract_object_phrase(words[0] if words else str(cid))
                
                if obj_key not in opinion_objects:
                    opinion_objects[obj_key] = []
                
                vec = encode_with_cache([opinion_text], emb_model, cache)[0]
                opinion_objects[obj_key].append((cid, meta, vec))
    
    max_opinions_per_object = 100
    for obj_key, opinions in opinion_objects.items():
        if len(opinions) < 2:
            continue
        
        if len(opinions) > max_opinions_per_object:
            opinions = opinions[:max_opinions_per_object]
        
        for i in range(len(opinions)):
            for j in range(i + 1, len(opinions)):
                cid1, meta1, vec1 = opinions[i]
                cid2, meta2, vec2 = opinions[j]
                
                similarity = float(np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2) + 1e-12))
                
                polarity1 = _extract_polarity_from_meta(meta1)
                polarity2 = _extract_polarity_from_meta(meta2)
                
                if similarity >= conflict_threshold:
                    if (polarity1 == "positive" and polarity2 == "negative") or \
                       (polarity1 == "negative" and polarity2 == "positive"):
                        conflict_pairs.append((cid1, cid2))
                        
                        if opinion_index.use_lmdb:
                            _update_opposed_to_lmdb(opinion_index, cid1, cid2)
                            _update_opposed_to_lmdb(opinion_index, cid2, cid1)
                        else:
                            if cid1 in opinion_index.meta:
                                if 'opposed_to' not in opinion_index.meta[cid1]:
                                    opinion_index.meta[cid1]['opposed_to'] = []
                                if cid2 not in opinion_index.meta[cid1]['opposed_to']:
                                    opinion_index.meta[cid1]['opposed_to'].append(cid2)
                            if cid2 in opinion_index.meta:
                                if 'opposed_to' not in opinion_index.meta[cid2]:
                                    opinion_index.meta[cid2]['opposed_to'] = []
                                if cid1 not in opinion_index.meta[cid2]['opposed_to']:
                                    opinion_index.meta[cid2]['opposed_to'].append(cid1)
    
    return conflict_pairs

def save_filtered_papers_to_csv():
    """保存被过滤论文的详细信息到CSV文件，用于误过滤检查"""
    return

def save_successful_papers_sample():
    """保存成功进行语义识别的论文样本到CSV文件（用于质量检查）"""
    global _successful_paper_details
    
    if not _successful_paper_details:
        return
    
    total_successful = len(_successful_paper_details)
    sample_count = max(
        SUCCESS_SAMPLE_MIN,
        min(
            SUCCESS_SAMPLE_MAX,
            int(total_successful * SUCCESS_SAMPLE_RATE)
        )
    )
    
    import random
    if total_successful > sample_count:
        sampled = random.sample(_successful_paper_details, sample_count)
    else:
        sampled = _successful_paper_details
    
    all_successful = []
    for detail in sampled:
        paper_id, title, abstract, opinions_list, year = detail
        opinions_str = '; '.join(opinions_list) if opinions_list else ''
        all_successful.append({
            'paper_id': paper_id,
            'title': title,
            'abstract': abstract[:500] if abstract else '',
            'opinions': opinions_str[:1000] if opinions_str else '',
            'opinion_count': len(opinions_list),
            'year': year if year is not None else ''
        })
    
    if not all_successful:
        return
    
    successful_csv_path = OUTPUT_DIR / "successful_papers_sample.csv"
    df = pd.DataFrame(all_successful)
    file_exists = successful_csv_path.exists()
    
    if file_exists:
        df.to_csv(successful_csv_path, mode='a', header=False, index=False, encoding='utf-8-sig')
    else:
        df.to_csv(successful_csv_path, mode='w', header=True, index=False, encoding='utf-8-sig')
    
    _successful_paper_details.clear()

def check_filtered_papers(filtered_csv_path=None, stage=None, min_confidence=None, limit=50):
    """检查被过滤的论文，判断是否是误过滤"""
    if filtered_csv_path is None:
        filtered_csv_path = OUTPUT_DIR / "filtered_papers_details.csv"
    
    if not Path(filtered_csv_path).exists():
        return None
    
    df = pd.read_csv(filtered_csv_path, encoding='utf-8-sig')
    
    if stage:
        df = df[df['filter_stage'] == stage]
    
    if min_confidence is not None and 'max_confidence' in df.columns:
        df = df[df['max_confidence'] >= min_confidence]
    
    if len(df) > limit:
        df = df.head(limit)
    
    print(f"\n📊 被过滤论文检查结果（共 {len(df)} 条）:")
    print("="*80)
    
    for idx, row in df.iterrows():
        print(f"\n[{idx+1}] 论文ID: {row['paper_id']}")
        print(f"    标题: {row['title']}")
        print(f"    过滤阶段: {row['filter_stage']}")
        if pd.notna(row.get('max_confidence')):
            print(f"    最高置信度: {row['max_confidence']:.3f}")
        print(f"    过滤原因: {row['filter_reason']}")
        if pd.notna(row.get('abstract')):
            abstract_preview = row['abstract'][:200] + "..." if len(row['abstract']) > 200 else row['abstract']
            print(f"    摘要预览: {abstract_preview}")
        print("-"*80)
    
    return df

def process_microbatch(rows, nlp, emb_model, cache, opinion_index, meta_buffer):
    """微批次处理函数"""
    global _successful_paper_details
    
    if USE_HASH_DEDUP:
        reset_microbatch_hash_set()
    
    _successful_paper_details = []
    
    texts = []
    for r in rows:
        title = getattr(r, 'title', '') or ''
        abstract = getattr(r, 'abstract', '') or ''
        if title and abstract:
            combined = f"{title}\n\n[ABSTRACT]\n\n{abstract}".strip()
        else:
            combined = f"{title}{abstract}".strip()
        if len(combined) > 8192:
            combined = combined[:8192]
        texts.append(combined)
    
    docs = list(nlp.pipe(texts, batch_size=SPACY_BATCH_SIZE, n_process=SPACY_N_PROCESS))
    
    all_candidates = []
    all_structured_opinions = []
    
    for row, doc in tqdm(zip(rows, docs), total=len(rows), desc="处理论文", leave=False):
        paper_id = getattr(row, 'paper_id', None) or ''
        if not paper_id or paper_id.strip() == '':
            title = getattr(row, 'title', '') or ''
            abstract = getattr(row, 'abstract', '') or ''
            year = getattr(row, 'year', None) or ''
            abstract_prefix = abstract[:100] if abstract else ''
            combined = f"{title}|{abstract_prefix}|{year}".strip()
            if combined:
                if xxhash:
                    paper_id = str(xxhash.xxh64(combined.encode('utf-8')).intdigest())
                else:
                    paper_id = str(hash(combined))
        
        abstract = getattr(row, 'abstract', '') or ''
        title = getattr(row, 'title', '') or ''
        has_abstract = bool(abstract.strip())
        
        semantic_results = extract_opinions_from_document(
            doc, emb_model, cache, 
            has_abstract=has_abstract, 
            paper_id=paper_id,
            paper_title=title,
            paper_abstract=abstract,
            nlp_model=nlp
        )
        
        candidates = []
        structured_ops = []
        for normalized_text, structured_opinion in semantic_results:
            if normalized_text and normalized_text not in candidates:
                candidates.append(normalized_text)
                structured_ops.append((normalized_text, structured_opinion))
        
        if candidates:
            year = getattr(row, 'year', None)
            if year is not None and pd.notna(year):
                year = int(year)
            else:
                year = None
            _successful_paper_details.append((
                paper_id,
                title,
                abstract,
                candidates,
                year
            ))
        
        if len(candidates) > N_TOP_CANDIDATES:
            candidates = candidates[:N_TOP_CANDIDATES]
            structured_ops = structured_ops[:N_TOP_CANDIDATES]
        
        all_candidates.append(candidates)
        all_structured_opinions.append(structured_ops)
    
    flat_candidates = [c for cs in all_candidates for c in cs]
    if flat_candidates:
        all_embeddings = encode_with_cache(flat_candidates, emb_model, cache)
    else:
        all_embeddings = np.zeros((0, cache.dim), dtype='float32')
    
    if flat_candidates:
        print(f"  候选语义数: {len(flat_candidates)}, 已生成嵌入向量")
    
    paper_opinions = []
    offset = 0
    
    for row, candidates in zip(rows, all_candidates):
        n = len(candidates)
        if n == 0:
            paper_opinions.append([])
            continue
        
        emb_slice = all_embeddings[offset:offset+n]
        offset += n
        
        top_opinions = select_top_opinions_from_embeddings(candidates, emb_slice)
        paper_opinions.append(top_opinions)
    
    all_batch_vecs = []
    all_batch_thresholds = []
    
    for top_opinions in paper_opinions:
        if not top_opinions:
            continue
        for phrase, vec in top_opinions:
            all_batch_vecs.append(vec)
            all_batch_thresholds.append(adaptive_threshold(phrase))
    
    if all_batch_vecs:
        all_batch_vecs = np.stack(all_batch_vecs)
        print(f"  正在索引中搜索 {len(all_batch_vecs)} 个向量...")
        batch_search_results = opinion_index.batch_search(all_batch_vecs, all_batch_thresholds)
    else:
        batch_search_results = []
    
    mentions = []
    result_idx = 0
    
    for paper_idx, (row, top_opinions) in enumerate(zip(rows, paper_opinions)):
        if not top_opinions:
            continue
        
        paper_year = getattr(row, 'year', None)
        if paper_year is not None and pd.notna(paper_year):
            paper_year = int(paper_year)
        else:
            paper_year = None
        
        paper_used_opinion_ids = set()
        paper_phrase_vectors = {}
        paper_opinion_list = []
        
        structured_ops = all_structured_opinions[paper_idx] if paper_idx < len(all_structured_opinions) else []
        structured_ops_dict = {normalize_text_cached(op[0]): op[1] for op in structured_ops if op and len(op) >= 2}
        
        for phrase_idx, (phrase, vec) in enumerate(top_opinions):
            original_cid, sim = batch_search_results[result_idx]
            result_idx += 1
            
            should_merge = False
            merge_target_cid = None
            for existing_cid, existing_vec in paper_phrase_vectors.items():
                similarity = float(np.dot(vec, existing_vec) / (np.linalg.norm(vec) * np.linalg.norm(existing_vec) + 1e-12))
                if similarity > 0.95:
                    should_merge = True
                    merge_target_cid = existing_cid
                    break
            
            is_new_opinion = (original_cid is None and not should_merge)
            
            if should_merge and merge_target_cid is not None:
                cid = merge_target_cid
                meta_buffer.record_alias(cid, phrase)
            elif original_cid is None:
                cid = opinion_index.add(phrase, vec, paper_year, [phrase])
                paper_phrase_vectors[cid] = vec
            else:
                cid = original_cid
                meta_buffer.record_alias(cid, phrase)
                paper_phrase_vectors[cid] = vec
            
            if paper_year is not None:
                meta_buffer.record_year(cid, int(paper_year))
            
            title = getattr(row, 'title', '') or ''
            if title:
                meta_buffer.record_label(cid, phrase, title)
            
            if cid in paper_used_opinion_ids:
                continue
            paper_used_opinion_ids.add(cid)
            
            meta = opinion_index._get_meta(cid)
            if meta is None:
                continue
            
            first_seen_year = meta['first_seen_year']
            
            is_annual_innovation = False
            if paper_year is not None:
                if is_new_opinion:
                    is_annual_innovation = True
                elif first_seen_year is not None and first_seen_year == paper_year:
                    is_annual_innovation = True
            
            structured_opinion = structured_ops_dict.get(normalize_text_cached(phrase))
            
            opinion_info = {
                'opinion_id': cid,
                'opinion_text': meta['opinion_text'],
                'canonical_label': meta['canonical_label'],
                'first_seen_year': first_seen_year,
                'alias': phrase,
                'paper_id': getattr(row, 'paper_id', None) or '',
                'year': paper_year,
                'is_annual_innovation': is_annual_innovation,
                'structured_opinion': structured_opinion
            }
            paper_opinion_list.append(opinion_info)
        
        annual_innovation_opinions = [op for op in paper_opinion_list if op['is_annual_innovation']]
        
        if annual_innovation_opinions:
            for op in annual_innovation_opinions:
                op['is_core_opinion'] = True
            for op in paper_opinion_list:
                if not op['is_annual_innovation']:
                    op['is_core_opinion'] = False
        else:
            if paper_opinion_list:
                for op in paper_opinion_list:
                    op['importance_score'] = calculate_opinion_importance_score(
                        op['alias'], op.get('structured_opinion')
                    )
                best_opinion = max(paper_opinion_list, key=lambda x: x.get('importance_score', 0.0))
                for op in paper_opinion_list:
                    op['is_core_opinion'] = (op['opinion_id'] == best_opinion['opinion_id'])
            else:
                continue
        
        for op in paper_opinion_list:
            mentions.append({
                'opinion_id': op['opinion_id'],
                'opinion_text': op['opinion_text'],
                'canonical_label': op['canonical_label'],
                'first_seen_year': op['first_seen_year'],
                'alias': op['alias'],
                'paper_id': op['paper_id'],
                'year': op['year'],
                'is_core_opinion': op['is_core_opinion']
            })
    
    save_filtered_papers_to_csv()
    save_successful_papers_sample()
    
    total_mentions = len(mentions)
    successful_papers = len([c for c in all_candidates if c])
    print(f"  微批次处理完成: {successful_papers}/{len(rows)} 篇论文成功提取语义, 共 {total_mentions} 个语义识别结果")
    
    return mentions

def process_streaming_csv():
    """流式CSV处理主函数"""
    print("\n" + "="*60)
    print("⚠️  重要提示：语义识别与核心语义选择功能")
    print("="*60)
    print("本程序执行语义识别流程：候选原子抽取 → 筛选 → 抽象层构建")
    print("核心语义选择：根据语义的首次出现年份判断年度创新语义")
    print("为确保判断准确性，请确认输入CSV文件已按年份从早到晚排序。")
    print("="*60)
    user_input = input("请确认CSV文件已按年份排序（输入 'yes' 继续，其他任意键退出）: ").strip().lower()
    if user_input != 'yes':
        print("程序已退出。请先对CSV文件按年份排序后再运行。")
        return
    
    if not torch.cuda.is_available():
        raise RuntimeError(
            "GPU不可用！系统要求使用GPU运行。\n"
            "请检查：\n"
            "1. CUDA是否正确安装\n"
            "2. PyTorch是否支持CUDA\n"
            "3. GPU驱动是否正常"
        )
    
    device = "cuda"
    
    print("\n" + "="*60)
    print("📦 正在初始化模型和组件...")
    print("="*60)
    emb_model = SentenceTransformer(EMB_MODEL, device=device)
    emb_dim = emb_model.get_sentence_embedding_dimension()
    print(f"✓ 嵌入模型已加载 (模型: {EMB_MODEL}, 维度: {emb_dim})")
    
    cache = TwoLevelEmbCache(dim=emb_dim)
    print("✓ 缓存系统已初始化")
    
    opinion_index = IncrementalOpinionIndex.load(emb_dim, "opinion_index")
    index_size = opinion_index._get_meta_count()
    print(f"✓ 语义索引已加载 (现有语义数: {index_size:,})")
    
    meta_buffer = MetaUpdateBuffer()
    paper_tracker = PaperProgressTracker(PROGRESS_DB)
    
    processed_count = paper_tracker.get_count()
    print(f"✓ 进度跟踪器已加载 (已处理论文数: {processed_count:,})")
    
    print("正在加载spaCy模型...")
    nlp = spacy.load("en_core_web_sm", disable=["ner"])
    nlp.add_pipe("sentencizer")
    nlp.max_length = 2_000_000
    print("✓ spaCy模型已加载")
    
    mentions_writer = YearlyDatabaseWriter(MENTIONS_DB)
    print("✓ 数据库写入器已初始化")
    print("="*60)
    
    usecols = ['id', 'title', 'abstract', 'keyword', 'pub_year']
    dtype = {'id': 'string', 'title': 'string', 'abstract': 'string', 'keyword': 'string', 'pub_year': 'Int64'}
    
    reader = pd.read_csv(INPUT_CSV, usecols=usecols, dtype=dtype, chunksize=CHUNK_SIZE,
                        encoding_errors="ignore", on_bad_lines='skip', keep_default_na=False)
    
    microbatch_buffer = []
    microbatch_count = 0
    total_papers = processed_count
    skipped_papers = 0
    last_checkpoint = time.time()
    start_time = time.time()
    
    print(f"\n开始流式处理CSV文件 (块大小: {CHUNK_SIZE:,}, 微批次大小: {PAPERS_PER_MICROBATCH:,})...")
    
    for chunk_idx, chunk in enumerate(reader, start=1):
        chunk = chunk.rename(columns={
            'id': 'paper_id', 'title': 'title', 'abstract': 'abstract',
            'keyword': 'keywords', 'pub_year': 'year'
        })
        string_columns = ['paper_id', 'title', 'abstract', 'keywords']
        for col in string_columns:
            if col in chunk.columns:
                chunk[col] = chunk[col].fillna('')
        
        chunk_size_before = len(chunk)
        chunk = chunk[chunk['abstract'].str.strip().astype(bool)]
        skipped_papers += chunk_size_before - len(chunk)
        
        if chunk_size_before > len(chunk):
            print(f"  块 #{chunk_idx}: 过滤了 {chunk_size_before - len(chunk)} 篇无摘要论文")
        
        for row in chunk.itertuples(index=False):
            if paper_tracker.is_processed(row):
                skipped_papers += 1
                continue
            
            microbatch_buffer.append(row)
            
            if len(microbatch_buffer) >= PAPERS_PER_MICROBATCH:
                count = len(microbatch_buffer)
                microbatch_count += 1
                batch_start_time = time.time()
                
                print(f"\n[微批次 #{microbatch_count}] 处理 {count} 篇论文...")
                mentions = process_microbatch(microbatch_buffer, nlp, emb_model, cache, opinion_index, meta_buffer)
                
                for r in microbatch_buffer:
                    paper_tracker.mark_processed(r)
                
                mentions_count = len(mentions) if mentions else 0
                if mentions:
                    df = pd.DataFrame(mentions)
                    mentions_writer.write_batch(df)
                
                total_papers += count
                batch_time = time.time() - batch_start_time
                mentions_count = len(mentions) if mentions else 0
                print(f"[微批次 #{microbatch_count}] 完成: {mentions_count} 个语义识别结果, 耗时 {batch_time:.1f}秒, 累计处理 {total_papers:,} 篇论文")
                
                microbatch_buffer = []
                
                if (microbatch_count % CHECKPOINT_EVERY_MICROBATCH == 0 or 
                    time.time() - last_checkpoint > CHECKPOINT_EVERY_SECONDS):
                    checkpoint_start = time.time()
                    print(f"\n💾 保存检查点 (微批次 #{microbatch_count})...")
                    meta_buffer.flush_to_index(opinion_index)
                    opinion_index._flush_pending()
                    mentions_writer.flush()
                    opinion_index.save("opinion_index")
                    cache.flush()
                    paper_tracker.flush()
                    save_progress(total_papers)
                    checkpoint_time = time.time() - checkpoint_start
                    last_checkpoint = time.time()
                    print(f"✓ 检查点已保存，耗时 {checkpoint_time:.1f}秒，累计处理 {total_papers:,} 篇论文")
                    
                    if microbatch_count % (CHECKPOINT_EVERY_MICROBATCH * 2) == 0:
                        conflict_pairs = detect_opinion_conflicts(opinion_index, emb_model, cache)
                        if conflict_pairs:
                            opinion_index.save("opinion_index")
                    
                    elapsed_time = time.time() - start_time
    
    if microbatch_buffer:
        count = len(microbatch_buffer)
        microbatch_count += 1
        batch_start_time = time.time()
        
        print(f"\n[最后微批次] 处理 {count} 篇论文...")
        mentions = process_microbatch(microbatch_buffer, nlp, emb_model, cache, opinion_index, meta_buffer)
        
        for r in microbatch_buffer:
            paper_tracker.mark_processed(r)
        
        mentions_count = len(mentions) if mentions else 0
        if mentions:
            df = pd.DataFrame(mentions)
            mentions_writer.write_batch(df)
        
        total_papers += count
        batch_time = time.time() - batch_start_time
        mentions_count = len(mentions) if mentions else 0
        print(f"[最后微批次] 完成: {mentions_count} 个语义识别结果, 耗时 {batch_time:.1f}秒, 累计处理 {total_papers:,} 篇论文")
        
        if (microbatch_count % CHECKPOINT_EVERY_MICROBATCH == 0 or 
            time.time() - last_checkpoint > CHECKPOINT_EVERY_SECONDS):
            checkpoint_start = time.time()
            print(f"\n💾 保存检查点 (微批次 #{microbatch_count})...")
            meta_buffer.flush_to_index(opinion_index)
            opinion_index._flush_pending()
            mentions_writer.flush()
            opinion_index.save("opinion_index")
            cache.flush()
            paper_tracker.flush()
            save_progress(total_papers)
            checkpoint_time = time.time() - checkpoint_start
            last_checkpoint = time.time()
            print(f"✓ 检查点已保存，耗时 {checkpoint_time:.1f}秒，累计处理 {total_papers:,} 篇论文")
            
            if microbatch_count % (CHECKPOINT_EVERY_MICROBATCH * 2) == 0:
                conflict_pairs = detect_opinion_conflicts(opinion_index, emb_model, cache)
                if conflict_pairs:
                    opinion_index.save("opinion_index")
            
            elapsed_time = time.time() - start_time
    
    if opinion_index.use_lmdb:
        opinions_list = []
        with opinion_index.lmdb_env.begin() as txn:
            cursor = txn.cursor()
            for key, val in cursor:
                cid = int(key.decode())
                if msgpack:
                    meta = msgpack.unpackb(val, raw=False)
                else:
                    meta = json.loads(val.decode())
                if meta is None:
                    continue
                opinions_list.append({
                    'opinion_id': cid,
                    'opinion_text': meta.get('opinion_text', ''),
                    'canonical_label': meta.get('canonical_label', ''),
                    'first_seen_year': meta.get('first_seen_year'),
                    'aliases': "; ".join(meta.get('aliases', []))
                })
        opinions_df = pd.DataFrame(opinions_list)
    else:
        opinions_df = pd.DataFrame([
            {
                'opinion_id': cid,
                'opinion_text': meta.get('opinion_text', '') if meta else '',
                'canonical_label': meta.get('canonical_label', '') if meta else '',
                'first_seen_year': meta.get('first_seen_year') if meta else None,
                'aliases': "; ".join(meta.get('aliases', [])) if meta else ''
            }
            for cid, meta in opinion_index.meta.items()
            if meta is not None
        ])
    print(f"\n正在保存最终结果 (共 {len(opinions_df):,} 条语义记录)...")
    opinions_df.to_parquet(OUT_OPINIONS, index=False)
    print(f"✓ 语义识别结果已保存到: {OUT_OPINIONS}")
    
    print("正在刷新所有数据到磁盘...")
    meta_buffer.flush_to_index(opinion_index)
    opinion_index._flush_pending()
    opinion_index.save("opinion_index")
    cache.flush()
    paper_tracker.flush()
    print("✓ 所有数据已刷新到磁盘")
    
    print(f"\n{'='*80}")
    print("🔍 执行最终语义冲突检测...")
    print(f"{'='*80}")
    conflict_pairs = detect_opinion_conflicts(opinion_index, emb_model, cache)
    if conflict_pairs:
        print(f"  检测到 {len(conflict_pairs)} 对潜在冲突语义，已处理")
    else:
        print("  ✓ 未检测到语义冲突")
    if conflict_pairs:
        opinion_index.save("opinion_index")
    
    total_semantic_results = opinion_index._get_meta_count()
    
    if opinion_index.raw_store:
        opinion_index.raw_store.close()
    cache.close()
    mentions_writer.close()
    paper_tracker.close()
    
    if opinion_index.use_lmdb and opinion_index.lmdb_env:
        opinion_index.lmdb_env.close()
    
    print(f"\n{'='*80}")
    print("✅ 语义识别处理完成")
    print(f"{'='*80}")
    print(f"📊 处理统计:")
    print(f"  - 总论文数: {total_papers:,} 篇")
    print(f"  - 跳过论文数: {skipped_papers:,} 篇")
    print(f"  - 总语义识别结果数: {total_semantic_results:,} 个")
    elapsed_minutes = (time.time() - start_time) / 60
    print(f"  - 总耗时: {elapsed_minutes:.1f} 分钟")
    if elapsed_minutes > 0:
        print(f"  - 平均处理速度: {total_papers / elapsed_minutes:.1f} 篇/分钟")
    print(f"\n📁 输出文件:")
    print(f"  - 语义识别结果目录: {OUT_OPINIONS}")
    print(f"  - 语义识别结果提及数据库: {MENTIONS_DB}")
    print(f"{'='*80}")

class MetricsMonitor:
    """阶段2.6：完整监控与告警体系
    
    功能：
    - 原子抽取层指标（召回率、精确率、F1、路径覆盖率）
    - 对齐层指标（对齐准确率、对齐覆盖率、对齐耗时）
    - 聚类层指标（聚类纯度、ARI、簇数量）
    - 系统性能指标（延迟、吞吐）
    - SLO/SLI监控
    - 告警管理
    - 数据漂移检测
    """
    
    def __init__(self, enable_alerts: bool = True):
        """初始化指标监控器
        
        Args:
            enable_alerts: 是否启用告警系统（默认True）
        """
        self.metrics = {
            "atom_extraction": {
                "total_sentences": 0,
                "path_a_success": 0,
                "path_b_success": 0,
                "path_c_success": 0,
                "sentences_with_atoms": 0,  # 新增：成功提取原子的句子数
                "path_a_atoms": 0,
                "path_b_atoms": 0,
                "path_c_atoms": 0,
                "total_atoms": 0,
                "aligned_atoms": 0,
            },
            "alignment": {
                "total_maus": 0,
                "aligned_maus": 0,
                "merged_maus": 0,
                "alignment_time_ms": [],
            },
            "clustering": {
                "total_atoms": 0,
                "clusters": 0,
                "cluster_sizes": [],
            },
            "performance": {
                "total_documents": 0,
                "total_time_seconds": 0,
                "per_document_times": [],
            },
            "low_confidence": {
                "total_atoms": 0,
                "low_confidence_count": 0,
                "by_source_path": defaultdict(int),
            }
        }
        self.start_time = None
        self.document_start_time = None
        
        self.alert_manager = AlertManager() if enable_alerts else None
        self.enable_alerts = enable_alerts
        
        self.metrics_history: List[Dict] = []
        self.max_history_size = 100
    
    def start_document(self):
        """开始处理文档时调用"""
        self.document_start_time = time.time()
    
    def end_document(self):
        """结束处理文档时调用"""
        if self.document_start_time:
            elapsed = (time.time() - self.document_start_time) * 1000
            elapsed_seconds = (time.time() - self.document_start_time)
            self.metrics["performance"]["per_document_times"].append(elapsed)
            self.metrics["performance"]["total_documents"] += 1
            self.metrics["performance"]["total_time_seconds"] += elapsed_seconds
            self.document_start_time = None
    
    def record_atom_extraction(self, sentences_count: int, path_a_atoms: int, path_b_atoms: int, 
                              aligned_atoms: int, path_c_atoms: int = 0, sentences_with_atoms: int = None):
        """记录原子抽取指标
        
        Args:
            sentences_count: 句子数量
            path_a_atoms: 路径A抽取的原子数
            path_b_atoms: 路径B抽取的原子数
            path_c_atoms: 路径C抽取的原子数（可选）
            aligned_atoms: 对齐后的原子数
            sentences_with_atoms: 成功提取原子的句子数（可选，用于计算extraction_rate）
        """
        self.metrics["atom_extraction"]["total_sentences"] += sentences_count
        self.metrics["atom_extraction"]["path_a_atoms"] += path_a_atoms
        self.metrics["atom_extraction"]["path_b_atoms"] += path_b_atoms
        self.metrics["atom_extraction"]["path_c_atoms"] += path_c_atoms
        self.metrics["atom_extraction"]["total_atoms"] += path_a_atoms + path_b_atoms + path_c_atoms
        self.metrics["atom_extraction"]["aligned_atoms"] += aligned_atoms
        
        # 记录句子级别的成功（用于计算extraction_rate）
        if sentences_with_atoms is not None:
            self.metrics["atom_extraction"]["sentences_with_atoms"] = self.metrics["atom_extraction"].get("sentences_with_atoms", 0) + sentences_with_atoms
        else:
            # 如果没有提供，使用启发式：如果有任何原子，假设至少有一个句子成功
            if path_a_atoms + path_b_atoms + path_c_atoms > 0:
                self.metrics["atom_extraction"]["sentences_with_atoms"] = self.metrics["atom_extraction"].get("sentences_with_atoms", 0) + max(1, sentences_count)
        
        # 路径覆盖率（文档级别，保持向后兼容）
        if path_a_atoms > 0:
            self.metrics["atom_extraction"]["path_a_success"] += sentences_count
        if path_b_atoms > 0:
            self.metrics["atom_extraction"]["path_b_success"] += sentences_count
        if path_c_atoms > 0:
            self.metrics["atom_extraction"]["path_c_success"] += sentences_count
    
    def record_alignment(self, total_maus: int, aligned_maus: int, merged_count: int, 
                        alignment_time_ms: float):
        """记录对齐指标
        
        Args:
            total_maus: 对齐前MAU总数
            aligned_maus: 对齐后MAU数
            merged_count: 合并的MAU数
            alignment_time_ms: 对齐耗时（毫秒）
        """
        self.metrics["alignment"]["total_maus"] += total_maus
        self.metrics["alignment"]["aligned_maus"] += aligned_maus
        self.metrics["alignment"]["merged_maus"] += merged_count
        self.metrics["alignment"]["alignment_time_ms"].append(alignment_time_ms)
    
    def record_clustering(self, total_atoms: int, clusters: int, cluster_sizes: List[int]):
        """记录聚类指标
        
        Args:
            total_atoms: 聚类前原子数
            clusters: 生成的簇数
            cluster_sizes: 每个簇的大小
        """
        self.metrics["clustering"]["total_atoms"] += total_atoms
        self.metrics["clustering"]["clusters"] += clusters
        self.metrics["clustering"]["cluster_sizes"].extend(cluster_sizes)
    
    def record_low_confidence(self, total_atoms: int, low_confidence_count: int, 
                             by_source_path: Dict[str, int]):
        """记录低置信度指标
        
        Args:
            total_atoms: 总原子数
            low_confidence_count: 低置信度原子数
            by_source_path: 按来源路径统计的低置信度原子数
        """
        self.metrics["low_confidence"]["total_atoms"] += total_atoms
        self.metrics["low_confidence"]["low_confidence_count"] += low_confidence_count
        for path, count in by_source_path.items():
            self.metrics["low_confidence"]["by_source_path"][path] += count
    
    def get_atom_extraction_metrics(self) -> Dict:
        """获取原子抽取层指标
        
        Returns:
            Dict: 包含召回率、精确率、F1、路径覆盖率等指标
        """
        metrics = self.metrics["atom_extraction"]
        total_sentences = metrics["total_sentences"]
        
        path_a_coverage = (metrics["path_a_success"] / total_sentences * 100) if total_sentences > 0 else 0.0
        path_b_coverage = (metrics["path_b_success"] / total_sentences * 100) if total_sentences > 0 else 0.0
        path_c_coverage = (metrics.get("path_c_success", 0) / total_sentences * 100) if total_sentences > 0 else 0.0
        
        # 计算extraction_rate（句子级别）和usable_rate（原子级别）
        sentences_with_atoms = metrics.get("sentences_with_atoms", 0)
        extraction_rate = (sentences_with_atoms / total_sentences * 100) if total_sentences > 0 else 0.0
        usable_rate = (metrics["aligned_atoms"] / metrics["total_atoms"] * 100) if metrics["total_atoms"] > 0 else 0.0
        
        return {
            "total_sentences": total_sentences,
            "path_a_coverage": path_a_coverage,
            "path_b_coverage": path_b_coverage,
            "path_c_coverage": path_c_coverage,
            "path_a_atoms": metrics["path_a_atoms"],
            "path_b_atoms": metrics["path_b_atoms"],
            "path_c_atoms": metrics.get("path_c_atoms", 0),
            "total_atoms": metrics["total_atoms"],
            "aligned_atoms": metrics["aligned_atoms"],
            "extraction_rate": extraction_rate,  # 新增：句子级别的提取率
            "usable_rate": usable_rate,  # 新增：原子级别的有效率（原alignment_rate）
            "alignment_rate": usable_rate,  # 保持向后兼容，但实际是usable_rate
        }
    
    def get_alignment_metrics(self) -> Dict:
        """获取对齐层指标
        
        Returns:
            Dict: 包含对齐准确率、对齐覆盖率、对齐耗时等指标
        """
        metrics = self.metrics["alignment"]
        alignment_times = metrics["alignment_time_ms"]
        
        avg_alignment_time = np.mean(alignment_times) if alignment_times else 0.0
        p95_alignment_time = np.percentile(alignment_times, 95) if alignment_times else 0.0
        
        alignment_coverage = (metrics["aligned_maus"] / metrics["total_maus"] * 100) if metrics["total_maus"] > 0 else 0.0
        merge_rate = (metrics["merged_maus"] / metrics["total_maus"] * 100) if metrics["total_maus"] > 0 else 0.0
        
        return {
            "total_maus": metrics["total_maus"],
            "aligned_maus": metrics["aligned_maus"],
            "alignment_coverage": alignment_coverage,
            "merged_maus": metrics["merged_maus"],
            "merge_rate": merge_rate,
            "avg_alignment_time_ms": avg_alignment_time,
            "p95_alignment_time_ms": p95_alignment_time,
        }
    
    def get_clustering_metrics(self) -> Dict:
        """获取聚类层指标
        
        Returns:
            Dict: 包含聚类纯度、ARI、簇数量等指标
        """
        metrics = self.metrics["clustering"]
        cluster_sizes = metrics["cluster_sizes"]
        
        avg_cluster_size = np.mean(cluster_sizes) if cluster_sizes else 0.0
        total_docs = self.metrics["performance"]["total_documents"]
        clusters_per_doc = (metrics["clusters"] / total_docs) if total_docs > 0 else 0.0
        
        return {
            "total_atoms": metrics["total_atoms"],
            "total_clusters": metrics["clusters"],
            "avg_cluster_size": avg_cluster_size,
            "clusters_per_document": clusters_per_doc,
            "cluster_size_distribution": {
                "min": int(np.min(cluster_sizes)) if cluster_sizes else 0,
                "max": int(np.max(cluster_sizes)) if cluster_sizes else 0,
                "median": int(np.median(cluster_sizes)) if cluster_sizes else 0,
            }
        }
    
    def get_performance_metrics(self) -> Dict:
        """获取系统性能指标
        
        Returns:
            Dict: 包含延迟、吞吐等指标
        """
        metrics = self.metrics.get("performance", {})
        per_doc_times = metrics.get("per_document_times", [])
        
        total_time = metrics.get("total_time_seconds", 0.0)
        total_docs = metrics.get("total_documents", 0)
        
        avg_time_per_doc = np.mean(per_doc_times) if per_doc_times else 0.0
        p50_time = np.percentile(per_doc_times, 50) if per_doc_times else 0.0
        p95_time = np.percentile(per_doc_times, 95) if per_doc_times else 0.0
        p99_time = np.percentile(per_doc_times, 99) if per_doc_times else 0.0
        
        throughput = (total_docs / total_time * 60) if total_time > 0 else 0.0
        
        return {
            "total_documents": total_docs,
            "total_time_seconds": total_time,
            "avg_time_per_doc_ms": avg_time_per_doc,
            "p50_time_ms": p50_time,
            "p95_time_ms": p95_time,
            "p99_time_ms": p99_time,
            "throughput_docs_per_minute": throughput,
        }
    
    def update_total_time(self, elapsed_seconds: float):
        """更新总处理时间
        
        Args:
            elapsed_seconds: 经过的秒数
        """
        self.metrics["performance"]["total_time_seconds"] += elapsed_seconds
    
    def get_low_confidence_metrics(self) -> Dict:
        """获取低置信度指标
        
        Returns:
            Dict: 包含低置信度原子统计
        """
        metrics = self.metrics["low_confidence"]
        total = metrics["total_atoms"]
        low_conf = metrics["low_confidence_count"]
        
        return {
            "total_atoms": total,
            "low_confidence_count": low_conf,
            "low_confidence_rate": (low_conf / total * 100) if total > 0 else 0.0,
            "by_source_path": dict(metrics["by_source_path"]),
        }
    
    def get_all_metrics(self) -> Dict:
        """获取所有指标
        
        Returns:
            Dict: 包含所有层级的指标
        """
        return {
            "atom_extraction": self.get_atom_extraction_metrics(),
            "alignment": self.get_alignment_metrics(),
            "clustering": self.get_clustering_metrics(),
            "performance": self.get_performance_metrics(),
            "low_confidence": self.get_low_confidence_metrics(),
        }
    
    def check_and_alert(self):
        """检查指标并触发告警（阶段2.6）"""
        if not self.enable_alerts or not self.alert_manager:
            return
        
        current_metrics = self.get_all_metrics()
        
        alerts = self.alert_manager.check_slos(current_metrics)
        drift_alerts = self.alert_manager.detect_drift(current_metrics)
        
        if alerts or drift_alerts:
            print(f"\n{FMT_HLINE*OUTPUT_WIDTH}")
            alert_title = "⚠️  系统告警" if _SUPPORTS_UNICODE else "WARNING: 系统告警"
            print(f"{alert_title:^{OUTPUT_WIDTH}}")
            print(f"{FMT_HLINE*OUTPUT_WIDTH}")
            
            for alert in alerts:
                severity_icon = "🔴" if _SUPPORTS_UNICODE and alert["severity"] == "critical" else ("🟡" if _SUPPORTS_UNICODE else "[!]")
                severity_text = "严重" if alert["severity"] == "critical" else "警告"
                print(f"  {severity_icon} [{severity_text}] {alert['message']}")
            
            for drift_alert in drift_alerts:
                drift_icon = "📊" if _SUPPORTS_UNICODE else "[*]"
                print(f"  {drift_icon} [数据漂移] {drift_alert['message']}")
            
            print(f"{FMT_HLINE*OUTPUT_WIDTH}")
            
            if self.alert_manager.should_rollback(alerts):
                pass
        
        self.metrics_history.append(current_metrics)
        if len(self.metrics_history) > self.max_history_size:
            self.metrics_history.pop(0)
    
    def print_summary(self):
        """打印指标摘要"""
        self.check_and_alert()
        
        atom_metrics = self.get_atom_extraction_metrics()
        align_metrics = self.get_alignment_metrics()
        cluster_metrics = self.get_clustering_metrics()
        perf_metrics = self.get_performance_metrics()
        low_conf_metrics = self.get_low_confidence_metrics()
        
        summary_icon = "📊" if _SUPPORTS_UNICODE else "[*]"
        print(f"\n{FMT_HLINE*OUTPUT_WIDTH}")
        print(f"{summary_icon} 系统指标摘要".center(OUTPUT_WIDTH))
        print(f"{FMT_HLINE*OUTPUT_WIDTH}")
        
        print(f"\n{'原子抽取层':^{OUTPUT_WIDTH}}")
        print(f"  {'总句子数:':<20} {atom_metrics['total_sentences']:>10}")
        print(f"  {'路径A覆盖率:':<20} {atom_metrics['path_a_coverage']:>9.2f}%")
        print(f"  {'路径B覆盖率:':<20} {atom_metrics['path_b_coverage']:>9.2f}%")
        print(f"  {'路径C覆盖率:':<20} {atom_metrics.get('path_c_coverage', 0.0):>9.2f}%")
        print(f"  {'路径A原子数:':<20} {atom_metrics['path_a_atoms']:>10}")
        print(f"  {'路径B原子数:':<20} {atom_metrics['path_b_atoms']:>10}")
        print(f"  {'路径C原子数:':<20} {atom_metrics.get('path_c_atoms', 0):>10}")
        print(f"  {'总原子数:':<20} {atom_metrics['total_atoms']:>10}")
        print(f"  {'对齐后原子数:':<20} {atom_metrics['aligned_atoms']:>10}")
        print(f"  {'提取率(句子级):':<20} {atom_metrics.get('extraction_rate', 0):>9.2f}%")
        print(f"  {'有效率(原子级):':<20} {atom_metrics.get('usable_rate', atom_metrics.get('alignment_rate', 0)):>9.2f}%")
        print(f"  {'对齐率(兼容):':<20} {atom_metrics.get('alignment_rate', 0):>9.2f}%")
        
        print(f"\n{'对齐层':^{OUTPUT_WIDTH}}")
        print(f"  {'对齐覆盖率:':<20} {align_metrics['alignment_coverage']:>9.2f}%")
        print(f"  {'合并率:':<20} {align_metrics['merge_rate']:>9.2f}%")
        print(f"  {'平均对齐耗时:':<20} {align_metrics['avg_alignment_time_ms']:>9.2f} ms")
        print(f"  {'P95对齐耗时:':<20} {align_metrics['p95_alignment_time_ms']:>9.2f} ms")
        
        print(f"\n{'聚类层':^{OUTPUT_WIDTH}}")
        print(f"  {'总簇数:':<20} {cluster_metrics['total_clusters']:>10}")
        print(f"  {'平均簇大小:':<20} {cluster_metrics['avg_cluster_size']:>9.2f}")
        print(f"  {'每文档簇数:':<20} {cluster_metrics['clusters_per_document']:>9.2f}")
        
        print(f"\n{'性能指标':^{OUTPUT_WIDTH}}")
        print(f"  {'总文档数:':<20} {perf_metrics['total_documents']:>10}")
        print(f"  {'平均处理时间:':<20} {perf_metrics['avg_time_per_doc_ms']:>9.2f} ms/文档")
        print(f"  {'P50延迟:':<20} {perf_metrics['p50_time_ms']:>9.2f} ms")
        print(f"  {'P95延迟:':<20} {perf_metrics['p95_time_ms']:>9.2f} ms")
        print(f"  {'吞吐量:':<20} {perf_metrics['throughput_docs_per_minute']:>9.2f} 文档/分钟")
        
        # 始终显示低置信度部分，即使为0也显示（避免掩盖问题）
        print(f"\n{'低置信度处理':^{OUTPUT_WIDTH}}")
        if low_conf_metrics['low_confidence_rate'] > 0:
            print(f"  {'低置信度率:':<20} {low_conf_metrics['low_confidence_rate']:>9.2f}%")
            if low_conf_metrics['by_source_path']:
                print(f"  {'按来源路径统计:':<20} {str(low_conf_metrics['by_source_path']):>50}")
        else:
            print(f"  {'低置信度率:':<20} {'0.00':>9}% (无低置信度项)")
        
        print(f"\n{FMT_HLINE*OUTPUT_WIDTH}")

_global_metrics_monitor = MetricsMonitor(enable_alerts=True)


def create_miner_with_trained_models(
    confidence_model_path: Optional[str] = None,
    weight_model_path: Optional[str] = None,
    device: Optional[str] = None
) -> ResearchInsightMiner:
    """创建带有已训练模型的ResearchInsightMiner实例
    
    Args:
        confidence_model_path: 置信度模型路径（可选）
        weight_model_path: 权重模型路径（可选）
        device: 设备名称（可选，默认自动检测GPU）
        
    Returns:
        ResearchInsightMiner: 配置好的实例
    """
    miner = ResearchInsightMiner(device=device)
    
    if confidence_model_path and confidence_model_path.strip():
        meta_path = confidence_model_path + "_meta.json"
        if os.path.exists(meta_path):
            with open(meta_path, 'r') as f:
                meta = json.load(f)
                model_type = meta.get("model_type", "lightgbm")
        else:
            model_type = "lightgbm"
        
        confidence_model = LearnableConfidenceModel(model_type=model_type)
        confidence_model.load(confidence_model_path)
        miner.confidence_model = confidence_model
    
    if weight_model_path and weight_model_path.strip():
        weight_model = LearnableWeightModel()
        weight_model.load(weight_model_path)
        miner.weight_model = weight_model
        miner.agg_layer.weight_model = weight_model
    
    return miner


def batch_extract(
    texts: List[str],
    miner: Optional[ResearchInsightMiner] = None,
    threshold: float = 0.75,
    mode: str = "core",
    batch_size: int = 32,
    show_progress: bool = True
) -> List[List[Dict]]:
    """批量提取语义原子
    
    Args:
        texts: 文本列表
        miner: ResearchInsightMiner实例（可选，默认创建新实例）
        threshold: 筛选阈值
        mode: 模式（"core"或"full"）
        batch_size: 批次大小
        show_progress: 是否显示进度
        
    Returns:
        List[List[Dict]]: 每个文本的语义原子列表
    """
    if miner is None:
        miner = ResearchInsightMiner()
    
    if not texts:
        return []
    
    all_results = []
    total = len(texts)
    
    for i in range(0, total, batch_size):
        batch = texts[i:i+batch_size]
        batch_results = []
        
        for text in batch:
            results = miner.extract(text, threshold=threshold, mode=mode)
            batch_results.append(results)
        
        all_results.extend(batch_results)
        
        if show_progress and total > 0:
            processed = min(i + batch_size, total)
    
    return all_results


def train_confidence_model_from_extractions(
    miner: ResearchInsightMiner,
    texts: List[str],
    ground_truth: Optional[List[List[Dict]]] = None,
    model_type: str = "lightgbm",
    save_path: Optional[str] = None
) -> Optional[LearnableConfidenceModel]:
    """从提取结果训练置信度模型（简化版）
    
    注意：此函数需要MAU对象，但extract方法返回的是Dict格式。
    实际应用中，建议直接从extract方法的内部流程中获取MAU对象进行训练。
    此函数仅作为示例框架，需要根据实际需求进行完善。
    
    Args:
        miner: ResearchInsightMiner实例
        texts: 文本列表
        ground_truth: 真实标签（可选，如果提供则使用，否则使用高置信度原子作为正样本）
        model_type: 模型类型（"lightgbm"或"xgboost"）
        save_path: 保存路径（可选）
        
    Returns:
        LearnableConfidenceModel: 训练好的模型，如果无法构建训练数据则返回None
        
    Warning:
        此函数当前实现不完整，因为extract方法返回Dict而非MAU对象。
        建议使用以下方式训练：
        1. 修改extract方法，使其返回MAU对象列表（可选参数）
        2. 或者直接从内部流程中获取MAU对象
        3. 或者使用人工标注的MAU对象列表
    """
    
    return None


# 单次打印控制（避免重复打印）
_initialization_printed = False

if __name__ == "__main__":
    import warnings
    warnings.filterwarnings('ignore', category=DeprecationWarning)
    warnings.filterwarnings('ignore', category=UserWarning)
    
    print(f"\n{FMT_HLINE*OUTPUT_WIDTH}")
    title = "语义识别系统 - 使用示例"
    print(f"{title:^{OUTPUT_WIDTH}}")
    print(f"{FMT_HLINE*OUTPUT_WIDTH}")
    
    sample_text = """
    Antennae in the hawkmoth Manduca sexta (Lepidoptera, Sphingidae) mediate abdominal flexion in response to mechanical stimuli
    OFlying insects rely on the integration of feedback signals from multiple sensory modalities. Thus, in addition to the visual input, mechanosensory information from antennae is crucial for stable flight in the hawkmoth Manduca sexta. However, the nature of compensatory reflexes mediated by mechanoreceptors on the antennae is unknown. In this study we describe an abdominal flexion response mediated by the antennal mechanosensory input during mechanical body rotations. Such reflexive abdominal moti
    """
    
    init_msg = "初始化模型..."
    print(f"\n{init_msg:^{OUTPUT_WIDTH}}")
    miner = ResearchInsightMiner()
    check_icon = "✓" if _SUPPORTS_UNICODE else "[OK]"
    print(f"{check_icon} 模型初始化完成".center(OUTPUT_WIDTH))
    
    print(f"\n{FMT_SEP*OUTPUT_WIDTH}")
    print(f"{'[示例1] 基本提取':^{OUTPUT_WIDTH}}")
    print(f"{FMT_SEP*OUTPUT_WIDTH}")
    results = miner.extract(sample_text, threshold=0.75, mode="core")
    
    if results:
        for i, result in enumerate(results, 1):
            theme = result.get('theme', result.get('theme_text', result.get('atom_text', 'N/A')))
            confidence = result.get('confidence', 0.0)
            sentence = result.get('sentence', result.get('atom_text', result.get('theme_text', 'N/A')))
            sentence_preview = sentence[:80] + "..." if len(sentence) > 80 else sentence
            
            result_type = "主题" if 'theme_text' in result else "原子"
            print(f"\n  {'结果 ' + str(i) + ':':<20} ({result_type})")
            if 'theme_text' in result:
                print(f"    {'主题:':<12} {theme}")
            else:
                print(f"    {'内容:':<12} {theme[:80] + '...' if len(theme) > 80 else theme}")
            print(f"    {'置信度:':<12} {confidence:.3f}")
            print(f"    {'详情:':<12} {sentence_preview}")
    else:
        print(f"\n  {'未提取到语义结果':^{OUTPUT_WIDTH}}")
    
    print(f"\n{FMT_SEP*OUTPUT_WIDTH}")
    print(f"{'[示例2] 指标监控':^{OUTPUT_WIDTH}}")
    print(f"{FMT_SEP*OUTPUT_WIDTH}")
    _global_metrics_monitor.print_summary()
    
    print(f"\n{FMT_HLINE*OUTPUT_WIDTH}")
    complete_icon = "✓" if _SUPPORTS_UNICODE else "[OK]"
    print(f"{complete_icon} 示例完成".center(OUTPUT_WIDTH))
    print(f"{FMT_HLINE*OUTPUT_WIDTH}\n")
