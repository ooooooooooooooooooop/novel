"""
全局模型注册器（单例模式）
统一管理所有深度学习模型的加载
"""

import torch
import logging
from pathlib import Path
from typing import Optional

import spacy
from transformers import (
    AutoTokenizer, 
    AutoModelForSequenceClassification,
    AutoModelForTokenClassification,
    pipeline
)
from sentence_transformers import SentenceTransformer
from fastcoref import FCoref

logger = logging.getLogger(__name__)


class HuggingFaceSRLPredictor:
    """
    HuggingFace SRL 适配器，兼容 AllenNLP Predictor 接口
    
    使用 pakkinlau/bert-base-uncased-finetuned-advanced-srl_arg 模型
    输出格式与 AllenNLP SRL 格式兼容
    """
    
    def __init__(self, model, tokenizer, nlp, device):
        self.model = model
        self.tokenizer = tokenizer
        self.nlp = nlp
        self.device = device
    
    def _merge_hyphenated_words(self, words: list) -> list:
        """
        将连字符连接的词合并成一个token
        
        例如: ['state', '-', 'of', '-', 'the', '-', 'art'] -> ['state-of-the-art']
        
        参数:
            words: 原始分词列表
        
        返回:
            合并后的分词列表
        """
        if not words:
            return words
        
        merged = []
        i = 0
        while i < len(words):
            # 检查是否是连字符序列的开始
            if i < len(words) - 1 and words[i + 1] == '-':
                # 开始收集连字符序列
                sequence = [words[i]]
                j = i + 1
                while j < len(words):
                    if words[j] == '-':
                        sequence.append(words[j])
                        j += 1
                        # 如果下一个词存在，添加到序列
                        if j < len(words):
                            sequence.append(words[j])
                            j += 1
                        else:
                            break
                    else:
                        break
                
                # 如果序列包含连字符，合并它们
                if '-' in sequence:
                    merged_word = ''.join(sequence)
                    merged.append(merged_word)
                    i = j
                else:
                    merged.append(words[i])
                    i += 1
            else:
                merged.append(words[i])
                i += 1
        
        return merged
    
    def predict(self, sentence: str) -> dict:
        """
        预测句子的语义角色标注
        
        参数:
            sentence: 输入文本（可以是多个句子）
        
        返回:
            {
                'words': List[str],
                'verbs': [
                    {
                        'verb': str,
                        'description': str,
                        'tags': List[str],  # BIO标签，如 'B-ARG0', 'I-ARG0', 'O'
                        'words': List[str],
                        'confidence': float  # 模型置信度（0-1之间）
                    }
                ]
            }
        """
        # 先分句，对每个句子分别进行SRL预测
        doc = self.nlp(sentence)
        sentences = list(doc.sents)
        
        # 如果只有一个句子，直接处理
        if len(sentences) == 1:
            return self._predict_single_sentence(sentence, doc)
        
        # 多个句子：分别处理每个句子，然后按顺序合并结果
        all_words = []
        all_verbs = []
        
        for sent in sentences:
            sent_text = sent.text.strip()
            if not sent_text:
                continue
            
            # 对单个句子进行SRL预测
            sent_result = self._predict_single_sentence(sent_text, sent.as_doc())
            sent_words = sent_result.get('words', [])
            sent_verbs = sent_result.get('verbs', [])
            
            # 每个verb_frame的tags和words只对应它自己句子的words
            all_words.extend(sent_words)
            all_verbs.extend(sent_verbs)
        
        return {
            'words': all_words,
            'verbs': all_verbs
        }
    
    def _predict_single_sentence(self, sentence: str, doc=None) -> dict:
        """
        对单个句子进行SRL预测（内部方法）
        
        参数:
            sentence: 输入句子
            doc: 可选的spaCy doc对象（如果已解析）
        
        返回:
            与predict相同的格式
        """
        if doc is None:
            doc = self.nlp(sentence)
        words = [token.text for token in doc]
        
        # 合并连字符词（如 state-of-the-art）
        words = self._merge_hyphenated_words(words)
        
        # 检测动词候选（基于原始doc，但会在后续检查中过滤掉连词中的部分）
        verb_candidates = []
        for token in doc:
            if token.pos_ in {"VERB", "AUX"} and not token.is_stop:
                verb_candidates.append(token)
        
        if not verb_candidates:
            return {'words': words, 'verbs': []}
        
        verbs_results = []
        
        for verb_token in verb_candidates:
            verb_text = verb_token.text
            verb_idx = verb_token.idx
            
            # 找到动词在words中的索引
            verb_word_idx = None
            for word_idx, word in enumerate(words):
                if word == verb_text:
                    verb_word_idx = word_idx
                    break
            
            # 如果动词不在合并后的words中（可能是连词的一部分），跳过
            if verb_word_idx is None:
                continue
            
            if verb_idx >= 0:
                marked_sentence = sentence[:verb_idx] + "[V] " + sentence[verb_idx:]
            else:
                marked_sentence = sentence.replace(verb_text, f"[V] {verb_text}", 1)
            
            inputs = self.tokenizer(
                marked_sentence,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512,
                return_offsets_mapping=True
            )
            
            input_ids = inputs['input_ids'].to(self.device)
            attention_mask = inputs['attention_mask'].to(self.device)
            offset_mapping = inputs['offset_mapping'][0]
            tokenized_tokens_raw = self.tokenizer.convert_ids_to_tokens(input_ids[0])
            
            if verb_idx >= 0:
                v_marker_start = verb_idx
                v_marker_end = verb_idx + 4
            else:
                v_marker_start = marked_sentence.find("[V]")
                v_marker_end = v_marker_start + 4 if v_marker_start >= 0 else -1
            
            # 计算合并后words的字符范围
            # 需要在原始sentence中查找每个合并后的word的位置
            word_char_ranges = []
            search_start = 0
            for word_idx, word in enumerate(words):
                # 在sentence中查找word的位置（从search_start开始）
                word_pos = sentence.find(word, search_start)
                if word_pos == -1:
                    # 如果找不到，尝试不区分大小写
                    word_pos = sentence.lower().find(word.lower(), search_start)
                    if word_pos == -1:
                        # 如果还是找不到，使用估算位置
                        word_pos = search_start
                
                word_start = word_pos
                word_end = word_pos + len(word)
                word_char_ranges.append((word_start, word_end, word_idx))
                search_start = word_end
            
            word_ids = []
            for token_idx, (start, end) in enumerate(offset_mapping):
                token = tokenized_tokens_raw[token_idx]
                
                if token in ['[CLS]', '[SEP]', '[PAD]']:
                    word_ids.append(None)
                    continue
                
                if v_marker_start >= 0 and start >= v_marker_start and end <= v_marker_end:
                    word_ids.append(None)
                    continue
                
                if start < v_marker_start:
                    char_pos_in_original = start
                elif start > v_marker_end:
                    char_pos_in_original = start - 4
                else:
                    word_ids.append(None)
                    continue
                
                word_idx = None
                for word_start, word_end, idx in word_char_ranges:
                    token_center = char_pos_in_original + (end - start) // 2
                    if word_start <= token_center < word_end:
                        word_idx = idx
                        break
                    token_start_in_original = char_pos_in_original
                    token_end_in_original = char_pos_in_original + (end - start)
                    overlap = min(token_end_in_original, word_end) - max(token_start_in_original, word_start)
                    if overlap > 0:
                        word_idx = idx
                
                word_ids.append(word_idx)
            
            # 预测
            with torch.no_grad():
                outputs = self.model(
                    input_ids=input_ids,
                    attention_mask=attention_mask
                )
            
            predictions = torch.argmax(outputs.logits, dim=-1)[0]
            probs = torch.softmax(outputs.logits, dim=-1)[0]
            max_probs = torch.max(probs, dim=-1)[0]
            tokenized_tokens = self.tokenizer.convert_ids_to_tokens(input_ids[0])
            
            token_label_pairs = []
            for token_idx, (token, pred_id, max_prob) in enumerate(zip(tokenized_tokens, predictions, max_probs)):
                label = self.model.config.id2label.get(pred_id.item(), 'O')
                if label == '_':
                    label = 'O'
                word_idx = word_ids[token_idx] if token_idx < len(word_ids) else None
                
                if token in ['[CLS]', '[SEP]', '[PAD]']:
                    continue
                if token.startswith('[') and token.endswith(']'):
                    continue
                
                if word_idx is not None and word_idx == verb_word_idx:
                    continue
                
                if word_idx is not None:
                    token_label_pairs.append((token_idx, label, max_prob.item(), word_idx))
            
            aligned_tags = ['O'] * len(words)
            aligned_confidences = [0.0] * len(words)
            
            if verb_word_idx is not None:
                aligned_tags[verb_word_idx] = 'O'
                aligned_confidences[verb_word_idx] = 0.0
            
            word_token_labels = {}
            for token_idx, label, conf, word_idx in token_label_pairs:
                if word_idx == verb_word_idx:
                    continue
                if word_idx not in word_token_labels:
                    word_token_labels[word_idx] = []
                word_token_labels[word_idx].append((label, conf))
            
            for word_idx in range(len(words)):
                if word_idx == verb_word_idx:
                    continue
                if word_idx in word_token_labels:
                    labels_for_word = word_token_labels[word_idx]
                    non_o_labels = [(l, c) for l, c in labels_for_word if l != 'O']
                    if non_o_labels:
                        aligned_tags[word_idx] = non_o_labels[0][0]
                        aligned_confidences[word_idx] = non_o_labels[0][1]
                    elif labels_for_word:
                        aligned_tags[word_idx] = labels_for_word[0][0]
                        aligned_confidences[word_idx] = labels_for_word[0][1]
            
            non_o_confidences = [conf for tag, conf in zip(aligned_tags, aligned_confidences) 
                                 if tag != 'O' and not tag.startswith('_')]
            if non_o_confidences:
                verb_frame_confidence = sum(non_o_confidences) / len(non_o_confidences)
            elif aligned_confidences:
                verb_frame_confidence = sum(aligned_confidences) / len(aligned_confidences)
            else:
                verb_frame_confidence = 0.5
            
            verbs_results.append({
                'verb': verb_text,
                'description': marked_sentence,
                'tags': aligned_tags,
                'words': words,
                'confidence': verb_frame_confidence
            })
        
        return {
            'words': words,
            'verbs': verbs_results
        }


