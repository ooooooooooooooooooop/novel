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
from tqdm import tqdm
from sentence_transformers import SentenceTransformer
import pyarrow as pa
import pyarrow.parquet as pq

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

# =========================
# 配置区
# =========================
INPUT_CSV = "2025外文论文全字段.csv"
OUTPUT_BASE_DIR = Path("output_5_concept_cooccurrence")
OUTPUT_BASE_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = OUTPUT_BASE_DIR / "stage1_concept_extraction"
OUTPUT_DIR.mkdir(exist_ok=True)
OUT_MENTIONS_DIR = OUTPUT_DIR / "mentions_by_year"
OUT_MENTIONS_DIR.mkdir(exist_ok=True)
OUT_CONCEPTS = str(OUTPUT_DIR / "concepts_catalog_streaming.parquet")
CHECKPOINT_DIR = OUTPUT_DIR / "checkpoints_streaming"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS_DB = str(CHECKPOINT_DIR / "paper_progress.db")

# 流式参数
CHUNK_SIZE = 50_000
PAPERS_PER_MICROBATCH = 2000
CHECKPOINT_EVERY_MICROBATCH = 5
CHECKPOINT_EVERY_SECONDS = 120
PARQUET_WRITE_BATCH_SIZE = 20
PARQUET_AUTO_FLUSH_SECONDS = 300

# 嵌入/缓存（优化参数）
EMB_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_BATCH_SIZE = 8192
EMBED_CACHE_SIZE = 800_000
SQLITE_CACHE_PATH = str(OUTPUT_DIR / "embed_cache.sqlite")
LMDB_META_PATH = str(OUTPUT_DIR / "concept_meta.lmdb")
RAW_EMBEDDING_PATH = str(OUTPUT_DIR / "raw_embeddings.lmdb")
SQLITE_BATCH_SIZE = 10000

# 候选与筛选（保持质量参数）
N_TOP_CANDIDATES = 20
N_TOP_CONCEPTS = 4
SIM_THRESHOLD = 0.83
CLUSTER_THRESHOLD = 0.80
ALIAS_LIMIT = 20
FAISS_SEARCH_K = 3  # 增加搜索候选数，提高匹配率

# YAKE（保持质量参数）
YAKE_DEDUP_FUNC = "jaro"
YAKE_DEDUP_LIM = 0.9
YAKE_TOP = 15
YAKE_MAX_CHARS = 1500
YAKE_MAX_WINDOWS = 4
YAKE_WINDOW_SIZE = 2
YAKE_PER_WINDOW_TOP = 3

# spaCy（优化批量）
SPACY_BATCH_SIZE = 1024
SPACY_N_PROCESS = 1

# FAISS索引
USE_HNSW = True
HNSW_M = 32
HNSW_EF_SEARCH = 80
HNSW_EF_CONSTRUCTION = 120

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
RAW_EMBEDDING_MAP_SIZE = 100 * 1024 * 1024 * 1024  # 100GB 默认映射

# 向量压缩
USE_VECTOR_COMPRESSION = True
COMPRESSION_METHOD = "PCA"
COMPRESSED_DIM = 256
PCA_TRAIN_SAMPLES = 100_000
ENABLE_PCA_AT_CONCEPTS = 1_000_000
ENABLE_PQ_AT_CONCEPTS = 5_000_000
TRAIN_PCA_IN_SAVE = False  # 是否在save()阶段触发PCA训练（默认关闭）

# =========================
# 简单Bloom Filter实现（如果pybloom不可用）
# =========================
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

# =========================
# 原始向量存储（LMDB持久化）
# =========================
class RawEmbeddingStore:
    def __init__(self, path: str, dim: int, map_size_bytes: int = 100 * 1024 * 1024 * 1024):
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
                return np.frombuffer(data, dtype='float32')
        else:
            val = self._store.get(cid)
            return val.copy() if val is not None else None

    def iterate(self):
        if self.enabled:
            with self.env.begin() as txn:
                cursor = txn.cursor()
                for key, value in cursor:
                    cid = struct.unpack('>Q', key)[0]
                    yield cid, np.frombuffer(value, dtype='float32')
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

# =========================
# 核心函数
# =========================
def normalize_text(t: str):
    return re.sub(r'\s+', ' ', (t or '').lower().strip().replace('-', ' '))

@lru_cache(maxsize=200_000)
def normalize_text_cached(t: str):
    return normalize_text(t)

# 泛用短语模式（保持质量判断）
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
    return len(n) <= 2 or any(rgx.match(n) for rgx in GENERIC_RE)

def adaptive_threshold(phrase: str, base=CLUSTER_THRESHOLD):
    n_tok = len(normalize_text_cached(phrase).split())
    if n_tok <= 2: return min(0.92, base + 0.07)
    if n_tok >= 6: return max(0.75, base - 0.05)
    return base

