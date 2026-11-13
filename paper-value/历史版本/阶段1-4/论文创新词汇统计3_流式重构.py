import os
import pandas as pd
import numpy as np
import re
import pickle
from collections import Counter
import spacy
from tqdm import tqdm
from sklearn.preprocessing import MinMaxScaler

# =============================================================================
# 基本环境配置
# =============================================================================
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'
os.chdir(f'{os.path.dirname(os.path.abspath(__file__))}')

config = {
    'csv_file_path': '2025外文论文全字段.csv',
    'output_file': 'data/raw/analysis_results.csv',
    'temp_dir': './temp',
    'time_columns': ['出版年'],
    'info_columns': ['期刊名称', '标题', '关键词', 'KeywordsPlus', '摘要'],
    'unique_id_column': '入藏号',
    'language': 'en',
    'min_word_length': 2,
    'min_occurrence': 1,
    'chunk_size': 500000,
    'num_processes': 6,
    'batch_size': 1500,
    'stopword_files': [
        'config/stopwords_en.txt',
        'config/stopwords_cn.txt',
        'config/structural_stopwords.txt',
        'config/scientific_stopwords_doc_freq.txt'
    ],
    'use_tfidf': True,
    'use_pos_filter': True,
    'use_burst_analysis': True,
    'extract_ngrams': True,
    'use_phrase_extraction': False,
    'ngram_range': (2, 3),
    'innovation_burst_threshold': 0.15,
    'min_years_span': 2,
    'turning_point_growth_factor': 3.0,
    'turning_point_min_freq': 100,
    'recent_window_years': 5,
    'exclude_last_n_years': 1,
    'doc_freq_threshold': 0.9,
    'total_rows': 9167774
}
config['usecols'] = [config['unique_id_column']] + config['time_columns'] + config['info_columns']
config['dtype'] = {col: ('float' if col in config['time_columns'] else 'string') for col in config['usecols']}

# =============================================================================
# 正则预编译
# =============================================================================
RE_HTML     = re.compile(r"<[^>]+>")  
RE_CONTROL  = re.compile(r"[\x00-\x1f\x7f-\x9f]")  
RE_DASH     = re.compile(r"\s*[-–—]\s*")  
RE_CONCAT_EN = re.compile(r"([A-Za-z0-9]{4,})(the|this|our|and|or|of|in|to|for|with|from|by)(\b)", re.I)  
RE_SAFE     = re.compile(r"[^A-Za-z0-9\u00C0-\u024F\u0370-\u03FF\u4e00-\u9fff\-\._/+#%°℃µμ:@' ]")  
RE_WS       = re.compile(r"\s+") 

# =============================================================================
# 工具函数
# =============================================================================
def read_and_merge_info(config):
    """分块读取CSV"""
    reader = pd.read_csv(
        config['csv_file_path'],
        chunksize=config['chunk_size'],
        usecols=config['usecols'],
        encoding='utf-8',
        dtype=config['dtype'],
        low_memory=False
    )
    for chunk in reader:
        chunk['merged_info'] = chunk[config['info_columns']].apply(
            lambda row: ' '.join(row.dropna().astype(str)), axis=1
        )
        chunk.drop(columns=config['info_columns'], inplace=True)
        yield chunk

def load_stopwords():
    """加载停用词"""
    stop_words = set()
    for stopword_file in config['stopword_files']:
        if os.path.exists(stopword_file):
            with open(stopword_file, 'r', encoding='utf-8') as f:
                stop_words.update(line.strip() for line in f if line.strip() and not line.startswith('#'))
    return stop_words