class ModelRegistry:
    """
    全局模型注册器（单例）
    
    所有模块通过此类获取预训练模型，避免重复加载
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, cache_dir: str = "./models/cached_models"):
        if self._initialized:
            return
        
        self._initialized = True
        if not Path(cache_dir).is_absolute():
            script_dir = Path(__file__).parent.parent
            self.cache_dir = (script_dir / cache_dir).resolve()
        else:
            self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self._nlp = None
        self._srl_predictor = None
        self._coref_predictor = None
        self._sentence_classifier = None
        self._sentence_tokenizer = None
        self._verb_inclusion_classifier = None
        self._verb_inclusion_tokenizer = None
        self._constraint_scene_classifier = None
        self._constraint_scene_tokenizer = None
        self._semantic_role_classifier = None
        self._semantic_role_tokenizer = None
        self._ner_model = None
        self._ner_tokenizer = None
        self._specter = None
        self._sentence_bert = None
        self._relation_extractor = None
        
        self._hf_srl_model = None
        self._hf_srl_tokenizer = None
    
    def get_nlp(self) -> spacy.language.Language:
        """加载 spaCy 模型"""
        if self._nlp is None:
            self._nlp = spacy.load('en_core_web_sm')
        return self._nlp
    
    def _get_hf_srl_model(self):
        """加载 HuggingFace SRL 模型"""
        if self._hf_srl_model is None or self._hf_srl_tokenizer is None:
            possible_paths = [
                self.cache_dir / "srl_finetuned",
                Path("./models/cached_models/srl_finetuned").resolve(),
                Path(__file__).parent.parent / "models" / "cached_models" / "srl_finetuned",
            ]
            
            finetuned_model_path = None
            for path in possible_paths:
                if path.exists() and (path / "config.json").exists():
                    finetuned_model_path = path
                    logger.info(f"找到微调模型: {finetuned_model_path}")
                    break
            
            if not finetuned_model_path:
                error_msg = "微调后的SRL模型不存在！请先运行 train_srl_model.py 训练模型。\n检查的路径：\n"
                for path in possible_paths:
                    exists = path.exists()
                    has_config = (path / "config.json").exists() if exists else False
                    error_msg += f"  {path}: 目录存在={exists}, config.json存在={has_config}\n"
                logger.error(error_msg)
                raise FileNotFoundError(error_msg)
            
            logger.info(f"加载微调后的SRL模型: {finetuned_model_path}")
            self._hf_srl_tokenizer = AutoTokenizer.from_pretrained(str(finetuned_model_path))
            self._hf_srl_model = AutoModelForTokenClassification.from_pretrained(str(finetuned_model_path))
            self._hf_srl_model.to(self.device)
            self._hf_srl_model.eval()
            logger.info(f"✓ 成功加载微调后的SRL模型")
        
        return self._hf_srl_model, self._hf_srl_tokenizer
    
    def get_srl_predictor(self):
        """
        加载语义角色标注模型
        
        返回 HuggingFaceSRLPredictor 适配器（兼容 AllenNLP 接口）
        """
        if self._srl_predictor is None:
            model, tokenizer = self._get_hf_srl_model()
            nlp = self.get_nlp()
            self._srl_predictor = HuggingFaceSRLPredictor(
                model=model,
                tokenizer=tokenizer,
                nlp=nlp,
                device=self.device
            )
        return self._srl_predictor
    
    def get_coref_predictor(self):
        """
        加载共指消解模型 (fastcoref)
        
        返回: FCoref 实例
        抛出: RuntimeError 如果模型加载失败
        """
        if self._coref_predictor is None:
            # 将 torch device 格式映射到 fastcoref 格式
            device = "cuda:0" if self.device == "cuda" else "cpu"
            
            try:
                self._coref_predictor = FCoref(device=device)
            except Exception as e:
                error_msg = f"Failed to load fastcoref model: {e}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
        
        return self._coref_predictor
    
    def get_sentence_classifier(self):
        """
        加载句子分类器（用于识别问题句/方法句等）
        
        注意：这里使用预训练的 SciBERT，实际使用时需要 fine-tune
        如果没有 fine-tuned 模型，会返回一个基础分类器
        """
        if self._sentence_classifier is None or self._sentence_tokenizer is None:
            # 尝试加载 fine-tuned 模型
            model_path = self.cache_dir / "sentence_classifier"
            
            if model_path.exists():
                # 使用自定义 fine-tuned 模型
                self._sentence_tokenizer = AutoTokenizer.from_pretrained(model_path)
                self._sentence_classifier = AutoModelForSequenceClassification.from_pretrained(model_path)
            else:
                # 使用预训练的 SciBERT（需要后续 fine-tune）
                logger.warning("Fine-tuned model not found, using base SciBERT")
                logger.warning("For production use, please fine-tune on labeled data")
                
                model_name = "allenai/scibert_scivocab_uncased"
                self._sentence_tokenizer = AutoTokenizer.from_pretrained(model_name)
                self._sentence_classifier = AutoModelForSequenceClassification.from_pretrained(
                    model_name,
                    num_labels=5,  # problem, method, result, background, other
                    ignore_mismatched_sizes=True
                )
            
            self._sentence_classifier.to(self.device)
        
        return self._sentence_classifier, self._sentence_tokenizer
    
    def get_verb_inclusion_classifier(self):
        """加载动词包含判断器"""
        if self._verb_inclusion_classifier is None or self._verb_inclusion_tokenizer is None:
            model_path = self.cache_dir / "verb_inclusion_classifier"
            
            if model_path.exists():
                self._verb_inclusion_tokenizer = AutoTokenizer.from_pretrained(model_path)
                self._verb_inclusion_classifier = AutoModelForSequenceClassification.from_pretrained(model_path)
            else:
                raise FileNotFoundError(
                    f"Verb inclusion classifier not found at {model_path}\n"
                    f"Please train it first: python train_verb_inclusion_classifier.py"
                )
            
            self._verb_inclusion_classifier.to(self.device)
        
        return self._verb_inclusion_classifier, self._verb_inclusion_tokenizer
    
    def get_ner_model(self):
        """加载科学文献 NER 模型"""
        if self._ner_model is None or self._ner_tokenizer is None:
            possible_paths = [
                self.cache_dir / "ner_finetuned",
                self.cache_dir / "ner_model",
            ]
            
            model_path = None
            for path in possible_paths:
                if path.exists():
                    model_path = path
                    break
            
            if model_path is not None:
                self._ner_tokenizer = AutoTokenizer.from_pretrained(model_path)
                self._ner_model = AutoModelForTokenClassification.from_pretrained(model_path)
            else:
                raise FileNotFoundError(
                    f"本地 NER fine-tuned 模型未找到。\n"
                    f"请先训练模型：python train_ner_finetuning.py\n"
                    f"预期路径：{self.cache_dir / 'ner_finetuned'}"
                )
            
            self._ner_model.to(self.device)
        
        return self._ner_model, self._ner_tokenizer
    
    def get_constraint_scene_classifier(self):
        """
        加载 Constraint/Scene 分类器
        
        用于判断候选短语是 constraint（限制/困难）还是 scene（应用场景/领域）
        返回: (model, tokenizer)
        """
        if self._constraint_scene_classifier is None or self._constraint_scene_tokenizer is None:
            model_path = self.cache_dir / "constraint_scene_classifier"
            
            if model_path.exists():
                self._constraint_scene_tokenizer = AutoTokenizer.from_pretrained(model_path)
                self._constraint_scene_classifier = AutoModelForSequenceClassification.from_pretrained(model_path)
            else:
                raise FileNotFoundError(
                    f"Constraint/scene classifier not found at {model_path}\n"
                    f"Please train it first: python train_constraint_scene_classifier.py"
                )
            
            self._constraint_scene_classifier.to(self.device)
            self._constraint_scene_classifier.eval()
        
        return self._constraint_scene_classifier, self._constraint_scene_tokenizer
    
    def get_semantic_role_classifier(self):
        """获取语义角色分类器"""
        if self._semantic_role_classifier is None or self._semantic_role_tokenizer is None:
            model_path = self.cache_dir / "semantic_role_classifier"
            
            if model_path.exists():
                self._semantic_role_tokenizer = AutoTokenizer.from_pretrained(model_path)
                self._semantic_role_classifier = AutoModelForSequenceClassification.from_pretrained(model_path)
            else:
                raise FileNotFoundError(
                    f"Semantic role classifier not found at {model_path}\n"
                    f"Please train it first: python train_semantic_role_classifier.py"
                )
            
            self._semantic_role_classifier.to(self.device)
            self._semantic_role_classifier.eval()
        
        return self._semantic_role_classifier, self._semantic_role_tokenizer
    
    def get_specter(self) -> SentenceTransformer:
        """加载 SPECTER"""
        if self._specter is None:
            self._specter = SentenceTransformer('allenai/specter')
        return self._specter
    
    def get_sentence_bert(self) -> SentenceTransformer:
        """加载通用 Sentence-BERT"""
        if self._sentence_bert is None:
            self._sentence_bert = SentenceTransformer('all-MiniLM-L6-v2')
        return self._sentence_bert
    
    def get_relation_extractor(self):
        """加载关系抽取模型"""
        if self._relation_extractor is None:
            try:
                self._relation_extractor = pipeline(
                    "text-classification",
                    model="allenai/scibert_scivocab_uncased",
                    device=0 if self.device == "cuda" else -1
                )
            except Exception as e:
                logger.warning(f"Failed to load relation extractor: {e}")
                self._relation_extractor = None
        
        return self._relation_extractor
    
    def preload_all(self):
        """预加载所有模型"""
        self.get_nlp()
        self.get_srl_predictor()
        self.get_coref_predictor()
        self.get_sentence_classifier()
        self.get_ner_model()
        self.get_specter()
        self.get_sentence_bert()
        self.get_relation_extractor()
    
    def clear_cache(self):
        """清空所有模型缓存（释放内存）"""
        self._nlp = None
        self._srl_predictor = None
        self._coref_predictor = None
        self._sentence_classifier = None
        self._ner_model = None
        self._specter = None
        self._sentence_bert = None
        self._relation_extractor = None
        self._hf_srl_model = None
        self._hf_srl_tokenizer = None
        
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


# 全局单例
_registry = ModelRegistry()

def get_registry() -> ModelRegistry:
    """获取全局模型注册器"""
    return _registry