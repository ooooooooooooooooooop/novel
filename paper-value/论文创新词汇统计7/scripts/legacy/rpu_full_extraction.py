# -*- coding: utf-8 -*-
"""
全量 RPU 抽取脚本

优化方案 A：
- 预筛选无摘要论文
- FP16 量化推理
- 大 batch_size
- SQLite 数据库存储
- WAL 机制保障
- 断点续跑

model_version: t5-rpu-v1.0
"""

import os
import sys
import csv
import json
import time
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

import torch
import numpy as np

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from project_config import load_project_config, get_paths

# ============================================================
# 冻结配置（一旦开始运行，不要修改）
# ============================================================
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_cfg = load_project_config()
_paths = get_paths(_cfg)


def _require_path(key: str) -> str:
    value = _paths.get(key)
    if value:
        return value
    raise KeyError(f"Missing required path key in project config: paths.{key}")


CONFIG = {
    # 输入（项目根 data/raw/）
    "input_csv": _require_path("raw_papers_csv_path"),
    
    # 输出
    "output_dir": _require_path("legacy_rpu_t5_output_dir"),
    "db_name": "rpu_database.db",
    
    # 模型
    "model_path": _require_path("research_structure_model_dir"),
    "model_version": "t5-rpu-v1.0",
    "device": "cuda" if torch.cuda.is_available() else "cpu",
    
    # 推理参数
    "max_input_length": 512,
    "max_output_length": 64,
    "batch_size": 256,               # 推理批次大小（建议测试 64/128/256，找到最优值）
    "use_fp16": True,               # FP16 量化
    
    # 批处理
    "paper_batch_size": 2000,       # 减小批次避免长时间GPU满载（原5000）
    "inference_delay": 0.1,         # 每N个推理批次后的延迟（秒）
    "db_commit_interval": 1000,     # 数据库提交间隔
    "wal_flush_interval": 500,      # WAL 刷新间隔
    
    # 监控阈值
    "max_rpu_per_paper": 20,        # 单篇论文 RPU 上限告警
    "max_json_error_rate": 0.10,    # JSON 解析错误率上限
    "max_empty_task_rate": 0.001,   # 空 Task 率上限
}

# ============================================================
# 日志配置
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(CONFIG["output_dir"], "extraction.log") 
            if os.path.exists(CONFIG["output_dir"]) 
            else "extraction.log",
            encoding='utf-8'
        )
    ]
)
logger = logging.getLogger(__name__)


# ============================================================
# 数据结构
# ============================================================
@dataclass
class RPU:
    paper_id: str
    sentence_index: int
    task: str
    object: str
    aspect: str
    context: str
    model_version: str


