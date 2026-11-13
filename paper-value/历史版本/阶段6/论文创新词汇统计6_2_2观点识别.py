import os
import re
import json
import time
import sqlite3
import zlib
import threading
import queue
import struct
from pathlib import Path
from collections import OrderedDict, defaultdict
from functools import lru_cache

import numpy as np
import pandas as pd
import torch
import faiss
import spacy
import yake
from sentence_transformers import SentenceTransformer, CrossEncoder
from fastcoref import FCoref

try:
    import xxhash
except ImportError:
    xxhash = None
    print("Warning: xxhash not available, using fallback hash")

try:
    import msgpack
except ImportError:
    msgpack = None
    print("Warning: msgpack not available, using json fallback")

try:
    import lmdb
except ImportError:
    lmdb = None
    print("Warning: lmdb not available, meta will use Python dict")

try:
    from pybloom_live import BloomFilter
    HAS_PYBLOOM = True
except ImportError:
    HAS_PYBLOOM = False
    BloomFilter = None

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

# 流式参数
CHUNK_SIZE = 50_000
PAPERS_PER_MICROBATCH = 2000
CHECKPOINT_EVERY_MICROBATCH = 5
CHECKPOINT_EVERY_SECONDS = 120
DB_WRITE_BATCH_SIZE = 10000

# 嵌入/缓存
EMB_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_BATCH_SIZE = 8192
EMBED_CACHE_SIZE = 800_000
SQLITE_CACHE_PATH = str(OUTPUT_DIR / "embed_cache.sqlite")
LMDB_META_PATH = str(OUTPUT_DIR / "opinion_meta.lmdb")
RAW_EMBEDDING_PATH = str(OUTPUT_DIR / "raw_embeddings.lmdb")
SQLITE_BATCH_SIZE = 10000

# 候选与筛选
N_TOP_CANDIDATES = 20
CLUSTER_THRESHOLD = 0.80
ALIAS_LIMIT = 20
FAISS_SEARCH_K = 3

# 自适应阈值参数
ADAPTIVE_THRESHOLD_PERCENTILE = 90  # 分位数（90%表示90%分位数）
ADAPTIVE_THRESHOLD_MIN = 0.75  # 最小阈值（防止过低）
ADAPTIVE_THRESHOLD_MAX = 0.95  # 最大阈值（防止过高）

# YAKE
YAKE_DEDUP_FUNC = "jaro"
YAKE_DEDUP_LIM = 0.9
YAKE_TOP = 15
YAKE_MAX_CHARS = 1500
YAKE_MAX_WINDOWS = 4
YAKE_WINDOW_SIZE = 2
YAKE_PER_WINDOW_TOP = 3

# spaCy
SPACY_BATCH_SIZE = 1024
SPACY_N_PROCESS = 1

# FAISS索引
USE_HNSW = True
HNSW_M = 16
HNSW_EF_SEARCH = 64
HNSW_EF_CONSTRUCTION = 64

# 哈希去重
USE_HASH_DEDUP = True
HASH_SET_SIZE = 100_000

# Bloom Filter
USE_BLOOM_FILTER = True
BLOOM_CAPACITY = 10_000_000
BLOOM_ERROR_RATE = 0.001

# LMDB元数据
USE_LMDB_META = True if lmdb else False
LMDB_META_CACHE_SIZE = 100_000

# 原始向量存储
RAW_EMBEDDING_MAP_SIZE = 100 * 1024 * 1024 * 1024

# 向量压缩
USE_VECTOR_COMPRESSION = True
COMPRESSION_METHOD = "PCA"
COMPRESSED_DIM = 256
PCA_TRAIN_SAMPLES = 100_000
ENABLE_PCA_AT_OPINIONS = 1_000_000
ENABLE_PQ_AT_OPINIONS = 5_000_000
TRAIN_PCA_IN_SAVE = False

OPINION_STOPWORDS_FILE = "config/opinion_stopwords.txt"
_OPINION_STOPWORDS = None