def clean_dataframe_texts(df: pd.DataFrame, column: str) -> pd.Series:
    arr = df[column].fillna("").astype(str).str.strip().to_numpy(copy=False)
    arr = np.array([x.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"') for x in arr], dtype=object)
    arr = np.array([RE_HTML.sub(" ", x) for x in arr], dtype=object)
    arr = np.array([RE_CONTROL.sub(" ", x) for x in arr], dtype=object)
    arr = np.array([RE_CONCAT_EN.sub(r"\1 \2", x) for x in arr], dtype=object)
    arr = np.array([RE_DASH.sub("-", x) for x in arr], dtype=object)
    arr = np.array([RE_SAFE.sub(" ", x) for x in arr], dtype=object)
    arr = np.array([RE_WS.sub(" ", x).strip() for x in arr], dtype=object)
    return pd.Series(arr, index=df.index)

def init_spacy_models(use_gpu_flag=True, language=config['language']):
    """初始化分词模型"""
    if use_gpu_flag:
        spacy.require_gpu()
    if language == 'zh':
        nlp = spacy.load("zh_core_web_trf", disable=["parser", "ner", "tagger", "lemmatizer", "textcat"])
    else:
        nlp = spacy.load("en_core_web_trf", disable=["parser", "ner", "tagger", "lemmatizer", "textcat"])
    return nlp

def spacy_tokenize_chunk(df, text_col, nlp, batch_size=256):
    df = df.copy()
    texts = df[text_col].astype(str).tolist()
    tokens_list = []
    for doc in tqdm(nlp.pipe(texts, batch_size=batch_size), total=len(texts), desc="Tokenizing"):
        tokens_list.append([token.text for token in doc])
    df[text_col] = tokens_list
    return df

def compute_token_stats_stream(df: pd.DataFrame,
                               token_col: str = 'merged_info',
                               id_col: str = config['unique_id_column'],
                               time_col: str = config['time_columns'][0],
                               sparse: bool = True) -> pd.DataFrame:
    """流式计算分词统计"""
    tf, df_counts, first_doc, time_counts = Counter(), Counter(), {}, Counter()
    cols = [id_col, token_col] + ([time_col] if time_col else [])
    for row in df.loc[:, cols].itertuples(index=False, name=None):
        if time_col:
            doc_id, tokens, tval = row
        else:
            doc_id, tokens = row
            tval = None
        if not tokens:
            continue
        tokens_clean = [t for t in tokens if t is not None]
        for tok in tokens_clean:
            tf[tok] += 1
            if tok not in first_doc:
                first_doc[tok] = doc_id
        for tok in set(tokens_clean):
            df_counts[tok] += 1
        if time_col and tval is not None and not pd.isna(tval):
            for tok in tokens_clean:
                time_counts[(tok, tval)] += 1

    tokens_all = list(tf.keys())
    result = pd.DataFrame({
        "token": tokens_all,
        "first_doc": [first_doc[t] for t in tokens_all],
        "tf": [tf[t] for t in tokens_all],
        "df": [df_counts[t] for t in tokens_all],
    })

    if time_col and time_counts:
        s = pd.Series(time_counts).unstack(level=1).fillna(0)
        s = s.rename_axis('token').reset_index()
        time_cols = [c for c in s.columns if c != 'token']
        dt = pd.to_datetime(time_cols, errors="coerce")
        if not dt.isna().all():
            sorted_cols = [time_cols[i] for i in np.argsort(dt.values)]
        else:
            num = pd.to_numeric(time_cols, errors="coerce")
            sorted_cols = [time_cols[i] for i in np.argsort(num.values)] if not np.isnan(num).all() else sorted(time_cols)
        s = s[['token'] + sorted_cols]
        if sparse:
            s[sorted_cols] = s[sorted_cols].astype(pd.SparseDtype("int64", 0))
        result = result.merge(s, on='token', how='left').fillna(0)

    result["tf"] = pd.to_numeric(result["tf"], downcast="integer")
    result["df"] = pd.to_numeric(result["df"], downcast="integer")
    fixed_cols = ["token", "first_doc", "tf", "df"]
    if time_col:
        time_value_cols = [c for c in result.columns if c not in fixed_cols]
        result = result[fixed_cols + sorted(time_value_cols)]
    result = result.reset_index(drop=True)
    return result

def update_global_stats(global_stats: dict, chunk_stats: pd.DataFrame, stop_words: set) -> None:
    """累计全局统计"""
    chunk_stats = chunk_stats[chunk_stats['token'].str.match(r'^[\u4e00-\u9fffA-Za-z\-]+$')]
    chunk_stats = chunk_stats[~chunk_stats['token'].str.isdigit()]
    def is_valid_token(t):
        if t.isascii():
            return len(t) >= 3
        return True
    chunk_stats = chunk_stats[chunk_stats['token'].apply(is_valid_token)]
    chunk_stats = chunk_stats[~chunk_stats['token'].str.lower().isin({w.lower() for w in stop_words})]
    for _, row in chunk_stats.iterrows():
        token = row["token"]
        if token not in global_stats:
            global_stats[token] = {"tf": 0, "df": 0, "first_doc": row["first_doc"]}
        g = global_stats[token]
        g["tf"] += row["tf"]
        g["df"] += row["df"]
        for col in chunk_stats.columns:
            if col not in ["token", "first_doc", "tf", "df"]:
                g[col] = g.get(col, 0) + row[col]

def export_global_stats(global_stats: dict, total_docs: int, output_file: str):
    df = pd.DataFrame.from_dict(global_stats, orient='index')
    df.index.name = 'token'
    df = df[~df.index.str.lower().isin({w.lower() for w in stop_words})]
    df = df[~df.index.str.fullmatch(r'[\u4e00-\u9fff]+')]
    df.reset_index(inplace=True)
    df['TF-IDF'] = df['tf']/df['df'] * np.log((total_docs + 1) / (df['df'] + 1))
    time_cols = [c for c in df.columns if c not in ['token', 'first_doc', 'tf', 'df', 'TF-IDF']]
    if time_cols:
        year_freq = df[time_cols].values.astype(float)
        df['maximum_growth_rate'] = np.max(np.diff(year_freq, axis=1), axis=1)
        df['cv'] = np.std(year_freq, axis=1) / (np.mean(year_freq, axis=1) + 1e-9)
        df['recent_early_ratio'] = [
            row[-len(row)//2:].sum() / (row[:len(row)//2].sum() + 1e-9)
            for row in year_freq
        ]
        df['peak_freq'] = year_freq.max(axis=1)
        df['inflection_year'] = [time_cols[i] for i in np.argmax(year_freq, axis=1)]
    indicators = ['maximum_growth_rate', 'recent_early_ratio', 'cv', 'peak_freq']
    df[indicators] = df[indicators].fillna(0)
    scaler = MinMaxScaler()
    scaled = scaler.fit_transform(df[indicators])
    weights = np.array([0.4, 0.3, 0.15, 0.15])
    df['innovation_score'] = (scaled * weights).sum(axis=1)
    df = df.sort_values(by=['innovation_score', 'df'], ascending=[False, False])
    ordered_cols = ['token', 'tf', 'df', 'TF-IDF', 'first_doc', 'innovation_score',
                    'maximum_growth_rate', 'cv', 'recent_early_ratio', 'peak_freq', 'inflection_year'] + time_cols
    df = df[ordered_cols]
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"已保存 {output_file}")

# =============================================================================
# 断点续跑功能
# =============================================================================
os.makedirs(config['temp_dir'], exist_ok=True)
PROGRESS_FILE = os.path.join(config['temp_dir'], 'progress.pkl')
GLOBAL_STATS_FILE = os.path.join(config['temp_dir'], 'global_stats.pkl')

def save_progress(chunk_idx, global_stats):
    with open(PROGRESS_FILE, 'wb') as f:
        pickle.dump(chunk_idx, f)
    with open(GLOBAL_STATS_FILE, 'wb') as f:
        pickle.dump(global_stats, f, protocol=pickle.HIGHEST_PROTOCOL)

def load_progress():
    if os.path.exists(PROGRESS_FILE) and os.path.exists(GLOBAL_STATS_FILE):
        with open(PROGRESS_FILE, 'rb') as f:
            chunk_idx = pickle.load(f)
        with open(GLOBAL_STATS_FILE, 'rb') as f:
            global_stats = pickle.load(f)
        print(f"[断点续跑] 从第 {chunk_idx + 1} 块继续处理...")
        return chunk_idx + 1, global_stats
    return 0, {}

# =============================================================================
# 主流程：支持断点续跑
# =============================================================================
stop_words = load_stopwords()
nlp = init_spacy_models(use_gpu_flag=True, language=config['language'])
start_chunk, global_stats = load_progress()

for chunk_idx, i in enumerate(read_and_merge_info(config)):
    if chunk_idx < start_chunk:
        continue
    print(f"\n=== 处理第 {chunk_idx} 块 ===")
    i['merged_info'] = clean_dataframe_texts(i, 'merged_info')
    i = spacy_tokenize_chunk(i, 'merged_info', nlp, batch_size=config['batch_size'])
    i = compute_token_stats_stream(i)
    update_global_stats(global_stats, i, stop_words)
    save_progress(chunk_idx, global_stats)
    print(f"[保存进度] 已完成第 {chunk_idx} 块")

export_global_stats(global_stats, config['total_rows'], config['output_file'])
os.remove(PROGRESS_FILE)
os.remove(GLOBAL_STATS_FILE)
print("🎯 全部完成，已删除断点文件。")
