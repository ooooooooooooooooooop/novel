"""
精炼版停用词生成器
修复效率问题：单次文件访问、统一扫描、真实词频、逻辑修正
"""

import re
import argparse
from pathlib import Path
from typing import Dict, List, Set, Iterator
from collections import Counter
import gc

import pandas as pd
import numpy as np
import os

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    print("⚠️  未安装tqdm，将使用简单进度显示")

# 项目根（脚本在 tools/ 或根目录均可）
_ROOT = Path(__file__).resolve().parent
if _ROOT.name == "tools":
    _ROOT = _ROOT.parent
os.chdir(_ROOT)

# 统一复合正则（一次扫描所有模式）
UNIFIED_PATTERN = re.compile(
    r'(?P<greek>[α-ωΑ-Ω]+)|'
    r'(?P<subscript>\w+[₀-₉⁰-⁹]+)|'
    r'(?P<hyphen>[a-zA-Z]+-[a-zA-Z]+)|'
    r'(?P<stat>p-value|t-test|χ²|r²)|'
    r'(?P<word>[a-zA-Z]{3,20})',
    re.IGNORECASE
)

# 文本清理（提前预编译）
CLEAN_PATTERN = re.compile(r'[^\w\s\-α-ωΑ-Ω]+')

CORE_STOPWORDS = frozenset({
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to',
    'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be',
    'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did',
    'will', 'would', 'could', 'should', 'may', 'might', 'can',
    'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she',
    'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them'
})

