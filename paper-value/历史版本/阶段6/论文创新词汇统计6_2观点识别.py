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
from collections import OrderedDict
from functools import lru_cache

import numpy as np
import pandas as pd
import torch
import faiss
import spacy
import yake
from sentence_transformers import SentenceTransformer

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
SIM_THRESHOLD = 0.83
CLUSTER_THRESHOLD = 0.80
ALIAS_LIMIT = 20
FAISS_SEARCH_K = 3

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
        
        self.index.add_with_ids(vecs, ids)
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
        if not self.raw_store or not self.compressor or not self.compressor.trained:
            return
        
        print(f"Rebuilding index with compression...")
        
        if USE_HNSW:
            base = faiss.IndexHNSWFlat(self.compressed_dim, HNSW_M, faiss.METRIC_INNER_PRODUCT)
            base.hnsw.efSearch = HNSW_EF_SEARCH
            base.hnsw.efConstruction = HNSW_EF_CONSTRUCTION
        else:
            base = faiss.IndexFlatIP(self.compressed_dim)
        new_index = faiss.IndexIDMap(base)
        
        batch_size = 1000
        batch_vecs = []
        batch_ids = []
        total_rebuilt = 0
        
        for cid, raw_vec in self.raw_store.iterate():
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

# 观点性动词分类
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

