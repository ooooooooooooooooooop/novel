
import torch
import spacy
import numpy as np
from fastcoref import FCoref
from sentence_transformers import CrossEncoder, SentenceTransformer
from typing import List, Dict, Any

class ResearchInsightMiner:
    def __init__(self, device: str = None):
        """
        初始化全流程 GPU 流水线
        """
        self.device = device if device else ('cuda' if torch.cuda.is_available() else 'cpu')
        print(f"⚡ System initialized on: {self.device.upper()}")

        # --- Module 1: Coref & Spacy ---
        print("Loading Module 1: Coreference Resolution & Segmentation...")
        self.coref_model = FCoref(device=self.device)
        
        try:
            spacy.require_gpu()
            self.nlp = spacy.load("en_core_web_trf")
        except:
            self.nlp = spacy.load("en_core_web_sm")

        # --- Module 2: NLI Engine ---
        print("Loading Module 2: DeBERTa-v3-Large NLI Engine...")
        self.nli_model = CrossEncoder('cross-encoder/nli-deberta-v3-large', device=self.device)
        
        self.hypotheses = {
            "AIM": "This study aims to investigate a specific problem or proposes a new method.",
            "CONCLUSION": "This sentence presents a key finding, result, or conclusion of the research.",
            "METHOD": "This sentence describes the methodology, dataset, or experimental setup."
        }

        # --- Module 3: Embeddings ---
        print("Loading Module 3: BGE-M3 Semantic Embeddings...")
        self.emb_model = SentenceTransformer('BAAI/bge-m3', device=self.device)
        
        self.anchors = {
            "AIM": self.emb_model.encode(["The objective is", "We propose", "The goal of this paper"], convert_to_tensor=True),
            "CONCLUSION": self.emb_model.encode(["Results show", "We conclude", "Therefore"], convert_to_tensor=True),
            "METHOD": self.emb_model.encode(["We utilized", "The dataset", "The experiment"], convert_to_tensor=True)
        }

        print("✅ All Systems Operational. Ready for Inference.")

    def _apply_coref(self, text: str) -> str:
        """
        【修复核心】手动应用共指消解
        1. 预测簇 (Predict Clusters)
        2. 倒序替换文本 (Reverse Substitution)
        """
        # 1. 获取预测结果
        preds = self.coref_model.predict(texts=[text])
        
        # 2. 获取簇的字符偏移量 (Indices)
        # 格式: [[(start, end), (start, end)], [...]]
        clusters = preds[0].get_clusters(as_strings=False)
        
        # 3. 构建替换列表
        replacements = []
        for cluster in clusters:
            # 策略: 取簇中第一个出现的词作为“本体” (通常是全称)
            # 例如 cluster: [(0, 10 "The Model"), (50, 52 "It")]
            # 我们把 "It" 替换为 "The Model"
            main_span = cluster[0] 
            main_text = text[main_span[0]:main_span[1]]
            
            # 对簇中剩余的词进行替换
            for mention_span in cluster[1:]:
                start, end = mention_span
                # 只有当是代词或短词时才替换，防止把 "The Algorithm" 替换成 "The Algorithm" (没必要)
                # 这里简单粗暴全替换，或者你可以加 len(mention) < 5 的判断
                replacements.append((start, end, main_text))
        
        # 4. 按起始位置倒序排序 (必须倒序，否则替换会破坏后续索引)
        replacements.sort(key=lambda x: x[0], reverse=True)
        
        # 5. 执行替换
        text_list = list(text)
        for start, end, new_str in replacements:
            # 简单的替换逻辑
            text_list[start:end] = list(new_str)
            
        return "".join(text_list)

    def _module_1_process_text(self, text: str) -> List[str]:
        """执行共指消解 + 智能分句"""
        # A. 共指消解 (修复后的调用)
        try:
            # 先清洗一下多余空格，防止 offset 对不上
            clean_input = " ".join(text.split())
            resolved_text = self._apply_coref(clean_input)
        except Exception as e:
            print(f"⚠️ Coref failed: {e}, utilizing raw text.")
            resolved_text = text
        
        # B. 清洗与分句
        doc = self.nlp(resolved_text)
        
        # 过滤长度 < 15 字符的噪音
        sentences = [sent.text.strip() for sent in doc.sents if len(sent.text.strip()) > 15]
        return sentences

    def _module_4_apply_rules(self, sentence: str) -> Dict[str, float]:
        s_lower = sentence.lower()
        boost = {"AIM": 0.0, "CONCLUSION": 0.0, "METHOD": 0.0}
        
        if any(k in s_lower for k in ["aim:", "goal:", "we propose", "in this paper"]):
            boost["AIM"] = 0.5
        if any(k in s_lower for k in ["conclude", "result", "showed that", "demonstrates"]):
            boost["CONCLUSION"] = 0.5
        if any(k in s_lower for k in ["using", "method", "dataset", "trained on"]):
            boost["METHOD"] = 0.3
        return boost

    def _module_2_3_compute_scores(self, sentences: List[str]):
        pairs = []
        map_idx = []
        keys = ["AIM", "CONCLUSION", "METHOD"]
        
        for i, sent in enumerate(sentences):
            for k in keys:
                pairs.append([sent, self.hypotheses[k]])
                map_idx.append((i, k))
        
        # NLI Inference
        nli_logits = self.nli_model.predict(pairs, batch_size=32, show_progress_bar=False)
        nli_probs = torch.softmax(torch.tensor(nli_logits), dim=1)[:, 1]
        
        # Embedding Inference
        sent_embs = self.emb_model.encode(sentences, convert_to_tensor=True)
        
        results_map = {i: {"AIM": {}, "CONCLUSION": {}, "METHOD": {}} for i in range(len(sentences))}
        
        for idx, score in enumerate(nli_probs):
            s_i, k = map_idx[idx]
            results_map[s_i][k]['nli'] = score.item()
            
        for k in keys:
            sims = torch.nn.functional.cosine_similarity(
                sent_embs.unsqueeze(1), self.anchors[k].unsqueeze(0), dim=2
            )
            max_sims, _ = torch.max(sims, dim=1)
            for i, sim_val in enumerate(max_sims):
                results_map[i][k]['sem'] = sim_val.item()
                
        return results_map

    def extract(self, raw_text: str, threshold: float = 0.75) -> List[Dict]:
        sentences = self._module_1_process_text(raw_text)
        if not sentences: return []

        scores_map = self._module_2_3_compute_scores(sentences)
        final_output = []

        for i, sent in enumerate(sentences):
            rules = self._module_4_apply_rules(sent)
            best_cat = None
            best_final_score = -1.0
            
            for cat in ["AIM", "CONCLUSION", "METHOD"]:
                nli_score = scores_map[i][cat]['nli']
                sem_score = scores_map[i][cat]['sem']
                rule_score = rules[cat]
                
                final_score = (nli_score * 0.7) + (max(0, sem_score) * 0.1) + rule_score
                
                # Position bias
                if i == 0 and cat == "AIM": final_score += 0.15
                if i == len(sentences)-1 and cat == "CONCLUSION": final_score += 0.15
                
                if final_score > best_final_score:
                    best_final_score = final_score
                    best_cat = cat
            
            if best_final_score >= threshold:
                final_output.append({
                    "id": i + 1,
                    "category": best_cat,
                    "confidence": round(best_final_score, 3),
                    "sentence": sent,
                    "original_nli_prob": round(scores_map[i][best_cat]['nli'], 3)
                })

        return final_output

# =======================================================
# 测试运行区
# =======================================================
if __name__ == "__main__":
    paper_abstract = """
Scientific Responsibility and Development We face many significant global challenges today;science and technology are essential elements in addressing all of these challenges. With the ability to make major contributions to development, the scientific community has a connected responsibility to do so, which fits closely with the core scientific goal of benefiting humanity. This article explores the meaning of scientific responsibility in relation to development, particularly within the global context.    """

    miner = ResearchInsightMiner()
    
    print("\n" + "="*60)
    print("Processing Abstract...")
    print("="*60)
    
    results = miner.extract(paper_abstract)
    
    for res in results:
        emoji = {"AIM": "🎯", "CONCLUSION": "💡", "METHOD": "⚙️"}
        print(f"{emoji.get(res['category'])} [{res['category']}] (Score: {res['confidence']})")
        print(f"   Sentence: \"{res['sentence']}\"")
        print("-" * 60)
