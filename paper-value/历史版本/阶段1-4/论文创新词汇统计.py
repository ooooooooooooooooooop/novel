
import pandas as pd
import re
import json
import pickle
import os
import time
import difflib
import math
from collections import defaultdict, Counter
import warnings
import multiprocessing
from multiprocessing import Pool, cpu_count
import numpy as np
import gc
import psutil

# 设置环境变量减少内存占用
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['NUMEXPR_NUM_THREADS'] = '1'

warnings.filterwarnings('ignore')
os.chdir(f'{os.path.dirname(os.path.abspath(__file__))}')
# 尝试导入依赖库
try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

try:
    import spacy
    try:
        spacy.load('en_core_web_sm')
        SPACY_AVAILABLE = True
    except OSError:
        SPACY_AVAILABLE = False
except ImportError:
    SPACY_AVAILABLE = False

try:
    import cupy as cp
    CUPY_AVAILABLE = True
except ImportError:
    CUPY_AVAILABLE = False
    print("⚠️  未安装cupy，GPU加速将不可用")

try:
    import numba
    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False
    print("⚠️  未安装numba，数值加速将受限")

try:
    import pyarrow
    PYARROW_AVAILABLE = True
except ImportError:
    PYARROW_AVAILABLE = False
    print("⚠️  未安装pyarrow，将使用CSV格式（较慢）")
    print("   建议运行：pip install pyarrow")

def _process_chunk_worker(args):
    """多进程worker函数：直接读取Parquet/CSV指定行范围"""
    chunk_id, file_path, start_row, end_row, header, config = args
    
    # 根据文件扩展名判断格式
    if file_path.endswith('.parquet'):
        # Parquet格式：使用高效的行范围过滤
        try:
            import pyarrow.parquet as pq
            # 使用 pyarrow 直接读取行范围（避免加载全部数据）
            parquet_file = pq.ParquetFile(file_path)
            # 读取指定的行组（row groups），更高效
            chunk_data = parquet_file.read_row_groups(
                row_groups=list(range(parquet_file.num_row_groups))
            ).to_pandas().iloc[start_row:end_row]
        except Exception:
            # 回退方案：使用 pandas 读取后切片
            chunk_data = pd.read_parquet(file_path).iloc[start_row:end_row]
    else:
        # CSV格式（兼容旧方式）
        if start_row == 0:
            chunk_data = pd.read_csv(file_path, nrows=end_row - start_row)
        else:
            # 跳过header和前start_row行数据，共start_row+1行
            chunk_data = pd.read_csv(file_path, skiprows=start_row + 1, nrows=end_row - start_row, names=header)
    
    # 解包配置
    stop_words = config['stop_words']
    min_word_length = config['min_word_length']
    language = config['language']
    analysis_mode = config['analysis_mode']
    time_columns = config['time_columns']
    info_columns = config['info_columns']
    text_column = config['text_column']
    unique_id_column = config['unique_id_column']
    use_pos_filter = config['use_pos_filter']
    extract_ngrams = config['extract_ngrams']
    ngram_range = config['ngram_range']
    
    # 预合并分析列（如果需要）
    if analysis_mode == 'info_columns':
        chunk_data['combined_info'] = chunk_data[info_columns].fillna('').agg(' '.join, axis=1)
    
    # 预编译正则表达式
    word_pattern = re.compile(r'\b[a-zA-Z]+(?:-[a-zA-Z]+)*\b')
    punctuation_pattern1 = re.compile(r'[&()（）【】\[\]{}]')
    punctuation_pattern2 = re.compile(r'[,:;．。！？]')
    punctuation_pattern3 = re.compile(r'["\'""'']')
    punctuation_pattern4 = re.compile(r'[`，、；：]')
    hyphen_pattern = re.compile(r'\s+-\s+')
    word_concat_pattern = re.compile(r'([a-z]{4,})(the|this|our|and|or|of|in|to|for|with|from|by)(\s|$)')
    
    # 本地统计
    local_freq = Counter()
    local_doc_freq = Counter()
    local_year_counts = defaultdict(lambda: defaultdict(int))
    local_first_occurrence = {}
    local_doc_count = 0
    
    # 批量收集文本用于spacy批处理
    texts_to_process = []
    rows_data = []
    
    for _, row in chunk_data.iterrows():
        row_dict = row.to_dict()
        
        # 创建分析文本
        if analysis_mode == 'info_columns':
            analysis_text = row_dict.get('combined_info', '')
        else:
            value = row_dict.get(text_column)
            analysis_text = str(value) if pd.notna(value) else ''
        
        texts_to_process.append(analysis_text)
        rows_data.append(row_dict)
    
    # 批量预处理所有文本（词性过滤将在主进程中统一执行）
    all_words_list = []
    for i, text in enumerate(texts_to_process):
        words = _preprocess_text_worker(
            text, language, min_word_length, stop_words, analysis_mode,
            word_pattern, punctuation_pattern1, punctuation_pattern2,
            punctuation_pattern3, punctuation_pattern4, hyphen_pattern,
            word_concat_pattern, extract_ngrams, ngram_range
        )
        all_words_list.append(words)
    
    # 处理每行的统计
    for i, (row_dict, words) in enumerate(zip(rows_data, all_words_list)):
        if not words:
            continue
        
        local_doc_count += 1
        unique_words = set(words)
        
        for word in words:
            local_freq[word] += 1
        
        for word in unique_words:
            local_doc_freq[word] += 1
        
        primary_year = row_dict.get(time_columns[0])
        year_val = int(primary_year) if pd.notna(primary_year) else None
        if year_val is not None:
            for word in words:
                local_year_counts[word][year_val] += 1
        
        new_words = [w for w in words if w not in local_first_occurrence]
        if new_words:
            # 仅保存CSV导出需要的字段：unique_id, time_columns, analysis_text（移除info_columns以减少85%存储）
            paper_info = {unique_id_column: str(row_dict[unique_id_column])}
            for col in time_columns:
                value = row_dict[col]
                paper_info[col] = int(value) if pd.notna(value) else 0
            
            for word in new_words:
                paper_info_copy = paper_info.copy()
                paper_info_copy['analysis_text'] = _extract_snippet_worker(texts_to_process[i], word, 30)
                local_first_occurrence[word] = paper_info_copy
    
    # 构建4张长表并落盘（Parquet优先，CSV回退）
    # 1. counts_df: word, token_count, doc_count
    counts_df = pd.DataFrame({
        'word': list(local_freq.keys()),
        'token_count': list(local_freq.values()),
        'doc_count': [local_doc_freq[w] for w in local_freq.keys()]
    })
    
    # 2. year_df: word, year, count（减少内存峰值）
    year_words = []
    year_years = []
    year_counts = []
    for word, year_dict in local_year_counts.items():
        for year, count in year_dict.items():
            year_words.append(word)
            year_years.append(year)
            year_counts.append(count)
    year_df = pd.DataFrame({'word': year_words, 'year': year_years, 'count': year_counts})
    del year_words, year_years, year_counts
    
    # 3. first_df: word + all paper info
    if local_first_occurrence:
        first_df = pd.DataFrame.from_dict(
            {word: {'word': word, **info} for word, info in local_first_occurrence.items()},
            orient='index'
        ).reset_index(drop=True)
    else:
        first_df = pd.DataFrame()
    
    # 写入文件（移除meta.parquet，文档数可从counts推导，减少2247次I/O操作）
    temp_dir = './temp'
    os.makedirs(temp_dir, exist_ok=True)
    
    if PYARROW_AVAILABLE:
        counts_df.to_parquet(os.path.join(temp_dir, f'chunk_{chunk_id}_counts.parquet'), index=False, compression='snappy')
        year_df.to_parquet(os.path.join(temp_dir, f'chunk_{chunk_id}_year.parquet'), index=False, compression='snappy')
        first_df.to_parquet(os.path.join(temp_dir, f'chunk_{chunk_id}_first.parquet'), index=False, compression='snappy')
    else:
        counts_df.to_csv(os.path.join(temp_dir, f'chunk_{chunk_id}_counts.csv'), index=False)
        year_df.to_csv(os.path.join(temp_dir, f'chunk_{chunk_id}_year.csv'), index=False)
        first_df.to_csv(os.path.join(temp_dir, f'chunk_{chunk_id}_first.csv'), index=False)
    
    # 清理内存
    del local_freq, local_doc_freq, local_year_counts, local_first_occurrence
    del chunk_data, texts_to_process, rows_data, all_words_list
    del counts_df, year_df, first_df
    gc.collect()
    
    # 返回chunk_id和文档数（用于后续聚合）
    return (chunk_id, local_doc_count)

def _preprocess_text_worker(text, language, min_word_length, stop_words, analysis_mode,
                            word_pattern, punctuation_pattern1, punctuation_pattern2,
                            punctuation_pattern3, punctuation_pattern4, hyphen_pattern,
                            word_concat_pattern, extract_ngrams, ngram_range):
    """文本预处理worker函数"""
    if pd.isna(text) or not isinstance(text, str) or not text.strip():
        return []
    
    if language in ['zh', 'mixed'] and not re.search(r'[\u4e00-\u9fffA-Za-z]', text):
        return []
    
    text = text.lower()
    text = word_concat_pattern.sub(r'\1 \2\3', text)
    
    if analysis_mode == 'info_columns':
        text = punctuation_pattern1.sub(' ', text)
        text = punctuation_pattern2.sub(' ', text)
        text = punctuation_pattern3.sub(' ', text)
        text = punctuation_pattern4.sub(' ', text)
        text = hyphen_pattern.sub(' ', text)
    
    words = []
    if language == 'zh' and JIEBA_AVAILABLE:
        words = list(jieba.cut(text))
    elif language == 'en':
        words = word_pattern.findall(text)
    elif language == 'mixed':
        english_words = word_pattern.findall(text)
        if JIEBA_AVAILABLE:
            chinese_text = re.sub(r'[a-zA-Z\s\-]+', ' ', text)
            chinese_words = [w for w in jieba.cut(chinese_text) if re.match(r'[\u4e00-\u9fff]+', w)]
            words = english_words + chinese_words
        else:
            words = english_words
    else:
        words = text.split()
    
    processed_words = []
    for word in words:
        if language == 'en':
            clean_word = re.sub(r'[^a-zA-Z\-]', '', word).strip('-')
        elif language == 'zh':
            clean_word = re.sub(r'[^\u4e00-\u9fff]', '', word)
        else:
            if re.match(r'^[a-zA-Z\-]+$', word):
                clean_word = re.sub(r'[^a-zA-Z\-]', '', word).strip('-')
            else:
                clean_word = re.sub(r'[^\u4e00-\u9fff]', '', word)
        
        if (len(clean_word) >= min_word_length and 
            clean_word not in stop_words and
            clean_word.strip() and
            not clean_word.isdigit() and
            clean_word != '-'):
            processed_words.append(clean_word)
    
    if extract_ngrams and len(processed_words) >= ngram_range[0]:
        ngrams = []
        for n in range(ngram_range[0], ngram_range[1] + 1):
            for i in range(len(processed_words) - n + 1):
                ngram = '_'.join(processed_words[i:i+n])
                ngrams.append(ngram)
        processed_words.extend(ngrams)
    
    return processed_words

def _batch_pos_filter(all_words_list, nlp, batch_size=1000):
    """批量词性过滤（GPU加速优化版）
    
    Args:
        all_words_list: 词汇列表的列表
        nlp: spaCy模型（已启用GPU）
        batch_size: GPU批处理大小（GPU模式下可设置更大，如1000-2000）
    """
    if not all_words_list or not nlp:
        return all_words_list
    
    texts = [' '.join(words) for words in all_words_list if words]
    if not texts:
        return all_words_list
    
    valid_pos = {'NOUN', 'PROPN', 'ADJ', 'NUM', 'X'}
    filtered_results = []
    
    # 使用 spaCy 的 pipe() 方法批量处理
    # GPU模式下使用更大的batch_size以最大化GPU利用率
    for doc, original_words in zip(nlp.pipe(texts, batch_size=batch_size), all_words_list):
        if not original_words:
            filtered_results.append([])
            continue
        
        # 使用集合加速查找
        original_words_set = set(original_words)
        filtered_words = []
        for token in doc:
            if token.pos_ in valid_pos and token.text in original_words_set:
                filtered_words.append(token.text)
        filtered_results.append(filtered_words)
    
    return filtered_results

