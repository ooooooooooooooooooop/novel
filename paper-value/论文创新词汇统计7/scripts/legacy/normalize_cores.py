# -*- coding: utf-8 -*-
"""
Script: normalize_cores.py
功能：构建 RPU 核心词标准化映射表 (Core Mapping)
逻辑：
1. 加载 phrase_table.json (从 mine_phrases.py 生成)
2. 基础归一化：小写、去标点、词形还原 (Lemmatization)
3. 向量聚类 (Vector Clustering): 使用 Sentence-BERT + Community Detection 发现语义相似词
4. LLM 验证 (LLM Verification): 对 Top-K 高频词进行 LLM 辅助消歧
5. 输出 core_mapping.json
"""

import os
import json
import logging
import re
import sys
from typing import List, Dict, Tuple
from pathlib import Path
from tqdm import tqdm
import numpy as np
from sentence_transformers import SentenceTransformer, util
import time

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


def _ensure_parent_dir(path: str):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


# ============================================================
# 配置
# ============================================================
CONFIG = {
    "phrase_table_path": _require_path("phrase_table_path"),
    "output_path": _require_path("core_mapping_path"),
    
    # 聚类参数
    "model_name": "all-MiniLM-L6-v2", # 轻量级模型
    "similarity_threshold": 0.85,     # 相似度阈值
    "min_community_size": 2,          # 最小聚类大小
    "max_clustering_vocab": 50000,    # 🚀 防止 OOM：只对 Top-N 高频词聚类
    
    # LLM 参数
    "enable_llm": True,
    "llm_top_k": 1000,                # 只验证 Top 1000 高频词
    "llm_batch_size": 50,             # 每批发送给 LLM 的词数
    "llm_provider": "openai",         # openai
    "api_key": os.getenv("OPENAI_API_KEY", ""),
    "base_url": "https://x666.me/v1",         # DeepSeek Base URL
    "llm_model": "gemini-3-pro-high"                       # 模型名称
}

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class VectorCluster:
    def __init__(self, model_name=CONFIG['model_name']):
        try:
            from sentence_transformers import SentenceTransformer, util
            self.model = SentenceTransformer(model_name)
            self.util = util
            self.available = True
        except ImportError:
            logger.warning("sentence-transformers not installed. Vector clustering disabled.")
            self.available = False

    def cluster(self, phrases: List[str]) -> Dict[str, str]:
        """
        对短语列表进行聚类，返回 {phrase: canonical_form} 映射
        Canonical Form 选取聚类中长度最短或最高频的词
        """
        if not self.available or not phrases:
            return {}
            
        logger.info(f"Encoding {len(phrases)} phrases...")
        embeddings = self.model.encode(phrases, batch_size=64, show_progress_bar=True, convert_to_tensor=True)
        
        logger.info("Running community detection...")
        # Fast Community Detection
        clusters = self.util.community_detection(
            embeddings, 
            threshold=CONFIG['similarity_threshold'], 
            min_community_size=CONFIG['min_community_size']
        )
        
        mapping = {}
        for cluster in clusters:
            # cluster 是索引列表 [idx1, idx2, ...]
            members = [phrases[i] for i in cluster]
            
            # 选取 Canonical：这里简单选取长度最短的，或者按外部频次排序（需要额外传参）
            # 假设 phrases 已经按频次降序排列，那么 members[0] 就是最高频的
            # 但为了稳妥，我们选取长度最短的作为 Base，或者最常用的缩写
            # 策略：选取最短的词作为 Canonical，如果长度相同选第一个
            canonical = sorted(members, key=len)[0]
            
            for member in members:
                if member != canonical:
                    mapping[member] = canonical
                    
        logger.info(f"Found {len(clusters)} clusters, created {len(mapping)} mappings.")
        return mapping

