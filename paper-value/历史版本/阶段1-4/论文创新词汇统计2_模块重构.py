import os
import sys
import time
import gc
import json
import pickle
import re
import warnings
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional, Iterator
from collections import defaultdict, Counter
from dataclasses import dataclass, asdict
from tempfile import gettempdir
import pandas as pd
import numpy as np
import multiprocessing
from multiprocessing import Pool, cpu_count
import psutil
import spacy
import cupy as cp
from tqdm import tqdm
import jieba
# 忽略警告
warnings.filterwarnings('ignore')

# 环境优化
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['NUMEXPR_NUM_THREADS'] = '1'

# RTX 4070Ti GPU优化
os.environ['CUDA_LAUNCH_BLOCKING'] = '0'
os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'max_split_size_mb:512'

# =============================================================================
# 模块级预编译正则表达式
# =============================================================================

RE_WORD = re.compile(r'\b[a-zA-Z]+(?:-[a-zA-Z]+)*\b')
RE_HTML = re.compile(r'<[^>]+>')
RE_CONTROL = re.compile(r'[\x00-\x1f\x7f-\x9f]')
RE_PUNCT1 = re.compile(r'[&()（）【】\[\]{}]')
RE_PUNCT2 = re.compile(r'[,:;．。！？]')
RE_PUNCT3 = re.compile(r'["\'""'']')
RE_PUNCT4 = re.compile(r'[`，、；：]')
RE_HYPHEN = re.compile(r'\s+-\s+')
RE_CONCAT = re.compile(r'([a-z]{4,})(the|this|our|and|or|of|in|to|for|with|from|by)(\s|$)')
RE_CLEAN_EN = re.compile(r'[^a-zA-Z\-]')
RE_CLEAN_ZH = re.compile(r'[^\u4e00-\u9fff]')

# =============================================================================
# 配置管理模块
# =============================================================================

@dataclass
class SystemConfig:
    """系统配置类"""
    # 文件路径
    csv_file_path: str
    output_file: str = 'analysis_results.csv'
    temp_dir: str = './temp'
    
    # 数据列配置
    time_columns: List[str] = None
    info_columns: List[str] = None
    text_column: Optional[str] = None
    unique_id_column: str = 'paper_id'
    
    # 分析参数
    language: str = 'en'
    min_word_length: int = 2
    min_occurrence: int = 1
    analyze_info_columns: bool = True
    
    # 性能配置
    chunk_size: int = 60000
    num_processes: int = 6
    batch_size: int = 1500
    
    # 停用词文件
    stopword_files: List[str] = None
    phrase_files: List[str] = None
    
    # 高级分析
    use_tfidf: bool = True  # 是否使用TF-IDF计算词汇重要性
    use_pos_filter: bool = True  # 是否使用词性过滤（需要spaCy）
    use_burst_analysis: bool = True  # 是否进行爆发度分析
    extract_ngrams: bool = True  # 是否提取N-gram（多词组合）
    use_phrase_extraction: bool = False  # 是否提取短语（名词短语+固定短语）
    ngram_range: Tuple[int, int] = (2, 3)
    
    # 爆发度分析参数
    innovation_burst_threshold: float = 0.15
    min_years_span: int = 2
    turning_point_growth_factor: float = 3.0
    turning_point_min_freq: int = 100
    recent_window_years: int = 5
    exclude_last_n_years: int = 1
    doc_freq_threshold: float = 0.9
    
    def __post_init__(self):
        """初始化后处理"""
        if self.time_columns is None:
            self.time_columns = ['year', 'volume', 'issue']
        if self.info_columns is None:
            self.info_columns = ['title', 'abstract', 'keywords']
        if self.stopword_files is None:
            self.stopword_files = ['config/stopwords_en.txt', 'config/stopwords_cn.txt']
        if self.phrase_files is None:
            self.phrase_files = ['phrases.txt']

