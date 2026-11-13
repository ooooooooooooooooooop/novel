# -*- coding: utf-8 -*-
"""
结构化 RPU 标签 → token-level span 标注

原则：
1. 只做对齐，不做推断
2. 对齐失败 = absent（全 O）
3. 允许 partial/fuzzy match
4. 字段彼此独立

不引入任何模型、不引入任何推理、不做任何"聪明优化"
"""

import json
import re
import os
import sys
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from transformers import AutoTokenizer
import pandas as pd

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


# ============================================================
# 配置
# ============================================================
TOKENIZER_NAME = "microsoft/deberta-v3-base"  # 统一使用 DeBERTa tokenizer

# 输入输出路径（来自 project_config）
INPUT_EXCEL = _require_path("training_data_excel_path")
OUTPUT_JSON = _require_path("span_labels_path")
OUTPUT_FAILED_JSON = _require_path("alignment_failed_samples_path")  # 对齐失败样本

# 对齐策略配置
USE_LEMMATIZATION_FOR_ALIGNMENT = True  # 是否使用词形还原辅助对齐（需要 nltk）

# 可选：使用词形还原辅助对齐（轻量级，仅用于对齐，不做语义推断）
lemmatizer = None
if USE_LEMMATIZATION_FOR_ALIGNMENT:
    try:
        import nltk
        from nltk.stem import WordNetLemmatizer
        # 确保下载 wordnet 数据
        try:
            nltk.data.find('tokenizers/punkt')
        except LookupError:
            nltk.download('punkt', quiet=True)
        try:
            nltk.data.find('corpora/wordnet')
        except LookupError:
            nltk.download('wordnet', quiet=True)
        
        lemmatizer = WordNetLemmatizer()
        USE_LEMMATIZATION = True
    except ImportError:
        USE_LEMMATIZATION = False
        print("警告: nltk 未安装，将仅使用规则匹配。安装命令: pip install nltk")
else:
    USE_LEMMATIZATION = False


# ============================================================
# 字段值预处理（只允许这 3 件事）
# ============================================================
def preprocess_field_value(value: str) -> str:
    """
    字段值预处理
    
    允许：
    1. lower-case
    2. strip 空格 / 标点
    3. collapse 连续空格
    
    不允许：同义词替换、词形还原、翻译、拆分重组
    """
    if not value:
        return ""
    
    # 1. lower-case
    value = value.lower()
    
    # 2. strip 空格和标点（只去掉首尾）
    value = value.strip()
    
    # 3. collapse 连续空格
    value = re.sub(r'\s+', ' ', value)
    
    return value


# ============================================================
# 宽松匹配规则（白名单化）
# ============================================================
# 允许的等价规则（仅限以下三种）
ARTICLE_WORDS = {'a', 'an', 'the'}  # 冠词集合（可忽略）

def get_word_pos(word: str) -> str:
    """获取词性（用于词形还原）"""
    # 简单启发式：根据常见动词/名词模式判断
    # 这不是真正的 POS tagging，只是辅助词形还原
    if word.endswith(('ed', 'ing', 'es', 's')) and len(word) > 3:
        return 'v'  # 可能是动词
    elif word.endswith('s') and len(word) > 2:
        return 'n'  # 可能是名词复数
    return 'n'  # 默认名词


