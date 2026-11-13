"""
研究行为结构化抽取模型训练脚本

用于微调 T5-Base 模型，从科研论文英文句子中抽取结构化字段：
Task（研究动作）、Object（研究对象）、Aspect（研究方面）、Context（研究语境）

================================================================================
训练数据格式要求（TSV/CSV文件）
================================================================================

数据文件格式：
  - 支持 TSV（.tsv）或 CSV（.csv）格式
  - 字段分隔符：␟（U+241F，不可见字符）
  - 必需列：sentence, Task, Object, Aspect, Context

数据格式说明：
1. sentence：英文原文句子（title 或 abstract 中的句子）
2. Task：研究动作动词或动词短语（例如 propose、evaluate、determine），如果不存在则为 null
3. Object：Task 直接作用的名词短语，如果不存在则为 null
4. Aspect：Object 的被研究部分（如 accuracy、efficiency），如果不存在则为 null
5. Context：研究语境、条件或用途，如果不存在则为 null

输出格式：
  模型输出固定格式：JSON数组 ["Task", "Object", "Aspect", "Context"]
  其中 null 表示该字段不存在

数据示例（TSV格式）：
sentence | Task | Object | Aspect | Context
---------|------|--------|--------|--------
In this study, we propose a method to determine an optimal threshold under a fixed sample size of 500. | propose | a method | null | In this study
We evaluate the performance on multiple tasks. | evaluate | the performance | null | null
The objective was to determine the threshold at which low plasma levels are associated with fractures. | determine | the threshold | null | null

输出示例：
  输入: "extract: In this study, we propose a method..."
  输出: ["propose", "a method", "null", "In this study"]

数据量要求：
  - 最少：500-1000 条样本
  - 建议：2000+ 条样本
  - 验证集：建议 20% 作为验证集

数据质量要求：
1. 标注准确性：所有字段必须严格遵守原文，禁止推测或自由发挥
2. 非研究行为句：所有字段必须为 null
3. 字段完整性：每个字段要么是原文片段，要么是 null
4. 多样性：覆盖不同类型的动词和句子结构
"""

import os
import csv
import json
import sys
import torch
import pandas as pd
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from torch.utils.data import Dataset
from transformers import (
    T5ForConditionalGeneration,
    T5Tokenizer,
    TrainingArguments,
    Trainer,
    DataCollatorForSeq2Seq
)
from sklearn.model_selection import train_test_split
import logging

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import load_project_config, get_paths

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_cfg = load_project_config()
_paths = get_paths(_cfg)


def _require_path(key: str) -> str:
    value = _paths.get(key)
    if value:
        return value
    raise KeyError(f"Missing required path key in project config: paths.{key}")


DEFAULT_TRAIN_DATA_FILE = _require_path("training_data_excel_path")
DEFAULT_OUTPUT_DIR = _require_path("research_structure_model_dir")

# 字段分隔符（U+241F，不可见字符）
SEPARATOR = '\u241F'


