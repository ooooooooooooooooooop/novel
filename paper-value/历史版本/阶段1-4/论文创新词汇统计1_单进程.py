
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

try:
    import numba
    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False

try:
    import pyarrow
    PYARROW_AVAILABLE = True
except ImportError:
    PYARROW_AVAILABLE = False
    print("⚠️  未安装pyarrow，将使用CSV格式（较慢）")

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
    """批量词性过滤"""
    if not all_words_list or not nlp:
        return all_words_list
    
    texts = [' '.join(words) for words in all_words_list if words]
    if not texts:
        return all_words_list
    
    valid_pos = {'NOUN', 'PROPN', 'ADJ', 'NUM', 'X'}
    filtered_results = []
    
    for doc, original_words in zip(nlp.pipe(texts, batch_size=batch_size), all_words_list):
        if not original_words:
            filtered_results.append([])
            continue
        
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
    """词汇首次出现分析器（单进程版本）"""
    
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
        """初始化分析器"""
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
        self.header = None
        self.first_occurrence_log = {}
        self.word_frequencies = Counter()
        self.word_document_frequency = Counter()
        self.word_tfidf_scores = {}
        self.total_documents = 0
        self.start_time = None
        self.word_year_counts = defaultdict(lambda: defaultdict(int))
        self.word_burst_scores = {}
        self.word_burst_details = {}
        self.innovation_indices = {}
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
        
        # 加载spacy模型
        if self.use_pos_filter:
            if not SPACY_AVAILABLE:
                print("⚠️  未安装spacy库，词性过滤将被禁用")
                self.use_pos_filter = False
            else:
                try:
                    import spacy
                    gpu_enabled = spacy.prefer_gpu()
                    self.nlp = spacy.load('en_core_web_sm')
                    
                    if gpu_enabled:
                        print("✅ spaCy英文模型加载成功（GPU加速已启用）")
                    else:
                        print("✅ spaCy英文模型加载成功（CPU模式）")
                except OSError:
                    print("⚠️  未找到spaCy英文模型，词性过滤将被禁用")
                    self.use_pos_filter = False
                    self.nlp = None
        
        # 验证配置
        self._validate_config()
        
        if self.use_tfidf:
            print("💡 TF-IDF模式已启用，将自动识别创新词汇")
        if self.use_pos_filter:
            print("💡 词性过滤已启用，仅保留名词和形容词")
        if self.extract_ngrams:
            print(f"💡 N-gram提取已启用，范围：{self.ngram_range}")
    
    def _validate_config(self):
        """验证配置和数据文件"""
        print("🔍 验证文件和配置...")
        
        if not os.path.exists(self.csv_file_path):
            raise FileNotFoundError(f"数据文件未找到：{self.csv_file_path}")
        
        # 读取文件头部信息
        try:
            if self.csv_file_path.endswith('.parquet'):
                sample = pd.read_parquet(self.csv_file_path, nrows=5)
            else:
                sample = pd.read_csv(self.csv_file_path, nrows=5)
            self.header = list(sample.columns)
            print(f"✅ 数据文件格式正确，列数：{len(self.header)}")
        except Exception as e:
            raise ValueError(f"读取数据文件失败：{e}")
        
        # 验证必需列
        required_columns = [self.unique_id_column] + self.time_columns
        if self.analysis_mode == 'info_columns':
            required_columns.extend(self.info_columns)
        else:
            required_columns.append(self.text_column)
        
        missing_columns = [col for col in required_columns if col not in self.header]
        if missing_columns:
            raise ValueError(f"缺少必需列：{missing_columns}")
        
        print(f"✅ 所有必需列都存在")
        print(f"📋 分析模式：{self.analysis_mode}")
        
        if self.analysis_mode == 'info_columns':
            print(f"📋 信息列：{self.info_columns}")
        else:
            print(f"📋 文本列：{self.text_column}")
        print(f"📋 时间列：{self.time_columns}")
        print(f"📋 唯一ID列：{self.unique_id_column}")
        print(f"📋 语言：{self.language}")
        
    def _get_stop_words(self):
        """加载停用词列表（增强版）"""
        stop_words = set()
        
        for file_path in self.stopword_files:
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        words = [line.strip().lower() for line in f if line.strip()]
                        stop_words.update(words)
                        print(f"✅ 加载停用词文件：{file_path}（{len(words)} 个词）")
                except Exception as e:
                    print(f"⚠️  加载停用词文件失败：{file_path}，错误：{e}")
            else:
                print(f"⚠️  停用词文件未找到：{file_path}")
        
        # 添加增强版内置停用词（解决期刊和常见词问题）
        builtin_stopwords = {
            # 基础停用词
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
            'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been', 
            'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 
            'could', 'should', 'may', 'might', 'can', 'this', 'that', 'these', 
            'those', 'we', 'they', 'it', 'he', 'she', 'you', 'i', 'me', 'my', 
            'our', 'their', 'his', 'her', 'its', 'your',
            
            # 期刊和出版商相关（解决frontiers, plos等问题）
            'journal', 'nature', 'science', 'plos', 'cell', 'lancet', 'nejm',
            'springer', 'elsevier', 'wiley', 'oxford', 'cambridge', 'ieee',
            'frontiers', 'mdpi', 'hindawi', 'biomed', 'pubmed', 'doi', 'pmid',
            'rsc', 'acs', 'sae', 'publications', 'publisher', 'press',
            
            # 学术常见词汇（解决abstract等问题）
            'abstract', 'keywords', 'introduction', 'conclusion', 'references',
            'methodology', 'results', 'discussion', 'acknowledgments', 'acknowledgement',
            'article', 'paper', 'study', 'research', 'analysis', 'method',
            'data', 'model', 'system', 'approach', 'technique', 'process',
            'editorial', 'review', 'letter', 'comment', 'reply', 'correspondence',
            'volume', 'issue', 'page', 'pages', 'number', 'vol', 'no', 'pp',
            'copyright', 'license', 'rights', 'reserved', 'permission',
            
            # 机构和地名
            'publication', 'published', 'university', 'institute', 'laboratory', 
            'department', 'center', 'centre', 'international', 'national', 
            'society', 'association', 'organization', 'switzerland', 'switzerl',
            
            # 常见但非创新词汇（解决behavi, prote等问题）
            'using', 'based', 'method', 'approach', 'technique', 'analysis',
            'model', 'system', 'data', 'information', 'technology', 'computer',
            'software', 'hardware', 'algorithm', 'program', 'application',
            'development', 'design', 'implementation', 'evaluation', 'performance',
            'optimization', 'improvement', 'enhancement', 'efficient', 'effective',
            'novel', 'new', 'innovative', 'advanced', 'modern', 'recent',
            'current', 'existing', 'traditional', 'conventional', 'standard',
            'general', 'common', 'typical', 'normal', 'regular', 'usual',
            
            # 截断词汇和常见问题词汇
            'behavi', 'behavior', 'behaviour', 'prote', 'protein', 'proteins',
            'obta', 'obtain', 'obtained', 'obtaining', 'stra', 'strategy', 'strategies',
            'underst', 'understand', 'understanding', 'certa', 'certain', 'certainly',
            'sens', 'sense', 'sensing', 'sensitive', 'sensitivity', 'sensor',
            'superi', 'superior', 'superiority', 'rema', 'remain', 'remaining',
            'multi', 'multiple', 'doma', 'domain', 'domains', 'fe', 'iron',
            
            # 数量和序数词
            'single', 'double', 'triple', 'multiple', 'various',
            'different', 'similar', 'same', 'other', 'another', 'each',
            'every', 'all', 'some', 'any', 'many', 'few', 'several',
            'first', 'second', 'third', 'last', 'final', 'initial',
            'main', 'major', 'minor', 'primary', 'secondary', 'basic',
            'fundamental', 'essential', 'important', 'significant', 'critical',
            
            # 疾病和疫情相关常见词（如果covid等也被认为过于常见）
            'pandemic', 'epidemic', 'disease', 'infection', 'virus', 'bacterial',
            
            # 编辑和格式词汇
            'notes', 'note', 'editor', 'editors', 'edited', 'revision', 'revised',
            'manuscript', 'submission', 'submitted', 'accepted', 'publication',
            
            # 免疫学常见词
            'immunology', 'immune', 'immunity', 'antibody', 'antigen',
            
            # 物理化学单位
            'nm', 'nanometer', 'micrometer', 'millimeter', 'centimeter',
            'gram', 'kilogram', 'liter', 'molar', 'celsius', 'fahrenheit'
        }
        
        stop_words.update(builtin_stopwords)
        
        print(f"📝 总停用词数量：{len(stop_words)}（包含增强过滤）")
        return stop_words
    
    def analyze_first_occurrences(self, total_rows=None):
        """分析词汇首次出现（单进程版本）"""
        self.start_time = time.time()
        print("🔄 开始词汇首次出现分析（单进程版本）")
        
        # 读取数据
        if self.csv_file_path.endswith('.parquet'):
            if total_rows:
                chunk_data = pd.read_parquet(self.csv_file_path).head(total_rows)
            else:
                chunk_data = pd.read_parquet(self.csv_file_path)
        else:
            if total_rows:
                chunk_data = pd.read_csv(self.csv_file_path, nrows=total_rows)
            else:
                chunk_data = pd.read_csv(self.csv_file_path)
        
        total_papers = len(chunk_data)
        print(f"📊 数据加载完成，共 {total_papers} 条记录")
        
        # 预合并分析列（如果需要）
        if self.analysis_mode == 'info_columns':
            print("🔧 预合并信息列...")
            chunk_data['combined_info'] = chunk_data[self.info_columns].fillna('').agg(' '.join, axis=1)
        
        # 批量收集文本和行数据
        print("🔧 批量收集文本数据...")
        texts_to_process = []
        rows_data = []
        
        for _, row in chunk_data.iterrows():
            row_dict = row.to_dict()
            
            # 创建分析文本
            if self.analysis_mode == 'info_columns':
                analysis_text = row_dict.get('combined_info', '')
            else:
                value = row_dict.get(self.text_column)
                analysis_text = str(value) if pd.notna(value) else ''
            
            texts_to_process.append(analysis_text)
            rows_data.append(row_dict)
        
        print(f"✅ 收集完成，共 {len(texts_to_process)} 条文本")
        
        # 批量预处理所有文本
        print("🔧 批量预处理文本...")
        all_words_list = []
        
        if self.show_progress:
            iterator = tqdm(enumerate(texts_to_process), total=len(texts_to_process), desc="预处理文本")
        else:
            iterator = enumerate(texts_to_process)
        
        for i, text in iterator:
            words = _preprocess_text_worker(
                text, self.language, self.min_word_length, self.stop_words, self.analysis_mode,
                self.word_pattern, self.punctuation_pattern1, self.punctuation_pattern2,
                self.punctuation_pattern3, self.punctuation_pattern4, self.hyphen_pattern,
                self.word_concat_pattern, self.extract_ngrams, self.ngram_range
            )
            all_words_list.append(words)
        
        print(f"✅ 文本预处理完成")
        
        # 词性过滤（批量）
        if self.use_pos_filter and self.nlp:
            print("🔧 执行批量词性过滤...")
            
            try:
                import spacy
                gpu_enabled = spacy.prefer_gpu()
                batch_size = 1000 if gpu_enabled else 500
            except:
                batch_size = 500
            
            all_words_list = _batch_pos_filter(all_words_list, self.nlp, batch_size)
            print("✅ 词性过滤完成")
        
        # 统计词汇
        print("🔧 统计词汇频次和首次出现...")
        local_freq = Counter()
        local_doc_freq = Counter()
        local_year_counts = defaultdict(lambda: defaultdict(int))
        local_first_occurrence = {}
        local_doc_count = 0
        
        if self.show_progress:
            iterator = tqdm(enumerate(zip(rows_data, all_words_list)), 
                          total=len(rows_data), desc="统计词汇")
        else:
            iterator = enumerate(zip(rows_data, all_words_list))
        
        for i, (row_dict, words) in iterator:
            if not words:
                continue
            
            local_doc_count += 1
            unique_words = set(words)
            
            # 词频统计（总出现次数）
            for word in words:
                local_freq[word] += 1
            
            # 文档频次统计（包含该词的文档数）
            for word in unique_words:
                local_doc_freq[word] += 1
            
            # 年份统计
            primary_year = row_dict.get(self.time_columns[0])
            year_val = int(primary_year) if pd.notna(primary_year) else None
            if year_val is not None:
                for word in words:
                    local_year_counts[word][year_val] += 1
            
            # 首次出现记录
            new_words = [w for w in words if w not in local_first_occurrence]
            if new_words:
                paper_info = {self.unique_id_column: str(row_dict[self.unique_id_column])}
                for col in self.time_columns:
                    value = row_dict[col]
                    paper_info[col] = int(value) if pd.notna(value) else 0
                
                for word in new_words:
                    paper_info_copy = paper_info.copy()
                    paper_info_copy['analysis_text'] = _extract_snippet_worker(texts_to_process[i], word, 30)
                    local_first_occurrence[word] = paper_info_copy
        
        # 更新全局统计
        self.word_frequencies = local_freq
        self.word_document_frequency = local_doc_freq
        self.word_year_counts = local_year_counts
        self.first_occurrence_log = local_first_occurrence
        self.total_documents = local_doc_count
        
        print(f"✅ 词汇统计完成")
        print(f"📊 处理文档数：{self.total_documents}")
        print(f"📊 唯一词汇数：{len(self.word_frequencies)}")
        print(f"📊 首次出现记录数：{len(self.first_occurrence_log)}")
        
        # 检查covid统计（验证）
        if 'covid' in self.word_frequencies:
            print(f"🔍 验证统计：covid词频={self.word_frequencies['covid']}, 文档频率={self.word_document_frequency.get('covid', 0)}")
        
        # 清理内存
        del chunk_data, texts_to_process, rows_data, all_words_list
        del local_freq, local_doc_freq, local_year_counts, local_first_occurrence
        gc.collect()
        print("🗑️  内存清理完成")
        
        # 计算TF-IDF分数
        if self.use_tfidf:
            print("🔢 计算TF-IDF分数...")
            self._calculate_tfidf()
        
        # 计算创新爆发度和所有创新指标
        if self.use_burst_filter:
            print("📈 计算创新指标...")
            self._calculate_innovation_metrics()
        
        # 计算最终创新指数
        print("🎯 计算创新指数...")
        self._calculate_innovation_index()
        
        total_time = time.time() - self.start_time
        print(f"✅ 分析完成，耗时：{total_time:.1f}秒")
        print(f"📊 处理词汇数：{len(self.word_frequencies)}")
        print(f"📊 处理文档数：{self.total_documents}")
        print(f"📊 创新指数计算完成：{len(self.innovation_indices)}")
        
    def _calculate_tfidf(self):
        """计算TF-IDF分数"""
        # 应用最小出现频率过滤
        filtered_words = {word for word, freq in self.word_frequencies.items() if freq >= self.min_occurrence}
        
        # 计算TF-IDF
        for word in filtered_words:
            tf = self.word_frequencies[word]
            df = self.word_document_frequency[word]
            
            # 文档频率过滤
            doc_freq_ratio = df / self.total_documents
            if doc_freq_ratio > self.doc_freq_threshold:
                continue
            
            idf = math.log(self.total_documents / df)
            tfidf = tf * idf
            self.word_tfidf_scores[word] = tfidf
        
        print(f"✅ TF-IDF计算完成，有效词汇：{len(self.word_tfidf_scores)}")
    
    def _calculate_innovation_metrics(self):
        """计算完整的创新指标"""
        # 确定分析年份范围
        all_years = set()
        for year_dict in self.word_year_counts.values():
            all_years.update(year_dict.keys())
        
        if not all_years:
            print("⚠️  未找到年份信息，跳过创新指标分析")
            return
        
        min_year, max_year = min(all_years), max(all_years)
        effective_max_year = max_year - self.exclude_last_n_years
        
        # 确定近期和早期的分割年份
        if self.recent_early_split_year is None:
            split_year = effective_max_year - self.recent_window_years
        else:
            split_year = self.recent_early_split_year
        
        print(f"📅 年份范围：{min_year}-{max_year}，分析范围：{min_year}-{effective_max_year}")
        print(f"📅 近期/早期分割年：{split_year}")
        
        # 处理符合条件的词汇
        valid_words = {word for word, freq in self.word_frequencies.items() 
                      if freq >= self.min_occurrence}
        
        for word in valid_words:
            year_counts = self.word_year_counts.get(word, {})
            if not year_counts:
                continue
            
            # 过滤有效年份
            filtered_counts = {year: count for year, count in year_counts.items() 
                             if min_year <= year <= effective_max_year}
            
            if not filtered_counts:
                continue
            
            word_min_year = min(filtered_counts.keys())
            word_max_year = max(filtered_counts.keys())
            years_span = word_max_year - word_min_year + 1
            
            if years_span < self.min_years_span:
                continue
            
            # 计算各种创新指标
            metrics = self._compute_word_innovation_metrics(
                word, filtered_counts, split_year, word_min_year, word_max_year
            )
            
            if metrics['innovation_burst'] >= self.innovation_burst_threshold:
                self.word_burst_scores[word] = metrics['innovation_burst']
                self.word_burst_details[word] = metrics
        
        print(f"✅ 创新指标计算完成，符合条件的词汇：{len(self.word_burst_details)}")
    
    def _compute_word_innovation_metrics(self, word, year_counts, split_year, min_year, max_year):
        """计算单个词汇的所有创新指标"""
        # 基本统计
        total_freq = sum(year_counts.values())
        years_span = max_year - min_year + 1
        
        # 早期和近期频次
        early_freq = sum(count for year, count in year_counts.items() if year <= split_year)
        recent_freq = sum(count for year, count in year_counts.items() if year > split_year)
        
        # 1. 创新爆发度（原有逻辑）
        recent_early_ratio = recent_freq / max(early_freq, 1)
        growth_intensity = math.log(recent_early_ratio + 1)
        time_decay = 1 / (2024 - max_year + 1)
        innovation_burst = growth_intensity * time_decay
        
        # 2. 最大增长率
        yearly_counts = []
        for year in range(min_year, max_year + 1):
            yearly_counts.append(year_counts.get(year, 0))
        
        growth_rates = []
        for i in range(1, len(yearly_counts)):
            if yearly_counts[i-1] > 0:
                growth_rate = yearly_counts[i] / yearly_counts[i-1]
                growth_rates.append(growth_rate)
        
        max_growth_rate = max(growth_rates) if growth_rates else 1.0
        
        # 3. 变异系数
        if len(yearly_counts) > 1 and np.mean(yearly_counts) > 0:
            coefficient_variation = np.std(yearly_counts) / np.mean(yearly_counts)
        else:
            coefficient_variation = 0
        
        # 4. 近期早期比
        recent_early_ratio_metric = recent_freq / max(early_freq, 1)
        
        # 5. 峰值频率
        peak_frequency = max(yearly_counts) if yearly_counts else 0
        
        # 6. 拐点年份
        turning_point_year = self._detect_turning_point(
            list(range(min_year, max_year + 1)), yearly_counts
        )
        
        return {
            'innovation_burst': innovation_burst,
            'max_growth_rate': max_growth_rate,
            'coefficient_variation': coefficient_variation,
            'recent_early_ratio': recent_early_ratio_metric,
            'peak_frequency': peak_frequency,
            'turning_point_year': turning_point_year,
            'early_freq': early_freq,
            'recent_freq': recent_freq,
            'total_freq': total_freq,
            'years_span': years_span,
            'first_year': min_year,
            'last_year': max_year
        }
    
    def _detect_turning_point(self, years, counts):
        """检测拐点年份（频次开始快速增长的年份）"""
        if len(years) < 3 or max(counts) < self.turning_point_min_freq:
            return years[0] if years else 2000
        
        # 计算增长率序列
        growth_rates = []
        for i in range(1, len(counts)):
            if counts[i-1] > 0:
                growth_rate = (counts[i] - counts[i-1]) / counts[i-1]
            else:
                growth_rate = 1.0 if counts[i] > 0 else 0.0
            growth_rates.append(growth_rate)
        
        # 寻找增长率显著上升的点
        turning_points = []
        for i in range(1, len(growth_rates)):
            if (growth_rates[i] > growth_rates[i-1] * self.turning_point_growth_factor and 
                growth_rates[i] > 0.5):  # 至少50%增长
                turning_points.append((years[i+1], growth_rates[i]))
        
        if turning_points:
            # 返回增长率最大的年份
            return max(turning_points, key=lambda x: x[1])[0]
        
        # 如果没有明显拐点，返回频次开始明显增加的年份
        max_count = max(counts)
        threshold = max_count * 0.2  # 峰值的20%
        for i, count in enumerate(counts):
            if count >= threshold:
                return years[i]
        
        return years[0]
    
    def _calculate_innovation_index(self):
        """计算创新指数（加权综合指标）"""
        if not self.word_burst_details:
            print("⚠️  没有创新指标数据，跳过创新指数计算")
            return
        
        # 收集所有指标值
        words = list(self.word_burst_details.keys())
        all_burst = [self.word_burst_details[w]['innovation_burst'] for w in words]
        all_ratio = [self.word_burst_details[w]['recent_early_ratio'] for w in words]
        all_growth = [self.word_burst_details[w]['max_growth_rate'] for w in words]
        all_variation = [self.word_burst_details[w]['coefficient_variation'] for w in words]
        all_peak = [self.word_burst_details[w]['peak_frequency'] for w in words]
        all_time = [self._calculate_time_factor(self.word_burst_details[w]['turning_point_year']) for w in words]
        
        # 标准化所有指标到[0,1]区间
        norm_burst = self._normalize_indicator(all_burst)
        norm_ratio = self._normalize_indicator(all_ratio)
        norm_growth = self._normalize_indicator(all_growth)
        norm_variation = self._normalize_indicator(all_variation)
        norm_peak = self._normalize_indicator(all_peak)
        norm_time = all_time  # 时间因子已经在[0,1]范围
        
        # 计算创新指数（加权公式）
        for i, word in enumerate(words):
            innovation_index = (
                0.35 * norm_burst[i] +      # 创新爆发度（35%）
                0.25 * norm_ratio[i] +      # 近期早期比（25%）
                0.15 * norm_growth[i] +     # 最大增长率（15%）
                0.10 * norm_variation[i] +  # 变异系数（10%）
                0.10 * norm_peak[i] +       # 峰值频率（10%）
                0.05 * norm_time[i]         # 时间因子（5%）
            )
            self.innovation_indices[word] = innovation_index
        
        print(f"✅ 创新指数计算完成，共 {len(self.innovation_indices)} 个词汇")
    
    def _normalize_indicator(self, values, method='minmax'):
        """标准化指标到[0,1]区间"""
        if not values:
            return []
        
        if method == 'minmax':
            min_val, max_val = min(values), max(values)
            if max_val > min_val:
                return [(x - min_val) / (max_val - min_val) for x in values]
            else:
                return [0] * len(values)
        elif method == 'zscore':
            mean_val, std_val = np.mean(values), np.std(values)
            if std_val > 0:
                normalized = [(x - mean_val) / std_val for x in values]
                # 转换到[0,1]区间
                min_norm, max_norm = min(normalized), max(normalized)
                if max_norm > min_norm:
                    return [(x - min_norm) / (max_norm - min_norm) for x in normalized]
                else:
                    return [0.5] * len(values)
            else:
                return [0.5] * len(values)
        
        return values
    
    def _calculate_time_factor(self, turning_point_year, current_year=2024):
        """计算时间因子：越近的拐点分数越高"""
        if turning_point_year is None or turning_point_year == 0:
            return 0
        
        years_ago = current_year - turning_point_year
        # 20年前的词汇时间因子为0，近期的为1
        return max(0, min(1, 1 - years_ago / 20))
    
    def get_top_words(self, n=50, sort_by='innovation'):
        """获取排名前N的词汇"""
        if sort_by == 'innovation' and self.innovation_indices:
            sorted_items = sorted(self.innovation_indices.items(), 
                                key=lambda x: x[1], reverse=True)
        elif sort_by == 'tfidf' and self.word_tfidf_scores:
            sorted_items = sorted(self.word_tfidf_scores.items(), 
                                key=lambda x: x[1], reverse=True)
        elif sort_by == 'frequency':
            sorted_items = sorted(self.word_frequencies.items(), 
                                key=lambda x: x[1], reverse=True)
        else:
            print(f"⚠️  排序方式 '{sort_by}' 不支持或数据不可用")
            return []
        
        return sorted_items[:n]
    
    def export_results(self, output_file='innovation_words.csv', sort_by='innovation', n=None):
        """导出分析结果（单一输出表）"""
        print(f"📤 导出分析结果到 {output_file}...")
        
        # 获取排序后的词汇
        if sort_by == 'innovation':
            if not self.innovation_indices:
                print("⚠️  创新指数数据不可用，改用TF-IDF排序")
                sort_by = 'tfidf'
            else:
                sorted_words = sorted(self.innovation_indices.items(), 
                                    key=lambda x: x[1], reverse=True)
        
        if sort_by == 'tfidf':
            if not self.word_tfidf_scores:
                print("⚠️  TF-IDF数据不可用，改用词频排序")
                sort_by = 'frequency'
            else:
                sorted_words = sorted(self.word_tfidf_scores.items(), 
                                    key=lambda x: x[1], reverse=True)
        
        if sort_by == 'frequency':
            sorted_words = sorted(self.word_frequencies.items(), 
                                key=lambda x: x[1], reverse=True)
        
        if n:
            sorted_words = sorted_words[:n]
        
        # 构建结果数据
        results = []
        for i, (word, score) in enumerate(sorted_words, 1):
            # 基本信息
            row = {
                'rank': i,
                'word': word,
                'frequency': self.word_frequencies.get(word, 0),
                'document_frequency': self.word_document_frequency.get(word, 0),
            }
            
            # TF-IDF分数
            if word in self.word_tfidf_scores:
                row['tfidf_score'] = round(self.word_tfidf_scores[word], 4)
            else:
                row['tfidf_score'] = 0
            
            # 创新指数
            if word in self.innovation_indices:
                row['innovation_index'] = round(self.innovation_indices[word], 4)
            else:
                row['innovation_index'] = 0
            
            # 详细创新指标
            if word in self.word_burst_details:
                details = self.word_burst_details[word]
                row.update({
                    'innovation_burst': round(details['innovation_burst'], 4),
                    'max_growth_rate': round(details['max_growth_rate'], 2),
                    'coefficient_variation': round(details['coefficient_variation'], 4),
                    'recent_early_ratio': round(details['recent_early_ratio'], 2),
                    'peak_frequency': details['peak_frequency'],
                    'turning_point_year': details['turning_point_year'],
                    'early_freq': details['early_freq'],
                    'recent_freq': details['recent_freq'],
                    'years_span': details['years_span'],
                    'first_year': details['first_year'],
                    'last_year': details['last_year']
                })
            else:
                # 填充默认值
                row.update({
                    'innovation_burst': 0,
                    'max_growth_rate': 0,
                    'coefficient_variation': 0,
                    'recent_early_ratio': 0,
                    'peak_frequency': 0,
                    'turning_point_year': 0,
                    'early_freq': 0,
                    'recent_freq': 0,
                    'years_span': 0,
                    'first_year': 0,
                    'last_year': 0
                })
            
            # 首次出现信息
            if word in self.first_occurrence_log:
                occurrence = self.first_occurrence_log[word]
                row.update({
                    'first_occurrence_paper': occurrence.get(self.unique_id_column, ''),
                    'first_occurrence_year': occurrence.get(self.time_columns[0], ''),
                    'analysis_text': occurrence.get('analysis_text', '')
                })
            else:
                row.update({
                    'first_occurrence_paper': '',
                    'first_occurrence_year': '',
                    'analysis_text': ''
                })
            
            results.append(row)
        
        # 保存结果
        df_results = pd.DataFrame(results)
        
        try:
            if PYARROW_AVAILABLE and output_file.endswith('.parquet'):
                df_results.to_parquet(output_file, index=False)
            else:
                # 确保使用CSV格式
                if output_file.endswith('.parquet'):
                    output_file = output_file.replace('.parquet', '.csv')
                df_results.to_csv(output_file, index=False, encoding='utf-8')
            
            print(f"✅ 结果已保存到 {output_file}")
            print(f"📊 导出记录数：{len(results)}")
            print(f"📊 排序方式：{sort_by}")
            
            # 显示前10个结果预览
            if results:
                print(f"\n📋 前10个{sort_by}排序结果预览：")
                for i in range(min(10, len(results))):
                    result = results[i]
                    print(f"{i+1:2d}. {result['word']:<15} "
                          f"创新指数:{result['innovation_index']:.4f} "
                          f"词频:{result['frequency']:,} "
                          f"TF-IDF:{result['tfidf_score']:.2f}")
            
        except Exception as e:
            print(f"❌ 保存文件失败：{e}")
        
        return df_results