def normalize_word_for_match(word: str, use_lemmatization: bool = None) -> str:
    """
    词级标准化（仅用于宽松匹配）
    
    使用词形还原（lemmatization）处理词形变化
    移除冠词
    """
    word = word.lower().strip()
    
    # 直接映射：针对已知失败案例的一对一优化（优先处理）
    direct_mapping = {
        'discussed': 'discuss',
        'discusses': 'discuss',
        'discuss': 'discuss',  # 防止词形还原错误（discuss -> discus）
        'proves': 'prove',
        'proved': 'prove',
        'prove': 'prove',  # 防止词形还原错误
        'focusses': 'focus',
        'focuses': 'focus',
        'focused': 'focus',
        'focus': 'focus',  # 防止词形还原错误
        'uses': 'use',
        'used': 'use',
        'use': 'use',  # 防止词形还原错误
        'found': 'find',
        'finds': 'find',
        'find': 'find',  # 防止词形还原错误
    }
    if word in direct_mapping:
        return direct_mapping[word]
    
    # 如果启用词形还原，使用词形还原
    if (use_lemmatization is None and USE_LEMMATIZATION) or (use_lemmatization is True):
        if lemmatizer is not None:
            try:
                # 尝试动词和名词两种词性，选择更短的结果（通常是词根）
                lemmatized_v = lemmatizer.lemmatize(word, pos='v')
                lemmatized_n = lemmatizer.lemmatize(word, pos='n')
                # 如果词形还原有效（结果不同），使用更短的结果
                # 但需要验证：词形还原结果应该是原词的前缀（避免 discus 这样的错误）
                if lemmatized_v != word or lemmatized_n != word:
                    candidate = None
                    # 优先选择是原词前缀的结果
                    if word.startswith(lemmatized_v) and len(word) - len(lemmatized_v) <= 3:
                        candidate = lemmatized_v
                    elif word.startswith(lemmatized_n) and len(word) - len(lemmatized_n) <= 3:
                        candidate = lemmatized_n
                    # 如果都不是前缀，选择更短的（但可能不可靠）
                    elif not candidate:
                        if len(lemmatized_v) <= len(lemmatized_n):
                            candidate = lemmatized_v
                        else:
                            candidate = lemmatized_n
                    if candidate:
                        word = candidate
                # 如果词形还原没有改变词（如 "focusses" -> "focusses"），尝试简单规则处理
                # 仅处理明显的双写形式（词形还原无法处理的情况）
                elif len(word) > 5 and word.endswith('sses') and word[-5] == word[-6]:
                    # 双写 + es，如 focusses -> focus
                    word = word[:-4] + 's'
            except:
                # 如果词形还原失败，保持原词
                pass
    
    # 移除冠词
    if word in ARTICLE_WORDS:
        return ""
    
    return word


# ============================================================
# spaCy lemmatizer（基于模型的词形还原）
# ============================================================
_spacy_nlp = None

def get_spacy_nlp():
    """懒加载 spaCy 模型"""
    global _spacy_nlp
    if _spacy_nlp is None:
        import spacy
        _spacy_nlp = spacy.load("en_core_web_sm")
    return _spacy_nlp


def lemmatize_with_spacy(text: str) -> str:
    """使用 spaCy 模型进行词形还原"""
    nlp = get_spacy_nlp()
    doc = nlp(text)
    return " ".join([token.lemma_.lower() for token in doc])


def lemmatize_tokens_with_spacy(tokens: List[str]) -> List[str]:
    """对 tokens 列表进行词形还原"""
    nlp = get_spacy_nlp()
    # 将 tokens 拼接成文本（处理 subword 前缀）
    text_parts = []
    for tok in tokens:
        if tok.startswith('▁'):
            text_parts.append(' ' + tok.replace('▁', ''))
        else:
            text_parts.append(tok.replace('##', ''))
    text = ''.join(text_parts).strip()
    
    # spaCy 处理
    doc = nlp(text)
    
    # 将 spaCy 的 lemmas 映射回原始 tokens
    # 需要处理 subword 对齐
    lemmatized = []
    spacy_idx = 0
    spacy_tokens = [(token.text.lower(), token.lemma_.lower()) for token in doc]
    
    for tok in tokens:
        tok_clean = tok.replace('##', '').replace('▁', '').lower()
        
        # 查找匹配的 spaCy token
        found = False
        for j in range(spacy_idx, len(spacy_tokens)):
            spacy_text, spacy_lemma = spacy_tokens[j]
            # 检查是否包含当前 subword
            if tok_clean in spacy_text or spacy_text.startswith(tok_clean) or tok_clean.startswith(spacy_text):
                lemmatized.append(spacy_lemma if tok_clean == spacy_text else tok_clean)
                if tok_clean == spacy_text:
                    spacy_idx = j + 1
                found = True
                break
        
        if not found:
            lemmatized.append(tok_clean)
    
    return lemmatized