class ResearchStructureDataset(Dataset):
    """研究行为结构化抽取数据集"""
    
    def __init__(self, data_file: str, tokenizer: T5Tokenizer, 
                 max_input_length: int = 512, max_output_length: int = 128):
        """
        初始化数据集
        
        参数:
            data_file: 训练数据文件路径（TSV或CSV格式）
            tokenizer: T5 tokenizer
            max_input_length: 输入最大长度
            max_output_length: 输出最大长度
        """
        self.tokenizer = tokenizer
        self.max_input_length = max_input_length
        self.max_output_length = max_output_length
        
        # 加载数据
        logger.info(f"从文件加载数据: {data_file}")
        self.samples = self._load_data(data_file)
        logger.info(f"成功加载 {len(self.samples)} 个训练样本")
    
    def _load_data(self, data_file: str) -> List[Dict[str, str]]:
        """加载数据文件（支持TSV、CSV和Excel）"""
        file_path = Path(data_file)
        
        if not file_path.exists():
            raise FileNotFoundError(f"训练数据文件不存在: {data_file}")
        
        samples = []
        required_columns = ['sentence', 'Task', 'Object', 'Aspect', 'Context']
        
        # 读取数据（支持Excel、TSV、CSV）
        file_ext = file_path.suffix.lower()
        if file_ext in ['.xlsx', '.xls']:
            df = pd.read_excel(data_file)
        elif file_ext == '.tsv':
            df = pd.read_csv(data_file, delimiter='\t', encoding='utf-8')
        elif file_ext == '.csv':
            df = pd.read_csv(data_file, delimiter=',', encoding='utf-8')
        else:
            # 尝试自动检测
            try:
                df = pd.read_excel(data_file)
            except:
                with open(data_file, 'r', encoding='utf-8') as f:
                    first_line = f.readline()
                    delimiter = '\t' if '\t' in first_line else ','
                df = pd.read_csv(data_file, delimiter=delimiter, encoding='utf-8')
        
        # 检查必需列
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValueError(f"数据文件缺少必需的列: {missing_columns}")
        
        # 处理数据
        for idx, row in df.iterrows():
            sentence = str(row['sentence']).strip()
            if not sentence:
                continue
            
            # 获取字段值，处理空值和null
            task = self._normalize_field(str(row.get('Task', '')).strip())
            object_field = self._normalize_field(str(row.get('Object', '')).strip())
            aspect = self._normalize_field(str(row.get('Aspect', '')).strip())
            context = self._normalize_field(str(row.get('Context', '')).strip())
            
            # 构建输出格式：JSON数组 ["Task", "Object", "Aspect", "Context"]
            output_list = [task, object_field, aspect, context]
            output_text = json.dumps(output_list, ensure_ascii=False)
            
            samples.append({
                'sentence': sentence,
                'task': task,
                'object': object_field,
                'aspect': aspect,
                'context': context,
                'output': output_text
            })
        
        return samples
    
    def _normalize_field(self, value: str) -> str:
        """规范化字段值：空值或'null'统一为'null'"""
        if not value or value.lower() == 'null' or value.lower() == 'none':
            return 'null'
        return value
    
    def __len__(self) -> int:
        return len(self.samples)
    
    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        """获取单个样本"""
        sample = self.samples[idx]
        
        # 输入格式：extract: {sentence}
        input_text = f"extract: {sample['sentence']}"
        
        # 输出格式：Task ␟ Object ␟ Aspect ␟ Context
        output_text = sample['output']
        
        # Tokenize输入
        input_encoding = self.tokenizer(
            input_text,
            max_length=self.max_input_length,
            padding='max_length',
            truncation=True,
            return_tensors='pt'
        )
        
        # Tokenize输出（作为标签）
        output_encoding = self.tokenizer(
            output_text,
            max_length=self.max_output_length,
            padding='max_length',
            truncation=True,
            return_tensors='pt'
        )
        
        # 将pad token的标签设置为-100（忽略）
        labels = output_encoding['input_ids'].clone()
        labels[labels == self.tokenizer.pad_token_id] = -100
        
        return {
            'input_ids': input_encoding['input_ids'].squeeze(),
            'attention_mask': input_encoding['attention_mask'].squeeze(),
            'labels': labels.squeeze()
        }


