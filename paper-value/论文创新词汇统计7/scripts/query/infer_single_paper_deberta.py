# -*- coding: utf-8 -*-
"""
单篇论文 RPU 推理（DeBERTa）

使用示例：
    from infer_single_paper_deberta import extract_rpu_from_text
    
    title = "Machine Learning for Medical Diagnosis"
    abstract = "This paper presents a novel approach..."
    
    rpus = extract_rpu_from_text(title, abstract)
    for rpu in rpus:
        print(f"Task: {rpu['task']}, Object: {rpu['object']}")
"""
from scripts.legacy.rpu_full_extraction_deberta import DeBERTaExtractor, CONFIG
from typing import List, Dict, Optional

# 全局模型实例（延迟加载）
_extractor = None

def get_extractor():
    """获取或初始化 DeBERTa 抽取器（单例模式）"""
    global _extractor
    if _extractor is None:
        _extractor = DeBERTaExtractor()
    return _extractor

def extract_rpu_from_text(title: str, abstract: str, paper_id: str = "unknown") -> List[Dict]:
    """
    从标题和摘要提取 RPU
    
    Args:
        title: 论文标题
        abstract: 论文摘要
        paper_id: 论文 ID（可选）
    
    Returns:
        List[Dict]: RPU 结果列表，每个 RPU 包含：
            - sentence_index: 句子索引
            - task: Task 字段
            - object: Object 字段
            - aspect: Aspect 字段（可能为空）
            - context: Context 字段（可能为空）
    """
    extractor = get_extractor()
    
    # 1. 收集文本
    texts = []
    if title and title.strip():
        texts.append(title.strip())
    if abstract and abstract.strip():
        texts.append(abstract.strip())
    
    if not texts:
        return []
    
    # 2. 分句
    split_results = extractor.split_sentences(texts)
    
    all_sentences = []
    sentence_sources = []  # 记录每个句子来自 title(0) 还是 abstract(1)
    
    for text_idx, sentences in enumerate(split_results):
        for sent in sentences:
            all_sentences.append(sent)
            sentence_sources.append(text_idx)
    
    if not all_sentences:
        return []
    
    # 3. 批量推理
    inference_results = extractor.infer_batch(all_sentences)
    
    # 4. 提取 RPU
    rpus = []
    for sent_idx, result in enumerate(inference_results):
        rpu = extractor.extract_rpu(paper_id, sent_idx, result)
        if rpu:
            rpus.append({
                "sentence_index": rpu.sentence_index,
                "task": rpu.task,
                "object": rpu.object,
                "aspect": rpu.aspect,
                "context": rpu.context,
                "source": "title" if sentence_sources[sent_idx] == 0 else "abstract"
            })
    
    return rpus

def extract_rpu_from_text_batch(titles_abstracts: List[Dict[str, str]]) -> List[List[Dict]]:
    """
    批量推理多篇论文
    
    Args:
        titles_abstracts: [{"title": "...", "abstract": "...", "paper_id": "..."}, ...]
    
    Returns:
        List[List[Dict]]: 每篇论文的 RPU 列表
    """
    extractor = get_extractor()
    
    all_texts = []
    text_to_paper = []  # (paper_idx, is_title)
    
    for paper_idx, paper in enumerate(titles_abstracts):
        title = paper.get("title", "").strip()
        abstract = paper.get("abstract", "").strip()
        
        if title:
            all_texts.append(title)
            text_to_paper.append((paper_idx, True))
        if abstract:
            all_texts.append(abstract)
            text_to_paper.append((paper_idx, False))
    
    if not all_texts:
        return [[] for _ in titles_abstracts]
    
    # 分句
    split_results = extractor.split_sentences(all_texts)
    
    all_sentences = []
    sentence_map = []  # (paper_idx, local_sent_idx)
    paper_sentence_counts = [0] * len(titles_abstracts)
    
    for text_idx, (paper_idx, is_title) in enumerate(text_to_paper):
        sentences = split_results[text_idx]
        for sent in sentences:
            all_sentences.append(sent)
            sentence_map.append((paper_idx, paper_sentence_counts[paper_idx]))
            paper_sentence_counts[paper_idx] += 1
    
    # 批量推理
    batch_size = CONFIG["batch_size"]
    all_rpus = [[] for _ in titles_abstracts]
    
    for batch_start in range(0, len(all_sentences), batch_size):
        batch_end = min(batch_start + batch_size, len(all_sentences))
        batch_sentences = all_sentences[batch_start:batch_end]
        
        inference_results = extractor.infer_batch(batch_sentences)
        
        for i, result in enumerate(inference_results):
            sent_idx = batch_start + i
            paper_idx, local_sent_idx = sentence_map[sent_idx]
            paper_id = titles_abstracts[paper_idx].get("paper_id", f"paper_{paper_idx}")
            
            rpu = extractor.extract_rpu(paper_id, local_sent_idx, result)
            if rpu:
                all_rpus[paper_idx].append({
                    "sentence_index": rpu.sentence_index,
                    "task": rpu.task,
                    "object": rpu.object,
                    "aspect": rpu.aspect,
                    "context": rpu.context
                })
    
    return all_rpus