# ============================================================
# Span 对齐规则（精确匹配 + 基于模型的 lemma 匹配）
# ============================================================
def find_span_in_tokens(
    field_value: str,
    tokens: List[str],
    tokenizer
) -> Tuple[Optional[Tuple[int, int]], str]:
    """
    在 tokens 中找 field_value 的 span
    
    规则：
    1. 精确 token 子序列匹配（优先）
    2. 基于 spaCy 模型的 lemma 匹配（处理动词词形变化）
    
    返回: ((start_idx, end_idx) 或 None, match_type)
    match_type: "exact" | "lemma" | "none"
    """
    if not field_value:
        return None, "none"
    
    # 预处理字段值（字符串级标准化）
    field_value = preprocess_field_value(field_value)
    if not field_value:
        return None, "none"
    
    # 精确 token 子序列匹配
    field_tokens = tokenizer.tokenize(field_value)
    field_tokens_clean = [t.replace('##', '').replace('▁', '').lower() for t in field_tokens]
    
    # Step 1: 精确匹配
    for i in range(len(tokens) - len(field_tokens_clean) + 1):
        candidate = tokens[i:i + len(field_tokens_clean)]
        candidate_clean = [t.replace('##', '').replace('▁', '').lower() for t in candidate]
        
        if candidate_clean == field_tokens_clean:
            return (i, i + len(field_tokens_clean)), "exact"
    
    # Step 2: 基于 spaCy 模型的 lemma 匹配
    # 对字段值进行 lemmatization
    field_lemma = lemmatize_with_spacy(field_value)
    field_lemma_tokens = field_lemma.split()
    
    # 对句子 tokens 进行 lemmatization
    tokens_clean = [t.replace('##', '').replace('▁', '').lower() for t in tokens]
    
    # 构建句子文本并获取 lemmas
    nlp = get_spacy_nlp()
    text_parts = []
    for tok in tokens:
        if tok.startswith('▁'):
            text_parts.append(' ' + tok.replace('▁', ''))
        else:
            text_parts.append(tok.replace('##', ''))
    sentence_text = ''.join(text_parts).strip()
    doc = nlp(sentence_text)
    
    # 构建 token 到 lemma 的映射（需要处理 subword 分词）
    # 简化方法：基于字符位置映射
    token_lemmas = []
    char_pos = 0
    doc_idx = 0
    
    for tok in tokens:
        tok_clean = tok.replace('##', '').replace('▁', '').lower()
        
        # 查找对应的 spaCy token
        lemma = tok_clean  # 默认使用原词
        for j in range(doc_idx, len(doc)):
            if doc[j].text.lower() == tok_clean:
                lemma = doc[j].lemma_.lower()
                doc_idx = j + 1
                break
            # 处理 subword：如果 spaCy token 包含当前 subword
            elif tok_clean in doc[j].text.lower():
                lemma = tok_clean  # subword 保持原样
                break
        
        token_lemmas.append(lemma)
    
    # 在 lemmatized tokens 中搜索 field lemma
    for i in range(len(token_lemmas) - len(field_lemma_tokens) + 1):
        candidate_lemmas = token_lemmas[i:i + len(field_lemma_tokens)]
        
        if candidate_lemmas == field_lemma_tokens:
            return (i, i + len(field_lemma_tokens)), "lemma"
    
    # 无法匹配
    return None, "none"


# ============================================================
# 标注 BIO
# ============================================================
def create_bio_labels(
    num_tokens: int,
    span: Optional[Tuple[int, int]],
    field_name: str
) -> List[str]:
    """
    创建 BIO 标签序列
    
    Args:
        num_tokens: token 数量
        span: (start_idx, end_idx) 或 None
        field_name: 字段名（TASK, OBJECT, ASPECT, CONTEXT）
    
    Returns:
        BIO 标签列表
    """
    labels = ['O'] * num_tokens
    
    if span is None:
        return labels  # 对齐失败 = 全 O
    
    start, end = span
    
    if start < num_tokens:
        labels[start] = f'B-{field_name}'
        for i in range(start + 1, min(end, num_tokens)):
            labels[i] = f'I-{field_name}'
    
    return labels