# =========================
# 修复的嵌入缓存（线程安全）
# =========================
class TwoLevelEmbCache:
    def __init__(self, dim: int):
        self.dim = dim
        self.store = OrderedDict()
        self.hits = self.total = 0
        self._lock = threading.Lock()
        
        # SQLite连接（必须先建立）
        self.conn = sqlite3.connect(SQLITE_CACHE_PATH, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("CREATE TABLE IF NOT EXISTS emb (k TEXT PRIMARY KEY, v BLOB)")
        self.conn.commit()
        
        # Bloom Filter（如果启用）- 必须在SQLite连接建立后初始化
        self.bloom = None
        if USE_BLOOM_FILTER:
            if HAS_PYBLOOM:
                self.bloom = BloomFilter(capacity=BLOOM_CAPACITY, error_rate=BLOOM_ERROR_RATE)
            else:
                self.bloom = SimpleBloomFilter(capacity=BLOOM_CAPACITY, error_rate=BLOOM_ERROR_RATE)
            # 从SQLite加载已有key到Bloom Filter
            self._load_bloom_from_sqlite()
        
        # 使用队列 + 专用写线程确保线程安全
        self.write_queue = queue.Queue()
        self.write_thread = threading.Thread(target=self._write_worker, daemon=True)
        self.write_thread.start()
        self._shutdown = False
    
    def _load_bloom_from_sqlite(self):
        """从SQLite加载已有key到Bloom Filter"""
        if not self.bloom:
            return
        try:
            cur = self.conn.execute("SELECT k FROM emb")
            for row in cur:
                self.bloom.add(row[0])
        except Exception as e:
            print(f"Warning: Failed to load Bloom Filter from SQLite: {e}")

    def _write_worker(self):
        """专用写线程，保证SQLite操作串行化"""
        batch = []
        while True:
            try:
                # 阻塞等待任务，或者超时批量写入
                item = self.write_queue.get(timeout=1.0)
                
                if item is None:  # 关闭信号
                    if batch:
                        self._write_batch_safe(batch)
                    self.write_queue.task_done()
                    break
                
                batch.append(item)
                self.write_queue.task_done()
                
                # 达到批量大小时写入
                if len(batch) >= SQLITE_BATCH_SIZE:
                    self._write_batch_safe(batch)
                    batch = []
                    
            except queue.Empty:
                # 超时时如果有数据就写入
                if batch:
                    self._write_batch_safe(batch)
                    batch = []
            except Exception as e:
                print(f"Write worker error: {e}")

    def _write_batch_safe(self, batch):
        """线程安全的批量写入"""
        try:
            self.conn.executemany("INSERT OR REPLACE INTO emb(k,v) VALUES(?,?)", batch)
            self.conn.commit()
        except Exception as e:
            print(f"SQLite write error: {e}")

    def get(self, key_norm: str):
        self.total += 1
        
        # 内存缓存（线程安全）
        with self._lock:
            if key_norm in self.store:
                self.store.move_to_end(key_norm)
                self.hits += 1
                return self.store[key_norm]
        
        # Bloom Filter预检查（如果启用）
        if self.bloom and key_norm not in self.bloom:
            return None
        
        # SQLite缓存
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
        
        # 更新Bloom Filter
        if self.bloom:
            self.bloom.add(key_norm)
        
        # 更新内存缓存
        with self._lock:
            self.store[key_norm] = vec
            self.store.move_to_end(key_norm)
            if len(self.store) > EMBED_CACHE_SIZE:
                self.store.popitem(last=False)
        
        # 异步写入SQLite
        blob = zlib.compress(vec.astype(np.float16).tobytes())
        try:
            self.write_queue.put((key_norm, blob), block=False)
        except queue.Full:
            print("Warning: SQLite write queue full, skipping cache write")

    def flush(self):
        """同步等待所有写入完成"""
        # 等待队列清空
        self.write_queue.join()

    def get_stats(self):
        return {'hit_rate': self.hits / max(1, self.total), 'cache_size': len(self.store)}

    def __del__(self):
        if not self._shutdown:
            self._shutdown = True
            try:
                self.write_queue.put(None)  # 关闭信号
                if self.write_thread.is_alive():
                    self.write_thread.join(timeout=5.0)
            except:
                pass



# =========================
# 优化的编码函数（带哈希去重）
# =========================
_microbatch_hash_set = set()

def reset_microbatch_hash_set():
    global _microbatch_hash_set
    _microbatch_hash_set.clear()

def _get_hash(text):
    normalized = normalize_text(text)
    if xxhash:
        return xxhash.xxh64(normalized.encode('utf-8')).intdigest()
    return hash(normalized)

def encode_with_cache(phrases, emb_model, cache):
    if not phrases:
        return np.zeros((0, cache.dim), dtype='float32')

    # 哈希去重：在微批内去重相同短语
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
        
        # 更新hash_set（用于跨microbatch的长期去重）
        for h in hash_to_unique_idx:
            _microbatch_hash_set.add(h)
        
        # 限制hash_set大小，避免内存无限增长
        if len(_microbatch_hash_set) > HASH_SET_SIZE:
            # 保留最近的一半
            items = list(_microbatch_hash_set)
            _microbatch_hash_set.clear()
            _microbatch_hash_set.update(items[-HASH_SET_SIZE//2:])
    else:
        unique_phrases = phrases
        phrase_to_unique_idx = list(range(len(phrases)))

    keys = [normalize_text_cached(p) for p in unique_phrases]
    vecs = [cache.get(k) for k in keys]
    misses_idx = [i for i, v in enumerate(vecs) if v is None]

    if misses_idx:
        to_encode = [unique_phrases[i] for i in misses_idx]
        
        # 按长度分组批量处理
        short_texts = [t for t in to_encode if len(t) <= 512]
        long_texts = [t for t in to_encode if len(t) > 512]
        
        all_new = []
        if short_texts:
            all_new.extend(_encode_batch(short_texts, emb_model, EMBED_BATCH_SIZE))
        if long_texts:
            all_new.extend(_encode_batch(long_texts, emb_model, EMBED_BATCH_SIZE // 4))
        
        for j, i in enumerate(misses_idx):
            vecs[i] = all_new[j]
            cache.put(keys[i], all_new[j])

    # 映射回原始顺序
    if USE_HASH_DEDUP and len(unique_phrases) < len(phrases):
        result_vecs = [vecs[idx] for idx in phrase_to_unique_idx]
        return np.stack(result_vecs, axis=0).astype('float32', copy=False)
    else:
        return np.stack(vecs, axis=0).astype('float32', copy=False)

def _encode_batch(texts, emb_model, batch_size):
    """批量编码，自适应OOM处理"""
    emb_model.eval()
    bs = batch_size
    all_vecs = []
    
    for start in range(0, len(texts), bs):
        batch = texts[start:start + bs]
        
        while True:
            try:
                with torch.no_grad():
                    vecs = emb_model.encode(
                        batch, convert_to_numpy=True, normalize_embeddings=True,
                        batch_size=min(bs, 1024), show_progress_bar=False
                    ).astype('float32', copy=False)
                all_vecs.append(vecs)
                break
            except RuntimeError as e:
                if "CUDA" in str(e).upper() and bs > 64:
                    bs //= 2
                    torch.cuda.empty_cache()
                    continue
                raise
    
    return np.vstack(all_vecs) if all_vecs else np.zeros((0, emb_model.get_sentence_embedding_dimension()), dtype='float32')

# =========================
# 向量压缩器（PCA + 预留PQ接口）
# =========================
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
        """使用样本向量训练PCA"""
        if not self.use_pca or self.trained:
            return
        
        vectors = np.asarray(vectors, dtype='float32')
        if len(vectors) < 2:
            return
        
        # 中心化
        self.mean = vectors.mean(axis=0)
        centered = vectors - self.mean
        
        # SVD分解
        U, s, Vt = np.linalg.svd(centered, full_matrices=False)
        
        # 保留前compressed_dim个主成分
        self.components = Vt[:self.compressed_dim].T
        self.trained = True
    
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
        
        # 如果输入是1D，返回1D
        if was_1d:
            return compressed.squeeze(0).astype('float32')
        return compressed.astype('float32')
    
    def save(self, path):
        """保存压缩器"""
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
        """加载压缩器"""
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

# =========================
# 修复的FAISS索引（改进搜索策略）
# =========================
class IncrementalConceptIndex:
    def __init__(self, emb_dim=384):
        self.original_emb_dim = emb_dim
        
        # LMDB元数据存储（如果启用）- 先初始化以便后续使用
        self.use_lmdb = USE_LMDB_META and lmdb
        if self.use_lmdb:
            Path(LMDB_META_PATH).parent.mkdir(parents=True, exist_ok=True)
            self.lmdb_env = lmdb.open(LMDB_META_PATH, map_size=10*1024*1024*1024, readonly=False)
            self.meta_cache = OrderedDict()
        else:
            self.meta = {}
            self.lmdb_env = None
        
        # 原始向量存储（如果启用压缩）- 先初始化，因为后续判断需要用到
        self.raw_store = None
        if USE_VECTOR_COMPRESSION:
            self.raw_store = RawEmbeddingStore(RAW_EMBEDDING_PATH, emb_dim, RAW_EMBEDDING_MAP_SIZE)
        
        # 向量压缩器
        self.compressor = None
        self.compressed_dim = emb_dim
        if USE_VECTOR_COMPRESSION:
            compressor_path = CHECKPOINT_DIR / "vector_compressor.json"
            self.compressor = VectorCompressor.load(str(compressor_path))
            if self.compressor and self.compressor.trained:
                self.compressed_dim = self.compressor.compressed_dim
            elif self.raw_store and self.raw_store.count() >= ENABLE_PCA_AT_CONCEPTS:
                # 如果raw_store中已有足够向量，创建compressor（将在下次flush时训练）
                self.compressor = VectorCompressor(
                    original_dim=emb_dim,
                    compressed_dim=COMPRESSED_DIM,
                    use_pca=True
                )
        
        # FAISS索引（使用压缩后的维度）
        index_dim = self.compressed_dim
        base = faiss.IndexHNSWFlat(index_dim, HNSW_M) if USE_HNSW else faiss.IndexFlatIP(index_dim)
        if USE_HNSW:
            base.hnsw.efSearch = HNSW_EF_SEARCH
            base.hnsw.efConstruction = HNSW_EF_CONSTRUCTION
        
        self.index = faiss.IndexIDMap(base)
        self.next_id = 0
        
        # 批量插入缓冲（只保存cid，向量从raw_store读取）
        self.pending_ids = []
        self.pending_meta = []
    
    def _get_meta_count(self):
        """获取元数据数量"""
        if self.use_lmdb:
            try:
                with self.lmdb_env.begin() as txn:
                    return txn.stat()['entries']
            except:
                return 0
        else:
            return len(self.meta) if hasattr(self, 'meta') else 0
    
    def _get_meta(self, cid):
        """获取元数据（带LRU缓存）"""
        if self.use_lmdb:
            # 先查缓存
            if cid in self.meta_cache:
                self.meta_cache.move_to_end(cid)
                return self.meta_cache[cid]
            
            # 从LMDB读取
            with self.lmdb_env.begin() as txn:
                key = str(cid).encode()
                val = txn.get(key)
                if val:
                    if msgpack:
                        meta = msgpack.unpackb(val, raw=False)
                    else:
                        meta = json.loads(val.decode())
                    # 重建alias_norm_set
                    meta['alias_norm_set'] = {normalize_text(a) for a in meta.get('aliases', [])}
                    # 加入缓存
                    self.meta_cache[cid] = meta
                    self.meta_cache.move_to_end(cid)
                    if len(self.meta_cache) > LMDB_META_CACHE_SIZE:
                        self.meta_cache.popitem(last=False)
                    return meta
            return None
        else:
            return self.meta.get(cid)
    
    def _set_meta(self, cid, meta):
        """设置元数据"""
        if self.use_lmdb:
            # 更新缓存
            self.meta_cache[cid] = meta
            self.meta_cache.move_to_end(cid)
            if len(self.meta_cache) > LMDB_META_CACHE_SIZE:
                self.meta_cache.popitem(last=False)
            
            # 异步写入LMDB（批量）
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
                # 序列化（排除alias_norm_set，它是Python set）
                meta_serializable = {k: v for k, v in meta.items() if k != 'alias_norm_set'}
                key = str(cid).encode()
                if msgpack:
                    val = msgpack.packb(meta_serializable, use_bin_type=True)
                else:
                    val = json.dumps(meta_serializable, ensure_ascii=False).encode()
                txn.put(key, val)
        self.pending_meta.clear()

    def add(self, concept_text, embedding, year, aliases):
        cid = self.next_id
        self.next_id += 1
        
        # 保存原始向量到raw_store（如果启用压缩）
        if self.raw_store:
            self.raw_store.put(cid, embedding)
        
        meta = {
            'concept_text': normalize_text(concept_text),
            'canonical_label': concept_text,
            'first_seen_year': int(year) if pd.notna(year) else None,
            'aliases': list(dict.fromkeys(aliases)),
            'alias_norm_set': {normalize_text(a) for a in aliases}
        }
        self._set_meta(cid, meta)
        
        # 批量插入（只保存cid，向量从raw_store读取）
        self.pending_ids.append(cid)
        
        if len(self.pending_ids) >= 100:
            self._flush_pending()
        
        return cid

    def _flush_pending(self):
        if not self.pending_ids:
            return
        
        # 从raw_store读取原始向量
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
            # fallback：如果没有raw_store，无法压缩（不应该发生）
            print("Warning: No raw_store available, skipping flush")
            self.pending_ids.clear()
            return
        
        # 检查是否需要训练PCA
        if self.compressor and not self.compressor.trained:
            total_count = self.raw_store.count()
            if total_count >= ENABLE_PCA_AT_CONCEPTS:
                # 保存当前pending_ids（重建时会包含它们）
                pending_before_rebuild = self.pending_ids.copy()
                self._train_compressor_and_rebuild()
                # 重建索引时已经包含了所有向量（包括pending的），所以清空pending_ids
                self.pending_ids.clear()
                self._flush_meta()
                return
        
        # 压缩向量（如果压缩器已训练）
        if self.compressor and self.compressor.trained:
            vecs = self.compressor.compress(vecs)
        
        # 检查索引维度是否匹配
        if self.index.d != vecs.shape[1]:
            print(f"Error: Index dimension mismatch ({self.index.d} vs {vecs.shape[1]})")
            self.pending_ids.clear()
            return
        
        # 插入到索引
        self.index.add_with_ids(vecs, ids)
        self.pending_ids.clear()
        self._flush_meta()
    
    def _train_compressor_and_rebuild(self):
        """训练PCA压缩器并重建索引"""
        if not self.raw_store or not self.compressor:
            return
        
        print(f"Starting PCA training and index rebuild...")
        
        # 收集训练样本
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
        
        # 保存压缩器
        compressor_path = CHECKPOINT_DIR / "vector_compressor.json"
        self.compressor.save(str(compressor_path))
        print(f"PCA trained: {self.original_emb_dim} -> {self.compressed_dim} dims")
        
        # 重建索引
        self._rebuild_index_with_compression()
    
    def _rebuild_index_with_compression(self):
        """使用压缩后的向量重建索引"""
        if not self.raw_store or not self.compressor or not self.compressor.trained:
            return
        
        print(f"Rebuilding index with compression...")
        
        # 创建新索引
        base = faiss.IndexHNSWFlat(self.compressed_dim, HNSW_M) if USE_HNSW else faiss.IndexFlatIP(self.compressed_dim)
        if USE_HNSW:
            base.hnsw.efSearch = HNSW_EF_SEARCH
            base.hnsw.efConstruction = HNSW_EF_CONSTRUCTION
        new_index = faiss.IndexIDMap(base)
        
        # 批量重建：读取所有原始向量，压缩后插入
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
        
        # 处理最后一批
        if batch_vecs:
            vecs_array = np.stack(batch_vecs, axis=0).astype('float32')
            ids_array = np.array(batch_ids, dtype=np.int64)
            new_index.add_with_ids(vecs_array, ids_array)
            total_rebuilt += len(batch_ids)
        
        # 替换索引
        self.index = new_index
        print(f"Index rebuild complete: {total_rebuilt} vectors")

    def search(self, embedding, threshold=None):
        """改进的搜索策略：查询top-k，返回第一个满足阈值的"""
        self._flush_pending()
        
        if self.index.ntotal == 0:
            return None, None
        
        # 压缩查询向量（如果启用）
        if self.compressor and self.compressor.trained:
            embedding = self.compressor.compress(embedding)
        
        # 查询更多候选，提高匹配率
        k = min(FAISS_SEARCH_K, self.index.ntotal)
        D, I = self.index.search(np.array([embedding], dtype='float32'), k)
        
        # 找第一个满足阈值的候选
        for i in range(k):
            sim, cid = float(D[0][i]), int(I[0][i])
            if threshold is None or sim >= threshold:
                return cid, sim
        
        return None, None

    def batch_search(self, embeddings, thresholds=None):
        """批量搜索多个向量
        
        Args:
            embeddings: np.ndarray, shape=(N, dim)
            thresholds: list[float] or None, 长度为N的阈值列表
        
        Returns:
            list[(cid, sim)], 长度为N，每个元素是(concept_id, similarity)或(None, None)
        """
        self._flush_pending()
        
        if self.index.ntotal == 0:
            return [(None, None)] * len(embeddings)
        
        if len(embeddings) == 0:
            return []
        
        embeddings = np.asarray(embeddings, dtype='float32')
        
        # 压缩查询向量（如果启用）
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
        
        # 检查是否需要训练PCA（在保存前）
        if TRAIN_PCA_IN_SAVE and self.compressor and not self.compressor.trained and self.raw_store:
            total_count = self.raw_store.count()
            if total_count >= ENABLE_PCA_AT_CONCEPTS:
                self._train_compressor_and_rebuild()
        
        faiss_path = CHECKPOINT_DIR / f"{base_name}.faiss"
        faiss.write_index(self.index, str(faiss_path))
        
        # 保存压缩器
        if self.compressor and self.compressor.trained:
            compressor_path = CHECKPOINT_DIR / "vector_compressor.json"
            self.compressor.save(str(compressor_path))
        
        # 保存元数据索引（如果使用LMDB，元数据已在LMDB中）
        if not self.use_lmdb:
            meta_data = {
                'next_id': self.next_id,
                'meta': {str(cid): {k: v for k, v in rec.items() if k != 'alias_norm_set'} 
                        for cid, rec in self.meta.items()}
            }
            json_path = CHECKPOINT_DIR / f"{base_name}.json"
            json_path.write_text(json.dumps(meta_data, ensure_ascii=False), encoding='utf-8')
        else:
            # 仅保存next_id
            meta_data = {'next_id': self.next_id}
            json_path = CHECKPOINT_DIR / f"{base_name}.json"
            json_path.write_text(json.dumps(meta_data, ensure_ascii=False), encoding='utf-8')
        
        # raw_store 使用 LMDB，会自动持久化，无需额外保存

    @staticmethod
    def load(emb_dim=384, base_name="concept_index"):
        faiss_path = CHECKPOINT_DIR / f"{base_name}.faiss"
        json_path = CHECKPOINT_DIR / f"{base_name}.json"
        
        if faiss_path.exists() and json_path.exists():
            obj = IncrementalConceptIndex(emb_dim)
            
            # 先加载压缩器（影响索引维度）
            compressor_path = CHECKPOINT_DIR / "vector_compressor.json"
            if compressor_path.exists():
                obj.compressor = VectorCompressor.load(str(compressor_path))
                if obj.compressor and obj.compressor.trained:
                    obj.compressed_dim = obj.compressor.compressed_dim
            
            # 加载FAISS索引
            obj.index = faiss.read_index(str(faiss_path))
            
            # 验证索引维度是否匹配
            if obj.compressor and obj.compressor.trained:
                if obj.index.d != obj.compressed_dim:
                    print(f"Warning: Index dimension ({obj.index.d}) doesn't match compressor ({obj.compressed_dim})")
                    print("  This may indicate index needs rebuild. Checking raw_store...")
                    if obj.raw_store and obj.raw_store.count() > 0:
                        print("  Raw vectors found, rebuilding index...")
                        obj._rebuild_index_with_compression()
            
            data = json.loads(json_path.read_text(encoding='utf-8'))
            obj.next_id = data.get('next_id', 0)
            
            # 加载元数据（如果使用LMDB，元数据已在LMDB中；否则从JSON加载）
            if not obj.use_lmdb:
                for cid_str, rec in data.get('meta', {}).items():
                    cid = int(cid_str)
                    obj.meta[cid] = {
                        **rec,
                        'alias_norm_set': {normalize_text(a) for a in rec.get('aliases', [])}
                    }
            
            # raw_store 使用 LMDB，会自动从磁盘加载，无需额外操作
            
            return obj
        
        return IncrementalConceptIndex(emb_dim)

# =========================
# 进度管理
# =========================
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
            year = getattr(row, 'year', None) or ''
            combined = f"{title}|{year}".strip()
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

# =========================
# 概念抽取核心逻辑（保持质量）
# =========================
# 全局YAKE提取器（避免重复初始化）
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
                if 3 <= len(phrase) <= 80:
                    phrases.append(phrase)
                buf = []
    if buf:
        phrase = " ".join(buf).strip()
        if 3 <= len(phrase) <= 80:
            phrases.append(phrase)
    return phrases

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
        except:
            continue
        if len(merged) >= YAKE_TOP:
            break
    return merged

def select_top_concepts_from_embeddings(candidates, embeddings):
    """保持完全相同的概念选择逻辑"""
    valid_indices = [i for i, c in enumerate(candidates) if not is_generic_phrase(c)]
    if not valid_indices:
        return []
    
    valid_candidates = [candidates[i] for i in valid_indices]
    valid_embeddings = embeddings[valid_indices]
    n = len(valid_candidates)
    
    if n == 1:
        return [(valid_candidates[0], valid_embeddings[0])]

    # 聚类
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

    if len(representatives) <= N_TOP_CONCEPTS:
        return list(zip(representatives, rep_embs))

    # 中心性排序
    rep_embs = np.stack(rep_embs)
    R = rep_embs @ rep_embs.T
    centrality = (R.sum(axis=1) - 1.0) / (len(representatives) - 1)
    top_idx = np.argsort(-centrality)[:N_TOP_CONCEPTS]
    return [(representatives[i], rep_embs[i]) for i in top_idx]

# =========================
# 分年Parquet写入器
# =========================
class YearlyParquetWriter:
    def __init__(self, output_dir: Path, schema: pa.Schema, buffer_size: int = PARQUET_WRITE_BATCH_SIZE, auto_flush_seconds: int = PARQUET_AUTO_FLUSH_SECONDS):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.schema = schema
        self.buffer_size = buffer_size
        self.auto_flush_seconds = auto_flush_seconds
        self.write_buffers = {}
        self.writers = {}
        self.index_file = self.output_dir / "index.json"
        self.index = self._load_index()
        self.last_flush_times = {}
    
    def _load_index(self):
        if self.index_file.exists():
            data = json.loads(self.index_file.read_text(encoding='utf-8'))
            return data.get('years', {})
        return {}
    
    def _save_index(self):
        index_data = {
            'years': self.index,
            'updated_at': time.time()
        }
        self.index_file.write_text(json.dumps(index_data, indent=2), encoding='utf-8')
    
    def _get_year_key(self, year):
        if pd.isna(year) or year is None:
            return 'unknown'
        return int(year)
    
    def write_batch(self, df: pd.DataFrame):
        if df.empty:
            return
        
        if 'year' not in df.columns:
            year_key = 'unknown'
        else:
            year_groups = df.groupby(df['year'].apply(self._get_year_key))
            for year_key, year_df in year_groups:
                if year_key not in self.write_buffers:
                    self.write_buffers[year_key] = []
                    self.last_flush_times[year_key] = time.time()
                
                self.write_buffers[year_key].append(year_df)
                
                should_flush = False
                if len(self.write_buffers[year_key]) >= self.buffer_size:
                    should_flush = True
                elif self.auto_flush_seconds > 0 and time.time() - self.last_flush_times[year_key] >= self.auto_flush_seconds:
                    should_flush = True
                
                if should_flush:
                    self._flush_year_buffer(year_key)
            return
        
        if 'unknown' not in self.write_buffers:
            self.write_buffers['unknown'] = []
            self.last_flush_times['unknown'] = time.time()
        
        self.write_buffers['unknown'].append(df)
        
        should_flush = False
        if len(self.write_buffers['unknown']) >= self.buffer_size:
            should_flush = True
        elif self.auto_flush_seconds > 0 and time.time() - self.last_flush_times['unknown'] >= self.auto_flush_seconds:
            should_flush = True
        
        if should_flush:
            self._flush_year_buffer('unknown')
    
    def _flush_year_buffer(self, year_key):
        if year_key not in self.write_buffers or not self.write_buffers[year_key]:
            return
        
        combined_df = pd.concat(self.write_buffers[year_key], ignore_index=True)
        year_file = self.output_dir / f"{year_key}_mentions.parquet"
        
        if year_file.exists() and str(year_key) in self.index:
            existing_df = pd.read_parquet(year_file)
            combined_df = pd.concat([existing_df, combined_df], ignore_index=True)
            combined_df.to_parquet(year_file, index=False, compression='snappy')
        else:
            combined_df.to_parquet(year_file, index=False, compression='snappy')
        
        self.index[str(year_key)] = {
            'file': str(year_file),
            'count': len(combined_df),
            'updated_at': time.time()
        }
        self._save_index()
        
        self.write_buffers[year_key].clear()
        self.last_flush_times[year_key] = time.time()
    
    def _flush_buffer(self):
        for year_key in list(self.write_buffers.keys()):
            self._flush_year_buffer(year_key)
    
    def flush(self):
        self._flush_buffer()
        self._save_index()

# =========================
# Meta更新缓冲区
# =========================
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
        in_title = phrase.lower() in title.lower()
        phrase_len = len(phrase)
        
        if cid not in self.label_buffer:
            self.label_buffer[cid] = (phrase, phrase_len, in_title)
        else:
            _, old_len, old_in_title = self.label_buffer[cid]
            if in_title and (not old_in_title or phrase_len > old_len):
                self.label_buffer[cid] = (phrase, phrase_len, in_title)
            elif not old_in_title and phrase_len > old_len:
                self.label_buffer[cid] = (phrase, phrase_len, in_title)
    
    def flush_to_index(self, concept_index):
        for cid, aliases in self.alias_buffer.items():
            meta = concept_index._get_meta(cid)
            if meta is None:
                continue
            for phrase in aliases:
                norm_phrase = normalize_text(phrase)
                if norm_phrase not in meta['alias_norm_set']:
                    meta['aliases'].append(phrase)
                    meta['alias_norm_set'].add(norm_phrase)
            if len(meta['aliases']) > ALIAS_LIMIT:
                meta['aliases'] = meta['aliases'][:ALIAS_LIMIT]
            concept_index._set_meta(cid, meta)
        
        for cid, year in self.year_buffer.items():
            meta = concept_index._get_meta(cid)
            if meta is None:
                continue
            if meta['first_seen_year'] is None:
                meta['first_seen_year'] = year
            else:
                meta['first_seen_year'] = min(meta['first_seen_year'], year)
            concept_index._set_meta(cid, meta)
        
        for cid, (phrase, phrase_len, in_title) in self.label_buffer.items():
            meta = concept_index._get_meta(cid)
            if meta is None:
                continue
            if in_title and phrase_len > len(meta['canonical_label']):
                meta['canonical_label'] = phrase
            concept_index._set_meta(cid, meta)
        
        self.clear()
    
    def clear(self):
        self.alias_buffer.clear()
        self.year_buffer.clear()
        self.label_buffer.clear()
    
    def size(self):
        return len(self.alias_buffer) + len(self.year_buffer) + len(self.label_buffer)

# =========================
# 微批处理
# =========================
def process_microbatch(rows, nlp, emb_model, cache, concept_index, meta_buffer):
    if USE_HASH_DEDUP:
        reset_microbatch_hash_set()
    
    # 预处理文本
    texts = []
    for r in rows:
        title = getattr(r, 'title', '') or ''
        abstract = getattr(r, 'abstract', '') or ''
        combined = f"{title} {abstract}".strip()
        # 截断过长文本
        if len(combined) > 8192:
            combined = combined[:8192]
        texts.append(combined)

    # spaCy处理
    docs = list(nlp.pipe(texts, batch_size=SPACY_BATCH_SIZE, n_process=SPACY_N_PROCESS))

    # 生成候选
    all_candidates = []
    for row, doc in zip(rows, docs):
        yake_terms = extract_yake_windowed(doc)
        noun_phrases = extract_lightweight_np(doc)
        
        keywords = getattr(row, 'keywords', '') or ''
        keywords_list = []
        if isinstance(keywords, str) and keywords.strip():
            for phrase in re.split(r"[;,/|]", keywords):
                phrase = phrase.strip()
                if phrase:
                    keywords_list.append(phrase)

        q1, q2 = N_TOP_CANDIDATES // 3, N_TOP_CANDIDATES // 3
        q3 = N_TOP_CANDIDATES - q1 - q2
        
        merged, seen = [], set()
        for src in (yake_terms[:q1], noun_phrases[:q2], keywords_list[:q3]):
            for x in src:
                if len(merged) >= N_TOP_CANDIDATES or not x or x in seen:
                    continue
                merged.append(x)
                seen.add(x)
        
        all_candidates.append(merged)

    # 批量编码
    flat_candidates = [c for cs in all_candidates for c in cs]
    if flat_candidates:
        all_embeddings = encode_with_cache(flat_candidates, emb_model, cache)
    else:
        all_embeddings = np.zeros((0, cache.dim), dtype='float32')

    # 收集所有论文的top_concepts
    paper_concepts = []
    offset = 0
    
    for row, candidates in zip(rows, all_candidates):
        n = len(candidates)
        if n == 0:
            paper_concepts.append([])
            continue
        
        emb_slice = all_embeddings[offset:offset+n]
        offset += n

        top_concepts = select_top_concepts_from_embeddings(candidates, emb_slice)
        paper_concepts.append(top_concepts)
    
    # 批量收集所有向量和阈值
    all_batch_vecs = []
    all_batch_thresholds = []
    
    for top_concepts in paper_concepts:
        if not top_concepts:
            continue
        for phrase, vec in top_concepts:
            all_batch_vecs.append(vec)
            all_batch_thresholds.append(adaptive_threshold(phrase))
    
    # 一次性批量搜索所有概念
    if all_batch_vecs:
        all_batch_vecs = np.stack(all_batch_vecs)
        batch_search_results = concept_index.batch_search(all_batch_vecs, all_batch_thresholds)
    else:
        batch_search_results = []
    
    # 匹配回论文并处理
    mentions = []
    result_idx = 0
    
    for paper_idx, (row, top_concepts) in enumerate(zip(rows, paper_concepts)):
        if not top_concepts:
            continue
        
        year = getattr(row, 'year', None)
        
        for phrase, vec in top_concepts:
            cid, sim = batch_search_results[result_idx]
            result_idx += 1
            
            if cid is None:
                cid = concept_index.add(phrase, vec, year, [phrase])
            else:
                meta_buffer.record_alias(cid, phrase)
                
                if year is not None:
                    meta_buffer.record_year(cid, int(year))
                
                title = getattr(row, 'title', '') or ''
                if title:
                    meta_buffer.record_label(cid, phrase, title)

            meta = concept_index._get_meta(cid)
            mentions.append({
                'concept_id': cid,
                'concept_text': meta['concept_text'],
                'canonical_label': meta['canonical_label'],
                'first_seen_year': meta['first_seen_year'],
                'alias': phrase,
                'paper_id': getattr(row, 'paper_id', None),
                'year': getattr(row, 'year', None)
            })
    
    return mentions

# =========================
# 主流程
# =========================
def process_streaming_csv():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    emb_model = SentenceTransformer(EMB_MODEL, device=device)
    emb_dim = emb_model.get_sentence_embedding_dimension()
    print(f"Using device: {device}, embedding dim: {emb_dim}")

    cache = TwoLevelEmbCache(dim=emb_dim)
    concept_index = IncrementalConceptIndex.load(emb_dim, "concept_index")
    meta_buffer = MetaUpdateBuffer()
    paper_tracker = PaperProgressTracker(PROGRESS_DB)
    
    processed_count = paper_tracker.get_count()
    if processed_count > 0:
        print(f"📂 检测到已处理 {processed_count} 篇论文，将跳过已处理论文")

    nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])
    nlp.add_pipe("sentencizer")
    nlp.max_length = 2_000_000

    mentions_schema = pa.schema([
        ('concept_id', pa.int64()),
        ('concept_text', pa.string()),
        ('canonical_label', pa.string()),
        ('first_seen_year', pa.int64()),
        ('alias', pa.string()),
        ('paper_id', pa.string()),
        ('year', pa.int64())
    ])
    
    mentions_writer = YearlyParquetWriter(OUT_MENTIONS_DIR, mentions_schema)

    usecols = ['入藏号', '标题', '摘要', '关键词', '出版年']
    dtype = {'入藏号': 'string', '标题': 'string', '摘要': 'string', '关键词': 'string', '出版年': 'Int64'}
    
    reader = pd.read_csv(INPUT_CSV, usecols=usecols, dtype=dtype, chunksize=CHUNK_SIZE,
                        encoding_errors="ignore", on_bad_lines='skip', keep_default_na=False)

    microbatch_buffer = []
    microbatch_count = 0
    total_papers = processed_count
    skipped_papers = 0
    last_checkpoint = time.time()
    pbar = tqdm(desc="Papers", unit="paper", mininterval=0.5, initial=processed_count)

    try:
        for chunk_idx, chunk in enumerate(reader, start=1):
            print(f"开始处理 chunk {chunk_idx}，微批大小 {PAPERS_PER_MICROBATCH}")
            chunk = chunk.rename(columns={
                '入藏号': 'paper_id', '标题': 'title', '摘要': 'abstract',
                '关键词': 'keywords', '出版年': 'year'
            }).fillna('')

            for row in chunk.itertuples(index=False):
                if paper_tracker.is_processed(row):
                    skipped_papers += 1
                    continue
                
                microbatch_buffer.append(row)
                
                if len(microbatch_buffer) >= PAPERS_PER_MICROBATCH:
                    count = len(microbatch_buffer)
                    mentions = process_microbatch(microbatch_buffer, nlp, emb_model, cache, concept_index, meta_buffer)
                    
                    for r in microbatch_buffer:
                        paper_tracker.mark_processed(r)
                    
                    if mentions:
                        df = pd.DataFrame(mentions)
                        mentions_writer.write_batch(df)
                    
                    pbar.update(count)
                    total_papers += count
                    microbatch_count += 1
                    microbatch_buffer = []

                    if (microbatch_count % CHECKPOINT_EVERY_MICROBATCH == 0 or 
                        time.time() - last_checkpoint > CHECKPOINT_EVERY_SECONDS):
                        meta_buffer.flush_to_index(concept_index)
                        mentions_writer.flush()
                        concept_index.save("concept_index")
                        cache.flush()
                        paper_tracker.flush()
                        # no-op
                        save_progress(total_papers)
                        last_checkpoint = time.time()
                        print(f"Checkpoint: {total_papers} papers ({skipped_papers} skipped), {concept_index._get_meta_count()} concepts")

        if microbatch_buffer:
            count = len(microbatch_buffer)
            mentions = process_microbatch(microbatch_buffer, nlp, emb_model, cache, concept_index, meta_buffer)
            
            for r in microbatch_buffer:
                paper_tracker.mark_processed(r)
            
            if mentions:
                df = pd.DataFrame(mentions)
                mentions_writer.write_batch(df)
            pbar.update(count)
            total_papers += count

    except KeyboardInterrupt:
        print("\n⚠️  Processing interrupted by user")
    except Exception as e:
        print(f"\n❌ Error during processing: {e}")
        raise
    finally:
        pbar.close()
        meta_buffer.flush_to_index(concept_index)
        concept_index._flush_pending()
        mentions_writer.flush()
        cache.flush()
        paper_tracker.flush()
        # no-op
        print("Cache flushed")

    # 输出概念目录
    if concept_index.use_lmdb:
        concepts_list = []
        with concept_index.lmdb_env.begin() as txn:
            cursor = txn.cursor()
            for key, val in cursor:
                cid = int(key.decode())
                if msgpack:
                    meta = msgpack.unpackb(val, raw=False)
                else:
                    meta = json.loads(val.decode())
                concepts_list.append({
                    'concept_id': cid,
                    'concept_text': meta['concept_text'],
                    'canonical_label': meta['canonical_label'],
                    'first_seen_year': meta['first_seen_year'],
                    'aliases': "; ".join(meta.get('aliases', []))
                })
        concepts_df = pd.DataFrame(concepts_list)
    else:
        concepts_df = pd.DataFrame([
            {
                'concept_id': cid,
                'concept_text': meta['concept_text'],
                'canonical_label': meta['canonical_label'],
                'first_seen_year': meta['first_seen_year'],
                'aliases': "; ".join(meta['aliases'])
            }
            for cid, meta in concept_index.meta.items()
        ])
    concepts_df.to_parquet(OUT_CONCEPTS, index=False)

    meta_buffer.flush_to_index(concept_index)
    concept_index._flush_pending()
    concept_index.save("concept_index")
    cache.flush()
    paper_tracker.flush()
    # no-op
    
    if concept_index.raw_store:
        concept_index.raw_store.close()
    if concept_index.use_lmdb and concept_index.lmdb_env:
        concept_index.lmdb_env.close()
    paper_tracker.close()
    # no-op
    clear_progress()

    print(f"\n✅ Processing complete!")
    print(f"Total papers: {total_papers} (skipped: {skipped_papers})")
    print(f"Total concepts: {concept_index._get_meta_count()}")
    print(f"Cache stats: {cache.get_stats()}")
    print(f"Output directory: {OUT_MENTIONS_DIR}")
    print(f"Concepts catalog: {OUT_CONCEPTS}")

def main():
    print("Starting optimized concept extraction...")
    process_streaming_csv()

if __name__ == "__main__":
    main()