def create_compute_metrics(tokenizer: T5Tokenizer):
    """创建计算评估指标的函数（闭包，避免硬编码tokenizer）"""
    def compute_metrics(eval_pred) -> Dict[str, float]:
        """计算评估指标"""
        predictions, labels = eval_pred
        
        # 将token ids转换为文本
        decoded_preds = tokenizer.batch_decode(predictions, skip_special_tokens=True)
        decoded_labels = tokenizer.batch_decode(labels, skip_special_tokens=True)
        
        # 解析字段
        total_samples = len(decoded_preds)
        task_correct = 0
        object_correct = 0
        aspect_correct = 0
        context_correct = 0
        format_correct = 0
        parse_success = 0
        
        for pred, label in zip(decoded_preds, decoded_labels):
            # 解析预测结果（JSON格式）
            try:
                pred_fields = json.loads(pred)
                if not isinstance(pred_fields, list):
                    pred_fields = []
            except (json.JSONDecodeError, ValueError):
                pred_fields = []
            
            try:
                label_fields = json.loads(label)
                if not isinstance(label_fields, list):
                    label_fields = []
            except (json.JSONDecodeError, ValueError):
                label_fields = []
            
            # 检查格式正确性（4个字段）
            if len(pred_fields) == 4 and len(label_fields) == 4:
                format_correct += 1
                parse_success += 1
                
                # 字段准确率（忽略大小写和空格）
                if str(pred_fields[0]).strip().lower() == str(label_fields[0]).strip().lower():
                    task_correct += 1
                if str(pred_fields[1]).strip().lower() == str(label_fields[1]).strip().lower():
                    object_correct += 1
                if str(pred_fields[2]).strip().lower() == str(label_fields[2]).strip().lower():
                    aspect_correct += 1
                if str(pred_fields[3]).strip().lower() == str(label_fields[3]).strip().lower():
                    context_correct += 1
            else:
                # 格式错误
                if len(pred_fields) == 4:
                    parse_success += 1
        
        metrics = {
            'task_accuracy': task_correct / total_samples if total_samples > 0 else 0.0,
            'object_accuracy': object_correct / total_samples if total_samples > 0 else 0.0,
            'aspect_accuracy': aspect_correct / total_samples if total_samples > 0 else 0.0,
            'context_accuracy': context_correct / total_samples if total_samples > 0 else 0.0,
            'format_accuracy': format_correct / total_samples if total_samples > 0 else 0.0,
            'parse_success_rate': parse_success / total_samples if total_samples > 0 else 0.0,
            'overall_accuracy': (task_correct + object_correct + aspect_correct + context_correct) / (total_samples * 4) if total_samples > 0 else 0.0
        }
        
        return metrics
    
    return compute_metrics


def train_research_structure_model(
    train_data_file: str,
    output_dir: str,
    model_name: str = "t5-base",
    eval_data_file: Optional[str] = None,
    num_epochs: int = 3,
    batch_size: int = 16,
    learning_rate: float = 3e-4,
    max_input_length: int = 512,
    max_output_length: int = 128,
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
):
    """
    训练研究行为结构化抽取模型
    
    参数:
        train_data_file: 训练数据文件路径（TSV/CSV格式）
        output_dir: 模型输出目录
        model_name: 基础模型名称（默认 t5-base）
        eval_data_file: 验证数据文件路径（可选）
        num_epochs: 训练轮数
        batch_size: 批次大小
        learning_rate: 学习率
        max_input_length: 输入最大长度
        max_output_length: 输出最大长度
        device: 设备（cuda/cpu）
    """
    logger.info(f"开始训练研究行为结构化抽取模型，基础模型: {model_name}")
    logger.info(f"设备: {device}")
    
    # 加载模型和tokenizer
    logger.info(f"加载模型和tokenizer: {model_name}")
    tokenizer = T5Tokenizer.from_pretrained(model_name)
    model = T5ForConditionalGeneration.from_pretrained(model_name)
    model.to(device)
    
    # 创建数据集
    train_dataset = ResearchStructureDataset(
        train_data_file, 
        tokenizer, 
        max_input_length=max_input_length,
        max_output_length=max_output_length
    )
    
    eval_dataset = None
    if eval_data_file:
        eval_dataset = ResearchStructureDataset(
            eval_data_file,
            tokenizer,
            max_input_length=max_input_length,
            max_output_length=max_output_length
        )
    
    # 数据整理器
    data_collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer,
        model=model,
        padding=True
    )
    
    # 训练参数
    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=num_epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size if eval_dataset else None,
        gradient_accumulation_steps=8,
        learning_rate=learning_rate,
        weight_decay=0.01,
        logging_dir=f"{output_dir}/logs",
        logging_steps=100,
        eval_strategy="epoch" if eval_dataset else "no",
        save_strategy="epoch",
        save_total_limit=3,
        load_best_model_at_end=True if eval_dataset else False,
        metric_for_best_model="eval_loss" if eval_dataset else None,
        greater_is_better=False,
        warmup_steps=500,
        fp16=torch.cuda.is_available(),
    )
    
    # 评估阶段禁用compute_metrics，避免显存累积
    # 结构化准确率评估应在训练结束后用独立脚本进行
    compute_metrics_fn = None
    
    # 创建Trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=data_collator,
        tokenizer=tokenizer,
        compute_metrics=compute_metrics_fn,
    )
    
    # 开始训练
    logger.info("开始训练...")
    trainer.train()
    
    # 保存模型
    logger.info(f"保存模型到 {output_dir}")
    trainer.save_model()
    tokenizer.save_pretrained(output_dir)
    
    logger.info("训练完成！")


