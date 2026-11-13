# -*- coding: utf-8 -*-
"""
DeBERTa-v3 Multi-Head Token Classification 训练脚本

任务：对每个 token 独立预测其在 TASK/OBJ/ASP/CTX 中的 BIO 标签
架构：DeBERTa encoder + 4 个独立分类头
"""

import json
import os
import gc
import random
import sys
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from pathlib import Path

import psutil
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from torch.optim import AdamW
from transformers import AutoModel, AutoTokenizer, get_linear_schedule_with_warmup

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


def print_memory(tag: str = ""):
    """打印内存使用情况"""
    process = psutil.Process(os.getpid())
    cpu_mem = process.memory_info().rss / 1024**3
    if torch.cuda.is_available():
        gpu_alloc = torch.cuda.memory_allocated() / 1024**3
        gpu_reserved = torch.cuda.memory_reserved() / 1024**3
        print(f"[MEM {tag}] CPU: {cpu_mem:.2f}GB | GPU alloc: {gpu_alloc:.2f}GB | GPU reserved: {gpu_reserved:.2f}GB")
    else:
        print(f"[MEM {tag}] CPU: {cpu_mem:.2f}GB")

# ============================================================
# 配置
# ============================================================
CONFIG = {
    # 路径
    "input_json": _require_path("span_labels_path"),
    "output_dir": _require_path("deberta_model_dir"),
    
    # 模型
    "model_name": "microsoft/deberta-v3-base",
    "max_length": 256,
    
    # 训练
    "batch_size": 8,  # 折中方案
    "learning_rate": 2e-5,
    "epochs": 100,
    "warmup_ratio": 0.05,
    "weight_decay": 0.01,
    "val_split": 0.2,
    "seed": 42,
    
    # 早停
    "early_stopping": {
        "enabled": True,
        "patience": 3,  # 连续 3 个 epoch 无提升则停止
        "min_delta": 0.001,  # 最小提升阈值（F1 提升小于此值视为无提升）
        "monitor": "core_f1"  # 监控指标：core_f1 或 avg_f1
    },
    
    # 损失权重
    "loss_weights": {
        "TASK": 1.0,
        "OBJ": 1.0,
        "ASP": 0.7,
        "CTX": 0.7
    },
    
    # 字段列表
    "fields": ["TASK", "OBJ", "ASP", "CTX"]
}

# 标签映射：O=0, B=1, I=2
LABEL2ID = {"O": 0, "B": 1, "I": 2}
ID2LABEL = {0: "O", 1: "B", 2: "I"}


def set_seed(seed: int):
    """设置随机种子"""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


# ============================================================
# 数据集
# ============================================================
class SpanLabelDataset(Dataset):
    """Token-level BIO 标注数据集"""
    
    def __init__(self, samples: List[Dict], tokenizer, max_length: int, fields: List[str]):
        self.samples = samples
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.fields = fields
        
        # 缓存 tokenizer 的特殊 token id
        self.cls_id = tokenizer.cls_token_id
        self.sep_id = tokenizer.sep_token_id
        self.pad_id = tokenizer.pad_token_id
    
    def __len__(self):
        return len(self.samples)
    
    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        sample = self.samples[idx]
        tokens = sample["tokens"]
        labels = sample["labels"]
        
        # 转换 tokens → input_ids
        input_ids = self.tokenizer.convert_tokens_to_ids(tokens)
        input_ids = [self.cls_id] + input_ids + [self.sep_id]
        
        # 截断
        if len(input_ids) > self.max_length:
            input_ids = input_ids[:self.max_length - 1] + [self.sep_id]
        
        seq_len = len(input_ids)
        attention_mask = [1] * seq_len
        
        # Padding
        pad_len = self.max_length - seq_len
        input_ids = input_ids + [self.pad_id] * pad_len
        attention_mask = attention_mask + [0] * pad_len
        
        # 转换标签
        result = {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
        }
        
        for field in self.fields:
            field_labels = labels.get(field, ["O"] * len(tokens))
            
            # 映射：O=0, B-*=1, I-*=2
            mapped = [-100]  # CLS
            for lbl in field_labels:
                if lbl == "O":
                    mapped.append(0)
                elif lbl.startswith("B-"):
                    mapped.append(1)
                elif lbl.startswith("I-"):
                    mapped.append(2)
                else:
                    mapped.append(0)
            mapped.append(-100)  # SEP
            
            # 截断
            if len(mapped) > self.max_length:
                mapped = mapped[:self.max_length - 1] + [-100]
            
            # Padding
            mapped = mapped + [-100] * (self.max_length - len(mapped))
            
            result[f"label_{field}"] = torch.tensor(mapped, dtype=torch.long)
        
        return result