def main():
    """主函数"""
    print("🚀 词汇创新分析器启动")
    print("=" * 60)
    
    # 配置参数
    config = {
        'csv_file_path': 'data.csv',  # 请修改为实际的数据文件路径
        'time_columns': ['year', 'volume', 'issue'],
        'info_columns': ['journal', 'author'],
        'text_column': None,  # 如果有专门的文本列，请设置
        'unique_id_column': 'paper_id',
        'language': 'en',
        'min_word_length': 3,
        'min_occurrence': 5,  # 最小出现次数
        'use_tfidf': True,
        'use_burst_filter': True,
        'innovation_burst_threshold': 0.1,  # 创新爆发度阈值
        'use_pos_filter': True,  # 词性过滤
        'extract_ngrams': False,  # 是否提取n-gram
    }
    
    # 创建分析器
    analyzer = WordFirstOccurrenceAnalyzer(**config)
    
    try:
        # 执行分析
        analyzer.analyze_first_occurrences()
        
        # 导出结果（单一输出表，按创新指数排序）
        results_df = analyzer.export_results(
            output_file='innovation_words.csv', 
            sort_by='innovation',
            n=1000  # 导出前1000个
        )
        
        print("\n" + "=" * 60)
        print("🎉 分析完成！")
        print(f"📊 总词汇数：{len(analyzer.word_frequencies):,}")
        print(f"📊 创新词汇数：{len(analyzer.innovation_indices):,}")
        print(f"📊 处理文档数：{analyzer.total_documents:,}")
        
        # 显示一些关键统计
        if analyzer.innovation_indices:
            top_innovation = max(analyzer.innovation_indices.items(), key=lambda x: x[1])
            print(f"🏆 最高创新指数：{top_innovation[0]} ({top_innovation[1]:.4f})")
        
        if 'covid' in analyzer.word_frequencies:
            covid_freq = analyzer.word_frequencies['covid']
            covid_doc_freq = analyzer.word_document_frequency.get('covid', 0)
            print(f"🔍 COVID统计验证：词频={covid_freq:,}, 文档频率={covid_doc_freq:,}")
        
    except Exception as e:
        print(f"❌ 分析失败：{e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
