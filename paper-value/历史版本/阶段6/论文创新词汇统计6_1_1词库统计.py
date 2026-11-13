import os
import re
import time
import sqlite3
from pathlib import Path
from collections import defaultdict
import pandas as pd
import spacy
from tqdm import tqdm
os.chdir(f'{os.path.dirname(os.path.abspath(__file__))}')
import yake

# =========================
# 配置区域（集中管理所有配置项）
# =========================
# 文件路径配置
INPUT_CSV = "data/raw/2026外文论文.csv"
STOPWORDS_FILE = "config/stopwords_en.txt"
OUTPUT_DIR = Path("output_6_vocabulary_statistics")
OUTPUT_DIR.mkdir(exist_ok=True)
DB_PATH = OUTPUT_DIR / "vocabulary.db"

# 批量处理配置
BATCH_WRITE_SIZE = 15000  # 保留用于统计（实际触发改为按条目数）
MEMORY_THRESHOLD = 500_000  # 超过50万条word/year或phrase/year条目时触发写入数据库
MAX_PAPERS_BEFORE_FLUSH = 20000  # 论文数阈值，防止内存无限增长
EXECUTEMANY_CHUNK_SIZE = 20000  # executemany分块大小，避免WAL变慢

# 文本处理配置
YAKE_TOKEN_THRESHOLD = 3000  # YAKE过滤的token数阈值（提升至3000，减少调用频率）
YAKE_PHRASE_THRESHOLD = 50  # 短语数量阈值，超过此值才调用YAKE

def load_stopwords():
    """加载停用词，转为小写集合"""
    stopwords = set()
    if os.path.exists(STOPWORDS_FILE):
        with open(STOPWORDS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                word = line.strip().lower()
                if word:
                    stopwords.add(word)
    return stopwords

def init_spacy_model():
    """初始化spaCy模型（禁用NER和parser以提升性能）"""
    try:
        nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])
        return nlp
    except OSError:
        print("错误：无法加载spaCy模型 'en_core_web_sm'")
        print("请运行: python -m spacy download en_core_web_sm")
        raise