class LLMNormalizer:
    def __init__(self, provider="gemini", api_key="", base_url=None, model_name="gemini-pro"):
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        
    def _call_gemini(self, prompt):
        # 伪代码：实际需要集成 google-generativeai 库
        # import google.generativeai as genai
        # genai.configure(api_key=self.api_key)
        # model = genai.GenerativeModel('gemini-pro')
        # response = model.generate_content(prompt)
        # return response.text
        
        # 使用 OpenAI 兼容接口调用
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )
            return response.choices[0].message.content
        except ImportError:
            logger.error("openai library not installed.")
            return "{}"
        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            return "{}"

    def normalize_batch(self, phrases: List[str]) -> Dict[str, str]:
        """
        构建 Prompt，请求 LLM 标准化一批词
        """
        prompt = f"""
You are a terminologist in Computer Science. 
Analyze the following list of technical terms. 
Identify synonyms, abbreviations, and variants.
Group them and map them to their Canonical Form (Standard Term).

Rules:
1. Map abbreviation to full name if common (e.g., "CNN" -> "Convolutional Neural Network").
2. Fix singular/plural/typos (e.g., "Transformers" -> "Transformer").
3. Do NOT merge distinct concepts (e.g., "BERT" and "GPT" are different).
4. Return a JSON object: {{"variant": "canonical_form"}}. Only include terms that need normalization.

List:
{json.dumps(phrases)}

JSON Output:
"""
        try:
            response_text = self._call_gemini(prompt)
            # 简单的清洗，防止 LLM 返回 markdown code block
            response_text = response_text.replace("```json", "").replace("```", "").strip()
            return json.loads(response_text)
        except Exception as e:
            logger.error(f"LLM call failed or invalid JSON: {e}")
            return {}

    def process(self, top_phrases: List[str]) -> Dict[str, str]:
        logger.info(f"LLM verifying top {len(top_phrases)} phrases...")
        
        # 尝试加载已有的 mapping，支持断点续传
        all_mappings = {}
        if os.path.exists(CONFIG['output_path']):
            try:
                with open(CONFIG['output_path'], 'r', encoding='utf-8') as f:
                    all_mappings = json.load(f)
                logger.info(f"Resuming from existing mapping with {len(all_mappings)} entries.")
            except:
                pass
        
        # 找出尚未处理的词
        remaining_phrases = [p for p in top_phrases if p not in all_mappings]
        logger.info(f"Remaining phrases to process: {len(remaining_phrases)}")
        
        # 分批处理
        batch_size = CONFIG['llm_batch_size']
        for i in range(0, len(remaining_phrases), batch_size):
            batch = remaining_phrases[i:i+batch_size]
            try:
                batch_mapping = self.normalize_batch(batch)
                all_mappings.update(batch_mapping)
                
                # 实时保存，防止中断丢失
                with open(CONFIG['output_path'], 'w', encoding='utf-8') as f:
                    json.dump(all_mappings, f, indent=2, ensure_ascii=False)
                    
                time.sleep(1) # Rate limit
            except Exception as e:
                logger.error(f"Batch processing failed at index {i}: {e}")
                # 继续处理下一个 batch，不中断整个流程
                continue
            
        return all_mappings

class QualityController:
    def __init__(self):
        pass

    def apply_quality_control(self, phrase_data: List[Dict]) -> List[Dict]:
        """
        质量控制与过滤 (Quality Control) - 补偿 mine_phrases 弃熵后的精度损失
        """
        logger.info("执行质量控制与过滤...")
        valid_phrases = []
        
        # 1. 构建子串竞争表 (Substring Competition)
        # 统计所有 phrase 的频次，用于判断 "A" 是否只是 "A B" 的一部分
        phrase_freq = {p['phrase']: p['frequency'] for p in phrase_data}
        
        for p in tqdm(phrase_data, desc="QC Filtering"):
            phrase = p['phrase']
            tokens = phrase.split()
            
            # Rule 1: 停用词边界检查 (Stopword Boundary Check)
            # 虽然 N-gram 生成时有检查，但合并后的短语可能引入新的边界问题
            # 例如 "the method of" -> 结尾是 of
            if tokens[-1].lower() in ["of", "and", "or", "the", "a", "an", "in", "on", "at", "to", "for", "with", "by"]:
                continue
            if tokens[0].lower() in ["of", "and", "or", "in", "on", "at", "to", "for", "with", "by"]:
                continue
                
            # Rule 2: 子串竞争 (Substring Competition / Superstring Frequency)
            # 如果 "convolutional neural" (A) 的频次是 1000
            # 而 "convolutional neural network" (B) 的频次是 950
            # 说明 A 几乎总是伴随 B 出现，A 不是独立短语。
            # 我们检查是否存在一个 Superstring B，使得 Freq(B) / Freq(A) > 0.8
            # 注意：这需要 O(N^2) 或优化算法。这里用简单的启发式：只检查 Top-N 里的 superstring
            # 或者：在 apply_abstract_layer 里用 MaxMatch 解决，这里只做轻量级过滤
            
            # Rule 3: 纯数字或单字符过滤
            if phrase.isdigit() or len(phrase) < 2:
                continue
                
            # Rule 4: 垃圾动词短语过滤 (Generic Verb Phrases)
            # 针对 "used the method", "showed that" 等
            if tokens[0].lower() in ["used", "using", "use", "showed", "show", "showing", "proposed", "propose"]:
                # 如果是 "used method" -> 过滤
                # 如果是 "used transformer" -> 保留 (需结合 Object 列表，这里简单过滤通用词)
                if len(tokens) == 2 and tokens[1].lower() in ["method", "model", "approach", "algorithm", "system", "technique"]:
                    continue
            
            valid_phrases.append(p)
            
        logger.info(f"质量控制完成: {len(phrase_data)} -> {len(valid_phrases)}")
        return valid_phrases