# ============================================================
# 主转换函数
# ============================================================
def convert_rpu_to_spans(
    sentence: str,
    rpu_label: Dict[str, Optional[str]],
    tokenizer
) -> Dict:
    """
    将结构化 RPU 标签转换为 token-level span 标注
    
    Args:
        sentence: 输入句子
        rpu_label: {
            "task": str | null,
            "object": str | null,
            "aspect": str | null,
            "context": str | null
        }
        tokenizer: DeBERTa tokenizer
    
    Returns:
        {
            "tokens": [t1, t2, ..., tn],
            "labels": {
                "TASK": ["O", "B-TASK", "I-TASK", ...],
                "OBJ": ["O", "B-OBJ", "I-OBJ", ...],
                "ASP": ["O", "B-ASP", "I-ASP", ...],
                "CTX": ["O", "B-CTX", "I-CTX", ...]
            },
            "alignment_info": {
                "task": {"has_original_value": bool, "match_type": str, "matched": bool},
                ...
            }
        }
    """
    # Step 1: 统一分词
    tokens = tokenizer.tokenize(sentence)
    
    # Step 2-5: 对每个字段进行对齐和标注
    labels = {}
    
    # 字段映射（RPU 字段名 → 标签前缀）
    field_mapping = {
        "task": "TASK",
        "object": "OBJ",      # 使用 OBJ 而非 OBJECT（更简洁）
        "aspect": "ASP",
        "context": "CTX"
    }
    
    # 记录对齐信息（用于统计）
    alignment_info = {}
    
    for field_key, label_prefix in field_mapping.items():
        field_value = rpu_label.get(field_key)
        
        # 字段值为空 / null → 全 O
        if not field_value:
            labels[label_prefix] = create_bio_labels(len(tokens), None, label_prefix)
            alignment_info[field_key] = {
                "has_original_value": False,
                "match_type": "none",
                "matched": False
            }
            continue
        
        # 找 span（返回 span 和匹配类型）
        span, match_type = find_span_in_tokens(field_value, tokens, tokenizer)
        
        # 标注 BIO（对齐失败 → span=None → 全 O）
        labels[label_prefix] = create_bio_labels(len(tokens), span, label_prefix)
        
        # 记录对齐信息
        alignment_info[field_key] = {
            "has_original_value": True,
            "match_type": match_type,
            "matched": span is not None
        }
    
    return {
        "tokens": tokens,
        "labels": labels,
        "alignment_info": alignment_info  # 用于统计
    }
    
    return {
        "tokens": tokens,
        "labels": labels
    }


# ============================================================
# 读取 Excel 文件
# ============================================================
def load_excel_data(excel_path: str) -> List[Dict]:
    """
    从 Excel 文件读取训练数据
    
    Excel 格式：
    - sentence: 句子
    - Task: Task 字段
    - Object: Object 字段
    - Aspect: Aspect 字段
    - Context: Context 字段
    
    Returns:
        [
            {
                "sentence": str,
                "rpu_label": {
                    "task": str | null,
                    "object": str | null,
                    "aspect": str | null,
                    "context": str | null
                }
            },
            ...
        ]
    """
    import pandas as pd
    
    print(f"读取 Excel 文件: {excel_path}")
    df = pd.read_excel(excel_path)
    
    data = []
    for _, row in df.iterrows():
        sentence = str(row.get("sentence", "")).strip()
        if not sentence or sentence == "nan":
            continue
        
        # 构建 rpu_label
        rpu_label = {
            "task": None,
            "object": None,
            "aspect": None,
            "context": None
        }
        
        # 读取各字段（处理 NaN）
        for field in ["Task", "Object", "Aspect", "Context"]:
            value = row.get(field)
            if pd.notna(value) and str(value).strip():
                rpu_label[field.lower()] = str(value).strip()
        
        data.append({
            "sentence": sentence,
            "rpu_label": rpu_label
        })
    
    print(f"加载 {len(data)} 条有效样本")
    return data