class RefinedGenerator:
    """精炼版生成器"""
    
    def __init__(self, sample_size=None):
        self.lemmatizer = self._init_lemmatizer()
        self.lemma_cache = {}
        self.sample_size = sample_size
    
    def _init_lemmatizer(self):
        """初始化词形还原器"""
        try:
            import nltk
            from nltk.stem import WordNetLemmatizer
            
            for resource, path in [('wordnet', 'corpora/wordnet'), ('punkt', 'tokenizers/punkt')]:
                try:
                    nltk.data.find(path)
                except LookupError:
                    nltk.download(resource, quiet=True)
            
            return WordNetLemmatizer()
        except:
            return None
    
    def generate(self, papers_file: str, stopwords_file: str, output_file: str, custom_columns: List[str] = None, max_stopwords: int = None, doc_freq_percentile: int = 85):
        """主流程 - 基于文档频率识别通用词"""
        print("⚡ 文档频率法停用词生成器")

        if self.lemmatizer:
            print("✅ 词形还原器已启用")
        else:
            print("⚠️  词形还原器未启用，将使用原始词形")
            
        # 步骤1：智能加载
        text_chunks = self._smart_load(papers_file, custom_columns)
        print("加载完成")
        
        # 步骤2：统一扫描（追踪文档）
        domain_tokens, word_to_docs = self._unified_scan(text_chunks)
        total_papers = max(max(doc_ids) for doc_ids in word_to_docs.values()) + 1 if word_to_docs else 0
        print(f"分词完成: {len(domain_tokens):,} 词, {total_papers:,} 论文")
        
        # 步骤3：文档频率统计
        candidates = self._document_frequency_stats(domain_tokens, word_to_docs, total_papers, stopwords_file, doc_freq_percentile)
        print(f"统计完成: {len(candidates)} 候选")
        
        # 显示前10个通用词详情
        if candidates:
            print(f"\n🔝 Top 10 通用词:")
            for i, c in enumerate(candidates[:10], 1):
                print(f"  {i}. {c['word']:15} | 评分={c['score']:.2f} | 文档占比={c['doc_ratio']:.1%} | 词频={c['freq']:,}")
        
        # 步骤4：简单筛选
        new_stopwords = self._simple_filtering(candidates, max_words=max_stopwords)
        print(f"\n筛选完成: {len(new_stopwords)} 新词")
        
        # 调试：检查特定词是否进入最终停用词表
        debug_words = [ "study", "model", "analysis", "data", "address", "method", "based", "author", "journal", "performance", "patients", "energy", "reprint", "proposed", "time", "control", "methods", "properties", "cells", "water", "compared", "effects", "design", "paper", "process", "surface", "systems", "development", "studies", "potential", "treatment", "cell", "temperature", "structure", "models", "approach", "materials", "cancer", "risk", "network", "increased", "power", "rate", "conditions", "learning", "activity", "impact", "disease", "expression", "health", "growth", "management", "quality", "factors", "stress", "parameters", "response", "role", "including", "review", "current", "increase"] 
        print(f"\n🔍 调试：检查常见科研词是否进入停用词表")
        for word in debug_words:
            found_in_candidates = next((c for c in candidates if c['word'] == word), None)
            in_output = word in new_stopwords
            
            if found_in_candidates:
                rank = candidates.index(found_in_candidates) + 1
                status = "✅ 已加入" if in_output else "❌ 未加入"
                print(f"  '{word}': {status} | 排名{rank} | 文档占比={found_in_candidates['doc_ratio']:.2%} | 词频={found_in_candidates['freq']:,}")
            else:
                print(f"  '{word}': ⚠️  未进入候选（词频<{MIN_FREQ}或已在基础停用词中）")
        
        # 步骤5：清洁输出
        self._clean_output(new_stopwords, stopwords_file, output_file)
        print(f"输出完成: {output_file}")
        
        if new_stopwords:
            print(f"新增前6个: {new_stopwords[:6]}")
            print(f"新增后6个: {new_stopwords[-6:]}")
    
    def _smart_load(self, papers_file: str, custom_columns: List[str] = None) -> Iterator[tuple]:
        """智能加载 - 返回(论文ID, 文本)"""
        file_path = Path(papers_file)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {papers_file}")
        
        encoding = None
        with open(file_path, 'rb') as raw_file:
            for enc in ['utf-8', 'gbk', 'latin1']:
                try:
                    raw_file.seek(0)
                    sample = raw_file.read(10000).decode(enc)
                    encoding = enc
                    break
                except UnicodeDecodeError:
                    continue
        
        if not encoding:
            raise ValueError("无法解码文件")
        
        sample_df = pd.read_csv(file_path, encoding=encoding, nrows=50)
        
        if custom_columns:
            available_cols = [col for col in custom_columns if col in sample_df.columns]
            if not available_cols:
                raise ValueError(f"自定义列不存在于CSV中。可用列: {list(sample_df.columns)}")
            text_columns = available_cols
            print(f"📋 使用自定义列: {text_columns}")
        else:
            text_columns = self._detect_text_columns_once(sample_df)
            print(f"🔍 自动检测列: {text_columns}")
        
        if not text_columns:
            raise ValueError("未检测到文本列")
        
        if self.sample_size:
            print(f"🎯 采样模式: 仅处理前 {self.sample_size:,} 篇论文")
        
        chunk_iter = pd.read_csv(
            file_path, encoding=encoding, chunksize=CHUNK_SIZE,
            usecols=text_columns, on_bad_lines='skip'
        )
        
        paper_id = 0
        pbar = tqdm(desc="📖 加载论文", unit="篇") if TQDM_AVAILABLE else None
        
        for chunk in chunk_iter:
            for idx in range(len(chunk)):
                if self.sample_size and paper_id >= self.sample_size:
                    if TQDM_AVAILABLE:
                        pbar.close()
                    return
                
                row_texts = []
                for col in text_columns:
                    if col in chunk.columns:
                        cell_value = chunk[col].iloc[idx]
                        if pd.notna(cell_value):
                            text = str(cell_value).strip()
                            if len(text) > 10:
                                row_texts.append(text)
                
                if row_texts:
                    combined_text = ' '.join(row_texts)
                    yield (paper_id, combined_text)
                    paper_id += 1
                    if TQDM_AVAILABLE:
                        pbar.update(1)
                    elif paper_id % 10000 == 0:
                        print(f"已加载: {paper_id:,} 篇")
            
            if paper_id % 50000 == 0:
                gc.collect()
        
        if TQDM_AVAILABLE:
            pbar.close()
    
    def _detect_text_columns_once(self, sample_df: pd.DataFrame) -> List[str]:
        """一次遍历检测文本列"""
        text_columns = []
        
        for col in sample_df.columns:
            col_lower = str(col).lower()
            
            # 合并关键字检测和内容检测
            if any(kw in col_lower for kw in ['title', 'abstract', 'content', 'text', 'summary']):
                text_columns.append(col)
            elif sample_df[col].dtype == 'object':
                # 同时检查平均长度
                valid = sample_df[col].dropna().astype(str)
                if len(valid) > 0 and valid.str.len().mean() > 30:
                    text_columns.append(col)
        
        return text_columns[:3]
    
    def _unified_scan(self, text_chunks: Iterator[tuple]) -> tuple:
        """统一扫描 - 返回(词列表, 词-文档映射)"""
        all_tokens = []
        word_to_docs = {}
        
        pbar = tqdm(desc="✂️  分词扫描", unit="篇") if TQDM_AVAILABLE else None
        processed_count = 0
        
        for paper_id, chunk_text in text_chunks:
            cleaned_text = CLEAN_PATTERN.sub(' ', chunk_text.lower())
            
            doc_words = set()
            for match in UNIFIED_PATTERN.finditer(cleaned_text):
                token = next((g for g in match.groups() if g), None)
                
                if (token and token not in CORE_STOPWORDS and 
                    not token.isdigit() and 3 <= len(token) <= 20):
                    
                    if self.lemmatizer and token.isalpha():
                        if token in self.lemma_cache:
                            token = self.lemma_cache[token]
                        else:
                            try:
                                lemmatized = self.lemmatizer.lemmatize(token)
                                self.lemma_cache[token] = lemmatized
                                token = lemmatized
                            except:
                                self.lemma_cache[token] = token
                    
                    all_tokens.append(token)
                    doc_words.add(token)
            
            for word in doc_words:
                if word not in word_to_docs:
                    word_to_docs[word] = set()
                word_to_docs[word].add(paper_id)
            
            processed_count += 1
            if TQDM_AVAILABLE:
                pbar.update(1)
                pbar.set_postfix({'词数': f"{len(all_tokens):,}", '缓存': len(self.lemma_cache)})
            elif processed_count % 10000 == 0:
                print(f"已处理: {processed_count:,} 篇, 词数: {len(all_tokens):,}")
            
            if len(all_tokens) % 100000 == 0:
                gc.collect()
        
        if TQDM_AVAILABLE:
            pbar.close()
        
        return all_tokens, word_to_docs
    
    def _document_frequency_stats(self, domain_tokens: List[str], word_to_docs: Dict, 
                                   total_papers: int, stopwords_file: str, percentile: int = 85) -> List[Dict]:
        """文档频率统计 - 基于逆IDF的科学评分"""
        word_freq = Counter(domain_tokens)
        
        current_stopwords = self._load_stopwords(stopwords_file)
        
        candidates = [
            word for word, freq in word_freq.items()
            if freq >= MIN_FREQ and word not in current_stopwords
        ]
        
        if len(candidates) < 5:
            return []
        
        print(f"📊 计算文档频率: {len(candidates):,} 候选词")
        
        doc_ratios = []
        idfs = []
        
        iterator = tqdm(candidates, desc="📈 统计文档频率", unit="词") if TQDM_AVAILABLE else candidates
        
        for word in iterator:
            doc_freq = len(word_to_docs.get(word, set()))
            doc_ratio = doc_freq / total_papers
            doc_ratios.append(doc_ratio)
            
            idf = np.log(total_papers / max(doc_freq, 1))
            idfs.append(idf)
        
        doc_ratios_array = np.array(doc_ratios)
        idfs_array = np.array(idfs)
        adaptive_threshold = np.percentile(doc_ratios_array, percentile)
        max_idf = idfs_array.max() if len(idfs_array) > 0 else 1.0
        
        print(f"📊 文档占比统计: 最大={doc_ratios_array.max():.2%}, 平均={doc_ratios_array.mean():.2%}, {percentile}分位={adaptive_threshold:.2%}")
        print(f"🎯 自适应阈值: {adaptive_threshold:.2%}")
        
        results = []
        for i, word in enumerate(candidates):
            doc_ratio = doc_ratios[i]
            idf = idfs[i]
            total_freq = word_freq[word]
            
            if doc_ratio >= adaptive_threshold:
                # 停用词评分：文档占比 × 词频（越高越通用）
                score = doc_ratio * np.log1p(total_freq)
                
                results.append({
                    'word': word,
                    'score': float(score),
                    'doc_ratio': float(doc_ratio),
                    'idf': float(idf),
                    'freq': int(total_freq)
                })
        
        # 按文档占比排序（最通用的词在前）
        results.sort(key=lambda x: (x['doc_ratio'], x['freq']), reverse=True)
        return results
    
    def _load_stopwords(self, stopwords_file: str) -> Set[str]:
        """加载停用词"""
        stopwords = set()
        path = Path(stopwords_file)
        
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        word = line.strip().lower()
                        if word and not word.startswith('#'):
                            stopwords.add(word)
            except Exception:
                pass  # 静默失败
        
        return stopwords
    
    def _simple_filtering(self, candidates: List[Dict], max_words: int = None) -> List[str]:
        """简单筛选 - 按评分排序取前N个"""
        if not candidates:
            return []
        
        # 使用配置的数量或全部候选词
        if max_words is None:
            max_count = len(candidates)
        else:
            max_count = min(max_words, len(candidates))
        
        return [c['word'] for c in candidates[:max_count]]
    
    def _clean_output(self, new_stopwords: List[str], stopwords_file: str, output_file: str):
        """清洁输出 - 去重避免重复"""
        # 加载现有停用词
        existing = self._load_stopwords(stopwords_file)
        
        # 去重合并
        all_stopwords = sorted(existing.union(set(new_stopwords)))
        
        # 清洁写入（检查并删除现有文件）
        output_path = Path(output_file)
        if output_path.exists():
            output_path.unlink()
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"# Total: {len(all_stopwords)} (Original: {len(existing)}, New: {len(new_stopwords)})\n\n")
            for word in all_stopwords:
                f.write(f"{word}\n")