def main():
    if not os.path.exists(CONFIG['phrase_table_path']):
        logger.error("Phrase table not found.")
        return
        
    logger.info("Loading phrases...")
    with open(CONFIG['phrase_table_path'], 'r', encoding='utf-8') as f:
        phrase_data = json.load(f)
    
    # === 新增：质量控制流程 ===
    qc = QualityController() # 需要定义这个类或把方法放进去
    phrase_data = qc.apply_quality_control(phrase_data)
    
    # phrase_data is list of dicts: [{'phrase': '...', 'score': ...}, ...]
    # Sort by score/freq just in case
    # Assume they are already valid candidates
    all_phrases = [p['phrase'] for p in phrase_data]
    
    final_mapping = {}
    
    # 1. Vector Clustering (Coarse-grained, high recall)
    # 重新排序：按频次降序，优先聚类高频词
    logger.info("Sorting phrases by frequency for clustering...")
    # phrase_data item: {'phrase': str, 'frequency': int, ...}
    phrase_data.sort(key=lambda x: x['frequency'], reverse=True)
    
    # 截取 Top-N 防止 OOM
    top_n = min(len(phrase_data), CONFIG['max_clustering_vocab'])
    clustering_candidates = [p['phrase'] for p in phrase_data[:top_n]]
    logger.info(f"Selected Top {top_n} phrases for vector clustering.")
    
    vc = VectorCluster()
    vector_mapping = vc.cluster(clustering_candidates)
    final_mapping.update(vector_mapping)
    
    # 🚀 立即保存聚类结果，防止 LLM 阶段中断导致丢失
    logger.info(f"Saving intermediate vector mappings ({len(vector_mapping)} entries)...")
    _ensure_parent_dir(CONFIG['output_path'])
    with open(CONFIG['output_path'], 'w', encoding='utf-8') as f:
        json.dump(final_mapping, f, indent=2, ensure_ascii=False)
    
    # 2. LLM Verification (Fine-grained, high precision, Top-K only)
    if CONFIG['enable_llm']:
        if not CONFIG['api_key']:
            logger.warning("OPENAI_API_KEY 未设置，跳过 LLM Verification。")
        else:
            top_k_phrases = all_phrases[:CONFIG['llm_top_k']]
            llm = LLMNormalizer(
                provider=CONFIG['llm_provider'], 
                api_key=CONFIG['api_key'],
                base_url=CONFIG['base_url'],
                model_name=CONFIG['llm_model']
            )
            llm_mapping = llm.process(top_k_phrases)
            
            # Merge: LLM overrides Vector
            final_mapping.update(llm_mapping)
        
    logger.info(f"Total mappings generated: {len(final_mapping)}")
    
    # Save
    _ensure_parent_dir(CONFIG['output_path'])
    with open(CONFIG['output_path'], 'w', encoding='utf-8') as f:
        json.dump(final_mapping, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved to {CONFIG['output_path']}")

if __name__ == "__main__":
    main()