# ============================================================
# 命令行测试
# ============================================================
if __name__ == "__main__":
    # 示例 1: 单篇论文
    print("=" * 70)
    print("示例 1: 单篇论文推理")
    print("=" * 70)
    
    title = "Plasma 25-Hydroxyvitamin D Levels and Fracture Risk in a Community-Based Cohort of Elderly Men in Sweden"
    abstract = """
Context: Blood levels of 25-hydroxyvitamin D [25(OH) D] is the generally accepted indicator of vitamin D status, but no universal reference level has been reached. Objective: The objective of the study was to determine the threshold at which low plasma 25(OH) D levels are associated with fractures in elderly men and clarify the importance of low levels on total fracture burden. Design and Participants: In the Uppsala Longitudinal Study of Adult Men, a population-based cohort (mean age, 71 yr, n = 1194), we examined the relationship between 25(OH) D and risk for fracture. Plasma 25(OH) D levels were measured with high-pressure liquid chromatography-mass spectrometry. Setting: The study was conducted in the municipality of Uppsala in Sweden, a country with a high fracture incidence. Main Outcome Measure: Time to fracture was measured. Results: During follow-up (median 11 yr), 309 of the participants (26%) sustained a fracture. 25(OH) D levels below 40 nmol/liter, which corresponded to the fifth percentile of 25(OH) D, were associated with a modestly increased risk for fracture, multivariable-adjusted hazard ratio 1.65 (95% confidence interval 1.09-2.49). No risk difference was detected above this level. Approximately 3% of the fractures were attributable to low 25(OH) D levels in this population. Conclusions: Vitamin D insufficiency is not a major cause of fractures in community-dwelling elderly men in Sweden. Despite the fact that cutaneous synthesis of previtamin D during the winter season is undetectable at this northern latitude of 60 degrees, only one in 20 had 25(OH) D levels below 40 nmol/liter, the threshold at which the risk for fracture started to increase. Genetic adaptations to limited UV light may be an explanation for our findings. (J Clin Endocrinol Metab 95: 2637-2645, 2010)

    """
    
    rpus = extract_rpu_from_text(title, abstract, paper_id="test_001")
    
    print(f"\n标题: {title}")
    print(f"摘要: {abstract[:100]}...")
    print(f"\n提取到 {len(rpus)} 个 RPU:\n")
    
    for i, rpu in enumerate(rpus, 1):
        print(f"RPU {i} (句子 {rpu['sentence_index']}, 来源: {rpu['source']}):")
        print(f"  Task: {rpu['task']}")
        print(f"  Object: {rpu['object']}")
        if rpu['aspect']:
            print(f"  Aspect: {rpu['aspect']}")
        if rpu['context']:
            print(f"  Context: {rpu['context']}")
        print()
    
    # # 示例 2: 批量推理
    # print("\n" + "=" * 70)
    # print("示例 2: 批量推理")
    # print("=" * 70)
    
    # papers = [
    #     {
    #         "paper_id": "paper_001",
    #         "title": "Machine Learning Applications",
    #         "abstract": "We propose a novel machine learning method for classification."
    #     },
    #     {
    #         "paper_id": "paper_002",
    #         "title": "Neural Networks",
    #         "abstract": "This study investigates the performance of neural networks."
    #     }
    # ]
    
    # batch_results = extract_rpu_from_text_batch(papers)
    
    # for paper_idx, rpus in enumerate(batch_results):
    #     print(f"\n论文 {paper_idx + 1} ({papers[paper_idx]['paper_id']}): {len(rpus)} 个 RPU")
    #     for rpu in rpus[:3]:  # 只显示前 3 个
    #         print(f"  - Task: {rpu['task'][:50]}... | Object: {rpu['object'][:50]}...")