def _extract_snippet_worker(text, keyword, max_len=30):
    """提取包含关键字的句子片段"""
    if not text or not keyword:
        return text[:max_len] + '...' if text and len(text) > max_len else (text or '')
    
    text_lower = text.lower()
    pos = text_lower.find(keyword.lower())
    if pos == -1:
        return text[:max_len] + '...' if len(text) > max_len else text
    
    delimiters = '.!?;。！？；\n\r'
    start = pos
    while start > 0 and text[start - 1] not in delimiters:
        start -= 1
    end = pos
    n = len(text)
    while end < n and text[end] not in delimiters:
        end += 1
    
    sentence = text[start:end].strip()
    if len(sentence) <= max_len:
        return sentence
    
    rel_pos = pos - start
    half = max_len // 2
    window_start = max(0, rel_pos - half)
    window_end = window_start + max_len
    if window_end > len(sentence):
        window_end = len(sentence)
        window_start = max(0, window_end - max_len)
    
    snippet = sentence[window_start:window_end].strip()
    prefix = '...' if window_start > 0 else ''
    suffix = '...' if window_end < len(sentence) else ''
    return f"{prefix}{snippet}{suffix}"

class WordFirstOccurrenceAnalyzer:
    """词汇首次出现分析器"""
    
    def __init__(self, csv_file_path, 
                 time_columns=['year', 'volume', 'issue'], 
                 info_columns=['journal', 'author'],
                 text_column=None,
                 unique_id_column='paper_id',
                 language='en', 
                 min_word_length=2,
                 analyze_info_columns=True,
                 min_occurrence=1,
                 show_progress=True,
                 progress_interval=1000,
                 use_tfidf=True,
                 stopword_files=['config/stopwords_en.txt', 'config/stopwords_cn.txt', 'config/scientific_stopwords_doc_freq.txt'],
                 use_burst_filter=True,
                 innovation_burst_threshold=0.15,
                 min_years_span=2,
                 turning_point_growth_factor=3.0,
                 turning_point_min_freq=100,
                 recent_window_years=5,
                 exclude_last_n_years=1,
                 recent_early_split_year=None,
                 use_pos_filter=True,
                 extract_ngrams=False,
                 ngram_range=(2, 3),
                 doc_freq_threshold=0.9):
        """
        初始化分析器
        
        Args:
            csv_file_path (str): CSV文件路径
            time_columns (list): 时间列列表，按优先级顺序排列
            info_columns (list): 信息列列表
            text_column (str or None): 文本内容列名，None表示分析info_columns
            unique_id_column (str): 唯一号列名
            language (str): 语言类型 ('en', 'zh', 'mixed')，用于分词策略
            min_word_length (int): 最小词汇长度
            analyze_info_columns (bool): 是否分析信息列
            min_occurrence (int): 最小出现频率，用于过滤低频词汇
            show_progress (bool): 是否显示进度条
            progress_interval (int): 进度显示间隔（当无进度条时使用）
            use_tfidf (bool): 是否使用TF-IDF算法提取创新词汇
            stopword_files (list): 停用词文件路径列表，将加载并合并所有文件（自动去重）
            use_burst_filter (bool): 是否启用创新爆发度过滤
            innovation_burst_threshold (float): 创新爆发度最低阈值（0-1之间）
            min_years_span (int): 词汇至少跨越的年份数
            turning_point_growth_factor (float): 拐点检测的增长倍数阈值
            turning_point_min_freq (int): 拐点检测的最小频率阈值
            recent_window_years (int): 近期窗口年数，用于计算近期/早期比
            exclude_last_n_years (int): 排除最后N年（处理不完整数据）
            recent_early_split_year (int or None): 手动指定近期/早期分界年份，None则自动计算
            use_pos_filter (bool): 是否使用词性标注过滤（需要spacy）
            extract_ngrams (bool): 是否提取N-gram短语
            ngram_range (tuple): N-gram范围，如(2,3)表示提取2-gram和3-gram
            doc_freq_threshold (float): 文档频率上限阈值（0-1之间）
        """
        self.csv_file_path = csv_file_path
        self.time_columns = time_columns
        self.info_columns = info_columns
        self.text_column = text_column
        self.unique_id_column = unique_id_column
        self.language = language
        self.min_word_length = min_word_length
        self.analyze_info_columns = analyze_info_columns
        self.min_occurrence = min_occurrence
        self.show_progress = show_progress and TQDM_AVAILABLE
        self.progress_interval = progress_interval
        self.use_tfidf = use_tfidf
        self.stopword_files = stopword_files
        self.header = None  # 数据列名（从验证过程中获取）
        self.first_occurrence_log = {}
        self.word_frequencies = Counter()
        self.word_document_frequency = Counter()
        self.word_tfidf_scores = {}
        self.total_documents = 0
        self.start_time = None
        self.word_year_counts = defaultdict(lambda: defaultdict(int))
        self.word_burst_scores = {}
        self.word_burst_details = {}
        self.use_burst_filter = use_burst_filter
        self.innovation_burst_threshold = innovation_burst_threshold
        self.min_years_span = min_years_span
        self.turning_point_growth_factor = turning_point_growth_factor
        self.turning_point_min_freq = turning_point_min_freq
        self.recent_window_years = recent_window_years
        self.exclude_last_n_years = exclude_last_n_years
        self.recent_early_split_year = recent_early_split_year
        self.use_pos_filter = use_pos_filter
        self.extract_ngrams = extract_ngrams
        self.ngram_range = ngram_range
        self.doc_freq_threshold = doc_freq_threshold
        self.nlp = None
        
        # 预编译正则表达式
        self.word_pattern = re.compile(r'\b[a-zA-Z]+(?:-[a-zA-Z]+)*\b')
        self.punctuation_pattern1 = re.compile(r'[&()（）【】\[\]{}]')
        self.punctuation_pattern2 = re.compile(r'[,:;．。！？]')
        self.punctuation_pattern3 = re.compile(r'["\'""'']')
        self.punctuation_pattern4 = re.compile(r'[`，、；：]')
        self.hyphen_pattern = re.compile(r'\s+-\s+')
        self.word_concat_pattern = re.compile(r'([a-z]{4,})(the|this|our|and|or|of|in|to|for|with|from|by)(\s|$)')
        
        # 确定分析模式
        self.analysis_mode = 'info_columns' if (self.analyze_info_columns or self.text_column is None) else 'text_column'
        
        # 预定义的停用词列表
        self.stop_words = self._get_stop_words()
        
        # 加载spacy模型（主进程GPU加速）
        if self.use_pos_filter:
            if not SPACY_AVAILABLE:
                print("⚠️  未安装spacy库，词性过滤将被禁用")
                print("   建议运行：pip install spacy")
                self.use_pos_filter = False
            else:
                try:
                    import spacy
                    # 尝试启用GPU加速
                    gpu_enabled = spacy.prefer_gpu()
                    self.nlp = spacy.load('en_core_web_sm')
                    
                    if gpu_enabled:
                        print("✅ spaCy英文模型加载成功（GPU加速已启用）")
                        print("🚀 词性过滤将使用GPU批量推理，显著提升性能")
                    else:
                        print("✅ spaCy英文模型加载成功（CPU模式）")
                        print("💡 提示：安装 spacy[cuda] 可启用GPU加速")
                    
                    print("💡 架构：主进程统一词性过滤，子进程仅负责文本预处理")
                except OSError:
                    print("⚠️  未找到spaCy英文模型，词性过滤将被禁用")
                    print("   建议运行：python -m spacy download en_core_web_sm")
                    self.use_pos_filter = False
                    self.nlp = None
        
        # 如果禁用了词性过滤，提示用户
        if not self.use_pos_filter:
            print("💡 词性过滤已禁用，可减少内存占用，但可能包含更多非实质性词汇")
        
        # 分阶段处理配置
        self.intermediate_prefix = './temp/' + self.csv_file_path + '.intermediate_stage1'
        
        # 验证配置
        self._validate_config()
        
        if self.use_tfidf:
            print("💡 TF-IDF模式已启用，将自动识别创新词汇")
        if self.use_pos_filter:
            print("💡 词性过滤已启用，仅保留名词和形容词")
        if self.extract_ngrams:
            print(f"💡 N-gram提取已启用，范围：{self.ngram_range}")
        
        if CUPY_AVAILABLE:
            try:
                gpu_device = cp.cuda.Device()
                gpu_memory = gpu_device.mem_info
                print(f"✅ GPU加速已启用（{gpu_device.compute_capability}，显存：{gpu_memory[1]//1024**3}GB）")
            except:
                print("⚠️  GPU检测失败，将使用CPU模式")
        else:
            print("💡 GPU加速未启用，使用CPU模式")
        
    def _print_memory_usage(self):
        """打印当前内存使用情况"""
        try:
            process = psutil.Process()
            mem_info = process.memory_info()
            mem_mb = mem_info.rss / (1024**2)
            print(f"   当前内存使用：{mem_mb:.1f} MB")
        except Exception:
            pass
    
    def clean_temp_files(self):
        """清理temp文件夹中的chunk文件（Parquet/CSV格式）"""
        temp_dir = './temp'
        if not os.path.exists(temp_dir):
            print("⚠️  temp文件夹不存在，无需清理")
            return
        
        chunk_files = [f for f in os.listdir(temp_dir) 
                      if f.startswith('chunk_') and (f.endswith('.parquet') or f.endswith('.csv'))]
        if not chunk_files:
            print("✅ temp文件夹中没有chunk文件")
            return
        
        total_size = sum(os.path.getsize(os.path.join(temp_dir, f)) for f in chunk_files)
        size_mb = total_size / (1024**2)
        
        print(f"🗑️  准备清理 {len(chunk_files)} 个chunk文件（共 {size_mb:.1f} MB）")
        for chunk_file in chunk_files:
            os.remove(os.path.join(temp_dir, chunk_file))
        print("✅ temp文件夹清理完成")
    
    def save_intermediate_results(self):
        """保存阶段1的中间结果（Parquet/CSV格式）"""
        print(f"💾 保存中间结果到：{self.intermediate_prefix}_*")
        
        # 确保temp目录存在
        temp_dir = os.path.dirname(self.intermediate_prefix)
        if temp_dir and not os.path.exists(temp_dir):
            os.makedirs(temp_dir, exist_ok=True)
            print(f"   创建目录：{temp_dir}")
        
        # 1. 词频与文档频次
        counts_records = []
        for word in self.word_frequencies.keys():
            counts_records.append({
                'word': word,
                'token_count': self.word_frequencies[word],
                'doc_count': self.word_document_frequency[word]
            })
        counts_df = pd.DataFrame(counts_records)
        
        # 2. 年份统计
        year_records = []
        for word, year_dict in self.word_year_counts.items():
            for year, count in year_dict.items():
                year_records.append({'word': word, 'year': year, 'count': count})
        year_df = pd.DataFrame(year_records)
        
        # 3. 首次出现记录
        first_records = []
        for word, info in self.first_occurrence_log.items():
            record = {'word': word}
            record.update(info)
            first_records.append(record)
        first_df = pd.DataFrame(first_records)
        
        # 4. 元数据
        config_df = pd.DataFrame([{
            'total_documents': self.total_documents,
            'header': str(self.header),
            'time_columns': str(self.time_columns),
            'info_columns': str(self.info_columns),
            'text_column': self.text_column,
            'unique_id_column': self.unique_id_column,
            'language': self.language,
            'min_word_length': self.min_word_length,
            'min_occurrence': self.min_occurrence,
            'analysis_mode': self.analysis_mode
        }])
        
        # 写入文件
        total_size = 0
        if PYARROW_AVAILABLE:
            counts_df.to_parquet(f'{self.intermediate_prefix}_counts.parquet', index=False, compression='snappy')
            year_df.to_parquet(f'{self.intermediate_prefix}_year.parquet', index=False, compression='snappy')
            first_df.to_parquet(f'{self.intermediate_prefix}_first.parquet', index=False, compression='snappy')
            config_df.to_parquet(f'{self.intermediate_prefix}_config.parquet', index=False, compression='snappy')
            total_size = sum([
                os.path.getsize(f'{self.intermediate_prefix}_counts.parquet'),
                os.path.getsize(f'{self.intermediate_prefix}_year.parquet'),
                os.path.getsize(f'{self.intermediate_prefix}_first.parquet'),
                os.path.getsize(f'{self.intermediate_prefix}_config.parquet')
            ])
        else:
            counts_df.to_csv(f'{self.intermediate_prefix}_counts.csv', index=False)
            year_df.to_csv(f'{self.intermediate_prefix}_year.csv', index=False)
            first_df.to_csv(f'{self.intermediate_prefix}_first.csv', index=False)
            config_df.to_csv(f'{self.intermediate_prefix}_config.csv', index=False)
            total_size = sum([
                os.path.getsize(f'{self.intermediate_prefix}_counts.csv'),
                os.path.getsize(f'{self.intermediate_prefix}_year.csv'),
                os.path.getsize(f'{self.intermediate_prefix}_first.csv'),
                os.path.getsize(f'{self.intermediate_prefix}_config.csv')
            ])
        
        file_size = total_size / (1024**2)
        print(f"✅ 中间结果已保存（{file_size:.1f} MB）")
        return True
    
    def load_intermediate_results(self):
        """加载阶段1的中间结果（Parquet/CSV格式）"""
        # 检测文件格式
        if os.path.exists(f'{self.intermediate_prefix}_counts.parquet'):
            file_ext = 'parquet'
            read_func = pd.read_parquet
        elif os.path.exists(f'{self.intermediate_prefix}_counts.csv'):
            file_ext = 'csv'
            read_func = pd.read_csv
        else:
            print(f"❌ 中间结果文件不存在：{self.intermediate_prefix}_*")
            return False
        
        print(f"📂 加载中间结果：{self.intermediate_prefix}_*.{file_ext}")
        try:
            # 1. 词频与文档频次
            counts_df = read_func(f'{self.intermediate_prefix}_counts.{file_ext}')
            self.word_frequencies = Counter()
            self.word_document_frequency = Counter()
            for _, row in counts_df.iterrows():
                self.word_frequencies[row['word']] = int(row['token_count'])
                self.word_document_frequency[row['word']] = int(row['doc_count'])
            
            # 2. 年份统计
            year_df = read_func(f'{self.intermediate_prefix}_year.{file_ext}')
            self.word_year_counts = defaultdict(lambda: defaultdict(int))
            for _, row in year_df.iterrows():
                self.word_year_counts[row['word']][int(row['year'])] = int(row['count'])
            
            # 3. 首次出现记录
            first_df = read_func(f'{self.intermediate_prefix}_first.{file_ext}')
            self.first_occurrence_log = {}
            for _, row in first_df.iterrows():
                word = row['word']
                info = row.drop('word').to_dict()
                self.first_occurrence_log[word] = info
            
            # 4. 元数据
            config_df = read_func(f'{self.intermediate_prefix}_config.{file_ext}')
            config_row = config_df.iloc[0]
            self.total_documents = int(config_row['total_documents'])
            self.header = eval(config_row['header'])
            
            print(f"✅ 加载成功！")
            print(f"   词汇数：{len(self.first_occurrence_log):,}")
            print(f"   文档数：{self.total_documents:,}")
            return True
        except Exception as e:
            print(f"❌ 加载失败：{e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _calculate_tfidf(self):
        """计算TF-IDF分数（GPU加速版）"""
        if self.total_documents == 0:
            return
        
        if CUPY_AVAILABLE:
            self._calculate_tfidf_gpu()
        else:
            self._calculate_tfidf_cpu()
    
    def _calculate_tfidf_gpu(self):
        """GPU加速的TF-IDF计算"""
        print("🚀 使用GPU加速计算TF-IDF...")
        
        words = list(self.first_occurrence_log.keys())
        n_words = len(words)
        
        if n_words == 0:
            return
        
        # 构建numpy数组
        tf_array = np.array([self.word_frequencies[w] for w in words], dtype=np.float64)
        df_array = np.array([self.word_document_frequency[w] for w in words], dtype=np.float64)
        
        # 转换到GPU
        tf_gpu = cp.array(tf_array)
        df_gpu = cp.array(df_array)
        
        # GPU批量计算IDF
        idf_gpu = cp.log(self.total_documents / df_gpu)
        
        # GPU批量计算TF-IDF
        tfidf_gpu = tf_gpu * idf_gpu
        
        # 转回CPU
        tfidf_array = cp.asnumpy(tfidf_gpu)
        
        # 构建结果字典
        for word, tfidf_score in zip(words, tfidf_array):
            self.word_tfidf_scores[word] = float(tfidf_score)
        
        # 释放GPU内存
        del tf_gpu, df_gpu, idf_gpu, tfidf_gpu
        cp.get_default_memory_pool().free_all_blocks()
    
    def _calculate_tfidf_cpu(self):
        """CPU版本的TF-IDF计算（后备方案）"""
        for word in self.first_occurrence_log.keys():
            tf = self.word_frequencies[word]
            df = self.word_document_frequency[word]
            
            idf = math.log(self.total_documents / df) if df > 0 else 0
            tfidf = tf * idf
            
            self.word_tfidf_scores[word] = tfidf
    
    def _calculate_innovation_burst_score(self):
        """计算创新爆发度分数（GPU加速版）"""
        if not self.word_year_counts:
            return
        
        print("📈 计算创新爆发度分数...")
        
        if CUPY_AVAILABLE:
            self._calculate_innovation_burst_score_gpu()
        else:
            self._calculate_innovation_burst_score_cpu()
    
    def _calculate_innovation_burst_score_gpu(self):
        """GPU加速的爆发度计算"""
        print("🚀 使用GPU加速计算爆发度...")
        
        # 收集所有年份
        all_years = set()
        for counts in self.word_year_counts.values():
            all_years.update(counts.keys())
        all_years = sorted(all_years)
        year_to_idx = {y: i for i, y in enumerate(all_years)}
        n_years = len(all_years)
        
        # 筛选符合条件的词汇
        valid_words = []
        for word in self.first_occurrence_log.keys():
            year_counts = self.word_year_counts.get(word, {})
            if year_counts and len(year_counts) >= self.min_years_span:
                valid_words.append(word)
        
        if not valid_words:
            print("⚠️  警告：没有符合条件的词汇用于计算爆发度")
            return
        
        n_words = len(valid_words)
        print(f"   处理 {n_words:,} 个词汇，{n_years} 个年份...")
        
        # 构建年度频次矩阵
        year_freq_matrix = np.zeros((n_words, n_years), dtype=np.float64)
        for i, word in enumerate(valid_words):
            year_counts = self.word_year_counts[word]
            for year, count in year_counts.items():
                j = year_to_idx[year]
                year_freq_matrix[i, j] = count
        
        # 转移到GPU
        year_freq_gpu = cp.array(year_freq_matrix)
        
        # GPU批量计算指标1：最大增长率
        shifted_freq = cp.roll(year_freq_gpu, 1, axis=1)
        shifted_freq[:, 0] = 0
        growth_rates = (year_freq_gpu + 1) / (shifted_freq + 1) - 1
        growth_rates[:, 0] = 0
        max_growth_rates = cp.max(growth_rates, axis=1)
        
        # GPU批量计算指标2：变异系数
        mean_freq = cp.mean(year_freq_gpu, axis=1, keepdims=True)
        std_freq = cp.std(year_freq_gpu, axis=1, keepdims=True)
        cvs = cp.where(mean_freq > 0, std_freq / mean_freq, 0).flatten()
        
        # GPU批量计算指标3：近期/早期比值
        if self.recent_early_split_year:
            split_year = self.recent_early_split_year
            split_idx = year_to_idx.get(split_year, n_years // 2)
        else:
            if self.exclude_last_n_years > 0:
                effective_end = n_years - self.exclude_last_n_years
            else:
                effective_end = n_years
            split_idx = max(0, effective_end - self.recent_window_years)
        
        early_freq = year_freq_gpu[:, :split_idx] if split_idx > 0 else cp.zeros((n_words, 1))
        recent_freq = year_freq_gpu[:, split_idx:] if split_idx < n_years else cp.zeros((n_words, 1))
        
        early_mean = cp.mean(early_freq, axis=1) if early_freq.shape[1] > 0 else cp.zeros(n_words)
        recent_mean = cp.mean(recent_freq, axis=1) if recent_freq.shape[1] > 0 else cp.zeros(n_words)
        recent_early_ratios = (recent_mean + 1) / (early_mean + 1)
        
        # GPU批量计算峰值频率
        peak_freqs = cp.max(year_freq_gpu, axis=1)
        
        # 转回CPU进行归一化和后续计算
        max_growth_rates_cpu = cp.asnumpy(max_growth_rates)
        cvs_cpu = cp.asnumpy(cvs)
        recent_early_ratios_cpu = cp.asnumpy(recent_early_ratios)
        peak_freqs_cpu = cp.asnumpy(peak_freqs)
        
        # 释放GPU内存
        del year_freq_gpu, shifted_freq, growth_rates, mean_freq, std_freq
        del early_freq, recent_freq, early_mean, recent_mean
        del max_growth_rates, cvs, recent_early_ratios, peak_freqs
        cp.get_default_memory_pool().free_all_blocks()
        
        # 归一化
        def normalize_array(arr):
            min_val, max_val = arr.min(), arr.max()
            if min_val == max_val:
                return np.full_like(arr, 0.5)
            return (arr - min_val) / (max_val - min_val)
        
        norm_max_growth = normalize_array(max_growth_rates_cpu)
        norm_cvs = normalize_array(cvs_cpu)
        norm_ratios = normalize_array(recent_early_ratios_cpu)
        
        # 计算最终爆发度（CPU部分）
        word_metrics = {}
        for i, word in enumerate(valid_words):
            word_metrics[word] = {
                'max_growth_rate': float(max_growth_rates_cpu[i]),
                'cv': float(cvs_cpu[i]),
                'recent_early_ratio': float(recent_early_ratios_cpu[i]),
                'peak_freq': int(peak_freqs_cpu[i])
            }
        
        # 拐点检测和最终分数计算
        for i, word in enumerate(valid_words):
            year_counts = self.word_year_counts[word]
            years = sorted(year_counts.keys())
            
            # 拐点检测
            turning_point_year = None
            turning_point_score = 0
            for j in range(1, len(years)):
                prev_freq = year_counts[years[j-1]]
                curr_freq = year_counts[years[j]]
                if (curr_freq >= prev_freq * self.turning_point_growth_factor and 
                    curr_freq >= self.turning_point_min_freq):
                    turning_point_year = years[j]
                    turning_point_score = 1
                    break
            
            # 加权计算原始爆发度
            raw_burst_score = (
                0.4 * norm_max_growth[i] +
                0.3 * norm_cvs[i] +
                0.2 * norm_ratios[i] +
                0.1 * turning_point_score
            )
            
            # 频率权重
            peak_freq = word_metrics[word]['peak_freq']
            freq_weight = math.log(1 + peak_freq)
            normalized_freq_weight = min(freq_weight / math.log(10000), 2.0)
            
            # 最终爆发度
            final_burst_score = raw_burst_score * normalized_freq_weight
            
            self.word_burst_scores[word] = final_burst_score
            self.word_burst_details[word] = {
                'max_growth_rate': word_metrics[word]['max_growth_rate'],
                'cv': word_metrics[word]['cv'],
                'recent_early_ratio': word_metrics[word]['recent_early_ratio'],
                'peak_freq': peak_freq,
                'turning_point_year': turning_point_year,
                'raw_burst_score': raw_burst_score,
                'freq_weight': normalized_freq_weight
            }
        
        # 对不符合条件的词汇设置默认值
        for word in self.first_occurrence_log.keys():
            if word not in self.word_burst_scores:
                self.word_burst_scores[word] = 0
                self.word_burst_details[word] = {}
        
        print(f"✅ GPU爆发度计算完成！共计算 {len(valid_words):,} 个词汇")
    
    def _calculate_innovation_burst_score_cpu(self):
        """CPU版本的爆发度计算（后备方案）"""
        print("使用CPU计算爆发度...")
        
        # 第一步：计算所有词汇的原始指标（使用字典避免索引错位）
        word_metrics = {}
        
        for word in self.first_occurrence_log.keys():
            year_counts = self.word_year_counts.get(word, {})
            if not year_counts:
                continue
            
            years = sorted(year_counts.keys())
            if len(years) < self.min_years_span:
                continue
            
            # 指标1：最大年度增长率（拉普拉斯平滑）
            max_growth_rate = 0
            for i in range(1, len(years)):
                prev_freq = year_counts[years[i-1]]
                curr_freq = year_counts[years[i]]
                growth_rate = (curr_freq + 1) / (prev_freq + 1) - 1
                max_growth_rate = max(max_growth_rate, growth_rate)
            
            # 指标2：变异系数
            freq_values = [year_counts[y] for y in years]
            mean_freq = sum(freq_values) / len(freq_values)
            if mean_freq > 0:
                variance = sum((f - mean_freq) ** 2 for f in freq_values) / len(freq_values)
                std_freq = variance ** 0.5
                cv = std_freq / mean_freq
            else:
                cv = 0
            
            # 指标3：近期/早期比值（动态窗口+排除不完整年份）
            if self.recent_early_split_year:
                # 手动指定分界点
                split_year = self.recent_early_split_year
                usable_years = years
            else:
                # 自动排除最后N年不完整数据
                if self.exclude_last_n_years > 0 and len(years) > self.exclude_last_n_years:
                    usable_years = years[:-self.exclude_last_n_years]
                else:
                    usable_years = years
                
                if not usable_years:
                    usable_years = years
                
                max_usable_year = max(usable_years)
                split_year = max_usable_year - self.recent_window_years
            
            early_years = [y for y in usable_years if y <= split_year]
            recent_years = [y for y in usable_years if y > split_year]
            
            early_mean = sum(year_counts[y] for y in early_years) / len(early_years) if early_years else 0
            recent_mean = sum(year_counts[y] for y in recent_years) / len(recent_years) if recent_years else 0
            
            recent_early_ratio = (recent_mean + 1) / (early_mean + 1)
            
            # 峰值频率
            peak_freq = max(freq_values)
            
            # 存储该词的所有指标
            word_metrics[word] = {
                'max_growth_rate': max_growth_rate,
                'cv': cv,
                'recent_early_ratio': recent_early_ratio,
                'peak_freq': peak_freq
            }
        
        # 第二步：归一化（从字典中提取值）
        if not word_metrics:
            print("⚠️  警告：没有符合条件的词汇用于计算爆发度")
            return
        
        max_growth_rates = [m['max_growth_rate'] for m in word_metrics.values()]
        cvs = [m['cv'] for m in word_metrics.values()]
        recent_early_ratios = [m['recent_early_ratio'] for m in word_metrics.values()]
        
        def normalize(values):
            if not values or min(values) == max(values):
                return {word: 0.5 for word in word_metrics.keys()}
            min_val, max_val = min(values), max(values)
            result = {}
            for word, val in zip(word_metrics.keys(), values):
                result[word] = (val - min_val) / (max_val - min_val)
            return result
        
        norm_max_growth = normalize(max_growth_rates)
        norm_cvs = normalize(cvs)
        norm_ratios = normalize(recent_early_ratios)
        
        # 第三步：计算最终爆发度分数
        for word in self.first_occurrence_log.keys():
            if word not in word_metrics:
                self.word_burst_scores[word] = 0
                self.word_burst_details[word] = {}
                continue
            
            year_counts = self.word_year_counts.get(word, {})
            years = sorted(year_counts.keys())
            
            # 指标4：拐点检测
            turning_point_year = None
            turning_point_score = 0
            for i in range(1, len(years)):
                prev_freq = year_counts[years[i-1]]
                curr_freq = year_counts[years[i]]
                if (curr_freq >= prev_freq * self.turning_point_growth_factor and 
                    curr_freq >= self.turning_point_min_freq):
                    turning_point_year = years[i]
                    turning_point_score = 1
                    break
            
            # 加权计算原始爆发度
            raw_burst_score = (
                0.4 * norm_max_growth[word] +
                0.3 * norm_cvs[word] +
                0.2 * norm_ratios[word] +
                0.1 * turning_point_score
            )
            
            # 应用基础频率权重（对数阻尼）
            peak_freq = word_metrics[word]['peak_freq']
            freq_weight = math.log(1 + peak_freq)
            normalized_freq_weight = min(freq_weight / math.log(10000), 2.0)
            
            # 最终爆发度
            final_burst_score = raw_burst_score * normalized_freq_weight
            
            self.word_burst_scores[word] = final_burst_score
            self.word_burst_details[word] = {
                'max_growth_rate': word_metrics[word]['max_growth_rate'],
                'cv': word_metrics[word]['cv'],
                'recent_early_ratio': word_metrics[word]['recent_early_ratio'],
                'peak_freq': peak_freq,
                'turning_point_year': turning_point_year,
                'raw_burst_score': raw_burst_score,
                'freq_weight': normalized_freq_weight
            }
        
        print(f"✅ 创新爆发度计算完成！共计算 {len(word_metrics)} 个词汇")
    
    def _validate_config(self):
        """验证配置参数"""
        if not self.time_columns:
            raise ValueError("时间列列表不能为空")
        
        if not self.info_columns:
            raise ValueError("信息列列表不能为空")
            
        if self.min_occurrence < 1:
            raise ValueError("min_occurrence必须大于等于1")
            
        if self.progress_interval < 1:
            raise ValueError("progress_interval必须大于等于1")
        
        # 检查jieba依赖
        if self.language in ['zh', 'mixed'] and not JIEBA_AVAILABLE:
            print("⚠️  警告：未安装jieba库，中文分词将退化为基于空格的切分")
            print("   建议运行：pip install jieba")
            
        # 检查进度条依赖
        if not TQDM_AVAILABLE and self.show_progress:
            print("💡 提示：未安装tqdm库，无法显示进度条")
            print("   建议运行：pip install tqdm")
            self.show_progress = False
        
        # 确定分析内容
        if self.analysis_mode == 'info_columns':
            analysis_content = f"信息列合并内容：{' + '.join(self.info_columns)}"
        else:
            analysis_content = f"文本列内容：{self.text_column}"
        
        # 检查列名重复
        all_columns = self.time_columns + self.info_columns + [self.unique_id_column]
        if self.text_column:
            all_columns.append(self.text_column)
        
        if len(set(all_columns)) != len(all_columns):
            raise ValueError("列名配置中存在重复")
        
        print("✅ 配置验证通过")
        print(f"   分析内容：{analysis_content}")
        print(f"   排序优先级：{' > '.join(self.time_columns)}")
        print(f"   语言设置：{self.language}")
        print(f"   停用词表：{len(self.stopword_files)}个文件（共{len(self.stop_words):,}个停用词）")
        print(f"   最小出现频率：{self.min_occurrence}")
        print(f"   进度显示：{'启用' if self.show_progress else f'禁用（每{self.progress_interval}条显示）'}")
        
    def _load_stopwords_from_file(self, file_path):
        """从文本文件加载停用词集合。每行一个词，支持#或//开头的注释。"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"停用词文件不存在：{file_path}")
        
        loaded_words = set()
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                token = line.strip()
                if not token or token.startswith('#') or token.startswith('//'):
                    continue
                # 英文统一小写，中文保持原样
                if re.match(r'^[A-Za-z\-]+$', token):
                    loaded_words.add(token.lower())
                else:
                    loaded_words.add(token)
        return loaded_words

    def _get_stop_words(self):
        """加载并合并所有停用词文件，自动去重"""
        all_stopwords = set()
        for file_path in self.stopword_files:
            all_stopwords.update(self._load_stopwords_from_file(file_path))
        return all_stopwords
    
    def validate_sorted_data(self):
        """验证已排序的中间文件（仅读取前100行进行轻量级验证）"""
        sorted_file_path = self.csv_file_path + '.sorted_temp.csv'
        
        print("正在验证已排序的中间文件...")
        
        if not os.path.exists(sorted_file_path):
            print(f"❌ 错误：中间文件不存在：{sorted_file_path}")
            print(f"💡 请先运行 '数据预处理排序.py' 生成中间文件")
            return False
        
        try:
            # 仅读取前100行验证列名和数据有效性
            sample_df = pd.read_csv(sorted_file_path, nrows=100)
            
            required_columns = self.time_columns + self.info_columns + [self.unique_id_column]
            if self.text_column and self.analysis_mode == 'text_column':
                required_columns.append(self.text_column)
                
            missing_columns = [col for col in required_columns if col not in sample_df.columns]
            if missing_columns:
                print(f"❌ 错误：中间文件缺少必要的列：{missing_columns}")
                return False
            
            # 保存列名供后续使用
            self.header = sample_df.columns.tolist()
            
            # 验证时间列数据范围
            for col in self.time_columns:
                try:
                    col_values = pd.to_numeric(sample_df[col], errors='coerce').dropna()
                    if len(col_values) > 0:
                        col_min = col_values.min()
                        col_max = col_values.max()
                        if pd.notna(col_min) and pd.notna(col_max):
                            if col_min == col_max:
                                print(f"   {col}：{int(col_min)}")
                            else:
                                print(f"   {col}：{int(col_min)} - {int(col_max)} (采样验证)")
                except Exception:
                    pass
            
            print(f"✅ 中间文件验证成功，列结构正确")
            return True
            
        except FileNotFoundError:
            print(f"❌ 错误：中间文件 '{sorted_file_path}' 不存在")
            print(f"💡 请先运行 '数据预处理排序.py' 生成中间文件")
            return False
        except Exception as e:
            print(f"❌ 数据验证错误：{e}")
            return False
    
    def create_analysis_text(self, row_dict):
        """创建分析文本"""
        if self.analysis_mode == 'info_columns':
            return row_dict.get('combined_info', '')
        else:
            value = row_dict.get(self.text_column)
            return str(value) if pd.notna(value) else ''
    
    def _gpu_batch_pos_filter_main(self, all_words, batch_size=500):
        """主进程GPU批量词性过滤（内存优化版）
        
        Args:
            all_words: 所有待过滤的词汇列表
            batch_size: GPU批处理大小（降低至500避免内存溢出）
        
        Returns:
            过滤后的词汇集合
        """
        if not all_words or not self.nlp:
            return set(all_words)
        
        valid_pos = {'NOUN', 'PROPN', 'ADJ', 'NUM', 'X'}
        filtered_words_set = set()
        
        total_batches = (len(all_words) + batch_size - 1) // batch_size
        print(f"   分{total_batches}批处理，每批{batch_size}个词汇")
        
        if TQDM_AVAILABLE:
            from tqdm import tqdm
            batch_iterator = tqdm(range(0, len(all_words), batch_size), 
                                 desc="GPU词性过滤", total=total_batches)
        else:
            batch_iterator = range(0, len(all_words), batch_size)
        
        for batch_idx, start_idx in enumerate(batch_iterator):
            end_idx = min(start_idx + batch_size, len(all_words))
            batch_words = all_words[start_idx:end_idx]
            
            batch_text = ' '.join(batch_words)
            
            try:
                doc = self.nlp(batch_text)
                
                batch_words_set = set(batch_words)
                for token in doc:
                    if token.pos_ in valid_pos and token.text in batch_words_set:
                        filtered_words_set.add(token.text)
                
                if (batch_idx + 1) % 10 == 0:
                    gc.collect()
                    
            except Exception as e:
                print(f"\n⚠️  批次{batch_idx}处理失败：{e}，跳过该批次")
                continue
        
        gc.collect()
        return filtered_words_set
    
    def _filter_by_pos(self, words):
        """词性过滤，仅保留名词、形容词等（已废弃，保留用于向后兼容）"""
        if not self.use_pos_filter or not self.nlp or not words:
            return words
        
        filtered_words = []
        text = ' '.join(words)
        doc = self.nlp(text)
        
        valid_pos = {'NOUN', 'PROPN', 'ADJ', 'NUM', 'X'}
        
        for token in doc:
            if token.pos_ in valid_pos and token.text in words:
                filtered_words.append(token.text)
        
        return filtered_words
    
    def _extract_ngrams(self, words):
        """提取N-gram短语"""
        if not self.extract_ngrams or len(words) < self.ngram_range[0]:
            return []
        
        ngrams = []
        for n in range(self.ngram_range[0], self.ngram_range[1] + 1):
            for i in range(len(words) - n + 1):
                ngram = '_'.join(words[i:i+n])
                ngrams.append(ngram)
        
        return ngrams
    
    def _process_chunk(self, chunk_df):
        """处理单个数据块"""
        local_freq = Counter()
        local_doc_freq = Counter()
        local_year_counts = defaultdict(lambda: defaultdict(int))
        local_first_occurrence = {}
        local_doc_count = 0
        
        # 对象缓存
        first_log = self.first_occurrence_log
        
        iterator = chunk_df.itertuples(index=False, name='Record')
        if self.show_progress:
            iterator = tqdm(iterator, total=len(chunk_df), desc="处理chunk", leave=False)
        
        for row in iterator:
            row_dict = row._asdict()
            
            analysis_text = self.create_analysis_text(row_dict)
            words = self.preprocess_text(analysis_text)
            
            if not words:
                continue
            
            local_doc_count += 1
            unique_words = set(words)
            
            # 统计频率
            for word in words:
                local_freq[word] += 1
            
            # 文档频率
            for word in unique_words:
                local_doc_freq[word] += 1
            
            # 年度计数
            primary_year = row_dict.get(self.time_columns[0])
            year_val = int(primary_year) if pd.notna(primary_year) else None
            if year_val is not None:
                for word in words:
                    local_year_counts[word][year_val] += 1
            
            # 首次出现记录
            new_words = [w for w in words if w not in first_log and w not in local_first_occurrence]
            if new_words:
                # 仅保存CSV导出需要的字段：unique_id, time_columns, analysis_text（移除info_columns以减少85%存储）
                paper_info = {
                    self.unique_id_column: str(row_dict[self.unique_id_column])
                }
                for col in self.time_columns:
                    value = row_dict[col]
                    paper_info[col] = int(value) if pd.notna(value) else 0
                
                for word in new_words:
                    paper_info_copy = paper_info.copy()
                    paper_info_copy['analysis_text'] = self._extract_snippet_with_keyword(analysis_text, word, max_len=30)
                    local_first_occurrence[word] = paper_info_copy
        
        return local_freq, local_doc_freq, local_year_counts, local_first_occurrence, local_doc_count
    
    def preprocess_text(self, text):
        """文本预处理"""
        if pd.isna(text) or not isinstance(text, str) or not text.strip():
            return []
        
        # 混合模式额外检查
        if self.language in ['zh', 'mixed'] and not re.search(r'[\u4e00-\u9fffA-Za-z]', text):
            return []
        
        # 转换为小写
        text = text.lower()
        
        # 修复单词粘连问题
        text = self.word_concat_pattern.sub(r'\1 \2\3', text)
        
        if self.analysis_mode == 'info_columns':
            # 使用预编译正则
            text = self.punctuation_pattern1.sub(' ', text)
            text = self.punctuation_pattern2.sub(' ', text)
            text = self.punctuation_pattern3.sub(' ', text)
            text = self.punctuation_pattern4.sub(' ', text)
            text = self.hyphen_pattern.sub(' ', text)
        
        # 分词策略
        words = []
        if self.language == 'zh' and JIEBA_AVAILABLE:
            words = list(jieba.cut(text))
        elif self.language == 'en':
            words = self.word_pattern.findall(text)
        elif self.language == 'mixed':
            english_words = self.word_pattern.findall(text)
            if JIEBA_AVAILABLE:
                chinese_text = re.sub(r'[a-zA-Z\s\-]+', ' ', text)
                chinese_words = [w for w in jieba.cut(chinese_text) if re.match(r'[\u4e00-\u9fff]+', w)]
                words = english_words + chinese_words
            else:
                words = english_words
        else:
            words = text.split()
        
        processed_words = []
        for word in words:
            # 清理
            if self.language == 'en':
                clean_word = re.sub(r'[^a-zA-Z\-]', '', word).strip('-')
            elif self.language == 'zh':
                clean_word = re.sub(r'[^\u4e00-\u9fff]', '', word)
            else:  # mixed
                if re.match(r'^[a-zA-Z\-]+$', word):
                    clean_word = re.sub(r'[^a-zA-Z\-]', '', word).strip('-')
                else:
                    clean_word = re.sub(r'[^\u4e00-\u9fff]', '', word)
            
            # 验证有效性
            if (len(clean_word) >= self.min_word_length and 
                clean_word not in self.stop_words and
                clean_word.strip() and
                not clean_word.isdigit() and
                clean_word != '-'):
                processed_words.append(clean_word)
        
        # 词性过滤
        processed_words = self._filter_by_pos(processed_words)
        
        # 提取N-gram
        ngrams = self._extract_ngrams(processed_words)
        
        # 合并单词和N-gram
        all_terms = processed_words + ngrams
        
        return all_terms
    
    def _extract_snippet_with_keyword(self, text, keyword, max_len=30):
        """从文本中提取包含关键字的句子片段，长度不超过 max_len。找不到则回退到前 max_len 字符。"""
        if not text or not keyword:
            return text[:max_len] + '...' if text and len(text) > max_len else (text or '')

        text_lower = text.lower()
        pos = text_lower.find(keyword.lower())
        if pos == -1:
            return text[:max_len] + '...' if len(text) > max_len else text

        # 寻找句子边界
        delimiters = '.!?;。！？；\n\r'
        start = pos
        while start > 0 and text[start - 1] not in delimiters:
            start -= 1
        end = pos
        n = len(text)
        while end < n and text[end] not in delimiters:
            end += 1

        sentence = text[start:end].strip()
        if len(sentence) <= max_len:
            return sentence

        # 超长时围绕关键字截取窗口
        # 计算关键字在句子中的相对位置
        rel_pos = pos - start
        half = max_len // 2
        # 优先保证关键字出现在片段中间附近
        window_start = max(0, rel_pos - half)
        window_end = window_start + max_len
        if window_end > len(sentence):
            window_end = len(sentence)
            window_start = max(0, window_end - max_len)

        snippet = sentence[window_start:window_end].strip()
        # 添加省略号标记截断
        prefix = '...' if window_start > 0 else ''
        suffix = '...' if window_end < len(sentence) else ''
        return f"{prefix}{snippet}{suffix}"

    def _save_checkpoint(self, checkpoint_dir, stage, batch_idx, data_dict):
        """保存合并进度checkpoint"""
        os.makedirs(checkpoint_dir, exist_ok=True)
        progress_file = os.path.join(checkpoint_dir, 'progress.json')
        
        # 保存进度信息
        progress = {stage: batch_idx}
        if os.path.exists(progress_file):
            with open(progress_file, 'r', encoding='utf-8') as f:
                existing = json.load(f)
            existing.update(progress)
            progress = existing
        
        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump(progress, f)
        
        # 保存数据
        for key, value in data_dict.items():
            pkl_file = os.path.join(checkpoint_dir, f'{key}.pkl')
            with open(pkl_file, 'wb') as f:
                pickle.dump(value, f)

    def _load_checkpoint(self, checkpoint_dir, stage):
        """加载checkpoint，返回(已处理批次数, 已加载数据字典)"""
        progress_file = os.path.join(checkpoint_dir, 'progress.json')
        if not os.path.exists(progress_file):
            return 0, {}
        
        with open(progress_file, 'r', encoding='utf-8') as f:
            progress = json.load(f)
        
        batch_idx = progress.get(stage, 0)
        if batch_idx == 0:
            return 0, {}
        
        # 加载数据
        data_dict = {}
        for pkl_name in ['word_freq', 'word_doc_freq', 'word_year', 'first_log']:
            pkl_file = os.path.join(checkpoint_dir, f'{pkl_name}.pkl')
            if os.path.exists(pkl_file):
                with open(pkl_file, 'rb') as f:
                    data_dict[pkl_name] = pickle.load(f)
        
        return batch_idx, data_dict

    def analyze_first_occurrences(self, total_rows):
        """执行分析（多进程加速版 - 直接读取CSV行范围）
        
        Args:
            total_rows: 数据总行数（显式传入，避免全量加载数据）
        """
        analysis_content = "信息列合并内容" if self.analysis_mode == 'info_columns' else f"文本列({self.text_column})"
        print(f"开始分析{analysis_content}中的词汇首次出现...")
        
        if not hasattr(self, 'header') or not self.header:
            print("❌ 错误：请先验证数据文件")
            return False
        
        # 记录开始时间
        self.start_time = time.time()
        
        total_papers = total_rows
        
        # 准备配置字典（词性过滤将在主进程中统一执行）
        config = {
            'stop_words': self.stop_words,
            'min_word_length': self.min_word_length,
            'language': self.language,
            'analysis_mode': self.analysis_mode,
            'time_columns': self.time_columns,
            'info_columns': self.info_columns,
            'text_column': self.text_column,
            'unique_id_column': self.unique_id_column,
            'use_pos_filter': False,  # 子进程不执行词性过滤
            'extract_ngrams': self.extract_ngrams,
            'ngram_range': self.ngram_range
        }
        
        # 使用已存在的中间文件
        temp_file_path = self.csv_file_path + '.sorted_temp.csv'
        print(f"📝 使用中间文件进行多进程处理...")
        print(f"   数据规模：{total_papers:,} 行 × {len(self.header)} 列")
        
        # 分块处理（内存优化：降低chunk_size避免峰值）
        chunk_size = 10000
        total_chunks = (total_papers + chunk_size - 1) // chunk_size
        
        # 检查断点续传
        temp_dir = './temp'
        os.makedirs(temp_dir, exist_ok=True)
        existing_chunks = set()
        if os.path.exists(temp_dir):
            for filename in os.listdir(temp_dir):
                if filename.startswith('chunk_') and ('_counts.parquet' in filename or '_counts.csv' in filename):
                    chunk_id = int(filename.split('_')[1])
                    existing_chunks.add(chunk_id)
        
        # 准备所有chunk参数（只传行号范围，不传数据）
        chunk_args = []
        chunk_id = 0
        for start_idx in range(0, total_papers, chunk_size):
            end_idx = min(start_idx + chunk_size, total_papers)
            if chunk_id not in existing_chunks:
                chunk_args.append((chunk_id, temp_file_path, start_idx, end_idx, self.header, config))
            chunk_id += 1
        
        # 多进程处理（降低并发减少内存峰值）
        num_processes = 6
        if existing_chunks:
            print(f"🔄 检测到 {len(existing_chunks)} 个已完成的数据块，继续处理剩余 {len(chunk_args)} 个...")
        print(f"🚀 启动多进程处理（{num_processes}个进程，{len(chunk_args)}个待处理块 / 总共{total_chunks}块）...")
        print(f"   内存优化：chunk_size={chunk_size:,}行，进程数={num_processes}")
        
        if chunk_args:
            # 分批启动多进程任务，避免队列累积
            process_batch_size = num_processes * 3
            total_batches = (len(chunk_args) + process_batch_size - 1) // process_batch_size
            
            if self.show_progress:
                pbar = tqdm(total=len(chunk_args), desc="并行处理")
            
            chunk_doc_counts = {}  # 存储每个chunk的文档数
            for batch_idx in range(total_batches):
                batch_start = batch_idx * process_batch_size
                batch_end = min(batch_start + process_batch_size, len(chunk_args))
                batch_chunk_args = chunk_args[batch_start:batch_end]
                
                with Pool(processes=num_processes) as pool:
                    for result in pool.imap(_process_chunk_worker, batch_chunk_args):
                        if result:  # result = (chunk_id, local_doc_count)
                            chunk_id, doc_count = result
                            chunk_doc_counts[chunk_id] = doc_count
                        if self.show_progress:
                            pbar.update(1)
                # 每批完成后清理
                gc.collect()
            
            if self.show_progress:
                pbar.close()
            
            # 存储文档计数，供后续合并使用
            self._chunk_doc_counts = chunk_doc_counts
        else:
            print("✅ 所有数据块已处理完毕，跳过多进程处理")
            self._chunk_doc_counts = {}
        
        print(f"✅ 多进程处理完成，开始合并结果...")
        
        # 获取所有chunk ID（从counts文件）
        all_files = os.listdir(temp_dir)
        chunk_ids = sorted(set([
            int(f.split('_')[1]) for f in all_files 
            if f.startswith('chunk_') and ('_counts.parquet' in f or '_counts.csv' in f)
        ]))
        
        if not chunk_ids:
            print("⚠️  未找到任何chunk文件，跳过合并")
            return
        
        # 判断文件格式
        sample_file = f'chunk_{chunk_ids[0]}_counts'
        if os.path.exists(os.path.join(temp_dir, f'{sample_file}.parquet')):
            file_ext = 'parquet'
            read_func = pd.read_parquet
        else:
            file_ext = 'csv'
            read_func = pd.read_csv
        
        print(f"📊 开始合并 {len(chunk_ids)} 个chunk（格式：{file_ext.upper()}）...")
        
        # 1. 合并词频与文档频次（批量读取+groupby聚合）
        batch_size = 10
        checkpoint_dir = os.path.join(temp_dir, 'merge_checkpoint')
        checkpoint_interval = 10
        
        # 加载checkpoint
        start_batch, checkpoint_data = self._load_checkpoint(checkpoint_dir, 'word_freq')
        word_freq = checkpoint_data.get('word_freq', Counter())
        word_doc_freq = checkpoint_data.get('word_doc_freq', Counter())
        
        if start_batch > 0:
            print(f"📂 检测到checkpoint，从第{start_batch}批继续（共{(len(chunk_ids) + batch_size - 1) // batch_size}批）")
        
        if self.show_progress:
            print("📈 合并词频统计...")
            batch_iter = tqdm(range(start_batch * batch_size, len(chunk_ids), batch_size), 
                              desc="词频聚合", mininterval=0.5)
        else:
            batch_iter = range(start_batch * batch_size, len(chunk_ids), batch_size)
        
        for batch_start in batch_iter:
            batch_end = min(batch_start + batch_size, len(chunk_ids))
            batch_ids = chunk_ids[batch_start:batch_end]
            
            counts_dfs = []
            for cid in batch_ids:
                fpath = os.path.join(temp_dir, f'chunk_{cid}_counts.{file_ext}')
                if os.path.exists(fpath):
                    counts_dfs.append(read_func(fpath))
            
            if counts_dfs:
                merged = pd.concat(counts_dfs, ignore_index=True)
                aggregated = merged.groupby('word', as_index=False).sum()
                
                # 高效转换（避免iterrows）
                word_counts = dict(zip(aggregated['word'], aggregated['token_count']))
                doc_counts = dict(zip(aggregated['word'], aggregated['doc_count']))
                
                for word, count in word_counts.items():
                    word_freq[word] += int(count)
                for word, count in doc_counts.items():
                    word_doc_freq[word] += int(count)
                
                del counts_dfs, merged, aggregated, word_counts, doc_counts
                gc.collect()
            
            # 定期保存checkpoint
            current_batch = batch_start // batch_size + 1
            if current_batch % checkpoint_interval == 0:
                self._save_checkpoint(checkpoint_dir, 'word_freq', current_batch, {
                    'word_freq': word_freq,
                    'word_doc_freq': word_doc_freq
                })
        
        self.word_frequencies = word_freq
        self.word_document_frequency = word_doc_freq
        
        # 2. 合并年份统计（批量读取+groupby聚合）
        # 加载checkpoint
        start_batch, checkpoint_data = self._load_checkpoint(checkpoint_dir, 'year')
        if checkpoint_data.get('word_year'):
            word_year = checkpoint_data['word_year']
        else:
            word_year = defaultdict(lambda: defaultdict(int))
        
        if start_batch > 0:
            print(f"📂 检测到checkpoint，从第{start_batch}批继续")
        
        if self.show_progress:
            print("📈 合并年份统计...")
            batch_iter = tqdm(range(start_batch * batch_size, len(chunk_ids), batch_size), 
                              desc="年份聚合", mininterval=0.5)
        else:
            batch_iter = range(start_batch * batch_size, len(chunk_ids), batch_size)
        
        for batch_start in batch_iter:
            batch_end = min(batch_start + batch_size, len(chunk_ids))
            batch_ids = chunk_ids[batch_start:batch_end]
            
            year_dfs = []
            for cid in batch_ids:
                fpath = os.path.join(temp_dir, f'chunk_{cid}_year.{file_ext}')
                if os.path.exists(fpath):
                    year_dfs.append(read_func(fpath))
            
            if year_dfs:
                merged = pd.concat(year_dfs, ignore_index=True)
                aggregated = merged.groupby(['word', 'year'], as_index=False).sum()
                
                for _, row in aggregated.iterrows():
                    word_year[row['word']][int(row['year'])] += int(row['count'])
                
                del year_dfs, merged, aggregated
                gc.collect()
            
            # 定期保存checkpoint
            current_batch = batch_start // batch_size + 1
            if current_batch % checkpoint_interval == 0:
                self._save_checkpoint(checkpoint_dir, 'year', current_batch, {
                    'word_year': word_year
                })
        
        self.word_year_counts = word_year
        
        # 3. 合并首次出现记录（阶段级checkpoint）
        checkpoint_file = os.path.join(checkpoint_dir, 'stage_first.done')
        if os.path.exists(checkpoint_file):
            print("📂 检测到首次记录已完成，跳过")
            with open(os.path.join(checkpoint_dir, 'first_log.pkl'), 'rb') as f:
                first_log = pickle.load(f)
        else:
            first_log = {}
            
            if self.show_progress:
                print("📈 合并首次出现记录...")
                chunk_iter = tqdm(chunk_ids, desc="首次记录", mininterval=0.5)
            else:
                chunk_iter = chunk_ids
            
            for cid in chunk_iter:
                fpath = os.path.join(temp_dir, f'chunk_{cid}_first.{file_ext}')
                if os.path.exists(fpath):
                    first_df = read_func(fpath)
                    for _, row in first_df.iterrows():
                        word = row['word']
                        if word not in first_log:
                            info = row.drop('word').to_dict()
                            first_log[word] = info
                    del first_df
            
            # 保存阶段完成标记
            with open(checkpoint_file, 'w') as f:
                f.write('done')
            with open(os.path.join(checkpoint_dir, 'first_log.pkl'), 'wb') as f:
                pickle.dump(first_log, f)
        
        self.first_occurrence_log = first_log
        
        # 4. 从chunk_doc_counts字典获取文档计数（无需读取meta文件，节省2247次I/O）
        if hasattr(self, '_chunk_doc_counts') and self._chunk_doc_counts:
            total_docs = sum(self._chunk_doc_counts.values())
        else:
            # 兼容性：如果没有_chunk_doc_counts，从first_occurrence_log推导（阶段2加载）
            total_docs = len(set(info.get(self.unique_id_column, '') for info in self.first_occurrence_log.values()))
            if total_docs == 0:
                total_docs = self.total_documents  # 使用已加载的值
        
        self.total_documents = total_docs
        
        elapsed = time.time() - self.start_time
        print(f"✅ 结果合并完成！处理了 {total_papers:,} 篇记录，耗时 {elapsed:.2f}秒，速度 {total_papers/elapsed:.0f}条/秒")
        print(f"📁 临时文件：{len(chunk_ids)} 个chunk（共{len(chunk_ids)*3}个文件）保存在 {temp_dir} 文件夹")
        
        # 完成后提示清理checkpoint
        if os.path.exists(checkpoint_dir):
            checkpoint_size = sum(os.path.getsize(os.path.join(checkpoint_dir, f)) 
                                 for f in os.listdir(checkpoint_dir) if os.path.isfile(os.path.join(checkpoint_dir, f)))
            print(f"💾 Checkpoint文件夹占用 {checkpoint_size/1024/1024:.1f}MB，可手动删除：{checkpoint_dir}")
        
        gc.collect()
        self._print_memory_usage()
        
        # 主进程统一词性过滤（GPU批量处理）
        if self.use_pos_filter and self.nlp:
            print("🚀 主进程开始GPU批量词性过滤...")
            original_word_count = len(first_log)
            
            # 收集所有词汇进行批量过滤
            all_words = list(first_log.keys())
            filtered_words = self._gpu_batch_pos_filter_main(all_words)
            
            # 根据过滤结果重建所有统计数据
            word_freq = Counter({w: word_freq[w] for w in filtered_words if w in word_freq})
            word_doc_freq = Counter({w: word_doc_freq[w] for w in filtered_words if w in word_doc_freq})
            word_year = defaultdict(lambda: defaultdict(int), {
                w: word_year[w] for w in filtered_words if w in word_year
            })
            first_log = {w: first_log[w] for w in filtered_words if w in first_log}
            
            # 更新实例变量
            self.word_frequencies = word_freq
            self.word_document_frequency = word_doc_freq
            self.word_year_counts = word_year
            self.first_occurrence_log = first_log
            
            filtered_word_count = len(first_log)
            print(f"✅ GPU词性过滤完成：{original_word_count:,} -> {filtered_word_count:,} 个词汇（仅保留名词/形容词）")
        
        # 应用最小出现频率过滤并同步清理
        if self.min_occurrence > 1:
            original_count = len(self.first_occurrence_log)
            filtered_log = {word: info for word, info in self.first_occurrence_log.items() 
                          if self.word_frequencies[word] >= self.min_occurrence}
            
            self.word_frequencies = Counter({word: count for word, count in self.word_frequencies.items() 
                                           if word in filtered_log})
            
            self.word_document_frequency = Counter({word: count for word, count in self.word_document_frequency.items() 
                                                   if word in filtered_log})
            
            self.word_year_counts = defaultdict(lambda: defaultdict(int), {
                word: counts for word, counts in self.word_year_counts.items() if word in filtered_log
            })
            
            self.first_occurrence_log = filtered_log
            filtered_count = len(self.first_occurrence_log)
            print(f"🔍 应用最小出现频率过滤 (>={self.min_occurrence}次)：{original_count:,} -> {filtered_count:,} 个词汇")
        
        # 停用词二次过滤
        original_count_before_stopwords = len(self.first_occurrence_log)
        filtered_log = {word: info for word, info in self.first_occurrence_log.items() 
                       if word not in self.stop_words}
        
        self.word_frequencies = Counter({word: count for word, count in self.word_frequencies.items() 
                                       if word in filtered_log})
        
        self.word_document_frequency = Counter({word: count for word, count in self.word_document_frequency.items() 
                                               if word in filtered_log})
        
        self.word_year_counts = defaultdict(lambda: defaultdict(int), {
            word: counts for word, counts in self.word_year_counts.items() if word in filtered_log
        })
        
        self.first_occurrence_log = filtered_log
        stopwords_filtered_count = len(self.first_occurrence_log)
        if stopwords_filtered_count != original_count_before_stopwords:
            print(f"🚫 停用词二次过滤：{original_count_before_stopwords:,} -> {stopwords_filtered_count:,} 个词汇")
        
        # 文档频率上限过滤
        if self.doc_freq_threshold < 1.0:
            original_count_before_docfreq = len(self.first_occurrence_log)
            filtered_log = {word: info for word, info in self.first_occurrence_log.items() 
                           if self.word_document_frequency.get(word, 0) / self.total_documents <= self.doc_freq_threshold}
            
            self.word_frequencies = Counter({word: count for word, count in self.word_frequencies.items() 
                                           if word in filtered_log})
            
            self.word_document_frequency = Counter({word: count for word, count in self.word_document_frequency.items() 
                                                   if word in filtered_log})
            
            self.word_year_counts = defaultdict(lambda: defaultdict(int), {
                word: counts for word, counts in self.word_year_counts.items() if word in filtered_log
            })
            
            self.first_occurrence_log = filtered_log
            docfreq_filtered_count = len(self.first_occurrence_log)
            if docfreq_filtered_count != original_count_before_docfreq:
                print(f"🚫 超高频词过滤 (DF>{self.doc_freq_threshold*100:.0f}%)：{original_count_before_docfreq:,} -> {docfreq_filtered_count:,} 个词汇")
        
        # 计算TF-IDF分数
        if self.use_tfidf:
            print("📊 计算TF-IDF分数...")
            self._calculate_tfidf()
            print(f"✅ TF-IDF计算完成！")
        
        # 计算创新爆发度分数
        if self.use_burst_filter:
            self._calculate_innovation_burst_score()
            
            # 应用爆发度阈值过滤
            original_count_before_burst = len(self.first_occurrence_log)
            filtered_log = {word: info for word, info in self.first_occurrence_log.items() 
                           if self.word_burst_scores.get(word, 0) >= self.innovation_burst_threshold}
            
            self.word_frequencies = Counter({word: count for word, count in self.word_frequencies.items() 
                                           if word in filtered_log})
            
            self.word_document_frequency = Counter({word: count for word, count in self.word_document_frequency.items() 
                                                   if word in filtered_log})
            
            self.word_year_counts = defaultdict(lambda: defaultdict(int), {
                word: counts for word, counts in self.word_year_counts.items() if word in filtered_log
            })
            
            if self.use_tfidf:
                self.word_tfidf_scores = {word: score for word, score in self.word_tfidf_scores.items() 
                                         if word in filtered_log}
            
            self.word_burst_scores = {word: score for word, score in self.word_burst_scores.items() 
                                     if word in filtered_log}
            
            self.word_burst_details = {word: details for word, details in self.word_burst_details.items() 
                                      if word in filtered_log}
            
            self.first_occurrence_log = filtered_log
            burst_filtered_count = len(self.first_occurrence_log)
            print(f"🎯 创新爆发度过滤 (>={self.innovation_burst_threshold})：{original_count_before_burst:,} -> {burst_filtered_count:,} 个词汇")
        
        elapsed_time = time.time() - self.start_time
        print(f"✅ 分析完成！从{analysis_content}中发现 {len(self.first_occurrence_log):,} 个符合条件的词汇")
        print(f"   处理时间：{elapsed_time:.2f}秒，平均速度：{total_papers/elapsed_time:.0f}条/秒")
        return True
    
    def export_results(self, output_file='word_first_occurrences.csv', format='csv', 
                     encoding='utf-8-sig', auto_confirm=False):
        """导出结果"""
        if not self.first_occurrence_log:
            print("❌ 错误：没有分析结果可导出")
            return False
        
        if format == 'json' and len(self.first_occurrence_log) > 50000:
            print("⚠️  数据量较大，JSON格式文件可能很大，建议使用CSV格式")
            if auto_confirm:
                print("⚠️  auto_confirm=True，继续导出大JSON文件（可能较慢）")
            else:
                try:
                    response = input("是否继续导出JSON？(y/n): ")
                    if response.lower() != 'y':
                        print("用户取消导出")
                        return False
                except (EOFError, KeyboardInterrupt):
                    print("\n⚠️  非交互环境或用户中断，跳过JSON导出")
                    return False
        
        print(f"正在导出结果到 {output_file}（编码：{encoding}）...")
        
        if format == 'csv':
            all_years = set()
            for counts in self.word_year_counts.values():
                all_years.update(y for y in counts.keys() if y is not None)
            all_years = sorted(all_years)

            results_rows = []
            for word, info in self.first_occurrence_log.items():
                row_data = {
                    '词汇': word,
                    '总频率': self.word_frequencies[word],
                    '文档频率': self.word_document_frequency.get(word, 0),
                    'TF-IDF分数': round(self.word_tfidf_scores.get(word, 0), 4) if self.use_tfidf else 0,
                    f'首次出现{self.unique_id_column}': info.get(self.unique_id_column, '')
                }
                
                # 添加创新爆发度相关字段
                if self.use_burst_filter and word in self.word_burst_scores:
                    burst_details = self.word_burst_details.get(word, {})
                    row_data['创新爆发度'] = round(self.word_burst_scores[word], 4)
                    row_data['最大增长率'] = round(burst_details.get('max_growth_rate', 0), 4)
                    row_data['变异系数'] = round(burst_details.get('cv', 0), 4)
                    row_data['近期早期比'] = round(burst_details.get('recent_early_ratio', 0), 4)
                    row_data['峰值频率'] = int(burst_details.get('peak_freq', 0))
                    row_data['拐点年份'] = burst_details.get('turning_point_year', '')
                
                for col in self.time_columns:
                    value = info.get(col, 0)
                    row_data[f'首次出现{col}'] = int(value) if pd.notna(value) else 0
                
                row_data['首次出现来源'] = info.get('analysis_text', '')
                
                year_counts = self.word_year_counts.get(word, {})
                for y in all_years:
                    row_data[str(y)] = int(year_counts.get(y, 0))
                results_rows.append(row_data)

            results_df = pd.DataFrame(results_rows)
            
            # 确定排序策略：优先使用创新爆发度，其次TF-IDF，最后总频率
            if self.use_burst_filter and '创新爆发度' in results_df.columns:
                sort_keys = ['创新爆发度', '峰值频率', '词汇']
                sort_ascending = [False, False, True]
            elif self.use_tfidf and 'TF-IDF分数' in results_df.columns:
                sort_keys = ['TF-IDF分数', '词汇']
                sort_ascending = [False, True]
            else:
                sort_keys = ['总频率', '词汇']
                sort_ascending = [False, True]
            
            results_df = results_df.sort_values(sort_keys, ascending=sort_ascending)
            results_df.to_csv(output_file, index=False, encoding=encoding)
            
        elif format == 'json':
            try:
                export_data = {}
                for word, info in self.first_occurrence_log.items():
                    export_info = info.copy()
                    export_info['frequency'] = self.word_frequencies[word]
                    export_data[word] = export_info
                    
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"❌ JSON导出失败：{e}")
                return False
        
        print(f"✅ 导出完成！文件：{output_file}")
        print(f"   记录数：{len(self.first_occurrence_log):,}")
        print(f"   编码格式：{encoding}")
        return True
    
    def get_statistics(self):
        """获取统计信息"""
        if not self.first_occurrence_log:
            return None
        
        primary_time_col = self.time_columns[0]
        time_counts = defaultdict(int)
        
        # 统计时间分布
        for word_data in self.first_occurrence_log.values():
            time_val = word_data.get(primary_time_col, 0)
            if time_val != 0:  # 排除0值
                time_counts[time_val] += 1
        
        # 信息列统计
        info_col_stats = {}
        for col in self.info_columns:
            col_counts = defaultdict(int)
            for word_data in self.first_occurrence_log.values():
                value = word_data.get(col, '')
                if value and str(value).strip():
                    col_counts[str(value)] += 1
            info_col_stats[col] = dict(sorted(col_counts.items(), key=lambda x: x[1], reverse=True)[:10])
        
        # 词长统计
        word_length_counts = defaultdict(int)
        for word in self.first_occurrence_log.keys():
            word_length_counts[len(word)] += 1
        
        # 词频统计
        frequency_distribution = defaultdict(int)
        for word in self.first_occurrence_log.keys():
            freq = self.word_frequencies[word]
            frequency_distribution[freq] += 1
        
        # 时间范围
        times = list(time_counts.keys())
        min_time = min(times) if times else None
        max_time = max(times) if times else None
        
        return {
            'total_words': len(self.first_occurrence_log),
            'total_word_occurrences': sum(self.word_frequencies.values()),
            'average_frequency': sum(self.word_frequencies.values()) / len(self.first_occurrence_log) if self.first_occurrence_log else 0,
            'time_range': (min_time, max_time),
            'words_by_time': dict(sorted(time_counts.items())),
            'info_column_stats': info_col_stats,
            'word_length_distribution': dict(sorted(word_length_counts.items())),
            'frequency_distribution': dict(sorted(frequency_distribution.items())),
            'primary_time_column': primary_time_col,
            'analysis_mode': self.analysis_mode,
            'min_occurrence_filter': self.min_occurrence
        }
    
    def search_word(self, target_word):
        """搜索词汇"""
        target_word = target_word.lower().strip()                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               
        if target_word in self.first_occurrence_log:
            info = self.first_occurrence_log[target_word]
            frequency = self.word_frequencies[target_word]
            
            print(f"\n=== 词汇 '{target_word}' 的详细信息 ===")
            print(f"首次出现唯一号：{info[self.unique_id_column]}")
            print(f"总出现频率：{frequency} 次")
            
            for col in self.time_columns:
                if col in info and info[col] != 0:
                    print(f"{col}：{info[col]}")
            
            for col in self.info_columns:
                if col in info and info[col]:   
                    print(f"{col}：{info[col]}")
            
            if 'analysis_text' in info:
                print(f"首次出现来源：{info['analysis_text']}")
            
            print(f"完整引用：{info['full_citation']}")
            return {**info, 'frequency': frequency}
        else:
            print(f"❌ 未找到词汇 '{target_word}'")
            
            word_list = list(self.first_occurrence_log.keys())
            try:
                similar_words = difflib.get_close_matches(target_word, word_list, n=5, cutoff=0.6)
                if not similar_words:
                    sample_size = min(10000, len(word_list))
                    sample_words = word_list[:sample_size]
                    similar_words = [w for w in sample_words if target_word in w or w in target_word][:5]
                    
                if similar_words:
                    print(f"💡 相似词汇建议：{', '.join(similar_words)}")
            except Exception as e:
                print(f"⚠️  相似词搜索失败：{e}")
            
            return None
    
    def plot_statistics(self):
        """绘制统计图表"""
        try:
            import matplotlib.pyplot as plt
            import matplotlib
            matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
            matplotlib.rcParams['axes.unicode_minus'] = False
            
            stats = self.get_statistics()
            if not stats:
                print("没有统计数据可绘制")
                return
            
            fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
            
            time_data = stats['words_by_time']
            if time_data:
                def sort_key(x):
                    try:
                        return (0, int(x))
                    except (ValueError, TypeError):
                        return (1, str(x))
                
                sorted_times = sorted(time_data.keys(), key=sort_key)
                years = sorted_times
                counts = [time_data[year] for year in years]
                
                ax1.plot(range(len(years)), counts, marker='o')
                ax1.set_title('新词汇数量时间趋势')
                ax1.set_xlabel(stats['primary_time_column'])
                ax1.set_ylabel('新词汇数量')
                
                if len(years) > 10:
                    step = max(1, len(years) // 10)
                    ax1.set_xticks(range(0, len(years), step))
                    ax1.set_xticklabels([str(years[i]) for i in range(0, len(years), step)], rotation=45)
                else:
                    ax1.set_xticks(range(len(years)))
                    ax1.set_xticklabels([str(year) for year in years], rotation=45)
                ax1.grid(True)
            
            # 2. 词长分布
            length_data = stats['word_length_distribution']
            if length_data:
                lengths = list(length_data.keys())
                counts = list(length_data.values())
                ax2.bar(lengths, counts)
                ax2.set_title('词汇长度分布')
                ax2.set_xlabel('词汇长度')
                ax2.set_ylabel('词汇数量')
            
            # 3. 信息列统计
            if stats['info_column_stats']:
                col_name = list(stats['info_column_stats'].keys())[0]
                col_data = stats['info_column_stats'][col_name]
                if col_data:
                    names = list(col_data.keys())[:10]
                    counts = list(col_data.values())[:10]
                    ax3.barh(range(len(names)), counts)
                    ax3.set_yticks(range(len(names)))
                    ax3.set_yticklabels(names, fontsize=8)
                    ax3.set_title(f'{col_name}词汇贡献排行')
                    ax3.set_xlabel('词汇数量')
            
            # 4. 词频分布
            freq_data = stats['frequency_distribution']
            if freq_data:
                frequencies = sorted(freq_data.keys())
                counts = [freq_data[f] for f in frequencies]
                ax4.bar(frequencies, counts)
                ax4.set_title('词汇出现频率分布')
                ax4.set_xlabel('出现频率')
                ax4.set_ylabel('词汇数量')
                if max(counts) > 10:
                    ax4.set_yscale('log')
            
            plt.tight_layout()
            
            output_dir = os.path.dirname(os.path.abspath(self.csv_file_path))
            output_path = os.path.join(output_dir, 'word_statistics.png')
            plt.savefig(output_path, dpi=300, bbox_inches='tight')
            print(f"✅ 统计图表已保存为：{output_path}")
            
            plt.show()
            
        except ImportError:
            print("❌ 需要安装matplotlib才能绘制图表")
            print("   运行：pip install matplotlib")
        except Exception as e:
            print(f"❌ 绘图错误：{e}")
    
    def display_sample_results(self, n=10, sort_by='time'):
        """显示样例结果"""
        if not self.first_occurrence_log:
            print("没有分析结果可显示")
            return
        
        primary_time_col = self.time_columns[0]
        analysis_content = "信息列合并内容" if self.analysis_mode == 'info_columns' else f"文本列({self.text_column})"
        
        if sort_by == 'burst' and self.use_burst_filter:
            print(f"\n=== 创新词汇（前{n}个，按创新爆发度排序）===")
            sorted_words = sorted(self.first_occurrence_log.items(), 
                                key=lambda x: (self.word_burst_scores.get(x[0], 0), x[0]), reverse=True)
        elif sort_by == 'tfidf' and self.use_tfidf:
            print(f"\n=== 创新词汇（前{n}个，按TF-IDF排序）===")
            sorted_words = sorted(self.first_occurrence_log.items(), 
                                key=lambda x: (self.word_tfidf_scores.get(x[0], 0), x[0]), reverse=True)
        elif sort_by == 'freq':
            print(f"\n=== 从{analysis_content}中发现的高频词汇（前{n}个，按频率排序）===")
            sorted_words = sorted(self.first_occurrence_log.items(), 
                                key=lambda x: (self.word_frequencies[x[0]], x[0]), reverse=True)
        else:
            print(f"\n=== 从{analysis_content}中发现的词汇首次出现（前{n}个，按时间排序）===")
            sorted_words = sorted(self.first_occurrence_log.items(), 
                                key=lambda x: (x[1].get(primary_time_col, 0), x[0]))
        
        for i, (word, info) in enumerate(sorted_words[:n]):
            frequency = self.word_frequencies[word]
            tfidf = self.word_tfidf_scores.get(word, 0)
            doc_freq = self.word_document_frequency.get(word, 0)
            
            # 优先显示创新爆发度信息
            if self.use_burst_filter and word in self.word_burst_scores:
                burst_score = self.word_burst_scores[word]
                burst_details = self.word_burst_details.get(word, {})
                peak_freq = burst_details.get('peak_freq', frequency)
                max_growth = burst_details.get('max_growth_rate', 0)
                turning_point = burst_details.get('turning_point_year', '')
                
                print(f"{i+1}. 词汇：'{word}'（爆发度={burst_score:.4f}, 峰值={peak_freq:,}, 最大增长率={max_growth:.2f}倍）")
                if turning_point:
                    print(f"   拐点：{turning_point}年")
            elif self.use_tfidf:
                print(f"{i+1}. 词汇：'{word}'（TF-IDF={tfidf:.2f}, 词频={frequency}, 文档频率={doc_freq}）")
            else:
                print(f"{i+1}. 词汇：'{word}'（长度：{len(word)}, 频率：{frequency}次）")
            
            print(f"   唯一号：{info[self.unique_id_column]}")
            
            time_info = []
            for col in self.time_columns:
                if col in info and info[col] != 0:
                    time_info.append(f"{col}:{info[col]}")
            if time_info:
                print(f"   时间：{', '.join(time_info)}")
            
            for col in self.info_columns:
                if col in info and info[col]:
                    print(f"   {col}：{info[col]}")
            
            if 'analysis_text' in info:
                print(f"   来源：{info['analysis_text']}")
            
            print()
    
    def run_complete_analysis(self, total_rows, output_file='word_first_occurrences.csv', 
                             export_encoding='utf-8-sig', auto_confirm=True, 
                             show_sample_by='time', processing_stage='auto'):
        """运行完整分析（分阶段处理）
        
        Args:
            total_rows: 数据总行数（显式传入）
            output_file: 输出文件路径
            export_encoding: 导出编码
            auto_confirm: 自动确认
            show_sample_by: 样例排序方式
            processing_stage: 处理阶段 (1=基础统计, 2=词性过滤+导出, 'auto'=自动判断)
        """
        print("=" * 70)
        print("🚀 词汇首次出现分析器（分阶段处理版）")
        print("=" * 70)
        
        overall_start = time.time()
        
        # 自动判断阶段
        if processing_stage == 'auto':
            if os.path.exists(f'{self.intermediate_prefix}_counts.parquet') or os.path.exists(f'{self.intermediate_prefix}_counts.csv'):
                print("🔍 检测到中间结果文件，自动进入阶段2")
                processing_stage = 2
            else:
                print("🔍 未检测到中间结果，自动进入阶段1")
                processing_stage = 1
        
        # 阶段1：基础统计
        if processing_stage == 1:
            print("\n📊 === 阶段1：基础统计（跳过词性过滤） ===")
            
            if not self.validate_sorted_data():
                return False
            
            print(f"📊 数据总行数：{total_rows:,}")
            
            # 临时禁用词性过滤
            original_use_pos_filter = self.use_pos_filter
            self.use_pos_filter = False
            
            if not self.analyze_first_occurrences(total_rows):
                self.use_pos_filter = original_use_pos_filter
                return False
            
            self.use_pos_filter = original_use_pos_filter
            
            # 保存中间结果
            if not self.save_intermediate_results():
                return False
            
            print("\n" + "=" * 70)
            print("✅ 阶段1完成！中间结果已保存")
            print(f"⏱️  阶段1运行时间：{time.time() - overall_start:.2f}秒")
            print("\n💡 下一步：运行阶段2进行词性过滤和最终导出")
            print(f"   提示：将 PROCESSING_STAGE 设置为 2 或 'auto'")
            print("=" * 70)
            return True
        
        # 阶段2：词性过滤 + 最终处理
        elif processing_stage == 2:
            print("\n📊 === 阶段2：词性过滤 + 最终处理 ===")
            
            # 加载中间结果
            if not self.load_intermediate_results():
                print("❌ 无法加载中间结果，请先运行阶段1")
                return False
            
            self._print_memory_usage()
            
            # 执行词性过滤
            if self.use_pos_filter and self.nlp:
                print("\n🚀 开始词性过滤...")
                original_word_count = len(self.first_occurrence_log)
                
                all_words = list(self.first_occurrence_log.keys())
                filtered_words = self._gpu_batch_pos_filter_main(all_words)
                
                # 根据过滤结果重建所有统计数据
                self.word_frequencies = Counter({w: self.word_frequencies[w] for w in filtered_words if w in self.word_frequencies})
                self.word_document_frequency = Counter({w: self.word_document_frequency[w] for w in filtered_words if w in self.word_document_frequency})
                self.word_year_counts = defaultdict(lambda: defaultdict(int), {
                    w: self.word_year_counts[w] for w in filtered_words if w in self.word_year_counts
                })
                self.first_occurrence_log = {w: self.first_occurrence_log[w] for w in filtered_words if w in self.first_occurrence_log}
                
                filtered_word_count = len(self.first_occurrence_log)
                print(f"✅ 词性过滤完成：{original_word_count:,} -> {filtered_word_count:,} 个词汇")
                
                gc.collect()
                self._print_memory_usage()
            
            # 计算TF-IDF
            if self.use_tfidf:
                print("\n📊 计算TF-IDF分数...")
                self._calculate_tfidf()
                print(f"✅ TF-IDF计算完成！")
                gc.collect()
            
            # 计算创新爆发度
            if self.use_burst_filter:
                print("\n📈 计算创新爆发度...")
                self._calculate_innovation_burst_score()
                
                # 应用爆发度阈值过滤
                original_count_before_burst = len(self.first_occurrence_log)
                filtered_log = {word: info for word, info in self.first_occurrence_log.items() 
                               if self.word_burst_scores.get(word, 0) >= self.innovation_burst_threshold}
                
                self.word_frequencies = Counter({word: count for word, count in self.word_frequencies.items() 
                                               if word in filtered_log})
                self.word_document_frequency = Counter({word: count for word, count in self.word_document_frequency.items() 
                                                       if word in filtered_log})
                self.word_year_counts = defaultdict(lambda: defaultdict(int), {
                    word: counts for word, counts in self.word_year_counts.items() if word in filtered_log
                })
                
                if self.use_tfidf:
                    self.word_tfidf_scores = {word: score for word, score in self.word_tfidf_scores.items() 
                                             if word in filtered_log}
                
                self.word_burst_scores = {word: score for word, score in self.word_burst_scores.items() 
                                         if word in filtered_log}
                self.word_burst_details = {word: details for word, details in self.word_burst_details.items() 
                                          if word in filtered_log}
                
                self.first_occurrence_log = filtered_log
                burst_filtered_count = len(self.first_occurrence_log)
                print(f"🎯 创新爆发度过滤 (>={self.innovation_burst_threshold})：{original_count_before_burst:,} -> {burst_filtered_count:,} 个词汇")
                
                gc.collect()
                self._print_memory_usage()
        
        stats = self.get_statistics()
        if stats:
            print(f"\n📊 === 分析结果统计 ===")
            print(f"符合条件的词汇：{stats['total_words']:,}")
            print(f"词汇总出现次数：{stats['total_word_occurrences']:,}")
            print(f"平均出现频率：{stats['average_frequency']:.2f}次/词")
            
            if stats['time_range'][0] is not None:
                print(f"时间跨度（{stats['primary_time_column']}）：{stats['time_range'][0]} - {stats['time_range'][1]}")
            
            if stats['words_by_time']:
                peak_time, peak_count = max(stats['words_by_time'].items(), key=lambda x: x[1])
                print(f"词汇增长峰值：{peak_time}（{peak_count:,} 个新词）")
            
            if stats['min_occurrence_filter'] > 1:
                print(f"最小出现频率过滤：>={stats['min_occurrence_filter']}次")
            
            for col, col_stats in stats['info_column_stats'].items():
                if col_stats:
                    print(f"\n{col}词汇贡献（前3）：")
                    for value, count in list(col_stats.items())[:3]:
                        print(f"  {value}：{count:,} 个")
        
        # 显示创新词汇：优先使用爆发度，其次TF-IDF，最后按指定方式
        if self.use_burst_filter:
            display_mode = 'burst'
        elif self.use_tfidf:
            display_mode = 'tfidf'
        else:
            display_mode = show_sample_by
        
        self.display_sample_results(8, sort_by=display_mode)
        
        self.export_results(output_file, encoding=export_encoding, auto_confirm=auto_confirm)
        
        total_time = time.time() - overall_start
        
        print("\n" + "=" * 70)
        print("✅ 分析完成！")
        print(f"⏱️  总运行时间：{total_time:.2f}秒")
        print("💡 可用功能：")
        print("   - analyzer.search_word('词汇') 搜索特定词汇")
        print("   - analyzer.plot_statistics() 绘制统计图表") 
        print("   - analyzer.word_frequencies 查看词频统计")
        if self.use_burst_filter:
            print("   - analyzer.word_burst_scores 查看创新爆发度分数")
            print("   - analyzer.display_sample_results(n=10, sort_by='burst') 按爆发度排序")
        if self.use_tfidf:
            print("   - analyzer.word_tfidf_scores 查看TF-IDF分数")
            print("   - analyzer.display_sample_results(n=10, sort_by='tfidf') 按TF-IDF排序")
        print("   - analyzer.display_sample_results(n=10, sort_by='freq') 按频率排序显示")
        print("   - analyzer.clean_temp_files() 清理临时文件")
        print("=" * 70)
        return True


if __name__ == "__main__":
    # Windows多进程支持
    multiprocessing.freeze_support()
    
    # 数据文件配置
    CSV_FILE_PATH = '2025外文论文全字段.csv'
    TOTAL_ROWS = 9167774  # 数据总行数（已知固定值，避免全量加载计数）
    
    # 列配置
    TIME_COLUMNS = ['出版年', '卷', '期']
    INFO_COLUMNS = ['期刊名称', '标题', '关键词', 'KeywordsPlus', '摘要']
    UNIQUE_ID_COLUMN = '入藏号'
    
    # 基础参数
    LANGUAGE = 'en'
    MIN_WORD_LENGTH = 2
    MIN_OCCURRENCE = 1
    PROGRESS_INTERVAL = 500
    OUTPUT_FILE = 'perfect_word_analysis.csv'
    EXPORT_ENCODING = 'utf-8-sig'
    
    # 创新词汇识别算法
    USE_TFIDF = True
    USE_BURST_FILTER = True
    INNOVATION_BURST_THRESHOLD = 0.15
    MIN_YEARS_SPAN = 2
    TURNING_POINT_GROWTH_FACTOR = 3.0
    TURNING_POINT_MIN_FREQ = 100
    RECENT_WINDOW_YEARS = 5
    EXCLUDE_LAST_N_YEARS = 1
    RECENT_EARLY_SPLIT_YEAR = None
    
    # 停用词配置
    STOPWORD_FILES = ['config/stopwords_en.txt', 'config/stopwords_cn.txt', 'config/structural_stopwords.txt', 'config/scientific_stopwords_doc_freq.txt']
    
    # 词性过滤（主进程GPU批量推理，子进程不参与）
    # 功能：仅保留名词/形容词等实质性词汇，过滤动词/副词等
    # 架构：主进程统一GPU批量词性过滤，避免多进程冲突
    USE_POS_FILTER = True
    
    # N-gram短语提取
    EXTRACT_NGRAMS = True
    NGRAM_RANGE = (2, 3)
    
    # 文档频率上限（过滤超高频通用词）
    DOC_FREQ_THRESHOLD = 0.9
    
    # 分阶段处理配置
    # 'auto' = 自动判断（检测中间文件）
    # 1 = 仅执行阶段1（基础统计，跳过词性过滤）
    # 2 = 仅执行阶段2（加载中间结果，执行词性过滤和导出）
    PROCESSING_STAGE = 'auto'
    
    try:
        print("🚀 启动词汇分析器（分阶段处理版）")
        
        analyzer = WordFirstOccurrenceAnalyzer(
            csv_file_path=CSV_FILE_PATH,
            time_columns=TIME_COLUMNS,
            info_columns=INFO_COLUMNS,
            text_column=None,
            unique_id_column=UNIQUE_ID_COLUMN,
            language=LANGUAGE,
            min_word_length=MIN_WORD_LENGTH,
            analyze_info_columns=True,
            min_occurrence=MIN_OCCURRENCE,
            show_progress=True,
            progress_interval=PROGRESS_INTERVAL,
            use_tfidf=USE_TFIDF,
            stopword_files=STOPWORD_FILES,
            use_burst_filter=USE_BURST_FILTER,
            innovation_burst_threshold=INNOVATION_BURST_THRESHOLD,
            min_years_span=MIN_YEARS_SPAN,
            turning_point_growth_factor=TURNING_POINT_GROWTH_FACTOR,
            turning_point_min_freq=TURNING_POINT_MIN_FREQ,
            recent_window_years=RECENT_WINDOW_YEARS,
            exclude_last_n_years=EXCLUDE_LAST_N_YEARS,
            recent_early_split_year=RECENT_EARLY_SPLIT_YEAR,
            use_pos_filter=USE_POS_FILTER,
            extract_ngrams=EXTRACT_NGRAMS,
            ngram_range=NGRAM_RANGE,
            doc_freq_threshold=DOC_FREQ_THRESHOLD
        )
        
        success = analyzer.run_complete_analysis(
            total_rows=TOTAL_ROWS,
            output_file=OUTPUT_FILE,
            export_encoding=EXPORT_ENCODING,
            auto_confirm=True,
            show_sample_by='burst' if USE_BURST_FILTER else ('tfidf' if USE_TFIDF else 'time'),
            processing_stage=PROCESSING_STAGE
        )
        
        if success:
            print(f"\n🎉 分析完成！结果保存到：{OUTPUT_FILE}")
            
            if USE_BURST_FILTER and analyzer.word_burst_scores:
                top_innovative = sorted(analyzer.word_burst_scores.items(), key=lambda x: x[1], reverse=True)[:5]
                print(f"\n🌟 创新爆发度最高的5个词汇：")
                for word, burst_score in top_innovative:
                    burst_details = analyzer.word_burst_details.get(word, {})
                    peak_freq = burst_details.get('peak_freq', 0)
                    turning_point = burst_details.get('turning_point_year', '')
                    turning_info = f", 拐点={turning_point}年" if turning_point else ""
                    print(f"   '{word}'：爆发度={burst_score:.4f}, 峰值={peak_freq:,}{turning_info}")
            elif USE_TFIDF and analyzer.word_tfidf_scores:
                top_innovative = sorted(analyzer.word_tfidf_scores.items(), key=lambda x: x[1], reverse=True)[:5]
                print(f"\n🌟 创新度最高的5个词汇（TF-IDF）：")
                for word, tfidf in top_innovative:
                    freq = analyzer.word_frequencies[word]
                    print(f"   '{word}'：TF-IDF={tfidf:.2f}, 词频={freq}")
            elif analyzer.word_frequencies:
                top_words = analyzer.word_frequencies.most_common(5)
                print(f"\n🔥 出现频率最高的5个词汇：")
                for word, freq in top_words:
                    print(f"   '{word}'：{freq}次")
            
            try:
                print("\n📊 正在生成统计图表...")
                analyzer.plot_statistics()
            except Exception as e:
                print(f"💡 图表生成失败：{e}")
                print("   提示：安装matplotlib可显示统计图表")
                
        else:
            print("\n❌ 分析失败，请检查配置和数据")
            
    except KeyboardInterrupt:
        print("\n⏹️  分析被用户中断")
    except Exception as e:
        print(f"\n💥 程序错误：{e}")
        print("\n🔧 排查建议：")
        print("1. 检查文件路径和权限")
        print("2. 验证CSV文件格式和列名") 
        print("3. 确认数据质量和类型")
        print("4. 检查参数配置范围")
        print("5. 确保有足够的内存和磁盘空间")
