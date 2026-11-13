# -*- coding: utf-8 -*-
"""
全量 RPU 抽取脚本（DeBERTa 版）

基于 benchmark 验证的模型和参数：
- 模型：DeBERTaMultiHeadClassifierFast（合并 head 优化版）
- 速度：1040 sent/s（RTX 5070 Ti）
- 质量：TASK F1 +7.2%, OBJ F1 +13.1%

model_version: deberta-rpu-v1.0
"""

import os
import csv
import json
import time
import sqlite3
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

import torch
import torch.nn as nn
from transformers import AutoModel, AutoTokenizer

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
    "output_dir": str(Path(_paths["rpu_db_path"]).parent),
    "db_name": "rpu_database.db",
    
    # DeBERTa 模型（冻结）
    "model_name": "microsoft/deberta-v3-base",
    "checkpoint_path": _require_path("deberta_checkpoint_path"),
    "model_version": "deberta-rpu-v1.0",
    "device": "cuda" if torch.cuda.is_available() else "cpu",
    
    # 推理参数（从 benchmark 冻结）
    "max_length": 128,
    "batch_size": 512, # 192
    "use_fp16": True,
    "fields": ["TASK", "OBJ", "ASP", "CTX"],
    
    # 分片参数
    "shard_size": 40000,              # 每片论文数
    "paper_batch_size": 2000,         # 每批处理论文数
    "db_commit_interval": 1000,       # 数据库提交间隔
    
    # 监控阈值
    "max_empty_rate": 0.80,           # 空预测率上限（连续 3 shard 触发）
    "max_task_drop": 0.15,            # TASK 命中率下降上限
    "max_throughput_variance": 0.30,  # 吞吐波动上限
}