def rule_filter_opinion_sentences(doc) -> List[str]:
    """规则召回：识别可能包含观点的句子（高召回率）"""
    global _stage1_filter_stats, _stage1_recall_stats
    candidate_sentences = []
    
    # 明显的非观点句子模式（应该被过滤）
    NON_OPINION_PATTERNS = [
        r'^\s*\(?\s*[Cc]\)\s*\d{4}',  # 版权信息 "(C) 2010"
        r'All rights reserved',  # 版权信息
        r'Elsevier|Springer|IEEE|ACM|Wiley',  # 出版商名称（单独出现）
        r'^\s*\d+\s*:\s*\d+',  # 页码 "21:376-379"
        r'doi:|DOI:',  # DOI信息
        r'^[A-Z][a-z]+\s+[A-Z][a-z]+\s+Fibrinolysis',  # 期刊名称格式
        r'^\s*[A-Z][a-z]+\s+and\s+[A-Z][a-z]+\s+analysis',  # "EDS and XRD analysis" 这种纯描述
    ]
    
    # 识别标题：检测[ABSTRACT]分隔符之前的句子
    doc_sents = list(doc.sents)
    doc_text = doc.text
    abstract_marker_pos = doc_text.find('[ABSTRACT]')
    
    def is_title_sentence(sent):
        """判断句子是否为标题（出现在[ABSTRACT]标记之前）"""
        if abstract_marker_pos == -1:
            # 没有分隔符，则第一个句子可能是标题
            return sent == doc_sents[0] and len(sent.text) < 200
        else:
            # 有分隔符，检查句子是否在分隔符之前
            return sent.start_char < abstract_marker_pos
    
    for sent_idx, sent in enumerate(doc_sents):
        sent_text = sent.text.strip()
        _stage1_filter_stats['total_sentences'] += 1
        
        is_title = is_title_sentence(sent)
        
        # 对标题使用更宽松的长度要求（5字符），对正文保持10字符
        min_length = 5 if is_title else 10
        if len(sent_text) < min_length:
            _stage1_filter_stats['filtered_too_short'] += 1
            if len(_stage1_filter_stats['filtered_samples']) < 10:
                _stage1_filter_stats['filtered_samples'].append({
                    'sentence': sent_text[:100],
                    'reason': 'too_short',
                    'length': len(sent_text)
                })
            continue
        
        # 过滤明显的非观点句子（版权信息、期刊信息等）
        is_non_opinion = any(re.search(pattern, sent_text, re.IGNORECASE) for pattern in NON_OPINION_PATTERNS)
        if is_non_opinion:
            _stage1_filter_stats['filtered_no_pattern'] += 1
            continue
        
        has_opinion_verb = False
        matched_verb = None
        sent_lower = sent_text.lower()
        
        phrase_verbs = ['leads to', 'lead to', 'led to', 'results in', 'result in', 'resulted in',
                       'causes', 'cause', 'caused', 'enables', 'enable', 'enabled',
                       'allows', 'allow', 'allowed', 'prevents', 'prevent', 'prevented',
                       'serve to', 'serves to', 'served to', 'continue to', 'continues to', 'continued to',
                       'tend to', 'tends to', 'tended to', 'appear to', 'appears to', 'appeared to',
                       'play a role', 'plays a role', 'played a role', 'play an role', 'plays an role', 'played an role',
                       'play a crucial role', 'play an important role', 'play a key role', 'play a significant role',
                       'play a vital role', 'play an essential role', 'play a critical role', 'play a major role']
        for phrase_verb in phrase_verbs:
            if phrase_verb in sent_lower:
                has_opinion_verb = True
                matched_verb = phrase_verb
                break
        
        if not has_opinion_verb:
            for token in sent:
                if token.lemma_.lower() in OPINION_VERBS_STRONG | OPINION_VERBS_MEDIUM | OPINION_VERBS_WEAK:
                    has_opinion_verb = True
                    matched_verb = token.lemma_.lower()
                    break
        
        has_comparison = any(re.search(pattern, sent_text, re.IGNORECASE) 
                           for pattern in COMPARISON_PATTERNS)
        
        has_evaluation = any(re.search(pattern, sent_text, re.IGNORECASE) 
                            for pattern in EVALUATION_PATTERNS)
        
        has_negation = any(re.search(pattern, sent_text, re.IGNORECASE) 
                          for pattern in NEGATION_PATTERNS)
        
        has_explicit_opinion = has_opinion_verb or has_comparison or has_evaluation or has_negation
        
        potential_opinion_keywords = [
            r'\b(finding|result|outcome|conclusion|evidence|observation|discovery)\b',
            r'\b(show|demonstrate|indicate|reveal|suggest|prove|confirm)\s+that',
            r'\b(agree|consistent|accordance|accord)\s+with',
            r'\b(attempt|try|seek)\s+to\s+(predict|explain|understand|investigate)',
            r'\b(was|were)\s+(found|observed|detected|identified|discovered)',
            r'\b(achieve|obtain|attain|accomplish|realize)\s+',
            r'\b(contribute|contributes|contributed)\s+(?:to|toward)\b',
            r'\b(influence|influences|influenced)\s+(?:on|upon)\b',
            r'\b(affect|affects|affected)\s+(?:on|upon)\b',
            r'\b(impact|impacts|impacted)\s+(?:on|upon)\b',
            r'\b(play|plays|played)\s+(?:a|an)\s+(?:role|part|function)\b',
            r'\b(important|crucial|significant|essential|critical|key|vital)\s+(?:for|to|in)\b',
            r'\b(associated|correlated|linked|related)\s+(?:with|to)\b',
            r'\b(lead|leads|led)\s+(?:to|toward)\b',
            r'\b(result|results|resulted)\s+(?:in|from)\b',
            r'\b(cause|causes|caused)\s+(?:by|of)\b',
            r'\b(aim|aims|aimed|goal|goals|objective|objectives|purpose)\s+(?:of|is|was|are|were)\b',
            r'\b(designed|intended|meant)\s+(?:to|for)\b',
            r'\b(research|study|investigation|analysis)\s+(?:show|demonstrate|indicate|reveal|suggest|find|prove|confirm)\b',
            r'\b(we|our|this|the)\s+(?:research|study|investigation|analysis|paper|work)\s+(?:show|demonstrate|indicate|reveal|suggest|find|prove|confirm)\b',
        ]
        has_potential_opinion = any(re.search(pattern, sent_text, re.IGNORECASE) for pattern in potential_opinion_keywords)
        
        has_research_keywords = any(kw in sent_lower for kw in [
            'finding', 'result', 'outcome', 'conclusion', 'evidence', 'observation', 'discovery',
            'important', 'crucial', 'significant', 'essential', 'critical', 'key', 'vital',
            'effective', 'efficient', 'better', 'worse', 'superior', 'inferior',
            'improve', 'enhance', 'increase', 'reduce', 'decrease'
        ])
        
        title_opinion_keywords = [
            'novel', 'new', 'innovative', 'original', 'breakthrough', 'advance',
            'effective', 'efficient', 'better', 'superior', 'improved', 'enhanced',
            'significant', 'important', 'crucial', 'key', 'vital', 'essential',
            'comparison', 'compared', 'versus', 'vs',
            'findings', 'implications', 'contributions'
        ]
        title_keyword_count = sum(1 for kw in title_opinion_keywords if kw in sent_lower)
        has_title_opinion_keyword = is_title and (
            title_keyword_count >= 1 and (has_comparison or has_evaluation or has_opinion_verb)
        )
        
        min_words_for_implicit = 3 if is_title else 8
        has_implicit_opinion = has_research_keywords and len(sent_text.split()) >= min_words_for_implicit
        
        should_block_in_stage1 = False
        if not is_title:
            method_description_patterns = [
                r'\b(we|they)\s+(introduce|introduced|propose|proposed|present|presented|describe|described|report|reported|discuss|discussed)\b',
                r'\b(we|they)\s+(implement|implemented|develop|developed|design|designed|create|created|build|built|establish|established)\b',
                r'\b(we|they)\s+(use|used|employ|employed|apply|applied|adopt|adopted|utilize|utilized)\b',
                r'\b(we|they)\s+(analyze|analyzed|examine|examined|investigate|investigated|assess|assessed|evaluate|evaluated)\b',
                r'\b(we|they)\s+(measure|measured|calculate|calculated|estimate|estimated|conduct|conducted|perform|performed)\b',
                r'\b(this|the)\s+(paper|article|study|work|research)\s+(introduce|introduces|propose|proposes|present|presents|describe|describes|report|reports|discuss|discusses)\b',
                r'\b(this|the)\s+(paper|article|study|work|research)\s+(implement|implements|develop|develops|design|designs|provide|provides|give|gives)\b',
                r'\b(in\s+this)\s+(paper|article|study|work|research)?,?\s+(we|they)\s+(introduce|propose|present|describe|report|discuss|implement|develop|design)\b',
                r'\b(aim|goal|objective|purpose)\s+(?:of\s+(?:this|the)\s+study\s+)?(?:is|was|are|were)\s+to\s+(investigate|examine|analyze|assess|evaluate|determine|explore)\b',
                r'\bthe\s+purpose\s+of\s+this\s+(study|research|paper|work)\s+is\s+to\b',
                r'\b(?:on|in)\s+the\s+basis\s+of\b',
                r'\b(?:analysis|study|research)\s+(?:is|was)\s+based\s+on\b',
            ]
            should_block_in_stage1 = any(re.search(p, sent_lower) for p in method_description_patterns)
        
        if (has_explicit_opinion or has_potential_opinion or has_implicit_opinion or has_title_opinion_keyword) and not should_block_in_stage1:
            candidate_sentences.append(sent_text)
            _stage1_recall_stats['total_candidates'] += 1
            if has_opinion_verb:
                _stage1_recall_stats['by_verb'] += 1
            if has_comparison:
                _stage1_recall_stats['by_comparison'] += 1
            if has_evaluation:
                _stage1_recall_stats['by_evaluation'] += 1
            if has_negation:
                _stage1_recall_stats['by_negation'] += 1
            if has_title_opinion_keyword:
                if 'by_title' not in _stage1_recall_stats:
                    _stage1_recall_stats['by_title'] = 0
                _stage1_recall_stats['by_title'] += 1
        else:
            _stage1_filter_stats['filtered_no_pattern'] += 1
            if len(_stage1_filter_stats['filtered_samples']) < 200:
                # 检查是否包含可能被漏掉的观点性词汇
                potential_verbs = []
                for token in sent:
                    verb_lemma = token.lemma_.lower()
                    if token.pos_ == 'VERB' and verb_lemma not in OPINION_VERBS_STRONG | OPINION_VERBS_MEDIUM | OPINION_VERBS_WEAK:
                        if verb_lemma in ['predict', 'explain', 'understand', 'investigate', 'examine', 'analyze']:
                            potential_verbs.append(verb_lemma)
                
                _stage1_filter_stats['filtered_samples'].append({
                    'sentence': sent_text[:150],
                    'reason': 'no_pattern',
                    'has_verb': has_opinion_verb,
                    'matched_verb': matched_verb,
                    'has_comparison': has_comparison,
                    'has_evaluation': has_evaluation,
                    'has_negation': has_negation,
                    'potential_verbs': potential_verbs,
                    'sentence_length': len(sent_text.split())
                })
    
    return candidate_sentences