class ConfigurationManager:
    """配置管理器 - 阶段0"""
    
    def __init__(self, config: SystemConfig):
        self.config = config
        self.stop_words: Set[str] = set()
        self.phrase_patterns: List[str] = []
        self.nlp_model = None
        self.phrase_matcher = None
        
        # 创建必要目录
        Path(self.config.temp_dir).mkdir(exist_ok=True)
    
    def load_resources(self) -> bool:
        """加载停用词、短语词典和NLP模型"""
        print("📂 === 阶段0: 任务初始化 ===")
        
        # 1. 加载停用词
        self._load_stopwords()
        
        # 2. 加载短语词典
        self._load_phrases()
        
        # 3. 加载NLP模型
        if self.config.use_pos_filter:
            self._load_nlp_model()
        
        print("✅ 资源初始化完成")
        print(f"   停用词: {len(self.stop_words):,} 个")
        print(f"   短语模式: {len(self.phrase_patterns):,} 个")
        print(f"   NLP模型: {'已加载' if self.nlp_model else '未启用'}")
        
        return True
    
    def _load_stopwords(self):
        """加载停用词"""
        for stopword_file in self.config.stopword_files:
            if os.path.exists(stopword_file):
                with open(stopword_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        word = line.strip()
                        if word and not word.startswith('#'):
                            if re.match(r'^[A-Za-z\-]+$', word):
                                self.stop_words.add(word.lower())
                            else:
                                self.stop_words.add(word)
    
    def _load_phrases(self):
        """加载短语词典"""
        if not self.config.use_phrase_extraction:
            return
        for phrase_file in self.config.phrase_files:
            if os.path.exists(phrase_file):
                with open(phrase_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        phrase = line.strip()
                        if phrase and not phrase.startswith('#'):
                            self.phrase_patterns.append(phrase)
    
    def _load_nlp_model(self):
        try:
            mempool = cp.get_default_memory_pool()
            mempool.set_limit(size=11.5 * 1024**3)
            print("✅ GPU内存池已配置: 11.5GB (RTX 4070Ti优化)")
        except Exception as e:
            print(f"⚠️ GPU内存池配置失败: {e}")
        
        # 强制GPU加速
        try:
            spacy.require_gpu()
            gpu_enabled = True
        except:
            gpu_enabled = spacy.prefer_gpu()
        
        self.nlp_model = spacy.load('en_core_web_sm')
        
        # 构建PhraseMatcher
        if self.phrase_patterns and self.config.use_phrase_extraction:
            from spacy.matcher import PhraseMatcher
            self.phrase_matcher = PhraseMatcher(self.nlp_model.vocab, attr='LOWER')
            patterns = [self.nlp_model(phrase) for phrase in self.phrase_patterns]
            self.phrase_matcher.add("PHRASES", patterns)
        
        print(f"✅ spaCy模型已加载 ({'GPU' if gpu_enabled else 'CPU'})")

# =============================================================================
# 数据读取模块 - 阶段1（主进程）
# =============================================================================

class DataReader:
    """数据读取器 - 阶段1（主进程）"""
    
    def __init__(self, config: SystemConfig):
        self.config = config
    
    def read_chunks(self, total_rows: int) -> Iterator[Tuple[int, pd.DataFrame]]:
        """分块读取CSV数据"""
        print("📊 === 阶段1: 分块数据读取（主进程） ===")
        print(f"   文件: {self.config.csv_file_path}")
        print(f"   总行数: {total_rows:,}")
        print(f"   块大小: {self.config.chunk_size:,}")
        
        # 仅读取需要的列
        required_cols = list(set(
            self.config.time_columns + 
            self.config.info_columns + 
            [self.config.unique_id_column]
        ))
        
        # 指定稳定 dtype
        dtype_spec = {self.config.unique_id_column: str}
        
        chunk_id = 0
        try:
            for chunk_data in pd.read_csv(
                self.config.csv_file_path, 
                chunksize=self.config.chunk_size,
                usecols=required_cols,
                dtype=dtype_spec,
                low_memory=False
            ):
                if chunk_id == 0:
                    self._column_names = chunk_data.columns.tolist()
                yield chunk_id, chunk_data
                chunk_id += 1
        except Exception as e:
            print(f"⚠️ 读取chunk {chunk_id} 失败: {e}")

# =============================================================================
# 文本预处理模块 - 阶段2（多进程）
# =============================================================================

class TextPreprocessor:
    """文本预处理器 - 阶段2（多进程）"""
    
    def __init__(self, config: SystemConfig, stop_words: Set[str]):
        self.config = config
        self.stop_words = stop_words
    
    def clean_text_batch(self, texts: List[str]) -> List[str]:
        """批量清理文本"""
        cleaned_texts = []
        
        for text in texts:
            if pd.isna(text) or not isinstance(text, str):
                cleaned_texts.append("")
                continue
            
            # HTML和控制字符清理
            text = RE_HTML.sub(' ', text)
            text = RE_CONTROL.sub(' ', text)
            
            # 标准化
            text = text.lower().strip()
            
            # 修复词汇粘连
            text = RE_CONCAT.sub(r'\1 \2\3', text)
            
            # 标点符号处理
            if self.config.analyze_info_columns:
                text = RE_PUNCT1.sub(' ', text)
                text = RE_PUNCT2.sub(' ', text)
                text = RE_PUNCT3.sub(' ', text)
                text = RE_PUNCT4.sub(' ', text)
                text = RE_HYPHEN.sub(' ', text)
            
            # 多空格合并
            text = ' '.join(text.split())
            
            cleaned_texts.append(text)
        
        return cleaned_texts

# 多进程文本清洗工作函数
def clean_texts_worker(args) -> Tuple[int, List[str]]:
    """多进程文本清洗工作函数"""
    chunk_id, texts, config_dict, stop_words = args
    
    # 重建配置对象和预处理器
    config = SystemConfig(**config_dict)
    preprocessor = TextPreprocessor(config, set(stop_words))
    
    try:
        cleaned_texts = preprocessor.clean_text_batch(texts)
        return chunk_id, cleaned_texts
    except Exception as e:
        print(f"⚠️ Chunk {chunk_id} 文本清洗失败: {e}")
        return chunk_id, texts  # 返回原始文本

# =============================================================================
# NLP处理模块 - 阶段3（单进程或GPU任务）
# =============================================================================

class NLPProcessor:
    """NLP处理器 - 阶段3（单进程或独立GPU任务）"""
    
    def __init__(self, config: SystemConfig, nlp_model, phrase_matcher, stop_words: Set[str]):
        self.config = config
        self.nlp_model = nlp_model
        self.phrase_matcher = phrase_matcher
        self.stop_words = stop_words
        self.precomputed_chunk_stats = {}
    
    def _clear_gpu_memory(self):
        """清理GPU内存"""
        cp.get_default_memory_pool().free_all_blocks()
        gc.collect()
    
    def extract_high_quality_phrases_batch(self, texts_batches: List[Tuple[int, List[str]]]) -> List[Tuple[int, List[List[str]]]]:
        """批量高质量短语识别（单进程处理）"""
        print("🧠 === 阶段3: 高质量短语识别（单进程/GPU任务） ===")
        
        SUB_BATCH_SIZE = 5000
        results = []
        
        progress_bar = texts_batches
        progress_bar = tqdm(texts_batches, desc="NLP处理")
        
        for chunk_id, texts in progress_bar:
            if not self.nlp_model:
                tokens_list = self._simple_tokenize_batch(texts)
            else:
                tokens_list = []
                num_texts = len(texts)
                num_sub_batches = (num_texts + SUB_BATCH_SIZE - 1) // SUB_BATCH_SIZE
                
                for sub_idx in range(num_sub_batches):
                    start_idx = sub_idx * SUB_BATCH_SIZE
                    end_idx = min(start_idx + SUB_BATCH_SIZE, num_texts)
                    sub_texts = texts[start_idx:end_idx]
                    
                    sub_tokens = self._extract_high_quality_phrases(sub_texts)
                    tokens_list.extend(sub_tokens)
                    
                    self._clear_gpu_memory()
            
            # 预计算块级词频与文档频次
            try:
                token_counter = Counter()
                doc_counter = Counter()
                for tokens in tokens_list:
                    if not tokens:
                        continue
                    token_counter.update(tokens)
                    doc_counter.update(set(tokens))
                self.precomputed_chunk_stats[chunk_id] = (token_counter, doc_counter)
            except Exception:
                self.precomputed_chunk_stats[chunk_id] = None

            results.append((chunk_id, tokens_list))
        
        print(f"✅ NLP处理完成，处理了 {len(results)} 个数据块")
        return results
    
    def _extract_high_quality_phrases(self, texts: List[str]) -> List[List[str]]:
        """高质量短语识别"""
        all_tokens = []
        
        # 使用spaCy的pipe方法批量处理，n_process=1确保GPU利用
        for doc in self.nlp_model.pipe(texts, batch_size=self.config.batch_size, n_process=1):
            tokens = self._extract_tokens_from_doc(doc)
            all_tokens.append(tokens)
        
        self._clear_gpu_memory()
        return all_tokens
    
    def _extract_tokens_from_doc(self, doc) -> List[str]:
        """从spaCy文档提取词汇"""
        tokens = []
        
        # 1. 名词短语识别
        if self.config.use_phrase_extraction:
            for chunk in doc.noun_chunks:
                phrase = '_'.join([token.lemma_.lower() for token in chunk 
                                 if not token.is_stop and token.is_alpha])
                if len(phrase) > 2 and phrase not in self.stop_words:
                    tokens.append(phrase)
        
        # 2. 命名实体识别
        for ent in doc.ents:
            entity = ent.text.lower().replace(' ', '_')
            if len(entity) >= self.config.min_word_length and entity not in self.stop_words:
                tokens.append(entity)
        
        # 3. 固定短语匹配
        if self.config.use_phrase_extraction and self.phrase_matcher:
            matches = self.phrase_matcher(doc)
            for match_id, start, end in matches:
                phrase = doc[start:end].text.lower().replace(' ', '_')
                if phrase not in self.stop_words:
                    tokens.append(phrase)
        
        # 4. 单词Token（词性过滤）
        valid_pos = {'NOUN', 'PROPN', 'ADJ', 'NUM', 'X'}
        for token in doc:
            if (token.pos_ in valid_pos and 
                len(token.text) >= self.config.min_word_length and
                token.text.lower() not in self.stop_words and
                token.is_alpha):
                tokens.append(token.lemma_.lower())
        
        # 5. N-gram提取
        if self.config.extract_ngrams and len(tokens) >= self.config.ngram_range[0]:
            ngrams = self._extract_ngrams(tokens)
            tokens.extend(ngrams)
        
        return tokens
    
    def _extract_ngrams(self, tokens: List[str]) -> List[str]:
        """提取N-gram"""
        ngrams = []
        for n in range(self.config.ngram_range[0], self.config.ngram_range[1] + 1):
            for i in range(len(tokens) - n + 1):
                ngram = '_'.join(tokens[i:i+n])
                ngrams.append(ngram)
        return ngrams
    
    def _simple_tokenize_batch(self, texts: List[str]) -> List[List[str]]:
        """简单分词（无NLP模型时使用）"""
        all_tokens = []
        
        for text in texts:
            if self.config.language == 'en':
                words = RE_WORD.findall(text)
            elif self.config.language == 'zh':
                words = list(jieba.cut(text))
            else:
                words = text.split()
            
            # 过滤和清理
            tokens = []
            for word in words:
                clean_word = self._clean_word(word)
                if (clean_word and 
                    len(clean_word) >= self.config.min_word_length and
                    clean_word not in self.stop_words):
                    tokens.append(clean_word)
            
            all_tokens.append(tokens)
        
        return all_tokens
    
    def _clean_word(self, word: str) -> str:
        """清理单词"""
        if self.config.language == 'en':
            clean_word = RE_CLEAN_EN.sub('', word).strip('-')
        elif self.config.language == 'zh':
            clean_word = RE_CLEAN_ZH.sub('', word)
        else:
            if re.match(r'^[a-zA-Z\-]+$', word):
                clean_word = RE_CLEAN_EN.sub('', word).strip('-')
            else:
                clean_word = RE_CLEAN_ZH.sub('', word)
        
        return clean_word if clean_word != '-' and not clean_word.isdigit() else ''

# =============================================================================
# 统计计算模块 - 阶段4（多进程）
# =============================================================================

@dataclass
class ChunkStatistics:
    """单个数据块的统计结果"""
    chunk_id: int
    token_frequencies: Counter
    doc_frequencies: Counter
    year_frequencies: Dict[str, Dict[int, int]]
    first_occurrences: Dict[str, Dict]
    doc_count: int


class StatisticsCalculator:
    """统计计算器 - 阶段4（多进程优化版：路径传参+低内存）"""
    
    def __init__(self, config):
        self.config = config
        # 临时目录（系统默认，如 /tmp 或 C:\Users\<user>\AppData\Local\Temp）
        self.temp_dir = os.path.join(gettempdir(), "stats_chunks")
        os.makedirs(self.temp_dir, exist_ok=True)

    def calculate_chunk_statistics(self, chunk_id: int,
                                   chunk_data: pd.DataFrame,
                                   tokens_list: List[List[str]],
                                   precomputed: Optional[Tuple[Counter, Counter]] = None) -> 'ChunkStatistics':
        """计算单个数据块的统计信息（核心逻辑不变）"""
        if precomputed:
            token_freq, doc_freq = precomputed
        else:
            token_freq = Counter()
            doc_freq = Counter()

        year_freq = defaultdict(lambda: defaultdict(int))
        first_occur = {}
        doc_count = 0
        
        for idx, (_, row) in enumerate(chunk_data.iterrows()):
            if idx >= len(tokens_list):
                continue
                
            tokens = tokens_list[idx]
            if not tokens:
                continue
            
            doc_count += 1
            
            # 词频/文档频率统计
            if not precomputed:
                token_freq.update(tokens)
                doc_freq.update(set(tokens))
        
            # 年度频率统计
            primary_year = row[self.config.time_columns[0]]
            if pd.notna(primary_year):
                try:
                    year_val = int(primary_year)
                except (ValueError, TypeError):
                    continue
                token_counts = Counter(tokens)
                for token, count in token_counts.items():
                    year_freq[token][year_val] += count
                
                # 首次出现记录
                new_tokens = [t for t in tokens if t not in first_occur]
                if new_tokens:
                    paper_info = {
                        self.config.unique_id_column: str(row[self.config.unique_id_column])
                    }
                    
                    for col in self.config.time_columns:
                        value = row[col]
                        if pd.notna(value):
                            try:
                                paper_info[col] = int(value)
                            except (ValueError, TypeError):
                                paper_info[col] = 0
                        else:
                            paper_info[col] = 0
                    
                    analysis_text = self._create_analysis_text(row)
                    
                    for token in new_tokens:
                        token_info = paper_info.copy()
                        token_info['analysis_text'] = self._extract_snippet(analysis_text, token)
                        first_occur[token] = token_info
        
        return ChunkStatistics(
            chunk_id=chunk_id,
            token_frequencies=token_freq,
            doc_frequencies=doc_freq,
            year_frequencies=dict(year_freq),
            first_occurrences=first_occur,
            doc_count=doc_count
        )

    def _create_analysis_text(self, row) -> str:
        """创建分析文本"""
        if getattr(self.config, "analyze_info_columns", False):
            texts = []
            for col in self.config.info_columns:
                value = row.get(col, '')
                if pd.notna(value):
                    texts.append(str(value))
            return ' '.join(texts)
        else:
            value = row.get(self.config.text_column, '')
            return str(value) if pd.notna(value) else ''
    
    def _extract_snippet(self, text: str, keyword: str, max_len: int = 30) -> str:
        """提取包含关键词的文本片段"""
        if not text or not keyword:
            return text[:max_len] + '...' if text and len(text) > max_len else (text or '')
        
        text_lower = text.lower()
        keyword_lower = keyword.lower()
        pos = text_lower.find(keyword_lower)
        
        if pos == -1:
            return text[:max_len] + '...' if len(text) > max_len else text
        
        delimiters = '.!?;。！？；\n\r'
        start = pos
        while start > 0 and text[start - 1] not in delimiters:
            start -= 1
        
        end = pos
        while end < len(text) and text[end] not in delimiters:
            end += 1
        
        sentence = text[start:end]
        sentence_stripped = sentence.strip()
        if len(sentence_stripped) <= max_len:
            return sentence_stripped
        
        rel_pos = pos - start
        half = max_len // 2
        window_start = max(0, rel_pos - half)
        window_end = window_start + max_len
        
        if window_end > len(sentence):
            window_end = len(sentence)
            window_start = max(0, window_end - max_len)
        
        snippet = sentence[window_start:window_end]
        snippet_stripped = snippet.strip()
        prefix = '...' if window_start > 0 else ''
        suffix = '...' if window_end < len(sentence) else ''
        
        return f"{prefix}{snippet_stripped}{suffix}"



# =========================================================
# 多进程工作函数（完全兼容原接口，自动路径优化）
# =========================================================
def calculate_statistics_worker(args) -> Optional['ChunkStatistics']:
    """
    多进程统计计算工作函数（自动检测是否传对象或路径）：
    - 若 args 中包含 DataFrame，则自动转为磁盘缓存；
    - 若包含路径，则直接读取；
    """
    try:
        chunk_id, chunk_data_or_path, tokens_or_path, precomputed, config_dict = args
        config = SystemConfig(**config_dict)
        calculator = StatisticsCalculator(config)

        # 自动区分传入类型
        # 若主进程仍传入 DataFrame / List，则自动写入临时文件
        if isinstance(chunk_data_or_path, pd.DataFrame):
            data_path = os.path.join(gettempdir(), f"chunk_{chunk_id}.feather")
            chunk_data_or_path.to_feather(data_path)
        else:
            data_path = chunk_data_or_path

        if isinstance(tokens_or_path, list):
            tokens_path = os.path.join(gettempdir(), f"tokens_{chunk_id}.pkl")
            with open(tokens_path, "wb") as f:
                pickle.dump(tokens_or_path, f, protocol=4)
        else:
            tokens_path = tokens_or_path

        # 加载数据（轻量 IO）
        chunk_data = pd.read_feather(data_path)
        with open(tokens_path, "rb") as f:
            tokens_list = pickle.load(f)

        # 执行统计
        chunk_stats = calculator.calculate_chunk_statistics(chunk_id, chunk_data, tokens_list, precomputed)

        # 清理内存和临时文件
        del chunk_data, tokens_list
        gc.collect()
        try:
            os.remove(data_path)
            os.remove(tokens_path)
        except Exception:
            pass

        return chunk_stats

    except Exception as e:
        print(f"⚠️ Chunk {args[0]} 统计计算失败: {e}")
        return None


# =============================================================================
# 结果合并模块
# =============================================================================

class ResultsMerger:
    """结果合并器 - 阶段5"""
    
    def __init__(self, config: SystemConfig):
        self.config = config
    
    def merge_statistics(self, chunk_stats: List[ChunkStatistics]) -> Tuple[Counter, Counter, Dict, Dict, int]:
        """合并所有数据块的统计结果"""
        print("📊 === 阶段5: 统计结果合并 ===")
        
        global_token_freq = Counter()
        global_doc_freq = Counter()
        global_year_freq = defaultdict(lambda: defaultdict(int))
        global_first_occur = {}
        total_docs = 0
        progress_bar = tqdm(chunk_stats, desc="合并统计")
        
        for chunk_stat in progress_bar:
            # 合并词频（Counter的update等同于批量累加）
            global_token_freq.update(chunk_stat.token_frequencies)
            
            # 合并文档频率
            global_doc_freq.update(chunk_stat.doc_frequencies)
            
            # 合并年度频率
            for token, year_dict in chunk_stat.year_frequencies.items():
                for year, count in year_dict.items():
                    global_year_freq[token][year] += count
            
            # 合并首次出现（保持最早的）
            for token, info in chunk_stat.first_occurrences.items():
                if token not in global_first_occur:
                    global_first_occur[token] = info
                else:
                    # 比较时间，保留更早的记录
                    current_year = global_first_occur[token].get(self.config.time_columns[0], float('inf'))
                    new_year = info.get(self.config.time_columns[0], float('inf'))
                    if new_year < current_year:
                        global_first_occur[token] = info
            
            total_docs += chunk_stat.doc_count
        
        print("✅ 合并完成")
        print(f"   总词汇: {len(global_first_occur):,}")
        print(f"   总文档: {total_docs:,}")
        
        return (global_token_freq, global_doc_freq, dict(global_year_freq), 
                global_first_occur, total_docs)

# =============================================================================
# 首次出现分析模块
# =============================================================================

class FirstOccurrenceAnalyzer:
    """首次出现分析器 - 阶段6"""
    
    def __init__(self, config: SystemConfig):
        self.config = config
    
    def analyze_first_occurrences(self, token_freq: Counter, doc_freq: Counter,
                                year_freq: Dict, first_occur: Dict, total_docs: int) -> Dict[str, int]:
        """分析词汇首次出现时间"""
        print("📊 === 阶段6: 首次出现时间统计 ===")
        
        first_occurrence_years = {}
        
        # 按时间排序处理
        sorted_tokens = sorted(first_occur.items(), 
                             key=lambda x: x[1].get(self.config.time_columns[0], 0))
        
        progress_bar = tqdm(sorted_tokens, desc="首次出现分析")
        
        for token, info in progress_bar:
            first_year = info.get(self.config.time_columns[0], 0)
            first_occurrence_years[token] = first_year
        
        print("✅ 首次出现分析完成")
        return first_occurrence_years

# =============================================================================
# 高级分析模块
# =============================================================================

class AdvancedAnalyzer:
    """高级分析器 - 阶段7"""
    
    def __init__(self, config: SystemConfig):
        self.config = config
    
    def calculate_advanced_metrics(self, token_freq: Counter, doc_freq: Counter,
                                 year_freq: Dict, first_occur: Dict, 
                                 total_docs: int) -> Dict[str, Dict]:
        """计算TF-IDF和爆发度等高级指标"""
        print("📊 === 阶段7: 二级统计分析 ===")
        
        metrics = {}
        
        # TF-IDF计算
        if self.config.use_tfidf:
            tfidf_scores = self._calculate_tfidf(token_freq, doc_freq, total_docs)
        else:
            tfidf_scores = {}
        
        # 爆发度分析
        if self.config.use_burst_analysis:
            burst_scores = self._calculate_burst_scores(year_freq)
        else:
            burst_scores = {}
        
        # 趋势分析
        trend_scores = self._calculate_trend_scores(year_freq)
        
        # 合并所有指标
        for token in first_occur.keys():
            metrics[token] = {
                'tfidf': tfidf_scores.get(token, 0),
                'burst': burst_scores.get(token, 0),
                'trend': trend_scores.get(token, 0),
                'frequency': token_freq[token],
                'doc_frequency': doc_freq[token]
            }
        
        print("✅ 高级指标计算完成")
        return metrics
    
    def _calculate_tfidf(self, token_freq: Counter, doc_freq: Counter, total_docs: int) -> Dict[str, float]:
        """计算TF-IDF分数"""
        tfidf_scores = {}
        total_tokens = sum(token_freq.values())

        if len(token_freq) > 1000:
            tfidf_scores = self._calculate_tfidf_gpu(token_freq, doc_freq, total_docs, total_tokens)
        else:
            if not token_freq:
                return {}
            tokens = list(token_freq.keys())
            tf_array = np.fromiter((token_freq[t] for t in tokens), dtype=np.float64)
            tf_array /= total_tokens if total_tokens > 0 else 1.0
            df_array = np.fromiter((doc_freq[t] for t in tokens), dtype=np.float64)
            # 避免除零与 log(0)
            df_array[df_array == 0] = 1.0
            idf_array = np.log(total_docs / df_array)
            tfidf_array = tf_array * idf_array
            tfidf_scores = dict(zip(tokens, tfidf_array.tolist()))

        return tfidf_scores
    
    def _calculate_tfidf_gpu(self, token_freq: Counter, doc_freq: Counter, 
                           total_docs: int, total_tokens: int) -> Dict[str, float]:
        """GPU加速的TF-IDF计算"""
        try:
            import cupy as cp
            
            tokens = list(token_freq.keys())
            tf_array = np.array([token_freq[t] / total_tokens for t in tokens], dtype=np.float64)
            df_array = np.array([doc_freq[t] for t in tokens], dtype=np.float64)
            
            # 转换到GPU
            tf_gpu = cp.array(tf_array)
            df_gpu = cp.array(df_array)
            
            # 计算IDF
            idf_gpu = cp.log(total_docs / df_gpu)
            
            # 计算TF-IDF
            tfidf_gpu = tf_gpu * idf_gpu
            
            # 转回CPU
            tfidf_array = cp.asnumpy(tfidf_gpu)
            
            # 构建结果字典
            tfidf_scores = dict(zip(tokens, tfidf_array))
            
            # 释放GPU内存
            del tf_gpu, df_gpu, idf_gpu, tfidf_gpu
            cp.get_default_memory_pool().free_all_blocks()
            
            return tfidf_scores
            
        except Exception as e:
            print(f"⚠️ GPU TF-IDF计算失败，回退到CPU: {e}")
            return {}
    
    def _calculate_burst_scores(self, year_freq: Dict) -> Dict[str, float]:
        """计算创新爆发度分数"""
        burst_scores = {}
        
        for token, year_counts in year_freq.items():
            if len(year_counts) < self.config.min_years_span:
                burst_scores[token] = 0
                continue
            
            years = sorted(year_counts.keys())
            counts = [year_counts[y] for y in years]
            
            if not counts:
                burst_scores[token] = 0
                continue
            
            # 计算各种指标
            max_growth_rate = self._calculate_max_growth_rate(counts)
            cv = self._calculate_coefficient_of_variation(counts)
            recent_early_ratio = self._calculate_recent_early_ratio(counts)
            
            # 归一化并加权
            burst_score = (0.4 * max_growth_rate + 0.3 * cv + 0.3 * recent_early_ratio)
            burst_scores[token] = burst_score
        
        return burst_scores
    
    def _calculate_max_growth_rate(self, counts: List[int]) -> float:
        """计算最大增长率"""
        if len(counts) < 2:
            return 0
        
        max_growth = 0
        for i in range(1, len(counts)):
            growth = (counts[i] + 1) / (counts[i-1] + 1) - 1
            max_growth = max(max_growth, growth)
        
        return max_growth
    
    def _calculate_coefficient_of_variation(self, counts: List[int]) -> float:
        """计算变异系数"""
        if not counts:
            return 0
        
        mean_val = sum(counts) / len(counts)
        if mean_val == 0:
            return 0
        
        variance = sum((c - mean_val) ** 2 for c in counts) / len(counts)
        std_val = variance ** 0.5
        
        return std_val / mean_val
    
    def _calculate_recent_early_ratio(self, counts: List[int]) -> float:
        """计算近期/早期比值"""
        if len(counts) < self.config.recent_window_years:
            return 1.0
        
        recent_counts = counts[-self.config.recent_window_years:]
        early_counts = counts[:-self.config.recent_window_years]
        
        if not early_counts:
            return 1.0
        
        recent_mean = sum(recent_counts) / len(recent_counts)
        early_mean = sum(early_counts) / len(early_counts)
        
        return (recent_mean + 1) / (early_mean + 1)
    
    def _calculate_trend_scores(self, year_freq: Dict) -> Dict[str, float]:
        """计算趋势分数（线性拟合）"""
        trend_scores = {}
        
        for token, year_counts in year_freq.items():
            if len(year_counts) < 3:
                trend_scores[token] = 0
                continue
            
            years = sorted(year_counts.keys())
            counts = [year_counts[y] for y in years]
            
            # 简单线性回归
            n = len(years)
            sum_x = sum(range(n))
            sum_y = sum(counts)
            sum_xy = sum(i * counts[i] for i in range(n))
            sum_x2 = sum(i * i for i in range(n))
            
            if n * sum_x2 - sum_x * sum_x == 0:
                trend_scores[token] = 0
            else:
                slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)
                trend_scores[token] = slope
        
        return trend_scores

# =============================================================================
# 导出管理模块
# =============================================================================

class ExportManager:
    """导出管理器 - 阶段8"""
    
    def __init__(self, config: SystemConfig):
        self.config = config
    
    def export_results(self, first_occur: Dict, metrics: Dict[str, Dict], 
                      year_freq: Dict) -> bool:
        """导出结果和可视化"""
        print("📊 === 阶段8: 结果导出与可视化 ===")
        
        # 1. 构建结果DataFrame
        results_df = self._build_results_dataframe(first_occur, metrics, year_freq)
        
        # 2. 导出文件
        success = self._export_to_file(results_df)
        
        if success:
            # 3. 生成可视化（可选）
            self._generate_visualizations(results_df)
            
            # 4. 保存执行日志
            self._save_execution_log(metrics)
            
            print(f"✅ 导出完成: {self.config.output_file}")
        
        return success
    
    def _build_results_dataframe(self, first_occur: Dict, metrics: Dict[str, Dict],
                                year_freq: Dict) -> pd.DataFrame:
        """构建结果DataFrame"""
        results = []
        
        # 获取所有年份用于列名
        all_years = set()
        for year_dict in year_freq.values():
            all_years.update(year_dict.keys())
        all_years = sorted(all_years)
        
        for token, info in first_occur.items():
            row = {
                '词汇': token,
                '总频率': metrics[token]['frequency'],
                '文档频率': metrics[token]['doc_frequency'],
                'TF-IDF分数': round(metrics[token]['tfidf'], 4),
                '创新爆发度': round(metrics[token]['burst'], 4),
                '趋势分数': round(metrics[token]['trend'], 4),
                f'首次出现{self.config.unique_id_column}': info.get(self.config.unique_id_column, '')
            }
            
            # 添加时间列
            for col in self.config.time_columns:
                row[f'首次出现{col}'] = info.get(col, 0)
            
            # 添加分析文本
            row['首次出现来源'] = info.get('analysis_text', '')
            
            # 添加年度统计
            token_year_counts = year_freq.get(token, {})
            for year in all_years:
                row[str(year)] = token_year_counts.get(year, 0)
            
            results.append(row)
        
        df = pd.DataFrame(results)
        
        # 排序（使用稳定排序）
        if self.config.use_burst_analysis:
            df = df.sort_values(['创新爆发度', '总频率', '词汇'], 
                              ascending=[False, False, True], 
                              kind='stable')
        elif self.config.use_tfidf:
            df = df.sort_values(['TF-IDF分数', '总频率', '词汇'], 
                              ascending=[False, False, True],
                              kind='stable')
        else:
            df = df.sort_values(['总频率', '词汇'], 
                              ascending=[False, True],
                              kind='stable')
        
        return df
    
    def _export_to_file(self, results_df: pd.DataFrame) -> bool:
        """导出到文件"""
        try:
            if self.config.output_file.endswith('.parquet'):
                results_df.to_parquet(self.config.output_file, index=False, compression='snappy')
            else:
                # 默认导出为CSV
                if not self.config.output_file.endswith('.csv'):
                    output_file = self.config.output_file.rsplit('.', 1)[0] + '.csv'
                else:
                    output_file = self.config.output_file
                results_df.to_csv(output_file, index=False, encoding='utf-8-sig')
                
            print(f"   文件格式: {'Parquet' if self.config.output_file.endswith('.parquet') else 'CSV'}")
            print(f"   记录数: {len(results_df):,}")
            return True
            
        except Exception as e:
            print(f"❌ 导出失败: {e}")
            return False
    
    def _generate_visualizations(self, results_df: pd.DataFrame):
        """生成可视化图表"""
        try:
            import matplotlib.pyplot as plt
            import matplotlib
            matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS']
            matplotlib.rcParams['axes.unicode_minus'] = False
            
            fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
            
            # 1. 词汇长度分布
            word_lengths = results_df['词汇'].str.len()
            ax1.hist(word_lengths, bins=20, alpha=0.7)
            ax1.set_title('词汇长度分布')
            ax1.set_xlabel('词汇长度')
            ax1.set_ylabel('词汇数量')
            
            # 2. 频率分布
            ax2.hist(results_df['总频率'], bins=50, alpha=0.7)
            ax2.set_title('词汇频率分布')
            ax2.set_xlabel('出现频率')
            ax2.set_ylabel('词汇数量')
            ax2.set_yscale('log')
            
            # 3. TF-IDF分布
            if self.config.use_tfidf:
                ax3.hist(results_df['TF-IDF分数'], bins=50, alpha=0.7, color='green')
                ax3.set_title('TF-IDF分数分布')
                ax3.set_xlabel('TF-IDF分数')
                ax3.set_ylabel('词汇数量')
            
            # 4. 爆发度分布
            if self.config.use_burst_analysis:
                ax4.hist(results_df['创新爆发度'], bins=50, alpha=0.7, color='red')
                ax4.set_title('创新爆发度分布')
                ax4.set_xlabel('爆发度分数')
                ax4.set_ylabel('词汇数量')
            
            plt.tight_layout()
            
            # 保存图表
            chart_file = self.config.output_file.rsplit('.', 1)[0] + '_visualization.png'
            plt.savefig(chart_file, dpi=300, bbox_inches='tight')
            print(f"   可视化图表: {chart_file}")
            
            plt.close()
            
        except ImportError:
            print("   跳过可视化（matplotlib未安装）")
        except Exception as e:
            print(f"   可视化生成失败: {e}")
    
    def _save_execution_log(self, metrics: Dict[str, Dict]):
        """保存执行日志"""
        log_info = {
            'execution_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'total_words': len(metrics),
            'config': asdict(self.config),
            'system_info': {
                'cpu_count': cpu_count(),
                'memory_gb': round(psutil.virtual_memory().total / (1024**3), 2),
                'python_version': sys.version.split()[0]
            }
        }
        
        log_file = self.config.output_file.rsplit('.', 1)[0] + '_log.json'
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(log_info, f, indent=2, ensure_ascii=False)
        
        print(f"   执行日志: {log_file}")

# =============================================================================
# 主分析器类
# =============================================================================

class TextAnalysisPipeline:
    """文本分析流水线主类"""
    
    def __init__(self, config: SystemConfig):
        self.config = config
        self.config_manager = None
        self.data_reader = None
        
        # 分析结果存储
        self.token_frequencies = Counter()
        self.doc_frequencies = Counter() 
        self.year_frequencies = {}
        self.first_occurrences = {}
        self.advanced_metrics = {}
        self.total_documents = 0
    
    def run_analysis(self, total_rows: int) -> bool:
        """运行完整分析流程"""
        print("🚀 开始文本分析流水线")
        print("=" * 70)
        
        start_time = time.time()
        
        try:
            # 阶段0: 系统初始化
            if not self._initialize_system():
                return False
            
            # 阶段1-4: 按正确的并行策略处理数据
            chunk_stats = self._process_all_stages(total_rows)
            if not chunk_stats:
                return False
            
            # 阶段5: 结果合并
            if not self._merge_results(chunk_stats):
                return False
            
            # 阶段6: 首次出现分析
            if not self._analyze_first_occurrences():
                return False
            
            # 阶段7: 高级分析
            if not self._perform_advanced_analysis():
                return False
            
            # 阶段8: 导出结果
            if not self._export_results():
                return False
            
            # 完成
            total_time = time.time() - start_time
            self._print_summary(total_time)
            
            return True
            
        except KeyboardInterrupt:
            print("\n⏹️ 分析被用户中断")
            return False
        except Exception as e:
            print(f"\n❌ 分析过程出错: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _initialize_system(self) -> bool:
        """阶段0: 系统初始化"""
        self.config_manager = ConfigurationManager(self.config)
        return self.config_manager.load_resources()
    
    def _monitor_memory(self, stage_name: str):
        """监控内存使用情况"""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / (1024 * 1024)
            print(f"   内存使用: {memory_mb:.1f}MB")
            
            # 如果内存使用过高，强制垃圾回收
            if memory_mb > 20000:  # 20GB阈值（32GB系统优化）
                print("   ⚠️ 内存使用过高，执行垃圾回收...")
                gc.collect()
                memory_info = process.memory_info()
                memory_mb = memory_info.rss / (1024 * 1024)
                print(f"   垃圾回收后内存: {memory_mb:.1f}MB")
        except Exception as e:
            print(f"   ⚠️ 内存监控失败: {e}")
    
    def _process_all_stages(self, total_rows: int) -> Optional[List[ChunkStatistics]]:
        """阶段1-4: 按正确并行策略处理所有数据"""
        print("🔄 === 阶段1-4: 数据处理流水线 ===")
        
        # 阶段1: 数据读取（主进程）
        self.data_reader = DataReader(self.config)
        
        # 收集所有数据块
        chunk_data_list = []
        raw_texts_list = []
        
        for chunk_id, chunk_data in self.data_reader.read_chunks(total_rows):
            chunk_data_list.append((chunk_id, chunk_data))
            
            # 提取原始文本
            texts = []
            for _, row in chunk_data.iterrows():
                if self.config.analyze_info_columns:
                    text_parts = []
                    for col in self.config.info_columns:
                        value = row.get(col, '')
                        if pd.notna(value):
                            text_parts.append(str(value))
                    texts.append(' '.join(text_parts))
                else:
                    value = row.get(self.config.text_column, '')
                    texts.append(str(value) if pd.notna(value) else '')
            
            raw_texts_list.append((chunk_id, texts))
        
        print(f"✅ 阶段1完成：读取了 {len(chunk_data_list)} 个数据块")
        self._monitor_memory("阶段1完成")
        
        # 阶段2: 文本预清洗（多进程）
        print("🧹 === 阶段2: 文本预清洗（多进程） ===")
        
        clean_args = []
        config_dict = asdict(self.config)
        
        for chunk_id, texts in raw_texts_list:
            clean_args.append((chunk_id, texts, config_dict, list(self.config_manager.stop_words)))
        
        cleaned_texts_list = []
        with Pool(processes=self.config.num_processes) as pool:
            results = list(tqdm(
                pool.imap(clean_texts_worker, clean_args),
                total=len(clean_args),
                desc="文本清洗"
            ))
        
        # 重新排序结果
        cleaned_texts_dict = {chunk_id: texts for chunk_id, texts in results}
        cleaned_texts_list = [(chunk_id, cleaned_texts_dict[chunk_id]) 
                             for chunk_id, _ in chunk_data_list]
        
        print(f"✅ 阶段2完成：清洗了 {len(cleaned_texts_list)} 个数据块")
        self._monitor_memory("阶段2完成")
        
        # 阶段3: NLP处理（单进程或GPU任务）
        nlp_processor = NLPProcessor(
            self.config, 
            self.config_manager.nlp_model,
            self.config_manager.phrase_matcher,
            self.config_manager.stop_words
        )
        
        tokens_results = nlp_processor.extract_high_quality_phrases_batch(cleaned_texts_list)
        
        # 结果已按输入顺序返回，仅保留每块的 tokens_list 以降低序列化体积
        tokens_list = [tokens for _, tokens in tokens_results]
        
        print(f"✅ 阶段3完成：NLP处理了 {len(tokens_list)} 个数据块")
        self._monitor_memory("阶段3完成")
        
        # 阶段4: 统计计算（多进程）- 使用文件传递避免内存溢出
        print("📊 === 阶段4: 基础统计（多进程） ===")
        
        # 保存数据到临时文件以避免序列化内存问题
        temp_dir = os.path.join(gettempdir(), "analysis_chunks")
        os.makedirs(temp_dir, exist_ok=True)
        
        stats_args = []
        for i, ((chunk_id, chunk_data), tokens_list_chunk) in enumerate(zip(chunk_data_list, tokens_list)):
            precomputed = nlp_processor.precomputed_chunk_stats.get(chunk_id)
            
            # 保存数据到文件
            data_path = os.path.join(temp_dir, f"chunk_{chunk_id}.feather")
            tokens_path = os.path.join(temp_dir, f"tokens_{chunk_id}.pkl")
            
            try:
                chunk_data.to_feather(data_path)
                with open(tokens_path, "wb") as f:
                    pickle.dump(tokens_list_chunk, f, protocol=4)
                
                stats_args.append((chunk_id, data_path, tokens_path, precomputed, config_dict))
            except Exception as e:
                print(f"⚠️ Chunk {chunk_id} 文件保存失败: {e}")
                # 回退到直接传递（小数据块）
                stats_args.append((chunk_id, chunk_data, tokens_list_chunk, precomputed, config_dict))

        # 释放NLP阶段中间状态以节省内存
        nlp_processor.precomputed_chunk_stats = {}
        tokens_results = None
        tokens_list = None
        
        chunk_stats = []
        with Pool(processes=self.config.num_processes) as pool:
            results = list(tqdm(
                pool.imap(calculate_statistics_worker, stats_args),
                total=len(stats_args),
                desc="统计计算"
            ))
        
        # 清理临时文件
        try:
            import shutil
            shutil.rmtree(temp_dir)
        except Exception as e:
            print(f"⚠️ 临时文件清理失败: {e}")
        
        # 过滤有效结果
        chunk_stats = [r for r in results if r is not None]
        
        print(f"✅ 阶段4完成：统计了 {len(chunk_stats)} 个数据块")
        return chunk_stats
    
    def _merge_results(self, chunk_stats: List[ChunkStatistics]) -> bool:
        """阶段5: 结果合并"""
        merger = ResultsMerger(self.config)
        
        (self.token_frequencies, self.doc_frequencies, self.year_frequencies,
         self.first_occurrences, self.total_documents) = merger.merge_statistics(chunk_stats)
        
        # 应用最小出现频率过滤
        if self.config.min_occurrence > 1:
            self._apply_frequency_filter()
        
        return True
    
    def _analyze_first_occurrences(self) -> bool:
        """阶段6: 首次出现分析"""
        analyzer = FirstOccurrenceAnalyzer(self.config)
        
        first_occurrence_years = analyzer.analyze_first_occurrences(
            self.token_frequencies, self.doc_frequencies,
            self.year_frequencies, self.first_occurrences,
            self.total_documents
        )
        
        # 更新首次出现信息
        for token, year in first_occurrence_years.items():
            if token in self.first_occurrences:
                self.first_occurrences[token]['first_year'] = year
        
        return True
    
    def _perform_advanced_analysis(self) -> bool:
        """阶段7: 高级分析"""
        analyzer = AdvancedAnalyzer(self.config)
        
        self.advanced_metrics = analyzer.calculate_advanced_metrics(
            self.token_frequencies, self.doc_frequencies,
            self.year_frequencies, self.first_occurrences,
            self.total_documents
        )
        
        # 应用高级过滤
        if self.config.use_burst_analysis:
            self._apply_burst_filter()
        
        return True
    
    def _export_results(self) -> bool:
        """阶段8: 导出结果"""
        exporter = ExportManager(self.config)
        
        return exporter.export_results(
            self.first_occurrences, self.advanced_metrics, 
            self.year_frequencies
        )
    
    def _apply_frequency_filter(self):
        """应用最小频率过滤"""
        print(f"🔍 应用最小频率过滤 (>= {self.config.min_occurrence})")
        
        original_count = len(self.first_occurrences)
        
        # 过滤词汇
        filtered_tokens = {token for token, freq in self.token_frequencies.items() 
                          if freq >= self.config.min_occurrence}
        
        # 更新所有数据结构
        self.token_frequencies = Counter({t: f for t, f in self.token_frequencies.items() 
                                        if t in filtered_tokens})
        self.doc_frequencies = Counter({t: f for t, f in self.doc_frequencies.items() 
                                      if t in filtered_tokens})
        self.year_frequencies = {t: y for t, y in self.year_frequencies.items() 
                               if t in filtered_tokens}
        self.first_occurrences = {t: info for t, info in self.first_occurrences.items() 
                                if t in filtered_tokens}
        
        filtered_count = len(self.first_occurrences)
        print(f"   {original_count:,} -> {filtered_count:,} 个词汇")
    
    def _apply_burst_filter(self):
        """应用爆发度过滤"""
        print(f"🎯 应用爆发度过滤 (>= {self.config.innovation_burst_threshold})")
        
        original_count = len(self.first_occurrences)
        
        # 过滤词汇
        filtered_tokens = {token for token, metrics in self.advanced_metrics.items() 
                          if metrics['burst'] >= self.config.innovation_burst_threshold}
        
        # 更新所有数据结构
        self.token_frequencies = Counter({t: f for t, f in self.token_frequencies.items() 
                                        if t in filtered_tokens})
        self.doc_frequencies = Counter({t: f for t, f in self.doc_frequencies.items() 
                                      if t in filtered_tokens})
        self.year_frequencies = {t: y for t, y in self.year_frequencies.items() 
                               if t in filtered_tokens}
        self.first_occurrences = {t: info for t, info in self.first_occurrences.items() 
                                if t in filtered_tokens}
        self.advanced_metrics = {t: m for t, m in self.advanced_metrics.items() 
                               if t in filtered_tokens}
        
        filtered_count = len(self.first_occurrences)
        print(f"   {original_count:,} -> {filtered_count:,} 个词汇")
    
    def _print_summary(self, total_time: float):
        """打印分析总结"""
        print("\n" + "=" * 70)
        print("✅ 分析完成!")
        print(f"⏱️  总用时: {total_time:.2f} 秒")
        print(f"📊 发现词汇: {len(self.first_occurrences):,} 个")
        print(f"📄 处理文档: {self.total_documents:,} 篇")
        print(f"🎯 处理速度: {self.total_documents/total_time:.0f} 篇/秒")
        
        if self.config.use_burst_analysis and self.advanced_metrics:
            top_burst = max(self.advanced_metrics.items(), 
                          key=lambda x: x[1]['burst'])
            print(f"🌟 最高爆发度: '{top_burst[0]}' ({top_burst[1]['burst']:.4f})")
        
        print("=" * 70)

# =============================================================================
# 主程序入口
# =============================================================================

def main():
    """主程序"""
    # Python GC优化（大数据处理）
    gc.set_threshold(1000, 10, 10)
    
    # Windows多进程支持
    multiprocessing.freeze_support()
    
    # 内存优化设置
    try:
        # Windows系统不支持resource模块，跳过内存限制设置
        if sys.platform != 'win32':
            import resource
            # 设置内存限制（如果系统支持）- 32GB内存系统优化
            max_memory_gb = 28  # 限制最大内存使用为28GB，保留4GB给系统
            max_memory_bytes = max_memory_gb * 1024 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (max_memory_bytes, max_memory_bytes))
            print(f"✅ 内存限制已设置: {max_memory_gb}GB (32GB系统优化)")
        else:
            print("✅ Windows系统检测到，跳过内存限制设置")
    except Exception as e:
        print(f"⚠️ 内存限制设置失败: {e}")
    
    print("🚀 词汇首次出现分析系统 v2.0.1")
    print("📋 32GB内存优化版本")
    print("=" * 70)
    print("🔄 并行策略:")
    print("   阶段1: 分块数据读取 (主进程)")
    print("   阶段2: 文本预清洗 (8进程并行)")
    print("   阶段3: 高质量短语识别 (单进程/GPU任务)")
    print("   阶段4: 基础统计 (8进程并行)")
    print("=" * 70)
    
    # ============================================================================
    # 用户配置区 - 所有参数在此统一管理
    # ============================================================================
    
    # --- 文件路径 ---
    CSV_FILE_PATH = '2025外文论文全字段.csv'
    OUTPUT_FILE = 'analysis_results.csv'
    TEMP_DIR = './temp'
    
    # --- 数据列配置 ---
    TIME_COLUMNS = ['出版年', '卷', '期']
    INFO_COLUMNS = ['期刊名称', '标题', '关键词', 'KeywordsPlus', '摘要']
    UNIQUE_ID_COLUMN = '入藏号'
    
    # --- 基础分析参数 ---
    LANGUAGE = 'en'  # 'en'=英文, 'zh'=中文
    MIN_WORD_LENGTH = 2
    MIN_OCCURRENCE = 1  # 词汇最小出现次数
    
    # --- 性能配置 ---
    CHUNK_SIZE = 50000  # 每次读取的数据块大小（32GB内存优化）
    NUM_PROCESSES = 8  # 多进程并行数（32GB内存优化）
    BATCH_SIZE = 2000  # NLP批处理大小（32GB内存优化）
    
    # --- 停用词文件 ---
    STOPWORD_FILES = [
        'config/stopwords_en.txt',
        'config/stopwords_cn.txt',
        'config/structural_stopwords.txt',
        'config/scientific_stopwords_doc_freq.txt'
    ]
    
    # --- 高级分析功能开关 ---
    USE_TFIDF = True  # TF-IDF重要性计算
    USE_POS_FILTER = False  # 词性过滤（需要spaCy）
    USE_BURST_ANALYSIS = True  # 创新爆发度分析
    EXTRACT_NGRAMS = False  # N-gram多词组合提取
    USE_PHRASE_EXTRACTION = False  # 短语提取（名词短语+固定短语）⭐
    NGRAM_RANGE = (2, 3)  # N-gram范围
    
    # --- 爆发度分析参数 ---
    INNOVATION_BURST_THRESHOLD = 0.15  # 创新爆发度阈值
    MIN_YEARS_SPAN = 2  # 最小年份跨度
    TURNING_POINT_GROWTH_FACTOR = 3.0  # 转折点增长因子
    TURNING_POINT_MIN_FREQ = 100  # 转折点最小频率
    RECENT_WINDOW_YEARS = 5  # 近期窗口年数
    EXCLUDE_LAST_N_YEARS = 1  # 排除最后N年
    DOC_FREQ_THRESHOLD = 0.9  # 文档频率阈值
    
    # --- 数据行数（已知） ---
    TOTAL_ROWS = 9167774
    
    # ============================================================================
    # 创建配置对象
    # ============================================================================
    
    config = SystemConfig(
        csv_file_path=CSV_FILE_PATH,
        output_file=OUTPUT_FILE,
        temp_dir=TEMP_DIR,
        time_columns=TIME_COLUMNS,
        info_columns=INFO_COLUMNS,
        unique_id_column=UNIQUE_ID_COLUMN,
        language=LANGUAGE,
        min_word_length=MIN_WORD_LENGTH,
        min_occurrence=MIN_OCCURRENCE,
        chunk_size=CHUNK_SIZE,
        num_processes=NUM_PROCESSES,
        batch_size=BATCH_SIZE,
        stopword_files=STOPWORD_FILES,
        use_tfidf=USE_TFIDF,
        use_pos_filter=USE_POS_FILTER,
        use_burst_analysis=USE_BURST_ANALYSIS,
        extract_ngrams=EXTRACT_NGRAMS,
        use_phrase_extraction=USE_PHRASE_EXTRACTION,
        ngram_range=NGRAM_RANGE,
        innovation_burst_threshold=INNOVATION_BURST_THRESHOLD,
        min_years_span=MIN_YEARS_SPAN,
        turning_point_growth_factor=TURNING_POINT_GROWTH_FACTOR,
        turning_point_min_freq=TURNING_POINT_MIN_FREQ,
        recent_window_years=RECENT_WINDOW_YEARS,
        exclude_last_n_years=EXCLUDE_LAST_N_YEARS,
        doc_freq_threshold=DOC_FREQ_THRESHOLD
    )
    
    # 创建分析器
    pipeline = TextAnalysisPipeline(config)
    
    # 运行分析
    success = pipeline.run_analysis(TOTAL_ROWS)
    
    if success:
        print(f"\n🎉 分析成功完成！结果保存在: {config.output_file}")
        
        # 显示top词汇
        if pipeline.advanced_metrics:
            print("\n🌟 创新爆发度最高的5个词汇:")
            top_burst = sorted(pipeline.advanced_metrics.items(), 
                             key=lambda x: x[1]['burst'], reverse=True)[:5]
            for i, (token, metrics) in enumerate(top_burst, 1):
                print(f"   {i}. '{token}': 爆发度={metrics['burst']:.4f}, "
                      f"频率={metrics['frequency']:,}")
    else:
        print("\n❌ 分析失败，请检查配置和数据文件")
    
    print("\n💡 提示: 可使用 pipeline.first_occurrences 查看详细结果")
    return pipeline if success else None

if __name__ == "__main__":
    pipeline = main()