# ============================================================
# 日志配置
# ============================================================
os.makedirs(CONFIG["output_dir"], exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(CONFIG["output_dir"], "extraction.log"),
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
# 数据库管理（复用 T5 版本结构）
# ============================================================
class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None
        self._init_db()
    
    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, timeout=120, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA cache_size=50000")
        self.conn.execute("PRAGMA temp_store=MEMORY")
        self.conn.execute("PRAGMA mmap_size=268435456")
        self.conn.execute("PRAGMA busy_timeout=30000")
        
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
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS shard_status (
                shard_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                num_papers INTEGER DEFAULT 0,
                num_sentences INTEGER DEFAULT 0,
                num_rpu INTEGER DEFAULT 0,
                runtime_sec REAL DEFAULT 0,
                task_hit_rate REAL DEFAULT 0,
                empty_rate REAL DEFAULT 0,
                error_msg TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_rpu_paper_id ON rpu(paper_id)")
        self.conn.commit()
        logger.info(f"数据库初始化完成: {self.db_path}")
    
    def insert_rpus(self, rpus: List[RPU]):
        if not rpus:
            return
        self.conn.executemany(
            """INSERT OR REPLACE INTO rpu 
               (paper_id, sentence_index, task, object, aspect, context, model_version)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(r.paper_id, r.sentence_index, r.task, r.object, r.aspect, r.context, r.model_version)
             for r in rpus]
        )
    
    def update_shard_status(self, shard_id: str, status: str, num_papers: int = 0,
                           num_sentences: int = 0, num_rpu: int = 0, runtime_sec: float = 0,
                           task_hit_rate: float = 0, empty_rate: float = 0, error_msg: str = None):
        self.conn.execute(
            """INSERT OR REPLACE INTO shard_status 
               (shard_id, status, num_papers, num_sentences, num_rpu, runtime_sec, 
                task_hit_rate, empty_rate, error_msg, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (shard_id, status, num_papers, num_sentences, num_rpu, runtime_sec,
             task_hit_rate, empty_rate, error_msg)
        )
    
    def get_pending_shards(self) -> List[str]:
        cursor = self.conn.execute(
            "SELECT shard_id FROM shard_status WHERE status = 'pending' ORDER BY shard_id"
        )
        return [row[0] for row in cursor.fetchall()]
    
    def get_done_shards(self) -> set:
        cursor = self.conn.execute(
            "SELECT shard_id FROM shard_status WHERE status = 'done'"
        )
        return {row[0] for row in cursor.fetchall()}
    
    def commit(self):
        self.conn.commit()
    
    def checkpoint(self):
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.conn.commit()
    
    def close(self):
        if self.conn:
            self.conn.close()
    
    def get_total_rpu_count(self) -> int:
        cursor = self.conn.execute("SELECT COUNT(*) FROM rpu")
        return cursor.fetchone()[0]


# ============================================================
# DeBERTa 模型（从 benchmark 复用）
# ============================================================
class DeBERTaMultiHeadClassifierFast(nn.Module):
    """合并 head 优化版"""
    
    def __init__(self, model_name: str, num_labels: int = 3, fields: List[str] = None):
        super().__init__()
        self.fields = fields or CONFIG["fields"]
        self.num_labels = num_labels
        self.num_fields = len(self.fields)
        
        self.backbone = AutoModel.from_pretrained(model_name)
        hidden_size = self.backbone.config.hidden_size
        self.combined_head = nn.Linear(hidden_size, self.num_fields * num_labels)
        self.dropout = nn.Dropout(0.1)
    
    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> Dict[str, torch.Tensor]:
        outputs = self.backbone(input_ids=input_ids, attention_mask=attention_mask)
        hidden_states = outputs.last_hidden_state
        hidden_states = self.dropout(hidden_states)
        combined_logits = self.combined_head(hidden_states)
        
        batch_size, seq_len, _ = combined_logits.shape
        combined_logits = combined_logits.view(batch_size, seq_len, self.num_fields, self.num_labels)
        
        logits = {}
        for i, field in enumerate(self.fields):
            logits[field] = combined_logits[:, :, i, :]
        return logits
    
    @classmethod
    def from_legacy_checkpoint(cls, checkpoint_path: str, model_name: str, device: str, fields: List[str]):
        model = cls(model_name=model_name, num_labels=3, fields=fields)
        checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
        old_state_dict = checkpoint["model_state_dict"]
        
        weights_to_concat = []
        biases_to_concat = []
        for field in fields:
            weights_to_concat.append(old_state_dict[f"heads.{field}.weight"])
            biases_to_concat.append(old_state_dict[f"heads.{field}.bias"])
        
        combined_weight = torch.cat(weights_to_concat, dim=0)
        combined_bias = torch.cat(biases_to_concat, dim=0)
        
        new_state_dict = {}
        for key, value in old_state_dict.items():
            if key.startswith("heads."):
                continue
            new_state_dict[key] = value
        
        new_state_dict["combined_head.weight"] = combined_weight
        new_state_dict["combined_head.bias"] = combined_bias
        
        model.load_state_dict(new_state_dict)
        logger.info("  权重转换完成: 4×Linear(768,3) → Linear(768,12)")
        return model


# ============================================================
# DeBERTa 抽取器
# ============================================================
class DeBERTaExtractor:
    def __init__(self):
        logger.info(f"加载 DeBERTa 模型: {CONFIG['checkpoint_path']}")
        self.device = CONFIG["device"]
        self.tokenizer = AutoTokenizer.from_pretrained(CONFIG["model_name"])
        
        self.model = DeBERTaMultiHeadClassifierFast.from_legacy_checkpoint(
            checkpoint_path=CONFIG["checkpoint_path"],
            model_name=CONFIG["model_name"],
            device=self.device,
            fields=CONFIG["fields"]
        )
        self.model.to(self.device)
        
        if CONFIG["use_fp16"] and self.device == "cuda":
            self.model.half()
            logger.info("  已启用 FP16")
        
        self.model.eval()
        
        # 缓存
        self.cls_id = self.tokenizer.cls_token_id
        self.sep_id = self.tokenizer.sep_token_id
        self.pad_id = self.tokenizer.pad_token_id
        self.max_len = CONFIG["max_length"]
        
        # spaCy 分句器
        import spacy
        self.nlp = spacy.blank("en")
        self.nlp.add_pipe("sentencizer")
        
        logger.info("DeBERTa 模型加载完成")
    
    def split_sentences(self, texts: List[str]) -> List[List[str]]:
        results = []
        for doc in self.nlp.pipe(texts, batch_size=2000):
            sents = [sent.text.strip() for sent in doc.sents if sent.text.strip()]
            results.append(sents)
        return results
    
    def tokenize_batch_fast(self, sentences: List[str]) -> Tuple[List[List[str]], torch.Tensor, torch.Tensor, List[int]]:
        """批量 tokenize（Fast Tokenizer 优化版）"""
        if not sentences:
            return [], torch.tensor([]), torch.tensor([]), []
        
        # 使用 Fast Tokenizer 批量处理（Rust 并行）
        encoded = self.tokenizer(
            sentences,
            add_special_tokens=True,
            max_length=self.max_len,
            padding=True,
            truncation=True,
            return_tensors="pt"
        )
        
        input_ids = encoded["input_ids"]
        attention_mask = encoded["attention_mask"]
        
        # 恢复 tokens 用于 BIO → text
        all_tokens = []
        token_counts = []
        
        for i, ids in enumerate(input_ids):
            # 找到实际 token 范围（去掉 CLS、SEP、PAD）
            mask = attention_mask[i]
            seq_len = mask.sum().item()
            
            # 去掉 CLS 和 SEP
            content_ids = ids[1:seq_len-1].tolist()
            tokens = self.tokenizer.convert_ids_to_tokens(content_ids)
            
            all_tokens.append(tokens)
            token_counts.append(len(tokens))
        
        return all_tokens, input_ids, attention_mask, token_counts
    
    def infer_batch(self, sentences: List[str], diagnose: bool = False) -> List[Dict[str, Tuple[List[str], List[str]]]]:
        """批量推理，返回每句的 {field: (tokens, bio_labels)}"""
        if not sentences:
            return []
        
        # 诊断模式：精确计时
        if diagnose:
            t0 = time.time()
        
        all_tokens, input_ids, attention_mask, token_counts = self.tokenize_batch_fast(sentences)
        
        if diagnose:
            t1 = time.time()
        
        if len(input_ids) == 0:
            return []
        
        input_ids = input_ids.to(self.device, non_blocking=True)
        attention_mask = attention_mask.to(self.device, non_blocking=True)
        
        if diagnose and self.device == "cuda":
            torch.cuda.synchronize()
            t2 = time.time()
        
        with torch.inference_mode():
            if CONFIG["use_fp16"] and self.device == "cuda":
                with torch.amp.autocast('cuda'):
                    logits = self.model(input_ids, attention_mask)
            else:
                logits = self.model(input_ids, attention_mask)
        
        if diagnose and self.device == "cuda":
            torch.cuda.synchronize()
            t3 = time.time()
        
        preds_all = {field: torch.argmax(logits[field], dim=-1).cpu().numpy() for field in CONFIG["fields"]}
        
        if diagnose:
            t4 = time.time()
        
        results = []
        for i, num_tokens in enumerate(token_counts):
            sample_result = {}
            tokens = all_tokens[i]
            for field in CONFIG["fields"]:
                preds = preds_all[field][i]
                valid_preds = preds[1:1 + num_tokens].tolist()
                bio_labels = [f"B-{field}" if p == 1 else f"I-{field}" if p == 2 else "O" for p in valid_preds]
                sample_result[field] = (tokens, bio_labels)
            results.append(sample_result)
        
        if diagnose:
            t5 = time.time()
            batch_len = input_ids.shape[1]
            print(f"  [Diagnose] batch={len(sentences)}, seq_len={batch_len} | "
                  f"Tokenize:{(t1-t0)*1000:.0f}ms, Transfer:{(t2-t1)*1000:.0f}ms, "
                  f"GPU:{(t3-t2)*1000:.0f}ms, Argmax:{(t4-t3)*1000:.0f}ms, Post:{(t5-t4)*1000:.0f}ms | "
                  f"Total:{(t5-t0)*1000:.0f}ms")
        
        return results
    
    def bio_to_text(self, tokens: List[str], bio_labels: List[str]) -> str:
        """从 BIO 标签提取原文文本"""
        spans = self._extract_spans(bio_labels)
        if not spans:
            return ""
        
        start, end = spans[0]
        if start >= len(tokens) or end > len(tokens):
            return ""
        
        text_parts = []
        for i in range(start, end):
            token = tokens[i]
            # DeBERTa 使用 ▁ 作为 subword 前缀
            if token.startswith("▁"):
                if text_parts:
                    text_parts.append(" ")
                text_parts.append(token[1:])
            elif token.startswith("##"):
                text_parts.append(token[2:])
            else:
                if text_parts and not text_parts[-1].endswith(" "):
                    text_parts.append(" ")
                text_parts.append(token)
        
        return "".join(text_parts).strip()
    
    def _extract_spans(self, bio_labels: List[str]) -> List[Tuple[int, int]]:
        """从 BIO 标签提取 span 位置"""
        spans = []
        start = None
        
        for i, label in enumerate(bio_labels):
            if label.startswith("B-"):
                if start is not None:
                    spans.append((start, i))
                start = i
            elif label.startswith("I-"):
                if start is None:
                    start = i
            else:
                if start is not None:
                    spans.append((start, i))
                    start = None
        
        if start is not None:
            spans.append((start, len(bio_labels)))
        
        return spans
    
    def extract_rpu(self, paper_id: str, sentence_index: int, 
                    inference_result: Dict[str, Tuple[List[str], List[str]]]) -> Optional[RPU]:
        """从推理结果提取 RPU"""
        task_tokens, task_bio = inference_result["TASK"]
        obj_tokens, obj_bio = inference_result["OBJ"]
        asp_tokens, asp_bio = inference_result["ASP"]
        ctx_tokens, ctx_bio = inference_result["CTX"]
        
        task = self.bio_to_text(task_tokens, task_bio)
        obj = self.bio_to_text(obj_tokens, obj_bio)
        
        # 强制规则：Task 或 Object 为空则丢弃
        if not task or not obj:
            return None
        
        aspect = self.bio_to_text(asp_tokens, asp_bio)
        context = self.bio_to_text(ctx_tokens, ctx_bio)
        
        return RPU(
            paper_id=paper_id,
            sentence_index=sentence_index,
            task=task,
            object=obj,
            aspect=aspect,
            context=context,
            model_version=CONFIG["model_version"]
        )


# ============================================================
# 监控器
# ============================================================
class Monitor:
    def __init__(self):
        self.reset()
    
    def reset(self):
        self.shard_stats = []
        self.consecutive_high_empty = 0
        self.baseline_task_rate = None
    
    def record_shard(self, num_sentences: int, num_rpu: int, runtime_sec: float):
        task_hit_rate = num_rpu / max(1, num_sentences)
        empty_rate = 1 - task_hit_rate
        sent_per_sec = num_sentences / max(0.001, runtime_sec)
        
        self.shard_stats.append({
            "num_sentences": num_sentences,
            "num_rpu": num_rpu,
            "runtime_sec": runtime_sec,
            "task_hit_rate": task_hit_rate,
            "empty_rate": empty_rate,
            "sent_per_sec": sent_per_sec
        })
        
        # 设置基线
        if self.baseline_task_rate is None and len(self.shard_stats) >= 3:
            self.baseline_task_rate = sum(s["task_hit_rate"] for s in self.shard_stats[:3]) / 3
        
        # 检查连续高空预测率
        if empty_rate > CONFIG["max_empty_rate"]:
            self.consecutive_high_empty += 1
        else:
            self.consecutive_high_empty = 0
        
        return task_hit_rate, empty_rate, sent_per_sec
    
    def check_anomaly(self) -> Optional[str]:
        if self.consecutive_high_empty >= 3:
            return f"连续 {self.consecutive_high_empty} 个 shard 空预测率 > {CONFIG['max_empty_rate']*100:.0f}%"
        
        if self.baseline_task_rate is not None and len(self.shard_stats) > 3:
            recent_rate = self.shard_stats[-1]["task_hit_rate"]
            drop = self.baseline_task_rate - recent_rate
            if drop > CONFIG["max_task_drop"]:
                return f"TASK 命中率下降 {drop*100:.1f}%（基线: {self.baseline_task_rate*100:.1f}%）"
        
        if len(self.shard_stats) >= 5:
            recent_speeds = [s["sent_per_sec"] for s in self.shard_stats[-5:]]
            avg_speed = sum(recent_speeds) / len(recent_speeds)
            variance = max(abs(s - avg_speed) / avg_speed for s in recent_speeds)
            if variance > CONFIG["max_throughput_variance"]:
                return f"吞吐波动过大: {variance*100:.1f}%"
        
        return None
    
    def get_summary(self) -> Dict:
        if not self.shard_stats:
            return {}
        
        total_sentences = sum(s["num_sentences"] for s in self.shard_stats)
        total_rpu = sum(s["num_rpu"] for s in self.shard_stats)
        total_runtime = sum(s["runtime_sec"] for s in self.shard_stats)
        
        return {
            "total_shards": len(self.shard_stats),
            "total_sentences": total_sentences,
            "total_rpu": total_rpu,
            "total_runtime_sec": total_runtime,
            "avg_sent_per_sec": total_sentences / max(0.001, total_runtime),
            "overall_task_hit_rate": total_rpu / max(1, total_sentences)
        }


# ============================================================
# 分片管理
# ============================================================
def generate_shards(csv_path: str, shard_size: int, output_dir: str) -> List[Tuple[str, int, int]]:
    """生成分片信息（带缓存）: [(shard_id, start_line, end_line), ...]"""
    cache_path = os.path.join(output_dir, "shards_cache.json")
    
    # 检查缓存
    if os.path.exists(cache_path):
        logger.info(f"加载分片缓存: {cache_path}")
        with open(cache_path, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        
        # 验证缓存有效性
        if cache.get("csv_path") == csv_path and cache.get("shard_size") == shard_size:
            shards = [tuple(s) for s in cache["shards"]]
            logger.info(f"缓存有效: {len(shards)} 个分片，总计 {cache['total_lines']:,} 篇")
            return shards
        else:
            logger.info("缓存参数不匹配，重新扫描...")
    
    # 扫描 CSV
    logger.info(f"扫描论文文件生成分片信息...")
    total_lines = 0
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for _ in reader:
            total_lines += 1
    
    logger.info(f"总论文数: {total_lines:,}")
    
    shards = []
    num_shards = (total_lines + shard_size - 1) // shard_size
    
    for i in range(num_shards):
        shard_id = f"shard_{i:04d}"
        start_line = i * shard_size
        end_line = min((i + 1) * shard_size, total_lines)
        shards.append((shard_id, start_line, end_line))
    
    # 保存缓存
    cache = {
        "csv_path": csv_path,
        "shard_size": shard_size,
        "total_lines": total_lines,
        "num_shards": len(shards),
        "shards": shards,
        "created_at": datetime.now().isoformat()
    }
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    logger.info(f"分片缓存已保存: {cache_path}")
    
    logger.info(f"生成 {len(shards)} 个分片，每片 {shard_size:,} 篇")
    return shards


def load_shard_papers(csv_path: str, start_line: int, end_line: int) -> List[Dict]:
    """加载指定分片的论文"""
    papers = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i < start_line:
                continue
            if i >= end_line:
                break
            
            abstract = row.get("abstract", "").strip()
            if not abstract:
                continue
            
            papers.append({
                "id": row.get("id", str(i)),
                "title": row.get("title", ""),
                "abstract": abstract
            })
    
    return papers


# ============================================================
# 主处理流程
# ============================================================
def process_shard(shard_id: str, papers: List[Dict], extractor: DeBERTaExtractor,
                  db: DatabaseManager, monitor: Monitor) -> Dict:
    """处理单个分片"""
    start_time = time.time()
    
    logger.info(f"[{shard_id}] 开始处理 {len(papers):,} 篇论文...")
    
    # 1. 收集所有文本
    all_texts = []
    text_to_paper = []  # (paper_idx, is_title)
    
    for i, paper in enumerate(papers):
        if paper["title"]:
            all_texts.append(paper["title"])
            text_to_paper.append((i, True))
        if paper["abstract"]:
            all_texts.append(paper["abstract"])
            text_to_paper.append((i, False))
    
    # 2. 批量分句
    split_results = extractor.split_sentences(all_texts)
    
    all_sentences = []
    sentence_map = []  # (paper_idx, local_sent_idx)
    paper_sentence_counts = [0] * len(papers)
    
    for text_idx, (paper_idx, is_title) in enumerate(text_to_paper):
        sentences = split_results[text_idx]
        for sent in sentences:
            all_sentences.append(sent)
            sentence_map.append((paper_idx, paper_sentence_counts[paper_idx]))
            paper_sentence_counts[paper_idx] += 1
    
    logger.info(f"[{shard_id}] 分句完成: {len(all_sentences):,} 个句子")
    
    # 3. 批量推理
    all_rpus = []
    batch_size = CONFIG["batch_size"]
    num_batches = (len(all_sentences) + batch_size - 1) // batch_size
    infer_start_time = time.time()
    
    for batch_idx in range(num_batches):
        batch_start = batch_idx * batch_size
        batch_end = min((batch_idx + 1) * batch_size, len(all_sentences))
        batch_sentences = all_sentences[batch_start:batch_end]
        
        inference_results = extractor.infer_batch(batch_sentences)
        
        for i, result in enumerate(inference_results):
            sent_idx = batch_start + i
            paper_idx, local_sent_idx = sentence_map[sent_idx]
            paper_id = papers[paper_idx]["id"]
            
            rpu = extractor.extract_rpu(paper_id, local_sent_idx, result)
            if rpu:
                all_rpus.append(rpu)
        
        # 进度显示（每 20 batch 或最后一个）
        if (batch_idx + 1) % 20 == 0 or batch_idx == num_batches - 1:
            elapsed = time.time() - infer_start_time
            processed = batch_end
            speed = processed / max(0.001, elapsed)
            remaining = len(all_sentences) - processed
            eta = remaining / max(1, speed)
            logger.info(f"[{shard_id}] {processed:,}/{len(all_sentences):,} sent | {speed:.0f} sent/s | ETA {eta:.0f}s | RPU {len(all_rpus):,}")
    
    # 4. 写入数据库
    db.insert_rpus(all_rpus)
    
    runtime_sec = time.time() - start_time
    task_hit_rate, empty_rate, sent_per_sec = monitor.record_shard(
        num_sentences=len(all_sentences),
        num_rpu=len(all_rpus),
        runtime_sec=runtime_sec
    )
    
    # 更新分片状态
    db.update_shard_status(
        shard_id=shard_id,
        status="done",
        num_papers=len(papers),
        num_sentences=len(all_sentences),
        num_rpu=len(all_rpus),
        runtime_sec=runtime_sec,
        task_hit_rate=task_hit_rate,
        empty_rate=empty_rate
    )
    db.commit()
    
    logger.info(f"[{shard_id}] 完成: {len(all_rpus):,} RPU, {sent_per_sec:.1f} sent/s, 耗时 {runtime_sec:.1f}s")
    
    return {
        "shard_id": shard_id,
        "num_papers": len(papers),
        "num_sentences": len(all_sentences),
        "num_rpu": len(all_rpus),
        "runtime_sec": runtime_sec,
        "sent_per_sec": sent_per_sec,
        "task_hit_rate": task_hit_rate,
        "empty_rate": empty_rate
    }


def main():
    logger.info("=" * 70)
    logger.info("DeBERTa 全量 RPU 抽取")
    logger.info(f"时间: {datetime.now().isoformat()}")
    logger.info(f"模型版本: {CONFIG['model_version']}")
    logger.info("=" * 70)
    
    # 初始化
    db_path = os.path.join(CONFIG["output_dir"], CONFIG["db_name"])
    db = DatabaseManager(db_path)
    monitor = Monitor()
    
    # 生成分片（带缓存）
    shards = generate_shards(CONFIG["input_csv"], CONFIG["shard_size"], CONFIG["output_dir"])
    
    # 初始化分片状态
    done_shards = db.get_done_shards()
    pending_shards = [(s, start, end) for s, start, end in shards if s not in done_shards]
    
    for shard_id, _, _ in shards:
        if shard_id not in done_shards:
            db.update_shard_status(shard_id, "pending")
    db.commit()
    
    logger.info(f"待处理分片: {len(pending_shards)}/{len(shards)}")
    
    if not pending_shards:
        logger.info("所有分片已完成！")
        return
    
    # 加载模型
    extractor = DeBERTaExtractor()
    
    # 处理分片
    for shard_idx, (shard_id, start_line, end_line) in enumerate(pending_shards):
        logger.info(f"\n{'='*70}")
        logger.info(f"处理分片 {shard_idx + 1}/{len(pending_shards)}: {shard_id}")
        logger.info(f"{'='*70}")
        
        # 加载论文
        papers = load_shard_papers(CONFIG["input_csv"], start_line, end_line)
        
        if not papers:
            logger.warning(f"[{shard_id}] 无有效论文，跳过")
            db.update_shard_status(shard_id, "done", error_msg="no_valid_papers")
            db.commit()
            continue
        
        # 处理分片
        result = process_shard(shard_id, papers, extractor, db, monitor)
        
        # 检查异常
        anomaly = monitor.check_anomaly()
        if anomaly:
            logger.error(f"⚠️ 检测到异常: {anomaly}")
            logger.error("建议检查后再继续运行")
            # 不自动中止，但记录警告
        
        # 保存分片元数据
        meta_path = os.path.join(CONFIG["output_dir"], f"{shard_id}_meta.json")
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        # 定期 checkpoint
        if (shard_idx + 1) % 10 == 0:
            db.checkpoint()
            logger.info("数据库检查点完成")
        
        # 释放内存
        del papers
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    
    # 最终报告
    logger.info("\n" + "=" * 70)
    logger.info("全量运行完成")
    logger.info("=" * 70)
    
    summary = monitor.get_summary()
    logger.info(f"总分片数: {summary.get('total_shards', 0)}")
    logger.info(f"总句子数: {summary.get('total_sentences', 0):,}")
    logger.info(f"总 RPU 数: {summary.get('total_rpu', 0):,}")
    logger.info(f"总耗时: {summary.get('total_runtime_sec', 0):.1f}s")
    logger.info(f"平均速度: {summary.get('avg_sent_per_sec', 0):.1f} sent/s")
    logger.info(f"TASK 命中率: {summary.get('overall_task_hit_rate', 0)*100:.2f}%")
    
    # 保存最终报告
    report_path = os.path.join(CONFIG["output_dir"], "final_report.json")
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    db.close()
    logger.info(f"报告已保存: {report_path}")


if __name__ == "__main__":
    main()