_OPINION_CLASSIFIER = None
_OPINION_CLASSIFIER_THRESHOLD = 0.50

def get_opinion_classifier(emb_model):
    """获取观点分类器"""
    global _OPINION_CLASSIFIER
    if _OPINION_CLASSIFIER is None:
        _OPINION_CLASSIFIER = {
            'emb_model': emb_model,
            'opinion_prompts': [
                "This sentence presents a research finding or conclusion",
                "This sentence compares methods or evaluates performance",
                "This sentence claims superiority or improvement"
            ]
        }
    return _OPINION_CLASSIFIER

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
    
    matches_template = any(re.search(template['pattern'], sentence, re.IGNORECASE) 
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
    matches_template = any(re.search(template['pattern'], sentence, re.IGNORECASE) 
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

def classify_opinion_sentences(sentences: List[str], emb_model, cache, doc=None) -> List[str]:
    """基于规则的特征验证：过滤非观点句
    
    使用规则特征验证替代语义相似度匹配：
    - 观点性动词验证（强/中等）
    - 主谓结构验证
    - 断言性验证
    - 观点模板匹配
    """
    if not sentences:
        return []
    
    # 如果没有提供doc，需要重新解析（但通常应该提供）
    if doc is None:
        # 如果无法获取doc，回退到简单规则验证
        confirmed_sentences = []
        for sent in sentences:
            sent_lower = sent.lower()
            # 简单验证：必须有强/中等观点性动词，并且有断言性内容
            has_strong_verb = any(verb in sent_lower for verb in OPINION_VERBS_STRONG)
            has_medium_verb = any(verb in sent_lower for verb in OPINION_VERBS_MEDIUM)
            has_comparison = any(re.search(pattern, sent, re.IGNORECASE) for pattern in COMPARISON_PATTERNS)
            has_evaluation = any(re.search(pattern, sent, re.IGNORECASE) for pattern in EVALUATION_PATTERNS)
            has_negation = any(re.search(pattern, sent, re.IGNORECASE) for pattern in NEGATION_PATTERNS)
            matches_template = any(re.search(template['pattern'], sent, re.IGNORECASE) 
                                  for template in OPINION_TEMPLATES)
            
            if (has_strong_verb or has_medium_verb) and (has_comparison or has_evaluation or has_negation or matches_template):
                confirmed_sentences.append(sent)
        return confirmed_sentences
    
    # 使用完整的规则验证
    confirmed_sentences = []
    # 从doc中提取句子对象
    doc_sents = {sent.text.strip(): sent for sent in doc.sents}
    
    # 检测[ABSTRACT]标记位置，用于判断是否为标题句子
    abstract_marker_pos = doc.text.find('[ABSTRACT]')
    doc_sents_list = list(doc.sents)
    
    for sent_text in sentences:
        # 找到对应的spaCy句子对象
        sent_doc = doc_sents.get(sent_text.strip())
        if sent_doc is None:
            # 如果找不到，尝试模糊匹配
            for doc_sent in doc.sents:
                if doc_sent.text.strip()[:50] == sent_text.strip()[:50]:
                    sent_doc = doc_sent
                    break
        
        if sent_doc is None:
            continue
        
        is_title = False
        if abstract_marker_pos == -1:
            # 没有分隔符，第一个句子可能是标题
            is_title = (sent_doc == doc_sents_list[0] and len(sent_doc.text) < 200)
        else:
            # 有分隔符，检查句子是否在分隔符之前
            is_title = (sent_doc.start_char < abstract_marker_pos)
        
        # 根据是否为标题选择验证函数
        if is_title:
            # 标题使用更宽松的验证规则
            if verify_title_opinion_by_rules(sent_text, sent_doc):
                confirmed_sentences.append(sent_text)
        else:
            # 摘要使用标准验证规则
            if verify_opinion_by_rules(sent_text, sent_doc):
                confirmed_sentences.append(sent_text)
    
    return confirmed_sentences

def detect_opinion_stance(sentence: str, structured_opinion: StructuredOpinion) -> StructuredOpinion:
    """检测观点方向：极性、强度、方向"""
    sent_lower = sentence.lower()
    
    # 检测极性
    positive_indicators = ['outperforms', 'better', 'superior', 'improves', 'effective', 
                          'significant', 'exceeds', 'surpasses', 'enhances', 'increases']
    negative_indicators = ['worse', 'inferior', 'fails', 'does not', 'cannot', 
                          'unable', 'reduces', 'decreases', 'not better', 'not effective']
    
    has_positive = any(ind in sent_lower for ind in positive_indicators)
    has_negative = any(ind in sent_lower for ind in negative_indicators)
    
    if has_negative and not has_positive:
        structured_opinion.polarity = "negative"
    elif has_positive and not has_negative:
        structured_opinion.polarity = "positive"
    else:
        structured_opinion.polarity = "neutral"
    
    strength_patterns = {
        'high': ['significantly', 'substantially', 'dramatically', 'greatly', 'considerably'],
        'medium': ['moderately', 'somewhat', 'fairly', 'reasonably'],
        'low': ['slightly', 'marginally', 'minimally', 'somewhat']
    }
    
    for level, words in strength_patterns.items():
        if any(word in sent_lower for word in words):
            structured_opinion.strength = level
            break
    
    if structured_opinion.polarity == "positive" and structured_opinion.strength in ['high', 'medium']:
        structured_opinion.stance = "support"
    elif structured_opinion.polarity == "negative" and structured_opinion.strength in ['high', 'medium']:
        structured_opinion.stance = "oppose"
    else:
        structured_opinion.stance = "neutral"
    
    return structured_opinion

def extract_structured_opinion_from_sentence(sentence: str, doc) -> Optional[StructuredOpinion]:
    """从句子中提取结构化观点（使用模板匹配）"""
    global _stage3_extraction_stats
    _stage3_extraction_stats['total_sentences'] += 1
    sentence_lower = sentence.lower()
    
    # 按优先级尝试匹配模板
    template_matched = False
    matched_template_priority = None
    for template in sorted(OPINION_TEMPLATES, key=lambda x: x['priority']):
        pattern = template['pattern']
        slots = template['slots']
        template_priority = template.get('priority', 999)
        
        match = re.search(pattern, sentence, re.IGNORECASE)
        if match:
            template_matched = True
            matched_template_priority = template_priority
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
            
            if opinion.object and opinion.predicate:
                _stage3_extraction_stats['template_matched'] += 1
                opinion = detect_opinion_stance(sentence, opinion)
                return opinion
            else:
                # 模板匹配但字段缺失
                _stage3_extraction_stats['field_missing'] += 1
                if len(_stage3_extraction_stats['failed_samples']) < 10:
                    _stage3_extraction_stats['failed_samples'].append({
                        'sentence': sentence[:150],
                        'reason': 'template_matched_but_field_missing',
                        'has_object': bool(opinion.object),
                        'has_predicate': bool(opinion.predicate),
                        'template_priority': template_priority
                    })
    
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

def extract_opinion_from_dependency(doc, sentence: str) -> Optional[StructuredOpinion]:
    """使用基于POS标签和位置的方法提取观点（不依赖依存句法分析）"""
    opinion = StructuredOpinion()
    sent_lower = sentence.lower()
    
    # 辅助函数：提取名词短语（基于POS标签和位置）
    def extract_noun_phrase(start_token):
        """从起始token提取名词短语（基于POS标签和位置）"""
        tokens = [start_token]
        start_idx = start_token.i
        
        # 向前查找限定词和形容词（基于POS标签）
        for i in range(start_idx - 1, -1, -1):
            token = doc[i]
            # 限定词：the, a, an
            if token.pos_ == "DET":
                tokens.insert(0, token)
            # 形容词
            elif token.pos_ == "ADJ":
                tokens.insert(0, token)
            # 名词（复合名词）
            elif token.pos_ in ["NOUN", "PROPN"] and start_idx - i <= 2:
                tokens.insert(0, token)
            else:
                break
        
        # 向后查找修饰词（基于POS标签）
        for i in range(start_idx + 1, len(doc)):
            token = doc[i]
            # 形容词
            if token.pos_ == "ADJ":
                tokens.append(token)
            # 名词（复合名词）
            elif token.pos_ in ["NOUN", "PROPN"] and i - start_idx <= 2:
                tokens.append(token)
            # 介词短语（停止）
            elif token.pos_ == "ADP":
                break
            else:
                break
        
        return " ".join([t.text for t in tokens])
    
    # 策略1：查找观点性动词（强/中等），使用基于位置的方法查找名词
    for token in doc:
        verb_lemma = token.lemma_.lower()
        if verb_lemma in OPINION_VERBS_STRONG | OPINION_VERBS_MEDIUM:
            verb_idx = token.i
            # 查找动词前后的名词（作为object）
            # 优先查找动词前的名词（通常是主语）
            for i in range(verb_idx - 1, max(0, verb_idx - 6), -1):
                if doc[i].pos_ in ["NOUN", "PROPN"]:
                    opinion.object = extract_noun_phrase(doc[i])
                    break
            # 如果前面没找到，查找动词后的名词（通常是宾语）
            if not opinion.object:
                for i in range(verb_idx + 1, min(len(doc), verb_idx + 6)):
                    if doc[i].pos_ in ["NOUN", "PROPN"]:
                        opinion.object = extract_noun_phrase(doc[i])
                        break
            
            opinion.predicate = verb_lemma
            if opinion.object and opinion.predicate:
                opinion = detect_opinion_stance(sentence, opinion)
                return opinion
    
    # 策略2：查找动词，如果包含观点性内容
    for token in doc:
        if token.pos_ in ["VERB", "AUX"]:
            verb_idx = token.i
            if any(kw in sent_lower for kw in ['result', 'finding', 'conclusion', 'evidence', 'outcome', 'performance', 'accuracy']):
                # 查找动词前后的名词
                for i in range(verb_idx - 1, max(0, verb_idx - 6), -1):
                    if doc[i].pos_ in ["NOUN", "PROPN"]:
                        opinion.object = extract_noun_phrase(doc[i])
                        break
            if not opinion.object:
                for i in range(verb_idx + 1, min(len(doc), verb_idx + 6)):
                    if doc[i].pos_ in ["NOUN", "PROPN"]:
                        opinion.object = extract_noun_phrase(doc[i])
                        break
                        
            if opinion.object:
                opinion.predicate = token.lemma_
                if opinion.object and opinion.predicate:
                    opinion = detect_opinion_stance(sentence, opinion)
                    return opinion
    
    # 策略3：查找名词+观点性形容词/动词
    for token in doc:
        if token.pos_ in ["NOUN", "PROPN"]:
            token_text = token.text.lower()
            if any(kw in token_text for kw in ['result', 'finding', 'conclusion', 'evidence', 'outcome', 'performance', 'method', 'approach']):
                opinion.object = extract_noun_phrase(token)
                # 查找名词前后的动词/形容词
                token_idx = token.i
                for i in range(max(0, token_idx - 3), min(len(doc), token_idx + 3)):
                    if i != token_idx and doc[i].pos_ in ["VERB", "ADJ"]:
                        opinion.predicate = doc[i].lemma_
                        break
    
                if not opinion.predicate:
                    # 如果没有找到，使用默认predicate
                    opinion.predicate = "show"
    if opinion.object and opinion.predicate:
        opinion = detect_opinion_stance(sentence, opinion)
        return opinion
    
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
    """对象抽象化：提取核心名词，同义词归一化"""
    if not phrase:
        return ""
    
    # 转换为小写并去除前后空格
    phrase_lower = normalize_text(phrase)
    
    # 同义词归一化
    for synonym, canonical in SYNONYM_MAP.items():
        if synonym in phrase_lower:
            return canonical
    
    # 如果提供了doc，使用spaCy提取核心名词
    if doc:
        for np in doc.noun_chunks:
            if np.text.lower() in phrase_lower:
                # 提取head noun
                head = np.root.text
                return head.lower()
    
    # 简单处理：去除常见修饰词
    words = phrase_lower.split()
    # 去除限定词和常见修饰词
    filtered_words = [w for w in words if w not in ['the', 'a', 'an', 'this', 'that', 
                                                     'proposed', 'novel', 'new', 'improved']]
    
    if filtered_words:
        # 返回最后一个词（通常是核心名词）
        return filtered_words[-1]
    
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
# 阶段1召回质量统计（用于诊断）
_stage1_recall_stats = {
    'total_candidates': 0,
    'by_verb': 0,
    'by_comparison': 0,
    'by_evaluation': 0,
    'by_negation': 0,
    'samples': []
}
# 阶段1过滤统计（新增：记录为什么句子被过滤）
_stage1_filter_stats = {
    'total_sentences': 0,
    'filtered_too_short': 0,
    'filtered_no_verb': 0,
    'filtered_no_pattern': 0,
    'filtered_samples': [],
    'potential_opinion_verbs': set(),
    'potential_patterns': [],
    'false_negative_count': 0,  # 误过滤数量（真正的观点被过滤）
    'true_negative_count': 0,  # 正确过滤数量（非观点被正确过滤）
    'uncertain_count': 0  # 不确定数量
}
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

def extract_opinions_from_document(doc, emb_model, cache, has_abstract=False, paper_id=None) -> List[Tuple[str, StructuredOpinion]]:
    """从文档中提取观点（五阶段流程）"""
    global _extract_debug_count, _extract_debug_count_by_abstract, _filtered_paper_ids
    
    _extract_debug_count['total'] += 1
    
    if has_abstract:
        _extract_debug_count_by_abstract['total_with_abstract'] += 1
    else:
        _extract_debug_count_by_abstract['total_without_abstract'] += 1
    
    # 阶段1：规则召回
    candidate_sentences = rule_filter_opinion_sentences(doc)
    
    if not candidate_sentences:
        _extract_debug_count['stage1_empty'] += 1
        if has_abstract:
            _extract_debug_count_by_abstract['stage1_empty_with_abstract'] += 1
        else:
            _extract_debug_count_by_abstract['stage1_empty_without_abstract'] += 1
        if paper_id is not None:
            _filtered_paper_ids['stage1_empty'].append(paper_id)
        return []
    
    # 阶段2：基于规则的特征验证（替代语义相似度匹配）
    confirmed_sentences = classify_opinion_sentences(candidate_sentences, emb_model, cache, doc=doc)
    
    if not confirmed_sentences:
        _extract_debug_count['stage2_empty'] += 1
        if has_abstract:
            _extract_debug_count_by_abstract['stage2_empty_with_abstract'] += 1
        else:
            _extract_debug_count_by_abstract['stage2_empty_without_abstract'] += 1
        if paper_id is not None:
            _filtered_paper_ids['stage2_empty'].append(paper_id)
        return []
    
    # 阶段3-4：结构化抽取
    opinions = []
    structured_count = 0
    for sent_text in confirmed_sentences:
        # 使用原doc（spaCy doc包含所有句子信息）
        structured_opinion = extract_structured_opinion_from_sentence(sent_text, doc)
        
        if structured_opinion:
            structured_count += 1
            # 阶段5：规范化
            normalized_text = normalize_opinion_to_string(structured_opinion)
            if normalized_text:
                opinions.append((normalized_text, structured_opinion))
    
    if structured_count == 0:
        _extract_debug_count['stage3_empty'] += 1
        if has_abstract:
            _extract_debug_count_by_abstract['stage3_empty_with_abstract'] += 1
        else:
            _extract_debug_count_by_abstract['stage3_empty_without_abstract'] += 1
        if paper_id is not None:
            _filtered_paper_ids['stage3_empty'].append(paper_id)
    elif not opinions:
        _extract_debug_count['stage5_empty'] += 1
        if has_abstract:
            _extract_debug_count_by_abstract['stage5_empty_with_abstract'] += 1
        else:
            _extract_debug_count_by_abstract['stage5_empty_without_abstract'] += 1
        if paper_id is not None:
            _filtered_paper_ids['stage5_empty'].append(paper_id)
    
    return opinions

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

# 全局YAKE提取器（保留用于兼容，但将被观点识别替代）
_YAKE_EXTRACTOR = None

def get_yake_extractor():
    global _YAKE_EXTRACTOR
    if _YAKE_EXTRACTOR is None:
        _YAKE_EXTRACTOR = yake.KeywordExtractor(
            lan="en", n=4, top=YAKE_TOP, 
            dedupLim=YAKE_DEDUP_LIM, dedupFunc=YAKE_DEDUP_FUNC
        )
    return _YAKE_EXTRACTOR

def extract_lightweight_np(doc):
    phrases, buf = [], []
    for tok in doc:
        if tok.pos_ in ("ADJ", "NOUN", "PROPN"):
            buf.append(tok.text)
        else:
            if buf:
                phrase = " ".join(buf).strip()
                if _is_valid_noun_phrase(phrase):
                    phrases.append(phrase)
                buf = []
    if buf:
        phrase = " ".join(buf).strip()
        if _is_valid_noun_phrase(phrase):
            phrases.append(phrase)
    return phrases

def _is_valid_noun_phrase(phrase: str) -> bool:
    """过滤低质量的noun phrase"""
    if not (3 <= len(phrase) <= 80):
        return False
    
    # 过滤通用词汇组合
    normalized = normalize_text(phrase)
    words = normalized.split()
    
    # 过滤：全是常见形容词/限定词
    common_adj = {'many', 'much', 'more', 'most', 'some', 'several', 'various', 
                  'different', 'important', 'significant', 'high', 'low', 'new', 
                  'old', 'previous', 'recent', 'current', 'future', 'next'}
    if len(words) <= 3 and all(w in common_adj for w in words):
        return False
    
    # 过滤：重复词汇（如"high high important"）
    if len(set(words)) < len(words) * 0.6:
        return False
    
    # 过滤：全是数字或特殊字符
    if all(not c.isalnum() or c.isdigit() for c in phrase if c.isalnum()):
        return False
    
    # 过滤：已经是停用词
    if is_generic_phrase(phrase):
        return False
    
    return True

def extract_yake_windowed(doc):
    sents = [s.text for s in doc.sents]
    windows = []
    for i in range(0, min(len(sents), YAKE_MAX_WINDOWS * YAKE_WINDOW_SIZE), YAKE_WINDOW_SIZE):
        chunk = " ".join(sents[i:i+YAKE_WINDOW_SIZE]).strip()
        if chunk:
            windows.append(chunk[:YAKE_MAX_CHARS])
    
    if not windows:
        return []
    
    extractor = get_yake_extractor()
    
    merged, seen = [], set()
    for w in windows:
        try:
            for kw, _ in extractor.extract_keywords(w)[:YAKE_PER_WINDOW_TOP]:
                if kw not in seen:
                    seen.add(kw)
                    merged.append(kw)
                    if len(merged) >= YAKE_TOP:
                        break
        except Exception as e:
            # YAKE提取失败是可恢复的错误，记录警告但继续处理
            # 使用更详细的错误信息，但不打印完整traceback（避免日志过多）
            error_type = type(e).__name__
            print(f"Warning: YAKE extraction failed for window ({error_type}): {e}")
            continue
        if len(merged) >= YAKE_TOP:
            break
    return merged

def select_top_opinions_from_embeddings(candidates, embeddings):
    """选择有效观点：通过聚类去重，保留所有有效观点（不限制数量）"""
    valid_indices = [i for i, c in enumerate(candidates) if not is_generic_phrase(c)]
    if not valid_indices:
        return []
    
    valid_candidates = [candidates[i] for i in valid_indices]
    valid_embeddings = embeddings[valid_indices]
    n = len(valid_candidates)
    
    if n == 1:
        return [(valid_candidates[0], valid_embeddings[0])]

    # 聚类去重
    sim_mat = valid_embeddings @ valid_embeddings.T
    visited = np.zeros(n, dtype=bool)
    clusters = []
    
    for i in range(n):
        if visited[i]:
            continue
        members = np.where(sim_mat[i] > SIM_THRESHOLD)[0]
        visited[members] = True
        clusters.append(members.tolist())

    # 代表选择
    representatives, rep_embs = [], []
    for members in clusters:
        cemb = valid_embeddings[members]
        centroid = cemb.mean(axis=0)
        centroid = centroid / (np.linalg.norm(centroid) + 1e-12)
        best_idx = members[np.argmax(cemb @ centroid)]
        representatives.append(valid_candidates[best_idx])
        rep_embs.append(valid_embeddings[best_idx])

    # 边界情况处理
    if len(representatives) == 0:
        return []
    if len(representatives) == 1:
        return list(zip(representatives, rep_embs))
    
    # 按中心性排序（重要性排序），保留所有观点
    rep_embs = np.stack(rep_embs)
    R = rep_embs @ rep_embs.T
    centrality = (R.sum(axis=1) - 1.0) / (len(representatives) - 1)
    sorted_idx = np.argsort(-centrality)  # 按中心性降序排序
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

def process_microbatch(rows, nlp, emb_model, cache, opinion_index, meta_buffer):
    global _stage1_recall_stats, _stage2_verification_stats, _stage1_filter_stats, _stage3_extraction_stats, _stage5_normalization_stats, _extract_debug_count_by_abstract, _filtered_paper_ids
    if USE_HASH_DEDUP:
        reset_microbatch_hash_set()
    
    # 重置统计信息（每个微批次独立统计）
    _filtered_paper_ids = {
        'stage1_empty': [],
        'stage2_empty': [],
        'stage3_empty': [],
        'stage5_empty': [],
    }
    _stage1_recall_stats = {
        'total_candidates': 0,
        'by_verb': 0,
        'by_comparison': 0,
        'by_evaluation': 0,
        'by_negation': 0,
        'samples': []
    }
    _stage1_filter_stats = {
        'total_sentences': 0,
        'filtered_too_short': 0,
        'filtered_no_verb': 0,
        'filtered_no_pattern': 0,
        'filtered_samples': [],
        'potential_opinion_verbs': set(),
        'potential_patterns': [],
        'false_negative_count': 0,
        'true_negative_count': 0,
        'uncertain_count': 0
    }
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
        has_abstract = bool(abstract.strip())
        
        # 使用观点识别提取观点
        opinions = extract_opinions_from_document(doc, emb_model, cache, has_abstract=has_abstract, paper_id=paper_id)
        
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
        stage1_remaining = total - _extract_debug_count['stage1_empty']
        stage2_remaining = stage1_remaining - _extract_debug_count['stage2_empty']
        stage3_remaining = stage2_remaining - _extract_debug_count['stage3_empty']
        stage5_remaining = stage3_remaining - _extract_debug_count['stage5_empty']
        
        print(f"\n📈 各阶段论文数变化:")
        print(f"   - 阶段0（开始）: {total} 篇论文")
        print(f"   - 阶段1（规则召回）后: {stage1_remaining} 篇有候选句子 | 过滤 {_extract_debug_count['stage1_empty']} 篇 ({_extract_debug_count['stage1_empty']/total*100:.1f}%)")
        print(f"   - 阶段2（精确验证）后: {stage2_remaining} 篇通过验证 | 再过滤 {_extract_debug_count['stage2_empty']} 篇 ({_extract_debug_count['stage2_empty']/total*100:.1f}%)")
        print(f"   - 阶段3（结构化）后: {stage3_remaining} 篇完成结构化 | 再过滤 {_extract_debug_count['stage3_empty']} 篇 ({_extract_debug_count['stage3_empty']/total*100:.1f}%)")
        print(f"   - 阶段5（规范化）后: {stage5_remaining} 篇最终有观点 | 再过滤 {_extract_debug_count['stage5_empty']} 篇 ({_extract_debug_count['stage5_empty']/total*100:.1f}%)")
        print(f"   - 最终保留率: {stage5_remaining/total*100:.1f}%")
        
        # 🆕 区分有摘要/无摘要的详细统计
        print(f"\n📊 各阶段过滤情况（区分有摘要/无摘要）:")
        total_with_abstract = _extract_debug_count_by_abstract['total_with_abstract']
        total_without_abstract = _extract_debug_count_by_abstract['total_without_abstract']
        
        if total_with_abstract > 0 or total_without_abstract > 0:
            print(f"   - 初始状态:")
            print(f"     * 有摘要的论文数: {total_with_abstract}")
            print(f"     * 无摘要的论文数: {total_without_abstract}")
            
            # 阶段1统计
            stage1_empty_with_abstract = _extract_debug_count_by_abstract['stage1_empty_with_abstract']
            stage1_empty_without_abstract = _extract_debug_count_by_abstract['stage1_empty_without_abstract']
            stage1_remaining_with_abstract = total_with_abstract - stage1_empty_with_abstract
            stage1_remaining_without_abstract = total_without_abstract - stage1_empty_without_abstract
            print(f"   - 阶段1（规则召回）后:")
            print(f"     * 有摘要: 剩余 {stage1_remaining_with_abstract} 篇 | 过滤 {stage1_empty_with_abstract} 篇 ({stage1_empty_with_abstract/total_with_abstract*100:.1f}%)" if total_with_abstract > 0 else "     * 有摘要: 0 篇")
            print(f"     * 无摘要: 剩余 {stage1_remaining_without_abstract} 篇 | 过滤 {stage1_empty_without_abstract} 篇 ({stage1_empty_without_abstract/total_without_abstract*100:.1f}%)" if total_without_abstract > 0 else "     * 无摘要: 0 篇")
            if _filtered_paper_ids['stage1_empty']:
                print(f"     * 被过滤的论文ID: {_filtered_paper_ids['stage1_empty']}")
            
            # 阶段2统计
            stage2_empty_with_abstract = _extract_debug_count_by_abstract['stage2_empty_with_abstract']
            stage2_empty_without_abstract = _extract_debug_count_by_abstract['stage2_empty_without_abstract']
            stage2_remaining_with_abstract = stage1_remaining_with_abstract - stage2_empty_with_abstract
            stage2_remaining_without_abstract = stage1_remaining_without_abstract - stage2_empty_without_abstract
            print(f"   - 阶段2（精确验证）后:")
            print(f"     * 有摘要: 剩余 {stage2_remaining_with_abstract} 篇 | 再过滤 {stage2_empty_with_abstract} 篇 ({stage2_empty_with_abstract/stage1_remaining_with_abstract*100:.1f}%)" if stage1_remaining_with_abstract > 0 else "     * 有摘要: 0 篇")
            print(f"     * 无摘要: 剩余 {stage2_remaining_without_abstract} 篇 | 再过滤 {stage2_empty_without_abstract} 篇 ({stage2_empty_without_abstract/stage1_remaining_without_abstract*100:.1f}%)" if stage1_remaining_without_abstract > 0 else "     * 无摘要: 0 篇")
            if _filtered_paper_ids['stage2_empty']:
                print(f"     * 被过滤的论文ID: {_filtered_paper_ids['stage2_empty']}")
            
            # 阶段3统计
            stage3_empty_with_abstract = _extract_debug_count_by_abstract['stage3_empty_with_abstract']
            stage3_empty_without_abstract = _extract_debug_count_by_abstract['stage3_empty_without_abstract']
            stage3_remaining_with_abstract = stage2_remaining_with_abstract - stage3_empty_with_abstract
            stage3_remaining_without_abstract = stage2_remaining_without_abstract - stage3_empty_without_abstract
            print(f"   - 阶段3（结构化）后:")
            print(f"     * 有摘要: 剩余 {stage3_remaining_with_abstract} 篇 | 再过滤 {stage3_empty_with_abstract} 篇 ({stage3_empty_with_abstract/stage2_remaining_with_abstract*100:.1f}%)" if stage2_remaining_with_abstract > 0 else "     * 有摘要: 0 篇")
            print(f"     * 无摘要: 剩余 {stage3_remaining_without_abstract} 篇 | 再过滤 {stage3_empty_without_abstract} 篇 ({stage3_empty_without_abstract/stage2_remaining_without_abstract*100:.1f}%)" if stage2_remaining_without_abstract > 0 else "     * 无摘要: 0 篇")
            if _filtered_paper_ids['stage3_empty']:
                print(f"     * 被过滤的论文ID: {_filtered_paper_ids['stage3_empty']}")
            
            # 阶段5统计
            stage5_empty_with_abstract = _extract_debug_count_by_abstract['stage5_empty_with_abstract']
            stage5_empty_without_abstract = _extract_debug_count_by_abstract['stage5_empty_without_abstract']
            stage5_remaining_with_abstract = stage3_remaining_with_abstract - stage5_empty_with_abstract
            stage5_remaining_without_abstract = stage3_remaining_without_abstract - stage5_empty_without_abstract
            print(f"   - 阶段5（规范化）后:")
            print(f"     * 有摘要: 剩余 {stage5_remaining_with_abstract} 篇 | 再过滤 {stage5_empty_with_abstract} 篇 ({stage5_empty_with_abstract/stage3_remaining_with_abstract*100:.1f}%)" if stage3_remaining_with_abstract > 0 else "     * 有摘要: 0 篇")
            print(f"     * 无摘要: 剩余 {stage5_remaining_without_abstract} 篇 | 再过滤 {stage5_empty_without_abstract} 篇 ({stage5_empty_without_abstract/stage3_remaining_without_abstract*100:.1f}%)" if stage3_remaining_without_abstract > 0 else "     * 无摘要: 0 篇")
            if _filtered_paper_ids['stage5_empty']:
                print(f"     * 被过滤的论文ID: {_filtered_paper_ids['stage5_empty']}")
            
            # 最终保留率
            print(f"   - 最终保留率:")
            print(f"     * 有摘要: {stage5_remaining_with_abstract/total_with_abstract*100:.1f}%" if total_with_abstract > 0 else "     * 有摘要: N/A")
            print(f"     * 无摘要: {stage5_remaining_without_abstract/total_without_abstract*100:.1f}%" if total_without_abstract > 0 else "     * 无摘要: N/A")

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

    nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])
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
    print(f"📊 最终统计:")
    print(f"   - 总论文数: {total_papers:,} 篇 (跳过: {skipped_papers:,})")
    print(f"   - 总观点数: {opinion_index._get_meta_count():,} 个")
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