# ============================================================
# 批量转换
# ============================================================
def convert_dataset(
    input_data: List[Dict],
    output_path: str,
    tokenizer_name: str = TOKENIZER_NAME
):
    """
    批量转换数据集
    
    Args:
        input_data: [
            {
                "sentence": str,
                "rpu_label": {
                    "task": str | null,
                    "object": str | null,
                    "aspect": str | null,
                    "context": str | null
                }
            },
            ...
        ]
        output_path: 输出 JSON 文件路径
        tokenizer_name: tokenizer 名称
    """
    print(f"加载 tokenizer: {tokenizer_name}")
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)
    
    print(f"转换 {len(input_data)} 条样本...")
    
    converted = []
    failed_samples = []  # 对齐失败的样本
    stats = {
        "total": len(input_data),
        # 基础统计
        "task_present": 0,
        "object_present": 0,
        "aspect_present": 0,
        "context_present": 0,
        "task_absent": 0,
        "object_absent": 0,
        "aspect_absent": 0,
        "context_absent": 0,
        # 对齐统计（诊断性指标）
        "task_exact_match": 0,
        "task_lemma_match": 0,
        "task_fuzzy_match": 0,
        "task_alignment_failed": 0,
        "object_exact_match": 0,
        "object_lemma_match": 0,
        "object_fuzzy_match": 0,
        "object_alignment_failed": 0,
        "aspect_exact_match": 0,
        "aspect_lemma_match": 0,
        "aspect_fuzzy_match": 0,
        "aspect_alignment_failed": 0,
        "context_exact_match": 0,
        "context_lemma_match": 0,
        "context_fuzzy_match": 0,
        "context_alignment_failed": 0,
    }
    
    # 完整对齐统计
    complete_success = 0
    partial_success = 0
    
    for item in input_data:
        sentence = item.get("sentence", "").strip()
        rpu_label = item.get("rpu_label", {})
        
        if not sentence:
            continue
        
        # 转换
        result = convert_rpu_to_spans(sentence, rpu_label, tokenizer)
        alignment_info = result.get("alignment_info", {})
        
        # 检查是否所有有值字段都对齐成功
        all_fields_aligned = True
        has_any_field = False
        sample_failed_fields = []
        
        # 映射回原始字段名用于统计
        field_name_map = {"TASK": "task", "OBJ": "object", "ASP": "aspect", "CTX": "context"}
        
        # 统计
        for field in ["TASK", "OBJ", "ASP", "CTX"]:
            labels = result["labels"][field]
            has_field = any(l != 'O' for l in labels)
            field_name = field_name_map[field]
            
            if has_field:
                stats[f"{field_name}_present"] += 1
            else:
                stats[f"{field_name}_absent"] += 1
            
            # 对齐统计（诊断性指标）
            if field_name in alignment_info:
                info = alignment_info[field_name]
                if info["has_original_value"]:
                    has_any_field = True
                    if info["matched"]:
                        if info["match_type"] == "exact":
                            stats[f"{field_name}_exact_match"] += 1
                        elif info["match_type"] == "lemma":
                            stats[f"{field_name}_lemma_match"] += 1
                        elif info["match_type"] == "fuzzy":
                            stats[f"{field_name}_fuzzy_match"] += 1
                    else:
                        all_fields_aligned = False
                        stats[f"{field_name}_alignment_failed"] += 1
                        sample_failed_fields.append(field_name)
        
        # 保存逻辑：
        # 1. 如果所有字段都是空的（无标注），直接保存（全 O 标签）
        # 2. 如果有标注，则所有有标注的字段都必须对齐成功才保存
        if not has_any_field:
            # 无标注样本，直接保存
            converted.append({
                "sentence": sentence,
                "tokens": result["tokens"],
                "labels": result["labels"],
                "original_rpu": rpu_label
            })
        elif all_fields_aligned:
            # 有标注且全部对齐成功
            complete_success += 1
            converted.append({
                "sentence": sentence,
                "tokens": result["tokens"],
                "labels": result["labels"],
                "original_rpu": rpu_label
            })
        else:
            # 有标注但部分字段对齐失败
            partial_success += 1
            failed_samples.append({
                "sentence": sentence,
                "failed_fields": sample_failed_fields,
                "original_rpu": rpu_label,
                "tokens": result["tokens"]
            })
    
    # 保存转换结果
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(converted, f, ensure_ascii=False, indent=2)
    
    # 保存对齐失败的样本
    if failed_samples:
        failed_output_path = OUTPUT_FAILED_JSON
        failed_output_dir = os.path.dirname(failed_output_path)
        if failed_output_dir:
            os.makedirs(failed_output_dir, exist_ok=True)
        with open(failed_output_path, 'w', encoding='utf-8') as f:
            json.dump(failed_samples, f, ensure_ascii=False, indent=2)
        print(f"\n对齐失败样本已保存到: {failed_output_path}")
        print(f"对齐失败样本数: {len(failed_samples)} 条")
    
    # 打印统计
    print("\n" + "=" * 60)
    print("转换统计")
    print("=" * 60)
    print(f"总样本: {stats['total']}")
    
    # 完整对齐统计
    total_with_labels = complete_success + partial_success
    no_label_count = len(converted) - complete_success
    
    print(f"\n完整对齐统计:")
    print(f"  有标注的样本总数: {total_with_labels}")
    print(f"  ✓ 完整对齐成功: {complete_success} ({100*complete_success/total_with_labels:.1f}% 有标注样本)")
    print(f"  ✗ 部分对齐失败: {partial_success} ({100*partial_success/total_with_labels:.1f}% 有标注样本)")
    print(f"  无标注样本（全O）: {no_label_count} 条")
    print(f"\n最终保存样本数: {len(converted)} 条（包含 {complete_success} 条完整对齐 + {no_label_count} 条无标注）")
    
    print("\n字段级对齐统计:")
    for field_name in ["task", "object", "aspect", "context"]:
        exact = stats[f"{field_name}_exact_match"]
        lemma = stats[f"{field_name}_lemma_match"]
        fuzzy = stats[f"{field_name}_fuzzy_match"]
        failed = stats[f"{field_name}_alignment_failed"]
        total_original = exact + lemma + fuzzy + failed
        
        if total_original > 0:
            success = exact + lemma + fuzzy
            print(f"  {field_name.capitalize()}: ({total_original} 条原始标注)")
            print(f"    精确匹配: {exact} ({100*exact/total_original:.1f}%)")
            print(f"    Lemma匹配: {lemma} ({100*lemma/total_original:.1f}%)")
            print(f"    对齐失败: {failed} ({100*failed/total_original:.1f}%)")
            print(f"    成功率: {100*success/total_original:.1f}%")
        else:
            print(f"  {field_name.capitalize()}: 无原始标注")
    
    # 分析是否需要人工标注
    print("\n" + "=" * 60)
    print("人工标注建议")
    print("=" * 60)
    
    if complete_success < 1000:
        print(f"⚠️ 完整对齐的有标注样本只有 {complete_success} 条，建议增加人工标注！")
        print(f"   需要补充约 {1000 - complete_success} 条有标注样本达到 1000 条基准")
        print(f"   当前总样本数: {len(converted)} 条（含 {no_label_count} 条无标注样本）")
    elif complete_success < 2000:
        print(f"⚠ 完整对齐的有标注样本 {complete_success} 条，中等规模")
        print(f"   建议补充 {2000 - complete_success} 条有标注样本以提高模型效果")
        print(f"   当前总样本数: {len(converted)} 条（含 {no_label_count} 条无标注样本）")
    else:
        print(f"✓ 完整对齐的有标注样本 {complete_success} 条，数据量充足")
        print(f"   当前总样本数: {len(converted)} 条（含 {no_label_count} 条无标注样本）")
    
    # 字段覆盖率（只统计有标注的样本）
    print(f"\n字段覆盖分析（在完整对齐的有标注样本中）:")
    field_coverage = {"TASK": 0, "OBJ": 0, "ASP": 0, "CTX": 0}
    for sample in converted:
        # 检查是否有任何字段有标注
        has_any_label = any(
            any(l != 'O' for l in sample["labels"][field])
            for field in ["TASK", "OBJ", "ASP", "CTX"]
        )
        if has_any_label:
            for field in ["TASK", "OBJ", "ASP", "CTX"]:
                if any(l != 'O' for l in sample["labels"][field]):
                    field_coverage[field] += 1
    
    for field, count in field_coverage.items():
        pct = 100 * count / complete_success if complete_success > 0 else 0
        print(f"  {field}: {count}/{complete_success} ({pct:.1f}%)")
    
    print("\n" + "=" * 60)
    print(f"转换完成，保存到: {output_path}")
    print("=" * 60)


# ============================================================
# 主函数
# ============================================================
def main():
    # 检查输入文件
    if not os.path.exists(INPUT_EXCEL):
        print(f"错误: 输入文件不存在: {INPUT_EXCEL}")
        return
    
    # 从 Excel 读取数据
    input_data = load_excel_data(INPUT_EXCEL)
    
    if not input_data:
        print("错误: 没有有效数据")
        return
    
    # 转换
    convert_dataset(input_data, OUTPUT_JSON, TOKENIZER_NAME)


if __name__ == "__main__":
    main()