def collate_fn(batch: List[Dict]) -> Dict[str, torch.Tensor]:
    """批次整理"""
    result = {}
    for key in batch[0].keys():
        result[key] = torch.stack([item[key] for item in batch])
    return result


# ============================================================
# 模型
# ============================================================
class DeBERTaMultiHeadClassifier(nn.Module):
    """DeBERTa + 4 个独立分类头"""
    
    def __init__(self, model_name: str, num_labels: int = 3, fields: List[str] = None):
        super().__init__()
        self.fields = fields or CONFIG["fields"]
        
        # Backbone
        self.backbone = AutoModel.from_pretrained(model_name)
        hidden_size = self.backbone.config.hidden_size
        
        # 4 个独立分类头
        self.heads = nn.ModuleDict({
            field: nn.Linear(hidden_size, num_labels)
            for field in self.fields
        })
        
        # Dropout
        self.dropout = nn.Dropout(0.1)
    
    def forward(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor
    ) -> Dict[str, torch.Tensor]:
        # Backbone 前向传播
        outputs = self.backbone(input_ids=input_ids, attention_mask=attention_mask)
        hidden_states = outputs.last_hidden_state  # [batch, seq_len, hidden]
        hidden_states = self.dropout(hidden_states)
        
        # 各字段分类头
        logits = {}
        for field in self.fields:
            logits[field] = self.heads[field](hidden_states)  # [batch, seq_len, 3]
        
        return logits


# ============================================================
# 损失计算
# ============================================================
def compute_loss(
    logits: Dict[str, torch.Tensor],
    labels: Dict[str, torch.Tensor],
    loss_weights: Dict[str, float]
) -> Tuple[torch.Tensor, Dict[str, float]]:
    """
    计算加权多字段损失
    
    Returns:
        total_loss: 总损失
        field_losses: 各字段损失（用于日志）
    """
    criterion = nn.CrossEntropyLoss(ignore_index=-100)
    
    total_loss = 0.0
    field_losses = {}
    
    for field, field_logits in logits.items():
        field_labels = labels[f"label_{field}"]
        
        # [batch, seq_len, 3] → [batch*seq_len, 3]
        flat_logits = field_logits.view(-1, 3)
        flat_labels = field_labels.view(-1)
        
        loss = criterion(flat_logits, flat_labels)
        field_losses[field] = loss.item()
        
        weight = loss_weights.get(field, 1.0)
        total_loss = total_loss + weight * loss
    
    return total_loss, field_losses


# ============================================================
# 评估：Span F1
# ============================================================
def extract_spans(predictions: List[int]) -> List[Tuple[int, int]]:
    """
    从 BIO 预测序列提取 span
    B=1 开始，I=2 延续，O=0 结束
    
    Returns:
        List of (start, end) tuples (end exclusive)
    """
    spans = []
    start = None
    
    for i, pred in enumerate(predictions):
        if pred == 1:  # B
            if start is not None:
                spans.append((start, i))
            start = i
        elif pred == 2:  # I
            if start is None:
                start = i  # 容错：I 开头视为 B
        else:  # O
            if start is not None:
                spans.append((start, i))
                start = None
    
    if start is not None:
        spans.append((start, len(predictions)))
    
    return spans


def compute_span_f1(
    pred_spans: List[Tuple[int, int]],
    gold_spans: List[Tuple[int, int]]
) -> Tuple[float, float, float]:
    """计算 span 级 F1"""
    pred_set = set(pred_spans)
    gold_set = set(gold_spans)
    
    if len(pred_set) == 0 and len(gold_set) == 0:
        return 1.0, 1.0, 1.0
    
    if len(pred_set) == 0:
        return 0.0, 0.0, 0.0
    
    if len(gold_set) == 0:
        return 0.0, 0.0, 0.0
    
    correct = len(pred_set & gold_set)
    precision = correct / len(pred_set)
    recall = correct / len(gold_set)
    
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    
    return precision, recall, f1