def main():
    """主程序 - 直接配置参数"""
    
    # ==================== 参数配置 ====================
    CSV_FILE_PATH = str(_ROOT / 'data' / 'raw' / '2025外文论文全字段.csv')
    if not Path(CSV_FILE_PATH).exists():
        CSV_FILE_PATH = '2025外文论文全字段.csv'
    STOPWORDS_FILE = str(_ROOT / 'config' / 'stopwords_en.txt')
    OUTPUT_FILE = str(_ROOT / 'config' / 'scientific_stopwords_doc_freq.txt')
    
    TEXT_COLUMNS = ['期刊名称', '标题', '关键词', 'KeywordsPlus', '摘要']
    
    MIN_WORD_FREQ = 50  # 降低词频阈值，获得更多候选词
    CHUNK_SIZE_CONFIG = 20000
    SAMPLE_SIZE = 50000  # 采样模式：仅处理5万篇（None=处理全部）
    MAX_STOPWORDS = None  # 输出停用词数量（None=全部候选词，推荐2500-3000）
    DOC_FREQ_PERCENTILE = 70  # 文档频率分位数阈值（70=前30%的词）
    # =============================================
    
    try:
        global MIN_FREQ, CHUNK_SIZE
        MIN_FREQ = MIN_WORD_FREQ
        CHUNK_SIZE = CHUNK_SIZE_CONFIG
        
        print(f"📄 输入文件: {CSV_FILE_PATH}")
        print(f"📝 停用词文件: {STOPWORDS_FILE}")
        print(f"💾 输出文件: {OUTPUT_FILE}")
        print(f"🔢 最小词频: {MIN_FREQ}")
        print(f"📊 处理模式: {'采样模式 ('+str(SAMPLE_SIZE)+' 篇)' if SAMPLE_SIZE else '完整CSV文件'}")
        print(f"📝 停用词数量: {'全部候选词' if MAX_STOPWORDS is None else MAX_STOPWORDS}")
        print(f"📈 文档频率阈值: {DOC_FREQ_PERCENTILE}分位（前{100-DOC_FREQ_PERCENTILE}%的词）")
        print("=" * 50)
        
        generator = RefinedGenerator(sample_size=SAMPLE_SIZE)
        generator.generate(CSV_FILE_PATH, STOPWORDS_FILE, OUTPUT_FILE, TEXT_COLUMNS, 
                         max_stopwords=MAX_STOPWORDS, doc_freq_percentile=DOC_FREQ_PERCENTILE)
        print("✅ 处理完成!")
        
    except Exception as e:
        print(f"❌ 处理失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()