# =========================
# 步骤2：数据库设计
# =========================
def create_database_tables(db_path):
    """创建数据库表结构（EAV模式：Entity-Attribute-Value）"""
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            # 添加超时参数，等待其他连接释放（最多等待30秒）
            conn = sqlite3.connect(str(db_path), timeout=30.0)
            
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = OFF")
            conn.execute("PRAGMA cache_size = -2000000")
            conn.execute("PRAGMA mmap_size = 30000000000")
            conn.execute("PRAGMA temp_store = MEMORY")
            
            # 如果数据库已存在且使用WAL模式，尝试checkpoint释放锁定和空间
            if Path(db_path).exists():
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    conn.commit()
                except sqlite3.OperationalError:
                    pass  # checkpoint失败不影响后续操作
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS word_year_freq (
                    word TEXT NOT NULL,
                    year INTEGER NOT NULL,
                    freq INTEGER DEFAULT 0,
                    PRIMARY KEY (word, year)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS phrase_year_freq (
                    phrase TEXT NOT NULL,
                    year INTEGER NOT NULL,
                    freq INTEGER DEFAULT 0,
                    PRIMARY KEY (phrase, year)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_papers (
                    paper_id TEXT PRIMARY KEY,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_processed_paper_id ON processed_papers(paper_id)")
            
            conn.commit()
            return conn
            
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                current_delay = retry_delay * (2 ** attempt)  # 指数退避
                print(f"数据库被锁定，等待 {current_delay} 秒后重试 ({attempt + 1}/{max_retries})...")
                time.sleep(current_delay)
                continue
            else:
                raise

# =========================
# 进度跟踪（断点续传支持）
# =========================
class PaperProgressTracker:
    def __init__(self, conn):
        self.conn = conn
        self._processed_set = self._load_processed_set()
        self._batch_buffer = []
        self._batch_size = 1000
    
    def _load_processed_set(self):
        """加载已处理的论文ID集合（优化：先检查数量，显示加载进度）"""
        # 先检查数量
        count_cur = self.conn.execute("SELECT COUNT(*) FROM processed_papers")
        total_count = count_cur.fetchone()[0]
        
        if total_count == 0:
            print("未找到已处理的论文记录")
            return set()
        
        print(f"正在加载已处理的论文记录（共 {total_count:,} 篇）...")
        
        # 分批加载，避免一次性加载过多数据到内存
        processed_set = set()
        batch_size = 100000
        
        if total_count <= batch_size:
            # 数据量小，直接加载
            cur = self.conn.execute("SELECT paper_id FROM processed_papers")
            processed_set = {row[0] for row in cur}
        else:
            # 数据量大，分批加载并显示进度
            offset = 0
            with tqdm(total=total_count, desc="加载已处理记录", unit="篇", mininterval=1.0) as pbar:
                while offset < total_count:
                    cur = self.conn.execute(
                        "SELECT paper_id FROM processed_papers LIMIT ? OFFSET ?",
                        (batch_size, offset)
                    )
                    batch = {row[0] for row in cur}
                    if not batch:  # 如果没有更多数据，退出
                        break
                    processed_set.update(batch)
                    offset += len(batch)
                    pbar.update(len(batch))
                    if len(batch) < batch_size:  # 如果返回的记录数少于批次大小，说明已读取完
                        break
        
        print(f"已加载 {len(processed_set):,} 篇已处理论文记录")
        return processed_set
    
    def _get_paper_id(self, paper_id, row_data=None):
        # 处理pandas StringDtype和Python str类型
        if paper_id is not None:
            paper_id_str = str(paper_id).strip()
            if paper_id_str:
                return paper_id_str
        if row_data:
            title = row_data.get('title', '') or ''
            abstract = row_data.get('abstract', '') or ''
            year = row_data.get('year', '') or ''
            combined = f"{title}|{abstract[:100]}|{year}".strip()
            if combined:
                return str(hash(combined))
        return None
    
    def is_processed(self, paper_id, row_data=None):
        paper_id = self._get_paper_id(paper_id, row_data)
        if paper_id is None:
            return False
        return paper_id in self._processed_set
    
    def mark_processed(self, paper_id, row_data=None):
        paper_id = self._get_paper_id(paper_id, row_data)
        if paper_id is None or paper_id in self._processed_set:
            return
        self._processed_set.add(paper_id)
        self._batch_buffer.append(paper_id)
        if len(self._batch_buffer) >= self._batch_size:
            self._flush_batch()
    
    def _flush_batch(self):
        if not self._batch_buffer:
            return
        sql = "INSERT OR IGNORE INTO processed_papers (paper_id) VALUES (?)"
        self.conn.executemany(sql, [(pid,) for pid in self._batch_buffer])
        self.conn.commit()
        self._batch_buffer = []
    
    def flush(self):
        self._flush_batch()

# =========================
# 文本处理配置（正则表达式、模板、白名单等）
# =========================
DASH_RE = re.compile(r'[—–]')
TITLE_SKIP_RE = re.compile(
    r'\b(purpose|methodology|results|goal|objective|aim|background|introduction|conclusion|methods?)[:;—–]\s*',
    flags=re.IGNORECASE
)
PUNCT_CLEAN_RE = re.compile(r'[;:]\s+')
SPACE_NORMALIZE_RE = re.compile(r'\s+')
WORD_PATTERN_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9\-\._]*$')  # 字母数字开头，支持科学术语如COVID-19, GPT-4, deep-learning-based

def clean_text(text):
    """清洗文本，移除会导致spaCy分词异常的符号"""
    if not text:
        return ""
    
    text = DASH_RE.sub(' ', text)
    text = TITLE_SKIP_RE.sub('', text)
    text = PUNCT_CLEAN_RE.sub(' ', text)
    text = SPACE_NORMALIZE_RE.sub(' ', text)
    
    return text.strip()

ALLOWED_CHARS = set(
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ'  # 大写字母
    'abcdefghijklmnopqrstuvwxyz'  # 小写字母
    '0123456789'                   # 数字
    ' \t\n\r'                     # 空白字符
    '-—–'                         # 连字符
    './·'                         # 点号
    '+×*'                         # 数学符号
    '/\\'                         # 斜杠
    '()[]{}'                      # 括号
    '%℃°'                         # 百分比和温度
    '_'                           # 下划线（科学术语如A_B）
    'αβγδεζηθικλμνξοπρστυφχψω'  # 希腊字母小写
    'ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ'  # 希腊字母大写
)

def has_punctuation(text):
    """判断文本是否包含不允许的标点符号"""
    for c in text:
        if c not in ALLOWED_CHARS:
            return True
    return False

def normalize_word_case(word):
    """智能大小写归一化"""
    if not word:
        return word
    
    has_letters = any(c.isalpha() for c in word)
    if not has_letters:
        return word.lower()
    
    if word.isupper():
        if len(word) <= 6:
            return word
        else:
            return word.lower()
    
    has_upper = any(c.isupper() for c in word)
    has_lower = any(c.islower() for c in word)
    if has_upper and has_lower:
        return word
    
    return word.lower()

def normalize_phrase_case(phrase):
    """智能短语大小写归一化"""
    if not phrase or not phrase.strip():
        return phrase.lower() if phrase else phrase
    
    words = phrase.split()
    if not words or all(not w.strip() for w in words):
        return phrase.lower()
    
    normalized_words = []
    for word in words:
        normalized_words.append(normalize_word_case(word))
    
    return " ".join(normalized_words)

def extract_words_and_phrases(doc, stopwords, doc_text=None):
    """一次遍历同时提取words和phrases"""
    processed_tokens = []
    text_list = []
    words = set()
    
    for token in doc:
        token_text = token.text
        text_list.append(token_text)  # 提前构建文本列表
        
        is_valid = (WORD_PATTERN_RE.match(token_text) and
                   len(token_text) >= 2 and 
                   token_text.lower() not in stopwords)
        
        if is_valid:
            normalized = normalize_word_case(token_text)
            words.add(normalized)  # 直接添加到words集合
            processed_tokens.append({
                'text': token_text,
                'norm': normalized,
                'pos': token.pos_,
                'is_valid': True
            })
        else:
            processed_tokens.append({
                'text': token_text,
                'norm': None,
                'pos': token.pos_,
                'is_valid': False
            })
    
    phrases = set()
    pos_sequences = [token['pos'] for token in processed_tokens]
    
    for i in range(len(processed_tokens)):
        for template_len in [2, 3, 4]:
            if i + template_len > len(processed_tokens):
                continue
            
            pos_key = tuple(pos_sequences[i:i+template_len])
            templates_dict = POS_TEMPLATES.get(template_len, {})
            
            if pos_key in templates_dict:
                template_status = templates_dict[pos_key]
                
                if template_status is False:
                    continue
                
                phrase_text = " ".join(text_list[i:i+template_len]).strip()
                
                if template_status == "filtered":
                    phrase_text_lower = phrase_text.lower()
                    has_propn = any(processed_tokens[i+j]['pos'] == "PROPN" for j in range(template_len))
                    if not has_propn:
                        adp_token = None
                        for j in range(template_len):
                            if processed_tokens[i+j]['pos'] == "ADP":
                                adp_token = processed_tokens[i+j]['text'].lower()
                                break
                        if adp_token and adp_token in ALLOWED_ADP_PHRASES:
                            if phrase_text_lower not in ALLOWED_ADP_PHRASES[adp_token]:
                                continue
                        else:
                            continue
                
                if not has_punctuation(phrase_text) and len(phrase_text) >= 3:
                    phrases.add(normalize_phrase_case(phrase_text))
    
    if doc_text and phrases and should_use_yake(doc) and len(phrases) >= YAKE_PHRASE_THRESHOLD:
        phrases = filter_phrases_with_yake(doc_text, phrases)
    
    return words, phrases

def extract_words(doc, stopwords):
    """提取单词，返回去重集合"""
    words, _ = extract_words_and_phrases(doc, stopwords)
    return words

POS_TEMPLATES = {
    2: {
        ("ADJ", "NOUN"): True,
        ("NOUN", "NOUN"): True,
        ("PROPN", "NOUN"): True,  # 专名+名词
        ("NOUN", "PROPN"): True,  # 名词+专名
        ("PROPN", "PROPN"): True,  # 专名+专名
        ("ADJ", "VERB"): True,  # 形容词+动词（如deep learning based）
        ("NOUN", "VERB"): True,  # 名词+动词（如machine learning driven）
    },
    3: {
        ("ADJ", "NOUN", "NOUN"): True,
        ("ADJ", "ADJ", "NOUN"): True,
        ("NOUN", "NOUN", "NOUN"): True,
        ("PROPN", "ADP", "PROPN"): True,  # 专名+介词+专名（如University of Oxford）
        ("ADJ", "PROPN", "NOUN"): True,  # 形容词+专名+名词
        # ("NOUN", "ADP", "NOUN"): False,  # 已禁用：噪声过大，白名单无法有效过滤
        ("ADJ", "NOUN", "VERB"): True,
        ("NOUN", "NOUN", "VERB"): True,
    },
    4: {
        ("ADJ", "ADJ", "NOUN", "NOUN"): True,
        ("NOUN", "NOUN", "NOUN", "NOUN"): True,
        ("PROPN", "PROPN", "PROPN", "PROPN"): True,  # 多词专名
        ("ADJ", "NOUN", "NOUN", "NOUN"): True,
        ("ADJ", "NOUN", "NOUN", "VERB"): True,
    }
}

ALLOWED_ADP_PHRASES = {
    "of": {"system of systems", "internet of things", "state of the art"},
    "for": {"model for prediction", "algorithm for optimization"},
    "in": {"method in machine learning"},
}

def is_allowed_adp_phrase(phrase_text, window):
    """检查ADP短语是否在白名单中"""
    if any(token.pos_ == "PROPN" for token in window):
        return True
    
    for token in window:
        if token.pos_ == "ADP":
            adp_text = token.text.lower()
            if adp_text in ALLOWED_ADP_PHRASES:
                if phrase_text in ALLOWED_ADP_PHRASES[adp_text]:
                    return True
            break  # 只检查第一个ADP token
    
    return False

_yake_extractor = None

def get_yake_extractor():
    """获取全局YAKE提取器"""
    global _yake_extractor
    if _yake_extractor is None:
        _yake_extractor = yake.KeywordExtractor(
            lan="en",
            n=3,
            dedupLim=0.7,
            top=100,
            features=None
        )
    return _yake_extractor

def should_use_yake(doc):
    """判断是否应该使用YAKE（基于token数，而非字符数）"""
    return len(doc) >= YAKE_TOKEN_THRESHOLD

def filter_phrases_with_yake(text, phrases):
    """使用YAKE算法过滤低价值短语"""
    if not phrases:
        return phrases
    
    kw_extractor = get_yake_extractor()
    if kw_extractor is None:
        return phrases
    
    keywords = kw_extractor.extract_keywords(text)
    yake_set = {phrase.lower().strip() for phrase, score in keywords}
    filtered_phrases = {p for p in phrases if p in yake_set}
    
    return filtered_phrases if filtered_phrases else phrases

def extract_all_phrases(doc, doc_text=None, stopwords=None):
    """提取短语，返回去重集合"""
    if stopwords is None:
        stopwords = set()
    _, phrases = extract_words_and_phrases(doc, stopwords, doc_text)
    return phrases

def batch_write_to_db(conn, word_freq, phrase_freq):
    """批量写入数据库（优化：大数据量时使用临时表批量合并）"""
    if not word_freq and not phrase_freq:
        return
    
    with conn:
        cursor = conn.cursor()
        
        if word_freq:
            word_values = []
            for word, year_dict in word_freq.items():
                for year, freq in year_dict.items():
                    if freq > 0:
                        word_values.append((word, year, freq))
            
            if word_values:
                if len(word_values) > 50000:
                    cursor.execute("DROP TABLE IF EXISTS temp_word_year_freq")
                    cursor.execute("""
                        CREATE TEMP TABLE temp_word_year_freq (
                            word TEXT NOT NULL,
                            year INTEGER NOT NULL,
                            freq INTEGER DEFAULT 0,
                            PRIMARY KEY (word, year)
                        )
                    """)
                    for i in range(0, len(word_values), EXECUTEMANY_CHUNK_SIZE):
                        chunk = word_values[i:i + EXECUTEMANY_CHUNK_SIZE]
                        cursor.executemany(
                            "INSERT INTO temp_word_year_freq (word, year, freq) VALUES (?, ?, ?)",
                            chunk
                        )
                    cursor.execute("""
                        INSERT OR IGNORE INTO word_year_freq (word, year, freq)
                        SELECT word, year, freq FROM temp_word_year_freq
                    """)
                    cursor.execute("""
                        UPDATE word_year_freq
                        SET freq = freq + (
                            SELECT freq FROM temp_word_year_freq 
                            WHERE temp_word_year_freq.word = word_year_freq.word 
                            AND temp_word_year_freq.year = word_year_freq.year
                        )
                        WHERE EXISTS (
                            SELECT 1 FROM temp_word_year_freq 
                            WHERE temp_word_year_freq.word = word_year_freq.word 
                            AND temp_word_year_freq.year = word_year_freq.year
                        )
                    """)
                    cursor.execute("DROP TABLE temp_word_year_freq")
                else:
                    sql = """
                        INSERT INTO word_year_freq (word, year, freq)
                        VALUES (?, ?, ?)
                        ON CONFLICT(word, year) DO UPDATE SET freq = freq + excluded.freq
                    """
                    for i in range(0, len(word_values), EXECUTEMANY_CHUNK_SIZE):
                        chunk = word_values[i:i + EXECUTEMANY_CHUNK_SIZE]
                        cursor.executemany(sql, chunk)
        
        if phrase_freq:
            phrase_values = []
            for phrase, year_dict in phrase_freq.items():
                for year, freq in year_dict.items():
                    if freq > 0:
                        phrase_values.append((phrase, year, freq))
            
            if phrase_values:
                if len(phrase_values) > 50000:
                    cursor.execute("DROP TABLE IF EXISTS temp_phrase_year_freq")
                    cursor.execute("""
                        CREATE TEMP TABLE temp_phrase_year_freq (
                            phrase TEXT NOT NULL,
                            year INTEGER NOT NULL,
                            freq INTEGER DEFAULT 0,
                            PRIMARY KEY (phrase, year)
                        )
                    """)
                    for i in range(0, len(phrase_values), EXECUTEMANY_CHUNK_SIZE):
                        chunk = phrase_values[i:i + EXECUTEMANY_CHUNK_SIZE]
                        cursor.executemany(
                            "INSERT INTO temp_phrase_year_freq (phrase, year, freq) VALUES (?, ?, ?)",
                            chunk
                        )
                    cursor.execute("""
                        INSERT OR IGNORE INTO phrase_year_freq (phrase, year, freq)
                        SELECT phrase, year, freq FROM temp_phrase_year_freq
                    """)
                    cursor.execute("""
                        UPDATE phrase_year_freq
                        SET freq = freq + (
                            SELECT freq FROM temp_phrase_year_freq 
                            WHERE temp_phrase_year_freq.phrase = phrase_year_freq.phrase 
                            AND temp_phrase_year_freq.year = phrase_year_freq.year
                        )
                        WHERE EXISTS (
                            SELECT 1 FROM temp_phrase_year_freq 
                            WHERE temp_phrase_year_freq.phrase = phrase_year_freq.phrase 
                            AND temp_phrase_year_freq.year = phrase_year_freq.year
                        )
                    """)
                    cursor.execute("DROP TABLE temp_phrase_year_freq")
                else:
                    sql = """
                        INSERT INTO phrase_year_freq (phrase, year, freq)
                        VALUES (?, ?, ?)
                        ON CONFLICT(phrase, year) DO UPDATE SET freq = freq + excluded.freq
                    """
                    for i in range(0, len(phrase_values), EXECUTEMANY_CHUNK_SIZE):
                        chunk = phrase_values[i:i + EXECUTEMANY_CHUNK_SIZE]
                        cursor.executemany(sql, chunk)

# =========================
# 步骤4：流式处理主循环（合并步骤3和4）
# =========================
def process_papers_streaming(csv_path, nlp, stopwords, conn):
    """流式处理论文，单次循环中提取并立即统计"""
    
    # 初始化进度跟踪器（断点续传支持）
    print("正在初始化进度跟踪器...")
    paper_tracker = PaperProgressTracker(conn)
    processed_count = len(paper_tracker._processed_set)
    if processed_count > 0:
        print(f"✓ 检测到断点续传：已处理 {processed_count:,} 篇论文，从此位置继续...")
    else:
        print("✓ 未检测到已处理记录，将从开始处理")
    
    # 初始化内存统计字典
    word_freq = defaultdict(lambda: defaultdict(int))
    phrase_freq = defaultdict(lambda: defaultdict(int))
    
    # 实时计数器（避免每次遍历字典计算条目数）
    total_entries = 0
    
    # CSV读取配置
    usecols = ['id', 'title', 'abstract', 'keyword', 'pub_year']
    dtype = {'id': 'string', 'title': 'string', 'abstract': 'string', 
             'keyword': 'string', 'pub_year': 'Int64'}
    
    paper_count = 0
    total_processed = 0
    skipped_count = 0
    scanned_count = 0  # 已扫描的论文数（包括跳过的）
    
    # 创建reader（仅读取一次CSV）
    print("开始处理论文...")
    print("正在读取CSV文件...")
    reader = pd.read_csv(csv_path, usecols=usecols, dtype=dtype, 
                        chunksize=50000, encoding_errors="ignore")
    
    # 初始化进度条，设置初始值为已处理数量（显示已处理的论文总数）
    pbar = tqdm(desc="处理论文", unit="篇", initial=processed_count, 
                mininterval=1.0, maxinterval=5.0)
    
    try:
        for chunk_idx, chunk in enumerate(reader, start=1):
            print(f"处理第 {chunk_idx} 个chunk（{len(chunk)} 篇论文）...")
            # 重命名列
            chunk = chunk.rename(columns={
                'id': 'paper_id',
                'title': 'title',
                'abstract': 'abstract',
                'keyword': 'keyword',
                'pub_year': 'year'
            }).fillna('')
            
            # 合并文本并清洗（跳过已处理的论文）
            texts = []
            rows_data = []
            for _, row in chunk.iterrows():
                scanned_count += 1
                paper_id = row['paper_id']
                row_data_dict = {
                    'title': row['title'],
                    'abstract': row['abstract'],
                    'year': row['year']
                }
                
                # 使用统一的is_processed方法检查，确保逻辑一致性
                # 注意：pandas的string类型不是Python str，所以不能直接用isinstance检查
                if paper_tracker.is_processed(paper_id, row_data_dict):
                    skipped_count += 1
                    # 跳过已处理的论文时不更新进度条，避免速度计算异常
                    # 进度条应该只反映实际处理的论文数
                    continue
                
                merged_text = f"{row['title']} {row['keyword']} {row['abstract']}".strip()
                if merged_text:
                    # 清洗文本，移除会导致spaCy分词异常的符号
                    cleaned_text = clean_text(merged_text)
                    if cleaned_text:
                        texts.append(cleaned_text)
                        rows_data.append({
                            'year': row['year'],
                            'paper_id': paper_id,
                            'row_data': row_data_dict
                        })
                    else:
                        # 文本清洗后为空，标记为已处理
                        paper_tracker.mark_processed(paper_id, row_data_dict)
                        pbar.update(1)
                else:
                    # 合并文本为空，标记为已处理
                    paper_tracker.mark_processed(paper_id, row_data_dict)
                    pbar.update(1)
            
            # spaCy批量处理（batch_size=512优化处理速度）
            if texts:
                docs = list(nlp.pipe(texts, batch_size=512))
                
                # 单次循环：提取并立即统计（每篇论文每个词/短语只算1次）
                for doc, row_data, text in zip(docs, rows_data, texts):
                    year = row_data['year']
                    paper_id = row_data['paper_id']
                    row_data_dict = row_data.get('row_data', {})
                    
                    # 正确处理pandas.Int64的NaN
                    if pd.isna(year):
                        paper_tracker.mark_processed(paper_id, row_data_dict)
                        pbar.update(1)
                        continue
                    
                    year = int(year)
                    
                    words, phrases = extract_words_and_phrases(doc, stopwords, doc_text=text)
                    
                    for word in words:
                        if word_freq[word][year] == 0:
                            total_entries += 1
                        word_freq[word][year] += 1
                    for phrase in phrases:
                        if phrase_freq[phrase][year] == 0:
                            total_entries += 1
                        phrase_freq[phrase][year] += 1
                    
                    paper_tracker.mark_processed(paper_id, row_data_dict)
                    
                    paper_count += 1
                    total_processed += 1
                    
                    should_flush = False
                    if paper_count % 100 == 0 or paper_count >= BATCH_WRITE_SIZE:
                        if (total_entries >= MEMORY_THRESHOLD or 
                            paper_count >= MAX_PAPERS_BEFORE_FLUSH or 
                            paper_count >= BATCH_WRITE_SIZE):
                            should_flush = True
                    
                    if should_flush:
                        batch_write_to_db(conn, word_freq, phrase_freq)
                        paper_tracker.flush()
                        word_freq.clear()
                        phrase_freq.clear()
                        total_entries = 0
                        paper_count = 0
                    
                    pbar.update(1)
    finally:
        pbar.close()
    
    if word_freq or phrase_freq:
        batch_write_to_db(conn, word_freq, phrase_freq)
    
    paper_tracker.flush()
    
    if skipped_count > 0:
        print(f"处理完成，共扫描 {scanned_count:,} 篇论文，处理 {total_processed:,} 篇新论文，跳过 {skipped_count:,} 篇已处理论文")
    else:
        print(f"处理完成，共处理 {total_processed:,} 篇论文")

def create_indexes(conn):
    """创建索引"""
    conn.execute("CREATE INDEX IF NOT EXISTS idx_word ON word_year_freq(word)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_phrase ON phrase_year_freq(phrase)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_word_year ON word_year_freq(year)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_phrase_year ON phrase_year_freq(year)")
    conn.commit()

# =========================
# 主函数
# =========================
def main():
    print("=" * 60)
    print("词库统计系统")
    print("=" * 60)
    
    # 步骤1：配置和初始化
    print("\n[步骤1] 配置和初始化...")
    stopwords = load_stopwords()
    print(f"已加载 {len(stopwords)} 个停用词")
    
    nlp = init_spacy_model()
    print("spaCy模型加载成功")
    
    # 步骤2：数据库设计
    print("\n[步骤2] 创建数据库...")
    conn = create_database_tables(DB_PATH)
    print(f"数据库已创建: {DB_PATH}")
    
    # 步骤3：文本处理函数（已在步骤4中调用）
    print("\n[步骤3] 文本处理函数已就绪（extract_words_and_phrases等）")
    
    # 步骤4：流式处理主循环（内部调用步骤3的文本处理函数和步骤5的批量写入函数）
    print("\n[步骤4] 开始流式处理...")
    process_papers_streaming(INPUT_CSV, nlp, stopwords, conn)
    
    # 步骤5：批量写入数据库（已在步骤4中自动调用）
    print("\n[步骤5] 批量写入数据库已完成（在流式处理过程中自动执行）")
    
    # 步骤6：创建索引（在写入完成后创建，提升写入性能）
    print("\n[步骤6] 创建索引...")
    create_indexes(conn)
    print("索引创建完成")
    
    # 关闭连接
    conn.close()
    print("\n处理完成！")

if __name__ == "__main__":
    main()