def evaluate(
    model: nn.Module,
    dataloader: DataLoader,
    device: torch.device,
    fields: List[str]
) -> Dict[str, Dict[str, float]]:
    """
    验证集评估
    
    Returns:
        {field: {precision, recall, f1, token_acc}}
    """
    model.eval()
    
    # 收集所有预测和标签
    all_predictions = {field: [] for field in fields}
    all_labels = {field: [] for field in fields}
    
    # Confusion 统计
    confusion = {field: {"B_as_O": 0, "B_as_I": 0, "I_as_O": 0, "I_as_B": 0, "O_as_B": 0, "O_as_I": 0} for field in fields}
    
    with torch.no_grad():
        for batch in dataloader:
            input_ids = batch["input_ids"].to(device, non_blocking=True)
            attention_mask = batch["attention_mask"].to(device, non_blocking=True)
            
            logits = model(input_ids, attention_mask)
            
            for field in fields:
                field_logits = logits[field]  # [batch, seq_len, 3]
                field_labels = batch[f"label_{field}"]  # [batch, seq_len]
                
                preds = torch.argmax(field_logits, dim=-1).cpu().numpy()  # [batch, seq_len]
                labels_np = field_labels.numpy()
                
                # 逐样本处理
                for pred_seq, label_seq in zip(preds, labels_np):
                    # 过滤 padding（-100）
                    valid_mask = label_seq != -100
                    valid_preds = pred_seq[valid_mask].tolist()
                    valid_labels = label_seq[valid_mask].tolist()
                    
                    all_predictions[field].append(valid_preds)
                    all_labels[field].append(valid_labels)
                    
                    # Confusion 统计
                    for p, g in zip(valid_preds, valid_labels):
                        if g == 1 and p == 0:
                            confusion[field]["B_as_O"] += 1
                        elif g == 1 and p == 2:
                            confusion[field]["B_as_I"] += 1
                        elif g == 2 and p == 0:
                            confusion[field]["I_as_O"] += 1
                        elif g == 2 and p == 1:
                            confusion[field]["I_as_B"] += 1
                        elif g == 0 and p == 1:
                            confusion[field]["O_as_B"] += 1
                        elif g == 0 and p == 2:
                            confusion[field]["O_as_I"] += 1
    
    # 计算指标
    results = {}
    for field in fields:
        total_tokens = 0
        correct_tokens = 0
        total_precision = 0.0
        total_recall = 0.0
        total_f1 = 0.0
        count = 0
        
        for pred_seq, label_seq in zip(all_predictions[field], all_labels[field]):
            # Token accuracy
            for p, g in zip(pred_seq, label_seq):
                total_tokens += 1
                if p == g:
                    correct_tokens += 1
            
            # Span F1
            pred_spans = extract_spans(pred_seq)
            gold_spans = extract_spans(label_seq)
            
            # 只统计有标注或有预测的样本
            if gold_spans or pred_spans:
                p, r, f = compute_span_f1(pred_spans, gold_spans)
                total_precision += p
                total_recall += r
                total_f1 += f
                count += 1
        
        if count > 0:
            avg_precision = total_precision / count
            avg_recall = total_recall / count
            avg_f1 = total_f1 / count
        else:
            avg_precision = avg_recall = avg_f1 = 0.0
        
        token_acc = correct_tokens / total_tokens if total_tokens > 0 else 0.0
        
        results[field] = {
            "precision": avg_precision,
            "recall": avg_recall,
            "f1": avg_f1,
            "token_acc": token_acc,
            "confusion": confusion[field]
        }
    
    return results


