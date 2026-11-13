import pandas as pd
import os
import pickle
import re
import numpy as np
import unicodedata
from collections import Counter, defaultdict
import heapq
import json
import hashlib
from datetime import datetime
import random
import torch
from transformers import AutoTokenizer, AutoModelForMaskedLM
from joblib import Parallel, delayed
import gc
import glob
from tqdm import tqdm
import pyarrow as pa
import pyarrow.parquet as pq
from pyarrow.parquet import ParquetWriter
from scipy.sparse import lil_matrix
import fasttext
import time


os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'
os.chdir(f'{os.path.dirname(os.path.abspath(__file__))}')

SYMBOL_HYPHEN = r"[\-‐‑–—]"
SYMBOL_SLASH = r"[/／⁄]"
SYMBOL_UNDERSCORE = r"[_]"
SYMBOL_MUL = r"[×x]"
SYMBOL_APOST = r"['']"
NUMBER = r"(?:[0-9]+(?:\.[0-9]*)?(?:e[+\-]?\d+)?|\d+)"
WORD = r"[A-Za-zΑ-ωβ-μΒ-ΜΒ-Ωα-ωΑ-Ω]+"
WORD_PART = fr"(?:{WORD}|[A-Za-z]+[0-9]|[0-9]+)"
CONNECTOR = fr"(?:{SYMBOL_HYPHEN}|{SYMBOL_SLASH}|{SYMBOL_UNDERSCORE})"
COMPOUND_PATTERN = (
    fr"(?:"
    fr"DOI:[^\s]+"
    fr"|arXiv:[^\s]+"
    fr"|PMID:[^\s]+"
    fr"|NCT[0-9]+"
    fr"|{WORD_PART}(?:{CONNECTOR}+{WORD_PART})+"
    fr"|{NUMBER}%"
    fr"|{NUMBER}[μµu]?[a-zA-Z%°℃μµ]*(?:/ml|/g|/L|/kg|mM|μM)?"
    fr"|{NUMBER}{SYMBOL_MUL}\d*"
    fr")"
)

FUNCTION_WORDS = [
    "of", "the", "and", "in", "for", "with", "on", "by", "from", "to", "a", "an", "or", "as", "at",
    "via", "per", "between", "among", "into", "over", "under", "but", "nor"
]

NOISE_PATTERNS = [
    r'^[Vv]ol\.?\s*\d+',
    r'^[Nn]o\.?\s*\d+',
    r'^pp?\.?\s*\d+',
    r'^\d{4}[年\-—]?',
    r'^\[\d+\]$',
    r'^\d+(\.\d+)?\-$',
    r'^\d{1,4}[:：]\d{1,4}$',
    r'^\d{3,6}$',
    r'^[A-Z]\d{2,}$',
]

config = {
    'csv_file_path': '2025外文论文全字段.csv',
    'chunk_size': 100000,
    'time_columns': ['出版年'],
    'info_columns': ['期刊名称', '标题', '关键词', 'KeywordsPlus', '摘要'],
    'unique_id_column': '入藏号',
    'temp_dir': r'temp\分词重构',
    'num_shards': 512,
    'shard_memory_threshold_mb': 500,
    'num_processes': 4,
    'language_filter': {
        'enabled': True,
        'mode': 'sentence'
    },
    'max_ngrams_per_n': 50000,
    'max_ctx_neighbors': 50,
    }
config['usecols'] = [config['unique_id_column']] + config['time_columns'] + config['info_columns']
config['dtype'] = {col: ('float' if col in config['time_columns'] else 'string') for col in config['usecols']}

def read_and_merge_info(config):
    reader = pd.read_csv(
        config['csv_file_path'],
        chunksize=config['chunk_size'],
        usecols=config['usecols'],
        encoding='utf-8',
        dtype=config['dtype'],
        low_memory=False
    )
    for chunk in reader:
        chunk['merged_info'] = chunk[config['info_columns']].apply(
            lambda row: ' '.join(row.dropna().astype(str)), axis=1
        )
        chunk.drop(columns=config['info_columns'], inplace=True)
        yield chunk

def clean_merged_info(df, text_col='merged_info'):
    arr = df[text_col].fillna("").astype(str).to_numpy(copy=False)

    block_patterns = [
        r'<math[\s\S]*?</math>',
        r'<div[\s\S]*?</div>',
        r'<table[\s\S]*?</table>',
        r'<figure[\s\S]*?</figure>',
        r'\\begin\{[a-zA-Z*]+\}[\s\S]*?\\end\{[a-zA-Z*]+\}',
    ]
    block_regex = re.compile('|'.join(block_patterns), re.I)

    INVIS_WS = '[\u200b\u200c\u200d\u200e\u200f\u2028\u2029\u2060\ufeff\u00a0\u1680\u180e\u2000-\u200a\u202f\u205f\u3000]'
    INVIS_WS_RE = re.compile(INVIS_WS)

    WS_PATTERN = re.compile(r'\s+')

    def clean_line(x):
        x = block_regex.sub(' ', x)
        x = INVIS_WS_RE.sub(' ', x)
        x = WS_PATTERN.sub(' ', x)
        return x.strip()
    cleaned_arr = np.vectorize(clean_line, otypes=[str])(arr)
    df = df.copy()
    df[text_col] = cleaned_arr
    return df

ft_model = None

def _init_fasttext_model():
    global ft_model
    if ft_model is None:
        ft_model = fasttext.load_model('resources/lid.176.bin')
    return ft_model

def filter_english_after_clean(df, text_col='merged_info', min_len=5):
    lf = config.get('language_filter', {})
    if not lf or not lf.get('enabled', False):
        return df

    mode = lf.get('mode', 'sentence')
    SENT_SPLIT = re.compile(r'(?<=[\.!?])\s+')
    PARA_SPLIT = re.compile(r'\n\s*\n')

    _init_fasttext_model()
    
    def keep_english_sentences(text, min_len=5):
        if not isinstance(text, str) or not text.strip():
            return ''
        sample = text[:500].replace('\n', ' ')
        label, prob = ft_model.predict(sample, k=1)
        if label[0] != '__label__en':
            return ''
        
        if mode == 'sentence':
            sents = SENT_SPLIT.split(text)
            kept = [s.strip() for s in sents if len(s.strip()) >= min_len]
            return ' '.join(kept)
        elif mode == 'paragraph':
            paras = PARA_SPLIT.split(text)
            kept = [p.strip().replace('\n', ' ') for p in paras if len(p.strip()) >= min_len]
            return ' '.join(kept)
        else:
            return text.strip() if len(text.strip()) >= min_len else ''
    
    arr = df[text_col].astype(str).to_numpy(copy=False)
    filtered = [keep_english_sentences(text) for text in tqdm(arr, desc="英文筛选")]

    df = df.copy()
    df[text_col] = filtered
    return df

def tokenize_and_normalize_fast(df, text_col='merged_info', doc_id_col=None):
    arr = df[text_col].fillna("").astype(str).to_numpy(copy=False)
    doc_ids = df.index.values if doc_id_col is None else df[doc_id_col].to_numpy(copy=False)

    COMPOUND = COMPOUND_PATTERN

    WORD_APOS = r"[A-Za-z]+(?:['’][A-Za-z]+)*"
    UNIT_SYM = r"[μµ%℃°]"
    PUNCT = r"[\.\,\:\;\?\!\(\)\[\]\{\}\"\“\”\‘\’\<\>\=]"
    SPLIT_PATTERN = re.compile(
        fr"{COMPOUND}"
        fr"|{WORD_APOS}"
        fr"|{NUMBER}"
        fr"|{UNIT_SYM}"
        fr"|{SYMBOL_HYPHEN}"
        fr"|{SYMBOL_SLASH}"
        fr"|{SYMBOL_UNDERSCORE}"
        fr"|{SYMBOL_MUL}"
        fr"|{PUNCT}",
        re.I
    )

    def norm_token(token):
        token = re.sub(SYMBOL_HYPHEN, "-", token)
        token = token.replace("µ", "μ")
        token = re.sub(SYMBOL_APOST, "'", token)
        token = re.sub(r"×", "x", token)
        token = token.lower()
        return token

    all_doc_id = []
    all_token_idx = []
    all_token_raw = []
    all_token_norm = []

    for doc_idx, text, doc_id in zip(range(len(arr)), arr, doc_ids):
        normed = unicodedata.normalize('NFKC', text)
        blocks = normed.strip().split()
        token_idx = 0
        for block in blocks:
            tokens = [m.group() for m in SPLIT_PATTERN.finditer(block)]
            for t in tokens:
                t = t.strip()
                if not t: continue
                all_doc_id.append(doc_id)
                all_token_idx.append(token_idx)
                all_token_raw.append(t)
                all_token_norm.append(norm_token(t))
                token_idx += 1

    return pd.DataFrame({
        'doc_id': all_doc_id,
        'token_idx': all_token_idx,
        'token_raw': all_token_raw,
        'token_norm': all_token_norm
    })