def load_opinion_stopwords():
    global _OPINION_STOPWORDS
    if _OPINION_STOPWORDS is None:
        _OPINION_STOPWORDS = set()
        try:
            with open(OPINION_STOPWORDS_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        _OPINION_STOPWORDS.add(normalize_text(line))
        except FileNotFoundError:
            print(f"Warning: {OPINION_STOPWORDS_FILE} not found, using empty stopwords")
    return _OPINION_STOPWORDS

def is_opinion_stopword(phrase: str) -> bool:
    stopwords = load_opinion_stopwords()
    n = normalize_text_cached(phrase)
    return n in stopwords


class SimpleBloomFilter:
    def __init__(self, capacity, error_rate):
        import math
        self.capacity = capacity
        self.error_rate = error_rate
        self.bit_array_size = int(-capacity * math.log(error_rate) / (math.log(2) ** 2))
        self.hash_count = int(math.ceil(math.log(2) * self.bit_array_size / capacity))
        self.bit_array = bytearray((self.bit_array_size + 7) // 8)
        self.count = 0
    
    def _hash(self, item, seed):
        if xxhash:
            return xxhash.xxh64(item.encode('utf-8'), seed=seed).intdigest()
        else:
            import hashlib
            return int(hashlib.md5((str(seed) + item).encode()).hexdigest(), 16)
    
    def add(self, item):
        for i in range(self.hash_count):
            h = self._hash(item, i) % self.bit_array_size
            byte_idx = h // 8
            bit_idx = h % 8
            self.bit_array[byte_idx] |= (1 << bit_idx)
        self.count += 1
    
    def __contains__(self, item):
        for i in range(self.hash_count):
            h = self._hash(item, i) % self.bit_array_size
            byte_idx = h // 8
            bit_idx = h % 8
            if not (self.bit_array[byte_idx] & (1 << bit_idx)):
                return False
        return True

class RawEmbeddingStore:
    def __init__(self, path: str, dim: int, map_size_bytes: int = 10 * 1024 * 1024 * 1024):
        """原始向量存储"""
        self.dim = dim
        self.path = Path(path)
        self.enabled = bool(lmdb)
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.env = lmdb.open(str(self.path), map_size=map_size_bytes, subdir=False, writemap=False, lock=True)
        else:
            print("Warning: lmdb not available, RawEmbeddingStore falling back to in-memory cache")
            self.env = None
            self._store = {}

    def put(self, cid: int, vector: np.ndarray):
        vec = np.asarray(vector, dtype='float32')
        if vec.ndim != 1 or vec.shape[0] != self.dim:
            raise ValueError(f"RawEmbeddingStore.put expects shape ({self.dim},), got {vec.shape}")
        if self.enabled:
            key = struct.pack('>Q', cid)
            data = vec.tobytes()
            with self.env.begin(write=True) as txn:
                txn.put(key, data)
        else:
            self._store[cid] = vec.copy()

    def get(self, cid: int):
        if self.enabled:
            key = struct.pack('>Q', cid)
            with self.env.begin() as txn:
                data = txn.get(key)
                if data is None:
                    return None
                return np.frombuffer(data, dtype='float32').copy()
        else:
            val = self._store.get(cid)
            return val.copy() if val is not None else None

    def iterate(self):
        if self.enabled:
            with self.env.begin() as txn:
                cursor = txn.cursor()
                for key, value in cursor:
                    cid = struct.unpack('>Q', key)[0]
                    yield cid, np.frombuffer(value, dtype='float32').copy()
        else:
            for cid, vec in self._store.items():
                yield cid, vec.copy()

    def count(self):
        if self.enabled:
            with self.env.begin() as txn:
                stat = txn.stat()
                return stat.get('entries', 0)
        return len(self._store)

    def close(self):
        if self.enabled and self.env is not None:
            self.env.close()

def normalize_text(t: str):
    return re.sub(r'\s+', ' ', (t or '').lower().strip().replace('-', ' '))

@lru_cache(maxsize=200_000)
def normalize_text_cached(t: str):
    return normalize_text(t)

# 泛用短语模式
GENERIC_RE = [re.compile(p, re.IGNORECASE) for p in [
    r"^this (paper|study|work|research)$",
    r"^our (method|approach|algorithm)$",
    r"^(novel|new|effective|efficient) (method|approach|algorithm)$",
    r"^(results?|experiments?|conclusion)$",
    r"^(introduction|related work|future work)$",
    r"^(analysis|evaluation|comparison)$",
]]

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

def adaptive_threshold(phrase: str, base=CLUSTER_THRESHOLD):
    n_tok = len(normalize_text_cached(phrase).split())
    if n_tok <= 2: return min(0.92, base + 0.07)
    if n_tok >= 6: return max(0.75, base - 0.05)
    return base

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
            if HAS_PYBLOOM:
                self.bloom = BloomFilter(capacity=BLOOM_CAPACITY, error_rate=BLOOM_ERROR_RATE)
            else:
                self.bloom = SimpleBloomFilter(capacity=BLOOM_CAPACITY, error_rate=BLOOM_ERROR_RATE)
            self._load_bloom_from_sqlite(limit=min(100000, BLOOM_CAPACITY // 2))
        
        self.write_queue = queue.Queue(maxsize=10000)
        self.write_thread = threading.Thread(target=self._write_worker, daemon=True)
        self.write_thread.start()
        self._shutdown = False
        self._shutdown_lock = threading.Lock()
    
    def _load_bloom_from_sqlite(self, limit=None):
        """从SQLite加载已有key到Bloom Filter"""
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
        """如果Bloom Filter接近容量，重建它"""
        if not self.bloom or self.bloom_count < self.bloom_rebuild_threshold:
            return
        
        print(f"Bloom Filter接近容量 ({self.bloom_count}/{BLOOM_CAPACITY}), rebuilding...")
        if HAS_PYBLOOM:
            self.bloom = BloomFilter(capacity=BLOOM_CAPACITY, error_rate=BLOOM_ERROR_RATE)
        else:
            self.bloom = SimpleBloomFilter(capacity=BLOOM_CAPACITY, error_rate=BLOOM_ERROR_RATE)
        try:
            cur = self.conn.execute("SELECT k FROM emb ORDER BY rowid DESC LIMIT ?", (BLOOM_CAPACITY // 2,))
            count = 0
            for row in cur:
                self.bloom.add(row[0])
                count += 1
            self.bloom_count = count
        except Exception as e:
            print(f"Warning: Failed to rebuild Bloom Filter: {e}")

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
                print(f"Write worker error: {e}")
                import traceback
                traceback.print_exc()
                for _ in batch:
                    self.write_queue.task_done()
                batch = []

    def _write_batch_safe(self, batch):
        try:
            self.conn.executemany("INSERT OR REPLACE INTO emb(k,v) VALUES(?,?)", batch)
            self.conn.commit()
        except Exception as e:
            print(f"SQLite write error: {e}")
            import traceback
            traceback.print_exc()

    def get(self, key_norm: str):
        self.total += 1
        
        with self._lock:
            if key_norm in self.store:
                self.store.move_to_end(key_norm)
                self.hits += 1
                return self.store[key_norm]
        
        if self.bloom and key_norm not in self.bloom:
            return None
        
        try:
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
        except Exception as e:
            print(f"SQLite read error: {e}")
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
        try:
            self.write_queue.put((key_norm, blob), block=True, timeout=5.0)
        except queue.Full:
            print("Warning: SQLite write queue full after timeout, skipping cache write")
        except Exception as e:
            print(f"Warning: Failed to enqueue cache write: {e}")

    def flush(self):
        if not self.write_thread.is_alive():
            print("Warning: Write thread is not alive during flush")
            return
        
        timeout = 30.0
        start_time = time.time()
        while self.write_queue.unfinished_tasks > 0:
            if time.time() - start_time > timeout:
                remaining_items = self.write_queue.qsize()
                unfinished = self.write_queue.unfinished_tasks
                print(f"Warning: Flush timeout after {timeout}s, {unfinished} tasks still unfinished, {remaining_items} items in queue")
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
            try:
                self.write_queue.put_nowait(None)
                shutdown_sent = True
            except queue.Full:
                self.write_queue.put(None, block=True, timeout=None)
                shutdown_sent = True
        except Exception as e:
            print(f"Warning: Failed to send shutdown signal: {e}")
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
                    print(f"Warning: Synchronously wrote {len(remaining_batch)} remaining items")
        
        if self.write_thread.is_alive():
            self.write_thread.join(timeout=10.0)
            if self.write_thread.is_alive():
                print("Warning: Write thread did not exit within timeout")
        
        try:
            if hasattr(self, 'conn') and self.conn:
                self.conn.close()
        except Exception as e:
            print(f"Warning: Error closing SQLite connection: {e}")
    
    def __del__(self):
        if not self._shutdown:
            self.close()



_microbatch_hash_lru = OrderedDict()
_microbatch_hash_lock = threading.Lock()

def reset_microbatch_hash_set():
    global _microbatch_hash_lru
    with _microbatch_hash_lock:
        _microbatch_hash_lru.clear()

def _get_hash(text):
    normalized = normalize_text(text)
    if xxhash:
        return xxhash.xxh64(normalized.encode('utf-8')).intdigest()
    return hash(normalized)

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
                print(f"Warning: Insufficient memory for full PCA training ({estimated_memory_mb:.1f}MB needed, {available_memory_mb:.1f}MB available)")
                print(f"  Using random sampling: {len(vectors)} -> {max_samples} samples")
                indices = np.random.choice(len(vectors), size=max_samples, replace=False)
                vectors = vectors[indices]
        
        self.mean = vectors.mean(axis=0)
        centered = vectors - self.mean
        
        try:
            U, s, Vt = np.linalg.svd(centered, full_matrices=False)
        except MemoryError:
            print("Error: Out of memory during SVD, trying incremental PCA...")
            max_samples = min(10000, len(vectors))
            if max_samples < len(vectors):
                indices = np.random.choice(len(vectors), size=max_samples, replace=False)
                vectors = vectors[indices]
                self.mean = vectors.mean(axis=0)
                centered = vectors - self.mean
                U, s, Vt = np.linalg.svd(centered, full_matrices=False)
            else:
                raise
        
        self.components = Vt[:self.compressed_dim].T
        self.trained = True
    
    def _get_available_memory_mb(self):
        try:
            import psutil
            return psutil.virtual_memory().available / (1024 * 1024)
        except ImportError:
            return 8192
    
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
            try:
                with self.lmdb_env.begin() as txn:
                    return txn.stat()['entries']
            except Exception as e:
                print(f"Warning: Failed to get meta count from LMDB: {e}")
                return 0
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
            print("Warning: No raw_store available, skipping flush")
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
            print(f"Error: Index dimension mismatch ({self.index.d} vs {vecs.shape[1]})")
            print("  Triggering index rebuild to fix dimension mismatch...")
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
                            print(f"  Reinserted {len(raw_ids_array)} vectors after rebuild")
                        else:
                            print(f"  Warning: Dimension still mismatch after rebuild ({self.index.d} vs {compressed_vecs.shape[1]}), vectors saved in raw_store but not indexed")
                    else:
                        print(f"  Warning: Compressor lost after rebuild, vectors saved in raw_store but not indexed")
                else:
                    print(f"  Warning: Could not read raw vectors from raw_store for rebuild")
            else:
                print(f"  Warning: Compressor not trained but dimension mismatch. This should not happen.")
                print(f"  Pending vectors saved in raw_store but not indexed. Index may need manual rebuild.")
            self.pending_ids.clear()
            self._flush_meta()
            return
        
        # 优化：增量添加，避免重复添加已存在的ID
        # FAISS IndexIDMap会自动处理重复ID（替换旧向量），但我们可以优化为批量检查
        try:
            self.index.add_with_ids(vecs, ids)
        except Exception as e:
            # 如果添加失败（例如维度不匹配），尝试重建索引
            print(f"Warning: Failed to add vectors to index: {e}")
            print("  Attempting to rebuild index...")
            if self.compressor and self.compressor.trained:
                self._rebuild_index_with_compression()
                # 重建后重试添加
                try:
                    self.index.add_with_ids(vecs, ids)
                except Exception as e2:
                    print(f"Error: Failed to add vectors after rebuild: {e2}")
                    print("  Vectors saved in raw_store but not indexed")
        
        self.pending_ids.clear()
        self._flush_meta()
    
    def _train_compressor_and_rebuild(self):
        """训练PCA压缩器并重建索引"""
        if not self.raw_store or not self.compressor:
            return
        
        print(f"Starting PCA training and index rebuild...")
        
        training_samples = []
        sample_count = 0
        for cid, vec in self.raw_store.iterate():
            training_samples.append(vec)
            sample_count += 1
            if sample_count >= PCA_TRAIN_SAMPLES:
                break
        
        if len(training_samples) < 1000:
            print(f"Warning: Only {len(training_samples)} samples available, skipping PCA training")
            return
        
        print(f"Training PCA with {len(training_samples)} samples...")
        training_array = np.stack(training_samples, axis=0).astype('float32')
        self.compressor.train(training_array)
        self.compressed_dim = self.compressor.compressed_dim
        
        compressor_path = CHECKPOINT_DIR / "vector_compressor.json"
        self.compressor.save(str(compressor_path))
        print(f"PCA trained: {self.original_emb_dim} -> {self.compressed_dim} dims")
        
        self._rebuild_index_with_compression()
    
    def _rebuild_index_with_compression(self):
        """重建索引（优化：支持增量更新，避免全量重建）"""
        if not self.raw_store or not self.compressor or not self.compressor.trained:
            return
        
        print(f"Rebuilding index with compression...")
        
        # 优化：检查是否可以增量更新
        # 注意：FAISS不直接支持获取所有ID，我们通过元数据来追踪已索引的ID
        existing_ids = set()
        if self.index.ntotal > 0:
            # 从元数据中获取已索引的ID（如果使用LMDB或内存元数据）
            if self.use_lmdb:
                try:
                    with self.lmdb_env.begin() as txn:
                        cursor = txn.cursor()
                        for key, _ in cursor:
                            try:
                                cid = int(key.decode())
                                existing_ids.add(cid)
                            except (ValueError, AttributeError):
                                continue
                except Exception:
                    pass
            else:
                # 内存元数据：直接获取所有ID
                existing_ids = set(self.meta.keys())
        
        # 如果索引为空或需要重建，创建新索引
        if self.index.ntotal == 0 or not existing_ids:
            if USE_HNSW:
                base = faiss.IndexHNSWFlat(self.compressed_dim, HNSW_M, faiss.METRIC_INNER_PRODUCT)
                base.hnsw.efSearch = HNSW_EF_SEARCH
                base.hnsw.efConstruction = HNSW_EF_CONSTRUCTION
            else:
                base = faiss.IndexFlatIP(self.compressed_dim)
            new_index = faiss.IndexIDMap(base)
        else:
            # 增量更新：只添加新向量
            new_index = self.index
        
        batch_size = 1000
        batch_vecs = []
        batch_ids = []
        total_rebuilt = 0
        total_skipped = 0
        
        for cid, raw_vec in self.raw_store.iterate():
            # 增量更新：跳过已存在的ID（如果索引不为空）
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
                    print(f"  Rebuilt {total_rebuilt} vectors...")
        
        if batch_vecs:
            vecs_array = np.stack(batch_vecs, axis=0).astype('float32')
            ids_array = np.array(batch_ids, dtype=np.int64)
            new_index.add_with_ids(vecs_array, ids_array)
            total_rebuilt += len(batch_ids)
        
        self.index = new_index
        if total_skipped > 0:
            print(f"Index rebuild complete: {total_rebuilt} vectors added, {total_skipped} skipped (already indexed)")
        else:
            print(f"Index rebuild complete: {total_rebuilt} vectors")

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
                        print(f"Error: raw_store dimension ({obj.raw_store.dim}) doesn't match compressor original_dim ({obj.compressor.original_dim})")
                        print("  Reinitializing raw_store with correct dimension...")
                        obj.raw_store.close()
                        obj.raw_store = RawEmbeddingStore(RAW_EMBEDDING_PATH, obj.compressor.original_dim, RAW_EMBEDDING_MAP_SIZE)
            
            obj.index = faiss.read_index(str(faiss_path))
            
            if obj.compressor and obj.compressor.trained:
                if obj.index.d != obj.compressed_dim:
                    print(f"Warning: Index dimension ({obj.index.d}) doesn't match compressor ({obj.compressed_dim})")
                    print("  This may indicate index needs rebuild. Checking raw_store...")
                    if obj.raw_store and obj.raw_store.count() > 0:
                        print("  Raw vectors found, rebuilding index...")
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

def save_progress(processed_papers: int):
    progress_file = CHECKPOINT_DIR / "progress.json"
    progress_file.write_text(json.dumps({"processed_papers": processed_papers}, ensure_ascii=False), encoding='utf-8')

def load_progress():
    progress_file = CHECKPOINT_DIR / "progress.json"
    if progress_file.exists():
        data = json.loads(progress_file.read_text(encoding='utf-8'))
        processed = data.get("processed_papers", 0)
        if processed > 0:
            print(f"📂 检测到断点续传：已处理 {processed} 篇论文，从此位置继续...")
            return processed
    return 0

def clear_progress():
    progress_file = CHECKPOINT_DIR / "progress.json"
    if progress_file.exists():
        progress_file.unlink()

from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field

# 观点本体结构定义
@dataclass
class StructuredOpinion:
    """结构化观点对象"""
    subject: Optional[str] = None          # 主体（提出观点的实体）
    object: str = ""                       # 对象（被评价的核心实体）
    predicate: str = ""                    # 判断/评价（观点性动词+评价内容）
    target: Optional[str] = None           # 评价目标（比较对象或评价标准）
    polarity: str = "neutral"             # 极性：positive/negative/neutral
    strength: Optional[str] = None         # 强度：significantly/strongly/slightly等
    context: Optional[str] = None          # 背景条件（适用场景/任务/数据集）
    stance: str = "neutral"               # 观点方向：support/oppose/neutral
    opposed_to: List[int] = field(default_factory=list)  # 冲突观点ID列表

# 核心发现本体结构定义
@dataclass
class StructuredFinding:
    """结构化核心发现对象"""
    finding_type: str = ""                # 发现类型：mechanism_revelation/new_discovery/method_development等
    discovery_object: str = ""            # 发现对象（被发现的实体）
    discovery_content: str = ""           # 发现内容（具体发现什么）
    discovery_verb: str = ""              # 发现性动词（mediate/discover/show等）
    discovery_method: Optional[str] = None # 发现方法（如何发现的，如果有）
    discovery_condition: Optional[str] = None # 发现条件（在什么条件下，如果有）
    confidence: float = 0.0              # 置信度
    source_sentence: str = ""             # 来源句子
    source_type: str = "abstract"         # 来源类型：title/abstract

# 核心发现类型配置
FINDING_TYPES = {
    'mechanism_revelation': {
        'name': '机制揭示',
        'keywords': ['mediate', 'regulate', 'control', 'influence', 'determine', 'cause', 'mechanism', 'mediates', 'regulates', 'controls'],
        'patterns': [
            r'\b(\w+(?:\s+\w+)*?)\s+mediates?\s+(\w+(?:\s+\w+)*?)\b',
            r'\b(\w+(?:\s+\w+)*?)\s+regulates?\s+(\w+(?:\s+\w+)*?)\b',
            r'\bmechanism\s+of\s+(\w+(?:\s+\w+)*?)\b',
            r'\bsimulation\s+of\s+the\s+mechanism\s+of\s+(\w+(?:\s+\w+)*?)\b'
        ],
        'confidence_base': 0.4,
        'priority': 1
    },
    'new_discovery': {
        'name': '新发现',
        'keywords': ['new', 'novel', 'discovered', 'found', 'identified', 'species', 'compound', 'material', 'discovery'],
        'patterns': [
            r'\b(new|novel)\s+(\w+(?:\s+\w+)*?)\s+(species|compound|material|method|technique|ester)\b',
            r'\ba\s+new\s+(\w+(?:\s+\w+)*?)\s+species\b',
            r'\btwo\s+new\s+(\w+(?:\s+\w+)*?)\b',
            r'\bthe\s+quest\s+for\s+(\w+(?:\s+\w+)*?)\b',
            r'\ba\s+new\s+epiphyllous\s+species\b'
        ],
        'confidence_base': 0.5,
        'priority': 1
    },
    'method_development': {
        'name': '方法开发',
        'keywords': ['developed', 'designed', 'created', 'proposed', 'introduced', 'established', 'rapid', 'facile', 'catalytic', 'automated'],
        'patterns': [
            r'\b(rapid|facile|novel|new)\s+(\w+(?:\s+\w+)*?)\b',
            r'\bcatalytic\s+(\w+(?:\s+\w+)*?)\b',
            r'\bautomated\s+(\w+(?:\s+\w+)*?)\b',
            r'\b(\w+(?:\s+\w+)*?)\s+probe\b',
            r'\b(\w+(?:\s+\w+)*?)\s+device\b',
            r'\b(\w+(?:\s+\w+)*?)\s+system\b'
        ],
        'confidence_base': 0.4,
        'priority': 2
    },
    'process_description': {
        'name': '过程描述',
        'keywords': ['pyrolysis', 'synthesis', 'process', 'reaction', 'degradation', 'formation'],
        'patterns': [
            r'\bpyrolysis\s+of\s+(\w+(?:\s+\w+)*?)\b',
            r'\bsynthesis\s+of\s+(\w+(?:\s+\w+)*?)\b',
            r'\bprocess\s+of\s+(\w+(?:\s+\w+)*?)\b',
            r'\breaction\s+of\s+(\w+(?:\s+\w+)*?)\b'
        ],
        'confidence_base': 0.3,
        'priority': 3
    },
    'feature_description': {
        'name': '特征描述',
        'keywords': ['characteristics', 'structure', 'properties', 'features', 'crystal structure'],
        'patterns': [
            r'\bcharacteristics?\s+of\s+(\w+(?:\s+\w+)*?)\b',
            r'\bstructure\s+of\s+(\w+(?:\s+\w+)*?)\b',
            r'\bproperties?\s+of\s+(\w+(?:\s+\w+)*?)\b',
            r'\bcrystal\s+structure\s+of\s+(\w+(?:\s+\w+)*?)\b'
        ],
        'confidence_base': 0.3,
        'priority': 3
    },
    'result_report': {
        'name': '结果报告',
        'keywords': ['are', 'is', 'show', 'demonstrate', 'indicate', 'reveal', 'budget', 'balance', 'hyper-methylated'],
        'patterns': [
            r'\b(\w+(?:\s+\w+)*?)\s+(are|is)\s+(\w+(?:\s+\w+)*?)\b',
            r'\b(\w+(?:\s+\w+)*?)\s+(show|demonstrate|indicate|reveal)\s+(\w+(?:\s+\w+)*?)\b',
            r'\b(\w+(?:\s+\w+)*?)\s+budget\b',
            r'\b(\w+(?:\s+\w+)*?)\s+balance\b'
        ],
        'confidence_base': 0.35,
        'priority': 2
    },
    'method_application': {
        'name': '方法应用',
        'keywords': ['use', 'application', 'management', 'utilization', 'employment'],
        'patterns': [
            r'\buse\s+of\s+(\w+(?:\s+\w+)*?)\s+for\s+(\w+(?:\s+\w+)*?)\b',
            r'\bapplication\s+of\s+(\w+(?:\s+\w+)*?)\b',
            r'\bmanagement\s+of\s+(\w+(?:\s+\w+)*?)\b',
            r'\b(\w+(?:\s+\w+)*?)\s+management\b'
        ],
        'confidence_base': 0.3,
        'priority': 3
    },
    'theory_concept': {
        'name': '理论概念',
        'keywords': ['theory', 'concept', 'science', 'how to', 'balancing', 'discussion'],
        'patterns': [
            r'\b(\w+(?:\s+\w+)*?)\s+science\b',
            r'\bhow\s+to\s+(\w+(?:\s+\w+)*?)\b',
            r'\ba\s+balancing\s+act\b',
            r'\btheory\s+of\s+(\w+(?:\s+\w+)*?)\b'
        ],
        'confidence_base': 0.25,
        'priority': 4
    }
}

# =============================================================================
# 8阶段观点识别系统 - 模块化实现
# =============================================================================

# =========================
# 阶段0：文本预处理模块
# =========================
class TextPreprocessor:
    """文本预处理：切分标题/摘要、句子标准化、清理无意义结构
    
    注意：原始数据只有标题和摘要，没有正文，因此只处理这两部分
    """
    
    def __init__(self, nlp_model=None):
        self.nlp = nlp_model
    
    def process(self, paper_text: str, paper_title: str = "", paper_abstract: str = "") -> Dict:
        """处理论文文本，返回结构化数据
        
        注意：原始数据只有标题和摘要，没有正文，因此只处理这两部分
        
        Returns:
            {
                'title': str,
                'sentences': List[str],  # 优质句子列表（仅来自摘要）
                'abstract_sentences': List[str]
            }
        """
        result = {
            'title': paper_title.strip() if paper_title else "",
            'sentences': [],
            'abstract_sentences': []
        }
        
        # 如果没有传入paper_abstract，尝试从paper_text中提取（通过[ABSTRACT]标记）
        if not paper_abstract and paper_text:
            abstract_marker = '[ABSTRACT]'
            if abstract_marker in paper_text:
                parts = paper_text.split(abstract_marker, 1)
                if len(parts) == 2:
                    if not paper_title and parts[0].strip():
                        result['title'] = parts[0].strip()
                    paper_abstract = parts[1].strip()
            elif not paper_title:
                # 如果没有[ABSTRACT]标记，且没有标题，尝试将第一行作为标题
                lines = paper_text.split('\n', 1)
                if len(lines) > 0 and lines[0].strip() and len(lines[0].strip()) < 200:
                    result['title'] = lines[0].strip()
                    if len(lines) > 1:
                        paper_abstract = lines[1].strip()
                else:
                    paper_abstract = paper_text
        
        # 提取摘要句子
        if paper_abstract:
            abstract_sents = self._extract_sentences(paper_abstract)
            result['abstract_sentences'] = abstract_sents
            result['sentences'].extend(abstract_sents)
        
        # 句子标准化
        result['sentences'] = [self._standardize_sentence(s) for s in result['sentences']]
        result['abstract_sentences'] = [self._standardize_sentence(s) for s in result['abstract_sentences']]
        
        # 过滤无意义结构
        result['sentences'] = [s for s in result['sentences'] if not self._is_meaningless(s)]
        result['abstract_sentences'] = [s for s in result['abstract_sentences'] if not self._is_meaningless(s)]
        
        return result
    
    def _extract_sentences(self, text: str) -> List[str]:
        """提取句子列表"""
        if not text or not self.nlp:
            # 简单分句
            sentences = re.split(r'[.!?]\s+', text)
            return [s.strip() for s in sentences if s.strip() and len(s.strip()) > 10]
        
        doc = self.nlp(text)
        return [sent.text.strip() for sent in doc.sents if len(sent.text.strip()) > 10]
    
    def _standardize_sentence(self, sentence: str) -> str:
        """句子标准化：合并被错误拆分的短句、处理引用括号"""
        # 合并被错误拆分的短句（如 "Fig. 1." 后接句子）
        sentence = re.sub(r'([A-Z][a-z]+\.)\s+([A-Z])', r'\1 \2', sentence)
        
        # 处理引用：保留但简化格式
        sentence = re.sub(r'\([^)]*\)', '', sentence)  # 移除括号内容（可选，根据需求调整）
        
        # 清理多余空格
        sentence = ' '.join(sentence.split())
        
        return sentence.strip()
    
    def _is_meaningless(self, sentence: str) -> bool:
        """判断是否为无意义结构"""
        s_lower = sentence.lower()
        
        # Copyright声明
        if re.search(r'copyright\s+©?\s*\d{4}', s_lower):
            return True
        
        # Received/Accepted
        if re.search(r'\b(received|accepted|published)\s+(january|february|march|april|may|june|july|august|september|october|november|december)', s_lower):
            return True
        
        # Funding statements
        if re.search(r'\b(funding|supported|grant|acknowledgment)', s_lower) and len(sentence) < 50:
            return True
        
        # 图表标题
        if re.match(r'^(fig|figure|table|scheme)\s+\d+[.:]', s_lower):
            return True
        
        # 过短句子
        if len(sentence) < 20:
            return True
        
        return False


# =========================
# 阶段1：创新实体识别模块
# =========================
class InnovationEntityRecognizer:
    """创新实体识别：名词短语 + 创新修饰词 + 语义异常检测"""
    
    INNOVATION_MODIFIERS = {
        'novel', 'new', 'improved', 'enhanced', 'innovative', 'efficient', 
        'effective', 'robust', 'original', 'pioneering', 'breakthrough',
        'advanced', 'superior', 'state-of-the-art', 'groundbreaking'
    }
    
    DISCIPLINE_PATTERNS = [
        r'\ba\s+(\w+(?:\s+\w+)*?)\s+algorithm\b',
        r'\ba\s+(\w+(?:\s+\w+)*?)\s+model\b',
        r'\ba\s+(\w+(?:\s+\w+)*?)\s+method\b',
        r'\ba\s+(\w+(?:\s+\w+)*?)\s+vector\b',
        r'\ba\s+(\w+(?:\s+\w+)*?)\s+system\b',
        r'\ba\s+(\w+(?:\s+\w+)*?)\s+approach\b',
        r'\ba\s+(\w+(?:\s+\w+)*?)\s+technique\b',
        r'\ba\s+(\w+(?:\s+\w+)*?)\s+framework\b'
    ]
    
    def __init__(self, nlp_model=None):
        self.nlp = nlp_model
        self._compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self.DISCIPLINE_PATTERNS]
    
    def extract(self, doc, sentences: List[str]) -> Dict[str, List[Tuple[str, float]]]:
        """提取创新实体及其评分
        
        Returns:
            {
                sentence: [(entity, innovation_score), ...]
            }
        """
        results = {}
        
        for sentence in sentences:
            entities = []
            
            # 提取名词短语
            if self.nlp:
                sent_doc = self.nlp(sentence)
                noun_phrases = [chunk.text for chunk in sent_doc.noun_chunks]
            else:
                # 简单提取：使用正则
                noun_phrases = re.findall(r'\b(?:the|a|an)?\s*([A-Z][a-z]+(?:\s+[A-Z]?[a-z]+)*)\b', sentence)
            
            for np in noun_phrases:
                if len(np) < 3:
                    continue
                
                score = self._score_innovation(np, sentence)
                if score > 0.3:  # 阈值可调
                    entities.append((np, score))
            
            if entities:
                results[sentence] = entities
        
        return results
    
    def _score_innovation(self, noun_phrase: str, context: str) -> float:
        """计算创新实体评分"""
        score = 0.0
        np_lower = noun_phrase.lower()
        ctx_lower = context.lower()
        
        # 1. 创新修饰词匹配
        for modifier in self.INNOVATION_MODIFIERS:
            if modifier in ctx_lower and modifier in ctx_lower[:ctx_lower.find(np_lower) + 50]:
                score += 0.4
                break
        
        # 2. 学科固定结构匹配
        for pattern in self._compiled_patterns:
            if pattern.search(context):
                score += 0.3
                break
        
        # 3. 语义异常检测（稀有、专有、跨领域组合）
        if self._is_semantically_anomalous(np_lower):
            score += 0.3
        
        return min(score, 1.0)
    
    def _is_semantically_anomalous(self, phrase: str) -> bool:
        """语义异常检测：检测稀有、专有、跨领域组合"""
        words = phrase.split()
        
        # 检测专有名词组合（首字母大写）
        if len(words) >= 2 and all(w[0].isupper() for w in words if w):
            return True
        
        # 检测跨领域组合（化学+生物等，通过特殊词根判断）
        chemical_indicators = ['benzyl', 'chloro', 'methyl', 'ethyl', 'phenyl']
        bio_indicators = ['protein', 'enzyme', 'cell', 'gene', 'dna']
        
        has_chemical = any(ind in phrase.lower() for ind in chemical_indicators)
        has_bio = any(ind in phrase.lower() for ind in bio_indicators)
        
        if has_chemical and has_bio:
            return True
        
        return False


# =========================
# 阶段2：动词类型分类模块
# =========================
class VerbTypeClassifier:
    """动词类型分类：创新/发现/报告/背景类"""
    
    INNOVATION_VERBS = {
        'propose', 'introduce', 'present', 'develop', 'design', 'construct',
        'create', 'formulate', 'establish', 'build', 'found', 'initiate'
    }
    
    DISCOVERY_VERBS = {
        'discover', 'find', 'observe', 'identify', 'reveal', 'demonstrate',
        'show', 'detect', 'uncover', 'expose'
    }
    
    FRAMEWORK_VERBS = {
        'report', 'obtain', 'provide', 'note', 'indicate', 'present',
        'describe', 'summarize'
    }
    
    BACKGROUND_VERBS = {
        'study', 'analyze', 'examine', 'consider', 'compare', 'investigate',
        'review', 'explore', 'discuss'
    }
    
    def __init__(self, nlp_model=None):
        self.nlp = nlp_model
    
    def classify(self, doc, sentence: str) -> Tuple[str, float]:
        """分类句子动词类型
        
        Returns:
            (verb_type, confidence): verb_type in ['innovation', 'discovery', 'framework', 'background', 'unknown']
        """
        if not self.nlp:
            return self._classify_simple(sentence)
        
        sent_doc = self.nlp(sentence)
        
        # 查找主干动词
        main_verb = None
        for token in sent_doc:
            if token.pos_ == 'VERB' and token.dep_ == 'ROOT':
                main_verb = token.lemma_.lower()
                break
        
        if not main_verb:
            return ('unknown', 0.0)
        
        # 分类
        if main_verb in self.INNOVATION_VERBS:
            return ('innovation', 0.9)
        elif main_verb in self.DISCOVERY_VERBS:
            return ('discovery', 0.8)
        elif main_verb in self.FRAMEWORK_VERBS:
            return ('framework', 0.7)
        elif main_verb in self.BACKGROUND_VERBS:
            return ('background', 0.6)
        else:
            return ('unknown', 0.3)
    
    def _classify_simple(self, sentence: str) -> Tuple[str, float]:
        """简单分类（无NLP模型时）"""
        s_lower = sentence.lower()
        
        for verb in self.INNOVATION_VERBS:
            if verb in s_lower:
                return ('innovation', 0.8)
        
        for verb in self.DISCOVERY_VERBS:
            if verb in s_lower:
                return ('discovery', 0.7)
        
        for verb in self.FRAMEWORK_VERBS:
            if verb in s_lower:
                return ('framework', 0.6)
        
        for verb in self.BACKGROUND_VERBS:
            if verb in s_lower:
                return ('background', 0.5)
        
        return ('unknown', 0.2)


# =========================
# 阶段3：标题语义对齐模块
# =========================
class TitleRelevanceScorer:
    """标题语义对齐：计算标题-句子相似度"""
    
    def __init__(self, emb_model=None, cache=None):
        self.emb_model = emb_model
        self.cache = cache
    
    def score(self, title: str, sentence: str) -> float:
        """计算标题相关度评分（0-1）"""
        if not title or not sentence or not self.emb_model:
            return 0.5  # 默认中等相关度
        
        # 编码标题和句子
        title_emb = self._encode(title)
        sent_emb = self._encode(sentence)
        
        if title_emb is None or sent_emb is None:
            return 0.5
        
        # 计算余弦相似度
        similarity = float(np.dot(title_emb, sent_emb) / (np.linalg.norm(title_emb) * np.linalg.norm(sent_emb) + 1e-12))
        
        # 归一化到0-1（相似度通常在-1到1之间）
        return (similarity + 1) / 2
    
    def _encode(self, text: str) -> Optional[np.ndarray]:
        """编码文本为向量"""
        if not text or not self.emb_model:
            return None
        
        try:
            # 使用全局的encode_with_cache函数
            embeddings = encode_with_cache([text], self.emb_model, self.cache)
            if embeddings and len(embeddings) > 0:
                return embeddings[0]
            return None
        except Exception:
            return None


# =========================
# 阶段4：论文结构理解模块
# =========================
class ParagraphRoleDetector:
    """论文结构理解：段落功能检测"""
    
    GAP_INDICATORS = ['however', 'but', 'still', 'yet', 'nevertheless', 'although']
    PROPOSED_INDICATORS = ['we propose', 'this paper presents', 'in this work', 'we develop', 'we introduce']
    CONTRIBUTION_INDICATORS = ['our contributions are', 'the main contribution is', 'we contribute', 'contributions include']
    FINDING_INDICATORS = ['we show', 'we demonstrate', 'results indicate', 'we find', 'we observe']
    
    def __init__(self, nlp_model=None):
        self.nlp = nlp_model
    
    def detect(self, sentence: str, position: str = "unknown") -> str:
        """检测句子结构角色
        
        Returns:
            role in ['background', 'gap', 'proposed_work', 'contributions', 'findings', 'unknown']
        """
        s_lower = sentence.lower()
        
        # 贡献句
        if any(indicator in s_lower for indicator in self.CONTRIBUTION_INDICATORS):
            return 'contributions'
        
        # 本文提出
        if any(indicator in s_lower for indicator in self.PROPOSED_INDICATORS):
            return 'proposed_work'
        
        # 发现句
        if any(indicator in s_lower for indicator in self.FINDING_INDICATORS):
            return 'findings'
        
        # 研究缺口
        if any(indicator in s_lower for indicator in self.GAP_INDICATORS):
            return 'gap'
        
        # 位置启发式：摘要/Introduction通常包含Proposed Work
        if position in ['abstract', 'introduction']:
            return 'proposed_work'
        
        return 'unknown'


# =========================
# 阶段5：深层依存抽取模块
# =========================
class DeepDependencyExtractor:
    """深层依存抽取：跳过框架动词、提取核心断言"""
    
    FRAMEWORK_VERBS = {'report', 'obtain', 'provide', 'note', 'indicate'}
    
    PRONOUNS = {'this', 'it', 'that', 'these', 'those'}
    PRONOUN_PHRASES = {'the method', 'the system', 'the approach', 'the technique', 
                      'the tool', 'the framework', 'the algorithm', 'the model'}
    
    GENERIC_WORDS = {
        'problem', 'approach', 'patients', 'method', 'data', 'results',
        'this', 'thing', 'it', 'that', 'these', 'those',
        'system', 'tool', 'technique', 'framework', 'algorithm', 'model',
        'study', 'pilot', 'analysis', 'evaluation'
    }
    
    GENERIC_ENTITY_PATTERNS = [
        r'\b(a|an|the)\s+(method|algorithm|framework|system|tool|technique|model|study|pilot)\b',
        r'\b(method|algorithm|framework|system|tool|technique|model|study|pilot)\s+(is|was|are|were)\b',
    ]
    
    def __init__(self, nlp_model=None):
        self.nlp = nlp_model
    
    def extract(self, doc, sentence: str, sentences: List[str] = None, sentence_idx: int = -1) -> Optional[Dict]:
        """提取深层语义片段
        
        Args:
            doc: spaCy文档对象（如果为None，会为sentence创建新的doc）
            sentence: 句子文本
            sentences: 句子列表（用于跨句扫描，可选）
            sentence_idx: 当前句子在列表中的索引（用于跨句扫描，可选）
        
        Returns:
            {
                'subject': str,
                'innovation_entity': str,
                'verb': str,
                'complement': str,
                'raw_opinion': str
            } or None
        """
        if not self.nlp:
            return None
        
        # 如果doc不为None，尝试从doc中找到对应的sentence
        sent_doc = None
        if doc is not None:
            # 尝试在doc中找到匹配的sentence
            for sent in doc.sents:
                if sent.text.strip() == sentence.strip() or sentence.strip() in sent.text:
                    sent_doc = sent
                    break
        
        # 如果没找到，为sentence创建新的doc
        if sent_doc is None:
            sent_doc = self.nlp(sentence)
        
        # 查找主干动词
        root_verb = None
        for token in sent_doc:
            if token.pos_ == 'VERB' and token.dep_ == 'ROOT':
                root_verb = token
                break
        
        if not root_verb:
            return None
        
        # 跳过框架动词，深入从句
        if root_verb.lemma_.lower() in self.FRAMEWORK_VERBS:
            # 查找从句（ccomp, xcomp）
            for child in root_verb.children:
                if child.dep_ in ['ccomp', 'xcomp']:
                    return self._extract_from_clause(child, sentence)
            
            # 查找直接宾语
            for child in root_verb.children:
                if child.dep_ == 'dobj':
                    return self._extract_from_object(child, sentence)
        
        # 正常提取：主语 + 动词 + 宾语
        result = {
            'subject': self._extract_subject(root_verb, sent_doc),
            'verb': root_verb.lemma_,
            'innovation_entity': self._extract_object(root_verb, sent_doc),
            'complement': self._extract_complement(root_verb, sent_doc),
            'raw_opinion': sentence
        }
        
        # 代词解析：替换this/it/the method等
        if sentences and sentence_idx >= 0:
            result['innovation_entity'] = self._resolve_pronouns(
                result.get('innovation_entity', ''), sentences, sentence_idx
            )
            result['complement'] = self._resolve_pronouns(
                result.get('complement', ''), sentences, sentence_idx
            )
        
        # 实体具体性判定：如果innovation_entity是通用词，标记为低置信度
        if result.get('innovation_entity'):
            is_specific = self._is_specific_entity(result['innovation_entity'])
            if not is_specific:
                # 如果实体是通用词，尝试从上下文寻找更具体的实体
                if sentences and sentence_idx >= 0:
                    # 在相邻句子中查找更具体的实体
                    specific_entity = self._find_specific_entity_in_context(
                        sentences, sentence_idx, result['innovation_entity']
                    )
                    if specific_entity:
                        result['innovation_entity'] = specific_entity
        
        # 如果complement为空，尝试跨句扫描
        if not result.get('complement') and sentences and sentence_idx >= 0:
            scanned_complement = self._scan_nearby_sentences_for_target(
                sentences, sentence_idx, result.get('innovation_entity', '')
            )
            if scanned_complement:
                result['complement'] = scanned_complement
        
        if result['innovation_entity']:
            return result
        
        return None
    
    def _extract_subject(self, verb_token, doc) -> str:
        """提取主语"""
        for child in verb_token.children:
            if child.dep_ in ['nsubj', 'nsubjpass']:
                return self._extract_noun_phrase(child)
        return ""
    
    def _extract_object(self, verb_token, doc) -> str:
        """提取宾语"""
        for child in verb_token.children:
            if child.dep_ == 'dobj':
                return self._extract_noun_phrase(child)
        return ""
    
    def _extract_complement(self, verb_token, doc) -> str:
        """提取补语"""
        for child in verb_token.children:
            if child.dep_ in ['acomp', 'xcomp']:
                return self._extract_noun_phrase(child)
        return ""
    
    def _extract_noun_phrase(self, token) -> str:
        """提取名词短语"""
        phrase_tokens = [token]
        
        # 收集修饰词
        for child in token.children:
            if child.dep_ in ['amod', 'det', 'compound']:
                phrase_tokens.append(child)
        
        phrase_tokens.sort(key=lambda t: t.i)
        return ' '.join([t.text for t in phrase_tokens])
    
    def _extract_from_clause(self, clause_token, sentence: str) -> Optional[Dict]:
        """从从句提取"""
        # 简化：返回从句内容
        return {
            'subject': 'we',
            'verb': 'report',
            'innovation_entity': clause_token.text,
            'complement': '',
            'raw_opinion': sentence
        }
    
    def _extract_from_object(self, obj_token, sentence: str) -> Optional[Dict]:
        """从宾语提取"""
        return {
            'subject': 'we',
            'verb': 'report',
            'innovation_entity': self._extract_noun_phrase(obj_token),
            'complement': '',
            'raw_opinion': sentence
        }
    
    def _is_specific_entity(self, entity: str) -> bool:
        """判断实体是否为具体术语（非通用词）
        
        Args:
            entity: 实体文本
        
        Returns:
            True表示是具体术语，False表示是通用词
        """
        if not entity:
            return False
        
        entity_lower = entity.lower().strip()
        entity_words = set(entity_lower.split())
        
        # 检查是否匹配泛化实体模式
        for pattern in self.GENERIC_ENTITY_PATTERNS:
            if re.search(pattern, entity_lower, re.IGNORECASE):
                return False
        
        # 如果所有词都是通用词，则不是具体实体
        if entity_words.issubset(self.GENERIC_WORDS):
            return False
        
        # 如果包含非通用词，且长度大于3个字符，认为是具体实体
        non_generic_words = entity_words - self.GENERIC_WORDS
        if non_generic_words and len(entity_lower) > 3:
            return True
        
        return False
    
    def _find_specific_entity_in_context(self, sentences: List[str], current_idx: int, 
                                         current_entity: str) -> str:
        """在上下文中查找更具体的实体
        
        Args:
            sentences: 句子列表
            current_idx: 当前句子索引
            current_entity: 当前提取的实体（可能是通用词）
        
        Returns:
            找到的具体实体，如果未找到则返回原实体
        """
        if not sentences or current_idx < 0:
            return current_entity
        
        # 在前后2句范围内查找
        scan_range = 2
        start_idx = max(0, current_idx - scan_range)
        end_idx = min(len(sentences), current_idx + scan_range + 1)
        
        for idx in range(start_idx, end_idx):
            if idx == current_idx:
                continue
            
            sent = sentences[idx]
            if not sent or not sent.strip():
                continue
            
            # 使用spaCy提取名词短语
            if self.nlp:
                try:
                    sent_doc = self.nlp(sent)
                    noun_phrases = [chunk.text for chunk in sent_doc.noun_chunks]
                    for np in noun_phrases:
                        if self._is_specific_entity(np) and len(np) > len(current_entity):
                            return np
                except Exception:
                    pass
        
        return current_entity
    
    def _resolve_pronouns(self, text: str, sentences: List[str], current_idx: int) -> str:
        """解析代词：将this/it/the method替换为前一句的NP
        
        Args:
            text: 待解析的文本
            sentences: 句子列表
            current_idx: 当前句子索引
        
        Returns:
            解析后的文本
        """
        if not text or not sentences or current_idx < 0:
            return text
        
        text_lower = text.lower().strip()
        
        # 检查是否包含代词或代词短语
        is_pronoun = text_lower in self.PRONOUNS
        is_pronoun_phrase = any(phrase in text_lower for phrase in self.PRONOUN_PHRASES)
        
        if not (is_pronoun or is_pronoun_phrase):
            return text
        
        # 向前查找1-2句，寻找最近的NP（优先匹配innovation_entities）
        for offset in [1, 2]:
            prev_idx = current_idx - offset
            if prev_idx < 0:
                continue
            
            prev_sent = sentences[prev_idx]
            if not prev_sent or not prev_sent.strip():
                continue
            
            # 使用spaCy提取名词短语
            if self.nlp:
                try:
                    prev_doc = self.nlp(prev_sent)
                    # 提取所有名词短语
                    noun_phrases = [chunk.text for chunk in prev_doc.noun_chunks]
                    if noun_phrases:
                        # 优先选择最长的NP（通常更具体）
                        replacement = max(noun_phrases, key=len)
                        if replacement and len(replacement) > 3:
                            return replacement
                except Exception:
                    pass
        
        return text
    
    def _scan_nearby_sentences_for_target(self, sentences: List[str], current_idx: int, 
                                         innovation_entity: str = '') -> str:
        """扫描相邻句子查找目标/问题/结果短语
        
        Args:
            sentences: 句子列表
            current_idx: 当前句子索引
            innovation_entity: 已提取的创新实体（用于上下文匹配）
        
        Returns:
            找到的目标/问题短语，如果未找到则返回空字符串
        """
        if not sentences or current_idx < 0 or current_idx >= len(sentences):
            return ""
        
        target_keywords = {
            'to improve', 'to enhance', 'to optimize', 'to solve', 'to address',
            'for', 'to reduce', 'to increase', 'to decrease', 'to minimize', 'to maximize',
            'problem', 'challenge', 'limitation', 'issue', 'difficulty',
            'improve', 'enhance', 'optimize', 'solve', 'address',
            'reduce', 'increase', 'decrease', 'minimize', 'maximize',
            'performance', 'accuracy', 'efficiency', 'robustness', 'reliability',
            'error', 'loss', 'cost', 'time', 'speed', 'quality'
        }
        
        # 向前扫描2-3句，向后扫描2-3句
        scan_range = 3
        start_idx = max(0, current_idx - scan_range)
        end_idx = min(len(sentences), current_idx + scan_range + 1)
        
        found_phrases = []
        
        for idx in range(start_idx, end_idx):
            if idx == current_idx:
                continue
            
            sent = sentences[idx].lower()
            
            # 查找目标关键词
            for keyword in target_keywords:
                if keyword in sent:
                    # 提取包含关键词的短语
                    # 简单策略：提取关键词前后的50个字符
                    keyword_pos = sent.find(keyword)
                    if keyword_pos >= 0:
                        # 使用原始句子长度，确保索引正确
                        original_sent = sentences[idx]
                        start = max(0, keyword_pos - 50)
                        end = min(len(original_sent), keyword_pos + len(keyword) + 50)
                        phrase = original_sent[start:end].strip()
                        if phrase and len(phrase) > 10:
                            found_phrases.append(phrase)
                            break
        
        # 返回最长的短语（通常包含更多信息）
        if found_phrases:
            return max(found_phrases, key=len)
        
        return ""


# =========================
# 阶段6：跨句融合模块
# =========================
class MultiSentenceFusion:
    """跨句融合：合并相关句子为完整观点"""
    
    def __init__(self, emb_model=None, cache=None, similarity_threshold=0.75):
        self.emb_model = emb_model
        self.cache = cache
        self.similarity_threshold = similarity_threshold
    
    def fuse(self, sentences: List[str], opinions: List[Dict], opinion_to_sentence_map: Dict) -> Tuple[List[Dict], Dict]:
        """融合相关句子
        
        Args:
            sentences: 句子列表
            opinions: 观点列表（每个包含raw_opinion等字段）
            opinion_to_sentence_map: opinion对象id到原始sentence的映射
        
        Returns:
            (融合后的观点列表, 融合后观点到原始sentence列表的映射)
        """
        if len(opinions) <= 1:
            # 建立简单的映射
            fused_to_original = {}
            for op in opinions:
                op_id = id(op)
                original_sent = opinion_to_sentence_map.get(op_id, "")
                if original_sent:
                    fused_to_original[id(op)] = [original_sent]
            return opinions, fused_to_original
        
        fused = []
        used = set()
        fused_to_original = {}  # 融合后观点到原始sentence列表的映射
        
        # 建立opinion索引到sentence索引的映射
        opinion_to_sent_idx = {}
        for i, op in enumerate(opinions):
            op_id = id(op)
            original_sent = opinion_to_sentence_map.get(op_id, "")
            if original_sent:
                sent_idx = sentences.index(original_sent) if original_sent in sentences else -1
                opinion_to_sent_idx[i] = sent_idx
        
        for i, op1 in enumerate(opinions):
            if i in used:
                continue
            
            # 查找可融合的观点
            fused_group = [op1]
            used.add(i)
            
            for j, op2 in enumerate(opinions[i+1:], start=i+1):
                if j in used:
                    continue
                
                # 获取sentence索引
                sent_idx1 = opinion_to_sent_idx.get(i, -1)
                sent_idx2 = opinion_to_sent_idx.get(j, -1)
                
                if self._should_fuse(op1, op2, sent_idx1, sent_idx2):
                    fused_group.append(op2)
                    used.add(j)
            
            # 融合组内观点
            if len(fused_group) > 1:
                fused_opinion = self._merge_opinions(fused_group)
                fused.append(fused_opinion)
                # 记录融合后观点对应的所有原始sentence
                original_sents = [opinion_to_sentence_map.get(id(op), "") for op in fused_group]
                original_sents = [s for s in original_sents if s]  # 过滤空字符串
                fused_to_original[id(fused_opinion)] = original_sents
            else:
                fused.append(op1)
                op_id = id(op1)
                original_sent = opinion_to_sentence_map.get(op_id, "")
                if original_sent:
                    fused_to_original[op_id] = [original_sent]
        
        return fused, fused_to_original
    
    def _should_fuse(self, op1: Dict, op2: Dict, sent_idx1: int, sent_idx2: int) -> bool:
        """判断是否应该融合两个观点"""
        # 位置邻近（同一段落内，距离<3句）
        if sent_idx1 >= 0 and sent_idx2 >= 0 and abs(sent_idx2 - sent_idx1) <= 3:
            # 语义相似度
            if self.emb_model:
                sim = self._semantic_similarity(op1.get('raw_opinion', ''), op2.get('raw_opinion', ''))
                if sim >= self.similarity_threshold:
                    return True
            
            # 创新实体重叠
            entity1 = op1.get('innovation_entity', '')
            entity2 = op2.get('innovation_entity', '')
            if entity1 and entity2 and (entity1.lower() in entity2.lower() or entity2.lower() in entity1.lower()):
                return True
        
        return False
    
    def _semantic_similarity(self, text1: str, text2: str) -> float:
        """计算语义相似度"""
        if not text1 or not text2 or not self.emb_model:
            return 0.0
        
        try:
            emb1 = self.emb_model.encode([text1], show_progress_bar=False)[0]
            emb2 = self.emb_model.encode([text2], show_progress_bar=False)[0]
            sim = float(np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2) + 1e-12))
            return (sim + 1) / 2
        except Exception:
            return 0.0
    
    def _has_metric_in_text(self, text: str) -> bool:
        """判断文本中是否包含度量信息"""
        if not text:
            return False
        text_lower = text.lower()
        
        # 字符串关键词匹配
        metric_keywords = {
            'accuracy', 'precision', 'recall', 'f1', 'f-score',
            'survival rate', 'mortality', 'exergy loss', 'energy efficiency',
            'error rate', 'success rate', 'completion rate'
        }
        for kw in metric_keywords:
            if kw in text_lower:
                return True
        
        # 正则表达式匹配（数字、百分比等）
        metric_patterns = [
            r'\d+%',
            r'\d+\.\d+',
            r'\b\d+\s*(times|fold|improvement)'
        ]
        for pattern in metric_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        
        return False
    
    def _extract_target_from_text(self, text: str) -> str:
        """从文本中提取目标/问题短语"""
        if not text:
            return ""
        text_lower = text.lower()
        
        # 模式1：to improve/enhance/optimize/solve/address/reduce/increase/decrease + 目标
        pattern1 = r'\bto\s+(?:improve|enhance|optimize|solve|address|reduce|increase|decrease)\s+([^\.]+)'
        match = re.search(pattern1, text_lower, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # 模式2：for + 目标
        pattern2 = r'\bfor\s+([^\.]+?)(?:\s+to\s+(?:improve|enhance|optimize|solve|address))?'
        match = re.search(pattern2, text_lower, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # 模式3：problem/challenge/limitation/issue + of/with/in + 目标
        pattern3 = r'\b(?:problem|challenge|limitation|issue)\s+(?:of|with|in)\s+([^\.]+)'
        match = re.search(pattern3, text_lower, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        return ""
    
    def _merge_opinions(self, opinions: List[Dict]) -> Dict:
        """合并多个观点（智能合并：优先合并method+target组合）"""
        merged = {
            'subject': 'we',
            'verb': 'propose',
            'innovation_entity': '',
            'complement': '',
            'raw_opinion': ''
        }
        
        if not opinions:
            return merged
        
        # 分类opinions：有method的、有target的、有metric的
        has_method = []  # 有innovation_entity的
        has_target = []  # 有complement的
        has_metric = []  # raw_opinion中包含度量的
        
        for op in opinions:
            entity = op.get('innovation_entity', '').strip()
            complement = op.get('complement', '').strip()
            raw_text = op.get('raw_opinion', '')
            
            if entity:
                has_method.append(op)
            if complement:
                has_target.append(op)
            if self._has_metric_in_text(raw_text):
                has_metric.append(op)
        
        # 智能合并规则1：A.method存在 + B.target存在 → 合并
        if has_method and has_target:
            # 优先选择最具体的method和target
            best_method_op = max(has_method, key=lambda op: len(op.get('innovation_entity', '')))
            best_target_op = max(has_target, key=lambda op: len(op.get('complement', '')))
            
            # 如果method所在opinion已有target，优先使用自己的target
            method_has_target = best_method_op.get('complement', '').strip()
            if method_has_target:
                merged['innovation_entity'] = best_method_op.get('innovation_entity', '')
                merged['complement'] = method_has_target
            else:
                # 如果method没有target，使用其他opinion的target
                merged['innovation_entity'] = best_method_op.get('innovation_entity', '')
                merged['complement'] = best_target_op.get('complement', '')
            
            # 合并verb：优先使用method所在opinion的verb
            merged['verb'] = best_method_op.get('verb', 'propose')
            merged['subject'] = best_method_op.get('subject', 'we')
        
        # 智能合并规则2：A.method存在 + B.metric存在 → 合并（将metric作为complement）
        elif has_method and has_metric and not has_target:
            best_method_op = max(has_method, key=lambda op: len(op.get('innovation_entity', '')))
            best_metric_op = max(has_metric, key=lambda op: len(op.get('raw_opinion', '')))
            
            merged['innovation_entity'] = best_method_op.get('innovation_entity', '')
            # 从metric文本中提取target
            metric_text = best_metric_op.get('raw_opinion', '')
            extracted_target = self._extract_target_from_text(metric_text)
            if extracted_target:
                merged['complement'] = extracted_target
            else:
                # 如果提取失败，使用metric文本的前50个字符
                merged['complement'] = metric_text[:50].strip()
            
            merged['verb'] = best_method_op.get('verb', 'propose')
            merged['subject'] = best_method_op.get('subject', 'we')
        
        # 默认合并：如果以上规则都不满足，使用原有逻辑
        else:
            entities = [op.get('innovation_entity', '') for op in opinions if op.get('innovation_entity')]
            if entities:
                merged['innovation_entity'] = entities[0]
            
            complements = [op.get('complement', '') for op in opinions if op.get('complement', '').strip()]
            if complements:
                merged['complement'] = max(complements, key=len)
            
            if opinions:
                merged['verb'] = opinions[0].get('verb', 'propose')
                merged['subject'] = opinions[0].get('subject', 'we')
        
        # 合并原始观点文本
        raw_texts = [op.get('raw_opinion', '') for op in opinions if op.get('raw_opinion')]
        merged['raw_opinion'] = ' '.join(raw_texts)
        
        return merged


# =========================
# 阶段7：观点评分与排序模块
# =========================
class OpinionScorer:
    """观点评分与排序：多维度综合评分"""
    
    def __init__(self):
        # 权重配置（可调）
        self.weights = {
            'verb_type': 0.25,
            'innovation_entity': 0.20,
            'structure_position': 0.15,
            'title_relevance': 0.20,
            'length': 0.10,
            'quantitative': 0.05,
            'purpose_structure': 0.05
        }
    
    def score(self, opinion: Dict, verb_type: str, has_innovation_entity: bool,
              structure_position: str, title_relevance: float, 
              paragraph_role: str = 'unknown') -> float:
        """计算综合评分"""
        scores = {}
        
        # 1. 动词类型评分
        verb_scores = {'innovation': 1.0, 'discovery': 0.8, 'framework': 0.5, 'background': 0.3, 'unknown': 0.2}
        scores['verb_type'] = verb_scores.get(verb_type, 0.2)
        
        # 2. 创新实体评分
        scores['innovation_entity'] = 1.0 if has_innovation_entity else 0.3
        
        # 3. 结构位置评分
        position_scores = {'abstract': 1.0, 'introduction': 0.9, 'body': 0.6, 'unknown': 0.5}
        scores['structure_position'] = position_scores.get(structure_position, 0.5)
        
        # 4. 标题相关度
        scores['title_relevance'] = title_relevance
        
        # 5. 长度合理性（50-200字符为最佳）
        raw_len = len(opinion.get('raw_opinion', ''))
        if 50 <= raw_len <= 200:
            scores['length'] = 1.0
        elif raw_len < 50:
            scores['length'] = raw_len / 50
        else:
            scores['length'] = max(0.5, 1.0 - (raw_len - 200) / 200)
        
        # 6. 定量改进（包含数字/百分比）
        raw_text = opinion.get('raw_opinion', '').lower()
        has_quantitative = bool(re.search(r'\d+%|\d+\.\d+|\b\d+\s*(times|fold|improvement)', raw_text))
        scores['quantitative'] = 1.0 if has_quantitative else 0.5
        
        # 7. 目的性结构（to address / to improve）
        has_purpose = bool(re.search(r'\bto\s+(address|improve|solve|enhance|optimize)', raw_text))
        scores['purpose_structure'] = 1.0 if has_purpose else 0.5
        
        # 综合评分
        total_score = sum(scores[key] * self.weights[key] for key in self.weights)
        
        return min(total_score, 1.0)
    
    def rank(self, opinions_with_scores: List[Tuple[Dict, float]], top_k: int = 3) -> List[Dict]:
        """排序并返回Top-K观点"""
        sorted_opinions = sorted(opinions_with_scores, key=lambda x: x[1], reverse=True)
        return [op for op, score in sorted_opinions[:top_k]]


# =========================
# 阶段8：语言重构模块
# =========================
class LanguageRewriter:
    """语言重构：将结构化观点重写为自然语言"""
    
    TARGET_KEYWORDS = {
        'problem', 'challenge', 'limitation', 'issue', 'difficulty',
        'improve', 'enhance', 'optimize', 'solve', 'address',
        'reduce', 'increase', 'decrease', 'minimize', 'maximize',
        'performance', 'accuracy', 'efficiency', 'robustness', 'reliability',
        'error', 'loss', 'cost', 'time', 'speed', 'quality'
    }
    
    METRIC_KEYWORDS = {
        'accuracy', 'precision', 'recall', 'f1', 'f-score',
        'survival rate', 'mortality', 'exergy loss', 'energy efficiency',
        'error rate', 'success rate', 'completion rate',
        'shuttle vector', 'vector', 'algorithm', 'model', 'method', 'approach',
        'system', 'framework', 'tool', 'technique', 'protocol'
    }
    
    GENERIC_WORDS = {
        'problem', 'approach', 'patients', 'method', 'data', 'results',
        'this', 'thing', 'it', 'that', 'these', 'those',
        'algorithm', 'framework', 'system', 'tool', 'technique', 'model',
        'study', 'pilot', 'analysis', 'evaluation'
    }
    
    GENERIC_ENTITY_PATTERNS = [
        r'\b(a|an|the)\s+(method|algorithm|framework|system|tool|technique|model|study|pilot)\b',
        r'\b(method|algorithm|framework|system|tool|technique|model|study|pilot)\s+(is|was|are|were)\b',
    ]
    
    TEMPLATES = [
        "We propose {innovation_entity} to {complement}.",
        "This paper presents {innovation_entity} that {complement}.",
        "We develop {innovation_entity} for {complement}.",
        "{innovation_entity} is proposed to {complement}."
    ]
    
    def _check_rewrite_conditions(self, opinion: Dict, raw_text: str = '') -> int:
        """检查是否满足重写条件（至少两项）
        
        Returns:
            满足条件的数量（0-3）
        """
        conditions_met = 0
        text_lower = (raw_text or opinion.get('raw_opinion', '') or '').lower()
        entity = (opinion.get('innovation_entity', '') or '').lower()
        complement = (opinion.get('complement', '') or '').lower()
        combined_text = f"{text_lower} {entity} {complement}"
        
        # 条件1：包含目标/问题关键词
        has_target_keywords = any(kw in combined_text for kw in self.TARGET_KEYWORDS)
        if has_target_keywords:
            conditions_met += 1
        
        # 条件2：包含具体度量/对象
        has_metric = any(kw in combined_text for kw in self.METRIC_KEYWORDS)
        if has_metric:
            conditions_met += 1
        
        # 条件3：包含方法名/实体或非通用名词
        entity_words = set(entity.split())
        is_non_generic = bool(entity_words - self.GENERIC_WORDS) and len(entity_words) > 0
        if is_non_generic and entity:
            conditions_met += 1
        
        return conditions_met
    
    def _is_specific_entity(self, entity: str) -> bool:
        """判断实体是否为具体术语（非通用词）"""
        if not entity:
            return False
        entity_lower = entity.lower().strip()
        entity_words = set(entity_lower.split())
        
        # 检查是否匹配泛化实体模式
        for pattern in self.GENERIC_ENTITY_PATTERNS:
            if re.search(pattern, entity_lower, re.IGNORECASE):
                return False
        
        # 检查是否所有词都是通用词
        if entity_words.issubset(self.GENERIC_WORDS):
            return False
        
        # 如果包含非通用词，且长度大于3个字符，认为是具体实体
        non_generic_words = entity_words - self.GENERIC_WORDS
        if non_generic_words and len(entity_lower) > 3:
            return True
        
        return False
    
    def _is_too_generic_entity(self, entity: str) -> bool:
        """判断实体是否过于泛化（用于保护机制A）"""
        if not entity:
            return True
        entity_lower = entity.lower().strip()
        
        # 检查是否匹配泛化实体模式
        for pattern in self.GENERIC_ENTITY_PATTERNS:
            if re.search(pattern, entity_lower, re.IGNORECASE):
                return True
        
        # 检查是否完全是通用词
        entity_words = set(entity_lower.split())
        if entity_words.issubset(self.GENERIC_WORDS):
            return True
        
        return False
    
    def _clean_original_sentence(self, raw_opinion: str) -> str:
        """清理原句：移除框架动词，保留核心内容"""
        if not raw_opinion:
            return ""
        cleaned = raw_opinion
        framework_patterns = [
            r'^(we|this paper|the authors?|they)\s+(?:report|find|show|demonstrate|prove|suggest|indicate)\s+that\s+',
            r'^(we|this paper|the authors?|they)\s+(?:report|find|show|demonstrate|prove|suggest|indicate)\s+',
        ]
        for pattern in framework_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip()
        return cleaned
    
    def rewrite(self, opinion: Dict) -> str:
        """重写为自然语言"""
        entity = opinion.get('innovation_entity', '')
        complement = opinion.get('complement', '')
        verb = opinion.get('verb', 'propose')
        subject = opinion.get('subject', 'we')
        raw_opinion = opinion.get('raw_opinion', '')
        
        if not entity:
            return raw_opinion
        
        # 保护机制B：如果complement为空，不允许进入模板1/模板2，必须返回cleaned原句
        has_valid_complement = bool(complement and complement.strip())
        
        # 保护机制A：如果entity过于泛化且complement为空，不能用模板3，返回cleaned原句
        is_too_generic = self._is_too_generic_entity(entity)
        
        if not has_valid_complement:
            # 如果entity过于泛化，直接返回cleaned原句（不生成空洞句）
            if is_too_generic:
                cleaned = self._clean_original_sentence(raw_opinion)
                if cleaned:
                    return cleaned
                return raw_opinion
            
            # 如果entity不泛化但complement为空，检查是否满足条件才使用模板3
            conditions_met = self._check_rewrite_conditions(opinion, raw_opinion)
            if conditions_met >= 2:
                # 满足条件，可以使用模板3
                if 'propose' in verb.lower() or 'introduce' in verb.lower():
                    return f"We propose {entity}."
                elif 'develop' in verb.lower() or 'create' in verb.lower():
                    return f"We develop {entity}."
                elif 'present' in verb.lower():
                    return f"This paper presents {entity}."
                else:
                    return f"{entity} is proposed."
            else:
                # 不满足条件，返回cleaned原句
                cleaned = self._clean_original_sentence(raw_opinion)
                if cleaned:
                    return cleaned
                return raw_opinion
        
        # 检查是否满足至少两项条件
        conditions_met = self._check_rewrite_conditions(opinion, raw_opinion)
        
        # 如果entity过于泛化，即使有complement，也应该返回cleaned原句（避免生成空洞句）
        if is_too_generic:
            cleaned = self._clean_original_sentence(raw_opinion)
            if cleaned:
                return cleaned
            return raw_opinion
        
        # 满足条件：进行完整重写（此时complement一定不为空，entity一定不泛化）
        # 模板1（完整）：有complement且有量化结果
        has_quantitative = bool(re.search(r'\d+%|\d+\.\d+|\b\d+\s*(times|fold|improvement)', raw_opinion))
        if has_quantitative and conditions_met >= 2:
            if 'propose' in verb.lower() or 'introduce' in verb.lower():
                return f"We propose {entity} to {complement}."
            elif 'develop' in verb.lower() or 'create' in verb.lower():
                return f"We develop {entity} for {complement}."
            elif 'present' in verb.lower():
                return f"This paper presents {entity} that {complement}."
            else:
                return f"{entity} is proposed to {complement}."
        
        # 模板2（方法+用途）：有complement但无量化
        if 'propose' in verb.lower() or 'introduce' in verb.lower():
            return f"We propose {entity} to {complement}."
        elif 'develop' in verb.lower() or 'create' in verb.lower():
            return f"We develop {entity} for {complement}."
        elif 'present' in verb.lower():
            return f"This paper presents {entity} that {complement}."
        else:
            return f"{entity} is proposed to {complement}."


# =========================
# 主管道类：整合所有8个阶段
# =========================
class OpinionExtractionPipeline:
    """8阶段观点识别管道"""
    
    def __init__(self, nlp_model, emb_model=None, cache=None):
        self.nlp = nlp_model
        self.emb_model = emb_model
        self.cache = cache
        
        # 初始化各阶段
        self.stage0 = TextPreprocessor(nlp_model)
        self.stage1 = InnovationEntityRecognizer(nlp_model)
        self.stage2 = VerbTypeClassifier(nlp_model)
        self.stage3 = TitleRelevanceScorer(emb_model, cache)
        self.stage4 = ParagraphRoleDetector(nlp_model)
        self.stage5 = DeepDependencyExtractor(nlp_model)
        self.stage6 = MultiSentenceFusion(emb_model, cache)
        self.stage7 = OpinionScorer()
        self.stage8 = LanguageRewriter()
    
    def extract(self, paper_text: str, paper_title: str = "", paper_abstract: str = "", doc=None) -> List[Tuple[str, StructuredOpinion]]:
        """执行完整的8阶段提取流程
        
        Args:
            paper_text: 论文正文文本
            paper_title: 论文标题
            paper_abstract: 论文摘要
            doc: 可选的spaCy文档对象（如果已存在，直接使用）
        
        Returns:
            List[Tuple[normalized_text, StructuredOpinion]]
        """
        # 阶段0：文本预处理
        preprocessed = self.stage0.process(paper_text, paper_title, paper_abstract)
        sentences = preprocessed['sentences']
        
        if not sentences:
            return []
        
        # 使用传入的doc或创建新的spaCy文档
        if doc is None and self.nlp:
            full_text = ' '.join(sentences)
            doc = self.nlp(full_text)
        elif doc is None:
            doc = None
        
        # 阶段1：创新实体识别
        innovation_entities = self.stage1.extract(doc, sentences)
        
        # 阶段2：动词类型分类
        verb_types = {}
        for sentence in sentences:
            verb_type, conf = self.stage2.classify(doc, sentence)
            verb_types[sentence] = (verb_type, conf)
        
        # 阶段3：标题语义对齐
        title_relevances = {}
        for sentence in sentences:
            title_relevances[sentence] = self.stage3.score(paper_title, sentence)
        
        # 阶段4：论文结构理解
        paragraph_roles = {}
        for i, sentence in enumerate(sentences):
            # 所有句子都来自摘要（没有正文）
            position = 'abstract'
            paragraph_roles[sentence] = self.stage4.detect(sentence, position)
        
        # 阶段5：深层依存抽取
        raw_opinions = []
        opinion_to_sentence_map = {}  # 建立opinion到原始sentence的映射
        for idx, sentence in enumerate(sentences):
            extracted = self.stage5.extract(doc, sentence, sentences=sentences, sentence_idx=idx)
            if extracted:
                # 如果阶段5没有提取到innovation_entity，尝试使用阶段1的结果
                if not extracted.get('innovation_entity') and sentence in innovation_entities:
                    entities = innovation_entities[sentence]
                    if entities:
                        # 使用评分最高的创新实体
                        best_entity, best_score = max(entities, key=lambda x: x[1])
                        extracted['innovation_entity'] = best_entity
                
                raw_opinions.append(extracted)
                # 记录每个opinion对应的原始sentence
                opinion_to_sentence_map[id(extracted)] = sentence
        
        if not raw_opinions:
            return []
        
        # 阶段6：跨句融合（需要传递opinion到sentence的映射）
        fused_opinions, fused_to_original_sentences = self.stage6.fuse(sentences, raw_opinions, opinion_to_sentence_map)
        
        # 阶段7：观点评分与排序
        opinions_with_scores = []
        for opinion in fused_opinions:
            # 获取融合后观点对应的原始sentence（可能是一个或多个）
            original_sentences = fused_to_original_sentences.get(id(opinion), [])
            if not original_sentences:
                # 如果找不到映射，尝试使用raw_opinion的前100字符匹配
                raw_text = opinion.get('raw_opinion', '')[:100]
                for sent in sentences:
                    if sent[:100] in raw_text or raw_text in sent[:100]:
                        original_sentences = [sent]
                        break
            
            # 使用第一个原始sentence获取特征（如果有多个，取第一个）
            source_sentence = original_sentences[0] if original_sentences else ""
            
            verb_type, _ = verb_types.get(source_sentence, ('unknown', 0.0))
            has_entity = bool(opinion.get('innovation_entity'))
            # 所有句子都来自摘要（没有正文）
            position = 'abstract'
            title_rel = title_relevances.get(source_sentence, 0.5)
            para_role = paragraph_roles.get(source_sentence, 'unknown')
            
            score = self.stage7.score(opinion, verb_type, has_entity, position, title_rel, para_role)
            opinions_with_scores.append((opinion, score))
        
        top_opinions = self.stage7.rank(opinions_with_scores, top_k=3)
        
        # 阶段8：语言重构
        final_results = []
        for opinion in top_opinions:
            rewritten = self.stage8.rewrite(opinion)
            
            # 转换为StructuredOpinion
            structured = StructuredOpinion(
                subject=opinion.get('subject'),
                object=opinion.get('innovation_entity', ''),
                predicate=opinion.get('verb', ''),
                context=opinion.get('complement', '')
            )
            
            final_results.append((rewritten, structured))
        
        return final_results

# =========================
# 规则引擎配置化系统
# =========================
class RuleEngine:
    """配置化规则引擎，支持规则加载、执行和权重调整"""
    
    def __init__(self, config=None):
        self.config = config or self._default_config()
        self._compiled_patterns = {}
        self._verb_sets = self._build_verb_sets()
    
    def _default_config(self):
        """默认规则配置"""
        return {
            'scoring': {
                'strong_verb': 40,
                'medium_verb': 35,
                'weak_verb': 15,
                'implicit_verb': 20,
                'research_keywords': 20,
                'opinion_keywords': 15,
                'assertion': 15,
                'comparison': 10,
                'evaluation': 10,
                'domain_assertion': 10,
                'numeric_assertion': 10,
                'result_verb': 15,
                'statistical_assertion': 20,
                'necessity_assertion': 10,
                'risk_assertion': 10,
                'comparison_assertion': 10,
                'template_match': 20,
                'sentence_length': 5
            },
            'penalties': {
                'pure_data_desc': {'base': 45, 'with_keywords': 35},
                'method_description': {'base': 40, 'with_keywords': 30},
                'experimental_design': {'base': 30, 'with_keywords': 20},
                'procedure_description': {'base': 35, 'with_keywords': 25},
                'pure_description': {'base': 40, 'with_keywords': 30}
            },
            'thresholds': {
                'base_opinion': 40,
                'min_with_penalty': 50,
                'penalty_multiplier': 1.85
            },
            'conditions': {
                'min_sentence_length': 6,
                'min_title_length': 5
            }
        }
    
    def _build_verb_sets(self):
        """构建动词集合（从全局变量加载）"""
        return {
            'strong': OPINION_VERBS_STRONG,
            'medium': OPINION_VERBS_MEDIUM,
            'weak': OPINION_VERBS_WEAK
        }
    
    def get_compiled_pattern(self, pattern):
        """获取编译后的正则表达式（缓存）"""
        if pattern not in self._compiled_patterns:
            self._compiled_patterns[pattern] = re.compile(pattern, re.IGNORECASE)
        return self._compiled_patterns[pattern]
    
    def evaluate_rule(self, rule_name, context):
        """评估单个规则"""
        # 规则评估逻辑将在后续实现中扩展
        pass
    
    def calculate_score(self, features):
        """根据特征计算观点分数"""
        config = self.config['scoring']
        score = 0
        
        if features.get('has_strong_verb'):
            score += config['strong_verb']
        elif features.get('has_medium_verb'):
            score += config['medium_verb']
        elif features.get('has_weak_verb_only'):
            score += config['weak_verb']
        
        if features.get('has_implicit_opinion_verb'):
            score += config['implicit_verb']
        
        if features.get('has_research_keywords'):
            score += config['research_keywords']
        if features.get('has_opinion_keywords'):
            score += config['opinion_keywords']
        
        if features.get('has_assertion'):
            score += config['assertion']
        if features.get('has_comparison'):
            score += config['comparison']
        if features.get('has_evaluation'):
            score += config['evaluation']
        if features.get('has_domain_assertion'):
            score += config['domain_assertion']
        if features.get('has_numeric_assertion'):
            score += config['numeric_assertion']
        if features.get('has_result_verb'):
            score += config['result_verb']
        if features.get('has_statistical_assertion'):
            score += config['statistical_assertion']
        if features.get('has_necessity_assertion'):
            score += config['necessity_assertion']
        if features.get('has_risk_assertion'):
            score += config['risk_assertion']
        if features.get('has_comparison_assertion'):
            score += config['comparison_assertion']
        
        if features.get('matches_template'):
            score += config['template_match']
        
        if features.get('sentence_length', 0) >= self.config['conditions']['min_sentence_length']:
            score += config['sentence_length']
        
        return score
    
    def calculate_penalty(self, features):
        """计算非观点惩罚分数"""
        penalties = self.config['penalties']
        max_penalty = 0
        
        if features.get('is_pure_data_desc'):
            penalty_config = penalties['pure_data_desc']
            max_penalty = max(max_penalty, 
                penalty_config['with_keywords'] if features.get('has_opinion_keywords') 
                else penalty_config['base'])
        
        if features.get('is_method_description'):
            penalty_config = penalties['method_description']
            max_penalty = max(max_penalty,
                penalty_config['with_keywords'] if features.get('has_research_keywords')
                else penalty_config['base'])
        
        if features.get('is_experimental_design'):
            penalty_config = penalties['experimental_design']
            max_penalty = max(max_penalty,
                penalty_config['with_keywords'] if features.get('has_research_keywords')
                else penalty_config['base'])
        
        if features.get('is_procedure_description'):
            penalty_config = penalties['procedure_description']
            max_penalty = max(max_penalty,
                penalty_config['with_keywords'] if features.get('has_research_keywords')
                else penalty_config['base'])
        
        if features.get('is_pure_description'):
            penalty_config = penalties['pure_description']
            max_penalty = max(max_penalty,
                penalty_config['with_keywords'] if features.get('has_research_keywords')
                else penalty_config['base'])
        
        return max_penalty
    
    def should_accept(self, opinion_score, penalty_score, conditions_met):
        """判断是否应该接受为观点"""
        thresholds = self.config['thresholds']
        
        if not conditions_met:
            return False
        
        if penalty_score >= 20:
            required_score = penalty_score * thresholds['penalty_multiplier']
            return (opinion_score > required_score) and (opinion_score >= thresholds['min_with_penalty'])
        else:
            return (opinion_score > penalty_score) and (opinion_score >= thresholds['base_opinion'])

# 全局规则引擎实例（延迟初始化）
_rule_engine = None

def get_rule_engine():
    """获取全局规则引擎实例"""
    global _rule_engine
    if _rule_engine is None:
        _rule_engine = RuleEngine()
    return _rule_engine

# =========================
# 特征提取器（统一接口 + 缓存）
# =========================
class FeatureExtractor:
    """统一的特征提取接口，支持缓存和批量提取"""
    
    def __init__(self, cache_size=10000):
        self.cache = {}
        self.cache_size = cache_size
        self._compiled_patterns = {}
        self._verb_sets = {
            'strong': OPINION_VERBS_STRONG,
            'medium': OPINION_VERBS_MEDIUM,
            'weak': OPINION_VERBS_WEAK
        }
    
    def _get_cache_key(self, sentence, sent_doc):
        """生成缓存键"""
        if sent_doc is not None:
            # 使用句子文本和token数量作为键
            return f"{sentence[:100]}_{len(sent_doc)}"
        return sentence[:100]
    
    def extract_features(self, sentence: str, sent_doc=None, use_cache=True):
        """提取句子特征（统一接口）"""
        cache_key = self._get_cache_key(sentence, sent_doc) if use_cache else None
        
        if use_cache and cache_key in self.cache:
            return self.cache[cache_key]
        
        features = self._extract_features_impl(sentence, sent_doc)
        
        if use_cache:
            if len(self.cache) >= self.cache_size:
                # 简单的LRU：删除最旧的条目（保留最近使用的）
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
            self.cache[cache_key] = features
        
        return features
    
    def _extract_features_impl(self, sentence: str, sent_doc=None):
        """特征提取实现"""
        sent_lower = sentence.lower()
        features = {}
        
        # 1. 动词特征
        if sent_doc is not None:
            features.update(self._extract_verb_features(sent_doc))
        else:
            # 回退到简单文本匹配
            features['has_strong_verb'] = any(verb in sent_lower for verb in self._verb_sets['strong'])
            features['has_medium_verb'] = any(verb in sent_lower for verb in self._verb_sets['medium'])
            features['has_weak_verb_only'] = any(verb in sent_lower for verb in self._verb_sets['weak']) and not features.get('has_strong_verb') and not features.get('has_medium_verb')
        
        # 2. 模式匹配特征
        features.update(self._extract_pattern_features(sentence))
        
        # 3. 结构特征
        if sent_doc is not None:
            features.update(self._extract_structure_features(sent_doc, sentence))
        
        # 4. 断言特征
        features.update(self._extract_assertion_features(sentence, sent_lower))
        
        # 5. 非观点指示器
        features.update(self._extract_non_opinion_features(sentence, sent_lower, features))
        
        return features
    
    def _extract_verb_features(self, sent_doc):
        """提取动词特征"""
        features = {
            'has_strong_verb': False,
            'has_medium_verb': False,
            'has_weak_verb_only': False,
            'matched_verb': None
        }
        
        for token in sent_doc:
            lemma_lower = token.lemma_.lower()
            if lemma_lower in self._verb_sets['strong']:
                features['has_strong_verb'] = True
                features['matched_verb'] = lemma_lower
                break
        
        if not features['has_strong_verb']:
            for token in sent_doc:
                lemma_lower = token.lemma_.lower()
                if lemma_lower in self._verb_sets['medium']:
                    features['has_medium_verb'] = True
                    features['matched_verb'] = lemma_lower
                    break
        
        if not (features['has_strong_verb'] or features['has_medium_verb']):
            for token in sent_doc:
                lemma_lower = token.lemma_.lower()
                if lemma_lower in self._verb_sets['weak']:
                    features['has_weak_verb_only'] = True
                    features['matched_verb'] = lemma_lower
                    break
        
        return features
    
    def _extract_pattern_features(self, sentence):
        """提取模式匹配特征"""
        features = {
            'has_comparison': False,
            'has_evaluation': False,
            'has_negation': False,
            'matches_template': False
        }
        
        for pattern in COMPARISON_PATTERNS:
            if get_compiled_pattern(pattern).search(sentence):
                features['has_comparison'] = True
                break
        
        for pattern in EVALUATION_PATTERNS:
            if get_compiled_pattern(pattern).search(sentence):
                features['has_evaluation'] = True
                break
        
        for pattern in NEGATION_PATTERNS:
            if get_compiled_pattern(pattern).search(sentence):
                features['has_negation'] = True
                break
        
        features['matches_template'] = any(
            get_compiled_pattern(template['pattern']).search(sentence)
            for template in OPINION_TEMPLATES
        )
        
        return features
    
    def _extract_structure_features(self, sent_doc, sentence):
        """提取结构特征"""
        features = {
            'has_subject_predicate': False,
            'has_verb_or_adj': False,
            'has_noun': False,
            'sentence_length': len(sentence.split())
        }
        
        has_verb_or_adj = any(token.pos_ in ["VERB", "AUX", "ADJ"] for token in sent_doc)
        has_noun = any(token.pos_ in ["NOUN", "PROPN"] for token in sent_doc)
        
        features['has_verb_or_adj'] = has_verb_or_adj
        features['has_noun'] = has_noun
        features['has_subject_predicate'] = (has_verb_or_adj and has_noun) or (has_verb_or_adj and features['sentence_length'] >= 5)
        
        return features
    
    def _extract_assertion_features(self, sentence, sent_lower):
        """提取断言特征"""
        features = {
            'has_assertion': False,
            'has_domain_assertion': False,
            'has_numeric_assertion': False,
            'has_statistical_assertion': False,
            'has_necessity_assertion': False,
            'has_risk_assertion': False,
            'has_comparison_assertion': False,
            'has_result_verb': False
        }
        
        # 领域断言
        domain_indicators = ['accuracy', 'precision', 'recall', 'performance', 'efficiency', 
                            'result', 'outcome', 'finding', 'evidence', 'observation']
        features['has_domain_assertion'] = any(ind in sent_lower for ind in domain_indicators)
        
        # 数值断言
        features['has_numeric_assertion'] = bool(re.search(
            r'\d+%|\d+\.\d+%|\d+\s+percent|\d+\.\d+[-]?fold|\d+[-]?fold\s+(increased|decreased|higher|lower|risk|chance)',
            sentence, re.IGNORECASE))
        
        # 统计断言
        features['has_statistical_assertion'] = bool(re.search(
            r'(significant|similar|no\s+significant|statistically\s+significant)\s+(difference|differences|association|correlation|relationship|effect|impact)',
            sentence, re.IGNORECASE))
        
        # 必要性断言
        features['has_necessity_assertion'] = bool(re.search(
            r'\b(needed|required|necessary|essential|critical|crucial)\s+(?:for|to)\b', sentence, re.IGNORECASE))
        
        # 风险断言
        features['has_risk_assertion'] = bool(re.search(
            r'\b(risk|risks)\s+(?:of|for)\b|\b(at\s+)?(?:high|low|increased|decreased|elevated|reduced)\s+(?:risk|risks)\s+(?:of|for)\b',
            sentence, re.IGNORECASE))
        
        # 结果动词
        result_verbs = ['found', 'obtained', 'achieved', 'attained', 'accomplished', 'realized',
                       'discovered', 'identified', 'revealed', 'demonstrated', 'showed']
        features['has_result_verb'] = any(verb in sent_lower for verb in result_verbs)
        
        # 综合断言
        features['has_assertion'] = (features['has_comparison'] or features['has_evaluation'] or 
                                    features['has_negation'] or features['has_domain_assertion'] or
                                    features['has_numeric_assertion'] or features['has_result_verb'] or
                                    features['has_statistical_assertion'] or features['has_necessity_assertion'] or
                                    features['has_risk_assertion'] or features['has_comparison_assertion'])
        
        return features
    
    def _extract_non_opinion_features(self, sentence, sent_lower, existing_features):
        """提取非观点指示器特征"""
        features = {
            'is_pure_data_desc': False,
            'is_method_description': False,
            'is_experimental_design': False,
            'is_procedure_description': False,
            'is_pure_description': False
        }
        
        # 简化的非观点检测（完整实现在verify_opinion_by_rules中）
        # 这里只提取基础特征，详细判断在规则引擎中完成
        
        return features
    
    def clear_cache(self):
        """清空缓存"""
        self.cache.clear()

# 全局特征提取器实例（延迟初始化）
_feature_extractor = None

def get_feature_extractor():
    """获取全局特征提取器实例"""
    global _feature_extractor
    if _feature_extractor is None:
        _feature_extractor = FeatureExtractor()
    return _feature_extractor

# =========================
# 可解释性机制（决策路径记录和置信度解释）
# =========================
@dataclass
class DecisionPath:
    """决策路径记录"""
    sentence: str
    stage: str  # 'stage1', 'stage2', 'stage3', etc.
    decision: str  # 'accepted', 'rejected', 'partial'
    confidence: float  # 0.0-1.0
    features: Dict[str, any] = field(default_factory=dict)
    rules_triggered: List[str] = field(default_factory=list)
    templates_matched: List[int] = field(default_factory=list)
    reasoning: str = ""
    timestamp: float = field(default_factory=time.time)

class ExplainabilityTracker:
    """可解释性追踪器：记录决策路径和置信度"""
    
    def __init__(self, max_records=1000):
        self.decision_paths = []
        self.max_records = max_records
        self.stats = {
            'total_decisions': 0,
            'accepted': 0,
            'rejected': 0,
            'by_stage': defaultdict(int),
            'by_confidence_range': defaultdict(int)
        }
    
    def record_decision(self, path: DecisionPath):
        """记录决策路径"""
        self.decision_paths.append(path)
        self.stats['total_decisions'] += 1
        
        if path.decision == 'accepted':
            self.stats['accepted'] += 1
        elif path.decision == 'rejected':
            self.stats['rejected'] += 1
        
        self.stats['by_stage'][path.stage] += 1
        
        # 按置信度范围统计
        if path.confidence >= 0.9:
            self.stats['by_confidence_range']['high'] += 1
        elif path.confidence >= 0.7:
            self.stats['by_confidence_range']['medium'] += 1
        else:
            self.stats['by_confidence_range']['low'] += 1
        
        # 限制记录数量
        if len(self.decision_paths) > self.max_records:
            self.decision_paths.pop(0)
    
    def generate_explanation(self, path: DecisionPath) -> str:
        """生成可读的解释"""
        explanation_parts = []
        
        explanation_parts.append(f"阶段: {path.stage}")
        explanation_parts.append(f"决策: {path.decision}")
        explanation_parts.append(f"置信度: {path.confidence:.2%}")
        
        if path.features:
            explanation_parts.append("\n特征:")
            for key, value in path.features.items():
                if value:
                    explanation_parts.append(f"  - {key}: {value}")
        
        if path.rules_triggered:
            explanation_parts.append(f"\n触发的规则 ({len(path.rules_triggered)}):")
            for rule in path.rules_triggered[:5]:  # 最多显示5个
                explanation_parts.append(f"  - {rule}")
        
        if path.templates_matched:
            explanation_parts.append(f"\n匹配的模板 ({len(path.templates_matched)}):")
            for template_idx in path.templates_matched[:3]:  # 最多显示3个
                explanation_parts.append(f"  - 模板 #{template_idx}")
        
        if path.reasoning:
            explanation_parts.append(f"\n推理: {path.reasoning}")
        
        return "\n".join(explanation_parts)
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        return {
            'total_decisions': self.stats['total_decisions'],
            'accepted': self.stats['accepted'],
            'rejected': self.stats['rejected'],
            'acceptance_rate': self.stats['accepted'] / max(1, self.stats['total_decisions']),
            'by_stage': dict(self.stats['by_stage']),
            'by_confidence_range': dict(self.stats['by_confidence_range']),
            'recent_decisions': len(self.decision_paths)
        }
    
    def clear(self):
        """清空记录"""
        self.decision_paths.clear()
        self.stats = {
            'total_decisions': 0,
            'accepted': 0,
            'rejected': 0,
            'by_stage': defaultdict(int),
            'by_confidence_range': defaultdict(int)
        }

# 全局可解释性追踪器实例（延迟初始化）
_explainability_tracker = None

def get_explainability_tracker():
    """获取全局可解释性追踪器实例"""
    global _explainability_tracker
    if _explainability_tracker is None:
        _explainability_tracker = ExplainabilityTracker()
    return _explainability_tracker

def calculate_confidence(features: Dict, opinion_score: float, penalty_score: float, 
                        conditions_met: bool) -> float:
    """计算决策置信度（0.0-1.0）"""
    if not conditions_met:
        return 0.0
    
    # 基础置信度：基于观点分数和惩罚分数的差值
    score_diff = opinion_score - penalty_score
    if score_diff <= 0:
        return 0.0
    
    # 归一化到0-1范围（假设最大分数差为100）
    base_confidence = min(1.0, score_diff / 100.0)
    
    # 特征增强：强特征增加置信度
    feature_boost = 0.0
    if features.get('has_strong_verb'):
        feature_boost += 0.15
    elif features.get('has_medium_verb'):
        feature_boost += 0.10
    
    if features.get('matches_template'):
        feature_boost += 0.10
    
    if features.get('has_statistical_assertion'):
        feature_boost += 0.05
    
    # 特征惩罚：非观点特征降低置信度
    feature_penalty = 0.0
    if features.get('is_pure_data_desc') or features.get('is_method_description'):
        feature_penalty += 0.20
    
    final_confidence = min(1.0, base_confidence + feature_boost - feature_penalty)
    return max(0.0, final_confidence)

# 观点性动词分类（保留用于向后兼容）
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
    'compare', 'contrast', 'differentiate', 'distinguish', 'separate'
}

# 编译正则表达式缓存（计算优化）
_compiled_patterns_cache = {}

def get_compiled_pattern(pattern):
    """获取编译后的正则表达式（缓存优化）"""
    if pattern not in _compiled_patterns_cache:
        _compiled_patterns_cache[pattern] = re.compile(pattern, re.IGNORECASE)
    return _compiled_patterns_cache[pattern]

# 比较性表述模式
COMPARISON_PATTERNS = [
    r'\b(better|worse|superior|inferior|outperforms?|exceeds?|surpasses?|beats?)\b',
    r'\b(more|less)\s+(effective|efficient|accurate|precise|robust|reliable|scalable)\b',
    r'\b(improves?|enhances?|increases?|reduces?|decreases?|boosts?|elevates?)\b',
    r'\b(higher|lower|greater|smaller|faster|slower|larger|smaller)\s+(performance|accuracy|efficiency|speed|cost|error|rate)\b',
    r'\b(compared\s+to|compared\s+with|in\s+comparison\s+to|relative\s+to)\b',
    r'\b(agreement|consistent|accordance|accord)\s+with\b',
    r'\b(similar|different|distinct|comparable|equivalent)\b',
    r'\b(very|quite|highly|extremely|significantly)\s+(different|similar|distinct|comparable|equivalent|high|low)\b',
    r'\b(exactly|approximately|nearly|almost)\s+(equivalent|equal|same|different)\b',
    r'\b(correlation|correlations)\s+(coefficient|coefficients|between|among|with)\b',
    r'\b(high|low|strong|weak|positive|negative)\s+(correlation|correlations)\b',
    r'\b(lower|higher|greater|smaller|faster|slower|larger|smaller)\s+than\b',
    r'\b(up\s+to|down\s+to|similar\s+to|equal\s+to)\b',
    r'\b(dominant|predominant|primary|main|major|key|principal)\b',
    r'\b(is|are|was|were)\s+(dominant|predominant|primary|main|major|key|principal)\b',
    r'\b(better|best|well|poorly|badly)\s+(?:fitted|fit|matched|matched\s+by)\s+(?:by|with|to)\b',
    r'\b(?:fitted|fit|matched)\s+(?:by|with|to)\s+(?:the|a|an)\b',
    r'\b(searched|search|searches)\s+(?:for|whether|if)\b',
    r'\b(tested|test|tests)\s+(?:whether|if|for)\b'
]

# 评价性表述模式
EVALUATION_PATTERNS = [
    r'\b(effective|efficient|significant|improved|novel|superior|excellent|innovative|original|pioneering|breakthrough|groundbreaking|state-of-the-art)\b',
    r'\b(significantly|substantially|dramatically|greatly|slightly|marginally|considerably|remarkably|notably)\b',
    r'\b(robust|scalable|reliable|feasible|practical|applicable|generalizable|versatile|flexible)\b',
    r'\b(accurate|precise|reliable|valid|sound|solid|strong|weak|promising|encouraging)\b',
    r'\b(achievement|success|progress|advancement|improvement|enhancement|optimization)\b',
    r'\b(high|low|good|poor|excellent|outstanding|remarkable|notable|considerable)\s+(performance|accuracy|efficiency|quality|result|outcome)\b',
    r'\b(dominant|predominant|primary|main|major|key|principal)\b',
    r'\b(effect|effects|formation|impact|impacts|influence|influences|contribution|contributions)\b',
    r'\b(evident|not\s+so\s+evident|distinctive|characteristic|feature|features)\b',
    r'\b(valued|valuable|debatable|controversial|questionable|doubtful|uncertain|available|accessible)\b',
    r'\b(play|plays|played)\s+(?:a|an)\s+(?:crucial|important|key|significant|vital|essential|critical|major)\s+(?:role|part|function)\s+(?:in|for)\b',
    r'\b(can|could|may|might|should|would)\s+(?:play|serve|act|function)\s+(?:a|an)?\s*(?:crucial|important|key|significant|vital|essential|critical|major)?\s*(?:role|part|function)?\s*(?:in|for)?\b',
    r'\b(can|could|may|might|should|would)\s+(?:act|serve|function|work|operate)\s+(?:as|by|through)\b',
    r'\b(seems?|appears?|appeared)\s+(?:to|that)\b',
    r'\b(needed|required|necessary|essential|critical|crucial)\s+(?:for|to)\b',
    r'\b(risk|risks)\s+(?:of|for)\b',
    r'\b(at\s+)?(?:high|low|increased|decreased|elevated|reduced)\s+(?:risk|risks)\s+(?:of|for)\b'
]

# 否定观点模式
NEGATION_PATTERNS = [
    r'\b(does\s+not|did\s+not|fails?\s+to|cannot|unable\s+to|no\s+significant|lack\s+of|absence\s+of)\b',
    r'\b(not\s+better|not\s+effective|not\s+improve|not\s+achieve|not\s+obtain)\b',
    r'\b(without\s+significant|no\s+evidence|no\s+difference|no\s+improvement)\b',
    r'\b(limited|restricted|constrained|insufficient|inadequate|deficient)\b',
    r'\b(there\s+was|there\s+were)\s+no\s+(association|correlation|relationship|difference|effect|impact|link|connection)\b',
    r'\bno\s+(association|correlation|relationship|difference|effect|impact|link|connection)\s+(between|among|with|in)\b',
    r'\b(was|were)\s+no\s+(association|correlation|relationship|difference|effect|impact|link|connection)\b',
    r'\b(none|no\s+one|nothing)\s+(of|among)\s+.*\s+(fulfilled|met|satisfied|achieved|reached)\b',
    r'\b(no|not\s+any)\s+\w+\s+(fulfilled|met|satisfied|achieved|reached|obtained)\b',
    r'\b(did\s+not|does\s+not|do\s+not)\s+(follow|fit|fits|conform|match|agree|comply)\b',
    r'\b(may|might|could|should|would)\s+not\s+(?:be\s+)?(?:affected|influenced|changed|modified|altered)\b',
    r'\b(not|not\s+be)\s+(?:affected|influenced|changed|modified|altered)\b'
]

OPINION_TEMPLATES = [
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(outperforms?|exceeds?|surpasses?|beats?)\s+(\w+(?:\s+\w+)*?)(?:\s+on\s+([^\.]+))?',
        'slots': ['object', 'predicate', 'target', 'context'],
        'priority': 1
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+is\s+(better|worse|superior|inferior)\s+than\s+(\w+(?:\s+\w+)*?)(?:\s+for\s+([^\.]+))?',
        'slots': ['object', 'predicate', 'target', 'context'],
        'priority': 1
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(significantly|substantially|dramatically|greatly|slightly|marginally)\s+(outperforms?|exceeds?|improves?)\s+(\w+(?:\s+\w+)*?)',
        'slots': ['object', 'strength', 'predicate', 'target'],
        'priority': 1
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+is\s+(effective|efficient|significant|improved|novel|superior)(?:\s+for\s+([^\.]+))?',
        'slots': ['object', 'predicate', 'context'],
        'priority': 2
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(significantly|substantially|dramatically|greatly|slightly|marginally)\s+(improves?|enhances?|increases?|reduces?)\s+(\w+(?:\s+\w+)*?)(?:\s+on\s+([^\.]+))?',
        'slots': ['object', 'strength', 'predicate', 'target', 'context'],
        'priority': 2
    },
    {
        'pattern': r'(we|our|the\s+author|this\s+paper)\s+(show|demonstrate|prove|find|argue|claim|suggest)\s+that\s+(\w+(?:\s+\w+)*?)\s+(\w+(?:\s+\w+)*?)(?:\s+on\s+([^\.]+))?',
        'slots': ['subject', 'predicate', 'object', 'judgment', 'context'],
        'priority': 2
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+does\s+not\s+(outperform|exceed|surpass|beat|improve)\s+(\w+(?:\s+\w+)*?)(?:\s+on\s+([^\.]+))?',
        'slots': ['object', 'predicate', 'target', 'context'],
        'priority': 3
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+fails?\s+to\s+(\w+(?:\s+\w+)*?)(?:\s+on\s+([^\.]+))?',
        'slots': ['object', 'predicate', 'context'],
        'priority': 3
    },
    {
        'pattern': r'when\s+([^,]+),\s+(\w+(?:\s+\w+)*?)\s+(\w+(?:\s+\w+)*?)(?:\s+on\s+([^\.]+))?',
        'slots': ['condition', 'object', 'predicate', 'context'],
        'priority': 4
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(\w+(?:\s+\w+)*?)\s+if\s+([^\.]+)',
        'slots': ['object', 'predicate', 'condition'],
        'priority': 4
    },
    {
        'pattern': r'(we|our|the\s+author|this\s+paper)\s+propose\s+(?:a\s+)?(?:new\s+)?(\w+(?:\s+\w+)*?)(?:\s+for\s+([^\.]+))?',
        'slots': ['subject', 'object', 'context'],
        'priority': 5
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+is\s+a\s+(\w+(?:\s+\w+)*?)\s+for\s+([^\.]+)',
        'slots': ['object', 'predicate', 'context'],
        'priority': 5
    },
    {
        'pattern': r'this\s+is\s+the\s+first\s+(?:work|paper|study|research)\s+to\s+(\w+(?:\s+\w+)*?)(?:\s+(\w+(?:\s+\w+)*?))?(?:\s+(?:on|for|in)\s+([^\.]+))?',
        'slots': ['predicate', 'object', 'context'],
        'priority': 2
    },
    {
        'pattern': r'(we|our|the\s+author|this\s+paper)\s+introduce\s+(?:a|an)\s+(?:novel|innovative|original|new|pioneering)\s+(\w+(?:\s+\w+)*?)(?:\s+(?:for|to|in)\s+([^\.]+))?',
        'slots': ['subject', 'object', 'context'],
        'priority': 2
    },
    {
        'pattern': r'a\s+breakthrough\s+(?:in|for)\s+(\w+(?:\s+\w+)*?)(?:\s+(\w+(?:\s+\w+)*?))?(?:\s+(?:on|for)\s+([^\.]+))?',
        'slots': ['object', 'predicate', 'context'],
        'priority': 2
    },
    {
        'pattern': r'(we|our|the\s+author|this\s+paper)\s+present\s+(?:a|an)\s+(?:novel|innovative|original|new|pioneering|groundbreaking)\s+(\w+(?:\s+\w+)*?)(?:\s+(?:for|to|in)\s+([^\.]+))?',
        'slots': ['subject', 'object', 'context'],
        'priority': 2
    },
    {
        'pattern': r'(we|our|the\s+author|this\s+paper)\s+develop\s+(?:a|an)\s+(?:novel|innovative|original|new|pioneering)\s+(\w+(?:\s+\w+)*?)(?:\s+(?:for|to|in)\s+([^\.]+))?',
        'slots': ['subject', 'object', 'context'],
        'priority': 2
    },
    {
        'pattern': r'(the|this|our)\s+(\w+(?:\s+\w+)*?)\s+(?:analysis|study|investigation|experiment|method|approach)\s+(?:show|demonstrate|indicate|reveal|find|suggest)\s+that\s+(\w+(?:\s+\w+)*?)(?:\s+(\w+(?:\s+\w+)*?))?',
        'slots': ['subject', 'object', 'predicate', 'judgment'],
        'priority': 2
    },
    {
        'pattern': r'(compared\s+to|compared\s+with|in\s+comparison\s+to)\s+(\w+(?:\s+\w+)*?),\s+(\w+(?:\s+\w+)*?)\s+(show|demonstrate|achieve|obtain)\s+(\w+(?:\s+\w+)*?)',
        'slots': ['context', 'target', 'object', 'predicate', 'judgment'],
        'priority': 1
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(?:was|were)\s+(investigated|studied|analyzed|examined|evaluated)\s+(?:using|with|by)\s+(\w+(?:\s+\w+)*?)(?:\.|,)\s+(?:the|and)\s+(?:result|finding|outcome)\s+(?:show|demonstrate|indicate|reveal)\s+that\s+(\w+(?:\s+\w+)*?)',
        'slots': ['object', 'predicate', 'context', 'judgment'],
        'priority': 3
    },
    {
        'pattern': r'(the|this)\s+(?:experimental|experiment|analysis|study)\s+(?:result|finding|outcome)\s+(?:show|demonstrate|indicate|reveal|suggest)\s+that\s+(\w+(?:\s+\w+)*?)\s+(\w+(?:\s+\w+)*?)',
        'slots': ['subject', 'object', 'predicate'],
        'priority': 2
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(?:is|are)\s+(?:in|found\s+to\s+be)\s+(?:good|excellent|strong|significant)\s+(?:agreement|accordance|accord)\s+with\s+(\w+(?:\s+\w+)*?)',
        'slots': ['object', 'target'],
        'priority': 3
    },
    {
        'pattern': r'(we|our|the\s+author|this\s+paper|the\s+study)\s+(?:achieve|obtain|attain|accomplish|realize)\s+(\w+(?:\s+\w+)*?)(?:\s+(?:of|on|for)\s+([^\.]+))?',
        'slots': ['subject', 'object', 'context'],
        'priority': 2
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(?:achieve|obtain|attain|accomplish|realize)\s+(\d+%|\d+\.\d+%|\d+\s+percent)(?:\s+(?:of|on)\s+([^\.]+))?',
        'slots': ['object', 'predicate', 'context'],
        'priority': 1
    },
    {
        'pattern': r'(no|not\s+any)\s+(?:significant|noticeable|appreciable)\s+(?:difference|improvement|change|effect)\s+(?:was|were|could\s+be)\s+(?:found|observed|detected|identified)',
        'slots': ['predicate'],
        'priority': 3
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(?:prove|proves|proved)\s+to\s+be\s+(\w+(?:\s+\w+)*?)(?:\s+(?:for|in|on)\s+([^\.]+))?',
        'slots': ['object', 'predicate', 'context'],
        'priority': 2
    },
    {
        'pattern': r'(?:the|this|our)\s+(\w+(?:\s+\w+)*?)\s+(?:result|finding|outcome|conclusion|evidence)\s+(?:show|demonstrate|indicate|reveal|suggest|prove)\s+that\s+(\w+(?:\s+\w+)*?)\s+(\w+(?:\s+\w+)*?)',
        'slots': ['subject', 'object', 'predicate'],
        'priority': 2
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(?:play|plays|played)\s+(?:a|an)\s+(?:crucial|important|key|significant|vital|essential)\s+(?:role|part|function)\s+(?:in|for)\s+(\w+(?:\s+\w+)*?)',
        'slots': ['object', 'context'],
        'priority': 2
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(?:is|are|was|were)\s+(?:more|less)\s+(?:likely|effective|efficient|accurate)\s+(?:than|to|for)\s+(\w+(?:\s+\w+)*?)',
        'slots': ['object', 'target'],
        'priority': 1
    },
    {
        'pattern': r'(?:there|there\s+was|there\s+were)\s+(?:no|not\s+any)\s+(?:significant|noticeable|appreciable|statistical)\s+(?:difference|improvement|change|effect|association|correlation)\s+(?:between|in|among)\s+(\w+(?:\s+\w+)*?)',
        'slots': ['object'],
        'priority': 3
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(?:better|worse|more|less)\s+(?:correlate|correlates|correlated)\s+(?:with|than)\s+(\w+(?:\s+\w+)*?)',
        'slots': ['object', 'target'],
        'priority': 1
    },
    {
        'pattern': r'(?:we|our|the\s+author|this\s+paper|the\s+study)\s+(?:report|reports|reported|present|presents|presented|describe|describes|described)\s+(?:a|an)\s+(\w+(?:\s+\w+)*?)(?:\s+(?:case|study|method|approach|technique))?(?:\s+(?:of|for|in)\s+([^\.]+))?',
        'slots': ['object', 'context'],
        'priority': 3
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(?:summarize|summarizes|summarized|review|reviews|reviewed)\s+(?:the|a|an)\s+(\w+(?:\s+\w+)*?)(?:\s+(?:of|for|in)\s+([^\.]+))?',
        'slots': ['subject', 'object', 'context'],
        'priority': 3
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(?:aim|aims|aimed)\s+(?:at|to)\s+(\w+(?:\s+\w+)*?)(?:\s+(?:of|for|in)\s+([^\.]+))?',
        'slots': ['subject', 'object', 'context'],
        'priority': 3
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(?:increase|increases|increased|decrease|decreases|decreased|improve|improves|improved|enhance|enhances|enhanced)\s+(?:the|a|an)\s+(\w+(?:\s+\w+)*?)(?:\s+(?:of|for|in)\s+([^\.]+))?',
        'slots': ['subject', 'object', 'context'],
        'priority': 2
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(?:provide|provides|provided|have|has|had)\s+(?:the\s+)?(?:potential\s+)?(?:to\s+)?(?:provide|improve|enhance|increase|decrease)\s+(\w+(?:\s+\w+)*?)',
        'slots': ['object', 'predicate'],
        'priority': 3
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(?:should|must|need|needs|needed)\s+(?:be|to\s+be)\s+(?:taken|considered|accounted|into\s+account)\s+(?:in|for)\s+(\w+(?:\s+\w+)*?)',
        'slots': ['object', 'context'],
        'priority': 3
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(?:evolve|evolves|evolved|evolving)\s+(?:from|to)\s+(\w+(?:\s+\w+)*?)',
        'slots': ['object', 'target'],
        'priority': 3
    },
    {
        'pattern': r'(\w+(?:\s+\w+)*?)\s+(?:shed|sheds|shedding)\s+(?:light|insight)\s+(?:on|into)\s+(\w+(?:\s+\w+)*?)',
        'slots': ['subject', 'object'],
        'priority': 3
    }
]

def verify_opinion_by_rules(sentence: str, sent_doc) -> bool:
    """基于规则的特征验证：判断句子是否为观点句"""
    sent_lower = sentence.lower()
    has_strong_verb = False
    has_medium_verb = False
    matched_verb = None
    
    phrase_verbs_medium = ['leads to', 'lead to', 'led to', 'results in', 'result in', 'resulted in',
                          'causes', 'cause', 'caused', 'enables', 'enable', 'enabled',
                          'allows', 'allow', 'allowed', 'prevents', 'prevent', 'prevented',
                          'reduces', 'reduce', 'reduced', 'increases', 'increase', 'increased',
                          'improves', 'improve', 'improved', 'enhances', 'enhance', 'enhanced',
                          'serve to', 'serves to', 'served to', 'continue to', 'continues to', 'continued to',
                          'tend to', 'tends to', 'tended to', 'appear to', 'appears to', 'appeared to',
                          'contribute to', 'contributes to', 'contributed to',
                          'influence on', 'influences on', 'influenced on',
                          'affect on', 'affects on', 'affected on',
                          'impact on', 'impacts on', 'impacted on',
                          'play a role', 'plays a role', 'played a role',
                          'play an role', 'plays an role', 'played an role',
                          'play a crucial role', 'play an important role', 'play a key role',
                          'play a significant role', 'play a vital role', 'play an essential role',
                          'play a critical role', 'play a major role']
    for phrase_verb in phrase_verbs_medium:
        if phrase_verb in sent_lower:
            has_medium_verb = True
            matched_verb = phrase_verb
            break
    
    if not (has_strong_verb or has_medium_verb):
        for token in sent_doc:
            verb_lemma = token.lemma_.lower()
            if verb_lemma in OPINION_VERBS_STRONG:
                has_strong_verb = True
                matched_verb = verb_lemma
                break
            elif verb_lemma in OPINION_VERBS_MEDIUM:
                has_medium_verb = True
                matched_verb = verb_lemma
    
    has_weak_verb_only = False
    if not (has_strong_verb or has_medium_verb):
        for token in sent_doc:
            if token.lemma_.lower() in OPINION_VERBS_WEAK:
                has_weak_verb_only = True
                break
    
    has_subject_predicate = False
    has_verb_or_adj = False
    has_noun = False
    
    for token in sent_doc:
        if token.pos_ in ["VERB", "AUX", "ADJ"]:
            has_verb_or_adj = True
        if token.pos_ in ["NOUN", "PROPN"]:
            has_noun = True
    
    if (has_verb_or_adj and has_noun) or (has_verb_or_adj and len(sentence.split()) >= 5):
        has_subject_predicate = True
    
    has_assertion = False
    
    has_comparison = any(re.search(pattern, sentence, re.IGNORECASE) for pattern in COMPARISON_PATTERNS)
    has_evaluation = any(re.search(pattern, sentence, re.IGNORECASE) for pattern in EVALUATION_PATTERNS)
    has_negation = any(re.search(pattern, sentence, re.IGNORECASE) for pattern in NEGATION_PATTERNS)
    
    # 检查是否是纯数据描述（需要过滤，收紧检测）
    is_pure_data_desc = False
    # 模式：包含百分比或数字，但没有观点性关键词
    has_percentage = bool(re.search(r'\d+%|\d+\.\d+%', sentence))
    has_number = bool(re.search(r'\d+', sentence))
    has_data_keywords = any(kw in sent_lower for kw in ['contain', 'contains', 'contained', 'comprise', 'comprises', 'comprised',
                                                       'similar to', 'similar', 'up to', 'down to'])
    has_opinion_keywords = any(kw in sent_lower for kw in ['result', 'finding', 'conclusion', 'evidence', 'outcome', 
                                                          'important', 'crucial', 'significant', 'effective', 'better', 'worse',
                                                          'show', 'demonstrate', 'indicate', 'reveal', 'suggest', 'prove',
                                                          'improve', 'enhance', 'increase', 'reduce', 'decrease'])
    sentence_words = sentence.split()
    is_short_sentence = len(sentence_words) < 20
    has_data_list_keywords = any(kw in sent_lower for kw in [
        'were as follows', 'stages of', 'were present in', 'were found in',
        'were observed in', 'were detected in', 'were identified in',
        'consisted of', 'comprised', 'contained', 'included'
    ])
    if (has_percentage or has_number) and not (has_strong_verb or has_medium_verb) and not has_opinion_keywords:
        if (is_short_sentence and (has_percentage or len(re.findall(r'\d+', sentence)) >= 2)) or has_data_keywords or has_data_list_keywords:
            is_pure_data_desc = True
    elif (has_assertion and not (has_strong_verb or has_medium_verb or has_weak_verb_only)) and (has_percentage or has_number) and not has_opinion_keywords:
        if is_short_sentence or len(re.findall(r'\d+', sentence)) >= 2 or has_data_list_keywords:
            is_pure_data_desc = True
    elif (has_weak_verb_only and has_assertion) and (has_percentage or has_number) and has_data_list_keywords and not has_opinion_keywords:
        if is_short_sentence or len(re.findall(r'\d+', sentence)) >= 2:
            is_pure_data_desc = True
    elif (has_medium_verb and has_assertion) and (has_percentage or has_number) and has_data_list_keywords and not has_opinion_keywords:
        if is_short_sentence or len(re.findall(r'\d+', sentence)) >= 2:
            is_pure_data_desc = True
    
    is_method_description = False
    method_keywords = ['material and methods', 'methods:', 'method:', 'to experimentally', 'to examine', 'to investigate',
                      'we used', 'we employed', 'we applied', 'were used', 'were employed', 'were applied',
                      'were determined', 'were measured', 'were recorded', 'were collected',
                      'was performed', 'was conducted', 'was analyzed', 'procedure', 'protocol', 'method was', 'technique was',
                      'were assigned', 'were fed', 'consisted of', 'was added', 'was selected', 'was chosen',
                      'experimental design', 'study design', 'research design', 'data collection', 'data acquisition',
                      'sample preparation', 'specimen preparation', 'material preparation',
                      'random sampling', 'sampling was', 'was applied to', 'were applied to',
                      'was applied to determine', 'was applied to measure', 'was applied to assess',
                      'were collected and', 'were counted', 'was counted', 'numbers counted']
    if any(kw in sent_lower for kw in method_keywords):
        has_result_keywords = any(kw in sent_lower for kw in ['result', 'finding', 'conclusion', 'evidence', 'outcome',
                                                              'show', 'demonstrate', 'indicate', 'reveal', 'suggest',
                                                              'important', 'crucial', 'significant', 'effective', 'better', 'worse',
                                                              'improve', 'enhance', 'increase', 'reduce', 'decrease',
                                                              'prove', 'confirm', 'support', 'justify', 'found', 'observed',
                                                              'achieved', 'obtained', 'correlated', 'associated', 'linked'])
        if not has_result_keywords and not (has_strong_verb or has_medium_verb):
            is_method_description = True
    
    is_experimental_design = False
    experimental_design_keywords = [
        'were randomly assigned', 'were fed', 'consisted of', 'was added to',
        'treatment diet', 'control diet', 'was selected', 'was chosen',
        'experimental group', 'control group', 'treatment group', 'placebo group',
        'randomized', 'randomization', 'blinded', 'double-blind', 'single-blind',
        'inclusion criteria', 'exclusion criteria', 'eligibility criteria'
    ]
    if any(kw in sent_lower for kw in experimental_design_keywords):
        has_result_keywords = any(kw in sent_lower for kw in ['result', 'finding', 'conclusion', 'evidence', 'outcome',
                                                              'show', 'demonstrate', 'indicate', 'reveal', 'suggest',
                                                              'important', 'crucial', 'significant', 'effective', 'better', 'worse'])
        if not has_result_keywords:
            is_experimental_design = True
    
    is_procedure_description = False
    procedure_keywords = [
        'procedure', 'protocol', 'technique', 'method', 'approach',
        'step', 'steps', 'process', 'processes', 'workflow', 'workflows',
        'algorithm', 'algorithms', 'implementation', 'implementations'
    ]
    procedure_verbs = ['simulated', 'simulate', 'simulates', 'simulating',
                      'applied', 'apply', 'applies', 'applying',
                      'used', 'use', 'uses', 'using',
                      'performed', 'perform', 'performs', 'performing',
                      'conducted', 'conduct', 'conducts', 'conducting',
                      'executed', 'execute', 'executes', 'executing',
                      'implemented', 'implement', 'implements', 'implementing',
                      'carried out', 'carries out', 'carry out']
    if any(kw in sent_lower for kw in procedure_keywords) or any(verb in sent_lower for verb in procedure_verbs):
        has_result_keywords = any(kw in sent_lower for kw in ['result', 'finding', 'conclusion', 'evidence', 'outcome',
                                                              'show', 'demonstrate', 'indicate', 'reveal', 'suggest',
                                                              'important', 'crucial', 'significant', 'effective', 'better', 'worse',
                                                              'improve', 'enhance', 'increase', 'reduce', 'decrease',
                                                              'prove', 'confirm', 'support', 'justify', 'found', 'observed',
                                                              'achieved', 'obtained', 'correlated', 'associated', 'linked'])
        if not has_result_keywords and not (has_strong_verb or has_medium_verb):
            is_procedure_description = True
    
    is_pure_description = False
    description_verbs = ['describe', 'described', 'describes', 'describing',
                       'discuss', 'discussed', 'discusses', 'discussing',
                       'present', 'presents', 'presented', 'presenting',
                       'introduce', 'introduces', 'introduced', 'introducing',
                       'review', 'reviews', 'reviewed', 'reviewing',
                       'summarize', 'summarizes', 'summarized', 'summarizing',
                       'outline', 'outlines', 'outlined', 'outlining']
    if any(verb in sent_lower for verb in description_verbs):
        has_result_keywords = any(kw in sent_lower for kw in ['result', 'finding', 'conclusion', 'evidence', 'outcome',
                                                              'show', 'demonstrate', 'indicate', 'reveal', 'suggest',
                                                              'important', 'crucial', 'significant', 'effective', 'better', 'worse',
                                                              'improve', 'enhance', 'increase', 'reduce', 'decrease',
                                                              'prove', 'confirm', 'support', 'justify', 'found', 'observed',
                                                              'achieved', 'obtained', 'correlated', 'associated', 'linked'])
        has_chapter_paper_study = any(phrase in sent_lower for phrase in [
            'chapter', 'this chapter', 'this paper', 'this study', 'this work',
            'the chapter', 'the paper', 'the study', 'the work',
            'paper describes', 'study describes', 'work describes',
            'chapter describes', 'chapter discusses', 'paper discusses', 'study discusses',
            'review article', 'this review', 'the review', 'article summarized', 'article summarizes'
        ])
        has_summary_keywords = any(phrase in sent_lower for phrase in [
            'summary', 'summaries', 'summarize', 'summarizes', 'summarized',
            'put in front', 'is put', 'are put', 'was put', 'were put',
            'is placed', 'are placed', 'was placed', 'were placed',
            'is given', 'are given', 'was given', 'were given',
            'is provided', 'are provided', 'was provided', 'were provided'
        ])
        has_purpose_phrase = any(phrase in sent_lower for phrase in [
            'in order to', 'in order to identify', 'in order to outline', 'in order to discuss',
            'to identify', 'to outline', 'to discuss', 'to describe', 'to summarize'
        ])
        if not has_result_keywords and not (has_strong_verb or has_medium_verb):
            if has_chapter_paper_study or (has_weak_verb_only and not has_assertion) or has_summary_keywords or has_purpose_phrase or (not has_assertion and not has_comparison and not has_evaluation):
                is_pure_description = True
    
    conclusion_indicators = ['conclude', 'conclusion', 'therefore', 'thus', 'hence', 'consequently', 
                            'in summary', 'in conclusion', 'to summarize', 'in summary', 'in brief']
    has_conclusion = any(ind in sent_lower for ind in conclusion_indicators)
    
    domain_assertion_indicators = ['accuracy', 'precision', 'recall', 'f1-score', 'f1', 'auc', 'roc',
                                   'performance', 'efficiency', 'throughput', 'latency', 'speed',
                                   'result', 'outcome', 'finding', 'evidence', 'observation',
                                   'achievement', 'success', 'improvement', 'enhancement',
                                   'agreement', 'consistent', 'accordance', 'accord',
                                   'effect', 'effects', 'formation', 'impact', 'impacts',
                                   'influence', 'influences', 'contribution', 'contributions',
                                   'distinctive', 'characteristic', 'feature', 'features']
    has_domain_assertion = any(ind in sent_lower for ind in domain_assertion_indicators)
    
    has_numeric_assertion = bool(re.search(r'\d+%|\d+\.\d+%|\d+\s+percent|\d+\.\d+[-]?fold|\d+[-]?fold\s+(increased|decreased|higher|lower|risk|chance)', sentence, re.IGNORECASE))
    
    has_statistical_assertion = bool(re.search(r'(significant|similar|no\s+significant|statistically\s+significant)\s+(difference|differences|association|correlation|relationship|effect|impact)', sentence, re.IGNORECASE))
    
    has_comparison_assertion = bool(re.search(r'\b(very|quite|highly|extremely|significantly)\s+(different|similar|distinct|comparable|equivalent|high|low)\b', sentence, re.IGNORECASE)) or \
                              bool(re.search(r'\b(exactly|approximately|nearly|almost)\s+(equivalent|equal|same|different)\b', sentence, re.IGNORECASE)) or \
                              bool(re.search(r'\b(high|low|strong|weak|positive|negative)\s+(correlation|correlations)\b', sentence, re.IGNORECASE)) or \
                              bool(re.search(r'\b(correlation|correlations)\s+(coefficient|coefficients|between|among|with)\b', sentence, re.IGNORECASE)) or \
                              bool(re.search(r'\b(lower|higher|greater|smaller|faster|slower|larger|smaller)\s+than\b', sentence, re.IGNORECASE)) or \
                              bool(re.search(r'\b(up\s+to|down\s+to|similar\s+to|equal\s+to)\b', sentence, re.IGNORECASE)) or \
                              bool(re.search(r'\b(is|are|was|were)\s+(dominant|predominant|primary|main|major|key|principal)\b', sentence, re.IGNORECASE)) or \
                              bool(re.search(r'\b(dominant|predominant|primary|main|major|key|principal)\b', sentence, re.IGNORECASE)) or \
                              bool(re.search(r'\b(better|best|well|poorly|badly)\s+(?:fitted|fit|matched|matched\s+by)\s+(?:by|with|to)\b', sentence, re.IGNORECASE)) or \
                              bool(re.search(r'\b(searched|search|searches)\s+(?:for|whether|if)\b', sentence, re.IGNORECASE)) or \
                              bool(re.search(r'\b(tested|test|tests)\s+(?:whether|if|for)\b', sentence, re.IGNORECASE)) or \
                              bool(re.search(r'\b(seems?|appears?|appeared)\s+(?:to|that)\b', sentence, re.IGNORECASE)) or \
                              bool(re.search(r'\b(can|could|may|might|should|would)\s+(?:act|serve|function|work|operate)\s+(?:as|by|through)\b', sentence, re.IGNORECASE))
    
    result_verbs = ['found', 'obtained', 'achieved', 'attained', 'accomplished', 'realized',
                    'discovered', 'identified', 'revealed', 'demonstrated', 'showed']
    result_verbs_passive = ['was detected', 'were detected', 'was observed', 'were observed',
                           'was found', 'were found', 'was identified', 'were identified',
                           'was discovered', 'were discovered', 'was revealed', 'were revealed']
    has_result_verb = any(verb in sent_lower for verb in result_verbs) or \
                     any(verb in sent_lower for verb in result_verbs_passive)
    
    has_necessity_assertion = bool(re.search(r'\b(needed|required|necessary|essential|critical|crucial)\s+(?:for|to)\b', sentence, re.IGNORECASE)) or \
                             bool(re.search(r'\bcan\s+be\s+(?:used|applied|employed|utilized)\b', sentence, re.IGNORECASE))
    
    has_risk_assertion = bool(re.search(r'\b(risk|risks)\s+(?:of|for)\b', sentence, re.IGNORECASE)) or \
                        bool(re.search(r'\b(at\s+)?(?:high|low|increased|decreased|elevated|reduced)\s+(?:risk|risks)\s+(?:of|for)\b', sentence, re.IGNORECASE))
    
    has_assertion = has_comparison or has_evaluation or has_negation or has_conclusion or \
                    has_domain_assertion or has_numeric_assertion or has_result_verb or \
                    has_statistical_assertion or has_necessity_assertion or has_risk_assertion or \
                    has_comparison_assertion
    
    matches_template = any(get_compiled_pattern(template['pattern']).search(sentence) 
                          for template in OPINION_TEMPLATES)
    
    abstract_nouns = ['method', 'approach', 'result', 'performance', 'effectiveness', 'efficiency',
                     'accuracy', 'improvement', 'enhancement', 'advantage', 'benefit', 'contribution',
                     'finding', 'evidence', 'conclusion', 'hypothesis', 'claim', 'proposal']
    has_abstract_noun = any(noun in sent_lower for noun in abstract_nouns)
    
    starts_with_conclusion = sent_lower.startswith('conclusion') or sent_lower.startswith('conclusion:')
    has_strong_assertion = matches_template or has_numeric_assertion or (starts_with_conclusion and has_assertion)
    
    has_implicit_opinion_verb = any(phrase in sent_lower for phrase in [
        'contribute to', 'contributes to', 'contributed to',
        'influence on', 'influences on', 'influenced on',
        'affect on', 'affects on', 'affected on',
        'impact on', 'impacts on', 'impacted on',
        'play a role', 'plays a role', 'played a role',
        'play an role', 'plays an role', 'played an role',
        'play a crucial role', 'play an important role', 'play a key role',
        'play a significant role', 'play a vital role', 'play an essential role',
        'play a critical role', 'play a major role'
    ])
    if has_medium_verb and matched_verb in ['contribute to', 'contributes to', 'contributed to',
                                            'play a role', 'plays a role', 'played a role',
                                            'play an role', 'plays an role', 'played an role',
                                            'play a crucial role', 'play an important role', 'play a key role',
                                            'play a significant role', 'play a vital role', 'play an essential role',
                                            'play a critical role', 'play a major role']:
        has_implicit_opinion_verb = False
    
    has_research_keywords_for_verb = any(kw in sent_lower for kw in [
        'finding', 'result', 'outcome', 'conclusion', 'evidence', 'observation', 'discovery',
        'important', 'crucial', 'significant', 'essential', 'critical', 'key', 'vital',
        'effective', 'efficient', 'better', 'worse', 'superior', 'inferior',
        'improve', 'enhance', 'increase', 'reduce', 'decrease',
        'show', 'demonstrate', 'indicate', 'reveal', 'suggest', 'prove', 'confirm',
        'support', 'justify', 'found', 'observed', 'achieved', 'obtained',
        'correlated', 'associated', 'linked', 'related', 'influenced', 'affected', 'impacted'
    ])
    sentence_length_ok = len(sentence.split()) >= 6
    verb_condition = has_strong_verb or has_medium_verb or \
                     has_weak_verb_only or \
                     has_implicit_opinion_verb or \
                     has_strong_assertion or has_statistical_assertion or has_necessity_assertion or has_risk_assertion or \
                     has_comparison_assertion or \
                     has_research_keywords_for_verb or \
                     has_assertion or \
                     has_comparison or \
                     has_evaluation or \
                     has_domain_assertion or \
                     has_numeric_assertion or \
                     has_result_verb or \
                     has_opinion_keywords or \
                     (len(sentence.split()) >= 6)
    
    has_research_keywords_for_structure = any(kw in sent_lower for kw in [
        'finding', 'result', 'outcome', 'conclusion', 'evidence', 'observation', 'discovery',
        'important', 'crucial', 'significant', 'essential', 'critical', 'key', 'vital',
        'effective', 'efficient', 'better', 'worse', 'superior', 'inferior'
    ])
    sentence_length_ok_for_structure = len(sentence.split()) >= 6
    if (has_strong_verb) or \
       (has_medium_verb) or \
       (has_weak_verb_only) or \
       (has_implicit_opinion_verb) or \
       (has_research_keywords_for_structure) or \
       (has_assertion) or \
       (has_comparison) or \
       (has_evaluation) or \
       (has_opinion_keywords) or \
       (has_domain_assertion) or \
       (has_numeric_assertion) or \
       (has_result_verb) or \
       (len(sentence.split()) >= 6):
        structure_condition = True
    else:
        structure_condition = has_subject_predicate
    
    has_research_keywords_in_assertion = any(kw in sent_lower for kw in [
        'finding', 'result', 'outcome', 'conclusion', 'evidence', 'observation', 'discovery',
        'important', 'crucial', 'significant', 'essential', 'critical', 'key', 'vital',
        'effective', 'efficient', 'better', 'worse', 'superior', 'inferior',
        'improve', 'enhance', 'increase', 'reduce', 'decrease', 'show', 'demonstrate',
        'indicate', 'reveal', 'suggest', 'prove', 'confirm', 'support', 'justify'
    ])
    if has_strong_verb or has_medium_verb or has_weak_verb_only or has_implicit_opinion_verb:
        assertion_condition = True
    elif has_research_keywords_in_assertion or has_assertion or has_comparison or has_evaluation or \
         has_domain_assertion or has_numeric_assertion or has_result_verb or has_opinion_keywords or \
         matches_template:
        assertion_condition = True
    elif len(sentence.split()) >= 6:
        assertion_condition = True
    else:
        assertion_condition = has_assertion or matches_template
    
    opinion_score = 0
    
    if has_strong_verb:
        opinion_score += 40
    elif has_medium_verb:
        opinion_score += 35
    elif has_weak_verb_only:
        opinion_score += 15
    
    if has_implicit_opinion_verb:
        opinion_score += 20
    
    if has_research_keywords_for_verb:
        opinion_score += 20
    if has_opinion_keywords:
        opinion_score += 15
    
    if has_assertion:
        opinion_score += 15
    if has_comparison:
        opinion_score += 10
    if has_evaluation:
        opinion_score += 10
    if has_domain_assertion:
        opinion_score += 10
    if has_numeric_assertion:
        opinion_score += 10
    if has_result_verb:
        opinion_score += 15
    if has_statistical_assertion:
        opinion_score += 20
    if has_necessity_assertion:
        opinion_score += 10
    if has_risk_assertion:
        opinion_score += 10
    if has_comparison_assertion:
        opinion_score += 10
    
    if matches_template:
        opinion_score += 20
    
    if len(sentence.split()) >= 6:
        opinion_score += 5
    
    non_opinion_scores = []
    
    score_data = 0
    if is_pure_data_desc:
        score_data = 35 if has_opinion_keywords else 45
    non_opinion_scores.append(score_data)
    
    score_method = 0
    if is_method_description:
        score_method = 30 if has_research_keywords_for_verb else 40
    non_opinion_scores.append(score_method)
    
    score_design = 0
    if is_experimental_design:
        score_design = 20 if has_research_keywords_for_verb else 30
    non_opinion_scores.append(score_design)
    
    score_procedure = 0
    if is_procedure_description:
        score_procedure = 25 if has_research_keywords_for_verb else 35
    non_opinion_scores.append(score_procedure)
    
    score_desc = 0
    if is_pure_description:
        score_desc = 30 if has_research_keywords_for_verb else 40
    non_opinion_scores.append(score_desc)
    
    non_opinion_score = max(non_opinion_scores) if non_opinion_scores else 0
    
    def has_data_intensive_features(text_lower):
        """检测句子是否包含强数据特征"""
        patterns = [
            r'\d+%?\s*\(\d+/\d+\)',  # "27% (3/11)"
            r'\bp\s*[<>=]\s*0\.\d+',  # "p < 0.05"
            r'\bn\s*=\s*\d+',  # "n = 100"
            r'\b\d+\.\d+\s*±\s*\d+\.\d+',  # "7.74 ± 0.26"
            r'\b(mean|median|average|rate|ratio|percentage|proportion)\s*[:=]\s*\d+',
        ]
        return any(re.search(p, text_lower) for p in patterns)
    
    # 反指示器2：被动方法描述
    def is_passive_methodology(text_lower):
        """检测是否为被动语态的方法描述"""
        passive_patterns = [
            r'\b(was|were|is|are)\s+(measured|detected|collected|analyzed|assessed|evaluated|determined|calculated|obtained|performed)\s+(using|by|with|via|through)',
            r'\b(samples?|data|specimens?|materials?)\s+(was|were)\s+(measured|collected|obtained|processed)',
        ]
        return any(re.search(p, text_lower) for p in passive_patterns)
    
    # 反指示器3：描述性动词（简化版，阶段1已拦截大部分）
    def has_descriptive_verb(text_lower):
        """检测描述性动词（被动语态描述，阶段1漏网之鱼）"""
        descriptive_patterns = [
            r'\b(are|is|was|were)\s+(presented|described|reported)\s+(?:in|by|through|here)\b',
        ]
        return any(re.search(p, text_lower) for p in descriptive_patterns)
    
    def has_method_description_with_medium_verb(text_lower):
        """检测流程描述"""
        method_patterns = [
            r'\bwas\s+carried\s+out\s+(?:using|by|with|at)\b',
            r'\b(?:study\s+)?population\s+consisted\s+of\b',
        ]
        return any(re.search(p, text_lower) for p in method_patterns)
    
    def count_strong_opinion_signals(text_lower, has_strong_v, has_comparative, has_evaluative):
        """统计强观点信号数量"""
        signals = 0
        if has_strong_v: signals += 1
        if has_comparative: signals += 1
        if has_evaluative: signals += 1
        if re.search(r'\b(should|must|may|might|could|would)\s+\w+', text_lower):
            signals += 1
        if re.search(r'\b(therefore|thus|consequently|hence|accordingly|as a result)\b', text_lower):
            signals += 1
        return signals
    
    data_intensive = has_data_intensive_features(sent_lower)
    passive_method = is_passive_methodology(sent_lower)
    descriptive_verb = has_descriptive_verb(sent_lower)
    method_with_medium_verb = has_method_description_with_medium_verb(sent_lower)
    strong_signals = count_strong_opinion_signals(
        sent_lower, 
        has_strong_verb, 
        has_comparison_assertion, 
        has_evaluation
    )
    
    if data_intensive and passive_method:
        non_opinion_score = max(non_opinion_score, 40)
        if strong_signals < 2:
            non_opinion_score += 15

    elif data_intensive:
        if strong_signals < 2:
            non_opinion_score += 10
    
    if descriptive_verb:
        non_opinion_score = max(non_opinion_score, 30)
        if strong_signals < 2:
            non_opinion_score += 10
    
    if method_with_medium_verb:
        non_opinion_score = max(non_opinion_score, 35)
        if strong_signals < 2:
            non_opinion_score += 12
    
    basic_conditions_met = verb_condition and structure_condition and assertion_condition
    
    if basic_conditions_met:
        threshold = 40
        
        if non_opinion_score >= 20:
            required_opinion_score = non_opinion_score * 1.85
            is_opinion = (opinion_score > required_opinion_score) and (opinion_score >= 50)
        else:
            is_opinion = (opinion_score > non_opinion_score) and (opinion_score >= threshold)
    else:
        is_opinion = False
    
    global _stage2_verification_stats
    _stage2_verification_stats['total_verified'] += 1
    if not is_opinion:
        failure_reasons = []
        if not verb_condition:
            failure_reasons.append("动词条件")
            _stage2_verification_stats['failed_verb'] += 1
        if not structure_condition:
            failure_reasons.append("主谓结构")
            _stage2_verification_stats['failed_structure'] += 1
        if not assertion_condition:
            failure_reasons.append("断言性")
            _stage2_verification_stats['failed_assertion'] += 1
        if basic_conditions_met:
            if opinion_score <= non_opinion_score:
                failure_reasons.append(f"评分不足(观点:{opinion_score} <= 非观点:{non_opinion_score})")
            elif opinion_score < 50:
                failure_reasons.append(f"观点得分不足(观点:{opinion_score} < 50)")
        
        if len(_stage2_verification_stats['samples']) < 200:
            structure_details = {}
            has_verb_or_adj = any(token.pos_ in ["VERB", "AUX", "ADJ"] for token in sent_doc)
            has_noun = any(token.pos_ in ["NOUN", "PROPN"] for token in sent_doc)
            structure_details['has_verb_or_adj'] = has_verb_or_adj
            structure_details['has_noun'] = has_noun
            structure_details['sentence_length'] = len(sentence.split())
            
            _stage2_verification_stats['samples'].append({
                'sentence': sentence[:150],
                'has_strong_verb': has_strong_verb,
                'has_medium_verb': has_medium_verb,
                'has_weak_verb_only': has_weak_verb_only,
                'has_subject_predicate': has_subject_predicate,
                'has_assertion': has_assertion,
                'matches_template': matches_template,
                'failure_reasons': failure_reasons,
                'structure_details': structure_details,
                'verb_condition': verb_condition,
                'structure_condition': structure_condition,
                'assertion_condition': assertion_condition,
                'opinion_score': opinion_score,
                'non_opinion_score': non_opinion_score,
                'basic_conditions_met': basic_conditions_met
            })
    else:
        _stage2_verification_stats['passed'] += 1
        if len(_stage2_verification_stats['passed_samples']) < 200:
            _stage2_verification_stats['passed_samples'].append({
                'sentence': sentence[:150],
                'has_strong_verb': has_strong_verb,
                'has_medium_verb': has_medium_verb,
                'has_weak_verb_only': has_weak_verb_only,
                'has_assertion': has_assertion,
                'matches_template': matches_template,
                'is_pure_data_desc': is_pure_data_desc,
                'verb_condition': verb_condition,
                'structure_condition': structure_condition,
                'assertion_condition': assertion_condition,
                'opinion_score': opinion_score,
                'non_opinion_score': non_opinion_score,
                'basic_conditions_met': basic_conditions_met
            })
    
    return is_opinion

def calculate_rule_confidence(sentence: str, sent_doc, is_title: bool = False) -> float:
    """计算规则置信度分数（0-1）
    
    将规则特征转换为置信度分数，替代二元判断
    
    Args:
        sentence: 句子文本
        sent_doc: spaCy文档对象
        is_title: 是否为标题
    
    Returns:
        置信度分数（0-1）
    """
    sent_lower = sentence.lower()
    confidence = 0.0
    
    # 1. 观点性动词得分（最高0.4）
    has_strong_verb = False
    has_medium_verb = False
    has_weak_verb = False
    
    # 检查短语动词
    phrase_verbs_medium = ['leads to', 'lead to', 'led to', 'results in', 'result in', 'resulted in',
                          'causes', 'cause', 'caused', 'enables', 'enable', 'enabled',
                          'allows', 'allow', 'allowed', 'prevents', 'prevent', 'prevented',
                          'reduces', 'reduce', 'reduced', 'increases', 'increase', 'increased',
                          'improves', 'improve', 'improved', 'enhances', 'enhance', 'enhanced']
    for phrase_verb in phrase_verbs_medium:
        if phrase_verb in sent_lower:
            has_medium_verb = True
            break
    
    # 检查词形动词
    if not has_medium_verb:
        for token in sent_doc:
            verb_lemma = token.lemma_.lower()
            if verb_lemma in OPINION_VERBS_STRONG:
                has_strong_verb = True
                break
            elif verb_lemma in OPINION_VERBS_MEDIUM:
                has_medium_verb = True
                break
    
    if not (has_strong_verb or has_medium_verb):
        for token in sent_doc:
            if token.lemma_.lower() in OPINION_VERBS_WEAK:
                has_weak_verb = True
                break
    
    if has_strong_verb:
        confidence += 0.4
    elif has_medium_verb:
        confidence += 0.25
    elif has_weak_verb:
        confidence += 0.1
    
    # 2. 句子长度得分（最高0.1）
    word_count = len(sentence.split())
    if 15 <= word_count <= 80:
        confidence += 0.1
    elif 10 <= word_count < 15 or 80 < word_count <= 120:
        confidence += 0.05
    
    # 3. 断言性内容得分（最高0.2）
    has_comparison = any(get_compiled_pattern(pattern).search(sentence) 
                        for pattern in COMPARISON_PATTERNS)
    has_evaluation = any(get_compiled_pattern(pattern).search(sentence) 
                        for pattern in EVALUATION_PATTERNS)
    has_negation = any(get_compiled_pattern(pattern).search(sentence) 
                      for pattern in NEGATION_PATTERNS)
    
    if has_comparison:
        confidence += 0.1
    if has_evaluation:
        confidence += 0.1
    if has_negation:
        confidence += 0.05
    
    # 4. 观点模板匹配得分（最高0.2）
    matches_template = any(get_compiled_pattern(template['pattern']).search(sentence) 
                          for template in OPINION_TEMPLATES)
    if matches_template:
        confidence += 0.2
    
    # 5. 不确定性词语惩罚（×0.7）
    uncertainty_words = ['may', 'might', 'could', 'possibly', 'perhaps', 'maybe', 'potentially']
    if any(word in sent_lower for word in uncertainty_words):
        confidence *= 0.7
    
    # 6. 标题增益（×1.2）
    if is_title:
        confidence *= 1.2
    
    # 7. 非观点特征惩罚
    # 纯数据描述
    has_percentage = bool(re.search(r'\d+%|\d+\.\d+%', sentence))
    has_number = bool(re.search(r'\d+', sentence))
    method_keywords = ['we used', 'we employed', 'we applied', 'were used', 'were employed', 'were applied',
                      'was performed', 'was conducted', 'procedure', 'protocol', 'method was']
    is_method_desc = any(kw in sent_lower for kw in method_keywords)
    
    if (has_percentage or has_number) and not (has_strong_verb or has_medium_verb) and is_method_desc:
        confidence *= 0.5  # 严重惩罚
    
    # 归一化到[0, 1]
    confidence = min(1.0, max(0.0, confidence))
    
    return confidence

def calculate_syntax_confidence(sentence: str, sent_doc) -> float:
    """计算句法置信度分数（0-1）
    
    基于依存句法分析提取的结构特征
    
    Args:
        sentence: 句子文本
        sent_doc: spaCy文档对象
    
    Returns:
        句法置信度分数（0-1）
    """
    if sent_doc is None:
        return 0.0
    
    confidence = 0.0
    
    # 检查主谓结构
    has_subject = False
    has_verb = False
    for token in sent_doc:
        if token.dep_ in ['nsubj', 'nsubjpass']:
            has_subject = True
        if token.pos_ == 'VERB':
            has_verb = True
    
    if has_subject and has_verb:
        confidence += 0.1
    
    # 检查典型观点结构：主体-断言-目标
    has_object = False
    has_predicate = False
    for token in sent_doc:
        if token.dep_ in ['dobj', 'pobj', 'attr']:
            has_object = True
        if token.pos_ == 'VERB' and token.dep_ in ['ROOT', 'ccomp', 'xcomp']:
            has_predicate = True
    
    if has_object and has_predicate:
        confidence += 0.1
    
    # 检查是否有修饰关系（形容词修饰名词）
    has_amod = False
    for token in sent_doc:
        if token.dep_ == 'amod':
            has_amod = True
            break
    
    if has_amod:
        confidence += 0.05
    
    # 归一化到[0, 0.3]（句法置信度上限）
    confidence = min(0.3, max(0.0, confidence))
    
    return confidence

def fuse_confidence_scores(rule_conf: float, semantic_conf: float = None, syntax_conf: float = None) -> float:
    """融合多源置信度分数
    
    Args:
        rule_conf: 规则置信度（0-1）
        semantic_conf: 语义模型置信度（0-1，可选）
        syntax_conf: 句法置信度（0-1，可选）
    
    Returns:
        融合后的置信度分数（0-1）
    """
    # 默认值处理
    if semantic_conf is None:
        semantic_conf = 0.0  # 语义模型未实现时，权重分配给规则
    if syntax_conf is None:
        syntax_conf = 0.0
    
    # 权重融合
    weights = CONFIDENCE_WEIGHTS
    # 如果语义模型未提供，将权重重新分配
    if semantic_conf == 0.0:
        effective_rule_weight = weights['rule'] + weights['semantic']
        effective_syntax_weight = weights['syntax']
        total_weight = effective_rule_weight + effective_syntax_weight
        if total_weight > 0:
            effective_rule_weight /= total_weight
            effective_syntax_weight /= total_weight
        else:
            effective_rule_weight = 1.0
            effective_syntax_weight = 0.0
        fused = effective_rule_weight * rule_conf + effective_syntax_weight * syntax_conf
    else:
        total_weight = weights['rule'] + weights['semantic'] + weights['syntax']
        if total_weight > 0:
            fused = (weights['rule'] * rule_conf + 
                    weights['semantic'] * semantic_conf + 
                    weights['syntax'] * syntax_conf) / total_weight
        else:
            fused = rule_conf
    
    # 归一化到[0, 1]
    return min(1.0, max(0.0, fused))

def verify_title_opinion_by_rules(sentence: str, sent_doc) -> bool:
    """
    标题专用的观点验证函数（更宽松的规则）
    
    与摘要验证的主要区别：
    1. 降低non_opinion_score的惩罚（标题不应触发流程描述等）
    2. 降低动态阈值倍率（从1.7到1.3）
    3. 更宽容地处理短句和不完整句子
    """
    sent_lower = sentence.lower()
    
    # 复用verify_opinion_by_rules的大部分逻辑，但调整参数
    # 检测观点性动词
    has_strong_verb = False
    has_medium_verb = False
    has_weak_verb = False
    has_opinion_verb = False
    matched_verb = None
    
    # 强观点动词
    for token in sent_doc:
        lemma_lower = token.lemma_.lower()
        if lemma_lower in OPINION_VERBS_STRONG:
            has_strong_verb = True
            has_opinion_verb = True
            matched_verb = lemma_lower
            break
    
    # 中等观点动词
    if not has_strong_verb:
        for token in sent_doc:
            lemma_lower = token.lemma_.lower()
            if lemma_lower in OPINION_VERBS_MEDIUM:
                has_medium_verb = True
                has_opinion_verb = True
                matched_verb = lemma_lower
                break
    
    # 主谓结构
    has_subject = False
    has_verb = False
    for token in sent_doc:
        if token.dep_ in ['nsubj', 'nsubjpass']:
            has_subject = True
        if token.pos_ == 'VERB':
            has_verb = True
    has_structure = has_subject and has_verb
    
    # 断言性内容
    has_comparison = any(re.search(pattern, sentence, re.IGNORECASE) for pattern in COMPARISON_PATTERNS)
    has_evaluation = any(re.search(pattern, sentence, re.IGNORECASE) for pattern in EVALUATION_PATTERNS)
    has_negation = any(re.search(pattern, sentence, re.IGNORECASE) for pattern in NEGATION_PATTERNS)
    
    # 观点模板匹配
    matches_template = any(get_compiled_pattern(template['pattern']).search(sentence) 
                          for template in OPINION_TEMPLATES)
    
    # 📊 评分系统
    opinion_score = 0
    
    # 观点性动词得分
    if has_strong_verb:
        opinion_score += 50
    elif has_medium_verb:
        opinion_score += 35
    elif has_weak_verb:
        opinion_score += 20
    
    # 结构性得分
    if has_structure:
        opinion_score += 15
    
    # 断言性得分
    if has_comparison:
        opinion_score += 25
    if has_evaluation:
        opinion_score += 25
    if has_negation:
        opinion_score += 20
    if matches_template:
        opinion_score += 20
    
    # 非观点特征评分（标题中权重降低）
    non_opinion_score = 0
    
    # 纯数据描述（标题中很少出现，降低权重）
    if re.search(r'\d+%\s*\(\d+/\d+\)', sentence):
        non_opinion_score = max(non_opinion_score, 20)  # 降低到20（原35）
    elif re.search(r'\bn\s*=\s*\d+', sent_lower):
        non_opinion_score = max(non_opinion_score, 15)  # 降低到15（原25）
    
    # 方法描述（标题中极少出现）
    if re.search(r'\b(we|they)\s+(used|employed|applied|utilized|adopted|implemented|conducted|performed)\b', sent_lower):
        non_opinion_score = max(non_opinion_score, 15)  # 降低到15（原30）
    
    # 🔑 关键区别：动态阈值倍率降低为1.3（标题更宽容）
    threshold = 40
    if non_opinion_score >= 20:
        required_opinion_score = non_opinion_score * 1.3  # 标题专用：1.3倍率
        is_opinion = (opinion_score > required_opinion_score) and (opinion_score >= 50)
    else:
        is_opinion = (opinion_score > non_opinion_score) and (opinion_score >= threshold)
    
    return is_opinion

def detect_opinion_stance(sentence: str, structured_opinion: StructuredOpinion, doc) -> StructuredOpinion:
    """检测观点方向：极性、强度、方向（完全基于依存关系分析）"""
    # 检测否定词及其作用范围（基于依存关系路径，性能优化版）
    negation_cache = {}  # 局部缓存否定检测结果（每个句子独立）
    
    def is_negated(token, doc):
        """检查token是否被否定词修饰（基于依存树路径，带缓存和深度限制）"""
        # 使用局部缓存避免重复计算（每个句子独立）
        cache_key = (token.i, id(doc))
        if cache_key in negation_cache:
            return negation_cache[cache_key]
        
        # 方法1：直接查找否定修饰词（neg依赖）- 最快路径
        for child in token.children:
            if child.dep_ == 'neg' or child.lemma_.lower() in ['not', 'no', 'never', 'none']:
                negation_cache[cache_key] = True
                return True
        
        # 方法2：查找父节点的否定修饰
        if token.head.dep_ == 'neg' or token.head.lemma_.lower() in ['not', 'no', 'never']:
            negation_cache[cache_key] = True
            return True
        
        # 方法3：基于依存树路径查找否定词（增强版：处理复杂否定和从句嵌套）
        MAX_DEPTH = 5  # 增加深度以处理复杂嵌套
        NEGATION_LEMMAS = {'not', 'no', 'never', 'none', 'nothing', 'nobody', 'nowhere', 'neither', 'nor'}
        NEGATION_PREFIXES = {'un', 'non', 'in', 'im', 'il', 'ir', 'dis', 'de', 'mis'}
        
        def find_negation_in_path(current_token, visited=None, depth=0, clause_boundary=None):
            """在依存树路径中查找否定词（增强版：处理从句边界和复杂否定）"""
            if depth > MAX_DEPTH:
                return False
            if visited is None:
                visited = set()
            if current_token.i in visited:
                return False
            visited.add(current_token.i)
            
            # 检查当前token是否是否定词
            token_lemma = current_token.lemma_.lower()
            if token_lemma in NEGATION_LEMMAS:
                return True
            
            # 检查词形否定前缀（如un-, non-, in-等）
            token_text = current_token.text.lower()
            if any(token_text.startswith(prefix) for prefix in NEGATION_PREFIXES):
                return True
            
            # 检查从句边界（避免跨从句的否定作用）
            # 如果遇到从句标记词（如that, which, who等），限制否定作用范围
            if clause_boundary is None:
                clause_markers = {'that', 'which', 'who', 'whom', 'where', 'when', 'while', 'if', 'unless'}
                if token_lemma in clause_markers:
                    clause_boundary = current_token.i
            
            # 检查直接子节点中的否定词（优先检查）
            for child in current_token.children:
                if child.dep_ == 'neg' or child.lemma_.lower() in NEGATION_LEMMAS:
                    return True
                # 检查子节点的否定前缀
                if any(child.text.lower().startswith(prefix) for prefix in NEGATION_PREFIXES):
                    return True
            
            # 递归检查子节点（限制深度，考虑从句边界）
            if depth < MAX_DEPTH:
                for child in current_token.children:
                    # 如果子节点在从句边界之后，限制搜索范围
                    if clause_boundary is not None and child.i > clause_boundary and depth > 2:
                        continue
                    if find_negation_in_path(child, visited, depth + 1, clause_boundary):
                        return True
            
            # 检查父节点路径（向上查找，限制深度）
            if current_token.head != current_token and depth < MAX_DEPTH:
                # 如果父节点在从句边界之后且深度较大，限制搜索
                if clause_boundary is not None and current_token.head.i > clause_boundary and depth > 2:
                    return False
                if find_negation_in_path(current_token.head, visited, depth + 1, clause_boundary):
                    return True
            
            return False
        
        # 在token及其head的路径中查找否定词（增强版：考虑否定作用域）
        result = False
        
        # 检查双重否定（两个否定词抵消）
        negation_tokens_set = set()  # 使用set避免重复计数同一token
        
        def count_negations_in_scope(start_token, visited_neg=None, depth=0):
            """统计作用域内的否定词数量（修复：避免重复计数）"""
            if visited_neg is None:
                visited_neg = set()
            if depth > 3 or start_token.i in visited_neg:
                return 0
            visited_neg.add(start_token.i)
            
            count = 0
            token_lemma = start_token.lemma_.lower()
            # 检查是否是否定词（只计数一次，即使同时满足多个条件）
            is_negation_token = False
            if token_lemma in NEGATION_LEMMAS or start_token.dep_ == 'neg':
                is_negation_token = True
            # 检查否定前缀（避免与上面的重复计数）
            elif any(start_token.text.lower().startswith(prefix) for prefix in NEGATION_PREFIXES):
                is_negation_token = True
            
            if is_negation_token and start_token.i not in negation_tokens_set:
                count += 1
                negation_tokens_set.add(start_token.i)
            
            # 递归检查子节点和父节点
            for child in start_token.children:
                if depth < 3:
                    count += count_negations_in_scope(child, visited_neg, depth + 1)
            if start_token.head != start_token and depth < 3:
                count += count_negations_in_scope(start_token.head, visited_neg, depth + 1)
            
            return count
        
        # 统计作用域内的否定词
        negation_count = count_negations_in_scope(token)
        
        # 双重否定视为肯定（偶数个否定词且>0）
        if negation_count > 0 and negation_count % 2 == 0:
            negation_cache[cache_key] = False
            return False
        
        # 单数否定词或奇数个否定词视为否定
        if negation_count > 0 and negation_count % 2 == 1:
            # 已经检测到奇数个否定词，直接返回True
            negation_cache[cache_key] = True
            return True
        
        # 如果没有检测到否定词（negation_count == 0），使用路径查找方法
        if find_negation_in_path(token):
            result = True
        elif token.head != token and find_negation_in_path(token.head):
            result = True
        
        # 缓存结果（局部缓存）
        negation_cache[cache_key] = result
        return result
    
    # 检测极性（基于依存关系）
    positive_indicators = ['outperforms', 'better', 'superior', 'improves', 'effective', 
                          'significant', 'exceeds', 'surpasses', 'enhances', 'increases',
                          'achieves', 'obtains', 'accomplishes', 'succeeds']
    negative_indicators = ['worse', 'inferior', 'fails', 'cannot', 'unable', 
                          'reduces', 'decreases', 'declines', 'deteriorates']
    
    has_positive = False
    has_negative = False
    positive_negated = False
    negative_negated = False
    
    # 使用依存关系检测否定
    for token in doc:
        token_lower = token.lemma_.lower()
        is_neg = is_negated(token, doc)
        
        if token_lower in positive_indicators:
            has_positive = True
            if is_neg:
                positive_negated = True
        elif token_lower in negative_indicators:
            has_negative = True
            if is_neg:
                negative_negated = True
    
    # 判断最终极性（考虑否定）
    if positive_negated and not (has_negative and not negative_negated):
        structured_opinion.polarity = "negative"
    elif negative_negated and not (has_positive and not positive_negated):
        structured_opinion.polarity = "positive"
    elif has_negative and not has_positive:
        structured_opinion.polarity = "negative"
    elif has_positive and not has_negative:
        structured_opinion.polarity = "positive"
    else:
        structured_opinion.polarity = "neutral"
    
    # 检测强度（基于依存关系查找修饰词，包含advmod和amod）
    strength_patterns = {
        'high': ['significantly', 'substantially', 'dramatically', 'greatly', 'considerably', 'remarkably',
                'highly', 'extremely', 'very', 'much', 'strongly', 'deeply'],
        'medium': ['moderately', 'somewhat', 'fairly', 'reasonably', 'quite', 'rather', 'relatively'],
        'low': ['slightly', 'marginally', 'minimally', 'somewhat', 'a bit', 'a little']
    }
    
    # 强度形容词模式
    strength_adjectives = {
        'high': ['significant', 'substantial', 'dramatic', 'great', 'considerable', 'remarkable',
                'high', 'strong', 'major', 'important', 'crucial', 'critical'],
        'medium': ['moderate', 'fair', 'reasonable', 'some', 'certain'],
        'low': ['slight', 'marginal', 'minimal', 'small', 'minor']
    }
    
    # 查找强度修饰词（advmod - 副词修饰）
    for token in doc:
        token_lower = token.lemma_.lower()
        # 检查是否是强度副词
        if token.pos_ == 'ADV' and token_lower in [w for words in strength_patterns.values() for w in words]:
            for level, words in strength_patterns.items():
                if token_lower in words:
                    structured_opinion.strength = level
                    break
            if structured_opinion.strength:
                break
        # 检查是否通过advmod修饰观点性动词
        if token.dep_ == 'advmod' and token.head.lemma_.lower() in positive_indicators + negative_indicators:
            token_lower = token.lemma_.lower()
            for level, words in strength_patterns.items():
                if token_lower in words:
                    structured_opinion.strength = level
                    break
            if structured_opinion.strength:
                break
    
    # 如果还没找到强度，查找强度形容词（amod - 形容词修饰）
    if not structured_opinion.strength:
        for token in doc:
            token_lower = token.lemma_.lower()
            # 检查是否是强度形容词
            if token.pos_ == 'ADJ' and token_lower in [w for words in strength_adjectives.values() for w in words]:
                for level, words in strength_adjectives.items():
                    if token_lower in words:
                        structured_opinion.strength = level
                        break
                if structured_opinion.strength:
                    break
            # 检查是否通过amod修饰观点相关名词
            if token.dep_ == 'amod':
                # 检查修饰的名词是否是观点相关的
                head_text = token.head.text.lower()
                if any(kw in head_text for kw in ['result', 'finding', 'effect', 'improvement', 'performance', 'accuracy']):
                    token_lower = token.lemma_.lower()
                    for level, words in strength_adjectives.items():
                        if token_lower in words:
                            structured_opinion.strength = level
                            break
                    if structured_opinion.strength:
                        break
    
    # 判断观点方向
    if structured_opinion.polarity == "positive" and structured_opinion.strength in ['high', 'medium']:
        structured_opinion.stance = "support"
    elif structured_opinion.polarity == "negative" and structured_opinion.strength in ['high', 'medium']:
        structured_opinion.stance = "oppose"
    else:
        structured_opinion.stance = "neutral"
    
    return structured_opinion

def extract_structured_opinion_from_sentence(sentence: str, doc) -> Optional[StructuredOpinion]:
    """从句子中提取结构化观点（优化版：模板索引 + 早期终止 + 动态优先级）"""
    global _stage3_extraction_stats, _template_match_stats
    _stage3_extraction_stats['total_sentences'] += 1
    sentence_lower = sentence.lower()
    
    # 优化：构建模板关键词索引，快速过滤不匹配的模板
    def build_template_keywords():
        """构建模板关键词索引（首次调用时构建，后续复用）"""
        if not hasattr(extract_structured_opinion_from_sentence, '_template_keywords'):
            keywords_map = {}
            for idx, template in enumerate(OPINION_TEMPLATES):
                pattern = template['pattern'].lower()
                # 提取关键动词和名词作为索引关键词
                key_verbs = ['outperform', 'exceed', 'surpass', 'better', 'worse', 'improve', 
                            'enhance', 'show', 'demonstrate', 'prove', 'find', 'suggest']
                key_nouns = ['method', 'approach', 'result', 'finding', 'conclusion', 'evidence']
                
                template_keywords = set()
                for verb in key_verbs:
                    if verb in pattern:
                        template_keywords.add(verb)
                for noun in key_nouns:
                    if noun in pattern:
                        template_keywords.add(noun)
                
                # 如果模板包含特定短语，也加入索引
                if 'does not' in pattern or 'fails' in pattern:
                    template_keywords.add('negation')
                if 'first' in pattern and 'work' in pattern:
                    template_keywords.add('first_work')
                
                keywords_map[idx] = template_keywords
            extract_structured_opinion_from_sentence._template_keywords = keywords_map
        return extract_structured_opinion_from_sentence._template_keywords
    
    # 快速过滤：检查句子是否包含模板的关键词
    template_keywords = build_template_keywords()
    sentence_keywords = set()
    for verb in ['outperform', 'exceed', 'surpass', 'better', 'worse', 'improve', 
                 'enhance', 'show', 'demonstrate', 'prove', 'find', 'suggest']:
        if verb in sentence_lower:
            sentence_keywords.add(verb)
    for noun in ['method', 'approach', 'result', 'finding', 'conclusion', 'evidence']:
        if noun in sentence_lower:
            sentence_keywords.add(noun)
    if 'does not' in sentence_lower or 'fails' in sentence_lower:
        sentence_keywords.add('negation')
    if 'first' in sentence_lower and 'work' in sentence_lower:
        sentence_keywords.add('first_work')
    
    # 动态计算模板优先级：结合静态priority、匹配成功率和关键词匹配度
    def get_dynamic_priority(template, idx):
        static_priority = template.get('priority', 999)
        
        # 基础动态调整（基于历史成功率）
        dynamic_adjustment = 0
        if idx in _template_match_stats:
            stats = _template_match_stats[idx]
            total = stats['matches']
            if total > 0:
                success_rate = stats['successes'] / total
                # 成功率高则降低优先级值（提高优先级）
                dynamic_adjustment = int((0.5 - success_rate) * 4)  # 范围-2到+2
        
        # 关键词匹配度调整：如果句子包含模板关键词，提高优先级
        keyword_bonus = 0
        if idx in template_keywords:
            template_kw = template_keywords[idx]
            if template_kw and sentence_keywords:
                overlap = len(template_kw & sentence_keywords)
                if overlap > 0:
                    keyword_bonus = -min(2, overlap)  # 最多降低2（提高优先级）
        
        final_priority = static_priority + dynamic_adjustment + keyword_bonus
        return max(1, min(999, final_priority))
    
    # 按动态优先级排序模板，并过滤掉明显不匹配的模板
    template_with_indices = []
    for i, t in enumerate(OPINION_TEMPLATES):
        # 快速过滤：如果模板有关键词但句子没有，跳过
        if i in template_keywords:
            template_kw = template_keywords[i]
            if template_kw and not (template_kw & sentence_keywords):
                # 如果模板要求特定关键词但句子没有，跳过（除非是通用模板）
                if len(template_kw) > 2:  # 非通用模板
                    continue
        template_with_indices.append((i, t))
    
    sorted_templates = sorted(template_with_indices, 
                             key=lambda x: (get_dynamic_priority(x[1], x[0]), len(x[1]['pattern'])))
    
    template_matched = False
    matched_template_priority = None
    best_opinion = None
    best_priority = 999
    
    # 优化：早期终止机制 - 如果高优先级模板（priority <= 2）匹配成功，立即返回
    for template_idx, template in sorted_templates:
        pattern = template['pattern']
        slots = template['slots']
        template_priority = template.get('priority', 999)
        
        match = get_compiled_pattern(pattern).search(sentence)
        if match:
            template_matched = True
            matched_template_priority = template_priority
            
            # 记录模板匹配统计
            if template_idx not in _template_match_stats:
                _template_match_stats[template_idx] = {'matches': 0, 'successes': 0, 'failures': 0}
            _template_match_stats[template_idx]['matches'] += 1
            opinion = StructuredOpinion()
            groups = match.groups()
            
            for i, slot in enumerate(slots):
                if i < len(groups) and groups[i]:
                    value = groups[i].strip()
                    if slot == 'object':
                        opinion.object = value
                    elif slot == 'predicate':
                        if template_priority == 3 and 'does not' in pattern.lower() and value in ['outperform', 'exceed', 'surpass', 'beat', 'improve']:
                            opinion.predicate = f"does not {value}"
                        elif template_priority == 3 and 'fails' in pattern.lower():
                            opinion.predicate = f"fails to {value}"
                        else:
                            opinion.predicate = value
                    elif slot == 'target':
                        opinion.target = value
                    elif slot == 'context':
                        opinion.context = value
                    elif slot == 'strength':
                        opinion.strength = value
                    elif slot == 'subject':
                        opinion.subject = value
                    elif slot == 'judgment':
                        if opinion.predicate:
                            opinion.predicate += " " + value
                        else:
                            opinion.predicate = value
                    elif slot == 'condition':
                        if opinion.context:
                            opinion.context = f"{value}, {opinion.context}"
                        else:
                            opinion.context = value
            
            if template_priority == 2 and 'first' in pattern.lower() and 'work' in pattern.lower():
                if opinion.predicate and not opinion.object:
                    opinion.object = opinion.predicate
                    opinion.predicate = "first work to"
            
            if opinion.object and not opinion.predicate:
                innovation_verbs = ['propose', 'introduce', 'develop', 'present', 'create', 'design', 'innovate', 'pioneer']
                for verb in innovation_verbs:
                    if verb in sentence_lower:
                        opinion.predicate = verb
                        break
            
            # 字段完整度检查
            if opinion.object and opinion.predicate:
                # 高优先级模板（priority <= 2）且字段完整，立即返回
                if template_priority <= 2:
                    _stage3_extraction_stats['template_matched'] += 1
                    _template_match_stats[template_idx]['successes'] += 1
                    opinion = detect_opinion_stance(sentence, opinion, doc)
                    return opinion
                else:
                    # 记录最佳匹配（优先级最低的完整匹配）
                    if template_priority < best_priority:
                        best_opinion = opinion
                        best_priority = template_priority
            else:
                # 模板匹配但字段缺失，继续尝试下一个模板
                _stage3_extraction_stats['field_missing'] += 1
                _template_match_stats[template_idx]['failures'] += 1
                if len(_stage3_extraction_stats['failed_samples']) < 10:
                    _stage3_extraction_stats['failed_samples'].append({
                        'sentence': sentence[:150],
                        'reason': 'template_matched_but_field_missing',
                        'has_object': bool(opinion.object),
                        'has_predicate': bool(opinion.predicate),
                        'template_priority': template_priority
                    })
    
    # 如果有最佳匹配，返回它
    if best_opinion:
        _stage3_extraction_stats['template_matched'] += 1
        best_opinion = detect_opinion_stance(sentence, best_opinion, doc)
        return best_opinion
    
    # 模板匹配失败，尝试依存句法分析
    dependency_result = extract_opinion_from_dependency(doc, sentence)
    if dependency_result:
        _stage3_extraction_stats['dependency_matched'] += 1
        return dependency_result
    
    # 完全失败
    _stage3_extraction_stats['extraction_failed'] += 1
    if len(_stage3_extraction_stats['failed_samples']) < 15:
        _stage3_extraction_stats['failed_samples'].append({
            'sentence': sentence[:150],
            'reason': 'both_template_and_dependency_failed',
            'template_matched': template_matched,
            'matched_template_priority': matched_template_priority
        })
    
    return None

def calibrate_confidence(raw_confidence: float) -> float:
    """校准置信度值（基于验证集数据）"""
    global _confidence_calibration
    calibration_data = _confidence_calibration['calibration_data']
    
    if not calibration_data:
        return raw_confidence
    
    # 简单线性校准：基于校准数据的分布调整
    # 找到最接近的校准点
    sorted_data = sorted(calibration_data, key=lambda x: abs(x[0] - raw_confidence))
    if sorted_data:
        closest_conf, closest_correct = sorted_data[0]
        # 如果校准数据表明该置信度对应的准确率较低，则降低置信度
        # 如果准确率较高，则提高置信度
        if closest_correct:
            # 正确样本：适度提高置信度
            adjustment = min(0.1, (1.0 - raw_confidence) * 0.2)
            return min(1.0, raw_confidence + adjustment)
        else:
            # 错误样本：适度降低置信度
            adjustment = min(0.1, raw_confidence * 0.2)
            return max(0.0, raw_confidence - adjustment)
    
    return raw_confidence

def extract_opinion_from_dependency(doc, sentence: str) -> Optional[StructuredOpinion]:
    """基于依存句法分析提取结构化观点（优化版：单次遍历，增强置信度，修复范围Bug）"""
    sent_lower = sentence.lower()
    
    # 修复Bug：定位目标句子Span，避免遍历整个文档
    search_doc = None
    sentence_stripped = sentence.strip()
    for sent in doc.sents:
        if sent.text.strip() == sentence_stripped:
            search_doc = sent
            break
    
    if search_doc is None:
        search_doc = doc
    
    # 预构建noun_chunks映射（避免重复查找）
    noun_chunk_map = {}
    for chunk in search_doc.noun_chunks:
        for token in chunk:
            if token.i not in noun_chunk_map:
                noun_chunk_map[token.i] = chunk.text
    
    # 辅助函数：基于依存关系提取完整的名词短语（优化版：使用预构建的映射）
    def extract_noun_phrase_by_dependency(head_token):
        """基于依存关系提取名词短语（包含所有修饰词，支持更多依存关系类型）"""
        # 优先使用预构建的noun_chunks映射
        if head_token.i in noun_chunk_map:
            return noun_chunk_map[head_token.i]
        
        # 基于依存关系的提取
        tokens = [head_token]
        visited = {head_token.i}
        
        # 支持的修饰关系类型
        modifier_deps = ['amod', 'det', 'compound', 'nummod', 'nmod', 'poss', 'quantmod', 'appos']
        
        # 收集所有依赖于此head的修饰词
        def collect_modifiers(token, is_before_head=True):
            """递归收集修饰词"""
            if token.i in visited:
                return
            visited.add(token.i)
            
            # 根据依存关系类型和位置插入
            if token.dep_ in modifier_deps:
                if is_before_head or token.i < head_token.i:
                    # 向前查找的修饰词插入前面
                    insert_pos = 0
                    for i, t in enumerate(tokens):
                        if t.i > token.i:
                            insert_pos = i
                            break
                        insert_pos = i + 1
                    tokens.insert(insert_pos, token)
                else:
                    # 向后查找的修饰词插入后面
                    insert_pos = len(tokens)
                    for i, t in enumerate(tokens):
                        if t.i > token.i:
                            insert_pos = i
                            break
                    tokens.insert(insert_pos, token)
            
            # 递归收集修饰词的修饰词
            for grandchild in token.children:
                if grandchild.dep_ in modifier_deps:
                    collect_modifiers(grandchild, is_before_head=(grandchild.i < head_token.i))
        
        # 收集所有修饰词
        for child in head_token.children:
            if child.i in visited:
                continue
            if child.dep_ in modifier_deps:
                collect_modifiers(child, is_before_head=(child.i < head_token.i))
        
        # 按原始顺序排序
        tokens.sort(key=lambda t: t.i)
        return " ".join([t.text for t in tokens])
    
    # 增强的置信度计算函数（添加语义一致性验证和校准支持）
    def calculate_confidence(opinion: StructuredOpinion, has_subject: bool, has_object: bool, 
                            has_target: bool, has_context: bool, verb_strength: str, 
                            token=None, doc=None) -> float:
        """计算提取结果的置信度（增强版：包含语义一致性验证和校准）"""
        global _confidence_calibration
        confidence = 0.0
        
        # 基础字段完整性（50%权重）
        if has_object:
            confidence += 0.25
        if has_subject:
            confidence += 0.08
        if has_target:
            confidence += 0.08
        if has_context:
            confidence += 0.09
        
        # 动词强度（20%权重）
        if verb_strength == 'strong':
            confidence += 0.2
        elif verb_strength == 'medium':
            confidence += 0.15
        else:
            confidence += 0.1
        
        # 字段质量评估（20%权重）
        if opinion.object:
            obj_words = opinion.object.split()
            if len(obj_words) >= 2:
                confidence += 0.1
            # 检查object是否包含有效名词（避免纯形容词或虚词）
            if any(len(w) > 3 for w in obj_words):
                confidence += 0.05
        if opinion.predicate:
            pred_words = opinion.predicate.split()
            if len(pred_words) >= 1:
                confidence += 0.05
        
        # 语义一致性验证（10%权重）：检查依存关系合理性
        if token and doc and opinion.object and opinion.predicate:
            # 验证object和predicate在依存树中的关系是否合理
            # 如果token是观点性动词，object应该是其论元
            if token.pos_ == 'VERB':
                # 检查object是否在token的论元范围内（通过children或noun_chunks）
                object_tokens = [t for t in doc if any(t.text in word for word in opinion.object.split()[:3])]
                if object_tokens:
                    # 检查object_tokens是否与token有合理的依存关系
                    for obj_tok in object_tokens[:1]:  # 只检查第一个匹配的token
                        # 检查是否是直接论元关系
                        if (obj_tok.head == token or 
                            any(child.head == token for child in obj_tok.children) or
                            token in [c.head for c in obj_tok.children]):
                            confidence += 0.1
                            break
        
        raw_confidence = min(confidence, 1.0)
        
        # 应用置信度校准（如果启用）
        if _confidence_calibration['enabled'] and _confidence_calibration['calibration_data']:
            calibrated_confidence = calibrate_confidence(raw_confidence)
            return calibrated_confidence
        
        return raw_confidence
    
    # 存储所有策略的结果和置信度
    candidate_opinions = []
    
    # 单次遍历：并行应用所有策略
    for token in search_doc:
        verb_lemma = token.lemma_.lower()
        token_pos = token.pos_
        token_dep = token.dep_
        
        # 策略1：基于依存关系查找观点性动词及其论元
        if verb_lemma in OPINION_VERBS_STRONG | OPINION_VERBS_MEDIUM:
            opinion = StructuredOpinion()
            subject = None
            object_token = None
            
            # 一次性收集所有children信息
            children_by_dep = {}
            for child in token.children:
                if child.dep_ not in children_by_dep:
                    children_by_dep[child.dep_] = []
                children_by_dep[child.dep_].append(child)
            
            # 查找主语
            if 'nsubj' in children_by_dep or 'nsubjpass' in children_by_dep:
                for dep in ['nsubj', 'nsubjpass']:
                    if dep in children_by_dep:
                        subject = extract_noun_phrase_by_dependency(children_by_dep[dep][0])
                        opinion.subject = subject
                        break
            
            # 查找直接宾语
            if 'dobj' in children_by_dep:
                object_token = children_by_dep['dobj'][0]
            # 如果没有直接宾语，查找介词宾语
            elif 'prep' in children_by_dep:
                for prep_child in children_by_dep['prep']:
                    for prep_grandchild in prep_child.children:
                        if prep_grandchild.dep_ == 'pobj':
                            object_token = prep_grandchild
                            break
                    if object_token:
                        break
            
            # 优先使用宾语作为object，否则使用主语
            if object_token:
                opinion.object = extract_noun_phrase_by_dependency(object_token)
            elif subject:
                opinion.object = subject
            
            # 查找目标（target）
            if 'prep' in children_by_dep:
                for prep_child in children_by_dep['prep']:
                    prep_text = prep_child.text.lower()
                    if prep_text in ['than', 'to', 'over', 'against', 'compared', 'versus', 'vs']:
                        for prep_grandchild in prep_child.children:
                            if prep_grandchild.dep_ == 'pobj':
                                opinion.target = extract_noun_phrase_by_dependency(prep_grandchild)
                                break
                        if opinion.target:
                            break
            
            # 查找背景条件（context）
            if 'prep' in children_by_dep:
                for prep_child in children_by_dep['prep']:
                    prep_text = prep_child.text.lower()
                    if prep_text in ['for', 'on', 'in', 'with', 'under', 'when']:
                        context_parts = []
                        for prep_grandchild in prep_child.children:
                            if prep_grandchild.dep_ == 'pobj':
                                context_parts.append(extract_noun_phrase_by_dependency(prep_grandchild))
                            elif prep_grandchild.dep_ in ['det', 'amod']:
                                context_parts.insert(0, prep_grandchild.text)
                        if context_parts:
                            opinion.context = " ".join(context_parts)
                            break
            
            opinion.predicate = verb_lemma
            if opinion.object and opinion.predicate:
                verb_strength = 'strong' if verb_lemma in OPINION_VERBS_STRONG else 'medium'
                confidence = calculate_confidence(
                    opinion, bool(opinion.subject), bool(opinion.object),
                    bool(opinion.target), bool(opinion.context), verb_strength, token, search_doc
                )
                candidate_opinions.append((opinion, confidence, 1))
            
            # 策略4：查找补语从句（xcomp）- 在同一token上检查
            if 'xcomp' in children_by_dep:
                for xcomp_child in children_by_dep['xcomp']:
                    opinion = StructuredOpinion()
                    xcomp_subject = subject  # 复用已查找的subject
                    if xcomp_subject:
                        opinion.subject = xcomp_subject
                    
                    # xcomp的宾语通常是object
                    xcomp_object = None
                    for xcomp_grandchild in xcomp_child.children:
                        if xcomp_grandchild.dep_ == 'dobj':
                            xcomp_object = extract_noun_phrase_by_dependency(xcomp_grandchild)
                            break
                    
                    if xcomp_object:
                        opinion.object = xcomp_object
                    elif xcomp_subject:
                        opinion.object = xcomp_subject
                    
                    # predicate是主动词+xcomp动词
                    xcomp_verb = xcomp_child.lemma_.lower() if xcomp_child.pos_ == 'VERB' else xcomp_child.text.lower()
                    opinion.predicate = f"{verb_lemma} {xcomp_verb}"
                    
                    # 查找context（复用已收集的prep信息）
                    if 'prep' in children_by_dep:
                        for prep_child in children_by_dep['prep']:
                            if prep_child.text.lower() in ['for', 'on', 'in', 'with']:
                                context_parts = []
                                for prep_grandchild in prep_child.children:
                                    if prep_grandchild.dep_ == 'pobj':
                                        context_parts.append(extract_noun_phrase_by_dependency(prep_grandchild))
                                if context_parts:
                                    opinion.context = " ".join(context_parts)
                                    break
                    
                    if opinion.object and opinion.predicate:
                        verb_strength = 'strong' if verb_lemma in OPINION_VERBS_STRONG else 'medium'
                        confidence = calculate_confidence(
                            opinion, bool(opinion.subject), bool(opinion.object),
                            bool(opinion.target), bool(opinion.context), verb_strength, token, search_doc
                        )
                        candidate_opinions.append((opinion, confidence, 4))
            
            # 策略5：查找从句补语（ccomp）- 在同一token上检查
            if 'ccomp' in children_by_dep:
                for ccomp_child in children_by_dep['ccomp']:
                    opinion = StructuredOpinion()
                    ccomp_subject = subject  # 复用已查找的subject
                    if ccomp_subject:
                        opinion.subject = ccomp_subject
                    
                    # 在ccomp中查找object（通常是ccomp的主语）
                    ccomp_obj = None
                    for ccomp_grandchild in ccomp_child.children:
                        if ccomp_grandchild.dep_ in ['nsubj', 'nsubjpass']:
                            ccomp_obj = extract_noun_phrase_by_dependency(ccomp_grandchild)
                            break
                    
                    if ccomp_obj:
                        opinion.object = ccomp_obj
                    elif ccomp_subject:
                        opinion.object = ccomp_subject
                    
                    # predicate是主动词
                    opinion.predicate = verb_lemma
                    
                    # 查找context（复用已收集的prep信息）
                    if 'prep' in children_by_dep:
                        for prep_child in children_by_dep['prep']:
                            if prep_child.text.lower() in ['for', 'on', 'in', 'with']:
                                context_parts = []
                                for prep_grandchild in prep_child.children:
                                    if prep_grandchild.dep_ == 'pobj':
                                        context_parts.append(extract_noun_phrase_by_dependency(prep_grandchild))
                                if context_parts:
                                    opinion.context = " ".join(context_parts)
                                    break
                    
                    if opinion.object and opinion.predicate:
                        verb_strength = 'strong' if verb_lemma in OPINION_VERBS_STRONG else 'medium'
                        confidence = calculate_confidence(
                            opinion, bool(opinion.subject), bool(opinion.object),
                            bool(opinion.target), bool(opinion.context), verb_strength, token, search_doc
                        )
                        candidate_opinions.append((opinion, confidence, 5))
        
        # 策略2：查找被动语态的观点性动词
        if token_pos == "VERB" and token_dep == "nsubjpass":
            verb_lemma = token.lemma_.lower()
            if verb_lemma in OPINION_VERBS_STRONG | OPINION_VERBS_MEDIUM:
                opinion = StructuredOpinion()
                children_by_dep = {}
                for child in token.children:
                    if child.dep_ not in children_by_dep:
                        children_by_dep[child.dep_] = []
                    children_by_dep[child.dep_].append(child)
                
                # 被动语态：主语是受事（object）
                if 'nsubjpass' in children_by_dep:
                    opinion.object = extract_noun_phrase_by_dependency(children_by_dep['nsubjpass'][0])
                
                # 查找by短语（施事）
                if 'agent' in children_by_dep:
                    for agent_child in children_by_dep['agent']:
                        for agent_grandchild in agent_child.children:
                            if agent_grandchild.dep_ == 'pobj':
                                agent_text = extract_noun_phrase_by_dependency(agent_grandchild)
                                opinion.subject = agent_text
                                if not opinion.target:
                                    opinion.target = agent_text
                                break
                
                # 查找背景条件（context）
                if 'prep' in children_by_dep:
                    for prep_child in children_by_dep['prep']:
                        prep_text = prep_child.text.lower()
                        if prep_text in ['for', 'on', 'in', 'with', 'under', 'when']:
                            context_parts = []
                            for prep_grandchild in prep_child.children:
                                if prep_grandchild.dep_ == 'pobj':
                                    context_parts.append(extract_noun_phrase_by_dependency(prep_grandchild))
                                elif prep_grandchild.dep_ in ['det', 'amod']:
                                    context_parts.insert(0, prep_grandchild.text)
                            if context_parts:
                                opinion.context = " ".join(context_parts)
                                break
                
                opinion.predicate = verb_lemma
                if opinion.object and opinion.predicate:
                    verb_strength = 'strong' if verb_lemma in OPINION_VERBS_STRONG else 'medium'
                    confidence = calculate_confidence(
                        opinion, bool(opinion.subject), bool(opinion.object),
                        bool(opinion.target), bool(opinion.context), verb_strength, token, search_doc
                    )
                    candidate_opinions.append((opinion, confidence, 2))
        
        # 策略3：查找系动词+表语结构（is/are + adjective/noun）
        if token.lemma_.lower() in ['be', 'is', 'are', 'was', 'were']:
            children_by_dep = {}
            for child in token.children:
                if child.dep_ not in children_by_dep:
                    children_by_dep[child.dep_] = []
                children_by_dep[child.dep_].append(child)
            
            # 查找表语（attr, acomp）
            if 'attr' in children_by_dep or 'acomp' in children_by_dep:
                for dep in ['attr', 'acomp']:
                    if dep in children_by_dep:
                        for child in children_by_dep[dep]:
                            opinion = StructuredOpinion()
                            # 查找主语
                            subject = None
                            if 'nsubj' in children_by_dep or 'nsubjpass' in children_by_dep:
                                for s_dep in ['nsubj', 'nsubjpass']:
                                    if s_dep in children_by_dep:
                                        subject = extract_noun_phrase_by_dependency(children_by_dep[s_dep][0])
                                        opinion.subject = subject
                                        break
                            
                            if subject:
                                opinion.object = subject
                                # 表语作为predicate的一部分
                                if child.pos_ == "ADJ":
                                    opinion.predicate = f"is {child.lemma_}"
                                else:
                                    opinion.predicate = f"is {extract_noun_phrase_by_dependency(child)}"
                                
                                # 查找背景条件（context）
                                if 'prep' in children_by_dep:
                                    for prep_child in children_by_dep['prep']:
                                        prep_text = prep_child.text.lower()
                                        if prep_text in ['for', 'on', 'in', 'with', 'under', 'when']:
                                            context_parts = []
                                            for prep_grandchild in prep_child.children:
                                                if prep_grandchild.dep_ == 'pobj':
                                                    context_parts.append(extract_noun_phrase_by_dependency(prep_grandchild))
                                                elif prep_grandchild.dep_ in ['det', 'amod']:
                                                    context_parts.insert(0, prep_grandchild.text)
                                            if context_parts:
                                                opinion.context = " ".join(context_parts)
                                                break
                                
                                if opinion.object and opinion.predicate:
                                    confidence = calculate_confidence(
                                        opinion, bool(opinion.subject), bool(opinion.object),
                                        bool(opinion.target), bool(opinion.context), 'medium', token, search_doc
                                    )
                                    candidate_opinions.append((opinion, confidence, 3))
                        break
    
    # 多候选策略：返回多个高置信度候选，按置信度排序
    if candidate_opinions:
        # 按置信度降序排序，置信度相同时按策略优先级排序（策略1优先）
        candidate_opinions.sort(key=lambda x: (-x[1], x[2]))
        
        # 过滤低质量候选（置信度>=0.4）
        high_confidence_candidates = [(op, conf, strat) for op, conf, strat in candidate_opinions if conf >= 0.4]
        
        if high_confidence_candidates:
            # 返回最高置信度的候选（保持向后兼容）
            best_opinion, best_confidence, best_strategy = high_confidence_candidates[0]
            best_opinion = detect_opinion_stance(sentence, best_opinion, doc)
            
            # 如果存在多个高置信度候选（置信度差异<0.1），可以考虑返回多个
            # 但为了保持接口兼容性，先返回最佳候选
            # 可以在StructuredOpinion中添加alternatives字段存储其他候选
            if len(high_confidence_candidates) > 1:
                # 检查是否有多个候选置信度接近（差异<0.1）
                top_confidence = high_confidence_candidates[0][1]
                alternatives = []
                for alt_op, alt_conf, alt_strat in high_confidence_candidates[1:]:
                    if top_confidence - alt_conf < 0.1:  # 置信度差异小于0.1
                        alt_op = detect_opinion_stance(sentence, alt_op, doc)
                        alternatives.append((alt_op, alt_conf, alt_strat))
                
                # 将备选候选存储在元数据中（如果后续需要）
                # 当前先返回最佳候选
                return best_opinion
            
            return best_opinion
    
    return None

# 同义词归一化词典（可扩展）
SYNONYM_MAP = {
    # Transformer相关
    'transformer architecture': 'transformer',
    'transformer model': 'transformer',
    'the transformer': 'transformer',
    'transformer encoder': 'transformer',
    'transformer decoder': 'transformer',
    'transformer network': 'transformer',
    'attention mechanism': 'attention',
    'self-attention': 'attention',
    'multi-head attention': 'attention',
    # RNN相关
    'rnn model': 'rnn',
    'recurrent neural network': 'rnn',
    'recurrent network': 'rnn',
    'lstm model': 'lstm',
    'long short-term memory': 'lstm',
    'lstm network': 'lstm',
    'gru model': 'gru',
    'gated recurrent unit': 'gru',
    # BERT相关
    'bert model': 'bert',
    'bidirectional encoder representations from transformers': 'bert',
    'bert encoder': 'bert',
    'bert-base': 'bert',
    'bert-large': 'bert',
    # ResNet相关
    'resnet model': 'resnet',
    'residual network': 'resnet',
    'resnet architecture': 'resnet',
    # CNN相关
    'convolutional neural network': 'cnn',
    'cnn model': 'cnn',
    'convnet': 'cnn',
    'convolutional network': 'cnn',
    # GAN相关
    'generative adversarial network': 'gan',
    'gan model': 'gan',
    'adversarial network': 'gan',
    # 其他常见模型
    'vgg model': 'vgg',
    'vgg network': 'vgg',
    'alexnet': 'alexnet',
    'googlenet': 'googlenet',
    'inception': 'inception',
    'yolo': 'yolo',
    'you only look once': 'yolo',
    # 方法相关
    'deep learning': 'deep learning',
    'deep neural network': 'deep learning',
    'dnn': 'deep learning',
    'machine learning': 'machine learning',
    'ml': 'machine learning',
    'neural network': 'neural network',
    'nn': 'neural network',
    # 任务相关
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

def abstract_object_phrase(phrase: str, doc=None) -> str:
    """对象抽象化：保留完整语义信息，仅去除无关限定词"""
    if not phrase:
        return ""
    
    # 转换为小写并去除前后空格
    phrase_lower = normalize_text(phrase)
    
    # 同义词归一化（保留，但仅用于完全匹配的情况）
    for synonym, canonical in SYNONYM_MAP.items():
        if phrase_lower == synonym:
            return canonical
    
    # 去除无关限定词，但保留关键修饰词（数量、重要形容词等）
    words = phrase_lower.split()
    # 仅去除基本限定词，保留数量词、重要形容词等
    filtered_words = [w for w in words if w not in ['the', 'a', 'an', 'this', 'that']]
    
    if filtered_words:
        # 返回完整短语（保留所有关键信息）
        return " ".join(filtered_words)
    
    return phrase_lower

def normalize_opinion_to_string(structured_opinion: StructuredOpinion) -> str:
    """将结构化观点转换为标准字符串，用于向量嵌入和去重"""
    global _stage5_normalization_stats
    _stage5_normalization_stats['total_structured'] += 1
    
    if not structured_opinion.object or not structured_opinion.predicate:
        _stage5_normalization_stats['normalized_failed'] += 1
        if not structured_opinion.object:
            _stage5_normalization_stats['failed_reasons']['missing_object'] += 1
        if not structured_opinion.predicate:
            _stage5_normalization_stats['failed_reasons']['missing_predicate'] += 1
        
        if len(_stage5_normalization_stats['failed_samples']) < 10:
            _stage5_normalization_stats['failed_samples'].append({
                'reason': 'missing_field',
                'has_object': bool(structured_opinion.object),
                'has_predicate': bool(structured_opinion.predicate),
                'object': structured_opinion.object[:50] if structured_opinion.object else None,
                'predicate': structured_opinion.predicate[:50] if structured_opinion.predicate else None
            })
        return ""
    
    # 抽象化对象
    object_abstracted = abstract_object_phrase(structured_opinion.object)
    
    # 组装核心观点：对象 + 判断 + 评价目标
    core = f"{object_abstracted} {structured_opinion.predicate}"
    
    if structured_opinion.target:
        target_abstracted = abstract_object_phrase(structured_opinion.target)
        core += f" {target_abstracted}"
    
    # 添加强度修饰
    if structured_opinion.strength:
        if structured_opinion.strength == 'high':
            core = f"significantly {core}"
        elif structured_opinion.strength == 'medium':
            core = f"moderately {core}"
        elif structured_opinion.strength == 'low':
            core = f"slightly {core}"
        else:
            core = f"{structured_opinion.strength} {core}"
    
    # 处理否定观点
    if structured_opinion.polarity == "negative":
        if not core.startswith("does not") and not core.startswith("fails"):
            core = f"does not {core}"
    
    # 添加背景条件（可选，用于区分不同场景下的相同观点）
    if structured_opinion.context:
        context_clean = structured_opinion.context.strip()[:50]  # 截断过长
        core += f" {context_clean}"
    
    # 使用现有的normalize_text函数标准化
    normalized = normalize_text(core)
    if normalized:
        _stage5_normalization_stats['normalized_success'] += 1
    else:
        _stage5_normalization_stats['normalized_failed'] += 1
        _stage5_normalization_stats['failed_reasons']['normalize_text_empty'] += 1
        if len(_stage5_normalization_stats['failed_samples']) < 10:
            _stage5_normalization_stats['failed_samples'].append({
                'reason': 'normalize_text_empty',
                'core': core[:100]
            })
    
    return normalized

# 全局调试计数器（用于统计）
_extract_debug_count = {'total': 0, 'stage1_empty': 0, 'stage2_empty': 0, 'stage3_empty': 0, 'stage5_empty': 0}
# 区分有摘要/无摘要的统计
_extract_debug_count_by_abstract = {
    'total_with_abstract': 0,
    'total_without_abstract': 0,
    'stage1_empty_with_abstract': 0,
    'stage1_empty_without_abstract': 0,
    'stage2_empty_with_abstract': 0,
    'stage2_empty_without_abstract': 0,
    'stage3_empty_with_abstract': 0,
    'stage3_empty_without_abstract': 0,
    'stage5_empty_with_abstract': 0,
    'stage5_empty_without_abstract': 0,
}
_filtered_paper_ids = {
    'stage1_empty': [],
    'stage2_empty': [],
    'stage3_empty': [],
    'stage5_empty': [],
}
# 被过滤论文的详细信息（用于误过滤检查）
_filtered_paper_details = {
    'stage2_empty': [],  # [(paper_id, title, abstract, max_confidence, reason, core_findings)]
    'stage3_empty': [],  # [(paper_id, title, abstract, reason, core_findings)]
    'stage5_empty': [],  # [(paper_id, title, abstract, reason, core_findings)]
}

# 成功提取观点的论文详情（用于保存样本）
_successful_paper_details = []  # [(paper_id, title, abstract, opinions_list, year)]

# 成功案例采样比例（5%）
SUCCESS_SAMPLE_RATE = 0.05
SUCCESS_SAMPLE_MIN = 10  # 最少采样数量
SUCCESS_SAMPLE_MAX = 100  # 最多采样数量
# 阶段2规则验证统计（用于诊断）
_stage2_verification_stats = {
    'total_verified': 0,
    'failed_verb': 0,
    'failed_structure': 0,
    'failed_assertion': 0,
    'passed': 0,
    'samples': [],
    'passed_samples': [],
    'false_negative_count': 0,  # 误过滤数量（真正的观点被过滤）
    'true_negative_count': 0,  # 正确过滤数量（非观点被正确过滤）
    'false_positive_count': 0,  # 误通过数量（非观点被误通过）
    'true_positive_count': 0,  # 正确通过数量（真正的观点被正确通过）
    'uncertain_count': 0  # 不确定数量
}
# 阶段3-4结构化抽取统计（新增）
_stage3_extraction_stats = {
    'total_sentences': 0,
    'template_matched': 0,
    'dependency_matched': 0,
    'extraction_failed': 0,
    'field_missing': 0,
    'failed_samples': []
}

# 模板匹配统计（用于动态调整优先级）
_template_match_stats = {}  # {template_index: {'matches': int, 'successes': int, 'failures': int}}

# 置信度校准参数
_confidence_calibration = {
    'enabled': False,
    'calibration_data': [],  # [(confidence, is_correct), ...]
    'calibrated_threshold': 0.4,  # 校准后的阈值
    'base_threshold': 0.4,  # 原始阈值
    'calibration_method': 'isotonic'  # 'isotonic' 或 'platt'
}

# 置信度融合权重（可调整）
CONFIDENCE_WEIGHTS = {
    'rule': 0.5,      # 规则置信度权重
    'semantic': 0.4,  # 语义模型置信度权重（待实现）
    'syntax': 0.1     # 句法置信度权重
}

# 置信度阈值（0-1）
CONFIDENCE_THRESHOLD = 0.4
# 阶段5规范化统计（新增）
_stage5_normalization_stats = {
    'total_structured': 0,
    'normalized_success': 0,
    'normalized_failed': 0,
    'failed_reasons': {
        'missing_object': 0,
        'missing_predicate': 0,
        'normalize_text_empty': 0
    },
    'failed_samples': []
}

def detect_opinion_sentences_unified(doc, emb_model=None, cache=None, has_abstract=False) -> Tuple[List[Tuple[str, float]], float]:
    """统一的观点检测器（合并阶段1+2）
    
    使用置信度机制，返回句子和置信度分数对，以及最高置信度分数
    
    Args:
        doc: spaCy文档对象
        emb_model: 嵌入模型（可选，用于语义置信度）
        cache: 嵌入缓存（可选）
        has_abstract: 是否有摘要
    
    Returns:
        Tuple[List[Tuple[str, float]], float]: 
            - (句子文本, 置信度分数) 列表，按置信度降序排序
            - 最高置信度分数（即使低于阈值）
    """
    # 检测[ABSTRACT]标记位置
    doc_text = doc.text
    abstract_marker_pos = doc_text.find('[ABSTRACT]')
    doc_sents_list = list(doc.sents)
    
    def is_title_sentence(sent):
        """判断句子是否为标题"""
        if abstract_marker_pos == -1:
            return sent == doc_sents_list[0] and len(sent.text) < 200
        else:
            return sent.start_char < abstract_marker_pos
    
    # 统一检测：对每个句子计算置信度
    sentence_confidences = []
    max_confidence = 0.0  # 记录最高置信度（即使低于阈值）
    
    for sent in doc_sents_list:
        sent_text = sent.text.strip()
        
        # 基本过滤：长度检查
        is_title = is_title_sentence(sent)
        min_length = 5 if is_title else 10
        if len(sent_text) < min_length:
            continue
        
        # 计算规则置信度
        rule_conf = calculate_rule_confidence(sent_text, sent, is_title=is_title)
        
        # 计算句法置信度
        syntax_conf = calculate_syntax_confidence(sent_text, sent)
        
        # 语义置信度（待实现，暂时为None）
        semantic_conf = None
        
        # 融合置信度
        fused_conf = fuse_confidence_scores(rule_conf, semantic_conf, syntax_conf)
        
        # 更新最高置信度
        if fused_conf > max_confidence:
            max_confidence = fused_conf
        
        # 只保留置信度超过阈值的句子
        if fused_conf >= CONFIDENCE_THRESHOLD:
            sentence_confidences.append((sent_text, fused_conf))
    
    # 按置信度降序排序
    sentence_confidences.sort(key=lambda x: x[1], reverse=True)
    
    return sentence_confidences, max_confidence

# =========================
# ResearchInsightMiner 类（来自 6_2_3）
# =========================
class ResearchInsightMiner:
    def __init__(self, device: str = None):
        """
        初始化全流程 GPU 流水线
        """
        self.device = device if device else ('cuda' if torch.cuda.is_available() else 'cpu')
        print(f"⚡ System initialized on: {self.device.upper()}")

        # --- Module 1: Coref & Spacy ---
        print("Loading Module 1: Coreference Resolution & Segmentation...")
        self.coref_model = FCoref(device=self.device)
        
        try:
            spacy.require_gpu()
            self.nlp = spacy.load("en_core_web_trf")
        except:
            self.nlp = spacy.load("en_core_web_sm")

        # --- Module 2: NLI Engine ---
        print("Loading Module 2: DeBERTa-v3-Large NLI Engine...")
        self.nli_model = CrossEncoder('cross-encoder/nli-deberta-v3-large', device=self.device)
        
        self.hypotheses = {
            "AIM": "This study aims to investigate a specific problem or proposes a new method.",
            "CONCLUSION": "This sentence presents a key finding, result, or conclusion of the research.",
            "METHOD": "This sentence describes the methodology, dataset, or experimental setup."
        }

        # --- Module 3: Embeddings ---
        print("Loading Module 3: BGE-M3 Semantic Embeddings...")
        self.emb_model = SentenceTransformer('BAAI/bge-m3', device=self.device)
        
        self.anchors = {
            "AIM": self.emb_model.encode(["The objective is", "We propose", "The goal of this paper"], convert_to_tensor=True),
            "CONCLUSION": self.emb_model.encode(["Results show", "We conclude", "Therefore"], convert_to_tensor=True),
            "METHOD": self.emb_model.encode(["We utilized", "The dataset", "The experiment"], convert_to_tensor=True)
        }

        print("✅ All Systems Operational. Ready for Inference.")

    def _apply_coref(self, text: str) -> str:
        """
        【修复核心】手动应用共指消解
        1. 预测簇 (Predict Clusters)
        2. 倒序替换文本 (Reverse Substitution)
        """
        # 1. 获取预测结果
        preds = self.coref_model.predict(texts=[text])
        
        # 2. 获取簇的字符偏移量 (Indices)
        # 格式: [[(start, end), (start, end)], [...]]
        clusters = preds[0].get_clusters(as_strings=False)
        
        # 3. 构建替换列表
        replacements = []
        for cluster in clusters:
            # 策略: 取簇中第一个出现的词作为"本体" (通常是全称)
            # 例如 cluster: [(0, 10 "The Model"), (50, 52 "It")]
            # 我们把 "It" 替换为 "The Model"
            main_span = cluster[0] 
            main_text = text[main_span[0]:main_span[1]]
            
            # 对簇中剩余的词进行替换
            for mention_span in cluster[1:]:
                start, end = mention_span
                # 只有当是代词或短词时才替换，防止把 "The Algorithm" 替换成 "The Algorithm" (没必要)
                # 这里简单粗暴全替换，或者你可以加 len(mention) < 5 的判断
                replacements.append((start, end, main_text))
        
        # 4. 按起始位置倒序排序 (必须倒序，否则替换会破坏后续索引)
        replacements.sort(key=lambda x: x[0], reverse=True)
        
        # 5. 执行替换
        text_list = list(text)
        for start, end, new_str in replacements:
            # 简单的替换逻辑
            text_list[start:end] = list(new_str)
            
        return "".join(text_list)

    def _module_1_process_text(self, text: str) -> List[str]:
        """执行共指消解 + 智能分句"""
        # A. 共指消解 (修复后的调用)
        try:
            # 先清洗一下多余空格，防止 offset 对不上
            clean_input = " ".join(text.split())
            resolved_text = self._apply_coref(clean_input)
        except Exception as e:
            print(f"⚠️ Coref failed: {e}, utilizing raw text.")
            resolved_text = text
        
        # B. 清洗与分句
        doc = self.nlp(resolved_text)
        
        # 过滤长度 < 15 字符的噪音
        sentences = [sent.text.strip() for sent in doc.sents if len(sent.text.strip()) > 15]
        return sentences

    def _module_4_apply_rules(self, sentence: str) -> Dict[str, float]:
        s_lower = sentence.lower()
        boost = {"AIM": 0.0, "CONCLUSION": 0.0, "METHOD": 0.0}
        
        if any(k in s_lower for k in ["aim:", "goal:", "we propose", "in this paper"]):
            boost["AIM"] = 0.5
        if any(k in s_lower for k in ["conclude", "result", "showed that", "demonstrates"]):
            boost["CONCLUSION"] = 0.5
        if any(k in s_lower for k in ["using", "method", "dataset", "trained on"]):
            boost["METHOD"] = 0.3
        return boost

    def _module_2_3_compute_scores(self, sentences: List[str]):
        pairs = []
        map_idx = []
        keys = ["AIM", "CONCLUSION", "METHOD"]
        
        for i, sent in enumerate(sentences):
            for k in keys:
                pairs.append([sent, self.hypotheses[k]])
                map_idx.append((i, k))
        
        # NLI Inference
        nli_logits = self.nli_model.predict(pairs, batch_size=32, show_progress_bar=False)
        nli_probs = torch.softmax(torch.tensor(nli_logits), dim=1)[:, 1]
        
        # Embedding Inference
        sent_embs = self.emb_model.encode(sentences, convert_to_tensor=True)
        
        results_map = {i: {"AIM": {}, "CONCLUSION": {}, "METHOD": {}} for i in range(len(sentences))}
        
        for idx, score in enumerate(nli_probs):
            s_i, k = map_idx[idx]
            results_map[s_i][k]['nli'] = score.item()
            
        for k in keys:
            sims = torch.nn.functional.cosine_similarity(
                sent_embs.unsqueeze(1), self.anchors[k].unsqueeze(0), dim=2
            )
            max_sims, _ = torch.max(sims, dim=1)
            for i, sim_val in enumerate(max_sims):
                results_map[i][k]['sem'] = sim_val.item()
                
        return results_map

    def extract(self, raw_text: str, threshold: float = 0.75) -> List[Dict]:
        sentences = self._module_1_process_text(raw_text)
        if not sentences: return []

        scores_map = self._module_2_3_compute_scores(sentences)
        final_output = []

        for i, sent in enumerate(sentences):
            rules = self._module_4_apply_rules(sent)
            best_cat = None
            best_final_score = -1.0
            
            for cat in ["AIM", "CONCLUSION", "METHOD"]:
                nli_score = scores_map[i][cat]['nli']
                sem_score = scores_map[i][cat]['sem']
                rule_score = rules[cat]
                
                final_score = (nli_score * 0.7) + (max(0, sem_score) * 0.1) + rule_score
                
                # Position bias
                if i == 0 and cat == "AIM": final_score += 0.15
                if i == len(sentences)-1 and cat == "CONCLUSION": final_score += 0.15
                
                if final_score > best_final_score:
                    best_final_score = final_score
                    best_cat = cat
            
            if best_final_score >= threshold:
                final_output.append({
                    "id": i + 1,
                    "category": best_cat,
                    "confidence": round(best_final_score, 3),
                    "sentence": sent,
                    "original_nli_prob": round(scores_map[i][best_cat]['nli'], 3)
                })

        return final_output

# 全局管道实例缓存
_global_miner = None

def extract_opinions_from_document(doc, emb_model, cache, has_abstract=False, paper_id=None, paper_title=None, paper_abstract=None, nlp_model=None) -> List[Tuple[str, StructuredOpinion]]:
    """从文档中提取观点（使用ResearchInsightMiner）"""
    global _extract_debug_count, _extract_debug_count_by_abstract, _filtered_paper_ids, _filtered_paper_details, _global_miner
    
    _extract_debug_count['total'] += 1
    
    if has_abstract:
        _extract_debug_count_by_abstract['total_with_abstract'] += 1
    else:
        _extract_debug_count_by_abstract['total_without_abstract'] += 1
    
    # 获取或创建ResearchInsightMiner实例
    if _global_miner is None:
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        _global_miner = ResearchInsightMiner(device=device)
    
    # 准备输入文本
    paper_text = doc.text if doc else ""
    if not paper_title:
        # 尝试从doc中提取标题（第一个短句）
        if doc:
            doc_sents = list(doc.sents)
            if doc_sents and len(doc_sents[0].text) < 200:
                paper_title = doc_sents[0].text
    
    # 组合标题和摘要
    if paper_title and paper_abstract:
        combined_text = f"{paper_title}\n\n{paper_abstract}".strip()
    elif paper_title:
        combined_text = paper_title
    elif paper_abstract:
        combined_text = paper_abstract
    else:
        combined_text = paper_text
    
    # 使用ResearchInsightMiner提取观点
    try:
        results = _global_miner.extract(combined_text, threshold=0.75)
        
        if results:
            # 将ResearchInsightMiner的Dict结果转换为Tuple[str, StructuredOpinion]格式
            opinions = []
            for res in results:
                sentence = res.get('sentence', '')
                category = res.get('category', '')
                confidence = res.get('confidence', 0.0)
                
                # 创建StructuredOpinion对象
                structured_opinion = StructuredOpinion(
                    object=sentence,  # 使用句子作为对象
                    predicate=category,  # 使用类别作为谓词
                    context=f"confidence:{confidence}"
                )
                
                # 使用句子作为规范化文本
                normalized_text = sentence
                opinions.append((normalized_text, structured_opinion))
            
            return opinions
        else:
            # 记录失败
            _extract_debug_count['stage2_empty'] += 1
            if has_abstract:
                _extract_debug_count_by_abstract['stage2_empty_with_abstract'] += 1
            else:
                _extract_debug_count_by_abstract['stage2_empty_without_abstract'] += 1
            
            failure_reason = 'ResearchInsightMiner未提取到观点'
            if paper_id is not None:
                _filtered_paper_ids['stage2_empty'].append(paper_id)
            
            # 如果提取失败，回退到核心发现提取
            findings = extract_findings_from_document(doc, emb_model, cache, has_abstract, paper_id, paper_title, paper_abstract)
            core_findings_str = ''
            if findings:
                finding_texts = [norm_text for norm_text, _ in findings]
                core_findings_str = '; '.join(finding_texts)
            
            if paper_id is not None:
                _filtered_paper_details['stage2_empty'].append((
                    paper_id,
                    paper_title or '',
                    paper_abstract or '',
                    0.0,
                    failure_reason,
                    core_findings_str
                ))
            
            return [(norm_text, StructuredOpinion(object=find.discovery_object or "", predicate=find.discovery_verb or "", context=f"finding_type:{find.finding_type}")) 
                    for norm_text, find in findings]
    
    except Exception as e:
        # 异常处理：回退到核心发现提取
        _extract_debug_count['stage2_empty'] += 1
        if has_abstract:
            _extract_debug_count_by_abstract['stage2_empty_with_abstract'] += 1
        else:
            _extract_debug_count_by_abstract['stage2_empty_without_abstract'] += 1
        
        if paper_id is not None:
            _filtered_paper_ids['stage2_empty'].append(paper_id)
        
        findings = extract_findings_from_document(doc, emb_model, cache, has_abstract, paper_id, paper_title, paper_abstract)
        return [(norm_text, StructuredOpinion(object=find.discovery_object or "", predicate=find.discovery_verb or "", context=f"finding_type:{find.finding_type}")) 
                for norm_text, find in findings]

# =========================
# 核心发现提取系统
# =========================

# 全局统计变量（核心发现）
_finding_extract_debug_count = {
    'total': 0,
    'stage1_empty': 0,
    'stage2_empty': 0,
    'stage3_empty': 0,
    'stage5_empty': 0
}

_finding_extract_debug_count_by_abstract = {
    'total_with_abstract': 0,
    'total_without_abstract': 0,
    'stage1_empty_with_abstract': 0,
    'stage1_empty_without_abstract': 0,
    'stage2_empty_with_abstract': 0,
    'stage2_empty_without_abstract': 0,
    'stage3_empty_with_abstract': 0,
    'stage3_empty_without_abstract': 0,
    'stage5_empty_with_abstract': 0,
    'stage5_empty_without_abstract': 0
}

def detect_finding_sentences(doc) -> List[Tuple[str, str, float]]:
    """检测可能包含核心发现的句子
    
    Returns:
        List[Tuple[sentence, finding_type, confidence]]: 候选句子列表
    """
    candidate_sentences = []
    doc_sents = list(doc.sents)
    if not doc_sents:
        return candidate_sentences
    
    doc_text = doc.text
    abstract_marker_pos = doc_text.find('[ABSTRACT]')
    
    def is_title_sentence(sent):
        """判断句子是否为标题"""
        if abstract_marker_pos == -1:
            return sent == doc_sents[0] and len(sent.text) < 200
        else:
            return sent.start_char < abstract_marker_pos
    
    for sent in doc_sents:
        sent_text = sent.text.strip()
        if len(sent_text) < 10:
            continue
        
        sent_lower = sent_text.lower()
        is_title = is_title_sentence(sent)
        
        # 检查每种发现类型，收集所有匹配的类型
        matched_types = []
        for finding_type, config in FINDING_TYPES.items():
            # 检查关键词
            has_keyword = any(kw in sent_lower for kw in config['keywords'])
            
            # 检查模式（优化：使用编译后的正则表达式）
            matches_pattern = False
            for pattern in config['patterns']:
                compiled_pattern = get_compiled_pattern(pattern)
                if compiled_pattern.search(sent_text):
                    matches_pattern = True
                    break
            
            if has_keyword or matches_pattern:
                # 计算置信度
                confidence = config['confidence_base']
                if is_title:
                    confidence += 0.1  # 标题加分
                if matches_pattern:
                    confidence += 0.1  # 模式匹配加分
                if has_keyword and matches_pattern:
                    confidence += 0.05  # 双重匹配加分
                
                confidence = min(1.0, confidence)
                priority = config.get('priority', 999)  # 默认优先级最低
                matched_types.append((finding_type, confidence, priority))
        
        # 如果匹配到类型，选择优先级最高的（priority值最小的）
        if matched_types:
            # 优化：如果只有一个匹配类型，直接使用，避免排序
            if len(matched_types) == 1:
                best_type, best_confidence, _ = matched_types[0]
            else:
                # 按优先级排序（priority小的优先），然后按置信度排序
                matched_types.sort(key=lambda x: (x[2], -x[1]))  # 先按priority升序，再按confidence降序
                best_type, best_confidence, _ = matched_types[0]
            candidate_sentences.append((sent_text, best_type, best_confidence))
    
    return candidate_sentences

def extract_structured_finding_from_sentence(sentence: str, doc, finding_type: str) -> Optional[StructuredFinding]:
    """从句子中提取结构化核心发现（改进版：保留完整语义信息）"""
    finding = StructuredFinding()
    finding.finding_type = finding_type
    finding.source_sentence = sentence
    finding.confidence = FINDING_TYPES.get(finding_type, {}).get('confidence_base', 0.3)
    
    sent_lower = sentence.lower()
    
    # 检测是否为标题（更可靠的方法）
    doc_text = doc.text
    abstract_marker_pos = doc_text.find('[ABSTRACT]')
    doc_sents = list(doc.sents)
    is_title = False
    if not doc_sents:
        finding.source_type = "abstract"
    elif abstract_marker_pos == -1:
        # 没有分隔符，检查是否是第一个句子且较短
        if doc_sents[0].text.strip() == sentence.strip() and len(sentence) < 200:
            is_title = True
            finding.source_type = "title"
        else:
            finding.source_type = "abstract"
    else:
        # 有分隔符，检查句子是否在分隔符之前
        for sent in doc_sents:
            if sent.text.strip() == sentence.strip():
                is_title = (sent.start_char < abstract_marker_pos)
                finding.source_type = "title" if is_title else "abstract"
                break
        else:
            # 如果找不到匹配的句子，默认为摘要
            finding.source_type = "abstract"
    
    # 定位目标句子
    sent_doc = None
    for sent in doc.sents:
        if sent.text.strip() == sentence.strip():
            sent_doc = sent
            break
    
    if sent_doc is None:
        sent_doc = doc
    
    # 预构建noun_chunks映射
    noun_chunk_map = {}
    for chunk in sent_doc.noun_chunks:
        for token in chunk:
            if token.i not in noun_chunk_map:
                noun_chunk_map[token.i] = chunk.text
    
    # 辅助函数：基于依存关系提取完整的名词短语
    def extract_noun_phrase_by_dependency(head_token):
        """基于依存关系提取完整名词短语（包含所有修饰词）"""
        if head_token.i in noun_chunk_map:
            return noun_chunk_map[head_token.i]
        
        tokens = [head_token]
        visited = {head_token.i}
        modifier_deps = ['amod', 'det', 'compound', 'nummod', 'nmod', 'poss', 'quantmod', 'appos']
        
        # 限制收集的修饰词数量，避免跨句子收集过多内容
        max_tokens = 15
        
        def collect_modifiers(token, is_before_head=True):
            if token.i in visited or len(tokens) >= max_tokens:
                return
            # 限制token与head_token的距离（避免跨句子）
            if abs(token.i - head_token.i) > 20:
                return
            visited.add(token.i)
            
            if token.dep_ in modifier_deps:
                if is_before_head or token.i < head_token.i:
                    insert_pos = 0
                    for i, t in enumerate(tokens):
                        if t.i > token.i:
                            insert_pos = i
                            break
                        insert_pos = i + 1
                    tokens.insert(insert_pos, token)
                else:
                    insert_pos = len(tokens)
                    for i, t in enumerate(tokens):
                        if t.i > token.i:
                            insert_pos = i
                            break
                    tokens.insert(insert_pos, token)
            
            for grandchild in token.children:
                if grandchild.dep_ in modifier_deps and len(tokens) < max_tokens:
                    collect_modifiers(grandchild, is_before_head=(grandchild.i < head_token.i))
        
        for child in head_token.children:
            if child.i in visited or len(tokens) >= max_tokens:
                continue
            if child.dep_ in modifier_deps:
                collect_modifiers(child, is_before_head=(child.i < head_token.i))
        
        tokens.sort(key=lambda t: t.i)
        return " ".join([t.text for t in tokens])
    
    # 辅助函数：从文本中查找匹配的token（改进：更精确的匹配）
    def find_matching_token(text, sent_doc):
        """查找与文本匹配的token，优先匹配完整短语"""
        text_lower = text.lower().strip()
        text_words = text_lower.split()
        
        if not text_words:
            return None
        
        # 优先尝试精确匹配完整短语（通过noun_chunks）
        for chunk in sent_doc.noun_chunks:
            chunk_text = chunk.text.lower().strip()
            # 精确匹配优先
            if chunk_text == text_lower:
                return chunk.root
            # 然后尝试包含匹配（但要求至少匹配第一个词）
            if text_words[0] in chunk_text and (text_lower in chunk_text or chunk_text in text_lower):
                return chunk.root
        
        # 如果noun_chunks匹配失败，尝试匹配单个token
        if len(text_words) == 1:
            for token in sent_doc:
                if token.text.lower() == text_words[0] and token.pos_ in ['NOUN', 'PROPN']:
                    return token
        else:
            # 多词短语：优先查找包含所有词的chunk，否则查找第一个匹配的词
            best_match = None
            best_score = 0
            for chunk in sent_doc.noun_chunks:
                chunk_text = chunk.text.lower()
                # 计算匹配的词数
                matched_words = sum(1 for word in text_words if word in chunk_text)
                if matched_words > best_score and matched_words >= len(text_words) // 2:
                    best_score = matched_words
                    best_match = chunk.root
            
            if best_match:
                return best_match
            
            # 如果找不到好的chunk匹配，查找第一个匹配的词
            for token in sent_doc:
                if token.text.lower() == text_words[0] and token.pos_ in ['NOUN', 'PROPN']:
                    return token
        
        return None
    
    # 根据发现类型提取结构化信息（改进：使用完整名词短语）
    if finding_type == 'mechanism_revelation':
        match = re.search(r'\b(\w+(?:\s+\w+)*?)\s+mediates?\s+(\w+(?:\s+\w+)*?)\b', sentence, re.IGNORECASE)
        if match:
            obj_text = match.group(1)
            content_text = match.group(2)
            # 使用依存句法提取完整短语
            matching_token = find_matching_token(obj_text, sent_doc)
            if matching_token:
                finding.discovery_object = extract_noun_phrase_by_dependency(matching_token)
            else:
                finding.discovery_object = obj_text
            matching_token = find_matching_token(content_text, sent_doc)
            if matching_token:
                finding.discovery_content = extract_noun_phrase_by_dependency(matching_token)
            else:
                finding.discovery_content = content_text
            finding.discovery_verb = "mediate"
        else:
            match = re.search(r'\b(\w+(?:\s+\w+)*?)\s+regulates?\s+(\w+(?:\s+\w+)*?)\b', sentence, re.IGNORECASE)
            if match:
                obj_text = match.group(1)
                content_text = match.group(2)
                matching_token = find_matching_token(obj_text, sent_doc)
                if matching_token:
                    finding.discovery_object = extract_noun_phrase_by_dependency(matching_token)
                else:
                    finding.discovery_object = obj_text
                matching_token = find_matching_token(content_text, sent_doc)
                if matching_token:
                    finding.discovery_content = extract_noun_phrase_by_dependency(matching_token)
                else:
                    finding.discovery_content = content_text
                finding.discovery_verb = "regulate"
            else:
                match = re.search(r'\bmechanism\s+of\s+(\w+(?:\s+\w+)*?)\b', sentence, re.IGNORECASE)
                if match:
                    obj_text = match.group(1)
                    matching_token = find_matching_token(obj_text, sent_doc)
                    if matching_token:
                        finding.discovery_object = extract_noun_phrase_by_dependency(matching_token)
                    else:
                        finding.discovery_object = obj_text
                    finding.discovery_content = "mechanism"
                    finding.discovery_verb = "reveal"
    
    elif finding_type == 'new_discovery':
        match = re.search(r'\b(new|novel)\s+(\w+(?:\s+\w+)*?)\s+(species|compound|material|method|technique|ester)\b', sentence, re.IGNORECASE)
        if match:
            obj_text = match.group(2)
            matching_token = find_matching_token(obj_text, sent_doc)
            if matching_token:
                finding.discovery_object = extract_noun_phrase_by_dependency(matching_token)
            else:
                finding.discovery_object = obj_text
            finding.discovery_content = match.group(3)
            finding.discovery_verb = "discover"
        else:
            match = re.search(r'\ba\s+new\s+(\w+(?:\s+\w+)*?)\s+species\b', sentence, re.IGNORECASE)
            if match:
                obj_text = match.group(1)
                matching_token = find_matching_token(obj_text, sent_doc)
                if matching_token:
                    finding.discovery_object = extract_noun_phrase_by_dependency(matching_token)
                else:
                    finding.discovery_object = obj_text
                finding.discovery_content = "species"
                finding.discovery_verb = "discover"
            else:
                match = re.search(r'\btwo\s+new\s+(\w+(?:\s+\w+)*?)\b', sentence, re.IGNORECASE)
                if match:
                    obj_text = match.group(1)
                    matching_token = find_matching_token(obj_text, sent_doc)
                    if matching_token:
                        finding.discovery_object = extract_noun_phrase_by_dependency(matching_token)
                    else:
                        finding.discovery_object = obj_text
                    finding.discovery_content = "new compounds"
                    finding.discovery_verb = "discover"
    
    elif finding_type == 'method_development':
        match = re.search(r'\b(rapid|facile|novel|new|catalytic|automated)\s+(\w+(?:\s+\w+)*?)\b', sentence, re.IGNORECASE)
        if match:
            obj_text = match.group(2)
            matching_token = find_matching_token(obj_text, sent_doc)
            if matching_token:
                finding.discovery_object = extract_noun_phrase_by_dependency(matching_token)
            else:
                finding.discovery_object = obj_text
            finding.discovery_content = match.group(1) + " method"
            finding.discovery_verb = "develop"
        else:
            match = re.search(r'\b(\w+(?:\s+\w+)*?)\s+(probe|device|system)\b', sentence, re.IGNORECASE)
            if match:
                obj_text = match.group(1)
                matching_token = find_matching_token(obj_text, sent_doc)
                if matching_token:
                    finding.discovery_object = extract_noun_phrase_by_dependency(matching_token)
                else:
                    finding.discovery_object = obj_text
                finding.discovery_content = match.group(2)
                finding.discovery_verb = "develop"
    
    elif finding_type == 'process_description':
        match = re.search(r'\b(pyrolysis|synthesis|process|reaction)\s+of\s+(\w+(?:\s+\w+)*?)\b', sentence, re.IGNORECASE)
        if match:
            obj_text = match.group(2)
            matching_token = find_matching_token(obj_text, sent_doc)
            if matching_token:
                finding.discovery_object = extract_noun_phrase_by_dependency(matching_token)
            else:
                finding.discovery_object = obj_text
            finding.discovery_content = match.group(1)
            finding.discovery_verb = "describe"
    
    elif finding_type == 'feature_description':
        match = re.search(r'\b(characteristics?|structure|properties?|crystal\s+structure)\s+of\s+(\w+(?:\s+\w+)*?)\b', sentence, re.IGNORECASE)
        if match:
            obj_text = match.group(2)
            matching_token = find_matching_token(obj_text, sent_doc)
            if matching_token:
                finding.discovery_object = extract_noun_phrase_by_dependency(matching_token)
            else:
                finding.discovery_object = obj_text
            finding.discovery_content = match.group(1)
            finding.discovery_verb = "describe"
    
    elif finding_type == 'result_report':
        match = re.search(r'\b(\w+(?:\s+\w+)*?)\s+(are|is)\s+(\w+(?:\s+\w+)*?)\b', sentence, re.IGNORECASE)
        if match:
            obj_text = match.group(1)
            content_text = match.group(3)
            matching_token = find_matching_token(obj_text, sent_doc)
            if matching_token:
                finding.discovery_object = extract_noun_phrase_by_dependency(matching_token)
            else:
                finding.discovery_object = obj_text
            matching_token = find_matching_token(content_text, sent_doc)
            if matching_token:
                finding.discovery_content = extract_noun_phrase_by_dependency(matching_token)
            else:
                finding.discovery_content = content_text
            finding.discovery_verb = "report"
    
    elif finding_type == 'method_application':
        match = re.search(r'\buse\s+of\s+(\w+(?:\s+\w+)*?)\s+for\s+(\w+(?:\s+\w+)*?)\b', sentence, re.IGNORECASE)
        if match:
            obj_text = match.group(1)
            content_text = match.group(2)
            matching_token = find_matching_token(obj_text, sent_doc)
            if matching_token:
                finding.discovery_object = extract_noun_phrase_by_dependency(matching_token)
            else:
                finding.discovery_object = obj_text
            matching_token = find_matching_token(content_text, sent_doc)
            if matching_token:
                finding.discovery_content = extract_noun_phrase_by_dependency(matching_token)
            else:
                finding.discovery_content = content_text
            finding.discovery_verb = "apply"
        else:
            match = re.search(r'\bmanagement\s+of\s+(\w+(?:\s+\w+)*?)\b', sentence, re.IGNORECASE)
            if match:
                obj_text = match.group(1)
                matching_token = find_matching_token(obj_text, sent_doc)
                if matching_token:
                    finding.discovery_object = extract_noun_phrase_by_dependency(matching_token)
                else:
                    finding.discovery_object = obj_text
                finding.discovery_content = "management"
                finding.discovery_verb = "apply"
    
    elif finding_type == 'theory_concept':
        match = re.search(r'\b(\w+(?:\s+\w+)*?)\s+science\b', sentence, re.IGNORECASE)
        if match:
            obj_text = match.group(1)
            matching_token = find_matching_token(obj_text, sent_doc)
            if matching_token:
                finding.discovery_object = extract_noun_phrase_by_dependency(matching_token)
            else:
                finding.discovery_object = obj_text
            finding.discovery_content = "science"
            finding.discovery_verb = "discuss"
    
    # 如果无法提取结构化信息，使用依存句法提取完整名词短语
    if not finding.discovery_object:
        if sent_doc:
            # 优先使用noun_chunks
            noun_chunks_list = list(sent_doc.noun_chunks)
            if noun_chunks_list:
                first_chunk = noun_chunks_list[0]
                finding.discovery_object = first_chunk.text
            else:
                # 使用依存句法提取第一个名词短语
                for token in sent_doc:
                    if token.pos_ in ['NOUN', 'PROPN']:
                        finding.discovery_object = extract_noun_phrase_by_dependency(token)
                        break
            if not finding.discovery_object:
                # 最后回退：使用前几个词（保留更多信息）
                words = sentence.split()[:5]
                finding.discovery_object = " ".join(words)
            finding.discovery_content = "finding"
            finding.discovery_verb = "report"
        else:
            words = sentence.split()[:5]
            finding.discovery_object = " ".join(words)
            finding.discovery_content = "finding"
            finding.discovery_verb = "report"
    
    # 确保至少有一个基本字段
    if not finding.discovery_object:
        return None
    
    return finding

def normalize_finding_to_string(structured_finding: StructuredFinding) -> str:
    """将结构化核心发现转换为标准字符串，用于向量嵌入和去重（改进版：保留完整语义信息）
    
    注意：finding_type信息保存在StructuredOpinion的context字段中，不包含在norm_text中
    这样可以避免信息冗余，同时保持norm_text的简洁性
    """
    if not structured_finding.discovery_object:
        return ""
    
    # 最小化抽象化：仅去除无关限定词，保留完整语义信息
    object_processed = abstract_object_phrase(structured_finding.discovery_object)
    if not object_processed:
        return ""
    
    # 组装核心发现：对象 + 动词 + 内容（保留完整信息）
    core = object_processed
    
    if structured_finding.discovery_verb:
        core += f" {structured_finding.discovery_verb}"
    
    if structured_finding.discovery_content:
        # 对于内容，也进行最小化处理，保留关键信息
        content_processed = abstract_object_phrase(structured_finding.discovery_content)
        if content_processed:
            core += f" {content_processed}"
    
    # 最终规范化：转换为小写并去除多余空格
    normalized = normalize_text(core)
    
    return normalized

def extract_findings_from_document(doc, emb_model, cache, has_abstract=False, paper_id=None, paper_title=None, paper_abstract=None) -> List[Tuple[str, StructuredFinding]]:
    """从文档中提取核心发现（当观点提取失败时使用）"""
    global _finding_extract_debug_count, _finding_extract_debug_count_by_abstract
    
    _finding_extract_debug_count['total'] += 1
    
    if has_abstract:
        _finding_extract_debug_count_by_abstract['total_with_abstract'] += 1
    else:
        _finding_extract_debug_count_by_abstract['total_without_abstract'] += 1
    
    # 阶段1：检测可能包含核心发现的句子
    candidate_sentences = detect_finding_sentences(doc)
    
    if not candidate_sentences:
        _finding_extract_debug_count['stage1_empty'] += 1
        if has_abstract:
            _finding_extract_debug_count_by_abstract['stage1_empty_with_abstract'] += 1
        else:
            _finding_extract_debug_count_by_abstract['stage1_empty_without_abstract'] += 1
        return []
    
    # 阶段2：按置信度排序，选择高置信度的句子
    # 优化：如果候选句子数量较少，不需要排序
    # 注意：由于阶段1已经检查了candidate_sentences不为空，所以confirmed_sentences也不会为空
    if len(candidate_sentences) > 5:
        candidate_sentences.sort(key=lambda x: x[2], reverse=True)
        confirmed_sentences = candidate_sentences[:5]  # 最多选择5个句子
    else:
        confirmed_sentences = candidate_sentences
    
    # 防御性检查：理论上不会发生，但保留以防万一
    if not confirmed_sentences:
        _finding_extract_debug_count['stage2_empty'] += 1
        if has_abstract:
            _finding_extract_debug_count_by_abstract['stage2_empty_with_abstract'] += 1
        else:
            _finding_extract_debug_count_by_abstract['stage2_empty_without_abstract'] += 1
        return []
    
    # 阶段3：结构化抽取
    findings = []
    structured_count = 0
    for sent_text, finding_type, confidence in confirmed_sentences:
        structured_finding = extract_structured_finding_from_sentence(sent_text, doc, finding_type)
        
        if structured_finding and structured_finding.discovery_object:
            structured_finding.confidence = confidence
            structured_count += 1
            # 阶段5：规范化
            normalized_text = normalize_finding_to_string(structured_finding)
            if normalized_text:
                findings.append((normalized_text, structured_finding))
    
    if structured_count == 0:
        _finding_extract_debug_count['stage3_empty'] += 1
        if has_abstract:
            _finding_extract_debug_count_by_abstract['stage3_empty_with_abstract'] += 1
        else:
            _finding_extract_debug_count_by_abstract['stage3_empty_without_abstract'] += 1
    elif not findings:
        _finding_extract_debug_count['stage5_empty'] += 1
        if has_abstract:
            _finding_extract_debug_count_by_abstract['stage5_empty_with_abstract'] += 1
        else:
            _finding_extract_debug_count_by_abstract['stage5_empty_without_abstract'] += 1
    
    return findings

def detect_opinion_conflicts(opinion_index, emb_model, cache, conflict_threshold=0.85):
    """检测观点冲突：识别同一对象上的对立观点
    
    Args:
        opinion_index: 观点索引对象
        emb_model: 嵌入模型
        cache: 嵌入缓存
        conflict_threshold: 判断内容相似度阈值（超过此值且极性相反视为冲突）
    
    Returns:
        conflict_pairs: List[Tuple[int, int]] 冲突观点ID对列表
    """
    conflict_pairs = []
    
    # 收集所有观点的对象和元数据
    opinion_objects = {}  # object -> List[(opinion_id, meta, embedding)]
    
    # 从索引中获取所有观点
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
                    # 从opinion_text中提取对象（使用抽象化方法）
                    # 尝试从规范化后的文本中提取核心对象
                    words = opinion_text.split()
                    if len(words) >= 2:
                        # 取前两个词作为候选对象（通常是"对象 判断"格式）
                        candidate_obj = " ".join(words[:2])
                        obj_key = abstract_object_phrase(candidate_obj)
                    else:
                        obj_key = abstract_object_phrase(words[0] if words else str(cid))
                    
                    if obj_key not in opinion_objects:
                        opinion_objects[obj_key] = []
                    
                    if opinion_index.raw_store:
                        vec = opinion_index.raw_store.get(cid)
                        if vec is None:
                            # 重新编码
                            vec = encode_with_cache([opinion_text], emb_model, cache)[0]
                    else:
                        vec = encode_with_cache([opinion_text], emb_model, cache)[0]
                    
                    opinion_objects[obj_key].append((cid, meta, vec))
    else:
        for cid, meta in opinion_index.meta.items():
            if meta and 'opinion_text' in meta:
                opinion_text = meta.get('opinion_text', '')
                # 使用抽象化方法提取对象
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
    
    # 对每个对象的观点进行冲突检测（优化：限制比较范围）
    max_opinions_per_object = 100  # 如果某个对象观点太多，只比较前100个
    for obj_key, opinions in opinion_objects.items():
        if len(opinions) < 2:
            continue
        
        # 如果观点太多，只取前N个进行比较（避免性能问题）
        if len(opinions) > max_opinions_per_object:
            opinions = opinions[:max_opinions_per_object]
        
        # 两两比较
        for i in range(len(opinions)):
            for j in range(i + 1, len(opinions)):
                cid1, meta1, vec1 = opinions[i]
                cid2, meta2, vec2 = opinions[j]
                
                # 计算相似度
                similarity = float(np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2) + 1e-12))
                
                polarity1 = _extract_polarity_from_meta(meta1)
                polarity2 = _extract_polarity_from_meta(meta2)
                
                # 如果相似度高且极性相反，视为冲突
                if similarity >= conflict_threshold:
                    if (polarity1 == "positive" and polarity2 == "negative") or \
                       (polarity1 == "negative" and polarity2 == "positive"):
                        conflict_pairs.append((cid1, cid2))
                        
                        # 更新元数据中的opposed_to字段
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

def _extract_polarity_from_meta(meta):
    """从元数据中提取极性"""
    if 'polarity' in meta:
        return meta['polarity']
    
    # 从opinion_text中推断
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

def select_top_opinions_from_embeddings(candidates, embeddings):
    """选择有效观点：通过聚类去重，保留所有有效观点（不限制数量）
    
    优化：使用FAISS近似最近邻替代O(n²)全量相似度矩阵，复杂度从O(n²)降为O(n log n)
    """
    valid_indices = [i for i, c in enumerate(candidates) if not is_generic_phrase(c)]
    if not valid_indices:
        return []
    
    valid_candidates = [candidates[i] for i in valid_indices]
    valid_embeddings = embeddings[valid_indices]
    n = len(valid_candidates)
    
    if n == 1:
        return [(valid_candidates[0], valid_embeddings[0])]

    # 小规模数据（<100）仍使用精确方法，避免FAISS开销
    if n < 100:
        return _cluster_exact(valid_candidates, valid_embeddings, n)
    
    # 大规模数据使用FAISS近似最近邻 + Union-Find聚类
    return _cluster_approximate(valid_candidates, valid_embeddings, n)

def _cluster_exact(candidates, embeddings, n):
    """精确聚类方法（适用于小规模数据）
    
    支持自适应阈值：基于数据分布自动确定聚类阈值
    """
    sim_mat = embeddings @ embeddings.T
    visited = np.zeros(n, dtype=bool)
    clusters = []
    
    # 自适应阈值计算（分位数法）
    if n >= 10:
        # 收集所有最近邻相似度（每行的最大非对角线元素）
        nearest_similarities = []
        for i in range(n):
            row_sims = sim_mat[i]
            # 排除自己（对角线元素）
            non_diag_sims = np.delete(row_sims, i)
            if len(non_diag_sims) > 0:
                max_sim = np.max(non_diag_sims)
                if max_sim > 0:
                    nearest_similarities.append(max_sim)
        
        if len(nearest_similarities) >= 5:
            # 计算分位数作为自适应阈值
            adaptive_threshold = np.percentile(nearest_similarities, ADAPTIVE_THRESHOLD_PERCENTILE)
            # 限制在合理范围内
            cluster_threshold = max(ADAPTIVE_THRESHOLD_MIN, 
                                   min(ADAPTIVE_THRESHOLD_MAX, adaptive_threshold))
        else:
            # 样本不足，使用最小阈值
            cluster_threshold = ADAPTIVE_THRESHOLD_MIN
    else:
        # 数据量太小，使用最小阈值
        cluster_threshold = ADAPTIVE_THRESHOLD_MIN
    
    for i in range(n):
        if visited[i]:
            continue
        members = np.where(sim_mat[i] > cluster_threshold)[0]
        visited[members] = True
        clusters.append(members.tolist())

    return _select_representatives(candidates, embeddings, clusters)

def _cluster_approximate(candidates, embeddings, n):
    """近似聚类方法（使用FAISS，适用于大规模数据）
    
    支持自适应阈值：基于数据分布自动确定聚类阈值
    """
    # 归一化向量（FAISS内积搜索需要）
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normalized_embeddings = embeddings / (norms + 1e-12)
    
    # 构建临时FAISS索引（使用Flat索引，快速构建）
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(normalized_embeddings.astype('float32'))
    
    # Union-Find数据结构用于聚类
    parent = list(range(n))
    
    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    
    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py
    
    # 对每个向量搜索相似邻居（k=min(50, n-1)避免过度搜索）
    k = min(50, n - 1)
    if k > 0:
        similarities, indices = index.search(normalized_embeddings.astype('float32'), k + 1)
        
        # 自适应阈值计算（分位数法）
        if n >= 10:
            # 收集所有最近邻相似度（跳过自己，取第一个最近邻）
            nearest_similarities = []
            for i in range(n):
                if len(indices[i]) > 1:  # 确保有最近邻
                    nearest_sim = similarities[i][1]  # 第一个最近邻（跳过自己）
                    if nearest_sim > 0:  # 过滤无效值
                        nearest_similarities.append(nearest_sim)
            
            if len(nearest_similarities) >= 5:  # 至少5个样本才计算分位数
                # 计算分位数作为自适应阈值
                adaptive_threshold = np.percentile(nearest_similarities, ADAPTIVE_THRESHOLD_PERCENTILE)
                # 限制在合理范围内
                cluster_threshold = max(ADAPTIVE_THRESHOLD_MIN, 
                                       min(ADAPTIVE_THRESHOLD_MAX, adaptive_threshold))
            else:
                # 样本不足，使用最小阈值
                cluster_threshold = ADAPTIVE_THRESHOLD_MIN
        else:
            # 数据量太小，使用最小阈值
            cluster_threshold = ADAPTIVE_THRESHOLD_MIN
        
        # 使用计算得到的阈值进行聚类
        for i in range(n):
            for j_idx, sim in zip(indices[i][1:], similarities[i][1:]):  # 跳过自己
                # 内积值（归一化后）>= 阈值 表示相似度足够高
                if sim >= cluster_threshold:
                    union(i, j_idx)
    # 如果 k == 0（n == 1），不需要聚类，直接进入结果收集
    
    # 收集聚类结果
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
    
    # 优化中心性计算：使用采样近似（当代表数量>100时）
    if len(representatives) > 100:
        # 采样计算中心性：随机选择50个代表计算中心性
        sample_size = min(50, len(representatives))
        sample_indices = np.random.choice(len(representatives), sample_size, replace=False)
        sample_embs = np.stack([rep_embs[i] for i in sample_indices])
        rep_embs_stack = np.stack(rep_embs)
        
        # 计算采样代表之间的相似度
        R_sample = sample_embs @ sample_embs.T
        centrality_sample = R_sample.sum(axis=1) / (sample_size - 1)
        
        # 计算所有代表与采样代表的平均相似度作为中心性近似
        R_all = rep_embs_stack @ sample_embs.T
        centrality = R_all.mean(axis=1)
    else:
        # 小规模：精确计算
        rep_embs_stack = np.stack(rep_embs)
        R = rep_embs_stack @ rep_embs_stack.T
    centrality = (R.sum(axis=1) - 1.0) / (len(representatives) - 1)
    
    sorted_idx = np.argsort(-centrality)
    return [(representatives[i], rep_embs[i]) for i in sorted_idx]

def calculate_opinion_importance_score(phrase: str, structured_opinion: Optional[StructuredOpinion] = None) -> float:
    """计算观点重要性分数（用于非创新观点的选择）"""
    score = 0.0
    
    # 1. 观点性动词强度（40%权重）
    if structured_opinion and structured_opinion.predicate:
        predicate_lower = structured_opinion.predicate.lower()
        if any(verb in predicate_lower for verb in OPINION_VERBS_STRONG):
            score += 0.4
        elif any(verb in predicate_lower for verb in OPINION_VERBS_MEDIUM):
            score += 0.25
        elif any(verb in predicate_lower for verb in OPINION_VERBS_WEAK):
            score += 0.1
    
    # 2. 观点长度（20%权重）- 适中长度更优
    phrase_len = len(phrase)
    if 15 <= phrase_len <= 80:
        score += 0.2
    elif 10 <= phrase_len < 15 or 80 < phrase_len <= 120:
        score += 0.1
    
    # 3. 包含创新关键词（20%权重）
    innovation_keywords = ['novel', 'first', 'pioneering', 'breakthrough', 
                          'groundbreaking', 'innovative', 'original', 'state-of-the-art']
    phrase_lower = phrase.lower()
    if any(keyword in phrase_lower for keyword in innovation_keywords):
        score += 0.2
    
    # 4. 包含具体技术术语（20%权重）- 简单启发式：包含大写字母或数字
    if any(c.isupper() or c.isdigit() for c in phrase):
        score += 0.1
    # 包含多个单词（避免过短）
    word_count = len(phrase.split())
    if word_count >= 3:
        score += 0.1
    
    return min(score, 1.0)

class YearlyDatabaseWriter:
    def __init__(self, db_path: str, buffer_size: int = DB_WRITE_BATCH_SIZE):
        """初始化数据库写入器
        
        Args:
            db_path: SQLite数据库路径
            buffer_size: 批量写入缓冲区大小
        """
        self.db_path = db_path
        self.buffer_size = buffer_size
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        
        # SQLite性能优化PRAGMA（参考词库统计6）
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")  # 比OFF更安全，性能仍好
        self.conn.execute("PRAGMA cache_size = -2000000")  # 2GB缓存
        self.conn.execute("PRAGMA mmap_size = 30000000000")  # 30GB mmap
        self.conn.execute("PRAGMA temp_store = MEMORY")
        
        # 创建观点提及表
        # 主键改为 (opinion_id, paper_id)，确保同一论文中同一观点只记录一次
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
        
        # 如果表已存在但没有is_core_opinion字段，则添加该字段
        try:
            self.conn.execute("ALTER TABLE opinion_mentions ADD COLUMN is_core_opinion INTEGER DEFAULT 0")
            self.conn.commit()
        except sqlite3.OperationalError:
            # 字段已存在，忽略错误
            pass
        
        # 创建索引（优化查询性能）
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_opinion_mentions_year ON opinion_mentions(year)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_opinion_mentions_opinion_id ON opinion_mentions(opinion_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_opinion_mentions_paper_id ON opinion_mentions(paper_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_opinion_mentions_first_seen_year ON opinion_mentions(first_seen_year)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_opinion_mentions_is_core ON opinion_mentions(is_core_opinion)")
        
        self.conn.commit()
        
        # 批量写入缓冲区
        self.buffer = []
        self.executemany_chunk_size = 20000  # 分块大小，避免WAL变慢
    
    def write_batch(self, df: pd.DataFrame):
        """批量写入数据到缓冲区
        
        Args:
            df: 包含mention记录的DataFrame
        """
        if df.empty:
            return
        
        # 转换为元组列表（处理None值）
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
        
        # 达到缓冲区大小时触发写入
        if len(self.buffer) >= self.buffer_size:
            self._flush()
    
    def _flush(self):
        """将缓冲区数据写入数据库"""
        if not self.buffer:
            return
        
        # 使用ON CONFLICT DO NOTHING避免重复插入（PRIMARY KEY约束）
        # 主键为 (opinion_id, paper_id)，确保同一论文中同一观点只记录一次
        # 参考词库统计6的批量写入方式
        sql = """
            INSERT INTO opinion_mentions 
            (opinion_id, opinion_text, canonical_label, first_seen_year, alias, paper_id, year, is_core_opinion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(opinion_id, paper_id) DO NOTHING
        """
        
        # 分块executemany，避免WAL变慢（参考词库统计6）
        try:
            self.conn.execute('BEGIN TRANSACTION')
            for i in range(0, len(self.buffer), self.executemany_chunk_size):
                chunk = self.buffer[i:i + self.executemany_chunk_size]
                self.conn.executemany(sql, chunk)
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise
        finally:
            self.buffer.clear()
    
    def flush(self):
        """强制刷新缓冲区"""
        self._flush()
    
    def close(self):
        """关闭数据库连接"""
        self.flush()
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()
    
    def get_stats(self):
        """获取统计信息"""
        if not hasattr(self, 'conn') or not self.conn:
            return {}
        try:
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
        except Exception as e:
            print(f"Warning: Failed to get database stats: {e}")
            return {}

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

def save_filtered_papers_to_csv():
    """保存被过滤论文的详细信息到CSV文件，用于误过滤检查"""
    global _filtered_paper_details
    
    if not any(_filtered_paper_details.values()):
        return
    
    filtered_csv_path = OUTPUT_DIR / "filtered_papers_details.csv"
    
    # 准备数据
    all_filtered = []
    for stage, details_list in _filtered_paper_details.items():
        for detail in details_list:
            if stage == 'stage2_empty':
                if len(detail) == 6:
                    paper_id, title, abstract, max_confidence, reason, core_findings = detail
                else:
                    # 兼容旧格式（没有core_findings）
                    paper_id, title, abstract, max_confidence, reason = detail
                    core_findings = ''
                all_filtered.append({
                    'paper_id': paper_id,
                    'title': title,
                    'abstract': abstract[:500] if abstract else '',  # 限制摘要长度
                    'filter_stage': stage,
                    'max_confidence': max_confidence,
                    'filter_reason': reason,
                    'core_findings': core_findings
                })
            else:  # stage3_empty or stage5_empty
                if len(detail) == 5:
                    paper_id, title, abstract, reason, core_findings = detail
                else:
                    # 兼容旧格式（没有core_findings）
                    paper_id, title, abstract, reason = detail
                    core_findings = ''
                all_filtered.append({
                    'paper_id': paper_id,
                    'title': title,
                    'abstract': abstract[:500] if abstract else '',
                    'filter_stage': stage,
                    'max_confidence': None,
                    'filter_reason': reason,
                    'core_findings': core_findings
                })
    
    if not all_filtered:
        return
    
    # 保存到CSV（追加模式）
    df = pd.DataFrame(all_filtered)
    file_exists = filtered_csv_path.exists()
    
    # 如果文件已存在，检查是否需要更新表头（添加 core_findings 列）
    if file_exists:
        try:
            existing_df = pd.read_csv(filtered_csv_path, encoding='utf-8-sig', nrows=0)  # 只读表头
            if 'core_findings' not in existing_df.columns:
                # 需要更新表头：读取所有数据，添加缺失的列，重新保存
                existing_df = pd.read_csv(filtered_csv_path, encoding='utf-8-sig')
                if 'core_findings' not in existing_df.columns:
                    existing_df['core_findings'] = ''
                # 重新保存完整数据（包含新数据）
                combined_df = pd.concat([existing_df, df], ignore_index=True)
                combined_df.to_csv(filtered_csv_path, index=False, encoding='utf-8-sig')
                print(f"📝 已更新表头并保存了 {len(all_filtered)} 条新记录（共 {len(combined_df)} 条）")
            else:
                # 表头已包含 core_findings，直接追加
                df.to_csv(filtered_csv_path, mode='a', header=False, index=False, encoding='utf-8-sig')
                print(f"📝 本次微批次保存了 {len(all_filtered)} 条被过滤论文记录")
        except Exception as e:
            # 如果读取失败，直接追加（兼容旧格式）
            df.to_csv(filtered_csv_path, mode='a', header=False, index=False, encoding='utf-8-sig')
            print(f"📝 本次微批次保存了 {len(all_filtered)} 条被过滤论文记录（警告：读取现有文件时出错: {e}）")
    else:
        # 文件不存在，创建新文件
        df.to_csv(filtered_csv_path, mode='w', header=True, index=False, encoding='utf-8-sig')
        print(f"\n📝 已创建被过滤论文详情文件: {filtered_csv_path}")
        print(f"📝 本次微批次保存了 {len(all_filtered)} 条被过滤论文记录")

def save_successful_papers_sample():
    """保存成功提取观点的论文样本到CSV文件（用于质量检查）"""
    global _successful_paper_details
    
    if not _successful_paper_details:
        return
    
    # 计算采样数量
    total_successful = len(_successful_paper_details)
    sample_count = max(
        SUCCESS_SAMPLE_MIN,
        min(
            SUCCESS_SAMPLE_MAX,
            int(total_successful * SUCCESS_SAMPLE_RATE)
        )
    )
    
    # 随机采样
    import random
    if total_successful > sample_count:
        sampled = random.sample(_successful_paper_details, sample_count)
    else:
        sampled = _successful_paper_details
    
    # 准备数据
    all_successful = []
    for detail in sampled:
        paper_id, title, abstract, opinions_list, year = detail
        # 将观点列表转换为字符串（用分号分隔）
        opinions_str = '; '.join(opinions_list) if opinions_list else ''
        all_successful.append({
            'paper_id': paper_id,
            'title': title,
            'abstract': abstract[:500] if abstract else '',  # 限制摘要长度
            'opinions': opinions_str[:1000] if opinions_str else '',  # 限制观点长度
            'opinion_count': len(opinions_list),
            'year': year if year is not None else ''
        })
    
    if not all_successful:
        return
    
    # 保存到CSV（追加模式）
    successful_csv_path = OUTPUT_DIR / "successful_papers_sample.csv"
    df = pd.DataFrame(all_successful)
    file_exists = successful_csv_path.exists()
    
    if file_exists:
        # 追加模式
        df.to_csv(successful_csv_path, mode='a', header=False, index=False, encoding='utf-8-sig')
        print(f"📝 本次微批次保存了 {len(all_successful)} 条成功案例样本（共采样 {sample_count}/{total_successful} 篇）")
    else:
        # 创建新文件
        df.to_csv(successful_csv_path, mode='w', header=True, index=False, encoding='utf-8-sig')
        print(f"\n📝 已创建成功案例样本文件: {successful_csv_path}")
        print(f"📝 本次微批次保存了 {len(all_successful)} 条成功案例样本（共采样 {sample_count}/{total_successful} 篇）")
    
    # 清空当前批次的成功案例（避免重复）
    _successful_paper_details.clear()

def check_filtered_papers(filtered_csv_path=None, stage=None, min_confidence=None, limit=50):
    """检查被过滤的论文，判断是否是误过滤
    
    Args:
        filtered_csv_path: CSV文件路径，默认为output目录下的filtered_papers_details.csv
        stage: 过滤阶段筛选（'stage2_empty', 'stage3_empty', 'stage5_empty'），None表示全部
        min_confidence: 最小置信度筛选（仅对stage2_empty有效），None表示不筛选
        limit: 显示数量限制
    
    Returns:
        DataFrame: 被过滤论文的详细信息
    """
    if filtered_csv_path is None:
        filtered_csv_path = OUTPUT_DIR / "filtered_papers_details.csv"
    
    if not Path(filtered_csv_path).exists():
        print(f"❌ 未找到被过滤论文文件: {filtered_csv_path}")
        return None
    
    df = pd.read_csv(filtered_csv_path, encoding='utf-8-sig')
    
    # 筛选
    if stage:
        df = df[df['filter_stage'] == stage]
    
    if min_confidence is not None and 'max_confidence' in df.columns:
        df = df[df['max_confidence'] >= min_confidence]
    
    # 限制数量
    if len(df) > limit:
        df = df.head(limit)
        print(f"⚠️  仅显示前 {limit} 条记录，共 {len(pd.read_csv(filtered_csv_path, encoding='utf-8-sig'))} 条")
    
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
    global _stage2_verification_stats, _stage3_extraction_stats, _stage5_normalization_stats, _extract_debug_count_by_abstract, _filtered_paper_ids, _filtered_paper_details, _successful_paper_details
    if USE_HASH_DEDUP:
        reset_microbatch_hash_set()
    
    # 重置统计信息（每个微批次独立统计）
    _filtered_paper_ids = {
        'stage1_empty': [],
        'stage2_empty': [],
        'stage3_empty': [],
        'stage5_empty': [],
    }
    _filtered_paper_details = {
        'stage2_empty': [],
        'stage3_empty': [],
        'stage5_empty': [],
    }
    _successful_paper_details = []  # 重置成功案例列表
    _stage2_verification_stats = {
        'total_verified': 0,
        'failed_verb': 0,
        'failed_structure': 0,
        'failed_assertion': 0,
        'passed': 0,
        'samples': [],
        'passed_samples': [],
        'false_negative_count': 0,
        'true_negative_count': 0,
        'false_positive_count': 0,
        'true_positive_count': 0,
        'uncertain_count': 0
    }
    _stage3_extraction_stats = {
        'total_sentences': 0,
        'template_matched': 0,
        'dependency_matched': 0,
        'extraction_failed': 0,
        'field_missing': 0,
        'failed_samples': []
    }
    _stage5_normalization_stats = {
        'total_structured': 0,
        'normalized_success': 0,
        'normalized_failed': 0,
        'failed_reasons': {
            'missing_object': 0,
            'missing_predicate': 0,
            'normalize_text_empty': 0
        },
        'failed_samples': []
    }
    
    # 预处理文本
    texts = []
    for r in rows:
        title = getattr(r, 'title', '') or ''
        abstract = getattr(r, 'abstract', '') or ''
        # 使用分隔符区分标题和摘要
        if title and abstract:
            combined = f"{title}\n\n[ABSTRACT]\n\n{abstract}".strip()
        else:
            combined = f"{title}{abstract}".strip()
        # 截断过长文本
        if len(combined) > 8192:
            combined = combined[:8192]
        texts.append(combined)

    # spaCy处理
    docs = list(nlp.pipe(texts, batch_size=SPACY_BATCH_SIZE, n_process=SPACY_N_PROCESS))

    # 生成候选：使用真正的观点识别替代概念提取
    all_candidates = []
    all_structured_opinions = []  # 保存结构化观点信息
    
    # 🆕 详细阶段统计
    stage_stats = {
        'total_papers': len(rows),
        'empty_abstract_count': 0,  # 摘要为空的论文数
        'stage0_papers': len(rows),  # 初始论文数
        'stage1_papers': 0,  # 阶段1后有候选的论文数
        'stage2_papers': 0,  # 阶段2后有确认观点的论文数
        'stage3_papers': 0,  # 阶段3后有结构化观点的论文数
        'stage5_papers': 0,  # 阶段5后有规范化观点的论文数
    }
    
    # 统计摘要为空的论文
    for row in rows:
        abstract = getattr(row, 'abstract', '') or ''
        if not abstract.strip():
            stage_stats['empty_abstract_count'] += 1
    
    # 调试统计（保留原有）
    debug_stats = {
        'total_papers': len(rows),
        'papers_with_sentences': 0,
        'papers_with_candidates': 0,
        'papers_with_confirmed': 0,
        'papers_with_structured': 0,
        'papers_with_normalized': 0,
        'total_candidates': 0,
        'total_confirmed': 0,
        'total_structured': 0,
        'total_normalized': 0
    }
    
    for row, doc in zip(rows, docs):
        # 检查文档是否有句子
        doc_sents = list(doc.sents)
        if doc_sents:
            debug_stats['papers_with_sentences'] += 1
        
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
        
        # 使用观点识别提取观点
        opinions = extract_opinions_from_document(
            doc, emb_model, cache, 
            has_abstract=has_abstract, 
            paper_id=paper_id,
            paper_title=title,
            paper_abstract=abstract,
            nlp_model=nlp
        )
        
        # 提取规范化后的观点字符串作为候选
        candidates = []
        structured_ops = []
        for normalized_text, structured_opinion in opinions:
            if normalized_text and normalized_text not in candidates:
                candidates.append(normalized_text)
                structured_ops.append((normalized_text, structured_opinion))  # 存储元组而非仅对象
        
        if candidates:
            debug_stats['papers_with_normalized'] += 1
            debug_stats['total_normalized'] += len(candidates)
            
            # 收集成功案例（用于保存样本）
            year = getattr(row, 'year', None)
            if year is not None and pd.notna(year):
                year = int(year)
            else:
                year = None
            _successful_paper_details.append((
                paper_id,
                title,
                abstract,
                candidates,  # 观点列表
                year
            ))
        
        # 限制候选数量
        if len(candidates) > N_TOP_CANDIDATES:
            candidates = candidates[:N_TOP_CANDIDATES]
            structured_ops = structured_ops[:N_TOP_CANDIDATES]
        
        all_candidates.append(candidates)
        all_structured_opinions.append(structured_ops)
    
    # 🆕 统计各阶段有观点的论文数（通过检查extract_opinions返回结果）
    stage_stats['stage5_papers'] = sum(1 for cands in all_candidates if cands)
    
    # 🆕 从_extract_debug_count获取各阶段统计（区分有摘要/无摘要）
    # 注意：_extract_debug_count是全局变量，在extract_opinions_from_document中更新
    # 我们需要在extract_opinions_from_document中区分有摘要/无摘要，但这样改动太大
    # 暂时先统计总体，后续可以优化
    
    # 🆕 简化的输出（仅关键统计）
    if debug_stats['total_papers'] > 0:
        print(f"\n{'='*80}")
        print(f"📊 微批次统计")
        print(f"{'='*80}")
        print(f"📄 初始状态:")
        print(f"   - 总论文数: {debug_stats['total_papers']}")
        print(f"   - 摘要为空的论文数: {stage_stats['empty_abstract_count']} ({stage_stats['empty_abstract_count']/debug_stats['total_papers']*100:.1f}%)")
        print(f"   - 有摘要的论文数: {debug_stats['total_papers'] - stage_stats['empty_abstract_count']} ({(debug_stats['total_papers'] - stage_stats['empty_abstract_count'])/debug_stats['total_papers']*100:.1f}%)")
        # 删除所有冗余的测试代码输出（已全部删除）
        
        # 计算各阶段剩余的论文数
        total = _extract_debug_count['total']
        # 阶段1和阶段2已合并为统一检测器，stage1_empty不再有意义
        stage2_remaining = total - _extract_debug_count['stage2_empty']
        stage3_remaining = stage2_remaining - _extract_debug_count['stage3_empty']
        stage5_remaining = stage3_remaining - _extract_debug_count['stage5_empty']
        
        print(f"\n📈 各阶段论文数变化（8阶段系统）:")
        print(f"   - 阶段0（文本预处理）: {total} 篇论文")
        # 阶段1-2：创新实体识别 + 动词类型分类
        stage1_2_remaining = total - _extract_debug_count['stage2_empty']
        print(f"   - 阶段1-2（创新实体+动词分类）后: {stage1_2_remaining} 篇通过检测 | 过滤 {_extract_debug_count['stage2_empty']} 篇 ({_extract_debug_count['stage2_empty']/total*100:.1f}%)")
        # 阶段3-5：标题对齐+结构理解+深层依存抽取
        stage3_5_remaining = stage1_2_remaining - _extract_debug_count['stage3_empty']
        print(f"   - 阶段3-5（标题对齐+结构理解+依存抽取）后: {stage3_5_remaining} 篇完成结构化 | 再过滤 {_extract_debug_count['stage3_empty']} 篇 ({_extract_debug_count['stage3_empty']/total*100:.1f}%)")
        # 阶段6-8：跨句融合+评分排序+语言重构
        stage6_8_remaining = stage3_5_remaining - _extract_debug_count['stage5_empty']
        print(f"   - 阶段6-8（跨句融合+评分排序+语言重构）后: {stage6_8_remaining} 篇最终有观点 | 再过滤 {_extract_debug_count['stage5_empty']} 篇 ({_extract_debug_count['stage5_empty']/total*100:.1f}%)")
        print(f"   - 最终保留率: {stage6_8_remaining/total*100:.1f}%")
        
        # 🆕 区分有摘要/无摘要的详细统计
        print(f"\n📊 各阶段过滤情况（区分有摘要/无摘要）:")
        total_with_abstract = _extract_debug_count_by_abstract['total_with_abstract']
        total_without_abstract = _extract_debug_count_by_abstract['total_without_abstract']
        
        if total_with_abstract > 0 or total_without_abstract > 0:
            print(f"   - 初始状态:")
            print(f"     * 有摘要的论文数: {total_with_abstract}")
            print(f"     * 无摘要的论文数: {total_without_abstract}")
            
            # 阶段1+2统计（已合并）
            stage2_empty_with_abstract = _extract_debug_count_by_abstract['stage2_empty_with_abstract']
            stage2_empty_without_abstract = _extract_debug_count_by_abstract['stage2_empty_without_abstract']
            stage2_remaining_with_abstract = total_with_abstract - stage2_empty_with_abstract
            stage2_remaining_without_abstract = total_without_abstract - stage2_empty_without_abstract
            print(f"   - 阶段1-2（创新实体+动词分类）后:")
            print(f"     * 有摘要: 剩余 {stage2_remaining_with_abstract} 篇 | 过滤 {stage2_empty_with_abstract} 篇 ({stage2_empty_with_abstract/total_with_abstract*100:.1f}%)" if total_with_abstract > 0 else "     * 有摘要: 0 篇")
            print(f"     * 无摘要: 剩余 {stage2_remaining_without_abstract} 篇 | 过滤 {stage2_empty_without_abstract} 篇 ({stage2_empty_without_abstract/total_without_abstract*100:.1f}%)" if total_without_abstract > 0 else "     * 无摘要: 0 篇")
            if _filtered_paper_ids['stage2_empty']:
                print(f"     * 被过滤的论文ID: {_filtered_paper_ids['stage2_empty']}")
            
            # 阶段3统计
            stage3_empty_with_abstract = _extract_debug_count_by_abstract['stage3_empty_with_abstract']
            stage3_empty_without_abstract = _extract_debug_count_by_abstract['stage3_empty_without_abstract']
            stage3_remaining_with_abstract = stage2_remaining_with_abstract - stage3_empty_with_abstract
            stage3_remaining_without_abstract = stage2_remaining_without_abstract - stage3_empty_without_abstract
            print(f"   - 阶段3-5（标题对齐+结构理解+依存抽取）后:")
            print(f"     * 有摘要: 剩余 {stage3_remaining_with_abstract} 篇 | 再过滤 {stage3_empty_with_abstract} 篇 ({stage3_empty_with_abstract/stage2_remaining_with_abstract*100:.1f}%)" if stage2_remaining_with_abstract > 0 else "     * 有摘要: 0 篇")
            print(f"     * 无摘要: 剩余 {stage3_remaining_without_abstract} 篇 | 再过滤 {stage3_empty_without_abstract} 篇 ({stage3_empty_without_abstract/stage2_remaining_without_abstract*100:.1f}%)" if stage2_remaining_without_abstract > 0 else "     * 无摘要: 0 篇")
            if _filtered_paper_ids['stage3_empty']:
                print(f"     * 被过滤的论文ID: {_filtered_paper_ids['stage3_empty']}")
            
            # 阶段5统计
            stage5_empty_with_abstract = _extract_debug_count_by_abstract['stage5_empty_with_abstract']
            stage5_empty_without_abstract = _extract_debug_count_by_abstract['stage5_empty_without_abstract']
            stage5_remaining_with_abstract = stage3_remaining_with_abstract - stage5_empty_with_abstract
            stage5_remaining_without_abstract = stage3_remaining_without_abstract - stage5_empty_without_abstract
            print(f"   - 阶段6-8（跨句融合+评分排序+语言重构）后:")
            print(f"     * 有摘要: 剩余 {stage5_remaining_with_abstract} 篇 | 再过滤 {stage5_empty_with_abstract} 篇 ({stage5_empty_with_abstract/stage3_remaining_with_abstract*100:.1f}%)" if stage3_remaining_with_abstract > 0 else "     * 有摘要: 0 篇")
            print(f"     * 无摘要: 剩余 {stage5_remaining_without_abstract} 篇 | 再过滤 {stage5_empty_without_abstract} 篇 ({stage5_empty_without_abstract/stage3_remaining_without_abstract*100:.1f}%)" if stage3_remaining_without_abstract > 0 else "     * 无摘要: 0 篇")
            if _filtered_paper_ids['stage5_empty']:
                print(f"     * 被过滤的论文ID: {_filtered_paper_ids['stage5_empty']}")
            
            # 最终保留率
            print(f"   - 最终保留率:")
            print(f"     * 有摘要: {stage5_remaining_with_abstract/total_with_abstract*100:.1f}%" if total_with_abstract > 0 else "     * 有摘要: N/A")
            print(f"     * 无摘要: {stage5_remaining_without_abstract/total_without_abstract*100:.1f}%" if total_without_abstract > 0 else "     * 无摘要: N/A")
        
        # 🆕 核心发现统计信息
        finding_total = _finding_extract_debug_count.get('total', 0)
        if finding_total > 0:
            print(f"\n🔍 核心发现提取统计:")
            print(f"   - 尝试提取核心发现的论文数: {finding_total}")
            finding_stage1_empty = _finding_extract_debug_count.get('stage1_empty', 0)
            finding_stage2_empty = _finding_extract_debug_count.get('stage2_empty', 0)
            finding_stage3_empty = _finding_extract_debug_count.get('stage3_empty', 0)
            finding_stage5_empty = _finding_extract_debug_count.get('stage5_empty', 0)
            
            # 计算各阶段剩余数量（注意：阶段2的输入是阶段1的输出）
            finding_stage1_remaining = finding_total - finding_stage1_empty
            finding_stage2_remaining = finding_stage1_remaining - finding_stage2_empty if finding_stage1_remaining > 0 else 0
            finding_stage3_remaining = finding_stage2_remaining - finding_stage3_empty if finding_stage2_remaining > 0 else 0
            finding_stage5_remaining = finding_stage3_remaining - finding_stage5_empty if finding_stage3_remaining > 0 else 0
            
            print(f"   - 阶段1（检测）后: {finding_stage1_remaining} 篇有候选句子 | 过滤 {finding_stage1_empty} 篇")
            if finding_stage1_remaining > 0:
                print(f"   - 阶段2（筛选）后: {finding_stage2_remaining} 篇通过筛选 | 再过滤 {finding_stage2_empty} 篇")
                if finding_stage2_remaining > 0:
                    print(f"   - 阶段3（结构化）后: {finding_stage3_remaining} 篇完成结构化 | 再过滤 {finding_stage3_empty} 篇")
                    if finding_stage3_remaining > 0:
                        print(f"   - 阶段5（规范化）后: {finding_stage5_remaining} 篇最终有核心发现 | 再过滤 {finding_stage5_empty} 篇")
            if finding_total > 0:
                print(f"   - 核心发现提取成功率: {finding_stage5_remaining/finding_total*100:.1f}%")
            
            # 区分有摘要/无摘要的核心发现统计
            finding_total_with_abstract = _finding_extract_debug_count_by_abstract.get('total_with_abstract', 0)
            finding_total_without_abstract = _finding_extract_debug_count_by_abstract.get('total_without_abstract', 0)
            if finding_total_with_abstract > 0 or finding_total_without_abstract > 0:
                print(f"\n   📊 核心发现提取（区分有摘要/无摘要）:")
                print(f"     * 有摘要的论文数: {finding_total_with_abstract}")
                print(f"     * 无摘要的论文数: {finding_total_without_abstract}")
                
                # 计算有摘要/无摘要的核心发现提取成功数（按阶段链式计算）
                finding_stage1_with_abstract = finding_total_with_abstract - \
                    _finding_extract_debug_count_by_abstract.get('stage1_empty_with_abstract', 0)
                finding_stage2_with_abstract = finding_stage1_with_abstract - \
                    _finding_extract_debug_count_by_abstract.get('stage2_empty_with_abstract', 0) if finding_stage1_with_abstract > 0 else 0
                finding_stage3_with_abstract = finding_stage2_with_abstract - \
                    _finding_extract_debug_count_by_abstract.get('stage3_empty_with_abstract', 0) if finding_stage2_with_abstract > 0 else 0
                finding_stage5_with_abstract = finding_stage3_with_abstract - \
                    _finding_extract_debug_count_by_abstract.get('stage5_empty_with_abstract', 0) if finding_stage3_with_abstract > 0 else 0
                
                finding_stage1_without_abstract = finding_total_without_abstract - \
                    _finding_extract_debug_count_by_abstract.get('stage1_empty_without_abstract', 0)
                finding_stage2_without_abstract = finding_stage1_without_abstract - \
                    _finding_extract_debug_count_by_abstract.get('stage2_empty_without_abstract', 0) if finding_stage1_without_abstract > 0 else 0
                finding_stage3_without_abstract = finding_stage2_without_abstract - \
                    _finding_extract_debug_count_by_abstract.get('stage3_empty_without_abstract', 0) if finding_stage2_without_abstract > 0 else 0
                finding_stage5_without_abstract = finding_stage3_without_abstract - \
                    _finding_extract_debug_count_by_abstract.get('stage5_empty_without_abstract', 0) if finding_stage3_without_abstract > 0 else 0
                
                print(f"     * 有摘要: 成功提取 {finding_stage5_with_abstract} 篇 ({finding_stage5_with_abstract/finding_total_with_abstract*100:.1f}%)" if finding_total_with_abstract > 0 else "     * 有摘要: 0 篇")
                print(f"     * 无摘要: 成功提取 {finding_stage5_without_abstract} 篇 ({finding_stage5_without_abstract/finding_total_without_abstract*100:.1f}%)" if finding_total_without_abstract > 0 else "     * 无摘要: 0 篇")

    # 批量编码
    flat_candidates = [c for cs in all_candidates for c in cs]
    if flat_candidates:
        all_embeddings = encode_with_cache(flat_candidates, emb_model, cache)
    else:
        all_embeddings = np.zeros((0, cache.dim), dtype='float32')

    # 收集所有论文的top_opinions
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
    
    # 批量收集所有向量和阈值
    all_batch_vecs = []
    all_batch_thresholds = []
    
    for top_opinions in paper_opinions:
        if not top_opinions:
            continue
        for phrase, vec in top_opinions:
            all_batch_vecs.append(vec)
            all_batch_thresholds.append(adaptive_threshold(phrase))
    
    # 一次性批量搜索所有观点
    if all_batch_vecs:
        all_batch_vecs = np.stack(all_batch_vecs)
        batch_search_results = opinion_index.batch_search(all_batch_vecs, all_batch_thresholds)
    else:
        batch_search_results = []
    
    # 匹配回论文并处理（带论文内去重和相似度合并）
    mentions = []
    result_idx = 0
    
    for paper_idx, (row, top_opinions) in enumerate(zip(rows, paper_opinions)):
        if not top_opinions:
            continue
        
        year = getattr(row, 'year', None)
        paper_year = getattr(row, 'year', None)
        if paper_year is not None and pd.notna(paper_year):
            paper_year = int(paper_year)
        else:
            paper_year = None
        
        # 论文内去重：记录已使用的opinion_id和相似短语
        paper_used_opinion_ids = set()
        paper_phrase_vectors = {}  # 用于相似度检查
        paper_opinion_list = []  # 收集该论文的所有观点信息
        
        # 获取该论文的结构化观点信息（用于重要性评分）
        structured_ops = all_structured_opinions[paper_idx] if paper_idx < len(all_structured_opinions) else []
        structured_ops_dict = {normalize_text_cached(op[0]): op[1] for op in structured_ops if op and len(op) >= 2}
        
        for phrase_idx, (phrase, vec) in enumerate(top_opinions):
            original_cid, sim = batch_search_results[result_idx]
            result_idx += 1
            
            # 论文内相似度检查：如果与已使用的短语高度相似，合并
            should_merge = False
            merge_target_cid = None
            for existing_cid, existing_vec in paper_phrase_vectors.items():
                similarity = float(np.dot(vec, existing_vec) / (np.linalg.norm(vec) * np.linalg.norm(existing_vec) + 1e-12))
                if similarity > 0.95:  # 高度相似阈值
                    should_merge = True
                    merge_target_cid = existing_cid
                    break
            
            is_new_opinion = (original_cid is None and not should_merge)
            
            if should_merge and merge_target_cid is not None:
                # 合并到已存在的观点
                cid = merge_target_cid
                meta_buffer.record_alias(cid, phrase)
            elif original_cid is None:
                # 新观点
                cid = opinion_index.add(phrase, vec, year, [phrase])
                paper_phrase_vectors[cid] = vec
            else:
                # 已存在的观点
                cid = original_cid
                meta_buffer.record_alias(cid, phrase)
                paper_phrase_vectors[cid] = vec
            
            # 记录年份和标签（新观点和已存在观点都需要）
            if year is not None:
                meta_buffer.record_year(cid, int(year))
            
            title = getattr(row, 'title', '') or ''
            if title:
                meta_buffer.record_label(cid, phrase, title)

            # 论文内去重：如果该opinion_id已在此论文中使用，跳过
            if cid in paper_used_opinion_ids:
                continue
            paper_used_opinion_ids.add(cid)

            # 获取meta（只获取一次）
            meta = opinion_index._get_meta(cid)
            if meta is None:
                print(f"Warning: meta not found for opinion_id {cid}, skipping mention")
                continue
            # 保持None值，不使用0表示缺失（0是有效年份值）
            first_seen_year = meta['first_seen_year']  # 保持None，数据库支持可空整型
            
            # 判断是否为年度创新
            is_annual_innovation = False
            if paper_year is not None:
                if is_new_opinion:
                    # 新观点，如果paper_year不为None，则肯定是年度创新
                    is_annual_innovation = True
                elif first_seen_year is not None and first_seen_year == paper_year:
                    # 已存在的观点，如果first_seen_year等于paper_year，说明在本年度首次出现
                    is_annual_innovation = True
            
            # 获取结构化观点信息（用于重要性评分）
            structured_opinion = structured_ops_dict.get(normalize_text_cached(phrase))
            
            # 收集观点信息
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
        
        # 为该论文选择核心观点
        annual_innovation_opinions = [op for op in paper_opinion_list if op['is_annual_innovation']]
        
        if annual_innovation_opinions:
            # 如果有年度创新观点，全部标记为核心观点
            for op in annual_innovation_opinions:
                op['is_core_opinion'] = True
            # 非年度创新观点标记为非核心
            for op in paper_opinion_list:
                if not op['is_annual_innovation']:
                    op['is_core_opinion'] = False
        else:
            # 如果没有年度创新观点，选择重要性最高的一个
            if paper_opinion_list:
                # 计算每个观点的重要性分数
                for op in paper_opinion_list:
                    op['importance_score'] = calculate_opinion_importance_score(
                        op['alias'], op.get('structured_opinion')
                    )
                # 选择分数最高的观点
                best_opinion = max(paper_opinion_list, key=lambda x: x.get('importance_score', 0.0))
                # 标记核心观点
                for op in paper_opinion_list:
                    op['is_core_opinion'] = (op['opinion_id'] == best_opinion['opinion_id'])
            else:
                # 如果没有观点，跳过
                continue
        
        # 添加到mentions列表
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
    
    # 保存被过滤论文的详细信息到CSV文件
    save_filtered_papers_to_csv()
    
    # 保存成功案例样本到CSV文件
    save_successful_papers_sample()
    
    return mentions

def process_streaming_csv():
    global _extract_debug_count
    
    # 年份顺序确认
    print("\n" + "="*60)
    print("⚠️  重要提示：核心观点选择功能")
    print("="*60)
    print("本程序将根据观点的首次出现年份判断年度创新观点。")
    print("为确保判断准确性，请确认输入CSV文件已按年份从早到晚排序。")
    print("="*60)
    user_input = input("请确认CSV文件已按年份排序（输入 'yes' 继续，其他任意键退出）: ").strip().lower()
    if user_input != 'yes':
        print("程序已退出。请先对CSV文件按年份排序后再运行。")
        return
    print("✅ 已确认，开始处理...\n")
    
    # 优先使用GPU，只有在GPU不可用时才使用CPU
    if torch.cuda.is_available():
        device = "cuda"
        print(f"✅ Using GPU: {torch.cuda.get_device_name(0)}")
    else:
        device = "cpu"
        print("⚠️  GPU not available, using CPU")
    emb_model = SentenceTransformer(EMB_MODEL, device=device)
    emb_dim = emb_model.get_sentence_embedding_dimension()
    print(f"Using device: {device}, embedding dim: {emb_dim}")

    cache = TwoLevelEmbCache(dim=emb_dim)
    opinion_index = IncrementalOpinionIndex.load(emb_dim, "opinion_index")
    meta_buffer = MetaUpdateBuffer()
    paper_tracker = PaperProgressTracker(PROGRESS_DB)
    
    processed_count = paper_tracker.get_count()
    if processed_count > 0:
        print(f"📂 检测到已处理 {processed_count} 篇论文，将跳过已处理论文")

    # 启用parser以支持依存句法分析（提升结构化提取准确率）
    nlp = spacy.load("en_core_web_sm", disable=["ner"])
    nlp.add_pipe("sentencizer")
    nlp.max_length = 2_000_000

    mentions_writer = YearlyDatabaseWriter(MENTIONS_DB)

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
    current_chunk_idx = 0  # 记录当前chunk编号

    try:
        for chunk_idx, chunk in enumerate(reader, start=1):
            current_chunk_idx = chunk_idx
            print(f"\n{'='*80}")
            print(f"📦 开始处理 Chunk {chunk_idx}，Chunk大小 {len(chunk)}，微批大小 {PAPERS_PER_MICROBATCH}")
            print(f"{'='*80}")
            chunk = chunk.rename(columns={
                'id': 'paper_id', 'title': 'title', 'abstract': 'abstract',
                'keyword': 'keywords', 'pub_year': 'year'
            })
            # 仅对字符串列填充空串，保持year列为可空整型（Int64）
            string_columns = ['paper_id', 'title', 'abstract', 'keywords']
            for col in string_columns:
                if col in chunk.columns:
                    chunk[col] = chunk[col].fillna('')
            
            # 在chunk级别过滤掉没有摘要的数据（分块后、逐行处理前）
            chunk_size_before = len(chunk)
            chunk = chunk[chunk['abstract'].str.strip().astype(bool)]
            skipped_papers += chunk_size_before - len(chunk)

            for row in chunk.itertuples(index=False):
                if paper_tracker.is_processed(row):
                    skipped_papers += 1
                    continue
                
                microbatch_buffer.append(row)
                
                if len(microbatch_buffer) >= PAPERS_PER_MICROBATCH:
                    count = len(microbatch_buffer)
                    microbatch_count += 1
                    batch_start_time = time.time()
                    
                    # 重置调试计数器
                    _extract_debug_count = {'total': 0, 'stage1_empty': 0, 'stage2_empty': 0, 'stage3_empty': 0, 'stage5_empty': 0}
                    _extract_debug_count_by_abstract = {
                        'total_with_abstract': 0,
                        'total_without_abstract': 0,
                        'stage1_empty_with_abstract': 0,
                        'stage1_empty_without_abstract': 0,
                        'stage2_empty_with_abstract': 0,
                        'stage2_empty_without_abstract': 0,
                        'stage3_empty_with_abstract': 0,
                        'stage3_empty_without_abstract': 0,
                        'stage5_empty_with_abstract': 0,
                        'stage5_empty_without_abstract': 0,
                    }
                    
                    mentions = process_microbatch(microbatch_buffer, nlp, emb_model, cache, opinion_index, meta_buffer)
                    
                    for r in microbatch_buffer:
                        paper_tracker.mark_processed(r)
                    
                    mentions_count = len(mentions) if mentions else 0
                    if mentions:
                        df = pd.DataFrame(mentions)
                        mentions_writer.write_batch(df)
                    
                    total_papers += count
                    batch_time = time.time() - batch_start_time
                    
                    # 显示每批次的总结信息
                    print(f"\n✅ 微批次 {microbatch_count} 完成 (Chunk {chunk_idx})")
                    print(f"   - 处理论文数: {count:,} 篇")
                    print(f"   - 提取观点数: {mentions_count:,} 条")
                    print(f"   - 累计论文数: {total_papers:,} 篇 (跳过空白摘要: {skipped_papers:,})")
                    print(f"   - 累计观点数: {opinion_index._get_meta_count():,} 个")
                    print(f"   - 处理耗时: {batch_time:.2f} 秒")
                    
                    microbatch_buffer = []

                    if (microbatch_count % CHECKPOINT_EVERY_MICROBATCH == 0 or 
                        time.time() - last_checkpoint > CHECKPOINT_EVERY_SECONDS):
                        checkpoint_start = time.time()
                        # 确保flush顺序一致：先flush meta buffer，再flush pending，再save，最后flush cache
                        meta_buffer.flush_to_index(opinion_index)
                        opinion_index._flush_pending()  # 确保pending向量已写入
                        mentions_writer.flush()
                        opinion_index.save("opinion_index")
                        cache.flush()
                        paper_tracker.flush()
                        save_progress(total_papers)
                        checkpoint_time = time.time() - checkpoint_start
                        last_checkpoint = time.time()
                        
                        # 定期进行观点冲突检测（每10个微批次）
                        if microbatch_count % (CHECKPOINT_EVERY_MICROBATCH * 2) == 0:
                            conflict_pairs = detect_opinion_conflicts(opinion_index, emb_model, cache)
                            if conflict_pairs:
                                print(f"  ⚠️  检测到 {len(conflict_pairs)} 个观点冲突对")
                                opinion_index.save("opinion_index")  # 保存冲突检测结果
                        
                        elapsed_time = time.time() - start_time
                        print(f"\n💾 检查点保存完成 (微批次 {microbatch_count})")
                        print(f"   - 总论文数: {total_papers:,} 篇 (跳过: {skipped_papers:,})")
                        print(f"   - 总观点数: {opinion_index._get_meta_count():,} 个")
                        print(f"   - 保存耗时: {checkpoint_time:.2f} 秒")
                        print(f"   - 总耗时: {elapsed_time/60:.1f} 分钟")

        if microbatch_buffer:
            count = len(microbatch_buffer)
            microbatch_count += 1
            batch_start_time = time.time()
            
            # 重置调试计数器
            _extract_debug_count = {'total': 0, 'stage1_empty': 0, 'stage2_empty': 0, 'stage3_empty': 0, 'stage5_empty': 0}
            _extract_debug_count_by_abstract = {
                'total_with_abstract': 0,
                'total_without_abstract': 0,
                'stage1_empty_with_abstract': 0,
                'stage1_empty_without_abstract': 0,
                'stage2_empty_with_abstract': 0,
                'stage2_empty_without_abstract': 0,
                'stage3_empty_with_abstract': 0,
                'stage3_empty_without_abstract': 0,
                'stage5_empty_with_abstract': 0,
                'stage5_empty_without_abstract': 0,
            }
            
            mentions = process_microbatch(microbatch_buffer, nlp, emb_model, cache, opinion_index, meta_buffer)
            
            for r in microbatch_buffer:
                paper_tracker.mark_processed(r)
            
            mentions_count = len(mentions) if mentions else 0
            if mentions:
                df = pd.DataFrame(mentions)
                mentions_writer.write_batch(df)
            
            total_papers += count
            batch_time = time.time() - batch_start_time
            
            # 显示最后一批的总结信息
            chunk_info = f"Chunk {current_chunk_idx}" if current_chunk_idx > 0 else "最后一批"
            print(f"\n✅ 微批次 {microbatch_count} 完成 ({chunk_info})")
            print(f"   - 处理论文数: {count:,} 篇")
            print(f"   - 提取观点数: {mentions_count:,} 条")
            print(f"   - 累计论文数: {total_papers:,} 篇 (跳过: {skipped_papers:,})")
            print(f"   - 累计观点数: {opinion_index._get_meta_count():,} 个")
            print(f"   - 处理耗时: {batch_time:.2f} 秒")
            
            # 最后一批处理完后，如果满足检查点条件，也要保存
            if (microbatch_count % CHECKPOINT_EVERY_MICROBATCH == 0 or 
                time.time() - last_checkpoint > CHECKPOINT_EVERY_SECONDS):
                checkpoint_start = time.time()
                meta_buffer.flush_to_index(opinion_index)
                opinion_index._flush_pending()
                mentions_writer.flush()
                opinion_index.save("opinion_index")
                cache.flush()
                paper_tracker.flush()
                save_progress(total_papers)
                checkpoint_time = time.time() - checkpoint_start
                last_checkpoint = time.time()
                
                # 定期进行观点冲突检测（每10个微批次）
                if microbatch_count % (CHECKPOINT_EVERY_MICROBATCH * 2) == 0:
                    conflict_pairs = detect_opinion_conflicts(opinion_index, emb_model, cache)
                    if conflict_pairs:
                        print(f"  ⚠️  检测到 {len(conflict_pairs)} 个观点冲突对")
                        opinion_index.save("opinion_index")
                
                elapsed_time = time.time() - start_time
                print(f"\n💾 检查点保存完成 (微批次 {microbatch_count})")
                print(f"   - 总论文数: {total_papers:,} 篇 (跳过: {skipped_papers:,})")
                print(f"   - 总观点数: {opinion_index._get_meta_count():,} 个")
                print(f"   - 保存耗时: {checkpoint_time:.2f} 秒")
                print(f"   - 总耗时: {elapsed_time/60:.1f} 分钟")

    except KeyboardInterrupt:
        print("\n⚠️  处理被用户中断")
    except Exception as e:
        print(f"\n❌ 处理过程中出错: {e}")
        raise
    finally:
        meta_buffer.flush_to_index(opinion_index)
        opinion_index._flush_pending()
        mentions_writer.flush()
        cache.flush()
        paper_tracker.flush()
        print("\n💾 缓存已刷新")
        # 注意：mentions_writer.close()在正常流程末尾调用，异常时也需要确保关闭

    # 输出概念目录
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
                # 使用safe_get_meta确保meta不为None 
                if meta is None:
                    print(f"Warning: meta is None for opinion_id {cid}, skipping")
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
            if meta is not None  # 过滤None值
        ])
    opinions_df.to_parquet(OUT_OPINIONS, index=False)

    meta_buffer.flush_to_index(opinion_index)
    opinion_index._flush_pending()
    opinion_index.save("opinion_index")
    cache.flush()
    paper_tracker.flush()
    
    # 最终观点冲突检测
    print(f"\n{'='*80}")
    print("🔍 执行最终观点冲突检测...")
    print(f"{'='*80}")
    conflict_pairs = detect_opinion_conflicts(opinion_index, emb_model, cache)
    if conflict_pairs:
        print(f"  ⚠️  检测到 {len(conflict_pairs)} 个观点冲突对")
        # 保存冲突检测结果
        opinion_index.save("opinion_index")
    else:
        print("  ✅ 未检测到冲突")
    
    # 在关闭LMDB之前先获取观点数
    total_opinions = opinion_index._get_meta_count()
    
    if opinion_index.raw_store:
        opinion_index.raw_store.close()
    if opinion_index.use_lmdb and opinion_index.lmdb_env:
        opinion_index.lmdb_env.close()
    cache.close()
    paper_tracker.close()
    clear_progress()

    # 获取数据库统计信息并关闭连接
    try:
        db_stats = mentions_writer.get_stats()
    except Exception as e:
        print(f"⚠️  获取数据库统计信息失败: {e}")
        db_stats = {}
    finally:
        mentions_writer.close()
    
    total_time = time.time() - start_time
    print(f"\n{'='*80}")
    print("✅ 处理完成！")
    print(f"{'='*80}")
    
    # 提示用户检查被过滤的论文
    filtered_csv_path = OUTPUT_DIR / "filtered_papers_details.csv"
    if filtered_csv_path.exists():
        df_filtered = pd.read_csv(filtered_csv_path, encoding='utf-8-sig')
        total_filtered = len(df_filtered)
        if total_filtered > 0:
            print(f"\n⚠️  检测到 {total_filtered} 篇论文被过滤")
            print(f"📝 被过滤论文详情已保存至: {filtered_csv_path}")
            print(f"💡 提示: 可以使用以下代码检查被过滤的论文是否是误过滤:")
            print(f"   from 论文创新词汇统计6_2_1观点识别 import check_filtered_papers")
            print(f"   check_filtered_papers(limit=20)  # 查看前20条")
            print(f"   # 或查看特定阶段的被过滤论文:")
            print(f"   check_filtered_papers(stage='stage2_empty', min_confidence=0.35, limit=20)")
    
    # 提示用户查看成功案例样本
    successful_csv_path = OUTPUT_DIR / "successful_papers_sample.csv"
    if successful_csv_path.exists():
        df_successful = pd.read_csv(successful_csv_path, encoding='utf-8-sig')
        total_successful = len(df_successful)
        if total_successful > 0:
            print(f"\n✅ 成功案例样本已保存: {successful_csv_path}")
            print(f"📊 共保存 {total_successful} 条成功提取观点的论文样本（用于质量检查）")
    
    print(f"📊 最终统计:")
    print(f"   - 总论文数: {total_papers:,} 篇 (跳过: {skipped_papers:,})")
    print(f"   - 总观点数: {total_opinions:,} 个")
    print(f"   - 总耗时: {total_time/60:.1f} 分钟 ({total_time:.1f} 秒)")
    cache_stats = cache.get_stats()
    if cache_stats:
        print(f"   - 缓存统计: {cache_stats}")
    if db_stats:
        print(f"   - 数据库统计: {db_stats}")
    print(f"{'='*80}")
    print(f"Mentions database: {MENTIONS_DB}")
    print(f"Opinions catalog: {OUT_OPINIONS}")

def main():
    print("Starting optimized opinion identification...")
    process_streaming_csv()

if __name__ == "__main__":
    main()