# ============================================================
# 训练主函数
# ============================================================
def train():
    """训练主流程"""
    print("=" * 60)
    print("DeBERTa-v3 Multi-Head Token Classification 训练")
    print("=" * 60)
    
    # 设置随机种子
    set_seed(CONFIG["seed"])
    
    # 设备
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"设备: {device}")
    
    # 创建输出目录
    os.makedirs(CONFIG["output_dir"], exist_ok=True)
    
    # 加载数据
    print(f"\n加载数据: {CONFIG['input_json']}")
    print_memory("加载数据前")
    with open(CONFIG["input_json"], "r", encoding="utf-8") as f:
        all_samples = json.load(f)
    print(f"总样本数: {len(all_samples)}")
    print_memory("加载数据后")
    
    # 使用所有数据训练（不划分验证集）
    train_samples = all_samples
    print(f"训练集: {len(train_samples)} (使用所有数据)")
    
    # 加载 tokenizer
    print(f"\n加载 tokenizer: {CONFIG['model_name']}")
    tokenizer = AutoTokenizer.from_pretrained(CONFIG["model_name"])
    
    # 创建数据集
    train_dataset = SpanLabelDataset(
        train_samples, tokenizer, CONFIG["max_length"], CONFIG["fields"]
    )
    
    # DataLoader（Windows 上不用 pin_memory）
    train_loader = DataLoader(
        train_dataset,
        batch_size=CONFIG["batch_size"],
        shuffle=True,
        collate_fn=collate_fn,
        num_workers=0
    )
    
    # 创建验证集 DataLoader（用于监控，使用训练集的一部分）
    # 为了监控训练进度，从训练集中取一小部分作为验证集
    val_size = min(100, len(train_samples) // 10)  # 最多100个样本或10%
    val_samples = train_samples[:val_size]
    val_dataset = SpanLabelDataset(
        val_samples, tokenizer, CONFIG["max_length"], CONFIG["fields"]
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=CONFIG["batch_size"],
        shuffle=False,
        collate_fn=collate_fn,
        num_workers=0
    )
    print(f"验证集（仅用于监控）: {len(val_samples)} 样本")
    
    # 加载模型
    print(f"\n加载模型: {CONFIG['model_name']}")
    print_memory("加载模型前")
    model = DeBERTaMultiHeadClassifier(
        model_name=CONFIG["model_name"],
        num_labels=3,
        fields=CONFIG["fields"]
    )
    model.to(device)
    print_memory("加载模型后")
    
    # 优化器
    optimizer = AdamW(
        model.parameters(),
        lr=CONFIG["learning_rate"],
        weight_decay=CONFIG["weight_decay"]
    )
    
    # 学习率调度器
    total_steps = len(train_loader) * CONFIG["epochs"]
    warmup_steps = int(total_steps * CONFIG["warmup_ratio"])
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=warmup_steps,
        num_training_steps=total_steps
    )
    
    print(f"\n训练参数:")
    print(f"  Epochs: {CONFIG['epochs']}")
    print(f"  Batch size: {CONFIG['batch_size']}")
    print(f"  Learning rate: {CONFIG['learning_rate']}")
    print(f"  Total steps: {total_steps}")
    print(f"  Warmup steps: {warmup_steps}")
    print(f"  Loss weights: {CONFIG['loss_weights']}")
    
    # 训练日志
    training_log = []
    best_f1 = 0.0
    best_epoch = 0
    
    # 早停相关
    early_stopping = CONFIG["early_stopping"]
    if early_stopping["enabled"]:
        patience = early_stopping["patience"]
        min_delta = early_stopping["min_delta"]
        monitor = early_stopping["monitor"]
        patience_counter = 0
        print(f"\n早停已启用: patience={patience}, min_delta={min_delta}, monitor={monitor}")
    else:
        patience_counter = None
    
    # 训练循环
    print("\n" + "=" * 60)
    print("开始训练")
    print("=" * 60)
    
    for epoch in range(1, CONFIG["epochs"] + 1):
        model.train()
        epoch_loss = 0.0
        epoch_field_losses = {field: 0.0 for field in CONFIG["fields"]}
        
        for step, batch in enumerate(train_loader):
            input_ids = batch["input_ids"].to(device, non_blocking=True)
            attention_mask = batch["attention_mask"].to(device, non_blocking=True)
            labels = {k: v.to(device, non_blocking=True) for k, v in batch.items() if k.startswith("label_")}
            
            # 前向传播
            logits = model(input_ids, attention_mask)
            
            # 计算损失
            loss, field_losses = compute_loss(logits, labels, CONFIG["loss_weights"])
            
            # 反向传播
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            scheduler.step()
            
            epoch_loss += loss.item()
            for field in CONFIG["fields"]:
                epoch_field_losses[field] += field_losses[field]
            
            # 进度显示（每 10 步或第一步）
            if (step + 1) % 10 == 0 or step == 0:
                print(f"  Epoch {epoch}, Step {step + 1}/{len(train_loader)}, Loss: {loss.item():.4f}")
            # 内存监控（每 50 步）
            if (step + 1) % 50 == 0 or step == 0:
                print_memory(f"step {step + 1}")
        
        # Epoch 平均损失
        avg_epoch_loss = epoch_loss / len(train_loader)
        avg_field_losses = {f: v / len(train_loader) for f, v in epoch_field_losses.items()}
        
        print(f"\nEpoch {epoch} 训练完成")
        print(f"  平均损失: {avg_epoch_loss:.4f}")
        for field, loss_val in avg_field_losses.items():
            print(f"    {field}: {loss_val:.4f}")
        
        # 验证
        print(f"\nEpoch {epoch} 验证...")
        val_results = evaluate(model, val_loader, device, CONFIG["fields"])
        
        # 计算平均 F1（以 TASK 和 OBJ 为主）
        core_f1 = (val_results["TASK"]["f1"] + val_results["OBJ"]["f1"]) / 2
        all_f1 = sum(val_results[f]["f1"] for f in CONFIG["fields"]) / len(CONFIG["fields"])
        
        print(f"\nEpoch {epoch} 验证结果:")
        for field in CONFIG["fields"]:
            r = val_results[field]
            print(f"  {field}: P={r['precision']:.3f}, R={r['recall']:.3f}, F1={r['f1']:.3f}, TokenAcc={r['token_acc']:.3f}")
        print(f"  Core F1 (TASK+OBJ): {core_f1:.3f}")
        print(f"  Avg F1 (all): {all_f1:.3f}")
        
        # 记录日志
        epoch_log = {
            "epoch": epoch,
            "train_loss": avg_epoch_loss,
            "train_field_losses": avg_field_losses,
            "val_results": {
                field: {
                    "precision": val_results[field]["precision"],
                    "recall": val_results[field]["recall"],
                    "f1": val_results[field]["f1"],
                    "token_acc": val_results[field]["token_acc"]
                }
                for field in CONFIG["fields"]
            },
            "core_f1": core_f1,
            "avg_f1": all_f1
        }
        training_log.append(epoch_log)
        
        # 保存最优模型和早停检查
        current_metric = core_f1 if monitor == "core_f1" else all_f1
        
        if current_metric > best_f1 + min_delta:
            # 有显著提升
            improvement = current_metric - best_f1
            best_f1 = current_metric
            best_epoch = epoch
            patience_counter = 0  # 重置计数器
            
            # 保存 checkpoint
            checkpoint_path = os.path.join(CONFIG["output_dir"], "best_model.pt")
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "scheduler_state_dict": scheduler.state_dict(),
                "best_f1": best_f1,
                "config": CONFIG
            }, checkpoint_path)
            print(f"  *** 新最优模型已保存 ({monitor}: {best_f1:.3f}, 提升: +{improvement:.3f}) ***")
        else:
            # 无提升
            if early_stopping["enabled"]:
                patience_counter += 1
                if patience_counter >= patience:
                    print(f"\n  ⚠️  早停触发: {monitor} 连续 {patience} 个 epoch 无提升")
                    print(f"  最优 {monitor}: {best_f1:.3f} (Epoch {best_epoch})")
                    break
                else:
                    print(f"  [早停] {monitor} 无提升 ({patience_counter}/{patience})")
        
        print("-" * 60)
    
    # 训练完成
    print("\n" + "=" * 60)
    print("训练完成")
    print("=" * 60)
    print(f"最优 Epoch: {best_epoch}")
    print(f"最优 Core F1: {best_f1:.3f}")
    
    # 保存训练日志
    log_path = os.path.join(CONFIG["output_dir"], "training_log.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(training_log, f, indent=2, ensure_ascii=False)
    print(f"\n训练日志已保存: {log_path}")
    
    # 加载最优模型进行最终验证
    print("\n加载最优模型进行最终验证...")
    checkpoint = torch.load(os.path.join(CONFIG["output_dir"], "best_model.pt"))
    model.load_state_dict(checkpoint["model_state_dict"])
    
    final_results = evaluate(model, val_loader, device, CONFIG["fields"])
    
    # 保存验证报告
    validation_report = {
        "best_epoch": best_epoch,
        "best_core_f1": best_f1,
        "timestamp": datetime.now().isoformat(),
        "config": CONFIG,
        "field_results": {}
    }
    
    print("\n最终验证结果:")
    for field in CONFIG["fields"]:
        r = final_results[field]
        print(f"  {field}:")
        print(f"    Precision: {r['precision']:.4f}")
        print(f"    Recall:    {r['recall']:.4f}")
        print(f"    F1:        {r['f1']:.4f}")
        print(f"    TokenAcc:  {r['token_acc']:.4f}")
        
        validation_report["field_results"][field] = {
            "precision": r["precision"],
            "recall": r["recall"],
            "f1": r["f1"],
            "token_acc": r["token_acc"]
        }
    
    report_path = os.path.join(CONFIG["output_dir"], "validation_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(validation_report, f, indent=2, ensure_ascii=False)
    print(f"\n验证报告已保存: {report_path}")
    
    # 保存 Confusion 分析
    confusion_report = {field: final_results[field]["confusion"] for field in CONFIG["fields"]}
    confusion_path = os.path.join(CONFIG["output_dir"], "confusion_analysis.json")
    with open(confusion_path, "w", encoding="utf-8") as f:
        json.dump(confusion_report, f, indent=2, ensure_ascii=False)
    print(f"Confusion 分析已保存: {confusion_path}")
    
    print("\n" + "=" * 60)
    print("全部完成")
    print("=" * 60)


if __name__ == "__main__":
    train()