class RobinHoodHashMap:
    
    EMPTY_HASH = np.uint64(0)
    TOMBSTONE_VALUE = np.int32(-1)
    MAX_LOAD_FACTOR = 0.72
    MIN_LOAD_FACTOR = 0.2
    TOMBSTONE_THRESHOLD = 0.25
    
    def __init__(self, initial_capacity=None):
        if initial_capacity is None:
            initial_capacity = 131072
        initial_capacity = self._next_power_of_two(initial_capacity)
        
        self.capacity = initial_capacity
        self.capacity_mask = np.uint64(self.capacity - 1)
        self.size = 0
        self.tombstone_count = 0
        
        self.key_hashes = np.zeros(self.capacity, dtype=np.uint64)
        self.values = np.zeros(self.capacity, dtype=np.int32)
    
    @staticmethod
    def _next_power_of_two(n):
        if n <= 0:
            return 1
        n -= 1
        n |= n >> 1
        n |= n >> 2
        n |= n >> 4
        n |= n >> 8
        n |= n >> 16
        n |= n >> 32
        return n + 1
    
    def _hash_to_slot(self, key_hash):
        return np.uint64(key_hash) & self.capacity_mask
    
    def _probe_distance(self, slot, key_hash):
        initial_slot = self._hash_to_slot(key_hash)
        slot = np.uint64(slot)
        initial_slot = np.uint64(initial_slot)
        capacity = np.uint64(self.capacity)
        if slot >= initial_slot:
            return int(slot - initial_slot)
        else:
            return int(capacity - initial_slot + slot)
    
    def _should_resize(self):
        effective_load = (self.size + self.tombstone_count) / self.capacity
        return effective_load > self.MAX_LOAD_FACTOR
    
    def _should_shrink(self):
        if self.capacity <= 131072:
            return False
        load_factor = self.size / self.capacity
        return load_factor < self.MIN_LOAD_FACTOR
    
    def _should_compact(self):
        if self.tombstone_count == 0:
            return False
        tombstone_ratio = self.tombstone_count / self.capacity
        return tombstone_ratio > self.TOMBSTONE_THRESHOLD
    
    def _resize(self, new_capacity=None):
        old_key_hashes = self.key_hashes
        old_values = self.values
        old_capacity = self.capacity
        
        if new_capacity is None:
            new_capacity = self.capacity * 2
        else:
            new_capacity = self._next_power_of_two(new_capacity)
        
        self.capacity = new_capacity
        self.capacity_mask = np.uint64(self.capacity - 1)
        old_size = self.size
        self.size = 0
        self.tombstone_count = 0
        
        self.key_hashes = np.zeros(self.capacity, dtype=np.uint64)
        self.values = np.zeros(self.capacity, dtype=np.int32)
        
        for i in range(old_capacity):
            if old_key_hashes[i] != self.EMPTY_HASH and old_values[i] != self.TOMBSTONE_VALUE:
                self._insert_internal(old_key_hashes[i], old_values[i])
    
    def _compact(self):
        old_capacity = self.capacity
        self._resize(old_capacity)
    
    def _insert_internal(self, key_hash, value):
        key_hash = np.uint64(key_hash)
        initial_slot = self._hash_to_slot(key_hash)
        probe_distance = 0
        current_key = key_hash
        current_value = value
        
        slot = np.uint64(initial_slot)
        max_probes = self.capacity
        probe_count = 0
        
        while probe_count < max_probes:
            slot_hash = self.key_hashes[slot]
            
            if slot_hash == self.EMPTY_HASH:
                self.key_hashes[slot] = current_key
                self.values[slot] = current_value
                self.size += 1
                return
            
            if slot_hash == current_key:
                if self.values[slot] == self.TOMBSTONE_VALUE:
                    self.values[slot] = current_value
                    self.size += 1
                    self.tombstone_count -= 1
                else:
                    self.values[slot] = current_value
                return
            
            if self.values[slot] == self.TOMBSTONE_VALUE:
                self.key_hashes[slot] = current_key
                self.values[slot] = current_value
                self.size += 1
                self.tombstone_count -= 1
                return
            
            existing_probe_distance = self._probe_distance(slot, slot_hash)
            
            if existing_probe_distance < probe_distance:
                self.key_hashes[slot], current_key = current_key, slot_hash
                self.values[slot], current_value = current_value, self.values[slot]
                probe_distance = existing_probe_distance
            
            slot = np.uint64(slot + 1) & self.capacity_mask
            probe_distance += 1
            probe_count += 1
        
        diagnostic_info = {
            'capacity': self.capacity,
            'size': self.size,
            'tombstone_count': self.tombstone_count,
            'load_factor': (self.size + self.tombstone_count) / self.capacity,
            'max_probes': max_probes,
            'probe_count': probe_count,
            'key_hash': int(key_hash)
        }
        raise RuntimeError(
            f"Hash table is full or hash function produces too many collisions. "
            f"Diagnostics: {diagnostic_info}"
        )
    
    def __contains__(self, key_hash):
        key_hash = np.uint64(key_hash)
        initial_slot = self._hash_to_slot(key_hash)
        probe_distance = 0
        slot = np.uint64(initial_slot)
        max_probes = self.capacity
        probe_count = 0
        
        while probe_count < max_probes:
            slot_hash = self.key_hashes[slot]
            
            if slot_hash == self.EMPTY_HASH:
                return False
            
            if slot_hash == key_hash and self.values[slot] != self.TOMBSTONE_VALUE:
                return True
            
            existing_probe_distance = self._probe_distance(slot, slot_hash)
            if probe_distance > existing_probe_distance:
                return False
            
            slot = np.uint64(slot + 1) & self.capacity_mask
            probe_distance += 1
            probe_count += 1
        
        return False
    
    def __getitem__(self, key_hash):
        key_hash = np.uint64(key_hash)
        initial_slot = self._hash_to_slot(key_hash)
        probe_distance = 0
        slot = np.uint64(initial_slot)
        max_probes = self.capacity
        probe_count = 0
        
        while probe_count < max_probes:
            slot_hash = self.key_hashes[slot]
            
            if slot_hash == self.EMPTY_HASH:
                raise KeyError(f"Key {key_hash} not found")
            
            if slot_hash == key_hash and self.values[slot] != self.TOMBSTONE_VALUE:
                return int(self.values[slot])
            
            existing_probe_distance = self._probe_distance(slot, slot_hash)
            if probe_distance > existing_probe_distance:
                raise KeyError(f"Key {key_hash} not found")
            
            slot = np.uint64(slot + 1) & self.capacity_mask
            probe_distance += 1
            probe_count += 1
        
        raise KeyError(f"Key {key_hash} not found")
    
    def __delitem__(self, key_hash):
        key_hash = np.uint64(key_hash)
        initial_slot = self._hash_to_slot(key_hash)
        probe_distance = 0
        slot = np.uint64(initial_slot)
        max_probes = self.capacity
        probe_count = 0
        
        while probe_count < max_probes:
            slot_hash = self.key_hashes[slot]
            
            if slot_hash == self.EMPTY_HASH:
                raise KeyError(f"Key {key_hash} not found")
            
            if slot_hash == key_hash:
                if self.values[slot] == self.TOMBSTONE_VALUE:
                    raise KeyError(f"Key {key_hash} not found")
                else:
                    self.values[slot] = self.TOMBSTONE_VALUE
                    self.size -= 1
                    self.tombstone_count += 1
                    return
            
            existing_probe_distance = self._probe_distance(slot, slot_hash)
            if probe_distance > existing_probe_distance:
                raise KeyError(f"Key {key_hash} not found")
            
            slot = np.uint64(slot + 1) & self.capacity_mask
            probe_distance += 1
            probe_count += 1
        
        raise KeyError(f"Key {key_hash} not found")
    
    def __setitem__(self, key_hash, value):
        if self._should_resize():
            self._resize()
        elif self._should_compact():
            self._compact()
        elif self._should_shrink():
            new_capacity = max(131072, self.capacity // 2)
            self._resize(new_capacity)
        
        self._insert_internal(key_hash, np.int32(value))
    
    def get(self, key_hash, default=None):
        key_hash = np.uint64(key_hash)
        initial_slot = self._hash_to_slot(key_hash)
        probe_distance = 0
        slot = np.uint64(initial_slot)
        max_probes = self.capacity
        probe_count = 0
        
        while probe_count < max_probes:
            slot_hash = self.key_hashes[slot]
            
            if slot_hash == self.EMPTY_HASH:
                return default
            
            if slot_hash == key_hash and self.values[slot] != self.TOMBSTONE_VALUE:
                return int(self.values[slot])
            
            existing_probe_distance = self._probe_distance(slot, slot_hash)
            if probe_distance > existing_probe_distance:
                return default
            
            slot = np.uint64(slot + 1) & self.capacity_mask
            probe_distance += 1
            probe_count += 1
        
        return default
    
    def clear(self):
        self.size = 0
        self.tombstone_count = 0
        self.key_hashes.fill(self.EMPTY_HASH)
        self.values.fill(0)
    
    def __len__(self):
        return self.size
    
    def get_stats(self):
        effective_load = (self.size + self.tombstone_count) / self.capacity if self.capacity > 0 else 0
        load_factor = self.size / self.capacity if self.capacity > 0 else 0
        tombstone_ratio = self.tombstone_count / self.capacity if self.capacity > 0 else 0
        return {
            'capacity': self.capacity,
            'size': self.size,
            'tombstone_count': self.tombstone_count,
            'load_factor': load_factor,
            'effective_load_factor': effective_load,
            'tombstone_ratio': tombstone_ratio
        }


class NumpyNgramStore:
    def __init__(self, max_token_id=1000000, max_ctx_size=200, initial_capacity=None):
        self.max_token_id = max_token_id
        self.max_ctx_size = max_ctx_size
        
        if initial_capacity is None:
            initial_capacity = 8192
        
        self.ngram_arrays = []
        self._capacity = initial_capacity
        self._size = 0
        self.n_values = np.empty(self._capacity, dtype=np.int32)
        self.df_counts = np.empty(self._capacity, dtype=np.int32)
        self.last_doc_ids = np.empty(self._capacity, dtype=np.int32)
        self.doc_ids_lists = []
        
        self.ngram_index_map = {}
        
        self.left_ctx_rows = []
        self.right_ctx_rows = []

    
    def _ngram_to_hash(self, ngram_array):
        return hash(ngram_array.tobytes())
    
    def _ensure_capacity(self):
        if self._size >= self._capacity:
            new_capacity = self._capacity * 2
            new_n_values = np.empty(new_capacity, dtype=np.int32)
            new_df_counts = np.empty(new_capacity, dtype=np.int32)
            new_last_doc_ids = np.empty(new_capacity, dtype=np.int32)
            new_n_values[:self._size] = self.n_values[:self._size]
            new_df_counts[:self._size] = self.df_counts[:self._size]
            new_last_doc_ids[:self._size] = self.last_doc_ids[:self._size]
            self.n_values = new_n_values
            self.df_counts = new_df_counts
            self.last_doc_ids = new_last_doc_ids
            self._capacity = new_capacity
    
    def get_or_create_index(self, ngram_array, n):
        ngram_hash = self._ngram_to_hash(ngram_array)
        if ngram_hash in self.ngram_index_map:
            return self.ngram_index_map[ngram_hash]
        
        self._ensure_capacity()
        idx = self._size
        self.ngram_arrays.append(ngram_array.copy())
        self.n_values[idx] = n
        self.df_counts[idx] = 0
        self.last_doc_ids[idx] = -1
        self.doc_ids_lists.append(set())
        
        self.left_ctx_rows.append(BoundedCounter(max_size=300))
        self.right_ctx_rows.append(BoundedCounter(max_size=300))
        
        self.ngram_index_map[ngram_hash] = idx
        self._size += 1
        return idx
    
    def update_ngram(self, ngram_array, n, doc_id, left_ctx_id, right_ctx_id):
        if not isinstance(ngram_array, np.ndarray):
            ngram_array = np.array(ngram_array, dtype=np.int32)
        
        idx = self.get_or_create_index(ngram_array, n)
        
        if self.last_doc_ids[idx] != doc_id:
            self.df_counts[idx] += 1
            self.last_doc_ids[idx] = doc_id
        
        self.doc_ids_lists[idx].add(doc_id)
        
        if left_ctx_id >= 0 and left_ctx_id < self.max_token_id:
            self.left_ctx_rows[idx][left_ctx_id] += 1
        if right_ctx_id >= 0 and right_ctx_id < self.max_token_id:
            self.right_ctx_rows[idx][right_ctx_id] += 1

    
    def batch_update(self, ngram_arrays, n_vals, doc_ids, left_ctx_ids, right_ctx_ids):
        if len(ngram_arrays) == 0:
            return
        
        ngram_arrays = [np.array(arr, dtype=np.int32) if not isinstance(arr, np.ndarray) else arr 
                        for arr in ngram_arrays]
        n_vals = np.array(n_vals, dtype=np.int32)
        doc_ids = np.array(doc_ids, dtype=np.int32)
        left_ctx_ids = np.array(left_ctx_ids, dtype=np.int32)
        right_ctx_ids = np.array(right_ctx_ids, dtype=np.int32)
        
        if len(ngram_arrays) != len(doc_ids):
            raise ValueError(f"ngram_arrays长度({len(ngram_arrays)})与doc_ids长度({len(doc_ids)})不匹配")
        if len(ngram_arrays) != len(n_vals):
            raise ValueError(f"ngram_arrays长度({len(ngram_arrays)})与n_vals长度({len(n_vals)})不匹配")
        
        indices = []
        for ngram_arr, n in zip(ngram_arrays, n_vals):
            idx = self.get_or_create_index(ngram_arr, int(n))
            indices.append(idx)
        
        indices = np.array(indices, dtype=np.int32)
        
        if len(left_ctx_ids) != len(ngram_arrays) or len(right_ctx_ids) != len(ngram_arrays):
            doc_to_ctx = {}
            left_pos = 0
            right_pos = 0
            
            for doc_id in doc_ids:
                if doc_id not in doc_to_ctx:
                    doc_to_ctx[doc_id] = {'left': [], 'right': []}
                
                while left_pos < len(left_ctx_ids):
                    token = left_ctx_ids[left_pos]
                    if token == -1:
                        left_pos += 1
                        break
                    doc_to_ctx[doc_id]['left'].append(token)
                    left_pos += 1
                
                while right_pos < len(right_ctx_ids):
                    token = right_ctx_ids[right_pos]
                    if token == -1:
                        right_pos += 1
                        break
                    doc_to_ctx[doc_id]['right'].append(token)
                    right_pos += 1
            
            for idx in np.unique(indices):
                mask = indices == idx
                if len(mask) != len(indices):
                    raise ValueError(f"mask长度({len(mask)})与indices长度({len(indices)})不匹配")
                if len(indices) != len(doc_ids):
                    raise ValueError(f"indices长度({len(indices)})与doc_ids长度({len(doc_ids)})不匹配")
                idx_doc_ids = doc_ids[mask]
                
                unique_docs = np.unique(idx_doc_ids)
                if len(unique_docs) > 0:
                    new_doc = unique_docs[0]
                    if self.last_doc_ids[idx] != new_doc:
                        self.df_counts[idx] += len(unique_docs)
                        self.last_doc_ids[idx] = new_doc
                    
                    self.doc_ids_lists[idx].update(unique_docs)
                
                all_left_ctx = []
                all_right_ctx = []
                for doc_id in idx_doc_ids:
                    if doc_id in doc_to_ctx:
                        all_left_ctx.extend(doc_to_ctx[doc_id]['left'])
                        all_right_ctx.extend(doc_to_ctx[doc_id]['right'])
                
                if len(all_left_ctx) > 0:
                    left_valid = np.array(all_left_ctx, dtype=np.int32)
                    left_valid = left_valid[(left_valid >= 0) & (left_valid < self.max_token_id)]
                    if len(left_valid) > 0:
                        left_counts = np.bincount(left_valid)
                        nonzero_indices = np.nonzero(left_counts)[0]
                        for token_id in nonzero_indices:
                            self.left_ctx_rows[idx][token_id] += int(left_counts[token_id])
                
                if len(all_right_ctx) > 0:
                    right_valid = np.array(all_right_ctx, dtype=np.int32)
                    right_valid = right_valid[(right_valid >= 0) & (right_valid < self.max_token_id)]
                    if len(right_valid) > 0:
                        right_counts = np.bincount(right_valid)
                        nonzero_indices = np.nonzero(right_counts)[0]
                        for token_id in nonzero_indices:
                            self.right_ctx_rows[idx][token_id] += int(right_counts[token_id])
        else:
            unique_indices = np.unique(indices)
            
            for idx in unique_indices:
                mask = indices == idx
                if len(indices) != len(doc_ids):
                    raise ValueError(f"indices长度({len(indices)})与doc_ids长度({len(doc_ids)})不匹配")
                if len(indices) != len(left_ctx_ids):
                    raise ValueError(f"indices长度({len(indices)})与left_ctx_ids长度({len(left_ctx_ids)})不匹配")
                if len(indices) != len(right_ctx_ids):
                    raise ValueError(f"indices长度({len(indices)})与right_ctx_ids长度({len(right_ctx_ids)})不匹配")
                idx_doc_ids = doc_ids[mask]
                idx_left_ctx = left_ctx_ids[mask]
                idx_right_ctx = right_ctx_ids[mask]
                
                unique_docs = np.unique(idx_doc_ids)
                if len(unique_docs) > 0:
                    new_doc = unique_docs[0]
                    if self.last_doc_ids[idx] != new_doc:
                        self.df_counts[idx] += len(unique_docs)
                        self.last_doc_ids[idx] = new_doc
                    
                    self.doc_ids_lists[idx].update(unique_docs)
                
                left_valid = idx_left_ctx[(idx_left_ctx >= 0) & (idx_left_ctx < self.max_token_id)]
                right_valid = idx_right_ctx[(idx_right_ctx >= 0) & (idx_right_ctx < self.max_token_id)]
                
                if len(left_valid) > 0:
                    left_counts = np.bincount(left_valid)
                    nonzero_indices = np.nonzero(left_counts)[0]
                    for token_id in nonzero_indices:
                        self.left_ctx_rows[idx][token_id] += int(left_counts[token_id])
                
                if len(right_valid) > 0:
                    right_counts = np.bincount(right_valid)
                    nonzero_indices = np.nonzero(right_counts)[0]
                    for token_id in nonzero_indices:
                        self.right_ctx_rows[idx][token_id] += int(right_counts[token_id])
    
    def _convert_to_csr_if_needed(self):
        pass
    
    def get_top_contexts(self, idx, max_ctx):
        left_row = self.left_ctx_rows[idx]
        right_row = self.right_ctx_rows[idx]
        
        if len(left_row) > 0:
            left_dict = {int(k): int(v) for k, v in left_row.most_common(max_ctx)}
        else:
            left_dict = {}
        
        if len(right_row) > 0:
            right_dict = {int(k): int(v) for k, v in right_row.most_common(max_ctx)}
        else:
            right_dict = {}
        
        return left_dict, right_dict
    
    def clear(self):
        self.ngram_arrays.clear()
        self._size = 0
        self.n_values = np.empty(self._capacity, dtype=np.int32)
        self.df_counts = np.empty(self._capacity, dtype=np.int32)
        self.last_doc_ids = np.empty(self._capacity, dtype=np.int32)
        self.doc_ids_lists.clear()
        self.ngram_index_map.clear()
        self.left_ctx_rows.clear()
        self.right_ctx_rows.clear()
    
    def __len__(self):
        return self._size

class BoundedCounter:
    def __init__(self, max_size=100):
        self.max_size = max_size
        self.grow_threshold = int(max_size * 1.5)
        self.counts = {}
    
    def _batch_evict(self):
        if len(self.counts) >= self.grow_threshold:
            top_items = heapq.nlargest(self.max_size, self.counts.items(), key=lambda x: x[1])
            self.counts = dict(top_items)
    
    def __getitem__(self, key):
        return self.counts.get(key, 0)
    
    def __setitem__(self, key, value):
        self.counts[key] = value
        if len(self.counts) >= self.grow_threshold:
            self._batch_evict()
    
    def __iadd__(self, value):
        return self
    
    def update(self, other):
        if isinstance(other, (dict, Counter)):
            for key, count in other.items():
                if key in self.counts:
                    self.counts[key] += count
                else:
                    self.counts[key] = count
            if len(self.counts) >= self.grow_threshold:
                self._batch_evict()
    
    def most_common(self, n=None):
        if n is None:
            return sorted(self.counts.items(), key=lambda x: x[1], reverse=True)
        return heapq.nlargest(n, self.counts.items(), key=lambda x: x[1])
    
    def __len__(self):
        return len(self.counts)
    
    def to_dict(self):
        return self.counts.copy()
    
    def keys(self):
        return self.counts.keys()
    
    def values(self):
        return self.counts.values()
    
    def items(self):
        return self.counts.items()
    
    def __repr__(self):
        return f"BoundedCounter(max_size={self.max_size}, items={len(self.counts)})"

class ShardedNgramProcessor:

    def __init__(self, num_shards=512, memory_threshold_mb=500, temp_dir=None, max_token_id=1000000):
        self.num_shards = int(num_shards)
        self.memory_threshold_mb = int(memory_threshold_mb)
        self.temp_dir = temp_dir or config.get('temp_dir', 'temp')
        os.makedirs(self.temp_dir, exist_ok=True)
        self.max_token_id = max_token_id

        self.flush_after = 2000
        initial_capacity = 4096
        
        self._stores = [NumpyNgramStore(max_token_id=max_token_id, initial_capacity=initial_capacity) for _ in range(self.num_shards)]
        
        max_ctx = int(config.get('max_ctx_neighbors', 100) or 100)
        self.max_ctx_size = max_ctx * 2
        
        self.schema = pa.schema([                                                                                                                                                                                                                                       
            ('ngram_id_tuple', pa.list_(pa.field('item', pa.int32()))),
            ('n', pa.int32()),
            ('df', pa.int32()),
            ('last_doc_id', pa.int32()),
            ('doc_ids', pa.list_(pa.field('item', pa.int32()))),
            ('left_ctx_keys', pa.list_(pa.field('item', pa.int32()))),
            ('left_ctx_values', pa.list_(pa.field('item', pa.int32()))),
            ('right_ctx_keys', pa.list_(pa.field('item', pa.int32()))),
            ('right_ctx_values', pa.list_(pa.field('item', pa.int32())))
        ])

    def get_shard_idx(self, ngram_array):
        if isinstance(ngram_array, np.ndarray):
            key = ngram_array.tobytes()                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         
        else:
            key = tuple(ngram_array) if isinstance(ngram_array, (list, tuple)) else ngram_array
        return hash(key) % self.num_shards
    
    def update_ngram(self, ngram_array, n, doc_id, left_ctx_id, right_ctx_id):
        shard_idx = self.get_shard_idx(ngram_array)
        if not isinstance(ngram_array, np.ndarray):
            ngram_array = np.array(ngram_array, dtype=np.int32)
        self._stores[shard_idx].update_ngram(ngram_array, n, doc_id, left_ctx_id, right_ctx_id)
    
    def batch_update_ngrams(self, ngram_arrays, n_vals, doc_ids, left_ctx_ids, right_ctx_ids):
        shard_groups = defaultdict(lambda: {'arrays': [], 'n_vals': [], 'doc_ids': [], 
                                           'left_ctx': [], 'right_ctx': []})
        
        for arr, n, doc_id, left_id, right_id in zip(ngram_arrays, n_vals, doc_ids, left_ctx_ids, right_ctx_ids):
            shard_idx = self.get_shard_idx(arr)
            shard_groups[shard_idx]['arrays'].append(arr)
            shard_groups[shard_idx]['n_vals'].append(n)
            shard_groups[shard_idx]['doc_ids'].append(doc_id)
            shard_groups[shard_idx]['left_ctx'].append(left_id)
            shard_groups[shard_idx]['right_ctx'].append(right_id)
        
        for shard_idx, group in shard_groups.items():
            self._stores[shard_idx].batch_update(
                group['arrays'], group['n_vals'], group['doc_ids'],
                group['left_ctx'], group['right_ctx']
            )

    def spill_shard_to_disk(self, shard_idx, chunk_idx, proc_id):
        store = self._stores[shard_idx]
        if len(store) == 0:
            return
        
        ngram_id_tuples = []
        n_values = []
        df_values = []
        last_doc_ids = []
        doc_ids_list = []
        left_ctx_keys_list = []
        left_ctx_values_list = []
        right_ctx_keys_list = []
        right_ctx_values_list = []
        
        max_ctx = int(config.get('max_ctx_neighbors', 100) or 100)
        
        for idx in range(len(store)):
            ngram_array = store.ngram_arrays[idx]
            ngram_id_tuples.append([np.int32(x).item() for x in ngram_array.tolist()])
            n_values.append(np.int32(store.n_values[idx]).item())
            df_values.append(np.int32(store.df_counts[idx]).item())
            last_doc_ids.append(np.int32(store.last_doc_ids[idx]).item())
            
            doc_ids_set = store.doc_ids_lists[idx]
            doc_ids_list.append([np.int32(x).item() for x in sorted(doc_ids_set)] if len(doc_ids_set) > 0 else [])
            
            left_dict, right_dict = store.get_top_contexts(idx, max_ctx)
            left_ctx_keys_list.append([np.int32(x).item() for x in left_dict.keys()])
            left_ctx_values_list.append([np.int32(x).item() for x in left_dict.values()])
            right_ctx_keys_list.append([np.int32(x).item() for x in right_dict.keys()])
            right_ctx_values_list.append([np.int32(x).item() for x in right_dict.values()])
        
        if not ngram_id_tuples:
            store.clear()
            return
        
        store._convert_to_csr_if_needed()
        
        arrays = []
        for field in self.schema:
            if field.name == 'ngram_id_tuple':
                arr = pa.array(ngram_id_tuples)
                arr = arr.cast(pa.list_(pa.int32()), safe=False)
            elif field.name == 'n':
                arr = pa.array(n_values)
                arr = arr.cast(pa.int32(), safe=False)
            elif field.name == 'df':
                arr = pa.array(df_values)
                arr = arr.cast(pa.int32(), safe=False)
            elif field.name == 'last_doc_id':
                arr = pa.array(last_doc_ids)
                arr = arr.cast(pa.int32(), safe=False)
            elif field.name == 'doc_ids':
                arr = pa.array(doc_ids_list)
                arr = arr.cast(pa.list_(pa.int32()), safe=False)
            elif field.name == 'left_ctx_keys':
                arr = pa.array(left_ctx_keys_list)
                arr = arr.cast(pa.list_(pa.int32()), safe=False)
            elif field.name == 'left_ctx_values':
                arr = pa.array(left_ctx_values_list)
                arr = arr.cast(pa.list_(pa.int32()), safe=False)
            elif field.name == 'right_ctx_keys':
                arr = pa.array(right_ctx_keys_list)
                arr = arr.cast(pa.list_(pa.int32()), safe=False)
            elif field.name == 'right_ctx_values':
                arr = pa.array(right_ctx_values_list)
                arr = arr.cast(pa.list_(pa.int32()), safe=False)
            else:
                continue
            arrays.append(arr)
        
        table = pa.Table.from_arrays(arrays, schema=self.schema)
        table = table.cast(self.schema)
        
        filepath = os.path.join(self.temp_dir, f'shard_{shard_idx}_chunk_{chunk_idx}_proc_{proc_id}.parquet')
        filepath = os.path.normpath(filepath)
        
        pq.write_table(table, filepath, compression='snappy', use_deprecated_int96_timestamps=False, coerce_timestamps='us')
        store.clear()
        gc.collect()

    def check_and_spill(self, chunk_idx, proc_id):
        total_spilled = 0
        for shard_idx in range(self.num_shards):
            store_len = len(self._stores[shard_idx])
            if store_len >= self.flush_after:
                self.spill_shard_to_disk(shard_idx, chunk_idx, proc_id)
                total_spilled += 1
        gc.collect()

    def merge_shard_files(self, shard_idx, chunk_idx, token_id_to_norm, proc_id_list, timings_dict=None):
        t_read_start = time.time()
        files = []
        temp_dir_norm = os.path.normpath(self.temp_dir)
        for proc_id in proc_id_list:
            pattern = os.path.join(temp_dir_norm, f'shard_{shard_idx}_chunk_{chunk_idx}_proc_{proc_id}*.parquet')
            pattern = os.path.normpath(pattern)
            matched_files = glob.glob(pattern)
            if not matched_files:
                exact_pattern = os.path.join(temp_dir_norm, f'shard_{shard_idx}_chunk_{chunk_idx}_proc_{proc_id}.parquet')
                exact_pattern = os.path.normpath(exact_pattern)
                if os.path.exists(exact_pattern):
                    matched_files = [exact_pattern]
            files.extend(matched_files)
        files = sorted(files)
        

        initial_capacity = 4096
        merge_store = NumpyNgramStore(max_token_id=self.max_token_id, initial_capacity=initial_capacity)
        max_ctx = int(config.get('max_ctx_neighbors', 100) or 100)
        t_read_init = time.time() - t_read_start
        
        time_read_batch = 0.0
        time_batch_update = 0.0
        total_rows_read = 0
        for f in files:
            t_file_open = time.time()
            parquet_file = pq.ParquetFile(f)
            file_schema = parquet_file.schema
            time_read_batch += time.time() - t_file_open
            
            if not all(col in file_schema.names for col in self.schema.names):
                file_arrow_schema = parquet_file.schema_arrow
                if len(file_schema.names) == len(self.schema.names):
                    types_match = all(f1.type == f2.type for f1, f2 in zip(file_arrow_schema, self.schema))
                    table = parquet_file.read()
                    table = table.rename_columns(self.schema.names)
                    table = table.cast(self.schema)
                    for batch in table.to_batches(max_chunksize=10000):
                        batch_table = pa.Table.from_batches([batch], schema=self.schema)
                        ngram_id_tuples = batch_table['ngram_id_tuple'].to_pylist()
                        if not ngram_id_tuples:
                            continue
                        total_rows_read += len(ngram_id_tuples)
                        batch_len = len(ngram_id_tuples)
                        n_values = batch_table['n'].to_pylist()
                        df_values = batch_table['df'].to_pylist()
                        doc_ids_col = batch_table['doc_ids'].to_pylist()
                        left_ctx_keys = batch_table['left_ctx_keys'].to_pylist()
                        left_ctx_values = batch_table['left_ctx_values'].to_pylist()
                        right_ctx_keys = batch_table['right_ctx_keys'].to_pylist()
                        right_ctx_values = batch_table['right_ctx_values'].to_pylist()
                        
                        ngram_arrays_batch = []
                        n_vals_batch = []
                        doc_ids_batch = []
                        left_ctx_ids_batch = []
                        right_ctx_ids_batch = []
                        
                        for i in range(len(ngram_id_tuples)):
                            ngram_tuple = ngram_id_tuples[i] if ngram_id_tuples[i] else []
                            ngram_array = np.array(ngram_tuple, dtype=np.int32)
                            n = int(n_values[i]) if i < len(n_values) else 0
                            
                            doc_ids_list = doc_ids_col[i] if i < len(doc_ids_col) and doc_ids_col[i] else []
                            left_keys = left_ctx_keys[i] if i < len(left_ctx_keys) and left_ctx_keys[i] else []
                            left_vals = left_ctx_values[i] if i < len(left_ctx_values) and left_ctx_values[i] else []
                            right_keys = right_ctx_keys[i] if i < len(right_ctx_keys) and right_ctx_keys[i] else []
                            right_vals = right_ctx_values[i] if i < len(right_ctx_values) and right_ctx_values[i] else []
                            
                            for doc_id in doc_ids_list:
                                ngram_arrays_batch.append(ngram_array)
                                n_vals_batch.append(n)
                                doc_ids_batch.append(doc_id)
                                
                                if left_keys and left_vals and len(left_keys) == len(left_vals):
                                    for key, val in zip(left_keys, left_vals):
                                        for _ in range(int(val)):
                                            left_ctx_ids_batch.append(key)
                                    left_ctx_ids_batch.append(-1)
                                else:
                                    left_ctx_ids_batch.append(-1)
                                
                                if right_keys and right_vals and len(right_keys) == len(right_vals):
                                    for key, val in zip(right_keys, right_vals):
                                        for _ in range(int(val)):
                                            right_ctx_ids_batch.append(key)
                                    right_ctx_ids_batch.append(-1)
                                else:
                                    right_ctx_ids_batch.append(-1)
                        
                        if len(ngram_arrays_batch) > 0:
                            merge_store.batch_update(
                                ngram_arrays_batch, n_vals_batch, doc_ids_batch,
                                left_ctx_ids_batch, right_ctx_ids_batch
                            )
                    continue
                else:
                    continue
            else:
                continue
            
            batch_count = 0
            for batch in parquet_file.iter_batches(batch_size=10000):
                batch_count += 1
                t_batch_read = time.time()
                table = pa.Table.from_batches([batch])
                
                if 'ngram_id_tuple' not in table.column_names or len(table) == 0:
                    continue
                
                ngram_id_tuples = table['ngram_id_tuple'].to_pylist()
                if not ngram_id_tuples:
                    continue
                
                total_rows_read += len(ngram_id_tuples)
                
                batch_len = len(ngram_id_tuples)
                n_values = table['n'].to_pylist() if 'n' in table.column_names else [0] * batch_len
                df_values = table['df'].to_pylist() if 'df' in table.column_names else [0] * batch_len
                doc_ids_col = table['doc_ids'].to_pylist() if 'doc_ids' in table.column_names else [[]] * batch_len
                left_ctx_keys = table['left_ctx_keys'].to_pylist() if 'left_ctx_keys' in table.column_names else [[]] * batch_len
                left_ctx_values = table['left_ctx_values'].to_pylist() if 'left_ctx_values' in table.column_names else [[]] * batch_len
                right_ctx_keys = table['right_ctx_keys'].to_pylist() if 'right_ctx_keys' in table.column_names else [[]] * batch_len
                right_ctx_values = table['right_ctx_values'].to_pylist() if 'right_ctx_values' in table.column_names else [[]] * batch_len
                
                ngram_arrays_batch = []
                n_vals_batch = []
                doc_ids_batch = []
                left_ctx_ids_batch = []
                right_ctx_ids_batch = []
                
                for i in range(len(ngram_id_tuples)):
                    ngram_tuple = ngram_id_tuples[i] if ngram_id_tuples[i] else []
                    ngram_array = np.array(ngram_tuple, dtype=np.int32)
                    n = int(n_values[i]) if i < len(n_values) else 0
                    
                    doc_ids_list = doc_ids_col[i] if i < len(doc_ids_col) and doc_ids_col[i] else []
                    left_keys = left_ctx_keys[i] if i < len(left_ctx_keys) and left_ctx_keys[i] else []
                    left_vals = left_ctx_values[i] if i < len(left_ctx_values) and left_ctx_values[i] else []
                    right_keys = right_ctx_keys[i] if i < len(right_ctx_keys) and right_ctx_keys[i] else []
                    right_vals = right_ctx_values[i] if i < len(right_ctx_values) and right_ctx_values[i] else []
                    
                    for doc_id in doc_ids_list:
                        ngram_arrays_batch.append(ngram_array)
                        n_vals_batch.append(n)
                        doc_ids_batch.append(doc_id)
                        
                        if left_keys and left_vals and len(left_keys) == len(left_vals):
                            for key, val in zip(left_keys, left_vals):
                                for _ in range(int(val)):
                                    left_ctx_ids_batch.append(key)
                            left_ctx_ids_batch.append(-1)
                        else:
                            left_ctx_ids_batch.append(-1)
                        
                        if right_keys and right_vals and len(right_keys) == len(right_vals):
                            for key, val in zip(right_keys, right_vals):
                                for _ in range(int(val)):
                                    right_ctx_ids_batch.append(key)
                            right_ctx_ids_batch.append(-1)
                        else:
                            right_ctx_ids_batch.append(-1)
                time_read_batch += time.time() - t_batch_read
                
                t_update = time.time()
                if len(ngram_arrays_batch) > 0:
                    if len(ngram_arrays_batch) != len(doc_ids_batch):
                        raise ValueError(f"merge_shard_files: ngram_arrays_batch长度({len(ngram_arrays_batch)})与doc_ids_batch长度({len(doc_ids_batch)})不匹配")
                    if len(ngram_arrays_batch) != len(n_vals_batch):
                        raise ValueError(f"merge_shard_files: ngram_arrays_batch长度({len(ngram_arrays_batch)})与n_vals_batch长度({len(n_vals_batch)})不匹配")
                    merge_store.batch_update(
                        ngram_arrays_batch, n_vals_batch, doc_ids_batch,
                        left_ctx_ids_batch, right_ctx_ids_batch
                    )
                time_batch_update += time.time() - t_update
                
                del table, batch
        
        if timings_dict is not None:
            timings_dict['read_files'] += t_read_init + time_read_batch
            timings_dict['batch_update'] += time_batch_update

        t_mem_start = time.time()
        store = self._stores[shard_idx]
        if len(store) > 0:
            ngram_arrays_mem = []
            n_vals_mem = []
            doc_ids_mem = []
            left_ctx_ids_mem = []
            right_ctx_ids_mem = []
            
            for idx in range(len(store)):
                ngram_array = store.ngram_arrays[idx]
                n = int(store.n_values[idx])
                doc_ids_arr = store.doc_ids_lists[idx]
                
                left_row = store.left_ctx_rows[idx]
                right_row = store.right_ctx_rows[idx]
                
                doc_ids_len = len(doc_ids_arr)
                if doc_ids_len > 0:
                    ngram_arrays_mem.extend([ngram_array] * doc_ids_len)
                    n_vals_mem.extend([n] * doc_ids_len)
                    doc_ids_mem.extend([int(doc_id) for doc_id in doc_ids_arr])
                    
                    if len(left_row) > 0:
                        left_ctx_pattern = []
                        for token_id, count in left_row.items():
                            count_int = int(count)
                            if count_int > 0:
                                left_ctx_pattern.extend([int(token_id)] * count_int)
                        left_ctx_pattern.append(-1)
                        for doc_id in doc_ids_arr:
                            left_ctx_ids_mem.extend(left_ctx_pattern)
                    else:
                        left_ctx_ids_mem.extend([-1] * doc_ids_len)
                    
                    if len(right_row) > 0:
                        right_ctx_pattern = []
                        for token_id, count in right_row.items():
                            count_int = int(count)
                            if count_int > 0:
                                right_ctx_pattern.extend([int(token_id)] * count_int)
                        right_ctx_pattern.append(-1)
                        for doc_id in doc_ids_arr:
                            right_ctx_ids_mem.extend(right_ctx_pattern)
                    else:
                        right_ctx_ids_mem.extend([-1] * doc_ids_len)
            
            if len(ngram_arrays_mem) > 0:
                merge_store.batch_update(
                    ngram_arrays_mem, n_vals_mem, doc_ids_mem,
                    left_ctx_ids_mem, right_ctx_ids_mem
                )
        
        if timings_dict is not None:
            timings_dict['process_memory_stores'] += time.time() - t_mem_start
        
        t_agg_start = time.time()
        agg = {}
        for idx in range(len(merge_store)):
            ngram_array = merge_store.ngram_arrays[idx]
            ngram_tuple = tuple(ngram_array)
            n = int(merge_store.n_values[idx])
            key = (ngram_tuple, n)
            
            agg[key] = {
                'n': n,
                'df': int(merge_store.df_counts[idx]),
                'doc_ids': merge_store.doc_ids_lists[idx].copy(),
                'left': BoundedCounter(self.max_ctx_size),
                'right': BoundedCounter(self.max_ctx_size)
            }
            
            left_dict, right_dict = merge_store.get_top_contexts(idx, max_ctx * 2)
            agg[key]['left'].update(left_dict)
            agg[key]['right'].update(right_dict)
        
        if timings_dict is not None:
            timings_dict['aggregate'] += time.time() - t_agg_start

        t_convert_start = time.time()
        rows = []
        for (ngram_ids, n), v in agg.items():
            left_most_common = v['left'].most_common(max_ctx)
            left_final = dict(left_most_common)
            left_all_dict = v['left'].to_dict()
            if len(left_all_dict) > len(left_final):
                other_sum = sum(c for t, c in left_all_dict.items() if t not in left_final)
                if other_sum > 0:
                    left_final['<OTHER>'] = other_sum
            
            right_most_common = v['right'].most_common(max_ctx)
            right_final = dict(right_most_common)
            right_all_dict = v['right'].to_dict()
            if len(right_all_dict) > len(right_final):
                other_sum = sum(c for t, c in right_all_dict.items() if t not in right_final)
                if other_sum > 0:
                    right_final['<OTHER>'] = other_sum

            ngram_norm_tuple = tuple(token_id_to_norm.get(tid, f'<ID:{tid}>') for tid in ngram_ids)
            doc_ids_result = list(v.get('doc_ids', set()))
            rows.append({
                'ngram_norm': ' '.join(ngram_norm_tuple),
                'ngram_raw': None,
                'ngram_id_tuple': tuple(ngram_ids),
                'ngram_norm_tuple': ngram_norm_tuple,
                'n': n,
                'df': int(v['df']),
                'doc_ids': doc_ids_result,
                'left_ctx_dist': left_final,
                'right_ctx_dist': right_final
            })

        if rows:
            result = pd.DataFrame(rows)
        else:
            result = pd.DataFrame(columns=[
                'ngram_norm', 'ngram_raw', 'ngram_id_tuple', 'ngram_norm_tuple', 'n', 'df', 'doc_ids',
                'left_ctx_dist', 'right_ctx_dist'
            ])
        
        if timings_dict is not None:
            timings_dict['convert_to_df'] += time.time() - t_convert_start
        
        return result


    def cleanup_shard_files(self, chunk_idx, proc_id):
        for shard_idx in range(self.num_shards):
            pattern = os.path.join(self.temp_dir, f'shard_{shard_idx}_chunk_{chunk_idx}_proc_{proc_id}*.parquet')
            for f in glob.glob(pattern):
                os.remove(f)
        for i in range(self.num_shards):
            self._stores[i].clear()
        gc.collect()

def _add_context_columns(tokens_df):
    tokens_df = tokens_df.sort_values(['doc_id', 'token_idx'], ignore_index=True)
    tokens_df['prev_token'] = tokens_df['token_norm'].shift(1, fill_value='<BOS>')
    tokens_df['next_token'] = tokens_df['token_norm'].shift(-1, fill_value='<EOS>')
    tokens_df['doc_break_prev'] = tokens_df['doc_id'] != tokens_df['doc_id'].shift(1)
    tokens_df['doc_break_next'] = tokens_df['doc_id'] != tokens_df['doc_id'].shift(-1)
    tokens_df.loc[tokens_df['doc_break_prev'], 'prev_token'] = '<BOS>'
    tokens_df.loc[tokens_df['doc_break_next'], 'next_token'] = '<EOS>'
    return tokens_df


def extract_unigram_compound_stats(tokens_df: pd.DataFrame, compound_pattern=None):
    tokens_df = _add_context_columns(tokens_df)

    if compound_pattern is None:
        compound_pattern = re.compile(COMPOUND_PATTERN, re.I)

    unigram_records = []
    for idx, row in tokens_df.iterrows():
        token_raw = str(row['token_raw'])
        token_norm = str(row['token_norm'])
        if compound_pattern.fullmatch(token_raw):
            unigram_records.append((
                token_norm, (token_raw,), (token_norm,), 1,
                row['doc_id'], row['prev_token'], row['next_token']
            ))
    
    if not unigram_records:
        return pd.DataFrame(columns=['ngram_norm', 'ngram_raw', 'ngram_norm_tuple', 'n', 'doc_id', 'left_ctx', 'right_ctx'])

    unigram_df = pd.DataFrame(
        unigram_records,
        columns=['ngram_norm', 'ngram_raw', 'ngram_norm_tuple', 'n', 'doc_id', 'left_ctx', 'right_ctx']
    )

    doc_counts = unigram_df.groupby(['ngram_norm', 'n', 'doc_id'], sort=False).size().reset_index(name='_count')
    df_counts = doc_counts.groupby(['ngram_norm', 'n'], sort=False).size().reset_index(name='df')
    
    ctx_agg = unigram_df.groupby(['ngram_norm', 'n'], sort=False).agg({
        'ngram_raw': 'first',
        'ngram_norm_tuple': 'first',
        'left_ctx': lambda x: dict(Counter(x)),
        'right_ctx': lambda x: dict(Counter(x)),
        'doc_id': lambda s: set(s)
    }).reset_index().rename(columns={'doc_id': 'doc_ids'})
    
    unigram_table = df_counts.merge(ctx_agg, on=['ngram_norm', 'n'], how='left')
    unigram_table = unigram_table.rename(columns={
        'left_ctx': 'left_ctx_dist',
        'right_ctx': 'right_ctx_dist'
    })
    return unigram_table

def _get_ngram_table_arrow_schema():
    return pa.schema([
        ('ngram_norm', pa.string()),
        ('ngram_raw', pa.list_(pa.string())),  # tuple 存储为 list<string>
        ('ngram_id_tuple', pa.list_(pa.int32())),
        ('ngram_norm_tuple', pa.list_(pa.string())),
        ('n', pa.int32()),
        ('df', pa.int32()),
        ('doc_ids', pa.list_(pa.int32())),
        ('left_ctx_dist', pa.struct([('keys', pa.list_(pa.int32())), ('values', pa.list_(pa.int32()))])),  # dict 存储为 struct，keys是token_id（整数）
        ('right_ctx_dist', pa.struct([('keys', pa.list_(pa.int32())), ('values', pa.list_(pa.int32()))]))
    ])


def _convert_to_arrow_table(ngram_table, use_explicit_schema=True):
    if ngram_table.empty:
        return pa.Table.from_pandas(ngram_table)
    
    if not use_explicit_schema:
        return pa.Table.from_pandas(ngram_table)
    
    schema = _get_ngram_table_arrow_schema()
    
    arrays = []
    for field in schema:
        col_name = field.name
        if col_name not in ngram_table.columns:
            arrays.append(None)
            continue
        
        if field.name == 'ngram_raw':
            raw_col = ngram_table[col_name]
            raw_list = [[r] if isinstance(r, str) else list(r) if isinstance(r, tuple) else r for r in raw_col]
            arrays.append(pa.array(raw_list, type=pa.list_(pa.string())))
        elif field.name == 'ngram_id_tuple':
            id_col = ngram_table[col_name]
            id_list = [list(t) if isinstance(t, tuple) else t for t in id_col]
            arrays.append(pa.array(id_list, type=pa.list_(pa.int32())))
        elif field.name == 'ngram_norm_tuple':
            norm_col = ngram_table[col_name]
            norm_list = [list(t) if isinstance(t, tuple) else t for t in norm_col]
            arrays.append(pa.array(norm_list, type=pa.list_(pa.string())))
        elif field.name in ['left_ctx_dist', 'right_ctx_dist']:
            ctx_col = ngram_table[col_name]
            ctx_maps = []
            for d in ctx_col:
                if isinstance(d, dict):
                    keys = list(d.keys())
                    values = list(d.values())
                    keys_int = []
                    for k in keys:
                        if k == '<OTHER>':
                            keys_int.append(-1)
                        elif isinstance(k, str) and k.startswith('<ID:'):
                            keys_int.append(int(k.replace('<ID:', '').replace('>', '')))
                        else:
                            keys_int.append(int(k))
                    ctx_maps.append({'keys': keys_int, 'values': values})
                else:
                    ctx_maps.append({'keys': [], 'values': []})
            arrays.append(pa.array(ctx_maps, type=field.type))
        elif field.name == 'doc_ids':
            doc_col = ngram_table[col_name]
            doc_list = [list(d) if isinstance(d, (set, tuple)) else d for d in doc_col]
            arrays.append(pa.array(doc_list, type=pa.list_(pa.int32())))
        else:
            arrays.append(pa.array(ngram_table[col_name], type=field.type))
    
    valid_arrays = []
    valid_fields = []
    for i, arr in enumerate(arrays):
        if arr is not None:
            valid_arrays.append(arr)
            valid_fields.append(schema[i])
    
    return pa.Table.from_arrays(valid_arrays, schema=pa.schema(valid_fields))

def _convert_from_arrow_table(arrow_table):
    df = arrow_table.to_pandas()
    
    if 'left_ctx_dist' in df.columns:
        def restore_ctx_dist(x):
            if isinstance(x, dict) and 'keys' in x:
                result = {}
                for k, v in zip(x['keys'], x['values']):
                    key = '<OTHER>' if k == -1 else k
                    result[key] = v
                return result
            return dict(x) if isinstance(x, dict) else {}
        df['left_ctx_dist'] = df['left_ctx_dist'].apply(restore_ctx_dist)
    if 'right_ctx_dist' in df.columns:
        def restore_ctx_dist(x):
            if isinstance(x, dict) and 'keys' in x:
                result = {}
                for k, v in zip(x['keys'], x['values']):
                    key = '<OTHER>' if k == -1 else k
                    result[key] = v
                return result
            return dict(x) if isinstance(x, dict) else {}
        df['right_ctx_dist'] = df['right_ctx_dist'].apply(restore_ctx_dist)
    if 'ngram_raw' in df.columns:
        df['ngram_raw'] = df['ngram_raw'].apply(lambda x: tuple(x) if isinstance(x, list) else x)
    if 'ngram_id_tuple' in df.columns:
        df['ngram_id_tuple'] = df['ngram_id_tuple'].apply(lambda x: tuple(x) if isinstance(x, list) else x)
    if 'ngram_norm_tuple' in df.columns:
        df['ngram_norm_tuple'] = df['ngram_norm_tuple'].apply(lambda x: tuple(x) if isinstance(x, list) else x)
    if 'doc_ids' in df.columns:
        df['doc_ids'] = df['doc_ids'].apply(lambda x: list(x) if not isinstance(x, list) else x)
    
    return df

def _fill_ngram_raw_optimized(ngram_table, token_id_to_raw, ngram_id_tuple_col='ngram_id_tuple'):
    if ngram_table.empty:
        ngram_table['ngram_raw'] = None
        return ngram_table
    
    if 'ngram_raw' in ngram_table.columns:
        has_valid_raw = ngram_table['ngram_raw'].notna().any()
        if has_valid_raw:
            return ngram_table
    
    arrow_table = _convert_to_arrow_table(ngram_table, use_explicit_schema=True)
    
    if 'ngram_id_tuple' in arrow_table.column_names:
        ngram_id_col = arrow_table['ngram_id_tuple'].to_pylist()
    else:
        ngram_id_col = arrow_table['ngram_norm_tuple'].to_pylist()
    
    ngram_raw_list = []
    for ngram_ids in ngram_id_col:
        if isinstance(ngram_ids, (list, tuple)):
            raw_tuple = tuple(token_id_to_raw.get(tid, f'<ID:{tid}>') for tid in ngram_ids)
        else:
            raw_tuple = (token_id_to_raw.get(ngram_ids, f'<ID:{ngram_ids}>'),)
        ngram_raw_list.append(raw_tuple)
    
    ngram_raw_array = pa.array([list(r) for r in ngram_raw_list], type=pa.list_(pa.string()))
    if 'ngram_raw' in arrow_table.column_names:
        col_idx = arrow_table.column_names.index('ngram_raw')
        arrow_table = arrow_table.remove_column(col_idx)
    arrow_table = arrow_table.append_column('ngram_raw', ngram_raw_array)
    ngram_table = _convert_from_arrow_table(arrow_table)
    
    return ngram_table

def _update_topk_store(topk_store, df_part, topk, min_df):
    if df_part is None or df_part.empty:
        return
    if min_df and isinstance(min_df, (int, float)) and min_df > 1:
        df_part = df_part.loc[df_part['df'] >= min_df]
        if df_part.empty:
            return

    if topk is None:
        for n_val, sub in df_part.groupby('n', sort=False):
            prev = topk_store.get(n_val)
            if prev is None or prev.empty:
                topk_store[n_val] = sub
            else:
                topk_store[n_val] = pd.concat([prev, sub], ignore_index=True)
        return
    
    for n_val, sub in df_part.groupby('n', sort=False):
        prev = topk_store.get(n_val)
        
        if prev is None or prev.empty:
            if len(sub) <= topk:
                topk_store[n_val] = sub.copy()
            else:
                topk_store[n_val] = sub.nlargest(topk, columns=['df'])
        else:
            if len(prev) >= topk:
                min_df_current = prev['df'].min()
                max_df_sub = sub['df'].max()
                eps = 1e-9
                if max_df_sub < min_df_current - eps:
                    continue
                elif abs(max_df_sub - min_df_current) <= eps:
                    sub_filtered = sub[abs(sub['df'] - min_df_current) <= eps]
                    if len(sub_filtered) > 0:
                        cand = pd.concat([prev, sub_filtered], ignore_index=True)
                        topk_store[n_val] = cand.nlargest(topk, columns=['df'])
                else:
                    sub_filtered = sub[sub['df'] >= min_df_current - eps]
                    if len(sub_filtered) > 0:
                        cand = pd.concat([prev, sub_filtered], ignore_index=True)
                        topk_store[n_val] = cand.nlargest(topk, columns=['df'])
            else:
                cand = pd.concat([prev, sub], ignore_index=True)
                topk_store[n_val] = cand.nlargest(topk, columns=['df'])

def _merge_token_vocabs(vocab_list, base_counter):
    all_tokens = set()
    for vocab in vocab_list:
        all_tokens.update(vocab.keys())
    
    sorted_tokens = sorted(all_tokens)
    merged_vocab = {}
    remap_dicts = []
    next_id = base_counter
    
    for token in sorted_tokens:
        if token == '<BOS>' or token == '<EOS>':
            merged_vocab[token] = 0
        else:
            merged_vocab[token] = next_id
            next_id += 1
    
    for vocab in vocab_list:
        remap = {}
        for token, old_id in vocab.items():
            new_id = merged_vocab[token]
            if old_id != 0 and new_id != 0:
                remap[old_id] = new_id
        remap_dicts.append(remap)
    
    return merged_vocab, next_id, remap_dicts

def _remap_token_ids_in_files(temp_dir, chunk_idx, proc_id, remap_dict, num_shards):
    
    for shard_idx in range(num_shards):
        pattern = os.path.join(temp_dir, f'shard_{shard_idx}_chunk_{chunk_idx}_proc_{proc_id}*.parquet')
        files = glob.glob(pattern)
        
        for filepath in files:
            df = pd.read_parquet(filepath)
            
            def remap_tuple(tup):
                if isinstance(tup, (list, np.ndarray)):
                    tup = tuple(tup)
                if isinstance(tup, tuple):
                    return tuple(remap_dict.get(tid, tid) if tid != 0 else 0 for tid in tup)
                return tup
            
            if 'ngram_id_tuple' in df.columns:
                df['ngram_id_tuple'] = df['ngram_id_tuple'].apply(remap_tuple)
            
            def remap_ctx_dist(ctx_dist):
                if isinstance(ctx_dist, dict):
                    new_dist = {}
                    for old_id, count in ctx_dist.items():
                        if old_id == 0:
                            new_id = 0
                        else:
                            new_id = remap_dict.get(old_id, old_id)
                        new_dist[new_id] = new_dist.get(new_id, 0) + count
                    return new_dist
                return ctx_dist
            
            if 'left_ctx_dist' in df.columns:
                df['left_ctx_dist'] = df['left_ctx_dist'].apply(remap_ctx_dist)
            if 'right_ctx_dist' in df.columns:
                df['right_ctx_dist'] = df['right_ctx_dist'].apply(remap_ctx_dist)
            
            df.to_parquet(filepath, compression='snappy', index=False)

def _extract_ngram_stats_worker(args):
    tokens_df_subset, chunk_idx, proc_id, ngram_range, min_ngram_df = args
    
    local_token_vocab = {}
    local_counter = 1
    
    ngram_table, updated_counter, timings = extract_ngram_stats(
        tokens_df_subset,
        proc_id,
        ngram_range=ngram_range,
        min_ngram_df=min_ngram_df,
        global_token_vocab=local_token_vocab,
        global_token_id_counter=local_counter,
        chunk_idx=chunk_idx
    )
    
    return local_token_vocab, proc_id, timings

def extract_ngram_stats(tokens_df: pd.DataFrame, proc_id, ngram_range=(2, 5), min_ngram_df=1, global_token_vocab=None, global_token_id_counter=None, chunk_idx=0):
    timings = {}
    t_start = time.time()
    
    t0 = time.time()
    tokens_df = _add_context_columns(tokens_df)
    tokens_df = tokens_df.sort_values(["doc_id", "token_idx"], ignore_index=True)
    timings['add_context_sort'] = time.time() - t0

    if global_token_vocab is None:
        raise ValueError("global_token_vocab 必须提供，不能为空")
    
    t1 = time.time()
    token_norm_to_id = global_token_vocab
    next_token_id = global_token_id_counter if global_token_id_counter is not None else 1
    unique_tokens = tokens_df['token_norm'].unique()
    for t in unique_tokens:
        t_str = str(t)
        if t_str not in token_norm_to_id:
            token_norm_to_id[t_str] = next_token_id
            next_token_id += 1
    updated_counter = next_token_id
    timings['build_vocab'] = time.time() - t1
    
    BOS_ID = 0
    EOS_ID = 0
    
    token_id_to_norm = {}
    token_id_to_norm[BOS_ID] = '<BOS>'
    token_id_to_norm[EOS_ID] = '<EOS>'

    unique_doc_ids = tokens_df['doc_id'].unique()
    doc_id_to_int = {doc_id: i for i, doc_id in enumerate(unique_doc_ids)}

    doc_ids_raw = tokens_df["doc_id"].to_numpy()
    token_norm = tokens_df["token_norm"].astype(str).to_numpy()
    prev_t = tokens_df["prev_token"].astype(str).to_numpy()
    next_t = tokens_df["next_token"].astype(str).to_numpy()

    t1_5 = time.time()
    doc_ids = np.array([doc_id_to_int[did] for did in doc_ids_raw], dtype=np.int32)
    token_ids = np.array([token_norm_to_id.get(t, 0) for t in token_norm], dtype=np.int32)
    
    prev_ids = np.array([
        BOS_ID if t == '<BOS>' else (EOS_ID if t == '<EOS>' else token_norm_to_id.get(t, 0))
        for t in prev_t
    ], dtype=np.int32)
    next_ids = np.array([
        EOS_ID if t == '<EOS>' else (token_norm_to_id.get(t, 0) if t != '<BOS>' else BOS_ID)
        for t in next_t
    ], dtype=np.int32)
    timings['convert_to_arrays'] = time.time() - t1_5

    t2 = time.time()
    doc_offsets = np.flatnonzero(np.r_[True, doc_ids[1:] != doc_ids[:-1], True])
    max_ctx = int(config.get('max_ctx_neighbors', 100) or 100)
    
    num_shards = int(config.get('num_shards', 512))
    memory_threshold_mb = int(config.get('shard_memory_threshold_mb', 500))
    
    max_token_id = max(token_norm_to_id.values()) if token_norm_to_id else 1000000
    temp_dir_used = config.get('temp_dir', 'temp')
    processor = ShardedNgramProcessor(
        num_shards=num_shards,
        memory_threshold_mb=memory_threshold_mb,
        temp_dir=temp_dir_used,
        max_token_id=max_token_id + 1000
    )
    timings['init_processor'] = time.time() - t2

    t3 = time.time()
    time_generate_ngrams = 0.0
    time_batch_update = 0.0
    time_check_spill = 0.0
    for i in tqdm(range(len(doc_offsets) - 1), desc="🚀 处理文档", unit="doc", mininterval=1.0):
        s, e = doc_offsets[i], doc_offsets[i + 1]
        doc_id_int = doc_ids[s]
        doc_token_ids = token_ids[s:e]
        doc_prev_ids = prev_ids[s:e]
        doc_next_ids = next_ids[s:e]
        L = e - s
        if L < ngram_range[0]:
            continue

        t_ngram_start = time.time()
        total_ngrams = sum(max(0, L - n + 1) for n in range(ngram_range[0], ngram_range[1] + 1))
        if total_ngrams == 0:
            continue
        
        ngram_arrays_batch = []
        n_vals_batch = np.empty(total_ngrams, dtype=np.int32)
        doc_ids_batch = np.full(total_ngrams, doc_id_int, dtype=np.int32)
        left_ctx_ids_batch = np.empty(total_ngrams, dtype=np.int32)
        right_ctx_ids_batch = np.empty(total_ngrams, dtype=np.int32)
        
        idx = 0
        for n in range(ngram_range[0], ngram_range[1] + 1):
            count = L - n + 1
            if count <= 0:
                continue
            ngram_arrays_batch.extend([doc_token_ids[j:j+n] for j in range(count)])
            n_vals_batch[idx:idx+count] = n
            left_ctx_ids_batch[idx:idx+count] = doc_prev_ids[:count]
            right_ctx_ids_batch[idx:idx+count] = doc_next_ids[n-1:n-1+count]
            idx += count
        time_generate_ngrams += time.time() - t_ngram_start
        
        t_update_start = time.time()
        if ngram_arrays_batch:
            processor.batch_update_ngrams(
                ngram_arrays_batch, n_vals_batch, doc_ids_batch,
                left_ctx_ids_batch, right_ctx_ids_batch
            )
        time_batch_update += time.time() - t_update_start
        
        t_spill_start = time.time()
        if (i + 1) % 500 == 0:
            processor.check_and_spill(chunk_idx, proc_id)
        time_check_spill += time.time() - t_spill_start

        del doc_token_ids, doc_prev_ids, doc_next_ids

    timings['process_docs'] = time.time() - t3
    timings['process_docs_generate_ngrams'] = time_generate_ngrams
    timings['process_docs_batch_update'] = time_batch_update
    timings['process_docs_check_spill'] = time_check_spill
    
    t4 = time.time()
    processor.check_and_spill(chunk_idx, proc_id)
    timings['final_spill'] = time.time() - t4
    
    t5 = time.time()
    gc.collect()
    timings['gc_collect_1'] = time.time() - t5

    t6 = time.time()
    needed_ids = set()
    for store in processor._stores:
        for ngram_array in store.ngram_arrays:
            needed_ids.update(ngram_array.tolist())
        for left_row in store.left_ctx_rows:
            needed_ids.update(left_row.keys())
        for right_row in store.right_ctx_rows:
            needed_ids.update(right_row.keys())

    
    for shard_idx in range(processor.num_shards):
        pattern = os.path.join(processor.temp_dir, f'shard_{shard_idx}_chunk_{chunk_idx}_proc_{proc_id}*.parquet')
        for f in glob.glob(pattern):
            df = pd.read_parquet(f)
            if 'ngram_id_tuple' in df.columns:
                for ngram_seq in df['ngram_id_tuple']:
                    if isinstance(ngram_seq, (list, np.ndarray)):
                        needed_ids.update(ngram_seq)
                    elif isinstance(ngram_seq, tuple):
                        needed_ids.update(ngram_seq)
    
    for token, tid in token_norm_to_id.items():
        if tid in needed_ids:
            token_id_to_norm[tid] = token
    timings['collect_needed_ids'] = time.time() - t6
    
    t7 = time.time()
    topk_store = {}
    topk = config.get('max_ngrams_per_n')
    merge_shards_timings = {
        'read_files': 0.0,
        'batch_update': 0.0,
        'process_memory_stores': 0.0,
        'aggregate': 0.0,
        'convert_to_df': 0.0,
        'update_topk_store': 0.0,
        'gc_collect': 0.0
    }
    processor.check_and_spill(chunk_idx, proc_id)
    for shard_idx in range(processor.num_shards):
        if len(processor._stores[shard_idx]) > 0:
            processor.spill_shard_to_disk(shard_idx, chunk_idx, proc_id)
    gc_collect_interval = int(config.get('gc_collect_interval', 50))
    for shard_idx in tqdm(range(processor.num_shards), desc="🔄 归并分片", unit="shard"):
        result = processor.merge_shard_files(shard_idx, chunk_idx, token_id_to_norm, [proc_id], merge_shards_timings)
        if result is not None and not result.empty:
            t_update = time.time()
            _update_topk_store(topk_store, result, topk=topk, min_df=min_ngram_df)
            merge_shards_timings['update_topk_store'] += time.time() - t_update
            del result
            if (shard_idx + 1) % gc_collect_interval == 0 or shard_idx == processor.num_shards - 1:
                t_gc = time.time()
                gc.collect()
                merge_shards_timings['gc_collect'] += time.time() - t_gc
    timings['merge_shards'] = time.time() - t7
    timings.update({f'merge_shards_{k}': v for k, v in merge_shards_timings.items()})

    t8 = time.time()
    if topk_store:
        ngram_table = pd.concat(list(topk_store.values()), ignore_index=True)
    else:
        ngram_table = pd.DataFrame(columns=[
            'ngram_norm', 'ngram_raw', 'ngram_norm_tuple', 'n', 'df',
            'left_ctx_dist', 'right_ctx_dist'
        ])
    
    ngram_table = ngram_table.loc[ngram_table['df'] >= min_ngram_df].copy()
    

    if not ngram_table.empty:
        token_norm_to_id = global_token_vocab
        token_norm_to_raw = tokens_df.drop_duplicates(subset=['token_norm'], keep='first').set_index('token_norm')['token_raw'].astype(str).to_dict()
        token_id_to_raw = {token_norm_to_id.get(norm, -1): raw for norm, raw in token_norm_to_raw.items() if norm in token_norm_to_id}
        token_id_to_raw[-1] = '<UNK>'
        ngram_table = _fill_ngram_raw_optimized(ngram_table, token_id_to_raw, ngram_id_tuple_col='ngram_id_tuple')
    else:
        ngram_table['ngram_raw'] = None
    timings['postprocess_table'] = time.time() - t8

    timings['total'] = time.time() - t_start
    return ngram_table, updated_counter, timings

def compute_ngram_metrics_fast(ng, df_unigram, df_ngram, df95, function_words, total_docs=None):
    ngram_arr = ng['ngram_norm_tuple'].apply(lambda x: tuple(x) if not isinstance(x, tuple) else x).values
    n = np.array([len(ng) for ng in ngram_arr])
    freq_ngram_arr = np.asarray(ng['df'], dtype=float)

    if total_docs is None:
        raise ValueError("total_docs 必须提供，不能为 None")
    total_df = float(total_docs) + 1e-8

    PMI_arr = np.zeros(len(ng))
    minPMI_arr = np.zeros(len(ng))
    tscore_arr = np.zeros(len(ng))

    total_items = len(ngram_arr)
    print(f"[步骤5] 计算创新指标: 0/{total_items} (0.0%)", end='\r')
    for i, ngram in enumerate(ngram_arr):
        freq_ngram = freq_ngram_arr[i]

        ps = [df_unigram.get(t, 0) / total_df for t in ngram]
        p_xy = freq_ngram / total_df

        if len(ngram) == 1:
            pmi = 0
            minpmi = 0
        elif len(ngram) == 2 and ps[0] > 0 and ps[1] > 0 and p_xy > 0:
            pmi = np.log(p_xy / (ps[0] * ps[1]) + 1e-12)
            minpmi = pmi
        elif len(ngram) > 2:
            minpmi = np.inf
            for j in range(len(ngram)-1):
                l, r = ngram[j], ngram[j+1]
                p_l = df_unigram.get(l,0)/total_df
                p_r = df_unigram.get(r,0)/total_df
                pair = (l, r)
                freq_pair = df_ngram.get(pair, 0)
                p_pair = freq_pair / total_df
                if p_l > 0 and p_r > 0 and p_pair > 0:
                    pmi_val = np.log(p_pair / (p_l * p_r) + 1e-12)
                    minpmi = min(minpmi, pmi_val)
            pmi = minpmi if np.isfinite(minpmi) else 0
        else:
            pmi = 0
            minpmi = 0

        PMI_arr[i] = pmi
        minPMI_arr[i] = minpmi

        expect = total_df * np.prod([max(p, 1e-12) for p in ps])
        tscore_arr[i] = (freq_ngram - expect) / (np.sqrt(freq_ngram) + 1) if freq_ngram > 0 else 0
        
        if (i + 1) % max(1, total_items // 20) == 0 or (i + 1) == total_items:
            pct = (i + 1) / total_items * 100
            print(f"[步骤5] 计算创新指标: {i + 1}/{total_items} ({pct:.1f}%)", end='\r')

    def entropy_dist_batch(ctx_dist_series):
        Hs = []
        for d in ctx_dist_series:
            tot = sum(d.values()) if isinstance(d, dict) else 0
            if not tot or not isinstance(d, dict):
                Hs.append(0.)
                continue
            ps = np.array([v/tot for v in d.values() if v > 0])
            Hs.append(float(-np.sum(ps * np.log(ps+1e-12))))
        return np.array(Hs)

    H_left_arr = entropy_dist_batch(ng['left_ctx_dist'])
    H_right_arr = entropy_dist_batch(ng['right_ctx_dist'])

    rarity_arr = np.ones(len(ng))
    mask = (freq_ngram_arr > 0) & (df95 > 0)
    df95 = float(df95)
    rarity_arr[mask] = 1.0 - (np.log(freq_ngram_arr[mask] + 1) / np.log(df95 + 1))

    func_word_flags = np.zeros(len(ng), dtype=bool)
    for i, ngram in enumerate(ngram_arr):
        ngram_str = ' '.join(ngram)
        if all(t in function_words for t in ngram):
            func_word_flags[i] = True
        elif ngram[0] in function_words or ngram[-1] in function_words:
            func_word_flags[i] = True
        elif len(ngram) > 2:
            for j in range(1, len(ngram)-1):
                if ngram[j] in function_words:
                    func_word_flags[i] = True
                    break
        if '-' in ngram_str:
            func_word_flags[i] = False

    print(f"[步骤5] 计算创新指标: {total_items}/{total_items} (100.0%)")
    ng['PMI'] = PMI_arr
    ng['minPMI'] = minPMI_arr
    ng['t_score'] = tscore_arr
    ng['H_left'] = H_left_arr
    ng['H_right'] = H_right_arr
    ng['rarity'] = rarity_arr
    ng['is_function_word_dominated'] = func_word_flags
    return ng

def prefilter_ngram_candidates(
    ngram_table,
    min_df_threshold={1:5000, 2:3000, 3:800, 4:200, 5:80},
    minPMI_threshold={1: 0, 2: 3.5, 3: 4.5, 4: 5.0, 5: 5.5},
    min_entropy=1.5,
    exception_pattern=None
):
    """
    预筛 n-gram 候选：输出通过池与灰池。
    """
    df = ngram_table.copy()

    if exception_pattern is None:
        exception_pattern = re.compile(
            r"""(?:^|\s)
                (?:
                    [A-Za-z]+\d+[A-Za-z]* |              # ResNet50, GPT2
                    [A-Za-z]+-\d+ |                     # IL-6, ResNet-50
                    [A-Za-z]+-\w+-[A-Za-z0-9]+ |        # SARS-CoV-2, BERT-base-uncased
                    [A-Za-z0-9]+[/_-][A-Za-z0-9]+ |     # RG-108, RNA/DNA, state_of_the_art
                    \d+[A-Za-z]+ |                      # 5μm, 10%
                    [A-Za-z]+\d+[-/]\d+                 # IL-1β, COVID-19
                )
                (?:\s|$)
            """, re.X | re.I
        )

    ngram_str_normalized = df['ngram_norm_tuple'].apply(
        lambda x: ' '.join(str(t) for t in x) if isinstance(x, (tuple, list, np.ndarray)) else ''
    )
    exception_mask = ngram_str_normalized.str.contains(exception_pattern, na=False)

    noise_patterns = NOISE_PATTERNS
    ngram_str = ngram_str_normalized
    noise_mask = np.zeros(len(df), dtype=bool)
    for pat in noise_patterns:
        noise_mask = noise_mask | ngram_str.str.match(re.compile(pat))

    ng_n      = df['n'].astype(int).fillna(2)
    freq      = df['df'].astype(float).fillna(0)
    minPMI    = df['minPMI'].astype(float).fillna(0)
    H_left    = df['H_left'].astype(float).fillna(0)
    H_right   = df['H_right'].astype(float).fillna(0)

    vec_min_df    = ng_n.map(lambda n: min_df_threshold.get(n, 10)).values
    vec_min_pmi   = ng_n.map(lambda n: minPMI_threshold.get(n, 2)).values
    vec_ent       = min_entropy

    relax_df = vec_min_df / 5
    relax_pmi = vec_min_pmi - 0.5
    relax_ent = vec_ent

    is_unigram = (ng_n == 1).values
    pmi_check = np.where(is_unigram, True, minPMI >= vec_min_pmi)
    pmi_check_relax = np.where(is_unigram, True, minPMI >= relax_pmi)
    mask_strict = (
        (~noise_mask) &
        (~exception_mask) &
        (freq >= vec_min_df) &
        pmi_check &
        (H_left >= vec_ent) &
        (H_right >= vec_ent)
    )
    mask_exception = (
        (~noise_mask) &
        (exception_mask) &
        (freq >= relax_df) &
        pmi_check_relax &
        (H_left >= relax_ent) &
        (H_right >= relax_ent)
    )
    mask_grey = (
        (~noise_mask)
        & ~mask_strict
        & ~mask_exception
        &
        (
            (
                (freq >= vec_min_df * 0.6)
                & np.where(is_unigram, True, minPMI >= vec_min_pmi * 0.9)
                & (H_left >= vec_ent * 0.8)
                & (H_right >= vec_ent * 0.8)
            ) |
            (
                (exception_mask)
                & (freq >= relax_df * 0.6)
                & np.where(is_unigram, True, minPMI >= relax_pmi * 0.9)
                & (H_left >= relax_ent * 0.8)
                & (H_right >= relax_ent * 0.8)
            )
        )
    )

    through_pool = df.loc[mask_strict | mask_exception].copy()
    grey_pool = df.loc[mask_grey].copy()
    return through_pool, grey_pool

def lm_validate_candidates(
    df_candidates,
    text_corpus,
    k_contexts=10,
    window_size=80,
    batch_size=16,
    lm_name="allenai/scibert_scivocab_uncased",
    device=None,
    verbose=True,
    model=None,
    tokenizer=None,
    lm_p20_threshold=1.5,
    calibrate_threshold=False,
    calibration_sample_size=5,
):
    """
    用语言模型评估候选的自然度与编码成本。
    输入: 语料与候选；输出: LM_mean/LM_p20/subword_cost/LM_flag/LM_reason。
    """

    LM_DEVICE = device if device is not None else ("cuda" if torch.cuda.is_available() else "cpu")

    if model is None or tokenizer is None:
        if verbose:
            print(f"[LM] 加载模型 {lm_name}...")
        model = AutoModelForMaskedLM.from_pretrained(lm_name).to(LM_DEVICE)
        model.eval()
        tokenizer = AutoTokenizer.from_pretrained(lm_name)
        if not hasattr(tokenizer, 'is_fast') or not tokenizer.is_fast:
            if verbose:
                print(f"[LM警告] {lm_name} 不支持fast tokenizer，offsets映射可能不精确")
    random.seed(42)
    np.random.seed(42)

    def sample_contexts_for_terms(df, text_corpus, tokenizer, k=10, window_tokens=80):
        """基于 token 对齐采样上下文"""
        term_contexts = {}
        max_docs_per_term = min(50, len(text_corpus))
        for idx, row in df.iterrows():
            term = row['ngram_norm'] if 'ngram_norm' in row else row['term_norm']
            term_norm_list = term.split() if isinstance(term, str) else list(term) if isinstance(term, (tuple, list)) else [str(term)]
            
            term_ctxs = []
            doc_count = 0
            for doc_id, doc_text in text_corpus:
                if doc_count >= max_docs_per_term:
                    break
                if not doc_text:
                    continue
                doc_count += 1
                encoding = tokenizer(doc_text, return_offsets_mapping=True, add_special_tokens=True)
                token_ids = encoding['input_ids']
                offsets = encoding['offset_mapping']
                tokens = tokenizer.convert_ids_to_tokens(token_ids)
                
                matches = []
                for i in range(1, len(tokens) - len(term_norm_list)):
                    matched = True
                    for j, tgt_token in enumerate(term_norm_list):
                        if i + j >= len(tokens):
                            matched = False
                            break
                        token_at_pos = tokens[i + j].lower().replace('##', '').replace('▁', '').strip()
                        tgt_lower = str(tgt_token).lower().strip()
                        if token_at_pos != tgt_lower and not (token_at_pos.startswith(tgt_lower) or tgt_lower.startswith(token_at_pos)):
                            matched = False
                            break
                    if matched:
                        matches.append((i, i + len(term_norm_list)))
                
                if not matches:
                    continue
                
                samples = random.sample(matches, min(len(matches), max(1, k - len(term_ctxs))))
                for tok_start, tok_end in samples:
                    ctx_start = max(1, tok_start - window_tokens // 2)
                    ctx_end = min(len(token_ids) - 1, tok_end + window_tokens // 2)
                    ctx_token_ids = token_ids[ctx_start:ctx_end]
                    local_tok_start = tok_start - ctx_start
                    local_tok_end = tok_end - ctx_start
                    
                    term_ctxs.append((ctx_token_ids, local_tok_start, local_tok_end, doc_id))
                    if len(term_ctxs) >= k:
                        break
                if len(term_ctxs) >= k:
                    break
            
            term_contexts[str(term)] = term_ctxs
        
        return term_contexts

    def compute_plr_for_context(context_token_ids, token_start, token_end, tokenizer, model, device=None):
        device = device or next(model.parameters()).device
        cls_id = getattr(tokenizer, 'cls_token_id', None) or getattr(tokenizer, 'bos_token_id', None)
        sep_id = getattr(tokenizer, 'sep_token_id', None) or getattr(tokenizer, 'eos_token_id', None)
        base_input_ids = torch.tensor([cls_id] + context_token_ids + [sep_id], device=device)
        token_len = len(base_input_ids)
        
        adj_start = token_start + 1
        adj_end = token_end + 1
        
        if adj_start < 1 or adj_end > token_len or adj_start >= adj_end:
            return np.nan
        
        span_len = adj_end - adj_start
        if span_len <= 1:
            return np.nan
        
        ll_whole_list = []
        for i in range(adj_start, adj_end):
            if i >= token_len:
                break
            masked_ids = base_input_ids.clone()
            masked_ids[i] = tokenizer.mask_token_id
            with torch.no_grad():
                outputs = model(masked_ids.unsqueeze(0))
                logprobs = torch.log_softmax(outputs.logits, dim=-1)
                ll_whole_list.append(logprobs[0, i, base_input_ids[i]].item())
        
        pll_whole = np.mean(ll_whole_list) if ll_whole_list else -np.inf
        
        boundary_tokens = []
        for word in ["and", ",", "of", ".", "the"]:
            tokenized = tokenizer.encode(word, add_special_tokens=False)
            if tokenized:
                boundary_tokens.append(tokenized[0])
        
        if not boundary_tokens:
            return pll_whole
        
        pll_broken_candidates = []
        for break_pos in range(adj_start, adj_end):
            if break_pos >= token_len:
                continue
            for boundary_token_id in boundary_tokens[:2]:
                broken_ids = base_input_ids.tolist()
                broken_ids.insert(break_pos + 1, boundary_token_id)
                broken_input_ids = torch.tensor(broken_ids, device=device)
                broken_start = adj_start
                broken_end = adj_end + 1
                broken_span_len = broken_end - broken_start
                
                if broken_span_len <= 1 or broken_end > len(broken_input_ids):
                    continue
                
                ll_broken_list = []
                for i in range(broken_start, broken_end):
                    if i >= len(broken_input_ids):
                        break
                    masked_ids = broken_input_ids.clone()
                    masked_ids[i] = tokenizer.mask_token_id
                    with torch.no_grad():
                        outputs = model(masked_ids.unsqueeze(0))
                        logprobs = torch.log_softmax(outputs.logits, dim=-1)
                        ll_broken_list.append(logprobs[0, i, broken_input_ids[i]].item())
                
                if ll_broken_list:
                    pll_broken_candidates.append(np.mean(ll_broken_list))
        
        pll_broken = min(pll_broken_candidates) if pll_broken_candidates else -np.inf
        
        plr = pll_whole - pll_broken
        return plr

    def subword_cost(term, tokenizer):
        return len(tokenizer.tokenize(term))

    if verbose: print(f"[LM] 上下文采样（token流对齐）...")
    term_context_dict = sample_contexts_for_terms(
        df_candidates, text_corpus, tokenizer, k=k_contexts, window_tokens=window_size
    )
    def build_examples_for_term(ctx_list, max_k=5):
        if not ctx_list:
            return []
        picks = random.sample(ctx_list, min(max_k, len(ctx_list)))
        examples = []
        for ctx_token_ids, s, e, doc_id in picks:
            left = tokenizer.decode(ctx_token_ids[:max(0, s)])
            mid = tokenizer.decode(ctx_token_ids[max(0, s):max(0, e)])
            right = tokenizer.decode(ctx_token_ids[max(0, e):])
            snippet = f"{left}【{mid}】{right}".strip()
            examples.append(f"(doc={doc_id}) {snippet}")
        return examples
    term_examples_map = {term: build_examples_for_term(ctxs, max_k=5) for term, ctxs in term_context_dict.items()}
    all_plr_stats = []
    all_subword_cost = []

    BATCH = []
    idx_to_plr = {}
    for idx, row in df_candidates.iterrows():
        term = row['ngram_norm'] if 'ngram_norm' in row else row['term_norm']
        idx_to_plr[idx] = []
        ctxs = term_context_dict.get(str(term), [])
        
        for ctx_token_ids, tok_start, tok_end, doc_id in ctxs:
            BATCH.append((ctx_token_ids, tok_start, tok_end, idx))
            if len(BATCH) >= batch_size:
                batch_plrs = []
                for context_ids, s, e, batch_idx in BATCH:
                    plr = compute_plr_for_context(context_ids, s, e, tokenizer, model, device=LM_DEVICE)
                    batch_plrs.append((batch_idx, plr))
                for batch_idx, plr in batch_plrs:
                    idx_to_plr[batch_idx].append(plr)
                BATCH = []
    
    if BATCH:
        batch_plrs = []
        for context_ids, s, e, batch_idx in BATCH:
            plr = compute_plr_for_context(context_ids, s, e, tokenizer, model, device=LM_DEVICE)
            batch_plrs.append((batch_idx, plr))
        for batch_idx, plr in batch_plrs:
            idx_to_plr[batch_idx].append(plr)
    
    for idx, row in df_candidates.iterrows():
        term = row['ngram_norm'] if 'ngram_norm' in row else row['term_norm']
        all_plr_stats.append(idx_to_plr.get(idx, []))
        cost = subword_cost(str(term), tokenizer)
        all_subword_cost.append(cost)

    LM_p20 = [np.nanpercentile(scores, 20) if scores else np.nan for scores in all_plr_stats]
    LM_mean = [np.nanmean(scores) if scores else np.nan for scores in all_plr_stats]
    df_candidates = df_candidates.copy()
    df_candidates['LM_p20'] = LM_p20
    df_candidates['LM_mean'] = LM_mean
    df_candidates['subword_cost'] = all_subword_cost
    candidate_examples = []
    for idx, row in df_candidates.iterrows():
        term = row['ngram_norm'] if 'ngram_norm' in row else row['term_norm']
        exs = term_examples_map.get(str(term), [])
        if not exs:
            exs = []
        candidate_examples.append(exs[:5])
    df_candidates['example_contexts'] = candidate_examples

    actual_threshold = lm_p20_threshold
    if calibrate_threshold and len(df_candidates) >= calibration_sample_size:
        sample_df = df_candidates.sample(n=min(calibration_sample_size, len(df_candidates)), random_state=42)
        valid_p20 = [x for x in sample_df['LM_p20'] if not np.isnan(x)]
        if valid_p20:
            sample_median = np.median(valid_p20)
            actual_threshold = max(lm_p20_threshold, sample_median * 0.6)
            if verbose:
                print(f"[LM校准] 样本中位数: {sample_median:.2f}, 调整后阈值: {actual_threshold:.2f}")

    cost_max = 8
    LM_flag = []
    LM_reason = []
    for i, row in df_candidates.iterrows():
        if np.isnan(row['LM_p20']):
            LM_flag.append(False)
            LM_reason.append('无有效上下文')
        elif row['LM_p20'] < actual_threshold:
            LM_flag.append(False)
            LM_reason.append(f'低PLR_p20({row["LM_p20"]:.2f}<{actual_threshold:.2f})')
        elif row['subword_cost'] > cost_max:
            LM_flag.append(False)
            LM_reason.append('编码成本高')
        else:
            LM_flag.append(True)
            LM_reason.append('')
    df_candidates['LM_flag'] = LM_flag
    df_candidates['LM_reason'] = LM_reason
    if verbose:
        print(f"[LM] 验证通过率: {sum(LM_flag)}/{len(LM_flag)}, 使用阈值: {actual_threshold:.2f}")
    return df_candidates, model, tokenizer

def merge_term_variants(
    df_candidates, 
    number_placeholder="<num>", 
    topk_variant_examples=3,
    agg_LM_col='LM_p20',
    context_col_left="left_ctx_dist", 
    context_col_right="right_ctx_dist",
    return_variant_table=False
):
    """
    合并术语变体为概念簇。
    输入含 term_norm/term_raw/df/上下文/LM；输出 cluster_df。
    可选返回变体表。
    """

    term_norm_col = 'term_norm' if 'term_norm' in df_candidates.columns else 'ngram_norm'
    term_raw_col = 'term_raw' if 'term_raw' in df_candidates.columns else 'ngram_raw'
    
    def get_token_aligned_key(term):
        """
        生成按 token 位置对齐的 key，仅同位数字可合并。
        """
        tokens = str(term).lower().split()
        normalized_tokens = []
        for token in tokens:
            normalized_token = re.sub(r"\d+", number_placeholder, token)
            normalized_tokens.append(normalized_token)
        return tuple(normalized_tokens)
    
    num_group_map = defaultdict(list)
    for idx, row in df_candidates.iterrows():
        aligned_key = get_token_aligned_key(str(row[term_norm_col]))
        num_group_map[aligned_key].append(idx)

    clusters = []
    for aligned_key, idx_list in num_group_map.items():
        clusters.append(idx_list)

    cluster_items = []
    for cluster_i, idxs in enumerate(clusters):
        raw_vals = []
        for idx in idxs:
            raw_val = df_candidates.loc[idx, term_raw_col]
            if isinstance(raw_val, (tuple, list)):
                raw_vals.append(' '.join(str(x) for x in raw_val))
            else:
                raw_vals.append(str(raw_val))
        variants = Counter(raw_vals)
        variant_list = list(variants.most_common(topk_variant_examples))
        term_raw_top = variant_list[0][0] if variant_list else ""
        n_variants = len(variants)
        norm_forms = [str(df_candidates.loc[idx, term_norm_col]).lower() for idx in idxs]
        term_norm = Counter(norm_forms).most_common(1)[0][0]
        all_doc_ids = set()
        if 'doc_ids' in df_candidates.columns:
            for idx in idxs:
                docids = df_candidates.loc[idx, 'doc_ids']
                if isinstance(docids, (list, set)):
                    all_doc_ids.update(docids)
                elif isinstance(docids, str):
                    parsed = json.loads(docids)
                    if isinstance(parsed, (list, set)):
                        all_doc_ids.update(parsed)
        elif 'df' in df_candidates.columns:
            raise RuntimeError("缺少 doc_ids 列，无法进行变体级文献集合并去重")
        else:
            raise RuntimeError("候选缺少必要列 doc_ids/df，无法计算 df_merged")
        all_df = len(all_doc_ids) if all_doc_ids else 0

        merged_left_ctx = Counter()
        merged_right_ctx = Counter()
        for idx in idxs:
            left = df_candidates.loc[idx, context_col_left]
            right = df_candidates.loc[idx, context_col_right]
            if isinstance(left, dict):
                merged_left_ctx.update(left)
            if isinstance(right, dict):
                merged_right_ctx.update(right)
        def calc_entropy(counter):
            total = sum(counter.values())
            if total == 0: return 0.0
            probs = [v/total for v in counter.values() if v > 0]
            return -sum(p * np.log(p) for p in probs if p > 0)
        H_left_merged = calc_entropy(merged_left_ctx)
        H_right_merged = calc_entropy(merged_right_ctx)

        def aggregate_values(col_name, idxs):
            vals = [df_candidates.loc[idx, col_name] for idx in idxs if col_name in df_candidates.columns and not pd.isna(df_candidates.loc[idx, col_name])]
            if not vals:
                return np.nan
            return np.nanpercentile(vals, 20) if len(vals) > 2 else np.nanmean(vals)
        
        LM_agg = aggregate_values(agg_LM_col, idxs)
        minPMI_agg = aggregate_values('minPMI', idxs)

        example_contexts = []
        if 'example_contexts' in df_candidates.columns:
            ctx_lists = [df_candidates.loc[idx, 'example_contexts'] for idx in idxs if isinstance(df_candidates.loc[idx, 'example_contexts'], list)]
            flat_ctx = []
            for lst in ctx_lists:
                flat_ctx.extend([c for c in lst if isinstance(c, str)])
            seen = set()
            dedup = []
            for c in flat_ctx:
                if c not in seen:
                    seen.add(c)
                    dedup.append(c)
                if len(dedup) >= 5:
                    break
            example_contexts = dedup
        elif 'example_context' in df_candidates.columns:
            contexts = [df_candidates.loc[idx, 'example_context'] for idx in idxs if isinstance(df_candidates.loc[idx, 'example_context'], str)]
            example_contexts = contexts[:5]

        cluster_items.append({
            "term_norm": term_norm,
            "term_raw_top": term_raw_top,
            "variants": n_variants,
            "variant_forms": [v[0] for v in variant_list],
            "df_merged": all_df,
            "H_left_merged": H_left_merged,
            "H_right_merged": H_right_merged,
            "LM_agg": LM_agg,
            "minPMI_agg": minPMI_agg,
            "example_contexts": example_contexts
        })

    cluster_df = pd.DataFrame(cluster_items, columns=[
        "term_norm", "term_raw_top", "variants",
        "variant_forms", "df_merged",
        "H_left_merged", "H_right_merged", "LM_agg", "minPMI_agg",
        "example_contexts"
    ]).sort_values(by="df_merged", ascending=False).reset_index(drop=True)

    if return_variant_table:
        variant2cid = {}
        for cid, idxs in enumerate(clusters):
            for idx in idxs:
                variant2cid[idx] = cid
        variant_table = df_candidates.copy()
        variant_table['concept_cluster_id'] = variant_table.index.map(lambda idx: variant2cid.get(idx, -1))
        return cluster_df, variant_table

    return cluster_df

def rank_and_score_candidates(
    cluster_df,
    lm_col="LM_agg",
    boundary_cols=("H_left_merged", "H_right_merged"),
    cohesion_col="minPMI_agg",
    rarity_col="df_merged",  # 稀有度本质同df倒排
    context_col="example_contexts",
    weights=None,
    t_high=0.75,
    t_low=0.5,
    minmax_score=True,
    n_contexts=5
):
    """
    对合并候选综合打分并分区（通过/灰区/否决）。
    输入需含 term_norm/df_merged/边界/凝聚/LM/示例上下文。
    返回加入 score 与 rank_zone 的结果表。
    """
    df = cluster_df.copy()

    LM = df[lm_col].astype('float').replace([np.inf, -np.inf], np.nan)
    if len(boundary_cols) == 2:
        Bound = df[list(boundary_cols)].min(axis=1)
    else:
        Bound = df[boundary_cols[0]].astype('float').replace([np.inf, -np.inf], np.nan)
    if cohesion_col not in df.columns:
        raise RuntimeError(f"缺少凝聚度列 {cohesion_col}，请确保在 merge_term_variants 中已聚合 minPMI_agg")
    Cohesion = df[cohesion_col].astype('float').replace([np.inf, -np.inf], np.nan)
    Rarity = -np.log1p(df[rarity_col].astype('float').replace([np.inf, -np.inf], np.nan))

    for arr in [LM, Bound, Cohesion, Rarity]:
        arr.fillna(0, inplace=True)

    def minmax_norm(x):
        if x.max() == x.min(): return np.zeros_like(x)
        return (x - x.min()) / (x.max() - x.min())
    def zscore(x):
        m, s = x.mean(), x.std()
        return (x - m) / (s if s > 0 else 1)

    if minmax_score:
        LM_std = minmax_norm(LM)
        Bound_std = minmax_norm(Bound)
        Cohesion_std = minmax_norm(Cohesion)
        Rarity_std = minmax_norm(Rarity)
    else:
        LM_std = zscore(LM)
        Bound_std = zscore(Bound)
        Cohesion_std = zscore(Cohesion)
        Rarity_std = zscore(Rarity)

    if weights is None:
        weights = {'lm': 0.40, 'boundary': 0.25, 'cohesion': 0.20, 'rarity': 0.15}
    score = (
        weights['lm'] * LM_std +
        weights['boundary'] * Bound_std +
        weights['cohesion'] * Cohesion_std +
        weights['rarity'] * Rarity_std
    )
    df["score"] = score

    df["rank_zone"] = np.select(
        [df['score'] >= t_high, df['score'] >= t_low],
        ['通过区', '灰区'],
        default='否决区'
    )
    df = df.sort_values(by="score", ascending=False).reset_index(drop=True)

    result = pd.DataFrame({
        "term_raw_top": df["term_raw_top"],
        "term_norm": df["term_norm"],
        "df": df["df_merged"],
        "variants": df["variants"],
        "variant_forms": df["variant_forms"],
        "H_left": df[boundary_cols[0]],
        "H_right": df[boundary_cols[1]],
        lm_col: LM,
        "score": df["score"],
        "rank_zone": df["rank_zone"],
        "example_contexts": df[context_col].apply(lambda x: x[:n_contexts] if isinstance(x, list) else [])
    })
    if "minPMI" in df.columns:
        result["minPMI"] = df["minPMI"]
    if "minPMI_agg" in df.columns:
        result["minPMI_agg"] = df["minPMI_agg"]
    if "t_score" in df.columns:
        result["t_score"] = df["t_score"]
    result["rarity"] = Rarity

    return result

os.makedirs(config['temp_dir'], exist_ok=True)
PROGRESS_FILE = os.path.join(config['temp_dir'], 'progress.pkl')
GLOBAL_STATS_FILE = os.path.join(config['temp_dir'], 'global_stats.pkl')
LM_STATUS_FILE = os.path.join(config['temp_dir'], 'lm_status.pkl')
CALIB_DOCS_FILE = os.path.join('artifacts', 'calibration_doc_ids.txt')

def save_progress(chunk_idx, global_stats):
    with open(PROGRESS_FILE, 'wb') as f:
        pickle.dump(chunk_idx, f)
    with open(GLOBAL_STATS_FILE, 'wb') as f:
        pickle.dump(global_stats, f, protocol=pickle.HIGHEST_PROTOCOL)

def load_progress():
    if os.path.exists(PROGRESS_FILE) and os.path.exists(GLOBAL_STATS_FILE):
        with open(PROGRESS_FILE, 'rb') as f:
            chunk_idx = pickle.load(f)
        with open(GLOBAL_STATS_FILE, 'rb') as f:
            global_stats = pickle.load(f)
        print(f"[断点续跑] 从第 {chunk_idx + 1} 块继续处理...")
        return chunk_idx + 1, global_stats
    return 0, {}

def load_lm_status():
    if os.path.exists(LM_STATUS_FILE):
        with open(LM_STATUS_FILE, 'rb') as f:
            return pickle.load(f) or {}
    return {}

def save_lm_status(status):
    with open(LM_STATUS_FILE, 'wb') as f:
        pickle.dump(status, f, protocol=pickle.HIGHEST_PROTOCOL)

def _deserialize_val(x):
    if isinstance(x, str):
        return json.loads(x)
    return x

def _intersects_docids(docids, calib_ids):
    if isinstance(docids, (list, set, tuple)):
        for d in docids:
            if str(d) in calib_ids:
                return True
    elif isinstance(docids, str):
        parsed = json.loads(docids)
        if isinstance(parsed, (list, set, tuple)):
            for d in parsed:
                if str(d) in calib_ids:
                    return True
    return False

def serialize_object_columns(df):
    df_copy = df.copy()
    for col in df_copy.columns:
        if df_copy[col].dtype == 'object':
            def serialize_val(x):
                if isinstance(x, dict):
                    converted_dict = {}
                    for k, v in x.items():
                        if isinstance(k, (np.integer, np.floating)):
                            k = k.item()
                        elif not isinstance(k, (str, int, float, bool)) and k is not None:
                            k = str(k)
                        if isinstance(v, (np.integer, np.floating)):
                            v = v.item()
                        converted_dict[k] = v
                    return json.dumps(converted_dict)
                elif isinstance(x, (list, set, tuple)):
                    converted_list = []
                    for item in x:
                        if isinstance(item, (np.integer, np.floating)):
                            item = item.item()
                        converted_list.append(item)
                    return json.dumps(converted_list)
                return x
            df_copy[col] = df_copy[col].apply(serialize_val)
    return df_copy

def deserialize_object_columns(df):
    df_copy = df.copy()
    # for col in df_copy.columns:
    #     if df_copy[col].dtype == 'object':
    #         df_copy[col] = df_copy[col].apply(_deserialize_val)
    return df_copy

def _norm_key(row):
    key = row['ngram_norm'] if 'ngram_norm' in row else (row['term_norm'] if 'term_norm' in row else None)
    if key is None:
        return None
    if isinstance(key, (list, tuple)):
        return ' '.join(map(str, key))
    return str(key)

def select_for_lm(df_candidates, lm_status, df_change_ratio=0.2):
    if df_candidates is None or df_candidates.empty:
        return df_candidates, df_candidates
    keys = df_candidates.apply(_norm_key, axis=1)
    df_candidates = df_candidates.copy()
    df_candidates['__key__'] = keys
    need_mask = []
    for _, r in df_candidates.iterrows():
        k = r['__key__']
        if not k:
            need_mask.append(True)
            continue
        st = lm_status.get(k)
        if st is None:
            need_mask.append(True)
            continue
        old_df = st.get('df', 0)
        new_df = float(r.get('df', 0))
        denom = old_df if old_df > 0 else 1.0
        rel = abs(new_df - old_df) / denom
        old_lm = st.get('LM_p20', None)
        cross = (old_lm is None) or (1.3 <= old_lm <= 1.7)
        need_mask.append(rel >= df_change_ratio or cross)
    need_mask = np.array(need_mask, dtype=bool)
    need_lm_df = df_candidates.loc[need_mask].drop(columns=['__key__'])
    no_lm_df = df_candidates.loc[~need_mask].drop(columns=['__key__'])
    return need_lm_df, no_lm_df

def run_acceptance_checks(cluster_df, merge_result, combined_pool, weights_meta, thresholds_meta, lm_name, code_hash):
    report = {'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    checks = []
    def add(name, status, details=""):
        checks.append({'name': name, 'status': status, 'details': details})
    required_cols = [
        'term_norm','term_raw_top','df','variants','variant_forms',
        'H_left','H_right','score','rank_zone'
    ]
    missing = [c for c in required_cols if c not in cluster_df.columns]
    if missing:
        add('fields_integrity','FAIL',f"missing: {missing}")
    else:
        add('fields_integrity','PASS','')
    if isinstance(merge_result, pd.DataFrame) and not merge_result.empty:
        recomputed = rank_and_score_candidates(
            merge_result,
            lm_col="LM_agg",
            boundary_cols=("H_left_merged","H_right_merged"),
            cohesion_col="minPMI_agg",
            rarity_col="df_merged",
            context_col="example_contexts",
            weights=None,
            t_high=thresholds_meta.get('t_high',0.75),
            t_low=thresholds_meta.get('t_low',0.5),
            minmax_score=True,
            n_contexts=5
        )
        k = min(100, len(cluster_df), len(recomputed))
        ok_order = list(cluster_df.head(k)['term_norm']) == list(recomputed.head(k)['term_norm'])
        ok_scores = np.allclose(
            np.array(cluster_df.head(k)['score'], dtype=float),
            np.array(recomputed.head(k)['score'], dtype=float),
            rtol=1e-8, atol=1e-10
        ) if k>0 else True
        add('metric_reproducible', 'PASS' if (ok_order and ok_scores) else 'FAIL', '')
    else:
        add('metric_reproducible','WARN','no merge_result to recompute')
    if isinstance(combined_pool, pd.DataFrame) and not combined_pool.empty and 'doc_ids' in combined_pool.columns and 'df' in combined_pool.columns:
        sample = combined_pool.sample(n=min(200, len(combined_pool)), random_state=42)
        bad = 0
        for _, r in sample.iterrows():
            docids = r['doc_ids']
            expected = len(set(docids)) if isinstance(docids,(list,set,tuple)) else None
            if expected is None or int(r['df']) != int(expected):
                bad += 1
        add('df_dedup_consistency', 'PASS' if bad==0 else 'FAIL', f"violations={bad}")
    else:
        add('df_dedup_consistency','WARN','insufficient columns')
    if isinstance(combined_pool, pd.DataFrame) and not combined_pool.empty and 'ngram_raw' in combined_pool.columns and 'n' in combined_pool.columns:
        sub = combined_pool[combined_pool['n']==1]
        cnt = 0
        total = len(sub)
        if total>0:
            for x in sub['ngram_raw'].head(min(5000,total)):
                s = ' '.join(x) if isinstance(x,(list,tuple)) else str(x)
                if re.search(COMPOUND_PATTERN, s) is not None:
                    cnt += 1
            ratio = (cnt/max(1,total))*100.0
            add('token_protection_proxy','PASS' if ratio>=0.5 else 'WARN', f"ratio={ratio:.2f}%")
        else:
            add('token_protection_proxy','WARN','no unigram subset')
    else:
        add('token_protection_proxy','WARN','insufficient columns')
    base_path = os.path.join('artifacts','baseline_leaderboard.parquet')
    if os.path.exists(base_path):
        base_df = pd.read_parquet(base_path)
        base_df = deserialize_object_columns(base_df)
    else:
        base_df = None
    if base_df is not None and isinstance(combined_pool, pd.DataFrame) and not combined_pool.empty and 'doc_ids' in combined_pool.columns:
        calib_ids = None
        if os.path.exists(CALIB_DOCS_FILE):
            with open(CALIB_DOCS_FILE,'r',encoding='utf-8') as f:
                calib_ids = set(x.strip() for x in f if x.strip())
        if calib_ids:
            calib_pool = combined_pool[combined_pool['doc_ids'].apply(lambda x: _intersects_docids(x, calib_ids))]
            if not calib_pool.empty:
                calib_merge = merge_term_variants(
                    calib_pool,
                    number_placeholder="<num>",
                    topk_variant_examples=3,
                    agg_LM_col='LM_p20',
                    context_col_left="left_ctx_dist",
                    context_col_right="right_ctx_dist",
                    return_variant_table=False
                )
                if not calib_merge.empty:
                    calib_board = rank_and_score_candidates(
                        calib_merge,
                        lm_col="LM_agg",
                        boundary_cols=("H_left_merged","H_right_merged"),
                        cohesion_col="minPMI_agg",
                        rarity_col="df_merged",
                        context_col="example_contexts",
                        weights=None,
                        t_high=thresholds_meta.get('t_high',0.75),
                        t_low=thresholds_meta.get('t_low',0.5),
                        minmax_score=True,
                        n_contexts=5
                    )
                    k = min(100,len(base_df),len(calib_board))
                    ok = list(base_df.head(k)['term_norm']) == list(calib_board.head(k)['term_norm'])
                    add('lm_stability_calibration','PASS' if ok else 'FAIL','')
                else:
                    add('lm_stability_calibration','WARN','empty calib_merge')
            else:
                add('lm_stability_calibration','WARN','empty calib_pool')
        else:
            add('lm_stability_calibration','WARN','no calibration ids')
    else:
        add('lm_stability_calibration','WARN','no baseline to compare')
    bad = 0
    sample = cluster_df.sample(n=min(100, len(cluster_df)), random_state=42) if len(cluster_df)>0 else cluster_df
    for _, r in sample.iterrows():
        vf = r.get('variant_forms', [])
        top = r.get('term_raw_top', '')
        if not isinstance(vf,(list,tuple,set)) or len(vf)==0:
            bad += 1
            continue
        if top not in set(vf):
            bad += 1
    add('merge_correctness','PASS' if bad==0 else 'FAIL', f"violations={bad}")
    if isinstance(combined_pool, pd.DataFrame) and not combined_pool.empty and 'doc_ids' in combined_pool.columns:
        ok = all(isinstance(x,(list,set,tuple)) for x in combined_pool['doc_ids'].head(min(1000,len(combined_pool))))
        add('bos_eos_proxy','PASS' if ok else 'FAIL','')
    else:
        add('bos_eos_proxy','WARN','insufficient columns')
    report['checks'] = checks
    report['meta'] = {
        'weights': weights_meta,
        'thresholds': thresholds_meta,
        'model_name': lm_name,
        'code_version': code_hash
    }
    os.makedirs('artifacts', exist_ok=True)
    with open(os.path.join('artifacts','acceptance_report.json'),'w',encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    for c in checks:
        print(f"[验收] {c['name']}: {c['status']} {(' - ' + c['details']) if c.get('details') else ''}")

# ========== 1. 加载进度和初始化全局统计 ==========
start_chunk, global_stats = load_progress()

if not global_stats:
    global_stats = {
        'df_unigram': Counter(),
        'df_ngram': Counter(),
        'text_corpus': [],
        'all_doc_ids': set(),
        'token_vocab': {},
        'token_id_counter': 1
    }
else:
    global_stats['df_unigram'] = Counter(global_stats.get('df_unigram', {}))
    global_stats['df_ngram'] = Counter(global_stats.get('df_ngram', {}))
    global_stats.setdefault('text_corpus', [])
    all_doc_ids = global_stats.get('all_doc_ids', set())
    if not isinstance(all_doc_ids, set):
        global_stats['all_doc_ids'] = set(all_doc_ids) if all_doc_ids else set()
    global_stats.setdefault('token_vocab', {})
    global_stats.setdefault('token_id_counter', 1)

function_words = set(FUNCTION_WORDS)

lm_model = None
lm_tokenizer = None
lm_name = "allenai/scibert_scivocab_uncased"

all_chunk_ngram_tables = []

# ========== 2. 逐块处理论文数据 ==========
for chunk_idx, chunk_df in enumerate(read_and_merge_info(config)):
    if chunk_idx < start_chunk:
        continue
    print(f"\n=== 处理第 {chunk_idx} 块 ===")
    
    # 2.1 清理HTML标签和保留英文内容
    chunk_df = clean_merged_info(chunk_df)
    chunk_df = filter_english_after_clean(chunk_df)
    
    # 2.2 构建文本语料库用于语言模型评估
    text_corpus_chunk = [(row[config['unique_id_column']], str(row['merged_info'])) 
                         for _, row in chunk_df.iterrows()]
    global_stats['text_corpus'].extend(text_corpus_chunk)
    
    # 2.3 分词并统一词形
    tokens_df = tokenize_and_normalize_fast(
        chunk_df, 
        text_col='merged_info', 
        doc_id_col=config['unique_id_column']
    )
    
    num_processes = config.get('num_processes', 4)
    ngram_range = config.get('ngram_range', (2, 5))
    print(f"[配置] ngram_range = {ngram_range}")
    min_ngram_df = config.get('min_ngram_df', 1)
    temp_dir = config.get('temp_dir', 'temp')
    os.makedirs(temp_dir, exist_ok=True)

    # 2.4 提取短语频率和上下文分布
    if len(tokens_df) > 0:
        # 2.4.1 分配数据到各进程
        tokens_df['__proc_hash__'] = tokens_df['doc_id'].astype(str).map(
            lambda x: int(hashlib.md5(x.encode()).hexdigest(), 16) % num_processes
        )
        proc_groups = tokens_df.groupby('__proc_hash__')
        token_norm_to_raw = tokens_df.drop_duplicates(subset=['token_norm'], keep='first').set_index('token_norm')['token_raw'].astype(str).to_dict()
        token_mapping_path = os.path.join(temp_dir, f"chunk{chunk_idx}_token_mapping.pkl")
        with open(token_mapping_path, 'wb') as f:
            pickle.dump(token_norm_to_raw, f)
        del token_norm_to_raw
        gc.collect()
        
        tokens_df_path = os.path.join(temp_dir, f"chunk{chunk_idx}_tokens_df.parquet")
        tokens_df.to_parquet(tokens_df_path, index=False, engine="pyarrow")
        
        worker_args = []
        for proc_id in range(num_processes):
            if proc_id in proc_groups.groups:
                subset_df = tokens_df.loc[proc_groups.groups[proc_id]].copy()
                subset_df = subset_df.drop('__proc_hash__', axis=1)
                temp_path = os.path.join(temp_dir, f"chunk{chunk_idx}_proc{proc_id}.parquet")
                subset_df.to_parquet(temp_path, index=False, engine="pyarrow")
                worker_args.append((temp_path, chunk_idx, proc_id, ngram_range, min_ngram_df, temp_dir))
        del tokens_df
        gc.collect()
        def _extract_ngram_stats_worker_safe(args):
            parquet_path, chunk_idx, proc_id, ngram_range, min_ngram_df, temp_dir = args
            df = pd.read_parquet(parquet_path)
            result = _extract_ngram_stats_worker((df, chunk_idx, proc_id, ngram_range, min_ngram_df))
            if len(result) == 3:
                local_token_vocab, proc_id_result, _ = result
                result = (local_token_vocab, proc_id_result)
            del df
            gc.collect()
            vocab_file_path = os.path.join(temp_dir, f"chunk{chunk_idx}_proc{proc_id}_vocab.pkl")
            with open(vocab_file_path, 'wb') as f:
                pickle.dump(result[0], f)
            
            import time
            time.sleep(0.1)
            temp_dir_norm = os.path.normpath(temp_dir)
            if proc_id == 0:
                shard_files = []
                for shard_idx in range(int(config.get('num_shards', 512))):
                    pattern = os.path.join(temp_dir_norm, f'shard_{shard_idx}_chunk_{chunk_idx}_proc_{proc_id}*.parquet')
                    pattern = os.path.normpath(pattern)
                    matched = glob.glob(pattern)
                    shard_files.extend(matched)
            
            return (vocab_file_path, proc_id)

        if worker_args:
            # 2.4.2 并行统计各进程的短语频次
            print(f"[提取Ngram] 开始并行处理 {len(worker_args)} 个进程...")
            results = Parallel(n_jobs=num_processes, prefer='processes')(
                delayed(_extract_ngram_stats_worker_safe)(args) for args in tqdm(worker_args, desc="提取Ngram统计", disable=False)
            )
            
            vocab_list = []
            proc_id_list = []
            vocab_file_paths = []
            for vocab_file_path, proc_id in results:
                with open(vocab_file_path, 'rb') as f:
                    vocab_list.append(pickle.load(f))
                vocab_file_paths.append(vocab_file_path)
                proc_id_list.append(proc_id)
            # 2.4.3 统一词汇表ID映射
            merged_vocab, updated_counter, remap_dicts = _merge_token_vocabs(
                vocab_list, global_stats['token_id_counter']
            )
            del vocab_list
            gc.collect()

            global_stats['token_vocab'].update(merged_vocab)
            global_stats['token_id_counter'] = updated_counter
            num_shards = int(config.get('num_shards', 512))
            remap_args = [(temp_dir, chunk_idx, proc_id, remap_dict, num_shards) 
                         for proc_id, remap_dict in zip(proc_id_list, remap_dicts)]
            Parallel(n_jobs=num_processes, prefer='processes')(
                delayed(_remap_token_ids_in_files)(*args) for args in tqdm(remap_args, desc="重映射Token ID", disable=False)
            )

            token_id_to_norm = {v: k for k, v in merged_vocab.items()}
            token_id_to_norm[0] = '<BOS>'
            token_mapping_path = os.path.join(temp_dir, f"chunk{chunk_idx}_token_mapping.pkl")
            token_id_to_raw = {}
            if os.path.exists(token_mapping_path):
                with open(token_mapping_path, 'rb') as f:
                    token_norm_to_raw = pickle.load(f)
                token_id_to_raw = {merged_vocab.get(norm, -1): raw for norm, raw in token_norm_to_raw.items() if norm in merged_vocab}
                token_id_to_raw[-1] = '<UNK>'
                token_id_to_raw[0] = '<BOS>'
            else:
                token_id_to_raw = {}

            # 2.4.4 聚合各分片结果并保留高频候选
            memory_threshold_mb = int(config.get('shard_memory_threshold_mb', 500))
            max_token_id = max(merged_vocab.values()) if merged_vocab else 1000000
            topk = config.get('max_ngrams_per_n')
            ngram_table = None
            
            def _merge_shard_worker(args):
                shard_idx, chunk_idx, token_id_to_norm, proc_id_list, num_shards, memory_threshold_mb, temp_dir, max_token_id = args
                processor = ShardedNgramProcessor(
                    num_shards=num_shards,
                    memory_threshold_mb=memory_threshold_mb,
                    temp_dir=temp_dir,
                    max_token_id=max_token_id + 1000
                )
                files_found = []
                temp_dir_norm = os.path.normpath(temp_dir)
                for proc_id in proc_id_list:
                    pattern = os.path.join(temp_dir_norm, f'shard_{shard_idx}_chunk_{chunk_idx}_proc_{proc_id}*.parquet')
                    pattern = os.path.normpath(pattern)
                    matched_files = glob.glob(pattern)
                    if not matched_files:
                        exact_pattern = os.path.join(temp_dir_norm, f'shard_{shard_idx}_chunk_{chunk_idx}_proc_{proc_id}.parquet')
                        exact_pattern = os.path.normpath(exact_pattern)
                        if os.path.exists(exact_pattern):
                            matched_files = [exact_pattern]
                    files_found.extend(matched_files)
                    if shard_idx == 0:
                        exact_path = os.path.join(temp_dir_norm, f'shard_{shard_idx}_chunk_{chunk_idx}_proc_{proc_id}.parquet')
                        exact_path = os.path.normpath(exact_path)
                        exists = os.path.exists(exact_path)
                result = processor.merge_shard_files(shard_idx, chunk_idx, token_id_to_norm, proc_id_list)
                return result if result is not None and not result.empty else None
            
            merge_args = [
                (shard_idx, chunk_idx, token_id_to_norm, proc_id_list, num_shards, memory_threshold_mb, temp_dir, max_token_id)
                for shard_idx in range(num_shards)
            ]
            print(f"[合并分片] 开始合并 {len(merge_args)} 个分片...")
            with Parallel(n_jobs=num_processes, prefer='processes', max_nbytes=None, pre_dispatch='all') as parallel:
                merge_results = parallel(
                    delayed(_merge_shard_worker)(args) for args in tqdm(merge_args, desc="合并分片", disable=False)
                )
            
            processor = ShardedNgramProcessor(
                num_shards=num_shards,
                memory_threshold_mb=memory_threshold_mb,
                temp_dir=temp_dir
            )
            
            topk_store = {}
            non_empty_count = 0
            empty_count = 0
            none_count = 0
            for result in merge_results:
                if result is not None:
                    if not result.empty:
                        non_empty_count += 1
                        _update_topk_store(topk_store, result, topk=topk, min_df=min_ngram_df)
                    else:
                        empty_count += 1
                    del result
                else:
                    none_count += 1
            gc.collect()

            if topk_store:
                ngram_table = pd.concat(list(topk_store.values()), ignore_index=True)
            else:
                ngram_table = pd.DataFrame(columns=[
                    'ngram_norm', 'ngram_raw', 'ngram_id_tuple', 'ngram_norm_tuple', 'n', 'df',
                    'left_ctx_dist', 'right_ctx_dist'
                ])

            # 2.4.5 释放临时资源
            for proc_id in proc_id_list:
                processor.cleanup_shard_files(chunk_idx, proc_id)
                parquet_path = os.path.join(temp_dir, f"chunk{chunk_idx}_proc{proc_id}.parquet")
                if os.path.exists(parquet_path):
                    os.remove(parquet_path)
            for vocab_file_path in vocab_file_paths:
                if os.path.exists(vocab_file_path):
                    os.remove(vocab_file_path)

            # 2.4.6 按最小文档频率过滤并还原原始词形
            ngram_table = ngram_table.loc[ngram_table['df'] >= min_ngram_df].copy()

            if not ngram_table.empty:
                ngram_table = _fill_ngram_raw_optimized(ngram_table, token_id_to_raw, ngram_id_tuple_col='ngram_id_tuple')
                if os.path.exists(token_mapping_path):
                    os.remove(token_mapping_path)
            else:
                ngram_table['ngram_raw'] = None
        else:
            ngram_table = pd.DataFrame(columns=[
                'ngram_norm', 'ngram_raw', 'ngram_id_tuple', 'ngram_norm_tuple', 'n', 'df',
                'left_ctx_dist', 'right_ctx_dist'
            ])
    else:
        ngram_table = pd.DataFrame(columns=[
            'ngram_norm', 'ngram_raw', 'ngram_id_tuple', 'ngram_norm_tuple', 'n', 'df',
            'left_ctx_dist', 'right_ctx_dist'
        ])

    # 2.5 提取单字复合词（如"COVID-19"）
    
    tokens_df_path = os.path.join(temp_dir, f"chunk{chunk_idx}_tokens_df.parquet")
    if os.path.exists(tokens_df_path):
        tokens_df = pd.read_parquet(tokens_df_path)
        os.remove(tokens_df_path)
    else:
        tokens_df = pd.DataFrame()
    
    if len(tokens_df) > 0:
        unigram_compound_table = extract_unigram_compound_stats(tokens_df)
        if not unigram_compound_table.empty:
            token_norm_to_id = global_stats['token_vocab']
            
            if 'ngram_id_tuple' not in unigram_compound_table.columns:
                def norm_tuple_to_id_tuple(norm_tuple):
                    if isinstance(norm_tuple, (list, tuple)):
                        return tuple(token_norm_to_id.get(norm, -1) for norm in norm_tuple)
                    else:
                        return (token_norm_to_id.get(norm_tuple, -1),)
                unigram_compound_table['ngram_id_tuple'] = unigram_compound_table['ngram_norm_tuple'].apply(norm_tuple_to_id_tuple)
            
            if 'doc_ids' in unigram_compound_table.columns:
                unigram_compound_table['doc_ids'] = unigram_compound_table['doc_ids'].apply(lambda x: list(x) if isinstance(x, set) else x)
            
            if 'left_ctx_dist' in unigram_compound_table.columns:
                def convert_ctx_keys(ctx_dict):
                    if not isinstance(ctx_dict, dict):
                        return {}
                    return {token_norm_to_id.get(k, -1) if k != '<OTHER>' else -1: v for k, v in ctx_dict.items()}
                unigram_compound_table['left_ctx_dist'] = unigram_compound_table['left_ctx_dist'].apply(convert_ctx_keys)
            
            if 'right_ctx_dist' in unigram_compound_table.columns:
                def convert_ctx_keys(ctx_dict):
                    if not isinstance(ctx_dict, dict):
                        return {}
                    return {token_norm_to_id.get(k, -1) if k != '<OTHER>' else -1: v for k, v in ctx_dict.items()}
                unigram_compound_table['right_ctx_dist'] = unigram_compound_table['right_ctx_dist'].apply(convert_ctx_keys)
            
            ngram_table_cols = ngram_table.columns.tolist()
            for col in ngram_table_cols:
                if col not in unigram_compound_table.columns:
                    if col == 'doc_ids':
                        unigram_compound_table['doc_ids'] = [[]] * len(unigram_compound_table)
                    else:
                        unigram_compound_table[col] = None
            
            unigram_compound_table = unigram_compound_table[ngram_table_cols]
            
            ngram_table = ngram_table.copy()
            unigram_compound_table = unigram_compound_table.copy()
            ngram_table.index = range(len(ngram_table))
            unigram_compound_table.index = range(len(ngram_table), len(ngram_table) + len(unigram_compound_table))
            ngram_table = pd.concat([ngram_table, unigram_compound_table], axis=0)
            ngram_table = ngram_table.reset_index(drop=True)
        
        # 2.6 累计单字和短语的文档频率
        unigram_doc_counts = tokens_df.groupby('token_norm')['doc_id'].nunique().to_dict()
        for token_norm, df_count in unigram_doc_counts.items():
            global_stats['df_unigram'][token_norm] += df_count
        
        chunk_doc_ids = set(tokens_df['doc_id'].unique())
        global_stats.setdefault('all_doc_ids', set())
        global_stats['all_doc_ids'].update(chunk_doc_ids)
    
    if not ngram_table.empty:
        for _, row in ngram_table.iterrows():
            ngram_tuple = row['ngram_norm_tuple']
            if isinstance(ngram_tuple, (list, np.ndarray)):
                ngram_tuple = tuple(ngram_tuple)
            global_stats['df_ngram'][ngram_tuple] += int(row['df'])
    
    del tokens_df
    gc.collect()
    need_cols = [
        'ngram_norm', 'ngram_raw', 'ngram_norm_tuple', 'n', 'df',
        'left_ctx_dist', 'right_ctx_dist', 'doc_ids'
    ]
    cols_exist = [c for c in need_cols if c in ngram_table.columns]
    all_chunk_ngram_tables.append(ngram_table[cols_exist].copy())

    # 2.7 检查点保存
    save_progress(chunk_idx, global_stats)
    print(f"[保存进度] 已完成第 {chunk_idx} 块")
    
    # # 测试模式：只处理一块数据
    # print(f"[测试模式] 仅处理一块数据进行测试，现在跳出循环进入最终结果生成")
    # break

# ========== 3. 计算全局阈值（df95和总文档数） ==========
print("[步骤3] 开始计算全局阈值...")
if not global_stats['df_ngram']:
    raise RuntimeError("global_stats['df_ngram'] 为空，无法计算全局 df95，请先完成全库统计后重试")
global_df_values = np.array(list(global_stats['df_ngram'].values()))
if len(global_df_values) == 0:
    raise RuntimeError("global df_ngram 值数组为空，无法计算 df95，请检查统计流程")
print(f"[步骤3] 计算df95中，共有 {len(global_df_values)} 个ngram...")
df95 = float(np.percentile(global_df_values, 95))
print(f"[步骤3] df95 = {df95:.2f}")

total_docs = len(global_stats.get('all_doc_ids', set()))
if total_docs <= 0:
    raise RuntimeError("total_docs 为 0，无法计算PMI/熵/稀有度，请检查输入数据与统计流程")
print(f"[步骤3] 总文档数 = {total_docs}")

# ========== 4. 生成校准文档集（1%随机采样） ==========
if not os.path.exists(CALIB_DOCS_FILE):
    os.makedirs('artifacts', exist_ok=True)
    all_ids = list(global_stats.get('all_doc_ids', set()))
    if all_ids:
        random.seed(42)
        k = max(1, int(0.01 * len(all_ids)))
        sample_ids = random.sample(all_ids, k=k)
        with open(CALIB_DOCS_FILE, 'w', encoding='utf-8') as f:
            for did in sample_ids:
                f.write(str(did) + "\n")
        print(f"[校准集] 已保存 {len(sample_ids)} 个 doc_id 至 {CALIB_DOCS_FILE}")

# ========== 5. 合并所有块的候选并计算创新指标 ==========
print("[步骤5] 开始合并所有块的候选词汇...")
if not all_chunk_ngram_tables:
    raise RuntimeError("未收集到任何候选ngram_table，无法进入离线指标阶段")

print(f"[步骤5] 合并 {len(all_chunk_ngram_tables)} 个块的ngram_table...")
all_candidates = pd.concat(all_chunk_ngram_tables, ignore_index=True)
print(f"[步骤5] 合并完成，共有 {len(all_candidates)} 个候选词汇")

print(f"[步骤5] 开始计算创新指标（PMI、熵、稀有度等），这可能需要一些时间...")
all_candidates = compute_ngram_metrics_fast(
    all_candidates,
    dict(global_stats['df_unigram']),
    dict(global_stats['df_ngram']),
    df95,
    function_words,
    total_docs=total_docs
)
print(f"[步骤5] 创新指标计算完成")

# ========== 6. 初步筛选：分为通过区和灰区 ==========
print("[步骤6] 开始初步筛选候选词汇（通过区/灰区）...")
if not all_candidates.empty:
    # 打印候选分布统计
    print(f"[步骤6] 候选分布统计:")
    print(f"  - 总候选数: {len(all_candidates)}")
    if 'n' in all_candidates.columns:
        n_counts = all_candidates['n'].value_counts().sort_index()
        print(f"  - N-gram分布: {dict(n_counts)}")
    if 'df' in all_candidates.columns:
        print(f"  - 文档频率(df)范围: {all_candidates['df'].min():.0f} ~ {all_candidates['df'].max():.0f}, 中位数: {all_candidates['df'].median():.0f}")
    if 'minPMI' in all_candidates.columns:
        print(f"  - minPMI范围: {all_candidates['minPMI'].min():.2f} ~ {all_candidates['minPMI'].max():.2f}, 中位数: {all_candidates['minPMI'].median():.2f}")
    if 'H_left' in all_candidates.columns and 'H_right' in all_candidates.columns:
        print(f"  - 左熵(H_left)范围: {all_candidates['H_left'].min():.2f} ~ {all_candidates['H_left'].max():.2f}, 中位数: {all_candidates['H_left'].median():.2f}")
        print(f"  - 右熵(H_right)范围: {all_candidates['H_right'].min():.2f} ~ {all_candidates['H_right'].max():.2f}, 中位数: {all_candidates['H_right'].median():.2f}")
    
    # 质量导向的阈值计算：结合固定质量标准和数据规模自适应
    # df阈值：基于总文档数的比例（质量标准），但随数据规模适当调整
    # PMI阈值：使用绝对质量标准，不随分布变化
    # 熵阈值：使用绝对质量标准
    # 避免固定分位数带来的"筛选比例固定"问题
    base_df_ratio = 0.001
    base_pmi_absolute = 2.0
    base_entropy_absolute = 1.0
    
    quality_factors = {1: 0.5, 2: 1.0, 3: 1.5, 4: 2.0, 5: 2.5}
    thresholds = {}
    
    for n_val in sorted(all_candidates['n'].unique()):
        subset = all_candidates[all_candidates['n'] == n_val]
        if len(subset) > 0:
            df_median = subset['df'].median()
            df_max = subset['df'].max()
            base_df = max(1, int(total_docs * base_df_ratio * quality_factors.get(n_val, 1.0)))
            
            if df_median < base_df * 0.5:
                df_thresh = max(1, int(df_median * 0.8))
            elif df_max < base_df:
                df_thresh = max(1, int(df_max * 0.6))
            else:
                df_thresh = base_df
            
            pmi_median = subset['minPMI'].median()
            pmi_thresh = max(base_pmi_absolute * quality_factors.get(n_val, 1.0) * 0.8, 
                            pmi_median * 0.7 if pmi_median > 0 else base_pmi_absolute)
            
            thresholds[n_val] = {
                'df': df_thresh,
                'pmi': pmi_thresh
            }
    
    entropy_values = np.concatenate([all_candidates['H_left'].values, all_candidates['H_right'].values])
    entropy_values = entropy_values[~np.isnan(entropy_values)]
    entropy_median = np.median(entropy_values) if len(entropy_values) > 0 else base_entropy_absolute
    entropy_thresh = max(base_entropy_absolute, entropy_median * 0.7)
    
    quality_min_df = {n: thresholds[n]['df'] for n in thresholds}
    quality_minPMI = {n: thresholds[n]['pmi'] for n in thresholds}
    quality_min_entropy = entropy_thresh
    
    # 固定阈值作为对比
    fixed_min_df_threshold = {1:5000, 2:3000, 3:800, 4:200, 5:80}
    fixed_minPMI_threshold = {1: 0, 2: 3.5, 3: 4.5, 4: 5.0, 5: 5.5}
    fixed_min_entropy = 1.5
    
    print(f"[步骤6] 筛选阈值设置:")
    print(f"  - 质量导向阈值（基于质量标准，非固定分位数）:")
    print(f"    * min_df_threshold: {quality_min_df}")
    print(f"    * minPMI_threshold: {quality_minPMI}")
    print(f"    * min_entropy: {quality_min_entropy:.2f}")
    print(f"    * 说明: df阈值基于总文档数比例+数据稀疏性自适应，PMI/熵使用绝对质量标准")
    print(f"  - 固定阈值（默认值，仅作对比）:")
    print(f"    * min_df_threshold: {fixed_min_df_threshold}")
    print(f"    * minPMI_threshold: {fixed_minPMI_threshold}")
    print(f"    * min_entropy: {fixed_min_entropy}")
    
    # 使用质量导向阈值进行筛选
    through_pool, grey_pool = prefilter_ngram_candidates(
        all_candidates,
        min_df_threshold=quality_min_df,
        minPMI_threshold=quality_minPMI,
        min_entropy=quality_min_entropy
    )
else:
    through_pool = pd.DataFrame()
    grey_pool = pd.DataFrame()

print(f"[步骤6] 筛选完成：通过区 {len(through_pool)} 个，灰区 {len(grey_pool)} 个")

# ========== 7. 语言模型评估创新性 ==========
print("[步骤7] 开始语言模型评估创新性...")
combined_pool_parts = []
# 7.1 评估通过区候选的创新性
if not through_pool.empty:
    print(f"[步骤7.1] 评估通过区候选（{len(through_pool)} 个），这可能需要较长时间...")
    lm_status = load_lm_status()
    need_lm_df, no_lm_df = select_for_lm(through_pool.copy(), lm_status, df_change_ratio=0.2)
    filled_no_lm = None
    if no_lm_df is not None and not no_lm_df.empty:
        vals = []
        for _, r in no_lm_df.iterrows():
            k = _norm_key(r)
            st = lm_status.get(k, {}) if k else {}
            vals.append(st.get('LM_p20', np.nan))
        no_lm_df = no_lm_df.copy()
        no_lm_df['LM_p20'] = vals
        no_lm_df['LM_mean'] = np.nan
        no_lm_df['subword_cost'] = np.nan
        no_lm_df['LM_flag'] = no_lm_df['LM_p20'].apply(lambda x: False if pd.isna(x) else (x >= 1.5))
        no_lm_df['LM_reason'] = no_lm_df['LM_p20'].apply(lambda x: '沿用历史' if not pd.isna(x) else '无历史')
        filled_no_lm = no_lm_df
    evaluated = []
    if need_lm_df is not None and not need_lm_df.empty:
        need_lm_df, lm_model, lm_tokenizer = lm_validate_candidates(
            need_lm_df,
            global_stats['text_corpus'],
            k_contexts=5,
            window_size=80,
            batch_size=32,
            lm_name=lm_name,
            device=None,
            verbose=True,
            model=lm_model,
            tokenizer=lm_tokenizer,
            lm_p20_threshold=1.5,
            calibrate_threshold=(start_chunk == 0),
            calibration_sample_size=5
        )
        if not need_lm_df.empty:
            need_lm_df = need_lm_df.reset_index(drop=True)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              
            evaluated.append(need_lm_df)
            for _, r in need_lm_df.iterrows():
                k = _norm_key(r)
                if not k:
                    continue
                lm_status[k] = {'df': float(r.get('df', 0)), 'LM_p20': float(r.get('LM_p20', np.nan))}
    if filled_no_lm is not None and not filled_no_lm.empty:
        evaluated.append(filled_no_lm)
    if evaluated:
        cleaned_evaluated = []
        for i, df in enumerate(evaluated):
            if df.columns.duplicated().any():
                df = df.loc[:, ~df.columns.duplicated()]
            cleaned_evaluated.append(df)
        through_pool = pd.concat(cleaned_evaluated, ignore_index=True)
    else:
        through_pool = pd.DataFrame()
    if not through_pool.empty:
        through_pool = through_pool.reset_index(drop=True)
        combined_pool_parts.append(through_pool)
    save_lm_status(lm_status)
    print(f"[步骤7.1] 通过区评估完成")

# 7.2 评估灰区候选的创新性（仅前1000个）
grey_pool_head_size = min(1000, len(grey_pool)) if not grey_pool.empty else 0
if grey_pool_head_size > 0:
    print(f"[步骤7.2] 评估灰区候选（前 {grey_pool_head_size} 个）...")
    grey_pool_head = grey_pool.head(grey_pool_head_size).copy()
    lm_status = load_lm_status()
    need_lm_df, no_lm_df = select_for_lm(grey_pool_head, lm_status, df_change_ratio=0.2)
    filled_no_lm = None
    if no_lm_df is not None and not no_lm_df.empty:
        vals = []
        for _, r in no_lm_df.iterrows():
            k = _norm_key(r)
            st = lm_status.get(k, {}) if k else {}
            vals.append(st.get('LM_p20', np.nan))
        no_lm_df = no_lm_df.copy()
        no_lm_df['LM_p20'] = vals
        no_lm_df['LM_mean'] = np.nan
        no_lm_df['subword_cost'] = np.nan
        no_lm_df['LM_flag'] = no_lm_df['LM_p20'].apply(lambda x: False if pd.isna(x) else (x >= 1.5))
        no_lm_df['LM_reason'] = no_lm_df['LM_p20'].apply(lambda x: '沿用历史' if not pd.isna(x) else '无历史')
        filled_no_lm = no_lm_df
    evaluated = []
    if need_lm_df is not None and not need_lm_df.empty:
        need_lm_df, lm_model, lm_tokenizer = lm_validate_candidates(
            need_lm_df,
            global_stats['text_corpus'],
            k_contexts=5,
            window_size=80,
            batch_size=32,
            lm_name=lm_name,
            device=None,
            verbose=True,
            model=lm_model,
            tokenizer=lm_tokenizer,
            lm_p20_threshold=1.5,
            calibrate_threshold=False
        )
        if not need_lm_df.empty:
            evaluated.append(need_lm_df)
            for _, r in need_lm_df.iterrows():
                k = _norm_key(r)
                if not k:
                    continue
                lm_status[k] = {'df': float(r.get('df', 0)), 'LM_p20': float(r.get('LM_p20', np.nan))}
    if filled_no_lm is not None and not filled_no_lm.empty:
        evaluated.append(filled_no_lm)
    if evaluated:
        cleaned_evaluated = []
        for i, df in enumerate(evaluated):
            if df.columns.duplicated().any():
                df = df.loc[:, ~df.columns.duplicated()]
            cleaned_evaluated.append(df)
        grey_pool_head = pd.concat(cleaned_evaluated, ignore_index=True)
    else:
        grey_pool_head = pd.DataFrame()
    if not grey_pool_head.empty:
        if 'LM_flag' in grey_pool_head.columns:
            grey_pool_head = grey_pool_head.loc[grey_pool_head['LM_flag'] == True].reset_index(drop=True)
        if not grey_pool_head.empty:
            combined_pool_parts.append(grey_pool_head)
    save_lm_status(lm_status)
    print(f"[步骤7.2] 灰区评估完成")

if combined_pool_parts:
    print(f"[步骤7] 合并评估结果...")
    combined_pool = pd.concat(combined_pool_parts, ignore_index=True)
    print(f"[步骤7] 语言模型评估完成，共有 {len(combined_pool)} 个候选")
else:
    combined_pool = pd.DataFrame()
    print(f"[步骤7] 语言模型评估完成，但无有效候选")

# ========== 8. 合并变体形式并生成最终排行榜 ==========
print("[步骤8] 开始合并变体形式并生成最终排行榜...")
merge_result = None
# 8.1 合并同一术语的不同变体（如"deep-learning"和"deep learning"）
if not combined_pool.empty:
    print(f"[步骤8.1] 合并变体形式（{len(combined_pool)} 个候选）...")
    merge_result = merge_term_variants(
        combined_pool,
        number_placeholder="<num>",
        topk_variant_examples=3,
        agg_LM_col='LM_p20',
        context_col_left="left_ctx_dist",
        context_col_right="right_ctx_dist",
        return_variant_table=False
    )
    print(f"[步骤8.1] 合并完成，共有 {len(merge_result)} 个合并后的术语")
    if not merge_result.empty:
        # 8.2 计算综合创新得分并排序
        print("[步骤8.2] 计算综合创新得分并排序...")
        cluster_df = rank_and_score_candidates(
            merge_result,
            lm_col="LM_agg",
            boundary_cols=("H_left_merged", "H_right_merged"),
            cohesion_col="minPMI_agg",
            rarity_col="df_merged",
            context_col="example_contexts",
            weights=None,
            t_high=0.75,
            t_low=0.5,
            minmax_score=True,
            n_contexts=5
        )
        print(f"[步骤8.2] 排序完成")
        print(f"[结果] 通过区: {len(cluster_df[cluster_df['rank_zone']=='通过区'])}, "
              f"灰区: {len(cluster_df[cluster_df['rank_zone']=='灰区'])}, "
              f"否决区: {len(cluster_df[cluster_df['rank_zone']=='否决区'])}")
        # 8.3 保存最终创新词汇排行榜
        print("[步骤8.3] 保存最终创新词汇排行榜...")
        os.makedirs('results', exist_ok=True)
        os.makedirs('artifacts', exist_ok=True)
        prev_parquet = os.path.join('results', '创新词汇排行榜.parquet')
        prev_df = None
        if os.path.exists(prev_parquet):
            prev_df = pd.read_parquet(prev_parquet)
            prev_df = deserialize_object_columns(prev_df)
            reverse_mapping = {
                '标准词汇': 'term_norm',
                '常用形式': 'term_raw_top',
                '综合得分': 'score',
                '评级': 'rank_zone',
                '文档频率': 'df',
                '变体数': 'variants',
                '变体列表': 'variant_forms',
                '语言模型得分': 'LM_agg',
                '左边界熵': 'H_left',
                '右边界熵': 'H_right',
                '凝聚度': 'minPMI_agg',
                '稀有度': 'rarity',
                '示例上下文': 'example_contexts'
            }
            prev_df = prev_df.rename(columns=reverse_mapping)
        
        column_mapping = {
            'term_norm': '标准词汇',
            'term_raw_top': '常用形式',
            'score': '综合得分',
            'rank_zone': '评级',
            'df': '文档频率',
            'variants': '变体数',
            'variant_forms': '变体列表',
            'LM_agg': '语言模型得分',
            'H_left': '左边界熵',
            'H_right': '右边界熵',
            'minPMI_agg': '凝聚度',
            'rarity': '稀有度',
            'example_contexts': '示例上下文'
        }
        column_order = ['标准词汇', '常用形式', '综合得分', '评级', 
                       '文档频率', '变体数', '变体列表',
                       '语言模型得分', '左边界熵', '右边界熵', '凝聚度', '稀有度',
                       '示例上下文']
        
        cluster_df_cn = cluster_df.rename(columns=column_mapping)
        available_cols = [col for col in column_order if col in cluster_df_cn.columns]
        cluster_df_cn = cluster_df_cn[available_cols]
        
        final_csv = os.path.join('results', '创新词汇排行榜.csv')
        final_parquet = os.path.join('results', '创新词汇排行榜.parquet')
        cluster_df_serialized = serialize_object_columns(cluster_df_cn)
        cluster_df_serialized.to_csv(final_csv, index=False)
        cluster_df_serialized.to_parquet(final_parquet, index=False)
        print(f"[步骤8.3] 已保存最终排行榜: {final_csv}, {final_parquet}")
        
        # 8.4 生成校准集的基准排行榜
        calib_ids = None
        if os.path.exists(CALIB_DOCS_FILE):
            with open(CALIB_DOCS_FILE, 'r', encoding='utf-8') as f:
                calib_ids = set(x.strip() for x in f if x.strip())
        if calib_ids and not combined_pool.empty and 'doc_ids' in combined_pool.columns:
            calib_pool = combined_pool[combined_pool['doc_ids'].apply(lambda x: _intersects_docids(x, calib_ids))]
            if not calib_pool.empty:
                calib_merge = merge_term_variants(
                    calib_pool,
                    number_placeholder="<num>",
                    topk_variant_examples=3,
                    agg_LM_col='LM_p20',
                    context_col_left="left_ctx_dist",
                    context_col_right="right_ctx_dist",
                    return_variant_table=False
                )
                if not calib_merge.empty:
                    calib_board = rank_and_score_candidates(
                        calib_merge,
                        lm_col="LM_agg",
                        boundary_cols=("H_left_merged", "H_right_merged"),
                        cohesion_col="minPMI_agg",
                        rarity_col="df_merged",
                        context_col="example_contexts",
                        weights=None,
                        t_high=0.75,
                        t_low=0.5,
                        minmax_score=True,
                        n_contexts=5
                    )
                    calib_parquet = os.path.join('results', '校准集基准排行榜.parquet')
                    calib_board_serialized = serialize_object_columns(calib_board)
                    calib_board_serialized.to_parquet(calib_parquet, index=False)
        # 8.5 对比上次结果生成变更日志
        if prev_df is not None and not prev_df.empty:
            curr = cluster_df.reset_index().rename(columns={'index': 'new_rank'})
            prev = prev_df.reset_index().rename(columns={'index': 'old_rank'})
            curr['new_rank'] = curr['new_rank'].astype(int)
            prev['old_rank'] = prev['old_rank'].astype(int)
            curr_key = curr.set_index('term_norm')[['new_rank', 'rank_zone', 'variant_forms']]
            prev_key = prev.set_index('term_norm')[['old_rank', 'rank_zone', 'variant_forms']]
            added_keys = sorted(set(curr_key.index) - set(prev_key.index))
            added = [{'term_norm': k, 'new_rank': int(curr_key.loc[k, 'new_rank']), 'rank_zone': curr_key.loc[k, 'rank_zone']} for k in added_keys]
            common = sorted(set(curr_key.index) & set(prev_key.index))
            rank_changes = []
            merge_changes = []
            for k in common:
                old_r = int(prev_key.loc[k, 'old_rank'])
                new_r = int(curr_key.loc[k, 'new_rank'])
                old_zone = str(prev_key.loc[k, 'rank_zone'])
                new_zone = str(curr_key.loc[k, 'rank_zone'])
                if (old_r != new_r) or (old_zone != new_zone):
                    rank_changes.append({
                        'term_norm': k,
                        'old_rank': old_r,
                        'new_rank': new_r,
                        'delta': old_r - new_r,
                        'old_zone': old_zone,
                        'new_zone': new_zone
                    })
                old_vs = set(prev_key.loc[k, 'variant_forms']) if isinstance(prev_key.loc[k, 'variant_forms'], (list, set, tuple)) else set()
                new_vs = set(curr_key.loc[k, 'variant_forms']) if isinstance(curr_key.loc[k, 'variant_forms'], (list, set, tuple)) else set()
                if old_vs != new_vs:
                    merge_changes.append({
                        'term_norm': k,
                        'old_size': int(len(old_vs)),
                        'new_size': int(len(new_vs)),
                        'added_forms': sorted(list(new_vs - old_vs))[:20],
                        'removed_forms': sorted(list(old_vs - new_vs))[:20]
                    })
            changelog = {
                'added': added,
                'rank_changes': rank_changes,
                'merge_changes': merge_changes
            }
            with open(os.path.join('artifacts', 'changelog.json'), 'w', encoding='utf-8') as f:
                json.dump(changelog, f, ensure_ascii=False, indent=2)
        # 8.6 生成元数据和质量验收报告
        fw_sorted = sorted(FUNCTION_WORDS)
        fw_bytes = ('\n'.join(fw_sorted)).encode('utf-8')
        function_words_hash = hashlib.sha256(fw_bytes).hexdigest()
        with open(__file__, 'rb') as f:
            code_bytes = f.read()
        code_hash = hashlib.sha256(code_bytes).hexdigest()
        weights_meta = {'lm': 0.40, 'boundary': 0.25, 'cohesion': 0.20, 'rarity': 0.15}
        thresholds_meta = {'t_high': 0.75, 't_low': 0.5, 'lm_p20_threshold': 1.5}
        zone_counts = {
            'pass': int((cluster_df['rank_zone'] == '通过区').sum()),
            'grey': int((cluster_df['rank_zone'] == '灰区').sum()),
            'reject': int((cluster_df['rank_zone'] == '否决区').sum()),
            'total': int(len(cluster_df))
        }
        metadata = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'model_name': lm_name,
            'weights': weights_meta,
            'thresholds': thresholds_meta,
            'function_words_hash': function_words_hash,
            'code_version': code_hash,
            'row_counts': zone_counts
        }
        with open(os.path.join('artifacts', 'metadata.json'), 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        run_acceptance_checks(
            cluster_df=cluster_df,
            merge_result=merge_result,
            combined_pool=combined_pool,
            weights_meta=weights_meta,
            thresholds_meta=thresholds_meta,
            lm_name=lm_name,
            code_hash=code_hash
        )
        print("[保存] results/ 已生成: 创新词汇排行榜.csv/.parquet, 校准集基准排行榜.parquet(若有)")
        print("[保存] artifacts/ 已生成: metadata.json, acceptance_report.json, changelog.json(若有), calibration_doc_ids.txt")
        print("\n" + "="*70)
        print("[✅] 所有步骤已完成！")
        print("    最终结果: results/")
        print("    元数据和质量报告: artifacts/")
        print("="*70)
else:
    print("[⚠️] 警告: combined_pool 为空，无法生成最终排行榜")