if __name__ == "__main__":
    # ========== 路径配置（来自 project_config） ==========
    TRAIN_DATA_FILE = DEFAULT_TRAIN_DATA_FILE
    OUTPUT_DIR = DEFAULT_OUTPUT_DIR
    
    # 基础模型名称
    MODEL_NAME = "t5-base"
    
    # 训练参数
    NUM_EPOCHS = 3
    BATCH_SIZE = 2
    LEARNING_RATE = 3e-4
    MAX_INPUT_LENGTH = 512
    MAX_OUTPUT_LENGTH = 64
    
    # 验证集比例（从训练数据中自动分割）
    VALIDATION_SPLIT = 0.2
    RANDOM_SEED = 42
    # ===================================
    
    # 读取训练数据
    logger.info(f"读取训练数据: {TRAIN_DATA_FILE}")

    
    df = pd.read_excel(TRAIN_DATA_FILE)
    
    # 自动分割训练集和验证集
    if VALIDATION_SPLIT > 0:
        train_df, eval_df = train_test_split(
            df,
            test_size=VALIDATION_SPLIT,
            random_state=RANDOM_SEED,
            shuffle=True
        )
        logger.info(f"数据分割完成：训练集 {len(train_df)} 条，验证集 {len(eval_df)} 条")
        
        # 保存临时文件
        temp_dir = Path(OUTPUT_DIR) / "tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        train_temp_file = str(temp_dir / "research_structure_train_temp.tsv")
        eval_temp_file = str(temp_dir / "research_structure_eval_temp.tsv")
        train_df.to_csv(train_temp_file, sep='\t', index=False, encoding='utf-8')
        eval_df.to_csv(eval_temp_file, sep='\t', index=False, encoding='utf-8')
        
        train_file = train_temp_file
        eval_file = eval_temp_file
    else:
        train_file = TRAIN_DATA_FILE
        eval_file = None
        logger.info("未设置验证集分割，将只进行训练")
    
    # 开始训练
    train_research_structure_model(
        train_data_file=train_file,
        output_dir=OUTPUT_DIR,
        model_name=MODEL_NAME,
        eval_data_file=eval_file,
        num_epochs=NUM_EPOCHS,
        batch_size=BATCH_SIZE,
        learning_rate=LEARNING_RATE,
        max_input_length=MAX_INPUT_LENGTH,
        max_output_length=MAX_OUTPUT_LENGTH
    )
    
    # 清理临时文件
    if VALIDATION_SPLIT > 0:
        if os.path.exists(train_temp_file):
            os.remove(train_temp_file)
        if os.path.exists(eval_temp_file):
            os.remove(eval_temp_file)
        logger.info("已清理临时文件")