# ============================================================
# 数据库管理
# ============================================================
class DatabaseManager:
    """SQLite 数据库管理器"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None
        self._init_db()
    
    def _init_db(self):
        """初始化数据库表"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        # 使用更长的超时时间，并启用 WAL 模式
        self.conn = sqlite3.connect(self.db_path, timeout=120, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA cache_size=50000")
        self.conn.execute("PRAGMA temp_store=MEMORY")
        self.conn.execute("PRAGMA mmap_size=268435456")  # 256MB
        self.conn.execute("PRAGMA busy_timeout=30000")  # 30秒忙等待
        self.conn.execute("PRAGMA wal_autocheckpoint=100000")  # WAL 自动检查点（增大，减少自动检查点频率）
        
        # RPU 表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS rpu (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id TEXT NOT NULL,
                sentence_index INTEGER NOT NULL,
                task TEXT NOT NULL,
                object TEXT NOT NULL,
                aspect TEXT,
                context TEXT,
                model_version TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(paper_id, sentence_index)
            )
        """)
        
        # 状态表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_status (
                paper_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                rpu_count INTEGER DEFAULT 0,
                sentence_count INTEGER DEFAULT 0,
                error_msg TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 索引
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_rpu_paper_id ON rpu(paper_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON paper_status(status)")
        
        self.conn.commit()
        logger.info(f"数据库初始化完成: {self.db_path}")
    
    def init_paper_status(self, paper_ids: List[str]):
        """批量初始化论文状态（分批插入，避免锁定）"""
        batch_size = 100000  # 每批 10万条
        total = len(paper_ids)
        inserted = 0
        
        logger.info(f"开始初始化 {total:,} 篇论文状态（分批插入）...")
        
        for i in range(0, total, batch_size):
            batch = paper_ids[i:i + batch_size]
            cursor = self.conn.cursor()
            cursor.executemany(
                "INSERT OR IGNORE INTO paper_status (paper_id, status) VALUES (?, 'pending')",
                [(pid,) for pid in batch]
            )
            self.conn.commit()
            inserted += cursor.rowcount
            
            if (i + batch_size) % 1000000 == 0 or (i + batch_size) >= total:
                logger.info(f"  已初始化 {min(i + batch_size, total):,}/{total:,} 篇 ({100*min(i + batch_size, total)/total:.1f}%)")
        
        logger.info(f"初始化完成: {inserted:,} 篇（新插入）")
        return inserted
    
    def init_paper_status_streaming(self, csv_path: str):
        """流式初始化论文状态（边扫描边插入，避免内存溢出）"""
        batch_size = 50000  # 每批 5万条（减小批次避免锁定）
        batch = []
        total = 0
        inserted = 0
        
        logger.info(f"流式初始化论文状态表（批次大小: {batch_size:,}）...")
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                pid = row.get("id", str(i))
                batch.append(pid)
                total += 1
                
                if len(batch) >= batch_size:
                    max_retries = 3
                    retry_count = 0
                    success = False
                    
                    while retry_count < max_retries and not success:
                        try:
                            # 使用 BEGIN IMMEDIATE 获取写锁
                            self.conn.execute("BEGIN IMMEDIATE")
                            cursor = self.conn.cursor()
                            cursor.executemany(
                                "INSERT OR IGNORE INTO paper_status (paper_id, status) VALUES (?, 'pending')",
                                [(pid,) for pid in batch]
                            )
                            self.conn.commit()
                            inserted += cursor.rowcount
                            cursor.close()
                            batch = []
                            success = True
                        except sqlite3.OperationalError as e:
                            self.conn.rollback()
                            retry_count += 1
                            if "locked" in str(e).lower() and retry_count < max_retries:
                                wait_time = 0.5 * retry_count
                                logger.warning(f"数据库锁定，等待 {wait_time:.1f}s 后重试... (第 {i+1:,} 篇, 重试 {retry_count}/{max_retries})")
                                time.sleep(wait_time)
                            else:
                                raise
                    
                    # 每 10万条执行一次检查点（防止 WAL 文件过大）
                    if (i + 1) % 100000 == 0:
                        logger.info(f"  已扫描并初始化 {i+1:,} 篇 (新插入: {inserted:,})...")
                        # 执行 WAL 检查点
                        try:
                            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                            self.conn.commit()
                            logger.info("  WAL 检查点完成")
                        except Exception as e:
                            logger.warning(f"  检查点执行失败: {e}")
                    
                    # 每 50万条输出详细进度
                    if (i + 1) % 500000 == 0:
                        logger.info(f"  进度: {i+1:,}/{total if total > 0 else '?'} 篇")
        
        # 处理剩余批次
        if batch:
            max_retries = 3
            retry_count = 0
            success = False
            
            while retry_count < max_retries and not success:
                try:
                    self.conn.execute("BEGIN IMMEDIATE")
                    cursor = self.conn.cursor()
                    cursor.executemany(
                        "INSERT OR IGNORE INTO paper_status (paper_id, status) VALUES (?, 'pending')",
                        [(pid,) for pid in batch]
                    )
                    self.conn.commit()
                    inserted += cursor.rowcount
                    cursor.close()
                    success = True
                except sqlite3.OperationalError as e:
                    self.conn.rollback()
                    retry_count += 1
                    if "locked" in str(e).lower() and retry_count < max_retries:
                        wait_time = 0.5 * retry_count
                        logger.warning(f"数据库锁定，等待 {wait_time:.1f}s 后重试最后一批... (重试 {retry_count}/{max_retries})")
                        time.sleep(wait_time)
                    else:
                        raise
        
        # 最后执行一次检查点
        logger.info("执行最终 WAL 检查点...")
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.commit()
            logger.info("最终检查点完成")
        except Exception as e:
            logger.warning(f"最终检查点执行失败: {e}")
        
        logger.info(f"流式初始化完成: 总计 {total:,} 篇，新插入 {inserted:,} 篇")
        return inserted
    
    def get_pending_papers(self, limit: int = None) -> List[str]:
        """获取待处理论文 ID"""
        query = "SELECT paper_id FROM paper_status WHERE status = 'pending'"
        if limit:
            query += f" LIMIT {limit}"
        cursor = self.conn.execute(query)
        return [row[0] for row in cursor.fetchall()]
    
    def get_status_counts(self) -> Dict[str, int]:
        """获取各状态计数"""
        cursor = self.conn.execute(
            "SELECT status, COUNT(*) FROM paper_status GROUP BY status"
        )
        return dict(cursor.fetchall())
    
    def insert_rpus(self, rpus: List[RPU]):
        """批量插入 RPU"""
        if not rpus:
            return
        self.conn.executemany(
            """INSERT OR REPLACE INTO rpu 
               (paper_id, sentence_index, task, object, aspect, context, model_version)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(r.paper_id, r.sentence_index, r.task, r.object, r.aspect, r.context, r.model_version)
             for r in rpus]
        )
    
    def update_paper_status(self, paper_id: str, status: str, rpu_count: int = 0, 
                           sentence_count: int = 0, error_msg: str = None):
        """更新论文状态"""
        self.conn.execute(
            """UPDATE paper_status 
               SET status = ?, rpu_count = ?, sentence_count = ?, error_msg = ?, 
                   updated_at = CURRENT_TIMESTAMP
               WHERE paper_id = ?""",
            (status, rpu_count, sentence_count, error_msg, paper_id)
        )
    
    def batch_update_status(self, updates: List[Tuple]):
        """批量更新状态: [(paper_id, status, rpu_count, sentence_count, error_msg), ...]"""
        self.conn.executemany(
            """UPDATE paper_status 
               SET status = ?, rpu_count = ?, sentence_count = ?, error_msg = ?, 
                   updated_at = CURRENT_TIMESTAMP
               WHERE paper_id = ?""",
            [(s, rc, sc, em, pid) for pid, s, rc, sc, em in updates]
        )
    
    def commit(self):
        self.conn.commit()
    
    def close(self):
        if self.conn:
            self.conn.close()
    
    def get_total_rpu_count(self) -> int:
        """获取总 RPU 数"""
        cursor = self.conn.execute("SELECT COUNT(*) FROM rpu")
        return cursor.fetchone()[0]
    
    def checkpoint(self):
        """手动执行 WAL 检查点"""
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.commit()
        except Exception as e:
            logger.warning(f"检查点执行失败: {e}")


# ============================================================
# WAL 写前日志
# ============================================================
class WALManager:
    """写前日志管理器"""
    
    def __init__(self, wal_dir: str):
        self.wal_dir = wal_dir
        os.makedirs(wal_dir, exist_ok=True)
        self.current_wal = None
        self.current_file = None
    
    def start_batch(self, batch_id: str):
        """开始一个批次"""
        self.current_wal = os.path.join(self.wal_dir, f"wal_{batch_id}.jsonl")
        self.current_file = open(self.current_wal, 'w', encoding='utf-8')
    
    def write(self, paper_id: str, rpus: List[Dict]):
        """写入 WAL"""
        if self.current_file:
            record = {"paper_id": paper_id, "rpus": rpus, "timestamp": time.time()}
            self.current_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    def flush(self):
        """刷新到磁盘"""
        if self.current_file:
            self.current_file.flush()
            os.fsync(self.current_file.fileno())
    
    def commit(self):
        """提交（删除 WAL）"""
        if self.current_file:
            self.current_file.close()
            self.current_file = None
        if self.current_wal and os.path.exists(self.current_wal):
            os.remove(self.current_wal)
            self.current_wal = None
    
    def get_uncommitted_wals(self) -> List[str]:
        """获取未提交的 WAL 文件"""
        if not os.path.exists(self.wal_dir):
            return []
        return [os.path.join(self.wal_dir, f) for f in os.listdir(self.wal_dir) 
                if f.startswith("wal_") and f.endswith(".jsonl")]
    
    def recover(self, db: DatabaseManager) -> int:
        """从 WAL 恢复"""
        uncommitted = self.get_uncommitted_wals()
        if not uncommitted:
            return 0
        
        recovered = 0
        for wal_path in uncommitted:
            logger.info(f"恢复 WAL: {wal_path}")
            try:
                with open(wal_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        record = json.loads(line)
                        paper_id = record["paper_id"]
                        rpus = [RPU(
                            paper_id=paper_id,
                            sentence_index=r["sentence_index"],
                            task=r["task"],
                            object=r["object"],
                            aspect=r.get("aspect", ""),
                            context=r.get("context", ""),
                            model_version=CONFIG["model_version"]
                        ) for r in record["rpus"]]
                        
                        db.insert_rpus(rpus)
                        db.update_paper_status(paper_id, "done", len(rpus), 0)
                        recovered += 1
                
                db.commit()
                os.remove(wal_path)
            except Exception as e:
                logger.error(f"WAL 恢复失败: {wal_path}, {e}")
        
        return recovered


# ============================================================
# RPU 抽取器（FP16 优化）
# ============================================================
class RPUExtractor:
    """RPU 抽取器（FP16 优化版）"""
    
    def __init__(self, model_path: str, device: str, use_fp16: bool = True):
        from transformers import T5ForConditionalGeneration, AutoTokenizer
        
        self.device = device
        logger.info(f"加载模型: {model_path}")
        logger.info(f"设备: {device}, FP16: {use_fp16}")
        
        self.tokenizer = AutoTokenizer.from_pretrained("t5-base")
        self.model = T5ForConditionalGeneration.from_pretrained(model_path)
        
        if use_fp16 and device == "cuda":
            self.model.half()
            logger.info("已启用 FP16 量化")
        
        self.model.to(device)
        self.model.eval()
        
        # 分句器
        import spacy
        self.nlp = spacy.blank("en")
        self.nlp.add_pipe("sentencizer")
        
        logger.info("模型加载完成")
    
    def split_sentences(self, texts: List[str]) -> List[List[str]]:
        """批量分句"""
        results = []
        for doc in self.nlp.pipe(texts, batch_size=2000):
            sents = [sent.text.strip() for sent in doc.sents if sent.text.strip()]
            results.append(sents)
        return results
    
    def extract_batch(self, sentences: List[str], batch_size: int) -> List[str]:
        """批量抽取（带详细性能监控）"""
        if not sentences:
            return []
        
        total = len(sentences)
        num_batches = (total + batch_size - 1) // batch_size
        all_outputs = []
        
        # 性能统计
        tokenize_times = []
        transfer_times = []
        generate_times = []
        decode_times = []
        batch_total_times = []
        input_lengths = []  # 记录每个 batch 的实际输入长度（用于分析 padding 影响）
        
        logger.info(f"  T5 推理: {total:,} 个句子, {num_batches} 个批次")
        
        for i in range(0, len(sentences), batch_size):
            batch = sentences[i:i + batch_size]
            batch_num = i // batch_size + 1
            input_texts = [f"extract: {s}" for s in batch]
            
            # ========== C1: Tokenize (CPU) ==========
            if self.device == "cuda":
                torch.cuda.synchronize()
            t0 = time.perf_counter()
            
            inputs = self.tokenizer(
                input_texts,
                max_length=CONFIG["max_input_length"],
                padding=True,
                truncation=True,
                return_tensors='pt'
            )
            
            # 记录输入长度统计（用于分析 padding 影响）
            actual_seq_len = inputs['input_ids'].shape[1]
            input_lengths.append(actual_seq_len)
            
            t1 = time.perf_counter()
            tokenize_time = t1 - t0
            tokenize_times.append(tokenize_time)
            
            # ========== C2: Transfer to GPU ==========
            inputs = inputs.to(self.device)
            if self.device == "cuda":
                torch.cuda.synchronize()
            t2 = time.perf_counter()
            transfer_time = t2 - t1
            transfer_times.append(transfer_time)
            
            # ========== C3: Generate (GPU) ==========
            with torch.no_grad():
                if CONFIG["use_fp16"] and self.device == "cuda":
                    with torch.amp.autocast('cuda'):
                        outputs = self.model.generate(
                            input_ids=inputs['input_ids'],
                            attention_mask=inputs['attention_mask'],
                            max_length=CONFIG["max_output_length"],
                            num_beams=1,
                            do_sample=False,
                            early_stopping=False,
                            output_scores=False,
                            return_dict_in_generate=False
                        )
                else:
                    outputs = self.model.generate(
                        input_ids=inputs['input_ids'],
                        attention_mask=inputs['attention_mask'],
                        max_length=CONFIG["max_output_length"],
                        num_beams=1,
                        do_sample=False,
                        early_stopping=False,
                        output_scores=False,
                        return_dict_in_generate=False
                    )
            
            if self.device == "cuda":
                torch.cuda.synchronize()
            t3 = time.perf_counter()
            generate_time = t3 - t2
            generate_times.append(generate_time)
            
            # ========== C4: Decode (CPU) ==========
            decoded = [self.tokenizer.decode(o, skip_special_tokens=True) for o in outputs]
            t4 = time.perf_counter()
            decode_time = t4 - t3
            decode_times.append(decode_time)
            
            all_outputs.extend(decoded)
            batch_total = t4 - t0
            batch_total_times.append(batch_total)
            
            # 及时释放 GPU 内存
            del inputs, outputs, decoded
            if self.device == "cuda":
                # 每 5 个批次清理一次 GPU 缓存，避免显存碎片累积
                if batch_num % 5 == 0:
                    torch.cuda.empty_cache()
                
                # 每 10 个批次给系统留出响应时间（短暂延迟）
                if batch_num % 10 == 0 and CONFIG.get("inference_delay", 0) > 0:
                    time.sleep(CONFIG["inference_delay"])
            
            # 每 20 个批次输出详细性能统计
            if batch_num % 20 == 0 or batch_num == num_batches:
                progress = 100 * batch_num / num_batches
                # 计算累计平均值
                avg_tokenize = sum(tokenize_times) / len(tokenize_times) * 1000
                avg_transfer = sum(transfer_times) / len(transfer_times) * 1000
                avg_generate = sum(generate_times) / len(generate_times) * 1000
                avg_decode = sum(decode_times) / len(decode_times) * 1000
                avg_total = sum(batch_total_times) / len(batch_total_times) * 1000
                avg_seq_len = sum(input_lengths) / len(input_lengths) if input_lengths else 0
                
                logger.info(f"    推理进度: {batch_num}/{num_batches} ({progress:.1f}%) - {len(all_outputs):,}/{total:,} 句")
                logger.info(f"    性能: tokenize={avg_tokenize:.1f}ms, transfer={avg_transfer:.1f}ms, "
                          f"generate={avg_generate:.1f}ms, decode={avg_decode:.1f}ms, total={avg_total:.1f}ms/batch")
                logger.info(f"    输入长度: 平均 {avg_seq_len:.0f} tokens/batch (batch_size={batch_size})")
        
        # 最终清理 GPU 缓存
        if self.device == "cuda":
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        
        # 输出最终性能统计
        if tokenize_times and generate_times:
            total_tokenize = sum(tokenize_times)
            total_transfer = sum(transfer_times)
            total_generate = sum(generate_times)
            total_decode = sum(decode_times)
            total_all = total_tokenize + total_transfer + total_generate + total_decode
            
            avg_seq_len = sum(input_lengths) / len(input_lengths) if input_lengths else 0
            max_seq_len = max(input_lengths) if input_lengths else 0
            min_seq_len = min(input_lengths) if input_lengths else 0
            
            logger.info(f"  T5 推理完成，性能分解:")
            logger.info(f"    Tokenize:  {total_tokenize:.2f}s ({100*total_tokenize/total_all:.1f}%)")
            logger.info(f"    Transfer:  {total_transfer:.2f}s ({100*total_transfer/total_all:.1f}%)")
            logger.info(f"    Generate:  {total_generate:.2f}s ({100*total_generate/total_all:.1f}%)")
            logger.info(f"    Decode:    {total_decode:.2f}s ({100*total_decode/total_all:.1f}%)")
            logger.info(f"    总计:      {total_all:.2f}s")
            logger.info(f"    单位成本:  {total_all/total*1000:.2f} ms/句")
            logger.info(f"    输入长度:  平均 {avg_seq_len:.0f}, 范围 [{min_seq_len}, {max_seq_len}] tokens (batch_size={batch_size})")
        
        return all_outputs


# ============================================================
# RPU 解析与过滤
# ============================================================
def parse_rpu_output(paper_id: str, sentence_index: int, raw_output: str) -> Optional[RPU]:
    """解析模型输出为 RPU"""
    try:
        fields = json.loads(raw_output)
        if not isinstance(fields, list) or len(fields) != 4:
            return None
        
        def normalize(val):
            if val is None:
                return ""
            val_str = str(val).strip()
            if val_str.lower() in ("", "null", "nan", "none"):
                return ""
            return val_str
        
        task = normalize(fields[0])
        obj = normalize(fields[1])
        aspect = normalize(fields[2])
        context = normalize(fields[3])
        
        # 强制规则：Task 或 Object 为空则丢弃
        if not task or not obj:
            return None
        
        return RPU(
            paper_id=paper_id,
            sentence_index=sentence_index,
            task=task,
            object=obj,
            aspect=aspect,
            context=context,
            model_version=CONFIG["model_version"]
        )
    except (json.JSONDecodeError, ValueError, IndexError):
        return None


# ============================================================
# 监控统计
# ============================================================
class Monitor:
    """实时监控"""
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        self.papers_processed = 0
        self.sentences_processed = 0
        self.rpus_generated = 0
        self.json_errors = 0
        self.empty_tasks = 0
        self.empty_objects = 0
        self.rpu_counts = []
        self.start_time = time.time()
    
    def update(self, paper_rpu_count: int, sentence_count: int, json_err: int = 0):
        self.papers_processed += 1
        self.sentences_processed += sentence_count
        self.rpus_generated += paper_rpu_count
        self.json_errors += json_err
        self.rpu_counts.append(paper_rpu_count)
    
    def get_stats(self) -> Dict:
        elapsed = time.time() - self.start_time
        papers_per_sec = self.papers_processed / elapsed if elapsed > 0 else 0
        
        return {
            "papers_processed": self.papers_processed,
            "sentences_processed": self.sentences_processed,
            "rpus_generated": self.rpus_generated,
            "json_error_rate": self.json_errors / max(1, self.sentences_processed),
            "avg_rpu_per_paper": self.rpus_generated / max(1, self.papers_processed),
            "papers_per_second": papers_per_sec,
            "elapsed_seconds": elapsed
        }
    
    def check_anomaly(self) -> Optional[str]:
        """检查异常"""
        stats = self.get_stats()
        
        if stats["json_error_rate"] > CONFIG["max_json_error_rate"]:
            return f"JSON 错误率过高: {stats['json_error_rate']:.2%}"
        
        # 检查最近的 RPU 数分布
        if len(self.rpu_counts) >= 100:
            recent = self.rpu_counts[-100:]
            if sum(1 for c in recent if c > CONFIG["max_rpu_per_paper"]) > 10:
                return f"单篇 RPU 数异常: 最近100篇中{sum(1 for c in recent if c > CONFIG['max_rpu_per_paper'])}篇超过{CONFIG['max_rpu_per_paper']}"
        
        return None


# ============================================================
# 主处理流程
# ============================================================
def load_papers_batch(csv_path: str, paper_ids: set, batch_size: int) -> List[Dict]:
    """按 ID 加载论文（流式读取，只加载需要的）"""
    papers = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get("id", "")
            if pid in paper_ids:
                abstract = row.get("abstract", "").strip()
                # 预筛选：跳过无摘要论文
                if not abstract:
                    continue
                papers.append({
                    "id": pid,
                    "title": row.get("title", ""),
                    "abstract": abstract
                })
                if len(papers) >= batch_size:
                    break
    return papers


def scan_all_paper_ids(csv_path: str) -> Tuple[List[str], int, int]:
    """扫描所有论文 ID，统计有无摘要"""
    paper_ids = []
    with_abstract = 0
    without_abstract = 0
    
    logger.info(f"扫描论文文件: {csv_path}")
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            pid = row.get("id", str(i))
            abstract = row.get("abstract", "").strip()
            paper_ids.append(pid)
            if abstract:
                with_abstract += 1
            else:
                without_abstract += 1
            
            if (i + 1) % 1000000 == 0:
                logger.info(f"  已扫描 {i+1:,} 篇...")
    
    logger.info(f"扫描完成: 总计 {len(paper_ids):,} 篇")
    logger.info(f"  有摘要: {with_abstract:,} ({100*with_abstract/len(paper_ids):.1f}%)")
    logger.info(f"  无摘要: {without_abstract:,} ({100*without_abstract/len(paper_ids):.1f}%)")
    
    return paper_ids, with_abstract, without_abstract


def process_paper_batch(papers: List[Dict], extractor: RPUExtractor, 
                        db: DatabaseManager, wal: WALManager, 
                        monitor: Monitor) -> int:
    """处理一批论文（带进度显示）"""
    if not papers:
        return 0
    
    import time
    step_start = time.time()
    
    # 1. 收集所有文本
    logger.info("  [步骤 1/5] 收集标题和摘要...")
    all_texts = []
    paper_indices = []  # (paper_idx, is_title)
    
    for i, paper in enumerate(papers):
        if paper["title"]:
            all_texts.append(paper["title"])
            paper_indices.append((i, True))
        if paper["abstract"]:
            all_texts.append(paper["abstract"])
            paper_indices.append((i, False))
    
    logger.info(f"    完成: {len(all_texts):,} 个文本, 耗时 {time.time() - step_start:.1f}s")
    
    # 2. 批量分句
    step_start = time.time()
    logger.info("  [步骤 2/5] 批量分句...")
    all_sentences = []
    sentence_map = []  # (paper_idx, local_sentence_idx)
    
    split_results = extractor.split_sentences(all_texts)
    
    text_idx = 0
    paper_sentence_counts = [0] * len(papers)
    
    for paper_idx, is_title in paper_indices:
        sentences = split_results[text_idx]
        text_idx += 1
        
        if is_title:
            # 标题作为一个句子
            for sent in sentences:
                all_sentences.append(sent)
                sentence_map.append((paper_idx, paper_sentence_counts[paper_idx]))
                paper_sentence_counts[paper_idx] += 1
        else:
            # 摘要分句
            for sent in sentences:
                all_sentences.append(sent)
                sentence_map.append((paper_idx, paper_sentence_counts[paper_idx]))
                paper_sentence_counts[paper_idx] += 1
    
    logger.info(f"    完成: {len(all_sentences):,} 个句子, 耗时 {time.time() - step_start:.1f}s")
    
    # 3. 批量推理
    step_start = time.time()
    logger.info("  [步骤 3/5] T5 批量推理...")
    raw_outputs = extractor.extract_batch(all_sentences, CONFIG["batch_size"])
    logger.info(f"    完成: 耗时 {time.time() - step_start:.1f}s")
    
    # 4. 解析 RPU 并按论文分组
    step_start = time.time()
    logger.info("  [步骤 4/5] 解析 RPU...")
    paper_rpus = {i: [] for i in range(len(papers))}
    json_errors = 0
    
    for sent_idx, raw_output in enumerate(raw_outputs):
        paper_idx, local_sent_idx = sentence_map[sent_idx]
        paper_id = papers[paper_idx]["id"]
        
        rpu = parse_rpu_output(paper_id, local_sent_idx, raw_output)
        if rpu:
            paper_rpus[paper_idx].append(rpu)
        elif raw_output and not raw_output.startswith("["):
            json_errors += 1
    
    total_rpus = sum(len(rpus) for rpus in paper_rpus.values())
    logger.info(f"    完成: {total_rpus:,} 个 RPU, JSON 错误: {json_errors}, 耗时 {time.time() - step_start:.1f}s")
    
    # 5. 写入 WAL 并更新数据库
    step_start = time.time()
    logger.info("  [步骤 5/5] 写入数据库...")
    status_updates = []
    all_rpus = []
    
    for paper_idx, rpus in paper_rpus.items():
        paper = papers[paper_idx]
        paper_id = paper["id"]
        
        # 写 WAL
        wal.write(paper_id, [
            {"sentence_index": r.sentence_index, "task": r.task, "object": r.object, 
             "aspect": r.aspect, "context": r.context}
            for r in rpus
        ])
        
        all_rpus.extend(rpus)
        status_updates.append((
            paper_id, "done", len(rpus), paper_sentence_counts[paper_idx], None
        ))
        
        monitor.update(len(rpus), paper_sentence_counts[paper_idx], 
                      json_errors // len(papers) if papers else 0)
    
    # 6. 刷新 WAL
    wal.flush()
    
    # 7. 写入数据库
    db.insert_rpus(all_rpus)
    db.batch_update_status(status_updates)
    db.commit()
    
    # 8. 提交 WAL
    wal.commit()
    
    rpu_count = len(all_rpus)
    logger.info(f"    完成: 写入 {rpu_count:,} 个 RPU, 耗时 {time.time() - step_start:.1f}s")
    
    # 清理内存（在返回前保存结果）
    del all_texts, all_sentences, raw_outputs, paper_rpus, status_updates
    if extractor.device == "cuda":
        torch.cuda.empty_cache()
    
    return rpu_count


def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("全量 RPU 抽取")
    logger.info(f"模型版本: {CONFIG['model_version']}")
    logger.info(f"FP16: {CONFIG['use_fp16']}")
    logger.info(f"Batch Size: {CONFIG['batch_size']}")
    logger.info("=" * 60)
    
    # 创建输出目录
    os.makedirs(CONFIG["output_dir"], exist_ok=True)
    
    # 初始化数据库
    db_path = os.path.join(CONFIG["output_dir"], CONFIG["db_name"])
    db = DatabaseManager(db_path)
    
    # 初始化 WAL
    wal_dir = os.path.join(CONFIG["output_dir"], "wal")
    wal = WALManager(wal_dir)
    
    # WAL 恢复
    recovered = wal.recover(db)
    if recovered > 0:
        logger.info(f"从 WAL 恢复 {recovered} 篇论文")
    
    # 检查状态表
    status_counts = db.get_status_counts()
    
    if not status_counts:
        # 首次运行：流式初始化论文状态表
        logger.info("首次运行，开始流式初始化论文状态表...")
        inserted = db.init_paper_status_streaming(CONFIG["input_csv"])
        logger.info(f"初始化完成: {inserted:,} 篇论文")
    else:
        logger.info(f"状态统计: {status_counts}")
    
    # 初始化抽取器
    model_path = CONFIG["model_path"]
    if not Path(model_path).exists():
        logger.error(f"模型不存在: {model_path}")
        return
    
    extractor = RPUExtractor(model_path, CONFIG["device"], CONFIG["use_fp16"])
    
    # 初始化监控
    monitor = Monitor()
    
    # 获取总论文数（用于进度计算）
    status_counts = db.get_status_counts()
    total_papers = status_counts.get('pending', 0) + status_counts.get('done', 0) + status_counts.get('failed', 0)
    if total_papers == 0:
        # 如果状态表为空，需要先初始化
        logger.warning("无法获取总论文数，将在处理过程中更新")
        total_papers = None
    
    # 主循环
    batch_id = 0
    total_start = time.time()
    
    while True:
        # 获取待处理论文
        pending_ids = db.get_pending_papers(limit=CONFIG["paper_batch_size"])
        
        if not pending_ids:
            logger.info("所有论文处理完成")
            break
        
        batch_id += 1
        batch_start = time.time()
        
        # 更新总论文数（如果之前不知道）
        if total_papers is None:
            status_counts = db.get_status_counts()
            total_papers = status_counts.get('pending', 0) + status_counts.get('done', 0) + status_counts.get('failed', 0)
        
        # 计算进度（使用数据库中的 done 计数，包含历史 + 当前运行）
        status_counts = db.get_status_counts()
        pending_count = status_counts.get('pending', 0)
        done_count = status_counts.get('done', 0)
        failed_count = status_counts.get('failed', 0)
        
        # 确保 total_papers 准确（done + pending + failed）
        if total_papers is None or total_papers == 0:
            total_papers = done_count + pending_count + failed_count
        
        if total_papers and total_papers > 0:
            progress_pct = 100 * done_count / total_papers
            remaining = pending_count
            elapsed = time.time() - total_start
            if done_count > 0:
                avg_time_per_paper = elapsed / done_count
                eta_seconds = avg_time_per_paper * remaining
                eta_hours = eta_seconds / 3600
                logger.info(f"批次 {batch_id}: 处理 {len(pending_ids)} 篇论文...")
                logger.info(f"  整体进度: {done_count:,}/{total_papers:,} ({progress_pct:.2f}%) | 剩余: {remaining:,} 篇 | 预计剩余时间: {eta_hours:.1f} 小时")
            else:
                logger.info(f"批次 {batch_id}: 处理 {len(pending_ids)} 篇论文...")
                logger.info(f"  整体进度: {done_count:,}/{total_papers:,} ({progress_pct:.2f}%) | 剩余: {remaining:,} 篇")
        else:
            logger.info(f"批次 {batch_id}: 处理 {len(pending_ids)} 篇论文...")
        
        # 加载论文数据（预筛选无摘要）
        pending_set = set(pending_ids)
        papers = load_papers_batch(CONFIG["input_csv"], pending_set, CONFIG["paper_batch_size"])
        
        # 标记无摘要论文为 done
        loaded_ids = set(p["id"] for p in papers)
        skipped_ids = pending_set - loaded_ids
        if skipped_ids:
            for pid in skipped_ids:
                db.update_paper_status(pid, "done", 0, 0, "no_abstract")
            db.commit()
            logger.info(f"  跳过无摘要论文: {len(skipped_ids)} 篇")
        
        if not papers:
            continue
        
        # 开始 WAL 批次
        wal.start_batch(f"{batch_id}_{int(time.time())}")
        
        # 处理论文
        try:
            rpu_count = process_paper_batch(papers, extractor, db, wal, monitor)
        except Exception as e:
            logger.error(f"批次处理失败: {e}")
            # 标记为 failed
            for p in papers:
                db.update_paper_status(p["id"], "failed", 0, 0, str(e))
            db.commit()
            continue
        
        batch_time = time.time() - batch_start
        
        # 打印统计
        stats = monitor.get_stats()
        logger.info(f"  完成: {len(papers)} 篇, {rpu_count} RPU, 耗时 {batch_time:.1f}s")
        logger.info(f"  累计: {stats['papers_processed']:,} 篇, {stats['rpus_generated']:,} RPU")
        logger.info(f"  速度: {stats['papers_per_second']:.1f} 篇/秒, 平均 {stats['avg_rpu_per_paper']:.2f} RPU/篇")
        
        # 检查异常
        anomaly = monitor.check_anomaly()
        if anomaly:
            logger.warning(f"检测到异常: {anomaly}")
            logger.warning("建议检查后再继续，按 Ctrl+C 停止")
        
        # 状态更新
        if batch_id % 10 == 0:
            status_counts = db.get_status_counts()
            total_rpu = db.get_total_rpu_count()
            logger.info(f"状态统计: {status_counts}, 总 RPU: {total_rpu:,}")
        
        # 每批次完成后给系统留出响应时间
        if extractor.device == "cuda":
            torch.cuda.synchronize()  # 确保 GPU 操作完成
            time.sleep(0.1)  # 100ms 延迟，让系统响应（每批约 0.1 秒，对总速度影响 < 1%）
    
    # 完成
    total_time = time.time() - total_start
    final_stats = monitor.get_stats()
    
    logger.info("=" * 60)
    logger.info("抽取完成")
    logger.info(f"总论文数: {final_stats['papers_processed']:,}")
    logger.info(f"总 RPU 数: {db.get_total_rpu_count():,}")
    logger.info(f"总耗时: {total_time/3600:.2f} 小时")
    logger.info(f"平均速度: {final_stats['papers_per_second']:.1f} 篇/秒")
    logger.info("=" * 60)
    
    db.close()


if __name__ == "__main__":
    main()
